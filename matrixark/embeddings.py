# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 MatrixArkAI
"""Embedding providers for summary and query vectors."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import Protocol

from .hashing import stable_hash64


class EmbeddingModel(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text."""


@dataclass(slots=True)
class HashingEmbeddingModel:
    """Deterministic no-download embedding model for tests and local demos."""

    dim: int = 96

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        for token in tokens:
            idx = int(stable_hash64(token), 16) % self.dim
            vector[idx] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class SentenceTransformerEmbeddingModel:
    """Optional open-source embedding provider with lazy model loading.

    Set MATRIXARK_ALLOW_MODEL_DOWNLOAD=1 before using this provider in a machine that
    may need to download the configured model.
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            if os.environ.get("MATRIXARK_ALLOW_MODEL_DOWNLOAD") != "1":
                raise RuntimeError("model download disabled; set MATRIXARK_ALLOW_MODEL_DOWNLOAD=1")
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [list(map(float, vector)) for vector in vectors]


class OpenSourceModelRegistry:
    """Lazy registry for swappable open-source extractors and embedders."""

    def __init__(self) -> None:
        self._embedders: dict[str, EmbeddingModel] = {
            "hashing-local": HashingEmbeddingModel(),
        }

    def embedding_model(self, name: str | None = None) -> EmbeddingModel:
        if name is None:
            provider = os.environ.get("MATRIXARK_EMBEDDING_PROVIDER", "hashing")
            if provider == "sentence-transformers":
                name = os.environ.get("MATRIXARK_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
            else:
                name = "hashing-local"
        if name in self._embedders:
            return self._embedders[name]
        if name.startswith("sentence-transformers/"):
            model = SentenceTransformerEmbeddingModel(name)
            self._embedders[name] = model
            return model
        raise KeyError(f"unknown embedding model: {name}")


def cosine_similarity(left: list[float], right: list[float]) -> float:
    total = 0.0
    for idx, value in enumerate(left[: min(len(left), len(right))]):
        total += value * right[idx]
    return total
