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

from api.services.sizing_pipeline import run_full_sizing
from api.schemas.sizing import SizingInput
from core.generator_library import GENERATOR_LIBRARY, filter_by_type
from core.pdf_report import generate_comprehensive_pdf
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

BESS_STRATEGIES = ["Transient Only", "Hybrid (Balanced)", "Reliability Priority"]

REGIONS = [
    "US - Gulf Coast", "US - West Coast", "US - Northeast",
    "US - Midwest", "US - Southeast", "Canada",
    "Europe - West", "Europe - North", "Europe - South",
    "Latin America", "Middle East", "Africa",
    "Asia - Southeast", "Asia - East", "Australia",
]

GEN_TYPE_OPTIONS = ["High Speed", "Medium Speed", "Gas Turbine"]


# =============================================================================
# HELPERS
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
        if value > 1:
            return f"{value:.{decimals}f}%"
        return f"{value * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return str(value)


# =============================================================================
# SIDEBAR — INPUT SECTIONS
# =============================================================================
def render_sidebar():
    """Render all sidebar input sections. Returns a SizingInput when Run is clicked."""

    st.sidebar.markdown(
        f"### :zap: CAT Power Solution v{APP_VERSION}"
    )
    st.sidebar.caption("Prime Power Quick-Size Tool")
    st.sidebar.divider()

    # ── Template Preset ──
    template_options = ["Custom (Manual)"] + list(TEMPLATES.keys())
    template = st.sidebar.selectbox(
        "Project Template",
        template_options,
        index=0,
        help=HELP_TEXTS.get("template_choice", ""),
    )

    # If template changed, apply defaults
    if template != "Custom (Manual)":
        tpl = TEMPLATES[template]
        for k, v in tpl.items():
            if k in st.session_state:
                st.session_state[k] = v

    st.sidebar.divider()

    # ── Section 1: Load Profile ──
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
        spinning_res_pct = st.number_input(
            "Spinning Reserve (%)", min_value=0.0, max_value=100.0,
            value=float(INPUT_DEFAULTS["spinning_res_pct"]), step=5.0,
            help=HELP_TEXTS.get("spinning_res_pct", ""),
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

    # ── Section 2: Site Conditions ──
    with st.sidebar.expander(":thermometer: Site Conditions"):
        site_temp_c = st.number_input(
            "Ambient Temperature (C)", min_value=-40.0, max_value=60.0,
            value=float(INPUT_DEFAULTS["site_temp_c"]), step=1.0,
            help=HELP_TEXTS.get("site_temp_c", ""),
        )
        site_alt_m = st.number_input(
            "Site Altitude (m)", min_value=0.0, max_value=5000.0,
            value=float(INPUT_DEFAULTS["site_alt_m"]), step=50.0,
            help=HELP_TEXTS.get("site_alt_m", ""),
        )
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
        if derate_mode == "Manual":
            derate_factor_manual = st.number_input(
                "Manual Derate Factor", min_value=0.01, max_value=1.0,
                value=float(INPUT_DEFAULTS["derate_factor_manual"]), step=0.05,
                format="%.2f", help=HELP_TEXTS.get("derate_factor_manual", ""),
            )

    # ── Section 3: Technology ──
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
            "Fuel Supply", ["Pipeline Gas", "LNG"],
            index=0, horizontal=True,
            help=HELP_TEXTS.get("fuel_mode", ""),
        )
        lng_days = INPUT_DEFAULTS["lng_days"]
        if fuel_mode == "LNG":
            lng_days = st.number_input(
                "LNG Storage (days)", min_value=1, max_value=30,
                value=int(INPUT_DEFAULTS["lng_days"]), step=1,
                help=HELP_TEXTS.get("lng_days", ""),
            )

    # ── Section 4: Voltage ──
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

    # ── Section 5: Economics ──
    with st.sidebar.expander(":moneybag: Economics"):
        region = st.selectbox(
            "Region", REGIONS,
            index=REGIONS.index(INPUT_DEFAULTS["region"]),
            help=HELP_TEXTS.get("region", ""),
        )
        gas_price = st.number_input(
            "Gas Price ($/MMBtu)", min_value=0.0, max_value=50.0,
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

    # ── Section 6: Infrastructure ──
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

    # ── Section 7: Footprint ──
    with st.sidebar.expander(":world_map: Footprint"):
        enable_footprint_limit = st.checkbox(
            "Limit Site Area", value=INPUT_DEFAULTS["enable_footprint_limit"],
            help=HELP_TEXTS.get("enable_footprint_limit", ""),
        )
        max_area_m2 = INPUT_DEFAULTS["max_area_m2"]
        if enable_footprint_limit:
            max_area_m2 = st.number_input(
                "Max Area (m2)", min_value=100.0,
                value=float(INPUT_DEFAULTS["max_area_m2"]), step=500.0,
                help=HELP_TEXTS.get("max_area_m2", ""),
            )

    st.sidebar.divider()

    # ── Run Button ──
    run_clicked = st.sidebar.button(
        ":zap: Run Sizing", type="primary", use_container_width=True,
    )

    # Build inputs dict
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
        use_bess=use_bess,
        bess_strategy=bess_strategy,
        enable_black_start=enable_black_start,
        cooling_method=cooling_method,
        freq_hz=freq_hz,
        dist_loss_pct=dist_loss_pct,
        volt_mode=volt_mode,
        manual_voltage_kv=manual_voltage_kv,
        gas_price=gas_price,
        wacc=wacc,
        project_years=project_years,
        benchmark_price=benchmark_price,
        carbon_price_per_ton=carbon_price_per_ton,
        enable_depreciation=enable_depreciation,
        pipeline_cost_usd=pipeline_cost_usd,
        permitting_cost_usd=permitting_cost_usd,
        commissioning_cost_usd=commissioning_cost_usd,
        bess_cost_kw=bess_cost_kw,
        bess_cost_kwh=bess_cost_kwh,
        bess_om_kw_yr=bess_om_kw_yr,
        fuel_mode=fuel_mode,
        lng_days=lng_days,
        include_chp=False,
        enable_footprint_limit=enable_footprint_limit,
        max_area_m2=max_area_m2,
        region=region,
    )

    return run_clicked, inputs_dict


