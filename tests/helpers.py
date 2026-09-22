from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZipInfo


def build_zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def build_zip_with_infos(entries: list[tuple[str, bytes]]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in entries:
            info = ZipInfo(filename=name)
            archive.writestr(info, content)
    return buffer.getvalue()


def write_sample_zip(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        build_zip_bytes(
            {
                "lease_agreement.txt": b"House rent agreement sample.",
                "nda.pdf": b"%PDF-1.4 sample contract",
            }
        )
    )
    return path
