"""Typed PostgreSQL engine construction and read-only connectivity checks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Final

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from pl_platform.core.config import DatabaseTarget, Settings, get_settings

MINIMUM_POSTGRESQL_MAJOR: Final = 16


class DatabaseConnectionError(RuntimeError):
    """A configured PostgreSQL target is unavailable or incompatible."""


@dataclass(frozen=True, slots=True)
class DatabaseConnectionInfo:
    """Non-secret facts returned by a successful connection check."""

    target: DatabaseTarget
    database_name: str
    database_user: str
    server_version: str
    server_version_number: int
    timezone: str


def create_database_engine(
    settings: Settings,
    *,
    target: DatabaseTarget,
) -> Engine:
    """Build a lazy SQLAlchemy engine for one explicitly selected target."""

    return create_engine(
        settings.database_url_for(target),
        connect_args={
            "application_name": f"pl-platform-{target}",
            "connect_timeout": settings.database_connect_timeout_seconds,
            "options": "-c timezone=UTC",
        },
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
    )


def check_database_connection(
    engine: Engine,
    *,
    target: DatabaseTarget,
) -> DatabaseConnectionInfo:
    """Verify a target without creating or changing database objects."""

    statement = text(
        "SELECT current_database(), current_user, current_setting('server_version'), "
        "current_setting('server_version_num'), current_setting('TimeZone'), "
        "rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
        "rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user"
    )
    try:
        with engine.connect() as connection:
            (
                database_name,
                database_user,
                version,
                version_number,
                timezone,
                can_login,
                is_superuser,
                can_create_database,
                can_create_role,
                can_replicate,
                can_bypass_rls,
            ) = connection.execute(statement).one()
        numeric_version = int(version_number)
    except (SQLAlchemyError, TypeError, ValueError) as exc:
        msg = f"unable to connect to the configured {target} PostgreSQL database"
        raise DatabaseConnectionError(msg) from exc

    major_version = numeric_version // 10_000
    if major_version < MINIMUM_POSTGRESQL_MAJOR:
        msg = (
            f"PostgreSQL {MINIMUM_POSTGRESQL_MAJOR} or newer is required; "
            f"the {target} target reports {version}"
        )
        raise DatabaseConnectionError(msg)
    if timezone != "UTC":
        msg = f"the {target} PostgreSQL session timezone must be UTC"
        raise DatabaseConnectionError(msg)
    if not can_login or any(
        (
            is_superuser,
            can_create_database,
            can_create_role,
            can_replicate,
            can_bypass_rls,
        )
    ):
        msg = f"the {target} PostgreSQL role must be an unprivileged login role"
        raise DatabaseConnectionError(msg)
    if database_name != engine.url.database or database_user != engine.url.username:
        msg = f"the {target} PostgreSQL connection identity does not match its URL"
        raise DatabaseConnectionError(msg)

    return DatabaseConnectionInfo(
        target=target,
        database_name=str(database_name),
        database_user=str(database_user),
        server_version=str(version),
        server_version_number=numeric_version,
        timezone=str(timezone),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check a configured PostgreSQL target without changing it."
    )
    parser.add_argument(
        "--target",
        choices=("development", "test", "production"),
        default="development",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    target: DatabaseTarget = arguments.target
    engine: Engine | None = None
    try:
        engine = create_database_engine(get_settings(), target=target)
        result = check_database_connection(engine, target=target)
    except (DatabaseConnectionError, ValueError) as exc:
        parser.error(str(exc))
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
