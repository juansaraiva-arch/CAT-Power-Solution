# api/services/electrical_sizing.py
"""
Electrical sizing for prime power data center plants.

All generators run simultaneously (pod architecture).
Bus sized for pod-pair contingency transfer capacity (N+1 pod).
Transformer sized for pod-pair apparent power (contingency = design basis).
Off-grid: generator X''d dominates fault impedance (78% of total Z).
Cable impedance neglected: Z_cable/Z_trafo < 0.3% for substations < 100m.
"""

from math import sqrt, ceil
from typing import Optional

BUS_RATINGS_A     = [1200, 2000, 3000, 4000]
XFMR_MVA_STDS     = [1,1.5,2,2.5,3,5,7.5,10,15,20,25,30,37.5,45,50,
                      67,75,100,112.5,133,150,167,200,250,333]
BREAKER_RATINGS_KA = [16, 25, 31.5, 40, 50, 63, 80]
HV_LEVELS_KV      = [34.5, 69.0, 138.0]
BUS_AMPACITY_MAX  = {34.5: 3000, 69.0: 3000, 138.0: 2000}


def _next_std(value, stds):
    for s in stds:
        if s >= value: return s
    return stds[-1]


def _I_bus(P_mw, V_kv, pf=0.8):
    return P_mw * 1000.0 / (sqrt(3.0) * V_kv * pf)


def _isc_one_group(P_pair_mw, V_hv, V_lv, n_gens, P_gen_mw,
                    z_trafo=0.0575, xd=0.20, pf=0.8):
    """Symmetrical ISC (kA) from one trafo+gen group referred to HV bus."""
    S_trafo = P_pair_mw / pf
    S_gen   = P_gen_mw  / pf
    Z_gen   = xd * V_hv**2 / S_gen / n_gens     # all gens in parallel
    Z_trafo = z_trafo * V_hv**2 / S_trafo
    Z_total = Z_gen + Z_trafo
    Vph     = V_hv * 1000.0 / sqrt(3.0)
    I_ka    = Vph / (Z_total * 1000.0)
    return I_ka, Z_gen, Z_trafo


def _isc_mv_ring_bus(
    n_pods: int,
    n_per_pod: int,
    P_gen_mw: float,
    V_lv: float = 13.8,
    z_trafo: float = 0.0575,
    xd: float = 0.20,
    pf: float = 0.8,
    asym: float = 1.30,
) -> dict:
    """
    Symmetrical and asymmetrical ISC at 13.8 kV generator bus — ring bus topology.

    Fault sources:
    1. LOCAL:  own pod's generators in parallel (n_per_pod gens, direct connection)
    2. REMOTE: each of the (n_pods - 1) other pods contributes via:
               generators -> step-up trafo (LV side) -> 34.5 kV ring ->
               faulted pod's step-up trafo (HV->LV reverse) -> fault bus
               = 2 transformers in series per remote path

    All impedances referred to V_lv = 13.8 kV.

    Validated against 5 CAT schemas (DC_Esquemas.pptx):
    S1 (6p×5g×4MW):  ISC_sym=25.5kA, ISC_asym=33.2kA → 40kA breaker
    S2 (10p×9g×1.5): ISC_sym=28.2kA, ISC_asym=36.7kA → 40kA breaker
    S3 (10p×12g×1.5):ISC_sym=37.6kA, ISC_asym=48.9kA → 50kA breaker
    S4 (10p×7g×2.5): ISC_sym=36.6kA, ISC_asym=47.5kA → 50kA breaker
    S5 (10p×10g×2.5):ISC_sym=52.2kA, ISC_asym=67.9kA → 80kA breaker
    """
    S_gen_mva   = P_gen_mw / pf
    S_trafo_mva = (n_per_pod * P_gen_mw * 2) / pf   # pod-pair MVA

    # Single generator Thevenin impedance referred to LV
    Z_gen_ohm  = xd * V_lv**2 / S_gen_mva

    # Local contribution: own pod's n_per_pod gens in parallel
    Z_local    = Z_gen_ohm / n_per_pod

    # One transformer referred to LV
    Z_trafo_lv = z_trafo * V_lv**2 / S_trafo_mva

    # One remote pod path: (gen_of_remote_pod in parallel) + 2×Z_trafo
    Z_one_remote   = (Z_gen_ohm / n_per_pod) + 2.0 * Z_trafo_lv

    # (n_pods - 1) remote pods in parallel
    Z_remote_total = Z_one_remote / (n_pods - 1)

    # Fault impedance: local || remote_total
    Z_fault = (Z_local * Z_remote_total) / (Z_local + Z_remote_total)

    V_phase   = V_lv * 1000.0 / sqrt(3.0)
    I_sym_ka  = V_phase / (Z_fault  * 1000.0)
    I_asym_ka = I_sym_ka * asym

    I_local_ka  = V_phase / (Z_local         * 1000.0)
    I_remote_ka = V_phase / (Z_remote_total  * 1000.0)

    breakers = [16, 25, 31.5, 40, 50, 63, 80]
    breaker  = next((b for b in breakers if b >= I_asym_ka), 80)

    return {
        'I_isc_sym_ka':  I_sym_ka,
        'I_isc_asym_ka': I_asym_ka,
        'mv_breaker_ka': breaker,
        'I_local_ka':    I_local_ka,
        'I_remote_ka':   I_remote_ka,
        'z_local_ohm':   Z_local,
        'z_remote_ohm':  Z_remote_total,
        'z_trafo_lv_ohm':Z_trafo_lv,
    }


