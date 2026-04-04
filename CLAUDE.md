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
  project_manager.py   ← INPUT_DEFAULTS (105 keys incl. CAPEX BOS adders), DC_TYPE_DEFAULTS (7 DC types × 7 fields), TEMPLATES, COUNTRIES, HELP_TEXTS, project_to_json(), project_from_json()
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
- **Main file:** `streamlit_app.py` — single-file app with sidebar-only inputs + results dashboard
- **Python on Streamlit Cloud:** 3.13 (cannot be changed; `.python-version` is ignored)
- **Dependencies:** `requirements.txt` — only Streamlit-specific deps (no FastAPI, asyncpg, etc.)
- **API deps separate:** `requirements-api.txt` — for FastAPI server

### Sidebar-Only Architecture (P35 / P47)
Sidebar-only architecture. **No wizard exists** — all wizard code was deleted in P35. Sizing runs reactively on every input change. No `_wiz_*` or `_stored_*` keys (only survivor: `_stored_bess_autonomy_min`).

**3-level progressive disclosure (render_sidebar(), lines 308–1194):**

#### LEVEL 1 — Quick Sizing (always visible, no expander)
After the Unit System and Template dividers, these fields are always visible at the top:
- Unit System radio (Metric / Imperial) — stored to `_unit_sys` session state
- Project Template selectbox — applies `TEMPLATES[name]` values to session state
- **⚡ Quick Sizing subheader**
  - **Data Center Type** selectbox — `key="_dc_type_select"`, `on_change=_on_dc_type_change`; auto-fills Load Profile fields via `_dcdefault_*` session state keys
  - **IT Load (MW)** number_input
  - **Generator Types** multiselect + **Generator Model** selectbox + ISO Rating / Efficiency metrics
  - **Region** selectbox

#### DC_TYPE_DEFAULTS auto-fill mechanism (P47 / P48)
Two-step pattern that avoids Streamlit's "value= ignored after first render" and "key+value conflict" bugs:

**Step 1 — Callback** (`_on_dc_type_change`, fires before next render):
- Reads `st.session_state["_dc_type_select"]`
- Writes `DC_TYPE_DEFAULTS[dc_type][key]` → `st.session_state[f"_dcdefault_{key}"]` for all 7 fields
- Affected fields: `pue`, `capacity_factor`, `peak_avg_ratio`, `load_step_pct`, `avail_req`, `spinning_res_pct`, `load_ramp_req`

**Step 2 — Pre-render transfer block** (runs just before Load Profile expander on every render):
```python
for field, default in _LP_FIELD_DEFAULTS.items():
    dckey = f"_dcdefault_{field}"
    if dckey in st.session_state:
        st.session_state[field] = st.session_state.pop(dckey)  # force DC default
    elif field not in st.session_state:
        st.session_state[field] = default  # seed on first run
```

**Widget pattern:** All 7 Load Profile widgets use `key=field` only — NO `value=` parameter. Streamlit reads from `st.session_state[field]` automatically.

**Why two steps?** Streamlit rule: callbacks cannot write to a widget's `key=` if that widget also specifies `value=` in the same render. The pre-render transfer happens in the script body (before the widget renders), which is safe. Pop'ing `_dcdefault_*` after transfer prevents stale values from persisting across reruns.

`DC_TYPE_DEFAULTS` imported from `core.project_manager` (no local copy in streamlit_app.py)

#### LEVEL 2 — Standard (expanders)
- 📋 **Project Info** (collapsed) — project name, client, contacts, country, state/province, county, grid frequency. Stored via `key=` to `_project_name`, `_client_name`, etc.
- 📊 **Load Profile** (expanded) — pue, capacity_factor, peak_avg_ratio, load_step_pct, avail_req, load_ramp_req, spinning_res_pct (all using `key=field`, seeded by pre-render block; auto-updated via `_dcdefault_*` on DC Type change); + load preview metrics (Total DC / Average / Peak)
- ⚡ **Generator & BESS** (expanded) — use_bess, bess_autonomy_min, bess_dod, enable_black_start, include_chp (gen_filter/model moved to Quick)
- 🌡️ **Site Conditions** (collapsed) — site_temp (unit-aware), site_alt (unit-aware), methane_number, derate_mode; Auto mode shows live derate factor preview
- 💰 **Economics** (collapsed) — gas_price_pipeline, wacc, project_years, benchmark_price, carbon_price_per_ton, enable_depreciation; + nested **"Advanced CAPEX Adders"** sub-expander (bos_pct, civil_pct, fuel_system_pct, epc_pct, contingency_pct, electrical_pct, commissioning_pct). Region removed (moved to Quick).

#### LEVEL 3 — Advanced (collapsed expander)
Flat sub-sections (no nested expanders): Voltage & Electrical, Fuel & LNG, Generator Overrides, BESS Costs, Emissions & Noise, CHP/Tri-Gen, Phasing, Infrastructure, Footprint, GERP PDF Import.
**Load Dynamics sub-section removed** (P47) — those 5 fields moved to Load Profile expander.

### main() Flow (lines 3847–4014)
1. `check_auth()` — auth gate
2. Initialize `st.session_state.result = None` if absent
3. `render_sidebar()` → `inputs_dict, benchmark_price` (ALL inputs collected here)
4. Store 8 cross-tab keys: `_benchmark_price`, `_site_temp`, `_site_alt`, `_mn`, `_fuel_mode`, `_dist_loss_pct`, `_include_chp`, `_enable_phasing`
5. `SizingInput(**inputs_dict)` → `run_full_sizing()` → `st.session_state.result` (on error: show traceback, return)
6. Apply IEEE 493 electrical path factor: `r.system_availability *= get_electrical_path_factor(bus_tie_mode)` (or `_elec_path_avail` if Reliability tab has overridden it)
7. `render_executive_summary(r, benchmark_price)` — headline KPIs above tabs
8. Build `tab_labels` list with conditionals (see Tab Order below)
9. `st.tabs(tab_labels)` + dispatch each tab via `tab_idx` counter

