import asyncio
import random
from datetime import date, timedelta

from app.extraction.base import ExtractionRequest


class MockExtractionClient:
    """Returns random plausible values. Does not read document bytes."""

    JURISDICTIONS = (
        "India",
        "Maharashtra",
        "Delhi",
        "Karnataka",
        "England and Wales",
        "Singapore",
    )
    PERIODS = ("15 days", "30 days", "60 days", "90 days")
    PHRASES = (
        "As specified in the agreement",
        "Subject to applicable law",
        "To be determined by the parties",
        "Standard commercial terms apply",
    )

    def __init__(self, delay_ms: int = 50) -> None:
        self.delay_ms = delay_ms

    async def extract(self, request: ExtractionRequest) -> dict[str, str]:
        if self.delay_ms:
            await asyncio.sleep(self.delay_ms / 1000)
        return {variable: self._value_for(variable) for variable in request.variables}

    def _value_for(self, variable: str) -> str:
        key = variable.lower()
        if key.endswith("_date") or "date" in key:
            start = date(2020, 1, 1)
            return (start + timedelta(days=random.randint(0, 2000))).isoformat()
        if any(token in key for token in ("rent", "deposit", "charges", "amount", "fee")):
            return f"INR {random.randint(1_000, 500_000):,}"
        if "law" in key or "jurisdiction" in key:
            return random.choice(self.JURISDICTIONS)
        if "period" in key or "notice" in key:
            return random.choice(self.PERIODS)
        if "clause" in key:
            return "Either party may terminate this agreement by written notice as specified herein."
        return random.choice(self.PHRASES)
