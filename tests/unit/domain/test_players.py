"""Reviewed canonical player identity tests."""

from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from pl_platform.domain.players import (
    CanonicalPlayer,
    PlayerAlias,
    PlayerIdentityConflictError,
    PlayerRegistry,
    PlayerRegistryDocument,
    PlayerRegistryValidationError,
    UnknownPlayerAliasError,
)


def _player(ordinal: int, *, alias: str, external_id: str) -> CanonicalPlayer:
    return CanonicalPlayer(
        id=uuid5(NAMESPACE_URL, f"test-player:{ordinal}"),
        slug=f"test-player-{ordinal}",
        display_name=f"Test Player {ordinal}",
        aliases=(
            PlayerAlias(
                source_id="test-source",
                external_name=alias,
                external_id=external_id,
            ),
        ),
    )


def test_player_registry_resolves_only_reviewed_exact_evidence() -> None:
    first = _player(1, alias="Exact Player", external_id="p-1")
    registry = PlayerRegistry(
        PlayerRegistryDocument(schema_version=1, players=(first,))
    )

    assert (
        registry.resolve_provider_player("test-source", "p-1", "Exact Player") == first
    )
    assert (
        registry.resolve_provider_player("test-source", "unknown", " exact  player ")
        == first
    )
    with pytest.raises(UnknownPlayerAliasError, match="reviewed mapping"):
        registry.resolve_provider_player("test-source", "p-2", "Similar Player")


def test_player_registry_rejects_duplicate_and_conflicting_evidence() -> None:
    first = _player(1, alias="First", external_id="p-1")
    second = _player(2, alias="Second", external_id="p-2")
    conflict_registry = PlayerRegistry(
        PlayerRegistryDocument(schema_version=1, players=(first, second))
    )
    with pytest.raises(PlayerIdentityConflictError, match="different players"):
        conflict_registry.resolve_provider_player("test-source", "p-1", "Second")
    duplicate_alias = second.model_copy(
        update={
            "aliases": (
                PlayerAlias(
                    source_id="test-source",
                    external_name="First",
                    external_id="p-3",
                ),
            )
        }
    )
    with pytest.raises(PlayerRegistryValidationError, match="duplicate player alias"):
        PlayerRegistry(
            PlayerRegistryDocument(schema_version=1, players=(first, duplicate_alias))
        )


def test_player_registry_rejects_duplicate_ids_slugs_and_external_ids() -> None:
    first = _player(1, alias="First", external_id="p-1")
    second = _player(2, alias="Second", external_id="p-2")

    with pytest.raises(ValidationError, match="IDs"):
        PlayerRegistryDocument(
            schema_version=1,
            players=(first, second.model_copy(update={"id": first.id})),
        )
    with pytest.raises(ValidationError, match="slugs"):
        PlayerRegistryDocument(
            schema_version=1,
            players=(first, second.model_copy(update={"slug": first.slug})),
        )
    duplicate_id = second.model_copy(
        update={
            "aliases": (
                PlayerAlias(
                    source_id="test-source",
                    external_name="Second",
                    external_id="p-1",
                ),
            )
        }
    )
    with pytest.raises(PlayerRegistryValidationError, match="external ID"):
        PlayerRegistry(
            PlayerRegistryDocument(schema_version=1, players=(first, duplicate_id))
        )
    with pytest.raises(ValidationError, match="trimmed and printable"):
        PlayerAlias(
            source_id="test-source",
            external_name="First",
            external_id=" p-1",
        )
