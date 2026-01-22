# calculators/loans.py
"""
Loan calculation module (enum-backed exposure types + rating buckets).

Paste this entire file over calculators/loans.py.

Features:
- Uses calculators.constants.ExposureType and RatingBucket in calculations.
- Backwards-compatible: accepts exposure_type and rating_bucket as enums OR legacy strings.
- Implements:
  - Basel III Standardized (Corporates + Banks, simplified SCRA mapping)
  - Basel II Standardized (simplified mapping)
  - IRB Foundation (Basel II F-IRB prototype) for Corporate/Bank/Sovereign
- Utilities: normalize rates, coerce enums from legacy strings.

Dependencies:
- scipy
- calculators.constants (ExposureType, RatingBucket)
"""

import math
from typing import Optional, Union

from scipy.stats import norm

from calculators.constants import ExposureType, RatingBucket

# Basel II IRB scaling factor (kept as-is for current prototype)
SCALING_FACTOR_IRB = 1.06

# PD floors used in the current IRB prototype (kept as-is for now)
PD_FLOORS = {
    "corporate": 0.0003,   # 0.03%
    "bank": 0.0005,        # 0.05%
    "sovereign": 0.0005,   # 0.05%
}


# ============================================================
# PUBLIC ENTRYPOINT
# ============================================================
def calculate_loan_capital(
    approach: str,
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
    Main entrypoint for loan capital.

    exposure_type: ExposureType enum (preferred) or legacy string (coerced)
    rating_bucket: RatingBucket enum (preferred) or legacy string (coerced)
    """
    approach_lower = (approach or "").lower()

    et_enum = _coerce_exposure_type(exposure_type)  # may be None
    rb_enum = _coerce_rating_bucket(rating_bucket)  # may be None

    # ========================================================
    # STANDARDIZED APPROACHES
    # ========================================================
    if "standardized" in approach_lower:
        # IMPORTANT: check Basel III before Basel II because "basel iii" contains "basel ii" as substring
        if "basel iii" in approach_lower:
            rw = get_standardized_risk_weight_basel3(
                exposure_type=et_enum,
                rating_bucket=rb_enum,
            )
            version = "Basel III"
        elif "basel ii" in approach_lower:
            rw = get_standardized_risk_weight_basel2(
                exposure_type=et_enum,
                rating_bucket=rb_enum,
                is_regulatory_retail=is_regulatory_retail,
                is_prudent_mortgage=is_prudent_mortgage,
            )
            version = "Basel II"
        else:
            rw = 1.0
            version = "Unknown"

        rwa = ead * rw
        capital_required = rwa * capital_ratio

        return {
            "approach": approach,
            "version": version,
            "exposure_type_enum": (et_enum.name if et_enum else None),
            "rating_bucket_enum": (rb_enum.name if rb_enum else None),
            "risk_weight": rw,
            "risk_weight_pct": f"{rw * 100:.2f}%",
            "EAD": ead,
            "RWA": rwa,
            "capital_ratio": capital_ratio,
            "capital_required": capital_required,
            "notes": "Standardized approach calculation (simplified).",
        }

    # ========================================================
    # IRB APPROACHES (Basel II F-IRB prototype)
    # ========================================================
    if "irb" in approach_lower:
        # route by exposure type enum
        if et_enum == ExposureType.CORPORATE:
            return _calculate_irb_foundation_asrf(
                asset_class_key="corporate",
                asset_class_label="Foundation IRB - Corporate",
                ead=ead,
                pd=pd,
                lgd=lgd,
                maturity_months=maturity_months,
                capital_ratio=capital_ratio,
                approach=approach,
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
                approach=approach,
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
                approach=approach,
            )

        # Non-covered IRB asset classes: keep stub until implemented
        return _calculate_irb_stub(
            approach=approach,
            ead=ead,
            maturity_months=maturity_months,
            pd=pd,
            lgd=lgd,
            capital_ratio=capital_ratio,
        )

    return {"error": f"Unknown approach: {approach}"}


# ============================================================
# BASEL III STANDARDIZED — CORPORATES & BANKS (SCRA simplified)
# ============================================================
def get_standardized_risk_weight_basel3(
    exposure_type: Optional[ExposureType],
    rating_bucket: Optional[RatingBucket],
) -> float:
    """
    Basel III Standardized Credit Risk Approach (SCRA) — simplified.

    Implemented:
      - Corporate exposures (SCRA mapping)
      - Bank exposures (SCRA mapping)
    """
    # Corporate SCRA
    if exposure_type == ExposureType.CORPORATE:
        if rating_bucket in {RatingBucket.AAA_AA, RatingBucket.A, RatingBucket.BBB}:
            return 0.75
        if rating_bucket == RatingBucket.BB_B:
            return 1.00
        if rating_bucket == RatingBucket.BELOW_B:
            return 1.50
        return 1.00  # unrated/unknown fallback

    # Bank SCRA (simplified)
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
        return 1.00  # unrated/unknown fallback

    # Not implemented yet for other exposure types
    return 1.00


# ============================================================
# BASEL II STANDARDIZED (simplified, enum-aware)
# ============================================================
def get_standardized_risk_weight_basel2(
    exposure_type: Optional[ExposureType],
    rating_bucket: Optional[RatingBucket],
    is_regulatory_retail: bool,
    is_prudent_mortgage: bool,
) -> float:
    """
    Simplified Basel II standardized mapping, enum-aware.
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

    # CRE and other exposure types remain simplified as 100% for now
    return 1.00


# ============================================================
# IRB FOUNDATION — SHARED ASRF ENGINE
# ============================================================
def _calculate_irb_foundation_asrf(
    asset_class_key: str,
    asset_class_label: str,
    ead: float,
    pd: float,
    lgd: float,
    maturity_months: int,
    capital_ratio: float,
    approach: str,
):
    """
    Shared ASRF implementation for Foundation IRB (Corporate/Bank/Sovereign).

    - Applies PD floors by asset class key
    - Normalizes PD/LGD (accepts decimals or percentages)
    - Uses measured maturity with floor/cap (1–5 years; fallback 2.5y)
    - Applies IRB scaling factor (1.06)
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
        "approach": approach,
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


# ============================================================
# IRB FALLBACK STUB
# ============================================================
def _calculate_irb_stub(
    approach: str,
    ead: float,
    maturity_months: int,
    pd: float,
    lgd: float,
    capital_ratio: float,
):
    return {
        "approach": approach,
        "notes": "IRB stub — asset class not yet implemented.",
    }


# ============================================================
# UTILITIES
# ============================================================
def _normalize_rate(x, default: float) -> float:
    """
    Normalize a rate possibly supplied as:
      - decimal (0.01)
      - percent (1 meaning 1%, or 45 meaning 45%)
    """
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
    """
    Coerce RatingBucket enum from enum or legacy strings.
    """
    if rb is None:
        return None
    if isinstance(rb, RatingBucket):
        return rb

    if isinstance(rb, str):
        s = rb.strip()

        # allow enum value strings (e.g., "AAA_AA") or labels
        value_map = {e.value: e for e in RatingBucket}
        label_map = {e.label.lower(): e for e in RatingBucket}

        if s in value_map:
            return value_map[s]
        if s.lower() in label_map:
            return label_map[s.lower()]

        # common legacy variants
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
    """
    Coerce ExposureType enum from enum or legacy strings.
    """
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

        # common legacy variants
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
