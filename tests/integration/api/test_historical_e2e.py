"""Transaction-scoped historical artifact to FastAPI release validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from pl_platform.api.application import create_app
from pl_platform.api.queries import PostgresResourceQueryService
from pl_platform.core.config import Settings
from pl_platform.domain.fixtures import Fixture
from pl_platform.domain.seasons import load_season_registry
from pl_platform.domain.teams import load_team_registry
from pl_platform.features.chronology import (
    chronological_fixture_batches,
    fixture_competition_date,
)
from pl_platform.ingestion.manifest import load_manifest
from pl_platform.persistence.database import create_database_engine

SEASON_ID = "2024-2025"
TEAM_REGISTRY_PATH = Path("data/reference/teams.json")
SEASON_REGISTRY_PATH = Path("data/reference/seasons.json")
HISTORICAL_MANIFEST_PATH = Path("data/manifests/football-data.json")
CANONICAL_ROOT = Path("data/interim/canonical/epl") / SEASON_ID
CANONICAL_MANIFEST_PATH = CANONICAL_ROOT / "dataset-manifest.json"
CANONICAL_FIXTURES_PATH = CANONICAL_ROOT / "fixtures.jsonl"
RAW_CAPTURE_PATH = Path("data/raw/football-data/epl") / SEASON_ID / "E0.csv"
REQUEST_HEADERS = {"X-Request-ID": "historical-api-release"}
READ_TABLES = (
    "identity.reference_document",
    "identity.team_registry_member",
    "identity.season_registry_entry",
    "identity.season_membership",
    "ingestion.raw_capture",
    "football.canonical_dataset",
    "football.fixture",
    "football.fixture_revision",
    "prediction.current_model_prediction",
    "simulation.simulation_run",
)


class _SourceManifest(TypedDict):
    file_id: str


class _CanonicalManifest(TypedDict):
    competition_id: str
    dataset_id: str
    dataset_schema_version: int
    fixture_count: int
    fixtures_sha256: str
    season_id: str
    source: _SourceManifest


@dataclass(frozen=True, slots=True)
class _TransactionResourceQueryService(PostgresResourceQueryService):
    """Bind production queries to an outer rollback-only test transaction."""

    connection: Connection

    @contextmanager
    def _connection(self) -> Iterator[Connection]:
        yield self.connection


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _table_counts(engine: Engine) -> tuple[int, ...]:
    with engine.connect() as connection:
        return tuple(
            int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
            for table in READ_TABLES
        )


def _execute_many(
    connection: Connection,
    statement: str,
    rows: Sequence[Mapping[str, object]],
) -> None:
    if rows:
        connection.execute(text(statement), list(rows))


def _stored_object(
    *,
    path: Path,
    media_type: str,
    format_id: str,
    canonicalization_profile: str,
    encoding: str = "utf-8",
) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "sha256": _sha256(payload),
        "byte_count": len(payload),
        "media_type": media_type,
        "encoding": encoding,
        "format_id": format_id,
        "canonicalization_profile": canonicalization_profile,
        "payload": payload,
    }


def _load_fixtures() -> tuple[Fixture, ...]:
    payload = CANONICAL_FIXTURES_PATH.read_text(encoding="utf-8")
    return tuple(
        Fixture.model_validate_json(line) for line in payload.splitlines() if line
    )


def _fixture_revision_row(
    fixture: Fixture,
    *,
    record_ordinal: int,
    dataset_id: str,
    manifest_sha256: str,
    season_registry_sha256: str,
) -> dict[str, object]:
    full_time = fixture.full_time_score
    half_time = fixture.half_time_score
    statistics = fixture.statistics
    home = statistics.home if statistics is not None else None
    away = statistics.away if statistics is not None else None
    return {
        "canonical_dataset_id": dataset_id,
        "canonical_manifest_sha256": manifest_sha256,
        "fixture_id": fixture.id,
        "record_ordinal": record_ordinal,
        "competition_id": fixture.competition_id,
        "season_id": fixture.season_id,
        "season_registry_sha256": season_registry_sha256,
        "home_team_id": fixture.home_team_id,
        "away_team_id": fixture.away_team_id,
        "kickoff_at": fixture.kickoff_at,
        "kickoff_precision": fixture.kickoff_precision.value,
        "status": fixture.status.value,
        "matchweek": fixture.matchweek,
        "referee": fixture.referee,
        "full_time_home_goals": full_time.home if full_time is not None else None,
        "full_time_away_goals": full_time.away if full_time is not None else None,
        "half_time_home_goals": half_time.home if half_time is not None else None,
        "half_time_away_goals": half_time.away if half_time is not None else None,
        "outcome": fixture.outcome.value if fixture.outcome is not None else None,
        "home_shots": home.shots if home is not None else None,
        "away_shots": away.shots if away is not None else None,
        "home_shots_on_target": home.shots_on_target if home is not None else None,
        "away_shots_on_target": away.shots_on_target if away is not None else None,
        "home_fouls": home.fouls if home is not None else None,
        "away_fouls": away.fouls if away is not None else None,
        "home_corners": home.corners if home is not None else None,
        "away_corners": away.corners if away is not None else None,
        "home_yellow_cards": home.yellow_cards if home is not None else None,
        "away_yellow_cards": away.yellow_cards if away is not None else None,
        "home_red_cards": home.red_cards if home is not None else None,
        "away_red_cards": away.red_cards if away is not None else None,
    }


def _seed_historical_projection(connection: Connection) -> tuple[Fixture, ...]:
    teams = load_team_registry(TEAM_REGISTRY_PATH)
    seasons = load_season_registry(SEASON_REGISTRY_PATH, teams)
    season = seasons.get(SEASON_ID)
    historical_manifest = load_manifest(HISTORICAL_MANIFEST_PATH)
    raw_entry = historical_manifest.get_file(f"epl-{SEASON_ID}")
    fixtures = _load_fixtures()
    manifest = cast(
        _CanonicalManifest,
        json.loads(CANONICAL_MANIFEST_PATH.read_text(encoding="utf-8")),
    )
    team_registry_sha256 = _sha256(TEAM_REGISTRY_PATH.read_bytes())
    season_registry_sha256 = _sha256(SEASON_REGISTRY_PATH.read_bytes())
    canonical_manifest_sha256 = _sha256(CANONICAL_MANIFEST_PATH.read_bytes())
    fixtures_sha256 = _sha256(CANONICAL_FIXTURES_PATH.read_bytes())
    historical_manifest_sha256 = _sha256(HISTORICAL_MANIFEST_PATH.read_bytes())
    raw_capture_sha256 = _sha256(RAW_CAPTURE_PATH.read_bytes())

    assert manifest["season_id"] == SEASON_ID
    assert manifest["competition_id"] == season.competition_id
    assert manifest["fixture_count"] == len(fixtures) == 380
    assert manifest["fixtures_sha256"] == fixtures_sha256
    assert raw_entry.sha256 == raw_capture_sha256
    assert all(fixture.season_id == SEASON_ID for fixture in fixtures)

    objects = (
        _stored_object(
            path=TEAM_REGISTRY_PATH,
            media_type="application/json",
            format_id="team-registry-json-v2",
            canonicalization_profile="identity_json_v1",
        ),
        _stored_object(
            path=SEASON_REGISTRY_PATH,
            media_type="application/json",
            format_id="season-registry-json-v1",
            canonicalization_profile="identity_json_v1",
        ),
        _stored_object(
            path=HISTORICAL_MANIFEST_PATH,
            media_type="application/json",
            format_id="historical-data-manifest-json-v1",
            canonicalization_profile="identity_json_v1",
        ),
        _stored_object(
            path=CANONICAL_MANIFEST_PATH,
            media_type="application/json",
            format_id="canonical-dataset-manifest-json-v2",
            canonicalization_profile="canonical_json_v1",
        ),
        _stored_object(
            path=CANONICAL_FIXTURES_PATH,
            media_type="application/x-ndjson",
            format_id="canonical-fixtures-jsonl-v2",
            canonicalization_profile="canonical_jsonl_v1",
        ),
        _stored_object(
            path=RAW_CAPTURE_PATH,
            media_type="text/csv",
            format_id="football-data-csv-v1",
            canonicalization_profile="opaque",
            encoding=raw_entry.encoding,
        ),
    )
    _execute_many(
        connection,
        """
        INSERT INTO lineage.stored_object (
            sha256, byte_count, media_type, encoding, format_id,
            canonicalization_profile, payload
        ) VALUES (
            :sha256, :byte_count, :media_type, :encoding, :format_id,
            :canonicalization_profile, :payload
        ) ON CONFLICT (sha256) DO NOTHING
        """,
        objects,
    )
    _execute_many(
        connection,
        """
        INSERT INTO identity.reference_document (
            document_sha256, document_kind, schema_version
        ) VALUES (:document_sha256, :document_kind, :schema_version)
        ON CONFLICT (document_sha256) DO NOTHING
        """,
        (
            {
                "document_sha256": team_registry_sha256,
                "document_kind": "team_registry",
                "schema_version": teams.schema_version,
            },
            {
                "document_sha256": season_registry_sha256,
                "document_kind": "season_registry",
                "schema_version": seasons.schema_version,
            },
            {
                "document_sha256": historical_manifest_sha256,
                "document_kind": "historical_manifest",
                "schema_version": historical_manifest.schema_version,
            },
        ),
    )
    connection.execute(
        text(
            """
            INSERT INTO identity.source (
                source_id, provider_name, homepage_url, attribution, usage_notice
            ) VALUES (
                :source_id, :provider_name, :homepage_url, :attribution,
                :usage_notice
            ) ON CONFLICT (source_id) DO NOTHING
            """
        ),
        {
            "source_id": historical_manifest.source.id,
            "provider_name": historical_manifest.source.name,
            "homepage_url": historical_manifest.source.homepage_url,
            "attribution": historical_manifest.source.attribution,
            "usage_notice": historical_manifest.source.usage_notice,
        },
    )
    _execute_many(
        connection,
        """
        INSERT INTO identity.source_allowed_host (source_id, ordinal, hostname)
        VALUES (:source_id, :ordinal, :hostname)
        ON CONFLICT (source_id, ordinal) DO NOTHING
        """,
        tuple(
            {
                "source_id": historical_manifest.source.id,
                "ordinal": ordinal,
                "hostname": hostname,
            }
            for ordinal, hostname in enumerate(historical_manifest.source.allowed_hosts)
        ),
    )
    connection.execute(
        text(
            """
            INSERT INTO ingestion.raw_capture (
                source_id, artifact_id, historical_manifest_sha256,
                object_sha256, source_url, destination, captured_at, encoding,
                expected_byte_count, expected_row_count, required_columns,
                immutable
            ) VALUES (
                :source_id, :artifact_id, :historical_manifest_sha256,
                :object_sha256, :source_url, :destination, :captured_at,
                :encoding, :expected_byte_count, :expected_row_count,
                :required_columns, :immutable
            ) ON CONFLICT (source_id, artifact_id) DO NOTHING
            """
        ),
        {
            "source_id": historical_manifest.source.id,
            "artifact_id": raw_entry.id,
            "historical_manifest_sha256": historical_manifest_sha256,
            "object_sha256": raw_capture_sha256,
            "source_url": raw_entry.url,
            "destination": raw_entry.destination,
            "captured_at": raw_entry.captured_at,
            "encoding": raw_entry.encoding,
            "expected_byte_count": raw_entry.expected_bytes,
            "expected_row_count": raw_entry.expected_rows,
            "required_columns": list(raw_entry.required_columns),
            "immutable": raw_entry.immutable,
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO identity.competition (
                competition_id, display_name, country_code, timezone_name
            ) VALUES (
                'eng-premier-league', 'Premier League', 'ENG', 'Europe/London'
            ) ON CONFLICT (competition_id) DO NOTHING
            """
        )
    )
    _execute_many(
        connection,
        "INSERT INTO identity.team (team_id) VALUES (:team_id) "
        "ON CONFLICT (team_id) DO NOTHING",
        tuple({"team_id": team.id} for team in teams.teams),
    )
    _execute_many(
        connection,
        """
        INSERT INTO identity.team_registry_member (
            document_sha256, ordinal, team_id, slug, display_name, country_code
        ) VALUES (
            :document_sha256, :ordinal, :team_id, :slug, :display_name,
            :country_code
        ) ON CONFLICT (document_sha256, ordinal) DO NOTHING
        """,
        tuple(
            {
                "document_sha256": team_registry_sha256,
                "ordinal": ordinal,
                "team_id": team.id,
                "slug": team.slug,
                "display_name": team.name,
                "country_code": team.country_code,
            }
            for ordinal, team in enumerate(teams.teams)
        ),
    )
    connection.execute(
        text(
            """
            INSERT INTO identity.season (competition_id, season_id)
            VALUES (:competition_id, :season_id)
            ON CONFLICT (competition_id, season_id) DO NOTHING
            """
        ),
        {"competition_id": season.competition_id, "season_id": season.id},
    )
    season_ordinal = tuple(item.id for item in seasons.seasons).index(SEASON_ID)
    connection.execute(
        text(
            """
            INSERT INTO identity.season_registry_entry (
                season_registry_sha256, competition_id, season_id, ordinal,
                starts_on, ends_on, completed
            ) VALUES (
                :season_registry_sha256, :competition_id, :season_id, :ordinal,
                :starts_on, :ends_on, :completed
            ) ON CONFLICT (
                season_registry_sha256, competition_id, season_id
            ) DO NOTHING
            """
        ),
        {
            "season_registry_sha256": season_registry_sha256,
            "competition_id": season.competition_id,
            "season_id": season.id,
            "ordinal": season_ordinal,
            "starts_on": season.starts_on,
            "ends_on": season.ends_on,
            "completed": season.completed,
        },
    )
    _execute_many(
        connection,
        """
        INSERT INTO identity.season_membership (
            season_registry_sha256, competition_id, season_id, team_id,
            ordinal, entry_status, previous_competition_id
        ) VALUES (
            :season_registry_sha256, :competition_id, :season_id, :team_id,
            :ordinal, :entry_status, :previous_competition_id
        ) ON CONFLICT (
            season_registry_sha256, competition_id, season_id, team_id
        ) DO NOTHING
        """,
        tuple(
            {
                "season_registry_sha256": season_registry_sha256,
                "competition_id": season.competition_id,
                "season_id": season.id,
                "team_id": membership.team_id,
                "ordinal": ordinal,
                "entry_status": membership.entry_status.value,
                "previous_competition_id": membership.previous_competition_id,
            }
            for ordinal, membership in enumerate(season.memberships)
        ),
    )
    connection.execute(
        text(
            """
            INSERT INTO football.canonical_dataset (
                dataset_id, manifest_sha256, competition_id, season_id,
                raw_source_id, raw_artifact_id, team_registry_sha256,
                season_registry_sha256, fixtures_sha256,
                dataset_schema_version, fixture_count, ordering_contract
            ) VALUES (
                :dataset_id, :manifest_sha256, :competition_id, :season_id,
                :raw_source_id, :raw_artifact_id, :team_registry_sha256,
                :season_registry_sha256, :fixtures_sha256,
                :dataset_schema_version, :fixture_count,
                'kickoff_at_fixture_id'
            ) ON CONFLICT (dataset_id, manifest_sha256) DO NOTHING
            """
        ),
        {
            "dataset_id": manifest["dataset_id"],
            "manifest_sha256": canonical_manifest_sha256,
            "competition_id": manifest["competition_id"],
            "season_id": manifest["season_id"],
            "raw_source_id": "football-data-uk",
            "raw_artifact_id": manifest["source"]["file_id"],
            "team_registry_sha256": team_registry_sha256,
            "season_registry_sha256": season_registry_sha256,
            "fixtures_sha256": fixtures_sha256,
            "dataset_schema_version": manifest["dataset_schema_version"],
            "fixture_count": manifest["fixture_count"],
        },
    )
    _execute_many(
        connection,
        """
        INSERT INTO football.fixture (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) VALUES (
            :fixture_id, :competition_id, :season_id, :home_team_id,
            :away_team_id
        ) ON CONFLICT (fixture_id) DO NOTHING
        """,
        tuple(
            {
                "fixture_id": fixture.id,
                "competition_id": fixture.competition_id,
                "season_id": fixture.season_id,
                "home_team_id": fixture.home_team_id,
                "away_team_id": fixture.away_team_id,
            }
            for fixture in fixtures
        ),
    )
    _execute_many(
        connection,
        """
        INSERT INTO football.fixture_revision (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id,
            record_ordinal, competition_id, season_id, season_registry_sha256,
            home_team_id, away_team_id, kickoff_at, kickoff_precision, status,
            matchweek, referee, full_time_home_goals, full_time_away_goals,
            half_time_home_goals, half_time_away_goals, outcome, home_shots,
            away_shots, home_shots_on_target, away_shots_on_target, home_fouls,
            away_fouls, home_corners, away_corners, home_yellow_cards,
            away_yellow_cards, home_red_cards, away_red_cards
        ) VALUES (
            :canonical_dataset_id, :canonical_manifest_sha256, :fixture_id,
            :record_ordinal, :competition_id, :season_id,
            :season_registry_sha256, :home_team_id, :away_team_id, :kickoff_at,
            :kickoff_precision, :status, :matchweek, :referee,
            :full_time_home_goals, :full_time_away_goals,
            :half_time_home_goals, :half_time_away_goals, :outcome,
            :home_shots, :away_shots, :home_shots_on_target,
            :away_shots_on_target, :home_fouls, :away_fouls, :home_corners,
            :away_corners, :home_yellow_cards, :away_yellow_cards,
            :home_red_cards, :away_red_cards
        ) ON CONFLICT (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id
        ) DO NOTHING
        """,
        tuple(
            _fixture_revision_row(
                fixture,
                record_ordinal=ordinal,
                dataset_id=manifest["dataset_id"],
                manifest_sha256=canonical_manifest_sha256,
                season_registry_sha256=season_registry_sha256,
            )
            for ordinal, fixture in enumerate(fixtures)
        ),
    )
    _execute_many(
        connection,
        """
        INSERT INTO football.fixture_source_reference (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id,
            ordinal, source_id, external_id
        ) VALUES (
            :canonical_dataset_id, :canonical_manifest_sha256, :fixture_id,
            :ordinal, :source_id, :external_id
        ) ON CONFLICT (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id, ordinal
        ) DO NOTHING
        """,
        tuple(
            {
                "canonical_dataset_id": manifest["dataset_id"],
                "canonical_manifest_sha256": canonical_manifest_sha256,
                "fixture_id": fixture.id,
                "ordinal": ordinal,
                "source_id": reference.source_id,
                "external_id": reference.external_id,
            }
            for fixture in fixtures
            for ordinal, reference in enumerate(fixture.source_references)
        ),
    )
    batches = chronological_fixture_batches(fixtures)
    _execute_many(
        connection,
        """
        INSERT INTO football.fixture_batch (
            canonical_dataset_id, canonical_manifest_sha256, batch_ordinal,
            batch_kind, competition_date, exact_kickoff_at
        ) VALUES (
            :canonical_dataset_id, :canonical_manifest_sha256, :batch_ordinal,
            :batch_kind, :competition_date, :exact_kickoff_at
        ) ON CONFLICT (
            canonical_dataset_id, canonical_manifest_sha256, batch_ordinal
        ) DO NOTHING
        """,
        tuple(
            {
                "canonical_dataset_id": manifest["dataset_id"],
                "canonical_manifest_sha256": canonical_manifest_sha256,
                "batch_ordinal": ordinal,
                "batch_kind": (
                    "date_only_date" if batch.is_date_only_batch else "exact_kickoff"
                ),
                "competition_date": fixture_competition_date(batch.fixtures[0]),
                "exact_kickoff_at": (
                    None if batch.is_date_only_batch else batch.feature_cutoff_at
                ),
            }
            for ordinal, batch in enumerate(batches)
        ),
    )
    _execute_many(
        connection,
        """
        INSERT INTO football.fixture_batch_member (
            canonical_dataset_id, canonical_manifest_sha256, batch_ordinal,
            member_ordinal, fixture_id
        ) VALUES (
            :canonical_dataset_id, :canonical_manifest_sha256, :batch_ordinal,
            :member_ordinal, :fixture_id
        ) ON CONFLICT (
            canonical_dataset_id, canonical_manifest_sha256,
            batch_ordinal, member_ordinal
        ) DO NOTHING
        """,
        tuple(
            {
                "canonical_dataset_id": manifest["dataset_id"],
                "canonical_manifest_sha256": canonical_manifest_sha256,
                "batch_ordinal": batch_ordinal,
                "member_ordinal": member_ordinal,
                "fixture_id": fixture.id,
            }
            for batch_ordinal, batch in enumerate(batches)
            for member_ordinal, fixture in enumerate(batch.fixtures)
        ),
    )
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    return fixtures


