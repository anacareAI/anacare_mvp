#!/usr/bin/env python3
"""
tools/seed_demo_data.py

Populates the database with realistic Chicago-area demo data for AnaCare demos.
Creates ~20 providers with negotiated rates for CPT codes 27447, 45378, and 73721,
plus quality scores drawn from realistic CMS-like distributions.

Usage:
    python tools/seed_demo_data.py            # insert (skip if already seeded)
    python tools/seed_demo_data.py --clear    # drop and re-seed
"""

import argparse
import os
import sys
import logging

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

PLAN_ID = "AETNA-PPO-IL-2026"

# ── Providers ─────────────────────────────────────────────────────────────────
# (npi, name, specialty, taxonomy, address, city, state, zip, entity_type)
PROVIDERS = [
    # Orthopedic surgeons / facilities (for CPT 27447 knee, 73721 MRI)
    ("1003010001", "Northwestern Memorial Hospital", "Orthopedic Surgery",
     "207X00000X", "251 E Huron St", "Chicago", "IL", "60611", "NPI-2"),
    ("1003010002", "Rush University Medical Center", "Orthopedic Surgery",
     "207X00000X", "1653 W Congress Pkwy", "Chicago", "IL", "60612", "NPI-2"),
    ("1003010003", "UChicago Medicine", "Orthopedic Surgery",
     "207X00000X", "5841 S Maryland Ave", "Chicago", "IL", "60637", "NPI-2"),
    ("1003010004", "Advocate Illinois Masonic Medical Center", "Orthopedic Surgery",
     "207X00000X", "836 W Wellington Ave", "Chicago", "IL", "60657", "NPI-2"),
    ("1003010005", "Loyola University Medical Center", "Orthopedic Surgery",
     "207X00000X", "2160 S 1st Ave", "Maywood", "IL", "60153", "NPI-2"),
    ("1003010006", "NorthShore University HealthSystem", "Orthopedic Surgery",
     "207X00000X", "2650 Ridge Ave", "Evanston", "IL", "60201", "NPI-2"),
    ("1003010007", "Silver Cross Hospital", "Orthopedic Surgery",
     "207X00000X", "1900 Silver Cross Blvd", "New Lenox", "IL", "60451", "NPI-2"),
    ("1003010008", "Edward-Elmhurst Health", "Orthopedic Surgery",
     "207X00000X", "801 S Washington St", "Naperville", "IL", "60540", "NPI-2"),
    ("1003010009", "Midwest Orthopedic Center", "Orthopedic Surgery",
     "207X00000X", "730 N Michigan Ave", "Chicago", "IL", "60611", "NPI-1"),
    ("1003010010", "Chicago Sports & Orthopedics", "Orthopedic Surgery",
     "207X00000X", "680 N Lake Shore Dr", "Chicago", "IL", "60611", "NPI-1"),
    ("1003010019", "Illinois Bone & Joint Institute", "Orthopedic Surgery",
     "207X00000X", "2401 Ravine Way", "Glenview", "IL", "60025", "NPI-1"),
    ("1003010020", "Palos Health Orthopedics", "Orthopedic Surgery",
     "207X00000X", "12251 S 80th Ave", "Palos Heights", "IL", "60463", "NPI-1"),
    # Gastroenterology (for CPT 45378 colonoscopy)
    ("1003010011", "GI Associates of Chicago", "Gastroenterology",
     "207RG0100X", "111 N Wabash Ave", "Chicago", "IL", "60602", "NPI-1"),
    ("1003010012", "Digestive Health Institute", "Gastroenterology",
     "207RG0100X", "2525 S Michigan Ave", "Chicago", "IL", "60616", "NPI-1"),
    ("1003010013", "Chicago Gastroenterology Consultants", "Gastroenterology",
     "207RG0100X", "1000 N Clark St", "Chicago", "IL", "60610", "NPI-1"),
    ("1003010014", "Northwestern Gastroenterology", "Gastroenterology",
     "207RG0100X", "675 N St Clair St", "Chicago", "IL", "60611", "NPI-1"),
    ("1003010015", "Advocate Digestive Health Center", "Gastroenterology",
     "207RG0100X", "3000 N Halsted St", "Chicago", "IL", "60657", "NPI-1"),
    # Radiology (for CPT 73721 MRI knee)
    ("1003010016", "Chicago Radiology Associates", "Radiology",
     "2085R0202X", "200 E Illinois St", "Chicago", "IL", "60611", "NPI-1"),
    ("1003010017", "Suburban Imaging Center", "Radiology",
     "2085R0202X", "9000 W 87th St", "Hickory Hills", "IL", "60457", "NPI-1"),
    ("1003010018", "Midwest MRI Specialists", "Radiology",
     "2085R0202X", "444 N Michigan Ave", "Chicago", "IL", "60611", "NPI-1"),
]

