"""Checksum-verified downloader for immutable historical source files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.error import URLError
from urllib.request import Request, urlopen

from pl_platform.ingestion.manifest import (
    HistoricalDataManifest,
    HistoricalFile,
    load_manifest,
)

Fetcher = Callable[[str, float, int], bytes]
DownloadStatus = Literal["downloaded", "already_present"]


class DownloadError(RuntimeError):
    """Base error for a rejected or unsuccessful raw-data download."""


class ChecksumMismatchError(DownloadError):
    """Downloaded bytes do not match the reviewed manifest checksum."""


class ImmutableFileConflictError(DownloadError):
    """A destination exists with content different from the manifest."""


class DownloadValidationError(DownloadError):
    """Downloaded content does not satisfy the manifest data contract."""


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Auditable result of one idempotent download attempt."""

    entry_id: str
    path: Path
    sha256: str
    byte_count: int
    row_count: int
    status: DownloadStatus


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as raw_file:
        for chunk in iter(lambda: raw_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_destination(data_root: Path, relative_destination: str) -> Path:
    root = data_root.resolve()
    relative_path = PurePosixPath(relative_destination)
    destination = root.joinpath(*relative_path.parts).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        msg = f"destination escapes data root: {relative_destination}"
        raise DownloadValidationError(msg) from exc
    return destination


def _fetch_url(url: str, timeout: float, maximum_bytes: int) -> bytes:
    request = Request(
        url,
        headers={"User-Agent": "pl-prediction-platform/0.1 (+data research)"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = bytes(response.read(maximum_bytes + 1))
    except URLError as exc:
        msg = f"failed to download {url}: {exc.reason}"
        raise DownloadError(msg) from exc

    if len(payload) > maximum_bytes:
        msg = f"download exceeded manifest byte count of {maximum_bytes}"
        raise DownloadValidationError(msg)
    return payload


def _validate_payload(payload: bytes, entry: HistoricalFile) -> int:
    if len(payload) != entry.expected_bytes:
        msg = (
            f"byte count mismatch for {entry.id}: expected {entry.expected_bytes}, "
            f"received {len(payload)}"
        )
        raise DownloadValidationError(msg)

    actual_checksum = _sha256_bytes(payload)
    if actual_checksum != entry.sha256:
        msg = (
            f"checksum mismatch for {entry.id}: expected {entry.sha256}, "
            f"received {actual_checksum}"
        )
        raise ChecksumMismatchError(msg)

    try:
        text = payload.decode(entry.encoding)
    except UnicodeDecodeError as exc:
        msg = f"payload for {entry.id} is not valid {entry.encoding}"
        raise DownloadValidationError(msg) from exc

    reader = csv.DictReader(io.StringIO(text, newline=""))
    columns = set(reader.fieldnames or ())
    missing_columns = sorted(set(entry.required_columns) - columns)
    if missing_columns:
        msg = f"payload for {entry.id} is missing columns: {', '.join(missing_columns)}"
        raise DownloadValidationError(msg)

    row_count = sum(
        1 for row in reader if any(value not in (None, "") for value in row.values())
    )
    if row_count != entry.expected_rows:
        msg = (
            f"row count mismatch for {entry.id}: expected {entry.expected_rows}, "
            f"received {row_count}"
        )
        raise DownloadValidationError(msg)
    return row_count


def verify_existing_file(
    entry: HistoricalFile,
    destination: Path,
) -> DownloadResult:
    """Verify an existing raw file against its immutable manifest entry."""

    actual_checksum = _sha256_file(destination)
    if actual_checksum != entry.sha256:
        msg = (
            f"refusing to overwrite immutable raw file {destination}; "
            f"expected checksum {entry.sha256}, found {actual_checksum}"
        )
        raise ImmutableFileConflictError(msg)
    return DownloadResult(
        entry_id=entry.id,
        path=destination,
        sha256=actual_checksum,
        byte_count=destination.stat().st_size,
        row_count=entry.expected_rows,
        status="already_present",
    )


def download_manifest_entry(
    manifest: HistoricalDataManifest,
    entry_id: str,
    data_root: Path,
    *,
    timeout: float = 30.0,
    fetch: Fetcher | None = None,
) -> DownloadResult:
    """Download one entry after validating integrity and immutability."""

    entry = manifest.get_file(entry_id)
    destination = _resolve_destination(data_root, entry.destination)
    if destination.exists():
        return verify_existing_file(entry, destination)

    fetcher = fetch or _fetch_url
    payload = fetcher(entry.url, timeout, entry.expected_bytes)
    row_count = _validate_payload(payload, entry)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)

        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            return verify_existing_file(entry, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return DownloadResult(
        entry_id=entry.id,
        path=destination,
        sha256=entry.sha256,
        byte_count=len(payload),
        row_count=row_count,
        status="downloaded",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download checksum-pinned historical football CSV data."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--entry-id")
    selection.add_argument(
        "--all",
        action="store_true",
        help="download or verify every manifest entry in manifest order",
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the historical download command."""

    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        manifest = load_manifest(arguments.manifest)
        entry_ids = (
            tuple(entry.id for entry in manifest.files)
            if arguments.all
            else (arguments.entry_id,)
        )
        results = tuple(
            download_manifest_entry(
                manifest,
                entry_id,
                arguments.data_root,
                timeout=arguments.timeout,
            )
            for entry_id in entry_ids
        )
    except (DownloadError, KeyError, OSError, ValueError) as exc:
        parser.error(str(exc))

    serialized_results = []
    for result in results:
        serialized = asdict(result)
        serialized["path"] = str(result.path)
        serialized_results.append(serialized)
    final_output: object = (
        serialized_results if arguments.all else serialized_results[0]
    )
    print(json.dumps(final_output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
