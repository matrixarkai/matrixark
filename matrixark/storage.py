# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 MatrixArkAI
"""TemporalStore-facing protocols and test adapter."""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from .embeddings import cosine_similarity
from .models import (
    ContextEvent,
    ContextNode,
    ContextPackAudit,
    EmbeddingRecord,
    IndexRef,
    ResourceChunk,
    ResourceDocument,
    SummaryDirtyMarker,
)
from .validation import validate_embedding_record


class TemporalStoreAdapter(Protocol):
    def upsert_node(self, node: ContextNode) -> None:
        """Create or update a context node."""

    def write_event(self, event: ContextEvent) -> None:
        """Write a timestamp-keyed context event."""

    def write_index_ref(self, ref: IndexRef) -> None:
        """Write a secondary-index reference."""

    def mark_summary_dirty(self, marker: SummaryDirtyMarker) -> None:
        """Queue summary refresh without blocking event writes."""

    def write_resource_document(self, document: ResourceDocument) -> None:
        """Store parsed resource metadata."""

    def write_resource_chunk(self, chunk: ResourceChunk) -> None:
        """Store parsed resource chunk text and source metadata."""

    def query_resource_chunks(
        self,
        tenant_id: str,
        chunk_ids: list[str],
        filters: dict[str, str],
        limit: int,
    ) -> list[ResourceChunk]:
        """Fetch resource chunks selected by recall and filtered at serving time."""

    def upsert_embedding(self, record: EmbeddingRecord) -> None:
        """Store or replace an embedding record in TemporalStore."""

    def search_embeddings(
        self,
        tenant_id: str,
        query_vector: list[float],
        limit: int,
        filters: dict[str, str],
    ) -> list[tuple[EmbeddingRecord, float]]:
        """Recall candidate refs by vector similarity from TemporalStore."""

    def query_events(
        self,
        tenant_id: str,
        node_hashes: list[str],
        start_ms: int,
        end_ms: int,
        filters: dict[str, str],
        limit: int,
    ) -> list[ContextEvent]:
        """Read events by node, time range, and compact indexed filters."""

    def write_pack_audit(self, audit: ContextPackAudit) -> None:
        """Persist a replayable context-pack audit."""

    def get_pack_audit(self, tenant_id: str, query_id: str) -> ContextPackAudit | None:
        """Return the stored context-pack audit for replay."""


class InMemoryTemporalStoreAdapter:
    """In-memory adapter that mimics the TemporalStore model boundaries."""

    def __init__(self) -> None:
        self.nodes: dict[tuple[str, str], ContextNode] = {}
        self.events: dict[tuple[str, str], list[ContextEvent]] = defaultdict(list)
        self.indexes: dict[tuple[str, str, str], list[IndexRef]] = defaultdict(list)
        self.dirty_markers: list[SummaryDirtyMarker] = []
        self.audits: dict[tuple[str, str], ContextPackAudit] = {}
        self.resource_documents: dict[tuple[str, str], ResourceDocument] = {}
        self.resource_chunks: dict[tuple[str, str], ResourceChunk] = {}
        self.embeddings: dict[tuple[str, str], EmbeddingRecord] = {}

    def upsert_node(self, node: ContextNode) -> None:
        current = self.nodes.get((node.tenant_id, node.node_hash))
        if current and current.last_event_time_ms > node.last_event_time_ms:
            node.last_event_time_ms = current.last_event_time_ms
        self.nodes[(node.tenant_id, node.node_hash)] = node

    def write_event(self, event: ContextEvent) -> None:
        key = (event.tenant_id, event.node_hash)
        self.events[key].append(event)
        self.events[key].sort(key=lambda item: (item.event_time_ms, item.event_id_hash), reverse=True)
        node = self.nodes.get((event.tenant_id, event.node_hash))
        if node:
            node.last_event_time_ms = max(node.last_event_time_ms, event.event_time_ms)
            node.summary_dirty = True

    def write_index_ref(self, ref: IndexRef) -> None:
        key = (ref.tenant_id, ref.index_name, ref.index_value_hash)
        self.indexes[key].append(ref)

    def mark_summary_dirty(self, marker: SummaryDirtyMarker) -> None:
        self.dirty_markers.append(marker)

    def write_resource_document(self, document: ResourceDocument) -> None:
        self.resource_documents[(document.tenant_id, document.resource_id)] = document

    def write_resource_chunk(self, chunk: ResourceChunk) -> None:
        self.resource_chunks[(chunk.tenant_id, chunk.chunk_id)] = chunk

    def query_resource_chunks(
        self,
        tenant_id: str,
        chunk_ids: list[str],
        filters: dict[str, str],
        limit: int,
    ) -> list[ResourceChunk]:
        chunks: list[ResourceChunk] = []
        for chunk_id in chunk_ids:
            chunk = self.resource_chunks.get((tenant_id, chunk_id))
            if chunk is None or not self._metadata_matches(chunk.metadata, filters):
                continue
            chunks.append(chunk)
            if len(chunks) >= limit:
                break
        return chunks

    def upsert_embedding(self, record: EmbeddingRecord) -> None:
        validate_embedding_record(record)
        self.embeddings[(record.tenant_id, record.ref_id)] = record

    def search_embeddings(
        self,
        tenant_id: str,
        query_vector: list[float],
        limit: int,
        filters: dict[str, str],
    ) -> list[tuple[EmbeddingRecord, float]]:
        scored: list[tuple[EmbeddingRecord, float]] = []
        for (record_tenant, _), record in self.embeddings.items():
            if record_tenant != tenant_id:
                continue
            if not self._metadata_matches(record.metadata, filters):
                continue
            score = cosine_similarity(query_vector, record.vector)
            if score > 0.0:
                scored.append((record, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def query_events(
        self,
        tenant_id: str,
        node_hashes: list[str],
        start_ms: int,
        end_ms: int,
        filters: dict[str, str],
        limit: int,
    ) -> list[ContextEvent]:
        candidates: list[ContextEvent] = []
        for node_hash in node_hashes:
            for event in self.events.get((tenant_id, node_hash), []):
                if len(candidates) >= limit * 4:
                    break
                if not (start_ms <= event.event_time_ms <= end_ms):
                    continue
                if event.valid_until_ms is not None and event.valid_until_ms < end_ms:
                    continue
                if self._matches(event, filters):
                    candidates.append(event)
        candidates.sort(key=lambda item: (item.importance, item.event_time_ms), reverse=True)
        return candidates[:limit]

    def write_pack_audit(self, audit: ContextPackAudit) -> None:
        self.audits[(audit.tenant_id, audit.query_id)] = audit

    def get_pack_audit(self, tenant_id: str, query_id: str) -> ContextPackAudit | None:
        return self.audits.get((tenant_id, query_id))

    def _matches(self, event: ContextEvent, filters: dict[str, str]) -> bool:
        for key, value in filters.items():
            if key == "event_type":
                if event.event_type != value:
                    return False
            elif str(event.compact_attrs.get(key, "")).lower() != value:
                return False
        return True

    def _metadata_matches(self, metadata: dict[str, str] | dict[str, object], filters: dict[str, str]) -> bool:
        for key, value in filters.items():
            if key not in metadata:
                continue
            if str(metadata.get(key, "")).lower() != value:
                return False
        return True
