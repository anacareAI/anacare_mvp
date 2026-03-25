"""
tests/test_compute_cost_timeline.py

Unit tests for the cost timeline calculation engine.
"""

from datetime import date

import pytest
from tools.compute_cost_timeline import (
    compute_cost_timeline,
    compute_dynamic_checkpoints,
    TimelineInput,
    CostTimelineResult,
    TimelinePoint,
    CostVariableType,
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _base_input(**overrides) -> TimelineInput:
    """Return a baseline TimelineInput with common defaults."""
    defaults = dict(
        negotiated_rate=5000.0,
        deductible_remaining=0.0,
        coinsurance_pct=0.20,
        oop_max_remaining=3000.0,
        monthly_premium=0.0,
        monthly_hsa_contribution=0.0,
        payment_plan_months=0,
        checkpoints=[3, 6, 12, 24],
    )
    defaults.update(overrides)
    return TimelineInput(**defaults)


def _point_at(result: CostTimelineResult, months: int) -> TimelinePoint:
    for pt in result.timeline_points:
        if pt.months == months:
            return pt
    raise KeyError(f"No timeline point found for month {months}")


# ── Deductible processing ────────────────────────────────────────────────────

def test_deductible_fully_met_no_ongoing_costs():
    """With deductible met and no premiums/HSA, all checkpoints show lump-sum OOP."""
    inp = _base_input(negotiated_rate=5000, deductible_remaining=0, coinsurance_pct=0.20)
    result = compute_cost_timeline(inp)
    assert result.procedure_oop == 1000.0  # 20% of 5000
    for pt in result.timeline_points:
        assert pt.cumulative_medical_oop == 1000.0
        assert pt.net_out_of_pocket == 1000.0


def test_partial_deductible_applied():
    """Partial deductible is paid first; coinsurance on remainder."""
    inp = _base_input(negotiated_rate=5000, deductible_remaining=300, coinsurance_pct=0.20)
    result = compute_cost_timeline(inp)
    expected_oop = 300 + 0.20 * 4700  # 300 + 940 = 1240
    assert abs(result.procedure_oop - expected_oop) < 0.01


def test_deductible_exceeds_rate():
    """When rate < deductible remaining, full rate goes to deductible; no coinsurance."""
    inp = _base_input(negotiated_rate=200, deductible_remaining=700, coinsurance_pct=0.20)
    result = compute_cost_timeline(inp)
    assert result.procedure_oop == 200.0
    pt = _point_at(result, 3)
    assert pt.cumulative_medical_oop == 200.0
    assert pt.deductible_remaining == 500.0  # 700 - 200


def test_deductible_remaining_tracked_at_checkpoints():
    """After procedure, deductible_remaining at each checkpoint reflects amount paid."""
    inp = _base_input(negotiated_rate=3000, deductible_remaining=1000, coinsurance_pct=0.20)
    result = compute_cost_timeline(inp)
    # All checkpoints should show same post-procedure deductible_remaining
    for pt in result.timeline_points:
        assert pt.deductible_remaining == 0.0  # 1000 fully consumed by 3000 rate


# ── Premiums ────────────────────────────────────────────────────────────────

def test_premiums_accumulate_over_time():
    """Monthly premiums compound correctly at each checkpoint."""
    inp = _base_input(
        negotiated_rate=1000,
        deductible_remaining=0,
        coinsurance_pct=0.0,
        monthly_premium=200.0,
    )
    result = compute_cost_timeline(inp)
    pt3 = _point_at(result, 3)
    pt6 = _point_at(result, 6)
    pt12 = _point_at(result, 12)
    pt24 = _point_at(result, 24)

    assert pt3.cumulative_premiums == pytest.approx(600.0)   # 3 months × $200
    assert pt6.cumulative_premiums == pytest.approx(1200.0)  # 6 months × $200
    assert pt12.cumulative_premiums == pytest.approx(2400.0) # 12 months × $200
    assert pt24.cumulative_premiums == pytest.approx(4800.0) # 24 months × $200


def test_premiums_added_to_net_oop():
    """Net OOP includes both medical cost and premiums."""
    inp = _base_input(
        negotiated_rate=1000,
        deductible_remaining=0,
        coinsurance_pct=0.0,
        monthly_premium=100.0,
    )
    result = compute_cost_timeline(inp)
    pt3 = _point_at(result, 3)
    # medical OOP = 0 (coinsurance is 0%), premiums = 300
    assert pt3.cumulative_medical_oop == 0.0
    assert pt3.cumulative_premiums == pytest.approx(300.0)
    assert pt3.net_out_of_pocket == pytest.approx(300.0)


# ── HSA contributions ────────────────────────────────────────────────────────

def test_hsa_reduces_net_oop():
    """HSA contributions reduce net out-of-pocket at each checkpoint."""
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
        monthly_hsa_contribution=100.0,
    )
    result = compute_cost_timeline(inp)
    pt12 = _point_at(result, 12)
    assert pt12.cumulative_hsa_credits == pytest.approx(1200.0)  # 12 × $100
    assert pt12.net_out_of_pocket == pytest.approx(1000.0 - 1200.0)  # OOP - HSA