### Tab Order (current — post P45)
| # | Tab | Condition |
|---|---|---|
| 1 | 📋 Summary | always |
| 2 | 📈 Reliability | always |
| 3 | 🔋 BESS | always |
| 4 | ⚡ Electrical | always |
| 5 | 📊 Load Profile | always |
| 6 | 🌿 Environmental | always |
| 7 | 💰 Financial | always |
| 8 | ⛽ Gas Consumption | if `fuel_consumption_curve` key in gen_data |
| 9 | 🔥 CHP / Tri-Gen | if `include_chp` |
| 10 | 🗺️ Footprint | always |
| 11 | 📅 Phasing | if `enable_phasing` |
| 12 | 📜 Emissions Compliance | always |
| 13 | 🔊 Noise | always |
| 14 | ⛽ LNG Logistics | if `fuel_mode in ("LNG","Dual-Fuel")` |
| 15 | 📄 Proposal | always (last) |

### Proposal Generation (Tab 📄 Proposal)
After sizing completes, users can generate a professional DOCX proposal:
- **Tab location:** Last tab in results dashboard ("📄 Proposal") — single tab, no legacy "Proposal Doc" tab
- **Exhibit checkboxes:** 3 mandatory (A=Definitions, B=ESC, C=CVA) + 6 optional (Datasheets, Warranty, Conceptual Layout, Scope of Supply, Sizing Report PDF, Additional Docs); auto-lettered D/E/F...
- **Form fields:** BDM info, dealer, incoterm, delivery, payment terms, offer types, notes — all inside the Proposal tab (no sidebar expander; `ENABLE_PROPOSAL_GEN` flag removed by P45)
- **Defaults:** `core/proposal_defaults.py` (PROPOSAL_DEFAULTS dict)
- **Generator:** `core/proposal_generator.py` → `generate_proposal_docx(sizing_result, gen_data, project_info, selected_exhibits, sizing_pdf_bytes, output_path)`
- **Output:** Branded .docx with Caterpillar logo, cover page, sections 1–6 + dynamic exhibits
- **Logo:** `assets/logo_caterpillar.png` (official Caterpillar wordmark)

### Session State Keys (post-P35/P45)
- `result` — the current `SizingResult` object
- `_benchmark_price`, `_site_temp`, `_site_alt`, `_mn`, `_fuel_mode`, `_dist_loss_pct`, `_include_chp`, `_enable_phasing` — cross-tab values written by `main()` after each sizing run
- `_project_name`, `_client_name`, `_contact_name`, `_contact_email`, `_contact_phone`, `_country`, `_state_province`, `_county_district`, `_freq_hz_proposal` — proposal metadata, written by Project Info expander widgets via `key=`
- `_unit_sys` — unit system ("Metric"/"Imperial"), written by Unit System radio
- `_stored_bess_autonomy_min` — only surviving `_stored_*` key; written by BESS tab override button, read by sidebar BESS autonomy widget
- `_elec_path_avail` — set by Reliability tab topology selector; overrides `get_electrical_path_factor()` default in `main()`
- `_swg_topology` — HV switchgear topology selection (Electrical tab)
- `spinning_res_pct` removed from UI (P04) — SR now derived from physical contingencies

### INPUT_DEFAULTS Stale Keys (known — harmless)
`max_maintenance_units` and `selected_fleet_config_maint` remain in `INPUT_DEFAULTS` (core/project_manager.py) after P32 removed them from SizingInput/SizingResult. Pipeline ignores them. `bess_strategy` key also remains (P34 hardcoded it to "Hybrid" internally).

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
7. **Fleet optimization — single config meeting avail_req** (Binomial availability) → 8. Voltage recommendation →
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

**HV SWG Bus Sizing (P18):** Dual HV switchgear N-1 contingency model in `streamlit_app.py`:
- Topology selector: Single SWG (radial) | Dual SWG ring/sectionalized | Double bus/double breaker
- Normal operation: each SWG carries `normal_factor` × I_total (50% for dual)
- N-1 contingency: surviving SWG carries 100% — this is the bus rating basis
- Tie-breaker rating: N-1 transfer current + ISC interrupting
- ISC split model: local (55%) + remote (45%) contributions for dual SWG
- Equipment recommendations table: incomers, bus bars, tie-breaker, transformers
- Session state key: `_swg_topology`

### Frequency Screening — Inertia Fields
The `frequency_screening` dict returned by `calculate_frequency_screening()` in `core/engine.py` includes:
- `H_per_unit` — mechanical inertia constant from the generator library (e.g., 1.2 s for G3516H)
- `H_bess` — virtual inertia from BESS (0 if no BESS; up to 4.0 s via heuristic `4.0 × min(1, bess_ratio/0.2)`)
- `H_total` — sum of `H_per_unit + H_bess` (system-level inertia for swing equation screening)
- `H_system` — alias for `H_total` (backward compat from P06)

The Streamlit UI displays all three H components separately with a warning if `H_per_unit > 2.0 s` (atypical for recip gas engines).

### BESS Autonomy-Based Energy Sizing (P13)
**Formula:** `bess_energy_mwh = bess_power_mw × (autonomy_min / 60) / bess_dod`

