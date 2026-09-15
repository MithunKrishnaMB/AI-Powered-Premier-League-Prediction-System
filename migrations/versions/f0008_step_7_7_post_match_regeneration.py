"""Add append-only state, prediction and simulation regeneration lineage.

Revision ID: f0008_step_7_7
Revises: f0007_step_7_4
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f0008_step_7_7"
down_revision: str | None = "f0007_step_7_4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DDL: tuple[str, ...] = (
    "ALTER TABLE simulation.result_component "
    "DROP CONSTRAINT uq_result_component_object",
    """
    ALTER TABLE prediction.completed_prediction_evaluation
      ADD CONSTRAINT uq_completed_evaluation_advancement_lineage UNIQUE (
          evaluation_id, identity_sha256, fixture_id
      )
    """,
    """
    ALTER TABLE simulation.simulation_run
      ADD CONSTRAINT uq_simulation_run_regeneration_lineage UNIQUE (
          simulation_id, input_sha256, simulation_seed
      )
    """,
    """
    ALTER TABLE simulation.simulation_summary
      ADD CONSTRAINT uq_simulation_summary_regeneration_lineage UNIQUE (
          summary_id, simulation_id
      )
    """,
    """
    CREATE TABLE prediction.operational_team_state (
        state_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        state_object_sha256 persistence.sha256 NOT NULL UNIQUE,
        schema_version persistence.positive_version NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        initial_elo_sha256 persistence.sha256 NOT NULL,
        completed_result_count integer NOT NULL,
        CONSTRAINT uq_operational_team_state_snapshot UNIQUE (
            state_id, identity_sha256, competition_id, season_id
        ),
        CONSTRAINT fk_operational_team_state_identity FOREIGN KEY (identity_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_operational_team_state_object FOREIGN KEY (state_object_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_operational_team_state_initial_elo FOREIGN KEY (
            initial_elo_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_operational_team_state_season FOREIGN KEY (
            competition_id, season_id
        ) REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_operational_team_state_v1 CHECK (
            schema_version = 1 AND competition_id = 'eng-premier-league'
            AND season_id <> '2025-2026'
            AND completed_result_count >= 0
            AND state_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:operational-team-state:1|' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE prediction.operational_team_state_result (
        state_id uuid NOT NULL,
        ordinal integer NOT NULL,
        result_id uuid NOT NULL,
        result_identity_sha256 persistence.sha256 NOT NULL,
        result_observation_id uuid NOT NULL,
        result_cache_key_sha256 persistence.sha256 NOT NULL,
        result_retrieved_at timestamptz NOT NULL,
        fixture_id uuid NOT NULL,
        PRIMARY KEY (state_id, ordinal),
        CONSTRAINT uq_operational_state_result UNIQUE (state_id, result_id),
        CONSTRAINT fk_operational_state_result_owner FOREIGN KEY (state_id)
            REFERENCES prediction.operational_team_state (state_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_operational_state_result_value FOREIGN KEY (
            result_id, result_identity_sha256, fixture_id
        ) REFERENCES football.current_completed_result (
            result_id, identity_sha256, fixture_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_operational_state_result_observation FOREIGN KEY (
            result_observation_id, result_id, fixture_id,
            result_cache_key_sha256, result_retrieved_at
        ) REFERENCES football.current_result_observation (
            observation_id, result_id, fixture_id, cache_key_sha256, retrieved_at
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_operational_state_result_ordinal CHECK (ordinal >= 0)
    )
    """,
    """
    CREATE TABLE prediction.operational_team_state_rating (
        state_id uuid NOT NULL,
        team_id uuid NOT NULL,
        team_ordinal integer NOT NULL,
        elo_rating persistence.finite_float64 NOT NULL,
        PRIMARY KEY (state_id, team_id),
        CONSTRAINT uq_operational_state_rating_ordinal UNIQUE (
            state_id, team_ordinal
        ),
        CONSTRAINT fk_operational_state_rating_owner FOREIGN KEY (state_id)
            REFERENCES prediction.operational_team_state (state_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_operational_state_rating_team FOREIGN KEY (team_id)
            REFERENCES identity.team (team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_operational_state_rating_ordinal CHECK (
            team_ordinal BETWEEN 0 AND 19
        )
    )
    """,
    """
    CREATE FUNCTION prediction.validate_operational_team_state()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        result_total integer;
        result_order_valid boolean;
        rating_total integer;
        rating_order_valid boolean;
        bad_members integer;
    BEGIN
        SELECT count(*), bool_and(ordinal = expected_ordinal)
          INTO result_total, result_order_valid
        FROM (
            SELECT ordinal,
                   row_number() OVER (
                       ORDER BY r.ordinal
                   )::integer - 1 AS expected_ordinal
            FROM prediction.operational_team_state_result r
            WHERE r.state_id = NEW.state_id
        ) ordered_results;
        SELECT count(*), bool_and(team_ordinal = expected_ordinal)
          INTO rating_total, rating_order_valid
        FROM (
            SELECT team_ordinal,
                   row_number() OVER (ORDER BY team_id)::integer - 1
                       AS expected_ordinal
            FROM prediction.operational_team_state_rating r
            WHERE r.state_id = NEW.state_id
        ) ordered_ratings;
        SELECT count(*) INTO bad_members
        FROM prediction.operational_team_state_rating r
        WHERE r.state_id = NEW.state_id AND NOT EXISTS (
            SELECT 1 FROM identity.season_membership m
            WHERE m.competition_id = 'eng-premier-league'
              AND m.season_id = NEW.season_id AND m.team_id = r.team_id
        );
        IF result_total <> NEW.completed_result_count
           OR (result_total > 0 AND NOT coalesce(result_order_valid, false))
           OR rating_total <> 20 OR NOT coalesce(rating_order_valid, false)
           OR bad_members <> 0 THEN
            RAISE EXCEPTION 'state_chain_invalid: incomplete operational team state'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_operational_team_state_complete';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_operational_team_state
    AFTER INSERT ON prediction.operational_team_state
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION prediction.validate_operational_team_state()
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_operational_team_state_result
    AFTER INSERT ON prediction.operational_team_state_result
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION prediction.validate_operational_team_state()
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_operational_team_state_rating
    AFTER INSERT ON prediction.operational_team_state_rating
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION prediction.validate_operational_team_state()
    """,
    """
    CREATE TABLE prediction.team_state_advancement (
        advancement_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        advancement_object_sha256 persistence.sha256 NOT NULL UNIQUE,
        schema_version persistence.positive_version NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        prior_advancement_id uuid,
        pre_state_id uuid NOT NULL,
        pre_state_sha256 persistence.sha256 NOT NULL,
        post_state_id uuid NOT NULL,
        post_state_sha256 persistence.sha256 NOT NULL,
        applied_at timestamptz NOT NULL,
        applied_result_count integer NOT NULL,
        CONSTRAINT uq_team_state_advancement_snapshot UNIQUE (
            advancement_id, identity_sha256, post_state_id
        ),
        CONSTRAINT uq_team_state_advancement_identity_lineage UNIQUE (
            advancement_id, identity_sha256
        ),
        CONSTRAINT uq_team_state_advancement_post_lineage UNIQUE (
            advancement_id, post_state_id
        ),
        CONSTRAINT uq_team_state_advancement_predecessor UNIQUE (
            season_id, pre_state_id
        ),
        CONSTRAINT uq_team_state_advancement_post UNIQUE (
            season_id, post_state_id
        ),
        CONSTRAINT fk_team_state_advancement_identity FOREIGN KEY (identity_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_team_state_advancement_object FOREIGN KEY (
            advancement_object_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_team_state_advancement_pre FOREIGN KEY (
            pre_state_id, pre_state_sha256, competition_id, season_id
        ) REFERENCES prediction.operational_team_state (
            state_id, identity_sha256, competition_id, season_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_team_state_advancement_post FOREIGN KEY (
            post_state_id, post_state_sha256, competition_id, season_id
        ) REFERENCES prediction.operational_team_state (
            state_id, identity_sha256, competition_id, season_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_team_state_advancement_prior FOREIGN KEY (
            prior_advancement_id, pre_state_id
        ) REFERENCES prediction.team_state_advancement (
            advancement_id, post_state_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_team_state_advancement_v1 CHECK (
            schema_version = 1 AND competition_id = 'eng-premier-league'
            AND season_id <> '2025-2026'
            AND pre_state_id <> post_state_id AND applied_result_count > 0
            AND advancement_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:team-state-advancement:1|' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE prediction.team_state_advancement_result (
        advancement_id uuid NOT NULL,
        ordinal integer NOT NULL,
        evaluation_id uuid NOT NULL,
        evaluation_identity_sha256 persistence.sha256 NOT NULL,
        result_id uuid NOT NULL,
        result_identity_sha256 persistence.sha256 NOT NULL,
        fixture_id uuid NOT NULL,
        PRIMARY KEY (advancement_id, ordinal),
        CONSTRAINT uq_team_state_result_evaluation UNIQUE (evaluation_id),
        CONSTRAINT uq_team_state_result_value UNIQUE (result_id),
        CONSTRAINT fk_team_state_advancement_result_owner FOREIGN KEY (
            advancement_id
        ) REFERENCES prediction.team_state_advancement (advancement_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_team_state_advancement_result_evaluation FOREIGN KEY (
            evaluation_id, evaluation_identity_sha256, fixture_id
        ) REFERENCES prediction.completed_prediction_evaluation (
            evaluation_id, identity_sha256, fixture_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_team_state_advancement_result_value FOREIGN KEY (
            result_id, result_identity_sha256, fixture_id
        ) REFERENCES football.current_completed_result (
            result_id, identity_sha256, fixture_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_team_state_advancement_result_ordinal CHECK (ordinal >= 0)
    )
    """,
    """
    CREATE FUNCTION prediction.validate_team_state_advancement()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        member_total integer;
        member_order_valid boolean;
        pre_count integer;
        post_count integer;
        missing_pre integer;
        missing_applied integer;
        evidence_time timestamptz;
    BEGIN
        SELECT count(*), bool_and(ordinal = expected_ordinal)
          INTO member_total, member_order_valid
        FROM (
            SELECT ordinal,
                   row_number() OVER (ORDER BY fixture_id)::integer - 1
                       AS expected_ordinal
            FROM prediction.team_state_advancement_result r
            WHERE r.advancement_id = NEW.advancement_id
        ) ordered_members;
        SELECT completed_result_count INTO pre_count
        FROM prediction.operational_team_state WHERE state_id = NEW.pre_state_id;
        SELECT completed_result_count INTO post_count
        FROM prediction.operational_team_state WHERE state_id = NEW.post_state_id;
        SELECT count(*) INTO missing_pre
        FROM prediction.operational_team_state_result p
        WHERE p.state_id = NEW.pre_state_id AND NOT EXISTS (
            SELECT 1 FROM prediction.operational_team_state_result n
            WHERE n.state_id = NEW.post_state_id AND n.result_id = p.result_id
        );
        SELECT count(*) INTO missing_applied
        FROM prediction.team_state_advancement_result a
        WHERE a.advancement_id = NEW.advancement_id AND NOT EXISTS (
            SELECT 1 FROM prediction.operational_team_state_result n
            WHERE n.state_id = NEW.post_state_id AND n.result_id = a.result_id
        );
        SELECT max(e.result_retrieved_at) INTO evidence_time
        FROM prediction.team_state_advancement_result a
        JOIN prediction.completed_prediction_evaluation e
          ON e.evaluation_id = a.evaluation_id
        WHERE a.advancement_id = NEW.advancement_id;
        IF member_total <> NEW.applied_result_count
           OR NOT coalesce(member_order_valid, false)
           OR post_count <> pre_count + member_total
           OR missing_pre <> 0 OR missing_applied <> 0
           OR evidence_time IS DISTINCT FROM NEW.applied_at
           OR (NEW.prior_advancement_id IS NULL AND pre_count <> 0) THEN
            RAISE EXCEPTION 'state_chain_invalid: invalid team-state advancement'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_team_state_advancement_complete';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_team_state_advancement
    AFTER INSERT ON prediction.team_state_advancement
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION prediction.validate_team_state_advancement()
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_team_state_advancement_result
    AFTER INSERT ON prediction.team_state_advancement_result
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION prediction.validate_team_state_advancement()
    """,
    """
    CREATE TABLE prediction.prediction_regeneration (
        regeneration_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        regeneration_object_sha256 persistence.sha256 NOT NULL UNIQUE,
        schema_version persistence.positive_version NOT NULL,
        advancement_id uuid NOT NULL,
        advancement_identity_sha256 persistence.sha256 NOT NULL,
        prior_prediction_id uuid NOT NULL,
        prior_prediction_identity_sha256 persistence.sha256 NOT NULL,
        replacement_prediction_id uuid NOT NULL UNIQUE,
        replacement_prediction_identity_sha256 persistence.sha256 NOT NULL,
        fixture_id uuid NOT NULL,
        season_id text NOT NULL,
        CONSTRAINT uq_prediction_regeneration_once UNIQUE (
            advancement_id, prior_prediction_id
        ),
        CONSTRAINT fk_prediction_regeneration_identity FOREIGN KEY (identity_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_prediction_regeneration_object FOREIGN KEY (
            regeneration_object_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_prediction_regeneration_advancement FOREIGN KEY (
            advancement_id, advancement_identity_sha256
        ) REFERENCES prediction.team_state_advancement (
            advancement_id, identity_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_prediction_regeneration_prior FOREIGN KEY (
            prior_prediction_id, prior_prediction_identity_sha256,
            fixture_id, season_id
        ) REFERENCES prediction.current_model_prediction (
            prediction_id, identity_sha256, fixture_id, season_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_prediction_regeneration_replacement FOREIGN KEY (
            replacement_prediction_id, replacement_prediction_identity_sha256,
            fixture_id, season_id
        ) REFERENCES prediction.current_model_prediction (
            prediction_id, identity_sha256, fixture_id, season_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_prediction_regeneration_v1 CHECK (
            schema_version = 1 AND season_id <> '2025-2026'
            AND prior_prediction_id <> replacement_prediction_id
            AND regeneration_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:prediction-regeneration:1|' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE FUNCTION prediction.validate_prediction_regeneration()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        prior_feature_id uuid;
        replacement_feature_id uuid;
        prior_cutoff timestamptz;
        replacement_cutoff timestamptz;
        missing_new integer;
        already_present integer;
    BEGIN
        SELECT feature_id, feature_cutoff_at INTO prior_feature_id, prior_cutoff
        FROM prediction.current_model_prediction
        WHERE prediction_id = NEW.prior_prediction_id;
        SELECT feature_id, feature_cutoff_at
          INTO replacement_feature_id, replacement_cutoff
        FROM prediction.current_model_prediction
        WHERE prediction_id = NEW.replacement_prediction_id;
        SELECT count(*) INTO missing_new
        FROM prediction.team_state_advancement_result a
        WHERE a.advancement_id = NEW.advancement_id AND NOT EXISTS (
            SELECT 1 FROM prediction.upcoming_feature_result_source s
            WHERE s.feature_id = replacement_feature_id
              AND s.result_id = a.result_id
        );
        SELECT count(*) INTO already_present
        FROM prediction.team_state_advancement_result a
        WHERE a.advancement_id = NEW.advancement_id AND EXISTS (
            SELECT 1 FROM prediction.upcoming_feature_result_source s
            WHERE s.feature_id = prior_feature_id AND s.result_id = a.result_id
        );
        IF replacement_cutoff <= prior_cutoff OR missing_new <> 0
           OR already_present = (
               SELECT applied_result_count
               FROM prediction.team_state_advancement
               WHERE advancement_id = NEW.advancement_id
           ) THEN
            RAISE EXCEPTION 'state_chain_invalid: invalid prediction regeneration'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_prediction_regeneration_complete';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_prediction_regeneration
    AFTER INSERT ON prediction.prediction_regeneration
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION prediction.validate_prediction_regeneration()
    """,
    """
    CREATE TABLE prediction.season_simulation_regeneration (
        regeneration_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        regeneration_object_sha256 persistence.sha256 NOT NULL UNIQUE,
        schema_version persistence.positive_version NOT NULL,
        advancement_id uuid NOT NULL,
        advancement_identity_sha256 persistence.sha256 NOT NULL,
        previous_simulation_id uuid NOT NULL,
        replacement_input_sha256 persistence.sha256 NOT NULL,
        replacement_simulation_id uuid NOT NULL UNIQUE,
        replacement_summary_id uuid NOT NULL UNIQUE,
        simulation_seed numeric(20, 0) NOT NULL,
        season_id text NOT NULL,
        CONSTRAINT uq_season_simulation_regeneration_once UNIQUE (
            advancement_id, previous_simulation_id
        ),
        CONSTRAINT fk_season_simulation_regeneration_identity FOREIGN KEY (
            identity_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_season_simulation_regeneration_object FOREIGN KEY (
            regeneration_object_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_season_simulation_regeneration_advancement FOREIGN KEY (
            advancement_id, advancement_identity_sha256
        ) REFERENCES prediction.team_state_advancement (
            advancement_id, identity_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_season_simulation_regeneration_previous FOREIGN KEY (
            previous_simulation_id
        ) REFERENCES simulation.simulation_run (simulation_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_season_simulation_regeneration_input FOREIGN KEY (
            replacement_input_sha256
        ) REFERENCES simulation.simulation_input (input_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_season_simulation_regeneration_run FOREIGN KEY (
            replacement_simulation_id, replacement_input_sha256,
            simulation_seed
        ) REFERENCES simulation.simulation_run (
            simulation_id, input_sha256, simulation_seed
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_season_simulation_regeneration_summary FOREIGN KEY (
            replacement_summary_id, replacement_simulation_id
        ) REFERENCES simulation.simulation_summary (
            summary_id, simulation_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_season_simulation_regeneration_v1 CHECK (
            schema_version = 1 AND season_id <> '2025-2026'
            AND previous_simulation_id <> replacement_simulation_id
            AND regeneration_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:season-simulation-regeneration:1|'
                || identity_sha256
            )
        )
    )
    """,
    """
    CREATE FUNCTION prediction.validate_season_simulation_regeneration()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        previous_input persistence.sha256;
        replacement_season text;
        replacement_summary_season text;
        missing_new integer;
        old_present integer;
    BEGIN
        SELECT input_sha256 INTO previous_input FROM simulation.simulation_run
        WHERE simulation_id = NEW.previous_simulation_id;
        SELECT season_id INTO replacement_season FROM simulation.simulation_input
        WHERE input_sha256 = NEW.replacement_input_sha256;
        SELECT season_id INTO replacement_summary_season
        FROM simulation.simulation_summary
        WHERE summary_id = NEW.replacement_summary_id;
        SELECT count(*) INTO missing_new
        FROM prediction.team_state_advancement_result a
        WHERE a.advancement_id = NEW.advancement_id AND NOT EXISTS (
            SELECT 1 FROM simulation.simulation_input_completed_fixture c
            WHERE c.input_sha256 = NEW.replacement_input_sha256
              AND c.fixture_id = a.fixture_id
        );
        SELECT count(*) INTO old_present
        FROM prediction.team_state_advancement_result a
        WHERE a.advancement_id = NEW.advancement_id AND EXISTS (
            SELECT 1 FROM simulation.simulation_input_completed_fixture c
            WHERE c.input_sha256 = previous_input AND c.fixture_id = a.fixture_id
        );
        IF replacement_season IS DISTINCT FROM NEW.season_id
           OR replacement_summary_season IS DISTINCT FROM NEW.season_id
           OR missing_new <> 0 OR old_present = (
               SELECT applied_result_count
               FROM prediction.team_state_advancement
               WHERE advancement_id = NEW.advancement_id
           ) THEN
            RAISE EXCEPTION 'state_chain_invalid: invalid simulation regeneration'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_season_simulation_regeneration_complete';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_season_simulation_regeneration
    AFTER INSERT ON prediction.season_simulation_regeneration
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION prediction.validate_season_simulation_regeneration()
    """,
)


IMMUTABLE_TABLES: tuple[str, ...] = (
    "operational_team_state",
    "operational_team_state_result",
    "operational_team_state_rating",
    "team_state_advancement",
    "team_state_advancement_result",
    "prediction_regeneration",
    "season_simulation_regeneration",
)


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)
    for table in IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER immutable_guard
            BEFORE UPDATE OR DELETE ON prediction.{table}
            FOR EACH ROW EXECUTE FUNCTION persistence.reject_immutable_mutation()
            """
        )


def downgrade() -> None:
    for function in (
        "validate_season_simulation_regeneration",
        "validate_prediction_regeneration",
        "validate_team_state_advancement",
        "validate_operational_team_state",
    ):
        op.execute(f"DROP FUNCTION prediction.{function}() CASCADE")
    for table in reversed(IMMUTABLE_TABLES):
        op.execute(f"DROP TABLE prediction.{table}")
    op.execute(
        "ALTER TABLE simulation.simulation_summary "
        "DROP CONSTRAINT uq_simulation_summary_regeneration_lineage"
    )
    op.execute(
        "ALTER TABLE simulation.simulation_run "
        "DROP CONSTRAINT uq_simulation_run_regeneration_lineage"
    )
    op.execute(
        "ALTER TABLE prediction.completed_prediction_evaluation "
        "DROP CONSTRAINT uq_completed_evaluation_advancement_lineage"
    )
    op.execute(
        "ALTER TABLE simulation.result_component "
        "ADD CONSTRAINT uq_result_component_object UNIQUE (object_sha256)"
    )
