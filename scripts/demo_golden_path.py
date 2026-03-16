#!/usr/bin/env python3
"""Deterministic golden-path demo for EvalOps Kit."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = WORKSPACE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@dataclass(frozen=True)
class DemoRunResult:
    output_root: Path
    baseline_out: Path
    pass_out: Path
    fail_out: Path
    pass_report: Path
    fail_report: Path
    pass_diff_exit: int
    fail_diff_exit: int
    success: bool
    checks: tuple[str, ...]


def run_demo(workspace_root: Path, output_root: Path) -> DemoRunResult:
    assets_root = workspace_root / "examples" / "golden_path"
    baseline_suite = assets_root / "suite_baseline.toml"
    regression_suite = assets_root / "suite_regression.toml"

    baseline_out = output_root / "baseline-run"
    pass_out = output_root / "candidate-pass-run"
    fail_out = output_root / "candidate-fail-run"
    pass_report = output_root / "diff-pass.md"
    fail_report = output_root / "diff-fail.md"

    output_root.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []
    pass_diff_exit = -1
    fail_diff_exit = -1

    required_paths = (baseline_suite, regression_suite)
    missing_paths = [path for path in required_paths if not path.exists()]
    if missing_paths:
        for path in missing_paths:
            checks.append(f"Missing required demo asset: {path}")
        return DemoRunResult(
            output_root=output_root,
            baseline_out=baseline_out,
            pass_out=pass_out,
            fail_out=fail_out,
            pass_report=pass_report,
            fail_report=fail_report,
            pass_diff_exit=pass_diff_exit,
            fail_diff_exit=fail_diff_exit,
            success=False,
            checks=tuple(checks),
        )

    baseline_run_exit = _run_cli(
        ["run", "--suite", str(baseline_suite), "--out", str(baseline_out)]
    )
    if baseline_run_exit != 0:
        checks.append(f"Baseline run failed with exit code {baseline_run_exit}.")

    pass_run_exit = _run_cli(["run", "--suite", str(baseline_suite), "--out", str(pass_out)])
    if pass_run_exit != 0:
        checks.append(f"Pass-candidate run failed with exit code {pass_run_exit}.")

    pass_diff_exit = _run_cli(
        [
            "diff",
            "--base",
            str(baseline_out),
            "--cand",
            str(pass_out),
            "--suite",
            str(baseline_suite),
            "--out",
            str(pass_report),
        ]
    )
    if pass_diff_exit != 0:
        checks.append(f"Pass diff expected exit code 0, got {pass_diff_exit}.")

    fail_run_exit = _run_cli(["run", "--suite", str(regression_suite), "--out", str(fail_out)])
    if fail_run_exit != 0:
        checks.append(f"Fail-candidate run failed with exit code {fail_run_exit}.")

    fail_diff_exit = _run_cli(
        [
            "diff",
            "--base",
            str(baseline_out),
            "--cand",
            str(fail_out),
            "--suite",
            str(baseline_suite),
            "--out",
            str(fail_report),
        ]
    )
    if fail_diff_exit == 0:
        checks.append("Fail diff expected non-zero exit code, got 0.")

    pass_report_text = _read_text_or_none(pass_report)
    if pass_report_text is None:
        checks.append(f"Pass diff report was not created: {pass_report}")
    else:
        if "FAIL `" in pass_report_text:
            checks.append("Pass diff report unexpectedly contains failing gates.")
        if "PASS `overall_avg_drop_max`" not in pass_report_text:
            checks.append("Pass diff report does not show expected passing overall gate.")

    fail_report_text = _read_text_or_none(fail_report)
    if fail_report_text is None:
        checks.append(f"Fail diff report was not created: {fail_report}")
    else:
        if "FAIL `overall_avg_drop_max`" not in fail_report_text:
            checks.append("Fail diff report does not show failing overall drop gate.")
        if "`case-1`" not in fail_report_text:
            checks.append("Fail diff report does not include regressed case `case-1`.")

    success = not checks
    if success:
        checks.append("Observed expected pass/fail behavior.")

    return DemoRunResult(
        output_root=output_root,
        baseline_out=baseline_out,
        pass_out=pass_out,
        fail_out=fail_out,
        pass_report=pass_report,
        fail_report=fail_report,
        pass_diff_exit=pass_diff_exit,
        fail_diff_exit=fail_diff_exit,
        success=success,
        checks=tuple(checks),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="demo_golden_path.py",
        description="Run deterministic baseline/pass/fail regression demo for EvalOps Kit.",
    )
    parser.add_argument(
        "--output-root",
        help=(
            "Optional directory for demo outputs. "
            "Defaults to a new temp directory that is kept for inspection."
        ),
    )
    args = parser.parse_args(argv)

    if args.output_root:
        output_root = Path(args.output_root).resolve()
    else:
        output_root = Path(mkdtemp(prefix="evalops-golden-path-")).resolve()

    result = run_demo(workspace_root=WORKSPACE_ROOT, output_root=output_root)
    _print_result(result)
    return 0 if result.success else 1


def _run_cli(args: list[str]) -> int:
    from evalops_kit.cli import main as evalops_main

    return int(evalops_main(args))


def _read_text_or_none(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _print_result(result: DemoRunResult) -> None:
    print("EvalOps Kit golden path demo")
    print(f"output_root: {result.output_root}")
    print(f"baseline_run: {result.baseline_out}")
    print(f"pass_candidate_run: {result.pass_out}")
    print(f"fail_candidate_run: {result.fail_out}")
    print(f"pass_diff_report: {result.pass_report} (exit={result.pass_diff_exit})")
    print(f"fail_diff_report: {result.fail_report} (exit={result.fail_diff_exit})")
    status = "SUCCESS" if result.success else "FAILURE"
    print(f"status: {status}")
    for check in result.checks:
        print(f"- {check}")


if __name__ == "__main__":
    raise SystemExit(main())
