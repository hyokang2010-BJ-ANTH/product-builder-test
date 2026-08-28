"""무료 이미지 소스 (Wikimedia Commons) 검색/다운로드 + 폰트 확보 유틸리티."""
import os
import re
import html
import time

import requests

from common import ROOT

# 위키미디어는 연락처가 없는 User-Agent를 정책적으로 차단한다.
# (https://meta.wikimedia.org/wiki/User-Agent_policy)
# 개인 이메일 대신 공개 저장소 주소를 연락처로 쓴다.
HEADERS = {
    "User-Agent": (
        "hair-content-automation/1.0 "
        "(+https://github.com/hyokang2010-BJ-ANTH/product-builder-test)"
    )
}
TIMEOUT = 20
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

MIN_REQUEST_INTERVAL = 0.5
RETRY_STATUSES = (429, 500, 502, 503, 504)
_last_request_at = 0.0


def _polite_get(url, **kwargs):
    """위키미디어 요청을 간격을 지켜 보내고, 429/5xx는 백오프 후 재시도한다."""
    global _last_request_at

    for attempt in range(4):
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)

        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kwargs)
        _last_request_at = time.monotonic()

        if r.status_code in RETRY_STATUSES and attempt < 3:
            time.sleep(2**attempt)
            continue

        r.raise_for_status()
        return r

    r.raise_for_status()
    return r


ALLOWED_LICENSE_PREFIXES = ("cc0", "public domain", "cc by")

FONT_DIR = os.path.join(ROOT, "assets", "fonts")
FONT_PATH = os.path.join(FONT_DIR, "BlackHanSans-Regular.ttf")
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/blackhansans/BlackHanSans-Regular.ttf"

BODY_FONT_PATH = os.path.join(FONT_DIR, "NotoSansKR-Regular.ttf")
BODY_FONT_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf"
)


def _strip_html(text):
    return re.sub("<[^<]+?>", "", html.unescape(text or "")).strip()


def _is_license_ok(license_short):
    if not license_short:
        return False
    return license_short.strip().lower().startswith(ALLOWED_LICENSE_PREFIXES)


def wikimedia_search_images(keyword, limit=3):
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": f"{keyword} filetype:bitmap",
        "srnamespace": 6,
        "srlimit": limit,
    }
    r = _polite_get(COMMONS_API, params=params)
    titles = [item["title"] for item in r.json().get("query", {}).get("search", [])]

    results = []
    for title in titles:
        info = _get_image_info(title)
        if info:
            results.append(info)
    return results


def _get_image_info(title):
    params = {
        "action": "query",
        "format": "json",
        "titles": title,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size",
        "iiurlwidth": 1080,
    }
    r = _polite_get(COMMONS_API, params=params)
    pages = r.json().get("query", {}).get("pages", {})
    for page in pages.values():
        infos = page.get("imageinfo")
        if not infos:
            continue
        info = infos[0]
        meta = info.get("extmetadata", {})
        license_short = meta.get("LicenseShortName", {}).get("value", "")
        if not _is_license_ok(license_short):
            continue
        return {
            "title": title,
            "url": info.get("thumburl") or info.get("url"),
            "license": license_short,
            "artist": _strip_html(meta.get("Artist", {}).get("value", "")),
            "credit": _strip_html(meta.get("Credit", {}).get("value", "")),
            "source_page": f"https://commons.wikimedia.org/wiki/{title.replace(' ', '_')}",
        }
    return None


def download_image(info, dest_path):
    r = _polite_get(info["url"])
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(r.content)
    return dest_path


def _download_font(url, dest_path):
    os.makedirs(FONT_DIR, exist_ok=True)
    try:
        r = _polite_get(url)
        with open(dest_path, "wb") as f:
            f.write(r.content)
        return dest_path
    except Exception:
        return None


def ensure_display_font():
    """헤드라인용 한글 폰트(Black Han Sans, OFL)를 확보한다. 실패 시 None."""
    if os.path.exists(FONT_PATH):
        return FONT_PATH
    return _download_font(FONT_URL, FONT_PATH)


def ensure_body_font():
    """본문용 한글 폰트(Noto Sans KR, OFL)를 확보한다. 실패 시 None."""
    if os.path.exists(BODY_FONT_PATH):
        return BODY_FONT_PATH
    return _download_font(BODY_FONT_URL, BODY_FONT_PATH)
