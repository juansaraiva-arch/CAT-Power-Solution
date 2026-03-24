"""
CAT Power Solution — Sizing Schemas
=====================================
Request/Response models for the full sizing pipeline.
"""

from pydantic import BaseModel, Field
from typing import Optional


class SizingInput(BaseModel):
    """Complete project inputs for full sizing. Mirrors INPUT_DEFAULTS structure."""

    # ── Load Profile ──
    p_it: float = Field(100.0, gt=0, le=2000, description="IT load in MW")
    pue: float = Field(1.20, ge=1.0, le=3.0, description="Power Usage Effectiveness")
    capacity_factor: float = Field(0.90, gt=0, le=1.0)
    peak_avg_ratio: float = Field(1.15, ge=1.0, le=2.0)
    load_step_pct: float = Field(40.0, ge=0, le=100)
    spinning_res_pct: float = Field(20.0, ge=0, le=100)
    avail_req: float = Field(99.99, ge=90, le=100, description="Availability requirement (%)")
    load_ramp_req: float = Field(3.0, gt=0, description="Load change rate (MW/min)")
    dc_type: str = Field("AI Factory (Training)", description="Data center type")

    # ── Site Conditions ──
    derate_mode: str = Field("Auto-Calculate", description="'Auto-Calculate' or 'Manual'")
    site_temp_c: float = Field(35.0, ge=-40, le=60)
    site_alt_m: float = Field(100.0, ge=0, le=5000)
    methane_number: int = Field(80, ge=0, le=100)
    derate_factor_manual: float = Field(0.9, gt=0, le=1.0)

    # ── Technology ──
    generator_model: str = Field("G3516H", description="Generator library model name")
    gen_overrides: Optional[dict] = Field(None, description="Optional generator parameter overrides")
    use_bess: bool = Field(True, description="Include BESS in solution")
    bess_strategy: str = Field("Hybrid (Balanced)",
                               description="'Transient Only', 'Hybrid (Balanced)', or 'Reliability Priority'")
    enable_black_start: bool = True
    cooling_method: str = Field("Air-Cooled", description="'Air-Cooled' or 'Water-Cooled'")
    freq_hz: int = Field(60, description="Grid frequency (50 or 60)")
    dist_loss_pct: float = Field(1.5, ge=0, le=10)
    aux_load_pct: float = Field(4.0, ge=0, le=15, description="Auxiliary load percentage")

    # ── Voltage ──
    volt_mode: str = Field("Auto-Recommend", description="'Auto-Recommend' or 'Manual'")
    manual_voltage_kv: float = Field(13.8, gt=0)

    # ── Economics ──
    gas_price: float = Field(3.5, ge=0, description="Gas price $/MMBtu (pipeline)")
    gas_price_lng: float = Field(8.0, ge=0, description="LNG price $/MMBtu")
    wacc: float = Field(8.0, ge=0, le=30, description="WACC as percentage")
    project_years: int = Field(20, ge=1, le=40)
    benchmark_price: float = Field(0.12, ge=0, description="Grid benchmark $/kWh")
    carbon_price_per_ton: float = Field(0.0, ge=0)
    enable_depreciation: bool = True

    # ── Infrastructure (optional — if 0, assumed in BOP/install multiplier) ──
    pipeline_cost_usd: float = Field(0.0, ge=0, description="Pipeline infrastructure cost ($). Optional.")
    permitting_cost_usd: float = Field(0.0, ge=0, description="Environmental permits cost ($). Optional.")
    commissioning_cost_usd: float = Field(0.0, ge=0, description="Commissioning cost ($). Optional.")

    # ── Pipeline Sizing (for auto-calculation) ──
    pipeline_distance_km: float = Field(0.0, ge=0, description="Pipeline distance in km (0=skip auto-calc)")
    pipeline_diameter_inch: float = Field(6.0, ge=2, le=48, description="Pipeline diameter in inches")

    # ── Gas Pipeline Sizing (Weymouth, P10) ──
    gas_supply_pressure_psia: float = Field(100.0, ge=10, le=1500, description="Gas utility supply pressure at site boundary (psia)")
    gas_pipeline_length_miles: float = Field(1.0, ge=0.1, le=50, description="Distance from utility tap to site (miles)")
    gas_pipe_efficiency: float = Field(0.92, ge=0.5, le=1.0, description="Weymouth pipe efficiency factor")
    gas_sg: float = Field(0.65, ge=0.4, le=1.0, description="Gas specific gravity")
    gas_temp_f: float = Field(60.0, ge=-20, le=150, description="Average gas temperature (°F)")
    gas_z_factor: float = Field(0.90, ge=0.5, le=1.0, description="Gas compressibility factor")

    # ── BESS Economics ──
    bess_cost_kw: float = Field(250.0, ge=0)
    bess_cost_kwh: float = Field(400.0, ge=0)
    bess_om_kw_yr: float = Field(5.0, ge=0)

    # ── Fuel ──
    fuel_mode: str = Field("Pipeline Gas",
                           description="'Pipeline Gas', 'LNG', or 'Dual-Fuel'")
    lng_days: int = Field(5, ge=1, le=30)
    lng_backup_pct: float = Field(30.0, ge=0, le=100, description="% of load backed by LNG (dual-fuel)")

    # ── CHP / Tri-Generation ──
    include_chp: bool = False
    chp_recovery_eff: float = Field(0.50, ge=0, le=0.90, description="CHP heat recovery efficiency")
    absorption_cop: float = Field(0.70, ge=0, le=1.5, description="Absorption chiller COP")
    cooling_load_mw: float = Field(0.0, ge=0, description="Site cooling demand (MW thermal)")

    # ── Emissions Control ──
    include_scr: bool = Field(False, description="Include SCR for NOx reduction")
    include_oxicat: bool = Field(False, description="Include Oxidation Catalyst for CO reduction")

    # ── Noise ──
    noise_limit_db: float = Field(65.0, ge=30, le=100, description="Noise limit at property line (dBA)")
    distance_to_property_m: float = Field(100.0, ge=1, description="Distance to property line (m)")
    distance_to_residence_m: float = Field(300.0, ge=1, description="Distance to nearest residence (m)")
    acoustic_treatment: str = Field("Standard",
                                    description="'Standard', 'Enhanced', 'Critical', 'Building'")

    # ── Phasing ──
    enable_phasing: bool = False
    n_phases: int = Field(3, ge=1, le=5)
    months_between_phases: int = Field(6, ge=1, le=24)

    # ── Fleet Maintenance (P12) ──
    max_maintenance_units: int = Field(0, ge=0, le=10, description="Max gens in simultaneous maintenance")
    selected_fleet_config_maint: str = Field("B", description="Fleet maint config for CAPEX: A/B/C")

    # ── Footprint ──
    enable_footprint_limit: bool = False
    max_area_m2: float = Field(10000.0, gt=0)

    # ── Region ──
    region: str = Field("US - Gulf Coast", description="Region for cost estimation")

    # ── Unit System ──
    unit_system: str = Field("Metric", description="'Metric' or 'Imperial'")


