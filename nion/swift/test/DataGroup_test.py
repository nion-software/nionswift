# standard libraries
import contextlib
import copy
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.ui import TestUI


class TestDataGroupClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_deep_copy_should_deep_copy_child_data_groups(self):
        data_group = DataGroup.DataGroup()
        data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        data_group.append_data_item(data_item1)
        data_group2 = DataGroup.DataGroup()
        data_group.append_data_group(data_group2)
        # attempt to copy
        data_group_copy = copy.deepcopy(data_group)
        # make sure data_groups are not shared
        self.assertNotEqual(data_group.data_groups[0], data_group_copy.data_groups[0])

    def test_deep_copy_should_not_deep_copy_data_items(self):
        data_group = DataGroup.DataGroup()
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        data_group.append_data_item(data_item)
        data_group_copy = copy.deepcopy(data_group)
        self.assertEqual(data_item.uuid, data_group_copy.data_item_uuids[0])

    def test_counted_data_items(self):
        # TODO: split test_counted_data_items into separate tests
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_group = DataGroup.DataGroup()
            document_model.append_data_group(data_group)
            self.assertEqual(len(data_group.counted_data_items), 0)
            self.assertEqual(len(document_model.data_items), 0)
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item1)
            data_group.append_data_item(data_item1)
            # make sure that both top level and data_group see the data item
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(len(data_group.counted_data_items), 1)
            self.assertEqual(list(document_model.data_items), list(data_group.counted_data_items))
            self.assertIn(data_item1, list(data_group.counted_data_items.keys()))
            # add a child data item and make sure top level and data_group see it
            # also check data item.
            data_item1a = document_model.get_resample_new(data_item1)
            data_group.append_data_item(data_item1a)
            self.assertEqual(len(document_model.data_items), 2)
            self.assertEqual(len(data_group.counted_data_items), 2)
            self.assertIn(data_item1, list(data_group.counted_data_items.keys()))
            self.assertIn(data_item1a, list(data_group.counted_data_items.keys()))
            # add a child data item to the child and make sure top level and data_group match.
            # also check data items.
            data_item1a1 = document_model.get_resample_new(data_item1a)
            display_specifier1a1 = DataItem.DisplaySpecifier.from_data_item(data_item1a1)
            data_group.append_data_item(data_item1a1)
            self.assertEqual(len(document_model.data_items), 3)
            self.assertEqual(len(data_group.counted_data_items), 3)
            self.assertIn(data_item1, list(data_group.counted_data_items.keys()))
            self.assertIn(data_item1a, list(data_group.counted_data_items.keys()))
            self.assertIn(data_item1a1, list(data_group.counted_data_items.keys()))
            # now add a data item that already has children
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item2)
            data_item2a = document_model.get_resample_new(data_item2)
            data_group.append_data_item(data_item2)
            data_group.append_data_item(data_item2a)
            self.assertEqual(len(document_model.data_items), 5)
            self.assertEqual(len(data_group.counted_data_items), 5)
            self.assertIn(data_item2a, document_model.data_items)
            self.assertIn(data_item2a, list(data_group.counted_data_items.keys()))
            # remove data item without children
            document_model.remove_data_item(data_item1a1)
            self.assertEqual(len(document_model.data_items), 4)
            self.assertEqual(len(data_group.counted_data_items), 4)
            # now remove data item with children
            document_model.remove_data_item(data_item2)
            self.assertEqual(len(document_model.data_items), 2)
            self.assertEqual(len(data_group.counted_data_items), 2)

    def test_deleting_data_item_removes_it_from_data_group(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.random.randn(4, 4))
            document_model.append_data_item(data_item)
            data_group = DataGroup.DataGroup()
            data_group.append_data_item(data_item)
            document_model.append_data_group(data_group)
            self.assertEqual(1, len(data_group.data_items))
            self.assertEqual(0, len(data_group.data_groups))
            document_model.remove_data_item(data_item)
            self.assertEqual(0, len(data_group.data_items))
            self.assertEqual(0, len(data_group.data_groups))

    def test_deleting_data_items_from_data_group_undo_redo(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            # setup three data items in a group
            data_item1 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item2 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item3 = DataItem.DataItem(numpy.random.randn(4, 4))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            data_group = DataGroup.DataGroup()
            data_group.append_data_item(data_item1)
            data_group.append_data_item(data_item2)
            data_group.append_data_item(data_item3)
            document_model.append_data_group(data_group)
            # remove two of the three
            command = DocumentController.DocumentController.RemoveDataGroupLibraryItemsCommand(document_model, data_group, [data_item1, data_item3])
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(1, len(data_group.data_items))
            self.assertEqual(0, len(data_group.data_groups))
            self.assertEqual(data_item2, data_group.data_items[0])
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(3, len(data_group.data_items))
            self.assertEqual(0, len(data_group.data_groups))
            self.assertEqual(data_item1, data_group.data_items[0])
            self.assertEqual(data_item2, data_group.data_items[1])
            self.assertEqual(data_item3, data_group.data_items[2])
            # redo and check
            document_controller.handle_redo()
            self.assertEqual(1, len(data_group.data_items))
            self.assertEqual(0, len(data_group.data_groups))
            self.assertEqual(data_item2, data_group.data_items[0])

    def test_deleting_data_items_out_of_order_from_data_group_undo_redo(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            # setup three data items in a group
            data_item1 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item2 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item3 = DataItem.DataItem(numpy.random.randn(4, 4))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            data_group = DataGroup.DataGroup()
            data_group.append_data_item(data_item1)
            data_group.append_data_item(data_item2)
            data_group.append_data_item(data_item3)
            document_model.append_data_group(data_group)
            # remove two of the three
            command = DocumentController.DocumentController.RemoveDataGroupLibraryItemsCommand(document_model, data_group, [data_item3, data_item1])
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(1, len(data_group.data_items))
            self.assertEqual(0, len(data_group.data_groups))
            self.assertEqual(data_item2, data_group.data_items[0])
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(3, len(data_group.data_items))
            self.assertEqual(0, len(data_group.data_groups))
            self.assertEqual(data_item1, data_group.data_items[0])
            self.assertEqual(data_item2, data_group.data_items[1])
            self.assertEqual(data_item3, data_group.data_items[2])
            # redo and check
            document_controller.handle_redo()
            self.assertEqual(1, len(data_group.data_items))
            self.assertEqual(0, len(data_group.data_groups))
            self.assertEqual(data_item2, data_group.data_items[0])

    def test_insert_data_item_into_data_group_undo_redo(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            # setup three data items and put two in a group
            data_item1 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item2 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item3 = DataItem.DataItem(numpy.random.randn(4, 4))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            data_group = DataGroup.DataGroup()
            data_group.append_data_item(data_item1)
            data_group.append_data_item(data_item3)
            document_model.append_data_group(data_group)
            # insert a new one
            command = document_controller.create_insert_data_group_library_item_command(data_group, 1, data_item2)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(3, len(data_group.data_items))
            self.assertEqual(0, len(data_group.data_groups))
            self.assertEqual(data_item1, data_group.data_items[0])
            self.assertEqual(data_item2, data_group.data_items[1])
            self.assertEqual(data_item3, data_group.data_items[2])
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(2, len(data_group.data_items))
            self.assertEqual(0, len(data_group.data_groups))
            self.assertEqual(data_item1, data_group.data_items[0])
            self.assertEqual(data_item3, data_group.data_items[1])
            # redo and check
            document_controller.handle_redo()
            self.assertEqual(3, len(data_group.data_items))
            self.assertEqual(0, len(data_group.data_groups))
            self.assertEqual(data_item1, data_group.data_items[0])
            self.assertEqual(data_item2, data_group.data_items[1])
            self.assertEqual(data_item3, data_group.data_items[2])

    def test_insert_data_group_undo_redo(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            # setup three data items and put two in a group
            data_item1 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item3 = DataItem.DataItem(numpy.random.randn(4, 4))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item3)
            data_group1 = DataGroup.DataGroup()
            data_group1.append_data_item(data_item1)
            data_group2 = DataGroup.DataGroup()
            data_group3 = DataGroup.DataGroup()
            data_group2_uuid = data_group2.uuid
            data_group3.append_data_item(data_item3)
            document_model.append_data_group(data_group1)
            document_model.append_data_group(data_group3)
            # insert the middle data group
            command = DocumentController.DocumentController.InsertDataGroupCommand(document_model, document_model, 1, data_group2)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(3, len(document_model.data_groups))
            self.assertEqual(data_group1, document_model.data_groups[0])
            self.assertEqual(data_group3, document_model.data_groups[2])
            self.assertEqual(data_group2_uuid, document_model.data_groups[1].uuid)
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(2, len(document_model.data_groups))
            self.assertEqual(data_group1, document_model.data_groups[0])
            self.assertEqual(data_group3, document_model.data_groups[1])
            # redo and check
            document_controller.handle_redo()
            self.assertEqual(3, len(document_model.data_groups))
            self.assertEqual(data_group1, document_model.data_groups[0])
            self.assertEqual(data_group3, document_model.data_groups[2])
            self.assertEqual(data_group2_uuid, document_model.data_groups[1].uuid)

    def test_remove_data_group_undo_redo(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            # setup three data items and put two in a group
            data_item1 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item3 = DataItem.DataItem(numpy.random.randn(4, 4))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item3)
            data_group1 = DataGroup.DataGroup()
            data_group1.append_data_item(data_item1)
            data_group2 = DataGroup.DataGroup()
            data_group3 = DataGroup.DataGroup()
            data_group2_uuid = data_group2.uuid
            data_group3.append_data_item(data_item3)
            document_model.append_data_group(data_group1)
            document_model.append_data_group(data_group2)
            document_model.append_data_group(data_group3)
            # remove the middle data group
            command = DocumentController.DocumentController.RemoveDataGroupCommand(document_model, document_model, data_group2)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(2, len(document_model.data_groups))
            self.assertEqual(data_group1, document_model.data_groups[0])
            self.assertEqual(data_group3, document_model.data_groups[1])
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(3, len(document_model.data_groups))
            self.assertEqual(data_group1, document_model.data_groups[0])
            self.assertEqual(data_group3, document_model.data_groups[2])
            self.assertEqual(data_group2_uuid, document_model.data_groups[1].uuid)
            # redo and check
            document_controller.handle_redo()
            self.assertEqual(2, len(document_model.data_groups))
            self.assertEqual(data_group1, document_model.data_groups[0])
            self.assertEqual(data_group3, document_model.data_groups[1])

    def test_data_group_rename_undo_redo(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            # setup data group
            data_group = DataGroup.DataGroup()
            data_group.title = "ethel"
            document_model.append_data_group(data_group)
            # rename
            command = document_controller.create_rename_data_group_command(data_group, "fred")
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(data_group.title, "fred")
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(data_group.title, "ethel")
            # redo and check
            document_controller.handle_redo()
            self.assertEqual(data_group.title, "fred")

    def test_data_item_removed_implicitly_from_data_group_undo_redo(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            # setup three data items and put in a group
            data_item1 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item2 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item3 = DataItem.DataItem(numpy.random.randn(4, 4))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            data_group = DataGroup.DataGroup()
            data_group.append_data_item(data_item1)
            data_group.append_data_item(data_item2)
            data_group.append_data_item(data_item3)
            document_model.append_data_group(data_group)
            # remove the 2nd data item
            command = document_controller.create_remove_library_items_command([data_item2])
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(data_group.data_items))
            self.assertEqual(document_model.data_items[0], data_group.data_items[0])
            self.assertEqual(document_model.data_items[1], data_group.data_items[1])
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(3, len(data_group.data_items))
            self.assertEqual(document_model.data_items[0], data_group.data_items[0])
            self.assertEqual(document_model.data_items[1], data_group.data_items[1])
            self.assertEqual(document_model.data_items[2], data_group.data_items[2])
            # redo and check
            document_controller.handle_redo()
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(data_group.data_items))
            self.assertEqual(document_model.data_items[0], data_group.data_items[0])
            self.assertEqual(document_model.data_items[1], data_group.data_items[1])

    def test_inserting_items_data_group_undo_redo(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            # setup three data items and put in a group
            data_item1 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item2 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item3 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item4 = DataItem.DataItem(numpy.random.randn(4, 4))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item3)
            document_model.append_data_item(data_item4)
            data_group = DataGroup.DataGroup()
            data_group.append_data_item(data_item1)
            data_group.append_data_item(data_item3)
            document_model.append_data_group(data_group)
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(data_group.data_items))
            self.assertListEqual([data_item1, data_item3, data_item4], list(document_model.data_items))
            self.assertListEqual([data_item1, data_item3], list(data_group.data_items))
            # insert new items
            command = DocumentController.DocumentController.InsertDataGroupLibraryItemsCommand(document_controller, data_group, [data_item2, data_item4], 1)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(4, len(document_model.data_items))
            self.assertEqual(4, len(data_group.data_items))
            self.assertListEqual([data_item1, data_item3, data_item4, data_item2], list(document_model.data_items))
            self.assertListEqual([data_item1, data_item2, data_item4, data_item3], list(data_group.data_items))
            # undo and check
            document_controller.handle_undo()
            self.assertEqual(3, len(document_model.data_items))
            self.assertEqual(2, len(data_group.data_items))
            self.assertListEqual([data_item1, data_item3, data_item4], list(document_model.data_items))
            self.assertListEqual([data_item1, data_item3], list(data_group.data_items))
            # redo and check
            document_controller.handle_redo()
            data_item2 = document_model.data_items[3]
            self.assertEqual(4, len(document_model.data_items))
            self.assertEqual(4, len(data_group.data_items))
            self.assertListEqual([data_item1, data_item3, data_item4, data_item2], list(document_model.data_items))
            self.assertListEqual([data_item1, data_item2, data_item4, data_item3], list(data_group.data_items))


if __name__ == '__main__':
    unittest.main()
