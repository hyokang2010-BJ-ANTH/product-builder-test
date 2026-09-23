"""원내(on-premise) 웹 앱: 브라우저에서 각도별 사진을 올리면 3D 모델과 분석 결과를 만든다.

    python -m afs3d serve            # http://127.0.0.1:8765 에서 열림

- 표준 라이브러리만 사용 (추가 설치 없음). 사진은 이 PC 의 --data-dir 밖으로 나가지 않는다.
- 파일은 한 장씩 PUT 으로 받는다 (multipart 파싱 불필요, 장별 진행률 표시 가능).
- 작업은 큐에 쌓여 한 번에 하나씩 `python -m afs3d run` 하위 프로세스로 처리된다 (GPU 는 한 개).
- 기본은 이 PC 에서만 접속 가능(127.0.0.1). 원내 다른 PC 에서 쓰려면 --host 0.0.0.0 을 주면
  접속 토큰이 자동 생성되어 그 토큰이 있는 주소로만 접근할 수 있다.
"""
from __future__ import annotations

import json
import mimetypes
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .io_utils import IMAGE_EXTS

PROJECT_DIR = Path(__file__).resolve().parents[1]  # `python -m afs3d` 가 동작하는 폴더
WEB_DIR = PROJECT_DIR / "web"
MAX_FILE_BYTES = 300 * 1024 * 1024
LOG_LINES = 400

# (COLMAP 단계 또는 출력 문구, 화면 표시 이름, 진행률 %)
STAGES = [
    ("전처리 완료", "전처리 완료", 10),
    ("feature_extractor", "특징점 추출", 15),
    ("_matcher", "사진 간 매칭", 30),
    ("mapper", "카메라 위치 추정", 55),
    ("point_triangulator", "3D 점 삼각측량", 55),
    ("model_converter", "모델 정리", 65),
    ("image_undistorter", "조밀 재구성 준비", 70),
    ("patch_match_stereo", "조밀 재구성 (깊이 추정)", 75),
    ("stereo_fusion", "점군 융합", 88),
    ("poisson_mesher", "메쉬 생성", 93),
    ("두피 ROI 면적", "탈모 면적 분석", 98),
]

# 결과로 내려줄 수 있는 파일 (작업 폴더 기준 상대경로)
RESULT_FILES = {
    "sparse.ply": "work/sparse.ply",
    "coverage.ply": "work/analysis/coverage.ply",
    "top_view.png": "work/analysis/top_view.png",
    "report.json": "work/analysis/report.json",
    "reconstruction.json": "work/reconstruction.json",
    "quality.csv": "work/quality.csv",
    "mesh.ply": "work/dense/meshed-poisson.ply",
}

_SAFE_NAME = re.compile(r"[^0-9A-Za-z가-힣._ ()+-]+")  # manifest.csv 의 파일명과 맞도록 공백·괄호는 유지


def safe_filename(name: str) -> str | None:
    """경로 요소를 버리고 허용 문자만 남긴다. 허용 확장자가 아니면 None."""
    base = Path(unquote(name).replace("\\", "/")).name
    base = _SAFE_NAME.sub("_", base).strip().lstrip(".")
    if not base:
        return None
    ext = Path(base).suffix.lower()
    if ext in IMAGE_EXTS or ext in (".csv", ".zip"):
        return base
    return None


@dataclass
class JobOptions:
    label: str = ""
    mode: str = "sfm"
    mask: bool = True
    dense: bool = False
    rig_radius_mm: float | None = None
    drop_flagged: bool = False
    max_side: int = 3200

    @classmethod
    def from_dict(cls, d: dict) -> "JobOptions":
        o = cls()
        o.label = str(d.get("label", ""))[:80]
        o.mode = "rig" if d.get("mode") == "rig" else "sfm"
        o.mask = bool(d.get("mask", True))
        o.dense = bool(d.get("dense", False))
        r = d.get("rig_radius_mm")
        o.rig_radius_mm = float(r) if r not in (None, "") and float(r) > 0 else None
        o.drop_flagged = bool(d.get("drop_flagged", False))
        o.max_side = int(d.get("max_side", 3200) or 0)
        return o


