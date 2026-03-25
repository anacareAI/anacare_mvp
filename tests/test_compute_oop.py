"""
tests/test_compute_oop.py

Unit tests for the OOP calculation engine.
Run: pytest tests/test_compute_oop.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from tools.compute_oop import compute_oop, compute_oop_range, OOPResult


class TestComputeOop:

    def test_deductible_fully_met(self):
        result = compute_oop(
            negotiated_rate=5000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            oop_max_remaining=2000,
        )
        assert result.estimated_oop == 1000.0
        assert result.patient_pays_deductible == 0.0
        assert result.patient_pays_coinsurance == 1000.0
        assert not result.oop_max_applied

    def test_partial_deductible(self):
        result = compute_oop(
            negotiated_rate=5000,
            deductible_remaining=300,
            coinsurance_pct=0.20,
            oop_max_remaining=2000,
        )
        # Patient pays $300 to deductible + 20% of remaining $4700 = $940
        assert result.patient_pays_deductible == 300.0
        assert result.estimated_oop == round(300 + 0.20 * 4700, 2)
        assert not result.oop_max_applied

    def test_oop_max_applied(self):
        result = compute_oop(
            negotiated_rate=50000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            oop_max_remaining=1500,
        )
        assert result.estimated_oop == 1500.0
        assert result.oop_max_applied

    def test_preventive_cpt_code(self):
        # 45378 = screening colonoscopy → $0 ACA preventive
        result = compute_oop(
            negotiated_rate=3000,
            deductible_remaining=500,
            coinsurance_pct=0.20,
            oop_max_remaining=2000,
            cpt_code="45378",
        )
        assert result.estimated_oop == 0.0
        assert "ACA" in (result.note or "")

    def test_is_preventive_flag(self):
        result = compute_oop(
            negotiated_rate=1000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            oop_max_remaining=5000,
            is_preventive=True,
        )
        assert result.estimated_oop == 0.0

    def test_deductible_exceeds_rate(self):
        # Rate $200 < deductible remaining $700 → patient pays full rate
        result = compute_oop(
            negotiated_rate=200,
            deductible_remaining=700,
            coinsurance_pct=0.20,
            oop_max_remaining=2000,
        )
        assert result.estimated_oop == 200.0
        assert result.patient_pays_deductible == 200.0
        assert result.patient_pays_coinsurance == 0.0

    def test_zero_coinsurance(self):
        result = compute_oop(
            negotiated_rate=10000,
            deductible_remaining=0,
            coinsurance_pct=0.0,
            oop_max_remaining=5000,
        )
        assert result.estimated_oop == 0.0

    def test_full_coinsurance(self):
        result = compute_oop(
            negotiated_rate=1000,
            deductible_remaining=0,
            coinsurance_pct=1.0,
            oop_max_remaining=5000,
        )
        assert result.estimated_oop == 1000.0

    def test_invalid_coinsurance_raises(self):
        with pytest.raises(ValueError, match="coinsurance_pct"):
            compute_oop(5000, 0, 1.5, 2000)

    def test_invalid_negative_rate_raises(self):
        with pytest.raises(ValueError, match="negotiated_rate"):
            compute_oop(-1, 0, 0.20, 2000)

    def test_invalid_negative_deductible_raises(self):
        with pytest.raises(ValueError, match="deductible_remaining"):
            compute_oop(5000, -100, 0.20, 2000)

    def test_invalid_negative_oop_max_raises(self):
        with pytest.raises(ValueError, match="oop_max_remaining"):
            compute_oop(5000, 0, 0.20, -1)


class TestComputeOopRange:

    def test_range_best_is_lower(self):
        result = compute_oop_range(
            negotiated_rate=5000,
            coinsurance_pct=0.20,
            oop_max_remaining=2000,
        )
        assert result["estimated_oop_best"] <= result["estimated_oop_worst"]
        assert result["deductible_unknown"] is True

    def test_range_preventive_both_zero(self):
        result = compute_oop_range(
            negotiated_rate=3000,
            coinsurance_pct=0.20,
            oop_max_remaining=2000,
            cpt_code="45378",
        )
        assert result["estimated_oop_best"] == 0.0
        assert result["estimated_oop_worst"] == 0.0