# =============================================================================
# RESULTS — TAB 1: SUMMARY
# =============================================================================
def render_summary_tab(r):
    """Top-level metrics and key results table."""

    # Methane warning
    if r.methane_warning:
        st.warning(f":warning: {r.methane_warning}")

    # Headline metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total DC Load", f"{r.p_total_dc:.1f} MW")
    c2.metric("Fleet Size", f"{r.n_running}+{r.n_reserve} = {r.n_total}")
    c3.metric("LCOE", f"${r.lcoe:.4f}/kWh")
    c4.metric("Availability", f"{r.system_availability:.3f}%")

    st.divider()

    # Key results table
    st.subheader("Sizing Summary")

    data = {
        "Parameter": [
            "Generator Model",
            "ISO Rating (MW)",
            "Site Rating (MW)",
            "Derate Factor",
            "Running Units",
            "Reserve Units",
            "Total Fleet",
            "Installed Capacity (MW)",
            "Load per Unit (%)",
            "Fleet Efficiency (%)",
            "Recommended Voltage (kV)",
            "Frequency (Hz)",
            "BESS Power (MW)",
            "BESS Energy (MWh)",
        ],
        "Value": [
            r.selected_gen,
            f"{r.unit_iso_cap:.2f}",
            f"{r.unit_site_cap:.2f}",
            f"{r.derate_factor:.4f}",
            str(r.n_running),
            str(r.n_reserve),
            str(r.n_total),
            f"{r.installed_cap:.1f}",
            f"{r.load_per_unit_pct:.1f}",
            f"{r.fleet_efficiency * 100:.1f}",
            f"{r.rec_voltage_kv:.1f}",
            str(r.freq_hz),
            f"{r.bess_power_mw:.2f}",
            f"{r.bess_energy_mwh:.2f}",
        ],
    }
    st.table(pd.DataFrame(data).set_index("Parameter"))


# =============================================================================
# RESULTS — TAB 2: RELIABILITY
# =============================================================================
def render_reliability_tab(r):
    """Availability over time chart and config comparison."""

    st.subheader("System Availability Over Time")

    # Availability chart
    years = list(range(1, len(r.availability_over_time) + 1))
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=years, y=r.availability_over_time,
        mode="lines+markers",
        name="System Availability",
        line=dict(color="#FFCC00", width=3),
        marker=dict(size=6),
    ))
    # Requirement threshold
    fig.add_hline(
        y=r.avail_req, line_dash="dash", line_color="red",
        annotation_text=f"Requirement: {r.avail_req}%",
    )
    fig.update_layout(
        xaxis_title="Year",
        yaxis_title="Availability (%)",
        yaxis=dict(range=[
            min(min(r.availability_over_time) - 0.5, r.avail_req - 1),
            100.1,
        ]),
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Reliability configs comparison
    st.subheader("Reliability Configurations")

    configs_data = []
    for cfg in r.reliability_configs:
        configs_data.append({
            "Configuration": cfg.name,
            "N Running": cfg.n_running,
            "N Reserve": cfg.n_reserve,
            "N Total": cfg.n_total,
            "BESS MW": f"{cfg.bess_mw:.2f}",
            "BESS MWh": f"{cfg.bess_mwh:.2f}",
            "BESS Credit": f"{cfg.bess_credit:.2f}",
            "Availability (%)": f"{cfg.availability:.4f}",
            "Load (%)": f"{cfg.load_pct:.1f}",
            "Efficiency (%)": f"{cfg.efficiency * 100:.1f}",
        })

    df_configs = pd.DataFrame(configs_data)

    # Highlight the selected config
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
# RESULTS — TAB 3: BESS
# =============================================================================
def render_bess_tab(r):
    """BESS sizing breakdown."""

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
                       marker_color="#FFCC00"),
                go.Bar(name="Energy (MWh)", x=components, y=energy_vals,
                       marker_color="#4A90D9"),
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


