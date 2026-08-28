"""웹 푸시 알림 발송 (선택 기능).

GitHub Pages는 정적 호스팅이라 별도 서버 없이는 구독 정보를 자동으로 받을 수 없다.
그래서 1인 사용을 전제로 아래처럼 가볍게 구성한다:
  1) scripts/generate_vapid_keys.py 로 VAPID 키를 한 번 생성해 GitHub Secrets에 등록
  2) PWA(index.html)에서 "알림 받기" 버튼으로 구독을 생성하면 화면에 구독 JSON이 표시됨
  3) 그 JSON을 data/push_subscriptions.json 에 (GitHub 웹 UI에서) 붙여넣고 커밋 - 최초 1회만
  4) 이후 매일 파이프라인이 끝나면 이 스크립트가 등록된 구독자에게 알림을 보낸다
VAPID_PRIVATE_KEY가 설정되지 않았거나 구독자가 없으면 조용히 건너뛴다.
"""
import json
import os

from common import DATA_DIR

SUBS_PATH = os.path.join(DATA_DIR, "push_subscriptions.json")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_CONTACT = os.environ.get("VAPID_CONTACT_EMAIL", "mailto:hyokang2010@gmail.com")


def _load_subscriptions():
    if not os.path.exists(SUBS_PATH):
        return []
    with open(SUBS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def notify_new_content(title, date_str):
    if not VAPID_PRIVATE_KEY:
        print("VAPID_PRIVATE_KEY 미설정 - 웹 푸시 알림 건너뜀 (README '알림 설정' 참고)")
        return

    subs = _load_subscriptions()
    if not subs:
        print("등록된 구독자가 없어 웹 푸시 알림을 건너뜀")
        return

    from pywebpush import WebPushException, webpush

    payload = json.dumps(
        {
            "title": "오늘의 탈모 콘텐츠가 준비됐어요",
            "body": title,
            "date": date_str,
            "url": "./",
        },
        ensure_ascii=False,
    )

    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_CONTACT},
            )
            print("푸시 알림 발송 완료")
        except WebPushException as e:
            print(f"푸시 발송 실패 (구독 만료 가능성): {e}")
