# standard libraries
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
from nion.swift import Image
from nion.swift import ImagePanel
from nion.swift import Operation
from nion.swift import Storage
from nion.swift import Test
from nion.swift import UserInterface


def construct_test_document(app, create_workspace=False):
    storage_writer = Storage.DictStorageWriter()
    document_model = DocumentModel.DocumentModel(storage_writer)
    document_controller = DocumentController.DocumentController(app.ui, document_model, _create_workspace=create_workspace)
    data_group1 = DataGroup.DataGroup()
    document_controller.document_model.data_groups.append(data_group1)
    data_item1a = DataItem.DataItem()
    data_item1a.master_data = numpy.zeros((256, 256), numpy.uint32)
    data_group1.data_items.append(data_item1a)
    data_item1b = DataItem.DataItem()
    data_item1b.master_data = numpy.zeros((256, 256), numpy.uint32)
    data_group1.data_items.append(data_item1b)
    data_group1a = DataGroup.DataGroup()
    data_group1.data_groups.append(data_group1a)
    data_group1b = DataGroup.DataGroup()
    data_group1.data_groups.append(data_group1b)
    data_group2 = DataGroup.DataGroup()
    document_controller.document_model.data_groups.append(data_group2)
    data_group2a = DataGroup.DataGroup()
    data_group2.data_groups.append(data_group2a)
    data_group2b = DataGroup.DataGroup()
    data_group2.data_groups.append(data_group2b)
    data_group2b1 = DataGroup.DataGroup()
    data_group2b.data_groups.append(data_group2b1)
    data_item2b1a = DataItem.DataItem()
    data_item2b1a.master_data = numpy.zeros((256, 256), numpy.uint32)
    data_group2b1.data_items.append(data_item2b1a)
    return document_controller

class TestDocumentControllerClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_delete_document_controller(self):
        storage_writer = Storage.DictStorageWriter()
        document_model = DocumentModel.DocumentModel(storage_writer)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, _create_workspace=False)
        document_model = None
        weak_document_model = weakref.ref(document_controller.document_model)
        weak_document_window = weakref.ref(document_controller.document_window)
        weak_document_controller = weakref.ref(document_controller)
        self.assertIsNotNone(weak_document_controller())
        self.assertIsNotNone(weak_document_window())
        self.assertIsNotNone(weak_document_model())
        document_controller.close()
        document_controller = None
        self.assertIsNone(weak_document_controller())
        self.assertIsNone(weak_document_window())
        self.assertIsNone(weak_document_model())

    def test_image_panel_releases_data_item(self):
        storage_writer = Storage.DictStorageWriter()
        document_model = DocumentModel.DocumentModel(storage_writer)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, _create_workspace=False)
        document_controller.document_model.create_default_data_groups()
        default_data_group = document_controller.document_model.data_groups[0]
        data_item = DataItem.DataItem()
        data_item.master_data = numpy.zeros((256, 256), numpy.uint32)
        default_data_group.data_items.append(data_item)
        weak_data_item = weakref.ref(data_item)
        image_panel = ImagePanel.ImagePanel(document_controller, "image-panel", {})
        image_panel.data_panel_selection = DataItem.DataItemSpecifier(default_data_group, data_item)
        self.assertIsNotNone(weak_data_item())
        image_panel.close()
        document_controller.close()
        data_item = None
        self.assertIsNone(weak_data_item())

    def test_main_thread_sync(self):
        storage_writer = Storage.DictStorageWriter()
        document_model = DocumentModel.DocumentModel(storage_writer)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, _create_workspace=False)
        data_group = DataGroup.DataGroup()
        document_controller.document_model.data_groups.append(data_group)
        data_item = DataItem.DataItem()
        data_item.master_data = numpy.zeros((256, 256), numpy.uint32)
        # make sure this works when called from the main thread
        document_controller.add_data_item_on_main_thread(data_group, data_item)

    def test_flat_data_groups(self):
        document_controller = construct_test_document(self.app)
        self.assertEqual(len(list(document_controller.document_model.get_flat_data_group_generator())), 7)
        self.assertEqual(len(list(document_controller.document_model.get_flat_data_item_generator())), 3)
        self.assertEqual(document_controller.document_model.get_data_item_by_key(0), document_controller.document_model.data_groups[0].data_items[0])
        self.assertEqual(document_controller.document_model.get_data_item_by_key(1), document_controller.document_model.data_groups[0].data_items[1])
        self.assertEqual(document_controller.document_model.get_data_item_by_key(2), document_controller.document_model.data_groups[1].data_groups[1].data_groups[0].data_items[0])
