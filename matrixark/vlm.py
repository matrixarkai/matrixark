# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 MatrixArkAI
"""VLM providers for multimodal query and summary embedding signals."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from .embeddings import EmbeddingModel, HashingEmbeddingModel


class VlmModel(Protocol):
    def embed_text(self, texts: list[str]) -> list[list[float]]:
        """Return VLM-derived vectors for text or text-plus-resource summaries."""


@dataclass(slots=True)
class LocalVlmModel:
    """Deterministic local VLM stand-in for offline tests."""

    embedder: EmbeddingModel | None = None

    def embed_text(self, texts: list[str]) -> list[list[float]]:
        model = self.embedder or HashingEmbeddingModel(dim=96)
        return model.embed([f"vlm semantic view: {text}" for text in texts])


class HuggingFaceVlmModel:
    """Optional Hugging Face VLM provider with a local deterministic fallback.

    The MVP stores VLM embeddings through the same TemporalStore interface. If the VLM
    model is unavailable or downloads are disabled, the deterministic fallback keeps the
    runtime testable.
    """

    def __init__(self, model_name: str, fallback: VlmModel | None = None) -> None:
        self.model_name = model_name
        self.fallback = fallback or LocalVlmModel()
        self._processor = None
        self._model = None

    def embed_text(self, texts: list[str]) -> list[list[float]]:
        if os.environ.get("MATRIXARK_ALLOW_MODEL_DOWNLOAD") != "1":
            return self.fallback.embed_text(texts)
        try:
            # Keep the provider path explicit for Docker/model wiring. The first VLM
            # implementation still falls back to deterministic vectors for text-only
            # tests because most VLMs need image inputs.
            from transformers import AutoProcessor, BlipForConditionalGeneration

            if self._processor is None:
                self._processor = AutoProcessor.from_pretrained(self.model_name)
                self._model = BlipForConditionalGeneration.from_pretrained(self.model_name)
        except Exception:
            return self.fallback.embed_text(texts)
        return self.fallback.embed_text(texts)


class VlmModelRegistry:
    def vlm_model(self, provider: str, model_name: str) -> VlmModel:
        if provider == "hf-vlm":
            return HuggingFaceVlmModel(model_name)
        return LocalVlmModel()

