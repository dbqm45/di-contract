"""Checks the suite manifest suite.yaml against the contract; with --live also against the product repositories.

    uv run --with 'pyyaml>=6' python tools/check_suite.py          # offline (CI)
    uv run --with 'pyyaml>=6' python tools/check_suite.py --live   # + GitHub (gh CLI)

Offline:
  1. the manifest has the expected shape (ids unique, SemVer versions, known pin and version kinds);
  2. suite.contract equals contract/contract.json, and contract_compatible_from is a released version not after it;
  3. every product's contract pin is a released contract version inside [contract_compatible_from, contract];
  4. every link joins known products, names event types of contract/event.schema.json and files of contract/,
     and both ends of an event link pin the contract.
Products pinned behind the current contract are listed as a note, not an error (the range says they still fit).
--live reads each product's pin and version from its repository's default branch through `gh api` and lists every
difference with the manifest. Exit code: 0 — consistent, 1 — a problem (each one listed).
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contract"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
PIN_KINDS = {"json-version", "json-sets-max", "schema-filename"}
VERSION_KINDS = {"pyproject", "package-json", "tag"}
REPO = re.compile(r"^[\w.-]+/[\w.-]+$")


def semver(v: str) -> tuple[int, int, int]:
    a, b, c = (int(x) for x in v.split("."))
    return a, b, c


def released_versions() -> set[str]:
    """The current version and every version named in the history line of contract/README.md ("0.x.y — …")."""
    readme = (CONTRACT / "README.md").read_text(encoding="utf-8")
    found = set(re.findall(r"(\d+\.\d+\.\d+) —", readme))
    found.add(json.loads((CONTRACT / "contract.json").read_text(encoding="utf-8"))["version"])
    return found


def load(path: Path = ROOT / "suite.yaml") -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("suite.yaml: not a mapping")
    # YAML reads 2026-11-22 as a date; keep it as text.
    if "suite" in data and isinstance(data["suite"], dict) and "date" in data["suite"]:
        data["suite"]["date"] = str(data["suite"]["date"])
    return data


def check(m: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(problems, notes) for the manifest `m`."""
    problems: list[str] = []
    notes: list[str] = []
    suite = m.get("suite") or {}
    products = m.get("products") or []
    links = m.get("links") or []
    for key in ("release", "date", "contract", "contract_compatible_from"):
        if not str(suite.get(key, "")).strip():
            problems.append(f"suite.{key}: missing")
    current = str(suite.get("contract", ""))
    floor = str(suite.get("contract_compatible_from", ""))
    actual = json.loads((CONTRACT / "contract.json").read_text(encoding="utf-8"))["version"]
    released = released_versions()
    if current != actual:
        problems.append(f"suite.contract is {current}, contract/contract.json is {actual}")
    if not SEMVER.match(floor) or floor not in released:
        problems.append(f"suite.contract_compatible_from {floor!r} is not a released contract version")
    elif SEMVER.match(current) and semver(floor) > semver(current):
        problems.append(f"suite.contract_compatible_from {floor} is after suite.contract {current}")

    ids: dict[str, dict[str, Any]] = {}
    for i, p in enumerate(products):
        pid = str(p.get("id", ""))
        where = f"products[{i}] {pid or '?'}"
        if not re.fullmatch(r"[a-z][a-z0-9-]*", pid):
            problems.append(f"{where}: id must be lower-case letters, digits and '-'")
        if pid in ids:
            problems.append(f"{where}: duplicate id")
        ids[pid] = p
        if not str(p.get("name", "")).strip():
            problems.append(f"{where}: name missing")
        if not REPO.match(str(p.get("repo", ""))):
            problems.append(f"{where}: repo must be owner/name")
        if not SEMVER.match(str(p.get("version", ""))):
            problems.append(f"{where}: version is not X.Y.Z")
        vs = p.get("version_source") or {}
        if vs.get("kind") not in VERSION_KINDS:
            problems.append(f"{where}: version_source.kind must be one of {sorted(VERSION_KINDS)}")
        elif vs["kind"] != "tag" and not vs.get("file"):
            problems.append(f"{where}: version_source.file missing")
        pin, pinned = p.get("pin"), p.get("contract")
        if (pin is None) != (pinned is None):
            problems.append(f"{where}: contract and pin go together")
        if pin is not None:
            if pin.get("kind") not in PIN_KINDS or not pin.get("file"):
                problems.append(f"{where}: pin needs file and kind ({', '.join(sorted(PIN_KINDS))})")
            v = str(pinned)
            if not SEMVER.match(v) or v not in released:
                problems.append(f"{where}: contract {v} is not a released contract version")
            elif SEMVER.match(floor) and SEMVER.match(current) and not semver(floor) <= semver(v) <= semver(current):
                problems.append(f"{where}: contract {v} is outside [{floor}, {current}]")
            elif v != current:
                notes.append(f"{pid} pins {v}, behind the current {current}")

    schema = json.loads((CONTRACT / "event.schema.json").read_text(encoding="utf-8"))
    event_types = set(schema["properties"]["type"]["enum"])
    for i, link in enumerate(links):
        where = f"links[{i}] {link.get('from')} → {link.get('to')}"
        for end in ("from", "to"):
            if link.get(end) not in ids:
                problems.append(f"{where}: unknown product {link.get(end)!r}")
        events, files = link.get("events") or [], link.get("files") or []
        if not events and not files:
            problems.append(f"{where}: names neither events nor files")
        for e in events:
            if e not in event_types:
                problems.append(f"{where}: {e} is not an event type of the contract")
        for f in files:
            if not (CONTRACT / f).is_file():
                problems.append(f"{where}: contract/{f} does not exist")
        if events:
            for end in ("from", "to"):
                p = ids.get(link.get(end, ""))
                if p is not None and p.get("contract") is None:
                    problems.append(f"{where}: {p['id']} exchanges contract events but pins no contract")
    return problems, notes


