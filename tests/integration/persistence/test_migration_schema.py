"""PostgreSQL migration-shape checks for Steps 5.4 through 5.7."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from pl_platform.core.config import Settings
from pl_platform.persistence.database import create_database_engine

EXPECTED_SCHEMAS = {
    "feature",
    "football",
    "identity",
    "ingestion",
    "lineage",
    "ml",
    "model",
    "persistence",
    "provider_cache",
    "registry",
    "simulation",
}


@pytest.fixture(scope="module")
def migrated_test_engine() -> Iterator[Engine]:
    """Provide the explicitly configured test database at migration head."""

    settings = Settings()
    if settings.test_database_url is None:
        pytest.skip("test PostgreSQL URL is not configured")
    engine = create_database_engine(settings, target="test")
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    if revision != "f0004_step_5_7":
        engine.dispose()
        pytest.skip("test PostgreSQL database is not at the Step 5.7 head")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_migration_head_contains_every_bounded_schema(
    migrated_test_engine: Engine,
) -> None:
    with migrated_test_engine.connect() as connection:
        schemas = set(
            connection.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name = ANY(:names)"
                ),
                {"names": sorted(EXPECTED_SCHEMAS)},
            ).scalars()
        )

    assert schemas == EXPECTED_SCHEMAS


@pytest.mark.postgresql
def test_provenance_foreign_keys_are_restrictive(
    migrated_test_engine: Engine,
) -> None:
    with migrated_test_engine.connect() as connection:
        non_restrictive = (
            connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE contype = 'f' AND connamespace IN ("
                    "SELECT oid FROM pg_namespace WHERE nspname = ANY(:names)) "
                    "AND (confupdtype <> 'r' OR confdeltype <> 'r')"
                ),
                {"names": sorted(EXPECTED_SCHEMAS)},
            )
            .scalars()
            .all()
        )

    assert non_restrictive == []


@pytest.mark.postgresql
def test_all_persistent_tables_have_immutable_guards(
    migrated_test_engine: Engine,
) -> None:
    with migrated_test_engine.connect() as connection:
        missing = (
            connection.execute(
                text(
                    "SELECT n.nspname || '.' || c.relname "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.relkind = 'r' AND n.nspname = ANY(:names) "
                    "AND NOT EXISTS (SELECT 1 FROM pg_trigger t "
                    "WHERE t.tgrelid = c.oid AND t.tgname = 'immutable_guard' "
                    "AND NOT t.tgisinternal) ORDER BY 1"
                ),
                {"names": sorted(EXPECTED_SCHEMAS - {"persistence"})},
            )
            .scalars()
            .all()
        )

    assert missing == []


@pytest.mark.postgresql
def test_sealed_target_and_simulation_constraints_exist(
    migrated_test_engine: Engine,
) -> None:
    expected_constraints = {
        "ck_simulation_run_v1",
        "ck_untouched_test_freeze_v1",
    }
    expected_triggers = {
        "validate_distribution_provenance",
        "validate_simulation_summary",
    }
    with migrated_test_engine.connect() as connection:
        constraints = set(
            connection.execute(
                text("SELECT conname FROM pg_constraint WHERE conname = ANY(:names)"),
                {"names": sorted(expected_constraints)},
            ).scalars()
        )
        triggers = set(
            connection.execute(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE tgname = ANY(:names) AND NOT tgisinternal"
                ),
                {"names": sorted(expected_triggers)},
            ).scalars()
        )

    assert constraints == expected_constraints
    assert triggers == expected_triggers


@pytest.mark.postgresql
def test_database_uuid_contract_matches_an_existing_feature_artifact(
    migrated_test_engine: Engine,
) -> None:
    """Guard the PostgreSQL timestamp/UUID projection with a real row."""

    with migrated_test_engine.connect() as connection:
        actual = connection.execute(
            text(
                "SELECT uuid_generate_v5(uuid_ns_url(), "
                "'pl-platform:feature-row:2|' || :fixture_id || '|' || "
                "persistence.utc_iso8601(CAST(:cutoff AS timestamptz)) || "
                "'|epl-pre-match|2|canonical-fixtures-2024-2025|' || "
                ":fixtures_sha256 || '|' || :context_sha256)"
            ),
            {
                "fixture_id": "c9fe77a3-cef5-5062-86d8-2abc94e2e488",
                "cutoff": "2024-08-16T19:00:00Z",
                "fixtures_sha256": (
                    "449814373608c7cf90851a609c0b60e5b938bd85b4d0b1c591b35a99507999fb"
                ),
                "context_sha256": (
                    "9d7c8b7caf3b98a6127a73247c91925b3e500238489a630fa5033ad2ddbd9a38"
                ),
            },
        ).scalar_one()

    assert str(actual) == "3cdffbcc-f4ac-50c9-b87d-398d4639c24d"
