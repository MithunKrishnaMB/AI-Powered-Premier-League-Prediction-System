"""Cross-record validation for football datasets."""

from pl_platform.quality.fixtures import (
    DataQualityError,
    FixtureQualityReport,
    QualityIssue,
    QualitySeverity,
    validate_premier_league_fixtures,
)

__all__ = [
    "DataQualityError",
    "FixtureQualityReport",
    "QualityIssue",
    "QualitySeverity",
    "validate_premier_league_fixtures",
]
