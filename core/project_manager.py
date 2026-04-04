"""
CAT Size Solution — Project Manager
=====================================
Single source of truth for:
  - All input defaults (104 keys)
  - DC_TYPE_DEFAULTS — per-type intelligent defaults for progressive disclosure
  - Project header (name, client, contact, location)
  - Save / Load to JSON
  - Template presets
"""

import json
from datetime import datetime
from copy import deepcopy

APP_VERSION = "4.0"

# ==============================================================================
# HEADER DEFAULTS
# ==============================================================================
HEADER_DEFAULTS = {
    "project_name": "",
    "client_name": "",
    "contact_name": "",
    "contact_email": "",
    "contact_phone": "",
    "country": "",
    "state_province": "",
    "county_district": "",
}

# ==============================================================================
# INPUT DEFAULTS — SINGLE SOURCE OF TRUTH FOR ALL 76 SIDEBAR INPUTS
# ==============================================================================
INPUT_DEFAULTS = {
    # ── Global Settings ──
    "unit_system": "Metric (SI)",
    "freq_hz": 60,

    # ── Section 1: Load Profile ──
    "template_choice": "Custom (Manual)",
    "dc_type": "AI Factory (Training)",
    "p_it": 100.0,
    "avail_req": 99.99,
    "pue": 1.20,
    "load_step_pct": 40.0,
    "spinning_res_pct": 20.0,
    "capacity_factor": 0.90,
    "peak_avg_ratio": 1.15,
    "load_ramp_req": 3.0,

    # ── Section 2: Site Conditions ──
    "derate_mode": "Auto-Calculate",
    "site_temp_c": 35,
    "site_temp_f": 95,
    "site_alt_m": 100,
    "site_alt_ft": 300,
    "methane_number": 80,
    "derate_factor_manual": 0.9,
    "enable_footprint_limit": False,
    "max_area_m2": 10000,
    "bus_tie_mode": "closed",
    "max_area_ft2": 10000,

    # ── Section 3: Technology ──
    "gen_filter": ["High Speed", "Medium Speed"],
    "use_bess": True,
    "bess_strategy": "Hybrid (Balanced)",
    "enable_black_start": True,
    "include_chp": False,
    "cooling_method": "Air-Cooled",
    "fuel_mode": "Pipeline Gas",
    "lng_days": 5,
    "volt_mode": "Auto-Recommend",
    "manual_voltage_kv": 13.8,
    "dist_loss_pct": 1.5,

    # ── Emissions Control ──
    "force_emissions": False,
    "cost_scr_kw": 75.0,
    "cost_oxicat_kw": 25.0,

    # ── Generator Selection ──
    "selected_gen_name": "G3516H",
    # GERP PDF import fields (only used when gen is imported)
    "custom_model": "G3520K (Generic)",
    "custom_iso_kw": 2500.0,
    "custom_eff_pct": 44.4,
    "custom_heat_jw": 550.0,
    "custom_heat_exhaust": 1054.0,
    "custom_nox": 0.5,

    # ── Generator Parameter Overrides ──
    # None = use library default
    "gen_iso_mw_override": None,
    "gen_voltage_kv": 13.8,
    "gen_aux_pct": 2.0,
    "gen_eff_override": None,
    "gen_step_load_override": None,
    "gen_ramp_rate_override": None,
    "gen_cost_kw_override": None,
    "gen_install_kw_override": None,
    "lead_time_weeks": 24,

    # ── Generation Cost Method ──
    "gen_cost_mode": "budget_estimate",       # "budget_estimate" or "bdm_total_price"
    "gen_total_price_bdm": 0.0,               # Total price in USD if BDM mode

    # ── Section 4: Economics ──
    "gas_price_pipeline": 3.5,
    "gas_price_lng": 9.5,
    "benchmark_price": 0.12,

    # BESS Economics
    "bess_cost_kw": 250.0,
    "bess_cost_kwh": 400.0,
    "bess_om_kw_yr": 5.0,
    "bess_life_batt": 10,
    "bess_life_inv": 15,

    # Infrastructure costs
    "pipeline_cost_usd": 500_000,       # $ — typical short run ~$500k
    "permitting_cost_usd": 250_000,     # $ — typical data center ~$200-500k
    "commissioning_cost_usd": 0,        # $ — keep 0; calculated from commissioning_pct

    # Protection Limits (P08)
    "voltage_sag_limit_pct": 15.0,      # % — max acceptable voltage sag at gen bus
    "freq_nadir_limit_hz": 59.5,        # Hz — min acceptable frequency (60 Hz system)
    "freq_rocof_limit_hz_s": 2.0,       # Hz/s — max rate of change of frequency

    # CAPEX BOS Adders (% of gen + install base)
    "bos_pct": 0.17,
    "civil_pct": 0.13,
    "fuel_system_pct": 0.06,
    "epc_pct": 0.12,
    "contingency_pct": 0.10,

    # Fuel Infrastructure
    "fuel_infra_mult": 1.0,
    "lng_tank_cost": 450000,
    "dist_gas_main_m": 1000,

    # Financial Specs
    "wacc": 8.0,
    "project_years": 20,
    "enable_itc": False,
    "enable_ptc": False,
    "enable_depreciation": True,
    "region": "US - Gulf Coast",
    "carbon_price_per_ton": 0,
    "enable_lcoe_target": False,
    "target_lcoe": 0.08,

    # CAPEX BOS adders — as fraction of (generator equipment + installation) subtotal
    "bos_pct":           0.17,   # BOS: MV switchgear, transformers (~17%)
    "civil_pct":         0.13,   # Civil: foundations, grading, drainage (~13%)
    "fuel_system_pct":   0.06,   # Fuel: gas piping, regulators, metering (~6%)
    "electrical_pct":    0.06,   # MV electrical: cables, protection relays (~6%)
    "epc_pct":           0.12,   # EPC management fee (~12%)
    "commissioning_pct": 0.025,  # Commissioning and startup (~2.5%)
    "contingency_pct":   0.10,   # Contingency allowance (~10%)

    # Dual-Fuel / LNG
    "lng_backup_pct": 30.0,

    # CHP / Tri-Generation
    "chp_recovery_eff": 0.50,
    "absorption_cop": 0.70,
    "cooling_load_mw": 0.0,

    # Emissions Control
    "include_scr": False,
    "include_oxicat": False,

    # Noise
    "noise_limit_db": 65.0,
    "distance_to_property_m": 100.0,
    "distance_to_residence_m": 300.0,
    "acoustic_treatment": "Standard",

    # Phasing
    "enable_phasing": False,
    "n_phases": 3,
    "months_between_phases": 6,

    # Pipeline Sizing
    "pipeline_distance_km": 0.0,
    "pipeline_diameter_inch": 6.0,

    # Gas Pipeline Sizing (Weymouth)
    "gas_supply_pressure_psia": 100.0,   # psia — utility supply pressure at site boundary
    "gas_pipeline_length_miles": 1.0,    # miles — distance from utility tap to site
    "gas_pipe_efficiency": 0.92,         # Weymouth pipe efficiency factor
    "gas_sg": 0.65,                      # specific gravity (pipeline nat gas, CH4-dominant)
    "gas_temp_f": 60.0,                  # °F — average gas temperature
    "gas_z_factor": 0.90,               # compressibility factor (<300 psia)

    # Fleet Maintenance (P12)
    "max_maintenance_units":       1,    # gens in simultaneous scheduled maintenance (0=strict, 1=realistic)

    # BESS Autonomy (P13)
    # Formula: bess_energy_mwh = bess_power_mw × (autonomy_min / 60) / bess_dod
    "bess_autonomy_min": 10.0,                   # minutes — default for Hybrid (Balanced)
    "bess_autonomy_min_transient":    1.0,        # minutes — Transient Only
    "bess_autonomy_min_hybrid":      10.0,        # minutes — Hybrid (Balanced)
    "bess_autonomy_min_reliability": 30.0,        # minutes — Reliability Priority
    "bess_dod": 0.85,                             # depth of discharge

    # Aux Load
    "aux_load_pct": 4.0,
}

