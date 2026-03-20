# EvalOps Kit

CI-native evals for tool-using agents.

EvalOps Kit gives you a deterministic local workflow to:

- run a suite against dataset + traces (`evalops-kit run`)
- compare candidate vs baseline (`evalops-kit diff`)
- fail CI when regression gates are violated

## Problem this solves

Agent behavior regresses when prompts, tool wiring, model settings, or orchestration change.
Manual spot checks miss issues and are hard to reproduce.

EvalOps Kit makes regressions explicit with stable artifacts:

- `summary.json` for aggregate metrics
- `cases.jsonl` for per-case outcomes and tags
- `report.md` / diff Markdown for humans and CI logs

## Why CI-native evals matter

If evals are not part of CI, they become optional and drift out of release flow.

With EvalOps Kit, you can gate merges on deterministic checks:

- score drops (`overall_avg_drop_max`, `per_grader_avg_drop_max`)
- quality regressions surfaced as top regressed cases
- reliability regressions (`missing_traces_increase_max`, `invalid_traces_increase_max`)

The diff command exits non-zero on gate failure, which is directly usable in GitHub Actions.

## Quickstart (from zero)

Requirements:
- Git
- Python 3.10+

From a fresh machine or shell:

```bash
git clone https://github.com/mireya-o/evalops-kit.git
cd evalops-kit
python3 -m venv .venv
./.venv/bin/python -m pip install -U pip
./.venv/bin/python -m pip install -e .
./.venv/bin/evalops-kit run --suite examples/minimal/suite.toml --out /tmp/evalops-run
./.venv/bin/evalops-kit diff --base /tmp/evalops-run --cand /tmp/evalops-run --suite examples/minimal/suite.toml
```

After `run`, inspect:
- `/tmp/evalops-run/summary.json`
- `/tmp/evalops-run/cases.jsonl`
- `/tmp/evalops-run/report.md`

Important:
- This quickstart is a deterministic sanity check on the bundled minimal fixtures.
- The bundled minimal suite intentionally includes one missing trace, so seeing `traces_missing=1` in the diff output is expected.
- For a true baseline-vs-candidate pass/fail regression demo, run `./.venv/bin/python scripts/demo_golden_path.py`.

If you want contributor tooling as well, use:

```bash
./.venv/bin/python -m pip install -e ".[dev]"
```

## Golden path demo (from a fresh clone)

From the repo root, after the install above:

```bash
./.venv/bin/python scripts/demo_golden_path.py
```

What it does:
1. Runs a baseline from committed fixtures in `examples/golden_path/`.
2. Runs a no-regression candidate and verifies `diff` exits `0`.
3. Runs a regressed candidate and verifies `diff` exits non-zero.
4. Writes pass/fail diff reports and prints their paths.

The script exits `0` only when both expected behaviors are observed.

## Diff + gates

Basic usage:

```bash
evalops-kit diff \
  --base /path/to/baseline-run \
  --cand /path/to/candidate-run \
  --suite examples/golden_path/suite_baseline.toml \
  --out /tmp/evalops-diff.md
```

Behavior:

- writes Markdown diff report (`--out` optional; otherwise stdout)
- returns `0` when all configured gates pass
- returns `2` when one or more gates fail

Supported gate kinds in suite TOML:

- `overall_avg_drop_max`
- `per_grader_avg_drop_max`
- `missing_traces_increase_max`
- `invalid_traces_increase_max`

## GitHub Actions workflow template

A copy-paste-ready template is provided at:

- `examples/github_actions/regression-check.yml`

Copy it into `.github/workflows/` in your repo, then adapt the suite paths and candidate trace generation step.

## OpenAI Agents SDK integration (optional)

Install optional adapter dependencies:

```bash
python -m pip install -e ".[agents]"
```

Minimal integration:

```python
from pathlib import Path

from agents import RunConfig, Runner
from evalops_kit.adapters.openai_agents import (
    EvalOpsAgentsCollector,
    get_processor,
    install_agents_processor,
)

collector = EvalOpsAgentsCollector(Path("traces"))
processor = get_processor(collector=collector)
install_agents_processor(processor, replace_existing=True)

case_id = "case-1"
result = Runner.run_sync(
    agent,
    "Say hello.",
    run_config=RunConfig(trace_metadata={"case_id": case_id}, workflow_name="evalops"),
)
collector.set_final_output(case_id, str(result.final_output))
```

Use `replace_existing=True` when EvalOps should be the only trace exporter.
See `examples/openai_agents/README.md` for a complete usage note.

## Repository structure

```text
src/evalops_kit/            Core package (CLI, run/diff pipeline, suite parsing, graders)
tests/                      Deterministic unit/integration tests
examples/minimal/           Small starter suite + fixtures
examples/golden_path/       Baseline/regression fixtures for end-to-end demo
examples/github_actions/    Workflow templates (not auto-triggered in this repo)
scripts/demo_golden_path.py Portable Python demo runner
```

## Roadmap (short)

- Add more deterministic graders and richer failure tags.
- Add more trace adapters behind optional extras.
- Stabilize artifact schema/versioning for long-term CI compatibility.
- Add migration guidance and release automation for public adoption.

## Development checks

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest
```
