import tempfile
import unittest
from pathlib import Path

from rich.console import Console

from novelslack.reader import TextReader
from novelslack.ui import ConsoleUI


class ResponsiveTerminalTests(unittest.TestCase):
    def _reader(self, root: Path) -> TextReader:
        book = root / "book.txt"
        long_line = "这是一段用于测试终端窗口缩放的中文长文本。" * 8
        book.write_text(
            "\n".join([long_line for _ in range(40)]),
            encoding="utf-8",
        )
        reader = TextReader(page_size=15)
        self.assertTrue(reader.load(book))
        return reader

    def test_narrow_window_reduces_reader_density(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = self._reader(Path(directory))
            ui = ConsoleUI()
            ui.console = Console(
                width=80,
                height=26,
                force_terminal=False,
                color_system=None,
            )

            fitted = ui.recommended_reader_page_size(reader, 15)
            self.assertGreaterEqual(fitted, 2)
            self.assertLess(fitted, 15)

    def test_large_window_can_restore_preferred_density(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = self._reader(Path(directory))
            ui = ConsoleUI()
            ui.console = Console(
                width=220,
                height=55,
                force_terminal=False,
                color_system=None,
            )

            fitted = ui.recommended_reader_page_size(reader, 15)
            self.assertEqual(fitted, 15)

    def test_catalog_page_size_tracks_height(self):
        ui = ConsoleUI()
        ui.console = Console(
            width=100,
            height=20,
            force_terminal=False,
            color_system=None,
        )
        self.assertLess(ui.recommended_catalog_page_size(18), 18)


if __name__ == "__main__":
    unittest.main()