Replaces the hardcoded 2.0h/2.5h coverage in `sizing_pipeline.py`. User-configurable via sidebar.

| Strategy | Default autonomy | Energy (ref 43.86 MW) | CAPEX |
|---|---|---|---|
| Transient Only | 1 min | 0.86 MWh | $11.3M |
| Hybrid (Balanced) | 10 min | 8.60 MWh | $14.4M |
| Reliability Priority | 30 min | 25.80 MWh | $21.3M |

**Parameters:** `bess_autonomy_min` (default 10.0), `bess_dod` (default 0.85).

### Availability & Electrical Path (P14)
- **fix:** `a_gen` in pod fleet optimizer now reads `unit_availability` (0.93) instead
  of MTBF/MTTR ratio (0.9947). `mttr_hours` retained for BESS bridge calc (~line 438).
- **feat:** Electrical path availability now **calculated** from IEEE 493-2007 Table 3-4
  component data (not hardcoded). Topology selector in Reliability tab drives the calculation.
  Topologies and IEEE 493 calculated A_path values:
    Radial single bus:             0.999871  (1.13 hr/yr downtime)
    Ring bus / sectionalized N-1:  0.999999991  (0.00 min/yr — bus is NOT the bottleneck)
    Double bus / double breaker:   0.999999992  (0.00 min/yr)
    2N fully redundant:            0.999999996  (0.00 min/yr)
  Components: MV breakers (lam=0.0027, MTTR=83.1h), bus duct, MV cable.
  Transformers EXCLUDED: their failure is counted in fleet binomial model.
  Component data expander shows IEEE 493 Table 3-4 source data with footnote.
  Default topology: Ring bus / sectionalized N-1 (CAT standard for DCs).
  Combined ~ Fleet Only for ring bus (bus is NOT the reliability bottleneck).
- **feat:** Pod Architecture Banner at top of Electrical tab.
  Shows n_pods × n_per, n_total, installed cap, normal loading, n_trafos.
  Config A/B/C label shown if maintenance config is active.

### Sidebar Widget Pattern (post-P35)
All sidebar widgets use `value=INPUT_DEFAULTS[...]` directly — no `_stored_*` or `_wiz_*` indirection.
- Streamlit's own widget state persistence handles reruns.
- `inputs_dict` is built from local widget variables at end of `render_sidebar()`.
- Exception: `_stored_bess_autonomy_min` — only surviving `_stored_*` key, used by BESS tab autonomy override button to persist across reruns.

### Bug Fix: Generator model selector persistencia (commit c916f8a)
- `render_wizard_step_3()`: `gen_idx` ahora lee desde `st.session_state.get("_wiz_generator_model")`
  en lugar de `INPUT_DEFAULTS["selected_gen_name"]`
- Fallback seguro: si el modelo guardado no existe en la lista filtrada actual,
  cae al default (cubre el caso de cambio de tipo de generador)
- Mismo patrón que el fix del DC Type selector (commit 4dea7c2)

### P25 — Systemic wizard widget persistence fix (commit f04dbbc, 2026-03-28)
- **Root cause:** All wizard widgets (Steps 2-4) used `value=INPUT_DEFAULTS[...]` / `index=0`
  with `key=`, causing Streamlit to overwrite user values on every rerun.
- **Fix pattern:** `value=st.session_state.get("_wiz_KEY", INPUT_DEFAULTS["KEY"])`
  applied to ~17 widgets; index for all selectbox/radio widgets computed from session state.
- **Step 2 fixed:** Unit System radio, Template selectbox, DC Type selectbox.
- **Step 3 fixed:** Derate Mode radio, Include BESS/Black Start/CHP checkboxes,
  BESS Strategy selectbox, Cooling radio, Fuel Mode radio, Voltage Mode radio.
- **Step 4 fixed:** Region selectbox, MACRS checkbox, Site Area checkbox.
- **`_init_wizard_state()` corrections:** `_wiz_gen_filter` `"All"` → list;
  `_wiz_derate_factor_manual` key typo fixed; `_wiz_cooling` key `cooling` → `cooling_method`;
  `_wiz_volt_mode` fallback `"Auto"` → `"Auto-Recommend"` (matches radio options).
- **Resolves:** generator always G3516H, template not applying, BESS strategy not
  persisting, cooling/fuel/voltage resetting, region resetting on rerun.

### Callbacks must write ONLY to `_stored_` keys (commit 3f25f1f, 2026-03-30)
- **Root cause:** `_on_template_change()` and `_apply_dc_type_defaults()` were writing
  to `_wiz_X` keys from inside callbacks. Streamlit raises
  "widget with key _wiz_X was created with a default value but also had its value set
  via the Session State API" warning whenever a rendered widget's key is written from outside.
- **Rule:** `_wiz_X` keys are the **exclusive property of their widgets**. No callback or
  external code may write to them. Callbacks write ONLY to `_stored_X` keys.
- **Fixed callbacks:**
  - `_DC_DEFAULT_KEYS` targets changed from `_wiz_*` → `_stored_*`
  - `_apply_dc_type_defaults()`: writes to `_stored_*` + also writes `_stored_dc_type`
  - `_on_template_change()`: simplified to write only `_stored_*` keys (removed `_wiz_` writes)
  - `_on_dc_type_change()` inline wrapper removed — `_apply_dc_type_defaults` used directly
- `_build_inputs_from_wizard()` already reads `_stored_` first → values flow correctly

### P24a — Electrical path factor topology lookup (commit 0cfce70, 2026-03-29)
- **Replaced** hardcoded `electrical_path_factor = 0.9950` (43.8 hrs/yr downtime)
  with `get_electrical_path_factor(bus_tie_mode)` lookup in `core/engine.py`:
  - `"closed"`: 0.999999 (ring bus, ties cerrados, IEEE 493-2007)
  - `"open"`: 0.9999 (sections independientes)
