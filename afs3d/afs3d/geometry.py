"""카메라 기하: 리그 각도 → 카메라 포즈, 회전/쿼터니언, 구·원 피팅(스케일 복원)."""
from __future__ import annotations

import numpy as np

WORLD_UP = np.array([0.0, 0.0, 1.0])


def camera_center(azimuth_deg: float, elevation_deg: float, radius: float) -> np.ndarray:
    """머리 중심을 원점, +Z 를 위로 둔 구면좌표. azimuth 0° = +X 방향."""
    az, el = np.radians(azimuth_deg), np.radians(elevation_deg)
    return radius * np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])


def look_at_world_to_cam(center: np.ndarray, target: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """COLMAP 규약(x 오른쪽, y 아래, z 앞)의 world→camera (R, t) 를 반환한다."""
    target = np.zeros(3) if target is None else target
    f = target - center
    f = f / np.linalg.norm(f)
    right = np.cross(f, WORLD_UP)
    if np.linalg.norm(right) < 1e-6:  # 정수리 바로 위에서 내려다보는 컷: 임의의 수평축을 사용
        right = np.cross(f, np.array([0.0, 1.0, 0.0]))
    right /= np.linalg.norm(right)
    down = np.cross(f, right)
    r_c2w = np.stack([right, down, f], axis=1)
    r_w2c = r_c2w.T
    return r_w2c, -r_w2c @ center


def rotmat_to_quat(r: np.ndarray) -> np.ndarray:
    """회전행렬 → (qw, qx, qy, qz), qw >= 0."""
    m = r
    tr = np.trace(m)
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        q = [0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [(m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s]
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s]
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s]
    q = np.array(q)
    q /= np.linalg.norm(q)
    return q if q[0] >= 0 else -q


def quat_to_rotmat(q) -> np.ndarray:
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def fit_sphere(points: np.ndarray) -> tuple[np.ndarray, float]:
    """최소제곱 구 피팅: |p|² = 2c·p + (r² - |c|²)."""
    p = np.asarray(points, float)
    a = np.hstack([2 * p, np.ones((len(p), 1))])
    b = (p**2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    c = sol[:3]
    return c, float(np.sqrt(sol[3] + c @ c))


def fit_circle_3d(points: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    """평면 위 점들의 원 피팅. (중심, 반지름, 평면 법선)."""
    p = np.asarray(points, float)
    mu = p.mean(axis=0)
    _, _, vt = np.linalg.svd(p - mu)
    u, v, n = vt[0], vt[1], vt[2]
    xy = np.stack([(p - mu) @ u, (p - mu) @ v], axis=1)
    a = np.hstack([2 * xy, np.ones((len(xy), 1))])
    b = (xy**2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    c2 = sol[:2]
    r = float(np.sqrt(sol[2] + c2 @ c2))
    return mu + c2[0] * u + c2[1] * v, r, n


def rig_radius(points: np.ndarray, planar_tol: float = 0.05) -> tuple[np.ndarray, float, str]:
    """카메라 중심들이 놓인 구(여러 고도 링) 또는 원(단일 링)의 중심·반지름.

    AFS 처럼 카메라가 머리 둘레를 일정 거리로 도는 장비에서, SfM 결과의 반지름과
    실제 촬영 반경(mm)의 비로 모델 스케일을 복원한다.
    """
    p = np.asarray(points, float)
    if len(p) < 4:
        raise ValueError("스케일 추정에는 카메라가 4대 이상 필요합니다")
    sv = np.linalg.svd(p - p.mean(axis=0), compute_uv=False)
    if sv[2] / sv[0] < planar_tol:
        c, r, _ = fit_circle_3d(p)
        return c, r, "circle"
    c, r = fit_sphere(p)
    return c, r, "sphere"