def test_hsa_and_premiums_together():
    """HSA and premiums both factor into net OOP correctly."""
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
        monthly_premium=300.0,
        monthly_hsa_contribution=150.0,
    )
    result = compute_cost_timeline(inp)
    pt6 = _point_at(result, 6)
    expected_net = 1000.0 + (6 * 300.0) - (6 * 150.0)  # medical + premiums - HSA
    assert pt6.net_out_of_pocket == pytest.approx(expected_net)


def test_hsa_credits_listed_in_breakdown():
    """HSA credits appear with negative amount in breakdown."""
    inp = _base_input(
        negotiated_rate=1000,
        deductible_remaining=0,
        coinsurance_pct=0.0,
        monthly_hsa_contribution=50.0,
    )
    result = compute_cost_timeline(inp)
    pt3 = _point_at(result, 3)
    hsa_entry = next((b for b in pt3.breakdown if b["type"] == "hsa_credit"), None)
    assert hsa_entry is not None
    assert hsa_entry["amount"] < 0  # credits are negative


# ── Payment plans ────────────────────────────────────────────────────────────

def test_payment_plan_spreads_oop():
    """With a 12-month payment plan, OOP is distributed over 12 months."""
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,  # OOP = $1000
        payment_plan_months=12,
    )
    result = compute_cost_timeline(inp)
    assert result.procedure_oop == 1000.0
    assert result.payment_plan_monthly == pytest.approx(1000.0 / 12, abs=0.02)


def test_payment_plan_no_upfront_at_month_0():
    """With a payment plan, no lump-sum payment appears at month 0."""
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
        payment_plan_months=6,
    )
    result = compute_cost_timeline(inp)
    month_0_events = [e for e in result.events if e.month == 0]
    assert len(month_0_events) == 0


def test_payment_plan_balance_decreases_over_time():
    """Payment plan balance decreases at each checkpoint."""
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,  # OOP = $1000
        payment_plan_months=12,
    )
    result = compute_cost_timeline(inp)
    pt3 = _point_at(result, 3)
    pt6 = _point_at(result, 6)
    pt12 = _point_at(result, 12)

    assert pt3.payment_plan_balance_remaining > pt6.payment_plan_balance_remaining
    assert pt6.payment_plan_balance_remaining > 0
    assert pt12.payment_plan_balance_remaining == pytest.approx(0.0, abs=0.02)


def test_payment_plan_total_equals_procedure_oop():
    """Total of all payment plan installments equals procedure OOP."""
    inp = _base_input(
        negotiated_rate=6000,
        deductible_remaining=0,
        coinsurance_pct=0.20,  # OOP = $1200
        payment_plan_months=6,
        checkpoints=[6],
    )
    result = compute_cost_timeline(inp)
    installments = [e for e in result.events if e.cost_variable_type == CostVariableType.PAYMENT_PLAN_INSTALLMENT]
    total = sum(e.amount for e in installments)
    assert abs(total - result.procedure_oop) < 0.02  # rounding tolerance


# ── Events ───────────────────────────────────────────────────────────────────

def test_deductible_event_emitted_at_month_0():
    """When deductible is non-zero, a DEDUCTIBLE event is emitted at month 0."""
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=500,
        coinsurance_pct=0.20,
    )
    result = compute_cost_timeline(inp)
    ded_events = [e for e in result.events if e.cost_variable_type == CostVariableType.DEDUCTIBLE]
    assert len(ded_events) == 1
    assert ded_events[0].month == 0
    assert ded_events[0].amount == 500.0


def test_coinsurance_event_emitted_at_month_0():
    """When coinsurance is non-zero, a COINSURANCE event is emitted at month 0."""
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
    )
    result = compute_cost_timeline(inp)
    coin_events = [e for e in result.events if e.cost_variable_type == CostVariableType.COINSURANCE]
    assert len(coin_events) == 1
    assert coin_events[0].month == 0
    assert coin_events[0].amount == pytest.approx(1000.0)


