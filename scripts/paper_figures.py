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

ID_CONVERTERS = (
    "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/",
    "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
)
PMC_IMG_BASE = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/bin/{fname}"

# 같은 그림이 호스트·확장자에 따라 다른 경로로 제공된다.
# 본문 XML이 가리키는 이름(.webp 등)이 그대로는 404가 나는 경우가 많아
# 확장자를 바꿔가며, 그리고 Europe PMC 미러까지 차례로 시도한다.
# NCBI는 PMC를 pmc.ncbi.nlm.nih.gov 도메인으로 옮겼다.
# 예전 www.ncbi.nlm.nih.gov/pmc/... 경로는 이미지도 API도 모두 404를 준다.
PMC_IMG_HOSTS = (
    "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/bin/{fname}",
    "https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/bin/{fname}",
    "https://europepmc.org/articles/{pmcid}/bin/{fname}",
)
IMG_EXTENSIONS = ("jpg", "jpeg", "png", "gif", "webp")


def _candidate_image_urls(pmcid, fname):
    stem, _, ext = fname.rpartition(".")
    if not stem:  # 확장자가 없는 이름
        stem, ext = fname, ""

    exts = ([ext] if ext else []) + [e for e in IMG_EXTENSIONS if e != ext]
    seen = set()
    for host in PMC_IMG_HOSTS:
        for e in exts:
            url = host.format(pmcid=pmcid, fname=f"{stem}.{e}" if e else stem)
            if url not in seen:
                seen.add(url)
                yield url

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

# 의학 오픈액세스 저널 상당수가 CC BY-NC(비상업 한정)로 배포한다.
# 기본값은 안전하게 제외하지만, 수익화하지 않는 채널이라면 아래 환경변수를 켜서
# 쓸 수 있다. 켜더라도 attribution.txt에 경고가 함께 기록된다.
ALLOW_NC = os.environ.get("ALLOW_NC_FIGURES", "").strip().lower() in ("1", "true", "yes")


