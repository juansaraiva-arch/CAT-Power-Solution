"""
CAT Power Solution — Full Sizing Pipeline
============================================
Replicates the complete calculation sequence from size_solution.py
without any UI dependencies. Pure stateless computation.

Reference: Prime Power app/size_solution.py lines 893-1860
"""

import math
import numpy as np

from core.engine import (
    get_part_load_efficiency,
    transient_stability_check,
    frequency_screening,
    calculate_spinning_reserve_units,
    calculate_bess_requirements,
    calculate_bess_reliability_credit,
    calculate_availability_weibull,
    optimize_fleet_size,
    pod_fleet_optimizer,
    calculate_macrs_depreciation,
    noise_at_distance,
    calculate_combined_noise,
    noise_setback_distance,
    calculate_site_derate,
    calculate_emissions,
    calculate_footprint,
    calculate_lcoe,
    calculate_lng_logistics,
    calculate_pipeline_capex,
    calculate_chp,
    calculate_emissions_control_capex,
    check_emissions_compliance,
    gas_price_sensitivity,
    calculate_net_efficiency_and_heat_rate,
    calculate_phasing,
    design_validation_scorecard,
    lcoe_gap_recommender,
    footprint_optimization_recommendations,
    calculate_gas_pipeline,
    calculate_fleet_maintenance_configs,
)
from core.generator_library import GENERATOR_LIBRARY
from api.services.generator_resolver import resolve_generator
from api.schemas.sizing import SizingInput, SizingResult, ReliabilityConfig


# ==============================================================================
# REGIONAL COST MULTIPLIERS (standalone, no security_config dependency)
# ==============================================================================

_REGIONAL_MULTIPLIERS = {
    "US - Gulf Coast": 1.00,
    "US - West Coast": 1.15,
    "US - Northeast": 1.10,
    "US - Midwest": 1.05,
    "US - Southeast": 1.02,
    "Canada": 1.12,
    "Europe - West": 1.25,
    "Europe - North": 1.30,
    "Europe - South": 1.15,
    "Latin America": 0.90,
    "Middle East": 0.95,
    "Africa": 1.10,
    "Asia - Southeast": 0.85,
    "Asia - East": 1.05,
    "Australia": 1.20,
}

# Default O&M costs (public budget-level estimates)
_DEFAULT_OM = {
    "fixed_kw_yr": 12.0,
    "variable_mwh": 5.0,
    "labor_per_unit": 50000,
    "overhaul_cost_per_mw": 40000,
}


def _get_regional_multiplier(region: str) -> float:
    """Get regional cost multiplier."""
    return _REGIONAL_MULTIPLIERS.get(region, 1.0)


# ==============================================================================
# RELIABILITY CONFIG BUILDER
# ==============================================================================

def _find_availability_config(
    name: str,
    n_running: int,
    unit_site_cap: float,
    unit_availability: float,
    project_years: int,
    gen_data: dict,
    avail_decimal: float,
    p_avg_at_gen: float,
    bess_mw: float = 0,
    bess_mwh: float = 0,
    bess_credit: float = 0,
    spinning_result: dict | None = None,
    bess_genset_credit: int = 0,
) -> dict:
    """
    Find minimum N+X reserve to meet availability target.

    When *bess_genset_credit* > 0 the BESS can bridge power for that many
    generator-equivalents while a reserve unit starts.  The availability
    model then only requires ``n_running - bess_genset_credit`` physical
    generators to be simultaneously available, which reduces the number of
    reserve units needed.

    Returns a reliability config dict.
    """
    load_pct = (p_avg_at_gen / (n_running * unit_site_cap)) * 100 if n_running > 0 else 0
    # BESS can cover some generators, so fewer need to be available at once
    effective_n_running = max(1, n_running - bess_genset_credit)

    best = None
    for n_res in range(0, 101):
        n_tot = n_running + n_res
        avg_avail, _ = calculate_availability_weibull(
            n_tot, effective_n_running, unit_availability, project_years,
        )

        if avg_avail >= avail_decimal:
            eff = get_part_load_efficiency(
                gen_data["electrical_efficiency"], load_pct, gen_data["type"]
            )
            best = {
                "name": name,
                "n_running": n_running,
                "n_reserve": n_res,
                "n_total": n_tot,
                "bess_mw": bess_mw,
                "bess_mwh": bess_mwh,
                "bess_credit": bess_credit,
                "availability": avg_avail,
                "load_pct": load_pct,
                "efficiency": eff,
                "spinning_reserve_mw": spinning_result.get("spinning_reserve_mw", 0) if spinning_result else 0,
                "spinning_from_gens": spinning_result.get("spinning_from_gens", 0) if spinning_result else 0,
                "spinning_from_bess": spinning_result.get("spinning_from_bess", 0) if spinning_result else 0,
                "headroom_mw": spinning_result.get("headroom_available", 0) if spinning_result else 0,
            }
            break

    # Fallback if target not met with 100 reserves
    if not best:
        n_res_fb = 100
        n_tot_fb = n_running + n_res_fb
        fb_avail, _ = calculate_availability_weibull(
            n_tot_fb, effective_n_running, unit_availability, project_years,
        )
        eff = get_part_load_efficiency(
            gen_data["electrical_efficiency"], load_pct, gen_data["type"]
        )
        best = {
            "name": name,
            "n_running": n_running,
            "n_reserve": n_res_fb,
            "n_total": n_tot_fb,
            "bess_mw": bess_mw,
            "bess_mwh": bess_mwh,
            "bess_credit": bess_credit,
            "availability": fb_avail,
            "load_pct": load_pct,
            "efficiency": eff,
            "spinning_reserve_mw": spinning_result.get("spinning_reserve_mw", 0) if spinning_result else 0,
            "spinning_from_gens": spinning_result.get("spinning_from_gens", 0) if spinning_result else 0,
            "spinning_from_bess": spinning_result.get("spinning_from_bess", 0) if spinning_result else 0,
            "headroom_mw": spinning_result.get("headroom_available", 0) if spinning_result else 0,
        }

    return best


# ==============================================================================
# FULL SIZING PIPELINE
# ==============================================================================

