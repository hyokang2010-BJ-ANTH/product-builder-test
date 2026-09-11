"""영상 제작용 PPTX를 만든다.

예전에는 렌더링된 프레임 이미지를 슬라이드에 통째로 한 장씩 깔았는데,
그러면 문구 하나 고치려 해도 PPT 안에서는 아무것도 손댈 수 없어 사실상 이미지 뷰어였다.
지금은 배경과 텍스트를 분리해, 파워포인트에서 바로 문구를 고치고 다시 내보낼 수 있게 만든다.

구성(9:16 세로, 쇼츠 폼 유지):
  1) 훅      - 저널 배지 + 큰 강조구 + 설명구 (전부 편집 가능한 텍스트 박스)
  2) 논문 소개 - 표지 카드 이미지 + 제목/출처 텍스트
  3) 논문 그림 - PMC 오픈액세스 그림 원본 + 캡션
  4) 핵심 포인트 - 주제 사진 배경 + 자막 텍스트
  5) 논문 표   - 표를 실제 PPT 표로 삽입(셀 단위 편집 가능)
  6) 내 코멘트 - 본인 사진 + 코멘트
  7) CTA
  8) 출처     - 논문/이미지 크레딧
"""
import json
import os

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Emu, Inches, Pt

from common import TEMPLATES_DIR

SLIDE_W_IN = 6.08  # 1080/1920 비율 (9:16)
SLIDE_H_IN = 10.8

BRAND_BG = RGBColor(0x1B, 0x1F, 0x3B)
BRAND_BG2 = RGBColor(0x12, 0x14, 0x2A)
ACCENT = RGBColor(0xFF, 0x6B, 0x6B)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
MUTED = RGBColor(0xAA, 0xAF, 0xCD)

KO_FONT = "Arial"  # 파워포인트에서 한글이 깨지지 않는 무난한 기본값


def _fill(slide, color):
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = color


def _textbox(slide, text, left, top, width, height, size, color=WHITE,
             bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text or ""
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = KO_FONT
    return box


def _full_bleed_picture(slide, prs, img_path):
    """이미지를 슬라이드 전체에 꽉 차게, 비율을 지켜 배치한다."""
    from PIL import Image

    with Image.open(img_path) as im:
        iw, ih = im.size
    sw, sh = prs.slide_width, prs.slide_height
    scale = max(sw / iw, sh / ih)
    w, h = int(iw * scale), int(ih * scale)
    slide.shapes.add_picture(img_path, int((sw - w) / 2), int((sh - h) / 2), width=w, height=h)


def _scrim(slide, prs, top_ratio=0.62):
    """사진 위 글씨가 읽히도록 하단에 어두운 막을 깐다."""
    from pptx.enum.shapes import MSO_SHAPE

    top = int(prs.slide_height * top_ratio)
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, top, prs.slide_width,
                                 prs.slide_height - top)
    shp.fill.solid()
    shp.fill.fore_color.rgb = RGBColor(0, 0, 0)
    shp.fill.transparency = 0.35
    shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def _add_hook(prs, blank, script, topic):
    s = prs.slides.add_slide(blank)
    _fill(s, BRAND_BG)
    journal = (topic.get("journal") or topic.get("source_name") or "").strip()
    if journal:
        _textbox(s, journal.upper()[:40], Inches(0.4), Inches(1.5), prs.slide_width - Inches(0.8),
                 Inches(0.5), 14, ACCENT)
    _textbox(s, script.get("hook_accent", ""), Inches(0.3), Inches(3.4),
             prs.slide_width - Inches(0.6), Inches(2.2), 80, ACCENT)
    _textbox(s, script.get("hook_sub", ""), Inches(0.5), Inches(5.9),
             prs.slide_width - Inches(1.0), Inches(1.6), 28, WHITE)
    _textbox(s, f"{topic.get('pub_date', '')}  |  매일 아침 탈모 연구 한 편",
             Inches(0.4), Inches(9.6), prs.slide_width - Inches(0.8), Inches(0.5), 12, MUTED,
             bold=False)
    s.notes_slide.notes_text_frame.text = (
        f"[hook] 약 4초\n대본: {script.get('hook', '')}\n"
        "연출 노트: 0.5초 안에 스크롤을 멈추게 하는 구간. 숫자를 크게 읽어준다."
    )
    return s


