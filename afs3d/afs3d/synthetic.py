"""합성 데이터: 정답을 아는 가상 두상(타원체)과 AFS 식 다각도 촬영 이미지.

실제 환자 사진 없이 파이프라인 전체(품질점검 → SfM → 스케일 복원 → 면적 분석)를 검증하는 용도.
좌표계: 머리 중심 원점, +Z 위, +X 얼굴 정면(= azimuth 0°), 단위 mm.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from PIL import Image

from .geometry import camera_center, look_at_world_to_cam
from .ply import Mesh, write_ply

AXES = np.array([95.0, 75.0, 110.0])  # 앞뒤, 좌우, 위아래 반축 (mm)
BALD_AXIS = np.array([0.45, 0.0, 0.89])  # 앞쪽으로 기운 정수리 방향 → 전두-정수리 탈모 (Norwood IV~V 유사)
BALD_COS = np.cos(np.radians(40))
SKIN = np.array([214, 170, 140], np.float32)
HAIR = np.array([48, 38, 32], np.float32)


class ValueNoise3D:
    """다중 옥타브 3D value noise (해시 격자, 비주기적).

    표면 위치의 함수라 모든 시점에서 같은 무늬 → SIFT 특징점이 일관된다.
    격자값을 표(table)로 두고 modulo 로 돌려 쓰면 무늬가 반복되어 오매칭이 생기므로 해시로 만든다.
    """

    def __init__(self, seed: int = 0, cell_mm: float = 6.0, octaves: int = 4):
        self.seed, self.cell_mm, self.octaves = seed, cell_mm, octaves

    def _hash(self, ix, iy, iz, octave):
        h = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791) ^ ((self.seed * 4 + octave) * 2654435761)
        h = (h ^ (h >> 13)) * 1274126177
        h = h ^ (h >> 16)
        return (h & 0xFFFFFF).astype(np.float32) / 0xFFFFFF

    def _sample(self, p, cell, octave):
        q = p / cell
        i = np.floor(q).astype(np.int64)
        t = q - i
        t = t * t * (3 - 2 * t)  # smoothstep 보간
        out = 0
        for dx in (0, 1):
            for dy in (0, 1):
                for dz in (0, 1):
                    w = (t[:, 0] if dx else 1 - t[:, 0]) * (t[:, 1] if dy else 1 - t[:, 1]) * (t[:, 2] if dz else 1 - t[:, 2])
                    out = out + w * self._hash(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz, octave)
        return out

    def __call__(self, p: np.ndarray) -> np.ndarray:
        acc, amp, total = 0.0, 1.0, 0.0
        for k in range(self.octaves):
            acc = acc + amp * self._sample(p, self.cell_mm / 2**k, k)
            total += amp
            amp *= 0.6
        return acc / total


def unit_dir(p: np.ndarray) -> np.ndarray:
    d = p / AXES
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def bald_mask(p: np.ndarray) -> np.ndarray:
    return unit_dir(p) @ (BALD_AXIS / np.linalg.norm(BALD_AXIS)) > BALD_COS


def hair_mask(p: np.ndarray) -> np.ndarray:
    d = unit_dir(p)
    face = (d[:, 0] > 0.25) & (d[:, 2] < 0.3)  # 이마·얼굴
    return (d[:, 2] > -0.25) & ~face & ~bald_mask(p)


def surface_color(p: np.ndarray, noise: ValueNoise3D) -> np.ndarray:
    # value noise 합은 0.5 근처에 몰리므로 대비를 늘려 모공·색소 같은 국소 무늬를 흉내 낸다
    n = np.clip((noise(p) - 0.5) * 3.0 + 0.5, 0, 1)[:, None]
    fine = np.clip((noise(p * 3.7 + 11.0) - 0.5) * 3.0 + 0.5, 0, 1)[:, None]
    skin = SKIN * (0.6 + 0.6 * n) * (0.75 + 0.5 * fine)
    hair = HAIR * (0.4 + 1.8 * fine) * (0.7 + 0.6 * n)
    col = np.where(hair_mask(p)[:, None], hair, skin)
    return np.clip(col, 0, 255)


def head_mesh(n_lat: int = 120, n_lon: int = 240, seed: int = 0) -> tuple[Mesh, np.ndarray]:
    """타원체 메쉬와 면 단위 정답 탈모 라벨."""
    lat = np.linspace(-np.pi / 2, np.pi / 2, n_lat + 1)[1:-1]
    lon = np.linspace(0, 2 * np.pi, n_lon, endpoint=False)
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    unit = np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1).reshape(-1, 3)
    verts = np.vstack([unit * AXES, [0, 0, -AXES[2]], [0, 0, AXES[2]]])
    south, north = len(verts) - 2, len(verts) - 1

    faces = []
    idx = np.arange(len(unit)).reshape(n_lat - 1, n_lon)
    for i in range(n_lat - 2):
        for j in range(n_lon):
            a, b = idx[i, j], idx[i, (j + 1) % n_lon]
            c, d = idx[i + 1, j], idx[i + 1, (j + 1) % n_lon]
            faces += [(a, b, d), (a, d, c)]
    for j in range(n_lon):
        faces.append((idx[0, (j + 1) % n_lon], idx[0, j], south))
        faces.append((idx[-1, j], idx[-1, (j + 1) % n_lon], north))
    faces = np.array(faces, dtype=np.int64)

    noise = ValueNoise3D(seed)
    colors = surface_color(verts, noise).astype(np.uint8)
    face_bald = bald_mask(verts[faces].mean(axis=1))
    return Mesh(verts, colors, faces), face_bald


def default_rig() -> list[tuple[float, float]]:
    """(azimuth, elevation) 100 컷: 4개 고도 링 + 정수리 방향 보강."""
    rings = [(0, 36), (25, 30), (50, 24), (75, 10)]
    return [(360.0 * k / n, el) for el, n in rings for k in range(n)]


def render_view(
    azimuth: float, elevation: float, radius: float, focal: float, size: tuple[int, int], noise: ValueNoise3D,
    exposure: float = 1.0, background: int = 128,
) -> np.ndarray:  # fmt: skip
    w, h = size
    c = camera_center(azimuth, elevation, radius)
    r_w2c, _ = look_at_world_to_cam(c)
    u, v = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    rays_cam = np.stack([(u - w / 2) / focal, (v - h / 2) / focal, np.ones_like(u)], axis=-1).reshape(-1, 3)
    d = rays_cam @ r_w2c  # (R^T · r)^T = r^T · R
    d /= np.linalg.norm(d, axis=1, keepdims=True)

    # 타원체와의 교차: |(c + t d)/AXES|² = 1
    oc, dd = c / AXES, d / AXES
    a = (dd**2).sum(1)
    b = 2 * (dd @ oc)
    cc = oc @ oc - 1
    disc = b * b - 4 * a * cc
    hit = disc > 0
    t = (-b[hit] - np.sqrt(disc[hit])) / (2 * a[hit])
    p = c + t[:, None] * d[hit]
    nrm = p / AXES**2
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    shade = 0.35 + 0.65 * np.clip((nrm * -d[hit]).sum(1), 0, 1)

    img = np.full((h * w, 3), background, np.float32)
    # exposure 는 선형광 배율 → sRGB(감마 2.2) 값에는 exposure^(1/2.2) 로 반영
    img[hit] = surface_color(p, noise) * shade[:, None] * exposure ** (1 / 2.2)
    return np.clip(img, 0, 255).astype(np.uint8).reshape(h, w, 3)


def make_dataset(
    out_dir: str | Path, radius: float = 450.0, focal: float = 1050.0, size: tuple[int, int] = (960, 720),
    seed: int = 0, exposure_jitter: float = 0.15, views: list[tuple[float, float]] | None = None,
) -> Path:  # fmt: skip
    """out_dir/images/*.jpg + out_dir/manifest.csv + out_dir/ground_truth.ply 생성."""
    out_dir = Path(out_dir)
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    noise = ValueNoise3D(seed)
    rng = np.random.default_rng(seed + 1)
    views = views or default_rig()
    with open(out_dir / "manifest.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filename", "azimuth_deg", "elevation_deg", "radius_mm", "focal_px", "exposure"])
        for i, (az, el) in enumerate(views):
            exp = float(1 + rng.uniform(-exposure_jitter, exposure_jitter))  # AFS 밝기 설정 변화 흉내
            img = render_view(az, el, radius, focal, size, noise, exposure=exp)
            name = f"afs_{i:03d}.jpg"
            Image.fromarray(img).save(out_dir / "images" / name, quality=95)
            w.writerow([name, f"{az:.3f}", f"{el:.3f}", radius, focal, f"{exp:.3f}"])
    mesh, _ = head_mesh(seed=seed)
    write_ply(out_dir / "ground_truth.ply", mesh)
    return out_dir
