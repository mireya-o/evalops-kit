from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from evalops_kit.cli import main
from evalops_kit.dataset import load_dataset
from evalops_kit.errors import DatasetLoadError, SuiteConfigError
from evalops_kit.suite import (
    InvalidTracesIncreaseMaxGateConfig,
    MissingTracesIncreaseMaxGateConfig,
    OverallAvgDropMaxGateConfig,
    PerGraderAvgDropMaxGateConfig,
    RuleRegexGraderConfig,
    TraceToolPolicyGraderConfig,
    load_suite,
)

HAS_TOMLLIB = importlib.util.find_spec("tomllib") is not None


def test_dataset_loader_reports_invalid_json_with_file_and_line(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text(
        '{"id":"case-1","input":{"prompt":"ok"}}\n{"id":"case-2","input":\n',
        encoding="utf-8",
    )

    with pytest.raises(DatasetLoadError) as exc:
        load_dataset(dataset_path)

    message = str(exc.value)
    assert str(dataset_path) in message
    assert "line 2" in message


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            'version = "0.1"\nname = "demo"\n',
            "missing required key 'dataset'",
        ),
        (
            'version = 1\nname = "demo"\ndataset = "dataset.jsonl"\n',
            "key 'version' must be a string",
        ),
    ],
)
@pytest.mark.skipif(not HAS_TOMLLIB, reason="tomllib is unavailable on this Python version")
def test_suite_parser_validates_required_keys_and_types(
    tmp_path: Path, content: str, expected: str
) -> None:
    suite_path = tmp_path / "suite.toml"
    suite_path.write_text(content, encoding="utf-8")

    with pytest.raises(SuiteConfigError) as exc:
        load_suite(suite_path)

    assert expected in str(exc.value)


