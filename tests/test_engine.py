"""
CAT Power Solution — Engine Unit Tests
========================================
Validates that extracted calculation functions produce correct results.
Run with: pytest tests/test_engine.py -v
"""

import math
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.engine import (
    get_part_load_efficiency,
    transient_stability_check,
    frequency_screening,
    calculate_spinning_reserve_units,
    calculate_bess_requirements,
    calculate_bess_reliability_credit,
    calculate_availability_weibull,
    optimize_fleet_size,
    calculate_macrs_depreciation,
    noise_at_distance,
    calculate_combined_noise,
    noise_setback_distance,
    calculate_site_derate,
    calculate_emissions,
    calculate_footprint,
    calculate_lcoe,
)

from core.generator_library import (
    GENERATOR_LIBRARY,
    get_library,
    filter_by_type,
    get_model_names,
    get_model_summary,
)


# ==============================================================================
# PART-LOAD EFFICIENCY
# ==============================================================================

class TestPartLoadEfficiency:

    def test_full_load_returns_base_efficiency(self):
        """At 100% load, efficiency = base efficiency."""
        assert get_part_load_efficiency(0.441, 100, "High Speed") == 0.441

    def test_zero_load_returns_zero(self):
        """At 0% load, efficiency = 0."""
        assert get_part_load_efficiency(0.441, 0, "High Speed") == 0.0

    def test_part_load_reduces_efficiency(self):
        """At 50% load, efficiency < base."""
        eff_50 = get_part_load_efficiency(0.441, 50, "High Speed")
        assert 0 < eff_50 < 0.441

    def test_medium_speed_flatter_curve(self):
        """Medium speed engines have flatter part-load curves."""
        hs_50 = get_part_load_efficiency(0.441, 50, "High Speed")
        ms_50 = get_part_load_efficiency(0.441, 50, "Medium Speed")
        assert ms_50 > hs_50  # Medium speed better at part load

    def test_gas_turbine_steeper_curve(self):
        """Gas turbines lose efficiency faster at part load."""
        hs_50 = get_part_load_efficiency(0.441, 50, "High Speed")
        gt_50 = get_part_load_efficiency(0.441, 50, "Gas Turbine")
        assert gt_50 < hs_50  # Turbine worse at part load

    def test_unknown_type_returns_base(self):
        """Unknown gen type returns base efficiency unchanged."""
        assert get_part_load_efficiency(0.441, 50, "Unknown") == 0.441

    def test_clamping(self):
        """Load is clamped to 0-100 range."""
        eff_neg = get_part_load_efficiency(0.441, -10, "High Speed")
        eff_zero = get_part_load_efficiency(0.441, 0, "High Speed")
        assert eff_neg == eff_zero

        eff_high = get_part_load_efficiency(0.441, 150, "High Speed")
        eff_100 = get_part_load_efficiency(0.441, 100, "High Speed")
        assert eff_high == eff_100


# ==============================================================================
# TRANSIENT STABILITY
# ==============================================================================

class TestTransientStability:

    def test_pass_with_many_units(self):
        """Many units reduce equivalent reactance → passes."""
        ok, sag = transient_stability_check(0.14, 50, 25)
        assert ok is True
        assert sag < 10

    def test_fail_with_few_units(self):
        """Few units with high step load → fails."""
        ok, sag = transient_stability_check(0.14, 1, 100)
        assert ok is False
        assert sag > 10


# ==============================================================================
# FREQUENCY SCREENING
# ==============================================================================

