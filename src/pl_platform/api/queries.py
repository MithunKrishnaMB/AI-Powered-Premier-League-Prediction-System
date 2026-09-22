"""Lazy, read-only PostgreSQL queries for version-one API resources."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from pl_platform.api.errors import ApiError
from pl_platform.api.pagination import PaginatedResponse, PaginationParams
from pl_platform.api.resources import (
    EvaluationMetric,
    Fixture,
    FixtureStatus,
    ModelPerformance,
    ModelPerformanceDetail,
    PositionProbability,
    PredictedTable,
    PredictedTableRow,
    Prediction,
    Season,
    SeasonDetail,
    SeasonTeam,
    Simulation,
    StandingRow,
    Standings,
    Team,
)
from pl_platform.core.config import DatabaseConfigurationError, DatabaseTarget, Settings
from pl_platform.persistence.database import create_database_engine
from pl_platform.persistence.repositories import MIGRATION_HEAD

SEALED_TEST_SEASON = "2025-2026"
PREMIER_LEAGUE = "eng-premier-league"

_TEAM_CTE = """
ranked_team AS (
    SELECT m.team_id, m.slug, m.display_name, m.country_code,
           m.document_sha256 AS registry_sha256,
           row_number() OVER (
               PARTITION BY m.team_id
               ORDER BY d.schema_version DESC, m.document_sha256 DESC
           ) AS registry_rank
    FROM identity.team_registry_member AS m
    JOIN identity.reference_document AS d
      ON d.document_sha256 = m.document_sha256
    WHERE d.document_kind = 'team_registry'
),
current_team AS (
    SELECT team_id, slug, display_name, country_code, registry_sha256
    FROM ranked_team
    WHERE registry_rank = 1
)
"""

_SEASON_CTE = """
ranked_season AS (
    SELECT e.competition_id, e.season_id, e.starts_on, e.ends_on, e.completed,
           e.season_registry_sha256 AS registry_sha256,
           row_number() OVER (
               PARTITION BY e.competition_id, e.season_id
               ORDER BY d.schema_version DESC, e.season_registry_sha256 DESC
           ) AS registry_rank
    FROM identity.season_registry_entry AS e
    JOIN identity.reference_document AS d
      ON d.document_sha256 = e.season_registry_sha256
    WHERE d.document_kind = 'season_registry'
),
current_season AS (
    SELECT competition_id, season_id, starts_on, ends_on, completed,
           registry_sha256
    FROM ranked_season
    WHERE registry_rank = 1
)
"""

_FIXTURE_CTE = """
current_revision_ranked AS (
    SELECT r.fixture_id, r.kickoff_at, r.kickoff_precision, r.status,
           r.matchweek,
           row_number() OVER (
               PARTITION BY r.fixture_id
               ORDER BY o.retrieved_at DESC NULLS LAST, r.identity_sha256 DESC
           ) AS revision_rank
    FROM football.current_fixture_revision AS r
    LEFT JOIN football.current_fixture_observation AS o
      ON o.revision_id = r.revision_id
),
current_revision AS (
    SELECT fixture_id, kickoff_at, kickoff_precision, status, matchweek
    FROM current_revision_ranked
    WHERE revision_rank = 1
),
historical_revision_ranked AS (
    SELECT r.fixture_id, r.kickoff_at, r.kickoff_precision, r.status,
           r.matchweek, r.full_time_home_goals, r.full_time_away_goals,
           r.outcome,
           row_number() OVER (
               PARTITION BY r.fixture_id
               ORDER BY d.dataset_schema_version DESC,
                        r.canonical_manifest_sha256 DESC
           ) AS revision_rank
    FROM football.fixture_revision AS r
    JOIN football.canonical_dataset AS d
      ON d.dataset_id = r.canonical_dataset_id
     AND d.manifest_sha256 = r.canonical_manifest_sha256
),
historical_revision AS (
    SELECT fixture_id, kickoff_at, kickoff_precision, status, matchweek,
           full_time_home_goals, full_time_away_goals, outcome
    FROM historical_revision_ranked
    WHERE revision_rank = 1
),
fixture_projection AS (
    SELECT f.fixture_id, f.competition_id, f.season_id, f.home_team_id,
           f.away_team_id,
           coalesce(c.kickoff_at, h.kickoff_at) AS kickoff_at,
           coalesce(c.kickoff_precision, h.kickoff_precision)
               AS kickoff_precision,
           CASE WHEN result.result_id IS NOT NULL THEN 'finished'
                ELSE coalesce(c.status, h.status) END AS status,
           coalesce(c.matchweek, h.matchweek) AS matchweek,
           coalesce(result.full_time_home_goals, h.full_time_home_goals)
               AS full_time_home_goals,
           coalesce(result.full_time_away_goals, h.full_time_away_goals)
               AS full_time_away_goals,
           coalesce(result.outcome, h.outcome) AS outcome
    FROM football.fixture AS f
    LEFT JOIN current_revision AS c ON c.fixture_id = f.fixture_id
    LEFT JOIN historical_revision AS h ON h.fixture_id = f.fixture_id
    LEFT JOIN football.current_completed_result AS result
      ON result.fixture_id = f.fixture_id
)
"""

_LATEST_REGISTRY_EVENT_CTE = """
latest_registry_event AS (
    SELECT e.entry_id, e.to_state,
           row_number() OVER (
               PARTITION BY e.entry_id
               ORDER BY e.sequence DESC, e.event_sha256 DESC
           ) AS event_rank
    FROM registry.registry_event AS e
)
"""


class ResourceQueryService(Protocol):
    """Typed read boundary injected into the HTTP router."""

    def list_teams(
        self, *, season_id: str | None, pagination: PaginationParams
    ) -> PaginatedResponse[Team]: ...

    def get_team(self, team_id: UUID) -> Team: ...

    def list_seasons(
        self, *, pagination: PaginationParams
    ) -> PaginatedResponse[Season]: ...

    def get_season(self, season_id: str) -> SeasonDetail: ...

    def list_fixtures(
        self,
        *,
        season_id: str | None,
        team_id: UUID | None,
        fixture_status: FixtureStatus | None,
        pagination: PaginationParams,
    ) -> PaginatedResponse[Fixture]: ...

    def get_fixture(self, fixture_id: UUID) -> Fixture: ...

    def get_standings(self, season_id: str) -> Standings: ...

    def list_predictions(
        self,
        *,
        season_id: str | None,
        team_id: UUID | None,
        pagination: PaginationParams,
    ) -> PaginatedResponse[Prediction]: ...

    def get_prediction(self, prediction_id: UUID) -> Prediction: ...

    def list_simulations(
        self, *, season_id: str | None, pagination: PaginationParams
    ) -> PaginatedResponse[Simulation]: ...

    def get_simulation(self, simulation_id: UUID) -> Simulation: ...

    def get_predicted_table(self, simulation_id: UUID) -> PredictedTable: ...

    def list_model_performance(
        self, *, pagination: PaginationParams
    ) -> PaginatedResponse[ModelPerformance]: ...

    def get_model_performance(self, model_id: UUID) -> ModelPerformanceDetail: ...


def _not_found(code: str, message: str) -> ApiError:
    return ApiError(status_code=404, code=code, message=message)


def _schema_incompatible() -> ApiError:
    return ApiError(
        status_code=503,
        code="database_schema_incompatible",
        message="The database schema is incompatible with this API.",
    )


def _validated[T: BaseModel](model: type[T], row: object) -> T:
    try:
        return model.model_validate(row)
    except ValidationError as exc:
        raise _schema_incompatible() from exc


def _page[T: BaseModel](
    connection: Connection,
    *,
    count_sql: str,
    select_sql: str,
    values: Mapping[str, object],
    pagination: PaginationParams,
    model: type[T],
) -> PaginatedResponse[T]:
    total = connection.execute(text(count_sql), values).scalar_one()
    if not isinstance(total, int):
        raise _schema_incompatible()
    page_values = dict(values)
    page_values.update(limit=pagination.limit, offset=pagination.offset)
    rows = connection.execute(text(select_sql), page_values).mappings().all()
    items = tuple(_validated(model, row) for row in rows)
    return PaginatedResponse[T].build(
        items=items,
        params=pagination,
        total=total,
    )


@dataclass(frozen=True, slots=True)
class PostgresResourceQueryService:
    """Execute isolated lazy reads against the configured environment target."""

    settings: Settings

    def _target(self) -> DatabaseTarget:
        if (
            self.settings.environment == "production"
            and self.settings.production_database_url is None
        ):
            raise ApiError(
                status_code=503,
                code="database_not_configured",
                message="The production database is not configured.",
            )
        if self.settings.environment == "production":
            return "production"
        return "test" if self.settings.environment == "test" else "development"

    @contextmanager
    def _connection(self) -> Iterator[Connection]:
        engine: Engine | None = None
        try:
            engine = create_database_engine(self.settings, target=self._target())
            with engine.connect() as connection, connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
                if revision != MIGRATION_HEAD:
                    raise _schema_incompatible()
                yield connection
        except ApiError:
            raise
        except DatabaseConfigurationError as exc:
            raise ApiError(
                status_code=503,
                code="database_not_configured",
                message="The database is not configured.",
            ) from exc
        except (SQLAlchemyError, TypeError, ValueError) as exc:
            raise ApiError(
                status_code=503,
                code="database_unavailable",
                message="The database is unavailable.",
            ) from exc
        finally:
            if engine is not None:
                engine.dispose()

    def list_teams(
        self, *, season_id: str | None, pagination: PaginationParams
    ) -> PaginatedResponse[Team]:
        where = ""
        values: dict[str, object] = {}
        ctes = _TEAM_CTE
        if season_id is not None:
            ctes += ",\n" + _SEASON_CTE
            where = """
