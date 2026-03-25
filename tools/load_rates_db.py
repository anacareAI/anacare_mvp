"""
load_rates_db.py

Upserts normalized rate records and provider records into PostgreSQL.
Reads .tmp/normalized_rates.jsonl and .tmp/providers.json.

Usage:
    python tools/load_rates_db.py [--init-schema]

Flags:
    --init-schema    Run schema.sql to create tables first (idempotent)

Prerequisites:
    DB_* env vars set in .env (host, port, name, user, password)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

TMP_DIR = Path(".tmp")
RATES_PATH = TMP_DIR / "normalized_rates.jsonl"
PROVIDERS_PATH = TMP_DIR / "providers.json"
SCHEMA_PATH = Path("tools/schema.sql")

BATCH_SIZE = 500  # records per INSERT batch


def get_connection():
    password = os.environ.get("DB_PASSWORD", "")
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=password or None,
        connect_timeout=15,
        sslmode="require" if password else "prefer",
    )


def init_schema(conn):
    log.info(f"Running schema from {SCHEMA_PATH}")
    with open(SCHEMA_PATH) as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    log.info("Schema initialized")


def load_providers(conn) -> tuple[int, int]:
    if not PROVIDERS_PATH.exists():
        log.warning(f"{PROVIDERS_PATH} not found — skipping provider upsert")
        return 0, 0

    with open(PROVIDERS_PATH) as f:
        providers = json.load(f)

    inserted = 0

    with conn.cursor() as cur:
        for batch_start in range(0, len(providers), BATCH_SIZE):
            batch = providers[batch_start:batch_start + BATCH_SIZE]
            rows = [
                (
                    p["npi"], p["name"], p["entity_type"], p["specialty"],
                    p["taxonomy_code"], p["address"], p["city"], p["state"],
                    p["zip"], p["phone"], p["npi_resolved"],
                )
                for p in batch
            ]
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO providers (npi, name, entity_type, specialty, taxonomy_code,
                                       address, city, state, zip, phone, npi_resolved, last_synced)
                VALUES %s
                ON CONFLICT (npi) DO UPDATE SET
                    name=EXCLUDED.name, entity_type=EXCLUDED.entity_type,
                    specialty=EXCLUDED.specialty, taxonomy_code=EXCLUDED.taxonomy_code,
                    address=EXCLUDED.address, city=EXCLUDED.city, state=EXCLUDED.state,
                    zip=EXCLUDED.zip, phone=EXCLUDED.phone,
                    npi_resolved=EXCLUDED.npi_resolved, last_synced=NOW()
                """,
                rows,
            )
            inserted += len(batch)
        conn.commit()

    log.info(f"Providers upserted: {inserted:,}")
    return inserted, updated


def load_rates(conn) -> tuple[int, int]:
    if not RATES_PATH.exists():
        log.error(f"{RATES_PATH} not found. Run parse_rates.py first.")
        sys.exit(1)

    records = []
    with open(RATES_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    log.info(f"Upserting {len(records):,} rate records")
    started_at = datetime.now(tz=__import__("datetime").timezone.utc).replace(tzinfo=None)
    inserted = 0
    skipped = 0

    with conn.cursor() as cur:
        for batch_start in range(0, len(records), BATCH_SIZE):
            batch = records[batch_start:batch_start + BATCH_SIZE]
            rows = [
                (
                    r["npi"], r.get("plan_id"), r["cpt_code"], r["rate"],
                    r["rate_type"], r.get("billing_class"), r.get("expiration_date"),
                    r.get("rate_flag"), r.get("source_file"),
                )
                for r in batch
            ]
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO rates (npi, plan_id, cpt_code, rate, rate_type,
                                   billing_class, expiration_date, rate_flag, source_file)
                VALUES %s
                ON CONFLICT (npi, cpt_code, rate_type, billing_class) DO UPDATE SET
                    rate=LEAST(rates.rate, EXCLUDED.rate),
                    rate_flag=EXCLUDED.rate_flag,
                    source_file=EXCLUDED.source_file,
                    ingested_at=NOW()
                """,
                rows,
            )
            inserted += len(batch)

            if batch_start % (BATCH_SIZE * 10) == 0 and batch_start > 0:
                log.info(f"  Progress: {batch_start:,}/{len(records):,}")

        # Log ingestion
        source_files = list({r.get("source_file", "") for r in records})
        cur.execute(
            """
            INSERT INTO ingestion_log (source_file, payer, records_written, started_at)
            VALUES (%s, %s, %s, %s)
            """,
            (", ".join(source_files)[:500], "aetna", inserted, started_at),
        )
        conn.commit()

    log.info(f"Rates upserted: {inserted:,}")
    return inserted, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-schema", action="store_true", help="Run schema.sql first")
    args = parser.parse_args()

    log.info("=== AnaCare: Load Rates to DB ===")

    try:
        conn = get_connection()
        log.info("DB connection established")
    except psycopg2.OperationalError as e:
        log.error(f"DB connection failed: {e}")
        log.error("Check DB_* env vars in .env")
        sys.exit(1)

    if args.init_schema:
        init_schema(conn)
        if not RATES_PATH.exists():
            log.info("Schema created. No rate data to load yet — run the M1 pipeline first.")
            conn.close()
            return

    load_providers(conn)
    inserted, _ = load_rates(conn)

    conn.close()
    log.info(f"=== Done: {inserted:,} rates loaded ===")
    log.info("M1 complete. Next: run tools/fetch_quality_cms.py (M3) or tools/compute_oop.py (M2)")


if __name__ == "__main__":
    main()
