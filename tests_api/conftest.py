"""
CAT Power Solution — API Test Fixtures
========================================
Shared fixtures for API endpoint tests.
"""

import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def sample_generator_ref():
    """Standard generator reference for testing."""
    return {"model_name": "G3516H", "overrides": None}


@pytest.fixture
def sample_sizing_input():
    """Standard sizing input with defaults."""
    return {
        "header": {"project_name": "Test Project"},
        "inputs": {
            "p_it": 100.0,
            "pue": 1.20,
            "generator_model": "G3516H",
            "use_bess": True,
            "bess_strategy": "Hybrid (Balanced)",
            "site_temp_c": 35.0,
            "site_alt_m": 100.0,
            "freq_hz": 60,
        },
    }


@pytest.fixture
def sample_quick_sizing():
    """Minimal quick sizing input."""
    return {
        "p_it": 50.0,
        "pue": 1.25,
        "generator_model": "G3516H",
        "use_bess": True,
    }
