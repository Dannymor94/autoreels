"""Self-tests for the optional handoff evidence-consistency checker (stdlib only)."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "evidence_consistency", Path(__file__).with_name("evidence_consistency.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EvidenceConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        files = {
            "positive.stdout": "PASS [01] alpha\nPASS [02] beta\n",
            "positive.stderr": "",
            "positive.exit": "0\n",
            "negative.stdout": "MISMATCH\n",
            "negative.stderr": "",
            "negative.exit": "1\n",
        }
        for name, text in files.items():
            (self.root / name).write_text(text, encoding="utf-8")
        self.manifest = {
            "schema": 1,
            "task": "M224-R2",
            "base_sha": "a" * 40,
            "artifacts": [
                {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in self.root.iterdir()
            ],
            "runs": [
                {"name": "positive", "expected_exit": 0, "stdout": "positive.stdout",
                 "stderr": "positive.stderr", "exit_file": "positive.exit", "checks": 2},
                {"name": "negative", "expected_exit": 1, "stdout": "negative.stdout",
                 "stderr": "negative.stderr", "exit_file": "negative.exit"},
            ],
            "claims": [
                {"id": "F5", "level": "HELPER", "status": "CONFIRMED", "evidence": ["positive.stdout"]},
                {"id": "F6", "level": "NOT_REPRODUCED", "status": "NOT_REPRODUCED", "evidence": ["positive.stdout"]},
            ],
        }
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        (self.root / "evidence.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def errors(self):
        return module.validate(self.root / "evidence.json")

    def test_valid(self):
        self.assertEqual(self.errors(), [])

    def test_tampered_hash(self):
        (self.root / "positive.stdout").write_text("hacked", encoding="utf-8")
        self.assertTrue(any("hash mismatch" in e for e in self.errors()))

    def test_tampered_exit_receipt(self):
        (self.root / "negative.exit").write_text("0\n", encoding="utf-8")
        self.assertTrue(any("!= expected" in e for e in self.errors()))

    def test_missing_numbered_assertion(self):
        (self.root / "positive.stdout").write_text("PASS [01] alpha\nPASS [03] beta\n", encoding="utf-8")
        self.assertTrue(any("expected consecutive" in e for e in self.errors()))

    def test_path_traversal(self):
        self.manifest["artifacts"][0]["path"] = "../secret"
        self.save()
        self.assertTrue(self.errors())

    def test_contradictory_claim(self):
        self.manifest["claims"][1]["status"] = "CONFIRMED"
        self.save()
        self.assertTrue(any("cannot be CONFIRMED" in e for e in self.errors()))


if __name__ == "__main__":
    unittest.main()
