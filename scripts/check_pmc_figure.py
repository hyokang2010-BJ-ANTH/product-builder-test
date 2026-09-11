"""PMC 논문 그림을 실제로 내려받을 수 있는지 점검하는 진단 도구.

매일 선정되는 논문이 달라서 그림 다운로드 경로를 확인하기 어렵기 때문에,
PMC ID를 직접 지정해 후보 URL을 하나씩 시험해 보고 결과를 표로 보여준다.

사용:
    python scripts/check_pmc_figure.py PMC13548128
    (GitHub Actions의 "Diagnose PMC figures" 워크플로로도 실행 가능)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from paper_figures import (
    HEADERS,
    fetch_oa_package,
    figure_from_package,
    TIMEOUT,
    _candidate_image_urls,
    _license_ok,
    extract_figures,
    extract_tables,
    fetch_pmc_article,
)


def main(pmcid):
    print(f"=== {pmcid} 점검 ===\n")

    root = fetch_pmc_article(pmcid)
    if root is None:
        print("본문 XML을 불러오지 못했습니다.")
        return 1

    ok, reason = _license_ok(root)
    print(f"라이선스: {reason} (사용가능={ok})")

    figures = extract_figures(root, pmcid, max_items=3)
    tables = extract_tables(root, max_items=2)
    print(f"본문에서 찾은 그림 {len(figures)}개, 표 {len(tables)}개\n")

    if not figures:
        print("그림이 없는 논문입니다.")
        return 0

    # 1) 공식 경로: OA 패키지
    import tempfile

    workdir = tempfile.mkdtemp()
    print("--- OA 패키지 경로 ---")
    package_dir = fetch_oa_package(pmcid, workdir)
    if package_dir:
        files = sorted(os.listdir(package_dir))
        print(f"패키지에서 이미지 {len(files)}개 확보: {', '.join(files[:6])}"
              + (" ..." if len(files) > 6 else ""))
        for i, fig in enumerate(figures, 1):
            path = figure_from_package(fig, package_dir, workdir, i)
            print(f"  {'OK ' if path else '실패'} {fig['label']} ({fig['file']})"
                  + (f" -> {os.path.getsize(path)//1024}KB" if path else ""))
    else:
        print("패키지를 받지 못했습니다.")

    # 2) 예전 경로: 본문이 가리키는 /bin/ URL (참고용)
    print("\n--- /bin/ 직접 접근 (참고) ---")
    for fig in figures:
        print(f"[{fig['label']}] 원본 파일명: {fig['file']}")
        found = False
        for url in _candidate_image_urls(pmcid, fig["file"]):
            try:
                r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True,
                                 stream=True)
                ctype = r.headers.get("Content-Type", "")
                size = r.headers.get("Content-Length", "?")
                mark = "OK " if (r.status_code == 200 and ctype.startswith("image/")) else "   "
                print(f"  {mark}{r.status_code} {ctype:<24} {size:>9}  {url}")
                r.close()
                if r.status_code == 200 and ctype.startswith("image/"):
                    found = True
                    break
            except Exception as e:
                print(f"     ERR {type(e).__name__:<24}            {url}")
        if not found:
            print("  -> 이 그림은 어떤 후보 URL로도 받을 수 없습니다.")
        print()
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "PMC13548128"
    sys.exit(main(target))
