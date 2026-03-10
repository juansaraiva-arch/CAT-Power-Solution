# CAT QuickSize v3.1 — Detailed Technical Manual

**Prime Power Sizing Tool for Data Centers**

---

**Version:** 3.1
**Platform:** Streamlit + FastAPI + React
**URL:** https://quick-size-solution.streamlit.app
**Calculation Engine:** 14 functions, 23-step sizing pipeline
**Generator Library:** 8 CAT generator models
**Input Variables:** 76 parameters across 4 categories
**Output Variables:** 55+ result fields
**Author:** Francisco Saraiva
**Date:** 2025

---

## Table of Contents

1. Application Overview
2. Input Variables — 76 Parameters
3. Generator Library — 8 CAT Models
4. Calculation Methodologies — 14 Engine Functions
5. Sizing Pipeline — 23 Steps
6. Output Variables — 55+ Fields
7. Predefined Templates — 4 Presets
8. Regional Multipliers & O&M Costs
9. Emissions Compliance Matrix — 5 Jurisdictions
10. Technical Summary

---

## 1. Application Overview

**CAT QuickSize** is an engineering tool for sizing prime power generation solutions for data centers. It calculates the optimal fleet of CAT natural gas generators, Battery Energy Storage Systems (BESS), emissions controls, and full financial analysis.

### Architecture

| Component | Technology | Description |
|---|---|---|
| Pilot UI | Streamlit | Interactive web interface |
| REST API | FastAPI (Python 3.11) | 8 routers, sizing endpoints |
| Web Frontend | React + TypeScript | Modern BDM interface |
| Calculation Engine | core/engine.py | 14 stateless functions (897 lines) |
| Library | core/generator_library.py | 8 generators, ~20 specs each |
| Pipeline | sizing_pipeline.py | 23 sequential steps (830 lines) |

### Flow

The user enters load parameters, site conditions, technology choices, and economic inputs. The pipeline executes 23 sequential steps producing: optimal fleet, BESS, electrical stability, emissions, physical footprint, and financial analysis with LCOE, NPV, and payback.

> **Note:** All engine functions are *stateless*: inputs in, pure outputs out.

---

## 2. Input Variables — 76 Parameters

### 2.1 Load Profile

| Variable | Key | Default | Range | Unit | Description |
|---|---|---|---|---|---|
| IT Load | p_it | 100.0 | 0.1-2000 | MW | Data center IT load (before PUE) |
| PUE | pue | 1.20 | 1.0-3.0 | ratio | Power Usage Effectiveness |
| Capacity Factor | capacity_factor | 0.90 | 0.01-1.0 | ratio | Annual average capacity factor |
| Peak/Avg Ratio | peak_avg_ratio | 1.15 | 1.0-2.0 | ratio | Peak to average load ratio |
| Load Step | load_step_pct | 40.0 | 0-100 | % | Maximum instantaneous load change |
| Spinning Reserve | spinning_res_pct | 20.0 | 0-100 | % | Required spinning reserve |
| Availability | avail_req | 99.99 | 90-100 | % | Availability target (Tier IV) |
| Load Ramp Rate | load_ramp_req | 3.0 | >0 | MW/min | Maximum load change rate |
| DC Type | dc_type | AI Factory | selection | — | Data center type |

### 2.2 Site Conditions

| Variable | Key | Default | Range | Unit | Description |
|---|---|---|---|---|---|
| Derate Mode | derate_mode | Auto-Calculate | — | — | Auto or Manual |
| Site Temperature | site_temp_c | 35.0 | -40 to 60 | C | Ambient temp. Derating >40C |
| Site Altitude | site_alt_m | 100.0 | 0-5000 | m | Altitude. Derating >300m |
| Methane Number | methane_number | 80 | 0-100 | MN | Gas quality. Derating <80 |
| Manual Derate | derate_factor_manual | 0.90 | 0.01-1.0 | ratio | Direct manual factor |

### 2.3 Technology

