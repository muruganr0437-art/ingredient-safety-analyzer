import pytest
from pydantic import ValidationError

from models.ingredient import EvidenceSource, Ingredient
from services import ai_service
from services import ingredient_service as isvc
from services import report_service as rs
from services.evidence_service import retrieve_evidence, source_problems, validate_source_url
from services.exposure_service import calculate_exposure


@pytest.fixture()
def report(ingredients):
    idx = isvc.build_index(ingredients)
    matches = isvc.match_items(isvc.split_ingredient_list(
        "Water, preservative (sodium benzoate), Aspartme, mystery gum, Citric acid"), idx)
    ex = calculate_exposure(500, 0.33, 60, 40, True, "label", ingredient_name="Aspartame")
    return rs.build_report("Test Drink", matches, {i.id: i for i in ingredients}, [ex])


def test_report_sections_and_content(report):
    txt = rs.report_to_text(report)
    for heading in ["Product overview", "Ingredient identification results", "Ingredient purposes",
                    "Potential health concerns", "Exposure assessment", "Missing data and uncertainty",
                    "Scientific references", "Disclaimer"]:
        assert heading in txt
    assert "Sodium benzoate" in txt
    assert "https://www.efsa.europa.eu/en/efsajournal/pub/4433" in txt


def test_never_claims_completely_safe(report):
    assert "completely safe" not in rs.report_to_text(report).lower()
    for e in report["ingredients"]:
        # seed records are unverified -> can never be "no specific concern"
        assert e["risk_category"] != rs.RISK_NONE


def test_unmatched_and_pending_are_reported_not_analysed(report):
    assert "mystery gum" in report["unmatched"] and "Water" in report["unmatched"]
    assert [p["input_name"] for p in report["pending_confirmation"]] == ["Aspartme"]
    assert all(e["canonical_name"] != "Aspartame" for e in report["ingredients"])


def test_confirming_a_fuzzy_match_includes_it(ingredients):
    idx = isvc.build_index(ingredients)
    matches = isvc.match_items(isvc.split_ingredient_list("Aspartme"), idx)
    rep = rs.build_report("x", matches, {i.id: i for i in ingredients}, confirmed_inputs={"Aspartme"})
    assert rep["ingredients"][0]["canonical_name"] == "Aspartame"


def test_missing_data_section_flags_gaps(report):
    joined = " ".join(report["missing_data"])
    assert "not found in the ingredient database" in joined.lower()
    assert "unverified" in joined
    assert "Citric acid" in joined  # not-assessed record


def test_pdf_is_valid_and_contains_working_links(report):
    pdf = rs.report_to_pdf(report)
    assert pdf.startswith(b"%PDF")
    assert b"https://www.efsa.europa.eu/en/efsajournal/pub/4433" in pdf  # link annotation


def test_redaction_removes_body_weight(report):
    assert any("Body weight" in a for x in report["exposures"] for a in x["personal_assumptions"])
    red = rs.redact_report(report)
    assert all(x["personal_assumptions"] == [] for x in red["exposures"])
    assert "Body weight" not in rs.report_to_text(red)


def test_urgent_alert_appears_in_report(ingredients):
    from services.safety_service import check_toxic_exposure
    alert = check_toxic_exposure("my child swallowed a lot of this")
    rep = rs.build_report("x", [], {}, safety_alert=alert)
    txt = rs.report_to_text(rep)
    assert rs.RISK_URGENT in txt and "Do not induce vomiting" in txt


# ---- invalid sources / missing evidence ----
@pytest.mark.parametrize("url", ["not a url", "ftp://example.org/x", "http://", "javascript:alert(1)", ""])
def test_invalid_source_urls_rejected(url):
    assert validate_source_url(url)[0] is False
    with pytest.raises(ValidationError):
        EvidenceSource(title="t", publisher="p", url=url, claim_supported="c")


def test_missing_evidence_record_is_flagged():
    ing = Ingredient(canonical_name="Mystery additive")
    assert any("No evidence source" in p for p in source_problems(ing))


def test_reviewed_record_requires_sources_and_date():
    with pytest.raises(ValidationError):
        Ingredient(canonical_name="X", verification_status="reviewed")


def test_effect_must_cite_a_listed_source():
    with pytest.raises(ValidationError):
        Ingredient(canonical_name="X", health_effects=[{"effect": "e", "source_url": "https://a.org/x"}])


def test_retrieval_returns_nothing_when_irrelevant(ingredients):
    assert retrieve_evidence("quantum chromodynamics", ingredients) == []
    assert retrieve_evidence("aspartame phenylketonuria", ingredients)[0]["ingredient"] == "Aspartame"


# ---- AI guardrails ----
def test_ai_output_validation_blocks_invented_numbers_and_links():
    facts = {"x": "ADI 40 mg/kg"}
    assert ai_service.validate_ai_output("The limit is 40 mg/kg.", facts)[0]
    assert not ai_service.validate_ai_output("The limit is 99 mg/kg.", facts)[0]
    assert not ai_service.validate_ai_output("See https://evil.example", facts)[0]
    assert not ai_service.validate_ai_output("This person will die soon", {"a": 1})[0]


def test_ai_disabled_by_default():
    assert ai_service.is_available() is False
    assert not ai_service.explain({"ingredients": [], "unmatched": []}).ok
