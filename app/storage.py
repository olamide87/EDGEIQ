import json
from pathlib import Path
from app.models import Offer


def append_snapshot(offers: list[Offer], path: str = "data/odds_snapshots.jsonl") -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        for offer in offers:
            handle.write(json.dumps(offer.model_dump(mode="json")) + "\n")