# ==============================================================================
# DC_TYPE_DEFAULTS — per-type intelligent defaults for progressive disclosure
# Applied automatically when the user selects a DC type in Quick Sizing (P47+).
# Keys match DC_TYPES list exactly. Values are industry-typical for preliminary
# sizing — user can override after auto-fill.
# Sources: Uptime Institute, ASHRAE TC9.9, Lawrence Berkeley National Lab
# ==============================================================================
DC_TYPE_DEFAULTS = {
    "AI Factory (Training)": {
        "pue": 1.20,
        "capacity_factor": 0.95,
        "peak_avg_ratio": 1.10,
        "load_step_pct": 40.0,
        "avail_req": 99.99,
        "spinning_res_pct": 20.0,
        "load_ramp_req": 3.0,
    },
    "AI Inference": {
        "pue": 1.25,
        "capacity_factor": 0.85,
        "peak_avg_ratio": 1.15,
        "load_step_pct": 35.0,
        "avail_req": 99.99,
        "spinning_res_pct": 20.0,
        "load_ramp_req": 2.5,
    },
    "Enterprise Mixed": {
        "pue": 1.40,
        "capacity_factor": 0.70,
        "peak_avg_ratio": 1.25,
        "load_step_pct": 30.0,
        "avail_req": 99.95,
        "spinning_res_pct": 15.0,
        "load_ramp_req": 1.5,
    },
    "HPC / Research": {
        "pue": 1.15,
        "capacity_factor": 0.90,
        "peak_avg_ratio": 1.10,
        "load_step_pct": 40.0,
        "avail_req": 99.99,
        "spinning_res_pct": 20.0,
        "load_ramp_req": 3.0,
    },
    "Hyperscale Standard": {
        "pue": 1.20,
        "capacity_factor": 0.80,
        "peak_avg_ratio": 1.20,
        "load_step_pct": 30.0,
        "avail_req": 99.99,
        "spinning_res_pct": 15.0,
        "load_ramp_req": 2.0,
    },
    "Colocation": {
        "pue": 1.50,
        "capacity_factor": 0.65,
        "peak_avg_ratio": 1.30,
        "load_step_pct": 25.0,
        "avail_req": 99.95,
        "spinning_res_pct": 10.0,
        "load_ramp_req": 1.5,
    },
    "Edge Computing": {
        "pue": 1.30,
        "capacity_factor": 0.75,
        "peak_avg_ratio": 1.20,
        "load_step_pct": 20.0,
        "avail_req": 99.90,
        "spinning_res_pct": 10.0,
        "load_ramp_req": 1.0,
    },
}

