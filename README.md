# MatrixArk Context Runtime

The Python home of MatrixArk: context ingestion, retrieval, feedback, and the operator
tooling that runs around them. A caller hands it a raw user query plus optional hints;
it extracts the useful temporal signals, writes lightweight context events, updates
summary embeddings, and returns a token-budgeted context pack.

**Open source under the Apache License 2.0, for anyone in the world to use, fork,
modify and build on.** Issues and pull requests are welcome from everyone — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## The MatrixArk repositories

The core projects listed below are public and Apache-2.0:

| Project | Use it for | Execution model |
|---|---|---|
| **MatrixArk (this repository)** | Context ingestion, retrieval, and feedback | Python runtime, MCP and HTTP entry points, and agent hooks; configure storage and model providers explicitly. |
| [TemporalStore](https://github.com/matrixarkai/TemporalStore) | Temporal features, sequences, and context serving | Serving engine with its own endpoints, persistence, and replication settings. |
| [MatrixCache](https://github.com/matrixarkai/matrixcache) | Tiered caching inside a Rust application | Embedded library; the application owns authoritative data and network requests. |
| [MatrixRaft](https://github.com/matrixarkai/matrixraft) | Consensus inside a service | Embedded library; the host supplies transport and state-machine application. |
| [MatrixObject](https://github.com/matrixarkai/MatrixObject) | Distributed object storage | Object API with separately configured metadata and replica services. |
| [MatrixAdsDemo](https://github.com/matrixarkai/MatrixAdsDemo) | Exploring an ads retrieval and auction pipeline | Standalone generated-data demonstration, not a context-runtime deployment. |

This repository owns the Python context runtime and its agent and operator tooling.
TemporalStore owns the serving engine and also ships its Python LLM-context SDK and
Feast online-store integrations. Use those engine-specific packages from the
[TemporalStore repository](https://github.com/matrixarkai/TemporalStore), rather than
assuming every Python integration is installed by MatrixArk.

## Getting Help

Search [public issues](https://github.com/matrixarkai/matrixark/issues) before
opening a report. Include the revision, Python version, entry point, storage
adapter, and provider configuration with secrets removed. Supply a small synthetic
resource or query and the expected context result. For embedding problems, include
model identity and vector dimensions; for resource access, describe how the raw
resource remains available without publishing its private URI.

Do not attach model API keys, user conversations, or production context packs.
Follow the [security policy](SECURITY.md) for sensitive reports, not a public issue.
For code or documentation changes, start with [CONTRIBUTING.md](CONTRIBUTING.md).

## Deployment Responsibilities

| Component | Responsibility |
|---|---|
| MatrixArk runtime | Context ingestion, query planning, retrieval, packing, and feedback |
| Storage adapter | Connecting runtime state to the selected durable backend |
| Model providers | Extraction and embedding configuration, credentials, timeouts, and model lifecycle |
| Host application | Starting services, access control, request budgets, and handling provider failures |

Choose the context runtime for context workflows and TemporalStore's Feast integration for
online feature workflows. They can share a serving backend, but package installation does
not connect them automatically. Keep raw-resource access and model credentials configured
outside examples, and do not treat deterministic local providers as deployed model services.

## Implementation entry points

| Area | Start reading |
|---|---|
| Context service orchestration | [Runtime API](matrixark/api.py) |
| Storage protocol and local adapter | [Storage interfaces](matrixark/storage.py) |
| End-to-end agent integration example | [Agent flow](examples/agent_loop_flow.py) |

The storage protocol describes what the runtime needs from its backend; the local
adapter is not a durable service. Follow the deployment adapter instructions when
connecting retained context to a running backend, and configure model providers
separately from storage.

## Choose Your Starting Point

| Goal | Start with |
|---|---|
| Run a local context flow | [Quick start](#quick-start) and the examples below |
| Embed context ingestion and retrieval | [Integration shape](#integration-shape) |
| Connect durable serving state | [Deployment adapters](#deployment-adapters) |
| Serve Feast online features | [TemporalStore's Feast integration](https://github.com/matrixarkai/TemporalStore/tree/main/integrations/feast) |
| Configure feature-serving writes and expiry | [Native Feast provider](https://github.com/matrixarkai/TemporalStore/tree/main/integrations/feast/feast_temporalstore_command) |
| Build an agent-facing tool | The installed MCP, HTTP, and hook entry points below |

The local in-memory adapter and deterministic providers are a starting point, not a
durable deployment. Installing this package does not start TemporalStore or configure
model credentials. Choose a storage adapter, provider configuration, and service
lifecycle explicitly before relying on retained context across process restarts.

### Feature-serving configuration belongs to the engine

For Feast materialization and online reads, configure the provider in the
[TemporalStore command integration](https://github.com/matrixarkai/TemporalStore/tree/main/integrations/feast/feast_temporalstore_command).
That package owns bounded binary batches, timestamp-conditioned latest values,
optional key TTL, and adaptive timestamp prefetch for stale traffic. The prefetch
hint does not cache timestamps, and supported conditional writes still enforce
ordering on the server. Augmented writes and older-node fallbacks have different
concurrency limits, documented with the provider.

These are engine-client options, not MatrixArk context-adapter settings. Installing
or configuring MatrixArk does not enable Feast history, teardown key tracking, or
a distributed serving topology. Use the provider's setup and benchmark guides for
that workflow rather than inferring service throughput from context-runtime calls.

## Deployment and Upgrade Checklist

- Pin the Python package and storage-client versions. Choose context workflows
  here or online-feature workflows in the TemporalStore Feast integration;
  installing one does not configure the other.
- Select a durable adapter before relying on context across restarts. The
  in-memory adapter is a local implementation, not replicated persistence.
- Configure model providers, credentials, and download policy explicitly. The
  deterministic providers do not establish deployed model quality or latency.
- Preserve access to raw resource URIs as well as stored chunks and vectors.
  The runtime does not copy the original resource into serving storage.
- Treat an embedding-model change as a data migration: keep model identity,
  vector dimensions, and stored embeddings consistent with the query encoder.
  Do not compare context-extraction latency with storage-only read QPS.

## Context Workflow Map

| Input or action | Runtime output | Keep configured outside the runtime |
|---|---|---|
| Query or agent event | Validated context events and selected context nodes | Tenant identity, access policy, and request budgets. |
| Markdown, PDF, or text resource | Stable chunks, source metadata, and embedding records | Durable access to the original `raw_uri`; parsed storage does not copy the source file. |
| Retrieval request | Ranked, token-budgeted context pack | Storage connectivity and the model identity used for stored and query vectors. |
| Final answer and confirmation | Feedback events available to later retrieval | The agent's model call and the application's decision to accept an answer. |
| Online feature materialization | A separate TemporalStore Feast workflow | Install and configure the engine provider; a context adapter does not register it. |

Start with [resource ingestion](#resource-flow), the [agent loop](#agent-loop),
or [deployment adapters](#deployment-adapters) for the corresponding contract.
Deterministic example providers make local flows reproducible, but do not establish
the quality or latency of a deployed extraction or embedding model.

## Layout

```
matrixark/      the context runtime library: extraction, embeddings, planning, packing
tools/          the MCP server, the HTTP control plane and portal, the agent hooks,
                the validators and test harnesses, and the shell entry points
sdk/python/     the Python SDK
examples/       worked integrations
tests/          the end-to-end suites
```

Installed entry points:

| command | what it starts |
|---|---|
| `matrixark-mcp-server` | the MCP server |
| `matrixark-http-portal` | the HTTP control plane |
| `matrixark-agent-hook` | the agent hook |
| `matrixark-admin` | the admin CLI |
| `matrixark-local-recovery` | local recovery |

## Design

A few decisions shape the whole runtime, and each one is there to keep serving cheap:

- **A model registry that loads lazily**, so a fast test never pays for a model it does
  not use, and a deployment pays once.
- **A batchable embedding interface**, because recall is dominated by how many vectors
  you can embed per call, not by how fast one call returns.
- **A hierarchical context tree rather than a rigid filesystem path**, so a node can be
  created and summarised without inventing a directory layout for it first.
- **One serving store.** Events, nodes, chunks, indexes, embeddings and replay all live
  in TemporalStore; there is no second place for serving state to drift into.
- **Raw bytes referenced by URI, never copied in.** `raw_uri` points at the original;
  only parsed chunks and vectors are stored.
- **Validation before any write**, so a bad agent input fails loudly instead of becoming
  replayable context.

The default implementation is dependency-light and uses deterministic local models, so
the fast tests run without downloading anything. Docker runs the same flow with
`sentence-transformers/all-MiniLM-L6-v2` for embeddings and `google/flan-t5-small` as
the extraction-model provider, and configures
`Salesforce/blip-image-captioning-base` as the VLM provider path; local fast tests use
a deterministic VLM stand-in. OpenAI and AI-agent model callbacks fit behind the
provider interfaces in `matrixark/embeddings.py`, `matrixark/extraction.py` and
`matrixark/vlm.py`.

## Workflow

```mermaid
flowchart LR
  A["Customer query or hook event"] --> B["MatrixArk extraction"]
  B --> C["ContextEvent"]
  B --> D["ContextNode summary"]
  D --> E["Summary embedding"]
  C --> F["TemporalStore adapter"]
  E --> F
  R["MD / PDF / TXT resource"] --> P["Resource parser + chunks"]
  P --> F
  H["Raw query + hints"] --> I["Query planning"]
  I --> F
  F --> J["ContextPack"]
  J --> K["Cursor / agent final prompt"]
  K --> L["Feedback hook"]
  L --> B
```

## Quick start

From the repository root, install with Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

In Windows PowerShell, use `.\.venv\Scripts\Activate.ps1` instead of the
`source` line. Run the install and examples from this repository's root.

The base package has no third-party runtime dependencies. Install `.[models]` for
the optional model and document providers, or `.[api]` for the HTTP dependencies.
These extras do not provision a TemporalStore service. The in-memory adapter below
is useful for local flows; a durable deployment needs an explicitly configured
storage adapter and a running serving engine.

Run the unit tests:

```bash
python -m unittest discover -s tests -v
```

Run a sample flow:

```bash
python examples/gpu_purchase_flow.py
python examples/agent_loop_flow.py
```

Run Docker with open-source embeddings:

```bash
docker compose build
MATRIXARK_ALLOW_MODEL_DOWNLOAD=1 docker compose run --rm matrixark-test
```

If your Docker install uses the legacy CLI, replace `docker compose` with
`docker-compose`.

## Integration shape

The caller does not have to define schemas. It sends:

- `tenant_id`
- raw text from a query, document, tool result, or final answer
- optional hints such as team, project, user, timestamps, token budget, and source

MatrixArk owns the harder work:

- infer time windows and filters
- choose or create a small number of context nodes
- validate API input, prompt budgets, resource paths and embedding records before any
  serving-state write
- write `ContextEvent` records
- parse `.md`, `.pdf` and `.txt` resources into stable chunks
- update summary embeddings asynchronously
- store embedding-model and VLM-model vectors for queries and summaries
- query by scope, time, filters, candidate nodes and resource chunks
- build replayable `ContextPack` results
- record agent query, final-answer feedback and user confirmation back as events

## Deployment adapters

The included adapter is in-memory and testable. A production TemporalStore adapter
implements the same protocol — `TemporalStoreAdapter`: write and query context events,
nodes, indexes, dirty summary markers, resource documents, resource chunks, summary
and chunk embeddings, and context-pack audits.

TemporalStore is the only serving store. Raw files are mounted or referenced by
`raw_uri`; parsed serving data and vectors are stored through TemporalStore.

### Context APIs and online features

Context ingestion and token-budgeted retrieval are this package's workflows.
Feast latest-value serving is a separate TemporalStore integration: install and
configure its provider from the engine repository. Installing MatrixArk does not
register a Feast provider, materialize offline features, start a cache server,
or establish a replicated storage cluster.

Keep performance measurements scoped to the API being used. Context extraction,
embedding generation, retrieval, and prompt packing include different work from
an online feature point read. For feature-serving materialization and read
workloads, use the engine's
[benchmark guide](https://github.com/matrixarkai/TemporalStore/blob/main/docs/feast_online_store_benchmark.md)
with matching payloads, durability, and concurrency. Do not infer context-model
quality or end-to-end agent latency from storage QPS alone.

## API safety

The public Python service raises `MatrixArkValidationError` **before** storage writes
when required fields are missing, text or query payloads exceed configured bounds,
prompt budgets are invalid, resource paths do not exist, or embedding vectors are
malformed. That keeps the adapter focused on persistence, and keeps bad agent input
from becoming replayable context.

## Resource flow

`ingest_resource()` takes a `ResourceIngestRequest` with `tenant_id`, `raw_uri` and
optional `team`, `project` and `title` hints.

- Markdown preserves heading paths.
- PDF extracts page text when `pypdf` is installed, with a plain-text fallback for
  lightweight tests.
- TXT chunks paragraph text.
- Every chunk stores its source path, offsets, page or heading metadata, token
  estimate, and an embedding record.

## Agent loop

`MockAiAgentHarness` shows the integration a vertical Cursor or agent host is expected
to make:

1. The agent sends a raw query through `agent_query()`.
2. MatrixArk records it as a temporal event and returns a `ContextPack`.
3. The agent calls its LLM with local context plus that pack.
4. The agent sends the final answer through `agent_final_answer()`.
5. The user replies — say, "Yes, that is correct."
6. MatrixArk classifies that reply as confirmation and stores it through
   `agent_confirmation()`.

Query, final answer and confirmation are all injected as events, so later prompts can
reuse accepted answers and confirmed memories. Query and VLM query embeddings are
persisted too, for replay and diagnostics.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
