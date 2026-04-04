"""
tests/test_proposal.py
======================
Tests for CAT Power Solution proposal document generation.

Completely independent from test_engine.py and test_api.py.
Do not import anything from those files.
"""
import io
import os
import zipfile
from datetime import date
from unittest.mock import MagicMock

import pytest

from core.proposal_defaults import (
    PROPOSAL_DEFAULTS,
    PROPOSAL_TYPE_OPTIONS,
    INCOTERM_OPTIONS,
    DELIVERY_DESTINATION_OPTIONS,
)
from core.proposal_generator import _generate_proposal_docx_legacy as generate_proposal_docx


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_sizing_result():
    """
    Minimal SizingResult mock sufficient for proposal generation.
    Uses MagicMock so any unexpected attribute access returns a MagicMock
    rather than raising AttributeError — mirrors the defensive coding required
    in proposal_generator.py.
    """
    r = MagicMock()
    r.selected_gen = "CAT G3520H"
    r.total_facility_mw = 100.0

    # Config A (best reliability configuration)
    r.config_a = MagicMock()
    r.config_a.n_units = 10
    r.config_a.availability = 0.9995
    r.config_a.unit_derated_mw = 9.8

    # Fallback n_units at top level
    r.n_units = 10

    # BESS
    r.bess = MagicMock()
    r.bess.power_mw = 5.0
    r.bess.energy_mwh = 10.0

    # Financial
    r.financial = MagicMock()
    r.financial.capex_total_musd = 85.0

    # Footprint
    r.footprint = MagicMock()
    r.footprint.total_area_m2 = 4200.0

    # Site conditions (may be accessed for §3.2)
    r.site_temp_c = 35.0
    r.site_alt_m = 500.0
    r.freq_hz = 60
    r.methane_number = 70
    r.fuel_mode = "Pipeline Gas"
    r.p_it = 80.0
    r.pue = 1.25
    r.step_load_pct = 25
    r.acoustic_treatment = "Standard"

    return r


@pytest.fixture
def mock_sizing_result_no_bess(mock_sizing_result):
    """Variant with BESS explicitly set to None."""
    mock_sizing_result.bess = None
    return mock_sizing_result


@pytest.fixture
def sample_header():
    return {
        "project_name":   "Test DC Project",
        "client_name":    "ACME Hyperscale",
        "contact_name":   "John Doe",
        "contact_email":  "jdoe@acme.com",
        "contact_phone":  "+1 555 123 4567",
        "country":        "United States",
        "state_province": "Texas",
    }


@pytest.fixture
def sample_proposal_info():
    """Fully populated proposal info based on PROPOSAL_DEFAULTS with test values."""
    info = dict(PROPOSAL_DEFAULTS)
    info["bdm_name"] = "Francisco Saraiva"
    info["bdm_email"] = "fsaraiva@cat.com"
    info["dealer_name"] = "Thompson CAT"
    info["delivery_date_est"] = "Q3 2027 (~18 months ARO)"
    info["proposal_notes"] = "This is a budgetary estimate only."
    return info


@pytest.fixture
def minimal_proposal_info():
    """Minimal proposal info — many fields empty, tests graceful fallback."""
    return dict(PROPOSAL_DEFAULTS)


# =============================================================================
# TEST CLASS 1: PROPOSAL_DEFAULTS structure
# =============================================================================

