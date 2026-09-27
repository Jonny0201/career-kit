"""Reviewed, user-supplied document backends; no bundled production template."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata

from .atomic import atomic_publish_noreplace
from .canonical_json import canonical_sha256, pretty_bytes
from .errors import ContractError
from .ids import new_id
from .store import Store, safe_id
from .workflows import Workflows, require, job_content_hash


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(text):
    return "".join(unicodedata.normalize("NFKC", text).split())


def document_slot(value):
    purpose = value.get("purpose", "submission")
    base = value.get("translation_of", {}).get("source_purpose", "submission") if purpose == "review_only" else purpose
    container = "correspondence_documents" if base == "correspondence" else "documents"
    slot = value["document_type"] if purpose != "review_only" else value["document_type"] + ":review_only:" + value["language"]
    return container, slot


class Documents:
    def __init__(self, paths):
        self.paths = paths
        self.store = Store(paths)
        self.flow = Workflows(paths)

    def profile_manifest(self, identifier):
        safe_id(identifier)
        root = self.paths.permanent("local/document-profiles/" + identifier)
        file = self.paths.permanent(f"local/document-profiles/{identifier}/profile.json")
        require(file.is_file(), "DOCUMENT_PROFILE_MISSING", "provide a template and implement a private document backend first")
        value = json.loads(file.read_text())
        require(value.get("schema_version") == 1 and value.get("id") == identifier,
                "DOCUMENT_PROFILE_INVALID", "profile identity/version differs")
        require(set(value.get("document_types", [])) <= {"resume", "cover_letter"} and value.get("document_types"),
                "DOCUMENT_PROFILE_INVALID", "declare supported document types")
        require(value.get("output") in {"pdf", "text"}, "DOCUMENT_PROFILE_INVALID", "declare one output modality")
        entrypoint = value.get("entrypoint")
        require(isinstance(entrypoint, str) and entrypoint.endswith(".py"), "DOCUMENT_PROFILE_INVALID", "the version-one launcher is a reviewed local Python entrypoint")
        executable = self.paths.permanent(f"local/document-profiles/{identifier}/{entrypoint}")
        require(executable.is_file() and executable.is_relative_to(root), "DOCUMENT_PROFILE_INVALID", "entrypoint must be within this profile")
        require(isinstance(value.get("languages"), list) and value["languages"], "DOCUMENT_PROFILE_INVALID", "declare output languages")
        files = {}
        for item in sorted(root.rglob("*")):
            require(not item.is_symlink(), "DOCUMENT_PROFILE_INVALID", "profile assets cannot use symbolic links")
            if item.is_file():
                files[item.relative_to(root).as_posix()] = digest(item)
        return value, files, canonical_sha256(files)

    def register(self, identifier):
        value, files, code_hash = self.profile_manifest(identifier)
        previous = [p for p in self.store.list("document_profile") if p["id"] == identifier]
        return self.store.put("document_profile", identifier,
            {"manifest": value, "files": files, "code_hash": code_hash, "status": "proposed"},
            expected=previous[0]["revision"] if previous else None,
            reason="Propose the exact local renderer, assets and dependencies for user review")

    def approve(self, identifier, revision):
        profile = self.store.get("document_profile", identifier)
        _, _, current = self.profile_manifest(identifier)
        require(profile["revision"] == revision and profile["payload"]["code_hash"] == current,
                "DOCUMENT_PROFILE_CHANGED", "profile changed after review")
        return self.store.put("document_profile", identifier, {**profile["payload"], "status": "approved"},
                              expected=revision, actor="user", reason="User approved this exact local executable and template package")

    def check(self, identifier):
        value, _, code_hash = self.profile_manifest(identifier)
        profile = self.store.get("document_profile", identifier)
        require(profile["payload"].get("status") == "approved" and profile["payload"]["code_hash"] == code_hash,
                "DOCUMENT_PROFILE_CHANGED", "approve this exact renderer before using it")
        dependencies = value.get("required_commands", [])
        require(all(isinstance(name, str) and re.fullmatch(r"[\w.-]+", name) for name in dependencies), "DOCUMENT_PROFILE_INVALID", "dependencies are command names, not shell expressions")
        missing = [name for name in dependencies if shutil.which(name) is None]
        return {"ok": not missing, "profile_id": identifier, "code_hash": code_hash, "missing_commands": missing}

    def render(self, application_id, identifier, content):
        app = self.store.get("application", application_id)
        check = self.check(identifier)
        require(check["ok"], "DOCUMENT_DEPENDENCY_MISSING", "install only the selected profile's missing tools")
        profile = self.store.get("document_profile", identifier)
        manifest = profile["payload"]["manifest"]
        kind = content.get("document_type")
        language = content.get("language")
        purpose = content.get("purpose", "submission")
        require(purpose in {"submission", "review_only", "correspondence"}, "DOCUMENT_PURPOSE_INVALID", "declare submission, review-only or separately requested correspondence")
        if purpose == "correspondence":
            require(isinstance(content.get("request_ref"), str) and content["request_ref"].strip(),
                    "DOCUMENT_REQUEST_REQUIRED", "bind correspondence to the actual user/HR follow-up request")
        translation = None
        if purpose == "review_only":
            ref = content.get("translation_of", {})
            original = self.store.get("document", ref.get("id", ""), ref.get("revision"))
            source_purpose = original["payload"].get("purpose", "submission")
            source_container = "correspondence_documents" if source_purpose == "correspondence" else "documents"
            require(ref.get("revision") == original["revision"] and kind == "cover_letter"
                    and original["payload"]["application_id"] == application_id
                    and original["payload"]["document_type"] == kind and source_purpose in {"submission", "correspondence"}
                    and app["payload"].get(source_container, {}).get(kind) == ref,
                    "DOCUMENT_TRANSLATION_INVALID", "bind a review-only companion to this application's current submission letter")
            translation = {**ref, "artifact_sha256": original["payload"]["artifact_sha256"], "source_purpose": source_purpose}
        correspondence = purpose == "correspondence" or (translation and translation["source_purpose"] == "correspondence")
        require(app["payload"]["submitted_at"] is None or correspondence, "APPLICATION_ALREADY_SUBMITTED",
                "preserve the submitted documents; use separately requested correspondence for a follow-up")
        require(kind in manifest["document_types"] and language in manifest["languages"], "DOCUMENT_PROFILE_INVALID", "profile does not support this document/language")
        if kind == "cover_letter" and not correspondence:
            requirements = app["payload"].get("requirements")
            require(requirements and requirements["cover_letter"] in {"required", "optional"},
                    "DOCUMENT_NOT_REQUESTED", "Cover Letter follows actual application-page requirements, not the JD alone")
        bank = self.flow.candidate("facts")
        identity = self.flow.candidate("profile")
        require(content.get("facts_revision") == bank["revision"], "DOCUMENT_SOURCE_STALE", "content must bind the current approved facts")
        require(content.get("application_id") == application_id, "DOCUMENT_APPLICATION_MISMATCH", "content belongs to another application")
        facts = {f["id"]: f for f in bank["payload"]["facts"]}
        claims = content.get("claims", [])
        require(claims and all(c.get("text") for c in claims), "DOCUMENT_CLAIM_INVALID", "document claims cannot be empty")
        for claim in claims:
            category = claim.get("kind", "candidate")
            if category == "candidate":
                require(claim.get("fact_refs") and all(ref in facts and kind in facts[ref]["allowed_outputs"] for ref in claim["fact_refs"]),
                        "DOCUMENT_CLAIM_INVALID", "claim references unapproved or output-forbidden facts")
            elif category == "company":
                company = self.store.get("company", app["payload"]["job"]["company_id"])
                from .workflows import official_url
                evidence = company["payload"].get("evidence")
                require(isinstance(evidence, list), "DOCUMENT_CLAIM_INVALID", "company prose needs structured official evidence")
                known = {e["id"]: e for e in evidence if isinstance(e, dict) and e.get("id") and e.get("url") and e.get("excerpt")}
                refs = claim.get("company_evidence_refs", [])
                require(kind == "cover_letter" and refs and all(ref in known for ref in refs), "DOCUMENT_CLAIM_INVALID", "bind company assertions to official evidence, not candidate facts")
                hosts = {official_url(company["payload"]["official_url"]), *company["payload"].get("verified_careers_hosts", [])}
                require(all(official_url(known[ref]["url"]) in hosts for ref in refs), "DOCUMENT_CLAIM_INVALID", "company evidence is not from its verified official sources")
            else:
                require(kind == "cover_letter" and category in {"interest", "closing"} and not claim.get("fact_refs"),
                        "DOCUMENT_CLAIM_INVALID", "only explicitly labelled non-factual letter statements may omit evidence")
        allowed_identity = set(manifest.get("identity_fields", []))
        require(allowed_identity <= {"display_name", "email", "phone", "location", "links"}, "DOCUMENT_PROFILE_INVALID", "profile requests forbidden identity fields")
        injected = {k: identity["payload"].get(k) for k in allowed_identity}
        # Localized names/locations are user-authored, never guessed or translated.
        injected = {k: v.get(language) if isinstance(v, dict) else v for k, v in injected.items()}
        require(all(isinstance(v, str) and v for v in injected.values()), "DOCUMENT_IDENTITY_MISSING", "complete the profile's requested identity values locally")
        expected_text = [str(c["text"]) for c in claims] + list(injected.values())
        static = manifest.get("static_text", [])
        require(all(isinstance(t, str) for t in static), "DOCUMENT_PROFILE_INVALID", "static labels must be explicit strings")
        self.paths.initialize_runtime()
        with tempfile.TemporaryDirectory(prefix="document-", dir=self.paths.runtime_path("work")) as temporary:
            work = Path(temporary)
            request = {"schema_version": 1, "document_type": kind, "language": language,
                       "claims": claims, "identity": injected, "static_text": static,
                       "job": {k: app["payload"]["job"][k] for k in ("title", "description")}}
            input_path = work / "input.json"
            input_path.write_bytes(pretty_bytes(request)); input_path.chmod(0o600)
            entry = self.paths.permanent(f"local/document-profiles/{identifier}/{manifest['entrypoint']}")
            environment = {k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}}
            environment.update(PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(work), TEMP=str(work), TMP=str(work))
            try:
                result = subprocess.run([sys.executable, str(entry), "--input", str(input_path), "--output-dir", str(work)],
                                        cwd=work, env=environment, capture_output=True, timeout=180)
            except subprocess.TimeoutExpired:
                raise ContractError("DOCUMENT_RENDER_TIMEOUT", "renderer timed out; private subprocess output is withheld") from None
            require(result.returncode == 0, "DOCUMENT_RENDER_FAILED", "renderer failed; raw output is not exposed because it may contain private values")
            output = work / ("document.pdf" if manifest["output"] == "pdf" else "document.txt")
            require(output.is_file() and not output.is_symlink(), "DOCUMENT_RENDER_FAILED", "renderer did not create the required regular output file")
            if manifest["output"] == "pdf":
                from pypdf import PdfReader
                pdf = PdfReader(output)
                require(not pdf.is_encrypted and len(pdf.pages) > 0, "DOCUMENT_VALIDATION_FAILED", "output must be a readable PDF")
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                page_count = len(pdf.pages)
                maximum = manifest.get("maximum_pages")
                require(maximum is None or (isinstance(maximum, int) and page_count <= maximum), "DOCUMENT_VALIDATION_FAILED", "PDF exceeds this user's page limit")
            else:
                text = output.read_text(encoding="utf-8")
                page_count = None
            normalized = compact(text)
            require(all(compact(t) in normalized for t in expected_text), "DOCUMENT_VALIDATION_FAILED", "output lost expected identity or claim text")
            remaining = normalized
            for phrase in sorted(expected_text + static, key=len, reverse=True):
                remaining = remaining.replace(compact(phrase), "")
            require(not any(c.isalnum() for c in remaining), "DOCUMENT_VALIDATION_FAILED", "output includes undeclared text; account for headings or unsupported additions")
            require(self.profile_manifest(identifier)[2] == check["code_hash"] and self.flow.candidate("facts")["revision"] == bank["revision"]
                    and self.flow.candidate("profile")["revision"] == identity["revision"], "DOCUMENT_SOURCE_STALE", "inputs changed while rendering")
            doc_id = new_id("artifact")
            destination = self.paths.permanent(f"data/documents/{doc_id}/{output.name}")
            atomic_publish_noreplace(destination, output.read_bytes())
            record = self.store.put("document", doc_id, {
                "application_id": application_id, "document_type": kind, "language": language,
                "purpose": purpose, "translation_of": translation, "job_content_hash": job_content_hash(app["payload"]["job"]),
                "request_ref": content.get("request_ref"),
                "profile_id": identifier, "profile_hash": check["code_hash"],
                "facts_revision": bank["revision"], "identity_revision": identity["revision"],
                "content_hash": canonical_sha256(content), "content_snapshot": content,
                "artifact": destination.relative_to(self.paths.root).as_posix(),
                "artifact_sha256": digest(destination), "claim_refs": [ref for c in claims for ref in c.get("fact_refs", [])],
                "text_extraction_passed": True, "page_count": page_count, "review": "pending",
                "visual_review": "required", "semantic_truth_review": "required",
            }, reason="Generated document; machine text checks are not human visual or factual approval")
        return self.attach(application_id, record["id"])

    def attach(self, application_id, doc_id):
        """Recover publication after a committed document but interrupted app link."""
        document = self.store.get("document", doc_id)
        app = self.store.get("application", application_id)
        require(document["payload"]["application_id"] == application_id, "DOCUMENT_APPLICATION_MISMATCH", "document belongs to another application")
        value = document["payload"]
        require(digest(self.paths.permanent(value["artifact"])) == value["artifact_sha256"], "DOCUMENT_CHANGED", "document bytes changed")
        ref = {"id": doc_id, "revision": document["revision"]}
        container, slot = document_slot(value)
        if app["payload"].get(container, {}).get(slot) != ref:
            require(app["payload"]["submitted_at"] is None or container == "correspondence_documents", "APPLICATION_ALREADY_SUBMITTED", "do not rewrite an actual submission's document references")
            self.store.put("application", application_id,
                {**app["payload"], container: {**app["payload"].get(container, {}), slot: ref}},
                expected=app["revision"], reason="Attach exact prepared or reviewed document without recreating the application")
        return {**ref, "artifact": value["artifact"], "artifact_sha256": value["artifact_sha256"], "review": value["review"], "purpose": value.get("purpose", "submission"), "slot": slot, "container": container}

    def review(self, doc_id, revision, decision, feedback):
        require(decision in {"approved", "revise", "rejected", "skipped"} and feedback, "REVIEW_INVALID", "give a decision and the user's feedback")
        record = self.store.get("document", doc_id)
        app = self.store.get("application", record["payload"]["application_id"])
        value = record["payload"]
        container, slot = document_slot(value)
        require(app["payload"]["submitted_at"] is None or container == "correspondence_documents", "APPLICATION_ALREADY_SUBMITTED", "preserve the review version used for an actual submission")
        require(app["payload"].get(container, {}).get(slot, {}).get("id") == doc_id, "DOCUMENT_NOT_CURRENT", "this document was superseded; select it explicitly before reviewing instead of silently replacing a newer artifact")
        require(record["revision"] == revision, "REVISION_CONFLICT", "review targets a different document revision")
        require(digest(self.paths.permanent(record["payload"]["artifact"])) == record["payload"]["artifact_sha256"], "DOCUMENT_CHANGED", "artifact changed after presentation")
        if decision == "approved":
            require(self.flow.candidate("facts")["revision"] == record["payload"]["facts_revision"]
                    and self.flow.candidate("profile")["revision"] == record["payload"]["identity_revision"],
                    "DOCUMENT_SOURCE_STALE", "candidate sources changed; review a refreshed document, not stale content")
            require(record["payload"].get("job_content_hash") == job_content_hash(app["payload"]["job"]),
                    "DOCUMENT_SOURCE_STALE", "job content changed; do not approve an old document against a different JD")
            if value.get("purpose") == "review_only":
                source = app["payload"].get(container, {}).get("cover_letter")
                require(source and self.store.get("document", source["id"], source["revision"])["payload"]["artifact_sha256"] == value["translation_of"]["artifact_sha256"],
                        "DOCUMENT_SOURCE_STALE", "the submission letter changed; refresh its review-only companion")
        updated = self.store.put("document", doc_id, {**record["payload"], "review": decision, "feedback": feedback,
            "visual_review": "user_reviewed" if decision == "approved" else "required",
            "semantic_truth_review": "user_reviewed" if decision == "approved" else "required"},
            expected=revision, actor="user", reason="Exact human document decision; not permission to send or submit")
        self.attach(record["payload"]["application_id"], doc_id)
        return updated
