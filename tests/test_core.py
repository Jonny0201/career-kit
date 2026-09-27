import copy
import json
from pathlib import Path
import unittest

from career_kit.cli import initialize, doctor
from career_kit.documents import Documents
from career_kit.errors import ContractError
from career_kit.paths import ProjectPaths, discover_project_root
from career_kit.store import Store
from career_kit.canonical_json import canonical_sha256
from helpers import workspace, setup, profile, content


class CoreTests(unittest.TestCase):
    def test_empty_checkout_needs_no_private_backend_or_data(self):
        with workspace() as paths:
            result = doctor(paths)
            self.assertTrue(result["ok"])
            self.assertEqual(result["document_setup"], "not_configured")
            self.assertFalse(paths.permanent("data").exists())
            first = initialize(paths)
            self.assertEqual(len(first["created_blank_inputs"]), 5)
            self.assertEqual(initialize(paths)["created_blank_inputs"], [])
            self.assertFalse(paths.permanent("data").exists())

    def test_nested_repository_never_falls_back_to_parent(self):
        with workspace() as paths:
            nested = paths.root / "child"; nested.mkdir(); (nested / ".git").mkdir()
            with self.assertRaises(ContractError): discover_project_root(nested)
            (nested / ".career-kit.json").write_text('{"project":"career-kit","format_version":1}')
            self.assertEqual(discover_project_root(nested), nested)
            for name in ("../outside", "/absolute", "data/../../outside"):
                with self.assertRaises(ContractError): ProjectPaths(nested).path(name)
            (nested / "escape").symlink_to(paths.root, target_is_directory=True)
            with self.assertRaises(ContractError): ProjectPaths(nested).path("escape/local")

    def test_revision_conflicts_and_tampering_are_detected(self):
        with workspace() as paths:
            store = Store(paths)
            result = store.put("preferences", "preferences", {}, reason="Synthetic")
            with self.assertRaises(ContractError): store.put("preferences", "preferences", {}, reason="Synthetic")
            file = paths.permanent(f"data/records/preferences/preferences/{result['revision']}.json")
            file.write_text("{}")
            with self.assertRaises(ContractError): store.verify()

    def test_crash_orphan_never_becomes_current_data(self):
        with workspace() as paths:
            store = Store(paths)
            def crash(stage): raise OSError("synthetic crash")
            with self.assertRaises(OSError): store.put("preferences", "preferences", {}, reason="Synthetic", failpoint=crash)
            with self.assertRaises(ContractError): store.get("preferences", "preferences")
            self.assertFalse(store.verify()["ok"])
            self.assertFalse(paths.runtime_path("locks/writer.lock").exists())

    def test_matching_requires_bound_confirmed_facts_and_real_role_coverage(self):
        with workspace() as paths:
            flow, job, mapping, app = setup(paths)
            self.assertEqual(flow.evaluate(job, mapping)["decision"], "apply")
            changed = copy.deepcopy(mapping); changed["facts_revision"] = "0" * 64
            with self.assertRaises(ContractError): flow.evaluate(job, changed)
            changed = copy.deepcopy(mapping); changed["requirements"][0].update(coverage="unsupported", fact_refs=[])
            self.assertEqual(flow.evaluate(job, changed)["decision"], "skip")
            self.assertFalse(flow.evaluate(job, changed)["document_generation_allowed"])
            self.assertEqual(flow.application_create(job, mapping, "repeat")["id"], app["id"])
            self.assertEqual(len(flow.store.list("application")), 1)
            bundle = json.dumps(flow.bundle("resume"))
            self.assertNotIn("synthetic-email-token", bundle)
            self.assertNotIn("Synthetic Applicant", bundle)

    def test_hard_unknown_does_not_generate_documents(self):
        with workspace() as paths:
            flow, job, mapping, app = setup(paths)
            job["requirements"][0]["hard"] = True
            mapping["job_hash"] = canonical_sha256(job)
            mapping["requirements"][0].update(coverage="unknown", fact_refs=[])
            self.assertFalse(flow.evaluate(job, mapping)["document_generation_allowed"])

    def test_text_backend_render_review_and_submission_flow(self):
        with workspace() as paths:
            flow, job, mapping, app = setup(paths); profile(paths)
            docs = Documents(paths)
            proposed = docs.register("text-example")
            with self.assertRaises(ContractError): docs.render(app["id"], "text-example", content(flow, app))
            docs.approve("text-example", proposed["revision"])
            result = docs.render(app["id"], "text-example", content(flow, app))
            self.assertEqual(result["review"], "pending")
            self.assertEqual(list(paths.runtime_path("work").iterdir()), [])
            docs.review(result["id"], result["revision"], "approved", "User reviewed the synthetic final file")
            flow.requirements(app["id"], {"cover_letter": "not_supported", "page_evidence": "Synthetic one-file form"})
            submitted = flow.report_submitted(app["id"], "User reports actual test submission")
            self.assertEqual(flow.report_submitted(app["id"], "same")["revision"], submitted["revision"])
            self.assertEqual(flow.store.get("application", app["id"])["payload"]["submission_warnings"], [])
            self.assertTrue(flow.store.verify()["ok"])

    def test_independent_pdf_backend_does_not_require_a_native_design_format(self):
        with workspace() as paths:
            flow, job, mapping, app = setup(paths); profile(paths, "pdf-example", "pdf")
            docs = Documents(paths); p = docs.register("pdf-example"); docs.approve("pdf-example", p["revision"])
            result = docs.render(app["id"], "pdf-example", content(flow, app))
            self.assertTrue(result["artifact"].endswith(".pdf"))
            self.assertEqual(flow.store.get("document", result["id"])["payload"]["page_count"], 1)

    def test_changed_renderer_or_unsupported_claims_are_rejected(self):
        with workspace() as paths:
            flow, job, mapping, app = setup(paths); directory = profile(paths)
            docs = Documents(paths); p = docs.register("text-example"); docs.approve("text-example", p["revision"])
            bad = content(flow, app); bad["claims"][0]["fact_refs"] = ["unconfirmed"]
            with self.assertRaises(ContractError): docs.render(app["id"], "text-example", bad)
            (directory / "render.py").write_text("raise RuntimeError('changed')")
            with self.assertRaises(ContractError): docs.check("text-example")

    def test_renderer_extra_text_fails_and_temporary_output_is_cleaned(self):
        with workspace() as paths:
            flow, job, mapping, app = setup(paths); profile(paths, extra="Undeclared experience")
            docs = Documents(paths); p = docs.register("text-example"); docs.approve("text-example", p["revision"])
            with self.assertRaises(ContractError): docs.render(app["id"], "text-example", content(flow, app))
            self.assertEqual(list(paths.runtime_path("work").iterdir()), [])
            self.assertEqual(flow.store.list("document"), [])

    def test_letter_follows_page_requirements_and_never_the_jd_alone(self):
        with workspace() as paths:
            flow, job, mapping, app = setup(paths); profile(paths)
            docs = Documents(paths); p = docs.register("text-example"); docs.approve("text-example", p["revision"])
            with self.assertRaises(ContractError): docs.render(app["id"], "text-example", content(flow, app, "cover_letter"))
            flow.requirements(app["id"], {"cover_letter": "optional", "page_evidence": "Synthetic optional covering-letter text box"})
            letter = content(flow, app, "cover_letter")
            letter["claims"].append({"kind": "closing", "text": "Thank you for considering this synthetic example."})
            self.assertEqual(docs.render(app["id"], "text-example", letter)["review"], "pending")

    def test_actual_submission_is_recorded_with_missing_preparation_warnings(self):
        with workspace() as paths:
            flow, job, mapping, app = setup(paths)
            flow.report_submitted(app["id"], "User explicitly reports an actual event")
            stored = flow.store.get("application", app["id"])["payload"]
            self.assertEqual(stored["status"], "submitted")
            self.assertIn("resume_not_recorded", stored["submission_warnings"])
