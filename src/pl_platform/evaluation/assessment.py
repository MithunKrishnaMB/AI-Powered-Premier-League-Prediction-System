"""Frozen development acceptance gates and model-appropriate explanations."""

from __future__ import annotations

from collections.abc import Sequence
from math import sqrt
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pl_platform.domain.evaluation import (
    OutcomeCounts,
    OutcomeProbabilities,
    ProbabilisticMetricSummary,
)
from pl_platform.domain.training import TrainingExample
from pl_platform.evaluation.advanced_materialize import AdvancedEvaluationManifest
from pl_platform.evaluation.benchmarks import fit_naive_outcome_prior
from pl_platform.evaluation.catboost_materialize import CatBoostTuningDatasetManifest
from pl_platform.evaluation.catboost_model import fit_catboost_classifier
from pl_platform.evaluation.logistic import fit_multinomial_logistic_regression
from pl_platform.evaluation.materialize import EvaluationDatasetManifest
from pl_platform.evaluation.score_models import (
    PoissonModelParameters,
    fit_dixon_coles_rho,
    fit_independent_poisson,
)
from pl_platform.evaluation.walk_forward import walk_forward_windows

ASSESSMENT_METHOD_VERSION: Final = 1
CandidateMethod = Literal[
    "elo",
    "multinomial_logistic",
    "catboost",
    "poisson",
    "dixon_coles",
]
FiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
NonNegativeFloat = Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class ModelAssessmentError(ValueError):
    """Assessment inputs violate frozen population or explanation contracts."""


