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
   
## Roadmap (Retail excluded)

### Phase 1 — EAD/CCF baseline
- [ ] Implement compute_ead() module + ead_details audit output
- [ ] Wire UI inputs (CCF override) + results display
- [ ] Unit tests for LOC/LC/Term scenarios

### Phase 2 — Basel III IRB CRE
- [ ] Add CRE to IRB mapping (remove stub)
- [ ] Define CRE IRB treatment + cre_irb_details rule-path output
- [ ] Unit tests (CRE IRB vs standardized + output floor)

### Phase 3 — Jurisdiction parameter tables
- [ ] Centralize floors/thresholds/output floor settings
- [ ] Add param_set_version to outputs

### Phase 4 — A-IRB LGD estimation scaffolding
- [ ] Add LGD model hooks + governance placeholders

### Phase 5 — Governance & provenance
- [ ] run_metadata (timestamp, requested/effective approach, param versions)

### Phase 6 — UX/validation hardening
- [ ] Input validation + units/currency clarity
