import tempfile
import unittest
from pathlib import Path

from novelslack.index_cache import TextIndexCache
from novelslack.reader import TextReader


class ReaderIndexTests(unittest.TestCase):
    def test_index_cache_and_volumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = root / "book.txt"
            cache = TextIndexCache(root / "index.json")

            book.write_text(
                "\n".join(
                    [
                        "第一卷 小丑",
                        "第一章 开始",
                        *[f"a{i}" for i in range(8)],
                        "第二章 继续",
                        *[f"b{i}" for i in range(8)],
                        "第二卷 无面人",
                        "第三章 转折",
                        *[f"c{i}" for i in range(8)],
                        "第四章 结束",
                        *[f"d{i}" for i in range(8)],
                    ]
                ),
                encoding="utf-8",
            )

            first = TextReader(page_size=5)
            self.assertTrue(first.load(book, cache))
            self.assertFalse(first.index_cache_hit)
            self.assertEqual(len(first.volumes), 2)
            self.assertEqual(len(first.chapters), 4)

            second = TextReader(page_size=5)
            self.assertTrue(second.load(book, cache))
            self.assertTrue(second.index_cache_hit)
            self.assertEqual(len(second.volumes), 2)
            self.assertEqual(second.volumes[1].number, 2)


if __name__ == "__main__":
    unittest.main()
