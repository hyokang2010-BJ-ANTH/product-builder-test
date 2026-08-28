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

## ⚠️ 먼저 확인: 이 저장소는 현재 **공개(public)** 상태입니다

생성되는 모든 콘텐츠와 **`assets/my-photo/latest.jpg`에 올리는 본인 사진이 인터넷에 공개**됩니다.
사진을 올릴 계획이라면 먼저 저장소를 비공개로 바꾸는 것을 권장합니다:
**Settings → 맨 아래 Danger Zone → Change repository visibility → Make private**

> 참고: 비공개로 바꾸면 GitHub Pages는 유료 플랜(Pro 이상)에서만 동작합니다.
> 무료 플랜을 유지하려면 저장소는 공개로 두되 본인 사진은 넣지 않는 방법도 있습니다
> (그 경우 "내 코멘트" 씬은 자동 생성된 배경 이미지로 채워집니다).

## 자동화 활성화 방법 (최초 1회)

**현재 이 저장소의 기본 브랜치는 `claude/hair-content-automation-pmaa4z` 입니다.**
`main` 브랜치는 존재하지 않으며, 병합할 필요가 없습니다. 스케줄(cron)은 기본 브랜치에서만
동작하는데 이미 조건을 만족하므로, 아래 두 가지만 하면 됩니다.

1. **Actions 활성화 확인** — 저장소 상단 **Actions** 탭을 엽니다.
   - "Workflows aren't being run on this repository" 같은 안내와 함께 초록색
     **I understand my workflows, go ahead and enable them** 버튼이 보이면 눌러주세요.
   - 왼쪽 목록에 `Daily Hair Content Automation`이 보이면 이미 활성화된 상태입니다.
2. **Pages 활성화** — **Settings → Pages → Build and deployment → Source** 를
   **GitHub Actions**로 설정합니다.

그다음 **Actions → Daily Hair Content Automation → Run workflow** 로 한 번 수동 실행하면
첫 콘텐츠가 생성되고, 이어서 Pages 배포가 자동으로 따라옵니다. 몇 분 뒤
`https://hyokang2010-bj-anth.github.io/product-builder-test/` 에서 대시보드를 볼 수 있습니다.

이후에는 매일 오전 10시(KST)에 자동으로 실행됩니다.

> 기본 브랜치 이름을 나중에 `main`으로 바꾸고 싶다면
> **Settings → Branches → 브랜치 이름 옆 연필 아이콘**에서 변경할 수 있습니다.
> `.github/workflows/pages.yml`의 `branches:` 목록에 `main`도 이미 포함되어 있어
> 이름을 바꿔도 그대로 동작합니다.

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

## 업로드 전 확인할 것 (중요)

이 파이프라인은 **초안 생성기**입니다. 아래 두 가지는 사람이 직접 확인해야 합니다.

1. **영문 초록의 번역·의역** — 별도 번역 API를 쓰지 않아 논문 초록이 영문 그대로
   인용되고 `[검수 필요]` 표시가 붙습니다. 그대로 읽지 말고 다듬어주세요.
2. **논문이 실제로 그 주장을 하는지** — 자동 추출은 초록의 문장을 고르는 것이지
   내용을 이해하는 것이 아닙니다. 의학 정보인 만큼 원문 링크로 한 번 확인하세요.

## 자동 걸러내는 것들 (실제 운영에서 발견해 대응한 사례)

초기 자동 실행에서 아래 문제들이 실제로 발생해 방어 로직을 넣었습니다.
비슷한 증상이 다시 보이면 해당 지점을 살펴보세요.

| 증상 | 원인 | 대응 위치 |
| --- | --- | --- |
| 탈모와 무관한 논문 선정 (두피 백선 진단법 등) | `scalp` 키워드가 지나치게 광범위 | `common.py`의 `PUBMED_QUERY`, `RELEVANCE_KEYWORDS` |
| 대본에 저자 명단이 초록 대신 노출 | efetch 텍스트 파싱이 "가장 긴 문단"을 초록으로 오인 | `search_sources.fetch_abstract` (XML 파싱) |
| 철회(RETRACTION) 공지가 최신 논문으로 선정 | PubMed는 철회 공지·정오표도 함께 색인 | `generate_content.is_publishable` |
| 429 Too Many Requests로 실행 실패 | NCBI는 API 키 없이 초당 3회 제한 | `search_sources._eutils_get` (간격 강제 + 백오프) |
| 핵심 포인트가 1개만 나와 씬이 빔 | 수치 없는 리뷰 논문에서 문장이 전부 탈락 | `generate_content.extract_highlights` |

## 그 밖의 동작 방식

- **매일 새 주제 자동 선택**: `data/used_topics.json`에 이미 다룬 논문/기사를 기록해
  중복을 피합니다. 검색 결과가 모두 소진되면 자동으로 초기화됩니다.
- **PubMed 검색 범위**: 최근 30일 이내 발행된 논문만 대상으로 합니다.
- **무료 이미지 소스 한계**: 주제와 정확히 일치하는 이미지가 없으면 안내 문구가 담긴
  플레이스홀더가 대신 사용됩니다 (자동 재시도는 다음 날 실행 시 이루어집니다).
- **실행 실패 확인**: Actions 탭에서 빨간 X가 보이면 로그를 확인하세요. 외부 소스
  장애로 실패해도 다음 날 정상 실행되며, 그날 데이터만 비게 됩니다.
- **저장소 용량**: 하루 생성물은 약 2MB(프레임 6장 + PPT)이고 `pwa/data/latest`
  사본까지 더하면 하루 4MB 안팎입니다. 1년이면 1.5GB 정도이므로 당장은 문제없지만,
  오래 운영하면 정리가 필요합니다. 과거 데이터는 `git rm -r data/2026-01-*` 처럼
  지워도 커밋 히스토리에 남아 언제든 되살릴 수 있습니다.
- **이미지 관련성**: 'hair'라는 단어는 청각 유모세포(hair cell)나 식물 뿌리털에도
  쓰여서 무관한 사진이 걸릴 수 있습니다. 대표적인 것들은 자동으로 걸러내지만
  (`image_sources.IMAGE_EXCLUDE_PATTERNS`), 어색한 이미지가 보이면 그 목록에
  키워드를 추가하세요.
