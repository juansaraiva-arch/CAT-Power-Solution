"""
CAT Power Solution — Common Schemas
====================================
Shared Pydantic models used across multiple routers.
"""

from pydantic import BaseModel, Field
from typing import Optional


class GeneratorRef(BaseModel):
    """Reference a generator by library name, with optional parameter overrides."""
    model_name: str = Field(..., description="Generator model name, e.g. 'G3516H'")
    overrides: Optional[dict] = Field(
        None,
        description="Optional overrides for generator parameters, e.g. {'iso_rating_mw': 2.3}",
    )


class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str
    error_code: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    version: str
    engine_functions: int
    generator_models: int


class VersionResponse(BaseModel):
    """Version and metadata response."""
    app_version: str
    api_version: str
    generator_count: int
    engine_function_count: int
