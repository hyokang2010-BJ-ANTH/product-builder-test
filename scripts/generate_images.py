"""영상 제작용 이미지 생성:
1) 논문/기사 표지 카드 (paper_card.png) - 직접 렌더링
2) 주제 관련 이미지 (topic_1.jpg, topic_2.jpg) - Wikimedia Commons 무료 소스
3) 개인 사진 슬롯 (assets/my-photo/latest.jpg, 없으면 안내 플레이스홀더)
4) 위 소재 + 대본을 shortform_template.json 구성에 맞춰 합성한 최종 프레임 이미지 6장
"""
import json
import os
import shutil

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

from common import ASSETS_DIR, TEMPLATES_DIR
from image_sources import (
    download_image,
    ensure_body_font,
    ensure_display_font,
    wikimedia_search_images,
)

W, H = 1080, 1920
BRAND_TOP = (27, 31, 59)
BRAND_BOTTOM = (58, 46, 92)
ACCENT = (255, 107, 107)
MY_PHOTO_PATH = os.path.join(ASSETS_DIR, "my-photo", "latest.jpg")


# ---------- 폰트 ----------
def _font(size, display=False):
    path = ensure_display_font() if display else ensure_body_font()
    if path and os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


# 헤드라인 폰트(Black Han Sans)에는 수학·그리스 기호 글리프가 없어 빈칸으로 렌더링된다.
# 의학 초록에는 이런 기호가 흔하므로(실제로 "Adults (≥18 years)"가 "Adults (  18 years)"로
# 나왔다) 읽을 수 있는 형태로 바꿔 그린다.
SYMBOL_REPLACEMENTS = {
    "≥": ">=", "≤": "<=", "±": "+/-", "×": "x", "÷": "/",
    "−": "-", "–": "-", "—": "-", "…": "...",
    "′": "'", "″": '"', "‰": "/1000", "°": "도", "→": "->",
    "μ": "u", "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
}


def _sanitize_for_font(text):
    for src, dst in SYMBOL_REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text


def _text_block_height(draw, lines, font, line_spacing):
    heights = [draw.textbbox((0, 0), l, font=font)[3] for l in lines]
    return sum(heights) + line_spacing * (len(lines) - 1), heights


def _fit_font(draw, text, box, base_size, display=True, min_size=30, line_spacing=14):
    """텍스트가 주어진 영역에 들어갈 때까지 글자 크기를 줄여 폰트를 고른다.

    긴 초록 문장이 그대로 들어오면 자막이 패널 밖으로 넘치기 때문에 필요하다.
    """
    text = _sanitize_for_font(text)  # 치환 후 길이로 재야 실제 렌더링과 일치한다
    x0, y0, x1, y1 = box
    size = base_size
    while size > min_size:
        font = _font(size, display=display)
        lines = _wrap(draw, text, font, x1 - x0)
        total_h, _ = _text_block_height(draw, lines, font, line_spacing)
        if total_h <= (y1 - y0):
            return font
        size -= 4
    return _font(min_size, display=display)


def _wrap(draw, text, font, max_width):
    words = text.replace("\n", " \n ").split(" ")
    lines, cur = [], ""
    for w in words:
        if w == "\n":
            lines.append(cur)
            cur = ""
            continue
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _gradient(size=(W, H), top=BRAND_TOP, bottom=BRAND_BOTTOM):
    img = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(img)
    for y in range(size[1]):
        t = y / max(size[1] - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (size[0], y)], fill=color)
    return img


def _cover_resize(img, size):
    return ImageOps.fit(img, size, method=Image.LANCZOS)


