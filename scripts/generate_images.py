"""영상 제작용 이미지 생성:
1) 논문/기사 표지 카드 (paper_card.png) - 직접 렌더링
2) 주제 관련 이미지 (topic_1.jpg, topic_2.jpg) - Wikimedia Commons 무료 소스
3) 개인 사진 슬롯 (assets/my-photo/latest.jpg, 없으면 안내 플레이스홀더)
4) 위 소재 + 대본을 shortform_template.json 구성에 맞춰 합성한 최종 프레임 이미지 6장
"""
import json
import os

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
    x0, y0, x1, y1 = box
    lines = _wrap(draw, text, font, x1 - x0)
    heights = [draw.textbbox((0, 0), l, font=font)[3] for l in lines]
    total_h = sum(heights) + line_spacing * (len(lines) - 1)
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
    saved = []
    credits = []
    for kw in keywords:
        if len(saved) >= count:
            break
        try:
            results = wikimedia_search_images(kw, limit=3)
        except Exception:
            results = []
        for info in results:
            if len(saved) >= count:
                break
            try:
                idx = len(saved) + 1
                ext = ".jpg" if info["url"].lower().endswith((".jpg", ".jpeg")) else ".png"
                dest = os.path.join(out_dir, f"topic_{idx}{ext}")
                download_image(info, dest)
                saved.append(dest)
                credits.append(info)
            except Exception:
                continue
    return saved, credits


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
        display_font = _font(font_size, display=True)

        if scene["layout"] == "full_bleed_text":
            frame = _gradient()
            draw = ImageDraw.Draw(frame)
            _draw_centered_text(draw, text, display_font, (100, H // 2 - 300, W - 100, H // 2 + 300))

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
            _draw_centered_text(draw, text, display_font, (80, H - 560, W - 80, H - 80))
        else:
            frame = _gradient()
            draw = ImageDraw.Draw(frame)

        out_path = os.path.join(images_dir, f"frame_{scene['order']:02d}_{scene['id']}.png")
        frame.save(out_path)
        frame_paths.append(out_path)

    return frame_paths


def generate_all_images(content, day_dir):
    topic = content["topic"]
    script = content["script"]
    images_dir = os.path.join(day_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    paper_card_path = os.path.join(day_dir, "paper_card.png")
    render_paper_card(topic, paper_card_path)

    keywords = ["hair loss treatment", "hair transplant surgery", "scalp dermatology"]
    saved, credits = fetch_topic_images(keywords, images_dir, count=2)
    for i in range(len(saved), 2):
        _placeholder_topic_image(os.path.join(images_dir, f"topic_{i + 1}.jpg"))

    ensure_my_photo_placeholder()

    frames = render_scene_frames(script, day_dir)

    credits_path = os.path.join(day_dir, "image_credits.json")
    with open(credits_path, "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=2)

    return {
        "paper_card": paper_card_path,
        "topic_images": saved,
        "frames": frames,
        "credits_file": credits_path,
    }
