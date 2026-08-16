"""Application configuration, loaded from environment variables / .env."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Central config. All fields have sane local-dev defaults so the app
    works out of the box with no .env file at all (using the rule-based
    LLM fallback and a SQLite database under ./data)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM provider credentials (optional -- see llm/factory.py)
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    # Storage
    civic_db_path: str = "data/civic.db"
    app_db_path: str = "data/app.db"

    # Validator configuration
    large_table_row_threshold: int = 500
    max_result_rows: int = 200

    def civic_db_abspath(self) -> Path:
        p = Path(self.civic_db_path)
        return p if p.is_absolute() else REPO_ROOT / p

    def app_db_abspath(self) -> Path:
        p = Path(self.app_db_path)
        return p if p.is_absolute() else REPO_ROOT / p


def get_settings() -> Settings:
    return Settings()