class AcceptanceContract(BaseModel):
    """Thresholds declared before the untouched test season may be opened."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    population: Literal["five_complete_expanding_season_walk_forward_folds"] = (
        "five_complete_expanding_season_walk_forward_folds"
    )
    fold_ids: tuple[str, ...] = tuple(window.id for window in walk_forward_windows())
    evaluation_season_ids: tuple[str, ...] = tuple(
        window.evaluation_season_ids[0] for window in walk_forward_windows()
    )
    baseline_method: Literal["naive"] = "naive"
    minimum_relative_log_loss_improvement: Annotated[
        float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)
    ] = 0.02
    maximum_brier_ratio: Annotated[
        float, Field(strict=True, ge=0.0, allow_inf_nan=False)
    ] = 1.0
    maximum_rps_ratio: Annotated[
        float, Field(strict=True, ge=0.0, allow_inf_nan=False)
    ] = 1.0
    minimum_log_loss_fold_wins: Literal[3] = 3
    champion_rule: Literal["minimum_log_loss_then_brier_then_rps_then_method_id"] = (
        "minimum_log_loss_then_brier_then_rps_then_method_id"
    )
    calibration_scope: Literal[
        "selected_identity_policy_only;paired_four_fold_diagnostic_not_comparable"
    ] = "selected_identity_policy_only;paired_four_fold_diagnostic_not_comparable"

    @model_validator(mode="after")
    def thresholds_must_remain_frozen(self) -> Self:
        if (
            self.minimum_relative_log_loss_improvement != 0.02
            or self.maximum_brier_ratio != 1.0
            or self.maximum_rps_ratio != 1.0
        ):
            raise ValueError("acceptance thresholds are frozen for this test boundary")
        return self


class FoldMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    partition_id: str = Field(min_length=1)
    evaluation_season_id: str = Field(pattern=r"^\d{4}-\d{4}$")
    metric: ProbabilisticMetricSummary


class CandidateGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: CandidateMethod
    aggregate_metric: ProbabilisticMetricSummary
    folds: tuple[FoldMetric, ...] = Field(min_length=5, max_length=5)
    relative_log_loss_improvement: FiniteFloat
    log_loss_fold_wins: Annotated[int, Field(strict=True, ge=0, le=5)]
    complete_coverage: bool
    log_loss_improvement_passed: bool
    brier_noninferiority_passed: bool
    rps_noninferiority_passed: bool
    fold_stability_passed: bool
    accepted: bool


class AcceptanceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: AcceptanceContract
    baseline_aggregate_metric: ProbabilisticMetricSummary
    baseline_folds: tuple[FoldMetric, ...] = Field(min_length=5, max_length=5)
    candidates: tuple[CandidateGateResult, ...] = Field(min_length=5, max_length=5)
    accepted_methods: tuple[CandidateMethod, ...]
    champion_method: CandidateMethod

    @model_validator(mode="after")
    def selection_must_match_contract(self) -> Self:
        expected_order: tuple[CandidateMethod, ...] = (
            "elo",
            "multinomial_logistic",
            "catboost",
            "poisson",
            "dixon_coles",
        )
        if tuple(item.method for item in self.candidates) != expected_order:
            raise ValueError("assessment candidates have an unsupported order")
        if (
            self.baseline_aggregate_metric.method != "naive"
            or self.baseline_aggregate_metric.mean_log_loss <= 0.0
            or tuple(item.partition_id for item in self.baseline_folds)
            != self.contract.fold_ids
            or tuple(item.evaluation_season_id for item in self.baseline_folds)
            != self.contract.evaluation_season_ids
            or any(item.metric.method != "naive" for item in self.baseline_folds)
            or self.baseline_aggregate_metric.prediction_count
            != sum(item.metric.prediction_count for item in self.baseline_folds)
        ):
            raise ValueError("assessment baseline does not match its frozen population")
        for candidate in self.candidates:
            folds = candidate.folds
            complete = (
                candidate.aggregate_metric.prediction_count
                == self.baseline_aggregate_metric.prediction_count
                and candidate.aggregate_metric.outcome_counts
                == self.baseline_aggregate_metric.outcome_counts
                and tuple(fold.partition_id for fold in folds) == self.contract.fold_ids
                and tuple(fold.evaluation_season_id for fold in folds)
                == self.contract.evaluation_season_ids
                and all(
                    fold.metric.method == candidate.method
                    and fold.metric.prediction_count
                    == baseline_fold.metric.prediction_count
                    and fold.metric.outcome_counts
                    == baseline_fold.metric.outcome_counts
                    for fold, baseline_fold in zip(
                        folds, self.baseline_folds, strict=True
                    )
                )
            )
            relative = (
                self.baseline_aggregate_metric.mean_log_loss
                - candidate.aggregate_metric.mean_log_loss
            ) / self.baseline_aggregate_metric.mean_log_loss
            wins = sum(
                fold.metric.mean_log_loss < baseline_fold.metric.mean_log_loss
                for fold, baseline_fold in zip(folds, self.baseline_folds, strict=True)
            )
            log_pass = relative >= self.contract.minimum_relative_log_loss_improvement
            brier_pass = (
                candidate.aggregate_metric.mean_multiclass_brier_score
                <= self.baseline_aggregate_metric.mean_multiclass_brier_score
                * self.contract.maximum_brier_ratio
            )
            rps_pass = (
                candidate.aggregate_metric.mean_ranked_probability_score
                <= self.baseline_aggregate_metric.mean_ranked_probability_score
                * self.contract.maximum_rps_ratio
            )
            fold_pass = wins >= self.contract.minimum_log_loss_fold_wins
            accepted = complete and log_pass and brier_pass and rps_pass and fold_pass
            if (
                candidate.aggregate_metric.method != candidate.method
                or abs(candidate.relative_log_loss_improvement - relative) > 1e-15
                or candidate.log_loss_fold_wins != wins
                or candidate.complete_coverage != complete
                or candidate.log_loss_improvement_passed != log_pass
                or candidate.brier_noninferiority_passed != brier_pass
                or candidate.rps_noninferiority_passed != rps_pass
                or candidate.fold_stability_passed != fold_pass
                or candidate.accepted != accepted
            ):
                raise ValueError(
                    "candidate gate result does not match recorded metrics"
                )
        expected_accepted = tuple(
            item.method for item in self.candidates if item.accepted
        )
        if self.accepted_methods != expected_accepted or not expected_accepted:
            raise ValueError("accepted methods do not match the gate results")
        expected_champion = min(
            (item for item in self.candidates if item.accepted),
            key=lambda item: (
                item.aggregate_metric.mean_log_loss,
                item.aggregate_metric.mean_multiclass_brier_score,
                item.aggregate_metric.mean_ranked_probability_score,
                item.method,
            ),
        ).method
        if self.champion_method != expected_champion:
            raise ValueError("champion does not satisfy the frozen selection rule")
        return self


class LogisticPredictorExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    predictor_name: str = Field(min_length=1)
    home_win_coefficient: FiniteFloat
    draw_coefficient: FiniteFloat
    away_win_coefficient: FiniteFloat
    l2_importance: NonNegativeFloat


class CatBoostPredictorExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    predictor_name: str = Field(min_length=1)
    normalized_prediction_values_change: NonNegativeFloat


class TeamRateExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: UUID
    attack_log_rate: FiniteFloat
    defence_log_rate: FiniteFloat


class GlobalModelExplanations(BaseModel):
    """Development-fit global explanations; no fixture target is serialized."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    development_training_row_count: PositiveInt
    outcome_order: tuple[Literal["home_win"], Literal["draw"], Literal["away_win"]]
    naive_counts: OutcomeCounts
    naive_prior: OutcomeProbabilities
    elo_signals: tuple[
        Literal["home_elo_expected_score"], Literal["away_elo_expected_score"]
    ]
    elo_interpretation: Literal[
        "relative_home_away_share_of_non_draw_mass_not_calibrated_three_way_probability"
    ]
    logistic_intercepts: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    logistic_coefficient_basis: Literal[
        "standardized_imputed_predictors;multiclass_logit_coefficients"
    ]
    logistic_predictors: tuple[LogisticPredictorExplanation, ...] = Field(min_length=1)
    catboost_importance_type: Literal["PredictionValuesChange"]
    catboost_candidate_id: str = Field(min_length=1)
    catboost_predictors: tuple[CatBoostPredictorExplanation, ...] = Field(min_length=1)
    poisson_intercept_log_rate: FiniteFloat
    poisson_home_advantage_log_rate: FiniteFloat
    poisson_rate_equations: tuple[
        Literal["home=exp(intercept+home_advantage+home_attack+away_defence)"],
        Literal["away=exp(intercept+away_attack+home_defence)"],
    ]
    poisson_teams: tuple[TeamRateExplanation, ...] = Field(min_length=1)
    dixon_coles_rho: FiniteFloat
    dixon_coles_adjusted_scores: Literal["0-0,0-1,1-0,1-1"]
    calibration_selected_strategy: Literal["identity", "temperature_scaling"]
    explanation_scope: Literal[
        "global_development_fit_only;not_fixture_level_causal_explanations"
    ]

    @model_validator(mode="after")
    def rows_must_be_complete_and_ordered(self) -> Self:
        if self.naive_counts.total != self.development_training_row_count:
            raise ValueError("naive explanation counts must cover development rows")
        expected_logistic = tuple(
            sorted(
                self.logistic_predictors,
                key=lambda row: (-row.l2_importance, row.predictor_name),
            )
        )
        expected_catboost = tuple(
            sorted(
                self.catboost_predictors,
                key=lambda row: (
                    -row.normalized_prediction_values_change,
                    row.predictor_name,
                ),
            )
        )
        if (
            self.logistic_predictors != expected_logistic
            or len({row.predictor_name for row in self.logistic_predictors})
            != len(self.logistic_predictors)
            or self.catboost_predictors != expected_catboost
            or len({row.predictor_name for row in self.catboost_predictors})
            != len(self.catboost_predictors)
        ):
            raise ValueError("predictor explanations must be unique and ordered")
        team_ids = tuple(row.team_id for row in self.poisson_teams)
        if team_ids != tuple(sorted(set(team_ids), key=str)):
            raise ValueError("Poisson explanation team IDs must be unique and ordered")
        return self


