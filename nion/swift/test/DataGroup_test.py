# futures
from __future__ import absolute_import

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

    def test_inserting_item_with_existing_data_source_establishes_connection(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model)
        with contextlib.closing(document_controller):
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item2)  # add this first
            data_item2a = document_model.get_resample_new(data_item2)
            # verify
            self.assertEqual(document_model.get_source_data_items(data_item2a)[0], data_item2)

    def test_removing_data_item_with_dependent_data_item_removes_them_both(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model)
        with contextlib.closing(document_controller):
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item2)
            document_model.get_resample_new(data_item2)
            # verify assumptions
            self.assertEqual(len(document_model.data_items), 2)
            # remove root
            document_model.remove_data_item(data_item2)
            # verify it and its dependent are gone
            self.assertEqual(len(document_model.data_items), 0)

    def test_deleting_document_with_dependent_data_items_works(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            data_item_child = DataItem.DataItem()
            document_model.append_data_item(data_item_child)

if __name__ == '__main__':
    unittest.main()
