"""
format_output.py

Serializes a ranked provider list into the API response schema defined in the PRD.
Called by the API layer after rank_providers.py produces results.

This is a pure formatting module — no DB, no I/O, no network.
"""

from datetime import datetime, timezone
from typing import Any

DISCLAIMER = (
    "Cost estimates are based on negotiated rates and self-reported plan information. "
    "Actual patient responsibility may vary based on claims adjudication, provider billing "
    "practices, and plan-specific rules. This is not a guarantee of payment."
)


def format_response(
    ranked_providers: list[dict],
    query: dict,
    meta: dict | None = None,
) -> dict:
    """
    Wrap a ranked provider list in the full API response envelope.

    Args:
        ranked_providers: Output from rank_providers.rank_providers()
        query:            Original request parameters echoed back
        meta:             Optional metadata (latency, data freshness, etc.)

    Returns:
        API response dict, ready for json.dumps()
    """
    # Separate ranked from unverified
    ranked = [p for p in ranked_providers if p.get("rank") is not None]
    unverified = [p for p in ranked_providers if p.get("section") == "unverified"]

    ranking_basis = ranked[0].get("ranking_basis", "cost_only") if ranked else "cost_only"
    warnings = []

    # Surface quality suppression warning if present
    if ranking_basis == "cost_only":
        first = ranked[0] if ranked else None
        if first and first.get("warning"):
            warnings.append(first["warning"])

    if unverified:
        warnings.append(
            f"{len(unverified)} provider(s) excluded from ranking: rate data unavailable."
        )

    response = {
        "status": "ok",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "query": query,
        "ranking_basis": ranking_basis,
        "result_count": len(ranked),
        "results": [_format_provider(p) for p in ranked],
        "unverified_providers": [_format_unverified(p) for p in unverified],
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }

    if meta:
        response["meta"] = meta

    return response


def format_error(code: int, message: str, details: dict | None = None) -> dict:
    """Consistent error response envelope."""
    return {
        "status": "error",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }


def _format_provider(p: dict) -> dict:
    """Format a single ranked provider per PRD API response schema."""
    return {
        "npi": p.get("npi"),
        "provider_name": p.get("provider_name"),
        "specialty": p.get("specialty"),
        "address": _format_address(p),
        "distance_miles": p.get("distance_miles"),
        "cpt_code": p.get("cpt_code"),
        "procedure": p.get("procedure"),
        "negotiated_rate": p.get("negotiated_rate"),
        "estimated_oop": p.get("estimated_oop"),
        "quality_score": p.get("quality_score"),
        "quality_signals": p.get("quality_signals", {}),
        "rank": p.get("rank"),
        "ranking_basis": p.get("ranking_basis"),
        "notes": p.get("notes", []),
        "timeline": p.get("timeline"),
    }


def _format_unverified(p: dict) -> dict:
    return {
        "npi": p.get("npi"),
        "provider_name": p.get("provider_name"),
        "rate_unknown": True,
    }


def _format_address(p: dict) -> str:
    parts = filter(None, [
        p.get("address"),
        p.get("city"),
        p.get("state"),
        p.get("zip"),
    ])
    return ", ".join(parts)


def format_cpt_lookup(query: str, candidates: list[dict]) -> dict:
    """Format the /cpt-lookup response."""
    return {
        "status": "ok",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "query": query,
        "cpt_candidates": candidates,
    }


def format_timeline(result: Any) -> dict:
    """
    Serialize a CostTimelineResult dataclass to a JSON-serializable dict.

    Each timeline point includes:
      - months / label / date
      - cumulative_medical_oop, cumulative_premiums, cumulative_hsa_credits
      - net_out_of_pocket, deductible_remaining, oop_max_remaining
      - payment_plan_balance_remaining
      - breakdown: [{type, amount, label}] per cost variable

    Each event includes:
      - month / date
      - amount (positive = patient pays, negative = credit)
      - cost_variable_type (deductible | coinsurance | premium | hsa_contribution | payment_plan_installment)
      - label / cumulative_net

    Args:
        result: CostTimelineResult instance from compute_cost_timeline()

    Returns:
        Dict ready for JSON serialization and inclusion in provider API response.
    """
    def _d(date_val):
        return date_val.isoformat() if date_val else None

    return {
        "procedure_oop": result.procedure_oop,
        "payment_plan_monthly": result.payment_plan_monthly,
        "timeline_points": [
            {
                "months": tp.months,
                "label": tp.label,
                "date": _d(tp.date),
                "cumulative_medical_oop": tp.cumulative_medical_oop,
                "cumulative_premiums": tp.cumulative_premiums,
                "cumulative_hsa_credits": tp.cumulative_hsa_credits,
                "net_out_of_pocket": tp.net_out_of_pocket,
                "deductible_remaining": tp.deductible_remaining,
                "oop_max_remaining": tp.oop_max_remaining,
                "payment_plan_balance_remaining": tp.payment_plan_balance_remaining,
                "breakdown": tp.breakdown,
            }
            for tp in result.timeline_points
        ],
        "events": [
            {
                "month": ev.month,
                "date": _d(ev.date),
                "amount": ev.amount,
                "cost_variable_type": ev.cost_variable_type,
                "label": ev.label,
                "cumulative_net": ev.cumulative_net,
            }
            for ev in result.events
        ],
        "notes": result.notes,
    }
