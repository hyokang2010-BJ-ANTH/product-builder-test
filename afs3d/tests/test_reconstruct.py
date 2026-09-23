import os
import shutil

import numpy as np
import pytest

from afs3d.cli import main
from afs3d.io_utils import load_shots
from afs3d.preprocess import PrepOptions, preprocess_shots
from afs3d.reconstruct import ReconOptions, reconstruct
from afs3d.synthetic import make_dataset


def test_dry_run_prints_colmap_pipeline(tmp_path, capsys):
    img = tmp_path / "images"
    img.mkdir()
    (img / "a.jpg").write_bytes(b"")
    main(["reconstruct", "--images", str(img), "--work", str(tmp_path / "w"), "--dense", "--dry-run"])
    out = capsys.readouterr().out
    for step in ("feature_extractor", "exhaustive_matcher", "mapper", "model_converter",
                 "image_undistorter", "patch_match_stereo", "stereo_fusion", "poisson_mesher"):  # fmt: skip
        assert step in out


needs_colmap = pytest.mark.skipif(
    shutil.which("colmap") is None or not os.environ.get("AFS3D_SLOW"),
    reason="COLMAP 설치 + AFS3D_SLOW=1 일 때만 실행 (수 분 소요)",
)


@needs_colmap
@pytest.mark.parametrize("mode", ["rig", "sfm"])
def test_colmap_on_synthetic_head(tmp_path, mode):
    data = make_dataset(tmp_path / "data")
    shots = load_shots(data / "images", data / "manifest.csv")
    preprocess_shots(shots, tmp_path / "w", PrepOptions(max_side=None, make_masks=True))
    res = reconstruct(tmp_path / "w", shots, ReconOptions(mode=mode, rig_radius_mm=450.0))
    assert res["n_registered"] >= 90
    # 복원한 스케일로 환산한 촬영 반경이 실제(450 mm)와 2% 이내
    assert np.isclose(res["rig_radius_model"] * res["scale_mm_per_unit"], 450, rtol=0.02)
    if mode == "rig":
        assert np.isclose(res["rig_radius_model"], 450, rtol=1e-3)
