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
