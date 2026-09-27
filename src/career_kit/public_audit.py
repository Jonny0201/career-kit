"""Fail-closed audit of every publishable file, staged blob and Git revision.

This is a coverage/checking tool, not a mathematical proof of absence of unknown
personal information. An agent must also review semantics before publication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from .atomic import atomic_replace
from .canonical_json import canonical_sha256, pretty_bytes
from .errors import ContractError
from .paths import ProjectPaths

PRIVATE = {"data", "local", "credentials", "runtime.nosync", "tmp", "candidate", "applications",
           "opportunities", "companies", "mail", "operations", "event-streams", "artifact-store", "acceptance-cases"}
ALLOWED_SUFFIXES = {".py", ".md", ".json", ".toml", ".sh", ".yml", ".yaml", ".txt"}
PATTERNS = {
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "SECRET_TOKEN": re.compile(r"\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]{20,}\b|\bBearer\s+[A-Za-z0-9._~-]{24,}"),
    "PERSONAL_PATH": re.compile(r"/Users/[A-Za-z0-9._-]+/|[A-Z]:\\Users\\[A-Za-z0-9._-]+\\"),
    "PHONE_OR_IDENTIFIER": re.compile(r"(?<![A-Za-z0-9])\+?\d{10,18}(?![A-Za-z0-9])"),
    "OPAQUE_PAYLOAD": re.compile(r"[A-Za-z0-9+/=]{1024,}"),
}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
SECRET_FIELD = re.compile(r'''["'](?:password|app_password|access_token|refresh_token|cookie|otp|verification_code)["']\s*:\s*["']([^"']*)["']''', re.I)


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)
    return result.stdout


def findings_for(path, data, literals=(), metadata=False):
    findings = []
    if not metadata:
        parts = Path(path).parts
        if any(part in PRIVATE for part in parts) or path.startswith(("resume/template/", "cover-letter/template/")):
            findings.append("PRIVATE_PATH")
        if Path(path).suffix not in ALLOWED_SUFFIXES and Path(path).name not in {"LICENSE", "NOTICE", ".gitignore", "careerkit", "bootstrap", "test", "audit-public", "pre-commit", "pre-push", "commit-msg"}:
            findings.append("UNCLASSIFIED_FILE")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return sorted(set(findings + ["BINARY_OR_ENCODING"]))
    if "\0" in text:
        findings.append("BINARY_OR_ENCODING")
    searchable = text if metadata else path + "\n" + text
    for name, pattern in PATTERNS.items():
        candidate = searchable
        if metadata and name == "PHONE_OR_IDENTIFIER":
            # Exempt actual Git header timestamps, not arbitrary numbers in a
            # commit/tag message. Email addresses have their own check below.
            candidate = re.sub(r"(?m)^((?:author|committer|tagger) .*?>) \d+ [+-]\d{4}$", r"\1 [GIT_TIME]", candidate)
            candidate = EMAIL.sub("[EMAIL_CHECKED_SEPARATELY]", candidate)
        if pattern.search(candidate):
            findings.append(name)
    for match in EMAIL.finditer(text):
        domain = match.group(1).casefold()
        dummy = domain.endswith((".invalid", ".test")) or domain in {"example.com", "example.org", "example.net"}
        public_attribution = metadata and (domain == "users.noreply.github.com" or match[0] == "noreply@github.com")
        # These exact platform/system addresses are public infrastructure, not
        # applicant contact data (including their scanner regression examples).
        if not dummy and not public_attribution and match[0] not in {"git@github.com", "noreply@github.com"}:
            findings.append("NONEXAMPLE_EMAIL")
    if any(term.casefold() in searchable.casefold() for term in literals if term):
        findings.append("PRIVATE_FINGERPRINT")
    for match in SECRET_FIELD.finditer(text):
        value = match.group(1)
        if value and not value.startswith(("synthetic-", "example-", "{{", "<")):
            findings.append("LITERAL_SECRET_FIELD")
    return sorted(set(findings))


def fingerprint_metadata(data, approval=None):
    """An approved public identity never exempts message text or secret scans."""
    if approval is None:
        return data
    header, separator, message = data.partition(b"\n\n")
    lines = header.split(b"\n")
    identities = [line for line in lines if line.startswith((b"author ", b"committer "))]
    if (not isinstance(approval, dict) or not approval.get("reason") or len(identities) != 2
            or hashlib.sha256(b"\n".join(identities)).hexdigest() != approval.get("headers_sha256")):
        raise ContractError("ATTRIBUTION_APPROVAL_INVALID", "public attribution approval does not bind these exact identity headers")
    return b"\n".join(line for line in lines if line not in identities) + separator + message


def audit(paths, *, literals=(), metadata_literals=(), extra_revisions=(), public_attributions=None):
    root = paths.root
    public_attributions = public_attributions or {}
    top = Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if top != root.resolve():
        raise ContractError("AUDIT_WRONG_REPOSITORY", "this checkout must own its Git repository")
    issues = []
    blobs = {}
    trees = set()
    if any(not re.fullmatch(r"[a-f0-9]{40,64}", item) for item in extra_revisions):
        raise ContractError("AUDIT_REVISION_INVALID", "push revisions must be exact object IDs")
    commits = sorted(set(git(root, "rev-list", "--all", *extra_revisions).decode().splitlines()))
    for commit in commits:
        metadata = git(root, "cat-file", "commit", commit)
        # Secret/email/path checks always inspect the complete original metadata.
        codes = set(findings_for(commit, metadata, metadata=True))
        fingerprint_input = fingerprint_metadata(metadata, public_attributions.get(commit)).decode("utf-8")
        if any(term.casefold() in fingerprint_input.casefold() for term in metadata_literals if term):
            codes.add("PRIVATE_FINGERPRINT")
        for code in codes:
            issues.append({"scope": "commit", "object": commit, "code": code})
        tree = git(root, "rev-parse", commit + "^{tree}").decode().strip()
        if tree in trees:
            continue
        trees.add(tree)
        for item in git(root, "ls-tree", "-rz", tree).split(b"\0"):
            if not item:
                continue
            header, filename = item.split(b"\t", 1)
            mode, kind, oid = header.decode().split()
            path = filename.decode()
            if kind != "blob" or mode == "120000":
                issues.append({"scope": "history", "path": path, "code": "LINK_OR_SUBMODULE"})
            else:
                blobs.setdefault(oid, set()).add(path)
    for item in git(root, "for-each-ref", "--format=%(objecttype) %(objectname)", "refs/tags").decode().splitlines():
        kind, oid = item.split()
        if kind == "tag":
            for code in findings_for(oid, git(root, "cat-file", "tag", oid), metadata_literals, metadata=True):
                issues.append({"scope": "tag", "object": oid, "code": code})
    for entry in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        header, filename = entry.split(b"\t", 1)
        mode, oid, stage = header.decode().split()
        if mode in {"120000", "160000"} or stage != "0":
            issues.append({"scope": "index", "path": filename.decode(), "code": "LINK_SUBMODULE_OR_CONFLICT"})
        else:
            blobs.setdefault(oid, set()).add(filename.decode())
    for oid, filenames in blobs.items():
        data = git(root, "cat-file", "blob", oid)
        for path in filenames:
            for code in findings_for(path, data, literals):
                issues.append({"scope": "blob", "path": path, "object": oid, "code": code})
    working = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    working_hashes = {}
    for path in set(working) - {""}:
        file = root / path
        if file.is_symlink():
            issues.append({"scope": "working", "path": path, "code": "LINK_OR_SUBMODULE"})
        elif file.is_file():
            data = file.read_bytes()
            working_hashes[path] = hashlib.sha256(data).hexdigest()
            for code in findings_for(path, data, literals):
                issues.append({"scope": "working", "path": path, "code": code})
    tree = git(root, "write-tree").decode().strip()
    refs = git(root, "for-each-ref", "--format=%(refname) %(objectname)")
    return {"schema_version": 1, "ok": not issues, "index_tree": tree,
            "commit_count": len(commits), "blob_count": len(blobs), "working_file_count": len(set(working) - {""}),
            "refs_hash": hashlib.sha256(refs).hexdigest(), "findings": sorted(issues, key=lambda item: json.dumps(item, sort_keys=True)),
            "commits_hash": canonical_sha256(commits), "working_hash": canonical_sha256(working_hashes),
            "rules_hash": canonical_sha256({"literals": list(literals), "metadata_literals": list(metadata_literals), "public_attributions": public_attributions}),
            "approved_public_attribution_count": sum(commit in public_attributions for commit in commits),
            "all_publishable_files_checked": True, "raw_match_values_included": False,
            "semantic_review_required": True, "fingerprint_count": len(literals)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-rules")
    parser.add_argument("--attest-semantic-review", action="store_true")
    parser.add_argument("--require-attestation", action="store_true")
    parser.add_argument("--pre-push", action="store_true")
    args = parser.parse_args(argv)
    paths = ProjectPaths.discover()
    saved_rules = paths.runtime_path("cache/private-audit-rules.json")
    rules = json.loads(saved_rules.read_text()) if saved_rules.is_file() else {}
    if args.private_rules:
        if not args.private_rules.startswith("runtime.nosync/"):
            raise ContractError("AUDIT_INPUT_INVALID", "private fingerprints must stay in ignored local runtime")
        rules = json.loads(paths.path(args.private_rules).read_text())
        atomic_replace(saved_rules, pretty_bytes(rules))
        saved_rules.chmod(0o600)
    extra = []
    if args.pre_push:
        for line in sys.stdin:
            fields = line.split()
            if len(fields) != 4:
                raise ContractError("AUDIT_PUSH_INVALID", "unexpected push hook input")
            if set(fields[1]) != {"0"}:
                extra.append(fields[1])
    report = audit(paths, literals=rules.get("literals", []), metadata_literals=rules.get("metadata_literals", []),
                   extra_revisions=extra, public_attributions=rules.get("public_attributions", {}))
    attestation = paths.runtime_path("cache/public-audit.json")
    if args.attest_semantic_review and report["ok"]:
        atomic_replace(attestation, pretty_bytes({"tree": report["index_tree"], "report_hash": canonical_sha256(report),
                                                "semantic_review": "primary_agent_or_maintainer_attested", "fingerprint_count": report["fingerprint_count"]}))
    if args.require_attestation:
        if not attestation.is_file() or json.loads(attestation.read_text()).get("report_hash") != canonical_sha256(report):
            report["ok"] = False
            report["findings"].append({"code": "EXACT_TREE_REVIEW_REQUIRED", "scope": "publication"})
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