| Variable | Key | Default | Description |
|---|---|---|---|
| Generator Model | generator_model | G3516H | Generator model (8 options) |
| Gen Overrides | gen_overrides | null | Parameter override dictionary |
| Use BESS | use_bess | true | Include BESS |
| BESS Strategy | bess_strategy | Hybrid (Balanced) | Transient Only / Hybrid / Reliability Priority |
| Black Start | enable_black_start | true | BESS for black start |
| Cooling | cooling_method | Air-Cooled | Air-Cooled or Water-Cooled |
| Frequency | freq_hz | 60 | 50 or 60 Hz |
| Distribution Loss | dist_loss_pct | 1.5% | Distribution losses |
| Voltage Mode | volt_mode | Auto-Recommend | Auto or Manual |
| Manual Voltage | manual_voltage_kv | 13.8 | Manual kV |

### 2.4 Economics

| Variable | Key | Default | Unit | Description |
|---|---|---|---|---|
| Gas Price | gas_price | 3.50 | $/MMBtu | Natural gas price |
| WACC | wacc | 8.0 | % | Cost of capital |
| Project Years | project_years | 20 | years | Project horizon |
| Benchmark Price | benchmark_price | 0.12 | $/kWh | Grid reference price |
| Carbon Price | carbon_price_per_ton | 0.0 | $/ton | Carbon tax |
| MACRS | enable_depreciation | true | — | Accelerated depreciation |
| BESS Cost (kW) | bess_cost_kw | 250 | $/kW | BESS inverter cost |
| BESS Cost (kWh) | bess_cost_kwh | 400 | $/kWh | BESS battery cost |
| BESS O&M | bess_om_kw_yr | 5.0 | $/kW/yr | Annual BESS O&M |
| Gen Cost Mode | gen_cost_mode | budget_estimate | — | Estimate or BDM price |
| BDM Total Price | gen_total_price_bdm | 0.0 | USD | BDM total price |
| Force Emissions | force_emissions | false | — | Force aftertreatment |
| SCR Cost | cost_scr_kw | 75 | $/kW | SCR cost |
| OxiCat Cost | cost_oxicat_kw | 25 | $/kW | Oxidation catalyst cost |
| Fuel Mode | fuel_mode | Pipeline Gas | — | Pipeline / LNG / Dual-Fuel |
| LNG Days | lng_days | 5 | days | LNG autonomy |
| CHP | include_chp | false | — | Trigeneration (+20% CAPEX) |
| Max Area | max_area_m2 | 10000 | m2 | Maximum plant area |
| Region | region | US - Gulf Coast | — | 15 regions for costs |

---

## 3. Generator Library — 8 CAT Models

### Primary Specifications

| Model | Type | ISO (MW) | Efficiency | Heat Rate | Step Load | Ramp (MW/s) | MTBF (h) |
|---|---|---|---|---|---|---|---|
| XGC1900 | High Speed | 1.90 | 39.2% | 8,780 | 25% | 0.5 | 50,000 |
| G3520FR | High Speed | 2.50 | 38.6% | 8,836 | 40% | 0.6 | 48,000 |
| G3520K | High Speed | 2.50 | 45.3% | 7,638 | 15% | 0.4 | 52,000 |
| G3516H | High Speed | 2.50 | 44.1% | 7,740 | 25% | 0.5 | 50,000 |
| CG260-16 | High Speed | 3.96 | 43.4% | 7,860 | 10% | 0.45 | 55,000 |
| C175-20 | High Speed | 4.00 | 42.0% | 8,120 | 20% | 0.5 | 50,000 |
| Titan 130 | Gas Turbine | 16.50 | 35.4% | 9,630 | 15% | 2.0 | 80,000 |
| G20CM34 | Medium Speed | 9.76 | 47.5% | 7,480 | 10% | 0.3 | 60,000 |

### Emissions & Costs

