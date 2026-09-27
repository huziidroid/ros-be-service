"""
ConversationWorkflow — one long-running Temporal workflow per conversation
(tenant_waba_id + wa_id).

Started via signal-with-start: services/intake.py starts the workflow on the first
message for a wa_id and signals the existing execution for every message after that.
Signals are processed strictly in order, one at a time, off self._pending.

Every step with real I/O (media extraction, classification, sending replies) runs as
a `workflow.execute_activity(...)` call, never a bare function call.
"""

import contextlib
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError


with workflow.unsafe.imports_passed_through():
    from app.activities.conversation import (
        classify,
        send_clarify_options,
        send_whatsapp_reply,
    )
    from app.activities.message_ingestion import extract_text
    from app.schemas.workflows.conversation import (
        ClarifyReplyInput,
        ClassifyInput,
        ConversationTurn,
        ConversationWorkflowConfig,
        ConversationWorkflowState,
        NewMessageSignal,
        RoutingAction,
        RoutingDecision,
        SendReplyInput,
    )


# This workflow never imports app.core.settings directly — reading live settings in
# workflow code isn't replay-safe. Tunable config comes in via ConversationWorkflowConfig,
# read once by the caller and carried forward through continue-as-new.
#
# These are fixed technical bounds, not product config, so they stay as constants.
_MAX_SEEN_WAMIDS = 50
_CONTINUE_AS_NEW_EVERY = 200
_CONTINUE_AS_NEW_MAX_AGE = timedelta(hours=24)

_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_ACTIVITY_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
)

_UNSUPPORTED_MESSAGE_REPLY = (
    "Sorry, I can't handle that type of message yet — could you send it as text?"
)
_TROUBLE_REPLY = "Having some trouble on our end — please try again in a moment."
_CHITCHAT_REPLY = (
    "Hey! How can I help — is this about an order, support, payments, or our catalog?"
)
_OUT_OF_SCOPE_REPLY = (
    "That's outside what I can help with here — I'm here for orders, support, "
    "payments, and catalog questions."
)


def _clarify_body(decision: RoutingDecision) -> str:
    """Body text above the WhatsApp list-interactive's options (see _send_clarify
    for the options themselves)."""
    if decision.primary_domain:
        return (
            f"I think this might be about {decision.primary_domain} — pick one "
            "below, or tell me more:"
        )
    return "Could you pick what this is about?"


def _dispatch_reply(decision: RoutingDecision) -> str:
    domains = [d for d in [decision.primary_domain, *decision.secondary_domains] if d]
    names = " and ".join(domains) if domains else "the right team"
    return (
        f"Got it — routing you to our {names} team. "
        "(Routing only, for now — full handling is coming soon.)"
    )


def _reply_for(decision: RoutingDecision) -> str:
    """Plain-text reply for every RoutingAction except CLARIFY — CLARIFY goes
    through _send_clarify (WhatsApp list-interactive), not this."""
    if decision.action in (RoutingAction.DISPATCH, RoutingAction.DISPATCH_MULTI):
        return _dispatch_reply(decision)
    if decision.action == RoutingAction.DEFER_OUT_OF_SCOPE:
        return _OUT_OF_SCOPE_REPLY
    return _CHITCHAT_REPLY


def _truncate(text: str | None) -> str | None:
    """Head+tail truncation — keeps both the start and end of a long message."""
    if text is None or len(text) <= 500:
        return text
    return text[:300] + text[-200:]