def calculate_electrical_sizing(
    n_pods: int,
    n_per_pod: int,
    P_gen_mw: float,
    V_gen_kv: float = 13.8,
    pf: float = 0.8,
    z_trafo_pu: float = 0.0575,
    xd_subtrans_pu: float = 0.20,
    isc_asymmetry_factor: float = 1.30,
    preferred_hv_kv: Optional[float] = None,
    p_load_mw: Optional[float] = None,
) -> dict:
    P_pod      = n_per_pod * P_gen_mw
    P_pair     = P_pod * 2
    n_t        = n_pods // 2          # transformers (one per pod pair)
    if n_t < 1: n_t = 1              # safety floor
    P_plant    = p_load_mw if p_load_mw is not None else n_pods * P_pod
    n_pair     = n_per_pod * 2

    # MV Bus (13.8 kV)
    I_mv_norm = _I_bus(P_pod,  V_gen_kv, pf)
    I_mv_cont = _I_bus(P_pair, V_gen_kv, pf)
    mv_bus    = _next_std(I_mv_cont, BUS_RATINGS_A)

    # Transformer
    xfmr_load = P_pair / pf
    xfmr_sel  = _next_std(xfmr_load, XFMR_MVA_STDS)
    xfmr_norm_pct = (P_pod / pf) / xfmr_sel * 100.0

    # HV levels
    hv_results = {}
    rec_hv = None
    for V in HV_LEVELS_KV:
        I_n   = _I_bus(P_plant, V, pf)
        bus_r = _next_std(I_n, BUS_RATINGS_A)
        bus_ok = I_n <= BUS_AMPACITY_MAX[V]

        I1_ka, Z_gen, Z_trafo = _isc_one_group(
            P_pair, V, V_gen_kv, n_pair, P_gen_mw, z_trafo_pu, xd_subtrans_pu, pf)
        Vph   = V * 1000.0 / sqrt(3.0)
        Z_s   = Vph / (I1_ka * 1000.0)
        I_sym = Vph / (Z_s / n_t * 1000.0)
        I_asy = I_sym * isc_asymmetry_factor
        brk   = _next_std(I_asy, BREAKER_RATINGS_KA)
        isc_ok = I_asy <= 40.0

        hv_results[V] = {
            'voltage_kv': V, 'I_normal_a': I_n, 'bus_rating_a': bus_r,
            'bus_ok': bus_ok, 'I_isc_sym_ka': I_sym, 'I_isc_asym_ka': I_asy,
            'isc_ok': isc_ok, 'breaker_ka': brk,
            'z_gen_pct': Z_gen/(Z_gen+Z_trafo)*100,
            'z_trafo_pct': Z_trafo/(Z_gen+Z_trafo)*100,
        }
        if rec_hv is None and bus_ok and isc_ok:
            rec_hv = V

    if rec_hv is None: rec_hv = HV_LEVELS_KV[-1]
    if preferred_hv_kv and preferred_hv_kv in hv_results:
        rec_hv = preferred_hv_kv

    # MV 13.8 kV ring bus ISC (P09)
    mv_isc = _isc_mv_ring_bus(
        n_pods, n_per_pod, P_gen_mw,
        V_lv=V_gen_kv, z_trafo=z_trafo_pu,
        xd=xd_subtrans_pu, pf=pf,
        asym=isc_asymmetry_factor,
    )

    rec = hv_results[rec_hv]
    return {
        'mv_voltage_kv': V_gen_kv, 'mv_I_normal_a': I_mv_norm,
        'mv_I_contingency_a': I_mv_cont, 'mv_bus_rating_a': mv_bus,
        'xfmr_mva_load': xfmr_load, 'xfmr_mva_selected': xfmr_sel,
        'xfmr_loading_normal_pct': xfmr_norm_pct, 'xfmr_count': n_t,
        'xfmr_voltage_ratio': f"{V_gen_kv:.1f}/{rec_hv:.1f} kV",
        'hv_voltage_kv': rec_hv,
        'hv_I_normal_a': rec['I_normal_a'], 'hv_bus_rating_a': rec['bus_rating_a'],
        'hv_bus_ok': rec['bus_ok'],
        'isc_sym_ka': rec['I_isc_sym_ka'], 'isc_asym_ka': rec['I_isc_asym_ka'],
        'hv_breaker_ka': rec['breaker_ka'],
        'isc_z_gen_pct': rec['z_gen_pct'], 'isc_z_trafo_pct': rec['z_trafo_pct'],
        'hv_all_levels': hv_results,
        'mv_isc': mv_isc,
        'assumptions': {
            'z_trafo_pu': z_trafo_pu, 'xd_subtrans_pu': xd_subtrans_pu,
            'isc_asymmetry_factor': isc_asymmetry_factor, 'pf': pf,
            'cable_impedance': 'neglected (< 0.3% of Z_trafo)',
        },
    }
