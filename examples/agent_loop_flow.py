from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matrixark import IngestRequest, MatrixArkContextService, MockAiAgentHarness, ResourceIngestRequest


def main() -> None:
    service = MatrixArkContextService()
    tenant_id = "company_a"
    hints = {"team": "infra_team", "project": "project_1", "actor": "alice", "max_prompt_tokens": 180}
    base = Path(__file__).resolve().parent / "resources"

    service.ingest(
        IngestRequest(
            tenant_id=tenant_id,
            text="Alice approved the Project 1 GPU purchase request for 42000 USD.",
            source="before_llm_hook",
            event_time_ms=1_781_000_000_000,
            hints=hints,
        )
    )
    service.ingest_resource(
        ResourceIngestRequest(
            tenant_id=tenant_id,
            raw_uri=str(base / "gpu_runbook.md"),
            hints=hints,
            event_time_ms=1_781_000_010_000,
        )
    )

    result = MockAiAgentHarness(service).run(
        tenant_id=tenant_id,
        query="Can we approve another GPU batch for Project 1?",
        hints=hints,
        now_ms=1_781_100_000_000,
    )

    print(
        json.dumps(
            {
                "query_id": result.query_id,
                "context_items": [asdict(item) for item in result.context_pack.items],
                "final_event_type": result.final_event.event_type,
                "confirmation_event_type": result.confirmation_event.event_type,
                "temporalstore_event_count": sum(len(events) for events in service.temporalstore.events.values()),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
