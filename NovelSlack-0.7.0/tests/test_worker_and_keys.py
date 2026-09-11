import tempfile
import unittest
from pathlib import Path

from novelslack.activity import MaintenanceDashboardWorker
from novelslack.input import KEYMAP
from novelslack.model import Action


class WorkerAndKeyTests(unittest.TestCase):
    def test_scan_budget_never_fully_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = MaintenanceDashboardWorker(Path(directory))
            worker._touch_snapshot(cpu_load=99, memory_load=96)
            self.assertEqual(worker._scan_budget(), 2)

    def test_cleanup_and_selection_keys(self):
        self.assertEqual(KEYMAP["["], Action.PREVIOUS_CHAPTER)
        self.assertEqual(KEYMAP["]"], Action.NEXT_CHAPTER)
        self.assertEqual(KEYMAP[" "], Action.TOGGLE)
        self.assertEqual(KEYMAP["__ENTER__"], Action.SELECT)
        self.assertEqual(KEYMAP["C"], Action.CLEANUP)


if __name__ == "__main__":
    unittest.main()
