"""
CAT Power Solution — Core Module
==================================
Pure business logic with zero UI dependencies.

Submodules:
  engine             — Sizing calculations (efficiency, BESS, fleet, availability, LCOE)
  generator_library  — Generator specifications + GERP PDF parser
  project_manager    — Project data model, defaults, save/load JSON
  pdf_report         — PDF report generation (ReportLab)
"""

from .engine import (
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

from .generator_library import (
    GENERATOR_LIBRARY,
    get_library,
    filter_by_type,
    get_model_names,
    get_model_summary,
    parse_gerp_pdf,
)

from .project_manager import (
    INPUT_DEFAULTS,
    HEADER_DEFAULTS,
    TEMPLATES,
    HELP_TEXTS,
    COUNTRIES,
    DC_TYPE_DEFAULTS,
    new_project,
    apply_template,
    project_to_json,
    project_from_json,
)

from .pdf_report import generate_comprehensive_pdf