@pytest.mark.local_release
@pytest.mark.postgresql
def test_historical_artifacts_reach_api_deterministically_without_persistence() -> None:
    settings = Settings(environment="test")
    assert settings.test_database_url is not None, "test PostgreSQL is required"
    engine = create_database_engine(settings, target="test")
    before_counts = _table_counts(engine)
    before_artifacts = _tree_bytes(settings.artifact_root)
    connection = engine.connect()
    transaction = connection.begin()

    try:
        fixtures = _seed_historical_projection(connection)
        expected = sorted(fixtures, key=lambda item: (item.kickoff_at, item.id))
        service = _TransactionResourceQueryService(settings, connection)
        app = create_app(settings=settings, resources=service)

        with TestClient(app) as client:
            teams = client.get(
                f"/api/v1/teams?season_id={SEASON_ID}&limit=100",
                headers=REQUEST_HEADERS,
            )
            season = client.get(f"/api/v1/seasons/{SEASON_ID}", headers=REQUEST_HEADERS)
            fixture_page = client.get(
                f"/api/v1/fixtures?season_id={SEASON_ID}&status=finished"
                "&limit=25&offset=0",
                headers=REQUEST_HEADERS,
            )
            fixture_detail = client.get(
                f"/api/v1/fixtures/{expected[0].id}", headers=REQUEST_HEADERS
            )
            team_fixtures = client.get(
                f"/api/v1/fixtures?season_id={SEASON_ID}"
                f"&team_id={expected[0].home_team_id}&limit=100",
                headers=REQUEST_HEADERS,
            )
            predictions = client.get(
                f"/api/v1/predictions?season_id={SEASON_ID}",
                headers=REQUEST_HEADERS,
            )
            simulations = client.get(
                f"/api/v1/simulations?season_id={SEASON_ID}",
                headers=REQUEST_HEADERS,
            )
            first_bodies = tuple(
                response.content
                for response in (
                    teams,
                    season,
                    fixture_page,
                    fixture_detail,
                    team_fixtures,
                    predictions,
                    simulations,
                )
            )
            repeated_bodies = (
                client.get(
                    f"/api/v1/teams?season_id={SEASON_ID}&limit=100",
                    headers=REQUEST_HEADERS,
                ).content,
                client.get(
                    f"/api/v1/seasons/{SEASON_ID}", headers=REQUEST_HEADERS
                ).content,
                client.get(
                    f"/api/v1/fixtures?season_id={SEASON_ID}&status=finished"
                    "&limit=25&offset=0",
                    headers=REQUEST_HEADERS,
                ).content,
                client.get(
                    f"/api/v1/fixtures/{expected[0].id}",
                    headers=REQUEST_HEADERS,
                ).content,
                client.get(
                    f"/api/v1/fixtures?season_id={SEASON_ID}"
                    f"&team_id={expected[0].home_team_id}&limit=100",
                    headers=REQUEST_HEADERS,
                ).content,
                client.get(
                    f"/api/v1/predictions?season_id={SEASON_ID}",
                    headers=REQUEST_HEADERS,
                ).content,
                client.get(
                    f"/api/v1/simulations?season_id={SEASON_ID}",
                    headers=REQUEST_HEADERS,
                ).content,
            )

        assert all(
            response.status_code == 200
            for response in (
                teams,
                season,
                fixture_page,
                fixture_detail,
                team_fixtures,
                predictions,
                simulations,
            )
        )
        assert teams.json()["page"] == {
            "limit": 100,
            "offset": 0,
            "returned": 20,
            "total": 20,
            "next_offset": None,
            "previous_offset": None,
        }
        assert season.json()["season_id"] == SEASON_ID
        assert season.json()["team_count"] == len(season.json()["teams"]) == 20
        assert fixture_page.json()["page"] == {
            "limit": 25,
            "offset": 0,
            "returned": 25,
            "total": 380,
            "next_offset": 25,
            "previous_offset": None,
        }
        assert fixture_page.json()["items"][0]["fixture_id"] == str(expected[0].id)
        expected_outcome = expected[0].outcome
        assert expected_outcome is not None
        assert fixture_detail.json()["outcome"] == expected_outcome.value
        assert team_fixtures.json()["page"]["total"] == 38
        assert predictions.json()["page"]["total"] == 0
        assert simulations.json()["page"]["total"] == 0
        assert repeated_bodies == first_bodies
    finally:
        transaction.rollback()
        connection.close()
        after_counts = _table_counts(engine)
        engine.dispose()

    assert after_counts == before_counts
    assert _tree_bytes(settings.artifact_root) == before_artifacts
