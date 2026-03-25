"""
api/main.py

AnaCare Intelligence Engine — FastAPI application.

Endpoints:
  POST /v1/cpt-lookup          Map procedure description -> CPT candidates
  POST /v1/rank-providers      Core ranking query
  GET  /v1/providers/{npi}     Single provider detail
  GET  /v1/health              Health check

Auth: OAuth 2.0 client credentials (token endpoint at /oauth/token)

Run locally:
    pip install -r requirements.txt
    uvicorn api.main:app --reload --port 8000
"""

import logging
import os
import time
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field, field_validator

load_dotenv()

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from api import db as database
from tools.compute_cost_timeline import TimelineInput, compute_cost_timeline
from tools.compute_oop import compute_oop, compute_oop_range
from tools.format_output import format_cpt_lookup, format_error, format_response, format_timeline
from tools.geocode import filter_by_radius
from tools.map_cpt import lookup_cpt
from tools.rank_providers import ProviderRecord, RankRequest, rank_providers

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

_start_time = time.time()

app = FastAPI(
    title="AnaCare Intelligence Engine",
    description="Provider cost and quality ranking API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    database.init_pool()
    log.info("AnaCare API started")


# ── Auth (stub — OAuth client credentials) ────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/oauth/token", auto_error=False)


def get_current_client(token: Annotated[str | None, Depends(oauth2_scheme)]):
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token. Use /oauth/token to obtain one.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # TODO: verify JWT signature against stored client secrets (Secrets Manager)
    return {"client_id": "sandbox", "scopes": ["rank:read", "cpt:read"]}


# ── Request / Response models ──────────────────────────────────────────────────

class CptLookupRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)


class RankProvidersRequest(BaseModel):
    cpt_code: str
    plan_id: str | None = None
    zip: str = Field(..., min_length=5, max_length=5)
    radius_miles: float = Field(25.0, ge=1, le=100)
    deductible_remaining: float = Field(..., ge=0)
    coinsurance_pct: float = Field(..., ge=0, le=1)
    oop_max_remaining: float = Field(..., ge=0)
    deductible_unknown: bool = False
    weights: dict = Field(default={"cost": 0.6, "quality": 0.4})
    limit: int = Field(10, ge=1, le=100)

    # Timeline parameters (optional)
    include_timeline: bool = False
    monthly_premium: float = Field(0.0, ge=0)
    monthly_hsa_contribution: float = Field(0.0, ge=0)
    payment_plan_months: int = Field(0, ge=0)

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, v):
        cost = v.get("cost", 0)
        quality = v.get("quality", 0)
        if abs(cost + quality - 1.0) > 0.001:
            raise ValueError(f"cost + quality weights must equal 1.0, got {cost + quality}")
        if cost < 0 or quality < 0:
            raise ValueError("Weights must be non-negative")
        return v


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/v1/health")
def health():
    uptime_seconds = round(time.time() - _start_time, 1)

    db_status = "ok"
    db_error = None
    try:
        with database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as exc:
        db_status = "error"
        db_error = str(exc)

    return {
        "status": "ok",
        "version": "0.1.0",
        "uptime_seconds": uptime_seconds,
        "db": {"status": db_status, **({"error": db_error} if db_error else {})},
    }


@app.post("/oauth/token")
def oauth_token(client_id: str, client_secret: str, scope: str = "rank:read cpt:read"):
    """Sandbox: accepts any credentials. Production: validate JWT signed with Secrets Manager."""
    return {
        "access_token": f"sandbox-token-{client_id}",
        "token_type": "bearer",
        "expires_in": 3600,
        "scope": scope,
    }


@app.post("/v1/cpt-lookup")
def cpt_lookup(
    body: CptLookupRequest,
    client: Annotated[dict, Depends(get_current_client)],
):
    start = time.perf_counter()
    candidates = lookup_cpt(body.query)
    if not candidates:
        raise HTTPException(status_code=404, detail=f"No CPT codes found for: {body.query}")
    latency_ms = round((time.perf_counter() - start) * 1000)
    result = format_cpt_lookup(body.query, candidates)
    result["meta"] = {"latency_ms": latency_ms}
    return result


