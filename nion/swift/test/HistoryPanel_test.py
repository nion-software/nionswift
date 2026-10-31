# standard libraries
import logging
import typing
import unittest

# third party libraries
# None

# local libraries
from nion.swift import HistoryPanel
from nion.swift.model import CommandHistory
from nion.swift.model import Feature
from nion.swift.test import TestContext
from nion.ui import Window


class TestHistoryPanelClass(unittest.TestCase):

    def setUp(self) -> None:
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()

    def tearDown(self) -> None:
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def _enable_command_log(self) -> None:
        # the application enables the command log, with the command history on it, only when it sets up a log file.
        commands_logger = logging.getLogger("_commands")
        self.addCleanup(setattr, commands_logger, "disabled", commands_logger.disabled)
        self.addCleanup(setattr, commands_logger, "propagate", commands_logger.propagate)
        self.addCleanup(commands_logger.setLevel, commands_logger.level)
        commands_logger.disabled = False
        commands_logger.propagate = False
        commands_logger.setLevel(logging.INFO)
        if CommandHistory.command_history not in commands_logger.handlers:
            commands_logger.addHandler(CommandHistory.command_history)
            self.addCleanup(commands_logger.removeHandler, CommandHistory.command_history)

    def _enable_feature(self) -> None:
        feature = Feature.FeatureManager().get_feature(HistoryPanel.history_panel_feature_id)
        assert feature
        feature.enabled = True
        self.addCleanup(setattr, feature, "enabled", False)

    def test_history_panel_is_only_in_a_window_while_its_feature_is_enabled(self) -> None:
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            self.assertIsNone(document_controller.find_dock_panel("history-panel"))
        self._enable_feature()
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            self.assertIsNotNone(document_controller.find_dock_panel("history-panel"))

    def test_copy_in_history_panel_copies_the_selected_entries(self) -> None:
        class HistoryPanelTestAction(Window.Action):
            action_id = "history_panel_test.action"
            action_name = "History Panel Test"

            def execute(self, context: Window.ActionContext) -> Window.ActionResult:
                return Window.ActionResult(Window.ActionStatus.FINISHED)

        Window.register_action(HistoryPanelTestAction())
        self.addCleanup(Window.unregister_action, "history_panel_test.action")
        self._enable_feature()
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller_with_application()
            # an application disables the command log when it is made.
            self._enable_command_log()
            history_panel = document_controller.find_dock_panel("history-panel")
            assert isinstance(history_panel, HistoryPanel.HistoryPanel)
            document_controller.perform_action("history_panel_test.action", invoked_from=Window.ActionOrigin.MENU)
            document_controller.periodic()
            # select the action's two rows, its start and its end, which are the last two.
            entry_count = len(CommandHistory.command_history.entries)
            history_panel._selection.set_multiple({entry_count - 2, entry_count - 1})
            history_panel._list_canvas_item.request_focus()
            document_controller.perform_edit_command("copy")
            copied_lines = document_controller.ui.clipboard_text().splitlines()
            self.assertEqual(2, len(copied_lines))
            self.assertTrue(all("history_panel_test.action" in line for line in copied_lines))

    def test_history_panel_selection_stays_on_its_entry_when_the_full_history_drops_its_oldest(self) -> None:
        self._enable_feature()
        self._enable_command_log()
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            history_panel = document_controller.find_dock_panel("history-panel")
            assert isinstance(history_panel, HistoryPanel.HistoryPanel)
            for index in range(CommandHistory.MAX_ENTRY_COUNT):
                CommandHistory.record(CommandHistory.CommandHistoryEntryKind.PANEL, "panel opened", identifier=f"selection-test-{index}")
            document_controller.periodic()
            history_panel._selection.set(CommandHistory.MAX_ENTRY_COUNT - 2)
            # the full history drops its oldest entry for this one.
            CommandHistory.record(CommandHistory.CommandHistoryEntryKind.PANEL, "panel opened", identifier="selection-test-new")
            document_controller.periodic()
            history_panel._list_canvas_item.request_focus()
            document_controller.perform_edit_command("copy")
            self.assertIn(f"selection-test-{CommandHistory.MAX_ENTRY_COUNT - 2}", document_controller.ui.clipboard_text())


if __name__ == '__main__':
    unittest.main()
