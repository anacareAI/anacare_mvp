"""
fetch_mrf_index.py

Fetches the Aetna MRF table-of-contents from the healthsparq metadata API
and writes a filtered list of in-network file URLs to .tmp/aetna_mrf_links.json.

Aetna publishes MRFs through CVS Health's healthsparq CDN. The metadata API
returns a list of all available files; this script deduplicates them and
writes download URLs for use by stream_mrf_file.py.

Usage:
    python tools/fetch_mrf_index.py
    python tools/fetch_mrf_index.py --brand ALICFI  # fully insured
    python tools/fetch_mrf_index.py --limit 3        # only first N files

Output:
    .tmp/aetna_mrf_links.json — list of {description, location, plan_count} dicts
"""

import argparse
import json
import logging
import os
import sys
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
OUTPUT_LINKS = TMP_DIR / "aetna_mrf_links.json"

METADATA_BASE = "https://mrf.healthsparq.com/aetnacvs-egress.nophi.kyruushsq.com/prd/mrf/AETNACVS_I"
CDN_BASE = METADATA_BASE

BRAND_CODES = {
    "ALICSI": "Self-insured (Aetna Life Insurance Company)",
    "ALICFI": "Fully insured",
    "ALICUNDER100": "Self-insured (under 100 lives)",
    "AETNACVS": "AetnaCVS Individual Exchange",
    "ASA": "Aetna Signature Administrators",
}


def fetch_metadata(brand_code: str) -> dict:
    url = f"{METADATA_BASE}/{brand_code}/latest_metadata.json"
    log.info(f"Fetching metadata: {url}")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    log.info(f"Metadata contains {len(data.get('files', []))} file entries")
    return data


def extract_links(data: dict, brand_code: str) -> list[dict]:
    files = data.get("files", [])
    in_net = [f for f in files if f.get("fileSchema") == "IN_NETWORK_RATES"]
    log.info(f"In-network rate files: {len(in_net)}")

    seen = set()
    links = []
    for f in in_net:
        fn = f.get("fileName", "")
        if fn in seen:
            continue
        seen.add(fn)

        file_path = f.get("filePath", "")
        if not file_path:
            continue

        location = f"{CDN_BASE}/{brand_code}/{file_path}"
        plans = f.get("reportingPlans", [])
        plan_names = [p.get("planName", "") for p in plans]
        description = f"{f.get('reportingEntityName', '')} — {', '.join(plan_names[:3])}"

        links.append({
            "description": description[:200],
            "location": location,
            "plan_count": len(plans),
            "last_updated": f.get("lastUpdatedOn", ""),
            "file_name": fn,
        })

    log.info(f"Unique in-network files: {len(links)}")
    return links


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", default="ALICSI", choices=list(BRAND_CODES.keys()),
                        help="Aetna brand code (default: ALICSI = self-insured)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit to first N files (0 = all)")
    args = parser.parse_args()

    log.info("=== AnaCare: Fetch Aetna MRF Index ===")
    log.info(f"Brand: {args.brand} ({BRAND_CODES[args.brand]})")

    data = fetch_metadata(args.brand)
    links = extract_links(data, args.brand)

    if not links:
        log.error("No in-network files found")
        sys.exit(1)

    if args.limit > 0:
        links = links[:args.limit]
        log.info(f"Limited to {len(links)} file(s)")

    TMP_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_LINKS, "w") as f:
        json.dump(links, f, indent=2)
    log.info(f"Saved {len(links)} links to {OUTPUT_LINKS}")

    log.info("=== Done ===")
    log.info(f"Next step: python tools/stream_mrf_file.py --links {OUTPUT_LINKS}")


if __name__ == "__main__":
    main()
