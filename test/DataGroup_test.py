# standard libraries
import copy
import logging
import unittest
import weakref

# third party libraries
import numpy
import scipy

# local libraries
from nion.swift import Application
from nion.swift import DataGroup
from nion.swift import DataItem
from nion.swift import DocumentController
from nion.swift import DocumentModel
from nion.swift import Operation
from nion.swift import Storage
from nion.ui import Test



class TestDataGroupClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_deep_copy_should_deep_copy_child_data_groups(self):
        data_group = DataGroup.DataGroup()
        with data_group.ref():
            data_item1 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            data_group.append_data_item(data_item1)
            data_group2 = DataGroup.DataGroup()
            data_group.data_groups.append(data_group2)
            # attempt to copy
            data_group_copy = copy.deepcopy(data_group)
            with data_group_copy.ref():
                # make sure data_groups are not shared
                self.assertNotEqual(data_group.data_groups[0], data_group_copy.data_groups[0])

    def test_deep_copy_should_not_deep_copy_data_items(self):
        data_group = DataGroup.DataGroup()
        with data_group.ref():
            data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
            data_group.append_data_item(data_item)
            data_group_copy = copy.deepcopy(data_group)
            with data_group_copy.ref():
                self.assertEqual(data_item, data_group_copy.data_items[0])

    def test_counted_data_items(self):
        datastore = Storage.DictDatastore()
        document_model = DocumentModel.DocumentModel(datastore)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model)
        data_group = DataGroup.DataGroup()
        document_controller.document_model.data_groups.append(data_group)
        self.assertEqual(len(data_group.counted_data_items), 0)
        self.assertEqual(len(document_controller.document_model.counted_data_items), 0)
        data_item1 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item1)
        data_group.append_data_item(data_item1)
        # make sure that both top level and data_group see the data item
        self.assertEqual(len(document_controller.document_model.counted_data_items), 1)
        self.assertEqual(len(data_group.counted_data_items), 1)
        self.assertEqual(document_controller.document_model.counted_data_items, data_group.counted_data_items)
        self.assertIn(data_item1, data_group.counted_data_items.keys())
        # add a child data item and make sure top level and data_group see it
        # also check data item.
        data_item1a = DataItem.DataItem()
        operation1a = Operation.OperationItem("resample-operation")
        data_item1a.operations.append(operation1a)
        data_item1.data_items.append(data_item1a)
        self.assertEqual(len(document_controller.document_model.counted_data_items), 2)
        self.assertEqual(len(data_group.counted_data_items), 2)
        self.assertEqual(len(data_item1.counted_data_items), 1)
        self.assertIn(data_item1, data_group.counted_data_items.keys())
        self.assertIn(data_item1a, data_group.counted_data_items.keys())
        self.assertIn(data_item1a, data_item1.counted_data_items.keys())
        # add a child data item to the child and make sure top level and data_group match.
        # also check data items.
        data_item1a1 = DataItem.DataItem()
        operation1a1 = Operation.OperationItem("resample-operation")
        data_item1a1.operations.append(operation1a1)
        data_item1a.data_items.append(data_item1a1)
        data_item1a1.calculated_calibrations
        self.assertEqual(len(document_controller.document_model.counted_data_items), 3)
        self.assertEqual(len(data_group.counted_data_items), 3)
        self.assertEqual(len(data_item1.counted_data_items), 2)
        self.assertEqual(len(data_item1a.counted_data_items), 1)
        self.assertIn(data_item1, data_group.counted_data_items.keys())
        self.assertIn(data_item1a, data_group.counted_data_items.keys())
        self.assertIn(data_item1a, data_item1.counted_data_items.keys())
        self.assertIn(data_item1a1, data_group.counted_data_items.keys())
        self.assertIn(data_item1a1, data_item1a.counted_data_items.keys())
        # now add a data item that already has children
        data_item2 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item2a = DataItem.DataItem()
        operation2a = Operation.OperationItem("resample-operation")
        data_item2a.operations.append(operation2a)
        data_item2.data_items.append(data_item2a)
        self.assertEqual(len(data_item2.counted_data_items), 1)
        self.assertIn(data_item2a, data_item2.counted_data_items.keys())
        document_model.append_data_item(data_item2)
        data_group.append_data_item(data_item2)
        self.assertEqual(len(document_controller.document_model.counted_data_items), 5)
        self.assertEqual(len(data_group.counted_data_items), 5)
        self.assertEqual(len(data_item2.counted_data_items), 1)
        self.assertIn(data_item2a, document_controller.document_model.counted_data_items.keys())
        self.assertIn(data_item2a, data_group.counted_data_items.keys())
        self.assertIn(data_item2a, data_item2.counted_data_items.keys())
        # remove data item without children
        data_item1a.data_items.remove(data_item1a1)
        self.assertEqual(len(document_controller.document_model.counted_data_items), 4)
        self.assertEqual(len(data_group.counted_data_items), 4)
        self.assertEqual(len(data_item1.counted_data_items), 1)
        # now remove data item with children
        data_group.remove_data_item(data_item2)
        self.assertEqual(len(document_controller.document_model.counted_data_items), 4)
        self.assertEqual(len(data_group.counted_data_items), 2)

# TODO: add test for smart group updated when calibration changes (use smart group of pixel < 1nm)

if __name__ == '__main__':
    unittest.main()
