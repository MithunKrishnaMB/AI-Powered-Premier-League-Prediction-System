"""Deterministic CPU CatBoost classifier for three-way match outcomes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import version
from typing import Annotated, Final, Protocol, cast

import catboost as _catboost  # type: ignore[import-untyped]
import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from pl_platform.domain.evaluation import OUTCOME_ORDER, OutcomeProbabilities
from pl_platform.domain.features import PredictorSet
from pl_platform.domain.training import TrainingExample
from pl_platform.evaluation.logistic import predictor_matrix

CATBOOST_METHOD_VERSION: Final = 1
CATBOOST_RUNTIME_VERSION: Final = "1.2.10"
CATBOOST_RANDOM_SEED: Final = 20260912

if version("catboost") != CATBOOST_RUNTIME_VERSION:  # pragma: no cover
    raise RuntimeError("evaluation requires the pinned CatBoost 1.2.10 runtime")


class CatBoostModelError(ValueError):
    """CatBoost inputs or fitted outputs violate the deterministic contract."""


class CatBoostParameters(BaseModel):
    """One predefined candidate; candidates are never generated from test data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^catboost-[a-z0-9-]+$")
    iterations: Annotated[int, Field(strict=True, ge=1)]
    depth: Annotated[int, Field(strict=True, ge=1, le=12)]
    learning_rate: Annotated[float, Field(strict=True, gt=0.0, le=1.0)]
    l2_leaf_reg: Annotated[float, Field(strict=True, gt=0.0)]


CATBOOST_CANDIDATES: Final = (
    CatBoostParameters(
        id="catboost-depth4-conservative",
        iterations=200,
        depth=4,
        learning_rate=0.03,
        l2_leaf_reg=3.0,
    ),
    CatBoostParameters(
        id="catboost-depth5-conservative",
        iterations=300,
        depth=5,
        learning_rate=0.03,
        l2_leaf_reg=5.0,
    ),
    CatBoostParameters(
        id="catboost-depth6-regularized",
        iterations=200,
        depth=6,
        learning_rate=0.05,
        l2_leaf_reg=10.0,
    ),
)


class _CatBoostModel(Protocol):
    tree_count_: int
    classes_: npt.NDArray[np.int64]

    def fit(
        self,
        features: npt.NDArray[np.float64],
        targets: npt.NDArray[np.int64],
    ) -> object: ...

    def predict_proba(
        self,
        features: npt.NDArray[np.float64],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class CatBoostFitDiagnostics:
    candidate_id: str
    tree_count: int
    predictor_count: int
    training_row_count: int


@dataclass(frozen=True, slots=True)
class FittedCatBoostClassifier:
    """In-memory fitted model; registry serialization remains out of scope."""

    predictor_names: tuple[str, ...]
    model: _CatBoostModel
    diagnostics: CatBoostFitDiagnostics

    def predict_probabilities(self, predictors: PredictorSet) -> OutcomeProbabilities:
        matrix = predictor_matrix((predictors,), self.predictor_names)
        raw_probabilities = np.asarray(
            self.model.predict_proba(matrix),
            dtype=np.float64,
        )
        if (
            raw_probabilities.shape != (1, 3)
            or not np.isfinite(raw_probabilities).all()
        ):
            msg = "CatBoost returned invalid three-way probabilities"
            raise CatBoostModelError(msg)
        home_win = round(float(raw_probabilities[0, 0]), 15)
        draw = round(float(raw_probabilities[0, 1]), 15)
        away_win = 1.0 - home_win - draw
        return OutcomeProbabilities(
            home_win=home_win,
            draw=draw,
            away_win=away_win,
        )


def fit_catboost_classifier(
    examples: Sequence[TrainingExample],
    predictor_names: tuple[str, ...],
    parameters: CatBoostParameters,
) -> FittedCatBoostClassifier:
    """Fit one deterministic candidate on one chronological training window."""

    if not examples:
        msg = "CatBoost requires training examples"
        raise CatBoostModelError(msg)
    ordered = tuple(sorted(examples, key=lambda item: (item.kickoff_at, item.id)))
    outcome_index = {outcome: index for index, outcome in enumerate(OUTCOME_ORDER)}
    counts = Counter(example.target.outcome for example in ordered)
    if any(counts[outcome] == 0 for outcome in OUTCOME_ORDER):
        msg = "CatBoost training window must contain every outcome"
        raise CatBoostModelError(msg)
    features = predictor_matrix(
        tuple(example.predictors for example in ordered),
        predictor_names,
    )
    targets = np.asarray(
        [outcome_index[example.target.outcome] for example in ordered],
        dtype=np.int64,
    )
    model = cast(
        _CatBoostModel,
        _catboost.CatBoostClassifier(
            iterations=parameters.iterations,
            depth=parameters.depth,
            learning_rate=parameters.learning_rate,
            l2_leaf_reg=parameters.l2_leaf_reg,
            loss_function="MultiClass",
            random_seed=CATBOOST_RANDOM_SEED,
            thread_count=1,
            task_type="CPU",
            bootstrap_type="No",
            random_strength=0.0,
            grow_policy="SymmetricTree",
            nan_mode="Min",
            allow_writing_files=False,
            logging_level="Silent",
        ),
    )
    model.fit(features, targets)
    if tuple(int(value) for value in model.classes_) != (0, 1, 2):
        msg = "CatBoost class order does not match the canonical outcome order"
        raise CatBoostModelError(msg)
    if model.tree_count_ != parameters.iterations:
        msg = "CatBoost tree count does not match the fixed candidate contract"
        raise CatBoostModelError(msg)
    return FittedCatBoostClassifier(
        predictor_names=predictor_names,
        model=model,
        diagnostics=CatBoostFitDiagnostics(
            candidate_id=parameters.id,
            tree_count=model.tree_count_,
            predictor_count=len(predictor_names),
            training_row_count=len(ordered),
        ),
    )
