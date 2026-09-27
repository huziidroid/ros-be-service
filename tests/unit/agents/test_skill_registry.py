"""
Unit tests for app.agents.skills — the directory-discovered domain registry.
"""

import sys
import types
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from app.agents import skills
from app.schemas.workflows.conversation import NonSkillDomain, Skill


def test_registry_is_discovered_at_import_and_non_empty() -> None:
    assert skills.SKILL_REGISTRY, "SKILL_REGISTRY should not be empty."


@pytest.mark.parametrize("domain", ["order", "support", "payment", "catalog"])
def test_expected_domains_are_registered(domain: str) -> None:
    assert domain in skills.SKILL_REGISTRY
    skill = skills.SKILL_REGISTRY[domain]
    assert isinstance(skill, Skill)
    assert skill.domain == domain
    assert skill.description  # feeds the classifier prompt — must not be empty


@pytest.mark.parametrize("domain", list(NonSkillDomain))
def test_non_skill_outcomes_are_known_domains(domain: NonSkillDomain) -> None:
    assert skills.is_known_domain(domain)


def test_registered_skill_domains_are_known_domains() -> None:
    for domain in skills.SKILL_REGISTRY:
        assert skills.is_known_domain(domain)


def test_unregistered_domain_is_not_known() -> None:
    assert not skills.is_known_domain("not_a_real_domain")


def _fake_iter_modules(names: list[str]) -> "Iterator[tuple[object, str, bool]]":
    for name in names:
        yield (object(), name, True)


def test_discover_skills_fails_fast_on_missing_skill_export() -> None:
    broken = types.ModuleType("app.agents.skills.broken")  # no SKILL attribute

    with (
        patch.object(
            skills.pkgutil,
            "iter_modules",
            return_value=_fake_iter_modules(["broken"]),
        ),
        patch.object(skills.importlib, "import_module", return_value=broken),
        pytest.raises(RuntimeError, match="does not export a module-level SKILL"),
    ):
        skills._discover_skills()


def test_discover_skills_fails_fast_on_duplicate_domain() -> None:
    module_a = types.ModuleType("app.agents.skills.a")
    module_a.SKILL = Skill(domain="order", description="a")  # type: ignore[attr-defined]
    module_b = types.ModuleType("app.agents.skills.b")
    module_b.SKILL = Skill(domain="order", description="b")  # type: ignore[attr-defined]

    modules_by_name = {"a": module_a, "b": module_b}

    with (
        patch.object(
            skills.pkgutil,
            "iter_modules",
            return_value=_fake_iter_modules(["a", "b"]),
        ),
        patch.object(
            skills.importlib,
            "import_module",
            side_effect=lambda name: modules_by_name[name.rsplit(".", 1)[-1]],
        ),
        pytest.raises(RuntimeError, match="Duplicate domain 'order'"),
    ):
        skills._discover_skills()


def test_discover_skills_fails_fast_on_wrong_skill_type() -> None:
    broken = types.ModuleType("app.agents.skills.broken")
    broken.SKILL = "not a Skill instance"  # type: ignore[attr-defined]

    with (
        patch.object(
            skills.pkgutil,
            "iter_modules",
            return_value=_fake_iter_modules(["broken"]),
        ),
        patch.object(skills.importlib, "import_module", return_value=broken),
        pytest.raises(RuntimeError, match="is not a Skill instance"),
    ):
        skills._discover_skills()


# Guard against sys.modules pollution from the fake module names used above leaking
# into other tests, since types.ModuleType() doesn't register itself automatically —
# nothing to clean up here in practice, but kept explicit for future readers.
assert "app.agents.skills.broken" not in sys.modules
