"""Tests for the secret-free Alembic initialization boundary."""

from pathlib import Path

from alembic.config import Config


def test_alembic_configuration_has_no_embedded_database_url() -> None:
    config = Config("alembic.ini")
    script_location = config.get_main_option("script_location")

    assert script_location is not None
    assert script_location.replace("\\", "/").endswith("/migrations")
    assert config.get_main_option("sqlalchemy.url") is None


def test_step_5_3_has_no_schema_revisions() -> None:
    version_files = {
        path.name
        for path in Path("migrations/versions").iterdir()
        if path.is_file() and path.name != ".gitkeep"
    }

    assert version_files == set()


def test_alembic_files_do_not_embed_local_password() -> None:
    migration_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (Path("alembic.ini"), *Path("migrations").glob("**/*"))
        if path.is_file() and "__pycache__" not in path.parts
    )

    assert "pl2026" not in migration_text
