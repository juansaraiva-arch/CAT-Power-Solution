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

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

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
# STATIC FRONTEND (Production Mode)
# ==============================================================================
# In Docker/production, the built React app is in /app/static.
# FastAPI serves it so we only need a single server.

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

if STATIC_DIR.is_dir():
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="static-assets")

    @app.get("/", include_in_schema=False)
    async def serve_spa():
        return FileResponse(str(STATIC_DIR / "index.html"))

    # Catch-all: any non-API route returns the SPA (for client-side routing)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def catch_all(request: Request, full_path: str):
        # Don't catch API routes
        if full_path.startswith("api"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        # Serve actual static files if they exist
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        # Otherwise return index.html for SPA routing
        return FileResponse(str(STATIC_DIR / "index.html"))
else:
    # Development mode: no static dir, just return API info
    @app.get("/", include_in_schema=False)
    async def root():
        return {"message": "CAT Power Solution API", "docs": "/api/docs"}
