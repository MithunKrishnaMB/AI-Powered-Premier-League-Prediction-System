"""Transactional verification of the complete local Alembic chain."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text

from pl_platform.core.config import Settings
from pl_platform.persistence.database import (
    check_database_connection,
    create_database_engine,
)

MIGRATION_REVISIONS = (
    "f0001_step_5_4",
    "f0002_step_5_5",
    "f0003_step_5_6",
    "f0004_step_5_7",
    "f0005_step_6_7",
    "f0006_step_6_8",
    "f0007_step_7_4",
    "f0008_step_7_7",
    "f0009_step_7_9",
)
APPLICATION_SCHEMAS = (
    "feature",
    "football",
    "identity",
    "ingestion",
    "lineage",
    "ml",
    "model",
    "persistence",
    "prediction",
    "provider_cache",
    "registry",
    "simulation",
)


def _revision(connection: Connection) -> str | None:
    table = connection.execute(
        text("SELECT to_regclass('public.alembic_version')")
    ).scalar_one()
    if table is None:
        return None
    return connection.execute(
        text("SELECT version_num FROM public.alembic_version")
    ).scalar_one_or_none()


def _schemas(connection: Connection, names: Sequence[str]) -> set[str]:
    return set(
        connection.execute(
            text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name = ANY(:names)"
            ),
            {"names": list(names)},
        ).scalars()
    )


def _engine_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return _revision(connection)


@pytest.mark.local_release
@pytest.mark.postgresql
def test_complete_migration_chain_is_reversible_only_on_the_test_target() -> None:
    settings = Settings()
    assert settings.database_url is not None, "development PostgreSQL is required"
    assert settings.test_database_url is not None, "test PostgreSQL is required"

    development = create_database_engine(settings, target="development")
    test = create_database_engine(settings, target="test")
    try:
        development_info = check_database_connection(
            development,
            target="development",
        )
        test_info = check_database_connection(test, target="test")
        assert development_info.database_name == "pl_platform_dev"
        assert test_info.database_name == "pl_platform_test"
        development_head = _engine_revision(development)
        assert development_head == MIGRATION_REVISIONS[-1]
        assert _engine_revision(test) == MIGRATION_REVISIONS[-1]

        with test.connect() as connection:
            transaction = connection.begin()
            try:
                config = Config("alembic.ini")
                config.attributes["connection"] = connection

                command.downgrade(config, "base")
                assert _revision(connection) is None
                assert _schemas(connection, APPLICATION_SCHEMAS) == set()

                for revision in MIGRATION_REVISIONS:
                    command.upgrade(config, revision)
                    assert _revision(connection) == revision

                assert _schemas(connection, APPLICATION_SCHEMAS) == set(
                    APPLICATION_SCHEMAS
                )
            finally:
                transaction.rollback()

        assert _engine_revision(test) == MIGRATION_REVISIONS[-1]
        assert _engine_revision(development) == development_head
    finally:
        test.dispose()
        development.dispose()
