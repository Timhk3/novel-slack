import tempfile
import unittest
from pathlib import Path

from novelslack.reader import TextReader


class ChapterBoundedPaginationTests(unittest.TestCase):
    def _reader(self, root: Path, page_size: int = 5) -> TextReader:
        book = root / "book.txt"
        book.write_text(
            "\n".join(
                [
                    "前言",
                    "说明",
                    "第一章 第一章标题",
                    "一-1",
                    "一-2",
                    "一-3",
                    "一-4",
                    "一-5",
                    "一-6",
                    "第二章 第二章标题",
                    "二-1",
                    "二-2",
                    "二-3",
                    "第三章 第三章标题",
                    "三-1",
                    "三-2",
                ]
            ),
            encoding="utf-8",
        )
        reader = TextReader(page_size=page_size)
        self.assertTrue(reader.load(book))
        return reader

    def test_new_chapter_heading_is_first_line_after_next_page(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = self._reader(Path(directory), page_size=5)

            self.assertTrue(reader.jump_to_chapter_index(1))
            self.assertEqual(reader.current_lines()[0], "第一章 第一章标题")

            # Page 1 of chapter 1 does not leak chapter 2.
            self.assertNotIn("第二章 第二章标题", reader.current_lines())

            reader.next_page()
            self.assertNotIn("第二章 第二章标题", reader.current_lines())

            # One more next-page enters chapter 2 exactly at its heading.
            reader.next_page()
            self.assertEqual(reader.current_lines()[0], "第二章 第二章标题")
            self.assertEqual(reader.page_start, reader.chapters[1].line_index)

    def test_next_chapter_always_starts_at_heading(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = self._reader(Path(directory), page_size=5)
            reader.jump_to_chapter_index(1)

            self.assertTrue(reader.next_chapter())
            self.assertEqual(reader.current_lines()[0], "第二章 第二章标题")

            self.assertTrue(reader.next_chapter())
            self.assertEqual(reader.current_lines()[0], "第三章 第三章标题")

    def test_previous_page_from_chapter_start_goes_to_previous_chapter_last_page(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = self._reader(Path(directory), page_size=5)
            reader.jump_to_chapter_index(2)

            reader.previous_page()
            lines = reader.current_lines()

            self.assertNotIn("第二章 第二章标题", lines)
            self.assertIn("一-5", lines)

    def test_page_numbers_are_unique_and_goto_page_uses_chapter_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = self._reader(Path(directory), page_size=5)
            starts = reader._page_starts()

            self.assertEqual(len(starts), len(set(starts)))

            for page in range(1, reader.total_pages + 1):
                self.assertTrue(reader.jump_to_page(page))
                self.assertEqual(reader.current_page, page)

    def test_resize_realignment_keeps_chapter_heading_as_page_start(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = self._reader(Path(directory), page_size=5)
            reader.jump_to_chapter_index(2)
            heading_line = reader.page_start

            reader.page_size = 3
            reader.jump_to_line(heading_line)

            self.assertEqual(reader.page_start, heading_line)
            self.assertEqual(reader.current_lines()[0], "第二章 第二章标题")


if __name__ == "__main__":
    unittest.main()
