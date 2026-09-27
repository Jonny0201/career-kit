import json
import hashlib
import subprocess
import unittest

from career_kit.public_audit import audit, findings_for, fingerprint_metadata
from career_kit.errors import ContractError
from helpers import workspace


class PrivacyTests(unittest.TestCase):
    def test_commit_message_numbers_and_private_filenames_remain_checked(self):
        timestamp = "1" * 10
        header = ("author Example <person@example.invalid> " + timestamp + " +0000\n\nClean message").encode()
        self.assertNotIn("PHONE_OR_IDENTIFIER", findings_for("metadata", header, metadata=True))
        number = "2" * 11
        self.assertIn("PHONE_OR_IDENTIFIER", findings_for("metadata", header + ("\nCall " + number).encode(), metadata=True))
        self.assertIn("PRIVATE_FINGERPRINT", findings_for("synthetic-private-canary.txt", b"clean", ["synthetic-private-canary"]))

    def test_public_identity_approval_is_exact_and_never_exempts_content(self):
        with workspace() as paths:
            git = self.repo(paths)
            file = paths.root / "README.md"; file.write_text("Synthetic clean source")
            git("add", "README.md"); git("commit", "-qm", "test(privacy): clean source")
            oid = git("rev-parse", "HEAD").decode().strip()
            raw = git("cat-file", "commit", oid)
            headers = [line for line in raw.partition(b"\n\n")[0].split(b"\n") if line.startswith((b"author ", b"committer "))]
            approval = {"headers_sha256": hashlib.sha256(b"\n".join(headers)).hexdigest(), "reason": "Synthetic user confirmation of public identity"}
            self.assertFalse(audit(paths, metadata_literals=["Synthetic Maintainer"])["ok"])
            self.assertTrue(audit(paths, metadata_literals=["Synthetic Maintainer"], public_attributions={oid: approval})["ok"])
            with self.assertRaises(ContractError): fingerprint_metadata(raw, {**approval, "headers_sha256": "0" * 64})
            self.assertIn(b"Synthetic Maintainer", fingerprint_metadata(raw + b"Synthetic Maintainer", approval))
            file.write_text("Synthetic Maintainer")
            self.assertFalse(audit(paths, literals=["Synthetic Maintainer"], metadata_literals=["Synthetic Maintainer"], public_attributions={oid: approval})["ok"])
            git("add", "README.md"); git("commit", "-qm", "test(privacy): another commit")
            self.assertFalse(audit(paths, metadata_literals=["Synthetic Maintainer"], public_attributions={oid: approval})["ok"])

    def repo(self, paths):
        def git(*args):
            return subprocess.run(["git", *args], cwd=paths.root, capture_output=True, check=True).stdout
        git("init", "-q"); git("config", "user.name", "Synthetic Maintainer")
        git("config", "user.email", "maintainer@example.invalid")
        return git

    def test_every_staged_blob_is_checked_not_only_working_files(self):
        with workspace() as paths:
            git = self.repo(paths)
            path = paths.root / "sample.txt"
            path.write_text("synthetic-private-canary")
            git("add", "sample.txt")
            path.write_text("clean current view")
            result = audit(paths, literals=["synthetic-private-canary"])
            self.assertFalse(result["ok"])
            self.assertTrue(any(f["scope"] == "blob" for f in result["findings"]))
            self.assertNotIn("synthetic-private-canary", json.dumps(result))

    def test_deleted_private_data_in_history_is_still_detected(self):
        with workspace() as paths:
            git = self.repo(paths)
            private = paths.root / "data"; private.mkdir()
            (private / "profile.json").write_text("{}")
            git("add", "data"); git("commit", "-qm", "test(privacy): synthetic private path")
            git("rm", "-q", "data/profile.json"); git("commit", "-qm", "test(privacy): remove current copy")
            self.assertFalse(audit(paths)["ok"])

    def test_unknown_binary_email_and_secret_are_not_silently_skipped(self):
        self.assertIn("BINARY_OR_ENCODING", findings_for("payload.txt", b"\x00binary"))
        email = ("private-user" + "@" + "mail-provider.org").encode()
        self.assertIn("NONEXAMPLE_EMAIL", findings_for("payload.txt", email))
        self.assertNotIn("NONEXAMPLE_EMAIL", findings_for("example.txt", b"person@example.invalid"))
        value = json.dumps({"password": "".join(chr(65 + i) for i in range(12))}).encode()
        self.assertIn("LITERAL_SECRET_FIELD", findings_for("payload.json", value))

    def test_symlink_and_submodule_entries_are_rejected(self):
        with workspace() as paths:
            git = self.repo(paths)
            (paths.root / "link").symlink_to("../outside")
            git("add", "link")
            self.assertTrue(any("LINK" in f["code"] for f in audit(paths)["findings"]))

    def test_clean_fictional_source_and_public_attribution_are_allowed(self):
        self.assertNotIn("NONEXAMPLE_EMAIL", findings_for("metadata", b"committer GitHub <noreply@github.com>", metadata=True))
        with workspace() as paths:
            git = self.repo(paths)
            (paths.root / "README.md").write_text("# Example toolkit\nNo candidate data.")
            git("add", "README.md"); git("commit", "-qm", "docs(example): synthetic source")
            result = audit(paths)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["commit_count"], 1)

    def test_detached_push_object_is_checked(self):
        with workspace() as paths:
            git = self.repo(paths)
            (paths.root / "README.md").write_text("Synthetic clean base")
            git("add", "README.md"); git("commit", "-qm", "test(privacy): clean base")
            base = git("rev-parse", "HEAD").decode().strip()
            (paths.root / "README.md").write_text("synthetic-private-detached-canary")
            git("add", "README.md"); git("commit", "-qm", "test(privacy): detached synthetic object")
            leaked = git("rev-parse", "HEAD").decode().strip()
            # Only an isolated disposable test repository is reset here.
            git("reset", "--hard", base)
            result = audit(paths, literals=["synthetic-private-detached-canary"], extra_revisions=[leaked])
            self.assertFalse(result["ok"])
            self.assertEqual(result["commit_count"], 2)

    def test_attestation_binds_history_rules_and_working_files(self):
        from career_kit.canonical_json import canonical_sha256
        with workspace() as paths:
            git = self.repo(paths)
            path = paths.root / "README.md"; path.write_text("Synthetic clean base")
            git("add", "README.md"); git("commit", "-qm", "test(privacy): clean base")
            before = canonical_sha256(audit(paths))
            self.assertEqual(before, canonical_sha256(audit(paths)))
            self.assertNotEqual(before, canonical_sha256(audit(paths, literals=["synthetic-unmatched-rule"])))
            path.write_text("Changed clean source")
            self.assertNotEqual(before, canonical_sha256(audit(paths)))