def _draw_centered_text(draw, text, font, box, fill="white", line_spacing=14, align="center"):
    text = _sanitize_for_font(text)
    x0, y0, x1, y1 = box
    lines = _wrap(draw, text, font, x1 - x0)
    total_h, heights = _text_block_height(draw, lines, font, line_spacing)
    y = y0 + max((y1 - y0 - total_h) // 2, 0)
    for line, lh in zip(lines, heights):
        w = draw.textlength(line, font=font)
        x = x0 + (x1 - x0 - w) / 2 if align == "center" else x0
        draw.text((x, y), line, font=font, fill=fill)
        y += lh + line_spacing


def _bottom_panel(img, panel_ratio=0.34, color=(0, 0, 0), alpha=160):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    panel_h = int(img.size[1] * panel_ratio)
    draw.rectangle([0, img.size[1] - panel_h, img.size[0], img.size[1]], fill=(*color, alpha))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


# ---------- 1) 논문/기사 표지 카드 ----------
def render_paper_card(topic, out_path):
    img = _gradient()
    draw = ImageDraw.Draw(img)

    badge_text = "PAPER" if topic["source_type"] == "paper" else "NEWS"
    badge_font = _font(40, display=True)
    draw.rounded_rectangle([80, 140, 80 + draw.textlength(badge_text, font=badge_font) + 60, 210],
                            radius=20, fill=ACCENT)
    draw.text((110, 152), badge_text, font=badge_font, fill="white")

    title_font = _font(64, display=True)
    _draw_centered_text(draw, topic["title"], title_font, (80, 320, W - 80, 1100), fill="white")

    meta_font = _font(38)
    meta = topic.get("journal") or topic.get("source_name") or ""
    date = topic.get("pub_date", "")
    meta_text = f"{meta}\n{date}".strip()
    _draw_centered_text(draw, meta_text, meta_font, (80, 1200, W - 80, 1420), fill=(220, 220, 235))

    footer_font = _font(32)
    draw.text((80, H - 160), "출처: PubMed / Google News (무료 공개 검색)", font=footer_font, fill=(180, 180, 200))

    img.save(out_path)
    return out_path


# ---------- 2) 주제 관련 이미지 ----------
def fetch_topic_images(keywords, out_dir, count=2):
    """주제 이미지를 받아 topic_1.jpg, topic_2.jpg로 정규화해 저장한다.

    파일명을 고정하는 이유: 예전에는 원본 URL의 확장자를 그대로 따랐는데
    (.png로 저장되는 경우가 있었다), 씬 템플릿은 topic_N.jpg를 찾기 때문에
    다운로드가 성공해도 프레임에는 빈 배경이 깔렸다.
    """
    saved = []
    credits = []
    for kw in keywords:
        if len(saved) >= count:
            break
        try:
            results = wikimedia_search_images(kw, limit=3)
        except Exception as e:
            print(f"  위키미디어 검색 실패 ({kw}): {e}")
            results = []
        for info in results:
            if len(saved) >= count:
                break
            try:
                idx = len(saved) + 1
                dest = os.path.join(out_dir, f"topic_{idx}.jpg")
                tmp = os.path.join(out_dir, f".topic_{idx}.download")
                download_image(info, tmp)
                # 원본이 PNG든 무엇이든 항상 JPEG로 통일한다
                Image.open(tmp).convert("RGB").save(dest, "JPEG", quality=88)
                os.remove(tmp)
                saved.append(dest)
                credits.append(info)
            except Exception as e:
                # 조용히 넘어가면 왜 플레이스홀더가 나왔는지 알 수 없으므로 남긴다
                print(f"  이미지 내려받기 실패 ({info.get('title', '?')[:40]}): {e}")
                continue
    return saved, credits


def write_attribution(credits, topic, out_path):
    """영상 설명란에 그대로 붙여넣을 출처·저작권 표시문을 만든다.

    위키미디어 이미지는 CC BY / CC BY-SA가 많아 저작자 표시가 의무다.
    """
    lines = [
        "[출처]",
        f"논문: {topic.get('title', '')}",
        f"게재: {topic.get('journal') or topic.get('source_name', '')}",
        f"원문: {topic.get('url', '')}",
        "",
    ]

    if credits:
        lines.append("[이미지 출처]")
        for c in credits:
            name = c.get("title", "").replace("File:", "")
            artist = c.get("artist") or "저작자 미상"
            lines.append(f"- {name} / {artist} / {c.get('license', '')}")
            lines.append(f"  {c.get('source_page', '')}")
        if any("sa" in (c.get("license") or "").lower() for c in credits):
            lines += [
                "",
                "※ CC BY-SA 이미지가 포함되어 있습니다. 저작자 표시가 필수이며,",
                "  동일조건변경허락(ShareAlike) 조항이 영상 전체에 적용될 수 있으니",
                "  상업적 이용 시 해당 이미지를 교체하는 편이 안전합니다.",
            ]
    else:
        lines.append("[이미지 출처] 자체 생성 이미지만 사용 (외부 출처 없음)")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def _placeholder_topic_image(out_path, label="주제 이미지"):
    img = _gradient(top=(40, 40, 60), bottom=(20, 20, 35))
    draw = ImageDraw.Draw(img)
    font = _font(48, display=True)
    _draw_centered_text(draw, f"{label}\n(소스 검색 실패 - 자동 재시도 필요)", font, (100, H // 2 - 150, W - 100, H // 2 + 150))
    img.save(out_path)
    return out_path


# ---------- 3) 개인 사진 ----------
def ensure_my_photo_placeholder():
    if os.path.exists(MY_PHOTO_PATH):
        return MY_PHOTO_PATH
    os.makedirs(os.path.dirname(MY_PHOTO_PATH), exist_ok=True)
    img = _gradient(top=(60, 60, 70), bottom=(30, 30, 38))
    draw = ImageDraw.Draw(img)
    font = _font(46, display=True)
    _draw_centered_text(
        draw,
        "여기에 본인 사진을 넣어주세요\nassets/my-photo/latest.jpg 로 교체",
        font,
        (100, H // 2 - 150, W - 100, H // 2 + 150),
    )
    img.save(MY_PHOTO_PATH)
    return MY_PHOTO_PATH


# ---------- 4) 최종 프레임 합성 ----------
def _resolve_text(script, source):
    if source.startswith("script."):
        key = source.split(".", 1)[1]
        if "[" in key:
            base, idx = key[:-1].split("[")
            arr = script.get(base) or []
            idx = int(idx)
            return arr[idx] if idx < len(arr) else ""
        return script.get(key, "")
    if source.startswith("custom."):
        return "탈모 연구, 매일 쉽게 정리해드립니다 🙂"
    return source


def render_scene_frames(script, day_dir):
    with open(os.path.join(TEMPLATES_DIR, "shortform_template.json"), encoding="utf-8") as f:
        template = json.load(f)

    images_dir = os.path.join(day_dir, "images")
    frame_paths = []
    for scene in template["scenes"]:
        text = _resolve_text(script, scene.get("text_source", "")) if scene.get("text_source") else ""
        if not text and scene["id"] in ("key_finding_2",):
            continue  # 하이라이트가 부족하면 스킵

        font_size = scene.get("font_size", 56)

        if scene["layout"] == "full_bleed_text":
            frame = _gradient()
            draw = ImageDraw.Draw(frame)
            box = (100, H // 2 - 300, W - 100, H // 2 + 300)
            _draw_centered_text(draw, text, _fit_font(draw, text, box, font_size), box)

        elif scene["layout"] == "image_top_text_bottom":
            src = os.path.join(day_dir, os.path.basename(scene["image_source"]))
            base = Image.open(src).convert("RGB") if os.path.exists(src) else _gradient()
            frame = _cover_resize(base, (W, H))
            draw = ImageDraw.Draw(frame)

        elif scene["layout"] in ("topic_image_bg_text_overlay", "personal_photo_bg_text_overlay"):
            if scene["layout"] == "personal_photo_bg_text_overlay":
                src = ensure_my_photo_placeholder()
            else:
                src = os.path.join(images_dir, os.path.basename(scene["image_source"]))
                if not os.path.exists(src):
                    src = None
            base = Image.open(src).convert("RGB") if src and os.path.exists(src) else _gradient()
            frame = _cover_resize(base, (W, H)).filter(ImageFilter.GaussianBlur(0))
            frame = _bottom_panel(frame)
            draw = ImageDraw.Draw(frame)
            box = (80, H - 560, W - 80, H - 80)
            _draw_centered_text(draw, text, _fit_font(draw, text, box, font_size), box)
        else:
            frame = _gradient()
            draw = ImageDraw.Draw(frame)

        # 사진 배경이 들어간 프레임을 PNG로 저장하면 한 장에 3MB를 넘어
        # 저장소가 빠르게 불어난다. 영상 소재로는 고품질 JPEG로 충분하다.
        out_path = os.path.join(images_dir, f"frame_{scene['order']:02d}_{scene['id']}.jpg")
        frame.convert("RGB").save(out_path, "JPEG", quality=92, optimize=True)
        frame_paths.append(out_path)

    return frame_paths


def generate_all_images(content, day_dir):
    topic = content["topic"]
    script = content["script"]
    images_dir = os.path.join(day_dir, "images")
    # 같은 날 다시 실행할 때 이전 회차 파일이 남아 섞이지 않도록 비우고 시작한다
    if os.path.isdir(images_dir):
        shutil.rmtree(images_dir)
    os.makedirs(images_dir, exist_ok=True)

    paper_card_path = os.path.join(day_dir, "paper_card.png")
    render_paper_card(topic, paper_card_path)

    # 'hair'만 넣으면 청각 유모세포·식물 뿌리털 같은 무관한 사진이 걸리므로
    # 탈모/두피 맥락이 분명한 표현을 쓴다
    keywords = [
        "androgenetic alopecia",
        "hair transplant surgery",
        "hair loss baldness",
        "human scalp",
    ]
    saved, credits = fetch_topic_images(keywords, images_dir, count=2)
    for i in range(len(saved), 2):
        _placeholder_topic_image(os.path.join(images_dir, f"topic_{i + 1}.jpg"))

    ensure_my_photo_placeholder()

    frames = render_scene_frames(script, day_dir)

    credits_path = os.path.join(day_dir, "image_credits.json")
    with open(credits_path, "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=2)

    attribution_path = write_attribution(credits, topic, os.path.join(day_dir, "attribution.txt"))

    return {
        "paper_card": paper_card_path,
        "topic_images": saved,
        "frames": frames,
        "credits_file": credits_path,
        "attribution_file": attribution_path,
    }
