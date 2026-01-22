# calculators/loans.py
"""
Loan calculation module

This version includes:
- Jurisdiction-aware Basel III IRB input floors (PD and LGD) using Basel/OSFI text.
- Configurable "BCBS baseline floors" option for jurisdictions that have not adopted Basel III final.
- Collateral-type aware secured LGD floors for Basel III IRB Advanced when floors are enabled.
- Collateral type is always accepted as an input and carried through outputs for future EAD/mitigation work.
- LGD audit outputs (lgd_used + floor/rule notes) similar to CRE rule-path details.
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


# ============================================================
# Basel III / OSFI / Basel Framework input floors
# ============================================================

# Basel/OSFI PD floor: 0.05% for all exposures except sovereign asset class
PD_FLOOR_BASEL3_GENERAL = 0.0005  # 0.05%

# Retail PD minimums (not fully wired into IRB retail classes yet)
PD_FLOOR_RETAIL_OTHER = 0.0005        # 0.05%
PD_FLOOR_RETAIL_QRRE_REVOLVER = 0.0010  # 0.10%


# Basel/OSFI LGD floors
# NOTE:
# - These floors depend on secured/unsecured and collateral type.
# - Our UI provides collateral_type; we use it for A-IRB floor selection when floors are enabled.
LGD_FLOORS_BASEL_WHOLESALE = {
    "unsecured": 0.25,  # 25%
    "secured_by_collateral_type": {
        "financial": 0.00,
        "receivables": 0.10,
        "real_estate": 0.10,      # commercial or residential real estate
        "other_physical": 0.15,
        "intangibles": 0.25,
    },
}

LGD_FLOORS_BASEL_RETAIL = {
    "qrre": 0.50,
    "residential_mortgage": 0.10,
    "other_retail_unsecured": 0.30,
    "other_retail_secured_by_collateral_type": {
        "financial": 0.00,
        "receivables": 0.10,
        "real_estate": 0.10,
        "other_physical": 0.15,
    },
}

JURISDICTION = {
    "CAN": "CAN",
    "US": "US",
}

FLOOR_REGIME = {
    "NONE": "NONE",
    "BCBS": "BCBS",
    "OSFI": "OSFI",
}


# ----------------------------
# Supervisory LGD defaults for F-IRB (prototype defaults)
# ----------------------------
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
    # Jurisdiction/floors
    jurisdiction: str = "US",                  # "US" or "CAN"
    apply_bcbs_baseline_floors: bool = False,  # for US/non-adopting jurisdictions
    # Collateral typing (always accepted; used for A-IRB floors now, and later EAD/mitigation)
    collateral_type: Optional[str] = None,     # "financial", "receivables", "real_estate", "other_physical", "intangibles", or None
    # CRE-specific optional parameters
    property_value: Optional[float] = None,
    property_income_dependent: bool = False,
    counterparty_type: Optional[Union[ExposureType, str]] = None,
) -> Dict[str, Any]:
    approach_enum = _coerce_approach(approach)
    et_enum = _coerce_exposure_type(exposure_type)
    rb_enum = _coerce_rating_bucket(rating_bucket)
    cp_enum = _coerce_exposure_type(counterparty_type) if counterparty_type is not None else ExposureType.CORPORATE

    jurisdiction_norm = (jurisdiction or "US").strip().upper()
    if jurisdiction_norm not in (JURISDICTION["US"], JURISDICTION["CAN"]):
        jurisdiction_norm = JURISDICTION["US"]

    # Determine which floor regime to use for Basel III IRB input floors
    if jurisdiction_norm == JURISDICTION["CAN"]:
        floor_regime = FLOOR_REGIME["OSFI"]
    else:
        floor_regime = FLOOR_REGIME["BCBS"] if apply_bcbs_baseline_floors else FLOOR_REGIME["NONE"]

    # Normalize collateral_type (None or canonical string)
    collateral_type_norm = _normalize_collateral_type(collateral_type)

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
            "jurisdiction": jurisdiction_norm,
            "floor_regime": floor_regime,
            "exposure_type_enum": (et_enum.name if et_enum else None),
            "rating_bucket_enum": (rb_enum.name if rb_enum else None),
            "collateral_type": collateral_type_norm,  # carry through for future mitigation/EAD
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
    # IRB
    # =========================
    if approach_enum.method == "irb":
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
            scaling_factor = 1.0

            pd_floors = {
                "corporate": PD_FLOOR_BASEL3_GENERAL,
                "bank": PD_FLOOR_BASEL3_GENERAL,
                "sovereign": 0.0,  # PD floors do not apply to sovereign asset class
            }

            if approach_enum == Approach.BASEL_III_IRB_ADVANCED:
                irb_mode = "Basel III IRB - Advanced"

                # Conservative limitation: do not apply A-IRB own-LGD to banks in this implementation.
                if asset_class_key == "bank":
                    lgd_mode = "supervisory"
                    lgd_defaults = LGD_DEFAULTS_BASEL3_FIRB
                    lgd_floor_policy = {
                        "enabled": False,
                        "floor_value": None,
                        "floor_source": floor_regime,
                        "rule_path": "A-IRB own-LGD not applied to bank exposures in this implementation → supervisory LGD default used",
                        "inputs": {"collateral_type": collateral_type_norm},
                    }
                else:
                    lgd_mode = "bank_estimated"
                    lgd_defaults = LGD_DEFAULTS_BASEL3_FIRB
                    lgd_floor_policy = _get_basel3_lgd_floor_policy(
                        floor_regime=floor_regime,
                        asset_class_key=asset_class_key,
                        collateral_type=collateral_type_norm,
                    )
            else:
                irb_mode = "Basel III IRB - Foundation"
                lgd_mode = "supervisory"
                lgd_defaults = LGD_DEFAULTS_BASEL3_FIRB
                lgd_floor_policy = {
                    "enabled": False,
                    "floor_value": None,
                    "floor_source": floor_regime,
                    "rule_path": "Foundation uses supervisory LGD defaults",
                    "inputs": {"collateral_type": collateral_type_norm},
                }

        else:
            # Basel II IRB Foundation (existing prototype behavior)
            scaling_factor = SCALING_FACTOR_BASEL2_IRB
            irb_mode = "Basel II IRB - Foundation"
            pd_floors = {
                "corporate": 0.0003,
                "bank": 0.0005,
                "sovereign": 0.0005,
            }
            lgd_mode = "supervisory"
            lgd_defaults = LGD_DEFAULTS_BASEL2_FIRB
            lgd_floor_policy = {
                "enabled": False,
                "floor_value": None,
                "floor_source": "N/A",
                "rule_path": "Basel II IRB floors not changed here",
                "inputs": {"collateral_type": collateral_type_norm},
            }

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
            lgd_floor_policy=lgd_floor_policy,
            jurisdiction=jurisdiction_norm,
            floor_regime=floor_regime,
            collateral_type=collateral_type_norm,
        )

        if not apply_output_floor:
            return irb_result

        # Basel III Output Floor:
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
# Floor policy helpers
# ============================================================
def _get_basel3_lgd_floor_policy(
    *,
    floor_regime: str,
    asset_class_key: str,
    collateral_type: Optional[str],
) -> Dict[str, Any]:
    """
    Collateral types supported:
      financial, receivables, real_estate, other_physical, intangibles

    If collateral_type is None/empty, uses the unsecured wholesale floor (25%).
    """
    if asset_class_key == "sovereign":
        return {
            "enabled": False,
            "floor_value": None,
            "floor_source": floor_regime,
            "rule_path": "Basel III IRB: LGD parameter floors do not apply to sovereign asset class",
            "inputs": {"collateral_type": collateral_type},
        }

    if floor_regime == FLOOR_REGIME["NONE"]:
        return {
            "enabled": False,
            "floor_value": None,
            "floor_source": floor_regime,
            "rule_path": "No Basel III-final LGD floors applied (floor regime configured as NONE)",
            "inputs": {"collateral_type": collateral_type},
        }

    # Secured floors by collateral type (if provided and recognized)
    if collateral_type:
        secured_map = LGD_FLOORS_BASEL_WHOLESALE["secured_by_collateral_type"]
        if collateral_type in secured_map:
            floor_val = float(secured_map[collateral_type])
            return {
                "enabled": True,
                "floor_value": floor_val,
                "floor_source": floor_regime,
                "rule_path": f"Basel III IRB LGD floor (wholesale secured): collateral_type='{collateral_type}' → floor={floor_val:.4f}",
                "inputs": {"collateral_type": collateral_type},
            }

        # Unknown collateral type → fall back to unsecured floor
        return {
            "enabled": True,
            "floor_value": float(LGD_FLOORS_BASEL_WHOLESALE["unsecured"]),
            "floor_source": floor_regime,
            "rule_path": f"Basel III IRB LGD floor: unknown collateral_type='{collateral_type}' → fallback to unsecured floor=25%",
            "inputs": {"collateral_type": collateral_type},
        }

    # Default to unsecured wholesale floor
    return {
        "enabled": True,
        "floor_value": float(LGD_FLOORS_BASEL_WHOLESALE["unsecured"]),
        "floor_source": floor_regime,
        "rule_path": "Basel III IRB LGD floor (wholesale unsecured default): floor=25% (no collateral_type provided)",
        "inputs": {"collateral_type": collateral_type},
    }


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
# IRB ASRF CORE
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
    lgd_mode: str,
    lgd_floor_policy: Dict[str, Any],
    jurisdiction: str,
    floor_regime: str,
    collateral_type: Optional[str],
) -> Dict[str, Any]:
    pd_in = _normalize_rate(pd, default=0.01)

    pd_floor = float(pd_floors.get(asset_class_key, 0.0))
    if pd_floor <= 0.0:
        pd_used = pd_in
        pd_note = "No PD floor applied for this asset class"
    else:
        pd_used = max(pd_in, pd_floor)
        pd_note = f"PD used = max(PD input {pd_in:.6f}, PD floor {pd_floor:.6f})"

    if maturity_months and maturity_months > 0:
        M = min(5.0, max(1.0, float(maturity_months) / 12.0))
    else:
        M = 2.5

    lgd_default = float(lgd_defaults.get(asset_class_key, 0.45))

    lgd_floor_applied = False
    lgd_floor_value = None
    lgd_note = None
    lgd_rule_path = None

    if lgd_mode == "supervisory":
        lgd_used = lgd_default
        lgd_source = "supervisory_default"
        lgd_note = f"Using supervisory default LGD={lgd_used:.4f}"
        lgd_rule_path = "Supervisory LGD default (Foundation or constrained exposure type)"
    else:
        lgd_in = _normalize_rate(lgd, default=lgd_default)
        lgd_used = lgd_in
        lgd_source = "bank_estimated" if (lgd is not None and float(lgd) > 0) else "default_used_missing_input"

        if lgd_floor_policy.get("enabled") and lgd_floor_policy.get("floor_value") is not None:
            lgd_floor_value = float(lgd_floor_policy["floor_value"])
            lgd_rule_path = lgd_floor_policy.get("rule_path")

            if lgd_used < lgd_floor_value:
                lgd_used = lgd_floor_value
                lgd_floor_applied = True
                lgd_note = f"Bank-estimated LGD {lgd_in:.4f} raised to floor {lgd_floor_value:.4f}"
            else:
                lgd_note = f"Bank-estimated LGD used: {lgd_used:.4f} (>= floor {lgd_floor_value:.4f})"
        else:
            lgd_rule_path = lgd_floor_policy.get("rule_path") or "No LGD floor applied"
            lgd_note = f"Bank-estimated LGD used: {lgd_used:.4f} (no floor applied)"

    exp_term = math.exp(-50.0 * max(pd_used, 1e-12))
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

    return {
        "approach_enum": approach_enum.name,
        "approach_label": approach_enum.label,
        "irb_mode": irb_mode,
        "asset_class": asset_class_label,
        "jurisdiction": jurisdiction,
        "floor_regime": floor_regime,
        "collateral_type": collateral_type,

        "pd_input": pd_in,
        "pd_used": pd_used,
        "pd_floor": pd_floor if pd_floor > 0 else None,
        "pd_note": pd_note,

        "lgd_input": _normalize_rate(lgd, default=lgd_default),
        "lgd_mode": lgd_mode,
        "lgd_used": lgd_used,
        "lgd_source": lgd_source,
        "lgd_default": lgd_default,
        "lgd_floor_applied": lgd_floor_applied,
        "lgd_floor_value": lgd_floor_value,
        "lgd_note": lgd_note,
        "lgd_rule_path": lgd_rule_path,
        "lgd_floor_policy": lgd_floor_policy,

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
# Utilities
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


def _normalize_collateral_type(collateral_type: Optional[str]) -> Optional[str]:
    if collateral_type is None:
        return None
    s = str(collateral_type).strip().lower()
    if s in ("", "none", "unsecured", "n/a"):
        return None
    # Allowed set used for secured-floor mapping; we keep unknown strings for audit trail.
    allowed = {"financial", "receivables", "real_estate", "other_physical", "intangibles"}
    return s if s in allowed else s


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
