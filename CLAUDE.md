# CAT Power Solution — Claude Code Project Guide

## Project Overview
Prime power sizing platform for AI Data Centers and Industrial projects.
**Owner:** Francisco Saraiva — LEPS Global, Caterpillar Electric Power
**Version:** 5.0 | **Python:** 3.11+ | **Framework:** FastAPI + Streamlit

## Critical Rules
- **NEVER modify files in `core/`** — This is validated CAT IP. Any change requires full test suite re-validation and Francisco's explicit authorization.
- **NEVER commit `.env`** — Only `.env.example` goes in the repo. Secrets stay local.
- **NEVER modify `api/schemas/`** unless absolutely necessary — These define the API contract.

## Architecture

```
core/                  ← Calculation engine — DO NOT TOUCH without authorization
  engine.py            ← Derating, LCOE, availability, emissions, pod fleet optimizer, SR calculation
  generator_library.py ← 10 CAT generator models with full specs (incl. prime_power_kw, mtbf, mttr)
  pdf_report.py        ← ReportLab PDF generation (executive + comprehensive)
  project_manager.py   ← INPUT_DEFAULTS (83+ inputs incl. CAPEX BOS adders), TEMPLATES, COUNTRIES, HELP_TEXTS
  proposal_defaults.py ← Default values, dropdown options for proposal form (PROPOSAL_DEFAULTS, INCOTERM_OPTIONS, etc.)
  proposal_generator.py← DOCX proposal generation with Caterpillar branding, uses python-docx

api/                   ← FastAPI REST API
  main.py              ← App factory, CORS, rate limiting (slowapi), audit middleware
  config.py            ← Centralized settings via pydantic-settings (reads .env)
  auth.py              ← Entra ID JWT validation + role-based access (demo/full/admin)
  dependencies.py      ← Shared FastAPI deps (generator resolver, auth re-exports)
  routers/
    health.py          ← Public (no auth) — /api/v1/health, /api/v1/version
    generators.py      ← require_role("demo") — generator library CRUD
    projects.py        ← require_role("demo") — templates, defaults, countries
    engine.py          ← require_role("full") — 16 individual calculation endpoints
    sizing.py          ← require_role("full") — /sizing/full, /sizing/quick
    reports.py         ← require_role("full") — PDF generation
  schemas/             ← Pydantic models (SizingInput, SizingResult, etc.)
  services/
    sizing_pipeline.py ← Full sizing orchestration (resolve → derate → BESS → pod fleet → LCOE)
    generator_resolver.py ← Resolve model name + overrides to gen_data dict

streamlit_app.py       ← Streamlit Cloud demo app (calls core directly, no API needed)
security_config.py     ← Streamlit auth gate (email + OTP + password)
auth_db.py             ← JSON-based user store for Streamlit auth
auth_otp.py            ← OTP generation/verification
auth_email.py          ← SMTP email delivery for OTP codes

db/
  schema.sql           ← PostgreSQL 15+ (projects, audit_log, equipment_pricing + RLS)
  migrations/          ← Future migration scripts

assets/
  logo_caterpillar.png ← Official Caterpillar logo used in DOCX proposals and Streamlit UI

tests/
  test_engine.py       ← 48 unit tests for core engine (2 pre-existing TransientStability failures)
  test_api.py          ← 7 API smoke tests (require python-multipart — environmental errors in local dev)
  test_proposal.py     ← 43 tests for proposal defaults + DOCX generation
  conftest.py          ← Mock auth fixtures (client_admin, client_full, client_demo, client_anonymous)

static/                ← Pre-built React frontend (served by FastAPI in production)
  assets/
    logo_caterpillar.png ← Logo copy for Streamlit static serving
frontend/              ← React source (Vite + TypeScript + shadcn/ui)
```

## Streamlit App (Demo)
- **Live URL:** https://cat-power-solution.streamlit.app
- **Main file:** `streamlit_app.py` — single-file app with wizard + results dashboard
- **Python on Streamlit Cloud:** 3.13 (cannot be changed; `.python-version` is ignored)
- **Dependencies:** `requirements.txt` — only Streamlit-specific deps (no FastAPI, asyncpg, etc.)
- **API deps separate:** `requirements-api.txt` — for FastAPI server

