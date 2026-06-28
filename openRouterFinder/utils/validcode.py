"""Captcha image generation utilities."""

import base64
import io
import secrets
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def _get_font(size: int = 26):
    """Load font with fallback to default. Cache by size."""
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]

    # Try webFinder public directory
    paths = [
        Path(__file__).parent.parent.parent / "webFinder" / "public" / "NotoSansHans-Regular.ttf",
    ]
    for p in paths:
        if p.exists():
            font = ImageFont.truetype(str(p), size=size)
            _FONT_CACHE[size] = font
            return font
    return ImageFont.load_default()


def _rand_rgb(low: int, high: int) -> tuple[int, int, int]:
    """Return a random RGB tuple using cryptographically secure randomness."""
    return tuple(secrets.randbelow(high - low + 1) + low for _ in range(3))


def generate_captcha(num: int) -> bytes:
    """Generate JPEG captcha image bytes."""
    bg = _rand_rgb(30, 60)
    img = Image.new("RGB", (90, 30), bg)
    draw = ImageDraw.Draw(img)
    fg = _rand_rgb(180, 255)
    font = _get_font()
    draw.text((20, 0), str(num), fg, font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def generate_captcha_b64(num: int) -> str:
    """Generate base64-encoded captcha image."""
    img_bytes = generate_captcha(num)
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"