WHERE EXISTS (
    SELECT 1
    FROM current_season AS s
    JOIN identity.season_membership AS membership
      ON membership.season_registry_sha256 = s.registry_sha256
     AND membership.competition_id = s.competition_id
     AND membership.season_id = s.season_id
    WHERE s.competition_id = :competition_id
      AND s.season_id = :season_id
      AND membership.team_id = team.team_id
)
"""
            values = {"competition_id": PREMIER_LEAGUE, "season_id": season_id}
        base = f"WITH {ctes} SELECT * FROM current_team AS team {where}"
        with self._connection() as connection:
            return _page(
                connection,
                count_sql=f"SELECT count(*) FROM ({base}) AS counted",
                select_sql=(
                    f"{base} ORDER BY display_name, team_id LIMIT :limit OFFSET :offset"
                ),
                values=values,
                pagination=pagination,
                model=Team,
            )

    def get_team(self, team_id: UUID) -> Team:
        query = f"""
WITH {_TEAM_CTE}
SELECT * FROM current_team WHERE team_id = :team_id
"""
        with self._connection() as connection:
            row = (
                connection.execute(text(query), {"team_id": team_id})
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise _not_found("team_not_found", "Team not found.")
        return _validated(Team, row)

    def list_seasons(
        self, *, pagination: PaginationParams
    ) -> PaginatedResponse[Season]:
        base = f"""
