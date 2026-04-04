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
from core.proposal_generator import generate_proposal_docx, _generate_proposal_docx_legacy
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

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(
    page_title="CAT Power Solution",
    page_icon=":zap:",
    layout="wide",
    initial_sidebar_state="expanded",
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

# Per-DC-type suggested defaults for load dynamics parameters.
# These are industry-typical values for preliminary sizing — the user
# can always override them after the auto-fill.
# Sources: Uptime Institute, ASHRAE TC9.9, Lawrence Berkeley National Lab
DC_TYPE_DEFAULTS = {
    "AI Factory (Training)": {
        "pue":               1.12,   # liquid cooling, very efficient
        "capacity_factor":   0.90,   # training runs at near-constant load
        "peak_avg_ratio":    1.10,   # very flat load profile
        "load_step_pct":     30.0,   # large GPU job starts/stops
        "spinning_res_pct":  15.0,   # high SR — GPU loads are unforgiving
        "load_ramp_req":     5.0,    # MW/min
        "avail_req":         99.99,
    },
    "AI Inference": {
        "pue":               1.15,
        "capacity_factor":   0.75,   # variable inference traffic
        "peak_avg_ratio":    1.25,
        "load_step_pct":     25.0,
        "spinning_res_pct":  15.0,
        "load_ramp_req":     5.0,
        "avail_req":         99.99,
    },
    "Hyperscale Standard": {
        "pue":               1.25,
        "capacity_factor":   0.80,
        "peak_avg_ratio":    1.20,
        "load_step_pct":     20.0,
        "spinning_res_pct":  10.0,
        "load_ramp_req":     3.0,
        "avail_req":         99.99,
    },
    "Colocation": {
        "pue":               1.35,
        "capacity_factor":   0.70,
        "peak_avg_ratio":    1.35,
        "load_step_pct":     15.0,
        "spinning_res_pct":  10.0,
        "load_ramp_req":     2.0,
        "avail_req":         99.982,  # Tier III
    },
    "Enterprise Mixed": {
        "pue":               1.45,
        "capacity_factor":   0.65,
        "peak_avg_ratio":    1.40,
        "load_step_pct":     10.0,
        "spinning_res_pct":  10.0,
        "load_ramp_req":     1.5,
        "avail_req":         99.741,  # Tier II
    },
    "HPC / Research": {
        "pue":               1.20,
        "capacity_factor":   0.85,
        "peak_avg_ratio":    1.15,
        "load_step_pct":     35.0,   # batch job starts
        "spinning_res_pct":  15.0,
        "load_ramp_req":     5.0,
        "avail_req":         99.99,
    },
    "Edge Computing": {
        "pue":               1.30,
        "capacity_factor":   0.60,
        "peak_avg_ratio":    1.50,   # very peaky
        "load_step_pct":     25.0,
        "spinning_res_pct":  15.0,
        "load_ramp_req":     3.0,
        "avail_req":         99.671,  # Tier I
    },
}

# DC_TYPE_DEFAULTS is kept as reference data (P35: wizard removed, sidebar uses INPUT_DEFAULTS directly)


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


# ── Electrical Path Availability — IEEE 493-2007 (Gold Book) ─────────────────
# Component failure rates and MTTR from IEEE 493-2007, Table 3-4.
# Step-up transformers EXCLUDED: their failure affects generator availability
# (counted in the binomial fleet model), not the bus path availability.

_IEEE493 = {
    # component: (lambda failures/yr, MTTR hours)  Source: IEEE 493-2007 Table 3-4
    "cb":    (0.0027,  83.1),   # MV circuit breaker, metal-clad switchgear
    "bus":   (0.0024,  35.0),   # Bus duct, per 100 ft section
    "cable": (0.0083,  15.7),   # MV cable, per 1,000 ft
    "trafo": (0.0062, 341.7),   # Power transformer >500 kVA (shown in table, EXCLUDED from calc)
}

def _ieee493_section_load_path_U(
    n_D_breakers: int = 2,     # 52D distribution breakers per section (load side)
    bus_ft: float     = 150.0, # HV bus length per section
    cable_ft: float   = 500.0, # HV cable to loads
) -> float:
    """
    Unavailability of ONE HV bus section's load-side path.
    Includes: HV bus + 52D distribution breakers + HV cable to load.
    Excludes: 52T generator incomers and step-up transformers (in fleet model).
    """
    lam_cb,  mttr_cb  = _IEEE493["cb"]
    lam_bus, mttr_bus  = _IEEE493["bus"]
    lam_cbl, mttr_cbl  = _IEEE493["cable"]
    return (n_D_breakers * lam_cb * mttr_cb / 8760
            + lam_bus * mttr_bus / 8760 * (bus_ft / 100.0)
            + lam_cbl * mttr_cbl / 8760 * (cable_ft / 1000.0))

def _ieee493_elec_path(topology: str) -> float:
    """
    Calculate electrical path availability per IEEE 493-2007.
    For ring/redundant topologies, models simultaneous failure probability.
    52T5 demand failure (fails to close on N-1) is included for ring topologies.
    Returns: A_path (0-1).
    """
    U_CB = _IEEE493["cb"][0] * _IEEE493["cb"][1] / 8760  # per breaker

    if topology == "Radial single bus":
        U = _ieee493_section_load_path_U(n_D_breakers=4, bus_ft=200, cable_ft=500)
        return 1.0 - U

    elif topology == "Ring bus / sectionalized (N-1)":
        U_sec = _ieee493_section_load_path_U(n_D_breakers=2, bus_ft=150, cable_ft=500)
        U_52T5_demand = U_CB * (U_sec * 2)
        U_ring = U_sec ** 2 + U_52T5_demand
        return 1.0 - U_ring

    elif topology == "Double bus / double breaker":
        U_sec = _ieee493_section_load_path_U(n_D_breakers=2, bus_ft=100, cable_ft=300)
        U_dbl = U_sec ** 2 + U_CB * (U_sec * 2)
        return 1.0 - U_dbl

    elif topology == "2N fully redundant":
        U_sec = _ieee493_section_load_path_U(n_D_breakers=2, bus_ft=80, cable_ft=200)
        return 1.0 - U_sec ** 2

    return 0.9990  # conservative fallback

_ELEC_TOPOLOGY_OPTIONS = {
    "Radial single bus": {
        "description": (
            "Single bus section, no redundancy. Any bus component failure "
            "causes a full outage. Only suitable for small or temporary "
            "installations without reliability requirements."
        ),
        "typical_use": "Small projects, temporary power, non-critical loads.",
    },
    "Ring bus / sectionalized (N-1)": {
        "description": (
            "Dual HV section bus (SWGR-A and SWGR-B) with bus-tie breaker 52T5 "
            "(normally open). In normal operation each section carries half the load. "
            "On N-1 (one section fails), 52T5 closes and the surviving section "
            "carries 100% of load. CAT standard topology for data center prime power -- "
            "confirmed across Fidelis 120 MW, JERA Americas 150/216 MW, and P-05H."
        ),
        "typical_use": "Standard data center prime power. CAT default.",
    },
    "Double bus / double breaker": {
        "description": (
            "Each generator and each load feeder connects to both buses via "
            "independent breakers. Both buses must fail simultaneously for "
            "any load to be interrupted. Higher capital cost than ring bus."
        ),
        "typical_use": "Tier III-IV, high-reliability industrial, large campus.",
    },
    "2N fully redundant": {
        "description": (
            "Two completely independent electrical paths -- separate transformer, "
            "switchgear, cable, and feeder for each load. Any single component "
            "failure is tolerated without any load interruption."
        ),
        "typical_use": "Tier IV, mission-critical financial/government infrastructure.",
    },
}

def _fmt_downtime(hours):
    """Format downtime in the most readable unit."""
    if hours < 1/60:
        return f"{hours*3600:.1f} sec/yr"
    elif hours < 1:
        return f"{hours*60:.1f} min/yr"
    return f"{hours:.1f} hr/yr"


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

    # ---- 3. Project Info ----
    with st.sidebar.expander("\U0001f4cb Project Info", expanded=False):
        st.caption("Fill these fields when generating the proposal document.")
        st.text_input("Project Name", placeholder="Phoenix DC-1 Prime Power",
                      key="_project_name", help=HELP_TEXTS.get("project_name", ""))
        st.text_input("Client Name", placeholder="Acme Corp",
                      key="_client_name", help=HELP_TEXTS.get("client_name", ""))
        st.text_input("Contact Name", key="_contact_name",
                      help=HELP_TEXTS.get("contact_name", ""))
        st.text_input("Contact Email", key="_contact_email",
                      help=HELP_TEXTS.get("contact_email", ""))
        st.text_input("Contact Phone", key="_contact_phone",
                      help=HELP_TEXTS.get("contact_phone", ""))
        _country_default = HEADER_DEFAULTS.get("country", COUNTRIES[0] if COUNTRIES else "")
        _country_idx = COUNTRIES.index(_country_default) if _country_default in COUNTRIES else 0
        st.selectbox("Country", COUNTRIES, index=_country_idx,
                     key="_country", help=HELP_TEXTS.get("country", ""))
        st.text_input("State / Province", key="_state_province",
                      help=HELP_TEXTS.get("state_province", ""))
        st.text_input("County / District", key="_county_district",
                      help=HELP_TEXTS.get("county_district", ""))
        freq_hz = st.radio("Grid Frequency (Hz)", [60, 50], index=0, horizontal=True,
                           key="_freq_hz_proposal", help=HELP_TEXTS.get("freq_hz", ""))

    # ---- 4. Load Profile (Basic — expanded) ----
    with st.sidebar.expander("\U0001f4ca Load Profile", expanded=True):
        _dc_default = INPUT_DEFAULTS["dc_type"]
        dc_type = st.selectbox(
            "Data Center Type", DC_TYPES,
            index=DC_TYPES.index(_dc_default) if _dc_default in DC_TYPES else 0,
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

    # ---- 5. Generator & BESS (Basic — expanded) ----
    with st.sidebar.expander("\u26a1 Generator & BESS", expanded=True):
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

        use_bess = st.checkbox(
            "Include BESS", value=INPUT_DEFAULTS["use_bess"],
            help=HELP_TEXTS.get("use_bess", ""),
        )
        bess_strategy = "Hybrid (Balanced)"
        bess_autonomy_min = float(INPUT_DEFAULTS.get("bess_autonomy_min", 10.0))
        bess_dod = float(INPUT_DEFAULTS.get("bess_dod", 0.85))
        if use_bess:
            _autonomy_default = INPUT_DEFAULTS.get('bess_autonomy_min', 10.0)
            bess_autonomy_min = st.number_input(
                "BESS autonomy (minutes)",
                min_value=0.5,
                max_value=120.0,
                value=float(st.session_state.get('_stored_bess_autonomy_min', st.session_state.get('_bess_autonomy_min', _autonomy_default))),
                step=0.5,
                format="%.1f",
                key='_bess_autonomy_min',
                help=(
                    "Time the BESS must sustain its rated power output. "
                    "Drives energy capacity: MWh = MW × (min ÷ 60) ÷ DoD.\n\n"
                    "Typical values by role:\n"
                    "• 1 min — Transient only (governor gap cover)\n"
                    "• 10 min — Hybrid (time to start and sync one unit)\n"
                    "• 30 min — Reliability priority (operator response window)\n"
                    "• 60–120 min — Short-term backup (client-specific requirement)"
                ),
            )
            bess_dod = st.number_input(
                "BESS Depth of Discharge",
                min_value=0.50, max_value=1.00,
                value=float(INPUT_DEFAULTS.get("bess_dod", 0.85)),
                step=0.05, format="%.2f",
                help="Usable fraction of total battery capacity (0.85 = 85% DoD typical for Li-ion).",
            )
        enable_black_start = st.checkbox(
            "Black Start Capable", value=INPUT_DEFAULTS["enable_black_start"],
            help=HELP_TEXTS.get("enable_black_start", ""),
        )
        include_chp = st.checkbox(
            "Include CHP / Tri-Generation",
            value=INPUT_DEFAULTS.get("include_chp", False),
            help=HELP_TEXTS.get("include_chp", ""),
        )

    # ---- 6. Site Conditions (collapsed) ----
    with st.sidebar.expander("\U0001f321\ufe0f Site Conditions"):
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
            # Get derate_type from generator (site conditions renders before technology; use default)
            _sb_gen = INPUT_DEFAULTS["selected_gen_name"]
            _sb_gen_data = GENERATOR_LIBRARY.get(_sb_gen, {})
            _sb_derate_type = _sb_gen_data.get('derate_type', 'high_speed_recip')
            _dr = calculate_site_derate(site_temp_c, site_alt_m, methane_number,
                                         derate_type=_sb_derate_type)
            st.info(
                f"**Derate Factor: {_dr['derate_factor']:.4f}**  \n"
                f"Methane: {_dr['methane_deration']:.4f} | "
                f"Altitude: {_dr['altitude_deration']:.4f} | "
                f"ACHRF: {_dr['achrf']:.4f}"
            )
            if _dr.get('methane_warning'):
                st.warning(_dr['methane_warning'])
            if _dr.get('derate_table_source') in ('typical_estimate', 'placeholder_pending'):
                _dt = _dr.get('derate_type', '')
                if _dt == 'medium_speed_recip':
                    st.warning(
                        f"⚠️ **Derate table — typical estimate.** "
                        f"The site derating for {_sb_gen} uses a conservative typical table "
                        f"for medium-speed reciprocating engines. "
                        f"Validated CAT GERP data is not yet available."
                    )
                elif _dt == 'gas_turbine':
                    st.warning(
                        f"⚠️ **Derate table — placeholder.** "
                        f"Gas turbine derate characteristics differ significantly. "
                        f"Consult CAT GERP data for {_sb_gen} before using these results."
                    )
        else:
            derate_factor_manual = st.number_input(
                "Manual Derate Factor", min_value=0.01, max_value=1.0,
                value=float(INPUT_DEFAULTS["derate_factor_manual"]), step=0.05,
                format="%.2f", help=HELP_TEXTS.get("derate_factor_manual", ""),
            )

    # ---- 7. Economics (collapsed) ----
    with st.sidebar.expander("\U0001f4b0 Economics"):
        _region_default = INPUT_DEFAULTS["region"]
        region = st.selectbox(
            "Region", REGIONS,
            index=REGIONS.index(_region_default) if _region_default in REGIONS else 0,
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

    # ---- 8. Advanced (collapsed — single expander, no nesting) ----
    with st.sidebar.expander("\u2699\ufe0f Advanced", expanded=False):

        # -- Load Dynamics --
        st.markdown("**Load Dynamics**")
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
        spinning_res_pct = st.number_input(
            "Spinning Reserve (%)", min_value=0.0, max_value=100.0,
            value=float(INPUT_DEFAULTS["spinning_res_pct"]), step=5.0,
            help=HELP_TEXTS.get("spinning_res_pct", ""),
            key="spinning_res_pct_input",
        )

        st.markdown("---")

        # -- Voltage & Electrical --
        st.markdown("**Voltage & Electrical**")
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
        # ── HV Switchgear Topology (P18) ────────────────────────────────
        _SWG_TOPOLOGY_OPTIONS = {
            "Single SWG (radial)":                    {"n_swg": 1, "normal_factor": 1.0, "contingency_factor": 1.0},
            "Dual SWG — ring / sectionalized (N-1)":  {"n_swg": 2, "normal_factor": 0.5, "contingency_factor": 1.0},
            "Double bus / double breaker":             {"n_swg": 2, "normal_factor": 0.5, "contingency_factor": 1.0},
        }
        swg_topology = st.selectbox(
            "HV SWG Architecture",
            options=list(_SWG_TOPOLOGY_OPTIONS.keys()),
            index=1,  # default: Dual SWG ring/sectionalized
            key="_swg_topology",
            help=(
                "Defines how many HV switchgear panels share the generator output. "
                "Dual SWG (ring/sectionalized): normal operation at 50% each; "
                "N-1 contingency requires surviving SWG to carry 100% of load. "
                "Bus and breakers are rated for the N-1 condition. "
                "Single SWG: bus always carries 100% — more conservative sizing."
            ),
        )
        dist_loss_pct = st.number_input(
            "Distribution Losses (%)", min_value=0.0, max_value=10.0,
            value=float(INPUT_DEFAULTS["dist_loss_pct"]), step=0.5,
            help=HELP_TEXTS.get("dist_loss_pct", ""),
        )
        _cooling_opts = ["Air-Cooled", "Water-Cooled"]
        _cooling_default = INPUT_DEFAULTS.get("cooling_method", "Air-Cooled")
        cooling_method = st.radio(
            "Cooling Method", _cooling_opts,
            index=_cooling_opts.index(_cooling_default) if _cooling_default in _cooling_opts else 0,
            horizontal=True,
            help=HELP_TEXTS.get("cooling_method", ""),
        )
        _bt_opts = ["closed", "open"]
        _bt_default = INPUT_DEFAULTS["bus_tie_mode"]
        bus_tie_mode = st.radio(
            "Bus-Tie Mode", _bt_opts,
            index=_bt_opts.index(_bt_default) if _bt_default in _bt_opts else 0,
            horizontal=True,
            help=HELP_TEXTS.get("bus_tie_mode", ""),
            format_func=lambda x: "Closed (Ring Bus)" if x == "closed" else "Open (Independent)",
        )
        # Initialize _elec_path_avail from bus_tie_mode if Reliability tab hasn't set it yet
        if "_elec_path_avail" not in st.session_state:
            from core.engine import get_electrical_path_factor as _get_epf
            st.session_state["_elec_path_avail"] = _get_epf(bus_tie_mode)
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

        st.markdown("---")

        # -- Fuel & LNG --
        st.markdown("**Fuel & LNG**")
        _fuel_default = INPUT_DEFAULTS["fuel_mode"]
        fuel_mode = st.radio(
            "Fuel Supply", FUEL_MODES,
            index=FUEL_MODES.index(_fuel_default) if _fuel_default in FUEL_MODES else 0,
            horizontal=True,
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

        st.markdown("---")

        # -- Generator Overrides --
        st.markdown("**Generator Overrides**")
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
            value=float(gen_data_params.get('unit_availability', 0.965) * 100),
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

        lib_avail = gen_data_params.get('unit_availability', 0.965)
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

        st.markdown("---")

        # -- BESS Costs --
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

        st.markdown("---")

        # -- Emissions & Noise --
        st.markdown("**Emissions & Noise**")
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

        st.markdown("---")

        # -- CHP / Tri-Gen --
        st.markdown("**CHP / Tri-Gen**")
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
        else:
            st.caption("Enable CHP in Generator & BESS section to configure details.")

        st.markdown("---")

        # -- Phasing --
        st.markdown("**Phasing**")
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

        st.markdown("---")

        # -- Infrastructure --
        st.markdown("**Infrastructure**")
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

        st.markdown("---")

        # -- Footprint --
        st.markdown("**Footprint**")
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

        st.markdown("---")

        # -- GERP PDF Import --
        st.markdown("**GERP PDF Import**")
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
        bess_autonomy_min=bess_autonomy_min,
        bess_dod=bess_dod,
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
        # CAPEX BOS adders (P08 Fix 6)
        bos_pct=bos_pct,
        civil_pct=civil_pct,
        fuel_system_pct=fuel_system_pct,
        epc_pct=epc_pct,
        contingency_pct=contingency_pct,
        # Electrical bus topology (P24a)
        bus_tie_mode=bus_tie_mode,
    )

    # ── Proposal Information (commercial fields for DOCX generation) ──
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

    _epf = st.session_state.get('_elec_path_avail', 0.9950)
    if _epf and _epf < 1.0 and r.system_availability:
        st.caption(
            f"System availability includes electrical path factor "
            f"{_epf:.4f} (breakers, MV bus, transformer, cables — "
            f"IEEE 493 lumped model). Generator-only availability: "
            f"{r.system_availability / _epf * 100:.4f}%"
        )

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
        # Non-validated derate table warning in summary
        if getattr(r, 'derate_table_source', None) in ('typical_estimate', 'placeholder_pending'):
            _dts = getattr(r, 'derate_type', '')
            if _dts == 'medium_speed_recip':
                st.caption("⚠️ Derate uses typical estimate — OEM data pending")
            elif _dts == 'gas_turbine':
                st.caption("⚠️ Derate uses placeholder table — consult CAT GERP")
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

    # ---- Spinning Reserve Advisory ----
    sr_required = r.spinning_reserve_mw
    sr_available = r.spinning_from_gens + r.spinning_from_bess
    sr_deficit = sr_required - sr_available

    if sr_deficit > 0:
        import math
        additional_gens = 0
        if r.unit_site_cap > 0:
            additional_gens = math.ceil(sr_deficit / r.unit_site_cap)

        st.warning(
            f"⚠️ **Spinning Reserve Shortfall: {sr_deficit:.1f} MW**\n\n"
            f"Required: {sr_required:.1f} MW | Available: {sr_available:.1f} MW "
            f"(Generators: {r.spinning_from_gens:.1f} MW + BESS: {r.spinning_from_bess:.1f} MW)\n\n"
            f"**Options to resolve:**\n"
            f"1. **Enable or increase BESS** — add {sr_deficit:.1f} MW of BESS power to cover the deficit\n"
            f"2. **Add ~{additional_gens} generator(s)** — increases fleet headroom by "
            f"~{additional_gens * r.unit_site_cap:.1f} MW\n"
            f"3. **Increase BESS autonomy** — if BESS is already enabled, increasing autonomy "
            f"may improve spinning reserve contribution"
        )
    elif hasattr(r, 'headroom_mw') and r.headroom_mw > 0:
        sr_margin = sr_available - sr_required
        if sr_margin > 0 and sr_required > 0:
            margin_pct = (sr_margin / sr_required) * 100
            if margin_pct < 20:
                st.info(
                    f"ℹ️ Spinning Reserve meets requirements with a thin margin: "
                    f"{sr_available:.1f} MW available vs {sr_required:.1f} MW required "
                    f"({margin_pct:.0f}% margin). Consider BESS to increase reserve."
                )


# =============================================================================
# TAB 2: RELIABILITY
# =============================================================================
def render_reliability_tab(r):
    """Spinning reserve visualization and reliability configuration comparison."""

    # ---- Pod Architecture (if applicable) ----
    # Read from selected maintenance config if one is active, else from r
    _sel_cfg_key = st.session_state.get('fleet_maint_config_sel', None)
    _maint_cfgs  = getattr(r, 'fleet_maintenance_configs', {}) or {}
    _active_mc   = _maint_cfgs.get(_sel_cfg_key) if _sel_cfg_key and _maint_cfgs else None

    if _active_mc:
        _n_pods    = _active_mc.get('n_pods',    getattr(r, 'n_pods', 0))
        _n_per     = _active_mc.get('n_per_pod', getattr(r, 'n_per_pod', 0))
        _n_tot     = _active_mc.get('n_total',   r.n_total)
        _load_norm = _active_mc.get('loading_normal_pct', getattr(r, 'loading_normal_pct', 0))
        _load_cont = _active_mc.get('loading_contingency_pct', getattr(r, 'loading_contingency_pct', 0))
        _cap_cont  = _active_mc.get('cap_combined', (_n_pods - 1) * _n_per * r.unit_site_cap)
    else:
        _n_pods    = getattr(r, 'n_pods', 0)
        _n_per     = getattr(r, 'n_per_pod', 0)
        _n_tot     = r.n_total
        _load_norm = getattr(r, 'loading_normal_pct', 0)
        _load_cont = getattr(r, 'loading_contingency_pct', 0)
        _cap_cont  = getattr(r, 'cap_contingency', (_n_pods - 1) * _n_per * r.unit_site_cap if _n_pods > 0 else 0)

    if _n_pods > 0:
        st.subheader("Pod Architecture")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Number of Pods",        f"{_n_pods}")
        c2.metric("Generators / Pod",      f"{_n_per}")
        c3.metric("Normal Loading",        f"{_load_norm:.1f}%")
        c4.metric("Contingency Loading",   f"{_load_cont:.1f}%")

        st.caption(
            f"All {_n_tot} generators operate simultaneously across {_n_pods} pods. "
            f"**N+1 pod redundancy:** loss of any single pod ({_n_per} gens, "
            f"{_n_per * r.unit_site_cap:.1f} MW) leaves {_cap_cont:.1f} MW "
            f"available at {_load_cont:.1f}% loading. "
            f"Normal loading {_load_norm:.1f}% ≤ prime/standby ratio — "
            f"thermal margin maintained in all operating conditions."
        )
        if _active_mc:
            st.info(f"**Active: Config {_sel_cfg_key}** — maintenance-aware architecture applied.")
        st.divider()

    # ---- Sizing Input Variables Reference ----
    st.subheader("Sizing Input Variables")
    st.caption(
        "Reference table showing all key variables used in the reliability and fleet "
        "sizing calculations. To adjust any value, use the sidebar controls."
    )

    _site_temp = st.session_state.get("_site_temp", 35)
    _site_alt  = st.session_state.get("_site_alt", 100)
    _mn        = st.session_state.get("_mn", 80)
    _dist_loss = st.session_state.get("_dist_loss_pct", 2.0)

    _sv_gen_data   = GENERATOR_LIBRARY.get(r.selected_gen, {})
    _sv_unit_avail = _sv_gen_data.get("unit_availability", 0.965)
    _sv_aux_load   = _sv_gen_data.get("aux_load_pct", 4.0)
    _sv_epf        = r.electrical_path_factor if hasattr(r, 'electrical_path_factor') else 0.999999

    import pandas as pd  # noqa: E402 — needed here: pd is also imported locally later in the function, making it a local variable in Python's scope analysis
    _sv_col_left, _sv_col_right = st.columns(2)

    with _sv_col_left:
        st.markdown("**Generator & Fleet**")
        _sv_gen_vars = {
            "Generator Model":       r.selected_gen,
            "ISO Rating":            f"{r.unit_iso_cap:.2f} MW",
            "Site Rating (Derated)": f"{r.unit_site_cap:.2f} MW",
            "Derate Factor":         f"{r.derate_factor:.4f}",
            "Unit Availability":     f"{_sv_unit_avail * 100:.1f}%",
            "Electrical Efficiency": f"{r.fleet_efficiency * 100:.1f}%",
            "Aux Load":              f"{_sv_aux_load:.1f}%",
            "Fleet Size":            f"{r.n_running} running + {r.n_reserve} reserve = {r.n_total}",
        }
        st.table(pd.DataFrame(
            [{"Parameter": k, "Value": v} for k, v in _sv_gen_vars.items()]
        ).set_index("Parameter"))

    with _sv_col_right:
        st.markdown("**Site & System**")
        _sv_site_vars = {
            "Ambient Temperature": f"{_site_temp:.0f} \u00b0C",
            "Site Altitude":       f"{_site_alt:.0f} m",
            "Methane Number":      f"{_mn}",
            "Capacity Factor":     f"{r.capacity_factor:.2f}",
            "PUE":                 f"{r.pue:.2f}",
            "Distribution Losses": f"{_dist_loss:.1f}%",
            "Spinning Reserve":    (
                f"{r.spinning_reserve_mw:.2f} MW "
                f"({r.spinning_reserve_mw / r.p_total_dc * 100:.1f}%)"
                if r.p_total_dc > 0 else "N/A"
            ),
            "Electrical Path Factor": f"{_sv_epf * 100:.6f}%",
            "System Availability":    f"{r.system_availability * 100:.4f}%",
        }
        st.table(pd.DataFrame(
            [{"Parameter": k, "Value": v} for k, v in _sv_site_vars.items()]
        ).set_index("Parameter"))

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

    # ── Fleet Configuration (P32 — single optimal config) ──
    st.divider()
    st.subheader("Fleet Configuration")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Running Units", r.n_running)
    col2.metric("Reserve Units", r.n_reserve)
    col3.metric("Total Fleet", r.n_total)
    col4.metric("Installed Capacity", f"{r.installed_cap:.1f} MW")

    col5, col6, col7 = st.columns(3)
    col5.metric("Load per Unit", f"{r.load_per_unit_pct:.1f}%")
    col6.metric("Fleet Efficiency", f"{r.fleet_efficiency * 100:.1f}%")
    col7.metric("System Availability", f"{r.system_availability * 100:.4f}%")

    avail_target = getattr(r, 'avail_req', 99.98) if hasattr(r, 'avail_req') else 99.98
    if r.system_availability * 100 >= avail_target:
        st.success("Fleet meets availability target.")
    else:
        st.warning("Fleet does not meet availability target. Consider increasing reserve units.")

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
        cfg_bess_cost = (cfg.bess_mwh / r.bess_energy_mwh * (r.capex_breakdown or {}).get('bess', 0)) if r.bess_energy_mwh > 0 else 0
        cfg_capex_m = (cfg_gen_cost + cfg_bess_cost) / 1e6

        # r.n_pods updates after Apply & Re-run; derive per-config n_per
        _n_pods_d = r.n_pods if (hasattr(r, 'n_pods') and r.n_pods and r.n_pods > 0) else 1
        _n_per_d  = round(cfg.n_total / _n_pods_d) if _n_pods_d > 0 else cfg.n_total
        configs_data.append({
            "Configuration": cfg.name,
            "Fleet": f"{_n_pods_d}p×{_n_per_d}",
            "Total": cfg.n_total,
            "BESS (MW/MWh)": f"{cfg.bess_mw:.0f}/{cfg.bess_mwh:.0f}" if cfg.bess_mw > 0 else "None",
            "BESS Credit": f"{cfg.bess_credit:.1f}",
            "Spin. BESS": f"{cfg.spinning_from_bess:.1f} MW" if cfg.spinning_from_bess > 0 else "-",
            "Load (%)": f"{cfg.load_pct:.1f}",
            "Eff. (%)": f"{cfg.efficiency * 100:.1f}",
            "Avail. (%)": f"{cfg.availability * 100:.4f}",
            "CAPEX ($M)": f"${cfg_capex_m:.1f}",
        })

    if configs_data:
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
    else:
        st.info("No reliability configurations available.")

    # ── Electrical Path Availability & Uptime Tier (IEEE 493-2007) ────────
    st.divider()
    st.subheader("System Availability — Electrical Path & Uptime Classification")

    import pandas as pd
    import math as _math
    from core.engine import _binomial_availability

    # --- Topology selector (IEEE 493 calculated, not hardcoded) ---
    _topo_options = list(_ELEC_TOPOLOGY_OPTIONS.keys())
    _topo_default = "Ring bus / sectionalized (N-1)"
    _topo_idx     = _topo_options.index(_topo_default)

    selected_topology = st.selectbox(
        "HV Bus Topology",
        options=_topo_options,
        index=_topo_idx,
        key="_elec_bus_topology",
        help=(
            "Electrical bus architecture connecting generators to the facility load. "
            "Determines the redundancy level and fault tolerance of the distribution system. "
            "Source: IEEE 493-2007 (Gold Book) — Recommended Practice for "
            "the Design of Reliable Industrial and Commercial Power Systems."
        ),
    )

    _topo_info = _ELEC_TOPOLOGY_OPTIONS[selected_topology]
    st.caption(f"**{selected_topology}:** {_topo_info['description']}")
    st.caption(f"Typical use: {_topo_info['typical_use']}")

    # Calculate electrical path factor from IEEE 493
    epf = _ieee493_elec_path(selected_topology)
    st.session_state["_elec_path_avail"] = epf

    # --- Fleet-only vs Combined availability ---
    a_gen_active = getattr(r, 'a_gen_derived', 0.965)
    n_total = getattr(r, 'n_total', 0)
    _unit_cap = getattr(r, 'unit_site_cap', 1.0) or 1.0
    _p_peak   = getattr(r, 'p_total_peak', 0)
    n_required = _math.ceil(_p_peak / _unit_cap) if _unit_cap > 0 and _p_peak > 0 else n_total

    if n_total > 0 and n_required > 0:
        a_fleet = _binomial_availability(n_total, n_required, a_gen_active)
    else:
        a_fleet = getattr(r, 'system_availability', 0.99) / epf

    a_combined = a_fleet * epf

    # Display metrics
    col_f, col_e, col_c = st.columns(3)
    col_f.metric(
        "Fleet Only", f"{a_fleet * 100:.4f}%",
        help=f"P(X >= {n_required} | n={n_total}, p={a_gen_active:.3f}) — binomial CDF.",
    )
    col_e.metric(
        "Elec. Path (IEEE 493)", f"{epf * 100:.6f}%",
        help=(
            f"Topology: {selected_topology}. "
            f"Component data: MV breakers lambda=0.0027 f/yr, MTTR=83.1 hr; "
            f"bus duct lambda=0.0024; MV cable lambda=0.0083. "
            f"Transformers excluded (counted in fleet model)."
        ),
    )
    col_c.metric(
        "Combined System", f"{a_combined * 100:.4f}%",
        help="Fleet Only x Electrical Path Factor.",
    )

    # Downtime equivalents
    dt_fleet    = (1 - a_fleet)    * 8760
    dt_elec     = (1 - epf)        * 8760
    dt_combined = (1 - a_combined) * 8760

    st.caption(
        f"**Downtime equivalents:** "
        f"Fleet: {_fmt_downtime(dt_fleet)} | "
        f"Elec. path: {_fmt_downtime(dt_elec)} | "
        f"Combined: {_fmt_downtime(dt_combined)}"
    )

    # IEEE 493 component breakdown expander
    with st.expander("IEEE 493-2007 Component Data (source for electrical path factor)"):
        st.markdown(
            "Failure rates and MTTR from **IEEE 493-2007, Table 3-4** — "
            "*Recommended Practice for the Design of Reliable Industrial and "
            "Commercial Power Systems (Gold Book)*."
        )
        _comp_data = {
            "Component": [
                "MV circuit breaker (metal-clad)",
                "Bus duct (per 100 ft section)",
                "MV cable (per 1,000 ft)",
                "Power transformer >500 kVA *",
            ],
            "failures/yr": ["0.0027", "0.0024", "0.0083", "0.0062"],
            "MTTR (hours)":    ["83.1",   "35.0",   "15.7",   "341.7"],
            "U = lam x MTTR/8760": [
                f"{0.0027*83.1/8760:.2e}",
                f"{0.0024*35.0/8760:.2e}",
                f"{0.0083*15.7/8760:.2e}",
                f"{0.0062*341.7/8760:.2e} *",
            ],
        }
        st.table(pd.DataFrame(_comp_data).set_index("Component"))
        st.caption(
            "\\* Transformer unavailability is **not included** in the electrical path factor "
            "because transformer failure affects generator availability (already modeled "
            "in the fleet binomial calculation). Including it here would double-count."
        )
        st.caption(
            f"**Topology: {selected_topology}** — "
            + ("Single series path: A = 1 - U_section."
               if "Radial" in selected_topology
               else "Parallel redundant paths: A = 1 - U_section^2. Both sections must "
                    "fail simultaneously for a bus outage.")
        )

    st.divider()

    # --- Uptime Tier Classification ---
    st.subheader("Uptime Institute Tier Classification")

    downtime_hr  = (1 - a_combined) * 8760
    downtime_min = downtime_hr * 60

    _TIERS = [
        ("Tier I -- Basic",              99.671,  28.8),
        ("Tier II -- Redundant",         99.741,  22.0),
        ("Tier III -- Concurrently Maint.", 99.982, 1.6),
        ("Tier IV -- Fault Tolerant",    99.995,  0.4),
    ]

    tier_data = []
    achieved = "Below Tier I"
    for label, pct, max_down_hr in _TIERS:
        met = "Yes" if a_combined * 100 >= pct else "No"
        if a_combined * 100 >= pct:
            achieved = label
        tier_data.append({
            'Tier': label,
            'Req Avail (%)': f"{pct:.3f}%",
            'Max Downtime/yr': f"{max_down_hr:.1f} hr",
            'Met?': met,
        })

    st.dataframe(pd.DataFrame(tier_data), use_container_width=True, hide_index=True)
    st.info(f"**Achieved:** {achieved} — Projected downtime: {_fmt_downtime(downtime_hr)}")

    # --- a_gen Sensitivity Table ---
    st.markdown("---")
    st.subheader("Generator Availability Sensitivity")

    a_gen_range = [0.920, 0.930, 0.940, 0.950, 0.960, 0.965, 0.970, 0.975, 0.980, 0.985, 0.990]
    sens_data = []
    for ag in a_gen_range:
        if n_total > 0 and n_required > 0:
            af = _binomial_availability(n_total, n_required, ag)
        else:
            af = ag ** 10
        ac = af * epf
        marker = " <" if abs(ag - a_gen_active) < 0.001 else ""
        dt_hr = (1 - ac) * 8760
        sens_data.append({
            'a_gen': f"{ag:.3f}{marker}",
            'Fleet Avail (%)': f"{af * 100:.4f}%",
            'Combined (%)': f"{ac * 100:.4f}%",
            'Downtime (hr/yr)': f"{dt_hr:.4f}",
        })

    st.dataframe(pd.DataFrame(sens_data), use_container_width=True, hide_index=True)
    st.caption(
        f"Fleet: {n_total} total generators, {n_required} required. "
        f"Active a_gen = {a_gen_active:.3f} (marked with <). "
        f"Electrical path: {selected_topology}, A = {epf:.10f}."
    )



# =============================================================================
# TAB 3: BESS
# =============================================================================
def render_bess_tab(r):
    """BESS sizing breakdown and function checklist."""

    if not r.use_bess:
        st.info("BESS is disabled for this configuration.")
        return

    # ── BESS Autonomy Control ─────────────────────────────────────────────
    st.subheader("BESS Autonomy")

    _auto_min_calc  = getattr(r, 'bess_autonomy_min', 10.0) or 10.0
    _auto_basis     = getattr(r, 'bess_autonomy_min_basis', '')

    st.info(
        f"**BESS Autonomy: {_auto_min_calc:.0f} minutes** "
        + (f"({_auto_basis})" if _auto_basis else
           f"(transient support + spinning reserve coverage)") +
        "  \nYou may increase autonomy via the sidebar for additional resilience. "
        "Reducing below the spinning reserve obligation window will trigger a warning."
    )

    _c1, _c2, _c3 = st.columns(3)
    _c1.metric(
        "Configured Autonomy",
        f"{_auto_min_calc:.0f} min",
        help="BESS autonomy configured by the user (sidebar).",
    )
    _c2.metric(
        "Calculated Energy",
        f"{r.bess_energy_mwh:.2f} MWh",
        help="BESS energy at the minimum required autonomy.",
    )
    _c3.metric(
        "Calculated Power",
        f"{r.bess_power_mw:.2f} MW",
        help="BESS rated power for this strategy.",
    )

    # Override input
    _override_key = "_bess_autonomy_override_min"
    _current_override = st.session_state.get(_override_key, float(_auto_min_calc))

    bess_autonomy_override = st.number_input(
        "Override Autonomy (minutes)",
        min_value=0.5,
        max_value=240.0,
        value=_current_override,
        step=1.0,
        format="%.0f",
        key=_override_key,
        help=(
            "Override the configured autonomy. Values above the current setting add resilience "
            "and increase BESS energy proportionally. "
            f"Values below {_auto_min_calc:.0f} min will trigger a warning."
        ),
    )

    # Warning if override is below configured minimum
    if bess_autonomy_override < _auto_min_calc * 0.999:  # 0.1% tolerance
        st.warning(
            f"⚠️ **Autonomy below configured minimum.** "
            f"The design requires at least **{_auto_min_calc:.0f} minutes** "
            f"to fulfill its spinning reserve obligation. "
            f"With {bess_autonomy_override:.0f} minutes, the BESS may not bridge a "
            f"generator start-up event or maintain frequency during a contingency. "
            f"**Increase autonomy before finalizing the design.**"
        )
    elif bess_autonomy_override > _auto_min_calc * 1.001:
        # Show what the override means in MWh
        _dod = getattr(r, 'bess_dod', 0.85) or 0.85
        _override_energy = r.bess_power_mw * (bess_autonomy_override / 60) / _dod
        _delta_energy    = _override_energy - r.bess_energy_mwh
        st.success(
            f"✅ Override accepted: {bess_autonomy_override:.0f} min "
            f"→ **{_override_energy:.2f} MWh** "
            f"(+{_delta_energy:.2f} MWh vs. minimum). "
            f"Re-run sizing to update CAPEX and LCOE with the new BESS energy."
        )
        # Show re-run button if override differs from current result
        if abs(_override_energy - r.bess_energy_mwh) > 0.01:
            if st.button(
                f"▶ Re-run with {bess_autonomy_override:.0f} min autonomy",
                key="_bess_rerun_autonomy",
                type="primary",
            ):
                st.session_state["_stored_bess_autonomy_min"] = bess_autonomy_override
                st.rerun()

    st.divider()

    # ── BESS Sizing Breakdown ─────────────────────────────────────────────
    st.subheader("BESS Sizing Breakdown")

    c1, c2 = st.columns(2)
    c1.metric("Total Power", f"{r.bess_power_mw:.2f} MW")
    c2.metric("Total Energy", f"{r.bess_energy_mwh:.2f} MWh")

    # Autonomy formula caption (P13)
    autonomy_min = getattr(r, 'bess_autonomy_min', 10.0) or 10.0
    dod = getattr(r, 'bess_dod', 0.85) or 0.85
    st.caption(
        f"Energy = {r.bess_power_mw:.1f} MW × {autonomy_min:.1f} min ÷ 60 ÷ {dod:.2f} DoD"
        f" = {r.bess_energy_mwh:.2f} MWh"
    )

    st.markdown(f"**BESS Autonomy:** {getattr(r, 'bess_autonomy_min', 10):.0f} minutes")

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
        ("Peak Shaving", r.use_bess),
        ("Frequency Regulation Support", r.bess_power_mw > 0),
        ("Reliability Credit (N+X reduction)", r.spinning_from_bess > 0),
    ]

    for func_name, func_active in bess_functions:
        icon = "\u2705" if func_active else "\u2b1c"
        st.markdown(f"{icon} {func_name}")


# =============================================================================
# TAB 4: ELECTRICAL
# =============================================================================
def render_electrical_tab(r):
    """Voltage, efficiency, heat rate, frequency screening, and stability."""

    # ── Pod Architecture Banner ──────────────────────────────────────────────
    n_pods   = getattr(r, 'n_pods',   None)
    n_per    = getattr(r, 'n_per_pod', None)
    n_total  = getattr(r, 'n_total',  None)
    n_trafos = getattr(r, 'n_trafos', None)
    p_inst   = getattr(r, 'installed_cap', None)
    loading  = getattr(r, 'loading_normal_pct', None)
    if n_pods and n_per and n_total:
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Pod Architecture",   f"{n_pods} pods × {n_per} gens")
        col2.metric("Total Generators",   f"{n_total}")
        col3.metric("P Installed",        f"{p_inst:.1f} MW" if p_inst else "—")
        col4.metric("Normal Loading",     f"{loading:.1f}%" if loading else "—")
        col5.metric("Transformers",       f"{n_trafos}" if n_trafos else "—")

        st.divider()

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

    # SR advisory
    sr_available = r.spinning_from_gens + r.spinning_from_bess
    sr_deficit = r.spinning_reserve_mw - sr_available
    if sr_deficit > 0:
        st.error(
            f"Spinning Reserve deficit: {sr_deficit:.1f} MW. "
            f"Enable BESS or add generators to cover the shortfall."
        )
    else:
        st.success(
            f"Spinning Reserve satisfied: {sr_available:.1f} MW available "
            f"({sr_available - r.spinning_reserve_mw:.1f} MW margin)."
        )

    # ── HV Switchgear Bus Sizing — N-1 Corrected (P18) ──────────────────
    import math as _math

    swg_topology = st.session_state.get('_swg_topology', 'Dual SWG — ring / sectionalized (N-1)')
    _SWG_TOPOLOGY_OPTIONS = {
        "Single SWG (radial)":                    {"n_swg": 1, "normal_factor": 1.0, "contingency_factor": 1.0},
        "Dual SWG — ring / sectionalized (N-1)":  {"n_swg": 2, "normal_factor": 0.5, "contingency_factor": 1.0},
        "Double bus / double breaker":             {"n_swg": 2, "normal_factor": 0.5, "contingency_factor": 1.0},
    }
    _swg_cfg = _SWG_TOPOLOGY_OPTIONS.get(swg_topology, {"n_swg": 2, "normal_factor": 0.5, "contingency_factor": 1.0})
    n_swg              = _swg_cfg["n_swg"]
    normal_factor      = _swg_cfg["normal_factor"]
    contingency_factor = _swg_cfg["contingency_factor"]

    # ── 52T5 Bus-Tie Operating Mode (only relevant for dual SWG) ─────────
    if _swg_cfg["n_swg"] > 1:
        tie_mode = st.radio(
            "52T5 Bus-Tie Breaker — Normal State",
            options=[
                "Normally Open (NO) — Standard CAT practice",
                "Normally Closed (NC) — Ring bus, continuous paralleling",
            ],
            index=0,   # default: NO — matches all CAT Switchgear one-line diagrams
            key="_tie_breaker_mode",
            horizontal=True,
            help=(
                "52T5 is the bus sectionalizing breaker between SWGR-A and SWGR-B. "
                "Normally Open (NO): each bus section operates independently in normal "
                "conditions. On N-1, 52T5 closes to transfer load — lower normal ISC. "
                "Normally Closed (NC): both sections in continuous parallel — maximum ISC "
                "on any fault, highest breaker rating required. "
                "All CAT Switchgear data center one-lines use the NO configuration."
            ),
        )
        _tie_is_NO = "Normally Open" in tie_mode
    else:
        _tie_is_NO = True   # single SWG — no tie breaker
        tie_mode   = "N/A"

    v_kv        = r.rec_voltage_kv
    p_total_mw  = r.p_total_peak
    pf          = 0.8
    _n_pods     = getattr(r, 'n_pods', None)
    _n_trafos   = getattr(r, 'n_trafos', None)

    I_total_a        = (p_total_mw * 1e6) / (_math.sqrt(3) * v_kv * 1000 * pf)
    I_normal_a       = I_total_a * normal_factor
    I_contingency_a  = I_total_a * contingency_factor

    _BUS_RATINGS_A = [800, 1200, 1600, 2000, 2500, 3000, 4000, 5000, 6000]
    bus_rating_a   = next((br for br in _BUS_RATINGS_A if br >= I_contingency_a * 1.1), _BUS_RATINGS_A[-1])

    I_tie_breaker_a = I_contingency_a if n_swg > 1 else 0.0

    # ── Short Circuit Current — mode-dependent ───────────────────────────
    # k_sc = subtransient short circuit factor for high-speed recip gas engines
    # Based on typical X"d = 15-20% → k_sc ≈ 5-7. Conservative value = 6.5
    k_sc   = 6.5
    k_asym = 1.6   # IEC 60909 first-cycle asymmetric factor (X/R ≈ 15-20)

    # Total ISC if all generators were on one bus (worst case, NC ring)
    ISC_sym_total_a  = I_total_a * k_sc
    ISC_asym_total_a = ISC_sym_total_a * k_asym

    if n_swg > 1 and _tie_is_NO:
        # 52T5 Normally Open — each section sees only its own pods' contribution
        # On close-in N-1, 52T5 closes and tie sees remote ISC through cable impedance.
        # 50% local + 30% remote attenuated through tie (conservative estimate).
        ISC_local_a  = ISC_sym_total_a * 0.50   # local section pods only
        ISC_remote_a = ISC_sym_total_a * 0.30   # remote pods attenuated through tie
        ISC_sym_a    = ISC_local_a + ISC_remote_a   # = 80% of total (NO, N-1)
        ISC_asym_a   = ISC_sym_a * k_asym
        _isc_basis   = (
            f"52T5 Normally Open: fault on one bus section sees local pods "
            f"({ISC_local_a/1000:.1f} kA) + remote pods attenuated through bus-tie "
            f"({ISC_remote_a/1000:.1f} kA). Full ISC study required for exact values."
        )
    elif n_swg > 1 and not _tie_is_NO:
        # 52T5 Normally Closed — all generators contribute to any fault
        ISC_local_a  = ISC_sym_total_a * 0.50
        ISC_remote_a = ISC_sym_total_a * 0.50
        ISC_sym_a    = ISC_sym_total_a   # 100% — all generators contribute
        ISC_asym_a   = ISC_asym_total_a
        _isc_basis   = (
            f"52T5 Normally Closed: all generators contribute to any bus fault "
            f"(max ISC = {ISC_sym_a/1000:.1f} kA symmetric). "
            f"This requires highest-rated breakers. "
            f"Consider switching to NO configuration to reduce ISC."
        )
    else:
        # Single SWG
        ISC_local_a  = ISC_sym_total_a
        ISC_remote_a = 0.0
        ISC_sym_a    = ISC_sym_total_a
        ISC_asym_a   = ISC_asym_total_a
        _isc_basis   = f"Single bus: all generators contribute directly."

    # IEC 60076 standard power transformer ratings (MVA)
    _TRAFO_RATINGS_MVA = [2.5, 5.0, 7.5, 10.0, 12.5, 15.0, 20.0, 25.0,
                           31.5, 40.0, 50.0, 63.0, 80.0]
    p_per_pod_mw    = p_total_mw / _n_pods if _n_pods else p_total_mw
    trafo_mva_each  = next((t for t in _TRAFO_RATINGS_MVA if t >= p_per_pod_mw / pf * 1.15), 30.0)
    n_trafos_calc   = _n_pods if _n_pods else _math.ceil(p_total_mw / trafo_mva_each / pf)
    trafo_total_mva = n_trafos_calc * trafo_mva_each

    st.divider()
    st.subheader(f"HV Switchgear Bus Sizing — {v_kv:.1f} kV")

    if n_swg > 1:
        st.info(
            f"**Architecture: {swg_topology}** — {n_swg} SWG panels in service. "
            f"Normal operation: each SWG carries **{normal_factor*100:.0f}% of load "
            f"({I_normal_a:,.0f} A)**. "
            f"N-1 contingency (one SWG faults): surviving SWG carries **100% of load "
            f"({I_contingency_a:,.0f} A)**. "
            f"**Bus and breakers are rated for the N-1 condition.** "
            f"Bus-tie breaker (52T5) {'closes automatically on N-1 to transfer load' if _tie_is_NO else 'is normally closed — continuous paralleling'}."
        )
    else:
        st.info(
            f"**Architecture: {swg_topology}** — single SWG, all load on one bus. "
            f"Bus rated for total continuous current ({I_normal_a:,.0f} A)."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Normal Current (per SWG)",
        f"{I_normal_a:,.0f} A",
        help=f"Current per SWG in normal operation ({normal_factor*100:.0f}% of total load).",
    )
    c2.metric(
        "N-1 Contingency Current",
        f"{I_contingency_a:,.0f} A",
        help="Current in surviving SWG when one SWG is out of service. This is the bus sizing basis.",
    )
    c3.metric(
        "Bus Rating (standard)",
        f"{bus_rating_a:,.0f} A",
        help=f"Next standard bus rating above N-1 current with 10% margin. Basis: N-1 contingency.",
    )
    c4.metric(
        "Step-up Transformers",
        f"{n_trafos_calc} × {trafo_mva_each:.1f} MVA",
        help=f"Total installed: {trafo_total_mva:.0f} MVA. One transformer per pod stepping up to {v_kv:.1f} kV.",
    )

    st.divider()
    st.subheader("Short Circuit Analysis — HV SWG")
    st.caption(
        f"Basis: IEC 60909. Generator subtransient factor k_sc = {k_sc}. "
        f"Asymmetric multiplier k_asym = {k_asym} (X/R ≈ 15–20). "
        + ("Split model: fault on one SWG bus receives local + attenuated remote contribution. " if n_swg > 1 else "") +
        "Full ISC study required before equipment procurement."
    )

    if n_swg > 1:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("ISC Local Contribution",   f"{ISC_local_a/1000:.1f} kA",
                  help="Generators directly connected to the faulted SWG bus.")
        c2.metric("ISC Remote Contribution",  f"{ISC_remote_a/1000:.1f} kA",
                  help="Generators on the other SWG, connected through the bus-tie cable. Attenuated by tie impedance.")
        c3.metric("ISC Total (symmetric)",    f"{ISC_sym_a/1000:.1f} kA",
                  help="Conservative: sum of local + remote (ignores tie impedance attenuation).")
        c4.metric("ISC Asymmetric (1st cycle)", f"{ISC_asym_a/1000:.1f} kA",
                  help="First-cycle asymmetric fault current. Basis for breaker interrupting rating.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("ISC Symmetric",    f"{ISC_sym_a/1000:.1f} kA")
        c2.metric("ISC Asymmetric",   f"{ISC_asym_a/1000:.1f} kA",
                  help="First-cycle. Basis for breaker interrupting rating.")

    st.caption(f"**ISC basis:** {_isc_basis}")

    # IEC 62271-100 and ANSI/IEEE C37.06 standard interrupting ratings (kA)
    # 80–125 kA are special-order equipment — flag in UI if selected
    _BREAKER_RATINGS_KA = [16, 20, 25, 31.5, 40, 50, 63, 80, 100, 125]
    _BREAKER_SPECIAL_ORDER_KA = 80  # ratings >= this value are long-lead special order
    breaker_rating_ka = next((b for b in _BREAKER_RATINGS_KA if b >= ISC_asym_a/1000 * 1.1), _BREAKER_RATINGS_KA[-1])
    _breaker_is_special = breaker_rating_ka >= _BREAKER_SPECIAL_ORDER_KA
    _breaker_at_max     = breaker_rating_ka == _BREAKER_RATINGS_KA[-1] and \
                          ISC_asym_a / 1000 * 1.1 > _BREAKER_RATINGS_KA[-1]

    st.divider()
    st.subheader("Equipment Recommendations")

    eq_data = {
        "Equipment": [
            f"Generator incomer breaker ({v_kv:.1f} kV)",
            "Bus bar rating",
            f"Bus-tie breaker 52T5 ({v_kv:.1f} kV)" if n_swg > 1 else "—",
            f"Step-up transformer ({n_trafos_calc} units)",
            "Current-limiting reactor (optional)",
        ],
        "Basis": [
            "N-1 contingency current + 10% margin",
            "N-1 contingency + ISC withstand",
            ("N-1 transfer current + close-in ISC from remote section" if _tie_is_NO else "All-generator ISC — max rating") if n_swg > 1 else "—",
            f"Pod peak output ÷ PF × 1.15 margin",
            "Reduce ISC to standard breaker range (50–63 kA)",
        ],
        "Minimum Rating": [
            f"{bus_rating_a:,.0f} A continuous / {breaker_rating_ka} kA interrupting",
            f"{bus_rating_a:,.0f} A / {ISC_asym_a/1000:.0f} kA withstand (1 s)",
            (f"{I_contingency_a:,.0f} A continuous / {breaker_rating_ka} kA interrupting "
             f"({'NO→close on N-1' if _tie_is_NO else 'NC, always closed'})") if n_swg > 1 else "—",
            f"{trafo_mva_each:.1f} MVA ONAN — {v_kv:.1f} kV / HV",
            f"Recommended if ISC_asym > 63 kA — consult application engineering"
                if ISC_asym_a/1000 > 63 else "Not required at this load level",
        ],
    }
    st.table(pd.DataFrame(eq_data).set_index("Equipment"))

    # ── Breaker rating warnings ──────────────────────────────────────────
    if _breaker_at_max:
        st.error(
            f"⛔ **ISC exceeds available standard breaker ratings.** "
            f"Calculated ISC asymmetric = {ISC_asym_a/1000:.1f} kA requires "
            f"{ISC_asym_a/1000*1.1:.0f} kA interrupting capacity with 10% margin — "
            f"above the {_BREAKER_RATINGS_KA[-1]} kA maximum in this table. "
            f"Contact CAT application engineering and the switchgear manufacturer "
            f"before proceeding. Consider: (1) splitting the generator bus into "
            f"more sections, (2) adding current-limiting reactors on generator "
            f"incomers, or (3) upgrading to a higher voltage level (34.5 kV or 69 kV) "
            f"to reduce ISC magnitude."
        )
    elif _breaker_is_special:
        st.warning(
            f"⚠️ **Special-order breaker required: {breaker_rating_ka} kA.** "
            f"Interrupting ratings ≥ {_BREAKER_SPECIAL_ORDER_KA} kA are not standard "
            f"catalog items. Expect extended lead times (typically 20–36 weeks) and "
            f"significant cost premium vs. standard ratings. "
            f"Consider current-limiting reactors on generator incomers to reduce ISC "
            f"to the 50–63 kA range. Confirm with CAT switchgear division and the "
            f"project electrical engineer before budgeting."
        )

    if n_swg > 1:
        if _tie_is_NO:
            st.warning(
                "⚠️ **Bus-tie breaker (52T5) — Automatic Bus Transfer scheme required.** "
                "With 52T5 Normally Open, the protection relay must detect loss of "
                "SWGR-A or SWGR-B de-energization and CLOSE 52T5 within 100–200 ms "
                "to restore power to the affected loads. "
                "Verify that the surviving generator fleet can absorb the full load step "
                "without frequency collapse. See **Transient Stability** tab. "
                "52T5 must be rated for the N-1 transfer current AND the close-in ISC "
                f"from the remote section ({ISC_remote_a/1000:.1f} kA through tie)."
            )
        else:
            st.warning(
                "⚠️ **52T5 Normally Closed — continuous bus paralleling.** "
                "Both sections operate in parallel at all times. "
                "Any fault is seen by ALL generators — maximum ISC applies. "
                f"Calculated ISC asymmetric = {ISC_asym_a/1000:.1f} kA. "
                "Ensure all breakers (incomers, feeders, and 52T5) are rated for "
                f"the full {ISC_asym_a/1000:.1f} kA interrupting capacity. "
                "This configuration is less common in CAT Switchgear data center designs."
            )

    st.caption(
        "All currents are calculated at peak load. "
        f"Power factor assumed = {pf}. "
        "ISC values are preliminary estimates — a formal short circuit study per IEC 60909 "
        "or ANSI/IEEE C37 is required before equipment specification and procurement."
    )

    # ---- Electrical Sizing (P08) — Detailed Model ----
    if hasattr(r, 'electrical_sizing'):
        e = r.electrical_sizing
        st.divider()
        st.subheader("MV Generator Bus — 13.8 kV (Detailed Model)")
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
# =============================================================================
# TAB: PROPOSAL
# =============================================================================
def render_proposal_tab(r):
    """Proposal document generation with exhibit selection."""

    st.subheader("Customer Proposal")
    st.markdown(
        "Generate the customer proposal document. Select which exhibits "
        "to include. CVA and ESC are always included as mandatory appendices."
    )

    st.divider()

    # ---- Mandatory Appendices (always included, shown as info) ----
    st.markdown("**Mandatory Appendices** (always included)")
    col1, col2, col3 = st.columns(3)
    col1.markdown("✅ Appendix A — Definitions")
    col2.markdown("✅ Appendix B — Extended Service Coverage (ESC)")
    col3.markdown("✅ Appendix C — Customer Value Agreement (CVA)")

    st.divider()

    # ---- Optional Exhibits (user selects via checkboxes) ----
    st.markdown("**Optional Exhibits** (select to include)")

    col1, col2 = st.columns(2)
    with col1:
        include_datasheets = st.checkbox(
            "Datasheets",
            value=True,
            help="Equipment datasheets for the selected generator model.",
            key="_exhibit_datasheets",
        )
        include_warranty = st.checkbox(
            "Warranty Statement",
            value=False,
            help="Warranty terms and conditions (dealer-specific).",
            key="_exhibit_warranty",
        )
        include_layout = st.checkbox(
            "Conceptual Layout",
            value=False,
            help="Preliminary site layout drawing.",
            key="_exhibit_layout",
        )

    with col2:
        include_scope = st.checkbox(
            "Scope of Supply Matrix",
            value=False,
            help="Detailed scope of supply breakdown.",
            key="_exhibit_scope",
        )
        include_sizing_report = st.checkbox(
            "Sizing Report (PDF)",
            value=True,
            help="Comprehensive sizing results from this tool — fleet, BESS, "
                 "electrical, financial, emissions, and all calculated parameters.",
            key="_exhibit_sizing_report",
        )
        include_additional_docs = st.checkbox(
            "Additional Technical Documents",
            value=False,
            help="Fuel analyses, engineering assumptions, or other supporting documents.",
            key="_exhibit_additional_docs",
        )

    # Build the selected exhibits list with dynamic lettering
    selected_exhibits = []
    exhibit_options = [
        ("Datasheets", include_datasheets, "Equipment datasheets for the selected generator."),
        ("Warranty Statement", include_warranty, "Dealer-specific warranty terms."),
        ("Conceptual Layout", include_layout, "Preliminary site layout."),
        ("Scope of Supply Matrix", include_scope, "Detailed scope breakdown."),
        ("Sizing Report", include_sizing_report, "Comprehensive sizing results from CAT Power Solution."),
        ("Additional Technical Documents", include_additional_docs, "Supporting technical documents."),
    ]

    for name, included, description in exhibit_options:
        if included:
            letter = chr(ord('D') + len(selected_exhibits))
            selected_exhibits.append({
                "letter": letter,
                "name": name,
                "description": description,
            })

    # Store in session state for P41B (Word generation)
    st.session_state["_proposal_exhibits"] = selected_exhibits
    st.session_state["_proposal_mandatory"] = [
        {"letter": "A", "name": "Definitions"},
        {"letter": "B", "name": "Extended Service Coverage (ESC)"},
        {"letter": "C", "name": "Customer Value Agreement (CVA)"},
    ]

    # ---- Preview: Table of Contents for Appendices ----
    st.divider()
    st.markdown("**Appendices Preview**")

    toc_items = [
        "Appendix A — Definitions",
        "Appendix B — Extended Service Coverage (ESC)",
        "Appendix C — Customer Value Agreement (CVA)",
    ]
    for exhibit in selected_exhibits:
        toc_items.append(f"Appendix {exhibit['letter']} — {exhibit['name']}")

    for item in toc_items:
        st.markdown(f"- {item}")

    # ---- Download Buttons ----
    st.divider()

    col_pdf, col_docx = st.columns(2)

    # Sizing Report PDF
    with col_pdf:
        st.markdown("**Sizing Report (PDF)**")
        try:
            pdf_data = r.model_dump()
            gen_data = GENERATOR_LIBRARY.get(r.selected_gen, {})
            pdf_data["gen_data"] = gen_data

            emissions = r.emissions or {}
            co2_tpy = emissions.get('co2_tpy', 0.0)
            nox_tpy = emissions.get('nox_tpy', 0.0)
            co_tpy  = emissions.get('co_tpy',  0.0)
            _T_TO_LB_HR = 2204.62 / 8760.0
            pdf_data['co2_ton_yr']       = round(co2_tpy, 1)
            pdf_data['nox_lb_hr']        = round(nox_tpy * _T_TO_LB_HR, 3)
            pdf_data['co_lb_hr']         = round(co_tpy  * _T_TO_LB_HR, 3)
            _carbon_price = getattr(r, 'carbon_price_per_ton', 0.0) or 0.0
            pdf_data['carbon_cost_year'] = round(co2_tpy * _carbon_price, 2)
            _capex_bd = r.capex_breakdown or {}
            pdf_data['capex_items'] = [
                {'label': k.replace('_', ' ').title(),
                 'value_m': round(float(v) / 1e6, 2) if v else 0.0}
                for k, v in _capex_bd.items()
            ]
            pdf_data['initial_capex_sum'] = getattr(r, 'total_capex', 0)
            pdf_data['selected_config'] = {
                'spinning_reserve_mw': getattr(r, 'spinning_reserve_mw', 0),
                'spinning_from_gens':  getattr(r, 'spinning_from_gens', 0),
                'spinning_from_bess':  getattr(r, 'spinning_from_bess', 0),
                'headroom_mw':         getattr(r, 'headroom_mw', 0),
            }
            pdf_data['pue_actual'] = r.pue if hasattr(r, 'pue') else r.p_total_dc / max(r.p_it, 1)
            pdf_data['n_pods']    = getattr(r, 'n_pods', None)
            pdf_data['n_per_pod'] = getattr(r, 'n_per_pod', None)

            pdf_bytes = generate_comprehensive_pdf(pdf_data)
            st.download_button(
                label=":page_facing_up: Download Sizing Report",
                data=pdf_bytes,
                file_name=f"CAT_Sizing_{r.selected_gen}_{r.p_it:.0f}MW.pdf",
                mime="application/pdf",
                type="primary",
            )
        except Exception as e:
            st.error(f"Error generating PDF: {e}")

    # Word Proposal — P41B
    with col_docx:
        st.markdown("**Customer Proposal (Word)**")

        project_info = {
            "project_name": st.session_state.get("_project_name", "Untitled Project"),
            "client_name": st.session_state.get("_client_name", ""),
            "contact_name": st.session_state.get("_contact_name", ""),
            "contact_email": st.session_state.get("_contact_email", ""),
            "contact_phone": st.session_state.get("_contact_phone", ""),
            "country": st.session_state.get("_country", ""),
            "state_province": st.session_state.get("_state_province", ""),
            "county_district": st.session_state.get("_county_district", ""),
        }

        # Get sizing PDF bytes if Sizing Report exhibit is selected
        sizing_pdf = None
        if include_sizing_report:
            try:
                pdf_data_sr = r.model_dump()
                gen_data_sr = GENERATOR_LIBRARY.get(r.selected_gen, {})
                pdf_data_sr["gen_data"] = gen_data_sr
                emissions_sr = r.emissions or {}
                co2_tpy_sr = emissions_sr.get("co2_tpy", 0.0)
                nox_tpy_sr = emissions_sr.get("nox_tpy", 0.0)
                co_tpy_sr = emissions_sr.get("co_tpy", 0.0)
                _T_TO_LB_HR_SR = 2204.62 / 8760.0
                pdf_data_sr["co2_ton_yr"] = round(co2_tpy_sr, 1)
                pdf_data_sr["nox_lb_hr"] = round(nox_tpy_sr * _T_TO_LB_HR_SR, 2)
                pdf_data_sr["co_lb_hr"] = round(co_tpy_sr * _T_TO_LB_HR_SR, 2)
                pdf_data_sr["n_pods"] = getattr(r, "n_pods", None)
                pdf_data_sr["n_per_pod"] = getattr(r, "n_per_pod", None)
                sizing_pdf = generate_comprehensive_pdf(pdf_data_sr)
            except Exception:
                sizing_pdf = None

        try:
            docx_bytes = generate_proposal_docx(
                sizing_result=r.model_dump(),
                gen_data=GENERATOR_LIBRARY.get(r.selected_gen, {}),
                project_info=project_info,
                selected_exhibits=selected_exhibits,
                sizing_pdf_bytes=sizing_pdf,
            )

            proj_name = project_info.get("project_name", "Project") or "Project"
            safe_name = proj_name.replace(" ", "_")[:30]

            st.download_button(
                label=":page_facing_up: Download Proposal (.docx)",
                data=docx_bytes,
                file_name=f"CAT_Proposal_{safe_name}_{r.selected_gen}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
            )
        except Exception as e:
            st.error(f"Error generating proposal: {e}")


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




# =============================================================================
# MAIN
# =============================================================================
def main():
    """Main app entry point — sidebar inputs, reactive sizing."""

    # Auth gate
    check_auth()

    # Initialize result
    if "result" not in st.session_state:
        st.session_state.result = None

    # Sidebar collects ALL inputs
    inputs_dict, benchmark_price = render_sidebar()

    # Store cross-tab values
    st.session_state["_benchmark_price"] = inputs_dict["benchmark_price"]
    st.session_state["_site_temp"] = inputs_dict["site_temp_c"]
    st.session_state["_site_alt"] = inputs_dict["site_alt_m"]
    st.session_state["_mn"] = inputs_dict["methane_number"]
    st.session_state["_fuel_mode"] = inputs_dict["fuel_mode"]
    st.session_state["_dist_loss_pct"] = inputs_dict["dist_loss_pct"]
    st.session_state["_include_chp"] = inputs_dict["include_chp"]
    st.session_state["_enable_phasing"] = inputs_dict["enable_phasing"]

    # Run sizing reactively
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

    # Apply electrical path derating to reported system availability
    # (IEEE 493-2007 derived — topology based, not hardcoded)
    from core.engine import get_electrical_path_factor as _get_epf
    _btm = inputs_dict.get("bus_tie_mode", "closed")
    elec_path_avail = st.session_state.get('_elec_path_avail', _get_epf(_btm))
    if hasattr(r, 'system_availability') and r.system_availability:
        r.system_availability = r.system_availability * elec_path_avail

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
    tab_labels.append(":page_facing_up: Proposal")

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

    # Tab: Proposal
    with tabs[tab_idx]:
        render_proposal_tab(r)
    tab_idx += 1


if __name__ == "__main__":
    main()