# ==============================================================================
# TEMPLATES
# ==============================================================================
TEMPLATES = {
    "Edge / Micro (<5 MW)": {
        "dc_type": "Edge Computing", "p_it": 3.0, "avail_req": 99.90,
        "pue": 1.40, "load_step_pct": 25.0, "spinning_res_pct": 15.0,
        "capacity_factor": 0.75, "peak_avg_ratio": 1.25, "load_ramp_req": 1.0,
        "gen_filter": ["High Speed"], "use_bess": False,
    },
    "Enterprise (5-50 MW)": {
        "dc_type": "Colocation", "p_it": 20.0, "avail_req": 99.98,
        "pue": 1.30, "load_step_pct": 25.0, "spinning_res_pct": 20.0,
        "capacity_factor": 0.85, "peak_avg_ratio": 1.20, "load_ramp_req": 2.0,
        "gen_filter": ["High Speed"], "use_bess": False,
    },
    "Hyperscale (50-200 MW)": {
        "dc_type": "Hyperscale Standard", "p_it": 100.0, "avail_req": 99.99,
        "pue": 1.20, "load_step_pct": 30.0, "spinning_res_pct": 20.0,
        "capacity_factor": 0.90, "peak_avg_ratio": 1.15, "load_ramp_req": 3.0,
        "gen_filter": ["High Speed", "Medium Speed"], "use_bess": True,
    },
    "AI Campus (200+ MW)": {
        "dc_type": "AI Factory (Training)", "p_it": 300.0, "avail_req": 99.99,
        "pue": 1.15, "load_step_pct": 40.0, "spinning_res_pct": 25.0,
        "capacity_factor": 0.95, "peak_avg_ratio": 1.10, "load_ramp_req": 5.0,
        "gen_filter": ["High Speed", "Medium Speed"], "use_bess": True,
    },
}

