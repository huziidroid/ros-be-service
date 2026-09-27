"""Loads SOUL.md once — the shared persona/tone/boundaries doc composed into every
agent's system prompt by build_agent() (see agent.py in this package).

"Persona consistency is an architectural property, not a prompting property" — every
agent under app/agents/ goes through build_agent(), so every agent automatically shares
this one file. Editing SOUL.md changes every agent's tone; no agent package should
define its own persona text.
"""

from functools import lru_cache
from pathlib import Path

from app.core.settings import settings


_SOUL_PATH = Path(__file__).parent / "SOUL.md"


@lru_cache(maxsize=1)
def get_soul() -> str:
    # str.replace, not .format(): SOUL.md is free-form prose an editor may add
    # other {braces} to later — .format() would break on those, replace() won't.
    text = _SOUL_PATH.read_text(encoding="utf-8").strip()
    return text.replace("{app_name}", settings.app_name)