def run_full_sizing(inputs: SizingInput) -> dict:
    """
    Execute the complete sizing pipeline.

    Mirrors the calculation logic from size_solution.py render() function.
    Returns a flat dict suitable for SizingResult or PDF report.

    Parameters
    ----------
    inputs : SizingInput
        Complete set of project inputs.

    Returns
    -------
    dict
        Full sizing results including fleet, BESS, electrical, emissions,
        footprint, and financial data.
    """

    # ── Step 1: Resolve generator ──
    gen_data = resolve_generator(inputs.generator_model, inputs.gen_overrides)

    # ── Step 2: Load calculations ──
    p_total_dc = inputs.p_it * inputs.pue
    p_total_avg = p_total_dc * inputs.capacity_factor
    # CORRECT — PAR = Peak / Average  →  Peak = Average × PAR
    p_total_peak = p_total_avg * inputs.peak_avg_ratio

    # Generator terminal load (after distribution losses)
    dist_loss_factor = 1 - inputs.dist_loss_pct / 100
    p_avg_at_gen = p_total_avg / dist_loss_factor
    p_peak_at_gen = p_total_peak / dist_loss_factor

    # ── Step 3: Site derating (CAT official tables with bilinear interpolation) ──
    derate_type = gen_data.get('derate_type', 'high_speed_recip')
    if inputs.derate_mode == "Auto-Calculate":
        derate_result = calculate_site_derate(
            inputs.site_temp_c, inputs.site_alt_m, inputs.methane_number,
            derate_type=derate_type,
        )
        derate_factor = derate_result["derate_factor"]
        methane_deration = derate_result["methane_deration"]
        altitude_deration = derate_result["altitude_deration"]
        achrf = derate_result["achrf"]
        methane_warning = derate_result["methane_warning"]
    else:
        derate_factor = inputs.derate_factor_manual
        methane_deration = 1.0
        altitude_deration = derate_factor  # Manual mode: attribute all derating to altitude
        achrf = 1.0
        methane_warning = None

    unit_iso_cap = gen_data["iso_rating_mw"]
    unit_site_cap = unit_iso_cap * derate_factor

    # ── Step 4: BESS sizing ──
    bess_power_transient = 0.0
    bess_energy_transient = 0.0
    bess_breakdown_transient = {}

    if inputs.use_bess:
        bess_power_transient, bess_energy_transient, bess_breakdown_transient = (
            calculate_bess_requirements(
                p_avg_at_gen, p_peak_at_gen,
                inputs.load_step_pct,
                gen_data["ramp_rate_mw_s"],
                gen_data["step_load_pct"],
                inputs.load_ramp_req,
                inputs.enable_black_start,
            )
        )

    # ── Step 5: Spinning reserve ──
    spinning_result = calculate_spinning_reserve_units(
        p_avg_load=p_avg_at_gen,
        unit_capacity=unit_site_cap,
        spinning_reserve_pct=inputs.spinning_res_pct,
        use_bess=inputs.use_bess,
        bess_power_mw=bess_power_transient if inputs.use_bess else 0,
        gen_step_capability_pct=gen_data["step_load_pct"],
        p_total_peak=p_total_peak,
        load_step_pct=inputs.load_step_pct,
        bess_energy_mwh=bess_energy_transient if inputs.use_bess else 0,
    )

    # ── Step 6: Pod Architecture Fleet Optimization (P05) ──
    avail_decimal = inputs.avail_req / 100

    mtbf = gen_data.get('mtbf_hours', 3000.0)
    mttr_hours = gen_data.get('mttr_hours', 16.0)  # used downstream for BESS bridge calc
    # a_gen uses operational availability (industry 93-95%), not MTBF/MTTR ratio (fix: 2026-03)
    a_gen = gen_data.get('unit_availability', 0.93)

    # Max normal loading from prime/standby ratio
    prime_kw   = gen_data.get('prime_power_kw', gen_data.get('standby_kw', unit_site_cap * 1000) * 0.90)
    standby_kw = gen_data.get('standby_kw', unit_site_cap * 1000)
    max_normal_loading = prime_kw / standby_kw  # ≈ 0.90 for CAT

    pod_result = pod_fleet_optimizer(
        p_total_peak       = p_total_peak,
        unit_site_cap      = unit_site_cap,
        a_gen              = a_gen,
        avail_req          = avail_decimal,
        max_normal_loading = max_normal_loading,
    )

    if pod_result is None:
        raise ValueError(
            f"Pod optimizer found no valid solution for "
            f"p_peak={p_total_peak:.1f} MW, unit={unit_site_cap:.2f} MW, "
            f"avail_req={avail_decimal*100:.3f}%"
        )

    # Map pod result to existing result fields (backward compat)
    n_running            = pod_result['n_running']
    n_reserve            = pod_result['n_reserve']
    n_total_pod          = pod_result['n_total']
    installed_cap_pod    = pod_result['installed_cap']
    load_per_unit_pct    = pod_result['loading_normal_pct']

    # New pod-specific result fields (additive)
    n_pods               = pod_result['n_pods']
    n_per_pod            = pod_result['n_per_pod']
    cap_contingency      = pod_result['cap_contingency']
    loading_contingency_pct = pod_result['loading_contingency_pct']
    a_system_calculated  = pod_result['a_system_calculated']
    a_gen_derived        = a_gen
    max_normal_loading_pct = max_normal_loading * 100.0

    # ── Fleet Maintenance Configs (P12) ──
    max_maint_units = getattr(inputs, 'max_maintenance_units', 0)
    fleet_maintenance_configs = calculate_fleet_maintenance_configs(
        p_total_peak          = p_total_peak,
        unit_site_cap         = unit_site_cap,
        a_gen                 = a_gen,
        avail_req             = avail_decimal,
        max_normal_loading    = max_normal_loading,
        max_maintenance_units = max_maint_units,
        base_n_pods           = pod_result['n_pods'],
    )
    # Annotate base pod_result with C4 fields
    pod_result['max_maintenance_units'] = max_maint_units
    pod_result['cap_combined'] = pod_result.get('cap_combined', pod_result['cap_contingency'])
    pod_result['maintenance_margin_mw'] = round(
        pod_result['cap_combined'] - p_total_peak, 3)

    # ── Electrical Sizing (P08) ──
    from api.services.electrical_sizing import calculate_electrical_sizing
    electrical = calculate_electrical_sizing(
        n_pods               = n_pods,
        n_per_pod            = n_per_pod,
        P_gen_mw             = unit_site_cap,
        V_gen_kv             = 13.8,
        pf                   = getattr(inputs, 'pf_electrical', 0.80),
        z_trafo_pu           = getattr(inputs, 'z_trafo_pu', 0.0575),
        xd_subtrans_pu       = getattr(inputs, 'xd_subtrans_pu', 0.20),
        isc_asymmetry_factor = getattr(inputs, 'isc_asymmetry_factor', 1.30),
        preferred_hv_kv      = getattr(inputs, 'preferred_hv_kv', None),
        p_load_mw            = p_total_peak,
    )

    # Legacy compatibility — keep old variable names used downstream
    n_running_from_load  = n_running
    unit_availability = gen_data.get("unit_availability", 0.93)

    # ── Step 8: Reliability configurations A/B/C ──
    reliability_configs = []

    # --- Config A: No BESS (Baseline) ---
    spinning_no_bess = calculate_spinning_reserve_units(
        p_avg_load=p_avg_at_gen,
        unit_capacity=unit_site_cap,
        spinning_reserve_pct=inputs.spinning_res_pct,
        use_bess=False,
        bess_power_mw=0,
        gen_step_capability_pct=gen_data["step_load_pct"],
        p_total_peak=p_total_peak,
        load_step_pct=inputs.load_step_pct,
        bess_energy_mwh=0,
    )
    n_running_peak = math.ceil(p_total_peak / unit_site_cap)
    n_running_no_bess = max(spinning_no_bess["n_units_running"], n_running_peak)

    config_a = _find_availability_config(
        name="A: No BESS",
        n_running=n_running_no_bess,
        unit_site_cap=unit_site_cap,
        unit_availability=unit_availability,
        project_years=inputs.project_years,
        gen_data=gen_data,
        avail_decimal=avail_decimal,
        p_avg_at_gen=p_avg_at_gen,
        spinning_result=spinning_no_bess,
    )
    reliability_configs.append(config_a)

    # --- Config B: BESS Transient Only ---
    config_b = None
    spinning_with_bess = None
    if inputs.use_bess:
        spinning_with_bess = calculate_spinning_reserve_units(
            p_avg_load=p_avg_at_gen,
            unit_capacity=unit_site_cap,
            spinning_reserve_pct=inputs.spinning_res_pct,
            use_bess=True,
            bess_power_mw=bess_power_transient,
            gen_step_capability_pct=gen_data["step_load_pct"],
            p_total_peak=p_total_peak,
            load_step_pct=inputs.load_step_pct,
            bess_energy_mwh=bess_energy_transient,
        )
        n_running_with_bess = spinning_with_bess["n_units_running"]

        config_b = _find_availability_config(
            name="B: BESS Transient",
            n_running=n_running_with_bess,
            unit_site_cap=unit_site_cap,
            unit_availability=unit_availability,
            project_years=inputs.project_years,
            gen_data=gen_data,
            avail_decimal=avail_decimal,
            p_avg_at_gen=p_avg_at_gen,
            bess_mw=bess_power_transient,
            bess_mwh=bess_energy_transient,
            spinning_result=spinning_with_bess,
        )
        reliability_configs.append(config_b)

    # --- Config C: Hybrid / Reliability Priority ---
    bess_reliability_enabled = inputs.use_bess and inputs.bess_strategy != "Transient Only"
    config_c = None

    if inputs.use_bess and bess_reliability_enabled and spinning_with_bess:
        n_running_min_c = spinning_with_bess["n_units_running"]

        # BESS sizing for reliability
        if inputs.bess_strategy == "Hybrid (Balanced)":
            target_gensets_covered = 5
        else:  # Reliability Priority
            target_gensets_covered = 8

        # Autonomy-based energy sizing (P13)
        bess_autonomy_min = getattr(inputs, 'bess_autonomy_min', 10.0)
        bess_autonomy_h = bess_autonomy_min / 60.0
        bess_dod = getattr(inputs, 'bess_dod', 0.85)

        bess_power_hybrid = max(bess_power_transient, target_gensets_covered * unit_site_cap)
        bess_energy_hybrid = max(
            bess_power_hybrid * bess_autonomy_h / bess_dod,
            target_gensets_covered * unit_site_cap * bess_autonomy_h / bess_dod,
        )

        # BESS reliability credit — how many genset-equivalents BESS can bridge
        try:
            bess_credit_units, credit_breakdown = calculate_bess_reliability_credit(
                bess_power_hybrid, bess_energy_hybrid, unit_site_cap, mttr_hours
            )
            bess_credit_conservative = bess_credit_units * 0.65
            bess_credit_int = max(0, int(bess_credit_conservative))
        except Exception:
            bess_credit_int = 0
            bess_credit_conservative = 0

        # Use _find_availability_config with bess_genset_credit so that
        # the availability model requires fewer physical generators to be
        # available simultaneously → fewer reserve units needed.
        config_c = _find_availability_config(
            name=f"C: {inputs.bess_strategy}",
            n_running=n_running_min_c,
            unit_site_cap=unit_site_cap,
            unit_availability=unit_availability,
            project_years=inputs.project_years,
            gen_data=gen_data,
            avail_decimal=avail_decimal,
            p_avg_at_gen=p_avg_at_gen,
            bess_mw=bess_power_hybrid,
            bess_mwh=bess_energy_hybrid,
            bess_credit=bess_credit_conservative,
            spinning_result=spinning_with_bess,
            bess_genset_credit=bess_credit_int,
        )
        reliability_configs.append(config_c)

    # ── Step 9: Select final configuration ──
    if inputs.bess_strategy == "Transient Only" and len(reliability_configs) >= 2:
        selected_config = reliability_configs[1]  # Config B
    elif inputs.bess_strategy in ("Hybrid (Balanced)", "Reliability Priority") and len(reliability_configs) >= 3:
        selected_config = reliability_configs[2]  # Config C
    elif len(reliability_configs) >= 1:
        selected_config = reliability_configs[0]  # Config A
    else:
        selected_config = {
            "name": "Fallback",
            "n_running": n_running_from_load,
            "n_reserve": 10,
            "n_total": n_running_from_load + 10,
            "bess_mw": bess_power_transient if inputs.use_bess else 0,
            "bess_mwh": bess_energy_transient if inputs.use_bess else 0,
            "bess_credit": 0,
            "availability": 0.9999,
            "load_pct": (p_avg_at_gen / (n_running_from_load * unit_site_cap)) * 100,
            "spinning_reserve_mw": spinning_result["spinning_reserve_mw"],
            "spinning_from_gens": spinning_result["spinning_from_gens"],
            "spinning_from_bess": spinning_result["spinning_from_bess"],
            "headroom_mw": spinning_result.get("headroom_available", 0),
        }

    # ── Step 10: Extract final values ──
    # Pod optimizer (P05) provides n_running, n_reserve, n_total, installed_cap
    n_total = n_total_pod
    installed_cap = installed_cap_pod
    # n_running and n_reserve already set from pod_result above
    bess_power_total = selected_config["bess_mw"]
    bess_energy_total = selected_config["bess_mwh"]
    # load_per_unit_pct already set from pod_result above

    # BESS breakdown
    if inputs.use_bess and bess_power_total > 0:
        bess_breakdown = dict(bess_breakdown_transient)
        bess_breakdown["reliability_backup"] = bess_power_total - bess_power_transient
    else:
        bess_breakdown = {}

    # ── Step 11: Fleet efficiency ──
    # Note: Site derating (temp/altitude/fuel) is already applied at the power level
    # via the CAT ADF table in Step 3. No additional efficiency corrections are applied
    # here to avoid double-counting.
    base_fleet_eff = get_part_load_efficiency(
        gen_data["electrical_efficiency"], load_per_unit_pct, gen_data["type"]
    )
    fleet_efficiency = base_fleet_eff

    # ── Step 12: Voltage recommendation ──
    if inputs.volt_mode == "Auto-Recommend":
        if installed_cap < 10:
            rec_voltage_kv = 4.16
        elif installed_cap < 50:
            rec_voltage_kv = 13.8
        elif installed_cap < 200:
            rec_voltage_kv = 34.5
        else:
            rec_voltage_kv = 34.5
    else:
        rec_voltage_kv = inputs.manual_voltage_kv

    # ── Step 13: Transient stability ──
    # Use the same load_step_mw from the SR calculation (P03/P04) — not re-derived
    step_load_mw = spinning_result["load_step_mw"]
    stability_ok, voltage_sag = transient_stability_check(
        gen_data["reactance_xd_2"], n_running, step_load_mw, unit_site_cap
    )

    # ── Step 14: Availability ──
    # Use the config's pre-calculated availability (includes BESS reliability
    # boost).  Only call Weibull for the timeline array.
    system_availability = selected_config["availability"]
    _, availability_curve = calculate_availability_weibull(
        n_total, n_running, unit_availability, inputs.project_years,
    )

    # ── Step 15: Emissions ──
    emissions = calculate_emissions(
        n_running, unit_site_cap, gen_data,
        inputs.capacity_factor, load_per_unit_pct,
    )

    # ── Step 16: Footprint ──
    # Calculate LNG gallons if applicable
    is_lng_primary = "LNG" in inputs.fuel_mode
    has_lng_storage = inputs.fuel_mode in ("LNG (Virtual Pipeline)", "Dual-Fuel (Pipe + LNG Backup)")
    lng_gal = 0.0
    if has_lng_storage and fleet_efficiency > 0:
        total_fuel_input_mw = p_total_avg / fleet_efficiency
        total_fuel_input_mmbtu_hr = total_fuel_input_mw * 3.412
        lng_mmbtu_total = total_fuel_input_mmbtu_hr * 24 * inputs.lng_days
        lng_gal = lng_mmbtu_total / 0.075

    footprint = calculate_footprint(
        n_total, unit_site_cap, gen_data,
        bess_power_total, bess_energy_total,
        has_lng_storage, lng_gal,
        inputs.cooling_method, p_total_dc,
    )

    # ── Step 17: Net efficiency ──
    net_efficiency = fleet_efficiency * dist_loss_factor if fleet_efficiency > 0 else 0

    # ── Step 18: Financial calculations ──
    wacc = inputs.wacc / 100  # Convert from percentage
    regional_mult = _get_regional_multiplier(inputs.region)

    # Scale factor for small projects
    if installed_cap < 2.5:
        scale_factor = 1.30
    elif installed_cap < 10.0:
        scale_factor = 1.15
    elif installed_cap < 50.0:
        scale_factor = 1.05
    else:
        scale_factor = 1.0

    gen_unit_cost = gen_data["est_cost_kw"] * regional_mult * scale_factor
    gen_install_cost = gen_data["est_install_kw"] * regional_mult * scale_factor

    gen_cost_total_m = (installed_cap * 1000) * gen_unit_cost / 1e6

    # BESS CAPEX
    if inputs.use_bess and bess_power_total > 0:
        cost_power_part = (bess_power_total * 1000) * inputs.bess_cost_kw
        cost_energy_part = (bess_energy_total * 1000) * inputs.bess_cost_kwh
        bess_capex_m = (cost_power_part + cost_energy_part) / 1e6
        bess_om_annual = bess_power_total * 1000 * inputs.bess_om_kw_yr
    else:
        bess_capex_m = 0
        bess_om_annual = 0

    # Installation index
    idx_install = gen_install_cost / gen_unit_cost if gen_unit_cost > 0 else 0.5
    idx_chp = 0.20 if inputs.include_chp else 0

    # Infrastructure line items (pipeline, permits, commissioning — user inputs)
    pipeline_cost = getattr(inputs, 'pipeline_cost_usd', 0) or 0
    permitting_cost = getattr(inputs, 'permitting_cost_usd', 0) or 0
    commissioning_cost_user = getattr(inputs, 'commissioning_cost_usd', 0) or 0
    infra_capex_m = (pipeline_cost + permitting_cost + commissioning_cost_user) / 1e6

    # Fix M (P06) — CAPEX BOS components
    capex_gen_m = gen_cost_total_m                        # generators
    capex_install_m = gen_cost_total_m * idx_install      # installation
    capex_chp_m = gen_cost_total_m * idx_chp              # CHP (if enabled)
    capex_base_m = capex_gen_m + capex_install_m          # base for BOS adders

    # BOS adders as fraction of gen+install base
    bos_pct          = getattr(inputs, 'bos_pct',         0.17)
    civil_pct        = getattr(inputs, 'civil_pct',       0.13)
    fuel_system_pct  = getattr(inputs, 'fuel_system_pct', 0.06)
    electrical_pct   = getattr(inputs, 'electrical_pct',  0.06)
    epc_pct          = getattr(inputs, 'epc_pct',         0.12)
    commissioning_pct = getattr(inputs, 'commissioning_pct', 0.025)
    contingency_pct  = getattr(inputs, 'contingency_pct', 0.10)

    capex_bos_m         = capex_base_m * bos_pct
    capex_civil_m       = capex_base_m * civil_pct
    capex_fuel_sys_m    = capex_base_m * fuel_system_pct
    capex_electrical_m  = capex_base_m * electrical_pct
    capex_epc_m         = capex_base_m * epc_pct
    capex_commission_m  = capex_base_m * commissioning_pct

    capex_subtotal_m = (capex_base_m + capex_chp_m + capex_bos_m + capex_civil_m
                        + capex_fuel_sys_m + capex_electrical_m + capex_epc_m
                        + capex_commission_m + bess_capex_m + infra_capex_m)
    capex_contingency_m = capex_subtotal_m * contingency_pct

    # Total CAPEX
    total_capex_m = capex_subtotal_m + capex_contingency_m

    # Effective hours and energy
    # Fix K (P06): p_total_avg = p_total_dc × CF already — no further CF
    # Annual energy = average power × hours in a year
    effective_hours = 8760  # used for fuel cost calculation below
    mwh_year = p_total_avg * 8760

    # O&M costs
    om = _DEFAULT_OM
    model_var_om = gen_data.get('variable_om_mwh', om["variable_mwh"])
    om_fixed_annual = (installed_cap * 1000) * om["fixed_kw_yr"]
    om_variable_annual = mwh_year * model_var_om
    om_labor_annual = n_total * om["labor_per_unit"]

    # Overhaul
    overhaul_hours = gen_data.get('overhaul_hours', 60000)
    overhaul_interval_years = overhaul_hours / (8760 * inputs.capacity_factor) if inputs.capacity_factor > 0 else 20
    overhaul_pv = 0
    if wacc > 0:
        for year in np.arange(overhaul_interval_years, inputs.project_years, overhaul_interval_years):
            cost = installed_cap * om["overhaul_cost_per_mw"]
            overhaul_pv += cost / ((1 + wacc) ** int(year))
        crf = (wacc * (1 + wacc) ** inputs.project_years) / ((1 + wacc) ** inputs.project_years - 1)
    else:
        crf = 1.0 / inputs.project_years
    overhaul_annualized = overhaul_pv * crf

    om_cost_year = om_fixed_annual + om_variable_annual + om_labor_annual + bess_om_annual + overhaul_annualized

    # Fuel cost
    total_gas_price = inputs.gas_price  # Simplified; in full app this depends on fuel_mode
    total_fuel_input_mw = p_total_avg / fleet_efficiency if fleet_efficiency > 0 else 0
    total_fuel_input_mmbtu_hr = total_fuel_input_mw * 3.412
    fuel_cost_year = total_fuel_input_mmbtu_hr * total_gas_price * effective_hours

    # Carbon cost
    co2_ton_yr = emissions.get("co2_tpy", 0)
    carbon_cost_year = co2_ton_yr * inputs.carbon_price_per_ton

    # Depreciation benefit
    depreciation_benefit_m = 0
    if inputs.enable_depreciation and wacc > 0:
        depreciation_benefit_m = calculate_macrs_depreciation(
            total_capex_m * 1e6, inputs.project_years, wacc
        ) / 1e6

    # BESS repowering
    repowering_pv_m = 0.0
    if inputs.use_bess:
        bess_life_batt = 10
        bess_life_inv = 15
        for year in range(1, inputs.project_years + 1):
            year_cost = 0.0
            if year % bess_life_batt == 0 and year < inputs.project_years:
                year_cost += bess_energy_total * 1000 * inputs.bess_cost_kwh
            if year % bess_life_inv == 0 and year < inputs.project_years:
                year_cost += bess_power_total * 1000 * inputs.bess_cost_kw
            if year_cost > 0 and wacc > 0:
                repowering_pv_m += (year_cost / 1e6) / ((1 + wacc) ** year)
    repowering_annualized = repowering_pv_m * 1e6 * crf

    # Total annual cost
    capex_annualized = (total_capex_m * 1e6) * crf
    total_annual_cost = fuel_cost_year + om_cost_year + capex_annualized + repowering_annualized + carbon_cost_year

    # Tax benefits
    depreciation_annualized = (depreciation_benefit_m * 1e6) * crf
    total_annual_cost_after_tax = total_annual_cost - depreciation_annualized

    # LCOE
    lcoe_val = total_annual_cost_after_tax / (mwh_year * 1000) if mwh_year > 0 else 0

    # NPV
    annual_grid_cost = mwh_year * 1000 * inputs.benchmark_price
    annual_savings = annual_grid_cost - (fuel_cost_year + om_cost_year + carbon_cost_year)

    if wacc > 0:
        pv_savings = annual_savings * ((1 - (1 + wacc) ** -inputs.project_years) / wacc)
    else:
        pv_savings = annual_savings * inputs.project_years

    total_tax_benefits = depreciation_benefit_m * 1e6
    npv_val = pv_savings + total_tax_benefits - (total_capex_m * 1e6) - (repowering_pv_m * 1e6)

    # Payback
    if annual_savings > 0:
        simple_payback = (total_capex_m * 1e6) / annual_savings
    else:
        simple_payback = 99.0

    # ── Step 18a: Net Efficiency & Heat Rate ──
    aux_pct = gen_data.get('aux_load_pct', 4.0)
    net_eff_data = calculate_net_efficiency_and_heat_rate(
        fleet_efficiency, aux_pct, inputs.dist_loss_pct,
    )

    # ── Step 18b: LNG Logistics ──
    lng_logistics = {}
    effective_gas_price = inputs.gas_price
    if inputs.fuel_mode in ("LNG", "Dual-Fuel"):
        lng_logistics = calculate_lng_logistics(
            p_avg_at_gen, fleet_efficiency, inputs.lng_days,
            inputs.gas_price_lng, inputs.gas_price,
            100.0 if inputs.fuel_mode == "LNG" else inputs.lng_backup_pct,
        )
        effective_gas_price = lng_logistics.get('blended_gas_price', inputs.gas_price)
        # Recalculate fuel cost with blended price
        fuel_cost_year = total_fuel_input_mmbtu_hr * effective_gas_price * effective_hours

    # ── Step 18c: Pipeline auto-calc ──
    if inputs.pipeline_distance_km > 0 and pipeline_cost == 0:
        pipeline_cost = calculate_pipeline_capex(
            inputs.pipeline_distance_km, inputs.pipeline_diameter_inch
        )
        # Recalculate infra
        infra_capex_m = (pipeline_cost + permitting_cost + commissioning_cost_user) / 1e6

    # ── Step 18d: CHP / Tri-Generation ──
    chp_results = {}
    if inputs.include_chp:
        chp_results = calculate_chp(
            n_running, unit_site_cap, gen_data, load_per_unit_pct,
            inputs.chp_recovery_eff, inputs.absorption_cop, inputs.cooling_load_mw,
        )

    # ── Step 18e: Emissions Control ──
    emissions_control = calculate_emissions_control_capex(
        n_total, unit_site_cap, inputs.include_scr, inputs.include_oxicat,
    )

    # ── Step 18f: Emissions Compliance ──
    # Apply aftertreatment reductions so compliance reflects post-treatment values
    nox_red_frac = 1 - emissions_control.get('nox_reduction_pct', 0) / 100
    co_red_frac = 1 - emissions_control.get('co_reduction_pct', 0) / 100

    emissions_compliance = check_emissions_compliance(
        emissions.get('nox_rate_g_kwh', 0) * nox_red_frac,
        emissions.get('co_rate_g_kwh', 0) * co_red_frac,
        emissions.get('co2_rate_kg_mwh', 0),
        unit_site_cap, n_running,
        nox_tpy=emissions.get('nox_tpy', 0) * nox_red_frac,
        co_tpy=emissions.get('co_tpy', 0) * co_red_frac,
        co2_tpy=emissions.get('co2_tpy', 0),
    )

    # ── Step 18g: Frequency Screening ──
    freq_result = frequency_screening(
        n_running, unit_site_cap, p_avg_at_gen,
        p_avg_at_gen * (inputs.load_step_pct / 100),
        gen_data, bess_power_total, inputs.use_bess, inputs.freq_hz,
    )

    # ── Step 18h: Noise Assessment ──
    attenuation_map = {"Standard": 10, "Enhanced": 20, "Critical": 30, "Building": 40}
    attenuation_db = attenuation_map.get(inputs.acoustic_treatment, 10)
    source_noise = gen_data.get('noise_db_at_1m', 105)
    combined_noise = calculate_combined_noise(source_noise, attenuation_db, n_running)
    noise_at_property = noise_at_distance(combined_noise, inputs.distance_to_property_m)
    noise_at_residence = noise_at_distance(combined_noise, inputs.distance_to_residence_m)
    setback = noise_setback_distance(combined_noise, inputs.noise_limit_db)
    noise_results = {
        'source_noise_db': source_noise,
        'attenuation_db': attenuation_db,
        'combined_noise_db': combined_noise,
        'noise_at_property_db': noise_at_property,
        'noise_at_residence_db': noise_at_residence,
        'noise_limit_db': inputs.noise_limit_db,
        'property_compliant': noise_at_property <= inputs.noise_limit_db,
        'setback_distance_m': setback,
        'acoustic_treatment': inputs.acoustic_treatment,
    }

    # ── Step 18i: Design Validation Scorecard ──
    # Use physical SR requirement from P03 redesign, not legacy user input
    spinning_required = spinning_result.get("sr_required_mw", p_avg_at_gen * (inputs.spinning_res_pct / 100))
    step_load_mw_actual = spinning_result.get("load_step_mw", p_avg_at_gen * (inputs.load_step_pct / 100))
    scorecard = design_validation_scorecard(
        system_availability, inputs.avail_req,
        selected_config.get("spinning_reserve_mw", 0), spinning_required,
        voltage_sag, load_per_unit_pct,
        bess_power_total, step_load_mw_actual,
        freq_result.get('nadir_hz', 59.5),
        freq_result.get('nadir_limit', 59.5),
        freq_result.get('rocof_hz_s', 0),
        freq_result.get('rocof_limit', 2.0),
        n_reserve,
        n_pods=pod_result.get('n_pods', 0) if pod_result else 0,
        n_per_pod=pod_result.get('n_per_pod', 0) if pod_result else 0,
    )

    # ── Step 18j: Gas Price Sensitivity ──
    gas_sens = gas_price_sensitivity(
        inputs.gas_price,
        emissions.get('annual_fuel_mmbtu', 0),
        om_cost_year,
        total_capex_m * 1e6,
        mwh_year * 1000,
        wacc, inputs.project_years, inputs.benchmark_price,
    )

    # ── Step 18k: LCOE Recommender ──
    lcoe_recs = lcoe_gap_recommender(
        lcoe_val, inputs.benchmark_price, gen_data,
        n_running, n_reserve, inputs.use_bess,
        inputs.include_chp, inputs.enable_depreciation,
    )

    # ── Step 18l: Footprint Optimization ──
    total_area = footprint.get('total_area_m2', 0)
    fp_recs = []
    if inputs.enable_footprint_limit and total_area > inputs.max_area_m2:
        fp_recs = footprint_optimization_recommendations(
            total_area, inputs.max_area_m2, gen_data,
            n_total, n_reserve, inputs.use_bess, GENERATOR_LIBRARY,
        )

    # ── Step 18m: Phasing ──
    phasing_result = {}
    if inputs.enable_phasing:
        phasing_result = calculate_phasing(
            p_total_dc, unit_site_cap, n_total, total_capex_m * 1e6,
            inputs.n_phases, inputs.months_between_phases,
        )

    # ── Step 18n: CAPEX & O&M Breakdown (Fix M — P06) ──
    capex_breakdown = {
        # existing
        'generators':        capex_gen_m * 1e6,
        'installation':      capex_install_m * 1e6,
        'bess':              bess_capex_m * 1e6,
        'chp':               chp_results.get('chp_capex_usd', 0) if inputs.include_chp else 0,
        'emissions_control': emissions_control.get('total_capex', 0),
        'lng_infrastructure': lng_logistics.get('lng_capex_usd', 0),
        'pipeline':          pipeline_cost,
        'permitting':        permitting_cost,
        # new BOS components (P06)
        'bos':               capex_bos_m * 1e6,
        'civil':             capex_civil_m * 1e6,
        'fuel_system':       capex_fuel_sys_m * 1e6,
        'electrical':        capex_electrical_m * 1e6,
        'epc':               capex_epc_m * 1e6,
        'commissioning':     capex_commission_m * 1e6,
        'contingency':       capex_contingency_m * 1e6,
    }
    capex_assumptions = {
        'generators': f"${gen_unit_cost:,.0f}/kW x {installed_cap * 1000:,.0f} kW",
        'installation': f"${gen_install_cost:,.0f}/kW (idx {idx_install:.2f})",
        'bess': (f"${inputs.bess_cost_kw:,.0f}/kW + ${inputs.bess_cost_kwh:,.0f}/kWh"
                 if inputs.use_bess and bess_power_total > 0 else "N/A"),
        'chp': ("HRSG $200k/MW + Abs $350k/MW" if inputs.include_chp else "N/A"),
        'emissions_control': (
            ("SCR $70/kW" if inputs.include_scr else "") +
            (" + " if inputs.include_scr and inputs.include_oxicat else "") +
            ("OxiCat $20/kW" if inputs.include_oxicat else "") or "N/A"
        ),
        'lng_infrastructure': "Tanks + vaporizer + piping" if lng_logistics.get('lng_capex_usd', 0) > 0 else "N/A",
        'pipeline': "User input",
        'permitting': "User input",
        'bos':           f"{bos_pct*100:.1f}% of gen+install",
        'civil':         f"{civil_pct*100:.1f}% of gen+install",
        'fuel_system':   f"{fuel_system_pct*100:.1f}% of gen+install",
        'electrical':    f"{electrical_pct*100:.1f}% of gen+install",
        'epc':           f"{epc_pct*100:.1f}% of gen+install",
        'commissioning': f"{commissioning_pct*100:.1f}% of gen+install",
        'contingency':   f"{contingency_pct*100:.1f}% of subtotal",
    }
    om_breakdown_dict = {
        'fixed': om_fixed_annual,
        'variable': om_variable_annual,
        'labor': om_labor_annual,
        'overhaul': overhaul_annualized,
        'bess_om': bess_om_annual,
    }

    # ── Step 18o: Off-Grid vs Grid Comparison ──
    grid_comparison = {}
    grid_annual = mwh_year * 1000 * inputs.benchmark_price
    gas_annual = fuel_cost_year + om_cost_year
    if grid_annual > 0:
        grid_cumulative = []
        gas_cumulative = []
        cum_grid = 0
        cum_gas = total_capex_m * 1e6
        crossover_year = None
        for yr in range(1, inputs.project_years + 1):
            cum_grid += grid_annual
            cum_gas += gas_annual
            grid_cumulative.append(cum_grid)
            gas_cumulative.append(cum_gas)
            if crossover_year is None and cum_grid >= cum_gas:
                crossover_year = yr
        grid_comparison = {
            'grid_cumulative': grid_cumulative,
            'gas_cumulative': gas_cumulative,
            'crossover_year': crossover_year,
            'grid_annual': grid_annual,
            'gas_annual': gas_annual,
            'savings_20yr': cum_grid - cum_gas,
        }

    # ── Step 18g: Gas Pipeline Sizing (P10) ──
    gas_pipeline = None
    fuel_curve = gen_data.get('fuel_consumption_curve')
    if fuel_curve and p_total_avg > 0:
        # Interpolate operating-point heat rate from fuel curve
        curve_load_pcts = fuel_curve['load_pct']
        curve_mj_vals   = fuel_curve['mj_per_ekwh']
        clamped_load = min(max(load_per_unit_pct, curve_load_pcts[0]), curve_load_pcts[-1])
        hr_op_mj_kwh = float(np.interp(clamped_load, curve_load_pcts, curve_mj_vals))

        gas_pipeline = calculate_gas_pipeline(
            p_total_avg_mw           = p_total_avg,
            hr_op_mj_kwh            = hr_op_mj_kwh,
            gen_data                 = gen_data,
            gas_supply_pressure_psia = getattr(inputs, 'gas_supply_pressure_psia', 100.0),
            pipeline_length_miles    = getattr(inputs, 'gas_pipeline_length_miles', 1.0),
            pipe_efficiency          = getattr(inputs, 'gas_pipe_efficiency', 0.92),
            gas_sg                   = getattr(inputs, 'gas_sg', 0.65),
            gas_temp_f               = getattr(inputs, 'gas_temp_f', 60.0),
            gas_z_factor             = getattr(inputs, 'gas_z_factor', 0.90),
        )

    # ── Step 19: Assemble result ──
    rel_configs = [ReliabilityConfig(**c) for c in reliability_configs]

    return SizingResult(
        # Project
        project_name="",
        dc_type=inputs.dc_type,
        region=inputs.region,
        app_version="4.0",
        # Load
        p_it=inputs.p_it,
        pue=inputs.pue,
        p_total_dc=p_total_dc,
        p_total_avg=p_total_avg,
        p_total_peak=p_total_peak,
        capacity_factor=inputs.capacity_factor,
        avail_req=inputs.avail_req,
        # Generator
        selected_gen=inputs.generator_model,
        unit_iso_cap=unit_iso_cap,
        unit_site_cap=unit_site_cap,
        derate_factor=derate_factor,
        methane_deration=methane_deration,
        altitude_deration=altitude_deration,
        derate_type=derate_type,
        derate_table_source=derate_result.get('derate_table_source', 'validated_gerp_em7206') if inputs.derate_mode == "Auto-Calculate" else None,
        achrf=achrf,
        methane_warning=methane_warning,
        # Fleet
        n_running=n_running,
        n_reserve=n_reserve,
        n_total=n_total,
        installed_cap=installed_cap,
        load_per_unit_pct=load_per_unit_pct,
        fleet_efficiency=fleet_efficiency,
        # Pod Architecture (P05)
        n_pods=n_pods,
        n_per_pod=n_per_pod,
        cap_contingency=cap_contingency,
        loading_normal_pct=load_per_unit_pct,
        loading_contingency_pct=loading_contingency_pct,
        a_system_calculated=a_system_calculated,
        a_gen_derived=a_gen_derived,
        max_normal_loading_pct=max_normal_loading_pct,
        # unit_site_cap already set above (line 917)
        # Spinning
        spinning_reserve_mw=selected_config.get("spinning_reserve_mw", 0),
        spinning_from_gens=selected_config.get("spinning_from_gens", 0),
        spinning_from_bess=selected_config.get("spinning_from_bess", 0),
        headroom_mw=selected_config.get("headroom_mw", 0),
        # SR diagnostics (P03/P04)
        sr_required_mw=spinning_result.get("sr_required_mw", 0),
        sr_user_mw=spinning_result.get("sr_user_mw", 0),
        sr_user_below_physical=spinning_result.get("sr_user_below_physical", False),
        sr_dominant_contingency=spinning_result.get("sr_dominant_contingency", "N-1"),
        load_step_mw=spinning_result.get("load_step_mw", 0),
        n1_mw=spinning_result.get("n1_mw", 0),
        bess_sr_credit_valid=spinning_result.get("bess_sr_credit_valid", False),
        bess_sr_response_ok=spinning_result.get("bess_sr_response_ok", False),
        bess_sr_energy_ok=spinning_result.get("bess_sr_energy_ok", False),
        bess_sr_available_mws=spinning_result.get("bess_sr_available_mws", 0),
        bess_sr_required_mws=spinning_result.get("bess_sr_required_mws", 0),
        # Reliability
        reliability_configs=rel_configs,
        selected_config_name=selected_config["name"],
        # BESS
        use_bess=inputs.use_bess,
        bess_strategy=inputs.bess_strategy,
        bess_power_mw=bess_power_total,
        bess_energy_mwh=bess_energy_total,
        bess_breakdown=bess_breakdown,
        bess_autonomy_min=getattr(inputs, 'bess_autonomy_min', 10.0),
        bess_dod=getattr(inputs, 'bess_dod', 0.85),
        # Electrical
        rec_voltage_kv=rec_voltage_kv,
        freq_hz=inputs.freq_hz,
        stability_ok=stability_ok,
        voltage_sag=voltage_sag,
        net_efficiency=net_efficiency,
        # Net Efficiency & Heat Rate
        gross_efficiency=fleet_efficiency,
        aux_load_pct=aux_pct,
        heat_rate_lhv_btu=net_eff_data['heat_rate_lhv_btu'],
        heat_rate_hhv_btu=net_eff_data['heat_rate_hhv_btu'],
        heat_rate_lhv_mj=net_eff_data['heat_rate_lhv_mj'],
        heat_rate_hhv_mj=net_eff_data['heat_rate_hhv_mj'],
        # Availability
        system_availability=system_availability,
        availability_over_time=availability_curve,
        # Emissions
        emissions=emissions,
        # Emissions Compliance
        emissions_compliance=emissions_compliance,
        emissions_control=emissions_control,
        # Footprint
        footprint=footprint,
        footprint_recommendations=fp_recs,
        # Financial
        lcoe=lcoe_val,
        npv=npv_val,
        total_capex=total_capex_m * 1e6,
        annual_fuel_cost=fuel_cost_year,
        annual_om_cost=om_cost_year,
        simple_payback_years=simple_payback,
        annual_savings=annual_savings,
        grid_annual_cost=annual_grid_cost,
        breakeven_gas_price=gas_sens.get('breakeven_gas_price', 0),
        pipeline_cost_usd=pipeline_cost,
        permitting_cost_usd=permitting_cost,
        commissioning_cost_usd=commissioning_cost_user,
        # Financial extras
        capex_breakdown=capex_breakdown,
        capex_assumptions=capex_assumptions,
        om_breakdown=om_breakdown_dict,
        gas_sensitivity=gas_sens,
        lcoe_recommendations=lcoe_recs,
        # LNG
        lng_logistics=lng_logistics,
        # CHP
        chp_results=chp_results,
        # Noise
        noise_results=noise_results,
        # Phasing
        phasing=phasing_result,
        # Scorecard
        design_scorecard=scorecard,
        # Frequency
        frequency_screening=freq_result,
        # Grid comparison
        grid_comparison=grid_comparison,
        # Electrical sizing (P08)
        electrical_sizing=electrical,
        # Gas pipeline (P10)
        gas_pipeline=gas_pipeline,
        # Fleet Maintenance (P12)
        cap_combined=pod_result.get('cap_combined'),
        maintenance_margin_mw=pod_result.get('maintenance_margin_mw'),
        max_maintenance_units=max_maint_units,
        fleet_maintenance_configs=fleet_maintenance_configs if fleet_maintenance_configs else None,
        selected_fleet_config_maint=getattr(inputs, 'selected_fleet_config_maint', 'B'),
    )


def run_quick_sizing(p_it: float, pue: float = 1.2, generator_model: str = "G3516H",
                     use_bess: bool = True, site_temp_c: float = 35.0,
                     site_alt_m: float = 100.0, freq_hz: int = 60) -> dict:
    """Quick sizing with minimal inputs, using defaults for everything else."""
    inputs = SizingInput(
        p_it=p_it,
        pue=pue,
        generator_model=generator_model,
        use_bess=use_bess,
        site_temp_c=site_temp_c,
        site_alt_m=site_alt_m,
        freq_hz=freq_hz,
    )
    return run_full_sizing(inputs)
