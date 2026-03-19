"""
CAT Power Solution — Proposal Document Defaults
================================================
Commercial and administrative fields required to generate the customer proposal DOCX.
These are separate from sizing inputs and do not affect the calculation engine.
"""

# Proposal document version tracking
PROPOSAL_VERSION = "1.0"

# Default values for all commercial/administrative fields
PROPOSAL_DEFAULTS = {
    # --- Cover page ---
    "cat_division":         "LEPS Business Development",
    "proposal_type":        "Budgetary",          # Budgetary | Preliminary | Final
    "doc_version":          "Rev. 0",
    "bdm_name":             "",                    # Business Development Manager name
    "bdm_email":            "",

    # --- Commercial / Pricing ---
    "dealer_name":          "",
    "dealer_contact":       "",
    "incoterm":             "Ex Works (EXW)",
    "delivery_destination": "Ex Factory",          # Ex Factory | CAT Distribution Center | On-site | Port of Receivable Country
    "delivery_date_est":    "",                    # free text, e.g. "Q3 2026 (~18 months ARO)"
    "proposal_validity":    "90 days from date of issue",
    "payment_pct_down":     30,
    "payment_pct_30d":      30,
    "payment_pct_sol":      30,
    "payment_pct_rts":      10,

    # --- Offer scope ---
    "offer_type_genset":       True,
    "offer_type_switchgear":   False,
    "offer_type_solutions":    False,
    "offer_type_hybrid":       False,

    # --- Post-sale services ---
    "include_cva":          False,
    "include_esc":          False,

    # --- Additional options table (up to 5 rows) ---
    # Each entry: {"description": str, "price_usd": float}
    "additional_options":   [],

    # --- Clarifications / notes ---
    "proposal_notes":       "",    # Free text for §5 Clarifications section
}

# Dropdown choices for proposal_type
PROPOSAL_TYPE_OPTIONS = ["Budgetary", "Preliminary", "Final"]

# Dropdown choices for incoterm
INCOTERM_OPTIONS = [
    "Ex Works (EXW)",
    "Free Carrier (FCA)",
    "Free On Board (FOB)",
    "Cost and Freight (CFR)",
    "Cost Insurance Freight (CIF)",
    "Delivered Duty Paid (DDP)",
    "Delivered At Place (DAP)",
]

# Dropdown choices for delivery destination
DELIVERY_DESTINATION_OPTIONS = [
    "Ex Factory",
    "CAT Distribution Center",
    "On-site",
    "Port of Receivable Country",
]