| Model | NOx (g/kWh) | CO (g/kWh) | Cost ($/kW) | Install ($/kW) | Maint Int (h) | Maint Dur (h) |
|---|---|---|---|---|---|---|
| XGC1900 | 0.50 | 2.50 | 775 | 300 | 1,000 | 48 |
| G3520FR | 0.50 | 2.10 | 575 | 650 | 1,000 | 48 |
| G3520K | 0.30 | 2.30 | 575 | 650 | 1,000 | 48 |
| G3516H | 0.50 | 2.00 | 550 | 600 | 1,000 | 48 |
| CG260-16 | 0.50 | 1.80 | 675 | 1,100 | 1,000 | 48 |
| C175-20 | 0.50 | 1.50 | 625 | 900 | 1,000 | 56 |
| Titan 130 | 0.60 | 0.60 | 775 | 1,000 | 8,000 | 120 |
| G20CM34 | 0.50 | 0.50 | 700 | 1,250 | 2,500 | 72 |

### Electrical Parameters

| Model | Power Density (MW/m2) | Gas Pressure (psi) | Reactance X"d (p.u.) | Inertia H (s) |
|---|---|---|---|---|
| XGC1900 | 0.010 | 1.5 | 0.14 | 1.0 |
| G3520FR | 0.010 | 1.5 | 0.14 | 1.5 |
| G3520K | 0.010 | 1.5 | 0.13 | 1.2 |
| G3516H | 0.010 | 1.5 | 0.14 | 1.2 |
| CG260-16 | 0.009 | 7.25 | 0.15 | 1.3 |
| C175-20 | 0.009 | 3.0 | 0.15 | 1.4 |
| Titan 130 | 0.020 | 300 | 0.18 | 5.0 |
| G20CM34 | 0.008 | 90 | 0.16 | 2.5 |

> **GERP Parser:** Includes `parse_gerp_pdf()` function to import specs from CAT performance PDF reports.

---

## 4. Calculation Methodologies — 14 Functions

### 4.1 Part-Load Efficiency `get_part_load_efficiency()`

Linear interpolation against CAT curves by generator type.

**Curves (factor over base efficiency):**

| Load % | High Speed | Medium Speed | Gas Turbine |
|---|---|---|---|
| 0% | 0.00 | 0.00 | 0.00 |
| 25% | 0.70 | 0.75 | 0.55 |
| 50% | 0.88 | 0.91 | 0.78 |
| 75% | 0.96 | 0.97 | 0.90 |
| 100% | 1.00 | 1.00 | 1.00 |

```
factor = np.interp(load_pct, xp, fp)
efficiency = base_eff * factor
```

### 4.2 Transient Stability `transient_stability_check()`

Voltage sag check for AI workloads.

```
equiv_xd = xd_pu / sqrt(num_units)
voltage_sag = (step_load_pct / 100) * equiv_xd * 100
PASS if voltage_sag <= 10%
```

### 4.3 Frequency Screening `frequency_screening()`

Simplified swing equation for nadir and ROCOF.

```
Constants: R=0.05 (droop), D=2.0 (damping), T_gov=0.5s, pf=0.85

S_total_mva = n_running * (unit_cap_mw / pf)
H_total = H_mech + H_bess  (H_bess = 4.0 * min(1, bess_ratio/0.2))

ROCOF = (P_step_pu * freq_hz) / (2 * H_total)
df_ss = (P_step_pu / (D + 1/R)) * freq_hz
overshoot = 1.0 + sqrt(T_gov / (4 * H_total))
df_nadir = df_ss * overshoot
nadir_hz = freq_hz - df_nadir

Criteria: nadir >= 59.5 Hz (60 Hz), ROCOF <= 1.0 Hz/s
```

### 4.4 Spinning Reserve `calculate_spinning_reserve_units()`

```
spinning_reserve_mw = p_avg * (spinning_res_pct / 100)

WITHOUT BESS:  required_cap = p_avg + spinning_from_gens
WITH BESS (>90% coverage): required_cap = p_avg * 1.05

n_running = ceil(required_cap / unit_capacity)
```

