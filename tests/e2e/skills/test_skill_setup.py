import os
import re
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILLS_DIR)
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import new_project  # noqa: E402
from session import Session  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"
INSTALL_RE = re.compile(r"\b(apt|apt-get|pip|pip3|npm|brew|cargo|curl)\b")


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillSetup(unittest.TestCase):
    def test_setup_headless(self):
        project = new_project("setup", init=False)
        session = Session(project.repo, "setup", interactive=False)

        result = session.run("/sdlc:setup")

        # setup-checks.sh runs as the skill's frontmatter `!` line, before the model's
        # turn starts, so it never shows up as a Bash tool call (session.py driver facts).
        # `skills == ["setup"]` is the observable proxy that it ran.
        self.assertEqual(result.skills, ["setup"])

        for tool in result.tools:
            if tool["name"] != "Bash":
                continue
            command = str((tool["input"] or {}).get("command", ""))
            self.assertNotRegex(command, INSTALL_RE, f"an install command ran: {command}")

        self.assertIn("/sdlc:init", result.text)


if __name__ == "__main__":
    unittest.main()