### Streamlit Wizard Flow
After login, users see a 5-step guided wizard before results:
1. **Project Info** — name, client, location, grid frequency
2. **Load Profile** — template, DC type, IT load, PUE, dynamics, live preview
3. **Site & Technology** — derate (auto/manual), generator, BESS, fuel, voltage
4. **Economics** — gas price, WACC, region, BESS costs, CAPEX BOS adders, footprint
5. **Review & Run** — summary + "Run Sizing" button

After wizard: full sidebar available for fine-tuning, reactive re-sizing on changes.

### Proposal Generation (Tab 📄 Proposal)
After sizing completes, users can generate a professional DOCX proposal:
- **Tab location:** 6th tab in results dashboard ("📄 Proposal")
- **Form fields:** BDM info, dealer, incoterm, delivery, payment terms, offer types, notes
- **Defaults:** `core/proposal_defaults.py` (PROPOSAL_DEFAULTS dict)
- **Generator:** `core/proposal_generator.py` → `generate_proposal_docx()`
- **Output:** Branded .docx with Caterpillar logo, 7 sections + 7 appendices
- **Logo:** `assets/logo_caterpillar.png` (official Caterpillar wordmark)

### Wizard Session State Keys
- `_wizard_step` (int 0-4), `_wizard_complete` (bool), `_wizard_running` (bool)
- All wizard inputs use `_wiz_` prefix (e.g., `_wiz_p_it`, `_wiz_dc_type`)
- Sidebar widgets use their own keys — no collision since wizard and sidebar never render together
- `spinning_res_pct` removed from UI (P04) — SR now derived from physical contingencies

## Running the Project

```bash
# Development (API only)
REQUIRE_AUTH=false python -m uvicorn api.main:app --reload --port 8000

# Development (API + Frontend)
start-dev.bat

# Streamlit demo (local)
streamlit run streamlit_app.py

# Tests
pytest tests/test_engine.py -v      # Engine tests (46/48 pass — 2 pre-existing)
pytest tests/test_api.py -v         # API smoke tests (require python-multipart)
pytest tests/test_proposal.py -v    # Proposal tests (43/43 pass)

# Share publicly
start-share.bat                     # Uses ngrok or localtunnel
```

## Key Environment Variables
- `REQUIRE_AUTH` — `false` for local dev, `true` for production (Entra ID JWT)
- `ENABLE_DB_PERSISTENCE` — `false` until PostgreSQL configured
- `ALLOWED_ORIGINS` — CORS whitelist (comma-separated, or `*` for dev)
- `ENVIRONMENT` — `development` | `staging` | `production`

## Authentication & Authorization
- **Streamlit:** Email OTP + password auth via `security_config.py` (JSON user store)
- **API:** Auth disabled locally via `REQUIRE_AUTH=false` → returns mock admin user
- **Three roles:** demo (view generators/templates), full (run sizing/reports), admin (all)
- **Security groups:** SG-CPS-Demo, SG-CPS-Full, SG-CPS-Admin (Entra ID)
- **JWT validation** in `api/auth.py` against Microsoft JWKS endpoint

## Deployment
- **Streamlit Cloud:** Auto-deploys from `main` branch. Uses `streamlit_app.py` as entry.
- **Render:** `render.yaml` blueprint included. Free tier, Python runtime.
- **Azure App Service:** `azure-pipelines.yml` for CI/CD.
- **Docker:** `Dockerfile` + `docker-compose.yml` for local/production.
- **GitHub repo:** `juansaraiva-arch/CAT-Power-Solution`

## Testing Auth in Tests
Use fixtures from `conftest.py`:
- `client_no_auth` — REQUIRE_AUTH=false (dev mode)
- `client_admin` / `client_full` / `client_demo` — mock users with specific roles
- `client_anonymous` — no token, REQUIRE_AUTH=true (tests 401)

