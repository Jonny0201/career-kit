"""Crash-safe same-filesystem file publication."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path

from career_kit.errors import ContractError


Failpoint = Callable[[str, Path, Path], None]


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_temporary(target: Path, data: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    return temporary


def atomic_publish_noreplace(
    target: Path,
    data: bytes,
    *,
    failpoint: Failpoint | None = None,
) -> None:
    """Publish a complete file atomically and fail if *target* exists."""

    temporary = _write_temporary(target, data)
    try:
        if failpoint:
            failpoint("temporary_fsynced", temporary, target)
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise ContractError(
                "ATOMIC_TARGET_EXISTS",
                "refusing to replace an immutable target",
                {"target": str(target)},
            ) from exc
        _fsync_directory(target.parent)
        if failpoint:
            failpoint("target_published", temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
        _fsync_directory(target.parent)


def atomic_replace(
    target: Path,
    data: bytes,
    *,
    failpoint: Failpoint | None = None,
) -> None:
    """Atomically replace a mutable derived pointer or projection."""

    temporary = _write_temporary(target, data)
    try:
        if failpoint:
            failpoint("temporary_fsynced", temporary, target)
        os.replace(temporary, target)
        _fsync_directory(target.parent)
        if failpoint:
            failpoint("target_replaced", temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def cleanup_interrupted_writes(directory: Path) -> list[Path]:
    removed: list[Path] = []
    if not directory.exists():
        return removed
    for path in directory.rglob(".*.tmp"):
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed
