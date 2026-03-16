"""Run pipeline for suite evaluation artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evalops_kit.dataset import load_dataset
from evalops_kit.errors import SuiteConfigError
from evalops_kit.graders import evaluate_grader
from evalops_kit.suite import load_suite
from evalops_kit.trace import load_trace


@dataclass(frozen=True)
class TraceIssue:
    """Trace problem tracked for reporting."""

    case_id: str
    trace_path: str
    error: str | None = None


def run_suite(suite_path: Path, out_dir: Path) -> None:
    """Execute the v0.1 run pipeline and write artifacts."""
    suite = load_suite(suite_path)
    dataset_cases = load_dataset(suite.dataset_path)

    started_at = _iso_utc_now()
    traces_found = 0
    missing_issues: list[TraceIssue] = []
    invalid_issues: list[TraceIssue] = []
    case_results: list[dict[str, Any]] = []
    graded_case_count = 0
    overall_score_total = 0.0
    per_grader_totals = {grader.name: 0.0 for grader in suite.graders}
    per_grader_counts = {grader.name: 0 for grader in suite.graders}
    suite_base = suite.path.parent

    for dataset_case in dataset_cases:
        tags: list[str] = []
        trace_path: str | None = None
        scores: dict[str, float] = {}
        final_score: float | None = None

        if suite.traces_dir is not None:
            expected_trace_path = _resolve_trace_path(
                traces_dir=suite.traces_dir,
                pattern=suite.trace_filename_pattern,
                case_id=dataset_case.case_id,
                suite_path=suite.path,
            )
            expected_trace_display = _display_path(expected_trace_path, suite_base)

            if expected_trace_path.exists():
                trace_path = expected_trace_display
                try:
                    trace = load_trace(expected_trace_path, dataset_case.case_id)
                    traces_found += 1
                except ValueError as exc:
                    tags.append("invalid_trace")
                    invalid_issues.append(
                        TraceIssue(
                            case_id=dataset_case.case_id,
                            trace_path=expected_trace_display,
                            error=str(exc),
                        )
                    )
                else:
                    total_weight = 0.0
                    weighted_score_sum = 0.0
                    for grader in suite.graders:
                        grader_result = evaluate_grader(grader, trace)
                        scores[grader.name] = grader_result.score
                        tags.extend(grader_result.tags)
                        per_grader_totals[grader.name] += grader_result.score
                        per_grader_counts[grader.name] += 1
                        total_weight += grader.weight
                        weighted_score_sum += grader.weight * grader_result.score

                    if scores:
                        final_score = _compute_final_score(scores, weighted_score_sum, total_weight)
                        graded_case_count += 1
                        overall_score_total += final_score
            else:
                tags.append("missing_trace")
                missing_issues.append(
                    TraceIssue(
                        case_id=dataset_case.case_id,
                        trace_path=expected_trace_display,
                    )
                )

        case_results.append(
            {
                "case_id": dataset_case.case_id,
                "trace_path": trace_path,
                "tags": _dedupe_preserve_order(tags),
                "scores": scores,
                "final_score": final_score,
            }
        )

    ended_at = _iso_utc_now()
    summary = {
        "suite": {
            "name": suite.name,
            "version": suite.version,
        },
        "counts": {
            "total_cases": len(dataset_cases),
            "traces_found": traces_found,
            "traces_missing": len(missing_issues),
            "traces_invalid": len(invalid_issues),
        },
        "run": {
            "started_at": started_at,
            "ended_at": ended_at,
            "created_at": ended_at,
        },
    }
    if graded_case_count > 0:
        summary["metrics"] = {
            "overall_avg_score": overall_score_total / graded_case_count,
            "per_grader_avg": {
                grader.name: (per_grader_totals[grader.name] / per_grader_counts[grader.name])
                for grader in suite.graders
                if per_grader_counts[grader.name] > 0
            },
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_summary(out_dir / "summary.json", summary)
    _write_cases(out_dir / "cases.jsonl", case_results)
    _write_report(out_dir / "report.md", summary, case_results, missing_issues, invalid_issues)


def _resolve_trace_path(traces_dir: Path, pattern: str, case_id: str, suite_path: Path) -> Path:
    try:
        trace_name = pattern.format(case_id=case_id)
    except KeyError as exc:
        raise SuiteConfigError(
            f"Invalid suite {suite_path}: trace_filename_pattern must include '{{case_id}}'."
        ) from exc
    except ValueError as exc:
        raise SuiteConfigError(
            f"Invalid suite {suite_path}: trace_filename_pattern is not a valid format string."
        ) from exc
    return traces_dir / trace_name


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_cases(path: Path, case_results: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in case_results:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def _write_report(
    path: Path,
    summary: dict[str, Any],
    case_results: list[dict[str, Any]],
    missing_issues: list[TraceIssue],
    invalid_issues: list[TraceIssue],
    top_n: int = 20,
) -> None:
    suite = summary["suite"]
    counts = summary["counts"]
    run_meta = summary["run"]

    lines = [
        "# EvalOps Kit Run Report",
        "",
        f"Suite: **{suite['name']}** (version `{suite['version']}`)",
        f"Created at: `{run_meta['created_at']}`",
        "",
        "## Counts",
        f"- total_cases: {counts['total_cases']}",
        f"- traces_found: {counts['traces_found']}",
        f"- traces_missing: {counts['traces_missing']}",
        f"- traces_invalid: {counts['traces_invalid']}",
        "",
    ]

    metrics = summary.get("metrics")
    if isinstance(metrics, dict):
        overall_avg = metrics.get("overall_avg_score")
        per_grader_avg = metrics.get("per_grader_avg")
        if isinstance(overall_avg, (int, float)):
            lines.extend(
                [
                    "## Scores",
                    f"- overall_avg_score: {overall_avg:.6f}",
                ]
            )
            if isinstance(per_grader_avg, dict):
                for grader_name in sorted(per_grader_avg):
                    grader_score = per_grader_avg[grader_name]
                    if isinstance(grader_score, (int, float)):
                        lines.append(f"- per_grader_avg.{grader_name}: {grader_score:.6f}")
            lines.append("")

    worst_cases = _worst_scored_cases(case_results, top_n=top_n)
    lines.extend(
        [
            f"## Worst cases ({len(worst_cases)})",
        ]
    )
    if worst_cases:
        for case in worst_cases:
            tags = case["tags"]
            if tags:
                tags_text = ", ".join(str(tag) for tag in tags)
            else:
                tags_text = "none"
            case_id = case["case_id"]
            final_score = float(case["final_score"])
            lines.append(f"- `{case_id}`: final_score={final_score:.6f}; tags={tags_text}")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            f"## Missing traces ({len(missing_issues)})",
        ]
    )

    if missing_issues:
        for issue in missing_issues[:top_n]:
            lines.append(f"- `{issue.case_id}`: `{issue.trace_path}`")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            f"## Invalid traces ({len(invalid_issues)})",
        ]
    )
    if invalid_issues:
        for issue in invalid_issues[:top_n]:
            lines.append(f"- `{issue.case_id}`: `{issue.trace_path}` ({issue.error})")
    else:
        lines.append("- None")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _display_path(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _compute_final_score(
    scores: dict[str, float], weighted_score_sum: float, total_weight: float
) -> float:
    if total_weight > 0:
        return weighted_score_sum / total_weight
    return sum(scores.values()) / len(scores)


def _worst_scored_cases(case_results: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    scored_cases = [result for result in case_results if result.get("final_score") is not None]
    scored_cases.sort(key=lambda item: (float(item["final_score"]), str(item["case_id"])))
    return scored_cases[:top_n]
