# Workflow: Ranking API (M4)

**Objective:** Run the fully assembled AnaCare `/rank-providers` and `/cpt-lookup` API endpoints locally and validate end-to-end behavior.

**Milestone:** M4 — Ranking API

---

## Prerequisites

All upstream milestones complete:
- M1: `rates` and `providers` tables populated in PostgreSQL
- M3: `quality_scores` table populated (or empty — API handles gracefully)
- `.env` configured with `DB_*`, `ANTHROPIC_API_KEY`

---

## Running the API Locally

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

API docs available at: http://localhost:8000/docs

---

## Authentication Flow

```bash
# Get a sandbox token
curl -X POST "http://localhost:8000/oauth/token?client_id=test&client_secret=test"

# Use token in subsequent requests
TOKEN="sandbox-token-test"
```

---

## Test the /cpt-lookup Endpoint

```bash
curl -X POST http://localhost:8000/v1/cpt-lookup \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "knee replacement"}'
```

Expected response includes CPT candidates: 27447, 27446, 27445 with confidence scores.

---

## Test the /rank-providers Endpoint

```bash
curl -X POST http://localhost:8000/v1/rank-providers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "cpt_code": "27447",
    "plan_id": "AETNA-PPO-IL-2026",
    "zip": "60601",
    "radius_miles": 25,
    "deductible_remaining": 700,
    "coinsurance_pct": 0.20,
    "oop_max_remaining": 2300,
    "weights": {"cost": 0.7, "quality": 0.3},
    "limit": 10
  }'
```

---

## Validation Checklist

- [ ] `/v1/health` returns `{"status": "ok"}`
- [ ] `/oauth/token` returns an access token
- [ ] `/v1/cpt-lookup` returns ≥1 CPT candidate for "knee replacement"
- [ ] `/v1/rank-providers` returns ranked providers with `estimated_oop`, `quality_score`, `rank`
- [ ] Response includes `disclaimer` field
- [ ] Invalid weights (cost=0.8, quality=0.8) return HTTP 422
- [ ] Unknown zip returns HTTP 404
- [ ] Request without token returns HTTP 401

---

## Latency Target

Per PRD: p95 latency for `/rank-providers` < 3 seconds.

Bottleneck will be DB query. Ensure indexes are created (see schema.sql):
- `idx_rates_cpt` on `rates(cpt_code)`
- `idx_rates_cpt_npi` on `rates(cpt_code, npi)`

---

## Known Limitations (v1)

- Distance filtering uses zip prefix (first 3 digits), not haversine geocoding — rough approximation
- OAuth token endpoint is a sandbox stub; production requires JWT signing with client secrets from Secrets Manager
- `/v1/providers/{npi}` returns raw DB row; no distance calculation yet

---

## Notes & Learnings

- FastAPI `on_event("startup")` initializes the DB connection pool; ensure DB_* vars are set before starting
- `psycopg2` requires `libpq` installed on the host; on macOS: `brew install libpq`
- Use `uvicorn --reload` for development only; production uses Gunicorn + uvicorn workers on ECS
