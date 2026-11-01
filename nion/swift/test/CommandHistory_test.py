# standard libraries
import datetime
import logging
import typing
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift.model import CommandHistory
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.test import TestContext
from nion.ui import Window
from nion.utils import Event


class TestCommandHistoryClass(unittest.TestCase):

    def setUp(self) -> None:
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()
        self._entry_appended_listeners = list[Event.EventListener]()

    def tearDown(self) -> None:
        self._entry_appended_listeners = list()
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

    def _listen_for_entries(self) -> list[CommandHistory.CommandHistoryEntry]:
        self._enable_command_log()
        entries = list[CommandHistory.CommandHistoryEntry]()
        # the listener is held until the test ends, when dropping it stops the recording.
        self._entry_appended_listeners.append(CommandHistory.command_history.entry_appended_event.listen(entries.append))
        return entries

    def test_action_from_a_dialog_is_recorded_with_its_origin_parameters_and_duration(self) -> None:
        class HistoryTestAction(Window.Action):
            action_id = "command_history_test.action"
            action_name = "History Test"

            def execute(self, context: Window.ActionContext) -> Window.ActionResult:
                return Window.ActionResult(Window.ActionStatus.FINISHED)

        Window.register_action(HistoryTestAction())
        self.addCleanup(Window.unregister_action, "command_history_test.action")
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller_with_application()
            entries = self._listen_for_entries()
            document_controller.execute_action("command_history_test.action", parameters={"name": "new"},
                                               invoked_from=Window.ActionOrigin.DIALOG, invoked_from_id="test_dialog")
            action_entry, action_end_entry = entries
            self.assertEqual((CommandHistory.CommandHistoryEntryKind.ACTION, "command_history_test.action", "History Test"),
                             (action_entry.kind, action_entry.identifier, action_entry.title))
            self.assertEqual((Window.ActionOrigin.DIALOG, "test_dialog"), (action_entry.invoked_from, action_entry.invoked_from_id))
            self.assertEqual("new", action_entry.parameters["name"])
            self.assertEqual((CommandHistory.CommandHistoryEntryKind.ACTION_END, "command_history_test.action"),
                             (action_end_entry.kind, action_end_entry.identifier))
            self.assertIsNotNone(action_end_entry.duration)

    def test_action_which_raises_is_recorded_with_its_end(self) -> None:
        class RaisingTestAction(Window.Action):
            action_id = "command_history_test.raises"
            action_name = "Raising Test"

            def execute(self, context: Window.ActionContext) -> Window.ActionResult:
                raise ValueError()

        Window.register_action(RaisingTestAction())
        self.addCleanup(Window.unregister_action, "command_history_test.raises")
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller_with_application()
            entries = self._listen_for_entries()
            with self.assertRaises(ValueError):
                document_controller.execute_action("command_history_test.raises")
            self.assertEqual([CommandHistory.CommandHistoryEntryKind.ACTION, CommandHistory.CommandHistoryEntryKind.ACTION_END], [entry.kind for entry in entries])

    def test_change_made_by_an_action_is_recorded_with_the_action(self) -> None:
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller_with_application()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            assert display_panel
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_display_item(document_model.get_display_item_for_data_item(data_item))
            entries = self._listen_for_entries()
            document_controller.perform_action("processing.line_profile", invoked_from=Window.ActionOrigin.MENU)
            change_entries = [entry for entry in entries if entry.kind == CommandHistory.CommandHistoryEntryKind.CHANGE]
            self.assertTrue(change_entries)
            self.assertEqual({"processing.line_profile"}, {entry.action_id for entry in change_entries})

    def test_edit_command_which_makes_a_change_is_recorded_as_an_action(self) -> None:
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller_with_application()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            assert display_panel
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            assert display_item
            display_panel.set_display_panel_display_item(display_item)
            display_item.add_graphic(Graphics.RectangleGraphic())
            display_item.graphic_selection.set(0)
            document_controller.perform_edit_command("copy")
            entries = self._listen_for_entries()
            document_controller.perform_edit_command("paste", invoked_from=Window.ActionOrigin.MENU)
            self.assertEqual(2, len(display_item.graphics))
            action_entry, change_entry, action_end_entry = entries
            self.assertEqual((CommandHistory.CommandHistoryEntryKind.ACTION, "window.paste", Window.ActionOrigin.MENU),
                             (action_entry.kind, action_entry.identifier, action_entry.invoked_from))
            self.assertEqual((CommandHistory.CommandHistoryEntryKind.CHANGE, "window.paste"), (change_entry.kind, change_entry.action_id))
            self.assertEqual((CommandHistory.CommandHistoryEntryKind.ACTION_END, "window.paste"), (action_end_entry.kind, action_end_entry.identifier))

    def test_command_history_keeps_only_the_most_recent_entries(self) -> None:
        command_history = CommandHistory.CommandHistoryHandler()
        for index in range(CommandHistory.MAX_ENTRY_COUNT + 10):
            entry = CommandHistory.CommandHistoryEntry(CommandHistory.CommandHistoryEntryKind.PANEL, datetime.datetime.now(), "panel opened", identifier=f"panel-{index}")
            command_history.handle(logging.makeLogRecord({"msg": entry}))
        entries = command_history.entries
        self.assertEqual(CommandHistory.MAX_ENTRY_COUNT, len(entries))
        self.assertEqual(f"panel-{CommandHistory.MAX_ENTRY_COUNT + 9}", entries[-1].identifier)


if __name__ == '__main__':
    unittest.main()
