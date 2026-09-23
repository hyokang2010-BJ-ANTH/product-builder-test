import numpy as np

from afs3d.colmap_io import read_images_txt, write_text_model
from afs3d.geometry import (
    camera_center,
    fit_sphere,
    look_at_world_to_cam,
    quat_to_rotmat,
    rig_radius,
    rotmat_to_quat,
)


def test_look_at_points_camera_at_origin():
    for az, el in [(0, 0), (90, 30), (200, 75), (10, 90)]:
        c = camera_center(az, el, 450)
        r, t = look_at_world_to_cam(c)
        assert np.allclose(r @ r.T, np.eye(3), atol=1e-9)
        assert np.isclose(np.linalg.det(r), 1)
        origin_cam = r @ np.zeros(3) + t
        assert np.allclose(origin_cam[:2], 0, atol=1e-9) and origin_cam[2] > 0  # 원점이 화면 중앙, 앞쪽


def test_image_up_is_world_up_for_side_views():
    r, _ = look_at_world_to_cam(camera_center(45, 0, 400))
    up_world = -r.T[:, 1]
    assert np.allclose(up_world, [0, 0, 1], atol=1e-9)


def test_quaternion_roundtrip():
    rng = np.random.default_rng(0)
    for _ in range(50):
        q = rng.normal(size=4)
        q /= np.linalg.norm(q)
        r = quat_to_rotmat(q)
        assert np.allclose(quat_to_rotmat(rotmat_to_quat(r)), r, atol=1e-9)


def test_sphere_and_circle_fit_recover_radius():
    pts = np.array([camera_center(az, el, 450) for el in (0, 30, 60) for az in range(0, 360, 20)]) + [5, -3, 2]
    c, r = fit_sphere(pts)
    assert np.isclose(r, 450, rtol=1e-6) and np.allclose(c, [5, -3, 2], atol=1e-6)
    _, r2, kind = rig_radius(pts)
    assert kind == "sphere" and np.isclose(r2, 450, rtol=1e-6)
    ring = np.array([camera_center(az, 20, 300) for az in range(0, 360, 15)])
    _, r3, kind = rig_radius(ring)
    assert kind == "circle" and np.isclose(r3, 300 * np.cos(np.radians(20)), rtol=1e-6)


def test_text_model_roundtrip(tmp_path):
    imgs = []
    for i, az in enumerate(range(0, 360, 45), start=1):
        c = camera_center(az, 10, 450)
        r, t = look_at_world_to_cam(c)
        imgs.append((i, f"img_{i:03d}.jpg", 1, r, t))
    write_text_model(tmp_path, {1: ("PINHOLE", 640, 480, [700, 700, 320, 240])}, imgs)
    back = read_images_txt(tmp_path / "images.txt")
    assert [b.name for b in back] == [x[1] for x in imgs]
    for b, (_, _, _, r, t) in zip(back, imgs):
        assert np.allclose(b.center, -r.T @ t, atol=1e-6)
