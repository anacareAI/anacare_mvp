# PRD: AnaCare Consumer Platform — v1.0

**Product:** AnaCare — Insurance-Integrated Cost Transparency Platform
**Version:** 1.0
**Date:** 2026-03-25
**Status:** Active Planning — Interview Decisions Locked

---

## 0. Locked Decisions (from Founder Interview — 2026-03-25)

| Decision | Choice | Notes |
|---|---|---|
| Authentication | Fully stateless v1 | No accounts. Plan + location entered per session. |
| Frontend tech | React | Component state for multi-step flow. |
| Distribution | Payer integration | Link from insurance company's member portal to AnaCare. |
| Plan ID v1 | Dropdown only (Tier 1) | Populated from HealthCare.gov 2026 landscape file. Deductible + OOP entered manually. |
| Payer integration long-term | TBD | URL params (?plan_id=) for demo handoff; OAuth/FHIR token for production payer deal. |
| Revenue model | Payer licenses it (B2B) | Aetna/BCBS/UHC pay annual license. Not employer-direct or consumer subscription. |
| Demo target | 8–12 weeks | Full pipeline with real data. |
| Mobile UX | Tap-to-expand accordion | Hover panel collapses to tap-accordion on touch devices. |
| Cost timeline scope | All 3 phases, all 10 procedures | Pre-op + surgery + post-op required for all launch procedures before shipping. |
| Launch procedure | Knee Replacement (27447) first | Lead demo procedure. Expand to 10 total. |
| Data strategy | Real Aetna MRF data | No synthetic rates. Real negotiated rates from Aetna MRF index. |
| Infrastructure | AWS | S3 (raw MRF files) + Aurora PostgreSQL + ECS (streaming workers) + Lambda (API). |
| RAND fallback | MRF rate directly (no multiplier) | Use Aetna negotiated rate directly when available. RAND multiplier only for hospitals not in MRF. |
| Ranking control | Slider + sort tabs | Sort tabs (Best Value / Lowest Cost / Top Rated / Nearest) + cost↔quality weighting slider. |
| Surgeon cards | Critical for v1 | Full doctor cards (volume + credentials + years in practice) in hospital detail view. |
| Non-negotiable feature | Full 3-phase cost timeline | This is the core differentiator. Everything else ships around this. |
| Team | Solo founder + Claude Code | Ruthless prioritization required. AI handles implementation. |
| MRF ingestion approach | Streaming + CPT filter | Stream Aetna MRF with ijson, filter to target CPT codes during stream — do NOT download full file to disk. |

---

## 1. Vision

AnaCare is the platform where patients on specific insurance plans go to find their best in-network providers before they book care. Not after the bill arrives — before.

The promise: **Compare real prices, see your out-of-pocket cost, and pick the right provider.**

This is not a search engine. It is a decision engine. The user arrives knowing their plan, their procedure, and their location. They leave knowing exactly where to go and what it will cost them — broken down by phase, by CPT code, by line item.

Billion-dollar insight: **the only reason this hasn't been built is that the data is hard to assemble.** We've assembled it. Now we build the surface that makes it matter to a real person.

---

## 2. Target User

**Primary:** Insured patients on employer-sponsored or ACA plans (Aetna, BCBS, Cigna, UHC) who are planning an elective or semi-elective procedure and want to know what it will cost before they schedule.

**Secondary:** Employees at self-insured companies steered to the platform by their benefits team.

**Persona:** "Joe Schmoe" — 38 years old, Aetna PPO, $1,400 deductible remaining, planning a knee replacement. He's been quoted wildly different prices by three different people and has no idea who to believe. He just wants a number and a name.

---

## 3. Product Pillars

| Pillar | Description |
|---|---|
| **Real prices** | Negotiated rates from CMS MRFs — not billed charges, not averages |
| **Your cost** | OOP calculated from your specific plan's deductible, coinsurance, and OOP max |
| **Best provider** | Quality-weighted ranking with cost, volume, outcomes, and proximity |
| **Full episode** | Pre-op through post-op cost breakdown — no surprise bills |
| **Your doctors** | Surgeons affiliated with each hospital, with procedure volume and credentials |

