# Message Routing — Implementation Plan

Status: **LOCKED.** Design finalized, not yet implemented. This consolidates every
architecture decision made while designing how inbound WhatsApp messages get classified
and routed to the right domain (orders, support, payments, catalog, and future domains).
Nothing in this document is open — any future change is a new decision, not an edit to
erase what's here.

## 1. Goals

- Classify each inbound message into one or more business domains, or recognize it as
  chitchat / out-of-scope / genuinely ambiguous.
- Scale to new domains without editing routing internals (directory-discovered, not
  hard-coded).
- Be provably not-irresponsible: no confidence threshold trusted without measuring it,
  no concurrency guarantee weaker than what's structurally necessary, no unbounded cost
  growth as conversations get longer.
- Use one agent framework end-to-end — LangChain for both the classifier/router step and
  every domain agent — rather than mixing frameworks across layers of the same system.
- Align with LangChain's own documented multi-agent patterns once real domain agents are
  built, rather than reinventing conversation state LangGraph/Temporal already provide.

## 2. Architecture decisions (summary)

| Concern | Decision | Why |
|---|---|---|
| Orchestration | One long-running Temporal workflow per **conversation** (`tenant_waba_id` + `wa_id`), not per message. New messages arrive as **signals** via `signal_with_start`. | Temporal's official LangGraph plugin uses exactly this pattern in production. Signals to one workflow execution process sequentially — this removes the memory race condition structurally, not via a best-effort lock. |
| Routing topology | **Supervisor** (our classifier) + N domain agents. Domain agents get exactly one handoff tool: `transfer_to_supervisor`. No agent-to-agent mesh. | Full mesh is O(N²) and industry sources call supervisor "the 2026 production default" even at just 5 agents. |
| Skill/domain registry | Directory-discovered (`app/agents/skills/<domain>/__init__.py` exporting a `SKILL` object), loaded at import time, fail-fast on missing/duplicate. `IntentMatch.domain: str`, validated at runtime against the live registry — not a hard-coded `Literal`. | Explicit requirement: adding domain 5 must not mean editing a registry file. |
| Code location | Everything lives under `app/agents/` — the router (supervisor/classifier) and every domain agent, as sibling subpackages. No separate `app/routing/` package. | The router/agents split only made sense while they were two different frameworks. Now that both are LangChain, keeping them in separate top-level packages doesn't reflect a real boundary — it's one system, one package. |
| Classifier backend | LangChain's model/structured-output primitives, called directly — no backend-swap abstraction. | One framework, one implementation. Matches LangChain's own Router pattern reference implementation. DSPy is not a near-term plan; the abstraction that would have made it a config change was speculative cost for a swap that isn't happening — dropped. |
| Model provider | OpenAI, via `app/clients/llm.py`. | Decided; not Anthropic. Prompt-caching mechanics (§7) follow OpenAI's model, not Anthropic's. |
| Multi-intent | `MessageClassification.intents: list[IntentMatch]`, capped at 3. | One message can span domains ("check my order and your return policy"). |
| Confidence | Treated as an **ordering signal**, not a calibrated probability, until measured. Expected Calibration Error (ECE) computed against the golden eval set before any threshold ships. If ECE > 0.10, fall back to self-consistency (classify twice, only dispatch on agreement) rather than trusting a threshold. Implemented as a manual flip, not an auto-detected mode: `settings.routing_use_self_consistency` (`ROUTING_USE_SELF_CONSISTENCY` env var, default `False`) is set by a human after running the eval harness and finding ECE > 0.10 — `app/agents/router/__init__.py::route_message` then classifies twice, only trusting the number on agreement (bypasses the threshold entirely via `decide_action(confidence_threshold=0.0, ...)`), and forces `CLARIFY` on disagreement via `decide_action(force_clarify=True, ...)`. Categorical outcomes (chitchat/out_of_scope) never get a second pass — there's no confidence number in play for them to double-check. | LLM verbal confidence is known to be systematically miscalibrated post-RLHF. |
| Out-of-scope vs. unknown vs. chitchat | Three distinct outcomes, not one catch-all "unknown." | Conflating them means an off-topic question and a genuinely ambiguous order question get the same (wrong) treatment. |
| Short-term (routing) memory | Last 6 turns / 30 min inactivity, lives in the conversation workflow's own state — no separate Redis store. | Temporal workflow state is already durable; a second store would be a second system of record for the same fact. |
| Per-agent (domain) memory | Deferred to Phase 2 (first real domain agent). Plan: structured `AgentState` fields for business facts + LangChain's `SummarizationMiddleware` for raw transcript growth. | Different problem, different scope — only matters once an agent has extended back-and-forth. |
| Mem0 | Evaluated, not adopted for either memory tier. | Built for cross-session personalization via vector search + its own LLM extraction cost — the wrong shape and cost for a bounded 6-turn buffer or a single agent's working memory. May be revisited later for genuine long-term customer personalization inside a core agent, not for routing. |
| Cost: token/$$ | OpenAI's automatic prompt caching: keep the static system prompt (Soul + domain descriptions) as a stable, identical prefix on every call, dynamic content (customer message, recent turns) after it. | OpenAI caches automatically for prompts over ~1024 tokens and discounts repeated prefix tokens — no manual cache-breakpoint API like Anthropic's `cache_control`; the only thing we control is prompt ordering (static first, dynamic last) so the cacheable prefix actually stays identical call to call. |
| Agent construction | Composition, not inheritance: `app/agents/base/agent.py::build_agent()` is a factory wrapping LangChain's `create_agent()`, not a base class every agent subclasses. The router's classifier (`app/agents/router/classifier.py`) goes through it too — no exception for the no-tool, structured-output case — via a `response_format=MessageClassification` argument and an `extra_instructions` parameter that appends the classifier's static skill-description prompt after the Soul, reading the result off `result["structured_response"]` rather than `result["messages"]`. | Matches LangChain's own architecture (`create_agent` is a factory) and avoids the deep-inheritance trap that makes agent codebases unmaintainable as they grow. Shared behavior is extracted into the factory's defaults and into middleware, not into a class hierarchy. Routing the classifier through the same factory is what makes the "Safety & governance" row below actually true for routing calls, not just future domain agents. |
| Persona/tone | `SOUL.md`, loaded once via `app/agents/base/soul.py`, composed into every prompt (router now, every domain agent later) inside `build_agent()`. Product name is a `{app_name}` placeholder in `SOUL.md`, substituted from `settings.app_name` (`APP_NAME` env var) at load time — never hardcoded in prose (`SOUL.md`, the classifier's system prompt, or anywhere else). | "Persona consistency is an architectural property, not a prompting property." Living inside `base/` means it's applied automatically by the one factory every agent goes through. One env var for the product name means a rename is a one-line config change, not a grep-and-replace across every prompt. |
| LLM client | `app/clients/llm.py` — the model/provider client, alongside `app/clients/whatsapp.py` and `app/clients/redis.py`. | Existing project convention: anything that talks to an external service lives in `clients/`, regardless of which internal layer (agents, activities) calls it. |
| Safety & governance | `app/agents/base/middleware.py` holds the baseline middleware stack applied by `build_agent()` to every agent: `PIIMiddleware` (redact before model input and before logging) and `HumanInTheLoopMiddleware` (per-tool `interrupt_on` policy — read-only tools auto-approved, state-changing tools like cancel/refund require approval). | These are LangChain's own built-in middleware, not custom-built governance — same "don't reinvent what the framework already provides" principle applied elsewhere in this plan. |
| Checkpointer | `AsyncPostgresSaver`, required once `HumanInTheLoopMiddleware` is used (interrupts must survive a pause). Same durability need the `ConversationWorkflow` already has. | No new infrastructure — confirms the orchestration decision in §5 is the right foundation for governance too, not an unrelated add-on. |
| Long-term memory | Not built, not currently needed. If a real cross-conversation personalization need appears later, the documented path is LangGraph's `PostgresStore` against the existing Postgres database — not Mem0. | Short-term (Tier 1/Tier 2, see below) is already durable via workflow state. Long-term/cross-session is a distinct LangGraph concept (`Store`, namespace+key) with no current requirement driving it. |
| Staleness | 30-min inactivity timer resets `active_domain` to cold (conversation stays alive). ~7-day total inactivity lets the workflow complete; `signal_with_start` transparently starts a fresh one next time. | Prevents a stale `active_domain` from wrongly capturing an unrelated message weeks later. |
| Workflow history growth | `continue-as-new` triggered by **either** of two bounds, matching "every N signals or T hours": a signal-count counter (`_CONTINUE_AS_NEW_EVERY = 200`, checked after each processed message) or a wall-clock deadline (`_CONTINUE_AS_NEW_MAX_AGE = timedelta(hours=24)`, computed once via `workflow.now()` at the top of `run()`, re-checked both on the idle-timeout path and the per-signal path). Carries forward only compact state (`active_domain`, last 6 turns, recent wamids) via `ConversationWorkflowState`. | Keeps Temporal replay cost flat regardless of total conversation length. Count alone leaves a gap: a conversation with a steady but infrequent trickle of messages might never idle long enough to close and never rack up 200 signals — the time bound closes that gap. |
| Eval | **Deviated from the original DeepEval/CI plan.** Implemented as a hand-rolled ECE + accuracy script (`app/agents/eval/test_router.py`, golden set in `app/agents/eval/golden_set.py`), covering per-domain, multi-intent, chitchat, out-of-scope, ambiguous/low-confidence, and memory-dependent-follow-up cases as originally scoped — but gated behind a `live_llm` pytest marker (registered in `pyproject.toml`) and **excluded from the default test run and CI**, since it makes real, billed LLM calls. Run explicitly and locally (or in a deliberate, separate CI job) when re-measuring ECE, e.g. before flipping `routing_use_self_consistency`. | DeepEval was evaluated but not adopted: the golden-set/ECE logic it would add value on top of is a small, custom calculation (binned confidence vs. accuracy), and a hand-rolled script avoids a new dependency for a computation that's a few dozen lines either way. Keeping it out of CI is a cost decision, not an oversight — every CI run would otherwise cost real OpenAI spend on every commit. |
| Dispatch, before domain agents exist | Every `RoutingAction` (including `DISPATCH`/`DISPATCH_MULTI`) resolves to a WhatsApp text reply via a `send_whatsapp_reply` activity. `DISPATCH` names the domain it routed to. | Phase 1 has no real domain agent yet (Phase 2). Without a reply, `DISPATCH` is a silent no-op and the routing/clarify flow can't be tested end-to-end before Phase 2 exists. |
| Media ingestion (text today, audio/etc. later) | One `extract_text` activity, dispatched by `message.message_type` via a flat lookup table in a single module — not the directory-discovered pattern used for skills. Today: one branch, `"text"` (passthrough). Every other type returns "unsupported" today; the workflow acknowledges plainly rather than crashing. | WhatsApp's message types are a small, closed set defined by Meta's API contract, not an open business concept we're growing — the discovery-registry ceremony used for skills doesn't earn its keep here. Runs as a plain activity, not a child workflow: Temporal's own guidance reserves child workflows for fan-out over many independent items or a separate execution lifecycle, neither of which applies to one media step on one message. |
| Workflow/activity boundary | `extract_text`, the classifier call (`route_message`), and `send_whatsapp_reply` are each `workflow.execute_activity(...)` calls inside `ConversationWorkflow` — never bare function calls in workflow code. | Temporal workflows must be deterministic; anything that does real I/O (LLM calls, Graph API calls, HTTP) has to run in an activity, full stop. Earlier prose describing "run `route_message()`" inside the workflow was imprecise about this — corrected here before Phase 1 is built. |

## 3. Schemas — `app/schemas/workflows/conversation.py`

Not a separate `app/schemas/routing.py`: every routing type here exists to serve
`ConversationWorkflow` — there's no other consumer — so a second module didn't
reflect a real boundary. `Skill`, the signal payload, `ConversationWorkflowConfig`
(§5), `ConversationWorkflowState`, and the activity I/O types (`ExtractedText`,
`ClassifyInput`, `SendReplyInput`) all live in this same file.

```python
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field

from app.core.settings import settings

class IntentMatch(BaseModel):
    domain: str  # validated against live SKILL_REGISTRY + {"chitchat", "out_of_scope"}
    sub_intent: str | None = None
    confidence: float
    entities: dict[str, Any] = Field(default_factory=dict)

class MessageClassification(BaseModel):
    intents: list[IntentMatch] = Field(max_length=settings.classify_max_intents)

    @property
    def primary(self) -> IntentMatch | None:
        return max(self.intents, key=lambda i: i.confidence, default=None)

@dataclass
class ConversationTurn:
    role: str  # "inbound" | "outbound"
    text: str | None  # head+tail truncated (first 300 + last 200 chars) before storage
    domain: str | None = None

class RoutingAction(StrEnum):
    DISPATCH = "dispatch"
    DISPATCH_MULTI = "dispatch_multi"
    CLARIFY = "clarify"
    DEFER_OUT_OF_SCOPE = "defer_out_of_scope"
    CHITCHAT_REPLY = "chitchat_reply"

@dataclass
class RoutingDecision:
    action: RoutingAction
    classification: MessageClassification
    primary_domain: str | None = None      # best-guess domain, set even on CLARIFY
    secondary_domains: list[str] = field(default_factory=list)
```

Note the fix baked in here: `primary_domain` must be populated with the best-guess domain
even when `action == CLARIFY` (the sub-threshold guess), not left `None`. Missing this was
a bug caught during design review — without it, the clarify-then-answer fast path silently
does nothing.

`MessageClassification.intents`' `max_length` reads `settings.classify_max_intents`
directly at class-definition time — safe here (unlike reading settings inside
`ConversationWorkflow` itself, §5): this validation runs inside the `classify`
*activity*, not in replayed workflow code, so it isn't subject to the same
determinism constraint.

These types stay in `app/schemas/` per the existing project convention (cross-module
schema-like types don't live scattered across the modules that use them).

## 4. `app/agents/` — directory structure

Everything LangChain-based lives here: the router (supervisor) and every domain agent,
as sibling subpackages sharing one persona file. There is no separate `app/routing/`
package.

```
app/agents/
  __init__.py              # package marker only — nothing to export at this level

  base/                      # the one seam every agent/feature goes through — composition, not inheritance
    __init__.py
    agent.py                   # build_agent(...) -> factory wrapping LangChain's create_agent()
    soul.py                    # get_soul() -> str, loads SOUL.md, lru_cache(1)
    SOUL.md                    # human-editable persona/tone/boundaries doc
    middleware.py               # baseline stack build_agent() applies to everything: PIIMiddleware,
                                # HumanInTheLoopMiddleware (per-tool interrupt_on policy)

  router/                   # the supervisor: classifies, decides, dispatches
    __init__.py               # route_message(message, memory) -> RoutingDecision — the one public hook
    classifier.py              # LangChain structured-output classifier, called directly — no backend abstraction
    cascade.py                  # classify_with_cascade(): pass 1 cheap, pass 2 memory-enriched retry
    decide.py                   # decide_action(): chitchat/out_of_scope/clarify/dispatch/dispatch_multi

  skills/                    # directory-discovered domain registry
    __init__.py                # scans this directory (sorted), builds SKILL_REGISTRY, fail-fast on dup/missing SKILL
    test_registry.py            # CI: every skill package well-formed — catches a broken package in review, not at boot
    order/
      __init__.py                # SKILL = Skill(domain="order", description=..., workflow=None)
                                  # Phase 2+: this package also gains the actual agent, its tools,
                                  # and its AgentState — the SKILL registration and the agent
                                  # implementation live together once the agent exists.
    support/
      __init__.py
    payment/
      __init__.py
    catalog/
      __init__.py

  eval/                      # shared eval harness — grows as domain agents are added
    golden_set.py               # labeled messages: per-domain, multi-intent, chitchat, out_of_scope, ambiguous
    test_router.py              # DeepEval, computes ECE against golden_set, gates CI
    # test_order_agent.py, etc. — added in Phase 2+ once a domain agent exists to test
```

`Skill` dataclass (defined in `app/schemas/workflows/conversation.py`, used by
`app/agents/skills/`): `domain: str`, `description: str` (feeds the router's prompt),
`workflow: type | None` (`None` = classifiable but not built yet),
`confidence_threshold: float = 0.6`.

Activities called by `ConversationWorkflow` live under `app/activities/` — following the
existing project convention (`app/activities/message_intake.py`, `tenant_onboarding.py`),
not inside `app/agents/`, since activities are the I/O boundary, not agent logic:

```
app/activities/
  message_ingestion.py   # extract_text(message) -> ExtractedText — flat dispatch by
                          # message_type; one branch ("text") today, "unsupported"
                          # result for everything else. Audio's future branch
                          # (media download + transcode-if-needed + transcription)
                          # slots in here without touching the workflow.
  conversation.py        # send_whatsapp_reply(...) — thin activity wrapper over
                          # app/clients/whatsapp.py::send_text_message. classify(...) —
                          # thin activity wrapper over app/agents/router's route_message,
                          # since that call is itself an LLM call (I/O) and can't run
                          # as a bare function inside the workflow.
```

## 5. Orchestration — `ConversationWorkflow`

Replaces per-message `MessageIntakeWorkflow` as the durability boundary for routing.

- Workflow ID: `conv-{tenant_waba_id}-{wa_id}`.
- Started via `signal_with_start("new_message", ...)` — first message creates it,
  subsequent ones signal the existing execution. Callers never need to check if one
  already exists.
- Config vs. state — deliberately two separate dataclasses, not one:
  `ConversationWorkflowConfig` (`idle_minutes`, `close_days`, `memory_turns`) is read
  from `settings.routing_*` exactly once, by `services/intake.py` (plain code, not
  workflow code), at the moment a conversation's workflow is started —
  `ConversationWorkflowConfig.from_settings()` — and passed in as `run()`'s own
  argument. `ConversationWorkflow` itself never imports `app.core.settings`: reading
  live settings inside workflow code would be a determinism hazard, since settings
  could change between a workflow's original run and a later replay. `config` is
  carried forward unchanged through every `continue-as-new`; `state`
  (`active_domain`, `recent_turns`, `seen_wamids`) changes signal to signal and is
  rebuilt fresh into the next `continue-as-new`.
- In-workflow state: `active_domain: str | None`, `recent_turns: list[ConversationTurn]`
  (bounded to `config.memory_turns`), `seen_wamids: list[str]` (bounded to a fixed
  technical constant — see §10 — carried across `continue-as-new`).
- Per signal (new message), every I/O step below is `workflow.execute_activity(...)` —
  none of this is a bare function call in workflow code (see §2, "workflow/activity
  boundary"):
  1. Dedup check against `seen_wamids` (replaces the old per-`wamid` workflow-ID dedup trick).
  2. `extract_text` activity — today, a passthrough for `message_type == "text"`; any
     other type comes back "unsupported" and short-circuits to step 5 with an
     acknowledgment reply saying so, skipping classification entirely.
  3. If `active_domain` is set and not stale → invoke that domain's agent directly, skip
     classification (Phase 2+, once a domain agent exists).
  4. Else → classifier activity (`route_message`, the stateless classify+decide step) →
     produces a `RoutingDecision`.
  5. `send_whatsapp_reply` activity, for every `RoutingAction` outcome — including
     `DISPATCH`/`DISPATCH_MULTI`, which (until Phase 2) reply naming the domain routed
     to rather than actually invoking an agent. This is what makes the full routing +
     clarify flow testable end-to-end before any domain agent is built.
  6. Update `recent_turns`, reset the inactivity timer (`config.idle_minutes`).
- Timers: 30-min inactivity → reset `active_domain` to `None` (stay alive). ~7-day total
  inactivity → let the workflow complete.
- `continue-as-new` on a schedule (e.g., every N signals or T hours) to bound history size.

This is built from the start — there is no interim per-message-workflow phase. Per §9,
`ConversationWorkflow` and the router go live together as Phase 1.

## 6. Confidence handling — concrete mechanics

1. Before shipping `routing_confidence_threshold`, run the golden eval set through the
   classifier and compute ECE (Expected Calibration Error: weighted average of
   `|accuracy - confidence|` per confidence bin).
2. If ECE ≤ 0.10: the threshold is a reasonable signal, ship it, re-measure on every
   model/prompt version bump (calibration doesn't transfer across versions).
3. If ECE > 0.10: don't ship a threshold-gated decision. Use self-consistency instead —
   classify twice; dispatch only if both calls agree on the primary domain; otherwise
   `CLARIFY`. Costs one extra model call per message but doesn't depend on a number we
   can't trust.

## 7. Cost efficiency — prompt caching

The classifier's system prompt (Soul + skill descriptions) is identical on every call,
for every tenant, all day. Keep it as a stable, identical prefix (static content first,
dynamic content — customer message, recent turns — after it); OpenAI caches automatically
for prompts over ~1024 tokens and discounts repeated prefix tokens, no manual
cache-breakpoint API to call. Never let dynamic content leak into that prefix region —
that's what actually breaks the cache hit, not a missing API call.

## 8. Settings additions

```python
openai_api_key: SecretStr
routing_confidence_threshold: float = 0.6   # do not trust blindly — see §6
routing_memory_turns: int = 6
routing_conversation_idle_minutes: int = 30   # soft reset of active_domain
routing_conversation_close_days: int = 7      # hard close, workflow completes
classify_max_intents: int = 3
```

## 9. Phasing (recommended order)

**Phase 0 — Foundation, no behavior change.**
`app/schemas/workflows/conversation.py`, `app/agents/skills/` (all 4 domains, `workflow=None`),
`app/agents/base/` (`agent.py`, `soul.py` + `SOUL.md`, `middleware.py` with baseline
`PIIMiddleware`), `app/clients/llm.py`, `app/agents/skills/test_registry.py`. Zero
production risk — `HumanInTheLoopMiddleware` and its checkpointer requirement land in
Phase 2, once there's an actual state-changing tool call to gate.

**Phase 1 — Router + orchestration together.**
There is no interim per-message-workflow step — `ConversationWorkflow`
(`signal_with_start`, timers, `continue-as-new`) and the router
(`app/agents/router/classifier.py`, `cascade.py`, `decide.py`, prompt-ordering for
caching per §7) land together, plus the three activities: `app/activities/
message_ingestion.py::extract_text` (text-only today, "unsupported" for every other
message type) and `app/activities/conversation.py::classify` / `send_whatsapp_reply` /
`send_clarify_options`. Every `RoutingAction` — including `DISPATCH`/`DISPATCH_MULTI`,
before any real domain agent exists — resolves to a reply via `send_whatsapp_reply`
(plain text) or, for `CLARIFY`, `send_clarify_options` (WhatsApp list-interactive, per
§10) naming the domain it routed to or offering the live `SKILL_REGISTRY` domains to
pick from. This is what makes the full routing + clarify flow testable end-to-end in
this phase, without waiting on Phase 2's domain agent. Migrate `services/intake.py`/
webhook path to signal instead of starting per-message workflows. This is where the
concurrency race condition is structurally closed from day one. Build `app/agents/eval/`
and **measure ECE against real traffic here** — flip `settings.routing_use_self_consistency`
if it comes back above 0.10.

**Phase 2 — First real domain agent (order) + per-agent memory.**
Build the order agent inside `app/agents/skills/order/` via `build_agent()`, its own
`AgentState`, one `transfer_to_supervisor` tool, `SummarizationMiddleware` for its own
message history. Classify each tool by risk (`get_order_status` auto-approved,
`cancel_order`/`issue_refund` require approval) and wire `HumanInTheLoopMiddleware`'s
`interrupt_on` accordingly; stand up `AsyncPostgresSaver` as the checkpointer this
requires. Extend `app/agents/eval/` with a long-conversation (25+ message) scenario.

## 10. Implementation hardening (from the earlier stress test, still applies)

These don't change with the LangChain/orchestration decisions above — they're about
WhatsApp's API constraints and defensive handling, independent of framework choice.

- **Clarifying replies use WhatsApp's list interactive type, not buttons.** Button-type
  messages cap at 3 options; there are already 4 domains. Implemented via
  `RoutingDecision.available_domains` (the live `SKILL_REGISTRY`'s domains at
  classification time, set by `decide_action`), `ClarifyReplyInput`, and
  `app/activities/conversation.py::send_clarify_options`, which builds the list payload
  (one row per domain, row `id` == domain name so the customer's tap round-trips as an
  unambiguous domain string) and calls `app/clients/whatsapp.py::send_interactive_message`.
  `ConversationWorkflow._send_clarify` falls back to a plain-text reply only if
  `available_domains` is empty (defensive — `SKILL_REGISTRY` is fail-fast at import, so
  this shouldn't happen in practice).
- **Stored turn text is head+tail truncated (first 300 + last 200 chars), not plain
  head truncation, before being kept in memory.** Bounds storage and prompt-token cost
  regardless of message length, while still catching the actual ask when it lands at the
  end of a long, rambling message rather than the start. No extra LLM call — this is a
  cheap, deterministic bound, not a summarization step. Summarization (`SummarizationMiddleware`,
  Phase 2) is a different tool for a different problem: compressing a genuinely long
  transcript in a domain agent's own working memory, not bounding one stored turn in the
  router's short 6-turn buffer, where an added LLM call on every long message would cost
  more than the signal it recovers.
- **`entities` in `IntentMatch` is treated as untrusted input downstream** — never
  interpolated directly into a prompt, query, or anything else without validation.
- **An outright classification failure (API error, exhausted retries) is not the same
  as low confidence, and must not be handled the same way.** Low confidence is a valid
  `MessageClassification` result that `decide_action` routes to `CLARIFY`. An exception
  gets a bounded retry ceiling and then a generic "having trouble, try again shortly"
  reply — never an indefinitely stuck workflow waiting on a retry that keeps failing.
- **The skill loader iterates the directory in sorted order.** Filesystem scan order
  isn't guaranteed stable across restarts, and that order feeds into the classifier's
  system prompt — unsorted iteration means a non-deterministic prompt between restarts.

## 11. What this actually is, plainly stated

`build_agent()` wraps LangChain's `create_agent()` — an agent **harness** running a
ReAct-style loop (call model → if it asked for a tool, run it → feed the result back →
repeat until the model answers without asking for a tool), with middleware as the
interception points around that loop. The router is a degenerate case of this: a single
structured-output classification call, no tool loop, because it doesn't need one. Domain
agents (Phase 2+) are the real ReAct case — they call tools, look at results, and decide
whether to call another or respond. Same factory, genuinely different usage; this isn't
two systems, it's one harness used two ways.

## 12. Product success — what "working" means, not just "shipped"

Routing correctness (§6, ECE) is necessary but not sufficient. From a product point of
view, the numbers that actually decide whether this system is doing its job:

| Metric | What it means here | Target (industry baseline, to be re-measured against our own traffic) |
|---|---|---|
| Autonomous resolution / containment rate | % of conversations that resolve without human takeover | Mature systems reach 70–85%; ours starts lower by design (Phase 2 has one domain agent) and should be tracked per-domain, not blended, since order/support/payment/catalog will not contain equally well |
| Accuracy against a trusted source | Weekly sample (50–100 conversations) graded against ground truth, not vibes | ≥90% |
| Hallucination rate | Same sample, checked for unsupported claims | <2% — this is the number `PIIMiddleware`/guardrails don't catch; needs its own eval, not assumed from ECE |
| Escalation correctness | Not just "did it escalate" but "did it escalate the right things" — false escalations cost human time, false non-escalations cost trust | No industry number; this is exactly what `HumanInTheLoopMiddleware`'s `interrupt_on` policy (§Phase 2) encodes as a design decision, not an afterthought |
| Customer effort | How many turns/clarifications a customer needed to get resolved | Falling trend, not a single target — this is what `CLARIFY` overuse would quietly break |

None of this is optional polish — it's the difference between "the classifier scored well
on the golden set" and "the system is actually good for the business." The golden-set eval
in §6/§9 measures classification quality; this section is the reminder that classification
quality is a leading indicator, not the outcome itself. Recommendation: stand up the
weekly-sample review (accuracy + hallucination rate) starting in Phase 1, before any real
domain agent exists — it's cheap to run against the router alone and establishes the
measurement habit before there's more surface area to measure.

## 13. Known trade-offs, stated plainly

- Multi-intent mid-conversation (customer adds an unrelated second topic after an agent
  is already engaged) has no clean fix — Handoffs are inherently sequential once warm.
  Mitigated by giving the active agent a `transfer_to_supervisor` escape hatch, not solved.
- Summarization (Phase 2) is lossy — a detail from early in a long conversation may not
  survive compression. Accepted cost of bounding context growth, not a bug.
- Self-consistency (if ECE forces it) doubles classification cost for every message, not
  just ambiguous ones. Trade latency/cost for not trusting a miscalibrated number.
