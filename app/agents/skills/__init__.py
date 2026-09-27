"""
Directory-discovered domain registry.

Every subdirectory here is a "skill": a business domain the router can classify a
message into. Each subpackage's __init__.py must export a module-level `SKILL: Skill`
(app/schemas/workflows/conversation.py::Skill). This module scans the directory once
at import time, in sorted order, and fails fast on a missing or duplicate `SKILL`.

Adding a new domain means adding a subdirectory here — nothing in this file changes.
"""

import importlib
import pkgutil
from pathlib import Path

from app.schemas.workflows.conversation import NON_SKILL_DOMAINS, Skill


def _discover_skills() -> dict[str, Skill]:
    registry: dict[str, Skill] = {}
    claimed_by: dict[str, str] = {}
    package_dir = Path(__file__).parent

    module_names = sorted(
        name for _, name, is_pkg in pkgutil.iter_modules([str(package_dir)]) if is_pkg
    )

    for module_name in module_names:
        module = importlib.import_module(f"{__name__}.{module_name}")
        skill = getattr(module, "SKILL", None)

        if skill is None:
            raise RuntimeError(
                f"app.agents.skills.{module_name} does not export a module-level "
                "SKILL (see app/schemas/workflows/conversation.py::Skill)."
            )
        if not isinstance(skill, Skill):
            raise RuntimeError(
                f"app.agents.skills.{module_name}.SKILL is not a Skill instance "
                f"(got {type(skill).__name__})."
            )
        if skill.domain in registry:
            raise RuntimeError(
                f"Duplicate domain '{skill.domain}': claimed by both "
                f"'{claimed_by[skill.domain]}' and '{module_name}'."
            )

        registry[skill.domain] = skill
        claimed_by[skill.domain] = module_name

    return registry


SKILL_REGISTRY: dict[str, Skill] = _discover_skills()


def is_known_domain(domain: str) -> bool:
    """True if `domain` is a registered skill or a NonSkillDomain outcome."""
    return domain in SKILL_REGISTRY or domain in NON_SKILL_DOMAINS
