import math

import pytest

from services.exposure_service import (INSUFFICIENT_MESSAGE, calculate_exposure, food_amount_kg,
                                       percent_to_mg_per_kg)


def ok(**kw):
    base = dict(concentration_mg_per_kg=500, food_kg_per_day=0.33, body_weight_kg=60,
                adi_mg_per_kg_bw=40, adi_verified=True, concentration_source="manufacturer declaration")
    base.update(kw)
    return calculate_exposure(**base)


def test_known_values():
    r = ok()
    assert r.status == "ok"
    assert r.daily_intake_mg == pytest.approx(165.0)          # 500 mg/kg * 0.33 kg
    assert r.exposure_mg_per_kg_bw == pytest.approx(2.75)     # 165 / 60
    assert r.percent_of_adi == pytest.approx(6.875)           # 2.75 / 40 * 100


def test_missing_concentration():
    r = ok(concentration_mg_per_kg=None)
    assert r.status == "insufficient" and r.message == INSUFFICIENT_MESSAGE
    assert r.daily_intake_mg is None and r.percent_of_adi is None


def test_missing_concentration_source():
    assert ok(concentration_source="").status == "insufficient"


@pytest.mark.parametrize("bw", [None, 0, -5, 1, 1000, float("nan"), float("inf"), "70"])
def test_invalid_body_weight(bw):
    r = ok(body_weight_kg=bw)
    assert r.status == "insufficient" and r.message == INSUFFICIENT_MESSAGE


@pytest.mark.parametrize("food", [None, 0, -1, 50, float("nan")])
def test_invalid_food_amount(food):
    assert ok(food_kg_per_day=food).status == "insufficient"


def test_missing_adi_still_gives_intake_but_no_comparison():
    r = ok(adi_mg_per_kg_bw=None, adi_verified=False)
    assert r.status == "ok" and r.percent_of_adi is None
    assert any("ADI" in m for m in r.missing)


def test_unreviewed_adi_is_not_used():
    r = ok(adi_verified=False)
    assert r.percent_of_adi is None and any("not been reviewed" in m for m in r.missing)


def test_exceeding_adi_is_reported_without_claiming_harm():
    r = ok(concentration_mg_per_kg=50_000)
    assert r.percent_of_adi > 100
    assert any("does not by itself establish that harm" in l for l in r.limitations)


def test_zero_concentration_is_valid():
    r = ok(concentration_mg_per_kg=0)
    assert r.status == "ok" and r.daily_intake_mg == 0


def test_personal_data_redaction():
    r = ok()
    assert any("Body weight" in a for a in r.to_dict()["personal_assumptions"])
    assert r.to_dict(include_personal=False)["personal_assumptions"] == []


def test_helpers():
    assert percent_to_mg_per_kg(0.01) == pytest.approx(100.0)
    assert food_amount_kg(330, 1) == pytest.approx(0.33)
    assert math.isclose(food_amount_kg(30, 2), 0.06)
