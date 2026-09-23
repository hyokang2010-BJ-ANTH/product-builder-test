import json

import numpy as np

from afs3d.analysis import AnalysisOptions, analyze_mesh, face_areas, run_analysis
from afs3d.ply import Mesh
from afs3d.synthetic import head_mesh

ROI_DEPTH = 70.0  # 정수리(z=110)에서 z=40 까지: 이마·얼굴(합성 두상에서 z<33) 제외


def _ground_truth(mesh, face_bald):
    v, f = mesh.vertices, mesh.faces
    top = np.percentile(v[:, 2], 99.5)
    roi_f = (v[:, 2] >= top - ROI_DEPTH)[f].sum(axis=1) >= 2
    a = face_areas(v, f)
    return a[roi_f].sum() / 100, a[roi_f & face_bald].sum() / 100


def test_exposed_area_matches_ground_truth():
    mesh, face_bald = head_mesh(seed=3)
    roi_gt, exposed_gt = _ground_truth(mesh, face_bald)
    rep, _ = analyze_mesh(mesh, AnalysisOptions(scale_mm_per_unit=1.0, roi_depth_mm=ROI_DEPTH))
    assert rep.units == "cm2"
    assert np.isclose(rep.roi_area, roi_gt, rtol=1e-6)
    assert abs(rep.exposed_area - exposed_gt) / exposed_gt < 0.05
    assert rep.graft_estimates["40_FU_per_cm2"] == round(rep.exposed_area * 40)


def test_scale_and_orientation_invariance():
    """모델 단위(SfM 임의 스케일)와 임의 회전에서도 scale/up 을 주면 같은 면적이 나와야 한다."""
    mesh, _ = head_mesh(seed=3)
    ref, _ = analyze_mesh(mesh, AnalysisOptions(scale_mm_per_unit=1.0, roi_depth_mm=ROI_DEPTH))

    rng = np.random.default_rng(1)
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    q *= np.sign(np.linalg.det(q))
    s = 0.037  # 1 모델단위 = 1/0.037 mm
    moved = Mesh(mesh.vertices @ q.T * s + [3, -2, 7], mesh.colors, mesh.faces)
    up = q @ np.array([0, 0, 1.0])
    rep, _ = analyze_mesh(moved, AnalysisOptions(up=tuple(up), scale_mm_per_unit=1 / s, roi_depth_mm=ROI_DEPTH))
    assert np.isclose(rep.roi_area, ref.roi_area, rtol=1e-3)
    assert np.isclose(rep.exposed_area, ref.exposed_area, rtol=1e-3)


def test_run_analysis_writes_outputs(tmp_path):
    mesh, _ = head_mesh(n_lat=60, n_lon=120, seed=0)
    rep = run_analysis(mesh, tmp_path, AnalysisOptions(scale_mm_per_unit=1.0, front=(1, 0, 0), map_px=300))
    assert (tmp_path / "coverage.ply").exists() and (tmp_path / "top_view.png").exists()
    data = json.loads((tmp_path / "report.json").read_text())
    assert data["report"]["exposed_area"] == rep.exposed_area


def test_unscaled_reports_relative_units():
    mesh, _ = head_mesh(n_lat=40, n_lon=80)
    rep, _ = analyze_mesh(mesh, AnalysisOptions())
    assert rep.units == "model_units2" and not rep.graft_estimates and rep.notes
