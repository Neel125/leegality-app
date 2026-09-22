import pytest

from app.config import Settings
from app.services.errors import DomainValidationError
from app.services.zip_archive_service import ZipArchiveService
from tests.helpers import build_zip_bytes, build_zip_with_infos


def service(**overrides: object) -> ZipArchiveService:
    return ZipArchiveService(Settings(**overrides))


def test_extracts_allowed_files_and_skips_junk() -> None:
    payload = build_zip_bytes(
        {
            "contracts/lease.txt": b"lease",
            "__MACOSX/._lease.txt": b"junk",
            ".DS_Store": b"junk",
            "sub/._hidden.txt": b"junk",
        }
    )
    entries = service().extract(payload)
    assert [entry.filename for entry in entries] == ["lease.txt"]
    assert entries[0].data == b"lease"


def test_rejects_too_many_files() -> None:
    payload = build_zip_bytes({f"doc_{i}.txt": b"x" for i in range(3)})
    with pytest.raises(DomainValidationError, match="more than 2"):
        service(max_documents_per_zip=2).extract(payload)


def test_rejects_oversized_file() -> None:
    payload = build_zip_bytes({"big.txt": b"abcdefghijklmnop"})
    with pytest.raises(DomainValidationError, match="exceeds"):
        service(max_document_bytes=10).extract(payload)


def test_rejects_zip_slip() -> None:
    payload = build_zip_with_infos([("../secret.txt", b"nope")])
    with pytest.raises(DomainValidationError, match="Path traversal"):
        service().extract(payload)


def test_rejects_unsupported_type() -> None:
    payload = build_zip_bytes({"malware.exe": b"xx"})
    with pytest.raises(DomainValidationError, match="Unsupported file type"):
        service().extract(payload)


def test_rejects_empty_or_junk_only_zip() -> None:
    payload = build_zip_bytes({".DS_Store": b"x", "__MACOSX/foo.txt": b"y"})
    with pytest.raises(DomainValidationError, match="no extractable documents"):
        service().extract(payload)


def test_rejects_invalid_zip() -> None:
    with pytest.raises(DomainValidationError, match="not a valid ZIP"):
        service().extract(b"this is not a zip")


def test_renames_duplicate_basenames() -> None:
    payload = build_zip_bytes({"a/contract.txt": b"1", "b/contract.txt": b"2"})
    entries = service().extract(payload)
    names = {entry.filename for entry in entries}
    assert names == {"contract.txt", "contract_2.txt"}
