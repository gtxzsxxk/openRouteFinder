"""Captcha image generation utilities."""

import io
import base64
import random
from pathlib import Path

from PIL import Image, ImageFont, ImageDraw


def _get_font(size: int = 26):
    """Load font with fallback to default."""
    # Try webFinder public directory
    paths = [
        Path(__file__).parent.parent.parent / "webFinder" / "public" / "NotoSansHans-Regular.ttf",
    ]
    for p in paths:
        if p.exists():
            return ImageFont.truetype(str(p), size=size)
    return ImageFont.load_default()


def generate_captcha(num: int) -> bytes:
    """Generate JPEG captcha image bytes."""
    bg = (
        random.randint(30, 60),
        random.randint(30, 60),
        random.randint(30, 60),
    )
    img = Image.new("RGB", (90, 30), bg)
    draw = ImageDraw.Draw(img)
    fg = (
        random.randint(180, 255),
        random.randint(180, 255),
        random.randint(180, 255),
    )
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


def rotate_runway_image(angle: int) -> str:
    """Rotate runway icon and return base64 PNG."""
    paths = [
        Path(__file__).parent.parent.parent / "webFinder" / "public" / "runway.png",
    ]
    img_path = None
    for p in paths:
        if p.exists():
            img_path = p
            break
    if img_path is None:
        raise FileNotFoundError("runway.png not found")

    img = Image.open(img_path)
    img = img.rotate(360 - angle)
    img = img.resize((32, 32))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"
