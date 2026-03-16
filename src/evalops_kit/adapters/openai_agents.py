"""Optional OpenAI Agents SDK adapter for EvalOps trace JSON files."""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SPAN_TYPE_MAP = {
    "function": "tool_call",
    "generation": "generation",
    "agent": "agent",
    "handoff": "handoff",
    "guardrail": "guardrail",
    "custom": "custom",
    "response": "response",
    "mcp_tools": "mcp_tools",
}


def agents_span_to_event(span: Any, *, include_export: bool = False) -> dict[str, Any]:
    """Convert one Agents SDK span into one EvalOps event."""
    return _agents_span_to_events(span, include_export=include_export)[0]


def _agents_span_to_events(span: Any, *, include_export: bool) -> list[dict[str, Any]]:
    span_data_export = _export_span_data(span)
    span_type = span_data_export.get("type")
    mapped_type = _SPAN_TYPE_MAP.get(span_type, "span") if isinstance(span_type, str) else "span"

    event: dict[str, Any] = {"type": mapped_type}
    name = _optional_non_empty_str(span_data_export.get("name"))
    if name is not None:
        event["name"] = name

    span_error = _json_safe(getattr(span, "error", None))
    if span_error is not None:
        event["error"] = span_error

    meta = _build_span_meta(
        span=span,
        span_type=span_type,
        span_data_export=span_data_export,
        include_export=include_export,
    )
    if meta:
        event["meta"] = meta

    events = [event]
    if mapped_type == "tool_call" and span_error is not None:
        tool_error: dict[str, Any] = {
            "type": "tool_error",
            "error": span_error,
        }
        if name is not None:
            tool_error["name"] = name
        if meta:
            tool_error["meta"] = dict(meta)
        events.append(tool_error)
    return events


def _build_span_meta(
    *,
    span: Any,
    span_type: Any,
    span_data_export: dict[str, Any],
    include_export: bool,
) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for attr_name in ("trace_id", "span_id", "parent_id", "started_at", "ended_at"):
        attr_value = getattr(span, attr_name, None)
        if attr_value is not None:
            meta[attr_name] = _json_safe(attr_value)

    if isinstance(span_type, str):
        meta["span_type"] = span_type

    if include_export:
        meta["span_data"] = _json_safe(span_data_export)

    return meta


def _export_span_data(span: Any) -> dict[str, Any]:
    span_data = getattr(span, "span_data", None)
    export_fn = getattr(span_data, "export", None)
    if not callable(export_fn):
        return {}
    exported = export_fn()
    if not isinstance(exported, dict):
        raise ValueError("span.span_data.export() must return a dict.")
    return exported


