"""
CAT Power Solution — Generators Router
========================================
CRUD endpoints for the generator library.
Requires 'demo' role or higher.
"""

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Depends
from typing import Optional
from io import BytesIO

from api.auth import require_role, AuthenticatedUser
from api.schemas.generators import (
    GeneratorSpec,
    GeneratorSummary,
    GeneratorLibraryResponse,
    GeneratorFilterRequest,
)
from core.generator_library import (
    GENERATOR_LIBRARY,
    get_library,
    filter_by_type,
    get_model_names,
    get_model_summary,
    parse_gerp_pdf,
)

router = APIRouter()


@router.get("", response_model=GeneratorLibraryResponse)
def list_generators(
    type_filter: Optional[str] = Query(
        None,
        description="Comma-separated type filter, e.g. 'High Speed,Gas Turbine'",
    ),
    user: AuthenticatedUser = Depends(require_role("demo")),
):
    """List all generators, optionally filtered by type."""
    lib = get_library()
    if type_filter:
        types = [t.strip() for t in type_filter.split(",")]
        lib = filter_by_type(lib, types)
    return GeneratorLibraryResponse(generators=lib, count=len(lib))


@router.get("/names", response_model=list[str])
def list_generator_names(
    user: AuthenticatedUser = Depends(require_role("demo")),
):
    """List all generator model names."""
    return get_model_names()


@router.get("/{model_name}", response_model=GeneratorSpec)
def get_generator(
    model_name: str,
    user: AuthenticatedUser = Depends(require_role("demo")),
):
    """Get full specifications for a generator model."""
    lib = get_library()
    if model_name not in lib:
        raise HTTPException(
            status_code=404,
            detail=f"Generator model '{model_name}' not found. "
                   f"Available: {sorted(lib.keys())}",
        )
    return GeneratorSpec(**lib[model_name])


@router.get("/{model_name}/summary", response_model=GeneratorSummary)
def get_generator_summary(
    model_name: str,
    user: AuthenticatedUser = Depends(require_role("demo")),
):
    """Get a brief summary for a generator model."""
    summary = get_model_summary(model_name)
    if not summary:
        raise HTTPException(
            status_code=404,
            detail=f"Generator model '{model_name}' not found.",
        )
    return GeneratorSummary(**summary)


@router.post("/filter", response_model=GeneratorLibraryResponse)
def filter_generators(
    req: GeneratorFilterRequest,
    user: AuthenticatedUser = Depends(require_role("demo")),
):
    """Filter generators by technology type(s)."""
    lib = get_library()
    filtered = filter_by_type(lib, req.types)
    return GeneratorLibraryResponse(generators=filtered, count=len(filtered))


@router.post("/upload-gerp")
async def upload_gerp(
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(require_role("demo")),
):
    """
    Parse a GERP PDF performance report and return extracted generator data.
    Returns model name, site rating (kW), efficiency, heat rejection, and emissions.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    try:
        contents = await file.read()
        pdf_bytes = BytesIO(contents)
        data = parse_gerp_pdf(pdf_bytes)

        if not data:
            raise HTTPException(
                status_code=422,
                detail="Could not extract generator data from this PDF. "
                       "Please verify it is a valid GERP performance report.",
            )

        return {
            "success": True,
            "parsed_data": data,
            "message": f"Successfully parsed GERP for model {data.get('model', 'Unknown')}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error parsing GERP PDF: {str(e)}")
