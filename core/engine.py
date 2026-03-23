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
                              step_load_mw: float,
                              unit_capacity_mw: float) -> tuple:
    """
    Voltage sag screening for block-load step events (IEEE 3002.7).

    Formula:  ΔV% ≈ P_step / S_sc × 100
    where     S_sc  = N × S_rated / X"d   (short-circuit capacity)
              P_step = step load in MW

    The step load represents a sudden block-load energization (e.g., a
    data-hall coming online) expressed as a fraction of total system load.

    Note: Results are screening values. For projects with tight margins,
    validate with a full dynamic simulation (e.g., ETAP).

    Parameters
    ----------
    xd_pu : float
        Sub-transient reactance X"d per unit.
    num_units : int
        Number of generators online in parallel.
    step_load_mw : float
        Step load magnitude in MW.
    unit_capacity_mw : float
        Rated capacity of each generator in MW.

    Returns
    -------
    tuple(bool, float)
        (passes, voltage_sag_percent)
    """
    # System short-circuit capacity (MVA, assuming pf ≈ 1)
    s_sc = (num_units * unit_capacity_mw) / xd_pu if xd_pu > 0 else 1e9
    # Voltage sag: ΔV% ≈ P_step / (P_step + S_sc) × 100
    voltage_sag = (step_load_mw / (step_load_mw + s_sc)) * 100
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
        'H_per_unit': H_mech,       # Fix L (P06) — expose per-unit inertia
        'H_system': H_total,        # Fix L (P06) — system inertia (mech + BESS)
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
    p_total_peak: float = 0,
    load_step_pct: float = 0,
    bess_energy_mwh: float = 0,
) -> dict:
    """
    Calculate number of running units considering spinning reserve.

    Spinning reserve is now derived from physical contingencies:
      1. Worst load step: load_step_pct × p_total_peak
      2. N-1 contingency: loss of largest online generator at operating load
    The effective SR is the maximum of these two and the legacy user input.

    BESS SR credit is validated against:
      - Response time ≤ 10 s (Li-ion: ~200 ms — always passes)
      - Energy availability: available MWs ≥ required MWs over governor gap

    WITHOUT BESS:
      Generators must provide ALL spinning reserve as HEADROOM.
    WITH BESS (validated):
      BESS provides instant response; fewer generators needed.

    Returns
    -------
    dict
        n_units_running, load_per_unit_pct, spinning_reserve_mw,
        spinning_from_gens, spinning_from_bess, total_online_capacity,
        headroom_available, required_online_capacity,
        sr_required_mw, sr_user_mw, sr_user_below_physical,
        sr_dominant_contingency, load_step_mw, n1_mw,
        bess_sr_credit_valid, bess_sr_response_ok, bess_sr_energy_ok,
        bess_sr_available_mws, bess_sr_required_mws
    """
    # ── Physical SR requirement ──
    # Contingency 1: worst load step the system must absorb
    load_step_mw = (load_step_pct / 100.0) * p_total_peak if p_total_peak > 0 else 0

    # Contingency 2: N-1 — loss of the largest online generator
    # Use unit_capacity as proxy (exact load per unit determined after fleet sizing)
    n1_mw = unit_capacity

    # Physically required SR = worst of the two contingencies
    sr_required_mw = max(load_step_mw, n1_mw) if p_total_peak > 0 else 0

    # Legacy user input (deprecated as UI control in P04, kept as floor)
    sr_user_mw = p_avg_load * (spinning_reserve_pct / 100.0)

    # Effective SR: physical requirement cannot be overridden downward
    if p_total_peak > 0 and load_step_pct > 0:
        spinning_reserve_mw = max(sr_required_mw, sr_user_mw)
    else:
        # Fallback to legacy behavior when new params not provided
        spinning_reserve_mw = sr_user_mw

    # Diagnostic fields
    sr_user_below_physical = sr_user_mw < sr_required_mw
    sr_dominant_contingency = "load_step" if load_step_mw >= n1_mw else "N-1"

    # ── BESS SR credit: physical validation (Fix D — P04) ──
    BESS_RESPONSE_TIME_S    = 0.2    # Li-ion: ~200ms — always passes
    GOVERNOR_RESPONSE_GAP_S = 20.0   # Seconds until generators reach full governor response
    BESS_MIN_SOC_CREDIT     = 0.20   # Reserve 20% SoC for SR duty

    if use_bess and bess_power_mw > 0:
        bess_response_ok = BESS_RESPONSE_TIME_S <= 10.0  # always True for Li-ion

        bess_available_mws = bess_energy_mwh * (1.0 - BESS_MIN_SOC_CREDIT) * 3600.0
        bess_required_mws  = bess_power_mw * GOVERNOR_RESPONSE_GAP_S
        bess_energy_ok     = bess_available_mws >= bess_required_mws

        spinning_from_bess    = min(bess_power_mw, spinning_reserve_mw) \
                                if (bess_response_ok and bess_energy_ok) else 0.0
        bess_sr_credit_valid  = bess_response_ok and bess_energy_ok
        bess_sr_response_ok   = bess_response_ok
        bess_sr_energy_ok     = bess_energy_ok
        bess_sr_available_mws = bess_available_mws
        bess_sr_required_mws  = bess_required_mws
    else:
        spinning_from_bess    = 0.0
        bess_sr_credit_valid  = False
        bess_sr_response_ok   = False
        bess_sr_energy_ok     = False
        bess_sr_available_mws = 0.0
        bess_sr_required_mws  = 0.0

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
        'sr_required_mw': sr_required_mw,
        'sr_user_mw': sr_user_mw,
        'sr_user_below_physical': sr_user_below_physical,
        'sr_dominant_contingency': sr_dominant_contingency,
        'load_step_mw': load_step_mw,
        'n1_mw': n1_mw,
        'bess_sr_credit_valid': bess_sr_credit_valid,
        'bess_sr_response_ok': bess_sr_response_ok,
        'bess_sr_energy_ok': bess_sr_energy_ok,
        'bess_sr_available_mws': bess_sr_available_mws,
        'bess_sr_required_mws': bess_sr_required_mws,
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
# 8a. POD ARCHITECTURE FLEET OPTIMIZER (P05)
# ==============================================================================

