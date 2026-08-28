"""PWA 아이콘(아이폰 홈 화면용 포함)을 한 번 생성한다."""
import os

from PIL import Image, ImageDraw

from common import ROOT
from image_sources import ensure_display_font

ICON_DIR = os.path.join(ROOT, "pwa", "icons")
TOP = (27, 31, 59)
BOTTOM = (58, 46, 92)
ACCENT = (255, 107, 107)


def _gradient(size):
    img = Image.new("RGB", size, TOP)
    draw = ImageDraw.Draw(img)
    for y in range(size[1]):
        t = y / max(size[1] - 1, 1)
        color = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (size[0], y)], fill=color)
    return img


def make_icon(size, out_path, radius_ratio=0.22):
    img = _gradient((size, size)).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size, size], radius=int(size * radius_ratio), fill=255)
    img.putalpha(mask)

    draw = ImageDraw.Draw(img)
    font_path = ensure_display_font()
    label = "毛"
    try:
        from PIL import ImageFont

        font = ImageFont.truetype(font_path, int(size * 0.42)) if font_path else ImageFont.load_default()
    except Exception:
        from PIL import ImageFont

        font = ImageFont.load_default()

    text = "탈모"
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.ellipse(
        [size * 0.5 - size * 0.06, size * 0.14, size * 0.5 + size * 0.06, size * 0.14 + size * 0.12],
        fill=ACCENT,
    )
    draw.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1] + size * 0.06), text, font=font, fill="white")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)


def main():
    make_icon(192, os.path.join(ICON_DIR, "icon-192.png"))
    make_icon(512, os.path.join(ICON_DIR, "icon-512.png"))
    # iOS 홈 화면 아이콘은 투명 배경/둥근 모서리를 지원하지 않으므로 불투명 정사각형으로 별도 생성
    make_icon(180, os.path.join(ICON_DIR, "apple-touch-icon.png"), radius_ratio=0)
    img = Image.open(os.path.join(ICON_DIR, "apple-touch-icon.png")).convert("RGBA")
    bg = Image.new("RGBA", img.size, (*TOP, 255))
    bg.alpha_composite(img)
    bg.convert("RGB").save(os.path.join(ICON_DIR, "apple-touch-icon.png"))
    print("아이콘 생성 완료:", ICON_DIR)


if __name__ == "__main__":
    main()
