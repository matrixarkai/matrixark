# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 MatrixArkAI
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matrixark import FeedbackRequest, IngestRequest, MatrixArkContextService, RetrieveRequest


def main() -> None:
    service = MatrixArkContextService()
    tenant_id = "company_a"
    hints = {"team": "infra_team", "project": "project_1", "actor": "alice"}

    service.ingest(
        IngestRequest(
            tenant_id=tenant_id,
            text="Alice approved the GPU purchase request for Project 1. Budget is 42000 USD.",
            source="before_llm_hook",
            event_time_ms=1_781_000_000_000,
            hints=hints,
        )
    )
    service.ingest(
        IngestRequest(
            tenant_id=tenant_id,
            text="The team spent 39000 USD on cloud GPU capacity last month for Project 1.",
            source="tool_result_hook",
            event_time_ms=1_781_100_000_000,
            hints=hints,
        )
    )

    pack = service.retrieve(
        RetrieveRequest(
            tenant_id=tenant_id,
            query="Can we buy another GPU batch for Project 1 based on recent approval and cost?",
            hints={"team": "infra_team", "project": "project_1"},
            max_prompt_tokens=120,
            now_ms=1_781_200_000_000,
        )
    )

    service.feedback(
        FeedbackRequest(
            tenant_id=tenant_id,
            query_id=pack.query_id,
            final_answer="Final answer: buy only if finance confirms remaining GPU budget after the approved 42000 USD request.",
            hints={"team": "infra_team", "project": "project_1"},
            event_time_ms=1_781_200_005_000,
        )
    )

    print(
        json.dumps(
            {
                "query_id": pack.query_id,
                "replay_ref": pack.replay_ref,
                "estimated_tokens": pack.estimated_tokens,
                "items": [asdict(item) for item in pack.items],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
