from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from matrixark import IngestRequest, MatrixArkContextService, MockAiAgentHarness, ResourceIngestRequest


class StagedContextFlowE2ETest(unittest.TestCase):
    def test_extraction_recall_query_feedback_and_confirmation_pipeline(self) -> None:
        service = MatrixArkContextService()
        tenant_id = "company_a"
        now_ms = 1_781_100_000_000
        hints = {
            "team": "infra_team",
            "project": "project_1",
            "actor": "alice",
            "max_prompt_tokens": 180,
        }

        approval = service.ingest(
            IngestRequest(
                tenant_id=tenant_id,
                text="Alice approved Project 1 GPU purchase request 8891 for 42000 USD.",
                source="before_llm_hook",
                event_time_ms=1_781_000_000_000,
                hints=hints,
            )
        )
        cost = service.ingest(
            IngestRequest(
                tenant_id=tenant_id,
                text="Project 1 spent 39000 USD on cloud GPU capacity last month.",
                source="tool_result_hook",
                event_time_ms=1_781_000_100_000,
                hints=hints,
            )
        )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runbook = base / "gpu_runbook.md"
            budget = base / "budget.txt"
            approval_pdf = base / "approval.pdf"
            runbook.write_text(
                "# GPU Runbook\n\n## Approval\n\nProject 1 GPU expansions require finance approval.\n\n"
                "## Budget\n\nCompare approved purchase request 8891 with current cloud GPU spend.",
                encoding="utf-8",
            )
            budget.write_text(
                "Project 1 GPU budget guidance: do not exceed 50000 USD without finance confirmation.",
                encoding="utf-8",
            )
            approval_pdf.write_text(
                "PDF fallback fixture: request 8891 was approved by Alice for Project 1 GPU expansion.",
                encoding="utf-8",
            )

            resources = [
                service.ingest_resource(
                    ResourceIngestRequest(
                        tenant_id=tenant_id,
                        raw_uri=str(path),
                        hints=hints,
                        event_time_ms=1_781_000_200_000,
                    )
                )
                for path in (runbook, budget, approval_pdf)
            ]

            agent_result = MockAiAgentHarness(service).run(
                tenant_id=tenant_id,
                query="Can we approve another GPU batch for Project 1 based on approval and budget?",
                hints=hints,
                now_ms=now_ms,
                second_user_query="Yes, that is correct. Please remember it.",
            )

        pack = agent_result.context_pack
        replay = service.replay(tenant_id, agent_result.query_id)
        self.assertIsNotNone(replay)
        self.assertGreaterEqual(len(pack.items), 2)
        self.assertLessEqual(pack.estimated_tokens, hints["max_prompt_tokens"])
        self.assertIn(approval.node_hash, pack.plan.candidate_node_hashes)
        self.assertIn(cost.node_hash, pack.plan.candidate_node_hashes)
        self.assertIn("cost_related", pack.plan.filters)
        self.assertIn("approval", {item.event_type for item in pack.items})
        self.assertTrue(any(item.event_type == "resource_chunk" for item in pack.items))
        self.assertTrue(any(item.source_ref for item in pack.items if item.event_type == "resource_chunk"))

        event_types = [
            event.event_type
            for events in service.temporalstore.events.values()
            for event in events
        ]
        self.assertIn("approval", event_types)
        self.assertIn("cost", event_types)
        self.assertIn("resource_ingested", event_types)
        self.assertIn("agent_query", event_types)
        self.assertIn("feedback", event_types)
        self.assertIn("confirmation", event_types)
        self.assertEqual(agent_result.final_event.event_type, "feedback")
        self.assertEqual(agent_result.confirmation_event.event_type, "confirmation")

        embedding_ref_types = {
            record.ref_type
            for (record_tenant, _), record in service.temporalstore.embeddings.items()
            if record_tenant == tenant_id
        }
        self.assertIn("context_node", embedding_ref_types)
        self.assertIn("document_summary", embedding_ref_types)
        self.assertIn("resource_chunk", embedding_ref_types)
        self.assertIn("query_embedding", embedding_ref_types)
        self.assertIn("vlm_query_embedding", embedding_ref_types)
        self.assertIn("vlm_context_summary", embedding_ref_types)
        self.assertIn("vlm_resource_chunk", embedding_ref_types)

        self.assertIn((tenant_id, f"query:{agent_result.query_id}"), service.temporalstore.embeddings)
        self.assertIn((tenant_id, f"vlm-query:{agent_result.query_id}"), service.temporalstore.embeddings)
        for resource in resources:
            self.assertIn((tenant_id, resource.node_hash), service.temporalstore.embeddings)
            self.assertIn((tenant_id, f"vlm-summary:{resource.node_hash}"), service.temporalstore.embeddings)

        notes = " ".join(replay.decision_notes)
        self.assertIn("extraction stage", notes)
        self.assertIn("embedding stage", notes)
        self.assertIn("recall stage", notes)
        self.assertIn("filter stage", notes)
        self.assertIn("pack stage", notes)


if __name__ == "__main__":
    unittest.main()
