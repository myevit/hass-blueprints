# Occupant-Aware ERV Blueprints

Blueprint files:

- `occupant-aware-erv-recommendation.yaml` — template-domain diagnostic sensor.
- `occupant-aware-erv-controller.yaml` — automation-domain on/off ERV controller.

Version: 1.0.1

## Design and safety contract

The recommendation sensor is the policy layer; it never calls an ERV service. The controller is the actuator layer and consumes only the recommendation state and diagnostic attributes.

- The highest fresh, valid selected indoor CO2 value is used. Readings are not averaged.
- `critical` always requests ventilation.
- At the configurable CO2 pollution-override threshold, `ventilation_required` wins over a PM2.5 pollution hold. This prevents outdoor pollution from suppressing high indoor CO2 indefinitely.
- PM2.5 is the primary pollution signal. Outdoor VOC/AQ index is displayed as supporting diagnostic context only; it does not independently suppress ventilation.
- An occupancy sensor only reduces baseline demand. It does not change a high-CO2 recommendation.
- The controller defaults to dry-run. It logs the complete decision to `blueprints.occupant_aware_erv` and preserves the same variables in Home Assistant automation traces. Dry-run cannot call `switch.turn_on` or `switch.turn_off`.
- A required `input_boolean` manual blocker holds all actuator changes. Use it before direct/manual ERV operation. A `sensor_fault` also holds the switch state.
- Decision persistence provides temporal hysteresis; minimum on/off times, a fixed intermittent duty window, and maximum pollution-suppression time further reduce chatter. Critical CO2, CO2 pollution override, and maximum suppression expiry can bypass minimum off time; the manual blocker always wins.

## Recommendation states and diagnostic attributes

| State | Meaning | Controller intent |
|---|---|---|
| `clean_air_low_demand` | CO2 does not require ventilation; no PM2.5 hold applies. | Off after persistence/minimum-on guard. |
| `pollution_hold` | Fresh PM2.5 exceeds the configured hold threshold while CO2 is below override. | Off except for bounded relief pulses after each maximum-suppression interval. |
| `intermittent` | Occupied baseline CO2 or optional humidity support suggests periodic exchange. | Configured on/off duty cycle. |
| `ventilation_required` | CO2 reaches the ventilation threshold, or reaches the pollution-override threshold. | On. |
| `critical` | CO2 reaches critical threshold. | On immediately. |
| `sensor_fault` | Required CO2/PM2.5 data is unavailable or stale at non-urgent CO2, or configured CO2 thresholds are invalid. | Hold actuator state; inspect attributes. High/critical CO2 still requests ventilation when outdoor PM2.5 is unavailable. |

Important attributes include `decision_reason`, `selected_co2_ppm`, `valid_co2_sources`, `co2_overrides_pollution`, source-status attributes, configured `thresholds`, and `recovery_note`. Primary CO2 and outdoor PM2.5 are direct triggers and are reevaluated immediately on source updates. Optional secondary CO2, occupancy, humidity, and VOC inputs are reevaluated by the bounded five-minute trigger; their normal decision latency is therefore up to approximately five minutes. Trigger-based template sensor state and attributes are restored on Home Assistant restart; the controller also performs a startup recheck.

## Defaults and units

Defaults are starting points, not claims of universal health or equipment limits. Tune them to the household, local air-quality guidance, ERV capacity, and professional advice.

| Input | Default | Unit |
|---|---:|---|
| Sensor maximum age | 15 | minutes |
| Occupied baseline CO2 | 800 | ppm |
| CO2 ventilation required | 1000 | ppm |
| CO2 pollution override | 1200 | ppm |
| Critical CO2 | 1400 | ppm |
| PM2.5 pollution hold | 35 | µg/m³ |
| Humidity intermittent support | 60 | %RH |
| Recommendation persistence | 5 | minutes |
| Minimum ERV on time | 10 | minutes |
| Minimum ERV off time | 5 | minutes |
| Maximum pollution suppression | 60 | minutes |
| Intermittent cycle / on portion | 30 / 10 | minutes |

Keep thresholds ordered: baseline ≤ ventilation-required ≤ pollution-override ≤ critical. Keep intermittent on time no greater than its cycle length. Invalid ordering is enforced as `sensor_fault` / `hold_invalid_timing_configuration`, not merely documented.

## Import and use

1. Copy or import `occupant-aware-erv-recommendation.yaml` as a **Template** blueprint. Official Home Assistant placement is `config/blueprints/template/<author>/` when managing files manually. Create a template entity from it and give the resulting sensor a stable entity ID.
2. Create a manual-blocker helper: **Settings → Devices & services → Helpers → Create helper → Toggle**. Keep it on while installing, testing, servicing, or manually controlling the ERV.
3. Copy or import `occupant-aware-erv-controller.yaml` as an **Automation** blueprint. Create an automation from it, select the recommendation sensor, ERV switch, and blocker helper. Leave Live mode disabled.
4. Observe recommendation attributes, controller traces, and `blueprints.occupant_aware_erv` logs across normal occupancy and outdoor-air conditions. Verify the proposed state changes and timers.
5. Only after review, explicitly enable Live mode. Keep notifications disabled unless a suitable notification action is configured.

