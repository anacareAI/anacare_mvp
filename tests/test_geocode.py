"""
tests/test_geocode.py

Unit tests for the geocoding / distance module.
Run: pytest tests/test_geocode.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from tools.geocode import haversine_miles, filter_by_radius, distance_miles


class TestHaversine:

    def test_same_point_is_zero(self):
        assert haversine_miles(41.8781, -87.6298, 41.8781, -87.6298) == pytest.approx(0.0, abs=0.01)

    def test_chicago_to_evanston(self):
        # Chicago (41.8781, -87.6298) to Evanston (42.0450, -87.6877) ≈ 11.7 miles
        dist = haversine_miles(41.8781, -87.6298, 42.0450, -87.6877)
        assert 10 < dist < 14

    def test_chicago_to_new_york(self):
        # Chicago to NYC ≈ 790 miles
        dist = haversine_miles(41.8781, -87.6298, 40.7128, -74.0060)
        assert 700 < dist < 730

    def test_symmetry(self):
        d1 = haversine_miles(41.8781, -87.6298, 42.0450, -87.6877)
        d2 = haversine_miles(42.0450, -87.6877, 41.8781, -87.6298)
        assert d1 == pytest.approx(d2, rel=0.001)


class TestFilterByRadius:

    def _make_providers(self):
        return [
            {"npi": "1111111111", "zip": "60601"},  # Chicago downtown
            {"npi": "2222222222", "zip": "60611"},  # Chicago Streeterville
            {"npi": "3333333333", "zip": "90210"},  # Beverly Hills (far)
        ]

    def test_zip_prefix_fallback_no_data(self):
        """When centroid data isn't loaded, fall back to zip prefix matching."""
        from tools import geocode
        # Force no centroid data
        original = geocode._zip_coords.copy()
        original_loaded = geocode._loaded
        geocode._zip_coords.clear()
        geocode._loaded = True

        try:
            providers = self._make_providers()
            result = filter_by_radius(providers, "60601", radius_miles=25)
            result_npis = {r["npi"] for r in result}
            # Prefix 606 matches 60601 and 60611 but not 90210
            assert "1111111111" in result_npis
            assert "2222222222" in result_npis
            assert "3333333333" not in result_npis
        finally:
            geocode._zip_coords.update(original)
            geocode._loaded = original_loaded

    def test_distance_attached_to_providers(self):
        """Each provider gets a distance_miles key after filtering."""
        from tools import geocode
        original = geocode._zip_coords.copy()
        original_loaded = geocode._loaded
        geocode._zip_coords.clear()
        geocode._loaded = True

        try:
            providers = [{"npi": "1111111111", "zip": "60601"}]
            result = filter_by_radius(providers, "60601", radius_miles=25)
            assert "distance_miles" in result[0]
        finally:
            geocode._zip_coords.update(original)
            geocode._loaded = original_loaded


class TestDistanceMiles:

    def test_unknown_zip_returns_none(self):
        # 00000 is not a real zip
        result = distance_miles("00000", "60601")
        assert result is None

    def test_same_zip_returns_zero_or_small(self):
        result = distance_miles("60601", "60601")
        # Either None (no centroid data) or ~0
        assert result is None or result < 1.0
