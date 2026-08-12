"""Validation helpers for MatrixArk public APIs."""

from __future__ import annotations

from pathlib import Path

from .models import (
    AgentConfirmationRequest,
    AgentFinalAnswerRequest,
    AgentQueryRequest,
    EmbeddingRecord,
    FeedbackRequest,
    IngestRequest,
    ResourceIngestRequest,
    RetrieveRequest,
)


class MatrixArkValidationError(ValueError):
    """Raised when a caller submits invalid MatrixArk API input."""


MAX_TEXT_BYTES = 256 * 1024
MAX_QUERY_BYTES = 32 * 1024
MAX_HINTS = 64
MAX_PROMPT_TOKENS = 200_000
MAX_EMBEDDING_DIM = 16_384


def validate_ingest_request(request: IngestRequest) -> None:
    _require_text("tenant_id", request.tenant_id)
    _require_text("text", request.text)
    _require_size("text", request.text, MAX_TEXT_BYTES)
    _validate_hints(request.hints)


def validate_retrieve_request(request: RetrieveRequest) -> None:
    _require_text("tenant_id", request.tenant_id)
    _require_text("query", request.query)
    _require_size("query", request.query, MAX_QUERY_BYTES)
    if request.max_prompt_tokens <= 0 or request.max_prompt_tokens > MAX_PROMPT_TOKENS:
        raise MatrixArkValidationError("max_prompt_tokens is out of range")
    _validate_hints(request.hints)


def validate_feedback_request(request: FeedbackRequest) -> None:
    _require_text("tenant_id", request.tenant_id)
    _require_text("query_id", request.query_id)
    _require_text("final_answer", request.final_answer)
    _require_size("final_answer", request.final_answer, MAX_TEXT_BYTES)
    _validate_hints(request.hints)


def validate_agent_query_request(request: AgentQueryRequest) -> None:
    validate_retrieve_request(
        RetrieveRequest(
            tenant_id=request.tenant_id,
            query=request.query,
            hints=request.hints,
            max_prompt_tokens=request.max_prompt_tokens,
            now_ms=request.now_ms,
        )
    )


def validate_agent_final_answer_request(request: AgentFinalAnswerRequest) -> None:
    validate_feedback_request(
        FeedbackRequest(
            tenant_id=request.tenant_id,
            query_id=request.query_id,
            final_answer=request.final_answer,
            accepted=request.accepted,
            hints=request.hints,
            event_time_ms=request.event_time_ms,
        )
    )


def validate_agent_confirmation_request(request: AgentConfirmationRequest) -> None:
    _require_text("tenant_id", request.tenant_id)
    _require_text("query_id", request.query_id)
    _require_text("confirmation_text", request.confirmation_text)
    _require_size("confirmation_text", request.confirmation_text, MAX_QUERY_BYTES)
    _validate_hints(request.hints)


def validate_resource_ingest_request(request: ResourceIngestRequest) -> None:
    _require_text("tenant_id", request.tenant_id)
    _require_text("raw_uri", request.raw_uri)
    if not Path(request.raw_uri).exists():
        raise MatrixArkValidationError("raw_uri does not exist")
    _validate_hints(request.hints)


def validate_embedding_record(record: EmbeddingRecord) -> None:
    _require_text("tenant_id", record.tenant_id)
    _require_text("ref_id", record.ref_id)
    _require_text("ref_type", record.ref_type)
    if not record.vector or len(record.vector) > MAX_EMBEDDING_DIM:
        raise MatrixArkValidationError("embedding vector has invalid dimension")
    if any(not isinstance(value, (float, int)) for value in record.vector):
        raise MatrixArkValidationError("embedding vector must contain numeric values")


def _require_text(name: str, value: str) -> None:
    if not value or not str(value).strip():
        raise MatrixArkValidationError(f"{name} is required")


def _require_size(name: str, value: str, max_bytes: int) -> None:
    if len(value.encode("utf-8")) > max_bytes:
        raise MatrixArkValidationError(f"{name} exceeds maximum size")


def _validate_hints(hints: dict[str, object]) -> None:
    if len(hints) > MAX_HINTS:
        raise MatrixArkValidationError("too many hints")
    for key in hints:
        if not isinstance(key, str) or not key.strip():
            raise MatrixArkValidationError("hint keys must be non-empty strings")
