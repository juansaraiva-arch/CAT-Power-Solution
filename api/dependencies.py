"""
CAT Power Solution — API Dependencies
=======================================
Shared FastAPI dependencies for dependency injection.
"""

from fastapi import HTTPException
from api.services.generator_resolver import resolve_generator as _resolve
from api.schemas.common import GeneratorRef


def resolve_generator_or_404(ref: GeneratorRef) -> dict:
    """
    Resolve a GeneratorRef to a full data dict, or raise HTTP 404.
    Use this in route handlers that need gen_data.
    """
    try:
        return _resolve(ref.model_name, ref.overrides)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
