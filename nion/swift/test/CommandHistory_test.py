# standard libraries
import datetime
import logging
import typing
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import DataPanel
from nion.swift import ProjectPanel
from nion.swift.model import CommandHistory
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.test import TestContext
from nion.ui import CanvasItem
from nion.ui import TestUI
from nion.ui import UserInterface
from nion.ui import Widgets
from nion.ui import Window
from nion.utils import Event
from nion.utils import Geometry

WidgetType = typing.TypeVar("WidgetType", bound=UserInterface.Widget)


def find_contained_widget(widget: UserInterface.Widget, widget_type: type[WidgetType]) -> WidgetType | None:
    # the first widget of the type, searching the widget and then the widgets it contains, depth first.
    if isinstance(widget, widget_type):
        return widget
    for contained_widget in widget._contained_widgets:
        if found_widget := find_contained_widget(contained_widget, widget_type):
            return found_widget
    return None


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

    def test_delete_in_the_data_panel_is_recorded_as_delete_item_with_where_it_was_invoked(self) -> None:
        for invoked_by_key in (False, True):
            with self.subTest(invoked_by_key=invoked_by_key), TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller_with_application()
                document_model = document_controller.document_model
                for _ in range(2):
                    document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8))))
                document_controller.periodic()
                data_panel = typing.cast(DataPanel.DataPanel, document_controller.find_dock_panel("data-panel"))
                canvas_widget = data_panel.data_view_widget
                canvas_widget.canvas_item.layout_immediate(Geometry.IntSize(width=320, height=480))
                display_items = list(document_controller.filtered_display_items_model.display_items)
                canvas_widget.simulate_mouse_click(40, 40, CanvasItem.KeyboardModifiers())
                entries = self._listen_for_entries()
                if invoked_by_key:
                    assert canvas_widget.on_key_pressed
                    canvas_widget.on_key_pressed(typing.cast(TestUI.UserInterface, document_controller.ui).create_key_by_id("delete"))
                else:
                    document_controller.perform_edit_command("delete", invoked_from=Window.ActionOrigin.MENU)
                self.assertEqual([display_items[1]], list(document_model.display_items))
                expected_origin = (Window.ActionOrigin.KEY, "data-panel") if invoked_by_key else (Window.ActionOrigin.MENU, None)
                self.assertEqual([("item.delete", *expected_origin)],
                                 [(entry.identifier, entry.invoked_from, entry.invoked_from_id) for entry in entries if entry.kind == CommandHistory.CommandHistoryEntryKind.ACTION])
                self.assertEqual({"item.delete"}, {entry.action_id for entry in entries if entry.kind == CommandHistory.CommandHistoryEntryKind.CHANGE})

    def test_delete_in_a_browser_display_panel_is_recorded_as_delete_item_with_where_it_was_invoked(self) -> None:
        for invoked_by_key in (False, True):
            with self.subTest(invoked_by_key=invoked_by_key), TestContext.create_memory_context() as test_context:
                document_controller = test_context.create_document_controller_with_application()
                document_model = document_controller.document_model
                for _ in range(2):
                    document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8))))
                display_panel = document_controller.selected_display_panel
                assert display_panel
                display_panel.change_display_panel_content({"browser_type": "grid"})
                document_controller.periodic()
                canvas_widget = display_panel.canvas_widget
                assert canvas_widget
                canvas_widget.canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
                display_items = list(document_controller.filtered_display_items_model.display_items)
                # click the grid's first cell, below the display panel's header.
                canvas_widget.simulate_mouse_click(60, 80, CanvasItem.KeyboardModifiers())
                entries = self._listen_for_entries()
                if invoked_by_key:
                    assert canvas_widget.on_key_pressed
                    canvas_widget.on_key_pressed(typing.cast(TestUI.UserInterface, document_controller.ui).create_key_by_id("delete"))
                else:
                    document_controller.perform_edit_command("delete", invoked_from=Window.ActionOrigin.MENU)
                self.assertEqual([display_items[1]], list(document_model.display_items))
                expected_origin = (Window.ActionOrigin.KEY, "display-panel") if invoked_by_key else (Window.ActionOrigin.MENU, None)
                self.assertEqual([("item.delete", *expected_origin)],
                                 [(entry.identifier, entry.invoked_from, entry.invoked_from_id) for entry in entries if entry.kind == CommandHistory.CommandHistoryEntryKind.ACTION])

    def test_edit_delete_in_the_collections_panel_is_recorded_as_remove_group_from_the_menu(self) -> None:
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller_with_application()
            document_model = document_controller.document_model
            document_controller.add_group()
            collections_panel = typing.cast(ProjectPanel.CollectionsPanel, document_controller.find_dock_panel("collections-panel"))
            list_widget = find_contained_widget(collections_panel.widget, Widgets.ListWidget)
            assert list_widget
            canvas_widget = find_contained_widget(list_widget, UserInterface.CanvasWidget)
            assert canvas_widget
            canvas_widget.canvas_item.layout_immediate(Geometry.IntSize(width=320, height=400))
            # the rows are 20 pixels high, and the first data group follows the four smart collections.
            canvas_widget.simulate_mouse_click(40, 4 * 20 + 10, CanvasItem.KeyboardModifiers())
            entries = self._listen_for_entries()
            document_controller.perform_edit_command("delete", invoked_from=Window.ActionOrigin.MENU)
            self.assertEqual(0, len(document_model.data_groups))
            self.assertEqual([("project.remove_group", Window.ActionOrigin.MENU)],
                             [(entry.identifier, entry.invoked_from) for entry in entries if entry.kind == CommandHistory.CommandHistoryEntryKind.ACTION])

    def test_cut_of_a_graphic_is_recorded_as_one_action_with_its_change(self) -> None:
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
            entries = self._listen_for_entries()
            document_controller.perform_edit_command("cut", invoked_from=Window.ActionOrigin.MENU)
            self.assertEqual(0, len(display_item.graphics))
            self.assertEqual(["window.cut"], [entry.identifier for entry in entries if entry.kind == CommandHistory.CommandHistoryEntryKind.ACTION])
            self.assertEqual(["window.cut"], [entry.action_id for entry in entries if entry.kind == CommandHistory.CommandHistoryEntryKind.CHANGE])

    def test_edit_delete_in_a_display_panel_is_recorded_as_delete_selected_graphics_from_the_menu(self) -> None:
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
            display_panel.request_focus()
            entries = self._listen_for_entries()
            document_controller.perform_edit_command("delete", invoked_from=Window.ActionOrigin.MENU)
            self.assertEqual(0, len(display_item.graphics))
            self.assertEqual([("display_panel.delete_graphics", Window.ActionOrigin.MENU)],
                             [(entry.identifier, entry.invoked_from) for entry in entries if entry.kind == CommandHistory.CommandHistoryEntryKind.ACTION])

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