- **New input:** `bus_tie_mode` added to `SizingInput`, `INPUT_DEFAULTS`, `HELP_TEXTS`,
  sidebar Technology expander, and wizard Step 3 (with `on_change` callback).
- **`electrical_path_factor`** added to `SizingResult` (default 0.999999).
- **Pipeline:** `sizing_pipeline.py` imports and calls `get_electrical_path_factor()`,
  stores result in `SizingResult.electrical_path_factor`.
- **`main()`:** fallback for `_elec_path_avail` now uses `get_electrical_path_factor(bus_tie_mode)`
  instead of hardcoded 0.9950. Reliability tab topology selector still overrides it.
- **Engineering basis:** IEEE 493-2007 Table 3-4 failure rates for MV switchgear,
  power transformers, protective relays. Topology: SWGR-A + SWGR-B + 52T5 bus-tie.
  Step-up transformers captured in binomial fleet model, NOT in this factor.
- **Tests:** 48/48 pass.

### P48 — Fix DC Type auto-fill: all 7 Load Profile fields force-updated on DC Type change (2026-04-04)
- **Bug:** Switching DC Type did not update Load Profile fields (e.g. spinning_res_pct showed 20% for Colocation, expected 10%). All 7 fields affected.
- **Root cause:** Two distinct Streamlit pitfalls triggered by the P47 `_dcdefault_*` pattern:
  1. Widgets WITHOUT `key=` (pue, capacity_factor, peak_avg_ratio, load_step_pct, avail_req, load_ramp_req) — Streamlit ignores `value=` on reruns after the widget's internal state is set
  2. `spinning_res_pct` WITH `key="spinning_res_pct"` AND `value=st.session_state.get(...)` — Streamlit uses the stored `st.session_state["spinning_res_pct"]` and ignores the `value=` expression entirely
- **Fix — complete two-step pattern for all 7 fields:**
  1. `_on_dc_type_change()` callback: unchanged — writes `st.session_state["_dcdefault_<field>"]` for all 7 fields
  2. **Pre-render transfer block** (lines 421–442, before Load Profile expander on every render):
     ```python
     _LP_FIELD_DEFAULTS = {  # all 7 fields with INPUT_DEFAULTS as fallback
         "pue", "capacity_factor", "peak_avg_ratio", "load_step_pct",
         "avail_req", "load_ramp_req", "spinning_res_pct"
     }
     for field, default in _LP_FIELD_DEFAULTS.items():
         dckey = f"_dcdefault_{field}"
         if dckey in st.session_state:
             st.session_state[field] = st.session_state.pop(dckey)  # force DC default
         elif field not in st.session_state:
             st.session_state[field] = default  # seed on first run
     ```
  3. All 7 Load Profile widgets use `key=field` only — NO `value=` parameter
- **Verified (simulation):** All 3 DC type switches (Colocation, HPC/Research, Edge Computing) produce exact matches. DC type switch also correctly overrides any prior manual user edit.
- **No code changes in P48-fix2** — the complete fix was already in P48. Confirmation commit only.
- py_compile OK

### P47 — Sidebar progressive disclosure: Quick / Standard / Advanced (2026-04-04)
- **LEVEL 1 (Quick Sizing, always visible):** Data Center Type, IT Load, Generator Types + Model, Region — the 4 most-used fields exposed without opening any expander
- **DC_TYPE_DEFAULTS auto-fill:** `_on_dc_type_change()` callback writes `_dcdefault_<key>` session state entries when DC Type changes; Load Profile widgets read them as initial values → PUE, CF, PAR, load step, availability, SR%, ramp rate auto-fill on DC type selection
- **Load Profile expander** gains 5 load-dynamics fields (peak_avg_ratio, load_step_pct, avail_req, load_ramp_req, spinning_res_pct) moved from Advanced; loses dc_type + p_it (moved to Quick)
- **Generator & BESS expander** loses gen_filter + generator_model + specs (moved to Quick)
- **Economics expander** loses region (moved to Quick)
- **Advanced expander** loses entire Load Dynamics sub-section (moved to Load Profile)
- **Change 1:** `DC_TYPE_DEFAULTS` removed from streamlit_app.py local scope (−69 lines); now imported from `core.project_manager`
- Net: `streamlit_app.py` 3,962 lines (was 4,014 before P47 + DC_TYPE_DEFAULTS removal)
- All inputs_dict keys preserved. py_compile OK.

### P46 — Add DC_TYPE_DEFAULTS to core/project_manager.py (2026-04-04)
- Added `DC_TYPE_DEFAULTS` dict to `core/project_manager.py` immediately after `INPUT_DEFAULTS`
- 7 DC types × 7 fields: `pue`, `capacity_factor`, `peak_avg_ratio`, `load_step_pct`, `avail_req`, `spinning_res_pct`, `load_ramp_req`
- Keys match `DC_TYPES` list in `streamlit_app.py` exactly (verified — zero missing, zero extra)
- Canonical home for progressive disclosure auto-fill logic; `streamlit_app.py` will import from here in P47
- Updated module docstring to reflect 105 keys + `DC_TYPE_DEFAULTS`
- Existing `DC_TYPE_DEFAULTS` in `streamlit_app.py` (lines 71–135) will be replaced by the import in P47
- Tests: 41/43 proposal tests pass (2 pre-existing P26 failures unrelated)

