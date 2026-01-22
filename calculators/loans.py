# calculators/loans.py
"""
Loan calculation module (Approach enum + ExposureType + RatingBucket).

Notes:
- This file expects calculators.constants.Approach, ExposureType, RatingBucket to exist.
- Backwards compatibility: functions accept Approach or legacy string (coercion applied).
- IRB implemented remains Basel II Foundation IRB (we'll add Basel III IRB later).
"""

import math
from typing import Optional, Union

from scipy.stats import norm

from calculators.constants import Approach, ExposureType, RatingBucket

# Basel II IRB scaling factor (kept for current IRB prototype)
SCALING_FACTOR_IRB = 1.06

# PD floors used in the current IRB prototype
PD_FLOORS = {
    "corporate": 0.0003,   # 0.03%
    "bank": 0.0005,        # 0.05%
    "sovereign": 0.0005,   # 0.05%
}


# ---------------------------
# Public entrypoint
# ---------------------------
def calculate_loan_capital(
    approach: Union[Approach, str],
    ead: float,
    balance: float,
    maturity_months: int,
    amortization_months: int,
    interest_rate: float,
    pd: float,
    lgd: float,
    exposure_type: Union[ExposureType, str, None],
    rating_bucket: Union[RatingBucket, str, None],
    is_regulatory_retail: bool = False,
    is_prudent_mortgage: bool = False,
    capital_ratio: float = 0.08,
):
    """
    Main entrypoint.

    approach: Approach enum or legacy string (coerced)
    exposure_type: ExposureType enum or legacy string (coerced)
    rating_bucket: RatingBucket enum or legacy string (coerced)
    """
    # Coerce approach/exposure/rating
    approach_enum = _coerce_approach(approach)
    et_enum = _coerce_exposure_type(exposure_type)
    rb_enum = _coerce_rating_bucket(rating_bucket)

    # if coercion failed, fall back to previous string parsing behaviour conservatively
    if approach_enum is None:
        # try naive string parsing fallback
        approach_str = (approach or "").lower()
        if "basel iii" in approach_str and "standard" in approach_str:
            approach_enum = Approach.BASEL_III_STANDARDIZED
        elif "basel iii" in approach_str and "irb" in approach_str:
            approach_enum = Approach.BASEL_III_IRB
        elif "irb" in approach_str:
            approach_enum = Approach.BASEL_II_IRB
        elif "basel ii" in approach_str and "standard" in approach_str:
            approach_enum = Approach.BASEL_II_STANDARDIZED
        else:
            approach_enum = Approach.BASEL_II_STANDARDIZED  # safe default

    # Route by structured approach
    if approach_enum.method == "standardized":
        # route to Basel III or Basel II standardized depending on regime
        if approach_enum.regime == "basel3":
            rw = get_standardized_risk_weight_basel3(
                exposure_type=et_enum,
                rating_bucket=rb_enum,
            )
            version = "Basel III"
        else:
            rw = get_standardized_risk_weight_basel2(
                exposure_type=et_enum,
                rating_bucket=rb_enum,
                is_regulatory_retail=is_regulatory_retail,
                is_prudent_mortgage=is_prudent_mortgage,
            )
            version = "Basel II"

        rwa = ead * rw
        capital_required = rwa * capital_ratio

        return {
            "approach_enum": approach_enum.name,
            "approach_label": approach_enum.label,
            "version": version,
            "exposure_type_enum": (et_enum.name if et_enum else None),
            "rating_bucket_enum": (rb_enum.name if rb_enum else None),
            "risk_weight": rw,
            "risk_weight_pct": f"{rw * 100:.2f}%",
            "EAD": ead,
            "RWA": rwa,
            "capital_ratio": capital_ratio,
            "capital_required": capital_required,
        }

    # IRB route (method == 'irb')
    if approach_enum.method == "irb":
        # currently our IRB implementation is F-IRB (Basel II style); keep routing by exposure type
        if et_enum == ExposureType.CORPORATE:
            return _calculate_irb_foundation_asrf(
                asset_class_key="corporate",
                asset_class_label="Foundation IRB - Corporate",
                ead=ead,
                pd=pd,
                lgd=lgd,
                maturity_months=maturity_months,
                capital_ratio=capital_ratio,
                approach_enum=approach_enum,
            )

        if et_enum == ExposureType.BANK:
            return _calculate_irb_foundation_asrf(
                asset_class_key="bank",
                asset_class_label="Foundation IRB - Bank",
                ead=ead,
                pd=pd,
                lgd=lgd,
                maturity_months=maturity_months,
                capital_ratio=capital_ratio,
                approach_enum=approach_enum,
            )

        if et_enum == ExposureType.SOVEREIGN_CENTRAL_BANK:
            return _calculate_irb_foundation_asrf(
                asset_class_key="sovereign",
                asset_class_label="Foundation IRB - Sovereign/Central Bank",
                ead=ead,
                pd=pd,
                lgd=lgd,
                maturity_months=maturity_months,
                capital_ratio=capital_ratio,
                approach_enum=approach_enum,
            )

        return _calculate_irb_stub(
            approach_enum=approach_enum,
            ead=ead,
            maturity_months=maturity_months,
            pd=pd,
            lgd=lgd,
            capital_ratio=capital_ratio,
        )

    return {"error": "Unsupported approach/method"}


