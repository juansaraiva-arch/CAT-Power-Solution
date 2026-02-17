"""
CAT Power Solution — Sizing Engine
====================================
Pure calculation module — NO UI dependencies (no Streamlit, no Plotly).

This module is the intellectual property core of the application.
It can be consumed by:
  - Streamlit UI  (current pilot)
  - FastAPI REST   (future web app)
  - CLI scripts    (batch sizing)
  - Unit tests     (pytest)

All functions are stateless: inputs in → results out.
"""

import math
import numpy as np
from copy import deepcopy

# ==============================================================================
# 1. PART-LOAD EFFICIENCY MODEL
# ==============================================================================

def get_part_load_efficiency(base_eff: float, load_pct: float, gen_type: str) -> float:
    """
    Efficiency curves validated against CAT test data using Linear Interpolation.
    Ensures 100% load = 100% of rated efficiency.

    Parameters
    ----------
    base_eff : float
        ISO-rated electrical efficiency (e.g. 0.441 for 44.1%).
    load_pct : float
        Operating load as percentage of rated capacity (0-100).
    gen_type : str
        One of "High Speed", "Medium Speed", "Gas Turbine".

    Returns
    -------
    float
        Adjusted efficiency at the given load point.
    """
    load_pct = max(0, min(100, load_pct))

    if gen_type == "High Speed":
        xp = [0, 25, 50, 75, 100]
        fp = [0.0, 0.70, 0.88, 0.96, 1.00]
    elif gen_type == "Medium Speed":
        xp = [0, 25, 50, 75, 100]
        fp = [0.0, 0.75, 0.91, 0.97, 1.00]
    elif gen_type == "Gas Turbine":
        xp = [0, 25, 50, 75, 100]
        fp = [0.0, 0.55, 0.78, 0.90, 1.00]
    else:
        return base_eff

    factor = np.interp(load_pct, xp, fp)
    return base_eff * factor


# ==============================================================================
# 2. TRANSIENT STABILITY
# ==============================================================================

def transient_stability_check(xd_pu: float, num_units: int,
                              step_load_pct: float) -> tuple:
    """
    Critical voltage sag check for AI workloads.

    Returns
    -------
    tuple(bool, float)
        (passes, voltage_sag_percent)
    """
    equiv_xd = xd_pu / math.sqrt(num_units)
    voltage_sag = (step_load_pct / 100) * equiv_xd * 100
    return (voltage_sag <= 10), voltage_sag


# ==============================================================================
# 3. FREQUENCY SCREENING (Swing Equation)
# ==============================================================================

def frequency_screening(n_running: int, unit_cap_mw: float,
                        p_avg_mw: float, step_mw: float,
                        gen_data: dict,
                        bess_mw: float = 0, bess_enabled: bool = False,
                        freq_hz: int = 60) -> dict:
    """
    Analytical frequency nadir and ROCOF screening.
    Uses simplified swing equation — NOT a substitute for full ODE simulation.

    Returns
    -------
    dict
        nadir_hz, rocof_hz_s, nadir_ok, rocof_ok, nadir_limit,
        rocof_limit, H_total, P_step_pu, notes
    """
    pf_gen = 0.85
    S_gen_mva = unit_cap_mw / pf_gen
    S_total_mva = n_running * S_gen_mva

    # Inertia
    H_mech = gen_data.get('inertia_h', 1.0)
    H_bess = 0.0
    if bess_enabled and bess_mw > 0:
        bess_ratio = bess_mw / S_total_mva
        H_bess = 4.0 * min(1.0, bess_ratio / 0.2)
    H_total = H_mech + H_bess

    # Per-unit step
    P_step_pu = step_mw / S_total_mva if S_total_mva > 0 else 1.0

    # Governor parameters
    R = 0.05      # 5% droop
    D = 2.0       # Data center PE load damping
    T_gov = 0.5   # Governor time constant (s)

    # ROCOF
    rocof_initial = (P_step_pu * freq_hz) / (2 * H_total) if H_total > 0 else 99

    if bess_enabled and bess_mw > 0:
        bess_coverage = min(bess_mw / step_mw, 1.0) if step_mw > 0 else 0
        rocof_initial *= (1 - bess_coverage * 0.7)

    # Nadir
    delta_f_ss = (P_step_pu / (D + 1 / R)) * freq_hz
    overshoot = 1.0 + math.sqrt(T_gov / (4 * max(H_total, 0.5)))
    delta_f_nadir = delta_f_ss * overshoot

    if bess_enabled and bess_mw > 0:
        bess_pu = min(bess_mw / S_total_mva, P_step_pu)
        delta_f_nadir *= max(0.3, 1 - bess_pu / P_step_pu * 0.6)

    nadir_hz = max(freq_hz - delta_f_nadir, freq_hz - 5.0)

    nadir_limit = 59.5 if freq_hz == 60 else 49.5
    rocof_limit = 1.0

    nadir_ok = nadir_hz >= nadir_limit
    rocof_ok = rocof_initial <= rocof_limit

    notes = []
    if not nadir_ok:
        notes.append(f"Nadir {nadir_hz:.2f} Hz < {nadir_limit} Hz — add inertia or BESS")
    if not rocof_ok:
        notes.append(f"ROCOF {rocof_initial:.2f} Hz/s > {rocof_limit} Hz/s — add virtual inertia")
    if nadir_ok and rocof_ok:
        notes.append("Screening PASS — confirm with detailed ODE simulation")

    return {
        'nadir_hz': nadir_hz,
        'rocof_hz_s': rocof_initial,
        'nadir_ok': nadir_ok,
        'rocof_ok': rocof_ok,
        'nadir_limit': nadir_limit,
        'rocof_limit': rocof_limit,
        'H_total': H_total,
        'P_step_pu': P_step_pu,
        'notes': notes,
    }


