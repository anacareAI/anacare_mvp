# Workflow: Quality Scoring Pipeline

**Objective:** Compute a 0–100 quality index per provider NPI using CMS Care Compare data and apply the 40% coverage suppression rule.

**Milestone:** M3 — Quality Layer

---

## Required Inputs

| Input | Source |
|---|---|
| `.tmp/providers.json` | Output of resolve_npi.py |
| CMS Provider Data Catalog API | Public, no API key |
| DB credentials (`DB_*`) | `.env` (optional, only if `--db` flag used) |

---

## Step-by-Step

### Step 1 — Fetch CMS Quality Data

```bash
python tools/fetch_quality_cms.py
```

- Queries CMS Physician Compare + Hospital Compare datasets for each resolved NPI
- Supports resume (skips already-fetched NPIs)
- Writes `.tmp/quality_raw.json`
- Logs coverage percentage → if <40%, warns that quality will be suppressed

**Edge cases:**
- NPI not in CMS data → `has_data: false`, handled gracefully in scoring
- CMS API rate-limited → tool retries automatically with backoff

---

### Step 2 — Score Quality

```bash
python tools/score_quality.py
python tools/score_quality.py --db   # also upserts to PostgreSQL
```

**Scoring model (v1):**

| Signal | Weight (normalized) | Source |
|---|---|---|
| CMS outcome rating (1-5 stars) | ~43% | CMS Care Compare |
| Procedure volume (log-scaled) | ~31% | CMS claims |
| Patient satisfaction (HCAHPS 0-100) | ~25% | CMS HCAHPS |

Note: weights sum to 80% of PRD spec because safety/board-cert signals are excluded in v1. Weights are re-normalized to sum to 100% for the actual score.

**Coverage rule (enforced in scoring step):**
- If <40% of providers have quality data → set ALL `quality_score = null`
- Ranking system will use `ranking_basis: cost_only` automatically
- Never interpolate or estimate quality scores

**Output:** `.tmp/quality_scores.json` + optional DB upsert

---

## Field Mapping: CMS API → Score Signals

| Score signal | CMS field names tried (first non-null wins) |
|---|---|
| `cms_outcome_rating` | `cms_overall_rating`, `overall_rating`, `star_rating`, `quality_rating` |
| `procedure_volume` | `num_procedures`, `procedure_volume`, `number_of_procedures`, `volume` |
| `patient_satisfaction` | `hcahps_base_score`, `patient_satisfaction`, `hcahps_summary_star_rating` |

CMS field names vary by dataset version — the tool tries multiple synonyms and uses the first non-null value.

---

## Notes & Learnings

- CMS Physician Compare dataset ID (2026-03-20): `mj5m-pzi6`
- CMS Hospital Compare dataset ID (2026-03-20): `wq2k-b7rv`
- CMS updates annually; check `last_updated_on` before re-fetching
- Staleness threshold: 13 months (per PRD)
- CMS field names have changed across dataset versions — always log raw field names when debugging missing scores
