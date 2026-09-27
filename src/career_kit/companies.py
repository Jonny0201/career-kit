"""User-owned seed lists and resumable, evidence-bound company batches."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .canonical_json import canonical_sha256
from .errors import ContractError
from .store import Store
from .workflows import Workflows, name_key, official_url, require, website_key


def read_seeds(paths, relative):
    require(relative.startswith(("local/inputs/", "data/drafts/", "runtime.nosync/work/")),
            "INPUT_FORBIDDEN", "keep the user's list in this workspace's private input directories")
    file = paths.path(relative)
    require(file.is_file() and file.stat().st_size <= 5_000_000, "INPUT_INVALID", "seed input is missing or too large")
    text = file.read_text(encoding="utf-8-sig")
    if file.suffix.lower() == ".json":
        value = json.loads(text)
    elif file.suffix.lower() == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        require(reader.fieldnames and set(reader.fieldnames) <= {"name", "url", "notes", "channel"}
                and ({"name", "url"} & set(reader.fieldnames)), "SEED_FORMAT_INVALID", "CSV headers are name,url,notes,channel; normalize other sheets with the agent first")
        value = {"source": relative, "companies": list(reader)}
    elif file.suffix.lower() == ".txt":
        value = {"source": relative, "companies": [line.strip() for line in text.splitlines() if line.strip()]}
    else:
        raise ContractError("SEED_FORMAT_INVALID", "use UTF-8 JSON/CSV/text; the agent must normalize spreadsheets locally, never execute cells or macros")
    require(isinstance(value, dict), "SEED_FORMAT_INVALID", "seed JSON must be an object")
    return value


class CompanyIntake:
    def __init__(self, paths):
        self.store = Store(paths)
        self.flow = Workflows(paths)

    def import_seeds(self, source):
        require(isinstance(source.get("source"), str) and source["source"].strip()
                and isinstance(source.get("companies"), list), "SEED_FORMAT_INVALID", "give a source and company rows; an empty list must be an explicit user report")
        rows = source["companies"]
        require(len(rows) <= 5000, "SEED_FORMAT_INVALID", "split lists larger than 5000 rows into explicit batches")
        cleaned = {}
        for number, value in enumerate(rows, 1):
            if isinstance(value, str):
                value = value.strip()
                value = {"url": value} if value.startswith("https://") else {"name": value}
            require(isinstance(value, dict), "SEED_FORMAT_INVALID", "each row must be a name, HTTPS URL or object")
            require(set(value) <= {"name", "url", "notes", "channel"}, "SEED_FORMAT_INVALID", "normalize company columns before import; do not silently copy unrelated personal columns")
            name, url = value.get("name", ""), value.get("url", "")
            notes, channel = value.get("notes", ""), value.get("channel") or "unknown"
            require(all(isinstance(v, str) for v in (name, url, notes)) and (name.strip() or url.strip()),
                    "SEED_FORMAT_INVALID", "each row needs a nonempty company name or source URL")
            require(channel in {"unknown", "direct", "recruiter"}, "SEED_FORMAT_INVALID", "channel is unknown, direct or recruiter")
            if url:
                official_url(url)  # Syntax only, never official-identity verification.
            key = "name:" + name_key(name) if name.strip() else "url:" + website_key(url)
            if key not in cleaned:
                cleaned[key] = {"seed_id": "seed_" + canonical_sha256(key)[:24], "name": name.strip() or None,
                                "supplied_urls": [], "notes": [], "source_rows": [], "channels": []}
            row = cleaned[key]
            row["source_rows"].append(number)
            for field, item in (("supplied_urls", url.strip()), ("notes", notes.strip()), ("channels", channel)):
                if item and item not in row[field]: row[field].append(item)
        identifier = "seeds_" + canonical_sha256(source)[:24]
        existing = [r for r in self.store.list("company_seeds") if r["id"] == identifier]
        if existing:
            return {"id": identifier, "revision": existing[0]["revision"], "reused": True}
        return self.store.put("company_seeds", identifier,
            {"source": source["source"], "source_hash": canonical_sha256(source), "rows": list(cleaned.values()),
             "input_row_count": len(rows), "duplicate_row_count": len(rows) - len(cleaned), "status": "unverified_leads"},
            reason="Preserve this user's own initial list; importing is neither identity verification nor registry approval")

    def show_seeds(self, identifier):
        record = self.store.get("company_seeds", identifier)
        return {"id": identifier, "revision": record["revision"],
                "input_row_count": record["payload"]["input_row_count"], "duplicate_row_count": record["payload"]["duplicate_row_count"],
                "rows": [{k: row[k] for k in ("seed_id", "name", "supplied_urls", "source_rows", "channels")} for row in record["payload"]["rows"]],
                "notes_included": False, "verified": False, "approved": False}

    def propose_batch(self, source):
        require(isinstance(source.get("source"), str) and source["source"].strip()
                and isinstance(source.get("companies"), list) and source["companies"], "BATCH_INVALID", "give provenance and researched company proposals")
        preferences = self.flow.candidate("preferences")
        origin = source.get("origin", "seed_list")
        require(origin in {"seed_list", "discovery"}, "BATCH_INVALID", "origin is seed_list or discovery")
        seeds = None
        if origin == "seed_list":
            ref = source.get("seed_batch", {})
            seeds = self.store.get("company_seeds", ref.get("id", ""), ref.get("revision"))
            require(ref.get("revision") == seeds["revision"], "BATCH_INVALID", "bind the exact imported list revision")
            seed_ids = {row["seed_id"] for row in seeds["payload"]["rows"]}
        else:
            require(preferences["payload"].get("company_search", {}).get("allow_discovery") is True,
                    "DISCOVERY_NOT_REQUESTED", "ask whether the user wants preference-based discovery; do not borrow a contributor's list")
        require(len(source["companies"]) <= 500, "BATCH_INVALID", "use at most 500 reviewed company proposals per batch")
        # Validate the entire input before publishing any company record.
        identities = {}
        for proposal in source["companies"]:
            require(isinstance(proposal, dict), "BATCH_INVALID", "company proposal must be an object")
            self.flow.company_validate(proposal)
            key = website_key(proposal["official_url"])
            require(key not in identities or identities[key] == name_key(proposal["name"]),
                    "COMPANY_IDENTITY_AMBIGUOUS", "different names share one proposed identity URL; resolve aliases or separate official identities before publishing")
            identities[key] = name_key(proposal["name"])
            if seeds:
                refs = proposal.get("seed_refs", [])
                require(refs and all(ref in seed_ids for ref in refs), "BATCH_INVALID", "each researched company must reference its actual input rows")
            labels = [row["name"] for row in seeds["payload"]["rows"] if row["seed_id"] in proposal["seed_refs"] and row["name"]] if seeds else []
            if not self.flow.company_excluded({**proposal, "seed_names": labels}):
                self.flow.company_target(proposal)
        identifier = "cbatch_" + canonical_sha256([source, preferences["revision"]])[:24]
        existing = [b for b in self.store.list("company_batch") if b["id"] == identifier]
        if existing:
            return {"id": identifier, "revision": existing[0]["revision"], "reused": True}
        items, seen = [], set()
        for proposal in source["companies"]:
            if seeds:
                labels = [row["name"] for row in seeds["payload"]["rows"] if row["seed_id"] in proposal["seed_refs"] and row["name"]]
                proposal = {**proposal, "seed_names": labels}
            key = website_key(proposal["official_url"])
            if key in seen: continue
            seen.add(key)
            if self.flow.company_excluded(proposal):
                items.append({"status": "excluded", "name": proposal["name"], "reason": "user_blacklist", "reviewable": False})
                continue
            ref = self.flow.company_propose(proposal)
            record = self.store.get("company", ref["id"], ref["revision"])
            items.append({"id": ref["id"], "revision": ref["revision"], "name": record["payload"]["name"],
                          "status": record["payload"]["status"], "reviewable": record["payload"]["status"] == "proposed"})
        return self.store.put("company_batch", identifier,
            {"source_hash": canonical_sha256(source), "source": source["source"], "origin": origin,
             "seed_batch": source.get("seed_batch"), "preferences_revision": preferences["revision"],
             "items": items, "status": "proposed"}, reason="Prepared an exact, locally reviewable company admission batch; existing registry decisions are retained")

    def review_batch(self, identifier, revision, decision, *, failpoint=None):
        require(decision in {"approved", "rejected", "watchlist"}, "DECISION_INVALID", "record the actual user decision")
        batch = self.store.get("company_batch", identifier)
        value = batch["payload"]
        if value["status"] in {"reviewing", "reviewed"}:
            require(value.get("reviewed_revision") == revision and value.get("decision") == decision,
                    "REVISION_CONFLICT", "resume only the same exact authorized batch decision")
            if value["status"] == "reviewed": return {"id": identifier, "revision": batch["revision"], "reused": True}
        else:
            require(batch["revision"] == revision, "REVISION_CONFLICT", "batch changed after presentation")
        require(self.flow.candidate("preferences")["revision"] == value["preferences_revision"],
                "BATCH_PREFERENCES_CHANGED", "refresh this batch against the user's changed preferences")
        pending = [item for item in value["items"] if item["reviewable"]]
        reason = "User batch decision " + identifier + " " + revision
        for item in pending:
            current = self.store.get("company", item["id"])
            completed_here = current["previous"] == item["revision"] and current["reason"] == reason and current["payload"]["status"] == decision
            require(current["revision"] == item["revision"] or completed_here, "REVISION_CONFLICT", "a company changed independently; do not overwrite that decision")
            if decision == "approved":
                require(not self.flow.company_excluded(current["payload"]), "COMPANY_EXCLUDED", "a company is now excluded")
        if value["status"] == "proposed":
            saved = self.store.put("company_batch", identifier, {**value, "status": "reviewing", "reviewed_revision": revision, "decision": decision},
                                   expected=batch["revision"], actor="user", reason="User authorized this exact displayed batch; persist intent before updating members")
            batch = self.store.get("company_batch", identifier, saved["revision"])
        for item in pending:
            current = self.store.get("company", item["id"])
            if current["revision"] == item["revision"]:
                self.store.put("company", item["id"], {**current["payload"], "status": decision}, expected=item["revision"], actor="user", reason=reason)
            if failpoint: failpoint(item["id"])
        return self.store.put("company_batch", identifier, {**batch["payload"], "status": "reviewed"},
                              expected=batch["revision"], actor="user", reason="Completed the exact batch decision; no application or external effect was created")
