"""Secret-free Alembic environment for explicit local database targets."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.pool import NullPool

from pl_platform.core.config import (
    DatabaseConfigurationError,
    DatabaseTarget,
    Settings,
    get_settings,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Step 5.3 intentionally has no ORM metadata or schema revision. Tables begin
# in Step 5.4, after which their metadata can be added here.
target_metadata = None


def _database_target(settings: Settings) -> DatabaseTarget:
    if settings.environment == "development":
        return "development"
    if settings.environment == "test":
        return "test"
    return "production"


def _database_url(settings: Settings) -> str:
    target = _database_target(settings)
    if target == "production":
        return settings.production_migration_url()
    return settings.database_url_for(target)


def _configure_context(*, connection: Connection | None, url: str | None) -> None:
    if connection is not None:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_schemas=True,
            transaction_per_migration=True,
        )
        return
    if url is None:
        msg = "offline Alembic configuration requires a database URL"
        raise DatabaseConfigurationError(msg)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
        transaction_per_migration=True,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )


def run_migrations_offline() -> None:
    """Render migrations without opening a database connection."""

    _configure_context(connection=None, url=_database_url(get_settings()))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against exactly one explicitly selected target."""

    settings = get_settings()
    supplied_connection: object = config.attributes.get("connection")
    if isinstance(supplied_connection, Connection):
        _configure_context(connection=supplied_connection, url=None)
        with context.begin_transaction():
            context.run_migrations()
        return
    if supplied_connection is not None:
        msg = "Alembic connection attribute must be a SQLAlchemy Connection"
        raise DatabaseConfigurationError(msg)

    engine: Engine = create_engine(
        _database_url(settings),
        poolclass=NullPool,
        connect_args={
            "application_name": "pl-platform-alembic",
            "connect_timeout": settings.database_connect_timeout_seconds,
            "options": "-c timezone=UTC",
        },
    )
    try:
        with engine.connect() as connection:
            _configure_context(connection=connection, url=None)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
