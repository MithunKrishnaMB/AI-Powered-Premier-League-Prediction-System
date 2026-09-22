"""Static contract for the manual zero-cost Render deployment boundary."""

from pathlib import Path


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

    assert "key: PLP_ENVIRONMENT\n        value: production" in blueprint
    assert "key: PLP_PRODUCTION_DATABASE_URL\n        sync: false" in blueprint
    assert "PLP_PRODUCTION_MIGRATION_DATABASE_URL" not in blueprint
    assert "key: PLP_TRUSTED_CLIENT_IP_HEADER" in blueprint
    assert "value: CF-Connecting-IP" in blueprint
    assert "postgresql" not in blueprint.casefold()
    assert "password" not in blueprint.casefold()