def _method_metric(
    metrics: Sequence[ProbabilisticMetricSummary], method: str
) -> ProbabilisticMetricSummary:
    try:
        return next(metric for metric in metrics if metric.method == method)
    except StopIteration as exc:
        raise ModelAssessmentError(f"missing aggregate metric for {method!r}") from exc


def _folds(
    method: CandidateMethod | Literal["naive"],
    base: EvaluationDatasetManifest,
    catboost: CatBoostTuningDatasetManifest,
    advanced: AdvancedEvaluationManifest,
) -> tuple[FoldMetric, ...]:
    selected_catboost = next(
        candidate
        for candidate in catboost.candidates
        if candidate.parameters.id == catboost.selected_candidate_id
    )
    rows: list[FoldMetric] = []
    for index, window in enumerate(walk_forward_windows()):
        if method in ("naive", "elo", "multinomial_logistic"):
            metric = _method_metric(base.walk_forward_folds[index].metrics, method)
        elif method == "catboost":
            metric = selected_catboost.folds[index].metric
        elif method == "poisson":
            metric = advanced.score_models.folds[index].poisson_metric
        else:
            metric = advanced.score_models.folds[index].dixon_coles_metric
        rows.append(
            FoldMetric(
                partition_id=window.id,
                evaluation_season_id=window.evaluation_season_ids[0],
                metric=metric,
            )
        )
    return tuple(rows)


