# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DataItem
from nion.swift import DataPanel
from nion.swift import DocumentController
from nion.swift import ImagePanel
from nion.swift import Storage
from nion.swift import Test


class TestDataPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), catch_stdout=False, set_global=False)

    def tearDown(self):
        pass

    class DummyImagePanel(object):
        def __init__(self, data_item):
            self.data_item = data_item

    # make sure we can delete top level items, and child items
    def test_image_panel_delete(self):
        storage_writer = Storage.DictStorageWriter()
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        # data_group
        #   data_item1
        #     data_item1a
        #   data_item2
        #     data_item2a
        #   data_item3
        data_group = DocumentController.DataGroup()
        data_group.title = "data_group"
        document_controller.data_groups.append(data_group)
        data_item1 = DataItem.DataItem()
        data_item1.title = "data_item1"
        data_item1.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group.data_items.append(data_item1)
        data_item1a = DataItem.DataItem()
        data_item1a.title = "data_item1a"
        data_item1.data_items.append(data_item1a)
        data_item2 = DataItem.DataItem()
        data_item2.title = "data_item2"
        data_item2.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group.data_items.append(data_item2)
        data_item2a = DataItem.DataItem()
        data_item2a.title = "data_item2a"
        data_item2.data_items.append(data_item2a)
        data_item3 = DataItem.DataItem()
        data_item3.title = "data_item3"
        data_item3.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group.data_items.append(data_item3)
        image_panel = ImagePanel.ImagePanel(document_controller, "image-panel")
        image_panel.data_panel_selection = DataPanel.DataItemSpecifier(data_group, data_item1)
        data_panel = DataPanel.DataPanel(document_controller, "data-panel")
        document_controller.selected_image_panel = image_panel
        # first delete a child of a data item
        self.assertEqual(len(data_item1.data_items), 1)
        data_panel.data_group_model.itemChanged(0, -1, 0)
        data_panel.data_item_model.itemChanged(1)
        data_panel.data_item_model.itemKeyPress(1, chr(127), 0)
        self.assertEqual(len(data_item1.data_items), 0)
        # now delete a child of a data group
        self.assertEqual(len(data_group.data_items), 3)
        data_panel.data_item_model.itemChanged(3)
        data_panel.data_item_model.itemKeyPress(3, chr(127), 0)
        self.assertEqual(len(data_group.data_items), 2)
        image_panel.close()
        data_panel.close()

    # make sure switching between two views containing data items from the same group
    # switch between those data items in the data panel when switching.
    def test_selected_data_item_persistence(self):
        storage_writer = Storage.DictStorageWriter()
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        parent_data_group = DocumentController.DataGroup()
        parent_data_group.title = "parent_data_group"
        data_group = DocumentController.DataGroup()
        data_group.title = "data_group"
        parent_data_group.data_groups.append(data_group)
        document_controller.data_groups.append(parent_data_group)
        data_item1 = DataItem.DataItem()
        data_item1.title = "data_item1"
        data_item1.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group.data_items.append(data_item1)
        data_item2 = DataItem.DataItem()
        data_item2.title = "data_item2"
        data_item2.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group.data_items.append(data_item2)
        image_panel1 = ImagePanel.ImagePanel(document_controller, "image-panel")
        image_panel1.data_panel_selection = DataPanel.DataItemSpecifier(data_group, data_item1)
        image_panel2 = ImagePanel.ImagePanel(document_controller, "image-panel")
        image_panel2.data_panel_selection = DataPanel.DataItemSpecifier(data_group, data_item2)
        data_panel = DataPanel.DataPanel(document_controller, "data-panel")
        self.assertEqual(data_panel.data_group_model._parent_id, 0)
        self.assertEqual(data_panel.data_group_model._parent_row, -1)
        self.assertEqual(data_panel.data_group_model._index, -1)
        self.assertEqual(data_panel.data_item_model._index, -1)
        document_controller.selected_image_panel = image_panel1
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 0)
        self.assertEqual(data_panel.data_item_model._index, 0)
        document_controller.selected_image_panel = image_panel2
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 0)
        self.assertEqual(data_panel.data_item_model._index, 1)
        document_controller.selected_image_panel = image_panel1
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 0)
        self.assertEqual(data_panel.data_item_model._index, 0)
        image_panel1.close()
        image_panel2.close()

    # make sure switching between two data items in different groups works
    # then make sure the same group is selected if the data item is in multiple groups
    def test_selected_group_persistence(self):
        storage_writer = Storage.DictStorageWriter()
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        parent_data_group = DocumentController.DataGroup()
        parent_data_group.title = "parent_data_group"
        data_group1 = DocumentController.DataGroup()
        data_group1.title = "Group 1"
        parent_data_group.data_groups.append(data_group1)
        data_item1 = DataItem.DataItem()
        data_item1.title = "Data 1"
        data_item1.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group1.data_items.append(data_item1)
        data_group2 = DocumentController.DataGroup()
        data_group2.title = "Group 2"
        parent_data_group.data_groups.append(data_group2)
        data_item2 = DataItem.DataItem()
        data_item2.title = "Data 2"
        data_item2.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group2.data_items.append(data_item2)
        document_controller.data_groups.append(parent_data_group)
        image_panel1 = ImagePanel.ImagePanel(document_controller, "image-panel")
        image_panel1.data_panel_selection = DataPanel.DataItemSpecifier(data_group1, data_item1)
        image_panel2 = ImagePanel.ImagePanel(document_controller, "image-panel")
        image_panel2.data_panel_selection = DataPanel.DataItemSpecifier(data_group2, data_item2)
        data_panel = DataPanel.DataPanel(document_controller, "data-panel")
        self.assertEqual(data_panel.data_group_model._parent_id, 0)
        self.assertEqual(data_panel.data_group_model._parent_row, -1)
        self.assertEqual(data_panel.data_group_model._index, -1)
        self.assertEqual(data_panel.data_item_model._index, -1)
        document_controller.selected_image_panel = image_panel1
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 0)
        self.assertEqual(data_panel.data_item_model._index, 0)
        document_controller.selected_image_panel = image_panel2
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 1)
        self.assertEqual(data_panel.data_item_model._index, 0)
        document_controller.selected_image_panel = image_panel1
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 0)
        self.assertEqual(data_panel.data_item_model._index, 0)
        # now make sure if a data item is in multiple groups, the right one is selected
        data_group2.data_items.append(data_item1)
        document_controller.selected_image_panel = image_panel2
        data_panel.data_item_model.itemChanged(1)
        document_controller.selected_image_panel = image_panel1
        data_panel.data_item_model.itemChanged(0)
        self.assertEqual(image_panel1.data_item, data_item1)
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 0)
        self.assertEqual(data_panel.data_item_model._index, 0)
        document_controller.selected_image_panel = image_panel2
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 1)
        self.assertEqual(data_panel.data_item_model._index, 1)
        document_controller.selected_image_panel = image_panel1
        self.assertEqual(image_panel1.data_item, data_item1)
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 0)
        self.assertEqual(data_panel.data_item_model._index, 0)
        # now make sure group selections are preserved
        document_controller.selected_image_panel = image_panel1
        data_panel.data_group_model.itemChanged(1, 0, 1)
        data_panel.data_item_model.itemChanged(-1)
        self.assertIsNone(image_panel1.data_item)
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 1)
        self.assertEqual(data_panel.data_item_model._index, -1)
        document_controller.selected_image_panel = image_panel2
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 1)
        self.assertEqual(data_panel.data_item_model._index, 1)
        document_controller.selected_image_panel = image_panel1
        self.assertIsNone(image_panel1.data_item)
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 1)
        self.assertEqual(data_panel.data_item_model._index, -1)
        # make sure root level is handled ok
        document_controller.selected_image_panel = image_panel1
        data_panel.data_group_model.itemChanged(0, -1, 0)
        document_controller.selected_image_panel = image_panel2
        self.assertEqual(data_panel.data_group_model._parent_id, 1)
        self.assertEqual(data_panel.data_group_model._parent_row, 0)
        self.assertEqual(data_panel.data_group_model._index, 1)
        self.assertEqual(data_panel.data_item_model._index, 1)
        document_controller.selected_image_panel = image_panel1
        self.assertEqual(data_panel.data_group_model._parent_id, 0)
        self.assertEqual(data_panel.data_group_model._parent_row, -1)
        self.assertEqual(data_panel.data_group_model._index, 0)
        image_panel1.close()
        image_panel2.close()

    def test_selection_during_operations(self):
        storage_writer = Storage.DictStorageWriter()
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        parent_data_group = DocumentController.DataGroup()
        parent_data_group.title = "parent_data_group"
        data_group1 = DocumentController.DataGroup()
        data_group1.title = "Group 1"
        parent_data_group.data_groups.append(data_group1)
        data_item1 = DataItem.DataItem()
        data_item1.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group1.data_items.append(data_item1)
        data_group2 = DocumentController.DataGroup()
        data_group2.title = "Group 2"
        parent_data_group.data_groups.append(data_group2)
        data_item2 = DataItem.DataItem()
        data_item2.title = "Data 2"
        data_item2.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group2.data_items.append(data_item2)
        document_controller.data_groups.append(parent_data_group)
        image_panel1 = ImagePanel.ImagePanel(document_controller, "image-panel")
        image_panel1.data_panel_selection = DataPanel.DataItemSpecifier(data_group1, data_item1)
        image_panel2 = ImagePanel.ImagePanel(document_controller, "image-panel")
        image_panel2.data_panel_selection = DataPanel.DataItemSpecifier(data_group2, data_item2)
        data_panel = DataPanel.DataPanel(document_controller, "data-panel")
        document_controller.selected_image_panel = image_panel1
        # make sure our preconditions are right
        self.assertEqual(document_controller.selected_data_item, data_item1)
        self.assertEqual(len(data_item1.data_items), 0)
        # add processing and make sure it appeared
        document_controller.processing_invert()
        self.assertEqual(len(data_item1.data_items), 1)
        # now make sure both the image panel and data panel show it as selected
        self.assertEqual(image_panel1.data_panel_selection.data_item, data_item1.data_items[0])
        self.assertEqual(data_panel.data_group_model.data_panel_selection.data_group, data_group1)
        self.assertEqual(data_panel.data_item_model.data_panel_selection.data_group, data_group1)
        self.assertEqual(data_panel.data_item_model.data_panel_selection.data_item, data_item1.data_items[0])
        # switch away and back and make sure selection is still correct
        document_controller.selected_image_panel = image_panel2
        document_controller.selected_image_panel = image_panel1
        self.assertEqual(image_panel1.data_panel_selection.data_item, data_item1.data_items[0])
        self.assertEqual(data_panel.data_group_model.data_panel_selection.data_group, data_group1)
        self.assertEqual(data_panel.data_item_model.data_panel_selection.data_group, data_group1)
        self.assertEqual(data_panel.data_item_model.data_panel_selection.data_item, data_item1.data_items[0])

    def test_add_remove_sync(self):
        storage_writer = Storage.DictStorageWriter()
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        data_group = DocumentController.DataGroup()
        data_group.title = "data_group"
        document_controller.data_groups.append(data_group)
        data_item1 = DataItem.DataItem()
        data_item1.title = "data_item1"
        data_item1.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group.data_items.append(data_item1)
        data_item2 = DataItem.DataItem()
        data_item2.title = "data_item2"
        data_item2.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group.data_items.append(data_item2)
        data_item3 = DataItem.DataItem()
        data_item3.title = "data_item3"
        data_item3.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group.data_items.append(data_item3)
        image_panel = ImagePanel.ImagePanel(document_controller, "image-panel")
        image_panel.data_panel_selection = DataPanel.DataItemSpecifier(data_group, data_item2)
        data_panel = DataPanel.DataPanel(document_controller, "data-panel")
        document_controller.selected_image_panel = image_panel
        # verify assumptions
        self.assertEqual(len(data_panel.data_item_model.model), 3)
        # delete 2nd item
        data_panel.data_item_model.itemKeyPress(1, chr(127), 0)
        self.assertEqual(len(data_panel.data_item_model.model), 2)
        self.assertEqual(data_panel.data_item_model.model[0]["uuid"], str(data_item1.uuid))
        self.assertEqual(data_panel.data_item_model.model[1]["uuid"], str(data_item3.uuid))
        # insert new item
        data_item4 = DataItem.DataItem()
        data_item4.title = "data_item4"
        data_item4.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group.data_items.insert(1, data_item4)
        self.assertEqual(len(data_panel.data_item_model.model), 3)
        self.assertEqual(data_panel.data_item_model.model[0]["uuid"], str(data_item1.uuid))
        self.assertEqual(data_panel.data_item_model.model[1]["uuid"], str(data_item4.uuid))
        self.assertEqual(data_panel.data_item_model.model[2]["uuid"], str(data_item3.uuid))
        # finish up
        image_panel.close()
        data_panel.close()

    def test_select_after_receive_files(self):
        storage_writer = Storage.DictStorageWriter()
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        data_group = DocumentController.DataGroup()
        data_group.title = "data_group"
        document_controller.data_groups.append(data_group)
        data_item1 = DataItem.DataItem()
        data_item1.title = "data_item1"
        data_item1.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group.data_items.append(data_item1)
        image_panel = ImagePanel.ImagePanel(document_controller, "image-panel")
        data_panel = DataPanel.DataPanel(document_controller, "data-panel")
        document_controller.selected_image_panel = image_panel
        self.assertIsNone(image_panel.data_panel_selection.data_group)
        self.assertIsNone(image_panel.data_panel_selection.data_item)
        data_panel.receiveFiles(data_group, 0, [":/app/scroll_gem.png"])
        self.assertEqual(image_panel.data_panel_selection.data_group, data_group)
        self.assertEqual(image_panel.data_panel_selection.data_item, data_group.data_items[0])
        image_panel.close()
        data_panel.close()

    def test_data_panel_remove_group(self):
        storage_writer = Storage.DictStorageWriter()
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer, _create_workspace=False)
        data_group1 = DocumentController.DataGroup()
        data_group1.title = "data_group1"
        data_item1 = DataItem.DataItem()
        data_item1.title = "Green 1"
        data_item1.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group1.data_items.append(data_item1)
        document_controller.data_groups.append(data_group1)
        green_group = DocumentController.SmartDataGroup()
        green_group.title = "green_group"
        document_controller.data_groups.insert(0, green_group)
        self.assertEqual(len(green_group.data_items), 1)
        data_panel = DataPanel.DataPanel(document_controller, "data-panel")
        document_controller.remove_data_group_from_parent(document_controller.data_groups[0], document_controller)

    def test_data_panel_remove_item_by_key(self):
        storage_writer = Storage.DictStorageWriter()
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer, _create_workspace=False)
        data_group1 = DocumentController.DataGroup()
        data_group1.title = "data_group1"
        data_item1 = DataItem.DataItem()
        data_item1.title = "Green 1"
        data_item1.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_group1.data_items.append(data_item1)
        green_group = DocumentController.SmartDataGroup()
        green_group.title = "green_group"
        document_controller.data_groups.insert(0, green_group)
        document_controller.data_groups.append(data_group1)
        data_panel = DataPanel.DataPanel(document_controller, "data-panel")
        data_panel.update_data_panel_selection(DataPanel.DataItemSpecifier(data_group1, data_item1))
        self.assertTrue(data_item1 in data_group1.data_items)
        data_panel.data_item_model.itemKeyPress(0, chr(127), 0)
        self.assertFalse(data_item1 in data_group1.data_items)

    def log(self, data_panel):
        logging.debug("DATA GROUP MODEL")
        data_panel.data_group_model.log()
        logging.debug("DATA ITEM MODEL")
        data_panel.data_item_model.log()
        logging.debug("DATA PANEL SELECTION")
        logging.debug("Data group: %s (%s) -> %s", data_panel.data_group_model._parent_row, data_panel.data_group_model._parent_id, data_panel.data_group_model._index)
        logging.debug("Data item: %s", data_panel.data_item_model._index)
