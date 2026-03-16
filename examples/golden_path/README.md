# Golden Path Assets

These fixtures drive the end-to-end demo in `scripts/demo_golden_path.py`.

## Contents

- `dataset.jsonl`: shared dataset used by all runs.
- `suite_baseline.toml`: suite pointing at `traces_baseline/`.
- `suite_regression.toml`: suite pointing at `traces_regression/`.
- `traces_baseline/`: expected-good traces.
- `traces_regression/`: one intentionally regressed trace (`case-1`).

## Expected outcomes

- Baseline vs baseline candidate: all gates pass, `evalops-kit diff` exits `0`.
- Baseline vs regression candidate: score-drop gates fail, `evalops-kit diff` exits non-zero.