def _binomial_availability(n_total: int, n_required: int, a_gen: float) -> float:
    """P(at least n_required of n_total generators available)."""
    q = 1.0 - a_gen
    return sum(
        math.comb(n_total, k) * (a_gen ** k) * (q ** (n_total - k))
        for k in range(n_required, n_total + 1)
    )


def pod_fleet_optimizer(
    p_total_peak: float,
    unit_site_cap: float,
    a_gen: float,
    avail_req: float,
    max_normal_loading: float,
    max_pods: int = 20,
    max_per_pod: int = 40,
) -> dict:
    """
    Pod architecture fleet optimizer for prime power data centers.

    All generators run simultaneously at partial load. Redundancy is via
    N+1 pod: losing one full pod leaves (N_pods-1) pods covering 100%
    of the DC load.

    Constraints:
      1. Physical N+1 pod: (N_pods-1) * n_per_pod * unit_site_cap >= p_total_peak
      2. Normal loading:   p_total_peak / (n_total * unit_site_cap) <= max_normal_loading
      3. Statistical:      binomial(n_total, n_required, a_gen) >= avail_req

    Sorted by (n_total ASC, N_pods ASC) — minimum fleet first.

    Parameters
    ----------
    p_total_peak : float
        Corrected peak load in MW (from P03).
    unit_site_cap : float
        Single generator site-rated capacity in MW.
    a_gen : float
        Generator availability (MTBF/(MTBF+MTTR)), fractional.
    avail_req : float
        System availability target, fractional (e.g. 0.9999).
    max_normal_loading : float
        Maximum sustainable loading fraction (prime_power_kw / standby_kw).
    max_pods : int
        Maximum pods to search (default 20).
    max_per_pod : int
        Maximum generators per pod to search (default 40).

    Returns
    -------
    dict or None
        Pod fleet result with n_pods, n_per_pod, n_total, etc.
        None if no valid solution found.
    """
    n_required = math.ceil(p_total_peak / unit_site_cap)
    best = None

    for n_pods in range(2, max_pods + 1):
        for n_per in range(1, max_per_pod + 1):
            n_total = n_pods * n_per

            if n_total < n_required:
                continue

            # Constraint 1: Physical N+1 pod
            contingency_cap = (n_pods - 1) * n_per * unit_site_cap
            if contingency_cap < p_total_peak:
                continue

            # Constraint 2: Normal loading cap
            norm_loading = p_total_peak / (n_total * unit_site_cap)
            if norm_loading > max_normal_loading:
                continue

            # Constraint 3: Statistical availability
            a_sys = _binomial_availability(n_total, n_required, a_gen)
            if a_sys < avail_req:
                continue

            # First valid solution found at minimum n_total
            if best is None or n_total < best['n_total']:
                best = {
                    'n_pods':               n_pods,
                    'n_per_pod':            n_per,
                    'n_total':              n_total,
                    'n_running':            n_total,   # all pods run simultaneously
                    'n_reserve':            0,         # no cold standby — redundancy via pods
                    'installed_cap':        n_total * unit_site_cap,
                    'cap_contingency':      contingency_cap,
                    'loading_normal_pct':   norm_loading * 100.0,
                    'loading_contingency_pct': (p_total_peak / contingency_cap) * 100.0,
                    'a_system_calculated':  a_sys,
                    'n_required_min':       n_required,
                }
            # Once n_total starts increasing, we have the minimum — break inner loop
            elif n_total > best['n_total']:
                break

        if best and n_pods > best['n_pods'] + 2:
            # Safety: stop outer loop once solutions get worse
            break

    return best


# ==============================================================================
# 8b. LEGACY FLEET SIZE OPTIMIZATION (preserved for backward compatibility)
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


# ==============================================================================
# 15. DUAL-FUEL & LNG LOGISTICS
# ==============================================================================

def calculate_lng_logistics(
    p_avg_mw: float,
    fleet_efficiency: float,
    lng_days: int = 5,
    gas_price_lng: float = 8.0,
    gas_price_pipeline: float = 3.5,
    lng_backup_pct: float = 100.0,
) -> dict:
    """
    LNG virtual pipeline logistics: daily consumption, storage sizing,
    number of tanks, truck traffic, and infrastructure CAPEX.

    Parameters
    ----------
    p_avg_mw : float
        Average load (MW).
    fleet_efficiency : float
        Fleet electrical efficiency (decimal).
    lng_days : int
        LNG storage autonomy in days.
    gas_price_lng : float
        LNG price in $/MMBtu.
    gas_price_pipeline : float
        Pipeline gas price in $/MMBtu.
    lng_backup_pct : float
        % of load to be covered by LNG (for dual-fuel mode).

    Returns
    -------
    dict
        daily_consumption_gal, storage_gallons, n_tanks, tank_capacity_gal,
        truck_deliveries_per_week, lng_capex_usd, blended_gas_price
    """
    if fleet_efficiency <= 0:
        return {
            'daily_consumption_gal': 0, 'storage_gallons': 0,
            'n_tanks': 0, 'tank_capacity_gal': 0,
            'truck_deliveries_per_week': 0, 'lng_capex_usd': 0,
            'blended_gas_price': gas_price_pipeline,
        }

    # Fuel consumption
    total_fuel_mw = p_avg_mw * (lng_backup_pct / 100) / fleet_efficiency
    total_fuel_mmbtu_hr = total_fuel_mw * 3.412
    daily_mmbtu = total_fuel_mmbtu_hr * 24

    # LNG: ~82.6 MJ/gal LHV → 0.0783 MMBtu/gal
    mmbtu_per_gal = 0.0783
    daily_gal = daily_mmbtu / mmbtu_per_gal

    # Storage sizing
    storage_gal = daily_gal * lng_days

    # Tank sizing (standard 15,000 gal horizontal tanks)
    tank_capacity = 15000
    n_tanks = max(1, math.ceil(storage_gal / tank_capacity))

    # Truck deliveries (10,000 gal per truck)
    truck_capacity = 10000
    weekly_gal = daily_gal * 7
    trucks_per_week = max(1, math.ceil(weekly_gal / truck_capacity))

    # LNG infrastructure CAPEX
    tank_cost = 250000  # per tank
    vaporizer_cost = 150000 * max(1, math.ceil(total_fuel_mw / 5))
    piping_cost = 75000 * n_tanks
    lng_capex = n_tanks * tank_cost + vaporizer_cost + piping_cost

    # Blended gas price (for dual-fuel)
    blended = gas_price_pipeline * (1 - lng_backup_pct / 100) + gas_price_lng * (lng_backup_pct / 100)

    return {
        'daily_consumption_gal': daily_gal,
        'storage_gallons': storage_gal,
        'n_tanks': n_tanks,
        'tank_capacity_gal': tank_capacity,
        'truck_deliveries_per_week': trucks_per_week,
        'lng_capex_usd': lng_capex,
        'blended_gas_price': blended,
        'daily_mmbtu': daily_mmbtu,
        'storage_mmbtu': daily_mmbtu * lng_days,
    }


