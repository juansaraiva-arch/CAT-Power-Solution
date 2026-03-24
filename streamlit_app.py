"""
CAT Power Solution — Streamlit App
====================================
Full prime-power sizing tool for data center gas generation.
Calls the sizing pipeline directly (no API server needed).

Deploy on Streamlit Cloud or run locally:
    streamlit run streamlit_app.py
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np

from api.services.sizing_pipeline import run_full_sizing
from api.schemas.sizing import SizingInput
from core.generator_library import GENERATOR_LIBRARY, filter_by_type, parse_gerp_pdf
from core.engine import calculate_site_derate
from core.pdf_report import generate_comprehensive_pdf
from core.proposal_defaults import (
    PROPOSAL_DEFAULTS,
    PROPOSAL_TYPE_OPTIONS,
    INCOTERM_OPTIONS,
    DELIVERY_DESTINATION_OPTIONS,
)
from core.proposal_generator import generate_proposal_docx
from core.project_manager import (
    APP_VERSION,
    INPUT_DEFAULTS,
    TEMPLATES,
    HELP_TEXTS,
    HEADER_DEFAULTS,
    COUNTRIES,
    new_project,
    apply_template,
    project_to_json,
    project_from_json,
)
from security_config import check_auth

import os
ENABLE_PROPOSAL_GEN = os.environ.get("ENABLE_PROPOSAL_GEN", "true").lower() == "true"

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(
    page_title="CAT Power Solution",
    page_icon=":zap:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# =============================================================================
# CONSTANTS
# =============================================================================
DC_TYPES = [
    "AI Factory (Training)",
    "AI Inference",
    "Enterprise Mixed",
    "HPC / Research",
    "Hyperscale Standard",
    "Colocation",
    "Edge Computing",
]

BESS_STRATEGIES = ["Transient Only", "Hybrid (Balanced)", "Reliability Priority"]

REGIONS = [
    "US - Gulf Coast", "US - West Coast", "US - Northeast",
    "US - Midwest", "US - Southeast", "Canada",
    "Europe - West", "Europe - North", "Europe - South",
    "Latin America", "Middle East", "Africa",
    "Asia - Southeast", "Asia - East", "Australia",
]

GEN_TYPE_OPTIONS = ["High Speed", "Medium Speed", "Gas Turbine"]

FUEL_MODES = ["Pipeline Gas", "LNG", "Dual-Fuel"]

ACOUSTIC_TREATMENTS = ["Standard", "Enhanced", "Critical", "Building"]

# Color palette
COLOR_PRIMARY = "#FFCC00"      # CAT Yellow
COLOR_SECONDARY = "#4A90D9"    # Blue
COLOR_DANGER = "#E74C3C"       # Red
COLOR_SUCCESS = "#27AE60"      # Green
COLOR_GREY = "#7F8C8D"

# Wizard step definitions
WIZARD_STEPS = [
    {"title": "Project Info",      "icon": ":clipboard:", "short": "Info"},
    {"title": "Load Profile",      "icon": ":bar_chart:", "short": "Load"},
    {"title": "Site & Technology",  "icon": ":gear:",      "short": "Site"},
    {"title": "Economics",         "icon": ":moneybag:",  "short": "Econ"},
    {"title": "Review & Run",      "icon": ":rocket:",    "short": "Review"},
]


# =============================================================================
# UNIT SYSTEM HELPERS
# =============================================================================

def _get_unit_sys() -> str:
    """Return current unit system from session state."""
    return st.session_state.get("_unit_sys", "Metric")


def _temp_label() -> str:
    return "\u00b0F" if _get_unit_sys() == "Imperial" else "\u00b0C"


def _to_display_temp(c: float) -> float:
    """Convert Celsius to display unit."""
    return c * 9.0 / 5.0 + 32.0 if _get_unit_sys() == "Imperial" else c


def _from_display_temp(v: float) -> float:
    """Convert display temp back to Celsius for the engine."""
    return (v - 32.0) * 5.0 / 9.0 if _get_unit_sys() == "Imperial" else v


def _alt_label() -> str:
    return "ft" if _get_unit_sys() == "Imperial" else "m"


def _to_display_alt(m: float) -> float:
    return m * 3.28084 if _get_unit_sys() == "Imperial" else m


def _from_display_alt(v: float) -> float:
    return v / 3.28084 if _get_unit_sys() == "Imperial" else v


def _dist_label() -> str:
    return "ft" if _get_unit_sys() == "Imperial" else "m"


def _to_display_dist(m: float) -> float:
    return m * 3.28084 if _get_unit_sys() == "Imperial" else m


def _from_display_dist(v: float) -> float:
    return v / 3.28084 if _get_unit_sys() == "Imperial" else v


def _area_label() -> str:
    return "ft\u00b2" if _get_unit_sys() == "Imperial" else "m\u00b2"


def _to_display_area(m2: float) -> float:
    return m2 * 10.7639 if _get_unit_sys() == "Imperial" else m2


def _from_display_area(v: float) -> float:
    return v / 10.7639 if _get_unit_sys() == "Imperial" else v


# =============================================================================
# OTHER HELPERS
# =============================================================================

def _get_filtered_models(type_filter: list) -> list:
    """Return generator model names matching the type filter."""
    if not type_filter:
        type_filter = ["High Speed"]
    filtered = filter_by_type(GENERATOR_LIBRARY, type_filter)
    return sorted(filtered.keys())


def _fmt(value, fmt_str=".2f"):
    """Format a number safely."""
    try:
        return f"{value:{fmt_str}}"
    except (TypeError, ValueError):
        return str(value)


def _pct(value, decimals=1):
    """Format a fraction or percentage for display."""
    try:
        if value is None:
            return "N/A"
        if value > 1:
            return f"{value:.{decimals}f}%"
        return f"{value * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return str(value)


def _safe_get(d: dict, key: str, default=0):
    """Safely get a value from a dict, returning default if missing or None."""
    if not d:
        return default
    val = d.get(key, default)
    return val if val is not None else default


# =============================================================================
# WIZARD — 5-STEP GUIDED SETUP
# =============================================================================

def _init_wizard_state():
    """Initialize wizard session state keys to defaults if missing."""
    defaults = {
        "_wizard_step": 0,
        "_wizard_complete": False,
        "_wizard_running": False,
        # Step 1: Project Info
        "_wiz_project_name": HEADER_DEFAULTS.get("project_name", ""),
        "_wiz_client_name": HEADER_DEFAULTS.get("client_name", ""),
        "_wiz_contact_name": HEADER_DEFAULTS.get("contact_name", ""),
        "_wiz_contact_email": HEADER_DEFAULTS.get("contact_email", ""),
        "_wiz_contact_phone": HEADER_DEFAULTS.get("contact_phone", ""),
        "_wiz_country": HEADER_DEFAULTS.get("country", ""),
        "_wiz_state_province": HEADER_DEFAULTS.get("state_province", ""),
        "_wiz_county_district": HEADER_DEFAULTS.get("county_district", ""),
        "_wiz_freq_hz": INPUT_DEFAULTS["freq_hz"],
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def render_wizard_stepper():
    """Render horizontal step progress indicator."""
    current = st.session_state.get("_wizard_step", 0)
    steps_html = '<div style="display:flex;align-items:center;justify-content:center;gap:4px;padding:12px 0;flex-wrap:wrap;">'
    for i, step in enumerate(WIZARD_STEPS):
        is_complete = i < current
        is_current = i == current
        if is_current:
            bg, fg, weight = "#FFCC00", "#000", "bold"
        elif is_complete:
            bg, fg, weight = "#4A90D9", "#fff", "normal"
        else:
            bg, fg, weight = "#ddd", "#888", "normal"
        txt = "&#10003;" if is_complete else str(i + 1)
        label_color = "#000" if is_current else "#888"
        steps_html += (
            f'<div style="display:flex;align-items:center;gap:4px;">'
            f'<div style="width:28px;height:28px;border-radius:50%;background:{bg};'
            f'color:{fg};display:flex;align-items:center;justify-content:center;'
            f'font-size:13px;font-weight:bold;">{txt}</div>'
            f'<span style="font-size:13px;font-weight:{weight};color:{label_color};">'
            f'{step["title"]}</span></div>'
        )
        if i < len(WIZARD_STEPS) - 1:
            line_color = "#4A90D9" if i < current else "#ddd"
            steps_html += f'<div style="width:40px;height:2px;background:{line_color};margin:0 4px;"></div>'
    steps_html += '</div>'
    st.markdown(steps_html, unsafe_allow_html=True)


def _render_load_preview():
    """Show computed Total DC, Average, and Peak loads."""
    p_it = st.session_state.get("_wiz_p_it", float(INPUT_DEFAULTS["p_it"]))
    pue = st.session_state.get("_wiz_pue", float(INPUT_DEFAULTS["pue"]))
    cf = st.session_state.get("_wiz_capacity_factor", float(INPUT_DEFAULTS["capacity_factor"]))
    par = st.session_state.get("_wiz_peak_avg_ratio", float(INPUT_DEFAULTS["peak_avg_ratio"]))
    total_dc = p_it * pue
    avg_load = total_dc * cf
    peak_load = avg_load * par  # PAR = Peak/Average, so Peak = Average × PAR
    c1, c2, c3 = st.columns(3)
    c1.metric("Total DC Load", f"{total_dc:.1f} MW")
    c2.metric("Average Load", f"{avg_load:.1f} MW")
    c3.metric("Peak Load", f"{peak_load:.1f} MW")
    if peak_load > total_dc:
        st.caption(
            f"ℹ️ Peak ({peak_load:.1f} MW) > Total DC Load ({total_dc:.1f} MW) "
            f"— expected when CF < 1.0 and PAR > CF. Fleet must cover peak."
        )


# ── Step 1: Project Info ──

def render_wizard_step_1():
    st.header(":clipboard: Project Info")
    st.caption("Enter project identification and site location details.")

    st.subheader("Project Details")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Project Name", key="_wiz_project_name",
                       placeholder="Phoenix DC-1 Prime Power",
                       help=HELP_TEXTS.get("project_name", ""))
        st.text_input("Contact Name", key="_wiz_contact_name",
                       help=HELP_TEXTS.get("contact_name", ""))
        st.text_input("Contact Phone", key="_wiz_contact_phone",
                       help=HELP_TEXTS.get("contact_phone", ""))
    with col2:
        st.text_input("Client Name", key="_wiz_client_name",
                       placeholder="Acme Corp",
                       help=HELP_TEXTS.get("client_name", ""))
        st.text_input("Contact Email", key="_wiz_contact_email",
                       help=HELP_TEXTS.get("contact_email", ""))

    st.divider()
    st.subheader("Site Location")
    col1, col2, col3 = st.columns(3)
    with col1:
        country_idx = 0
        wiz_country = st.session_state.get("_wiz_country", "")
        if wiz_country in COUNTRIES:
            country_idx = COUNTRIES.index(wiz_country)
        st.selectbox("Country", COUNTRIES, index=country_idx,
                      key="_wiz_country", help=HELP_TEXTS.get("country", ""))
    with col2:
        st.text_input("State / Province", key="_wiz_state_province",
                       help=HELP_TEXTS.get("state_province", ""))
    with col3:
        st.text_input("County / District", key="_wiz_county_district",
                       help=HELP_TEXTS.get("county_district", ""))

    st.divider()
    freq_options = [60, 50]
    freq_idx = freq_options.index(st.session_state.get("_wiz_freq_hz", 60)) if st.session_state.get("_wiz_freq_hz", 60) in freq_options else 0
    st.radio("Grid Frequency (Hz)", freq_options, index=freq_idx,
             horizontal=True, key="_wiz_freq_hz",
             help=HELP_TEXTS.get("freq_hz", ""))


# ── Step 2: Load Profile ──

def render_wizard_step_2():
    st.header(":bar_chart: Load Profile")
    st.caption("Define the data center load characteristics.")

    # Unit system toggle
    unit_options = ["Metric", "Imperial"]
    unit_sys = st.radio("Unit System", unit_options, index=0,
                         horizontal=True, key="_wiz_unit_sys",
                         help=HELP_TEXTS.get("unit_system", ""))
    st.session_state["_unit_sys"] = unit_sys

    st.divider()

    # Template quick start
    st.subheader("Quick Start Template")
    template_options = ["Custom (Manual)"] + list(TEMPLATES.keys())
    template = st.selectbox("Template", template_options, index=0,
                             key="_wiz_template",
                             help="Select a pre-configured template to auto-fill common settings.")

    st.divider()

    # Application
    st.subheader("Application")
    col1, col2, col3 = st.columns(3)
    with col1:
        dc_default = INPUT_DEFAULTS["dc_type"]
        dc_idx = DC_TYPES.index(dc_default) if dc_default in DC_TYPES else 0
        st.selectbox("Data Center Type", DC_TYPES, index=dc_idx,
                      key="_wiz_dc_type", help=HELP_TEXTS.get("dc_type", ""))
    with col2:
        st.number_input("Critical IT Load (MW)", min_value=0.1, max_value=2000.0,
                         value=float(INPUT_DEFAULTS["p_it"]), step=1.0,
                         key="_wiz_p_it", help=HELP_TEXTS.get("p_it", ""))
    with col3:
        st.number_input("Availability (%)", min_value=90.0, max_value=100.0,
                         value=float(INPUT_DEFAULTS["avail_req"]), step=0.01,
                         format="%.2f", key="_wiz_avail_req",
                         help=HELP_TEXTS.get("avail_req", ""))

    st.divider()

    # Load Dynamics
    st.subheader("Load Dynamics")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.number_input("PUE", min_value=1.0, max_value=3.0,
                         value=float(INPUT_DEFAULTS["pue"]), step=0.05,
                         format="%.2f", key="_wiz_pue",
                         help=HELP_TEXTS.get("pue", ""))
        st.slider("Capacity Factor", min_value=0.50, max_value=1.0,
                   value=float(INPUT_DEFAULTS["capacity_factor"]), step=0.01,
                   key="_wiz_capacity_factor",
                   help=HELP_TEXTS.get("capacity_factor", ""))
    with col2:
        st.number_input("Max Step Load (%)", min_value=0.0, max_value=100.0,
                         value=float(INPUT_DEFAULTS["load_step_pct"]), step=5.0,
                         key="_wiz_load_step_pct",
                         help=HELP_TEXTS.get("load_step_pct", ""))
        st.number_input("Peak/Avg Ratio", min_value=1.0, max_value=2.0,
                         value=float(INPUT_DEFAULTS["peak_avg_ratio"]), step=0.05,
                         format="%.2f", key="_wiz_peak_avg_ratio",
                         help=HELP_TEXTS.get("peak_avg_ratio", ""))
    with col3:
        # spinning_res_pct removed — now derived from physical contingencies (P04)
        st.number_input("Load Ramp Rate (MW/min)", min_value=0.1, max_value=100.0,
                         value=float(INPUT_DEFAULTS["load_ramp_req"]), step=0.5,
                         key="_wiz_load_ramp_req",
                         help=HELP_TEXTS.get("load_ramp_req", ""))

    st.divider()
    _render_load_preview()


# ── Step 3: Site & Technology ──

def render_wizard_step_3():
    st.header(":gear: Site & Technology")
    st.caption("Configure site conditions and technology selections.")

    # Site Conditions
    st.subheader(":thermometer: Site Conditions")
    derate_mode = st.radio("Derate Mode", ["Auto-Calculate", "Manual"],
                            index=0, horizontal=True, key="_wiz_derate_mode",
                            help=HELP_TEXTS.get("derate_mode", ""))

    if derate_mode == "Auto-Calculate":
        col1, col2, col3 = st.columns(3)
        with col1:
            site_temp_display = st.number_input(
                f"Ambient Temperature ({_temp_label()})",
                min_value=_to_display_temp(-40.0),
                max_value=_to_display_temp(60.0),
                value=_to_display_temp(float(INPUT_DEFAULTS["site_temp_c"])),
                step=1.0, key="_wiz_site_temp_display",
                help=HELP_TEXTS.get("site_temp_c", ""))
            site_temp_c = _from_display_temp(site_temp_display)
        with col2:
            site_alt_display = st.number_input(
                f"Site Altitude ({_alt_label()})",
                min_value=0.0, max_value=_to_display_alt(5000.0),
                value=_to_display_alt(float(INPUT_DEFAULTS["site_alt_m"])),
                step=50.0, key="_wiz_site_alt_display",
                help=HELP_TEXTS.get("site_alt_m", ""))
            site_alt_m = _from_display_alt(site_alt_display)
        with col3:
            methane_number = st.number_input(
                "Methane Number", min_value=0, max_value=100,
                value=int(INPUT_DEFAULTS["methane_number"]), step=5,
                key="_wiz_methane_number",
                help=HELP_TEXTS.get("methane_number", ""))

        _dr = calculate_site_derate(site_temp_c, site_alt_m, methane_number)
        st.info(
            f"**Derate Factor: {_dr['derate_factor']:.4f}**  \n"
            f"Methane: {_dr['methane_deration']:.4f} | "
            f"Altitude: {_dr['altitude_deration']:.4f} | "
            f"ACHRF: {_dr['achrf']:.4f}"
        )
        if _dr.get('methane_warning'):
            st.warning(_dr['methane_warning'])
        st.session_state["_wiz_site_temp_c"] = site_temp_c
        st.session_state["_wiz_site_alt_m"] = site_alt_m
    else:
        st.number_input("Manual Derate Factor", min_value=0.01, max_value=1.0,
                         value=float(INPUT_DEFAULTS["derate_factor_manual"]),
                         step=0.05, format="%.2f", key="_wiz_derate_factor_manual",
                         help=HELP_TEXTS.get("derate_factor_manual", ""))

    st.divider()

    # Generator Selection
    st.subheader("Generator Selection")
    col1, col2 = st.columns([2, 1])
    with col1:
        gen_filter = st.multiselect("Generator Types", GEN_TYPE_OPTIONS,
                                     default=INPUT_DEFAULTS["gen_filter"],
                                     key="_wiz_gen_filter",
                                     help=HELP_TEXTS.get("gen_filter", ""))
        available_models = _get_filtered_models(gen_filter)
        default_gen = INPUT_DEFAULTS["selected_gen_name"]
        gen_idx = available_models.index(default_gen) if default_gen in available_models else 0
        generator_model = st.selectbox("Generator Model", available_models,
                                        index=gen_idx, key="_wiz_generator_model",
                                        help=HELP_TEXTS.get("selected_gen_name", ""))
    with col2:
        gen_data = GENERATOR_LIBRARY.get(generator_model, {})
        if gen_data:
            st.metric("ISO Rating", f"{gen_data.get('iso_rating_mw', 0)} MW")
            st.metric("Efficiency", f"{gen_data.get('electrical_efficiency', 0)*100:.1f}%")
            st.caption(gen_data.get("description", ""))

    with st.expander(":page_facing_up: Import from GERP PDF"):
        uploaded_pdf = st.file_uploader("Upload GERP PDF", type=["pdf"], key="_wiz_gerp_pdf")
        if uploaded_pdf:
            try:
                gerp_data = parse_gerp_pdf(uploaded_pdf)
                if gerp_data:
                    st.success(f"Parsed: {gerp_data.get('model', 'Unknown')}")
                    for k, v in gerp_data.items():
                        st.caption(f"**{k}**: {v}")
                else:
                    st.warning("Could not extract data from PDF.")
            except Exception as e:
                st.error(f"PDF parse error: {e}")

    st.divider()

    # Technology Options
    st.subheader("Technology Options")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.checkbox("Include BESS", value=INPUT_DEFAULTS["use_bess"],
                     key="_wiz_use_bess", help=HELP_TEXTS.get("use_bess", ""))
    with col2:
        st.checkbox("Black Start", value=INPUT_DEFAULTS["enable_black_start"],
                     key="_wiz_enable_black_start",
                     help=HELP_TEXTS.get("enable_black_start", ""))
    with col3:
        st.checkbox("CHP / Tri-Gen", value=False,
                     key="_wiz_include_chp", help=HELP_TEXTS.get("include_chp", ""))

    if st.session_state.get("_wiz_use_bess", True):
        bess_idx = BESS_STRATEGIES.index(INPUT_DEFAULTS["bess_strategy"]) if INPUT_DEFAULTS["bess_strategy"] in BESS_STRATEGIES else 1
        st.selectbox("BESS Strategy", BESS_STRATEGIES, index=bess_idx,
                      key="_wiz_bess_strategy", help=HELP_TEXTS.get("bess_strategy", ""))

    col1, col2 = st.columns(2)
    with col1:
        st.radio("Cooling", ["Air-Cooled", "Water-Cooled"], index=0,
                  horizontal=True, key="_wiz_cooling",
                  help=HELP_TEXTS.get("cooling_method", ""))
        fuel_mode = st.radio("Fuel Mode", FUEL_MODES, index=0, horizontal=True,
                              key="_wiz_fuel_mode",
                              help=HELP_TEXTS.get("fuel_mode", ""))
        if fuel_mode in ("LNG", "Dual-Fuel"):
            st.number_input("LNG Storage (days)", min_value=1, max_value=30,
                            value=int(INPUT_DEFAULTS["lng_days"]), step=1,
                            key="_wiz_lng_days", help=HELP_TEXTS.get("lng_days", ""))
    with col2:
        st.radio("Voltage Mode", ["Auto-Recommend", "Manual"], index=0,
                  horizontal=True, key="_wiz_volt_mode",
                  help=HELP_TEXTS.get("volt_mode", ""))
        if st.session_state.get("_wiz_volt_mode") == "Manual":
            st.number_input("Manual Voltage (kV)", min_value=0.48, max_value=69.0,
                            value=float(INPUT_DEFAULTS["manual_voltage_kv"]),
                            step=0.1, format="%.1f", key="_wiz_manual_voltage_kv")
        st.number_input("Distribution Losses (%)", min_value=0.0, max_value=10.0,
                         value=float(INPUT_DEFAULTS["dist_loss_pct"]), step=0.5,
                         key="_wiz_dist_loss_pct",
                         help=HELP_TEXTS.get("dist_loss_pct", ""))


# ── Step 4: Economics ──

def render_wizard_step_4():
    st.header(":moneybag: Economics")
    st.caption("Set financial parameters and cost assumptions.")

    st.subheader("Fuel & Energy Pricing")
    col1, col2 = st.columns(2)
    with col1:
        st.number_input("Pipeline Gas Price ($/MMBtu)", min_value=0.0, max_value=50.0,
                         value=float(INPUT_DEFAULTS["gas_price_pipeline"]), step=0.5,
                         key="_wiz_gas_price",
                         help=HELP_TEXTS.get("gas_price_pipeline", ""))
    with col2:
        st.number_input("Grid Benchmark ($/kWh)", min_value=0.0, max_value=1.0,
                         value=float(INPUT_DEFAULTS["benchmark_price"]), step=0.01,
                         format="%.3f", key="_wiz_benchmark_price",
                         help=HELP_TEXTS.get("benchmark_price", ""))

    st.divider()
    st.subheader("Financial Parameters")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.number_input("WACC (%)", min_value=0.0, max_value=30.0,
                         value=float(INPUT_DEFAULTS["wacc"]), step=0.5,
                         key="_wiz_wacc", help=HELP_TEXTS.get("wacc", ""))
    with col2:
        st.number_input("Project Life (years)", min_value=1, max_value=40,
                         value=int(INPUT_DEFAULTS["project_years"]), step=1,
                         key="_wiz_project_years",
                         help=HELP_TEXTS.get("project_years", ""))
    with col3:
        region_idx = REGIONS.index(INPUT_DEFAULTS["region"]) if INPUT_DEFAULTS["region"] in REGIONS else 0
        st.selectbox("Region", REGIONS, index=region_idx,
                      key="_wiz_region", help=HELP_TEXTS.get("region", ""))

    col1, col2 = st.columns(2)
    with col1:
        st.checkbox("MACRS Depreciation", value=INPUT_DEFAULTS["enable_depreciation"],
                     key="_wiz_enable_depreciation",
                     help=HELP_TEXTS.get("enable_depreciation", ""))
    with col2:
        st.number_input("Carbon Price ($/ton CO2)", min_value=0.0, max_value=500.0,
                         value=float(INPUT_DEFAULTS["carbon_price_per_ton"]), step=5.0,
                         key="_wiz_carbon_price",
                         help=HELP_TEXTS.get("carbon_price_per_ton", ""))

    # BESS Costs
    if st.session_state.get("_wiz_use_bess", INPUT_DEFAULTS["use_bess"]):
        st.divider()
        st.subheader("BESS Economics")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.number_input("BESS Power Cost ($/kW)", min_value=0.0,
                             value=float(INPUT_DEFAULTS["bess_cost_kw"]), step=25.0,
                             key="_wiz_bess_cost_kw",
                             help=HELP_TEXTS.get("bess_cost_kw", ""))
        with col2:
            st.number_input("BESS Energy Cost ($/kWh)", min_value=0.0,
                             value=float(INPUT_DEFAULTS["bess_cost_kwh"]), step=25.0,
                             key="_wiz_bess_cost_kwh",
                             help=HELP_TEXTS.get("bess_cost_kwh", ""))
        with col3:
            st.number_input("BESS O&M ($/kW-yr)", min_value=0.0,
                             value=float(INPUT_DEFAULTS["bess_om_kw_yr"]), step=1.0,
                             key="_wiz_bess_om_kw_yr",
                             help=HELP_TEXTS.get("bess_om_kw_yr", ""))

    # CAPEX BOS Adders (Fix M — P06)
    st.divider()
    with st.expander("Advanced CAPEX Adders", expanded=False):
        st.caption("As % of (generator equipment + installation) base cost.")
        c1, c2 = st.columns(2)
        with c1:
            st.number_input("BOS / Switchgear + Xfmr (%)", 0.0, 50.0,
                            INPUT_DEFAULTS['bos_pct']*100, 1.0,
                            key="_wiz_bos_pct")
            st.number_input("Civil / Site Work (%)", 0.0, 50.0,
                            INPUT_DEFAULTS['civil_pct']*100, 1.0,
                            key="_wiz_civil_pct")
            st.number_input("Fuel System (%)", 0.0, 30.0,
                            INPUT_DEFAULTS['fuel_system_pct']*100, 0.5,
                            key="_wiz_fuel_system_pct")
        with c2:
            st.number_input("MV Electrical (%)", 0.0, 30.0,
                            INPUT_DEFAULTS['electrical_pct']*100, 0.5,
                            key="_wiz_electrical_pct")
            st.number_input("EPC Management (%)", 0.0, 30.0,
                            INPUT_DEFAULTS['epc_pct']*100, 1.0,
                            key="_wiz_epc_pct")
            st.number_input("Contingency (%)", 0.0, 30.0,
                            INPUT_DEFAULTS['contingency_pct']*100, 1.0,
                            key="_wiz_contingency_pct")

    # Footprint
    st.divider()
    st.subheader("Footprint Constraint")
    col1, col2 = st.columns(2)
    with col1:
        st.checkbox("Limit Site Area", value=INPUT_DEFAULTS["enable_footprint_limit"],
                     key="_wiz_enable_footprint_limit",
                     help=HELP_TEXTS.get("enable_footprint_limit", ""))
    with col2:
        if st.session_state.get("_wiz_enable_footprint_limit", False):
            st.number_input(f"Max Area ({_area_label()})",
                            min_value=_to_display_area(100.0),
                            value=_to_display_area(float(INPUT_DEFAULTS["max_area_m2"])),
                            step=500.0, key="_wiz_max_area_display",
                            help=HELP_TEXTS.get("max_area_m2", ""))


# ── Step 5: Review & Run ──

def render_wizard_step_5():
    st.header(":rocket: Review & Run")
    st.caption("Verify your inputs before running the sizing calculation.")

    col1, col2, col3 = st.columns(3)
    ss = st.session_state

    with col1:
        st.markdown("**Application**")
        pn = ss.get("_wiz_project_name", "")
        if pn:
            st.write(f"Project: **{pn}**")
        st.write(f"Type: {ss.get('_wiz_dc_type', INPUT_DEFAULTS['dc_type'])}")
        st.write(f"IT Load: **{ss.get('_wiz_p_it', INPUT_DEFAULTS['p_it']):.1f} MW**")
        st.write(f"Availability: {ss.get('_wiz_avail_req', INPUT_DEFAULTS['avail_req']):.2f}%")
        st.write(f"PUE: {ss.get('_wiz_pue', INPUT_DEFAULTS['pue']):.2f}")
        st.write(f"Capacity Factor: {ss.get('_wiz_capacity_factor', INPUT_DEFAULTS['capacity_factor']):.2f}")

    with col2:
        st.markdown("**Site & Technology**")
        st.write(f"Temperature: {ss.get('_wiz_site_temp_c', INPUT_DEFAULTS['site_temp_c']):.0f} \u00b0C")
        st.write(f"Altitude: {ss.get('_wiz_site_alt_m', INPUT_DEFAULTS['site_alt_m']):.0f} m")
        st.write(f"Generator: **{ss.get('_wiz_generator_model', INPUT_DEFAULTS['selected_gen_name'])}**")
        bess_label = "Yes" if ss.get("_wiz_use_bess", INPUT_DEFAULTS["use_bess"]) else "No"
        st.write(f"BESS: {bess_label}")
        st.write(f"Fuel: {ss.get('_wiz_fuel_mode', INPUT_DEFAULTS['fuel_mode'])}")
        st.write(f"Frequency: {ss.get('_wiz_freq_hz', INPUT_DEFAULTS['freq_hz'])} Hz")

    with col3:
        st.markdown("**Economics**")
        st.write(f"Gas Price: ${ss.get('_wiz_gas_price', INPUT_DEFAULTS['gas_price_pipeline'])}/MMBtu")
        st.write(f"Benchmark: ${ss.get('_wiz_benchmark_price', INPUT_DEFAULTS['benchmark_price'])}/kWh")
        st.write(f"WACC: {ss.get('_wiz_wacc', INPUT_DEFAULTS['wacc'])}%")
        st.write(f"Project Life: {ss.get('_wiz_project_years', INPUT_DEFAULTS['project_years'])} years")
        st.write(f"Region: {ss.get('_wiz_region', INPUT_DEFAULTS['region'])}")

    st.divider()
    _render_load_preview()
    st.divider()
    st.info("Click **Run Sizing** below to calculate the optimal fleet configuration.")


# ── Navigation ──

def render_wizard_navigation():
    """Back / Next / Run Sizing buttons."""
    current = st.session_state.get("_wizard_step", 0)
    col_left, col_spacer, col_right = st.columns([1, 3, 1])
    with col_left:
        if current > 0:
            if st.button(":arrow_left: Back", use_container_width=True, key="_wiz_nav_back"):
                st.session_state["_wizard_step"] = current - 1
                st.rerun()
    with col_right:
        if current < 4:
            if st.button("Next :arrow_right:", use_container_width=True, type="primary",
                          key="_wiz_nav_next"):
                st.session_state["_wizard_step"] = current + 1
                st.rerun()
        else:
            if st.button(":zap: Run Sizing", use_container_width=True, type="primary",
                          key="_wiz_run_sizing"):
                st.session_state["_wizard_running"] = True
                st.session_state["_wizard_complete"] = True
                st.rerun()


# ── Input Assembly ──

def _build_inputs_from_wizard():
    """Build inputs_dict from wizard session state. Returns (inputs_dict, benchmark_price)."""
    ss = st.session_state
    gen_model = ss.get("_wiz_generator_model", INPUT_DEFAULTS["selected_gen_name"])
    gen_data = GENERATOR_LIBRARY.get(gen_model, {})

    max_area_m2 = float(INPUT_DEFAULTS["max_area_m2"])
    if ss.get("_wiz_enable_footprint_limit", False):
        max_area_display = ss.get("_wiz_max_area_display", _to_display_area(float(INPUT_DEFAULTS["max_area_m2"])))
        max_area_m2 = _from_display_area(max_area_display)

    benchmark_price = float(ss.get("_wiz_benchmark_price", INPUT_DEFAULTS["benchmark_price"]))

    inputs_dict = dict(
        p_it=float(ss.get("_wiz_p_it", INPUT_DEFAULTS["p_it"])),
        pue=float(ss.get("_wiz_pue", INPUT_DEFAULTS["pue"])),
        capacity_factor=float(ss.get("_wiz_capacity_factor", INPUT_DEFAULTS["capacity_factor"])),
        peak_avg_ratio=float(ss.get("_wiz_peak_avg_ratio", INPUT_DEFAULTS["peak_avg_ratio"])),
        load_step_pct=float(ss.get("_wiz_load_step_pct", INPUT_DEFAULTS["load_step_pct"])),
        spinning_res_pct=0.0,  # deprecated — engine now uses physical SR calculation (P04)
        avail_req=float(ss.get("_wiz_avail_req", INPUT_DEFAULTS["avail_req"])),
        load_ramp_req=float(ss.get("_wiz_load_ramp_req", INPUT_DEFAULTS["load_ramp_req"])),
        dc_type=ss.get("_wiz_dc_type", INPUT_DEFAULTS["dc_type"]),
        derate_mode=ss.get("_wiz_derate_mode", INPUT_DEFAULTS["derate_mode"]),
        site_temp_c=float(ss.get("_wiz_site_temp_c", INPUT_DEFAULTS["site_temp_c"])),
        site_alt_m=float(ss.get("_wiz_site_alt_m", INPUT_DEFAULTS["site_alt_m"])),
        methane_number=int(ss.get("_wiz_methane_number", INPUT_DEFAULTS["methane_number"])),
        derate_factor_manual=float(ss.get("_wiz_derate_factor_manual", INPUT_DEFAULTS["derate_factor_manual"])),
        generator_model=gen_model,
        gen_overrides=None,
        use_bess=ss.get("_wiz_use_bess", INPUT_DEFAULTS["use_bess"]),
        bess_strategy=ss.get("_wiz_bess_strategy", INPUT_DEFAULTS["bess_strategy"]),
        enable_black_start=ss.get("_wiz_enable_black_start", INPUT_DEFAULTS["enable_black_start"]),
        cooling_method=ss.get("_wiz_cooling", INPUT_DEFAULTS["cooling_method"]),
        freq_hz=int(ss.get("_wiz_freq_hz", INPUT_DEFAULTS["freq_hz"])),
        dist_loss_pct=float(ss.get("_wiz_dist_loss_pct", INPUT_DEFAULTS["dist_loss_pct"])),
        aux_load_pct=gen_data.get("aux_load_pct", float(INPUT_DEFAULTS["aux_load_pct"])),
        volt_mode=ss.get("_wiz_volt_mode", INPUT_DEFAULTS["volt_mode"]),
        manual_voltage_kv=float(ss.get("_wiz_manual_voltage_kv", INPUT_DEFAULTS["manual_voltage_kv"])),
        gas_price=float(ss.get("_wiz_gas_price", INPUT_DEFAULTS["gas_price_pipeline"])),
        gas_price_lng=float(INPUT_DEFAULTS.get("gas_price_lng", 9.5)),
        wacc=float(ss.get("_wiz_wacc", INPUT_DEFAULTS["wacc"])),
        project_years=int(ss.get("_wiz_project_years", INPUT_DEFAULTS["project_years"])),
        benchmark_price=benchmark_price,
        carbon_price_per_ton=float(ss.get("_wiz_carbon_price", INPUT_DEFAULTS["carbon_price_per_ton"])),
        enable_depreciation=ss.get("_wiz_enable_depreciation", INPUT_DEFAULTS["enable_depreciation"]),
        pipeline_cost_usd=float(INPUT_DEFAULTS["pipeline_cost_usd"]),
        permitting_cost_usd=float(INPUT_DEFAULTS["permitting_cost_usd"]),
        commissioning_cost_usd=float(INPUT_DEFAULTS["commissioning_cost_usd"]),
        pipeline_distance_km=float(INPUT_DEFAULTS["pipeline_distance_km"]),
        pipeline_diameter_inch=float(INPUT_DEFAULTS["pipeline_diameter_inch"]),
        gas_supply_pressure_psia=float(INPUT_DEFAULTS.get("gas_supply_pressure_psia", 100.0)),
        gas_pipeline_length_miles=float(INPUT_DEFAULTS.get("gas_pipeline_length_miles", 1.0)),
        max_maintenance_units=int(INPUT_DEFAULTS.get("max_maintenance_units", 1)),
        selected_fleet_config_maint=INPUT_DEFAULTS.get("selected_fleet_config_maint", "B"),
        bess_cost_kw=float(ss.get("_wiz_bess_cost_kw", INPUT_DEFAULTS["bess_cost_kw"])),
        bess_cost_kwh=float(ss.get("_wiz_bess_cost_kwh", INPUT_DEFAULTS["bess_cost_kwh"])),
        bess_om_kw_yr=float(ss.get("_wiz_bess_om_kw_yr", INPUT_DEFAULTS["bess_om_kw_yr"])),
        # CAPEX BOS adders (Fix M — P06)
        bos_pct=float(ss.get("_wiz_bos_pct", INPUT_DEFAULTS["bos_pct"]*100)) / 100,
        civil_pct=float(ss.get("_wiz_civil_pct", INPUT_DEFAULTS["civil_pct"]*100)) / 100,
        fuel_system_pct=float(ss.get("_wiz_fuel_system_pct", INPUT_DEFAULTS["fuel_system_pct"]*100)) / 100,
        electrical_pct=float(ss.get("_wiz_electrical_pct", INPUT_DEFAULTS["electrical_pct"]*100)) / 100,
        epc_pct=float(ss.get("_wiz_epc_pct", INPUT_DEFAULTS["epc_pct"]*100)) / 100,
        commissioning_pct=float(INPUT_DEFAULTS["commissioning_pct"]),
        contingency_pct=float(ss.get("_wiz_contingency_pct", INPUT_DEFAULTS["contingency_pct"]*100)) / 100,
        fuel_mode=ss.get("_wiz_fuel_mode", INPUT_DEFAULTS["fuel_mode"]),
        lng_days=int(ss.get("_wiz_lng_days", INPUT_DEFAULTS["lng_days"])),
        lng_backup_pct=float(INPUT_DEFAULTS["lng_backup_pct"]),
        include_chp=ss.get("_wiz_include_chp", False),
        chp_recovery_eff=float(INPUT_DEFAULTS["chp_recovery_eff"]),
        absorption_cop=float(INPUT_DEFAULTS["absorption_cop"]),
        cooling_load_mw=float(INPUT_DEFAULTS["cooling_load_mw"]),
        include_scr=False,
        include_oxicat=False,
        noise_limit_db=float(INPUT_DEFAULTS["noise_limit_db"]),
        distance_to_property_m=float(INPUT_DEFAULTS["distance_to_property_m"]),
        distance_to_residence_m=float(INPUT_DEFAULTS["distance_to_residence_m"]),
        acoustic_treatment=INPUT_DEFAULTS["acoustic_treatment"],
        enable_phasing=False,
        n_phases=3,
        months_between_phases=6,
        enable_footprint_limit=ss.get("_wiz_enable_footprint_limit", False),
        max_area_m2=max_area_m2,
        region=ss.get("_wiz_region", INPUT_DEFAULTS["region"]),
        unit_system=ss.get("_wiz_unit_sys", "Metric"),
    )
    return inputs_dict, benchmark_price


# ── Master Wizard Renderer ──

def render_wizard():
    """Full wizard experience — hides sidebar, renders steps."""
    # Hide sidebar during wizard
    st.markdown("""
    <style>
        [data-testid="stSidebar"] { display: none; }
        [data-testid="stSidebarCollapsedControl"] { display: none; }
    </style>
    """, unsafe_allow_html=True)

    st.image("assets/logo_caterpillar.png", width=350)
    st.caption(f"Power Solution v{APP_VERSION} — Prime Power Quick-Size Wizard")

    render_wizard_stepper()
    st.divider()

    step = st.session_state.get("_wizard_step", 0)
    step_renderers = [
        render_wizard_step_1,
        render_wizard_step_2,
        render_wizard_step_3,
        render_wizard_step_4,
        render_wizard_step_5,
    ]
    step_renderers[step]()

    st.divider()
    render_wizard_navigation()


# =============================================================================
# SIDEBAR -- INPUT SECTIONS
# =============================================================================
def render_sidebar():
    """Render all sidebar input sections. Returns (inputs_dict, benchmark_price)."""

    st.sidebar.image("assets/logo_caterpillar.png", width=200)
    st.sidebar.caption(f"Power Solution v{APP_VERSION}")

    # ---- Logout button ----
    user_email = st.session_state.get("auth_user", "")
    if user_email:
        st.sidebar.caption(f"Signed in as **{user_email}**")
        if st.sidebar.button("Sign Out", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    st.sidebar.divider()

    # ---- 1. Unit System Toggle ----
    unit_sys = st.sidebar.radio(
        "Unit System", ["Metric", "Imperial"],
        index=0, horizontal=True,
        help=HELP_TEXTS.get("unit_system", ""),
    )
    st.session_state["_unit_sys"] = unit_sys

    st.sidebar.divider()

    # ---- 2. Template Preset ----
    template_options = ["Custom (Manual)"] + list(TEMPLATES.keys())
    template = st.sidebar.selectbox(
        "Project Template",
        template_options,
        index=0,
        help=HELP_TEXTS.get("template_choice", ""),
    )

    if template != "Custom (Manual)":
        tpl = TEMPLATES[template]
        for k, v in tpl.items():
            if k in st.session_state:
                st.session_state[k] = v

    st.sidebar.divider()

    # ---- 3. GERP PDF Import ----
    with st.sidebar.expander(":page_facing_up: GERP PDF Import"):
        uploaded_pdf = st.file_uploader("Upload GERP PDF", type=["pdf"], key="gerp_pdf")
        if uploaded_pdf:
            try:
                gerp_data = parse_gerp_pdf(uploaded_pdf)
                if gerp_data:
                    st.success(f"Parsed: {gerp_data.get('model', 'Unknown')}")
                    for k, v in gerp_data.items():
                        st.caption(f"**{k}**: {v}")
                else:
                    st.warning("Could not extract data from PDF.")
            except Exception as e:
                st.error(f"PDF parse error: {e}")

    # ---- 4. Load Profile ----
    with st.sidebar.expander(":bar_chart: Load Profile", expanded=True):
        dc_type = st.selectbox(
            "Data Center Type", DC_TYPES,
            index=DC_TYPES.index(INPUT_DEFAULTS["dc_type"]),
            help=HELP_TEXTS.get("dc_type", ""),
        )
        p_it = st.number_input(
            "IT Load (MW)", min_value=0.1, max_value=2000.0,
            value=float(INPUT_DEFAULTS["p_it"]), step=1.0,
            help=HELP_TEXTS.get("p_it", ""),
        )
        pue = st.number_input(
            "PUE", min_value=1.0, max_value=3.0,
            value=float(INPUT_DEFAULTS["pue"]), step=0.05,
            format="%.2f", help=HELP_TEXTS.get("pue", ""),
        )
        capacity_factor = st.slider(
            "Capacity Factor", min_value=0.50, max_value=1.0,
            value=float(INPUT_DEFAULTS["capacity_factor"]), step=0.01,
            help=HELP_TEXTS.get("capacity_factor", ""),
        )
        peak_avg_ratio = st.number_input(
            "Peak / Average Ratio", min_value=1.0, max_value=2.0,
            value=float(INPUT_DEFAULTS["peak_avg_ratio"]), step=0.05,
            format="%.2f", help=HELP_TEXTS.get("peak_avg_ratio", ""),
        )
        load_step_pct = st.number_input(
            "Max Step Load (%)", min_value=0.0, max_value=100.0,
            value=float(INPUT_DEFAULTS["load_step_pct"]), step=5.0,
            help=HELP_TEXTS.get("load_step_pct", ""),
        )
        # spinning_res_pct removed — now derived from physical contingencies (P04)
        spinning_res_pct = 0.0

        st.markdown("**Protection Limits**")
        voltage_sag_limit_pct = st.number_input(
            "Max Voltage Sag (%)", min_value=5.0, max_value=35.0,
            value=float(INPUT_DEFAULTS.get('voltage_sag_limit_pct', 15.0)), step=1.0,
            help="Maximum acceptable voltage sag at generator bus during a load step event. "
                 "Typical data center requirement: 10-20%.",
        )
        _freq_default = float(INPUT_DEFAULTS.get("freq_hz", 60))
        freq_nadir_limit_hz = st.number_input(
            "Min Frequency Nadir (Hz)", min_value=55.0, max_value=_freq_default - 0.1,
            value=float(INPUT_DEFAULTS.get('freq_nadir_limit_hz', _freq_default - 0.5)),
            step=0.1, format="%.1f",
            help="Minimum acceptable frequency during a contingency event. "
                 "IEEE 1547 / NERC: 59.5 Hz for 60 Hz systems.",
        )
        freq_rocof_limit_hz_s = st.number_input(
            "Max RoCoF (Hz/s)", min_value=0.1, max_value=10.0,
            value=float(INPUT_DEFAULTS.get('freq_rocof_limit_hz_s', 2.0)),
            step=0.1, format="%.1f",
            help="Maximum rate of change of frequency. IEEE 1547: 2.0 Hz/s.",
        )

        avail_req = st.number_input(
            "Availability Requirement (%)", min_value=90.0, max_value=100.0,
            value=float(INPUT_DEFAULTS["avail_req"]), step=0.01,
            format="%.2f", help=HELP_TEXTS.get("avail_req", ""),
        )
        load_ramp_req = st.number_input(
            "Load Ramp Rate (MW/min)", min_value=0.1, max_value=100.0,
            value=float(INPUT_DEFAULTS["load_ramp_req"]), step=0.5,
            help=HELP_TEXTS.get("load_ramp_req", ""),
        )

    # ---- 5. Site Conditions ----
    with st.sidebar.expander(":thermometer: Site Conditions"):
        temp_default_c = float(INPUT_DEFAULTS["site_temp_c"])
        temp_display_default = _to_display_temp(temp_default_c)
        temp_min = _to_display_temp(-40.0)
        temp_max = _to_display_temp(60.0)
        site_temp_display = st.number_input(
            f"Ambient Temperature ({_temp_label()})",
            min_value=temp_min, max_value=temp_max,
            value=temp_display_default, step=1.0,
            help=HELP_TEXTS.get("site_temp_c", ""),
        )
        site_temp_c = _from_display_temp(site_temp_display)

        alt_default_m = float(INPUT_DEFAULTS["site_alt_m"])
        alt_display_default = _to_display_alt(alt_default_m)
        site_alt_display = st.number_input(
            f"Site Altitude ({_alt_label()})",
            min_value=0.0, max_value=_to_display_alt(5000.0),
            value=alt_display_default, step=50.0,
            help=HELP_TEXTS.get("site_alt_m", ""),
        )
        site_alt_m = _from_display_alt(site_alt_display)

        methane_number = st.number_input(
            "Methane Number", min_value=0, max_value=100,
            value=int(INPUT_DEFAULTS["methane_number"]), step=5,
            help=HELP_TEXTS.get("methane_number", ""),
        )
        derate_mode = st.radio(
            "Derate Mode", ["Auto-Calculate", "Manual"],
            index=0, horizontal=True,
            help=HELP_TEXTS.get("derate_mode", ""),
        )
        derate_factor_manual = 0.9
        if derate_mode == "Auto-Calculate":
            _dr = calculate_site_derate(site_temp_c, site_alt_m, methane_number)
            st.info(
                f"**Derate Factor: {_dr['derate_factor']:.4f}**  \n"
                f"Methane: {_dr['methane_deration']:.4f} | "
                f"Altitude: {_dr['altitude_deration']:.4f} | "
                f"ACHRF: {_dr['achrf']:.4f}"
            )
            if _dr.get('methane_warning'):
                st.warning(_dr['methane_warning'])
        else:
            derate_factor_manual = st.number_input(
                "Manual Derate Factor", min_value=0.01, max_value=1.0,
                value=float(INPUT_DEFAULTS["derate_factor_manual"]), step=0.05,
                format="%.2f", help=HELP_TEXTS.get("derate_factor_manual", ""),
            )

    # ---- 6. Technology ----
    with st.sidebar.expander(":gear: Technology"):
        gen_filter = st.multiselect(
            "Generator Types", GEN_TYPE_OPTIONS,
            default=INPUT_DEFAULTS["gen_filter"],
            help=HELP_TEXTS.get("gen_filter", ""),
        )
        available_models = _get_filtered_models(gen_filter)
        default_gen = INPUT_DEFAULTS["selected_gen_name"]
        gen_idx = available_models.index(default_gen) if default_gen in available_models else 0
        generator_model = st.selectbox(
            "Generator Model", available_models, index=gen_idx,
            help=HELP_TEXTS.get("selected_gen_name", ""),
        )

        # Show selected gen specs
        gen_data = GENERATOR_LIBRARY.get(generator_model, {})
        if gen_data:
            st.caption(gen_data.get("description", ""))
            col_a, col_b = st.columns(2)
            col_a.metric("ISO Rating", f"{gen_data['iso_rating_mw']} MW")
            col_b.metric("Efficiency", f"{gen_data['electrical_efficiency']*100:.1f}%")

        freq_hz = st.radio(
            "Grid Frequency (Hz)", [60, 50],
            index=0, horizontal=True,
            help=HELP_TEXTS.get("freq_hz", ""),
        )
        use_bess = st.checkbox(
            "Include BESS", value=INPUT_DEFAULTS["use_bess"],
            help=HELP_TEXTS.get("use_bess", ""),
        )
        bess_strategy = INPUT_DEFAULTS["bess_strategy"]
        if use_bess:
            bess_strategy = st.selectbox(
                "BESS Strategy", BESS_STRATEGIES,
                index=BESS_STRATEGIES.index(INPUT_DEFAULTS["bess_strategy"]),
                help=HELP_TEXTS.get("bess_strategy", ""),
            )
        enable_black_start = st.checkbox(
            "Black Start Capable", value=INPUT_DEFAULTS["enable_black_start"],
            help=HELP_TEXTS.get("enable_black_start", ""),
        )
        max_maintenance_units = st.number_input(
            "Max generators in maintenance simultaneously",
            min_value=0, max_value=10,
            value=int(INPUT_DEFAULTS.get('max_maintenance_units', 1)),
            step=1,
            help=(
                "Maximum number of generators that may be under scheduled maintenance "
                "when a pod-level fault occurs simultaneously. "
                "0 = strict scheduling (no maintenance during risk windows). "
                "1 = realistic default for fleets of 50+ units."
            ),
        )
        cooling_method = st.radio(
            "Cooling Method", ["Air-Cooled", "Water-Cooled"],
            index=0, horizontal=True,
            help=HELP_TEXTS.get("cooling_method", ""),
        )
        dist_loss_pct = st.number_input(
            "Distribution Losses (%)", min_value=0.0, max_value=10.0,
            value=float(INPUT_DEFAULTS["dist_loss_pct"]), step=0.5,
            help=HELP_TEXTS.get("dist_loss_pct", ""),
        )
        fuel_mode = st.radio(
            "Fuel Supply", FUEL_MODES,
            index=0, horizontal=True,
            help=HELP_TEXTS.get("fuel_mode", ""),
        )
        lng_days = int(INPUT_DEFAULTS["lng_days"])
        lng_backup_pct = 30.0
        gas_price_lng = float(INPUT_DEFAULTS.get("gas_price_lng", 8.0))

        if fuel_mode in ("LNG", "Dual-Fuel"):
            lng_days = st.number_input(
                "LNG Storage (days)", min_value=1, max_value=30,
                value=int(INPUT_DEFAULTS["lng_days"]), step=1,
                help=HELP_TEXTS.get("lng_days", ""),
            )
            gas_price_lng = st.number_input(
                "LNG Price ($/MMBtu)", min_value=0.0, max_value=50.0,
                value=float(INPUT_DEFAULTS.get("gas_price_lng", 8.0)), step=0.5,
                help=HELP_TEXTS.get("gas_price_lng", "LNG delivered price in $/MMBtu."),
            )
            if fuel_mode == "Dual-Fuel":
                lng_backup_pct = st.number_input(
                    "LNG Backup (%)", min_value=0.0, max_value=100.0,
                    value=30.0, step=5.0,
                    help="Percentage of load backed by LNG in dual-fuel mode.",
                )

    # ---- 7. Generator Parameters ----
    with st.sidebar.expander(":wrench: Generator Parameters"):
        gen_data_params = GENERATOR_LIBRARY.get(generator_model, {})

        override_iso = st.number_input(
            "ISO Rating (MW)",
            value=float(gen_data_params.get('iso_rating_mw', 2.5)),
            step=0.1, format="%.2f",
        )
        override_voltage = st.number_input(
            "Voltage (kV)",
            value=float(gen_data_params.get('voltage_kv', 13.8)),
            step=0.1, format="%.1f",
        )
        override_aux = st.number_input(
            "Aux Load (%)",
            value=float(gen_data_params.get('aux_load_pct', 4.0)),
            step=0.5, format="%.1f",
        )
        override_avail = st.number_input(
            "Availability (%)", min_value=80.0, max_value=100.0,
            value=float(gen_data_params.get('unit_availability', 0.93) * 100),
            step=0.5, format="%.1f",
        )
        override_eff = st.number_input(
            "Efficiency (%)",
            value=float(gen_data_params.get('electrical_efficiency', 0.40) * 100),
            step=0.5, format="%.1f",
        )
        override_step = st.number_input(
            "Step Load (%)",
            value=float(gen_data_params.get('step_load_pct', 25)),
            step=5.0, format="%.0f",
        )
        override_ramp = st.number_input(
            "Ramp Rate (MW/s)",
            value=float(gen_data_params.get('ramp_rate_mw_s', 0.5)),
            step=0.1, format="%.2f",
        )
        override_cost = st.number_input(
            "Equipment Cost ($/kW)",
            value=float(gen_data_params.get('est_cost_kw', 600)),
            step=25.0, format="%.0f",
        )
        override_install = st.number_input(
            "Install Cost ($/kW)",
            value=float(gen_data_params.get('est_install_kw', 600)),
            step=25.0, format="%.0f",
        )
        override_inertia = st.number_input(
            "Inertia Constant H (s)", min_value=0.1, max_value=10.0,
            value=float(gen_data_params.get('inertia_h', 1.0)),
            step=0.1, format="%.1f",
            help="Generator rotating mass inertia constant (H). "
                 "Reciprocating gas engines: 0.5–1.5 s. "
                 "Synchronous machines: 2–8 s. "
                 "Lower H → faster frequency drop after a contingency.",
        )

        # Build overrides dict (only include changed values)
        gen_overrides = {}
        lib_iso = gen_data_params.get('iso_rating_mw', 2.5)
        if abs(override_iso - lib_iso) > 0.001:
            gen_overrides['iso_rating_mw'] = override_iso

        lib_aux = gen_data_params.get('aux_load_pct', 4.0)
        if abs(override_aux - lib_aux) > 0.001:
            gen_overrides['aux_load_pct'] = override_aux

        lib_avail = gen_data_params.get('unit_availability', 0.93)
        if abs(override_avail / 100.0 - lib_avail) > 0.001:
            gen_overrides['unit_availability'] = override_avail / 100.0

        lib_eff = gen_data_params.get('electrical_efficiency', 0.40)
        if abs(override_eff / 100.0 - lib_eff) > 0.001:
            gen_overrides['electrical_efficiency'] = override_eff / 100.0

        lib_step = gen_data_params.get('step_load_pct', 25)
        if abs(override_step - lib_step) > 0.001:
            gen_overrides['step_load_pct'] = override_step

        lib_ramp = gen_data_params.get('ramp_rate_mw_s', 0.5)
        if abs(override_ramp - lib_ramp) > 0.001:
            gen_overrides['ramp_rate_mw_s'] = override_ramp

        lib_cost = gen_data_params.get('est_cost_kw', 600)
        if abs(override_cost - lib_cost) > 0.001:
            gen_overrides['est_cost_kw'] = override_cost

        lib_install = gen_data_params.get('est_install_kw', 600)
        if abs(override_install - lib_install) > 0.001:
            gen_overrides['est_install_kw'] = override_install

        lib_inertia = gen_data_params.get('inertia_h', 1.0)
        if abs(override_inertia - lib_inertia) > 0.01:
            gen_overrides['inertia_h'] = override_inertia

        if gen_overrides:
            st.info(f"{len(gen_overrides)} parameter(s) overridden")

    # ---- 8. Voltage ----
    with st.sidebar.expander(":electric_plug: Voltage"):
        volt_mode = st.radio(
            "Voltage Mode", ["Auto-Recommend", "Manual"],
            index=0, horizontal=True,
            help=HELP_TEXTS.get("volt_mode", ""),
        )
        manual_voltage_kv = 13.8
        if volt_mode == "Manual":
            manual_voltage_kv = st.number_input(
                "Manual Voltage (kV)", min_value=0.48, max_value=69.0,
                value=float(INPUT_DEFAULTS["manual_voltage_kv"]), step=0.1,
                format="%.1f",
            )

    # ---- 9. Economics ----
    with st.sidebar.expander(":moneybag: Economics"):
        region = st.selectbox(
            "Region", REGIONS,
            index=REGIONS.index(INPUT_DEFAULTS["region"]),
            help=HELP_TEXTS.get("region", ""),
        )
        gas_price = st.number_input(
            "Pipeline Gas Price ($/MMBtu)", min_value=0.0, max_value=50.0,
            value=float(INPUT_DEFAULTS["gas_price_pipeline"]), step=0.5,
            help=HELP_TEXTS.get("gas_price_pipeline", ""),
        )
        wacc = st.number_input(
            "WACC (%)", min_value=0.0, max_value=30.0,
            value=float(INPUT_DEFAULTS["wacc"]), step=0.5,
            help=HELP_TEXTS.get("wacc", ""),
        )
        project_years = st.number_input(
            "Project Life (years)", min_value=1, max_value=40,
            value=int(INPUT_DEFAULTS["project_years"]), step=1,
            help=HELP_TEXTS.get("project_years", ""),
        )
        benchmark_price = st.number_input(
            "Grid Benchmark ($/kWh)", min_value=0.0, max_value=1.0,
            value=float(INPUT_DEFAULTS["benchmark_price"]), step=0.01,
            format="%.3f", help=HELP_TEXTS.get("benchmark_price", ""),
        )
        carbon_price_per_ton = st.number_input(
            "Carbon Price ($/ton CO2)", min_value=0.0, max_value=500.0,
            value=float(INPUT_DEFAULTS["carbon_price_per_ton"]), step=5.0,
            help=HELP_TEXTS.get("carbon_price_per_ton", ""),
        )
        enable_depreciation = st.checkbox(
            "MACRS Depreciation", value=INPUT_DEFAULTS["enable_depreciation"],
            help=HELP_TEXTS.get("enable_depreciation", ""),
        )

        st.markdown("**BESS Costs**")
        bess_cost_kw = st.number_input(
            "BESS Power Cost ($/kW)", min_value=0.0,
            value=float(INPUT_DEFAULTS["bess_cost_kw"]), step=25.0,
            help=HELP_TEXTS.get("bess_cost_kw", ""),
        )
        bess_cost_kwh = st.number_input(
            "BESS Energy Cost ($/kWh)", min_value=0.0,
            value=float(INPUT_DEFAULTS["bess_cost_kwh"]), step=25.0,
            help=HELP_TEXTS.get("bess_cost_kwh", ""),
        )
        bess_om_kw_yr = st.number_input(
            "BESS O&M ($/kW-yr)", min_value=0.0,
            value=float(INPUT_DEFAULTS["bess_om_kw_yr"]), step=1.0,
            help=HELP_TEXTS.get("bess_om_kw_yr", ""),
        )

        st.markdown("**CAPEX Adders** *(% of gen + install base)*")
        with st.expander("Advanced CAPEX Adders", expanded=False):
            st.caption(
                "Applied as a percentage of (generator equipment + installation) subtotal. "
                "Defaults calibrated to CAT prime power data center projects."
            )
            col1, col2 = st.columns(2)
            with col1:
                bos_pct = st.number_input(
                    "BOS / Switchgear + Xfmr (%)", 0.0, 50.0,
                    value=float(INPUT_DEFAULTS.get('bos_pct', 0.17)) * 100, step=1.0,
                    help="MV switchgear, transformers, protection relays.",
                ) / 100.0
                civil_pct = st.number_input(
                    "Civil / Site Work (%)", 0.0, 50.0,
                    value=float(INPUT_DEFAULTS.get('civil_pct', 0.13)) * 100, step=1.0,
                    help="Foundations, grading, drainage, fencing.",
                ) / 100.0
                fuel_system_pct = st.number_input(
                    "Fuel System (%)", 0.0, 30.0,
                    value=float(INPUT_DEFAULTS.get('fuel_system_pct', 0.06)) * 100, step=0.5,
                    help="Gas piping, regulators, metering.",
                ) / 100.0
            with col2:
                epc_pct = st.number_input(
                    "EPC Management (%)", 0.0, 30.0,
                    value=float(INPUT_DEFAULTS.get('epc_pct', 0.12)) * 100, step=1.0,
                    help="Engineering, procurement, construction management.",
                ) / 100.0
                contingency_pct = st.number_input(
                    "Contingency (%)", 0.0, 30.0,
                    value=float(INPUT_DEFAULTS.get('contingency_pct', 0.10)) * 100, step=1.0,
                    help="Project contingency allowance.",
                ) / 100.0

            # Infrastructure costs (absolute $)
            st.markdown("**Infrastructure (absolute $)**")
            col3, col4 = st.columns(2)
            with col3:
                pipeline_cost_usd = st.number_input(
                    "Gas Pipeline ($)", min_value=0.0,
                    value=float(INPUT_DEFAULTS.get('pipeline_cost_usd', 500000.0)),
                    step=50000.0, format="%.0f",
                    help="Gas supply pipeline to site. Default: $500k (typical short run).",
                )
            with col4:
                permitting_cost_usd = st.number_input(
                    "Permitting ($)", min_value=0.0,
                    value=float(INPUT_DEFAULTS.get('permitting_cost_usd', 250000.0)),
                    step=25000.0, format="%.0f",
                    help="Environmental, electrical, and construction permits.",
                )
            commissioning_cost_usd = st.number_input(
                "Commissioning ($)", min_value=0.0,
                value=float(INPUT_DEFAULTS.get('commissioning_cost_usd', 0.0)),
                step=50000.0, format="%.0f",
                help="Startup and commissioning. If 0, calculated automatically from "
                     "CAPEX adder (2.5% of gen+install).",
            )

            st.markdown("**Gas Supply Parameters**")
            gas_supply_pressure_psia = st.number_input(
                "Supply Pressure (psia)", min_value=10.0, max_value=1500.0,
                value=float(INPUT_DEFAULTS.get('gas_supply_pressure_psia', 100.0)),
                step=10.0, format="%.0f",
                help=(
                    "Gas utility supply pressure at site boundary. "
                    "Typical values: 60-100 psia (medium pressure industrial distribution), "
                    "250-500 psia (high pressure transmission). "
                    "Gas turbines require 200-300 psia — compressor may be needed."
                ),
            )
            gas_pipeline_length_miles = st.number_input(
                "Pipeline Distance (miles)", min_value=0.1, max_value=50.0,
                value=float(INPUT_DEFAULTS.get('gas_pipeline_length_miles', 1.0)),
                step=0.5, format="%.1f",
                help="Distance from utility tap to site boundary (Weymouth equation).",
            )

    # ---- 10. CHP / Tri-Gen ----
    with st.sidebar.expander(":fire: CHP / Tri-Gen"):
        include_chp = st.checkbox(
            "Include CHP / Tri-Generation",
            value=INPUT_DEFAULTS.get("include_chp", False),
            help=HELP_TEXTS.get("include_chp", ""),
        )
        chp_recovery_eff = 0.50
        absorption_cop = 0.70
        cooling_load_mw = 0.0
        if include_chp:
            chp_recovery_eff = st.number_input(
                "Heat Recovery Efficiency", min_value=0.0, max_value=0.90,
                value=0.50, step=0.05, format="%.2f",
                help="Fraction of waste heat recovered for useful work.",
            )
            absorption_cop = st.number_input(
                "Absorption Chiller COP", min_value=0.0, max_value=1.5,
                value=0.70, step=0.05, format="%.2f",
                help="Coefficient of Performance of the absorption chiller.",
            )
            cooling_load_mw = st.number_input(
                "Cooling Load (MW thermal)", min_value=0.0,
                value=0.0, step=1.0,
                help="Site cooling demand in MW thermal.",
            )

    # ---- 11. Emissions Control ----
    with st.sidebar.expander(":factory: Emissions Control"):
        include_scr = st.checkbox(
            "Include SCR (NOx Reduction)",
            value=False,
            help="Selective Catalytic Reduction for NOx control.",
        )
        include_oxicat = st.checkbox(
            "Include Oxidation Catalyst (CO Reduction)",
            value=False,
            help="Oxidation catalyst for CO and VOC control.",
        )

    # ---- 12. Noise ----
    with st.sidebar.expander(":loud_sound: Noise"):
        noise_limit_db = st.number_input(
            "Noise Limit at Property Line (dBA)",
            min_value=30.0, max_value=100.0,
            value=65.0, step=1.0,
            help="Maximum allowable noise level at the property boundary.",
        )
        dist_prop_default = 100.0
        dist_prop_display = _to_display_dist(dist_prop_default)
        distance_to_property_display = st.number_input(
            f"Distance to Property Line ({_dist_label()})",
            min_value=_to_display_dist(1.0),
            value=dist_prop_display, step=10.0,
            help="Distance from power plant center to nearest property boundary.",
        )
        distance_to_property_m = _from_display_dist(distance_to_property_display)

        dist_res_default = 300.0
        dist_res_display = _to_display_dist(dist_res_default)
        distance_to_residence_display = st.number_input(
            f"Distance to Nearest Residence ({_dist_label()})",
            min_value=_to_display_dist(1.0),
            value=dist_res_display, step=10.0,
            help="Distance from power plant center to nearest residence.",
        )
        distance_to_residence_m = _from_display_dist(distance_to_residence_display)

        acoustic_treatment = st.selectbox(
            "Acoustic Treatment Level",
            ACOUSTIC_TREATMENTS,
            index=0,
            help="Standard: basic enclosure. Enhanced: additional barriers. "
                 "Critical: hospital-grade. Building: fully enclosed.",
        )

    # ---- 13. Phasing ----
    with st.sidebar.expander(":calendar: Phasing"):
        enable_phasing = st.checkbox(
            "Enable Phased Deployment",
            value=False,
            help="Deploy generators in multiple phases to match load growth.",
        )
        n_phases = 3
        months_between_phases = 6
        if enable_phasing:
            n_phases = st.number_input(
                "Number of Phases", min_value=1, max_value=5,
                value=3, step=1,
            )
            months_between_phases = st.number_input(
                "Months Between Phases", min_value=1, max_value=24,
                value=6, step=1,
            )

    # ---- 14. Infrastructure ----
    with st.sidebar.expander(":building_construction: Infrastructure"):
        pipeline_cost_usd = st.number_input(
            "Pipeline Cost ($)", min_value=0.0,
            value=float(INPUT_DEFAULTS["pipeline_cost_usd"]), step=10000.0,
            format="%.0f",
        )
        permitting_cost_usd = st.number_input(
            "Permitting Cost ($)", min_value=0.0,
            value=float(INPUT_DEFAULTS["permitting_cost_usd"]), step=10000.0,
            format="%.0f",
        )
        commissioning_cost_usd = st.number_input(
            "Commissioning Cost ($)", min_value=0.0,
            value=float(INPUT_DEFAULTS["commissioning_cost_usd"]), step=10000.0,
            format="%.0f",
        )
        pipeline_distance_km = st.number_input(
            "Pipeline Distance (km)", min_value=0.0,
            value=0.0, step=0.5,
            help="Distance from gas main to site. 0 = skip auto-calculation.",
        )
        pipeline_diameter_inch = st.number_input(
            "Pipeline Diameter (inch)", min_value=2.0, max_value=48.0,
            value=6.0, step=1.0,
            help="Nominal pipeline diameter in inches.",
        )

    # ---- 15. Footprint ----
    with st.sidebar.expander(":world_map: Footprint"):
        enable_footprint_limit = st.checkbox(
            "Limit Site Area", value=INPUT_DEFAULTS["enable_footprint_limit"],
            help=HELP_TEXTS.get("enable_footprint_limit", ""),
        )
        max_area_m2 = float(INPUT_DEFAULTS["max_area_m2"])
        if enable_footprint_limit:
            area_display_default = _to_display_area(float(INPUT_DEFAULTS["max_area_m2"]))
            max_area_display = st.number_input(
                f"Max Area ({_area_label()})", min_value=_to_display_area(100.0),
                value=area_display_default, step=500.0,
                help=HELP_TEXTS.get("max_area_m2", ""),
            )
            max_area_m2 = _from_display_area(max_area_display)

    st.sidebar.divider()

    # ---- Project Save/Load ----
    st.sidebar.divider()
    st.sidebar.caption("Project File")
    col_save, col_load = st.sidebar.columns(2)
    with col_save:
        if st.button(":floppy_disk: Save", use_container_width=True):
            proj = new_project()
            proj["inputs"] = {
                "p_it": p_it, "pue": pue, "dc_type": dc_type,
                "capacity_factor": capacity_factor, "peak_avg_ratio": peak_avg_ratio,
                "generator_model": generator_model, "site_temp_c": site_temp_c,
                "site_alt_m": site_alt_m,
            }
            st.session_state["_project_json"] = project_to_json(proj)

    if st.session_state.get("_project_json"):
        st.sidebar.download_button(
            ":arrow_down: Download JSON",
            data=st.session_state["_project_json"],
            file_name="cat_project.json",
            mime="application/json",
        )

    with col_load:
        proj_file = st.file_uploader("Load", type=["json"], key="proj_load", label_visibility="collapsed")
        if proj_file:
            try:
                proj = project_from_json(proj_file.read().decode("utf-8"))
                st.sidebar.success("Project loaded")
            except Exception as e:
                st.sidebar.error(f"Load error: {e}")

    # ---- Build inputs dict ----
    aux_load_pct_val = override_aux if gen_overrides.get('aux_load_pct') else gen_data_params.get('aux_load_pct', 4.0)

    inputs_dict = dict(
        p_it=p_it,
        pue=pue,
        capacity_factor=capacity_factor,
        peak_avg_ratio=peak_avg_ratio,
        load_step_pct=load_step_pct,
        spinning_res_pct=spinning_res_pct,
        avail_req=avail_req,
        load_ramp_req=load_ramp_req,
        dc_type=dc_type,
        derate_mode=derate_mode,
        site_temp_c=site_temp_c,
        site_alt_m=site_alt_m,
        methane_number=methane_number,
        derate_factor_manual=derate_factor_manual,
        generator_model=generator_model,
        gen_overrides=gen_overrides if gen_overrides else None,
        use_bess=use_bess,
        bess_strategy=bess_strategy,
        enable_black_start=enable_black_start,
        cooling_method=cooling_method,
        freq_hz=freq_hz,
        dist_loss_pct=dist_loss_pct,
        aux_load_pct=aux_load_pct_val,
        volt_mode=volt_mode,
        manual_voltage_kv=manual_voltage_kv,
        gas_price=gas_price,
        gas_price_lng=gas_price_lng,
        wacc=wacc,
        project_years=project_years,
        benchmark_price=benchmark_price,
        carbon_price_per_ton=carbon_price_per_ton,
        enable_depreciation=enable_depreciation,
        pipeline_cost_usd=pipeline_cost_usd,
        permitting_cost_usd=permitting_cost_usd,
        commissioning_cost_usd=commissioning_cost_usd,
        pipeline_distance_km=pipeline_distance_km,
        pipeline_diameter_inch=pipeline_diameter_inch,
        gas_supply_pressure_psia=gas_supply_pressure_psia,
        gas_pipeline_length_miles=gas_pipeline_length_miles,
        bess_cost_kw=bess_cost_kw,
        bess_cost_kwh=bess_cost_kwh,
        bess_om_kw_yr=bess_om_kw_yr,
        fuel_mode=fuel_mode,
        lng_days=lng_days,
        lng_backup_pct=lng_backup_pct,
        include_chp=include_chp,
        chp_recovery_eff=chp_recovery_eff,
        absorption_cop=absorption_cop,
        cooling_load_mw=cooling_load_mw,
        include_scr=include_scr,
        include_oxicat=include_oxicat,
        noise_limit_db=noise_limit_db,
        distance_to_property_m=distance_to_property_m,
        distance_to_residence_m=distance_to_residence_m,
        acoustic_treatment=acoustic_treatment,
        enable_phasing=enable_phasing,
        n_phases=n_phases,
        months_between_phases=months_between_phases,
        enable_footprint_limit=enable_footprint_limit,
        max_area_m2=max_area_m2,
        region=region,
        unit_system=unit_sys,
        # Protection limits (P08 Fix 4)
        voltage_sag_limit_pct=voltage_sag_limit_pct,
        freq_nadir_limit_hz=freq_nadir_limit_hz,
        freq_rocof_limit_hz_s=freq_rocof_limit_hz_s,
        # Fleet Maintenance (P12)
        max_maintenance_units=max_maintenance_units,
        selected_fleet_config_maint=st.session_state.get('fleet_maint_config_sel', 'B'),
        # CAPEX BOS adders (P08 Fix 6)
        bos_pct=bos_pct,
        civil_pct=civil_pct,
        fuel_system_pct=fuel_system_pct,
        epc_pct=epc_pct,
        contingency_pct=contingency_pct,
    )

    # ── Proposal Information (commercial fields for DOCX generation) ──
    if ENABLE_PROPOSAL_GEN:
        with st.sidebar.expander("📄 Proposal Information", expanded=False):
            st.markdown("**Cover & Identity**")
            st.text_input("CAT Division",
                key="prop_cat_division",
                value=st.session_state.get("prop_cat_division", PROPOSAL_DEFAULTS["cat_division"]))
            st.selectbox("Proposal Type",
                options=PROPOSAL_TYPE_OPTIONS,
                key="prop_proposal_type",
                index=PROPOSAL_TYPE_OPTIONS.index(
                    st.session_state.get("prop_proposal_type", PROPOSAL_DEFAULTS["proposal_type"])))
            st.text_input("Document Version",
                key="prop_doc_version",
                value=st.session_state.get("prop_doc_version", PROPOSAL_DEFAULTS["doc_version"]))
            st.text_input("BDM Name",
                key="prop_bdm_name",
                value=st.session_state.get("prop_bdm_name", PROPOSAL_DEFAULTS["bdm_name"]))
            st.text_input("BDM Email",
                key="prop_bdm_email",
                value=st.session_state.get("prop_bdm_email", PROPOSAL_DEFAULTS["bdm_email"]))

            st.markdown("**Commercial**")
            st.text_input("Authorized CAT Dealer",
                key="prop_dealer_name",
                value=st.session_state.get("prop_dealer_name", PROPOSAL_DEFAULTS["dealer_name"]))
            st.selectbox("Incoterm",
                options=INCOTERM_OPTIONS,
                key="prop_incoterm",
                index=INCOTERM_OPTIONS.index(
                    st.session_state.get("prop_incoterm", PROPOSAL_DEFAULTS["incoterm"])))
            st.selectbox("Delivery Destination",
                options=DELIVERY_DESTINATION_OPTIONS,
                key="prop_delivery_destination",
                index=DELIVERY_DESTINATION_OPTIONS.index(
                    st.session_state.get("prop_delivery_destination",
                                         PROPOSAL_DEFAULTS["delivery_destination"])))
            st.text_input("Estimated Delivery",
                placeholder="e.g. Q3 2026 (~18 months ARO)",
                key="prop_delivery_date_est",
                value=st.session_state.get("prop_delivery_date_est",
                                            PROPOSAL_DEFAULTS["delivery_date_est"]))
            st.text_input("Proposal Validity",
                key="prop_proposal_validity",
                value=st.session_state.get("prop_proposal_validity",
                                            PROPOSAL_DEFAULTS["proposal_validity"]))

            st.markdown("**Payment Terms (%)**")
            col1, col2 = st.columns(2)
            with col1:
                st.number_input("Down", 0, 100, key="prop_payment_down",
                    value=int(st.session_state.get("prop_payment_down",
                                                    PROPOSAL_DEFAULTS["payment_pct_down"])))
                st.number_input("At SOL", 0, 100, key="prop_payment_sol",
                    value=int(st.session_state.get("prop_payment_sol",
                                                    PROPOSAL_DEFAULTS["payment_pct_sol"])))
            with col2:
                st.number_input("30 days PO", 0, 100, key="prop_payment_30d",
                    value=int(st.session_state.get("prop_payment_30d",
                                                    PROPOSAL_DEFAULTS["payment_pct_30d"])))
                st.number_input("At RTS", 0, 100, key="prop_payment_rts",
                    value=int(st.session_state.get("prop_payment_rts",
                                                    PROPOSAL_DEFAULTS["payment_pct_rts"])))

            st.markdown("**Offer Scope**")
            st.checkbox("Genset", key="prop_offer_genset",
                value=st.session_state.get("prop_offer_genset",
                                            PROPOSAL_DEFAULTS["offer_type_genset"]))
            st.checkbox("Switchgear", key="prop_offer_switchgear",
                value=st.session_state.get("prop_offer_switchgear",
                                            PROPOSAL_DEFAULTS["offer_type_switchgear"]))
            st.checkbox("Solutions", key="prop_offer_solutions",
                value=st.session_state.get("prop_offer_solutions",
                                            PROPOSAL_DEFAULTS["offer_type_solutions"]))
            st.checkbox("Hybrid", key="prop_offer_hybrid",
                value=st.session_state.get("prop_offer_hybrid",
                                            PROPOSAL_DEFAULTS["offer_type_hybrid"]))

            st.markdown("**Post-sale Services**")
            st.checkbox("Include CVA overview in proposal",
                key="prop_include_cva",
                value=st.session_state.get("prop_include_cva", PROPOSAL_DEFAULTS["include_cva"]))
            st.checkbox("Include ESC overview in proposal",
                key="prop_include_esc",
                value=st.session_state.get("prop_include_esc", PROPOSAL_DEFAULTS["include_esc"]))

            st.markdown("**Notes / Clarifications**")
            st.text_area("Proposal notes (§5)",
                key="prop_notes",
                height=80,
                value=st.session_state.get("prop_notes", PROPOSAL_DEFAULTS["proposal_notes"]))

    return inputs_dict, benchmark_price


# =============================================================================
# HELPERS
# =============================================================================
def _fleet_size_label(r) -> str:
    """Format fleet size for pod architecture or legacy N+reserve."""
    if hasattr(r, 'n_pods') and hasattr(r, 'n_per_pod') and r.n_pods > 0:
        return f"{r.n_pods}pods × {r.n_per_pod} = {r.n_total}"
    return f"{r.n_running}+{r.n_reserve} = {r.n_total}"


# =============================================================================
# EXECUTIVE SUMMARY (before tabs)
# =============================================================================
def render_executive_summary(r, benchmark_price: float):
    """Render headline KPIs and LCOE verdict above the tabs."""

    st.title(f":zap: Sizing Results -- {r.selected_gen} | {r.p_it:.0f} MW IT")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total DC Load", f"{r.p_total_dc:.1f} MW")
    c2.metric("Fleet Size", _fleet_size_label(r))
    c3.metric("LCOE", f"${r.lcoe:.4f}/kWh")
    c4.metric("Availability", f"{r.system_availability * 100:.3f}%")
    c5.metric("BESS Power", f"{r.bess_power_mw:.2f} MW")
    c6.metric("Payback", f"{r.simple_payback_years:.1f} yr")

    # LCOE verdict
    if r.lcoe < benchmark_price:
        savings_pct = (1.0 - r.lcoe / benchmark_price) * 100.0
        st.success(
            f":white_check_mark: LCOE ${r.lcoe:.4f}/kWh is **{savings_pct:.1f}% below** "
            f"grid benchmark ${benchmark_price:.4f}/kWh. Off-grid gas generation is cost-competitive."
        )
    elif r.lcoe > benchmark_price:
        premium_pct = (r.lcoe / benchmark_price - 1.0) * 100.0
        st.warning(
            f":warning: LCOE ${r.lcoe:.4f}/kWh is **{premium_pct:.1f}% above** "
            f"grid benchmark ${benchmark_price:.4f}/kWh. Review LCOE recommender for optimization."
        )
    else:
        st.info(f"LCOE matches grid benchmark at ${r.lcoe:.4f}/kWh.")

    st.divider()


# =============================================================================
# TAB 1: SUMMARY
# =============================================================================
def render_summary_tab(r):
    """Top-level metrics, key results table, and design scorecard."""

    # Methane warning
    if r.methane_warning:
        st.warning(f":warning: {r.methane_warning}")

    # Headline metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total DC Load", f"{r.p_total_dc:.1f} MW")
    c2.metric("Fleet Size", _fleet_size_label(r))
    c3.metric("LCOE", f"${r.lcoe:.4f}/kWh")
    c4.metric("Availability", f"{r.system_availability * 100:.3f}%")

    st.divider()

    # Fleet Configuration Details — 2-column layout
    st.subheader("Fleet Configuration Details")

    col_specs, col_ops = st.columns(2)
    with col_specs:
        st.markdown("**Generator Specifications**")
        st.write(f"- Model: **{r.selected_gen}**")
        st.write(f"- ISO Rating: {r.unit_iso_cap:.2f} MW")
        st.write(f"- Site Rating: {r.unit_site_cap:.2f} MW")
        st.write(f"- Derate Factor: {r.derate_factor:.4f}")
        st.write(f"- Efficiency (ISO): {r.fleet_efficiency * 100:.1f}%")
        st.write(f"- Voltage: {r.rec_voltage_kv:.1f} kV")
        st.write(f"- Frequency: {r.freq_hz} Hz")

    with col_ops:
        st.markdown("**Operating Parameters**")
        st.write(f"- Running Units: **{r.n_running}**")
        st.write(f"- Reserve Units: **{r.n_reserve}**")
        st.write(f"- Total Fleet: **{r.n_total}**")
        st.write(f"- Installed Capacity: {r.installed_cap:.1f} MW")
        st.write(f"- Load per Unit: {r.load_per_unit_pct:.1f}%")
        st.write(f"- BESS Power: {r.bess_power_mw:.2f} MW")
        st.write(f"- BESS Energy: {r.bess_energy_mwh:.2f} MWh")

    # ---- Design Validation Scorecard ----
    if r.design_scorecard:
        st.divider()
        st.subheader("Design Validation Scorecard")

        # Render as card grid (2 rows of 4)
        checks = r.design_scorecard
        for row_start in range(0, len(checks), 4):
            row_checks = checks[row_start:row_start + 4]
            cols = st.columns(len(row_checks))
            for col, check in zip(cols, row_checks):
                passed_flag = check.get('passed', False)
                icon = "\u2705" if passed_flag else "\u274c"
                border_color = "#27AE60" if passed_flag else "#E74C3C"
                with col:
                    st.markdown(
                        f"""<div style="border:2px solid {border_color}; border-radius:8px;
                        padding:12px; text-align:center; height:140px;">
                        <div style="font-size:24px;">{icon}</div>
                        <div style="font-weight:bold; font-size:13px; margin:4px 0;">{check.get('check', '')}</div>
                        <div style="font-size:15px; color:{border_color};">{check.get('actual', '')}</div>
                        <div style="font-size:11px; color:#888;">Req: {check.get('requirement', '')}</div>
                        </div>""",
                        unsafe_allow_html=True,
                    )

        # Count pass/fail
        passed = sum(1 for c in checks if c.get('passed', False))
        total = len(checks)
        if passed == total:
            st.success(f"All {total} design checks passed.")
        else:
            st.warning(f"{passed}/{total} design checks passed. Review items marked with \u274c.")

        # Fix G — SR vs physical requirement (P04)
        if hasattr(r, 'sr_required_mw'):
            sr_available = r.spinning_from_gens + r.spinning_from_bess
            sr_ok = sr_available >= r.sr_required_mw
            if not sr_ok:
                st.error(
                    f"\u274c Spinning reserve insufficient: {sr_available:.1f} MW available "
                    f"< {r.sr_required_mw:.1f} MW required "
                    f"(dominant: {r.sr_dominant_contingency.replace('_', ' ')} event)."
                )


# =============================================================================
# TAB 2: RELIABILITY
# =============================================================================
def render_reliability_tab(r):
    """Spinning reserve visualization and reliability configuration comparison."""

    # ---- Pod Architecture (if applicable) ----
    if hasattr(r, 'n_pods') and r.n_pods > 0:
        st.subheader("Pod Architecture")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Number of Pods",        f"{r.n_pods}")
        c2.metric("Generators / Pod",      f"{r.n_per_pod}")
        c3.metric("Normal Loading",        f"{r.loading_normal_pct:.1f}%")
        c4.metric("Contingency Loading",   f"{r.loading_contingency_pct:.1f}%")

        cap_contingency = getattr(r, 'cap_contingency', (r.n_pods - 1) * r.n_per_pod * r.unit_site_cap)
        st.caption(
            f"All {r.n_total} generators operate simultaneously across {r.n_pods} pods. "
            f"**N+1 pod redundancy:** loss of any single pod ({r.n_per_pod} gens, "
            f"{r.n_per_pod * r.unit_site_cap:.1f} MW) leaves {cap_contingency:.1f} MW "
            f"available at {r.loading_contingency_pct:.1f}% loading. "
            f"Normal loading {r.loading_normal_pct:.1f}% ≤ prime/standby ratio — "
            f"thermal margin maintained in all operating conditions."
        )
        st.divider()

    # ---- Spinning Reserve Distribution ----
    st.subheader("Load Distribution per Running Unit")

    load_per_unit_mw = r.unit_site_cap * (r.load_per_unit_pct / 100)
    headroom_per_unit_mw = r.unit_site_cap - load_per_unit_mw
    n_show = min(r.n_running, 10)
    bar_labels = [f"Gen {i+1}" for i in range(n_show)]

    fig_dist = go.Figure()
    fig_dist.add_trace(go.Bar(
        name="Actual Load",
        x=bar_labels, y=[load_per_unit_mw] * n_show,
        marker_color="#1f77b4",
        text=[f"{r.load_per_unit_pct:.0f}%"] * n_show,
        textposition="inside",
    ))
    fig_dist.add_trace(go.Bar(
        name="Spinning Reserve (Headroom)",
        x=bar_labels, y=[headroom_per_unit_mw] * n_show,
        marker_color="#90EE90",
        text=[f"{100 - r.load_per_unit_pct:.0f}%"] * n_show,
        textposition="inside",
    ))

    # BESS bar (if spinning from BESS > 0)
    selected_cfg = next((c for c in r.reliability_configs if c.name == r.selected_config_name), None)
    bess_spin = selected_cfg.spinning_from_bess if selected_cfg else 0
    if bess_spin > 0:
        fig_dist.add_trace(go.Bar(
            name="BESS Reserve",
            x=["BESS"], y=[bess_spin],
            marker_color="#FFD700",
            text=[f"{bess_spin:.1f} MW"],
            textposition="inside",
        ))

    fig_dist.add_hline(
        y=r.unit_site_cap, line_dash="dash", line_color=COLOR_DANGER,
        annotation_text=f"Unit Capacity: {r.unit_site_cap:.1f} MW",
    )
    suffix = f" (showing {n_show} of {r.n_running})" if r.n_running > 10 else ""
    fig_dist.update_layout(
        barmode="stack",
        yaxis_title="Power (MW)",
        height=400,
        title=f"Load Distribution Across {r.n_running} Running Units{suffix}",
    )
    st.plotly_chart(fig_dist, use_container_width=True)

    # ── Maintenance-Aware Fleet Configurations (P12) ──
    maint_n = getattr(r, 'max_maintenance_units', 0)
    maint_configs = getattr(r, 'fleet_maintenance_configs', {}) or {}

    if maint_n > 0 and maint_configs:
        st.divider()
        st.subheader("Maintenance-Aware Fleet Configurations")
        st.caption(
            f"The following configurations satisfy both N+1 pod redundancy AND "
            f"the combined contingency with **{maint_n} generator(s) in scheduled "
            f"maintenance**. Select one to use for CAPEX calculation."
        )

        # Build comparison table
        config_labels = {
            'A': ('Distributed', 'More pods · same or fewer gens · min CAPEX gen+inst'),
            'B': ('Conservative', 'Same pod topology · add gens · min electrical changes'),
            'C': ('Balanced', '+1 pod · minimal gen increase · moderate margin'),
        }

        # Get base values for delta computation
        base_gens   = r.n_total
        base_pods   = r.n_pods
        base_trafos = r.n_pods // 2

        cfg_data = []
        for key in ['A', 'B', 'C']:
            cfg = maint_configs.get(key)
            if not cfg:
                continue
            dn = cfg['n_total'] - base_gens
            dp = cfg['n_pods']  - base_pods
            dt = (cfg['n_pods'] // 2) - base_trafos
            lbl, desc = config_labels.get(key, (key, ''))
            cfg_data.append({
                'Key': key,
                'Config': f"{key} — {lbl}",
                'Architecture': f"{cfg['n_pods']} pods × {cfg['n_per_pod']} gens = {cfg['n_total']}",
                'Combined cap': f"{cfg['cap_combined']:.1f} MW",
                'Margin': f"{cfg['maintenance_margin_mw']:+.1f} MW",
                'Loading': f"{cfg['loading_normal_pct']:.1f}%",
                'Δ Pods': f"{dp:+d}",
                'Δ Gens': f"{dn:+d}",
                'Δ Trafos': f"{dt:+d}",
                'Description': desc,
            })

        if cfg_data:
            import pandas as pd
            df = pd.DataFrame(cfg_data).drop(columns=['Key', 'Description'])
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Descriptions
            for row in cfg_data:
                st.caption(f"**Config {row['Key']}:** {row['Description']}")

            # Selector
            current_sel = getattr(r, 'selected_fleet_config_maint', 'B')
            available_keys = [d['Key'] for d in cfg_data]
            sel = st.radio(
                "Select configuration for CAPEX calculation",
                options=available_keys,
                index=available_keys.index(current_sel) if current_sel in available_keys else 0,
                horizontal=True,
                key='fleet_maint_config_sel',
                help="The selected configuration's fleet size drives the generator and installation CAPEX.",
            )

            # Store selection in session state for next run
            st.session_state['fleet_maint_config_sel'] = sel

            # Show selected config details
            sel_cfg = maint_configs.get(sel)
            if sel_cfg:
                st.info(
                    f"**Selected: Config {sel}** — "
                    f"{sel_cfg['n_pods']} pods × {sel_cfg['n_per_pod']} gens = "
                    f"{sel_cfg['n_total']} generators · "
                    f"{sel_cfg['n_total'] * r.unit_site_cap:.1f} MW installed · "
                    f"Combined contingency: {sel_cfg['cap_combined']:.1f} MW "
                    f"({sel_cfg['maintenance_margin_mw']:+.1f} MW margin). "
                    f"Re-run sizing to apply this configuration to CAPEX."
                )

    elif maint_n == 0:
        st.caption(
            "ℹ️ Set 'Max generators in maintenance' > 0 in the sidebar to generate "
            "maintenance-aware fleet configurations."
        )

    # Pod Architecture — rendered at top of tab (P08), removed duplicate here
    if False:
        st.caption(
            f"Redundancy: N+1 pod \u2014 loss of any single pod ({r.n_per_pod} gens, "
            f"{r.n_per_pod * r.unit_site_cap:.1f} MW) leaves "
            f"{r.cap_contingency:.1f} MW available at "
            f"{r.loading_contingency_pct:.1f}% loading."
        )

    st.divider()

    # ---- Reliability configs comparison ----
    st.subheader("Reliability Configurations")

    # Per-config CAPEX estimation (gen cost scales with fleet size)
    gen_cost_per_unit = 0
    if r.n_total > 0 and r.capex_breakdown:
        gen_plus_install = r.capex_breakdown.get('generators', 0) + r.capex_breakdown.get('installation', 0)
        gen_cost_per_unit = gen_plus_install / r.n_total  # $/unit

    configs_data = []
    for cfg in r.reliability_configs:
        # Estimate CAPEX: gen+install scales with n_total, BESS scales with MWh
        cfg_gen_cost = cfg.n_total * gen_cost_per_unit
        cfg_bess_cost = (cfg.bess_mwh / r.bess_energy_mwh * r.capex_breakdown.get('bess', 0)) if r.bess_energy_mwh > 0 else 0
        cfg_capex_m = (cfg_gen_cost + cfg_bess_cost) / 1e6

        configs_data.append({
            "Configuration": cfg.name,
            "Fleet": f"{r.n_pods}p×{r.n_per_pod}" if hasattr(r, 'n_pods') and r.n_pods > 0
                     else f"{cfg.n_running}+{cfg.n_reserve}",
            "Total": cfg.n_total,
            "BESS (MW/MWh)": f"{cfg.bess_mw:.0f}/{cfg.bess_mwh:.0f}" if cfg.bess_mw > 0 else "None",
            "BESS Credit": f"{cfg.bess_credit:.1f}",
            "Spin. BESS": f"{cfg.spinning_from_bess:.1f} MW" if cfg.spinning_from_bess > 0 else "-",
            "Load (%)": f"{cfg.load_pct:.1f}",
            "Eff. (%)": f"{cfg.efficiency * 100:.1f}",
            "Avail. (%)": f"{cfg.availability * 100:.4f}",
            "CAPEX ($M)": f"${cfg_capex_m:.1f}",
        })

    df_configs = pd.DataFrame(configs_data)

    def _highlight_selected(row):
        if row["Configuration"] == r.selected_config_name:
            return ["background-color: #FFF3CD"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df_configs.style.apply(_highlight_selected, axis=1),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"Selected: **{r.selected_config_name}**")


# =============================================================================
# TAB 3: BESS
# =============================================================================
def render_bess_tab(r):
    """BESS sizing breakdown and function checklist."""

    if not r.use_bess:
        st.info("BESS is disabled for this configuration.")
        return

    st.subheader("BESS Sizing Breakdown")

    c1, c2 = st.columns(2)
    c1.metric("Total Power", f"{r.bess_power_mw:.2f} MW")
    c2.metric("Total Energy", f"{r.bess_energy_mwh:.2f} MWh")

    st.markdown(f"**Strategy:** {r.bess_strategy}")

    # Breakdown bar chart
    breakdown = r.bess_breakdown
    if breakdown:
        components = []
        power_vals = []
        energy_vals = []

        for key, val in breakdown.items():
            label = key.replace("_", " ").title()
            if isinstance(val, dict):
                components.append(label)
                power_vals.append(val.get("power_mw", 0))
                energy_vals.append(val.get("energy_mwh", 0))
            elif isinstance(val, (int, float)):
                components.append(label)
                power_vals.append(val)
                energy_vals.append(0)

        if components:
            fig = go.Figure(data=[
                go.Bar(name="Power (MW)", x=components, y=power_vals,
                       marker_color=COLOR_PRIMARY),
                go.Bar(name="Energy (MWh)", x=components, y=energy_vals,
                       marker_color=COLOR_SECONDARY),
            ])
            fig.update_layout(
                barmode="group",
                yaxis_title="Value",
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)

    # Spinning reserve from BESS
    st.divider()
    st.subheader("Spinning Reserve Contribution")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Spinning Reserve", f"{r.spinning_reserve_mw:.2f} MW")
    c2.metric("From Generators", f"{r.spinning_from_gens:.2f} MW")
    c3.metric("From BESS", f"{r.spinning_from_bess:.2f} MW")

    # Fix I — BESS SR Credit Status (P04)
    if r.use_bess and hasattr(r, 'bess_sr_credit_valid'):
        if r.bess_sr_credit_valid:
            st.success(
                f"\u2705 BESS SR credit validated \u2014 "
                f"{r.bess_sr_available_mws:.0f} MWs available "
                f"\u2265 {r.bess_sr_required_mws:.0f} MWs required"
            )
        else:
            reasons = []
            if not r.bess_sr_response_ok:
                reasons.append("response time > 10 s")
            if not r.bess_sr_energy_ok:
                reasons.append(
                    f"energy insufficient "
                    f"({r.bess_sr_available_mws:.0f} MWs < {r.bess_sr_required_mws:.0f} MWs)"
                )
            st.error(f"\u274c BESS SR credit invalidated: {'; '.join(reasons)}. "
                     f"spinning_from_bess forced to 0 MW.")

    # BESS Function Checklist
    st.divider()
    st.subheader("BESS Function Checklist")

    bess_functions = [
        ("Transient Response / Load Step Support", True),
        ("Spinning Reserve Contribution", r.spinning_from_bess > 0),
        ("Black Start Capability", hasattr(r, 'bess_breakdown') and
         isinstance(r.bess_breakdown, dict) and
         'black_start' in r.bess_breakdown),
        ("Peak Shaving", r.bess_strategy in ("Hybrid (Balanced)", "Reliability Priority")),
        ("Frequency Regulation Support", r.bess_power_mw > 0),
        ("Reliability Credit (N+X reduction)", any(
            cfg.bess_credit > 0 for cfg in r.reliability_configs
        ) if r.reliability_configs else False),
    ]

    for func_name, func_active in bess_functions:
        icon = "\u2705" if func_active else "\u2b1c"
        st.markdown(f"{icon} {func_name}")


# =============================================================================
# TAB 4: ELECTRICAL
# =============================================================================
def render_electrical_tab(r):
    """Voltage, efficiency, heat rate, frequency screening, and stability."""

    st.subheader("Electrical System")

    c1, c2, c3 = st.columns(3)
    c1.metric("Recommended Voltage", f"{r.rec_voltage_kv:.1f} kV")
    c2.metric("Frequency", f"{r.freq_hz} Hz")
    c3.metric("Net Efficiency", f"{r.net_efficiency * 100:.1f}%")

    st.divider()

    # ---- Net Efficiency & Heat Rate ----
    st.subheader("Efficiency & Heat Rate")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Gross Efficiency", f"{r.gross_efficiency * 100:.1f}%" if r.gross_efficiency else "N/A")
    c2.metric("Net Efficiency", f"{r.net_efficiency * 100:.1f}%")
    c3.metric("Aux Load", f"{r.aux_load_pct:.1f}%")
    c4.metric("Dist Losses", f"{st.session_state.get('_dist_loss_pct', 1.5):.1f}%")

    st.markdown("**Heat Rates**")
    hr_data = {
        "Basis": ["LHV (BTU/kWh)", "HHV (BTU/kWh)", "LHV (MJ/kWh)", "HHV (MJ/kWh)"],
        "Value": [
            f"{r.heat_rate_lhv_btu:,.0f}" if r.heat_rate_lhv_btu else "N/A",
            f"{r.heat_rate_hhv_btu:,.0f}" if r.heat_rate_hhv_btu else "N/A",
            f"{r.heat_rate_lhv_mj:.2f}" if r.heat_rate_lhv_mj else "N/A",
            f"{r.heat_rate_hhv_mj:.2f}" if r.heat_rate_hhv_mj else "N/A",
        ],
    }
    st.table(pd.DataFrame(hr_data).set_index("Basis"))

    st.divider()

    # ---- Frequency Screening ----
    if r.frequency_screening:
        st.subheader("Frequency Screening")
        fs = r.frequency_screening
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Frequency Nadir", f"{_safe_get(fs, 'nadir_hz', 0):.2f} Hz")
        c2.metric("RoCoF", f"{_safe_get(fs, 'rocof_hz_s', 0):.3f} Hz/s")
        h_mech  = _safe_get(fs, 'H_per_unit', 0)   # mechanical H from generator
        h_bess  = _safe_get(fs, 'H_bess', 0)        # virtual inertia from BESS
        h_total = _safe_get(fs, 'H_total', 0)       # total system H
        c3.metric("H mech (gen)", f"{h_mech:.2f} s")
        c4.metric("H virtual (BESS)", f"{h_bess:.2f} s")
        c5.metric("H total (system)", f"{h_total:.2f} s")
        if h_mech > 2.0:
            st.warning(
                f"⚠️ Generator mechanical inertia H = {h_mech:.2f} s is higher than "
                f"typical for reciprocating gas engines (0.5–1.5 s). "
                f"Verify with manufacturer data."
            )
        if h_bess > 0:
            st.info(
                f"ℹ️ BESS virtual inertia contribution: {h_bess:.2f} s "
                f"(grid-forming inverter emulation). "
                f"Total system inertia H = {h_total:.2f} s."
            )

        fc1, fc2 = st.columns(2)
        nadir_ok = fs.get('nadir_ok', True)
        rocof_ok = fs.get('rocof_ok', True)
        if nadir_ok:
            fc1.success(f"Nadir OK (limit: {_safe_get(fs, 'nadir_limit', 0)} Hz)")
        else:
            fc1.error(f"Nadir FAIL (limit: {_safe_get(fs, 'nadir_limit', 0)} Hz)")
        if rocof_ok:
            fc2.success(f"RoCoF OK (limit: {_safe_get(fs, 'rocof_limit', 0)} Hz/s)")
        else:
            fc2.error(f"RoCoF FAIL (limit: {_safe_get(fs, 'rocof_limit', 0)} Hz/s)")

        if fs.get('notes'):
            st.info(fs['notes'])

    st.divider()

    # ---- Transient Stability ----
    st.subheader("Transient Stability")
    c1, c2 = st.columns(2)

    if r.stability_ok:
        c1.success(":white_check_mark: Stable")
    else:
        c1.error(":x: Unstable")

    c2.metric("Voltage Sag", f"{r.voltage_sag:.1f}%")

    # Fix J — Transient Stability Disclaimer (P04)
    st.caption(
        "\u26a0\ufe0f Preliminary estimate only. Voltage sag calculated from active power balance. "
        "A dynamic stability study (EMT/PSCAD or PSS/E) is required before detailed design."
    )

    st.divider()

    # ---- Spinning Reserve Detail (Fix H — P04) ----
    st.subheader("Spinning Reserve Detail")
    if hasattr(r, 'sr_required_mw'):
        data = {
            "Component": [
                "SR required \u2014 physical",
                "  \u21b3 load step contingency",
                "  \u21b3 N-1 contingency",
                "SR from generators",
                "SR from BESS (validated)",
                "SR total available",
                "Generator headroom",
            ],
            "MW": [
                f"{r.sr_required_mw:.2f}",
                f"{r.load_step_mw:.2f}",
                f"{r.n1_mw:.2f}",
                f"{r.spinning_from_gens:.2f}",
                f"{r.spinning_from_bess:.2f}",
                f"{r.spinning_from_gens + r.spinning_from_bess:.2f}",
                f"{r.headroom_mw:.2f}",
            ],
        }
    else:
        # Fallback for old result objects
        data = {
            "Component": ["Spinning Reserve", "From Generators", "From BESS", "Headroom"],
            "MW": [f"{r.spinning_reserve_mw:.2f}", f"{r.spinning_from_gens:.2f}",
                   f"{r.spinning_from_bess:.2f}", f"{r.headroom_mw:.2f}"],
        }
    st.table(pd.DataFrame(data).set_index("Component"))

    # ---- Electrical Sizing (P08) ----
    if hasattr(r, 'electrical_sizing'):
        e = r.electrical_sizing
        st.divider()
        st.subheader("MV Generator Bus — 13.8 kV")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Normal Current",      f"{e['mv_I_normal_a']:.0f} A")
        c2.metric("Contingency Current", f"{e['mv_I_contingency_a']:.0f} A")
        c3.metric("Bus Rating",          f"{e['mv_bus_rating_a']:,} A")
        c4.metric(f"{e['xfmr_count']} Transformers", f"{e['xfmr_mva_selected']:.1f} MVA each")
        st.caption(
            f"Bus sized for N+1 pod contingency (both pods routing to one transformer). "
            f"Transformer {e['xfmr_voltage_ratio']} — normal loading: "
            f"{e['xfmr_loading_normal_pct']:.0f}% (~50% expected — contingency is the design basis)."
        )

        if 'mv_isc' in e:
            mi = e['mv_isc']
            st.markdown("**Short circuit — 13.8 kV bus (ring bus topology)**")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Local contribution",   f"{mi['I_local_ka']:.1f} kA")
            c2.metric("Remote (ring infeed)",  f"{mi['I_remote_ka']:.1f} kA")
            c3.metric("ISC asymmetric",        f"{mi['I_isc_asym_ka']:.1f} kA")
            c4.metric("Gen breaker required",  f"{mi['mv_breaker_ka']} kA (ANSI C37)")
            st.caption(
                f"Ring bus: fault at 13.8 kV bus receives own generators "
                f"({mi['I_local_ka']:.1f} kA direct) plus all other pods "
                f"through two transformers in series "
                f"({mi['I_remote_ka']:.1f} kA). Remote contribution dominates."
            )
            if mi['mv_breaker_ka'] >= 63:
                st.warning(
                    f"⚠️ ISC asymmetric = {mi['I_isc_asym_ka']:.1f} kA requires "
                    f"{mi['mv_breaker_ka']} kA switchgear at 13.8 kV. "
                    "Verify availability with switchgear manufacturer. "
                    "For plants > 150 MW consider current-limiting reactors "
                    "or split-bus topology to reduce fault levels."
                )

        st.divider()
        st.subheader(f"HV Collector Bus — {e['hv_voltage_kv']:.1f} kV")

        levels_data = []
        for V, d in e['hv_all_levels'].items():
            levels_data.append({
                "Voltage": f"{V:.1f} kV",
                "I normal": f"{d['I_normal_a']:.0f} A",
                "Bus rating": f"{d['bus_rating_a']:,} A",
                "Ampacity": "✅ OK" if d['bus_ok'] else "❌ EXCEEDS",
                "ISC sym": f"{d['I_isc_sym_ka']:.1f} kA",
                "ISC asym": f"{d['I_isc_asym_ka']:.1f} kA",
                "Breaker": f"{d['breaker_ka']} kA",
                "": "← SELECTED" if V == e['hv_voltage_kv'] else "",
            })
        st.table(pd.DataFrame(levels_data).set_index("Voltage"))

        if e['hv_voltage_kv'] > 34.5:
            i_34 = e['hv_all_levels'][34.5]['I_normal_a']
            st.info(
                f"ℹ️ 34.5 kV bus would require {i_34:.0f} A — exceeds 3,000 A "
                f"practical limit. Escalated to {e['hv_voltage_kv']:.1f} kV automatically."
            )

        st.divider()
        st.subheader("Short Circuit Analysis")
        c1, c2, c3 = st.columns(3)
        c1.metric("ISC Symmetric",    f"{e['isc_sym_ka']:.1f} kA")
        c2.metric("ISC Asymmetric",   f"{e['isc_asym_ka']:.1f} kA")
        c3.metric("Breaker Required", f"{e['hv_breaker_ka']} kA (ANSI C37)")
        st.caption(
            f"Generator X''d contributes {e['isc_z_gen_pct']:.0f}% of fault impedance "
            f"(transformer: {e['isc_z_trafo_pct']:.0f}%). In off-grid prime power systems, "
            f"generators self-limit fault current — ISC is typically 9–20 kA at 34.5 kV, "
            f"always within 25 kA standard breakers."
        )
        st.warning(
            "⚠️ **Engineering disclaimer:** ISC values are preliminary estimates for "
            "conceptual design and equipment pre-selection only. Assumptions: "
            f"Z_trafo={e['assumptions']['z_trafo_pu']*100:.2f}% (ANSI typical 5.5–7.5%), "
            f"X''d={e['assumptions']['xd_subtrans_pu']*100:.0f}% per unit, "
            f"cable impedance {e['assumptions']['cable_impedance']}. "
            "A formal short-circuit study (IEC 60909 or ANSI/IEEE C37) is required "
            "before equipment purchase and protection relay settings."
        )


# =============================================================================
# TAB 5: LOAD PROFILE
# =============================================================================
def render_load_profile_tab(r):
    """Synthetic 8760h annual load profile and duration curve."""

    st.subheader("Annual Load Profile (Synthetic 8760h)")

    hours = np.arange(8760)
    base = r.p_total_avg if r.p_total_avg > 0 else r.p_total_dc * 0.9

    # Synthetic daily pattern (24h cycle) + seasonal + noise
    daily_pattern = 1.0 + 0.15 * np.sin(2.0 * np.pi * hours / 24.0 - np.pi / 2.0)
    seasonal = 1.0 + 0.05 * np.sin(2.0 * np.pi * hours / 8760.0)
    np.random.seed(42)
    noise = 1.0 + 0.02 * np.random.randn(8760)
    load_profile = base * daily_pattern * seasonal * noise
    load_profile = np.clip(load_profile, base * 0.70, r.p_total_peak)

    # Annual load profile chart
    fig_annual = go.Figure()
    fig_annual.add_trace(go.Scatter(
        x=list(hours), y=list(load_profile),
        mode="lines",
        name="Load Profile",
        line=dict(color=COLOR_PRIMARY, width=1),
        fill="tozeroy",
        fillcolor="rgba(255, 204, 0, 0.2)",
    ))
    fig_annual.add_hline(y=r.p_total_peak, line_dash="dash", line_color=COLOR_DANGER,
                         annotation_text=f"Peak: {r.p_total_peak:.1f} MW")
    fig_annual.add_hline(y=base, line_dash="dot", line_color=COLOR_SECONDARY,
                         annotation_text=f"Average: {base:.1f} MW")
    fig_annual.update_layout(
        xaxis_title="Hour of Year",
        yaxis_title="Load (MW)",
        height=400,
    )
    st.plotly_chart(fig_annual, use_container_width=True)

    st.divider()

    # Duration Curve — enriched with zones
    st.subheader("Load Duration Curve")
    sorted_load = np.sort(load_profile)[::-1]
    pct_time = np.linspace(0, 100, len(sorted_load))
    online_cap = r.n_running * r.unit_site_cap

    fig_dur = go.Figure()
    fig_dur.add_trace(go.Scatter(
        x=list(pct_time), y=list(sorted_load),
        mode="lines",
        name="DC Load",
        line=dict(color="#667eea", width=2),
        fill="tozeroy",
        fillcolor="rgba(102, 126, 234, 0.15)",
    ))

    # Zone: Spinning Reserve (green band above average load)
    fig_dur.add_hrect(
        y0=r.p_total_avg, y1=r.p_total_avg + r.spinning_reserve_mw,
        fillcolor="lightgreen", opacity=0.3,
        annotation_text=f"Spinning Reserve: {r.spinning_reserve_mw:.1f} MW",
        annotation_position="top left",
    )

    # Zone: BESS Peak Shaving (yellow, only if BESS and peak > online)
    if r.use_bess and r.p_total_peak > online_cap:
        fig_dur.add_hrect(
            y0=online_cap, y1=r.p_total_peak,
            fillcolor="yellow", opacity=0.2,
            annotation_text=f"BESS Peak Shaving ({r.bess_power_mw:.1f} MW)",
            annotation_position="top left",
        )

    # Reference lines
    fig_dur.add_hline(y=r.installed_cap, line_dash="dash", line_color=COLOR_DANGER,
                      annotation_text=f"Installed: {r.installed_cap:.1f} MW")
    fig_dur.add_hline(y=online_cap, line_dash="dashdot", line_color=COLOR_SUCCESS,
                      annotation_text=f"Online: {online_cap:.1f} MW")
    fig_dur.add_hline(y=r.p_total_avg, line_dash="dot", line_color="orange",
                      annotation_text=f"Average: {r.p_total_avg:.1f} MW")

    fig_dur.update_layout(
        xaxis_title="% of Time Exceeded",
        yaxis_title="Load (MW)",
        height=450,
    )
    st.plotly_chart(fig_dur, use_container_width=True)

    # Stats
    st.subheader("Load Statistics")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Peak Load", f"{r.p_total_peak:.1f} MW")
    c2.metric("Average Load", f"{base:.1f} MW")
    c3.metric("Min Load (est.)", f"{base * 0.70:.1f} MW")
    c4.metric("Capacity Factor", f"{r.capacity_factor:.2f}")


# =============================================================================
# TAB 6: ENVIRONMENTAL
# =============================================================================
def render_environmental_tab(r):
    """Emissions rates, compliance matrix, and aftertreatment recommendation."""

    st.subheader("Emissions Summary")

    emissions = r.emissions
    if emissions:
        # Raw annual totals
        nox_tpy = emissions.get('nox_tpy', 0)
        co_tpy = emissions.get('co_tpy', 0)
        co2_tpy = emissions.get('co2_tpy', 0)

        # Aftertreatment reductions
        ec = r.emissions_control if r.emissions_control else {}
        nox_red = _safe_get(ec, 'nox_reduction_pct', 0) / 100  # 0.90 when SCR active
        co_red = _safe_get(ec, 'co_reduction_pct', 0) / 100    # 0.80 when OxiCat active

        nox_after = nox_tpy * (1 - nox_red)
        co_after = co_tpy * (1 - co_red)
        co2_after = co2_tpy  # No aftertreatment for CO2

        em_data = {
            "Pollutant": ["NOx", "CO", "CO₂"],
            "Rate": [
                f"{emissions.get('nox_rate_g_kwh', 0):.3f} g/kWh",
                f"{emissions.get('co_rate_g_kwh', 0):.3f} g/kWh",
                f"{emissions.get('co2_rate_kg_mwh', 0):.1f} kg/MWh",
            ],
            "Annual Total": [
                f"{nox_tpy:.1f} tons/yr",
                f"{co_tpy:.1f} tons/yr",
                f"{co2_tpy:,.0f} tons/yr",
            ],
            "Annual Total (with Aftertreatment)": [
                f"{nox_after:.1f} tons/yr" if nox_red > 0 else "—",
                f"{co_after:.1f} tons/yr" if co_red > 0 else "—",
                "—",
            ],
        }
        st.table(pd.DataFrame(em_data).set_index("Pollutant"))

    st.divider()

    # ---- Emissions Compliance Matrix (quick view) ----
    if r.emissions_compliance:
        st.subheader("Emissions Compliance (Quick View)")
        compliance_data = []
        for item in r.emissions_compliance:
            icon = "\u2705" if item.get('compliant', True) else "\u274c"
            compliance_data.append({
                "Status": icon,
                "Regulation": item.get('regulation', ''),
                "Parameter": item.get('parameter', ''),
                "Limit": f"{item.get('limit', '')} {item.get('unit', '')}",
                "Actual": f"{item.get('actual', '')} {item.get('unit', '')}",
            })
        st.dataframe(pd.DataFrame(compliance_data), use_container_width=True, hide_index=True)

    st.divider()

    # ---- Emissions Control / Aftertreatment ----
    if r.emissions_control:
        st.subheader("Aftertreatment Recommendation")
        ec = r.emissions_control
        c1, c2 = st.columns(2)
        c1.metric("SCR CAPEX", f"${_safe_get(ec, 'scr_capex', 0):,.2f}")
        c2.metric("OxiCat CAPEX", f"${_safe_get(ec, 'oxicat_capex', 0):,.2f}")

        c3, c4, c5 = st.columns(3)
        c3.metric("Total Aftertreatment CAPEX", f"${_safe_get(ec, 'total_capex', 0):,.2f}")
        c4.metric("NOx Reduction", f"{_safe_get(ec, 'nox_reduction_pct', 0):.0f}%")
        c5.metric("CO Reduction", f"{_safe_get(ec, 'co_reduction_pct', 0):.0f}%")


# =============================================================================
# TAB 7: FINANCIAL
# =============================================================================
def render_financial_tab(r, benchmark_price: float):
    """LCOE, CAPEX breakdown, O&M, gas sensitivity, grid comparison, recommender."""

    st.subheader("Financial Summary")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("LCOE", f"${r.lcoe:.4f}/kWh")
    c2.metric("Total CAPEX", f"${r.total_capex:,.2f}")
    c3.metric("NPV", f"${r.npv:,.2f}")
    c4.metric("Payback", f"{r.simple_payback_years:.1f} years")

    st.divider()

    # ---- Annual Costs ----
    st.subheader("Annual Operating Costs")
    c1, c2 = st.columns(2)
    c1.metric("Annual Fuel Cost", f"${r.annual_fuel_cost / 1e6:.2f}M / yr")
    c2.metric("Annual O&M Cost", f"${r.annual_om_cost / 1e6:.2f}M / yr")

    st.divider()

    # ---- CAPEX Breakdown (editable) ----
    st.subheader("CAPEX Breakdown")
    if r.capex_breakdown:
        assumptions = r.capex_assumptions if r.capex_assumptions else {}
        capex_items = []
        for key, val in r.capex_breakdown.items():
            label = key.replace("_", " ").title()
            cost_m = round(float(val) / 1_000_000, 2) if val else 0.00
            capex_items.append({
                "Component": label,
                "Assumption": assumptions.get(key, ""),
                "Cost ($M)": cost_m,
            })

        df_capex = pd.DataFrame(capex_items)
        edited_capex = st.data_editor(
            df_capex,
            use_container_width=True,
            hide_index=True,
            disabled=["Component", "Assumption"],
            column_config={
                "Cost ($M)": st.column_config.NumberColumn(
                    format="$%.2fM",
                    min_value=0.0,
                    step=0.01,
                ),
            },
            num_rows="fixed",
            key="capex_editor",
        )
        capex_total = edited_capex["Cost ($M)"].sum() * 1_000_000
        st.metric("Total CAPEX", f"${capex_total / 1_000_000:,.2f}M")

    st.divider()

    # ---- O&M Breakdown Stacked Bar ----
    if r.om_breakdown:
        st.subheader("O&M Cost Breakdown")
        om = r.om_breakdown
        om_categories = []
        om_values = []
        om_colors = [COLOR_PRIMARY, COLOR_SECONDARY, COLOR_SUCCESS, COLOR_DANGER, COLOR_GREY]

        for key, val in om.items():
            label = key.replace("_", " ").title()
            om_categories.append(label)
            om_values.append(float(val) if val else 0.0)

        fig_om = go.Figure()
        for i, (cat, val) in enumerate(zip(om_categories, om_values)):
            color = om_colors[i % len(om_colors)]
            fig_om.add_trace(go.Bar(
                x=["Annual O&M"],
                y=[val],
                name=cat,
                marker_color=color,
                text=[f"${val:,.2f}"],
                textposition="inside",
            ))
        fig_om.update_layout(
            barmode="stack",
            yaxis_title="Cost ($/year)",
            height=400,
            showlegend=True,
        )
        st.plotly_chart(fig_om, use_container_width=True)

    st.divider()

    # ---- LCOE vs Grid ----
    st.subheader("LCOE vs Grid Benchmark")
    fig_bench = go.Figure()
    fig_bench.add_trace(go.Bar(
        y=["Gas Generation LCOE", "Grid Benchmark"],
        x=[r.lcoe, benchmark_price],
        orientation="h",
        marker_color=[COLOR_PRIMARY, COLOR_SECONDARY],
        text=[f"${r.lcoe:.4f}", f"${benchmark_price:.4f}"],
        textposition="outside",
    ))
    fig_bench.update_layout(
        xaxis_title="$/kWh",
        height=200,
        margin=dict(l=10, r=10, t=10, b=30),
    )
    st.plotly_chart(fig_bench, use_container_width=True)

    st.divider()

    # ---- Gas Price Sensitivity ----
    if r.gas_sensitivity and r.gas_sensitivity.get('prices'):
        st.subheader("Gas Price Sensitivity")
        gs = r.gas_sensitivity
        fig_gas = go.Figure()
        fig_gas.add_trace(go.Scatter(
            x=gs['prices'], y=gs['lcoes'],
            mode='lines+markers',
            name='LCOE',
            line=dict(color=COLOR_PRIMARY, width=2),
            marker=dict(size=6),
        ))
        fig_gas.add_hline(
            y=benchmark_price, line_dash='dash', line_color=COLOR_DANGER,
            annotation_text=f'Grid: ${benchmark_price:.3f}',
        )
        if gs.get('breakeven_price') is not None:
            fig_gas.add_vline(
                x=gs['breakeven_price'], line_dash='dot', line_color=COLOR_SECONDARY,
                annotation_text=f'Breakeven: ${gs["breakeven_price"]:.1f}/MMBtu',
            )
        fig_gas.update_layout(
            xaxis_title='Gas Price ($/MMBtu)',
            yaxis_title='LCOE ($/kWh)',
            height=400,
        )
        st.plotly_chart(fig_gas, use_container_width=True)

    st.divider()

    # ---- Off-Grid vs Grid 20-Year Cumulative ----
    if r.grid_comparison and r.grid_comparison.get('grid_cumulative'):
        st.subheader("Off-Grid vs Grid: 20-Year Cumulative Cost")
        gc = r.grid_comparison
        years = list(range(1, len(gc['grid_cumulative']) + 1))
        fig_grid = go.Figure()
        fig_grid.add_trace(go.Scatter(
            x=years,
            y=[v / 1e6 for v in gc['grid_cumulative']],
            name='Grid (Cumulative)',
            line=dict(color=COLOR_DANGER, width=2),
        ))
        fig_grid.add_trace(go.Scatter(
            x=years,
            y=[v / 1e6 for v in gc['gas_cumulative']],
            name='CAT Off-Grid (Cumulative)',
            line=dict(color=COLOR_PRIMARY, width=2),
        ))
        if gc.get('crossover_year'):
            fig_grid.add_vline(
                x=gc['crossover_year'], line_dash='dash', line_color=COLOR_SECONDARY,
                annotation_text=f'Payback Year {gc["crossover_year"]}',
            )
        fig_grid.update_layout(
            xaxis_title='Year',
            yaxis_title='Cumulative Cost ($M)',
            height=400,
        )
        st.plotly_chart(fig_grid, use_container_width=True)

        if gc.get('savings_20yr') is not None:
            savings_20yr = gc['savings_20yr']
            if savings_20yr > 0:
                st.success(f"20-Year Savings vs Grid: **${savings_20yr/1e6:,.1f}M**")
            else:
                st.warning(f"20-Year Premium vs Grid: **${abs(savings_20yr)/1e6:,.1f}M**")

    st.divider()

    # ---- LCOE Gap Recommender ----
    if r.lcoe_recommendations:
        st.subheader("LCOE Optimization Strategies")
        for rec in r.lcoe_recommendations:
            applicable = rec.get('applicable', True)
            icon = "\u2705" if applicable else "\u26aa"
            savings = rec.get('potential_savings_pct', 0)
            st.markdown(
                f"{icon} **{rec.get('strategy', '')}** "
                f"(~{savings:.1f}% savings) -- {rec.get('description', '')}"
            )


# =============================================================================
# TAB 8: CHP / TRI-GEN
# =============================================================================
def render_chp_tab(r):
    """CHP / Tri-Generation results."""

    if not r.chp_results:
        st.info("CHP / Tri-Generation is not enabled for this configuration.")
        return

    st.subheader("CHP / Tri-Generation Results")
    chp = r.chp_results

    c1, c2, c3 = st.columns(3)
    c1.metric("Waste Heat Available", f"{_safe_get(chp, 'waste_heat_mw', 0):.2f} MW")
    c2.metric("Recovered Heat", f"{_safe_get(chp, 'recovered_heat_mw', 0):.2f} MW")
    c3.metric("CHP Efficiency", f"{_safe_get(chp, 'chp_efficiency', 0) * 100:.1f}%")

    st.divider()

    c4, c5, c6 = st.columns(3)
    c4.metric("Absorption Chiller Cooling", f"{_safe_get(chp, 'cooling_from_absorption_mw', 0):.2f} MW")
    c5.metric("Cooling Coverage", f"{_safe_get(chp, 'cooling_coverage_pct', 0):.0f}%")
    c6.metric("CHP CAPEX", f"${_safe_get(chp, 'chp_capex_usd', 0):,.2f}")

    st.divider()

    # PUE / WUE Improvement
    st.subheader("Efficiency Improvements")
    c7, c8 = st.columns(2)
    pue_imp = _safe_get(chp, 'pue_improvement', 0)
    c7.metric("PUE Improvement", f"{pue_imp:.3f}")
    c8.metric("Effective PUE with CHP", f"{r.pue - pue_imp:.2f}" if pue_imp else "N/A")

    # Visual summary
    st.divider()
    st.subheader("Energy Flow Summary")
    st.markdown(
        f"- **Electrical Output:** {r.p_total_dc:.1f} MW\n"
        f"- **Waste Heat:** {_safe_get(chp, 'waste_heat_mw', 0):.1f} MW (thermal)\n"
        f"- **Recovered Heat:** {_safe_get(chp, 'recovered_heat_mw', 0):.1f} MW (thermal)\n"
        f"- **Absorption Cooling:** {_safe_get(chp, 'cooling_from_absorption_mw', 0):.1f} MW (cooling)\n"
        f"- **Overall CHP Efficiency:** {_safe_get(chp, 'chp_efficiency', 0) * 100:.1f}%\n"
    )


# =============================================================================
# TAB 9: FOOTPRINT
# =============================================================================
def render_footprint_tab(r):
    """Site footprint pie chart, breakdown, and optimization."""

    st.subheader("Site Footprint")

    footprint = r.footprint
    if not footprint:
        st.info("No footprint data available.")
        return

    area_keys = [
        ("gen_area_m2", "Generators"),
        ("bess_area_m2", "BESS"),
        ("cooling_area_m2", "Cooling"),
        ("substation_area_m2", "Substation"),
        ("lng_area_m2", "LNG Storage"),
    ]

    fp_items = []
    fp_values = []

    for key, label in area_keys:
        val = footprint.get(key, 0)
        if val and val > 0:
            fp_items.append(label)
            fp_values.append(val)

    if fp_items:
        # Pie chart
        fig_pie = go.Figure(data=[go.Pie(
            labels=fp_items,
            values=fp_values,
            hole=0.4,
            marker=dict(colors=[COLOR_PRIMARY, COLOR_SECONDARY, COLOR_SUCCESS,
                                COLOR_DANGER, COLOR_GREY]),
            textinfo="label+percent",
        )])
        fig_pie.update_layout(height=400, title_text="Footprint Distribution")
        st.plotly_chart(fig_pie, use_container_width=True)

        # Breakdown table
        st.subheader("Area Breakdown")
        area_unit = _area_label()
        breakdown_rows = []
        for item, val in zip(fp_items, fp_values):
            display_val = _to_display_area(val)
            breakdown_rows.append({
                "Component": item,
                f"Area ({area_unit})": f"{display_val:,.0f}",
            })
        st.table(pd.DataFrame(breakdown_rows).set_index("Component"))

    total_area = footprint.get("total_area_m2", 0)
    total_display = _to_display_area(total_area)
    st.metric("Total Site Area",
              f"{total_display:,.0f} {_area_label()} ({total_area / 10000:.2f} hectares)")

    # Optimization recommendations
    if r.footprint_recommendations:
        st.divider()
        st.subheader("Footprint Optimization Recommendations")
        for rec in r.footprint_recommendations:
            st.markdown(
                f"- **{rec.get('recommendation', rec.get('strategy', ''))}**: "
                f"{rec.get('description', rec.get('details', ''))}"
            )


# =============================================================================
# TAB 10: PHASING
# =============================================================================
def render_phasing_tab(r):
    """Phased deployment schedule and timeline chart."""

    if not r.phasing or not r.phasing.get('phases'):
        st.info("Phased deployment is not enabled for this configuration.")
        return

    st.subheader("Phased Deployment Plan")

    phasing = r.phasing
    phases = phasing['phases']

    c1, c2, c3 = st.columns(3)
    c1.metric("Number of Phases", str(_safe_get(phasing, 'n_phases', len(phases))))
    c2.metric("Total Duration", f"{_safe_get(phasing, 'total_months', 0)} months")
    c3.metric("Phase 1 CAPEX", f"${_safe_get(phasing, 'phase1_capex', 0):,.2f}")

    if _safe_get(phasing, 'deferred_capex', 0) > 0:
        st.info(f"Deferred CAPEX: ${phasing['deferred_capex']:,.2f}")

    st.divider()

    # Phase schedule table
    st.subheader("Phase Schedule")
    phase_rows = []
    for p in phases:
        phase_rows.append({
            "Phase": p.get('phase', p.get('name', '')),
            "Start Month": p.get('start_month', ''),
            "Units Added": p.get('units_added', p.get('n_units', '')),
            "Cumulative Capacity (MW)": f"{p.get('cumulative_cap_mw', 0):.1f}",
            "CAPEX ($)": f"${p.get('capex', 0):,.2f}" if p.get('capex') else "",
        })
    st.table(pd.DataFrame(phase_rows))

    st.divider()

    # Timeline chart: Capacity vs Month
    st.subheader("Capacity Build-Out Timeline")
    months = [p.get('start_month', 0) for p in phases]
    caps = [p.get('cumulative_cap_mw', 0) for p in phases]

    fig_phase = go.Figure()
    fig_phase.add_trace(go.Scatter(
        x=months, y=caps,
        mode='lines+markers',
        name='Cumulative Capacity',
        line=dict(color=COLOR_PRIMARY, width=3),
        marker=dict(size=10),
    ))
    fig_phase.add_hline(
        y=r.p_total_dc, line_dash='dash', line_color=COLOR_DANGER,
        annotation_text=f'Full Load: {r.p_total_dc:.1f} MW',
    )
    fig_phase.update_layout(
        xaxis_title='Month',
        yaxis_title='Capacity (MW)',
        height=400,
    )
    st.plotly_chart(fig_phase, use_container_width=True)


# =============================================================================
# TAB 11: EMISSIONS COMPLIANCE
# =============================================================================
def render_emissions_compliance_tab(r):
    """Full emissions compliance matrix with detailed regulation breakdown."""

    # ---- Emissions Summary (rates + annual totals + aftertreatment) ----
    st.subheader("Emissions Summary")
    emissions = r.emissions
    if emissions:
        nox_tpy = emissions.get('nox_tpy', 0)
        co_tpy = emissions.get('co_tpy', 0)
        co2_tpy = emissions.get('co2_tpy', 0)

        ec_at = r.emissions_control if r.emissions_control else {}
        nox_red = _safe_get(ec_at, 'nox_reduction_pct', 0) / 100
        co_red = _safe_get(ec_at, 'co_reduction_pct', 0) / 100

        nox_after = nox_tpy * (1 - nox_red)
        co_after = co_tpy * (1 - co_red)

        em_data = {
            "Pollutant": ["NOx", "CO", "CO₂"],
            "Rate": [
                f"{emissions.get('nox_rate_g_kwh', 0):.3f} g/kWh",
                f"{emissions.get('co_rate_g_kwh', 0):.3f} g/kWh",
                f"{emissions.get('co2_rate_kg_mwh', 0):.1f} kg/MWh",
            ],
            "Annual Total": [
                f"{nox_tpy:.1f} tons/yr",
                f"{co_tpy:.1f} tons/yr",
                f"{co2_tpy:,.0f} tons/yr",
            ],
            "Annual Total (with Aftertreatment)": [
                f"{nox_after:.1f} tons/yr" if nox_red > 0 else "—",
                f"{co_after:.1f} tons/yr" if co_red > 0 else "—",
                "—",
            ],
        }
        st.table(pd.DataFrame(em_data).set_index("Pollutant"))

    st.divider()

    st.subheader("Emissions Compliance Matrix")

    if not r.emissions_compliance:
        st.info("No emissions compliance data available. Enable emissions control "
                "options in the sidebar to generate compliance analysis.")
        return

    # Full compliance table
    compliance_rows = []
    for item in r.emissions_compliance:
        compliant = item.get('compliant', True)
        icon = "\u2705" if compliant else "\u274c"
        compliance_rows.append({
            "": icon,
            "Regulation": item.get('regulation', ''),
            "Parameter": item.get('parameter', ''),
            "Limit": item.get('limit', ''),
            "Actual": item.get('actual', ''),
            "Unit": item.get('unit', ''),
            "Compliant": "Yes" if compliant else "No",
            "Notes": item.get('notes', ''),
        })

    df_compliance = pd.DataFrame(compliance_rows)
    st.dataframe(df_compliance, use_container_width=True, hide_index=True)

    # Summary
    total_checks = len(r.emissions_compliance)
    passing = sum(1 for item in r.emissions_compliance if item.get('compliant', True))
    if passing == total_checks:
        st.success(f"All {total_checks} regulatory checks passed.")
    else:
        failing = total_checks - passing
        st.error(f"{failing} of {total_checks} checks failed. Aftertreatment recommended.")

    # Aftertreatment recommendation
    if r.emissions_control:
        st.divider()
        st.subheader("Aftertreatment System Recommendation")
        ec = r.emissions_control
        c1, c2, c3 = st.columns(3)
        c1.metric("SCR CAPEX", f"${_safe_get(ec, 'scr_capex', 0):,.2f}")
        c2.metric("OxiCat CAPEX", f"${_safe_get(ec, 'oxicat_capex', 0):,.2f}")
        c3.metric("Total CAPEX", f"${_safe_get(ec, 'total_capex', 0):,.2f}")

        st.markdown(
            f"- NOx Reduction: **{_safe_get(ec, 'nox_reduction_pct', 0):.0f}%**\n"
            f"- CO Reduction: **{_safe_get(ec, 'co_reduction_pct', 0):.0f}%**"
        )


# =============================================================================
# TAB 12: NOISE
# =============================================================================
def render_noise_tab(r):
    """Noise assessment: source levels, compliance, propagation chart."""

    st.subheader("Noise Assessment")

    if not r.noise_results:
        st.info("No noise data available.")
        return

    nr = r.noise_results

    c1, c2, c3 = st.columns(3)
    c1.metric("Source Noise (per unit)", f"{_safe_get(nr, 'source_noise_db', 0):.1f} dBA")
    c2.metric("Combined Noise (fleet)", f"{_safe_get(nr, 'combined_noise_db', 0):.1f} dBA")
    c3.metric("Noise Limit", f"{_safe_get(nr, 'noise_limit_db', 65):.0f} dBA")

    st.divider()

    c4, c5 = st.columns(2)
    c4.metric(f"Noise at Property ({_dist_label()})",
              f"{_safe_get(nr, 'noise_at_property_db', 0):.1f} dBA")
    c5.metric(f"Noise at Residence ({_dist_label()})",
              f"{_safe_get(nr, 'noise_at_residence_db', 0):.1f} dBA")

    # Compliance check
    property_compliant = nr.get('property_compliant', True)
    if property_compliant:
        st.success(":white_check_mark: Noise at property line is within limits.")
    else:
        st.error(":x: Noise at property line exceeds limits. "
                 "Acoustic treatment upgrade or setback increase required.")

    setback = _safe_get(nr, 'setback_distance_m', 0)
    if setback > 0:
        st.info(f"Minimum setback distance for compliance: "
                f"{_to_display_dist(setback):.0f} {_dist_label()}")

    # Acoustic treatment
    treatment = nr.get('acoustic_treatment', 'Standard')
    st.markdown(f"**Acoustic Treatment:** {treatment}")

    st.divider()

    # ---- Noise Propagation Chart ----
    st.subheader("Noise Propagation (Distance vs dBA)")

    combined_db = _safe_get(nr, 'combined_noise_db', 100)
    noise_limit = _safe_get(nr, 'noise_limit_db', 65)

    distances = [10, 25, 50, 100, 200, 300, 500, 750, 1000]
    # Simple inverse-square law noise propagation: L2 = L1 - 20*log10(d2/d1)
    # Reference: combined_noise_db at 1m
    ref_dist = 1.0
    noise_levels = []
    for d in distances:
        if d > 0:
            level = combined_db - 20.0 * np.log10(d / ref_dist)
            noise_levels.append(max(level, 0))
        else:
            noise_levels.append(combined_db)

    fig_noise = go.Figure()
    fig_noise.add_trace(go.Scatter(
        x=distances, y=noise_levels,
        mode='lines+markers',
        name='Noise Level',
        line=dict(color=COLOR_PRIMARY, width=2),
        marker=dict(size=6),
    ))
    fig_noise.add_hline(
        y=noise_limit, line_dash='dash', line_color=COLOR_DANGER,
        annotation_text=f'Limit: {noise_limit} dBA',
    )
    fig_noise.update_layout(
        xaxis_title='Distance (m)',
        yaxis_title='Noise Level (dBA)',
        xaxis_type='log',
        height=400,
    )
    st.plotly_chart(fig_noise, use_container_width=True)


# =============================================================================
# TAB 13: LNG LOGISTICS
# =============================================================================
def render_lng_tab(r):
    """LNG logistics: consumption, storage, truck traffic, CAPEX."""

    st.subheader("LNG Logistics")

    if not r.lng_logistics:
        st.info("LNG logistics data is not available. Select LNG or Dual-Fuel mode.")
        return

    lng = r.lng_logistics

    c1, c2, c3 = st.columns(3)
    c1.metric("Daily LNG Consumption", f"{_safe_get(lng, 'daily_consumption_gal', 0):,.0f} gal/day")
    c2.metric("Storage Required", f"{_safe_get(lng, 'storage_gallons', 0):,.0f} gallons")
    c3.metric("Number of Tanks", str(_safe_get(lng, 'n_tanks', 0)))

    st.divider()

    c4, c5, c6 = st.columns(3)
    c4.metric("Truck Deliveries/Week", f"{_safe_get(lng, 'truck_deliveries_per_week', 0):.1f}")
    c5.metric("LNG Infrastructure CAPEX", f"${_safe_get(lng, 'lng_capex_usd', 0):,.2f}")
    c6.metric("Blended Gas Price", f"${_safe_get(lng, 'blended_gas_price', 0):.2f}/MMBtu")

    st.divider()

    # Visual: daily consumption gauge
    st.subheader("Daily Fuel Consumption")
    daily_gal = _safe_get(lng, 'daily_consumption_gal', 0)
    storage_gal = _safe_get(lng, 'storage_gallons', 0)

    if storage_gal > 0:
        days_autonomy = storage_gal / daily_gal if daily_gal > 0 else 0
        st.progress(min(1.0, daily_gal / storage_gal))
        st.caption(f"Storage provides **{days_autonomy:.1f} days** of autonomy at full load.")

    # Truck traffic info
    st.subheader("Truck Traffic Summary")
    trucks_per_week = _safe_get(lng, 'truck_deliveries_per_week', 0)
    st.markdown(
        f"- **{trucks_per_week:.1f} truck deliveries per week** "
        f"(~{trucks_per_week/7:.1f} per day)\n"
        f"- Standard LNG trailer: ~10,000 gallons\n"
        f"- Consider traffic routing and site access constraints"
    )


# =============================================================================
# TAB 14: DERATING
# =============================================================================
def render_derating_tab(r):
    """Derating breakdown with CAT official tables."""

    st.subheader("Site Derating Analysis")

    if r.methane_warning:
        st.warning(f":warning: {r.methane_warning}")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Site Conditions**")
        site_temp_c = st.session_state.get('_site_temp', 35)
        site_alt_m = st.session_state.get('_site_alt', 100)
        mn = st.session_state.get('_mn', 80)

        temp_display = _to_display_temp(site_temp_c)
        alt_display = _to_display_alt(site_alt_m)

        st.markdown(f"- Temperature: **{temp_display:.0f}{_temp_label()}**")
        st.markdown(f"- Altitude: **{alt_display:.0f} {_alt_label()}**")
        st.markdown(f"- Methane Number: **{mn}**")

    with c2:
        st.markdown("**Derating Factors (CAT Official Tables)**")
        st.markdown(f"- Methane Deration: **{r.methane_deration:.4f}**")
        st.markdown(f"- Altitude Deration (ADF): **{r.altitude_deration:.4f}**")
        st.markdown(f"- **Combined Derate: {r.derate_factor:.4f}**")

    st.divider()

    # ACHRF
    st.subheader("Aftercooler Heat Rejection Factor")
    st.metric("ACHRF", f"{r.achrf:.4f}")
    st.caption(
        "The Aftercooler Heat Rejection Factor indicates the increase in heat rejection "
        "at site conditions relative to ISO. Values > 1.0 mean additional cooling capacity "
        "is needed."
    )

    st.divider()

    # Visual breakdown
    st.subheader("Derating Waterfall")
    fig = go.Figure(go.Waterfall(
        name="Derate",
        orientation="v",
        x=["ISO Rating", "Methane Deration", "Altitude Deration", "Site Rating"],
        y=[1.0,
           -(1.0 - r.methane_deration),
           -(r.methane_deration - r.derate_factor),
           0],
        measure=["absolute", "relative", "relative", "total"],
        connector=dict(line=dict(color="gray")),
        increasing=dict(marker=dict(color=COLOR_SECONDARY)),
        decreasing=dict(marker=dict(color=COLOR_DANGER)),
        totals=dict(marker=dict(color=COLOR_PRIMARY)),
        text=[
            "1.000",
            f"-{(1.0 - r.methane_deration):.4f}",
            f"-{(r.methane_deration - r.derate_factor):.4f}",
            f"{r.derate_factor:.4f}",
        ],
        textposition="outside",
    ))
    fig.update_layout(
        yaxis_title="Factor",
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# TAB: GAS CONSUMPTION
# =============================================================================
def render_gas_consumption_tab(r):
    """Fuel consumption curve for the selected generator."""

    gen_data = GENERATOR_LIBRARY.get(r.selected_gen, {})
    curve = gen_data.get("fuel_consumption_curve")

    if not curve:
        st.info("Fuel consumption curve data is not available for this generator model.")
        return

    load_pcts = curve["load_pct"]
    mj_values = curve["mj_per_ekwh"]
    iso_kw = gen_data["iso_rating_mw"] * 1000
    power_kw = [iso_kw * (p / 100) for p in load_pcts]

    fig = go.Figure()

    # Fuel consumption curve
    fig.add_trace(go.Scatter(
        x=power_kw, y=mj_values,
        mode="lines+markers",
        name="Fuel Consumption",
        line=dict(color=COLOR_PRIMARY, width=3),
        marker=dict(size=8),
    ))

    # Operating point
    op_pct = min(max(r.load_per_unit_pct, load_pcts[0]), load_pcts[-1])
    op_kw = iso_kw * (op_pct / 100)
    # Interpolate MJ/ekWh at operating point
    op_mj = np.interp(op_pct, load_pcts, mj_values)

    fig.add_trace(go.Scatter(
        x=[op_kw], y=[op_mj],
        mode="markers+text",
        name="Operating Point",
        marker=dict(size=14, color=COLOR_DANGER, symbol="star"),
        text=[f"  {op_mj:.2f} MJ/ekWh @ {op_pct:.0f}%"],
        textposition="middle right",
        textfont=dict(size=12, color=COLOR_DANGER),
    ))

    fig.update_layout(
        title=f"Genset Power vs. Fuel Consumption (nominal) \u2014 {r.selected_gen}",
        xaxis_title="Genset Power (ekW)",
        yaxis_title="Fuel Consumption (MJ/ekW-hr)",
        height=450,
        yaxis=dict(range=[min(mj_values) - 0.3, max(mj_values) + 0.3]),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Summary metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("Full Load Consumption", f"{mj_values[-1]:.2f} MJ/ekWh")
    c2.metric("At Operating Point", f"{op_mj:.2f} MJ/ekWh")
    c3.metric("Load per Unit", f"{r.load_per_unit_pct:.1f}%")

    # ── Monthly Gas Consumption (P10) ──
    if hasattr(r, 'gas_pipeline') and r.gas_pipeline:
        gp = r.gas_pipeline

        st.divider()
        st.subheader("Monthly Gas Consumption")

        monthly = gp['monthly_consumption']
        df_monthly = pd.DataFrame(monthly)
        df_monthly.columns = ['Month', 'Days', 'Energy (MWh)', 'Consumption (MMBtu)', 'Flow rate (MMSCFD)']
        df_monthly['Consumption (MMBtu)'] = df_monthly['Consumption (MMBtu)'].apply(
            lambda x: f"{x:,.0f}")
        df_monthly['Energy (MWh)'] = df_monthly['Energy (MWh)'].apply(
            lambda x: f"{x:,.0f}")

        st.dataframe(df_monthly, use_container_width=True, hide_index=True)

        gc1, gc2, gc3 = st.columns(3)
        gc1.metric("Annual consumption", f"{gp['annual_mmbtu']/1e6:.2f}M MMBtu/yr")
        gc2.metric("Daily average flow", f"{gp['daily_mmscfd']:.2f} MMSCFD")
        gc3.metric("Annual energy gen.", f"{gp['annual_mwh']/1e6:.3f} TWh/yr")

        st.caption(
            f"Based on operating heat rate of {op_mj:.2f} MJ/ekWh "
            f"at {r.load_per_unit_pct:.1f}% load (part-load efficiency applied). "
            f"LHV assumed: 1,012 BTU/scf (pipeline natural gas)."
        )

        # ── Pipeline Sizing (P10) ──
        st.divider()
        st.subheader("Gas Supply Pipeline Sizing")

        # Inline editable inputs (mirror sidebar)
        with st.expander("Pipeline parameters", expanded=True):
            pcol1, pcol2 = st.columns(2)
            with pcol1:
                st.number_input(
                    "Supply pressure (psia)", 10.0, 1500.0,
                    value=float(gp['P1_supply_psia']), step=10.0,
                    key="gas_p1_inline",
                    help="Gas utility pressure at site boundary fence.",
                )
            with pcol2:
                st.number_input(
                    "Distance to utility tap (miles)", 0.1, 50.0,
                    value=float(gp['pipeline_length_miles']), step=0.5,
                    key="gas_dist_inline",
                    help="Pipeline length from utility main to site.",
                )
            st.caption(
                f"Generator type: **{gp['gen_type_label']}** — "
                f"minimum site inlet pressure required: **{gp['P2_required_psia']:.0f} psia**. "
                f"Update sidebar inputs and re-run to recalculate with new values."
            )

        if gp['needs_compressor']:
            st.error(
                f"⛽ **Fuel Gas Booster Compressor Required.** "
                f"Utility supply pressure ({gp['P1_supply_psia']:.0f} psia) is below "
                f"the minimum combustor inlet pressure for {gp['gen_type_label']} "
                f"({gp['P2_required_psia']:.0f} psia). "
                f"A fuel gas booster compressor must be included in the plant design. "
                f"Set supply pressure ≥ {gp['P2_required_psia']:.0f} psia and re-run to size the pipeline."
            )
        else:
            pc1, pc2, pc3, pc4 = st.columns(4)
            pc1.metric("Flow rate",       f"{gp['daily_mmscfd']:.2f} MMSCFD")
            pc2.metric("Min. diameter",   f"{gp['D_min_inches']:.2f}\"")
            pc3.metric("Recommended NPS", f"NPS {gp['D_nps_inches']}\"")
            pc4.metric("Pipe velocity",   f"{gp['velocity_fps']:.0f} ft/s")

            if gp['velocity_fps'] > 60:
                st.warning(
                    f"⚠️ Gas velocity {gp['velocity_fps']:.0f} ft/s exceeds 60 ft/s recommended "
                    f"limit for carbon steel pipe (erosion risk). Consider larger NPS or "
                    f"verify supply pressure assumptions."
                )

            st.caption(
                f"Weymouth equation  ·  "
                f"P1={gp['P1_supply_psia']:.0f} psia → P2={gp['P2_required_psia']:.0f} psia  ·  "
                f"L={gp['pipeline_length_miles']:.1f} mi  ·  "
                f"E={gp['assumptions']['pipe_efficiency_E']}  ·  "
                f"Sg={gp['assumptions']['gas_sg']}  ·  "
                f"T={gp['assumptions']['gas_temp_f']:.0f}°F  ·  "
                f"Z={gp['assumptions']['gas_z_factor']}"
            )
            st.warning(
                "⚠️ **Engineering disclaimer:** Pipeline diameter is a preliminary estimate "
                "for conceptual design only. The Weymouth equation assumes fully turbulent "
                "flow and is conservative vs Panhandle A/B. Actual design requires: "
                "(1) gas composition analysis for LHV and Sg, "
                "(2) utility supply pressure verification, "
                "(3) detailed hydraulic simulation per ASME B31.8. "
                "Consult the gas utility and a licensed pipeline engineer before procurement."
            )

    st.caption(
        "Source: CAT Gas Consumption data sheet. "
        "Fuel consumption increases at part load due to lower thermal efficiency."
    )


# =============================================================================
# TAB 15: PDF REPORT
# =============================================================================
def render_pdf_tab(r):
    """PDF report download."""

    st.subheader("Download Sizing Report")
    st.markdown(
        "Generate a comprehensive PDF report with all sizing results, "
        "charts, and technical specifications."
    )

    try:
        pdf_data = r.model_dump()
        # Add gen_data for the PDF report
        gen_data = GENERATOR_LIBRARY.get(r.selected_gen, {})
        pdf_data["gen_data"] = gen_data
        pdf_bytes = generate_comprehensive_pdf(pdf_data)

        st.download_button(
            label=":page_facing_up: Download PDF Report",
            data=pdf_bytes,
            file_name=f"CAT_Sizing_{r.selected_gen}_{r.p_it:.0f}MW.pdf",
            mime="application/pdf",
            type="primary",
        )
    except Exception as e:
        st.error(f"Error generating PDF: {e}")


# =============================================================================
# LANDING PAGE
# =============================================================================
def render_landing_page():
    """Show landing page when no sizing result is available."""
    st.image("assets/logo_caterpillar.png", width=350)
    st.markdown(f"### Power Solution — Prime Power Quick-Size Tool v{APP_VERSION}")
    st.markdown("---")
    st.markdown(
        """
        Configure your project parameters in the sidebar, then click
        **:zap: Run Sizing** to generate a complete power solution.

        **Features:**
        - 10 generator models (High Speed, Medium Speed, Gas Turbine)
        - Official CAT derating tables with bilinear interpolation
        - BESS sizing with multiple strategies
        - Weibull reliability modeling (N+X configurations)
        - CHP / Tri-Generation analysis
        - Emissions compliance with 5 regulatory frameworks
        - Noise assessment with propagation modeling
        - LNG logistics and dual-fuel support
        - Phased deployment planning
        - Financial analysis (LCOE, NPV, payback, gas sensitivity)
        - Off-Grid vs Grid 20-year cost comparison
        - Design validation scorecard
        - PDF report generation

        **Quick Start:** Select a template preset from the sidebar to
        pre-fill typical values for your project size.
        """
    )

    st.divider()

    # Generator library quick reference
    st.subheader("Generator Library")
    lib_data = []
    for name, spec in sorted(GENERATOR_LIBRARY.items()):
        lib_data.append({
            "Model": name,
            "Type": spec.get("type", ""),
            "ISO MW": spec.get("iso_rating_mw", 0),
            "Eff (%)": f"{spec.get('electrical_efficiency', 0) * 100:.1f}",
            "Step (%)": spec.get("step_load_pct", 0),
            "Voltage (kV)": spec.get("voltage_kv", 0),
        })
    st.dataframe(pd.DataFrame(lib_data), use_container_width=True, hide_index=True)


def _build_proposal_info_from_session() -> dict:
    """Collect proposal commercial fields from session state into a dict."""
    return {
        "cat_division":          st.session_state.get("prop_cat_division",
                                     PROPOSAL_DEFAULTS["cat_division"]),
        "proposal_type":         st.session_state.get("prop_proposal_type",
                                     PROPOSAL_DEFAULTS["proposal_type"]),
        "doc_version":           st.session_state.get("prop_doc_version",
                                     PROPOSAL_DEFAULTS["doc_version"]),
        "bdm_name":              st.session_state.get("prop_bdm_name",
                                     PROPOSAL_DEFAULTS["bdm_name"]),
        "bdm_email":             st.session_state.get("prop_bdm_email",
                                     PROPOSAL_DEFAULTS["bdm_email"]),
        "dealer_name":           st.session_state.get("prop_dealer_name",
                                     PROPOSAL_DEFAULTS["dealer_name"]),
        "incoterm":              st.session_state.get("prop_incoterm",
                                     PROPOSAL_DEFAULTS["incoterm"]),
        "delivery_destination":  st.session_state.get("prop_delivery_destination",
                                     PROPOSAL_DEFAULTS["delivery_destination"]),
        "delivery_date_est":     st.session_state.get("prop_delivery_date_est",
                                     PROPOSAL_DEFAULTS["delivery_date_est"]),
        "proposal_validity":     st.session_state.get("prop_proposal_validity",
                                     PROPOSAL_DEFAULTS["proposal_validity"]),
        "payment_pct_down":      st.session_state.get("prop_payment_down",
                                     PROPOSAL_DEFAULTS["payment_pct_down"]),
        "payment_pct_30d":       st.session_state.get("prop_payment_30d",
                                     PROPOSAL_DEFAULTS["payment_pct_30d"]),
        "payment_pct_sol":       st.session_state.get("prop_payment_sol",
                                     PROPOSAL_DEFAULTS["payment_pct_sol"]),
        "payment_pct_rts":       st.session_state.get("prop_payment_rts",
                                     PROPOSAL_DEFAULTS["payment_pct_rts"]),
        "offer_type_genset":     st.session_state.get("prop_offer_genset",
                                     PROPOSAL_DEFAULTS["offer_type_genset"]),
        "offer_type_switchgear": st.session_state.get("prop_offer_switchgear",
                                     PROPOSAL_DEFAULTS["offer_type_switchgear"]),
        "offer_type_solutions":  st.session_state.get("prop_offer_solutions",
                                     PROPOSAL_DEFAULTS["offer_type_solutions"]),
        "offer_type_hybrid":     st.session_state.get("prop_offer_hybrid",
                                     PROPOSAL_DEFAULTS["offer_type_hybrid"]),
        "include_cva":           st.session_state.get("prop_include_cva",
                                     PROPOSAL_DEFAULTS["include_cva"]),
        "include_esc":           st.session_state.get("prop_include_esc",
                                     PROPOSAL_DEFAULTS["include_esc"]),
        "additional_options":    PROPOSAL_DEFAULTS["additional_options"],
        "proposal_notes":        st.session_state.get("prop_notes",
                                     PROPOSAL_DEFAULTS["proposal_notes"]),
    }


def render_proposal_tab(r):
    """Render the Proposal Document generation tab."""
    st.subheader("Customer Proposal Document")
    st.markdown(
        "Generate a formatted Word (.docx) proposal for this project. "
        "Complete the **📄 Proposal Information** fields in the sidebar before generating."
    )

    proposal_info = _build_proposal_info_from_session()

    # Validation warnings
    warnings = []
    if not proposal_info["bdm_name"]:
        warnings.append("BDM Name is empty — will appear blank on cover page.")
    if not proposal_info["dealer_name"]:
        warnings.append("Authorized CAT Dealer name is empty — required for pricing section.")
    if not proposal_info["delivery_date_est"]:
        warnings.append("Estimated delivery date is empty.")
    pct_total = (
        proposal_info["payment_pct_down"] +
        proposal_info["payment_pct_30d"] +
        proposal_info["payment_pct_sol"] +
        proposal_info["payment_pct_rts"]
    )
    if pct_total != 100:
        warnings.append(f"Payment terms total {pct_total}% — should sum to 100%.")

    if warnings:
        with st.expander(f"⚠️ {len(warnings)} field(s) incomplete", expanded=True):
            for w in warnings:
                st.warning(w)

    # Preview summary
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Project", st.session_state.get("_wiz_project_name", "—"))
        st.metric("Client", st.session_state.get("_wiz_client_name", "—"))
    with col2:
        st.metric("Generator", r.selected_gen)
        st.metric("Proposal Type", proposal_info["proposal_type"])
    with col3:
        st.metric("Division", proposal_info["cat_division"])
        st.metric("Version", proposal_info["doc_version"])

    st.divider()

    if st.button("📄 Generate Proposal Document", type="primary", use_container_width=True):
        header_info = {
            "project_name":   st.session_state.get("_wiz_project_name", "Unnamed Project"),
            "client_name":    st.session_state.get("_wiz_client_name", ""),
            "contact_name":   st.session_state.get("_wiz_contact_name", ""),
            "contact_email":  st.session_state.get("_wiz_contact_email", ""),
            "contact_phone":  st.session_state.get("_wiz_contact_phone", ""),
            "country":        st.session_state.get("_wiz_country", ""),
            "state_province": st.session_state.get("_wiz_state_province", ""),
        }
        try:
            with st.spinner("Generating proposal document..."):
                docx_bytes = generate_proposal_docx(
                    sizing_result=r,
                    header_info=header_info,
                    proposal_info=proposal_info,
                )
            project_slug = header_info["project_name"].replace(" ", "_")[:30]
            version_slug = proposal_info["doc_version"].replace(" ", "").replace(".", "")
            filename = f"CAT_Proposal_{project_slug}_{version_slug}.docx"
            st.success("✅ Proposal document ready.")
            st.download_button(
                label="⬇️ Download Proposal (.docx)",
                data=docx_bytes,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Proposal generation failed: {e}")
            import traceback
            st.code(traceback.format_exc())


# =============================================================================
# MAIN
# =============================================================================
def main():
    """Main app entry point — wizard-first, then results."""

    # ── Auth gate — blocks until authenticated ──
    check_auth()

    # Initialize session state
    if "result" not in st.session_state:
        st.session_state.result = None
    _init_wizard_state()

    # ── WIZARD MODE ──
    if not st.session_state.get("_wizard_complete", False):
        render_wizard()
        return

    # ── RESULTS MODE ──

    # First run after wizard completes
    if st.session_state.get("_wizard_running", False):
        inputs_dict, benchmark_price = _build_inputs_from_wizard()
        try:
            with st.spinner("Running sizing pipeline..."):
                sizing_input = SizingInput(**inputs_dict)
                result = run_full_sizing(sizing_input)
                st.session_state.result = result
                st.session_state["_wizard_running"] = False
        except Exception as e:
            st.error(f"Sizing failed: {e}")
            import traceback
            st.code(traceback.format_exc())
            st.session_state["_wizard_running"] = False
            st.session_state["_wizard_complete"] = False
            return

    # Sidebar for post-wizard adjustments
    inputs_dict, benchmark_price = render_sidebar()

    # "Back to Wizard" button in sidebar
    st.sidebar.divider()
    if st.sidebar.button(":arrow_left: Back to Wizard", use_container_width=True):
        st.session_state["_wizard_complete"] = False
        st.session_state["_wizard_step"] = 4
        st.rerun()

    # Store some values for cross-tab access
    st.session_state["_benchmark_price"] = inputs_dict["benchmark_price"]
    st.session_state["_site_temp"] = inputs_dict["site_temp_c"]
    st.session_state["_site_alt"] = inputs_dict["site_alt_m"]
    st.session_state["_mn"] = inputs_dict["methane_number"]
    st.session_state["_fuel_mode"] = inputs_dict["fuel_mode"]
    st.session_state["_dist_loss_pct"] = inputs_dict["dist_loss_pct"]
    st.session_state["_include_chp"] = inputs_dict["include_chp"]
    st.session_state["_enable_phasing"] = inputs_dict["enable_phasing"]

    # Auto-run sizing on every input change (reactive)
    try:
        sizing_input = SizingInput(**inputs_dict)
        result = run_full_sizing(sizing_input)
        st.session_state.result = result
    except Exception as e:
        st.error(f"Sizing failed: {e}")
        import traceback
        st.code(traceback.format_exc())
        return

    r = st.session_state.result

    # ---- Executive Summary (before tabs) ----
    render_executive_summary(r, benchmark_price)

    # ---- Determine which conditional tabs to show ----
    fuel_mode = st.session_state.get("_fuel_mode", "Pipeline Gas")
    include_chp = st.session_state.get("_include_chp", False)
    enable_phasing = st.session_state.get("_enable_phasing", False)
    show_lng = fuel_mode in ("LNG", "Dual-Fuel")

    # ---- Build tab list ----
    # Check if selected generator has fuel consumption curve
    _gen_data = GENERATOR_LIBRARY.get(r.selected_gen, {})
    show_gas_tab = "fuel_consumption_curve" in _gen_data

    tab_labels = [
        ":clipboard: Summary",
        ":chart_with_upwards_trend: Reliability",
        ":battery: BESS",
        ":electric_plug: Electrical",
        ":bar_chart: Load Profile",
        ":deciduous_tree: Environmental",
        ":moneybag: Financial",
    ]
    if show_gas_tab:
        tab_labels.append(":fuelpump: Gas Consumption")

    # Conditional tabs
    if include_chp:
        tab_labels.append(":fire: CHP / Tri-Gen")
    tab_labels.append(":world_map: Footprint")
    if enable_phasing:
        tab_labels.append(":calendar: Phasing")
    tab_labels.append(":page_with_curl: Emissions Compliance")
    tab_labels.append(":loud_sound: Noise")
    if show_lng:
        tab_labels.append(":fuelpump: LNG Logistics")
    if ENABLE_PROPOSAL_GEN:
        tab_labels.append(":memo: Proposal Doc")
    tab_labels.append(":page_facing_up: PDF Report")

    tabs = st.tabs(tab_labels)

    tab_idx = 0

    # Tab 1: Summary
    with tabs[tab_idx]:
        render_summary_tab(r)
    tab_idx += 1

    # Tab 2: Reliability
    with tabs[tab_idx]:
        render_reliability_tab(r)
    tab_idx += 1

    # Tab 3: BESS
    with tabs[tab_idx]:
        render_bess_tab(r)
    tab_idx += 1

    # Tab 4: Electrical
    with tabs[tab_idx]:
        render_electrical_tab(r)
    tab_idx += 1

    # Tab 5: Load Profile
    with tabs[tab_idx]:
        render_load_profile_tab(r)
    tab_idx += 1

    # Tab 6: Environmental
    with tabs[tab_idx]:
        render_environmental_tab(r)
    tab_idx += 1

    # Tab 7: Financial
    with tabs[tab_idx]:
        render_financial_tab(r, benchmark_price)
    tab_idx += 1

    # Tab: Gas Consumption (conditional)
    if show_gas_tab:
        with tabs[tab_idx]:
            render_gas_consumption_tab(r)
        tab_idx += 1

    # Tab 8: CHP (conditional)
    if include_chp:
        with tabs[tab_idx]:
            render_chp_tab(r)
        tab_idx += 1

    # Tab 9: Footprint
    with tabs[tab_idx]:
        render_footprint_tab(r)
    tab_idx += 1

    # Tab 10: Phasing (conditional)
    if enable_phasing:
        with tabs[tab_idx]:
            render_phasing_tab(r)
        tab_idx += 1

    # Tab 11: Emissions Compliance
    with tabs[tab_idx]:
        render_emissions_compliance_tab(r)
    tab_idx += 1

    # Tab 12: Noise
    with tabs[tab_idx]:
        render_noise_tab(r)
    tab_idx += 1

    # Tab 13: LNG Logistics (conditional)
    if show_lng:
        with tabs[tab_idx]:
            render_lng_tab(r)
        tab_idx += 1

    # Tab: Proposal Doc (conditional on feature flag)
    if ENABLE_PROPOSAL_GEN:
        with tabs[tab_idx]:
            render_proposal_tab(r)
        tab_idx += 1

    # Tab: PDF Report
    with tabs[tab_idx]:
        render_pdf_tab(r)
    tab_idx += 1


if __name__ == "__main__":
    main()
