from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from matrixark import (
    FeedbackRequest,
    IngestRequest,
    MatrixArkContextService,
    MatrixArkValidationError,
    MockAiAgentHarness,
    ResourceIngestRequest,
    RetrieveRequest,
)


class MatrixArkPipelineTest(unittest.TestCase):
    def test_ingest_retrieve_and_feedback(self) -> None:
        service = MatrixArkContextService()
        tenant_id = "company_a"
        hints = {"team": "infra_team", "project": "project_1", "actor": "alice"}

        ingest_result = service.ingest(
            IngestRequest(
                tenant_id=tenant_id,
                text="Alice approved the GPU purchase request for Project 1. Budget is 42000 USD.",
                source="before_llm_hook",
                event_time_ms=1_781_000_000_000,
                hints=hints,
            )
        )

        self.assertEqual(ingest_result.event_type, "approval")
        self.assertTrue(ingest_result.summary_dirty)
        self.assertIn("project_1", ingest_result.node_path)
        self.assertIn((tenant_id, ingest_result.node_hash), service.temporalstore.embeddings)
        self.assertIn((tenant_id, f"vlm-summary:{ingest_result.node_hash}"), service.temporalstore.embeddings)

        pack = service.retrieve(
            RetrieveRequest(
                tenant_id=tenant_id,
                query="Can we buy another GPU batch for Project 1 based on approval?",
                hints={"team": "infra_team", "project": "project_1"},
                max_prompt_tokens=100,
                now_ms=1_781_100_000_000,
            )
        )

        self.assertGreaterEqual(len(pack.items), 1)
        self.assertEqual(pack.items[0].event_type, "approval")
        self.assertLessEqual(pack.estimated_tokens, 100)
        self.assertIsNotNone(service.replay(tenant_id, pack.query_id))
        self.assertIn((tenant_id, f"query:{pack.query_id}"), service.temporalstore.embeddings)
        self.assertIn((tenant_id, f"vlm-query:{pack.query_id}"), service.temporalstore.embeddings)

        feedback = service.feedback(
            FeedbackRequest(
                tenant_id=tenant_id,
                query_id=pack.query_id,
                final_answer="The final answer recommends checking remaining GPU budget before buying more.",
                hints={"team": "infra_team", "project": "project_1"},
                event_time_ms=1_781_100_005_000,
            )
        )
        self.assertEqual(feedback.event_type, "feedback")

    def test_time_window_filters_out_old_events(self) -> None:
        service = MatrixArkContextService()
        tenant_id = "company_a"
        hints = {"team": "infra_team", "project": "project_1"}
        service.ingest(
            IngestRequest(
                tenant_id=tenant_id,
                text="Alice approved the GPU purchase request for Project 1.",
                event_time_ms=1_700_000_000_000,
                hints=hints,
            )
        )
        pack = service.retrieve(
            RetrieveRequest(
                tenant_id=tenant_id,
                query="What approval happened today for Project 1?",
                hints={"team": "infra_team", "project": "project_1"},
                now_ms=1_781_100_000_000,
            )
        )
        self.assertEqual(pack.items, [])

    def test_raw_query_plus_hints_is_enough_for_planning(self) -> None:
        service = MatrixArkContextService()
        tenant_id = "company_a"
        service.ingest(
            IngestRequest(
                tenant_id=tenant_id,
                text="The team spent 39000 USD on cloud GPU capacity last month for Project 1.",
                event_time_ms=1_781_000_000_000,
                hints={"team": "infra_team", "project": "project_1"},
            )
        )
        pack = service.retrieve(
            RetrieveRequest(
                tenant_id=tenant_id,
                query="Show recent GPU cost for Project 1",
                hints={"team": "infra_team", "project": "project_1"},
                max_prompt_tokens=80,
                now_ms=1_781_100_000_000,
            )
        )
        self.assertEqual(pack.plan.extracted_intent, "cost_lookup")
        self.assertEqual(pack.plan.filters["cost_related"], "true")
        self.assertEqual(len(pack.items), 1)

    def test_temporalstore_only_resource_ingestion_and_query(self) -> None:
        service = MatrixArkContextService()
        tenant_id = "company_a"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            md_path = base / "gpu_runbook.md"
            txt_path = base / "budget.txt"
            pdf_path = base / "approval.pdf"
            md_path.write_text(
                "# GPU Runbook\n\n## Approval\n\nProject 1 GPU purchase requires finance approval before capacity is added.",
                encoding="utf-8",
            )
            txt_path.write_text("Project 1 budget note: GPU cloud capacity should stay below 50000 USD.", encoding="utf-8")
            pdf_path.write_text("PDF text fallback: Alice approved the Project 1 GPU purchase.", encoding="utf-8")

            for path in (md_path, txt_path, pdf_path):
                result = service.ingest_resource(
                    ResourceIngestRequest(
                        tenant_id=tenant_id,
                        raw_uri=str(path),
                        hints={"team": "infra_team", "project": "project_1"},
                        event_time_ms=1_781_000_000_000,
                    )
                )
                self.assertGreaterEqual(result.chunk_count, 1)
                self.assertTrue(result.summary_dirty)
                self.assertIn((tenant_id, f"vlm-summary:{result.node_hash}"), service.temporalstore.embeddings)

            pack = service.retrieve(
                RetrieveRequest(
                    tenant_id=tenant_id,
                    query="Find the GPU approval runbook for Project 1",
                    hints={"team": "infra_team", "project": "project_1"},
                    max_prompt_tokens=140,
                    now_ms=1_781_100_000_000,
                )
            )

            self.assertGreaterEqual(len(pack.items), 1)
            self.assertTrue(any(item.event_type == "resource_chunk" for item in pack.items))
            self.assertTrue(any(item.source_ref and ("gpu_runbook" in item.source_ref or "approval.pdf" in item.source_ref) for item in pack.items))
            self.assertGreaterEqual(len(service.temporalstore.resource_chunks), 3)

    def test_resource_filters_are_and_conditions(self) -> None:
        service = MatrixArkContextService()
        tenant_id = "company_a"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            keep = base / "keep.md"
            drop = base / "drop.md"
            keep.write_text("# GPU\n\nProject 1 GPU budget approval note.", encoding="utf-8")
            drop.write_text("# GPU\n\nProject 2 GPU budget approval note.", encoding="utf-8")
            service.ingest_resource(
                ResourceIngestRequest(tenant_id, str(keep), hints={"team": "infra_team", "project": "project_1"})
            )
            service.ingest_resource(
                ResourceIngestRequest(tenant_id, str(drop), hints={"team": "infra_team", "project": "project_2"})
            )
            pack = service.retrieve(
                RetrieveRequest(
                    tenant_id=tenant_id,
                    query="GPU budget approval note",
                    hints={"team": "infra_team", "project": "project_1"},
                    now_ms=1_781_100_000_000,
                )
            )
            refs = " ".join(item.source_ref or "" for item in pack.items)
            self.assertIn("keep.md", refs)
            self.assertNotIn("drop.md", refs)

    def test_mock_ai_agent_query_feedback_and_confirmation_inject_events(self) -> None:
        service = MatrixArkContextService()
        tenant_id = "company_a"
        hints = {"team": "infra_team", "project": "project_1", "actor": "alice", "max_prompt_tokens": 120}
        service.ingest(
            IngestRequest(
                tenant_id=tenant_id,
                text="Alice approved the Project 1 GPU purchase request for 42000 USD.",
                source="before_llm_hook",
                event_time_ms=1_781_000_000_000,
                hints=hints,
            )
        )

        result = MockAiAgentHarness(service).run(
            tenant_id=tenant_id,
            query="Can we approve another GPU batch for Project 1?",
            hints=hints,
            now_ms=1_781_100_000_000,
        )

        self.assertGreaterEqual(len(result.context_pack.items), 1)
        self.assertEqual(result.final_event.event_type, "feedback")
        self.assertEqual(result.confirmation_event.event_type, "confirmation")
        replay = service.replay(tenant_id, result.query_id)
        self.assertIsNotNone(replay)

        event_types = [
            event.event_type
            for events in service.temporalstore.events.values()
            for event in events
        ]
        self.assertIn("agent_query", event_types)
        self.assertIn("feedback", event_types)
        self.assertIn("confirmation", event_types)
        self.assertIn((tenant_id, f"query:{result.query_id}"), service.temporalstore.embeddings)
        self.assertIn((tenant_id, f"vlm-query:{result.query_id}"), service.temporalstore.embeddings)

    def test_public_api_validation_rejects_bad_inputs(self) -> None:
        service = MatrixArkContextService()

        with self.assertRaises(MatrixArkValidationError):
            service.ingest(IngestRequest(tenant_id="", text="valid text"))

        with self.assertRaises(MatrixArkValidationError):
            service.retrieve(RetrieveRequest(tenant_id="company_a", query="", max_prompt_tokens=100))

        with self.assertRaises(MatrixArkValidationError):
            service.retrieve(RetrieveRequest(tenant_id="company_a", query="hello", max_prompt_tokens=0))

        with self.assertRaises(MatrixArkValidationError):
            service.feedback(
                FeedbackRequest(
                    tenant_id="company_a",
                    query_id="",
                    final_answer="answer",
                )
            )

        with self.assertRaises(MatrixArkValidationError):
            service.ingest_resource(
                ResourceIngestRequest(
                    tenant_id="company_a",
                    raw_uri="/path/that/does/not/exist.md",
                )
            )


if __name__ == "__main__":
    unittest.main()
