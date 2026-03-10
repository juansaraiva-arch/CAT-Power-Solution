"""
CAT Power Solution — API Smoke Tests
======================================
Verifies authentication, authorization, and basic endpoint behavior.
Run with: pytest tests/test_api.py -v
"""

import pytest
from tests.conftest import SAMPLE_SIZING_INPUT


# ==============================================================================
# 1. Health endpoint — no auth required
# ==============================================================================

class TestHealth:
    def test_health_returns_200(self, client_no_auth):
        """GET /api/v1/health without auth → 200."""
        resp = client_no_auth.get("/api/v1/health")
        assert resp.status_code == 200

    def test_health_check_structure(self, client_no_auth):
        """/health returns status, version, and environment."""
        resp = client_no_auth.get("/api/v1/health")
        data = resp.json()
        assert "status" in data
        assert "version" in data
        assert "environment" in data
        assert data["status"] == "healthy"


# ==============================================================================
# 2. Authentication — sizing requires auth
# ==============================================================================

class TestSizingAuth:
    def test_sizing_requires_auth(self, client_anonymous):
        """POST /api/v1/sizing/full without token → 401."""
        resp = client_anonymous.post("/api/v1/sizing/full", json=SAMPLE_SIZING_INPUT)
        assert resp.status_code == 401

    def test_sizing_demo_role_forbidden(self, client_demo):
        """POST /api/v1/sizing/full with role=demo → 403."""
        resp = client_demo.post("/api/v1/sizing/full", json=SAMPLE_SIZING_INPUT)
        assert resp.status_code == 403

    def test_sizing_full_role_allowed(self, client_full):
        """POST /api/v1/sizing/full with role=full → 200."""
        resp = client_full.post("/api/v1/sizing/full", json=SAMPLE_SIZING_INPUT)
        assert resp.status_code == 200


# ==============================================================================
# 3. Generators — demo role allowed
# ==============================================================================

class TestGenerators:
    def test_generators_demo_allowed(self, client_demo):
        """GET /api/v1/generators/ with role=demo → 200."""
        resp = client_demo.get("/api/v1/generators")
        assert resp.status_code == 200


# ==============================================================================
# 4. Integration — 100 MW data center sizing
# ==============================================================================

class TestSizingIntegration:
    def test_sizing_100mw_data_center(self, client_full):
        """100 MW, G3520K, Houston TX — canonical test case."""
        resp = client_full.post("/api/v1/sizing/full", json=SAMPLE_SIZING_INPUT)
        assert resp.status_code == 200
        data = resp.json()

        # Fleet size: 100 MW with G3520K (2.5 MW) → need ~40+ units
        assert data["n_total"] >= 40

        # Availability target: 99.99% four-nines
        assert data["system_availability"] >= 0.9999, (
            f"Expected >= 99.99% availability, got {data['system_availability']}"
        )

        # LCOE sanity checks
        assert data["lcoe"] > 0, "LCOE must be positive"
        assert data["lcoe"] < 500, "LCOE sanity check: must be < 500 $/MWh"
