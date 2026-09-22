from app.config import Settings
from app.extraction.base import ExtractionClient
from app.extraction.mock_client import MockExtractionClient


def build_extraction_client(settings: Settings) -> ExtractionClient:
    provider = settings.extractor.lower()
    if provider == "mock":
        return MockExtractionClient(delay_ms=settings.extract_delay_ms)
    raise ValueError(f"Unsupported extractor: {settings.extractor}")
