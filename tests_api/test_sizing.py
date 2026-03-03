"""
CAT Power Solution — Sizing Pipeline Tests
============================================
End-to-end tests for the full and quick sizing endpoints.
"""


class TestFullSizing:

    def test_full_sizing_default_inputs(self, client, sample_sizing_input):
        resp = client.post("/api/v1/sizing/full", json=sample_sizing_input)
        assert resp.status_code == 200
        data = resp.json()

        # Core results present
        assert data["n_running"] > 0
        assert data["n_total"] >= data["n_running"]
        assert data["installed_cap"] > 0
        assert data["fleet_efficiency"] > 0

        # Load calculations
        assert data["p_total_dc"] == 100.0 * 1.20
        assert data["p_total_avg"] > 0

        # BESS
        assert data["use_bess"] is True
        assert data["bess_power_mw"] >= 0

        # Financial
        assert data["lcoe"] > 0
        assert data["total_capex"] > 0

        # Reliability configs
        assert len(data["reliability_configs"]) >= 1

    def test_full_sizing_no_bess(self, client):
        resp = client.post("/api/v1/sizing/full", json={
            "inputs": {
                "p_it": 50.0,
                "use_bess": False,
                "generator_model": "G3516H",
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["use_bess"] is False
        assert data["bess_power_mw"] == 0

    def test_full_sizing_with_overrides(self, client):
        resp = client.post("/api/v1/sizing/full", json={
            "inputs": {
                "p_it": 100.0,
                "generator_model": "G3516H",
                "gen_overrides": {"iso_rating_mw": 3.0},
            },
        })
        assert resp.status_code == 200
        # With larger generators, should need fewer units
        data = resp.json()
        assert data["n_running"] > 0

    def test_full_sizing_unknown_generator(self, client):
        resp = client.post("/api/v1/sizing/full", json={
            "inputs": {
                "p_it": 100.0,
                "generator_model": "NONEXISTENT",
            },
        })
        assert resp.status_code == 404

    def test_full_sizing_gas_turbine(self, client):
        resp = client.post("/api/v1/sizing/full", json={
            "inputs": {
                "p_it": 200.0,
                "generator_model": "Titan 130",
                "use_bess": True,
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["selected_gen"] == "Titan 130"
        # Fewer units with larger turbines
        assert data["n_running"] < 50

    def test_project_name_propagates(self, client):
        resp = client.post("/api/v1/sizing/full", json={
            "header": {"project_name": "My Data Center"},
            "inputs": {"p_it": 50.0, "generator_model": "G3516H"},
        })
        assert resp.status_code == 200
        assert resp.json()["project_name"] == "My Data Center"


class TestQuickSizing:

    def test_quick_sizing_basic(self, client, sample_quick_sizing):
        resp = client.post("/api/v1/sizing/quick", json=sample_quick_sizing)
        assert resp.status_code == 200
        data = resp.json()
        assert data["p_it"] == 50.0
        assert data["n_running"] > 0
        assert data["lcoe"] > 0

    def test_quick_sizing_minimal(self, client):
        resp = client.post("/api/v1/sizing/quick", json={
            "p_it": 10.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_total"] >= 1


class TestProjects:

    def test_new_project(self, client):
        resp = client.get("/api/v1/projects/new")
        assert resp.status_code == 200
        data = resp.json()
        assert "header" in data
        assert "inputs" in data
        assert data["app_version"] == "4.0"

    def test_list_templates(self, client):
        resp = client.get("/api/v1/projects/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["templates"], list)
        assert len(data["templates"]) >= 4

    def test_get_defaults(self, client):
        resp = client.get("/api/v1/projects/defaults")
        assert resp.status_code == 200
        data = resp.json()
        assert "p_it" in data["defaults"]
        assert data["defaults"]["p_it"] == 100.0

    def test_get_countries(self, client):
        resp = client.get("/api/v1/projects/countries")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["countries"], list)
        assert len(data["countries"]) > 10

    def test_help_texts(self, client):
        resp = client.get("/api/v1/projects/help-texts")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert len(data) > 20
