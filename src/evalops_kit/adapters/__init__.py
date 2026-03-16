"""Optional runtime adapters for EvalOps Kit."""

from evalops_kit.adapters.openai_agents import (
    EvalOpsAgentsCollector,
    EvalOpsTraceBuffer,
    agents_span_to_event,
    get_processor,
    install_agents_processor,
)

__all__ = [
    "EvalOpsAgentsCollector",
    "EvalOpsTraceBuffer",
    "agents_span_to_event",
    "get_processor",
    "install_agents_processor",
]
