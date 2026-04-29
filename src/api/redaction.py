"""Hybrid config redactor: suffix-match + Pydantic ``sensitive=True`` annotation.

Replaces secret-bearing values with ``"***REDACTED***"`` so the result is safe
to return from ``GET /v1/config``.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

REDACTED = "***REDACTED***"
_SUFFIX_RULES = ("_key", "_token", "_secret", "_password")
_CONTAINS_RULES = ("credentials",)


def _matches_suffix_rules(key: str) -> bool:
    k = key.lower()
    return any(k.endswith(s) for s in _SUFFIX_RULES) or any(c in k for c in _CONTAINS_RULES)


def redact(data: Any, *, sensitive_paths: set[tuple[str, ...]] | None = None) -> Any:
    """Walk ``data`` and replace secret-keyed values with ``REDACTED``.

    ``sensitive_paths`` is a set of dotted-path tuples (e.g. ``{("provider", "api_key")}``)
    indicating fields that must be redacted regardless of name. Suffix rules apply on top.
    """
    sensitive_paths = sensitive_paths or set()
    return _walk(data, path=(), sensitive_paths=sensitive_paths)


def _walk(node: Any, *, path: tuple[str, ...], sensitive_paths: set[tuple[str, ...]]) -> Any:
    if isinstance(node, dict):
        out: dict = {}
        for k, v in node.items():
            child_path = path + (str(k),)
            is_sensitive = (
                child_path in sensitive_paths
                or _matches_suffix_rules(str(k))
            )
            if is_sensitive:
                out[k] = REDACTED
            else:
                out[k] = _walk(v, path=child_path, sensitive_paths=sensitive_paths)
        return out
    if isinstance(node, list):
        return [_walk(x, path=path, sensitive_paths=sensitive_paths) for x in node]
    return node


def _collect_sensitive_paths(model_cls: type[BaseModel], prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    """Walk a Pydantic model class and collect dotted paths flagged ``sensitive=True``."""
    paths: set[tuple[str, ...]] = set()
    for name, info in model_cls.model_fields.items():
        full_path = prefix + (name,)
        extra = info.json_schema_extra or {}
        if isinstance(extra, dict) and extra.get("sensitive"):
            paths.add(full_path)
        # Recurse into nested BaseModel annotations
        ann = info.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            paths |= _collect_sensitive_paths(ann, prefix=full_path)
    return paths


def redact_model(model: BaseModel) -> dict:
    """Dump a Pydantic model and apply hybrid redaction (suffix + sensitive=True)."""
    sensitive_paths = _collect_sensitive_paths(type(model))
    return redact(model.model_dump(), sensitive_paths=sensitive_paths)
