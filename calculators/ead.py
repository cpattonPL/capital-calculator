# calculators/ead.py
"""
EAD / CCF calculation utilities (Phase 1 baseline)

compute_ead(...) returns:
- ead: float
- ead_details: dict with drawn, undrawn, ccf_used, product_ccf, ead_calc_path

Default product CCFs (baseline prototype):
- Term loan: undrawn CCF = 0.0 (i.e., no undrawn conversion)
- LOC (revolver): undrawn CCF = 0.75 (75%)
- LC (letters of credit): undrawn CCF = 1.0 (100%)

Notes:
- This is intentionally simple and modular so we can later swap in a more
  sophisticated Basel EAD/CCF function without touching the rest of the
  capital calculation plumbing.
"""

from typing import Dict, Optional, Tuple

DEFAULT_PRODUCT_CCF = {
    "TERM": 0.0,
    "LOC": 0.75,
    "LC": 1.0,
}


def compute_ead(
    *,
    loan_type: str,
    commitment: float,
    balance: float,
    utilization_pct: Optional[float] = None,
    # optional override for undrawn CCF (a single scalar applied to undrawn portion)
    undrawn_ccf_override: Optional[float] = None,
    # optional map to override defaults by product
    product_ccf_overrides: Optional[Dict[str, float]] = None,
) -> Tuple[float, Dict]:
    """
    Compute EAD (prototype) using simple CCF logic.

    Args:
        loan_type: "Term", "LOC", or "LC" (case-insensitive)
        commitment: authorized amount available to borrower
        balance: current drawn amount
        utilization_pct: optional; if provided and loan_type != "Term", used to derive balance if balance==0
        undrawn_ccf_override: if provided (0.0..1.0), used instead of the product default for undrawn portion
        product_ccf_overrides: optional dict e.g. {"LOC": 0.7}

    Returns:
        (ead, ead_details)
    """

    lt = (loan_type or "TERM").strip().upper()

    # sanitize inputs
    try:
        commitment_val = float(commitment or 0.0)
    except Exception:
        commitment_val = 0.0
    try:
        balance_val = float(balance or 0.0)
    except Exception:
        balance_val = 0.0

    # if balance is zero and utilization provided for non-term, derive balance
    if balance_val <= 0.0 and utilization_pct is not None and lt != "TERM":
        try:
            util = float(utilization_pct)
            balance_val = commitment_val * util
        except Exception:
            pass

    # product CCF selection (capacity to override via product_ccf_overrides)
    product_ccf_map = DEFAULT_PRODUCT_CCF.copy()
    if product_ccf_overrides:
        for k, v in product_ccf_overrides.items():
            if isinstance(k, str) and v is not None:
                product_ccf_map[k.strip().upper()] = float(v)

    default_undrawn_ccf = float(product_ccf_map.get(lt, 0.0))

    # undrawn CCF selection: override beats product default
    undrawn_ccf = (
        float(undrawn_ccf_override)
        if (undrawn_ccf_override is not None and undrawn_ccf_override >= 0.0)
        else default_undrawn_ccf
    )

    # calculate drawn & undrawn portions
    drawn = max(0.0, min(balance_val, commitment_val))
    undrawn = max(0.0, commitment_val - drawn)

    # EAD = drawn + undrawn * undrawn_ccf
    ead = drawn + undrawn * undrawn_ccf

    ead_details = {
        "loan_type": lt,
        "commitment": commitment_val,
        "balance_drawn": drawn,
        "undrawn_commitment": undrawn,
        "product_undrawn_ccf_default": default_undrawn_ccf,
        "undrawn_ccf_used": undrawn_ccf,
        "undrawn_ccf_override": undrawn_ccf_override,
        "product_ccf_overrides": product_ccf_overrides or {},
        "ead": ead,
        "ead_calc_path": f"EAD = drawn ({drawn}) + undrawn ({undrawn}) * undrawn_ccf ({undrawn_ccf})",
    }

    return float(ead), ead_details
