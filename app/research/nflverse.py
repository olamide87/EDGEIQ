from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import polars as pl

from app.research.manifest import CachedDatasetFile, DataManifest, DatasetSource, sha256_file


class DatasetUnavailableError(RuntimeError):
    """Raised when an nflverse loader or requested season is unavailable."""


class DatasetSchemaError(RuntimeError):
    """Raised when upstream data no longer satisfies the adapter contract."""


class DatasetLoader(Protocol):
    def __call__(self, seasons: list[int]) -> pl.DataFrame: ...


@dataclass(frozen=True)
class DatasetContract:
    key: str
    loader_name: str
    required_columns: frozenset[str]
    source_url: str
    required_any_of: tuple[frozenset[str], ...] = ()
    sort_columns: tuple[str, ...] = ()
    license_name: str = "CC-BY 4.0"
    license_url: str = "https://creativecommons.org/licenses/by/4.0/"
    attribution: str = "nflverse contributors"

    def source(self) -> DatasetSource:
        return DatasetSource(
            dataset=self.key,
            loader=self.loader_name,
            source_url=self.source_url,
            license_name=self.license_name,
            license_url=self.license_url,
            attribution=self.attribution,
        )


_DATA_BASE = "https://github.com/nflverse/nflverse-data/releases"
DATASET_CONTRACTS: dict[str, DatasetContract] = {
    "player_stats": DatasetContract(
        "player_stats", "load_player_stats",
        frozenset({"season", "week", "player_id", "player_display_name", "position", "receptions"}),
        f"{_DATA_BASE}/tag/player_stats",
        required_any_of=(frozenset({"team"}), frozenset({"recent_team"})),
        sort_columns=("season", "week", "player_id"),
    ),
    "pbp": DatasetContract(
        "pbp", "load_pbp", frozenset({"season", "week", "game_id", "play_id"}),
        f"{_DATA_BASE}/tag/pbp",
        sort_columns=("season", "week", "game_id", "play_id"),
    ),
    "schedules": DatasetContract(
        "schedules", "load_schedules",
        frozenset({"season", "week", "game_id", "gameday", "home_team", "away_team"}),
        f"{_DATA_BASE}/tag/schedules",
        sort_columns=("season", "week", "game_id"),
    ),
    "rosters": DatasetContract(
        "rosters", "load_rosters", frozenset({"season", "gsis_id", "full_name", "position"}),
        f"{_DATA_BASE}/tag/roster",
        sort_columns=("season", "gsis_id"),
    ),
    "weekly_rosters": DatasetContract(
        "weekly_rosters", "load_rosters_weekly",
        frozenset({"season", "week", "gsis_id", "full_name", "position"}),
        f"{_DATA_BASE}/tag/weekly_rosters",
        sort_columns=("season", "week", "gsis_id"),
    ),
    "snap_counts": DatasetContract(
        "snap_counts", "load_snap_counts", frozenset({"season", "week", "game_id"}),
        f"{_DATA_BASE}/tag/snap_counts",
        sort_columns=("season", "week", "game_id", "pfr_player_id"),
    ),
    "participation": DatasetContract(
        "participation", "load_participation", frozenset({"nflverse_game_id", "play_id"}),
        "https://github.com/nflverse/nflverse-data/releases/tag/participation",
        sort_columns=("nflverse_game_id", "play_id"),
        license_name="CC-BY-SA 4.0",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        attribution=(
            "NFL NextGenStats via nflverse through 2022; "
            "FTN Data via nflverse from 2023 onward"
        ),
    ),
    "injuries": DatasetContract(
        "injuries", "load_injuries", frozenset({"season", "week"}),
        f"{_DATA_BASE}/tag/injuries",
        sort_columns=("season", "week", "gsis_id", "full_name"),
    ),
    "depth_charts": DatasetContract(
        "depth_charts", "load_depth_charts", frozenset({"gsis_id"}),
        f"{_DATA_BASE}/tag/depth_charts",
        required_any_of=(frozenset({"season", "week"}), frozenset({"dt", "team"})),
        sort_columns=("season", "week", "dt", "team", "gsis_id"),
    ),
}

DEFAULT_DATASETS: tuple[str, ...] = (
    "player_stats", "schedules", "rosters", "weekly_rosters", "snap_counts",
    "participation", "injuries", "depth_charts",
)


