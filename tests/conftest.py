from __future__ import annotations

from pathlib import Path

import pytest

from text_to_sql_mcp.config import Settings
from text_to_sql_mcp.db.seed import build_civic_db, init_app_db
from text_to_sql_mcp.introspection import list_schema


@pytest.fixture(scope="session")
def civic_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data") / "civic.db"
    build_civic_db(path, seed=42)
    return path


@pytest.fixture()
def app_db_path(tmp_path: Path) -> Path:
    path = tmp_path / "app.db"
    init_app_db(path)
    return path


@pytest.fixture(scope="session")
def schema(civic_db_path: Path):
    return list_schema(civic_db_path)


@pytest.fixture()
def settings(civic_db_path: Path, app_db_path: Path) -> Settings:
    return Settings(
        civic_db_path=str(civic_db_path),
        app_db_path=str(app_db_path),
        anthropic_api_key=None,
        openai_api_key=None,
    )