### P45 — Remove legacy Proposal Doc tab (2026-04-04)
- Removed `ENABLE_PROPOSAL_GEN` env flag, `render_docx_proposal_tab()`, `_build_proposal_info_from_session()`, sidebar "📄 Proposal Information" expander (15 widgets), `:memo: Proposal Doc` tab label and routing block
- **−228 lines** from `streamlit_app.py`
- Single **📄 Proposal** tab (P41A/B exhibit checkboxes + `generate_proposal_docx()`) is now the only proposal UI
- Legacy `_generate_proposal_docx_legacy()` remains in `core/proposal_generator.py` for backward compat

### P43 — Fix output_path parameter in generate_proposal_docx (2026-04-04)
- Added `output_path: str = None` to `generate_proposal_docx()` signature (line 1130)
- Root cause: function body referenced `output_path` at serialize step but parameter was missing from signature — `NameError` on any call that reached the `if output_path:` block
- Legacy `_generate_proposal_docx_legacy()` already had the parameter; new function was missing it

### P42 — Fix generate_proposal_docx signature (2026-04-03)
- Added `gen_data` as explicit keyword parameter (was consumed via `**kwargs` causing silent failures)
- Ensures `generate_proposal_docx(sizing_result, gen_data=gen_data, ...)` call from `render_proposal_tab()` passes generator specs correctly

### P41B — Word proposal generator implemented (2026-04-03)
- New `generate_proposal_docx(sizing_result, gen_data, project_info, selected_exhibits, sizing_pdf_bytes=None)` in `core/proposal_generator.py`
- Generates .docx with cover page, TOC, sections 1–6 (filled from sizing results + project info), and dynamic appendices
- Mandatory exhibits always included: A=Definitions, B=ESC (Extended Service Coverage), C=CVA (Service Agreement)
- Optional exhibits from checkboxes with auto-lettering D/E/F...: Datasheets, Warranty Statement, Conceptual Layout, Scope of Supply Matrix, Sizing Report (with summary table of key results), Additional Technical Documents
- Backward-compat routing: positional legacy call `(sizing_result, header_info, proposal_info)` detected by "project_name" key presence and routes to `_generate_proposal_docx_legacy`
- `render_proposal_tab()` col_docx block replaced with actual `st.download_button` for .docx
- Project info from session state: `_project_name`, `_client_name`, `_country`, `_state_province`, etc.
- Sizing Report exhibit: pulls n_total, n_running, n_reserve, installed_cap, bess, availability, CAPEX, LCOE, pod architecture from sizing_result dict
- `requirements.txt` already had `python-docx>=1.1` — no new deps

### P41A — Proposal tab with exhibit selection checkboxes (2026-04-03)
- PDF Report tab renamed to **Proposal** tab (`render_pdf_tab` → `render_proposal_tab`)
- Old DOCX proposal function renamed to `render_docx_proposal_tab` behind `ENABLE_PROPOSAL_GEN` flag (**later removed by P45**)
- New `render_proposal_tab()` shows: mandatory appendices (A=Definitions, B=ESC, C=CVA), 6 optional exhibit checkboxes (Datasheets, Warranty, Conceptual Layout, Scope of Supply, Sizing Report PDF, Additional Docs), dynamic appendix lettering D/E/F..., live appendices preview, PDF download (identical to old render_pdf_tab), Word download via P41B
- `_proposal_exhibits` and `_proposal_mandatory` stored in session state for P41B

### P40 — SR shortfall advisory below Design Validation Scorecard (2026-04-03)
- Added SR shortfall advisory block in `render_summary_tab()` BELOW the design scorecard
- When spinning reserve is insufficient (`sr_deficit > 0`): shows `st.warning` with deficit MW, available vs required breakdown, and 3 actionable options (enable/increase BESS, add N generators, increase BESS autonomy)
- When SR passes with thin margin (<20%): shows `st.info` with margin percentage
- Added SR pass/fail summary in `render_electrical_tab()` after the SR detail table: `st.error` on deficit, `st.success` with margin MW when satisfied
- No changes to scorecard tile rendering, `core/`, or `api/`

### P39 — Hotfix: confirm spinning_res_pct widget→inputs_dict connection (2026-04-03)
- Verified `spinning_res_pct` widget in Advanced > Load Dynamics correctly writes to `inputs_dict` after P38 restore
- Added stable `key="spinning_res_pct"` session state key to prevent value loss on rerun
- No logic changes — confirmation + defensive key stabilization only

### P38 — Hotfix: restore spinning_res_pct input in Advanced (2026-04-03)
- `spinning_res_pct` slider was lost during P37 sidebar reorganization (not included in new Advanced expander)
- Restored to **Advanced → Load Dynamics** flat section
- Field was still used in `inputs_dict` and pipeline; only the UI widget was missing

### P37 — Reorganize sidebar Basic + Advanced (2026-04-03)
- Restructured `render_sidebar()` from 13 flat expanders → 6 expanders: Project Info, Load Profile, Generator & BESS, Site Conditions, Economics, Advanced
- **Load Profile** slimmed to 4 fields: DC Type, IT Load, PUE, Capacity Factor
- **Generator & BESS** new combined expander: gen filter/model/specs, BESS, Black Start, CHP checkbox
- **Advanced** single collapsed expander with flat sub-sections (no nested expanders): Load Dynamics, Voltage & Electrical, Fuel & LNG, Generator Overrides, BESS Costs, Emissions & Noise, CHP/Tri-Gen, Phasing, Infrastructure, Footprint, GERP PDF Import
- All `inputs_dict` keys and variable names unchanged — no logic changes