---

## 4. UI Architecture

### 4.1 Top Bar / Header

- **Left:** AnaCare logo (large, upper-left corner)
- **Center-left:** User name displayed — e.g., `Joe Schmoe` — styled exactly like Charta's user header
- **Center-right:** Plan badge — e.g., `Aetna` — displayed as a labeled pill/box in the top bar, exactly like Charta's plan header box
- **Style:** Thin, clean, dark — no clutter

### 4.2 Hero Section

**Button flow (Figma-style):**
`AnaCare Logo` → `Compare Providers & Costs` → `Discover care options and estimate your out-of-pocket costs before you choose`

**Headline (user picks one — default to Option 2):**
1. Compare real prices, estimate your out-of-pocket, and find the best care
2. **Compare real prices, estimate your cost, and find the best provider** ← default
3. Compare real prices, see your cost, and pick the right provider

**Style:** Minimalist, premium, thin font weight. Dark background. Soft gradient. No hero image — the data is the visual.

---

## 5. Step 1 — Procedure Selection

### 5.1 Category Hover Interaction

- Left panel shows major procedure categories (e.g., Orthopedic, Cardiac, Spine, General Surgery, etc.)
- On hover over a category, a right-side dropdown panel slides in with specific procedures in that category
- User can select one or more procedures ("select all that apply")
- Moving cursor back to left panel collapses the right-side dropdown
- Hovering a different category collapses the previous dropdown and opens a new one
- This is a pure CSS/JS hover — no clicks required to open

### 5.2 CPT Code Display

- As user selects procedures, selected CPT codes appear at the bottom of the procedure panel
- Display format: `[Procedure Name] — CPT [code]`
- Multiple selections stack cleanly
- User can deselect from this bottom bar

### 5.3 Procedure Categories (Initial Set)

| Category | Example Procedures |
|---|---|
| Orthopedic | Knee Replacement, Hip Replacement, ACL Reconstruction, Rotator Cuff Repair, Spinal Fusion |
| Cardiac | Coronary Angioplasty, Cardiac Catheterization, Pacemaker Implant, CABG |
| Spine | Lumbar Discectomy, Cervical Fusion, Laminectomy |
| General Surgery | Appendectomy, Cholecystectomy, Hernia Repair, Colectomy |
| GI | Colonoscopy, Upper Endoscopy, Hemorrhoid Banding |
| Oncology | Mastectomy, Prostatectomy, Tumor Excision |
| Imaging | MRI (Knee, Hip, Spine, Brain), CT Scan, X-Ray |
| Women's Health | Hysterectomy, C-Section, Fibroid Removal |
| Urology | Prostatectomy, Kidney Stone Removal, Cystoscopy |
| Neurology | Carpal Tunnel Release, Spinal Cord Stimulator |

---

## 6. Step 2 — Location

### 6.1 Location Permission Modal

- On entry, display a browser location permission modal: "Allow AnaCare to use your location to find nearby providers"
- If granted: use browser geolocation (lat/lng), convert to zip code on backend
- If denied: fallback to manual zip code entry field

### 6.2 Zip Code Fallback

- Simple input: "Enter your zip code"
- Validation: 5-digit US zip codes only
- When zip is used instead of GPS, distance weighting is identical — no penalty for zip-based users

### 6.3 Radius Dropdown

- Options: `10 miles` | `25 miles` (default) | `50 miles` | `100 miles` | `Any distance`
- Default: 25 miles
- "Any distance" returns all in-network providers nationally, sorted by distance ascending

---

## 7. Step 3 — Plan & Benefits

### 7.1 Plan ID Dropdown

