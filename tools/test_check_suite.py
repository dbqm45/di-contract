"""Tests of tools/check_suite.py: the manifest goes red with a useful message.

    uv run --with 'pyyaml>=6' --with pytest python -m pytest -q tools/test_check_suite.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_suite

BASE = check_suite.load()


def problems(change) -> list[str]:  # type: ignore[no-untyped-def]
    m: dict[str, Any] = copy.deepcopy(BASE)
    change(m)
    return check_suite.check(m)[0]


def product(m: dict[str, Any], pid: str) -> dict[str, Any]:
    return next(p for p in m["products"] if p["id"] == pid)


def test_s01_the_manifest_in_the_repo_is_consistent() -> None:
    found, notes = check_suite.check(copy.deepcopy(BASE))
    assert found == []
    assert all("behind the current" in n for n in notes)


def test_s02_suite_contract_must_equal_contract_json() -> None:
    assert any("contract/contract.json" in p for p in problems(lambda m: m["suite"].update(contract="0.14.0")))


def test_s03_a_pin_outside_the_compatible_range_or_unreleased_is_an_error() -> None:
    assert any("outside" in p for p in problems(lambda m: product(m, "di-release").update(contract="0.3.0")))
    assert any("not a released" in p for p in problems(lambda m: product(m, "di-release").update(contract="0.15.9")))


def test_s04_links_must_name_known_products_events_and_files() -> None:
    assert any("unknown product" in p for p in problems(lambda m: m["links"][0].update(to="di-nothing")))
    assert any("not an event type" in p for p in problems(lambda m: m["links"][0].update(events=["gate.nope"])))
    assert any("does not exist" in p for p in problems(lambda m: m["links"][-1].update(files=["nope.schema.json"])))


def test_s05_an_event_link_needs_a_pinned_contract_on_both_ends() -> None:
    def unpin(m: dict[str, Any]) -> None:
        p = product(m, "di-definition")
        p.pop("contract")
        p.pop("pin")

    assert any("pins no contract" in p for p in problems(unpin))


def test_s06_shape_errors_name_the_field() -> None:
    assert any("duplicate id" in p for p in problems(lambda m: m["products"].append(copy.deepcopy(m["products"][0]))))
    assert any("version is not" in p for p in problems(lambda m: product(m, "di-channels").update(version="1.0")))
    assert any("go together" in p for p in problems(lambda m: product(m, "di-decision").pop("pin")))