# ── Rates ─────────────────────────────────────────────────────────────────────
# (npi, cpt_code, rate) — professional fee-for-service negotiated rates
# CPT 27447: Total knee arthroplasty (professional component, $2,000–$5,500)
# CPT 45378: Colonoscopy (professional component, $400–$1,200)
# CPT 73721: MRI knee (professional component, $300–$900)
RATES = [
    # CPT 27447 — knee arthroplasty
    ("1003010001", "27447", 3200.00),
    ("1003010002", "27447", 2800.00),
    ("1003010003", "27447", 3600.00),
    ("1003010004", "27447", 2500.00),
    ("1003010005", "27447", 2350.00),
    ("1003010006", "27447", 3100.00),
    ("1003010007", "27447", 2150.00),
    ("1003010008", "27447", 2750.00),
    ("1003010009", "27447", 4250.00),
    ("1003010010", "27447", 3850.00),
    ("1003010019", "27447", 2950.00),
    ("1003010020", "27447", 2050.00),
    # CPT 45378 — colonoscopy
    ("1003010011", "45378",  520.00),
    ("1003010012", "45378",  680.00),
    ("1003010013", "45378",  450.00),
    ("1003010014", "45378",  780.00),
    ("1003010015", "45378",  610.00),
    ("1003010001", "45378",  950.00),  # Hospital also does GI
    ("1003010002", "45378",  870.00),
    # CPT 73721 — MRI knee
    ("1003010016", "73721",  380.00),
    ("1003010017", "73721",  310.00),
    ("1003010018", "73721",  430.00),
    ("1003010001", "73721",  650.00),  # Hospital also does MRI
    ("1003010006", "73721",  590.00),
    ("1003010008", "73721",  520.00),
    ("1003010009", "73721",  480.00),
]

# ── Quality scores ────────────────────────────────────────────────────────────
# (npi, quality_score, cms_outcome_rating, procedure_volume, patient_satisfaction, data_coverage_pct)
QUALITY = [
    ("1003010001", 91.0, 4.7, 423, 89.0, 98.0),
    ("1003010002", 88.0, 4.5, 380, 87.0, 95.0),
    ("1003010003", 85.0, 4.3, 290, 84.0, 92.0),
    ("1003010004", 76.0, 3.9, 198, 78.0, 85.0),
    ("1003010005", 72.0, 3.7, 165, 75.0, 80.0),
    ("1003010006", 83.0, 4.2, 247, 82.0, 90.0),
    ("1003010007", 68.0, 3.5, 134, 71.0, 75.0),
    ("1003010008", 79.0, 4.0, 210, 81.0, 88.0),
    ("1003010009", 87.0, 4.4, 315, 86.0, 93.0),
    ("1003010010", 84.0, 4.2, 275, 83.0, 91.0),
    ("1003010011", 80.0, 4.1, 520, 82.0, 89.0),
    ("1003010012", 73.0, 3.7, 310, 76.0, 82.0),
    ("1003010013", 77.0, 3.9, 380, 79.0, 85.0),
    ("1003010014", 89.0, 4.5, 490, 88.0, 94.0),
    ("1003010015", 82.0, 4.1, 420, 83.0, 90.0),
    ("1003010016", 86.0, 4.3, 890, 85.0, 92.0),
    ("1003010017", 74.0, 3.8, 620, 77.0, 83.0),
    ("1003010018", 88.0, 4.4, 760, 87.0, 94.0),
    ("1003010019", 81.0, 4.1, 230, 80.0, 87.0),
    ("1003010020", 69.0, 3.6, 148, 72.0, 76.0),
]


