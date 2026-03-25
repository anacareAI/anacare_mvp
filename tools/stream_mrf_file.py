"""
stream_mrf_file.py

Streams a single Aetna MRF in-network JSON file using ijson (never loads into memory).
Filters to target CPT codes and writes matching rate records to .tmp/raw_rates.jsonl.

Usage:
    python tools/stream_mrf_file.py --url <mrf_url>
    python tools/stream_mrf_file.py --links .tmp/aetna_mrf_links.json

Output:
    .tmp/raw_rates.jsonl   — newline-delimited JSON, one rate record per line
"""

import argparse
import gzip
import json
import logging
import os
import sys
import time
from pathlib import Path

import ijson
import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

# v1 target CPT codes
TARGET_CPT_CODES = set(
    os.getenv("TARGET_CPT_CODES", "27447,45378,73721").split(",")
)

TMP_DIR = Path(".tmp")
OUTPUT_PATH = TMP_DIR / "raw_rates.jsonl"

MAX_RETRIES = 5
BACKOFF_BASE = 2
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB streaming read buffer
REQUEST_TIMEOUT = 120

LOG_INTERVAL = 100_000  # log progress every N rate objects parsed


# ── HTTP ───────────────────────────────────────────────────────────────────────


def open_stream(url: str):
    """Return a streaming response for the given URL with retry."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info(f"Opening stream: {url} (attempt {attempt})")
            resp = requests.get(
                url,
                stream=True,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": "AnaCare-MRF-Streamer/0.1 (contact@anacare.ai)"},
            )
            if resp.status_code == 200:
                return resp
            if resp.status_code == 404:
                log.error(f"404 Not Found: {url}")
                sys.exit(1)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = BACKOFF_BASE ** attempt
                log.warning(f"HTTP {resp.status_code} — retrying in {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
        except (requests.ConnectionError, requests.Timeout) as e:
            wait = BACKOFF_BASE ** attempt
            log.warning(f"{e} — retrying in {wait}s")
            time.sleep(wait)
    log.error(f"All {MAX_RETRIES} attempts failed for {url}")
    sys.exit(1)


# ── Parsing ───────────────────────────────────────────────────────────────────


def stream_rates(resp: requests.Response, source_url: str, out_file, max_records: int = 0) -> int:
    """
    Stream-parse the MRF JSON response using ijson.
    Handles both plain JSON and gzipped JSON (.json.gz) streams.

    If max_records > 0, stops after writing that many records (for faster demo runs).

    Returns count of records written.
    """
    written = 0
    parsed = 0
    skipped_cpt = 0

    # Decompress on-the-fly if gzipped
    raw = resp.raw
    raw.decode_content = True
    if source_url.endswith(".gz"):
        log.info("Detected gzipped stream — decompressing on the fly")
        raw = gzip.GzipFile(fileobj=raw)

    try:
        for item in ijson.items(raw, "in_network.item"):
            parsed += 1
            if parsed % LOG_INTERVAL == 0:
                log.info(f"  Parsed {parsed:,} in-network entries, {written:,} written, {skipped_cpt:,} skipped (CPT filter)")

            billing_code = str(item.get("billing_code", "")).strip()
            billing_code_type = item.get("billing_code_type", "").upper()

            if billing_code_type != "CPT" or billing_code not in TARGET_CPT_CODES:
                skipped_cpt += 1
                continue

            description = item.get("description", "")
            negotiated_rates = item.get("negotiated_rates", [])

            for rate_group in negotiated_rates:
                provider_groups = rate_group.get("provider_groups", [])
                negotiated_prices = rate_group.get("negotiated_prices", [])

                npis = []
                for pg in provider_groups:
                    npis.extend(str(n) for n in pg.get("npi", []))

                for price in negotiated_prices:
                    negotiated_rate = price.get("negotiated_rate")
                    negotiated_type = price.get("negotiated_type", "")
                    expiration_date = price.get("expiration_date", "")
                    billing_class = price.get("billing_class", "")

                    rate_type = {
                        "negotiated": "fee_for_service",
                        "fee schedule": "fee_for_service",
                        "case rate": "case_rate",
                        "capitation": "capitation",
                        "percent of total charges": "percent_of_charges",
                        "per diem": "per_diem",
                        "other": "other",
                    }.get(negotiated_type.lower(), negotiated_type.lower() or "unknown")

                    for npi in npis:
                        record = {
                            "npi": npi,
                            "cpt_code": billing_code,
                            "description": description,
                            "rate": negotiated_rate,
                            "rate_type": rate_type,
                            "billing_class": billing_class,
                            "expiration_date": expiration_date,
                            "source_file": source_url,
                        }
                        out_file.write(json.dumps(record) + "\n")
                        written += 1

                        if max_records > 0 and written >= max_records:
                            log.info(f"Reached max_records={max_records}, stopping early")
                            log.info(f"  Parsed {parsed:,} entries, {written:,} written, {skipped_cpt:,} skipped")
                            return written

    except ijson.JSONError as e:
        log.error(f"ijson parse error at entry {parsed}: {e}")
        log.warning("Partial results written. File may be malformed.")

    log.info(f"Stream complete: {parsed:,} entries parsed, {written:,} records written, {skipped_cpt:,} skipped")
    return written


# ── Main ───────────────────────────────────────────────────────────────────────


def process_url(url: str, append: bool = False, max_records: int = 0) -> int:
    """Stream one MRF URL and write rate records to OUTPUT_PATH."""
    TMP_DIR.mkdir(exist_ok=True)
    mode = "a" if append else "w"
    resp = open_stream(url)
    content_length = resp.headers.get("Content-Length")
    if content_length:
        log.info(f"File size: {int(content_length) / 1024 / 1024:.0f} MB")
    else:
        log.info("File size unknown (no Content-Length header)")

    log.info(f"Target CPT codes: {sorted(TARGET_CPT_CODES)}")
    log.info(f"Writing to: {OUTPUT_PATH} (mode={mode})")

    with open(OUTPUT_PATH, mode) as f:
        count = stream_rates(resp, url, f, max_records=max_records)
    return count


def main():
    parser = argparse.ArgumentParser(description="Stream Aetna MRF in-network file and extract target CPT rates")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="Direct URL of a single MRF in-network file")
    group.add_argument("--links", help="Path to .tmp/aetna_mrf_links.json (process all listed files)")
    parser.add_argument("--append", action="store_true", help="Append to existing output file instead of overwriting")
    parser.add_argument("--max-records", type=int, default=0,
                        help="Stop after writing N records total (0 = no limit)")
    args = parser.parse_args()

    log.info("=== AnaCare: Stream MRF File ===")

    if args.url:
        count = process_url(args.url, append=args.append, max_records=args.max_records)
        log.info(f"Total records written: {count:,}")
    else:
        with open(args.links) as f:
            links = json.load(f)
        log.info(f"Processing {len(links)} MRF file(s) from {args.links}")
        total = 0
        remaining = args.max_records
        for i, link in enumerate(links, 1):
            url = link["location"]
            desc = link.get("description", url)
            log.info(f"\n[{i}/{len(links)}] {desc}")
            count = process_url(url, append=(i > 1 or args.append), max_records=remaining)
            total += count
            log.info(f"Running total: {total:,} records")
            if args.max_records > 0:
                remaining = args.max_records - total
                if remaining <= 0:
                    log.info("Global max_records reached, stopping.")
                    break

        log.info(f"\n=== Done: {total:,} total rate records written to {OUTPUT_PATH} ===")

    log.info("Next step: run tools/parse_rates.py")


if __name__ == "__main__":
    main()
