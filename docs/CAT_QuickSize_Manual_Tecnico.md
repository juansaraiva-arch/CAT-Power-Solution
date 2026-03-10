# CAT QuickSize v3.1 — Manual Tecnico Detallado

**Prime Power Sizing Tool for Data Centers**

---

**Version:** 3.1
**Plataforma:** Streamlit + FastAPI + React
**URL:** https://quick-size-solution.streamlit.app
**Motor de Calculo:** 14 funciones, 23 pasos de sizing
**Biblioteca:** 8 modelos de generadores CAT
**Variables de Entrada:** 76 parametros en 4 categorias
**Variables de Salida:** 55+ campos de resultado
**Autor:** Francisco Saraiva
**Fecha:** 2025

---

## Contenido

1. Descripcion General de la Aplicacion
2. Variables de Entrada — 76 Parametros
3. Biblioteca de Generadores — 8 Modelos CAT
4. Metodologias de Calculo — 14 Funciones del Motor
5. Pipeline de Sizing — 23 Pasos
6. Variables de Salida — 55+ Campos
7. Templates Predefinidos — 4 Presets
8. Multiplicadores Regionales y Costos O&M
9. Matriz de Cumplimiento de Emisiones — 5 Jurisdicciones
10. Resumen Tecnico

---

## 1. Descripcion General

**CAT QuickSize** es una herramienta de ingenieria para el dimensionamiento de soluciones de generacion de energia prime power para centros de datos. Calcula la flota optima de generadores de gas natural CAT, sistemas de almacenamiento de energia (BESS), controles de emisiones y analisis financiero completo.

### Arquitectura

| Componente | Tecnologia | Descripcion |
|---|---|---|
| UI Piloto | Streamlit | Interfaz web interactiva |
| API REST | FastAPI (Python 3.11) | 8 routers, endpoints para sizing |
| Frontend Web | React + TypeScript | Interfaz moderna para BDMs |
| Motor de Calculo | core/engine.py | 14 funciones stateless (897 lineas) |
| Biblioteca | core/generator_library.py | 8 generadores, ~20 specs cada uno |
| Pipeline | sizing_pipeline.py | 23 pasos secuenciales (830 lineas) |

### Flujo

El usuario ingresa parametros de carga, condiciones del sitio, tecnologia y economia. El pipeline ejecuta 23 pasos secuenciales que producen: flota optima, BESS, estabilidad electrica, emisiones, huella fisica, y analisis financiero con LCOE, NPV y payback.

> **Nota:** Todas las funciones del motor son *stateless*: reciben inputs y producen outputs puros.

---

## 2. Variables de Entrada — 76 Parametros

### 2.1 Load Profile (Perfil de Carga)

| Variable | Clave | Default | Rango | Unidad | Descripcion |
|---|---|---|---|---|---|
| IT Load | p_it | 100.0 | 0.1-2000 | MW | Carga IT del data center (sin PUE) |
| PUE | pue | 1.20 | 1.0-3.0 | ratio | Power Usage Effectiveness |
| Capacity Factor | capacity_factor | 0.90 | 0.01-1.0 | ratio | Factor de capacidad promedio anual |
| Peak/Avg Ratio | peak_avg_ratio | 1.15 | 1.0-2.0 | ratio | Relacion carga pico / promedio |
| Load Step | load_step_pct | 40.0 | 0-100 | % | Maximo cambio instantaneo de carga |
| Spinning Reserve | spinning_res_pct | 20.0 | 0-100 | % | Reserva rodante requerida |
| Availability | avail_req | 99.99 | 90-100 | % | Disponibilidad objetivo (Tier IV) |
| Load Ramp Rate | load_ramp_req | 3.0 | >0 | MW/min | Velocidad de cambio de carga |
| DC Type | dc_type | AI Factory | seleccion | — | Tipo de data center |

### 2.2 Site Conditions

| Variable | Clave | Default | Rango | Unidad | Descripcion |
|---|---|---|---|---|---|
| Derate Mode | derate_mode | Auto-Calculate | — | — | Auto o Manual |
| Site Temperature | site_temp_c | 35.0 | -40 a 60 | C | Temp. ambiente. Derating >40C |
| Site Altitude | site_alt_m | 100.0 | 0-5000 | m | Altitud. Derating >300m |
| Methane Number | methane_number | 80 | 0-100 | MN | Calidad del gas. Derating <80 |
| Manual Derate | derate_factor_manual | 0.90 | 0.01-1.0 | ratio | Factor manual directo |

### 2.3 Technology