def calculate_pipeline_capex(
    distance_km: float = 1.0,
    diameter_inch: float = 6.0,
    terrain_factor: float = 1.0,
) -> float:
    """
    Pipeline infrastructure CAPEX based on diameter and distance.

    Base cost: ~$500/m for 6" pipe + terrain multiplier.

    Returns
    -------
    float
        Total pipeline CAPEX in USD.
    """
    base_cost_per_m = 500 * (diameter_inch / 6) ** 1.4
    return base_cost_per_m * distance_km * 1000 * terrain_factor


# ==============================================================================
# 16. CHP / TRI-GENERATION
# ==============================================================================

def calculate_chp(
    n_running: int,
    unit_cap_mw: float,
    gen_data: dict,
    load_pct: float = 75.0,
    chp_recovery_eff: float = 0.50,
    absorption_cop: float = 0.70,
    cooling_load_mw: float = 0.0,
) -> dict:
    """
    Combined Heat and Power / Tri-Generation calculations.

    Parameters
    ----------
    chp_recovery_eff : float
        Fraction of waste heat recoverable (typically 0.40-0.60).
    absorption_cop : float
        Absorption chiller COP (typically 0.65-0.80).
    cooling_load_mw : float
        Site cooling demand in MW thermal.

    Returns
    -------
    dict
        waste_heat_mw, recovered_heat_mw, chp_efficiency,
        cooling_from_absorption_mw, cooling_coverage_pct,
        pue_improvement, chp_capex_usd
    """
    elec_output = n_running * unit_cap_mw * (load_pct / 100)
    elec_eff = gen_data.get('electrical_efficiency', 0.40)

    # Waste heat = fuel input - electrical output
    fuel_input = elec_output / elec_eff if elec_eff > 0 else 0
    waste_heat = fuel_input - elec_output

    # Recoverable heat
    recovered_heat = waste_heat * chp_recovery_eff

    # Combined efficiency
    chp_efficiency = (elec_output + recovered_heat) / fuel_input if fuel_input > 0 else 0

    # Absorption chiller cooling
    cooling_from_absorption = recovered_heat * absorption_cop

    # Cooling coverage
    cooling_coverage = min(1.0, cooling_from_absorption / cooling_load_mw) if cooling_load_mw > 0 else 0

    # PUE improvement from CHP
    # Typical: base PUE 1.4 → with CHP can reach 1.2
    pue_improvement = min(0.20, cooling_coverage * 0.20)

    # CHP CAPEX (heat recovery + absorption chiller)
    hrsg_cost = recovered_heat * 200000  # $/MW_thermal
    absorption_cost = cooling_from_absorption * 350000 if cooling_from_absorption > 0 else 0
    chp_capex = hrsg_cost + absorption_cost

    # Water usage (make-up water for cooling tower)
    wue = recovered_heat * 0.5  # L/kWh simplified

    return {
        'waste_heat_mw': waste_heat,
        'recovered_heat_mw': recovered_heat,
        'chp_efficiency': chp_efficiency,
        'cooling_from_absorption_mw': cooling_from_absorption,
        'cooling_coverage_pct': cooling_coverage * 100,
        'pue_improvement': pue_improvement,
        'chp_capex_usd': chp_capex,
        'fuel_input_mw': fuel_input,
        'wue_l_kwh': wue,
    }


# ==============================================================================
# 17. EMISSIONS CONTROL & COMPLIANCE
# ==============================================================================

def calculate_emissions_control_capex(
    n_total: int,
    unit_cap_mw: float,
    include_scr: bool = False,
    include_oxicat: bool = False,
    force_scr: bool = False,
) -> dict:
    """
    Emissions control equipment CAPEX.

    SCR (Selective Catalytic Reduction) — reduces NOx by 90%.
    OxiCat (Oxidation Catalyst) — reduces CO by 80%.

    Returns
    -------
    dict
        scr_capex, oxicat_capex, total_capex, nox_reduction_pct, co_reduction_pct
    """
    plant_capacity_mw = n_total * unit_cap_mw

    scr_capex = 0
    oxicat_capex = 0
    nox_reduction = 0
    co_reduction = 0

    if include_scr or force_scr:
        # SCR: ~$60-80/kW for reciprocating engines
        scr_cost_per_kw = 70
        scr_capex = plant_capacity_mw * 1000 * scr_cost_per_kw
        nox_reduction = 90.0

    if include_oxicat:
        # OxiCat: ~$15-25/kW
        oxicat_cost_per_kw = 20
        oxicat_capex = plant_capacity_mw * 1000 * oxicat_cost_per_kw
        co_reduction = 80.0

    return {
        'scr_capex': scr_capex,
        'oxicat_capex': oxicat_capex,
        'total_capex': scr_capex + oxicat_capex,
        'nox_reduction_pct': nox_reduction,
        'co_reduction_pct': co_reduction,
    }


