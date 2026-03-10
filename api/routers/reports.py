"""
CAT Power Solution — Reports Router
=====================================
PDF report generation endpoints.
Supports two modes: 'executive' (1-page summary) and 'full' (comprehensive design report).
Requires 'full' role or higher.
"""

from io import BytesIO

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse

from api.auth import require_role, AuthenticatedUser
from api.schemas.sizing import SizingProjectInput
from api.services.sizing_pipeline import run_full_sizing
from core.pdf_report import generate_comprehensive_pdf, generate_executive_pdf

router = APIRouter()


@router.post("/pdf")
def generate_pdf(
    data: dict,
    mode: str = Query("full", enum=["executive", "full"]),
    user: AuthenticatedUser = Depends(require_role("full")),
):
    """
    Generate a PDF report from pre-calculated sizing data.

    The data dict must contain all keys expected by generate_comprehensive_pdf().
    Use this endpoint if you've already run the sizing pipeline separately.
    """
    try:
        if mode == "executive":
            pdf_bytes = generate_executive_pdf(data)
        else:
            pdf_bytes = generate_comprehensive_pdf(data)
        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=CAT_Power_Solution_{mode.title()}_Report.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation error: {str(e)}")


@router.post("/pdf-from-sizing")
def generate_pdf_from_sizing(
    req: SizingProjectInput,
    mode: str = Query("full", enum=["executive", "full"]),
    user: AuthenticatedUser = Depends(require_role("full")),
):
    """
    Run the full sizing pipeline, then generate a PDF report.

    This is a convenience endpoint that combines /sizing/full + /reports/pdf
    in a single request. Supports mode='executive' (1-page) or mode='full' (detailed).
    """
    try:
        result = run_full_sizing(req.inputs)

        # Build CAPEX items list from breakdown
        capex_items = []
        for key, val in result.capex_breakdown.items():
            label_map = {
                "generation_units": "Generation Units",
                "installation_bop": "Installation & BOP",
                "tri_gen_chp": "Tri-Gen / CHP",
                "bess_system": "BESS System",
                "aftertreatment": "Aftertreatment (SCR/OxiCat)",
            }
            if val > 0:
                capex_items.append({
                    "label": label_map.get(key, key.replace("_", " ").title()),
                    "value_m": val / 1e6,
                })

        # Build PDF data dict from sizing result — all data mapped correctly
        pdf_data = {
            "project_name": req.header.project_name if req.header else "",
            "client_name": req.header.client_name if req.header else "",
            "dc_type": result.dc_type,
            "region": result.region,
            "app_version": result.app_version,
            "p_it": result.p_it,
            "pue": result.pue,
            "p_total_dc": result.p_total_dc,
            "p_total_avg": result.p_total_avg,
            "p_total_peak": result.p_total_peak,
            "capacity_factor": result.capacity_factor,
            "avail_req": result.avail_req,
            "selected_gen": result.selected_gen,
            "gen_data": {},
            "unit_iso_cap": result.unit_iso_cap,
            "unit_site_cap": result.unit_site_cap,
            "derate_factor": result.derate_factor,
            "n_running": result.n_running,
            "n_reserve": result.n_reserve,
            "n_total": result.n_total,
            "installed_cap": result.installed_cap,
            "load_per_unit_pct": result.load_per_unit_pct,
            "fleet_efficiency": result.fleet_efficiency,
            "prob_gen": result.system_availability,
            "target_met": result.system_availability >= (result.avail_req / 100),
            "use_bess": result.use_bess,
            "bess_strategy": result.bess_strategy,
            "bess_power_total": result.bess_power_mw,
            "bess_energy_total": result.bess_energy_mwh,
            "bess_breakdown": result.bess_breakdown,
            "rec_voltage_kv": result.rec_voltage_kv,
            "freq_hz": result.freq_hz,
            "stability_ok": result.stability_ok,
            "voltage_sag": result.voltage_sag,
            "net_efficiency": result.net_efficiency,
            "area_gen": result.footprint.get("gen_area_m2", 0),
            "area_bess": result.footprint.get("bess_area_m2", 0),
            "total_area_m2": result.footprint.get("total_area_m2", 0),
            "nox_lb_hr": result.emissions.get("nox_lb_hr", 0),
            "co_lb_hr": result.emissions.get("co_lb_hr", 0),
            "co2_ton_yr": result.emissions.get("co2_tpy", 0),
            "carbon_cost_year": result.emissions.get("co2_tpy", 0) * req.inputs.carbon_price_per_ton,
            "include_chp": req.inputs.include_chp,
            "cooling_method": req.inputs.cooling_method,
            "pue_actual": result.pue,
            # Financial — total_capex is in raw dollars, convert to millions for PDF
            "initial_capex_sum": result.total_capex / 1e6,
            "lcoe": result.lcoe,
            "fuel_cost_year": result.annual_fuel_cost,
            "om_cost_year": result.annual_om_cost,
            "annual_savings": result.annual_savings,
            "npv": result.npv,
            "payback_str": f"{result.simple_payback_years:.1f} Years",
            # Fixed: Use actual WACC from inputs, not LCOE
            "wacc": req.inputs.wacc / 100,
            "project_years": req.inputs.project_years,
            "total_gas_price": req.inputs.gas_price,
            "benchmark_price": req.inputs.benchmark_price,
            "breakeven_gas_price": result.breakeven_gas_price,
            "capex_items": capex_items,
            "selected_config": {
                "spinning_reserve_mw": result.spinning_reserve_mw,
                "spinning_from_gens": result.spinning_from_gens,
                "spinning_from_bess": result.spinning_from_bess,
                "headroom_mw": result.headroom_mw,
            },
            # Extra data for executive summary
            "simple_payback_years": result.simple_payback_years,
            "annual_fuel_cost": result.annual_fuel_cost,
            "annual_om_cost": result.annual_om_cost,
            "grid_annual_cost": result.grid_annual_cost,
        }

        if mode == "executive":
            pdf_bytes = generate_executive_pdf(pdf_data)
            filename = "CAT_Power_Solution_Executive_Summary.pdf"
        else:
            pdf_bytes = generate_comprehensive_pdf(pdf_data)
            filename = "CAT_Power_Solution_Full_Report.pdf"

        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Generator not found: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation error: {str(e)}")