| Variable | Clave | Default | Descripcion |
|---|---|---|---|
| Generator Model | generator_model | G3516H | Modelo del generador (8 opciones) |
| Gen Overrides | gen_overrides | null | Sobreescritura de parametros |
| Use BESS | use_bess | true | Incluir BESS |
| BESS Strategy | bess_strategy | Hybrid (Balanced) | Transient Only / Hybrid / Reliability Priority |
| Black Start | enable_black_start | true | BESS para arranque en negro |
| Cooling | cooling_method | Air-Cooled | Air-Cooled o Water-Cooled |
| Frequency | freq_hz | 60 | 50 o 60 Hz |
| Distribution Loss | dist_loss_pct | 1.5% | Perdidas de distribucion |
| Voltage Mode | volt_mode | Auto-Recommend | Auto o Manual |
| Manual Voltage | manual_voltage_kv | 13.8 | kV manual |

### 2.4 Economics

| Variable | Clave | Default | Unidad | Descripcion |
|---|---|---|---|---|
| Gas Price | gas_price | 3.50 | $/MMBtu | Precio gas natural |
| WACC | wacc | 8.0 | % | Costo de capital |
| Project Years | project_years | 20 | anos | Horizonte del proyecto |
| Benchmark Price | benchmark_price | 0.12 | $/kWh | Precio referencia grid |
| Carbon Price | carbon_price_per_ton | 0.0 | $/ton | Impuesto carbono |
| MACRS | enable_depreciation | true | — | Depreciacion acelerada |
| BESS Cost (kW) | bess_cost_kw | 250 | $/kW | Costo inversor BESS |
| BESS Cost (kWh) | bess_cost_kwh | 400 | $/kWh | Costo baterias BESS |
| BESS O&M | bess_om_kw_yr | 5.0 | $/kW/yr | O&M anual BESS |
| Gen Cost Mode | gen_cost_mode | budget_estimate | — | Estimacion o precio BDM |
| BDM Total Price | gen_total_price_bdm | 0.0 | USD | Precio total del BDM |
| Force Emissions | force_emissions | false | — | Forzar aftertreatment |
| SCR Cost | cost_scr_kw | 75 | $/kW | Costo SCR |
| OxiCat Cost | cost_oxicat_kw | 25 | $/kW | Costo catalizador oxidacion |
| Fuel Mode | fuel_mode | Pipeline Gas | — | Pipeline / LNG / Dual-Fuel |
| LNG Days | lng_days | 5 | dias | Autonomia LNG |
| CHP | include_chp | false | — | Trigeneracion (+20% CAPEX) |
| Max Area | max_area_m2 | 10000 | m2 | Area maxima planta |
| Region | region | US - Gulf Coast | — | 15 regiones para costos |

---

## 3. Biblioteca de Generadores — 8 Modelos CAT

### Especificaciones Principales

| Modelo | Tipo | ISO (MW) | Eficiencia | Heat Rate | Step Load | Ramp (MW/s) | MTBF (h) |
|---|---|---|---|---|---|---|---|
| XGC1900 | High Speed | 1.90 | 39.2% | 8,780 | 25% | 0.5 | 50,000 |
| G3520FR | High Speed | 2.50 | 38.6% | 8,836 | 40% | 0.6 | 48,000 |
| G3520K | High Speed | 2.50 | 45.3% | 7,638 | 15% | 0.4 | 52,000 |
| G3516H | High Speed | 2.50 | 44.1% | 7,740 | 25% | 0.5 | 50,000 |
| CG260-16 | High Speed | 3.96 | 43.4% | 7,860 | 10% | 0.45 | 55,000 |
| C175-20 | High Speed | 4.00 | 42.0% | 8,120 | 20% | 0.5 | 50,000 |
| Titan 130 | Gas Turbine | 16.50 | 35.4% | 9,630 | 15% | 2.0 | 80,000 |
| G20CM34 | Medium Speed | 9.76 | 47.5% | 7,480 | 10% | 0.3 | 60,000 |

### Emisiones y Costos

| Modelo | NOx (g/kWh) | CO (g/kWh) | Cost ($/kW) | Install ($/kW) | Maint Int (h) | Maint Dur (h) |
|---|---|---|---|---|---|---|
| XGC1900 | 0.50 | 2.50 | 775 | 300 | 1,000 | 48 |
| G3520FR | 0.50 | 2.10 | 575 | 650 | 1,000 | 48 |
| G3520K | 0.30 | 2.30 | 575 | 650 | 1,000 | 48 |
| G3516H | 0.50 | 2.00 | 550 | 600 | 1,000 | 48 |
| CG260-16 | 0.50 | 1.80 | 675 | 1,100 | 1,000 | 48 |
| C175-20 | 0.50 | 1.50 | 625 | 900 | 1,000 | 56 |
| Titan 130 | 0.60 | 0.60 | 775 | 1,000 | 8,000 | 120 |
| G20CM34 | 0.50 | 0.50 | 700 | 1,250 | 2,500 | 72 |