def check_emissions_compliance(
    nox_g_kwh: float,
    co_g_kwh: float,
    co2_kg_mwh: float,
    unit_cap_mw: float,
    n_running: int,
    nox_tpy: float = 0.0,
    co_tpy: float = 0.0,
    co2_tpy: float = 0.0,
) -> list:
    """
    Check emissions against worldwide regulatory frameworks for NOx, CO, and CO₂.

    Frameworks:
    - US EPA NSPS (40 CFR Part 60 Subpart JJJJ)
    - US Title V (major source threshold)
    - EU MCP Directive (Medium Combustion Plant, 2015/2193)
    - EU IED / BAT-AEL (Industrial Emissions Directive, >50 MWth)
    - CARB (California Air Resources Board)
    - IFC / World Bank (Environmental, Health, and Safety Guidelines)

    Returns
    -------
    list[dict]
        Each dict has: regulation, parameter, limit, actual, unit,
        compliant (bool), notes
    """
    # Cast to native Python types to avoid numpy.bool_ serialisation errors
    nox_g_kwh = float(nox_g_kwh)
    co_g_kwh = float(co_g_kwh)
    co2_kg_mwh = float(co2_kg_mwh)
    nox_tpy = float(nox_tpy)
    co_tpy = float(co_tpy)
    co2_tpy = float(co2_tpy)

    total_cap_mw = float(unit_cap_mw * n_running)
    results = []

    # ── Unit conversions ──
    # g/kWh → g/bhp-hr (1 kWh = 1.341 bhp-hr → multiply by 0.7457)
    nox_g_bhphr = nox_g_kwh * 0.7457
    co_g_bhphr = co_g_kwh * 0.7457

    # g/kWh → mg/Nm³ @15% O2 for lean-burn gas engines
    # Conversion factor ≈ 4.5 (depends on engine efficiency & excess air)
    nox_mg_nm3 = nox_g_kwh * 4500
    co_mg_nm3 = co_g_kwh * 4500

    # mg/Nm³ → ppmvd @15% O2  (MW_NOx=46: 1 ppm ≈ 2.05 mg/Nm³)
    nox_ppm = nox_mg_nm3 / 2.05
    # mg/Nm³ → ppmvd @15% O2  (MW_CO=28: 1 ppm ≈ 1.25 mg/Nm³)
    co_ppm = co_mg_nm3 / 1.25

    # ════════════════════════════════════════════════════════════════
    # NOx REGULATIONS
    # ════════════════════════════════════════════════════════════════

    # 1. US EPA NSPS Subpart JJJJ — NOx ≤ 1.0 g/bhp-hr (lean-burn SI > 500 hp)
    results.append({
        'regulation': 'US EPA NSPS (JJJJ)',
        'parameter': 'NOx',
        'limit': 1.0,
        'actual': round(nox_g_bhphr, 3),
        'unit': 'g/bhp-hr',
        'compliant': nox_g_bhphr <= 1.0,
        'notes': 'Lean-burn SI engines > 500 hp',
    })

    # 2. US Title V — NOx ≤ 100 tons/yr (major source threshold)
    results.append({
        'regulation': 'US Title V',
        'parameter': 'NOx (annual)',
        'limit': 100.0,
        'actual': round(nox_tpy, 1),
        'unit': 'tons/year',
        'compliant': nox_tpy <= 100.0,
        'notes': 'Major source threshold; may require Title V permit',
    })

    # 3. EU MCP Directive (1–50 MWth) — NOx ≤ 190 mg/Nm³ @15% O2
    results.append({
        'regulation': 'EU MCP Directive',
        'parameter': 'NOx',
        'limit': 190.0,
        'actual': round(nox_mg_nm3, 1),
        'unit': 'mg/Nm³ @15% O2',
        'compliant': nox_mg_nm3 <= 190.0,
        'notes': 'New gas engines 1–50 MWth (Directive 2015/2193)',
    })

    # 4. EU IED BAT-AEL (>50 MWth) — NOx ≤ 100 mg/Nm³ @15% O2
    ied_applicable = total_cap_mw > 50
    results.append({
        'regulation': 'EU IED (BAT)',
        'parameter': 'NOx',
        'limit': 100.0,
        'actual': round(nox_mg_nm3, 1),
        'unit': 'mg/Nm³ @15% O2',
        'compliant': nox_mg_nm3 <= 100.0 if ied_applicable else True,
        'notes': 'BAT-AEL for gas engines >50 MWth' if ied_applicable
                 else 'Plant <50 MWth — IED not applicable',
    })

    # 5. CARB — NOx ≤ 11 ppmvd @15% O2
    results.append({
        'regulation': 'CARB (California)',
        'parameter': 'NOx',
        'limit': 11.0,
        'actual': round(nox_ppm, 1),
        'unit': 'ppmvd @15% O2',
        'compliant': nox_ppm <= 11.0,
        'notes': 'Most stringent US state regulation',
    })

    # ════════════════════════════════════════════════════════════════
    # CO REGULATIONS
    # ════════════════════════════════════════════════════════════════

    # 6. US EPA NSPS Subpart JJJJ — CO ≤ 2.0 g/bhp-hr (lean-burn SI > 500 hp)
    results.append({
        'regulation': 'US EPA NSPS (JJJJ)',
        'parameter': 'CO',
        'limit': 2.0,
        'actual': round(co_g_bhphr, 3),
        'unit': 'g/bhp-hr',
        'compliant': co_g_bhphr <= 2.0,
        'notes': 'Lean-burn SI engines > 500 hp',
    })

    # 7. US Title V — CO ≤ 100 tons/yr (major source threshold)
    results.append({
        'regulation': 'US Title V',
        'parameter': 'CO (annual)',
        'limit': 100.0,
        'actual': round(co_tpy, 1),
        'unit': 'tons/year',
        'compliant': co_tpy <= 100.0,
        'notes': 'Major source threshold; may require Title V permit',
    })

    # 8. EU MCP Directive (1–50 MWth) — CO ≤ 500 mg/Nm³ @15% O2
    results.append({
        'regulation': 'EU MCP Directive',
        'parameter': 'CO',
        'limit': 500.0,
        'actual': round(co_mg_nm3, 1),
        'unit': 'mg/Nm³ @15% O2',
        'compliant': co_mg_nm3 <= 500.0,
        'notes': 'New gas engines 1–50 MWth (Directive 2015/2193)',
    })

    # 9. EU IED BAT-AEL (>50 MWth) — CO ≤ 100 mg/Nm³ @15% O2
    results.append({
        'regulation': 'EU IED (BAT)',
        'parameter': 'CO',
        'limit': 100.0,
        'actual': round(co_mg_nm3, 1),
        'unit': 'mg/Nm³ @15% O2',
        'compliant': co_mg_nm3 <= 100.0 if ied_applicable else True,
        'notes': 'BAT-AEL for gas engines >50 MWth' if ied_applicable
                 else 'Plant <50 MWth — IED not applicable',
    })

    # 10. CARB — CO ≤ 250 ppmvd @15% O2
    results.append({
        'regulation': 'CARB (California)',
        'parameter': 'CO',
        'limit': 250.0,
        'actual': round(co_ppm, 1),
        'unit': 'ppmvd @15% O2',
        'compliant': co_ppm <= 250.0,
        'notes': 'Stationary gas engines',
    })

    # ════════════════════════════════════════════════════════════════
    # CO₂ REGULATIONS
    # ════════════════════════════════════════════════════════════════

    # 11. IFC / World Bank EHS Guidelines — CO₂ ≤ 400 kg/MWh (gas-fired)
    results.append({
        'regulation': 'IFC / World Bank',
        'parameter': 'CO₂',
        'limit': 400.0,
        'actual': round(co2_kg_mwh, 1),
        'unit': 'kg/MWh',
        'compliant': co2_kg_mwh <= 400.0,
        'notes': 'EHS guideline for gas-fired thermal power',
    })

    # 12. EU ETS — reporting threshold (>20 MWth)
    thermal_mw = total_cap_mw / 0.40  # approximate thermal input
    results.append({
        'regulation': 'EU ETS',
        'parameter': 'CO₂ (annual)',
        'limit': 'N/A',
        'actual': f"{co2_tpy:,.0f}",
        'unit': 'tons/year',
        'compliant': thermal_mw < 20,
        'notes': f'{"Reporting required (>20 MWth)" if thermal_mw >= 20 else "Below 20 MWth threshold — exempt"}',
    })

    return results


