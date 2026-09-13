"""검색된 논문/뉴스 중 오늘 다룰 주제 1건을 선정하고, 60초 쇼츠용 대본을 생성한다.

주의: 별도의 번역/LLM API를 사용하지 않으므로, 논문 초록(영문)은 원문 인용으로 대본에 포함되고
"[검수 필요]" 표시가 붙는다. 업로드 전 사람이 한 번 다듬는 것을 권장한다.
"""
import re

from common import (
    ANIMAL_JOURNAL_HINTS,
    ANIMAL_KEYWORDS,
    EXCLUDED_PUBTYPES,
    EXCLUDED_TITLE_PREFIXES,
    OFF_TOPIC_PHRASES,
    OFF_TOPIC_WORD_PREFIXES,
    PLANT_JOURNAL_PREFIXES,
    RELEVANCE_KEYWORDS,
    USED_TOPICS_PATH,
    has_word_prefix,
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
    if title.startswith(EXCLUDED_TITLE_PREFIXES):
        return False

    # 사람 대상 채널이므로 동물 연구는 뺀다
    words = set(re.findall(r"[a-z]+", title))
    if words & set(ANIMAL_KEYWORDS):
        return False
    journal = (paper.get("journal") or "").lower()
    if any(h in journal for h in ANIMAL_JOURNAL_HINTS):
        return False

    return True


def is_off_topic(text):
    """"hair"가 들어가지만 사람 모발과 무관한 분야인지 확인한다.

    "hair" 한 낱말만 보면 식물 뿌리털(root hair), 내이 유모세포(hair cell)까지 걸린다.
    실제로 애기장대 가뭄 내성 논문이 "root hair growth"라는 제목으로 선정된 적이 있다.
    """
    lowered = (text or "").lower()
    if any(p in lowered for p in OFF_TOPIC_PHRASES):
        return True
    return has_word_prefix(lowered, OFF_TOPIC_WORD_PREFIXES)


def is_on_topic(title, journal=""):
    """제목에 탈모/모발 핵심 키워드가 있는지 확인한다.

    PubMed 쿼리는 초록까지 훑기 때문에, 모발 샘플을 다뤘을 뿐 주제는 다른 논문
    (예: 두피 백선 진단법)이 걸릴 수 있다. 제목 기준으로 한 번 더 거른다.
    """
    lowered = (title or "").lower()
    if not any(k in lowered for k in RELEVANCE_KEYWORDS):
        return False
    if is_off_topic(lowered):
        return False
    # 저널이 식물·농학 분야면 제목이 어떻든 사람 모발 연구가 아니다
    return not has_word_prefix(journal, PLANT_JOURNAL_PREFIXES)


def pick_topic():
    used = load_json(USED_TOPICS_PATH, {"ids": []})
    used_ids = set(used.get("ids", []))

    # 제목 기준으로만 주제를 판정하므로 후보를 넉넉히 받아온다
    papers = [p for p in search_pubmed(max_results=30) if is_publishable(p)]
    fresh = [p for p in papers if p["id"] not in used_ids]

    # 1순위: 제목에 탈모/모발 키워드가 있는 논문
    for p in fresh:
        if is_on_topic(p["title"], p.get("journal", "")):
            abstract = fetch_abstract(p["pmid"])
            if not abstract:
                continue  # 사설·코멘터리 등 초록 없는 글은 대본을 만들 수 없다
            # 제목만으로 가려지지 않는 분야는 초록에서 한 번 더 거른다.
            # 초록은 배제에만 쓴다. 선정에 쓰면 부작용으로 탈모를 한 줄 언급한
            # 항암제 논문까지 통과한다(실제로 폐암 논문이 선정된 적이 있다).
            if is_off_topic(abstract):
                continue
            p["abstract"] = abstract
            return p, used

    # 초록 기준 판정은 쓰지 않는다. 항암제 논문처럼 부작용으로 탈모를 한 줄 언급한
    # 무관한 연구가 통과하기 때문이다(실제로 폐암 논문이 선정된 적이 있다).
    # 제목에 맞는 논문이 없으면 차라리 뉴스로 넘어간다.
    news = search_news()
    for n in news:
        if n["id"] not in used_ids:
            return n, used

    # 모두 소진된 경우: 사용 이력을 초기화하고 주제에 맞는 논문/뉴스를 재사용
    for p in papers:
        if not is_on_topic(p["title"], p.get("journal", "")):
            continue
        abstract = fetch_abstract(p["pmid"])
        if abstract and not is_off_topic(abstract):
            p["abstract"] = abstract
            return p, {"ids": []}
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


PERCENT_PATTERN = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")
SAMPLE_PATTERN = re.compile(r"\b(\d{2,6})\s+(?:patients|participants|subjects|men|women|cases)\b", re.I)

# 논문 주제를 한눈에 알리는 키워드 (제목에서 찾으면 훅 소재로 쓴다)
HOOK_TOPIC_WORDS = [
    ("transplant", "모발이식"),
    ("minoxidil", "미녹시딜"),
    ("finasteride", "피나스테리드"),
    ("dutasteride", "두타스테리드"),
    ("stem cell", "줄기세포"),
    ("exosome", "엑소좀"),
    ("microneedl", "마이크로니들"),
    ("laser", "레이저"),
    ("platelet-rich", "PRP"),
    ("jak", "JAK 억제제"),
    ("alopecia areata", "원형탈모"),
    ("androgenetic", "남성형 탈모"),
    ("female pattern", "여성형 탈모"),
    ("ultrasound", "초음파 진단"),
    ("regenerat", "모발 재생"),
]


def build_hook_parts(paper, highlights):
    """첫 화면에 쓸 (강조구, 설명구)를 논문마다 다르게 만든다.

    매일 같은 문구를 띄우면 팔로워가 금세 지나치므로, 논문에서 가장 강한
    숫자나 주제어를 뽑아 첫 줄을 바꾼다. 읽는 순서는 강조구 -> 설명구로 유지한다.
    """
    blob = " ".join([paper.get("abstract", "") or ""] + list(highlights or []))
    title = (paper.get("title") or "").lower()

    # 1순위: 인상적인 퍼센트 (너무 작거나 100 초과인 값은 제외)
    pcts = [float(p) for p in PERCENT_PATTERN.findall(blob)]
    pcts = [p for p in pcts if 5 <= p <= 100]
    if pcts:
        best = max(pcts)
        best_txt = f"{best:g}%"
        return best_txt, "이 숫자, 탈모 연구가 새로 내놨습니다"

    # 2순위: 표본 규모 (숫자가 클수록 신뢰 신호가 된다)
    samples = [int(s) for s in SAMPLE_PATTERN.findall(blob)]
    if samples:
        n = max(samples)
        if n >= 100:
            return f"{n:,}명", "대규모 연구에서 나온 결과입니다"

    # 3순위: 제목의 주제 키워드
    for key, label in HOOK_TOPIC_WORDS:
        if key in title:
            return label, "오늘 나온 최신 연구를 정리했습니다"

    # 마지막: 저널 권위로 승부
    journal = (paper.get("journal") or "").split(":")[0].strip()
    if journal:
        return "오늘의 논문", f"{journal}에 실린 새 연구입니다"
    return "오늘의 탈모 연구", "새로 나온 논문을 정리했습니다"


def fetch_fulltext_summary(paper):
    """PMC 오픈액세스면 본문을 받아 섹션별로 요약한다. 없으면 None.

    그림과 달리 본문 텍스트는 정상적으로 받아진다(PMC가 막는 것은 이미지 파일이다).
    """
    try:
        from paper_figures import fetch_pmc_article, pmid_to_pmcid
        from paper_fulltext import summarize_fulltext
    except ImportError as e:
        print(f"  전문 요약 모듈을 불러오지 못했습니다: {e}")
        return None

    from paper_fulltext import summarize_abstract

    def from_abstract(reason):
        """전문을 못 쓸 때 초록이라도 섹션으로 나눠 쓴다.

        최근 30일 논문은 엠바고 탓에 PMC에 거의 없어서(실측 0/15일)
        실제로는 이 경로가 기본이 된다.
        """
        summary = summarize_abstract(paper.get("abstract", ""))
        if summary["section_count"]:
            print(
                f"  {reason} - 초록을 {summary['section_count']}개 항목, "
                f"{summary['sentence_count']}문장으로 정리했습니다"
            )
        return summary or None

    pmid = paper.get("pmid")
    if not pmid:
        return from_abstract("PMID 없음")

    pmcid = pmid_to_pmcid(pmid)
    if not pmcid:
        return from_abstract("전문 미공개(PMC 없음)")

    root = fetch_pmc_article(pmcid)
    if root is None:
        return from_abstract("전문 내려받기 실패")

    summary = summarize_fulltext(root)
    if summary["section_count"]:
        print(
            f"  전문 요약 확보: {summary['section_count']}개 섹션, "
            f"{summary['sentence_count']}문장 ({pmcid})"
        )
        paper["pmcid"] = pmcid
        summary["source"] = "fulltext"
        return summary

    return from_abstract(f"본문 섹션을 찾지 못함 ({pmcid})")


def build_script_for_paper(paper, fulltext=None):
    """편집용 상세 대본을 만든다.

    초록 문장 몇 개만 싣던 예전 방식은 "면역 특권이 무너진다" 한 줄로 끝나
    영상으로 만들 내용이 없었다. 본문을 받아올 수 있으면 배경·방법·결과·고찰·결론을
    섹션별로 싣는다. 길이를 줄이는 대신 재료를 충분히 주고, 편집은 사람이 한다.
    """
    highlights = extract_highlights(paper.get("abstract", ""))
    authors = ", ".join(paper.get("authors") or []) or "연구진"
    accent, sub = build_hook_parts(paper, highlights)
    hook = f"{accent} {sub}"
    cta = "더 자세한 내용은 원문 링크에서 확인하세요. 매일 새로운 탈모 연구, 팔로우하고 놓치지 마세요!"

    sections = (fulltext or {}).get("sections") or []

    lines = [
        f"[훅] {hook}",
        "",
        "[논문 정보]",
        f"제목: {paper['title']}",
        f"저널: {paper['journal']}",
        f"저자: {authors} 외",
        f"발행: {paper.get('pub_date', '')}",
        f"원문: {paper['url']}",
        "",
        "[한눈에 보기]",
    ]
    for h in highlights:
        lines.append(f"- {h.strip()}")

    if sections:
        is_fulltext = (fulltext or {}).get("source") == "fulltext"
        if is_fulltext:
            header = f"[상세 내용] (논문 전문 {len(sections)}개 섹션에서 발췌)"
        else:
            header = (
                f"[상세 내용] (초록 {len(sections)}개 항목 정리 "
                "— 이 논문은 전문이 아직 공개되지 않아 초록을 씁니다)"
            )
        lines += ["", header]
        for sec in sections:
            lines += ["", f"◆ {sec['label']} — {sec['title']}"]
            for sentence in sec["sentences"]:
                lines.append(f"  · {sentence}")
    else:
        lines += [
            "",
            "[상세 내용]",
            "  초록을 읽지 못해 정리할 내용이 없습니다. 원문 링크를 확인하세요.",
        ]

    lines += [
        "",
        "[CTA] " + cta,
        "",
        "-" * 60,
        "※ 위 본문 문장은 논문 원문을 그대로 발췌한 것입니다(영문).",
        "   번역·의역과 사실 확인을 거친 뒤 영상에 사용하세요.",
        "   자동 추출은 문장을 고르는 것이지 내용을 이해하는 것이 아닙니다.",
    ]

    script_text = "\n".join(lines)
    return {
        "hook": hook,
        "hook_accent": accent,
        "hook_sub": sub,
        "intro": f"《{paper['journal']}》 - {paper['title']}",
        "highlights": highlights,
        "sections": sections,
        "cta": cta,
        "full_script": script_text,
        "reference_url": paper["url"],
        "reference_title": paper["title"],
        "reference_type": "paper",
    }


def build_script_for_news(article):
    accent, sub = "탈모 뉴스", "오늘 나온 소식을 3줄로 정리했습니다"
    hook = f"{accent} {sub}"
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
        "hook_accent": accent,
        "hook_sub": sub,
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
        script = build_script_for_paper(topic, fetch_fulltext_summary(topic))
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
