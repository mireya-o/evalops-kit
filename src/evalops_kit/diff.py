"""Diff pipeline for comparing two EvalOps Kit run outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evalops_kit.errors import DiffError
from evalops_kit.suite import (
    GateConfig,
    InvalidTracesIncreaseMaxGateConfig,
    MissingTracesIncreaseMaxGateConfig,
    OverallAvgDropMaxGateConfig,
    PerGraderAvgDropMaxGateConfig,
    SuiteConfig,
    load_suite,
)


@dataclass(frozen=True)
class CaseResult:
    """Per-case result row from cases.jsonl."""

    case_id: str
    final_score: float | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class RunMetrics:
    """Metrics extracted from one summary.json."""

    overall_avg_score: float | None
    per_grader_avg: dict[str, float]
    traces_missing: int | None
    traces_invalid: int | None


@dataclass(frozen=True)
class RunArtifacts:
    """Normalized run artifacts used by diff."""

    input_path: Path
    run_dir: Path
    summary_path: Path
    cases_path: Path
    suite_name: str | None
    suite_version: str | None
    metrics: RunMetrics
    cases_by_id: dict[str, CaseResult]


@dataclass(frozen=True)
class GateResult:
    """One evaluated gate."""

    kind: str
    passed: bool
    message: str


@dataclass(frozen=True)
class DiffResult:
    """Rendered diff outcome."""

    report_markdown: str
    gate_results: tuple[GateResult, ...]

    @property
    def has_gate_failures(self) -> bool:
        return any(not gate.passed for gate in self.gate_results)


def build_diff_report(
    base_path: Path,
    cand_path: Path,
    suite_path: Path | None = None,
    top_n_regressions: int = 10,
) -> DiffResult:
    """Build markdown diff report for base and candidate run artifacts."""
    base = _load_run_artifacts(base_path, label="base")
    cand = _load_run_artifacts(cand_path, label="cand")

    suite_config: SuiteConfig | None = None
    if suite_path is not None:
        suite_config = load_suite(suite_path)
    _validate_comparable_runs(base, cand, suite_config=suite_config)

    gates = tuple() if suite_config is None else suite_config.gates
    gate_results = _evaluate_gates(base, cand, gates)

    lines: list[str] = [
        "# EvalOps Kit Diff Report",
        "",
        f"- base path: `{base.input_path}`",
        f"- candidate path: `{cand.input_path}`",
    ]
    if suite_config is not None:
        lines.append(f"- suite (gates): **{suite_config.name}** (version `{suite_config.version}`)")
    else:
        suite_name, suite_version = _select_suite_identity(base, cand)
        if suite_name is not None and suite_version is not None:
            lines.append(f"- suite: **{suite_name}** (version `{suite_version}`)")
    lines.extend(["", "## Metrics"])

    overall_delta = _delta(cand.metrics.overall_avg_score, base.metrics.overall_avg_score)
    lines.append(
        "- overall_avg_score: "
        f"base={_fmt_float(base.metrics.overall_avg_score)}, "
        f"cand={_fmt_float(cand.metrics.overall_avg_score)}, "
        f"delta={_fmt_float(overall_delta, signed=True)}"
    )

    lines.extend(
        [
            "",
            "### per_grader_avg",
            "| grader | base | cand | delta |",
            "|---|---:|---:|---:|",
        ]
    )
    per_grader_rows = _per_grader_rows(base.metrics.per_grader_avg, cand.metrics.per_grader_avg)
    if per_grader_rows:
        for grader, base_score, cand_score, delta in per_grader_rows:
            lines.append(
                f"| `{grader}` | {_fmt_float(base_score)} | {_fmt_float(cand_score)} | "
                f"{_fmt_float(delta, signed=True)} |"
            )
    else:
        lines.append("| _none_ | n/a | n/a | n/a |")

    missing_delta = _delta_int(cand.metrics.traces_missing, base.metrics.traces_missing)
    invalid_delta = _delta_int(cand.metrics.traces_invalid, base.metrics.traces_invalid)
    lines.extend(
        [
            "",
            "- traces_missing: "
            f"base={_fmt_int(base.metrics.traces_missing)}, "
            f"cand={_fmt_int(cand.metrics.traces_missing)}, "
            f"delta={_fmt_int(missing_delta, signed=True)}",
            "- traces_invalid: "
            f"base={_fmt_int(base.metrics.traces_invalid)}, "
            f"cand={_fmt_int(cand.metrics.traces_invalid)}, "
            f"delta={_fmt_int(invalid_delta, signed=True)}",
        ]
    )

    regressions = _top_regressions(base.cases_by_id, cand.cases_by_id, top_n=top_n_regressions)
    lines.extend(["", f"## Top regressions ({len(regressions)})"])
    if regressions:
        for case_id, base_score, cand_score, delta in regressions:
            lines.append(
                f"- `{case_id}`: base={base_score:.6f}, cand={cand_score:.6f}, delta={delta:+.6f}"
            )
    else:
        lines.append("- None")

    newly_missing = _new_case_ids_with_tag(base.cases_by_id, cand.cases_by_id, "missing_trace")
    lines.extend(["", f"## Newly missing traces ({len(newly_missing)})"])
    if newly_missing:
        for case_id in newly_missing:
            lines.append(f"- `{case_id}`")
    else:
        lines.append("- None")

    newly_invalid = _new_case_ids_with_tag(base.cases_by_id, cand.cases_by_id, "invalid_trace")
    lines.extend(["", f"## Newly invalid traces ({len(newly_invalid)})"])
    if newly_invalid:
        for case_id in newly_invalid:
            lines.append(f"- `{case_id}`")
    else:
        lines.append("- None")

    lines.append("")
    if suite_config is None:
        lines.extend(
            [
                "## Gates",
                "- Not evaluated (no `--suite` provided).",
            ]
        )
    elif not gate_results:
        lines.extend(
            [
                "## Gates",
                "- No gates configured in suite.",
            ]
        )
    else:
        lines.append(f"## Gates ({len(gate_results)})")
        for gate_result in gate_results:
            status = "PASS" if gate_result.passed else "FAIL"
            lines.append(f"- {status} `{gate_result.kind}`: {gate_result.message}")

    return DiffResult(report_markdown="\n".join(lines) + "\n", gate_results=gate_results)


def write_diff_report(report_markdown: str, out_path: Path) -> None:
    """Write diff report markdown to file."""
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_markdown, encoding="utf-8")
    except OSError as exc:
        raise DiffError(f"Failed to write diff report to {out_path}: {exc}.") from exc


def _load_run_artifacts(path: Path, label: str) -> RunArtifacts:
    input_path = path.resolve()
    run_dir, summary_path = _resolve_summary_path(path, label=label)
    cases_path = run_dir / "cases.jsonl"
    if not cases_path.exists():
        raise DiffError(f"Invalid {label} run: missing cases.jsonl at {cases_path}.")
    if not cases_path.is_file():
        raise DiffError(f"Invalid {label} run: {cases_path} is not a file.")

    summary = _load_summary_json(summary_path, label=label)
    suite_name, suite_version = _read_suite_identity(summary, label=label)
    metrics = _read_run_metrics(summary, label=label)
    cases_by_id = _load_cases_jsonl(cases_path, label=label)
    return RunArtifacts(
        input_path=input_path,
        run_dir=run_dir.resolve(),
        summary_path=summary_path.resolve(),
        cases_path=cases_path.resolve(),
        suite_name=suite_name,
        suite_version=suite_version,
        metrics=metrics,
        cases_by_id=cases_by_id,
    )


def _resolve_summary_path(path: Path, label: str) -> tuple[Path, Path]:
    if not path.exists():
        raise DiffError(f"{label} path not found: {path}")

    if path.is_dir():
        run_dir = path
        summary_path = run_dir / "summary.json"
    elif path.is_file():
        if path.name != "summary.json":
            raise DiffError(
                f"Invalid {label} path {path}: expected run directory or summary.json file."
            )
        summary_path = path
        run_dir = path.parent
    else:
        raise DiffError(f"Invalid {label} path {path}: expected file or directory.")

    if not summary_path.exists():
        raise DiffError(f"Invalid {label} run: missing summary.json at {summary_path}.")
    if not summary_path.is_file():
        raise DiffError(f"Invalid {label} run: {summary_path} is not a file.")
    return run_dir, summary_path


def _load_summary_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DiffError(f"Failed to read {label} summary {path}: {exc}.") from exc
    except json.JSONDecodeError as exc:
        raise DiffError(f"Invalid JSON in {label} summary {path}: {exc.msg}.") from exc
    if not isinstance(payload, dict):
        raise DiffError(f"Invalid {label} summary {path}: expected top-level object.")
    return payload


def _read_suite_identity(summary: dict[str, Any], label: str) -> tuple[str | None, str | None]:
    raw_suite = summary.get("suite")
    if raw_suite is None:
        return None, None
    if not isinstance(raw_suite, dict):
        raise DiffError(f"Invalid {label} summary: 'suite' must be an object when provided.")

    name = raw_suite.get("name")
    version = raw_suite.get("version")
    if name is not None and not isinstance(name, str):
        raise DiffError(f"Invalid {label} summary: 'suite.name' must be a string.")
    if version is not None and not isinstance(version, str):
        raise DiffError(f"Invalid {label} summary: 'suite.version' must be a string.")
    return name, version


def _read_run_metrics(summary: dict[str, Any], label: str) -> RunMetrics:
    raw_metrics = summary.get("metrics")
    if raw_metrics is None:
        overall_avg_score = None
        per_grader_avg: dict[str, float] = {}
    else:
        if not isinstance(raw_metrics, dict):
            raise DiffError(f"Invalid {label} summary: 'metrics' must be an object.")
        overall_avg_score = _optional_number(
            raw_metrics, "overall_avg_score", f"{label} summary metrics"
        )
        raw_per_grader = raw_metrics.get("per_grader_avg")
        if raw_per_grader is None:
            per_grader_avg = {}
        else:
            if not isinstance(raw_per_grader, dict):
                raise DiffError(
                    f"Invalid {label} summary: 'metrics.per_grader_avg' must be an object."
                )
            per_grader_avg = {}
            for grader, value in raw_per_grader.items():
                if not isinstance(grader, str) or grader.strip() == "":
                    raise DiffError(
                        f"Invalid {label} summary: 'metrics.per_grader_avg' keys must be strings."
                    )
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise DiffError(
                        "Invalid "
                        f"{label} summary: metrics.per_grader_avg.{grader} must be a number."
                    )
                per_grader_avg[grader] = float(value)

    raw_counts = summary.get("counts")
    if raw_counts is None:
        traces_missing = None
        traces_invalid = None
    else:
        if not isinstance(raw_counts, dict):
            raise DiffError(f"Invalid {label} summary: 'counts' must be an object.")
        traces_missing = _optional_int(raw_counts, "traces_missing", f"{label} summary counts")
        traces_invalid = _optional_int(raw_counts, "traces_invalid", f"{label} summary counts")

    return RunMetrics(
        overall_avg_score=overall_avg_score,
        per_grader_avg=per_grader_avg,
        traces_missing=traces_missing,
        traces_invalid=traces_invalid,
    )


def _load_cases_jsonl(path: Path, label: str) -> dict[str, CaseResult]:
    rows: dict[str, CaseResult] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise DiffError(
                    f"Invalid JSON in {label} cases {path} at line {line_number}: {exc.msg}."
                ) from exc
            if not isinstance(payload, dict):
                raise DiffError(
                    f"Invalid {label} cases {path} line {line_number}: expected object."
                )

            case_id = payload.get("case_id")
            if not isinstance(case_id, str) or case_id.strip() == "":
                raise DiffError(
                    f"Invalid {label} cases {path} line {line_number}: "
                    "field 'case_id' must be a non-empty string."
                )
            if case_id in rows:
                raise DiffError(f"Invalid {label} cases {path}: duplicate case_id {case_id!r}.")

            final_score = _parse_optional_case_score(
                payload.get("final_score"), path=path, label=label, line_number=line_number
            )
            tags = _parse_case_tags(
                payload.get("tags"),
                path=path,
                label=label,
                line_number=line_number,
            )
            rows[case_id] = CaseResult(case_id=case_id, final_score=final_score, tags=tags)
    return rows


def _parse_optional_case_score(
    value: Any, path: Path, label: str, line_number: int
) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise DiffError(
            f"Invalid {label} cases {path} line {line_number}: "
            "field 'final_score' must be a number or null."
        )
    return float(value)


def _parse_case_tags(value: Any, path: Path, label: str, line_number: int) -> tuple[str, ...]:
    if value is None:
        return tuple()
    if not isinstance(value, list):
        raise DiffError(
            f"Invalid {label} cases {path} line {line_number}: field 'tags' must be an array."
        )
    tags: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            raise DiffError(
                f"Invalid {label} cases {path} line {line_number}: tags[{idx}] must be a string."
            )
        tags.append(item)
    return tuple(tags)


def _top_regressions(
    base_cases: dict[str, CaseResult], cand_cases: dict[str, CaseResult], top_n: int
) -> list[tuple[str, float, float, float]]:
    rows: list[tuple[str, float, float, float]] = []
    shared_case_ids = set(base_cases) & set(cand_cases)
    for case_id in shared_case_ids:
        base_score = base_cases[case_id].final_score
        cand_score = cand_cases[case_id].final_score
        if base_score is None or cand_score is None:
            continue
        delta = cand_score - base_score
        if delta < 0:
            rows.append((case_id, base_score, cand_score, delta))
    rows.sort(key=lambda item: (item[3], item[0]))
    return rows[:top_n]


def _new_case_ids_with_tag(
    base_cases: dict[str, CaseResult], cand_cases: dict[str, CaseResult], tag: str
) -> list[str]:
    base_tagged = {case_id for case_id, row in base_cases.items() if tag in row.tags}
    cand_tagged = {case_id for case_id, row in cand_cases.items() if tag in row.tags}
    return sorted(cand_tagged - base_tagged)


def _evaluate_gates(
    base: RunArtifacts, cand: RunArtifacts, gates: tuple[GateConfig, ...]
) -> tuple[GateResult, ...]:
    results: list[GateResult] = []
    for gate in gates:
        if isinstance(gate, OverallAvgDropMaxGateConfig):
            results.append(_eval_overall_avg_drop_gate(gate, base, cand))
        elif isinstance(gate, PerGraderAvgDropMaxGateConfig):
            results.append(_eval_per_grader_avg_drop_gate(gate, base, cand))
        elif isinstance(gate, MissingTracesIncreaseMaxGateConfig):
            results.append(_eval_missing_traces_increase_gate(gate, base, cand))
        elif isinstance(gate, InvalidTracesIncreaseMaxGateConfig):
            results.append(_eval_invalid_traces_increase_gate(gate, base, cand))
        else:  # pragma: no cover - defensive for future extensions
            raise DiffError(f"Unsupported gate config type in suite: {type(gate)!r}")
    return tuple(results)


def _eval_overall_avg_drop_gate(
    gate: OverallAvgDropMaxGateConfig, base: RunArtifacts, cand: RunArtifacts
) -> GateResult:
    base_value = base.metrics.overall_avg_score
    cand_value = cand.metrics.overall_avg_score
    if base_value is None or cand_value is None:
        return GateResult(
            kind=gate.kind,
            passed=False,
            message=(
                "missing required metric overall_avg_score "
                f"(base={_fmt_float(base_value)}, cand={_fmt_float(cand_value)})"
            ),
        )

    drop = base_value - cand_value
    passed = drop <= gate.max_drop
    return GateResult(
        kind=gate.kind,
        passed=passed,
        message=f"drop={drop:.6f}, max_drop={gate.max_drop:.6f}",
    )


def _eval_per_grader_avg_drop_gate(
    gate: PerGraderAvgDropMaxGateConfig, base: RunArtifacts, cand: RunArtifacts
) -> GateResult:
    base_value = base.metrics.per_grader_avg.get(gate.grader)
    cand_value = cand.metrics.per_grader_avg.get(gate.grader)
    if base_value is None or cand_value is None:
        missing_in: list[str] = []
        if base_value is None:
            missing_in.append("base")
        if cand_value is None:
            missing_in.append("cand")
        return GateResult(
            kind=gate.kind,
            passed=False,
            message=(
                "missing required "
                f"per_grader_avg.{gate.grader!r} in {', '.join(missing_in)} summary."
            ),
        )

    drop = base_value - cand_value
    passed = drop <= gate.max_drop
    return GateResult(
        kind=gate.kind,
        passed=passed,
        message=(f"grader={gate.grader!r}, drop={drop:.6f}, max_drop={gate.max_drop:.6f}"),
    )


def _eval_missing_traces_increase_gate(
    gate: MissingTracesIncreaseMaxGateConfig, base: RunArtifacts, cand: RunArtifacts
) -> GateResult:
    base_value = base.metrics.traces_missing
    cand_value = cand.metrics.traces_missing
    if base_value is None or cand_value is None:
        return GateResult(
            kind=gate.kind,
            passed=False,
            message=(
                "missing required metric counts.traces_missing "
                f"(base={_fmt_int(base_value)}, cand={_fmt_int(cand_value)})"
            ),
        )
    increase = cand_value - base_value
    passed = increase <= gate.max_increase
    return GateResult(
        kind=gate.kind,
        passed=passed,
        message=f"increase={increase:+d}, max_increase={gate.max_increase}",
    )


def _eval_invalid_traces_increase_gate(
    gate: InvalidTracesIncreaseMaxGateConfig, base: RunArtifacts, cand: RunArtifacts
) -> GateResult:
    base_value = base.metrics.traces_invalid
    cand_value = cand.metrics.traces_invalid
    if base_value is None or cand_value is None:
        return GateResult(
            kind=gate.kind,
            passed=False,
            message=(
                "missing required metric counts.traces_invalid "
                f"(base={_fmt_int(base_value)}, cand={_fmt_int(cand_value)})"
            ),
        )
    increase = cand_value - base_value
    passed = increase <= gate.max_increase
    return GateResult(
        kind=gate.kind,
        passed=passed,
        message=f"increase={increase:+d}, max_increase={gate.max_increase}",
    )


def _per_grader_rows(
    base_per_grader: dict[str, float], cand_per_grader: dict[str, float]
) -> list[tuple[str, float | None, float | None, float | None]]:
    rows: list[tuple[str, float | None, float | None, float | None]] = []
    for grader in sorted(set(base_per_grader) | set(cand_per_grader)):
        base_value = base_per_grader.get(grader)
        cand_value = cand_per_grader.get(grader)
        rows.append((grader, base_value, cand_value, _delta(cand_value, base_value)))
    return rows


def _optional_number(data: dict[str, Any], key: str, ctx: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise DiffError(f"Invalid {ctx}: field '{key}' must be a number when provided.")
    return float(value)


def _optional_int(data: dict[str, Any], key: str, ctx: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise DiffError(f"Invalid {ctx}: field '{key}' must be an integer when provided.")
    return value


def _validate_comparable_runs(
    base: RunArtifacts, cand: RunArtifacts, suite_config: SuiteConfig | None
) -> None:
    _validate_case_id_sets(base, cand)
    if suite_config is None:
        _validate_matching_suite_identity_without_suite(base, cand)
        return

    expected_identity = _normalize_suite_identity(
        suite_config.name,
        suite_config.version,
        label=f"suite {suite_config.path}",
    )
    _validate_summary_matches_suite_file(base, expected_identity, label="base")
    _validate_summary_matches_suite_file(cand, expected_identity, label="cand")


def _validate_case_id_sets(base: RunArtifacts, cand: RunArtifacts) -> None:
    base_case_ids = set(base.cases_by_id)
    cand_case_ids = set(cand.cases_by_id)
    missing_in_cand = sorted(base_case_ids - cand_case_ids)
    missing_in_base = sorted(cand_case_ids - base_case_ids)
    if not missing_in_cand and not missing_in_base:
        return
    raise DiffError(
        "Invalid diff inputs: cases.jsonl case_id sets do not match. "
        f"missing in cand: {_fmt_case_id_list(missing_in_cand)}; "
        f"missing in base: {_fmt_case_id_list(missing_in_base)}."
    )


def _validate_matching_suite_identity_without_suite(base: RunArtifacts, cand: RunArtifacts) -> None:
    base_identity = _normalize_suite_identity(
        base.suite_name,
        base.suite_version,
        label="base summary",
    )
    cand_identity = _normalize_suite_identity(
        cand.suite_name,
        cand.suite_version,
        label="cand summary",
    )
    if base_identity != cand_identity:
        base_identity_display = _fmt_suite_identity(base_identity)
        cand_identity_display = _fmt_suite_identity(cand_identity)
        raise DiffError(
            "Invalid diff inputs: base and cand suite identity must match "
            "when --suite is not provided "
            f"(base={base_identity_display}, cand={cand_identity_display})."
        )


def _validate_summary_matches_suite_file(
    run: RunArtifacts, expected_identity: tuple[str, str], label: str
) -> None:
    run_identity = _normalize_suite_identity(
        run.suite_name,
        run.suite_version,
        label=f"{label} summary",
    )
    if run_identity != expected_identity:
        raise DiffError(
            f"Invalid diff inputs: {label} summary suite identity does not match --suite "
            f"(expected={_fmt_suite_identity(expected_identity)}, "
            f"{label}={_fmt_suite_identity(run_identity)})."
        )


def _normalize_suite_identity(
    name: str | None, version: str | None, *, label: str
) -> tuple[str, str] | None:
    if name is None and version is None:
        return None
    if name is None or version is None:
        raise DiffError(
            f"Invalid diff inputs: {label} must include both suite.name and suite.version."
        )

    normalized_name = name.strip()
    normalized_version = version.strip()
    if not normalized_name or not normalized_version:
        raise DiffError(
            f"Invalid diff inputs: {label} must include non-empty suite.name and suite.version."
        )
    return normalized_name, normalized_version


def _fmt_suite_identity(identity: tuple[str, str] | None) -> str:
    if identity is None:
        return "none"
    name, version = identity
    return f"{name!r}@{version!r}"


def _fmt_case_id_list(case_ids: list[str]) -> str:
    if not case_ids:
        return "none"
    return ", ".join(repr(case_id) for case_id in case_ids)


def _select_suite_identity(base: RunArtifacts, cand: RunArtifacts) -> tuple[str | None, str | None]:
    if cand.suite_name and cand.suite_version:
        return cand.suite_name, cand.suite_version
    if base.suite_name and base.suite_version:
        return base.suite_name, base.suite_version
    return None, None


def _delta(cand_value: float | None, base_value: float | None) -> float | None:
    if cand_value is None or base_value is None:
        return None
    return cand_value - base_value


def _delta_int(cand_value: int | None, base_value: int | None) -> int | None:
    if cand_value is None or base_value is None:
        return None
    return cand_value - base_value


def _fmt_float(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    if signed:
        return f"{value:+.6f}"
    return f"{value:.6f}"


def _fmt_int(value: int | None, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    if signed:
        return f"{value:+d}"
    return str(value)