WITH {_SEASON_CTE}
SELECT s.competition_id, s.season_id, s.starts_on, s.ends_on, s.completed,
       s.registry_sha256, count(m.team_id)::integer AS team_count
FROM current_season AS s
LEFT JOIN identity.season_membership AS m
  ON m.season_registry_sha256 = s.registry_sha256
 AND m.competition_id = s.competition_id AND m.season_id = s.season_id
WHERE s.competition_id = :competition_id
GROUP BY s.competition_id, s.season_id, s.starts_on, s.ends_on, s.completed,
         s.registry_sha256
"""
        values = {"competition_id": PREMIER_LEAGUE}
        with self._connection() as connection:
            return _page(
                connection,
                count_sql=f"SELECT count(*) FROM ({base}) AS counted",
                select_sql=(
                    f"{base} ORDER BY starts_on DESC, season_id DESC "
                    "LIMIT :limit OFFSET :offset"
                ),
                values=values,
                pagination=pagination,
                model=Season,
            )

    def get_season(self, season_id: str) -> SeasonDetail:
        season_query = f"""
WITH {_SEASON_CTE}
SELECT s.competition_id, s.season_id, s.starts_on, s.ends_on, s.completed,
       s.registry_sha256, count(m.team_id)::integer AS team_count
FROM current_season AS s
LEFT JOIN identity.season_membership AS m
  ON m.season_registry_sha256 = s.registry_sha256
 AND m.competition_id = s.competition_id AND m.season_id = s.season_id