### P35 — Eliminate wizard, sidebar-only architecture (2026-04-02)
- Deleted all wizard code: `WIZARD_STEPS`, `_init_wizard_state`, `render_wizard_stepper`, `render_wizard_step_1` through `render_wizard_step_5`, `render_wizard_navigation`, `render_wizard`, `_build_inputs_from_wizard`, `_make_wizard_persist_callback`, `_sidebar_default`, `_on_generator_change`, `_apply_dc_type_defaults`, `_on_template_change`, `_DC_DEFAULT_KEYS`
- **−926 lines** (4985 → 4059)
- Rewrote `main()` — always runs `render_sidebar()` → `run_full_sizing()` reactively; no wizard gates, no "Back to Wizard" button
- Added `📋 Project Info` sidebar expander (project/client/contact/country/freq fields for proposal generator)
- All sidebar widgets use `value=INPUT_DEFAULTS[...]` directly — no `_stored_*` or `_wiz_*` keys
- `initial_sidebar_state` changed from `"collapsed"` → `"expanded"`
- Only surviving `_stored_*` key: `_stored_bess_autonomy_min` (BESS tab override button — intentional)

### P34 — Remove BESS Strategy selectbox (2026-04-02)
- Removed `BESS_STRATEGIES` constant and BESS Strategy selectbox from wizard Step 3 and sidebar
- Pipeline always uses `"Hybrid (Balanced)"` internally — hardcoded in `_build_inputs_from_wizard()` and `inputs_dict`
- User controls BESS sizing via autonomy slider only (minutes)
- BESS tab now shows autonomy instead of strategy name
- BESS checklist "Peak Shaving" now driven by `r.use_bess` instead of strategy name check
- Cleaned up strategy-dependent autonomy warning messages in BESS tab

### P32 — Simplify reliability to single config (2026-04-02)
- Eliminated 3-config (A/B/C) maintenance architecture selector and all associated plumbing
- **Removed from `sizing_pipeline.py`:** `calculate_fleet_maintenance_configs` call + P30 override block + 5 maintenance fields from SizingResult assembly + import of `calculate_fleet_maintenance_configs`
- **Removed from `api/schemas/sizing.py`:** `max_maintenance_units` and `selected_fleet_config_maint` from `SizingInput`; `cap_combined`, `maintenance_margin_mw`, `max_maintenance_units`, `fleet_maintenance_configs`, `selected_fleet_config_maint` Optional fields from `SizingResult`
- **Removed from `streamlit_app.py`:** `max_maintenance_units` sidebar number_input; fleet maintenance fields from `inputs_dict` and `_build_inputs_from_wizard()`; entire Maintenance-Aware Fleet Configurations section with comparison table, radio selector, and "Apply & Re-run Sizing" button; `_config_rerun` handler in `main()`; maintenance config banner from `render_electrical_tab()`; `r.reliability_configs` iteration in BESS checklist
- **Added:** Simple "Fleet Configuration" metrics display in Reliability tab (4 fleet metrics + 3 efficiency/availability metrics + availability target check)
- **Net result:** Pipeline computes one optimal fleet that meets `avail_req` — used for ALL downstream calculations (CAPEX, LCOE, footprint, emissions). No user selection, no radio buttons, no re-run button. −199 lines.

### P31 — Fix config override not reaching pipeline (2026-04-02) [superseded by P32]
- P30's `sizing_pipeline.py` override IS correct — produces A=$312M, B=$342M, C=$327M when called directly
- **Root cause:** Two bugs in `streamlit_app.py`; fixed — then entire 3-config system removed by P32

### P30 — Fix preferred_config propagation to downstream results (2026-04-01) [superseded by P32]
- Fixed `selected_fleet_config_maint` (A/B/C) not changing CAPEX, LCOE, or other results
- Entire multi-config system removed by P32

### P28 — Sidebar initializes from wizard values (2026-03-30)
- All sidebar widgets read `_stored_*` keys as initial values, falling back
  to `INPUT_DEFAULTS` if no wizard values exist
- Added `_sidebar_default()` helper for consistent `_stored_ → INPUT_DEFAULTS` pattern
- Covers ~25 widgets: IT load, PUE, generator model, site conditions, economics, etc.
- Ensures wizard→sidebar transition preserves all user-configured values

### P27b — Variables table + re-run fix (2026-03-30)
- **Removed** tornado sensitivity chart (P27) — replaced with reference table
- **Added** "Sizing Input Variables" table in Reliability tab showing all key
  parameters: generator specs, site conditions, fleet size, availability
- **Fixed** sizing overwrite on re-run via `_config_rerun` flag (removed in P32 along with the entire multi-config system)

### P27 — Availability sensitivity tornado chart (2026-03-30)
- Added tornado chart to Reliability tab showing impact of 3 key variables
  on system availability: unit availability (±0.05), reserve units (N±1), electrical path factor
- Uses binomial model for instant calculation (no pipeline re-execution)
- Variables reuse already-computed `a_gen_active`, `epf`, `n_total` from tab scope
- Includes summary table and methodology caption; variables sorted by impact magnitude

### P26b — Project Info persistence + proposal text residue (2026-03-30)
- Step 1 widgets now have `on_change` + `_stored_` callbacks (same P25L pattern)
  — covers project_name, client_name, contact_name/email/phone, country, state_province, county_district, freq_hz
- `header_info` dict in Proposal tab reads `_stored_` first → `_wiz_` → default (Fix 1B)
- Metrics preview in Proposal tab reads `_stored_` first (Fix 1B)
- `render_wizard_step_5()` reads `_stored_project_name` and `_stored_freq_hz` first (Fix 1C)
- Fixed residual `"supporting systems"` → `"supporting solutions"` in `exec_summary_4` (proposal_generator.py)

