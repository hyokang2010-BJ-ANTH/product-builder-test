"""논문 전문(full text)을 섹션별로 읽어 요약 재료를 만든다.

초록만 쓰면 "면역 특권이 무너진다" 한 줄로 끝나 영상에 담을 내용이 없다.
PMC 오픈액세스 논문은 본문 전체를 XML로 받을 수 있으므로,
서론·방법·결과·고찰·결론을 나눠 읽고 각 섹션에서 중요한 문장을 골라낸다.

추출식 요약이라 문장을 '고르는' 것이지 '이해해서 다시 쓰는' 것은 아니다.
그래서 원문 문장을 그대로 싣고 검수 표시를 붙인다. 편집은 사람이 한다.
"""
import re

# 섹션 제목으로 종류를 판별한다. JATS의 sec-type 속성이 있으면 그쪽을 먼저 본다.
SECTION_KINDS = (
    ("intro", ("introduction", "background", "overview", "intro")),
    ("methods", ("method", "material", "patients", "study design", "search strategy",
                 "data collection", "participants", "protocol", "statistical")),
    ("results", ("result", "finding", "outcome", "efficacy", "safety")),
    ("discussion", ("discussion", "interpretation", "implication", "limitation")),
    ("conclusion", ("conclusion", "conclusions", "summary", "future", "perspective",
                    "take-home", "clinical relevance")),
)

# 본문이 아닌 부속 섹션은 요약 재료에서 뺀다
EXCLUDED_SECTIONS = (
    "reference", "acknowledg", "author contribution", "conflict", "competing",
    "funding", "supplementary", "abbreviation", "ethic", "consent",
    "data availability", "declaration", "disclosure", "appendix", "footnote",
)

