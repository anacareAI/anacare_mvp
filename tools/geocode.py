"""
geocode.py

Zip-code to lat/lng lookup and haversine distance calculation.
Used by the API to filter providers by radius_miles.

Uses a local zip code dataset (no API key required).
Falls back to zip-prefix matching if coordinates unavailable.

Usage (as a module):
    from tools.geocode import distance_miles, zip_to_coords
"""

import csv
import logging
import math
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

# US zip code lat/lng dataset — free from Census ZCTA centroid file
# Download: https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
# Expected format: TSV with columns: GEOID, ALAND, AWATER, ALAND_SQMI, AWATER_SQMI, INTPTLAT, INTPTLONG
ZIP_DATA_PATH = Path("tools/data/zcta_centroids.tsv")

# In-memory cache: zip → (lat, lng)
_zip_coords: dict[str, tuple[float, float]] = {}
_loaded = False


def _load_zip_data():
    global _loaded, _zip_coords
    if _loaded:
        return
    if not ZIP_DATA_PATH.exists():
        log.warning(
            f"Zip centroid file not found at {ZIP_DATA_PATH}. "
            "Distance filtering will use zip-prefix fallback. "
            f"Download from Census Gazetteer and place at {ZIP_DATA_PATH}"
        )
        _loaded = True
        return

    with open(ZIP_DATA_PATH, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            try:
                zip_code = str(row.get("GEOID", "")).strip().zfill(5)
                lat = float(row.get("INTPTLAT", 0))
                lng = float(row.get("INTPTLONG", 0))
                _zip_coords[zip_code] = (lat, lng)
            except (ValueError, KeyError):
                continue

    log.info(f"Loaded {len(_zip_coords):,} zip code centroids")
    _loaded = True


@lru_cache(maxsize=10_000)
def zip_to_coords(zip_code: str) -> tuple[float, float] | None:
    """Return (lat, lng) for a 5-digit zip code, or None if unknown."""
    _load_zip_data()
    zip_code = str(zip_code).strip().zfill(5)
    return _zip_coords.get(zip_code)


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Haversine formula: great-circle distance between two points on Earth.
    Returns distance in miles.
    """
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def distance_miles(
    patient_zip: str,
    provider_zip: str,
) -> float | None:
    """
    Return distance in miles between patient zip and provider zip.
    Returns None if either zip is unresolvable.
    """
    patient_coords = zip_to_coords(patient_zip)
    provider_coords = zip_to_coords(provider_zip)
    if patient_coords is None or provider_coords is None:
        return None
    return round(haversine_miles(*patient_coords, *provider_coords), 1)


def filter_by_radius(
    providers: list[dict],
    patient_zip: str,
    radius_miles: float,
) -> list[dict]:
    """
    Filter a list of provider dicts by distance from patient_zip.
    Attaches `distance_miles` to each provider.

    Falls back to zip-prefix matching if centroid data unavailable.
    """
    _load_zip_data()
    has_centroid_data = len(_zip_coords) > 0

    if not has_centroid_data:
        # Fallback: match first 3 digits of zip
        prefix = patient_zip[:3]
        filtered = []
        for p in providers:
            pzip = str(p.get("zip", ""))
            p["distance_miles"] = None  # unknown
            if pzip[:3] == prefix:
                filtered.append(p)
        log.debug(f"Zip-prefix fallback: {len(filtered)}/{len(providers)} providers within prefix {prefix}")
        return filtered

    patient_coords = zip_to_coords(patient_zip)
    if patient_coords is None:
        log.warning(f"Patient zip {patient_zip} not in centroid data — returning all providers unfiltered")
        for p in providers:
            p["distance_miles"] = None
        return providers

    filtered = []
    for p in providers:
        provider_zip = str(p.get("zip", ""))
        dist = distance_miles(patient_zip, provider_zip)
        p["distance_miles"] = dist
        if dist is None or dist <= radius_miles:
            filtered.append(p)

    log.debug(f"Radius filter: {len(filtered)}/{len(providers)} within {radius_miles} miles of {patient_zip}")
    return filtered
