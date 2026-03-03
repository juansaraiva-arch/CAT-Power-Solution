"""
CAT Power Solution — Engine Router
====================================
Individual endpoints for each of the 16 calculation functions.
All endpoints are POST (structured inputs → calculated outputs).
"""

from fastapi import APIRouter

from api.dependencies import resolve_generator_or_404
from api.schemas.engine import (
    PartLoadEfficiencyRequest, PartLoadEfficiencyResponse,
    TransientStabilityRequest, TransientStabilityResponse,
    FrequencyScreeningRequest, FrequencyScreeningResponse,
    SpinningReserveRequest, SpinningReserveResponse,
    BessRequirementsRequest, BessRequirementsResponse, BessBreakdown,
    BessReliabilityCreditRequest, BessReliabilityCreditResponse,
    AvailabilityRequest, AvailabilityResponse,
    FleetOptimizationRequest, FleetOptimizationResponse, FleetOptionDetail,
    MacrsDepreciationRequest, MacrsDepreciationResponse,
    NoiseAtDistanceRequest, NoiseAtDistanceResponse,
    CombinedNoiseRequest, CombinedNoiseResponse,
    NoiseSetbackRequest, NoiseSetbackResponse,
    SiteDerateRequest, SiteDerateResponse,
    EmissionsRequest, EmissionsResponse,
    FootprintRequest, FootprintResponse,
    LcoeRequest, LcoeResponse,
)
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

router = APIRouter()


# ==============================================================================
# 1. PART-LOAD EFFICIENCY
# ==============================================================================

@router.post("/part-load-efficiency", response_model=PartLoadEfficiencyResponse)
def api_part_load_efficiency(req: PartLoadEfficiencyRequest):
    """Calculate generator efficiency at a given load point."""
    eff = get_part_load_efficiency(req.base_efficiency, req.load_pct, req.gen_type)
    return PartLoadEfficiencyResponse(
        efficiency=eff,
        base_efficiency=req.base_efficiency,
        load_pct=req.load_pct,
        gen_type=req.gen_type,
    )


# ==============================================================================
# 2. TRANSIENT STABILITY
# ==============================================================================

@router.post("/transient-stability", response_model=TransientStabilityResponse)
def api_transient_stability(req: TransientStabilityRequest):
    """Check transient voltage stability for step load events."""
    # step_load_pct is % of total online capacity → convert to MW
    total_online_mw = req.num_units * req.unit_capacity_mw
    step_load_mw = total_online_mw * (req.step_load_pct / 100)
    passes, sag = transient_stability_check(
        req.xd_pu, req.num_units, step_load_mw, req.unit_capacity_mw,
    )
    return TransientStabilityResponse(passes=passes, voltage_sag_pct=sag)


# ==============================================================================
# 3. FREQUENCY SCREENING
# ==============================================================================

@router.post("/frequency-screening", response_model=FrequencyScreeningResponse)
def api_frequency_screening(req: FrequencyScreeningRequest):
    """Screen frequency nadir and ROCOF per IEEE 1547-2018 (500ms window)."""
    gen_data = resolve_generator_or_404(req.generator)
    result = frequency_screening(
        req.n_running, req.unit_cap_mw, req.p_avg_mw, req.step_mw,
        gen_data, req.bess_mw, req.bess_enabled, req.freq_hz,
        req.rocof_threshold, req.h_bess,
    )
    return FrequencyScreeningResponse(**result)


# ==============================================================================
# 4. SPINNING RESERVE
# ==============================================================================

@router.post("/spinning-reserve", response_model=SpinningReserveResponse)
def api_spinning_reserve(req: SpinningReserveRequest):
    """Calculate number of units needed for spinning reserve."""
    result = calculate_spinning_reserve_units(
        req.p_avg_load, req.unit_capacity, req.spinning_reserve_pct,
        req.use_bess, req.bess_power_mw, req.gen_step_capability_pct,
    )
    return SpinningReserveResponse(**result)


# ==============================================================================
# 5. BESS REQUIREMENTS
# ==============================================================================

@router.post("/bess-requirements", response_model=BessRequirementsResponse)
def api_bess_requirements(req: BessRequirementsRequest):
    """Size battery energy storage system (BESS)."""
    power, energy, breakdown = calculate_bess_requirements(
        req.p_net_req_avg, req.p_net_req_peak, req.step_load_req,
        req.gen_ramp_rate, req.gen_step_capability, req.load_change_rate_req,
        req.enable_black_start,
    )
    return BessRequirementsResponse(
        bess_power_mw=power,
        bess_energy_mwh=energy,
        breakdown=BessBreakdown(**breakdown),
    )


# ==============================================================================
# 6. BESS RELIABILITY CREDIT
# ==============================================================================

@router.post("/bess-reliability-credit", response_model=BessReliabilityCreditResponse)
def api_bess_reliability_credit(req: BessReliabilityCreditRequest):
    """Calculate BESS reliability credit toward fleet availability."""
    effective, breakdown = calculate_bess_reliability_credit(
        req.bess_power_mw, req.bess_energy_mwh,
        req.unit_capacity_mw, req.mttr_hours,
    )
    return BessReliabilityCreditResponse(**breakdown)