class ProjectHeader(BaseModel):
    """Project identification header."""
    project_name: str = ""
    client_name: str = ""
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    country: str = ""
    state_province: str = ""
    county_district: str = ""


class SizingProjectInput(BaseModel):
    """Full project with header + sizing inputs."""
    header: Optional[ProjectHeader] = None
    inputs: SizingInput


class ReliabilityConfig(BaseModel):
    """One reliability configuration (e.g. Config A, B, C)."""
    name: str
    n_running: int
    n_reserve: int
    n_total: int
    bess_mw: float
    bess_mwh: float
    bess_credit: float
    availability: float
    load_pct: float
    efficiency: float
    spinning_reserve_mw: float
    spinning_from_gens: float
    spinning_from_bess: float
    headroom_mw: float


class SizingResult(BaseModel):
    """Complete sizing output from the full pipeline."""

    # ── Project ──
    project_name: str = ""
    dc_type: str = ""
    region: str = ""
    app_version: str = "4.0"

    # ── Load ──
    p_it: float
    pue: float
    p_total_dc: float
    p_total_avg: float
    p_total_peak: float
    capacity_factor: float
    avail_req: float

    # ── Generator ──
    selected_gen: str
    unit_iso_cap: float
    unit_site_cap: float
    derate_factor: float
    methane_deration: float = 1.0
    altitude_deration: float = 1.0
    achrf: float = 1.0
    methane_warning: Optional[str] = None

    # ── Fleet ──
    n_running: int
    n_reserve: int
    n_total: int
    installed_cap: float
    load_per_unit_pct: float
    fleet_efficiency: float

    # ── Pod Architecture (P05) ──
    n_pods: int = 0
    n_per_pod: int = 0
    cap_contingency: float = 0.0
    loading_normal_pct: float = 0.0
    loading_contingency_pct: float = 0.0
    a_system_calculated: float = 0.0
    a_gen_derived: float = 0.0
    max_normal_loading_pct: float = 0.0
    # Fleet Maintenance (P12)
    cap_combined: Optional[float] = None
    maintenance_margin_mw: Optional[float] = None
    max_maintenance_units: Optional[int] = None
    fleet_maintenance_configs: Optional[dict] = None
    selected_fleet_config_maint: Optional[str] = None

    # ── Spinning Reserve ──
    spinning_reserve_mw: float
    spinning_from_gens: float
    spinning_from_bess: float
    headroom_mw: float

    # ── SR Diagnostics (P03/P04) ──
    sr_required_mw: float = 0.0
    sr_user_mw: float = 0.0
    sr_user_below_physical: bool = False
    sr_dominant_contingency: str = "N-1"
    load_step_mw: float = 0.0
    n1_mw: float = 0.0
    bess_sr_credit_valid: bool = False
    bess_sr_response_ok: bool = False
    bess_sr_energy_ok: bool = False
    bess_sr_available_mws: float = 0.0
    bess_sr_required_mws: float = 0.0

    # ── Reliability ──
    reliability_configs: list[ReliabilityConfig]
    selected_config_name: str

    # ── BESS ──
    use_bess: bool
    bess_strategy: str
    bess_power_mw: float
    bess_energy_mwh: float
    bess_breakdown: dict

    # ── Electrical ──
    rec_voltage_kv: float
    freq_hz: int
    stability_ok: bool
    voltage_sag: float
    net_efficiency: float

    # ── Net Efficiency & Heat Rate ──
    gross_efficiency: float = 0.0
    aux_load_pct: float = 4.0
    heat_rate_lhv_btu: float = 0.0
    heat_rate_hhv_btu: float = 0.0
    heat_rate_lhv_mj: float = 0.0
    heat_rate_hhv_mj: float = 0.0

    # ── Availability ──
    system_availability: float
    availability_over_time: list[float]

    # ── Emissions ──
    emissions: dict

    # ── Emissions Compliance ──
    emissions_compliance: list = []

    # ── Emissions Control ──
    emissions_control: dict = {}

    # ── Footprint ──
    footprint: dict

    # ── Footprint Optimization ──
    footprint_recommendations: list = []

    # ── Financial ──
    lcoe: float
    npv: float
    total_capex: float
    annual_fuel_cost: float
    annual_om_cost: float
    annual_savings: float = 0.0
    grid_annual_cost: float = 0.0
    breakeven_gas_price: float = 0.0
    simple_payback_years: float
    pipeline_cost_usd: float = 0.0
    permitting_cost_usd: float = 0.0
    commissioning_cost_usd: float = 0.0
    capex_breakdown: dict = {}
    capex_assumptions: dict = {}
    om_breakdown: dict = {}

    # ── Gas Sensitivity ──
    gas_sensitivity: dict = {}

    # ── LCOE Recommender ──
    lcoe_recommendations: list = []

    # ── LNG Logistics ──
    lng_logistics: dict = {}

    # ── CHP / Tri-Generation ──
    chp_results: dict = {}

    # ── Noise Assessment ──
    noise_results: dict = {}

    # ── Phasing ──
    phasing: dict = {}

    # ── Design Scorecard ──
    design_scorecard: list = []

    # ── Frequency Screening ──
    frequency_screening: dict = {}

    # ── Electrical Sizing (P08) ──
    electrical_sizing: dict = {}

    # ── Gas Pipeline Sizing (P10) ──
    gas_pipeline: Optional[dict] = None

    # ── Off-Grid vs Grid ──
    grid_comparison: dict = {}


class QuickSizingInput(BaseModel):
    """Simplified sizing input for quick estimates."""
    p_it: float = Field(..., gt=0, le=2000, description="IT load in MW")
    pue: float = Field(1.20, ge=1.0, le=3.0)
    generator_model: str = Field("G3516H", description="Generator model name")
    use_bess: bool = True
    site_temp_c: float = Field(35.0, ge=-40, le=60)
    site_alt_m: float = Field(100.0, ge=0, le=5000)
    freq_hz: int = Field(60, description="Grid frequency")
