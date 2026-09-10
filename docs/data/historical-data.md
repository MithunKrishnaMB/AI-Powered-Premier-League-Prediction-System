# Historical Data Provenance

## Historical source window

The initial source is [Football-Data.co.uk](https://www.football-data.co.uk/data.php).
It publishes downloadable CSV files containing football results, match
statistics, and betting odds. The provider states that the data is free and
intended for league-match prediction, while warning that it cannot guarantee
accuracy.

The tracked source window contains eleven completed English Premier League
seasons from 2015–16 through 2025–26, totaling 4,180 matches. Every season has
its own immutable URL, capture timestamp, byte count, row count, encoding, and
SHA-256 digest in `data/manifests/football-data.json`.

The newest captured file is the completed 2025–26 season:

- provider competition code: `E0`
- source URL: `https://www.football-data.co.uk/mmz4281/2526/E0.csv`
- captured at: `2026-09-10T11:19:37Z`
- rows: `380` matches
- bytes: `203438`
- encoding: `utf-8-sig` (UTF-8 with a byte-order mark)
- SHA-256: `3e3a8352f9ada6789c508d6ca184424421fed56a30400904a4a327c583407e62`

This capture includes many bookmaker columns. Their presence does not mean they
will automatically become model features. Feature eligibility and kickoff-time
availability must be assessed separately to prevent leakage.

## Manifest contract

`data/manifests/football-data.json` is tracked in Git. It records source
attribution, the allowed download hosts, season identity, destination, expected
shape, encoding, capture time, and checksum.

The raw CSV files are ignored by Git. A fresh environment can reproduce or
verify the complete capture with:

```powershell
plp-download-historical `
  --manifest data/manifests/football-data.json `
  --all `
  --data-root data
```

Use `--entry-id epl-2025-2026` in place of `--all` when only one season is
needed.

The first four seasons do not include a `Time` column. Their canonical records
therefore retain `kickoff_precision: date_only`; noon Europe/London is used only
as a deterministic timestamp anchor and must not be treated as an observed
kickoff time.

## Immutability rules

The downloader:

1. accepts only HTTPS URLs from manifest-approved hosts;
2. prevents destinations from escaping the selected data directory;
3. validates byte count, SHA-256 checksum, required columns, and row count;
4. publishes a verified file atomically;
5. treats an existing matching file as an idempotent success; and
6. refuses to replace an existing file whose checksum differs.

If the provider corrects a completed-season file, add a reviewed manifest change
or a separately identified capture. Never silently overwrite the earlier raw
input, because that would make trained models impossible to reproduce.

Raw source data remains subject to the provider's terms. Do not redistribute it
without reviewing those terms and retaining attribution.
