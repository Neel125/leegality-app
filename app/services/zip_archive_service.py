from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile, ZipInfo

from app.config import Settings
from app.services.errors import DomainValidationError

JUNK_NAMES = {".ds_store", "thumbs.db"}
JUNK_PREFIXES = ("__macosx",)
READ_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class ZipEntry:
    filename: str
    size_bytes: int
    data: bytes


class ZipArchiveService:
    def __init__(self, settings: Settings) -> None:
        self.max_documents = settings.max_documents_per_zip
        self.max_document_bytes = settings.max_document_bytes
        self.allowed_extensions = tuple(ext.lower() for ext in settings.allowed_extensions)

    def extract(self, zip_bytes: bytes) -> list[ZipEntry]:
        try:
            archive = ZipFile(BytesIO(zip_bytes))
        except BadZipFile as exc:
            raise DomainValidationError("Uploaded file is not a valid ZIP archive") from exc

        entries: list[ZipEntry] = []
        used_names: dict[str, int] = {}
        with archive:
            infos = archive.infolist()
            for info in infos:
                entry = self._read_entry(archive, info, used_names)
                if entry is None:
                    continue
                entries.append(entry)
                if len(entries) > self.max_documents:
                    raise DomainValidationError(
                        f"ZIP contains more than {self.max_documents} documents"
                    )

        if not entries:
            raise DomainValidationError("ZIP contains no extractable documents")
        return entries

    def _read_entry(
        self, archive: ZipFile, info: ZipInfo, used_names: dict[str, int]
    ) -> ZipEntry | None:
        if info.is_dir():
            return None
        if self._is_junk(info.filename):
            return None

        base = self._safe_basename(info.filename)
        ext = Path(base).suffix.lower()
        if ext not in self.allowed_extensions:
            raise DomainValidationError(f"Unsupported file type: {base}")

        unique_name = self._unique_name(base, used_names)
        data = self._read_limited(archive, info, unique_name)
        return ZipEntry(filename=unique_name, size_bytes=len(data), data=data)

    def _safe_basename(self, name: str) -> str:
        normalized = name.replace("\\", "/")
        if normalized.startswith("/"):
            raise DomainValidationError("Absolute paths are not allowed in the ZIP")
        if ".." in Path(normalized).parts:
            raise DomainValidationError("Path traversal is not allowed in the ZIP")
        base = Path(normalized).name
        if not base or base in {".", ".."}:
            raise DomainValidationError("Invalid filename in the ZIP")
        return base

    def _is_junk(self, name: str) -> bool:
        normalized = name.replace("\\", "/").lower()
        parts = Path(normalized).parts
        if any(part.startswith(JUNK_PREFIXES) for part in parts):
            return True
        base = Path(normalized).name
        if base in JUNK_NAMES or base.startswith("._"):
            return True
        return False

    def _unique_name(self, base: str, used_names: dict[str, int]) -> str:
        stem = Path(base).stem
        ext = Path(base).suffix
        count = used_names.get(base.lower(), 0)
        used_names[base.lower()] = count + 1
        if count == 0:
            return base
        return f"{stem}_{count + 1}{ext}"

    def _read_limited(self, archive: ZipFile, info: ZipInfo, filename: str) -> bytes:
        chunks: list[bytes] = []
        total = 0
        with archive.open(info) as source:
            while True:
                chunk = source.read(READ_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_document_bytes:
                    limit_mb = self.max_document_bytes // (1024 * 1024)
                    raise DomainValidationError(f"{filename} exceeds {limit_mb} MB")
                chunks.append(chunk)
        if total == 0:
            raise DomainValidationError(f"{filename} is empty")
        return b"".join(chunks)
