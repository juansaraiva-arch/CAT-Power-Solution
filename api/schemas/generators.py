"""
CAT Power Solution — Generator Schemas
========================================
Pydantic models for generator library endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional


class GeneratorSpec(BaseModel):
    """Full specification for a generator model."""
    description: str
    type: str
    iso_rating_mw: float
    electrical_efficiency: float
    heat_rate_lhv: float
    step_load_pct: float
    ramp_rate_mw_s: float
    emissions_nox: float
    emissions_co: float
    mtbf_hours: float
    maintenance_interval_hrs: float
    maintenance_duration_hrs: float
    default_for: float
    default_maint: float
    est_cost_kw: float
    est_install_kw: float
    power_density_mw_per_m2: float
    gas_pressure_min_psi: float
    reactance_xd_2: float
    inertia_h: float


class GeneratorSummary(BaseModel):
    """Brief summary for a generator model."""
    model: str
    description: str
    type: str
    mw: float
    efficiency: float
    step_load_pct: float


class GeneratorLibraryResponse(BaseModel):
    """Response containing the full generator library."""
    generators: dict[str, GeneratorSpec]
    count: int


class GeneratorFilterRequest(BaseModel):
    """Request to filter generators by type."""
    types: list[str] = Field(
        ...,
        description="Generator types to include, e.g. ['High Speed', 'Gas Turbine']",
    )
