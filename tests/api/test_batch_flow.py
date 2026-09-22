import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.extraction.base import ExtractionRequest
from app.application import create_app
from tests.helpers import build_zip_bytes, write_sample_zip


def wait_for_batch(client: TestClient, batch_id: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        response = client.get(f"/api/v1/batches/{batch_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in {"completed", "failed"} and body["progress"]["pending"] == 0:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Batch {batch_id} did not finish: {body}")


def upload(client: TestClient, zip_bytes: bytes, variables: list[str], filename: str = "batch.zip"):
    return client.post(
        "/api/v1/batches",
        files={"file": (filename, zip_bytes, "application/zip")},
        data={"variables": json.dumps(variables)},
    )


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_frontend_landing(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Contract batch review" in response.text


def test_upload_process_and_review(client: TestClient, sample_zip: Path) -> None:
    variables = ["effective_date", "governing_law"]
    response = upload(client, sample_zip.read_bytes(), variables)
    assert response.status_code == 202
    payload = response.json()
    batch_id = payload["id"]
    assert payload["document_count"] == 2
    assert payload["status"] == "queued"

    body = wait_for_batch(client, batch_id)
    assert body["status"] == "completed"
    assert body["progress"]["completed"] == 2
    assert body["progress"]["failed"] == 0
    assert body["ready_for_review"] is True
    assert body["review"]["pending"] == 4

    docs = client.get(f"/api/v1/batches/{batch_id}/documents")
    assert docs.status_code == 200
    items = docs.json()["items"]
    assert len(items) == 2
    document_id = items[0]["id"]

    detail = client.get(f"/api/v1/documents/{document_id}")
    assert detail.status_code == 200
    findings = detail.json()["findings"]
    assert {item["variable_name"] for item in findings} == set(variables)

    pending = client.get(f"/api/v1/batches/{batch_id}/findings", params={"review_status": "pending"})
    assert pending.status_code == 200
    finding_id = pending.json()["items"][0]["id"]

    accepted = client.post(f"/api/v1/findings/{finding_id}/review", json={"decision": "accepted"})
    assert accepted.status_code == 200
    assert accepted.json()["review_status"] == "accepted"

    flipped = client.post(f"/api/v1/findings/{finding_id}/review", json={"decision": "rejected"})
    assert flipped.json()["review_status"] == "rejected"


def test_invalid_zip_returns_400(client: TestClient) -> None:
    response = upload(client, b"not-a-zip", ["effective_date"], filename="batch.zip")
    assert response.status_code == 400


def test_missing_resources_return_404(client: TestClient) -> None:
    assert client.get("/api/v1/batches/missing").status_code == 404
    assert client.get("/api/v1/documents/missing").status_code == 404
    review = client.post("/api/v1/findings/missing/review", json={"decision": "accepted"})
    assert review.status_code == 404


def test_invalid_review_decision_returns_422(client: TestClient) -> None:
    response = client.post("/api/v1/findings/whatever/review", json={"decision": "pending"})
    assert response.status_code == 422


def test_one_document_failure_does_not_fail_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FlakyExtractor:
        async def extract(self, request: ExtractionRequest) -> dict[str, str]:
            if "fail" in request.filename:
                raise RuntimeError("extractor unavailable")
            return {variable: "ok" for variable in request.variables}

    monkeypatch.setattr("app.application.build_extraction_client", lambda _settings: FlakyExtractor())
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/fail.db",
        storage_dir=str(tmp_path / "storage"),
        extract_delay_ms=0,
        worker_poll_interval_ms=20,
        worker_concurrency=2,
    )
    application = create_app(settings)
    zip_bytes = build_zip_bytes({"ok.txt": b"ok", "fail.txt": b"nope"})
    with TestClient(application) as client:
        response = upload(client, zip_bytes, ["effective_date"])
        assert response.status_code == 202
        body = wait_for_batch(client, response.json()["id"])
        assert body["status"] == "completed"
        assert body["progress"]["completed"] == 1
        assert body["progress"]["failed"] == 1


def test_sample_fixture_roundtrip(client: TestClient) -> None:
    fixture = Path("tests/fixtures/sample_batch.zip")
    if not fixture.exists():
        write_sample_zip(fixture)
    response = upload(client, fixture.read_bytes(), ["monthly_rent"])
    assert response.status_code == 202
    wait_for_batch(client, response.json()["id"])
