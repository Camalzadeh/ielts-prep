"""Generate launcher/ielts.ico (multi-size) and frontend/favicon.png."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent


def font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw(size=512):
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    # vertical gradient rounded square: deep indigo -> teal
    grad = Image.new("RGBA", (s, s))
    top, bottom = (49, 46, 129), (13, 148, 136)
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / (s - 1)
        gd.line([(0, y), (s, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # open book glyph
    cx, by = s // 2, int(s * 0.64)
    w, h = int(s * 0.30), int(s * 0.17)
    page = (255, 255, 255, 235)
    d.polygon([(cx, by), (cx - w, by - int(h * 0.25)), (cx - w, by - h - int(h * 0.25)), (cx, by - h)], fill=page)
    d.polygon([(cx, by), (cx + w, by - int(h * 0.25)), (cx + w, by - h - int(h * 0.25)), (cx, by - h)], fill=(255, 255, 255, 205))
    # "IELTS" wordmark
    f = font(int(s * 0.23))
    text = "IELTS"
    tw = d.textlength(text, font=f)
    d.text(((s - tw) / 2, int(s * 0.13)), text, font=f, fill=(255, 255, 255, 255))
    # accent dot (band score badge)
    r = int(s * 0.07)
    d.ellipse([int(s * 0.78) - r, int(s * 0.80) - r, int(s * 0.78) + r, int(s * 0.80) + r], fill=(251, 191, 36, 255))
    return img


if __name__ == "__main__":
    big = draw(512)
    big.save(HERE / "ielts.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(HERE / "ielts.png")
    print("icon written")
