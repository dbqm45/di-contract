# CLAUDE.md

This repository is the shared contract of Delivery Intelligence Suite (see `README.md`). It holds data, not code:
JSON schemas, examples and fixtures in `contract/`, and check scripts in `tools/` (`check_contract.py`, `check_suite.py` for `suite.yaml`).

- Edit schemas only here; never in a consumer's pinned copy.
- Any change to `contract/` other than `contract/README.md` needs a new version in `contract/contract.json`
  (SemVer; in 0.x a backward-incompatible change raises the second number), a line in the history at the top of
  `contract/README.md`, and updated examples (event examples carry the current `contract_version`).
- Run `uv run --with 'jsonschema>=4.23' python tools/check_contract.py` before committing; CI runs the same.
- `suite.yaml` (outside `contract/`, no contract version needed) says which product versions and contract pins form
  a suite release; check it with `uv run --with 'pyyaml>=6' python tools/check_suite.py` (`--live` compares with the
  product repositories) and keep it in step after a product release or a pin change.
- Never move or delete a `contract-v*` tag; `contract-release.yml` creates them on `main`.
- Commits and pull request titles: Conventional Commits in English, imperative, no trailing period, at most 72
  characters. Work on a branch and open a pull request to `main`.
- `contract/README.md` and `contract/decision-record.md` are in Polish, like the rest of the suite's design documents.
