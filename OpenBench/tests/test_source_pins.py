import json
from pathlib import Path

from django.test import SimpleTestCase


class SourcePinTests(SimpleTestCase):

    def test_canonical_worker_and_runner_are_exactly_pinned(self):
        root = Path(__file__).resolve().parents[2]
        config = json.loads((root / "Config" / "config.json").read_text(encoding="utf-8"))

        self.assertEqual(config["client_version"], 41)
        self.assertEqual(
            config["client_repo_ref"],
            "3e2abc27f541a9f18cba0d40c6c537dc0378fac1",
        )
        self.assertEqual(config["shogitest_min_version"], "0.1.2")
        self.assertEqual(
            config["shogitest_repo_ref"],
            "06a9c7bcd2515d1ee154df790cec5786c11e905e",
        )
