# standard libraries
import contextlib
import logging
import pathlib
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DisplayPanel
from nion.swift import Facade
from nion.swift import MimeTypes
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.test import TestContext
from nion.ui import CanvasItem
from nion.ui import ListCanvasItem
from nion.ui import TestUI
from nion.utils import Geometry
from nion.utils import ListModel


Facade.initialize()


class TestDataPanelClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        TestContext.end_leaks(self)

    def test_data_panel_has_initial_selection(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((4, 4))))
            data_panel = document_controller.find_dock_panel("data-panel")
            project_panel = document_controller.find_dock_panel("collections-panel")
            document_controller.periodic()
            # data items
            self.assertEqual(1, data_panel._list_canvas_item.canvas_items_count)
            # collections
            self.assertSetEqual({0}, project_panel._collection_selection.indexes)

    # make sure we can delete top level items, and child items
    def test_image_panel_delete(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            # data_group
            #   data_item1
            #     data_item1a
            #   data_item2
            #     data_item2a
            #   data_item3
            data_group = DataGroup.DataGroup()
            data_group.title = "data_group"
            document_model.append_data_group(data_group)
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "data_item1"
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_group.append_display_item(display_item1)
            data_item1a = document_model.get_invert_new(display_item1, display_item1.data_item)
            data_item1a.title = "data_item1a"
            display_item1a = document_model.get_display_item_for_data_item(data_item1a)
            data_group.append_display_item(display_item1a)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2.title = "data_item2"
            document_model.append_data_item(data_item2)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            data_group.append_display_item(display_item2)
            data_item2a = document_model.get_invert_new(display_item2, display_item2.data_item)
            data_item2a.title = "data_item2a"
            display_item2a = document_model.get_display_item_for_data_item(data_item2a)
            data_group.append_display_item(display_item2a)
            data_item3 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item3.title = "data_item3"
            document_model.append_data_item(data_item3)
            data_group.append_display_item(document_model.get_display_item_for_data_item(data_item3))
            display_panel = DisplayPanel.DisplayPanel(document_controller, dict())
            with contextlib.closing(display_panel):
                display_panel.set_display_panel_display_item(display_item1)
                data_panel = document_controller.find_dock_panel("data-panel")
                document_controller.select_data_item_in_data_panel(data_item=data_item1)
                document_controller.periodic()
                document_controller.selected_display_panel = display_panel
                # first delete a child of a data item
                self.assertEqual(len(document_model.get_dependent_data_items(data_item1)), 1)
                self.assertEqual(len(data_group.display_items), 5)
                document_controller.select_data_item_in_data_panel(data_item=data_item1a)
                # document_controller.selection.set(3)  # set above by date_item instead
                data_panel._list_canvas_item.handle_delete()
                self.assertEqual(len(document_model.get_dependent_data_items(data_item1)), 0)
                # now delete a child of a data group
                self.assertEqual(len(data_group.display_items), 4)
                document_controller.select_data_item_in_data_panel(data_item=data_item2)
                # document_controller.selection.set(2)  # set above by date_item instead
                data_panel._list_canvas_item.handle_delete()
                self.assertEqual(len(data_group.display_items), 2)

    def test_data_panel_deletes_all_selected_items(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_controller.periodic()
            display_item = document_model.display_items[0]
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            data_panel = document_controller.find_dock_panel("data-panel")
            self.assertEqual(3, len(document_model.data_items))
            document_controller.selection.set_multiple([0, 1, 2])
            document_controller.periodic()
            data_panel._list_canvas_item.handle_delete()
            self.assertEqual(0, len(document_model.data_items))

    # make sure switching between two views containing data items from the same group
    # switch between those data items in the data panel when switching.
    def test_selected_data_item_persistence(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            parent_data_group = DataGroup.DataGroup()
            parent_data_group.title = "parent_data_group"
            data_group = DataGroup.DataGroup()
            data_group.title = "data_group"
            document_model.append_data_group(data_group)
            document_model.append_data_group(parent_data_group)
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "data_item1"
            document_model.append_data_item(data_item1)
            data_group.append_display_item(document_model.get_display_item_for_data_item(data_item1))
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2.title = "data_item2"
            document_model.append_data_item(data_item2)
            data_group.append_display_item(document_model.get_display_item_for_data_item(data_item2))
            data_panel = document_controller.find_dock_panel("data-panel")
            project_panel = document_controller.find_dock_panel("collections-panel")
            self.assertSetEqual({0}, project_panel._collection_selection.indexes)
            self.assertSetEqual(set(), document_controller.selection.indexes)
            document_controller.select_data_group_in_data_panel(data_group=data_group, data_item=data_item1)
            self.assertSetEqual({4}, project_panel._collection_selection.indexes)
            self.assertSetEqual({0}, document_controller.selection.indexes)
            document_controller.select_data_group_in_data_panel(data_group=data_group, data_item=data_item2)
            self.assertSetEqual({4}, project_panel._collection_selection.indexes)
            self.assertSetEqual({1}, document_controller.selection.indexes)
            document_controller.select_data_group_in_data_panel(data_group=data_group, data_item=data_item1)
            self.assertSetEqual({4}, project_panel._collection_selection.indexes)
            self.assertSetEqual({0}, document_controller.selection.indexes)

    # make sure switching between two data items in different groups works
    # then make sure the same group is selected if the data item is in multiple groups
    def test_selected_group_persistence(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            # create data_item2 earlier than data_item1 so they sort to match old test setup
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2.title = "Data 2"
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "Data 1"
            parent_data_group = DataGroup.DataGroup()
            parent_data_group.title = "parent_data_group"
            data_group1 = DataGroup.DataGroup()
            data_group1.title = "Group 1"
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_group1.append_display_item(display_item1)
            data_group2 = DataGroup.DataGroup()
            data_group2.title = "Group 2"
            document_model.append_data_item(data_item2)
            data_group2.append_display_item(document_model.get_display_item_for_data_item(data_item2))
            document_model.append_data_group(parent_data_group)
            document_model.append_data_group(data_group1)
            document_model.append_data_group(data_group2)
            data_panel = document_controller.find_dock_panel("data-panel")
            project_panel = document_controller.find_dock_panel("collections-panel")
            data_panel.focused = True
            self.assertSetEqual({0}, project_panel._collection_selection.indexes)
            self.assertEqual(document_controller.selection.indexes, set())
            document_controller.select_data_group_in_data_panel(data_group=data_group1, data_item=data_item1)
            self.assertSetEqual({5}, project_panel._collection_selection.indexes)
            self.assertSetEqual({0}, document_controller.selection.indexes)
            document_controller.select_data_group_in_data_panel(data_group=data_group2, data_item=data_item2)
            self.assertSetEqual({6}, project_panel._collection_selection.indexes)
            self.assertSetEqual({0}, document_controller.selection.indexes)
            document_controller.select_data_group_in_data_panel(data_group=data_group1, data_item=data_item1)
            self.assertSetEqual({5}, project_panel._collection_selection.indexes)
            self.assertSetEqual({0}, document_controller.selection.indexes)
            # now make sure if a data item is in multiple groups, the right one is selected
            data_group2.append_display_item(display_item1)
            document_controller.select_data_group_in_data_panel(data_group=data_group2, data_item=data_item2)
            document_controller.selection.set(1)
            document_controller.select_data_group_in_data_panel(data_group=data_group1, data_item=data_item1)
            document_controller.selection.set(0)
            self.assertEqual(document_controller.selected_data_item, data_item1)
            self.assertSetEqual({5}, project_panel._collection_selection.indexes)
            self.assertSetEqual({0}, document_controller.selection.indexes)
            document_controller.select_data_group_in_data_panel(data_group=data_group2, data_item=data_item1)
            self.assertSetEqual({6}, project_panel._collection_selection.indexes)
            self.assertSetEqual({1}, document_controller.selection.indexes)
            document_controller.select_data_group_in_data_panel(data_group=data_group1, data_item=data_item1)
            self.assertEqual(document_controller.selected_data_item, data_item1)
            self.assertSetEqual({5}, project_panel._collection_selection.indexes)
            self.assertSetEqual({0}, document_controller.selection.indexes)
            # now make sure group selections are preserved
            document_controller.select_data_group_in_data_panel(data_group=data_group1, data_item=data_item1)
            document_controller.selection.clear()  # data_group1 now has no data item selected
            self.assertIsNone(document_controller.selected_data_item)
            self.assertSetEqual({5}, project_panel._collection_selection.indexes)
            self.assertSetEqual(set(), document_controller.selection.indexes)
            document_controller.select_data_group_in_data_panel(data_group=data_group2, data_item=data_item1)
            self.assertSetEqual({6}, project_panel._collection_selection.indexes)
            self.assertSetEqual({1}, document_controller.selection.indexes)
            document_controller.select_data_group_in_data_panel(data_group=data_group2)
            self.assertIsNone(document_controller.selected_data_item)
            self.assertSetEqual({6}, project_panel._collection_selection.indexes)
            self.assertSetEqual(set(), document_controller.selection.indexes)
            # make sure root level is handled ok
            document_controller.select_data_group_in_data_panel(data_group=data_group2, data_item=data_item1)
            self.assertSetEqual({6}, project_panel._collection_selection.indexes)
            self.assertSetEqual({1}, document_controller.selection.indexes)

    def test_data_panel_updates_focused_data_item_when_single_item_selected_when_focused(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((2, 2))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((2, 2))))
            data_panel = document_controller.find_dock_panel("data-panel")
            data_panel.focused = True
            document_controller.select_data_item_in_data_panel(document_model.data_items[0])
            self.assertEqual(document_model.data_items[0], document_controller.selected_data_item)
            document_controller.select_data_item_in_data_panel(document_model.data_items[1])
            self.assertEqual(document_model.data_items[1], document_controller.selected_data_item)

    def test_data_panel_clears_selected_data_item_when_multiple_items_selected_when_focused(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((2, 2))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((2, 2))))
            data_panel = document_controller.find_dock_panel("data-panel")
            data_panel.focused = True
            document_controller.select_data_item_in_data_panel(document_model.data_items[0])
            self.assertEqual(document_model.data_items[0], document_controller.selected_data_item)
            document_controller.select_data_items_in_data_panel(document_model.data_items)
            self.assertEqual(None, document_controller.selected_data_item)

    def test_data_panel_clears_selected_data_item_when_clearing_selection_when_focused(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((2, 2))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((2, 2))))
            data_panel = document_controller.find_dock_panel("data-panel")
            data_panel.focused = True
            document_controller.select_data_item_in_data_panel(document_model.data_items[0])
            self.assertEqual(document_model.data_items[0], document_controller.selected_data_item)
            document_controller.select_data_items_in_data_panel([])
            self.assertEqual(None, document_controller.selected_data_item)

    def test_selection_during_operations(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            # data_item1
            #   inverted
            # data_item2
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "data_item1"
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2.title = "data_item2"
            document_model.append_data_item(data_item2)
            # finished setting up
            data_panel = document_controller.find_dock_panel("data-panel")
            data_panel.focused = True
            document_controller.select_data_item_in_data_panel(data_item=data_item1)
            # make sure our preconditions are right
            self.assertEqual(document_controller.selected_data_item, data_item1)
            self.assertEqual(len(document_model.get_dependent_data_items(data_item1)), 0)
            # add processing and make sure it appeared
            self.assertEqual(document_controller.selected_data_item, data_item1)
            inverted_data_item = document_controller.processing_invert().data_item
            self.assertEqual(len(document_model.get_dependent_data_items(data_item1)), 1)
            # now make sure data panel shows it as selected
            self.assertEqual(document_controller.selected_data_item, inverted_data_item)
            # switch away and back and make sure selection is still correct
            document_controller.select_data_item_in_data_panel(data_item=data_item2)
            document_controller.select_data_item_in_data_panel(data_item=inverted_data_item)
            self.assertEqual(document_controller.selected_data_item, inverted_data_item)

    def test_existing_item_gets_initially_added_to_binding_data_items(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_group = DataGroup.DataGroup()
            data_group.title = "data_group"
            document_controller.document_model.append_data_group(data_group)
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "data_item1"
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_group.append_display_item(display_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2.title = "data_item2"
            document_model.append_data_item(data_item2)
            data_group.append_display_item(document_model.get_display_item_for_data_item(data_item2))
            filtered_display_items = ListModel.FilteredListModel(items_key="display_items")
            filtered_display_items.container = data_group
            self.assertTrue(display_item1 in filtered_display_items.items)
            data_panel = document_controller.find_dock_panel("data-panel")
            document_controller.select_data_group_in_data_panel(data_group=data_group, data_item=data_item1)
            filtered_display_items.close()
            filtered_display_items = None

    def test_data_group_data_items_model_should_close_nicely(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_group = DataGroup.DataGroup()
            data_group.title = "data_group"
            document_controller.document_model.append_data_group(data_group)
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "data_item1"
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_group.append_display_item(display_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2.title = "data_item2"
            document_model.append_data_item(data_item2)
            data_group.append_display_item(document_model.get_display_item_for_data_item(data_item2))
            filtered_display_items = ListModel.FilteredListModel(items_key="display_items")
            filtered_display_items.container = data_group
            self.assertTrue(display_item1 in filtered_display_items.items)
            filtered_display_items.close()
            filtered_display_items = None

    def test_data_group_data_items_model_should_replace_data_group_with_itself_without_failing(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_group = DataGroup.DataGroup()
            data_group.title = "data_group"
            document_controller.document_model.append_data_group(data_group)
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "data_item1"
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_group.append_display_item(display_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2.title = "data_item2"
            document_model.append_data_item(data_item2)
            data_group.append_display_item(document_model.get_display_item_for_data_item(data_item2))
            filtered_display_items = ListModel.FilteredListModel(items_key="display_items")
            filtered_display_items.container = data_group
            filtered_display_items.container = data_group
            self.assertTrue(display_item1 in filtered_display_items.items)
            filtered_display_items.close()
            filtered_display_items = None

    def test_add_remove_sync(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            # create data group
            data_group = DataGroup.DataGroup()
            data_group.title = "data_group"
            document_controller.document_model.append_data_group(data_group)
            # put three data items in data group
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item1)
            data_item1.title = "data_item1"
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_group.append_display_item(display_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item2)
            data_item2.title = "data_item2"
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            data_group.append_display_item(display_item2)
            data_item3 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item3)
            display_item3 = document_model.get_display_item_for_data_item(data_item3)
            data_item3.title = "data_item3"
            data_group.append_display_item(document_model.get_display_item_for_data_item(data_item3))
            # set up the data panel
            data_panel = document_controller.find_dock_panel("data-panel")
            document_controller.select_data_group_in_data_panel(data_group=data_group, data_item=data_item2)
            document_controller.periodic()
            data_panel.periodic()
            # verify assumptions
            self.assertEqual(data_panel._list_canvas_item.canvas_items_count, 3)
            # delete 2nd item
            data_group.remove_display_item(data_group.display_items[1])
            document_controller.periodic()
            data_panel.periodic()
            self.assertEqual(data_panel._list_canvas_item.canvas_items_count, 2)
            self.assertEqual(data_panel._list_canvas_item.canvas_items[0]._canvas_item.title, str(display_item1.title))
            self.assertEqual(data_panel._list_canvas_item.canvas_items[1]._canvas_item.title, str(display_item3.title))
            # insert new item
            data_item4 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item4)
            display_item4 = document_model.get_display_item_for_data_item(data_item4)
            data_item4.title = "data_item4"
            data_group.insert_display_item(1, document_model.get_display_item_for_data_item(data_item4))
            document_controller.periodic()
            data_panel.periodic()
            self.assertEqual(data_panel._list_canvas_item.canvas_items_count, 3)
            self.assertEqual(data_panel._list_canvas_item.canvas_items[0]._canvas_item.title, str(display_item1.title))
            self.assertEqual(data_panel._list_canvas_item.canvas_items[1]._canvas_item.title, str(display_item4.title))
            self.assertEqual(data_panel._list_canvas_item.canvas_items[2]._canvas_item.title, str(display_item3.title))

    def test_select_after_receive_files(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item.title = "data_item"
            document_model.append_data_item(data_item)
            data_panel = document_controller.find_dock_panel("data-panel")
            data_panel.focused = True
            self.assertIsNone(document_controller.selected_display_item)
            document_controller.receive_files([pathlib.Path(":/app/scroll_gem.png")], index=0)
            document_controller.periodic()
            self.assertEqual(document_controller.selected_display_item, document_model.display_items[1])

    def test_setting_data_browser_selection_to_multiple_items_via_document_controller_updates_selection_object(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_controller.select_data_items_in_data_panel(document_model.data_items[:-1])
            self.assertEqual({1, 2}, document_controller.selection.indexes)  # items are ordered newest to oldest

    def test_data_panel_remove_group(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_group1 = DataGroup.DataGroup()
            data_group1.title = "data_group1"
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "Green 1"
            document_model.append_data_item(data_item1)
            data_group1.append_display_item(document_model.get_display_item_for_data_item(data_item1))
            document_controller.document_model.append_data_group(data_group1)
            green_group = DataGroup.DataGroup()
            green_group.title = "green_group"
            green_group.append_display_item(document_model.get_display_item_for_data_item(data_item1))
            document_controller.document_model.insert_data_group(0, green_group)
            self.assertEqual(len(green_group.display_items), 1)
            data_panel = document_controller.find_dock_panel("data-panel")
            document_controller.remove_data_group_from_container(document_controller.document_model.data_groups[0], document_controller.document_model._project)

    def test_data_panel_remove_item_by_key(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_group1 = DataGroup.DataGroup()
            data_group1.title = "data_group1"
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "Green 1"
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_group1.append_display_item(display_item1)
            green_group = DataGroup.DataGroup()
            green_group.title = "green_group"
            green_group.append_display_item(display_item1)
            document_controller.document_model.insert_data_group(0, green_group)
            document_controller.document_model.append_data_group(data_group1)
            data_panel = document_controller.find_dock_panel("data-panel")
            document_controller.select_data_group_in_data_panel(data_group=data_group1, data_item=data_item1)
            self.assertTrue(display_item1 in data_group1.display_items)
            document_controller.selection.set(0)
            data_panel._list_canvas_item.handle_delete()
            self.assertFalse(display_item1 in data_group1.display_items)

    def test_remove_item_should_remove_children_when_both_parent_and_child_are_selected(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "data_item1"
            document_model.append_data_item(data_item1)
            data_item1a = DataItem.DataItem()
            data_item1a.title = "data_item1a"
            document_model.append_data_item(data_item1a)
            data_panel = document_controller.find_dock_panel("data-panel")
            document_controller.periodic()
            document_controller.selection.set_multiple([0, 1])
            data_panel._list_canvas_item.handle_delete()

    def test_data_panel_should_save_and_restore_state_when_no_data_group_is_selected(self):
        # TODO: implement data panel save/restore test
        self.assertTrue(True)

    def test_data_items_are_inserted_correctly_when_switching_from_none_to_all_selected(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            for i in range(3):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
            data_panel = document_controller.find_dock_panel("data-panel")
            project_panel = document_controller.find_dock_panel("collections-panel")
            project_panel._collection_selection.set(2)
            project_panel._collection_selection.set(1)

    def test_display_filter_filters_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            for i in range(3):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                data_item.title = "X" if i != 1 else "Y"
                document_model.append_data_item(data_item)
            data_panel = document_controller.find_dock_panel("data-panel")
            document_controller.periodic()  # changes to filter will be queued. update that here.
            self.assertEqual(len(document_controller.filtered_display_items_model.items), 3)
            document_controller.display_filter = ListModel.TextFilter("title", "Y")
            document_controller.periodic()  # changes to filter will be queued. update that here.
            self.assertEqual(len(document_controller.filtered_display_items_model.items), 1)

    def test_changing_display_limits_causes_display_changed_message(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # necessary to make the thumbnails update in the data panel
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_changed_ref = [False]
            def display_changed():
                display_changed_ref[0] = True
            with contextlib.closing(display_item.display_changed_event.listen(display_changed)):
                display_item.display_data_channels[0].display_limits = (0.25, 0.75)
                self.assertTrue(display_changed_ref[0])

    def test_change_from_group_with_selected_items_to_group_with_no_items_updates_data_items_correctly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            # create two data groups
            data_group1 = DataGroup.DataGroup()
            data_group1.title = "data_group1"
            document_model.append_data_group(data_group1)
            data_group2 = DataGroup.DataGroup()
            data_group2.title = "data_group1"
            document_model.append_data_group(data_group2)
            # add items to data group 1
            data_item1a = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1a.title = "data_item1a"
            document_model.append_data_item(data_item1a)
            data_group1.append_display_item(document_model.get_display_item_for_data_item(data_item1a))
            data_item1b = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1b.title = "data_item1a"
            document_model.append_data_item(data_item1b)
            data_group1.append_display_item(document_model.get_display_item_for_data_item(data_item1b))
            # now select the first group in the data panel
            document_controller.select_data_group_in_data_panel(data_group=data_group1)
            data_panel = document_controller.find_dock_panel("data-panel")
            document_controller.selection.set_multiple([0, 1])
            document_controller.select_data_group_in_data_panel(data_group=data_group2)

    def test_change_from_group_with_selected_items_to_all_updates_data_items_correctly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            # create two data groups
            data_group1 = DataGroup.DataGroup()
            data_group1.title = "data_group1"
            document_model.append_data_group(data_group1)
            # add items to data group 1
            data_item1a = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1a.title = "data_item1a"
            document_model.append_data_item(data_item1a)
            data_group1.append_display_item(document_model.get_display_item_for_data_item(data_item1a))
            data_item1b = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1b.title = "data_item1a"
            document_model.append_data_item(data_item1b)
            # now select the first group in the data panel
            document_controller.select_data_group_in_data_panel(data_group=data_group1)
            self.assertEqual(len(document_controller.filtered_display_items_model.items), 1)
            document_controller.set_filter(filter_id="all")
            self.assertEqual(len(document_controller.filtered_display_items_model.items), 2)

    def test_change_from_filter_to_group_and_back_and_forth_updates_without_recursion(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            # create two data groups
            data_group1 = DataGroup.DataGroup()
            data_group1.title = "data_group1"
            document_model.append_data_group(data_group1)
            data_group2 = DataGroup.DataGroup()
            data_group2.title = "data_group1"
            document_model.append_data_group(data_group2)
            # now select the first group in the data panel
            document_controller.set_filter(filter_id="all")
            document_controller.select_data_group_in_data_panel(data_group=data_group2)

    def test_data_panel_list_contents_resize_properly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            data_panel = document_controller.find_dock_panel("data-panel")
            width = 320
            data_panel._data_list_widget.canvas_item.layout_immediate(Geometry.IntSize(width=width, height=148))
            self.assertEqual(width - 16, data_panel._scroll_area_canvas_item.canvas_bounds.width)
            self.assertEqual(width - 16, data_panel._scroll_area_canvas_item.content.canvas_bounds.width)
            width = 344
            data_panel._data_list_widget.canvas_item.layout_immediate(Geometry.IntSize(width=width, height=148))
            self.assertEqual(width - 16, data_panel._scroll_area_canvas_item.canvas_bounds.width)
            self.assertEqual(width - 16, data_panel._scroll_area_canvas_item.content.canvas_bounds.width)

    def test_data_panel_scroll_bar_works_properly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            for _ in range(10):
                document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32)))
            document_controller.periodic()
            data_panel = document_controller.find_dock_panel("data-panel")
            data_panel._data_list_widget.canvas_item.layout_immediate(Geometry.IntSize(width=320, height=160))
            self.assertEqual(data_panel._scroll_area_canvas_item.content_origin, Geometry.IntPoint(0, 0))
            self.assertEqual(data_panel._scroll_area_canvas_item.content_size, Geometry.IntSize(800, 304))
            data_panel._scroll_bar_canvas_item.simulate_drag((8, 8), (24, 8))
            self.assertEqual(data_panel._scroll_area_canvas_item.content_origin, Geometry.IntPoint(-80, 0))
            self.assertEqual(data_panel._scroll_area_canvas_item.content_size, Geometry.IntSize(800, 304))

    def test_data_panel_grid_contents_resize_properly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_panel = document_controller.find_dock_panel("data-panel")
            width = 320
            data_panel._data_grid_widget.content_widget.children[0].canvas_item.layout_immediate(Geometry.IntSize(width=width, height=148))
            self.assertEqual(width - 16, data_panel.data_grid_controller.scroll_area_canvas_item.canvas_bounds.width)
            self.assertEqual(width - 16, data_panel.data_grid_controller.scroll_area_canvas_item.content.canvas_bounds.width)
            width = 344
            data_panel._data_grid_widget.content_widget.children[0].canvas_item.layout_immediate(Geometry.IntSize(width=width, height=148))
            self.assertEqual(width - 16, data_panel.data_grid_controller.scroll_area_canvas_item.canvas_bounds.width)
            self.assertEqual(width - 16, data_panel.data_grid_controller.scroll_area_canvas_item.content.canvas_bounds.width)

    def test_switching_to_temporary_group_displays_temporary_items(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.zeros((4, 4)))
            data_item2 = DataItem.DataItem(numpy.zeros((4, 4)))
            data_item2.category = "temporary"
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            data_panel = document_controller.find_dock_panel("data-panel")
            project_panel = document_controller.find_dock_panel("collections-panel")
            project_panel._collection_selection.set(1)  # persistent
            document_controller.periodic()
            self.assertEqual(1, data_panel._list_canvas_item.canvas_items_count)
            self.assertEqual(data_panel._list_canvas_item.canvas_items[0]._canvas_item.display_item.data_item, data_item1)
            project_panel._collection_selection.set(2)  # temporary
            document_controller.periodic()
            self.assertEqual(1, data_panel._list_canvas_item.canvas_items_count)
            self.assertEqual(data_panel._list_canvas_item.canvas_items[0]._canvas_item.display_item.data_item, data_item2)

    def test_processing_temporary_data_item_keeps_temporary_items_displayed(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.zeros((4, 4)))
            data_item1.category = "temporary"
            data_item2 = DataItem.DataItem(numpy.zeros((4, 4)))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_panel = document_controller.find_dock_panel("data-panel")
            project_panel = document_controller.find_dock_panel("collections-panel")
            # index, parent_row, parent_id
            project_panel._collection_selection.set(2)
            document_controller.periodic()
            document_controller.selected_display_panel.set_display_panel_display_item(display_item1)
            self.assertEqual(data_panel._list_canvas_item.canvas_items_count, 1)
            self.assertEqual(data_panel._list_canvas_item.canvas_items[0]._canvas_item.display_item.data_item, data_item1)
            data_item3 = document_model.get_invert_new(display_item1, display_item1.data_item)
            document_model.recompute_all()
            document_controller.periodic()
            self.assertEqual(data_panel._list_canvas_item.canvas_items_count, 2)
            self.assertEqual(data_panel._list_canvas_item.canvas_items[0]._canvas_item.display_item.data_item, data_item3)
            self.assertEqual(data_panel._list_canvas_item.canvas_items[1]._canvas_item.display_item.data_item, data_item1)

    def test_switching_to_latest_session_group_displays_latest_session(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.zeros((4, 4)))
            data_item2 = DataItem.DataItem(numpy.zeros((4, 4)))
            data_item3 = DataItem.DataItem(numpy.zeros((4, 4)))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            data_item1.session_id = document_model.session_id
            data_item2.session_id = "20170101-120000"
            data_item3.session_id = "20170101-120000"
            data_panel = document_controller.find_dock_panel("data-panel")
            project_panel = document_controller.find_dock_panel("collections-panel")
            # index, parent_row, parent_id
            project_panel._collection_selection.set(1)
            document_controller.periodic()
            self.assertEqual(data_panel._list_canvas_item.canvas_items_count, 3)
            list_data_items = [list_item_canvas_item._canvas_item.display_item.data_item for list_item_canvas_item in data_panel._list_canvas_item.canvas_items]
            self.assertIn(data_item1, list_data_items)
            self.assertIn(data_item2, list_data_items)
            self.assertIn(data_item3, list_data_items)
            project_panel._collection_selection.set(3)
            document_controller.periodic()
            self.assertEqual(data_panel._list_canvas_item.canvas_items_count, 1)
            list_data_items = [list_item_canvas_item._canvas_item.display_item.data_item for list_item_canvas_item in data_panel._list_canvas_item.canvas_items]
            self.assertIn(data_item1, list_data_items)

    def test_switching_from_latest_group_to_all_group_displays_all(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.zeros((4, 4)))
            data_item2 = DataItem.DataItem(numpy.zeros((4, 4)))
            data_item3 = DataItem.DataItem(numpy.zeros((4, 4)))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            data_item1.session_id = document_model.session_id
            data_item2.session_id = "20170101-120000"
            data_item3.session_id = "20170101-120000"
            data_panel = document_controller.find_dock_panel("data-panel")
            project_panel = document_controller.find_dock_panel("collections-panel")
            # index, parent_row, parent_id
            project_panel._collection_selection.set(1)
            document_controller.periodic()
            self.assertEqual(data_panel._list_canvas_item.canvas_items_count, 3)
            project_panel._collection_selection.set(3)
            document_controller.periodic()
            self.assertEqual(data_panel._list_canvas_item.canvas_items_count, 1)
            project_panel._collection_selection.set(1)
            document_controller.periodic()
            self.assertEqual(data_panel._list_canvas_item.canvas_items_count, 3)

    def test_new_display_panel_does_not_change_the_filter(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((4, 4))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((4, 4))))
            data_panel = document_controller.find_dock_panel("data-panel")
            project_panel = document_controller.find_dock_panel("collections-panel")
            document_controller.periodic()
            # select temporary items
            project_panel._collection_selection.set(2)
            document_controller.periodic()
            # check assumptions, temporary group selected
            self.assertEqual(data_panel._list_canvas_item.canvas_items_count, 0)
            self.assertSetEqual({2}, project_panel._collection_selection.indexes)
            # create display panel
            data_panel = document_controller.find_dock_panel("data-panel")
            display_panel = DisplayPanel.DisplayPanel(document_controller, dict())
            with contextlib.closing(display_panel):
                document_controller.selected_display_panel = display_panel
                # create a temporary data item
                data_item = DataItem.DataItem(numpy.zeros((4, 4)))
                data_item.category = "temporary"
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_panel.set_display_panel_display_item(display_item)
                # check that changing display updates to the one temporary data item in the data panel
                self.assertEqual(data_panel._list_canvas_item.canvas_items_count, 1)
                self.assertSetEqual({2}, project_panel._collection_selection.indexes)

    def test_data_item_starts_drag_with_data_item_mime_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((4, 4)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_panel = document_controller.find_dock_panel("data-panel")
            project_panel = document_controller.find_dock_panel("collections-panel")
            # index, parent_row, parent_id
            project_panel._collection_selection.set(1)
            document_controller.periodic()
            document_controller.selected_display_panel.set_display_panel_display_item(display_item)
            mime_data, thumbnail = data_panel._list_canvas_item._delegate._get_mime_data_and_thumbnail_data(ListCanvasItem.ListCanvasItem2DragStartedEvent(display_item, [display_item], Geometry.IntPoint(), CanvasItem.KeyboardModifiers()))
            self.assertTrue(mime_data.has_format(MimeTypes.DISPLAY_ITEM_MIME_TYPE))

    def test_changing_filter_validates_data_browser_selection(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((16, 16))))
            document_controller.select_data_items_in_data_panel(document_model.data_items[1:])
            self.assertEqual({0, 1}, document_controller.selection.indexes)  # items are ordered newest to oldest
            document_controller.set_filter(filter_id="none")
            self.assertEqual(list(), document_controller.selected_display_items)
            self.assertEqual(set(), document_controller.selection.indexes)  # items are ordered newest to oldest

    def test_collections_filter_is_persistent(self):
        with TestContext.MemoryProfileContext() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_group = DataGroup.DataGroup()
                document_model.append_data_group(data_group)
                data_item = DataItem.DataItem(numpy.zeros((256, 256)))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                data_group.append_display_item(display_item)
                document_controller.set_data_group(data_group)
                document_controller.set_filter(filter_id="persistent")
            document_controller = profile_context.create_document_controller(auto_close=False)
            with contextlib.closing(document_controller):
                self.assertEqual((None, "persistent"), document_controller.get_data_group_and_filter_id())

    def test_collections_data_group_is_persistent(self):
        with TestContext.MemoryProfileContext() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_group = DataGroup.DataGroup()
                document_model.append_data_group(data_group)
                data_item = DataItem.DataItem(numpy.zeros((256, 256)))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                data_group.append_display_item(display_item)
                document_controller.set_filter(filter_id="persistent")
                document_controller.set_data_group(data_group)
            document_controller = profile_context.create_document_controller(auto_close=False)
            with contextlib.closing(document_controller):
                data_group = document_controller.document_model.data_groups[0]
                self.assertEqual((data_group, None), document_controller.get_data_group_and_filter_id())


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