@dataclass
class Job:
    id: str
    created: float
    options: JobOptions
    status: str = "uploading"  # uploading | queued | running | done | failed | cancelled
    stage: str = "사진 업로드"
    progress: int = 0
    n_images: int = 0
    error: str = ""
    finished: float | None = None
    results: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["options"] = asdict(self.options)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        d = dict(d)
        d["options"] = JobOptions(**d["options"])
        return cls(**d)


def build_command(job_dir: Path, opts: JobOptions) -> list[str]:
    cmd = [sys.executable, "-m", "afs3d", "run", "--images", str(job_dir / "upload"),
           "--work", str(job_dir / "work"), "--mode", opts.mode, "--max-side", str(opts.max_side)]  # fmt: skip
    if (job_dir / "manifest.csv").exists():
        cmd += ["--manifest", str(job_dir / "manifest.csv")]
    if opts.mask:
        cmd.append("--mask")
    if opts.dense:
        cmd.append("--dense")
    if opts.drop_flagged:
        cmd.append("--drop-flagged")
    if opts.rig_radius_mm:
        cmd += ["--rig-radius-mm", str(opts.rig_radius_mm)]
    return cmd


def stage_for_line(line: str) -> tuple[str, int] | None:
    for key, label, pct in STAGES:
        if key in line:
            return label, pct
    return None