# ==============================================================================
# 4. SPINNING RESERVE CALCULATION
# ==============================================================================

def calculate_spinning_reserve_units(
    p_avg_load: float,
    unit_capacity: float,
    spinning_reserve_pct: float,
    use_bess: bool = False,
    bess_power_mw: float = 0,
    gen_step_capability_pct: float = 0,
) -> dict:
    """
    Calculate number of running units considering spinning reserve.

    WITHOUT BESS:
      Generators must provide ALL spinning reserve as HEADROOM.
    WITH BESS:
      BESS provides instant response; fewer generators needed.

    Returns
    -------
    dict
        n_units_running, load_per_unit_pct, spinning_reserve_mw,
        spinning_from_gens, spinning_from_bess, total_online_capacity,
        headroom_available, required_online_capacity
    """
    spinning_reserve_mw = p_avg_load * (spinning_reserve_pct / 100)

    if use_bess and bess_power_mw > 0:
        spinning_from_bess = min(bess_power_mw, spinning_reserve_mw)
    else:
        spinning_from_bess = 0

    spinning_from_gens = spinning_reserve_mw - spinning_from_bess

    if use_bess and spinning_from_bess >= spinning_reserve_mw * 0.9:
        required_online_capacity = p_avg_load * 1.05
    else:
        required_online_capacity = p_avg_load + spinning_from_gens

    n_units_running = max(1, math.ceil(required_online_capacity / unit_capacity))

    total_online_capacity = n_units_running * unit_capacity
    load_per_unit_pct = (p_avg_load / total_online_capacity) * 100
    headroom_available = total_online_capacity - p_avg_load

    return {
        'n_units_running': n_units_running,
        'load_per_unit_pct': load_per_unit_pct,
        'spinning_reserve_mw': spinning_reserve_mw,
        'spinning_from_gens': spinning_from_gens,
        'spinning_from_bess': spinning_from_bess,
        'total_online_capacity': total_online_capacity,
        'headroom_available': headroom_available,
        'required_online_capacity': required_online_capacity,
    }


# ==============================================================================
# 5. BESS SIZING
# ==============================================================================

