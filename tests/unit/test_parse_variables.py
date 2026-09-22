import pytest

from app.services.batch_service import BatchService
from app.services.errors import DomainValidationError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('["effective_date","governing_law"]', ["effective_date", "governing_law"]),
        ("effective_date,governing_law", ["effective_date", "governing_law"]),
        ("inference", ["inference"]),
        ("inference,test", ["inference", "test"]),
        ("'[\"inference\"]'", ["inference"]),
        ('"effective_date"', ["effective_date"]),
        (" remote node ", ["remote node"]),
    ],
)
def test_parse_variables_accepts_postman_formats(raw: str, expected: list[str]) -> None:
    assert BatchService._parse_variables(raw) == expected


def test_parse_variables_rejects_empty() -> None:
    with pytest.raises(DomainValidationError):
        BatchService._parse_variables("  ")
