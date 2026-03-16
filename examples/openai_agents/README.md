# OpenAI Agents SDK Integration (Optional)

This adapter exports OpenAI Agents SDK traces into EvalOps Kit trace JSON files.

## Install

```bash
python -m pip install -e ".[dev]"
python -m pip install openai-agents
# or: python -m pip install -e ".[agents]"
```

## Minimal export flow

```python
from pathlib import Path

from agents import Agent, RunConfig, Runner
from evalops_kit.adapters.openai_agents import (
    EvalOpsAgentsCollector,
    get_processor,
    install_agents_processor,
)

collector = EvalOpsAgentsCollector(Path("traces"))
processor = get_processor(collector=collector)
install_agents_processor(processor, replace_existing=True)

agent = Agent(name="evalops-agent", instructions="You are concise and correct.")

for case_id, prompt in [("case-1", "Say hello.")]:
    result = Runner.run_sync(
        agent,
        prompt,
        run_config=RunConfig(
            trace_metadata={"case_id": case_id},
            workflow_name="evalops",
        ),
    )
    collector.set_final_output(case_id, str(result.final_output))
```

Use `replace_existing=True` when you want EvalOps traces to be the only trace sink.

## Notes

- Running real model calls requires network access and a valid API key.
- This example is documentation-only and is not executed in tests.
