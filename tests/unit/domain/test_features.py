"""Tests for the point-in-time feature-row contract."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from pl_platform.domain.features import (
    CanonicalDatasetProvenance,
    PointInTimeFeatureRow,
    PredictorSet,
    PredictorValue,
    SourceArtifactProvenance,
    TrainingLabel,
    deterministic_feature_row_id,
)
from pl_platform.domain.fixtures import KickoffPrecision, MatchOutcome

FIXTURE_ID = UUID("e5358903-3112-54e5-9260-590bd63824ac")
HOME_TEAM_ID = UUID("6f4ce9e1-6d36-5198-af34-7aca2aac351e")
AWAY_TEAM_ID = UUID("cfde9ca5-a6d2-5ec5-acaf-3a739dcd9c5b")
FIXTURES_SHA256 = "a" * 64
SOURCE_SHA256 = "b" * 64
KICKOFF = datetime(2025, 8, 15, 19, tzinfo=UTC)
CUTOFF = datetime(2025, 8, 15, 18, tzinfo=UTC)


def _predictors() -> PredictorSet:
    return PredictorSet(
        schema_id="pre-match-core",
        schema_version=1,
        values=(
            PredictorValue(name="away_prior_matches", value=3),
            PredictorValue(name="home_is_promoted", value=False),
            PredictorValue(name="home_points_per_match", value=2.0),
            PredictorValue(name="optional_form_signal", value=None),
        ),
    )


def _provenance() -> CanonicalDatasetProvenance:
    return CanonicalDatasetProvenance(
        dataset_id="canonical-fixtures-2025-2026",
        dataset_schema_version=2,
        competition_id="eng-premier-league",
        season_id="2025-2026",
        fixtures_sha256=FIXTURES_SHA256,
        team_registry_schema_version=1,
        season_registry_schema_version=1,
        source=SourceArtifactProvenance(
            source_id="football-data",
            artifact_id="epl-2025-2026",
            sha256=SOURCE_SHA256,
            captured_at=datetime(2026, 6, 1, tzinfo=UTC),
        ),
    )


def _row_payload() -> dict[str, object]:
    predictors = _predictors()
    provenance = _provenance()
    return {
        "id": deterministic_feature_row_id(
            fixture_id=FIXTURE_ID,
            feature_cutoff_at=CUTOFF,
            predictor_schema_id=predictors.schema_id,
            predictor_schema_version=predictors.schema_version,
            canonical_dataset_id=provenance.dataset_id,
            canonical_fixtures_sha256=provenance.fixtures_sha256,
        ),
        "fixture_id": FIXTURE_ID,
        "competition_id": "eng-premier-league",
        "season_id": "2025-2026",
        "home_team_id": HOME_TEAM_ID,
        "away_team_id": AWAY_TEAM_ID,
        "kickoff_at": KICKOFF,
        "kickoff_precision": KickoffPrecision.EXACT,
        "feature_cutoff_at": CUTOFF,
        "predictors": predictors,
        "training_label": TrainingLabel(
            outcome=MatchOutcome.HOME_WIN,
            home_goals=2,
            away_goals=1,
        ),
        "provenance": provenance,
    }


def _recalculate_id(payload: dict[str, object]) -> None:
    predictors = payload["predictors"]
    provenance = payload["provenance"]
    assert isinstance(predictors, PredictorSet)
    assert isinstance(provenance, CanonicalDatasetProvenance)
    feature_cutoff_at = payload["feature_cutoff_at"]
    assert isinstance(feature_cutoff_at, datetime)
    payload["id"] = deterministic_feature_row_id(
        fixture_id=FIXTURE_ID,
        feature_cutoff_at=feature_cutoff_at,
        predictor_schema_id=predictors.schema_id,
        predictor_schema_version=predictors.schema_version,
        canonical_dataset_id=provenance.dataset_id,
        canonical_fixtures_sha256=provenance.fixtures_sha256,
    )


def test_accepts_labeled_and_unlabeled_rows_with_separate_structures() -> None:
    labeled = PointInTimeFeatureRow.model_validate(_row_payload())
    unlabeled_payload = _row_payload()
    unlabeled_payload["training_label"] = None
    unlabeled = PointInTimeFeatureRow.model_validate(unlabeled_payload)

    serialized = labeled.model_dump(mode="json")
    assert labeled.schema_version == 1
    assert serialized["predictors"]["values"][0]["name"] == "away_prior_matches"
    assert serialized["training_label"] == {
        "outcome": "home_win",
        "home_goals": 2,
        "away_goals": 1,
    }
    assert unlabeled.training_label is None


@pytest.mark.parametrize(
    ("home_goals", "away_goals", "outcome"),
    [
        (1, 1, MatchOutcome.DRAW),
        (0, 2, MatchOutcome.AWAY_WIN),
    ],
)
def test_accepts_each_consistent_training_label(
    home_goals: int,
    away_goals: int,
    outcome: MatchOutcome,
) -> None:
    label = TrainingLabel(
        home_goals=home_goals,
        away_goals=away_goals,
        outcome=outcome,
    )

    assert label.outcome == outcome


def test_rejects_training_label_that_disagrees_with_score() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        TrainingLabel(
            outcome=MatchOutcome.AWAY_WIN,
            home_goals=2,
            away_goals=1,
        )


@pytest.mark.parametrize("name", ["outcome", "full_time_score", "post_match_xg"])
def test_rejects_post_match_predictor_names(name: str) -> None:
    with pytest.raises(ValidationError, match="reserved for post-match labels"):
        PredictorValue(name=name, value=1)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            (
                PredictorValue(name="prior_points", value=1),
                PredictorValue(name="prior_points", value=2),
            ),
            "must be unique",
        ),
        (
            (
                PredictorValue(name="home_prior_points", value=1),
                PredictorValue(name="away_prior_points", value=2),
            ),
            "ordered by name",
        ),
    ],
)
def test_rejects_ambiguous_predictor_ordering(
    values: tuple[PredictorValue, ...],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        PredictorSet(schema_id="pre-match-core", schema_version=1, values=values)


def test_rejects_non_finite_or_coerced_predictor_values() -> None:
    with pytest.raises(ValidationError):
        PredictorValue(name="prior_points", value=float("nan"))
    with pytest.raises(ValidationError):
        PredictorValue.model_validate({"name": "prior_points", "value": "2"})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("away_team_id", HOME_TEAM_ID, "teams must differ"),
        ("competition_id", "other-league", "provenance competition"),
        ("season_id", "2024-2025", "provenance season"),
        (
            "kickoff_at",
            datetime(2025, 8, 15, 20, tzinfo=timezone(timedelta(hours=1))),
            "kickoff_at must be timezone-aware UTC",
        ),
        (
            "feature_cutoff_at",
            datetime(2025, 8, 15, 19, 30, tzinfo=UTC),
            "later than an exact kickoff",
        ),
    ],
)
def test_rejects_internally_inconsistent_rows(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _row_payload()
    payload[field] = value
    if field == "feature_cutoff_at":
        _recalculate_id(payload)

    with pytest.raises(ValidationError, match=message):
        PointInTimeFeatureRow.model_validate(payload)


def test_exact_kickoff_allows_cutoff_at_kickoff() -> None:
    payload = _row_payload()
    payload["feature_cutoff_at"] = KICKOFF
    _recalculate_id(payload)

    row = PointInTimeFeatureRow.model_validate(payload)

    assert row.feature_cutoff_at == row.kickoff_at


def test_date_only_fixture_requires_cutoff_before_fixture_date() -> None:
    payload = _row_payload()
    payload["kickoff_precision"] = KickoffPrecision.DATE_ONLY
    payload["feature_cutoff_at"] = datetime(2025, 8, 15, 0, tzinfo=UTC)
    _recalculate_id(payload)

    with pytest.raises(ValidationError, match="before the source-local fixture date"):
        PointInTimeFeatureRow.model_validate(payload)

    payload["feature_cutoff_at"] = datetime(2025, 8, 14, 22, 59, tzinfo=UTC)
    _recalculate_id(payload)
    row = PointInTimeFeatureRow.model_validate(payload)
    assert row.kickoff_precision == KickoffPrecision.DATE_ONLY


def test_date_only_fixture_requires_a_supported_competition_timezone() -> None:
    payload = _row_payload()
    payload["competition_id"] = "other-league"
    payload["provenance"] = _provenance().model_copy(
        update={"competition_id": "other-league"}
    )
    payload["kickoff_precision"] = KickoffPrecision.DATE_ONLY

    with pytest.raises(ValidationError, match="known competition"):
        PointInTimeFeatureRow.model_validate(payload)


def test_rejects_non_utc_source_capture_time() -> None:
    with pytest.raises(ValidationError, match="captured_at must be timezone-aware UTC"):
        SourceArtifactProvenance(
            source_id="football-data",
            artifact_id="epl-2025-2026",
            sha256=SOURCE_SHA256,
            captured_at=datetime(2026, 6, 1),
        )


def test_deterministic_identity_changes_with_lineage_and_is_validated() -> None:
    payload = _row_payload()
    first = payload["id"]
    _recalculate_id(payload)
    assert payload["id"] == first

    payload["id"] = UUID("00000000-0000-0000-0000-000000000000")
    with pytest.raises(ValidationError, match="deterministic identity"):
        PointInTimeFeatureRow.model_validate(payload)

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        deterministic_feature_row_id(
            fixture_id=FIXTURE_ID,
            feature_cutoff_at=datetime(2025, 8, 15, 18),
            predictor_schema_id="pre-match-core",
            predictor_schema_version=1,
            canonical_dataset_id="canonical-fixtures-2025-2026",
            canonical_fixtures_sha256=FIXTURES_SHA256,
        )


def test_contract_is_frozen_and_forbids_unknown_fields() -> None:
    row = PointInTimeFeatureRow.model_validate(_row_payload())
    with pytest.raises(ValidationError, match="frozen"):
        row.season_id = "2024-2025"

    payload = _row_payload()
    payload["provider_team_name"] = "Example FC"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PointInTimeFeatureRow.model_validate(payload)
