from pathlib import Path
import json

from pydantic import BaseModel, field_validator


class ResearchConfig(BaseModel):
    seasons: list[int]
    data_dir: Path = Path("data")
    dataset_path: Path = Path("data/processed/wr_receptions.parquet")

    @field_validator("seasons")
    @classmethod
    def validate_seasons(cls, value: list[int]) -> list[int]:
        seasons = sorted(set(value))
        if not seasons or any(season < 1920 or season > 2100 for season in seasons):
            raise ValueError("seasons must contain valid NFL seasons")
        return seasons

    @classmethod
    def from_json(cls, path: Path) -> "ResearchConfig":
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
