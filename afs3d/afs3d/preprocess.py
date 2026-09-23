"""전처리: 세트 단위 화이트밸런스/노출 정규화, 배경 마스크, 리사이즈.

AFS 에서 밝기를 바꿔 가며 찍었거나 각도에 따라 조명이 달라진 경우, 특징점 매칭과
텍스처 색이 흔들린다. 이미지마다 따로 보정하면 모발(어두움)과 두피(밝음) 비율이 다른
각도끼리 색이 달라지므로, 화이트밸런스는 세트 전체에 한 번만 적용하고 노출만 이미지별로 맞춘다.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .io_utils import Shot, read_exif_bytes, read_rgb, relative_exposure

GAMMA = 2.2


def _to_linear(rgb: np.ndarray) -> np.ndarray:
    return (rgb.astype(np.float32) / 255.0) ** GAMMA


def _to_srgb(lin: np.ndarray) -> np.ndarray:
    return (np.clip(lin, 0, 1) ** (1 / GAMMA) * 255.0 + 0.5).astype(np.uint8)


def gray_world_gains(rgb: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """회색세계 가정 화이트밸런스 게인 (G 채널 기준)."""
    lin = _to_linear(rgb)
    px = lin[mask > 0] if mask is not None else lin.reshape(-1, 3)
    # 클리핑/암부 픽셀은 색 정보가 없으므로 제외
    lum = px.mean(axis=1)
    px = px[(lum > 0.02) & (lum < 0.95)]
    if len(px) == 0:
        return np.ones(3, np.float32)
    means = px.mean(axis=0)
    return (means[1] / np.maximum(means, 1e-6)).astype(np.float32)


def median_luma(rgb: np.ndarray, mask: np.ndarray | None = None) -> float:
    lin = _to_linear(rgb)
    y = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    vals = y[mask > 0] if mask is not None else y.ravel()
    return float(np.median(vals)) if vals.size else 0.0


def apply_color(rgb: np.ndarray, wb_gains: np.ndarray, exposure_gain: float) -> np.ndarray:
    return _to_srgb(_to_linear(rgb) * wb_gains[None, None, :] * exposure_gain)


def foreground_mask(rgb: np.ndarray, border_frac: float = 0.04, thresh: float = 18.0) -> np.ndarray:
    """단색 배경(촬영 부스 배경막)을 가정한 전경 마스크. 255=머리, 0=배경.

    가장자리 픽셀의 Lab 중앙값을 배경색으로 보고, 그와 충분히 다른 가장 큰 연결 영역을 머리로 본다.
    배경이 단색이 아니면 쓰지 말 것 (그 경우 딥러닝 세그멘테이션으로 교체: concept.md 5.3).
    """
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    h, w = lab.shape[:2]
    b = max(2, int(round(min(h, w) * border_frac)))
    border = np.concatenate(
        [lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3), lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)]
    )
    bg = np.median(border, axis=0)
    dist = np.linalg.norm(lab - bg[None, None, :], axis=2)
    fg = (dist > thresh).astype(np.uint8)

    k = max(3, (min(h, w) // 150) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel, iterations=2)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    if n <= 1:
        return np.full((h, w), 255, np.uint8)  # 분리 실패 시 전체를 쓴다 (마스크가 없느니만 못한 결과 방지)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = (labels == largest).astype(np.uint8)

    # 구멍 메우기: 바깥에서 flood fill 한 뒤 반전
    flood = mask.copy()
    pad = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, pad, (0, 0), 1)
    holes = (flood == 0).astype(np.uint8)
    return ((mask | holes) * 255).astype(np.uint8)


def _resize(rgb: np.ndarray, max_side: int | None) -> tuple[np.ndarray, float]:
    if not max_side:
        return rgb, 1.0
    h, w = rgb.shape[:2]
    s = max_side / max(h, w)
    if s >= 1:
        return rgb, 1.0
    return cv2.resize(rgb, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA), s


def exposure_gains(shots: list[Shot], lumas: list[float]) -> dict:
    """세트 중앙값 노출로 맞추는 이미지별 게인.

    노출 메타데이터(장비 설정/EXIF)가 모든 사진에 있으면 그것을 쓴다. 픽셀 밝기로 맞추면
    탈모 부위가 많이 보이는 각도(밝음)와 모발이 많은 각도(어두움)의 '내용 차이'까지 지워 버리기 때문이다.
    메타데이터가 없을 때만 전경 밝기 중앙값으로 맞춘다.
    """
    exps = [relative_exposure(s) for s in shots]
    if exps and all(e and e > 0 for e in exps):
        ref = float(np.median(exps))
        return {"source": "metadata", "gains": [float(np.clip(ref / e, 0.25, 4.0)) for e in exps]}
    ref = float(np.median(lumas)) if lumas else 0.0
    gains = [float(np.clip(ref / lu, 0.25, 4.0)) if lu > 1e-4 else 1.0 for lu in lumas]
    return {"source": "luma", "gains": gains}


@dataclass
class PrepOptions:
    max_side: int | None = 3200
    normalize_color: bool = True
    make_masks: bool = False
    jpeg_quality: int = 95


def preprocess_shots(shots: list[Shot], out_dir: str | Path, opts: PrepOptions = PrepOptions()) -> dict:
    """shots 를 out_dir/images (+ out_dir/masks) 로 내보내고 메타데이터(prep.json)를 남긴다.

    COLMAP 마스크 규칙: masks/<이미지파일명>.png, 0 인 픽셀에서는 특징점을 뽑지 않는다.
    """
    out_dir = Path(out_dir)
    img_dir = out_dir / "images"
    mask_dir = out_dir / "masks"
    # 이전 실행의 결과가 섞이지 않도록 비운다 (다른 세트의 이미지/마스크가 COLMAP 에 들어가는 사고 방지)
    for d in (img_dir, mask_dir):
        if d.exists():
            shutil.rmtree(d)
    img_dir.mkdir(parents=True)
    if opts.make_masks:
        mask_dir.mkdir(parents=True)

    # 1차: 스케일/마스크/색 통계 수집 (이미지가 100장 수준이라 메모리에 올려도 되지만 두 번 읽어 메모리를 아낀다)
    stats = []
    for s in shots:
        rgb, scale = _resize(read_rgb(s.path), opts.max_side)
        mask = foreground_mask(rgb) if opts.make_masks else None
        stats.append(
            {"scale": scale, "gains": gray_world_gains(rgb, mask), "luma": median_luma(rgb, mask), "mask": mask}
        )

    wb = np.median(np.stack([st["gains"] for st in stats]), axis=0) if opts.normalize_color else np.ones(3, np.float32)
    gains = exposure_gains(shots, [st["luma"] for st in stats])

    meta = {"wb_gains": wb.tolist(), "exposure_source": gains["source"], "images": []}
    for s, st, gain in zip(shots, stats, gains["gains"]):
        rgb, _ = _resize(read_rgb(s.path), opts.max_side)
        if not opts.normalize_color:
            gain = 1.0
        else:
            rgb = apply_color(rgb, wb, gain)
        out_name = Path(s.name).with_suffix(".jpg").name
        exif = read_exif_bytes(s.path)
        Image.fromarray(rgb).save(img_dir / out_name, quality=opts.jpeg_quality, **({"exif": exif} if exif else {}))
        if st["mask"] is not None:
            cv2.imwrite(str(mask_dir / f"{out_name}.png"), st["mask"])
        meta["images"].append(
            {"source": str(s.path), "name": out_name, "scale": st["scale"], "exposure_gain": gain, "order": s.order}
        )

    (out_dir / "prep.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta
