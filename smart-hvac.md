# Smart Thermostat Blueprint – Technical Overview

> **Blueprint file:** `smart-hvac.yaml` > **Version inside blueprint:** 1.12.0
> **Domain:** `automation`

---

## 1. Purpose & High-Level Behaviour

This Home Assistant blueprint transforms an ordinary **single-zone thermostat** into a smarter controller that keeps the _room_ or _group of rooms_ (not just the wall-mounted thermostat) inside a comfort band while respecting safety limits.

Core goals:

1. **Dynamic sensor selection** – Uses _Day_ and _Night_ room sensors and automatically swaps between them by the clock, those sensors could be from different rooms, based regular human occupancy through the day.
2. **Smooth circadian targets** – Generates a cosine temperature curve between the configured daytime and nighttime set-points.
3. **Adaptive nudging** – Every hour adjusts thermostat set-points by ≤ 0.5 °C to pull the room back toward the target band with minimal overshoot. Minimal 0.5C adjustment is required to give termostat a room to do own temperature control without triggering it go 100% on cooling or heating.
   3.1 **Room Temperature Control Rules (CRITICAL):**

   **ABSOLUTE BOUNDS (Always Enforced):**

   - Room temperature must NEVER be below `night_temp` (user's minimum comfort)
   - Room temperature must NEVER be above `day_temp` (user's maximum comfort)

   **COMFORT TOLERANCE (Normal Operation):**

   - If room temperature is within bounds, allow ±0.5°C deviation from circadian target
   - Only adjust thermostat when room drifts outside this ±0.5°C comfort zone

   **SAFETY LIMITS (Hard Stops):**

   - `safety_min_setpoint` < `night_temp` ≤ **actual_room_temp** ≤ `day_temp` < `safety_max_setpoint`
   - Never set thermostat beyond safety limits even for corrections

4. **Weather-aware anticipation** – (optional) Factors in weather forecast, outdoor temperature and solar impact to pre-empt natural heating/cooling trends.
5. **Mode management** – Can flip between `heat`, `cool`, and `heat_cool` modes (if allowed) to minimise drift.
6. **Fan enforcement** – Optionally forces the thermostat fan into a specified mode after each run (useful for ERV/HRV systems).
7. **Safety first** – Aborts if sensor data are stale/invalid or if requested temps exceed configured safety bounds.

All configuration is exposed in the blueprint UI—no YAML edits required.

---

## 2. Trigger & Execution Cadence

The automation runs **once per hour**, immediately executing its logic tree.

---

## 3. Inputs (Blueprint `input:` section)

Below is an exhaustive list of user-configurable inputs grouped by function. The internal entity-id variables created for each input are shown in parentheses.

### 3.1 Temperature Sensors & Targets

- `day_target_sensor` (`day_target_sensor_entity`): primary room sensor used during the daytime period.
- `night_target_sensor` (`night_target_sensor_entity`): primary room sensor used during the nighttime period.
- `thermostat` (`thermostat_entity`): the climate entity being controlled.
- `day_temp_input` (`day_temp_input_entity`): _input_number_ helper holding the daytime target temperature (used when `use_day_temp_input` is `true`).
- `use_day_temp_input` (default **true**): switch to read the daytime target from the helper instead of the fixed value.
- `day_temp_static` (default **22 °C**): fixed fallback daytime target when helper is disabled.
- `night_temp_input` (`night_temp_input_entity`): _input_number_ helper holding the nighttime target temperature.
- `use_night_temp_input` (default **true**): switch to read the nighttime target from the helper instead of the fixed value.
- `night_temp_static` (default **20 °C**): fixed fallback nighttime target when helper is disabled.
- `day_sensor_start_hour` (`day_start_hour`, default **6**): hour (0–23) when the automation begins using the _day_ sensor.
- `night_sensor_start_hour` (`night_start_hour`, default **22**): hour (0–23) when the automation begins using the _night_ sensor.

### 3.2 Data-Freshness & Safety

- `sensor_timeout` (default **2 h**): maximum age before a sensor reading is considered stale.
- `min_temp_limit` (default **10 °C**): skip if any sensor reads below this value.
- `max_temp_limit` (default **35 °C**): skip if any sensor reads above this value.
- `safety_min_setpoint` (default **18 °C**): never push the thermostat below this set-point.
- `safety_max_setpoint` (default **28 °C**): never push the thermostat above this set-point.

### 3.3 Weather / Environment (optional)

- `use_weather_forecast` (default **false**): master toggle that enables the weather-aware branch.
- `weather_entity`: Home Assistant weather entity used for forecasts.
- `outdoor_temp_sensor`: dedicated real-time outdoor temperature sensor.
- `use_outdoor_temp_sensor` (default **false**): whether to prefer the dedicated outdoor sensor over the forecast.
- `humidity_sensor`: optional indoor humidity sensor.
- `use_humidity_sensor` (default **false**): whether to include humidity in calculations.
- `solar_adjustment` (default **0.5 °C**): magnitude of direct sunlight impact.
- `forecast_adjustment` (default **0.3 °C**): base °C delta applied from forecast trends.
- `gradient_threshold` (default **2.0 °C**): indoor-outdoor Δ that defines a warming/cooling trend.

### 3.4 Circadian Settings

- `circadian_hour` (default **2**): hour of the coolest point on the circadian curve (warmest occurs 12 h later).

### 3.5 Fan & Mode Control

- `enforce_fan_mode` (default **true**): whether to force the thermostat fan mode after each run.
- `fan_mode_setting` (default **low**): fan mode that will be enforced.
- `allow_mode_switch` (default **false**): allows the automation to flip between _heat_ and _cool_ when the thermostat is not in `heat_cool`.

### 3.6 Debugging

- `debug_notifications` (default **false**): if enabled, writes a persistent notification after each run.

---

## 4. Variable Derivation

At runtime, the blueprint defines Jinja2 variables. Key ones:

- `current_target_sensor_entity` – Chooses _day_ vs _night_ sensor based on `day_start_hour`/`night_start_hour` and current time.
- `day_temp` / `night_temp` – Resolved numeric targets from helper or static value.
- `desired_temp` – **Cosine function** establishing a smooth temperature waveform between night and day targets.
  ```jinja2
  phase = (current_hour - circadian_hour) * 15°  # 24 h → 360°
  curve = (1 - cos(phase)) / 2                  # 0…1
  desired = night_temp + (day_temp - night_temp) * curve
  ```
- `temp_difference` – Δ between _current room_ and _desired_ temp.
- `offset_adjustment` – ±0.5 °C nudge if room drifts beyond desired ± 0.5 °C.
- `is_weather_available` – Boolean gating the _weather path_.
- Weather-specific vars (`solar_impact`, `natural_trend`, `weather_adjustment_factor`, …) – compute anticipatory adjustments.
- `needed_mode` – Decides if thermostat should switch HVAC mode (if allowed).

---

## 5. Execution Flow

The automation is essentially a **state-machine** with three nested decision layers:

1. **Pre-execution safety** – Stale/invalid sensor data → abort with optional debug notification.
2. **Weather or No-weather Path** – Branches depending on `is_weather_available`.
3. **HVAC mode specific actions** – Separate handling for `heat_cool` vs single-set-point modes.

A concise flowchart:

```mermaid
graph TD
    A[Hourly Trigger] --> B{Safety Check}
    B -- fail --> B1[Notify & Stop]
    B -- ok --> C{Weather Enabled?}
    C -- yes --> D[Calculate Weather Adjustments]
    C -- no --> E[Skip Weather Logic]
    D --> F
    E --> F
    F[Compute New Target(s)] --> G{Thermostat Mode}
    G -- heat_cool --> H[Set target_temp_low / high]
    G -- heat or cool --> I[Set temperature]
    H --> J{Mode Switch Needed?}
    I --> J
    J -- yes --> K[climate.set_hvac_mode]
    J --> L{Fan Enforcement}
    K --> L
    L -- needed --> M[climate.set_fan_mode]
    L --> N{Debug Enabled?}
    M --> N
    N -- yes --> O[persistent_notification.create]
```

---

## 6. Detailed Logic Notes

### 6.1 Safety Validation (`sensors_valid`)

Checks **three things** for the day sensor, night sensor, _and_ thermostat:

1. State not `unknown/unavailable/none`.
2. Temperature within `min_temp_limit` … `max_temp_limit`.
3. `last_updated` newer than `sensor_timeout`.

If _any_ fail, automation aborts and (optionally) creates a detailed **🛡️ Smart Thermostat Safety Check Failed** persistent notification.

### 6.2 Weather-Aware Adjustment

When enabled, the blueprint fetches `weather.get_forecasts` (hourly) and derives:

- **Outdoor temperature** – Forecast or dedicated sensor.
- **Solar impact** – Extra °C if condition is `sunny` / `partlycloudy` during 06-18h.
- **Natural trend** – `warming`, `cooling`, or `stable` using indoor-outdoor gradient, solar, building mass and forecast trend.

These feed `weather_adjustment_factor`, a signed °C offset that is:

- Applied **directly** to `heat_cool` bands (`weather_adjustment_for_range`).
- Applied **conditionally** in single-set-point modes (`natural_heat_cool_adjustment`).

### 6.3 Set-point Calculation (Heat-Cool Mode)

1. Compute candidate **low**:
   ```jinja2
   desired_band_low = desired_temp - 0.5
   low_candidate = max(desired_band_low, night_temp, safety_min)
   high_limit   = min(day_temp, safety_max)
   low_final    = min(low_candidate, high_limit - 1)
   ```
2. Rate-limit change to ±0.5 °C per run.
3. **High** is `low + 1 °C` capped to `day_temp`/`safety_max` and also rate-limited.
4. Guarantee min 1 °C difference; whichever point moved less is adjusted to satisfy the gap, required for thermostat to operate.

### 6.4 Set-point Calculation (Heat or Cool Mode)

_Target_ is the current thermostat set-point plus `offset_adjustment` and (if `natural_trend` aligns) `natural_heat_cool_adjustment`. Total change is again rounded to nearest 0.5 °C and clamped inside safety bounds.

### 6.5 HVAC Mode Switching

If `allow_mode_switch` is enabled and thermostat is **not** already in `heat_cool`, the blueprint will flip between `heat` ↔ `cool` when `temp_difference` exceeds ±0.7 °C.

### 6.6 Fan Mode Enforcement

After temperature changes, if `enforce_fan_mode` is true and the thermostat's current `fan_mode` differs from `fan_mode_setting`, the automation waits 1 minute then calls `climate.set_fan_mode`.

### 6.7 Debug Notification

When `debug_notifications` is on, the final action posts a `persistent_notification` summarising:

- Current & desired temps
- Weather impact breakdown (solar / trend)
- HVAC mode decision and actual changes made

Example title: **Smart Thermostat DEBUG ON**.

---

## 7. Rate Limiting & Stability Strategies

- All temperature deltas are **rounded to 0.5 °C** ensuring small, predictable nudges.
- Maximum change **per run** is ±0.5 °C on each set-point to avoid sudden jumps.

Keep this file as the "single source of truth" for future LLM-assisted edits to `smart-hvac.yaml`.

---

this are our test values for blueprint to abe able to do diagnostics:

bedroom_sensor: sensor.average_bedroom_temperature
thermostat: climate.thermostat
day_temp_input: input_number.smart_thermostat_target_temperature_day
night_temp_input: input_number.smart_thermostat_target_temperature_night
sensor_timeout: 5
day_target_sensor: sensor.average_bedroom_temperature
night_target_sensor: sensor.average_bedroom_temperature
day_sensor_start_hour: 10
night_sensor_start_hour: 18
weather_entity: weather.edmonton
use_weather_forecast: true
debug_notifications: true
safety_max_setpoint: 26
safety_min_setpoint: 18
update_frequency: "5"
forecast_adjustment: 0.2
gradient_threshold: 5
circadian_hour: 2
outdoor_temp_sensor: sensor.thermostat_outdoor_temperature
humidity_sensor: sensor.view_plus_humidity
use_outdoor_temp_sensor: true
use_humidity_sensor: true

## 8. Changelog

### Version 1.12.0 (Current)

**Performance & Maintainability Improvements**

- ✅ **Consistency**: Fixed `circadian_hour` default value from 4 to 2 (aligned with specification)
- ✅ **Maintainability**: Broke down monolithic templates into smaller, testable components:
  - `solar_impact_factor` - Simplified solar impact calculation
  - `humidity_feels_adjustment` - Separated humidity adjustment logic
  - `indoor_outdoor_gradient` - Temperature gradient analysis
  - `natural_thermal_trend` - Clean natural trend determination
  - `debug_*` variables - Performance-optimized debug components
- ✅ **Android Performance**: Reduced computational load by pre-calculating complex weather factors
- ✅ **Debug UX**: Cleaner, more readable debug notifications with emoji indicators
- ✅ **Code Quality**: Added performance optimization comments and documentation

### Version 1.11.0 (Previous)

- Original comprehensive weather-aware thermostat control