- Dropdown lists all supported insurance plans
- Format: `Plan Name (Individual)` or `Plan Name (Family)`
- Plans are grouped by payer (Aetna, BCBS, Cigna, UHC, etc.)
- Everything about the plan is stored on backend — user never enters coinsurance or OOP max manually

**Initial plan set:** All Aetna IL individual and family PPO/HMO plans from HealthCare.gov 2026 landscape file, then expanded nationally.

### 7.2 Deductible Remaining

- Input field: `Deductible Remaining ($)`
- Question mark button (?) opens a modal: step-by-step directions on how to find deductible remaining in the member portal
- If blank: system shows cost range (best case / worst case) with label "Deductible status unknown"

### 7.3 OOP Max Remaining

- Input field: `Out-of-Pocket Maximum Remaining ($)`
- Same question mark (?) button with directions for finding OOP max remaining in member portal

### 7.4 Plan Info Button

- Small `?` icon next to plan dropdown
- Opens a modal / drawer showing full plan details in a clean table:

| Field | Value |
|---|---|
| Plan Name | Aetna PPO Gold IL 2026 |
| Deductible (Individual) | $1,500 |
| Deductible (Family) | $3,000 |
| OOP Max (Individual) | $6,000 |
| OOP Max (Family) | $12,000 |
| Coinsurance | 20% after deductible |
| Primary Care Copay | $25 |
| Specialist Copay | $50 |
| ER Copay | $300 |
| Urgent Care Copay | $75 |
| Network Type | PPO |
| Rx Tier 1 Copay | $10 |
| Rx Tier 2 Copay | $35 |
| Rx Tier 3 Copay | $70 |

---

## 8. Results — Provider Rankings

### 8.1 Header

- `X providers found` — exact count stays visible throughout
- `Showing top 6 of X providers · Sorted by Best Value`

### 8.2 Sort Tabs

```
[ Best Value ]  [ Lowest Cost ]  [ Top Rated ]  [ Nearest ]
```

- Switching tabs re-sorts from the beginning (resets to top 6 shown)
- Default: Best Value (composite score: cost 60% + quality 40%)

### 8.3 Progressive Disclosure

- Initial: top 6 results shown
- `Show more options` → expands to 9, button becomes `Show fewer options` (collapses to 6)
- `Show more options` again → expands to 12
- Pattern continues in increments of 3, indefinitely
- Collapse always goes back to previous state (12→9, 9→6, etc.)
- Each sort tab switch resets to top 6 shown

### 8.4 Ranking Score Increments

- Best Value score displayed as a percentile or composite score
- Displayed in 2.5% increments (not 5%) for finer granularity
- Example: `92.5 / 100` or displayed as a progress bar at 2.5% resolution

### 8.5 Provider Card

Each card displays:
- Hospital name + CMS star rating
- Distance from user
- `Estimated Out-of-Pocket: $X,XXX`
- `Negotiated Rate: $XX,XXX`
- Quality score (0–100) with badge
- Volume badge: e.g., `312 procedures/year`
- Sort tag: e.g., `Best Value · #1 in your area`
- `View Details` button → opens detail drawer with full cost breakdown + affiliated doctors

---

## 9. Cost Breakdown — "Show Your Work"

This is the core transparency feature. Every estimate is fully decomposed.

### 9.1 Surgery Day Bundle

| Component | Amount |
|---|---|
| Facility / OR fee | $X,XXX |
| Surgeon fee | $X,XXX |
| Anesthesia (~18% of surgeon fee) | $XXX |
| Implant / device (if applicable) | $X,XXX |
| **Total negotiated rate** | **$XX,XXX** |

### 9.2 Full Cost Timeline (3 Phases)

#### Phase 1 — Pre-Op (Weeks to Months Before Surgery)

| Item | CPT | Visits | Cost Each | Total |
|---|---|---|---|---|
| Surgeon consult | 99214 | 1–2 | $280 | $280–$560 |
| Knee MRI | 73721 | 1 | $850 | $850 |
| Pre-op labs (metabolic panel) | 80053 | 1 | $120 | $120 |
| CBC | 85025 | 1 | $45 | $45 |
| EKG | 93000 | 1 | $85 | $85 |
| Chest X-ray | 71046 | 1 | $65 | $65 |
| Anesthesia pre-op consult | 99213 | 1 | $180 | $180 |
| **Phase 1 Total** | | | | **~$1,625** |

