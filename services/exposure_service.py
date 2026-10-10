"""Exposure arithmetic. It refuses to compute from missing/invalid inputs and never assumes values."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Optional

INSUFFICIENT_MESSAGE = "Exposure cannot be reliably calculated with the available information."
ADI_NOTE = ("An ADI is a chronic (lifetime) reference value built with safety margins. It is not an acute "
            "poisoning threshold and not a guarantee of individual safety. Exceeding it does not by itself "
            "establish that harm has occurred, and staying below it does not rule out individual sensitivity.")
MIN_BODY_WEIGHT_KG, MAX_BODY_WEIGHT_KG = 2.0, 500.0
MAX_FOOD_KG_PER_DAY = 20.0


@dataclass
class ExposureResult:
    status: str  # 'ok' | 'insufficient'
    message: str = ""
    ingredient_name: str = ""
    daily_intake_mg: Optional[float] = None
    exposure_mg_per_kg_bw: Optional[float] = None
    adi_mg_per_kg_bw: Optional[float] = None
    adi_expressed_as: Optional[str] = None
    adi_source: Optional[str] = None
    percent_of_adi: Optional[float] = None
    assumptions: list[str] = field(default_factory=list)
    personal_assumptions: list[str] = field(default_factory=list)  # removed when history is stored
    missing: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self, include_personal: bool = True) -> dict:
        d = asdict(self)
        if not include_personal:
            d["personal_assumptions"] = []
        return d


def _valid_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def percent_to_mg_per_kg(percent: float) -> float:
    """1 % w/w = 10,000 mg/kg. Only use with a percentage that is explicitly declared AND confirmed."""
    return percent * 10_000.0


def food_amount_kg(serving_g: float, servings_per_day: float) -> float:
    return serving_g * servings_per_day / 1000.0


def calculate_exposure(
    concentration_mg_per_kg: Optional[float],
    food_kg_per_day: Optional[float],
    body_weight_kg: Optional[float],
    adi_mg_per_kg_bw: Optional[float] = None,
    adi_verified: bool = False,
    concentration_source: Optional[str] = None,
    ingredient_name: str = "",
    adi_expressed_as: Optional[str] = None,
    adi_source: Optional[str] = None,
) -> ExposureResult:
    """Compute intake (mg/day), mg/kg bw/day and %ADI when - and only when - inputs are valid and verified."""
    res = ExposureResult(status="insufficient", ingredient_name=ingredient_name)
    res.limitations.append(ADI_NOTE)

    if not _valid_number(concentration_mg_per_kg) or concentration_mg_per_kg < 0:
        res.missing.append("A validated, non-negative concentration of the ingredient in the food (mg/kg food).")
    if not (concentration_source or "").strip():
        res.missing.append("The source of the concentration value (e.g., manufacturer declaration or lab report).")
    if not _valid_number(food_kg_per_day) or food_kg_per_day <= 0 or food_kg_per_day > MAX_FOOD_KG_PER_DAY:
        res.missing.append(f"A valid amount of food eaten per day (> 0 and <= {MAX_FOOD_KG_PER_DAY:g} kg).")
    if not _valid_number(body_weight_kg) or not (MIN_BODY_WEIGHT_KG <= body_weight_kg <= MAX_BODY_WEIGHT_KG):
        res.missing.append(f"A valid body weight ({MIN_BODY_WEIGHT_KG:g}-{MAX_BODY_WEIGHT_KG:g} kg).")
    if res.missing:
        res.message = INSUFFICIENT_MESSAGE
        return res

    intake = concentration_mg_per_kg * food_kg_per_day
    per_kg = intake / body_weight_kg
    res.status = "ok"
    res.daily_intake_mg = intake
    res.exposure_mg_per_kg_bw = per_kg
    res.assumptions.append(
        f"Concentration {concentration_mg_per_kg:g} mg/kg food (source: {concentration_source.strip()}).")
    res.assumptions.append(f"Food consumed: {food_kg_per_day:g} kg/day, eaten every day.")
    res.personal_assumptions.append(f"Body weight: {body_weight_kg:g} kg.")

    if _valid_number(adi_mg_per_kg_bw) and adi_mg_per_kg_bw > 0 and adi_verified:
        res.adi_mg_per_kg_bw = adi_mg_per_kg_bw
        res.adi_expressed_as = adi_expressed_as
        res.adi_source = adi_source
        res.percent_of_adi = per_kg / adi_mg_per_kg_bw * 100.0
        if adi_expressed_as:
            res.limitations.append(
                f"The ADI is expressed as: {adi_expressed_as}. Your concentration must be in the same form "
                "for the comparison to be meaningful.")
        res.message = "Exposure estimated and compared with a reviewed ADI."
    else:
        why = "no ADI is recorded" if not _valid_number(adi_mg_per_kg_bw) else "the ADI record has not been reviewed"
        res.missing.append(f"An applicable, reviewed ADI ({why}); no comparison was made.")
        res.message = "Intake estimated; it cannot be compared with a safety limit."
    res.limitations.append("Only this one food is counted; other dietary sources of the substance are not.")
    return res
