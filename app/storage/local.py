import shutil
from pathlib import Path


class LocalStorageAdapter:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, batch_id: str, filename: str, data: bytes) -> str:
        directory = self.root / batch_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        path.write_bytes(data)
        return str(path)

    def delete_batch(self, batch_id: str) -> None:
        directory = self.root / batch_id
        if directory.exists():
            shutil.rmtree(directory)