#### Phase 2 — Surgery Day

*(as in 9.1 above)*

#### Phase 3 — Post-Op (Days to Months After Surgery)

| Item | CPT/HCPCS | Quantity | Cost Each | Total |
|---|---|---|---|---|
| Follow-up visits | 99213 | 3–4 visits | $180 | $540–$720 |
| Physical therapy | 97110/97112 | 20 sessions | $135–$185 | $2,700–$3,700 |
| X-ray follow-up | 73560 | 2 | $120 | $240 |
| Knee brace (DME) | L1820 | 1 | $95 | $95 |
| Crutches (DME) | E0110 | 1 | $65 | $65 |
| Rx: Oxycodone (generic) | | 1 fill | $45 | $45 |
| Rx: Xarelto | | 1 fill | $35 | $35 |
| Rx: Celecoxib (generic) | | 1 fill | $25 | $25 |
| **Phase 3 Total** | | | | **~$3,745–$4,925** |

### 9.3 Complication Risk Overlay

- Display hospital's actual complication rate vs. national average (from CMS COMP_HIP_KNEE)
- Toggle: `Base estimate` / `If complications occur (X% risk at this hospital)`
- Complication scenario adds estimated $12,000 expected complication cost × hospital's complication rate

### 9.4 What IS and IS NOT Included

**Clearly labeled section: "What's in this estimate"**
- Surgery day bundle (facility + surgeon + anesthesia + implant)
- Standard post-op PT sessions (procedure-specific count)
- Standard post-surgical Rx medications
- Typical follow-up visits

**Clearly labeled section: "Not included in this estimate"**
- Pre-op imaging if already done (MRI, CT)
- Pre-op lab work if already done
- Second opinion visits
- Home health aide
- DME beyond standard kit
- Complications or readmission
- Any out-of-network cost if provider isn't fully in-network
- Pathology/lab fees from surgery

### 9.5 Disclaimer (Required)

> *"Cost estimates are based on CMS negotiated rate data and your plan's cost-sharing rules. Actual patient responsibility may vary based on claims adjudication, provider billing practices, and plan-specific rules. This is not a guarantee of payment. Estimates are for planning purposes only."*

---

## 10. Affiliated Doctors (Within Each Hospital)

### 10.1 Doctor Card (Inside Hospital Detail View)

Each hospital's detail drawer includes a "Doctors at this hospital" section.

**Doctor card fields:**
- Full name + credentials (MD, DO, etc.)
- Specialty (from NPPES taxonomy)
- Annual procedure volume for the selected CPT code (from Medicare Part B data)
- Years in practice (derived from NPI enumeration date in NPPES)
- Practice address / affiliated location
- "Top performer" badge if in top quartile for volume in region

### 10.2 Data Sources for Doctor Profiles

| Data Element | Source |
|---|---|
| NPI, specialty, taxonomy | NPPES NPI Registry full monthly bulk download |
| Surgeon name, credentials | NPPES |
| Annual procedure volume (by CPT) | Medicare Part B Physician & Other Practitioners by Provider and Service (2023, most recent available) |
| Hospital affiliation | CMS Facility Affiliation Data (dataset 27ea-46a8) — NPI → facility CCN mapping |
| Fallback affiliation | City + state + procedure overlap match (for ~40–60% of surgeons not in Facility Affiliation data) |

### 10.3 Join Logic

```
Part B (NPI + CPT volume)
  + NPPES (name, credentials, years in practice)
  + Facility Affiliation (NPI → hospital CCN)
  = Surgeon card attached to specific hospital for specific procedure
```

---

## 11. Data Sources & Ingestion Plan

