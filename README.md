# di-contract

The shared contract of Delivery Intelligence Suite: the JSON schemas, examples and conventions that every
suite app uses to exchange objects and events (decision, problem, change, task, story, release plan, autonomy
policy, triage recommendation, reconstruction, design links, and the event envelope with one payload per event
type). The detailed description, in Polish, is in [`contract/README.md`](contract/README.md); the Decision Record
file format is in [`contract/decision-record.md`](contract/decision-record.md).

Current version: **0.15.0** (`contract/contract.json`).

## Where it came from

Until 0.14.0 the contract lived in `contract/` of [dbqm45/pdi](https://github.com/dbqm45/pdi) (DI Decision) and was
released there as tags `contract-v<version>`. It was moved here on 2026-11-22 (decision D-P3; step 6 of
`pdi/docs/plan-budowy-suity.md`) because the suite now has more consumers than pdi, tf, ci_for_sdlc and ShipScope.
The files are a copy of pdi `contract/` at commit `eeb37ff`; only links to pdi's documents were turned into full
GitHub links. History before the move stays in pdi. The schemas, examples and fixtures are byte-for-byte those of
pdi's tag `contract-v0.14.0`; `decision-record.md` was added in pdi after that tag (a document, not a schema).

The directory layout is kept on purpose: consumers fetch `contract/<file>` from a tag, so moving to this repository
changes only the `repo` in their pin files.

## Rules

- **One source.** Schemas are edited only here. Consumers keep generated, pinned copies and never edit them by hand;
  their CI checks the copies byte for byte against the tag.
- **SemVer.** A backward-incompatible change raises the major version (in 0.x, the second number). Every change to
  `contract/` other than `contract/README.md` needs a new version in `contract/contract.json`.
- **Releases.** When a change to `contract/` reaches `main`, `contract-release.yml` checks the contract and creates the
  tag `contract-v<version>`. A tag never moves; if it exists and the files changed, the workflow fails.
- **Checks.** `uv run --with 'jsonschema>=4.23' python tools/check_contract.py` — every schema is valid JSON Schema
  2020-12, every schema and event type has an example, every example passes its schema, event examples carry the
  current version. CI runs it on every push and pull request.

## Consumers

| App | Pin file | Pinned version (2026-11-22) |
|---|---|---|
| DI Decision (pdi) | `contract/` (the former source; becomes a pinned copy) | 0.14.0 |
| DI Agent Factory (tf) | `tools/pdi-contract.json` | 0.14.0 |
| DI Definition (ci_for_sdlc) | `scripts/pdi-contract.json` | sets 0.4.0 … 0.14.0 |
| DI Release (evdt-service-shipscope) | `server/schemas/*.v0.14.0.schema.json` | 0.14.0 |

Each consumer switches its pin from `dbqm45/pdi` to `dbqm45/di-contract` in its own pull request (step 7 of the
plan). Until pdi's switch is merged, contract changes must not be made in pdi.

Planned next: a suite manifest (`suite.yaml`) that names which product versions and which contract version form a
suite release (step 14a).
