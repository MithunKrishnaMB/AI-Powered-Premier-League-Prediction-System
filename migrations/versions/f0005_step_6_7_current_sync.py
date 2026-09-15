"""Add current-season fixture, result and standings synchronization.

Revision ID: f0005_step_6_7
Revises: f0004_step_5_7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0005_step_6_7"
down_revision: str | None = "f0004_step_5_7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DDL: tuple[str, ...] = (
    """
    ALTER TABLE football.fixture_revision
      DROP CONSTRAINT ck_fixture_revision_status,
      DROP CONSTRAINT ck_fixture_revision_state
    """,
    """
    ALTER TABLE football.fixture_revision
      ADD CONSTRAINT ck_fixture_revision_status CHECK (status IN (
          'scheduled', 'postponed', 'cancelled', 'abandoned',
          'in_progress', 'finished'
      )),
      ADD CONSTRAINT ck_fixture_revision_state CHECK (
          (status = 'finished' AND full_time_home_goals IS NOT NULL
           AND outcome IS NOT NULL)
          OR
          (status IN ('scheduled', 'postponed', 'cancelled', 'abandoned')
           AND full_time_home_goals IS NULL
           AND half_time_home_goals IS NULL AND outcome IS NULL)
          OR status = 'in_progress'
      )
    """,
    """
    CREATE TABLE football.current_fixture_source_reference (
        source_id text NOT NULL,
        external_id text NOT NULL,
        fixture_id uuid NOT NULL,
        PRIMARY KEY (source_id, external_id),
        CONSTRAINT fk_current_fixture_reference_source FOREIGN KEY (source_id)
            REFERENCES identity.source (source_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_fixture_reference_fixture FOREIGN KEY (fixture_id)
            REFERENCES football.fixture (fixture_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_fixture_reference_external CHECK (external_id <> '')
    )
    """,
    """
    CREATE TABLE football.current_fixture_revision (
        revision_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        fixture_id uuid NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        home_team_id uuid NOT NULL,
        away_team_id uuid NOT NULL,
        kickoff_at timestamptz NOT NULL,
        kickoff_precision text NOT NULL,
        source_timezone text NOT NULL,
        source_local_date date NOT NULL,
        status text NOT NULL,
        matchweek smallint,
        venue text,
        referee text,
        CONSTRAINT uq_current_fixture_revision_snapshot UNIQUE (
            revision_id, fixture_id
        ),
        CONSTRAINT fk_current_fixture_revision_identity FOREIGN KEY (
            identity_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_fixture_revision_fixture FOREIGN KEY (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) REFERENCES football.fixture (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_fixture_revision_deterministic_id CHECK (
            revision_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:current-fixture-revision:1|' || identity_sha256
            )
        ),
        CONSTRAINT ck_current_fixture_revision_precision CHECK (
            kickoff_precision IN ('exact', 'date_only')
            AND source_local_date = (kickoff_at AT TIME ZONE source_timezone)::date
            AND (
                kickoff_precision = 'exact'
                OR kickoff_at = make_timestamptz(
                    extract(year FROM source_local_date)::integer,
                    extract(month FROM source_local_date)::integer,
                    extract(day FROM source_local_date)::integer,
                    12, 0, 0, source_timezone
                )
            )
        ),
        CONSTRAINT ck_current_fixture_revision_status CHECK (status IN (
            'scheduled', 'postponed', 'cancelled', 'abandoned', 'in_progress'
        )),
        CONSTRAINT ck_current_fixture_revision_fields CHECK (
            source_timezone <> '' AND (matchweek IS NULL OR matchweek >= 1)
            AND (venue IS NULL OR venue <> '')
            AND (referee IS NULL OR referee <> '')
        )
    )
    """,
    """
    CREATE TABLE football.current_fixture_observation (
        observation_id uuid PRIMARY KEY,
        fixture_id uuid NOT NULL,
        revision_id uuid NOT NULL,
        source_id text NOT NULL,
        external_id text NOT NULL,
        cache_key_sha256 persistence.sha256 NOT NULL,
        provider_updated_at timestamptz,
        provider_observed_at timestamptz,
        retrieved_at timestamptz NOT NULL,
        CONSTRAINT uq_current_fixture_observation UNIQUE (
            source_id, external_id, cache_key_sha256
        ),
        CONSTRAINT uq_current_fixture_observation_time UNIQUE (
            source_id, external_id, retrieved_at
        ),
        CONSTRAINT fk_current_fixture_observation_revision FOREIGN KEY (
            revision_id, fixture_id
        ) REFERENCES football.current_fixture_revision (revision_id, fixture_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_fixture_observation_reference FOREIGN KEY (
            source_id, external_id
        ) REFERENCES football.current_fixture_source_reference (
            source_id, external_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_fixture_observation_cache FOREIGN KEY (
            cache_key_sha256
        ) REFERENCES provider_cache.response (cache_key_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_fixture_observation_deterministic_id CHECK (
            observation_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:current-fixture-observation:1|' || fixture_id::text
                || '|' || cache_key_sha256 || '|' || revision_id::text
            )
        ),
        CONSTRAINT ck_current_fixture_observation_time CHECK (
            (provider_updated_at IS NULL OR provider_updated_at <= retrieved_at)
            AND (provider_observed_at IS NULL
                 OR provider_observed_at <= retrieved_at)
        )
    )
    """,
    """
    CREATE TABLE football.current_fixture_batch (
        batch_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        batch_kind text NOT NULL,
        source_timezone text NOT NULL,
        source_local_date date NOT NULL,
        exact_kickoff_at timestamptz,
        feature_cutoff_at timestamptz NOT NULL,
        knowledge_available_at timestamptz NOT NULL,
        CONSTRAINT fk_current_fixture_batch_identity FOREIGN KEY (identity_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_fixture_batch_season FOREIGN KEY (
            competition_id, season_id
        ) REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_fixture_batch_deterministic_id CHECK (
            batch_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:current-fixture-batch:1|' || identity_sha256
            )
        ),
        CONSTRAINT ck_current_fixture_batch_kind CHECK (
            (batch_kind = 'date_only_date' AND exact_kickoff_at IS NULL)
            OR (batch_kind = 'exact_kickoff' AND exact_kickoff_at IS NOT NULL
                AND exact_kickoff_at = feature_cutoff_at)
        ),
        CONSTRAINT ck_current_fixture_batch_timezone CHECK (
            source_timezone <> ''
        )
    )
    """,
    """
    CREATE TABLE football.current_fixture_batch_provenance (
        batch_id uuid NOT NULL,
        cache_key_sha256 persistence.sha256 NOT NULL,
        PRIMARY KEY (batch_id, cache_key_sha256),
        CONSTRAINT fk_current_batch_provenance_batch FOREIGN KEY (batch_id)
            REFERENCES football.current_fixture_batch (batch_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_batch_provenance_cache FOREIGN KEY (cache_key_sha256)
            REFERENCES provider_cache.response (cache_key_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE football.current_fixture_batch_member (
        batch_id uuid NOT NULL,
        member_ordinal integer NOT NULL,
        fixture_id uuid NOT NULL,
        revision_id uuid NOT NULL,
        PRIMARY KEY (batch_id, member_ordinal),
        CONSTRAINT uq_current_fixture_batch_member UNIQUE (batch_id, fixture_id),
        CONSTRAINT fk_current_fixture_batch_member_batch FOREIGN KEY (batch_id)
            REFERENCES football.current_fixture_batch (batch_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_fixture_batch_member_revision FOREIGN KEY (
            revision_id, fixture_id
        ) REFERENCES football.current_fixture_revision (revision_id, fixture_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_fixture_batch_member_ordinal CHECK (
            member_ordinal >= 0
        )
    )
    """,
    """
    CREATE TABLE football.current_completed_result (
        result_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        fixture_id uuid NOT NULL UNIQUE,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        home_team_id uuid NOT NULL,
        away_team_id uuid NOT NULL,
        full_time_home_goals smallint NOT NULL,
        full_time_away_goals smallint NOT NULL,
        outcome text NOT NULL,
        CONSTRAINT uq_current_result_snapshot UNIQUE (result_id, fixture_id),
        CONSTRAINT fk_current_result_identity FOREIGN KEY (identity_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_result_fixture FOREIGN KEY (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) REFERENCES football.fixture (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_result_deterministic_id CHECK (
            result_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:current-completed-result:1|' || identity_sha256
            )
        ),
        CONSTRAINT ck_current_result_nonnegative CHECK (
            full_time_home_goals >= 0 AND full_time_away_goals >= 0
        ),
        CONSTRAINT ck_current_result_outcome CHECK (
            outcome = CASE
                WHEN full_time_home_goals > full_time_away_goals THEN 'home_win'
                WHEN full_time_home_goals < full_time_away_goals THEN 'away_win'
                ELSE 'draw'
            END
        )
    )
    """,
    """
    CREATE TABLE football.current_result_observation (
        observation_id uuid PRIMARY KEY,
        result_id uuid NOT NULL,
        fixture_id uuid NOT NULL,
        source_id text NOT NULL,
        external_id text NOT NULL,
        cache_key_sha256 persistence.sha256 NOT NULL,
        completed_at timestamptz,
        retrieved_at timestamptz NOT NULL,
        CONSTRAINT uq_current_result_observation UNIQUE (
            source_id, external_id, cache_key_sha256
        ),
        CONSTRAINT fk_current_result_observation_result FOREIGN KEY (
            result_id, fixture_id
        ) REFERENCES football.current_completed_result (result_id, fixture_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_result_observation_reference FOREIGN KEY (
            source_id, external_id
        ) REFERENCES football.current_fixture_source_reference (
            source_id, external_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_result_observation_cache FOREIGN KEY (
            cache_key_sha256
        ) REFERENCES provider_cache.response (cache_key_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_result_observation_deterministic_id CHECK (
            observation_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:current-result-observation:1|' || result_id::text
                || '|' || cache_key_sha256
            )
        ),
        CONSTRAINT ck_current_result_observation_time CHECK (
            completed_at IS NULL OR completed_at <= retrieved_at
        )
    )
    """,
    """
    CREATE TABLE football.current_standing_snapshot (
        snapshot_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        source_id text NOT NULL,
        cache_key_sha256 persistence.sha256 NOT NULL UNIQUE,
        retrieved_at timestamptz NOT NULL,
        CONSTRAINT fk_current_standing_identity FOREIGN KEY (identity_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_standing_season FOREIGN KEY (
            competition_id, season_id
        ) REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_standing_source FOREIGN KEY (source_id)
            REFERENCES identity.source (source_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_standing_cache FOREIGN KEY (cache_key_sha256)
            REFERENCES provider_cache.response (cache_key_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_standing_deterministic_id CHECK (
            snapshot_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:current-standings-snapshot:1|' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE football.current_standing_row (
        snapshot_id uuid NOT NULL,
        team_id uuid NOT NULL,
        position smallint NOT NULL,
        played smallint NOT NULL,
        won smallint NOT NULL,
        drawn smallint NOT NULL,
        lost smallint NOT NULL,
        goals_for smallint NOT NULL,
        goals_against smallint NOT NULL,
        goal_difference smallint NOT NULL,
        points smallint NOT NULL,
        points_adjustment smallint NOT NULL,
        PRIMARY KEY (snapshot_id, team_id),
        CONSTRAINT uq_current_standing_position UNIQUE (snapshot_id, position),
        CONSTRAINT fk_current_standing_row_snapshot FOREIGN KEY (snapshot_id)
            REFERENCES football.current_standing_snapshot (snapshot_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_standing_row_team FOREIGN KEY (team_id)
            REFERENCES identity.team (team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_standing_row_counts CHECK (
            position BETWEEN 1 AND 20 AND played >= 0 AND won >= 0
            AND drawn >= 0 AND lost >= 0 AND goals_for >= 0
            AND goals_against >= 0 AND points >= 0
            AND played = won + drawn + lost
            AND goal_difference = goals_for - goals_against
            AND points = (3 * won) + drawn + points_adjustment
        )
    )
    """,
    """
    CREATE TABLE football.current_standing_source_reference (
        snapshot_id uuid NOT NULL,
        team_id uuid NOT NULL,
        source_id text NOT NULL,
        external_id text NOT NULL,
        PRIMARY KEY (snapshot_id, team_id),
        CONSTRAINT uq_current_standing_source_reference UNIQUE (
            snapshot_id, source_id, external_id
        ),
        CONSTRAINT fk_current_standing_reference_row FOREIGN KEY (
            snapshot_id, team_id
        ) REFERENCES football.current_standing_row (snapshot_id, team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_current_standing_reference_source FOREIGN KEY (source_id)
            REFERENCES identity.source (source_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_current_standing_reference_external CHECK (external_id <> '')
    )
    """,
    """
    CREATE FUNCTION football.validate_current_fixture_observation()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        cache_source text;
        cache_capability text;
        cache_fetched timestamptz;
        mapped_fixture uuid;
        current_status text;
        current_precision text;
        current_provider_updated timestamptz;
        later_count integer;
    BEGIN
        SELECT source_id, capability, fetched_at
          INTO cache_source, cache_capability, cache_fetched
        FROM provider_cache.response WHERE cache_key_sha256 = NEW.cache_key_sha256;
        SELECT fixture_id INTO mapped_fixture
        FROM football.current_fixture_source_reference
        WHERE source_id = NEW.source_id AND external_id = NEW.external_id;
        IF cache_source IS DISTINCT FROM NEW.source_id
           OR cache_capability IS DISTINCT FROM 'fixtures'
           OR cache_fetched IS DISTINCT FROM NEW.retrieved_at
           OR mapped_fixture IS DISTINCT FROM NEW.fixture_id THEN
            RAISE EXCEPTION 'provenance_mismatch: invalid fixture observation'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_current_fixture_observation_provenance';
        END IF;
        SELECT r.status, r.kickoff_precision, o.provider_updated_at
          INTO current_status, current_precision, current_provider_updated
        FROM football.current_fixture_observation o
        JOIN football.current_fixture_revision r ON r.revision_id = o.revision_id
        WHERE o.source_id = NEW.source_id AND o.external_id = NEW.external_id
          AND o.observation_id <> NEW.observation_id
          AND o.retrieved_at <= NEW.retrieved_at
        ORDER BY o.retrieved_at DESC, o.observation_id DESC LIMIT 1;
        SELECT count(*) INTO later_count
        FROM football.current_fixture_observation o
        WHERE o.source_id = NEW.source_id AND o.external_id = NEW.external_id
          AND o.observation_id <> NEW.observation_id
          AND o.retrieved_at > NEW.retrieved_at;
        IF later_count <> 0 OR (current_status IS NOT NULL AND (
            (current_status = 'cancelled' AND (
                SELECT status FROM football.current_fixture_revision
                WHERE revision_id = NEW.revision_id
            ) <> 'cancelled')
            OR (current_status = 'abandoned' AND (
                SELECT status FROM football.current_fixture_revision
                WHERE revision_id = NEW.revision_id
            ) <> 'abandoned')
            OR (current_status = 'in_progress' AND (
                SELECT status FROM football.current_fixture_revision
                WHERE revision_id = NEW.revision_id
            ) NOT IN ('in_progress', 'abandoned'))
            OR (current_precision = 'exact' AND (
                SELECT kickoff_precision FROM football.current_fixture_revision
                WHERE revision_id = NEW.revision_id
            ) = 'date_only')
            OR (current_provider_updated IS NOT NULL
                AND (NEW.provider_updated_at IS NULL
                     OR NEW.provider_updated_at < current_provider_updated))
        )) THEN
            RAISE EXCEPTION 'chronology_violation: regressive fixture observation'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_current_fixture_observation_chronology';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_current_fixture_observation
    AFTER INSERT ON football.current_fixture_observation
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION football.validate_current_fixture_observation()
    """,
    """
    CREATE FUNCTION football.validate_current_result_observation()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        cache_source text;
        cache_capability text;
        cache_fetched timestamptz;
        mapped_fixture uuid;
        latest_status text;
        latest_kickoff timestamptz;
    BEGIN
        SELECT source_id, capability, fetched_at
          INTO cache_source, cache_capability, cache_fetched
        FROM provider_cache.response WHERE cache_key_sha256 = NEW.cache_key_sha256;
        SELECT fixture_id INTO mapped_fixture
        FROM football.current_fixture_source_reference
        WHERE source_id = NEW.source_id AND external_id = NEW.external_id;
        SELECT r.status, r.kickoff_at INTO latest_status, latest_kickoff
        FROM football.current_fixture_observation o
        JOIN football.current_fixture_revision r ON r.revision_id = o.revision_id
        WHERE o.source_id = NEW.source_id AND o.external_id = NEW.external_id
          AND o.retrieved_at <= NEW.retrieved_at
        ORDER BY o.retrieved_at DESC, o.observation_id DESC LIMIT 1;
        IF cache_source IS DISTINCT FROM NEW.source_id
           OR cache_capability IS DISTINCT FROM 'results'
           OR cache_fetched IS DISTINCT FROM NEW.retrieved_at
           OR mapped_fixture IS DISTINCT FROM NEW.fixture_id
           OR latest_status IS NULL
           OR latest_status IN ('cancelled', 'abandoned')
           OR (NEW.completed_at IS NOT NULL
               AND NEW.completed_at < latest_kickoff) THEN
            RAISE EXCEPTION 'provenance_mismatch: result has no valid fixture state'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_current_result_observation_provenance';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_current_result_observation
    AFTER INSERT ON football.current_result_observation
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION football.validate_current_result_observation()
    """,
    """
    CREATE FUNCTION football.validate_current_fixture_batch()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        member_count integer;
        provenance_count integer;
        bad_members integer;
        bad_order integer;
        missing_date_members integer;
        maximum_retrieval timestamptz;
        date_only_count integer;
    BEGIN
        SELECT count(*), count(*) FILTER (WHERE (
                   r.competition_id <> NEW.competition_id
                   OR r.season_id <> NEW.season_id
                   OR r.source_local_date <> NEW.source_local_date
                   OR (NEW.batch_kind = 'exact_kickoff' AND (
                       r.kickoff_precision <> 'exact'
                       OR r.kickoff_at <> NEW.exact_kickoff_at
                   ))
               )), count(*) FILTER (WHERE r.kickoff_precision = 'date_only')
          INTO member_count, bad_members, date_only_count
        FROM football.current_fixture_batch_member m
        JOIN football.current_fixture_revision r ON r.revision_id = m.revision_id
        WHERE m.batch_id = NEW.batch_id;
        SELECT count(*), max(c.fetched_at)
          INTO provenance_count, maximum_retrieval
        FROM football.current_fixture_batch_provenance p
        JOIN provider_cache.response c
          ON c.cache_key_sha256 = p.cache_key_sha256
        WHERE p.batch_id = NEW.batch_id AND c.capability = 'fixtures';
        SELECT count(*) INTO bad_order FROM (
            SELECT member_ordinal,
                   row_number() OVER (ORDER BY fixture_id) - 1 AS expected
            FROM football.current_fixture_batch_member
            WHERE batch_id = NEW.batch_id
        ) ordered WHERE member_ordinal <> expected;
        SELECT count(*) INTO missing_date_members
        FROM football.current_fixture_observation o
        JOIN football.current_fixture_revision r ON r.revision_id = o.revision_id
        WHERE NEW.batch_kind = 'date_only_date'
          AND r.competition_id = NEW.competition_id
          AND r.season_id = NEW.season_id
          AND r.source_local_date = NEW.source_local_date
          AND EXISTS (
              SELECT 1 FROM football.current_fixture_batch_provenance p
              WHERE p.batch_id = NEW.batch_id
                AND p.cache_key_sha256 = o.cache_key_sha256
          )
          AND NOT EXISTS (
              SELECT 1 FROM football.current_fixture_batch_member m
              WHERE m.batch_id = NEW.batch_id AND m.fixture_id = o.fixture_id
          );
        IF member_count = 0 OR provenance_count = 0 OR bad_members <> 0
           OR bad_order <> 0 OR missing_date_members <> 0
           OR maximum_retrieval IS DISTINCT FROM NEW.knowledge_available_at
           OR (NEW.batch_kind = 'date_only_date' AND (
               date_only_count = 0
               OR NEW.feature_cutoff_at <> make_timestamptz(
                   extract(year FROM NEW.source_local_date)::integer,
                   extract(month FROM NEW.source_local_date)::integer,
                   extract(day FROM NEW.source_local_date)::integer,
                   0, 0, 0, NEW.source_timezone
               ) - interval '1 microsecond'
           )) THEN
            RAISE EXCEPTION 'chronology_violation: invalid current fixture batch'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_current_fixture_batch_complete';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_current_fixture_batch
    AFTER INSERT ON football.current_fixture_batch
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION football.validate_current_fixture_batch()
    """,
    """
    CREATE FUNCTION football.validate_current_standing_snapshot()
    RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        cache_source text;
        cache_capability text;
        cache_fetched timestamptz;
        row_count integer;
        reference_count integer;
        bad_members integer;
        bad_totals integer;
    BEGIN
        SELECT source_id, capability, fetched_at
          INTO cache_source, cache_capability, cache_fetched
        FROM provider_cache.response WHERE cache_key_sha256 = NEW.cache_key_sha256;
        SELECT count(*), count(*) FILTER (WHERE ref.source_id = NEW.source_id)
          INTO row_count, reference_count
        FROM football.current_standing_row r
        LEFT JOIN football.current_standing_source_reference ref
          ON ref.snapshot_id = r.snapshot_id AND ref.team_id = r.team_id
        WHERE r.snapshot_id = NEW.snapshot_id;
        SELECT count(*) INTO bad_members
        FROM football.current_standing_row r
        WHERE r.snapshot_id = NEW.snapshot_id AND NOT EXISTS (
            SELECT 1 FROM identity.season_membership m
            WHERE m.competition_id = NEW.competition_id
              AND m.season_id = NEW.season_id AND m.team_id = r.team_id
        );
        WITH known_results AS (
            SELECT cr.* FROM football.current_completed_result cr
            WHERE cr.competition_id = NEW.competition_id
              AND cr.season_id = NEW.season_id
              AND EXISTS (
                  SELECT 1 FROM football.current_result_observation ro
                  WHERE ro.result_id = cr.result_id
                    AND ro.retrieved_at <= NEW.retrieved_at
              )
        ), team_events AS (
            SELECT home_team_id AS team_id, 1 AS played,
                   (outcome = 'home_win')::int AS won,
                   (outcome = 'draw')::int AS drawn,
                   (outcome = 'away_win')::int AS lost,
                   full_time_home_goals AS goals_for,
                   full_time_away_goals AS goals_against
            FROM known_results
            UNION ALL
            SELECT away_team_id, 1, (outcome = 'away_win')::int,
                   (outcome = 'draw')::int, (outcome = 'home_win')::int,
                   full_time_away_goals, full_time_home_goals
            FROM known_results
        ), totals AS (
            SELECT team_id, sum(played) AS played, sum(won) AS won,
                   sum(drawn) AS drawn, sum(lost) AS lost,
                   sum(goals_for) AS goals_for,
                   sum(goals_against) AS goals_against
            FROM team_events GROUP BY team_id
        )
        SELECT count(*) INTO bad_totals
        FROM football.current_standing_row r
        LEFT JOIN totals t ON t.team_id = r.team_id
        WHERE r.snapshot_id = NEW.snapshot_id AND (
            r.played <> coalesce(t.played, 0)
            OR r.won <> coalesce(t.won, 0)
            OR r.drawn <> coalesce(t.drawn, 0)
            OR r.lost <> coalesce(t.lost, 0)
            OR r.goals_for <> coalesce(t.goals_for, 0)
            OR r.goals_against <> coalesce(t.goals_against, 0)
        );
        IF cache_source IS DISTINCT FROM NEW.source_id
           OR cache_capability IS DISTINCT FROM 'standings'
           OR cache_fetched IS DISTINCT FROM NEW.retrieved_at
           OR row_count <> 20 OR reference_count <> 20
           OR bad_members <> 0 OR bad_totals <> 0 THEN
            RAISE EXCEPTION
                'provenance_mismatch: standings incomplete or unreconciled'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_current_standing_snapshot_complete';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_current_standing_snapshot
    AFTER INSERT ON football.current_standing_snapshot
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION football.validate_current_standing_snapshot()
    """,
)


IMMUTABLE_TABLES: tuple[str, ...] = (
    "current_fixture_source_reference",
    "current_fixture_revision",
    "current_fixture_observation",
    "current_fixture_batch",
    "current_fixture_batch_provenance",
    "current_fixture_batch_member",
    "current_completed_result",
    "current_result_observation",
    "current_standing_snapshot",
    "current_standing_row",
    "current_standing_source_reference",
)


def upgrade() -> None:
    """Create immutable current-season synchronization structures."""

    for statement in DDL:
        op.execute(sa.text(statement))
    for table in IMMUTABLE_TABLES:
        op.execute(
            sa.text(
                "CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE "
                f"ON football.{table} FOR EACH ROW EXECUTE FUNCTION "
                "persistence.reject_immutable_mutation()"
            )
        )


def downgrade() -> None:
    """Remove current-season synchronization structures."""

    for table in reversed(IMMUTABLE_TABLES):
        op.execute(sa.text(f"DROP TABLE football.{table} CASCADE"))
    op.execute(
        sa.text("DROP FUNCTION IF EXISTS football.validate_current_standing_snapshot()")
    )
    op.execute(
        sa.text("DROP FUNCTION IF EXISTS football.validate_current_fixture_batch()")
    )
    op.execute(
        sa.text(
            "DROP FUNCTION IF EXISTS football.validate_current_result_observation()"
        )
    )
    op.execute(
        sa.text(
            "DROP FUNCTION IF EXISTS football.validate_current_fixture_observation()"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE football.fixture_revision "
            "DROP CONSTRAINT ck_fixture_revision_status, "
            "DROP CONSTRAINT ck_fixture_revision_state"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE football.fixture_revision "
            "ADD CONSTRAINT ck_fixture_revision_status CHECK (status IN ("
            "'scheduled', 'postponed', 'cancelled', 'in_progress', 'finished')), "
            "ADD CONSTRAINT ck_fixture_revision_state CHECK ("
            "(status = 'finished' AND full_time_home_goals IS NOT NULL "
            "AND outcome IS NOT NULL) OR "
            "(status IN ('scheduled', 'postponed', 'cancelled') "
            "AND full_time_home_goals IS NULL "
            "AND half_time_home_goals IS NULL AND outcome IS NULL) "
            "OR status = 'in_progress')"
        )
    )