### 11.1 Required Datasets

| Dataset | URL | Use |
|---|---|---|
| CMS MPFS 2026 (Jan release) | cms.gov/medicare/payment/fee-schedules/physician | Pre-op/post-op CPT code rates (PPRRVU26_JAN.xlsx) |
| CMS DMEPOS Fee Schedule | cms.gov/medicare/payment/fee-schedules/durable-medical-equipment | DME costs (crutches, walker, brace, CPM machine) |
| Medicare Part B by Provider & Service 2023 | data.cms.gov — provider-summary-by-type-of-service | Surgeon NPI, CPT volumes, specialty, city/state |
| NPPES NPI Registry (full monthly) | download.cms.gov/nppes/NPI_Files.html | Surgeon name, credentials, taxonomy, NPI date (~8GB) |
| CMS Facility Affiliation Data | data.cms.gov — dataset 27ea-46a8 | NPI → hospital CCN mapping |
| CMS Hospital General Information | data.cms.gov — dataset xubh-q36u | CCN → hospital name, city, state, CMS star rating |
| CMS Hospital Complications & Deaths | data.cms.gov — dataset yc9t-dgbk | COMP_HIP_KNEE, PSI_11, MORT_30_CABG per hospital |
| CMS Hospital Readmissions | data.cms.gov — dataset 9n3s-kdb3 | Hospital-wide readmission ratio |
| RAND Hospital Price Transparency v5.1 | rand.org/pubs/research_reports/RRA1144-2.html | Hospital-specific RAND multiplier (commercial-to-Medicare ratio) |
| HealthCare.gov 2026 Plan Landscape | healthcare.gov — health-and-dental-plan-datasets | Plan deductibles, OOP max, coinsurance by metal tier and state |
| Aetna MRF (and other payers) | Payer transparency index files | Negotiated rates by NPI, plan, CPT |

### 11.2 EPISODE_COSTS Data Structure

```python
EPISODE_COSTS = {
  "knee_replacement": {
    "proc_id": "knee_replacement",
    "cpt_primary": "27447",
    "preop": [
      { "name": "Surgeon consult", "cpt": "99214", "cost": 280, "visits": 1 },
      { "name": "Knee MRI", "cpt": "73721", "cost": 850, "visits": 1 },
      { "name": "Pre-op labs", "cpt": "80053", "cost": 120, "visits": 1 },
      { "name": "CBC", "cpt": "85025", "cost": 45, "visits": 1 },
      { "name": "EKG", "cpt": "93000", "cost": 85, "visits": 1 },
      { "name": "Anesthesia consult", "cpt": "99213", "cost": 180, "visits": 1 },
    ],
    "surgery": {
      # negotiated_rate derived from CMS MPFS × RAND multiplier
      # broken into: facility, surgeon, anesthesia, implant
    },
    "postop": [
      { "name": "Follow-up visits", "cpt": "99213", "cost": 180, "visits": 3 },
      { "name": "PT (therapeutic exercise)", "cpt": "97110", "sessions": 20, "cost_per_session": 155 },
      { "name": "PT (neuromuscular re-ed)", "cpt": "97112", "sessions": 5, "cost_per_session": 155 },
      { "name": "X-ray follow-up", "cpt": "73560", "cost": 120, "visits": 2 },
      { "name": "Knee brace", "hcpcs": "L1820", "cost": 95 },
      { "name": "Crutches", "hcpcs": "E0110", "cost": 65 },
      { "name": "Rx: Oxycodone", "cost": 45, "fills": 1 },
      { "name": "Rx: Xarelto", "cost": 35, "fills": 1 },
      { "name": "Rx: Celecoxib", "cost": 25, "fills": 1 },
    ],
    "complication_risk_field": "COMP_HIP_KNEE",
    "complication_cost_avg": 12000,
    "pt_sessions": 20,
  },
  # ... all 47 procedures
}
```

All CPT rates sourced from CMS MPFS 2026 (PPRRVU26_JAN.xlsx). All HCPCS rates from CMS DMEPOS schedule.

