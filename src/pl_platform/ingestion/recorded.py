"""Offline exact-byte replay boundary for current-provider contract tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.ingestion.current import (
    CurrentProviderCapability,
    CurrentProviderRequest,
    ExactProviderResponse,
    PageMetadata,
    ProviderCompatibility,
    ProviderResponseCapture,
    QuotaMetadata,
    Sha256,
    provider_request_identity,
)


class RecordedResponseContractError(ValueError):
    """A recording is unsafe, corrupted or incompatible with its request."""


class RecordedResponseSpec(BaseModel):
    """Checked metadata for one credential-free provider response recording."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    relative_path: str = Field(min_length=1)
    source_id: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_.-]*[a-z0-9])?$")
    capability: CurrentProviderCapability
    request_identity_sha256: Sha256
    retrieved_at: datetime
    provider_generated_at: datetime | None = None
    provider_request_id: str | None = Field(default=None, min_length=1)
    compatibility: ProviderCompatibility
    page: PageMetadata
    quota: QuotaMetadata
    response_sha256: Sha256
    http_status: int = Field(strict=True, ge=100, le=599)
    media_type: str = Field(min_length=1)
    encoding: Literal["utf-8", "utf-8-sig", "cp1252"]

    @model_validator(mode="after")
    def path_must_be_a_safe_relative_posix_path(self) -> Self:
        path = PurePosixPath(self.relative_path)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or "\\" in self.relative_path
        ):
            raise ValueError(
                "recorded response path must be a safe relative POSIX path"
            )
        if (
            self.retrieved_at.tzinfo is None
            or self.retrieved_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("recorded retrieval timestamp must be timezone-aware UTC")
        if self.provider_generated_at is not None:
            if (
                self.provider_generated_at.tzinfo is None
                or self.provider_generated_at.utcoffset() != timedelta(0)
            ):
                raise ValueError(
                    "recorded provider timestamp must be timezone-aware UTC"
                )
            if self.provider_generated_at > self.retrieved_at:
                raise ValueError("recorded provider timestamp cannot follow retrieval")
        if not 200 <= self.http_status <= 299:
            raise ValueError("recorded typed success must use a successful HTTP status")
        return self


class RecordedResponseManifest(BaseModel):
    """Complete canonically ordered offline contract corpus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    recordings: tuple[RecordedResponseSpec, ...]

    @model_validator(mode="after")
    def corpus_must_cover_every_capability_once(self) -> Self:
        actual = tuple(record.capability for record in self.recordings)
        expected = tuple(CurrentProviderCapability)
        if actual != expected:
            raise ValueError(
                "recorded corpus must cover every capability in canonical order"
            )
        paths = tuple(record.relative_path for record in self.recordings)
        if len(paths) != len(set(paths)):
            raise ValueError("recorded corpus paths must be unique")
        return self


def load_recorded_manifest(path: Path) -> RecordedResponseManifest:
    """Load a strict UTF-8 JSON manifest without tolerating unknown fields."""

    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
        return RecordedResponseManifest.model_validate(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RecordedResponseContractError(
            "recorded response manifest failed closed validation"
        ) from exc


def replay_recorded_response(
    *,
    root: Path,
    request: CurrentProviderRequest,
    spec: RecordedResponseSpec,
) -> ProviderResponseCapture:
    """Replay one checked recording without network access or response mutation."""

    identity = provider_request_identity(request)
    if request.capability is not spec.capability:
        raise RecordedResponseContractError(
            "recorded capability does not match the typed request"
        )
    if request.scope.source_id != spec.source_id:
        raise RecordedResponseContractError(
            "recorded source does not match the typed request"
        )
    if request.compatibility != spec.compatibility:
        raise RecordedResponseContractError(
            "recorded compatibility does not match the typed request"
        )
    if identity.sha256 != spec.request_identity_sha256:
        raise RecordedResponseContractError(
            "recorded request identity does not match the typed request"
        )
    resolved_root = root.resolve()
    response_path = resolved_root.joinpath(*PurePosixPath(spec.relative_path).parts)
    try:
        resolved_path = response_path.resolve(strict=True)
        resolved_path.relative_to(resolved_root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise RecordedResponseContractError(
            "recorded response is missing or outside its declared root"
        ) from exc
    try:
        body = resolved_path.read_bytes()
        response = ExactProviderResponse(
            body=body,
            sha256=spec.response_sha256,
            http_status=spec.http_status,
            media_type=spec.media_type,
            encoding=spec.encoding,
        )
        return ProviderResponseCapture(
            source_id=spec.source_id,
            capability=spec.capability,
            request_identity=identity,
            retrieved_at=spec.retrieved_at,
            provider_generated_at=spec.provider_generated_at,
            provider_request_id=spec.provider_request_id,
            compatibility=spec.compatibility,
            page=spec.page,
            quota=spec.quota,
            response=response,
        )
    except (OSError, ValueError) as exc:
        raise RecordedResponseContractError(
            "recorded response bytes or metadata failed closed validation"
        ) from exc
