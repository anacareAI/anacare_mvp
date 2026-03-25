"""
compute_oop.py

Computes estimated out-of-pocket cost for a patient given:
  - negotiated_rate: rate from MRF
  - deductible_remaining: dollars left before deductible is met
  - coinsurance_pct: e.g. 0.20 for 20% coinsurance
  - oop_max_remaining: dollars left before OOP max is reached

This is the core OOP engine used by the ranking API.
It is a pure-Python module — no DB access, no I/O — for easy testing.

Usage (as a module):
    from tools.compute_oop import compute_oop, OOPResult

Usage (as a script for smoke testing):
    python tools/compute_oop.py
"""

from dataclasses import dataclass


@dataclass
class OOPResult:
    estimated_oop: float
    patient_pays_deductible: float   # portion applied to deductible
    patient_pays_coinsurance: float  # coinsurance portion after deductible
    oop_max_applied: bool            # True if OOP max capped the result
    note: str | None = None          # explanatory note for API response


# CPT codes that are typically $0 under ACA preventive care mandate
PREVENTIVE_CPT_CODES = {
    "99381", "99382", "99383", "99384", "99385", "99386", "99387",  # preventive visits
    "99391", "99392", "99393", "99394", "99395", "99396", "99397",
    "45378",  # colonoscopy (screening) — NOTE: therapeutic colonoscopies are NOT free
    "G0101", "G0102", "G0105", "G0120", "G0121",  # CMS preventive codes
}


def compute_oop(
    negotiated_rate: float,
    deductible_remaining: float,
    coinsurance_pct: float,
    oop_max_remaining: float,
    cpt_code: str = "",
    is_preventive: bool = False,
) -> OOPResult:
    """
    Calculate estimated patient out-of-pocket cost.

    Logic:
    1. If preventive care → $0 (ACA mandate)
    2. If deductible not yet met → patient pays min(negotiated_rate, deductible_remaining)
       toward deductible; then coinsurance on any remainder
    3. Coinsurance applies to (negotiated_rate - amount_applied_to_deductible)
    4. Total is capped at oop_max_remaining

    Args:
        negotiated_rate:      MRF negotiated rate in USD
        deductible_remaining: Dollars left until deductible is fully met (>= 0)
        coinsurance_pct:      Coinsurance rate, e.g. 0.20 for 20%
        oop_max_remaining:    Dollars left until OOP max is hit (>= 0)
        cpt_code:             CPT code string for preventive check
        is_preventive:        Caller-supplied override; skips CPT lookup if True

    Returns:
        OOPResult dataclass
    """
    if negotiated_rate < 0:
        raise ValueError(f"negotiated_rate must be >= 0, got {negotiated_rate}")
    if not (0.0 <= coinsurance_pct <= 1.0):
        raise ValueError(f"coinsurance_pct must be between 0 and 1, got {coinsurance_pct}")
    if deductible_remaining < 0:
        raise ValueError(f"deductible_remaining must be >= 0, got {deductible_remaining}")
    if oop_max_remaining < 0:
        raise ValueError(f"oop_max_remaining must be >= 0, got {oop_max_remaining}")

    # Step 1: Preventive care check
    if is_preventive or cpt_code in PREVENTIVE_CPT_CODES:
        return OOPResult(
            estimated_oop=0.0,
            patient_pays_deductible=0.0,
            patient_pays_coinsurance=0.0,
            oop_max_applied=False,
            note="Likely $0 — ACA preventive care mandate applies. Verify with plan.",
        )

    # Step 2: Deductible portion
    # Patient pays the lesser of the full rate or the remaining deductible
    deductible_portion = min(negotiated_rate, deductible_remaining)
    amount_after_deductible = negotiated_rate - deductible_portion

    # Step 3: Coinsurance on the remainder
    coinsurance_portion = coinsurance_pct * amount_after_deductible

    # Step 4: Total before OOP cap
    total = deductible_portion + coinsurance_portion

    # Step 5: Apply OOP max cap
    oop_max_applied = total > oop_max_remaining
    capped_total = min(total, oop_max_remaining)

    return OOPResult(
        estimated_oop=round(capped_total, 2),
        patient_pays_deductible=round(deductible_portion, 2),
        patient_pays_coinsurance=round(min(coinsurance_portion, oop_max_remaining - deductible_portion), 2),
        oop_max_applied=oop_max_applied,
        note="Out-of-pocket maximum applied." if oop_max_applied else None,
    )


def compute_oop_range(
    negotiated_rate: float,
    coinsurance_pct: float,
    oop_max_remaining: float,
    cpt_code: str = "",
) -> dict:
    """
    When deductible status is unknown, return best-case and worst-case OOP.

    Best case: deductible already met (deductible_remaining = 0)
    Worst case: patient pays entire rate up to deductible first
    """
    best = compute_oop(
        negotiated_rate=negotiated_rate,
        deductible_remaining=0.0,
        coinsurance_pct=coinsurance_pct,
        oop_max_remaining=oop_max_remaining,
        cpt_code=cpt_code,
    )
    worst = compute_oop(
        negotiated_rate=negotiated_rate,
        deductible_remaining=negotiated_rate,  # entire rate goes to deductible
        coinsurance_pct=coinsurance_pct,
        oop_max_remaining=oop_max_remaining,
        cpt_code=cpt_code,
    )
    return {
        "estimated_oop_best": best.estimated_oop,
        "estimated_oop_worst": worst.estimated_oop,
        "deductible_unknown": True,
    }


# ── Smoke tests ────────────────────────────────────────────────────────────────

def _run_smoke_tests():
    """Quick sanity checks; run with: python tools/compute_oop.py"""

    cases = [
        # (label, kwargs, expected_oop)
        (
            "Deductible fully met, 20% coinsurance, $5000 rate",
            dict(negotiated_rate=5000, deductible_remaining=0, coinsurance_pct=0.20, oop_max_remaining=2000),
            1000.0,
        ),
        (
            "Partial deductible ($300 left), 20% coinsurance, $5000 rate",
            dict(negotiated_rate=5000, deductible_remaining=300, coinsurance_pct=0.20, oop_max_remaining=2000),
            round(300 + 0.20 * 4700, 2),
        ),
        (
            "OOP max cap applies",
            dict(negotiated_rate=50000, deductible_remaining=0, coinsurance_pct=0.20, oop_max_remaining=1500),
            1500.0,
        ),
        (
            "Preventive care (colonoscopy screening)",
            dict(negotiated_rate=3000, deductible_remaining=500, coinsurance_pct=0.20, oop_max_remaining=2000, cpt_code="45378"),
            0.0,
        ),
        (
            "Deductible exceeds rate (patient pays full rate to deductible)",
            dict(negotiated_rate=200, deductible_remaining=700, coinsurance_pct=0.20, oop_max_remaining=2000),
            200.0,
        ),
    ]

    passed = 0
    failed = 0
    for label, kwargs, expected in cases:
        result = compute_oop(**kwargs)
        status = "PASS" if abs(result.estimated_oop - expected) < 0.01 else "FAIL"
        if status == "PASS":
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {label}")
        if status == "FAIL":
            print(f"       expected={expected}, got={result.estimated_oop}")

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = _run_smoke_tests()
    import sys
    sys.exit(0 if success else 1)