def calculate_bess_requirements(
    p_net_req_avg: float,
    p_net_req_peak: float,
    step_load_req: float,
    gen_ramp_rate: float,
    gen_step_capability: float,
    load_change_rate_req: float,
    enable_black_start: bool = False,
) -> tuple:
    """
    Sophisticated BESS sizing based on actual transient analysis.

    Returns
    -------
    tuple(float, float, dict)
        (bess_power_total_mw, bess_energy_total_mwh, breakdown)
    """
    # Component 1: Step Load Support
    step_load_mw = p_net_req_avg * (step_load_req / 100)
    gen_step_mw = p_net_req_avg * (gen_step_capability / 100)
    bess_step_support = max(0, step_load_mw - gen_step_mw)

    # Component 2: Peak Shaving
    bess_peak_shaving = p_net_req_peak - p_net_req_avg

    # Component 3: Ramp Rate Support
    bess_ramp_support = max(0, (load_change_rate_req - gen_ramp_rate) * 10)

    # Component 4: Frequency Regulation
    bess_freq_reg = p_net_req_avg * 0.05

    # Component 5: Black Start
    bess_black_start = p_net_req_peak * 0.05 if enable_black_start else 0

    # Component 6: Spinning Reserve
    bess_spinning_reserve = p_net_req_avg * (step_load_req / 100)

    # Total Power — take max of all components, floor at 15% of peak
    bess_power_total = max(
        bess_step_support,
        bess_peak_shaving,
        bess_ramp_support,
        bess_freq_reg,
        bess_black_start,
        bess_spinning_reserve,
        p_net_req_peak * 0.15,
    )

    # Energy sizing
    c_rate = 1.0
    bess_energy_total = bess_power_total / c_rate / 0.85

    breakdown = {
        'step_support': bess_step_support,
        'peak_shaving': bess_peak_shaving,
        'ramp_support': bess_ramp_support,
        'freq_reg': bess_freq_reg,
        'black_start': bess_black_start,
        'spinning_reserve': bess_spinning_reserve,
    }

    return bess_power_total, bess_energy_total, breakdown


# ==============================================================================
# 6. BESS RELIABILITY CREDIT
# ==============================================================================

def calculate_bess_reliability_credit(
    bess_power_mw: float,
    bess_energy_mwh: float,
    unit_capacity_mw: float,
    mttr_hours: float = 48,
) -> tuple:
    """
    Calculate how many genset equivalents BESS can replace for reliability.

    BESS realistically covers 2-4 hours (bridge power while backup starts),
    NOT the full MTTR of 48 hours.

    Returns
    -------
    tuple(float, dict)
        (effective_credit, credit_breakdown)
    """
    if bess_power_mw <= 0 or bess_energy_mwh <= 0:
        return 0.0, {}

    realistic_coverage_hrs = 2.0

    power_credit = bess_power_mw / unit_capacity_mw
    bess_duration_hrs = bess_energy_mwh / bess_power_mw if bess_power_mw > 0 else 0
    energy_credit = bess_energy_mwh / (unit_capacity_mw * realistic_coverage_hrs)

    raw_credit = min(power_credit, energy_credit)

    bess_availability = 0.98
    coverage_factor = 0.70

    effective_credit = raw_credit * bess_availability * coverage_factor

    credit_breakdown = {
        'power_credit': power_credit,
        'energy_credit': energy_credit,
        'raw_credit': raw_credit,
        'bess_availability': bess_availability,
        'coverage_factor': coverage_factor,
        'effective_credit': effective_credit,
        'bess_duration_hrs': bess_duration_hrs,
        'realistic_coverage_hrs': realistic_coverage_hrs,
    }

    return effective_credit, credit_breakdown


# ==============================================================================
# 7. AVAILABILITY (Weibull / Binomial N+X)
# ==============================================================================

