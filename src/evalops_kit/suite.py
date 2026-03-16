"""Suite configuration parsing and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only hit on Python <3.11
    tomllib = None  # type: ignore[assignment]

from evalops_kit.errors import SuiteConfigError


@dataclass(frozen=True)
class RuleRegexGraderConfig:
    """Configuration for regex-based grading."""

    name: str
    kind: str
    weight: float
    pattern: str
    must_match: bool
    flags: str


@dataclass(frozen=True)
class TraceToolPolicyGraderConfig:
    """Configuration for tool usage policy grading."""

    name: str
    kind: str
    weight: float
    require_tools: tuple[str, ...]
    forbid_tools: tuple[str, ...]
    fail_on_tool_error: bool


GraderConfig = RuleRegexGraderConfig | TraceToolPolicyGraderConfig


@dataclass(frozen=True)
class OverallAvgDropMaxGateConfig:
    """Gate for maximum allowed drop in overall average score."""

    kind: str
    max_drop: float


@dataclass(frozen=True)
class PerGraderAvgDropMaxGateConfig:
    """Gate for maximum allowed drop in one grader's average score."""

    kind: str
    grader: str
    max_drop: float


@dataclass(frozen=True)
class MissingTracesIncreaseMaxGateConfig:
    """Gate for maximum allowed increase in missing traces."""

    kind: str
    max_increase: int


@dataclass(frozen=True)
class InvalidTracesIncreaseMaxGateConfig:
    """Gate for maximum allowed increase in invalid traces."""

    kind: str
    max_increase: int


GateConfig = (
    OverallAvgDropMaxGateConfig
    | PerGraderAvgDropMaxGateConfig
    | MissingTracesIncreaseMaxGateConfig
    | InvalidTracesIncreaseMaxGateConfig
)


@dataclass(frozen=True)
class SuiteConfig:
    """Parsed suite configuration."""

    path: Path
    name: str
    version: str
    dataset_path: Path
    traces_dir: Path | None
    trace_filename_pattern: str
    graders: tuple[GraderConfig, ...]
    gates: tuple[GateConfig, ...]


def load_suite(path: Path) -> SuiteConfig:
    """Load and validate a suite TOML file."""
    if tomllib is None:
        raise SuiteConfigError(
            "Suite parsing requires Python 3.11+ (stdlib tomllib is unavailable)."
        )

    if not path.exists():
        raise SuiteConfigError(f"Suite file not found: {path}")
    if not path.is_file():
        raise SuiteConfigError(f"Suite path is not a file: {path}")

    try:
        raw_config = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SuiteConfigError(f"Invalid TOML in {path}: {exc}") from exc

    if not isinstance(raw_config, dict):
        raise SuiteConfigError(f"Invalid suite structure in {path}: expected table at top level.")

    version = _require_str(raw_config, "version", path)
    name = _require_str(raw_config, "name", path)
    dataset = _require_str(raw_config, "dataset", path)
    traces_dir = _optional_str(raw_config, "traces_dir", path)
    trace_filename_pattern = _optional_str(raw_config, "trace_filename_pattern", path)
    if trace_filename_pattern is None:
        trace_filename_pattern = "{case_id}.json"
    graders = _parse_graders(raw_config, path)
    gates = _parse_gates(raw_config, path)

    suite_dir = path.parent
    resolved_dataset = (suite_dir / dataset).resolve()
    resolved_traces_dir = None if traces_dir is None else (suite_dir / traces_dir).resolve()

    return SuiteConfig(
        path=path.resolve(),
        name=name,
        version=version,
        dataset_path=resolved_dataset,
        traces_dir=resolved_traces_dir,
        trace_filename_pattern=trace_filename_pattern,
        graders=tuple(graders),
        gates=tuple(gates),
    )


def _require_str(config: dict[str, Any], key: str, path: Path) -> str:
    if key not in config:
        raise SuiteConfigError(f"Invalid suite {path}: missing required key '{key}'.")
    value = config[key]
    if not isinstance(value, str):
        raise SuiteConfigError(f"Invalid suite {path}: key '{key}' must be a string.")
    if value.strip() == "":
        raise SuiteConfigError(f"Invalid suite {path}: key '{key}' must not be empty.")
    return value


