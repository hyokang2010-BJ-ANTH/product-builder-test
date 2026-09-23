"""COLMAP CLI 오케스트레이션.

모드
- sfm : 사진만으로 카메라 포즈를 추정 (기본값, 환자 움직임에 강함). 촬영 반경(mm)을 주면 스케일을 복원한다.
- rig : 매니페스트의 방위각/고도/반경으로 포즈를 고정하고 3D 점만 삼각측량. 장비가 포즈를 정확히
        내보내고 환자가 고정돼 있을 때만 사용. 단위가 곧 mm 가 된다.

dense(조밀 재구성 + Poisson 메쉬)는 COLMAP 의 patch_match_stereo 가 CUDA 를 요구한다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .colmap_io import read_db_cameras, read_db_images, read_images_txt, write_text_model
from .geometry import camera_center, look_at_world_to_cam, rig_radius
from .io_utils import Shot


@dataclass
class ReconOptions:
    mode: str = "sfm"  # "sfm" | "rig"
    matcher: str = "auto"  # "auto" | "exhaustive" | "sequential"
    single_camera: bool = True
    camera_model: str = "OPENCV"
    use_masks: bool = True
    dense: bool = False
    rig_radius_mm: float | None = None  # sfm 모드 스케일 복원용 촬영 반경
    focal_px: float | None = None  # rig 모드에서 매니페스트에 focal_px 가 없을 때
    colmap: str = "colmap"
    dry_run: bool = False
    max_image_size: int = 2000  # dense 단계 해상도 상한 (VRAM 절약)
    use_gpu: bool | None = None  # None 이면 CUDA 빌드 여부로 자동 결정
    log: list[str] = field(default_factory=list)


class ColmapError(RuntimeError):
    pass


def colmap_info(colmap: str = "colmap") -> tuple[tuple[int, int], bool]:
    """(버전, CUDA 지원 여부). `colmap help` 첫 줄: 'COLMAP 3.9.1 -- ... (Commit ... with/without CUDA)'."""
    try:
        out = subprocess.run([colmap, "help"], capture_output=True, text=True, env=_env(), timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return (0, 0), False
    text = out.stdout + out.stderr
    m = re.search(r"COLMAP (\d+)\.(\d+)", text)
    version = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    return version, "with CUDA" in text and "without CUDA" not in text


def colmap_has_cuda(colmap: str = "colmap") -> bool:
    return colmap_info(colmap)[1]


def _gpu_flags(opts: ReconOptions, stage: str) -> list[str]:
    """SIFT 추출/매칭 GPU 옵션. CUDA 없는 서버에서 GPU SIFT 는 OpenGL 컨텍스트를 요구해 죽는다."""
    if opts.dry_run and opts.use_gpu is None:
        return []
    version, cuda = colmap_info(opts.colmap)
    use_gpu = cuda if opts.use_gpu is None else opts.use_gpu
    # COLMAP 3.12 부터 SiftExtraction/SiftMatching.use_gpu → FeatureExtraction/FeatureMatching.use_gpu
    if version >= (3, 12):
        section = "FeatureExtraction" if stage == "extract" else "FeatureMatching"
    else:
        section = "SiftExtraction" if stage == "extract" else "SiftMatching"
    return [f"--{section}.use_gpu", str(int(use_gpu))]


def _env() -> dict:
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")  # 서버(디스플레이 없음)에서 Qt 링크된 COLMAP 실행
    return env


def _run(opts: ReconOptions, *args: str | Path) -> None:
    cmd = [opts.colmap, *map(str, args)]
    opts.log.append(" ".join(cmd))
    print("$", " ".join(cmd), flush=True)
    if opts.dry_run:
        return
    proc = subprocess.run(cmd, env=_env(), capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-30:])
        raise ColmapError(f"COLMAP 실패 ({args[0]}):\n{tail}")


def _pick_matcher(opts: ReconOptions, n_images: int) -> str:
    if opts.matcher != "auto":
        return opts.matcher
    # 100여 장이면 전수 매칭(약 5천 쌍)이 가장 안정적. 그 이상은 촬영 순서 기반 매칭.
    return "exhaustive" if n_images <= 250 else "sequential"


def _largest_model(sparse_root: Path) -> Path:
    best, best_n = None, -1
    for d in sorted(p for p in sparse_root.iterdir() if p.is_dir()):
        f = d / "images.bin"
        n = f.stat().st_size if f.exists() else 0  # 등록 이미지 수에 비례
        if n > best_n:
            best, best_n = d, n
    if best is None:
        raise ColmapError("SfM 이 모델을 만들지 못했습니다 (사진 간 겹침/질감 부족). quality 리포트를 확인하세요.")
    return best


def _rig_prior_model(work: Path, shots_by_name: dict[str, Shot], scales: dict[str, float], opts: ReconOptions) -> Path:
    db = work / "database.db"
    db_images = read_db_images(db)
    db_cams = read_db_cameras(db)
    cam_params: dict[int, tuple[str, int, int, list[float]]] = {}
    images = []
    for im in db_images:
        shot = shots_by_name.get(im.name)
        if shot is None or not shot.has_pose:
            raise ColmapError(f"rig 모드: {im.name} 의 azimuth/elevation/radius 가 매니페스트에 없습니다")
        if im.camera_id not in cam_params:
            w, h = db_cams[im.camera_id]
            s = scales.get(im.name, 1.0)
            f = shot.focal_px * s if shot.focal_px else opts.focal_px
            if not f:
                raise ColmapError("rig 모드: focal_px (매니페스트 열 또는 --focal-px) 가 필요합니다")
            cx = shot.cx * s if shot.cx is not None else w / 2
            cy = shot.cy * s if shot.cy is not None else h / 2
            cam_params[im.camera_id] = ("PINHOLE", w, h, [f, f, cx, cy])
        c = camera_center(shot.azimuth_deg, shot.elevation_deg, shot.radius_mm)
        r, t = look_at_world_to_cam(c)
        images.append((im.image_id, im.name, im.camera_id, r, t))
    prior = work / "sparse_prior"
    write_text_model(prior, cam_params, images)
    return prior


def estimate_frame(model_txt: Path, rig_radius_mm: float | None, front_image: str | None = None) -> dict:
    """모델 좌표계 정보를 계산한다: mm 스케일, 위쪽 벡터, 앞쪽 힌트, 머리 중심 추정."""
    imgs = read_images_txt(model_txt / "images.txt")
    centers = np.array([im.center for im in imgs])
    up = np.mean([im.up_world for im in imgs], axis=0)
    up /= np.linalg.norm(up)
    info: dict = {"n_registered": len(imgs), "up": up.tolist(), "camera_centers": centers.round(6).tolist()}
    if len(imgs) >= 4:
        c, r, kind = rig_radius(centers)
        info.update({"rig_center": c.tolist(), "rig_radius_model": r, "rig_fit": kind})
        if rig_radius_mm:
            info["scale_mm_per_unit"] = rig_radius_mm / r
        ref = next((im for im in imgs if im.name == front_image), None) or min(imgs, key=lambda im: im.image_id)
        front = ref.center - c
        front -= (front @ up) * up
        if np.linalg.norm(front) > 1e-9:
            info["front"] = (front / np.linalg.norm(front)).tolist()
            info["front_image"] = ref.name
    return info


def reconstruct(work: str | Path, shots: list[Shot], opts: ReconOptions) -> dict:
    """work/images (preprocess 결과) → work/sparse/0 (+ work/dense/meshed-poisson.ply)."""
    work = Path(work)
    images = work / "images"
    masks = work / "masks"
    db = work / "database.db"
    if not opts.dry_run and shutil.which(opts.colmap) is None:
        raise ColmapError(f"COLMAP 실행 파일을 찾을 수 없습니다: {opts.colmap} (설치: concept.md 7장)")

    prep = json.loads((work / "prep.json").read_text()) if (work / "prep.json").exists() else {"images": []}
    name_of_source = {Path(m["source"]).name: m["name"] for m in prep["images"]}
    scales = {m["name"]: m["scale"] for m in prep["images"]}
    shots_by_name = {name_of_source.get(s.name, s.name): s for s in shots}
    n_images = len(shots_by_name)

    if db.exists() and not opts.dry_run:
        db.unlink()
    extract = ["feature_extractor", "--database_path", db, "--image_path", images,
               "--ImageReader.camera_model", opts.camera_model,
               "--ImageReader.single_camera", int(opts.single_camera)]  # fmt: skip
    if opts.use_masks and masks.is_dir():
        extract += ["--ImageReader.mask_path", masks]
    _run(opts, *extract, *_gpu_flags(opts, "extract"))

    matcher = _pick_matcher(opts, n_images)
    if matcher == "exhaustive":
        _run(opts, "exhaustive_matcher", "--database_path", db, *_gpu_flags(opts, "match"))
    else:
        _run(opts, "sequential_matcher", "--database_path", db, "--SequentialMatching.overlap", 15, *_gpu_flags(opts, "match"))

    sparse = work / "sparse"
    if sparse.exists() and not opts.dry_run:
        shutil.rmtree(sparse)
    sparse.mkdir(parents=True, exist_ok=True)

    if opts.mode == "rig":
        prior = work / "sparse_prior"
        if not opts.dry_run:
            prior = _rig_prior_model(work, shots_by_name, scales, opts)
        out = sparse / "0"
        out.mkdir(parents=True, exist_ok=True)
        _run(opts, "point_triangulator", "--database_path", db, "--image_path", images,
             "--input_path", prior, "--output_path", out)  # fmt: skip
        model = out
    else:
        _run(opts, "mapper", "--database_path", db, "--image_path", images, "--output_path", sparse)
        model = sparse / "0" if opts.dry_run else _largest_model(sparse)

    model_txt = work / "sparse_txt"
    model_txt.mkdir(exist_ok=True)
    _run(opts, "model_converter", "--input_path", model, "--output_path", model_txt, "--output_type", "TXT")
    # GPU 없이도 결과를 눈으로 확인할 수 있도록 sparse 점군을 PLY 로도 내보낸다
    _run(opts, "model_converter", "--input_path", model, "--output_path", work / "sparse.ply", "--output_type", "PLY")

    result: dict = {"mode": opts.mode, "model": str(model), "model_txt": str(model_txt), "n_input": n_images,
                    "sparse_ply": str(work / "sparse.ply")}  # fmt: skip
    if not opts.dry_run:
        result.update(estimate_frame(model_txt, None if opts.mode == "rig" else opts.rig_radius_mm))
        if opts.mode == "rig":
            result["scale_mm_per_unit"] = 1.0

    if opts.dense:
        if not opts.dry_run and not colmap_has_cuda(opts.colmap):
            result["dense_skipped"] = (
                "이 COLMAP 빌드는 CUDA 가 없어 patch_match_stereo 를 실행할 수 없습니다. "
                "NVIDIA GPU 환경에서 다시 실행하거나 concept.md 5.6 의 대안(OpenMVS, 3DGS)을 쓰세요."
            )
            print("!", result["dense_skipped"])
        else:
            dense = work / "dense"
            _run(opts, "image_undistorter", "--image_path", images, "--input_path", model,
                 "--output_path", dense, "--output_type", "COLMAP", "--max_image_size", opts.max_image_size)  # fmt: skip
            _run(opts, "patch_match_stereo", "--workspace_path", dense, "--workspace_format", "COLMAP",
                 "--PatchMatchStereo.geom_consistency", "true")  # fmt: skip
            _run(opts, "stereo_fusion", "--workspace_path", dense, "--workspace_format", "COLMAP",
                 "--input_type", "geometric", "--output_path", dense / "fused.ply")  # fmt: skip
            _run(opts, "poisson_mesher", "--input_path", dense / "fused.ply",
                 "--output_path", dense / "meshed-poisson.ply", "--PoissonMeshing.trim", 7)  # fmt: skip
            result["mesh"] = str(dense / "meshed-poisson.ply")
            result["points"] = str(dense / "fused.ply")

    result["commands"] = opts.log
    if not opts.dry_run:
        (work / "reconstruction.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result
