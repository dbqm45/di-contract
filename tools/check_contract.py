"""Checks the contract in contract/: run in CI on every pull request and before a release tag.

    uv run --with 'jsonschema>=4.23' python tools/check_contract.py

What it checks (ported from pdi tests/test_contract.py, where the contract lived until 0.14.0):
  1. every *.schema.json is a valid JSON Schema 2020-12;
  2. contract.json has a SemVer version, the shared key pattern and the default prefixes;
  3. every schema except the event schema has an example, and every event type has an example;
  4. every example passes its schema; the story-shape fixtures pass theirs;
  5. every event example, the decision example and the Decision Record example in decision-record.md carry the
     current contract_version, and every schema title ends with it ("… 0.15.1)").
Exit code: 0 — consistent, 1 — a problem (each one listed). Prints nothing from the files beyond names and paths.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

CONTRACT = Path(__file__).resolve().parents[1] / "contract"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
KEY_PATTERN = "^[A-Z][A-Z0-9]+-[0-9]+$"
PREFIXES = {"problem": "PRB", "change": "CHG", "task": "TSK", "decision": "DEC"}
FIXTURES = {
    "fixtures/story-shape/stories.json": "fixtures/story-shape/stories.schema.json",
    "fixtures/story-shape/expected.json": "fixtures/story-shape/expected.schema.json",
}


def load(rel: str | Path) -> Any:
    return json.loads((CONTRACT / rel).read_text(encoding="utf-8"))


def schema_for(example: Path) -> str:
    """The schema file of an example: event-*.json → event, release-plan*.json → release-plan, else by name."""
    if example.stem.startswith("event-"):
        return "event.schema.json"
    if example.stem.startswith("release-plan"):
        return "release-plan.schema.json"
    return f"{example.stem}.schema.json"


def problems_in(rel_schema: str, data: Any, where: str) -> list[str]:
    validator = Draft202012Validator(load(rel_schema), format_checker=Draft202012Validator.FORMAT_CHECKER)
    found = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    return [f"{where}: {'.'.join(map(str, e.absolute_path)) or '(root)'}: {e.validator}" for e in found]


def check() -> list[str]:
    problems: list[str] = []
    schemas = sorted(p.name for p in CONTRACT.glob("*.schema.json"))
    for name in schemas:
        try:
            Draft202012Validator.check_schema(load(name))
        except Exception as e:  # noqa: BLE001 — any reason makes the schema unusable
            problems.append(f"{name}: not a valid JSON Schema 2020-12 ({type(e).__name__})")

    settings = load("contract.json")
    version = settings.get("version", "")
    if not SEMVER.match(str(version)):
        problems.append(f"contract.json: version is not X.Y.Z ({version!r})")
    if settings.get("key_pattern") != KEY_PATTERN:
        problems.append("contract.json: key_pattern is not the shared key pattern")
    if settings.get("prefixes") != PREFIXES:
        problems.append("contract.json: prefixes differ from the defaults PRB, CHG, TSK, DEC")

    examples = sorted((CONTRACT / "examples").glob("*.json"))
    covered = {schema_for(p) for p in examples if not p.stem.startswith("event-")}
    for name in sorted(set(schemas) - {"event.schema.json"} - covered):
        problems.append(f"{name}: no example in examples/")
    event_types = load("event.schema.json")["properties"]["type"]["enum"]
    stems = {p.stem for p in examples}
    for t in event_types:
        if f"event-{t}" not in stems:
            problems.append(f"event type {t}: no example examples/event-{t}.json")

    for p in examples:
        rel_schema = schema_for(p)
        if not (CONTRACT / rel_schema).exists():
            problems.append(f"examples/{p.name}: no schema {rel_schema}")
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        problems += problems_in(rel_schema, data, f"examples/{p.name}")
        if p.stem.startswith("event-") and data.get("contract_version") != version:
            problems.append(f"examples/{p.name}: contract_version is not {version}")
    if load("examples/decision.json").get("contract_version") != version:
        problems.append(f"examples/decision.json: contract_version is not {version}")
    for name in schemas:
        if not str(load(name).get("title", "")).endswith(f" {version})"):
            problems.append(f"{name}: the title does not end with the current version ({version})")
    spec = (CONTRACT / "decision-record.md").read_text(encoding="utf-8")
    found = re.findall(r"^contract_version: (\S+)$", spec, flags=re.M)
    if found != [version]:
        problems.append(f"decision-record.md: the example's contract_version is {found or 'missing'}, not {version}")
    for rel, rel_schema in FIXTURES.items():
        problems += problems_in(rel_schema, load(rel), rel)
    return problems


def main() -> int:
    problems = check()
    if problems:
        print(f"✗ contract {load('contract.json').get('version')}: {len(problems)} problem(s)")
        for line in problems:
            print(f"  - {line}")
        return 1
    print(f"✓ contract {load('contract.json')['version']}: schemas, examples and fixtures are consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