## Sizing Pipeline Flow (v5.0 — post-audit)
1. Resolve generator → 2. Calculate loads (p_total_peak = p_avg × PAR) →
3. Site derating (CAT tables, validated vs EM7206-05-001 P11) → 4. BESS sizing →
5. Spinning reserve (physical: max(load_step, N-1) — BESS credit validated) →
6. **Pod fleet optimizer** (N+1 pod architecture, prime/standby loading) →
7. Availability (Binomial) → 8. Voltage recommendation →
9. Transient stability (coupled to SR load_step_mw) →
10. Frequency screening (inertia H from library) → 11. Emissions →
12. Footprint → 13. Financial (CAPEX with BOS + LCOE corrected denominator) →
14. **Electrical sizing** (P08/P09 — see below)

### Electrical Sizing Module (`api/services/electrical_sizing.py`)
Called from `sizing_pipeline.py` after pod fleet optimizer. Parameters:
- `n_pods`, `n_per_pod`, `P_gen_mw` — from pod fleet result
- `p_load_mw` — actual peak load (`p_total_peak`), **not** nameplate (P09 fix)
- `V_gen_kv` (13.8), `pf` (0.8), `z_trafo_pu` (0.0575), `xd_subtrans_pu` (0.20)

**MV Bus (13.8 kV):** Sized for pod-pair contingency transfer (N+1 pod architecture).

**Transformers:** One per pod pair (`n_t = n_pods // 2`), MVA = `P_pod_pair / pf`.

**HV Collector Bus:** Evaluated at 34.5 / 69 / 138 kV. Bus current uses `p_load_mw` (actual load), not installed nameplate. Auto-selects lowest voltage where both ampacity and ISC are within limits.

**HV ISC Model (`_isc_one_group`):** Each trafo+gen group referred to HV bus. All groups in parallel for total fault current.

**MV ISC Ring Bus Model (`_isc_mv_ring_bus`, P09):** Fault at 13.8 kV bus receives:
1. LOCAL — own pod's generators in parallel (direct connection)
2. REMOTE — all other pods via 2 transformers in series (step-up → ring → step-down)

Validated against 5 CAT schemas: S1–S5 (25.5 kA to 52.2 kA symmetrical). Breaker selection per ANSI C37 ratings [16, 25, 31.5, 40, 50, 63, 80 kA].

### Frequency Screening — Inertia Fields
The `frequency_screening` dict returned by `calculate_frequency_screening()` in `core/engine.py` includes:
- `H_per_unit` — mechanical inertia constant from the generator library (e.g., 1.2 s for G3516H)
- `H_bess` — virtual inertia from BESS (0 if no BESS; up to 4.0 s via heuristic `4.0 × min(1, bess_ratio/0.2)`)
- `H_total` — sum of `H_per_unit + H_bess` (system-level inertia for swing equation screening)
- `H_system` — alias for `H_total` (backward compat from P06)

The Streamlit UI displays all three H components separately with a warning if `H_per_unit > 2.0 s` (atypical for recip gas engines).

### Fleet Maintenance Configs (P12)
`calculate_fleet_maintenance_configs()` in `core/engine.py` — produces three alternative fleet configurations satisfying **C4** (N+1 pod capacity minus generators in scheduled maintenance ≥ peak load).

**Constraint C4:** `(N_pods−1) × n_per × P_gen − max_maint × P_gen ≥ P_peak`

| Config | Strategy | Description |
|--------|----------|-------------|
| A — Distributed | min n_total, max n_pods | More smaller pods, same or fewer gens |
| B — Conservative | same n_pods as base | Add gens to existing topology, no electrical changes |
| C — Balanced | base_n_pods + 1 | One extra pod, moderate gen increase |

**Parameters:** `max_maintenance_units` (default 1), `selected_fleet_config_maint` (default 'B').
The base `pod_fleet_optimizer()` also enforces C4 via `max_maintenance_units` kwarg (default 0 = backward compatible).

