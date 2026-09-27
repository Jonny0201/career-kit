"""A synthetic CLI journey; no network, real user files or browser submission."""
import contextlib
import io
import json
from unittest.mock import patch
import unittest

from career_kit.cli import main
from career_kit.store import utc_now
from helpers import workspace, profile


class OnboardingJourneyTests(unittest.TestCase):
    def test_blank_workspace_to_user_submission_mail_and_outcome(self):
        with workspace() as paths:
            def run(*args):
                output = io.StringIO()
                with patch("career_kit.cli.ProjectPaths.discover", return_value=paths), contextlib.redirect_stdout(output):
                    code = main(list(args))
                result = json.loads(output.getvalue())
                self.assertEqual(code, 0, result)
                return result["result"]

            def input_file(name, value):
                relative = "local/inputs/" + name + ".json"
                paths.permanent(relative).write_text(json.dumps(value))
                return relative

            run("init")
            self.assertEqual(run("status")["company_counts"]["approved"], 0)
            sections = {
                "profile": {"display_name": "Synthetic Person", "email": "person@example.invalid"},
                "history": {"projects": [{"id": "example-project", "narrative": "A fictional system.", "interview": [{"id": "ownership", "status": "confirmed", "answer": "Synthetic ownership."}]}]},
                "facts": {"facts": [{"id": "example-fact", "text": "Built a synthetic event processor.", "language": "en", "category": "technical", "model_visible": True, "source_ref": "example-project/ownership", "allowed_outputs": ["match", "resume", "cover_letter"]}]},
                "preferences": {"roles": ["Fictional role"], "company_blacklist": [], "company_search": {"initial_list_status": "provided", "allow_discovery": False}},
            }
            for section, value in sections.items():
                draft = run("candidate", "import", section, "--file", input_file(section, value))
                run("candidate", "approve", section, "--revision", draft["revision"])
            seeds = run("company", "seeds-import", "--file", input_file("company-seeds", {"source": "Synthetic user list", "companies": ["Example Journey"]}))
            seed = run("company", "seeds-show", seeds["id"])["rows"][0]
            proposals = {"source": "Synthetic official research", "origin": "seed_list", "seed_batch": {"id": seeds["id"], "revision": seeds["revision"]},
                         "companies": [{"name": "Example Journey", "official_url": "https://journey.invalid", "evidence": "Synthetic official evidence", "seed_refs": [seed["seed_id"]]}]}
            proposed = run("company", "propose-batch", "--file", input_file("company-batch", proposals))
            run("export-local", "company_batch", proposed["id"], "--output", "local/review/company-batch.json")
            run("company", "review-batch", proposed["id"], "--revision", proposed["revision"], "--decision", "approved")
            company = run("company", "list")["companies"][0]
            facts = run("candidate", "bundle", "match")
            job = {"company_id": company["id"], "requisition_id": "example-role", "title": "Fictional role", "description": "Build synthetic event processors.",
                   "source_url": "https://journey.invalid/role", "checked_at": utc_now(), "active": True,
                   "requirements": [{"id": "events", "role_defining": True, "hard": False}]}
            job_path = input_file("job", job)
            mapping = {"job_hash": run("hash-input", "--file", job_path)["sha256"], "facts_revision": facts["facts_revision"], "decision": "apply", "rationale": "Synthetic request and evidence match",
                       "requirements": [{"id": "events", "coverage": "direct", "fact_refs": ["example-fact"], "reason": "Synthetic evidence"}]}
            mapping_path = input_file("mapping", mapping)
            self.assertEqual(run("job", "evaluate", "--job", job_path, "--mapping", mapping_path)["decision"], "apply")
            app = run("application", "create", "--job", job_path, "--mapping", mapping_path, "--reason", "Synthetic user-directed search")
            profile(paths, "pdf-example", "pdf")
            template = run("documents", "register", "pdf-example")
            run("documents", "approve-profile", "pdf-example", "--revision", template["revision"])
            document_input = {"application_id": app["id"], "facts_revision": facts["facts_revision"], "document_type": "resume", "language": "en",
                              "claims": [{"text": "Built a synthetic event processor.", "fact_refs": ["example-fact"]}]}
            artifact = run("documents", "render", app["id"], "--profile", "pdf-example", "--content", input_file("content", document_input))
            run("documents", "review", artifact["id"], "--revision", artifact["revision"], "--decision", "approved", "--feedback", "Synthetic user reviewed exact PDF")
            run("application", "requirements", app["id"], "--file", input_file("requirements", {"cover_letter": "not_supported", "page_evidence": "Synthetic resume-only form"}))
            self.assertTrue(run("application", "readiness", app["id"])["ready_for_user_submission"])
            submitted = run("application", "report-submitted", app["id"], "--reason", "Synthetic user reports actual submission")
            self.assertEqual(run("application", "report-submitted", app["id"], "--reason", "Duplicate report")["revision"], submitted["revision"])
            directory = paths.permanent("credentials"); directory.mkdir(mode=0o700)
            config = directory / "mail.json"
            config.write_text(json.dumps({"auth_kind": "app_password", "username": "person@example.invalid", "password": "synthetic-app-secret",
                                          "imap": {"host": "imap.example.invalid", "port": 993}, "smtp": {"host": "smtp.example.invalid", "port": 465, "tls": "ssl"}})); config.chmod(0o600)
            draft = run("mail", "draft", "--file", input_file("reply", {"to": ["hr@example.invalid"], "subject": "Synthetic follow-up", "body": "Synthetic confirmation.",
                        "attachments": [{"path": artifact["artifact"], "sha256": artifact["artifact_sha256"]}]}))
            authorization = run("mail", "authorize", draft["id"], "--revision", draft["revision"])
            sent = []
            class SMTP:
                def login(self, *args): pass
                def send_message(self, message): sent.append(message); return {}
                def quit(self): pass
            class IMAP:
                def login(self, *args): pass
                def select(self, *args, **kwargs): return "OK", []
                def uid(self, command, *args):
                    return ("OK", [b"1"]) if command == "search" else ("OK", [(b"header", sent[0].as_bytes())])
                def logout(self): pass
            with patch("career_kit.mail.smtplib.SMTP_SSL", return_value=SMTP()), patch("career_kit.mail.imaplib.IMAP4_SSL", return_value=IMAP()):
                run("mail", "send", authorization["id"])
                self.assertEqual(len(run("mail", "sync")["messages"]), 1)
            self.assertEqual(len(sent), 1)
            run("outcome", app["id"], "--file", input_file("outcome", {"kind": "interview", "source": "Synthetic user report", "text": "Synthetic invitation received."}))
            self.assertEqual(run("status")["applications"][0]["status"], "submitted")
            self.assertTrue(run("verify")["ok"])
            self.assertEqual(list(paths.runtime_path("work").iterdir()), [])
