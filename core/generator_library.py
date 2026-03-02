"""
CAT Power Solution — Generator Library & GERP Parser
=====================================================
Contains:
  - Full generator specifications library (leps_gas_library)
  - GERP PDF parsing function
  - Helper functions for filtering and querying generators

NO UI dependencies — pure data and parsing logic.
"""

import re
from copy import deepcopy


# ==============================================================================
# GENERATOR SPECIFICATIONS LIBRARY
# ==============================================================================
# Source: Caterpillar LEPS data sheets + engineering estimates
# All costs are placeholder defaults; actual costs are injected from secrets.
# ==============================================================================

GENERATOR_LIBRARY = {
    "XGC1900": {
        "description": "Mobile Power Module (High Speed)",
        "type": "High Speed",
        "iso_rating_mw": 1.9,
        "electrical_efficiency": 0.392,
        "heat_rate_lhv": 8780,
        "step_load_pct": 25.0,
        "ramp_rate_mw_s": 0.5,
        "emissions_nox": 0.5,
        "emissions_co": 2.5,
        "unit_availability": 0.91,
        "default_for": 2.0,
        "default_maint": 5.0,
        "est_cost_kw": 775.0,
        "est_install_kw": 300.0,
        "power_density_mw_per_m2": 0.010,
        "gas_pressure_min_psi": 1.5,
        "reactance_xd_2": 0.14,
        "inertia_h": 1.0,
    },
    "G3520FR": {
        "description": "Fast Response Gen Set (High Speed)",
        "type": "High Speed",
        "iso_rating_mw": 2.5,
        "electrical_efficiency": 0.386,
        "heat_rate_lhv": 8836,
        "step_load_pct": 40.0,
        "ramp_rate_mw_s": 0.6,
        "emissions_nox": 0.5,
        "emissions_co": 2.1,
        "unit_availability": 0.91,
        "default_for": 2.0,
        "default_maint": 5.0,
        "est_cost_kw": 575.0,
        "est_install_kw": 650.0,
        "power_density_mw_per_m2": 0.010,
        "gas_pressure_min_psi": 1.5,
        "reactance_xd_2": 0.14,
        "inertia_h": 1.5,
    },
    "G3520K": {
        "description": "High Efficiency Gen Set (High Speed)",
        "type": "High Speed",
        "iso_rating_mw": 2.4,
        "electrical_efficiency": 0.453,
        "heat_rate_lhv": 7638,
        "step_load_pct": 15.0,
        "ramp_rate_mw_s": 0.4,
        "emissions_nox": 0.267,
        "emissions_co": 2.3,
        "unit_availability": 0.91,
        "default_for": 2.5,
        "default_maint": 6.0,
        "est_cost_kw": 575.0,
        "est_install_kw": 650.0,
        "power_density_mw_per_m2": 0.010,
        "gas_pressure_min_psi": 1.5,
        "reactance_xd_2": 0.13,
        "inertia_h": 1.2,
    },
    "G3516H": {
        "description": "Data Center Workhorse (High Speed, 2.5 MW)",
        "type": "High Speed",
        "iso_rating_mw": 2.5,
        "electrical_efficiency": 0.441,
        "heat_rate_lhv": 7740,
        "step_load_pct": 25.0,
        "ramp_rate_mw_s": 0.5,
        "emissions_nox": 0.5,
        "emissions_co": 2.0,
        "unit_availability": 0.93,
        "default_for": 2.0,
        "default_maint": 5.0,
        "est_cost_kw": 550.0,
        "est_install_kw": 600.0,
        "power_density_mw_per_m2": 0.010,
        "gas_pressure_min_psi": 1.5,
        "reactance_xd_2": 0.14,
        "inertia_h": 1.2,
    },
    "CG260-16": {
        "description": "Cogeneration Specialist (High Speed)",
        "type": "High Speed",
        "iso_rating_mw": 3.957,
        "electrical_efficiency": 0.434,
        "heat_rate_lhv": 7860,
        "step_load_pct": 10.0,
        "ramp_rate_mw_s": 0.45,
        "emissions_nox": 0.5,
        "emissions_co": 1.8,
        "unit_availability": 0.92,
        "default_for": 3.0,
        "default_maint": 5.0,
        "est_cost_kw": 675.0,
        "est_install_kw": 1100.0,
        "power_density_mw_per_m2": 0.009,
        "gas_pressure_min_psi": 7.25,
        "reactance_xd_2": 0.15,
        "inertia_h": 1.3,
    },
    "C175-20": {
        "description": "High Power Gas Gen Set (4 MW, High Speed)",
        "type": "High Speed",
        "iso_rating_mw": 4.0,
        "electrical_efficiency": 0.420,
        "heat_rate_lhv": 8120,
        "step_load_pct": 20.0,
        "ramp_rate_mw_s": 0.5,
        "emissions_nox": 0.5,
        "emissions_co": 1.5,
        "unit_availability": 0.93,
        "default_for": 2.5,
        "default_maint": 5.0,
        "est_cost_kw": 625.0,
        "est_install_kw": 900.0,
        "power_density_mw_per_m2": 0.009,
        "gas_pressure_min_psi": 3.0,
        "reactance_xd_2": 0.15,
        "inertia_h": 1.4,
    },
    "Titan 130": {
        "description": "Solar Gas Turbine (16.5 MW)",
        "type": "Gas Turbine",
        "iso_rating_mw": 16.5,
        "electrical_efficiency": 0.3543,
        "heat_rate_lhv": 9630,
        "step_load_pct": 15.0,
        "ramp_rate_mw_s": 2.0,
        "emissions_nox": 0.6,
        "emissions_co": 0.6,
        "unit_availability": 0.97,
        "default_for": 1.5,
        "default_maint": 2.0,
        "est_cost_kw": 775.0,
        "est_install_kw": 1000.0,
        "power_density_mw_per_m2": 0.020,
        "gas_pressure_min_psi": 300.0,
        "reactance_xd_2": 0.18,
        "inertia_h": 5.0,
    },
    "Titan 250": {
        "description": "Solar Gas Turbine (23.2 MW)",
        "type": "Gas Turbine",
        "iso_rating_mw": 23.2,
        "electrical_efficiency": 0.386,
        "heat_rate_lhv": 8670,
        "step_load_pct": 15.0,
        "ramp_rate_mw_s": 2.5,
        "emissions_nox": 0.6,
        "emissions_co": 0.6,
        "unit_availability": 0.97,
        "default_for": 1.5,
        "default_maint": 2.0,
        "est_cost_kw": 775.0,
        "est_install_kw": 1000.0,
        "power_density_mw_per_m2": 0.020,
        "gas_pressure_min_psi": 400.0,
        "reactance_xd_2": 0.18,
        "inertia_h": 5.0,
    },
    "Titan 350": {
        "description": "Solar Gas Turbine (38 MW)",
        "type": "Gas Turbine",
        "iso_rating_mw": 38.0,
        "electrical_efficiency": 0.402,
        "heat_rate_lhv": 8495,
        "step_load_pct": 15.0,
        "ramp_rate_mw_s": 3.0,
        "emissions_nox": 0.6,
        "emissions_co": 0.6,
        "unit_availability": 0.97,
        "default_for": 1.5,
        "default_maint": 2.0,
        "est_cost_kw": 775.0,
        "est_install_kw": 1000.0,
        "power_density_mw_per_m2": 0.020,
        "gas_pressure_min_psi": 400.0,
        "reactance_xd_2": 0.18,
        "inertia_h": 5.0,
    },
    "G20CM34": {
        "description": "Medium Speed Baseload Platform",
        "type": "Medium Speed",
        "iso_rating_mw": 9.76,
        "electrical_efficiency": 0.475,
        "heat_rate_lhv": 7484,
        "step_load_pct": 10.0,
        "ramp_rate_mw_s": 0.3,
        "emissions_nox": 0.5,
        "emissions_co": 0.5,
        "unit_availability": 0.92,
        "default_for": 3.0,
        "default_maint": 5.0,
        "est_cost_kw": 700.0,
        "est_install_kw": 1250.0,
        "power_density_mw_per_m2": 0.008,
        "gas_pressure_min_psi": 90.0,
        "reactance_xd_2": 0.16,
        "inertia_h": 2.5,
    },
}