# ==============================================================================
# 18. GAS PRICE SENSITIVITY
# ==============================================================================

def gas_price_sensitivity(
    base_gas_price: float,
    annual_fuel_mmbtu: float,
    annual_om_cost: float,
    total_capex: float,
    annual_energy_kwh: float,
    wacc: float,
    project_years: int,
    benchmark_price: float = 0.12,
) -> dict:
    """
    Gas price sensitivity analysis.

    Calculates LCOE at multiple gas price points and finds breakeven
    vs grid benchmark.

    Returns
    -------
    dict
        prices: list[float], lcoes: list[float], breakeven_price: float|None
    """
    if annual_energy_kwh <= 0 or project_years <= 0:
        return {'prices': [], 'lcoes': [], 'breakeven_price': None}

    # CRF
    if wacc > 0:
        crf = (wacc * (1 + wacc) ** project_years) / ((1 + wacc) ** project_years - 1)
    else:
        crf = 1.0 / project_years

    annualized_capex = total_capex * crf
    heat_rate_mmbtu_kwh = annual_fuel_mmbtu / annual_energy_kwh if annual_energy_kwh > 0 else 0

    # Price sweep from $1 to $15/MMBtu
    prices = [round(p * 0.5, 1) for p in range(2, 31)]
    lcoes = []
    breakeven = None

    for gp in prices:
        fuel_cost = gp * annual_fuel_mmbtu * (gp / base_gas_price) if base_gas_price > 0 else 0
        total_annual = annualized_capex + fuel_cost + annual_om_cost
        lcoe = total_annual / annual_energy_kwh
        lcoes.append(lcoe)

        if breakeven is None and lcoe > benchmark_price:
            # Linear interpolation for breakeven
            if len(lcoes) >= 2:
                prev_lcoe = lcoes[-2]
                prev_price = prices[len(lcoes) - 2]
                if lcoe != prev_lcoe:
                    frac = (benchmark_price - prev_lcoe) / (lcoe - prev_lcoe)
                    breakeven = prev_price + frac * (gp - prev_price)

    return {
        'prices': prices,
        'lcoes': lcoes,
        'breakeven_price': breakeven,
    }


# ==============================================================================
# 19. NET EFFICIENCY & HEAT RATE CONVERSIONS
# ==============================================================================

