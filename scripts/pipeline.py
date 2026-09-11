"""전체 파이프라인 실행 스크립트.

1. 논문/뉴스 검색 및 주제 선정, 대본 생성
2. 이미지 생성 (논문 카드 + 주제 이미지 + 개인사진 슬롯 + 최종 프레임)
3. PPTX 생성
4. data/YYYY-MM-DD/ 에 결과 저장, pwa/data/latest.json 갱신 (PWA 대시보드용)
5. (선택) 웹 푸시 알림 발송 - VAPID 키가 설정된 경우에만 동작

GitHub Actions에서 매일 01:00 UTC(=10:00 KST)에 실행된다.
"""
import json
import os
import shutil
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import DATA_DIR, PWA_DATA_DIR, day_dir, ensure_dirs, save_json, today_str
from generate_content import generate
from generate_images import generate_all_images
from generate_pptx import build_pptx


def build_archive_index():
    """지난 아티클을 모아 볼 수 있도록 날짜별 요약 목록을 만든다.

    PWA가 이 파일 하나만 받아 전체 목록을 그린다. 각 항목의 상세 자료는
    data/<날짜>/ 아래에 그대로 있으므로 중복 저장하지 않는다.
    """
    import glob

    items = []
    for result_path in sorted(glob.glob(os.path.join(DATA_DIR, "2*", "result.json")), reverse=True):
        try:
            with open(result_path, encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        topic = r.get("topic", {})
        script = r.get("script", {})
        assets = r.get("assets", {})
        day = os.path.basename(os.path.dirname(result_path))
        items.append(
            {
                "date": r.get("date", day),
                "dir": day,
                "title": topic.get("title", ""),
                "journal": topic.get("journal") or topic.get("source_name", ""),
                "source_type": topic.get("source_type", "paper"),
                "url": topic.get("url", ""),
                "hook_accent": script.get("hook_accent", ""),
                "hook_sub": script.get("hook_sub", ""),
                "thumb": f"{day}/{assets.get('paper_card', 'paper_card.png')}",
                "pptx": f"{day}/{assets.get('pptx', 'slides.pptx')}",
                "has_paper_figures": bool(assets.get("paper_figures")),
            }
        )

    index = {"count": len(items), "updated": today_str(), "items": items}
    save_json(os.path.join(DATA_DIR, "index.json"), index)
    save_json(os.path.join(PWA_DATA_DIR, "index.json"), index)
    print(f"  아카이브 인덱스 갱신: {len(items)}건")
    return index


def run():
    date_str = today_str()
    d = day_dir(date_str)

    print(f"[1/4] 검색 및 대본 생성 중... ({date_str})")
    content = generate()

    print("[2/4] 이미지 생성 중...")
    images = generate_all_images(content, d)

    print("[3/4] PPTX 생성 중...")
    pptx_path = os.path.join(d, "slides.pptx")
    build_pptx(
        content,
        images["frames"],
        pptx_path,
        paper_assets=images.get("paper_assets"),
        day_dir=d,
    )

    print("[4/4] 결과 저장 중...")
    with open(os.path.join(d, "script.txt"), "w", encoding="utf-8") as f:
        f.write(content["script"]["full_script"])

    paper_assets = images.get("paper_assets") or {}
    result = {
        "date": date_str,
        "topic": content["topic"],
        "script": content["script"],
        "assets": {
            "paper_card": os.path.relpath(images["paper_card"], d),
            "topic_images": [os.path.relpath(p, d) for p in images["topic_images"]],
            "frames": [os.path.relpath(p, d) for p in images["frames"]],
            "pptx": os.path.relpath(pptx_path, d),
            "paper_figures": [
                {
                    "label": f.get("label"),
                    "caption": f.get("caption"),
                    "path": os.path.relpath(f["path"], d),
                }
                for f in (paper_assets.get("figures") or [])
                if f.get("path")
            ],
            "paper_tables": paper_assets.get("tables") or [],
            "paper_source": paper_assets.get("source"),
            "paper_skip_reason": paper_assets.get("skip_reason"),
            "paper_figure_note": paper_assets.get("figure_note"),
        },
    }
    save_json(os.path.join(d, "result.json"), result)

    # PWA 대시보드가 읽을 최신 데이터 갱신 (data/<date>/ 를 그대로 pwa/data/latest 로 복사)
    ensure_dirs(PWA_DATA_DIR)
    pwa_latest_dir = os.path.join(PWA_DATA_DIR, "latest")
    if os.path.exists(pwa_latest_dir):
        shutil.rmtree(pwa_latest_dir)
    shutil.copytree(d, pwa_latest_dir)
    save_json(os.path.join(PWA_DATA_DIR, "latest.json"), result)

    build_archive_index()

    print(f"완료: data/{date_str}/ 및 pwa/data/latest 에 저장됨")

    try:
        from send_push import notify_new_content

        notify_new_content(content["topic"]["title"], date_str)
    except Exception as e:
        print(f"(웹 푸시 알림은 건너뜀: {e})")

    return result


if __name__ == "__main__":
    try:
        run()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
