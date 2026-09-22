# Contract Batch Processor

FastAPI service that accepts a ZIP of contract documents, extracts requested variables in the background via a mocked extraction API, and lets a reviewer accept or reject each finding.

The review UI is a single page at `/`. Swagger remains at `/docs`.

## Directory structure

```
.
├── main.py                         # Uvicorn entrypoint (port 8005)
├── requirements.txt
├── pytest.ini
├── .env.example
├── frontend/
│   └── index.html                  # Review UI served at /
├── docs/
│   ├── DESIGN.md                   # Current design, assumptions, trade-offs
│   └── FUTURE_SCOPE.md             # Production-scale evolution
├── app/
│   ├── application.py              # FastAPI app, lifespan worker
│   ├── config.py
│   ├── db.py
│   ├── dependencies.py
│   ├── routers.py
│   ├── controllers/                # HTTP: batches, documents, findings, health
│   ├── schemas/                    # Pydantic request/response
│   ├── models/                     # Batch, Document, Finding
│   ├── repositories/               # Persistence
│   ├── services/                   # ZIP ingest, batch, review, processing
│   ├── extraction/                 # ExtractionClient + mock
│   ├── storage/                    # Local file storage
│   └── workers/                    # Background document worker
└── tests/
    ├── conftest.py
    ├── helpers.py
    ├── api/
    ├── unit/
    └── fixtures/sample_batch.zip
```

`data/` (SQLite) and `storage/{batch_id}/` (unpacked documents) are created when the app runs.

## Requirements

- Python 3.11+
- `pip`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run

```bash
python -m app.main
```

Or:

```bash
uvicorn app.main:app --reload
```

`main.py` serves the app on port **8005**. Open:

- Review UI: http://127.0.0.1:8005/
- API docs: http://127.0.0.1:8005/docs

Use a **single Uvicorn worker**. Processing runs in-process; multiple OS workers would each run their own poller.

## Usage

Upload a ZIP plus the variables to extract (JSON array). The call returns immediately with a batch id.

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/batches \
  -F 'variables=["effective_date","expiry_date","governing_law","termination_clause"]' \
  -F "file=@tests/fixtures/sample_batch.zip;type=application/zip"
```

Poll until the batch finishes. `ready_for_review` is true as soon as any findings exist.

```bash
BATCH_ID=<id from previous response>
curl -sS "http://127.0.0.1:8000/api/v1/batches/${BATCH_ID}"
```

Inspect per-document status:

```bash
curl -sS "http://127.0.0.1:8000/api/v1/batches/${BATCH_ID}/documents"
```

List findings waiting for review, then accept or reject one:

```bash
curl -sS "http://127.0.0.1:8000/api/v1/batches/${BATCH_ID}/findings?review_status=pending"

curl -sS -X POST "http://127.0.0.1:8000/api/v1/findings/${FINDING_ID}/review" \
  -H "Content-Type: application/json" \
  -d '{"decision":"accepted"}'
```

Allowed document types inside the ZIP: `.pdf`, `.docx`, `.doc`, `.txt`, `.rtf`.

Limits: up to 1,000 documents per ZIP; each document up to 15 MB.

## Tests

```bash
pytest
```

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/app.db` | SQLAlchemy URL |
| `STORAGE_DIR` | `./storage` | Extracted document files (`storage/{batch_id}/`) |
| `EXTRACTOR` | `mock` | Extraction strategy |
| `EXTRACT_DELAY_MS` | `50` | Simulated extractor latency |
| `WORKER_CONCURRENCY` | `10` | Parallel document extracts |
| `WORKER_POLL_INTERVAL_MS` | `200` | Idle poll interval |
| `MAX_DOCUMENTS_PER_ZIP` | `1000` | Archive file cap |
| `MAX_DOCUMENT_BYTES` | `15728640` | Per-file cap (15 MB) |

See [docs/DESIGN.md](docs/DESIGN.md) for current architecture and [docs/FUTURE_SCOPE.md](docs/FUTURE_SCOPE.md) for how this would scale in production.
