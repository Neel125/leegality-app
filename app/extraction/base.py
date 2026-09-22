from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ExtractionRequest:
    document_id: str
    filename: str
    storage_path: str
    variables: list[str]


class ExtractionClient(Protocol):
    async def extract(self, request: ExtractionRequest) -> dict[str, str]: ...