### 11.3 CPT Reference Table for Pre/Post-Op Components

| Component | CPT / HCPCS |
|---|---|
| Office visit (established) | 99213, 99214 |
| Knee MRI | 73721 |
| Hip X-ray | 73502 |
| Spine MRI | 72148 |
| Brain MRI | 70553 |
| Pre-op labs (metabolic panel) | 80053 |
| CBC | 85025 |
| EKG | 93000 |
| Chest X-ray | 71046 |
| PT therapeutic exercise | 97110 |
| PT neuromuscular re-education | 97112 |
| Crutches | E0110 |
| Knee brace | L1820 |
| Walker | E0130 |
| CPM machine | E1800 |

---

## 12. OOP Calculation Engine

### 12.1 Formula

```
if deductible_remaining > 0:
    patient_pays_first = min(negotiated_rate, deductible_remaining)
    remaining_after_deductible = max(0, negotiated_rate - deductible_remaining)
    coinsurance_portion = remaining_after_deductible * coinsurance_pct
    total_oop = patient_pays_first + coinsurance_portion
else:
    total_oop = negotiated_rate * coinsurance_pct

out_of_pocket = min(total_oop, oop_max_remaining)
```

### 12.2 Applied Across All 3 Phases

- OOP calculation applied to each line item in pre-op, surgery, and post-op
- OOP max cap applied to the cumulative sum across all phases
- Display: "You've hit your OOP max — remaining costs are $0" when applicable
- Rx copay uses plan's tier-specific copay (not coinsurance)

---

## 13. Geographic Coverage

### 13.1 National by Default

This platform works for **every US zip code** from launch. No city restriction.

