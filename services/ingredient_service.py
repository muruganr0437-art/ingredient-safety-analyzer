"""Ingredient-list parsing and deterministic matching (exact -> identifier -> flagged fuzzy)."""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from models.ingredient import Ingredient

_ID_RE = re.compile(r"\b(e|ins)\s*-?\s*(\d{3,4}[a-z]?)\b", re.I)
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


def normalize_name(text: str) -> str:
    """Lower-case, strip accents/punctuation, collapse whitespace ('FD&C Yellow No. 5' -> 'fd and c yellow no 5')."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class ParsedItem:
    raw: str
    name: str
    inner: list[str] = field(default_factory=list)
    declared_percent: Optional[float] = None


@dataclass
class MatchResult:
    input_name: str
    match_type: str  # 'canonical' | 'synonym' | 'identifier' | 'fuzzy' | 'none'
    ingredient_id: Optional[int] = None
    confidence: float = 0.0
    needs_confirmation: bool = False
    declared_percent: Optional[float] = None
    note: str = ""


@dataclass
class IngredientIndex:
    names: dict[str, tuple[int, str]] = field(default_factory=dict)  # normalized -> (id, 'canonical'|'synonym')
    e_numbers: dict[str, int] = field(default_factory=dict)
    ins_numbers: dict[str, int] = field(default_factory=dict)


def build_index(ingredients: list[Ingredient]) -> IngredientIndex:
    idx = IngredientIndex()
    for ing in ingredients:
        if ing.id is None:
            raise ValueError("Ingredients must be loaded from the database (id missing).")
        idx.names[normalize_name(ing.canonical_name)] = (ing.id, "canonical")
    for ing in ingredients:  # synonyms never overwrite a canonical name
        for syn in ing.synonyms:
            idx.names.setdefault(normalize_name(syn), (ing.id, "synonym"))
        if ing.e_number:
            idx.e_numbers[ing.e_number[1:].lower()] = ing.id
        if ing.ins_number:
            idx.ins_numbers[ing.ins_number.lower()] = ing.id
    return idx


# ------------------------------------------------------------------- parsing
def _split_top_level(text: str) -> list[str]:
    parts, depth, buf = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch in ",;•·" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def split_ingredient_list(text: str) -> list[ParsedItem]:
    """Split a label's ingredient text into items, keeping parenthetical sub-ingredients."""
    text = re.sub(r"-\s*\n\s*", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^\s*ingredients?\s*[:\-]?\s*", "", text, flags=re.I).strip(" .")
    items: list[ParsedItem] = []
    for raw in _split_top_level(text):
        percent: Optional[float] = None
        inner: list[str] = []
        m = re.search(r"[(\[](.*)[)\]]", raw)
        outer = raw
        if m:
            outer = (raw[:m.start()] + raw[m.end():]).strip()
            inner_text = m.group(1)
            if re.fullmatch(r"\s*\d+(?:[.,]\d+)?\s*%\s*", inner_text):
                percent = float(inner_text.strip().rstrip("%").strip().replace(",", "."))
            else:
                inner = [_PERCENT_RE.sub("", p).strip(" .") for p in _split_top_level(inner_text)]
                inner = [p for p in inner if p]
        pm = _PERCENT_RE.search(outer)
        if pm:
            percent = float(pm.group(1).replace(",", "."))
            outer = _PERCENT_RE.sub("", outer)
        outer = outer.strip(" .:-")
        if outer or inner:
            items.append(ParsedItem(raw=raw, name=outer, inner=inner, declared_percent=percent))
    return items


# ------------------------------------------------------------------ matching
def match_text(text: str, idx: IngredientIndex, percent: Optional[float] = None) -> MatchResult:
    """Match one phrase. Exact name/synonym first, then E/INS number, then a *flagged* fuzzy suggestion."""
    norm = normalize_name(text)
    if norm in idx.names:
        iid, kind = idx.names[norm]
        return MatchResult(text, kind, iid, 1.0, False, percent)
    for m in _ID_RE.finditer(text or ""):
        prefix, num = m.group(1).lower(), m.group(2).lower()
        table = idx.e_numbers if prefix == "e" else idx.ins_numbers
        if num in table:
            return MatchResult(text, "identifier", table[num], 0.95, False, percent,
                               note=f"Matched by {prefix.upper()} {num.upper()}")
    if len(norm) >= 5:
        close = difflib.get_close_matches(norm, list(idx.names), n=1, cutoff=0.85)
        if close:
            iid, _ = idx.names[close[0]]
            ratio = difflib.SequenceMatcher(None, norm, close[0]).ratio()
            return MatchResult(text, "fuzzy", iid, round(ratio, 2), True, percent,
                               note=f"Possible match to '{close[0]}' - please confirm")
    return MatchResult(text, "none", None, 0.0, False, percent, note="Not found in the ingredient database")


def match_items(items: list[ParsedItem], idx: IngredientIndex) -> list[MatchResult]:
    """Match parsed items; de-duplicates by ingredient id and keeps unknowns visible."""
    results: list[MatchResult] = []
    for item in items:
        outer = match_text(item.name, idx, item.declared_percent) if item.name else None
        inner = [match_text(p, idx) for p in item.inner]
        inner_hits = [r for r in inner if r.match_type != "none"]
        if outer and outer.match_type != "none":
            results.append(outer)
            results.extend(inner_hits)
        elif inner_hits:
            # e.g. "Preservative (Sodium benzoate)": the functional-class word is not an ingredient.
            for r in inner_hits:
                if item.declared_percent and r.declared_percent is None:
                    r.declared_percent = item.declared_percent
            results.extend(inner_hits)
        elif outer:
            results.append(outer)
        else:
            results.extend(inner)
    seen: set[int] = set()
    unique: list[MatchResult] = []
    for r in results:
        if r.ingredient_id is not None and r.match_type != "fuzzy":
            if r.ingredient_id in seen:
                continue
            seen.add(r.ingredient_id)
        unique.append(r)
    return unique
