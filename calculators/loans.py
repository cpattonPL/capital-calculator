# calculators/loans.py
"""
Loan calculation module with Basel III A-IRB LGD input floors & audit outputs.

Key changes:
- Adds LGD_FLOORS_BASEL3, applied only when Approach == BASEL_III_IRB_ADVANCED and
  lgd_mode == "bank_estimated".
- Emits lgd_floor_applied, lgd_floor_value, lgd_note in IRB outputs for auditability.
- Leaves existing CRE details and output floor behavior intact.
"""

import math
from typing import Optional, Union, Tuple, Dict, Any

from scipy.stats import norm

from calculators.constants import Approach, ExposureType, RatingBucket


# ----------------------------
# Basel II IRB scaling factor
# ----------------------------
SCALING_FACTOR_BASEL2_IRB = 1.06

# Basel III output floor (72.5% of standardized RWA)
BASEL3_OUTPUT_FLOOR_PCT = 0.725


# ----------------------------
# PD floors (prototype)
# ----------------------------
PD_FLOORS_BASEL2 = {
    "corporate": 0.0003,  # 0.03%
    "bank": 0.0005,       # 0.05%
    "sovereign": 0.0005,  # 0.05%
}

# Basel III PD floor (prototype)
PD_FLOORS_BASEL3 = {
    "corporate": 0.0005,  # 0.05%
    "bank": 0.0005,       # 0.05%
    "sovereign": 0.0005,  # 0.05%
}

# Supervisory LGD defaults for F-IRB (prototype defaults)
LGD_DEFAULTS_BASEL2_FIRB = {
    "corporate": 0.45,
    "bank": 0.45,
    "sovereign": 0.45,
}

# Basel III F-IRB supervisory LGD defaults (prototype)
LGD_DEFAULTS_BASEL3_FIRB = {
    "corporate": 0.40,
    "bank": 0.45,
    "sovereign": 0.45,
}

# ----------------------------
# Basel III A-IRB LGD floors (input constraints for bank-estimated LGD)
# Prototype values — replace with your jurisdiction's supervisory floors as required.
# These floors are only applied when A-IRB is selected and LGD is bank-estimated.
# ----------------------------
LGD_FLOORS_BASEL3 = {
    "corporate": 0.10,   # 10% minimum LGD for corporate exposures (example prototype)
    "bank": 0.05,        # 5% minimum LGD for bank exposures (example prototype)
    "sovereign": 0.02,   # 2% minimum LGD for sovereign exposures (example prototype)
}


