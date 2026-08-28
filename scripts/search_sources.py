"""탈모/모발이식 관련 최신 논문(PubMed) 및 뉴스(Google News RSS)를 검색한다.
외부 API 키가 필요 없는 무료 소스만 사용한다.
"""
import re
import time
import urllib.parse as up

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
    """논문 초록(원문 영어)을 가져온다."""
    params = {"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "text"}
    r = requests.get(f"{EUTILS}/efetch.fcgi", params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    text = r.text.strip()
    # efetch abstract 텍스트 정리: 제목/저자 라인 이후 본문만 추출 시도
    parts = re.split(r"\n\n+", text)
    abstract = ""
    for p in parts:
        p = p.strip()
        if len(p) > 200 and not p.lower().startswith(("author information", "doi:", "pmid:")):
            abstract = p
            break
    if not abstract and parts:
        abstract = max(parts, key=len)
    return re.sub(r"\s+", " ", abstract).strip()


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
