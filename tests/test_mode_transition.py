import tempfile
import unittest
from pathlib import Path

from novelslack.app import NovelSlackApp
from novelslack.index_cache import TextIndexCache
from novelslack.model import Mode
from novelslack.state_store import StateStore


class FakeUI:
    def __init__(self):
        self.updates = 0

    def update(self, renderable):
        self.updates += 1

    def dashboard(self, *args):
        return "dashboard"

    def reader(self, *args):
        return "reader"

    def status(self, *args):
        return "status"

    def recommended_reader_page_size(self, reader, preferred_lines, extra_reserved_rows=0):
        return preferred_lines

    def stop(self):
        pass


class FakeWorker:
    def __init__(self):
        self.paused = 0
        self.resumed = 0

    def pause(self):
        self.paused += 1

    def resume(self):
        self.resumed += 1

    def snapshot(self):
        from novelslack.activity import StreamSnapshot
        return StreamSnapshot()

    def drain_events(self):
        return []


class ModeTransitionTests(unittest.TestCase):
    def test_live_reader_live_uses_single_transition_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = NovelSlackApp(
                root,
                store=StateStore(root / "state.json"),
                index_cache=TextIndexCache(root / "index.json"),
            )
            app.ui = FakeUI()
            app.worker = FakeWorker()

            app._transition(Mode.READING, force=True)
            self.assertEqual(app.state.mode, Mode.READING)
            self.assertGreaterEqual(app.worker.paused, 1)

            app._transition(Mode.LIVE, force=True)
            self.assertEqual(app.state.mode, Mode.LIVE)
            self.assertGreaterEqual(app.worker.resumed, 1)


if __name__ == "__main__":
    unittest.main()
