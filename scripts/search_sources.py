"""탈모/모발이식 관련 최신 논문(PubMed) 및 뉴스(Google News RSS)를 검색한다.
외부 API 키가 필요 없는 무료 소스만 사용한다.
"""
import re
import time
import urllib.parse as up
import xml.etree.ElementTree as ET

import feedparser
import requests

from common import PUBMED_QUERY, NEWS_QUERIES

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
HEADERS = {"User-Agent": "hair-content-automation/1.0"}
TIMEOUT = 20

# NCBI E-utilities는 API 키 없이 초당 3회로 제한된다.
# 이를 넘기면 429가 떨어지므로 모든 요청 사이에 최소 간격을 강제한다.
MIN_REQUEST_INTERVAL = 0.4
RETRY_STATUSES = (429, 500, 502, 503, 504)

_last_request_at = 0.0


def _eutils_get(endpoint, params, max_retries=4):
    """E-utilities 요청을 레이트 리밋을 지키며 보내고, 일시적 오류는 재시도한다."""
    global _last_request_at

    last_error = None
    for attempt in range(max_retries):
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)

        try:
            r = requests.get(
                f"{EUTILS}/{endpoint}", params=params, headers=HEADERS, timeout=TIMEOUT
            )
        except requests.RequestException as e:
            last_error = e
            _last_request_at = time.monotonic()
            if attempt == max_retries - 1:
                raise
            time.sleep(2**attempt)
            continue

        _last_request_at = time.monotonic()

        if r.status_code in RETRY_STATUSES and attempt < max_retries - 1:
            # 429는 잠시 뒤 대체로 풀리므로 지수 백오프로 물러섰다 재시도한다
            time.sleep(2**attempt)
            continue

        r.raise_for_status()
        return r

    if last_error:
        raise last_error
    raise RuntimeError(f"E-utilities 요청 실패: {endpoint}")


def search_pubmed(max_results=15):
    """최근 30일 이내 탈모/모발 관련 논문 목록을 반환한다."""
    params = {
        "db": "pubmed",
        "term": PUBMED_QUERY,
        "retmode": "json",
        "retmax": max_results,
        "sort": "most+recent",
    }
    r = _eutils_get("esearch.fcgi", params)
    ids = r.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    sum_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
    r = _eutils_get("esummary.fcgi", sum_params)
    summary = r.json().get("result", {})

    papers = []
    for pmid in ids:
        item = summary.get(pmid)
        if not item:
            continue
        papers.append(
            {
                "source_type": "paper",
                "pmid": pmid,
                "title": item.get("title", "").strip().rstrip("."),
                "journal": item.get("fulljournalname") or item.get("source", ""),
                "pub_date": item.get("pubdate", ""),
                "authors": [a.get("name") for a in item.get("authors", [])][:3],
                # 철회 공지·정오표 등을 걸러내는 데 쓴다 (예: "Retraction of Publication")
                "pubtypes": item.get("pubtype") or [],
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "id": f"pmid:{pmid}",
            }
        )
    return papers


def fetch_abstract(pmid):
    """논문 초록(원문 영어)을 가져온다.

    XML로 받아 <Abstract> 안의 <AbstractText>만 읽는다.

    두 가지를 피하기 위한 구조다:
    - text 모드로 받아 "가장 긴 문단"을 고르면 저자 명단이 초록으로 잘못 선택된다.
    - <OtherAbstract>에는 같은 논문의 번역본(프랑스어 등)이 들어 있어, 전체
      <AbstractText>를 훑으면 영문 초록에 외국어 번역이 뒤섞인다.
    """
    r = _eutils_get("efetch.fcgi", {"db": "pubmed", "id": pmid, "retmode": "xml"})

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return ""

    chunks = []
    # iter("Abstract")는 태그명이 정확히 일치할 때만 걸리므로 <OtherAbstract>는 제외된다
    for abstract in root.iter("Abstract"):
        for node in abstract.iter("AbstractText"):
            # itertext(): <i>, <sub> 같은 중첩 태그 안의 글자까지 모두 모은다
            text = "".join(node.itertext()).strip()
            if not text:
                continue
            label = node.get("Label")  # 구조화 초록의 BACKGROUND/METHODS/RESULTS 등
            chunks.append(f"{label.capitalize()}: {text}" if label else text)

    return re.sub(r"\s+", " ", " ".join(chunks)).strip()


def search_news(max_per_query=5):
    """Google News RSS로 한글 뉴스 기사를 검색한다 (API 키 불필요)."""
    articles = []
    seen_links = set()
    for q in NEWS_QUERIES:
        url = (
            "https://news.google.com/rss/search?q="
            + up.quote(q)
            + "&hl=ko&gl=KR&ceid=KR:ko"
        )
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue
        for entry in feed.entries[:max_per_query]:
            link = entry.get("link", "")
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            articles.append(
                {
                    "source_type": "news",
                    "title": entry.get("title", "").strip(),
                    "source_name": entry.get("source", {}).get("title", "") if hasattr(entry, "source") else "",
                    "pub_date": entry.get("published", ""),
                    "summary": re.sub("<[^<]+?>", "", entry.get("summary", "")).strip(),
                    "url": link,
                    "id": f"news:{link}",
                    "query": q,
                }
            )
    return articles


if __name__ == "__main__":
    import json

    papers = search_pubmed()
    news = search_news()
    print(json.dumps({"papers": papers, "news": news}, ensure_ascii=False, indent=2)[:3000])