# ---------------------------
# Standardized helpers
# ---------------------------
def get_standardized_risk_weight_basel3(
    exposure_type: Optional[ExposureType],
    rating_bucket: Optional[RatingBucket],
) -> float:
    """
    Basel III Standardized (SCRA) simplified: Corporates & Banks implemented.
    """
    if exposure_type == ExposureType.CORPORATE:
        if rating_bucket in {RatingBucket.AAA_AA, RatingBucket.A, RatingBucket.BBB}:
            return 0.75
        if rating_bucket == RatingBucket.BB_B:
            return 1.00
        if rating_bucket == RatingBucket.BELOW_B:
            return 1.50
        return 1.00

    if exposure_type == ExposureType.BANK:
        if rating_bucket == RatingBucket.AAA_AA:
            return 0.20
        if rating_bucket == RatingBucket.A:
            return 0.50
        if rating_bucket == RatingBucket.BBB:
            return 0.75
        if rating_bucket == RatingBucket.BB_B:
            return 1.00
        if rating_bucket == RatingBucket.BELOW_B:
            return 1.50
        return 1.00

    # Not implemented: residential, CRE, retail under Basel III standardized
    return 1.00


def get_standardized_risk_weight_basel2(
    exposure_type: Optional[ExposureType],
    rating_bucket: Optional[RatingBucket],
    is_regulatory_retail: bool,
    is_prudent_mortgage: bool,
) -> float:
    """
    Basel II simplified mappings (enum-aware).
    """
    if exposure_type == ExposureType.CORPORATE:
        if rating_bucket == RatingBucket.AAA_AA:
            return 0.20
        if rating_bucket == RatingBucket.A:
            return 0.50
        if rating_bucket == RatingBucket.BBB:
            return 1.00
        if rating_bucket == RatingBucket.BB_B:
            return 1.00
        if rating_bucket == RatingBucket.BELOW_B:
            return 1.50
        return 1.00

    if exposure_type == ExposureType.RETAIL:
        return 0.75 if is_regulatory_retail else 1.00

    if exposure_type == ExposureType.RESIDENTIAL_MORTGAGE:
        return 0.35 if is_prudent_mortgage else 1.00

    return 1.00


# ---------------------------
# IRB Foundation (shared ASRF)
# ---------------------------
def _calculate_irb_foundation_asrf(
    asset_class_key: str,
    asset_class_label: str,
    ead: float,
    pd: float,
    lgd: float,
    maturity_months: int,
    capital_ratio: float,
    approach_enum: Approach,
):
    """
    Shared IRB ASRF. The approach_enum is passed for traceability, although in this
    prototype the math remains the same (Basel II F-IRB).
    """
    pd_in = _normalize_rate(pd, default=0.01)
    lgd_in = _normalize_rate(lgd, default=0.45)

    pd_floor = PD_FLOORS.get(asset_class_key, 0.0003)
    pd_used = max(pd_in, pd_floor)

    if maturity_months and maturity_months > 0:
        M = min(5.0, max(1.0, float(maturity_months) / 12.0))
    else:
        M = 2.5

    exp_term = math.exp(-50.0 * pd_used)
    denom = 1.0 - math.exp(-50.0)
    denom = denom if denom != 0 else 1e-12
    R = 0.12 * (1.0 - exp_term) / denom + 0.24 * (1.0 - (1.0 - exp_term) / denom)

    b = (0.11852 - 0.05478 * math.log(max(pd_used, 1e-9))) ** 2

    term = (
        norm.ppf(pd_used) / math.sqrt(1.0 - R)
        + math.sqrt(R / (1.0 - R)) * norm.ppf(0.999)
    )

    K = lgd_in * norm.cdf(term) - pd_used * lgd_in
    maturity_adj = (1.0 + (M - 2.5) * b) / (1.0 - 1.5 * b)
    K_adj = K * maturity_adj

    rwa = 12.5 * SCALING_FACTOR_IRB * K_adj * ead
    capital_required = rwa * capital_ratio

    return {
        "approach_enum": approach_enum.name,
        "approach_label": approach_enum.label,
        "irb_treatment": asset_class_label,
        "pd_used": pd_used,
        "lgd_used": lgd_in,
        "maturity_years": M,
        "supervisory_correlation_R": R,
        "K_unadjusted": K,
        "maturity_adjustment_factor": maturity_adj,
        "K_adjusted": K_adj,
        "irb_scaling_factor": SCALING_FACTOR_IRB,
        "EAD": ead,
        "RWA": rwa,
        "effective_risk_weight_pct": f"{(rwa / ead) * 100:.2f}%" if ead and ead > 0 else None,
        "capital_required": capital_required,
    }


