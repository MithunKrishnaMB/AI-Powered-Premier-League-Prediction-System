"""Step 5.4: checked types, exact bytes, identities, seasons and fixtures.

Revision ID: f0001_step_5_4
Revises:
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0001_step_5_4"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DDL: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"',
    "CREATE SCHEMA persistence",
    "CREATE SCHEMA lineage",
    "CREATE SCHEMA identity",
    "CREATE SCHEMA football",
    """
    CREATE DOMAIN persistence.sha256 AS text
    CHECK (VALUE ~ '^[0-9a-f]{64}$')
    """,
    """
    CREATE DOMAIN persistence.positive_version AS smallint
    CHECK (VALUE > 0)
    """,
    """
    CREATE DOMAIN persistence.finite_float64 AS double precision
    CHECK (VALUE NOT IN (
        'NaN'::double precision,
        'Infinity'::double precision,
        '-Infinity'::double precision
    ))
    """,
    """
    CREATE DOMAIN persistence.probability AS double precision
    CHECK (
        VALUE NOT IN (
            'NaN'::double precision,
            'Infinity'::double precision,
            '-Infinity'::double precision
        )
        AND VALUE >= 0.0 AND VALUE <= 1.0
    )
    """,
    """
    CREATE DOMAIN persistence.positive_mass AS double precision
    CHECK (
        VALUE NOT IN (
            'NaN'::double precision,
            'Infinity'::double precision,
            '-Infinity'::double precision
        )
        AND VALUE > 0.0 AND VALUE <= 1.0
    )
    """,
    """
    CREATE DOMAIN persistence.uint64_seed AS numeric(20, 0)
    CHECK (VALUE >= 0 AND VALUE <= 18446744073709551615)
    """,
    """
    CREATE FUNCTION persistence.reject_immutable_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RAISE EXCEPTION 'immutable_record_violation: %.% cannot be %d',
            TG_TABLE_SCHEMA, TG_TABLE_NAME, lower(TG_OP)
            USING ERRCODE = '55000';
    END;
    $$
    """,
    """
    CREATE FUNCTION persistence.utc_iso8601(value timestamptz)
    RETURNS text
    LANGUAGE sql
    IMMUTABLE STRICT PARALLEL SAFE
    RETURN to_char(value AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
        || CASE
            WHEN extract(microseconds FROM value)::bigint % 1000000 = 0
                THEN ''
            ELSE '.' || rtrim(
                to_char(value AT TIME ZONE 'UTC', 'US'), '0'
            )
        END
        || '+00:00'
    """,
    """
    CREATE TABLE lineage.stored_object (
        sha256 persistence.sha256 PRIMARY KEY,
        byte_count bigint NOT NULL,
        media_type text NOT NULL,
        encoding text,
        format_id text NOT NULL,
        canonicalization_profile text NOT NULL,
        payload bytea NOT NULL,
        CONSTRAINT ck_stored_object_byte_count_positive
            CHECK (byte_count > 0),
        CONSTRAINT ck_stored_object_byte_count_matches
            CHECK (byte_count = octet_length(payload)),
        CONSTRAINT ck_stored_object_checksum_matches
            CHECK (sha256 = encode(digest(payload, 'sha256'), 'hex')),
        CONSTRAINT ck_stored_object_media_type
            CHECK (media_type IN (
                'application/json', 'application/x-ndjson', 'text/csv',
                'application/x-npy', 'application/octet-stream'
            )),
        CONSTRAINT ck_stored_object_format_id
            CHECK (format_id ~ '^[a-z0-9][a-z0-9._+-]*$'),
        CONSTRAINT ck_stored_object_canonicalization_profile
            CHECK (canonicalization_profile IN (
                'opaque', 'canonical_json_v1', 'canonical_jsonl_v1',
                'identity_json_v1', 'numpy_array_v1'
            )),
        CONSTRAINT ck_stored_object_encoding
            CHECK (
                (canonicalization_profile = 'numpy_array_v1' AND encoding IS NULL)
                OR
                (canonicalization_profile = 'opaque'
                    AND encoding IN ('utf-8', 'utf-8-sig', 'cp1252'))
                OR
                (canonicalization_profile IN (
                    'canonical_json_v1', 'canonical_jsonl_v1',
                    'identity_json_v1'
                ) AND encoding = 'utf-8')
            ),
        CONSTRAINT ck_stored_object_canonical_linefeed
            CHECK (
                canonicalization_profile NOT IN (
                    'canonical_json_v1', 'canonical_jsonl_v1'
                )
                OR right(convert_from(payload, 'UTF8'), 1) = E'\n'
            ),
        CONSTRAINT ck_stored_object_no_utf8_bom
            CHECK (
                canonicalization_profile NOT IN (
                    'canonical_json_v1', 'canonical_jsonl_v1',
                    'identity_json_v1'
                )
                OR substring(payload FROM 1 FOR 3) <> decode('efbbbf', 'hex')
            )
    )
    """,
    """
    CREATE TABLE identity.competition (
        competition_id text PRIMARY KEY,
        display_name text NOT NULL,
        country_code text NOT NULL,
        timezone_name text NOT NULL,
        CONSTRAINT ck_competition_id CHECK (competition_id ~ '^[a-z0-9-]+$'),
        CONSTRAINT ck_competition_country CHECK (country_code ~ '^[A-Z]{3}$'),
        CONSTRAINT ck_premier_league_identity CHECK (
            competition_id <> 'eng-premier-league'
            OR timezone_name = 'Europe/London'
        )
    )
    """,
    """
    CREATE TABLE identity.source (
        source_id text PRIMARY KEY,
        provider_name text NOT NULL,
        homepage_url text NOT NULL,
        attribution text NOT NULL,
        usage_notice text NOT NULL,
        CONSTRAINT ck_source_id CHECK (source_id ~ '^[a-z0-9-]+$'),
        CONSTRAINT ck_source_homepage_https CHECK (homepage_url ~ '^https://')
    )
    """,
    """
    CREATE TABLE identity.source_allowed_host (
        source_id text NOT NULL,
        ordinal integer NOT NULL,
        hostname text NOT NULL,
        PRIMARY KEY (source_id, ordinal),
        CONSTRAINT uq_source_allowed_host UNIQUE (source_id, hostname),
        CONSTRAINT fk_source_allowed_host_source FOREIGN KEY (source_id)
            REFERENCES identity.source (source_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_source_allowed_host_ordinal CHECK (ordinal >= 0),
        CONSTRAINT ck_source_allowed_host_lower CHECK (
            hostname = lower(hostname) AND hostname ~ '^[a-z0-9.-]+$'
        )
    )
    """,
    """
    CREATE TABLE identity.reference_document (
        document_sha256 persistence.sha256 PRIMARY KEY,
        document_kind text NOT NULL,
        schema_version persistence.positive_version NOT NULL,
        CONSTRAINT fk_reference_document_object FOREIGN KEY (document_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_reference_document_kind CHECK (document_kind IN (
            'historical_manifest', 'team_registry', 'season_registry'
        )),
        CONSTRAINT uq_reference_document_revision UNIQUE (
            document_kind, schema_version, document_sha256
        )
    )
    """,
    """
    CREATE TABLE identity.team (
        team_id uuid PRIMARY KEY
    )
    """,
    """
    CREATE TABLE identity.team_registry_member (
        document_sha256 persistence.sha256 NOT NULL,
        ordinal integer NOT NULL,
        team_id uuid NOT NULL,
        slug text NOT NULL,
        display_name text NOT NULL,
        country_code text NOT NULL,
        PRIMARY KEY (document_sha256, ordinal),
        CONSTRAINT uq_team_registry_member_team UNIQUE (document_sha256, team_id),
        CONSTRAINT uq_team_registry_member_slug UNIQUE (document_sha256, slug),
        CONSTRAINT fk_team_registry_member_document FOREIGN KEY (document_sha256)
            REFERENCES identity.reference_document (document_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_team_registry_member_team FOREIGN KEY (team_id)
            REFERENCES identity.team (team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_team_registry_member_ordinal CHECK (ordinal >= 0),
        CONSTRAINT ck_team_registry_member_slug CHECK (
            slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'
        ),
        CONSTRAINT ck_team_registry_member_country CHECK (
            country_code ~ '^[A-Z]{3}$'
        )
    )
    """,
    """
    CREATE TABLE identity.team_alias (
        document_sha256 persistence.sha256 NOT NULL,
        team_id uuid NOT NULL,
        source_id text NOT NULL,
        ordinal integer NOT NULL,
        external_name text NOT NULL,
        normalized_external_name text NOT NULL,
        external_id text,
        PRIMARY KEY (document_sha256, team_id, source_id, ordinal),
        CONSTRAINT fk_team_alias_member FOREIGN KEY (document_sha256, team_id)
            REFERENCES identity.team_registry_member (document_sha256, team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_team_alias_source FOREIGN KEY (source_id)
            REFERENCES identity.source (source_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT uq_team_alias_name UNIQUE (
            document_sha256, source_id, normalized_external_name
        ),
        CONSTRAINT ck_team_alias_ordinal CHECK (ordinal >= 0),
        CONSTRAINT ck_team_alias_name_nonempty CHECK (
            length(btrim(external_name)) > 0
            AND length(btrim(normalized_external_name)) > 0
        )
    )
    """,
    """
    CREATE TABLE identity.season (
        competition_id text NOT NULL,
        season_id text NOT NULL,
        PRIMARY KEY (competition_id, season_id),
        CONSTRAINT fk_season_competition FOREIGN KEY (competition_id)
            REFERENCES identity.competition (competition_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_season_id CHECK (
            season_id ~ '^[0-9]{4}-[0-9]{4}$'
            AND substring(season_id FROM 6 FOR 4)::integer
                = substring(season_id FROM 1 FOR 4)::integer + 1
        )
    )
    """,
    """
    CREATE TABLE identity.season_registry_entry (
        season_registry_sha256 persistence.sha256 NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        ordinal integer NOT NULL,
        starts_on date NOT NULL,
        ends_on date NOT NULL,
        completed boolean NOT NULL,
        PRIMARY KEY (season_registry_sha256, competition_id, season_id),
        CONSTRAINT uq_season_registry_entry_ordinal UNIQUE (
            season_registry_sha256, competition_id, ordinal
        ),
        CONSTRAINT fk_season_registry_entry_document
            FOREIGN KEY (season_registry_sha256)
            REFERENCES identity.reference_document (document_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_season_registry_entry_season
            FOREIGN KEY (competition_id, season_id)
            REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_season_registry_entry_ordinal CHECK (ordinal >= 0),
        CONSTRAINT ck_season_registry_entry_dates CHECK (
            starts_on < ends_on
            AND season_id = concat(
                extract(year FROM starts_on)::integer::text,
                '-',
                extract(year FROM ends_on)::integer::text
            )
        )
    )
    """,
    """
    CREATE TABLE identity.season_membership (
        season_registry_sha256 persistence.sha256 NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        team_id uuid NOT NULL,
        ordinal integer NOT NULL,
        entry_status text NOT NULL,
        previous_competition_id text,
        PRIMARY KEY (
            season_registry_sha256, competition_id, season_id, team_id
        ),
        CONSTRAINT uq_season_membership_ordinal UNIQUE (
            season_registry_sha256, competition_id, season_id, ordinal
        ),
        CONSTRAINT fk_season_membership_entry FOREIGN KEY (
            season_registry_sha256, competition_id, season_id
        ) REFERENCES identity.season_registry_entry (
            season_registry_sha256, competition_id, season_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_season_membership_team FOREIGN KEY (team_id)
            REFERENCES identity.team (team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_season_membership_ordinal CHECK (ordinal >= 0),
        CONSTRAINT ck_season_membership_status CHECK (
            entry_status IN ('continued', 'promoted')
        ),
        CONSTRAINT ck_season_membership_promotion CHECK (
            (entry_status = 'promoted' AND previous_competition_id IS NOT NULL)
            OR
            (entry_status = 'continued' AND previous_competition_id IS NULL)
        )
    )
    """,
    """
    CREATE TABLE football.canonical_dataset (
        dataset_id text NOT NULL,
        manifest_sha256 persistence.sha256 NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        raw_source_id text NOT NULL,
        raw_artifact_id text NOT NULL,
        team_registry_sha256 persistence.sha256 NOT NULL,
        season_registry_sha256 persistence.sha256 NOT NULL,
        fixtures_sha256 persistence.sha256 NOT NULL,
        dataset_schema_version persistence.positive_version NOT NULL,
        fixture_count integer NOT NULL,
        ordering_contract text NOT NULL,
        PRIMARY KEY (dataset_id, manifest_sha256),
        CONSTRAINT uq_canonical_dataset_fixture_bytes UNIQUE (
            dataset_id, fixtures_sha256
        ),
        CONSTRAINT uq_canonical_dataset_exact_bytes UNIQUE (
            dataset_id, manifest_sha256, fixtures_sha256
        ),
        CONSTRAINT uq_canonical_dataset_season_bytes UNIQUE (
            competition_id, season_id, dataset_schema_version, fixtures_sha256
        ),
        CONSTRAINT uq_canonical_dataset_lineage UNIQUE (
            dataset_id, manifest_sha256, competition_id, season_id,
            season_registry_sha256
        ),
        CONSTRAINT fk_canonical_dataset_manifest FOREIGN KEY (manifest_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_canonical_dataset_fixtures FOREIGN KEY (fixtures_sha256)
            REFERENCES lineage.stored_object (sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_canonical_dataset_season FOREIGN KEY (
            competition_id, season_id
        ) REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_canonical_dataset_team_registry
            FOREIGN KEY (team_registry_sha256)
            REFERENCES identity.reference_document (document_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_canonical_dataset_season_registry
            FOREIGN KEY (season_registry_sha256)
            REFERENCES identity.reference_document (document_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_canonical_dataset_count CHECK (fixture_count > 0),
        CONSTRAINT ck_canonical_dataset_ordering CHECK (
            ordering_contract = 'kickoff_at_fixture_id'
        )
    )
    """,
    """
    CREATE TABLE football.fixture (
        fixture_id uuid PRIMARY KEY,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        home_team_id uuid NOT NULL,
        away_team_id uuid NOT NULL,
        CONSTRAINT uq_fixture_pairing UNIQUE (
            competition_id, season_id, home_team_id, away_team_id
        ),
        CONSTRAINT uq_fixture_identity_snapshot UNIQUE (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ),
        CONSTRAINT uq_fixture_team_snapshot UNIQUE (
            fixture_id, home_team_id, away_team_id
        ),
        CONSTRAINT fk_fixture_season FOREIGN KEY (competition_id, season_id)
            REFERENCES identity.season (competition_id, season_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_fixture_home_team FOREIGN KEY (home_team_id)
            REFERENCES identity.team (team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_fixture_away_team FOREIGN KEY (away_team_id)
            REFERENCES identity.team (team_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_fixture_teams_differ CHECK (home_team_id <> away_team_id),
        CONSTRAINT ck_fixture_deterministic_id CHECK (
            fixture_id = uuid_generate_v5(
                uuid_ns_url(),
                'pl-platform:fixture:' || competition_id || '|' || season_id
                || '|' || home_team_id::text || '|' || away_team_id::text
            )
        )
    )
    """,
    """
    CREATE TABLE football.fixture_revision (
        canonical_dataset_id text NOT NULL,
        canonical_manifest_sha256 persistence.sha256 NOT NULL,
        fixture_id uuid NOT NULL,
        record_ordinal integer NOT NULL,
        competition_id text NOT NULL,
        season_id text NOT NULL,
        season_registry_sha256 persistence.sha256 NOT NULL,
        home_team_id uuid NOT NULL,
        away_team_id uuid NOT NULL,
        kickoff_at timestamptz NOT NULL,
        kickoff_precision text NOT NULL,
        status text NOT NULL,
        matchweek smallint,
        referee text,
        full_time_home_goals smallint,
        full_time_away_goals smallint,
        half_time_home_goals smallint,
        half_time_away_goals smallint,
        outcome text,
        home_shots integer,
        away_shots integer,
        home_shots_on_target integer,
        away_shots_on_target integer,
        home_fouls integer,
        away_fouls integer,
        home_corners integer,
        away_corners integer,
        home_yellow_cards integer,
        away_yellow_cards integer,
        home_red_cards integer,
        away_red_cards integer,
        PRIMARY KEY (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id
        ),
        CONSTRAINT uq_fixture_revision_ordinal UNIQUE (
            canonical_dataset_id, canonical_manifest_sha256, record_ordinal
        ),
        CONSTRAINT fk_fixture_revision_dataset FOREIGN KEY (
            canonical_dataset_id, canonical_manifest_sha256, competition_id,
            season_id, season_registry_sha256
        ) REFERENCES football.canonical_dataset (
            dataset_id, manifest_sha256, competition_id, season_id,
            season_registry_sha256
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_fixture_revision_fixture FOREIGN KEY (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) REFERENCES football.fixture (
            fixture_id, competition_id, season_id, home_team_id, away_team_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_fixture_revision_home_membership FOREIGN KEY (
            season_registry_sha256, competition_id, season_id, home_team_id
        ) REFERENCES identity.season_membership (
            season_registry_sha256, competition_id, season_id, team_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_fixture_revision_away_membership FOREIGN KEY (
            season_registry_sha256, competition_id, season_id, away_team_id
        ) REFERENCES identity.season_membership (
            season_registry_sha256, competition_id, season_id, team_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_fixture_revision_ordinal CHECK (record_ordinal >= 0),
        CONSTRAINT ck_fixture_revision_precision CHECK (
            kickoff_precision IN ('exact', 'date_only')
        ),
        CONSTRAINT ck_fixture_revision_status CHECK (status IN (
            'scheduled', 'postponed', 'cancelled', 'in_progress', 'finished'
        )),
        CONSTRAINT ck_fixture_revision_matchweek CHECK (
            matchweek IS NULL OR matchweek >= 1
        ),
        CONSTRAINT ck_fixture_revision_nonnegative CHECK (
            num_nonnulls(
                full_time_home_goals, full_time_away_goals,
                half_time_home_goals, half_time_away_goals,
                home_shots, away_shots, home_shots_on_target,
                away_shots_on_target, home_fouls, away_fouls,
                home_corners, away_corners, home_yellow_cards,
                away_yellow_cards, home_red_cards, away_red_cards
            ) = num_nonnulls(
                nullif(full_time_home_goals < 0, true),
                nullif(full_time_away_goals < 0, true),
                nullif(half_time_home_goals < 0, true),
                nullif(half_time_away_goals < 0, true),
                nullif(home_shots < 0, true), nullif(away_shots < 0, true),
                nullif(home_shots_on_target < 0, true),
                nullif(away_shots_on_target < 0, true),
                nullif(home_fouls < 0, true), nullif(away_fouls < 0, true),
                nullif(home_corners < 0, true), nullif(away_corners < 0, true),
                nullif(home_yellow_cards < 0, true),
                nullif(away_yellow_cards < 0, true),
                nullif(home_red_cards < 0, true),
                nullif(away_red_cards < 0, true)
            )
        ),
        CONSTRAINT ck_fixture_revision_score_pairs CHECK (
            (full_time_home_goals IS NULL) = (full_time_away_goals IS NULL)
            AND (half_time_home_goals IS NULL) = (half_time_away_goals IS NULL)
        ),
        CONSTRAINT ck_fixture_revision_state CHECK (
            (
                status = 'finished'
                AND full_time_home_goals IS NOT NULL
                AND outcome IS NOT NULL
            )
            OR
            (
                status IN ('scheduled', 'postponed', 'cancelled')
                AND full_time_home_goals IS NULL
                AND half_time_home_goals IS NULL
                AND outcome IS NULL
            )
            OR status = 'in_progress'
        ),
        CONSTRAINT ck_fixture_revision_outcome CHECK (
            outcome IS NULL OR outcome = CASE
                WHEN full_time_home_goals > full_time_away_goals THEN 'home_win'
                WHEN full_time_home_goals < full_time_away_goals THEN 'away_win'
                ELSE 'draw'
            END
        ),
        CONSTRAINT ck_fixture_revision_halftime CHECK (
            half_time_home_goals IS NULL
            OR (
                full_time_home_goals IS NOT NULL
                AND half_time_home_goals <= full_time_home_goals
                AND half_time_away_goals <= full_time_away_goals
            )
        )
    )
    """,
    """
    CREATE TABLE football.fixture_source_reference (
        canonical_dataset_id text NOT NULL,
        canonical_manifest_sha256 persistence.sha256 NOT NULL,
        fixture_id uuid NOT NULL,
        ordinal integer NOT NULL,
        source_id text NOT NULL,
        external_id text NOT NULL,
        PRIMARY KEY (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id, ordinal
        ),
        CONSTRAINT uq_fixture_source_reference UNIQUE (
            canonical_dataset_id, canonical_manifest_sha256,
            source_id, external_id
        ),
        CONSTRAINT fk_fixture_source_reference_revision FOREIGN KEY (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id
        ) REFERENCES football.fixture_revision (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_fixture_source_reference_source FOREIGN KEY (source_id)
            REFERENCES identity.source (source_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_fixture_source_reference_ordinal CHECK (ordinal >= 0)
    )
    """,
    """
    CREATE TABLE football.fixture_batch (
        canonical_dataset_id text NOT NULL,
        canonical_manifest_sha256 persistence.sha256 NOT NULL,
        batch_ordinal integer NOT NULL,
        batch_kind text NOT NULL,
        competition_date date NOT NULL,
        exact_kickoff_at timestamptz,
        PRIMARY KEY (
            canonical_dataset_id, canonical_manifest_sha256, batch_ordinal
        ),
        CONSTRAINT fk_fixture_batch_dataset FOREIGN KEY (
            canonical_dataset_id, canonical_manifest_sha256
        ) REFERENCES football.canonical_dataset (dataset_id, manifest_sha256)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_fixture_batch_ordinal CHECK (batch_ordinal >= 0),
        CONSTRAINT ck_fixture_batch_kind CHECK (
            (batch_kind = 'date_only_date' AND exact_kickoff_at IS NULL)
            OR (batch_kind = 'exact_kickoff' AND exact_kickoff_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE football.fixture_batch_member (
        canonical_dataset_id text NOT NULL,
        canonical_manifest_sha256 persistence.sha256 NOT NULL,
        batch_ordinal integer NOT NULL,
        member_ordinal integer NOT NULL,
        fixture_id uuid NOT NULL,
        PRIMARY KEY (
            canonical_dataset_id, canonical_manifest_sha256,
            batch_ordinal, member_ordinal
        ),
        CONSTRAINT uq_fixture_batch_member_fixture UNIQUE (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id
        ),
        CONSTRAINT fk_fixture_batch_member_batch FOREIGN KEY (
            canonical_dataset_id, canonical_manifest_sha256, batch_ordinal
        ) REFERENCES football.fixture_batch (
            canonical_dataset_id, canonical_manifest_sha256, batch_ordinal
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT fk_fixture_batch_member_revision FOREIGN KEY (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id
        ) REFERENCES football.fixture_revision (
            canonical_dataset_id, canonical_manifest_sha256, fixture_id
        ) ON UPDATE RESTRICT ON DELETE RESTRICT,
        CONSTRAINT ck_fixture_batch_member_ordinal CHECK (member_ordinal >= 0)
    )
    """,
    """
    CREATE FUNCTION football.validate_canonical_dataset()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        owner_dataset text;
        owner_manifest persistence.sha256;
        expected_count integer;
        revision_count integer;
        member_count integer;
        batch_count integer;
        used_batch_count integer;
        complete_season boolean;
        bad_complete_rows integer;
        bad_appearances integer;
        bad_batches integer;
    BEGIN
        owner_dataset := coalesce(
            to_jsonb(NEW)->>'canonical_dataset_id',
            to_jsonb(NEW)->>'dataset_id'
        );
        owner_manifest := coalesce(
            to_jsonb(NEW)->>'canonical_manifest_sha256',
            to_jsonb(NEW)->>'manifest_sha256'
        );
        SELECT d.fixture_count, e.is_complete
          INTO expected_count, complete_season
          FROM football.canonical_dataset d
          JOIN identity.season_registry_entry e
            ON e.season_registry_sha256 = d.season_registry_sha256
           AND e.competition_id = d.competition_id
           AND e.season_id = d.season_id
         WHERE d.dataset_id = owner_dataset
           AND d.manifest_sha256 = owner_manifest;
        SELECT count(*) INTO revision_count
          FROM football.fixture_revision
         WHERE canonical_dataset_id = owner_dataset
           AND canonical_manifest_sha256 = owner_manifest;
        SELECT count(*), count(DISTINCT batch_ordinal)
          INTO member_count, used_batch_count
          FROM football.fixture_batch_member
         WHERE canonical_dataset_id = owner_dataset
           AND canonical_manifest_sha256 = owner_manifest;
        SELECT count(*) INTO batch_count
          FROM football.fixture_batch
         WHERE canonical_dataset_id = owner_dataset
           AND canonical_manifest_sha256 = owner_manifest;
        IF revision_count <> expected_count OR member_count <> expected_count
           OR batch_count <> used_batch_count THEN
            RAISE EXCEPTION 'provenance_mismatch: canonical dataset incomplete'
                USING ERRCODE = '23514';
        END IF;
        SELECT count(*) INTO bad_batches
        FROM football.fixture_batch_member m
        JOIN football.fixture_batch b USING (
            canonical_dataset_id, canonical_manifest_sha256, batch_ordinal
        )
        JOIN football.fixture_revision r
          ON r.canonical_dataset_id = m.canonical_dataset_id
         AND r.canonical_manifest_sha256 = m.canonical_manifest_sha256
         AND r.fixture_id = m.fixture_id
        WHERE m.canonical_dataset_id = owner_dataset
          AND m.canonical_manifest_sha256 = owner_manifest
          AND (
            b.competition_date <>
                (r.kickoff_at AT TIME ZONE 'Europe/London')::date
            OR (
                EXISTS (
                    SELECT 1 FROM football.fixture_revision date_row
                    WHERE date_row.canonical_dataset_id = owner_dataset
                      AND date_row.canonical_manifest_sha256 = owner_manifest
                      AND (date_row.kickoff_at AT TIME ZONE 'Europe/London')::date
                          = b.competition_date
                      AND date_row.kickoff_precision = 'date_only'
                )
                AND (b.batch_kind <> 'date_only_date'
                     OR EXISTS (
                        SELECT 1 FROM football.fixture_batch_member other
                        JOIN football.fixture_revision other_revision
                          ON other_revision.canonical_dataset_id
                             = other.canonical_dataset_id
                         AND other_revision.canonical_manifest_sha256
                             = other.canonical_manifest_sha256
                         AND other_revision.fixture_id = other.fixture_id
                        WHERE other.canonical_dataset_id = owner_dataset
                          AND other.canonical_manifest_sha256 = owner_manifest
                          AND (other_revision.kickoff_at
                               AT TIME ZONE 'Europe/London')::date
                              = b.competition_date
                          AND other.batch_ordinal <> b.batch_ordinal
                     ))
            )
            OR (
                NOT EXISTS (
                    SELECT 1 FROM football.fixture_revision date_row
                    WHERE date_row.canonical_dataset_id = owner_dataset
                      AND date_row.canonical_manifest_sha256 = owner_manifest
                      AND (date_row.kickoff_at AT TIME ZONE 'Europe/London')::date
                          = b.competition_date
                      AND date_row.kickoff_precision = 'date_only'
                )
                AND (b.batch_kind <> 'exact_kickoff'
                     OR b.exact_kickoff_at <> r.kickoff_at)
            )
          );
        IF bad_batches <> 0 THEN
            RAISE EXCEPTION 'chronology_violation: fixture batch mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF complete_season THEN
            SELECT count(*) INTO bad_complete_rows
              FROM football.fixture_revision
             WHERE canonical_dataset_id = owner_dataset
               AND canonical_manifest_sha256 = owner_manifest
               AND status <> 'finished';
            SELECT count(*) INTO bad_appearances
            FROM identity.season_membership membership
            WHERE membership.season_registry_sha256 = (
                    SELECT season_registry_sha256
                    FROM football.canonical_dataset
                    WHERE dataset_id = owner_dataset
                      AND manifest_sha256 = owner_manifest
                )
              AND membership.competition_id = 'eng-premier-league'
              AND (
                (SELECT count(*) FROM football.fixture f
                 JOIN football.fixture_revision r USING (fixture_id)
                 WHERE r.canonical_dataset_id = owner_dataset
                   AND r.canonical_manifest_sha256 = owner_manifest
                   AND f.home_team_id = membership.team_id) <> 19
                OR
                (SELECT count(*) FROM football.fixture f
                 JOIN football.fixture_revision r USING (fixture_id)
                 WHERE r.canonical_dataset_id = owner_dataset
                   AND r.canonical_manifest_sha256 = owner_manifest
                   AND f.away_team_id = membership.team_id) <> 19
              );
            IF expected_count <> 380 OR bad_complete_rows <> 0
               OR bad_appearances <> 0 THEN
                RAISE EXCEPTION 'provenance_mismatch: complete season invalid'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER canonical_dataset_complete_from_dataset
    AFTER INSERT ON football.canonical_dataset
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION football.validate_canonical_dataset()
    """,
    """
    CREATE CONSTRAINT TRIGGER canonical_dataset_complete_from_revision
    AFTER INSERT ON football.fixture_revision
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION football.validate_canonical_dataset()
    """,
    """
    CREATE CONSTRAINT TRIGGER canonical_dataset_complete_from_batch
    AFTER INSERT ON football.fixture_batch
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION football.validate_canonical_dataset()
    """,
    """
    CREATE CONSTRAINT TRIGGER canonical_dataset_complete_from_batch_member
    AFTER INSERT ON football.fixture_batch_member
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION football.validate_canonical_dataset()
    """,
    """
    CREATE FUNCTION identity.validate_season_membership()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        owner_sha persistence.sha256;
        owner_competition text;
        owner_season text;
        member_count integer;
        promoted_count integer;
        minimum_ordinal integer;
        maximum_ordinal integer;
    BEGIN
        owner_sha := NEW.season_registry_sha256;
        owner_competition := NEW.competition_id;
        owner_season := NEW.season_id;
        SELECT count(*), count(*) FILTER (WHERE entry_status = 'promoted'),
               min(ordinal), max(ordinal)
          INTO member_count, promoted_count, minimum_ordinal, maximum_ordinal
          FROM identity.season_membership
         WHERE season_registry_sha256 = owner_sha
           AND competition_id = owner_competition
           AND season_id = owner_season;
        IF owner_competition = 'eng-premier-league'
           AND (
               member_count <> 20 OR promoted_count <> 3
               OR minimum_ordinal <> 0 OR maximum_ordinal <> 19
           ) THEN
            RAISE EXCEPTION 'season_membership_incomplete: %/%',
                owner_competition, owner_season
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER season_membership_complete_from_entry
    AFTER INSERT ON identity.season_registry_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION identity.validate_season_membership()
    """,
    """
    CREATE CONSTRAINT TRIGGER season_membership_complete_from_member
    AFTER INSERT ON identity.season_membership
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION identity.validate_season_membership()
    """,
)


IMMUTABLE_TABLES: tuple[tuple[str, str], ...] = (
    ("lineage", "stored_object"),
    ("identity", "competition"),
    ("identity", "source"),
    ("identity", "source_allowed_host"),
    ("identity", "reference_document"),
    ("identity", "team"),
    ("identity", "team_registry_member"),
    ("identity", "team_alias"),
    ("identity", "season"),
    ("identity", "season_registry_entry"),
    ("identity", "season_membership"),
    ("football", "canonical_dataset"),
    ("football", "fixture"),
    ("football", "fixture_revision"),
    ("football", "fixture_source_reference"),
    ("football", "fixture_batch"),
    ("football", "fixture_batch_member"),
)


def upgrade() -> None:
    """Create the lossless identity, lineage, season and fixture foundation."""

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
    """Remove Step 5.4 schemas while retaining shared PostgreSQL extensions."""

    op.execute(sa.text("DROP SCHEMA football CASCADE"))
    op.execute(sa.text("DROP SCHEMA identity CASCADE"))
    op.execute(sa.text("DROP SCHEMA lineage CASCADE"))
    op.execute(sa.text("DROP SCHEMA persistence CASCADE"))
