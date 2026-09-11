import tempfile
import unittest
from pathlib import Path

from novelslack.index_cache import TextIndexCache
from novelslack.reader import TextReader


class HeadingParser062Tests(unittest.TestCase):
    def test_false_volume_prose_falls_back_to_flat_chapter_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = root / "book.txt"

            lines = [
                "第一部完",
                "第一章 绯红",
                *["正文" for _ in range(10)],
                "第二部完",
                "第二章 情况",
                *["正文" for _ in range(10)],
                "第三部总结和请假",
                "第三章 来客",
                *["正文" for _ in range(10)],
                "第五部“红祭司”，大家可以做阅读理解了，笑。",
                "第四章 拍照专家",
                *["正文" for _ in range(10)],
                "第六部叫做“逐光者”，来自古称“逐日者”。",
                "第五章 灵感与尝试（求月票）",
                *["正文" for _ in range(10)],
                "第六部的一个问题在于，需要做的战斗太多了。",
                "第七部总结兼请假",
                "第六章 心理炼金会的线索",
                *["正文" for _ in range(10)],
            ]
            book.write_text("\n".join(lines), encoding="utf-8")

            reader = TextReader(page_size=10)
            self.assertTrue(reader.load(book, TextIndexCache(root / "cache.json")))

            self.assertEqual(reader.volumes, [])
            self.assertGreaterEqual(len(reader.chapters), 6)

    def test_chapter_title_stops_before_body_sentence_punctuation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = root / "book.txt"
            book.write_text(
                "\n".join(
                    [
                        "第一章 绯红",
                        *["正文" for _ in range(8)],
                        "第二章 灵感与尝试（求月票）",
                        *["正文" for _ in range(8)],
                        "第三章 真正的标题，这是正文式补充，不应进入标题。",
                        *["正文" for _ in range(8)],
                    ]
                ),
                encoding="utf-8",
            )

            reader = TextReader(page_size=5)
            self.assertTrue(reader.load(book))

            titles = [chapter.title for chapter in reader.chapters]
            self.assertIn("第二章 灵感与尝试（求月票）", titles)
            self.assertIn("第三章 真正的标题", titles)
            self.assertNotIn(
                "第三章 真正的标题，这是正文式补充，不应进入标题。",
                titles,
            )

    def test_old_index_schema_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = root / "book.txt"
            cache_path = root / "cache.json"

            book.write_text(
                "第一章 A\n" + "\n".join(["正文"] * 8) + "\n第二章 B\n",
                encoding="utf-8",
            )
            cache_path.write_text(
                '{"version":1,"books":{"stale":{"signature":"bad"}}}',
                encoding="utf-8",
            )

            cache = TextIndexCache(cache_path)
            self.assertEqual(cache.data["version"], 2)

    def test_colon_separator_is_part_of_heading_structure_not_body(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = root / "book.txt"
            book.write_text(
                "\n".join(
                    [
                        "第一卷：开端",
                        "第一章：绯红",
                        *["正文" for _ in range(8)],
                        "第二章：继续",
                        *["正文" for _ in range(8)],
                        "第二卷：转折",
                        "第三章：来客",
                        *["正文" for _ in range(8)],
                        "第四章：结束",
                        *["正文" for _ in range(8)],
                    ]
                ),
                encoding="utf-8",
            )

            reader = TextReader(page_size=5)
            self.assertTrue(reader.load(book))
            self.assertEqual(reader.chapters[0].title, "第一章 绯红")
            self.assertEqual(reader.volumes[0].title, "第一卷 开端")



if __name__ == "__main__":
    unittest.main()
