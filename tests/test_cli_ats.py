import contextlib
import io
import json
from unittest.mock import patch
import unittest

from career_kit.cli import main
from career_kit.ats import ATSParser, validate_public_url
from career_kit.errors import ContractError
from helpers import workspace


class CommandTests(unittest.TestCase):
    def test_cli_init_and_errors_do_not_echo_private_input_values(self):
        with workspace() as paths:
            out = io.StringIO()
            with patch("career_kit.cli.ProjectPaths.discover", return_value=paths), contextlib.redirect_stdout(out):
                self.assertEqual(main(["init"]), 0)
            result = json.loads(out.getvalue())
            self.assertEqual(len(result["result"]["created_blank_inputs"]), 4)
            out = io.StringIO()
            with patch("career_kit.cli.ProjectPaths.discover", return_value=paths), contextlib.redirect_stdout(out):
                self.assertEqual(main(["candidate", "import", "profile", "--file", "credentials/mail.json"]), 1)
            self.assertEqual(json.loads(out.getvalue())["error"]["code"], "INPUT_FORBIDDEN")

    def test_official_feed_parser_is_not_a_company_verification(self):
        raw = json.dumps({"jobs": [{"id": "synthetic-role", "title": "Synthetic Role", "absolute_url": "https://employer.invalid/job", "content": "<p>Fictional requirement</p>", "location": {"name": "Example"}}]}).encode()
        jobs, warnings, complete = ATSParser().parse("greenhouse", raw, "https://employer.invalid/careers")
        self.assertEqual(len(jobs), 1)
        self.assertIn("Fictional requirement", jobs[0]["description"])
        self.assertFalse(complete)  # A parsed response is not a completed live scan.

    def test_private_source_urls_are_rejected(self):
        for url in ("file:///private", "http://employer.invalid", "https://127.0.0.1/jobs", "https://localhost/jobs"):
            with self.subTest(url=url), self.assertRaises(ContractError): validate_public_url(url)