# ==============================================================================
# HELP TEXTS — explanations for each input shown in wizard and sidebar
# ==============================================================================
HELP_TEXTS = {
    # Header
    "project_name": "A unique name to identify this sizing study (e.g., 'Phoenix DC-1 Prime Power').",
    "client_name": "The end customer or developer requesting this study.",
    "contact_name": "Primary contact person for this project.",
    "contact_email": "Email address for project correspondence.",
    "contact_phone": "Phone number including country code.",
    "country": "Country where the data center will be built.",
    "state_province": "State, province, or region within the country.",
    "county_district": "County, district, or municipality for permitting purposes.",

    # Global
    "unit_system": "Metric uses °C, meters, m². Imperial uses °F, feet, ft².",
    "freq_hz": "Power grid frequency: 60 Hz (Americas, parts of Asia) or 50 Hz (Europe, Africa, most of Asia).",

    # Load Profile
    "template_choice": "Pre-configures typical parameters for common project sizes. You can adjust any value after.",
    "dc_type": "Determines default PUE, step load behavior, and cooling requirements.",
    "p_it": "Total IT critical load in megawatts. This is the net power consumed by servers, storage, and networking.",
    "avail_req": "Target system availability. 99.99% ('four nines') = max 52 min downtime/year. Drives N+X redundancy.",
    "pue": "Power Usage Effectiveness: ratio of total facility power to IT power. PUE 1.2 means 100 MW IT needs 120 MW total.",
    "load_step_pct": "Maximum instantaneous load change as % of total. AI training loads can step 30-40% in milliseconds.",
    "spinning_res_pct": "Extra running capacity above average load to absorb transients without frequency deviation.",
    "capacity_factor": "Fraction of the year the plant operates at average load. 0.90 = 7,884 hours/year.",
    "peak_avg_ratio": "Ratio of peak demand to average demand. Lower ratios indicate flatter, more predictable loads.",
    "load_ramp_req": "Rate of load change in MW per second. AI training clusters can ramp 3-5 MW/s.",

    # Site Conditions
    "derate_mode": "Auto-Calculate uses temperature and altitude to compute derating. Manual lets you enter a fixed factor.",
    "site_temp_c": "Maximum ambient temperature at site. CAT generators do not derate until above 40°C.",
    "site_alt_m": "Site elevation above sea level. Higher altitude = less oxygen = lower output.",
    "methane_number": "Gas quality indicator. Pipeline gas is typically MN 70-90. Below 70 may require derating.",
    "derate_factor_manual": "Manual power derating factor. 0.90 = generators produce 90% of their ISO rating.",
    "enable_footprint_limit": "Enable to constrain the plant within a maximum area. Affects generator count and layout.",
    "bus_tie_mode": ("Bus-tie breaker mode. Closed: maximum availability (ring bus mesh, "
                     "selective protection isolates faults without affecting the rest of the system). "
                     "Open: independent sections (lower short-circuit current, lower availability)."),
    "max_area_m2": "Maximum available area for the power plant in square meters.",

    # Technology
    "gen_filter": "Filter generator library by engine type: High Speed (recip), Medium Speed (recip), or Gas Turbine.",
    "use_bess": "Include Battery Energy Storage System for transient response, black start, and peak shaving.",
    "bess_strategy": "Transient Only: minimum BESS. Hybrid: balanced cost/performance. Reliability Priority: maximum BESS.",
    "enable_black_start": "Size BESS to restart the entire plant from a dead bus without external power.",
    "include_chp": "Include Combined Heat and Power (Tri-Generation). Recovers waste heat for absorption cooling.",
    "cooling_method": "Air-Cooled: simpler, higher footprint. Water-Cooled: more compact, requires water supply.",
    "fuel_mode": "Pipeline: continuous gas supply. LNG: virtual pipeline with on-site storage. Dual: pipeline + LNG backup.",
    "lng_days": "Days of fuel autonomy with on-site LNG storage. Typical: 3-7 days for backup, 10+ for primary.",
    "volt_mode": "Auto-Recommend selects optimal voltage based on plant size. Manual lets you specify.",
    "dist_loss_pct": "Electrical losses from generator terminals to IT load point. Includes transformers and cables.",
    "force_emissions": "Include SCR/Oxidation Catalyst regardless of calculated emissions level.",
    "cost_scr_kw": "Selective Catalytic Reduction cost per kW for NOx control.",
    "cost_oxicat_kw": "Oxidation Catalyst cost per kW for CO/VOC control.",

    # Generator
    "selected_gen_name": "Choose a generator model from the library, or import specifications from a GERP PDF report.",

    # Economics
    "gas_price_pipeline": "Natural gas price delivered via pipeline in $/MMBtu. US average: $2-5, Europe: $8-12.",
    "gas_price_lng": "LNG delivered price including molecule, liquefaction, and freight in $/MMBtu.",
    "benchmark_price": "Grid electricity price for comparison. Used to calculate savings and payback period.",
    "bess_cost_kw": "Battery inverter and power conversion cost per kW of power capacity.",
    "bess_cost_kwh": "Battery cell and rack cost per kWh of energy capacity.",
    "bess_om_kw_yr": "Annual BESS maintenance cost per kW of power capacity.",
    "bess_life_batt": "Battery cell replacement interval in years (augmentation cycle).",
    "bess_life_inv": "Power electronics (inverter) useful life in years.",
    "fuel_infra_mult": "Cost multiplier for fuel infrastructure (civil works, piping, gas regulation). 1.0 = baseline.",
    "lng_tank_cost": "Cost per LNG cryogenic storage tank (~60,000 gallon capacity).",
    "dist_gas_main_m": "Distance from site to the nearest gas pipeline connection point.",
    "wacc": "Weighted Average Cost of Capital. Higher WACC = stricter financial hurdle for project viability.",
    "project_years": "Economic analysis period. Typical: 20 years for infrastructure, 10-15 for technology-heavy.",
    "enable_itc": "Investment Tax Credit (30% of CAPEX). US federal incentive for qualifying projects.",
    "enable_ptc": "Production Tax Credit ($0.013/kWh). US incentive based on actual energy produced.",
    "enable_depreciation": "MACRS 5-year accelerated depreciation. Reduces taxable income in early years.",
    "region": "Geographic region for cost multiplier adjustment. Affects labor, materials, and logistics costs.",
    "carbon_price_per_ton": "Carbon tax or emissions trading cost per metric ton of CO2. $0 = no carbon pricing.",
    "target_lcoe": "Target Levelized Cost of Energy in $/kWh. Used as a benchmark for project viability.",
}

