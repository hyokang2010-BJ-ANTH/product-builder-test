"""무료 이미지 소스 (Wikimedia Commons) 검색/다운로드 + 폰트 확보 유틸리티."""
import os
import re
import html

import requests

from common import ROOT

HEADERS = {"User-Agent": "hair-content-automation/1.0"}
TIMEOUT = 20
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

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
    r = requests.get(COMMONS_API, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
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
    r = requests.get(COMMONS_API, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
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
    r = requests.get(info["url"], headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(r.content)
    return dest_path


def _download_font(url, dest_path):
    os.makedirs(FONT_DIR, exist_ok=True)
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
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