WHERE s.competition_id = :competition_id AND s.season_id = :season_id
GROUP BY s.competition_id, s.season_id, s.starts_on, s.ends_on, s.completed,
         s.registry_sha256
"""
        membership_query = f"""
WITH {_TEAM_CTE},
{_SEASON_CTE}
SELECT m.ordinal, m.entry_status, m.previous_competition_id,
       t.team_id, t.slug, t.display_name, t.country_code, t.registry_sha256
FROM current_season AS s
JOIN identity.season_membership AS m
  ON m.season_registry_sha256 = s.registry_sha256
 AND m.competition_id = s.competition_id AND m.season_id = s.season_id
JOIN current_team AS t ON t.team_id = m.team_id
WHERE s.competition_id = :competition_id AND s.season_id = :season_id
ORDER BY m.ordinal, t.team_id
"""
        values = {"competition_id": PREMIER_LEAGUE, "season_id": season_id}
        with self._connection() as connection:
            season_row = (
                connection.execute(text(season_query), values).mappings().one_or_none()
            )
            membership_rows = (
                connection.execute(text(membership_query), values).mappings().all()
                if season_row is not None
                else ()
            )
        if season_row is None:
            raise _not_found("season_not_found", "Season not found.")
        season = _validated(Season, season_row)
        teams = tuple(self._season_team(row) for row in membership_rows)
        return SeasonDetail(**season.model_dump(), teams=teams)

    @staticmethod
    def _season_team(row: RowMapping) -> SeasonTeam:
        team = _validated(
            Team,
            {
                key: row[key]
                for key in (
                    "team_id",
                    "slug",
                    "display_name",
                    "country_code",
                    "registry_sha256",
                )
            },
        )
        return _validated(
            SeasonTeam,
            {
                "ordinal": row["ordinal"],
                "entry_status": row["entry_status"],
                "previous_competition_id": row["previous_competition_id"],
                "team": team,
            },
        )

    def list_fixtures(
        self,
        *,
        season_id: str | None,
        team_id: UUID | None,
        fixture_status: FixtureStatus | None,
        pagination: PaginationParams,
    ) -> PaginatedResponse[Fixture]:
        clauses = ["competition_id = :competition_id"]
        values: dict[str, object] = {"competition_id": PREMIER_LEAGUE}
        if season_id is not None:
            clauses.append("season_id = :season_id")
            values["season_id"] = season_id
        if team_id is not None:
            clauses.append("(home_team_id = :team_id OR away_team_id = :team_id)")
            values["team_id"] = team_id
        if fixture_status is not None:
            clauses.append("status = :fixture_status")
            values["fixture_status"] = fixture_status.value
        where = " AND ".join(clauses)
        base = f"WITH {_FIXTURE_CTE} SELECT * FROM fixture_projection WHERE {where}"
        with self._connection() as connection:
            return _page(
                connection,
                count_sql=f"SELECT count(*) FROM ({base}) AS counted",
                select_sql=(
                    f"{base} ORDER BY kickoff_at NULLS LAST, fixture_id "
                    "LIMIT :limit OFFSET :offset"
                ),
                values=values,
                pagination=pagination,
                model=Fixture,
            )

    def get_fixture(self, fixture_id: UUID) -> Fixture:
        query = f"""
WITH {_FIXTURE_CTE}
SELECT * FROM fixture_projection WHERE fixture_id = :fixture_id
"""
        with self._connection() as connection:
            row = (
                connection.execute(text(query), {"fixture_id": fixture_id})
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise _not_found("fixture_not_found", "Fixture not found.")
        return _validated(Fixture, row)

    def get_standings(self, season_id: str) -> Standings:
        snapshot_query = """
SELECT snapshot_id, competition_id, season_id, retrieved_at
FROM football.current_standing_snapshot
WHERE competition_id = :competition_id AND season_id = :season_id
ORDER BY retrieved_at DESC, identity_sha256 DESC
LIMIT 1
"""
        rows_query = f"""
