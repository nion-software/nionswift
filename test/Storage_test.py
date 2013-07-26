# standard libraries
import copy
import logging
import threading
import unittest

# third party libraries
import numpy
import scipy

# local libraries
from nion.swift import Application
from nion.swift import DataItem
from nion.swift import DataPanel
from nion.swift import DocumentController
from nion.swift import Graphics
from nion.swift import ImagePanel
from nion.swift import Operation
from nion.swift import Storage
from nion.swift import Test


class TestStorageClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), catch_stdout=False, set_global=False)

    def tearDown(self):
        pass

    """
    document
        data_group
            data_item (line_graphic, rect_graphic, ellipse_graphic, gaussian, resample, invert)
            data_item2 (fft, ifft)
                data_item2a
                data_item2b
            data_item3
    """
    def save_document(self, document_controller):
        data_item = DataItem.DataItem()
        data_item.master_data = numpy.zeros((16, 16), numpy.uint32)
        data_group = DocumentController.DataGroup()
        data_group.data_items.append(data_item)
        document_controller.data_groups.append(data_group)
        data_item2 = DataItem.DataItem()
        data_item2.master_data = scipy.misc.lena()
        data_group.data_items.append(data_item2)
        data_item3 = DataItem.DataItem()
        data_item3.master_data = numpy.zeros((16, 16), numpy.uint32)
        data_group.data_items.append(data_item3)
        data_item2a = DataItem.DataItem()
        data_item2b = DataItem.DataItem()
        data_item2.data_items.append(data_item2a)
        data_item2.data_items.append(data_item2b)
        image_panel = ImagePanel.ImagePanel(document_controller, "image-panel")
        document_controller.selected_image_panel = image_panel
        image_panel.data_panel_selection = DataPanel.DataPanelSelection(data_group, data_item)
        self.assertEqual(document_controller.selected_data_item, data_item)
        document_controller.add_line_graphic()
        document_controller.add_rectangle_graphic()
        document_controller.add_ellipse_graphic()
        image_panel.data_panel_selection = DataPanel.DataPanelSelection(data_group, data_item)
        document_controller.processing_gaussian_blur()
        image_panel.data_panel_selection = DataPanel.DataPanelSelection(data_group, data_item)
        document_controller.processing_resample()
        image_panel.data_panel_selection = DataPanel.DataPanelSelection(data_group, data_item)
        document_controller.processing_invert()
        image_panel.data_panel_selection = DataPanel.DataPanelSelection(data_group, data_item)
        document_controller.processing_crop()
        image_panel.data_panel_selection = DataPanel.DataPanelSelection(data_group, data_item2)
        self.assertEqual(document_controller.selected_data_item, data_item2)
        document_controller.processing_fft()
        document_controller.processing_ifft()
        image_panel.close()

    def test_save_document(self):
        storage_writer = Storage.DictStorageWriter()
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        self.save_document(document_controller)

    def test_save_load_document(self):
        storage_writer = Storage.DictStorageWriter()
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        self.save_document(document_controller)
        data_items_count = len(document_controller.default_data_group.data_items)
        data_items_type = type(document_controller.default_data_group.data_items)
        document_controller.close()
        # read it back
        node_map_copy = copy.deepcopy(storage_writer.node_map)
        storage_writer = Storage.DictStorageWriter()
        storage_reader = Storage.DictStorageReader(node_map_copy)
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer, storage_reader)
        self.assertEqual(data_items_count, len(document_controller.default_data_group.data_items))
        self.assertEqual(data_items_type, type(document_controller.default_data_group.data_items))
        document_controller.close()

    def test_db_storage(self):
        db_name = ":memory:"
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        self.save_document(document_controller)
        storage_str = storage_writer.to_string()
        document_controller_uuid = document_controller.uuid
        data_items_count = len(document_controller.default_data_group.data_items)
        data_items_type = type(document_controller.default_data_group.data_items)
        data_item0_calibration_len = len(document_controller.default_data_group.data_items[0].calibrations)
        data_item0_uuid = document_controller.default_data_group.data_items[0].uuid
        data_item1_data_items_len = len(document_controller.default_data_group.data_items[1].data_items)
        document_controller.close()
        storage_writer.close()
        # read it back
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        self.assertNotEqual(document_controller_uuid, document_controller.uuid)
        storage_reader = Storage.DbStorageReader(db_name)
        storage_writer.close()
        storage_reader.from_string(storage_str)
        document_controller.read(storage_reader)
        self.assertEqual(document_controller_uuid, document_controller.uuid)
        self.assertEqual(data_items_count, len(document_controller.default_data_group.data_items))
        self.assertEqual(data_items_type, type(document_controller.default_data_group.data_items))
        self.assertIsNotNone(document_controller.default_data_group.data_items[0])
        self.assertIsNotNone(document_controller.default_data_group.data_items[0].data)
        self.assertEqual(data_item0_uuid, document_controller.default_data_group.data_items[0].uuid)
        self.assertEqual(data_item0_calibration_len, len(document_controller.default_data_group.data_items[0].calibrations))
        self.assertEqual(data_item1_data_items_len, len(document_controller.default_data_group.data_items[1].data_items))
        document_controller.close()

    # test whether we can update master_data and have it written to the db
    def test_db_storage_write_data(self):
        db_name = ":memory:"
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        data_item = DataItem.DataItem()
        data1 = numpy.zeros((16, 16), numpy.uint32)
        data1[0,0] = 1
        data_item.master_data = data1
        data_group = DocumentController.DataGroup()
        data_group.data_items.append(data_item)
        document_controller.data_groups.append(data_group)
        data2 = numpy.zeros((16, 16), numpy.uint32)
        data2[0,0] = 2
        data_item.master_data = data2
        storage_str = storage_writer.to_string()
        document_controller.close()
        # read it back
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        storage_reader = Storage.DbStorageReader(db_name)
        storage_reader.from_string(storage_str)
        document_controller.read(storage_reader)
        self.assertEqual(document_controller.default_data_group.data_items[0].data[0,0], 2)

    def update_data(self, data_item):
        data2 = numpy.zeros((16, 16), numpy.uint32)
        data2[0,0] = 2
        data_item.master_data = data2

    # test whether we can update the db from a thread
    def test_db_storage_write_on_thread(self):
        db_name = ":memory:"
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        data_item = DataItem.DataItem()
        data1 = numpy.zeros((16, 16), numpy.uint32)
        data1[0,0] = 1
        data_item.master_data = data1
        data_group = DocumentController.DataGroup()
        data_group.data_items.append(data_item)
        document_controller.data_groups.append(data_group)
        thread = threading.Thread(target=self.update_data, args=[data_item])
        thread.start()
        thread.join()
        storage_str = storage_writer.to_string()
        document_controller.close()
        # read it back
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        storage_reader = Storage.DbStorageReader(db_name)
        storage_reader.from_string(storage_str)
        document_controller.read(storage_reader)
        self.assertEqual(document_controller.default_data_group.data_items[0].data[0,0], 2)

    def test_db_storage_insert_items(self):
        db_name = ":memory:"
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        self.save_document(document_controller)
        # insert two items at beginning. this generates primary key error unless key updating is carefully handled
        data_item4 = DataItem.DataItem()
        data_item4.master_data = numpy.zeros((16, 16), numpy.uint32)
        document_controller.data_groups[0].data_items.insert(0, data_item4)
        data_item5 = DataItem.DataItem()
        data_item5.master_data = numpy.zeros((16, 16), numpy.uint32)
        document_controller.data_groups[0].data_items.insert(0, data_item5)
        c = storage_writer.conn.cursor()
        c.execute("SELECT COUNT(*) FROM relationships WHERE parent_uuid = ? AND key = 'data_items' AND item_index BETWEEN 0 and 4", (str(document_controller.data_groups[0].uuid), ))
        self.assertEqual(c.fetchone()[0], 5)
        # delete items to generate key error unless primary keys handled carefully. need to delete an item that is at index >= 2 to test for this problem.
        data_item6 = DataItem.DataItem()
        data_item6.master_data = numpy.zeros((16, 16), numpy.uint32)
        document_controller.data_groups[0].data_items.insert(1, data_item6)
        data_item7 = DataItem.DataItem()
        data_item7.master_data = numpy.zeros((16, 16), numpy.uint32)
        document_controller.data_groups[0].data_items.insert(1, data_item7)
        document_controller.data_groups[0].data_items.remove(document_controller.data_groups[0].data_items[2])
        # make sure indexes are in sequence still
        c = storage_writer.conn.cursor()
        c.execute("SELECT COUNT(*) FROM relationships WHERE parent_uuid = ? AND key = 'data_items' AND item_index BETWEEN 0 and 5", (str(document_controller.data_groups[0].uuid), ))
        self.assertEqual(c.fetchone()[0], 6)

    def test_copy_data_group(self):
        db_name = ":memory:"
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        data_group1 = DocumentController.DataGroup()
        document_controller.data_groups.append(data_group1)
        data_group1a = DocumentController.DataGroup()
        data_group1.data_groups.append(data_group1a)
        data_group1b = DocumentController.DataGroup()
        data_group1.data_groups.append(data_group1b)
        data_group2 = DocumentController.DataGroup()
        document_controller.data_groups.append(data_group2)
        data_group2a = DocumentController.DataGroup()
        data_group2.data_groups.append(data_group2a)
        data_group2b = DocumentController.DataGroup()
        data_group2.data_groups.append(data_group2b)
        data_group2b1 = DocumentController.DataGroup()
        data_group2b.data_groups.append(data_group2b1)
        data_group2_copy = data_group2.copy()
        data_group2_copy.add_ref()
        data_group2_copy.remove_ref()

    def verify_and_test_set_item(self, document_controller):
        # check that the graphic associated with the operation was read back
        graphic = document_controller.data_groups[0].data_items[0].graphics[3]
        crop_operation = document_controller.data_groups[0].data_items[0].data_items[3].operations[0]
        self.assertIsInstance(crop_operation, Operation.CropOperation)
        self.assertEqual(graphic, crop_operation.graphic)
        # test setting original graphic to None. the graphic is still referenced by the data item
        # so it should not be None
        old_graphic = crop_operation.graphic
        self.assertIsNotNone(document_controller.storage_writer.find_node_or_none(old_graphic))
        old_graphic.add_ref()
        crop_operation.graphic = None
        self.assertIsNotNone(document_controller.storage_writer.find_node_or_none(old_graphic))
        old_graphic.remove_ref()
        # test replacing the graphic
        graphic1 = Graphics.RectangleGraphic()
        graphic1.add_ref()
        graphic1.bounds = ((0.25,0.25), (0.5,0.5))
        crop_operation.graphic = graphic1
        self.assertIsNotNone(document_controller.storage_writer.find_node_or_none(graphic1))
        graphic2 = Graphics.RectangleGraphic()
        graphic2.add_ref()
        graphic2.bounds = ((0.25,0.25), (0.5,0.5))
        crop_operation.graphic = graphic2
        self.assertIsNone(document_controller.storage_writer.find_node_or_none(graphic1))
        self.assertIsNotNone(document_controller.storage_writer.find_node_or_none(graphic2))
        crop_operation.graphic = None
        self.assertIsNone(document_controller.storage_writer.find_node_or_none(graphic2))
        # finally test setting it to None
        graphic1.remove_ref()
        graphic2.remove_ref()

    def test_dict_storage_set_item(self):
        # write to storage
        storage_writer = Storage.DictStorageWriter()
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        self.save_document(document_controller)
        document_controller.close()
        # read it back
        node_map_copy = copy.deepcopy(storage_writer.node_map)
        storage_writer = Storage.DictStorageWriter()
        storage_reader = Storage.DictStorageReader(node_map_copy)
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer, storage_reader)
        document_controller.rewrite()
        # check that the graphic associated with the operation was read back
        self.verify_and_test_set_item(document_controller)
        # clean up
        document_controller.close()

    def test_db_storage_set_item(self):
        # write to storage
        db_name = ":memory:"
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        self.save_document(document_controller)
        storage_str = storage_writer.to_string()
        document_controller.close()
        # read it back
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        document_controller = DocumentController.DocumentController(self.app, None, storage_writer)
        storage_reader = Storage.DbStorageReader(db_name)
        storage_reader.from_string(storage_str)
        document_controller.read(storage_reader)
        # check that the graphic associated with the operation was read back
        self.verify_and_test_set_item(document_controller)
        # clean up
        document_controller.close()
