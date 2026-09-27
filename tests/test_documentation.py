from pathlib import Path
import re
import unittest


class DocumentationTests(unittest.TestCase):
    def test_relative_links_resolve_inside_this_repository(self):
        root = Path(__file__).resolve().parents[1]
        files = [root / "README.md", root / "AGENTS.md", root / "CONTRIBUTING.md", *root.joinpath("document").glob("*.md")]
        for file in files:
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", file.read_text()):
                if target.startswith(("https://", "http://", "#")):
                    continue
                resolved = (file.parent / target.split("#")[0]).resolve()
                self.assertTrue(resolved.is_relative_to(root), target)
                self.assertTrue(resolved.exists(), (file.name, target))

    def test_onboarding_has_project_specific_interviews_and_backend_setup(self):
        root = Path(__file__).resolve().parents[1]
        text = root.joinpath("document/getting-started.md").read_text()
        for term in ("Ownership", "source_ref", "unknown", "confidential", "project", "backend", "report-submitted"):
            self.assertIn(term.casefold(), text.casefold())
        self.assertTrue(root.joinpath(".agents/skills/career-kit/SKILL.md").is_file())
