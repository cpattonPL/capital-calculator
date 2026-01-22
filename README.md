# Capital Calculator (prototype)

Prototype Streamlit app for regulatory capital calculations for loans and securitizations.
This repo is intended to house functionality to be used in validation of future builds.  It has functionality for:
Basel II and Basel III for both loans and securitizations.

## Quick start

1. Create a virtual env and install:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
2. Run the Streamlit app
   streamlit run app.py
   
## What have we actually built so far for Basel III IRB Foundation vs Advanced?

Here’s the inventory of what’s implemented today in code:

Basel III IRB Foundation (F-IRB)

Implemented for these exposure types:

✅ Corporate

✅ Bank

✅ Sovereign / Central Bank

What it does:

Uses ASRF core (correlation function + maturity adjustment + capital K → RWA)

Uses supervisory LGD defaults (not bank-estimated)

Applies Basel III PD floor (0.05%) for corporate/banks; no PD floor for sovereign

Applies Basel III output floor vs Basel III Standardized RWA

What it does not do yet:

❌ Specialized IRB treatment for retail / mortgages / CRE (IRB side)

❌ More sophisticated EAD/CCF (still the simple EAD=balance wiring)

Basel III IRB Advanced (A-IRB)

Implemented for:

✅ Corporate (bank-estimated LGD + PD floor + output floor + LGD floor logic)

✅ Sovereign / Central Bank (bank-estimated LGD permitted in code, but LGD floors not applied by rule; PD floors not applied)

⚠️ Bank: currently forced to supervisory LGD (Foundation-like) with an explicit note (so it runs, but it’s not a full A-IRB banks implementation)

New as of this update:

✅ LGD floors + rule path (jurisdiction-aware)

✅ Collateral-type selection (secured floor table used when provided)

Not yet built:

❌ IRB CRE (if you pick Exposure Type = CRE under IRB approaches, it currently hits the IRB stub)

❌ IRB segmentation for retail classes (QRRE, other retail, residential mortgages) and their distinct floors/models

CRE coverage specifically

✅ Basel III Standardized – CRE is implemented (LTV buckets + audit rule path)

❌ Basel III IRB – CRE is not implemented yet (currently stub)
