# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 MatrixArkAI
"""Extraction providers with hooks for open-source LLM models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .hashing import canonical_path
from .models import ExtractedEvent, ExtractedQuery, IngestRequest, RetrieveRequest
from .time_utils import infer_time_window_ms, parse_time_ms, utc_now_ms


EVENT_KEYWORDS = {
    "approval": ["approve", "approved", "approval", "signoff", "confirmed"],
    "cost": ["cost", "budget", "spend", "invoice", "purchase", "gpu", "expense"],
    "risk": ["risk", "blocked", "incident", "outage", "regression"],
    "decision": ["decide", "decision", "chosen", "selected"],
    "memory": ["remember", "preference", "lesson", "policy"],
    "confirmation": ["confirm", "confirmed", "yes", "approved final", "looks good"],
}


class ExtractionProvider(Protocol):
    def extract_event(self, request: IngestRequest) -> ExtractedEvent:
        """Extract a serving-time event from raw text and hints."""

    def plan_query(self, request: RetrieveRequest) -> ExtractedQuery:
        """Extract query intent, time range, filters, and scope."""


@dataclass(slots=True)
class RuleBasedExtractor:
    """A small local extractor used when no LLM extractor is configured.

    Production MatrixArk can replace this with an open-source instruction model that
    emits the same compact fields.
    """

    def extract_event(self, request: IngestRequest) -> ExtractedEvent:
        now_ms = utc_now_ms()
        event_time_ms = parse_time_ms(request.event_time_ms or request.hints.get("event_time_ms"), now_ms)
        filters = self._base_filters(request.text, request.hints)
        event_type = self._event_type(request.text, request.source)
        team = str(request.hints.get("team") or request.hints.get("workspace") or "shared")
        project = str(request.hints.get("project") or filters.get("project") or self._guess_project(request.text))
        topic = str(request.hints.get("topic") or self._topic_from_event(event_type, request.text))
        node_path = canonical_path(request.tenant_id, team, project, topic)
        parent_path = canonical_path(request.tenant_id, team, project)
        summary = self._summary(event_type, request.text, project)
        actor = str(request.hints.get("actor") or request.hints.get("user") or "") or None
        importance = 0.8 if event_type in {"approval", "decision", "risk"} else 0.55
        return ExtractedEvent(
            node_path=node_path,
            parent_path=parent_path,
            node_kind=self._node_kind(event_type),
            node_summary=summary,
            event_type=event_type,
            event_time_ms=event_time_ms,
            text=request.text.strip(),
            filters=filters,
            actor=actor,
            confidence=0.72,
            importance=importance,
            raw_object_ref=request.raw_object_ref,
        )

    def plan_query(self, request: RetrieveRequest) -> ExtractedQuery:
        now_ms = request.now_ms or utc_now_ms()
        start_ms, end_ms = infer_time_window_ms(request.query, request.hints, now_ms)
        filters = self._base_filters(request.query, request.hints)
        team = str(request.hints.get("team") or request.hints.get("workspace") or "shared")
        project = str(request.hints.get("project") or filters.get("project") or self._guess_project(request.query))
        topic = str(request.hints.get("topic") or self._topic_from_event(self._event_type(request.query, "query"), request.query))
        scope_path = canonical_path(request.tenant_id, team, project, topic)
        keywords = re.findall(r"[a-zA-Z0-9_]+", request.query.lower())
        return ExtractedQuery(
            intent=self._intent(request.query),
            start_ms=start_ms,
            end_ms=end_ms,
            filters=filters,
            scope_path=scope_path,
            keywords=keywords[:12],
        )

    def _base_filters(self, text: str, hints: dict[str, object]) -> dict[str, str]:
        lowered = text.lower()
        filters: dict[str, str] = {}
        for key in ("team", "project", "status", "actor", "source"):
            if key in hints and hints[key] not in (None, ""):
                filters[key] = str(hints[key]).lower().replace(" ", "_")
        if "approved" in lowered or "approval" in lowered:
            filters.setdefault("event_type", "approval")
        if "cost" in lowered or "budget" in lowered or "gpu" in lowered or "purchase" in lowered:
            filters.setdefault("cost_related", "true")
        amount = re.search(r"\$?\b(\d{3,9})(?:\.\d+)?\b", text)
        if amount:
            filters.setdefault("amount_bucket", self._amount_bucket(int(amount.group(1))))
        return filters

    def _event_type(self, text: str, source: str) -> str:
        lowered = text.lower()
        if source == "feedback":
            return "feedback"
        if source == "agent_confirmation":
            return "confirmation"
        if source == "agent_query":
            return "agent_query"
        for event_type, words in EVENT_KEYWORDS.items():
            if any(word in lowered for word in words):
                return event_type
        return "note"

    def _intent(self, query: str) -> str:
        lowered = query.lower()
        if "can we" in lowered or "should we" in lowered:
            return "decision_support"
        if "what happened" in lowered or "history" in lowered:
            return "timeline_replay"
        if "cost" in lowered or "budget" in lowered:
            return "cost_lookup"
        return "context_lookup"

    def _guess_project(self, text: str) -> str:
        match = re.search(r"\b(project|proj)[-_ ]?([a-zA-Z0-9]+)\b", text, re.IGNORECASE)
        if match:
            return f"project_{match.group(2).lower()}"
        return "general"

    def _topic_from_event(self, event_type: str, text: str) -> str:
        lowered = text.lower()
        if "gpu" in lowered:
            return "gpu_purchase"
        if event_type == "approval":
            return "approvals"
        if event_type == "cost":
            return "costs"
        if event_type == "risk":
            return "risks"
        if event_type == "decision":
            return "decisions"
        return "memory"

    def _node_kind(self, event_type: str) -> str:
        if event_type in {"approval", "decision", "risk"}:
            return "business_event"
        if event_type == "feedback":
            return "memory"
        if event_type in {"agent_query", "confirmation"}:
            return "memory"
        return "resource"

    def _summary(self, event_type: str, text: str, project: str) -> str:
        clean = " ".join(text.strip().split())
        if len(clean) > 140:
            clean = clean[:137] + "..."
        return f"{project}: {event_type} context. {clean}"

    def _amount_bucket(self, amount: int) -> str:
        if amount < 1_000:
            return "lt_1k"
        if amount < 10_000:
            return "1k_10k"
        if amount < 100_000:
            return "10k_100k"
        return "gte_100k"


class OpenSourceLLMExtractor:
    """Optional OSS LLM extractor with deterministic local fallback.

    The first production version can swap the fallback prompt parser for a small
    instruction model. This class keeps the provider boundary explicit while tests stay
    fast and offline.
    """

    def __init__(self, fallback: ExtractionProvider | None = None, model_name: str | None = None) -> None:
        self.fallback = fallback or RuleBasedExtractor()
        self.model_name = model_name or "google/flan-t5-small"
        self._pipeline = None

    def extract_event(self, request: IngestRequest) -> ExtractedEvent:
        if self._load_pipeline_if_allowed() is None:
            return self.fallback.extract_event(request)
        return self.fallback.extract_event(request)

    def plan_query(self, request: RetrieveRequest) -> ExtractedQuery:
        if self._load_pipeline_if_allowed() is None:
            return self.fallback.plan_query(request)
        return self.fallback.plan_query(request)

    def _load_pipeline_if_allowed(self):
        import os

        if os.environ.get("MATRIXARK_EXTRACTION_PROVIDER") != "oss-llm":
            return None
        if os.environ.get("MATRIXARK_ALLOW_MODEL_DOWNLOAD") != "1":
            return None
        if self._pipeline is None:
            from transformers import pipeline

            self._pipeline = pipeline("text2text-generation", model=self.model_name)
        return self._pipeline
