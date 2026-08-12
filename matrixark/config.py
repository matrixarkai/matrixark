"""Runtime configuration for MatrixArk providers."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class MatrixArkConfig:
    embedding_provider: str = "hashing"
    embedding_model: str = "hashing-local"
    extraction_provider: str = "rule"
    extraction_model: str = "google/flan-t5-small"
    vlm_provider: str = "local"
    vlm_model: str = "Salesforce/blip-image-captioning-base"
    allow_model_download: bool = False

    @classmethod
    def from_env(cls) -> "MatrixArkConfig":
        provider = os.environ.get("MATRIXARK_EMBEDDING_PROVIDER", "hashing")
        default_model = "sentence-transformers/all-MiniLM-L6-v2" if provider == "sentence-transformers" else "hashing-local"
        return cls(
            embedding_provider=provider,
            embedding_model=os.environ.get("MATRIXARK_EMBEDDING_MODEL", default_model),
            extraction_provider=os.environ.get("MATRIXARK_EXTRACTION_PROVIDER", "rule"),
            extraction_model=os.environ.get("MATRIXARK_EXTRACTION_MODEL", "google/flan-t5-small"),
            vlm_provider=os.environ.get("MATRIXARK_VLM_PROVIDER", "local"),
            vlm_model=os.environ.get("MATRIXARK_VLM_MODEL", "Salesforce/blip-image-captioning-base"),
            allow_model_download=os.environ.get("MATRIXARK_ALLOW_MODEL_DOWNLOAD") == "1",
        )
