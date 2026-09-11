import tempfile
import unittest
from pathlib import Path

from novelslack.activity import MaintenanceDashboardWorker


class DirtySnapshotTests(unittest.TestCase):
    def test_revision_only_changes_on_value_change(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = MaintenanceDashboardWorker(Path(directory))
            before = worker.snapshot().revision

            worker._touch_snapshot(current_task="test")
            after = worker.snapshot().revision
            self.assertGreater(after, before)

            worker._touch_snapshot(current_task="test")
            self.assertEqual(worker.snapshot().revision, after)


if __name__ == "__main__":
    unittest.main()