def calculate_net_efficiency_and_heat_rate(
    gross_efficiency: float,
    aux_load_pct: float = 4.0,
    dist_loss_pct: float = 1.5,
) -> dict:
    """
    Net efficiency and heat rate conversions.

    Net Efficiency = Gross × (1 - aux_load/100) × (1 - dist_loss/100)
    Heat Rate LHV = 3412 / efficiency (BTU/kWh)
    Heat Rate HHV = Heat Rate LHV × 1.108 (for natural gas)
    Heat Rate MJ = BTU × 0.001055

    Returns
    -------
    dict
        net_efficiency, heat_rate_lhv_btu, heat_rate_hhv_btu,
        heat_rate_lhv_mj, heat_rate_hhv_mj
    """
    net_eff = gross_efficiency * (1 - aux_load_pct / 100) * (1 - dist_loss_pct / 100)

    hr_lhv_btu = 3412 / net_eff if net_eff > 0 else 0
    hr_hhv_btu = hr_lhv_btu * 1.108  # HHV/LHV ratio for natural gas
    hr_lhv_mj = hr_lhv_btu * 0.001055
    hr_hhv_mj = hr_hhv_btu * 0.001055

    return {
        'net_efficiency': net_eff,
        'gross_efficiency': gross_efficiency,
        'aux_load_pct': aux_load_pct,
        'dist_loss_pct': dist_loss_pct,
        'heat_rate_lhv_btu': hr_lhv_btu,
        'heat_rate_hhv_btu': hr_hhv_btu,
        'heat_rate_lhv_mj': hr_lhv_mj,
        'heat_rate_hhv_mj': hr_hhv_mj,
    }


# ==============================================================================
# 20. PHASING & MODULAR DEPLOYMENT
# ==============================================================================

def calculate_phasing(
    total_load_mw: float,
    unit_cap_mw: float,
    n_total: int,
    total_capex: float,
    n_phases: int = 3,
    months_between_phases: int = 6,
    phase_pcts: list = None,
) -> dict:
    """
    Multi-phase deployment planning.

    Parameters
    ----------
    n_phases : int
        Number of phases (1-5).
    months_between_phases : int
        Months between each phase start.
    phase_pcts : list[float]
        Percentage of total capacity per phase. If None, distributed equally.

    Returns
    -------
    dict
        phases: list[dict], total_months, phase1_capex, deferred_capex
    """
    if phase_pcts is None:
        phase_pcts = [100.0 / n_phases] * n_phases

    # Normalize to 100%
    total_pct = sum(phase_pcts)
    if total_pct > 0:
        phase_pcts = [p / total_pct * 100 for p in phase_pcts]

    phases = []
    cumulative_gens = 0
    cumulative_cap = 0
    cumulative_capex = 0

    for i, pct in enumerate(phase_pcts):
        phase_gens = max(1, round(n_total * pct / 100))
        phase_cap = phase_gens * unit_cap_mw
        phase_capex = total_capex * (pct / 100)
        start_month = i * months_between_phases
        cumulative_gens += phase_gens
        cumulative_cap += phase_cap
        cumulative_capex += phase_capex

        phases.append({
            'phase': i + 1,
            'start_month': start_month,
            'generators': phase_gens,
            'capacity_mw': phase_cap,
            'pct_of_total': pct,
            'capex': phase_capex,
            'cumulative_gens': min(cumulative_gens, n_total),
            'cumulative_cap_mw': min(cumulative_cap, n_total * unit_cap_mw),
            'cumulative_capex': cumulative_capex,
        })

    total_months = (n_phases - 1) * months_between_phases + 6  # +6 for commissioning

    return {
        'phases': phases,
        'n_phases': n_phases,
        'total_months': total_months,
        'phase1_capex': phases[0]['capex'] if phases else 0,
        'deferred_capex': total_capex - (phases[0]['capex'] if phases else 0),
        'time_to_first_power_months': 6,  # typical construction + commissioning
    }


# ==============================================================================
# 21. DESIGN VALIDATION SCORECARD
# ==============================================================================