### Parametros Electricos

| Modelo | Power Density (MW/m2) | Gas Pressure (psi) | Reactance X"d (p.u.) | Inertia H (s) |
|---|---|---|---|---|
| XGC1900 | 0.010 | 1.5 | 0.14 | 1.0 |
| G3520FR | 0.010 | 1.5 | 0.14 | 1.5 |
| G3520K | 0.010 | 1.5 | 0.13 | 1.2 |
| G3516H | 0.010 | 1.5 | 0.14 | 1.2 |
| CG260-16 | 0.009 | 7.25 | 0.15 | 1.3 |
| C175-20 | 0.009 | 3.0 | 0.15 | 1.4 |
| Titan 130 | 0.020 | 300 | 0.18 | 5.0 |
| G20CM34 | 0.008 | 90 | 0.16 | 2.5 |

> **GERP Parser:** Incluye funcion `parse_gerp_pdf()` para importar specs de reportes PDF de Caterpillar.

---

## 4. Metodologias de Calculo — 14 Funciones

### 4.1 Part-Load Efficiency `get_part_load_efficiency()`

Interpolacion lineal contra curvas CAT por tipo de generador.

**Curvas (factor sobre eficiencia base):**

| Carga % | High Speed | Medium Speed | Gas Turbine |
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

Verificacion de caida de voltaje para cargas AI.

```
equiv_xd = xd_pu / sqrt(num_units)
voltage_sag = (step_load_pct / 100) * equiv_xd * 100
PASS si voltage_sag <= 10%
```

### 4.3 Frequency Screening `frequency_screening()`

Ecuacion de swing simplificada para nadir y ROCOF.

```
Constantes: R=0.05 (droop), D=2.0 (damping), T_gov=0.5s, pf=0.85

S_total_mva = n_running * (unit_cap_mw / pf)
H_total = H_mech + H_bess  (H_bess = 4.0 * min(1, bess_ratio/0.2))

ROCOF = (P_step_pu * freq_hz) / (2 * H_total)
df_ss = (P_step_pu / (D + 1/R)) * freq_hz
overshoot = 1.0 + sqrt(T_gov / (4 * H_total))
df_nadir = df_ss * overshoot
nadir_hz = freq_hz - df_nadir

Criterios: nadir >= 59.5 Hz (60 Hz), ROCOF <= 1.0 Hz/s
```

### 4.4 Spinning Reserve `calculate_spinning_reserve_units()`

```
spinning_reserve_mw = p_avg * (spinning_res_pct / 100)

SIN BESS:  required_cap = p_avg + spinning_from_gens
CON BESS (>90% cobertura): required_cap = p_avg * 1.05

n_running = ceil(required_cap / unit_capacity)
```

### 4.5 BESS Sizing `calculate_bess_requirements()`

6 componentes independientes:

1. **Step Load Support:** max(0, step_load_mw - gen_step_mw)
2. **Peak Shaving:** p_peak - p_avg
3. **Ramp Rate Support:** max(0, (load_ramp_req - gen_ramp) * 10)
4. **Frequency Regulation:** p_avg * 0.05
5. **Black Start:** p_peak * 0.05 (si habilitado)
6. **Spinning Reserve:** p_avg * (step_load_pct / 100)

```
bess_power = max(comp1..6, p_peak * 0.15)  # piso 15% del pico
bess_energy = bess_power / 1.0 / 0.85      # C-rate=1, DoD=85%
```

### 4.6 BESS Reliability Credit `calculate_bess_reliability_credit()`

```
realistic_coverage = 2.0 horas
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

Envejecimiento: aging(year) = max(0.95, 1.0 - year * 0.001)
```

### 4.8 Fleet Optimization `optimize_fleet_size()`

Punto optimo de carga: 72.5%. Score multi-objetivo:

```
load_penalty = |load_pct - 72.5| / 100
score = efficiency * (1 - load_penalty * 0.5)
Selecciona n con mayor score (rango 30-95% de carga)
```

### 4.9 MACRS Depreciation `calculate_macrs_depreciation()`