def _optional_str(config: dict[str, Any], key: str, path: Path) -> str | None:
    if key not in config:
        return None
    value = config[key]
    if not isinstance(value, str):
        raise SuiteConfigError(f"Invalid suite {path}: key '{key}' must be a string when provided.")
    if value.strip() == "":
        raise SuiteConfigError(f"Invalid suite {path}: key '{key}' must not be empty.")
    return value


def _parse_graders(config: dict[str, Any], path: Path) -> list[GraderConfig]:
    raw_graders = config.get("graders")
    if raw_graders is None:
        return []
    if not isinstance(raw_graders, list):
        raise SuiteConfigError(f"Invalid suite {path}: key 'graders' must be an array of tables.")

    graders: list[GraderConfig] = []
    for index, raw_grader in enumerate(raw_graders):
        ctx = f"graders[{index}]"
        if not isinstance(raw_grader, dict):
            raise SuiteConfigError(f"Invalid suite {path}: {ctx} must be a table.")

        name = _require_nested_str(raw_grader, "name", path, ctx)
        kind = _require_nested_str(raw_grader, "kind", path, ctx)
        weight = _optional_nested_float(raw_grader, "weight", path, ctx, default=1.0)

        if kind == "rule_regex":
            graders.append(_parse_rule_regex_grader(raw_grader, path, ctx, name, kind, weight))
        elif kind == "trace_tool_policy":
            graders.append(
                _parse_trace_tool_policy_grader(raw_grader, path, ctx, name, kind, weight)
            )
        else:
            raise SuiteConfigError(
                f"Invalid suite {path}: {ctx}.kind must be one of "
                "'rule_regex' or 'trace_tool_policy'."
            )
    return graders


def _parse_gates(config: dict[str, Any], path: Path) -> list[GateConfig]:
    raw_gates = config.get("gates")
    if raw_gates is None:
        return []
    if not isinstance(raw_gates, list):
        raise SuiteConfigError(f"Invalid suite {path}: key 'gates' must be an array of tables.")

    gates: list[GateConfig] = []
    for index, raw_gate in enumerate(raw_gates):
        ctx = f"gates[{index}]"
        if not isinstance(raw_gate, dict):
            raise SuiteConfigError(f"Invalid suite {path}: {ctx} must be a table.")

        kind = _require_nested_str(raw_gate, "kind", path, ctx)
        if kind == "overall_avg_drop_max":
            gates.append(
                OverallAvgDropMaxGateConfig(
                    kind=kind,
                    max_drop=_require_nested_float(raw_gate, "max_drop", path, ctx),
                )
            )
        elif kind == "per_grader_avg_drop_max":
            gates.append(
                PerGraderAvgDropMaxGateConfig(
                    kind=kind,
                    grader=_require_nested_str(raw_gate, "grader", path, ctx),
                    max_drop=_require_nested_float(raw_gate, "max_drop", path, ctx),
                )
            )
        elif kind == "missing_traces_increase_max":
            gates.append(
                MissingTracesIncreaseMaxGateConfig(
                    kind=kind,
                    max_increase=_require_nested_int(raw_gate, "max_increase", path, ctx),
                )
            )
        elif kind == "invalid_traces_increase_max":
            gates.append(
                InvalidTracesIncreaseMaxGateConfig(
                    kind=kind,
                    max_increase=_require_nested_int(raw_gate, "max_increase", path, ctx),
                )
            )
        else:
            raise SuiteConfigError(
                f"Invalid suite {path}: {ctx}.kind must be one of "
                "'overall_avg_drop_max', 'per_grader_avg_drop_max', "
                "'missing_traces_increase_max', or 'invalid_traces_increase_max'."
            )
    return gates


