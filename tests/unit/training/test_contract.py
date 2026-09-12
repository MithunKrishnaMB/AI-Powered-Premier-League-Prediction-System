"""Tests for the versioned model-ready training-example contract."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from pl_platform.domain.fixtures import KickoffPrecision, MatchOutcome
from pl_platform.domain.training import (
    TrainingExample,
    deterministic_training_example_id,
)
from pl_platform.features.engine import build_point_in_time_feature_rows
from tests.unit.features.helpers import (
    TEAM_IDS,
    make_fixture,
    make_provenance,
    make_season,
)

FEATURE_DATASET_ID = "point-in-time-features-2025-2026"


def _example_payload() -> dict[str, object]:
    fixture = make_fixture(
        1,
        datetime(2025, 8, 1, 15, tzinfo=UTC),
        TEAM_IDS[0],
        TEAM_IDS[1],
    )
    (row,) = build_point_in_time_feature_rows(
        (fixture,), make_season(), make_provenance()
    )
    return {
        "id": deterministic_training_example_id(row.id, FEATURE_DATASET_ID),
        "feature_row_id": row.id,
        "fixture_id": row.fixture_id,
        "competition_id": row.competition_id,
        "season_id": row.season_id,
        "home_team_id": row.home_team_id,
        "away_team_id": row.away_team_id,
        "kickoff_at": row.kickoff_at,
        "kickoff_precision": row.kickoff_precision,
        "feature_cutoff_at": row.feature_cutoff_at,
        "predictors": row.predictors,
        "target": row.training_label,
        "source_feature_dataset_id": FEATURE_DATASET_ID,
    }


def test_accepts_training_example_with_structurally_separate_target() -> None:
    example = TrainingExample.model_validate(_example_payload())
    serialized = example.model_dump(mode="json")

    assert example.schema_version == 1
    assert serialized["target"] == {
        "outcome": "home_win",
        "home_goals": 1,
        "away_goals": 0,
    }
    assert "target" not in serialized["predictors"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("id", UUID(int=999), "deterministic identity"),
        ("away_team_id", TEAM_IDS[0], "teams must differ"),
        (
            "kickoff_at",
            datetime(2025, 8, 1, 16, tzinfo=timezone(timedelta(hours=1))),
            "kickoff_at must be timezone-aware UTC",
        ),
        (
            "feature_cutoff_at",
            datetime(2025, 8, 1, 16, tzinfo=UTC),
            "later than an exact kickoff",
        ),
    ],
)
def test_rejects_invalid_identity_domain_or_exact_time(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _example_payload()
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        TrainingExample.model_validate(payload)


def test_rejects_date_only_cutoff_inside_local_fixture_date() -> None:
    payload = _example_payload()
    payload["kickoff_precision"] = KickoffPrecision.DATE_ONLY
    payload["feature_cutoff_at"] = datetime(2025, 7, 31, 23, 30, tzinfo=UTC)

    with pytest.raises(ValidationError, match="precede its local fixture date"):
        TrainingExample.model_validate(payload)


def test_rejects_empty_predictor_set() -> None:
    payload = _example_payload()
    payload["predictors"] = {"schema_id": "epl-pre-match", "schema_version": 1}

    with pytest.raises(ValidationError, match="require approved predictors"):
        TrainingExample.model_validate(payload)


def test_target_score_consistency_remains_enforced() -> None:
    payload = _example_payload()
    payload["target"] = {
        "outcome": MatchOutcome.AWAY_WIN,
        "home_goals": 1,
        "away_goals": 0,
    }

    with pytest.raises(ValidationError, match="does not match"):
        TrainingExample.model_validate(payload)
