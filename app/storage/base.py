from typing import Protocol


class StorageBackend(Protocol):
    def save(self, batch_id: str, filename: str, data: bytes) -> str: ...

    def delete_batch(self, batch_id: str) -> None: ...