# ==============================================================================
# 7. AVAILABILITY (WEIBULL)
# ==============================================================================

@router.post("/availability", response_model=AvailabilityResponse)
def api_availability(req: AvailabilityRequest):
    """Calculate system availability using Binomial N+X model with fixed unit availability."""
    avail_y1, timeline = calculate_availability_weibull(
        req.n_total, req.n_running, req.unit_availability,
        req.project_years,
    )
    return AvailabilityResponse(
        system_availability=avail_y1,
        availability_over_time=timeline,
    )


# ==============================================================================
# 8. FLEET OPTIMIZATION
# ==============================================================================

@router.post("/fleet-optimization", response_model=FleetOptimizationResponse)
def api_fleet_optimization(req: FleetOptimizationRequest):
    """Find optimal fleet size balancing efficiency and reliability."""
    gen_data = resolve_generator_or_404(req.generator)
    n_opt, options = optimize_fleet_size(
        req.p_net_req_avg, req.p_net_req_peak, req.unit_cap,
        req.step_load_req, gen_data, req.use_bess,
    )
    # Convert int keys to strings for JSON compatibility
    str_options = {}
    for k, v in options.items():
        str_options[str(k)] = FleetOptionDetail(**v) if isinstance(v, dict) else v
    return FleetOptimizationResponse(
        optimal_n_running=n_opt,
        fleet_options=str_options,
    )


# ==============================================================================
# 9. MACRS DEPRECIATION
# ==============================================================================

@router.post("/macrs-depreciation", response_model=MacrsDepreciationResponse)
def api_macrs_depreciation(req: MacrsDepreciationRequest):
    """Calculate MACRS depreciation tax shield (present value)."""
    benefit = calculate_macrs_depreciation(req.capex, req.project_years, req.wacc)
    return MacrsDepreciationResponse(pv_tax_shield=benefit)


# ==============================================================================
# 10. NOISE AT DISTANCE
# ==============================================================================

@router.post("/noise/at-distance", response_model=NoiseAtDistanceResponse)
def api_noise_at_distance(req: NoiseAtDistanceRequest):
    """Calculate noise level at a given distance from source."""
    db = noise_at_distance(req.combined_db, req.distance_m)
    return NoiseAtDistanceResponse(noise_db=db)


# ==============================================================================
# 11. COMBINED NOISE
# ==============================================================================

@router.post("/noise/combined", response_model=CombinedNoiseResponse)
def api_combined_noise(req: CombinedNoiseRequest):
    """Calculate combined noise from N identical sources."""
    db = calculate_combined_noise(req.source_noise_db, req.attenuation_db, req.n_running)
    return CombinedNoiseResponse(combined_noise_db=db)


# ==============================================================================
# 12. NOISE SETBACK
# ==============================================================================

@router.post("/noise/setback", response_model=NoiseSetbackResponse)
def api_noise_setback(req: NoiseSetbackRequest):
    """Calculate minimum setback distance to meet noise limit."""
    dist = noise_setback_distance(req.combined_db, req.noise_limit_db)
    return NoiseSetbackResponse(setback_distance_m=dist)


# ==============================================================================
# 13. SITE DERATE
# ==============================================================================

@router.post("/site-derate", response_model=SiteDerateResponse)
def api_site_derate(req: SiteDerateRequest):
    """Calculate site derating using official CAT lookup tables with bilinear interpolation."""
    result = calculate_site_derate(req.site_temp_c, req.site_alt_m, req.methane_number)
    return SiteDerateResponse(**result)


# ==============================================================================
# 14. EMISSIONS
# ==============================================================================

@router.post("/emissions", response_model=EmissionsResponse)
def api_emissions(req: EmissionsRequest):
    """Calculate annual emissions (NOx, CO, CO2)."""
    gen_data = resolve_generator_or_404(req.generator)
    result = calculate_emissions(
        req.n_running, req.unit_cap_mw, gen_data,
        req.capacity_factor, req.load_per_unit_pct,
    )
    return EmissionsResponse(**result)


# ==============================================================================
# 15. FOOTPRINT
# ==============================================================================

@router.post("/footprint", response_model=FootprintResponse)
def api_footprint(req: FootprintRequest):
    """Calculate plant footprint (area in m2)."""
    gen_data = resolve_generator_or_404(req.generator)
    result = calculate_footprint(
        req.n_total, req.unit_cap_mw, gen_data,
        req.bess_power_mw, req.bess_energy_mwh,
        req.include_lng, req.lng_gallons,
        req.cooling_method, req.p_total_dc,
    )
    return FootprintResponse(**result)


# ==============================================================================
# 16. LCOE
# ==============================================================================

@router.post("/lcoe", response_model=LcoeResponse)
def api_lcoe(req: LcoeRequest):
    """Calculate Levelized Cost of Energy (LCOE) and financial metrics."""
    result = calculate_lcoe(
        req.total_capex, req.annual_om, req.annual_fuel_cost,
        req.annual_energy_mwh, req.wacc, req.project_years,
        req.carbon_cost_annual,
        req.pipeline_cost_usd, req.permitting_cost_usd, req.commissioning_cost_usd,
    )
    return LcoeResponse(**result)
