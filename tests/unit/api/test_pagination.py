"""Tests for reusable offset-pagination contracts."""

import pytest
from pydantic import ValidationError

from pl_platform.api.pagination import (
    DEFAULT_PAGE_LIMIT,
    MAXIMUM_PAGE_LIMIT,
    PageMetadata,
    PaginatedResponse,
    PaginationParams,
)


def test_default_and_bounded_pagination_parameters() -> None:
    assert PaginationParams() == PaginationParams(limit=DEFAULT_PAGE_LIMIT, offset=0)
    assert PaginationParams(limit=MAXIMUM_PAGE_LIMIT, offset=10).offset == 10
    with pytest.raises(ValidationError):
        PaginationParams(limit=0)
    with pytest.raises(ValidationError):
        PaginationParams(limit=MAXIMUM_PAGE_LIMIT + 1)
    with pytest.raises(ValidationError):
        PaginationParams(offset=-1)


def test_paginated_response_builds_stable_navigation_offsets() -> None:
    first = PaginatedResponse[int].build(
        items=(1, 2),
        params=PaginationParams(limit=2),
        total=5,
    )
    middle = PaginatedResponse[int].build(
        items=(3, 4),
        params=PaginationParams(limit=2, offset=2),
        total=5,
    )
    last = PaginatedResponse[int].build(
        items=(5,),
        params=PaginationParams(limit=2, offset=4),
        total=5,
    )

    assert first.page.next_offset == 2
    assert first.page.previous_offset is None
    assert middle.page.next_offset == 4
    assert middle.page.previous_offset == 0
    assert last.page.next_offset is None
    assert last.page.previous_offset == 2
    assert last.model_dump(mode="json") == {
        "items": [5],
        "page": {
            "limit": 2,
            "offset": 4,
            "returned": 1,
            "total": 5,
            "next_offset": None,
            "previous_offset": 2,
        },
    }


def test_empty_out_of_range_page_remains_consistent() -> None:
    page = PaginatedResponse[str].build(
        items=(),
        params=PaginationParams(limit=10, offset=30),
        total=20,
    )

    assert page.page.returned == 0
    assert page.page.previous_offset == 20


def test_inconsistent_metadata_and_item_counts_fail_closed() -> None:
    with pytest.raises(ValidationError, match="metadata is inconsistent"):
        PageMetadata(
            limit=2,
            offset=0,
            returned=1,
            total=5,
            next_offset=1,
            previous_offset=None,
        )
    with pytest.raises(ValidationError, match="item count"):
        PaginatedResponse[int](
            items=(1,),
            page=PageMetadata(
                limit=2,
                offset=0,
                returned=2,
                total=2,
                next_offset=None,
                previous_offset=None,
            ),
        )
    with pytest.raises(ValidationError, match="metadata is inconsistent"):
        PaginatedResponse[int].build(
            items=(1,),
            params=PaginationParams(limit=2),
            total=5,
        )
