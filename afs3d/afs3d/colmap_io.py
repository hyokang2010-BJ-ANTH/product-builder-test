"""COLMAP 텍스트 모델(cameras.txt / images.txt / points3D.txt) 및 database.db 입출력."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .geometry import quat_to_rotmat, rotmat_to_quat


@dataclass
class ColmapImage:
    image_id: int
    name: str
    camera_id: int
    qvec: np.ndarray  # world→camera (qw, qx, qy, qz)
    tvec: np.ndarray

    @property
    def rotation(self) -> np.ndarray:
        return quat_to_rotmat(self.qvec)

    @property
    def center(self) -> np.ndarray:
        return -self.rotation.T @ self.tvec

    @property
    def up_world(self) -> np.ndarray:
        """영상의 위쪽(-y_cam)을 월드 좌표로."""
        return -self.rotation.T[:, 1]

    @property
    def forward_world(self) -> np.ndarray:
        return self.rotation.T[:, 2]


def read_images_txt(path: str | Path) -> list[ColmapImage]:
    # 이미지 1개당 정확히 2줄(포즈 줄 + 2D 점 줄, 점이 없으면 빈 줄)
    lines = [ln for ln in Path(path).read_text().splitlines() if not ln.startswith("#")]
    out = []
    for pose_line in lines[0::2]:
        parts = pose_line.split()
        if len(parts) < 10:
            continue
        out.append(
            ColmapImage(
                image_id=int(parts[0]),
                qvec=np.array(list(map(float, parts[1:5]))),
                tvec=np.array(list(map(float, parts[5:8]))),
                camera_id=int(parts[8]),
                name=" ".join(parts[9:]),
            )
        )
    return out


def write_text_model(
    out_dir: str | Path,
    cameras: dict[int, tuple[str, int, int, list[float]]],
    images: list[tuple[int, str, int, np.ndarray, np.ndarray]],
) -> None:
    """포즈만 있는(3D 점 없는) 모델을 쓴다. point_triangulator 입력용.

    cameras: {camera_id: (model, width, height, params)}
    images: [(image_id, name, camera_id, R_w2c, t_w2c)]
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "cameras.txt", "w") as f:
        f.write("# CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        for cid, (model, w, h, params) in sorted(cameras.items()):
            f.write(f"{cid} {model} {w} {h} " + " ".join(f"{p:.10g}" for p in params) + "\n")
    with open(out_dir / "images.txt", "w") as f:
        f.write("# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n# POINTS2D[] as (X, Y, POINT3D_ID)\n")
        for image_id, name, cid, r, t in images:
            q = rotmat_to_quat(r)
            f.write(f"{image_id} " + " ".join(f"{v:.12g}" for v in (*q, *t)) + f" {cid} {name}\n\n")
    (out_dir / "points3D.txt").write_text("# 3D point list (empty: poses only)\n")


@dataclass
class DbImage:
    image_id: int
    name: str
    camera_id: int


def read_db_images(db_path: str | Path) -> list[DbImage]:
    with sqlite3.connect(str(db_path)) as con:
        rows = con.execute("SELECT image_id, name, camera_id FROM images ORDER BY image_id").fetchall()
    return [DbImage(*r) for r in rows]


def read_db_cameras(db_path: str | Path) -> dict[int, tuple[int, int]]:
    """camera_id → (width, height)."""
    with sqlite3.connect(str(db_path)) as con:
        rows = con.execute("SELECT camera_id, width, height FROM cameras").fetchall()
    return {cid: (w, h) for cid, w, h in rows}