@app.post("/v1/rank-providers")
def rank_providers_endpoint(
    body: RankProvidersRequest,
    client: Annotated[dict, Depends(get_current_client)],
):
    start = time.perf_counter()
    zip_prefix = body.zip[:3]

    rows = database.fetch_rates_for_query(
        cpt_code=body.cpt_code,
        plan_id=body.plan_id,
        zip_prefix=zip_prefix,
        radius_miles=body.radius_miles,
    )

    rows = filter_by_radius(rows, patient_zip=body.zip, radius_miles=body.radius_miles)

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No providers found for CPT {body.cpt_code} near zip {body.zip}",
        )

    provider_records: list[ProviderRecord] = []
    for row in rows:
        if body.deductible_unknown:
            oop_range = compute_oop_range(
                negotiated_rate=float(row["negotiated_rate"]),
                coinsurance_pct=body.coinsurance_pct,
                oop_max_remaining=body.oop_max_remaining,
                cpt_code=body.cpt_code,
            )
            estimated_oop = oop_range["estimated_oop_best"]
        else:
            oop_result = compute_oop(
                negotiated_rate=float(row["negotiated_rate"]),
                deductible_remaining=body.deductible_remaining,
                coinsurance_pct=body.coinsurance_pct,
                oop_max_remaining=body.oop_max_remaining,
                cpt_code=body.cpt_code,
            )
            estimated_oop = oop_result.estimated_oop

        quality_signals = {}
        if row.get("cms_outcome_rating") is not None:
            quality_signals["cms_outcome_rating"] = float(row["cms_outcome_rating"])
        if row.get("procedure_volume") is not None:
            quality_signals["procedure_volume"] = int(row["procedure_volume"])
        if row.get("patient_satisfaction") is not None:
            quality_signals["patient_satisfaction"] = float(row["patient_satisfaction"])

        provider_records.append(ProviderRecord(
            npi=row["npi"],
            provider_name=row["provider_name"] or "Unknown Provider",
            specialty=row["specialty"] or "",
            address=row["address"] or "",
            city=row["city"] or "",
            state=row["state"] or "",
            zip=row["zip"] or "",
            distance_miles=row.get("distance_miles") or 0.0,
            cpt_code=row["cpt_code"],
            procedure="",
            negotiated_rate=float(row["negotiated_rate"]),
            estimated_oop=estimated_oop,
            quality_score=float(row["quality_score"]) if row.get("quality_score") is not None else None,
            quality_signals=quality_signals,
        ))

    req = RankRequest(
        cost_weight=body.weights.get("cost", 0.6),
        quality_weight=body.weights.get("quality", 0.4),
        limit=body.limit,
    )
    ranked = rank_providers(provider_records, req)

    if body.include_timeline:
        for provider_dict in ranked:
            if provider_dict.get("rank") is not None:
                timeline_inp = TimelineInput(
                    negotiated_rate=provider_dict["negotiated_rate"],
                    deductible_remaining=body.deductible_remaining,
                    coinsurance_pct=body.coinsurance_pct,
                    oop_max_remaining=body.oop_max_remaining,
                    monthly_premium=body.monthly_premium,
                    monthly_hsa_contribution=body.monthly_hsa_contribution,
                    payment_plan_months=body.payment_plan_months,
                    cpt_code=body.cpt_code,
                )
                provider_dict["timeline"] = format_timeline(
                    compute_cost_timeline(timeline_inp)
                )

    latency_ms = round((time.perf_counter() - start) * 1000)
    return format_response(
        ranked_providers=ranked,
        query=body.model_dump(),
        meta={"latency_ms": latency_ms, "total_providers_evaluated": len(provider_records)},
    )


@app.get("/v1/providers/{npi}")
def get_provider(
    npi: str,
    client: Annotated[dict, Depends(get_current_client)],
):
    with database.get_conn() as conn:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT p.*, q.quality_score, q.cms_outcome_rating,
                       q.procedure_volume, q.patient_satisfaction, q.data_coverage_pct
                FROM providers p
                LEFT JOIN quality_scores q ON q.npi = p.npi
                WHERE p.npi = %s
                """,
                (npi,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Provider NPI {npi} not found")
    return dict(row)


# ── Error handlers ─────────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=format_error(exc.status_code, exc.detail),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    log.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content=format_error(500, "Internal server error"),
    )
