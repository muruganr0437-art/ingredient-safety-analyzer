"""Build the structured report, then render it to TXT and PDF from the same content blocks."""
from __future__ import annotations

import copy
import io
from datetime import datetime, timezone
from typing import Optional
from xml.sax.saxutils import escape

from models.ingredient import Ingredient
from services.evidence_service import (EVIDENCE_LABELS, EVIDENCE_TYPE_LABELS, TIMEFRAME_LABELS,
                                       VERIFICATION_NOTES, source_problems)
from services.exposure_service import ADI_NOTE, ExposureResult
from services.ingredient_service import MatchResult
from services.safety_service import SafetyAlert

RISK_NONE = "No specific concern identified in the available data"
RISK_POTENTIAL = "Potential concern under particular conditions"
RISK_ASSESS = "Additional assessment needed"
RISK_URGENT = "Urgent medical evaluation recommended"

DISCLAIMER = (
    "This report is an educational screening aid, not a medical diagnosis or advice. It cannot predict an "
    "individual's health outcome, lifespan or time to harm. Absence of an identified concern is not evidence "
    "of safety. Database records marked 'unverified' have not been reviewed by a person. If you suspect "
    "poisoning or have severe symptoms, contact local emergency services or a poison-information service "
    "immediately."
)


def risk_category(ing: Ingredient) -> str:
    """Conservative categorisation: unverified/unassessed records can never produce 'no specific concern'."""
    if ing.health_effects or ing.hazard_summary:
        return RISK_POTENTIAL
    if ing.evidence_level == "not_assessed" or ing.verification_status != "reviewed":
        return RISK_ASSESS
    return RISK_NONE


def describe_ingredient(ing: Ingredient, input_name: Optional[str] = None,
                        match: Optional[MatchResult] = None) -> dict:
    """Flatten one ingredient record into a display/report entry."""
    return {
        "ingredient_id": ing.id,
        "input_name": input_name or ing.canonical_name,
        "match_type": match.match_type if match else "canonical",
        "confidence": match.confidence if match else 1.0,
        "match_note": match.note if match else "",
        "declared_percent": match.declared_percent if match else None,
        "canonical_name": ing.canonical_name,
        "identifiers": ing.identifier_label,
        "category": ing.category,
        "purpose": ing.purpose or "Not recorded.",
        "risk_category": risk_category(ing),
        "verification_status": ing.verification_status,
        "verification_note": VERIFICATION_NOTES[ing.verification_status],
        "reviewed_on": ing.reviewed_on,
        "hazard_summary": ing.hazard_summary,
        "effects": [{
            "effect": e.effect, "timeframe": TIMEFRAME_LABELS[e.timeframe], "body_system": e.body_system,
            "route": e.exposure_route, "evidence_type": EVIDENCE_TYPE_LABELS[e.evidence_type],
            "evidence_level": EVIDENCE_LABELS[e.evidence_level], "conditions": e.conditions,
            "source_url": e.source_url,
        } for e in ing.health_effects],
        "allergen_notes": ing.allergen_notes,
        "permitted_use_notes": ing.permitted_use_notes,
        "safety_limits": [{
            "text": (f"{l.limit_type} {l.value_mg_per_kg_bw:g} mg/kg body weight/day"
                     + (f" (expressed as {l.expressed_as})" if l.expressed_as else "")
                     + f" - {l.authority}, {l.jurisdiction}. Status: {l.verification_status}."
                     + (f" {l.notes}" if l.notes else "")),
            "source_url": l.source_url,
        } for l in ing.safety_limits],
        "evidence_level": EVIDENCE_LABELS[ing.evidence_level],
        "evidence_limitations": ing.evidence_limitations,
        "precautions": ing.precautions,
        "sources": [s.model_dump() for s in ing.sources],
        "source_problems": source_problems(ing),
    }


