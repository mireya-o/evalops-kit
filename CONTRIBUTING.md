# Contributing

Thanks for contributing to EvalOps Kit.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Run checks

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest
```

## Run the demo

```bash
python scripts/demo_golden_path.py
```

## Contribution guidelines

- Keep changes small and reviewable.
- Add deterministic tests for any functional behavior change.
- Update docs/examples when behavior or workflows change.
- Avoid introducing network dependencies in tests.
- Preserve stable artifact formats unless a change is intentional and documented.
