"""Tests for the secret-free Alembic initialization boundary."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_configuration_has_no_embedded_database_url() -> None:
    config = Config("alembic.ini")
    script_location = config.get_main_option("script_location")

    assert script_location is not None
    assert script_location.replace("\\", "/").endswith("/migrations")
    assert config.get_main_option("sqlalchemy.url") is None


def test_steps_5_4_through_10_5_form_one_linear_revision_chain() -> None:
    version_files = {
        path.name
        for path in Path("migrations/versions").iterdir()
        if path.is_file() and path.name != ".gitkeep"
    }

    assert version_files == {
        "f0001_step_5_4_core_identity.py",
        "f0002_step_5_5_feature_model.py",
        "f0003_step_5_6_ml_evaluation.py",
        "f0004_step_5_7_ingestion_simulation.py",
        "f0005_step_6_7_current_sync.py",
        "f0006_step_6_8_squads_players.py",
        "f0007_step_7_4_prediction_lifecycle.py",
        "f0008_step_7_7_post_match_regeneration.py",
        "f0009_step_7_9_post_match_workflow.py",
        "f0010_step_10_5_canonical_validation.py",
    }

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["f0010_step_10_5"]
    revisions = list(script.walk_revisions())
    assert [revision.revision for revision in revisions] == [
        "f0010_step_10_5",
        "f0009_step_7_9",
        "f0008_step_7_7",
        "f0007_step_7_4",
        "f0006_step_6_8",
        "f0005_step_6_7",
        "f0004_step_5_7",
        "f0003_step_5_6",
        "f0002_step_5_5",
        "f0001_step_5_4",
    ]
    assert [revision.down_revision for revision in revisions] == [
        "f0009_step_7_9",
        "f0008_step_7_7",
        "f0007_step_7_4",
        "f0006_step_6_8",
        "f0005_step_6_7",
        "f0004_step_5_7",
        "f0003_step_5_6",
        "f0002_step_5_5",
        "f0001_step_5_4",
        None,
    ]
    assert all(revision.branch_labels == set() for revision in revisions)
    assert all(revision.dependencies is None for revision in revisions)


def test_alembic_files_do_not_embed_local_password() -> None:
    migration_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (Path("alembic.ini"), *Path("migrations").glob("**/*"))
        if path.is_file() and "__pycache__" not in path.parts
    )

    assert "pl2026" not in migration_text


def test_production_migrations_use_a_separate_explicit_url() -> None:
    environment = Path("migrations/env.py").read_text(encoding="utf-8")

    assert 'if target == "production":' in environment
    assert "return settings.production_migration_url()" in environment
    assert "settings.database_url_for(target)" in environment
