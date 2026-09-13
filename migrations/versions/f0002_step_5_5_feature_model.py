"""Step 5.5: feature, Elo, semantic model, artifact and registry structures.

Revision ID: f0002_step_5_5
Revises: f0001_step_5_4
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0002_step_5_5"
down_revision: str | Sequence[str] | None = "f0001_step_5_4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DDL: tuple[str, ...] = (
    "CREATE SCHEMA feature",
    "CREATE SCHEMA model",
    "CREATE SCHEMA registry",
    """
    CREATE TABLE feature.predictor_schema (
        schema_id text NOT NULL,
        schema_version persistence.positive_version NOT NULL,
        predictor_count integer NOT NULL,
        ordered_names_sha256 persistence.sha256 NOT NULL,
        PRIMARY KEY (schema_id, schema_version),
        CONSTRAINT uq_predictor_schema_snapshot UNIQUE (
            schema_id, schema_version, ordered_names_sha256
        ),
        CONSTRAINT ck_predictor_schema_supported CHECK (
            schema_id = 'epl-pre-match'
            AND schema_version = 2
            AND predictor_count = 175
            AND ordered_names_sha256
                = 'ddc9bdc8fbe020555e87d55a81f17622888a6917299dfe96aabb2caabe651fcb'
        )
    )
    """,
    """
    CREATE TABLE feature.predictor_definition (
        schema_id text NOT NULL,
        schema_version persistence.positive_version NOT NULL,
        ordinal integer NOT NULL,
        predictor_name text NOT NULL,
        PRIMARY KEY (schema_id, schema_version, ordinal),
        CONSTRAINT uq_predictor_definition_name UNIQUE (
            schema_id, schema_version, predictor_name
        ),
        CONSTRAINT fk_predictor_definition_schema FOREIGN KEY (
            schema_id, schema_version
        ) REFERENCES feature.predictor_schema (schema_id, schema_version)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_predictor_definition_ordinal CHECK (ordinal >= 0),
        CONSTRAINT ck_predictor_definition_name CHECK (
            predictor_name ~ '^[a-z][a-z0-9_]*$'
            AND predictor_name NOT IN (
                'outcome', 'home_goals', 'away_goals', 'full_time_score'
            )
            AND predictor_name !~ '^(target|label|post_match|full_time)_'
        )
    )
    """,
    """
    CREATE TABLE feature.processing_policy (
        policy_sha256 persistence.sha256 PRIMARY KEY,
        policy_version persistence.positive_version NOT NULL,
        chronology_version persistence.positive_version NOT NULL,
        date_only_batch_timezone text NOT NULL,
        form_window_matches smallint NOT NULL,
        season_state_resets boolean NOT NULL,
        opening_prior_schema_version persistence.positive_version NOT NULL,
        opening_prior_weight_matches smallint NOT NULL,
        opening_prior_continued_source text NOT NULL,
        opening_prior_promoted_source text NOT NULL,
        opening_prior_first_window_source text NOT NULL,
        opening_prior_fixed_points_per_match persistence.finite_float64 NOT NULL,
        opening_prior_fixed_result_rate persistence.finite_float64 NOT NULL,
        opening_prior_fixed_goals_per_match persistence.finite_float64 NOT NULL,
        elo_schema_version persistence.positive_version NOT NULL,
        elo_initial_rating persistence.finite_float64 NOT NULL,
        elo_home_advantage persistence.finite_float64 NOT NULL,
        elo_k_factor persistence.finite_float64 NOT NULL,
        elo_rating_scale persistence.finite_float64 NOT NULL,
        elo_season_retention persistence.finite_float64 NOT NULL,
        CONSTRAINT ck_processing_policy_v1 CHECK (
            policy_version = 1
            AND chronology_version = 1
            AND date_only_batch_timezone = 'Europe/London'
            AND form_window_matches = 5
            AND season_state_resets
            AND opening_prior_schema_version = 1
            AND opening_prior_weight_matches = 5
            AND opening_prior_continued_source = 'previous_team'
            AND opening_prior_promoted_source = 'previous_league'
            AND opening_prior_first_window_source = 'fixed_baseline'
            AND opening_prior_fixed_points_per_match = 1.3333333333333333
            AND opening_prior_fixed_result_rate = 0.3333333333333333
            AND opening_prior_fixed_goals_per_match = 1.5
            AND elo_schema_version = 1
            AND elo_initial_rating = 1500.0
            AND elo_home_advantage = 65.0
            AND elo_k_factor = 20.0
            AND elo_rating_scale = 400.0
            AND elo_season_retention = 0.75
        )
    )
    """,
    """
    CREATE TABLE feature.feature_dataset (
        dataset_id text NOT NULL,
        manifest_sha256 persistence.sha256 NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        canonical_dataset_id text NOT NULL,
        canonical_manifest_sha256 persistence.sha256 NOT NULL,
        canonical_fixtures_sha256 persistence.sha256 NOT NULL,
        raw_source_id text NOT NULL,
        raw_artifact_id text NOT NULL,
        predictor_schema_id text NOT NULL,
        predictor_schema_version persistence.positive_version NOT NULL,
        processing_policy_sha256 persistence.sha256 NOT NULL,
        features_sha256 persistence.sha256 NOT NULL,
        dataset_schema_version persistence.positive_version NOT NULL,
        feature_row_schema_version persistence.positive_version NOT NULL,
        row_count integer NOT NULL,
        historical_context_sha256 persistence.sha256 NOT NULL,
        previous_season_id text,
        previous_canonical_dataset_id text,
        previous_fixtures_sha256 persistence.sha256,
        ordering_contract text NOT NULL,
        PRIMARY KEY (dataset_id, manifest_sha256),
        CONSTRAINT uq_feature_dataset_bytes UNIQUE (dataset_id, features_sha256),
        CONSTRAINT uq_feature_dataset_season_bytes UNIQUE (
            competition_id, season_id, dataset_schema_version, features_sha256
        ),
        CONSTRAINT uq_feature_dataset_snapshot UNIQUE (
            dataset_id, manifest_sha256, competition_id, season_id,
            canonical_dataset_id, canonical_manifest_sha256,
            predictor_schema_id, predictor_schema_version
        ),
        CONSTRAINT uq_feature_dataset_canonical_bytes UNIQUE (
            dataset_id, manifest_sha256, canonical_fixtures_sha256
        ),
        CONSTRAINT fk_feature_dataset_manifest FOREIGN KEY (manifest_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_feature_dataset_bytes FOREIGN KEY (features_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_feature_dataset_season FOREIGN KEY (
            competition_id, season_id
        ) REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_feature_dataset_canonical FOREIGN KEY (
            canonical_dataset_id, canonical_manifest_sha256,
            canonical_fixtures_sha256
        ) REFERENCES football.canonical_dataset (
            dataset_id, manifest_sha256, fixtures_sha256
        )
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_feature_dataset_predictors FOREIGN KEY (
            predictor_schema_id, predictor_schema_version
        ) REFERENCES feature.predictor_schema (schema_id, schema_version)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_feature_dataset_policy FOREIGN KEY (
            processing_policy_sha256
        ) REFERENCES feature.processing_policy (policy_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_feature_dataset_versions CHECK (
            dataset_schema_version = 2 AND feature_row_schema_version = 2
        ),
        CONSTRAINT ck_feature_dataset_count CHECK (row_count > 0),
        CONSTRAINT ck_feature_dataset_ordering CHECK (
            ordering_contract = 'feature_cutoff_at_kickoff_at_feature_row_id'
        ),
        CONSTRAINT ck_feature_dataset_previous_context CHECK (
            num_nonnulls(
                previous_season_id,
                previous_canonical_dataset_id,
                previous_fixtures_sha256
            ) IN (0, 3)
        )
    )
    """,
    """
    CREATE TABLE feature.feature_row (
        feature_row_id uuid PRIMARY KEY,
        feature_dataset_id text NOT NULL,
        feature_manifest_sha256 persistence.sha256 NOT NULL,
        record_ordinal integer NOT NULL,
        schema_version persistence.positive_version NOT NULL,
        fixture_id uuid NOT NULL,
        canonical_dataset_id text NOT NULL,
        canonical_manifest_sha256 persistence.sha256 NOT NULL,
        canonical_fixtures_sha256 persistence.sha256 NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        home_team_id uuid NOT NULL,
        away_team_id uuid NOT NULL,
        kickoff_at timestamptz NOT NULL,
        kickoff_precision text NOT NULL,
        feature_cutoff_at timestamptz NOT NULL,
        predictor_schema_id text NOT NULL,
        predictor_schema_version persistence.positive_version NOT NULL,
        historical_context_sha256 persistence.sha256 NOT NULL,
        CONSTRAINT uq_feature_row_fixture UNIQUE (
            feature_dataset_id, feature_manifest_sha256, fixture_id
        ),
        CONSTRAINT uq_feature_row_ordinal UNIQUE (
            feature_dataset_id, feature_manifest_sha256, record_ordinal
        ),
        CONSTRAINT uq_feature_row_snapshot UNIQUE (
            feature_row_id, feature_dataset_id, feature_manifest_sha256,
            fixture_id, competition_id, season_id, home_team_id, away_team_id,
            kickoff_at, kickoff_precision, feature_cutoff_at
        ),
        CONSTRAINT fk_feature_row_dataset FOREIGN KEY (
            feature_dataset_id, feature_manifest_sha256, competition_id,
            season_id, canonical_dataset_id, canonical_manifest_sha256,
            predictor_schema_id, predictor_schema_version
        ) REFERENCES feature.feature_dataset (
            dataset_id, manifest_sha256, competition_id, season_id,
            canonical_dataset_id, canonical_manifest_sha256,
            predictor_schema_id, predictor_schema_version
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_feature_row_fixture_revision FOREIGN KEY (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id
        ) REFERENCES football.fixture_revision (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_feature_row_canonical_bytes FOREIGN KEY (
            canonical_dataset_id, canonical_fixtures_sha256
        ) REFERENCES football.canonical_dataset (dataset_id, fixtures_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_feature_row_dataset_canonical_bytes FOREIGN KEY (
            feature_dataset_id, feature_manifest_sha256,
            canonical_fixtures_sha256
        ) REFERENCES feature.feature_dataset (
            dataset_id, manifest_sha256, canonical_fixtures_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_feature_row_fixture_identity FOREIGN KEY (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) REFERENCES football.fixture (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_feature_row_predictor_schema FOREIGN KEY (
            predictor_schema_id, predictor_schema_version
        ) REFERENCES feature.predictor_schema (schema_id, schema_version)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_feature_row_ordinal CHECK (record_ordinal >= 0),
        CONSTRAINT ck_feature_row_schema_version CHECK (schema_version = 2),
        CONSTRAINT ck_feature_row_teams_differ CHECK (
            home_team_id <> away_team_id
        ),
        CONSTRAINT ck_feature_row_precision CHECK (
            kickoff_precision IN ('exact', 'date_only')
        ),
        CONSTRAINT ck_feature_row_cutoff CHECK (
            (kickoff_precision = 'exact' AND feature_cutoff_at <= kickoff_at)
            OR
            (
                kickoff_precision = 'date_only'
                AND competition_id = 'eng-premier-league'
                AND feature_cutoff_at < (
                    ((kickoff_at AT TIME ZONE 'Europe/London')::date)::timestamp
                    AT TIME ZONE 'Europe/London'
                )
            )
        ),
        CONSTRAINT ck_feature_row_deterministic_id CHECK (
            feature_row_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:feature-row:' || schema_version::text
                || '|' || fixture_id::text
                || '|' || persistence.utc_iso8601(feature_cutoff_at)
                || '|' || predictor_schema_id
                || '|' || predictor_schema_version::text
                || '|' || canonical_dataset_id
                || '|' || canonical_fixtures_sha256
                || '|' || historical_context_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE feature.feature_value (
        feature_row_id uuid NOT NULL,
        predictor_ordinal integer NOT NULL,
        predictor_schema_id text NOT NULL,
        predictor_schema_version persistence.positive_version NOT NULL,
        value_kind text NOT NULL,
        boolean_value boolean,
        integer_value bigint,
        float64_value persistence.finite_float64,
        PRIMARY KEY (feature_row_id, predictor_ordinal),
        CONSTRAINT fk_feature_value_row FOREIGN KEY (feature_row_id)
            REFERENCES feature.feature_row (feature_row_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_feature_value_definition FOREIGN KEY (
            predictor_schema_id, predictor_schema_version, predictor_ordinal
        ) REFERENCES feature.predictor_definition (
            schema_id, schema_version, ordinal
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_feature_value_ordinal CHECK (predictor_ordinal >= 0),
        CONSTRAINT ck_feature_value_kind CHECK (
            (value_kind = 'null' AND num_nonnulls(
                boolean_value, integer_value, float64_value
            ) = 0)
            OR
            (value_kind = 'boolean' AND boolean_value IS NOT NULL
                AND num_nonnulls(integer_value, float64_value) = 0)
            OR
            (value_kind = 'integer' AND integer_value IS NOT NULL
                AND num_nonnulls(boolean_value, float64_value) = 0)
            OR
            (value_kind = 'float64' AND float64_value IS NOT NULL
                AND num_nonnulls(boolean_value, integer_value) = 0)
        )
    )
    """,
    """
    CREATE TABLE feature.feature_label (
        feature_row_id uuid PRIMARY KEY,
        outcome text NOT NULL,
        home_goals smallint NOT NULL,
        away_goals smallint NOT NULL,
        CONSTRAINT fk_feature_label_row FOREIGN KEY (feature_row_id)
            REFERENCES feature.feature_row (feature_row_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_feature_label_goals CHECK (
            home_goals >= 0 AND away_goals >= 0
        ),
        CONSTRAINT ck_feature_label_outcome CHECK (
            outcome = CASE
                WHEN home_goals > away_goals THEN 'home_win'
                WHEN home_goals < away_goals THEN 'away_win'
                ELSE 'draw'
            END
        )
    )
    """,
    """
    CREATE TABLE feature.elo_rating_observation (
        feature_dataset_id text NOT NULL,
        feature_manifest_sha256 persistence.sha256 NOT NULL,
        batch_ordinal integer NOT NULL,
        team_id uuid NOT NULL,
        elo_schema_version persistence.positive_version NOT NULL,
        canonical_dataset_id text NOT NULL,
        canonical_manifest_sha256 persistence.sha256 NOT NULL,
        policy_sha256 persistence.sha256 NOT NULL,
        pre_batch_rating persistence.finite_float64 NOT NULL,
        PRIMARY KEY (
            feature_dataset_id, feature_manifest_sha256, batch_ordinal,
            team_id, elo_schema_version
        ),
        CONSTRAINT fk_elo_observation_dataset FOREIGN KEY (
            feature_dataset_id, feature_manifest_sha256
        ) REFERENCES feature.feature_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_elo_observation_batch FOREIGN KEY (
            canonical_dataset_id, canonical_manifest_sha256, batch_ordinal
        ) REFERENCES football.fixture_batch (
            canonical_dataset_id, canonical_manifest_sha256, batch_ordinal
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_elo_observation_team FOREIGN KEY (team_id)
            REFERENCES identity.team (team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_elo_observation_policy FOREIGN KEY (policy_sha256)
            REFERENCES feature.processing_policy (policy_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_elo_observation_version CHECK (elo_schema_version = 1),
        CONSTRAINT ck_elo_observation_ordinal CHECK (batch_ordinal >= 0)
    )
    """,
    """
    CREATE TABLE model.semantic_model (
        model_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        specification_version persistence.positive_version NOT NULL,
        competition_id text NOT NULL,
        training_dataset_id text NOT NULL,
        training_manifest_sha256 persistence.sha256 NOT NULL,
        assessment_manifest_sha256 persistence.sha256 NOT NULL,
        untouched_test_freeze_id text NOT NULL,
        untouched_test_manifest_sha256 persistence.sha256 NOT NULL,
        predictor_schema_id text NOT NULL,
        predictor_schema_version persistence.positive_version NOT NULL,
        CONSTRAINT fk_semantic_model_competition FOREIGN KEY (competition_id)
            REFERENCES identity.competition (competition_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_semantic_model_predictors FOREIGN KEY (
            predictor_schema_id, predictor_schema_version
        ) REFERENCES feature.predictor_schema (schema_id, schema_version)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_semantic_model_version CHECK (specification_version = 1),
        CONSTRAINT ck_semantic_model_deterministic_id CHECK (
            model_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:model-artifact:model:' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE model.classifier_specification (
        model_id uuid PRIMARY KEY,
        family text NOT NULL,
        method_version persistence.positive_version NOT NULL,
        configuration_id text NOT NULL,
        iterations smallint NOT NULL,
        depth smallint NOT NULL,
        learning_rate persistence.finite_float64 NOT NULL,
        l2_leaf_reg persistence.finite_float64 NOT NULL,
        loss_function text NOT NULL,
        random_seed integer NOT NULL,
        bootstrap_type text NOT NULL,
        random_strength persistence.finite_float64 NOT NULL,
        grow_policy text NOT NULL,
        nan_mode text NOT NULL,
        CONSTRAINT fk_classifier_specification_model FOREIGN KEY (model_id)
            REFERENCES model.semantic_model (model_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_classifier_specification_v1 CHECK (
            family = 'catboost_multiclass' AND method_version = 1
            AND configuration_id = 'catboost-depth6-regularized'
            AND iterations = 200 AND depth = 6 AND learning_rate = 0.05
            AND l2_leaf_reg = 10.0 AND loss_function = 'MultiClass'
            AND random_seed = 20260912 AND bootstrap_type = 'No'
            AND random_strength = 0.0 AND grow_policy = 'SymmetricTree'
            AND nan_mode = 'Min'
        )
    )
    """,
    """
    CREATE TABLE model.preprocessing_specification (
        model_id uuid PRIMARY KEY,
        schema_version persistence.positive_version NOT NULL,
        strategy text NOT NULL,
        predictor_order text NOT NULL,
        boolean_false_value persistence.finite_float64 NOT NULL,
        boolean_true_value persistence.finite_float64 NOT NULL,
        numeric_dtype text NOT NULL,
        null_strategy text NOT NULL,
        learned_imputation boolean NOT NULL,
        learned_scaling boolean NOT NULL,
        CONSTRAINT fk_preprocessing_specification_model FOREIGN KEY (model_id)
            REFERENCES model.semantic_model (model_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_preprocessing_specification_v1 CHECK (
            schema_version = 1 AND strategy = 'ordered_numeric_matrix'
            AND predictor_order = 'manifest_exact'
            AND boolean_false_value = 0.0 AND boolean_true_value = 1.0
            AND numeric_dtype = 'numpy_float64' AND null_strategy = 'numpy_nan'
            AND NOT learned_imputation AND NOT learned_scaling
        )
    )
    """,
    """
    CREATE TABLE model.calibration_specification (
        model_id uuid PRIMARY KEY,
        schema_version persistence.positive_version NOT NULL,
        strategy text NOT NULL,
        parameter_count smallint NOT NULL,
        has_component boolean NOT NULL,
        CONSTRAINT fk_calibration_specification_model FOREIGN KEY (model_id)
            REFERENCES model.semantic_model (model_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_calibration_specification_v1 CHECK (
            schema_version = 1 AND strategy = 'identity'
            AND parameter_count = 0 AND NOT has_component
        )
    )
    """,
    """
    CREATE TABLE model.score_model_specification (
        model_id uuid PRIMARY KEY,
        schema_version persistence.positive_version NOT NULL,
        status text NOT NULL,
        has_component boolean NOT NULL,
        produces_scorelines boolean NOT NULL,
        reason text NOT NULL,
        CONSTRAINT fk_score_model_specification_model FOREIGN KEY (model_id)
            REFERENCES model.semantic_model (model_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_score_model_specification_v1 CHECK (
            schema_version = 1 AND status = 'not_included'
            AND NOT has_component AND NOT produces_scorelines
            AND reason = 'no_score_model_selected_for_this_artifact'
        )
    )
    """,
    """
    CREATE TABLE model.prediction_contract (
        model_id uuid PRIMARY KEY,
        schema_version persistence.positive_version NOT NULL,
        task text NOT NULL,
        outcome_ordinal_1 text NOT NULL,
        outcome_ordinal_2 text NOT NULL,
        outcome_ordinal_3 text NOT NULL,
        probability_tolerance persistence.finite_float64 NOT NULL,
        produces_scorelines boolean NOT NULL,
        CONSTRAINT fk_prediction_contract_model FOREIGN KEY (model_id)
            REFERENCES model.semantic_model (model_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_prediction_contract_v1 CHECK (
            schema_version = 1
            AND task = 'full_time_three_way_outcome_probability'
            AND outcome_ordinal_1 = 'home_win'
            AND outcome_ordinal_2 = 'draw'
            AND outcome_ordinal_3 = 'away_win'
            AND probability_tolerance = 1e-12
            AND NOT produces_scorelines
        )
    )
    """,
    """
    CREATE TABLE model.runtime_requirement (
        model_id uuid PRIMARY KEY,
        schema_version persistence.positive_version NOT NULL,
        implementation text NOT NULL,
        python_version text NOT NULL,
        architecture_bits smallint NOT NULL,
        catboost_version text NOT NULL,
        numpy_version text NOT NULL,
        pydantic_version text NOT NULL,
        tzdata_version text NOT NULL,
        numerical_dtype text NOT NULL,
        compute_device text NOT NULL,
        thread_count smallint NOT NULL,
        predictor_schema_id text NOT NULL,
        predictor_schema_version persistence.positive_version NOT NULL,
        predictor_names_sha256 persistence.sha256 NOT NULL,
        CONSTRAINT fk_runtime_requirement_model FOREIGN KEY (model_id)
            REFERENCES model.semantic_model (model_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_runtime_requirement_predictors FOREIGN KEY (
            predictor_schema_id, predictor_schema_version,
            predictor_names_sha256
        ) REFERENCES feature.predictor_schema (
            schema_id, schema_version, ordered_names_sha256
        )
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_runtime_requirement_v1 CHECK (
            schema_version = 1 AND implementation = 'CPython'
            AND python_version = '3.14.7' AND architecture_bits = 64
            AND catboost_version = '1.2.10' AND numpy_version = '2.5.3'
            AND pydantic_version = '2.13.5' AND tzdata_version = '2026.3'
            AND numerical_dtype = 'float64' AND compute_device = 'CPU'
            AND thread_count = 1 AND predictor_schema_id = 'epl-pre-match'
            AND predictor_schema_version = 2
        )
    )
    """,
    """
    CREATE TABLE model.model_artifact (
        artifact_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        model_id uuid NOT NULL,
        layout_version persistence.positive_version NOT NULL,
        component_identity_sha256 persistence.sha256 NOT NULL,
        CONSTRAINT uq_model_artifact_snapshot UNIQUE (artifact_id, model_id),
        CONSTRAINT fk_model_artifact_model FOREIGN KEY (model_id)
            REFERENCES model.semantic_model (model_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_model_artifact_layout CHECK (layout_version = 1),
        CONSTRAINT ck_model_artifact_deterministic_id CHECK (
            artifact_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:model-artifact:artifact:' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE model.artifact_manifest (
        manifest_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        artifact_id uuid NOT NULL UNIQUE,
        manifest_sha256 persistence.sha256 NOT NULL UNIQUE,
        CONSTRAINT uq_artifact_manifest_snapshot UNIQUE (
            manifest_id, artifact_id, manifest_sha256
        ),
        CONSTRAINT fk_artifact_manifest_artifact FOREIGN KEY (artifact_id)
            REFERENCES model.model_artifact (artifact_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_artifact_manifest_object FOREIGN KEY (manifest_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_artifact_manifest_deterministic_id CHECK (
            manifest_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:model-artifact:manifest:' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE model.artifact_component (
        component_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        artifact_id uuid NOT NULL,
        ordinal smallint NOT NULL,
        role text NOT NULL,
        relative_path text NOT NULL,
        format_id text NOT NULL,
        media_type text NOT NULL,
        required boolean NOT NULL,
        byte_count bigint NOT NULL,
        component_sha256 persistence.sha256 NOT NULL,
        CONSTRAINT uq_artifact_component_ordinal UNIQUE (artifact_id, ordinal),
        CONSTRAINT uq_artifact_component_role UNIQUE (artifact_id, role),
        CONSTRAINT uq_artifact_component_path UNIQUE (artifact_id, relative_path),
        CONSTRAINT fk_artifact_component_artifact FOREIGN KEY (artifact_id)
            REFERENCES model.model_artifact (artifact_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_artifact_component_object FOREIGN KEY (component_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_artifact_component_deterministic_id CHECK (
            component_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:model-artifact:component:' || identity_sha256
            )
        ),
        CONSTRAINT ck_artifact_component_path CHECK (
            relative_path !~ '(^/|\\\\|(^|/)[.][.](/|$))'
        ),
        CONSTRAINT ck_artifact_component_v1 CHECK (
            required AND media_type = 'application/json' AND byte_count > 0
            AND (
                (ordinal = 1 AND role = 'preprocessor'
                    AND relative_path = 'components/preprocessor.json'
                    AND format_id = 'pl-platform-ordered-numeric-preprocessor-json')
                OR
                (ordinal = 2 AND role = 'classifier'
                    AND relative_path = 'components/classifier.json'
                    AND format_id = 'catboost-json')
            )
        )
    )
    """,
    """
    CREATE TABLE registry.registry_entry (
        entry_id uuid PRIMARY KEY,
        schema_version persistence.positive_version NOT NULL,
        model_id uuid NOT NULL UNIQUE,
        artifact_id uuid NOT NULL UNIQUE,
        manifest_id uuid NOT NULL UNIQUE,
        manifest_relative_path text NOT NULL,
        artifact_manifest_sha256 persistence.sha256 NOT NULL UNIQUE,
        entry_sha256 persistence.sha256 NOT NULL UNIQUE,
        CONSTRAINT fk_registry_entry_model FOREIGN KEY (model_id)
            REFERENCES model.semantic_model (model_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_registry_entry_artifact FOREIGN KEY (artifact_id)
            REFERENCES model.model_artifact (artifact_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_registry_entry_artifact_model FOREIGN KEY (
            artifact_id, model_id
        ) REFERENCES model.model_artifact (artifact_id, model_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_registry_entry_manifest FOREIGN KEY (manifest_id)
            REFERENCES model.artifact_manifest (manifest_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_registry_entry_manifest_snapshot FOREIGN KEY (
            manifest_id, artifact_id, artifact_manifest_sha256
        ) REFERENCES model.artifact_manifest (
            manifest_id, artifact_id, manifest_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_registry_entry_manifest_object FOREIGN KEY (
            artifact_manifest_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_registry_entry_object FOREIGN KEY (entry_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_registry_entry_v1 CHECK (schema_version = 1),
        CONSTRAINT ck_registry_entry_path CHECK (
            manifest_relative_path !~ '(^/|\\\\|(^|/)[.][.](/|$))'
        ),
        CONSTRAINT ck_registry_entry_deterministic_id CHECK (
            entry_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:model-registry:entry:1|' || artifact_id::text
                || '|' || artifact_manifest_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE registry.registry_event (
        event_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        entry_id uuid NOT NULL,
        sequence integer NOT NULL,
        event_sha256 persistence.sha256 NOT NULL UNIQUE,
        previous_event_id uuid,
        previous_event_sha256 persistence.sha256,
        action text NOT NULL,
        from_state text,
        to_state text NOT NULL,
        artifact_manifest_sha256 persistence.sha256 NOT NULL,
        assessment_manifest_sha256 persistence.sha256,
        rejection_reason text,
        CONSTRAINT uq_registry_event_sequence UNIQUE (entry_id, sequence),
        CONSTRAINT uq_registry_event_entry_event UNIQUE (entry_id, event_id),
        CONSTRAINT fk_registry_event_entry FOREIGN KEY (entry_id)
            REFERENCES registry.registry_entry (entry_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_registry_event_object FOREIGN KEY (event_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_registry_event_previous FOREIGN KEY (
            entry_id, previous_event_id
        ) REFERENCES registry.registry_event (entry_id, event_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_registry_event_sequence CHECK (sequence > 0),
        CONSTRAINT ck_registry_event_action CHECK (action IN (
            'register', 'accept_development', 'reject', 'activate', 'retire'
        )),
        CONSTRAINT ck_registry_event_state CHECK (
            (from_state IS NULL OR from_state IN (
                'candidate', 'development_accepted', 'rejected',
                'active', 'retired'
            ))
            AND to_state IN (
                'candidate', 'development_accepted', 'rejected',
                'active', 'retired'
            )
        ),
        CONSTRAINT ck_registry_event_payload CHECK (
            (action = 'register' AND sequence = 1 AND from_state IS NULL
                AND to_state = 'candidate' AND previous_event_id IS NULL
                AND previous_event_sha256 IS NULL
                AND assessment_manifest_sha256 IS NULL
                AND rejection_reason IS NULL)
            OR
            (action = 'accept_development' AND sequence > 1
                AND from_state = 'candidate'
                AND to_state = 'development_accepted'
                AND previous_event_id IS NOT NULL
                AND previous_event_sha256 IS NOT NULL
                AND assessment_manifest_sha256 IS NOT NULL
                AND rejection_reason IS NULL)
            OR
            (action = 'reject' AND sequence > 1
                AND from_state IN ('candidate', 'development_accepted')
                AND to_state = 'rejected'
                AND previous_event_id IS NOT NULL
                AND previous_event_sha256 IS NOT NULL
                AND assessment_manifest_sha256 IS NULL
                AND length(btrim(rejection_reason)) > 0)
        ),
        CONSTRAINT ck_registry_event_final_test_evidence_required CHECK (
            action <> 'activate' AND to_state <> 'active'
        ),
        CONSTRAINT ck_registry_event_no_retirement_v1 CHECK (
            action <> 'retire' AND to_state <> 'retired'
        ),
        CONSTRAINT ck_registry_event_deterministic_id CHECK (
            event_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:model-registry:event:' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE FUNCTION feature.validate_predictor_definitions()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        definition_count integer;
        minimum_ordinal integer;
        maximum_ordinal integer;
    BEGIN
        SELECT count(*), min(ordinal), max(ordinal)
          INTO definition_count, minimum_ordinal, maximum_ordinal
          FROM feature.predictor_definition
         WHERE schema_id = NEW.schema_id AND schema_version = NEW.schema_version;
        IF definition_count <> 175 OR minimum_ordinal <> 0
           OR maximum_ordinal <> 174 THEN
            RAISE EXCEPTION 'predictor_schema_incompatible: incomplete definitions'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER predictor_definitions_from_schema
    AFTER INSERT ON feature.predictor_schema
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION feature.validate_predictor_definitions()
    """,
    """
    CREATE CONSTRAINT TRIGGER predictor_definitions_from_definition
    AFTER INSERT ON feature.predictor_definition
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION feature.validate_predictor_definitions()
    """,
    """
    CREATE FUNCTION feature.validate_predictor_population()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        row_id uuid;
        expected_count integer;
        actual_count integer;
        minimum_ordinal integer;
        maximum_ordinal integer;
        mismatched_count integer;
    BEGIN
        row_id := NEW.feature_row_id;
        SELECT ps.predictor_count
          INTO expected_count
          FROM feature.feature_row fr
          JOIN feature.predictor_schema ps
            ON ps.schema_id = fr.predictor_schema_id
           AND ps.schema_version = fr.predictor_schema_version
         WHERE fr.feature_row_id = row_id;
        SELECT count(*), min(predictor_ordinal), max(predictor_ordinal),
               count(*) FILTER (
                   WHERE fv.predictor_schema_id <> fr.predictor_schema_id
                      OR fv.predictor_schema_version <> fr.predictor_schema_version
               )
          INTO actual_count, minimum_ordinal, maximum_ordinal, mismatched_count
          FROM feature.feature_value fv
          JOIN feature.feature_row fr ON fr.feature_row_id = fv.feature_row_id
         WHERE fv.feature_row_id = row_id;
        IF actual_count <> expected_count OR minimum_ordinal <> 0
           OR maximum_ordinal <> expected_count - 1 OR mismatched_count <> 0 THEN
            RAISE EXCEPTION 'predictor_schema_incompatible: %', row_id
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER feature_values_complete_from_row
    AFTER INSERT ON feature.feature_row
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION feature.validate_predictor_population()
    """,
    """
    CREATE CONSTRAINT TRIGGER feature_values_complete_from_value
    AFTER INSERT ON feature.feature_value
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION feature.validate_predictor_population()
    """,
    """
    CREATE FUNCTION model.validate_model_children()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        child_count integer;
    BEGIN
        SELECT
            (SELECT count(*) FROM model.classifier_specification
              WHERE model_id = NEW.model_id)
          + (SELECT count(*) FROM model.preprocessing_specification
              WHERE model_id = NEW.model_id)
          + (SELECT count(*) FROM model.calibration_specification
              WHERE model_id = NEW.model_id)
          + (SELECT count(*) FROM model.score_model_specification
              WHERE model_id = NEW.model_id)
          + (SELECT count(*) FROM model.prediction_contract
              WHERE model_id = NEW.model_id)
          + (SELECT count(*) FROM model.runtime_requirement
              WHERE model_id = NEW.model_id)
          INTO child_count;
        IF child_count <> 6 THEN
            RAISE EXCEPTION 'model_contract_incomplete: %', NEW.model_id
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER model_children_complete
    AFTER INSERT ON model.semantic_model
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION model.validate_model_children()
    """,
    """
    CREATE FUNCTION model.validate_artifact_components()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        component_count integer;
        mismatched_count integer;
    BEGIN
        SELECT count(*), count(*) FILTER (
            WHERE c.byte_count <> o.byte_count
               OR c.media_type <> o.media_type OR c.format_id <> o.format_id
        ) INTO component_count, mismatched_count
          FROM model.artifact_component c
          JOIN lineage.stored_object o ON o.sha256 = c.component_sha256
         WHERE c.artifact_id = NEW.artifact_id;
        IF component_count <> 2 OR mismatched_count <> 0 THEN
            RAISE EXCEPTION 'artifact_component_incomplete: %', NEW.artifact_id
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER artifact_components_complete_from_artifact
    AFTER INSERT ON model.model_artifact
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION model.validate_artifact_components()
    """,
    """
    CREATE CONSTRAINT TRIGGER artifact_components_complete_from_component
    AFTER INSERT ON model.artifact_component
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION model.validate_artifact_components()
    """,
    """
    CREATE FUNCTION registry.validate_event_chain()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        first_event registry.registry_event%ROWTYPE;
        current_event registry.registry_event%ROWTYPE;
        previous_event registry.registry_event%ROWTYPE;
        event_count integer;
        maximum_sequence integer;
    BEGIN
        SELECT count(*), max(sequence) INTO event_count, maximum_sequence
          FROM registry.registry_event WHERE entry_id = NEW.entry_id;
        IF event_count = 0 OR maximum_sequence <> event_count THEN
            RAISE EXCEPTION 'registry_transition_invalid: gap for %', NEW.entry_id
                USING ERRCODE = '23514';
        END IF;
        SELECT * INTO first_event FROM registry.registry_event
         WHERE entry_id = NEW.entry_id AND sequence = 1;
        IF first_event.action <> 'register' OR first_event.from_state IS NOT NULL
           OR first_event.to_state <> 'candidate' THEN
            RAISE EXCEPTION 'registry_transition_invalid: first event for %',
                NEW.entry_id USING ERRCODE = '23514';
        END IF;
        FOR current_event IN
            SELECT * FROM registry.registry_event
             WHERE entry_id = NEW.entry_id AND sequence > 1 ORDER BY sequence
        LOOP
            SELECT * INTO previous_event FROM registry.registry_event
             WHERE entry_id = NEW.entry_id
               AND sequence = current_event.sequence - 1;
            IF current_event.previous_event_id <> previous_event.event_id
               OR current_event.previous_event_sha256 <> previous_event.event_sha256
               OR current_event.from_state <> previous_event.to_state
               OR previous_event.to_state = 'rejected' THEN
                RAISE EXCEPTION 'registry_transition_invalid: chain for %',
                    NEW.entry_id USING ERRCODE = '23514';
            END IF;
        END LOOP;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER registry_chain_from_entry
    AFTER INSERT ON registry.registry_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION registry.validate_event_chain()
    """,
    """
    CREATE CONSTRAINT TRIGGER registry_chain_from_event
    AFTER INSERT ON registry.registry_event
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION registry.validate_event_chain()
    """,
    """
    CREATE VIEW registry.current_state AS
    SELECT DISTINCT ON (entry_id)
        entry_id, event_id, sequence, to_state AS state, event_sha256
      FROM registry.registry_event
     ORDER BY entry_id, sequence DESC
    """,
)


IMMUTABLE_TABLES: tuple[tuple[str, str], ...] = (
    ("feature", "predictor_schema"),
    ("feature", "predictor_definition"),
    ("feature", "processing_policy"),
    ("feature", "feature_dataset"),
    ("feature", "feature_row"),
    ("feature", "feature_value"),
    ("feature", "feature_label"),
    ("feature", "elo_rating_observation"),
    ("model", "semantic_model"),
    ("model", "classifier_specification"),
    ("model", "preprocessing_specification"),
    ("model", "calibration_specification"),
    ("model", "score_model_specification"),
    ("model", "prediction_contract"),
    ("model", "runtime_requirement"),
    ("model", "model_artifact"),
    ("model", "artifact_manifest"),
    ("model", "artifact_component"),
    ("registry", "registry_entry"),
    ("registry", "registry_event"),
)


def upgrade() -> None:
    """Create feature, model-artifact and append-only registry structures."""

    for statement in DDL:
        op.execute(sa.text(statement))
    for schema, table in IMMUTABLE_TABLES:
        op.execute(
            sa.text(
                f"CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE "
                f"ON {schema}.{table} FOR EACH ROW EXECUTE FUNCTION "
                "persistence.reject_immutable_mutation()"
            )
        )


def downgrade() -> None:
    """Remove Step 5.5 feature, model and registry schemas."""

    op.execute(sa.text("DROP SCHEMA registry CASCADE"))
    op.execute(sa.text("DROP SCHEMA model CASCADE"))
    op.execute(sa.text("DROP SCHEMA feature CASCADE"))