class NflverseAdapter:
    def __init__(
        self,
        *,
        seasons: Iterable[int],
        cache_dir: Path = Path("data/raw/nflverse"),
        manifest_dir: Path = Path("data/manifests"),
        loaders: dict[str, DatasetLoader] | None = None,
    ) -> None:
        self.seasons = sorted(set(seasons))
        if not self.seasons:
            raise ValueError("At least one season is required.")
        if any(isinstance(season, bool) or season < 1920 or season > 2100 for season in self.seasons):
            raise ValueError("Seasons must be four-digit NFL seasons between 1920 and 2100.")
        self.cache_dir = cache_dir
        self.manifest_dir = manifest_dir
        self._loaders = loaders or {}

    def _loader(self, contract: DatasetContract) -> DatasetLoader:
        if contract.key in self._loaders:
            return self._loaders[contract.key]
        try:
            import nflreadpy
        except ImportError as exc:
            raise DatasetUnavailableError(
                "nflreadpy is not installed; install requirements.txt or inject an offline loader."
            ) from exc
        loader = getattr(nflreadpy, contract.loader_name, None)
        if loader is None:
            raise DatasetUnavailableError(
                f"nflreadpy does not provide {contract.loader_name} for '{contract.key}'."
            )
        return loader

    @staticmethod
    def validate(contract: DatasetContract, frame: pl.DataFrame) -> None:
        missing = sorted(contract.required_columns - set(frame.columns))
        if missing:
            raise DatasetSchemaError(
                f"Dataset '{contract.key}' is missing required columns: {', '.join(missing)}."
            )
        if contract.required_any_of and not any(
            alternative <= set(frame.columns) for alternative in contract.required_any_of
        ):
            alternatives = " or ".join(
                "{" + ", ".join(sorted(option)) + "}" for option in contract.required_any_of
            )
            raise DatasetSchemaError(
                f"Dataset '{contract.key}' must contain one of these column sets: {alternatives}."
            )

    @staticmethod
    def _canonicalize(contract: DatasetContract, frame: pl.DataFrame) -> pl.DataFrame:
        columns = [name for name in contract.sort_columns if name in frame.columns]
        return frame.sort(columns) if columns else frame

    def _cache_path(self, dataset: str, season: int) -> Path:
        return self.cache_dir / dataset / f"{season}.parquet"

    def _read_cached(self, contract: DatasetContract) -> pl.DataFrame | None:
        paths = [self._cache_path(contract.key, season) for season in self.seasons]
        if not all(path.exists() for path in paths):
            return None
        frames: list[pl.DataFrame] = []
        for season, path in zip(self.seasons, paths, strict=True):
            try:
                frame = pl.read_parquet(path)
            except Exception as exc:
                raise DatasetSchemaError(f"Cached dataset '{path}' is not valid Parquet: {exc}") from exc
            self.validate(contract, frame)
            if frame.is_empty():
                raise DatasetUnavailableError(f"Cached dataset '{path}' contains no rows.")
            if "season" in frame.columns:
                if frame.get_column("season").null_count():
                    raise DatasetSchemaError(f"Cached dataset '{path}' contains null seasons.")
                observed = set(frame.get_column("season").drop_nulls().cast(pl.Int64).to_list())
                if observed != {season}:
                    raise DatasetSchemaError(
                        f"Cached dataset '{path}' contains seasons {sorted(observed)}, expected {season}."
                    )
            frames.append(self._canonicalize(contract, frame))
        return pl.concat(frames, how="diagonal_relaxed")

    def fetch(self, dataset: str, *, force: bool = False) -> pl.DataFrame:
        contract = DATASET_CONTRACTS.get(dataset)
        if contract is None:
            supported = ", ".join(sorted(DATASET_CONTRACTS))
            raise DatasetUnavailableError(f"Unsupported dataset '{dataset}'. Supported: {supported}.")
        if not force:
            cached = self._read_cached(contract)
            if cached is not None:
                return cached
        loader = self._loader(contract)
        frames: list[pl.DataFrame] = []
        for season in self.seasons:
            try:
                frame = loader([season])
            except Exception as exc:
                if isinstance(exc, (DatasetUnavailableError, DatasetSchemaError)):
                    raise
                raise DatasetUnavailableError(
                    f"Unable to load '{dataset}' for season {season}: {exc}"
                ) from exc
            if not isinstance(frame, pl.DataFrame):
                raise DatasetSchemaError(f"Dataset '{dataset}' did not return a Polars DataFrame.")
            self.validate(contract, frame)
            if frame.is_empty():
                raise DatasetUnavailableError(f"Dataset '{dataset}' has no rows for season {season}.")
            if "season" in frame.columns:
                if frame.get_column("season").null_count():
                    raise DatasetSchemaError(
                        f"Dataset '{dataset}' returned null seasons when {season} was requested."
                    )
                observed = set(frame.get_column("season").drop_nulls().cast(pl.Int64).to_list())
                if observed != {season}:
                    raise DatasetSchemaError(
                        f"Dataset '{dataset}' returned seasons {sorted(observed)} when {season} was requested."
                    )
            frame = self._canonicalize(contract, frame)
            path = self._cache_path(dataset, season)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = path.with_suffix(path.suffix + ".tmp")
            frame.write_parquet(temporary_path)
            temporary_path.replace(path)
            frames.append(frame)
        return pl.concat(frames, how="diagonal_relaxed")

    def download(
        self,
        datasets: Iterable[str] = DEFAULT_DATASETS,
        *,
        force: bool = False,
    ) -> tuple[dict[str, pl.DataFrame], Path, DataManifest]:
        keys = sorted(set(datasets))
        if not keys:
            raise ValueError("At least one dataset is required.")
        frames = {key: self.fetch(key, force=force) for key in keys}
        files: list[CachedDatasetFile] = []
        for key in keys:
            for season in self.seasons:
                path = self._cache_path(key, season)
                season_frame = pl.read_parquet(path)
                files.append(CachedDatasetFile(
                    dataset=key,
                    season=season,
                    relative_path=path.relative_to(self.cache_dir).as_posix(),
                    sha256=sha256_file(path),
                    row_count=season_frame.height,
                    columns=season_frame.columns,
                ))
        manifest = DataManifest(
            seasons=self.seasons,
            sources=[DATASET_CONTRACTS[key].source() for key in keys],
            files=files,
        ).with_hash()
        return frames, manifest.write(self.manifest_dir), manifest


def fixture_csv_loader(path: Path) -> DatasetLoader:
    """Build an injected offline loader for tests and documented fixture runs."""
    def load(seasons: list[int]) -> pl.DataFrame:
        frame = pl.read_csv(path, try_parse_dates=True)
        return frame.filter(pl.col("season").is_in(seasons))

    return load
