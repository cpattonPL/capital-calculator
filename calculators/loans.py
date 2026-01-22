# calculators/loans.py
"""
Loan calculation module (enum-backed rating buckets).

Replace existing calculators/loans.py with this file.

Features:
- Uses calculators.constants.RatingBucket for all rating-bucket comparisons.
- Backwards-compatible: accepts rating_bucket as RatingBucket or str (will coerce).
- Implements:
  - Basel III Standardized (Corporates + Banks, simplified SCRA mapping)
  - Basel II Standardized (unchanged simplified mapping, ported to enums)
  - IRB Foundation (shared ASRF engine for Corporate/Bank/Sovereign) with PD floors
- Utilities: rate normalization, rating coercion helpers.

Dependencies:
- scipy
- calculators.constants.RatingBucket
"""

import math
from typing import Optional, Union
from scipy.stats import norm

from calculators.constants import RatingBucket

# Basel IRB scaling factor (Basel II IRB default)
SCALING_FACTOR_IRB = 1.06

# PD floors used in current IRB prototype (defaults; jurisdiction may differ)
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
    exposure_type: str,
    rating_bucket: Union[RatingBucket, str, None],
    is_regulatory_retail: bool = False,
    is_prudent_mortgage: bool = False,
    capital_ratio: float = 0.08,
):
    """
    Main entrypoint for loan capital.

    - approach: text label (e.g., "Basel III - Standardized", "Basel II - IRB")
    - rating_bucket: can be RatingBucket enum, or legacy string (will be coerced when possible)
    """
    approach_lower = (approach or "").lower()
    exposure_type_lower = (exposure_type or "").lower()

    # Coerce rating bucket to enum if possible (otherwise None)
    rb_enum = _coerce_rating_bucket(rating_bucket)

    # ========================================================
    # STANDARDIZED APPROACHES
    # ========================================================
    if "standardized" in approach_lower:
        # IMPORTANT: check Basel III before Basel II because "basel iii" contains "basel ii" as substring
        if "basel iii" in approach_lower:
            rw = get_standardized_risk_weight_basel3(
                exposure_type=exposure_type,
                rating_bucket=rb_enum,
            )
            version = "Basel III"

        elif "basel ii" in approach_lower:
            rw = get_standardized_risk_weight_basel2(
                exposure_type=exposure_type,
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
            "exposure_type": exposure_type,
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
        if "corporate" in exposure_type_lower:
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

        if "bank" in exposure_type_lower:
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

        if "sovereign" in exposure_type_lower or "central bank" in exposure_type_lower:
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
    exposure_type: str,
    rating_bucket: Optional[RatingBucket],
) -> float:
    """
    Basel III Standardized Credit Risk Approach (SCRA) — simplified.

    Implemented:
      - Corporate exposures (SCRA mapping)
      - Bank exposures (SCRA mapping)

    Uses RatingBucket enum for comparisons (safer).
    """
    exposure_type = (exposure_type or "").lower()

    # -------------------------
    # Corporate SCRA mapping (simplified)
    # -------------------------
    if "corporate" in exposure_type:
        # Investment-grade set: AAA_AA, A, BBB
        if rating_bucket in {
            RatingBucket.AAA_AA,
            RatingBucket.A,
            RatingBucket.BBB,
        }:
            return 0.75
        if rating_bucket == RatingBucket.BB_B:
            return 1.00
        if rating_bucket == RatingBucket.BELOW_B:
            return 1.50
        # Unrated or unknown maps to 100%
        return 1.00

    # -------------------------
    # Bank SCRA mapping (simplified)
    # -------------------------
    if "bank" in exposure_type:
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

    # Other exposure classes not yet implemented under Basel III standardized:
    return 1.00


# ============================================================
# BASEL II STANDARDIZED (UNCHANGED, but enum-aware)
# ============================================================
def get_standardized_risk_weight_basel2(
    exposure_type: str,
    rating_bucket: Optional[RatingBucket],
    is_regulatory_retail: bool,
    is_prudent_mortgage: bool,
) -> float:
    """
    Simplified Basel II standardized mapping, ported to use enums when available.
    """
    exposure_type = (exposure_type or "").lower()

    # Corporate mapping (Basel II-style)
    if "corporate" in exposure_type:
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
        # unrated fallback:
        return 1.00

    if "retail" in exposure_type:
        return 0.75 if is_regulatory_retail else 1.00

    if "residential" in exposure_type:
        return 0.35 if is_prudent_mortgage else 1.00

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

    - Applies PD floors by asset_class_key
    - Uses normalization helpers for PD/LGD
    - Uses measured maturity (floor 1y cap 5y; fallback 2.5y)
    - Applies IRB scaling factor (1.06)
    """
    pd_in = _normalize_rate(pd, default=0.01)
    lgd_in = _normalize_rate(lgd, default=0.45)

    pd_floor = PD_FLOORS.get(asset_class_key, 0.0003)
    pd_used = max(pd_in, pd_floor)

    if maturity_months and maturity_months > 0:
        M = min(5.0, max(1.0, maturity_months / 12.0))
    else:
        M = 2.5

    exp_term = math.exp(-50 * pd_used)
    denom = 1 - math.exp(-50)
    denom = denom if denom != 0 else 1e-12
    R = 0.12 * (1 - exp_term) / denom + 0.24 * (1 - (1 - exp_term) / denom)

    b = (0.11852 - 0.05478 * math.log(max(pd_used, 1e-9))) ** 2

    term = (
        norm.ppf(pd_used) / math.sqrt(1 - R)
        + math.sqrt(R / (1 - R)) * norm.ppf(0.999)
    )

    K = lgd_in * norm.cdf(term) - pd_used * lgd_in
    maturity_adj = (1 + (M - 2.5) * b) / (1 - 1.5 * b)
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

    Rules:
      - if x is None or <= 0: return default
      - if x > 1: treat as percent and divide by 100
      - else: treat as decimal
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
    Coerce a rating-bucket input (enum or legacy string) to RatingBucket enum.

    Accepts:
      - RatingBucket members (returned unchanged)
      - Human-readable labels (e.g. "AAA to AA-") -> coerced to enum
      - Enum-like underscores (e.g. "AAA_AA") -> coerced
      - None -> returns None

    If no match is found, returns None (caller will use unrated fallback).
    """
    if rb is None:
        return None
    if isinstance(rb, RatingBucket):
        return rb
    try:
        # if user supplied the enum name (e.g., "AAA_AA")
        if isinstance(rb, str):
            rb_str = rb.strip()
            # direct enum name match
            try:
                return RatingBucket(rb_str)
            except ValueError:
                pass
            # match common UI labels
            label_map = {
                "AAA to AA-": RatingBucket.AAA_AA,
                "A+ to A-": RatingBucket.A,
                "BBB+ to BBB-": RatingBucket.BBB,
                "BB+ to B-": RatingBucket.BB_B,
                "Below B-": RatingBucket.BELOW_B,
                "Unrated": RatingBucket.UNRATED,
                "unrated": RatingBucket.UNRATED,
            }
            # case-insensitive match by normalized label
            for k, v in label_map.items():
                if rb_str.lower() == k.lower():
                    return v
    except Exception:
        pass
    return None
