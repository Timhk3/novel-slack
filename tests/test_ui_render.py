import io
import unittest

from rich.console import Console

from novelslack.activity import StreamSnapshot
from novelslack.model import CleanupItem, CleanupPlan
from novelslack.ui import ConsoleUI


class UiRenderTests(unittest.TestCase):
    def test_dashboard_and_cleanup_review_render(self):
        output = io.StringIO()
        ui = ConsoleUI()
        ui.console = Console(
            file=output,
            force_terminal=False,
            color_system=None,
            width=140,
        )

        ui.console.print(
            ui.dashboard(
                StreamSnapshot(
                    cpu_load=20,
                    memory_load=70,
                    current_task="user TEMP",
                    revision=2,
                ),
                [],
            )
        )

        plan = CleanupPlan(
            [
                CleanupItem(
                    "temp",
                    "Old TEMP",
                    1024,
                    "Safe",
                    "test",
                    True,
                    True,
                )
            ],
            True,
        )
        ui.console.print(ui.cleanup_review(plan, 0, {"temp"}))

        rendered = output.getvalue()
        self.assertIn("SYSTEM SNAPSHOT", rendered)
        self.assertIn("Cleanup Review", rendered)
        self.assertIn("[x]", rendered)


if __name__ == "__main__":
    unittest.main()