### 4.5 BESS Sizing `calculate_bess_requirements()`

6 independent components:

1. **Step Load Support:** max(0, step_load_mw - gen_step_mw)
2. **Peak Shaving:** p_peak - p_avg
3. **Ramp Rate Support:** max(0, (load_ramp_req - gen_ramp) * 10)
4. **Frequency Regulation:** p_avg * 0.05
5. **Black Start:** p_peak * 0.05 (if enabled)
6. **Spinning Reserve:** p_avg * (step_load_pct / 100)

```
bess_power = max(comp1..6, p_peak * 0.15)  # floor at 15% of peak
bess_energy = bess_power / 1.0 / 0.85      # C-rate=1, DoD=85%
```

### 4.6 BESS Reliability Credit `calculate_bess_reliability_credit()`

```
realistic_coverage = 2.0 hours
power_credit = bess_power / unit_cap
energy_credit = bess_energy / (unit_cap * 2.0)
raw_credit = min(power_credit, energy_credit)
effective = raw_credit * 0.98 (availability) * 0.70 (coverage)
```

### 4.7 Availability (Weibull/Binomial N+X) `calculate_availability_weibull()`

```
annual_maint = (8760 / maint_interval) * maint_duration
A_unit = MTBF / (MTBF + MTTR + annual_maint)

A_system = Sum(k=N_run to N_total) C(N_total,k) * A^k * (1-A)^(N-k)

Aging: aging(year) = max(0.95, 1.0 - year * 0.001)
```

### 4.8 Fleet Optimization `optimize_fleet_size()`

Optimal load point: 72.5%. Multi-objective score:

```
load_penalty = |load_pct - 72.5| / 100
score = efficiency * (1 - load_penalty * 0.5)
Selects n with highest score (30-95% load range)
```

### 4.9 MACRS Depreciation `calculate_macrs_depreciation()`

```
Schedule: [20%, 32%, 19.2%, 11.52%, 11.52%, 5.76%]
Tax rate: 21%
PV_benefit = Sum(CAPEX * rate * tax_rate / (1+WACC)^yr)
```

### 4.10 Noise Propagation (3 functions)

```
Combined:  L_total = (L_source - attenuation) + 10*log10(N)
Distance:  L_rx = L_src - 20*log10(d) - 11
Setback:   d_min = 10^((L_combined - L_limit - 11) / 20)
```

### 4.11 Site Derating `calculate_site_derate()`

```
temp_derate = 1 - ((T-40)/5.5)*0.01     if T>40C
alt_derate  = 1 - ((alt-300)/300)*0.035  if alt>300m
fuel_derate = 1 - ((80-MN)/100)*0.15     if MN<80

derate = max(0.50, temp * alt * fuel)
```

### 4.12 Emissions `calculate_emissions()`

```
NOx_lb_hr = p_avg_kw * (NOx_g_kwh / 1000)
NOx_tpy = (NOx_lb_hr * effective_hours) / 2000
CO2_tpy = fuel_mmbtu_hr * 0.0531 * 8760 * CF

Conversions: mg/Nm3 = g_kWh * 3.6 / 4.5
             ppmvd  = mg_Nm3 / factor (NOx:2.05, CO:1.25)

Aftertreatment: SCR if NOx>100tpy or >0.5 g/kWh (90% reduction)
                OxiCat if CO>100tpy or >2.0 g/kWh (85% reduction)

Urea: 20 L/MWh, 30-day storage, 275-gal totes, $0.50/gal
```

5 jurisdictions: US EPA NSPS, Title V, EU MCP, EU IED, CARB.

### 4.13 Footprint `calculate_footprint()`

| Component | Formula |
|---|---|
| Generators | N * unit_cap / power_density |
| BESS | energy_mwh * 40 m2/MWh |
| LNG | lng_gallons * 0.1 m2/gal |
| Cooling (Air) | heat_mw * 120 m2/MW |
| Cooling (Water) | heat_mw * 50 m2/MW |
| Substation | 500 + total_cap * 5 m2 |

