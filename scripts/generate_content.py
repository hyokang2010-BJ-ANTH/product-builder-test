"""검색된 논문/뉴스 중 오늘 다룰 주제 1건을 선정하고, 60초 쇼츠용 대본을 생성한다.

주의: 별도의 번역/LLM API를 사용하지 않으므로, 논문 초록(영문)은 원문 인용으로 대본에 포함되고
"[검수 필요]" 표시가 붙는다. 업로드 전 사람이 한 번 다듬는 것을 권장한다.
"""
import re

from common import (
    EXCLUDED_PUBTYPES,
    EXCLUDED_TITLE_PREFIXES,
    RELEVANCE_KEYWORDS,
    USED_TOPICS_PATH,
    load_json,
    save_json,
    today_str,
)
from search_sources import fetch_abstract, search_news, search_pubmed

NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\s?%|\b\d+(?:,\d{3})*(?:\.\d+)?\b")
# 초록에 섞여 들어오는 인용/링크 문장은 대본으로 읽을 수 없으므로 하이라이트에서 제외한다
CITATION_PATTERN = re.compile(r"https?://|doi\.org|\bdoi:", re.IGNORECASE)


def is_publishable(paper):
    """쇼츠 소재로 쓸 수 있는 원논문인지 확인한다.

    PubMed는 철회 공지("RETRACTION: ...")나 정오표도 최신 문헌으로 색인한다.
    이런 글이 선정되면 철회된 연구를 최신 성과처럼 소개하게 되므로 반드시 걸러야 한다.
    """
    types = {str(t).strip().lower() for t in (paper.get("pubtypes") or [])}
    if types & EXCLUDED_PUBTYPES:
        return False
    title = (paper.get("title") or "").strip().lower()
    return not title.startswith(EXCLUDED_TITLE_PREFIXES)


def is_on_topic(title):
    """제목에 탈모/모발 핵심 키워드가 있는지 확인한다.

    PubMed 쿼리는 초록까지 훑기 때문에, 모발 샘플을 다뤘을 뿐 주제는 다른 논문
    (예: 두피 백선 진단법)이 걸릴 수 있다. 제목 기준으로 한 번 더 거른다.
    """
    lowered = (title or "").lower()
    return any(k in lowered for k in RELEVANCE_KEYWORDS)


def pick_topic():
    used = load_json(USED_TOPICS_PATH, {"ids": []})
    used_ids = set(used.get("ids", []))

    papers = [p for p in search_pubmed() if is_publishable(p)]
    fresh = [p for p in papers if p["id"] not in used_ids]

    # 1순위: 제목에 탈모/모발 키워드가 있는 논문
    for p in fresh:
        if is_on_topic(p["title"]):
            abstract = fetch_abstract(p["pmid"])
            if not abstract:
                continue  # 사설·코멘터리 등 초록 없는 글은 대본을 만들 수 없다
            p["abstract"] = abstract
            return p, used

    # 2순위: 제목엔 없지만 초록에 키워드가 충분히 나오는 논문
    for p in fresh:
        abstract = fetch_abstract(p["pmid"])
        if is_on_topic(abstract):
            p["abstract"] = abstract
            return p, used

    news = search_news()
    for n in news:
        if n["id"] not in used_ids:
            return n, used

    # 모두 소진된 경우: 사용 이력을 초기화하고 주제에 맞는 논문/뉴스를 재사용
    on_topic = [p for p in papers if is_on_topic(p["title"])]
    if on_topic:
        on_topic[0]["abstract"] = fetch_abstract(on_topic[0]["pmid"])
        return on_topic[0], {"ids": []}
    if news:
        return news[0], {"ids": []}
    return None, used


def extract_highlights(abstract, max_items=3):
    """초록에서 핵심 포인트로 쓸 문장을 고른다.

    수치(%, 표본수)가 든 문장을 우선하되, 수치가 거의 없는 리뷰 논문에서도
    씬을 채울 수 있도록 나머지 문장으로 정원을 채운다. 예전에는 수치가 있는
    문장만 남겨서 리뷰 논문이면 포인트가 1개로 줄고 씬 하나가 통째로 비었다.
    """
    if not abstract:
        return []

    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", abstract)
        if len(s.strip()) > 20 and not CITATION_PATTERN.search(s)
    ]
    if not sentences:
        return []

    # 수치가 많은 순으로 뽑되(동점이면 초록 순서 유지)…
    ranked = sorted(sentences, key=lambda s: len(NUMBER_PATTERN.findall(s)), reverse=True)
    chosen = set(ranked[:max_items])
    # …대본 흐름이 자연스럽도록 초록에 나온 순서대로 되돌린다
    return [s for s in sentences if s in chosen]


def build_script_for_paper(paper):
    highlights = extract_highlights(paper.get("abstract", ""))
    authors = ", ".join(paper.get("authors") or []) or "연구진"
    hook = f"오늘 새로 나온 탈모 연구, 이거 안 보면 손해입니다."
    body_lines = [
        f"오늘 소개할 논문은 《{paper['journal']}》에 실린",
        f"\"{paper['title']}\" 입니다. ({authors} 외, {paper.get('pub_date', '')})",
        "",
        "핵심 내용은 이렇습니다:",
    ]
    for h in highlights:
        body_lines.append(f"- {h.strip()} [검수 필요: 한글 번역/의역 확인]")
    cta = "더 자세한 내용은 원문 링크에서 확인하세요. 매일 새로운 탈모 연구, 팔로우하고 놓치지 마세요!"

    script_text = "\n".join(
        [hook, "", *body_lines, "", cta]
    )
    return {
        "hook": hook,
        "intro": f"《{paper['journal']}》 - {paper['title']}",
        "highlights": highlights,
        "cta": cta,
        "full_script": script_text,
        "reference_url": paper["url"],
        "reference_title": paper["title"],
        "reference_type": "paper",
    }


def build_script_for_news(article):
    hook = "오늘 탈모 관련 최신 소식, 3줄 요약해드립니다."
    summary = article.get("summary") or article.get("title")
    body_lines = [
        f"오늘의 소식: {article['title']}",
        f"({article.get('source_name', '') or '뉴스'}, {article.get('pub_date', '')})",
        "",
        "요약:",
        f"- {summary} [검수 필요: 원문 대조 확인]",
    ]
    cta = "원문은 링크에서 확인하세요. 매일 새로운 탈모 소식, 놓치지 마세요!"
    script_text = "\n".join([hook, "", *body_lines, "", cta])
    return {
        "hook": hook,
        "intro": article["title"],
        "highlights": [summary],
        "cta": cta,
        "full_script": script_text,
        "reference_url": article["url"],
        "reference_title": article["title"],
        "reference_type": "news",
    }


def generate():
    topic, used = pick_topic()
    if topic is None:
        raise RuntimeError("검색 결과가 없습니다 (네트워크 또는 소스 응답 확인 필요)")

    if topic["source_type"] == "paper":
        script = build_script_for_paper(topic)
    else:
        script = build_script_for_news(topic)

    used_ids = set(used.get("ids", []))
    used_ids.add(topic["id"])
    save_json(USED_TOPICS_PATH, {"ids": sorted(used_ids)})

    return {
        "date": today_str(),
        "topic": topic,
        "script": script,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(generate(), ensure_ascii=False, indent=2))
