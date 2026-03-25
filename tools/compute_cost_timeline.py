"""
compute_cost_timeline.py

Computes a cost timeline showing WHEN and HOW MUCH a patient will pay over time,
projecting out at 3, 6, 12, and 24 month intervals.

Accounts for:
  - Procedure OOP (deductible + coinsurance, from compute_oop)
  - Monthly insurance premiums
  - Monthly HSA contributions (reduce net cost)
  - Payment plan option (split procedure OOP over N months)

This is a pure-Python module — no DB access, no I/O — for easy testing.

Usage:
    from tools.compute_cost_timeline import compute_cost_timeline, TimelineInput
"""

import calendar
from dataclasses import dataclass, field
from datetime import date as DateType
from enum import Enum
from typing import List, Optional

from tools.compute_oop import compute_oop


def compute_dynamic_checkpoints(
    negotiated_rate: float,
    deductible_remaining: float,
    coinsurance_pct: float,
    oop_max_remaining: float,
    monthly_premium: float = 0.0,
    monthly_hsa_contribution: float = 0.0,
    payment_plan_months: int = 0,
    cpt_code: str = "",
    is_preventive: bool = False,
) -> List[int]:
    """
    Determine optimal timeline checkpoint months based on procedure costs and plan structure.

    Logic:
    - Base checkpoints: 3, 6, 12
    - Include payment_plan_months if > 0 and > 12 (marks when plan is fully paid off)
    - Add month 24 if: procedure OOP > $2000, payment plan extends past 12 months,
      or monthly costs make 24-month view meaningful
    - Add HSA breakeven month if monthly_hsa > 0 and procedure OOP > 0:
      the month when cumulative HSA credits offset the full procedure OOP
      (only if 1 <= breakeven <= 48 and not already a standard checkpoint)

    Returns:
        Sorted list of unique checkpoint months (all > 0)
    """
    from math import ceil

    checkpoints: set[int] = {3, 6, 12}

    # Compute procedure OOP to drive cost-based decisions
    procedure_oop = 0.0
    if not is_preventive:
        from tools.compute_oop import compute_oop
        try:
            oop_result = compute_oop(
                negotiated_rate=negotiated_rate,
                deductible_remaining=deductible_remaining,
                coinsurance_pct=coinsurance_pct,
                oop_max_remaining=oop_max_remaining,
                cpt_code=cpt_code,
                is_preventive=is_preventive,
            )
            procedure_oop = oop_result.estimated_oop
        except Exception:
            procedure_oop = 0.0

    # Add payment plan completion month if it extends beyond month 12
    if payment_plan_months > 0 and payment_plan_months > 12:
        checkpoints.add(payment_plan_months)

    # Add month 24 for high-cost procedures, extended payment plans, or meaningful ongoing costs
    monthly_net = monthly_premium - monthly_hsa_contribution
    if procedure_oop > 2000 or payment_plan_months > 12 or (monthly_net > 0 and monthly_net * 24 > 500):
        checkpoints.add(24)

    # Add HSA breakeven month: when cumulative HSA credits cover the full procedure OOP
    if monthly_hsa_contribution > 0 and procedure_oop > 0:
        breakeven_month = ceil(procedure_oop / monthly_hsa_contribution)
        if 1 <= breakeven_month <= 48:
            checkpoints.add(breakeven_month)

    return sorted(checkpoints)


