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
        avail_1, _ = calculate_availability_weibull(51, 50, 50000, 20)
        avail_2, _ = calculate_availability_weibull(52, 50, 50000, 20)
        assert avail_2 > avail_1

    def test_availability_over_time_decreases(self):
        """Availability should generally decrease over time due to aging."""
        _, timeline = calculate_availability_weibull(52, 50, 50000, 20)
        assert len(timeline) == 20
        assert timeline[0] >= timeline[-1]


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

    def test_library_has_8_models(self):
        assert len(GENERATOR_LIBRARY) == 8

    def test_all_models_have_required_fields(self):
        required = ['iso_rating_mw', 'electrical_efficiency', 'type',
                     'mtbf_hours', 'step_load_pct']
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

    def test_iso_conditions_no_derate(self):
        """ISO standard conditions → no derating."""
        factor = calculate_site_derate(25, 300, 80)
        assert factor == 1.0

    def test_hot_site_derates(self):
        factor = calculate_site_derate(45, 300, 80)
        assert factor < 1.0

    def test_high_altitude_derates(self):
        factor = calculate_site_derate(25, 1500, 80)
        assert factor < 1.0

    def test_poor_fuel_derates(self):
        factor = calculate_site_derate(25, 300, 60)
        assert factor < 1.0

    def test_combined_derating(self):
        factor = calculate_site_derate(45, 1500, 60)
        assert factor < 0.85  # Significant combined derating


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
