#!/usr/bin/env python3
"""Static validation for the occupant-aware ERV blueprints.

This validates portable YAML/blueprint invariants locally. Full Home Assistant
configuration validation still requires importing the blueprints into a running
Home Assistant instance, which this repository deliberately does not access.
"""

from __future__ import annotations

from pathlib import Path
import sys

from jinja2 import Environment, TemplateSyntaxError
import yaml
from yaml.nodes import ScalarNode

ROOT = Path(__file__).resolve().parents[1]
RECOMMENDATION = ROOT / "occupant-aware-erv-recommendation.yaml"
CONTROLLER = ROOT / "occupant-aware-erv-controller.yaml"
DOCS = ROOT / "occupant-aware-erv.md"


class BlueprintLoader(yaml.SafeLoader):
    """Treat Home Assistant blueprint tags as scalar placeholders."""


def _input(loader: BlueprintLoader, node: ScalarNode) -> str:
    return f"!input {loader.construct_scalar(node)}"


BlueprintLoader.add_constructor("!input", _input)


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        # BlueprintLoader subclasses SafeLoader and only adds the scalar !input
        # constructor; it does not enable PyYAML's unsafe Python constructors.
        data = yaml.load(source, Loader=BlueprintLoader)
    if not isinstance(data, dict):
        raise AssertionError(f"{path.name}: expected a top-level mapping")
    return data


def assert_current_automation_syntax(text: str) -> None:
    for forbidden in ("\ntrigger:\n", "\ncondition:\n", "\naction:\n", "\n  - service:"):
        assert forbidden not in text, f"legacy syntax found: {forbidden!r}"


def assert_jinja_syntax(value: object, path: str = "root") -> None:
    """Parse every embedded template; runtime-only HA helpers are not executed."""
    environment = Environment()
    if isinstance(value, dict):
        for key, item in value.items():
            assert_jinja_syntax(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_jinja_syntax(item, f"{path}[{index}]")
    elif isinstance(value, str) and ("{{" in value or "{%" in value):
        try:
            environment.parse(value)
        except TemplateSyntaxError as error:
            raise AssertionError(f"invalid Jinja at {path}: {error}") from error


def main() -> None:
    recommendation = load(RECOMMENDATION)
    controller = load(CONTROLLER)
    recommendation_text = RECOMMENDATION.read_text(encoding="utf-8")
    controller_text = CONTROLLER.read_text(encoding="utf-8")
    docs_text = DOCS.read_text(encoding="utf-8")

    assert recommendation["blueprint"]["domain"] == "template"
    assert controller["blueprint"]["domain"] == "automation"
    assert recommendation["blueprint"]["homeassistant"]["min_version"] == "2025.4.0"
    assert controller["blueprint"]["homeassistant"]["min_version"] == "2025.4.0"
    assert_current_automation_syntax(recommendation_text)
    assert_current_automation_syntax(controller_text)
    assert_jinja_syntax(recommendation, RECOMMENDATION.name)
    assert_jinja_syntax(controller, CONTROLLER.name)

    states = {
        "clean_air_low_demand",
        "pollution_hold",
        "intermittent",
        "ventilation_required",
        "critical",
        "sensor_fault",
    }
    for state in states:
        assert state in recommendation_text, f"missing recommendation state: {state}"

    assert "ns.co2_values | max" in recommendation_text
    assert "co2 >= co2_pollution_override_ppm" in recommendation_text
    assert "co2_overrides_pollution" in recommendation_text
    assert "minutes: \"/5\"" in recommendation_text
    assert "states[entity_id].last_updated" in recommendation_text
    assert "invalid_co2_threshold_order" in recommendation_text
    assert "no_fresh_valid_outdoor_pm25" in recommendation_text

    controller_inputs = controller["blueprint"]["input"]
    live_input = controller_inputs["observability"]["input"]["live_mode"]
    assert live_input["default"] is False
    assert "hold_manual_blocker" in controller_text
    assert "hold_sensor_fault" in controller_text
    assert "suppression_expired" in controller_text
    assert "recommendation_age_seconds | float % maximum_suppression_seconds" in controller_text
    assert "hold_invalid_timing_configuration" in controller_text
    assert "minimum_on_seconds" in controller_text
    assert "minimum_off_seconds" in controller_text
    assert "stored_traces: 20" in controller_text
    assert "action: system_log.write" in controller_text
    assert "states[recommendation_sensor] is not none" in controller_text
    assert "default(false, true) | bool(false)" in controller_text

    turn_on_index = controller_text.index("action: switch.turn_on")
    turn_off_index = controller_text.index("action: switch.turn_off")
    guard_on_index = controller_text.index("live_mode and control_decision == 'turn_on'")
    guard_off_index = controller_text.index("live_mode and control_decision == 'turn_off'")
    assert guard_on_index < turn_on_index
    assert guard_off_index < turn_off_index

    household_entities = (
        "sensor.airgradient_pm2_5",
        "sensor.airgradient_voc_index",
        "sensor.view_plus_carbon_dioxide",
        "sensor.wave_plus_carbon_dioxide",
        "binary_sensor.magic_areas_aggregates_house_aggregate_occupancy",
        "sensor.house_humidity",
        "switch.erv",
    )
    for entity_id in household_entities:
        assert entity_id not in recommendation_text
        assert entity_id not in controller_text
        assert entity_id in docs_text

    print("PASS: YAML parsed with !input support")
    print("PASS: current plural automation/template syntax checks")
    print("PASS: embedded Jinja syntax parsed locally")
    print("PASS: all six recommendation states and CO2-overrides-pollution logic")
    print("PASS: dry-run default guards both ERV service actions")
    print("PASS: household entities appear only in documentation examples")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, TypeError, yaml.YAMLError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
