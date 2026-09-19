# MatrixArk Runtime Test Steps And Results

Date: 2026-06-16

Repo: `C:\root\src\github-services\matrixarkai-gitpush`

Branch: `main`

Commit tested before this update: local changes after `7c8f13ea60f76349b96fd3a74fedb02740ceb4ca`

## Summary

The MatrixArk Python runtime passed the local fast validation suite:

- Event ingestion into TemporalStore
- Public API validation for required fields, prompt budget, resource paths, and
  embedding records
- Raw-query retrieval from TemporalStore
- Staged e2e extraction -> recall -> filter -> pack test
- Feedback and confirmation event injection
- Embedding-model and VLM-model summary/query embeddings stored in TemporalStore
- Resource ingestion for Markdown, PDF fallback text, and TXT
- Resource query with AND filters
- Agent query -> context pack -> final answer -> confirmation loop
- Python compile check
- Docker Compose configuration check

Docker image build was attempted, but it did not reach MatrixArk code because the local environment timed out while pulling `python:3.11-slim` from Docker Hub.

## Test Steps

Run from:

```bash
cd /mnt/c/root/src/github-services/matrixarkai-gitpush
```

### 1. Unit Tests

Command:

```bash
PYTHONPATH=matrixark python3 -m unittest discover -s matrixark/tests -v
```

Result:

```text
test_ingest_retrieve_and_feedback ... ok
test_mock_ai_agent_query_feedback_and_confirmation_inject_events ... ok
test_extraction_recall_query_feedback_and_confirmation_pipeline ... ok
test_public_api_validation_rejects_bad_inputs ... ok
test_raw_query_plus_hints_is_enough_for_planning ... ok
test_resource_filters_are_and_conditions ... ok
test_temporalstore_only_resource_ingestion_and_query ... ok
test_time_window_filters_out_old_events ... ok

Ran 8 tests
OK
```

### 2. Staged Context Flow E2E Test

Command:

```bash
python3 -m unittest discover -s tests -p 'test_staged_context_flow_e2e.py' -v
```

Result:

```text
test_extraction_recall_query_feedback_and_confirmation_pipeline ... ok

Ran 1 test
OK
```

What it validates:

- Seed business events and resource files into TemporalStore.
- Extract approval/cost/resource events from raw text and files.
- Store context-node, document-summary, resource-chunk, query, and VLM embeddings in TemporalStore.
- Run raw query through extraction, embedding, TemporalStore recall, filtering, and pack building.
- Return both business-event and resource-chunk context with source refs.
- Inject final LLM feedback into TemporalStore.
- Treat the second user query as confirmation and inject a confirmation event.
- Verify replay audit contains extraction, embedding, recall, filter, and pack-stage notes.

### 3. Agent Loop Example

Command:

```bash
PYTHONPATH=matrixark python3 matrixark/examples/agent_loop_flow.py
```

Result: passed.

What it validates:

- Mock AI agent sends raw query.
- MatrixArk records the query as an `agent_query` TemporalStore event.
- MatrixArk retrieves a token-budgeted `ContextPack`.
- Mock agent sends final answer feedback.
- Mock user confirmation is recorded as a `confirmation` TemporalStore event.
- Context-pack replay metadata is stored.

### 4. GPU Purchase Example

Command:

```bash
PYTHONPATH=matrixark python3 matrixark/examples/gpu_purchase_flow.py
```

Result: passed.

What it validates:

- Business events are extracted from raw text.
- Approval/cost context is written to TemporalStore.
- Query-time context retrieval returns relevant approval context.
- Feedback is injected after the final answer.

### 5. Python Compile Check

Command:

```bash
PYTHONPATH=matrixark python3 -m compileall -q matrixark/matrixark
```

Result: passed.

### 6. Whitespace/Diff Check

Command:

```bash
git diff --check
```

Result: passed.

### 7. Docker Compose Config

Command:

```bash
cd /mnt/c/root/src/github-services/matrixarkai-gitpush/matrixark
docker-compose config
```

Result: passed.

What it validates:

- Docker service is syntactically valid.
- OSS model env vars are configured:
  - `MATRIXARK_EMBEDDING_PROVIDER=sentence-transformers`
  - `MATRIXARK_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2`
  - `MATRIXARK_EXTRACTION_PROVIDER=oss-llm`
  - `MATRIXARK_EXTRACTION_MODEL=google/flan-t5-small`
  - `MATRIXARK_VLM_PROVIDER=hf-vlm`
  - `MATRIXARK_VLM_MODEL=Salesforce/blip-image-captioning-base`

### 8. Docker Build

Command:

```bash
cd /mnt/c/root/src/github-services/matrixarkai-gitpush/matrixark
docker-compose build
```

Result: blocked by environment/network before MatrixArk code ran.

Observed output:

```text
Step 1/15 : FROM python:3.11-slim
failed to resolve reference "docker.io/library/python:3.11-slim":
failed to do request:
Head "https://registry-1.docker.io/v2/library/python/manifests/3.11-slim":
dial tcp ...:443: i/o timeout
Service 'matrixark-test' failed to build : Build failed
```

Interpretation:

- Docker is installed through WSL.
- Legacy `docker-compose` is available.
- The Dockerfile/Compose config is valid.
- The build did not reach dependency installation or MatrixArk tests.
- The blocker is Docker Hub base-image network access, not a MatrixArk runtime failure.

## Covered Test Scenarios

- `ingest()` writes `ContextNode`, `ContextEvent`, secondary index refs, summary dirty markers, and TemporalStore-owned embeddings.
- `ingest()` also writes VLM summary embeddings to TemporalStore.
- Public API validation rejects empty tenant/query ids, invalid prompt budgets,
  missing feedback query ids, nonexistent resource paths, and malformed embeddings.
- The staged e2e test validates extraction, embedding, recall, filter, pack, feedback, confirmation, and replay in one flow.
- `retrieve()` uses raw query + hints and returns relevant TemporalStore context.
- `retrieve()` stores query embeddings and VLM query embeddings in TemporalStore before recall.
- Time-window filtering excludes stale events.
- Resource ingestion parses `.md`, `.txt`, and `.pdf` fallback text.
- Resource chunks include source refs, heading/page metadata, and embeddings.
- Resource summaries and chunks include VLM embedding records in TemporalStore.
- Resource filters use AND behavior for team/project metadata.
- `agent_query()` records raw query events and retrieves context.
- `agent_final_answer()` injects final-answer feedback.
- A second user query such as "Yes, that is correct" is classified as confirmation and injected through `agent_confirmation()`.
- `replay()` returns stored context-pack audit metadata.

## Docker Test To Rerun When Network Works

```bash
cd /mnt/c/root/src/github-services/matrixarkai-gitpush/matrixark
docker-compose build
MATRIXARK_ALLOW_MODEL_DOWNLOAD=1 docker-compose run --rm matrixark-test
```

Expected result:

- Unit tests pass.
- `gpu_purchase_flow.py` passes.
- `agent_loop_flow.py` passes.
- Sentence-transformer embeddings and OSS extraction provider path initialize inside the container.
- Hugging Face VLM provider path initializes or falls back safely for text-only VLM embeddings.