# ==============================================================================
# LIBRARY HELPER FUNCTIONS
# ==============================================================================

def get_library(cost_injector=None) -> dict:
    """
    Return a deep copy of the generator library.

    Parameters
    ----------
    cost_injector : callable, optional
        Function(model_name) -> (equip_cost_kw, install_cost_kw).
        If provided, overrides default costs with injected values.

    Returns
    -------
    dict
        Deep copy of GENERATOR_LIBRARY with costs optionally injected.
    """
    lib = deepcopy(GENERATOR_LIBRARY)
    if cost_injector:
        for model in lib:
            try:
                equip, install = cost_injector(model)
                lib[model]["est_cost_kw"] = equip
                lib[model]["est_install_kw"] = install
            except Exception:
                pass  # Keep defaults
    return lib


def filter_by_type(library: dict, type_filter: list) -> dict:
    """Filter generator library by technology type(s)."""
    return {
        k: v for k, v in library.items()
        if v["type"] in type_filter
    }


def get_model_names(library: dict = None) -> list:
    """Return sorted list of all generator model names."""
    lib = library or GENERATOR_LIBRARY
    return sorted(lib.keys())


def get_model_summary(model_name: str, library: dict = None) -> dict:
    """Return a brief summary dict for display purposes."""
    lib = library or GENERATOR_LIBRARY
    data = lib.get(model_name, {})
    if not data:
        return {}
    return {
        "model": model_name,
        "description": data.get("description", ""),
        "type": data.get("type", ""),
        "mw": data.get("iso_rating_mw", 0),
        "efficiency": data.get("electrical_efficiency", 0),
        "step_load_pct": data.get("step_load_pct", 0),
    }