class JobManager:
    def __init__(self, data_dir: str | Path, command_builder=build_command):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.lock = threading.RLock()
        self.queue: queue.Queue[str] = queue.Queue()
        self.procs: dict[str, subprocess.Popen] = {}
        self.command_builder = command_builder
        self._load()
        threading.Thread(target=self._worker, daemon=True, name="afs3d-worker").start()

    # ---------- 저장 ----------
    def job_dir(self, job_id: str) -> Path:
        return self.data_dir / job_id

    def _save(self, job: Job) -> None:
        p = self.job_dir(job.id) / "job.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)

    def _load(self) -> None:
        for p in sorted(self.data_dir.glob("*/job.json")):
            try:
                job = Job.from_dict(json.loads(p.read_text(encoding="utf-8")))
            except (ValueError, TypeError, KeyError):
                continue
            if job.status in ("running", "queued"):
                job.status, job.error = "failed", "서버가 재시작되어 작업이 중단되었습니다. 다시 시작하세요."
                self._save(job)
            self.jobs[job.id] = job

    # ---------- 작업 ----------
    def create(self, options: dict) -> Job:
        job_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        (self.job_dir(job_id) / "upload").mkdir(parents=True)
        job = Job(id=job_id, created=time.time(), options=JobOptions.from_dict(options))
        with self.lock:
            self.jobs[job_id] = job
            self._save(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)

    def add_file(self, job: Job, name: str, body_iter, length: int) -> int:
        """업로드 파일 저장. zip 이면 이미지(와 manifest.csv)를 풀어 넣는다. 저장된 이미지 수를 반환."""
        if job.status != "uploading":
            raise ValueError("이미 시작된 작업에는 사진을 추가할 수 없습니다")
        fname = safe_filename(name)
        if not fname:
            raise ValueError(f"허용되지 않는 파일 형식입니다: {name} (jpg/png/tif, manifest.csv, zip)")
        if length > MAX_FILE_BYTES:
            raise ValueError("파일이 너무 큽니다 (최대 300MB)")
        d = self.job_dir(job.id)
        is_manifest = fname.lower().endswith(".csv")
        dest = d / "manifest.csv" if is_manifest else d / "upload" / fname
        tmp = dest.with_name(dest.name + ".part")
        with open(tmp, "wb") as f:
            for chunk in body_iter:
                f.write(chunk)
        if fname.lower().endswith(".zip"):
            try:
                added = self._extract_zip(tmp, d)
            finally:
                tmp.unlink(missing_ok=True)
        else:
            tmp.replace(dest)
            added = 0 if is_manifest else 1
        with self.lock:
            job.n_images = sum(1 for p in (d / "upload").iterdir() if p.suffix.lower() in IMAGE_EXTS)
            self._save(job)
        return added

    def _extract_zip(self, zpath: Path, d: Path) -> int:
        n = 0
        try:
            zf = zipfile.ZipFile(zpath)
        except zipfile.BadZipFile as e:
            raise ValueError("zip 파일을 열 수 없습니다") from e
        with zf:
            for info in zf.infolist():
                if info.is_dir() or info.file_size > MAX_FILE_BYTES:
                    continue
                fname = safe_filename(info.filename)
                if not fname or fname.lower().endswith(".zip") or Path(info.filename).name.startswith("._"):
                    continue
                dest = d / "manifest.csv" if fname.lower().endswith(".csv") else d / "upload" / fname
                with zf.open(info) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                n += dest.parent.name == "upload"
        return n

    def start(self, job: Job) -> None:
        with self.lock:
            if job.status not in ("uploading", "failed", "cancelled"):
                raise ValueError("이미 진행 중이거나 끝난 작업입니다")
            if job.n_images < 3:
                raise ValueError("사진이 3장 이상 필요합니다 (권장 60장 이상)")
            job.status, job.stage, job.progress, job.error = "queued", "대기 중", 0, ""
            self._save(job)
        self.queue.put(job.id)

    def cancel(self, job: Job) -> None:
        with self.lock:
            proc = self.procs.get(job.id)
            if proc and proc.poll() is None:
                proc.terminate()
            if job.status in ("queued", "running", "uploading"):
                job.status, job.stage = "cancelled", "취소됨"
                self._save(job)

    def delete(self, job: Job) -> None:
        self.cancel(job)
        with self.lock:
            self.jobs.pop(job.id, None)
        shutil.rmtree(self.job_dir(job.id), ignore_errors=True)

    def log_tail(self, job: Job, n: int = LOG_LINES) -> list[str]:
        p = self.job_dir(job.id) / "run.log"
        if not p.exists():
            return []
        return p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]

    # ---------- 실행 ----------
    def _worker(self) -> None:
        while True:
            job_id = self.queue.get()
            job = self.jobs.get(job_id)
            if job is None or job.status != "queued":
                continue
            try:
                self._run(job)
            except Exception as e:  # 워커 스레드가 죽지 않도록
                with self.lock:
                    job.status, job.error = "failed", f"내부 오류: {e}"
                    self._save(job)

    def _run(self, job: Job) -> None:
        d = self.job_dir(job.id)
        shutil.rmtree(d / "work", ignore_errors=True)
        cmd = self.command_builder(d, job.options)
        with self.lock:
            job.status, job.stage, job.progress = "running", "전처리 중 (색·노출 보정, 배경 제거)", 2
            self._save(job)
        with open(d / "run.log", "w", encoding="utf-8") as log:
            log.write("$ " + " ".join(cmd) + "\n")
            log.flush()
            proc = subprocess.Popen(cmd, cwd=PROJECT_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, env=_child_env())  # fmt: skip
            self.procs[job.id] = proc
            for line in proc.stdout:
                log.write(line)
                log.flush()
                st = stage_for_line(line)
                if st:
                    with self.lock:
                        job.stage, job.progress = st[0], max(job.progress, st[1])
                        self._save(job)
            code = proc.wait()
            self.procs.pop(job.id, None)
        with self.lock:
            if job.status == "cancelled":
                return
            job.results = {k: v for k, v in RESULT_FILES.items() if (d / v).exists()}
            job.summary = self._summary(d)
            job.finished = time.time()
            if code == 0:
                job.status, job.stage, job.progress = "done", "완료", 100
            else:
                job.status = "failed"
                tail = [ln for ln in self.log_tail(job, 40) if ln.strip()]
                job.error = tail[-1] if tail else f"종료 코드 {code}"
            self._save(job)

    @staticmethod
    def _summary(d: Path) -> dict:
        s: dict = {}
        rj = d / "work" / "reconstruction.json"
        if rj.exists():
            r = json.loads(rj.read_text(encoding="utf-8"))
            for k in ("mode", "n_input", "n_registered", "scale_mm_per_unit", "up", "front", "camera_centers",
                      "dense_skipped", "rig_fit"):  # fmt: skip
                if k in r:
                    s[k] = r[k]
        rep = d / "work" / "analysis" / "report.json"
        if rep.exists():
            s["report"] = json.loads(rep.read_text(encoding="utf-8"))["report"]
        return s


