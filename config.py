"""Central configuration. All paths are absolute and derived from this file's location."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "analyzer.db")).resolve()
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"
SEED_PATH = BASE_DIR / "database" / "seed_ingredients.json"

# Uploads
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "8"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_IMAGE_PIXELS = 25_000_000  # guards against decompression bombs

# OCR
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()
OCR_LANG = os.getenv("OCR_LANG", "eng").strip() or "eng"

# Admin (empty password => admin page disabled)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

# Optional AI layer (disabled by default)
AI_ENABLED = _bool("AI_ENABLED", False)
AI_API_URL = os.getenv("AI_API_URL", "").strip()
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "").strip()

# Emergency resources (verified, per-country; we never ship invented numbers)
EMERGENCY_RESOURCES_FILE = Path(
    os.getenv("EMERGENCY_RESOURCES_FILE", DATA_DIR / "emergency_resources.json")
)

APP_NAME = "AI Ingredient Safety Analyzer"
