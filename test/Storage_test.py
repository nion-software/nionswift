# standard libraries
import copy
import logging
import os
import shutil
import threading
import unittest

# third party libraries
import numpy
import scipy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import ImagePanel
from nion.swift import NDataHandler
from nion.swift.model import Calibration
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import ImportExportManager
from nion.swift.model import Operation
from nion.swift.model import Region
from nion.swift.model import Storage
from nion.swift.model import Utility
from nion.ui import Test


class TestStorageClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

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
        data = numpy.zeros((16, 16), numpy.uint32)
        data[:] = 50
        data[8, 8] = 2020
        data_item = DataItem.DataItem(data)
        data_item.displays[0].display_limits = (500, 1000)
        data_item.set_intensity_calibration(Calibration.Calibration(1.0, 2.0, "three"))
        with data_item.open_metadata("test") as metadata:
            metadata["one"] = 1
        data_item.add_region(Region.PointRegion())
        data_item.add_region(Region.LineRegion())
        data_item.add_region(Region.RectRegion())
        document_controller.document_model.append_data_item(data_item)
        data_group = DataGroup.DataGroup()
        data_group.append_data_item(data_item)
        document_controller.document_model.append_data_group(data_group)
        data_item2 = DataItem.DataItem(scipy.misc.lena())
        document_controller.document_model.append_data_item(data_item2)
        data_group.append_data_item(data_item2)
        data_item3 = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
        document_controller.document_model.append_data_item(data_item3)
        data_group.append_data_item(data_item3)
        data_item2a = DataItem.DataItem()
        data_item2b = DataItem.DataItem()
        data_item2a.add_data_source(data_item2)
        data_item2b.add_data_source(data_item2)
        data_group.append_data_item(data_item2a)
        data_group.append_data_item(data_item2b)
        document_controller.document_model.append_data_item(data_item2a)
        document_controller.document_model.append_data_item(data_item2b)
        image_panel = ImagePanel.ImagePanel(document_controller, "image-panel", {})
        document_controller.selected_image_panel = image_panel
        image_panel.set_displayed_data_item(data_item)
        self.assertEqual(document_controller.selected_data_item, data_item)
        document_controller.add_line_graphic()
        document_controller.add_rectangle_graphic()
        document_controller.add_ellipse_graphic()
        document_controller.add_point_graphic()
        image_panel.set_displayed_data_item(data_item)
        document_controller.processing_gaussian_blur()
        image_panel.set_displayed_data_item(data_item)
        document_controller.processing_resample()
        image_panel.set_displayed_data_item(data_item)
        document_controller.processing_invert()
        image_panel.set_displayed_data_item(data_item)
        document_controller.processing_crop()
        image_panel.set_displayed_data_item(data_item2)
        self.assertEqual(document_controller.selected_data_item, data_item2)
        document_controller.processing_fft()
        document_controller.processing_ifft()
        image_panel.close()

    def test_save_document(self):
        datastore = Storage.DictDatastore()
        document_model = DocumentModel.DocumentModel(datastore)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)

    def test_save_load_document(self):
        datastore = Storage.DictDatastore()
        document_model = DocumentModel.DocumentModel(datastore)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        data_items_count = len(document_controller.document_model.data_items)
        data_items_type = type(document_controller.document_model.data_items)
        document_controller.close()
        # read it back
        node_map_copy = copy.deepcopy(datastore.node_map)
        datastore = Storage.DictDatastore(node_map_copy)
        storage_cache = Storage.DictStorageCache()
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.assertEqual(data_items_count, len(document_controller.document_model.data_items))
        self.assertEqual(data_items_type, type(document_controller.document_model.data_items))
        document_controller.close()

    def test_save_load_document_to_files(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        db_name = os.path.join(workspace_dir, "Data.nswrk")
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        try:
            datastore = Storage.DbDatastore(data_reference_handler, db_name)
            storage_cache = Storage.DbStorageCache(db_name)
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(datastore, storage_cache, library_storage=library_storage)
            document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
            self.save_document(document_controller)
            data_items_count = len(document_controller.document_model.data_items)
            data_items_type = type(document_controller.document_model.data_items)
            # clean up
            document_controller.close()
            document_controller = None
            document_model = None
            storage_cache.close()
            storage_cache = None
            datastore.close()
            datastore = None
            # read it back
            data_reference_handler = Application.DataReferenceHandler(workspace_dir)
            datastore = Storage.DbDatastore(data_reference_handler, db_name)
            storage_cache = Storage.DbStorageCache(db_name)
            document_model = DocumentModel.DocumentModel(datastore, storage_cache, library_storage=library_storage)
            self.assertEqual(data_items_count, len(document_model.data_items))
            self.assertEqual(data_items_type, type(document_model.data_items))
            # clean up
            document_model.close()
            document_model = None
            storage_cache.close()
            storage_cache = None
            datastore.close()
            datastore = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def write_read_db_storage(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        library_storage = DocumentModel.FilePersistentStorage()
        document_model = DocumentModel.DocumentModel(datastore, storage_cache, library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        storage_data = datastore.to_data()
        document_model_uuid = document_controller.document_model.uuid
        data_items_count = len(document_controller.document_model.data_items)
        data_items_type = type(document_controller.document_model.data_items)
        data_item0_calibration_len = len(document_controller.document_model.data_items[0].intrinsic_calibrations)
        data_item0_uuid = document_controller.document_model.data_items[0].uuid
        data_item1_data_items_len = len(document_controller.document_model.get_dependent_data_items(document_controller.document_model.data_items[1]))
        document_controller.close()
        datastore.close()
        # read it back
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache, library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.assertEqual(document_model_uuid, document_controller.document_model.uuid)
        self.assertEqual(data_items_count, len(document_controller.document_model.data_items))
        self.assertEqual(data_items_type, type(document_controller.document_model.data_items))
        self.assertIsNotNone(document_controller.document_model.data_items[0])
        with document_controller.document_model.data_items[0].data_ref() as data_ref:
            self.assertIsNotNone(data_ref.data)
        self.assertEqual(data_item0_uuid, document_controller.document_model.data_items[0].uuid)
        self.assertEqual(data_item0_calibration_len, len(document_controller.document_model.data_items[0].intrinsic_calibrations))
        new_data_item1_data_items_len = len(document_controller.document_model.get_dependent_data_items(document_controller.document_model.data_items[1]))
        self.assertEqual(data_item1_data_items_len, new_data_item1_data_items_len)
        # check over the data item
        data_item = document_controller.document_model.data_items[0]
        self.assertEqual(data_item.displays[0].display_limits, (500, 1000))
        self.assertEqual(data_item.intrinsic_intensity_calibration.origin, 1.0)
        self.assertEqual(data_item.intrinsic_intensity_calibration.scale, 2.0)
        self.assertEqual(data_item.intrinsic_intensity_calibration.units, "three")
        self.assertEqual(data_item.get_metadata("test")["one"], 1)
        document_controller.close()

    def test_db_storage(self):
        self.write_read_db_storage()

    # test whether we can update master_data and have it written to the db
    def test_db_storage_write_data(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data1 = numpy.zeros((16, 16), numpy.uint32)
        data1[0,0] = 1
        data_item = DataItem.DataItem(data1)
        document_model.append_data_item(data_item)
        data_group = DataGroup.DataGroup()
        data_group.append_data_item(data_item)
        document_controller.document_model.append_data_group(data_group)
        data2 = numpy.zeros((16, 16), numpy.uint32)
        data2[0,0] = 2
        with data_item.data_ref() as data_ref:
            data_ref.master_data = data2
        storage_data = datastore.to_data()
        document_controller.close()
        # read it back
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with document_controller.document_model.data_items[0].data_ref() as data_ref:
            self.assertEqual(data_ref.data[0,0], 2)

    # test to ensure that no duplicate relationships are created
    def test_db_rewrite(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastoreProxy(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        # add the data group first so that if datastore is not disconnected,
        # writes will happen immediately to the database.
        data_group = DataGroup.DataGroup()
        document_model.append_data_group(data_group)
        datastore.disconnected = True
        datastore._throttling = 0.004  # 4ms
        for i in xrange(10):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            data_group.append_data_item(data_item)
        datastore.disconnected = False
        self.assertEqual(len(datastore.get_items(datastore.find_parent_node(data_group), "data_items")), 0)

    def update_data(self, data_item):
        data2 = numpy.zeros((16, 16), numpy.uint32)
        data2[0,0] = 2
        with data_item.data_ref() as data_ref:
            data_ref.master_data = data2

    # test whether we can update the db from a thread
    def test_db_storage_write_on_thread(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data1 = numpy.zeros((16, 16), numpy.uint32)
        data1[0,0] = 1
        data_item = DataItem.DataItem(data1)
        document_model.append_data_item(data_item)
        data_group = DataGroup.DataGroup()
        data_group.append_data_item(data_item)
        document_controller.document_model.append_data_group(data_group)
        thread = threading.Thread(target=self.update_data, args=[data_item])
        thread.start()
        thread.join()
        storage_data = datastore.to_data()
        document_controller.close()
        # read it back
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with document_controller.document_model.data_items[0].data_ref() as data_ref:
            self.assertEqual(data_ref.data[0,0], 2)

    def test_storage_insert_items(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        library_storage = DocumentModel.FilePersistentStorage()
        document_model = DocumentModel.DocumentModel(datastore, storage_cache, library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        # insert and append items
        data_group1 = DataGroup.DataGroup()
        data_group2 = DataGroup.DataGroup()
        data_group3 = DataGroup.DataGroup()
        document_controller.document_model.data_groups[0].append_data_group(data_group1)
        document_controller.document_model.data_groups[0].insert_data_group(0, data_group2)
        document_controller.document_model.data_groups[0].append_data_group(data_group3)
        self.assertEqual(len(library_storage.properties["data_groups"][0]["data_groups"]), 3)
        # delete items to generate key error unless primary keys handled carefully. need to delete an item that is at index >= 2 to test for this problem.
        data_group4 = DataGroup.DataGroup()
        data_group5 = DataGroup.DataGroup()
        document_controller.document_model.data_groups[0].insert_data_group(1, data_group4)
        document_controller.document_model.data_groups[0].insert_data_group(1, data_group5)
        document_controller.document_model.data_groups[0].remove_data_group(document_controller.document_model.data_groups[0].data_groups[2])
        # make sure indexes are in sequence still
        self.assertEqual(len(library_storage.properties["data_groups"][0]["data_groups"]), 4)

    def test_copy_data_group(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_group1 = DataGroup.DataGroup()
        document_controller.document_model.append_data_group(data_group1)
        data_group1a = DataGroup.DataGroup()
        data_group1.append_data_group(data_group1a)
        data_group1b = DataGroup.DataGroup()
        data_group1.append_data_group(data_group1b)
        data_group2 = DataGroup.DataGroup()
        document_controller.document_model.append_data_group(data_group2)
        data_group2a = DataGroup.DataGroup()
        data_group2.append_data_group(data_group2a)
        data_group2b = DataGroup.DataGroup()
        data_group2.append_data_group(data_group2b)
        data_group2b1 = DataGroup.DataGroup()
        data_group2b.append_data_group(data_group2b1)
        data_group2_copy = copy.deepcopy(data_group2)

    def test_adding_data_item_to_document_model_twice_raises_exception(self):
        datastore = Storage.DictDatastore()
        document_model = DocumentModel.DocumentModel(datastore)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        with self.assertRaises(AssertionError):
            document_model.append_data_item(data_item)

    # make sure thumbnail raises exception if a bad operation is involved
    def test_adding_data_item_to_data_group_twice_raises_exception(self):
        datastore = Storage.DictDatastore()
        document_model = DocumentModel.DocumentModel(datastore)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        document_model.data_groups[0].append_data_item(data_item)
        with self.assertRaises(AssertionError):
            document_model.data_groups[0].append_data_item(data_item)

    def test_insert_item_with_transaction(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        data_group = DataGroup.DataGroup()
        document_model.append_data_group(data_group)
        data_item = DataItem.DataItem()
        data_item.title = 'title'
        with data_item.transaction():
            with data_item.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
            document_model.append_data_item(data_item)
            data_group.append_data_item(data_item)
        storage_data = datastore.to_data()
        # make sure it reloads
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        data_item1 = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
        data_item2 = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
        data_item3 = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
        document_model.append_data_item(data_item1)
        document_model.append_data_item(data_item2)
        document_model.append_data_item(data_item3)
        # interleaved transactions
        data_item1.begin_transaction()
        data_item2.begin_transaction()
        data_item1.end_transaction()
        data_item3.begin_transaction()
        data_item3.end_transaction()
        data_item2.end_transaction()

    def test_data_item_should_store_modifications_within_transactions(self):
        reference_date = {'dst': '+00', 'tz': '-0800', 'local_datetime': '2000-06-30T15:02:00.000000'}
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        data_item = DataItem.DataItem()
        document_model.append_data_item(data_item)
        with data_item.transaction():
            data_item.datetime_original = reference_date
        storage_data = datastore.to_data()
        # make sure it reloads
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        self.assertEqual(document_model.data_items[0].datetime_original, reference_date)

    def test_data_writes_to_and_reloads_from_file(self):
        reference_date = {'dst': '+00', 'tz': '-0800', 'local_datetime': '2000-06-30T15:02:00.000000'}
        db_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        try:
            datastore = Storage.DbDatastore(data_reference_handler, db_name)
            storage_cache = Storage.DbStorageCache(db_name)
            document_model = DocumentModel.DocumentModel(datastore, storage_cache)
            data_item = DataItem.DataItem()
            data_item.datetime_original = reference_date
            with data_item.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
            document_model.append_data_item(data_item)
            reference_type, reference = data_item.get_data_file_info()
            self.assertEqual(reference_type, "relative_file")
            data_file_path = os.path.join(current_working_directory, "__Test", "Nion Swift Data", reference + ".ndata")
            self.assertTrue(os.path.exists(data_file_path))
            self.assertTrue(os.path.isfile(data_file_path))
            storage_data = datastore.to_data()
            datastore.close()
            # make sure the data reloads
            datastore = Storage.DbDatastore(data_reference_handler, db_name, storage_data=storage_data)
            storage_cache = Storage.DbStorageCache(db_name)
            document_model = DocumentModel.DocumentModel(datastore, storage_cache)
            with document_model.data_items[0].data_ref() as data_ref:
                self.assertIsNotNone(data_ref.data)
            # and then make sure the data file gets removed on disk when removed
            document_model.remove_data_item(document_model.data_items[0])
            self.assertFalse(os.path.exists(data_file_path))
            # clean up
            document_model.close()
            document_model = None
            storage_cache.close()
            storage_cache = None
            datastore.close()
            datastore = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_writing_empty_data_item_returns_expected_values(self):
        db_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        try:
            datastore = Storage.DbDatastore(data_reference_handler, db_name)
            storage_cache = Storage.DbStorageCache(db_name)
            document_model = DocumentModel.DocumentModel(datastore, storage_cache)
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            reference_type, reference = data_item.get_data_file_info()
            self.assertFalse(data_item.has_master_data)
            self.assertIsNone(data_item.data_shape)
            self.assertIsNone(data_item.data_dtype)
            self.assertEqual(reference_type, "relative_file")
            self.assertIsNotNone(reference)
            # clean up
            document_model.close()
            document_model = None
            storage_cache.close()
            storage_cache = None
            datastore.close()
            datastore = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_data_writes_to_file_after_transaction(self):
        db_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        try:
            datastore = Storage.DbDatastore(data_reference_handler, db_name)
            storage_cache = Storage.DbStorageCache(db_name)
            document_model = DocumentModel.DocumentModel(datastore, storage_cache)
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            # write data with transaction
            handler = NDataHandler.NDataHandler(os.path.join(current_working_directory, "__Test", "Nion Swift Data"))
            with data_item.transaction():
                with data_item.data_ref() as data_ref:
                    data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
                reference = document_model.managed_object_context.get_persistent_storage_for_object(data_item).get_default_reference(data_item)
                data_file_path = os.path.join(current_working_directory, "__Test", "Nion Swift Data", reference + ".ndata")
                # make sure data does NOT exist during the transaction
                self.assertIsNone(handler.read_data(reference))
            # make sure it DOES exist after the transaction
            self.assertTrue(os.path.exists(data_file_path))
            self.assertTrue(os.path.isfile(data_file_path))
            self.assertIsNotNone(handler.read_data(reference))
            # clean up
            document_model.close()
            document_model = None
            storage_cache.close()
            storage_cache = None
            datastore.close()
            datastore = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_data_removes_file_after_original_date_and_session_change(self):
        reference_date = {'dst': '+00', 'tz': '-0800', 'local_datetime': '2000-06-30T15:02:00.000000'}
        db_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        try:
            datastore = Storage.DbDatastore(data_reference_handler, db_name)
            storage_cache = Storage.DbStorageCache(db_name)
            document_model = DocumentModel.DocumentModel(datastore, storage_cache)
            data_item = DataItem.DataItem()
            data_item.datetime_original = reference_date
            with data_item.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
            document_model.append_data_item(data_item)
            reference_type, reference = data_item.get_data_file_info()
            data_file_path = os.path.join(current_working_directory, "__Test", "Nion Swift Data", reference + ".ndata")
            # make sure it get written to disk
            self.assertTrue(os.path.exists(data_file_path))
            self.assertTrue(os.path.isfile(data_file_path))
            # change the original date
            data_item.datetime_original = Utility.get_current_datetime_item()
            data_item.session_id = "20000531-000000"
            document_model.remove_data_item(data_item)
            # make sure it get removed from disk
            self.assertFalse(os.path.exists(data_file_path))
            # clean up
            document_model.close()
            document_model = None
            storage_cache.close()
            storage_cache = None
            datastore.close()
            datastore = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_reloading_data_item_with_display_builds_drawn_graphics_properly(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        self.assertEqual(len(document_model.data_items[0].displays[0].drawn_graphics), 8)  # verify assumptions
        storage_data = datastore.to_data()
        document_controller.close()
        # read it back
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # verify drawn_graphics reload
        self.assertEqual(len(document_model.data_items[0].displays[0].drawn_graphics), 8)
        # clean up
        document_controller.close()

    def test_writing_empty_data_item_followed_by_writing_data_adds_correct_calibrations(self):
        # this failed due to a key aliasing issue.
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # create empty data item
        data_item = DataItem.DataItem()
        document_model.append_data_item(data_item)
        data_item.begin_transaction()
        with data_item.data_ref() as data_ref:
            data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
        data_item.end_transaction()
        self.assertEqual(len(data_item.intrinsic_calibrations), 2)
        # save it out
        storage_data = datastore.to_data()
        # read it back
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # verify calibrations
        self.assertEqual(len(document_model.data_items[0].intrinsic_calibrations), 2)
        # clean up
        document_controller.close()

    def test_reloading_data_item_establishes_display_connection_to_storage(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        # save it out
        storage_data = datastore.to_data()
        # read it back
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # clean up
        document_controller.close()

    def test_reloading_data_item_establishes_operation_connection_to_storage(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        invert_operation = Operation.OperationItem("invert-operation")
        data_item.add_operation(invert_operation)
        # save it out
        storage_data = datastore.to_data()
        # read it back
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # clean up
        document_controller.close()

    def test_changes_to_operation_values_are_saved(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        gaussian_operation = Operation.OperationItem("gaussian-blur-operation")
        data_item.add_operation(gaussian_operation)
        gaussian_operation.set_property("sigma", 1.7)
        # save it out
        storage_data = datastore.to_data()
        # read it back
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # verify that properties read it correctly
        self.assertAlmostEqual(document_model.data_items[0].operations[0].get_property("sigma"), 1.7)
        # clean up
        document_controller.close()

    def test_reloaded_line_profile_operation_binds_to_roi(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item2 = DataItem.DataItem()
        document_model.append_data_item(data_item2)
        line_profile_operation = Operation.OperationItem("line-profile-operation")
        line_profile_operation.set_property("start", (0.1, 0.2))
        line_profile_operation.set_property("end", (0.3, 0.4))
        line_region = Region.LineRegion()
        line_region.start = 0.1, 0.2
        line_region.end = 0.3, 0.4
        line_profile_operation.region_uuid = line_region.uuid
        data_item.add_region(line_region)
        data_item2.add_operation(line_profile_operation)
        data_item2.add_data_source(data_item)
        # save it out
        storage_data = datastore.to_data()
        # read it back
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # verify that properties read it correctly
        self.assertEqual(document_model.data_items[0].regions[0].start, (0.1, 0.2))
        self.assertEqual(document_model.data_items[0].regions[0].end, (0.3, 0.4))
        self.assertEqual(document_model.data_items[1].operations[0].values["start"], (0.1, 0.2))
        self.assertEqual(document_model.data_items[1].operations[0].values["end"], (0.3, 0.4))
        document_model.data_items[0].regions[0].start = 0.11, 0.22
        self.assertEqual(document_model.data_items[1].operations[0].values["start"], (0.11, 0.22))
        self.assertEqual(document_model.data_items[1].operations[0].values["end"], (0.3, 0.4))
        # clean up
        document_controller.close()

    def test_reloaded_graphics_load_properly(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        rect_graphic = Graphics.RectangleGraphic()
        rect_graphic.bounds = ((0.25, 0.25), (0.5, 0.5))
        data_item.displays[0].append_graphic(rect_graphic)
        # save it out
        storage_data = datastore.to_data()
        document_controller.close()
        # read it back
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # verify
        self.assertEqual(len(document_model.data_items[0].displays[0].graphics), 1)
        # clean up
        document_controller.close()

    def test_reloaded_regions_load_properly(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        point_region = Region.PointRegion()
        point_region.position = (0.6, 0.4)
        point_region_uuid = point_region.uuid
        data_item.add_region(point_region)
        # save it out
        storage_data = datastore.to_data()
        document_controller.close()
        # read it back
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # verify
        self.assertEqual(document_model.data_items[0].regions[0].type, "point-region")
        self.assertEqual(document_model.data_items[0].regions[0].uuid, point_region_uuid)
        self.assertEqual(document_model.data_items[0].regions[0].position, (0.6, 0.4))
        # clean up
        document_controller.close()

    def test_reloaded_empty_data_groups_load_properly(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_group = DataGroup.DataGroup()
        document_model.append_data_group(data_group)
        # save it out
        storage_data = datastore.to_data()
        document_controller.close()
        # read it back
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # clean up
        document_controller.close()

    def test_new_data_item_stores_uuid_and_data_info_in_properties_immediately(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        self.assertTrue("master_data_shape" in data_item.properties)
        self.assertTrue("master_data_dtype" in data_item.properties)
        self.assertTrue("uuid" in data_item.properties)
        self.assertTrue("version" in data_item.properties)
        self.assertTrue("reader_version" in data_item.properties)

    def test_deleting_dependent_after_deleting_source_succeeds(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        db_name = os.path.join(workspace_dir, "Data.nswrk")
        try:
            datastore = Storage.DbDatastore(data_reference_handler, db_name)
            storage_cache = Storage.DbStorageCache(db_name)
            document_model = DocumentModel.DocumentModel(datastore, storage_cache)
            data_item = DataItem.DataItem()
            with data_item.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
            document_model.append_data_item(data_item)
            data_item2 = DataItem.DataItem()
            document_model.append_data_item(data_item2)
            data_item2.add_data_source(data_item)
            reference_type, reference = data_item.get_data_file_info()
            reference_type, reference2 = data_item2.get_data_file_info()
            data_file_path = os.path.join(current_working_directory, "__Test", "Nion Swift Data", reference + ".ndata")
            data2_file_path = os.path.join(current_working_directory, "__Test", "Nion Swift Data", reference2 + ".ndata")
            # make sure assumptions are correct
            self.assertTrue(os.path.exists(data_file_path))
            self.assertTrue(os.path.isfile(data_file_path))
            self.assertTrue(os.path.exists(data2_file_path))
            self.assertTrue(os.path.isfile(data2_file_path))
            # make sure original file gets deleted
            document_model.remove_data_item(data_item)
            self.assertFalse(os.path.exists(data_file_path))
            self.assertFalse(os.path.isfile(data_file_path))
            self.assertTrue(os.path.exists(data2_file_path))
            self.assertTrue(os.path.isfile(data2_file_path))
            # clean up
            document_model = None
            storage_cache.close()
            storage_cache = None
            datastore.close()
            datastore = None
            # read it back
            data_reference_handler = Application.DataReferenceHandler(workspace_dir)
            datastore = Storage.DbDatastore(data_reference_handler, db_name)
            storage_cache = Storage.DbStorageCache(db_name)
            document_model = DocumentModel.DocumentModel(datastore, storage_cache)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertTrue(os.path.isfile(data2_file_path))
            # make sure dependent gets deleted
            document_model.remove_data_item(document_model.data_items[0])
            self.assertFalse(os.path.exists(data2_file_path))
            # clean up
            document_model.close()
            document_model = None
            storage_cache.close()
            storage_cache = None
            datastore.close()
            datastore = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