# =============================================================================
# RESULTS — TAB 4: ELECTRICAL
# =============================================================================
def render_electrical_tab(r):
    """Voltage, stability, and spinning reserve details."""

    st.subheader("Electrical System")

    c1, c2, c3 = st.columns(3)
    c1.metric("Recommended Voltage", f"{r.rec_voltage_kv:.1f} kV")
    c2.metric("Frequency", f"{r.freq_hz} Hz")
    c3.metric("Net Efficiency", f"{r.net_efficiency * 100:.1f}%")

    st.divider()

    # Transient stability
    st.subheader("Transient Stability")
    c1, c2 = st.columns(2)

    if r.stability_ok:
        c1.success(":white_check_mark: Stable")
    else:
        c1.error(":x: Unstable")

    c2.metric("Voltage Sag", f"{r.voltage_sag:.1f}%")

    st.divider()

    # Spinning reserve
    st.subheader("Spinning Reserve Detail")
    data = {
        "Component": ["Spinning Reserve Requirement", "From Generators", "From BESS", "Generator Headroom"],
        "MW": [
            f"{r.spinning_reserve_mw:.2f}",
            f"{r.spinning_from_gens:.2f}",
            f"{r.spinning_from_bess:.2f}",
            f"{r.headroom_mw:.2f}",
        ],
    }
    st.table(pd.DataFrame(data).set_index("Component"))


# =============================================================================
# RESULTS — TAB 5: ENVIRONMENTAL
# =============================================================================
def render_environmental_tab(r):
    """Emissions and site footprint."""

    st.subheader("Emissions")

    emissions = r.emissions
    if emissions:
        em_data = {
            "Pollutant": ["NOx", "CO", "CO2"],
            "Rate": [
                f"{emissions.get('nox_rate_g_kwh', 0):.3f} g/kWh",
                f"{emissions.get('co_rate_g_kwh', 0):.3f} g/kWh",
                f"{emissions.get('co2_rate_kg_mwh', 0):.1f} kg/MWh",
            ],
            "Annual Total": [
                f"{emissions.get('nox_tpy', 0):.1f} tons/yr",
                f"{emissions.get('co_tpy', 0):.1f} tons/yr",
                f"{emissions.get('co2_tpy', 0):,.0f} tons/yr",
            ],
        }
        st.table(pd.DataFrame(em_data).set_index("Pollutant"))

    st.divider()

    # Footprint
    st.subheader("Site Footprint")

    footprint = r.footprint
    if footprint:
        fp_items = []
        fp_values = []

        area_keys = [
            ("gen_area_m2", "Generators"),
            ("bess_area_m2", "BESS"),
            ("cooling_area_m2", "Cooling"),
            ("substation_area_m2", "Substation"),
            ("lng_area_m2", "LNG Storage"),
        ]

        for key, label in area_keys:
            val = footprint.get(key, 0)
            if val and val > 0:
                fp_items.append(label)
                fp_values.append(val)

        if fp_items:
            fig = go.Figure(data=[
                go.Bar(x=fp_items, y=fp_values, marker_color="#FFCC00"),
            ])
            fig.update_layout(
                yaxis_title="Area (m2)",
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)

        total_area = footprint.get("total_area_m2", 0)
        st.metric("Total Site Area", f"{total_area:,.0f} m2 ({total_area/10000:.2f} hectares)")


