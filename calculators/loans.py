# calculators/loans.py
import math
from math import log, sqrt
from scipy.stats import norm

"""
Loan calculation module.

This file contains:
- Standardized approach (simplified)
- IRB Foundation for corporate exposures (Basel II-style)
- IRB fallback for non-corporates (still a stub)

References / implementation notes:
- IRB corporate formulas (correlation, b(PD), K formula, maturity adjustment) follow the Basel II IRB explanatory note.
  Key formula (conceptual):
    K = LGD * N[ (1-R)^(-1/2) * G(PD) + (R/(1-R))^(1/2) * G(0.999) ] - PD * LGD
    K_adj = K * (1 + (M - 2.5) * b(PD)) / (1 - 1.5 * b(PD))
    RWA = 12.5 * K_adj * EAD
  where:
    - G is the inverse normal CDF (norm.ppf)
    - N is the normal CDF (norm.cdf)
    - R = supervisory correlation function of PD
    - b(PD) = (0.11852 - 0.05478 * ln(PD))^2
- Default supervisory LGD for Foundation IRB is 45% if user does not provide an LGD.
- The code must be validated and calibrated against your national regulator's implementation and supervisory parameters.
"""

# ---------------------------
# Top-level defaults
# ---------------------------
# Note: capital_ratio is now passed in from the UI (do not hardcode here)

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
    approach_lower = approach.lower()

    # STANDARDIZED
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
            "risk_weight_pct": f"{rw * 100:.1f}%",
            "EAD": ead,
            "RWA": rwa,
            "capital_required": capital,
            "capital_ratio": capital_ratio,
            "notes": (
                "Standardized approach using simplified risk-weight mapping. "
                "Refine with full Basel tables for production use."
            ),
        }

    # IRB approaches
    elif "irb" in approach_lower:
        # If exposure is corporate, use IRB Foundation corporate implementation
        if exposure_type and "corporate" in exposure_type.lower():
            return _calculate_irb_foundation_corporate(
                ead=ead,
                pd=pd,
                lgd=lgd,
                maturity_months=maturity_months,
                capital_ratio=capital_ratio,
                approach=approach,
            )
        else:
            # Non-corporate IRB not yet implemented — fallback stub
            return _calculate_irb_stub(
                approach=approach,
                ead=ead,
                maturity_months=maturity_months,
                pd=pd,
                lgd=lgd,
                capital_ratio=capital_ratio,
            )
    else:
        return {"error": f"Unknown approach: {approach}"}