class TestFrequencyScreening:

    def test_basic_screening(self):
        gen = GENERATOR_LIBRARY["G3516H"]
        result = frequency_screening(
            n_running=50, unit_cap_mw=2.5,
            p_avg_mw=100, step_mw=30,
            gen_data=gen, freq_hz=60,
        )
        assert 'nadir_hz' in result
        assert 'rocof_hz_s' in result
        assert 'notes' in result
        assert isinstance(result['nadir_ok'], bool)

    def test_bess_improves_frequency(self):
        """BESS should improve both nadir and ROCOF."""
        gen = GENERATOR_LIBRARY["G3516H"]
        no_bess = frequency_screening(50, 2.5, 100, 30, gen, freq_hz=60)
        with_bess = frequency_screening(50, 2.5, 100, 30, gen,
                                         bess_mw=30, bess_enabled=True, freq_hz=60)
        assert with_bess['nadir_hz'] >= no_bess['nadir_hz']
        assert with_bess['rocof_hz_s'] <= no_bess['rocof_hz_s']


# ==============================================================================
# SPINNING RESERVE
# ==============================================================================

class TestSpinningReserve:

    def test_no_bess_more_units(self):
        """Without BESS, more units needed for spinning reserve."""
        no_bess = calculate_spinning_reserve_units(100, 2.5, 20)
        with_bess = calculate_spinning_reserve_units(100, 2.5, 20,
                                                      use_bess=True, bess_power_mw=20)
        assert no_bess['n_units_running'] >= with_bess['n_units_running']

    def test_minimum_one_unit(self):
        """Always at least 1 unit running."""
        result = calculate_spinning_reserve_units(0.1, 100, 0)
        assert result['n_units_running'] >= 1


# ==============================================================================
# BESS SIZING
# ==============================================================================

class TestBessSizing:

    def test_basic_sizing(self):
        power, energy, breakdown = calculate_bess_requirements(
            p_net_req_avg=100, p_net_req_peak=115,
            step_load_req=40, gen_ramp_rate=0.5,
            gen_step_capability=25, load_change_rate_req=3.0,
        )
        assert power > 0
        assert energy > 0
        assert 'step_support' in breakdown

    def test_black_start_increases_bess(self):
        """Black start adds BESS capacity."""
        _, _, bd_no = calculate_bess_requirements(100, 115, 40, 0.5, 25, 3.0, False)
        _, _, bd_yes = calculate_bess_requirements(100, 115, 40, 0.5, 25, 3.0, True)
        assert bd_yes['black_start'] > bd_no['black_start']


# ==============================================================================
# AVAILABILITY
# ==============================================================================

class TestAvailability:

    def test_more_reserves_higher_availability(self):
        """N+2 should have higher availability than N+1."""
        avail_1, _ = calculate_availability_weibull(51, 50, 0.93, 20)
        avail_2, _ = calculate_availability_weibull(52, 50, 0.93, 20)
        assert avail_2 > avail_1

    def test_availability_flat_over_time(self):
        """Availability should be constant (no aging model)."""
        _, timeline = calculate_availability_weibull(52, 50, 0.93, 20)
        assert len(timeline) == 20
        assert timeline[0] == timeline[-1]

    def test_fleet_availability_realistic_range(self):
        """At 93% unit avail, N+1 for 10 units gives ~82% — not unrealistically high.
        The old MTBF model gave >99% unit avail → 99.999% fleet avail for N+1.
        With 93% unit avail, more reserves (N+3, N+4, etc.) are needed to reach 99.99%."""
        avail_n1, _ = calculate_availability_weibull(11, 10, 0.93, 20)
        # N+1 at 93% is ~82% — realistic, not inflated
        assert avail_n1 < 0.90, f"N+1 fleet availability {avail_n1} too high for 93% unit avail"

        # Verify that adding more reserves increases availability toward 99.99%
        avail_n5, _ = calculate_availability_weibull(15, 10, 0.93, 20)
        assert avail_n5 > avail_n1, "More reserves should increase fleet availability"
        assert avail_n5 > 0.99, f"N+5 should be above 99%, got {avail_n5}"

    def test_unit_availability_from_library(self):
        """Each generator should have a unit_availability field."""
        for model, data in GENERATOR_LIBRARY.items():
            assert "unit_availability" in data, f"{model} missing unit_availability"
            assert 0.70 <= data["unit_availability"] <= 0.99, f"{model} availability out of range"


