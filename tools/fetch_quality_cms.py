"""
fetch_quality_cms.py

Fetches CMS Care Compare quality data for providers in our rates DB.
Queries the CMS Provider Data Catalog API by NPI and writes results
to .tmp/quality_raw.json.

CMS Provider Data Catalog API:
  https://data.cms.gov/provider-data/api/1/datastore/query/{dataset_id}/0

Datasets used in v1:
  - Physician Compare (doctors): dataset id = 'mj5m-pzi6'
  - Hospital Compare (facilities): dataset id = 'wq2k-b7rv'

Usage:
    python tools/fetch_quality_cms.py

Output:
    .tmp/quality_raw.json   — list of {npi, cms_data} dicts
"""

import json
import logging
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

TMP_DIR = Path(".tmp")
PROVIDERS_PATH = TMP_DIR / "providers.json"
OUTPUT_PATH = TMP_DIR / "quality_raw.json"

# CMS Provider Data Catalog — Physician Compare summary
PHYSICIAN_DATASET = "mj5m-pzi6"
HOSPITAL_DATASET = "wq2k-b7rv"
CMS_API_BASE = "https://data.cms.gov/provider-data/api/1/datastore/query"

REQUEST_DELAY = 0.2
MAX_RETRIES = 4
BACKOFF_BASE = 2
LOG_INTERVAL = 50


def query_cms(dataset_id: str, npi: str) -> list[dict]:
    """Query CMS Provider Data Catalog for a single NPI."""
    url = f"{CMS_API_BASE}/{dataset_id}/0"
    payload = {
        "conditions": [{"property": "npi", "value": npi, "operator": "="}],
        "limit": 10,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("results", [])
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = BACKOFF_BASE ** attempt
                log.warning(f"HTTP {resp.status_code} — retry in {wait}s")
                time.sleep(wait)
                continue
            log.debug(f"HTTP {resp.status_code} for NPI {npi} in dataset {dataset_id}")
            return []
        except (requests.ConnectionError, requests.Timeout) as e:
            wait = BACKOFF_BASE ** attempt
            log.warning(f"{e} — retry in {wait}s")
            time.sleep(wait)
    return []


def fetch_all(npis: list[str]) -> list[dict]:
    results = []
    found = 0
    not_found = 0

    for i, npi in enumerate(npis, 1):
        if i % LOG_INTERVAL == 0:
            log.info(f"  {i:,}/{len(npis):,} processed (found={found}, not_found={not_found})")

        physician_data = query_cms(PHYSICIAN_DATASET, npi)
        time.sleep(REQUEST_DELAY)
        hospital_data = query_cms(HOSPITAL_DATASET, npi)
        time.sleep(REQUEST_DELAY)

        combined = physician_data + hospital_data
        record = {
            "npi": npi,
            "physician_data": physician_data,
            "hospital_data": hospital_data,
            "has_data": len(combined) > 0,
        }
        results.append(record)

        if combined:
            found += 1
        else:
            not_found += 1

    log.info(f"Total: {len(npis):,} NPIs | with CMS data: {found:,} | no data: {not_found:,}")
    coverage_pct = (found / len(npis) * 100) if npis else 0
    log.info(f"Coverage: {coverage_pct:.1f}%")
    if coverage_pct < 40:
        log.warning(
            "Coverage below 40% threshold — quality scores will be suppressed per PRD rule. "
            "All providers will return quality_score: null, ranking_basis: cost_only."
        )
    return results


def load_npis() -> list[str]:
    if not PROVIDERS_PATH.exists():
        log.error(f"{PROVIDERS_PATH} not found. Run resolve_npi.py first.")
        sys.exit(1)
    with open(PROVIDERS_PATH) as f:
        providers = json.load(f)
    return [p["npi"] for p in providers if p.get("npi_resolved")]


def main():
    log.info("=== AnaCare: Fetch CMS Quality Data ===")
    npis = load_npis()
    log.info(f"Resolved NPIs to query: {len(npis):,}")

    # Resume support: load already-fetched NPIs
    existing: dict[str, dict] = {}
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH) as f:
            existing_list = json.load(f)
        existing = {r["npi"]: r for r in existing_list}
        log.info(f"Resuming: {len(existing):,} already fetched")

    pending = [n for n in npis if n not in existing]
    log.info(f"Remaining: {len(pending):,}")

    if pending:
        new_results = fetch_all(pending)
        existing.update({r["npi"]: r for r in new_results})

    TMP_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(list(existing.values()), f, indent=2)

    log.info(f"Written to {OUTPUT_PATH}")
    log.info("Next step: run tools/score_quality.py")


if __name__ == "__main__":
    main()