Home Assistant's Blueprint UI imports automation blueprints from **Settings → Automations & scenes → Blueprints → Import Blueprint**. Template blueprints are installed under the template blueprints directory and then instantiated as template entities; current official template documentation describes this separate flow.

## Household test example (documentation only)

These entities are **examples only** and are not embedded in either blueprint:

- Outdoor PM2.5: `sensor.airgradient_pm2_5`
- Optional outdoor VOC: `sensor.airgradient_voc_index`
- Indoor CO2: `sensor.view_plus_carbon_dioxide`, `sensor.wave_plus_carbon_dioxide`
- Optional occupancy: `binary_sensor.magic_areas_aggregates_house_aggregate_occupancy`
- Optional humidity: `sensor.house_humidity`
- ERV switch: `switch.erv`

## Test matrix

| Scenario | Inputs / setup | Expected recommendation | Expected dry-run decision |
|---|---|---|---|
| Low demand, clean outdoor air | Fresh low CO2 and PM2.5 below hold | `clean_air_low_demand` | `turn_off` after persistence and minimum-on time. |
| Occupied baseline | Occupancy on, highest CO2 ≥ baseline and below ventilation threshold | `intermittent` | Alternates by configured clock-hour duty window. |
| Unoccupied baseline | Occupancy off, same non-urgent CO2 | `clean_air_low_demand` | No baseline-driven intermittent request. |
| PM2.5 hold | PM2.5 ≥ hold; CO2 below override | `pollution_hold` | `turn_off`; after each maximum-suppression interval, run a bounded relief pulse using the configured intermittent on-time. |
| CO2 overrides pollution | PM2.5 ≥ hold; highest CO2 ≥ override | `ventilation_required` | `turn_on`; bypasses minimum off time. |
| Critical CO2 | Highest valid CO2 ≥ critical | `critical` | Immediate `turn_on`; bypasses persistence/minimum off time. |
| Secondary sensor higher | Both fresh; secondary higher | State is based on secondary/highest value | Inspect `selected_co2_ppm` and `valid_co2_sources`. |
| CO2 stale/unavailable | All selected CO2 invalid or older than max age | `sensor_fault` | `hold_sensor_fault`; no ERV service in dry-run or live mode. |
| PM2.5 stale/unavailable, CO2 below override | Fresh valid non-urgent CO2, invalid PM2.5 | `sensor_fault` | Hold current actuator state rather than assuming outdoor air is clean. |
| PM2.5 stale/unavailable, high CO2 | CO2 ≥ pollution override, invalid PM2.5 | `ventilation_required` or `critical` | CO2 need still wins; request ventilation. |
| Invalid configuration | Misordered CO2 thresholds or intermittent on-time > cycle | `sensor_fault` or valid recommendation with controller hold | No actuator change; inspect reason/trace. |
| Sensor recovery | Restore a fresh valid input | Normal state immediately for primary CO2/PM2.5, or on the next five-minute trigger for optional inputs | Re-evaluates from recovered recommendation. |
| Manual blocker | Blocker on during any condition | Recommendation unchanged | `hold_manual_blocker`; no actuator service even in Live mode. |
| Restart | Restart while ERV is off / pollution hold | Restored recommendation then startup recheck | Uses restored recommendation state age and current switch state; inspect trace before Live mode. |

## Known operational limits

Maximum suppression is measured from the recommendation sensor's continuous `pollution_hold` state age. A pre-existing ERV-off interval therefore cannot cause immediate suppression expiry when outdoor pollution first arrives. Once the interval elapses, the controller permits only a bounded relief pulse (the configured intermittent on-time, capped to the suppression interval), then returns to pollution hold. The startup trigger reevaluates restored state without relying on an in-memory timer. Use the manual blocker for any direct/manual ERV operation.

The intermittent schedule is based on the local clock minute within each hour. It is deterministic and restart-safe, but it is not a rolling timer. A five-minute controller check bounds normal actuation latency.

## Official documentation researched

- Blueprint schema: https://www.home-assistant.io/docs/blueprint/schema/
- Template integration and template blueprints: https://www.home-assistant.io/integrations/template/
- Automation YAML schema: https://www.home-assistant.io/docs/automation/yaml/
- Automation triggers: https://www.home-assistant.io/docs/automation/trigger/
- Automation actions: https://www.home-assistant.io/docs/automation/action/
