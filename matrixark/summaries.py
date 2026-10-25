# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 MatrixArkAI
"""Context-pack construction and token budgeting."""

from __future__ import annotations

import math

from .models import ContextEvent, ContextPackItem, ResourceChunk


def estimate_tokens(text: str) -> int:
    words = len(text.split())
    return max(1, math.ceil(words * 1.3))


def events_to_pack_items(events: list[ContextEvent], max_prompt_tokens: int) -> tuple[list[ContextPackItem], int]:
    items: list[ContextPackItem] = []
    used = 0
    for event in events:
        tokens = estimate_tokens(event.text)
        if used + tokens > max_prompt_tokens:
            continue
        items.append(
            ContextPackItem(
                event_id_hash=event.event_id_hash,
                node_hash=event.node_hash,
                text=event.text,
                event_time_ms=event.event_time_ms,
                event_type=event.event_type,
                reason=f"{event.event_type} matched TemporalStore time, filter, and recall plan",
                estimated_tokens=tokens,
                attrs=event.compact_attrs,
                source_ref=event.raw_object_ref,
            )
        )
        used += tokens
    return items, used


def chunks_to_pack_items(chunks: list[ResourceChunk], max_prompt_tokens: int) -> tuple[list[ContextPackItem], int]:
    items: list[ContextPackItem] = []
    used = 0
    for chunk in chunks:
        tokens = chunk.token_estimate or estimate_tokens(chunk.text)
        if used + tokens > max_prompt_tokens:
            continue
        source_ref = str(chunk.metadata.get("source_path", ""))
        if chunk.page_number is not None:
            source_ref = f"{source_ref}#page={chunk.page_number}"
        elif chunk.heading_path:
            source_ref = f"{source_ref}#{chunk.heading_path}"
        items.append(
            ContextPackItem(
                event_id_hash=chunk.chunk_id,
                node_hash=chunk.node_hash,
                text=chunk.text,
                event_time_ms=int(chunk.metadata.get("updated_at_ms", 0)),
                event_type="resource_chunk",
                reason="resource chunk matched TemporalStore embedding recall and filters",
                estimated_tokens=tokens,
                attrs=chunk.metadata,
                source_ref=source_ref,
            )
        )
        used += tokens
    return items, used
