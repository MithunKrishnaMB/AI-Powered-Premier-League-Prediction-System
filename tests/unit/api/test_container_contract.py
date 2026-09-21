"""Static contract for the production container build context and runtime."""

from __future__ import annotations

from pathlib import Path


def test_dockerfile_pins_the_non_root_single_process_factory_runtime() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.startswith(
        "FROM python:3.14.7-slim-trixie@sha256:"
        "caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2\n"
    )
    assert "PLP_ENVIRONMENT=production" in dockerfile
    assert "PLP_ARTIFACT_ROOT=/runtime/artifacts" in dockerfile
    assert "mkdir --parents /runtime/artifacts/registry" not in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "COPY ." not in dockerfile
    assert "COPY src ./src" in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "pl_platform.api.production_runtime"]' in (
        dockerfile
    )
    assert "/health/live" in dockerfile
    assert "/health/ready" not in dockerfile


def test_docker_build_context_is_an_explicit_source_only_allowlist() -> None:
    patterns = Path(".dockerignore").read_text(encoding="utf-8").splitlines()

    assert patterns == [
        "**",
        "!.dockerignore",
        "!Dockerfile",
        "!README.md",
        "!pyproject.toml",
        "!src/",
        "!src/**",
    ]
