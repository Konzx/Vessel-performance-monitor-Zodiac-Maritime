"""Every test gets a fresh database; never edit the analyst's working copy."""
import pytest
import database


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'reports.sqlite3')
    database.initialize()
    return database.DB_PATH