# ============================================================
# PUBLIC ENTRYPOINT
# ============================================================
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
    # CRE-specific optional parameters
    property_value: Optional[float] = None,
    property_income_dependent: bool = False,
    counterparty_type: Optional[Union[ExposureType, str]] = None,
) -> Dict[str, Any]:
    approach_enum = _coerce_approach(approach)
    et_enum = _coerce_exposure_type(exposure_type)
    rb_enum = _coerce_rating_bucket(rating_bucket)
    cp_enum = _coerce_exposure_type(counterparty_type) if counterparty_type is not None else ExposureType.CORPORATE

    # fallback if coercion fails
    if approach_enum is None:
        s = (approach or "").lower()
        if "basel iii" in s and "standard" in s:
            approach_enum = Approach.BASEL_III_STANDARDIZED
        elif "basel iii" in s and "advanced" in s and "irb" in s:
            approach_enum = Approach.BASEL_III_IRB_ADVANCED
        elif "basel iii" in s and "irb" in s:
            approach_enum = Approach.BASEL_III_IRB_FOUNDATION
        elif "irb" in s:
            approach_enum = Approach.BASEL_II_IRB
        elif "basel ii" in s and "standard" in s:
            approach_enum = Approach.BASEL_II_STANDARDIZED
        else:
            approach_enum = Approach.BASEL_II_STANDARDIZED

    # =========================
    # STANDARDIZED
    # =========================
    if approach_enum.method == "standardized":
        if approach_enum.regime == "basel3":
            rw, cre_details = get_standardized_risk_weight_basel3(
                exposure_type=et_enum,
                rating_bucket=rb_enum,
                ead=ead,
                property_value=property_value,
                property_income_dependent=property_income_dependent,
                counterparty_type=cp_enum,
            )
            version = "Basel III"
        else:
            rw = get_standardized_risk_weight_basel2(
                exposure_type=et_enum,
                rating_bucket=rb_enum,
                is_regulatory_retail=is_regulatory_retail,
                is_prudent_mortgage=is_prudent_mortgage,
            )
            cre_details = None
            version = "Basel II"

        rwa = ead * rw
        capital_required = rwa * capital_ratio

        out: Dict[str, Any] = {
            "approach_enum": approach_enum.name,
            "approach_label": approach_enum.label,
            "version": version,
            "exposure_type_enum": (et_enum.name if et_enum else None),
            "rating_bucket_enum": (rb_enum.name if rb_enum else None),
            "risk_weight": rw,
            "risk_weight_pct": f"{rw * 100:.2f}%",
            "EAD": ead,
            "property_value": property_value,
            "LTV": (ead / property_value if property_value and property_value > 0 else None),
            "property_income_dependent": property_income_dependent,
            "RWA": rwa,
            "capital_ratio": capital_ratio,
            "capital_required": capital_required,
        }
        if cre_details is not None:
            out["cre_details"] = cre_details
        return out

    # =========================
    # IRB (Basel II + Basel III Foundation/Advanced)
    # =========================
    if approach_enum.method == "irb":
        # Output floor applies to Basel III IRB (both F-IRB and A-IRB)
        apply_output_floor = approach_enum.regime == "basel3"

        # Determine asset_class_key from exposure type
        asset_class_key = None
        asset_class_label = None
        if et_enum == ExposureType.CORPORATE:
            asset_class_key = "corporate"
            asset_class_label = "IRB - Corporate"
        elif et_enum == ExposureType.BANK:
            asset_class_key = "bank"
            asset_class_label = "IRB - Bank"
        elif et_enum == ExposureType.SOVEREIGN_CENTRAL_BANK:
            asset_class_key = "sovereign"
            asset_class_label = "IRB - Sovereign/Central Bank"
        else:
            return _calculate_irb_stub(
                approach_enum=approach_enum,
                ead=ead,
                maturity_months=maturity_months,
                pd=pd,
                lgd=lgd,
                capital_ratio=capital_ratio,
            )

        # Basel III IRB branching: Foundation vs Advanced
        if approach_enum.regime == "basel3":
            pd_floors = PD_FLOORS_BASEL3
            scaling_factor = 1.0

            if approach_enum == Approach.BASEL_III_IRB_ADVANCED:
                irb_mode = "Basel III IRB - Advanced"
                lgd_mode = "bank_estimated"
                lgd_defaults = LGD_DEFAULTS_BASEL3_FIRB
                # A-IRB: also apply LGD floors for bank-estimated LGD
                lgd_floors = LGD_FLOORS_BASEL3
            else:
                # Foundation (also covers BASEL_III_IRB alias)
                irb_mode = "Basel III IRB - Foundation"
                lgd_mode = "supervisory"
                lgd_defaults = LGD_DEFAULTS_BASEL3_FIRB
                lgd_floors = {}  # no bank-estimated LGD floors applied for F-IRB
        else:
            # Basel II IRB Foundation (existing prototype)
            pd_floors = PD_FLOORS_BASEL2
            scaling_factor = SCALING_FACTOR_BASEL2_IRB
            irb_mode = "Basel II IRB - Foundation"
            lgd_mode = "supervisory"
            lgd_defaults = LGD_DEFAULTS_BASEL2_FIRB
            lgd_floors = {}

        irb_result = _calculate_irb_asrf(
            asset_class_key=asset_class_key,
            asset_class_label=asset_class_label,
            ead=ead,
            pd=pd,
            lgd=lgd,
            maturity_months=maturity_months,
            capital_ratio=capital_ratio,
            approach_enum=approach_enum,
            pd_floors=pd_floors,
            lgd_defaults=lgd_defaults,
            scaling_factor=scaling_factor,
            irb_mode=irb_mode,
            lgd_mode=lgd_mode,
            lgd_floors=lgd_floors,
        )

        # Basel II IRB returns directly (no output floor)
        if not apply_output_floor:
            return irb_result

        # Basel III Output Floor:
        # compare IRB RWA to 72.5% of Basel III standardized RWA
        std_rw, std_cre_details = get_standardized_risk_weight_basel3(
            exposure_type=et_enum,
            rating_bucket=rb_enum,
            ead=ead,
            property_value=property_value,
            property_income_dependent=property_income_dependent,
            counterparty_type=cp_enum,
        )
        rwa_std = ead * std_rw
        floor_rwa = BASEL3_OUTPUT_FLOOR_PCT * rwa_std

        rwa_irb_pre_floor = float(irb_result.get("RWA", 0.0))
        rwa_final = max(rwa_irb_pre_floor, float(floor_rwa))
        capital_required_final = rwa_final * float(capital_ratio)

        irb_result["output_floor"] = {
            "enabled": True,
            "floor_pct_of_standardized_rwa": BASEL3_OUTPUT_FLOOR_PCT,
            "standardized_version_used": "Basel III",
            "standardized_risk_weight": std_rw,
            "standardized_risk_weight_pct": f"{std_rw * 100:.2f}%",
            "standardized_rwa": rwa_std,
            "floor_rwa": floor_rwa,
            "rwa_irb_pre_floor": rwa_irb_pre_floor,
            "rwa_final_post_floor": rwa_final,
            "binding": rwa_final > rwa_irb_pre_floor + 1e-12,
            "notes": "RWA_final = max(RWA_IRB, 72.5% × RWA_Standardized).",
        }
        if std_cre_details is not None:
            irb_result["output_floor"]["standardized_cre_details"] = std_cre_details

        # Align top-level outputs with post-floor values
        irb_result["RWA"] = rwa_final
        irb_result["capital_required"] = capital_required_final
        irb_result["effective_risk_weight_pct"] = (
            f"{(rwa_final / ead) * 100:.2f}%" if ead and ead > 0 else None
        )

        return irb_result

    return {"error": "Unsupported approach/method"}


