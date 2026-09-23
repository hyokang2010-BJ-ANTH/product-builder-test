import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

import pytest

from afs3d import server as srv

FAKE_PIPELINE = r"""
import json, pathlib, sys
job = pathlib.Path(sys.argv[1])
print("전처리 완료", flush=True)
print("$ colmap feature_extractor", flush=True)
print("$ colmap mapper", flush=True)
w = job / "work"; (w / "analysis").mkdir(parents=True, exist_ok=True)
(w / "sparse.ply").write_text("ply")
(w / "reconstruction.json").write_text(json.dumps({"n_input": 3, "n_registered": 3, "up": [0, 0, 1]}))
if len(sys.argv) > 2:
    sys.exit(3)
"""


def fake_builder(fail=False):
    def build(job_dir, opts):
        return [sys.executable, "-c", FAKE_PIPELINE, str(job_dir)] + (["fail"] if fail else [])

    return build


@pytest.fixture
def app(tmp_path):
    def start(token=None, fail=False):
        srv.Handler.manager = srv.JobManager(tmp_path / "jobs", command_builder=fake_builder(fail))
        srv.Handler.token = token
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    started = []
    yield start
    for h in started:
        h.shutdown()
        h.server_close()


def call(url, method="GET", data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read()
            return r.status, (json.loads(body) if r.headers.get_content_type() == "application/json" else body)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def wait_status(base, job_id, want, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        _, j = call(f"{base}/api/jobs/{job_id}")
        if j["status"] in want:
            return j
        time.sleep(0.1)
    raise AssertionError(f"작업이 {want} 가 되지 않음: {j['status']}")


def test_safe_filename():
    assert srv.safe_filename("../../etc/passwd") is None
    assert srv.safe_filename("..%2F..%2Fx.jpg") == "x.jpg"
    assert srv.safe_filename("C:\\photos\\afs 001.JPG") == "afs 001.JPG"
    assert srv.safe_filename("manifest.csv") == "manifest.csv"
    assert srv.safe_filename("evil.sh") is None
    assert srv.safe_filename(".hidden.jpg") == "hidden.jpg"


def test_stage_mapping():
    assert srv.stage_for_line("$ colmap exhaustive_matcher --database_path x") == ("사진 간 매칭", 30)
    assert srv.stage_for_line("두피 ROI 면적 12.0 cm²") == ("탈모 면적 분석", 98)
    assert srv.stage_for_line("아무 출력") is None


def test_build_command_options(tmp_path):
    (tmp_path / "manifest.csv").write_text("filename\n")
    opts = srv.JobOptions.from_dict({"mode": "rig", "dense": True, "rig_radius_mm": "450", "mask": False})
    cmd = srv.build_command(tmp_path, opts)
    assert cmd[1:4] == ["-m", "afs3d", "run"]
    assert "--dense" in cmd and "--mask" not in cmd
    assert cmd[cmd.index("--rig-radius-mm") + 1] == "450.0"
    assert cmd[cmd.index("--manifest") + 1].endswith("manifest.csv")


def test_upload_run_and_results(app):
    base = app()
    code, page = call(base + "/")
    assert code == 200 and b"AFS 3D" in page
    code, job = call(base + "/api/jobs", "POST", json.dumps({"label": "차트 123", "rig_radius_mm": 450}).encode())
    assert code == 201 and job["status"] == "uploading"
    jid = job["id"]

    for i in range(2):
        code, r = call(f"{base}/api/jobs/{jid}/files/img_{i}.jpg", "PUT", b"\xff\xd8fakejpeg")
        assert code == 200
    code, r = call(f"{base}/api/jobs/{jid}/start", "POST")
    assert code == 400 and "3장" in r["error"]  # 너무 적으면 시작 거부

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("set/img_2.jpg", b"\xff\xd8x")
        z.writestr("set/manifest.csv", "filename\nimg_0.jpg\n")
        z.writestr("__MACOSX/set/._img_2.jpg", b"junk")
        z.writestr("set/readme.txt", "x")
    code, r = call(f"{base}/api/jobs/{jid}/files/set.zip", "PUT", buf.getvalue())
    assert code == 200 and r["n_images"] == 3

    code, r = call(f"{base}/api/jobs/{jid}/files/run.sh", "PUT", b"#!/bin/sh")
    assert code == 400

    code, _ = call(f"{base}/api/jobs/{jid}/start", "POST")
    assert code == 200
    j = wait_status(base, jid, {"done", "failed"})
    assert j["status"] == "done", j
    assert j["progress"] == 100 and j["has_manifest"]
    assert j["summary"]["n_registered"] == 3
    assert "sparse.ply" in j["results"]
    assert any("feature_extractor" in ln for ln in j["log"])

    code, body = call(f"{base}/api/jobs/{jid}/results/sparse.ply")
    assert code == 200 and body == b"ply"
    code, _ = call(f"{base}/api/jobs/{jid}/results/..%2F..%2Fjob.json")
    assert code == 404

    code, lst = call(base + "/api/jobs")
    assert lst[0]["options"]["label"] == "차트 123" and "camera_centers" not in lst[0]["summary"]

    code, _ = call(f"{base}/api/jobs/{jid}", "DELETE")
    assert code == 200
    assert not (srv.Handler.manager.data_dir / jid).exists()


def test_failed_job_reports_error(app):
    base = app(fail=True)
    _, job = call(base + "/api/jobs", "POST", b"{}")
    for i in range(3):
        call(f"{base}/api/jobs/{job['id']}/files/{i}.png", "PUT", b"x")
    call(f"{base}/api/jobs/{job['id']}/start", "POST")
    j = wait_status(base, job["id"], {"done", "failed"})
    assert j["status"] == "failed" and j["error"]


def test_token_required_when_set(app):
    base = app(token="abc123")
    assert call(base + "/api/jobs")[0] == 401
    assert call(base + "/api/jobs?token=abc123")[0] == 200
    assert call(base + "/api/jobs", headers={"Cookie": "afs3d_token=abc123"})[0] == 200
    assert call(base + "/api/jobs", headers={"Cookie": "afs3d_token=wrong"})[0] == 401


def test_restart_marks_running_jobs_failed(tmp_path):
    m = srv.JobManager(tmp_path, command_builder=fake_builder())
    job = m.create({})
    job.status = "running"
    m._save(job)
    m2 = srv.JobManager(tmp_path, command_builder=fake_builder())
    assert m2.get(job.id).status == "failed" and "재시작" in m2.get(job.id).error
