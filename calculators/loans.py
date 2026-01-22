# calculators/loans.py
"""
Loan calculation module.

Contains:
- Basel II Standardized (unchanged, simplified)
- Basel III Standardized (Corporates implemented using SCRA)
- IRB Foundation (Basel II F-IRB) for Corporate, Bank, Sovereign
- IRB fallback stub for other asset classes

Basel III Standardized scope (current):
- Corporates (SCRA)

Future:
- Banks (SCRA)
- Residential mortgages (LTV buckets)
- CRE
- Retail
"""

import math
from scipy.stats import norm

# Basel IRB scaling factor (Basel II IRB)
SCALING_FACTOR_IRB = 1.06

# Basel PD floors (kept as-is for Basel II IRB prototype)
PD_FLOORS = {
    "corporate": 0.0003,
    "bank": 0.0005,
    "sovereign": 0.0005,
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
    rating_bucket: str,
    is_regulatory_retail: bool = False,
    is_prudent_mortgage: bool = False,
    capital_ratio: float = 0.08,
):
    approach_lower = (approach or "").lower()
    exposure_type_lower = (exposure_type or "").lower()

    # ========================================================
    # STANDARDIZED APPROACHES
    # ========================================================
    if "standardized" in approach_lower:

        # ------------------------
        # Basel II Standardized
        # ------------------------
        if "basel ii" in approach_lower:
            rw = get_standardized_risk_weight_basel2(
                exposure_type=exposure_type,
                rating_bucket=rating_bucket,
                is_regulatory_retail=is_regulatory_retail,
                is_prudent_mortgage=is_prudent_mortgage,
            )
            version = "Basel II"

        # ------------------------
        # Basel III Standardized
        # ------------------------
        elif "basel iii" in approach_lower:
            rw = get_standardized_risk_weight_basel3(
                exposure_type=exposure_type,
                rating_bucket=rating_bucket,
            )
            version = "Basel III"

        else:
            rw = 1.0
            version = "Unknown"

        rwa = ead * rw
        capital_required = rwa * capital_ratio

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
            "capital_required": capital_required,
            "notes": "Standardized approach calculation.",
        }

    # ========================================================
    # IRB APPROACHES (Basel II F-IRB)
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
# BASEL III STANDARDIZED — CORPORATES (SCRA)
# ============================================================
def get_standardized_risk_weight_basel3(
    exposure_type: str,
    rating_bucket: str,
) -> float:
    """
    Basel III Standardized Credit Risk Approach (SCRA).

    Implemented:
    - Corporate exposures

    Risk weights:
    - Investment Grade: 75%
    - Non-Investment Grade: 100%
    - High Risk: 150%
    - Unrated: 100%
    """
    exposure_type = (exposure_type or "").lower()
    rating_bucket = (rating_bucket or "unrated").lower()

    if "corporate" not in exposure_type:
        return 1.00  # placeholder for non-corporates (to be implemented later)

    investment_grade = {
        "aaa to aa-",
        "a+ to a-",
        "bbb+ to bbb-",
    }

    non_investment_grade = {
        "bb+ to b-",
    }

    high_risk = {
        "below b-",
    }

    if rating_bucket in investment_grade:
        return 0.75
    if rating_bucket in non_investment_grade:
        return 1.00
    if rating_bucket in high_risk:
        return 1.50

    return 1.00  # unrated default


# ============================================================
# BASEL II STANDARDIZED (UNCHANGED)
# ============================================================
def get_standardized_risk_weight_basel2(
    exposure_type: str,
    rating_bucket: str,
    is_regulatory_retail: bool,
    is_prudent_mortgage: bool,
) -> float:
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

    if "corporate" in exposure_type:
        return corporate_rw_by_rating.get(rating_bucket, 1.00)

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
        "R": R,
        "K_adjusted": K_adj,
        "RWA": rwa,
        "effective_risk_weight_pct": f"{(rwa / ead) * 100:.2f}%",
        "capital_required": capital_required,
    }


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


def _normalize_rate(x, default: float) -> float:
    if x is None:
        return default
    try:
        val = float(x)
    except (TypeError, ValueError):
        return default
    if val <= 0:
        return default
    if val > 1:
        return val / 100.0
    return val