# ============================================================
# BASEL III STANDARDIZED
# Returns: (risk_weight, cre_details_or_none)
# ============================================================
def get_standardized_risk_weight_basel3(
    exposure_type: Optional[ExposureType],
    rating_bucket: Optional[RatingBucket],
    *,
    ead: Optional[float] = None,
    property_value: Optional[float] = None,
    property_income_dependent: bool = False,
    counterparty_type: Optional[ExposureType] = None,
) -> Tuple[float, Optional[dict]]:
    # Corporate SCRA
    if exposure_type == ExposureType.CORPORATE:
        if rating_bucket in {RatingBucket.AAA_AA, RatingBucket.A, RatingBucket.BBB}:
            return 0.75, None
        if rating_bucket == RatingBucket.BB_B:
            return 1.00, None
        if rating_bucket == RatingBucket.BELOW_B:
            return 1.50, None
        return 1.00, None

    # Bank SCRA
    if exposure_type == ExposureType.BANK:
        if rating_bucket == RatingBucket.AAA_AA:
            return 0.20, None
        if rating_bucket == RatingBucket.A:
            return 0.50, None
        if rating_bucket == RatingBucket.BBB:
            return 0.75, None
        if rating_bucket == RatingBucket.BB_B:
            return 1.00, None
        if rating_bucket == RatingBucket.BELOW_B:
            return 1.50, None
        return 1.00, None

    # CRE
    if exposure_type == ExposureType.COMMERCIAL_REAL_ESTATE:
        return _basel3_cre_risk_weight_with_details(
            rating_bucket=rating_bucket,
            ead=ead,
            property_value=property_value,
            property_income_dependent=property_income_dependent,
            counterparty_type=counterparty_type or ExposureType.CORPORATE,
        )

    return 1.00, None


