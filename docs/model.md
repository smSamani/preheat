---
type: concept
title: Thermal model
description: Single-zone 1R1C model with exact hourly update, COP curve and synthetic fixture.
resource: preheat/model.py, preheat/fixture.py
tags: [thermal-model, 1R1C, heat-pump]
generated:
  by: human:smSamani
  at: 2026-11-18
status: current
stale_after: 2027-05-18
sources:
  - id: sperber2020
    title: Reduced-order models for assessing demand response with heat pumps
    url: https://elib.dlr.de/190165/1/Sperber%20et%20al_2020_Postprint_Reduced-order%20models%20for%20assessing%20DR%20with%20heat%20pumps.pdf
  - id: yu2024
    title: Yu et al. (2024), effective heat capacity of a simulated well-insulated house
    url: https://ntnuopen.ntnu.no/ntnu-xmlui/bitstream/handle/11250/3182231/1-s2.0-S0360132324002336-main.pdf?isAllowed=y&sequence=1
  - id: laemmle2021
    title: Lämmle et al. (2021), performance of heat pumps in existing buildings
    url: https://www.lowex-bestand.de/wp-content/uploads/2022/01/Preprint_L%C3%A4mmle_et_al_2021_Performance-of-heat-pumps-in-existing-buildings.pdf
---

# Thermal model

One zone with heat capacity `C` (kWh/K) and loss coefficient `UA` (kW/K). With inputs constant over an hour, `C·dT/dτ = Q − UA·(T − Tout)` has the exact solution

```
a = exp(−UA·dt/C),  Q = COP·p + g,  Teq = Tout + Q/UA
T[t+1] = a·T[t] + (1 − a)·Teq
```

This is the exact discrete update, not an Euler step[^sperber2020]. `p` is electrical kW; heat delivered is `COP·p`. `energy_terms` gives an independent per-hour balance using the closed-form integral of the exponential trajectory; the residual must be about zero (test T3).

## Fixture (synthetic)

| Item | Value |
|---|---|
| C | 4 kWh/K nominal, order of magnitude only[^yu2024] |
| UA | 0.20 (current), 0.13 (insulated) kW/K |
| Heat pump | 0 to 4 kW electrical, continuous |
| COP | `clip(3 + 0.05·(Tout − 5), 2, 4)` |
| Outdoor | 2 °C, 6 °C from 09:00 to 17:00 |
| Gains | 0.2 kW, 0.5 kW from 17:00 to 22:00 |
| Price | €0.22/kWh, €0.38/kWh for hours starting 17:00 to 21:00 |
| Bounds | start 20 °C; floor 20 °C; 21 °C at 18:00 to 21:00; `T[24] ≥ 20`; ceiling is the swept variable |

## Cases

Seven one-at-a-time changes, applied to both envelopes: `nominal`, `outdoor_minus3`, `outdoor_plus3` (COP recomputed), `capacity_3`, `capacity_8`, `gains_x0.5`, `gains_x1.5`.

## Limitations

Air and structure are lumped; the heat pump is continuous with no cycling, defrost or emitter lag; COP depends on outdoor temperature only, so lower flow temperatures after insulation are ignored[^laemmle2021]; only UA differs between envelopes.

[^sperber2020]: Sperber, Frey & Bertsch (2020), reduced-order heat-pump demand-response models.
[^yu2024]: Yu et al. (2024): about 3.9 kWh/K for one simulated, well-insulated house; supports only the order of magnitude of C.
[^laemmle2021]: Lämmle et al. (2021): flow temperature and COP in existing buildings.