def design_validation_scorecard(
    system_availability: float,
    avail_req: float,
    spinning_reserve_mw: float,
    spinning_required_mw: float,
    voltage_sag: float,
    load_per_unit_pct: float,
    bess_power_mw: float,
    step_load_mw: float,
    nadir_hz: float,
    nadir_limit: float,
    rocof_hz_s: float,
    rocof_limit: float,
    n_reserve: int,
    n_pods: int = 0,
    n_per_pod: int = 0,
) -> list:
    """
    8-point design validation scorecard.

    Returns
    -------
    list[dict]
        Each dict: check_name, passed (bool), actual, requirement, notes
    """
    checks = []

    # 1. Availability (system_availability is decimal, avail_req is %)
    avail_pct = system_availability * 100
    checks.append({
        'check': 'System Availability',
        'passed': avail_pct >= avail_req,
        'actual': f'{avail_pct:.4f}%',
        'requirement': f'>= {avail_req}%',
        'notes': '' if avail_pct >= avail_req else 'Add reserve units or BESS',
    })

    # 2. Spinning Reserve
    checks.append({
        'check': 'Spinning Reserve',
        'passed': spinning_reserve_mw >= spinning_required_mw * 0.95,
        'actual': f'{spinning_reserve_mw:.2f} MW',
        'requirement': f'>= {spinning_required_mw:.2f} MW',
        'notes': '',
    })

    # 3. Voltage Sag
    checks.append({
        'check': 'Voltage Sag (Step Load)',
        'passed': voltage_sag <= 10.0,
        'actual': f'{voltage_sag:.1f}%',
        'requirement': '<= 10%',
        'notes': '' if voltage_sag <= 10 else 'Add units or BESS for step support',
    })

    # 4. Load per Unit (tiered: >100% overload, 76-100% optimal, 60-75% OK, <60% low eff)
    if load_per_unit_pct > 100.0:
        load_status = 'OVERLOAD'
        load_passed = False
        load_notes = 'Exceeds rated capacity — reduce load or add units'
    elif load_per_unit_pct >= 76.0:
        load_status = 'OPTIMAL'
        load_passed = True
        load_notes = ''
    elif load_per_unit_pct >= 60.0:
        load_status = 'OK'
        load_passed = True
        load_notes = 'Acceptable but below optimal efficiency range'
    else:
        load_status = 'LOW EFFICIENCY'
        load_passed = False
        load_notes = 'Below 60% — poor fuel efficiency, consider fewer larger units'
    checks.append({
        'check': 'Load per Unit',
        'passed': load_passed,
        'actual': f'{load_per_unit_pct:.1f}% ({load_status})',
        'requirement': '76-100% optimal',
        'notes': load_notes,
    })

    # 5. BESS vs Step Load
    bess_covers_step = bess_power_mw >= step_load_mw * 0.8 if step_load_mw > 0 else True
    checks.append({
        'check': 'BESS Step Coverage',
        'passed': bess_covers_step,
        'actual': f'{bess_power_mw:.2f} MW',
        'requirement': f'>= {step_load_mw * 0.8:.2f} MW',
        'notes': '80% of step load covered by BESS',
    })

    # 6. Frequency Nadir
    checks.append({
        'check': 'Frequency Nadir',
        'passed': nadir_hz >= nadir_limit,
        'actual': f'{nadir_hz:.2f} Hz',
        'requirement': f'>= {nadir_limit} Hz',
        'notes': '' if nadir_hz >= nadir_limit else 'Add inertia or BESS virtual inertia',
    })

    # 7. ROCOF
    checks.append({
        'check': 'ROCOF (IEEE 1547)',
        'passed': rocof_hz_s <= rocof_limit,
        'actual': f'{rocof_hz_s:.2f} Hz/s',
        'requirement': f'<= {rocof_limit} Hz/s',
        'notes': '',
    })

    # 8. N+X Redundancy (pod-level or legacy)
    if n_pods > 0:
        pod_redundancy_ok = n_pods >= 2
        checks.append({
            'check': 'N+1 Pod Redundancy',
            'passed': pod_redundancy_ok,
            'actual': f'{n_pods} pods × {n_per_pod} gens',
            'requirement': 'N≥2 pods',
            'notes': '' if pod_redundancy_ok else 'Single pod — no redundancy',
        })
    else:
        checks.append({
            'check': 'N+X Redundancy',
            'passed': n_reserve >= 1,
            'actual': f'N+{n_reserve}',
            'requirement': '>= N+1',
            'notes': '' if n_reserve >= 1 else 'No reserve units — single point of failure',
        })

    return checks


# ==============================================================================
# 22. LCOE RECOMMENDER
# ==============================================================================

def lcoe_gap_recommender(
    lcoe: float,
    target_lcoe: float,
    gen_data: dict,
    n_running: int,
    n_reserve: int,
    use_bess: bool,
    include_chp: bool,
    enable_depreciation: bool,
) -> list:
    """
    Recommend strategies to close LCOE gap vs target.

    Returns
    -------
    list[dict]
        Each dict: strategy, potential_savings_pct, description, applicable
    """
    gap = lcoe - target_lcoe
    if gap <= 0:
        return [{'strategy': 'On Target', 'potential_savings_pct': 0,
                 'description': 'LCOE meets or beats target', 'applicable': True}]

    strategies = []

    # 1. Enable CHP (if not already)
    if not include_chp:
        strategies.append({
            'strategy': 'Enable CHP/Cogeneration',
            'potential_savings_pct': 8.0,
            'description': 'Recover waste heat → improve overall efficiency by 15-20%',
            'applicable': True,
        })

    # 2. Optimize fleet loading
    strategies.append({
        'strategy': 'Optimize Fleet Loading',
        'potential_savings_pct': 5.0,
        'description': 'Target 70-80% load per unit for peak efficiency',
        'applicable': True,
    })

    # 3. Enable MACRS depreciation
    if not enable_depreciation:
        strategies.append({
            'strategy': 'Enable MACRS Depreciation',
            'potential_savings_pct': 4.0,
            'description': '5-year accelerated depreciation tax shield',
            'applicable': True,
        })

    # 4. Reduce redundancy (if over-provisioned)
    if n_reserve > 3:
        strategies.append({
            'strategy': 'Reduce Reserve Units',
            'potential_savings_pct': 3.0,
            'description': f'Current N+{n_reserve} may be over-provisioned with BESS',
            'applicable': use_bess,
        })

    # 5. Technology switch
    strategies.append({
        'strategy': 'Consider Higher Efficiency Model',
        'potential_savings_pct': 6.0,
        'description': 'Switch to model with higher electrical efficiency',
        'applicable': gen_data.get('electrical_efficiency', 0) < 0.45,
    })

    return strategies


# ==============================================================================
# 23. FOOTPRINT OPTIMIZATION
# ==============================================================================

def footprint_optimization_recommendations(
    current_area_m2: float,
    max_area_m2: float,
    gen_data: dict,
    n_total: int,
    n_reserve: int,
    use_bess: bool,
    available_generators: dict = None,
) -> list:
    """
    Recommend ways to reduce plant footprint.

    Returns
    -------
    list[dict]
        Each dict: recommendation, area_savings_m2, feasibility, notes
    """
    recommendations = []
    overshoot = current_area_m2 - max_area_m2

    # 1. Technology switch to higher power density
    if available_generators:
        current_density = gen_data.get('power_density_mw_per_m2', 0.010)
        for model, data in available_generators.items():
            if data.get('power_density_mw_per_m2', 0) > current_density * 1.3:
                new_area = current_area_m2 * (current_density / data['power_density_mw_per_m2'])
                savings = current_area_m2 - new_area
                recommendations.append({
                    'recommendation': f'Switch to {model}',
                    'area_savings_m2': savings,
                    'feasibility': 'Medium',
                    'notes': f'Higher power density: {data["power_density_mw_per_m2"]:.3f} MW/m² vs {current_density:.3f}',
                })

    # 2. Reduce redundancy
    if n_reserve > 2:
        unit_area = gen_data.get('iso_rating_mw', 2.5) / gen_data.get('power_density_mw_per_m2', 0.010)
        removable = n_reserve - 1
        savings = removable * unit_area
        recommendations.append({
            'recommendation': f'Reduce reserves from N+{n_reserve} to N+1',
            'area_savings_m2': savings,
            'feasibility': 'High' if use_bess else 'Low',
            'notes': 'BESS compensates for fewer reserves' if use_bess else 'Requires BESS to maintain availability',
        })

    # 3. Vertical/compact arrangement
    recommendations.append({
        'recommendation': 'Compact layout / multi-level',
        'area_savings_m2': current_area_m2 * 0.15,
        'feasibility': 'Medium',
        'notes': 'Stacked transformers, shared utility corridors',
    })

    return recommendations