def _basel3_cre_risk_weight_with_details(
    *,
    rating_bucket: Optional[RatingBucket],
    ead: Optional[float],
    property_value: Optional[float],
    property_income_dependent: bool,
    counterparty_type: ExposureType,
) -> Tuple[float, dict]:
    ltv = None
    if property_value and property_value > 0 and ead is not None:
        ltv = float(ead) / float(property_value)

    # Counterparty RW (for general CRE)
    cp_rw, _ = get_standardized_risk_weight_basel3(
        exposure_type=counterparty_type,
        rating_bucket=rating_bucket,
        ead=None,
        property_value=None,
        property_income_dependent=False,
        counterparty_type=None,
    )
    if counterparty_type not in {ExposureType.CORPORATE, ExposureType.BANK}:
        cp_rw = max(cp_rw, 1.00)

    details = {
        "asset_class": "CRE",
        "property_income_dependent": property_income_dependent,
        "counterparty_type": (counterparty_type.name if counterparty_type else None),
        "counterparty_rw": cp_rw,
        "ltv": ltv,
        "ltv_bucket": None,
        "rule_path": None,
        "rw_applied": None,
    }

    # Income-producing CRE
    if property_income_dependent:
        if ltv is None:
            rw = 1.10
            details["ltv_bucket"] = "Unknown (no property_value)"
            details["rule_path"] = "Basel III CRE (income-dependent): LTV unknown → default RW 110%"
            details["rw_applied"] = rw
            return rw, details

        if ltv <= 0.60:
            rw = 0.70
            details["ltv_bucket"] = "<= 60%"
            details["rule_path"] = "Basel III CRE (income-dependent): LTV <= 60% → RW 70%"
        elif ltv <= 0.80:
            rw = 0.90
            details["ltv_bucket"] = "60%–80%"
            details["rule_path"] = "Basel III CRE (income-dependent): 60% < LTV <= 80% → RW 90%"
        else:
            rw = 1.10
            details["ltv_bucket"] = "> 80%"
            details["rule_path"] = "Basel III CRE (income-dependent): LTV > 80% → RW 110%"

        details["rw_applied"] = rw
        return rw, details

    # General CRE
    if ltv is not None:
        if ltv <= 0.60:
            rw = min(0.60, cp_rw)
            details["ltv_bucket"] = "<= 60%"
            details["rule_path"] = "Basel III CRE (general): LTV <= 60% → RW = min(60%, RW_counterparty)"
            details["rw_applied"] = rw
            return rw, details

        rw = cp_rw
        details["ltv_bucket"] = "> 60%"
        details["rule_path"] = "Basel III CRE (general): LTV > 60% → RW = RW_counterparty"
        details["rw_applied"] = rw
        return rw, details

    rw = max(cp_rw, 1.00)
    details["ltv_bucket"] = "Unknown (no property_value)"
    details["rule_path"] = "Basel III CRE (general): LTV unknown → RW = max(RW_counterparty, 100%)"
    details["rw_applied"] = rw
    return rw, details


# ============================================================
# BASEL II STANDARDIZED (simplified)
# ============================================================
def get_standardized_risk_weight_basel2(
    exposure_type: Optional[ExposureType],
    rating_bucket: Optional[RatingBucket],
    is_regulatory_retail: bool,
    is_prudent_mortgage: bool,
) -> float:
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