def calculate_availability_weibull(
    n_total: int,
    n_running: int,
    mtbf_hours: float,
    project_years: int,
    maintenance_interval_hrs: float = 1000,
    maintenance_duration_hrs: float = 48,
) -> tuple:
    """
    Reliability model using industry standard availability formula
    INCLUDING planned maintenance.

    Availability = MTBF / (MTBF + MTTR + Planned_Maintenance_Time)

    Returns
    -------
    tuple(float, list[float])
        (system_availability_year1, availability_over_time)
    """
    mttr_hours_val = 48  # Average repair time

    annual_maintenance_hrs = (8760 / maintenance_interval_hrs) * maintenance_duration_hrs
    total_unavailable_hrs = mttr_hours_val + annual_maintenance_hrs

    unit_availability = mtbf_hours / (mtbf_hours + total_unavailable_hrs)

    # System availability — binomial N+X
    sys_avail = 0
    for k in range(n_running, n_total + 1):
        comb = math.comb(n_total, k)
        prob = comb * (unit_availability ** k) * ((1 - unit_availability) ** (n_total - k))
        sys_avail += prob

    # Availability over project life with aging
    availability_over_time = []
    for year in range(1, project_years + 1):
        aging_factor = max(0.95, 1.0 - year * 0.001)
        aged_unit_availability = unit_availability * aging_factor

        sys_avail_year = 0
        for k in range(n_running, n_total + 1):
            comb = math.comb(n_total, k)
            prob = (comb
                    * (aged_unit_availability ** k)
                    * ((1 - aged_unit_availability) ** (n_total - k)))
            sys_avail_year += prob

        availability_over_time.append(sys_avail_year)

    return sys_avail, availability_over_time


# ==============================================================================
# 8. FLEET SIZE OPTIMIZATION
# ==============================================================================

def optimize_fleet_size(
    p_net_req_avg: float,
    p_net_req_peak: float,
    unit_cap: float,
    step_load_req: float,
    gen_data: dict,
    use_bess: bool = False,
) -> tuple:
    """
    Multi-objective fleet optimization considering capacity, efficiency,
    step load coverage, and optionally BESS.

    Returns
    -------
    tuple(int, dict)
        (optimal_n_running, fleet_options)
    """
    if use_bess:
        n_min_peak = math.ceil(p_net_req_avg * 1.15 / unit_cap)
        headroom_required = p_net_req_avg * 1.10
        n_min_step = math.ceil(headroom_required / unit_cap)
    else:
        n_min_peak = math.ceil(p_net_req_peak / unit_cap)
        headroom_required = p_net_req_avg * (1 + step_load_req / 100) * 1.20
        n_min_step = math.ceil(headroom_required / unit_cap)

    n_ideal_eff = math.ceil(p_net_req_avg / (unit_cap * 0.72))
    n_running_optimal = max(n_min_peak, n_ideal_eff, n_min_step)

    fleet_options = {}
    for n in range(max(1, n_running_optimal - 1), n_running_optimal + 3):
        if use_bess:
            if n * unit_cap < p_net_req_avg * 1.10:
                continue
        else:
            if n * unit_cap < p_net_req_peak:
                continue

        load_pct = (p_net_req_avg / (n * unit_cap)) * 100
        if load_pct < 30 or load_pct > 95:
            continue
        eff = get_part_load_efficiency(
            gen_data["electrical_efficiency"], load_pct, gen_data["type"]
        )

        optimal_load = 72.5
        load_penalty = abs(load_pct - optimal_load) / 100
        fleet_options[n] = {
            'efficiency': eff,
            'load_pct': load_pct,
            'score': eff * (1 - load_penalty * 0.5),
        }

    if fleet_options:
        optimal_n = max(fleet_options, key=lambda x: fleet_options[x]['score'])
        return optimal_n, fleet_options
    else:
        return n_running_optimal, {}


# ==============================================================================
# 9. MACRS DEPRECIATION
# ==============================================================================

def calculate_macrs_depreciation(capex: float, project_years: int,
                                 wacc: float = 0.08) -> float:
    """
    MACRS 5-year accelerated depreciation schedule.

    Returns
    -------
    float
        Present value of tax shield benefit.
    """
    macrs_schedule = [0.20, 0.32, 0.192, 0.1152, 0.1152, 0.0576]
    tax_rate = 0.21

    pv_benefit = 0
    for year, rate in enumerate(macrs_schedule, 1):
        if year > project_years:
            break
        annual_benefit = capex * rate * tax_rate
        pv_benefit += annual_benefit / ((1 + wacc) ** year)

    return pv_benefit


# ==============================================================================
# 10. NOISE PROPAGATION
# ==============================================================================

def noise_at_distance(combined_db: float, distance_m: float) -> float:
    """
    Noise propagation model — point source, hemispherical spreading.

    L_receiver = L_source - 20·log10(distance) - 11

    Returns
    -------
    float
        Sound pressure level in dB(A) at the given distance.
    """
    if distance_m <= 1:
        return combined_db
    return combined_db - 20 * math.log10(distance_m) - 11


