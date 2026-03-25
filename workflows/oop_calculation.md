# Workflow: OOP Calculation Engine (M2)

**Objective:** Compute estimated patient out-of-pocket cost given a negotiated rate and caller-supplied plan parameters. No PHI stored — all inputs are per-request.

**Milestone:** M2 — OOP Engine

---

## How It Works

The OOP engine is a pure-Python module (`tools/compute_oop.py`) called by the API layer at query time. No DB access, no network calls.

### Formula

```
Step 1: If preventive CPT → OOP = $0 (ACA mandate)
Step 2: deductible_portion = min(negotiated_rate, deductible_remaining)
Step 3: coinsurance_portion = coinsurance_pct × (negotiated_rate − deductible_portion)
Step 4: total = deductible_portion + coinsurance_portion
Step 5: OOP = min(total, oop_max_remaining)
```

### Edge Cases Handled

| Scenario | Behavior |
|---|---|
| Deductible fully met (`deductible_remaining = 0`) | Patient pays coinsurance only |
| Deductible exceeds rate | Patient pays full rate toward deductible, $0 coinsurance |
| OOP max capped | `oop_max_applied: true` in response |
| Preventive CPT code | Returns `estimated_oop: 0`, note citing ACA mandate |
| `deductible_unknown: true` | Returns `estimated_oop_best` + `estimated_oop_worst` range |
| `deductible_remaining` not provided | API returns HTTP 400 (required field) |

---

## Running Smoke Tests

```bash
python tools/compute_oop.py
# Expected: 5 passed, 0 failed
```

---

## Running Full Unit Test Suite

```bash
pytest tests/test_compute_oop.py -v
# Expected: 14 passed
```

---

## Preventive Care CPT Codes

The engine flags these CPT codes as likely $0 under the ACA preventive care mandate:
- 99381-99387, 99391-99397 (preventive E&M visits)
- 45378 (screening colonoscopy — NOTE: therapeutic colonoscopies are NOT covered)
- G0101, G0102, G0105, G0120, G0121 (CMS preventive codes)

The API response includes a note: "Likely $0 — ACA preventive care mandate applies. Verify with plan."

**Important:** The caller or patient should always verify with their specific plan. ACA preventive coverage applies to in-network providers only. Some grandfathered plans may not cover all preventive services.

---

## Accuracy Target

Per PRD: OOP estimate within ±20% of actual EOB for 80% of cases (v1, self-reported plan data).

The primary source of inaccuracy in v1:
1. Deductible status is self-reported — patient may not know exact accumulator
2. MRF rate may not match the actual allowed amount post-adjudication
3. Facility fees are not included in MRF rates (facility_fee_warning flag)

These are addressed in v2 via employer claims feed integration (M8).

---

## API Input/Output

**Input (per /rank-providers request):**
```json
{
  "deductible_remaining": 700,
  "coinsurance_pct": 0.20,
  "oop_max_remaining": 2300,
  "deductible_unknown": false
}
```

**OOP calculation output (embedded in each ranked provider):**
```json
{
  "negotiated_rate": 18400.00,
  "estimated_oop": 1200.00
}
```

**Or when `deductible_unknown: true`:**
```json
{
  "estimated_oop_best": 800.00,
  "estimated_oop_worst": 2300.00,
  "deductible_unknown": true
}
```
