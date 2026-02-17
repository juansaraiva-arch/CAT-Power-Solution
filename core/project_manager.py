"""
CAT Size Solution — Project Manager
=====================================
Single source of truth for:
  - All input defaults (76 inputs)
  - Project header (name, client, contact, location)
  - Save / Load to JSON
  - Template presets
"""

import json
from datetime import datetime
from copy import deepcopy

APP_VERSION = "3.1"

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
    "gen_mtbf_override": None,
    "gen_maint_interval_override": None,
    "gen_maint_duration_override": None,
    "gen_eff_override": None,
    "gen_step_load_override": None,
    "gen_ramp_rate_override": None,
    "gen_cost_kw_override": None,
    "gen_install_kw_override": None,
    "lead_time_weeks": 24,

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

    # Load Distribution
    "load_strategy": "Equal Loading (N units)",
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
    "site_temp_c": "Maximum ambient temperature at site. Higher temperatures reduce generator output.",
    "site_alt_m": "Site elevation above sea level. Higher altitude = less oxygen = lower output.",
    "methane_number": "Gas quality indicator. Pipeline gas is typically MN 70-90. Below 70 may require derating.",
    "derate_factor_manual": "Manual power derating factor. 0.90 = generators produce 90% of their ISO rating.",
    "enable_footprint_limit": "Enable to constrain the plant within a maximum area. Affects generator count and layout.",
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
    "", "United States", "Canada", "Mexico", "Brazil", "Argentina", "Chile", "Colombia",
    "United Kingdom", "Germany", "France", "Spain", "Italy", "Netherlands", "Sweden", "Norway",
    "Saudi Arabia", "UAE", "Qatar", "Kuwait", "Oman", "Bahrain",
    "India", "China", "Japan", "South Korea", "Singapore", "Australia",
    "South Africa", "Nigeria", "Kenya", "Egypt",
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