def test_events_are_ordered_by_month():
    """All events in the events list are ordered by month ascending."""
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
        monthly_premium=200.0,
        monthly_hsa_contribution=100.0,
    )
    result = compute_cost_timeline(inp)
    months = [e.month for e in result.events]
    assert months == sorted(months)


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_preventive_care_zero_oop():
    """Preventive CPT code results in $0 OOP and no medical events."""
    inp = _base_input(
        negotiated_rate=3000,
        deductible_remaining=500,
        coinsurance_pct=0.20,
        cpt_code="45378",
    )
    result = compute_cost_timeline(inp)
    assert result.procedure_oop == 0.0
    for pt in result.timeline_points:
        assert pt.cumulative_medical_oop == 0.0
    assert any("ACA" in note or "preventive" in note.lower() for note in result.notes)


def test_no_premiums_no_hsa_basic():
    """Without ongoing costs, all checkpoints show same medical OOP."""
    inp = _base_input(
        negotiated_rate=2000,
        deductible_remaining=0,
        coinsurance_pct=0.10,  # OOP = $200
    )
    result = compute_cost_timeline(inp)
    for pt in result.timeline_points:
        assert pt.cumulative_medical_oop == pytest.approx(200.0)
        assert pt.cumulative_premiums == 0.0
        assert pt.cumulative_hsa_credits == 0.0
        assert pt.net_out_of_pocket == pytest.approx(200.0)


def test_custom_checkpoints():
    """Custom checkpoints generate timeline points at the specified months."""
    inp = _base_input(
        negotiated_rate=1000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
        checkpoints=[1, 2, 4],
    )
    result = compute_cost_timeline(inp)
    months = [pt.months for pt in result.timeline_points]
    assert months == [1, 2, 4]


def test_invalid_negative_premium_raises():
    inp = _base_input(monthly_premium=-50.0)
    with pytest.raises(ValueError, match="monthly_premium"):
        compute_cost_timeline(inp)


def test_invalid_negative_hsa_raises():
    inp = _base_input(monthly_hsa_contribution=-10.0)
    with pytest.raises(ValueError, match="monthly_hsa_contribution"):
        compute_cost_timeline(inp)


def test_invalid_negative_payment_plan_raises():
    inp = _base_input(payment_plan_months=-1)
    with pytest.raises(ValueError, match="payment_plan_months"):
        compute_cost_timeline(inp)


def test_empty_checkpoints_raises():
    inp = _base_input(checkpoints=[])
    with pytest.raises(ValueError, match="checkpoints"):
        compute_cost_timeline(inp)


def test_payment_plan_note_in_result():
    """A payment plan generates an explanatory note in the result."""
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
        payment_plan_months=6,
    )
    result = compute_cost_timeline(inp)
    assert any("installment" in note.lower() or "payment plan" in note.lower() for note in result.notes)


def test_hsa_note_in_result():
    """HSA contributions generate an explanatory note."""
    inp = _base_input(monthly_hsa_contribution=100.0)
    result = compute_cost_timeline(inp)
    assert any("hsa" in note.lower() for note in result.notes)


def test_zero_rate_no_events():
    """Zero negotiated rate generates no medical payment events."""
    inp = _base_input(negotiated_rate=0.0, coinsurance_pct=0.20)
    result = compute_cost_timeline(inp)
    assert result.procedure_oop == 0.0
    medical_events = [
        e for e in result.events
        if e.cost_variable_type in (CostVariableType.DEDUCTIBLE, CostVariableType.COINSURANCE)
    ]
    assert len(medical_events) == 0


# ── Date fields ───────────────────────────────────────────────────────────────

def test_events_have_no_date_without_procedure_date():
    """When procedure_date is not provided, all event dates are None."""
    inp = _base_input(negotiated_rate=5000, deductible_remaining=0, coinsurance_pct=0.20)
    result = compute_cost_timeline(inp)
    assert all(e.date is None for e in result.events)


def test_timeline_points_have_no_date_without_procedure_date():
    """When procedure_date is not provided, all timeline point dates are None."""
    inp = _base_input(negotiated_rate=5000, deductible_remaining=0, coinsurance_pct=0.20)
    result = compute_cost_timeline(inp)
    assert all(pt.date is None for pt in result.timeline_points)


