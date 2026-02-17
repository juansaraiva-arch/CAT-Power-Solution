"""
CAT Power Solution — Project Schemas
======================================
Pydantic models for project management endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional


class ProjectResponse(BaseModel):
    """Full project structure as returned by new_project()."""
    app_version: str
    created: str
    modified: str
    header: dict
    inputs: dict


class ApplyTemplateRequest(BaseModel):
    """Request to apply a template to a project."""
    project: dict = Field(..., description="Full project dict")
    template_name: str = Field(..., description="Template name to apply")


class TemplateListResponse(BaseModel):
    """List of available templates."""
    templates: list[str]


class DefaultsResponse(BaseModel):
    """INPUT_DEFAULTS dict."""
    defaults: dict


class CountriesResponse(BaseModel):
    """List of available countries."""
    countries: list[str]