def _add_paper_intro(prs, blank, script, topic, day_dir):
    s = prs.slides.add_slide(blank)
    _fill(s, BRAND_BG)
    card = os.path.join(day_dir, "paper_card.png")
    if os.path.exists(card):
        s.shapes.add_picture(card, Inches(0.55), Inches(0.9),
                             width=prs.slide_width - Inches(1.1))
    _textbox(s, topic.get("title", ""), Inches(0.4), Inches(7.4),
             prs.slide_width - Inches(0.8), Inches(2.0), 20, WHITE)
    _textbox(s, f"{topic.get('journal', '')}  ·  {topic.get('pub_date', '')}",
             Inches(0.4), Inches(9.4), prs.slide_width - Inches(0.8), Inches(0.6), 13, MUTED,
             bold=False)
    s.notes_slide.notes_text_frame.text = (
        f"[paper_intro] 약 8초\n대본: {script.get('intro', '')}\n"
        "연출 노트: 출처를 분명히 밝혀 신뢰를 준다."
    )
    return s


def _add_paper_figure(prs, blank, fig):
    s = prs.slides.add_slide(blank)
    _fill(s, BRAND_BG2)
    _textbox(s, f"논문 {fig.get('label', 'Figure')}", Inches(0.4), Inches(1.2),
             prs.slide_width - Inches(0.8), Inches(0.6), 20, ACCENT)
    if fig.get("path") and os.path.exists(fig["path"]):
        from PIL import Image

        with Image.open(fig["path"]) as im:
            iw, ih = im.size
        max_w = prs.slide_width - Inches(0.8)
        max_h = Inches(5.6)
        scale = min(max_w / iw, max_h / ih)
        w, h = int(iw * scale), int(ih * scale)
        s.shapes.add_picture(fig["path"], int((prs.slide_width - w) / 2), Inches(2.2),
                             width=w, height=h)
    _textbox(s, fig.get("caption", "")[:220], Inches(0.4), Inches(8.2),
             prs.slide_width - Inches(0.8), Inches(2.0), 15, RGBColor(0xE1, 0xE4, 0xF5),
             bold=False)
    s.notes_slide.notes_text_frame.text = (
        f"[paper_figure] 약 10초\n대본: 논문에 실린 {fig.get('label', '그림')}입니다. "
        f"{fig.get('caption', '')[:120]}\n"
        "연출 노트: 그래프를 짚어가며 설명하면 체류시간이 올라간다."
    )
    return s


def _add_paper_table(prs, blank, table):
    s = prs.slides.add_slide(blank)
    _fill(s, BRAND_BG2)
    _textbox(s, f"논문 {table.get('label', 'Table')}", Inches(0.4), Inches(1.2),
             prs.slide_width - Inches(0.8), Inches(0.6), 20, ACCENT)
    _textbox(s, table.get("caption", "")[:140], Inches(0.4), Inches(1.9),
             prs.slide_width - Inches(0.8), Inches(1.0), 13, MUTED, bold=False)

    rows = (table.get("rows") or [])[:7]
    if rows:
        ncols = min(max(len(r) for r in rows), 4)
        # 이미지가 아니라 진짜 PPT 표로 넣어 셀 값을 직접 고칠 수 있게 한다
        shape = s.shapes.add_table(len(rows), ncols, Inches(0.35), Inches(3.2),
                                   prs.slide_width - Inches(0.7),
                                   Inches(0.55) * len(rows))
        tbl = shape.table
        for ri, row in enumerate(rows):
            for ci in range(ncols):
                cell = tbl.cell(ri, ci)
                cell.text = (row[ci] if ci < len(row) else "")[:40]
                para = cell.text_frame.paragraphs[0]
                para.font.size = Pt(11 if ri else 12)
                para.font.bold = ri == 0
                para.font.name = KO_FONT
    s.notes_slide.notes_text_frame.text = (
        f"[paper_table] 약 8초\n대본: 표로 보면 이렇습니다. {table.get('caption', '')[:120]}\n"
        "연출 노트: 핵심 숫자 한 칸만 짚어준다. 표는 셀을 직접 수정할 수 있다."
    )
    return s


