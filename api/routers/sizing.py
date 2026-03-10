"""
CAT Power Solution — Sizing Router
====================================
Full and quick sizing pipeline endpoints.
Requires 'full' role or higher.
"""

from fastapi import APIRouter, HTTPException, Depends

from api.auth import require_role, AuthenticatedUser
from api.schemas.sizing import (
    SizingInput,
    SizingProjectInput,
    SizingResult,
    QuickSizingInput,
)
from api.services.sizing_pipeline import run_full_sizing, run_quick_sizing

router = APIRouter()


@router.post("/full", response_model=SizingResult)
def full_sizing(
    req: SizingProjectInput,
    user: AuthenticatedUser = Depends(require_role("full")),
):
    """
    Execute the complete sizing pipeline.

    Accepts a full project input (header + inputs) and returns
    comprehensive sizing results including fleet, BESS, electrical,
    emissions, footprint, and financial data.
    """
    try:
        result = run_full_sizing(req.inputs)
        # Inject project header if provided
        if req.header:
            result.project_name = req.header.project_name
        return result
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Generator not found: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sizing calculation error: {str(e)}")


@router.post("/quick", response_model=SizingResult)
def quick_sizing(
    req: QuickSizingInput,
    user: AuthenticatedUser = Depends(require_role("full")),
):
    """
    Quick sizing with minimal inputs.

    Uses defaults for all parameters not provided.
    Ideal for initial estimates and sensitivity analysis.
    """
    try:
        result = run_quick_sizing(
            p_it=req.p_it,
            pue=req.pue,
            generator_model=req.generator_model,
            use_bess=req.use_bess,
            site_temp_c=req.site_temp_c,
            site_alt_m=req.site_alt_m,
            freq_hz=req.freq_hz,
        )
        return result
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Generator not found: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quick sizing error: {str(e)}")