WITH {_TEAM_CTE}
SELECT r.position, r.played, r.won, r.drawn, r.lost, r.goals_for,
       r.goals_against, r.goal_difference, r.points, r.points_adjustment,
       t.team_id, t.slug, t.display_name, t.country_code, t.registry_sha256
FROM football.current_standing_row AS r
JOIN current_team AS t ON t.team_id = r.team_id
WHERE r.snapshot_id = :snapshot_id
ORDER BY r.position, r.team_id
"""
        values = {"competition_id": PREMIER_LEAGUE, "season_id": season_id}
        with self._connection() as connection:
            snapshot = (
                connection.execute(text(snapshot_query), values)
                .mappings()
                .one_or_none()
            )
            rows = (
                connection.execute(
                    text(rows_query), {"snapshot_id": snapshot["snapshot_id"]}
                )
                .mappings()
                .all()
                if snapshot is not None
                else ()
            )
        if snapshot is None:
            raise _not_found("standings_not_found", "Standings not found.")
        standing_rows = tuple(self._standing_row(row) for row in rows)
        return _validated(Standings, {**dict(snapshot), "rows": standing_rows})

    @staticmethod
    def _standing_row(row: RowMapping) -> StandingRow:
        team = _validated(
            Team,
            {key: row[key] for key in Team.model_fields},
        )
        values = {key: row[key] for key in StandingRow.model_fields if key != "team"}
        return _validated(StandingRow, {**values, "team": team})

    def list_predictions(
        self,
        *,
        season_id: str | None,
        team_id: UUID | None,
        pagination: PaginationParams,
    ) -> PaginatedResponse[Prediction]:
        clauses = ["competition_id = :competition_id", "season_id <> :sealed"]
        values: dict[str, object] = {
            "competition_id": PREMIER_LEAGUE,
            "sealed": SEALED_TEST_SEASON,
        }
        if season_id is not None:
            clauses.append("season_id = :season_id")
            values["season_id"] = season_id
        if team_id is not None:
            clauses.append("(home_team_id = :team_id OR away_team_id = :team_id)")
            values["team_id"] = team_id
        where = " AND ".join(clauses)
        columns = ", ".join(Prediction.model_fields)
        base = (
            f"SELECT {columns} FROM prediction.current_model_prediction WHERE {where}"
        )
        with self._connection() as connection:
            return _page(
                connection,
                count_sql=f"SELECT count(*) FROM ({base}) AS counted",
                select_sql=(
                    f"{base} ORDER BY kickoff_at, prediction_id "
                    "LIMIT :limit OFFSET :offset"
                ),
                values=values,
                pagination=pagination,
                model=Prediction,
            )

    def get_prediction(self, prediction_id: UUID) -> Prediction:
        columns = ", ".join(Prediction.model_fields)
        query = (
            f"SELECT {columns} FROM prediction.current_model_prediction "
            "WHERE prediction_id = :prediction_id AND season_id <> :sealed"
        )
        values = {"prediction_id": prediction_id, "sealed": SEALED_TEST_SEASON}
        with self._connection() as connection:
            row = connection.execute(text(query), values).mappings().one_or_none()
        if row is None:
            raise _not_found("prediction_not_found", "Prediction not found.")
        return _validated(Prediction, row)

    @staticmethod
    def _simulation_select() -> str:
        return """
SELECT run.simulation_id, summary.summary_id, input.competition_id,
       summary.season_id, run.algorithm_version, run.simulation_seed,
       run.simulation_count
FROM simulation.simulation_run AS run
JOIN simulation.simulation_input AS input ON input.input_sha256 = run.input_sha256
JOIN simulation.simulation_summary AS summary
  ON summary.simulation_id = run.simulation_id
