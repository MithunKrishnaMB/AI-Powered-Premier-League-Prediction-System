"""Step 5.6: training, sealed-test, prediction and evaluation structures.

Revision ID: f0003_step_5_6
Revises: f0002_step_5_5
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0003_step_5_6"
down_revision: str | Sequence[str] | None = "f0002_step_5_5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DDL: tuple[str, ...] = (
    "CREATE SCHEMA ml",
    """
    CREATE TABLE ml.target_schema (
        schema_id text NOT NULL,
        schema_version persistence.positive_version NOT NULL,
        field_ordinal_1 text NOT NULL,
        field_ordinal_2 text NOT NULL,
        field_ordinal_3 text NOT NULL,
        outcome_ordinal_1 text NOT NULL,
        outcome_ordinal_2 text NOT NULL,
        outcome_ordinal_3 text NOT NULL,
        PRIMARY KEY (schema_id, schema_version),
        CONSTRAINT ck_target_schema_v1 CHECK (
            schema_id = 'full-time-result-and-score' AND schema_version = 1
            AND field_ordinal_1 = 'outcome'
            AND field_ordinal_2 = 'home_goals'
            AND field_ordinal_3 = 'away_goals'
            AND outcome_ordinal_1 = 'home_win'
            AND outcome_ordinal_2 = 'draw'
            AND outcome_ordinal_3 = 'away_win'
        )
    )
    """,
    """
    CREATE TABLE ml.training_dataset (
        dataset_id text NOT NULL,
        manifest_sha256 persistence.sha256 NOT NULL,
        competition_id text NOT NULL,
        dataset_schema_version persistence.positive_version NOT NULL,
        training_row_schema_version persistence.positive_version NOT NULL,
        row_count integer NOT NULL,
        training_sha256 persistence.sha256 NOT NULL,
        predictor_schema_id text NOT NULL,
        predictor_schema_version persistence.positive_version NOT NULL,
        target_schema_id text NOT NULL,
        target_schema_version persistence.positive_version NOT NULL,
        historical_manifest_sha256 persistence.sha256 NOT NULL,
        team_registry_sha256 persistence.sha256 NOT NULL,
        season_registry_sha256 persistence.sha256 NOT NULL,
        ordering_contract text NOT NULL,
        PRIMARY KEY (dataset_id, manifest_sha256),
        CONSTRAINT uq_training_dataset_bytes UNIQUE (dataset_id, training_sha256),
        CONSTRAINT uq_training_manifest_sha UNIQUE (manifest_sha256),
        CONSTRAINT fk_training_dataset_manifest FOREIGN KEY (manifest_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_training_dataset_bytes FOREIGN KEY (training_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_training_dataset_competition FOREIGN KEY (competition_id)
            REFERENCES identity.competition (competition_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_training_dataset_predictors FOREIGN KEY (
            predictor_schema_id, predictor_schema_version
        ) REFERENCES feature.predictor_schema (schema_id, schema_version)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_training_dataset_targets FOREIGN KEY (
            target_schema_id, target_schema_version
        ) REFERENCES ml.target_schema (schema_id, schema_version)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_training_dataset_historical_document FOREIGN KEY (
            historical_manifest_sha256
        ) REFERENCES identity.reference_document (document_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_training_dataset_team_document FOREIGN KEY (
            team_registry_sha256
        ) REFERENCES identity.reference_document (document_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_training_dataset_season_document FOREIGN KEY (
            season_registry_sha256
        ) REFERENCES identity.reference_document (document_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_training_dataset_v1 CHECK (
            dataset_schema_version = 1 AND training_row_schema_version = 1
            AND row_count > 0
            AND ordering_contract = 'kickoff_at_training_example_id'
        )
    )
    """,
    """
    CREATE TABLE ml.training_dataset_season (
        training_dataset_id text NOT NULL,
        training_manifest_sha256 persistence.sha256 NOT NULL,
        ordinal integer NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        PRIMARY KEY (training_dataset_id, training_manifest_sha256, ordinal),
        CONSTRAINT uq_training_dataset_season UNIQUE (
            training_dataset_id, training_manifest_sha256,
            competition_id, season_id
        ),
        CONSTRAINT fk_training_dataset_season_owner FOREIGN KEY (
            training_dataset_id, training_manifest_sha256
        ) REFERENCES ml.training_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_training_dataset_season_identity FOREIGN KEY (
            competition_id, season_id
        ) REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_training_dataset_season_ordinal CHECK (ordinal >= 0)
    )
    """,
    """
    CREATE TABLE ml.training_feature_source (
        training_dataset_id text NOT NULL,
        training_manifest_sha256 persistence.sha256 NOT NULL,
        ordinal integer NOT NULL,
        feature_dataset_id text NOT NULL,
        feature_manifest_sha256 persistence.sha256 NOT NULL,
        canonical_dataset_id text NOT NULL,
        canonical_manifest_sha256 persistence.sha256 NOT NULL,
        raw_source_id text NOT NULL,
        raw_artifact_id text NOT NULL,
        historical_context_sha256 persistence.sha256 NOT NULL,
        PRIMARY KEY (training_dataset_id, training_manifest_sha256, ordinal),
        CONSTRAINT uq_training_feature_source UNIQUE (
            training_dataset_id, training_manifest_sha256,
            feature_dataset_id, feature_manifest_sha256
        ),
        CONSTRAINT fk_training_feature_source_owner FOREIGN KEY (
            training_dataset_id, training_manifest_sha256
        ) REFERENCES ml.training_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_training_feature_source_dataset FOREIGN KEY (
            feature_dataset_id, feature_manifest_sha256
        ) REFERENCES feature.feature_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_training_feature_source_canonical FOREIGN KEY (
            canonical_dataset_id, canonical_manifest_sha256
        ) REFERENCES football.canonical_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_training_feature_source_ordinal CHECK (ordinal >= 0)
    )
    """,
    """
    CREATE TABLE ml.training_example (
        training_example_id uuid PRIMARY KEY,
        schema_version persistence.positive_version NOT NULL,
        source_feature_dataset_id text NOT NULL,
        source_feature_manifest_sha256 persistence.sha256 NOT NULL,
        feature_row_id uuid NOT NULL,
        fixture_id uuid NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        home_team_id uuid NOT NULL,
        away_team_id uuid NOT NULL,
        kickoff_at timestamptz NOT NULL,
        kickoff_precision text NOT NULL,
        feature_cutoff_at timestamptz NOT NULL,
        CONSTRAINT uq_training_example_snapshot UNIQUE (
            training_example_id, source_feature_dataset_id,
            source_feature_manifest_sha256, feature_row_id, fixture_id,
            competition_id, season_id, kickoff_at, feature_cutoff_at
        ),
        CONSTRAINT fk_training_example_feature_row FOREIGN KEY (
            feature_row_id, source_feature_dataset_id,
            source_feature_manifest_sha256, fixture_id, competition_id,
            season_id, home_team_id, away_team_id, kickoff_at,
            kickoff_precision, feature_cutoff_at
        ) REFERENCES feature.feature_row (
            feature_row_id, feature_dataset_id, feature_manifest_sha256,
            fixture_id, competition_id, season_id, home_team_id, away_team_id,
            kickoff_at, kickoff_precision, feature_cutoff_at
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_training_example_v1 CHECK (schema_version = 1),
        CONSTRAINT ck_training_example_deterministic_id CHECK (
            training_example_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:training-example:1|' || feature_row_id::text
                || '|' || source_feature_dataset_id
            )
        )
    )
    """,
    """
    CREATE TABLE ml.training_dataset_example (
        training_dataset_id text NOT NULL,
        training_manifest_sha256 persistence.sha256 NOT NULL,
        ordinal integer NOT NULL,
        training_example_id uuid NOT NULL,
        PRIMARY KEY (training_dataset_id, training_manifest_sha256, ordinal),
        CONSTRAINT uq_training_dataset_example UNIQUE (
            training_dataset_id, training_manifest_sha256, training_example_id
        ),
        CONSTRAINT fk_training_dataset_example_owner FOREIGN KEY (
            training_dataset_id, training_manifest_sha256
        ) REFERENCES ml.training_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_training_dataset_example_example FOREIGN KEY (
            training_example_id
        ) REFERENCES ml.training_example (training_example_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_training_dataset_example_ordinal CHECK (ordinal >= 0)
    )
    """,
    """
    CREATE TABLE ml.training_target (
        training_example_id uuid PRIMARY KEY,
        outcome text NOT NULL,
        home_goals smallint NOT NULL,
        away_goals smallint NOT NULL,
        CONSTRAINT fk_training_target_example FOREIGN KEY (training_example_id)
            REFERENCES ml.training_example (training_example_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_training_target_goals CHECK (
            home_goals >= 0 AND away_goals >= 0
        ),
        CONSTRAINT ck_training_target_outcome CHECK (
            outcome = CASE
                WHEN home_goals > away_goals THEN 'home_win'
                WHEN home_goals < away_goals THEN 'away_win'
                ELSE 'draw'
            END
        )
    )
    """,
    """
    CREATE TABLE ml.untouched_test_freeze (
        freeze_id text NOT NULL,
        manifest_sha256 persistence.sha256 NOT NULL,
        schema_version persistence.positive_version NOT NULL,
        source_training_dataset_id text NOT NULL,
        source_training_manifest_sha256 persistence.sha256 NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        status text NOT NULL,
        row_count integer NOT NULL,
        ordered_identity_sha256 persistence.sha256 NOT NULL,
        target_access_policy text NOT NULL,
        development_use_policy text NOT NULL,
        PRIMARY KEY (freeze_id, manifest_sha256),
        CONSTRAINT uq_untouched_test_manifest UNIQUE (manifest_sha256),
        CONSTRAINT fk_untouched_test_manifest FOREIGN KEY (manifest_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_untouched_test_training FOREIGN KEY (
            source_training_dataset_id, source_training_manifest_sha256
        ) REFERENCES ml.training_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_untouched_test_season FOREIGN KEY (
            competition_id, season_id
        ) REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_untouched_test_freeze_v1 CHECK (
            schema_version = 1
            AND freeze_id = 'untouched-test-2025-2026-v1'
            AND competition_id = 'eng-premier-league'
            AND season_id = '2025-2026'
            AND status = 'frozen_untouched' AND row_count = 380
            AND target_access_policy = 'prohibited_until_explicit_final_test_step'
            AND development_use_policy = 'identity_and_lineage_only'
        )
    )
    """,
    """
    CREATE TABLE ml.untouched_test_freeze_member (
        freeze_id text NOT NULL,
        freeze_manifest_sha256 persistence.sha256 NOT NULL,
        ordinal integer NOT NULL,
        training_example_id uuid NOT NULL,
        feature_row_id uuid NOT NULL,
        fixture_id uuid NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        kickoff_at timestamptz NOT NULL,
        feature_cutoff_at timestamptz NOT NULL,
        source_feature_dataset_id text NOT NULL,
        source_feature_manifest_sha256 persistence.sha256 NOT NULL,
        predictor_payload_sha256 persistence.sha256 NOT NULL,
        PRIMARY KEY (freeze_id, freeze_manifest_sha256, ordinal),
        CONSTRAINT uq_untouched_test_member UNIQUE (
            freeze_id, freeze_manifest_sha256, training_example_id
        ),
        CONSTRAINT fk_untouched_test_member_owner FOREIGN KEY (
            freeze_id, freeze_manifest_sha256
        ) REFERENCES ml.untouched_test_freeze (freeze_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_untouched_test_member_example FOREIGN KEY (
            training_example_id, source_feature_dataset_id,
            source_feature_manifest_sha256, feature_row_id, fixture_id,
            competition_id, season_id, kickoff_at, feature_cutoff_at
        ) REFERENCES ml.training_example (
            training_example_id, source_feature_dataset_id,
            source_feature_manifest_sha256, feature_row_id, fixture_id,
            competition_id, season_id, kickoff_at, feature_cutoff_at
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_untouched_test_member_ordinal CHECK (ordinal >= 0),
        CONSTRAINT ck_untouched_test_member_season CHECK (
            competition_id = 'eng-premier-league' AND season_id = '2025-2026'
        )
    )
    """,
    """
    CREATE TABLE ml.evaluation_dataset (
        dataset_id text NOT NULL,
        manifest_sha256 persistence.sha256 NOT NULL,
        evaluation_kind text NOT NULL,
        dataset_schema_version persistence.positive_version NOT NULL,
        prediction_schema_version persistence.positive_version,
        source_training_dataset_id text NOT NULL,
        source_training_manifest_sha256 persistence.sha256 NOT NULL,
        prediction_sha256 persistence.sha256,
        row_count integer NOT NULL,
        numerical_runtime text NOT NULL,
        ordering_contract text NOT NULL,
        outcome_ordinal_1 text NOT NULL,
        outcome_ordinal_2 text NOT NULL,
        outcome_ordinal_3 text NOT NULL,
        PRIMARY KEY (dataset_id, manifest_sha256),
        CONSTRAINT uq_evaluation_manifest_sha UNIQUE (manifest_sha256),
        CONSTRAINT fk_evaluation_dataset_manifest FOREIGN KEY (manifest_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_evaluation_dataset_training FOREIGN KEY (
            source_training_dataset_id, source_training_manifest_sha256
        ) REFERENCES ml.training_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_evaluation_dataset_predictions FOREIGN KEY (
            prediction_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_evaluation_dataset_kind CHECK (evaluation_kind IN (
            'base', 'catboost_tuning', 'advanced', 'assessment'
        )),
        CONSTRAINT ck_evaluation_dataset_versions CHECK (
            dataset_schema_version = 1
            AND (prediction_schema_version IS NULL OR prediction_schema_version = 1)
        ),
        CONSTRAINT ck_evaluation_dataset_count CHECK (row_count >= 0),
        CONSTRAINT ck_evaluation_outcome_order CHECK (
            outcome_ordinal_1 = 'home_win'
            AND outcome_ordinal_2 = 'draw'
            AND outcome_ordinal_3 = 'away_win'
        )
    )
    """,
    """
    CREATE TABLE ml.evaluation_dataset_season (
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        role text NOT NULL,
        ordinal integer NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        PRIMARY KEY (
            evaluation_dataset_id, evaluation_manifest_sha256, role, ordinal
        ),
        CONSTRAINT uq_evaluation_dataset_season UNIQUE (
            evaluation_dataset_id, evaluation_manifest_sha256,
            competition_id, season_id
        ),
        CONSTRAINT fk_evaluation_dataset_season_owner FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) REFERENCES ml.evaluation_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_evaluation_dataset_season_identity FOREIGN KEY (
            competition_id, season_id
        ) REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_evaluation_dataset_season_role CHECK (
            role IN ('development', 'excluded')
            AND (season_id <> '2025-2026' OR role = 'excluded')
        ),
        CONSTRAINT ck_evaluation_dataset_season_ordinal CHECK (ordinal >= 0)
    )
    """,
    """
    CREATE TABLE ml.evaluation_partition (
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        partition_id text NOT NULL,
        partition_ordinal integer NOT NULL,
        partition_kind text NOT NULL,
        reference_row_count integer NOT NULL,
        evaluation_row_count integer NOT NULL,
        fit_converged boolean,
        fit_iterations integer,
        diagnostic_sha256 persistence.sha256,
        PRIMARY KEY (
            evaluation_dataset_id, evaluation_manifest_sha256, partition_id
        ),
        CONSTRAINT uq_evaluation_partition_ordinal UNIQUE (
            evaluation_dataset_id, evaluation_manifest_sha256,
            partition_ordinal
        ),
        CONSTRAINT fk_evaluation_partition_owner FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) REFERENCES ml.evaluation_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_evaluation_partition_diagnostic FOREIGN KEY (
            diagnostic_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_evaluation_partition_ordinal CHECK (partition_ordinal >= 0),
        CONSTRAINT ck_evaluation_partition_kind CHECK (
            partition_kind IN ('fixed_holdout', 'walk_forward', 'calibration')
        ),
        CONSTRAINT ck_evaluation_partition_counts CHECK (
            reference_row_count > 0 AND evaluation_row_count > 0
            AND (fit_iterations IS NULL OR fit_iterations > 0)
        )
    )
    """,
    """
    CREATE TABLE ml.evaluation_partition_season (
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        partition_id text NOT NULL,
        role text NOT NULL,
        ordinal integer NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        PRIMARY KEY (
            evaluation_dataset_id, evaluation_manifest_sha256,
            partition_id, role, ordinal
        ),
        CONSTRAINT uq_evaluation_partition_season UNIQUE (
            evaluation_dataset_id, evaluation_manifest_sha256,
            partition_id, competition_id, season_id
        ),
        CONSTRAINT fk_evaluation_partition_season_owner FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256, partition_id
        ) REFERENCES ml.evaluation_partition (
            evaluation_dataset_id, evaluation_manifest_sha256, partition_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_evaluation_partition_season_identity FOREIGN KEY (
            competition_id, season_id
        ) REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_evaluation_partition_season_role CHECK (
            role IN ('reference', 'evaluation', 'excluded')
            AND (season_id <> '2025-2026' OR role = 'excluded')
        ),
        CONSTRAINT ck_evaluation_partition_season_ordinal CHECK (ordinal >= 0)
    )
    """,
    """
    CREATE TABLE ml.probabilistic_prediction (
        prediction_id uuid PRIMARY KEY,
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        partition_id text NOT NULL,
        method text NOT NULL,
        method_version persistence.positive_version NOT NULL,
        configuration_id text,
        source_training_dataset_id text NOT NULL,
        source_training_manifest_sha256 persistence.sha256 NOT NULL,
        source_training_sha256 persistence.sha256 NOT NULL,
        source_training_example_id uuid NOT NULL,
        fixture_id uuid NOT NULL,
        season_id text NOT NULL,
        kickoff_at timestamptz NOT NULL,
        feature_cutoff_at timestamptz NOT NULL,
        home_win_probability persistence.probability NOT NULL,
        draw_probability persistence.probability NOT NULL,
        away_win_probability persistence.probability NOT NULL,
        CONSTRAINT fk_prediction_evaluation FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) REFERENCES ml.evaluation_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_prediction_partition FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256, partition_id
        ) REFERENCES ml.evaluation_partition (
            evaluation_dataset_id, evaluation_manifest_sha256, partition_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_prediction_training FOREIGN KEY (
            source_training_dataset_id, source_training_manifest_sha256
        ) REFERENCES ml.training_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_prediction_example FOREIGN KEY (
            source_training_example_id
        ) REFERENCES ml.training_example (training_example_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_prediction_fixture FOREIGN KEY (fixture_id)
            REFERENCES football.fixture (fixture_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT uq_prediction_method UNIQUE NULLS NOT DISTINCT (
            evaluation_dataset_id, evaluation_manifest_sha256, partition_id,
            source_training_example_id, method, method_version, configuration_id
        ),
        CONSTRAINT ck_prediction_method CHECK (method IN (
            'naive', 'elo', 'multinomial_logistic', 'catboost',
            'catboost_calibrated', 'poisson', 'dixon_coles'
        )),
        CONSTRAINT ck_prediction_method_version CHECK (method_version = 1),
        CONSTRAINT ck_prediction_final_test_sealed CHECK (
            season_id <> '2025-2026'
        ),
        CONSTRAINT ck_prediction_cutoff CHECK (feature_cutoff_at <= kickoff_at),
        CONSTRAINT ck_prediction_probability_mass CHECK (
            abs(
                home_win_probability + draw_probability
                + away_win_probability - 1.0
            ) <= 1e-12
        ),
        CONSTRAINT ck_prediction_deterministic_id CHECK (
            prediction_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:evaluation-prediction:1|'
                || source_training_sha256 || '|'
                || source_training_example_id::text || '|' || partition_id
                || '|' || method || '|' || method_version::text
                || CASE WHEN configuration_id IS NULL
                    THEN '' ELSE '|' || configuration_id END
            )
        )
    )
    """,
    """
    CREATE TABLE ml.evaluation_metric (
        metric_sha256 persistence.sha256 PRIMARY KEY,
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        partition_id text,
        method text NOT NULL,
        configuration_id text,
        metric_scope text NOT NULL,
        prediction_count integer NOT NULL,
        home_win_count integer NOT NULL,
        draw_count integer NOT NULL,
        away_win_count integer NOT NULL,
        mean_log_loss persistence.finite_float64 NOT NULL,
        mean_multiclass_brier_score persistence.finite_float64 NOT NULL,
        mean_ranked_probability_score persistence.finite_float64 NOT NULL,
        CONSTRAINT fk_evaluation_metric_dataset FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) REFERENCES ml.evaluation_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT uq_evaluation_metric UNIQUE NULLS NOT DISTINCT (
            evaluation_dataset_id, evaluation_manifest_sha256, partition_id,
            method, configuration_id, metric_scope
        ),
        CONSTRAINT ck_evaluation_metric_method CHECK (method IN (
            'naive', 'elo', 'multinomial_logistic', 'catboost',
            'catboost_calibrated', 'poisson', 'dixon_coles'
        )),
        CONSTRAINT ck_evaluation_metric_scope CHECK (
            metric_scope IN ('partition', 'aggregate', 'paired_calibration')
        ),
        CONSTRAINT ck_evaluation_metric_counts CHECK (
            prediction_count > 0 AND home_win_count >= 0 AND draw_count >= 0
            AND away_win_count >= 0
            AND home_win_count + draw_count + away_win_count = prediction_count
        ),
        CONSTRAINT ck_evaluation_metric_nonnegative CHECK (
            mean_log_loss >= 0.0 AND mean_multiclass_brier_score >= 0.0
            AND mean_ranked_probability_score >= 0.0
        )
    )
    """,
    """
    CREATE TABLE ml.catboost_candidate (
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        candidate_id text NOT NULL,
        selection_ordinal integer NOT NULL,
        iterations smallint NOT NULL,
        depth smallint NOT NULL,
        learning_rate persistence.finite_float64 NOT NULL,
        l2_leaf_reg persistence.finite_float64 NOT NULL,
        random_seed integer NOT NULL,
        thread_count smallint NOT NULL,
        task_type text NOT NULL,
        PRIMARY KEY (
            evaluation_dataset_id, evaluation_manifest_sha256, candidate_id
        ),
        CONSTRAINT uq_catboost_candidate_ordinal UNIQUE (
            evaluation_dataset_id, evaluation_manifest_sha256,
            selection_ordinal
        ),
        CONSTRAINT fk_catboost_candidate_evaluation FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) REFERENCES ml.evaluation_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_catboost_candidate_contract CHECK (
            selection_ordinal >= 0
            AND (
                (candidate_id = 'catboost-depth4-conservative'
                 AND iterations = 200 AND depth = 4
                 AND learning_rate = 0.03 AND l2_leaf_reg = 3.0)
                OR
                (candidate_id = 'catboost-depth5-conservative'
                 AND iterations = 300 AND depth = 5
                 AND learning_rate = 0.03 AND l2_leaf_reg = 5.0)
                OR
                (candidate_id = 'catboost-depth6-regularized'
                 AND iterations = 200 AND depth = 6
                 AND learning_rate = 0.05 AND l2_leaf_reg = 10.0)
            )
            AND random_seed = 20260912 AND thread_count = 1
            AND task_type = 'CPU'
        )
    )
    """,
    """
    CREATE TABLE ml.catboost_fold_fit (
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        candidate_id text NOT NULL,
        partition_id text NOT NULL,
        reference_row_count integer NOT NULL,
        evaluation_row_count integer NOT NULL,
        tree_count smallint NOT NULL,
        PRIMARY KEY (
            evaluation_dataset_id, evaluation_manifest_sha256,
            candidate_id, partition_id
        ),
        CONSTRAINT fk_catboost_fold_candidate FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256, candidate_id
        ) REFERENCES ml.catboost_candidate (
            evaluation_dataset_id, evaluation_manifest_sha256, candidate_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_catboost_fold_partition FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256, partition_id
        ) REFERENCES ml.evaluation_partition (
            evaluation_dataset_id, evaluation_manifest_sha256, partition_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_catboost_fold_counts CHECK (
            reference_row_count > 0 AND evaluation_row_count > 0
            AND tree_count IN (200, 300)
        )
    )
    """,
    """
    CREATE TABLE ml.calibration_evaluation (
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        method_version persistence.positive_version NOT NULL,
        configuration_id text NOT NULL,
        protocol text NOT NULL,
        selected_strategy text NOT NULL,
        selection_rule text NOT NULL,
        minimum_temperature persistence.finite_float64 NOT NULL,
        maximum_temperature persistence.finite_float64 NOT NULL,
        optimizer_iterations smallint NOT NULL,
        probability_floor persistence.finite_float64 NOT NULL,
        final_temperature persistence.finite_float64 NOT NULL,
        PRIMARY KEY (evaluation_dataset_id, evaluation_manifest_sha256),
        CONSTRAINT fk_calibration_evaluation_owner FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) REFERENCES ml.evaluation_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_calibration_evaluation_v1 CHECK (
            method_version = 1 AND configuration_id = 'temperature-scaling-v1'
            AND protocol = 'expanding_prior_oof_temperature_scaling'
            AND selected_strategy = 'identity'
            AND selection_rule = 'log_loss_then_brier_then_rps'
            AND minimum_temperature = 0.25
            AND maximum_temperature = 4.0
            AND optimizer_iterations = 96
            AND probability_floor = 1e-15
            AND final_temperature >= minimum_temperature
            AND final_temperature <= maximum_temperature
        )
    )
    """,
    """
    CREATE TABLE ml.calibration_fold_fit (
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        partition_id text NOT NULL,
        ordinal integer NOT NULL,
        fit_row_count integer NOT NULL,
        evaluation_row_count integer NOT NULL,
        temperature persistence.finite_float64 NOT NULL,
        optimizer_iterations integer NOT NULL,
        PRIMARY KEY (
            evaluation_dataset_id, evaluation_manifest_sha256, partition_id
        ),
        CONSTRAINT uq_calibration_fold_ordinal UNIQUE (
            evaluation_dataset_id, evaluation_manifest_sha256, ordinal
        ),
        CONSTRAINT fk_calibration_fold_owner FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) REFERENCES ml.calibration_evaluation (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_calibration_fold_values CHECK (
            ordinal >= 0 AND fit_row_count > 0 AND evaluation_row_count > 0
            AND temperature > 0.0 AND optimizer_iterations > 0
        )
    )
    """,
    """
    CREATE TABLE ml.score_model_evaluation (
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        method_version persistence.positive_version NOT NULL,
        poisson_configuration_id text NOT NULL,
        dixon_coles_configuration_id text NOT NULL,
        predictor_contract text NOT NULL,
        score_grid_maximum_goals smallint NOT NULL,
        PRIMARY KEY (evaluation_dataset_id, evaluation_manifest_sha256),
        CONSTRAINT fk_score_model_evaluation_owner FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) REFERENCES ml.evaluation_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_score_model_evaluation_v1 CHECK (
            method_version = 1
            AND poisson_configuration_id = 'independent-poisson-v1'
            AND dixon_coles_configuration_id = 'dixon-coles-v1'
            AND predictor_contract
                = 'canonical_team_ids_and_training_window_scores_only'
            AND score_grid_maximum_goals = 40
        )
    )
    """,
    """
    CREATE TABLE ml.poisson_fit (
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        partition_id text NOT NULL,
        training_row_count integer NOT NULL,
        team_count smallint NOT NULL,
        optimizer_iterations integer NOT NULL,
        final_objective persistence.finite_float64 NOT NULL,
        mean_home_goals persistence.finite_float64 NOT NULL,
        mean_away_goals persistence.finite_float64 NOT NULL,
        PRIMARY KEY (
            evaluation_dataset_id, evaluation_manifest_sha256, partition_id
        ),
        CONSTRAINT fk_poisson_fit_owner FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) REFERENCES ml.score_model_evaluation (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_poisson_fit_values CHECK (
            training_row_count > 0 AND team_count > 0
            AND optimizer_iterations > 0
            AND mean_home_goals > 0.0 AND mean_away_goals > 0.0
        )
    )
    """,
    """
    CREATE TABLE ml.dixon_coles_fit (
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        partition_id text NOT NULL,
        training_row_count integer NOT NULL,
        rho persistence.finite_float64 NOT NULL,
        low_score_row_count integer NOT NULL,
        adjustment_negative_log_likelihood persistence.finite_float64 NOT NULL,
        adjusted_scores text NOT NULL,
        PRIMARY KEY (
            evaluation_dataset_id, evaluation_manifest_sha256, partition_id
        ),
        CONSTRAINT fk_dixon_coles_fit_owner FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) REFERENCES ml.score_model_evaluation (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_dixon_coles_fit_values CHECK (
            training_row_count > 0 AND rho >= -0.15 AND rho <= 0.025
            AND low_score_row_count >= 0
            AND adjusted_scores = '0-0,0-1,1-0,1-1'
        )
    )
    """,
    """
    CREATE TABLE ml.model_assessment (
        evaluation_dataset_id text NOT NULL,
        evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        schema_version persistence.positive_version NOT NULL,
        accepted boolean NOT NULL,
        selected_method text NOT NULL,
        selected_configuration_id text NOT NULL,
        selected_calibration text NOT NULL,
        predictor_schema_id text NOT NULL,
        predictor_schema_version persistence.positive_version NOT NULL,
        outcome_ordinal_1 text NOT NULL,
        outcome_ordinal_2 text NOT NULL,
        outcome_ordinal_3 text NOT NULL,
        explanation_sha256 persistence.sha256 NOT NULL,
        PRIMARY KEY (evaluation_dataset_id, evaluation_manifest_sha256),
        CONSTRAINT uq_model_assessment_manifest UNIQUE (
            evaluation_manifest_sha256
        ),
        CONSTRAINT fk_model_assessment_owner FOREIGN KEY (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) REFERENCES ml.evaluation_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_model_assessment_predictors FOREIGN KEY (
            predictor_schema_id, predictor_schema_version
        ) REFERENCES feature.predictor_schema (schema_id, schema_version)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_model_assessment_explanation FOREIGN KEY (
            explanation_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_model_assessment_selected_policy CHECK (
            schema_version = 1 AND accepted
            AND selected_method = 'catboost'
            AND selected_configuration_id = 'catboost-depth6-regularized'
            AND selected_calibration = 'identity'
            AND predictor_schema_id = 'epl-pre-match'
            AND predictor_schema_version = 2
            AND outcome_ordinal_1 = 'home_win'
            AND outcome_ordinal_2 = 'draw'
            AND outcome_ordinal_3 = 'away_win'
        )
    )
    """,
    """
    CREATE TABLE ml.model_assessment_source (
        assessment_dataset_id text NOT NULL,
        assessment_manifest_sha256 persistence.sha256 NOT NULL,
        ordinal integer NOT NULL,
        source_evaluation_dataset_id text NOT NULL,
        source_evaluation_manifest_sha256 persistence.sha256 NOT NULL,
        PRIMARY KEY (
            assessment_dataset_id, assessment_manifest_sha256, ordinal
        ),
        CONSTRAINT uq_model_assessment_source UNIQUE (
            assessment_dataset_id, assessment_manifest_sha256,
            source_evaluation_dataset_id, source_evaluation_manifest_sha256
        ),
        CONSTRAINT fk_model_assessment_source_owner FOREIGN KEY (
            assessment_dataset_id, assessment_manifest_sha256
        ) REFERENCES ml.model_assessment (
            evaluation_dataset_id, evaluation_manifest_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_model_assessment_source_evaluation FOREIGN KEY (
            source_evaluation_dataset_id, source_evaluation_manifest_sha256
        ) REFERENCES ml.evaluation_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_model_assessment_source_ordinal CHECK (ordinal >= 0)
    )
    """,
    """
    ALTER TABLE model.semantic_model
      ADD CONSTRAINT fk_semantic_model_training FOREIGN KEY (
          training_dataset_id, training_manifest_sha256
      ) REFERENCES ml.training_dataset (dataset_id, manifest_sha256)
      ON UPDATE RESTRICT ON DELETE RESTRICT
    """,
    """
    ALTER TABLE model.semantic_model
      ADD CONSTRAINT fk_semantic_model_assessment FOREIGN KEY (
          assessment_manifest_sha256
      ) REFERENCES ml.model_assessment (evaluation_manifest_sha256)
      ON UPDATE RESTRICT ON DELETE RESTRICT
    """,
    """
    ALTER TABLE model.semantic_model
      ADD CONSTRAINT fk_semantic_model_test_freeze FOREIGN KEY (
          untouched_test_freeze_id, untouched_test_manifest_sha256
      ) REFERENCES ml.untouched_test_freeze (freeze_id, manifest_sha256)
      ON UPDATE RESTRICT ON DELETE RESTRICT
    """,
    """
    ALTER TABLE registry.registry_event
      ADD CONSTRAINT fk_registry_event_assessment FOREIGN KEY (
          assessment_manifest_sha256
      ) REFERENCES ml.model_assessment (evaluation_manifest_sha256)
      ON UPDATE RESTRICT ON DELETE RESTRICT
    """,
    """
    CREATE FUNCTION ml.validate_training_dataset()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        expected_count integer;
        actual_count integer;
        target_count integer;
        minimum_ordinal integer;
        maximum_ordinal integer;
    BEGIN
        SELECT row_count INTO expected_count
        FROM ml.training_dataset
        WHERE dataset_id = NEW.dataset_id
          AND manifest_sha256 = NEW.manifest_sha256;
        SELECT count(*), min(ordinal), max(ordinal),
               count(t.training_example_id)
        INTO actual_count, minimum_ordinal, maximum_ordinal, target_count
        FROM ml.training_dataset_example e
        LEFT JOIN ml.training_target t USING (training_example_id)
        WHERE e.training_dataset_id = NEW.dataset_id
          AND e.training_manifest_sha256 = NEW.manifest_sha256;
        IF actual_count <> expected_count OR target_count <> expected_count
           OR minimum_ordinal <> 0 OR maximum_ordinal <> expected_count - 1 THEN
            RAISE EXCEPTION 'provenance_mismatch: training dataset incomplete'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER training_dataset_complete
    AFTER INSERT ON ml.training_dataset
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ml.validate_training_dataset()
    """,
    """
    CREATE FUNCTION ml.validate_untouched_test_freeze()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        owner_freeze text;
        owner_manifest persistence.sha256;
        expected_count integer;
        actual_count integer;
        minimum_ordinal integer;
        maximum_ordinal integer;
    BEGIN
        owner_freeze := NEW.freeze_id;
        owner_manifest := coalesce(
            to_jsonb(NEW)->>'freeze_manifest_sha256',
            to_jsonb(NEW)->>'manifest_sha256'
        );
        SELECT row_count INTO expected_count
        FROM ml.untouched_test_freeze
        WHERE freeze_id = owner_freeze AND manifest_sha256 = owner_manifest;
        SELECT count(*), min(ordinal), max(ordinal)
        INTO actual_count, minimum_ordinal, maximum_ordinal
        FROM ml.untouched_test_freeze_member
        WHERE freeze_id = owner_freeze
          AND freeze_manifest_sha256 = owner_manifest;
        IF actual_count <> expected_count OR minimum_ordinal <> 0
           OR maximum_ordinal <> expected_count - 1 THEN
            RAISE EXCEPTION 'provenance_mismatch: test freeze incomplete'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER untouched_test_freeze_complete_from_freeze
    AFTER INSERT ON ml.untouched_test_freeze
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ml.validate_untouched_test_freeze()
    """,
    """
    CREATE CONSTRAINT TRIGGER untouched_test_freeze_complete_from_member
    AFTER INSERT ON ml.untouched_test_freeze_member
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ml.validate_untouched_test_freeze()
    """,
    """
    CREATE FUNCTION ml.validate_evaluation_partition_chronology()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        latest_reference text;
        earliest_evaluation text;
    BEGIN
        SELECT max(season_id) FILTER (WHERE role = 'reference'),
               min(season_id) FILTER (WHERE role = 'evaluation')
        INTO latest_reference, earliest_evaluation
        FROM ml.evaluation_partition_season
        WHERE evaluation_dataset_id = NEW.evaluation_dataset_id
          AND evaluation_manifest_sha256 = NEW.evaluation_manifest_sha256
          AND partition_id = NEW.partition_id;
        IF latest_reference IS NULL OR earliest_evaluation IS NULL
           OR latest_reference >= earliest_evaluation THEN
            RAISE EXCEPTION 'chronology_violation: partition is not chronological'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER evaluation_partition_chronology_from_partition
    AFTER INSERT ON ml.evaluation_partition
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ml.validate_evaluation_partition_chronology()
    """,
)


IMMUTABLE_TABLES: tuple[str, ...] = (
    "target_schema",
    "training_dataset",
    "training_dataset_season",
    "training_feature_source",
    "training_example",
    "training_dataset_example",
    "training_target",
    "untouched_test_freeze",
    "untouched_test_freeze_member",
    "evaluation_dataset",
    "evaluation_dataset_season",
    "evaluation_partition",
    "evaluation_partition_season",
    "probabilistic_prediction",
    "evaluation_metric",
    "catboost_candidate",
    "catboost_fold_fit",
    "calibration_evaluation",
    "calibration_fold_fit",
    "score_model_evaluation",
    "poisson_fit",
    "dixon_coles_fit",
    "model_assessment",
    "model_assessment_source",
)


def upgrade() -> None:
    """Create training, sealed-test and chronological evaluation structures."""

    for statement in DDL:
        op.execute(sa.text(statement))
    for table in IMMUTABLE_TABLES:
        op.execute(
            sa.text(
                f"CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE "
                f"ON ml.{table} FOR EACH ROW EXECUTE FUNCTION "
                "persistence.reject_immutable_mutation()"
            )
        )


def downgrade() -> None:
    """Remove Step 5.6 cross-schema constraints and ML structures."""

    op.execute(
        sa.text(
            "ALTER TABLE registry.registry_event "
            "DROP CONSTRAINT fk_registry_event_assessment"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE model.semantic_model "
            "DROP CONSTRAINT fk_semantic_model_test_freeze, "
            "DROP CONSTRAINT fk_semantic_model_assessment, "
            "DROP CONSTRAINT fk_semantic_model_training"
        )
    )
    op.execute(sa.text("DROP SCHEMA ml CASCADE"))
