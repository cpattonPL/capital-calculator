# app.py
import streamlit as st

from calculators.loans import calculate_loan_capital
from calculators.constants import Approach, ExposureType, RatingBucket


st.set_page_config(page_title="Capital Calculator", layout="wide")
st.title("Capital Calculator")


def _currency(x: float) -> str:
    try:
        return f"${x:,.2f}"
    except Exception:
        return str(x)


def _pct(x: float) -> str:
    try:
        return f"{x * 100:.2f}%"
    except Exception:
        return str(x)


COLLATERAL_OPTIONS = [
    ("Unsecured / None", None),
    ("Financial collateral", "financial"),
    ("Receivables", "receivables"),
    ("Real estate collateral", "real_estate"),
    ("Other physical collateral", "other_physical"),
    ("Intangibles", "intangibles"),
]


def default_revenue_threshold(jurisdiction: str) -> float:
    j = (jurisdiction or "US").upper()
    if j == "CAN":
        return 750_000_000.0
    if j == "EU":
        return 500_000_000.0
    return 500_000_000.0  # US default baseline


with st.sidebar:
    st.header("Approach & Exposure")

    approach = st.selectbox(
        "Capital approach",
        options=list(Approach),
        format_func=lambda a: a.label,
        index=list(Approach).index(Approach.BASEL_III_STANDARDIZED)
        if Approach.BASEL_III_STANDARDIZED in list(Approach)
        else 0,
    )

    exposure_type = st.selectbox(
        "Exposure Type (asset class)",
        options=list(ExposureType),
        format_func=lambda et: et.label,
        index=0,
    )

    rating_bucket = st.selectbox(
        "External rating bucket (if applicable)",
        options=list(RatingBucket),
        format_func=lambda rb: rb.label,
        index=list(RatingBucket).index(RatingBucket.UNRATED),
    )

    st.divider()
    st.header("Jurisdiction & Floors")

    jurisdiction = st.selectbox(
        "Jurisdiction",
        options=["US", "CAN", "EU"],
        index=0,
        help="CAN applies OSFI/Basel III-final input floors. US default applies none; BCBS baseline can be optionally enabled. EU default uses €500m large corporate threshold.",
    )

    apply_bcbs_baseline_floors = st.checkbox(
        "Apply BCBS baseline input floors (US only)",
        value=False,
        help="When enabled in US, applies BCBS Basel III IRB input floors as a configurable option. Canada still uses OSFI rules.",
        disabled=(jurisdiction != "US"),
    )

    st.divider()
    st.header("Capital Settings")
    capital_ratio = st.number_input(
        "Capital Ratio",
        min_value=0.0,
        max_value=1.0,
        value=0.08,
        step=0.005,
        format="%.4f",
        help="Example: 0.08 for 8%",
    )


st.header("Loan Inputs")

col1, col2, col3 = st.columns(3)

with col1:
    loan_type = st.selectbox("Loan type", options=["Term", "LOC", "LC"], index=0)
    commitment = st.number_input(
        "Commitment Amount",
        min_value=0.0,
        value=1_000_000.0,
        step=50_000.0,
        format="%.2f",
        help="Authorized amount available to borrower",
    )
    utilization_pct = st.number_input(
        "Utilization Percent",
        min_value=0.0,
        max_value=1.0,
        value=1.0 if loan_type == "Term" else 0.50,
        step=0.05,
        format="%.4f",
        help="Use 1.0 for 100%",
        disabled=(loan_type == "Term"),
    )

with col2:
    maturity_months = st.number_input(
        "Maturity Term (months)",
        min_value=1,
        value=36,
        step=1,
        help="Number of months until maturity (full principal repayment required)",
    )
    amortization_months = st.number_input(
        "Amortization Term (months)",
        min_value=1,
        value=60,
        step=1,
        help="Number of months the loan is amortized (e.g., 12 to 360)",
    )
    interest_rate = st.number_input(
        "Interest Rate",
        min_value=0.0,
        max_value=1.0,
        value=0.06,
        step=0.005,
        format="%.4f",
        help="Example: 0.06 for 6%",
    )

with col3:
    pd_input = st.number_input(
        "Probability of Default (PD)",
        min_value=0.0,
        max_value=1.0,
        value=0.01,
        step=0.001,
        format="%.6f",
        help="Decimal form (0.01 = 1%). IRB uses PD; Standardized may ignore.",
    )
    lgd_input = st.number_input(
        "Loss Given Default (LGD)",
        min_value=0.0,
        max_value=1.0,
        value=0.45,
        step=0.01,
        format="%.4f",
        help="Decimal form (0.45 = 45%). For Basel III IRB Advanced, treated as bank-estimated LGD and may be floored depending on jurisdiction/settings.",
    )