"""

    def list_simulations(
        self, *, season_id: str | None, pagination: PaginationParams
    ) -> PaginatedResponse[Simulation]:
        clauses = [
            "input.competition_id = :competition_id",
            "summary.season_id <> :sealed",
        ]
        values: dict[str, object] = {
            "competition_id": PREMIER_LEAGUE,
            "sealed": SEALED_TEST_SEASON,
        }
        if season_id is not None:
            clauses.append("summary.season_id = :season_id")
            values["season_id"] = season_id
        base = self._simulation_select() + " WHERE " + " AND ".join(clauses)
        with self._connection() as connection:
            return _page(
                connection,
                count_sql=f"SELECT count(*) FROM ({base}) AS counted",
                select_sql=(
                    f"{base} ORDER BY summary.season_id DESC, run.simulation_id "
                    "LIMIT :limit OFFSET :offset"
                ),
                values=values,
                pagination=pagination,
                model=Simulation,
            )

    def get_simulation(self, simulation_id: UUID) -> Simulation:
        query = (
            self._simulation_select()
            + """
WHERE run.simulation_id = :simulation_id AND summary.season_id <> :sealed
"""
        )
        values = {"simulation_id": simulation_id, "sealed": SEALED_TEST_SEASON}
        with self._connection() as connection:
            row = connection.execute(text(query), values).mappings().one_or_none()
        if row is None:
            raise _not_found("simulation_not_found", "Simulation not found.")
        return _validated(Simulation, row)

    def get_predicted_table(self, simulation_id: UUID) -> PredictedTable:
        simulation_query = (
            self._simulation_select()
            + """
WHERE run.simulation_id = :simulation_id AND summary.season_id <> :sealed
"""
        )
        team_query = f"""
WITH {_TEAM_CTE}
SELECT summary.team_id, summary.expected_points, summary.expected_goals_for,
       summary.expected_goals_against, summary.expected_goal_difference,
       summary.champion_probability, summary.top_four_probability,
       summary.top_six_probability, summary.relegation_probability,
       t.slug, t.display_name, t.country_code, t.registry_sha256
FROM simulation.team_summary AS summary
JOIN simulation.simulation_summary AS owner ON owner.summary_id = summary.summary_id
JOIN current_team AS t ON t.team_id = summary.team_id
WHERE owner.simulation_id = :simulation_id AND owner.season_id <> :sealed
ORDER BY summary.expected_points DESC,
         summary.expected_goal_difference DESC,
         summary.expected_goals_for DESC, summary.team_id
"""
        probability_query = """
SELECT probability.team_id, probability.position, probability.probability
FROM simulation.position_probability AS probability
JOIN simulation.simulation_summary AS owner
  ON owner.summary_id = probability.summary_id
WHERE owner.simulation_id = :simulation_id AND owner.season_id <> :sealed
ORDER BY probability.team_id, probability.position
"""
        values = {"simulation_id": simulation_id, "sealed": SEALED_TEST_SEASON}
        with self._connection() as connection:
            simulation_row = (
                connection.execute(text(simulation_query), values)
                .mappings()
                .one_or_none()
            )
            team_rows = (
                connection.execute(text(team_query), values).mappings().all()
                if simulation_row is not None
                else ()
            )
            probability_rows = (
                connection.execute(text(probability_query), values).mappings().all()
                if simulation_row is not None
                else ()
            )
        if simulation_row is None:
            raise _not_found("simulation_not_found", "Simulation not found.")
        simulation = _validated(Simulation, simulation_row)
        probabilities = self._probabilities_by_team(probability_rows)
        rows = tuple(
            self._predicted_table_row(position, row, probabilities)
            for position, row in enumerate(team_rows, start=1)
        )
        return PredictedTable(simulation=simulation, rows=rows)

    @staticmethod
    def _probabilities_by_team(
        rows: Sequence[RowMapping],
    ) -> dict[UUID, tuple[PositionProbability, ...]]:
        grouped: dict[UUID, list[PositionProbability]] = {}
        for row in rows:
            team_id = row["team_id"]
            if not isinstance(team_id, UUID):
                raise _schema_incompatible()
            grouped.setdefault(team_id, []).append(
                _validated(
                    PositionProbability,
                    {"position": row["position"], "probability": row["probability"]},
                )
            )
        return {team_id: tuple(values) for team_id, values in grouped.items()}

    @staticmethod
    def _predicted_table_row(
        position: int,
        row: RowMapping,
        probabilities: Mapping[UUID, tuple[PositionProbability, ...]],
    ) -> PredictedTableRow:
        team = _validated(Team, {key: row[key] for key in Team.model_fields})
        values = {
            key: row[key]
            for key in PredictedTableRow.model_fields
            if key not in {"predicted_position", "team", "position_probabilities"}
        }
        return _validated(
            PredictedTableRow,
            {
                **values,
                "predicted_position": position,
                "team": team,
                "position_probabilities": probabilities.get(team.team_id, ()),
            },
        )

    @staticmethod
    def _model_select() -> str:
        return f"""
