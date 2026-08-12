"""MatrixArk context service orchestration."""

from __future__ import annotations

from .config import MatrixArkConfig
from .embeddings import EmbeddingModel, OpenSourceModelRegistry
from .extraction import ExtractionProvider, OpenSourceLLMExtractor, RuleBasedExtractor
from .hashing import stable_hash64
from .models import (
    ContextEvent,
    ContextNode,
    ContextPack,
    ContextPackAudit,
    EmbeddingRecord,
    AgentConfirmationRequest,
    AgentFinalAnswerRequest,
    AgentQueryRequest,
    AgentQueryResult,
    FeedbackRequest,
    IndexRef,
    IngestRequest,
    IngestResult,
    QueryPlan,
    RetrieveRequest,
    ResourceIngestRequest,
    ResourceIngestResult,
    SummaryDirtyMarker,
)
from .resources import ResourceIngestionService
from .stages import EmbeddingStage, ExtractionStage, FilterStage, PackStage, RecallStage, make_query_plan
from .storage import InMemoryTemporalStoreAdapter, TemporalStoreAdapter
from .time_utils import parse_time_ms, utc_now_ms
from .validation import (
    validate_agent_confirmation_request,
    validate_agent_final_answer_request,
    validate_agent_query_request,
    validate_feedback_request,
    validate_ingest_request,
    validate_resource_ingest_request,
    validate_retrieve_request,
)
from .vlm import VlmModel, VlmModelRegistry


