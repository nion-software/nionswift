# standard libraries
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DataItem
from nion.swift import DataPanel
from nion.swift import DocumentController
from nion.swift import Operation
from nion.swift import Storage
from nion.swift import Test


class TestOperationClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), catch_stdout=False, set_global=False)
        db_name = ":memory:"
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        self.document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        self.document_controller.create_default_data_groups()
        default_data_group = self.document_controller.data_groups[0]
        self.image_panel = self.document_controller.selected_image_panel
        self.data_item = self.document_controller.set_data_by_key("test", numpy.zeros((1000, 1000)))
        self.image_panel.data_panel_selection = DataPanel.DataPanelSelection(default_data_group, self.data_item)

    def tearDown(self):
        self.image_panel.close()
        self.document_controller.close()

    # make sure we can remove a single operation
    def test_remove_operation(self):
        operation = Operation.InvertOperation()
        self.data_item.operations.append(operation)
        self.assertEqual(len(self.data_item.operations), 1)
        self.document_controller.remove_operation(operation)
        self.assertEqual(len(self.data_item.operations), 0)

    # make sure we can remove the second operation
    def test_multi_remove_operation(self):
        operation = Operation.InvertOperation()
        self.data_item.operations.append(operation)
        self.assertEqual(len(self.data_item.operations), 1)
        operation2 = Operation.ResampleOperation()
        self.data_item.operations.append(operation2)
        self.assertEqual(len(self.data_item.operations), 2)
        self.document_controller.remove_operation(operation2)
        self.assertEqual(len(self.data_item.operations), 1)

    # make sure defaults get propogated when adding data item to document
    def test_default_propogation(self):
        # first make sure data and calibrations come out OK
        operation = Operation.ResampleOperation()
        self.data_item.operations.append(operation)
        self.data_item.data  # just calculate it
        self.data_item.calculated_calibrations  # just calculate it
        # now create a new data item and add the operation before its added to document
        data_item = DataItem.DataItem()
        operation2 = Operation.ResampleOperation()
        data_item.operations.append(operation2)
        self.data_item.data_items.append(data_item)
        self.assertIsNotNone(operation2.description[0]["default"])
        self.assertIsNotNone(operation2.width)
