import streamlit as st
import pandas as pd
import numpy as np

from calculators.common import compute_ead, format_currency
from calculators.loans import calculate_loan_capital
from calculators.securitizations import calculate_securitization_capital
from calculators.constants import Approach, ExposureType, RatingBucket

st.set_page_config(page_title="Capital Calculator", layout="wide")

st.title("Capital Calculator — Loans & Securitizations")
st.markdown(
    "Choose an exposure type, specify characteristics and pick a regulatory approach. "
    "This prototype provides a scaffold — replace placeholder pieces with the exact "
    "regulatory formulas (see docs)."
)

# Global selection: Loans or Securitization
exposure_choice = st.selectbox("Exposure type", ["Loans", "Securitization"])

# =========================
# LOANS
# =========================
if exposure_choice == "Loans":
    st.header("Loan characteristics")

    # Existing loan inputs
    loan_type = st.selectbox("Loan type", ["Term", "LOC", "LC"])
    commitment_amount = st.number_input(
        "Commitment Amount",
        min_value=0.0,
        value=1_000_000.0,
        step=1_000.0,
    )
    utilization_pct = st.number_input(
        "Utilization Percent (0-100)",
        min_value=0.0,
        max_value=100.0,
        value=100.0,
    )
    balance = st.number_input(
        "Balance (if different from Commitment * Utilization)",
        value=commitment_amount * (utilization_pct / 100.0),
    )
    maturity_months = st.number_input(
        "Maturity Term (months)",
        min_value=1,
        value=60,
    )
    amortization_months = st.number_input(
        "Amortization Term (months)",
        min_value=1,
        value=60,
    )
    interest_rate = st.number_input(
        "Interest Rate (annual %)",
        min_value=0.0,
        value=4.5,
    )

    # PD / LGD inputs (used for IRB; may be ignored/overridden for standardized)
    pd_input = st.number_input(
        "Probability of Default (PD, decimal or %)",
        min_value=0.0,
        value=0.01,
        help=(
            "If the regulatory approach requires PD, you can input here. "
            "Otherwise this may be ignored or replaced by the approach."
        ),
    )
    lgd_input = st.number_input(
        "Loss Given Default (LGD, decimal or %)",
        min_value=0.0,
        value=0.45,
        help=(
            "If the regulatory approach requires LGD, you can input here. "
            "Otherwise this may be ignored or replaced by the approach."
        ),
    )

    st.markdown("---")
    st.subheader("Capital settings")

    capital_ratio = st.number_input(
        "Capital Ratio (e.g. 0.08 = 8%)",
        min_value=0.0,
        max_value=1.0,
        value=0.08,
        step=0.005,
        help=(
            "Target capital ratio applied to RWA. "
            "Basel minimum total capital is typically 8%, "
            "but banks often use higher internal targets."
        ),
    )


    st.markdown("---")
    st.subheader("Standardized exposure classification")

    # NEW: standardized exposure type (Basel asset class)
    exposure_type = st.selectbox(
        "Exposure Type (asset class)",
        options=list(ExposureType),
        format_func=lambda et: et.label,
    )


    # NEW: rating bucket used by standardized approach (if relevant)
    rating_bucket = st.selectbox(
        "External rating bucket (if applicable)",
        options=list(RatingBucket),
        format_func=lambda rb: rb.label,
    )


    # NEW: flags that influence standardized mapping
    is_regulatory_retail = st.checkbox(
        "Regulatory retail portfolio (for Retail)",
        value=True,
        help="Relevant if Exposure Type = Retail. 75% RW typically applies to qualifying retail portfolios.",
    )
    is_prudent_mortgage = st.checkbox(
        "Prudently underwritten residential mortgage (for Residential Mortgage)",
        value=True,
        help="Relevant if Exposure Type = Residential Mortgage. Standard Basel II RW is 35% for prudently underwritten mortgages.",
    )

    st.markdown("---")
    st.subheader("Choose regulatory approach")

    approach = st.selectbox(
        "Capital approach",
        options=list(Approach),
        format_func=lambda a: a.label,
    )

    if st.button("Calculate loan capital"):
        ead = compute_ead(commitment_amount, balance, loan_type, utilization_pct)
        result = calculate_loan_capital(
            approach=approach,
            ead=ead,
            balance=balance,
            maturity_months=maturity_months,
            amortization_months=amortization_months,
            interest_rate=interest_rate,
            pd=pd_input,
            lgd=lgd_input,
            exposure_type=exposure_type,   # enum
            rating_bucket=rating_bucket,   # enum
            is_regulatory_retail=is_regulatory_retail,
            is_prudent_mortgage=is_prudent_mortgage,
            capital_ratio=capital_ratio,
        )



        st.write("### Results")
        st.write(f"Exposure at Default (EAD): {format_currency(ead)}")
        st.json(result)

# =========================
# SECURITIZATIONS
# =========================
else:
    st.header("Securitization characteristics")

    exposure_amount = st.number_input(
        "Exposure Amount",
        min_value=0.0,
        value=1_000_000.0,
    )
    tranche_rating = st.text_input("Tranche external rating (if available)", value="")
    tranche_credit_enhancement = st.number_input(
        "Credit enhancement (%)",
        min_value=0.0,
        max_value=100.0,
        value=10.0,
    )
    secur_approach = st.selectbox(
        "Securitization Approach",
        [
            "SSFA (Basel II - SSFA)",
            "SEC-SA (Basel III - SEC-SA)",
            "SEC-ERBA (Basel III - ERBA)",
            "SEC-IRB (Basel III - IRB)",
        ],
    )

    if st.button("Calculate securitization capital"):
        result = calculate_securitization_capital(
            approach=secur_approach,
            exposure_amount=exposure_amount,
            tranche_rating=tranche_rating,
            credit_enhancement=tranche_credit_enhancement,
        )
        st.write("### Results")
        st.json(result)
