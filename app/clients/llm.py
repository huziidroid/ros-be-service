"""
OpenAI chat model client — the one place that constructs an LLM client, mirroring
app/clients/whatsapp.py and app/clients/redis.py for their respective external services.

app/agents/ (router, and every domain agent via app/agents/base/agent.py::build_agent())
asks for a model through get_chat_model(); nothing outside this module constructs
ChatOpenAI directly.
"""

from functools import cache

from langchain_openai import ChatOpenAI

from app.core.settings import settings


@cache
def get_chat_model(model: str | None = None, *, temperature: float = 0.0) -> ChatOpenAI:
    """
    Returns a cached ChatOpenAI instance for the given model/temperature pair.

    `model` defaults to settings.openai_default_model. Cached per (model, temperature)
    pair — cheap to call repeatedly rather than threading one instance through callers.
    """
    return ChatOpenAI(
        model=model or settings.openai_default_model,
        temperature=temperature,
        api_key=settings.openai_api_key,
    )