```
Schedule: [20%, 32%, 19.2%, 11.52%, 11.52%, 5.76%]
Tax rate: 21%
PV_benefit = Sum(CAPEX * rate * tax_rate / (1+WACC)^yr)
```

### 4.10 Noise Propagation (3 funciones)

```
Combined:  L_total = (L_source - attenuation) + 10*log10(N)
Distance:  L_rx = L_src - 20*log10(d) - 11
Setback:   d_min = 10^((L_combined - L_limit - 11) / 20)
```

### 4.11 Site Derating `calculate_site_derate()`

```
temp_derate = 1 - ((T-40)/5.5)*0.01     si T>40C
alt_derate  = 1 - ((alt-300)/300)*0.035  si alt>300m
fuel_derate = 1 - ((80-MN)/100)*0.15     si MN<80

derate = max(0.50, temp * alt * fuel)
```

### 4.12 Emissions `calculate_emissions()`

```
NOx_lb_hr = p_avg_kw * (NOx_g_kwh / 1000)
NOx_tpy = (NOx_lb_hr * effective_hours) / 2000
CO2_tpy = fuel_mmbtu_hr * 0.0531 * 8760 * CF

Conversiones: mg/Nm3 = g_kWh * 3.6 / 4.5
              ppmvd  = mg_Nm3 / factor (NOx:2.05, CO:1.25)

Aftertreatment: SCR si NOx>100tpy o >0.5 g/kWh (90% reduccion)
                OxiCat si CO>100tpy o >2.0 g/kWh (85% reduccion)

Urea: 20 L/MWh, storage 30 dias, totes de 275 gal, $0.50/gal
```

5 jurisdicciones: US EPA NSPS, Title V, EU MCP, EU IED, CARB.

### 4.13 Footprint `calculate_footprint()`

| Componente | Formula |
|---|---|
| Generadores | N * unit_cap / power_density |
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

## 5. Pipeline de Sizing — 23 Pasos

Funcion: `run_full_sizing(inputs: SizingInput) -> SizingResult`

1. **Resolve Generator** — Carga generador de biblioteca + overrides
2. **Load Calculations** — p_dc = p_it * PUE, p_avg = p_dc * CF, p_peak, perdidas dist.
3. **Site Derating** — Auto-calcula o aplica manual. unit_site_cap = iso * derate
4. **BESS Sizing** — 6 componentes transient si use_bess=true
5. **Spinning Reserve** — N unidades con headroom
6. **Fleet Optimization** — Punto optimo 72.5% carga
7. **Availability Target** — Convierte % a decimal, MTTR=48h
8. **Reliability Configs A/B/C** — A: No BESS, B: BESS Transient, C: Hybrid/Reliability (5-8 gensets, 2-2.5h cobertura, credito 0.65x)
9. **Select Configuration** — Segun bess_strategy
10. **Extract Final Values** — n_running, n_reserve, n_total, BESS breakdown
11. **Fleet Efficiency + Site Corrections** — Fuel quality (MN<70: x0.94, MN<80: x0.98), altitud extrema
12. **Voltage Recommendation** — <10MW:4.16kV, <50MW:13.8kV, >=50MW:34.5kV
13. **Transient Stability** — Voltage sag <= 10%
14. **Availability Curve** — Binomial N+X con envejecimiento
15. **Emissions** — NOx, CO, CO2, aftertreatment, urea, 5 regulaciones
16. **Footprint** — Area por componente, LNG si aplica
17. **Net Efficiency** — fleet_eff * (1 - dist_loss%)
18. **Financial** — CAPEX, O&M, fuel, carbon, MACRS, BESS repowering (bat:10y, inv:15y), LCOE, NPV, payback
19. **CAPEX Breakdown** — gen, install, CHP, BESS, aftertreatment
20. **O&M Breakdown** — fixed, variable, labor, overhaul, BESS, AT, urea
21. **Gas Sensitivity** — 20 puntos, breakeven gas price
22. **Grid Comparison** — Acumulados grid vs CAT, crossover year
23. **Assemble Result** — SizingResult (55+ campos)

---

## 6. Variables de Salida — 55+ Campos

### Proyecto
project_name, dc_type, region, app_version

### Carga
p_it, pue, p_total_dc, p_total_avg, p_total_peak, capacity_factor, avail_req

### Generador
selected_gen, unit_iso_cap, unit_site_cap, derate_factor

### Flota
n_running, n_reserve, n_total, installed_cap, load_per_unit_pct, fleet_efficiency

### Reserva Rodante
spinning_reserve_mw, spinning_from_gens, spinning_from_bess, headroom_mw