@pytest.mark.skipif(not HAS_TOMLLIB, reason="tomllib is unavailable on this Python version")
def test_suite_parser_parses_graders_section(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.toml"
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text('{"id":"case-1","input":{"prompt":"x"}}\n', encoding="utf-8")
    suite_path.write_text(
        "\n".join(
            [
                'version = "0.1"',
                'name = "demo"',
                'dataset = "dataset.jsonl"',
                "",
                "[[graders]]",
                'name = "regex_check"',
                'kind = "rule_regex"',
                'pattern = "ok"',
                'flags = "im"',
                "",
                "[[graders]]",
                'name = "tool_check"',
                'kind = "trace_tool_policy"',
                'require_tools = ["search"]',
                "",
                "[[gates]]",
                'kind = "overall_avg_drop_max"',
                "max_drop = 0.1",
                "",
                "[[gates]]",
                'kind = "per_grader_avg_drop_max"',
                'grader = "regex_check"',
                "max_drop = 0.2",
                "",
                "[[gates]]",
                'kind = "missing_traces_increase_max"',
                "max_increase = 1",
                "",
                "[[gates]]",
                'kind = "invalid_traces_increase_max"',
                "max_increase = 2",
            ]
        ),
        encoding="utf-8",
    )

    suite = load_suite(suite_path)
    assert len(suite.graders) == 2
    assert len(suite.gates) == 4

    regex_grader = suite.graders[0]
    assert isinstance(regex_grader, RuleRegexGraderConfig)
    assert regex_grader.name == "regex_check"
    assert regex_grader.pattern == "ok"
    assert regex_grader.must_match is True
    assert regex_grader.flags == "im"
    assert regex_grader.weight == 1.0

    tool_grader = suite.graders[1]
    assert isinstance(tool_grader, TraceToolPolicyGraderConfig)
    assert tool_grader.name == "tool_check"
    assert tool_grader.require_tools == ("search",)
    assert tool_grader.forbid_tools == ()
    assert tool_grader.fail_on_tool_error is True

    overall_gate = suite.gates[0]
    assert isinstance(overall_gate, OverallAvgDropMaxGateConfig)
    assert overall_gate.max_drop == 0.1

    per_grader_gate = suite.gates[1]
    assert isinstance(per_grader_gate, PerGraderAvgDropMaxGateConfig)
    assert per_grader_gate.grader == "regex_check"
    assert per_grader_gate.max_drop == 0.2

    missing_gate = suite.gates[2]
    assert isinstance(missing_gate, MissingTracesIncreaseMaxGateConfig)
    assert missing_gate.max_increase == 1

    invalid_gate = suite.gates[3]
    assert isinstance(invalid_gate, InvalidTracesIncreaseMaxGateConfig)
    assert invalid_gate.max_increase == 2


@pytest.mark.skipif(not HAS_TOMLLIB, reason="tomllib is unavailable on this Python version")
def test_suite_parser_rejects_unknown_grader_kind(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.toml"
    suite_path.write_text(
        "\n".join(
            [
                'version = "0.1"',
                'name = "demo"',
                'dataset = "dataset.jsonl"',
                "",
                "[[graders]]",
                'name = "bad"',
                'kind = "unknown_kind"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(SuiteConfigError) as exc:
        load_suite(suite_path)

    assert "graders[0].kind must be one of" in str(exc.value)


@pytest.mark.skipif(not HAS_TOMLLIB, reason="tomllib is unavailable on this Python version")
def test_run_command_writes_expected_artifacts_for_minimal_example(tmp_path: Path) -> None:
    workspace_root = Path(__file__).resolve().parents[1]
    suite_path = workspace_root / "examples" / "minimal" / "suite.toml"
    out_dir = tmp_path / "run-artifacts"

    exit_code = main(["run", "--suite", str(suite_path), "--out", str(out_dir)])
    assert exit_code == 0

    summary_path = out_dir / "summary.json"
    cases_path = out_dir / "cases.jsonl"
    report_path = out_dir / "report.md"
    assert summary_path.exists()
    assert cases_path.exists()
    assert report_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["suite"] == {"name": "minimal-suite", "version": "0.1"}
    assert summary["counts"] == {
        "total_cases": 3,
        "traces_found": 2,
        "traces_missing": 1,
        "traces_invalid": 0,
    }
    assert summary["metrics"] == {
        "overall_avg_score": pytest.approx(0.5),
        "per_grader_avg": {
            "final_mentions_hello": pytest.approx(0.5),
            "tool_policy": pytest.approx(0.5),
        },
    }
    assert "created_at" in summary["run"]
    assert "started_at" in summary["run"]
    assert "ended_at" in summary["run"]

    case_rows = [
        json.loads(line)
        for line in cases_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_case = {row["case_id"]: row for row in case_rows}
    assert set(by_case) == {"case-1", "case-2", "case-3"}

    assert by_case["case-1"] == {
        "case_id": "case-1",
        "trace_path": "traces/case-1.json",
        "tags": [],
        "scores": {
            "final_mentions_hello": 1.0,
            "tool_policy": 1.0,
        },
        "final_score": 1.0,
    }
    assert by_case["case-2"]["trace_path"] == "traces/case-2.json"
    assert by_case["case-2"]["scores"] == {
        "final_mentions_hello": 0.0,
        "tool_policy": 0.0,
    }
    assert by_case["case-2"]["final_score"] == 0.0
    assert set(by_case["case-2"]["tags"]) == {
        "rule_regex_no_match:final_mentions_hello",
        "missing_required_tools:lookup",
        "used_forbidden_tool:shell",
    }
    assert by_case["case-3"] == {
        "case_id": "case-3",
        "trace_path": None,
        "tags": ["missing_trace"],
        "scores": {},
        "final_score": None,
    }

    report = report_path.read_text(encoding="utf-8")
    assert "Suite: **minimal-suite**" in report
    assert "Worst cases (2)" in report
    assert "used_forbidden_tool:shell" in report
    assert "rule_regex_no_match:final_mentions_hello" in report
    assert "Missing traces (1)" in report
    assert "`case-3`" in report


@pytest.mark.skipif(not HAS_TOMLLIB, reason="tomllib is unavailable on this Python version")
def test_run_marks_tool_error_as_zero_score_when_fail_on_tool_error_enabled(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.jsonl"
    traces_dir = tmp_path / "traces"
    suite_path = tmp_path / "suite.toml"
    out_dir = tmp_path / "run-artifacts"

    traces_dir.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text('{"id":"case-1","input":{"prompt":"hello"}}\n', encoding="utf-8")
    (traces_dir / "case-1.json").write_text(
        json.dumps(
            {
                "case_id": "case-1",
                "events": [
                    {"type": "tool_call", "name": "lookup", "input": {"q": "hello"}},
                    {"type": "tool_error", "name": "lookup", "error": {"message": "boom"}},
                ],
                "final": {"text": "fallback"},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    suite_path.write_text(
        "\n".join(
            [
                'version = "0.1"',
                'name = "tool-error-suite"',
                'dataset = "dataset.jsonl"',
                'traces_dir = "traces"',
                "",
                "[[graders]]",
                'name = "tool_policy"',
                'kind = "trace_tool_policy"',
                "fail_on_tool_error = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", "--suite", str(suite_path), "--out", str(out_dir)])
    assert exit_code == 0

    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["metrics"]["overall_avg_score"] == pytest.approx(0.0)
    assert summary["metrics"]["per_grader_avg"]["tool_policy"] == pytest.approx(0.0)

    case_rows = [
        json.loads(line)
        for line in (out_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(case_rows) == 1
    assert case_rows[0]["scores"]["tool_policy"] == 0.0
    assert case_rows[0]["tags"] == ["tool_error"]
    assert case_rows[0]["final_score"] == 0.0