# ==============================================================================
# FLEET OPTIMIZATION
# ==============================================================================

class TestFleetOptimization:

    def test_basic_optimization(self):
        gen = GENERATOR_LIBRARY["G3516H"]
        n, options = optimize_fleet_size(100, 115, 2.5, 40, gen)
        assert n > 0
        assert isinstance(options, dict)

    def test_bess_reduces_fleet(self):
        """With BESS, optimal fleet should be same or smaller."""
        gen = GENERATOR_LIBRARY["G3516H"]
        n_no_bess, _ = optimize_fleet_size(100, 115, 2.5, 40, gen, use_bess=False)
        n_bess, _ = optimize_fleet_size(100, 115, 2.5, 40, gen, use_bess=True)
        assert n_bess <= n_no_bess


# ==============================================================================
# GENERATOR LIBRARY
# ==============================================================================

class TestGeneratorLibrary:

    def test_library_has_10_models(self):
        assert len(GENERATOR_LIBRARY) == 10

    def test_all_models_have_required_fields(self):
        required = ['iso_rating_mw', 'electrical_efficiency', 'type',
                     'unit_availability', 'step_load_pct']
        for model, data in GENERATOR_LIBRARY.items():
            for field in required:
                assert field in data, f"{model} missing {field}"

    def test_filter_by_type(self):
        hs = filter_by_type(GENERATOR_LIBRARY, ["High Speed"])
        assert "G3516H" in hs
        assert "Titan 130" not in hs

    def test_get_library_returns_deep_copy(self):
        lib = get_library()
        lib["G3516H"]["iso_rating_mw"] = 999
        assert GENERATOR_LIBRARY["G3516H"]["iso_rating_mw"] == 2.5


# ==============================================================================
# NOISE
# ==============================================================================

class TestNoise:

    def test_noise_decreases_with_distance(self):
        assert noise_at_distance(90, 100) < noise_at_distance(90, 10)

    def test_combined_noise_increases_with_units(self):
        n1 = calculate_combined_noise(95, 10, 1)
        n10 = calculate_combined_noise(95, 10, 10)
        assert n10 > n1

    def test_setback_distance(self):
        d = noise_setback_distance(90, 55)
        assert d > 1  # Should need some distance


# ==============================================================================
# SITE DERATING
# ==============================================================================