class TestProposalDefaults:
    """Validate the defaults module structure and completeness."""

    REQUIRED_KEYS = [
        "cat_division", "proposal_type", "doc_version",
        "bdm_name", "bdm_email",
        "dealer_name", "dealer_contact",
        "incoterm", "delivery_destination", "delivery_date_est",
        "proposal_validity",
        "payment_pct_down", "payment_pct_30d", "payment_pct_sol", "payment_pct_rts",
        "offer_type_genset", "offer_type_switchgear",
        "offer_type_solutions", "offer_type_hybrid",
        "include_cva", "include_esc",
        "additional_options", "proposal_notes",
    ]

    def test_all_required_keys_present(self):
        for key in self.REQUIRED_KEYS:
            assert key in PROPOSAL_DEFAULTS, f"Missing required key: '{key}'"

    def test_proposal_type_options_contains_three_types(self):
        assert "Budgetary" in PROPOSAL_TYPE_OPTIONS
        assert "Preliminary" in PROPOSAL_TYPE_OPTIONS
        assert "Final" in PROPOSAL_TYPE_OPTIONS

    def test_incoterm_options_contains_exw(self):
        assert any("EXW" in opt or "Ex Works" in opt for opt in INCOTERM_OPTIONS)

    def test_incoterm_options_minimum_length(self):
        assert len(INCOTERM_OPTIONS) >= 5

    def test_delivery_destination_options_minimum_length(self):
        assert len(DELIVERY_DESTINATION_OPTIONS) >= 4

    def test_default_payment_sums_to_100(self):
        total = (
            PROPOSAL_DEFAULTS["payment_pct_down"] +
            PROPOSAL_DEFAULTS["payment_pct_30d"] +
            PROPOSAL_DEFAULTS["payment_pct_sol"] +
            PROPOSAL_DEFAULTS["payment_pct_rts"]
        )
        assert total == 100, (
            f"Default payment terms sum to {total}%, expected 100%. "
            f"Values: down={PROPOSAL_DEFAULTS['payment_pct_down']}, "
            f"30d={PROPOSAL_DEFAULTS['payment_pct_30d']}, "
            f"sol={PROPOSAL_DEFAULTS['payment_pct_sol']}, "
            f"rts={PROPOSAL_DEFAULTS['payment_pct_rts']}"
        )

    def test_additional_options_is_empty_list(self):
        assert isinstance(PROPOSAL_DEFAULTS["additional_options"], list)
        assert len(PROPOSAL_DEFAULTS["additional_options"]) == 0

    def test_offer_type_genset_is_true_by_default(self):
        assert PROPOSAL_DEFAULTS["offer_type_genset"] is True

    def test_other_offer_types_false_by_default(self):
        assert PROPOSAL_DEFAULTS["offer_type_switchgear"] is False
        assert PROPOSAL_DEFAULTS["offer_type_solutions"] is False
        assert PROPOSAL_DEFAULTS["offer_type_hybrid"] is False

    def test_cat_division_default_not_empty(self):
        assert PROPOSAL_DEFAULTS["cat_division"] != ""

    def test_proposal_validity_default_not_empty(self):
        assert PROPOSAL_DEFAULTS["proposal_validity"] != ""


# =============================================================================
# TEST CLASS 2: DOCX generation — output structure
# =============================================================================