### 4.14 LCOE/Financial `calculate_lcoe()`

```
CRF = (WACC * (1+WACC)^n) / ((1+WACC)^n - 1)
CAPEX_annual = total_capex * CRF
LCOE = (CAPEX_annual + OM + Fuel + Carbon) / MWh_annual
NPV = PV_savings + tax_benefits - capex - repowering
Payback = total_capex / annual_savings
```

---

## 5. Sizing Pipeline — 23 Steps

Function: `run_full_sizing(inputs: SizingInput) -> SizingResult`

1. **Resolve Generator** — Load generator from library + overrides
2. **Load Calculations** — p_dc = p_it * PUE, p_avg = p_dc * CF, p_peak, dist. losses
3. **Site Derating** — Auto-calculate or apply manual. unit_site_cap = iso * derate
4. **BESS Sizing** — 6 transient components if use_bess=true
5. **Spinning Reserve** — N units with headroom
6. **Fleet Optimization** — Optimal 72.5% load point
7. **Availability Target** — Convert % to decimal, MTTR=48h
8. **Reliability Configs A/B/C** — A: No BESS, B: BESS Transient, C: Hybrid/Reliability (5-8 gensets, 2-2.5h coverage, 0.65x credit)
9. **Select Configuration** — Based on bess_strategy
10. **Extract Final Values** — n_running, n_reserve, n_total, BESS breakdown
11. **Fleet Efficiency + Site Corrections** — Fuel quality (MN<70: x0.94, MN<80: x0.98), extreme altitude
12. **Voltage Recommendation** — <10MW:4.16kV, <50MW:13.8kV, >=50MW:34.5kV
13. **Transient Stability** — Voltage sag <= 10%
14. **Availability Curve** — Binomial N+X with aging
15. **Emissions** — NOx, CO, CO2, aftertreatment, urea, 5 regulations
16. **Footprint** — Area by component, LNG if applicable
17. **Net Efficiency** — fleet_eff * (1 - dist_loss%)
18. **Financial** — CAPEX, O&M, fuel, carbon, MACRS, BESS repowering (batt:10y, inv:15y), LCOE, NPV, payback
19. **CAPEX Breakdown** — gen, install, CHP, BESS, aftertreatment
20. **O&M Breakdown** — fixed, variable, labor, overhaul, BESS, AT, urea
21. **Gas Sensitivity** — 20 points, breakeven gas price
22. **Grid Comparison** — Cumulative grid vs CAT, crossover year
23. **Assemble Result** — SizingResult (55+ fields)

---

## 6. Output Variables — 55+ Fields

### Project
project_name, dc_type, region, app_version

### Load
p_it, pue, p_total_dc, p_total_avg, p_total_peak, capacity_factor, avail_req

### Generator
selected_gen, unit_iso_cap, unit_site_cap, derate_factor

### Fleet
n_running, n_reserve, n_total, installed_cap, load_per_unit_pct, fleet_efficiency

### Spinning Reserve
spinning_reserve_mw, spinning_from_gens, spinning_from_bess, headroom_mw

### Reliability
reliability_configs (list of up to 3), selected_config_name

### BESS
use_bess, bess_strategy, bess_power_mw, bess_energy_mwh, bess_breakdown (7 components)

### Electrical
rec_voltage_kv, freq_hz, stability_ok, voltage_sag, net_efficiency, system_availability, availability_over_time

### Emissions & Footprint
emissions (dict: NOx/CO/CO2 in 5 units, aftertreatment, urea, compliance 5 jurisdictions)
footprint (dict: gen, BESS, LNG, cooling, substation, total, power_density)

### Financial
lcoe ($/kWh), npv (USD), total_capex (USD), annual_fuel_cost, annual_om_cost, simple_payback_years, annual_savings, grid_annual_cost, breakeven_gas_price, capex_breakdown (5 categories), om_breakdown (7 categories), gas_sensitivity (20 points), grid_comparison (cumulative + crossover)