def build_report(
    product_name: str,
    matches: list[MatchResult],
    ingredients_by_id: dict[int, Ingredient],
    exposures: Optional[list[ExposureResult]] = None,
    label_info: Optional[dict] = None,
    safety_alert: Optional[SafetyAlert] = None,
    confirmed_inputs: Optional[set[str]] = None,
    generated_at: Optional[str] = None,
) -> dict:
    """Assemble the report dict. Unconfirmed fuzzy matches are listed as pending, not analysed."""
    confirmed_inputs = confirmed_inputs or set()
    entries: list[dict] = []
    unmatched: list[str] = []
    pending: list[dict] = []
    for m in matches:
        if m.match_type == "none" or m.ingredient_id is None or m.ingredient_id not in ingredients_by_id:
            unmatched.append(m.input_name)
            continue
        ing = ingredients_by_id[m.ingredient_id]
        if m.needs_confirmation and m.input_name not in confirmed_inputs:
            pending.append({"input_name": m.input_name, "suggested": ing.canonical_name, "confidence": m.confidence})
            continue
        entries.append(describe_ingredient(ing, m.input_name, m))

    label_info = label_info or {}
    missing: list[str] = []
    if unmatched:
        missing.append("Not found in the ingredient database (not assessed): " + ", ".join(unmatched))
    for p in pending:
        missing.append(f"Unconfirmed match for '{p['input_name']}' (suggested: {p['suggested']}); not analysed.")
    for e in entries:
        label = e["canonical_name"]
        if e["verification_status"] != "reviewed":
            missing.append(f"{label}: database record is {e['verification_status']}.")
        if not e["safety_limits"]:
            missing.append(f"{label}: no numerical safety limit recorded.")
        for prob in e["source_problems"]:
            missing.append(f"{label}: {prob}")
        if e["evidence_level"] == EVIDENCE_LABELS["not_assessed"]:
            missing.append(f"{label}: hazards not assessed in the available database (not evidence of safety).")
    exposures = exposures or []
    if not any(x.status == "ok" for x in exposures):
        missing.append("No exposure calculation was performed (validated concentration, serving data and body "
                       "weight are required; ingredient-list order is not a concentration).")
    for x in exposures:
        for item in x.missing:
            missing.append(f"Exposure for {x.ingredient_name}: {item}")

    precautions = ["Use this report as a starting point; discuss personal health questions with a qualified clinician.",
                   "Check the product label and the manufacturer for information this report cannot see."]
    for e in entries:
        if e["precautions"]:
            precautions.append(f"{e['canonical_name']}: {e['precautions']}")

    counts: dict[str, int] = {}
    for e in entries:
        counts[e["risk_category"]] = counts.get(e["risk_category"], 0) + 1
    if unmatched or pending:
        counts[RISK_ASSESS] = counts.get(RISK_ASSESS, 0) + len(unmatched) + len(pending)

    return {
        "title": "Ingredient Safety Report",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "product": {"name": product_name or "Unnamed product", **{k: v for k, v in label_info.items() if v}},
        "ingredients": entries, "unmatched": unmatched, "pending_confirmation": pending,
        "exposures": [x.to_dict() for x in exposures],
        "missing_data": missing, "precautions": precautions, "risk_counts": counts,
        "safety_alert": ({"terms": safety_alert.matched_terms, "guidance": safety_alert.guidance,
                          "category": RISK_URGENT} if safety_alert and safety_alert.triggered else None),
        "disclaimer": DISCLAIMER,
    }


def redact_report(report: dict) -> dict:
    """Copy of the report safe to store in history: no body weight / personal exposure inputs."""
    r = copy.deepcopy(report)
    for x in r.get("exposures", []):
        x["personal_assumptions"] = []
    return r


