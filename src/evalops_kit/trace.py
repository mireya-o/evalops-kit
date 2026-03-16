"""Trace loading, model, and schema validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TraceEvent:
    """One event in an agent trace."""

    type: str
    name: str | None
    input: Any
    output: Any
    error: Any
    meta: Any


@dataclass(frozen=True)
class TraceFinal:
    """Final output payload in a trace."""

    text: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class TraceRecord:
    """Validated trace payload."""

    case_id: str
    events: tuple[TraceEvent, ...]
    final: TraceFinal


def load_trace(path: Path, expected_case_id: str) -> TraceRecord:
    """Load and validate one trace file."""
    try:
        raw_trace = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Invalid trace {path}: could not read file: {exc}.") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid trace {path}: invalid JSON: {exc.msg}.") from exc

    if not isinstance(raw_trace, dict):
        raise ValueError(f"Invalid trace {path}: expected top-level JSON object.")

    case_id = raw_trace.get("case_id")
    if not isinstance(case_id, str) or case_id.strip() == "":
        raise ValueError(f"Invalid trace {path}: field 'case_id' must be a non-empty string.")
    if case_id != expected_case_id:
        raise ValueError(
            f"Invalid trace {path}: field 'case_id'={case_id!r} does not match "
            f"dataset id {expected_case_id!r}."
        )

    events = raw_trace.get("events")
    if not isinstance(events, list):
        raise ValueError(f"Invalid trace {path}: field 'events' must be an array.")
    parsed_events = tuple(_parse_event(item, idx, path) for idx, item in enumerate(events))

    final = raw_trace.get("final")
    if not isinstance(final, dict):
        raise ValueError(f"Invalid trace {path}: field 'final' must be an object.")
    final_text = final.get("text")
    if final_text is not None and not isinstance(final_text, str):
        raise ValueError(
            f"Invalid trace {path}: field 'final.text' must be a string when provided."
        )

    return TraceRecord(
        case_id=case_id,
        events=parsed_events,
        final=TraceFinal(text=final_text, payload=final),
    )


def _parse_event(item: Any, index: int, path: Path) -> TraceEvent:
    if not isinstance(item, dict):
        raise ValueError(f"Invalid trace {path}: events[{index}] must be an object.")

    event_type = item.get("type")
    if not isinstance(event_type, str) or event_type.strip() == "":
        raise ValueError(f"Invalid trace {path}: events[{index}].type must be a non-empty string.")

    name = item.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError(
            f"Invalid trace {path}: events[{index}].name must be a string when provided."
        )

    return TraceEvent(
        type=event_type,
        name=name,
        input=item.get("input"),
        output=item.get("output"),
        error=item.get("error"),
        meta=item.get("meta"),
    )