def _optional_non_empty_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _required_non_empty_str(value: Any, *, field_name: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    raise ValueError(f"{field_name} must be a non-empty string.")


def _case_id_from_metadata(metadata: dict[str, Any] | None, *, case_id_key: str) -> str:
    if not isinstance(metadata, dict):
        raise ValueError(
            f"trace metadata must be a dict and include {case_id_key!r} for EvalOps trace export."
        )
    case_id = metadata.get(case_id_key)
    return _required_non_empty_str(case_id, field_name=f"trace metadata key {case_id_key!r}")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:  # pragma: no cover - best effort conversion
            pass
    return str(value)


@dataclass
class _TraceState:
    trace_id: str
    case_id: str
    trace_name: str | None
    events: list[dict[str, Any]] = field(default_factory=list)
    ended: bool = False


class EvalOpsTraceBuffer:
    """In-memory buffer for spans and trace lifecycle state."""

    def __init__(self, *, case_id_key: str = "case_id") -> None:
        self._case_id_key = case_id_key
        self._traces: dict[str, _TraceState] = {}
        self._final_text_by_case: dict[str, str | None] = {}
        self._written_case_ids: set[str] = set()

    def on_trace_start(
        self, trace_id: str, name: str | None, metadata: dict[str, Any] | None
    ) -> None:
        normalized_trace_id = _required_non_empty_str(trace_id, field_name="trace_id")
        case_id = _case_id_from_metadata(metadata, case_id_key=self._case_id_key)
        self._traces[normalized_trace_id] = _TraceState(
            trace_id=normalized_trace_id,
            case_id=case_id,
            trace_name=_optional_non_empty_str(name),
        )

    def on_span_end(self, trace_id: str, events: list[dict[str, Any]]) -> None:
        state = self._traces.get(trace_id)
        if state is None:
            raise ValueError(f"Unknown trace_id {trace_id!r}; call on_trace_start first.")
        state.events.extend(events)

    def on_trace_end(self, trace_id: str) -> None:
        state = self._traces.get(trace_id)
        if state is None:
            raise ValueError(f"Unknown trace_id {trace_id!r}; call on_trace_start first.")
        state.ended = True

    def set_final_output(self, case_id: str, final_text: str | None) -> None:
        normalized_case_id = _required_non_empty_str(case_id, field_name="case_id")
        self._final_text_by_case[normalized_case_id] = final_text

    def pop_ready_records(self) -> list[tuple[str, dict[str, Any]]]:
        ready: list[tuple[str, dict[str, Any]]] = []
        for trace_id, state in list(self._traces.items()):
            if not state.ended:
                continue
            if state.case_id not in self._final_text_by_case:
                continue
            if state.case_id in self._written_case_ids:
                del self._traces[trace_id]
                continue

            final_payload: dict[str, Any] = {}
            final_text = self._final_text_by_case[state.case_id]
            if final_text is not None:
                final_payload["text"] = str(final_text)

            payload: dict[str, Any] = {
                "case_id": state.case_id,
                "events": _json_safe(state.events),
                "final": final_payload,
                "meta": {"trace_id": state.trace_id},
            }
            if state.trace_name is not None:
                payload["meta"]["trace_name"] = state.trace_name

            ready.append((state.case_id, payload))
            self._written_case_ids.add(state.case_id)
            del self._traces[trace_id]

        return ready


class EvalOpsAgentsCollector:
    """Thread-safe collector that writes EvalOps trace files from Agents spans."""

    def __init__(
        self,
        out_dir: Path,
        *,
        case_id_key: str = "case_id",
        include_export: bool = False,
    ) -> None:
        self._out_dir = Path(out_dir)
        self._include_export = include_export
        self._buffer = EvalOpsTraceBuffer(case_id_key=case_id_key)
        self._lock = threading.Lock()

    def on_trace_start(
        self, trace_id: str, name: str | None, metadata: dict[str, Any] | None
    ) -> None:
        with self._lock:
            self._buffer.on_trace_start(trace_id=trace_id, name=name, metadata=metadata)
            ready = self._buffer.pop_ready_records()
        self._write_ready_records(ready)

    def on_span_end(self, span: Any) -> None:
        events = _agents_span_to_events(span, include_export=self._include_export)
        trace_id = _required_non_empty_str(
            getattr(span, "trace_id", None),
            field_name="span.trace_id",
        )
        with self._lock:
            self._buffer.on_span_end(trace_id=trace_id, events=events)
            ready = self._buffer.pop_ready_records()
        self._write_ready_records(ready)

    def on_trace_end(self, trace_id: str) -> None:
        with self._lock:
            self._buffer.on_trace_end(trace_id=trace_id)
            ready = self._buffer.pop_ready_records()
        self._write_ready_records(ready)

    def set_final_output(self, case_id: str, final_text: str | None) -> None:
        with self._lock:
            self._buffer.set_final_output(case_id=case_id, final_text=final_text)
            ready = self._buffer.pop_ready_records()
        self._write_ready_records(ready)

    def _write_ready_records(self, records: list[tuple[str, dict[str, Any]]]) -> None:
        if not records:
            return
        self._out_dir.mkdir(parents=True, exist_ok=True)
        for case_id, payload in records:
            out_path = self._out_dir / f"{case_id}.json"
            out_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )


