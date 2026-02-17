"""
CAT Power Solution — PDF Report Generator
===========================================
Generates comprehensive sizing reports using ReportLab.

NO UI dependencies — accepts a data dict, returns PDF bytes.
Can be called from Streamlit, FastAPI, or CLI.
"""

from io import BytesIO
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY


# ==============================================================================
# STYLES
# ==============================================================================

def _build_styles():
    """Create the report stylesheet."""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name='ReportTitle',
        parent=styles['Title'],
        fontSize=22,
        textColor=HexColor('#1a1a2e'),
        spaceAfter=15,
        alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name='SectionHeader',
        parent=styles['Heading1'],
        fontSize=13,
        textColor=HexColor('#FFFFFF'),
        spaceBefore=15,
        spaceAfter=8,
        backColor=HexColor('#1a1a2e'),
        borderPadding=6,
    ))
    styles.add(ParagraphStyle(
        name='SubSection',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=HexColor('#333333'),
        spaceBefore=12,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name='CustomBody',
        parent=styles['Normal'],
        fontSize=9,
        textColor=HexColor('#333333'),
        spaceAfter=6,
        alignment=TA_JUSTIFY,
    ))
    return styles


def _standard_table_style():
    """Return the base table style used throughout the report."""
    return TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1a1a2e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f8f8')]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
    ])


# ==============================================================================
# MAIN REPORT GENERATOR
# ==============================================================================

