from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from evalops_kit.cli import main

HAS_TOMLLIB = importlib.util.find_spec("tomllib") is not None


def test_diff_report_includes_expected_sections_without_suite(tmp_path: Path, capsys) -> None:
    base_dir = tmp_path / "base-run"
    cand_dir = tmp_path / "cand-run"
    _write_run(
        base_dir,
        summary={
            "suite": {"name": "demo-suite", "version": "0.1"},
            "counts": {"traces_missing": 0, "traces_invalid": 0},
            "metrics": {
                "overall_avg_score": 0.8,
                "per_grader_avg": {"quality": 0.8, "policy": 1.0},
            },
        },
        cases=[
            {"case_id": "case-1", "final_score": 1.0, "tags": []},
            {"case_id": "case-2", "final_score": 0.7, "tags": []},
            {"case_id": "case-3", "final_score": 0.5, "tags": []},
        ],
    )
    _write_run(
        cand_dir,
        summary={
            "suite": {"name": "demo-suite", "version": "0.1"},
            "counts": {"traces_missing": 1, "traces_invalid": 1},
            "metrics": {
                "overall_avg_score": 0.6,
                "per_grader_avg": {"quality": 0.6, "policy": 1.0},
            },
        },
        cases=[
            {"case_id": "case-1", "final_score": 0.4, "tags": []},
            {"case_id": "case-2", "final_score": None, "tags": ["missing_trace"]},
            {"case_id": "case-3", "final_score": None, "tags": ["invalid_trace"]},
        ],
    )

    exit_code = main(
        [
            "diff",
            "--base",
            str(base_dir / "summary.json"),
            "--cand",
            str(cand_dir),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "# EvalOps Kit Diff Report" in output
    assert "overall_avg_score" in output
    assert "### per_grader_avg" in output
    assert "traces_missing" in output
    assert "traces_invalid" in output
    assert "Top regressions (1)" in output
    assert "`case-1`" in output
    assert "Newly missing traces (1)" in output
    assert "Newly invalid traces (1)" in output
    assert "Not evaluated (no `--suite` provided)." in output


@pytest.mark.skipif(not HAS_TOMLLIB, reason="tomllib is unavailable on this Python version")
def test_diff_gate_failure_returns_non_zero_and_writes_report(tmp_path: Path) -> None:
    base_dir = tmp_path / "base-run"
    cand_dir = tmp_path / "cand-run"
    _write_run(
        base_dir,
        summary={
            "suite": {"name": "demo-suite", "version": "0.1"},
            "counts": {"traces_missing": 0, "traces_invalid": 0},
            "metrics": {
                "overall_avg_score": 0.8,
                "per_grader_avg": {"quality": 0.8},
            },
        },
        cases=[
            {"case_id": "case-1", "final_score": 1.0, "tags": []},
        ],
    )
    _write_run(
        cand_dir,
        summary={
            "suite": {"name": "demo-suite", "version": "0.1"},
            "counts": {"traces_missing": 1, "traces_invalid": 1},
            "metrics": {
                "overall_avg_score": 0.5,
                "per_grader_avg": {"quality": 0.5},
            },
        },
        cases=[
            {"case_id": "case-1", "final_score": 0.2, "tags": ["missing_trace", "invalid_trace"]},
        ],
    )

    suite_path = tmp_path / "suite.toml"
    suite_path.write_text(
        "\n".join(
            [
                'version = "0.1"',
                'name = "demo-suite"',
                'dataset = "dataset.jsonl"',
                "",
                "[[gates]]",
                'kind = "overall_avg_drop_max"',
                "max_drop = 0.0",
                "",
                "[[gates]]",
                'kind = "per_grader_avg_drop_max"',
                'grader = "quality"',
                "max_drop = 0.0",
                "",
                "[[gates]]",
                'kind = "missing_traces_increase_max"',
                "max_increase = 0",
                "",
                "[[gates]]",
                'kind = "invalid_traces_increase_max"',
                "max_increase = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report_path = tmp_path / "diff-report.md"
    exit_code = main(
        [
            "diff",
            "--base",
            str(base_dir),
            "--cand",
            str(cand_dir),
            "--suite",
            str(suite_path),
            "--out",
            str(report_path),
        ]
    )

    assert exit_code != 0
    assert report_path.exists()
    report = report_path.read_text(encoding="utf-8")
    assert "## Gates (4)" in report
    assert "FAIL `overall_avg_drop_max`" in report
    assert "FAIL `per_grader_avg_drop_max`" in report
    assert "FAIL `missing_traces_increase_max`" in report
    assert "FAIL `invalid_traces_increase_max`" in report


def _write_run(run_dir: Path, summary: dict, cases: list[dict]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    with (run_dir / "cases.jsonl").open("w", encoding="utf-8") as handle:
        for row in cases:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")