---

## 7. Predefined Templates

| Template | IT Load | PUE | CF | Peak/Avg | Step | Spin | Avail | Generator | BESS |
|---|---|---|---|---|---|---|---|---|---|
| Edge/Micro | 2 MW | 1.30 | 0.85 | 1.20 | 50% | 25% | 99.95% | XGC1900 | Transient Only |
| Enterprise | 20 MW | 1.25 | 0.85 | 1.20 | 40% | 20% | 99.99% | G3516H | Hybrid |
| Hyperscale | 100 MW | 1.18 | 0.90 | 1.15 | 30% | 15% | 99.995% | G20CM34 | Hybrid |
| AI Campus | 500 MW | 1.15 | 0.92 | 1.10 | 25% | 15% | 99.999% | G20CM34 | Reliability Priority |

---

## 8. Regional Multipliers

| Region | Multiplier |
|---|---|
| US - Gulf Coast | 1.00 (baseline) |
| US - Southeast | 1.02 |
| US - Midwest | 1.05 |
| Asia - East | 1.05 |
| US - Northeast | 1.10 |
| Africa | 1.10 |
| Canada | 1.12 |
| US - West Coast | 1.15 |
| Europe - South | 1.15 |
| Australia | 1.20 |
| Europe - West | 1.25 |
| Europe - North | 1.30 |
| Middle East | 0.95 |
| Latin America | 0.90 |
| Asia - Southeast | 0.85 |

### Scale Factors

| Capacity | Factor | Rationale |
|---|---|---|
| < 2.5 MW | 1.30 | No economies of scale |
| 2.5-10 MW | 1.15 | Small project |
| 10-50 MW | 1.05 | Medium |
| >= 50 MW | 1.00 | Full scale |

### Default O&M Costs

| Item | Value | Unit |
|---|---|---|
| Fixed O&M | $12.00 | $/kW/yr |
| Variable O&M | $5.00 | $/MWh |
| Labor per Unit | $50,000 | $/unit/yr |
| Overhaul | $40,000 | $/MW (every 60,000h) |

---

## 9. Emissions Compliance — 5 Jurisdictions

| Regulation | Region | NOx Limit | CO Limit | Scope |
|---|---|---|---|---|
| US EPA NSPS (JJJJ) | US | <= 1.5 g/kWh | <= 3.7 g/kWh | SI engines >500 hp |
| US EPA Title V | US | <= 100 tpy | <= 100 tpy | Total site emissions |
| EU MCP | EU | <= 95 mg/Nm3 | <= 500 mg/Nm3 | 1-50 MWth |
| EU IED (BAT-AEL) | EU | <= 75 mg/Nm3 | <= 100 mg/Nm3 | >50 MWth |
| CARB | California | <= 0.11 g/kWh | <= 0.45 g/kWh | Strictest US |

**Automatic aftertreatment:** SCR (90% NOx) if >100 tpy or >0.5 g/kWh. OxiCat (85% CO) if >100 tpy or >2.0 g/kWh.

---

## 10. Technical Summary

| Metric | Value |
|---|---|
| Version | 3.1 |
| Engine (engine.py) | 14 functions, 897 lines |
| Pipeline (sizing_pipeline.py) | 23 steps, 830 lines |
| Generators | 8 models, ~20 specs each |
| Input Variables | 76 parameters, 4 categories |
| Output Variables | 55+ fields (Pydantic) |
| Templates | 4 (Edge, Enterprise, Hyperscale, AI Campus) |
| Emissions Regulations | 5 jurisdictions |
| Regions | 15 multipliers |
| BESS Strategies | 3 |
| BESS Components | 6 independent |
| Reliability | Binomial N+X with Weibull aging |
| Depreciation | MACRS 5-year, 21% |
| Sensitivity | 20-point gas price sweep |
| Countries | 150+ |

---

*CAT QuickSize v3.1 — Detailed Technical Manual — 2025*
*Author: Francisco Saraiva — All rights reserved*
