# Workflow: Aetna MRF Ingestion Pipeline

**Objective:** Ingest Aetna machine-readable files (MRFs) for a target metro area, extract negotiated rates for 3 target CPT codes, and write normalized records to the `rates` table in PostgreSQL.

**Milestone:** M1 — MRF Pipeline

---

## Required Inputs

| Input | Source | Notes |
|---|---|---|
| `AETNA_MRF_INDEX_JSON_URL` | `.env` | Aetna's CMS-mandated index URL. Update if 404. |
| `TARGET_METRO` | `.env` | e.g. `chicago` — used to filter MRF file descriptions |
| `TARGET_ZIP_PREFIX` | `.env` | e.g. `606` — filters providers by geography |
| `DB_*` | `.env` | PostgreSQL connection params |
| Target CPT codes | Hardcoded in tools | `27447`, `45378`, `73721` (v1) |

---

## Step-by-Step Execution

### Step 1 — Fetch MRF Index

**Tool:** `tools/fetch_mrf_index.py`

```bash
python tools/fetch_mrf_index.py
```

**What it does:**
- Downloads Aetna's table-of-contents JSON (the "index" file)
- Validates CMS schema compliance (required keys present)
- Filters in-network file URLs to the target metro
- Writes results to `.tmp/aetna_mrf_index.json` and `.tmp/aetna_mrf_links.json`

**Expected output:** `.tmp/aetna_mrf_links.json` — list of `{description, location, plan_count}` dicts

**Edge cases:**
- `404 on index URL` → Aetna may have rotated the URL. Check AETNA_MRF_INDEX_JSON_URL in `.env`. Try searching CMS's payer registry for updated URL.
- `No links for target metro` → Tool falls back to all links; manually inspect and update TARGET_METRO
- `Rate limited (429)` → Tool retries with exponential backoff automatically

---

### Step 2 — Stream MRF File

**Tool:** `tools/stream_mrf_file.py` _(not yet implemented)_

**What it will do:**
- Take a URL from `.tmp/aetna_mrf_links.json`
- Stream the file using `ijson` (never load into memory — files can be 10–500 GB)
- Filter to target CPT codes: `27447`, `45378`, `73721`
- Write raw rate records to `.tmp/raw_rates.jsonl` (newline-delimited JSON)

**Key constraint:** Use `ijson.items(f, 'in_network_rates.item')` to stream without full parse.

---

### Step 3 — Parse & Normalize Rates

**Tool:** `tools/parse_rates.py` _(not yet implemented)_

**What it will do:**
- Read `.tmp/raw_rates.jsonl`
- Extract `npi`, `plan_id`, `cpt_code`, `rate`, `rate_type`, `effective_date`
- Deduplicate: one NPI may appear multiple times across negotiation arrangements
- Write to `.tmp/normalized_rates.jsonl`

**Schema produced:**
```
npi, plan_id, cpt_code, rate, rate_type, effective_date, source_file, ingested_at
```

---

### Step 4 — Resolve NPIs

**Tool:** `tools/resolve_npi.py` _(not yet implemented)_

**What it will do:**
- For each unique NPI in normalized_rates, query CMS NPI Registry API
- Enrich with: provider name, specialty, address, taxonomy code, entity type (individual vs. organization)
- Write to `.tmp/providers.json`

**API:** `https://npiregistry.cms.hhs.gov/api/?number={npi}&version=2.1`

---

### Step 5 — Load to Database

**Tool:** `tools/load_rates_db.py` _(not yet implemented)_

**What it will do:**
- Read `.tmp/normalized_rates.jsonl` and `.tmp/providers.json`
- Upsert into `rates` and `providers` tables in Aurora PostgreSQL
- Log ingestion stats: records inserted, duplicates skipped, errors

---

## Database Schema

```sql
CREATE TABLE providers (
  npi           TEXT PRIMARY KEY,
  name          TEXT,
  specialty     TEXT,
  address       TEXT,
  city          TEXT,
  state         TEXT,
  zip           TEXT,
  entity_type   TEXT,   -- 'NPI-1' (individual) or 'NPI-2' (organization)
  taxonomy_code TEXT,
  last_synced   TIMESTAMP
);

CREATE TABLE rates (
  id            SERIAL PRIMARY KEY,
  npi           TEXT REFERENCES providers(npi),
  plan_id       TEXT,
  cpt_code      TEXT,
  rate          NUMERIC,
  rate_type     TEXT,   -- fee_for_service | case_rate | capitation
  effective_date DATE,
  source_file   TEXT,
  ingested_at   TIMESTAMP DEFAULT NOW(),
  UNIQUE (npi, plan_id, cpt_code, effective_date)
);

CREATE INDEX idx_rates_cpt ON rates(cpt_code);
CREATE INDEX idx_rates_npi ON rates(npi);
CREATE INDEX idx_rates_plan ON rates(plan_id);
```

---

## Failure Handling

| Failure | Response |
|---|---|
| Index URL returns 404 | Log URL, alert, try fallback URL patterns from CMS payer registry |
| MRF file is malformed JSON | Skip file, log filename + error, continue with next file |
| NPI not in CMS registry | Mark provider as `npi_unresolved`, still insert rate record |
| DB write failure | Log record, write to `.tmp/failed_records.jsonl` for retry |
| Rate limited by CMS NPI API | Respect Retry-After header; batch NPI lookups (max 10/req) |

---

## Data Freshness

- MRF files update monthly. Check `last_updated_on` in index before re-ingesting.
- Staleness threshold: 45 days. If `last_updated_on` is older than 45 days, alert and refuse to serve data.
- Track `ingested_at` timestamp on every rate record.

---

## Notes & Learnings

_(Update this section as you discover edge cases during M1 execution)_

- Aetna MRF index URL as of 2026-03-20: `https://mrf.aetna.com/2024-01-01_aetna_index.json` — verify before running
- Individual in-network files can be 1–50 GB each; metro filtering on index descriptions reduces this significantly
- `ijson` is required for streaming; never use `json.load()` on MRF files
