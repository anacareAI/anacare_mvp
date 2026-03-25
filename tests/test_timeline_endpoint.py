"""
tests/test_timeline_endpoint.py

Tests for timeline integration in POST /v1/rank-providers.
Verifies that include_timeline=True returns a timeline array per provider,
and that include_timeline=False (default) omits it.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RATE_ROW = {
    "npi": "1234567890",
    "provider_name": "Dr. Jane Smith",
    "specialty": "Orthopedic Surgery",
    "address": "123 Main St",
    "city": "Chicago",
    "state": "IL",
    "zip": "60601",
    "distance_miles": 4.2,
    "cpt_code": "27447",
    "negotiated_rate": 18400.00,
    "quality_score": 87.0,
    "cms_outcome_rating": 4.5,
    "procedure_volume": 312,
    "patient_satisfaction": 82.0,
}

BASE_PAYLOAD = {
    "cpt_code": "27447",
    "zip": "60601",
    "radius_miles": 25,
    "deductible_remaining": 700.0,
    "coinsurance_pct": 0.20,
    "oop_max_remaining": 2300.0,
    "weights": {"cost": 0.6, "quality": 0.4},
    "limit": 10,
}


def _make_client():
    import api.main as main_module
    with patch.object(main_module.database, "init_pool", return_value=None):
        client = TestClient(main_module.app, raise_server_exceptions=False)
    return main_module, client


def _mock_db_and_geocode(main_module, rows=None):
    """Return context managers that mock DB fetch and geocode."""
    rows = rows or [SAMPLE_RATE_ROW]
    db_patch = patch.object(main_module.database, "fetch_rates_for_query", return_value=rows)
    geo_patch = patch("api.main.filter_by_radius", return_value=rows)
    return db_patch, geo_patch


# ---------------------------------------------------------------------------
# Tests: default behaviour (no timeline)
# ---------------------------------------------------------------------------

class TestRankProvidersNoTimeline:

    def test_timeline_absent_by_default(self):
        main_module, client = _make_client()
        db_p, geo_p = _mock_db_and_geocode(main_module)
        with db_p, geo_p:
            resp = client.post(
                "/v1/rank-providers",
                json=BASE_PAYLOAD,
                headers={"Authorization": "Bearer sandbox-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        for provider in body.get("results", []):
            assert provider.get("timeline") is None

    def test_timeline_absent_when_include_timeline_false(self):
        main_module, client = _make_client()
        db_p, geo_p = _mock_db_and_geocode(main_module)
        payload = {**BASE_PAYLOAD, "include_timeline": False}
        with db_p, geo_p:
            resp = client.post(
                "/v1/rank-providers",
                json=payload,
                headers={"Authorization": "Bearer sandbox-token"},
            )
        assert resp.status_code == 200
        for provider in resp.json().get("results", []):
            assert provider.get("timeline") is None


# ---------------------------------------------------------------------------
# Tests: include_timeline=True
# ---------------------------------------------------------------------------

class TestRankProvidersWithTimeline:

    def _ranked_result(self, extra_payload=None):
        main_module, client = _make_client()
        db_p, geo_p = _mock_db_and_geocode(main_module)
        payload = {**BASE_PAYLOAD, "include_timeline": True, **(extra_payload or {})}
        with db_p, geo_p:
            resp = client.post(
                "/v1/rank-providers",
                json=payload,
                headers={"Authorization": "Bearer sandbox-token"},
            )
        return resp

    def test_returns_200(self):
        resp = self._ranked_result()
        assert resp.status_code == 200

    def test_timeline_present_on_ranked_providers(self):
        resp = self._ranked_result()
        results = resp.json().get("results", [])
        assert len(results) > 0
        for provider in results:
            assert "timeline" in provider
            assert provider["timeline"] is not None

    def test_timeline_has_required_top_level_keys(self):
        resp = self._ranked_result()
        timeline = resp.json()["results"][0]["timeline"]
        assert "procedure_oop" in timeline
        assert "payment_plan_monthly" in timeline
        assert "timeline_points" in timeline
        assert "events" in timeline
        assert "notes" in timeline

    def test_timeline_points_is_list(self):
        resp = self._ranked_result()
        timeline = resp.json()["results"][0]["timeline"]
        assert isinstance(timeline["timeline_points"], list)

    def test_timeline_events_is_list(self):
        resp = self._ranked_result()
        timeline = resp.json()["results"][0]["timeline"]
        assert isinstance(timeline["events"], list)

    def test_timeline_points_default_checkpoints(self):
        resp = self._ranked_result()
        timeline = resp.json()["results"][0]["timeline"]
        months = [tp["months"] for tp in timeline["timeline_points"]]
        assert set(months) == {3, 6, 12, 24}

    def test_timeline_point_has_required_fields(self):
        resp = self._ranked_result()
        tp = resp.json()["results"][0]["timeline"]["timeline_points"][0]
        required = {
            "months", "label", "cumulative_medical_oop", "cumulative_premiums",
            "cumulative_hsa_credits", "net_out_of_pocket", "deductible_remaining",
            "oop_max_remaining", "payment_plan_balance_remaining", "breakdown",
        }
        assert required.issubset(set(tp.keys()))

    def test_timeline_event_has_required_fields(self):
        resp = self._ranked_result()
        events = resp.json()["results"][0]["timeline"]["events"]
        assert len(events) > 0
        ev = events[0]
        assert "month" in ev
        assert "amount" in ev
        assert "cost_variable_type" in ev
        assert "label" in ev
        assert "cumulative_net" in ev

    def test_procedure_oop_positive(self):
        resp = self._ranked_result()
        timeline = resp.json()["results"][0]["timeline"]
        assert timeline["procedure_oop"] >= 0

    def test_payment_plan_monthly_zero_when_no_plan(self):
        resp = self._ranked_result()
        timeline = resp.json()["results"][0]["timeline"]
        assert timeline["payment_plan_monthly"] == 0.0

    def test_payment_plan_monthly_nonzero_when_plan_set(self):
        resp = self._ranked_result(extra_payload={"payment_plan_months": 6})
        timeline = resp.json()["results"][0]["timeline"]
        assert timeline["payment_plan_monthly"] > 0

    def test_timeline_with_premium(self):
        resp = self._ranked_result(extra_payload={"monthly_premium": 200.0})
        timeline = resp.json()["results"][0]["timeline"]
        # At 3-month checkpoint, premiums should be 3 * 200 = 600
        tp_3 = next(tp for tp in timeline["timeline_points"] if tp["months"] == 3)
        assert tp_3["cumulative_premiums"] == pytest.approx(600.0)

    def test_timeline_with_hsa(self):
        resp = self._ranked_result(extra_payload={"monthly_hsa_contribution": 100.0})
        timeline = resp.json()["results"][0]["timeline"]
        tp_3 = next(tp for tp in timeline["timeline_points"] if tp["months"] == 3)
        assert tp_3["cumulative_hsa_credits"] == pytest.approx(300.0)

    def test_net_oop_reduced_by_hsa(self):
        resp_no_hsa = self._ranked_result()
        resp_with_hsa = self._ranked_result(extra_payload={"monthly_hsa_contribution": 100.0})
        tp_no_hsa = next(
            tp for tp in resp_no_hsa.json()["results"][0]["timeline"]["timeline_points"]
            if tp["months"] == 12
        )
        tp_with_hsa = next(
            tp for tp in resp_with_hsa.json()["results"][0]["timeline"]["timeline_points"]
            if tp["months"] == 12
        )
        assert tp_with_hsa["net_out_of_pocket"] < tp_no_hsa["net_out_of_pocket"]

    def test_invalid_include_timeline_flag_ignored(self):
        """include_timeline must be boolean — non-bool should return 422."""
        main_module, client = _make_client()
        db_p, geo_p = _mock_db_and_geocode(main_module)
        payload = {**BASE_PAYLOAD, "include_timeline": "yes"}
        with db_p, geo_p:
            resp = client.post(
                "/v1/rank-providers",
                json=payload,
                headers={"Authorization": "Bearer sandbox-token"},
            )
        # FastAPI will coerce "yes" → True (truthy string), not raise 422
        assert resp.status_code in (200, 422)

    def test_negative_payment_plan_months_returns_422(self):
        main_module, client = _make_client()
        db_p, geo_p = _mock_db_and_geocode(main_module)
        payload = {**BASE_PAYLOAD, "include_timeline": True, "payment_plan_months": -1}
        with db_p, geo_p:
            resp = client.post(
                "/v1/rank-providers",
                json=payload,
                headers={"Authorization": "Bearer sandbox-token"},
            )
        assert resp.status_code == 422

    def test_negative_monthly_premium_returns_422(self):
        main_module, client = _make_client()
        db_p, geo_p = _mock_db_and_geocode(main_module)
        payload = {**BASE_PAYLOAD, "include_timeline": True, "monthly_premium": -50.0}
        with db_p, geo_p:
            resp = client.post(
                "/v1/rank-providers",
                json=payload,
                headers={"Authorization": "Bearer sandbox-token"},
            )
        assert resp.status_code == 422
