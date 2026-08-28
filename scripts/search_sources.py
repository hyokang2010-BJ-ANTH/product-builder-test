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
HEADERS = {"User-Agent": "hair-content-automation/1.0 (contact: hyokang2010@gmail.com)"}
TIMEOUT = 20


def search_pubmed(max_results=15):
    """최근 30일 이내 탈모/모발 관련 논문 목록을 반환한다."""
    params = {
        "db": "pubmed",
        "term": PUBMED_QUERY,
        "retmode": "json",
        "retmax": max_results,
        "sort": "most+recent",
    }
    r = requests.get(f"{EUTILS}/esearch.fcgi", params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    ids = r.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    time.sleep(0.4)
    sum_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
    r = requests.get(f"{EUTILS}/esummary.fcgi", params=sum_params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
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
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "id": f"pmid:{pmid}",
            }
        )
    return papers


def fetch_abstract(pmid):
    """논문 초록(원문 영어)을 가져온다.

    XML로 받아 <AbstractText> 태그만 읽는다. 예전에는 text 모드 응답을
    빈 줄 기준으로 잘라 "가장 긴 문단"을 초록으로 골랐는데, 저자가 많은 논문에서는
    저자 명단 블록이 초록으로 잘못 선택돼 대본에 이름들이 그대로 나갔다.
    """
    params = {"db": "pubmed", "id": pmid, "retmode": "xml"}
    r = requests.get(f"{EUTILS}/efetch.fcgi", params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return ""

    chunks = []
    for node in root.iter("AbstractText"):
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
