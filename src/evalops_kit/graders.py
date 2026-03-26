"""Deterministic graders for validated traces."""

from __future__ import annotations

import re
from dataclasses import dataclass

from evalops_kit.suite import GraderConfig, RuleRegexGraderConfig, TraceToolPolicyGraderConfig
from evalops_kit.trace import TraceEvent, TraceRecord


@dataclass(frozen=True)
class GraderResult:
    """Result from one deterministic grader."""

    score: float
    tags: tuple[str, ...]


def evaluate_grader(grader: GraderConfig, trace: TraceRecord) -> GraderResult:
    """Evaluate one grader against one validated trace."""
    if isinstance(grader, RuleRegexGraderConfig):
        return _evaluate_rule_regex(grader, trace)
    if isinstance(grader, TraceToolPolicyGraderConfig):
        return _evaluate_trace_tool_policy(grader, trace)
    raise TypeError(f"Unsupported grader config type: {type(grader)!r}")


def _evaluate_rule_regex(grader: RuleRegexGraderConfig, trace: TraceRecord) -> GraderResult:
    regex_flags = _parse_regex_flags(grader.flags)
    matcher = re.compile(grader.pattern, flags=regex_flags)
    final_text = trace.final.text or ""
    matched = matcher.search(final_text) is not None
    passed = matched if grader.must_match else not matched
    if passed:
        return GraderResult(score=1.0, tags=())

    if grader.must_match:
        failure_tag = f"rule_regex_no_match:{grader.name}"
    else:
        failure_tag = f"rule_regex_unexpected_match:{grader.name}"
    return GraderResult(score=0.0, tags=(failure_tag,))


def _evaluate_trace_tool_policy(
    grader: TraceToolPolicyGraderConfig, trace: TraceRecord
) -> GraderResult:
    used_tools = {event.name for event in trace.events if event.type == "tool_call" and event.name}
    missing_required = sorted(set(grader.require_tools) - used_tools)
    used_forbidden = sorted(set(grader.forbid_tools) & used_tools)
    has_tool_error = any(_event_indicates_tool_error(event) for event in trace.events)

    tags: list[str] = []
    tags.extend(f"missing_required_tools:{tool}" for tool in missing_required)
    tags.extend(f"used_forbidden_tool:{tool}" for tool in used_forbidden)
    if grader.fail_on_tool_error and has_tool_error:
        tags.append("tool_error")

    score = 0.0 if tags else 1.0
    return GraderResult(score=score, tags=tuple(tags))


def _parse_regex_flags(flags: str) -> int:
    parsed_flags = 0
    for char in flags:
        if char == "i":
            parsed_flags |= re.IGNORECASE
        elif char == "m":
            parsed_flags |= re.MULTILINE
        elif char == "s":
            parsed_flags |= re.DOTALL
    return parsed_flags


def _event_indicates_tool_error(event: TraceEvent) -> bool:
    if event.type in {"error", "tool_error"}:
        return True
    if event.type not in {"tool_call", "tool_result"}:
        return False
    return event.error is not None
