# CAT Power Solution — Claude Code Project Guide

## Project Overview
Prime power sizing platform for AI Data Centers and Industrial projects.
**Owner:** Francisco Saraiva — LEPS Global, Caterpillar Electric Power
**Version:** 4.0 | **Python:** 3.11+ | **Framework:** FastAPI + Streamlit

## Critical Rules
- **NEVER modify files in `core/`** — This is validated CAT IP. Any change requires full test suite re-validation.
- **NEVER commit `.env`** — Only `.env.example` goes in the repo. Secrets stay local.
- **NEVER modify `api/schemas/`** unless absolutely necessary — These define the API contract.

## Architecture

```
core/                  ← Calculation engine (16 functions) — DO NOT TOUCH (except proposal modules)
  engine.py            ← Derating tables, LCOE, availability, emissions, etc.
  generator_library.py ← 10 CAT generator models with full specs
  pdf_report.py        ← ReportLab PDF generation (executive + comprehensive)
  project_manager.py   ← INPUT_DEFAULTS (76 inputs), TEMPLATES, COUNTRIES, HELP_TEXTS
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
    sizing_pipeline.py ← Full sizing orchestration (resolve → derate → BESS → fleet → LCOE)
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
  test_engine.py       ← 48 unit tests for core engine (2 pre-existing failures)
  test_api.py          ← 7 API smoke tests (auth, RBAC, health, sizing integration)
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
4. **Economics** — gas price, WACC, region, BESS costs, footprint
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

## Running the Project

```bash
# Development (API only)
REQUIRE_AUTH=false python -m uvicorn api.main:app --reload --port 8000

# Development (API + Frontend)
start-dev.bat

# Streamlit demo (local)
streamlit run streamlit_app.py

# Tests
pytest tests/test_engine.py -v      # Engine tests (46/48 pass)
pytest tests/test_api.py -v         # API smoke tests (7/7 pass)

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

## Sizing Pipeline Flow
1. Resolve generator → 2. Calculate loads → 3. Site derating (CAT tables) →
4. BESS sizing → 5. Spinning reserve → 6. Fleet optimization →
7. Three reliability configs (A/B/C) → 8. Availability (Binomial N+X) →
9. Voltage recommendation → 10. Transient stability → 11. Emissions →
12. Footprint → 13. Financial (CAPEX/OPEX/LCOE/NPV)

## Common Tasks
- **Add a new generator:** Edit `core/generator_library.py` GENERATOR_LIBRARY dict
- **Add a new template:** Edit `core/project_manager.py` TEMPLATES dict
- **Add a new endpoint:** Create in appropriate router, add Pydantic schema, add auth
- **Change default inputs:** Edit `core/project_manager.py` INPUT_DEFAULTS
- **Add a wizard step field:** Add widget in `render_wizard_step_N()`, add key to `_build_inputs_from_wizard()`
- **Change proposal defaults:** Edit `core/proposal_defaults.py` PROPOSAL_DEFAULTS dict
- **Modify proposal document:** Edit `core/proposal_generator.py` section builders (`_build_section_*`)
- **Run full sizing test:** `pytest tests/test_api.py::TestSizingIntegration -v`
- **Run proposal tests:** `pytest tests/test_proposal.py -v` (43 tests)

## Local Working Directory
- **Primary (outside OneDrive):** `C:\Users\juans\CAT Power Solution`
- **GitHub repo:** `juansaraiva-arch/CAT-Power-Solution`
- **Do NOT use the OneDrive copy** — causes sync/mmap issues with git
