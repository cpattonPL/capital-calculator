"""
Loan calculation module.

Each approach function returns a dict with:
- 'RWA' (risk-weighted assets)
- 'capital_required' (e.g., 8% of RWA or other regulatory %)
- intermediate items used (pd/lgd/effective_risk_weight/etc)

Standardised approach:
- Implements a *simplified* Basel II standardized mapping for key exposure types
  (sovereign/central bank, bank, corporate, retail, residential mortgages, etc.). :contentReference[oaicite:1]{index=1}
- Implements a *simplified* Basel III standardized mapping (e.g., investment-grade corporates
  with lower weights, but without the full LTV/leverage grids). :contentReference[oaicite:2]{index=2}
  You should refine these with the exact tables from BCBS128 and d424.

IRB:
- Still a stub that demonstrates the structure; replace with the IRB risk-weight functions
  from the Basel II IRB risk-weight paper and Basel III constraints. :contentReference[oaicite:3]{index=3}
"""

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
    - For standardized approaches: compute risk weight from exposure type + rating bucket.
    - For IRB approaches: use PD/LGD stub function (to be replaced with proper IRB formula).

    Returns a dict with RWA and capital plus some diagnostics.
    """
    approach_lower = approach.lower()

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
            "risk_weight_pct": f"{rw * 100:.1f}%",
            "EAD": ead,
            "RWA": rwa,
            "capital_required": capital,
            "capital_ratio": capital_ratio,   # NEW
            "notes": (
                "Standardized approach using simplified risk-weight mapping. "
                "Refine with full Basel tables for production use."
            ),
        }

    # =========================
    # IRB APPROACHES (STUB)
    # =========================
    elif "irb" in approach_lower:
        return _calculate_irb_stub(
            approach=approach,
            ead=ead,
            maturity_months=maturity_months,
            pd=pd,
            lgd=lgd,
            capital_ratio=capital_ratio,
        )


    # =========================
    # FALLBACK
    # =========================
    else:
        return {"error": f"Unknown approach: {approach}"}


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

    Key ideas:
    - Claims on corporates: 20/50/100/150% based on external rating, 100% for unrated. :contentReference[oaicite:4]{index=4}
    - Retail claims: 75% if qualifying retail; otherwise 100%. :contentReference[oaicite:5]{index=5}
    - Residential mortgages: 35% for prudently underwritten exposures, otherwise 100%. :contentReference[oaicite:6]{index=6}
    - Sovereigns and banks: rating-based buckets (simplified).
    - Other assets: 100%.

    Returns a decimal risk weight (e.g., 1.0 = 100%).
    """
    exposure_type = exposure_type.lower()
    rating_bucket = rating_bucket.lower()

    # Helper: rating-based RW mapping for corporates (Basel II-style)
    corporate_rw_by_rating = {
        "aaa to aa-": 0.20,
        "a+ to a-": 0.50,
        "bbb+ to bbb-": 1.00,
        "bb+ to b-": 1.00,
        "below b-": 1.50,
        "unrated": 1.00,
    }

    # Sovereign / central bank — simplified Basel II table
    sovereign_rw_by_rating = {
        "aaa to aa-": 0.00,
        "a+ to a-": 0.20,
        "bbb+ to bbb-": 0.50,
        "bb+ to b-": 1.00,
        "below b-": 1.50,
        "unrated": 1.00,
    }

    # Banks — simplified rating-based mapping
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
        return 1.00  # 100% RW for commercial real estate (simplified)

    # Other assets default to 100% RW
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
    Simplified Basel III standardized risk weights.

    This is deliberately a *light* implementation:
    - Corporates: treat "Investment Grade" (AAA–BBB-) as 75%, others 100%, unrated 100%. :contentReference[oaicite:7]{index=7}
    - Retail: 75% (regulatory retail) or 100% (other).
    - Residential mortgages: 35% for qualifying exposures, otherwise 100%.
      (Real Basel III uses LTV + income-producing distinctions.)
    - Sovereigns and banks: reuse Basel II tables for now (to be refined).
    """
    exposure_type = exposure_type.lower()
    rating_bucket = rating_bucket.lower()

    # Simple notion of "investment grade": AAA to BBB-
    investment_grade_buckets = {
        "aaa to aa-",
        "a+ to a-",
        "bbb+ to bbb-",
    }

    # For simplicity, reuse Basel II sovereign/bank tables
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
            return 0.75  # simplified investment-grade corporate RW
        else:
            return 1.00  # all other corporates (including unrated)

    if "retail" in exposure_type:
        return 0.75 if is_regulatory_retail else 1.00

    if "residential" in exposure_type:
        return 0.35 if is_prudent_mortgage else 1.00

    if "commercial" in exposure_type and "real estate" in exposure_type:
        # Basel III actually uses LTV-based buckets; keep 100% as a placeholder
        return 1.00

    return 1.00


# -------------------------------------------------------------------
# IRB stub (unchanged structural idea, but slightly cleaned)
# -------------------------------------------------------------------
def _calculate_irb_stub(
    approach: str,
    ead: float,
    maturity_months: int,
    pd: float,
    lgd: float,
):
    """
    Very rough IRB placeholder — DO NOT USE FOR REAL CAPITAL CALCULATION.

    Replace with:
    - Basel II IRB risk-weight functions (corporate, sovereign, bank, etc.). :contentReference[oaicite:8]{index=8}
    - Basel III constraints/parameter floors.

    For now, we:
    - Default PD to 1% and LGD to 45% if omitted.
    - Scale a pseudo "risk weight" based on PD, LGD and maturity.
    """
    approach_lower = approach.lower()
    pd = pd if pd and pd > 0 else 0.01
    lgd = lgd if lgd and lgd > 0 else 0.45

    # Completely arbitrary placeholder; bounded to avoid absurd numbers
    base_rw = pd * (lgd * 12) + (maturity_months / 120.0)
    risk_weight = min(5.0, max(0.5, base_rw))  # between 50% and 500%

    rwa = ead * risk_weight
    capital = rwa * BASE_CAPITAL_RATIO

    return {
        "approach": approach,
        "pd_used": pd,
        "lgd_used": lgd,
        "risk_weight": risk_weight,
        "risk_weight_pct": f"{risk_weight * 100:.1f}%",
        "EAD": ead,
        "RWA": rwa,
        "capital_required": capital,
        "capital_ratio": BASE_CAPITAL_RATIO,
        "notes": (
            "IRB calculation is a placeholder. Implement the official IRB risk-weight "
            "formulas (Basel II/III) before using for any real decisions."
        ),
    }
