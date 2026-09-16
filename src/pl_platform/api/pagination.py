"""Reusable deterministic offset-pagination contracts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_PAGE_LIMIT = 50
MAXIMUM_PAGE_LIMIT = 100


class PaginationModel(BaseModel):
    """Strict immutable base for pagination contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PaginationParams(PaginationModel):
    """Validated offset pagination accepted by future collection endpoints."""

    limit: int = Field(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAXIMUM_PAGE_LIMIT)
    offset: int = Field(default=0, ge=0)


class PageMetadata(PaginationModel):
    """Stable pagination metadata derived from a complete result count."""

    limit: int = Field(ge=1, le=MAXIMUM_PAGE_LIMIT)
    offset: int = Field(ge=0)
    returned: int = Field(ge=0)
    total: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    previous_offset: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def values_are_consistent(self) -> Self:
        expected_returned = min(self.limit, max(self.total - self.offset, 0))
        expected_next = (
            self.offset + self.returned
            if self.offset + self.returned < self.total
            else None
        )
        expected_previous = max(0, self.offset - self.limit) if self.offset else None
        if (
            self.returned != expected_returned
            or self.next_offset != expected_next
            or self.previous_offset != expected_previous
        ):
            msg = "pagination metadata is inconsistent"
            raise ValueError(msg)
        return self


class PaginatedResponse[T](PaginationModel):
    """Ordered items plus deterministic offset metadata."""

    items: tuple[T, ...]
    page: PageMetadata

    @model_validator(mode="after")
    def item_count_matches_metadata(self) -> Self:
        if len(self.items) != self.page.returned:
            msg = "item count does not match pagination metadata"
            raise ValueError(msg)
        return self

    @classmethod
    def build(
        cls,
        *,
        items: Sequence[T],
        params: PaginationParams,
        total: int,
    ) -> PaginatedResponse[T]:
        """Build one complete page and reject partial or inconsistent input."""

        returned = len(items)
        next_offset = (
            params.offset + returned if params.offset + returned < total else None
        )
        previous_offset = (
            max(0, params.offset - params.limit) if params.offset else None
        )
        return PaginatedResponse[T](
            items=tuple(items),
            page=PageMetadata(
                limit=params.limit,
                offset=params.offset,
                returned=returned,
                total=total,
                next_offset=next_offset,
                previous_offset=previous_offset,
            ),
        )
