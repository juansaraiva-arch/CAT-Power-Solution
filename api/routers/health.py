"""
CAT Power Solution — Health & Meta Router
===========================================
Health check and version endpoints for Docker/k8s.
No authentication required — public endpoints.
"""

from fastapi import APIRouter
from api.schemas.common import VersionResponse
from api.config import get_settings
from core.generator_library import GENERATOR_LIBRARY

router = APIRouter()

ENGINE_FUNCTION_COUNT = 16


@router.get("/health")
def health_check():
    """Health check endpoint for container orchestration."""
    settings = get_settings()
    return {
        "status": "healthy",
        "version": settings.app_version,
        "environment": settings.environment,
        "engine_functions": ENGINE_FUNCTION_COUNT,
        "generator_models": len(GENERATOR_LIBRARY),
    }


@router.get("/version", response_model=VersionResponse)
def version_info():
    """Application version and metadata."""
    settings = get_settings()
    return VersionResponse(
        app_version=settings.app_version,
        api_version="1.0.0",
        generator_count=len(GENERATOR_LIBRARY),
        engine_function_count=ENGINE_FUNCTION_COUNT,
    )
