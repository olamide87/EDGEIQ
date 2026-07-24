import dataclasses
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any


SERIALIZATION_VERSION = "canonical-json.v1"


def canonical_timestamp(value: datetime) -> str:
    utc = value.astimezone(timezone.utc)
    return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {
            field.name: canonical_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if field.name != "recorded_at"
        }
    if isinstance(value, (dict, MappingProxyType)):
        return {str(key): canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [canonical_value(item) for item in value]
    if isinstance(value, datetime):
        return canonical_timestamp(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_hash(value: Any, *, namespace: str) -> str:
    payload = f"{namespace}\n{canonical_json(value)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
