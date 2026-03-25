"""
tests/test_rank_providers.py

Unit tests for the provider ranking engine.
Run: pytest tests/test_rank_providers.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from tools.rank_providers import ProviderRecord, RankRequest, rank_providers, _percentile_ranks


def make_provider(**kwargs) -> ProviderRecord:
    defaults = dict(
        npi="1234567890",
        provider_name="Dr. Test",
        specialty="Orthopedics",
        address="100 Main St",
        city="Chicago",
        state="IL",
        zip="60601",
        distance_miles=5.0,
        cpt_code="27447",
        procedure="Total knee arthroplasty",
        negotiated_rate=10000,
        estimated_oop=1000,
        quality_score=75,
        quality_signals={},
    )
    defaults.update(kwargs)
    return ProviderRecord(**defaults)


class TestRankRequest:

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match="equal 1.0"):
            RankRequest(cost_weight=0.8, quality_weight=0.8)

    def test_weights_must_be_non_negative(self):
        with pytest.raises(ValueError, match="non-negative"):
            RankRequest(cost_weight=-0.1, quality_weight=1.1)

    def test_valid_cost_only(self):
        req = RankRequest(cost_weight=1.0, quality_weight=0.0)
        assert req.cost_weight == 1.0

    def test_limit_bounds(self):
        with pytest.raises(ValueError):
            RankRequest(cost_weight=0.6, quality_weight=0.4, limit=0)
        with pytest.raises(ValueError):
            RankRequest(cost_weight=0.6, quality_weight=0.4, limit=101)


class TestPercentileRanks:

    def test_single_value(self):
        assert _percentile_ranks([42.0]) == [1.0]

    def test_lower_is_better(self):
        ranks = _percentile_ranks([10, 50, 100], lower_is_better=True)
        assert ranks[0] > ranks[1] > ranks[2]  # lowest value gets highest rank

    def test_higher_is_better(self):
        ranks = _percentile_ranks([10, 50, 100], lower_is_better=False)
        assert ranks[2] > ranks[1] > ranks[0]  # highest value gets highest rank

    def test_empty(self):
        assert _percentile_ranks([]) == []


class TestRankProviders:

    def _make_three(self):
        return [
            make_provider(npi="1111111111", estimated_oop=500, quality_score=90),
            make_provider(npi="2222222222", estimated_oop=1500, quality_score=80),
            make_provider(npi="3333333333", estimated_oop=2000, quality_score=40),
        ]

    def test_returns_sorted_by_rank(self):
        providers = self._make_three()
        req = RankRequest(cost_weight=0.6, quality_weight=0.4)
        results = rank_providers(providers, req)
        ranks = [r["rank"] for r in results if r.get("rank")]
        assert ranks == sorted(ranks)

    def test_rank_starts_at_one(self):
        providers = self._make_three()
        req = RankRequest(cost_weight=0.6, quality_weight=0.4)
        results = rank_providers(providers, req)
        ranked = [r for r in results if r.get("rank")]
        assert ranked[0]["rank"] == 1

    def test_limit_respected(self):
        providers = self._make_three()
        req = RankRequest(cost_weight=0.6, quality_weight=0.4, limit=2)
        results = rank_providers(providers, req)
        ranked = [r for r in results if r.get("rank")]
        assert len(ranked) == 2

    def test_cost_only_when_all_quality_null(self):
        providers = [
            make_provider(npi="1111111111", estimated_oop=500, quality_score=None),
            make_provider(npi="2222222222", estimated_oop=1500, quality_score=None),
        ]
        req = RankRequest(cost_weight=0.6, quality_weight=0.4)
        results = rank_providers(providers, req)
        ranked = [r for r in results if r.get("rank")]
        assert all(r["ranking_basis"] == "cost_only" for r in ranked)

    def test_cost_only_low_coverage(self):
        # Only 1 of 5 providers has quality → 20% < 40% threshold
        providers = [
            make_provider(npi=f"{i}" * 10, estimated_oop=1000 * i, quality_score=(90 if i == 1 else None))
            for i in range(1, 6)
        ]
        req = RankRequest(cost_weight=0.6, quality_weight=0.4)
        results = rank_providers(providers, req)
        ranked = [r for r in results if r.get("rank")]
        assert all(r["ranking_basis"] == "cost_only" for r in ranked)

    def test_rate_unknown_excluded_from_ranking(self):
        providers = [
            make_provider(npi="1111111111", estimated_oop=500, quality_score=90, rate_unknown=False),
            make_provider(npi="2222222222", estimated_oop=100, quality_score=95, rate_unknown=True),
        ]
        req = RankRequest(cost_weight=0.6, quality_weight=0.4)
        results = rank_providers(providers, req)
        ranked = [r for r in results if r.get("rank")]
        unverified = [r for r in results if r.get("section") == "unverified"]
        assert len(ranked) == 1
        assert ranked[0]["npi"] == "1111111111"
        assert len(unverified) == 1
        assert unverified[0]["npi"] == "2222222222"

    def test_empty_providers_returns_empty(self):
        req = RankRequest(cost_weight=0.6, quality_weight=0.4)
        results = rank_providers([], req)
        assert results == []

    def test_lowest_oop_ranks_first_cost_only(self):
        providers = [
            make_provider(npi="1111111111", estimated_oop=3000, quality_score=None),
            make_provider(npi="2222222222", estimated_oop=500, quality_score=None),
            make_provider(npi="3333333333", estimated_oop=1500, quality_score=None),
        ]
        req = RankRequest(cost_weight=1.0, quality_weight=0.0)
        results = rank_providers(providers, req)
        ranked = [r for r in results if r.get("rank")]
        # Lowest OOP should be rank 1
        assert ranked[0]["npi"] == "2222222222"
        assert ranked[0]["estimated_oop"] == 500
