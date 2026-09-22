from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.application import create_app
from tests.helpers import write_sample_zip


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
        storage_dir=str(tmp_path / "storage"),
        extract_delay_ms=0,
        worker_poll_interval_ms=20,
        worker_concurrency=2,
    )


@pytest.fixture
def client(tmp_settings: Settings) -> TestClient:
    application = create_app(tmp_settings)
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def sample_zip(tmp_path: Path) -> Path:
    return write_sample_zip(tmp_path / "sample_batch.zip")
