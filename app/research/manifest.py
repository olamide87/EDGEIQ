from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(encoded).hexdigest()


class DatasetSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset: str
    loader: str
    source_url: str
    license_name: str
    license_url: str
    attribution: str


class CachedDatasetFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset: str
    season: int
    relative_path: str
    sha256: str
    row_count: int
    columns: list[str]


class DataManifest(BaseModel):
    schema_version: str = "1.0"
    provider: str = "nflverse/nflreadpy"
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    seasons: list[int]
    sources: list[DatasetSource]
    files: list[CachedDatasetFile]
    manifest_hash: str = ""

    def with_hash(self) -> "DataManifest":
        # Capture time remains auditable metadata, but it must not make identical
        # source bytes produce a different reproducibility identifier.
        payload = self.model_dump(mode="json", exclude={"captured_at", "manifest_hash"})
        return self.model_copy(update={"manifest_hash": canonical_hash(payload)})

    def write(self, directory: Path) -> Path:
        manifest = self.with_hash()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"nflverse-{manifest.manifest_hash[:12]}.json"
        path.write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path


def load_manifest(path: Path) -> DataManifest:
    manifest = DataManifest.model_validate_json(path.read_text(encoding="utf-8"))
    expected = manifest.with_hash().manifest_hash
    if manifest.manifest_hash != expected:
        raise ValueError(f"Manifest hash mismatch for {path}.")
    return manifest
