"""촬영 세트(이미지 폴더 + 선택적 매니페스트 CSV) 읽기."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}

# 매니페스트에서 숫자로 해석하는 열. 그 밖의 열은 Shot.extra 에 문자열로 보관한다.
NUMERIC_COLUMNS = ("azimuth_deg", "elevation_deg", "radius_mm", "focal_px", "cx", "cy")


@dataclass
class Shot:
    """촬영 1장. 각도 정보는 AFS 가 내보내는 경우에만 채워진다."""

    path: Path
    order: int
    azimuth_deg: float | None = None
    elevation_deg: float | None = None
    radius_mm: float | None = None
    focal_px: float | None = None
    cx: float | None = None
    cy: float | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def has_pose(self) -> bool:
        return None not in (self.azimuth_deg, self.elevation_deg, self.radius_mm)


def _natural_key(p: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def list_images(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"이미지 폴더가 없습니다: {folder}")
    return sorted((p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS), key=_natural_key)


def _to_float(v: str | None) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    return float(v)


def load_shots(image_dir: str | Path, manifest: str | Path | None = None) -> list[Shot]:
    """이미지 목록을 읽는다.

    manifest CSV 는 `filename` 열이 필수이고 NUMERIC_COLUMNS 는 선택이다.
    매니페스트가 있으면 그 행 순서가 촬영 순서가 되고, 없으면 파일명 자연 정렬 순서를 쓴다.
    """
    image_dir = Path(image_dir)
    if manifest is None:
        return [Shot(path=p, order=i) for i, p in enumerate(list_images(image_dir))]

    shots: list[Shot] = []
    with open(manifest, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "filename" not in reader.fieldnames:
            raise ValueError("매니페스트 CSV 에 'filename' 열이 필요합니다")
        for i, row in enumerate(reader):
            path = image_dir / row["filename"].strip()
            if not path.exists():
                raise FileNotFoundError(f"매니페스트에 있는 파일이 없습니다: {path}")
            nums = {k: _to_float(row.get(k)) for k in NUMERIC_COLUMNS}
            extra = {k: v for k, v in row.items() if k not in NUMERIC_COLUMNS and k != "filename"}
            shots.append(Shot(path=path, order=i, extra=extra, **nums))
    return shots


def read_rgb(path: str | Path) -> np.ndarray:
    """EXIF 회전을 반영해 RGB uint8 배열로 읽는다."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        return np.asarray(im.convert("RGB"))


def read_exif_bytes(path: str | Path) -> bytes | None:
    """COLMAP 이 초점거리 추정에 쓰는 EXIF 를 보존하기 위해 읽는다 (회전 태그는 1로 초기화)."""
    with Image.open(path) as im:
        exif = im.getexif()
        if not exif:
            return None
        exif.get_ifd(0x8769)  # Exif sub-IFD(FocalLength 등)를 로드해야 tobytes() 에 포함된다
        exif[0x0112] = 1
        return exif.tobytes()


def exif_exposure(path: str | Path) -> float | None:
    """상대 노출량 = 셔터시간 × ISO / F값². 같은 장면이면 픽셀 밝기가 이 값에 비례한다."""
    with Image.open(path) as im:
        ifd = im.getexif().get_ifd(0x8769)
    t, iso, fnum = ifd.get(0x829A), ifd.get(0x8827), ifd.get(0x829D)  # ExposureTime, ISOSpeedRatings, FNumber
    if isinstance(iso, tuple):
        iso = iso[0] if iso else None
    try:
        if t and iso and fnum:
            return float(t) * float(iso) / float(fnum) ** 2
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return None


def relative_exposure(shot: Shot) -> float | None:
    """매니페스트 `exposure` 열(장비 밝기 설정 배율)이 있으면 우선, 없으면 EXIF."""
    v = shot.extra.get("exposure")
    if v not in (None, ""):
        try:
            return float(v)
        except ValueError:
            pass
    return exif_exposure(shot.path)