def _child_env() -> dict:
    import os

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"  # 진행 단계를 실시간으로 받기 위해
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return env


class _Body:
    """요청 본문을 1MB 씩 읽는 반복자. 남은 바이트 수를 기억해 오류 시 정확히 그만큼만 버린다."""

    def __init__(self, rfile, length: int, size: int = 1 << 20):
        self.rfile, self.left, self.size = rfile, length, size

    def __iter__(self):
        while self.left > 0:
            chunk = self.rfile.read(min(self.size, self.left))
            if not chunk:
                self.left = 0
                break
            self.left -= len(chunk)
            yield chunk

    def drain(self) -> None:
        for _ in self:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = "afs3d"
    manager: JobManager
    token: str | None = None

    def log_message(self, fmt, *args):  # 요청마다 콘솔에 찍지 않는다
        pass

    # ---------- 공통 ----------
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _error(self, code: int, msg: str) -> None:
        self._json({"error": msg}, code)

    def _authorized(self) -> bool:
        if not self.token:
            return True
        q = parse_qs(urlparse(self.path).query)
        got = self.headers.get("X-Afs3d-Token") or (q.get("token") or [""])[0]
        if not got:
            cookie = self.headers.get("Cookie", "")
            m = re.search(r"afs3d_token=([0-9a-f]+)", cookie)
            got = m.group(1) if m else ""
        return secrets.compare_digest(got, self.token)

    def _route(self) -> tuple[list[str], dict]:
        u = urlparse(self.path)
        return [unquote(p) for p in u.path.split("/") if p], parse_qs(u.query)

    def _job(self, job_id: str) -> Job | None:
        job = self.manager.get(job_id)
        if job is None:
            self._error(404, "작업을 찾을 수 없습니다")
        return job

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ValueError("요청이 너무 큽니다")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw or b"{}")

    # ---------- 메서드 ----------
    def do_GET(self):
        if not self._authorized():
            return self._error(401, "접속 토큰이 필요합니다. 서버를 켠 PC 의 콘솔에 표시된 주소로 접속하세요.")
        parts, _ = self._route()
        if not parts or parts[0] in ("index.html",):
            return self._static("index.html", set_cookie=True)
        if parts[0] == "static" and len(parts) >= 2:
            return self._static("/".join(parts[1:]))
        if parts[:2] == ["api", "jobs"]:
            if len(parts) == 2:
                return self._json([_public(j, self.manager) for j in self.manager.list()])
            job = self._job(parts[2])
            if not job:
                return
            if len(parts) == 3:
                d = _public(job, self.manager, detail=True)
                return self._json(d)
            if len(parts) == 5 and parts[3] == "results":
                return self._result(job, parts[4])
        self._error(404, "없는 주소입니다")

    do_HEAD = do_GET

    def do_POST(self):
        if not self._authorized():
            return self._error(401, "접속 토큰이 필요합니다")
        parts, _ = self._route()
        try:
            if parts == ["api", "jobs"]:
                job = self.manager.create(self._read_body())
                return self._json(_public(job, self.manager), 201)
            if len(parts) == 4 and parts[:2] == ["api", "jobs"]:
                job = self._job(parts[2])
                if not job:
                    return
                if parts[3] == "start":
                    self.manager.start(job)
                    return self._json(_public(job, self.manager))
                if parts[3] == "cancel":
                    self.manager.cancel(job)
                    return self._json(_public(job, self.manager))
        except (ValueError, json.JSONDecodeError) as e:
            return self._error(400, str(e))
        self._error(404, "없는 주소입니다")

    def do_PUT(self):
        if not self._authorized():
            return self._error(401, "접속 토큰이 필요합니다")
        parts, _ = self._route()
        if len(parts) == 5 and parts[:2] == ["api", "jobs"] and parts[3] == "files":
            job = self._job(parts[2])
            if not job:
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = _Body(self.rfile, length)
            try:
                added = self.manager.add_file(job, parts[4], body, length)
            except ValueError as e:
                body.drain()  # 남은 본문을 버려야 응답이 정상 전달된다
                return self._error(400, str(e))
            return self._json({"added": added, "n_images": job.n_images})
        self._error(404, "없는 주소입니다")

    def do_DELETE(self):
        if not self._authorized():
            return self._error(401, "접속 토큰이 필요합니다")
        parts, _ = self._route()
        if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
            job = self._job(parts[2])
            if job:
                self.manager.delete(job)
                self._json({"deleted": job.id})
            return
        self._error(404, "없는 주소입니다")

    # ---------- 파일 ----------
    def _static(self, rel: str, set_cookie: bool = False) -> None:
        p = (WEB_DIR / rel).resolve()
        if not p.is_file() or WEB_DIR.resolve() not in p.parents:
            return self._error(404, "없는 파일입니다")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"
        extra = {}
        if set_cookie and self.token:
            extra["Set-Cookie"] = f"afs3d_token={self.token}; Path=/; HttpOnly; SameSite=Strict"
        self._send(200, p.read_bytes(), ctype, extra)

    def _result(self, job: Job, key: str) -> None:
        rel = RESULT_FILES.get(key)
        p = self.manager.job_dir(job.id) / rel if rel else None
        if not p or not p.is_file():
            return self._error(404, "결과 파일이 없습니다")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        self._send(200, p.read_bytes(), ctype, {"Content-Disposition": f'inline; filename="{job.id}-{key}"'})


