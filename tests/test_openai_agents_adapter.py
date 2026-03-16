from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalops_kit.adapters.openai_agents import EvalOpsAgentsCollector, agents_span_to_event
from evalops_kit.trace import load_trace


class StubSpanData:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def export(self) -> dict[str, Any]:
        return dict(self._payload)


class StubSpan:
    def __init__(
        self,
        *,
        trace_id: str = "trace-1",
        span_id: str = "span-1",
        parent_id: str | None = None,
        started_at: str = "2026-01-01T00:00:00Z",
        ended_at: str = "2026-01-01T00:00:01Z",
        error: Any = None,
        span_data_export: dict[str, Any] | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_id = parent_id
        self.started_at = started_at
        self.ended_at = ended_at
        self.error = error
        self.span_data = StubSpanData(span_data_export or {"type": "custom"})


def test_agents_span_to_event_maps_function_span_to_tool_call() -> None:
    span = StubSpan(span_data_export={"type": "function", "name": "lookup_weather"})

    event = agents_span_to_event(span)

    assert event["type"] == "tool_call"
    assert event["name"] == "lookup_weather"
    assert "span_data" not in event["meta"]


def test_tool_span_with_error_produces_tool_call_and_tool_error(tmp_path: Path) -> None:
    collector = EvalOpsAgentsCollector(out_dir=tmp_path)
    collector.on_trace_start(trace_id="trace-1", name="evalops", metadata={"case_id": "case-1"})
    collector.on_span_end(
        StubSpan(
            error={"message": "boom"},
            span_data_export={"type": "function", "name": "search_docs"},
        )
    )

    collector.on_trace_end("trace-1")
    collector.set_final_output("case-1", "done")

    payload = json.loads((tmp_path / "case-1.json").read_text(encoding="utf-8"))
    event_types = [event["type"] for event in payload["events"]]
    assert event_types == ["tool_call", "tool_error"]
    assert payload["events"][0]["name"] == "search_docs"
    assert payload["events"][1]["name"] == "search_docs"
    assert payload["events"][1]["error"] == {"message": "boom"}


def test_collector_writes_trace_after_trace_end_and_final_set(tmp_path: Path) -> None:
    collector = EvalOpsAgentsCollector(out_dir=tmp_path)
    collector.on_trace_start(trace_id="trace-2", name=None, metadata={"case_id": "case-2"})
    collector.on_span_end(
        StubSpan(
            trace_id="trace-2",
            span_id="span-2",
            span_data_export={"type": "generation"},
        )
    )
    collector.on_trace_end("trace-2")

    trace_path = tmp_path / "case-2.json"
    assert not trace_path.exists()

    collector.set_final_output("case-2", None)

    assert trace_path.exists()
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert payload["case_id"] == "case-2"
    assert payload["events"][0]["type"] == "generation"
    assert payload["final"] == {}
    assert payload["meta"]["trace_id"] == "trace-2"
    assert "trace_name" not in payload["meta"]

    trace = load_trace(trace_path, expected_case_id="case-2")
    assert trace.case_id == "case-2"
    assert trace.events[0].type == "generation"
    assert trace.final.text is None
