"""
rank_providers.py

Core ranking logic for the /rank-providers endpoint.
Pure Python — no DB access. Accepts a list of enriched provider records
(rate + quality + location already attached) and returns a sorted list.

This module is called by the API layer (api/main.py) after DB data is fetched.

Usage (as a module):
    from tools.rank_providers import rank_providers, RankRequest

Usage (smoke test):
    python tools/rank_providers.py
"""

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderRecord:
    """Input record for ranking. All cost/quality data already resolved."""
    npi: str
    provider_name: str
    specialty: str
    address: str
    city: str
    state: str
    zip: str
    distance_miles: float
    cpt_code: str
    procedure: str
    negotiated_rate: float
    estimated_oop: float
    quality_score: Optional[float]  # 0-100 or None
    quality_signals: dict = field(default_factory=dict)
    rate_unknown: bool = False


@dataclass
class RankRequest:
    cost_weight: float = 0.6
    quality_weight: float = 0.4
    limit: int = 10

    def __post_init__(self):
        if abs((self.cost_weight + self.quality_weight) - 1.0) > 0.001:
            raise ValueError(
                f"cost_weight + quality_weight must equal 1.0, "
                f"got {self.cost_weight} + {self.quality_weight} = {self.cost_weight + self.quality_weight}"
            )
        if self.cost_weight < 0 or self.quality_weight < 0:
            raise ValueError("Weights must be non-negative")
        if self.limit < 1 or self.limit > 100:
            raise ValueError("limit must be between 1 and 100")


