"""Add provider-neutral current player and squad persistence.

Revision ID: f0006_step_6_8
Revises: f0005_step_6_7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0006_step_6_8"
down_revision: str | None = "f0005_step_6_7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DDL: tuple[str, ...] = (
    """
    CREATE TABLE identity.player (
        player_id uuid PRIMARY KEY
    )
    """,
    """
    CREATE TABLE football.current_player_source_reference (
        source_id text NOT NULL,
        external_id text NOT NULL,
        player_id uuid NOT NULL,
        PRIMARY KEY (source_id, external_id),
        CONSTRAINT fk_current_player_reference_source FOREIGN KEY (source_id)
            REFERENCES identity.source (source_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_player_reference_player FOREIGN KEY (player_id)
            REFERENCES identity.player (player_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_player_reference_external CHECK (external_id <> '')
    )
    """,
    """
    CREATE TABLE football.current_player_observation (
        observation_id uuid PRIMARY KEY,
        player_id uuid NOT NULL,
        source_id text NOT NULL,
        external_id text NOT NULL,
        cache_key_sha256 persistence.sha256 NOT NULL,
        provider_name text NOT NULL,
        date_of_birth date,
        nationality_code text,
        provider_position text,
        retrieved_at timestamptz NOT NULL,
        CONSTRAINT uq_current_player_observation UNIQUE (
            source_id, external_id, cache_key_sha256
        ),
        CONSTRAINT fk_current_player_observation_reference FOREIGN KEY (
            source_id, external_id
        ) REFERENCES football.current_player_source_reference (
            source_id, external_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_player_observation_player FOREIGN KEY (player_id)
            REFERENCES identity.player (player_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_player_observation_cache FOREIGN KEY (
            cache_key_sha256
        ) REFERENCES provider_cache.response (cache_key_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_player_observation_deterministic_id CHECK (
            observation_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:current-player-observation:1|' || player_id::text
                || '|' || cache_key_sha256
            )
        ),
        CONSTRAINT ck_current_player_observation_metadata CHECK (
            provider_name <> ''
            AND (nationality_code IS NULL OR nationality_code ~ '^[A-Z]{3}$')
            AND (provider_position IS NULL OR provider_position <> '')
        )
    )
    """,
    """
    CREATE TABLE football.current_squad (
        squad_id uuid PRIMARY KEY,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        team_id uuid NOT NULL,
        CONSTRAINT uq_current_squad_scope UNIQUE (
            competition_id, season_id, team_id
        ),
        CONSTRAINT uq_current_squad_snapshot UNIQUE (squad_id, team_id),
        CONSTRAINT fk_current_squad_season FOREIGN KEY (
            competition_id, season_id
        ) REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_squad_team FOREIGN KEY (team_id)
            REFERENCES identity.team (team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_squad_deterministic_id CHECK (
            squad_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:squad:' || competition_id || '|' || season_id
                || '|' || team_id::text
            )
        )
    )
    """,
    """
    CREATE TABLE football.current_squad_source_reference (
        source_id text NOT NULL,
        external_id text NOT NULL,
        squad_id uuid NOT NULL,
        PRIMARY KEY (source_id, external_id),
        CONSTRAINT fk_current_squad_reference_source FOREIGN KEY (source_id)
            REFERENCES identity.source (source_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_squad_reference_squad FOREIGN KEY (squad_id)
            REFERENCES football.current_squad (squad_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_squad_reference_external CHECK (external_id <> '')
    )
    """,
    """
    CREATE TABLE football.current_squad_snapshot (
        snapshot_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        source_id text NOT NULL,
        as_of_date date NOT NULL,
        knowledge_available_at timestamptz NOT NULL,
        CONSTRAINT fk_current_squad_snapshot_identity FOREIGN KEY (
            identity_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_squad_snapshot_season FOREIGN KEY (
            competition_id, season_id
        ) REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_squad_snapshot_source FOREIGN KEY (source_id)
            REFERENCES identity.source (source_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_squad_snapshot_deterministic_id CHECK (
            snapshot_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:current-squad-snapshot:1|' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE football.current_squad_snapshot_provenance (
        snapshot_id uuid NOT NULL,
        cache_key_sha256 persistence.sha256 NOT NULL,
        PRIMARY KEY (snapshot_id, cache_key_sha256),
        CONSTRAINT fk_current_squad_provenance_snapshot FOREIGN KEY (snapshot_id)
            REFERENCES football.current_squad_snapshot (snapshot_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_squad_provenance_cache FOREIGN KEY (
            cache_key_sha256
        ) REFERENCES provider_cache.response (cache_key_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE football.current_squad_snapshot_team (
        snapshot_id uuid NOT NULL,
        ordinal integer NOT NULL,
        squad_id uuid NOT NULL,
        team_id uuid NOT NULL,
        PRIMARY KEY (snapshot_id, ordinal),
        CONSTRAINT uq_current_squad_snapshot_team UNIQUE (snapshot_id, team_id),
        CONSTRAINT uq_current_squad_snapshot_squad UNIQUE (
            snapshot_id, squad_id, team_id
        ),
        CONSTRAINT fk_current_squad_snapshot_team_owner FOREIGN KEY (snapshot_id)
            REFERENCES football.current_squad_snapshot (snapshot_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_squad_snapshot_team_squad FOREIGN KEY (
            squad_id, team_id
        ) REFERENCES football.current_squad (squad_id, team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_squad_snapshot_team_ordinal CHECK (ordinal >= 0)
    )
    """,
    """
    CREATE TABLE football.current_squad_member (
        snapshot_id uuid NOT NULL,
        squad_id uuid NOT NULL,
        team_id uuid NOT NULL,
        player_id uuid NOT NULL,
        source_id text NOT NULL,
        external_id text NOT NULL,
        membership_kind text NOT NULL,
        effective_from date NOT NULL,
        effective_to date,
        registered_from date NOT NULL,
        registered_to date,
        loan_parent_team_id uuid,
        shirt_number smallint,
        PRIMARY KEY (snapshot_id, squad_id, player_id),
        CONSTRAINT uq_current_squad_member_player UNIQUE (snapshot_id, player_id),
        CONSTRAINT fk_current_squad_member_squad FOREIGN KEY (
            snapshot_id, squad_id, team_id
        ) REFERENCES football.current_squad_snapshot_team (
            snapshot_id, squad_id, team_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_squad_member_player FOREIGN KEY (player_id)
            REFERENCES identity.player (player_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_squad_member_reference FOREIGN KEY (
            source_id, external_id
        ) REFERENCES football.current_player_source_reference (
            source_id, external_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_squad_member_loan_parent FOREIGN KEY (
            loan_parent_team_id
        ) REFERENCES identity.team (team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_squad_member_window CHECK (
            (effective_to IS NULL OR effective_to >= effective_from)
            AND registered_from >= effective_from
            AND (registered_to IS NULL OR registered_to >= registered_from)
            AND (effective_to IS NULL OR registered_to IS NULL
                 OR registered_to <= effective_to)
        ),
        CONSTRAINT ck_current_squad_member_kind CHECK (
            (membership_kind = 'loan' AND loan_parent_team_id IS NOT NULL
             AND loan_parent_team_id <> team_id)
            OR (membership_kind IN ('permanent', 'academy')
                AND loan_parent_team_id IS NULL)
        ),
        CONSTRAINT ck_current_squad_member_shirt CHECK (
            shirt_number IS NULL OR shirt_number >= 1
        )
    )
    """,
    """
    CREATE FUNCTION football.validate_current_player_observation()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        cache_source text;
        cache_capability text;
        cache_fetched timestamptz;
        mapped_player uuid;
    BEGIN
        SELECT source_id, capability, fetched_at
          INTO cache_source, cache_capability, cache_fetched
        FROM provider_cache.response WHERE cache_key_sha256 = NEW.cache_key_sha256;
        SELECT player_id INTO mapped_player
        FROM football.current_player_source_reference
        WHERE source_id = NEW.source_id AND external_id = NEW.external_id;
        IF cache_source IS DISTINCT FROM NEW.source_id
           OR cache_capability IS DISTINCT FROM 'metadata'
           OR cache_fetched IS DISTINCT FROM NEW.retrieved_at
           OR mapped_player IS DISTINCT FROM NEW.player_id THEN
            RAISE EXCEPTION 'provenance_mismatch: invalid player observation'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_current_player_observation_provenance';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_current_player_observation
    AFTER INSERT ON football.current_player_observation
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION football.validate_current_player_observation()
    """,
    """
    CREATE FUNCTION football.validate_current_squad_snapshot()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        team_count integer;
        provenance_count integer;
        maximum_retrieval timestamptz;
        bad_teams integer;
        bad_order integer;
        empty_squads integer;
        bad_members integer;
        bad_provenance integer;
    BEGIN
        SELECT count(*), count(*) FILTER (WHERE (
                   c.source_id <> NEW.source_id OR c.capability <> 'metadata'
               )), max(c.fetched_at)
          INTO provenance_count, bad_provenance, maximum_retrieval
        FROM football.current_squad_snapshot_provenance p
        JOIN provider_cache.response c
          ON c.cache_key_sha256 = p.cache_key_sha256
        WHERE p.snapshot_id = NEW.snapshot_id;
        SELECT count(*), count(*) FILTER (WHERE NOT EXISTS (
                   SELECT 1 FROM identity.season_membership sm
                   WHERE sm.competition_id = NEW.competition_id
                     AND sm.season_id = NEW.season_id AND sm.team_id = st.team_id
               ))
          INTO team_count, bad_teams
        FROM football.current_squad_snapshot_team st
        WHERE st.snapshot_id = NEW.snapshot_id;
        SELECT count(*) INTO bad_order FROM (
            SELECT ordinal, row_number() OVER (ORDER BY team_id) - 1 AS expected
            FROM football.current_squad_snapshot_team
            WHERE snapshot_id = NEW.snapshot_id
        ) ordered WHERE ordinal <> expected;
        SELECT count(*) INTO empty_squads
        FROM football.current_squad_snapshot_team st
        WHERE st.snapshot_id = NEW.snapshot_id AND NOT EXISTS (
            SELECT 1 FROM football.current_squad_member m
            WHERE m.snapshot_id = st.snapshot_id AND m.squad_id = st.squad_id
        );
        SELECT count(*) INTO bad_members
        FROM football.current_squad_member m
        WHERE m.snapshot_id = NEW.snapshot_id AND (
            m.source_id <> NEW.source_id
            OR m.registered_from > NEW.as_of_date
            OR (m.registered_to IS NOT NULL
                AND m.registered_to < NEW.as_of_date)
            OR NOT EXISTS (
                SELECT 1 FROM football.current_player_observation po
                WHERE po.player_id = m.player_id AND po.source_id = NEW.source_id
                  AND po.external_id = m.external_id
                  AND po.retrieved_at <= NEW.knowledge_available_at
            )
            OR NOT EXISTS (
                SELECT 1 FROM identity.season_registry_entry se
                WHERE se.competition_id = NEW.competition_id
                  AND se.season_id = NEW.season_id
                  AND m.registered_from >= se.starts_on
                  AND (m.registered_to IS NULL OR m.registered_to <= se.ends_on)
                  AND NEW.as_of_date BETWEEN se.starts_on AND se.ends_on
            )
            OR (m.loan_parent_team_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM identity.season_membership sm
                WHERE sm.competition_id = NEW.competition_id
                  AND sm.season_id = NEW.season_id
                  AND sm.team_id = m.loan_parent_team_id
            ))
        );
        IF provenance_count = 0 OR bad_provenance <> 0
           OR team_count <> 20 OR bad_teams <> 0
           OR bad_order <> 0 OR empty_squads <> 0 OR bad_members <> 0
           OR maximum_retrieval IS DISTINCT FROM NEW.knowledge_available_at THEN
            RAISE EXCEPTION 'provenance_mismatch: incomplete current squad snapshot'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_current_squad_snapshot_complete';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_current_squad_snapshot
    AFTER INSERT ON football.current_squad_snapshot
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION football.validate_current_squad_snapshot()
    """,
)


IMMUTABLE_TABLES: tuple[tuple[str, str], ...] = (
    ("identity", "player"),
    ("football", "current_player_source_reference"),
    ("football", "current_player_observation"),
    ("football", "current_squad"),
    ("football", "current_squad_source_reference"),
    ("football", "current_squad_snapshot"),
    ("football", "current_squad_snapshot_provenance"),
    ("football", "current_squad_snapshot_team"),
    ("football", "current_squad_member"),
)


def upgrade() -> None:
    """Create immutable player identity and full squad snapshots."""

    for statement in DDL:
        op.execute(sa.text(statement))
    for schema, table in IMMUTABLE_TABLES:
        op.execute(
            sa.text(
                "CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE "
                f"ON {schema}.{table} FOR EACH ROW EXECUTE FUNCTION "
                "persistence.reject_immutable_mutation()"
            )
        )


def downgrade() -> None:
    """Remove Step 6.8 player and squad structures."""

    for schema, table in reversed(IMMUTABLE_TABLES):
        op.execute(sa.text(f"DROP TABLE {schema}.{table} CASCADE"))
    op.execute(
        sa.text("DROP FUNCTION IF EXISTS football.validate_current_squad_snapshot()")
    )
    op.execute(
        sa.text(
            "DROP FUNCTION IF EXISTS football.validate_current_player_observation()"
        )
    )
