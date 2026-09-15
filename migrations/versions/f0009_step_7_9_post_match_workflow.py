"""Add the append-only, resumable post-match workflow journal.

Revision ID: f0009_step_7_9
Revises: f0008_step_7_7
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f0009_step_7_9"
down_revision: str | None = "f0008_step_7_7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DDL: tuple[str, ...] = (
    """
    CREATE TABLE prediction.post_match_workflow (
        workflow_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        workflow_object_sha256 persistence.sha256 NOT NULL UNIQUE,
        schema_version persistence.positive_version NOT NULL,
        season_id text NOT NULL,
        evaluation_count integer NOT NULL,
        evaluation_set_sha256 persistence.sha256 NOT NULL,
        advancement_id uuid NOT NULL,
        advancement_identity_sha256 persistence.sha256 NOT NULL,
        prediction_regeneration_count integer NOT NULL,
        prediction_regeneration_set_sha256 persistence.sha256 NOT NULL,
        simulation_regeneration_id uuid NOT NULL,
        simulation_regeneration_identity_sha256 persistence.sha256 NOT NULL,
        CONSTRAINT uq_post_match_workflow_snapshot UNIQUE (
            workflow_id, identity_sha256
        ),
        CONSTRAINT fk_post_match_workflow_identity FOREIGN KEY (identity_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_post_match_workflow_object FOREIGN KEY (
            workflow_object_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_post_match_workflow_v1 CHECK (
            schema_version = 1 AND season_id <> '2025-2026'
            AND evaluation_count > 0
            AND prediction_regeneration_count >= 0
            AND workflow_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:post-match-workflow:1|' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE prediction.post_match_workflow_event (
        event_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        event_object_sha256 persistence.sha256 NOT NULL UNIQUE,
        schema_version persistence.positive_version NOT NULL,
        workflow_id uuid NOT NULL,
        workflow_identity_sha256 persistence.sha256 NOT NULL,
        sequence integer NOT NULL,
        stage text NOT NULL,
        previous_event_id uuid,
        previous_event_sha256 persistence.sha256,
        stage_lineage_sha256 persistence.sha256 NOT NULL,
        CONSTRAINT uq_post_match_workflow_event_sequence UNIQUE (
            workflow_id, sequence
        ),
        CONSTRAINT uq_post_match_workflow_event_stage UNIQUE (
            workflow_id, stage
        ),
        CONSTRAINT uq_post_match_workflow_event_chain UNIQUE (
            workflow_id, event_id, identity_sha256
        ),
        CONSTRAINT fk_post_match_workflow_event_identity FOREIGN KEY (
            identity_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_post_match_workflow_event_object FOREIGN KEY (
            event_object_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_post_match_workflow_event_owner FOREIGN KEY (
            workflow_id, workflow_identity_sha256
        ) REFERENCES prediction.post_match_workflow (
            workflow_id, identity_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_post_match_workflow_event_previous FOREIGN KEY (
            workflow_id, previous_event_id, previous_event_sha256
        ) REFERENCES prediction.post_match_workflow_event (
            workflow_id, event_id, identity_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_post_match_workflow_event_v1 CHECK (
            schema_version = 1 AND sequence BETWEEN 0 AND 5
            AND ((sequence = 0 AND previous_event_id IS NULL
                  AND previous_event_sha256 IS NULL)
                 OR (sequence > 0 AND previous_event_id IS NOT NULL
                     AND previous_event_sha256 IS NOT NULL))
            AND event_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:post-match-workflow-event:1|' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE FUNCTION prediction.validate_post_match_workflow_event()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        workflow prediction.post_match_workflow%ROWTYPE;
        predecessor prediction.post_match_workflow_event%ROWTYPE;
        expected_stage text;
        expected_lineage persistence.sha256;
    BEGIN
        SELECT * INTO workflow FROM prediction.post_match_workflow
        WHERE workflow_id = NEW.workflow_id;
        expected_stage := CASE NEW.sequence
            WHEN 0 THEN 'planned'
            WHEN 1 THEN 'evaluations_persisted'
            WHEN 2 THEN 'state_advancement_persisted'
            WHEN 3 THEN 'predictions_regenerated'
            WHEN 4 THEN 'simulation_regenerated'
            WHEN 5 THEN 'completed'
        END;
        expected_lineage := CASE NEW.sequence
            WHEN 0 THEN workflow.identity_sha256
            WHEN 1 THEN workflow.evaluation_set_sha256
            WHEN 2 THEN workflow.advancement_identity_sha256
            WHEN 3 THEN workflow.prediction_regeneration_set_sha256
            WHEN 4 THEN workflow.simulation_regeneration_identity_sha256
            WHEN 5 THEN workflow.identity_sha256
        END;
        IF NEW.stage IS DISTINCT FROM expected_stage
           OR NEW.stage_lineage_sha256 IS DISTINCT FROM expected_lineage THEN
            RAISE EXCEPTION 'workflow_history_malformed: invalid workflow event'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_post_match_workflow_event_stage';
        END IF;
        IF NEW.sequence > 0 THEN
            SELECT * INTO predecessor
            FROM prediction.post_match_workflow_event
            WHERE workflow_id = NEW.workflow_id
              AND sequence = NEW.sequence - 1;
            IF predecessor.event_id IS DISTINCT FROM NEW.previous_event_id
               OR predecessor.identity_sha256
                    IS DISTINCT FROM NEW.previous_event_sha256 THEN
                RAISE EXCEPTION
                    'workflow_history_malformed: invalid workflow predecessor'
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'ck_post_match_workflow_event_chain';
            END IF;
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_post_match_workflow_event
    AFTER INSERT ON prediction.post_match_workflow_event
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION prediction.validate_post_match_workflow_event()
    """,
)


IMMUTABLE_TABLES: tuple[str, ...] = (
    "post_match_workflow",
    "post_match_workflow_event",
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
    op.execute("DROP FUNCTION prediction.validate_post_match_workflow_event() CASCADE")
    for table in reversed(IMMUTABLE_TABLES):
        op.execute(f"DROP TABLE prediction.{table}")
