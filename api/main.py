"""
CAT Power Solution — FastAPI Application
==========================================
REST API for the power system sizing engine.

Run with:
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

Docs at:
    http://localhost:8000/api/docs       (Swagger UI)
    http://localhost:8000/api/redoc      (ReDoc)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routers import health, generators, engine, sizing, projects, reports

# ==============================================================================
# APP FACTORY
# ==============================================================================

app = FastAPI(
    title="CAT Power Solution API",
    description=(
        "REST API for data center prime power system sizing.\n\n"
        "Provides individual calculation endpoints (efficiency, BESS, fleet, LCOE, etc.) "
        "and a full sizing pipeline that produces comprehensive results from a single request."
    ),
    version="3.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/v1/openapi.json",
    license_info={
        "name": "Proprietary",
    },
)

# ==============================================================================
# CORS (for future React/Angular frontend)
# ==============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# REGISTER ROUTERS
# ==============================================================================

app.include_router(health.router, prefix="/api/v1", tags=["Health"])
app.include_router(generators.router, prefix="/api/v1/generators", tags=["Generators"])
app.include_router(engine.router, prefix="/api/v1/engine", tags=["Engine"])
app.include_router(sizing.router, prefix="/api/v1/sizing", tags=["Sizing"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["Projects"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"])

# ==============================================================================
# GLOBAL EXCEPTION HANDLERS
# ==============================================================================


@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(KeyError)
async def key_error_handler(request, exc):
    return JSONResponse(status_code=404, content={"detail": f"Not found: {exc}"})


# ==============================================================================
# ROOT REDIRECT
# ==============================================================================

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "CAT Power Solution API", "docs": "/api/docs"}
