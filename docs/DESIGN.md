# Design

## What this system does

A user uploads a ZIP of contract documents and a list of variables to extract. The API stores the batch, processes each document asynchronously through a mocked extraction API, and exposes the results for human review (accept / reject per finding). Clients track batch and per-document status by polling.

A single page at `/` is the review surface. OpenAPI remains at `/docs`.

## MVC mapping

This is MVC adapted for a JSON API:

| Layer | Role | Package |
|---|---|---|
| **Controller** | Class per resource (`BatchController`, …). Parse HTTP, call one service, return a schema | `app/controllers/` |
| **View** | Request/response JSON (Pydantic) | `app/schemas/` |
| **Model** | Entities + repositories | `app/models/`, `app/repositories/` |

Controllers never run SQL, unzip archives, or call the extractor. ORM objects are never returned to the client.

A **service layer** sits between controllers and the model so the background worker can reuse `DocumentProcessingService` instead of duplicating controller code.

```
Client
  -> Controller
    -> Service
      -> Repository -> SQLAlchemy entity
      -> ZipArchiveService / StorageBackend / ExtractionClient
    <- Pydantic schema
```

## Processing flow

1. `POST /api/v1/batches` validates the ZIP, writes files under `storage/{batch_id}/`, inserts a `Batch` and `Document` rows (`queued`), returns **202** with `poll_url` and `review_url`.
2. `DocumentProcessingWorker` (FastAPI lifespan) claims queued documents with an optimistic `UPDATE ... WHERE status=queued`.
3. `DocumentProcessingService` calls `ExtractionClient.extract(...)`. The mock client does not read file bytes; it returns random values with light heuristics (`*_date`, rent/deposit, governing law, notice period).
4. One `Finding` per variable is stored with `review_status=pending`. The document becomes `completed` or `failed`.
5. Batch status is derived: any in-flight document → `processing`; all terminal and any success → `completed`; all failed → `failed`.
6. Reviewers poll `GET /batches/{id}`. `ready_for_review` is true when `review.pending > 0`. Findings can be reviewed as soon as their document completes; the reviewer does not have to wait for the entire ZIP.
7. `POST /findings/{id}/review` with `{ "decision": "accepted" | "rejected" }`. Re-review is allowed. There is no audit log in v1.

## Principles and patterns

Applied only where they change the design:

- **SRP** — controllers, ZIP validation, review, and the worker each have one job.
- **DIP / OCP** — worker depends on `ExtractionClient` and `StorageBackend` protocols. A real OCR/LLM client or S3 adapter is a new class plus a factory branch.
- **Repository** — SQL stays out of services.
- **Dependency injection** — FastAPI `Depends`; `create_app` is the composition root.
- **Strategy + Factory** — `build_extraction_client(settings)`.
- **Producer–consumer** — ingest enqueues documents; the worker consumes them with a concurrency cap.
- **Lightweight state machine** — document `queued → processing → completed | failed`.

Skipped: custom Unit of Work (the SQLAlchemy session is enough), CQRS, event bus, Celery.

## Future evolution

Not implemented here. The production layout (API, object store, Postgres, ZIP ingestion worker, queue, workers 1…N, extraction adapter, review UI) is in [FUTURE_SCOPE.md](FUTURE_SCOPE.md).

Short mapping:

| Future need | Current seam |
|---|---|
| Real extraction / OCR | New `ExtractionClient`; persist provider/confidence on `Finding` |
| Edit findings | `PATCH` + `finding_events` |
| Audit history | Append-only events |
| Roles | Auth in front of controllers |
| Object storage | `StorageBackend` → S3 |
| Distributed workers | Same document queue, Celery/SQS consumers |
| Higher volume | Streamed ZIP ingest, Postgres, backpressure |

Notification of “please review” is pull-based today (`ready_for_review` + `review_url`). Production would add webhooks/email on `batch.completed`.