# Collateral type is ALWAYS a loan input
st.subheader("Credit Risk Mitigation Inputs (future EAD/mitigation, and A-IRB floors when enabled)")
c1, c2 = st.columns([2, 3])

with c1:
    label_to_value = {lbl: val for (lbl, val) in COLLATERAL_OPTIONS}
    selected_label = st.selectbox(
        "Collateral type",
        options=[lbl for (lbl, _) in COLLATERAL_OPTIONS],
        index=0,
        help="Always captured as a loan input. Used today for Basel III IRB Advanced LGD secured-floor selection when floors are enabled, and later for mitigation/EAD work.",
    )
    collateral_type = label_to_value[selected_label]

with c2:
    floors_enabled = (jurisdiction == "CAN") or (jurisdiction == "US" and apply_bcbs_baseline_floors)
    if approach == Approach.BASEL_III_IRB_ADVANCED and floors_enabled:
        st.caption("LGD floors are enabled for this run; collateral type will affect the secured LGD floor.")
    else:
        st.caption("Collateral type is stored but not currently applied (it will be used later for mitigation/EAD work).")

# Derived balance & EAD (simple prototype)
if loan_type == "Term":
    balance = commitment
else:
    balance = commitment * utilization_pct

ead = balance

st.caption(
    f"Derived Balance: **{_currency(balance)}** | Derived EAD (prototype): **{_currency(ead)}**"
)

# A-IRB applicability inputs: Corporate revenue threshold
st.subheader("A-IRB applicability (Large corporate revenue threshold)")

show_rev_inputs = (exposure_type == ExposureType.CORPORATE)
rev1, rev2 = st.columns(2)

with rev1:
    annual_revenue = st.number_input(
        "Annual Revenue (consolidated)",
        min_value=0.0,
        value=0.0,
        step=10_000_000.0,
        format="%.2f",
        disabled=not show_rev_inputs,
        help="Used only to determine A-IRB applicability for large corporates. Set to 0 if unknown/unused.",
    )

with rev2:
    rev_default = default_revenue_threshold(jurisdiction)
    revenue_threshold = st.number_input(
        "Revenue Threshold (editable by jurisdiction)",
        min_value=0.0,
        value=float(rev_default),
        step=10_000_000.0,
        format="%.2f",
        disabled=not show_rev_inputs,
        help="Default: EU €500m, US $500m (modeled), CAN $750m (OSFI). Used to auto-switch A-IRB to F-IRB when exceeded.",
    )

if not show_rev_inputs:
    st.info("Revenue threshold inputs apply to Corporate exposures.")

# Basel II standardized toggles (kept)
st.subheader("Additional Flags (mainly Basel II Standardized)")
flag_col1, flag_col2 = st.columns(2)
with flag_col1:
    is_regulatory_retail = st.checkbox("Regulatory Retail (Basel II)", value=False)
with flag_col2:
    is_prudent_mortgage = st.checkbox("Prudent Mortgage (Basel II)", value=False)

# ============================================================
# CRE UI Fields
# ============================================================
st.subheader("CRE Inputs (Basel III Standardized – Commercial Real Estate)")

show_cre_fields = (
    approach == Approach.BASEL_III_STANDARDIZED
    and exposure_type == ExposureType.COMMERCIAL_REAL_ESTATE
)

if show_cre_fields:
    cre1, cre2, cre3 = st.columns(3)

    with cre1:
        property_value = st.number_input(
            "Property Value",
            min_value=0.0,
            value=2_000_000.0,
            step=50_000.0,
            format="%.2f",
            help="Used to compute LTV = EAD / Property Value",
        )

    with cre2:
        property_income_dependent = st.checkbox(
            "Income-producing / cashflow-dependent CRE?",
            value=False,
            help="Check if repayment is materially dependent on property cash flows.",
        )

    with cre3:
        counterparty_type = st.selectbox(
            "Counterparty Type (used for CRE fallback rules)",
            options=list(ExposureType),
            format_func=lambda et: et.label,
            index=list(ExposureType).index(ExposureType.CORPORATE),
        )

    ltv = (ead / property_value) if property_value and property_value > 0 else None
    st.caption(f"LTV (derived): **{_pct(ltv)}**" if ltv is not None else "LTV (derived): N/A")

else:
    property_value = None
    property_income_dependent = False
    counterparty_type = None
    st.info("Select **Basel III – Standardized** and **Commercial Real Estate** to enable CRE-specific inputs.")

st.divider()

