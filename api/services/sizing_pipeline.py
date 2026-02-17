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
    calculate_macrs_depreciation,
    noise_at_distance,
    calculate_combined_noise,
    noise_setback_distance,
    calculate_site_derate,
    calculate_emissions,
    calculate_footprint,
    calculate_lcoe,
)
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
    mtbf_hours: float,
    project_years: int,
    gen_data: dict,
    avail_decimal: float,
    p_avg_at_gen: float,
    bess_mw: float = 0,
    bess_mwh: float = 0,
    bess_credit: float = 0,
    spinning_result: dict | None = None,
    bess_reliability_boost: float = 0,
) -> dict:
    """
    Find minimum N+X reserve to meet availability target.
    Returns a reliability config dict.
    """
    load_pct = (p_avg_at_gen / (n_running * unit_site_cap)) * 100 if n_running > 0 else 0

    best = None
    for n_res in range(0, 101):
        n_tot = n_running + n_res
        avg_avail, _ = calculate_availability_weibull(
            n_tot, n_running, mtbf_hours, project_years,
            gen_data["maintenance_interval_hrs"],
            gen_data["maintenance_duration_hrs"],
        )
        effective_avail = min(1.0, avg_avail + bess_reliability_boost)

        if effective_avail >= avail_decimal:
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
                "availability": effective_avail,
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
            n_tot_fb, n_running, mtbf_hours, project_years,
            gen_data["maintenance_interval_hrs"],
            gen_data["maintenance_duration_hrs"],
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
            "availability": min(1.0, fb_avail + bess_reliability_boost),
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
    p_total_peak = p_total_dc * inputs.peak_avg_ratio

    # Generator terminal load (after distribution losses)
    dist_loss_factor = 1 - inputs.dist_loss_pct / 100
    p_avg_at_gen = p_total_avg / dist_loss_factor
    p_peak_at_gen = p_total_peak / dist_loss_factor

    # ── Step 3: Site derating ──
    if inputs.derate_mode == "Auto-Calculate":
        derate_factor = calculate_site_derate(
            inputs.site_temp_c, inputs.site_alt_m, inputs.methane_number
        )
    else:
        derate_factor = inputs.derate_factor_manual

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
    )

    # ── Step 6: Fleet optimization ──
    n_running_opt, fleet_options = optimize_fleet_size(
        p_avg_at_gen, p_peak_at_gen,
        unit_site_cap, inputs.load_step_pct,
        gen_data, inputs.use_bess,
    )
    n_running_from_load = max(n_running_opt, spinning_result["n_units_running"])

    # ── Step 7: Availability target ──
    avail_decimal = inputs.avail_req / 100
    mtbf_hours = gen_data["mtbf_hours"]
    mttr_hours = 48

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
    )
    n_running_peak = math.ceil(p_total_peak / unit_site_cap)
    n_running_no_bess = max(spinning_no_bess["n_units_running"], n_running_peak)

    config_a = _find_availability_config(
        name="A: No BESS",
        n_running=n_running_no_bess,
        unit_site_cap=unit_site_cap,
        mtbf_hours=mtbf_hours,
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
        )
        n_running_with_bess = spinning_with_bess["n_units_running"]

        config_b = _find_availability_config(
            name="B: BESS Transient",
            n_running=n_running_with_bess,
            unit_site_cap=unit_site_cap,
            mtbf_hours=mtbf_hours,
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
            bess_coverage_hrs = 2.0
        else:  # Reliability Priority
            target_gensets_covered = 8
            bess_coverage_hrs = 2.5

        bess_power_hybrid = max(bess_power_transient, target_gensets_covered * unit_site_cap)
        bess_energy_hybrid = max(
            bess_power_hybrid * bess_coverage_hrs,
            target_gensets_covered * unit_site_cap * bess_coverage_hrs,
        )

        # BESS reliability credit
        try:
            bess_credit_units, credit_breakdown = calculate_bess_reliability_credit(
                bess_power_hybrid, bess_energy_hybrid, unit_site_cap, mttr_hours
            )
            bess_credit_conservative = bess_credit_units * 0.65
            bess_credit_int = max(0, int(bess_credit_conservative))
        except Exception:
            bess_credit_int = 0
            bess_credit_conservative = 0

        # Search for optimal Config C
        config_b_reserve = config_b["n_reserve"] if config_b else config_a["n_reserve"]
        bess_reliability_boost = min(0.0005, bess_credit_int * 0.00005)

        found_c = False
        for n_run_offset in range(-5, 10):
            if found_c:
                break
            n_run = n_running_min_c + n_run_offset
            if n_run < n_running_min_c:
                continue
            if n_run * unit_site_cap < spinning_with_bess["required_online_capacity"]:
                continue

            for n_res_try in range(max(1, config_b_reserve - 10), config_b_reserve + 2):
                n_tot = n_run + n_res_try
                try:
                    avg_avail, _ = calculate_availability_weibull(
                        n_tot, n_run, mtbf_hours, inputs.project_years,
                        gen_data["maintenance_interval_hrs"],
                        gen_data["maintenance_duration_hrs"],
                    )
                    avg_avail_with_bess = min(1.0, avg_avail + bess_reliability_boost)

                    if avg_avail_with_bess >= avail_decimal:
                        load_pct_c = (p_avg_at_gen / (n_run * unit_site_cap)) * 100
                        eff_c = get_part_load_efficiency(
                            gen_data["electrical_efficiency"], load_pct_c, gen_data["type"]
                        )
                        config_c = {
                            "name": f"C: {inputs.bess_strategy}",
                            "n_running": n_run,
                            "n_reserve": n_res_try,
                            "n_total": n_tot,
                            "bess_mw": bess_power_hybrid,
                            "bess_mwh": bess_energy_hybrid,
                            "bess_credit": bess_credit_conservative,
                            "availability": avg_avail_with_bess,
                            "load_pct": load_pct_c,
                            "efficiency": eff_c,
                            "spinning_reserve_mw": spinning_with_bess["spinning_reserve_mw"],
                            "spinning_from_gens": spinning_with_bess["spinning_from_gens"],
                            "spinning_from_bess": spinning_with_bess["spinning_from_bess"],
                            "headroom_mw": n_run * unit_site_cap - p_total_avg,
                        }
                        found_c = True
                        break
                except Exception:
                    continue

        if config_c:
            reliability_configs.append(config_c)
        else:
            # Fallback Config C
            n_run_fb = n_running_min_c
            n_res_fb = 100
            fb_avail, _ = calculate_availability_weibull(
                n_run_fb + n_res_fb, n_run_fb, mtbf_hours, inputs.project_years,
                gen_data["maintenance_interval_hrs"],
                gen_data["maintenance_duration_hrs"],
            )
            fb_load = (p_avg_at_gen / (n_run_fb * unit_site_cap)) * 100
            config_c = {
                "name": f"C: {inputs.bess_strategy} (fallback)",
                "n_running": n_run_fb,
                "n_reserve": n_res_fb,
                "n_total": n_run_fb + n_res_fb,
                "bess_mw": bess_power_hybrid,
                "bess_mwh": bess_energy_hybrid,
                "bess_credit": bess_credit_conservative,
                "availability": fb_avail,
                "load_pct": fb_load,
                "efficiency": get_part_load_efficiency(
                    gen_data["electrical_efficiency"], fb_load, gen_data["type"]
                ),
                "spinning_reserve_mw": spinning_with_bess["spinning_reserve_mw"],
                "spinning_from_gens": spinning_with_bess["spinning_from_gens"],
                "spinning_from_bess": spinning_with_bess["spinning_from_bess"],
                "headroom_mw": n_run_fb * unit_site_cap - p_total_avg,
            }
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
    n_running = selected_config["n_running"]
    n_reserve = selected_config["n_reserve"]
    n_total = selected_config["n_total"]
    bess_power_total = selected_config["bess_mw"]
    bess_energy_total = selected_config["bess_mwh"]
    load_per_unit_pct = selected_config["load_pct"]
    installed_cap = n_total * unit_site_cap

    # BESS breakdown
    if inputs.use_bess and bess_power_total > 0:
        bess_breakdown = dict(bess_breakdown_transient)
        bess_breakdown["reliability_backup"] = bess_power_total - bess_power_transient
    else:
        bess_breakdown = {}

    # ── Step 11: Fleet efficiency with site corrections ──
    # Fuel quality correction
    if inputs.methane_number < 70:
        eff_fuel_factor = 0.94
    elif inputs.methane_number < 80:
        eff_fuel_factor = 0.98
    else:
        eff_fuel_factor = 1.0

    # Extreme altitude correction
    if inputs.site_alt_m > 2000:
        eff_alt_factor = 1.0 - ((inputs.site_alt_m - 2000) / 1000) * 0.005
    else:
        eff_alt_factor = 1.0

    site_efficiency_correction = eff_fuel_factor * eff_alt_factor

    base_fleet_eff = get_part_load_efficiency(
        gen_data["electrical_efficiency"], load_per_unit_pct, gen_data["type"]
    )
    fleet_efficiency = base_fleet_eff * site_efficiency_correction

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
    stability_ok, voltage_sag = transient_stability_check(
        gen_data["reactance_xd_2"], n_running, inputs.load_step_pct
    )

    # ── Step 14: Availability curve ──
    system_availability, availability_curve = calculate_availability_weibull(
        n_total, n_running, mtbf_hours, inputs.project_years,
        gen_data["maintenance_interval_hrs"],
        gen_data["maintenance_duration_hrs"],
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

    # Total CAPEX
    total_capex_m = (
        gen_cost_total_m
        + gen_cost_total_m * idx_install
        + gen_cost_total_m * idx_chp
        + bess_capex_m
    )

    # Effective hours and energy
    effective_hours = 8760 * inputs.capacity_factor
    mwh_year = p_total_avg * effective_hours

    # O&M costs
    om = _DEFAULT_OM
    om_fixed_annual = (installed_cap * 1000) * om["fixed_kw_yr"]
    om_variable_annual = mwh_year * om["variable_mwh"]
    om_labor_annual = n_total * om["labor_per_unit"]

    # Overhaul
    overhaul_interval_years = 60000 / (8760 * inputs.capacity_factor) if inputs.capacity_factor > 0 else 20
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

    # ── Step 19: Assemble result ──
    rel_configs = [ReliabilityConfig(**c) for c in reliability_configs]

    return SizingResult(
        # Project
        project_name="",
        dc_type=inputs.dc_type,
        region=inputs.region,
        app_version="3.1",
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
        # Fleet
        n_running=n_running,
        n_reserve=n_reserve,
        n_total=n_total,
        installed_cap=installed_cap,
        load_per_unit_pct=load_per_unit_pct,
        fleet_efficiency=fleet_efficiency,
        # Spinning
        spinning_reserve_mw=selected_config.get("spinning_reserve_mw", 0),
        spinning_from_gens=selected_config.get("spinning_from_gens", 0),
        spinning_from_bess=selected_config.get("spinning_from_bess", 0),
        headroom_mw=selected_config.get("headroom_mw", 0),
        # Reliability
        reliability_configs=rel_configs,
        selected_config_name=selected_config["name"],
        # BESS
        use_bess=inputs.use_bess,
        bess_strategy=inputs.bess_strategy,
        bess_power_mw=bess_power_total,
        bess_energy_mwh=bess_energy_total,
        bess_breakdown=bess_breakdown,
        # Electrical
        rec_voltage_kv=rec_voltage_kv,
        freq_hz=inputs.freq_hz,
        stability_ok=stability_ok,
        voltage_sag=voltage_sag,
        net_efficiency=net_efficiency,
        # Availability
        system_availability=system_availability,
        availability_over_time=availability_curve,
        # Emissions
        emissions=emissions,
        # Footprint
        footprint=footprint,
        # Financial
        lcoe=lcoe_val,
        npv=npv_val,
        total_capex=total_capex_m,
        annual_fuel_cost=fuel_cost_year,
        annual_om_cost=om_cost_year,
        simple_payback_years=simple_payback,
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