class MatrixArkContextService:
    """High-level API for ingestion, retrieval, feedback, and replay."""

    def __init__(
        self,
        temporalstore: TemporalStoreAdapter | None = None,
        extractor: ExtractionProvider | None = None,
        embedder: EmbeddingModel | None = None,
        vlm_model: VlmModel | None = None,
        config: MatrixArkConfig | None = None,
    ) -> None:
        self.config = config or MatrixArkConfig.from_env()
        registry = OpenSourceModelRegistry()
        vlm_registry = VlmModelRegistry()
        self.temporalstore = temporalstore or InMemoryTemporalStoreAdapter()
        self.extractor = extractor or self._default_extractor()
        self.embedder = embedder or registry.embedding_model(self.config.embedding_model)
        self.vlm_model = vlm_model or vlm_registry.vlm_model(self.config.vlm_provider, self.config.vlm_model)
        self.extraction_stage = ExtractionStage(self.extractor)
        self.embedding_stage = EmbeddingStage(self.embedder)
        self.recall_stage = RecallStage(self.temporalstore)
        self.filter_stage = FilterStage(self.temporalstore)
        self.pack_stage = PackStage(self.temporalstore)
        self.resource_ingestion = ResourceIngestionService(self.temporalstore, self.embedder, vlm_model=self.vlm_model)

    def ingest(self, request: IngestRequest) -> IngestResult:
        validate_ingest_request(request)
        extracted = self.extractor.extract_event(request)
        node_hash = stable_hash64(f"{request.tenant_id}:{extracted.node_path}")
        parent_hash = stable_hash64(f"{request.tenant_id}:{extracted.parent_path}") if extracted.parent_path else None
        event_id_hash = stable_hash64(
            f"{request.tenant_id}:{node_hash}:{extracted.event_time_ms}:{extracted.event_type}:{extracted.text}"
        )
        node = ContextNode(
            tenant_id=request.tenant_id,
            node_hash=node_hash,
            parent_hash=parent_hash,
            path=extracted.node_path,
            kind=extracted.node_kind,
            canonical_name=extracted.node_path.rsplit("/", 1)[-1],
            l0_summary=extracted.node_summary,
            last_event_time_ms=extracted.event_time_ms,
            compact_attrs={key: value for key, value in extracted.filters.items() if key in {"team", "project", "source"}},
        )
        self.temporalstore.upsert_node(node)

        event = ContextEvent(
            tenant_id=request.tenant_id,
            node_hash=node_hash,
            event_id_hash=event_id_hash,
            event_time_ms=extracted.event_time_ms,
            event_type=extracted.event_type,
            text=extracted.text,
            source=request.source,
            actor_hash=stable_hash64(extracted.actor) if extracted.actor else None,
            confidence=extracted.confidence,
            importance=extracted.importance,
            compact_attrs=extracted.filters,
            raw_object_ref=extracted.raw_object_ref,
        )
        self.temporalstore.write_event(event)
        indexed_fields = self._write_indexes(event)
        self.temporalstore.mark_summary_dirty(
            SummaryDirtyMarker(
                tenant_id=request.tenant_id,
                node_hash=node_hash,
                event_time_ms=event.event_time_ms,
                reason="event_ingested",
            )
        )

        vector = self.embedding_stage.embed([node.l0_summary])[0]
        self.temporalstore.upsert_embedding(
            EmbeddingRecord(
                tenant_id=request.tenant_id,
                ref_id=node_hash,
                ref_type="context_node",
                vector=vector,
                text=node.l0_summary,
                metadata={
                    "kind": node.kind,
                    "path": node.path,
                    "node_hash": node_hash,
                    "ref_type": "context_node",
                    **{key: str(value) for key, value in node.compact_attrs.items()},
                },
            )
        )
        self._store_vlm_embedding(
            request.tenant_id,
            ref_id=f"vlm-summary:{node_hash}",
            ref_type="vlm_context_summary",
            text=node.l0_summary,
            metadata={
                "kind": node.kind,
                "path": node.path,
                "node_hash": node_hash,
                "ref_type": "vlm_context_summary",
                **{key: str(value) for key, value in node.compact_attrs.items()},
            },
        )

        return IngestResult(
            tenant_id=request.tenant_id,
            node_hash=node_hash,
            node_path=extracted.node_path,
            event_id_hash=event_id_hash,
            event_type=event.event_type,
            indexed_fields=indexed_fields,
            summary_dirty=True,
        )

    def retrieve(self, request: RetrieveRequest) -> ContextPack:
        validate_retrieve_request(request)
        extracted = self.extraction_stage.plan_query(request)
        query_vector = self.embedding_stage.embed([request.query])[0]
        query_id_seed = stable_hash64(f"{request.tenant_id}:{request.query}:{request.now_ms or utc_now_ms()}")
        self._store_query_embeddings(request, query_id_seed, query_vector)
        recall_filters = self._recall_filters(extracted.filters)
        matches = self.recall_stage.recall(request.tenant_id, query_vector, recall_filters, limit=24)
        candidate_node_hashes: list[str] = []
        candidate_chunk_ids: list[str] = []
        for record, _ in matches:
            if record.ref_type in {"query_embedding", "vlm_query_embedding"}:
                continue
            if record.ref_type == "resource_chunk":
                candidate_chunk_ids.append(record.ref_id)
                node_hash = record.metadata.get("node_hash")
                if node_hash:
                    candidate_node_hashes.append(node_hash)
            elif record.ref_type in {"vlm_resource_chunk"}:
                chunk_id = record.metadata.get("chunk_id")
                node_hash = record.metadata.get("node_hash")
                if chunk_id:
                    candidate_chunk_ids.append(chunk_id)
                if node_hash:
                    candidate_node_hashes.append(node_hash)
            elif record.ref_type in {"vlm_context_summary", "document_summary"}:
                node_hash = record.metadata.get("node_hash") or record.ref_id
                candidate_node_hashes.append(node_hash)
            else:
                candidate_node_hashes.append(record.ref_id)
        exact_node_hash = stable_hash64(f"{request.tenant_id}:{extracted.scope_path}")
        if exact_node_hash not in candidate_node_hashes:
            candidate_node_hashes.insert(0, exact_node_hash)
        candidate_node_hashes = list(dict.fromkeys(candidate_node_hashes))[:12]
        candidate_chunk_ids = list(dict.fromkeys(candidate_chunk_ids))[:24]
        plan = make_query_plan(request, extracted, candidate_node_hashes)
        events = self.filter_stage.events(
            request.tenant_id,
            candidate_node_hashes,
            plan.start_ms,
            plan.end_ms,
            self._event_filters(plan.filters),
            limit=24,
        )
        chunks = self.filter_stage.chunks(request.tenant_id, candidate_chunk_ids, self._resource_filters(plan.filters), limit=16)
        return self.pack_stage.build(request, plan, events, chunks)

    def ingest_resource(self, request: ResourceIngestRequest) -> ResourceIngestResult:
        validate_resource_ingest_request(request)
        return self.resource_ingestion.ingest_resource(request)

    def agent_query(self, request: AgentQueryRequest) -> AgentQueryResult:
        validate_agent_query_request(request)
        query_event = None
        if request.record_query_event:
            query_event = self.ingest(
                IngestRequest(
                    tenant_id=request.tenant_id,
                    text=request.query,
                    source="agent_query",
                    event_time_ms=request.now_ms,
                    hints={**request.hints, "source": "agent_query"},
                )
            )
        context_pack = self.retrieve(
            RetrieveRequest(
                tenant_id=request.tenant_id,
                query=request.query,
                hints=request.hints,
                max_prompt_tokens=request.max_prompt_tokens,
                now_ms=request.now_ms,
            )
        )
        return AgentQueryResult(query_event=query_event, context_pack=context_pack)

    def agent_final_answer(self, request: AgentFinalAnswerRequest) -> IngestResult:
        validate_agent_final_answer_request(request)
        return self.feedback(
            FeedbackRequest(
                tenant_id=request.tenant_id,
                query_id=request.query_id,
                final_answer=request.final_answer,
                accepted=request.accepted,
                hints={**request.hints, "source": "agent_final_answer"},
                event_time_ms=request.event_time_ms,
            )
        )

    def agent_confirmation(self, request: AgentConfirmationRequest) -> IngestResult:
        validate_agent_confirmation_request(request)
        status = "confirmed" if request.confirmed else "rejected"
        return self.ingest(
            IngestRequest(
                tenant_id=request.tenant_id,
                text=request.confirmation_text,
                source="agent_confirmation",
                event_time_ms=request.event_time_ms,
                hints={**request.hints, "query_id": request.query_id, "status": status, "source": "agent_confirmation"},
            )
        )

    def agent_user_query_or_confirmation(
        self,
        tenant_id: str,
        text: str,
        hints: dict[str, str | int | float | bool],
        previous_query_id: str,
        now_ms: int,
    ) -> AgentQueryResult | IngestResult:
        if self._looks_like_confirmation(text):
            return self.agent_confirmation(
                AgentConfirmationRequest(
                    tenant_id=tenant_id,
                    query_id=previous_query_id,
                    confirmation_text=text,
                    confirmed=True,
                    hints=hints,
                    event_time_ms=now_ms,
                )
            )
        return self.agent_query(
            AgentQueryRequest(
                tenant_id=tenant_id,
                query=text,
                hints=hints,
                now_ms=now_ms,
                max_prompt_tokens=int(hints.get("max_prompt_tokens", 1800)),
            )
        )

    def feedback(self, request: FeedbackRequest) -> IngestResult:
        validate_feedback_request(request)
        source = "feedback_accepted" if request.accepted else "feedback_rejected"
        return self.ingest(
            IngestRequest(
                tenant_id=request.tenant_id,
                text=request.final_answer,
                source="feedback",
                event_time_ms=parse_time_ms(request.event_time_ms, utc_now_ms()),
                hints={
                    **request.hints,
                    "source": source,
                    "query_id": request.query_id,
                },
            )
        )

    def replay(self, tenant_id: str, query_id: str) -> ContextPackAudit | None:
        return self.temporalstore.get_pack_audit(tenant_id, query_id)

    def _write_indexes(self, event: ContextEvent) -> dict[str, str]:
        indexed_fields: dict[str, str] = {"event_type": event.event_type}
        for key in ("event_type", "status", "cost_related", "amount_bucket", "project", "team", "actor"):
            value = event.event_type if key == "event_type" else event.compact_attrs.get(key)
            if value in (None, ""):
                continue
            normalized = str(value).lower()
            value_hash = stable_hash64(f"{key}:{normalized}")
            indexed_fields[key] = normalized
            self.temporalstore.write_index_ref(
                IndexRef(
                    tenant_id=event.tenant_id,
                    index_name=key,
                    index_value_hash=value_hash,
                    node_hash=event.node_hash,
                    event_time_ms=event.event_time_ms,
                    event_id_hash=event.event_id_hash,
                )
            )
        return indexed_fields

    def _recall_filters(self, filters: dict[str, str]) -> dict[str, str]:
        return {key: value for key, value in filters.items() if key in {"team", "project", "source"}}

    def _event_filters(self, filters: dict[str, str]) -> dict[str, str]:
        return {key: value for key, value in filters.items() if key in {"event_type", "status", "cost_related", "amount_bucket"}}

    def _resource_filters(self, filters: dict[str, str]) -> dict[str, str]:
        return {key: value for key, value in filters.items() if key in {"team", "project", "mime_type", "source_path"}}

    def _default_extractor(self) -> ExtractionProvider:
        if self.config.extraction_provider == "oss-llm":
            return OpenSourceLLMExtractor(model_name=self.config.extraction_model)
        return RuleBasedExtractor()

    def _store_query_embeddings(self, request: RetrieveRequest, query_id: str, query_vector: list[float]) -> None:
        metadata = {
            "query_id": query_id,
            "ref_type": "query_embedding",
            **{key: str(value).lower().replace(" ", "_") for key, value in request.hints.items() if key in {"team", "project", "source"}},
        }
        self.temporalstore.upsert_embedding(
            EmbeddingRecord(
                tenant_id=request.tenant_id,
                ref_id=f"query:{query_id}",
                ref_type="query_embedding",
                vector=query_vector,
                text=request.query,
                metadata=metadata,
            )
        )
        self._store_vlm_embedding(
            request.tenant_id,
            ref_id=f"vlm-query:{query_id}",
            ref_type="vlm_query_embedding",
            text=request.query,
            metadata={**metadata, "ref_type": "vlm_query_embedding"},
        )

    def _store_vlm_embedding(
        self,
        tenant_id: str,
        ref_id: str,
        ref_type: str,
        text: str,
        metadata: dict[str, str],
    ) -> None:
        vector = self.vlm_model.embed_text([text])[0]
        self.temporalstore.upsert_embedding(
            EmbeddingRecord(
                tenant_id=tenant_id,
                ref_id=ref_id,
                ref_type=ref_type,
                vector=vector,
                text=text,
                metadata={**metadata, "model_family": "vlm"},
            )
        )

    def _looks_like_confirmation(self, text: str) -> bool:
        lowered = text.strip().lower()
        if len(lowered.split()) <= 8 and any(word in lowered for word in ("yes", "confirmed", "correct", "looks good", "remember it")):
            return True
        return any(phrase in lowered for phrase in ("that is correct", "please remember", "confirmed, use this"))
