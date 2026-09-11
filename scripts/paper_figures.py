"""논문 본문의 표(table)와 그림(figure)을 가져온다.

PubMed 초록만으로는 영상이 밋밋해서, 논문에 실린 실제 그래프·표를 화면에 띄우기 위한 모듈이다.
PubMed Central(PMC) 오픈액세스 논문만 대상으로 하며, 재배포가 허용된 라이선스인지 확인한다.

흐름:
  PMID -> (ID Converter) -> PMCID -> (efetch db=pmc) -> 본문 XML
       -> <fig>/<table-wrap> 추출 -> 이미지 내려받기
비공개(구독) 논문은 그림을 쓸 수 없으므로 빈 결과를 돌려주고, 호출부가 기존 방식으로 진행한다.
"""
import os
import re
import xml.etree.ElementTree as ET

from search_sources import _eutils_get, HEADERS, TIMEOUT

import requests

ID_CONVERTER = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
PMC_IMG_BASE = "https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/bin/{fname}"

# 재배포가 가능한 라이선스만 사용한다. PMC 오픈액세스라도 일부는
# "구독자 열람만 가능"이라 본문 그림을 영상에 쓸 수 없다.
REUSABLE_LICENSE_HINTS = (
    "creativecommons.org/licenses",
    "creativecommons.org/publicdomain",
    "cc by",
    "cc-by",
    "public domain",
    "open access",
)
NON_REUSABLE_HINTS = ("no commercial", "noncommercial", "non-commercial", "nc/")


def pmid_to_pmcid(pmid):
    """PMID를 PMCID로 바꾼다. PMC에 없으면 None."""
    try:
        r = requests.get(
            ID_CONVERTER,
            params={"ids": pmid, "format": "json", "tool": "hair-content-automation"},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        records = r.json().get("records", [])
        if records and records[0].get("pmcid"):
            return records[0]["pmcid"]
    except Exception as e:
        print(f"  PMCID 변환 실패 (pmid {pmid}): {e}")
    return None


def _license_ok(root):
    """본문 XML의 라이선스 표기를 보고 그림 재사용이 가능한지 판단한다."""
    texts = []
    for lic in root.iter():
        tag = lic.tag.lower()
        if tag.endswith("license") or tag.endswith("permissions"):
            texts.append(" ".join(lic.itertext()).lower())
            for k, v in lic.attrib.items():
                if "href" in k.lower():
                    texts.append(v.lower())
    blob = " ".join(texts)
    if not blob:
        return False, "라이선스 표기 없음"
    if any(h in blob for h in NON_REUSABLE_HINTS):
        return False, "비상업적 이용 한정 라이선스"
    if any(h in blob for h in REUSABLE_LICENSE_HINTS):
        return True, "재사용 가능 라이선스"
    return False, "재사용 가능 여부 불명"


def _clean(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def fetch_pmc_article(pmcid):
    """PMC 본문 XML을 가져온다."""
    numeric = pmcid.replace("PMC", "")
    r = _eutils_get("efetch.fcgi", {"db": "pmc", "id": numeric, "retmode": "xml"})
    try:
        return ET.fromstring(r.content)
    except ET.ParseError as e:
        print(f"  PMC XML 파싱 실패 ({pmcid}): {e}")
        return None


def extract_figures(root, pmcid, max_items=3):
    """<fig> 요소에서 그림 파일명과 설명을 뽑는다."""
    figures = []
    for fig in root.iter("fig"):
        if len(figures) >= max_items:
            break
        graphic = None
        for g in fig.iter("graphic"):
            for k, v in g.attrib.items():
                if k.endswith("href"):
                    graphic = v
                    break
            if graphic:
                break
        if not graphic:
            continue

        label = _clean("".join(next(iter(fig.iter("label")), ET.Element("x")).itertext()))
        caption_el = next(iter(fig.iter("caption")), None)
        caption = _clean("".join(caption_el.itertext())) if caption_el is not None else ""
        figures.append(
            {
                "kind": "figure",
                "label": label or "Figure",
                "caption": caption,
                "file": graphic,
                "pmcid": pmcid,
            }
        )
    return figures


def extract_tables(root, max_items=2):
    """<table-wrap>에서 표의 제목과 내용을 행 단위로 뽑는다.

    표 이미지는 별도로 제공되지 않는 경우가 많아, 셀 값을 읽어 직접 그려 쓴다.
    """
    tables = []
    for tw in root.iter("table-wrap"):
        if len(tables) >= max_items:
            break
        label = _clean("".join(next(iter(tw.iter("label")), ET.Element("x")).itertext()))
        caption_el = next(iter(tw.iter("caption")), None)
        caption = _clean("".join(caption_el.itertext())) if caption_el is not None else ""

        rows = []
        for tr in tw.iter("tr"):
            cells = [_clean("".join(td.itertext())) for td in tr if td.tag in ("td", "th")]
            if any(cells):
                rows.append(cells)
        if not rows:
            continue

        tables.append(
            {
                "kind": "table",
                "label": label or "Table",
                "caption": caption,
                "rows": rows[:8],  # 화면에 담길 만큼만
            }
        )
    return tables


def download_figure(fig, dest_dir, index):
    """PMC에서 그림 이미지를 내려받아 JPEG로 저장한다."""
    from PIL import Image

    fname = fig["file"]
    candidates = [fname] if "." in fname else [f"{fname}.jpg", f"{fname}.png", f"{fname}.gif"]

    for cand in candidates:
        url = PMC_IMG_BASE.format(pmcid=fig["pmcid"], fname=cand)
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200 or not r.content:
                continue
            tmp = os.path.join(dest_dir, f".paperfig_{index}.download")
            with open(tmp, "wb") as f:
                f.write(r.content)
            dest = os.path.join(dest_dir, f"paper_figure_{index}.jpg")
            Image.open(tmp).convert("RGB").save(dest, "JPEG", quality=90)
            os.remove(tmp)
            return dest
        except Exception:
            continue
    print(f"  논문 그림 내려받기 실패: {fig.get('label')} ({fname})")
    return None


def collect_paper_assets(topic, dest_dir, max_figures=2, max_tables=1):
    """논문에서 쓸 수 있는 그림·표를 모아 돌려준다.

    반환: {"figures": [...다운로드된 경로와 설명...], "tables": [...행 데이터...], "source": 설명}
    오픈액세스가 아니거나 라이선스가 불분명하면 빈 결과를 돌려준다.
    """
    empty = {"figures": [], "tables": [], "source": None}
    if topic.get("source_type") != "paper" or not topic.get("pmid"):
        return empty

    pmcid = pmid_to_pmcid(topic["pmid"])
    if not pmcid:
        print("  PMC 오픈액세스 아님 - 논문 그림·표 생략")
        return empty

    root = fetch_pmc_article(pmcid)
    if root is None:
        return empty

    ok, reason = _license_ok(root)
    if not ok:
        print(f"  논문 그림·표 사용 불가 ({reason}) - 생략")
        return empty

    figures = extract_figures(root, pmcid, max_items=max_figures)
    tables = extract_tables(root, max_items=max_tables)

    saved = []
    for i, fig in enumerate(figures, 1):
        path = download_figure(fig, dest_dir, i)
        if path:
            fig["path"] = path
            saved.append(fig)

    if saved or tables:
        print(f"  논문 자료 확보: 그림 {len(saved)}개, 표 {len(tables)}개 ({pmcid}, {reason})")

    return {
        "figures": saved,
        "tables": tables,
        "source": {"pmcid": pmcid, "license_note": reason},
    }