### Key Engine Changes (Audit Series P02-P06, March 2026)
| Finding | Fix | Impact |
|---------|-----|--------|
| H1: PAR applied to total DC | `p_peak = p_avg × PAR` | -11% fleet over-sizing |
| H3: SR was free user input | `SR = max(load_step_MW, N-1)` | Physics-based SR |
| H4: BESS SR unconditional | Response time + energy check | Validated credit |
| H5: No pod architecture | Pod fleet optimizer (N+1 pod) | Matches CAT schemas |
| H6: Stability decoupled | Uses same load_step_mw as SR | Coupled |
| H10: CAPEX missing BOS | 7 new line items (~1.72× multiplier) | All-in ~$2,000/kW |
| H10: LCOE double-CF | `mwh_year = p_avg × 8760` | LCOE drops ~11% |

### Generator Library Fields (added P05/P06/P10)
Each of the 10 models now includes:
- `prime_power_kw` — continuous prime power rating (kW)
- `standby_kw` — standby/nameplate rating (kW)
- `mtbf_hours` — mean time between failures (hours)
- `mttr_hours` — mean time to repair (hours)
- `inertia_h` — rotating mass inertia constant (seconds)
- `gas_inlet_pressure_psia` — minimum gas inlet pressure (psia): 5 for high-speed recip, 15 for medium-speed, 200-300 for turbines

### Gas Pipeline Sizing Module (P10)
`calculate_gas_pipeline()` in `core/engine.py` — standalone function (no existing functions modified).

**Parameters:** `p_total_avg_mw`, `hr_op_mj_kwh` (operating-point heat rate from fuel curve), `gen_data`, gas supply/pipeline inputs.

**Monthly Consumption:** Flat model based on capacity factor × days-in-month. Uses operating-point heat rate (part-load), not ISO full-load.

**Pipeline Sizing — Weymouth Equation (US customary):** Solves for minimum diameter D, selects next standard NPS from [2–24] inches. P2 = generator `gas_inlet_pressure_psia`. Velocity check warns if > 60 ft/s. Compressor warning if P1 < P2 (common for gas turbines).

**Result field:** `gas_pipeline: Optional[dict]` on `SizingResult` — contains `monthly_consumption`, `annual_mmbtu`, `daily_mmscfd`, `D_nps_inches`, `needs_compressor`, etc.

### CAPEX BOS Defaults (INPUT_DEFAULTS, added P06)
Applied as % of (generator + installation) base cost:
- `bos_pct`: 17% — MV switchgear, transformers
- `civil_pct`: 13% — foundations, grading, drainage
- `fuel_system_pct`: 6% — gas piping, regulators, metering
- `electrical_pct`: 6% — MV cables, protection relays
- `epc_pct`: 12% — EPC management fee
- `commissioning_pct`: 2.5% — startup
- `contingency_pct`: 10% — applied on subtotal

## Common Tasks
- **Add a new generator:** Edit `core/generator_library.py` GENERATOR_LIBRARY dict (include prime_power_kw, mtbf, mttr)
- **Add a new template:** Edit `core/project_manager.py` TEMPLATES dict
- **Add a new endpoint:** Create in appropriate router, add Pydantic schema, add auth
- **Change default inputs:** Edit `core/project_manager.py` INPUT_DEFAULTS
- **Add a wizard step field:** Add widget in `render_wizard_step_N()`, add key to `_build_inputs_from_wizard()`
- **Change proposal defaults:** Edit `core/proposal_defaults.py` PROPOSAL_DEFAULTS dict
- **Modify proposal document:** Edit `core/proposal_generator.py` section builders (`_build_section_*`)
- **Change CAPEX BOS defaults:** Edit `core/project_manager.py` INPUT_DEFAULTS (bos_pct, civil_pct, etc.)
- **Run full sizing test:** `pytest tests/test_api.py::TestSizingIntegration -v`
- **Run proposal tests:** `pytest tests/test_proposal.py -v` (43 tests)

## Local Working Directory
- **Primary (outside OneDrive):** `C:\Users\juans\CAT Power Solution`
- **GitHub repo:** `juansaraiva-arch/CAT-Power-Solution`
- **Do NOT use the OneDrive copy** — causes sync/mmap issues with git
