# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.1.0] - 2026-03-07

### Added
- Initial package scaffold with the `evalops-kit` CLI.
- `run` pipeline producing `summary.json`, `cases.jsonl`, and `report.md`.
- Suite parser (TOML), dataset loader (JSONL), and trace validator.
- Deterministic graders: `rule_regex` and `trace_tool_policy`.
- `diff` pipeline with regression gate evaluation and Markdown reporting.
- Optional OpenAI Agents SDK trace adapter.
- Minimal example suite and deterministic tests.
- Deterministic golden-path demo fixtures under `examples/golden_path/`.
- Portable demo runner `scripts/demo_golden_path.py` validating both pass and fail regression behavior.
- Copy-paste-ready GitHub Actions workflow template under `examples/github_actions/regression-check.yml`.

### Changed
- Reworked `README.md` into a product-oriented guide with quickstart, golden path, diff/gates usage, CI template, and roadmap.
