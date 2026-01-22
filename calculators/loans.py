# calculators/loans.py
"""
Loan calculation module.

Contains:
- Standardized approach (Basel II + Basel III) — simplified mappings
- IRB Foundation (Corporate, Bank, Sovereign/Central Bank) — ASRF implementation
- IRB fallback stub for other exposure types (until implemented)

Important IRB mechanics included:
- ASRF / Vasicek structure with 99.9% quantile
- Maturity adjustment
- IRB scaling factor 1.06
- PD floors by asset class (Basel III-style defaults)

Input normalization:
- PD and LGD can be provided as decimals (0.01) or percentages (1 = 1%).
  We normalize: values > 1 are interpreted as percentages and divided by 100.

Dependencies:
- scipy (for norm.cdf / norm.ppf)
"""

import math
from scipy.stats import norm

# Basel IRB scaling factor
SCALING_FACTOR_IRB = 1.06

# Basel III-style PD floors (defaults; jurisdiction may vary)
PD_FLOORS = {
    "corporate": 0.0003,   # 0.03%
    "bank": 0.0005,        # 0.05%
    "sovereign": 0.0005,   # 0.05%
}


# ---------------------------
# Public entrypoint
# ---------------------------
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
    rating_bucket: str,
    is_regulatory_retail: bool = False,
    is_prudent_mortgage: bool = False,
    capital_ratio: float = 0.08,
):
    """
    Main entrypoint for loan capital.

    Standardized:
      - Uses simplified RW mappings by exposure_type and rating_bucket.

    IRB:
      - Implements Foundation IRB for Corporate, Bank, Sovereign/Central Bank using ASRF.
      - Applies PD floors by asset class (defaults in PD_FLOORS).
      - Other exposure types fall back to a stub (until implemented).
    """
    approach_lower = (approach or "").lower()

    # =========================
    # STANDARDIZED APPROACHES
    # =========================
    if "standardized" in approach_lower or "standardised" in approach_lower:
        if "basel ii" in approach_lower:
            version = "Basel II"
            rw = get_standardized_risk_weight_basel2(
                exposure_type=exposure_type,
                rating_bucket=rating_bucket,
                is_regulatory_retail=is_regulatory_retail,
                is_prudent_mortgage=is_prudent_mortgage,
            )
        elif "basel iii" in approach_lower:
            version = "Basel III"
            rw = get_standardized_risk_weight_basel3(
                exposure_type=exposure_type,
                rating_bucket=rating_bucket,
                is_regulatory_retail=is_regulatory_retail,
                is_prudent_mortgage=is_prudent_mortgage,
            )
        else:
            version = "Unknown"
            rw = 1.0

        rwa = ead * rw
        capital = rwa * capital_ratio

        return {
            "approach": approach,
            "version": version,
            "exposure_type": exposure_type,
            "rating_bucket": rating_bucket,
            "risk_weight": rw,
            "risk_weight_pct": f"{rw * 100:.2f}%",
            "EAD": ead,
            "RWA": rwa,
            "capital_ratio": capital_ratio,
            "capital_required": capital,
            "notes": (
                "Standardized approach using simplified risk-weight mapping. "
                "Refine with full Basel tables for production use."
            ),
        }

    # =========================
    # IRB APPROACHES
    # =========================
    if "irb" in approach_lower:
        et = (exposure_type or "").lower()

        if "corporate" in et:
            return _calculate_irb_foundation_corporate(
                ead=ead,
                pd=pd,
                lgd=lgd,
                maturity_months=maturity_months,
                capital_ratio=capital_ratio,
                approach=approach,
            )

        if "bank" in et:
            return _calculate_irb_foundation_bank(
                ead=ead,
                pd=pd,
                lgd=lgd,
                maturity_months=maturity_months,
                capital_ratio=capital_ratio,
                approach=approach,
            )

        if "sovereign" in et or "central bank" in et:
            return _calculate_irb_foundation_sovereign(
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


# -------------------------------------------------------------------
# IRB Foundation wrappers (Corporate/Bank/Sovereign use shared helper)
# -------------------------------------------------------------------
def _calculate_irb_foundation_corporate(
    ead: float,
    pd: float,
    lgd: float,
    maturity_months: int,
    capital_ratio: float,
    approach: str,
):
    return _calculate_irb_foundation_asrf(
        asset_class_key="corporate",
        asset_class_label="Foundation - Corporate",
        ead=ead,
        pd=pd,
        lgd=lgd,
        maturity_months=maturity_months,
        capital_ratio=capital_ratio,
        approach=approach,
    )


def _calculate_irb_foundation_bank(
    ead: float,
    pd: float,
    lgd: float,
    maturity_months: int,
    capital_ratio: float,
    approach: str,
):
    return _calculate_irb_foundation_asrf(
        asset_class_key="bank",
        asset_class_label="Foundation - Bank",
        ead=ead,
        pd=pd,
        lgd=lgd,
        maturity_months=maturity_months,
        capital_ratio=capital_ratio,
        approach=approach,
    )


def _calculate_irb_foundation_sovereign(
    ead: float,
    pd: float,
    lgd: float,
    maturity_months: int,
    capital_ratio: float,
    approach: str,
):
    return _calculate_irb_foundation_asrf(
        asset_class_key="sovereign",
        asset_class_label="Foundation - Sovereign/Central Bank",
        ead=ead,
        pd=pd,
        lgd=lgd,
        maturity_months=maturity_months,
        capital_ratio=capital_ratio,
        approach=approach,
    )


# -------------------------------------------------------------------
# Shared IRB ASRF implementation + PD floors
# -------------------------------------------------------------------
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

    Adds:
      - PD floor by asset class (PD_FLOORS) applied after input normalization.
    """
    # ---- Normalize inputs (support decimal or % entry)
    pd_in = _normalize_rate(pd, default=0.01)   # default PD 1% if missing
    lgd_in = _normalize_rate(lgd, default=0.45) # supervisory LGD default 45% if missing

    # ---- Apply PD floor by asset class (Basel III-style defaults)
    pd_floor = PD_FLOORS.get(asset_class_key, 0.0003)  # fallback to corporate floor if unknown
    pd_used = max(pd_in, pd_floor)

    # ---- Effective maturity M based on loan maturity term (years), floor 1, cap 5; fallback 2.5
    if maturity_months and maturity_months > 0:
        M_raw = float(maturity_months) / 12.0
        M = min(5.0, max(1.0, M_raw))
    else:
        M_raw = None
        M = 2.5

    # ---- Supervisory correlation function R(PD) for corporate/bank/sovereign style exposures
    # Note: A production-grade engine may vary correlation or impose floors by asset class;
    # here we use the common Basel II functional form and differentiate primarily via PD floors.
    exp_term = math.exp(-50.0 * pd_used)
    denom = 1.0 - math.exp(-50.0)
    denom = denom if denom != 0 else 1e-12
    R = 0.12 * (1.0 - exp_term) / denom + 0.24 * (1.0 - (1.0 - exp_term) / denom)

    # ---- b(PD) maturity adjustment parameter
    pd_for_b = max(pd_used, 1e-9)
    b = (0.11852 - 0.05478 * math.log(pd_for_b)) ** 2

    # ---- ASRF term at 99.9%
    inv_norm_pd = norm.ppf(pd_used)
    inv_norm_999 = norm.ppf(0.999)
    term = (inv_norm_pd / math.sqrt(1.0 - R)) + (math.sqrt(R / (1.0 - R)) * inv_norm_999)

    # ---- K (unadjusted)
    K_unadj = lgd_in * norm.cdf(term) - pd_used * lgd_in

    # ---- Maturity adjustment
    denom_ma = (1.0 - 1.5 * b)
    denom_ma = denom_ma if denom_ma > 0 else 1e-9
    maturity_adjustment = (1.0 + (M - 2.5) * b) / denom_ma
    K_adj = K_unadj * maturity_adjustment

    # ---- RWA conversion with scaling factor
    rwa = 12.5 * SCALING_FACTOR_IRB * K_adj * ead
    capital_required = rwa * capital_ratio

    # ---- Derived effective risk weight: RWA / EAD
    rw_effective = (rwa / ead) if ead and ead > 0 else None

    return {
        "approach": approach,
        "irb_treatment": asset_class_label,
        "pd_input_normalized": pd_in,
        "pd_floor_applied": pd_floor,
        "pd_used": pd_used,
        "lgd_input_normalized": lgd_in,
        "lgd_used": lgd_in,
        "maturity_years": M,
        "maturity_years_raw": M_raw,
        "supervisory_correlation_R": R,
        "b_pd": b,
        "K_unadjusted": K_unadj,
        "maturity_adjustment_factor": maturity_adjustment,
        "K_adjusted": K_adj,
        "irb_scaling_factor": SCALING_FACTOR_IRB,
        "EAD": ead,
        "RWA": rwa,
        "effective_risk_weight_decimal": rw_effective,
        "effective_risk_weight_pct": (f"{rw_effective * 100:.2f}%" if rw_effective is not None else None),
        "capital_ratio": capital_ratio,
        "capital_required": capital_required,
        "notes": (
            "Foundation IRB ASRF implementation for corporate/bank/sovereign-style exposures. "
            "Includes maturity adjustment, IRB scaling factor 1.06, and PD floors by asset class."
        ),
    }


def _normalize_rate(x, default: float) -> float:
    """
    Normalize a rate that might be supplied as:
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


# -------------------------------------------------------------------
# IRB fallback stub for non-covered IRB asset classes
# -------------------------------------------------------------------
def _calculate_irb_stub(
    approach: str,
    ead: float,
    maturity_months: int,
    pd: float,
    lgd: float,
    capital_ratio: float,
):
    """
    Placeholder for IRB asset classes not yet implemented.
    """
    pd_used = _normalize_rate(pd, default=0.01)
    lgd_used = _normalize_rate(lgd, default=0.45)
    m = float(maturity_months) if (maturity_months and maturity_months > 0) else 36.0

    # Arbitrary placeholder, bounded
    base_rw = pd_used * (lgd_used * 12.0) + (m / 120.0)
    risk_weight = min(5.0, max(0.5, base_rw))

    rwa = ead * risk_weight
    capital_required = rwa * capital_ratio

    return {
        "approach": approach,
        "irb_treatment": "Stub (Non-covered IRB asset class)",
        "pd_used": pd_used,
        "lgd_used": lgd_used,
        "risk_weight": risk_weight,
        "risk_weight_pct": f"{risk_weight * 100:.2f}%",
        "EAD": ead,
        "RWA": rwa,
        "capital_ratio": capital_ratio,
        "capital_required": capital_required,
        "notes": (
            "IRB calculation is a placeholder for non-corporate/bank/sovereign exposures. "
            "Implement the official IRB risk-weight functions for each asset class."
        ),
    }


# -------------------------------------------------------------------
# Basel II Standardized — simplified risk weights
# -------------------------------------------------------------------
def get_standardized_risk_weight_basel2(
    exposure_type: str,
    rating_bucket: str,
    is_regulatory_retail: bool,
    is_prudent_mortgage: bool,
) -> float:
    """
    Simplified Basel II standardized risk weights (illustrative).
    Returns a decimal risk weight (e.g., 1.0 = 100%).
    """
    exposure_type = (exposure_type or "").lower()
    rating_bucket = (rating_bucket or "unrated").lower()

    corporate_rw_by_rating = {
        "aaa to aa-": 0.20,
        "a+ to a-": 0.50,
        "bbb+ to bbb-": 1.00,
        "bb+ to b-": 1.00,
        "below b-": 1.50,
        "unrated": 1.00,
    }

    sovereign_rw_by_rating = {
        "aaa to aa-": 0.00,
        "a+ to a-": 0.20,
        "bbb+ to bbb-": 0.50,
        "bb+ to b-": 1.00,
        "below b-": 1.50,
        "unrated": 1.00,
    }

    bank_rw_by_rating = {
        "aaa to aa-": 0.20,
        "a+ to a-": 0.50,
        "bbb+ to bbb-": 1.00,
        "bb+ to b-": 1.00,
        "below b-": 1.50,
        "unrated": 1.00,
    }

    if "sovereign" in exposure_type or "central bank" in exposure_type:
        return sovereign_rw_by_rating.get(rating_bucket, 1.00)

    if "bank" in exposure_type:
        return bank_rw_by_rating.get(rating_bucket, 1.00)

    if "corporate" in exposure_type:
        return corporate_rw_by_rating.get(rating_bucket, 1.00)

    if "retail" in exposure_type:
        return 0.75 if is_regulatory_retail else 1.00

    if "residential" in exposure_type:
        return 0.35 if is_prudent_mortgage else 1.00

    if "commercial" in exposure_type and "real estate" in exposure_type:
        return 1.00

    return 1.00


# -------------------------------------------------------------------
# Basel III Standardized — simplified risk weights
# -------------------------------------------------------------------
def get_standardized_risk_weight_basel3(
    exposure_type: str,
    rating_bucket: str,
    is_regulatory_retail: bool,
    is_prudent_mortgage: bool,
) -> float:
    """
    Simplified Basel III standardized risk weights (illustrative).
    This is intentionally light and should be expanded with Basel III grids (LTV, SCRA, etc.).
    """
    exposure_type = (exposure_type or "").lower()
    rating_bucket = (rating_bucket or "unrated").lower()

    investment_grade_buckets = {"aaa to aa-", "a+ to a-", "bbb+ to bbb-"}

    # For now, reuse Basel II sovereign/bank tables (refine later)
    if "sovereign" in exposure_type or "central bank" in exposure_type:
        return get_standardized_risk_weight_basel2(
            exposure_type="Sovereign / Central Bank",
            rating_bucket=rating_bucket,
            is_regulatory_retail=is_regulatory_retail,
            is_prudent_mortgage=is_prudent_mortgage,
        )

    if "bank" in exposure_type:
        return get_standardized_risk_weight_basel2(
            exposure_type="Bank",
            rating_bucket=rating_bucket,
            is_regulatory_retail=is_regulatory_retail,
            is_prudent_mortgage=is_prudent_mortgage,
        )

    if "corporate" in exposure_type:
        # Simplified: investment grade = 75%, else 100%
        return 0.75 if rating_bucket in investment_grade_buckets else 1.00

    if "retail" in exposure_type:
        return 0.75 if is_regulatory_retail else 1.00

    if "residential" in exposure_type:
        return 0.35 if is_prudent_mortgage else 1.00

    if "commercial" in exposure_type and "real estate" in exposure_type:
        return 1.00

    return 1.00