def _coerce_metadata(metadata: Any) -> dict[str, Any] | None:
    if metadata is None:
        return None
    if isinstance(metadata, dict):
        return metadata
    items = getattr(metadata, "items", None)
    if callable(items):
        return {str(key): value for key, value in metadata.items()}
    raise ValueError("trace.metadata must be a dict when provided.")


try:  # pragma: no cover - exercised only when optional dependency is installed
    from agents.tracing.processor_interface import TracingProcessor as _TracingProcessorBase
except Exception:  # pragma: no cover - import is optional by design
    _TracingProcessorBase = None


if _TracingProcessorBase is not None:  # pragma: no cover - optional dependency path

    class EvalOpsAgentsTracingProcessor(_TracingProcessorBase):  # type: ignore[misc]
        """TracingProcessor that forwards callbacks to EvalOpsAgentsCollector."""

        def __init__(self, collector: EvalOpsAgentsCollector) -> None:
            super().__init__()
            self.collector = collector
            self.errors: list[str] = []

        def on_trace_start(self, trace: Any, *args: Any, **kwargs: Any) -> None:
            self._capture(
                lambda: self.collector.on_trace_start(
                    trace_id=_required_non_empty_str(
                        getattr(trace, "trace_id", None),
                        field_name="trace.trace_id",
                    ),
                    name=_optional_non_empty_str(getattr(trace, "name", None)),
                    metadata=_coerce_metadata(getattr(trace, "metadata", None)),
                )
            )

        def on_span_start(self, span: Any, *args: Any, **kwargs: Any) -> None:
            self._capture(lambda: None)

        def on_span_end(self, span: Any, *args: Any, **kwargs: Any) -> None:
            self._capture(lambda: self.collector.on_span_end(span))

        def on_trace_end(self, trace: Any, *args: Any, **kwargs: Any) -> None:
            self._capture(
                lambda: self.collector.on_trace_end(
                    trace_id=_required_non_empty_str(
                        getattr(trace, "trace_id", None),
                        field_name="trace.trace_id",
                    )
                )
            )

        def shutdown(self, *args: Any, **kwargs: Any) -> None:
            self._capture(lambda: None)

        def force_flush(self, *args: Any, **kwargs: Any) -> None:
            self._capture(lambda: None)

        def _capture(self, callback: Callable[[], None]) -> None:
            try:
                callback()
            except Exception as exc:
                self.errors.append(str(exc))


def get_processor(
    *,
    collector: EvalOpsAgentsCollector | None = None,
    out_dir: Path | None = None,
    case_id_key: str = "case_id",
    include_export: bool = False,
) -> Any:
    """Build an EvalOps tracing processor if openai-agents is installed."""
    if _TracingProcessorBase is None:
        raise RuntimeError(
            "openai-agents is not installed. Install with `pip install openai-agents` "
            'or `pip install -e ".[agents]"`.'
        )
    if collector is None:
        if out_dir is None:
            raise ValueError("out_dir is required when collector is not provided.")
        collector = EvalOpsAgentsCollector(
            out_dir=out_dir,
            case_id_key=case_id_key,
            include_export=include_export,
        )
    return EvalOpsAgentsTracingProcessor(collector)


def install_agents_processor(processor: Any, *, replace_existing: bool = True) -> None:
    """Install tracing processor into OpenAI Agents SDK global tracing config."""
    try:
        if replace_existing:
            from agents.tracing import set_trace_processors

            set_trace_processors([processor])
            return

        from agents.tracing import add_trace_processor

        add_trace_processor(processor)
    except Exception as exc:  # pragma: no cover - optional dependency path
        raise RuntimeError(
            "Failed to install OpenAI Agents tracing processor. Ensure openai-agents is installed."
        ) from exc


__all__ = [
    "EvalOpsAgentsCollector",
    "EvalOpsTraceBuffer",
    "agents_span_to_event",
    "get_processor",
    "install_agents_processor",
]

if _TracingProcessorBase is not None:  # pragma: no cover - optional dependency path
    __all__.append("EvalOpsAgentsTracingProcessor")
