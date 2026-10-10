"""Evidence helpers: labels, source validation, optional reachability check, tiny keyword retriever."""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from models.ingredient import Ingredient, validate_http_url

EVIDENCE_LABELS = {
    "established": "Established evidence",
    "limited": "Limited or emerging evidence",
    "insufficient": "Insufficient evidence",
    "not_assessed": "Not assessed in the available database",
}
EVIDENCE_TYPE_LABELS = {
    "established_causal": "Established causal effect",
    "association": "Statistical association (causation not established)",
    "theoretical": "Theoretical / mechanistic concern",
}
TIMEFRAME_LABELS = {
    "short_term": "Short-term", "long_term": "Long-term",
    "allergy_sensitivity": "Allergy / sensitivity", "other": "Other",
}
VERIFICATION_NOTES = {
    "unverified": "This database record has NOT been reviewed by a person. Treat it as a lead to check, not as verified fact.",
    "reviewed": "This record was reviewed by a database administrator (see review date).",
    "outdated": "This record is flagged as OUTDATED and may no longer reflect current assessments.",
}


def validate_source_url(url: str) -> tuple[bool, str]:
    """Format-only check (no network). Returns (ok, message)."""
    try:
        validate_http_url(url)
        return True, "ok"
    except ValueError as exc:
        return False, str(exc)


def check_url_reachable(url: str, timeout: float = 5.0) -> Optional[bool]:
    """Optional live check. Returns None if the network check itself could not be performed."""
    ok, _ = validate_source_url(url)
    if not ok:
        return False
    try:
        import requests
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        return r.status_code < 400
    except Exception:  # noqa: BLE001
        return None


def source_problems(ing: Ingredient) -> list[str]:
    """List provenance gaps for a record (used in the report's missing-data section)."""
    problems: list[str] = []
    if not ing.sources:
        problems.append("No evidence source is recorded for this ingredient.")
    for s in ing.sources:
        ok, msg = validate_source_url(s.url)
        if not ok:
            problems.append(msg)
        if not s.retrieval_date:
            problems.append(f"Source not yet checked by a reviewer (no retrieval date): {s.title}")
    for e in ing.health_effects:
        if not e.source_url:
            problems.append(f"Health effect has no source: {e.effect[:60]}")
    for lim in ing.safety_limits:
        if not lim.source_url:
            problems.append(f"{lim.limit_type} has no source.")
        if lim.verification_status != "reviewed":
            problems.append(f"{lim.limit_type} of {lim.value_mg_per_kg_bw:g} mg/kg bw/day is not reviewed, so it is not used for comparisons.")
    return problems


# --- Lightweight retrieval over APPROVED records only (keyword scoring; swap for FAISS later) ---
def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]{3,}", (text or "").lower())


def retrieve_evidence(query: str, ingredients: list[Ingredient], k: int = 5) -> list[dict]:
    """Rank curated source claims by keyword overlap. Returns [] if nothing relevant (=> 'insufficient evidence')."""
    q = Counter(_tokens(query))
    scored: list[tuple[int, dict]] = []
    for ing in ingredients:
        for s in ing.sources:
            doc = " ".join([ing.canonical_name, s.title, s.claim_supported])
            overlap = sum(min(q[t], c) for t, c in Counter(_tokens(doc)).items() if t in q)
            if overlap:
                scored.append((overlap, {"ingredient": ing.canonical_name, "title": s.title, "url": s.url,
                                         "claim": s.claim_supported, "publisher": s.publisher}))
    scored.sort(key=lambda t: -t[0])
    return [d for _, d in scored[:k]]
