# 탈모/모발이식 콘텐츠 자동화

매일 아침 10시(KST)에 탈모·모발이식·모발관련 최신 논문(PubMed)과 뉴스를 자동 검색해
쇼츠(60초 숏폼)용 대본과 영상 제작용 이미지, PPT를 자동 생성합니다.
아이폰 홈 화면에 아이콘을 추가해 PWA로 확인할 수 있습니다.

## 구성 요소

```
scripts/                파이프라인 코드 (Python)
  search_sources.py      PubMed E-utilities + Google News RSS 검색 (무료, API 키 불필요)
  generate_content.py    주제 선정 + 대본 생성 (중복 방지, data/used_topics.json 기록)
  image_sources.py       Wikimedia Commons 무료 이미지 검색 + 한글 폰트 확보
  generate_images.py     논문 표지 카드 + 주제 이미지 + 개인사진 슬롯 + 최종 프레임 합성
  generate_pptx.py       영상 제작용 PPT 생성 (씬별 슬라이드 + 스피커 노트에 대본)
  pipeline.py            전체 파이프라인 실행 (매일 자동 실행되는 진입점)
  send_push.py           웹 푸시 알림 발송 (선택, VAPID 키 필요)
  generate_vapid_keys.py 웹 푸시용 VAPID 키 생성 (최초 1회)
  generate_pwa_icons.py  PWA/홈 화면 아이콘 생성 (최초 1회, 이미 생성되어 있음)

templates/shortform_template.json   60초 쇼츠 씬 구성 템플릿 (숏폼 제작 템플릿)

data/                   매일 생성되는 결과물 (자동 커밋됨)
  used_topics.json       이미 다룬 논문/기사 ID 기록 (중복 방지)
  YYYY-MM-DD/             해당 날짜 결과: script.txt, result.json, paper_card.png,
                          images/frame_0N_*.png (씬별 프레임), slides.pptx, image_credits.json

pwa/                    GitHub Pages로 배포되는 대시보드 (아이폰 홈 화면 앱)
  index.html, app.js, manifest.json, service-worker.js, icons/
  data/latest.json, data/latest/  파이프라인이 매일 갱신하는 최신 결과 (자동 생성)

assets/my-photo/latest.jpg   개인 사진 슬롯 (직접 교체)
assets/fonts/                무료 한글 폰트 (Black Han Sans, Noto Sans KR - OFL 라이선스)

.github/workflows/
  daily-content.yml       매일 01:00 UTC(=10:00 KST) 파이프라인 실행 + 결과 커밋/푸시
  pages.yml               pwa/ 변경 시 GitHub Pages 자동 배포
```

## 자동화 활성화 방법 (최초 1회)

1. 이 브랜치를 `main`에 병합하세요. **GitHub Actions의 스케줄(cron)은 기본 브랜치에서만 동작합니다.**
2. 저장소 **Settings → Pages → Build and deployment → Source** 를 **GitHub Actions**로 설정하세요.
3. (선택) `workflow_dispatch`로 `daily-content` 워크플로를 한 번 수동 실행해 첫 콘텐츠를 생성하세요.
4. 몇 분 후 `https://<사용자명>.github.io/<저장소명>/` 에서 대시보드가 보입니다.

## 아이폰 홈 화면 아이콘 + 알림

1. 아이폰 Safari로 Pages 주소를 엽니다.
2. 공유 버튼(⬆️) → **홈 화면에 추가** → 저장하면 앱 아이콘이 생성됩니다.
3. 홈 화면 아이콘으로 앱을 실행한 뒤 **"🔔 알림 받기"** 버튼을 누르면:
   - 앱을 열 때마다 새 콘텐츠가 있으면 로컬 알림을 표시합니다 (기본 동작, 추가 설정 불필요).
   - 앱이 꺼져 있어도 오는 **실시간 푸시**를 받으려면 아래 "실시간 푸시 설정"을 완료하세요.

### 실시간 푸시 설정 (선택, 앱이 꺼져 있어도 알림 수신)

GitHub Pages는 정적 호스팅이라 자체적으로 구독 정보를 저장할 서버가 없습니다.
1인 사용을 전제로 아래처럼 가볍게 구성했습니다.

1. `pip install pywebpush` 후 `python scripts/generate_vapid_keys.py` 실행
2. 출력된 **Private Key**를 저장소 **Settings → Secrets and variables → Actions** 에
   `VAPID_PRIVATE_KEY` 이름으로 등록
3. 출력된 **Public Key**를 `pwa/app.js` 상단 `VAPID_PUBLIC_KEY` 값에 붙여넣고 커밋/푸시
4. 아이폰에서 "🔔 알림 받기"를 누르면 화면에 구독 JSON이 표시됩니다. 이 내용을
   `data/push_subscriptions.json` 파일에 배열 형태로 (GitHub 웹에서 직접 편집) 붙여넣고 커밋 — **최초 1회만**
   ```json
   [
     { "endpoint": "...", "keys": { "p256dh": "...", "auth": "..." } }
   ]
   ```
5. 다음 날 자동 실행부터 `data/push_subscriptions.json`에 등록된 기기로 알림이 전송됩니다.

이 단계를 건너뛰어도 3번(로컬 알림)까지는 정상 동작합니다.

## 숏폼 제작 템플릿

`templates/shortform_template.json`이 60초 쇼츠의 씬 구성(훅 → 논문 소개 → 핵심 포인트 2개 →
내 코멘트 → CTA)을 정의합니다. 매일 이 템플릿에 맞춰
`data/YYYY-MM-DD/images/frame_01_hook.png` ~ `frame_06_cta.png` (1080×1920, 9:16) 가
생성되며, 이미지를 순서대로 CapCut/Premiere/VN 등에 임포트해 컷 편집만 하면 됩니다.
같은 구성으로 만들어진 `slides.pptx`는 슬라이드 노트에 해당 구간 대본이 들어 있어
프롬프터나 더빙 스크립트로 바로 활용할 수 있습니다.

## 이미지 구성

- **논문/기사 표지 카드**: 저작권 문제 없이 직접 렌더링한 카드 이미지 (제목/저널/날짜)
- **주제 관련 이미지**: Wikimedia Commons에서 라이선스(CC0/Public Domain/CC-BY 계열)를
  확인한 이미지만 사용하고, 출처는 `data/YYYY-MM-DD/image_credits.json`에 기록됩니다.
  CC-BY 계열은 영상 크레딧에 작가명을 표기해주세요.
- **내 사진**: `assets/my-photo/latest.jpg`를 본인 사진으로 교체하면 자동 반영됩니다
  (자세한 내용은 `assets/my-photo/README.md`).

## 로컬에서 수동 실행

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/pipeline.py
```

## 알아두어야 할 한계

- **대본 번역 검수 필요**: 별도 LLM/번역 API를 쓰지 않아 논문 초록은 영문 그대로
  인용되고 `[검수 필요]` 표시가 붙습니다. 업로드 전 한 번 다듬는 것을 권장합니다.
- **매일 새 주제 자동 선택**: `data/used_topics.json`에 이미 다룬 논문/기사를 기록해
  중복을 피합니다. 검색 결과가 모두 소진되면 자동으로 초기화됩니다.
- **PubMed 검색 범위**: 최근 30일 이내 발행된 논문만 대상으로 합니다.
- **무료 이미지 소스 한계**: 주제와 정확히 일치하는 이미지가 없으면 안내 문구가 담긴
  플레이스홀더가 대신 사용됩니다 (자동 재시도는 다음 날 실행 시 이루어집니다).
