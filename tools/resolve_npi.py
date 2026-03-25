"""
resolve_npi.py

Reads unique NPIs from .tmp/normalized_rates.jsonl, queries the CMS NPI
Registry API, and writes enriched provider records to .tmp/providers.json.

CMS NPI Registry API: https://npiregistry.cms.hhs.gov/api/
  - Free, no API key required
  - Supports batch lookup (number= param accepts one NPI at a time; use concurrency)
  - Rate limit: be conservative (~5 req/s)

Usage:
    python tools/resolve_npi.py

Output:
    .tmp/providers.json   — list of provider dicts keyed by NPI
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
INPUT_PATH = TMP_DIR / "normalized_rates.jsonl"
OUTPUT_PATH = TMP_DIR / "providers.json"

NPI_API_BASE = "https://npiregistry.cms.hhs.gov/api/"
NPI_API_VERSION = "2.1"
REQUEST_DELAY = 0.25   # seconds between requests (~4 req/s, well within limits)
MAX_RETRIES = 4
BACKOFF_BASE = 2
LOG_INTERVAL = 100


def fetch_npi(npi: str) -> dict | None:
    """Query CMS NPI Registry for a single NPI. Returns raw result dict or None."""
    params = {"number": npi, "version": NPI_API_VERSION}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(NPI_API_BASE, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    return results[0]
                return None  # NPI not found in registry
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = BACKOFF_BASE ** attempt
                log.warning(f"HTTP {resp.status_code} for NPI {npi} — retry in {wait}s")
                time.sleep(wait)
                continue
            log.warning(f"HTTP {resp.status_code} for NPI {npi}")
            return None
        except (requests.ConnectionError, requests.Timeout) as e:
            wait = BACKOFF_BASE ** attempt
            log.warning(f"{e} — retry in {wait}s")
            time.sleep(wait)
    log.error(f"All retries failed for NPI {npi}")
    return None


def extract_provider(npi: str, raw: dict) -> dict:
    """Normalize a CMS NPI Registry result into a clean provider dict."""
    entity_type_code = raw.get("enumeration_type", "")  # "NPI-1" or "NPI-2"

    basic = raw.get("basic", {})

    if entity_type_code == "NPI-1":
        # Individual provider
        first = basic.get("first_name", "")
        last = basic.get("last_name", "")
        credential = basic.get("credential", "")
        name = f"{first} {last}".strip()
        if credential:
            name = f"{name}, {credential}"
    else:
        # Organization
        name = basic.get("organization_name", "") or basic.get("name", "")

    # Primary practice address
    addresses = raw.get("addresses", [])
    primary = next(
        (a for a in addresses if a.get("address_purpose") == "LOCATION"),
        addresses[0] if addresses else {},
    )
    address_line = " ".join(filter(None, [
        primary.get("address_1", ""),
        primary.get("address_2", ""),
    ]))

    # Primary taxonomy (specialty)
    taxonomies = raw.get("taxonomies", [])
    primary_taxonomy = next(
        (t for t in taxonomies if t.get("primary")),
        taxonomies[0] if taxonomies else {},
    )
    taxonomy_code = primary_taxonomy.get("code", "")
    specialty = primary_taxonomy.get("desc", "")

    return {
        "npi": npi,
        "name": name,
        "entity_type": entity_type_code,
        "specialty": specialty,
        "taxonomy_code": taxonomy_code,
        "address": address_line,
        "city": primary.get("city", ""),
        "state": primary.get("state", ""),
        "zip": primary.get("postal_code", "")[:5],
        "phone": primary.get("telephone_number", ""),
        "npi_resolved": True,
    }


def unresolved_provider(npi: str) -> dict:
    return {
        "npi": npi,
        "name": None,
        "entity_type": None,
        "specialty": None,
        "taxonomy_code": None,
        "address": None,
        "city": None,
        "state": None,
        "zip": None,
        "phone": None,
        "npi_resolved": False,
    }


def load_unique_npis() -> set[str]:
    if not INPUT_PATH.exists():
        log.error(f"{INPUT_PATH} not found. Run parse_rates.py first.")
        sys.exit(1)
    npis = set()
    with open(INPUT_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            npis.add(r["npi"])
    return npis


def main():
    log.info("=== AnaCare: Resolve NPIs ===")
    npis = load_unique_npis()
    log.info(f"Unique NPIs to resolve: {len(npis):,}")

    # Load already-resolved providers if output exists (resume support)
    providers: dict[str, dict] = {}
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH) as f:
            existing = json.load(f)
        providers = {p["npi"]: p for p in existing}
        log.info(f"Resuming: {len(providers):,} already resolved")

    pending = [n for n in npis if n not in providers]
    log.info(f"Remaining to resolve: {len(pending):,}")

    resolved = 0
    unresolved = 0
    for i, npi in enumerate(pending, 1):
        if i % LOG_INTERVAL == 0:
            log.info(f"  Progress: {i:,}/{len(pending):,} (resolved={resolved}, unresolved={unresolved})")

        raw = fetch_npi(npi)
        if raw:
            providers[npi] = extract_provider(npi, raw)
            resolved += 1
        else:
            providers[npi] = unresolved_provider(npi)
            unresolved += 1

        time.sleep(REQUEST_DELAY)

    TMP_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(list(providers.values()), f, indent=2)

    log.info(
        f"Done: {resolved:,} resolved, {unresolved:,} unresolved → {OUTPUT_PATH}"
    )
    log.info("Next step: run tools/load_rates_db.py")


if __name__ == "__main__":
    main()
