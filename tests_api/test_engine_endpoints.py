"""
CAT Power Solution — Engine Endpoint Tests
============================================
Tests for each of the 16 individual calculation endpoints.
"""


class TestPartLoadEfficiency:

    def test_full_load(self, client):
        resp = client.post("/api/v1/engine/part-load-efficiency", json={
            "base_efficiency": 0.441, "load_pct": 100, "gen_type": "High Speed",
        })
        assert resp.status_code == 200
        assert resp.json()["efficiency"] == 0.441

    def test_part_load(self, client):
        resp = client.post("/api/v1/engine/part-load-efficiency", json={
            "base_efficiency": 0.441, "load_pct": 50, "gen_type": "High Speed",
        })
        assert resp.status_code == 200
        assert 0 < resp.json()["efficiency"] < 0.441


class TestTransientStability:

    def test_passes_with_many_units(self, client):
        resp = client.post("/api/v1/engine/transient-stability", json={
            "xd_pu": 0.14, "num_units": 50, "step_load_pct": 25,
        })
        assert resp.status_code == 200
        assert resp.json()["passes"] is True

    def test_fails_with_few_units(self, client):
        resp = client.post("/api/v1/engine/transient-stability", json={
            "xd_pu": 0.14, "num_units": 1, "step_load_pct": 100,
        })
        assert resp.status_code == 200
        assert resp.json()["passes"] is False


class TestFrequencyScreening:

    def test_basic_screening(self, client):
        resp = client.post("/api/v1/engine/frequency-screening", json={
            "n_running": 50, "unit_cap_mw": 2.5, "p_avg_mw": 100,
            "step_mw": 30,
            "generator": {"model_name": "G3516H"},
            "freq_hz": 60,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "nadir_hz" in data
        assert "rocof_hz_s" in data
        assert isinstance(data["nadir_ok"], bool)

    def test_unknown_generator_404(self, client):
        resp = client.post("/api/v1/engine/frequency-screening", json={
            "n_running": 50, "unit_cap_mw": 2.5, "p_avg_mw": 100,
            "step_mw": 30,
            "generator": {"model_name": "NONEXISTENT"},
        })
        assert resp.status_code == 404


class TestSpinningReserve:

    def test_basic_calculation(self, client):
        resp = client.post("/api/v1/engine/spinning-reserve", json={
            "p_avg_load": 100, "unit_capacity": 2.5, "spinning_reserve_pct": 20,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_units_running"] >= 1
        assert data["spinning_reserve_mw"] >= 0


class TestBessRequirements:

    def test_basic_sizing(self, client):
        resp = client.post("/api/v1/engine/bess-requirements", json={
            "p_net_req_avg": 100, "p_net_req_peak": 115,
            "step_load_req": 40, "gen_ramp_rate": 0.5,
            "gen_step_capability": 25, "load_change_rate_req": 3.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["bess_power_mw"] > 0
        assert data["bess_energy_mwh"] > 0
        assert "step_support" in data["breakdown"]


class TestBessReliabilityCredit:

    def test_basic_credit(self, client):
        resp = client.post("/api/v1/engine/bess-reliability-credit", json={
            "bess_power_mw": 10, "bess_energy_mwh": 20, "unit_capacity_mw": 2.5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "effective_credit" in data
        assert data["effective_credit"] >= 0


class TestAvailability:

    def test_basic_availability(self, client):
        resp = client.post("/api/v1/engine/availability", json={
            "n_total": 52, "n_running": 50, "unit_availability": 0.93, "project_years": 20,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert 0 < data["system_availability"] <= 1.0
        assert len(data["availability_over_time"]) == 20


class TestFleetOptimization:

    def test_basic_optimization(self, client):
        resp = client.post("/api/v1/engine/fleet-optimization", json={
            "p_net_req_avg": 100, "p_net_req_peak": 115,
            "unit_cap": 2.5, "step_load_req": 40,
            "generator": {"model_name": "G3516H"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["optimal_n_running"] > 0


class TestMacrsDepreciation:

    def test_basic_depreciation(self, client):
        resp = client.post("/api/v1/engine/macrs-depreciation", json={
            "capex": 100_000_000, "project_years": 20,
        })
        assert resp.status_code == 200
        assert resp.json()["pv_tax_shield"] > 0


class TestNoise:

    def test_noise_at_distance(self, client):
        resp = client.post("/api/v1/engine/noise/at-distance", json={
            "combined_db": 90, "distance_m": 100,
        })
        assert resp.status_code == 200
        assert resp.json()["noise_db"] < 90

    def test_combined_noise(self, client):
        resp = client.post("/api/v1/engine/noise/combined", json={
            "source_noise_db": 95, "attenuation_db": 10, "n_running": 10,
        })
        assert resp.status_code == 200
        assert resp.json()["combined_noise_db"] > 0

    def test_noise_setback(self, client):
        resp = client.post("/api/v1/engine/noise/setback", json={
            "combined_db": 90, "noise_limit_db": 55,
        })
        assert resp.status_code == 200
        assert resp.json()["setback_distance_m"] > 0


class TestSiteDerate:

    def test_iso_conditions(self, client):
        resp = client.post("/api/v1/engine/site-derate", json={
            "site_temp_c": 25, "site_alt_m": 0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["derate_factor"] == 1.0
        assert data["methane_deration"] == 1.0
        assert data["altitude_deration"] == 1.0
        assert data["achrf"] == 1.0
        assert data["methane_warning"] is None

    def test_hot_site(self, client):
        resp = client.post("/api/v1/engine/site-derate", json={
            "site_temp_c": 45, "site_alt_m": 1000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["derate_factor"] == 0.91
        assert data["altitude_deration"] == 0.91
        assert data["achrf"] == 1.29

    def test_methane_below_32(self, client):
        resp = client.post("/api/v1/engine/site-derate", json={
            "site_temp_c": 25, "site_alt_m": 0, "methane_number": 30,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["derate_factor"] == 0.0
        assert data["methane_deration"] == 0.0
        assert data["methane_warning"] is not None


class TestEmissions:

    def test_basic_emissions(self, client):
        resp = client.post("/api/v1/engine/emissions", json={
            "n_running": 50, "unit_cap_mw": 2.5,
            "generator": {"model_name": "G3516H"},
            "capacity_factor": 0.9, "load_per_unit_pct": 80,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["co2_tpy"] > 0
        assert data["nox_tpy"] >= 0


class TestFootprint:

    def test_basic_footprint(self, client):
        resp = client.post("/api/v1/engine/footprint", json={
            "n_total": 55, "unit_cap_mw": 2.5,
            "generator": {"model_name": "G3516H"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_area_m2"] > 0
        assert data["gen_area_m2"] > 0


class TestLcoe:

    def test_basic_lcoe(self, client):
        resp = client.post("/api/v1/engine/lcoe", json={
            "total_capex": 200_000_000,
            "annual_om": 5_000_000,
            "annual_fuel_cost": 15_000_000,
            "annual_energy_mwh": 700_000,
            "wacc": 0.08,
            "project_years": 20,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["lcoe"] > 0
        assert data["lcoe"] < 200  # $/MWh range
