---
type: concept
title: Thermal model
description: Single-state 1R1C model with exact hourly update, COP curve, synthetic fixture and what its two envelopes hold fixed.
resource: preheat/model.py, preheat/fixture.py
tags: [thermal-model, 1R1C, heat-pump]
author: smSamani
generated:
  at: 2026-11-19
status: current
stale_after: 2027-05-18
sources:
  - id: sperber2020
    title: Reduced-order models for assessing demand response with heat pumps
    url: https://elib.dlr.de/190165/1/Sperber%20et%20al_2020_Postprint_Reduced-order%20models%20for%20assessing%20DR%20with%20heat%20pumps.pdf
  - id: yu2024
    title: Yu et al. (2024), effective heat capacity of a simulated well-insulated house
    url: https://doi.org/10.1016/j.buildenv.2024.111391
  - id: laemmle2021
    title: Lämmle et al. (2021), performance of heat pumps in existing buildings
    url: https://www.lowex-bestand.de/wp-content/uploads/2022/01/Preprint_L%C3%A4mmle_et_al_2021_Performance-of-heat-pumps-in-existing-buildings.pdf
---

# Thermal model

One zone, one state. The whole home (air, fabric and contents together) is a single heat store with capacity `C` (kWh/K). It loses heat to outside through an effective whole-home loss coefficient `UA` (kW/K), which covers fabric and ventilation together. With inputs constant over an hour, `C·dT/dτ = COP·p + g − UA·(T − Tout)` has the exact solution

```
a = exp(−UA·Δt/C),  Δt = 1 h,  Q = COP·p + g,  Teq = Tout + Q/UA
T[t+1] = a·T[t] + (1 − a)·Teq
```

This is the exact discrete update, not an Euler step[^sperber2020]. `UA·Δt/C` is dimensionless. `p` is electrical kW. `COP·p` and `g` are thermal kW. Because Δt is one hour, kW held for the hour equals kWh. `energy_terms` gives an independent per-hour energy balance using the closed-form integral of the exponential trajectory; the residual must be about zero (test T3). A separate fine-step integration of the differential equation checks the update itself (test T2).

`check_bounds` returns a violation for any non-finite value or wrong array length, so a NaN schedule cannot pass silently.

## Fixture (synthetic)

| Item | Value |
|---|---|
| C | 4 kWh/K nominal, order of magnitude only[^yu2024] |
| UA | 0.20 (current), 0.13 (lower-loss case) kW/K |
| Heat pump | 0 to 4 kW electrical, continuous |
| COP | `clip(3 + 0.05·(Tout − 5), 2, 4)`: 2.85 at 2 °C, 3.05 at 6 °C, never clipped in the fixture |
| Outdoor | 2 °C, 6 °C from 09:00 to 17:00 |
| Gains | 0.2 kW, 0.5 kW from 17:00 to 22:00 (no separate solar gains) |
| Price | €0.22/kWh, €0.38/kWh for hours starting 17:00 to 21:00 |
| Bounds | start 20 °C (validated: not below 20 °C, not above the ceiling); floor 20 °C; 21 °C at 18:00 to 21:00; `T[24] ≥ 20`; ceiling is the swept variable |

## What the two envelopes are

Only `UA` differs between `current` and `insulated`. `C`, heat-pump size, the COP curve, gains, weather, prices and bounds are all held fixed. The values are illustrative. They are not mapped to any real building class or renovation measure. A real retrofit would also change flow temperature and COP, airtightness and possibly accessible thermal mass[^laemmle2021].

## Magnitudes and the lumped-capacity assumption

At 20 °C indoors and 2 °C outdoors, steady heat loss is 3.60 kW (current) and 2.34 kW (insulated). The time constants `C/UA` are 20 h and 30.8 h. The 4 kW electrical cap gives about 11.4 to 12.2 kW of heat at nominal COP, several times the steady loss, so the cap is not tight in steady state. It still binds at least once in 48 of the 84 cost-optimal schedules (the schedule draws the full 4 kW in at least one hour), counted by re-solving every pair. A 2 kW diagnostic in [sweep.md](sweep.md) shows what happens when it does.

The 3.9 kWh/K estimate[^yu2024] is an effective daily-period capacitance for one simulated house. It gives limited support for treating 4 kWh/K as available within one hour. At 22.5 °C the lump holds 10 kWh more than at 20 °C. The model omits emitter lag and any difference between air and surface temperature, so it probably overstates how fast heat can be stored and recovered. The `capacity_3` and `capacity_8` cases show how much the answer depends on `C`.

## Cases

Seven one-at-a-time changes, applied to both envelopes: `nominal`, `outdoor_minus3`, `outdoor_plus3` (COP recomputed), `capacity_3`, `capacity_8`, `gains_x0.5`, `gains_x1.5`.

## Limitations

Air and structure are lumped. The heat pump is continuous with no cycling, minimum modulation, defrost or emitter lag. COP depends on outdoor temperature only, so lower flow temperatures after insulation are ignored[^laemmle2021]. Only UA differs between envelopes. Every profile is invented. The warmer, cheaper afternoon and the evening rise in gains and price coincide, which favours shifting.

[^sperber2020]: Sperber, Frey & Bertsch (2020), reduced-order heat-pump demand-response models.
[^yu2024]: Yu et al. (2024): about 3.9 kWh/K for one simulated, well-insulated house; supports only the order of magnitude of C.
[^laemmle2021]: Lämmle et al. (2021): flow temperature and COP in existing buildings.
