"""Small deterministic commands for a conversational semantic orchestrator."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

from .atomic import atomic_publish_noreplace
from .canonical_json import pretty_bytes
from .documents import Documents
from .errors import ContractError
from .paths import ProjectPaths
from .store import Store
from .workflows import Workflows, require


def read_input(paths, relative):
    require(relative.startswith(("local/inputs/", "data/drafts/", "runtime.nosync/work/")),
            "INPUT_FORBIDDEN", "inputs belong in local/inputs, data/drafts or runtime work, never credentials")
    file = paths.path(relative)
    require(file.is_file() and file.stat().st_size <= 5_000_000, "INPUT_INVALID", "input is missing or too large")
    value = json.loads(file.read_text())
    require(isinstance(value, dict), "INPUT_INVALID", "input must be a JSON object")
    return value


def doctor(paths):
    integrity = Store(paths).verify()
    profiles = [{"id": p["id"], "status": p["payload"].get("status")} for p in Store(paths).list("document_profile")]
    return {"ok": integrity["ok"] and sys.version_info >= (3, 11) and importlib.util.find_spec("pypdf") is not None, "python_supported": sys.version_info >= (3, 11),
            "integrity": integrity, "document_profiles": profiles,
            "document_setup": "configured" if any(p["status"] == "approved" for p in profiles) else "not_configured",
            "pdf_reader_installed": importlib.util.find_spec("pypdf") is not None,
            "external_effects_attempted": False, "ancestor_configuration_used": False}


def initialize(paths):
    paths.initialize_runtime()
    templates = {
        "profile": {"display_name": None, "email": None, "phone": None, "location": None, "links": None},
        "facts": {"facts": []},
        "history": {"employment": [], "education": [], "projects": [], "publications": []},
        "preferences": {"roles": [], "seniority": [], "locations": [], "work_modes": [],
                        "company_blacklist": [], "compensation": None, "working_conditions": [],
                        "document_preferences": {}, "quota": None},
    }
    created = []
    for name, value in templates.items():
        path = paths.permanent(f"local/inputs/{name}.json")
        if not path.exists():
            atomic_publish_noreplace(path, pretty_bytes(value))
            created.append(path.relative_to(paths.root).as_posix())
    return {"created_blank_inputs": created, "existing_data_overwritten": False,
            "next_action": "complete private inputs with the user; read document/getting-started.md"}


def parser():
    root = argparse.ArgumentParser(prog="careerkit")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor"); commands.add_parser("init"); commands.add_parser("verify")
    candidate = commands.add_parser("candidate").add_subparsers(dest="action", required=True)
    imp = candidate.add_parser("import"); imp.add_argument("section", choices=("profile", "facts", "history", "preferences")); imp.add_argument("--file", required=True); imp.add_argument("--expected")
    approve = candidate.add_parser("approve"); approve.add_argument("section"); approve.add_argument("--revision", required=True)
    bundle = candidate.add_parser("bundle"); bundle.add_argument("purpose", choices=("resume", "cover_letter", "match", "interview"))
    company = commands.add_parser("company").add_subparsers(dest="action", required=True)
    proposal = company.add_parser("propose"); proposal.add_argument("--file", required=True)
    review = company.add_parser("review"); review.add_argument("id"); review.add_argument("--revision", required=True); review.add_argument("--decision", required=True, choices=("approved", "rejected", "watchlist"))
    company.add_parser("list")
    enrich = company.add_parser("enrich"); enrich.add_argument("id"); enrich.add_argument("--revision", required=True); enrich.add_argument("--file", required=True)
    job = commands.add_parser("job").add_subparsers(dest="action", required=True)
    evaluate = job.add_parser("evaluate"); evaluate.add_argument("--job", required=True); evaluate.add_argument("--mapping", required=True)
    ats = commands.add_parser("ats-parse"); ats.add_argument("adapter", choices=("greenhouse", "lever", "ashby", "smartrecruiters", "workday", "generic")); ats.add_argument("--file", required=True); ats.add_argument("--source-url", required=True)
    application = commands.add_parser("application").add_subparsers(dest="action", required=True)
    create = application.add_parser("create"); create.add_argument("--job", required=True); create.add_argument("--mapping", required=True); create.add_argument("--reason", required=True)
    show = application.add_parser("show"); show.add_argument("id")
    requirements = application.add_parser("requirements"); requirements.add_argument("id"); requirements.add_argument("--file", required=True)
    submit = application.add_parser("report-submitted"); submit.add_argument("id"); submit.add_argument("--reason", required=True)
    docs = commands.add_parser("documents").add_subparsers(dest="action", required=True)
    for name in ("register", "check"):
        command = docs.add_parser(name); command.add_argument("profile")
    approve = docs.add_parser("approve-profile"); approve.add_argument("profile"); approve.add_argument("--revision", required=True)
    render = docs.add_parser("render"); render.add_argument("application"); render.add_argument("--profile", required=True); render.add_argument("--content", required=True)
    review = docs.add_parser("review"); review.add_argument("id"); review.add_argument("--revision", required=True); review.add_argument("--decision", required=True, choices=("approved", "revise", "rejected", "skipped")); review.add_argument("--feedback", required=True)
    attach = docs.add_parser("attach"); attach.add_argument("application"); attach.add_argument("document")
    mail = commands.add_parser("mail").add_subparsers(dest="action", required=True)
    mail.add_parser("status")
    sync = mail.add_parser("sync"); sync.add_argument("--limit", type=int, default=10)
    draft = mail.add_parser("draft"); draft.add_argument("--file", required=True)
    auth = mail.add_parser("authorize"); auth.add_argument("id"); auth.add_argument("--revision", required=True)
    send = mail.add_parser("send"); send.add_argument("authorization")
    reconcile = mail.add_parser("reconcile"); reconcile.add_argument("id"); reconcile.add_argument("--outcome", required=True, choices=("confirmed", "not_sent", "unknown")); reconcile.add_argument("--evidence", required=True)
    account = commands.add_parser("account").add_subparsers(dest="action", required=True)
    prepare = account.add_parser("prepare"); prepare.add_argument("id"); prepare.add_argument("--registration-url", required=True); prepare.add_argument("--passwordless", action="store_true")
    report = account.add_parser("report"); report.add_argument("id"); report.add_argument("--status", required=True, choices=("registered", "awaiting_verification", "cancelled"))
    outcome = commands.add_parser("outcome"); outcome.add_argument("application"); outcome.add_argument("--file", required=True)
    export = commands.add_parser("export-local"); export.add_argument("kind"); export.add_argument("id"); export.add_argument("--output", required=True)
    return root


def execute(paths, args):
    flow = Workflows(paths)
    if args.command == "doctor":
        return doctor(paths)
    if args.command == "init":
        return initialize(paths)
    if args.command == "verify":
        return flow.store.verify()
    if args.command == "candidate":
        if args.action == "import":
            return flow.candidate_import(args.section, read_input(paths, args.file), expected=args.expected)
        if args.action == "approve":
            return flow.candidate_approve(args.section, args.revision)
        return flow.bundle(args.purpose)
    if args.command == "company":
        if args.action == "propose":
            return flow.company_propose(read_input(paths, args.file))
        if args.action == "review":
            return flow.company_review(args.id, args.revision, args.decision)
        if args.action == "enrich":
            return flow.company_enrich(args.id, args.revision, read_input(paths, args.file))
        return {"companies": [{"id": r["id"], "revision": r["revision"], "name": r["payload"]["name"], "status": r["payload"]["status"]} for r in flow.store.list("company")]}
    if args.command == "job":
        return flow.evaluate(read_input(paths, args.job), read_input(paths, args.mapping))
    if args.command == "ats-parse":
        from .ats import ATSParser
        require(args.file.startswith("runtime.nosync/work/"), "INPUT_FORBIDDEN", "official page payloads are temporary runtime inputs")
        source = paths.path(args.file)
        require(source.is_file() and source.stat().st_size <= 20_000_000, "INPUT_INVALID", "payload is missing or too large")
        jobs, warnings, complete = ATSParser().parse(args.adapter, source.read_bytes(), args.source_url)
        return {"jobs": jobs, "warnings": warnings, "complete": complete, "source_verified_by_parser": False}
    if args.command == "application":
        if args.action == "create":
            return flow.application_create(read_input(paths, args.job), read_input(paths, args.mapping), args.reason)
        if args.action == "requirements":
            return flow.requirements(args.id, read_input(paths, args.file))
        if args.action == "report-submitted":
            return flow.report_submitted(args.id, args.reason)
        record = flow.store.get("application", args.id)
        return {"id": args.id, "revision": record["revision"], **{k: record["payload"][k] for k in ("status", "documents", "submitted_at")}, "requirements_known": record["payload"]["requirements"] is not None}
    if args.command == "documents":
        documents = Documents(paths)
        if args.action == "register": return documents.register(args.profile)
        if args.action == "check": return documents.check(args.profile)
        if args.action == "approve-profile": return documents.approve(args.profile, args.revision)
        if args.action == "render": return documents.render(args.application, args.profile, read_input(paths, args.content))
        if args.action == "review": return documents.review(args.id, args.revision, args.decision, args.feedback)
        if args.action == "attach": return documents.attach(args.application, args.document)
    if args.command == "mail":
        from .mail import Mail
        mail = Mail(paths)
        if args.action == "status":
            mail.config()
            return {"configured": True, "connectivity": "not_checked", "secret_values_included": False}
        if args.action == "sync": return mail.sync(args.limit)
        if args.action == "draft": return mail.draft(read_input(paths, args.file))
        if args.action == "authorize": return mail.authorize(args.id, args.revision)
        if args.action == "send": return mail.send(args.authorization)
        if args.action == "reconcile": return mail.reconcile(args.id, args.outcome, args.evidence)
    if args.command == "account":
        from .accounts import prepare, report
        if args.action == "prepare": return prepare(paths, args.id, args.registration_url, passwordless=args.passwordless)
        return report(paths, args.id, args.status)
    if args.command == "outcome":
        return flow.outcome(args.application, read_input(paths, args.file))
    if args.command == "export-local":
        require(args.output.startswith("local/review/"), "OUTPUT_FORBIDDEN", "private review exports belong in local/review")
        record = flow.store.get(args.kind, args.id)
        atomic_publish_noreplace(paths.permanent(args.output), pretty_bytes(record))
        return {"path": args.output, "revision": record["revision"], "private_values_on_stdout": False}
    raise ContractError("COMMAND_INVALID", "unsupported command")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        value = execute(ProjectPaths.discover(), args)
        print(json.dumps({"ok": value.get("ok", True), "command": args.command, "result": value}, ensure_ascii=False))
        return 0 if value.get("ok", True) else 1
    except ContractError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False))
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"ok": False, "error": {"code": "INPUT_OR_IO_INVALID", "message": "inspect the local input or service configuration; private values are not echoed"}}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
