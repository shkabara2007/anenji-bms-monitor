# Field observations — two ANENJI packs and PowMR inverter

Equipment: two paralleled ANENJI 12.8 V 100 Ah LiFePO₄ packs with 4-cell BLE BMS, PowMR POW-HVM1K-12V. November 6–12, 2026. The observations are not manufacturer specifications.

| Condition | Pack A | Pack B | Important qualification |
|---|---|---|---|
| End of charge, setting Bulk 14.2 V, Float 13.7 V (Nov 7) | ~94% BMS SOC, ~49 mV cell spread | ~91%, ~10 mV | BMS measured 0 A around 13.61 V; charger stage not captured |
| Near end, setting Bulk 14.3 V, Float 13.7 V (Nov 10) | ~93%, ~47 mV | ~90%, ~10 mV | Again at ~13.61 V, 0 A |
| Discharge after AC removed (Nov 10) | ~92%, ~7 mV | ~89%, ~6 mV | Spread decreased with change of operating point |
| End after AC reconnected, setting Bulk 14.4 V, Float 13.7 V (Nov 10) | ~93%, ~46 mV | ~90%, ~9 mV | Restarted at high SOC, not a full-cycle test |
| Discharge Nov 12 16:32 | 13.23 V, −5.14 A, SOC 85%, ~5 mV | 13.22 V, −5.50 A, SOC 82%, ~7 mV | No BMS error flags reported |

**Measured:** repeated current taper to 0 A near 13.61 V while the inverter's **configured** Bulk setting was 14.2–14.4 V; pack A cell spread was higher near the end of charge, lower on discharge. Both charge MOSFET status flags remained ON during cited charge observations.

**Not established:** actual peak charging voltage, time and condition of absorption/float transition, actual stored capacity, calibration of SOC estimators, precise balancing thresholds or hardware fault. The inverter charge-complete lamp was observed on, but this does not prove physical 100% charge. Do not extrapolate charge voltage settings to other batteries without their manufacturer specification.