# -------------------------------------------------------------------
# IRB Foundation: corporate exposures (Basel II-style)
# -------------------------------------------------------------------
def _calculate_irb_foundation_corporate(ead: float, pd: float, lgd: float, maturity_months: int, capital_ratio: float, approach: str):
    """
    Foundation IRB corporate capital calculation.

    Inputs:
    - ead: exposure at default (currency)
    - pd: probability of default (decimal, e.g., 0.01)
    - lgd: loss given default (decimal). For Foundation IRB, if not provided, we default to 45% (0.45).
    - maturity_months: effective maturity in months (convert to years for formula)
    - capital_ratio: user-supplied capital ratio to compute final capital required

    Returns a dict with K, RWA, capital and diagnostics.
    """

    # Defaults & sanitation
    pd = float(pd) if (pd is not None and pd > 0.0) else 0.01  # default PD = 1% if missing or zero
    lgd = float(lgd) if (lgd is not None and lgd > 0.0) else 0.45  # default LGD = 45% for Foundation IRB
    # Effective maturity (M) based on the facility maturity term (years),
    # subject to Basel floor/cap when measuring M.
    # Basel notes Foundation IRB often uses fixed M=2.5y, but you requested
    # maturity-term-based M for this implementation. :contentReference[oaicite:2]{index=2}
    if maturity_months and maturity_months > 0:
        M_raw = float(maturity_months) / 12.0
        M = min(5.0, max(1.0, M_raw))  # floor 1 year, cap 5 years
    else:
        # If maturity is missing, fall back to the Basel Foundation default 2.5 years.
        M = 2.5  # :contentReference[oaicite:3]{index=3}


    # Supervisory correlation function R(PD) — Basel II corporate formula
    # R = 0.12 * (1 - exp(-50 * PD)) / (1 - exp(-50)) + 0.24 * (1 - (1 - exp(-50 * PD)) / (1 - exp(-50)))
    # This is algebraically equal to:
    # R = 0.12*(1 - exp(-50*PD))/(1 - exp(-50)) + 0.24*(1 - (1 - exp(-50*PD))/(1 - exp(-50)))
    exp_term = math.exp(-50.0 * pd)
    denom = 1.0 - math.exp(-50.0)
    # protect against edge-case denom = 0 (it isn't, but defensive coding)
    if denom == 0:
        denom = 1e-12
    R = 0.12 * (1.0 - exp_term) / denom + 0.24 * (1.0 - (1.0 - exp_term) / denom)

    # b(PD) maturity adjustment parameter
    # b(PD) = (0.11852 - 0.05478 * ln(PD))^2
    # ensure pd not zero to avoid log(0)
    pd_for_b = max(pd, 1e-9)
    b = (0.11852 - 0.05478 * math.log(pd_for_b)) ** 2

    # Compute the ASRF term:
    # term = (1 - R)^(-1/2) * G(PD) + (R / (1 - R))^(1/2) * G(0.999)
    inv_norm_pd = norm.ppf(pd)      # G(PD)
    inv_norm_999 = norm.ppf(0.999)  # G(0.999)
    term = (inv_norm_pd / math.sqrt(1.0 - R)) + (math.sqrt(R / (1.0 - R)) * inv_norm_999)

    # K (unadjusted)
    K_unadj = lgd * norm.cdf(term) - pd * lgd

    # Maturity adjustment factor
    # K_adj = K_unadj * (1 + (M - 2.5) * b) / (1 - 1.5 * b)
    denom_ma = (1.0 - 1.5 * b)
    if denom_ma <= 0:
        # if denominator non-positive, clip to small positive to avoid division by zero / nonsensical growth
        denom_ma = 1e-9
    maturity_adjustment = (1.0 + (M - 2.5) * b) / denom_ma

    K_adj = K_unadj * maturity_adjustment

    # Regulatory scaling to RWA: RWA = 12.5 * K_adj * EAD
    SCALING_FACTOR_IRB = 1.06  # Basel IRB scaling factor

    rwa = 12.5 * SCALING_FACTOR_IRB * K_adj * ead


    # capital required using the user-supplied capital ratio
    capital_required = rwa * capital_ratio

    result = {
        "approach": approach,
        "irb_treatment": "Foundation - Corporate",
        "pd_used": pd,
        "lgd_used": lgd,
        "maturity_years": M,
        "supervisory_correlation_R": R,
        "b_pd": b,
        "K_unadjusted": K_unadj,
        "maturity_adjustment_factor": maturity_adjustment,
        "K_adjusted": K_adj,
        "EAD": ead,
        "RWA": rwa,
        "capital_ratio": capital_ratio,
        "capital_required": capital_required,
        "notes": (
            "IRB Foundation corporate calculation implemented. Defaults: PD=1% if missing, LGD=45% if missing, M=3y if missing."
            " Validate against regulatory worked examples and your jurisdiction's supervisory parameters."
        ),
    }

    return result


# -------------------------------------------------------------------
# IRB fallback stub for non-corporates (keeps previous behavior)
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
    Very rough IRB placeholder for non-corporates — DO NOT USE FOR REAL CAPITAL CALCULATION.
    Kept for continuity for asset classes we haven't implemented yet.
    """
    pd = pd if pd and pd > 0 else 0.01
    lgd = lgd if lgd and lgd > 0 else 0.45

    base_rw = pd * (lgd * 12) + (maturity_months / 120.0)
    risk_weight = min(5.0, max(0.5, base_rw))  # between 50% and 500%

    rwa = ead * risk_weight
    capital = rwa * capital_ratio

    return {
        "approach": approach,
        "pd_used": pd,
        "lgd_used": lgd,
        "risk_weight": risk_weight,
        "risk_weight_pct": f"{risk_weight * 100:.1f}%",
        "EAD": ead,
        "RWA": rwa,
        "capital_required": capital,
        "capital_ratio": capital_ratio,
        "notes": (
            "IRB calculation is a placeholder for non-corporate exposures. Implement "
            "the official IRB risk-weight formulas for each asset class before use."
        ),
    }


# -------------------------------------------------------------------
# Standardized (unchanged simplified helpers below)
# -------------------------------------------------------------------
def get_standardized_risk_weight_basel2(
    exposure_type: str,
    rating_bucket: str,
    is_regulatory_retail: bool,
    is_prudent_mortgage: bool,
) -> float:
    exposure_type = exposure_type.lower()
    rating_bucket = rating_bucket.lower()

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


def get_standardized_risk_weight_basel3(
    exposure_type: str,
    rating_bucket: str,
    is_regulatory_retail: bool,
    is_prudent_mortgage: bool,
) -> float:
    exposure_type = exposure_type.lower()
    rating_bucket = rating_bucket.lower()

    investment_grade_buckets = {
        "aaa to aa-",
        "a+ to a-",
        "bbb+ to bbb-",
    }

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
        if rating_bucket in investment_grade_buckets:
            return 0.75
        else:
            return 1.00

    if "retail" in exposure_type:
        return 0.75 if is_regulatory_retail else 1.00

    if "residential" in exposure_type:
        return 0.35 if is_prudent_mortgage else 1.00

    if "commercial" in exposure_type and "real estate" in exposure_type:
        return 1.00

    return 1.00