# --- live: the repositories' default branches through `gh api` ---


def gh(path: str) -> Any:
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60, check=False)
    if r.returncode != 0:
        raise LookupError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"gh api {path} failed")
    return json.loads(r.stdout)


def file_text(repo: str, path: str) -> str:
    return base64.b64decode(gh(f"repos/{repo}/contents/{path}")["content"]).decode("utf-8")


def live_pin(repo: str, pin: dict[str, str]) -> str:
    kind, path = pin["kind"], pin["file"]
    if kind == "json-version":
        return str(json.loads(file_text(repo, path))["version"])
    if kind == "json-sets-max":
        sets = json.loads(file_text(repo, path))["sets"]
        return max((str(s["version"]) for s in sets), key=semver)
    names = [str(x["name"]) for x in gh(f"repos/{repo}/contents/{path}")]
    found = {m.group(1) for n in names if (m := re.fullmatch(r"event\.v(\d+\.\d+\.\d+)\.schema\.json", n))}
    if not found:
        raise LookupError(f"no event.v<version>.schema.json in {path}")
    return max(found, key=semver)


def live_version(repo: str, source: dict[str, str]) -> str:
    kind = source["kind"]
    if kind == "pyproject":
        return str(tomllib.loads(file_text(repo, source["file"]))["project"]["version"])
    if kind == "package-json":
        return str(json.loads(file_text(repo, source["file"]))["version"])
    tags = [str(t["name"]) for t in gh(f"repos/{repo}/tags?per_page=100")]
    versions = [t[1:] for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+", t)]
    if not versions:
        raise LookupError("no vX.Y.Z tag")
    return max(versions, key=semver)


def check_live(m: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for p in m.get("products") or []:
        try:
            got = live_version(p["repo"], p["version_source"])
            if got != p["version"]:
                problems.append(f"{p['id']}: version {p['version']} in suite.yaml, {got} in {p['repo']}")
            if p.get("pin"):
                pinned = live_pin(p["repo"], p["pin"])
                if pinned != p["contract"]:
                    problems.append(f"{p['id']}: contract {p['contract']} in suite.yaml, {pinned} in {p['repo']}")
        except (LookupError, KeyError, ValueError, OSError, subprocess.SubprocessError) as e:
            problems.append(f"{p['id']}: could not read {p['repo']} ({type(e).__name__}: {e})")
    return problems


def main(argv: list[str] | None = None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--live", action="store_true", help="also compare with the product repositories (gh CLI)")
    args = a.parse_args(argv)
    m = load()
    problems, notes = check(m)
    if args.live and not problems:
        problems += check_live(m)
    release = (m.get("suite") or {}).get("release")
    if problems:
        print(f"✗ suite {release}: {len(problems)} problem(s)")
        for line in problems:
            print(f"  - {line}")
        return 1
    print(f"✓ suite {release}: {len(m.get('products') or [])} products consistent with contract {m['suite']['contract']}"
          + (" and with their repositories" if args.live else ""))
    for line in notes:
        print(f"  · {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