def _add_months(d: DateType, months: int) -> DateType:
    """Add a number of months to a date, clamping to the last day of the target month."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return DateType(year, month, day)


class CostVariableType(str, Enum):
    DEDUCTIBLE = "deductible"
    COINSURANCE = "coinsurance"
    PREMIUM = "premium"
    HSA_CONTRIBUTION = "hsa_contribution"
    PAYMENT_PLAN_INSTALLMENT = "payment_plan_installment"


@dataclass
class TimelineEvent:
    """A single payment event in the timeline."""
    month: int                          # months from procedure date (0 = procedure month)
    amount: float                       # positive = patient pays, negative = credit
    cost_variable_type: CostVariableType
    label: str
    cumulative_net: float               # running net out-of-pocket after this event
    date: Optional[DateType] = None     # actual calendar date, populated when procedure_date is provided


@dataclass
class TimelinePoint:
    """Snapshot of cumulative costs at a given checkpoint month."""
    months: int
    label: str                          # "3 months", "6 months", etc.
    cumulative_medical_oop: float       # deductible + coinsurance paid to date
    cumulative_premiums: float          # total premiums paid to date
    cumulative_hsa_credits: float       # total HSA contributions received to date
    net_out_of_pocket: float            # medical_oop + premiums - hsa_credits
    deductible_remaining: float         # after procedure
    oop_max_remaining: float            # after procedure
    payment_plan_balance_remaining: float  # unpaid installments remaining
    breakdown: List[dict]               # [{type, amount, label}]
    date: Optional[DateType] = None     # actual calendar date, populated when procedure_date is provided


@dataclass
class TimelineInput:
    """All inputs needed to compute a cost timeline."""
    # Procedure cost parameters
    negotiated_rate: float
    deductible_remaining: float
    coinsurance_pct: float
    oop_max_remaining: float

    # Ongoing monthly costs (optional)
    monthly_premium: float = 0.0
    monthly_hsa_contribution: float = 0.0  # reduces net cost

    # Payment plan: split procedure OOP over N months (0 = lump sum at procedure)
    payment_plan_months: int = 0

    # Procedure metadata (optional, for preventive check)
    cpt_code: str = ""
    is_preventive: bool = False

    # If provided, TimelineEvent.date and TimelinePoint.date will be populated
    # with actual calendar dates derived from procedure_date + month offset.
    procedure_date: Optional[DateType] = None

    # Checkpoint months to generate snapshots for
    checkpoints: List[int] = field(default_factory=lambda: [3, 6, 12, 24])

    # When True, ignore `checkpoints` and auto-compute optimal intervals based on
    # procedure costs and insurance plan structure via compute_dynamic_checkpoints().
    use_dynamic_checkpoints: bool = False


@dataclass
class CostTimelineResult:
    """Full timeline result including events and checkpoint snapshots."""
    procedure_oop: float                # immediate OOP from OOP engine
    payment_plan_monthly: float         # monthly installment (0 if no payment plan)
    timeline_points: List[TimelinePoint]
    events: List[TimelineEvent]
    notes: List[str]


def compute_cost_timeline(inp: TimelineInput) -> CostTimelineResult:
    """
    Compute a payment timeline for a patient given procedure and plan parameters.

    Steps:
    1. Calculate procedure OOP using compute_oop engine
    2. Build monthly event stream (procedure payment, premiums, HSA)
    3. Aggregate cumulative totals at each checkpoint month
    4. Return structured timeline result

    Args:
        inp: TimelineInput dataclass with all required parameters

    Returns:
        CostTimelineResult with timeline_points at each checkpoint
    """
    # --- Resolve checkpoints (dynamic or caller-provided) ---
    if inp.use_dynamic_checkpoints:
        resolved_checkpoints = compute_dynamic_checkpoints(
            negotiated_rate=inp.negotiated_rate,
            deductible_remaining=inp.deductible_remaining,
            coinsurance_pct=inp.coinsurance_pct,
            oop_max_remaining=inp.oop_max_remaining,
            monthly_premium=inp.monthly_premium,
            monthly_hsa_contribution=inp.monthly_hsa_contribution,
            payment_plan_months=inp.payment_plan_months,
            cpt_code=inp.cpt_code,
            is_preventive=inp.is_preventive,
        )
    else:
        resolved_checkpoints = inp.checkpoints

    # Override inp with resolved checkpoints for the rest of the calculation.
    # We use a local variable rather than mutating inp.
    inp = TimelineInput(
        negotiated_rate=inp.negotiated_rate,
        deductible_remaining=inp.deductible_remaining,
        coinsurance_pct=inp.coinsurance_pct,
        oop_max_remaining=inp.oop_max_remaining,
        monthly_premium=inp.monthly_premium,
        monthly_hsa_contribution=inp.monthly_hsa_contribution,
        payment_plan_months=inp.payment_plan_months,
        cpt_code=inp.cpt_code,
        is_preventive=inp.is_preventive,
        procedure_date=inp.procedure_date,
        checkpoints=resolved_checkpoints,
        use_dynamic_checkpoints=False,  # already resolved
    )

    # --- Validate inputs ---
    if inp.monthly_premium < 0:
        raise ValueError(f"monthly_premium must be >= 0, got {inp.monthly_premium}")
    if inp.monthly_hsa_contribution < 0:
        raise ValueError(f"monthly_hsa_contribution must be >= 0, got {inp.monthly_hsa_contribution}")
    if inp.payment_plan_months < 0:
        raise ValueError(f"payment_plan_months must be >= 0, got {inp.payment_plan_months}")
    if not inp.checkpoints:
        raise ValueError("checkpoints must be a non-empty list")
    if any(c <= 0 for c in inp.checkpoints):
        raise ValueError("all checkpoints must be > 0")

    # --- Step 1: Compute procedure OOP ---
    oop_result = compute_oop(
        negotiated_rate=inp.negotiated_rate,
        deductible_remaining=inp.deductible_remaining,
        coinsurance_pct=inp.coinsurance_pct,
        oop_max_remaining=inp.oop_max_remaining,
        cpt_code=inp.cpt_code,
        is_preventive=inp.is_preventive,
    )

    procedure_oop = oop_result.estimated_oop
    deductible_after = max(0.0, inp.deductible_remaining - oop_result.patient_pays_deductible)
    oop_max_after = max(0.0, inp.oop_max_remaining - procedure_oop)

    # --- Step 2: Payment plan calculation ---
    payment_plan_monthly = 0.0
    if inp.payment_plan_months > 0 and procedure_oop > 0:
        payment_plan_monthly = round(procedure_oop / inp.payment_plan_months, 2)
        # Adjust last payment for rounding differences
        total_installments = payment_plan_monthly * inp.payment_plan_months
        rounding_diff = round(procedure_oop - total_installments, 2)
    else:
        rounding_diff = 0.0

    # --- Step 3: Build month-by-month arrays ---
    max_checkpoint = max(inp.checkpoints)

    # monthly_medical[m] = medical OOP payment in month m
    monthly_medical = [0.0] * (max_checkpoint + 1)
    monthly_premiums = [0.0] * (max_checkpoint + 1)
    monthly_hsa = [0.0] * (max_checkpoint + 1)

    if inp.payment_plan_months > 0 and procedure_oop > 0:
        # Spread OOP payments over months 1..payment_plan_months
        for m in range(1, min(inp.payment_plan_months, max_checkpoint) + 1):
            monthly_medical[m] = payment_plan_monthly
        # Add rounding difference to last installment (if within range)
        last_month = min(inp.payment_plan_months, max_checkpoint)
        monthly_medical[last_month] = round(monthly_medical[last_month] + rounding_diff, 2)
    else:
        # Lump sum at month 0 (procedure month), split by component
        monthly_medical[0] = procedure_oop

    # Premiums and HSA from month 1 onward
    for m in range(1, max_checkpoint + 1):
        monthly_premiums[m] = inp.monthly_premium
        monthly_hsa[m] = inp.monthly_hsa_contribution

    # --- Step 4: Build events list ---
    events: List[TimelineEvent] = []
    cumulative_net = 0.0
    cumulative_medical = 0.0

    for m in range(max_checkpoint + 1):
        event_date = _add_months(inp.procedure_date, m) if inp.procedure_date else None

        # Medical OOP event
        if monthly_medical[m] > 0:
            if m == 0 and inp.payment_plan_months == 0:
                # Lump sum: emit deductible and coinsurance as separate events
                if oop_result.patient_pays_deductible > 0:
                    cumulative_net += oop_result.patient_pays_deductible
                    cumulative_medical += oop_result.patient_pays_deductible
                    events.append(TimelineEvent(
                        month=0,
                        amount=oop_result.patient_pays_deductible,
                        cost_variable_type=CostVariableType.DEDUCTIBLE,
                        label="Deductible payment at procedure",
                        cumulative_net=round(cumulative_net, 2),
                        date=event_date,
                    ))
                if oop_result.patient_pays_coinsurance > 0:
                    cumulative_net += oop_result.patient_pays_coinsurance
                    cumulative_medical += oop_result.patient_pays_coinsurance
                    events.append(TimelineEvent(
                        month=0,
                        amount=oop_result.patient_pays_coinsurance,
                        cost_variable_type=CostVariableType.COINSURANCE,
                        label="Coinsurance payment at procedure",
                        cumulative_net=round(cumulative_net, 2),
                        date=event_date,
                    ))
            elif m > 0 and inp.payment_plan_months > 0:
                # Payment plan installment
                cumulative_net += monthly_medical[m]
                cumulative_medical += monthly_medical[m]
                events.append(TimelineEvent(
                    month=m,
                    amount=monthly_medical[m],
                    cost_variable_type=CostVariableType.PAYMENT_PLAN_INSTALLMENT,
                    label=f"Payment plan installment {m}/{inp.payment_plan_months}",
                    cumulative_net=round(cumulative_net, 2),
                    date=event_date,
                ))

        # Premium event
        if monthly_premiums[m] > 0:
            cumulative_net += monthly_premiums[m]
            events.append(TimelineEvent(
                month=m,
                amount=monthly_premiums[m],
                cost_variable_type=CostVariableType.PREMIUM,
                label=f"Month {m} premium",
                cumulative_net=round(cumulative_net, 2),
                date=event_date,
            ))

        # HSA event (credit — reduces net cost)
        if monthly_hsa[m] > 0:
            cumulative_net -= monthly_hsa[m]
            events.append(TimelineEvent(
                month=m,
                amount=-monthly_hsa[m],
                cost_variable_type=CostVariableType.HSA_CONTRIBUTION,
                label=f"Month {m} HSA contribution",
                cumulative_net=round(cumulative_net, 2),
                date=event_date,
            ))

    # --- Step 5: Build timeline points at checkpoints ---
    checkpoint_label_map = {3: "3 months", 6: "6 months", 12: "12 months", 24: "2 years"}
    timeline_points: List[TimelinePoint] = []

    for cp in sorted(inp.checkpoints):
        if cp > max_checkpoint:
            continue

        cp_medical = sum(monthly_medical[: cp + 1])
        cp_premiums = sum(monthly_premiums[: cp + 1])
        cp_hsa = sum(monthly_hsa[: cp + 1])
        cp_net = cp_medical + cp_premiums - cp_hsa

        # Payment plan balance remaining
        if inp.payment_plan_months > 0 and procedure_oop > 0:
            payments_made = min(cp, inp.payment_plan_months)
            plan_balance = max(0.0, procedure_oop - payments_made * payment_plan_monthly)
            # Adjust for rounding diff (last payment may differ slightly)
            if cp >= inp.payment_plan_months:
                plan_balance = 0.0
        else:
            plan_balance = 0.0

        breakdown = []
        if cp_medical > 0:
            breakdown.append({
                "type": "medical_oop",
                "amount": round(cp_medical, 2),
                "label": "Medical out-of-pocket",
            })
        if cp_premiums > 0:
            breakdown.append({
                "type": "premium",
                "amount": round(cp_premiums, 2),
                "label": "Insurance premiums",
            })
        if cp_hsa > 0:
            breakdown.append({
                "type": "hsa_credit",
                "amount": round(-cp_hsa, 2),
                "label": "HSA contributions (credit)",
            })

        timeline_points.append(TimelinePoint(
            months=cp,
            label=checkpoint_label_map.get(cp, f"{cp} months"),
            cumulative_medical_oop=round(cp_medical, 2),
            cumulative_premiums=round(cp_premiums, 2),
            cumulative_hsa_credits=round(cp_hsa, 2),
            net_out_of_pocket=round(cp_net, 2),
            deductible_remaining=round(deductible_after, 2),
            oop_max_remaining=round(oop_max_after, 2),
            payment_plan_balance_remaining=round(plan_balance, 2),
            breakdown=breakdown,
            date=_add_months(inp.procedure_date, cp) if inp.procedure_date else None,
        ))

    # --- Build notes ---
    notes: List[str] = []
    if oop_result.note:
        notes.append(oop_result.note)
    if inp.payment_plan_months > 0 and procedure_oop > 0:
        notes.append(
            f"Procedure cost of ${procedure_oop:.2f} split into "
            f"{inp.payment_plan_months} monthly installments of ${payment_plan_monthly:.2f}."
        )
    if inp.monthly_hsa_contribution > 0:
        notes.append(
            f"HSA contributions of ${inp.monthly_hsa_contribution:.2f}/month reduce net cost."
        )

    return CostTimelineResult(
        procedure_oop=procedure_oop,
        payment_plan_monthly=round(payment_plan_monthly, 2),
        timeline_points=timeline_points,
        events=events,
        notes=notes,
    )
