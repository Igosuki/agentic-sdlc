import os
import sys
import unittest

E2E_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, E2E_DIR)
from sandbox import new_project  # noqa: E402
from session import Session  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSmoke(unittest.TestCase):
    def test_status_on_a_new_project(self):
        project = new_project("smoke")
        session = Session(project.repo, "status")

        result = session.run("/sdlc:status")

        self.assertEqual(result.skills, ["status"])
        self.assertEqual(result.tools, [])
        self.assertEqual(result.prompts, [])
        self.assertGreater(result.cost_usd, 0)


if __name__ == "__main__":
    unittest.main()