def _parse_rule_regex_grader(
    raw_grader: dict[str, Any],
    path: Path,
    ctx: str,
    name: str,
    kind: str,
    weight: float,
) -> RuleRegexGraderConfig:
    pattern = _require_nested_str(raw_grader, "pattern", path, ctx)
    must_match = _optional_nested_bool(raw_grader, "must_match", path, ctx, default=True)
    flags = raw_grader.get("flags", "")
    if not isinstance(flags, str):
        raise SuiteConfigError(f"Invalid suite {path}: {ctx}.flags must be a string.")
    invalid_flags = sorted({char for char in flags if char not in {"i", "m", "s"}})
    if invalid_flags:
        joined = ", ".join(repr(char) for char in invalid_flags)
        raise SuiteConfigError(
            f"Invalid suite {path}: {ctx}.flags contains unsupported flag(s): {joined}."
        )
    return RuleRegexGraderConfig(
        name=name,
        kind=kind,
        weight=weight,
        pattern=pattern,
        must_match=must_match,
        flags=flags,
    )


def _parse_trace_tool_policy_grader(
    raw_grader: dict[str, Any],
    path: Path,
    ctx: str,
    name: str,
    kind: str,
    weight: float,
) -> TraceToolPolicyGraderConfig:
    require_tools = _optional_nested_str_list(
        raw_grader, "require_tools", path, ctx, default=tuple()
    )
    forbid_tools = _optional_nested_str_list(raw_grader, "forbid_tools", path, ctx, default=tuple())
    fail_on_tool_error = _optional_nested_bool(
        raw_grader, "fail_on_tool_error", path, ctx, default=True
    )

    return TraceToolPolicyGraderConfig(
        name=name,
        kind=kind,
        weight=weight,
        require_tools=require_tools,
        forbid_tools=forbid_tools,
        fail_on_tool_error=fail_on_tool_error,
    )


def _require_nested_str(config: dict[str, Any], key: str, path: Path, ctx: str) -> str:
    if key not in config:
        raise SuiteConfigError(f"Invalid suite {path}: {ctx} missing required key '{key}'.")
    value = config[key]
    if not isinstance(value, str):
        raise SuiteConfigError(f"Invalid suite {path}: {ctx}.{key} must be a string.")
    if value.strip() == "":
        raise SuiteConfigError(f"Invalid suite {path}: {ctx}.{key} must not be empty.")
    return value


def _optional_nested_bool(
    config: dict[str, Any], key: str, path: Path, ctx: str, default: bool
) -> bool:
    if key not in config:
        return default
    value = config[key]
    if not isinstance(value, bool):
        raise SuiteConfigError(f"Invalid suite {path}: {ctx}.{key} must be a boolean.")
    return value


def _optional_nested_float(
    config: dict[str, Any], key: str, path: Path, ctx: str, default: float
) -> float:
    if key not in config:
        return default
    value = config[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SuiteConfigError(f"Invalid suite {path}: {ctx}.{key} must be a number.")
    return float(value)


def _require_nested_float(config: dict[str, Any], key: str, path: Path, ctx: str) -> float:
    if key not in config:
        raise SuiteConfigError(f"Invalid suite {path}: {ctx} missing required key '{key}'.")
    value = config[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SuiteConfigError(f"Invalid suite {path}: {ctx}.{key} must be a number.")
    return float(value)


def _require_nested_int(config: dict[str, Any], key: str, path: Path, ctx: str) -> int:
    if key not in config:
        raise SuiteConfigError(f"Invalid suite {path}: {ctx} missing required key '{key}'.")
    value = config[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise SuiteConfigError(f"Invalid suite {path}: {ctx}.{key} must be an integer.")
    return value


def _optional_nested_str_list(
    config: dict[str, Any],
    key: str,
    path: Path,
    ctx: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    if key not in config:
        return default
    value = config[key]
    if not isinstance(value, list):
        raise SuiteConfigError(f"Invalid suite {path}: {ctx}.{key} must be an array of strings.")
    parsed: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or item.strip() == "":
            raise SuiteConfigError(
                f"Invalid suite {path}: {ctx}.{key}[{idx}] must be a non-empty string."
            )
        parsed.append(item)
    return tuple(parsed)
