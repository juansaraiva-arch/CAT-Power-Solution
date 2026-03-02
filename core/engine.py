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
# OFFICIAL CAT DERATING REFERENCE TABLES
# ==============================================================================
# Source: Caterpillar Fuel Usage Guide & Altitude Deration Factors (Oct 2025)
# These tables are the single source of truth for site derating calculations.
# ==============================================================================

# ── Methane Number Deration (1D) ──
# CAT Methane Number → Power Deration Factor
# MN < 32: gas not suitable for operation (factor = 0)
_MN_XS = [32, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 100]
_MN_YS = [0.70, 0.72, 0.74, 0.77, 0.84, 0.90, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]

# ── Altitude Deration Factor (2D) ──
# Rows: Inlet Air Temperature (°C), ascending
# Cols: Altitude (meters above sea level)
_ADF_TEMPS = [10, 15, 20, 25, 30, 35, 40, 45, 50]
_ADF_ALTS = [0, 250, 500, 750, 1000, 1250, 1500, 1750, 2000, 2250, 2500, 2750, 3000]
_ADF_TABLE = [
    # 10°C
    [1, 1, 1, 1, 1, 1, 0.98, 0.97, 0.93, 0.89, 0.86, 0.82, 0.82],
    # 15°C
    [1, 1, 1, 1, 1, 1, 0.98, 0.95, 0.92, 0.88, 0.85, 0.82, 0.82],
    # 20°C
    [1, 1, 1, 1, 1, 1, 0.97, 0.94, 0.90, 0.87, 0.84, 0.81, 0.81],
    # 25°C
    [1, 1, 1, 1, 1, 1, 0.98, 0.95, 0.92, 0.89, 0.86, 0.83, 0.80],
    # 30°C
    [1, 1, 1, 1, 1, 0.99, 0.96, 0.93, 0.90, 0.87, 0.84, 0.81, 0.78],
    # 35°C
    [1, 1, 1, 1, 1, 0.97, 0.94, 0.91, 0.88, 0.85, 0.82, 0.79, 0.76],
    # 40°C
    [1, 1, 1, 1, 1, 0.96, 0.91, 0.86, 0.81, 0.76, 0.71, 0.67, 0.63],
    # 45°C
    [1, 1, 1, 0.96, 0.91, 0.85, 0.80, 0.75, 0.71, 0.68, 0.64, 0.61, 0.57],
    # 50°C
    [1, 0.95, 0.91, 0.86, 0.81, 0.77, 0.73, 0.70, 0.67, 0.64, 0.61, 0.58, 0.55],
]

# ── Aftercooler Heat Rejection Factor (2D) ──
# Same row/col structure as ADF table
_ACHRF_TABLE = [
    # 10°C
    [1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00],
    # 15°C
    [1.00, 1.00, 1.00, 1.00, 1.00, 1.03, 1.03, 1.03, 1.03, 1.03, 1.03, 1.03, 1.03],
    # 20°C
    [1.00, 1.00, 1.00, 1.02, 1.05, 1.08, 1.08, 1.08, 1.08, 1.08, 1.08, 1.08, 1.08],
    # 25°C
    [1.00, 1.01, 1.04, 1.07, 1.10, 1.13, 1.13, 1.13, 1.13, 1.13, 1.13, 1.13, 1.13],
    # 30°C
    [1.03, 1.06, 1.09, 1.12, 1.15, 1.18, 1.18, 1.18, 1.18, 1.18, 1.18, 1.18, 1.18],
    # 35°C
    [1.08, 1.11, 1.14, 1.17, 1.20, 1.23, 1.23, 1.23, 1.23, 1.23, 1.23, 1.23, 1.23],
    # 40°C
    [1.13, 1.15, 1.18, 1.21, 1.25, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28],
    # 45°C
    [1.17, 1.20, 1.23, 1.26, 1.29, 1.33, 1.33, 1.33, 1.33, 1.33, 1.33, 1.33, 1.33],
    # 50°C
    [1.22, 1.25, 1.28, 1.31, 1.34, 1.38, 1.38, 1.38, 1.38, 1.38, 1.38, 1.38, 1.38],
]


# ==============================================================================
# INTERPOLATION UTILITIES
# ==============================================================================

def _interp_1d(x: float, xs: list, ys: list) -> float:
    """
    1D linear interpolation with clamping to table bounds.

    Parameters
    ----------
    x : float
        Input value to look up.
    xs : list[float]
        Sorted breakpoints (ascending).
    ys : list[float]
        Corresponding output values.

    Returns
    -------
    float
        Interpolated value, clamped to [ys[0], ys[-1]] range.
    """
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            t = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]