# ---------------------------------------------------------------- rendering
def _blocks(report: dict) -> list[tuple[str, str]]:
    """Convert the report to a flat list of (kind, text) blocks shared by TXT and PDF renderers."""
    b: list[tuple[str, str]] = [("title", report["title"]), ("p", f"Generated: {report['generated_at']} (UTC)")]
    if report.get("safety_alert"):
        b.append(("h1", f"URGENT: {RISK_URGENT}"))
        b.extend(("bullet", g) for g in report["safety_alert"]["guidance"])
    p = report["product"]
    b.append(("h1", "1. Product overview"))
    b.append(("p", f"Product: {p.get('name')}"))
    for key, label in [("serving_size", "Serving size"), ("allergens", "Declared allergens (from label text)"),
                       ("manufacturer", "Manufacturer"), ("expiry", "Expiry/best-before")]:
        if p.get(key):
            b.append(("p", f"{label}: {p[key]}"))
    if p.get("nutrition"):
        b.append(("p", "Nutrition (as read from label): " + "; ".join(f"{k}: {v}" for k, v in p["nutrition"].items())))
    b.append(("p", "Fields come from OCR/manual input and may contain errors."))

    b.append(("h1", "2. Ingredient identification results"))
    for e in report["ingredients"]:
        extra = f", declared {e['declared_percent']:g}%" if e.get("declared_percent") else ""
        ident = f" [{e['identifiers']}]" if e["identifiers"] else ""
        b.append(("bullet", f"'{e['input_name']}' -> {e['canonical_name']}{ident} "
                            f"(match: {e['match_type']}, confidence {e['confidence']:.2f}{extra})"))
    for n in report["unmatched"]:
        b.append(("bullet", f"'{n}' -> not found in the database (not assessed)"))
    for pnd in report["pending_confirmation"]:
        b.append(("bullet", f"'{pnd['input_name']}' -> possible match '{pnd['suggested']}' awaiting confirmation"))

    b.append(("h1", "3. Ingredient purposes"))
    for e in report["ingredients"]:
        b.append(("bullet", f"{e['canonical_name']} ({e['category']}): {e['purpose']}"))

    b.append(("h1", "4. Potential health concerns"))
    for e in report["ingredients"]:
        b.append(("h2", f"{e['canonical_name']} - {e['risk_category']}"))
        b.append(("p", f"Record status: {e['verification_note']}"))
        b.append(("p", f"Overall evidence: {e['evidence_level']}"))
        if e["hazard_summary"]:
            b.append(("p", f"Summary: {e['hazard_summary']}"))
        for ef in e["effects"]:
            line = f"{ef['timeframe']}: {ef['effect']} [{ef['evidence_type']}; {ef['evidence_level']}; route: {ef['route']}]"
            if ef["conditions"]:
                line += f" Conditions: {ef['conditions']}"
            b.append(("bullet", line))
            if ef["source_url"]:
                b.append(("url", ef["source_url"]))
        if e["evidence_limitations"]:
            b.append(("p", f"Evidence limitations: {e['evidence_limitations']}"))
        if e["permitted_use_notes"]:
            b.append(("p", f"Permitted-use notes: {e['permitted_use_notes']}"))

    b.append(("h1", "5. Affected body systems (only where evidence supports an association)"))
    any_sys = False
    for e in report["ingredients"]:
        for ef in e["effects"]:
            if ef["body_system"]:
                any_sys = True
                b.append(("bullet", f"{e['canonical_name']}: {ef['body_system']} ({ef['evidence_type']})"))
    if not any_sys:
        b.append(("p", "No body-system associations are recorded in the available data."))

    b.append(("h1", "6. Exposure assessment"))
    if not report["exposures"]:
        b.append(("p", "No exposure calculation was performed."))
    for x in report["exposures"]:
        b.append(("h2", x["ingredient_name"] or "Ingredient"))
        if x["status"] != "ok":
            b.append(("p", x["message"]))
        else:
            b.append(("bullet", f"Estimated daily intake: {x['daily_intake_mg']:.4g} mg/day"))
            b.append(("bullet", f"Exposure: {x['exposure_mg_per_kg_bw']:.4g} mg/kg body weight/day"))
            if x["percent_of_adi"] is not None:
                b.append(("bullet", f"Percentage of the applicable reviewed ADI ({x['adi_mg_per_kg_bw']:g} mg/kg bw/day): "
                                    f"{x['percent_of_adi']:.1f}%"))
            else:
                b.append(("bullet", "No comparison with a safety limit was made."))
        for a in x["assumptions"] + x["personal_assumptions"]:
            b.append(("bullet", f"Assumption: {a}"))
        for m in x["missing"]:
            b.append(("bullet", f"Missing: {m}"))
        for l in x["limitations"]:
            b.append(("p", f"Limitation: {l}"))

    b.append(("h1", "7. Known safety limits and interpretation"))
    any_limit = False
    for e in report["ingredients"]:
        for l in e["safety_limits"]:
            any_limit = True
            b.append(("bullet", f"{e['canonical_name']}: {l['text']}"))
            if l["source_url"]:
                b.append(("url", l["source_url"]))
    if not any_limit:
        b.append(("p", "No numerical safety limits are recorded for the matched ingredients."))
    b.append(("p", ADI_NOTE))

    b.append(("h1", "8. Allergen and sensitivity warnings"))
    allergy = False
    for e in report["ingredients"]:
        for ef in e["effects"]:
            if ef["timeframe"] == TIMEFRAME_LABELS["allergy_sensitivity"]:
                allergy = True
                b.append(("bullet", f"{e['canonical_name']}: {ef['effect']}"))
        if e["allergen_notes"]:
            allergy = True
            b.append(("bullet", f"{e['canonical_name']}: {e['allergen_notes']}"))
    if report["product"].get("allergens"):
        allergy = True
        b.append(("bullet", f"Label text states: {report['product']['allergens']}"))
    if not allergy:
        b.append(("p", "No allergen or sensitivity entries are recorded. Always read the product's own allergen statement."))

    b.append(("h1", "9. Missing data and uncertainty"))
    b.extend(("bullet", m) for m in report["missing_data"]) if report["missing_data"] else b.append(("p", "None identified."))

    b.append(("h1", "10. Practical precautions"))
    b.extend(("bullet", pr) for pr in report["precautions"])

    b.append(("h1", "11. Scientific references"))
    seen: set[tuple[str, str]] = set()
    for e in report["ingredients"]:
        for s in e["sources"]:
            key = (s["url"], s["claim_supported"])
            if key in seen:
                continue
            seen.add(key)
            retrieved = s["retrieval_date"] or "not yet checked by a reviewer"
            b.append(("bullet", f"{e['canonical_name']}: {s['title']} - {s['publisher']}"
                                f" (published {s['publication_date'] or 'n/a'}; retrieved: {retrieved}). "
                                f"Supports: {s['claim_supported']}"))
            b.append(("url", s["url"]))
    if not seen:
        b.append(("p", "No references are available for the matched ingredients. Evidence could not be verified."))

    b.append(("h1", "12. Disclaimer"))
    b.append(("p", report["disclaimer"]))
    return b


