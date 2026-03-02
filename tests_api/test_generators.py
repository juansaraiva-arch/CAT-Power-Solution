"""
CAT Power Solution — Generator Endpoint Tests
===============================================
"""


class TestGenerators:

    def test_list_all_generators(self, client):
        resp = client.get("/api/v1/generators")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 10
        assert "G3516H" in data["generators"]

    def test_list_generator_names(self, client):
        resp = client.get("/api/v1/generators/names")
        assert resp.status_code == 200
        names = resp.json()
        assert isinstance(names, list)
        assert "G3516H" in names
        assert len(names) == 10

    def test_get_specific_generator(self, client):
        resp = client.get("/api/v1/generators/G3516H")
        assert resp.status_code == 200
        data = resp.json()
        assert data["iso_rating_mw"] == 2.5
        assert data["type"] == "High Speed"

    def test_get_unknown_generator_404(self, client):
        resp = client.get("/api/v1/generators/UNKNOWN_MODEL")
        assert resp.status_code == 404

    def test_get_generator_summary(self, client):
        resp = client.get("/api/v1/generators/G3516H/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"] == "G3516H"
        assert data["mw"] == 2.5

    def test_filter_by_type(self, client):
        resp = client.post(
            "/api/v1/generators/filter",
            json={"types": ["Gas Turbine"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3  # Titan 130, 250, 350
        assert "Titan 130" in data["generators"]

    def test_filter_by_query_param(self, client):
        resp = client.get("/api/v1/generators?type_filter=High Speed")
        assert resp.status_code == 200
        data = resp.json()
        # All returned generators should be High Speed
        for name, spec in data["generators"].items():
            assert spec["type"] == "High Speed"

    def test_filter_multiple_types(self, client):
        resp = client.post(
            "/api/v1/generators/filter",
            json={"types": ["High Speed", "Medium Speed"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 7  # 6 High Speed + 1 Medium Speed