def pmid_to_pmcid(pmid):
    """PMID를 PMCID로 바꾼다. PMC에 없으면 None."""
    for service in ID_CONVERTERS:
        try:
            r = requests.get(
                service,
                params={"ids": pmid, "format": "json", "tool": "hair-content-automation"},
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            records = r.json().get("records", [])
            if records and records[0].get("pmcid"):
                return records[0]["pmcid"]
            return None  # 응답은 정상인데 PMC에 없는 논문
        except Exception as e:
            print(f"  PMCID 변환 실패 (pmid {pmid}, {service.split('/')[2]}): {e}")
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
        if ALLOW_NC:
            return True, "CC BY-NC(비상업 한정) - 수익화 채널에서는 사용 주의"
        return False, "비상업적 이용 한정 라이선스(CC BY-NC)"
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
            cells = []
            for td in tr:
                if td.tag not in ("td", "th"):
                    continue
                text = _clean("".join(td.itertext()))
                cells.append(text)
                # 가로 병합(colspan)은 빈 칸을 채워 열 위치를 맞춘다
                try:
                    span = int(td.attrib.get("colspan", 1))
                except ValueError:
                    span = 1
                cells.extend([""] * (span - 1))
            if any(cells):
                rows.append(cells)
        if not rows:
            continue

        # 세로 병합(rowspan)으로 비어 버린 앞쪽 칸은 위 행의 값을 이어받는다.
        # 그대로 두면 '분류' 열이 통째로 비어 표를 읽을 수 없다.
        width = max(len(r) for r in rows)
        filled = []
        prev = [""] * width
        for ri, row in enumerate(rows):
            row = list(row) + [""] * (width - len(row))
            # 헤더(0행)는 이어받기의 출처로 쓰지 않는다.
            # 그러지 않으면 2행 첫 칸에 열 제목이 그대로 복사된다.
            if ri > 1:
                for ci in range(width):
                    if not row[ci] and prev[ci]:
                        row[ci] = prev[ci]
            filled.append(row)
            if ri >= 1:
                prev = row
        rows = filled

        # 캡션 끝에 붙는 인용 참조([12345] 등)는 노이즈라 떼어낸다
        caption = re.sub(r"\[\d[\d,\s\-]*\]\s*$", "", caption).strip()

        tables.append(
            {
                "kind": "table",
                "label": label or "Table",
                "caption": caption,
                "rows": rows[:8],  # 화면에 담길 만큼만
            }
        )
    return tables


# 신 도메인을 우선 쓰고, 혹시 몰라 구 주소도 남겨 차례로 시도한다
OA_SERVICES = (
    "https://pmc.ncbi.nlm.nih.gov/utils/oa/oa.fcgi",
    "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi",
)


def fetch_oa_package(pmcid, dest_dir):
    """PMC 오픈액세스 패키지(tar.gz)를 받아 풀어놓고 그 경로를 돌려준다.

    본문 XML이 가리키는 /bin/ 이미지 경로는 현재 모두 404를 반환한다(2026-09 확인).
    NCBI가 공식으로 제공하는 방법은 이 OA 서비스로 패키지를 통째로 받는 것뿐이다.
    """
    import tarfile

    root = None
    last_error = None
    for service in OA_SERVICES:
        try:
            r = requests.get(service, params={"id": pmcid}, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            break
        except Exception as e:
            last_error = e
    if root is None:
        print(f"  OA 패키지 조회 실패 ({pmcid}): {last_error}")
        return None

    href = None
    for link in root.iter("link"):
        if link.get("format") == "tgz" and link.get("href"):
            href = link.get("href")
            break
    if not href:
        print(f"  OA 패키지 없음 ({pmcid}) - 그림 사용 불가")
        return None

    # OA 서비스는 ftp:// 주소를 주는데, 러너에서는 https로 받아야 한다
    href = href.replace("ftp://ftp.ncbi.nlm.nih.gov", "https://ftp.ncbi.nlm.nih.gov")

    archive = os.path.join(dest_dir, ".oa_package.tar.gz")
    extract_dir = os.path.join(dest_dir, ".oa_package")
    try:
        with requests.get(href, headers=HEADERS, timeout=60, stream=True) as resp:
            resp.raise_for_status()
            total = 0
            with open(archive, "wb") as f:
                for chunk in resp.iter_content(1 << 16):
                    total += len(chunk)
                    if total > 80 * 1024 * 1024:  # 비정상적으로 큰 패키지는 건너뛴다
                        raise RuntimeError("패키지가 80MB를 초과")
                    f.write(chunk)

        os.makedirs(extract_dir, exist_ok=True)
        with tarfile.open(archive, "r:gz") as tar:
            members = [
                m for m in tar.getmembers()
                if m.isfile() and os.path.splitext(m.name)[1].lower() in
                (".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff")
            ]
            for m in members:
                m.name = os.path.basename(m.name)  # 경로 이탈 방지
            tar.extractall(extract_dir, members=members)
        return extract_dir
    except Exception as e:
        print(f"  OA 패키지 내려받기 실패 ({pmcid}): {e}")
        return None
    finally:
        if os.path.exists(archive):
            os.remove(archive)


def figure_from_package(fig, package_dir, dest_dir, index):
    """풀어놓은 OA 패키지에서 해당 그림 파일을 찾아 JPEG로 저장한다."""
    from PIL import Image

    if not package_dir or not os.path.isdir(package_dir):
        return None

    stem = os.path.splitext(os.path.basename(fig["file"]))[0].lower()
    available = os.listdir(package_dir)

    # 파일명(확장자 제외)이 같은 것을 우선 찾고, 없으면 stem으로 시작하는 것을 쓴다
    match = next((f for f in available if os.path.splitext(f)[0].lower() == stem), None)
    if not match:
        match = next((f for f in available if f.lower().startswith(stem)), None)
    if not match:
        print(f"  패키지에 그림 없음: {fig.get('label')} ({fig['file']})")
        return None

    try:
        dest = os.path.join(dest_dir, f"paper_figure_{index}.jpg")
        with Image.open(os.path.join(package_dir, match)) as im:
            im.convert("RGB").save(dest, "JPEG", quality=90)
        return dest
    except Exception as e:
        print(f"  그림 변환 실패 ({match}): {e}")
        return None


def download_figure(fig, dest_dir, index):
    """PMC에서 그림 이미지를 내려받아 JPEG로 저장한다."""
    from PIL import Image

    fname = fig["file"]

    # 임시 파일은 반드시 지운다. 예전에는 이미지 변환이 실패하면 정리 코드에
    # 닿지 못해 .paperfig_N.download 가 저장소에 그대로 커밋됐다.
    tmp = os.path.join(dest_dir, f".paperfig_{index}.download")
    last_error = None
    try:
        for url in _candidate_image_urls(fig["pmcid"], fname):
            try:
                r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
                if r.status_code != 200 or not r.content:
                    last_error = f"HTTP {r.status_code}"
                    continue
                # PMC는 없는 파일에도 200과 함께 안내 페이지를 주는 경우가 있어
                # 내용이 진짜 이미지인지 확인한다
                ctype = r.headers.get("Content-Type", "")
                if not ctype.startswith("image/"):
                    last_error = f"이미지가 아닌 응답({ctype or '알 수 없음'})"
                    continue

                with open(tmp, "wb") as f:
                    f.write(r.content)
                dest = os.path.join(dest_dir, f"paper_figure_{index}.jpg")
                Image.open(tmp).convert("RGB").save(dest, "JPEG", quality=90)
                return dest
            except Exception as e:
                last_error = e
                continue
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    print(f"  논문 그림 내려받기 실패: {fig.get('label')} ({fname}) - {last_error}")
    return None


def collect_paper_assets(topic, dest_dir, max_figures=2, max_tables=1):
    """논문에서 쓸 수 있는 그림·표를 모아 돌려준다.

    반환: {"figures": [...다운로드된 경로와 설명...], "tables": [...행 데이터...], "source": 설명}
    오픈액세스가 아니거나 라이선스가 불분명하면 빈 결과를 돌려준다.
    """
    def skipped(reason):
        # 왜 그림이 없는지 남겨야 화면에서 "기능이 빠진 것"처럼 보이지 않는다
        return {"figures": [], "tables": [], "source": None, "skip_reason": reason}

    if topic.get("source_type") != "paper" or not topic.get("pmid"):
        return skipped("논문이 아닌 소재(뉴스)")

    pmcid = pmid_to_pmcid(topic["pmid"])
    if not pmcid:
        print("  PMC 오픈액세스 아님 - 논문 그림·표 생략")
        return skipped("PMC 오픈액세스로 공개되지 않은 논문")

    root = fetch_pmc_article(pmcid)
    if root is None:
        return skipped("PMC 본문을 불러오지 못함")

    ok, reason = _license_ok(root)
    if not ok:
        print(f"  논문 그림·표 사용 불가 ({reason}) - 생략")
        return skipped(reason)

    figures = extract_figures(root, pmcid, max_items=max_figures)
    tables = extract_tables(root, max_items=max_tables)

    saved = []
    if figures:
        # 그림은 OA 패키지에서만 안정적으로 얻을 수 있다.
        # (본문이 가리키는 /bin/ 경로는 현재 모두 404)
        package_dir = fetch_oa_package(pmcid, dest_dir)
        for i, fig in enumerate(figures, 1):
            path = figure_from_package(fig, package_dir, dest_dir, i)
            if not path:
                path = download_figure(fig, dest_dir, i)  # 예전 경로도 한 번은 시도
            if path:
                fig["path"] = path
                saved.append(fig)

        # 풀어놓은 패키지는 결과물이 아니므로 정리한다
        if package_dir and os.path.isdir(package_dir):
            import shutil

            shutil.rmtree(package_dir, ignore_errors=True)

    if saved or tables:
        print(f"  논문 자료 확보: 그림 {len(saved)}개, 표 {len(tables)}개 ({pmcid}, {reason})")

    return {
        "figures": saved,
        "tables": tables,
        "source": {"pmcid": pmcid, "license_note": reason},
    }