# ==============================================================================
# COUNTRY / LOCATION DATA
# ==============================================================================
COUNTRIES = [
    "",
    # Americas
    "United States", "Canada", "Mexico", "Guatemala", "Honduras", "El Salvador",
    "Nicaragua", "Costa Rica", "Panama", "Cuba", "Dominican Republic", "Haiti",
    "Jamaica", "Trinidad and Tobago", "Bahamas", "Barbados",
    "Colombia", "Venezuela", "Ecuador", "Peru", "Brazil", "Bolivia",
    "Paraguay", "Uruguay", "Argentina", "Chile", "Guyana", "Suriname",
    # Europe — Western
    "United Kingdom", "Ireland", "France", "Belgium", "Netherlands", "Luxembourg",
    "Germany", "Austria", "Switzerland", "Liechtenstein", "Monaco",
    # Europe — Southern
    "Spain", "Portugal", "Italy", "Greece", "Malta", "Cyprus", "Andorra",
    # Europe — Northern
    "Sweden", "Norway", "Denmark", "Finland", "Iceland",
    "Estonia", "Latvia", "Lithuania",
    # Europe — Central & Eastern
    "Poland", "Czech Republic", "Slovakia", "Hungary", "Romania", "Bulgaria",
    "Slovenia", "Croatia", "Serbia", "Bosnia and Herzegovina", "Montenegro",
    "North Macedonia", "Albania", "Kosovo", "Moldova", "Ukraine", "Belarus",
    # Europe — Other
    "Turkey", "Georgia", "Armenia", "Azerbaijan",
    # Middle East
    "Saudi Arabia", "UAE", "Qatar", "Kuwait", "Oman", "Bahrain",
    "Iraq", "Iran", "Israel", "Jordan", "Lebanon", "Syria", "Yemen",
    # Africa — North
    "Egypt", "Libya", "Tunisia", "Algeria", "Morocco",
    # Africa — West
    "Nigeria", "Ghana", "Senegal", "Ivory Coast", "Cameroon", "Mali",
    "Burkina Faso", "Niger", "Guinea", "Benin", "Togo", "Sierra Leone", "Liberia",
    # Africa — East
    "Kenya", "Ethiopia", "Tanzania", "Uganda", "Rwanda", "Mozambique",
    "Madagascar", "Somalia", "Djibouti", "Eritrea",
    # Africa — Southern
    "South Africa", "Namibia", "Botswana", "Zimbabwe", "Zambia",
    "Angola", "Malawi", "Mauritius",
    # Africa — Central
    "Democratic Republic of Congo", "Republic of Congo", "Gabon",
    "Equatorial Guinea", "Central African Republic", "Chad",
    # South Asia
    "India", "Pakistan", "Bangladesh", "Sri Lanka", "Nepal", "Bhutan", "Maldives",
    # East Asia
    "China", "Japan", "South Korea", "North Korea", "Taiwan", "Mongolia",
    # Southeast Asia
    "Indonesia", "Philippines", "Vietnam", "Thailand", "Myanmar", "Malaysia",
    "Singapore", "Cambodia", "Laos", "Brunei", "Timor-Leste",
    # Central Asia
    "Kazakhstan", "Uzbekistan", "Turkmenistan", "Tajikistan", "Kyrgyzstan", "Afghanistan",
    # Oceania
    "Australia", "New Zealand", "Papua New Guinea", "Fiji",
    "Samoa", "Tonga", "Solomon Islands", "Vanuatu",
    # Russia
    "Russia",
    # Other
    "Other",
]