def _public(job: Job, mgr: JobManager, detail: bool = False) -> dict:
    d = job.to_dict()
    if not detail:
        d["summary"] = {k: v for k, v in job.summary.items() if k != "camera_centers"}
    else:
        d["log"] = mgr.log_tail(job, 200)
        up = mgr.job_dir(job.id) / "upload"
        d["files"] = sorted(p.name for p in up.iterdir()) if up.exists() else []
        d["has_manifest"] = (mgr.job_dir(job.id) / "manifest.csv").exists()
    return d


def serve(host: str = "127.0.0.1", port: int = 8765, data_dir: str | Path = "jobs", token: str | None = None):
    local = host in ("127.0.0.1", "localhost", "::1")
    if not local and token is None:
        token = secrets.token_hex(16)
    Handler.manager = JobManager(data_dir)
    Handler.token = token
    httpd = ThreadingHTTPServer((host, port), Handler)
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{port}/" + (f"?token={token}" if token else "")
    print(f"AFS 3D 서버 실행 중 → {url}")
    print(f"작업 데이터 폴더: {Path(data_dir).resolve()}  (환자 사진이 저장됩니다. 외부 공유·커밋 금지)")
    if not local:
        print("원내 다른 PC 에서는 위 주소의 127.0.0.1 을 이 PC 의 IP 로 바꿔 접속하세요 (토큰 포함).")
    print("종료: Ctrl+C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return httpd
