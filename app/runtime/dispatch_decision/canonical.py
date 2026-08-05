import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from app.runtime.dispatch_decision.domain import DispatchDecisionInvalid


def canonical_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise DispatchDecisionInvalid("Canonical timestamps must be timezone-aware.")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise DispatchDecisionInvalid("Canonical map keys must be strings.")
        normalized = [(unicodedata.normalize("NFC", key), canonical_value(item)) for key, item in value.items()]
        if len({key for key, _ in normalized}) != len(normalized):
            raise DispatchDecisionInvalid("Canonical map keys collide after Unicode normalization.")
        return {key: item for key, item in sorted(normalized)}
    if isinstance(value, (tuple, list)):
        return [canonical_value(item) for item in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    raise DispatchDecisionInvalid(f"Unsupported canonical value: {type(value).__name__}.")


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonical_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def namespaced_digest(namespace: str, content: bytes) -> str:
    return hashlib.sha256(namespace.encode() + b"\n" + content).hexdigest()
