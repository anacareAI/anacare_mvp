.PHONY: install test test-verbose api seed schema zip-data \
        pipeline-m1 pipeline-m1-demo pipeline-m3 \
        frontend-install frontend-dev frontend-build

# ── Python backend ────────────────────────────────────────────────────────────

install:
	pip install -r requirements.txt

test:
	python -m pytest tests/ -q

test-verbose:
	python -m pytest tests/ -v

# Run API locally (requires DB_* and ANTHROPIC_API_KEY in .env)
api:
	uvicorn api.main:app --reload --port 8000

# One-shot smoke test for OOP + ranking engines (no DB required)
smoke:
	python tools/compute_oop.py
	python tools/rank_providers.py

# ── Database ──────────────────────────────────────────────────────────────────

# Initialize schema (run once after creating the DB)
schema:
	python tools/load_rates_db.py --init-schema

# Seed with ~20 realistic Chicago demo providers (fast, no pipeline needed)
seed:
	python tools/seed_demo_data.py

# Re-seed from scratch (clears existing demo rows first)
seed-fresh:
	python tools/seed_demo_data.py --clear

# Download zip centroid data (run once)
zip-data:
	python tools/download_zip_data.py

# ── MRF pipeline (real Aetna data) ───────────────────────────────────────────

pipeline-m1:
	python tools/fetch_mrf_index.py --limit 1
	python tools/stream_mrf_file.py --links .tmp/aetna_mrf_links.json
	python tools/parse_rates.py
	python tools/resolve_npi.py
	python tools/load_rates_db.py

# Quick demo pipeline: 1 file, capped at 5000 records
pipeline-m1-demo:
	python tools/fetch_mrf_index.py --limit 1
	python tools/stream_mrf_file.py --links .tmp/aetna_mrf_links.json --max-records 5000
	python tools/parse_rates.py
	python tools/resolve_npi.py
	python tools/load_rates_db.py

# M3 quality pipeline
pipeline-m3:
	python tools/fetch_quality_cms.py
	python tools/score_quality.py --db

# CPT lookup test (requires ANTHROPIC_API_KEY)
cpt-test:
	python tools/map_cpt.py "knee replacement"

# ── Frontend (Next.js) ────────────────────────────────────────────────────────

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

# ── Local dev (run in two separate terminals) ─────────────────────────────────
# Terminal 1: make api
# Terminal 2: make frontend-dev
