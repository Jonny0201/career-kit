import copy
import json
import unittest

from career_kit.cli import initialize
from career_kit.companies import CompanyIntake, read_seeds
from career_kit.errors import ContractError
from career_kit.status import status
from career_kit.workflows import Workflows
from helpers import workspace


def preferences(paths, **extra):
    flow = Workflows(paths)
    value = {"company_blacklist": [], "company_search": {"initial_list_status": "provided", "allow_discovery": False}, **extra}
    ref = flow.candidate_import("preferences", value)
    flow.candidate_approve("preferences", ref["revision"])
    return flow


def batch(intake, names=("Example Alpha", "Example Beta")):
    seeds = intake.import_seeds({"source": "Synthetic user list", "companies": list(names)})
    rows = intake.show_seeds(seeds["id"])["rows"]
    return {"source": "Synthetic official research", "origin": "seed_list", "seed_batch": {"id": seeds["id"], "revision": seeds["revision"]},
            "companies": [{"name": name, "official_url": f"https://employer-{i}.invalid", "evidence": "Synthetic official evidence", "seed_refs": [rows[i]["seed_id"]]} for i, name in enumerate(names)]}


class CompanyOnboardingTests(unittest.TestCase):
    def test_blank_initialization_never_supplies_someone_elses_list(self):
        with workspace() as paths:
            initialize(paths)
            seed_file = paths.permanent("local/inputs/company-seeds.json")
            self.assertEqual(json.loads(seed_file.read_text()), {"source": "", "companies": []})
            result = status(paths)
            self.assertIn("ask_user_for_initial_company_list", result["next_actions"])
            self.assertEqual(result["company_counts"]["approved"], 0)
            self.assertFalse(paths.permanent("data").exists())

    def test_csv_text_json_and_duplicate_rows_are_private_unverified_leads(self):
        with workspace() as paths:
            initialize(paths); intake = CompanyIntake(paths)
            file = paths.permanent("local/inputs/companies.csv")
            file.write_text('name,url,notes,channel\nExample Alpha,https://alpha.invalid,first note,direct\n example   alpha ,https://alpha.invalid/careers,second note,recruiter\nExample Beta,https://alpha.invalid,shared URL is not shared identity,unknown\n')
            source = read_seeds(paths, "local/inputs/companies.csv")
            ref = intake.import_seeds(source); result = intake.show_seeds(ref["id"])
            self.assertEqual(len(result["rows"]), 2)
            self.assertEqual(result["duplicate_row_count"], 1)
            self.assertFalse(result["approved"]); self.assertFalse(result["notes_included"])
            self.assertEqual(result["rows"][0]["source_rows"], [1, 2])
            self.assertEqual(intake.import_seeds(source)["revision"], ref["revision"])
            self.assertEqual(intake.store.list("company"), [])
            paths.permanent("local/inputs/companies.txt").write_text("Example Gamma\nhttps://delta.invalid\n")
            self.assertEqual(len(read_seeds(paths, "local/inputs/companies.txt")["companies"]), 2)
            with self.assertRaises(ContractError): read_seeds(paths, "credentials/list.json")

    def test_batch_excludes_user_blacklist_and_requires_exact_review(self):
        with workspace() as paths:
            preferences(paths, company_blacklist=["Example Alpha"])
            intake = CompanyIntake(paths); source = batch(intake)
            # Renaming a blacklisted seed during research does not evade exclusion.
            source["companies"][0]["name"] = "Canonical Example Alpha"
            proposed = intake.propose_batch(source)
            value = intake.store.get("company_batch", proposed["id"])["payload"]
            self.assertEqual([r["status"] for r in value["items"]], ["excluded", "proposed"])
            self.assertEqual(len(intake.store.list("company")), 1)
            with self.assertRaises(ContractError): intake.review_batch(proposed["id"], "0" * 64, "approved")
            accepted = intake.review_batch(proposed["id"], proposed["revision"], "approved")
            self.assertEqual(intake.store.list("company")[0]["payload"]["status"], "approved")
            self.assertEqual(intake.review_batch(proposed["id"], proposed["revision"], "approved")["revision"], accepted["revision"])

    def test_no_list_discovery_is_explicit_and_not_a_contributor_default(self):
        with workspace() as paths:
            flow = preferences(paths, company_search={"initial_list_status": "none", "allow_discovery": False})
            intake = CompanyIntake(paths)
            source = {"source": "Synthetic discovery", "origin": "discovery", "companies": [{"name": "Example Delta", "official_url": "https://delta.invalid", "evidence": "Synthetic evidence"}]}
            with self.assertRaises(ContractError): intake.propose_batch(source)
            self.assertIn("company_setup_deferred_by_user", status(paths)["next_actions"])
            old = flow.candidate("preferences")
            ref = flow.candidate_import("preferences", {"company_search": {"initial_list_status": "none", "allow_discovery": True}}, expected=old["revision"])
            flow.candidate_approve("preferences", ref["revision"])
            self.assertIn("discover_companies_from_confirmed_preferences", status(paths)["next_actions"])
            self.assertEqual(intake.propose_batch(source)["kind"], "company_batch")

    def test_whole_batch_validation_precedes_mutation(self):
        with workspace() as paths:
            preferences(paths); intake = CompanyIntake(paths); source = batch(intake)
            source["companies"][1]["official_url"] = "file:///not-a-source"
            with self.assertRaises(ContractError): intake.propose_batch(source)
            self.assertEqual(intake.store.list("company"), [])

    def test_shared_urls_do_not_silently_merge_distinct_companies(self):
        with workspace() as paths:
            flow = preferences(paths); intake = CompanyIntake(paths); source = batch(intake)
            source["companies"][1]["official_url"] = source["companies"][0]["official_url"]
            with self.assertRaises(ContractError): intake.propose_batch(source)
            self.assertEqual(intake.store.list("company"), [])
            first = flow.company_propose(source["companies"][0])
            with self.assertRaises(ContractError): flow.company_propose(source["companies"][1])
            enriched = flow.company_enrich(first["id"], first["revision"], {"aliases": ["Example Beta"], "evidence": "Synthetic official alias evidence"})
            self.assertEqual(flow.company_propose(source["companies"][1])["id"], enriched["id"])

    def test_batch_review_resumes_after_partial_local_completion(self):
        with workspace() as paths:
            preferences(paths); intake = CompanyIntake(paths); proposed = intake.propose_batch(batch(intake))
            def crash(_): raise OSError("Synthetic interruption after first committed decision")
            with self.assertRaises(OSError): intake.review_batch(proposed["id"], proposed["revision"], "approved", failpoint=crash)
            self.assertEqual(sum(r["payload"]["status"] == "approved" for r in intake.store.list("company")), 1)
            self.assertEqual(status(paths)["company_batches"][0]["status"], "reviewing")
            intake.review_batch(proposed["id"], proposed["revision"], "approved")
            self.assertEqual(sum(r["payload"]["status"] == "approved" for r in intake.store.list("company")), 2)
            self.assertTrue(intake.store.verify()["ok"])

    def test_reuse_does_not_reopen_rejected_companies_or_duplicate_identity(self):
        with workspace() as paths:
            flow = preferences(paths); intake = CompanyIntake(paths); source = batch(intake)
            ref = flow.company_propose(source["companies"][0])
            flow.company_review(ref["id"], ref["revision"], "rejected")
            source["companies"][0]["official_url"] = "https://EMPLOYER-0.invalid/"
            proposed = intake.propose_batch(source)
            intake.review_batch(proposed["id"], proposed["revision"], "approved")
            self.assertEqual(flow.store.get("company", ref["id"])["payload"]["status"], "rejected")
            self.assertEqual(len(flow.store.list("company")), 2)

    def test_changed_preferences_require_reassessing_a_batch(self):
        with workspace() as paths:
            flow = preferences(paths); intake = CompanyIntake(paths); proposed = intake.propose_batch(batch(intake))
            old = flow.candidate("preferences")
            draft = flow.candidate_import("preferences", {"company_blacklist": ["Example Beta"]}, expected=old["revision"])
            flow.candidate_approve("preferences", draft["revision"])
            with self.assertRaises(ContractError): intake.review_batch(proposed["id"], proposed["revision"], "approved")

    def test_existing_identity_conflict_is_detected_before_any_new_record(self):
        with workspace() as paths:
            flow = preferences(paths); intake = CompanyIntake(paths)
            flow.company_propose({"name": "Different Example Identity", "official_url": "https://employer-1.invalid", "evidence": "Synthetic evidence"})
            with self.assertRaises(ContractError): intake.propose_batch(batch(intake))
            self.assertEqual(len(intake.store.list("company")), 1)

    def test_existing_single_proposal_has_a_continuation_without_new_list(self):
        with workspace() as paths:
            flow = preferences(paths, company_search={})
            proposed = flow.company_propose({"name": "Example Single", "official_url": "https://single.invalid", "evidence": "Synthetic official evidence"})
            result = status(paths)
            self.assertEqual(result["pending_company_reviews"][0]["id"], proposed["id"])
            self.assertIn("review_existing_company_proposals", result["next_actions"])
            self.assertNotIn("ask_user_for_initial_company_list", result["next_actions"])
