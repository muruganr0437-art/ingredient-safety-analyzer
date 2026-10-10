import io

import pytest
from PIL import Image

import config
from services import ocr_service as o


def _img_bytes(fmt="PNG", size=(40, 40), color="white", exif=None):
    buf = io.BytesIO()
    img = Image.new("RGB", size, color)
    kwargs = {"exif": exif} if exif else {}
    img.save(buf, fmt, **kwargs)
    return buf.getvalue()


def test_valid_png_and_jpeg_and_webp():
    for fmt, name in [("PNG", "a.png"), ("JPEG", "a.jpg"), ("WEBP", "a.webp")]:
        o.validate_upload(name, _img_bytes(fmt))


def test_wrong_extension_rejected():
    with pytest.raises(o.ImageValidationError, match="Unsupported"):
        o.validate_upload("evil.exe", b"MZ...")


def test_empty_file_rejected():
    with pytest.raises(o.ImageValidationError, match="empty"):
        o.validate_upload("a.png", b"")


def test_corrupt_image_rejected():
    with pytest.raises(o.ImageValidationError, match="corrupt"):
        o.validate_upload("a.png", b"this is not an image")


def test_truncated_image_rejected():
    data = _img_bytes("PNG", (300, 300), "red")
    with pytest.raises(o.ImageValidationError):
        o.validate_upload("a.png", data[: len(data) // 2])


def test_oversize_rejected(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(o.ImageValidationError, match="larger"):
        o.validate_upload("a.png", _img_bytes())


def test_exif_orientation_is_applied():
    exif = Image.Exif()
    exif[274] = 6  # rotate 90 degrees
    data = _img_bytes("JPEG", (40, 20), exif=exif)
    img = o.load_image(data)
    assert img.size == (20, 40)


def test_ocr_failure_is_returned_not_raised(monkeypatch):
    import pytesseract

    def boom(*a, **k):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_string", boom)
    res = o.run_ocr(Image.new("RGB", (50, 50), "white"))
    assert not res.success and "manually" in res.error


def test_ocr_empty_text_is_failure(monkeypatch):
    import pytesseract
    monkeypatch.setattr(pytesseract, "image_to_string", lambda *a, **k: "  \n ")
    assert not o.run_ocr(Image.new("RGB", (50, 50))).success


def test_ocr_success_path(monkeypatch):
    import pytesseract
    monkeypatch.setattr(pytesseract, "image_to_string", lambda *a, **k: "Ingredients: Water")
    res = o.run_ocr(Image.new("RGB", (50, 50)))
    assert res.success and "Water" in res.text


SAMPLE = """Product Name: Fizzy Orange
Ingredients: Carbonated water, sugar,
acidity regulator (citric acid), preserva-
tive (sodium benzoate), colour (E110).
Contains: No major allergens
Serving size: 250 ml
Energy 105 kcal
Total Sugars 26 g
Sodium 12 mg
Manufactured by: Example Beverages Pvt Ltd, Chennai
Best before: 12/2027
"""


def test_parse_label_text():
    info = o.parse_label_text(SAMPLE)
    assert info.product_name == "Fizzy Orange"
    assert "preservative (sodium benzoate)" in info.ingredients_text
    assert info.ingredients_text.endswith("colour (E110)")
    assert info.serving_size == "250 ml"
    assert info.nutrition["energy"] == "105 kcal" and info.nutrition["sodium"] == "12 mg"
    assert info.manufacturer.startswith("Example Beverages")
    assert info.expiry == "12/2027"
    assert info.allergens.startswith("No major allergens")


def test_parse_label_text_missing_fields_stay_empty():
    info = o.parse_label_text("random words")
    assert info.ingredients_text == "" and info.expiry is None and info.nutrition == {}
