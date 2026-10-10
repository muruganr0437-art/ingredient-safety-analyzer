"""Upload validation, image clean-up, OCR and label-text parsing.

Nothing here executes uploaded content: files are decoded as images only, and
only whitelisted formats within size/pixel limits are accepted.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

import config

Image.MAX_IMAGE_PIXELS = config.MAX_IMAGE_PIXELS


class ImageValidationError(ValueError):
    """Raised with a user-friendly message when an upload is rejected."""


@dataclass
class OCRResult:
    success: bool
    text: str = ""
    error: Optional[str] = None


@dataclass
class LabelInfo:
    """Fields we could read from the label text. None/empty means 'not found', never 'assumed'."""
    product_name: Optional[str] = None
    ingredients_text: str = ""
    serving_size: Optional[str] = None
    nutrition: dict[str, str] = field(default_factory=dict)
    allergens: Optional[str] = None
    manufacturer: Optional[str] = None
    expiry: Optional[str] = None


def validate_upload(filename: str, data: bytes) -> None:
    """Raise ImageValidationError unless the upload is a safe, decodable JPG/PNG/WEBP image."""
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if ext not in config.ALLOWED_EXTENSIONS:
        raise ImageValidationError(
            f"Unsupported file type '.{ext}'. Please upload a JPG, JPEG, PNG or WEBP image.")
    if not data:
        raise ImageValidationError("The uploaded file is empty.")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise ImageValidationError(f"The file is larger than the {config.MAX_UPLOAD_MB} MB limit.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()  # detects many forms of corruption without fully decoding
        if fmt not in config.ALLOWED_FORMATS:
            raise ImageValidationError("The file content is not a JPEG, PNG or WEBP image.")
        with Image.open(io.BytesIO(data)) as img:
            img.load()  # full decode catches truncated files
    except ImageValidationError:
        raise
    except Image.DecompressionBombError:
        raise ImageValidationError("The image has too many pixels. Please upload a smaller image.")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ImageValidationError("The file is corrupt or is not a valid image.")


def load_image(data: bytes) -> Image.Image:
    """Decode bytes to an RGB image with EXIF orientation applied."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            return img.convert("RGB")
    except Image.DecompressionBombError:
        raise ImageValidationError("The image has too many pixels. Please upload a smaller image.")
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImageValidationError("The file is corrupt or is not a valid image.")


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """Grayscale + autocontrast; upscale small images (Tesseract likes ~300 DPI text)."""
    gray = ImageOps.autocontrast(ImageOps.grayscale(img))
    if max(gray.size) < 1600:
        factor = 2
        gray = gray.resize((gray.width * factor, gray.height * factor), Image.LANCZOS)
    return gray


def run_ocr(img: Image.Image) -> OCRResult:
    """Run Tesseract. Never raises: failures are returned so the UI can offer manual entry."""
    try:
        import pytesseract
    except ImportError:
        return OCRResult(False, error="pytesseract is not installed. Enter the ingredients manually.")
    try:
        if config.TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
        text = pytesseract.image_to_string(preprocess_for_ocr(img), lang=config.OCR_LANG)
    except pytesseract.TesseractNotFoundError:
        return OCRResult(False, error="Tesseract OCR is not installed or not on PATH. "
                                      "Install it (see README) or enter the ingredients manually.")
    except Exception as exc:  # noqa: BLE001 - OCR can fail in many ways; we degrade gracefully
        return OCRResult(False, error=f"OCR failed ({exc.__class__.__name__}). Enter the ingredients manually.")
    text = text.strip()
    if not text:
        return OCRResult(False, error="No readable text was found in the image. "
                                      "Try a sharper, well-lit photo or enter the ingredients manually.")
    return OCRResult(True, text=text)


# ------------------------------------------------------------------ parsing
_STOP = (r"(?:contains|allergen|allergy|nutrition|nutritional|manufactured|marketed|packed|best before|"
         r"use by|expiry|exp\.?|mfg|net (?:wt|weight|quantity)|storage|store in|serving size|fssai|"
         r"customer care|batch)")
_NUTRIENTS = ["energy", "calories", "total fat", "saturated fat", "trans fat", "cholesterol", "sodium",
              "total carbohydrate", "carbohydrate", "total sugars", "added sugars", "sugars", "sugar",
              "dietary fibre", "dietary fiber", "protein", "fat"]


def parse_label_text(text: str) -> LabelInfo:
    """Best-effort extraction from OCR text. Every field is optional and must be user-confirmed."""
    info = LabelInfo()
    flat = re.sub(r"-\s*\n\s*", "", text or "")  # re-join hyphenated line breaks
    one_line = re.sub(r"\s+", " ", flat)

    m = re.search(r"product\s*name\s*[:\-]\s*([^\n]{2,80})", flat, re.I)
    if m:
        info.product_name = m.group(1).strip()

    m = re.search(rf"ingredients?\s*[:\-]?\s*(.+?)(?=\b{_STOP}\b\s*[:\-]?|$)", one_line, re.I)
    if m:
        info.ingredients_text = m.group(1).strip(" .;:")

    m = re.search(r"serving\s*size\s*[:\-]?\s*([^\n]{1,60})", flat, re.I)
    if m:
        info.serving_size = m.group(1).strip()

    m = re.search(r"(?:contains|allergen(?:s| information| advice)?)\s*[:\-]\s*([^\n.]{2,150})", flat, re.I)
    if m:
        info.allergens = m.group(1).strip()

    m = re.search(r"(?:manufactured|marketed|packed|made)\s*by\s*[:\-]?\s*([^\n]{3,120})", flat, re.I)
    if m:
        info.manufacturer = m.group(1).strip()

    m = re.search(r"(?:best before|use by|expiry(?: date)?|exp\.?)\s*[:\-]?\s*"
                  r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2}[/\-.]\d{2,4}|[A-Za-z]{3,9}\.? ?\d{2,4})", flat, re.I)
    if m:
        info.expiry = m.group(1).strip()

    for line in flat.splitlines():
        low = line.lower()
        for n in _NUTRIENTS:
            if low.strip().startswith(n):
                mm = re.search(r"(\d+(?:[.,]\d+)?)\s*(kcal|kj|mg|µg|mcg|g)\b", low)
                if mm and n not in info.nutrition:
                    info.nutrition[n] = f"{mm.group(1)} {mm.group(2)}"
                break
    return info
