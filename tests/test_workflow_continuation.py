import copy
from datetime import datetime, UTC, timedelta
import unittest

from career_kit.canonical_json import canonical_sha256
from career_kit.documents import Documents
from career_kit.errors import ContractError
from career_kit.status import status
from helpers import workspace, setup, profile, content


class ContinuationTests(unittest.TestCase):
    def ready_resume(self, paths):
        flow, job, mapping, app = setup(paths); profile(paths)
        docs = Documents(paths); template = docs.register("text-example"); docs.approve("text-example", template["revision"])
        result = docs.render(app["id"], "text-example", content(flow, app))
        approved = docs.review(result["id"], result["revision"], "approved", "Actual synthetic user decision")
        flow.requirements(app["id"], {"cover_letter": "optional", "page_evidence": "Synthetic optional slot"})
        return flow, job, mapping, app, docs, approved

    def test_timestamp_refresh_preserves_documents_and_content_change_does_not(self):
        with workspace() as paths:
            flow, job, mapping, app, docs, approved = self.ready_resume(paths)
            self.assertTrue(flow.readiness(app["id"])["ready_for_user_submission"])
            updated = copy.deepcopy(job); updated["checked_at"] = (datetime.now(UTC) - timedelta(seconds=2)).isoformat()
            mapping["job_hash"] = canonical_sha256(updated)
            refreshed = flow.application_refresh(app["id"], updated, mapping)
            self.assertFalse(refreshed["job_content_changed"])
            self.assertTrue(flow.readiness(app["id"])["ready_for_user_submission"])
            updated["description"] = "Changed synthetic responsibilities"
            mapping["job_hash"] = canonical_sha256(updated)
            self.assertTrue(flow.application_refresh(app["id"], updated, mapping)["job_content_changed"])
            self.assertFalse(flow.readiness(app["id"])["ready_for_user_submission"])
            self.assertEqual(len(flow.store.list("application")), 1)

    def test_revision_loop_and_fresh_agent_status_are_actionable(self):
        with workspace() as paths:
            flow, job, mapping, app, docs, approved = self.ready_resume(paths)
            docs.review(approved["id"], approved["revision"], "revise", "Synthetic request to revise wording")
            self.assertEqual(status(paths)["pending_document_reviews"][0]["status"], "revise")
            revised = docs.render(app["id"], "text-example", content(flow, app))
            with self.assertRaises(ContractError): docs.review(approved["id"], flow.store.get("document", approved["id"])["revision"], "approved", "Old artifact")
            docs.review(revised["id"], revised["revision"], "approved", "Revised synthetic artifact accepted")
            self.assertTrue(flow.readiness(app["id"])["ready_for_user_submission"])
            self.assertEqual(status(paths)["pending_document_reviews"], [])

    def test_review_only_letter_cannot_replace_submission_letter(self):
        with workspace() as paths:
            flow, job, mapping, app, docs, _ = self.ready_resume(paths)
            letter = docs.render(app["id"], "text-example", content(flow, app, "cover_letter"))
            source = docs.review(letter["id"], letter["revision"], "approved", "Synthetic submission letter accepted")
            companion = content(flow, app, "cover_letter")
            companion.update(purpose="review_only", translation_of={"id": source["id"], "revision": source["revision"]})
            review = docs.render(app["id"], "text-example", companion)
            current = flow.store.get("application", app["id"])["payload"]["documents"]
            self.assertEqual(current["cover_letter"]["id"], source["id"])
            self.assertEqual(current["cover_letter:review_only:en"]["id"], review["id"])
            self.assertEqual(review["purpose"], "review_only")
            ready = flow.readiness(app["id"])
            self.assertTrue(ready["ready_for_user_submission"])
            self.assertNotIn(review["id"], [ref["id"] for ref in ready["submission_documents"]])

    def test_optional_letter_if_selected_still_needs_review(self):
        with workspace() as paths:
            flow, job, mapping, app, docs, _ = self.ready_resume(paths)
            self.assertNotIn("ask_user_for_initial_company_list", status(paths)["next_actions"])
            docs.render(app["id"], "text-example", content(flow, app, "cover_letter"))
            self.assertIn("cover_letter:NOT_APPROVED_FOR_SUBMISSION", flow.readiness(app["id"])["issues"])

    def test_readiness_rechecks_quota_after_another_submission(self):
        with workspace() as paths:
            flow, job, mapping, app, docs, _ = self.ready_resume(paths)
            prefs = flow.candidate("preferences")
            draft = flow.candidate_import("preferences", {"company_blacklist": [], "quota": {"maximum": 1, "window_days": 30}}, expected=prefs["revision"])
            flow.candidate_approve("preferences", draft["revision"])
            second_job = {**job, "requisition_id": "another-example-role"}
            second_mapping = {**mapping, "job_hash": canonical_sha256(second_job)}
            second = flow.application_create(second_job, second_mapping, "Synthetic second preparation")
            flow.report_submitted(app["id"], "Synthetic actual user report")
            self.assertIn("QUOTA_REACHED", flow.readiness(second["id"])["issues"])

    def test_submitted_preparation_snapshot_cannot_be_replaced(self):
        with workspace() as paths:
            flow, job, mapping, app, docs, _ = self.ready_resume(paths)
            submitted = flow.report_submitted(app["id"], "Synthetic actual user report")
            self.assertEqual(flow.report_submitted(app["id"], "Repeated report")["revision"], submitted["revision"])
            with self.assertRaises(ContractError): flow.application_refresh(app["id"], job, mapping)
            with self.assertRaises(ContractError): docs.render(app["id"], "text-example", content(flow, app))
            with self.assertRaises(ContractError): flow.requirements(app["id"], {"cover_letter": "required", "page_evidence": "Changed"})
            self.assertTrue(flow.readiness(app["id"])["already_submitted"])

    def test_requested_followup_document_preserves_original_submission(self):
        with workspace() as paths:
            flow, job, mapping, app, docs, _ = self.ready_resume(paths)
            flow.report_submitted(app["id"], "Synthetic actual user report")
            before = flow.store.get("application", app["id"])["payload"]
            followup = content(flow, app)
            followup["purpose"] = "correspondence"
            with self.assertRaises(ContractError): docs.render(app["id"], "text-example", followup)
            followup["request_ref"] = "synthetic-user-confirmed-hr-request"
            result = docs.render(app["id"], "text-example", followup)
            self.assertEqual(result["container"], "correspondence_documents")
            self.assertEqual(status(paths)["pending_document_reviews"][0]["slot"], "correspondence:resume")
            docs.review(result["id"], result["revision"], "approved", "Synthetic user accepted follow-up PDF")
            after = flow.store.get("application", app["id"])["payload"]
            self.assertEqual(after["documents"], before["documents"])
            self.assertEqual(after["submitted_at"], before["submitted_at"])
            self.assertEqual(after["job"], before["job"])
            self.assertEqual(len(flow.store.list("application")), 1)

    def test_requested_followup_letter_and_review_copy_use_separate_slots(self):
        with workspace() as paths:
            flow, job, mapping, app, docs, _ = self.ready_resume(paths)
            flow.requirements(app["id"], {"cover_letter": "not_supported", "page_evidence": "Synthetic original resume-only form"})
            flow.report_submitted(app["id"], "Synthetic actual user report")
            letter = content(flow, app, "cover_letter")
            letter.update(purpose="correspondence", request_ref="synthetic-new-hr-letter-request")
            result = docs.render(app["id"], "text-example", letter)
            reviewed = docs.review(result["id"], result["revision"], "approved", "Synthetic follow-up approved")
            companion = content(flow, app, "cover_letter")
            companion.update(purpose="review_only", translation_of={"id": reviewed["id"], "revision": reviewed["revision"]})
            copy = docs.render(app["id"], "text-example", companion)
            docs.review(copy["id"], copy["revision"], "approved", "Synthetic review translation accepted")
            saved = flow.store.get("application", app["id"])["payload"]
            self.assertNotIn("cover_letter", saved["documents"])
            self.assertEqual(saved["correspondence_documents"]["cover_letter"]["id"], result["id"])

    def test_missing_letters_stale_facts_and_modified_files_are_not_ready(self):
        with workspace() as paths:
            flow, job, mapping, app, docs, approved = self.ready_resume(paths)
            flow.requirements(app["id"], {"cover_letter": "required", "page_evidence": "Synthetic required slot"})
            self.assertIn("cover_letter:MISSING", flow.readiness(app["id"])["issues"])
            artifact = flow.store.get("document", approved["id"])["payload"]["artifact"]
            paths.permanent(artifact).write_text("Synthetic tampering")
            self.assertIn("resume:ARTIFACT_CHANGED", flow.readiness(app["id"])["issues"])
            facts = flow.candidate("facts")
            changed = flow.candidate_import("facts", facts["payload"], expected=facts["revision"])
            flow.candidate_approve("facts", changed["revision"])
            self.assertIn("MATCH_STALE", flow.readiness(app["id"])["issues"])