class TestProposalDocxOutput:
    """Validate that the DOCX output is structurally valid."""

    def test_returns_bytes(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        assert isinstance(result, bytes)

    def test_output_is_non_trivial(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        assert len(result) > 5_000, f"Output too small ({len(result)} bytes) — likely empty document"

    def test_output_is_valid_zip(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        buf = io.BytesIO(result)
        assert zipfile.is_zipfile(buf), "Output is not a valid ZIP archive (invalid DOCX)"

    def test_output_contains_document_xml(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as z:
            names = z.namelist()
        assert "word/document.xml" in names, f"word/document.xml not found. Files: {names}"

    def test_output_contains_content_types(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as z:
            names = z.namelist()
        assert "[Content_Types].xml" in names

    def test_output_path_writes_file(self, tmp_path, mock_sizing_result, sample_header, sample_proposal_info):
        out_path = str(tmp_path / "test_proposal.docx")
        result = generate_proposal_docx(
            mock_sizing_result, sample_header, sample_proposal_info,
            output_path=out_path,
        )
        assert os.path.exists(out_path), "File was not written to output_path"
        assert os.path.getsize(out_path) > 5_000
        assert isinstance(result, bytes), "Function must return bytes even when output_path is set"

    def test_output_path_none_does_not_create_file(self, mock_sizing_result, sample_header, sample_proposal_info):
        """When output_path=None, no file should be written to disk."""
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        assert isinstance(result, bytes)
        # Verify no stray file was created in cwd
        assert not os.path.exists("proposal.docx"), "Unexpected file created in cwd"


# =============================================================================
# TEST CLASS 3: DOCX content — key strings
# =============================================================================

def _get_document_xml(docx_bytes: bytes) -> str:
    """Helper: extract word/document.xml as a string from DOCX bytes."""
    buf = io.BytesIO(docx_bytes)
    with zipfile.ZipFile(buf) as z:
        return z.read("word/document.xml").decode("utf-8")


class TestProposalDocxContent:
    """Validate that key strings appear in the generated document."""

    def test_project_name_in_document(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Test DC Project" in xml

    def test_client_name_in_document(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "ACME Hyperscale" in xml

    def test_generator_model_in_document(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "CAT G3520H" in xml

    def test_dealer_name_in_document(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Thompson CAT" in xml

    def test_bdm_name_in_document(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Francisco Saraiva" in xml

    def test_current_year_in_document(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert str(date.today().year) in xml, "Current year not found in document"

    def test_section_executive_summary(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Executive Summary" in xml

    def test_section_solution_overview(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Solution Overview" in xml

    def test_section_technical_offer(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Technical Offer" in xml

    def test_section_pricing(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Pricing" in xml

    def test_section_clarifications(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Clarifications" in xml

    def test_section_commercial_assumptions(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Commercial Assumptions" in xml

    def test_appendix_a_definitions(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Appendix A" in xml
        assert "Definitions" in xml

    def test_appendix_f_esc(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Extended Service Coverage" in xml

    def test_appendix_g_cva(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Customer Value Agreement" in xml

    def test_incoterm_in_document(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "EXW" in xml or "Ex Works" in xml

    def test_proposal_notes_in_document(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "budgetary estimate only" in xml

    def test_caterpillar_text_in_document(self, mock_sizing_result, sample_header, sample_proposal_info):
        result = generate_proposal_docx(mock_sizing_result, sample_header, sample_proposal_info)
        xml = _get_document_xml(result)
        assert "Caterpillar" in xml


# =============================================================================
# TEST CLASS 4: Edge cases and graceful degradation
# =============================================================================

class TestProposalEdgeCases:
    """Test graceful handling of missing/empty fields and edge conditions."""

    def test_minimal_proposal_info_does_not_crash(
        self, mock_sizing_result, sample_header, minimal_proposal_info
    ):
        """Empty BDM name, empty dealer name — should not raise, just leave blanks."""
        result = generate_proposal_docx(mock_sizing_result, sample_header, minimal_proposal_info)
        assert isinstance(result, bytes)
        assert len(result) > 5_000

    def test_no_bess_does_not_crash(
        self, mock_sizing_result_no_bess, sample_header, sample_proposal_info
    ):
        """BESS=None should produce a valid document without BESS row."""
        result = generate_proposal_docx(
            mock_sizing_result_no_bess, sample_header, sample_proposal_info
        )
        assert isinstance(result, bytes)
        xml = _get_document_xml(result)
        assert "CAT G3520H" in xml  # document still has generator info

    def test_special_characters_in_project_name(
        self, mock_sizing_result, sample_proposal_info
    ):
        """Project names with special chars should not break XML generation."""
        header = {
            "project_name":   "Proyecto Ñoño & <Test> 'DC'",
            "client_name":    "Cliente & Co.",
            "contact_name":   "",
            "contact_email":  "",
            "contact_phone":  "",
            "country":        "Mexico",
            "state_province": "CDMX",
        }
        result = generate_proposal_docx(mock_sizing_result, header, sample_proposal_info)
        assert isinstance(result, bytes)
        buf = io.BytesIO(result)
        assert zipfile.is_zipfile(buf), "Special characters broke DOCX ZIP structure"

    def test_payment_terms_non_100_does_not_crash(
        self, mock_sizing_result, sample_header
    ):
        """Unbalanced payment terms should still produce a valid document."""
        info = dict(PROPOSAL_DEFAULTS)
        info["payment_pct_down"] = 50
        info["payment_pct_30d"] = 50
        info["payment_pct_sol"] = 0
        info["payment_pct_rts"] = 0
        result = generate_proposal_docx(mock_sizing_result, sample_header, info)
        assert isinstance(result, bytes)

    def test_additional_options_populated(
        self, mock_sizing_result, sample_header, sample_proposal_info
    ):
        """Additional options list should appear in the document."""
        info = dict(sample_proposal_info)
        info["additional_options"] = [
            {"description": "Acoustic enclosure upgrade", "price_usd": 25000.0},
            {"description": "Remote monitoring package", "price_usd": 15000.0},
        ]
        result = generate_proposal_docx(mock_sizing_result, sample_header, info)
        xml = _get_document_xml(result)
        assert "Acoustic enclosure" in xml or "acoustic enclosure" in xml.lower()

    def test_switchgear_offer_type(self, mock_sizing_result, sample_header, sample_proposal_info):
        """When switchgear=True, document should reflect it."""
        info = dict(sample_proposal_info)
        info["offer_type_switchgear"] = True
        result = generate_proposal_docx(mock_sizing_result, sample_header, info)
        assert isinstance(result, bytes)

    def test_empty_country_does_not_crash(self, mock_sizing_result, sample_proposal_info):
        """Missing location fields should not crash — fallback to empty string."""
        header = {
            "project_name":   "No Location Project",
            "client_name":    "Test Client",
            "contact_name":   "",
            "contact_email":  "",
            "contact_phone":  "",
            "country":        "",
            "state_province": "",
        }
        result = generate_proposal_docx(mock_sizing_result, header, sample_proposal_info)
        assert isinstance(result, bytes)
