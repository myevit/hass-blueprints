# Continuous ERV Outdoor-Air Compromise Blueprints

Blueprint files:

- `occupant-aware-erv-recommendation.yaml` — template policy sensor.
- `occupant-aware-erv-controller.yaml` — guarded soft-control automation.

Version: 2.0.1

## Equipment contract

This policy is designed for a continuous-duty ERV such as the **Panasonic Intelli-Balance 100 FV-10VEC2**. Panasonic describes its normal behavior as a low, continuous run, rates both motors for continuous operation, and ships its ASHRAE timer at 60 minutes per hour. Panasonic also documents the wall-switch input as a way to power down the fans and close outdoor dampers during poor outdoor air quality.

Therefore:

- Normal operation is **on continuously**.
- Low CO2, vacancy, or normal humidity never requests off.
- There is no Home Assistant duty cycle.
- A temporary off request is allowed only for confirmed, fresh outdoor PM2.5 pollution while indoor CO2 remains below the configured override.
- The Home Assistant switch represents the ERV wall/soft-control input; it is not used as a routine demand timer.

Official Panasonic sources:

- Product page: https://iaq.na.panasonic.com/erv/intelli-balance-100-any-climate-corded
- Installation and operating manual: https://ftp.panasonic.com/ventilationfan/intellibalance/intelli_10vec2h_en_install.pdf
- Sell sheet: https://ftp.panasonic.com/ventilationfan/intellibalance/intellibalance100_sellsheet.pdf

## Policy states

| State | Meaning | Controller intent |
|---|---|---|
| `normal_ventilation` | Outdoor PM2.5 is below the hold policy and indoor inputs are valid. | On continuously. |
| `pollution_hold` | Fresh outdoor PM2.5 has crossed the hold threshold and indoor CO2 is below override. | Off after persistence and minimum-on guard. |
| `ventilation_required` | Indoor CO2 is at or above the pollution-override threshold. | On immediately, even during outdoor pollution. |
| `critical` | Indoor CO2 is at or above the critical threshold. | On immediately. |
| `sensor_fault` | Required input is stale/unavailable/invalid or thresholds are misordered. | Fail on; an off hold requires positive evidence of bad outdoor air. |

Outdoor VOC, occupancy, and humidity remain visible as diagnostics but do not control routine operation.

## Default compromise thresholds

| Input | Default |
|---|---:|
| Sensor maximum age | 15 minutes |
| Outdoor PM2.5 hold entry | 55 µg/m³ |
| Outdoor PM2.5 hold release | 35 µg/m³ |
| Indoor CO2 pollution override | 1200 ppm |
| Critical indoor CO2 | 1400 ppm |
| Decision persistence | 10 minutes |
| Minimum on time | 10 minutes |
| Minimum off time | 10 minutes |

### PM2.5 hysteresis

The recommendation enters `pollution_hold` at **55 µg/m³ or above** after the controller persistence period. This entry value is approximately the current U.S. EPA boundary between *Unhealthy for Sensitive Groups* and *Unhealthy* PM2.5 air; it is used here as an engineering control point, not as an official ERV-operating prescription. Once held, it remains latched until PM2.5 reaches **35 µg/m³ or below**. The 20 µg/m³ deadband prevents chatter. The trigger-based sensor uses Home Assistant's documented `this` variable to retain the previous latch across reevaluations, restarts, and temporary PM-sensor outages. Changing the configured PM thresholds resets the old latch and reevaluates against the new entry threshold.

### Indoor/outdoor compromise

When outdoor PM2.5 is bad:

- CO2 below 1200 ppm: temporarily hold outdoor exchange off.
- CO2 at or above 1200 ppm: indoor air need outweighs the pollution hold; turn on.
- CO2 at or above 1400 ppm: critical, immediate on.

This is a policy compromise, not a medical claim. Tune thresholds if household needs or authoritative local guidance require it.

## Timing and safety

- `pollution_hold` and normal recovery must persist for 10 minutes before switching.
- Minimum on/off times reduce repeated soft-switch changes.
- `ventilation_required`, `critical`, and `sensor_fault` fail-on bypass persistence and minimum-off delay.
- The mandatory blocker is fail-closed: only an explicit `off` permits a service call. `on`, `unknown`, and `unavailable` all block. Restart mode plus a final blocker check immediately before each service call closes the blocker-change race.
- Dry-run remains the blueprint default.
- The controller reevaluates on recommendation changes, blocker changes, Home Assistant startup, and every five minutes.

## Household mapping

- Primary CO2: `sensor.view_plus_carbon_dioxide`
- Secondary CO2: `sensor.wave_plus_carbon_dioxide`
- Outdoor PM2.5: `sensor.airgradient_pm2_5`
- Supporting outdoor VOC: `sensor.airgradient_voc_index`
- Diagnostic occupancy: `binary_sensor.magic_areas_aggregates_house_aggregate_occupancy`
- Diagnostic humidity: `sensor.house_humidity`
- ERV soft-control switch: `switch.erv`
- Manual blocker: `input_boolean.erv_automation_blocker`

## Test matrix

| Scenario | Recommendation | Expected action |
|---|---|---|
| Clean outdoor air, low CO2 | `normal_ventilation` | On; low demand does not stop ERV. |
| Clean outdoor air, high CO2 | `ventilation_required` or `critical` | On. |
| PM2.5 rises to 55+, CO2 below 1200 | `pollution_hold` | Off after persistence/minimum-on time. |
| PM2.5 falls but remains above 35 | `pollution_hold` remains latched | Stay off. |
| PM2.5 reaches 35 or below | `normal_ventilation` | On after persistence/minimum-off time. |
| PM2.5 bad, CO2 reaches 1200 | `ventilation_required` | Immediate on. |
| PM2.5 bad, CO2 reaches 1400 | `critical` | Immediate on. |
| Outdoor PM2.5 unavailable/stale | `sensor_fault` | Fail on. |
| All selected CO2 unavailable/stale | `sensor_fault` | Fail on. |
| Blocker on | Recommendation unchanged | Hold; no service call. |
| Blocker unavailable/unknown | Recommendation unchanged | Fail-closed hold; no service call. |
| Unknown/unavailable recommendation | Unknown/unavailable | Fail on; only an explicit `pollution_hold` may request off. |

## Import and rollout

1. Install the template blueprint under `config/blueprints/template/<author>/` and instantiate the recommendation sensor.
2. Create the mandatory blocker helper and turn it on.
3. Install the automation blueprint and leave Live mode disabled.
4. Verify clean-air, synthetic pollution-hold, CO2-override, sensor-fault, and hysteresis scenarios in dry-run traces.
5. Enable Live mode only after validation; then remove the blocker and verify the real soft-control response.
