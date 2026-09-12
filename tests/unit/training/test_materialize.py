"""Tests for reproducible multi-season training-dataset materialization."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

import pl_platform.training.materialize as training_module
from pl_platform.domain.training import TrainingExample
from pl_platform.features.engine import build_point_in_time_feature_rows
from pl_platform.features.materialize import (
    FeatureMaterializationResult,
    FeaturePredictorSchema,
    load_feature_dataset,
    write_feature_dataset,
)
from pl_platform.ingestion.manifest import HistoricalDataManifest
from pl_platform.training.materialize import (
    TrainingDatasetError,
    TrainingInputChecksums,
    TrainingMaterializationResult,
    load_training_dataset,
    main,
    materialize_training_dataset,
    training_examples_from_feature_rows,
    write_training_dataset,
)
from tests.unit.features.helpers import (
    TEAM_IDS,
    make_fixture,
    make_provenance,
    make_season,
)


def _feature_artifacts(
    tmp_path: Path,
) -> tuple[
    tuple[TrainingExample, ...],
    training_module.TrainingFeatureSource,
    FeaturePredictorSchema,
    FeatureMaterializationResult,
]:
    fixtures = (
        make_fixture(
            1,
            datetime(2025, 8, 1, 15, tzinfo=UTC),
            TEAM_IDS[0],
            TEAM_IDS[1],
        ),
        make_fixture(
            2,
            datetime(2025, 8, 8, 15, tzinfo=UTC),
            TEAM_IDS[1],
            TEAM_IDS[0],
        ),
    )
    rows = build_point_in_time_feature_rows(
        fixtures,
        make_season(),
        make_provenance(),
    )
    feature_result = write_feature_dataset(
        rows,
        tmp_path / "features",
        make_provenance(),
        source_fixture_count=2,
    )
    loaded_rows, feature_manifest = load_feature_dataset(
        feature_result.feature_rows_path,
        feature_result.manifest_path,
    )
    examples = training_examples_from_feature_rows(loaded_rows, feature_manifest)
    source = training_module._feature_source(
        feature_manifest,
        feature_result.manifest_path,
    )
    return examples, source, feature_manifest.predictor_schema, feature_result


def _checksums() -> TrainingInputChecksums:
    return TrainingInputChecksums(
        historical_manifest_sha256="c" * 64,
        team_registry_sha256="d" * 64,
        season_registry_sha256="e" * 64,
    )


def test_writes_and_loads_deterministic_training_dataset(tmp_path: Path) -> None:
    examples, source, predictor_schema, _ = _feature_artifacts(tmp_path)
    output = tmp_path / "training"

    first = write_training_dataset(
        examples,
        output,
        predictor_schema,
        (source,),
        _checksums(),
    )
    original_bytes = first.training_rows_path.read_bytes()
    second = write_training_dataset(
        tuple(reversed(examples)),
        output,
        predictor_schema,
        (source,),
        _checksums(),
    )
    loaded, manifest = load_training_dataset(
        first.training_rows_path,
        first.manifest_path,
    )

    assert first.status == "written"
    assert second.status == "already_current"
    assert second.training_rows_path.read_bytes() == original_bytes
    assert loaded == examples
    assert first.training_sha256 == hashlib.sha256(original_bytes).hexdigest()
    assert manifest.training_row_count == 2
    assert manifest.season_ids == ("2025-2026",)
    assert manifest.target_schema.fields == ("outcome", "home_goals", "away_goals")
    assert manifest.predictor_schema.predictor_count == 175
    assert manifest.source_feature_datasets == (source,)


def test_training_projection_requires_a_target(tmp_path: Path) -> None:
    examples, _, _, feature_result = _feature_artifacts(tmp_path)
    rows, manifest = load_feature_dataset(
        feature_result.feature_rows_path,
        feature_result.manifest_path,
    )
    missing_target = rows[0].model_copy(update={"training_label": None})

    with pytest.raises(TrainingDatasetError, match="has no training target"):
        training_examples_from_feature_rows((missing_target,), manifest)
    assert examples[0].target is not None


def test_training_projection_rejects_feature_manifest_mismatches(
    tmp_path: Path,
) -> None:
    _, _, _, feature_result = _feature_artifacts(tmp_path)
    rows, manifest = load_feature_dataset(
        feature_result.feature_rows_path,
        feature_result.manifest_path,
    )
    wrong_season = rows[0].model_copy(update={"season_id": "2024-2025"})
    wrong_predictors = rows[0].model_copy(
        update={
            "predictors": rows[0].predictors.model_copy(update={"schema_version": 999})
        }
    )

    with pytest.raises(TrainingDatasetError, match="feature dataset"):
        training_examples_from_feature_rows((wrong_season,), manifest)
    with pytest.raises(TrainingDatasetError, match="predictor schema"):
        training_examples_from_feature_rows((wrong_predictors,), manifest)


def test_rejects_empty_counts_duplicates_and_unknown_sources(tmp_path: Path) -> None:
    examples, source, predictor_schema, _ = _feature_artifacts(tmp_path)

    with pytest.raises(TrainingDatasetError, match="cannot be empty"):
        write_training_dataset(
            (), tmp_path / "empty", predictor_schema, (source,), _checksums()
        )
    with pytest.raises(TrainingDatasetError, match="expected 2"):
        write_training_dataset(
            examples[:1],
            tmp_path / "short",
            predictor_schema,
            (source,),
            _checksums(),
        )
    with pytest.raises(TrainingDatasetError, match="IDs must be unique"):
        write_training_dataset(
            (examples[0], examples[0]),
            tmp_path / "duplicate",
            predictor_schema,
            (source,),
            _checksums(),
        )

    unknown_source = examples[0].model_copy(
        update={
            "id": UUID(int=999),
            "source_feature_dataset_id": "unknown-features",
        }
    )
    with pytest.raises(TrainingDatasetError, match="unknown feature dataset"):
        write_training_dataset(
            (unknown_source, examples[1]),
            tmp_path / "unknown",
            predictor_schema,
            (source,),
            _checksums(),
        )


def test_rejects_inconsistent_predictor_schema(tmp_path: Path) -> None:
    examples, source, predictor_schema, _ = _feature_artifacts(tmp_path)
    changed = examples[0].model_copy(
        update={
            "predictors": examples[0].predictors.model_copy(
                update={"schema_version": 999}
            )
        }
    )

    with pytest.raises(TrainingDatasetError, match="inconsistent predictors"):
        write_training_dataset(
            (changed, examples[1]),
            tmp_path / "changed",
            predictor_schema,
            (source,),
            _checksums(),
        )


def test_rejects_cross_season_feature_dataset_reference(tmp_path: Path) -> None:
    examples, source, predictor_schema, _ = _feature_artifacts(tmp_path)
    wrong_season_source = source.model_copy(update={"season_id": "2024-2025"})

    with pytest.raises(TrainingDatasetError, match="another season"):
        write_training_dataset(
            examples,
            tmp_path / "cross-season",
            predictor_schema,
            (wrong_season_source,),
            _checksums(),
        )


def test_loader_rejects_changed_training_bytes(tmp_path: Path) -> None:
    examples, source, predictor_schema, _ = _feature_artifacts(tmp_path)
    result = write_training_dataset(
        examples,
        tmp_path / "training",
        predictor_schema,
        (source,),
        _checksums(),
    )
    result.training_rows_path.write_bytes(
        result.training_rows_path.read_bytes() + b"\n"
    )

    with pytest.raises(TrainingDatasetError, match="checksum"):
        load_training_dataset(result.training_rows_path, result.manifest_path)


def _historical_manifest() -> HistoricalDataManifest:
    return HistoricalDataManifest.model_validate(
        {
            "schema_version": 1,
            "source": {
                "id": "verified-source",
                "name": "Test source",
                "homepage_url": "https://data.example.com",
                "allowed_hosts": ["data.example.com"],
                "attribution": "Test data",
                "usage_notice": "Testing only",
            },
            "files": [
                {
                    "id": "epl-2025-2026",
                    "competition_code": "E0",
                    "competition_name": "Premier League",
                    "country": "England",
                    "season_start": 2025,
                    "season_end": 2026,
                    "url": "https://data.example.com/E0.csv",
                    "destination": "raw/test/E0.csv",
                    "sha256": "b" * 64,
                    "expected_bytes": 1,
                    "expected_rows": 2,
                    "required_columns": ["Div"],
                    "encoding": "utf-8",
                    "captured_at": "2026-06-01T00:00:00Z",
                    "immutable": True,
                }
            ],
        }
    )


def test_orchestrator_reverifies_feature_sources_before_combining(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, feature_result = _feature_artifacts(tmp_path)
    manifest_path = tmp_path / "historical-manifest.json"
    teams_path = tmp_path / "teams.json"
    seasons_path = tmp_path / "seasons.json"
    manifest_path.write_text("tracked manifest", encoding="utf-8")
    teams_path.write_text("tracked teams", encoding="utf-8")
    seasons_path.write_text("tracked seasons", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        training_module,
        "load_manifest",
        lambda path: _historical_manifest(),
    )

    def verified_features(
        *args: object,
        **kwargs: object,
    ) -> tuple[FeatureMaterializationResult, ...]:
        calls.append(str(args[0]))
        return (feature_result,)

    monkeypatch.setattr(
        training_module,
        "materialize_feature_entries",
        verified_features,
    )

    result = materialize_training_dataset(
        manifest_path,
        teams_path,
        seasons_path,
        tmp_path,
    )

    assert calls == [str(manifest_path)]
    assert result.training_row_count == 2
    assert result.training_rows_path == (
        tmp_path / "processed/training/epl/2025-2026_to_2025-2026/training.jsonl"
    )


def test_cli_prints_result_and_reports_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = TrainingMaterializationResult(
        training_rows_path=tmp_path / "training.jsonl",
        manifest_path=tmp_path / "dataset-manifest.json",
        training_row_count=4180,
        training_sha256="a" * 64,
        status="written",
    )
    monkeypatch.setattr(
        training_module,
        "materialize_training_dataset",
        lambda *args: expected,
    )
    arguments = [
        "--manifest",
        "manifest.json",
        "--teams",
        "teams.json",
        "--seasons",
        "seasons.json",
    ]

    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["training_row_count"] == 4180

    def fail(*args: object) -> TrainingMaterializationResult:
        raise TrainingDatasetError("invalid training dataset")

    monkeypatch.setattr(training_module, "materialize_training_dataset", fail)
    with pytest.raises(SystemExit):
        main(arguments)
