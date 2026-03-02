"""
CAT Power Solution — Engine Schemas
=====================================
Request/Response models for each of the 16 engine calculation endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional
from .common import GeneratorRef


# ==============================================================================
# PART-LOAD EFFICIENCY
# ==============================================================================

class PartLoadEfficiencyRequest(BaseModel):
    base_efficiency: float = Field(..., description="ISO-rated electrical efficiency (e.g. 0.441)")
    load_pct: float = Field(..., ge=0, le=100, description="Operating load percentage (0-100)")
    gen_type: str = Field(..., description="'High Speed', 'Medium Speed', or 'Gas Turbine'")


class PartLoadEfficiencyResponse(BaseModel):
    efficiency: float
    base_efficiency: float
    load_pct: float
    gen_type: str


# ==============================================================================
# TRANSIENT STABILITY
# ==============================================================================

class TransientStabilityRequest(BaseModel):
    xd_pu: float = Field(..., description="Transient reactance in per-unit")
    num_units: int = Field(..., ge=1, description="Number of generating units")
    step_load_pct: float = Field(..., ge=0, description="Step load as percentage")


class TransientStabilityResponse(BaseModel):
    passes: bool
    voltage_sag_pct: float


# ==============================================================================
# FREQUENCY SCREENING
# ==============================================================================

class FrequencyScreeningRequest(BaseModel):
    n_running: int = Field(..., ge=1, description="Number of running units")
    unit_cap_mw: float = Field(..., gt=0, description="Unit capacity in MW")
    p_avg_mw: float = Field(..., gt=0, description="Average power in MW")
    step_mw: float = Field(..., ge=0, description="Step load in MW")
    generator: GeneratorRef
    bess_mw: float = Field(0.0, ge=0, description="BESS power in MW")
    bess_enabled: bool = False
    freq_hz: int = Field(60, description="Grid frequency (50 or 60 Hz)")
    rocof_threshold: float = Field(
        2.0, gt=0,
        description="IEEE 1547 ROCOF threshold in Hz/s. Default 2.0 for islanded systems.",
    )
    h_bess: float = Field(
        0.0, ge=0,
        description="Virtual inertia constant from BESS (seconds). Default 0.",
    )


class FrequencyScreeningResponse(BaseModel):
    nadir_hz: float
    rocof_hz_s: float
    nadir_ok: bool
    rocof_ok: bool
    rocof_pass_fail: str
    nadir_limit: float
    rocof_limit: float
    H_total: float
    H_bess: float
    P_step_pu: float
    notes: list[str]


# ==============================================================================
# SPINNING RESERVE
# ==============================================================================

class SpinningReserveRequest(BaseModel):
    p_avg_load: float = Field(..., gt=0, description="Average load in MW")
    unit_capacity: float = Field(..., gt=0, description="Unit capacity in MW")
    spinning_reserve_pct: float = Field(..., ge=0, description="Spinning reserve percentage")
    use_bess: bool = False
    bess_power_mw: float = Field(0.0, ge=0)
    gen_step_capability_pct: float = Field(0.0, ge=0)


class SpinningReserveResponse(BaseModel):
    n_units_running: int
    load_per_unit_pct: float
    spinning_reserve_mw: float
    spinning_from_gens: float
    spinning_from_bess: float
    total_online_capacity: float
    headroom_available: float
    required_online_capacity: float


# ==============================================================================
# BESS REQUIREMENTS
# ==============================================================================

class BessRequirementsRequest(BaseModel):
    p_net_req_avg: float = Field(..., gt=0, description="Average net requirement in MW")
    p_net_req_peak: float = Field(..., gt=0, description="Peak net requirement in MW")
    step_load_req: float = Field(..., ge=0, description="Step load requirement (%)")
    gen_ramp_rate: float = Field(..., gt=0, description="Generator ramp rate MW/min")
    gen_step_capability: float = Field(..., ge=0, description="Generator step capability (%)")
    load_change_rate_req: float = Field(..., gt=0, description="Load change rate requirement MW/min")
    enable_black_start: bool = False


class BessBreakdown(BaseModel):
    step_support: float
    peak_shaving: float
    ramp_support: float
    freq_reg: float
    black_start: float
    spinning_reserve: float


class BessRequirementsResponse(BaseModel):
    bess_power_mw: float
    bess_energy_mwh: float
    breakdown: BessBreakdown


# ==============================================================================
# BESS RELIABILITY CREDIT
# ==============================================================================

class BessReliabilityCreditRequest(BaseModel):
    bess_power_mw: float = Field(..., ge=0)
    bess_energy_mwh: float = Field(..., ge=0)
    unit_capacity_mw: float = Field(..., gt=0)
    mttr_hours: float = Field(48.0, gt=0, description="Mean time to repair in hours")


class BessReliabilityCreditResponse(BaseModel):
    effective_credit: float
    power_credit: float
    energy_credit: float
    raw_credit: float
    bess_availability: float
    coverage_factor: float
    bess_duration_hrs: float
    realistic_coverage_hrs: float


# ==============================================================================
# AVAILABILITY (WEIBULL)
# ==============================================================================

class AvailabilityRequest(BaseModel):
    n_total: int = Field(..., ge=1, description="Total number of units")
    n_running: int = Field(..., ge=1, description="Number of running units")
    unit_availability: float = Field(
        0.93, ge=0.70, le=0.99,
        description=(
            "Unit availability (maintenance + failures). "
            "Industry standard for prime power generators: ~93% "
            "(4% scheduled maintenance + 3% unplanned failures). "
            "Adjust only if manufacturer data or site history justifies a different value."
        ),
    )
    project_years: int = Field(20, ge=1, le=40, description="Project duration in years")


class AvailabilityResponse(BaseModel):
    system_availability: float
    availability_over_time: list[float]


# ==============================================================================
# FLEET OPTIMIZATION
# ==============================================================================

class FleetOptimizationRequest(BaseModel):
    p_net_req_avg: float = Field(..., gt=0, description="Average net requirement in MW")
    p_net_req_peak: float = Field(..., gt=0, description="Peak net requirement in MW")
    unit_cap: float = Field(..., gt=0, description="Unit capacity in MW")
    step_load_req: float = Field(..., ge=0, description="Step load requirement (%)")
    generator: GeneratorRef
    use_bess: bool = False


class FleetOptionDetail(BaseModel):
    efficiency: float
    load_pct: float
    score: float


class FleetOptimizationResponse(BaseModel):
    optimal_n_running: int
    fleet_options: dict[str, FleetOptionDetail]


# ==============================================================================
# MACRS DEPRECIATION
# ==============================================================================

class MacrsDepreciationRequest(BaseModel):
    capex: float = Field(..., gt=0, description="Capital expenditure in dollars")
    project_years: int = Field(..., ge=1, description="Project duration in years")
    wacc: float = Field(0.08, gt=0, lt=1, description="Weighted average cost of capital")


class MacrsDepreciationResponse(BaseModel):
    pv_tax_shield: float


# ==============================================================================
# NOISE
# ==============================================================================

class NoiseAtDistanceRequest(BaseModel):
    combined_db: float = Field(..., description="Sound pressure level in dB(A)")
    distance_m: float = Field(..., gt=0, description="Distance in meters")


class NoiseAtDistanceResponse(BaseModel):
    noise_db: float


class CombinedNoiseRequest(BaseModel):
    source_noise_db: float = Field(..., description="Single source noise in dB(A)")
    attenuation_db: float = Field(..., ge=0, description="Attenuation in dB(A)")
    n_running: int = Field(..., ge=1, description="Number of running sources")


class CombinedNoiseResponse(BaseModel):
    combined_noise_db: float


class NoiseSetbackRequest(BaseModel):
    combined_db: float = Field(..., description="Combined noise level in dB(A)")
    noise_limit_db: float = Field(..., description="Noise limit in dB(A)")


class NoiseSetbackResponse(BaseModel):
    setback_distance_m: float


# ==============================================================================
# SITE DERATE
# ==============================================================================

class SiteDerateRequest(BaseModel):
    site_temp_c: float = Field(..., description="Inlet air temperature in Celsius (clamped 10–50)")
    site_alt_m: float = Field(..., ge=0, description="Site altitude in meters (clamped 0–3000)")
    methane_number: int = Field(80, ge=0, le=100, description="CAT Methane Number of fuel gas")


class SiteDerateResponse(BaseModel):
    derate_factor: float = Field(..., description="Combined derate = methane × altitude")
    methane_deration: float = Field(..., description="Methane Number deration factor")
    altitude_deration: float = Field(..., description="Altitude Deration Factor from CAT table")
    achrf: float = Field(..., description="Aftercooler Heat Rejection Factor")
    methane_warning: Optional[str] = Field(None, description="Warning if MN < 32 or < 60")


# ==============================================================================
# EMISSIONS
# ==============================================================================

class EmissionsRequest(BaseModel):
    n_running: int = Field(..., ge=1)
    unit_cap_mw: float = Field(..., gt=0)
    generator: GeneratorRef
    capacity_factor: float = Field(..., gt=0, le=1)
    load_per_unit_pct: float = Field(..., gt=0, le=100)


class EmissionsResponse(BaseModel):
    nox_tpy: float
    co_tpy: float
    co2_tpy: float
    nox_rate_g_kwh: float
    co_rate_g_kwh: float
    co2_rate_kg_mwh: float
    annual_fuel_mmbtu: float
    annual_energy_mwh: float


# ==============================================================================
# FOOTPRINT
# ==============================================================================

class FootprintRequest(BaseModel):
    n_total: int = Field(..., ge=1)
    unit_cap_mw: float = Field(..., gt=0)
    generator: GeneratorRef
    bess_power_mw: float = Field(0.0, ge=0)
    bess_energy_mwh: float = Field(0.0, ge=0)
    include_lng: bool = False
    lng_gallons: float = Field(0.0, ge=0)
    cooling_method: str = Field("Air-Cooled", description="'Air-Cooled' or 'Water-Cooled'")
    p_total_dc: float = Field(0.0, ge=0, description="Total DC power in MW")


class FootprintResponse(BaseModel):
    gen_area_m2: float
    bess_area_m2: float
    lng_area_m2: float
    cooling_area_m2: float
    substation_area_m2: float
    total_area_m2: float
    power_density_mw_m2: float


# ==============================================================================
# LCOE
# ==============================================================================

class LcoeRequest(BaseModel):
    total_capex: float = Field(..., gt=0, description="Total capital expenditure ($)")
    annual_om: float = Field(..., ge=0, description="Annual O&M cost ($)")
    annual_fuel_cost: float = Field(..., ge=0, description="Annual fuel cost ($)")
    annual_energy_mwh: float = Field(..., gt=0, description="Annual energy production (MWh)")
    wacc: float = Field(..., gt=0, lt=1, description="Weighted average cost of capital")
    project_years: int = Field(..., ge=1, description="Project duration in years")
    carbon_cost_annual: float = Field(0.0, ge=0, description="Annual carbon cost ($)")
    pipeline_cost_usd: float = Field(
        0.0, ge=0,
        description="Pipeline infrastructure cost ($). Optional — if 0, assumed in BOP/installation multiplier.",
    )
    permitting_cost_usd: float = Field(
        0.0, ge=0,
        description="Environmental permits cost ($). Optional — if 0, assumed in BOP/installation multiplier.",
    )
    commissioning_cost_usd: float = Field(
        0.0, ge=0,
        description="Commissioning cost ($). Optional — if 0, assumed in BOP/installation multiplier.",
    )


class LcoeResponse(BaseModel):
    lcoe: float
    npv: float
    simple_payback_years: float
    annual_total_cost: float
    annualized_capex: float
    crf: float
    infrastructure_capex: float
    pipeline_cost_usd: float
    permitting_cost_usd: float
    commissioning_cost_usd: float