def _add_photo_caption(prs, blank, img_path, caption, scene_id, seconds, note):
    s = prs.slides.add_slide(blank)
    _fill(s, BRAND_BG)
    if img_path and os.path.exists(img_path):
        _full_bleed_picture(s, prs, img_path)
        _scrim(s, prs)
    _textbox(s, caption, Inches(0.4), Inches(7.0), prs.slide_width - Inches(0.8),
             Inches(3.2), 22, WHITE)
    s.notes_slide.notes_text_frame.text = f"[{scene_id}] 약 {seconds}초\n대본: {caption}\n연출 노트: {note}"
    return s


def _add_cta(prs, blank, script):
    s = prs.slides.add_slide(blank)
    _fill(s, BRAND_BG)
    _textbox(s, script.get("cta", ""), Inches(0.5), Inches(3.8),
             prs.slide_width - Inches(1.0), Inches(3.0), 34, WHITE)
    s.notes_slide.notes_text_frame.text = (
        f"[cta] 약 8초\n대본: {script.get('cta', '')}\n연출 노트: 원문 링크는 고정 댓글로 안내."
    )
    return s


def _add_sources(prs, blank, content, day_dir):
    s = prs.slides.add_slide(blank)
    _fill(s, BRAND_BG2)
    _textbox(s, "출처", Inches(0.4), Inches(0.8), prs.slide_width - Inches(0.8),
             Inches(0.6), 22, ACCENT)
    attribution = os.path.join(day_dir, "attribution.txt")
    body = ""
    if os.path.exists(attribution):
        with open(attribution, encoding="utf-8") as f:
            body = f.read()
    else:
        t = content["topic"]
        body = f"{t.get('title', '')}\n{t.get('url', '')}"
    _textbox(s, body[:1400], Inches(0.4), Inches(1.6), prs.slide_width - Inches(0.8),
             Inches(8.4), 10, RGBColor(0xD5, 0xD8, 0xEA), bold=False,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP)
    return s


def build_pptx(content, frame_paths, out_path, paper_assets=None, day_dir=None):
    """프레임 이미지 대신 배경+텍스트를 분리한 편집 가능한 덱을 만든다."""
    day_dir = day_dir or os.path.dirname(out_path)
    paper_assets = paper_assets or {}
    figures = paper_assets.get("figures") or []
    tables = paper_assets.get("tables") or []

    script = content["script"]
    topic = content["topic"]
    highlights = script.get("highlights") or []

    with open(os.path.join(TEMPLATES_DIR, "shortform_template.json"), encoding="utf-8") as f:
        template = json.load(f)
    seconds = {s["id"]: s["duration_sec"] for s in template["scenes"]}

    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W_IN)
    prs.slide_height = Inches(SLIDE_H_IN)
    blank = prs.slide_layouts[6]
    images_dir = os.path.join(day_dir, "images")

    _add_hook(prs, blank, script, topic)
    _add_paper_intro(prs, blank, script, topic, day_dir)

    if figures:
        _add_paper_figure(prs, blank, figures[0])

    if highlights:
        _add_photo_caption(prs, blank, os.path.join(images_dir, "topic_1.jpg"),
                           highlights[0], "key_finding_1", seconds.get("key_finding_1", 10),
                           "핵심 포인트 1. 자막을 끊어 읽는다.")
    if tables:
        _add_paper_table(prs, blank, tables[0])

    if len(highlights) > 1:
        _add_photo_caption(prs, blank, os.path.join(images_dir, "topic_2.jpg"),
                           highlights[1], "key_finding_2", seconds.get("key_finding_2", 10),
                           "핵심 포인트 2.")

    from generate_images import MY_PHOTO_PATH

    _add_photo_caption(prs, blank, MY_PHOTO_PATH, "탈모 연구, 매일 쉽게 정리해드립니다 🙂",
                       "my_take", seconds.get("my_take", 10),
                       "본인 사진 + 코멘트. 문구를 직접 바꿔 쓰세요.")
    _add_cta(prs, blank, script)
    _add_sources(prs, blank, content, day_dir)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    prs.save(out_path)
    return out_path