def _interp_2d(temp: float, alt: float,
               temps: list, alts: list, table: list) -> float:
    """
    Bilinear interpolation on a 2D lookup table with clamping.

    Parameters
    ----------
    temp : float
        Inlet air temperature (°C). Clamped to table range.
    alt : float
        Altitude (m above sea level). Clamped to table range.
    temps : list[float]
        Row breakpoints (ascending temperature values).
    alts : list[float]
        Column breakpoints (ascending altitude values).
    table : list[list[float]]
        2D array of values, table[row_idx][col_idx].

    Returns
    -------
    float
        Bilinearly interpolated value.
    """
    # Clamp inputs to table bounds
    temp = max(temps[0], min(temps[-1], temp))
    alt = max(alts[0], min(alts[-1], alt))

    # Find row indices (temperature)
    r = 0
    for i in range(len(temps) - 1):
        if temps[i] <= temp <= temps[i + 1]:
            r = i
            break
    else:
        r = len(temps) - 2

    # Find col indices (altitude)
    c = 0
    for i in range(len(alts) - 1):
        if alts[i] <= alt <= alts[i + 1]:
            c = i
            break
    else:
        c = len(alts) - 2

    # Bilinear interpolation weights
    t_range = temps[r + 1] - temps[r]
    a_range = alts[c + 1] - alts[c]
    t_frac = (temp - temps[r]) / t_range if t_range > 0 else 0.0
    a_frac = (alt - alts[c]) / a_range if a_range > 0 else 0.0

    # Four corner values
    v00 = table[r][c]
    v01 = table[r][c + 1]
    v10 = table[r + 1][c]
    v11 = table[r + 1][c + 1]

    # Bilinear formula
    return (v00 * (1 - t_frac) * (1 - a_frac)
            + v01 * (1 - t_frac) * a_frac
            + v10 * t_frac * (1 - a_frac)
            + v11 * t_frac * a_frac)


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

    Note: Voltage sag results are screening values. For projects with tight
    margins, validate with a full dynamic simulation (e.g., ETAP).

    Returns
    -------
    tuple(bool, float)
        (passes, voltage_sag_percent)
    """
    # Parallel generators: equivalent impedance = X"d / N (not sqrt(N))
    equiv_xd = xd_pu / num_units
    voltage_sag = (step_load_pct / 100) * equiv_xd * 100
    return (voltage_sag <= 10), voltage_sag


# ==============================================================================
# 3. FREQUENCY SCREENING (Swing Equation)
# ==============================================================================

def frequency_screening(n_running: int, unit_cap_mw: float,
                        p_avg_mw: float, step_mw: float,
                        gen_data: dict,
                        bess_mw: float = 0, bess_enabled: bool = False,
                        freq_hz: int = 60,
                        rocof_threshold: float = 2.0,
                        h_bess: float = 0.0) -> dict:
    """
    Frequency nadir and ROCOF screening per IEEE 1547-2018.

    ROCOF uses the deviation-based formulation with a 500 ms measurement
    window (IEEE Std 1547-2018, Section 6.5.2).

    Frequency stability results are screening values per IEEE 1547.
    These are not a substitute for a full dynamic simulation. For Tier III/IV
    projects or tight ROCOF margins, validate with ETAP or equivalent.

    Parameters
    ----------
    rocof_threshold : float
        IEEE 1547 ROCOF limit in Hz/s. Default 2.0 for islanded systems.
        Configurable per project requirements.
    h_bess : float
        Virtual inertia constant contributed by BESS (seconds). Default 0.

    Returns
    -------
    dict
        nadir_hz, rocof_hz_s, nadir_ok, rocof_ok, nadir_limit,
        rocof_limit, H_total, P_step_pu, rocof_pass_fail, notes
    """
    pf_gen = 0.85
    S_gen_mva = unit_cap_mw / pf_gen
    S_total_mva = n_running * S_gen_mva

    # Inertia
    H_mech = gen_data.get('inertia_h', 1.0)
    # BESS virtual inertia: use explicit h_bess if provided, else estimate
    if h_bess > 0:
        H_bess = h_bess
    elif bess_enabled and bess_mw > 0:
        bess_ratio = bess_mw / S_total_mva if S_total_mva > 0 else 0
        H_bess = 4.0 * min(1.0, bess_ratio / 0.2)
    else:
        H_bess = 0.0
    H_total = H_mech + H_bess

    # Per-unit step
    P_step_pu = step_mw / S_total_mva if S_total_mva > 0 else 1.0

    # Governor parameters
    R = 0.05      # 5% droop
    D = 2.0       # Data center PE load damping
    T_gov = 0.5   # Governor time constant (s)

    # IEEE 1547 ROCOF window: 500ms measurement period
    # Reference: IEEE Std 1547-2018, Section 6.5.2
    t_window = 0.500  # seconds

    # Frequency deviation from swing equation:
    # delta_f = (delta_P_loss / (2 * H * S_base)) * f_nominal * t
    # At t = t_window:
    delta_f_step = (step_mw / (2 * H_total * S_total_mva)) * freq_hz * t_window if (H_total > 0 and S_total_mva > 0) else freq_hz

    # BESS power injection reduces effective step loss
    if bess_enabled and bess_mw > 0:
        bess_coverage = min(bess_mw / step_mw, 1.0) if step_mw > 0 else 0
        delta_f_step *= (1 - bess_coverage * 0.7)

    # ROCOF = frequency deviation / measurement window
    rocof_calculated = delta_f_step / t_window

    # Nadir (unchanged analytical approach)
    delta_f_ss = (P_step_pu / (D + 1 / R)) * freq_hz
    overshoot = 1.0 + math.sqrt(T_gov / (4 * max(H_total, 0.5)))
    delta_f_nadir = delta_f_ss * overshoot

    if bess_enabled and bess_mw > 0:
        bess_pu = min(bess_mw / S_total_mva, P_step_pu) if S_total_mva > 0 else 0
        delta_f_nadir *= max(0.3, 1 - bess_pu / P_step_pu * 0.6) if P_step_pu > 0 else 1.0

    nadir_hz = max(freq_hz - delta_f_nadir, freq_hz - 5.0)

    nadir_limit = 59.5 if freq_hz == 60 else 49.5
    rocof_limit = rocof_threshold

    nadir_ok = nadir_hz >= nadir_limit
    rocof_ok = rocof_calculated <= rocof_limit

    rocof_pass_fail = "PASS" if rocof_ok else "FAIL"

    notes = []
    if not nadir_ok:
        notes.append(f"Nadir {nadir_hz:.2f} Hz < {nadir_limit} Hz — add inertia or BESS")
    if not rocof_ok:
        notes.append(f"ROCOF {rocof_calculated:.2f} Hz/s > {rocof_limit} Hz/s — add virtual inertia")
    if nadir_ok and rocof_ok:
        notes.append("Screening PASS — confirm with detailed dynamic simulation")
    notes.append(
        "Frequency stability results are screening values per IEEE 1547. "
        "For Tier III/IV projects or tight ROCOF margins, validate with ETAP or equivalent."
    )

    return {
        'nadir_hz': nadir_hz,
        'rocof_hz_s': rocof_calculated,
        'nadir_ok': nadir_ok,
        'rocof_ok': rocof_ok,
        'rocof_pass_fail': rocof_pass_fail,
        'nadir_limit': nadir_limit,
        'rocof_limit': rocof_limit,
        'H_total': H_total,
        'H_bess': H_bess,
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
    unit_availability: float = 0.93,
    project_years: int = 20,
) -> tuple:
    """
    Fleet availability using binomial N+X model with fixed unit availability.

    Industry standard for prime power generators: ~93% unit availability
    (4% scheduled maintenance + 3% unplanned failures).

    Parameters
    ----------
    n_total : int
        Total number of units in fleet (running + reserve).
    n_running : int
        Minimum number of units required to serve load.
    unit_availability : float
        Single-unit availability as decimal (e.g. 0.93).
        Default 0.93 per industry standard for prime power.
    project_years : int
        Project duration in years (used for timeline output).

    Returns
    -------
    tuple(float, list[float])
        (system_availability, availability_over_time)
        availability_over_time is constant (no aging degradation).
    """
    # System availability — binomial N+X
    # P(system up) = sum of P(k or more units available) for k >= n_running
    sys_avail = 0.0
    for k in range(n_running, n_total + 1):
        comb = math.comb(n_total, k)
        prob = comb * (unit_availability ** k) * ((1 - unit_availability) ** (n_total - k))
        sys_avail += prob

    # Flat availability over project life (no aging model)
    availability_over_time = [sys_avail] * project_years

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
                          methane_number: int = 80) -> dict:
    """
    Calculate generator derating using official Caterpillar lookup tables
    with bilinear interpolation.

    Uses three reference tables from the CAT Fuel Usage Guide:
      1. Methane Number → Power Deration Factor (1D interpolation)
      2. Temperature × Altitude → Altitude Deration Factor (bilinear)
      3. Temperature × Altitude → Aftercooler Heat Rejection Factor (bilinear)

    Combined derate = Methane Deration × Altitude Deration Factor.
    Derated Power = ISO Rating × Combined Derate Factor.
    Adjusted Aftercooler Heat Rejection = Nominal × ACHRF.

    Parameters
    ----------
    site_temp_c : float
        Inlet air temperature in °C. Clamped to [10, 50].
    site_alt_m : float
        Site altitude in meters above sea level. Clamped to [0, 3000].
    methane_number : int
        CAT Methane Number of the fuel gas. MN < 32 → cannot operate.

    Returns
    -------
    dict
        derate_factor : float — Combined factor (0.0–1.0)
        methane_deration : float — From MN table
        altitude_deration : float — From ADF table
        achrf : float — Aftercooler Heat Rejection Factor (≥ 1.0)
        methane_warning : str | None — Warning if MN < 32 or MN < 60
    """
    # ── Methane Number deration (1D) ──
    methane_warning = None
    if methane_number < 32:
        methane_deration = 0.0
        methane_warning = (
            "CAT Methane Number < 32: gas is not suitable for operation. "
            "Engine cannot run on this fuel quality."
        )
    elif methane_number < 60:
        methane_deration = _interp_1d(float(methane_number), _MN_XS, _MN_YS)
        methane_warning = (
            f"CAT Methane Number {methane_number} is below 60: "
            "significant power derating applied. Consider fuel conditioning."
        )
    else:
        methane_deration = _interp_1d(float(methane_number), _MN_XS, _MN_YS)

    # ── Altitude Deration Factor (bilinear) ──
    altitude_deration = _interp_2d(
        site_temp_c, site_alt_m, _ADF_TEMPS, _ADF_ALTS, _ADF_TABLE
    )

    # ── Aftercooler Heat Rejection Factor (bilinear) ──
    achrf = _interp_2d(
        site_temp_c, site_alt_m, _ADF_TEMPS, _ADF_ALTS, _ACHRF_TABLE
    )

    # ── Combined derate factor ──
    derate_factor = methane_deration * altitude_deration

    return {
        "derate_factor": round(derate_factor, 6),
        "methane_deration": round(methane_deration, 6),
        "altitude_deration": round(altitude_deration, 6),
        "achrf": round(achrf, 6),
        "methane_warning": methane_warning,
    }


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
    pipeline_cost_usd: float = 0,
    permitting_cost_usd: float = 0,
    commissioning_cost_usd: float = 0,
) -> dict:
    """
    Levelized Cost of Energy and NPV calculation.

    Pipeline, permits, and commissioning costs are optional. If left at zero,
    they are assumed included in the BOP/installation multiplier.

    Returns
    -------
    dict
        lcoe, npv, simple_payback_years, annual_total_cost, infrastructure_capex
    """
    if annual_energy_mwh <= 0 or project_years <= 0:
        return {'lcoe': 0, 'npv': 0, 'simple_payback_years': 0, 'annual_total_cost': 0,
                'annualized_capex': 0, 'crf': 0, 'infrastructure_capex': 0,
                'pipeline_cost_usd': 0, 'permitting_cost_usd': 0, 'commissioning_cost_usd': 0}

    # Infrastructure line items (amortized over project life alongside other CAPEX)
    infrastructure_capex = pipeline_cost_usd + permitting_cost_usd + commissioning_cost_usd
    total_capex_with_infra = total_capex + infrastructure_capex

    annual_total_cost = annual_om + annual_fuel_cost + carbon_cost_annual

    # CRF (Capital Recovery Factor)
    if wacc > 0:
        crf = (wacc * (1 + wacc) ** project_years) / ((1 + wacc) ** project_years - 1)
    else:
        crf = 1 / project_years

    annualized_capex = total_capex_with_infra * crf

    lcoe = (annualized_capex + annual_total_cost) / annual_energy_mwh

    # NPV of costs
    npv_costs = total_capex_with_infra
    for yr in range(1, project_years + 1):
        npv_costs += annual_total_cost / ((1 + wacc) ** yr)

    # Simple payback
    simple_payback = total_capex_with_infra / annual_total_cost if annual_total_cost > 0 else project_years

    return {
        'lcoe': lcoe,
        'npv': npv_costs,
        'simple_payback_years': min(simple_payback, project_years),
        'annual_total_cost': annual_total_cost,
        'annualized_capex': annualized_capex,
        'crf': crf,
        'infrastructure_capex': infrastructure_capex,
        'pipeline_cost_usd': pipeline_cost_usd,
        'permitting_cost_usd': permitting_cost_usd,
        'commissioning_cost_usd': commissioning_cost_usd,
    }
