"""
api/db.py

Database connection pool and query helpers for the AnaCare API.
"""

import os
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
import psycopg2.extras

log = logging.getLogger(__name__)

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def init_pool(min_conn: int = 2, max_conn: int = 10):
    global _pool
    password = os.environ.get("DB_PASSWORD", "")
    _pool = psycopg2.pool.ThreadedConnectionPool(
        min_conn,
        max_conn,
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=password or None,
        sslmode="require" if password else "prefer",
        connect_timeout=10,
    )
    log.info("DB connection pool initialized")


@contextmanager
def get_conn():
    if _pool is None:
        raise RuntimeError("DB pool not initialized. Call init_pool() first.")
    conn = _pool.getconn()
    try:
        yield conn
    finally:
        _pool.putconn(conn)


def fetch_rates_for_query(
    cpt_code: str,
    plan_id: str | None,
    zip_prefix: str,
    radius_miles: float,
) -> list[dict]:
    """
    Fetch negotiated rate records for a CPT code + geographic area.
    Returns list of dicts: {npi, rate, rate_type, provider fields...}

    Geography filtering: we filter providers by zip prefix as a proxy for
    distance. Full geocoding / haversine radius filtering happens in geocode.py
    after this call.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            params: list = [cpt_code, f"{zip_prefix}%"]
            plan_clause = ""
            if plan_id:
                plan_clause = "AND r.plan_id = %s"
                params.append(plan_id)

            cur.execute(
                f"""
                SELECT
                    r.npi,
                    r.cpt_code,
                    r.rate            AS negotiated_rate,
                    r.rate_type,
                    r.billing_class,
                    r.expiration_date,
                    p.name            AS provider_name,
                    p.specialty,
                    p.address,
                    p.city,
                    p.state,
                    p.zip,
                    q.quality_score,
                    q.cms_outcome_rating,
                    q.procedure_volume,
                    q.patient_satisfaction
                FROM rates r
                JOIN providers p ON p.npi = r.npi
                LEFT JOIN quality_scores q ON q.npi = r.npi
                WHERE r.cpt_code = %s
                  AND p.zip LIKE %s
                  {plan_clause}
                  AND (r.expiration_date IS NULL OR r.expiration_date > CURRENT_DATE)
                ORDER BY r.rate ASC
                """,
                params,
            )
            return [dict(row) for row in cur.fetchall()]
