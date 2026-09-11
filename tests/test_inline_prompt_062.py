import tempfile
import unittest
from pathlib import Path

from novelslack.app import NovelSlackApp
from novelslack.index_cache import TextIndexCache
from novelslack.model import Mode
from novelslack.state_store import StateStore


class InlinePromptTests(unittest.TestCase):
    def _app(self, root: Path) -> NovelSlackApp:
        book = root / "book.txt"
        book.write_text(
            "\n".join(
                [
                    "第一章 开始",
                    *[f"正文 alpha {i}" for i in range(20)],
                    "第二章 继续",
                    *[f"正文 beta {i}" for i in range(20)],
                ]
            ),
            encoding="utf-8",
        )
        return NovelSlackApp(
            root,
            str(book),
            page_size=10,
            store=StateStore(root / "state.json"),
            index_cache=TextIndexCache(root / "index.json"),
        )

    def test_escape_cancels_prompt_without_leaving_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self._app(Path(directory))
            app.state.mode = Mode.READING
            app._activate_inline_prompt("search")
            app.inline_prompt_buffer = "alpha"
            app._handle_inline_prompt_token("\x1b")

            self.assertEqual(app.state.mode, Mode.READING)
            self.assertIsNone(app.inline_prompt_kind)
            self.assertEqual(app.inline_prompt_buffer, "")

    def test_page_prompt_submits_in_same_reader_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self._app(Path(directory))
            app.state.mode = Mode.READING
            app._activate_inline_prompt("page")
            for char in "2":
                app._handle_inline_prompt_token(char)
            app._handle_inline_prompt_token("__ENTER__")

            self.assertEqual(app.state.mode, Mode.READING)
            self.assertIsNone(app.inline_prompt_kind)
            self.assertEqual(app.reader.current_page, 2)

    def test_search_prompt_submits_without_switching_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self._app(Path(directory))
            app.state.mode = Mode.READING
            app._activate_inline_prompt("search")
            for char in "beta":
                app._handle_inline_prompt_token(char)
            app._handle_inline_prompt_token("__ENTER__")

            self.assertEqual(app.state.mode, Mode.READING)
            self.assertEqual(app.reader.search_state.query, "beta")
            self.assertGreater(app.reader.search_state.count, 0)

    def test_reader_prompt_render_keeps_body_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self._app(Path(directory))
            app.state.mode = Mode.READING
            app._activate_inline_prompt("search")
            app.inline_prompt_buffer = "alpha"

            renderable = app.ui.reader(
                app.reader,
                None,
                app._prompt_label(),
                app.inline_prompt_buffer,
            )

            from rich.console import Console
            import io

            output = io.StringIO()
            console = Console(
                file=output,
                force_terminal=False,
                color_system=None,
                width=120,
                height=35,
            )
            console.print(renderable)
            rendered = output.getvalue()

            self.assertIn("Search text", rendered)
            self.assertIn("alpha", rendered)
            self.assertIn("正文", rendered)



if __name__ == "__main__":
    unittest.main()
