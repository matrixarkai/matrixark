# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 MatrixArkAI
"""Stable hashing helpers for TemporalStore object keys."""

from __future__ import annotations

import hashlib


def stable_hash64(value: str) -> str:
    """Return a deterministic 64-bit hex hash for compact object keys."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return digest[:16]


def scope_hash(*parts: str) -> str:
    normalized = "/".join(part.strip().lower() for part in parts if part and part.strip())
    return stable_hash64(normalized or "global")


def canonical_path(*parts: str) -> str:
    clean = [part.strip().lower().replace(" ", "_") for part in parts if part and part.strip()]
    return "/".join(clean) if clean else "global"

