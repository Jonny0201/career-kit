"""Opaque prefixed identifier registry.

Identifiers are never used for canonical event ordering.
"""

from __future__ import annotations

import re
import uuid

from career_kit.errors import ContractError


ID_PREFIXES = {
    "company": "cmp",
    "application": "app",
    "account": "acct",
    "mail_thread": "mail",
    "artifact": "art",
    "execution": "exe",
    "event": "evt",
}

_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-f]{32}$")
_ENTITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")


def new_id(namespace: str) -> str:
    try:
        prefix = ID_PREFIXES[namespace]
    except KeyError as exc:
        raise ContractError(
            "UNKNOWN_ID_NAMESPACE",
            f"unknown ID namespace: {namespace}",
            {"namespace": namespace},
        ) from exc
    return f"{prefix}_{uuid.uuid4().hex}"


def validate_generated_id(value: str) -> None:
    if not _SAFE_ID.fullmatch(value) or value.split("_", 1)[0] not in set(ID_PREFIXES.values()):
        raise ContractError("INVALID_GENERATED_ID", "ID does not match the frozen format")


def validate_entity_id(value: str) -> None:
    if not _ENTITY_ID.fullmatch(value) or value in {".", ".."}:
        raise ContractError(
            "INVALID_ENTITY_ID",
            "entity ID contains an unsafe path character or length",
            {"entity_id": value},
        )