CITATION_NOISE = re.compile(r"https?://|doi\.org|\bdoi:|\bet al\b\.?\s*$", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?\s?%|\bp\s*[<=>]\s*0?\.\d+|\b\d{2,}\b", re.IGNORECASE)

# 섹션별로 몇 문장까지 담을지. 결과는 넉넉히, 나머지는 요점만.
SENTENCE_BUDGET = {
    "intro": 3,
    "methods": 3,
    "results": 7,
    "discussion": 4,
    "conclusion": 3,
    "other": 2,
}

KIND_LABELS = {
    "intro": "배경",
    "methods": "연구 방법",
    "results": "주요 결과",
    "discussion": "고찰",
    "conclusion": "결론",
    "other": "그 밖의 내용",
}


def _clean(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    # 본문에는 [1,2] [3-5] 같은 인용 번호가 촘촘히 박혀 있어 읽기를 방해한다
    text = re.sub(r"\s*\[\d[\d,\s–\-]*\]", "", text)
    text = re.sub(r"\s*\(\s*(?:Fig|Figure|Table)\.?\s*\d+[a-zA-Z]?\s*\)", "", text)
    return text.strip()


def _classify(title, sec_type=""):
    blob = f"{sec_type} {title}".lower()
    for kind, keywords in SECTION_KINDS:
        if any(k in blob for k in keywords):
            return kind
    return "other"


def _is_excluded(title, sec_type=""):
    blob = f"{sec_type} {title}".lower()
    return any(x in blob for x in EXCLUDED_SECTIONS)


def _paragraph_texts(sec):
    """섹션 아래 모든 문단을 순서대로 모은다 (하위 섹션 포함)."""
    out = []
    for p in sec.iter("p"):
        text = _clean("".join(p.itertext()))
        if len(text) > 40:
            out.append(text)
    return out


def extract_sections(root):
    """PMC 본문 XML에서 섹션 목록을 뽑는다."""
    body = next(iter(root.iter("body")), None)
    if body is None:
        return []

    sections = []
    for sec in body.findall("sec"):
        title_el = next(iter(sec.iter("title")), None)
        title = _clean("".join(title_el.itertext())) if title_el is not None else ""
        sec_type = sec.attrib.get("sec-type", "")
        if _is_excluded(title, sec_type):
            continue

        paragraphs = _paragraph_texts(sec)
        if not paragraphs:
            continue

        sections.append(
            {
                "title": title or "(제목 없음)",
                "kind": _classify(title, sec_type),
                "paragraphs": paragraphs,
            }
        )

    # <sec> 없이 <p>만 나열된 논문도 있다
    if not sections:
        loose = [_clean("".join(p.itertext())) for p in body.findall("p")]
        loose = [t for t in loose if len(t) > 40]
        if loose:
            sections.append({"title": "본문", "kind": "other", "paragraphs": loose})

    return sections


def _split_sentences(text):
    # 약어(e.g., i.e., vs., Fig.) 뒤에서 잘리지 않도록 대문자 시작을 요구한다
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text)
    return [s.strip() for s in parts if len(s.strip()) > 30]


def pick_key_sentences(section, budget=None):
    """한 섹션에서 중요한 문장을 고른다.

    수치가 든 문장을 우선하되(결과 섹션에서 특히 중요), 원문 순서는 유지해
    읽었을 때 논리가 이어지도록 한다.
    """
    budget = budget or SENTENCE_BUDGET.get(section["kind"], 2)

    sentences = []
    for para in section["paragraphs"]:
        for s in _split_sentences(para):
            if CITATION_NOISE.search(s):
                continue
            sentences.append(s)
    if not sentences:
        return []

    ranked = sorted(sentences, key=lambda s: len(NUMBER_PATTERN.findall(s)), reverse=True)
    chosen = set(ranked[:budget])
    return [s for s in sentences if s in chosen]


# 구조화 초록의 라벨. PubMed 초록은 대개 "Objective: ... Methods: ..." 꼴이다.
ABSTRACT_LABELS = (
    ("intro", ("background", "objective", "objectives", "aim", "aims", "purpose",
               "introduction", "importance", "context")),
    ("methods", ("method", "methods", "materials", "design", "setting", "participants",
                 "patients", "intervention", "interventions", "measurements",
                 "data sources", "study selection", "main outcome", "main outcomes")),
    ("results", ("result", "results", "finding", "findings", "outcome", "outcomes")),
    ("conclusion", ("conclusion", "conclusions", "interpretation", "implication",
                    "implications", "significance", "relevance")),
)
_LABEL_WORDS = sorted(
    {w for _, words in ABSTRACT_LABELS for w in words}, key=len, reverse=True
)
_ABSTRACT_SPLIT = re.compile(
    r"(?=\b(?:" + "|".join(re.escape(w) for w in _LABEL_WORDS) + r")\b\s*:)",
    re.IGNORECASE,
)


# 라벨 없는 초록을 나눌 때 쓰는 단서. 의학 초록은 대체로
# 배경 -> 방법 -> 결과 -> 결론 순으로 서술되고, 문장의 동사가 그 단계를 드러낸다.
_METHOD_CUES = (
    "we integrated", "we performed", "we analyzed", "we analysed", "we conducted",
    "we enrolled", "we investigated", "we used", "we examined", "we assessed",
    "we evaluated", "we compared", "we reviewed", "we searched", "we developed",
    "was performed", "were performed", "were analyzed", "were enrolled",
    "were randomized", "this study", "in this", "using ", "to determine",
    "to evaluate", "to investigate", "to assess",
)
_RESULT_CUES = (
    "revealed", "showed", "demonstrated", "we found", "found that", "resulted",
    "observed", "underwent", "we resolved", "increased", "decreased", "improved",
    "was greater", "were greater", "was higher", "significantly", "compared with",
    "mechanistically", "notably", "interestingly", "among all",
)
# 결론 단서는 문장 첫머리에서만 본다.
# "highlighting", "underscoring" 같은 말은 결과 문장의 부연으로도 흔히 쓰여서
# 단순 포함 검사로 잡으면 결과가 결론으로 밀려난다(실제로 그런 오분류가 있었다).
_CONCLUSION_STARTS = (
    "these findings", "our findings", "these results", "our results",
    "in conclusion", "we conclude", "collectively", "taken together",
    "overall", "in summary", "altogether",
)
_CONCLUSION_TAIL_CUES = (
    "suggest", "indicate", "highlight", "underscore", "offer", "provide insight",
    "warrant", "may serve", "therapeutic", "future",
)


def _stage_of(sentence, index, total):
    low = sentence.lower()
    head = low[:70]

    # 1) 첫머리가 명확히 결론을 알리는 경우
    if any(head.startswith(c) for c in _CONCLUSION_STARTS):
        return "conclusion"

    # 2) 결과 서술이면 결과. 부연에 highlight 같은 말이 붙어도 결과로 둔다.
    if any(c in low for c in _RESULT_CUES):
        return "results"

    if any(c in low for c in _METHOD_CUES):
        return "methods"

    # 3) 마지막 문장이 마무리 표현을 담고 있으면 결론으로 본다
    if index == total - 1 and any(c in low for c in _CONCLUSION_TAIL_CUES):
        return "conclusion"

    # 앞부분은 대체로 배경 설명이다
    return "intro" if index < max(1, total // 3) else "results"


def _group_plain_abstract(sentences):
    """라벨 없는 초록을 배경·방법·결과·결론으로 묶는다.

    정확한 분류는 아니지만, 8문장이 한 덩어리로 붙어 있는 것보다
    편집할 때 훨씬 고르기 쉽다. 문장 순서는 원문 그대로 둔다.
    """
    total = len(sentences)
    buckets = {"intro": [], "methods": [], "results": [], "conclusion": []}
    for i, s in enumerate(sentences):
        buckets[_stage_of(s, i, total)].append(s)

    titles = {
        "intro": "Background", "methods": "Methods",
        "results": "Results", "conclusion": "Conclusion",
    }
    out = []
    for kind in ("intro", "methods", "results", "conclusion"):
        if buckets[kind]:
            out.append(
                {
                    "label": KIND_LABELS[kind],
                    "title": titles[kind] + " (자동 구분)",
                    "kind": kind,
                    "sentences": buckets[kind],
                }
            )
    return out


def summarize_abstract(abstract, max_sentences_per_part=6):
    """초록을 섹션처럼 나눠 요약 재료로 만든다.

    최근 30일 논문은 출판사 엠바고 때문에 PMC에 거의 올라오지 않는다(실측 0/15일).
    그래서 대부분의 날은 초록이 유일한 재료다. 구조화 초록이면 라벨을 살려
    배경·방법·결과·결론으로 나누고, 아닌 경우에도 문장을 넉넉히 싣는다.
    """
    abstract = (abstract or "").strip()
    if not abstract:
        return {"sections": [], "section_count": 0, "sentence_count": 0}

    chunks = [c.strip() for c in _ABSTRACT_SPLIT.split(abstract) if c.strip()]
    sections = []

    # 라벨이 하나도 없으면 통짜 초록이다. 문장의 서술 방식으로 나눠 편집하기 쉽게 만든다.
    if len(chunks) <= 1:
        sentences = [s for s in _split_sentences(abstract) if not CITATION_NOISE.search(s)]
        if not sentences:
            sentences = [abstract]
        sections.extend(_group_plain_abstract(sentences[: max_sentences_per_part + 3]))
    else:
        for chunk in chunks:
            head, _, rest = chunk.partition(":")
            label_word = head.strip().lower()
            body = rest.strip() or chunk

            kind = "other"
            for k, words in ABSTRACT_LABELS:
                if label_word in words:
                    kind = k
                    break

            sentences = [s for s in _split_sentences(body) if not CITATION_NOISE.search(s)]
            if not sentences:
                sentences = [body] if len(body) > 30 else []
            if not sentences:
                continue

            sections.append(
                {
                    "label": KIND_LABELS.get(kind, "내용"),
                    "title": head.strip().title() or "Abstract",
                    "kind": kind,
                    "sentences": sentences[:max_sentences_per_part],
                }
            )

    return {
        "sections": sections,
        "section_count": len(sections),
        "sentence_count": sum(len(s["sentences"]) for s in sections),
        "source": "abstract",
    }


def summarize_fulltext(root):
    """본문을 섹션별로 요약한 결과를 돌려준다.

    반환: {"sections": [{"label","title","kind","sentences":[...]}, ...],
           "section_count": n, "sentence_count": m}
    """
    sections = extract_sections(root)
    if not sections:
        return {"sections": [], "section_count": 0, "sentence_count": 0}

    # 같은 종류가 여러 개면(예: Results 1, Results 2) 뒤쪽은 예산을 줄인다
    seen_kinds = {}
    summarized = []
    for sec in sections:
        kind = sec["kind"]
        seen_kinds[kind] = seen_kinds.get(kind, 0) + 1
        budget = SENTENCE_BUDGET.get(kind, 2)
        if seen_kinds[kind] > 1:
            budget = max(1, budget // 2)

        sentences = pick_key_sentences(sec, budget)
        if not sentences:
            continue
        summarized.append(
            {
                "label": KIND_LABELS.get(kind, "내용"),
                "title": sec["title"],
                "kind": kind,
                "sentences": sentences,
            }
        )

    return {
        "sections": summarized,
        "section_count": len(summarized),
        "sentence_count": sum(len(s["sentences"]) for s in summarized),
    }
