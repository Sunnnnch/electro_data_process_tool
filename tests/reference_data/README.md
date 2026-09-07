# Electrochemical Numerical Reference Suite

`electrochem_reference_v1.json` contains small analytical cases for the five
built-in processing families. The values are intentionally simple enough to
verify from the documented equations:

- LSV: current-density normalization, target-current potential, Tafel slope,
  overpotential, and manual iR compensation.
- CV: charge integration at a constant scan rate and full-cycle detection.
- EIS: an ideal `Rs + (Rct || Cdl)` Randles circuit.
- ECSA: linear `DeltaJ` versus scan-rate fitting, `Cdl`, roughness factor, and
  geometric ECSA.
- FE: Faradaic efficiency, mole selectivity, and FE-share selectivity.

## Formula Basis

The reference values use the same physical definitions documented in run
reports, but are calculated independently of the production implementation:

```text
j (mA/cm2) = I (A) * 1000 / A_geo (cm2)
E_iR (V) = E_measured - (j / 1000) * A_geo * Rs
eta (mV) = abs(E_target - E_equilibrium) * 1000
E = intercept + b * log10(j); Tafel slope = b * 1000 mV/dec

dt = abs(dE) / scan_rate
Q_CV (mC) = integral abs(I_mA) dt

Z = Rs + Rct / (1 + i * 2*pi*f*Rct*Cdl)

DeltaJ = slope * scan_rate + intercept
Cdl = slope / 2
RF = Cdl / Cs
ECSA = RF * A_geo

FE_i (%) = n_i * F * amount_i / Q * 100
mole selectivity_i (%) = amount_i / sum(amount) * 100
FE-share selectivity_i (%) = FE_i / sum(FE) * 100
```

## Maintenance Rules

1. Do not regenerate expected values with the production function under test.
2. Derive changed values independently from the formula and record the reason
   in the commit that changes this file.
3. Increase `schema_version` when a definition, unit, or interpretation changes.
4. Add a new case instead of weakening a tolerance to hide an algorithm change.
5. Keep units explicit in every key and use only deterministic input values.

Run only this suite with:

```powershell
python -m pytest -q tests/test_v6_numerical_reference.py
```