WITH {_LATEST_REGISTRY_EVENT_CTE}
SELECT model.model_id, model.competition_id, model.specification_version,
       assessment.selected_method, assessment.selected_configuration_id,
       assessment.selected_calibration,
       assessment.accepted AS assessment_accepted,
       event.to_state AS registry_state
FROM model.semantic_model AS model
JOIN ml.model_assessment AS assessment
  ON assessment.evaluation_manifest_sha256 = model.assessment_manifest_sha256
LEFT JOIN registry.registry_entry AS entry ON entry.model_id = model.model_id
LEFT JOIN latest_registry_event AS event
  ON event.entry_id = entry.entry_id AND event.event_rank = 1
"""

    def list_model_performance(
        self, *, pagination: PaginationParams
    ) -> PaginatedResponse[ModelPerformance]:
        base = self._model_select() + " WHERE model.competition_id = :competition_id"
        values = {"competition_id": PREMIER_LEAGUE}
        with self._connection() as connection:
            return _page(
                connection,
                count_sql=f"SELECT count(*) FROM ({base}) AS counted",
                select_sql=(
                    f"{base} ORDER BY model.model_id LIMIT :limit OFFSET :offset"
                ),
                values=values,
                pagination=pagination,
                model=ModelPerformance,
            )

    def get_model_performance(self, model_id: UUID) -> ModelPerformanceDetail:
        model_query = self._model_select() + " WHERE model.model_id = :model_id"
        metric_query = """
SELECT metric.evaluation_dataset_id, metric.evaluation_manifest_sha256,
       metric.partition_id, metric.method, metric.configuration_id,
       metric.metric_scope, metric.prediction_count, metric.home_win_count,
       metric.draw_count, metric.away_win_count, metric.mean_log_loss,
       metric.mean_multiclass_brier_score,
       metric.mean_ranked_probability_score
FROM model.semantic_model AS model
JOIN ml.model_assessment_source AS source
  ON source.assessment_manifest_sha256 = model.assessment_manifest_sha256
JOIN ml.evaluation_metric AS metric
  ON metric.evaluation_dataset_id = source.source_evaluation_dataset_id
 AND metric.evaluation_manifest_sha256 = source.source_evaluation_manifest_sha256
WHERE model.model_id = :model_id
  AND NOT EXISTS (
      SELECT 1 FROM ml.evaluation_dataset_season AS season
      WHERE season.evaluation_dataset_id = metric.evaluation_dataset_id
        AND season.evaluation_manifest_sha256 = metric.evaluation_manifest_sha256
        AND season.season_id = :sealed AND season.role <> 'excluded'
  )
ORDER BY metric.evaluation_dataset_id, metric.method,
         metric.configuration_id NULLS FIRST, metric.metric_scope,
         metric.partition_id NULLS FIRST, metric.metric_sha256
"""
        values = {"model_id": model_id, "sealed": SEALED_TEST_SEASON}
        with self._connection() as connection:
            model_row = (
                connection.execute(text(model_query), {"model_id": model_id})
                .mappings()
                .one_or_none()
            )
            metric_rows = (
                connection.execute(text(metric_query), values).mappings().all()
                if model_row is not None
                else ()
            )
        if model_row is None:
            raise _not_found("model_not_found", "Model not found.")
        model = _validated(ModelPerformance, model_row)
        metrics = tuple(_validated(EvaluationMetric, row) for row in metric_rows)
        return ModelPerformanceDetail(**model.model_dump(), metrics=metrics)


def default_resource_query_service(settings: Settings) -> ResourceQueryService:
    """Build a side-effect-free query service; connections remain request-lazy."""

    return PostgresResourceQueryService(settings)
