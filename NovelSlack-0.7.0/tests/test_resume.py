import tempfile
import unittest
from pathlib import Path

from novelslack.index_cache import TextIndexCache
from novelslack.reader import TextReader
from novelslack.state_store import StateStore


class ResumeTests(unittest.TestCase):
    def test_exact_then_changed_file_falls_back_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = root / "book.txt"
            state = StateStore(root / "state.json")
            cache = TextIndexCache(root / "cache.json")

            book.write_text(
                "第一章 开始\n" + "\n".join(f"x{i}" for i in range(20))
                + "\n第二章 继续\n" + "\n".join(f"y{i}" for i in range(20)),
                encoding="utf-8",
            )

            reader = TextReader(page_size=5)
            reader.load(book, cache)
            reader.jump_to_chapter_reference("第二章")
            state.remember_reader(reader)
            state.flush(force=True)

            exact = TextReader(page_size=5)
            exact.load(book, cache)
            self.assertEqual(state.resume_reader(exact), "exact")

            book.write_text(
                "前言新增\n第一章 开始\n"
                + "\n".join(f"x{i}" for i in range(25))
                + "\n第二章 继续\n"
                + "\n".join(f"y{i}" for i in range(25)),
                encoding="utf-8",
            )

            changed = TextReader(page_size=5)
            changed.load(book, cache)
            self.assertIn(state.resume_reader(changed), {"chapter", "ratio"})


if __name__ == "__main__":
    unittest.main()
