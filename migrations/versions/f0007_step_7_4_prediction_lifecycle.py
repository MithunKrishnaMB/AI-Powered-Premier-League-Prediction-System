"""Add upcoming features, immutable predictions and completed evaluation.

Revision ID: f0007_step_7_4
Revises: f0006_step_6_8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0007_step_7_4"
down_revision: str | Sequence[str] | None = "f0006_step_6_8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DDL: tuple[str, ...] = (
    "CREATE SCHEMA prediction",
    """
    ALTER TABLE football.current_fixture_revision
      ADD CONSTRAINT uq_current_fixture_revision_lineage UNIQUE (
          revision_id, identity_sha256, fixture_id
      )
    """,
    """
    ALTER TABLE football.current_fixture_observation
      ADD CONSTRAINT uq_current_fixture_observation_lineage UNIQUE (
          observation_id, fixture_id, revision_id, cache_key_sha256
      )
    """,
    """
    ALTER TABLE football.current_fixture_batch
      ADD CONSTRAINT uq_current_fixture_batch_lineage UNIQUE (
          batch_id, identity_sha256, knowledge_available_at
      )
    """,
    """
    ALTER TABLE football.current_fixture_batch_member
      ADD CONSTRAINT uq_current_fixture_batch_member_lineage UNIQUE (
          batch_id, member_ordinal, fixture_id, revision_id
      )
    """,
    """
    ALTER TABLE football.current_completed_result
      ADD CONSTRAINT uq_current_completed_result_lineage UNIQUE (
          result_id, identity_sha256, fixture_id
      )
    """,
    """
    ALTER TABLE football.current_result_observation
      ADD CONSTRAINT uq_current_result_observation_lineage UNIQUE (
          observation_id, result_id, fixture_id, cache_key_sha256, retrieved_at
      )
    """,
    """
    ALTER TABLE registry.registry_entry
      ADD CONSTRAINT uq_registry_entry_prediction_lineage UNIQUE (
          entry_id, model_id, artifact_id, manifest_id,
          artifact_manifest_sha256
      )
    """,
    """
    ALTER TABLE registry.registry_event
      ADD CONSTRAINT uq_registry_event_prediction_lineage UNIQUE (
          entry_id, event_id, event_sha256
      )
    """,
    """
    CREATE TABLE prediction.upcoming_feature (
        feature_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        feature_object_sha256 persistence.sha256 NOT NULL UNIQUE,
        schema_version persistence.positive_version NOT NULL,
        fixture_id uuid NOT NULL,
        fixture_revision_id uuid NOT NULL,
        fixture_revision_identity_sha256 persistence.sha256 NOT NULL,
        fixture_observation_id uuid NOT NULL,
        fixture_cache_key_sha256 persistence.sha256 NOT NULL,
        fixture_batch_id uuid NOT NULL,
        fixture_batch_identity_sha256 persistence.sha256 NOT NULL,
        fixture_batch_member_ordinal integer NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        home_team_id uuid NOT NULL,
        away_team_id uuid NOT NULL,
        kickoff_at timestamptz NOT NULL,
        kickoff_precision text NOT NULL,
        feature_cutoff_at timestamptz NOT NULL,
        predictor_schema_id text NOT NULL,
        predictor_schema_version persistence.positive_version NOT NULL,
        predictor_payload_sha256 persistence.sha256 NOT NULL,
        completed_state_sha256 persistence.sha256 NOT NULL,
        historical_context_sha256 persistence.sha256 NOT NULL,
        opening_priors_sha256 persistence.sha256 NOT NULL,
        initial_elo_sha256 persistence.sha256 NOT NULL,
        CONSTRAINT uq_upcoming_feature_snapshot UNIQUE (
            feature_id, identity_sha256, fixture_id, competition_id, season_id,
            home_team_id, away_team_id, kickoff_at, feature_cutoff_at
        ),
        CONSTRAINT fk_upcoming_feature_identity FOREIGN KEY (identity_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_feature_object FOREIGN KEY (feature_object_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_feature_fixture FOREIGN KEY (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) REFERENCES football.fixture (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_feature_revision FOREIGN KEY (
            fixture_revision_id, fixture_revision_identity_sha256, fixture_id
        ) REFERENCES football.current_fixture_revision (
            revision_id, identity_sha256, fixture_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_feature_observation FOREIGN KEY (
            fixture_observation_id, fixture_id, fixture_revision_id,
            fixture_cache_key_sha256
        ) REFERENCES football.current_fixture_observation (
            observation_id, fixture_id, revision_id, cache_key_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_feature_batch FOREIGN KEY (
            fixture_batch_id, fixture_batch_identity_sha256,
            feature_cutoff_at
        ) REFERENCES football.current_fixture_batch (
            batch_id, identity_sha256, knowledge_available_at
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_feature_member FOREIGN KEY (
            fixture_batch_id, fixture_batch_member_ordinal,
            fixture_id, fixture_revision_id
        ) REFERENCES football.current_fixture_batch_member (
            batch_id, member_ordinal, fixture_id, revision_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_feature_predictors FOREIGN KEY (
            predictor_schema_id, predictor_schema_version
        ) REFERENCES feature.predictor_schema (schema_id, schema_version)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_feature_predictor_object FOREIGN KEY (
            predictor_payload_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_feature_state_object FOREIGN KEY (
            completed_state_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_feature_prior_object FOREIGN KEY (
            opening_priors_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_feature_elo_object FOREIGN KEY (
            initial_elo_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_upcoming_feature_v1 CHECK (
            schema_version = 1 AND predictor_schema_id = 'epl-pre-match'
            AND predictor_schema_version = 2
            AND season_id <> '2025-2026'
            AND kickoff_precision IN ('exact', 'date_only')
            AND (
                (kickoff_precision = 'exact' AND feature_cutoff_at < kickoff_at)
                OR (kickoff_precision = 'date_only' AND feature_cutoff_at < (
                    ((kickoff_at AT TIME ZONE 'Europe/London')::date)::timestamp
                    AT TIME ZONE 'Europe/London'
                ))
            )
            AND fixture_batch_member_ordinal >= 0
            AND feature_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:upcoming-feature:1|' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE prediction.upcoming_feature_result_source (
        feature_id uuid NOT NULL,
        ordinal integer NOT NULL,
        result_id uuid NOT NULL,
        result_identity_sha256 persistence.sha256 NOT NULL,
        fixture_id uuid NOT NULL,
        result_observation_id uuid NOT NULL,
        cache_key_sha256 persistence.sha256 NOT NULL,
        retrieved_at timestamptz NOT NULL,
        PRIMARY KEY (feature_id, ordinal),
        CONSTRAINT uq_upcoming_result_source UNIQUE (feature_id, result_id),
        CONSTRAINT fk_upcoming_result_source_feature FOREIGN KEY (feature_id)
            REFERENCES prediction.upcoming_feature (feature_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_result_source_result FOREIGN KEY (
            result_id, result_identity_sha256, fixture_id
        ) REFERENCES football.current_completed_result (
            result_id, identity_sha256, fixture_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_result_source_observation FOREIGN KEY (
            result_observation_id, result_id, fixture_id,
            cache_key_sha256, retrieved_at
        ) REFERENCES football.current_result_observation (
            observation_id, result_id, fixture_id, cache_key_sha256, retrieved_at
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_upcoming_result_source_ordinal CHECK (ordinal >= 0)
    )
    """,
    """
    CREATE TABLE prediction.upcoming_feature_value (
        feature_id uuid NOT NULL,
        predictor_ordinal integer NOT NULL,
        predictor_schema_id text NOT NULL,
        predictor_schema_version persistence.positive_version NOT NULL,
        value_kind text NOT NULL,
        boolean_value boolean,
        integer_value bigint,
        float64_value persistence.finite_float64,
        PRIMARY KEY (feature_id, predictor_ordinal),
        CONSTRAINT fk_upcoming_feature_value_owner FOREIGN KEY (feature_id)
            REFERENCES prediction.upcoming_feature (feature_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_upcoming_feature_value_definition FOREIGN KEY (
            predictor_schema_id, predictor_schema_version, predictor_ordinal
        ) REFERENCES feature.predictor_definition (
            schema_id, schema_version, ordinal
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_upcoming_feature_value_ordinal CHECK (
            predictor_ordinal >= 0
        ),
        CONSTRAINT ck_upcoming_feature_value_kind CHECK (
            (value_kind = 'null' AND num_nonnulls(
                boolean_value, integer_value, float64_value
            ) = 0)
            OR (value_kind = 'boolean' AND boolean_value IS NOT NULL
                AND num_nonnulls(integer_value, float64_value) = 0)
            OR (value_kind = 'integer' AND integer_value IS NOT NULL
                AND num_nonnulls(boolean_value, float64_value) = 0)
            OR (value_kind = 'float64' AND float64_value IS NOT NULL
                AND num_nonnulls(boolean_value, integer_value) = 0)
        )
    )
    """,
    """
    CREATE TABLE prediction.current_model_prediction (
        prediction_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        prediction_object_sha256 persistence.sha256 NOT NULL UNIQUE,
        schema_version persistence.positive_version NOT NULL,
        feature_id uuid NOT NULL,
        feature_identity_sha256 persistence.sha256 NOT NULL,
        fixture_id uuid NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        home_team_id uuid NOT NULL,
        away_team_id uuid NOT NULL,
        kickoff_at timestamptz NOT NULL,
        feature_cutoff_at timestamptz NOT NULL,
        registry_entry_id uuid NOT NULL,
        registry_head_event_id uuid NOT NULL,
        registry_head_event_sha256 persistence.sha256 NOT NULL,
        model_id uuid NOT NULL,
        artifact_id uuid NOT NULL,
        manifest_id uuid NOT NULL,
        artifact_manifest_sha256 persistence.sha256 NOT NULL,
        method text NOT NULL,
        method_version persistence.positive_version NOT NULL,
        configuration_id text NOT NULL,
        home_win_probability persistence.probability NOT NULL,
        draw_probability persistence.probability NOT NULL,
        away_win_probability persistence.probability NOT NULL,
        CONSTRAINT uq_current_prediction_snapshot UNIQUE (
            prediction_id, identity_sha256, fixture_id, season_id
        ),
        CONSTRAINT uq_current_prediction_lineage UNIQUE (
            feature_id, registry_entry_id, registry_head_event_id
        ),
        CONSTRAINT fk_current_prediction_identity FOREIGN KEY (identity_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_prediction_object FOREIGN KEY (
            prediction_object_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_prediction_feature FOREIGN KEY (
            feature_id, feature_identity_sha256, fixture_id, competition_id,
            season_id, home_team_id, away_team_id, kickoff_at, feature_cutoff_at
        ) REFERENCES prediction.upcoming_feature (
            feature_id, identity_sha256, fixture_id, competition_id,
            season_id, home_team_id, away_team_id, kickoff_at, feature_cutoff_at
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_prediction_registry FOREIGN KEY (
            registry_entry_id, model_id, artifact_id, manifest_id,
            artifact_manifest_sha256
        ) REFERENCES registry.registry_entry (
            entry_id, model_id, artifact_id, manifest_id,
            artifact_manifest_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_prediction_event FOREIGN KEY (
            registry_entry_id, registry_head_event_id,
            registry_head_event_sha256
        ) REFERENCES registry.registry_event (
            entry_id, event_id, event_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_prediction_v1 CHECK (
            schema_version = 1 AND season_id <> '2025-2026'
            AND method = 'catboost' AND method_version = 1
            AND configuration_id = 'catboost-depth6-regularized'
            AND feature_cutoff_at < kickoff_at
            AND abs(home_win_probability + draw_probability
                + away_win_probability - 1.0) <= 1e-12
            AND prediction_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:current-prediction:1|' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE prediction.completed_prediction_evaluation (
        evaluation_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        evaluation_object_sha256 persistence.sha256 NOT NULL UNIQUE,
        schema_version persistence.positive_version NOT NULL,
        prediction_id uuid NOT NULL,
        prediction_identity_sha256 persistence.sha256 NOT NULL,
        result_id uuid NOT NULL,
        result_identity_sha256 persistence.sha256 NOT NULL,
        result_observation_id uuid NOT NULL,
        result_cache_key_sha256 persistence.sha256 NOT NULL,
        result_retrieved_at timestamptz NOT NULL,
        fixture_id uuid NOT NULL,
        season_id text NOT NULL,
        outcome text NOT NULL,
        actual_outcome_probability persistence.probability NOT NULL,
        log_loss persistence.finite_float64 NOT NULL,
        multiclass_brier_score persistence.finite_float64 NOT NULL,
        ranked_probability_score persistence.finite_float64 NOT NULL,
        CONSTRAINT uq_completed_prediction_evaluation UNIQUE (
            prediction_id, result_id
        ),
        CONSTRAINT fk_completed_evaluation_identity FOREIGN KEY (identity_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_completed_evaluation_object FOREIGN KEY (
            evaluation_object_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_completed_evaluation_prediction FOREIGN KEY (
            prediction_id, prediction_identity_sha256, fixture_id, season_id
        ) REFERENCES prediction.current_model_prediction (
            prediction_id, identity_sha256, fixture_id, season_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_completed_evaluation_result FOREIGN KEY (
            result_id, result_identity_sha256, fixture_id
        ) REFERENCES football.current_completed_result (
            result_id, identity_sha256, fixture_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_completed_evaluation_observation FOREIGN KEY (
            result_observation_id, result_id, fixture_id,
            result_cache_key_sha256, result_retrieved_at
        ) REFERENCES football.current_result_observation (
            observation_id, result_id, fixture_id, cache_key_sha256, retrieved_at
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_completed_evaluation_v1 CHECK (
            schema_version = 1 AND season_id <> '2025-2026'
            AND outcome IN ('home_win', 'draw', 'away_win')
            AND actual_outcome_probability > 0.0
            AND log_loss >= 0.0 AND multiclass_brier_score >= 0.0
            AND ranked_probability_score >= 0.0
            AND evaluation_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:completed-prediction-evaluation:1|'
                || identity_sha256
            )
        )
    )
    """,
    """
    CREATE FUNCTION prediction.validate_upcoming_feature()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        expected_count integer;
        actual_count integer;
        bad_values integer;
        bad_results integer;
        result_count integer;
        minimum_result_ordinal integer;
        maximum_result_ordinal integer;
    BEGIN
        SELECT predictor_count INTO expected_count
        FROM feature.predictor_schema
        WHERE schema_id = NEW.predictor_schema_id
          AND schema_version = NEW.predictor_schema_version;
        SELECT count(*), count(*) FILTER (WHERE
                   v.predictor_schema_id <> NEW.predictor_schema_id
                   OR v.predictor_schema_version <> NEW.predictor_schema_version)
          INTO actual_count, bad_values
        FROM prediction.upcoming_feature_value v
        WHERE v.feature_id = NEW.feature_id;
        SELECT count(*), min(ordinal), max(ordinal),
               count(*) FILTER (WHERE retrieved_at > NEW.feature_cutoff_at)
          INTO result_count, minimum_result_ordinal,
               maximum_result_ordinal, bad_results
        FROM prediction.upcoming_feature_result_source s
        WHERE s.feature_id = NEW.feature_id;
        IF expected_count IS NULL OR actual_count <> expected_count
           OR bad_values <> 0 OR bad_results <> 0
           OR (result_count > 0 AND (
               minimum_result_ordinal <> 0
               OR maximum_result_ordinal <> result_count - 1
           )) THEN
            RAISE EXCEPTION 'predictor_schema_incompatible: incomplete upcoming feature'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_upcoming_feature_complete';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_upcoming_feature
    AFTER INSERT ON prediction.upcoming_feature
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION prediction.validate_upcoming_feature()
    """,
    """
    CREATE FUNCTION prediction.validate_active_prediction()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        event_state text;
        event_sequence integer;
        later_events integer;
    BEGIN
        SELECT to_state, sequence INTO event_state, event_sequence
        FROM registry.registry_event
        WHERE entry_id = NEW.registry_entry_id
          AND event_id = NEW.registry_head_event_id
          AND event_sha256 = NEW.registry_head_event_sha256;
        SELECT count(*) INTO later_events FROM registry.registry_event
        WHERE entry_id = NEW.registry_entry_id AND sequence > event_sequence;
        IF event_state IS DISTINCT FROM 'active' OR later_events <> 0 THEN
            RAISE EXCEPTION
                'registry_transition_invalid: prediction model is not active head'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_current_prediction_active_head';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_active_prediction
    AFTER INSERT ON prediction.current_model_prediction
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION prediction.validate_active_prediction()
    """,
    """
    CREATE FUNCTION prediction.validate_completed_evaluation()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        expected_outcome text;
        expected_probability double precision;
        expected_brier double precision;
        expected_ranked double precision;
        home_probability double precision;
        draw_probability double precision;
        away_probability double precision;
        result_retrieved_at timestamptz;
        prediction_cutoff timestamptz;
    BEGIN
        SELECT r.outcome, o.retrieved_at INTO expected_outcome, result_retrieved_at
        FROM football.current_completed_result r
        JOIN football.current_result_observation o
          ON o.result_id = r.result_id AND o.observation_id = NEW.result_observation_id
        WHERE r.result_id = NEW.result_id;
        SELECT feature_cutoff_at,
               CASE expected_outcome
                   WHEN 'home_win' THEN home_win_probability
                   WHEN 'draw' THEN draw_probability
                   ELSE away_win_probability
               END,
               home_win_probability, draw_probability, away_win_probability
          INTO prediction_cutoff, expected_probability,
               home_probability, draw_probability, away_probability
        FROM prediction.current_model_prediction
        WHERE prediction_id = NEW.prediction_id;
        expected_brier :=
            power(home_probability - CASE WHEN expected_outcome = 'home_win'
                THEN 1.0 ELSE 0.0 END, 2)
            + power(draw_probability - CASE WHEN expected_outcome = 'draw'
                THEN 1.0 ELSE 0.0 END, 2)
            + power(away_probability - CASE WHEN expected_outcome = 'away_win'
                THEN 1.0 ELSE 0.0 END, 2);
        expected_ranked := (
            power(home_probability - CASE WHEN expected_outcome = 'home_win'
                THEN 1.0 ELSE 0.0 END, 2)
            + power(home_probability + draw_probability
                - CASE WHEN expected_outcome IN ('home_win', 'draw')
                    THEN 1.0 ELSE 0.0 END, 2)
        ) / 2.0;
        IF expected_outcome IS DISTINCT FROM NEW.outcome
           OR expected_probability IS DISTINCT FROM NEW.actual_outcome_probability
           OR result_retrieved_at <= prediction_cutoff
           OR abs(NEW.log_loss + ln(expected_probability)) > 1e-12
           OR abs(NEW.multiclass_brier_score - expected_brier) > 1e-12
           OR abs(NEW.ranked_probability_score - expected_ranked) > 1e-12 THEN
            RAISE EXCEPTION 'provenance_mismatch: invalid completed evaluation'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_completed_evaluation_consistent';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_completed_evaluation
    AFTER INSERT ON prediction.completed_prediction_evaluation
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION prediction.validate_completed_evaluation()
    """,
)


IMMUTABLE_TABLES: tuple[str, ...] = (
    "upcoming_feature",
    "upcoming_feature_result_source",
    "upcoming_feature_value",
    "current_model_prediction",
    "completed_prediction_evaluation",
)


def upgrade() -> None:
    """Create the immutable prediction lifecycle projection."""

    for statement in DDL:
        op.execute(sa.text(statement))
    for table in IMMUTABLE_TABLES:
        op.execute(
            sa.text(
                "CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE "
                f"ON prediction.{table} FOR EACH ROW EXECUTE FUNCTION "
                "persistence.reject_immutable_mutation()"
            )
        )


def downgrade() -> None:
    """Remove the prediction lifecycle projection."""

    op.execute(sa.text("DROP SCHEMA prediction CASCADE"))
    op.execute(
        sa.text(
            "ALTER TABLE registry.registry_event "
            "DROP CONSTRAINT uq_registry_event_prediction_lineage"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE registry.registry_entry "
            "DROP CONSTRAINT uq_registry_entry_prediction_lineage"
        )
    )
    for table, constraint in (
        ("current_result_observation", "uq_current_result_observation_lineage"),
        ("current_completed_result", "uq_current_completed_result_lineage"),
        ("current_fixture_batch_member", "uq_current_fixture_batch_member_lineage"),
        ("current_fixture_batch", "uq_current_fixture_batch_lineage"),
        ("current_fixture_observation", "uq_current_fixture_observation_lineage"),
        ("current_fixture_revision", "uq_current_fixture_revision_lineage"),
    ):
        op.execute(
            sa.text(f"ALTER TABLE football.{table} DROP CONSTRAINT {constraint}")
        )