if st.button("Run Calculation", type="primary"):
    result = calculate_loan_capital(
        approach=approach,
        ead=ead,
        balance=balance,
        maturity_months=int(maturity_months),
        amortization_months=int(amortization_months),
        interest_rate=float(interest_rate),
        pd=float(pd_input),
        lgd=float(lgd_input),
        exposure_type=exposure_type,
        rating_bucket=rating_bucket,
        is_regulatory_retail=bool(is_regulatory_retail),
        is_prudent_mortgage=bool(is_prudent_mortgage),
        capital_ratio=float(capital_ratio),
        jurisdiction=jurisdiction,
        apply_bcbs_baseline_floors=bool(apply_bcbs_baseline_floors),
        collateral_type=collateral_type,
        annual_revenue=float(annual_revenue) if annual_revenue is not None else None,
        revenue_threshold=float(revenue_threshold) if revenue_threshold is not None else None,
        property_value=property_value,
        property_income_dependent=bool(property_income_dependent),
        counterparty_type=counterparty_type,
    )

    st.subheader("Results")

    # If not applicable, show the reason prominently and still show payload
    if result.get("status") == "not_applicable":
        st.error(result.get("reason", "Not applicable"))
        st.info(f"Suggested: {result.get('suggested_approach_label')}")
        st.subheader("Full result payload")
        st.json(result)
        st.stop()

    # Background switch banner
    bg = result.get("background_switch")
    if isinstance(bg, dict) and bg.get("enabled"):
        st.warning(
            f"Background switch applied: {bg.get('from_approach_label')} → {bg.get('to_approach_label')} "
            f"(Annual revenue {bg.get('annual_revenue'):,.0f} > threshold {bg.get('revenue_threshold_used'):,.0f})"
        )

    key_cols = st.columns(5)
    with key_cols[0]:
        if "risk_weight_pct" in result:
            st.metric("Risk Weight", result["risk_weight_pct"])
        elif "effective_risk_weight_pct" in result:
            st.metric("Effective Risk Weight", result["effective_risk_weight_pct"])
    with key_cols[1]:
        if "RWA" in result:
            st.metric("RWA", _currency(result["RWA"]))
    with key_cols[2]:
        if "capital_required" in result:
            st.metric("Capital Required", _currency(result["capital_required"]))
    with key_cols[3]:
        st.metric("Requested", result.get("requested_approach_label", ""))
    with key_cols[4]:
        st.metric("Effective", result.get("effective_approach_label", ""))

    # CRE details section
    if "cre_details" in result and isinstance(result["cre_details"], dict):
        st.subheader("CRE details (bucket + rule path)")
        cd = result["cre_details"]

        d1, d2, d3 = st.columns(3)
        with d1:
            st.write("**Rule path**")
            st.write(cd.get("rule_path"))
        with d2:
            st.write("**LTV bucket**")
            st.write(cd.get("ltv_bucket"))
            st.write("**LTV**")
            st.write(cd.get("ltv"))
        with d3:
            st.write("**Counterparty**")
            st.write(cd.get("counterparty_type"))
            st.write("**Counterparty RW**")
            st.write(cd.get("counterparty_rw"))
            st.write("**RW applied**")
            st.write(cd.get("rw_applied"))

        st.caption("Full CRE detail payload:")
        st.json(cd)

    # LGD + PD details (IRB)
    if "lgd_note" in result or "pd_note" in result:
        st.subheader("LGD / PD details (IRB)")
        l1, l2 = st.columns(2)
        with l1:
            st.write("**PD input / used**")
            st.write({"pd_input": result.get("pd_input"), "pd_used": result.get("pd_used"), "pd_floor": result.get("pd_floor")})
            st.write("**PD note**")
            st.write(result.get("pd_note"))
        with l2:
            st.write("**Collateral type (loan input)**")
            st.write(result.get("collateral_type"))
            st.write("**LGD mode**")
            st.write(result.get("lgd_mode"))
            st.write("**LGD used**")
            st.write(result.get("lgd_used"))
            st.write("**LGD floor applied?**")
            st.write(result.get("lgd_floor_applied"))
            st.write("**LGD floor value**")
            st.write(result.get("lgd_floor_value"))
            st.write("**LGD note**")
            st.write(result.get("lgd_note"))
            st.write("**LGD rule path**")
            st.write(result.get("lgd_rule_path"))

    # Output floor section (Basel III IRB)
    if "output_floor" in result and isinstance(result["output_floor"], dict):
        st.subheader("Basel III Output Floor details")
        st.json(result["output_floor"])

    st.subheader("Full result payload")
    st.json(result)
