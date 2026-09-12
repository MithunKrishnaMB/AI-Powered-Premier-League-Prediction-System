"""Tests for the formal untouched-season freeze contract."""

import hashlib
from pathlib import Path

import pytest

from pl_platform.domain.features import PredictorSet, PredictorValue, TrainingLabel
from pl_platform.domain.fixtures import MatchOutcome
from pl_platform.evaluation.test_freeze import (
    TestFreezeError as FreezeError,
)
from pl_platform.evaluation.test_freeze import (
    build_test_freeze,
    load_test_freeze,
    write_test_freeze,
)
from tests.unit.evaluation.helpers import (
    complete_corpus,
    make_training_manifest,
    training_manifest_payload,
)


def _manifest_sha256() -> str:
    return hashlib.sha256(
        training_manifest_payload(make_training_manifest())
    ).hexdigest()


def test_freeze_is_target_independent_and_deterministic(tmp_path: Path) -> None:
    examples = complete_corpus()
    manifest = make_training_manifest()
    freeze = build_test_freeze(examples, manifest, _manifest_sha256())
    first = write_test_freeze(freeze, tmp_path)
    second = write_test_freeze(freeze, tmp_path)
    loaded = load_test_freeze(first.manifest_path)

    changed = list(examples)
    test_index = next(
        index
        for index, example in enumerate(changed)
        if example.season_id == "2025-2026"
    )
    changed[test_index] = changed[test_index].model_copy(
        update={
            "target": TrainingLabel(
                outcome=MatchOutcome.DRAW,
                home_goals=0,
                away_goals=0,
            )
        }
    )
    changed_freeze = build_test_freeze(changed, manifest, _manifest_sha256())

    assert freeze.status == "frozen_untouched"
    assert freeze.test_row_count == 3
    assert freeze == changed_freeze
    assert first.status == "written"
    assert second.status == "already_current"
    assert loaded == freeze


def test_freeze_hash_changes_when_test_predictors_change() -> None:
    examples = list(complete_corpus())
    manifest = make_training_manifest()
    original = build_test_freeze(examples, manifest, _manifest_sha256())
    test_index = next(
        index
        for index, example in enumerate(examples)
        if example.season_id == "2025-2026"
    )
    predictors = examples[test_index].predictors
    changed_predictors = PredictorSet(
        schema_id=predictors.schema_id,
        schema_version=predictors.schema_version,
        values=tuple(
            PredictorValue(name=item.name, value=99.0)
            if item.name == "feature_signal"
            else item
            for item in predictors.values
        ),
    )
    examples[test_index] = examples[test_index].model_copy(
        update={"predictors": changed_predictors}
    )

    changed = build_test_freeze(examples, manifest, _manifest_sha256())

    assert changed.test_example_identities_sha256 != (
        original.test_example_identities_sha256
    )


def test_freeze_rejects_missing_or_incomplete_test_population() -> None:
    examples = tuple(
        example for example in complete_corpus() if example.season_id != "2025-2026"
    )
    with pytest.raises(FreezeError, match="no rows"):
        build_test_freeze(examples, make_training_manifest(), _manifest_sha256())

    incomplete = complete_corpus()[:-1]
    with pytest.raises(FreezeError, match="row count"):
        build_test_freeze(
            incomplete,
            make_training_manifest(),
            _manifest_sha256(),
        )


def test_freeze_loader_rejects_noncanonical_json_bytes(tmp_path: Path) -> None:
    freeze = build_test_freeze(
        complete_corpus(),
        make_training_manifest(),
        _manifest_sha256(),
    )
    path = tmp_path / "freeze.json"
    path.write_text(freeze.model_dump_json(), encoding="utf-8")

    with pytest.raises(FreezeError, match="not deterministic"):
        load_test_freeze(path)