# ==============================================================================
# PROJECT LIFECYCLE
# ==============================================================================
def new_project() -> dict:
    """Create a fresh project with all defaults."""
    return {
        "app_version": APP_VERSION,
        "created": datetime.now().isoformat(),
        "modified": datetime.now().isoformat(),
        "header": deepcopy(HEADER_DEFAULTS),
        "inputs": deepcopy(INPUT_DEFAULTS),
    }


def apply_template(project: dict, template_name: str) -> dict:
    """Apply a template preset — only overrides template-specific keys."""
    tpl = TEMPLATES.get(template_name)
    if tpl:
        project["inputs"].update(deepcopy(tpl))
    project["inputs"]["template_choice"] = template_name
    return project


def project_to_json(project: dict) -> str:
    """Serialize project to JSON string for download."""
    project["modified"] = datetime.now().isoformat()
    return json.dumps(project, indent=2, default=str)


def project_from_json(json_str: str) -> dict:
    """
    Deserialize project from JSON, merging with current defaults
    for forward-compatibility (old files load in newer app versions).
    """
    data = json.loads(json_str)

    # Merge inputs with current defaults (new keys get default values)
    merged_inputs = deepcopy(INPUT_DEFAULTS)
    merged_inputs.update(data.get("inputs", {}))
    data["inputs"] = merged_inputs

    # Merge header
    merged_header = deepcopy(HEADER_DEFAULTS)
    merged_header.update(data.get("header", {}))
    data["header"] = merged_header

    # Ensure version metadata
    data.setdefault("app_version", "unknown")
    data.setdefault("created", datetime.now().isoformat())
    data.setdefault("modified", datetime.now().isoformat())

    return data