def test_events_have_dates_when_procedure_date_provided():
    """When procedure_date is given, all events have a non-None date."""
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
        procedure_date=date(2026, 3, 1),
    )
    result = compute_cost_timeline(inp)
    assert len(result.events) > 0
    assert all(e.date is not None for e in result.events)


def test_event_at_month_0_matches_procedure_date():
    """Events at month 0 should have date equal to procedure_date."""
    proc_date = date(2026, 3, 15)
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
        procedure_date=proc_date,
    )
    result = compute_cost_timeline(inp)
    month_0_events = [e for e in result.events if e.month == 0]
    assert len(month_0_events) > 0
    for e in month_0_events:
        assert e.date == proc_date


def test_event_date_advances_by_month():
    """Events at month N should have date = procedure_date + N months."""
    proc_date = date(2026, 1, 1)
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
        monthly_premium=200.0,
        procedure_date=proc_date,
    )
    result = compute_cost_timeline(inp)
    for e in result.events:
        expected_date = date(2026 + (e.month // 12), ((0 + e.month) % 12) + 1, 1)
        assert e.date == expected_date


def test_timeline_points_have_dates_when_procedure_date_provided():
    """When procedure_date is given, all timeline points have a non-None date."""
    proc_date = date(2026, 3, 1)
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
        procedure_date=proc_date,
    )
    result = compute_cost_timeline(inp)
    assert all(pt.date is not None for pt in result.timeline_points)


def test_timeline_point_date_at_3_months():
    """Timeline point at month 3 should have date = procedure_date + 3 months."""
    proc_date = date(2026, 1, 15)
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
        procedure_date=proc_date,
        checkpoints=[3],
    )
    result = compute_cost_timeline(inp)
    pt = _point_at(result, 3)
    assert pt.date == date(2026, 4, 15)


def test_timeline_point_date_month_end_clamping():
    """Date arithmetic clamps to last day when target month is shorter."""
    # Jan 31 + 1 month = Feb 28 (non-leap year)
    proc_date = date(2026, 1, 31)
    inp = _base_input(
        negotiated_rate=5000,
        deductible_remaining=0,
        coinsurance_pct=0.20,
        procedure_date=proc_date,
        checkpoints=[1],
    )
    result = compute_cost_timeline(inp)
    pt = _point_at(result, 1)
    assert pt.date == date(2026, 2, 28)


# ── Dynamic checkpoint logic ──────────────────────────────────────────────────

class TestComputeDynamicCheckpoints:
    """Tests for compute_dynamic_checkpoints() standalone function."""

    def test_base_checkpoints_always_included(self):
        """3, 6, and 12 are always returned even with minimal inputs."""
        result = compute_dynamic_checkpoints(
            negotiated_rate=500,
            deductible_remaining=0,
            coinsurance_pct=0.10,
            oop_max_remaining=1000,
        )
        assert 3 in result
        assert 6 in result
        assert 12 in result

    def test_returns_sorted_list(self):
        """Returned checkpoints are always in ascending order."""
        result = compute_dynamic_checkpoints(
            negotiated_rate=5000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            oop_max_remaining=3000,
            payment_plan_months=18,
        )
        assert result == sorted(result)

    def test_no_duplicates(self):
        """Returned checkpoints contain no duplicate months."""
        result = compute_dynamic_checkpoints(
            negotiated_rate=5000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            oop_max_remaining=3000,
            payment_plan_months=12,  # same as base checkpoint
        )
        assert len(result) == len(set(result))

    def test_high_cost_includes_24_months(self):
        """OOP > $2000 triggers inclusion of month 24."""
        result = compute_dynamic_checkpoints(
            negotiated_rate=20000,
            deductible_remaining=0,
            coinsurance_pct=0.20,  # OOP = $4000 > $2000
            oop_max_remaining=5000,
        )
        assert 24 in result

    def test_low_cost_no_24_months_by_default(self):
        """Cheap procedure with no ongoing costs doesn't force month 24."""
        result = compute_dynamic_checkpoints(
            negotiated_rate=500,
            deductible_remaining=0,
            coinsurance_pct=0.10,  # OOP = $50
            oop_max_remaining=1000,
            monthly_premium=0,
        )
        assert 24 not in result

    def test_long_payment_plan_adds_completion_month(self):
        """Payment plan > 12 months adds the plan end month."""
        result = compute_dynamic_checkpoints(
            negotiated_rate=5000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            oop_max_remaining=3000,
            payment_plan_months=18,
        )
        assert 18 in result

    def test_short_payment_plan_not_added(self):
        """Payment plan <= 12 months is already covered by base checkpoints."""
        result = compute_dynamic_checkpoints(
            negotiated_rate=5000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            oop_max_remaining=3000,
            payment_plan_months=6,
        )
        # 6 is a base checkpoint already — no new month added beyond base+24
        assert 6 in result

    def test_hsa_breakeven_month_added(self):
        """HSA breakeven month (OOP / monthly_hsa) is included when in range."""
        # OOP = $1000 (5000 * 0.20), HSA = $200/mo → breakeven at month 5
        result = compute_dynamic_checkpoints(
            negotiated_rate=5000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            oop_max_remaining=3000,
            monthly_hsa_contribution=200.0,
        )
        assert 5 in result  # ceil(1000 / 200) = 5

    def test_hsa_breakeven_not_added_when_out_of_range(self):
        """HSA breakeven > 48 months is excluded."""
        # OOP = $1000, HSA = $10/mo → breakeven at month 100 (excluded)
        result = compute_dynamic_checkpoints(
            negotiated_rate=5000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            oop_max_remaining=3000,
            monthly_hsa_contribution=10.0,
        )
        assert 100 not in result

    def test_no_hsa_no_breakeven_checkpoint(self):
        """Without HSA contributions, no breakeven month is added."""
        result = compute_dynamic_checkpoints(
            negotiated_rate=5000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            oop_max_remaining=3000,
        )
        # Only standard + maybe 24 — no HSA-derived month
        for m in result:
            assert m in {3, 6, 12, 24}

    def test_all_positive_months(self):
        """All returned checkpoint months are > 0."""
        result = compute_dynamic_checkpoints(
            negotiated_rate=5000,
            deductible_remaining=500,
            coinsurance_pct=0.20,
            oop_max_remaining=3000,
            monthly_premium=300,
            monthly_hsa_contribution=150,
            payment_plan_months=24,
        )
        assert all(m > 0 for m in result)


