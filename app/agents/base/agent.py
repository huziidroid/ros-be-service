"""
build_agent() — factory every agent under app/agents/ goes through.

Wraps LangChain's create_agent(), applying this app's shared persona and baseline
governance middleware. With no tools, it's a single structured-output call (used by
the router's classifier); with tools, it runs the full ReAct loop.
"""

from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agents.base.middleware import BASELINE_MIDDLEWARE
from app.agents.base.soul import get_soul
from app.clients.llm import get_chat_model


def build_agent(
    *,
    model: str | BaseChatModel | None = None,
    tools: Sequence[Callable[..., Any] | dict[str, Any]] = (),
    extra_middleware: Sequence[AgentMiddleware] = (),
    extra_instructions: str = "",
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    response_format: Any = None,
    name: str | None = None,
) -> Runnable[Any, Any]:
    """
    Build a LangChain agent with this app's baseline applied.

    Every call gets the shared persona (SOUL.md) and baseline governance middleware
    (PII redaction) ahead of anything in `extra_middleware`.

    `extra_instructions` appends static, caller-specific system-prompt content after
    the persona (e.g. the router's classification instructions) — keep it static so
    the prompt prefix stays cacheable. `response_format` supports structured output
    (e.g. a Pydantic model) with no `tools`, reading the result off
    `result["structured_response"]` instead of `result["messages"]`.

    `checkpointer` is required once any middleware in `extra_middleware` needs one
    (e.g. HumanInTheLoopMiddleware) — the caller owns that pairing, not this factory.
    """
    resolved_model: str | BaseChatModel = (
        model if isinstance(model, BaseChatModel) else get_chat_model(model)
    )
    system_prompt = get_soul()
    if extra_instructions:
        system_prompt = f"{system_prompt}\n\n{extra_instructions}"
    return create_agent(
        model=resolved_model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[*BASELINE_MIDDLEWARE, *extra_middleware],
        checkpointer=checkpointer,
        response_format=response_format,
        name=name,
    )
