# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 MatrixArkAI
"""Resource parsing and ingestion for Markdown, PDF, and text files."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from .hashing import canonical_path, stable_hash64
from .models import (
    ContextEvent,
    ContextNode,
    EmbeddingRecord,
    IndexRef,
    ResourceChunk,
    ResourceDocument,
    ResourceIngestRequest,
    ResourceIngestResult,
    SummaryDirtyMarker,
)
from .storage import TemporalStoreAdapter
from .summaries import estimate_tokens
from .time_utils import parse_time_ms, utc_now_ms


@dataclass(slots=True)
class ParsedBlock:
    text: str
    start_offset: int
    end_offset: int
    page_number: int | None = None
    heading_path: str | None = None


class ResourceParser:
    def parse(self, raw_uri: str) -> tuple[str, str, list[ParsedBlock]]:
        path = Path(raw_uri)
        mime_type = mimetypes.guess_type(path.name)[0] or self._mime_from_suffix(path.suffix)
        if path.suffix.lower() == ".md":
            text = path.read_text(encoding="utf-8")
            return mime_type, text, self._parse_markdown(text)
        if path.suffix.lower() == ".pdf":
            text, blocks = self._parse_pdf(path)
            return mime_type, text, blocks
        text = path.read_text(encoding="utf-8")
        return mime_type, text, self._parse_text(text)

    def _parse_markdown(self, text: str) -> list[ParsedBlock]:
        blocks: list[ParsedBlock] = []
        headings: list[str] = []
        cursor = 0
        pending: list[str] = []
        pending_start = 0
        pending_heading = ""
        for match in re.finditer(r"(?m)^(#{1,6})\s+(.+)$", text):
            before = text[cursor : match.start()].strip()
            if before:
                pending.append(before)
            if pending:
                block_text = "\n\n".join(pending).strip()
                blocks.extend(self._chunk_text(block_text, pending_start, heading_path=pending_heading))
                pending = []
            level = len(match.group(1))
            heading = match.group(2).strip()
            headings = headings[: level - 1] + [heading]
            pending_heading = " / ".join(headings)
            pending_start = match.start()
            pending.append(heading)
            cursor = match.end()
        tail = text[cursor:].strip()
        if tail:
            pending.append(tail)
        if pending:
            blocks.extend(self._chunk_text("\n\n".join(pending), pending_start, heading_path=pending_heading))
        if not blocks and text.strip():
            blocks.extend(self._parse_text(text))
        return blocks

    def _parse_pdf(self, path: Path) -> tuple[str, list[ParsedBlock]]:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            all_text: list[str] = []
            blocks: list[ParsedBlock] = []
            offset = 0
            for page_index, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                all_text.append(page_text)
                blocks.extend(self._chunk_text(page_text, offset, page_number=page_index))
                offset += len(page_text) + 1
            return "\n".join(all_text), blocks
        except Exception:
            text = path.read_bytes().decode("utf-8", errors="ignore")
            return text, self._chunk_text(text, 0, page_number=1)

    def _parse_text(self, text: str) -> list[ParsedBlock]:
        return self._chunk_text(text, 0)

    def _chunk_text(
        self,
        text: str,
        base_offset: int,
        page_number: int | None = None,
        heading_path: str | None = None,
        target_words: int = 180,
        overlap_words: int = 30,
    ) -> list[ParsedBlock]:
        words = text.split()
        if not words:
            return []
        chunks: list[ParsedBlock] = []
        index = 0
        while index < len(words):
            end = min(len(words), index + target_words)
            chunk_text = " ".join(words[index:end])
            local_start = text.find(words[index]) if index == 0 else max(0, len(" ".join(words[:index])))
            local_end = local_start + len(chunk_text)
            chunks.append(
                ParsedBlock(
                    text=chunk_text,
                    start_offset=base_offset + local_start,
                    end_offset=base_offset + local_end,
                    page_number=page_number,
                    heading_path=heading_path,
                )
            )
            if end == len(words):
                break
            index = max(end - overlap_words, index + 1)
        return chunks

    def _mime_from_suffix(self, suffix: str) -> str:
        return {
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".pdf": "application/pdf",
        }.get(suffix.lower(), "application/octet-stream")


class ResourceIngestionService:
    def __init__(
        self,
        temporalstore: TemporalStoreAdapter,
        embedder,
        parser: ResourceParser | None = None,
        vlm_model=None,
    ) -> None:
        self.temporalstore = temporalstore
        self.embedder = embedder
        self.parser = parser or ResourceParser()
        self.vlm_model = vlm_model

    def ingest_resource(self, request: ResourceIngestRequest) -> ResourceIngestResult:
        raw_path = Path(request.raw_uri)
        mime_type, full_text, blocks = self.parser.parse(request.raw_uri)
        content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
        event_time_ms = parse_time_ms(request.event_time_ms or request.hints.get("event_time_ms"), utc_now_ms())
        team = str(request.hints.get("team") or "shared").lower().replace(" ", "_")
        project = str(request.hints.get("project") or "general").lower().replace(" ", "_")
        title = str(request.hints.get("title") or raw_path.stem)
        resource_id = stable_hash64(f"{request.tenant_id}:{request.raw_uri}:{content_hash}")
        node_path = canonical_path(request.tenant_id, team, project, "resources", title)
        node_hash = stable_hash64(f"{request.tenant_id}:{node_path}")
        parent_hash = stable_hash64(f"{request.tenant_id}:{canonical_path(request.tenant_id, team, project, 'resources')}")
        summary = self._summary(title, full_text, len(blocks))

        metadata = {
            "team": team,
            "project": project,
            "mime_type": mime_type,
            "source_path": str(raw_path),
            "content_hash": content_hash,
            "updated_at_ms": event_time_ms,
        }
        document = ResourceDocument(
            tenant_id=request.tenant_id,
            resource_id=resource_id,
            raw_uri=request.raw_uri,
            content_hash=content_hash,
            mime_type=mime_type,
            title=title,
            source_path=str(raw_path),
            created_at_ms=event_time_ms,
            updated_at_ms=event_time_ms,
            metadata=metadata,
        )
        self.temporalstore.write_resource_document(document)
        self.temporalstore.upsert_node(
            ContextNode(
                tenant_id=request.tenant_id,
                node_hash=node_hash,
                parent_hash=parent_hash,
                path=node_path,
                kind="resource",
                canonical_name=title.lower().replace(" ", "_"),
                l0_summary=summary,
                last_event_time_ms=event_time_ms,
                compact_attrs=metadata,
            )
        )
        event_id_hash = stable_hash64(f"{request.tenant_id}:{node_hash}:{event_time_ms}:resource_ingested:{content_hash}")
        self.temporalstore.write_event(
            ContextEvent(
                tenant_id=request.tenant_id,
                node_hash=node_hash,
                event_id_hash=event_id_hash,
                event_time_ms=event_time_ms,
                event_type="resource_ingested",
                text=summary,
                source=request.source,
                importance=0.45,
                compact_attrs=metadata,
                raw_object_ref=request.raw_uri,
            )
        )
        self._write_indexes(request.tenant_id, node_hash, event_time_ms, event_id_hash, metadata)

        vectors = self.embedder.embed([summary] + [block.text for block in blocks])
        self.temporalstore.upsert_embedding(
            EmbeddingRecord(
                tenant_id=request.tenant_id,
                ref_id=node_hash,
                ref_type="document_summary",
                vector=vectors[0],
                text=summary,
                metadata={**metadata, "node_hash": node_hash, "ref_type": "document_summary"},
            )
        )
        if self.vlm_model is not None:
            self.temporalstore.upsert_embedding(
                EmbeddingRecord(
                    tenant_id=request.tenant_id,
                    ref_id=f"vlm-summary:{node_hash}",
                    ref_type="vlm_context_summary",
                    vector=self.vlm_model.embed_text([summary])[0],
                    text=summary,
                    metadata={**metadata, "node_hash": node_hash, "ref_type": "vlm_context_summary", "model_family": "vlm"},
                )
            )
        for index, block in enumerate(blocks):
            chunk_id = stable_hash64(f"{resource_id}:{index}:{block.start_offset}:{block.end_offset}")
            chunk = ResourceChunk(
                tenant_id=request.tenant_id,
                resource_id=resource_id,
                chunk_id=chunk_id,
                node_hash=node_hash,
                chunk_index=index,
                text=block.text,
                start_offset=block.start_offset,
                end_offset=block.end_offset,
                page_number=block.page_number,
                heading_path=block.heading_path,
                token_estimate=estimate_tokens(block.text),
                metadata={
                    **metadata,
                    "chunk_id": chunk_id,
                    "node_hash": node_hash,
                    "heading_path": block.heading_path or "",
                    "page_number": block.page_number or 0,
                },
            )
            self.temporalstore.write_resource_chunk(chunk)
            self.temporalstore.upsert_embedding(
                EmbeddingRecord(
                    tenant_id=request.tenant_id,
                    ref_id=chunk_id,
                    ref_type="resource_chunk",
                    vector=vectors[index + 1],
                    text=block.text,
                    metadata={**chunk.metadata, "ref_type": "resource_chunk"},
                )
            )
            if self.vlm_model is not None:
                self.temporalstore.upsert_embedding(
                    EmbeddingRecord(
                        tenant_id=request.tenant_id,
                        ref_id=f"vlm-chunk:{chunk_id}",
                        ref_type="vlm_resource_chunk",
                        vector=self.vlm_model.embed_text([block.text])[0],
                        text=block.text,
                        metadata={
                            **chunk.metadata,
                            "ref_type": "vlm_resource_chunk",
                            "chunk_id": chunk_id,
                            "model_family": "vlm",
                        },
                    )
                )
        self.temporalstore.mark_summary_dirty(
            SummaryDirtyMarker(request.tenant_id, node_hash, event_time_ms, "resource_ingested")
        )
        return ResourceIngestResult(
            tenant_id=request.tenant_id,
            resource_id=resource_id,
            node_hash=node_hash,
            content_hash=content_hash,
            chunk_count=len(blocks),
            indexed_fields={key: str(value) for key, value in metadata.items()},
            summary_dirty=True,
        )

    def _summary(self, title: str, text: str, chunk_count: int) -> str:
        clean = " ".join(text.split())
        if len(clean) > 180:
            clean = clean[:177] + "..."
        return f"{title}: resource with {chunk_count} chunks. {clean}"

    def _write_indexes(
        self,
        tenant_id: str,
        node_hash: str,
        event_time_ms: int,
        event_id_hash: str,
        metadata: dict[str, object],
    ) -> None:
        for key in ("team", "project", "mime_type", "source_path", "content_hash"):
            value = metadata.get(key)
            if value in (None, ""):
                continue
            self.temporalstore.write_index_ref(
                IndexRef(
                    tenant_id=tenant_id,
                    index_name=key,
                    index_value_hash=stable_hash64(f"{key}:{str(value).lower()}"),
                    node_hash=node_hash,
                    event_time_ms=event_time_ms,
                    event_id_hash=event_id_hash,
                )
            )