def calculate_combined_noise(source_noise_db: float, attenuation_db: float,
                             n_running: int) -> float:
    """
    Combined noise from N identical sources with acoustic treatment.

    L_total = (L_single - attenuation) + 10·log10(N)
    """
    if n_running <= 0:
        return 0
    effective_source_db = source_noise_db - attenuation_db
    return effective_source_db + 10 * math.log10(n_running)


def noise_setback_distance(combined_db: float, noise_limit_db: float) -> float:
    """
    Minimum distance to meet a noise limit.

    d_min = 10^((L_combined - L_limit - 11) / 20)
    """
    if combined_db <= noise_limit_db + 11:
        return 1.0
    return 10 ** ((combined_db - noise_limit_db - 11) / 20)


# ==============================================================================
# 11. SITE DERATING
# ==============================================================================

def calculate_site_derate(site_temp_c: float, site_alt_m: float,
                          methane_number: int = 80) -> float:
    """
    Auto-calculate generator derating factor from site conditions.

    Factors:
      - Temperature: >25°C reduces output ~1% per 5.5°C
      - Altitude: >300m reduces output ~3.5% per 300m
      - Fuel quality: MN < 80 adds further derating

    Returns
    -------
    float
        Derate factor (0.0 – 1.0), e.g. 0.92 = 92% of ISO rating.
    """
    # Temperature derate
    if site_temp_c > 25:
        temp_derate = 1 - ((site_temp_c - 25) / 5.5) * 0.01
    else:
        temp_derate = 1.0

    # Altitude derate
    if site_alt_m > 300:
        alt_derate = 1 - ((site_alt_m - 300) / 300) * 0.035
    else:
        alt_derate = 1.0

    # Fuel quality derate
    if methane_number < 80:
        fuel_derate = 1 - ((80 - methane_number) / 100) * 0.15
    else:
        fuel_derate = 1.0

    return max(0.50, temp_derate * alt_derate * fuel_derate)


# ==============================================================================
# 12. EMISSIONS CALCULATIONS
# ==============================================================================

def calculate_emissions(n_running: int, unit_cap_mw: float,
                        gen_data: dict, capacity_factor: float,
                        load_per_unit_pct: float) -> dict:
    """
    Calculate annual emissions for the fleet.

    Returns
    -------
    dict
        nox_tpy, co_tpy, co2_tpy, nox_rate_g_kwh, co_rate_g_kwh,
        co2_rate_kg_mwh, annual_fuel_mmbtu, annual_energy_mwh
    """
    annual_hours = 8760 * capacity_factor
    annual_energy_mwh = n_running * unit_cap_mw * annual_hours

    # Fuel consumption
    heat_rate = gen_data.get('heat_rate_lhv', 8000)
    base_eff = gen_data.get('electrical_efficiency', 0.40)
    eff = get_part_load_efficiency(base_eff, load_per_unit_pct, gen_data.get('type', 'High Speed'))
    annual_fuel_mmbtu = (annual_energy_mwh * 3.412) / (eff / base_eff) if eff > 0 else 0

    # NOx (g/bhp-hr → tons/year)
    nox_rate = gen_data.get('emissions_nox', 0.5)  # g/bhp-hr
    nox_tpy = n_running * unit_cap_mw * 1341.02 * nox_rate * annual_hours / 1e6

    # CO
    co_rate = gen_data.get('emissions_co', 2.0)
    co_tpy = n_running * unit_cap_mw * 1341.02 * co_rate * annual_hours / 1e6

    # CO2 (from fuel: 117 lb/MMBtu for natural gas)
    co2_tpy = annual_fuel_mmbtu * 117 / 2000 if annual_fuel_mmbtu > 0 else 0

    # Intensity rates
    nox_g_kwh = (nox_tpy * 1e6) / (annual_energy_mwh * 1000) if annual_energy_mwh > 0 else 0
    co_g_kwh = (co_tpy * 1e6) / (annual_energy_mwh * 1000) if annual_energy_mwh > 0 else 0
    co2_kg_mwh = (co2_tpy * 907.185) / annual_energy_mwh if annual_energy_mwh > 0 else 0

    return {
        'nox_tpy': nox_tpy,
        'co_tpy': co_tpy,
        'co2_tpy': co2_tpy,
        'nox_rate_g_kwh': nox_g_kwh,
        'co_rate_g_kwh': co_g_kwh,
        'co2_rate_kg_mwh': co2_kg_mwh,
        'annual_fuel_mmbtu': annual_fuel_mmbtu,
        'annual_energy_mwh': annual_energy_mwh,
    }


