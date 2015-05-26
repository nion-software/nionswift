# futures
from __future__ import absolute_import

# standard libraries
import copy
import datetime
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
from nion.swift import DisplayPanel
from nion.swift import NDataHandler
from nion.swift.model import Calibration
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
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
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_specifier.display.display_limits = (500, 1000)
        display_specifier.buffered_data_source.set_intensity_calibration(Calibration.Calibration(1.0, 2.0, "three"))
        metadata = data_item.metadata
        metadata.setdefault("test", dict())["one"] = 1
        data_item.set_metadata(metadata)
        buffered_data_source = DataItem.DisplaySpecifier.from_data_item(data_item).buffered_data_source
        buffered_data_source.add_region(Region.PointRegion())
        buffered_data_source.add_region(Region.LineRegion())
        buffered_data_source.add_region(Region.RectRegion())
        buffered_data_source.add_region(Region.EllipseRegion())
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
        data_item2a.append_data_source(DataItem.BufferedDataSource())
        data_item2b = DataItem.DataItem()
        data_item2b.append_data_source(DataItem.BufferedDataSource())
        data_group.append_data_item(data_item2a)
        data_group.append_data_item(data_item2b)
        document_controller.document_model.append_data_item(data_item2a)
        document_controller.document_model.append_data_item(data_item2b)
        display_panel = DisplayPanel.DisplayPanel(document_controller, dict())
        document_controller.selected_display_panel = display_panel
        display_panel.set_displayed_data_item(data_item)
        self.assertEqual(document_controller.selected_display_specifier.data_item, data_item)
        document_controller.add_line_region()
        document_controller.add_rectangle_region()
        document_controller.add_ellipse_region()
        document_controller.add_point_region()
        display_panel.set_displayed_data_item(data_item)
        document_controller.processing_gaussian_blur()
        display_panel.set_displayed_data_item(data_item)
        document_controller.processing_resample()
        display_panel.set_displayed_data_item(data_item)
        document_controller.processing_invert()
        display_panel.set_displayed_data_item(data_item)
        document_controller.processing_crop()
        display_panel.set_displayed_data_item(data_item2)
        self.assertEqual(document_controller.selected_display_specifier.data_item, data_item2)
        document_controller.processing_fft()
        document_controller.processing_ifft()
        display_panel.canvas_item.close()
        display_panel.close()

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
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_range = display_specifier.buffered_data_source.data_range
            document_model.close()
            # read it back
            storage_cache = Storage.DictStorageCache()
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            read_data_item = document_model.data_items[0]
            read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
            self.assertEqual(read_display_specifier.buffered_data_source.data_range, data_range)
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
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            stats1 = copy.deepcopy(display_specifier.buffered_data_source.get_processed_data("statistics"))
            display_specifier.buffered_data_source.get_processor("statistics").recompute_data(None)
            stats2 = copy.deepcopy(display_specifier.buffered_data_source.get_processed_data("statistics"))
            document_model.close()
            self.assertNotEqual(stats1, stats2)
            # read it back
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            read_data_item = document_model.data_items[0]
            read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
            stats3 = copy.deepcopy(read_display_specifier.buffered_data_source.get_processed_data("statistics"))
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
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            histogram1 = numpy.copy(display_specifier.display.get_processed_data("histogram"))
            display_specifier.display.get_processor("histogram").recompute_data(None)
            histogram2 = numpy.copy(display_specifier.display.get_processed_data("histogram"))
            document_model.close()
            self.assertFalse(numpy.array_equal(histogram1, histogram2))
            # read it back
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            read_data_item = document_model.data_items[0]
            read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
            histogram3 = numpy.copy(read_display_specifier.display.get_processed_data("histogram"))
            self.assertTrue(numpy.array_equal(histogram2, histogram3))
            document_model.close()
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_thumbnail_does_not_get_invalidated_upon_reading(self):
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
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            storage_cache.set_cached_value(display_specifier.display, "thumbnail_data", numpy.zeros((128, 128, 4), dtype=numpy.uint8))
            self.assertFalse(storage_cache.is_cached_value_dirty(display_specifier.display, "thumbnail_data"))
            document_model.close()
            # read it back
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            read_data_item = document_model.data_items[0]
            read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
            # thumbnail data should still be valid
            self.assertFalse(storage_cache.is_cached_value_dirty(read_display_specifier.display, "thumbnail_data"))
            document_model.close()
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_reload_data_item_initializes_display_data_range(self):
        storage_cache = Storage.DbStorageCache(":memory:")
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertIsNotNone(display_specifier.buffered_data_source.data_range)
        self.assertIsNotNone(display_specifier.display.data_range)
        # read it back
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        self.assertIsNotNone(display_specifier.buffered_data_source.data_range)
        self.assertIsNotNone(display_specifier.display.data_range)

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

    def test_db_storage(self):
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
        data_item0 = document_controller.document_model.data_items[0]
        data_item1 = document_controller.document_model.data_items[1]
        data_item0_uuid = data_item0.uuid
        data_item1_uuid = data_item1.uuid
        data_item0_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item0)
        data_item0_calibration_len = len(data_item0_display_specifier.buffered_data_source.dimensional_calibrations)
        data_item1_data_items_len = len(document_controller.document_model.get_dependent_data_items(data_item1))
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        new_data_item0 = document_controller.document_model.get_data_item_by_uuid(data_item0_uuid)
        new_data_item0_display_specifier = DataItem.DisplaySpecifier.from_data_item(new_data_item0)
        self.assertIsNotNone(new_data_item0)
        self.assertEqual(document_model_uuid, document_controller.document_model.uuid)
        self.assertEqual(data_items_count, len(document_controller.document_model.data_items))
        self.assertEqual(data_items_type, type(document_controller.document_model.data_items))
        with new_data_item0_display_specifier.buffered_data_source.data_ref() as data_ref:
            self.assertIsNotNone(data_ref.data)
        self.assertEqual(data_item0_uuid, new_data_item0.uuid)
        self.assertEqual(data_item0_calibration_len, len(new_data_item0_display_specifier.buffered_data_source.dimensional_calibrations))
        new_data_item1 = document_controller.document_model.get_data_item_by_uuid(data_item1_uuid)
        new_data_item1_data_items_len = len(document_controller.document_model.get_dependent_data_items(new_data_item1))
        self.assertEqual(data_item1_uuid, new_data_item1.uuid)
        self.assertEqual(data_item1_data_items_len, new_data_item1_data_items_len)
        # check over the data item
        self.assertEqual(new_data_item0_display_specifier.display.display_limits, (500, 1000))
        self.assertEqual(new_data_item0_display_specifier.buffered_data_source.intensity_calibration.offset, 1.0)
        self.assertEqual(new_data_item0_display_specifier.buffered_data_source.intensity_calibration.scale, 2.0)
        self.assertEqual(new_data_item0_display_specifier.buffered_data_source.intensity_calibration.units, "three")
        self.assertEqual(new_data_item0.metadata.get("test")["one"], 1)
        document_controller.close()

    def test_dependencies_load_correctly_when_initially_loaded(self):
        cache_name = ":memory:"
        library_storage = DocumentModel.FilePersistentStorage()
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        data_item1_uuid = uuid.UUID("71ab9215-c6ae-4c36-aaf5-92ce78db02b6")
        # configure list of data items so that after sorted (on modification) they will still be listed in this order.
        # this makes one dependency (86d982d1) load before the main item (71ab9215) and one (7d3b374e) load after.
        # this tests the get_dependent_data_items after reading data.
        data_reference_handler.properties = {'2015/01/22/20150122-000000/data1': {'data_sources': [
            {'data_dtype': None, 'data_shape': None, 'data_source': {'data_sources': [
                {'buffered_data_source_uuid': '0a5db801-04d4-4b10-945d-c751b5127950', 'type': 'data-item-data-source',
                    'uuid': '0d0d47a5-2a35-4391-b7a1-a237f90bf432'}], 'operation_id': 'inverse-fft-operation',
                'type': 'operation', 'uuid': '23b6f59f-e054-47f0-94b7-10e75c652400'}, 'dimensional_calibrations': [],
                'displays': [{'uuid': '7eaddefe-22ca-4a7a-b53f-b1c07f3f8553'}],
                'created': '2015-01-22T17:16:12.421290', 'type': 'buffered-data-source',
                'uuid': '66128bc9-2fd5-47b8-8122-5b57fbfe58d7'}], 'metadata': {},
            'created': '2015-01-22T17:16:12.120937', 'uuid': '86d982d1-6d81-46fa-b19e-574e904902de', 'version': 8},
            '2015/01/22/20150122-000000/data2': {'data_sources': [
                {'data_dtype': 'int64', 'data_shape': (512, 512), 'dimensional_calibrations': [{}, {}],
                    'displays': [{'uuid': '106c5711-e8cd-4fc4-9f9d-9268b35359a2'}],
                    'created': '2015-01-22T17:16:12.319959', 'type': 'buffered-data-source',
                    'uuid': '0a5db801-04d4-4b10-945d-c751b5127950'}], 'metadata': {},
                'created': '2015-01-22T17:16:12.219730', 'uuid': '71ab9215-c6ae-4c36-aaf5-92ce78db02b6', 'version': 8},
            '2015/01/22/20150122-000000/data3': {'data_sources': [{'data_dtype': None, 'data_shape': None,
                'data_source': {'data_sources': [{'buffered_data_source_uuid': '0a5db801-04d4-4b10-945d-c751b5127950',
                    'type': 'data-item-data-source', 'uuid': '183316ac-6cdf-4f74-a4f2-85982e4c63c2'}],
                    'operation_id': 'fft-operation', 'type': 'operation',
                    'uuid': 'b856672f-9d48-46a4-9a48-b0c9847b59a7'}, 'dimensional_calibrations': [],
                'displays': [{'uuid': '7e01b8d6-3f3b-4234-9176-c57dbf2bc029'}],
                'created': '2015-01-22T17:16:12.408454', 'type': 'buffered-data-source',
                'uuid': 'd02f93be-e79a-4b2c-8fe2-0b0d27219251'}], 'metadata': {},
                'created': '2015-01-22T17:16:12.308003', 'uuid': '7d3b374e-e48b-460f-91de-7ff4e1a1a63c', 'version': 8}}
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        new_data_item1 = document_controller.document_model.get_data_item_by_uuid(data_item1_uuid)
        new_data_item1_data_items_len = len(document_controller.document_model.get_dependent_data_items(new_data_item1))
        self.assertEqual(data_item1_uuid, new_data_item1.uuid)
        self.assertEqual(2, new_data_item1_data_items_len)
        document_controller.close()

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
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        data_group = DataGroup.DataGroup()
        data_group.append_data_item(data_item)
        document_controller.document_model.append_data_group(data_group)
        data2 = numpy.zeros((16, 16), numpy.uint32)
        data2[0,0] = 2
        with display_specifier.buffered_data_source.data_ref() as data_ref:
            data_ref.master_data = data2
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = document_controller.document_model.data_items[0]
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        with display_specifier.buffered_data_source.data_ref() as data_ref:
            self.assertEqual(data_ref.data[0,0], 2)

    def update_data(self, data_item):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        data2 = numpy.zeros((16, 16), numpy.uint32)
        data2[0,0] = 2
        with display_specifier.buffered_data_source.data_ref() as data_ref:
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
        read_data_item = document_controller.document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        with read_display_specifier.buffered_data_source.data_ref() as data_ref:
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
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        with document_model.data_item_transaction(data_item):
            with display_specifier.buffered_data_source.data_ref() as data_ref:
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
        document_model.begin_data_item_transaction(data_item1)
        document_model.begin_data_item_transaction(data_item2)
        document_model.end_data_item_transaction(data_item1)
        document_model.begin_data_item_transaction(data_item3)
        document_model.end_data_item_transaction(data_item3)
        document_model.end_data_item_transaction(data_item2)

    def test_data_item_modification_should_not_change_when_reading(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        data_item = DataItem.DataItem()
        data_item.append_data_source(DataItem.BufferedDataSource())
        document_model.append_data_item(data_item)
        data_item._set_modified(modified)
        # make sure it reloads
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        self.assertEqual(document_model.data_items[0].modified, modified)

    def test_data_item_should_store_modifications_within_transactions(self):
        created = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        data_item = DataItem.DataItem()
        data_item.append_data_source(DataItem.BufferedDataSource())
        document_model.append_data_item(data_item)
        with document_model.data_item_transaction(data_item):
            data_item.created = created
        # make sure it reloads
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        self.assertEqual(document_model.data_items[0].created, created)

    def test_data_writes_to_and_reloads_from_file(self):
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
            data_item.created = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            with display_specifier.buffered_data_source.data_ref() as data_ref:
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
            read_data_item = document_model.data_items[0]
            read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
            with read_display_specifier.buffered_data_source.data_ref() as data_ref:
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
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            reference_type, reference = data_item.get_data_file_info()
            self.assertFalse(display_specifier.buffered_data_source.has_data)
            self.assertIsNone(display_specifier.buffered_data_source.data_shape)
            self.assertIsNone(display_specifier.buffered_data_source.data_dtype)
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
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            # write data with transaction
            handler = NDataHandler.NDataHandler(os.path.join(current_working_directory, "__Test", "Nion Swift Data"))
            with document_model.data_item_transaction(data_item):
                with display_specifier.buffered_data_source.data_ref() as data_ref:
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
        created = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
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
            data_item.created = created
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
            document_model.append_data_item(data_item)
            reference_type, reference = data_item.get_data_file_info()
            data_file_path = os.path.join(current_working_directory, "__Test", "Nion Swift Data", reference + ".ndata")
            # make sure it get written to disk
            self.assertTrue(os.path.exists(data_file_path))
            self.assertTrue(os.path.isfile(data_file_path))
            # change the original date
            data_item.created = datetime.datetime.utcnow()
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
        read_data_item = document_model.data_items[0]
        read_data_item_uuid = read_data_item.uuid
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        self.assertEqual(len(read_display_specifier.display.drawn_graphics), 9)  # verify assumptions
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        read_data_item = document_model.get_data_item_by_uuid(read_data_item_uuid)
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        # verify drawn_graphics reload
        self.assertEqual(len(read_display_specifier.display.drawn_graphics), 9)
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
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        with document_model.data_item_transaction(data_item):
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
        self.assertEqual(len(display_specifier.buffered_data_source.dimensional_calibrations), 2)
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        read_data_item = document_controller.document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        # verify calibrations
        self.assertEqual(len(read_display_specifier.buffered_data_source.dimensional_calibrations), 2)
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
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        data_item2 = DataItem.DataItem()
        document_model.append_data_item(data_item2)
        line_profile_operation = Operation.OperationItem("line-profile-operation")
        line_profile_operation.set_property("vector", ((0.1, 0.2), (0.3, 0.4)))
        line_profile_operation.establish_associated_region("line", display_specifier.buffered_data_source)
        line_profile_operation.add_data_source(data_item._create_test_data_source())
        data_item2.set_operation(line_profile_operation)
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        read_data_item = document_controller.document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        # verify that properties read it correctly
        self.assertEqual(read_display_specifier.buffered_data_source.regions[0].start, (0.1, 0.2))
        self.assertEqual(read_display_specifier.buffered_data_source.regions[0].end, (0.3, 0.4))
        start,end = document_model.data_items[1].operation.values["vector"]
        self.assertEqual(start, (0.1, 0.2))
        self.assertEqual(end, (0.3, 0.4))
        read_display_specifier.buffered_data_source.regions[0].start = 0.11, 0.22
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
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        rect_graphic = Graphics.RectangleGraphic()
        rect_graphic.bounds = ((0.25, 0.25), (0.5, 0.5))
        display_specifier.display.append_graphic(rect_graphic)
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        read_data_item = document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        # verify
        self.assertEqual(len(read_display_specifier.display.graphics), 1)
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
        DataItem.DisplaySpecifier.from_data_item(data_item).buffered_data_source.add_region(point_region)
        document_controller.close()
        # read it back
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        read_data_item = document_controller.document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        # verify
        self.assertEqual(read_display_specifier.buffered_data_source.regions[0].type, "point-region")
        self.assertEqual(read_display_specifier.buffered_data_source.regions[0].uuid, point_region_uuid)
        self.assertEqual(read_display_specifier.buffered_data_source.regions[0].position, (0.6, 0.4))
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
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
            document_model.append_data_item(data_item)
            data_item2 = DataItem.DataItem()
            invert_operation = Operation.OperationItem("invert-operation")
            invert_operation.add_data_source(data_item._create_test_data_source())
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
        read_data_item = document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        # check storage caches
        self.assertEqual(document_model.data_items[0].storage_cache, storage_cache)
        self.assertEqual(read_display_specifier.display.storage_cache, read_data_item._suspendable_storage_cache)
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
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_specifier.buffered_data_source.add_region(crop_region)
        display_panel = document_controller.selected_display_panel
        display_panel.set_displayed_data_item(data_item)
        operation = Operation.OperationItem("invert-operation")
        document_controller.add_processing_operation(DataItem.BufferedDataSourceSpecifier.from_data_item(data_item), operation, crop_region=crop_region)
        document_model.close()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        read_data_item = document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        self.assertEqual(read_display_specifier.buffered_data_source.regions[0].bounds, document_model.data_items[1].operation.data_sources[0].get_property("bounds"))
        read_display_specifier.buffered_data_source.regions[0].bounds = ((0.3, 0.4), (0.5, 0.6))
        self.assertEqual(read_display_specifier.buffered_data_source.regions[0].bounds, document_model.data_items[1].operation.data_sources[0].get_property("bounds"))

    def test_inverted_data_item_does_not_need_recompute_when_reloaded(self):
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(data_item._create_test_data_source())
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted.recompute_data()
        document_model.close()
        # reload and check inverted data item does not need recompute
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        read_data_item2 = document_model.data_items[1]
        read_display_specifier2 = DataItem.DisplaySpecifier.from_data_item(read_data_item2)
        self.assertFalse(read_display_specifier2.buffered_data_source.is_data_stale)

    def test_cropped_data_item_with_region_does_not_need_recompute_when_reloaded(self):
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        data_item_cropped = DataItem.DataItem()
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.add_data_source(data_item._create_test_data_source())
        data_item_cropped.set_operation(crop_operation)
        crop_operation.establish_associated_region("crop", display_specifier.buffered_data_source)
        document_model.append_data_item(data_item_cropped)
        data_item_cropped.recompute_data()
        read_data_item2 = document_model.data_items[1]
        read_display_specifier2 = DataItem.DisplaySpecifier.from_data_item(read_data_item2)
        self.assertFalse(read_display_specifier2.buffered_data_source.is_data_stale)
        document_model.close()
        # reload and check inverted data item does not need recompute
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        self.assertFalse(read_display_specifier2.buffered_data_source.is_data_stale)

    def test_cropped_data_item_with_region_still_updates_when_reloaded(self):
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.float))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        data_item_cropped = DataItem.DataItem()
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.add_data_source(data_item._create_test_data_source())
        data_item_cropped.set_operation(crop_operation)
        crop_operation.establish_associated_region("crop", display_specifier.buffered_data_source)
        document_model.append_data_item(data_item_cropped)
        data_item_cropped.recompute_data()
        read_data_item2 = document_model.data_items[1]
        read_display_specifier2 = DataItem.DisplaySpecifier.from_data_item(read_data_item2)
        self.assertFalse(read_display_specifier2.buffered_data_source.is_data_stale)
        document_model.close()
        # reload and check inverted data item does not need recompute
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        document_model.recompute_all()  # shouldn't be necessary unless other tests fail
        read_data_item = document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        read_data_item2 = document_model.data_items[1]
        read_display_specifier2 = DataItem.DisplaySpecifier.from_data_item(read_data_item2)
        read_display_specifier.buffered_data_source.regions[0].bounds = (0.25, 0.25), (0.5, 0.5)
        self.assertTrue(read_display_specifier2.buffered_data_source.is_data_stale)
        document_model.recompute_all()
        self.assertEqual(read_display_specifier2.buffered_data_source.data_shape, (128, 128))

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
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            cropped_data_item = DataItem.DataItem()
            crop_operation = Operation.OperationItem("crop-operation")
            crop_operation.add_data_source(data_item._create_test_data_source())
            cropped_data_item.set_operation(crop_operation)
            crop_operation.establish_associated_region("crop", display_specifier.buffered_data_source)
            document_model.append_data_item(cropped_data_item)
            cropped_display_specifier = DataItem.DisplaySpecifier.from_data_item(cropped_data_item)
            cropped_data_item.recompute_data()
            histogram1 = numpy.copy(cropped_display_specifier.display.get_processed_data("histogram"))
            cropped_display_specifier.display.get_processor("histogram").recompute_data(None)
            histogram2 = numpy.copy(cropped_display_specifier.display.get_processed_data("histogram"))
            document_model.close()
            self.assertFalse(numpy.array_equal(histogram1, histogram2))
            # read it back
            storage_cache = Storage.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, library_storage=library_storage, storage_cache=storage_cache)
            read_data_item = document_model.data_items[1]
            read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
            histogram3 = numpy.copy(read_display_specifier.display.get_processed_data("histogram"))
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
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertEqual(data_item.properties["version"], data_item.writer_version)
        self.assertEqual(len(display_specifier.buffered_data_source.dimensional_calibrations), 2)
        self.assertEqual(display_specifier.buffered_data_source.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(display_specifier.buffered_data_source.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(display_specifier.buffered_data_source.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))
        self.assertEqual(data_item.maybe_data_source.metadata.get("hardware_source")["voltage"], 200.0)
        self.assertFalse("session_uuid" in data_item.maybe_data_source.metadata.get("hardware_source"))
        self.assertIsNone(data_item.session_id)  # v1 is not allowed to set session_id
        self.assertEqual(display_specifier.buffered_data_source.data_dtype, numpy.uint32)
        self.assertEqual(display_specifier.buffered_data_source.data_shape, (256, 256))

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
        self.assertTrue("uuid" in data_item.properties["data_sources"][0]["displays"][0])
        self.assertTrue("uuid" in data_item.properties["data_sources"][0]["displays"][0]["graphics"][0])
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
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertEqual(data_item.properties["version"], data_item.writer_version)
        self.assertEqual(len(display_specifier.buffered_data_source.dimensional_calibrations), 2)
        self.assertEqual(display_specifier.buffered_data_source.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(display_specifier.buffered_data_source.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(display_specifier.buffered_data_source.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))

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
        self.assertEqual(str(data_item.operation.data_sources[0].source_data_item.uuid), data_item_dict["uuid"])
        # calibration renaming
        data_item = document_model.data_items[0]
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertEqual(len(display_specifier.buffered_data_source.dimensional_calibrations), 2)
        self.assertEqual(display_specifier.buffered_data_source.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(display_specifier.buffered_data_source.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(display_specifier.buffered_data_source.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))

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
        data_item3_dict = data_reference_handler.properties.setdefault("C", dict())
        data_item3_dict["uuid"] = str(uuid.uuid4())
        data_item3_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_item3_dict["master_data_dtype"] = None
        data_item3_dict["master_data_shape"] = None
        data_item3_dict["dimensional_calibrations"] = []
        data_item3_dict["intensity_calibration"] = {}
        data_item3_dict["version"] = 6
        # read it back
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, log_migrations=False)
        # # check it
        self.assertEqual(len(document_model.data_items), 3)
        self.assertEqual(str(document_model.data_items[0].uuid), data_item_dict["uuid"])
        self.assertEqual(str(document_model.data_items[1].uuid), data_item2_dict["uuid"])
        self.assertEqual(str(document_model.data_items[2].uuid), data_item3_dict["uuid"])
        data_item = document_model.data_items[1]
        self.assertEqual(data_item.properties["version"], data_item.writer_version)
        self.assertIsNotNone(data_item.operation)
        self.assertEqual(len(data_item.operation.data_sources), 1)
        self.assertEqual(str(data_item.operation.data_sources[0].source_data_item.uuid), data_item_dict["uuid"])
        # calibration renaming
        data_item = document_model.data_items[0]
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertEqual(len(display_specifier.buffered_data_source.dimensional_calibrations), 2)
        self.assertEqual(display_specifier.buffered_data_source.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(display_specifier.buffered_data_source.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
        self.assertEqual(display_specifier.buffered_data_source.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))

    def test_data_items_v7_migration(self):
        # construct v7 data item
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        data_item_dict = data_reference_handler.properties.setdefault("A", dict())
        data_item_dict["uuid"] = str(uuid.uuid4())
        data_item_dict["version"] = 7
        caption, flag, rating, title = "caption", -1, 3, "title"
        data_item_dict["caption"] = caption
        data_item_dict["flag"] = flag
        data_item_dict["rating"] = rating
        data_item_dict["title"] = title
        reference_date = {'dst': '+60', 'tz': '-0800', 'local_datetime': '2000-06-30T15:02:00.000000'}
        data_item_dict["datetime_original"] = reference_date
        data_source_dict = dict()
        data_source_dict["uuid"] = str(uuid.uuid4())
        data_source_dict["type"] = "buffered-data-source"
        data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_source_dict["data_shape"] = (256, 256)
        data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        data_item_dict["data_sources"] = [data_source_dict]
        metadata = {"instrument": "a big screwdriver", "extra_high_tension": 42}
        new_metadata = {"instrument": "a big screwdriver", "autostem": { "high_tension_v": 42}, "extra_high_tension": 42 }
        data_item_dict["hardware_source"] = metadata
        # read it back
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, log_migrations=False)
        # check metadata transferred to data source
        self.assertEqual(len(document_model.data_items), 1)
        self.assertEqual(document_model.data_items[0].metadata.get("hardware_source", dict()), dict())
        self.assertEqual(document_model.data_items[0].data_sources[0].metadata.get("hardware_source"), new_metadata)
        self.assertEqual(document_model.data_items[0].caption, caption)
        self.assertEqual(document_model.data_items[0].flag, flag)
        self.assertEqual(document_model.data_items[0].rating, rating)
        self.assertEqual(document_model.data_items[0].title, title)
        self.assertEqual(document_model.data_items[0].created, datetime.datetime.strptime("2000-06-30T22:02:00.000000", "%Y-%m-%dT%H:%M:%S.%f"))
        self.assertEqual(document_model.data_items[0].modified, document_model.data_items[0].created)
        self.assertEqual(document_model.data_items[0].data_sources[0].created, datetime.datetime.strptime("2000-06-30T22:02:00.000000", "%Y-%m-%dT%H:%M:%S.%f"))
        self.assertEqual(document_model.data_items[0].data_sources[0].modified, document_model.data_items[0].data_sources[0].created)
        self.assertEqual(document_model.data_items[0].data_sources[0].metadata.get("hardware_source").get("autostem").get("high_tension_v"), 42)

    def test_data_item_with_connected_crop_region_should_not_update_modification_when_loading(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        data_item_cropped = DataItem.DataItem()
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.add_data_source(data_item._create_test_data_source())
        data_item_cropped.set_operation(crop_operation)
        crop_operation.establish_associated_region("crop", display_specifier.buffered_data_source)
        document_model.append_data_item(data_item_cropped)
        data_item_cropped.recompute_data()
        data_item._set_modified(modified)
        data_item_cropped._set_modified(modified)
        self.assertEqual(document_model.data_items[0].modified, modified)
        self.assertEqual(document_model.data_items[1].modified, modified)
        document_model.close()
        # make sure it reloads without changing modification
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        self.assertEqual(document_model.data_items[0].modified, modified)
        self.assertEqual(document_model.data_items[1].modified, modified)
        document_model.recompute_all()  # try recomputing too
        self.assertEqual(document_model.data_items[0].modified, modified)
        self.assertEqual(document_model.data_items[1].modified, modified)

    def test_begin_end_transaction_with_no_change_should_not_write(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
        document_model.append_data_item(data_item)
        # force a write and verify
        document_model.begin_data_item_transaction(data_item)
        document_model.end_data_item_transaction(data_item)
        self.assertEqual(len(data_reference_handler.properties.keys()), 1)
        # continue with test
        data_item._set_modified(modified)
        self.assertEqual(document_model.data_items[0].modified, modified)
        # now clear the data_reference_handler and see if it gets written again
        data_reference_handler.properties.clear()
        document_model.begin_data_item_transaction(data_item)
        document_model.end_data_item_transaction(data_item)
        self.assertEqual(document_model.data_items[0].modified, modified)
        # properties should still be empty, unless it was written again
        self.assertEqual(data_reference_handler.properties, dict())

    def test_begin_end_transaction_with_change_should_write(self):
        # converse of previous test
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item._set_modified(modified)
        self.assertEqual(document_model.data_items[0].modified, modified)
        # now clear the data_reference_handler and see if it gets written again
        data_reference_handler.properties.clear()
        document_model.begin_data_item_transaction(data_item)
        data_item.set_metadata(data_item.metadata)
        document_model.end_data_item_transaction(data_item)
        self.assertNotEqual(document_model.data_items[0].modified, modified)
        # properties should still be empty, unless it was written again
        self.assertNotEqual(data_reference_handler.properties, dict())

    def test_storage_cache_disabled_during_transaction(self):
        storage_cache = Storage.DictStorageCache()
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
        document_model.append_data_item(data_item)
        cached_data_range = storage_cache.cache[data_item.maybe_data_source.uuid]["data_range"]
        self.assertEqual(cached_data_range, (1, 1))
        self.assertEqual(data_item.maybe_data_source.data_range, (1, 1))
        with document_model.data_item_transaction(data_item):
            with data_item.maybe_data_source.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((16, 16), numpy.uint32)
            self.assertEqual(data_item.maybe_data_source.data_range, (0, 0))
            self.assertEqual(cached_data_range, storage_cache.cache[data_item.maybe_data_source.uuid]["data_range"])
            self.assertEqual(cached_data_range, (1, 1))
        self.assertEqual(storage_cache.cache[data_item.maybe_data_source.uuid]["data_range"], (0, 0))

    def test_suspendable_storage_cache_caches_removes(self):
        data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
        storage_cache = Storage.DictStorageCache()
        suspendable_storage_cache = Storage.SuspendableCache(storage_cache)
        suspendable_storage_cache.set_cached_value(data_item, "key", 1.0)
        self.assertEqual(storage_cache.cache[data_item.uuid]["key"], 1.0)
        suspendable_storage_cache.suspend_cache()
        suspendable_storage_cache.remove_cached_value(data_item, "key")
        self.assertEqual(storage_cache.cache[data_item.uuid]["key"], 1.0)
        suspendable_storage_cache.spill_cache()
        self.assertIsNone(storage_cache.cache.get(data_item.uuid, dict()).get("key"))

    def test_suspendable_storage_cache_is_null_for_add_followed_by_remove(self):
        data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
        storage_cache = Storage.DictStorageCache()
        suspendable_storage_cache = Storage.SuspendableCache(storage_cache)
        suspendable_storage_cache.suspend_cache()
        suspendable_storage_cache.set_cached_value(data_item, "key", 1.0)
        suspendable_storage_cache.remove_cached_value(data_item, "key")
        suspendable_storage_cache.spill_cache()
        self.assertIsNone(storage_cache.cache.get(data_item.uuid, dict()).get("key"))

    def test_writing_properties_with_numpy_float32_succeeds(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(workspace_dir)
        data_reference_handler = Application.DataReferenceHandler(workspace_dir)
        try:
            document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            data_item.maybe_data_source.displays[0].display_limits = (numpy.float32(1.0), numpy.float32(1.0))
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