# ==============================================================================
# GERP PDF PARSER
# ==============================================================================

def parse_gerp_pdf(uploaded_file) -> dict:
    """
    Extract key data from a Caterpillar GERP PDF performance report.

    Parses:
      - Site Rating (ekW)
      - Genset Efficiency (%)
      - Heat Rejection (JW, Exhaust, Lube Oil) in kW
      - NOx Emission Level (g/bhp-hr)
      - Model name

    Parameters
    ----------
    uploaded_file : file-like object
        PDF file (from st.file_uploader or open()).

    Returns
    -------
    dict
        Parsed fields: ekW, eff, heat_jw, heat_exh, heat_oc, nox, model.
        Only includes fields that were successfully parsed.
    """
    import pdfplumber

    data = {}
    text_content = ""

    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text_content += page.extract_text() + "\n"

    # 1. SITE RATING (ekW)
    match_power = re.search(r"GENSET POWER.*?(\d{4})", text_content, re.DOTALL)
    if match_power:
        data['ekW'] = float(match_power.group(1))

    # 2. EFFICIENCY (%)
    match_eff = re.search(r"GENSET EFFICIENCY.*?(\d{2}\.\d)", text_content)
    if match_eff:
        data['eff'] = float(match_eff.group(1))

    # 3. HEAT REJECTION (kW)
    match_jw = re.search(r"REJ\. TO JACKET WATER.*?(\d{3,5})", text_content)
    if match_jw:
        data['heat_jw'] = float(match_jw.group(1))

    match_exh = re.search(r"REJECTION TO EXHAUST.*?120.*?(\d{3,5})", text_content)
    if match_exh:
        data['heat_exh'] = float(match_exh.group(1))

    match_oc = re.search(r"REJ\. TO LUBE OIL.*?(\d{3,5})", text_content)
    if match_oc:
        data['heat_oc'] = float(match_oc.group(1))

    # 4. EMISSIONS (NOx)
    match_nox = re.search(r"NOX EMISSION LEVEL.*?(\d\.\d+)", text_content)
    if match_nox:
        data['nox'] = float(match_nox.group(1))

    # 5. MODEL
    match_model = re.search(r"(G\d{4}[A-Z]?)", text_content)
    if match_model:
        data['model'] = match_model.group(1)

    return data
