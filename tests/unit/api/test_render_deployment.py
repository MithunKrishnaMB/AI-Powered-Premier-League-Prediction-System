"""Static contract for the manual zero-cost Render deployment boundary."""

from pathlib import Path

RENDER_ENV_KEYS = (
    "PLP_ENVIRONMENT",
    "PLP_LOG_LEVEL",
    "PLP_PRODUCTION_DATABASE_URL",
    "PLP_DATABASE_CONNECT_TIMEOUT_SECONDS",
    "PLP_DATABASE_POOL_SIZE",
    "PLP_DATABASE_MAX_OVERFLOW",
    "PLP_TRUSTED_CLIENT_IP_HEADER",
)


def _environment_keys(blueprint: str) -> tuple[str, ...]:
    return tuple(
        line.strip().removeprefix("- key: ")
        for line in blueprint.splitlines()
        if line.strip().startswith("- key: ")
    )


def test_render_blueprint_is_one_manual_free_singapore_web_service() -> None:
    blueprint = Path("render.yaml").read_text(encoding="utf-8")

    assert blueprint.count("  - type: web\n") == 1
    assert "runtime: docker" in blueprint
    assert "plan: free" in blueprint
    assert "region: singapore" in blueprint
    assert 'autoDeployTrigger: "off"' in blueprint
    assert "healthCheckPath: /health/live" in blueprint
    assert "healthCheckPath: /health/ready" not in blueprint
    assert "type: cron" not in blueprint
    assert "databases:" not in blueprint
    assert "preDeployCommand:" not in blueprint
    assert "disk:" not in blueprint


def test_render_blueprint_keeps_secrets_runtime_only_and_migrations_local() -> None:
    blueprint = Path("render.yaml").read_text(encoding="utf-8")

    assert _environment_keys(blueprint) == RENDER_ENV_KEYS
    assert "key: PLP_ENVIRONMENT\n        value: production" in blueprint
    assert "key: PLP_PRODUCTION_DATABASE_URL\n        sync: false" in blueprint
    assert "PLP_PRODUCTION_MIGRATION_DATABASE_URL" not in blueprint
    assert "key: PLP_TRUSTED_CLIENT_IP_HEADER" in blueprint
    assert "value: CF-Connecting-IP" in blueprint
    assert "postgresql" not in blueprint.casefold()
    assert "password" not in blueprint.casefold()


def test_render_free_tier_pool_and_secret_exclusion_are_bounded() -> None:
    blueprint = Path("render.yaml").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8").splitlines()
    gitignore = Path(".gitignore").read_text(encoding="utf-8").splitlines()

    assert 'key: PLP_DATABASE_CONNECT_TIMEOUT_SECONDS\n        value: "10"' in (
        blueprint
    )
    assert 'key: PLP_DATABASE_POOL_SIZE\n        value: "2"' in blueprint
    assert 'key: PLP_DATABASE_MAX_OVERFLOW\n        value: "1"' in blueprint
    assert "postgresql+psycopg://" not in blueprint
    assert "postgresql+psycopg://" not in dockerfile
    assert dockerignore[0] == "**"
    assert ".env" in gitignore
    assert ".env.*" in gitignore
