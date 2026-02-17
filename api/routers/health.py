"""
CAT Power Solution — Health & Meta Router
===========================================
Health check and version endpoints for Docker/k8s.
"""

from fastapi import APIRouter
from api.schemas.common import HealthResponse, VersionResponse
from core.generator_library import GENERATOR_LIBRARY

router = APIRouter()

APP_VERSION = "3.1"
API_VERSION = "1.0.0"
ENGINE_FUNCTION_COUNT = 16


@router.get("/health", response_model=HealthResponse)
def health_check():
    """Health check endpoint for container orchestration."""
    return HealthResponse(
        status="healthy",
        version=APP_VERSION,
        engine_functions=ENGINE_FUNCTION_COUNT,
        generator_models=len(GENERATOR_LIBRARY),
    )


@router.get("/version", response_model=VersionResponse)
def version_info():
    """Application version and metadata."""
    return VersionResponse(
        app_version=APP_VERSION,
        api_version=API_VERSION,
        generator_count=len(GENERATOR_LIBRARY),
        engine_function_count=ENGINE_FUNCTION_COUNT,
    )
