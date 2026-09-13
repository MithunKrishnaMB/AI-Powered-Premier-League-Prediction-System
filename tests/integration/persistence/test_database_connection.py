"""Read-only checks against explicitly separate PostgreSQL targets."""

import pytest

from pl_platform.core.config import DatabaseTarget, Settings
from pl_platform.persistence.database import (
    check_database_connection,
    create_database_engine,
)


@pytest.mark.postgresql
@pytest.mark.parametrize(
    ("target", "expected_database"),
    (
        ("development", "pl_platform_dev"),
        ("test", "pl_platform_test"),
    ),
)
def test_local_postgresql_target_is_isolated_and_unprivileged(
    target: DatabaseTarget,
    expected_database: str,
) -> None:
    settings = Settings()
    configured_url = (
        settings.test_database_url if target == "test" else settings.database_url
    )
    if configured_url is None:
        pytest.skip(f"{target} PostgreSQL URL is not configured")

    engine = create_database_engine(settings, target=target)
    try:
        result = check_database_connection(engine, target=target)
    finally:
        engine.dispose()

    assert result.database_name == expected_database
    assert result.database_user == "pl_app"
    assert result.server_version_number >= 160000
    assert result.timezone == "UTC"
