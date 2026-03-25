-- AnaCare Intelligence Engine — PostgreSQL Schema
-- Run once to initialize the database.
-- Compatible with Aurora PostgreSQL 15+

-- ── Providers ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS providers (
  npi            TEXT PRIMARY KEY,
  name           TEXT,
  entity_type    TEXT,   -- 'NPI-1' (individual) | 'NPI-2' (organization)
  specialty      TEXT,
  taxonomy_code  TEXT,
  address        TEXT,
  city           TEXT,
  state          TEXT,
  zip            TEXT,
  phone          TEXT,
  npi_resolved   BOOLEAN DEFAULT FALSE,
  last_synced    TIMESTAMP DEFAULT NOW()
);

-- ── Rates ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS rates (
  id              SERIAL PRIMARY KEY,
  npi             TEXT NOT NULL REFERENCES providers(npi) ON DELETE CASCADE,
  plan_id         TEXT,
  cpt_code        TEXT NOT NULL,
  rate            NUMERIC(12, 2) NOT NULL,
  rate_type       TEXT,   -- fee_for_service | case_rate | capitation | ...
  billing_class   TEXT,   -- professional | institutional
  expiration_date DATE,
  rate_flag       TEXT,   -- null | 'out_of_bounds'
  source_file     TEXT,
  ingested_at     TIMESTAMP DEFAULT NOW(),

  UNIQUE (npi, cpt_code, rate_type, billing_class)
);

CREATE INDEX IF NOT EXISTS idx_rates_cpt   ON rates(cpt_code);
CREATE INDEX IF NOT EXISTS idx_rates_npi   ON rates(npi);
CREATE INDEX IF NOT EXISTS idx_rates_plan  ON rates(plan_id);
CREATE INDEX IF NOT EXISTS idx_rates_cpt_npi ON rates(cpt_code, npi);

-- ── Quality Scores ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS quality_scores (
  npi                  TEXT PRIMARY KEY REFERENCES providers(npi) ON DELETE CASCADE,
  quality_score        NUMERIC(5, 2),   -- 0-100 or NULL
  cms_outcome_rating   NUMERIC(4, 2),
  procedure_volume     INTEGER,
  patient_satisfaction NUMERIC(4, 2),
  data_coverage_pct    NUMERIC(5, 2),   -- % of signals available
  last_updated         TIMESTAMP DEFAULT NOW()
);

-- ── Ingestion Log ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ingestion_log (
  id              SERIAL PRIMARY KEY,
  source_file     TEXT NOT NULL,
  payer           TEXT,
  records_written INTEGER,
  records_skipped INTEGER,
  started_at      TIMESTAMP,
  completed_at    TIMESTAMP DEFAULT NOW(),
  status          TEXT DEFAULT 'success'  -- success | partial | failed
);