def _calculate_irb_stub(
    approach_enum: Approach,
    ead: float,
    maturity_months: int,
    pd: float,
    lgd: float,
    capital_ratio: float,
):
    return {
        "approach_enum": approach_enum.name,
        "notes": "IRB stub — asset class not yet implemented.",
    }


# ---------------------------
# Utilities: normalization & coercion
# ---------------------------
def _normalize_rate(x, default: float) -> float:
    if x is None:
        return float(default)
    try:
        val = float(x)
    except (TypeError, ValueError):
        return float(default)
    if val <= 0.0:
        return float(default)
    if val > 1.0:
        return val / 100.0
    return val


def _coerce_rating_bucket(rb: Union[RatingBucket, str, None]) -> Optional[RatingBucket]:
    if rb is None:
        return None
    if isinstance(rb, RatingBucket):
        return rb
    if isinstance(rb, str):
        s = rb.strip()
        value_map = {e.value: e for e in RatingBucket}
        label_map = {e.label.lower(): e for e in RatingBucket}
        if s in value_map:
            return value_map[s]
        if s.lower() in label_map:
            return label_map[s.lower()]
        legacy_map = {
            "aaa to aa-": RatingBucket.AAA_AA,
            "a+ to a-": RatingBucket.A,
            "bbb+ to bbb-": RatingBucket.BBB,
            "bb+ to b-": RatingBucket.BB_B,
            "below b-": RatingBucket.BELOW_B,
            "unrated": RatingBucket.UNRATED,
        }
        if s.lower() in legacy_map:
            return legacy_map[s.lower()]
    return None


def _coerce_exposure_type(et: Union[ExposureType, str, None]) -> Optional[ExposureType]:
    if et is None:
        return None
    if isinstance(et, ExposureType):
        return et
    if isinstance(et, str):
        s = et.strip()
        value_map = {e.value: e for e in ExposureType}
        label_map = {e.label.lower(): e for e in ExposureType}
        if s in value_map:
            return value_map[s]
        if s.lower() in label_map:
            return label_map[s.lower()]
        legacy_map = {
            "corporate": ExposureType.CORPORATE,
            "retail": ExposureType.RETAIL,
            "residential mortgage": ExposureType.RESIDENTIAL_MORTGAGE,
            "commercial real estate": ExposureType.COMMERCIAL_REAL_ESTATE,
            "sovereign / central bank": ExposureType.SOVEREIGN_CENTRAL_BANK,
            "sovereign/central bank": ExposureType.SOVEREIGN_CENTRAL_BANK,
            "sovereign": ExposureType.SOVEREIGN_CENTRAL_BANK,
            "central bank": ExposureType.SOVEREIGN_CENTRAL_BANK,
            "bank": ExposureType.BANK,
            "other": ExposureType.OTHER,
        }
        if s.lower() in legacy_map:
            return legacy_map[s.lower()]
    return None


def _coerce_approach(a: Union[Approach, str, None]) -> Optional[Approach]:
    """
    Coerce approaches from enum or legacy label/string.

    Acceptable:
      - Approach enum (returned unchanged)
      - Enum value string (e.g., "BASEL_III_STANDARDIZED")
      - Label (e.g., "Basel III - Standardized")
      - Legacy strings containing "basel" / "irb" (best-effort)
    """
    if a is None:
        return None
    if isinstance(a, Approach):
        return a
    if isinstance(a, str):
        s = a.strip()
        # direct enum match by value
        value_map = {e.value: e for e in Approach}
        if s in value_map:
            return value_map[s]
        # label match
        label_map = {e.label.lower(): e for e in Approach}
        if s.lower() in label_map:
            return label_map[s.lower()]
        # best-effort parsing
        s_low = s.lower()
        if "basel iii" in s_low and "standard" in s_low:
            return Approach.BASEL_III_STANDARDIZED
        if "basel iii" in s_low and "irb" in s_low:
            return Approach.BASEL_III_IRB
        if "basel ii" in s_low and "standard" in s_low:
            return Approach.BASEL_II_STANDARDIZED
        if "irb" in s_low:
            return Approach.BASEL_II_IRB
    return None