# =============================================================================
# RESULTS — TAB 6: FINANCIAL
# =============================================================================
def render_financial_tab(r):
    """LCOE, CAPEX, NPV, payback, and cost comparison."""

    st.subheader("Financial Summary")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("LCOE", f"${r.lcoe:.4f}/kWh")
    c2.metric("Total CAPEX", f"${r.total_capex:,.0f}")
    c3.metric("NPV", f"${r.npv:,.0f}")
    c4.metric("Payback", f"{r.simple_payback_years:.1f} years")

    st.divider()

    # Annual costs
    st.subheader("Annual Operating Costs")
    c1, c2 = st.columns(2)
    c1.metric("Annual Fuel Cost", f"${r.annual_fuel_cost:,.0f}")
    c2.metric("Annual O&M Cost", f"${r.annual_om_cost:,.0f}")

    # Infrastructure costs
    infra_total = r.pipeline_cost_usd + r.permitting_cost_usd + r.commissioning_cost_usd
    if infra_total > 0:
        st.divider()
        st.subheader("Infrastructure Costs")
        c1, c2, c3 = st.columns(3)
        c1.metric("Pipeline", f"${r.pipeline_cost_usd:,.0f}")
        c2.metric("Permitting", f"${r.permitting_cost_usd:,.0f}")
        c3.metric("Commissioning", f"${r.commissioning_cost_usd:,.0f}")

    st.divider()

    # LCOE vs Grid comparison
    st.subheader("LCOE vs Grid Benchmark")
    fig = go.Figure(data=[
        go.Bar(
            x=[r.lcoe, r.p_it * 0],  # placeholder
            y=["Gas Generation", "Grid Benchmark"],
            orientation="h",
            marker_color=["#FFCC00", "#4A90D9"],
        ),
    ])
    # Add the actual benchmark
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=["Gas Generation LCOE", "Grid Benchmark"],
        x=[r.lcoe, st.session_state.get("_benchmark_price", 0.12)],
        orientation="h",
        marker_color=["#FFCC00", "#4A90D9"],
        text=[f"${r.lcoe:.4f}", f"${st.session_state.get('_benchmark_price', 0.12):.4f}"],
        textposition="outside",
    ))
    fig.update_layout(
        xaxis_title="$/kWh",
        height=200,
        margin=dict(l=10, r=10, t=10, b=30),
    )
    st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# RESULTS — TAB 7: DERATING
# =============================================================================
def render_derating_tab(r):
    """Derating breakdown with CAT official tables."""

    st.subheader("Site Derating Analysis")

    if r.methane_warning:
        st.warning(f":warning: {r.methane_warning}")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Site Conditions**")
        st.markdown(f"- Temperature: **{st.session_state.get('_site_temp', 35)}C**")
        st.markdown(f"- Altitude: **{st.session_state.get('_site_alt', 100)} m**")
        st.markdown(f"- Methane Number: **{st.session_state.get('_mn', 80)}**")

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
        increasing=dict(marker=dict(color="#4A90D9")),
        decreasing=dict(marker=dict(color="#E74C3C")),
        totals=dict(marker=dict(color="#FFCC00")),
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
# RESULTS — TAB 8: PDF REPORT
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
# MAIN
# =============================================================================
def main():
    """Main app entry point."""

    # Initialize session state
    if "result" not in st.session_state:
        st.session_state.result = None

    # Render sidebar and get inputs
    run_clicked, inputs_dict = render_sidebar()

    # Store some values for cross-tab access
    st.session_state["_benchmark_price"] = inputs_dict["benchmark_price"]
    st.session_state["_site_temp"] = inputs_dict["site_temp_c"]
    st.session_state["_site_alt"] = inputs_dict["site_alt_m"]
    st.session_state["_mn"] = inputs_dict["methane_number"]

    # Run sizing
    if run_clicked:
        try:
            with st.spinner("Running sizing pipeline..."):
                sizing_input = SizingInput(**inputs_dict)
                result = run_full_sizing(sizing_input)
                st.session_state.result = result
        except Exception as e:
            st.error(f"Sizing failed: {e}")
            import traceback
            st.code(traceback.format_exc())
            return

    # Main area
    r = st.session_state.result

    if r is None:
        # Landing page
        st.title(":zap: CAT Power Solution")
        st.markdown(f"### Prime Power Quick-Size Tool v{APP_VERSION}")
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
            - Financial analysis (LCOE, NPV, payback)
            - PDF report generation

            **Quick Start:** Select a template preset from the sidebar to
            pre-fill typical values for your project size.
            """
        )
        return

    # Results tabs
    st.title(f":zap: Sizing Results — {r.selected_gen} | {r.p_it:.0f} MW IT")

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        ":clipboard: Summary",
        ":chart_with_upwards_trend: Reliability",
        ":battery: BESS",
        ":electric_plug: Electrical",
        ":deciduous_tree: Environmental",
        ":moneybag: Financial",
        ":thermometer: Derating",
        ":page_facing_up: PDF Report",
    ])

    with tab1:
        render_summary_tab(r)
    with tab2:
        render_reliability_tab(r)
    with tab3:
        render_bess_tab(r)
    with tab4:
        render_electrical_tab(r)
    with tab5:
        render_environmental_tab(r)
    with tab6:
        render_financial_tab(r)
    with tab7:
        render_derating_tab(r)
    with tab8:
        render_pdf_tab(r)


if __name__ == "__main__":
    main()
