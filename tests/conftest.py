"""
CAT Power Solution — Test Fixtures
====================================
Shared pytest fixtures for API and engine tests.
Mocks authentication so tests run without Entra ID.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from api.auth import AuthenticatedUser


# ── Mock users for each role ─────────────────────────────────────────────────

MOCK_USERS = {
    "admin": AuthenticatedUser(
        email="admin@caterpillar.com",
        name="Test Admin",
        groups=["SG-CPS-Admin"],
        role="admin",
    ),
    "full": AuthenticatedUser(
        email="engineer@caterpillar.com",
        name="Test Engineer",
        groups=["SG-CPS-Full"],
        role="full",
    ),
    "demo": AuthenticatedUser(
        email="demo@caterpillar.com",
        name="Test Demo User",
        groups=["SG-CPS-Demo"],
        role="demo",
    ),
}


def _make_role_override(role: str):
    """Create a dependency override for get_current_user that returns a mock user."""
    user = MOCK_USERS[role]

    async def _override():
        return user

    return _override


@pytest.fixture()
def client_no_auth():
    """TestClient with auth disabled (REQUIRE_AUTH=false)."""
    with patch.dict("os.environ", {"REQUIRE_AUTH": "false", "ENVIRONMENT": "test"}):
        # Clear the settings cache so new env vars take effect
        from api.config import get_settings
        get_settings.cache_clear()

        from api.main import app
        with TestClient(app) as c:
            yield c

        get_settings.cache_clear()


@pytest.fixture()
def client_admin():
    """TestClient authenticated as admin role."""
    from api.auth import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = _make_role_override("admin")
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def client_full():
    """TestClient authenticated as full role."""
    from api.auth import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = _make_role_override("full")
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def client_demo():
    """TestClient authenticated as demo role."""
    from api.auth import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = _make_role_override("demo")
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def client_anonymous():
    """TestClient with no authentication (no override, require_auth=true)."""
    with patch.dict("os.environ", {"REQUIRE_AUTH": "true", "ENVIRONMENT": "test"}):
        from api.config import get_settings
        get_settings.cache_clear()

        from api.main import app
        app.dependency_overrides.clear()
        with TestClient(app) as c:
            yield c

        get_settings.cache_clear()


# ── Sample sizing input for integration tests ────────────────────────────────

SAMPLE_SIZING_INPUT = {
    "header": {
        "project_name": "Test 100MW Data Center",
        "client_name": "Test Client",
    },
    "inputs": {
        "p_it": 100.0,
        "pue": 1.20,
        "generator_model": "G3520K",
        "use_bess": True,
        "bess_strategy": "Hybrid (Balanced)",
        "site_temp_c": 35.0,
        "site_alt_m": 100.0,
        "freq_hz": 60,
        "region": "US - Gulf Coast",
    },
}
