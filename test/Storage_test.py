# standard libraries
import copy
import logging
import os
import shutil
import threading
import unittest
import uuid

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
        data_item.maybe_data_source.set_intensity_calibration(Calibration.Calibration(1.0, 2.0, "three"))
        with data_item.open_metadata("test") as metadata:
            metadata["one"] = 1
        data_item.add_region(Region.PointRegion())
        data_item.add_region(Region.LineRegion())
        data_item.add_region(Region.RectRegion())
        data_item.add_region(Region.EllipseRegion())
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
        data_group.append_data_item(data_item2a)
        data_group.append_data_item(data_item2b)
        document_controller.document_model.append_data_item(data_item2a)
        document_controller.document_model.append_data_item(data_item2b)
        image_panel = ImagePanel.ImagePanel(document_controller)
        document_controller.selected_image_panel = image_panel
        image_panel.set_displayed_data_item(data_item)
        self.assertEqual(document_controller.selected_data_item, data_item)
        document_controller.add_line_region()
        document_controller.add_rectangle_region()
        document_controller.add_ellipse_region()
        document_controller.add_point_region()
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
        image_panel.canvas_item.close()
        image_panel.close()

    def test_save_document(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)

    def test_save_load_document(self):
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        data_items_count = len(document_controller.document_model.data_items)
        data_items_type = type(document_controller.document_model.data_items)
        document_controller.close()
        # read it back
        storage_cache = Storage.DictStorageCache()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.assertEqual(data_items_count, len(document_controller.document_model.data_items))
        self.assertEqual(data_items_type, type(document_controller.document_model.data_items))
        document_controller.close()

    def test_storage_cache_closing_twice_throws_exception(self):
        storage_cache = Storage.DbStorageCache(":memory:")
        with self.assertRaises(AssertionError):
            storage_cache.close()
            storage_cache.close()

    def test_storage_cache_validates_data_range_upon_reading(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        try:
            storage_cache = Storage.DictStorageCache()
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            data_range = data_item.maybe_data_source.data_range
            document_model.close()
            # read it back
            storage_cache = Storage.DictStorageCache()
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            self.assertEqual(document_model.data_items[0].maybe_data_source.data_range, data_range)
            document_model.close()
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_storage_cache_stores_and_reloads_cached_statistics_values(self):
        # tests caching on data item
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        cache_name = os.path.join(workspace_dir, "Data.cache")
        try:
            storage_cache = Storage.DbStorageCache(cache_name)
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            stats1 = copy.deepcopy(data_item.get_processed_data("statistics"))
            data_item.get_processor("statistics").recompute_data(None)
            stats2 = copy.deepcopy(data_item.get_processed_data("statistics"))
            document_model.close()
            self.assertNotEqual(stats1, stats2)
            # read it back
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            stats3 = copy.deepcopy(document_model.data_items[0].get_processed_data("statistics"))
            self.assertEqual(stats2, stats3)
            document_model.close()
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_storage_cache_stores_and_reloads_cached_histogram_values(self):
        # tests caching on display
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        cache_name = os.path.join(workspace_dir, "Data.cache")
        try:
            storage_cache = Storage.DbStorageCache(cache_name)
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            histogram1 = numpy.copy(data_item.displays[0].get_processed_data("histogram"))
            data_item.displays[0].get_processor("histogram").recompute_data(None)
            histogram2 = numpy.copy(data_item.displays[0].get_processed_data("histogram"))
            document_model.close()
            self.assertFalse(numpy.array_equal(histogram1, histogram2))
            # read it back
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            histogram3 = numpy.copy(document_model.data_items[0].displays[0].get_processed_data("histogram"))
            self.assertTrue(numpy.array_equal(histogram2, histogram3))
            document_model.close()
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_save_load_document_to_files(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        cache_name = os.path.join(workspace_dir, "Data.cache")
        try:
            storage_cache = Storage.DbStorageCache(cache_name)
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
            self.save_document(document_controller)
            data_items_count = len(document_controller.document_model.data_items)
            data_items_type = type(document_controller.document_model.data_items)
            # clean up
            document_controller.close()
            document_controller = None
            document_model = None
            storage_cache = None
            # read it back
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            self.assertEqual(data_items_count, len(document_model.data_items))
            self.assertEqual(data_items_type, type(document_model.data_items))
            # clean up
            document_model.close()
            document_model = None
            storage_cache = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def write_read_db_storage(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        library_storage = DocumentModel.FilePersistentStorage()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        document_model_uuid = document_controller.document_model.uuid
        data_items_count = len(document_controller.document_model.data_items)
        data_items_type = type(document_controller.document_model.data_items)
        data_item0_calibration_len = len(document_controller.document_model.data_items[0].maybe_data_source.dimensional_calibrations)
        data_item0_uuid = document_controller.document_model.data_items[0].uuid
        data_item1_data_items_len = len(document_controller.document_model.get_dependent_data_items(document_controller.document_model.data_items[1]))
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.assertEqual(document_model_uuid, document_controller.document_model.uuid)
        self.assertEqual(data_items_count, len(document_controller.document_model.data_items))
        self.assertEqual(data_items_type, type(document_controller.document_model.data_items))
        self.assertIsNotNone(document_controller.document_model.data_items[0])
        with document_controller.document_model.data_items[0].maybe_data_source.data_ref() as data_ref:
            self.assertIsNotNone(data_ref.data)
        self.assertEqual(data_item0_uuid, document_controller.document_model.data_items[0].uuid)
        self.assertEqual(data_item0_calibration_len, len(document_controller.document_model.data_items[0].maybe_data_source.dimensional_calibrations))
        new_data_item1_data_items_len = len(document_controller.document_model.get_dependent_data_items(document_controller.document_model.data_items[1]))
        self.assertEqual(data_item1_data_items_len, new_data_item1_data_items_len)
        # check over the data item
        data_item = document_controller.document_model.data_items[0]
        self.assertEqual(data_item.displays[0].display_limits, (500, 1000))
        self.assertEqual(data_item.maybe_data_source.intensity_calibration.offset, 1.0)
        self.assertEqual(data_item.maybe_data_source.intensity_calibration.scale, 2.0)
        self.assertEqual(data_item.maybe_data_source.intensity_calibration.units, "three")
        self.assertEqual(data_item.get_metadata("test")["one"], 1)
        document_controller.close()

    def test_db_storage(self):
        self.write_read_db_storage()

    # test whether we can update master_data and have it written to the db
    def test_db_storage_write_data(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
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
        with data_item.maybe_data_source.data_ref() as data_ref:
            data_ref.master_data = data2
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with document_controller.document_model.data_items[0].maybe_data_source.data_ref() as data_ref:
            self.assertEqual(data_ref.data[0,0], 2)

    def update_data(self, data_item):
        data2 = numpy.zeros((16, 16), numpy.uint32)
        data2[0,0] = 2
        with data_item.maybe_data_source.data_ref() as data_ref:
            data_ref.master_data = data2

    # test whether we can update the db from a thread
    def test_db_storage_write_on_thread(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
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
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with document_controller.document_model.data_items[0].maybe_data_source.data_ref() as data_ref:
            self.assertEqual(data_ref.data[0,0], 2)

    def test_storage_insert_items(self):
        cache_name = ":memory:"
        storage_cache = Storage.DbStorageCache(cache_name)
        library_storage = DocumentModel.FilePersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage, storage_cache=storage_cache)
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
        document_model = DocumentModel.DocumentModel()
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
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        with self.assertRaises(AssertionError):
            document_model.append_data_item(data_item)

    # make sure thumbnail raises exception if a bad operation is involved
    def test_adding_data_item_to_data_group_twice_raises_exception(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        document_model.data_groups[0].append_data_item(data_item)
        with self.assertRaises(AssertionError):
            document_model.data_groups[0].append_data_item(data_item)

    def test_insert_item_with_transaction(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        data_group = DataGroup.DataGroup()
        document_model.append_data_group(data_group)
        data_item = DataItem.DataItem()
        data_item.append_data_source(DataItem.BufferedDataSource())
        data_item.title = 'title'
        with data_item.transaction():
            with data_item.maybe_data_source.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
            document_model.append_data_item(data_item)
            data_group.append_data_item(data_item)
        # make sure it reloads
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
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
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        data_item = DataItem.DataItem()
        document_model.append_data_item(data_item)
        with data_item.transaction():
            data_item.datetime_original = reference_date
        # make sure it reloads
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        self.assertEqual(document_model.data_items[0].datetime_original, reference_date)

    def test_data_writes_to_and_reloads_from_file(self):
        reference_date = {'dst': '+00', 'tz': '-0800', 'local_datetime': '2000-06-30T15:02:00.000000'}
        cache_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        try:
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
            data_item = DataItem.DataItem()
            data_item.append_data_source(DataItem.BufferedDataSource())
            data_item.datetime_original = reference_date
            with data_item.maybe_data_source.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
            document_model.append_data_item(data_item)
            reference_type, reference = data_item.get_data_file_info()
            self.assertEqual(reference_type, "relative_file")
            data_file_path = os.path.join(current_working_directory, "__Test", "Nion Swift Data", reference + ".ndata")
            self.assertTrue(os.path.exists(data_file_path))
            self.assertTrue(os.path.isfile(data_file_path))
            # make sure the data reloads
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
            with document_model.data_items[0].maybe_data_source.data_ref() as data_ref:
                self.assertIsNotNone(data_ref.data)
            # and then make sure the data file gets removed on disk when removed
            document_model.remove_data_item(document_model.data_items[0])
            self.assertFalse(os.path.exists(data_file_path))
            # clean up
            document_model.close()
            document_model = None
            storage_cache = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_writing_empty_data_item_returns_expected_values(self):
        cache_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        try:
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
            data_item = DataItem.DataItem()
            data_item.append_data_source(DataItem.BufferedDataSource())
            document_model.append_data_item(data_item)
            reference_type, reference = data_item.get_data_file_info()
            self.assertFalse(data_item.maybe_data_source.has_data)
            self.assertIsNone(data_item.maybe_data_source.data_shape)
            self.assertIsNone(data_item.maybe_data_source.data_dtype)
            self.assertEqual(reference_type, "relative_file")
            self.assertIsNotNone(reference)
            # clean up
            document_model.close()
            document_model = None
            storage_cache = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_data_writes_to_file_after_transaction(self):
        cache_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        try:
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
            data_item = DataItem.DataItem()
            data_item.append_data_source(DataItem.BufferedDataSource())
            document_model.append_data_item(data_item)
            # write data with transaction
            handler = NDataHandler.NDataHandler(os.path.join(current_working_directory, "__Test", "Nion Swift Data"))
            with data_item.transaction():
                with data_item.maybe_data_source.data_ref() as data_ref:
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
            storage_cache = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_data_removes_file_after_original_date_and_session_change(self):
        reference_date = {'dst': '+00', 'tz': '-0800', 'local_datetime': '2000-06-30T15:02:00.000000'}
        cache_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        try:
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
            data_item = DataItem.DataItem()
            data_item.append_data_source(DataItem.BufferedDataSource())
            data_item.datetime_original = reference_date
            with data_item.maybe_data_source.data_ref() as data_ref:
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
            storage_cache = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_reloading_data_item_with_display_builds_drawn_graphics_properly(self):
        cache_name = ":memory:"
        storage_cache = Storage.DbStorageCache(cache_name)
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        self.assertEqual(len(document_model.data_items[0].displays[0].drawn_graphics), 9)  # verify assumptions
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # verify drawn_graphics reload
        self.assertEqual(len(document_model.data_items[0].displays[0].drawn_graphics), 9)
        # clean up
        document_controller.close()

    def test_writing_empty_data_item_followed_by_writing_data_adds_correct_calibrations(self):
        # this failed due to a key aliasing issue.
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # create empty data item
        data_item = DataItem.DataItem()
        data_item.append_data_source(DataItem.BufferedDataSource())
        document_model.append_data_item(data_item)
        data_item.begin_transaction()
        with data_item.maybe_data_source.data_ref() as data_ref:
            data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
        data_item.end_transaction()
        self.assertEqual(len(data_item.maybe_data_source.dimensional_calibrations), 2)
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # verify calibrations
        self.assertEqual(len(document_model.data_items[0].maybe_data_source.dimensional_calibrations), 2)
        # clean up
        document_controller.close()

    def test_reloading_data_item_establishes_display_connection_to_storage(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # clean up
        document_controller.close()

    def test_reloading_data_item_establishes_operation_connection_to_storage(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        invert_operation = Operation.OperationItem("invert-operation")
        data_item.set_operation(invert_operation)
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # clean up
        document_controller.close()

    def test_changes_to_operation_values_are_saved(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        gaussian_operation = Operation.OperationItem("gaussian-blur-operation")
        data_item.set_operation(gaussian_operation)
        gaussian_operation.set_property("sigma", 1.7)
        # read it back
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # verify that properties read it correctly
        self.assertAlmostEqual(document_model.data_items[0].operation.get_property("sigma"), 1.7)
        # clean up
        document_controller.close()

    def test_reloaded_line_profile_operation_binds_to_roi(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item2 = DataItem.DataItem()
        document_model.append_data_item(data_item2)
        line_profile_operation = Operation.OperationItem("line-profile-operation")
        line_profile_operation.set_property("vector", ((0.1, 0.2), (0.3, 0.4)))
        line_profile_operation.establish_associated_region("line", data_item)
        line_profile_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item2.set_operation(line_profile_operation)
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # verify that properties read it correctly
        self.assertEqual(document_model.data_items[0].regions[0].start, (0.1, 0.2))
        self.assertEqual(document_model.data_items[0].regions[0].end, (0.3, 0.4))
        start,end = document_model.data_items[1].operation.values["vector"]
        self.assertEqual(start, (0.1, 0.2))
        self.assertEqual(end, (0.3, 0.4))
        document_model.data_items[0].regions[0].start = 0.11, 0.22
        start,end = document_model.data_items[1].operation.values["vector"]
        self.assertEqual(start, (0.11, 0.22))
        self.assertEqual(end, (0.3, 0.4))
        # clean up
        document_controller.close()

    def test_reloaded_graphics_load_properly(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        rect_graphic = Graphics.RectangleGraphic()
        rect_graphic.bounds = ((0.25, 0.25), (0.5, 0.5))
        data_item.displays[0].append_graphic(rect_graphic)
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # verify
        self.assertEqual(len(document_model.data_items[0].displays[0].graphics), 1)
        # clean up
        document_controller.close()

    def test_reloaded_regions_load_properly(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        point_region = Region.PointRegion()
        point_region.position = (0.6, 0.4)
        point_region_uuid = point_region.uuid
        data_item.add_region(point_region)
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # verify
        self.assertEqual(document_model.data_items[0].regions[0].type, "point-region")
        self.assertEqual(document_model.data_items[0].regions[0].uuid, point_region_uuid)
        self.assertEqual(document_model.data_items[0].regions[0].position, (0.6, 0.4))
        # clean up
        document_controller.close()

    def test_reloaded_empty_data_groups_load_properly(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_group = DataGroup.DataGroup()
        document_model.append_data_group(data_group)
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # clean up
        document_controller.close()

    def test_new_data_item_stores_uuid_and_data_info_in_properties_immediately(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        self.assertTrue("data_shape" in data_item.properties.get("data_sources")[0])
        self.assertTrue("data_dtype" in data_item.properties.get("data_sources")[0])
        self.assertTrue("uuid" in data_item.properties)
        self.assertTrue("version" in data_item.properties)

    def test_deleting_dependent_after_deleting_source_succeeds(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        cache_name = os.path.join(workspace_dir, "Data.cache")
        try:
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
            data_item = DataItem.DataItem()
            data_item.append_data_source(DataItem.BufferedDataSource())
            with data_item.maybe_data_source.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
            document_model.append_data_item(data_item)
            data_item2 = DataItem.DataItem()
            invert_operation = Operation.OperationItem("invert-operation")
            invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
            data_item2.set_operation(invert_operation)
            document_model.append_data_item(data_item2)
            reference_type, reference = data_item.get_data_file_info()
            reference_type, reference2 = data_item2.get_data_file_info()
            data_file_path = os.path.join(current_working_directory, "__Test", "Nion Swift Data", reference + ".ndata")
            data2_file_path = os.path.join(current_working_directory, "__Test", "Nion Swift Data", reference2 + ".ndata")
            # make sure assumptions are correct
            self.assertTrue(os.path.exists(data_file_path))
            self.assertTrue(os.path.isfile(data_file_path))
            self.assertTrue(os.path.exists(data2_file_path))
            self.assertTrue(os.path.isfile(data2_file_path))
            # clean up
            document_model.close()
            document_model = None
            storage_cache = None
            # delete the original file
            os.remove(data_file_path)
            # read it back the library
            data_reference_handler = Application.DataReferenceHandler(workspace_dir)
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
            self.assertEqual(len(document_model.data_items), 1)
            self.assertTrue(os.path.isfile(data2_file_path))
            # make sure dependent gets deleted
            document_model.remove_data_item(document_model.data_items[0])
            self.assertFalse(os.path.exists(data2_file_path))
            # clean up
            document_model.close()
            document_model = None
            storage_cache = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_reloaded_display_has_correct_storage_cache(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # check storage caches
        self.assertEqual(document_model.data_items[0].storage_cache, storage_cache)
        self.assertEqual(document_model.data_items[0].displays[0].storage_cache, storage_cache)
        # clean up
        document_controller.close()

    def test_data_items_written_with_newer_version_get_ignored(self):
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        # increment the version on the data item
        data_reference_handler.properties.values()[0]["version"] = data_item.writer_version + 1
        # read it back
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        # check it
        self.assertEqual(len(document_model.data_items), 0)

    def test_reloading_composite_operation_reconnects_when_reloaded(self):
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float))
        document_model.append_data_item(data_item)
        crop_region = Region.RectRegion()
        crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
        data_item.add_region(crop_region)
        image_panel = document_controller.selected_image_panel
        image_panel.set_displayed_data_item(data_item)
        operation = Operation.OperationItem("invert-operation")
        document_controller.add_processing_operation(operation, crop_region=crop_region)
        document_model.close()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        self.assertEqual(document_model.data_items[0].regions[0].bounds, document_model.data_items[1].operation.data_sources[0].get_property("bounds"))
        document_model.data_items[0].regions[0].bounds = ((0.3, 0.4), (0.5, 0.6))
        self.assertEqual(document_model.data_items[0].regions[0].bounds, document_model.data_items[1].operation.data_sources[0].get_property("bounds"))

    def test_inverted_data_item_does_not_need_recompute_when_reloaded(self):
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted.recompute_data()
        document_model.close()
        # reload and check inverted data item does not need recompute
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        self.assertFalse(document_model.data_items[1].maybe_data_source.is_data_stale)

    def test_cropped_data_item_with_region_does_not_need_recompute_when_reloaded(self):
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float))
        document_model.append_data_item(data_item)
        data_item_cropped = DataItem.DataItem()
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_cropped.set_operation(crop_operation)
        crop_operation.establish_associated_region("crop", data_item)
        document_model.append_data_item(data_item_cropped)
        data_item_cropped.recompute_data()
        self.assertFalse(document_model.data_items[1].maybe_data_source.is_data_stale)
        document_model.close()
        # reload and check inverted data item does not need recompute
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        self.assertFalse(document_model.data_items[1].maybe_data_source.is_data_stale)

    def test_cropped_data_item_with_region_still_updates_when_reloaded(self):
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float))
        document_model.append_data_item(data_item)
        data_item_cropped = DataItem.DataItem()
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_cropped.set_operation(crop_operation)
        crop_operation.establish_associated_region("crop", data_item)
        document_model.append_data_item(data_item_cropped)
        data_item_cropped.recompute_data()
        self.assertFalse(document_model.data_items[1].maybe_data_source.is_data_stale)
        document_model.close()
        # reload and check inverted data item does not need recompute
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        document_model.recompute_all()  # shouldn't be necessary unless other tests fail
        document_model.data_items[0].regions[0].bounds = (0.25, 0.25), (0.5, 0.5)
        self.assertTrue(document_model.data_items[1].maybe_data_source.is_data_stale)
        document_model.recompute_all()
        self.assertEqual(document_model.data_items[1].maybe_data_source.data_shape, (128, 128))

    def test_cropped_data_item_with_region_does_not_need_histogram_recompute_when_reloaded(self):
        # tests caching on display
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        cache_name = os.path.join(workspace_dir, "Data.cache")
        try:
            storage_cache = Storage.DbStorageCache(cache_name)
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            data_item_cropped = DataItem.DataItem()
            crop_operation = Operation.OperationItem("crop-operation")
            crop_operation.add_data_source(Operation.DataItemDataSource(data_item))
            data_item_cropped.set_operation(crop_operation)
            crop_operation.establish_associated_region("crop", data_item)
            document_model.append_data_item(data_item_cropped)
            data_item_cropped.recompute_data()
            histogram1 = numpy.copy(data_item_cropped.displays[0].get_processed_data("histogram"))
            data_item_cropped.displays[0].get_processor("histogram").recompute_data(None)
            histogram2 = numpy.copy(data_item_cropped.displays[0].get_processed_data("histogram"))
            document_model.close()
            self.assertFalse(numpy.array_equal(histogram1, histogram2))
            # read it back
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            histogram3 = numpy.copy(document_model.data_items[1].displays[0].get_processed_data("histogram"))
            self.assertTrue(numpy.array_equal(histogram2, histogram3))
            document_model.close()
            storage_cache = None
            document_model = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_data_items_v1_migration(self):
        # construct v1 data item
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        data_item_dict = data_reference_handler.properties.setdefault("A", dict())
        data_item_dict["spatial_calibrations"] = [{ "origin": 1.0, "scale": 2.0, "units": "mm" }, { "origin": 1.0, "scale": 2.0, "units": "mm" }]
        data_item_dict["intensity_calibration"] = { "origin": 0.1, "scale": 0.2, "units": "l" }
        data_item_dict["data_source_uuid"] = str(uuid.uuid4())
        data_item_dict["properties"] = { "voltage": 200.0, "session_uuid": str(uuid.uuid4()) }
        data_item_dict["version"] = 1
        data_reference_handler.data["A"] = numpy.zeros((256, 256), numpy.uint32)
        # read it back
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, log_migrations=False)
        # check it
        self.assertEqual(len(document_model.data_items), 1)
        data_item = document_model.data_items[0]
        self.assertEqual(data_item.properties["version"], data_item.writer_version)
        self.assertEqual(len(data_item.maybe_data_source.dimensional_calibrations), 2)
        self.assertEqual(data_item.maybe_data_source.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(data_item.maybe_data_source.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(data_item.maybe_data_source.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))
        self.assertEqual(data_item.get_metadata("hardware_source")["voltage"], 200.0)
        self.assertFalse("session_uuid" in data_item.get_metadata("hardware_source"))
        self.assertIsNone(data_item.session_id)  # v1 is not allowed to set session_id
        self.assertEqual(data_item.maybe_data_source.data_dtype, numpy.uint32)
        self.assertEqual(data_item.maybe_data_source.data_shape, (256, 256))

    def test_data_items_v2_migration(self):
        # construct v2 data item
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        data_item_dict = data_reference_handler.properties.setdefault("A", dict())
        data_item_dict["displays"] = [{"graphics": [{"type": "rect-graphic"}]}]
        data_item_dict["operations"] = [{"operation_id": "invert-operation"}]
        data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_item_dict["master_data_shape"] = (256, 256)
        data_item_dict["version"] = 2
        data_reference_handler.data["A"] = numpy.zeros((256, 256), numpy.uint32)
        # read it back
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, log_migrations=False)
        # check it
        self.assertEqual(len(document_model.data_items), 1)
        data_item = document_model.data_items[0]
        self.assertEqual(data_item.properties["version"], data_item.writer_version)
        self.assertTrue("uuid" in data_item.properties["displays"][0])
        self.assertTrue("uuid" in data_item.properties["displays"][0]["graphics"][0])
        self.assertTrue("uuid" in data_item.properties["data_sources"][0]["data_source"])

    def test_data_items_v3_migration(self):
        # construct v3 data item
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        data_item_dict = data_reference_handler.properties.setdefault("A", dict())
        data_item_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_item_dict["intrinsic_spatial_calibrations"] = [{ "origin": 1.0, "scale": 2.0, "units": "mm" }, { "origin": 1.0, "scale": 2.0, "units": "mm" }]
        data_item_dict["intrinsic_intensity_calibration"] = { "origin": 0.1, "scale": 0.2, "units": "l" }
        data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_item_dict["master_data_shape"] = (256, 256)
        data_item_dict["version"] = 3
        data_reference_handler.data["A"] = numpy.zeros((256, 256), numpy.uint32)
        # read it back
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, log_migrations=False)
        # check it
        self.assertEqual(len(document_model.data_items), 1)
        data_item = document_model.data_items[0]
        self.assertEqual(data_item.properties["version"], data_item.writer_version)
        self.assertEqual(len(data_item.maybe_data_source.dimensional_calibrations), 2)
        self.assertEqual(data_item.maybe_data_source.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(data_item.maybe_data_source.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(data_item.maybe_data_source.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))

    def test_data_items_v4_migration(self):
        # construct v4 data item
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        data_item_dict = data_reference_handler.properties.setdefault("A", dict())
        data_item_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        region_uuid_str = str(uuid.uuid4())
        data_item_dict["regions"] = [{"type": "rectangle-region", "uuid": region_uuid_str}]
        data_item_dict["operations"] = [{"operation_id": "crop-operation", "region_uuid": region_uuid_str}]
        data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_item_dict["master_data_shape"] = (256, 256)
        data_item_dict["version"] = 4
        data_reference_handler.data["A"] = numpy.zeros((256, 256), numpy.uint32)
        # read it back
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, log_migrations=False)
        # check it
        self.assertEqual(len(document_model.data_items), 1)
        data_item = document_model.data_items[0]
        self.assertEqual(data_item.properties["version"], data_item.writer_version)
        self.assertEqual(len(data_item.operation.region_connections), 1)
        self.assertEqual(data_item.operation.region_connections["crop"], uuid.UUID(region_uuid_str))
        self.assertFalse("region_uuid" in data_item.properties["data_sources"][0]["data_source"])

    def test_data_items_v5_migration(self):
        # construct v5 data item
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        data_item_dict = data_reference_handler.properties.setdefault("A", dict())
        data_item_dict["uuid"] = str(uuid.uuid4())
        data_item_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_item_dict["master_data_shape"] = (256, 256)
        data_item_dict["intrinsic_spatial_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        data_item_dict["intrinsic_intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        data_item_dict["version"] = 5
        data_reference_handler.data["A"] = numpy.zeros((256, 256), numpy.uint32)
        data_item2_dict = data_reference_handler.properties.setdefault("B", dict())
        data_item2_dict["uuid"] = str(uuid.uuid4())
        data_item2_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_item2_dict["operations"] = [{"operation_id": "invert-operation"}]
        data_item2_dict["data_sources"] = [data_item_dict["uuid"]]
        data_item2_dict["version"] = 5
        # read it back
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, log_migrations=False)
        # check it
        self.assertEqual(len(document_model.data_items), 2)
        self.assertEqual(str(document_model.data_items[0].uuid), data_item_dict["uuid"])
        self.assertEqual(str(document_model.data_items[1].uuid), data_item2_dict["uuid"])
        data_item = document_model.data_items[1]
        self.assertEqual(data_item.properties["version"], data_item.writer_version)
        self.assertIsNotNone(data_item.operation)
        self.assertEqual(len(data_item.operation.data_sources), 1)
        self.assertEqual(str(data_item.operation.data_sources[0].data_item.uuid), data_item_dict["uuid"])
        # calibration renaming
        data_item = document_model.data_items[0]
        self.assertEqual(len(data_item.maybe_data_source.dimensional_calibrations), 2)
        self.assertEqual(data_item.maybe_data_source.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(data_item.maybe_data_source.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(data_item.maybe_data_source.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))

    def test_data_items_v6_migration(self):
        # construct v6 data item
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        data_item_dict = data_reference_handler.properties.setdefault("A", dict())
        data_item_dict["uuid"] = str(uuid.uuid4())
        data_item_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_item_dict["master_data_shape"] = (256, 256)
        data_item_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        data_item_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        data_item_dict["version"] = 6
        data_reference_handler.data["A"] = numpy.zeros((256, 256), numpy.uint32)
        data_item2_dict = data_reference_handler.properties.setdefault("B", dict())
        data_item2_dict["uuid"] = str(uuid.uuid4())
        data_item2_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_item2_dict["operation"] = {"type": "operation", "operation_id": "invert-operation", "data_sources": [{"type": "data-item-data-source", "data_item_uuid": data_item_dict["uuid"]}]}
        data_item2_dict["version"] = 6
        # read it back
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, log_migrations=False)
        # # check it
        self.assertEqual(len(document_model.data_items), 2)
        self.assertEqual(str(document_model.data_items[0].uuid), data_item_dict["uuid"])
        self.assertEqual(str(document_model.data_items[1].uuid), data_item2_dict["uuid"])
        data_item = document_model.data_items[1]
        self.assertEqual(data_item.properties["version"], data_item.writer_version)
        self.assertIsNotNone(data_item.operation)
        self.assertEqual(len(data_item.operation.data_sources), 1)
        self.assertEqual(str(data_item.operation.data_sources[0].data_item.uuid), data_item_dict["uuid"])
        # calibration renaming
        data_item = document_model.data_items[0]
        self.assertEqual(len(data_item.maybe_data_source.dimensional_calibrations), 2)
        self.assertEqual(data_item.maybe_data_source.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(data_item.maybe_data_source.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(data_item.maybe_data_source.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