Implementation:
- All CMS data is national — load nationally, query by location
- MPFS and DMEPOS rates are national (Medicare doesn't vary by state for most codes)
- MRF data ingested by plan, not by city — Aetna national PPO files cover all markets
- Provider search uses PostGIS or Haversine distance query from user's lat/lng or zip centroid

### 13.2 Zip-to-Lat/Lng

- Preload zip code centroid table (free, public domain — Census ZCTA centroids)
- All radius searches use lat/lng bounding box + Haversine distance
- Distance is always in miles (US market)

---

## 14. System Architecture

### 14.1 Frontend

- Single-page app (React or pure HTML/CSS/JS depending on complexity)
- Dark, minimalist design — Stripe/Linear/Vercel aesthetic
- Thin font weight throughout (Inter or similar)
- Mobile responsive
- No unnecessary dependencies
- Pure CSS hover interactions for procedure category panel
- Provider cards are CSS Grid

### 14.2 Backend

- REST API (FastAPI or Node/Express)
- PostgreSQL with PostGIS extension for geo queries
- Redis cache: NPI metadata, plan data, quality scores
- Separate ingestion pipeline (Python scripts, async workers)

### 14.3 Database Schema (Key Tables)

```sql
-- Negotiated rates from MRF
rates (npi, plan_id, cpt_code, rate, rate_type, effective_date, source_file, ingested_at)

-- Provider master
providers (npi, name, specialty, taxonomy, credentials, address, city, state, zip, lat, lng, npi_enum_date)

-- Hospital / facility master
hospitals (ccn, name, city, state, zip, lat, lng, cms_star_rating, rand_multiplier)

-- Surgeon ↔ hospital affiliation
affiliations (npi, ccn, source)  -- source: 'cms_affiliation' | 'city_state_fallback'

-- Surgeon procedure volume
surgeon_volume (npi, cpt_code, annual_volume, year)

-- Hospital quality signals
hospital_quality (ccn, measure_id, score, national_avg, year)

-- Insurance plans
plans (plan_id, plan_name, payer, metal_tier, network_type, state, deductible_ind, deductible_fam, oop_max_ind, oop_max_fam, coinsurance_pct, pc_copay, specialist_copay, er_copay, uc_copay, rx_tier1, rx_tier2, rx_tier3)

-- Zip code centroids
zipcodes (zip, city, state, lat, lng)
```

### 14.4 Infrastructure

- **Railway / Render / Fly.io** for initial deployment (fast to ship)
- **PostgreSQL** with PostGIS
- **Redis** for caching
- **S3 / Cloudflare R2** for raw data storage
- **Background workers** for MRF ingestion and data refresh

---

## 15. Quality Scoring Model

### 15.1 Hospital Quality Score (0–100)

| Signal | Weight | Source |
|---|---|---|
| CMS outcome rating (star) | 35% | CMS Hospital General Info |
| Procedure-specific complication rate | 25% | CMS Complications & Deaths |
| Patient satisfaction (HCAHPS) | 20% | CMS Care Compare |
| Readmission ratio | 15% | CMS Readmissions |
| Procedure volume (log-scaled) | 5% | Medicare Part B claims |

### 15.2 Surgeon Quality Signals

- Annual procedure volume (primary signal — high volume = better outcomes)
- Years in practice (NPI enumeration date → years since first enumeration)
- Specialty board alignment (taxonomy code matches procedure type)
- No quality score displayed if data coverage < 40% for a procedure + region

### 15.3 Ranking Score (2.5% Increments)

```
rank_score = (cost_weight × cost_percentile) + (quality_weight × quality_percentile)
```
- Default weights: cost 60%, quality 40%
- Displayed at 2.5% resolution (e.g., 87.5 / 100, not rounded to 85 or 90)
- User-adjustable via slider: "Prioritize cost" ↔ "Prioritize quality"

---

## 16. Feature Flags & Phased Rollout

| Feature | Phase |
|---|---|
| Aetna plans, all US zip codes, top 10 procedures | v1 |
| BCBS, Cigna, UHC plans | v2 |
| All 47 procedures | v2 |
| Full pre-op/post-op cost timeline | v1 |
| Affiliated doctor cards | v1 |
| Complication risk toggle | v1 |
| Employer SSO + auto-populate plan data | v2 |
| Real-time deductible from payer API (FHIR) | v3 |
| Mobile app (React Native) | v3 |

---

## 17. Milestones (Re-sequenced for Solo Founder + AWS + Real Data)

Ordered by dependency. Data pipeline must run in parallel with UI build from day 1.

| Milestone | Deliverable | Week Target |
|---|---|---|
| M0 | AWS infra: S3 bucket + Aurora PostgreSQL (PostGIS) + ECS cluster + IAM roles | Week 1 |
| M1 | Aetna MRF index fetch: `fetch_mrf_index.py` downloads and parses TOC JSON | Week 1–2 |
| M2 | MRF streaming ingest: `stream_mrf_file.py` filters to CPT 27447 (knee), loads rates to Aurora | Week 2–4 |
| M3 | CMS data ingestion: Hospital General Info, Complications, Readmissions, RAND multiplier → Aurora | Week 3–4 |
| M4 | NPPES + Part B + Facility Affiliation ingestion → providers, surgeon_volume, affiliations tables | Week 4–6 |
| M5 | HealthCare.gov 2026 plan landscape → plans table (all Aetna IL plans to start) | Week 4–5 |
| M6 | Zip centroid table (Census ZCTA) → zipcodes table + PostGIS radius query working | Week 4 |
| M7 | EPISODE_COSTS data structure for Knee Replacement (27447): pre-op + surgery + post-op, all CPT rates from MPFS 2026 | Week 5–6 |
| M8 | OOP engine: full formula per line item, cumulative OOP max cap, Rx copay tiers | Week 6–7 |
| M9 | React UI scaffold: header (logo + user name + plan badge), hero section, procedure hover/accordion selector | Week 5–6 |
| M10 | Plan dropdown + deductible/OOP inputs + plan info modal + ? buttons with portal directions | Week 6–7 |
| M11 | Provider ranking results: sort tabs, progressive disclosure (6→9→12), 2.5% score increments, slider | Week 7–8 |
| M12 | Cost breakdown drawer: surgery bundle + 3-phase timeline + complication toggle + what's included/not | Week 8–9 |
| M13 | Surgeon cards within hospital detail: NPPES name + credentials + Part B volume + affiliation | Week 9–10 |
| M14 | Expand EPISODE_COSTS to remaining 9 procedures (hip, colonoscopy, ACL, etc.) | Week 10–11 |
| M15 | End-to-end demo: Joe Schmoe, knee replacement, 25 miles, Aetna PPO Gold IL, real MRF rates | Week 12 |

### MRF Ingestion Approach (Best Practice for Solo + AWS)

The Aetna MRF index JSON lists hundreds of file URLs. Do NOT download every file. The correct approach:

1. `fetch_mrf_index.py` — Download Aetna's table-of-contents JSON (small file, ~MB). Parse to get list of in-network file URLs.
2. Filter URLs to relevant plan types (PPO, national plans) — skip dental, vision, etc.
3. `stream_mrf_file.py` — For each file URL: stream with `ijson`, extract only records where `billing_code` is in your target CPT set (27447, 27130, etc.). Write matching records to S3 as compressed JSONL. Never load the full file into memory.
4. `load_rates_db.py` — Load the filtered S3 JSONL files into Aurora `rates` table.
5. Run ECS Fargate tasks for parallelism — multiple files streamed simultaneously.

This approach lets a single EC2/ECS task process a 200GB MRF file using ~500MB RAM.

---

## 18. Success Metrics

| Metric | Target |
|---|---|
| Zip codes supported | All US (33,000+ zip codes) |
| Plans in dropdown | All ACA + employer Aetna plans (start), then BCBS/Cigna/UHC |
| Procedures supported | 10 at launch, 47 by v2 |
| OOP estimate accuracy vs. EOB | ±20% for 80% of cases (improves with FHIR accumulator integration) |
| Cost timeline completeness | Pre-op + surgery + post-op for all 10 launch procedures |
| Provider results latency | <2 seconds p95 |
| Doctor cards per hospital | Coverage for ≥60% of hospitals via Facility Affiliation; remainder via fallback |
| Design partner signed | 1 self-insured employer or benefits broker within 60 days of M10 |

---

## 19. Open Questions

1. **Authentication:** Does v1 require login (user account to save plan data) or is it stateless (enter plan details each session)? Recommendation: stateless v1, optional account creation v2.
2. **RAND multiplier per hospital:** Already in existing data — confirm which hospitals have RAND multiplier populated vs. needing national average fallback.
3. **MRF priority:** Aetna national PPO first, then state-specific HMO plans. Confirm which plan IDs map to which MRF files.
4. **Facility Affiliation coverage gap:** ~40–60% of surgeons covered. For the rest, fallback is city+state+procedure overlap. Document which procedures and markets have lowest coverage and flag for user.
5. **Rx copay tiers:** Confirm tier classification for each Rx item across all supported plans (generic vs brand vs specialty).
6. **Plan data storage:** Plan data from HealthCare.gov landscape is public — store in `plans` table. Deductible remaining and OOP remaining are user-entered per session and never persisted.

---

## 20. Compliance & Disclaimers

**Data sources:** All public CMS data under the Transparency in Coverage rule (45 CFR Part 158) and CMS open data terms of use.

**No PHI stored:** Plan accumulator data (deductible remaining, OOP remaining) is entered by the user per session and never written to disk or database.

**Required disclaimer on all cost estimates:**
> *"Cost estimates are based on CMS negotiated rate data and plan cost-sharing rules you provided. Actual patient responsibility may vary based on claims adjudication, provider billing, and plan-specific rules. This is not a guarantee of payment or a quote from your insurer. Estimates are for planning purposes only."*

**HIPAA:** No BAA required for v1. No PHI is collected or stored. MRF rate data and quality scores are not PHI.
