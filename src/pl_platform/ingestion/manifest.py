"""Versioned contracts for reproducible historical-data sources."""

import json
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Source(BaseModel):
    """Identity and security boundary for an upstream data provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier
    name: str = Field(min_length=1)
    homepage_url: str
    allowed_hosts: tuple[str, ...] = Field(min_length=1)
    attribution: str = Field(min_length=1)
    usage_notice: str = Field(min_length=1)

    @field_validator("homepage_url")
    @classmethod
    def homepage_must_use_https(cls, value: str) -> str:
        if urlsplit(value).scheme != "https":
            msg = "source homepage must use HTTPS"
            raise ValueError(msg)
        return value


class HistoricalFile(BaseModel):
    """Expected identity and integrity metadata for one immutable raw file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier
    competition_code: str = Field(min_length=1)
    competition_name: str = Field(min_length=1)
    country: str = Field(min_length=1)
    season_start: int = Field(ge=1992, le=2100)
    season_end: int = Field(ge=1993, le=2101)
    url: str
    destination: str
    sha256: Sha256
    expected_bytes: int = Field(gt=0)
    expected_rows: int = Field(gt=0)
    required_columns: tuple[str, ...] = Field(min_length=1)
    encoding: Literal["cp1252", "utf-8", "utf-8-sig"]
    captured_at: datetime
    immutable: Literal[True]

    @field_validator("url")
    @classmethod
    def url_must_use_https(cls, value: str) -> str:
        if urlsplit(value).scheme != "https":
            msg = "historical file URL must use HTTPS"
            raise ValueError(msg)
        return value

    @field_validator("destination")
    @classmethod
    def destination_must_be_safe(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.suffix.casefold() != ".csv":
            msg = "destination must be a relative CSV path without parent traversal"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def season_must_span_one_year(self) -> Self:
        if self.season_end != self.season_start + 1:
            msg = "season_end must be exactly one year after season_start"
            raise ValueError(msg)
        return self


class HistoricalDataManifest(BaseModel):
    """Top-level source manifest with uniqueness and host guarantees."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    source: Source
    files: tuple[HistoricalFile, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def entries_must_be_unique_and_allowed(self) -> Self:
        entry_ids = [entry.id for entry in self.files]
        destinations = [entry.destination for entry in self.files]
        if len(entry_ids) != len(set(entry_ids)):
            msg = "manifest file IDs must be unique"
            raise ValueError(msg)
        if len(destinations) != len(set(destinations)):
            msg = "manifest destinations must be unique"
            raise ValueError(msg)

        allowed_hosts = {host.casefold() for host in self.source.allowed_hosts}
        for entry in self.files:
            hostname = urlsplit(entry.url).hostname
            if hostname is None or hostname.casefold() not in allowed_hosts:
                msg = f"URL host is not allowed for entry {entry.id}"
                raise ValueError(msg)
        return self

    def get_file(self, entry_id: str) -> HistoricalFile:
        """Return one manifest entry or raise a descriptive lookup error."""

        for entry in self.files:
            if entry.id == entry_id:
                return entry
        msg = f"manifest has no file entry named {entry_id!r}"
        raise KeyError(msg)


def load_manifest(path: Path) -> HistoricalDataManifest:
    """Load and validate a UTF-8 JSON historical-data manifest."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return HistoricalDataManifest.model_validate(payload)