def build_acceptance_report(
    base: EvaluationDatasetManifest,
    catboost: CatBoostTuningDatasetManifest,
    advanced: AdvancedEvaluationManifest,
) -> AcceptanceReport:
    """Apply pre-test gates to identical complete development populations."""

    contract = AcceptanceContract()
    baseline = _method_metric(base.walk_forward_aggregate_metrics, "naive")
    baseline_folds = _folds("naive", base, catboost, advanced)
    selected_catboost = next(
        candidate
        for candidate in catboost.candidates
        if candidate.parameters.id == catboost.selected_candidate_id
    )
    aggregates: tuple[tuple[CandidateMethod, ProbabilisticMetricSummary], ...] = (
        ("elo", _method_metric(base.walk_forward_aggregate_metrics, "elo")),
        (
            "multinomial_logistic",
            _method_metric(base.walk_forward_aggregate_metrics, "multinomial_logistic"),
        ),
        ("catboost", selected_catboost.aggregate_metric),
        ("poisson", advanced.score_models.aggregate_poisson_metric),
        ("dixon_coles", advanced.score_models.aggregate_dixon_coles_metric),
    )
    candidates: list[CandidateGateResult] = []
    for method, aggregate in aggregates:
        folds = _folds(method, base, catboost, advanced)
        complete = (
            aggregate.prediction_count == baseline.prediction_count
            and aggregate.outcome_counts == baseline.outcome_counts
            and tuple(fold.partition_id for fold in folds) == contract.fold_ids
            and all(
                fold.metric.prediction_count == baseline_fold.metric.prediction_count
                and fold.metric.outcome_counts == baseline_fold.metric.outcome_counts
                for fold, baseline_fold in zip(folds, baseline_folds, strict=True)
            )
        )
        relative = (
            baseline.mean_log_loss - aggregate.mean_log_loss
        ) / baseline.mean_log_loss
        wins = sum(
            fold.metric.mean_log_loss < baseline_fold.metric.mean_log_loss
            for fold, baseline_fold in zip(folds, baseline_folds, strict=True)
        )
        log_pass = relative >= contract.minimum_relative_log_loss_improvement
        brier_pass = (
            aggregate.mean_multiclass_brier_score
            <= baseline.mean_multiclass_brier_score * contract.maximum_brier_ratio
        )
        rps_pass = (
            aggregate.mean_ranked_probability_score
            <= baseline.mean_ranked_probability_score * contract.maximum_rps_ratio
        )
        fold_pass = wins >= contract.minimum_log_loss_fold_wins
        candidates.append(
            CandidateGateResult(
                method=method,
                aggregate_metric=aggregate,
                folds=folds,
                relative_log_loss_improvement=relative,
                log_loss_fold_wins=wins,
                complete_coverage=complete,
                log_loss_improvement_passed=log_pass,
                brier_noninferiority_passed=brier_pass,
                rps_noninferiority_passed=rps_pass,
                fold_stability_passed=fold_pass,
                accepted=(
                    complete and log_pass and brier_pass and rps_pass and fold_pass
                ),
            )
        )
    accepted = tuple(candidate.method for candidate in candidates if candidate.accepted)
    if not accepted:
        raise ModelAssessmentError("no candidate satisfies the frozen acceptance gates")
    champion = min(
        (candidate for candidate in candidates if candidate.accepted),
        key=lambda candidate: (
            candidate.aggregate_metric.mean_log_loss,
            candidate.aggregate_metric.mean_multiclass_brier_score,
            candidate.aggregate_metric.mean_ranked_probability_score,
            candidate.method,
        ),
    ).method
    return AcceptanceReport(
        contract=contract,
        baseline_aggregate_metric=baseline,
        baseline_folds=baseline_folds,
        candidates=tuple(candidates),
        accepted_methods=accepted,
        champion_method=champion,
    )


