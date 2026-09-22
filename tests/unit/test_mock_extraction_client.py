import pytest

from app.extraction.base import ExtractionRequest
from app.extraction.mock_client import MockExtractionClient


@pytest.fixture
def extractor() -> MockExtractionClient:
    return MockExtractionClient(delay_ms=0)


@pytest.mark.asyncio
async def test_returns_all_requested_keys(extractor: MockExtractionClient) -> None:
    variables = ["effective_date", "monthly_rent", "governing_law", "notice_period", "termination_clause", "other"]
    result = await extractor.extract(
        ExtractionRequest(
            document_id="d1",
            filename="lease.txt",
            storage_path="/tmp/lease.txt",
            variables=variables,
        )
    )
    assert set(result) == set(variables)


@pytest.mark.asyncio
async def test_heuristic_shapes(extractor: MockExtractionClient) -> None:
    result = await extractor.extract(
        ExtractionRequest(
            document_id="d1",
            filename="lease.txt",
            storage_path="/tmp/lease.txt",
            variables=["effective_date", "security_deposit", "governing_law", "notice_period"],
        )
    )
    assert result["effective_date"].count("-") == 2
    assert result["security_deposit"].startswith("INR ")
    assert result["governing_law"] in MockExtractionClient.JURISDICTIONS
    assert result["notice_period"] in MockExtractionClient.PERIODS