class TestUseDynamicCheckpoints:
    """Tests for use_dynamic_checkpoints flag on TimelineInput."""

    def test_use_dynamic_overrides_checkpoints_field(self):
        """When use_dynamic_checkpoints=True, caller's checkpoints list is ignored."""
        # With $10000 * 20% = $2000 OOP and 18-month plan, dynamic should add 18 and 24
        inp = TimelineInput(
            negotiated_rate=10000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            oop_max_remaining=5000,
            payment_plan_months=18,
            checkpoints=[99],  # caller passes bogus checkpoint — should be ignored
            use_dynamic_checkpoints=True,
        )
        result = compute_cost_timeline(inp)
        months = [pt.months for pt in result.timeline_points]
        # Should NOT contain 99 (caller-supplied); should contain dynamic months
        assert 99 not in months
        assert 3 in months
        assert 18 in months

    def test_use_dynamic_false_respects_checkpoints_field(self):
        """When use_dynamic_checkpoints=False, caller's checkpoints are used as-is."""
        inp = _base_input(
            negotiated_rate=5000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            checkpoints=[1, 5, 9],
            use_dynamic_checkpoints=False,
        )
        result = compute_cost_timeline(inp)
        months = [pt.months for pt in result.timeline_points]
        assert months == [1, 5, 9]

    def test_dynamic_checkpoints_produce_valid_timeline_points(self):
        """Timeline computed with dynamic checkpoints has valid point structures."""
        inp = TimelineInput(
            negotiated_rate=8000,
            deductible_remaining=500,
            coinsurance_pct=0.20,
            oop_max_remaining=3000,
            monthly_premium=200,
            monthly_hsa_contribution=100,
            use_dynamic_checkpoints=True,
        )
        result = compute_cost_timeline(inp)
        assert len(result.timeline_points) >= 3
        for pt in result.timeline_points:
            assert pt.months > 0
            assert pt.net_out_of_pocket is not None
            assert isinstance(pt.breakdown, list)

    def test_dynamic_with_high_hsa_adds_breakeven(self):
        """Dynamic mode adds HSA breakeven month to timeline."""
        # OOP = $1000, HSA = $200/mo → breakeven at month 5
        inp = TimelineInput(
            negotiated_rate=5000,
            deductible_remaining=0,
            coinsurance_pct=0.20,
            oop_max_remaining=3000,
            monthly_hsa_contribution=200.0,
            use_dynamic_checkpoints=True,
        )
        result = compute_cost_timeline(inp)
        months = [pt.months for pt in result.timeline_points]
        assert 5 in months