## Assumptions

- v1 runs as one process: FastAPI, an in-process worker, SQLite, and files under `storage/{batch_id}/`. That is enough to demonstrate the assignment, not to run multiple API hosts.
- The page at `/` is a thin client of the same API. It polls batch status and posts accept/reject. It does not own business rules.
- The mock extractor does not read document bytes. Files are still stored so a later OCR or LLM adapter can open `storage_path`.
- Extracted values are plausible stand-ins (dates, amounts, jurisdictions). They are not taken from the contract text.
- There is no login. Anyone who can reach the server can upload a batch and review findings.
- A reviewer may accept, reject, or change that decision. v1 does not record who changed it or the previous value.
- One human reviews a batch. Roles, assignment, and a second reviewer are out of scope.
- `variables` may be a JSON array (`["effective_date","governing_law"]`) or a comma-separated list (`effective_date,governing_law`).
- Duplicate file names inside a ZIP are renamed (`contract.txt`, `contract_2.txt`). `__MACOSX`, `.DS_Store`, and `._*` entries are skipped. Any other unsupported type rejects the whole ZIP.
- The 1,000-document and 15 MB limits are validation caps. v1 does not claim that a full 15 GB archive is safe to upload in memory.
- The original ZIP is discarded after a successful unpack. The stored documents are the source of truth.
- “Ready for review” is pull-based. The UI polls `GET /batches/{id}` and treats `ready_for_review` as the signal. There is no email or webhook.
- Production growth (object store, Postgres, a separate ZIP worker, a queue, workers 1…N, OCR/LLM behind the extraction adapter) is described in [FUTURE_SCOPE.md](FUTURE_SCOPE.md) and is not part of this build.

## Trade-offs

- **SQLite vs Postgres.** SQLite keeps setup to `pip install`, `pytest`, and `uvicorn`. It serializes writers and cannot be shared by several API instances. Postgres is the swap when the metadata moves off this machine; `DATABASE_URL` is already the seam.
- **In-process worker vs a queue and workers 1…N.** The lifespan poller needs no Redis or Celery and is enough for one host. It cannot scale extract independently of the API, and a crash can leave a document in `processing`. The future design puts unpacking in a ZIP ingestion worker and extraction on N queue consumers.
- **Whole ZIP in memory vs one file at a time.** Reading the upload and holding every entry simplifies validation. Peak RAM is about the size of the archive, so 1,000 × 15 MB can exhaust the API process. Streaming one entry, writing it, then dropping the buffer is the production ingest path.
- **Local disk vs object storage.** `storage/{batch_id}/` needs no cloud account and is easy to inspect. Those files are not shared across hosts and disappear with the disk. `StorageBackend` is the adapter boundary for S3 later.
- **Mock extraction vs OCR/LLM.** The mock returns immediately and makes the review flow testable without vendor keys, latency, or cost. The values are not grounded in the file. A real provider stays behind `ExtractionClient` so the worker and the review API do not change.
- **Polling UI vs push.** The page re-reads batch status every few seconds. That is enough for one reviewer sitting on the page. Email, webhooks, or a websocket would tell someone who is not watching; those belong with the production review UI.
- **Reject the whole ZIP vs fail one file.** A bad extension fails the upload before any document is queued, so the caller fixes the archive once. At higher volume, one unknown file should fail only that document so the other 999 still extract.


## Known limitations

- One Uvicorn process; the worker is not distributed.
- If the process dies mid-extract, a document can remain `processing` until a manual reset (a later worker should reclaim stale `processing` rows).
- The original ZIP is not retained after unpack; individual files are.
- Upload reads the ZIP into memory; theoretical 1,000 × 15 MB archives can exhaust RAM/disk.
- No auth, rate limiting, or virus scanning of uploads.
- Mock values are random, not grounded in document text.
- No finding edits, comments, or audit trail.
- SQLite is not suitable for multi-instance production.
