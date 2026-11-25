"""Checks the contract in contract/: run in CI on every pull request and before a release tag.

    uv run --with 'jsonschema>=4.23' python tools/check_contract.py

What it checks (ported from pdi tests/test_contract.py, where the contract lived until 0.14.0):
  1. every *.schema.json is a valid JSON Schema 2020-12;
  2. contract.json has a SemVer version, the shared key pattern and the default prefixes;
  3. every schema except the event schema has an example, and every event type has an example;
  4. every example passes its schema; the story-shape fixtures pass theirs;
  5. every event example, the decision example and the Decision Record example in decision-record.md carry the
     current contract_version, and every schema title ends with it ("… 0.16.0)");
  6. the origin field (0.16.0) has the same shape in the decision and in decision.recorded, with the apps of the
     event source enum; every suite app other than pdi is a value of the decision's source.kind (0.17.0);
  7. applies_to (0.22.0) is the same in the decision and in decision.recorded, and the reference path matcher
     below gives the expected result for every case in fixtures/applies-to/cases.json;
  8. a decision's status is only recorded or superseded (0.23.0: reverted removed — undoing a decision is a new
     decision that supersedes it, decision-record.md §7).
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
    problems += origin_problems()
    problems += reversibility_problems()
    problems += applies_to_problems()
    status = load("decision.schema.json")["properties"]["status"].get("enum")
    if status != ["recorded", "superseded"]:
        problems.append(f"decision.schema.json: status is {status}, expected recorded and superseded (0.23.0)")
    for rel, rel_schema in FIXTURES.items():
        problems += problems_in(rel_schema, load(rel), rel)
    return problems


def origin_problems() -> list[str]:
    """Pole pochodzenia (`origin`, od 0.16.0): ten sam kształt w decyzji i w `decision.recorded`, aplikacje jak w `source`."""
    decision = load("decision.schema.json")["properties"].get("origin")
    event = load("event.schema.json")
    recorded = event["$defs"]["decision_recorded"]["properties"].get("origin")
    if decision is None or recorded is None:
        return ["origin: missing in decision.schema.json or in decision.recorded"]
    problems = []
    if decision != recorded:
        problems.append("origin: decision.schema.json and decision.recorded differ")
    apps = event["properties"]["source"]["enum"]
    if decision.get("properties", {}).get("app", {}).get("enum") != apps:
        problems.append("origin.app: the apps differ from the event source enum")
    kinds = load("decision.schema.json")["properties"]["source"]["properties"]["kind"]["enum"]
    missing = [a for a in apps if a != "pdi" and a not in kinds]
    if missing:
        problems.append(f"decision source.kind: no value for suite apps {', '.join(missing)} (0.17.0)")
    return problems


def reversibility_problems() -> list[str]:
    """Odwracalność i decyzja tymczasowa (0.19.0, N2): to samo w decyzji, w `decision.recorded` i w pytaniach
    (`gate.requested`, `decision.proposed`); decyzja tymczasowa nigdy nie jest `one_way`."""
    decision = load("decision.schema.json")
    defs = load("event.schema.json")["$defs"]
    problems = []
    rev = decision["properties"].get("reversibility")
    if rev is None or "provisional" not in decision["properties"]:
        return ["reversibility: missing in decision.schema.json (0.19.0)"]
    if defs["decision_recorded"]["properties"].get("reversibility") != rev:
        problems.append("reversibility: decision.schema.json and decision.recorded differ")
    if defs["decision_recorded"]["properties"].get("provisional") != decision["properties"]["provisional"]:
        problems.append("provisional: decision.schema.json and decision.recorded differ")
    for name in ("gate_requested", "decision_proposed"):
        fields = defs[name]["properties"]
        if fields.get("reversibility") != rev or not {"closes_at", "default_option", "asked"} <= set(fields):
            problems.append(f"{name}: reversibility, closes_at, default_option or asked missing or different (0.19.0)")
    sample = load("examples/decision.json")
    bad = {**sample, "provisional": True, "reversibility": "one_way"}
    if not problems_in("decision.schema.json", bad, "provisional one_way"):
        problems.append("decision.schema.json: accepts a provisional one_way decision")
    good = {**sample, "provisional": True, "reversibility": "local"}
    problems += problems_in("decision.schema.json", good, "provisional local decision")
    return problems


def _segment(pattern: str) -> re.Pattern[str]:
    """One path segment of an `applies_to` pattern: `*` — any characters but `/`, `?` — one character."""
    return re.compile("".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in pattern) + r"\Z")


def applies_to_match(pattern: str, path: str) -> bool:
    """Reference matcher of `applies_to.paths` (decision-record.md §4a): anchored at the repository root, `**` as a
    whole segment is zero or more segments, and a pattern matching a directory covers every file under it."""
    pat = pattern.split("/")
    parts = path.replace("\\", "/").removeprefix("./").split("/")

    def go(i: int, j: int) -> bool:
        if i == len(pat):
            return True  # the rest of the path lies under the matched directory
        if pat[i] == "**":
            return any(go(i + 1, k) for k in range(j, len(parts) + 1))
        return j < len(parts) and bool(_segment(pat[i]).match(parts[j])) and go(i + 1, j + 1)

    return go(0, 0)


def applies_to_problems() -> list[str]:
    """`applies_to` (0.22.0): the same in the decision and in `decision.recorded`; the fixture cases match as stated;
    the patterns of the cases are valid in the schema and the invalid ones are rejected."""
    decision = load("decision.schema.json")["properties"].get("applies_to")
    recorded = load("event.schema.json")["$defs"]["decision_recorded"]["properties"].get("applies_to")
    if decision is None:
        return ["applies_to: missing in decision.schema.json (0.22.0)"]
    problems = []
    if recorded != decision:
        problems.append("applies_to: decision.schema.json and decision.recorded differ")
    if not (CONTRACT / "fixtures/applies-to/cases.json").exists():
        return [*problems, "fixtures/applies-to/cases.json: missing (0.22.0)"]
    fixture = load("fixtures/applies-to/cases.json")
    sample = load("examples/decision.json")
    for case in fixture["cases"]:
        got = applies_to_match(case["pattern"], case["path"])
        if got != case["match"]:
            problems.append(f"applies-to case {case['pattern']!r} ~ {case['path']!r}: {got}, expected {case['match']}")
    for pattern in sorted({c["pattern"] for c in fixture["cases"]}):
        problems += problems_in("decision.schema.json", {**sample, "applies_to": {"paths": [pattern]}}, pattern)
    for pattern in fixture["invalid_patterns"]:
        if not problems_in("decision.schema.json", {**sample, "applies_to": {"paths": [pattern]}}, pattern):
            problems.append(f"decision.schema.json: accepts the invalid applies_to pattern {pattern!r}")
    if not problems_in("decision.schema.json", {**sample, "applies_to": {}}, "empty applies_to"):
        problems.append("decision.schema.json: accepts an empty applies_to")
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