# ============================================================
# IRB ASRF CORE (parameterized)
# ============================================================
def _calculate_irb_asrf(
    asset_class_key: str,
    asset_class_label: str,
    ead: float,
    pd: float,
    lgd: float,
    maturity_months: int,
    capital_ratio: float,
    approach_enum: Approach,
    *,
    pd_floors: Dict[str, float],
    lgd_defaults: Dict[str, float],
    scaling_factor: float,
    irb_mode: str,
    lgd_mode: str,  # "supervisory" or "bank_estimated"
    lgd_floors: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    pd_in = _normalize_rate(pd, default=0.01)
    pd_floor = pd_floors.get(asset_class_key, 0.0003)
    pd_used = max(pd_in, pd_floor)

    # Maturity in years (floor 1, cap 5; fallback 2.5)
    if maturity_months and maturity_months > 0:
        M = min(5.0, max(1.0, float(maturity_months) / 12.0))
    else:
        M = 2.5

    # LGD handling:
    # - Foundation: use supervisory LGD defaults
    # - Advanced: use provided LGD (bank-estimated); if missing/<=0, fall back to default AND apply LGD floor if configured
    lgd_default = lgd_defaults.get(asset_class_key, 0.45)

    lgd_floor_value = None
    lgd_floor_applied = False
    lgd_note = None

    if lgd_mode == "supervisory":
        lgd_used = float(lgd_default)
        lgd_source = "supervisory_default"
        lgd_note = f"Using supervisory default LGD={lgd_used:.4f}"
    else:
        # bank_estimated: normalize user-supplied lgd, but apply floor if configured
        lgd_in = _normalize_rate(lgd, default=lgd_default)
        if lgd_floors and asset_class_key in lgd_floors:
            lgd_floor_value = float(lgd_floors[asset_class_key])
            if lgd_in < lgd_floor_value:
                lgd_used = lgd_floor_value
                lgd_floor_applied = True
                lgd_note = f"Bank-estimated LGD {lgd_in:.4f} raised to floor {lgd_floor_value:.4f}"
            else:
                lgd_used = lgd_in
                lgd_note = f"Bank-estimated LGD used: {lgd_used:.4f} (no floor applied)"
        else:
            lgd_used = lgd_in
            lgd_note = f"Bank-estimated LGD used: {lgd_used:.4f} (no floor configured)"

        lgd_source = "bank_estimated" if (lgd is not None and float(lgd) > 0) else "default_used_missing_input"

    # Correlation (same functional form as existing prototype)
    exp_term = math.exp(-50.0 * pd_used)
    denom = 1.0 - math.exp(-50.0)
    denom = denom if denom != 0 else 1e-12
    R = 0.12 * (1.0 - exp_term) / denom + 0.24 * (1.0 - (1.0 - exp_term) / denom)

    b = (0.11852 - 0.05478 * math.log(max(pd_used, 1e-9))) ** 2

    term = (
        norm.ppf(pd_used) / math.sqrt(1.0 - R)
        + math.sqrt(R / (1.0 - R)) * norm.ppf(0.999)
    )

    K = lgd_used * norm.cdf(term) - pd_used * lgd_used
    maturity_adj = (1.0 + (M - 2.5) * b) / (1.0 - 1.5 * b)
    K_adj = K * maturity_adj

    rwa = 12.5 * scaling_factor * K_adj * ead
    capital_required = rwa * capital_ratio

    result = {
        "approach_enum": approach_enum.name,
        "approach_label": approach_enum.label,
        "irb_mode": irb_mode,
        "asset_class": asset_class_label,
        "pd_used": pd_used,
        "pd_floor_applied": pd_floor,
        "lgd_mode": lgd_mode,
        "lgd_used": lgd_used,
        "lgd_source": lgd_source,
        "lgd_default": lgd_default,
        "lgd_floor_applied": lgd_floor_applied,
        "lgd_floor_value": lgd_floor_value,
        "lgd_note": lgd_note,
        "maturity_years": M,
        "supervisory_correlation_R": R,
        "K_unadjusted": K,
        "maturity_adjustment_factor": maturity_adj,
        "K_adjusted": K_adj,
        "irb_scaling_factor": scaling_factor,
        "EAD": ead,
        "RWA": rwa,
        "effective_risk_weight_pct": f"{(rwa / ead) * 100:.2f}%" if ead and ead > 0 else None,
        "capital_ratio": capital_ratio,
        "capital_required": capital_required,
    }

    return result


def _calculate_irb_stub(
    approach_enum: Approach,
    ead: float,
    maturity_months: int,
    pd: float,
    lgd: float,
    capital_ratio: float,
) -> Dict[str, Any]:
    return {
        "approach_enum": approach_enum.name,
        "approach_label": approach_enum.label,
        "notes": "IRB stub — asset class not yet implemented.",
    }


# ============================================================
# Utilities: normalization & coercion
# ============================================================
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
            "commercial_real_estate": ExposureType.COMMERCIAL_REAL_ESTATE,
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
    if a is None:
        return None
    if isinstance(a, Approach):
        return a
    if isinstance(a, str):
        s = a.strip()
        value_map = {e.value: e for e in Approach}
        if s in value_map:
            return value_map[s]
        label_map = {e.label.lower(): e for e in Approach}
        if s.lower() in label_map:
            return label_map[s.lower()]

        s_low = s.lower()
        if "basel iii" in s_low and "standard" in s_low:
            return Approach.BASEL_III_STANDARDIZED
        if "basel iii" in s_low and "advanced" in s_low and "irb" in s_low:
            return Approach.BASEL_III_IRB_ADVANCED
        if "basel iii" in s_low and "irb" in s_low:
            return Approach.BASEL_III_IRB_FOUNDATION
        if "basel ii" in s_low and "standard" in s_low:
            return Approach.BASEL_II_STANDARDIZED
        if "irb" in s_low:
            return Approach.BASEL_II_IRB

    return None