def _percentile_ranks(values: list[float], lower_is_better: bool = True) -> list[float]:
    """
    Convert a list of values to percentile ranks in [0, 1].
    lower_is_better=True → lower value gets rank closer to 1.0 (better).
    Returns ranks in the same order as input values.
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [1.0]

    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * n

    for rank_pos, (original_idx, _) in enumerate(indexed):
        percentile = rank_pos / (n - 1)  # 0.0 → worst rank position, 1.0 → best
        if lower_is_better:
            ranks[original_idx] = 1.0 - percentile  # flip: lower value → higher rank
        else:
            ranks[original_idx] = percentile
    return ranks


def rank_providers(
    providers: list[ProviderRecord],
    request: RankRequest,
) -> list[dict]:
    """
    Rank providers by composite cost + quality score.

    Steps:
    1. Filter out providers with unknown rates
    2. Check quality coverage (<40% → cost_only)
    3. Compute percentile ranks on OOP cost and quality score
    4. Compute composite rank_score
    5. Sort ascending by rank_score (lower = better)
    6. Attach rank ordinal and metadata
    7. Return top N per limit
    """
    # Step 1: Filter rate_unknown providers
    unknown = [p for p in providers if p.rate_unknown]
    known = [p for p in providers if not p.rate_unknown]

    if not known:
        return []

    # Step 2: Quality coverage check
    providers_with_quality = [p for p in known if p.quality_score is not None]
    quality_coverage = len(providers_with_quality) / len(known)
    use_quality = quality_coverage >= 0.40 and request.quality_weight > 0

    if use_quality:
        ranking_basis = "cost_and_quality"
    else:
        ranking_basis = "cost_only"

    # Step 3a: Cost percentile ranks (lower OOP = better)
    oop_values = [p.estimated_oop for p in known]
    cost_ranks = _percentile_ranks(oop_values, lower_is_better=True)

    # Step 3b: Quality percentile ranks (higher score = better)
    if use_quality:
        quality_values = [
            p.quality_score if p.quality_score is not None else 0.0
            for p in known
        ]
        quality_ranks = _percentile_ranks(quality_values, lower_is_better=False)
    else:
        quality_ranks = [0.0] * len(known)

    # Step 4: Composite score
    effective_cost_weight = 1.0 if not use_quality else request.cost_weight
    effective_quality_weight = 0.0 if not use_quality else request.quality_weight

    results = []
    for i, provider in enumerate(known):
        composite = (
            effective_cost_weight * cost_ranks[i]
            + effective_quality_weight * quality_ranks[i]
        )
        results.append((composite, i, provider))

    # Step 5: Sort descending (higher composite = better rank)
    results.sort(key=lambda x: x[0], reverse=True)

    # Step 6: Build output
    output = []
    for rank_ordinal, (composite_score, _, provider) in enumerate(results[:request.limit], 1):
        notes = []
        if use_quality and provider.quality_score is not None:
            if quality_ranks[known.index(provider)] >= 0.9:
                notes.append("Top 10% outcomes in region")
        # Volume note
        vol = provider.quality_signals.get("procedure_volume")
        if vol and vol >= 100:
            notes.append(f"High volume ({vol} procedures)")

        record = {
            "npi": provider.npi,
            "provider_name": provider.provider_name,
            "specialty": provider.specialty,
            "address": provider.address,
            "city": provider.city,
            "state": provider.state,
            "zip": provider.zip,
            "distance_miles": provider.distance_miles,
            "cpt_code": provider.cpt_code,
            "procedure": provider.procedure,
            "negotiated_rate": round(provider.negotiated_rate, 2),
            "estimated_oop": round(provider.estimated_oop, 2),
            "quality_score": provider.quality_score,
            "quality_signals": provider.quality_signals,
            "rank": rank_ordinal,
            "composite_score": round(composite_score, 4),
            "ranking_basis": ranking_basis,
            "notes": notes,
        }

        if not use_quality and quality_coverage < 0.40:
            record["warning"] = (
                f"Quality data covers only {quality_coverage * 100:.0f}% of providers "
                "in this region. Ranking by cost only."
            )

        output.append(record)

    # Append unresolved rate providers in a separate section
    for provider in unknown:
        output.append({
            "npi": provider.npi,
            "provider_name": provider.provider_name,
            "rate_unknown": True,
            "rank": None,
            "section": "unverified",
        })

    return output


# ── Smoke tests ────────────────────────────────────────────────────────────────

def _run_smoke_tests():
    providers = [
        ProviderRecord(
            npi="1111111111", provider_name="Dr. Alice", specialty="Orthopedics",
            address="100 Main St", city="Chicago", state="IL", zip="60601",
            distance_miles=2.0, cpt_code="27447", procedure="Total knee arthroplasty",
            negotiated_rate=18000, estimated_oop=1200, quality_score=87,
            quality_signals={"procedure_volume": 312},
        ),
        ProviderRecord(
            npi="2222222222", provider_name="Dr. Bob", specialty="Orthopedics",
            address="200 Oak Ave", city="Chicago", state="IL", zip="60605",
            distance_miles=5.1, cpt_code="27447", procedure="Total knee arthroplasty",
            negotiated_rate=22000, estimated_oop=1800, quality_score=62,
            quality_signals={"procedure_volume": 80},
        ),
        ProviderRecord(
            npi="3333333333", provider_name="Dr. Carol", specialty="Orthopedics",
            address="300 Elm Blvd", city="Chicago", state="IL", zip="60610",
            distance_miles=8.3, cpt_code="27447", procedure="Total knee arthroplasty",
            negotiated_rate=15000, estimated_oop=900, quality_score=45,
            quality_signals={},
        ),
    ]

    req = RankRequest(cost_weight=0.6, quality_weight=0.4, limit=10)
    results = rank_providers(providers, req)

    print(f"Ranked {len(results)} providers:")
    for r in results:
        print(f"  #{r['rank']} {r['provider_name']} | OOP=${r['estimated_oop']} | "
              f"Quality={r['quality_score']} | Composite={r['composite_score']}")

    assert results[0]["rank"] == 1
    assert len(results) == 3

    # Test weight validation
    try:
        RankRequest(cost_weight=0.8, quality_weight=0.8)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

    print("\nAll smoke tests passed.")
    return True


if __name__ == "__main__":
    _run_smoke_tests()
