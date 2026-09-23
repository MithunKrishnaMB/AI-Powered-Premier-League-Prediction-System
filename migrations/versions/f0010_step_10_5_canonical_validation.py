"""Repair canonical historical-dataset validation for the final season schema.

Revision ID: f0010_step_10_5
Revises: f0009_step_7_9
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f0010_step_10_5"
down_revision: str | None = "f0009_step_7_9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION football.validate_canonical_dataset()
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
    SELECT d.fixture_count, e.completed
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
"""


def upgrade() -> None:
    op.execute(FUNCTION_SQL)


def downgrade() -> None:
    op.execute(FUNCTION_SQL.replace("e.completed", "e.is_complete"))