class TestSiteDerating:
    """Tests for CAT official table-based derating with bilinear interpolation."""

    def test_returns_dict_with_all_fields(self):
        """Result should contain all derating breakdown fields."""
        result = calculate_site_derate(25, 0, 80)
        assert "derate_factor" in result
        assert "methane_deration" in result
        assert "altitude_deration" in result
        assert "achrf" in result
        assert "methane_warning" in result

    def test_iso_conditions_no_derate(self):
        """At 25°C, 0m altitude, MN=80 → all factors are 1.0."""
        result = calculate_site_derate(25, 0, 80)
        assert result["derate_factor"] == 1.0
        assert result["methane_deration"] == 1.0
        assert result["altitude_deration"] == 1.0
        assert result["achrf"] == 1.0
        assert result["methane_warning"] is None

    def test_25c_300m_still_no_derate(self):
        """At 25°C, 300m — ADF table still gives 1.0."""
        result = calculate_site_derate(25, 300, 80)
        assert result["altitude_deration"] == 1.0
        assert result["derate_factor"] == 1.0

    def test_hot_site_derates(self):
        """45°C at 1000m → ADF = 0.91 (from CAT table)."""
        result = calculate_site_derate(45, 1000, 80)
        assert result["altitude_deration"] == 0.91
        assert result["derate_factor"] == 0.91
        assert result["methane_deration"] == 1.0

    def test_high_altitude_derates(self):
        """25°C at 1500m → ADF table gives 0.98."""
        result = calculate_site_derate(25, 1500, 80)
        assert result["altitude_deration"] == 0.98
        assert result["derate_factor"] == 0.98

    def test_poor_fuel_derates(self):
        """MN=50 → methane deration = 0.84 (from CAT table)."""
        result = calculate_site_derate(25, 0, 50)
        assert result["methane_deration"] == 0.84
        assert result["derate_factor"] == 0.84

    def test_methane_below_32_zero(self):
        """MN < 32 → cannot operate, derate = 0."""
        result = calculate_site_derate(25, 0, 30)
        assert result["methane_deration"] == 0.0
        assert result["derate_factor"] == 0.0
        assert result["methane_warning"] is not None
        assert "not suitable" in result["methane_warning"]

    def test_methane_below_60_warns(self):
        """MN < 60 but >= 32 → warns about low quality."""
        result = calculate_site_derate(25, 0, 50)
        assert result["methane_warning"] is not None
        assert "below 60" in result["methane_warning"]

    def test_methane_60_plus_no_warning(self):
        """MN >= 60 → no warning."""
        result = calculate_site_derate(25, 0, 60)
        assert result["methane_deration"] == 1.0
        assert result["methane_warning"] is None

    def test_combined_derating(self):
        """45°C, 1500m, MN=50 → combined < 0.85."""
        result = calculate_site_derate(45, 1500, 50)
        assert result["derate_factor"] < 0.85

    def test_exact_table_point_50c_3000m(self):
        """Exact table corner: 50°C, 3000m → ADF = 0.55."""
        result = calculate_site_derate(50, 3000, 80)
        assert result["altitude_deration"] == 0.55

    def test_exact_table_point_45c_1000m(self):
        """Exact table point: 45°C, 1000m → ADF = 0.91."""
        result = calculate_site_derate(45, 1000, 80)
        assert result["altitude_deration"] == 0.91

    def test_exact_mn_32(self):
        """MN=32 is the minimum operable → factor = 0.70."""
        result = calculate_site_derate(25, 0, 32)
        assert result["methane_deration"] == 0.70

    def test_bilinear_interpolation_between_points(self):
        """37.5°C, 625m should interpolate between grid points."""
        result = calculate_site_derate(37.5, 625, 80)
        # Between 35°C and 40°C, between 500m and 750m
        # All four ADF corners are 1.0, so result should be 1.0
        assert result["altitude_deration"] == 1.0

    def test_achrf_hot_high(self):
        """ACHRF > 1.0 at hot, high-altitude conditions."""
        result = calculate_site_derate(50, 3000, 80)
        assert result["achrf"] == 1.38

    def test_achrf_cool_low(self):
        """ACHRF = 1.0 at cool, low-altitude conditions."""
        result = calculate_site_derate(10, 0, 80)
        assert result["achrf"] == 1.0

    def test_clamping_temp_above_max(self):
        """Temp > 50°C should clamp to 50°C table row."""
        result_60 = calculate_site_derate(60, 0, 80)
        result_50 = calculate_site_derate(50, 0, 80)
        assert result_60["altitude_deration"] == result_50["altitude_deration"]

    def test_clamping_alt_above_max(self):
        """Alt > 3000m should clamp to 3000m column."""
        result_4000 = calculate_site_derate(25, 4000, 80)
        result_3000 = calculate_site_derate(25, 3000, 80)
        assert result_4000["altitude_deration"] == result_3000["altitude_deration"]


# ==============================================================================
# FINANCIAL
# ==============================================================================

class TestFinancial:

    def test_macrs_depreciation(self):
        benefit = calculate_macrs_depreciation(100_000_000, 20)
        assert benefit > 0

    def test_lcoe_basic(self):
        result = calculate_lcoe(
            total_capex=200_000_000,
            annual_om=5_000_000,
            annual_fuel_cost=15_000_000,
            annual_energy_mwh=700_000,
            wacc=0.08,
            project_years=20,
        )
        assert result['lcoe'] > 0
        assert result['lcoe'] < 200  # Should be in $/MWh range (0.02-0.15 $/kWh = 20-150 $/MWh)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