def build_global_explanations(
    examples: Sequence[TrainingExample],
    predictor_names: tuple[str, ...],
    base: EvaluationDatasetManifest,
    catboost: CatBoostTuningDatasetManifest,
    advanced: AdvancedEvaluationManifest,
) -> GlobalModelExplanations:
    """Refit selected models on development rows and expose global structure."""

    if not examples:
        raise ModelAssessmentError("model explanations require development examples")
    ordered = tuple(sorted(examples, key=lambda item: (item.kickoff_at, item.id)))
    counts, prior = fit_naive_outcome_prior(tuple(item.target for item in ordered))
    logistic = fit_multinomial_logistic_regression(
        ordered,
        predictor_names,
        base.logistic_parameters,
    )
    if not logistic.diagnostics.converged:
        raise ModelAssessmentError("final logistic explanation fit did not converge")
    selected = next(
        candidate
        for candidate in catboost.candidates
        if candidate.parameters.id == catboost.selected_candidate_id
    )
    catboost_model = fit_catboost_classifier(
        ordered, predictor_names, selected.parameters
    )
    importances = catboost_model.normalized_feature_importances()
    parameters = PoissonModelParameters(
        optimizer_iterations=advanced.score_models.poisson_optimizer.optimizer_iterations,
        learning_rate=advanced.score_models.poisson_optimizer.learning_rate,
        beta_one=advanced.score_models.poisson_optimizer.beta_one,
        beta_two=advanced.score_models.poisson_optimizer.beta_two,
        epsilon=advanced.score_models.poisson_optimizer.epsilon,
        l2_strength=advanced.score_models.poisson_optimizer.l2_strength,
        minimum_expected_goals=(
            advanced.score_models.poisson_optimizer.minimum_expected_goals
        ),
        maximum_expected_goals=(
            advanced.score_models.poisson_optimizer.maximum_expected_goals
        ),
        maximum_score_goals=advanced.score_models.score_grid_maximum_goals_per_team,
        dixon_coles_optimizer_iterations=(
            advanced.score_models.dixon_coles_contract.optimizer_iterations
        ),
        dixon_coles_rho_minimum=(
            advanced.score_models.dixon_coles_contract.rho_minimum
        ),
        dixon_coles_rho_maximum=(
            advanced.score_models.dixon_coles_contract.rho_maximum
        ),
    )
    poisson = fit_independent_poisson(ordered, parameters)
    dixon_coles = fit_dixon_coles_rho(poisson, ordered)
    logistic_rows = tuple(
        sorted(
            (
                LogisticPredictorExplanation(
                    predictor_name=name,
                    home_win_coefficient=float(logistic.coefficients[index, 0]),
                    draw_coefficient=float(logistic.coefficients[index, 1]),
                    away_win_coefficient=float(logistic.coefficients[index, 2]),
                    l2_importance=sqrt(
                        sum(float(value) ** 2 for value in logistic.coefficients[index])
                    ),
                )
                for index, name in enumerate(predictor_names)
            ),
            key=lambda row: (-row.l2_importance, row.predictor_name),
        )
    )
    catboost_rows = tuple(
        sorted(
            (
                CatBoostPredictorExplanation(
                    predictor_name=name,
                    normalized_prediction_values_change=importances[index],
                )
                for index, name in enumerate(predictor_names)
            ),
            key=lambda row: (
                -row.normalized_prediction_values_change,
                row.predictor_name,
            ),
        )
    )
    team_rows = tuple(
        TeamRateExplanation(
            team_id=team_id,
            attack_log_rate=float(poisson.attack[index]),
            defence_log_rate=float(poisson.defence[index]),
        )
        for index, team_id in enumerate(poisson.team_ids)
    )
    return GlobalModelExplanations(
        development_training_row_count=len(ordered),
        outcome_order=("home_win", "draw", "away_win"),
        naive_counts=counts,
        naive_prior=prior,
        elo_signals=("home_elo_expected_score", "away_elo_expected_score"),
        elo_interpretation=(
            "relative_home_away_share_of_non_draw_mass_not_calibrated_three_way_probability"
        ),
        logistic_intercepts=(
            float(logistic.intercepts[0]),
            float(logistic.intercepts[1]),
            float(logistic.intercepts[2]),
        ),
        logistic_coefficient_basis=(
            "standardized_imputed_predictors;multiclass_logit_coefficients"
        ),
        logistic_predictors=logistic_rows,
        catboost_importance_type="PredictionValuesChange",
        catboost_candidate_id=selected.parameters.id,
        catboost_predictors=catboost_rows,
        poisson_intercept_log_rate=poisson.intercept,
        poisson_home_advantage_log_rate=poisson.home_advantage,
        poisson_rate_equations=(
            "home=exp(intercept+home_advantage+home_attack+away_defence)",
            "away=exp(intercept+away_attack+home_defence)",
        ),
        poisson_teams=team_rows,
        dixon_coles_rho=dixon_coles.rho,
        dixon_coles_adjusted_scores="0-0,0-1,1-0,1-1",
        calibration_selected_strategy=advanced.calibration.selected_strategy,
        explanation_scope=(
            "global_development_fit_only;not_fixture_level_causal_explanations"
        ),
    )
