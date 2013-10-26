# standard libraries
import copy
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
from nion.swift import Test



class TestDataGroupClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_copy(self):
        data_group = DataGroup.DataGroup()
        data_group.add_ref()
        data_item1 = DataItem.DataItem()
        data_item1.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group.data_items.append(data_item1)
        data_group2 = DataGroup.DataGroup()
        data_group.data_groups.append(data_group2)
        data_group_copy = copy.deepcopy(data_group)
        data_group_copy.add_ref()
        # make sure data_items are not shared
        self.assertNotEqual(data_group.data_items[0], data_group_copy.data_items[0])
        # make sure data_groups are not shared
        self.assertNotEqual(data_group.data_groups[0], data_group_copy.data_groups[0])
        # clean up
        data_group_copy.remove_ref()
        data_group.remove_ref()

    def test_counted_data_items(self):
        storage_writer = Storage.DictStorageWriter()
        document_model = DocumentModel.DocumentModel(storage_writer)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model)
        data_group = DataGroup.DataGroup()
        document_controller.document_model.data_groups.append(data_group)
        self.assertEqual(len(data_group.counted_data_items), 0)
        self.assertEqual(len(document_controller.document_model.counted_data_items), 0)
        data_item1 = DataItem.DataItem()
        data_item1.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group.data_items.append(data_item1)
        # make sure that both top level and data_group see the data item
        self.assertEqual(len(document_controller.document_model.counted_data_items), 1)
        self.assertEqual(len(data_group.counted_data_items), 1)
        self.assertEqual(document_controller.document_model.counted_data_items, data_group.counted_data_items)
        self.assertIn(data_item1, data_group.counted_data_items.keys())
        # add a child data item and make sure top level and data_group see it
        # also check data item.
        data_item1a = DataItem.DataItem()
        operation1a = Operation.Resample2dOperation()
        data_item1a.operations.append(operation1a)
        data_item1.data_items.append(data_item1a)
        self.assertEqual(len(document_controller.document_model.counted_data_items), 2)
        self.assertEqual(len(data_group.counted_data_items), 2)
        self.assertEqual(len(data_item1.counted_data_items), 1)
        self.assertEqual(document_controller.document_model.counted_data_items, data_group.counted_data_items)
        self.assertIn(data_item1, data_group.counted_data_items.keys())
        self.assertIn(data_item1a, data_group.counted_data_items.keys())
        self.assertIn(data_item1a, data_item1.counted_data_items.keys())
        # add a child data item to the child and make sure top level and data_group match.
        # also check data items.
        data_item1a1 = DataItem.DataItem()
        operation1a1 = Operation.Resample2dOperation()
        data_item1a1.operations.append(operation1a1)
        data_item1a.data_items.append(data_item1a1)
        data_item1a1.calculated_calibrations
        self.assertEqual(len(document_controller.document_model.counted_data_items), 3)
        self.assertEqual(len(data_group.counted_data_items), 3)
        self.assertEqual(len(data_item1.counted_data_items), 2)
        self.assertEqual(len(data_item1a.counted_data_items), 1)
        self.assertEqual(document_controller.document_model.counted_data_items, data_group.counted_data_items)
        self.assertIn(data_item1, data_group.counted_data_items.keys())
        self.assertIn(data_item1a, data_group.counted_data_items.keys())
        self.assertIn(data_item1a, data_item1.counted_data_items.keys())
        self.assertIn(data_item1a1, data_group.counted_data_items.keys())
        self.assertIn(data_item1a1, data_item1a.counted_data_items.keys())
        # now add a data item that already has children
        data_item2 = DataItem.DataItem()
        data_item2.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_item2a = DataItem.DataItem()
        operation2a = Operation.Resample2dOperation()
        data_item2a.operations.append(operation2a)
        data_item2.data_items.append(data_item2a)
        self.assertEqual(len(data_item2.counted_data_items), 1)
        self.assertIn(data_item2a, data_item2.counted_data_items.keys())
        data_group.data_items.append(data_item2)
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
        data_group.data_items.remove(data_item2)
        self.assertEqual(len(document_controller.document_model.counted_data_items), 2)
        self.assertEqual(len(data_group.counted_data_items), 2)

    # make sure that smart groups that get added have their counted set updated with any existing data items
    def test_counted_data_items_order(self):
        storage_writer = Storage.DictStorageWriter()
        document_model = DocumentModel.DocumentModel(storage_writer)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model)
        data_group1 = DataGroup.DataGroup()
        data_group1.title = "data_group1"
        data_item1 = DataItem.DataItem()
        data_item1.title = "Green 1"
        data_item1.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group1.data_items.append(data_item1)
        document_controller.document_model.data_groups.append(data_group1)
        green_group = DataGroup.SmartDataGroup()
        green_group.title = "green_group"
        document_controller.document_model.data_groups.append(green_group)
        self.assertEqual(len(green_group.data_items), 1)

    # make sure that property changes (title) trigger the smart group to update
    def test_smart_group_property_change(self):
        storage_writer = Storage.DictStorageWriter()
        document_model = DocumentModel.DocumentModel(storage_writer)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model)
        data_group1 = DataGroup.DataGroup()
        data_group1.title = "data_group1"
        data_item1 = DataItem.DataItem()
        data_item1.title = "Green 1"
        data_item1.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group1.data_items.append(data_item1)
        document_controller.document_model.data_groups.append(data_group1)
        green_group = DataGroup.SmartDataGroup()
        green_group.title = "green_group"
        document_controller.document_model.data_groups.append(green_group)
        self.assertEqual(len(green_group.data_items), 1)
        data_item1.title = "Blue 1"
        self.assertEqual(len(green_group.data_items), 0)
        data_item1.title = "Green 2"
        self.assertEqual(len(green_group.data_items), 1)

# TODO: add test for smart group updated when calibration changes (use smart group of pixel < 1nm)
