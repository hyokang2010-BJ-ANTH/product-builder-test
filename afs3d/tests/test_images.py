import csv

import cv2
import numpy as np
from PIL import Image

from afs3d.io_utils import load_shots
from afs3d.preprocess import PrepOptions, foreground_mask, preprocess_shots
from afs3d.quality import assess_shots
from afs3d.synthetic import ValueNoise3D, render_view


def _render(az=0, el=30, exposure=1.0, size=(320, 240)):
    return render_view(az, el, 450, 350, size, ValueNoise3D(0), exposure=exposure)


def _write_set(tmp_path, exposures):
    d = tmp_path / "images"
    d.mkdir()
    with open(tmp_path / "manifest.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filename", "azimuth_deg", "elevation_deg", "radius_mm", "exposure"])
        for i, e in enumerate(exposures):
            name = f"s_{i}.png"
            Image.fromarray(_render(az=i * 30, exposure=e)).save(d / name)
            w.writerow([name, i * 30, 30, 450, e])
    return d


def test_quality_flags_blur_and_exposure(tmp_path):
    d = _write_set(tmp_path, [1.0] * 6)
    img = cv2.imread(str(d / "s_2.png"))
    cv2.imwrite(str(d / "s_2.png"), cv2.GaussianBlur(img, (0, 0), 4))
    cv2.imwrite(str(d / "s_4.png"), (cv2.imread(str(d / "s_4.png")) * 0.35).astype(np.uint8))
    res = {r.name: r for r in assess_shots(load_shots(d))}
    assert "blurry" in res["s_2.png"].flags
    assert "exposure_outlier" in res["s_4.png"].flags
    assert res["s_0.png"].ok


def test_preprocess_uses_exposure_metadata(tmp_path):
    d = _write_set(tmp_path, [0.6, 1.0, 1.0, 1.6])
    shots = load_shots(d, tmp_path / "manifest.csv")
    assert shots[0].azimuth_deg == 0 and shots[1].radius_mm == 450
    meta = preprocess_shots(shots, tmp_path / "work", PrepOptions(max_side=None, make_masks=True))
    assert meta["exposure_source"] == "metadata"
    ref = _render(az=0, exposure=1.0).astype(float)
    fixed = np.asarray(Image.open(tmp_path / "work" / "images" / "s_0.jpg")).astype(float)
    m = foreground_mask(_render(az=0)) > 0
    # 노출 0.6 으로 찍힌 컷이 기준 노출로 복원되어야 한다 (JPEG 손실 허용)
    assert abs(fixed[m].mean() - ref[m].mean()) < 6
    assert (tmp_path / "work" / "masks" / "s_0.jpg.png").exists()


def test_foreground_mask_matches_head():
    img = _render(az=60, el=10)
    truth = np.any(img != 128, axis=2)
    mask = foreground_mask(img) > 0
    iou = (mask & truth).sum() / (mask | truth).sum()
    assert iou > 0.97


def _fg_rb_ratio(img, mask):
    px = img[mask].astype(float)
    return px[:, 0].mean() / px[:, 2].mean()


def test_default_prep_keeps_skin_tone(tmp_path):
    """머리 사진에 회색세계 WB 를 적용하면 피부색이 회색이 된다 → 기본값은 WB 없음."""
    _write_set(tmp_path, [1.0, 1.0, 1.0])
    shots = load_shots(tmp_path / "images", tmp_path / "manifest.csv")
    preprocess_shots(shots, tmp_path / "work", PrepOptions(max_side=None, make_masks=True))
    src = _render(az=0)
    out = np.asarray(Image.open(tmp_path / "work" / "images" / "s_0.jpg"))
    m = foreground_mask(src) > 0
    assert _fg_rb_ratio(out, m) > 1.3  # 피부/모발의 붉은 기가 유지되어야 함
    assert abs(_fg_rb_ratio(out, m) - _fg_rb_ratio(src, m)) < 0.05


def test_background_white_balance_removes_cast(tmp_path):
    d = tmp_path / "images"
    d.mkdir()
    cast = np.array([1.0, 1.0, 0.7])  # 파란 채널이 약한(노란) 색 틀어짐
    src = _render(az=0)
    for i in range(3):
        img = np.clip(src.astype(float) * cast, 0, 255).astype(np.uint8)
        Image.fromarray(img).save(d / f"c_{i}.png")
    shots = load_shots(d)
    meta = preprocess_shots(shots, tmp_path / "w", PrepOptions(max_side=None, make_masks=True, white_balance="background"))
    out = np.asarray(Image.open(tmp_path / "w" / "images" / "c_0.jpg")).astype(float)
    bg = foreground_mask(src) == 0
    r, g, b = out[bg].mean(axis=0)
    assert abs(r - b) < 4 and abs(g - b) < 4  # 회색 배경막이 다시 회색으로
    assert meta["white_balance"] == "background"
