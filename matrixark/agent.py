"""Mock AI-agent integration flow for end-to-end MatrixArk tests."""

from __future__ import annotations

from dataclasses import dataclass

from .models import AgentFinalAnswerRequest, AgentQueryRequest, ContextPack, IngestResult


@dataclass(slots=True)
class AgentRunResult:
    query_id: str
    context_pack: ContextPack
    final_event: IngestResult
    confirmation_event: IngestResult


class MockAiAgentHarness:
    """Small harness that mimics a Cursor-like agent using MatrixArk.

    The agent sends a raw query, receives a context pack, creates a mock final answer,
    then sends final-answer feedback and user confirmation back into TemporalStore.
    """

    def __init__(self, service) -> None:
        self.service = service

    def run(
        self,
        tenant_id: str,
        query: str,
        hints: dict[str, str | int | float | bool],
        now_ms: int,
        second_user_query: str = "Yes, that is correct. Please remember it.",
    ) -> AgentRunResult:
        query_result = self.service.agent_query(
            AgentQueryRequest(
                tenant_id=tenant_id,
                query=query,
                hints=hints,
                now_ms=now_ms,
                max_prompt_tokens=int(hints.get("max_prompt_tokens", 1000)),
            )
        )
        pack = query_result.context_pack
        supporting = "; ".join(item.text for item in pack.items[:2]) or "no matching context"
        final = self.service.agent_final_answer(
            AgentFinalAnswerRequest(
                tenant_id=tenant_id,
                query_id=pack.query_id,
                final_answer=f"Agent final answer based on MatrixArk context: {supporting}",
                accepted=True,
                hints=hints,
                event_time_ms=now_ms + 1,
            )
        )
        confirmation = self.service.agent_user_query_or_confirmation(
            tenant_id=tenant_id,
            text=second_user_query,
            hints=hints,
            previous_query_id=pack.query_id,
            now_ms=now_ms + 2,
        )
        if not isinstance(confirmation, IngestResult):
            raise RuntimeError("second user query was expected to be classified as confirmation")
        return AgentRunResult(
            query_id=pack.query_id,
            context_pack=pack,
            final_event=final,
            confirmation_event=confirmation,
        )