### P26 — Proposal generator content update (2026-03-30)
- Updated `core/proposal_generator.py` with director-approved template changes (commit 5a253fd)
- 24 content/terminology changes: section renames, definition updates, checkbox restructure
- Key changes: 'Solution Overview' → 'Proposed Customer Solution', 'Appendix' → 'Exhibit' (A–H),
  'package' → 'solution', 'applications' → 'Applications', dealer disclaimer strengthened,
  `{client_name}` placeholder in exec summary, Technical Offer checkboxes 4-col → 2-col (Genset Only / BOP),
  Exhibit G renamed to 'Service Agreement (SA) Overview' with SA intro paragraph,
  Exhibit F: 'Extended Service Coverage Overview', new definitions: BOP, RTS, SOL, SA, updated: Base Price, Delivery, Feature Code, PO/LOA
- No logic changes — all modifications are to hardcoded text strings
- `core/pdf_report.py` NOT modified — separate document format

### P25L — on_change + _stored_ pattern for all wizard widgets (commit 78f7566, 2026-03-29)
- Extended the generator's proven `on_change` + `_stored_` pattern to ALL ~40
  wizard widgets across Steps 2-4.
- **Pattern:** Each widget has `on_change=_make_wizard_persist_callback("_wiz_X", "_stored_X")`.
  The callback copies the widget value to a `_stored_X` key that is not tied to any
  widget and therefore survives Streamlit's session state cleanup on step transitions.
- **Read order:** `_stored_X` → `_wiz_X` → `INPUT_DEFAULTS["X"]` in all readers
  (`_build_inputs_from_wizard` via `_v()` helper, `render_wizard_step_5`, `_render_load_preview`).
- **Template callback** also writes to `_stored_` keys.
- **`_on_template_change()`** updated to write both `_wiz_` and `_stored_` for each key.
- **DEFINITIVE wizard persistence pattern** for Streamlit multi-step forms.

### P25k — Skip reactive sizing after wizard (commit 8cf5efc, 2026-03-29)
- **Problem:** P25j's `st.rerun()` didn't prevent sidebar from overwriting wizard
  results — the reactive sizing still ran on the next cycle.
- **Fix:** `_wizard_just_completed` flag set after wizard sizing, consumed by
  `st.session_state.pop()` in the reactive sizing guard. First render after wizard
  skips reactive sizing; subsequent sidebar changes trigger it normally.
- Removed P25j's `st.rerun()`.

### P25j — Prevent sidebar from overwriting wizard results (commit b9518ef, 2026-03-29)
- **Root cause (DEFINITIVE):** After wizard sizing completes with the correct
  generator, `main()` falls through to `render_sidebar()` which re-runs
  `run_full_sizing()` with sidebar defaults (G3516H), overwriting the result.
- **Fix:** Added `st.rerun()` after wizard sizing so the sidebar renders on a
  clean cycle where `_wizard_running=False` and the stored result is preserved.
- **Generator on_change pattern confirmed working:** `_stored_generator_model`
  correctly holds the user's selection across step transitions.

### P25h — Rollback to stable + generator on_change fix (commit c49c6e6, 2026-03-29)
- **Rolled back** P25-P25g experiments that broke defaults (min_value shown instead of correct defaults)
- **Widgets restored** to original stable pattern: `value=INPUT_DEFAULTS[...]` with `key=`
- **Generator fix:** `on_change=_on_generator_change` callback persists selection to
  `_stored_generator_model` (non-widget key, survives step transitions)
- **`_build_inputs_from_wizard()`** reads `_stored_generator_model` first, falls back
  to `_wiz_generator_model` then `INPUT_DEFAULTS`
- **`render_wizard_step_5()`** also reads `_stored_generator_model` first for Review display
- **If generator test passes**, same `on_change` + `_stored_` pattern will be applied
  to all other critical widgets (temp, alt, BESS strategy, etc.)
- **Removed** `_preserve/_restore_wizard_state()` (caused button key write errors)
- **Simplified** `_init_wizard_state()` to Step 1 keys only — Steps 2-4 widgets
  create their own session state via `value=`/`index=` defaults

### P25g — Remove value=/index= from keyed widgets + rollback P25f (commit 1102bb5, 2026-03-29)
- **P25f rollback:** Rendering all steps simultaneously caused widget key conflicts
  and showed all steps visually. Reverted to single-step render.
- **Root fix:** Removed `value=` from all `number_input`/`slider`/`checkbox` and
  `index=` from all `selectbox`/`radio` that have `key=`. When both `value=` and
  `key=` are present, Streamlit warns and the `value=` can override the restored
  session state value.
- **Pattern (DEFINITIVE):** For wizard widgets, use ONLY `key=` (no `value=`/`index=`).
  `_init_wizard_state()` sets initial defaults. `_preserve/_restore_wizard_state()`
  survives step transitions.

### P25f — Render all wizard steps simultaneously (commit c74bfc4, 2026-03-29)
- **Why P25e failed:** Streamlit deletes widget keys during the rerun itself,
  before `_preserve_wizard_state()` can execute on the next cycle.
- **Solution:** `render_wizard()` now renders ALL 5 steps on every rerun.
  Inactive steps are wrapped in `display:none` CSS containers. This keeps
  all widget keys alive in the DOM at all times.
- **Critical pattern:** Never conditionally render wizard steps with
  `step_renderers[step]()` — always render all of them.
- P25e preserve/restore kept as belt-and-suspenders backup.

