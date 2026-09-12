"""Tests for deterministic feature-dataset materialization and lineage."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

import pl_platform.features.materialize as materialize_module
from pl_platform.domain.features import (
    PointInTimeFeatureRow,
    PredictorSet,
    deterministic_feature_row_id,
)
from pl_platform.domain.fixtures import SourceFixtureReference
from pl_platform.domain.seasons import load_season_registry
from pl_platform.domain.teams import load_team_registry
from pl_platform.features.engine import build_point_in_time_feature_rows
from pl_platform.features.materialize import (
    FeatureDatasetError,
    FeatureMaterializationResult,
    load_feature_dataset,
    main,
    materialize_feature_entry,
    write_feature_dataset,
)
from pl_platform.ingestion.manifest import HistoricalFile, load_manifest
from pl_platform.ingestion.materialize import (
    MaterializationResult,
    write_canonical_dataset,
)
from tests.unit.features.helpers import (
    TEAM_IDS,
    make_fixture,
    make_provenance,
    make_season,
)
from tests.unit.quality.test_fixtures import complete_fixtures


def _rows() -> tuple[PointInTimeFeatureRow, ...]:
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
    return build_point_in_time_feature_rows(
        fixtures,
        make_season(),
        make_provenance(),
    )


def test_writes_deterministic_rows_and_complete_lineage_manifest(
    tmp_path: Path,
) -> None:
    rows = _rows()
    provenance = make_provenance()

    first = write_feature_dataset(
        rows,
        tmp_path,
        provenance,
        source_fixture_count=2,
    )
    original_bytes = first.feature_rows_path.read_bytes()
    second = write_feature_dataset(
        tuple(reversed(rows)),
        tmp_path,
        provenance,
        source_fixture_count=2,
    )
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    serialized_rows, validated_manifest = load_feature_dataset(
        first.feature_rows_path,
        first.manifest_path,
    )

    assert first.status == "written"
    assert second.status == "already_current"
    assert second.feature_rows_path.read_bytes() == original_bytes
    assert serialized_rows == rows
    assert first.features_sha256 == hashlib.sha256(original_bytes).hexdigest()
    assert manifest["features_sha256"] == first.features_sha256
    assert manifest["feature_row_schema_version"] == 1
    assert manifest["predictor_schema"]["id"] == "epl-pre-match"
    assert manifest["predictor_schema"]["predictor_count"] > 0
    assert manifest["processing"]["date_only_batch_timezone"] == "Europe/London"
    assert manifest["canonical_source"]["fixtures_sha256"] == "a" * 64
    assert manifest["raw_source"]["sha256"] == "b" * 64
    assert validated_manifest.features_sha256 == first.features_sha256


def test_loader_rejects_changed_feature_bytes(tmp_path: Path) -> None:
    result = write_feature_dataset(
        _rows(),
        tmp_path,
        make_provenance(),
        source_fixture_count=2,
    )
    result.feature_rows_path.write_bytes(result.feature_rows_path.read_bytes() + b"\n")

    with pytest.raises(FeatureDatasetError, match="checksum"):
        load_feature_dataset(result.feature_rows_path, result.manifest_path)


def test_replaces_stale_outputs_without_leaving_temporary_files(
    tmp_path: Path,
) -> None:
    rows = _rows()
    (tmp_path / "features.jsonl").write_text("stale", encoding="utf-8")
    (tmp_path / "dataset-manifest.json").write_text("stale", encoding="utf-8")

    result = write_feature_dataset(
        rows,
        tmp_path,
        make_provenance(),
        source_fixture_count=2,
    )

    assert result.status == "written"
    assert result.feature_rows_path.read_text(encoding="utf-8") != "stale"
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_cleans_up_after_publish_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError(source, destination)

    monkeypatch.setattr("pl_platform.features.materialize.os.replace", fail_replace)

    with pytest.raises(OSError):
        write_feature_dataset(
            _rows(),
            tmp_path,
            make_provenance(),
            source_fixture_count=2,
        )

    assert not list(tmp_path.glob("*.tmp"))


def test_rejects_row_count_and_identity_conflicts(tmp_path: Path) -> None:
    rows = _rows()
    provenance = make_provenance()

    with pytest.raises(FeatureDatasetError, match="expected 3"):
        write_feature_dataset(
            rows,
            tmp_path,
            provenance,
            source_fixture_count=3,
        )
    with pytest.raises(FeatureDatasetError, match="cannot be empty"):
        write_feature_dataset(
            (),
            tmp_path,
            provenance,
            source_fixture_count=0,
        )
    with pytest.raises(FeatureDatasetError, match="IDs must be unique"):
        write_feature_dataset(
            (rows[0], rows[0]),
            tmp_path,
            provenance,
            source_fixture_count=2,
        )
    duplicate_fixture = rows[1].model_copy(
        update={"fixture_id": rows[0].fixture_id, "id": UUID(int=999)}
    )
    with pytest.raises(FeatureDatasetError, match="unique fixtures"):
        write_feature_dataset(
            (rows[0], duplicate_fixture),
            tmp_path,
            provenance,
            source_fixture_count=2,
        )


@pytest.mark.parametrize(
    ("changed_row", "message"),
    [
        (
            lambda row: row.model_copy(
                update={"provenance": make_provenance(season_id="2024-2025")}
            ),
            "inconsistent source provenance",
        ),
        (
            lambda row: row.model_copy(
                update={
                    "predictors": row.predictors.model_copy(
                        update={"schema_version": 2}
                    )
                }
            ),
            "unsupported predictor schema",
        ),
        (
            lambda row: row.model_copy(update={"training_label": None}),
            "requires a training label",
        ),
    ],
)
def test_rejects_inconsistent_row_schema_or_lineage(
    tmp_path: Path,
    changed_row: Callable[[PointInTimeFeatureRow], PointInTimeFeatureRow],
    message: str,
) -> None:
    rows = _rows()
    changed = changed_row(rows[0])

    with pytest.raises(FeatureDatasetError, match=message):
        write_feature_dataset(
            (changed, rows[1]),
            tmp_path,
            make_provenance(),
            source_fixture_count=2,
        )


def test_rejects_changed_or_empty_predictor_name_schema(tmp_path: Path) -> None:
    rows = _rows()
    provenance = make_provenance()
    second_payload = rows[1].model_dump()
    second_predictors = rows[1].predictors.model_copy(
        update={"values": rows[1].predictors.values[:-1]}
    )
    second_payload["predictors"] = second_predictors
    second_payload["id"] = deterministic_feature_row_id(
        fixture_id=rows[1].fixture_id,
        feature_cutoff_at=rows[1].feature_cutoff_at,
        predictor_schema_id=second_predictors.schema_id,
        predictor_schema_version=second_predictors.schema_version,
        canonical_dataset_id=provenance.dataset_id,
        canonical_fixtures_sha256=provenance.fixtures_sha256,
    )
    changed_names = PointInTimeFeatureRow.model_validate(second_payload)

    with pytest.raises(FeatureDatasetError, match="one predictor schema"):
        write_feature_dataset(
            (rows[0], changed_names),
            tmp_path,
            provenance,
            source_fixture_count=2,
        )

    empty_payload = rows[0].model_dump()
    empty_payload["predictors"] = PredictorSet(
        schema_id="epl-pre-match",
        schema_version=1,
    )
    empty_row = PointInTimeFeatureRow.model_validate(empty_payload)
    with pytest.raises(FeatureDatasetError, match="at least one approved predictor"):
        write_feature_dataset(
            (empty_row,),
            tmp_path,
            provenance,
            source_fixture_count=1,
        )


def _canonical_test_dataset(
    tmp_path: Path,
) -> tuple[MaterializationResult, HistoricalFile]:
    manifest = load_manifest(Path("data/manifests/football-data.json"))
    entry = manifest.get_file("epl-2025-2026")
    source_id = manifest.source.id
    fixtures = tuple(
        fixture.model_copy(
            update={
                "source_references": (
                    SourceFixtureReference(
                        source_id=source_id,
                        external_id=f"test:{fixture.id}",
                    ),
                )
            }
        )
        for fixture in complete_fixtures()
    )
    teams = load_team_registry(Path("data/reference/teams.json"))
    seasons = load_season_registry(Path("data/reference/seasons.json"), teams)
    result = write_canonical_dataset(
        fixtures,
        tmp_path / "canonical",
        entry,
        seasons.get("2025-2026"),
        team_registry_schema_version=teams.schema_version,
        season_registry_schema_version=seasons.schema_version,
    )
    return result, entry


def test_entry_materialization_requires_verified_canonical_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_result, _ = _canonical_test_dataset(tmp_path)
    calls: list[tuple[object, ...]] = []

    def verified_historical(*args: object) -> MaterializationResult:
        calls.append(args)
        return canonical_result

    monkeypatch.setattr(
        materialize_module,
        "materialize_historical_entry",
        verified_historical,
    )

    result = materialize_feature_entry(
        Path("data/manifests/football-data.json"),
        "epl-2025-2026",
        Path("data/reference/teams.json"),
        Path("data/reference/seasons.json"),
        tmp_path,
    )

    assert len(calls) == 1
    assert result.feature_row_count == 380
    assert result.feature_rows_path == (
        tmp_path / "processed/features/epl/2025-2026/features.jsonl"
    )


@pytest.mark.parametrize(
    ("manifest_change", "message"),
    [
        ({"fixtures_sha256": "c" * 64}, "fixture checksum"),
        ({"fixture_count": 379}, "fixture count"),
        ({"source": {"file_id": "other", "sha256": "b" * 64}}, "raw artifact"),
    ],
)
def test_rejects_corrupt_canonical_lineage(
    tmp_path: Path,
    manifest_change: dict[str, object],
    message: str,
) -> None:
    canonical_result, entry = _canonical_test_dataset(tmp_path)
    payload = json.loads(canonical_result.manifest_path.read_text(encoding="utf-8"))
    payload.update(manifest_change)
    if "source" in manifest_change:
        payload["source"]["captured_at"] = entry.captured_at.isoformat()
    canonical_result.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FeatureDatasetError, match=message):
        materialize_module._canonical_inputs(
            canonical_result.fixtures_path,
            canonical_result.manifest_path,
            entry,
            source_id="football-data-uk",
        )


def test_cli_supports_single_and_all_entry_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = FeatureMaterializationResult(
        feature_rows_path=tmp_path / "features.jsonl",
        manifest_path=tmp_path / "dataset-manifest.json",
        feature_row_count=380,
        features_sha256="a" * 64,
        status="written",
    )
    monkeypatch.setattr(
        materialize_module,
        "materialize_feature_entry",
        lambda *args: expected,
    )

    assert (
        main(
            [
                "--manifest",
                "manifest.json",
                "--entry-id",
                "entry",
                "--teams",
                "teams.json",
                "--seasons",
                "seasons.json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["feature_row_count"] == 380

    assert (
        main(
            [
                "--manifest",
                "data/manifests/football-data.json",
                "--all",
                "--teams",
                "teams.json",
                "--seasons",
                "seasons.json",
            ]
        )
        == 0
    )
    assert len(json.loads(capsys.readouterr().out)) == 11


def test_cli_reports_materialization_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object) -> FeatureMaterializationResult:
        raise FeatureDatasetError("invalid feature dataset")

    monkeypatch.setattr(materialize_module, "materialize_feature_entry", fail)

    with pytest.raises(SystemExit):
        main(
            [
                "--manifest",
                "manifest.json",
                "--entry-id",
                "entry",
                "--teams",
                "teams.json",
                "--seasons",
                "seasons.json",
            ]
        )
