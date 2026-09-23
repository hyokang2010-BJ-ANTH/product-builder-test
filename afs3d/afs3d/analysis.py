"""3D 메쉬에서 두피 노출(탈모) 영역을 정량화한다.

절차
1. 위쪽 벡터(up) 기준으로 정수리부터 일정 깊이까지를 두피 관심영역(ROI)으로 잡는다.
2. 정점 색(Lab L*)을 Otsu 로 이진화해 '노출 두피(밝음)' vs '모발(어두움)' 으로 나눈다.
3. 메쉬 이웃 다수결로 잡음을 줄이고, 삼각형 면적을 합산해 cm² 로 보고한다.
4. 정수리 위에서 내려다본 지도(PNG)와 색 입힌 메쉬(PLY)를 만든다.

한계: 흰머리/밝은 모발, 두피 문신(SMP), 강한 반사광은 색 기준으로 구분되지 않는다 (concept.md 5.7).
결과는 연구/상담 보조용이며 진단 기기의 측정값이 아니다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .ply import Mesh, write_ply

EXPOSED_RGB = np.array([230, 40, 40], np.uint8)
HAIR_RGB = np.array([40, 90, 220], np.uint8)


@dataclass
class AnalysisOptions:
    up: tuple[float, float, float] = (0.0, 0.0, 1.0)
    front: tuple[float, float, float] | None = None  # 이마 방향 (지도에서 위쪽). None 이면 임의
    scale_mm_per_unit: float | None = None
    roi_depth_mm: float = 110.0  # 정수리에서 아래로 (scale 을 알 때)
    roi_depth_frac: float = 0.45  # 메쉬 높이 대비 비율 (scale 을 모를 때)
    threshold_l: float | None = None  # 수동 L* 임계값 (0-255 스케일). None 이면 Otsu
    smooth_iters: int = 3
    graft_densities: tuple[int, ...] = (30, 40, 50)  # FU/cm² 가정 이식 밀도
    map_px: int = 800


@dataclass
class AnalysisReport:
    units: str
    roi_area: float
    exposed_area: float
    exposed_ratio: float
    threshold_l: float
    n_vertices_roi: int
    graft_estimates: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def vertex_adjacency(faces: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """무방향 간선 목록 (중복 제거)."""
    e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    e = np.sort(e, axis=1)
    e = np.unique(e, axis=0)
    return e[:, 0], e[:, 1]


def smooth_labels(labels: np.ndarray, edges: tuple[np.ndarray, np.ndarray], iters: int) -> np.ndarray:
    """1-ring 다수결 (자기 자신 포함)."""
    a, b = edges
    lab = labels.astype(np.float32)
    for _ in range(iters):
        s = lab.copy()
        cnt = np.ones_like(lab)
        np.add.at(s, a, lab[b])
        np.add.at(s, b, lab[a])
        np.add.at(cnt, a, 1)
        np.add.at(cnt, b, 1)
        lab = (s / cnt > 0.5).astype(np.float32)
    return lab.astype(bool)


def face_areas(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    return 0.5 * np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1)


def lab_lightness(colors: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(colors.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB)[:, 0, 0].astype(np.float32)


def otsu(values: np.ndarray) -> float:
    v = np.clip(values, 0, 255).astype(np.uint8).reshape(-1, 1)
    t, _ = cv2.threshold(v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(t)


def analyze_mesh(mesh: Mesh, opts: AnalysisOptions) -> tuple[AnalysisReport, dict]:
    if mesh.colors is None or not mesh.n_faces:
        raise ValueError("정점 색과 면이 있는 메쉬가 필요합니다 (COLMAP poisson_mesher 결과 등)")
    scale = opts.scale_mm_per_unit or 1.0
    v = mesh.vertices * scale
    up = _unit(opts.up)
    h = v @ up
    top = np.percentile(h, 99.5)  # 떠 있는 잡음 점에 흔들리지 않게
    if opts.scale_mm_per_unit:
        depth = opts.roi_depth_mm
    else:
        depth = opts.roi_depth_frac * (top - np.percentile(h, 0.5))
    roi_v = h >= top - depth

    light = lab_lightness(mesh.colors)
    thr = opts.threshold_l if opts.threshold_l is not None else otsu(light[roi_v])
    exposed_v = (light > thr) & roi_v
    edges = vertex_adjacency(mesh.faces, len(v))
    if opts.smooth_iters:
        exposed_v = smooth_labels(exposed_v, edges, opts.smooth_iters) & roi_v

    f = mesh.faces
    areas = face_areas(v, f)
    roi_f = roi_v[f].sum(axis=1) >= 2
    exposed_f = exposed_v[f].sum(axis=1) >= 2
    roi_area = float(areas[roi_f].sum())
    exposed_area = float(areas[roi_f & exposed_f].sum())

    notes = []
    if opts.scale_mm_per_unit:
        units = "cm2"
        roi_area, exposed_area = roi_area / 100.0, exposed_area / 100.0
        grafts = {f"{d}_FU_per_cm2": int(round(exposed_area * d)) for d in opts.graft_densities}
    else:
        units = "model_units2"
        grafts = {}
        notes.append("스케일 미지정: 면적은 상대값입니다. --rig-radius-mm 또는 --scale 로 mm 스케일을 주세요.")
    ratio = exposed_area / roi_area if roi_area > 0 else 0.0
    if ratio > 0.9 or ratio < 0.01:
        notes.append("노출 비율이 극단값입니다. 흰머리/조명/ROI 설정을 확인하고 --threshold-l 로 조정하세요.")

    report = AnalysisReport(units, roi_area, exposed_area, ratio, thr, int(roi_v.sum()), grafts, notes)
    return report, {"roi_v": roi_v, "exposed_v": exposed_v, "light": light, "v_mm": v, "up": up}


def coverage_mesh(mesh: Mesh, labels: dict, blend: float = 0.55) -> Mesh:
    """ROI 안의 노출 두피는 빨강, 모발은 파랑으로 원래 색에 섞는다."""
    col = mesh.colors.astype(np.float32)
    roi, exp = labels["roi_v"], labels["exposed_v"]
    col[roi & exp] = (1 - blend) * col[roi & exp] + blend * EXPOSED_RGB
    col[roi & ~exp] = (1 - blend) * col[roi & ~exp] + blend * HAIR_RGB
    return Mesh(mesh.vertices, np.clip(col, 0, 255).astype(np.uint8), mesh.faces)


def top_view(mesh: Mesh, labels: dict, opts: AnalysisOptions) -> np.ndarray:
    """정수리 위에서 내려다본 정사영 지도. 왼쪽: 원본 색, 오른쪽: 노출 영역 오버레이. RGB 반환."""
    v, up, roi = labels["v_mm"], labels["up"], labels["roi_v"]
    if opts.front is not None:
        fwd = np.asarray(opts.front, float)
        fwd = _unit(fwd - (fwd @ up) * up)
    else:
        tmp = np.array([1.0, 0, 0]) if abs(up[0]) < 0.9 else np.array([0, 1.0, 0])
        fwd = _unit(tmp - (tmp @ up) * up)
    right = np.cross(fwd, up)

    f = mesh.faces[roi[mesh.faces].sum(axis=1) >= 2]
    x, y, z = v @ right, -(v @ fwd), v @ up
    used = np.unique(f)
    size = opts.map_px
    span = max(np.ptp(x[used]), np.ptp(y[used])) * 1.08 + 1e-9
    cx, cy = (x[used].min() + x[used].max()) / 2, (y[used].min() + y[used].max()) / 2
    px = ((x - cx) / span + 0.5) * (size - 1)
    py = ((y - cy) / span + 0.5) * (size - 1)
    tri = np.round(np.stack([px[f], py[f]], axis=-1) * 16).astype(np.int32)  # 4비트 서브픽셀
    order = np.argsort(z[f].mean(axis=1))  # 낮은 면부터 그려 위쪽 표면이 덮어쓰게 (painter's algorithm)
    cov = coverage_mesh(mesh, labels).colors

    panels = []
    for colors in (mesh.colors, cov):
        fc = colors[f].mean(axis=1)
        img = np.full((size, size, 3), 255, np.uint8)
        for k in order:
            cv2.fillConvexPoly(img, tri[k], tuple(int(c) for c in fc[k]), cv2.LINE_8, 4)
        panels.append(img)

    canvas = np.concatenate([panels[0], np.full((size, 8, 3), 255, np.uint8), panels[1]], axis=1)
    cv2.putText(canvas, "FRONT", (size // 2 - 30, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    if opts.scale_mm_per_unit:
        bar_px = int(round(50.0 / span * (size - 1)))  # 5 cm 스케일바
        y0 = size - 20
        cv2.line(canvas, (20, y0), (20 + bar_px, y0), (0, 0, 0), 3)
        cv2.putText(canvas, "5 cm", (20, y0 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return canvas


def run_analysis(mesh: Mesh, out_dir: str | Path, opts: AnalysisOptions) -> AnalysisReport:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report, labels = analyze_mesh(mesh, opts)
    write_ply(out_dir / "coverage.ply", coverage_mesh(mesh, labels))
    cv2.imwrite(str(out_dir / "top_view.png"), cv2.cvtColor(top_view(mesh, labels, opts), cv2.COLOR_RGB2BGR))
    payload = {"report": asdict(report), "options": asdict(opts)}
    (out_dir / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
