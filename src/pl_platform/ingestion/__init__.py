"""Historical and current football-data ingestion boundaries."""

from pl_platform.ingestion.download import (
    DownloadResult,
    download_manifest_entry,
    verify_existing_file,
)
from pl_platform.ingestion.football_data import (
    FootballDataMatch,
    parse_football_data_csv,
)
from pl_platform.ingestion.manifest import (
    HistoricalDataManifest,
    HistoricalFile,
    Source,
    load_manifest,
)

__all__ = [
    "DownloadResult",
    "FootballDataMatch",
    "HistoricalDataManifest",
    "HistoricalFile",
    "Source",
    "download_manifest_entry",
    "load_manifest",
    "parse_football_data_csv",
    "verify_existing_file",
]
