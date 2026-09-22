from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    storage_dir: str = "./storage"
    extractor: str = "mock"
    extract_delay_ms: int = 50
    worker_concurrency: int = 10
    worker_poll_interval_ms: int = 200
    max_documents_per_zip: int = 1000
    max_document_bytes: int = 15 * 1024 * 1024
    allowed_extensions: tuple[str, ...] = (".pdf", ".docx", ".doc", ".txt", ".rtf", ".md")


@lru_cache
def get_settings() -> Settings:
    return Settings()