def report_to_text(report: dict) -> str:
    out: list[str] = []
    for kind, text in _blocks(report):
        if kind == "title":
            out += [text.upper(), "=" * len(text)]
        elif kind == "h1":
            out += ["", text, "-" * len(text)]
        elif kind == "h2":
            out += ["", text]
        elif kind == "bullet":
            out.append(f"  * {text}")
        elif kind == "url":
            out.append(f"      {text}")
        else:
            out.append(text)
    return "\n".join(out) + "\n"


def _pdf_safe(text: str) -> str:
    """Standard PDF fonts are Latin-1/WinAnsi; replace anything else rather than crash."""
    return text.encode("cp1252", errors="replace").decode("cp1252")


def report_to_pdf(report: dict) -> bytes:
    """Render the complete report (with clickable reference URLs) to PDF bytes."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    ss = getSampleStyleSheet()
    styles = {
        "title": ss["Title"], "h1": ParagraphStyle("h1x", parent=ss["Heading2"], spaceBefore=10),
        "h2": ss["Heading3"], "p": ss["BodyText"],
        "bullet": ParagraphStyle("bx", parent=ss["BodyText"], leftIndent=12, bulletIndent=2),
        "url": ParagraphStyle("ux", parent=ss["BodyText"], leftIndent=24, fontSize=8, textColor="#1a56db"),
    }
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title=report["title"])
    flow = []
    for kind, text in _blocks(report):
        safe = escape(_pdf_safe(text))
        if kind == "url":
            para = Paragraph(f'<link href="{escape(text, {chr(34): "&quot;"})}">{safe}</link>', styles["url"])
        elif kind == "bullet":
            para = Paragraph(safe, styles["bullet"], bulletText="\u2022")
        else:
            para = Paragraph(safe, styles[kind])
        flow.append(para)
        if kind == "title":
            flow.append(Spacer(1, 4))
    doc.build(flow)
    return buf.getvalue()
