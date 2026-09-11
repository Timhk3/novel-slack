import os
import tempfile
import time
import unittest
from pathlib import Path

from novelslack.activity import MaintenanceDashboardWorker
from novelslack.platforms import (
    PlatformAdapter,
    PlatformPaths,
    TrashCleanResult,
    TrashStatus,
    create_platform_adapter,
)
from novelslack.platforms.linux import LinuxPlatformAdapter
from novelslack.platforms.macos import MacOSPlatformAdapter
from novelslack.platforms.windows import WindowsPlatformAdapter


class FixedCpu:
    def sample(self):
        return 12.5


class FakeAdapter(PlatformAdapter):
    key = "fake"
    display_name = "FakeOS"
    trash_label = "Trash"

    def __init__(self, root: Path):
        self.root = root

    def paths(self):
        return PlatformPaths(
            user_temp=self.root / "user-temp",
            system_temp=self.root / "system-temp",
            pip_cache=self.root / "pip",
            npm_cache=self.root / "npm",
            diagnostics=(("diagnostics", self.root / "diag"),),
            trash_root=self.root / "trash",
        )

    def state_dir(self):
        return self.root / "state"

    def app_cache_dir(self):
        return self.root / "cache"

    def create_cpu_sampler(self):
        return FixedCpu()

    def memory_status(self):
        return 50, 4 * 1024**3

    def process_count(self):
        return 10

    def process_memory_summary(self):
        return 10, [("demo", 128.0)], 0

    def trash_status(self):
        return TrashStatus(2048, 2)

    def empty_trash(self):
        return TrashCleanResult(2048, 2, 0)


class PlatformAdapterTests(unittest.TestCase):
    def test_factory_explicit_platforms(self):
        self.assertIsInstance(
            create_platform_adapter("windows"),
            WindowsPlatformAdapter,
        )
        self.assertIsInstance(
            create_platform_adapter("macos"),
            MacOSPlatformAdapter,
        )
        self.assertIsInstance(
            create_platform_adapter("linux"),
            LinuxPlatformAdapter,
        )

    def test_linux_native_metrics_work_on_linux(self):
        if not os.path.exists("/proc/meminfo"):
            self.skipTest("Linux /proc is not available")

        adapter = LinuxPlatformAdapter()

        memory = adapter.memory_status()
        self.assertIsNotNone(memory)
        self.assertGreaterEqual(memory[0], 0)
        self.assertGreater(memory[1], 0)

        count = adapter.process_count()
        self.assertIsNotNone(count)
        self.assertGreater(count, 0)

        sampler = adapter.create_cpu_sampler()
        sampler.sample()
        time.sleep(0.03)
        cpu = sampler.sample()
        self.assertIsNotNone(cpu)
        self.assertGreaterEqual(cpu, 0)
        self.assertLessEqual(cpu, 100)

    def test_posix_trash_implementations_use_user_scoped_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            linux = LinuxPlatformAdapter()
            linux.xdg_data = root / "linux-data"
            linux_files = linux.xdg_data / "Trash" / "files"
            linux_info = linux.xdg_data / "Trash" / "info"
            linux_files.mkdir(parents=True)
            linux_info.mkdir(parents=True)
            (linux_files / "deleted.txt").write_bytes(b"x" * 50)
            (linux_info / "deleted.txt.trashinfo").write_text(
                "[Trash Info]",
                encoding="utf-8",
            )

            status = linux.trash_status()
            self.assertEqual(status.size, 50)
            result = linux.empty_trash()
            self.assertGreaterEqual(result.reclaimed, 50)
            self.assertFalse(any(linux_files.iterdir()))
            self.assertFalse(any(linux_info.iterdir()))

            mac = MacOSPlatformAdapter()
            mac.home = root / "mac-home"
            mac_trash = mac.home / ".Trash"
            mac_trash.mkdir(parents=True)
            (mac_trash / "deleted.txt").write_bytes(b"x" * 60)

            status = mac.trash_status()
            self.assertEqual(status.size, 60)
            result = mac.empty_trash()
            self.assertGreaterEqual(result.reclaimed, 60)
            self.assertFalse(any(mac_trash.iterdir()))

    def test_worker_is_platform_agnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = FakeAdapter(root)

            for path in (
                adapter.paths().user_temp,
                adapter.paths().system_temp,
                adapter.paths().pip_cache,
                adapter.paths().npm_cache,
                adapter.paths().diagnostics[0][1],
                adapter.paths().trash_root,
            ):
                path.mkdir(parents=True, exist_ok=True)

            worker = MaintenanceDashboardWorker(root, adapter=adapter)
            worker._sample_system()
            snapshot = worker.snapshot()

            self.assertEqual(snapshot.platform_name, "FakeOS")
            self.assertEqual(snapshot.trash_label, "Trash")
            self.assertEqual(snapshot.memory_load, 50)
            self.assertEqual(snapshot.process_count, 10)
            self.assertEqual(snapshot.trash_bytes, 2048)

    def test_windows_paths_preserve_current_layout(self):
        adapter = WindowsPlatformAdapter()
        paths = adapter.paths()

        self.assertEqual(adapter.trash_label, "Recycle Bin")
        self.assertEqual(paths.pip_cache.name, "Cache")
        self.assertEqual(paths.npm_cache.name, "npm-cache")
        self.assertEqual(adapter.state_dir().name, "NovelSlack")
        self.assertEqual(adapter.app_cache_dir().name, "NovelSlack")

    def test_cleanup_engine_delegates_trash_to_adapter(self):
        from novelslack.maintenance import execute_cleanup
        from novelslack.model import CleanupItem, CleanupPlan

        with tempfile.TemporaryDirectory() as directory:
            adapter = FakeAdapter(Path(directory))
            plan = CleanupPlan(
                [
                    CleanupItem(
                        "trash",
                        "Trash",
                        2048,
                        "Confirm",
                        "test",
                        True,
                        False,
                    )
                ],
                True,
            )

            result = execute_cleanup(
                plan,
                {"trash"},
                adapter=adapter,
            )

            self.assertIn("2.0 KiB", result.summary)



if __name__ == "__main__":
    unittest.main()
