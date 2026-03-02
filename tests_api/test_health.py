"""
CAT Power Solution — Health Endpoint Tests
============================================
"""


class TestHealth:

    def test_health_returns_200(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["engine_functions"] == 16
        assert data["generator_models"] == 10

    def test_version_returns_metadata(self, client):
        resp = client.get("/api/v1/version")
        assert resp.status_code == 200
        data = resp.json()
        assert "app_version" in data
        assert "api_version" in data
        assert data["generator_count"] == 10

    def test_root_redirect(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "docs" in resp.json()
