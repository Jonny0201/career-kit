"""Immutable revisions and a hash-chained journal; no mutable data is Git policy."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import json
import os
import re

from .atomic import atomic_publish_noreplace
from .canonical_json import canonical_sha256, pretty_bytes
from .errors import ContractError

KINDS = {"candidate_profile", "candidate_facts", "candidate_history", "preferences",
         "company", "job", "application", "document_profile", "document", "review",
         "mail_draft", "mail_message", "effect", "outcome", "account",
         "company_seeds", "company_batch"}


def utc_now():
    return datetime.now(UTC).isoformat()


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}", value):
        raise ContractError("ID_INVALID", "record identifier is invalid")
    return value


@contextmanager
def writer_lock(paths):
    paths.initialize_runtime()
    lock = paths.runtime_path("locks/writer.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ContractError("WORKSPACE_BUSY", "a writer lock exists; inspect the owning process before recovery, never delete another task's lock")
    try:
        try:
            os.write(fd, str(os.getpid()).encode())
        finally:
            os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


class Store:
    def __init__(self, paths):
        self.paths = paths
        self.journal = paths.permanent("data/journal")

    def events(self):
        previous = None
        result = []
        if not self.journal.exists():
            return result
        for index, file in enumerate(sorted(self.journal.glob("*.json")), 1):
            if file.is_symlink() or file.name != f"{index:012d}.json":
                raise ContractError("JOURNAL_INVALID", "journal sequence or path is invalid")
            value = json.loads(file.read_text())
            digest = value.get("hash")
            base = {key: item for key, item in value.items() if key != "hash"}
            if value.get("sequence") != index or value.get("previous") != previous or canonical_sha256(base) != digest:
                raise ContractError("JOURNAL_INVALID", "journal integrity mismatch")
            previous = digest
            result.append(value)
        return result

    def _record_path(self, kind, identifier, digest):
        if kind not in KINDS or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError("RECORD_INVALID", "record kind or revision is invalid")
        return self.paths.permanent(f"data/records/{kind}/{safe_id(identifier)}/{digest}.json")

    def _read(self, event):
        file = self._record_path(event["kind"], event["id"], event["revision"])
        if not file.is_file():
            raise ContractError("RECORD_INVALID", "committed record is missing")
        record = json.loads(file.read_text())
        if canonical_sha256(record) != event["revision"] or record["kind"] != event["kind"] or record["id"] != event["id"]:
            raise ContractError("RECORD_INVALID", "record integrity mismatch")
        return {**record, "revision": event["revision"]}

    def get(self, kind, identifier, revision=None):
        safe_id(identifier)
        events = [e for e in self.events() if e["kind"] == kind and e["id"] == identifier and (revision is None or e["revision"] == revision)]
        if not events:
            raise ContractError("RECORD_NOT_FOUND", "no committed record matches this reference")
        return self._read(events[-1])

    def list(self, kind):
        latest = {}
        for event in self.events():
            if event["kind"] == kind:
                latest[event["id"]] = event
        return [self._read(event) for event in latest.values()]

    def put(self, kind, identifier, payload, *, expected=None, actor="agent", reason="", failpoint=None):
        if kind not in KINDS or not isinstance(payload, dict) or not reason.strip():
            raise ContractError("RECORD_INVALID", "registered kind, object payload and reason are required")
        safe_id(identifier)
        with writer_lock(self.paths):
            events = self.events()
            current = [e for e in events if e["kind"] == kind and e["id"] == identifier]
            if (current[-1]["revision"] if current else None) != expected:
                raise ContractError("REVISION_CONFLICT", "source changed; reread it before applying the edit")
            record = {"schema_version": 1, "kind": kind, "id": identifier,
                      "previous": expected, "payload": payload, "actor": actor,
                      "reason": reason, "recorded_at": utc_now()}
            digest = canonical_sha256(record)
            target = self._record_path(kind, identifier, digest)
            atomic_publish_noreplace(target, pretty_bytes(record))
            if failpoint:
                failpoint("record_written")
            base = {"schema_version": 1, "sequence": len(events) + 1,
                    "previous": events[-1]["hash"] if events else None,
                    "kind": kind, "id": identifier, "revision": digest}
            event = {**base, "hash": canonical_sha256(base)}
            atomic_publish_noreplace(self.journal / f"{len(events) + 1:012d}.json", pretty_bytes(event))
            return {"kind": kind, "id": identifier, "revision": digest}

    def verify(self):
        events = self.events()
        committed = set()
        for event in events:
            self._read(event)
            committed.add(self._record_path(event["kind"], event["id"], event["revision"]))
        root = self.paths.permanent("data/records")
        orphans = [p.relative_to(self.paths.root).as_posix() for p in root.glob("*/*/*.json") if p not in committed] if root.exists() else []
        return {"ok": not orphans, "event_count": len(events), "orphan_records": orphans,
                "journal_head": events[-1]["hash"] if events else None}
