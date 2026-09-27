"""
Measures the classifier against GOLDEN_SET — checks whether
routing_confidence_threshold is a calibrated number worth trusting.

Outside tests/ (pytest's testpaths) and marked `live_llm`: every case here is a real
OpenAI call — real cost, real network, so it doesn't run on a default `pytest`/CI
invocation. Run explicitly:

    pytest app/agents/eval/test_router.py -v -m live_llm

Add real-traffic-derived cases to golden_set.py over time; this seed set is small.
"""

import logging

import pytest

from app.agents.eval.golden_set import GOLDEN_SET
from app.agents.router.classifier import classify_message
from app.core.settings import settings


logger = logging.getLogger(__name__)
pytestmark = pytest.mark.live_llm


def _bucket(confidence: float, n_bins: int = 5) -> int:
    return min(int(confidence * n_bins), n_bins - 1)


async def _compute_ece() -> float:
    bins: dict[int, list[tuple[float, bool]]] = {}
    for case in GOLDEN_SET:
        classification = await classify_message(case.text)
        primary = classification.primary
        confidence = primary.confidence if primary else 0.0
        correct = primary is not None and primary.domain == case.expected_domain
        bins.setdefault(_bucket(confidence), []).append((confidence, correct))

    total = sum(len(entries) for entries in bins.values())
    ece = 0.0
    for entries in bins.values():
        bin_confidence = sum(c for c, _ in entries) / len(entries)
        bin_accuracy = sum(1 for _, correct in entries if correct) / len(entries)
        ece += (len(entries) / total) * abs(bin_accuracy - bin_confidence)
    return ece


async def test_classifier_ece_against_golden_set() -> None:
    ece = await _compute_ece()
    logger.info("golden_set_ece", extra={"ece": ece})
    # ECE <= 0.10 means the confidence threshold is a reasonable signal. Above
    # that, flip settings.routing_use_self_consistency instead of trusting it.
    assert ece <= 0.10, (
        f"ECE {ece:.4f} exceeds 0.10 — do not trust "
        f"routing_confidence_threshold ({settings.routing_confidence_threshold}) as "
        "a calibrated signal. Enable routing_use_self_consistency instead."
    )


async def test_classifier_accuracy_against_golden_set() -> None:
    correct = 0
    for case in GOLDEN_SET:
        classification = await classify_message(case.text)
        primary = classification.primary
        if primary is not None and primary.domain == case.expected_domain:
            correct += 1
    accuracy = correct / len(GOLDEN_SET)
    logger.info("golden_set_accuracy", extra={"accuracy": accuracy})
    # Loose bound for this seed set — tighten as the golden set grows.
    assert accuracy >= 0.7
