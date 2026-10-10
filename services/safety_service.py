"""Suspected-toxic-exposure detection and verified emergency-resource lookup."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

import config

_PATTERNS = [
    r"\bswallow(?:ed|ing)?\b", r"\bingest(?:ed|ion)?\b", r"\bover\s?dos(?:e|ed|ing)\b", r"\bpoison(?:ed|ing|ous)?\b",
    r"\btoxic\b", r"\bchest pain\b", r"\b(?:difficulty|trouble) breathing\b", r"\bcan(?:'|no)?t breathe\b",
    r"\bshort(?:ness)? of breath\b", r"\bunconscious\b", r"\bfaint(?:ed|ing)\b", r"\bseizure", r"\bconvuls",
    r"\banaphyla", r"\bswollen (?:throat|tongue|lips|face)\b", r"\bblue (?:lips|skin)\b",
    r"\bvomit(?:ing)? blood\b", r"\bsevere (?:pain|reaction|symptoms?)\b", r"\bemergency\b",
]
_RE = re.compile("|".join(_PATTERNS), re.I)

URGENT_GUIDANCE = [
    "Contact your local emergency services or a poison-information service right away. Do not wait for this app.",
    "Do not induce vomiting and do not try home remedies unless a qualified professional tells you to.",
    "Keep the product packaging and note what was taken, how much, and when, so you can tell the responder.",
    "This app cannot assess an individual poisoning and gives no prediction of outcome.",
]


@dataclass
class SafetyAlert:
    triggered: bool
    matched_terms: list[str]
    guidance: list[str]


def check_toxic_exposure(text: Optional[str]) -> Optional[SafetyAlert]:
    """Return a SafetyAlert if the text suggests suspected poisoning or severe symptoms, else None."""
    if not text or not text.strip():
        return None
    terms = sorted({m.group(0).lower() for m in _RE.finditer(text)})
    if not terms:
        return None
    return SafetyAlert(True, terms, list(URGENT_GUIDANCE))


def load_emergency_resources(country: Optional[str] = None) -> dict:
    """Return configured resources for a country, or {} if none are configured. Never invents numbers."""
    path = config.EMERGENCY_RESOURCES_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    countries = data.get("countries", {}) if isinstance(data, dict) else {}
    if country is None:
        return {k: v for k, v in countries.items() if k != "EXAMPLE-COUNTRY"}
    return countries.get(country, {})