# ==============================================================================
# 13. FOOTPRINT CALCULATION
# ==============================================================================

def calculate_footprint(n_total: int, unit_cap_mw: float,
                        gen_data: dict,
                        bess_power_mw: float = 0,
                        bess_energy_mwh: float = 0,
                        include_lng: bool = False,
                        lng_gallons: float = 0,
                        cooling_method: str = "Air-Cooled",
                        p_total_dc: float = 0) -> dict:
    """
    Calculate plant footprint breakdown by component.

    Returns
    -------
    dict
        gen_area_m2, bess_area_m2, lng_area_m2, cooling_area_m2,
        substation_area_m2, total_area_m2, power_density_mw_m2
    """
    density = gen_data.get('power_density_mw_per_m2', 0.010)
    gen_area = (n_total * unit_cap_mw / density) if density > 0 else 0

    # BESS area (~40 m² per MWh)
    bess_area = bess_energy_mwh * 40 if bess_energy_mwh > 0 else 0

    # LNG area (~0.1 m² per gallon)
    lng_area = lng_gallons * 0.1 if include_lng and lng_gallons > 0 else 0

    # Cooling area
    total_heat_mw = p_total_dc * 0.3 if p_total_dc > 0 else n_total * unit_cap_mw * 0.3
    if cooling_method == "Water-Cooled":
        cooling_area = total_heat_mw * 50
    else:
        cooling_area = total_heat_mw * 120

    # Substation area (scales with capacity)
    total_cap_mw = n_total * unit_cap_mw
    substation_area = 500 + total_cap_mw * 5

    total_area = gen_area + bess_area + lng_area + cooling_area + substation_area
    power_density = total_cap_mw / total_area if total_area > 0 else 0

    return {
        'gen_area_m2': gen_area,
        'bess_area_m2': bess_area,
        'lng_area_m2': lng_area,
        'cooling_area_m2': cooling_area,
        'substation_area_m2': substation_area,
        'total_area_m2': total_area,
        'power_density_mw_m2': power_density,
    }


# ==============================================================================
# 14. FINANCIAL / LCOE ENGINE
# ==============================================================================

def calculate_lcoe(
    total_capex: float,
    annual_om: float,
    annual_fuel_cost: float,
    annual_energy_mwh: float,
    wacc: float,
    project_years: int,
    carbon_cost_annual: float = 0,
) -> dict:
    """
    Levelized Cost of Energy and NPV calculation.

    Returns
    -------
    dict
        lcoe, npv, simple_payback_years, annual_total_cost
    """
    if annual_energy_mwh <= 0 or project_years <= 0:
        return {'lcoe': 0, 'npv': 0, 'simple_payback_years': 0, 'annual_total_cost': 0}

    annual_total_cost = annual_om + annual_fuel_cost + carbon_cost_annual

    # CRF (Capital Recovery Factor)
    if wacc > 0:
        crf = (wacc * (1 + wacc) ** project_years) / ((1 + wacc) ** project_years - 1)
    else:
        crf = 1 / project_years

    annualized_capex = total_capex * crf

    lcoe = (annualized_capex + annual_total_cost) / annual_energy_mwh

    # NPV of revenue (at LCOE price)
    npv_costs = total_capex
    for yr in range(1, project_years + 1):
        npv_costs += annual_total_cost / ((1 + wacc) ** yr)

    # Simple payback
    annual_savings = annual_energy_mwh * lcoe - annual_total_cost  # placeholder
    simple_payback = total_capex / annual_total_cost if annual_total_cost > 0 else project_years

    return {
        'lcoe': lcoe,
        'npv': npv_costs,
        'simple_payback_years': min(simple_payback, project_years),
        'annual_total_cost': annual_total_cost,
        'annualized_capex': annualized_capex,
        'crf': crf,
    }
