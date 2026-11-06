"""Render letter text as a page image, optionally made to look like a phone photo.

Used by ``plainread eval --ocr`` to test the whole photo-to-explanation path,
and to make the demo images in the README.
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Times New Roman.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "C:/Windows/Fonts/times.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _wrap(
    draw: ImageDraw.ImageDraw,
    line: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    width: int,
) -> list[str]:
    if not line.strip():
        return [""]
    words = line.split(" ")
    out: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}" if current else word
        if draw.textlength(trial, font=font) <= width:
            current = trial
        else:
            if current:
                out.append(current)
            current = word
    out.append(current)
    return out


def render_page(
    text: str, width: int = 1700, font_size: int = 30, margin: int = 130
) -> Image.Image:
    """Draw the letter on a white page, keeping its own line breaks."""
    font = _font(font_size)
    probe = ImageDraw.Draw(Image.new("L", (10, 10)))
    lines: list[str] = []
    for raw in text.split("\n"):
        lines.extend(_wrap(probe, raw.rstrip(), font, width - 2 * margin))
    line_height = int(font_size * 1.45)
    height = max(int(width * 1.29), 2 * margin + line_height * len(lines))
    page = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(page)
    y = margin
    for line in lines:
        draw.text((margin, y), line, font=font, fill=(20, 20, 24))
        y += line_height
    return page


def photograph(page: Image.Image, seed: int = 0, strength: float = 1.0) -> Image.Image:
    """Make a clean page look like a hand-held phone photo of paper."""
    rng = random.Random(seed)  # noqa: S311 - visual noise, not security
    angle = rng.uniform(-1.6, 1.6) * strength
    background = (rng.randint(70, 110), rng.randint(70, 100), rng.randint(60, 90))
    pad = int(page.width * 0.06)
    canvas = Image.new("RGB", (page.width + 2 * pad, page.height + 2 * pad), background)
    paper = page.copy()
    # Warm paper tint and uneven light from one side.
    shade = (
        Image.linear_gradient("L")
        .resize(paper.size)
        .rotate(rng.choice([0, 90, 180, 270]), expand=False)
    )
    dark = Image.new("RGB", paper.size, (205, 198, 186))
    paper = Image.composite(
        paper, Image.blend(paper, dark, 0.55), shade.point(lambda v: 150 + v * 105 // 255)
    )
    canvas.paste(paper, (pad, pad))
    canvas = canvas.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=background)
    canvas = canvas.filter(ImageFilter.GaussianBlur(radius=0.7 * strength))
    # Seeded sensor noise, so the same seed always gives the same photo.
    small = (max(1, canvas.width // 3), max(1, canvas.height // 3))
    grain = Image.frombytes("L", small, rng.randbytes(small[0] * small[1]))
    noise = grain.resize(canvas.size, Image.Resampling.NEAREST).convert("RGB")
    canvas = Image.blend(canvas, noise, 0.06 * strength)
    return canvas


def render_letter(text: str, photo: bool = True, seed: int = 0, width: int = 1700) -> Image.Image:
    page = render_page(text, width=width)
    return photograph(page, seed=seed) if photo else page