def generate_comprehensive_pdf(data: dict) -> bytes:
    """
    Generate a complete PDF sizing report.

    Parameters
    ----------
    data : dict
        All results needed for the report.  Expected keys:

        Project header:
            project_name, dc_type, region, app_version

        Load:
            p_it, pue, p_total_dc, p_total_avg, p_total_peak,
            capacity_factor, avail_req, load_step_pct, spinning_res_pct

        Generator:
            selected_gen, gen_data (dict), unit_site_cap, derate_factor

        Fleet:
            n_running, n_reserve, n_total, installed_cap,
            load_per_unit_pct, fleet_efficiency, prob_gen, target_met

        Spinning:
            selected_config (dict with spinning_reserve_mw,
            spinning_from_gens, spinning_from_bess, headroom_mw)

        Reliability:
            reliability_configs (list of dicts, optional)

        BESS:
            use_bess, bess_strategy, bess_power_total, bess_energy_total,
            bess_breakdown (dict)

        Electrical:
            rec_voltage_kv, freq_hz, stability_ok, voltage_sag,
            net_efficiency, heat_rate_hhv_mj

        Footprint:
            area_gen, area_bess, total_area_m2

        Environmental:
            nox_lb_hr, co_lb_hr, co2_ton_yr, carbon_cost_year,
            include_chp, cooling_method, pue_actual

        Financial:
            initial_capex_sum, lcoe, fuel_cost_year, om_cost_year,
            annual_savings, npv, payback_str, wacc, project_years,
            total_gas_price, benchmark_price, breakeven_gas_price,
            capex_items (list of (item_name, cost_m_usd))

    Returns
    -------
    bytes
        PDF file content.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )

    styles = _build_styles()
    ts = _standard_table_style()
    story = []

    # Convenience accessors with safe defaults
    def g(key, default=""):
        return data.get(key, default)

    gen_data = g("gen_data", {})

    # =====================================================================
    # COVER PAGE
    # =====================================================================
    story.append(Spacer(1, 1 * inch))
    story.append(Paragraph("⚡ CAT POWER SOLUTION", styles['ReportTitle']))
    story.append(Paragraph("Comprehensive Power System Sizing Report", styles['Heading2']))
    story.append(Spacer(1, 0.4 * inch))

    cover_data = [
        ['Project:', g('project_name', 'Untitled')],
        ['Data Center Type:', g('dc_type')],
        ['Report Date:', datetime.now().strftime("%B %d, %Y")],
        ['Region:', g('region')],
        ['Generated By:', f"CAT Power Solution v{g('app_version', '3.1')}"],
    ]
    cover_table = Table(cover_data, colWidths=[1.8 * inch, 4.2 * inch])
    cover_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(cover_table)
    story.append(Spacer(1, 0.5 * inch))

    # Executive summary
    use_bess = g('use_bess', False)
    bess_text = ""
    if use_bess:
        bess_text = (
            f'<br/><br/>Includes <b>{g("bess_power_total", 0):.1f} MW / '
            f'{g("bess_energy_total", 0):.1f} MWh</b> BESS for transient support.'
        )

    summary_text = f"""
    <b>Executive Summary:</b><br/><br/>
    This report presents the power system sizing for a <b>{g('p_it', 0):.0f} MW</b> IT load
    data center with <b>PUE {g('pue', 1.2):.2f}</b>. The recommended solution:
    <b>{g('n_total', 0)} x {g('selected_gen', 'N/A')}</b> in
    <b>N+{g('n_reserve', 0)}</b> configuration achieving
    <b>{g('prob_gen', 0) * 100:.3f}%</b> availability.{bess_text}
    <br/><br/>
    <b>Key Metrics:</b> LCOE ${g('lcoe', 0):.4f}/kWh |
    CAPEX ${g('initial_capex_sum', 0):.1f}M | Payback {g('payback_str', 'N/A')}
    """
    story.append(Paragraph(summary_text, styles['CustomBody']))
    story.append(PageBreak())

    # =====================================================================
    # 1. LOAD REQUIREMENTS
    # =====================================================================
    story.append(Paragraph("1. LOAD REQUIREMENTS", styles['SectionHeader']))
    load_data = [
        ['Parameter', 'Value', 'Unit'],
        ['Critical IT Load', f'{g("p_it", 0):.1f}', 'MW'],
        ['Power Usage Effectiveness (PUE)', f'{g("pue", 1.2):.2f}', '-'],
        ['Total DC Load (Design)', f'{g("p_total_dc", 0):.1f}', 'MW'],
        ['Average Operating Load', f'{g("p_total_avg", 0):.1f}', 'MW'],
        ['Peak Load', f'{g("p_total_peak", 0):.1f}', 'MW'],
        ['Capacity Factor', f'{g("capacity_factor", 0.9) * 100:.1f}', '%'],
        ['Required Availability', f'{g("avail_req", 99.99):.4f}', '%'],
        ['Step Load Requirement', f'{g("load_step_pct", 0):.0f}', '%'],
        ['Spinning Reserve Policy', f'{g("spinning_res_pct", 0):.0f}', '%'],
    ]
    t = Table(load_data, colWidths=[2.8 * inch, 2 * inch, 1.5 * inch])
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 0.25 * inch))

    # =====================================================================
    # 2. GENERATOR SELECTION
    # =====================================================================
    story.append(Paragraph("2. GENERATOR SELECTION", styles['SectionHeader']))
    gen_table_data = [
        ['Specification', 'Value'],
        ['Model', g('selected_gen')],
        ['Type', gen_data.get('type', 'N/A')],
        ['ISO Rating', f"{gen_data.get('iso_rating_mw', 0):.2f} MW"],
        ['Site Rating (Derated)', f"{g('unit_site_cap', 0):.2f} MW"],
        ['Derate Factor', f"{g('derate_factor', 1.0) * 100:.1f}%"],
        ['Electrical Efficiency', f"{gen_data.get('electrical_efficiency', 0) * 100:.1f}%"],
        ['Heat Rate (LHV)', f"{gen_data.get('heat_rate_lhv', 0):,.0f} BTU/kWh"],
        ['Step Load Capability', f"{gen_data.get('step_load_pct', 0):.0f}%"],
        ['Ramp Rate', f"{gen_data.get('ramp_rate_mw_s', 0):.1f} MW/s"],
        ['MTBF', f"{gen_data.get('mtbf_hours', 0):,} hours"],
    ]
    t = Table(gen_table_data, colWidths=[3 * inch, 3.3 * inch])
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 0.25 * inch))

    # =====================================================================
    # 3. FLEET CONFIGURATION
    # =====================================================================
    story.append(Paragraph("3. FLEET CONFIGURATION", styles['SectionHeader']))
    target_met = g('target_met', False)
    fleet_data = [
        ['Parameter', 'Value'],
        ['Running Units (N)', f'{g("n_running", 0)}'],
        ['Reserve Units (+X)', f'{g("n_reserve", 0)}'],
        ['Total Fleet', f'{g("n_total", 0)}'],
        ['Installed Capacity', f'{g("installed_cap", 0):.1f} MW'],
        ['Load per Unit', f'{g("load_per_unit_pct", 0):.1f}%'],
        ['Fleet Efficiency', f'{g("fleet_efficiency", 0) * 100:.2f}%'],
        ['Configuration', f'N+{g("n_reserve", 0)}'],
        ['Achieved Availability', f'{g("prob_gen", 0) * 100:.4f}%'],
        ['Target Met', 'YES ✓' if target_met else 'NO ✗'],
    ]
    t = Table(fleet_data, colWidths=[3 * inch, 3.3 * inch])
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 0.25 * inch))

    # =====================================================================
    # 4. SPINNING RESERVE
    # =====================================================================
    story.append(Paragraph("4. SPINNING RESERVE ANALYSIS", styles['SectionHeader']))
    sc = g('selected_config', {})
    spin_data = [
        ['Parameter', 'Value', 'Notes'],
        ['Spinning Reserve Required',
         f"{sc.get('spinning_reserve_mw', 0):.1f} MW",
         f"{g('spinning_res_pct', 0):.0f}% of avg load"],
        ['From Generators (Headroom)',
         f"{sc.get('spinning_from_gens', 0):.1f} MW",
         'Running units headroom'],
        ['From BESS',
         f"{sc.get('spinning_from_bess', 0):.1f} MW" if use_bess else 'N/A',
         'Instant response'],
        ['Available Headroom',
         f"{sc.get('headroom_mw', 0):.1f} MW",
         'Total spare capacity'],
    ]
    t = Table(spin_data, colWidths=[2.3 * inch, 1.8 * inch, 2.2 * inch])
    t.setStyle(ts)
    story.append(t)
    story.append(PageBreak())

    # =====================================================================
    # 5. CONFIGURATION COMPARISON (optional)
    # =====================================================================
    reliability_configs = g('reliability_configs', [])
    if len(reliability_configs) > 1:
        story.append(Paragraph("5. CONFIGURATION COMPARISON", styles['SectionHeader']))
        config_header = ['Configuration', 'Fleet', 'BESS (MW/MWh)',
                         'Load/Unit', 'Efficiency', 'Availability']
        config_rows = [config_header]
        for cfg in reliability_configs:
            bess_str = (f"{cfg.get('bess_mw', 0):.0f}/{cfg.get('bess_mwh', 0):.0f}"
                        if cfg.get('bess_mw', 0) > 0 else "None")
            config_rows.append([
                cfg.get('name', 'N/A'),
                f"{cfg.get('n_running', 0)}+{cfg.get('n_reserve', 0)}",
                bess_str,
                f"{cfg.get('load_pct', 0):.1f}%",
                f"{cfg.get('efficiency', 0) * 100:.1f}%",
                f"{cfg.get('availability', 0) * 100:.3f}%",
            ])
        t = Table(config_rows,
                  colWidths=[1.4 * inch, 0.7 * inch, 1 * inch,
                             0.9 * inch, 0.9 * inch, 1 * inch])
        t.setStyle(ts)
        story.append(t)
        story.append(Spacer(1, 0.25 * inch))

    # =====================================================================
    # 6. BESS SYSTEM
    # =====================================================================
    if use_bess:
        story.append(Paragraph("6. BESS SYSTEM", styles['SectionHeader']))
        bpt = g('bess_power_total', 0)
        bet = g('bess_energy_total', 0)
        bb = g('bess_breakdown', {})
        bess_data = [
            ['Parameter', 'Value'],
            ['Strategy', g('bess_strategy', 'N/A')],
            ['Power Capacity', f'{bpt:.1f} MW'],
            ['Energy Capacity', f'{bet:.1f} MWh'],
            ['Duration', f'{bet / bpt:.1f} hours' if bpt > 0 else 'N/A'],
            ['Step Load Support', f"{bb.get('step_support', 0):.1f} MW"],
            ['Peak Shaving', f"{bb.get('peak_shaving', 0):.1f} MW"],
            ['Spinning Reserve', f"{bb.get('spinning_reserve', 0):.1f} MW"],
        ]
        t = Table(bess_data, colWidths=[3 * inch, 3.3 * inch])
        t.setStyle(ts)
        story.append(t)
        story.append(Spacer(1, 0.25 * inch))

    # =====================================================================
    # 7. ELECTRICAL PERFORMANCE
    # =====================================================================
    story.append(Paragraph("7. ELECTRICAL PERFORMANCE", styles['SectionHeader']))
    elec_data = [
        ['Parameter', 'Value'],
        ['Connection Voltage', f'{g("rec_voltage_kv", 13.8)} kV'],
        ['System Frequency', f'{g("freq_hz", 60)} Hz'],
        ['Transient Stability', 'PASS ✓' if g('stability_ok', True) else 'FAIL ✗'],
        ['Voltage Sag', f'{g("voltage_sag", 0):.2f}% (Limit: 10%)'],
        ['Net Efficiency', f'{g("net_efficiency", 0) * 100:.2f}%'],
        ['Heat Rate (HHV)', f'{g("heat_rate_hhv_mj", 0):.2f} MJ/kWh'],
    ]
    t = Table(elec_data, colWidths=[3 * inch, 3.3 * inch])
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 0.25 * inch))

    # =====================================================================
    # 8. FOOTPRINT
    # =====================================================================
    story.append(Paragraph("8. FOOTPRINT & INFRASTRUCTURE", styles['SectionHeader']))
    area_gen = g('area_gen', 0)
    area_bess = g('area_bess', 0)
    total_area = g('total_area_m2', 0)
    foot_data = [
        ['Component', 'Area (m²)', 'Area (Acres)'],
        ['Generators', f'{area_gen:,.0f}', f'{area_gen * 0.000247105:.2f}'],
        ['BESS',
         f'{area_bess:,.0f}' if use_bess else 'N/A',
         f'{area_bess * 0.000247105:.2f}' if use_bess else 'N/A'],
        ['Total Site', f'{total_area:,.0f}', f'{total_area * 0.000247105:.2f}'],
    ]
    t = Table(foot_data, colWidths=[2.3 * inch, 2 * inch, 2 * inch])
    t.setStyle(ts)
    story.append(t)
    story.append(PageBreak())

    # =====================================================================
    # 9. ENVIRONMENTAL
    # =====================================================================
    story.append(Paragraph("9. ENVIRONMENTAL PERFORMANCE", styles['SectionHeader']))
    env_data = [
        ['Parameter', 'Value', 'Unit'],
        ['NOx Emissions', f'{g("nox_lb_hr", 0):.2f}', 'lb/hr'],
        ['CO Emissions', f'{g("co_lb_hr", 0):.2f}', 'lb/hr'],
        ['CO2 Emissions (Annual)', f'{g("co2_ton_yr", 0):,.0f}', 'tons/yr'],
        ['Carbon Cost', f'${g("carbon_cost_year", 0) / 1e6:.2f}M', '/year'],
        ['Cooling Method',
         'Tri-Gen (CHP)' if g('include_chp', False) else g('cooling_method', 'Air-Cooled'),
         '-'],
        ['Actual PUE', f'{g("pue_actual", 0):.2f}', '-'],
    ]
    t = Table(env_data, colWidths=[2.5 * inch, 2 * inch, 1.8 * inch])
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 0.25 * inch))

    # =====================================================================
    # 10. FINANCIAL ANALYSIS
    # =====================================================================
    story.append(Paragraph("10. FINANCIAL ANALYSIS", styles['SectionHeader']))
    fin_data = [
        ['Metric', 'Value'],
        ['Total CAPEX', f'${g("initial_capex_sum", 0):.2f}M'],
        ['LCOE', f'${g("lcoe", 0):.4f}/kWh'],
        ['Annual Fuel Cost', f'${g("fuel_cost_year", 0) / 1e6:.2f}M'],
        ['Annual O&M Cost', f'${g("om_cost_year", 0) / 1e6:.2f}M'],
        ['Annual Savings vs Grid', f'${g("annual_savings", 0) / 1e6:.2f}M'],
        ['NPV (Project Life)', f'${g("npv", 0) / 1e6:.2f}M'],
        ['Simple Payback', g('payback_str', 'N/A')],
        ['WACC', f'{g("wacc", 0.08) * 100:.1f}%'],
        ['Project Life', f'{g("project_years", 20)} years'],
        ['Gas Price', f'${g("total_gas_price", 0):.2f}/MMBtu'],
        ['Benchmark Electricity', f'${g("benchmark_price", 0):.3f}/kWh'],
    ]
    t = Table(fin_data, colWidths=[3 * inch, 3.3 * inch])
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 0.25 * inch))

    if g('breakeven_gas_price', 0) > 0:
        story.append(Paragraph(
            f"<b>Breakeven Gas Price:</b> ${g('breakeven_gas_price'):.2f}/MMBtu",
            styles['CustomBody'],
        ))
    story.append(PageBreak())

    # =====================================================================
    # 11. CAPEX BREAKDOWN
    # =====================================================================
    story.append(Paragraph("11. CAPEX BREAKDOWN", styles['SectionHeader']))
    capex_items = g('capex_items', [])
    capex_rows = [['Item', 'Cost (M USD)']]
    for item_name, cost_val in capex_items:
        capex_rows.append([item_name, f"${cost_val:.2f}M"])
    capex_rows.append(['TOTAL', f"${g('initial_capex_sum', 0):.2f}M"])

    t = Table(capex_rows, colWidths=[4 * inch, 2.3 * inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1a1a2e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), HexColor('#e8e8e8')),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [white, HexColor('#f8f8f8')]),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.4 * inch))

    # =====================================================================
    # DISCLAIMER
    # =====================================================================
    story.append(Paragraph("NOTES & DISCLAIMER", styles['SectionHeader']))
    disclaimer_text = """
    <b>Important Notes:</b><br/>
    1. This analysis is preliminary and for planning purposes only.<br/>
    2. Actual equipment selection requires detailed engineering studies.<br/>
    3. Site conditions may affect performance.<br/>
    4. Financial projections based on current market assumptions.<br/><br/>

    <b>Disclaimer:</b> This report is provided for informational purposes only.
    Final system design should be validated by qualified engineers.
    Caterpillar Inc. makes no warranties regarding accuracy or completeness.
    """
    story.append(Paragraph(disclaimer_text, styles['CustomBody']))

    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
