# Future Scope — Large-Scale Production

This document describes how the current assignment system would evolve. **None of this is implemented.** It is a growth map from the seams that already exist: `ExtractionClient`, `StorageBackend`, document-queue claims, repositories, and thin controllers.

Target: tens of thousands of documents per hour, multiple API instances, durable processing, real extractors, and human review at team scale.

## Coverage checklist

| Requirement | Where it is specified |
|---|---|
| Real document extraction or OCR providers | [Real document extraction or OCR](#real-document-extraction-or-ocr) |
| Editing extracted findings | [Editing extracted findings](#editing-extracted-findings) |
| Multiple reviewers and user roles | [Multiple reviewers and user roles](#multiple-reviewers-and-user-roles) |
| Persistent object storage | [Persistent object storage](#persistent-object-storage) |
| Higher processing volumes | [Higher processing volumes](#higher-processing-volumes) |
| Distributed workers | [Distributed workers](#distributed-workers) |
| Additional document formats and extraction rules | [Additional document formats and extraction rules](#additional-document-formats-and-extraction-rules) |

Keep the **domain model** (`Batch` → `Document` → `Finding`) and the **HTTP resource shape**. Replace the infrastructure behind repositories and protocols.

## Target architecture

This is the production shape. The API accepts the upload and returns. A separate ingestion worker unpacks the ZIP. Extraction workers pull from a queue and call one adapter. Review reads findings from Postgres.

```mermaid
flowchart TD
  Client[Client] --> API[API Service]
  API --> OBJ["Object Store\nZIP / Documents"]
  API --> PG["PostgreSQL\nMetadata"]
  OBJ --> Ingest[ZIP / Ingestion Worker]
  Ingest --> Q[Queue]
  Q --> W1[Worker 1]
  Q --> W2[Worker 2]
  Q --> WN[Worker N]
  W1 --> Adapter["Extraction Adapter\nMock API / OCR Provider / LLM Provider"]
  W2 --> Adapter
  WN --> Adapter
  Adapter --> Findings["Findings\nPending / Accepted / Rejected"]
  PG -.-> Findings
  Findings --> Review[Review UI]
```

| Component | Responsibility |
|---|---|
| **Client** | Uploads the ZIP and variable list. Later, the review UI is a client of the same API. |
| **API Service** | Stateless FastAPI replicas. Validates the request, stores the ZIP in the object store, writes the `Batch` row in Postgres, returns **202**. Does not unzip and does not call OCR or an LLM. |
| **Object store** | Durable bytes: original ZIP, then one object per document (`s3://…/{batch_id}/{filename}`). Shared by the API, the ingestion worker, and extraction workers. |
| **PostgreSQL** | Metadata only: batches, documents, findings, review status. Findings the review UI shows live here. |
| **ZIP / ingestion worker** | Reads the ZIP from the object store, streams **one file at a time** (≤ 15 MB), writes the document object, inserts a `Document` row, enqueues `document_id`. Drops the file buffer before the next entry. |
| **Queue** | One message per document. Decouples unpacking from extraction so worker count follows queue depth. |
| **Worker 1…N** | Each claims one message, loads that document from the object store, calls the extraction adapter, writes findings as `pending`. Scale N by vendor QPS, not by file count. |
| **Extraction adapter** | The `ExtractionClient` seam. Implementations: **Mock API** (today), **OCR provider** (scanned pages), **LLM provider** (structured variables on text). Workers depend on the adapter, not on a vendor SDK. |
| **Findings** | One row per variable: `pending`, then `accepted` or `rejected`. Written by workers; updated by the review API. |
| **Review UI** | Lists pending findings and posts accept / reject / edit. Reads Postgres through the API. |

Request path:

1. Client → API → object store (ZIP) and Postgres (`Batch` = `queued`).
2. Ingestion worker unpacks into document objects + `Document` rows and enqueues one job each.
3. Workers call the adapter. The adapter picks mock, OCR, or LLM from the file type and the variable schema.
4. Findings land in Postgres as `pending`.
5. Review UI accepts or rejects them.

Memory stays flat because no stage holds `N × 15 MB`. The API stores the ZIP and returns. The ingestion worker keeps one entry. Each extraction worker keeps one document. Peak RAM is `N_workers × jobs_in_flight × 15 MB × decode overhead`.

`DocumentProcessingService` stays behind the workers. The in-process `DocumentProcessingWorker` poller is removed from the API process.

## Current limits that force the change

| Area | v1 | Why it breaks in production |
|---|---|---|
| Compute | One Uvicorn process, in-process poller | Cannot scale ingest and extract independently; restart drops in-flight work |
| Queue | `SELECT` + `UPDATE ... WHERE status=queued` on SQLite | Writer lock, no visibility timeout, stale `processing` rows |
| Storage | Local disk `storage/{batch_id}/` | Not shared across hosts; no lifecycle or encryption |
| Database | SQLite | No concurrent writers, no replicas, no point-in-time recovery |
| Ingest | Whole ZIP in memory | 1,000 × 15 MB ≈ 15 GB RAM per request |
| Extractor | Mock, no retries | Real OCR/LLM is slow, rate-limited, and flaky |
| Review | Poll + no auth | No roles, no audit, no push when a batch is ready |
| Ops | No metrics/tracing | Cannot SLO extract latency or find poison documents |

## Phased evolution

Phases follow the diagram from the top down.

### Phase 1 — API, object store, Postgres

- API stores the ZIP in the object store and the `Batch` row in Postgres, then returns **202**. It does not unzip.
- `S3StorageAdapter` for `StorageBackend`. `storage_path` is an object key, not a local path.
- AuthN (JWT/OIDC) in front of controllers; services unchanged.
- Structured logs, request id, metrics (`batches_accepted`, `documents_processed`, `extract_latency`).

### Phase 2 — ZIP ingestion worker and queue

- A dedicated ingestion worker reads the ZIP from the object store and streams one entry at a time (≤ 15 MB).
- Each entry becomes a document object, a `Document` row, and one queue message (`document_id`).
- The API process no longer runs `DocumentProcessingWorker`.

### Phase 3 — Workers 1…N and the extraction adapter

- N workers consume the queue. Each holds one document, calls the extraction adapter, writes findings as `pending`.
- Adapter implementations: Mock API first, then OCR and LLM behind the same `ExtractionClient`.
- Lease / visibility timeout, backoff, dead-letter queue. Unique `(document_id, variable_name)` so a retry upserts.
- Stale reclaim: `status=processing AND lease_expires_at < now()` back to `queued`.
- Digital files use local text plus the LLM. Scanned pages use the OCR provider, then the LLM only for the requested variables.

### Phase 4 — Review UI and compliance

- Edit finding value (`PATCH`); append-only `finding_events` (who, before, after, reason).
- Roles: `submitter`, `reviewer`, `admin`. Dual control later (two reviewers).
- Webhook / email on `document.completed` and `batch.completed` so review is push, not only poll.
- Object lock / KMS encryption; retention and legal hold on stored contracts.
- Multi-tenant: `organization_id` on `Batch`; row-level isolation in repositories.

## Mapping assignment “future scope” to this design

### Real document extraction or OCR

v1 uses `MockExtractionClient` behind the `ExtractionClient` protocol. Production adds real providers **without changing** `DocumentProcessingService` or the HTTP API.

- New classes: `OcrExtractionClient`, `LlmExtractionClient`, vendor HTTP adapters (for example Textract, Document AI, a private OCR service). `build_extraction_client(settings)` already branches on `EXTRACTOR`.
- The worker already passes `ExtractionRequest` (`document_id`, `filename`, `storage_path`, `variables`). A real client reads bytes from object storage and sends them to the provider; the mock ignores bytes.
- Persist on `Finding`: `provider`, `model`, `raw_response`, `confidence`, `latency_ms`, optional bounding boxes / page numbers for OCR.
- Never call vendors from the API process. Extracts take 30–120s, need retries, and must not hold HTTP connections.
- Per-provider rate limiter and circuit breaker; timeout → retryable `failed`; 4xx validation → DLQ.
- Provider can be chosen per batch or per tenant (scanned PDF → OCR, native DOCX → text/LLM).

### Editing extracted findings

v1 only allows accept/reject. Production lets a reviewer correct the extracted value.

- `PATCH /api/v1/findings/{id}` with `{ "value": "..." }` on `FindingController`; `ReviewService.update_value(actor_id, finding_id, value)`.
- Write `finding_events` first (`old_value`, `new_value`, `actor_id`, `reason`, `at`), then update the row. Re-review after edit stays allowed.
- Optional: require a reason when editing; lock the field after `accepted` unless an admin reopens it.
- UI shows original extraction, confidence, and edited value side by side. The original extract is never overwritten in the event log.

### Multiple reviewers and user roles

v1 has no authentication; any caller can review. Production is multi-user.

**Roles** (enforced in middleware / dependencies in front of controllers; services receive `actor_id` + `role`, they do not parse JWTs):

| Role | Can |
|---|---|
| `submitter` | Upload batches, track own batches |
| `reviewer` | View assigned batches, accept/reject/edit findings |
| `lead_reviewer` | Reassign, reopen, dual-control second sign-off |
| `admin` | Tenants, extractor config, replay DLQ |

**Multiple reviewers**

- Assign a batch (or a document subset) to a review queue or named reviewers (`batch_reviewers`).
- Two reviewers may work the same batch: findings are claimed per row (`locked_by`, `locked_at`) so two people do not edit one field at once.
- Dual control (optional policy): `accepted` is provisional until a second reviewer confirms; store `reviewer_1` / `reviewer_2` on the finding or as two events.
- Conflict: if values differ, status `needs_resolution` for a lead reviewer.
- List pending work: `GET /batches?assigned_to=me&review_status=pending`.

### Persistent object storage

v1 writes files under `storage/{batch_id}/` on local disk. That is not shared across API replicas or workers.

- `S3StorageAdapter` (or GCS/Azure) implements `StorageBackend`. `Document.storage_path` becomes `s3://bucket/org/batch_id/filename`.
- Grow the protocol: `save_stream` (ingest without buffering 15 MB × N), `open` / `get` (workers and OCR), `presign_get` / `presign_put` (browser upload and review preview).
- API never returns a server filesystem path. Review UIs use short-lived signed URLs.
- Bucket private; KMS encryption; object versioning; lifecycle (expire raw files after N days, keep findings in Postgres).
- Optional object lock / legal hold for contracts. Malware scan on `PutObject` before a document is queued for extract.
- Delete path: tenant offboarding deletes the prefix and tombstones DB rows.

### Higher processing volumes

v1 can accept 1,000 documents per ZIP but processes them in one process with the ZIP in RAM. Production must ingest, extract, and review concurrently.

| Technique | Purpose |
|---|---|
| Streamed ZIP ingest | Bound memory to one 15 MB file, not 15 GB |
| Direct-to-object uploads | Client PUTs parts; API only stores keys (bypass API RAM) |
| Postgres + connection pooler | Concurrent API + workers |
| Queue + autoscaled workers | Absorb 1,000-doc spikes without growing the API |
| Idempotent jobs + DLQ | Poison documents do not block the queue |
| Batch status via counters / triggers | Avoid recounting 1,000 rows on every poll |
| Read replica for `GET /batches` | Review traffic off the write primary |
| Partition `documents` / `findings` by time or `batch_id` | Keep hot tables small |
| Per-tenant concurrency caps | Backpressure so one client cannot fill the cluster |
| Priority queues | SLA / interactive review vs overnight bulk |

Scale ingest and extract independently. The 1,000 × 15 MB cap is an ingest/memory problem; extract throughput is a worker × vendor-QPS problem.

### Distributed workers

v1 starts `DocumentProcessingWorker` inside the FastAPI lifespan and polls SQLite. The diagram splits that into two roles.

- **ZIP / ingestion worker** is the only process that unpacks. It enqueues one message per `document_id` (SQS, Redis, RabbitMQ, or Celery). The API never enqueues and never unzips.
- **Workers 1…N** consume that queue, call `DocumentProcessingService.process_claimed` through the extraction adapter, write findings, and ack.
- Lease / visibility timeout while extract runs; heartbeat extend; nack → exponential backoff; max attempts → dead-letter queue.
- Stale reclaim: `status=processing AND lease_expires_at < now()` back to `queued` (fixes the v1 “stuck processing after crash” limitation).
- Horizontal scale: worker count ≈ `queue_depth / target_extract_seconds`, capped by extractor QPS.
- Same claim idea as today (`UPDATE ... WHERE status=queued`) becomes “dequeue + lease” so two workers never extract the same document.

### Additional document formats and extraction rules

v1 allow-list is `.pdf`, `.docx`, `.doc`, `.txt`, `.rtf`. One unsupported file rejects the **entire ZIP**. Rules are only “these variable names, random mock values”.

**Formats**

- Extend ingest allow-list: PDF (native + scanned), images (TIFF/PNG/JPEG for OCR), DOCX/DOC, RTF, TXT, HTML, optionally XLSX for tabular contracts.
- Classify per file (`content_type`, `needs_ocr`) and route to the matching `ExtractionClient`.
- Unknown or blocked types mark **that document** `failed` with an error; the rest of the batch still processes.
- New formats are a `ZipArchiveService` allow-list change plus an extractor strategy; not a new API.

**Extraction rules**

- Per batch or tenant: a schema of variables (`name`, `type` date/money/text/enum, `required`, `regex`, `enum_values`, `description` for LLM prompts).
- Rules stored with the batch (not hardcoded in the mock heuristics).
- After extract: validate type/regex/required; invalid values stay on the finding with `validation_status=invalid` so reviewers see them first.
- Optional clause libraries (termination, governing law) as named extractors or prompt templates selected by contract type (lease vs NDA).

## Reliability, security, operations

**Reliability**

- At-least-once processing + idempotent writes.
- Retry policy: transient extractor errors retry; validation errors go to DLQ immediately.
- Batch completion is derived from document counts (already true in v1); emit `batch.completed` once via a transactional outbox.

**Security**

- Authn/z, tenant isolation, malware scan on upload (ClamAV/S3 malware protection) before extract.
- No public buckets; presigned URLs with short TTL.
- Secrets in a vault, not `.env` on disk.

**Observability**

- Trace id from API → queue message → worker → vendor HTTP.
- Dashboards: ingest rate, queue lag, extract p95, review pending age, DLQ size.
- Alert on queue lag and stuck `processing` older than 2× visibility timeout.

**Data**

- Automated Postgres backups and PITR.
- Object versioning on raw documents.
- GDPR: delete object + tombstone findings per tenant request.

## What we would not change

- Resource-oriented API (`/batches`, `/documents`, `/findings`) as the product contract.
- MVC + service + repository split; production code still must not put SQL or ZIP logic in controllers.
- `ExtractionClient` as the extraction adapter (mock, OCR, LLM) and `StorageBackend` as the object store.
- Per-document failure isolation: one bad file must not fail the batch (already v1 behavior).

## Suggested order of work

1. API writes the ZIP to the object store and the batch row to Postgres, then returns 202.
2. ZIP ingestion worker streams one file at a time and enqueues `document_id`.
3. Workers 1…N consume the queue through the extraction adapter (mock first).
4. Add OCR and LLM behind that adapter, with rate limits and a dead-letter queue.
5. Review UI on findings (`pending` / `accepted` / `rejected`), plus auth, edits, and roles.
6. Partitioning, read replicas, and tenant caps as volume grows.
