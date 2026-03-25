"""
score_quality.py

Computes a weighted quality index (0-100) per NPI from raw CMS data.
Reads .tmp/quality_raw.json, writes .tmp/quality_scores.json and
upserts into the quality_scores DB table.

v1 Scoring model (per PRD):
  CMS outcome rating       35%  (0-5 stars → 0-100 scale)
  Procedure volume         25%  (log-scaled, capped at 1000)
  Patient satisfaction     20%  (HCAHPS score, 0-100)
  [Safety / board cert intentionally excluded from v1 — no data source yet]

Coverage rule (per PRD):
  If <40% of providers for a given CPT+region have quality data,
  set ALL quality_score to null and return ranking_basis='cost_only'.

Usage:
    python tools/score_quality.py [--db]   # --db also upserts to postgres

Output:
    .tmp/quality_scores.json
"""

import argparse
import json
import logging
import math
import os
import sys
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
INPUT_PATH = TMP_DIR / "quality_raw.json"
OUTPUT_PATH = TMP_DIR / "quality_scores.json"

QUALITY_COVERAGE_THRESHOLD = 0.40  # per PRD: suppress quality if <40% coverage

# Signal weights (must sum to 1.0; v1 omits safety and board cert)
WEIGHTS = {
    "cms_outcome_rating": 0.35,
    "procedure_volume": 0.25,
    "patient_satisfaction": 0.20,
    # remaining 0.20 is unallocated in v1 — redistributed proportionally below
}

# Redistribute missing weights so scores still range 0-100
_total_weight = sum(WEIGHTS.values())
WEIGHTS = {k: v / _total_weight for k, v in WEIGHTS.items()}


def scale_outcome_rating(raw_value) -> float | None:
    """CMS star rating (1-5) → 0-100."""
    try:
        val = float(raw_value)
    except (TypeError, ValueError):
        return None
    if val < 1 or val > 5:
        return None
    return (val - 1) / 4 * 100  # 1→0, 3→50, 5→100


def scale_procedure_volume(raw_value) -> float | None:
    """Log-scale procedure volume, capped at 1000. 0→0, 1→~12, 100→50, 1000→100."""
    try:
        vol = int(raw_value)
    except (TypeError, ValueError):
        return None
    if vol < 0:
        return None
    cap = 1000
    if vol == 0:
        return 0.0
    return min(math.log(vol + 1) / math.log(cap + 1) * 100, 100.0)


def scale_patient_satisfaction(raw_value) -> float | None:
    """HCAHPS linear measure (0-100), pass through with validation."""
    try:
        val = float(raw_value)
    except (TypeError, ValueError):
        return None
    if val < 0 or val > 100:
        return None
    return val


def extract_signals(record: dict) -> dict:
    """
    Pull quality signals out of raw CMS API result.

    CMS Physician Compare fields (approximate — field names vary by dataset version):
      - 'cms_overall_rating'    → outcome rating
      - 'num_procedures'        → procedure volume
      - 'hcahps_base_score'     → patient satisfaction
    """
    physician = record.get("physician_data", [])
    hospital = record.get("hospital_data", [])
    all_data = physician + hospital

    # Try each record in the result set for non-null values
    def find_field(*keys):
        for entry in all_data:
            for key in keys:
                val = entry.get(key)
                if val is not None and str(val).strip() not in ("", "Not Available", "N/A"):
                    return val
        return None

    outcome_raw = find_field(
        "cms_overall_rating", "overall_rating", "star_rating", "quality_rating"
    )
    volume_raw = find_field(
        "num_procedures", "procedure_volume", "number_of_procedures", "volume"
    )
    satisfaction_raw = find_field(
        "hcahps_base_score", "patient_satisfaction", "hcahps_summary_star_rating"
    )

    return {
        "cms_outcome_rating_raw": outcome_raw,
        "procedure_volume_raw": volume_raw,
        "patient_satisfaction_raw": satisfaction_raw,
        "cms_outcome_rating": scale_outcome_rating(outcome_raw),
        "procedure_volume": scale_procedure_volume(volume_raw),
        "patient_satisfaction": scale_patient_satisfaction(satisfaction_raw),
    }