def get_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ.get("DB_PASSWORD") or None,
        sslmode="require" if os.environ.get("DB_PASSWORD") else "prefer",
        connect_timeout=10,
    )


def clear_data(cur):
    log.info("Clearing existing demo data...")
    cur.execute("DELETE FROM quality_scores WHERE npi LIKE '1003010%'")
    cur.execute("DELETE FROM rates WHERE npi LIKE '1003010%'")
    cur.execute("DELETE FROM providers WHERE npi LIKE '1003010%'")
    log.info("Cleared.")


def seed_providers(cur):
    sql = """
        INSERT INTO providers (npi, name, specialty, taxonomy_code, address, city, state, zip, entity_type, npi_resolved)
        VALUES %s
        ON CONFLICT (npi) DO UPDATE SET
            name = EXCLUDED.name,
            specialty = EXCLUDED.specialty,
            last_synced = NOW()
    """
    rows = [
        (npi, name, specialty, taxonomy, address, city, state, zip_, entity_type, True)
        for npi, name, specialty, taxonomy, address, city, state, zip_, entity_type in PROVIDERS
    ]
    psycopg2.extras.execute_values(cur, sql, rows)
    log.info(f"Upserted {len(rows)} providers.")


def seed_rates(cur):
    sql = """
        INSERT INTO rates (npi, plan_id, cpt_code, rate, rate_type, billing_class, source_file)
        VALUES %s
        ON CONFLICT (npi, cpt_code, rate_type, billing_class) DO UPDATE SET
            rate = EXCLUDED.rate,
            ingested_at = NOW()
    """
    rows = [
        (npi, PLAN_ID, cpt, rate, "fee_for_service", "professional", "seed_demo_data")
        for npi, cpt, rate in RATES
    ]
    psycopg2.extras.execute_values(cur, sql, rows)
    log.info(f"Upserted {len(rows)} rate records.")


def seed_quality(cur):
    sql = """
        INSERT INTO quality_scores (npi, quality_score, cms_outcome_rating, procedure_volume, patient_satisfaction, data_coverage_pct)
        VALUES %s
        ON CONFLICT (npi) DO UPDATE SET
            quality_score = EXCLUDED.quality_score,
            cms_outcome_rating = EXCLUDED.cms_outcome_rating,
            procedure_volume = EXCLUDED.procedure_volume,
            patient_satisfaction = EXCLUDED.patient_satisfaction,
            data_coverage_pct = EXCLUDED.data_coverage_pct,
            last_updated = NOW()
    """
    psycopg2.extras.execute_values(cur, sql, QUALITY)
    log.info(f"Upserted {len(QUALITY)} quality score records.")


def main():
    parser = argparse.ArgumentParser(description="Seed AnaCare demo data")
    parser.add_argument("--clear", action="store_true", help="Clear existing demo data before seeding")
    args = parser.parse_args()

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                if args.clear:
                    clear_data(cur)
                seed_providers(cur)
                seed_rates(cur)
                seed_quality(cur)
        log.info("Demo data seeded successfully.")
        log.info(f"  {len(PROVIDERS)} providers · {len(RATES)} rates · {len(QUALITY)} quality scores")
        log.info(f"  CPT codes: 27447 (knee), 45378 (colonoscopy), 73721 (MRI knee)")
        log.info(f"  Plan: {PLAN_ID}")
        log.info(f"  Try: zip=60601, deductible=$700, coinsurance=20%, OOP max=$2,300")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
