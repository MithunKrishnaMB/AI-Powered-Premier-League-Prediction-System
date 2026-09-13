"""Step 5.7: raw ingestion, provider cache and simulation structures.

Revision ID: f0004_step_5_7
Revises: f0003_step_5_6
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0004_step_5_7"
down_revision: str | Sequence[str] | None = "f0003_step_5_6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DDL: tuple[str, ...] = (
    "CREATE SCHEMA ingestion",
    "CREATE SCHEMA provider_cache",
    "CREATE SCHEMA simulation",
    """
    CREATE TABLE ingestion.raw_capture (
        source_id text NOT NULL,
        artifact_id text NOT NULL,
        historical_manifest_sha256 persistence.sha256 NOT NULL,
        object_sha256 persistence.sha256 NOT NULL,
        source_url text NOT NULL,
        destination text NOT NULL,
        captured_at timestamptz NOT NULL,
        encoding text NOT NULL,
        expected_byte_count bigint NOT NULL,
        expected_row_count integer NOT NULL,
        required_columns text[] NOT NULL,
        immutable boolean NOT NULL,
        PRIMARY KEY (source_id, artifact_id),
        CONSTRAINT fk_raw_capture_source FOREIGN KEY (source_id)
            REFERENCES identity.source (source_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_raw_capture_manifest FOREIGN KEY (
            historical_manifest_sha256
        ) REFERENCES identity.reference_document (document_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_raw_capture_object FOREIGN KEY (object_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_raw_capture_url CHECK (source_url ~ '^https://[^/]+/'),
        CONSTRAINT ck_raw_capture_destination CHECK (
            destination <> '' AND destination !~ '(^|/)[.][.](/|$)'
            AND destination !~ '^[A-Za-z]:[/\\\\]'
            AND destination !~ '^[/\\\\]'
        ),
        CONSTRAINT ck_raw_capture_contract CHECK (
            encoding = 'utf-8' AND expected_byte_count > 0
            AND expected_row_count > 0 AND cardinality(required_columns) > 0
            AND immutable
        )
    )
    """,
    """
    CREATE FUNCTION ingestion.validate_raw_capture()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        object_bytes bigint;
        capture_host text;
    BEGIN
        SELECT byte_count INTO object_bytes
        FROM lineage.stored_object WHERE sha256 = NEW.object_sha256;
        IF object_bytes IS DISTINCT FROM NEW.expected_byte_count THEN
            RAISE EXCEPTION 'checksum_mismatch: raw byte count differs'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_raw_capture_object_bytes';
        END IF;
        capture_host := lower(split_part(split_part(NEW.source_url, '://', 2), '/', 1));
        IF NOT EXISTS (
            SELECT 1 FROM identity.source_allowed_host h
            WHERE h.source_id = NEW.source_id AND lower(h.hostname) = capture_host
        ) THEN
            RAISE EXCEPTION 'provenance_mismatch: source host is not allowed'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_raw_capture_allowed_host';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_raw_capture
    AFTER INSERT ON ingestion.raw_capture
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ingestion.validate_raw_capture()
    """,
    """
    ALTER TABLE football.canonical_dataset
      ADD CONSTRAINT fk_canonical_dataset_raw_capture FOREIGN KEY (
          raw_source_id, raw_artifact_id
      ) REFERENCES ingestion.raw_capture (source_id, artifact_id)
      ON UPDATE RESTRICT ON DELETE RESTRICT
    """,
    """
    ALTER TABLE feature.feature_dataset
      ADD CONSTRAINT fk_feature_dataset_raw_capture FOREIGN KEY (
          raw_source_id, raw_artifact_id
      ) REFERENCES ingestion.raw_capture (source_id, artifact_id)
      ON UPDATE RESTRICT ON DELETE RESTRICT
    """,
    """
    ALTER TABLE ml.training_feature_source
      ADD CONSTRAINT fk_training_feature_source_raw_capture FOREIGN KEY (
          raw_source_id, raw_artifact_id
      ) REFERENCES ingestion.raw_capture (source_id, artifact_id)
      ON UPDATE RESTRICT ON DELETE RESTRICT
    """,
    """
    CREATE TABLE provider_cache.response (
        cache_key_sha256 persistence.sha256 PRIMARY KEY,
        source_id text NOT NULL,
        capability text NOT NULL,
        request_identity_sha256 persistence.sha256 NOT NULL,
        response_sha256 persistence.sha256 NOT NULL,
        fetched_at timestamptz NOT NULL,
        expires_at timestamptz NOT NULL,
        http_status smallint NOT NULL,
        media_type text NOT NULL,
        etag text,
        last_modified text,
        CONSTRAINT uq_provider_cache_response UNIQUE (
            source_id, capability, request_identity_sha256, fetched_at
        ),
        CONSTRAINT fk_provider_cache_source FOREIGN KEY (source_id)
            REFERENCES identity.source (source_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_provider_cache_request FOREIGN KEY (
            request_identity_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_provider_cache_response_object FOREIGN KEY (
            response_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_provider_cache_window CHECK (expires_at > fetched_at),
        CONSTRAINT ck_provider_cache_status CHECK (
            http_status BETWEEN 100 AND 599
        ),
        CONSTRAINT ck_provider_cache_capability CHECK (
            capability IN ('fixtures', 'results', 'standings', 'metadata')
        )
    )
    """,
    """
    CREATE TABLE simulation.scoreline_distribution (
        distribution_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        schema_version persistence.positive_version NOT NULL,
        fixture_id uuid NOT NULL,
        home_team_id uuid NOT NULL,
        away_team_id uuid NOT NULL,
        CONSTRAINT uq_distribution_fixture_snapshot UNIQUE (
            distribution_id, fixture_id, home_team_id, away_team_id
        ),
        CONSTRAINT fk_distribution_identity_bytes FOREIGN KEY (identity_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_distribution_fixture FOREIGN KEY (
            fixture_id, home_team_id, away_team_id
        ) REFERENCES football.fixture (fixture_id, home_team_id, away_team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_distribution_v1 CHECK (schema_version = 1),
        CONSTRAINT ck_distribution_teams CHECK (home_team_id <> away_team_id),
        CONSTRAINT ck_distribution_deterministic_id CHECK (
            distribution_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:season-simulation:scoreline-distribution:'
                || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE simulation.scoreline_probability (
        distribution_id uuid NOT NULL,
        score_ordinal integer NOT NULL,
        home_goals smallint NOT NULL,
        away_goals smallint NOT NULL,
        probability persistence.positive_mass NOT NULL,
        PRIMARY KEY (distribution_id, score_ordinal),
        CONSTRAINT uq_scoreline_probability UNIQUE (
            distribution_id, home_goals, away_goals
        ),
        CONSTRAINT fk_scoreline_probability_owner FOREIGN KEY (distribution_id)
            REFERENCES simulation.scoreline_distribution (distribution_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_scoreline_ordinal CHECK (score_ordinal >= 0),
        CONSTRAINT ck_scoreline_goals CHECK (
            home_goals BETWEEN 0 AND 40 AND away_goals BETWEEN 0 AND 40
        )
    )
    """,
    """
    CREATE FUNCTION simulation.validate_scoreline_distribution()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        row_total integer;
        ordinal_total integer;
        mass double precision;
        ordered boolean;
    BEGIN
        SELECT count(*), count(DISTINCT score_ordinal), sum(probability),
               bool_and(score_ordinal = expected_ordinal)
        INTO row_total, ordinal_total, mass, ordered
        FROM (
            SELECT p.*,
                   row_number() OVER (
                       ORDER BY home_goals, away_goals
                   )::integer - 1 AS expected_ordinal
            FROM simulation.scoreline_probability p
            WHERE p.distribution_id = NEW.distribution_id
        ) values_for_distribution;
        IF row_total = 0 OR ordinal_total <> row_total OR NOT coalesce(ordered, false)
           OR abs(mass - 1.0) > 1e-12 THEN
            RAISE EXCEPTION 'invalid_probability_mass: incomplete scorelines'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_scoreline_distribution_complete';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_scoreline_distribution
    AFTER INSERT ON simulation.scoreline_distribution
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION simulation.validate_scoreline_distribution()
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_scoreline_probability
    AFTER INSERT ON simulation.scoreline_probability
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION simulation.validate_scoreline_distribution()
    """,
    """
    CREATE TABLE simulation.distribution_provenance (
        provenance_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        distribution_id uuid NOT NULL,
        producer_kind text NOT NULL,
        producer_identity text NOT NULL,
        producer_version text NOT NULL,
        input_sha256 persistence.sha256 NOT NULL,
        artifact_id uuid,
        runtime_contract text NOT NULL,
        numerical_contract text NOT NULL,
        approval_context text NOT NULL,
        CONSTRAINT uq_distribution_provenance_snapshot UNIQUE (
            provenance_id, distribution_id
        ),
        CONSTRAINT fk_distribution_provenance_distribution FOREIGN KEY (
            distribution_id
        ) REFERENCES simulation.scoreline_distribution (distribution_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_distribution_provenance_input FOREIGN KEY (input_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_distribution_provenance_artifact FOREIGN KEY (artifact_id)
            REFERENCES model.model_artifact (artifact_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_distribution_provenance_kind CHECK (
            producer_kind IN ('explicit_input', 'model_artifact', 'provider')
        ),
        CONSTRAINT ck_distribution_provenance_artifact CHECK (
            (producer_kind = 'model_artifact' AND artifact_id IS NOT NULL)
            OR (producer_kind <> 'model_artifact' AND artifact_id IS NULL)
        ),
        CONSTRAINT ck_distribution_provenance_deterministic_id CHECK (
            provenance_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:distribution-provenance:' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE FUNCTION simulation.reject_classifier_scoreline_provenance()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    BEGIN
        IF NEW.producer_kind = 'model_artifact' AND NOT EXISTS (
            SELECT 1
            FROM model.model_artifact a
            JOIN model.semantic_model m ON m.model_id = a.model_id
            JOIN model.prediction_contract c
              ON c.model_id = m.model_id AND c.schema_version = 1
            JOIN model.score_model_specification s ON s.model_id = m.model_id
            WHERE a.artifact_id = NEW.artifact_id
              AND c.produces_scorelines AND s.produces_scorelines
        ) THEN
            RAISE EXCEPTION 'provenance_mismatch: artifact is not scoreline-capable'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_distribution_producer_scoreline_capable';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_distribution_provenance
    AFTER INSERT ON simulation.distribution_provenance
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION simulation.reject_classifier_scoreline_provenance()
    """,
    """
    CREATE TABLE simulation.simulation_input (
        input_sha256 persistence.sha256 PRIMARY KEY,
        schema_version persistence.positive_version NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        CONSTRAINT uq_simulation_input_snapshot UNIQUE (
            input_sha256, competition_id, season_id
        ),
        CONSTRAINT fk_simulation_input_bytes FOREIGN KEY (input_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_simulation_input_season FOREIGN KEY (
            competition_id, season_id
        ) REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_simulation_input_v1 CHECK (schema_version = 1)
    )
    """,
    """
    CREATE TABLE simulation.simulation_input_team (
        input_sha256 persistence.sha256 NOT NULL,
        ordinal integer NOT NULL,
        team_id uuid NOT NULL,
        PRIMARY KEY (input_sha256, ordinal),
        CONSTRAINT uq_simulation_input_team UNIQUE (input_sha256, team_id),
        CONSTRAINT fk_simulation_input_team_owner FOREIGN KEY (input_sha256)
            REFERENCES simulation.simulation_input (input_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_simulation_input_team_identity FOREIGN KEY (team_id)
            REFERENCES identity.team (team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_simulation_input_team_ordinal CHECK (
            ordinal BETWEEN 0 AND 19
        )
    )
    """,
    """
    CREATE TABLE simulation.simulation_input_completed_fixture (
        input_sha256 persistence.sha256 NOT NULL,
        ordinal integer NOT NULL,
        fixture_id uuid NOT NULL,
        home_team_id uuid NOT NULL,
        away_team_id uuid NOT NULL,
        home_goals smallint NOT NULL,
        away_goals smallint NOT NULL,
        outcome text NOT NULL,
        PRIMARY KEY (input_sha256, ordinal),
        CONSTRAINT uq_simulation_completed_fixture UNIQUE (
            input_sha256, fixture_id
        ),
        CONSTRAINT fk_simulation_completed_owner FOREIGN KEY (input_sha256)
            REFERENCES simulation.simulation_input (input_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_simulation_completed_fixture FOREIGN KEY (
            fixture_id, home_team_id, away_team_id
        ) REFERENCES football.fixture (fixture_id, home_team_id, away_team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_simulation_completed_ordinal CHECK (ordinal >= 0),
        CONSTRAINT ck_simulation_completed_goals CHECK (
            home_goals >= 0 AND away_goals >= 0
        ),
        CONSTRAINT ck_simulation_completed_outcome CHECK (
            outcome = CASE WHEN home_goals > away_goals THEN 'home_win'
                WHEN home_goals < away_goals THEN 'away_win' ELSE 'draw' END
        )
    )
    """,
    """
    CREATE TABLE simulation.simulation_input_batch (
        input_sha256 persistence.sha256 NOT NULL,
        batch_ordinal integer NOT NULL,
        batch_kind text NOT NULL,
        competition_date date NOT NULL,
        exact_kickoff_at timestamptz,
        PRIMARY KEY (input_sha256, batch_ordinal),
        CONSTRAINT fk_simulation_batch_owner FOREIGN KEY (input_sha256)
            REFERENCES simulation.simulation_input (input_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_simulation_batch_ordinal CHECK (batch_ordinal >= 0),
        CONSTRAINT ck_simulation_batch_kind CHECK (
            (batch_kind = 'date_only_date' AND exact_kickoff_at IS NULL)
            OR (batch_kind = 'exact_kickoff' AND exact_kickoff_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE simulation.simulation_input_remaining_fixture (
        input_sha256 persistence.sha256 NOT NULL,
        ordinal integer NOT NULL,
        fixture_id uuid NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        home_team_id uuid NOT NULL,
        away_team_id uuid NOT NULL,
        kickoff_at timestamptz NOT NULL,
        kickoff_precision text NOT NULL,
        distribution_id uuid NOT NULL,
        provenance_id uuid NOT NULL,
        batch_ordinal integer NOT NULL,
        batch_member_ordinal integer NOT NULL,
        PRIMARY KEY (input_sha256, ordinal),
        CONSTRAINT uq_simulation_remaining_fixture UNIQUE (
            input_sha256, fixture_id
        ),
        CONSTRAINT uq_simulation_batch_member UNIQUE (
            input_sha256, batch_ordinal, batch_member_ordinal
        ),
        CONSTRAINT fk_simulation_remaining_owner FOREIGN KEY (
            input_sha256, competition_id, season_id
        ) REFERENCES simulation.simulation_input (
            input_sha256, competition_id, season_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_simulation_remaining_fixture FOREIGN KEY (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) REFERENCES football.fixture (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_simulation_remaining_distribution FOREIGN KEY (
            distribution_id, fixture_id, home_team_id, away_team_id
        ) REFERENCES simulation.scoreline_distribution (
            distribution_id, fixture_id, home_team_id, away_team_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_simulation_remaining_provenance FOREIGN KEY (
            provenance_id, distribution_id
        ) REFERENCES simulation.distribution_provenance (
            provenance_id, distribution_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_simulation_remaining_batch FOREIGN KEY (
            input_sha256, batch_ordinal
        ) REFERENCES simulation.simulation_input_batch (
            input_sha256, batch_ordinal
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_simulation_remaining_ordinals CHECK (
            ordinal >= 0 AND batch_member_ordinal >= 0
        ),
        CONSTRAINT ck_simulation_remaining_precision CHECK (
            kickoff_precision IN ('exact', 'date_only')
        )
    )
    """,
    """
    CREATE FUNCTION simulation.validate_simulation_input()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        owner_competition_id text;
        owner_season_id text;
        team_total integer;
        team_order_valid boolean;
        bad_members integer;
        overlap_total integer;
        bad_batches integer;
        mixed_date_batches integer;
    BEGIN
        SELECT competition_id, season_id
        INTO owner_competition_id, owner_season_id
        FROM simulation.simulation_input
        WHERE input_sha256 = NEW.input_sha256;
        SELECT count(*), bool_and(ordinal = expected_ordinal)
        INTO team_total, team_order_valid
        FROM (
            SELECT t.*, row_number() OVER (ORDER BY team_id)::integer - 1
                AS expected_ordinal
            FROM simulation.simulation_input_team t
            WHERE input_sha256 = NEW.input_sha256
        ) ordered_teams;
        IF team_total <> 20 OR NOT coalesce(team_order_valid, false) THEN
            RAISE EXCEPTION 'provenance_mismatch: simulation input requires 20 teams'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_simulation_input_twenty_teams';
        END IF;
        SELECT count(*) INTO bad_members
        FROM simulation.simulation_input_team t
        WHERE t.input_sha256 = NEW.input_sha256
          AND NOT EXISTS (
              SELECT 1 FROM identity.season_membership m
              WHERE m.competition_id = owner_competition_id
                AND m.season_id = owner_season_id AND m.team_id = t.team_id
          );
        IF bad_members <> 0 THEN
            RAISE EXCEPTION 'provenance_mismatch: input team is not a season member'
                USING ERRCODE = 'foreign_key_violation',
                      CONSTRAINT = 'fk_simulation_input_team_season_membership';
        END IF;
        SELECT count(*) INTO overlap_total
        FROM simulation.simulation_input_completed_fixture c
        JOIN simulation.simulation_input_remaining_fixture r
          USING (input_sha256, fixture_id)
        WHERE c.input_sha256 = NEW.input_sha256;
        IF overlap_total <> 0 THEN
            RAISE EXCEPTION 'provenance_mismatch: fixture sets overlap'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_simulation_input_fixture_disjoint';
        END IF;
        SELECT count(*) INTO bad_batches
        FROM simulation.simulation_input_remaining_fixture r
        JOIN simulation.simulation_input_batch b
          USING (input_sha256, batch_ordinal)
        WHERE r.input_sha256 = NEW.input_sha256
          AND (
            (b.batch_kind = 'date_only_date' AND (
                r.kickoff_at AT TIME ZONE 'Europe/London'
            )::date <> b.competition_date)
            OR (b.batch_kind = 'exact_kickoff'
                AND (r.kickoff_precision <> 'exact'
                     OR r.kickoff_at <> b.exact_kickoff_at))
          );
        IF bad_batches <> 0 THEN
            RAISE EXCEPTION 'chronology_violation: simulation fixture batch differs'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_simulation_input_batch_consistency';
        END IF;
        SELECT count(*) INTO mixed_date_batches
        FROM simulation.simulation_input_batch d
        WHERE d.input_sha256 = NEW.input_sha256
          AND d.batch_kind = 'date_only_date'
          AND EXISTS (
              SELECT 1 FROM simulation.simulation_input_batch other
              WHERE other.input_sha256 = d.input_sha256
                AND other.competition_date = d.competition_date
                AND other.batch_ordinal <> d.batch_ordinal
          );
        IF mixed_date_batches <> 0 THEN
            RAISE EXCEPTION 'chronology_violation: invalid date batch'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_simulation_date_only_batch_complete';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_simulation_input
    AFTER INSERT ON simulation.simulation_input
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION simulation.validate_simulation_input()
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_simulation_input_team
    AFTER INSERT ON simulation.simulation_input_team
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION simulation.validate_simulation_input()
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_simulation_input_completed
    AFTER INSERT ON simulation.simulation_input_completed_fixture
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION simulation.validate_simulation_input()
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_simulation_input_batch
    AFTER INSERT ON simulation.simulation_input_batch
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION simulation.validate_simulation_input()
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_simulation_input_remaining
    AFTER INSERT ON simulation.simulation_input_remaining_fixture
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION simulation.validate_simulation_input()
    """,
    """
    CREATE TABLE simulation.simulation_run (
        simulation_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        input_sha256 persistence.sha256 NOT NULL,
        schema_version persistence.positive_version NOT NULL,
        algorithm_version persistence.positive_version NOT NULL,
        simulation_seed persistence.uint64_seed NOT NULL,
        simulation_count integer NOT NULL,
        CONSTRAINT uq_simulation_run_contract UNIQUE (
            input_sha256, simulation_seed, algorithm_version, simulation_count
        ),
        CONSTRAINT fk_simulation_run_input FOREIGN KEY (input_sha256)
            REFERENCES simulation.simulation_input (input_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_simulation_run_identity_bytes FOREIGN KEY (identity_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_simulation_run_v1 CHECK (
            schema_version = 1 AND algorithm_version = 1
            AND simulation_count = 10000
        ),
        CONSTRAINT ck_simulation_run_deterministic_id CHECK (
            simulation_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:vectorized-season-simulation:' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE simulation.result_component (
        simulation_id uuid NOT NULL,
        role text NOT NULL,
        object_sha256 persistence.sha256 NOT NULL,
        dtype text NOT NULL,
        shape integer[] NOT NULL,
        axis_order text[] NOT NULL,
        PRIMARY KEY (simulation_id, role),
        CONSTRAINT uq_result_component_object UNIQUE (object_sha256),
        CONSTRAINT fk_result_component_run FOREIGN KEY (simulation_id)
            REFERENCES simulation.simulation_run (simulation_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_result_component_object FOREIGN KEY (object_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_result_component_contract CHECK (
            (role IN ('points', 'goals_for', 'goals_against')
             AND dtype = 'int64' AND axis_order = ARRAY['run','team']::text[]
             AND cardinality(shape) = 2 AND shape[1] = 10000 AND shape[2] = 20)
            OR
            (role IN ('sampled_home_goals', 'sampled_away_goals')
             AND dtype = 'int16' AND axis_order = ARRAY['run','fixture']::text[]
             AND cardinality(shape) = 2 AND shape[1] = 10000 AND shape[2] >= 0)
            OR
            (role = 'position_mass' AND dtype = 'float64'
             AND axis_order = ARRAY['run','team','position']::text[]
             AND shape = ARRAY[10000,20,20]::integer[])
        )
    )
    """,
    """
    CREATE FUNCTION simulation.validate_result_components()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        run_id uuid;
        role_total integer;
        bad_profile integer;
        expected_fixture_count integer;
        bad_fixture_shape integer;
    BEGIN
        run_id := NEW.simulation_id;
        SELECT count(*), count(*) FILTER (
            WHERE o.canonicalization_profile <> 'numpy_array_v1'
        ) INTO role_total, bad_profile
        FROM simulation.result_component c
        JOIN lineage.stored_object o ON o.sha256 = c.object_sha256
        WHERE c.simulation_id = run_id;
        SELECT count(*) INTO expected_fixture_count
        FROM simulation.simulation_run r
        JOIN simulation.simulation_input_remaining_fixture f
          ON f.input_sha256 = r.input_sha256
        WHERE r.simulation_id = run_id;
        SELECT count(*) INTO bad_fixture_shape
        FROM simulation.result_component
        WHERE simulation_id = run_id
          AND role IN ('sampled_home_goals', 'sampled_away_goals')
          AND shape[2] <> expected_fixture_count;
        IF role_total <> 6 OR bad_profile <> 0 OR bad_fixture_shape <> 0 THEN
            RAISE EXCEPTION 'numerical_contract_mismatch: incomplete results'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_result_components_complete';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_result_components_from_run
    AFTER INSERT ON simulation.simulation_run
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION simulation.validate_result_components()
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_result_components_from_component
    AFTER INSERT ON simulation.result_component
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION simulation.validate_result_components()
    """,
    """
    CREATE TABLE simulation.simulation_summary (
        summary_id uuid PRIMARY KEY,
        identity_sha256 persistence.sha256 NOT NULL UNIQUE,
        simulation_id uuid NOT NULL UNIQUE,
        summary_sha256 persistence.sha256 NOT NULL UNIQUE,
        schema_version persistence.positive_version NOT NULL,
        algorithm_version persistence.positive_version NOT NULL,
        simulation_count integer NOT NULL,
        season_id text NOT NULL,
        CONSTRAINT fk_simulation_summary_run FOREIGN KEY (simulation_id)
            REFERENCES simulation.simulation_run (simulation_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_simulation_summary_identity_bytes FOREIGN KEY (
            identity_sha256
        ) REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_simulation_summary_bytes FOREIGN KEY (summary_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_simulation_summary_v1 CHECK (
            schema_version = 1 AND algorithm_version = 1
            AND simulation_count = 10000
            AND season_id ~ '^[0-9]{4}-[0-9]{4}$'
        ),
        CONSTRAINT ck_simulation_summary_deterministic_id CHECK (
            summary_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:simulation-summary:' || identity_sha256
            )
        )
    )
    """,
    """
    CREATE TABLE simulation.team_summary (
        summary_id uuid NOT NULL,
        team_id uuid NOT NULL,
        team_ordinal integer NOT NULL,
        expected_points persistence.finite_float64 NOT NULL,
        expected_goals_for persistence.finite_float64 NOT NULL,
        expected_goals_against persistence.finite_float64 NOT NULL,
        expected_goal_difference persistence.finite_float64 NOT NULL,
        champion_probability persistence.probability NOT NULL,
        top_four_probability persistence.probability NOT NULL,
        top_six_probability persistence.probability NOT NULL,
        relegation_probability persistence.probability NOT NULL,
        PRIMARY KEY (summary_id, team_id),
        CONSTRAINT uq_team_summary_ordinal UNIQUE (summary_id, team_ordinal),
        CONSTRAINT fk_team_summary_owner FOREIGN KEY (summary_id)
            REFERENCES simulation.simulation_summary (summary_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_team_summary_team FOREIGN KEY (team_id)
            REFERENCES identity.team (team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_team_summary_ordinal CHECK (
            team_ordinal BETWEEN 0 AND 19
        ),
        CONSTRAINT ck_team_summary_goal_difference CHECK (
            abs(expected_goal_difference
                - (expected_goals_for - expected_goals_against)) <= 1e-12
        )
    )
    """,
    """
    CREATE TABLE simulation.position_probability (
        summary_id uuid NOT NULL,
        team_id uuid NOT NULL,
        position smallint NOT NULL,
        probability persistence.probability NOT NULL,
        PRIMARY KEY (summary_id, team_id, position),
        CONSTRAINT fk_position_probability_team_summary FOREIGN KEY (
            summary_id, team_id
        ) REFERENCES simulation.team_summary (summary_id, team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_position_probability_position CHECK (
            position BETWEEN 1 AND 20
        )
    )
    """,
    """
    CREATE FUNCTION simulation.validate_simulation_summary()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        team_total integer;
        position_total integer;
        bad_team_mass integer;
        bad_position_mass integer;
        bad_thresholds integer;
        bad_team_identity integer;
        team_order_valid boolean;
        run_season_id text;
        champion_mass double precision;
        top_four_mass double precision;
        top_six_mass double precision;
        relegation_mass double precision;
    BEGIN
        SELECT i.season_id INTO run_season_id
        FROM simulation.simulation_run r
        JOIN simulation.simulation_input i ON i.input_sha256 = r.input_sha256
        WHERE r.simulation_id = NEW.simulation_id;
        SELECT count(*), sum(champion_probability), sum(top_four_probability),
               sum(top_six_probability), sum(relegation_probability)
        INTO team_total, champion_mass, top_four_mass, top_six_mass,
             relegation_mass
        FROM simulation.team_summary WHERE summary_id = NEW.summary_id;
        SELECT count(*) INTO position_total
        FROM simulation.position_probability WHERE summary_id = NEW.summary_id;
        SELECT bool_and(team_ordinal = expected_ordinal)
        INTO team_order_valid
        FROM (
            SELECT t.team_id, t.team_ordinal,
                   row_number() OVER (ORDER BY t.team_id)::integer - 1
                       AS expected_ordinal
            FROM simulation.team_summary t
            WHERE t.summary_id = NEW.summary_id
        ) ordered_summary_teams;
        SELECT count(*) INTO bad_team_identity
        FROM simulation.team_summary t
        WHERE t.summary_id = NEW.summary_id
          AND NOT EXISTS (
              SELECT 1
              FROM simulation.simulation_run r
              JOIN simulation.simulation_input_team i
                ON i.input_sha256 = r.input_sha256
              WHERE r.simulation_id = NEW.simulation_id
                AND i.team_id = t.team_id
          );
        SELECT count(*) INTO bad_team_mass FROM (
            SELECT team_id FROM simulation.position_probability
            WHERE summary_id = NEW.summary_id GROUP BY team_id
            HAVING count(*) <> 20 OR abs(sum(probability) - 1.0) > 1e-12
        ) invalid_team;
        SELECT count(*) INTO bad_position_mass FROM (
            SELECT position FROM simulation.position_probability
            WHERE summary_id = NEW.summary_id GROUP BY position
            HAVING count(*) <> 20 OR abs(sum(probability) - 1.0) > 1e-12
        ) invalid_position;
        SELECT count(*) INTO bad_thresholds
        FROM simulation.team_summary t
        JOIN LATERAL (
            SELECT max(probability) FILTER (WHERE position = 1) AS champion,
                   sum(probability) FILTER (WHERE position <= 4) AS top_four,
                   sum(probability) FILTER (WHERE position <= 6) AS top_six,
                   sum(probability) FILTER (WHERE position >= 18) AS relegation
            FROM simulation.position_probability p
            WHERE p.summary_id = t.summary_id AND p.team_id = t.team_id
        ) p ON true
        WHERE t.summary_id = NEW.summary_id AND (
            abs(t.champion_probability - p.champion) > 1e-12
            OR abs(t.top_four_probability - p.top_four) > 1e-12
            OR abs(t.top_six_probability - p.top_six) > 1e-12
            OR abs(t.relegation_probability - p.relegation) > 1e-12
        );
        IF run_season_id IS DISTINCT FROM NEW.season_id
           OR team_total <> 20 OR position_total <> 400 OR bad_team_mass <> 0
           OR bad_team_identity <> 0 OR NOT coalesce(team_order_valid, true)
           OR bad_position_mass <> 0 OR bad_thresholds <> 0
           OR abs(champion_mass - 1.0) > 1e-12
           OR abs(top_four_mass - 4.0) > 1e-12
           OR abs(top_six_mass - 6.0) > 1e-12
           OR abs(relegation_mass - 3.0) > 1e-12 THEN
            RAISE EXCEPTION 'invalid_probability_mass: simulation summary is incomplete'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_simulation_summary_complete';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER validate_simulation_summary
    AFTER INSERT ON simulation.simulation_summary
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION simulation.validate_simulation_summary()
    """,
)


IMMUTABLE_TABLES: tuple[tuple[str, str], ...] = (
    ("ingestion", "raw_capture"),
    ("provider_cache", "response"),
    ("simulation", "scoreline_distribution"),
    ("simulation", "scoreline_probability"),
    ("simulation", "distribution_provenance"),
    ("simulation", "simulation_input"),
    ("simulation", "simulation_input_team"),
    ("simulation", "simulation_input_completed_fixture"),
    ("simulation", "simulation_input_batch"),
    ("simulation", "simulation_input_remaining_fixture"),
    ("simulation", "simulation_run"),
    ("simulation", "result_component"),
    ("simulation", "simulation_summary"),
    ("simulation", "team_summary"),
    ("simulation", "position_probability"),
)


def upgrade() -> None:
    """Create raw-ingestion, provider-cache and simulation structures."""

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
    """Remove Step 5.7 cross-schema constraints and structures."""

    op.execute(
        sa.text(
            "ALTER TABLE ml.training_feature_source "
            "DROP CONSTRAINT fk_training_feature_source_raw_capture"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE feature.feature_dataset "
            "DROP CONSTRAINT fk_feature_dataset_raw_capture"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE football.canonical_dataset "
            "DROP CONSTRAINT fk_canonical_dataset_raw_capture"
        )
    )
    op.execute(sa.text("DROP SCHEMA simulation CASCADE"))
    op.execute(sa.text("DROP SCHEMA provider_cache CASCADE"))
    op.execute(sa.text("DROP SCHEMA ingestion CASCADE"))
