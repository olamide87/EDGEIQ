# Historical NFL data sources and attribution

EDGE IQ v0.5A uses the `nflreadpy` client for nflverse datasets. The adapter supports
player statistics, play-by-play, schedules, seasonal and weekly rosters, snap counts,
participation, injuries, and depth charts. Each local manifest records the concrete
loader, source URL, seasons, capture time, columns, rows, file hash, and attribution.

Most nflverse datasets are distributed under CC BY 4.0. Participation data carries
CC BY-SA 4.0 terms and requires attribution to NFL NextGenStats via nflverse through
2022 or FTN Data via nflverse from 2023 onward. Licensing is dataset-specific and
must be rechecked before redistribution or commercial use. EDGE IQ commits no
downloaded data; tiny files under `tests/fixtures/` are synthetic and project-authored.

Manifest hashes identify logical source content and exclude capture timestamps;
timestamps remain recorded as audit metadata. Processed manifests separately record
a canonical content hash and the physical Parquet file hash. The content hash is the
portable reproducibility identifier, while the file hash detects byte-level changes.

- nflreadpy documentation: https://nflreadpy.nflverse.com/
- nflreadpy source: https://github.com/nflverse/nflreadpy
- nflverse data releases: https://github.com/nflverse/nflverse-data/releases

nflverse is not a source of historical player-prop lines or sportsbook prices.
Prediction accuracy alone cannot demonstrate wagering profitability; genuine betting
backtests require point-in-time lines and prices from an appropriately licensed source.