### P25e — Wizard state preservation across steps (commit 6555514, 2026-03-29)
- **Root cause (DEFINITIVE):** Streamlit deletes session state keys for widgets
  not currently rendered. Wizard renders one step at a time, so navigating away
  from a step deletes all its widget keys. `_init_wizard_state()` then
  re-initializes them to defaults (e.g. `_wiz_generator_model` → G3516H).
- **Solution:** `_preserve_wizard_state()` / `_restore_wizard_state()` pair that
  copies all `_wiz_*` keys to a `_wizard_persist` dict (not tied to any widget)
  before step transitions and restores them on render.
- **Critical pattern for future wizard widgets:** Any new `_wiz_*` key is
  automatically preserved — no additional code needed per widget.
- Also removed P25d debug prints.

### P25b — Remaining widget fixes (commit a86f263, 2026-03-29)
- Added explicit `value=st.session_state.get(...)` to 4 widgets missing it: PUE, Methane Number, LNG days, Carbon Price
- Generator model selectbox: verified correct (reads session state for index — commit c916f8a)
- Full audit: 45 wizard widgets confirmed using correct session state pattern across Steps 2-4
- 6 BOS adder `number_input` widgets use positional `value` arg with session_state — confirmed correct

### Bug Fix: gen_filter multiselect key/value conflict (commit 5287d12)
- `render_wizard_step_3()`: eliminado `default=INPUT_DEFAULTS["gen_filter"]`
  del multiselect de Generator Types
- Causa raíz del bug de persistencia del generador: gen_filter revertía a
  `["High Speed"]` en cada rerun por conflicto key/value, forzando fallback
  a G3516H en `_wiz_generator_model`
- Patrón idéntico al key/value conflict de number_input documentado en CLAUDE.md
- `_wiz_gen_filter` ya inicializado en `_init_wizard_state()` — `default=` era
  redundante y destructivo

### PDF Report Key Mapping (P17/C1)
`core/pdf_report.py` uses `g(key, default)` helper. Corrected field mappings:
- `bess_power_mw` / `bess_energy_mwh` (was `bess_power_total` / `bess_energy_total`)
- `total_capex` (was `initial_capex_sum`)
- `simple_payback_years` (was `payback_str`)
- `annual_fuel_cost` / `annual_om_cost` (was `fuel_cost_year` / `om_cost_year`)
- `system_availability` (was `prob_gen`)
- `spinning_reserve_mw` in MW (was `spinning_res_pct` in %)
- Pod architecture (`n_pods × n_per_pod`), loading, Uptime tier, derate_table_source added.
- `render_pdf_tab()` in `streamlit_app.py` enriches `pdf_data` with flattened emissions,
  `capex_items` list, `selected_config`, and `gen_data` before calling `generate_comprehensive_pdf()`.

### CAPEX Total Calculation (H2)
`total_capex_m` in `sizing_pipeline.py` now includes:
- `emissions_control.get('total_capex', 0)` — SCR/oxidation catalyst CAPEX
- `lng_logistics.get('lng_capex_usd', 0)` — LNG tank + vaporizer + piping
These were in `capex_breakdown` but excluded from the sum. Fixed at line ~631.

### HV Switchgear — 52T5 Bus-Tie Modes (P18/P19/P22)
In `streamlit_app.py` Electrical tab:
- **52T5 mode selector:** Normally Open (NO) vs Normally Closed (NC)
- **NO mode (default):** ISC = local section only. 52T5 closes on N-1 contingency.
- **NC mode:** ISC = both sections contribute (ring bus paralleling). Higher ISC.
- **Breaker ratings:** ANSI C37 list extended to [16, 20, 25, 31.5, 40, 50, 63, 80, 100, 125] kA.
- **Warnings:** "Special Order" for 80-125 kA; "Exceeds Maximum" if ISC > 125 kA.
- Equipment recommendations table with bus bars, incomers, tie-breaker, current-limiting reactor.

### BESS Autonomy Calculated (P21)
In BESS tab, autonomy slider with override capability:
- Default autonomy derived from `bess_energy_mwh / bess_power_mw × 60`.
- User can override; warning shown if override differs >50% from calculated.
- Formula caption: `Energy = Power × autonomy_min / 60 / DoD`.

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
- `derate_type` — ADF table selector: `high_speed_recip` (validated GERP), `medium_speed_recip` (typical estimate), `gas_turbine` (placeholder)

**Derate type mapping:**
| derate_type | Models | Status |
|---|---|---|
| `high_speed_recip` | G3516H, G3520FR, G3520K, XGC1900, CG260-16 | Validated (GERP EM7206-05-001) |
| `medium_speed_recip` | C175-20, G20CM34 | Typical estimate — OEM data pending |
| `gas_turbine` | Titan 130/250/350 | Placeholder — uses high_speed table |

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
- **Add a sidebar input field:** Add widget in the appropriate `render_sidebar()` expander, add key to `inputs_dict` at bottom of that function
- **Change proposal defaults:** Edit `core/proposal_defaults.py` PROPOSAL_DEFAULTS dict
- **Modify proposal document:** Edit `core/proposal_generator.py` section builders (`_build_section_*`)
- **Change CAPEX BOS defaults:** Edit `core/project_manager.py` INPUT_DEFAULTS (bos_pct, civil_pct, etc.)
- **Run full sizing test:** `pytest tests/test_api.py::TestSizingIntegration -v`
- **Run proposal tests:** `pytest tests/test_proposal.py -v` (43 tests)

## Local Working Directory
- **Primary (outside OneDrive):** `C:\Users\juans\CAT Power Solution`
- **GitHub repo:** `juansaraiva-arch/CAT-Power-Solution`
- **Do NOT use the OneDrive copy** — causes sync/mmap issues with git
