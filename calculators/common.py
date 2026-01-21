import numpy as np

def compute_ead(commitment: float, balance: float, loan_type: str, utilization_pct: float) -> float:
    """
    Compute Exposure at Default (EAD).
    """
    if loan_type.lower() == "term":
        return float(balance)
    elif loan_type.lower() == "loc":
        return float(balance + (commitment - balance) * (utilization_pct / 100.0))
    elif loan_type.lower() == "lc":
        return float(balance + (commitment - balance) * 0.75)
    else:
        return float(balance)

def format_currency(x):
    return f"${x:,.2f}"
