#!/usr/bin/env python3
"""Parse every repository blueprint and reject retired HA YAML keys."""
from __future__ import annotations

from pathlib import Path
import re
import sys

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


class Loader(yaml.SafeLoader):
    """Safe loader with Home Assistant's blueprint input tag represented safely."""


Loader.add_constructor(
    "!input", lambda loader, node: {"!input": loader.construct_scalar(node)}
)

# The repository standard is current Home Assistant automation syntax. These are
# YAML keys only, not arbitrary words inside descriptions or template strings.
RETIRED_KEY_PATTERNS = (
    re.compile(r"^(trigger|condition|action):", re.MULTILINE),
    re.compile(r"^\s+platform:", re.MULTILINE),
    re.compile(r"^\s*(?:-\s+)?service:", re.MULTILINE),
    re.compile(r"^\s*data_template:", re.MULTILINE),
)


def strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def main() -> None:
    env = Environment()
    blueprints = sorted(ROOT.glob("*.y*ml"))
    failures: list[str] = []
    template_count = 0

    for path in blueprints:
        text = path.read_text()
        try:
            document = yaml.load(text, Loader=Loader)
            if not isinstance(document, dict) or "blueprint" not in document:
                raise ValueError("expected a blueprint mapping")
            blueprint = document["blueprint"]
            if blueprint.get("domain") not in {"automation", "template", "script"}:
                raise ValueError(f"unsupported blueprint domain: {blueprint.get('domain')!r}")
            for pattern in RETIRED_KEY_PATTERNS:
                if match := pattern.search(text):
                    raise ValueError(
                        f"retired syntax at line {text[:match.start()].count(chr(10)) + 1}: "
                        f"{match.group(0).strip()}"
                    )
            file_templates = 0
            for template in strings(document):
                if "{{" in template or "{%" in template:
                    env.parse(template)
                    file_templates += 1
            template_count += file_templates
            print(f"PASS: {path.name} ({blueprint['domain']}; {file_templates} Jinja scalar(s))")
        except Exception as error:
            failures.append(f"FAIL: {path.name}: {error}")

    print(f"Checked {len(blueprints)} blueprint(s) and {template_count} Jinja scalar(s).")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