### Confiabilidad
reliability_configs (list de hasta 3), selected_config_name

### BESS
use_bess, bess_strategy, bess_power_mw, bess_energy_mwh, bess_breakdown (7 componentes)

### Electrico
rec_voltage_kv, freq_hz, stability_ok, voltage_sag, net_efficiency, system_availability, availability_over_time

### Emisiones y Huella
emissions (dict: NOx/CO/CO2 en 5 unidades, aftertreatment, urea, compliance 5 jurisdicciones)
footprint (dict: gen, BESS, LNG, cooling, substation, total, power_density)

### Financiero
lcoe ($/kWh), npv (USD), total_capex (USD), annual_fuel_cost, annual_om_cost, simple_payback_years, annual_savings, grid_annual_cost, breakeven_gas_price, capex_breakdown (5 categorias), om_breakdown (7 categorias), gas_sensitivity (20 puntos), grid_comparison (acumulados + crossover)

---

## 7. Templates Predefinidos

| Template | IT Load | PUE | CF | Peak/Avg | Step | Spin | Avail | Generator | BESS |
|---|---|---|---|---|---|---|---|---|---|
| Edge/Micro | 2 MW | 1.30 | 0.85 | 1.20 | 50% | 25% | 99.95% | XGC1900 | Transient Only |
| Enterprise | 20 MW | 1.25 | 0.85 | 1.20 | 40% | 20% | 99.99% | G3516H | Hybrid |
| Hyperscale | 100 MW | 1.18 | 0.90 | 1.15 | 30% | 15% | 99.995% | G20CM34 | Hybrid |
| AI Campus | 500 MW | 1.15 | 0.92 | 1.10 | 25% | 15% | 99.999% | G20CM34 | Reliability Priority |

---

## 8. Multiplicadores Regionales

| Region | Multiplicador |
|---|---|
| US - Gulf Coast | 1.00 (base) |
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

| Capacidad | Factor | Razon |
|---|---|---|
| < 2.5 MW | 1.30 | Sin economia de escala |
| 2.5-10 MW | 1.15 | Proyecto pequeno |
| 10-50 MW | 1.05 | Mediano |
| >= 50 MW | 1.00 | Escala completa |

### O&M por Defecto

| Concepto | Valor | Unidad |
|---|---|---|
| Fixed O&M | $12.00 | $/kW/yr |
| Variable O&M | $5.00 | $/MWh |
| Labor per Unit | $50,000 | $/unit/yr |
| Overhaul | $40,000 | $/MW (c/60,000h) |

---

## 9. Matriz de Emisiones — 5 Jurisdicciones

| Regulacion | Region | NOx Limite | CO Limite | Alcance |
|---|---|---|---|---|
| US EPA NSPS (JJJJ) | US | <= 1.5 g/kWh | <= 3.7 g/kWh | SI engines >500 hp |
| US EPA Title V | US | <= 100 tpy | <= 100 tpy | Emisiones totales sitio |
| EU MCP | EU | <= 95 mg/Nm3 | <= 500 mg/Nm3 | 1-50 MWth |
| EU IED (BAT-AEL) | EU | <= 75 mg/Nm3 | <= 100 mg/Nm3 | >50 MWth |
| CARB | California | <= 0.11 g/kWh | <= 0.45 g/kWh | Mas estricta US |

**Aftertreatment automatico:** SCR (90% NOx) si >100 tpy o >0.5 g/kWh. OxiCat (85% CO) si >100 tpy o >2.0 g/kWh.

---

## 10. Resumen Tecnico

| Metrica | Valor |
|---|---|
| Version | 3.1 |
| Motor (engine.py) | 14 funciones, 897 lineas |
| Pipeline (sizing_pipeline.py) | 23 pasos, 830 lineas |
| Generadores | 8 modelos, ~20 specs c/u |
| Variables Entrada | 76 parametros, 4 categorias |
| Variables Salida | 55+ campos (Pydantic) |
| Templates | 4 (Edge, Enterprise, Hyperscale, AI Campus) |
| Regulaciones Emisiones | 5 jurisdicciones |
| Regiones | 15 multiplicadores |
| Estrategias BESS | 3 |
| Componentes BESS | 6 independientes |
| Confiabilidad | Binomial N+X con Weibull aging |
| Depreciacion | MACRS 5 anos, 21% |
| Sensibilidad | 20 puntos gas price |
| Paises | 150+ |

---

*CAT QuickSize v3.1 — Manual Tecnico Detallado — 2025*
*Autor: Francisco Saraiva — Todos los derechos reservados*
