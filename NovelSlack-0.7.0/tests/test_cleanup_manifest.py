import tempfile
import unittest
from pathlib import Path

from novelslack.activity import MaintenanceDashboardWorker
from novelslack.maintenance import execute_cleanup
from novelslack.model import CleanupCandidate


class CleanupManifestTests(unittest.TestCase):
    def test_cleanup_uses_validated_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = MaintenanceDashboardWorker(root)

            target = root / "old.tmp"
            target.write_bytes(b"x" * 100)
            stat = target.stat()

            worker.user_temp.candidates = [
                CleanupCandidate(target, stat.st_size, stat.st_mtime_ns)
            ]
            worker.user_temp.candidate_bytes = stat.st_size
            worker.user_temp.candidate_files = 1

            plan = worker.cleanup_plan()
            result = execute_cleanup(plan, {"user_temp"})

            self.assertFalse(target.exists())
            self.assertIn("reclaimed", result.summary)


if __name__ == "__main__":
    unittest.main()
