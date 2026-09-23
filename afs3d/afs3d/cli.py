"""명령행 진입점: python -m afs3d <command> ...

  check        촬영 품질 리포트 (흔들림/노출)
  prep         전처리 (색/노출 정규화, 마스크, 리사이즈)
  reconstruct  COLMAP 재구성 (sparse, --dense 시 메쉬까지)
  analyze      메쉬에서 두피 노출 면적/지도 계산
  run          check → prep → reconstruct → analyze 일괄 실행
  demo         합성 두상 촬영 세트 생성 (실제 환자 사진 없이 시험)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analysis import AnalysisOptions, run_analysis
from .io_utils import load_shots
from .ply import read_ply
from .preprocess import PrepOptions, preprocess_shots
from .quality import assess_shots, write_report
from .reconstruct import ReconOptions, reconstruct


def _add_input(p: argparse.ArgumentParser) -> None:
    p.add_argument("--images", required=True, help="AFS 에서 내보낸 사진 폴더")
    p.add_argument("--manifest", help="촬영 각도 CSV (filename, azimuth_deg, elevation_deg, radius_mm, focal_px)")


def _add_prep(p: argparse.ArgumentParser) -> None:
    p.add_argument("--max-side", type=int, default=3200, help="긴 변 최대 픽셀 (0=원본 유지)")
    p.add_argument("--no-color-norm", action="store_true", help="화이트밸런스/노출 정규화 끄기")
    p.add_argument("--mask", action="store_true", help="단색 배경 가정 전경 마스크 생성")
    p.add_argument("--drop-flagged", action="store_true", help="품질 플래그가 붙은 사진 제외")


def _add_recon(p: argparse.ArgumentParser) -> None:
    p.add_argument("--mode", choices=["sfm", "rig"], default="sfm")
    p.add_argument("--matcher", choices=["auto", "exhaustive", "sequential"], default="auto")
    p.add_argument("--multi-camera", action="store_true", help="여러 대의 카메라로 촬영한 경우")
    p.add_argument("--rig-radius-mm", type=float, help="카메라-머리중심 거리(mm). sfm 결과를 mm 로 스케일링")
    p.add_argument("--focal-px", type=float, help="rig 모드 초점거리(원본 해상도 픽셀)")
    p.add_argument("--dense", action="store_true", help="조밀 재구성 + Poisson 메쉬 (CUDA 필요)")
    p.add_argument("--colmap", default="colmap", help="COLMAP 실행 파일 경로")
    p.add_argument("--dry-run", action="store_true", help="COLMAP 명령만 출력")


def _add_analysis(p: argparse.ArgumentParser) -> None:
    p.add_argument("--scale", type=float, help="모델 단위 → mm 배율 (reconstruction.json 값보다 우선)")
    p.add_argument("--up", type=float, nargs=3, help="위쪽 벡터 (기본: reconstruction.json 또는 0 0 1)")
    p.add_argument("--front", type=float, nargs=3, help="이마 방향 벡터 (지도에서 위쪽)")
    p.add_argument("--roi-depth-mm", type=float, default=110.0, help="정수리에서 아래로 분석할 깊이(mm)")
    p.add_argument("--threshold-l", type=float, help="두피/모발 구분 L* 임계값 (0-255, 기본 Otsu 자동)")


def _manifest_default(args) -> str | None:
    if args.manifest:
        return args.manifest
    guess = Path(args.images).parent / "manifest.csv"
    return str(guess) if guess.exists() else None


def cmd_check(args) -> int:
    shots = load_shots(args.images, _manifest_default(args))
    results = assess_shots(shots)
    out = Path(args.out) / "quality.csv"
    write_report(results, out)
    bad = [r for r in results if r.flags]
    print(f"{len(results)}장 점검, 플래그 {len(bad)}장 → {out}")
    for r in bad:
        print(f"  {r.name}: {', '.join(r.flags)}")
    return 0


def _prep(args, shots):
    if args.drop_flagged:
        results = assess_shots(shots)
        write_report(results, Path(args.work) / "quality.csv")
        flagged = {r.name for r in results if r.flags}
        shots = [s for s in shots if s.name not in flagged]
        print(f"품질 플래그 {len(flagged)}장 제외 → {len(shots)}장 사용")
    opts = PrepOptions(max_side=args.max_side or None, normalize_color=not args.no_color_norm, make_masks=args.mask)
    preprocess_shots(shots, args.work, opts)
    print(f"전처리 완료 → {Path(args.work) / 'images'}")
    return shots


def cmd_prep(args) -> int:
    _prep(args, load_shots(args.images, _manifest_default(args)))
    return 0


def _recon_opts(args) -> ReconOptions:
    return ReconOptions(
        mode=args.mode,
        matcher=args.matcher,
        single_camera=not args.multi_camera,
        dense=args.dense,
        rig_radius_mm=args.rig_radius_mm,
        focal_px=args.focal_px,
        colmap=args.colmap,
        dry_run=args.dry_run,
    )


def _rig_radius_from_manifest(shots) -> float | None:
    radii = {s.radius_mm for s in shots if s.radius_mm}
    return radii.pop() if len(radii) == 1 else None


def cmd_reconstruct(args) -> int:
    shots = load_shots(args.images, _manifest_default(args))
    opts = _recon_opts(args)
    if opts.rig_radius_mm is None:
        opts.rig_radius_mm = _rig_radius_from_manifest(shots)
    res = reconstruct(args.work, shots, opts)
    _print_recon(res)
    return 0


def _print_recon(res: dict) -> None:
    if "n_registered" in res:
        print(f"등록된 사진 {res['n_registered']}/{res['n_input']}장, 모델: {res['model']}")
    if "scale_mm_per_unit" in res:
        print(f"스케일: 1 모델단위 = {res['scale_mm_per_unit']:.4f} mm ({res.get('rig_fit', 'rig')} 피팅)")
    if "mesh" in res:
        print(f"메쉬: {res['mesh']}")


def _analysis_opts(args, recon: dict) -> AnalysisOptions:
    return AnalysisOptions(
        up=tuple(args.up or recon.get("up", (0, 0, 1))),
        front=tuple(args.front) if args.front else (tuple(recon["front"]) if "front" in recon else None),
        scale_mm_per_unit=args.scale or recon.get("scale_mm_per_unit"),
        roi_depth_mm=args.roi_depth_mm,
        threshold_l=args.threshold_l,
    )


def _print_report(rep, out_dir) -> None:
    unit = "cm²" if rep.units == "cm2" else "(상대 단위)²"
    print(f"두피 ROI 면적 {rep.roi_area:.1f} {unit}, 노출 두피 {rep.exposed_area:.1f} {unit} ({rep.exposed_ratio:.1%})")
    for k, v in rep.graft_estimates.items():
        print(f"  이식 밀도 {k.split('_')[0]} FU/cm² 가정 시 약 {v} 모낭단위")
    for n in rep.notes:
        print("  주의:", n)
    print(f"결과 → {out_dir} (report.json, coverage.ply, top_view.png)")


def cmd_analyze(args) -> int:
    recon = {}
    if args.work and (Path(args.work) / "reconstruction.json").exists():
        recon = json.loads((Path(args.work) / "reconstruction.json").read_text())
    mesh_path = args.mesh or recon.get("mesh")
    if not mesh_path:
        print("메쉬 경로가 없습니다 (--mesh 또는 --dense 재구성 결과 필요)", file=sys.stderr)
        return 2
    out = Path(args.out or Path(args.work or ".") / "analysis")
    rep = run_analysis(read_ply(mesh_path), out, _analysis_opts(args, recon))
    _print_report(rep, out)
    return 0


def cmd_run(args) -> int:
    shots = load_shots(args.images, _manifest_default(args))
    shots = _prep(args, shots)
    opts = _recon_opts(args)
    if opts.rig_radius_mm is None:
        opts.rig_radius_mm = _rig_radius_from_manifest(shots)
    res = reconstruct(args.work, shots, opts)
    _print_recon(res)
    if "mesh" in res and not args.dry_run:
        out = Path(args.work) / "analysis"
        rep = run_analysis(read_ply(res["mesh"]), out, _analysis_opts(args, res))
        _print_report(rep, out)
    elif not args.dry_run:
        print("메쉬가 없어 분석 단계를 건너뜁니다 (--dense 필요, 또는 외부 메쉬로 `analyze --mesh`).")
    return 0


def cmd_demo(args) -> int:
    from .synthetic import make_dataset

    out = make_dataset(args.out, seed=args.seed)
    print(f"합성 촬영 세트 생성 → {out}/images (100장), manifest.csv, ground_truth.ply")
    print(f"다음: python -m afs3d run --images {out}/images --work {out}/work --mask")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="afs3d", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("check", help="촬영 품질 리포트")
    _add_input(s)
    s.add_argument("--out", default="work")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("prep", help="전처리")
    _add_input(s)
    _add_prep(s)
    s.add_argument("--work", default="work")
    s.set_defaults(func=cmd_prep)

    s = sub.add_parser("reconstruct", help="COLMAP 재구성 (prep 이후)")
    _add_input(s)
    _add_recon(s)
    s.add_argument("--work", default="work")
    s.set_defaults(func=cmd_reconstruct)

    s = sub.add_parser("analyze", help="메쉬 분석")
    s.add_argument("--mesh", help="PLY 메쉬 (정점 색 포함). 없으면 work/reconstruction.json 의 메쉬")
    s.add_argument("--work", help="reconstruction.json 이 있는 작업 폴더 (스케일/방향 자동)")
    s.add_argument("--out")
    _add_analysis(s)
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("run", help="전체 파이프라인")
    _add_input(s)
    _add_prep(s)
    _add_recon(s)
    _add_analysis(s)
    s.add_argument("--work", default="work")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("demo", help="합성 데이터 생성")
    s.add_argument("--out", default="demo_data")
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
