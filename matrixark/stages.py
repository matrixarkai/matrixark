"""OpenViking-inspired staged context runtime."""

from __future__ import annotations

from dataclasses import dataclass

from .embeddings import EmbeddingModel
from .extraction import RuleBasedExtractor
from .hashing import stable_hash64
from .models import ContextEvent, ContextPack, ContextPackAudit, QueryPlan, RetrieveRequest
from .storage import TemporalStoreAdapter
from .summaries import chunks_to_pack_items, events_to_pack_items
from .time_utils import utc_now_ms


@dataclass(slots=True)
class ExtractionStage:
    extractor: RuleBasedExtractor

    def plan_query(self, request: RetrieveRequest):
        return self.extractor.plan_query(request)


@dataclass(slots=True)
class EmbeddingStage:
    embedder: EmbeddingModel

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.embedder.embed(texts)


@dataclass(slots=True)
class RecallStage:
    temporalstore: TemporalStoreAdapter

    def recall(self, tenant_id: str, query_vector: list[float], filters: dict[str, str], limit: int = 16):
        return self.temporalstore.search_embeddings(tenant_id, query_vector, limit, filters)


@dataclass(slots=True)
class FilterStage:
    temporalstore: TemporalStoreAdapter

    def events(
        self,
        tenant_id: str,
        node_hashes: list[str],
        start_ms: int,
        end_ms: int,
        filters: dict[str, str],
        limit: int,
    ) -> list[ContextEvent]:
        return self.temporalstore.query_events(tenant_id, node_hashes, start_ms, end_ms, filters, limit)

    def chunks(self, tenant_id: str, chunk_ids: list[str], filters: dict[str, str], limit: int):
        return self.temporalstore.query_resource_chunks(tenant_id, chunk_ids, filters, limit)


@dataclass(slots=True)
class PackStage:
    temporalstore: TemporalStoreAdapter

    def build(
        self,
        request: RetrieveRequest,
        plan: QueryPlan,
        events: list[ContextEvent],
        chunks,
    ) -> ContextPack:
        event_items, event_tokens = events_to_pack_items(events, request.max_prompt_tokens)
        remaining = max(0, request.max_prompt_tokens - event_tokens)
        chunk_items, chunk_tokens = chunks_to_pack_items(chunks, remaining)
        items = event_items + chunk_items
        used_tokens = event_tokens + chunk_tokens
        audit = ContextPackAudit(
            tenant_id=request.tenant_id,
            query_id=plan.query_id,
            plan=plan,
            selected_event_ids=[item.event_id_hash for item in items],
            returned_tokens=used_tokens,
            decision_notes=[
                "extraction stage converted raw query into intent, time window, filters, and scope",
                "embedding stage created the query vector",
                "recall stage searched TemporalStore-owned summary and chunk embeddings",
                "filter stage enforced TemporalStore time and metadata filters",
                "pack stage enforced token budget and stored replay metadata",
            ],
        )
        self.temporalstore.write_pack_audit(audit)
        return ContextPack(
            tenant_id=request.tenant_id,
            query_id=plan.query_id,
            query=request.query,
            plan=plan,
            items=items,
            estimated_tokens=used_tokens,
            replay_ref=f"context-pack/{request.tenant_id}/{plan.query_id}",
        )


def make_query_plan(request: RetrieveRequest, extracted, candidate_node_hashes: list[str]) -> QueryPlan:
    query_id = stable_hash64(f"{request.tenant_id}:{request.query}:{request.now_ms or utc_now_ms()}")
    filters = {
        key: value
        for key, value in extracted.filters.items()
        if key in {"event_type", "status", "cost_related", "amount_bucket", "mime_type", "project", "team", "source_path"}
    }
    return QueryPlan(
        tenant_id=request.tenant_id,
        query_id=query_id,
        query=request.query,
        start_ms=extracted.start_ms,
        end_ms=extracted.end_ms,
        filters=filters,
        candidate_node_hashes=candidate_node_hashes,
        max_prompt_tokens=request.max_prompt_tokens,
        extracted_intent=extracted.intent,
    )