@workflow.defn
class ConversationWorkflow:
    def __init__(self) -> None:
        self._pending: list[NewMessageSignal] = []
        self._config = ConversationWorkflowConfig(
            idle_minutes=30, close_days=7, memory_turns=6
        )  # placeholder, overwritten by run()'s config argument
        self._active_domain: str | None = None
        self._recent_turns: list[ConversationTurn] = []
        self._seen_wamids: list[str] = []

    @workflow.signal
    def new_message(self, signal: NewMessageSignal) -> None:
        self._pending.append(signal)

    @workflow.run
    async def run(
        self,
        config: ConversationWorkflowConfig,
        state: ConversationWorkflowState | None = None,
    ) -> None:
        self._config = config
        if state is not None:
            self._active_domain = state.active_domain
            self._recent_turns = list(state.recent_turns)
            self._seen_wamids = list(state.seen_wamids)

        idle_timeout = timedelta(minutes=self._config.idle_minutes)
        close_timeout = timedelta(days=self._config.close_days)
        idle_elapsed = timedelta(0)
        processed_since_continue = 0
        continue_as_new_deadline = workflow.now() + _CONTINUE_AS_NEW_MAX_AGE

        while True:
            try:
                await workflow.wait_condition(
                    lambda: bool(self._pending), timeout=idle_timeout
                )
            except TimeoutError:
                # Soft reset: stay alive, just go cold.
                self._active_domain = None
                idle_elapsed += idle_timeout
                if idle_elapsed >= close_timeout:
                    return  # hard close; signal_with_start begins a fresh one next time
                if workflow.now() >= continue_as_new_deadline:
                    workflow.continue_as_new(args=[self._config, self._snapshot()])
                continue

            idle_elapsed = timedelta(0)
            signal = self._pending.pop(0)
            await self._handle_message(signal)
            processed_since_continue += 1

            if (
                processed_since_continue >= _CONTINUE_AS_NEW_EVERY
                or workflow.now() >= continue_as_new_deadline
            ):
                workflow.continue_as_new(args=[self._config, self._snapshot()])

    async def _handle_message(self, signal: NewMessageSignal) -> None:
        wamid = signal.message.id
        if wamid in self._seen_wamids:
            return  # Meta redelivery of a message we already processed

        self._seen_wamids.append(wamid)
        if len(self._seen_wamids) > _MAX_SEEN_WAMIDS:
            self._seen_wamids = self._seen_wamids[-_MAX_SEEN_WAMIDS:]

        wa_id = signal.message.from_

        extracted = await workflow.execute_activity(
            extract_text,
            signal.message,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )
        if not extracted.supported or extracted.text is None:
            await self._reply(signal.phone_number_id, wa_id, _UNSUPPORTED_MESSAGE_REPLY)
            return

        try:
            decision = await workflow.execute_activity(
                classify,
                ClassifyInput(text=extracted.text, recent_turns=self._recent_turns),
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )
        except ActivityError:
            # Exhausted retries — tell the customer plainly and move on.
            await self._reply(signal.phone_number_id, wa_id, _TROUBLE_REPLY)
            return

        if decision.action == RoutingAction.CLARIFY:
            reply_text = _clarify_body(decision)
            await self._send_clarify(signal.phone_number_id, wa_id, decision)
        else:
            reply_text = _reply_for(decision)
            await self._reply(signal.phone_number_id, wa_id, reply_text)

        turn_domain = decision.primary_domain
        self._recent_turns.append(
            ConversationTurn(
                role="inbound", text=_truncate(extracted.text), domain=turn_domain
            )
        )
        self._recent_turns.append(
            ConversationTurn(
                role="outbound", text=_truncate(reply_text), domain=turn_domain
            )
        )
        if len(self._recent_turns) > self._config.memory_turns:
            self._recent_turns = self._recent_turns[-self._config.memory_turns :]

    async def _reply(self, phone_number_id: str, wa_id: str, text: str) -> None:
        # Reply delivery failing after retries is already logged at the activity
        # layer — nothing more to do; don't crash the workflow over it.
        with contextlib.suppress(ActivityError):
            await workflow.execute_activity(
                send_whatsapp_reply,
                SendReplyInput(phone_number_id=phone_number_id, to=wa_id, text=text),
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )

    async def _send_clarify(
        self, phone_number_id: str, wa_id: str, decision: RoutingDecision
    ) -> None:
        if not decision.available_domains:
            # An empty list-interactive is rejected by the Meta API — fall back to text.
            await self._reply(phone_number_id, wa_id, _clarify_body(decision))
            return
        with contextlib.suppress(ActivityError):
            await workflow.execute_activity(
                send_clarify_options,
                ClarifyReplyInput(
                    phone_number_id=phone_number_id,
                    to=wa_id,
                    body=_clarify_body(decision),
                    options=decision.available_domains,
                ),
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )

    def _snapshot(self) -> ConversationWorkflowState:
        return ConversationWorkflowState(
            active_domain=self._active_domain,
            recent_turns=list(self._recent_turns),
            seen_wamids=list(self._seen_wamids),
        )