# ==============================================================================
# GAS CONSUMPTION & PIPELINE SIZING (P10)
# ==============================================================================

def calculate_gas_pipeline(
    p_total_avg_mw: float,
    hr_op_mj_kwh: float,
    gen_data: dict,
    gas_supply_pressure_psia: float = 100.0,
    pipeline_length_miles: float = 1.0,
    pipe_efficiency: float = 0.92,
    gas_sg: float = 0.65,
    gas_temp_f: float = 60.0,
    gas_z_factor: float = 0.90,
) -> dict:
    """
    Calculate monthly gas consumption and pipeline sizing.

    Uses Weymouth equation (US customary) solved for minimum pipe diameter.
    P2 (minimum site inlet pressure) is read from the generator library field
    'gas_inlet_pressure_psia'. Gas turbines typically require a booster
    compressor if utility supply pressure < combustor inlet requirement.

    Returns a dict with monthly consumption table, annual totals,
    daily flow rate, recommended NPS, and a compressor warning flag.
    """
    from math import sqrt

    # Constants
    LHV_BTU_SCF  = 1012.0     # BTU/scf — LHV pipeline natural gas
    MJ_PER_MMBTU = 1055.06    # MJ/MMBtu
    Tb = 520.0                 # °R base temp (60°F)
    Pb = 14.73                 # psia base pressure

    NPS_STANDARDS = [2, 3, 4, 6, 8, 10, 12, 16, 20, 24]

    T_rankine = gas_temp_f + 459.67
    P1 = gas_supply_pressure_psia
    P2 = float(gen_data.get('gas_inlet_pressure_psia', 5.0))

    # Monthly consumption
    DAYS_PER_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    MONTH_NAMES    = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    monthly = []
    for name, days in zip(MONTH_NAMES, DAYS_PER_MONTH):
        mwh    = p_total_avg_mw * 24.0 * days
        mmbtu  = mwh * 1000.0 * hr_op_mj_kwh / MJ_PER_MMBTU
        mmscfd = (mmbtu / days * 1e6) / (LHV_BTU_SCF * 1e6)
        monthly.append({
            'month':  name,
            'days':   days,
            'mwh':    round(mwh, 0),
            'mmbtu':  round(mmbtu, 0),
            'mmscfd': round(mmscfd, 3),
        })

    annual_mmbtu  = sum(m['mmbtu'] for m in monthly)
    annual_mwh    = sum(m['mwh']   for m in monthly)
    daily_mmbtu   = annual_mmbtu / 365.0
    daily_mmscfd  = daily_mmbtu * 1e6 / (LHV_BTU_SCF * 1e6)
    Q_scfd        = daily_mmscfd * 1e6   # convert to SCFD for Weymouth

    # Compressor warning
    needs_compressor = P1 < P2

    # Weymouth diameter (only if P1 > P2)
    if not needs_compressor and pipeline_length_miles > 0:
        coeff  = 433.5 * pipe_efficiency * (Tb / Pb)
        pterm  = sqrt((P1**2 - P2**2) / (gas_sg * T_rankine * gas_z_factor
                                          * pipeline_length_miles))
        D_min  = (Q_scfd / (coeff * pterm)) ** (3.0 / 8.0)
        D_nps  = next((n for n in NPS_STANDARDS if n >= D_min), NPS_STANDARDS[-1])
    else:
        D_min = 0.0
        D_nps = 0

    # Velocity check at selected NPS (ft/s at average operating pressure)
    if D_nps > 0:
        import math
        P_avg = (P1 + P2) / 2.0
        A_ft2 = math.pi * ((D_nps / 12.0) / 2.0) ** 2
        Q_actual_ft3s = Q_scfd * (Pb / P_avg) / 86400.0
        velocity_fps = Q_actual_ft3s / A_ft2
    else:
        velocity_fps = 0.0

    gen_type_label = 'Gas turbine' if P2 > 50 else (
        'Medium-speed reciprocating' if P2 > 10 else 'High-speed reciprocating')

    return {
        'monthly_consumption':   monthly,
        'annual_mmbtu':          round(annual_mmbtu, 0),
        'annual_mwh':            round(annual_mwh, 0),
        'daily_mmbtu':           round(daily_mmbtu, 0),
        'daily_mmscfd':          round(daily_mmscfd, 3),
        'Q_scfd':                round(Q_scfd, 0),
        'D_min_inches':          round(D_min, 2),
        'D_nps_inches':          D_nps,
        'velocity_fps':          round(velocity_fps, 1),
        'needs_compressor':      needs_compressor,
        'P1_supply_psia':        P1,
        'P2_required_psia':      P2,
        'gen_type_label':        gen_type_label,
        'pipeline_length_miles': pipeline_length_miles,
        'assumptions': {
            'equation':          'Weymouth (US customary)',
            'pipe_efficiency_E': pipe_efficiency,
            'gas_sg':            gas_sg,
            'gas_temp_f':        gas_temp_f,
            'gas_z_factor':      gas_z_factor,
            'LHV_btu_scf':       LHV_BTU_SCF,
        }
    }
