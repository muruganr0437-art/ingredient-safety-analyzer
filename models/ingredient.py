"""Pydantic models for curated ingredient records (single source of validation)."""
from __future__ import annotations

import re
from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

EvidenceLevel = Literal["established", "limited", "insufficient", "not_assessed"]
VerificationStatus = Literal["unverified", "reviewed", "outdated"]
Timeframe = Literal["short_term", "long_term", "allergy_sensitivity", "other"]
EvidenceType = Literal["established_causal", "association", "theoretical"]
LimitType = Literal["ADI", "TDI", "MTDI", "other"]

_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def validate_http_url(url: str) -> str:
    """Return the stripped URL or raise ValueError if it is not a plausible http(s) URL."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or " " in url:
        raise ValueError(f"Invalid source URL: {url!r}")
    return url


def _check_date(value: Optional[str]) -> Optional[str]:
    if value is None or not str(value).strip():
        return None
    value = str(value).strip()
    if not _DATE_RE.match(value):
        raise ValueError("Dates must look like YYYY, YYYY-MM or YYYY-MM-DD")
    return value


class EvidenceSource(BaseModel):
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    url: str
    publication_date: Optional[str] = None
    retrieval_date: Optional[str] = None  # when a human actually opened and checked it
    claim_supported: str = Field(min_length=1)

    _v_url = field_validator("url")(lambda cls, v: validate_http_url(v))
    _v_pub = field_validator("publication_date")(lambda cls, v: _check_date(v))
    _v_ret = field_validator("retrieval_date")(lambda cls, v: _check_date(v))


class HealthEffect(BaseModel):
    effect: str = Field(min_length=1)
    timeframe: Timeframe = "other"
    body_system: Optional[str] = None
    exposure_route: str = "oral"
    evidence_type: EvidenceType = "theoretical"
    evidence_level: EvidenceLevel = "insufficient"
    conditions: Optional[str] = None
    source_url: Optional[str] = None  # must match one of the record's sources


class SafetyLimit(BaseModel):
    limit_type: LimitType = "ADI"
    value_mg_per_kg_bw: float = Field(gt=0)
    expressed_as: Optional[str] = None
    authority: str = Field(min_length=1)
    jurisdiction: str = "International"
    source_url: Optional[str] = None
    verification_status: VerificationStatus = "unverified"
    reviewed_on: Optional[str] = None
    notes: Optional[str] = None

    _v_rev = field_validator("reviewed_on")(lambda cls, v: _check_date(v))

    @model_validator(mode="after")
    def _reviewed_needs_provenance(self) -> "SafetyLimit":
        if self.verification_status == "reviewed" and (not self.source_url or not self.reviewed_on):
            raise ValueError("A 'reviewed' safety limit needs a source_url and reviewed_on date")
        return self


class Ingredient(BaseModel):
    id: Optional[int] = None
    canonical_name: str = Field(min_length=1)
    synonyms: list[str] = Field(default_factory=list)
    ins_number: Optional[str] = None
    e_number: Optional[str] = None
    category: str = "unspecified"
    purpose: str = ""
    hazard_summary: Optional[str] = None
    evidence_level: EvidenceLevel = "not_assessed"
    evidence_limitations: Optional[str] = None
    permitted_use_notes: Optional[str] = None
    allergen_notes: Optional[str] = None
    precautions: Optional[str] = None
    verification_status: VerificationStatus = "unverified"
    reviewed_on: Optional[str] = None
    sources: list[EvidenceSource] = Field(default_factory=list)
    health_effects: list[HealthEffect] = Field(default_factory=list)
    safety_limits: list[SafetyLimit] = Field(default_factory=list)

    _v_rev = field_validator("reviewed_on")(lambda cls, v: _check_date(v))

    @field_validator("canonical_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("canonical_name must not be blank")
        return v

    @field_validator("e_number")
    @classmethod
    def _e_number(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        v = v.strip().upper().replace(" ", "")
        if not v.startswith("E"):
            v = "E" + v
        if not re.fullmatch(r"E\d{3,4}[A-Z]?", v):
            raise ValueError("e_number must look like E102 or E160A")
        return v

    @field_validator("ins_number")
    @classmethod
    def _ins_number(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        v = v.strip().upper().replace(" ", "")
        if v.startswith("INS"):
            v = v[3:]
        if not re.fullmatch(r"\d{3,4}[A-Z]?", v):
            raise ValueError("ins_number must look like 102 or 160A")
        return v

    @field_validator("synonyms")
    @classmethod
    def _synonyms(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for s in v:
            s = (s or "").strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
        return out

    @model_validator(mode="after")
    def _consistency(self) -> "Ingredient":
        urls = {s.url for s in self.sources}
        for eff in self.health_effects:
            if eff.source_url and eff.source_url not in urls:
                raise ValueError(f"Health effect cites a source not listed in 'sources': {eff.source_url}")
        for lim in self.safety_limits:
            if lim.source_url and lim.source_url not in urls:
                raise ValueError(f"Safety limit cites a source not listed in 'sources': {lim.source_url}")
        if self.verification_status == "reviewed":
            if not self.sources:
                raise ValueError("A 'reviewed' record needs at least one source")
            if not self.reviewed_on:
                raise ValueError("A 'reviewed' record needs a reviewed_on date")
        return self

    @property
    def identifier_label(self) -> str:
        parts = []
        if self.e_number:
            parts.append(self.e_number)
        if self.ins_number:
            parts.append(f"INS {self.ins_number}")
        return " / ".join(parts)
