"""Shared data contracts for MatrixArk context ingestion and retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field

Metadata = dict[str, str | int | float | bool]


@dataclass(slots=True)
class IngestRequest:
    tenant_id: str
    text: str
    source: str = "query"
    event_time_ms: int | None = None
    hints: Metadata = field(default_factory=dict)
    raw_object_ref: str | None = None


@dataclass(slots=True)
class IngestResult:
    tenant_id: str
    node_hash: str
    node_path: str
    event_id_hash: str
    event_type: str
    indexed_fields: dict[str, str]
    summary_dirty: bool


@dataclass(slots=True)
class RetrieveRequest:
    tenant_id: str
    query: str
    hints: Metadata = field(default_factory=dict)
    max_prompt_tokens: int = 1800
    now_ms: int | None = None


@dataclass(slots=True)
class FeedbackRequest:
    tenant_id: str
    query_id: str
    final_answer: str
    accepted: bool = True
    hints: Metadata = field(default_factory=dict)
    event_time_ms: int | None = None


@dataclass(slots=True)
class AgentQueryRequest:
    tenant_id: str
    query: str
    hints: Metadata = field(default_factory=dict)
    max_prompt_tokens: int = 1800
    now_ms: int | None = None
    record_query_event: bool = True


@dataclass(slots=True)
class AgentFinalAnswerRequest:
    tenant_id: str
    query_id: str
    final_answer: str
    accepted: bool = True
    hints: Metadata = field(default_factory=dict)
    event_time_ms: int | None = None


@dataclass(slots=True)
class AgentConfirmationRequest:
    tenant_id: str
    query_id: str
    confirmation_text: str
    confirmed: bool = True
    hints: Metadata = field(default_factory=dict)
    event_time_ms: int | None = None


@dataclass(slots=True)
class AgentQueryResult:
    query_event: "IngestResult | None"
    context_pack: "ContextPack"


@dataclass(slots=True)
class ResourceIngestRequest:
    tenant_id: str
    raw_uri: str
    hints: Metadata = field(default_factory=dict)
    source: str = "resource_file"
    event_time_ms: int | None = None


@dataclass(slots=True)
class ResourceIngestResult:
    tenant_id: str
    resource_id: str
    node_hash: str
    content_hash: str
    chunk_count: int
    indexed_fields: dict[str, str]
    summary_dirty: bool


@dataclass(slots=True)
class ContextNode:
    tenant_id: str
    node_hash: str
    parent_hash: str | None
    path: str
    kind: str
    canonical_name: str
    l0_summary: str
    status: str = "active"
    last_event_time_ms: int = 0
    summary_dirty: bool = True
    l1_ref: str | None = None
    raw_metadata_ref: str | None = None
    compact_attrs: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class ContextEvent:
    tenant_id: str
    node_hash: str
    event_id_hash: str
    event_time_ms: int
    event_type: str
    text: str
    source: str
    actor_hash: str | None = None
    status: str = "valid"
    valid_until_ms: int | None = None
    confidence: float = 0.8
    importance: float = 0.5
    related_node_hashes: list[str] = field(default_factory=list)
    compact_attrs: Metadata = field(default_factory=dict)
    raw_object_ref: str | None = None


@dataclass(slots=True)
class IndexRef:
    tenant_id: str
    index_name: str
    index_value_hash: str
    node_hash: str
    event_time_ms: int
    event_id_hash: str


@dataclass(slots=True)
class SummaryDirtyMarker:
    tenant_id: str
    node_hash: str
    event_time_ms: int
    reason: str


@dataclass(slots=True)
class QueryPlan:
    tenant_id: str
    query_id: str
    query: str
    start_ms: int
    end_ms: int
    filters: dict[str, str]
    candidate_node_hashes: list[str]
    max_prompt_tokens: int
    extracted_intent: str


@dataclass(slots=True)
class ContextPackItem:
    event_id_hash: str
    node_hash: str
    text: str
    event_time_ms: int
    event_type: str
    reason: str
    estimated_tokens: int
    attrs: Metadata = field(default_factory=dict)
    source_ref: str | None = None


@dataclass(slots=True)
class ContextPack:
    tenant_id: str
    query_id: str
    query: str
    plan: QueryPlan
    items: list[ContextPackItem]
    estimated_tokens: int
    replay_ref: str


@dataclass(slots=True)
class ContextPackAudit:
    tenant_id: str
    query_id: str
    plan: QueryPlan
    selected_event_ids: list[str]
    returned_tokens: int
    decision_notes: list[str]


@dataclass(slots=True)
class ResourceDocument:
    tenant_id: str
    resource_id: str
    raw_uri: str
    content_hash: str
    mime_type: str
    title: str
    source_path: str
    created_at_ms: int
    updated_at_ms: int
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class ResourceChunk:
    tenant_id: str
    resource_id: str
    chunk_id: str
    node_hash: str
    chunk_index: int
    text: str
    start_offset: int
    end_offset: int
    page_number: int | None = None
    heading_path: str | None = None
    token_estimate: int = 0
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class EmbeddingRecord:
    tenant_id: str
    ref_id: str
    ref_type: str
    vector: list[float]
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedEvent:
    node_path: str
    parent_path: str | None
    node_kind: str
    node_summary: str
    event_type: str
    event_time_ms: int
    text: str
    filters: dict[str, str]
    actor: str | None
    confidence: float
    importance: float
    raw_object_ref: str | None = None


@dataclass(slots=True)
class ExtractedQuery:
    intent: str
    start_ms: int
    end_ms: int
    filters: dict[str, str]
    scope_path: str
    keywords: list[str]
