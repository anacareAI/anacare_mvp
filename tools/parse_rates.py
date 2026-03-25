"""
parse_rates.py

Reads .tmp/raw_rates.jsonl (output of stream_mrf_file.py),
normalizes and deduplicates rate records, and writes
.tmp/normalized_rates.jsonl ready for DB ingestion.

Usage:
    python tools/parse_rates.py

Output:
    .tmp/normalized_rates.jsonl
"""

import json
import logging
import os
import sys
from datetime import datetime, date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

TMP_DIR = Path(".tmp")
INPUT_PATH = TMP_DIR / "raw_rates.jsonl"
OUTPUT_PATH = TMP_DIR / "normalized_rates.jsonl"

# Expiration date Aetna uses to mean "no expiration"
NO_EXPIRY_SENTINEL = "9999-12-31"

# Rate sanity bounds (USD) — flag outliers but don't drop them
RATE_MIN = 0.01
RATE_MAX = 5_000_000.00


def parse_date(s: str) -> str | None:
    """Return ISO date string or None if unparseable."""
    if not s or s == NO_EXPIRY_SENTINEL:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalize_npi(npi: str) -> str | None:
    """NPI must be exactly 10 digits."""
    npi = str(npi).strip().replace("-", "")
    if len(npi) == 10 and npi.isdigit():
        return npi
    return None


def normalize_record(raw: dict, ingested_at: str) -> dict | None:
    """
    Normalize a single raw rate record.
    Returns None if the record should be dropped (invalid NPI or rate).
    """
    npi = normalize_npi(raw.get("npi", ""))
    if not npi:
        return None

    cpt_code = str(raw.get("cpt_code", "")).strip()
    if not cpt_code:
        return None

    rate = raw.get("rate")
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        return None

    if rate < RATE_MIN or rate > RATE_MAX:
        log.debug(f"Rate out of bounds ({rate}) for NPI {npi} CPT {cpt_code} — flagging")

    rate_type = str(raw.get("rate_type", "unknown")).strip().lower()
    billing_class = str(raw.get("billing_class", "")).strip().lower()
    expiration_date = parse_date(raw.get("expiration_date", ""))
    source_file = str(raw.get("source_file", ""))

    return {
        "npi": npi,
        "cpt_code": cpt_code,
        "rate": round(rate, 2),
        "rate_type": rate_type,
        "billing_class": billing_class,  # professional | institutional | ""
        "expiration_date": expiration_date,
        "source_file": source_file,
        "ingested_at": ingested_at,
        "rate_flag": "out_of_bounds" if (rate < RATE_MIN or rate > RATE_MAX) else None,
    }


def main():
    if not INPUT_PATH.exists():
        log.error(f"Input not found: {INPUT_PATH}. Run stream_mrf_file.py first.")
        sys.exit(1)

    ingested_at = datetime.utcnow().isoformat()

    # Track seen (npi, cpt_code, rate_type, billing_class) tuples to deduplicate.
    # Keep the record with the lowest rate when duplicates exist.
    seen: dict[tuple, dict] = {}

    total_raw = 0
    dropped_invalid = 0
    dropped_dup = 0

    log.info(f"Reading {INPUT_PATH}")
    with open(INPUT_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total_raw += 1
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                dropped_invalid += 1
                continue

            record = normalize_record(raw, ingested_at)
            if record is None:
                dropped_invalid += 1
                continue

            # Dedup key: same provider + procedure + rate type + billing class
            key = (record["npi"], record["cpt_code"], record["rate_type"], record["billing_class"])
            if key in seen:
                # Keep lower rate (more favorable to patient)
                if record["rate"] < seen[key]["rate"]:
                    seen[key] = record
                dropped_dup += 1
            else:
                seen[key] = record

    normalized = list(seen.values())
    log.info(
        f"Raw records: {total_raw:,} | "
        f"Invalid/dropped: {dropped_invalid:,} | "
        f"Duplicates collapsed: {dropped_dup:,} | "
        f"Output: {len(normalized):,}"
    )

    TMP_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        for record in normalized:
            f.write(json.dumps(record) + "\n")

    log.info(f"Written to {OUTPUT_PATH}")

    # Summary stats
    by_cpt: dict[str, int] = {}
    for r in normalized:
        by_cpt[r["cpt_code"]] = by_cpt.get(r["cpt_code"], 0) + 1
    for cpt, count in sorted(by_cpt.items()):
        log.info(f"  CPT {cpt}: {count:,} provider-rate pairs")

    log.info("Next step: run tools/resolve_npi.py")


if __name__ == "__main__":
    main()
