"""
CAT Power Solution — Projects Router
======================================
Project management endpoints: defaults, templates, countries.
Requires 'demo' role or higher.
"""

from fastapi import APIRouter, HTTPException, Depends

from api.auth import require_role, AuthenticatedUser
from api.schemas.projects import (
    ProjectResponse,
    ApplyTemplateRequest,
    TemplateListResponse,
    DefaultsResponse,
    CountriesResponse,
)
from core.project_manager import (
    new_project,
    apply_template,
    INPUT_DEFAULTS,
    TEMPLATES,
    COUNTRIES,
    HELP_TEXTS,
)

router = APIRouter()


@router.get("/new", response_model=ProjectResponse)
def get_new_project(
    user: AuthenticatedUser = Depends(require_role("demo")),
):
    """Create a fresh project with all default values."""
    proj = new_project()
    return ProjectResponse(**proj)


@router.get("/defaults", response_model=DefaultsResponse)
def get_defaults(
    user: AuthenticatedUser = Depends(require_role("demo")),
):
    """Get the INPUT_DEFAULTS dictionary (all 76 inputs with defaults)."""
    return DefaultsResponse(defaults=INPUT_DEFAULTS)


@router.get("/templates", response_model=TemplateListResponse)
def list_templates(
    user: AuthenticatedUser = Depends(require_role("demo")),
):
    """List all available sizing templates."""
    return TemplateListResponse(templates=list(TEMPLATES.keys()))


@router.post("/apply-template", response_model=ProjectResponse)
def api_apply_template(
    req: ApplyTemplateRequest,
    user: AuthenticatedUser = Depends(require_role("demo")),
):
    """Apply a template to a project, overriding selected input values."""
    if req.template_name not in TEMPLATES and req.template_name != "Custom (Manual)":
        raise HTTPException(
            status_code=404,
            detail=f"Template '{req.template_name}' not found. "
                   f"Available: {list(TEMPLATES.keys())}",
        )
    project = apply_template(req.project, req.template_name)
    return ProjectResponse(**project)


@router.get("/countries", response_model=CountriesResponse)
def list_countries(
    user: AuthenticatedUser = Depends(require_role("demo")),
):
    """Get the list of available countries for project location."""
    return CountriesResponse(countries=COUNTRIES)


@router.get("/help-texts")
def get_help_texts(
    user: AuthenticatedUser = Depends(require_role("demo")),
):
    """Get all input help/tooltip texts."""
    return HELP_TEXTS
