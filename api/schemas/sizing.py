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

    # ── Voltage ──
    volt_mode: str = Field("Auto-Recommend", description="'Auto-Recommend' or 'Manual'")
    manual_voltage_kv: float = Field(13.8, gt=0)

    # ── Economics ──
    gas_price: float = Field(3.5, ge=0, description="Gas price $/MMBtu")
    wacc: float = Field(8.0, ge=0, le=30, description="WACC as percentage")
    project_years: int = Field(20, ge=1, le=40)
    benchmark_price: float = Field(0.12, ge=0, description="Grid benchmark $/kWh")
    carbon_price_per_ton: float = Field(0.0, ge=0)
    enable_depreciation: bool = True

    # ── BESS Economics ──
    bess_cost_kw: float = Field(250.0, ge=0)
    bess_cost_kwh: float = Field(400.0, ge=0)
    bess_om_kw_yr: float = Field(5.0, ge=0)

    # ── Fuel ──
    fuel_mode: str = Field("Pipeline Gas", description="'Pipeline Gas' or 'LNG'")
    lng_days: int = Field(5, ge=1, le=30)
    include_chp: bool = False

    # ── Footprint ──
    enable_footprint_limit: bool = False
    max_area_m2: float = Field(10000.0, gt=0)

    # ── Region ──
    region: str = Field("US - Gulf Coast", description="Region for cost estimation")


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
    app_version: str = "3.1"

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

    # ── Fleet ──
    n_running: int
    n_reserve: int
    n_total: int
    installed_cap: float
    load_per_unit_pct: float
    fleet_efficiency: float

    # ── Spinning Reserve ──
    spinning_reserve_mw: float
    spinning_from_gens: float
    spinning_from_bess: float
    headroom_mw: float

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

    # ── Availability ──
    system_availability: float
    availability_over_time: list[float]

    # ── Emissions ──
    emissions: dict

    # ── Footprint ──
    footprint: dict

    # ── Financial ──
    lcoe: float
    npv: float
    total_capex: float
    annual_fuel_cost: float
    annual_om_cost: float
    simple_payback_years: float


class QuickSizingInput(BaseModel):
    """Simplified sizing input for quick estimates."""
    p_it: float = Field(..., gt=0, le=2000, description="IT load in MW")
    pue: float = Field(1.20, ge=1.0, le=3.0)
    generator_model: str = Field("G3516H", description="Generator model name")
    use_bess: bool = True
    site_temp_c: float = Field(35.0, ge=-40, le=60)
    site_alt_m: float = Field(100.0, ge=0, le=5000)
    freq_hz: int = Field(60, description="Grid frequency")