def compute_score(signals: dict) -> float | None:
    """
    Weighted average of available signals.
    If no signals are available, return None.
    """
    total_weight = 0.0
    weighted_sum = 0.0

    for signal_key, weight in WEIGHTS.items():
        val = signals.get(signal_key)
        if val is not None:
            weighted_sum += weight * val
            total_weight += weight

    if total_weight == 0:
        return None

    # Re-normalize: if only some signals present, score is relative to available signals
    score = weighted_sum / total_weight
    return round(score, 2)


def score_all(raw_records: list[dict]) -> list[dict]:
    scored = []
    for record in raw_records:
        npi = record["npi"]
        signals = extract_signals(record)
        score = compute_score(signals)

        # Count how many signals are available
        available = sum(
            1 for k in ["cms_outcome_rating", "procedure_volume", "patient_satisfaction"]
            if signals.get(k) is not None
        )
        data_coverage_pct = available / 3 * 100

        scored.append({
            "npi": npi,
            "quality_score": score,
            "cms_outcome_rating": signals.get("cms_outcome_rating"),
            "procedure_volume_raw": signals.get("procedure_volume_raw"),
            "patient_satisfaction": signals.get("patient_satisfaction"),
            "data_coverage_pct": round(data_coverage_pct, 1),
            "has_quality_data": score is not None,
        })
    return scored


def check_coverage(scored: list[dict]) -> float:
    if not scored:
        return 0.0
    count_with_data = sum(1 for s in scored if s["has_quality_data"])
    return count_with_data / len(scored)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", action="store_true", help="Also upsert scores into PostgreSQL")
    args = parser.parse_args()

    log.info("=== AnaCare: Score Quality ===")

    if not INPUT_PATH.exists():
        log.error(f"{INPUT_PATH} not found. Run fetch_quality_cms.py first.")
        sys.exit(1)

    with open(INPUT_PATH) as f:
        raw_records = json.load(f)

    log.info(f"Scoring {len(raw_records):,} providers")
    scored = score_all(raw_records)
    coverage = check_coverage(scored)
    log.info(f"Quality data coverage: {coverage * 100:.1f}%")

    if coverage < QUALITY_COVERAGE_THRESHOLD:
        log.warning(
            f"Coverage {coverage * 100:.1f}% < {QUALITY_COVERAGE_THRESHOLD * 100:.0f}% threshold. "
            "Per PRD: all quality_score values will be null at query time. "
            "Ranking will use cost_only basis."
        )
        # Mark all scores as null (don't store misleading partial scores)
        for s in scored:
            s["quality_score"] = None
            s["suppressed"] = True
    else:
        for s in scored:
            s["suppressed"] = False

    TMP_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(scored, f, indent=2)
    log.info(f"Written {len(scored):,} records to {OUTPUT_PATH}")

    # Summary
    with_score = [s for s in scored if s["quality_score"] is not None]
    if with_score:
        avg_score = sum(s["quality_score"] for s in with_score) / len(with_score)
        log.info(f"Providers with quality score: {len(with_score):,} | avg score: {avg_score:.1f}")
    else:
        log.info("No providers have quality scores (suppressed or no data)")

    if args.db:
        _upsert_to_db(scored)

    log.info("Next step: run tools/map_cpt.py or tools/rank_providers.py")


def _upsert_to_db(scored: list[dict]):
    import psycopg2
    import psycopg2.extras

    try:
        conn = psycopg2.connect(
            host=os.environ["DB_HOST"],
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            sslmode="require",
        )
    except psycopg2.OperationalError as e:
        log.error(f"DB connection failed: {e}")
        return

    with conn.cursor() as cur:
        rows = [
            (
                s["npi"],
                s["quality_score"],
                s.get("cms_outcome_rating"),
                s.get("procedure_volume_raw"),
                s.get("patient_satisfaction"),
                s.get("data_coverage_pct"),
            )
            for s in scored
        ]
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO quality_scores
              (npi, quality_score, cms_outcome_rating, procedure_volume,
               patient_satisfaction, data_coverage_pct)
            VALUES %s
            ON CONFLICT (npi) DO UPDATE SET
              quality_score=EXCLUDED.quality_score,
              cms_outcome_rating=EXCLUDED.cms_outcome_rating,
              procedure_volume=EXCLUDED.procedure_volume,
              patient_satisfaction=EXCLUDED.patient_satisfaction,
              data_coverage_pct=EXCLUDED.data_coverage_pct,
              last_updated=NOW()
            """,
            rows,
        )
        conn.commit()
    conn.close()
    log.info(f"Upserted {len(scored):,} quality scores to DB")


if __name__ == "__main__":
    main()
