"""촬영 품질 점검: 흔들림(초점), 노출 편차, 클리핑.

5분 동안 100여 장을 찍는 동안 환자가 움직이거나 조명이 바뀐 컷을 재구성 전에 걸러낸다.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .io_utils import Shot, read_rgb

ANALYSIS_MAX_SIDE = 1024  # 장비 해상도와 무관하게 같은 크기에서 비교해야 선명도 수치가 비교 가능하다


@dataclass
class QualityResult:
    name: str
    width: int
    height: int
    sharpness: float  # Laplacian 분산 (클수록 선명)
    mean_luma: float  # 0-255
    clip_high: float  # 250 이상 픽셀 비율
    clip_low: float  # 5 이하 픽셀 비율
    flags: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.flags


def _downscale(gray: np.ndarray, max_side: int) -> np.ndarray:
    h, w = gray.shape
    s = max_side / max(h, w)
    if s >= 1:
        return gray
    return cv2.resize(gray, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)


def measure(rgb: np.ndarray) -> dict:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    small = _downscale(gray, ANALYSIS_MAX_SIDE)
    return {
        "width": rgb.shape[1],
        "height": rgb.shape[0],
        "sharpness": float(cv2.Laplacian(small, cv2.CV_64F).var()),
        "mean_luma": float(small.mean()),
        "clip_high": float((small >= 250).mean()),
        "clip_low": float((small <= 5).mean()),
    }


def flag_outliers(
    results: list[QualityResult],
    blur_ratio: float = 0.4,
    exposure_tol: float = 0.25,
    max_clip_high: float = 0.05,
    max_clip_low: float = 0.20,
) -> None:
    """세트 중앙값 대비 기준으로 플래그를 단다 (각도마다 장면이 달라 절대 기준은 쓰지 않는다)."""
    if not results:
        return
    med_sharp = float(np.median([r.sharpness for r in results]))
    med_luma = float(np.median([r.mean_luma for r in results]))
    for r in results:
        r.flags.clear()
        if r.sharpness < blur_ratio * med_sharp:
            r.flags.append("blurry")
        if med_luma > 0 and abs(r.mean_luma - med_luma) / med_luma > exposure_tol:
            r.flags.append("exposure_outlier")
        if r.clip_high > max_clip_high:
            r.flags.append("overexposed")
        if r.clip_low > max_clip_low:
            r.flags.append("underexposed")


def assess_shots(shots: list[Shot], **flag_kwargs) -> list[QualityResult]:
    results = [QualityResult(name=s.name, **measure(read_rgb(s.path))) for s in shots]
    flag_outliers(results, **flag_kwargs)
    return results


def write_report(results: list[QualityResult], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(QualityResult.__dataclass_fields__)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results:
            row = asdict(r)
            row["flags"] = ";".join(r.flags)
            w.writerow(row)
