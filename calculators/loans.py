# calculators/loans.py
"""
Loan calculation module.

Contains:
- Standardized approach (Basel II + Basel III) — simplified mappings
- IRB Foundation (Corporate, Bank, Sovereign/Central Bank) — ASRF implementation
- IRB fallback stub for other exposure types (until implemented)

Notes:
- IRB Foundation implementation uses the Basel IRB ASRF/Vasicek structure with 99.9th percentile,
  maturity adjustment, and IRB scaling factor 1.06.
- Effective maturity M is derived from the loan's maturity term (months) with Basel-style floor/cap:
  floor 1 year, cap 5 years; fallback 2.5 years if missing.
- Foundation IRB uses supervisory LGD by default (0.45) if user doesn't provide LGD.

Dependencies:
- scipy (for norm.cdf / norm.ppf)
"""

import math
from scipy.stats import norm

# Basel IRB scaling factor
SCALING_FACTOR_IRB = 1.06


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
# IRB Foundation wrappers (Step 3 refactor: corporate uses shared helper)
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
        asset_class="Foundation - Corporate",
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
        asset_class="Foundation - Bank",
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
        asset_class="Foundation - Sovereign/Central Bank",
        ead=ead,
        pd=pd,
        lgd=lgd,
        maturity_months=maturity_months,
        capital_ratio=capital_ratio,
        approach=approach,
    )


def _calculate_irb_foundation_asrf(
    asset_class: str,
    ead: float,
    pd: float,
    lgd: float,
    maturity_months: int,
    capital_ratio: float,
    approach: str,
):
    """
    Shared ASRF implementation for Foundation IRB (Corporate/Bank/Sovereign).

    Steps:
      1) Sanitize inputs, default PD and supervisory LGD where missing.
      2) Determine effective maturity M from maturity_months with floor/cap (1 to 5 years).
      3) Compute supervisory correlation R(PD).
      4) Compute b(PD) maturity factor.
      5) Compute unadjusted K via Vasicek/ASRF at 99.9%.
      6) Apply maturity adjustment to K.
      7) Convert to RWA with 12.5 * 1.06 * K_adj * EAD.
      8) Apply user-supplied capital_ratio to compute capital_required.
    """
    # Defaults & sanitation
    pd_used = float(pd) if (pd is not None and pd > 0.0) else 0.01
    # Foundation IRB supervisory LGD default (common baseline): 45%
    lgd_used = float(lgd) if (lgd is not None and lgd > 0.0) else 0.45

    # Effective maturity M based on loan maturity term (years), floor 1, cap 5; fallback 2.5
    if maturity_months and maturity_months > 0:
        M_raw = float(maturity_months) / 12.0
        M = min(5.0, max(1.0, M_raw))
    else:
        M_raw = None
        M = 2.5

    # Supervisory correlation function R(PD) for corporate/bank/sovereign style exposures
    exp_term = math.exp(-50.0 * pd_used)
    denom = 1.0 - math.exp(-50.0)
    denom = denom if denom != 0 else 1e-12
    R = 0.12 * (1.0 - exp_term) / denom + 0.24 * (1.0 - (1.0 - exp_term) / denom)

    # b(PD) maturity adjustment parameter
    pd_for_b = max(pd_used, 1e-9)
    b = (0.11852 - 0.05478 * math.log(pd_for_b)) ** 2

    # ASRF term at 99.9%
    inv_norm_pd = norm.ppf(pd_used)
    inv_norm_999 = norm.ppf(0.999)
    term = (inv_norm_pd / math.sqrt(1.0 - R)) + (math.sqrt(R / (1.0 - R)) * inv_norm_999)

    # K (unadjusted)
    K_unadj = lgd_used * norm.cdf(term) - pd_used * lgd_used

    # Maturity adjustment
    denom_ma = (1.0 - 1.5 * b)
    denom_ma = denom_ma if denom_ma > 0 else 1e-9
    maturity_adjustment = (1.0 + (M - 2.5) * b) / denom_ma
    K_adj = K_unadj * maturity_adjustment

    # RWA conversion with scaling factor
    rwa = 12.5 * SCALING_FACTOR_IRB * K_adj * ead
    capital_required = rwa * capital_ratio

    # Handy derived "risk weight" for display: RW = RWA / EAD
    rw_effective = (rwa / ead) if ead and ead > 0 else None

    return {
        "approach": approach,
        "irb_treatment": asset_class,
        "pd_used": pd_used,
        "lgd_used": lgd_used,
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
            "Includes maturity adjustment and IRB scaling factor 1.06."
        ),
    }


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
    pd_used = float(pd) if (pd is not None and pd > 0.0) else 0.01
    lgd_used = float(lgd) if (lgd is not None and lgd > 0.0) else 0.45
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
