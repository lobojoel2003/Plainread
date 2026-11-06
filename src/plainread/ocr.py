"""Turn photos and PDFs of letters into text, entirely on this device.

Photos go through Tesseract OCR after light clean-up (rotation from the
camera's EXIF data, grayscale, contrast, upscaling small images). PDFs use
their text layer when they have one and fall back to OCR for scanned pages.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp", "image/gif"}
PDF_TYPES = {"application/pdf"}
MAX_PIXELS = 60_000_000  # guards against decompression bombs

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class OcrUnavailableError(RuntimeError):
    """Tesseract is not installed or cannot be found."""


class UnsupportedFileError(ValueError):
    """The uploaded file is not an image or PDF we can read."""


@dataclass
class OcrResult:
    text: str
    pages: int
    confidence: float | None
    used_ocr: bool
    warnings: list[str] = field(default_factory=list)


def _windows_tesseract() -> str | None:
    for base in (
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ):
        if base:
            candidate = Path(base) / "Tesseract-OCR" / "tesseract.exe"
            if candidate.exists():
                return str(candidate)
    return None


def tesseract_command() -> str | None:
    """Locate the Tesseract executable (``PLAINREAD_TESSERACT`` overrides)."""
    override = os.environ.get("PLAINREAD_TESSERACT")
    if override:
        return override if Path(override).exists() or shutil.which(override) else None
    found = shutil.which("tesseract")
    if found:
        return found
    if sys.platform == "win32":
        return _windows_tesseract()
    for candidate in (
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/usr/bin/tesseract",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def tesseract_version() -> str | None:
    cmd = tesseract_command()
    if not cmd:
        return None
    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = cmd
        return str(pytesseract.get_tesseract_version())
    except Exception:
        return None


def ocr_available() -> bool:
    return tesseract_version() is not None


def prepare_image(image: Image.Image) -> Image.Image:
    """Clean up a phone photo so Tesseract can read it."""
    image = ImageOps.exif_transpose(image) or image
    if image.mode not in ("L", "RGB"):
        image = image.convert("RGB")
    gray = ImageOps.grayscale(image)
    longest = max(gray.size)
    if longest < 1800:
        scale = 1800 / longest
        gray = gray.resize(
            (round(gray.width * scale), round(gray.height * scale)), Image.Resampling.LANCZOS
        )
    elif longest > 4200:
        scale = 4200 / longest
        gray = gray.resize(
            (round(gray.width * scale), round(gray.height * scale)), Image.Resampling.LANCZOS
        )
    gray = ImageOps.autocontrast(gray, cutoff=1)
    return gray.filter(ImageFilter.SHARPEN)


def _ocr_image(image: Image.Image, lang: str) -> tuple[str, float | None]:
    import pytesseract

    cmd = tesseract_command()
    if not cmd:
        raise OcrUnavailableError("Tesseract OCR is not installed")
    pytesseract.pytesseract.tesseract_cmd = cmd
    prepared = prepare_image(image)
    config = "--oem 1 --psm 3 -c preserve_interword_spaces=1"
    try:
        data = pytesseract.image_to_data(
            prepared, lang=lang, config=config, output_type=pytesseract.Output.DICT
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailableError(str(exc)) from exc
    except pytesseract.TesseractError:
        if lang != "eng":
            return _ocr_image(image, "eng")
        raise
    return _layout_text(data), _mean_confidence(data)


def _mean_confidence(data: dict[str, list[object]]) -> float | None:
    values = []
    for conf, word in zip(data["conf"], data["text"], strict=False):
        try:
            number = float(str(conf))
        except ValueError:
            continue
        if number >= 0 and str(word).strip():
            values.append(number)
    return round(sum(values) / len(values), 1) if values else None


def _layout_text(data: dict[str, list[object]]) -> str:
    """Rebuild lines and paragraphs from Tesseract's word boxes.

    Words are placed at roughly their horizontal position, so columns in
    tables ("Receipt Number    Notice Date") stay lined up.
    """
    words: list[tuple[tuple[int, int, int, int], int, int, str]] = []
    widths: list[float] = []
    for i, word in enumerate(data["text"]):
        word = str(word).strip()
        if not word:
            continue
        key = (
            int(str(data["page_num"][i])),
            int(str(data["block_num"][i])),
            int(str(data["par_num"][i])),
            int(str(data["line_num"][i])),
        )
        left, width = int(str(data["left"][i])), int(str(data["width"][i]))
        words.append((key, left, width, word))
        if len(word) >= 3:
            widths.append(width / len(word))
    if not words:
        return ""
    widths.sort()
    char = max(1.0, widths[len(widths) // 2]) if widths else 10.0
    margin = min(left for _, left, _, _ in words)
    lines: dict[tuple[int, int, int, int], list[tuple[int, int, str]]] = {}
    for key, left, width, word in words:
        lines.setdefault(key, []).append((left, width, word))
    out: list[str] = []
    previous: tuple[int, int, int] | None = None
    for key in sorted(lines):
        paragraph = key[:3]
        if previous is not None and paragraph != previous:
            out.append("")
        line = ""
        for left, _width, word in sorted(lines[key]):
            column = round((left - margin) / char)
            if line:
                gap = column - len(line)
                line += " " * (gap if gap >= 3 else 1)
            else:
                line = " " * min(column, 40)
            line += word
        out.append(line.rstrip())
        previous = paragraph
    return "\n".join(out)


def sniff_type(data: bytes, filename: str = "", declared: str | None = None) -> str:
    if data[:5] == b"%PDF-":
        return "application/pdf"
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").lower()
    except (UnidentifiedImageError, OSError):
        fmt = ""
    mapping = {
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "tiff": "image/tiff",
        "bmp": "image/bmp",
        "gif": "image/gif",
        "mpo": "image/jpeg",
    }
    if fmt in mapping:
        return mapping[fmt]
    if filename.lower().endswith((".txt", ".text")) or (declared or "").startswith("text/"):
        return "text/plain"
    raise UnsupportedFileError(f"Unsupported file type: {filename or declared or 'unknown'}")


def read_pdf(data: bytes, lang: str = "eng") -> OcrResult:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    texts: list[str] = []
    confidences: list[float] = []
    used_ocr = False
    try:
        for index in range(len(pdf)):
            page = pdf[index]
            textpage = page.get_textpage()
            text = textpage.get_text_range().replace("\r\n", "\n")
            textpage.close()
            if len(text.strip()) < 40:
                bitmap = page.render(scale=300 / 72)
                image = bitmap.to_pil()
                text, conf = _ocr_image(image, lang)
                used_ocr = True
                if conf is not None:
                    confidences.append(conf)
            texts.append(text.strip())
            page.close()
    finally:
        pdf.close()
    conf_value = round(sum(confidences) / len(confidences), 1) if confidences else None
    return OcrResult("\n\n".join(texts), len(texts), conf_value, used_ocr)


def read_image(data: bytes, lang: str = "eng") -> OcrResult:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UnsupportedFileError("Could not open the image") from exc
    frames = getattr(image, "n_frames", 1)
    texts: list[str] = []
    confs: list[float] = []
    for frame in range(min(frames, 20)):
        if frames > 1:
            image.seek(frame)
        text, conf = _ocr_image(image.copy(), lang)
        texts.append(text)
        if conf is not None:
            confs.append(conf)
    conf_value = round(sum(confs) / len(confs), 1) if confs else None
    return OcrResult("\n\n".join(texts), len(texts), conf_value, True)


def read_file(
    data: bytes, filename: str = "", content_type: str | None = None, lang: str = "eng"
) -> OcrResult:
    """Read one uploaded file (photo, PDF or plain text)."""
    kind = sniff_type(data, filename, content_type)
    if kind in PDF_TYPES:
        return read_pdf(data, lang)
    if kind == "text/plain":
        return OcrResult(data.decode("utf-8", errors="replace"), 1, None, False)
    return read_image(data, lang)
