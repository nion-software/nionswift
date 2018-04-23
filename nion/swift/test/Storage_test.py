# standard libraries
import contextlib
import copy
import datetime
import gc
import json
import logging
import os
import pathlib
import shutil
import threading
import unittest
import uuid

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import Facade
from nion.swift import Thumbnails
from nion.swift.model import Cache
from nion.swift.model import Connection
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.ui import TestUI


Facade.initialize()


def memory_usage_resource():
    import resource
    import sys
    rusage_denom = 1024.
    if sys.platform == 'darwin':
        # ... it seems that in OSX the output is different units ...
        rusage_denom = rusage_denom * rusage_denom
    mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / rusage_denom
    return mem

class TestStorageClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)
        # self.__memory_start = memory_usage_resource()

    def tearDown(self):
        # gc.collect()
        # memory_usage = memory_usage_resource() - self.__memory_start
        # if memory_usage > 0.5:
        #     logging.debug("{} {}".format(self.id(), memory_usage))
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
        display_specifier.data_item.set_intensity_calibration(Calibration.Calibration(1.0, 2.0, "three"))
        metadata = data_item.metadata
        metadata.setdefault("test", dict())["one"] = 1
        data_item.metadata = metadata
        display = DataItem.DisplaySpecifier.from_data_item(data_item).display
        display.add_graphic(Graphics.PointGraphic())
        display.add_graphic(Graphics.LineGraphic())
        display.add_graphic(Graphics.RectangleGraphic())
        display.add_graphic(Graphics.EllipseGraphic())
        document_controller.document_model.append_data_item(data_item)
        data_group = DataGroup.DataGroup()
        data_group.append_data_item(data_item)
        document_controller.document_model.append_data_group(data_group)
        data_item2 = DataItem.DataItem(numpy.zeros((12, 12), dtype=numpy.int64))
        document_controller.document_model.append_data_item(data_item2)
        data_group.append_data_item(data_item2)
        data_item3 = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
        document_controller.document_model.append_data_item(data_item3)
        data_group.append_data_item(data_item3)
        data_item2a = DataItem.DataItem()
        data_item2a.ensure_data_source()
        data_item2b = DataItem.DataItem()
        data_item2b.ensure_data_source()
        data_group.append_data_item(data_item2a)
        data_group.append_data_item(data_item2b)
        document_controller.document_model.append_data_item(data_item2a)
        document_controller.document_model.append_data_item(data_item2b)
        display_panel = document_controller.workspace_controller.display_panels[0]
        document_controller.selected_display_panel = display_panel
        display_panel.set_display_panel_data_item(data_item)
        self.assertEqual(document_controller.selected_display_specifier.data_item, data_item)
        document_controller.add_line_graphic()
        document_controller.add_rectangle_graphic()
        document_controller.add_ellipse_graphic()
        document_controller.add_point_graphic()
        display_panel.set_display_panel_data_item(data_item)
        self.assertEqual(document_controller.selected_display_specifier.data_item, data_item)
        document_controller.processing_gaussian_blur()
        display_panel.set_display_panel_data_item(data_item)
        document_controller.processing_resample()
        display_panel.set_display_panel_data_item(data_item)
        document_controller.processing_invert()
        display_panel.set_display_panel_data_item(data_item)
        document_controller.processing_crop()
        display_panel.set_display_panel_data_item(data_item2)
        self.assertEqual(document_controller.selected_display_specifier.data_item, data_item2)
        document_controller.processing_fft()
        document_controller.processing_ifft()

    def test_save_document(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        document_controller.close()

    def test_save_load_document(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        data_items_count = len(document_controller.document_model.data_items)
        data_items_type = type(document_controller.document_model.data_items)
        document_controller.close()
        # # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.assertEqual(data_items_count, len(document_controller.document_model.data_items))
        self.assertEqual(data_items_type, type(document_controller.document_model.data_items))
        document_controller.close()

    def test_storage_cache_closing_twice_throws_exception(self):
        storage_cache = Cache.DbStorageCache(":memory:")
        with self.assertRaises(AssertionError):
            storage_cache.close()
            storage_cache.close()

    def test_storage_cache_validates_data_range_upon_reading(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        try:
            storage_cache = Cache.DictStorageCache()
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage, storage_cache=storage_cache)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                data_range = display_specifier.display.get_calculated_display_values(True).data_range
            # read it back
            storage_cache = Cache.DictStorageCache()
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage, storage_cache=storage_cache)
            with contextlib.closing(document_model):
                read_data_item = document_model.data_items[0]
                read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
                self.assertEqual(read_display_specifier.display.get_calculated_display_values(True).data_range, data_range)
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_thumbnail_does_not_get_invalidated_upon_reading(self):
        # tests caching on display
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        cache_name = os.path.join(workspace_dir, "Data.cache")
        try:
            storage_cache = Cache.DbStorageCache(cache_name)
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage, storage_cache=storage_cache)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                storage_cache.set_cached_value(display_specifier.display, "thumbnail_data", numpy.zeros((128, 128, 4), dtype=numpy.uint8))
                self.assertFalse(storage_cache.is_cached_value_dirty(display_specifier.display, "thumbnail_data"))
            # read it back
            storage_cache = Cache.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage, storage_cache=storage_cache)
            with contextlib.closing(document_model):
                read_data_item = document_model.data_items[0]
                read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
                # thumbnail data should still be valid
                self.assertFalse(storage_cache.is_cached_value_dirty(read_display_specifier.display, "thumbnail_data"))
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_reloading_thumbnail_from_cache_does_not_mark_it_as_dirty(self):
        # tests caching on display
        storage_cache = Cache.DictStorageCache()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            storage_cache.set_cached_value(display_specifier.display, "thumbnail_data", numpy.zeros((128, 128, 4), dtype=numpy.uint8))
            self.assertFalse(storage_cache.is_cached_value_dirty(display_specifier.display, "thumbnail_data"))
            with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.app.ui, display_specifier.display)) as thumbnail_source:
                thumbnail_source.recompute_data()
        # read it back
        storage_cache = storage_cache.clone()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        with contextlib.closing(document_model):
            read_data_item = document_model.data_items[0]
            read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
            # thumbnail data should still be valid
            self.assertFalse(storage_cache.is_cached_value_dirty(read_display_specifier.display, "thumbnail_data"))
            with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.app.ui, read_display_specifier.display)) as thumbnail_source:
                self.assertFalse(thumbnail_source._is_thumbnail_dirty)

    def test_reload_data_item_initializes_display_data_range(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0])
            self.assertIsNotNone(display_specifier.display.get_calculated_display_values(True).data_range)
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            display_specifier = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0])
            self.assertIsNotNone(display_specifier.display.get_calculated_display_values(True).data_range)

    @unittest.expectedFailure
    def test_reload_data_item_does_not_recalculate_display_data_range(self):
        storage_cache = Cache.DictStorageCache()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_uuid = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0]).display.uuid
        # read it back
        data_range = 1, 4
        storage_cache.cache[display_uuid]["data_range"] = data_range
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        with contextlib.closing(document_model):
            display_specifier = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0])
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).data_range, data_range)

    def test_reload_data_item_does_not_load_actual_data(self):
        # reloading data from disk should not have to load the data, otherwise bad performance ensues
        storage_cache = Cache.DictStorageCache()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
        # read it back
        data_read_count_ref = [0]
        def data_read(uuid):
            data_read_count_ref[0] += 1
        listener = memory_persistent_storage_system._test_data_read_event.listen(data_read)
        with contextlib.closing(listener):
            document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
            with contextlib.closing(document_model):
                self.assertEqual(data_read_count_ref[0], 0)

    def test_reload_data_item_initializes_display_slice(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((4, 4, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0])
            display_specifier.display.slice_center = 5
            display_specifier.display.slice_width = 3
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            display_specifier = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0])
            self.assertEqual(display_specifier.display.slice_center, 5)
            self.assertEqual(display_specifier.display.slice_width, 3)

    def test_reload_data_item_validates_display_slice_and_has_valid_data_and_stats(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data = numpy.zeros((4, 4, 8), numpy.uint32)
            data[..., 7] = 1
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0])
            display_specifier.display.slice_center = 5
            display_specifier.display.slice_width = 1
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).data_range, (0, 0))
        # make the slice_center be out of bounds
        memory_persistent_storage_system.properties[str(data_item.uuid)]["displays"][0]["slice_center"] = 20
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            display_specifier = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0])
            self.assertEqual(display_specifier.display.slice_center, 7)
            self.assertEqual(display_specifier.display.slice_width, 1)
            self.assertIsNotNone(document_model.data_items[0].data)
            self.assertEqual(display_specifier.display.get_calculated_display_values(True).data_range, (1, 1))

    def test_save_load_document_to_files(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        cache_name = os.path.join(workspace_dir, "Data.cache")
        try:
            storage_cache = Cache.DbStorageCache(cache_name)
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage, storage_cache=storage_cache)
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
            storage_cache = Cache.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage, storage_cache=storage_cache)
            with contextlib.closing(document_model):
                self.assertEqual(data_items_count, len(document_model.data_items))
                self.assertEqual(data_items_type, type(document_model.data_items))
            document_model = None
            storage_cache = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_db_storage(self):
        cache_name = ":memory:"
        storage_cache = Cache.DbStorageCache(cache_name)
        library_storage = DocumentModel.FilePersistentStorage()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage, storage_cache=storage_cache)
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
        data_item0_calibration_len = len(data_item0_display_specifier.data_item.dimensional_calibrations)
        data_item1_data_items_len = len(document_controller.document_model.get_dependent_data_items(data_item1))
        document_controller.close()
        # read it back
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        new_data_item0 = document_controller.document_model.get_data_item_by_uuid(data_item0_uuid)
        new_data_item0_display_specifier = DataItem.DisplaySpecifier.from_data_item(new_data_item0)
        self.assertIsNotNone(new_data_item0)
        self.assertEqual(document_model_uuid, document_controller.document_model.uuid)
        self.assertEqual(data_items_count, len(document_controller.document_model.data_items))
        self.assertEqual(data_items_type, type(document_controller.document_model.data_items))
        self.assertIsNotNone(new_data_item0_display_specifier.data_item.data)
        self.assertEqual(data_item0_uuid, new_data_item0.uuid)
        self.assertEqual(data_item0_calibration_len, len(new_data_item0_display_specifier.data_item.dimensional_calibrations))
        new_data_item1 = document_controller.document_model.get_data_item_by_uuid(data_item1_uuid)
        new_data_item1_data_items_len = len(document_controller.document_model.get_dependent_data_items(new_data_item1))
        self.assertEqual(data_item1_uuid, new_data_item1.uuid)
        self.assertEqual(data_item1_data_items_len, new_data_item1_data_items_len)
        # check over the data item
        self.assertEqual(new_data_item0_display_specifier.display.display_limits, (500, 1000))
        self.assertEqual(new_data_item0_display_specifier.data_item.intensity_calibration.offset, 1.0)
        self.assertEqual(new_data_item0_display_specifier.data_item.intensity_calibration.scale, 2.0)
        self.assertEqual(new_data_item0_display_specifier.data_item.intensity_calibration.units, "three")
        self.assertEqual(new_data_item0.metadata.get("test")["one"], 1)
        document_controller.close()

    def test_dependencies_are_correct_when_dependent_read_before_source(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            src_data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            src_data_item.category = "temporary"
            document_model.append_data_item(src_data_item)
            dst_data_item = document_model.get_fft_new(src_data_item)
            document_model.recompute_all()
            dst_data_item.created = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
            src_data_item_uuid = src_data_item.uuid
            dst_data_item_uuid = dst_data_item.uuid
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            src_data_item = document_model.get_data_item_by_uuid(src_data_item_uuid)
            dst_data_item = document_model.get_data_item_by_uuid(dst_data_item_uuid)
            # make sure the items are loading how we expect them to load (dependent first, then source)
            self.assertEqual(document_model.data_items[0], dst_data_item)
            self.assertEqual(document_model.data_items[1], src_data_item)
            # now the check to ensure the dependency is correct
            self.assertEqual(document_model.get_dependent_data_items(src_data_item)[0], dst_data_item)

    def test_dependencies_load_correctly_when_initially_loaded(self):
        # configure list of data items so that after sorted (on creation date) they will still be listed in this order.
        # this makes one dependency (86d982d1) load before the main item (71ab9215) and one (7d3b374e) load after.
        # this tests the get_dependent_data_items after reading data.
        library_storage = DocumentModel.MemoryPersistentStorage()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(item_uuid=uuid.UUID('86d982d1-6d81-46fa-b19e-574e904902de'))
            data_item1.ensure_data_source()
            data_item2 = DataItem.DataItem(item_uuid=uuid.UUID('71ab9215-c6ae-4c36-aaf5-92ce78db02b6'))
            data_item2.ensure_data_source()
            data_item3 = DataItem.DataItem(item_uuid=uuid.UUID('7d3b374e-e48b-460f-91de-7ff4e1a1a63c'))
            data_item3.ensure_data_source()
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            computation1 = document_model.create_computation(Symbolic.xdata_expression("xd.ifft(a.xdata)"))
            computation1.create_object("a", document_model.get_object_specifier(data_item2))
            document_model.set_data_item_computation(data_item1, computation1)
            computation2 = document_model.create_computation(Symbolic.xdata_expression("xd.fft(a.xdata)"))
            computation2.create_object("a", document_model.get_object_specifier(data_item2))
            document_model.set_data_item_computation(data_item3, computation2)
        memory_persistent_storage_system.properties["86d982d1-6d81-46fa-b19e-574e904902de"]["created"] = "2015-01-22T17:16:12.421290"
        memory_persistent_storage_system.properties["71ab9215-c6ae-4c36-aaf5-92ce78db02b6"]["created"] = "2015-01-22T17:16:12.219730"
        memory_persistent_storage_system.properties["7d3b374e-e48b-460f-91de-7ff4e1a1a63c"]["created"] = "2015-01-22T17:16:12.308003"
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item1_uuid = uuid.UUID("71ab9215-c6ae-4c36-aaf5-92ce78db02b6")
            new_data_item1 = document_model.get_data_item_by_uuid(data_item1_uuid)
            new_data_item1_data_items_len = len(document_model.get_dependent_data_items(new_data_item1))
            self.assertEqual(data_item1_uuid, new_data_item1.uuid)
            self.assertEqual(2, new_data_item1_data_items_len)

    # test whether we can update master_data and have it written to the db
    def test_db_storage_write_data(self):
        cache_name = ":memory:"
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
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
        display_specifier.data_item.set_data(data2)
        document_controller.close()
        # read it back
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = document_controller.document_model.data_items[0]
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertEqual(display_specifier.data_item.data[0 , 0], 2)
        document_controller.close()

    # test whether we can update the db from a thread
    def test_db_storage_write_on_thread(self):
        cache_name = ":memory:"
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data1 = numpy.zeros((16, 16), numpy.uint32)
        data1[0,0] = 1
        data_item = DataItem.DataItem(data1)
        document_model.append_data_item(data_item)
        data_group = DataGroup.DataGroup()
        data_group.append_data_item(data_item)
        document_controller.document_model.append_data_group(data_group)

        def update_data(event_loop, data_item):
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data2 = numpy.zeros((16, 16), numpy.uint32)
            data2[0,0] = 2
            def update_data_soon():
                display_specifier.data_item.set_data(data2)
            event_loop.call_soon_threadsafe(update_data_soon)

        thread = threading.Thread(target=update_data, args=[document_controller.event_loop, data_item])
        thread.start()
        thread.join()
        document_controller.close()
        # read it back
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        read_data_item = document_controller.document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        self.assertEqual(read_display_specifier.data_item.data[0, 0], 2)
        document_controller.close()

    def test_storage_insert_items(self):
        cache_name = ":memory:"
        storage_cache = Cache.DbStorageCache(cache_name)
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
        document_controller.close()

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
        document_controller.close()

    def test_adding_data_item_to_document_model_twice_raises_exception(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        with self.assertRaises(AssertionError):
            document_model.append_data_item(data_item)
        document_controller.close()

    def test_adding_data_item_to_data_group_twice_raises_exception(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            self.save_document(document_controller)
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            document_model.data_groups[0].append_data_item(data_item)
            with self.assertRaises(AssertionError):
                document_model.data_groups[0].append_data_item(data_item)

    def test_reading_data_group_with_duplicate_data_items_discards_duplicates(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        library_storage = DocumentModel.FilePersistentStorage()
        document_model = DocumentModel.DocumentModel(library_storage=library_storage, persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8))))
            data_group = DataGroup.DataGroup()
            data_group.append_data_item(document_model.data_items[0])
            data_group.append_data_item(document_model.data_items[1])
            document_model.append_data_group(data_group)
        library_properties = library_storage.properties
        library_properties['data_groups'][0]['data_item_uuids'][1] = library_properties['data_groups'][0]['data_item_uuids'][0]
        library_storage._set_properties(library_properties)
        document_model = DocumentModel.DocumentModel(library_storage=library_storage, persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            self.assertEqual(len(document_model.data_groups[0].data_items), 1)

    def test_insert_item_with_transaction(self):
        cache_name = ":memory:"
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        with contextlib.closing(document_model):
            data_group = DataGroup.DataGroup()
            document_model.append_data_group(data_group)
            data_item = DataItem.DataItem()
            data_item.ensure_data_source()
            data_item.title = 'title'
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            with document_model.item_transaction(data_item):
                display_specifier.data_item.set_data(numpy.zeros((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                data_group.append_data_item(data_item)
        # make sure it reloads
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item2 = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            data_item3 = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
            # interleaved transactions
            transaction1 = document_model.item_transaction(data_item1)
            transaction2 = document_model.item_transaction(data_item2)
            transaction1.close()
            transaction3 = document_model.item_transaction(data_item3)
            transaction3.close()
            transaction2.close()

    def test_data_item_modification_should_not_change_when_reading(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem()
            data_item.ensure_data_source()
            document_model.append_data_item(data_item)
            data_item._set_modified(modified)
        # make sure it reloads
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            self.assertEqual(document_model.data_items[0].modified, modified)

    def test_data_item_should_store_modifications_within_transactions(self):
        created = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        cache_name = ":memory:"
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem()
            data_item.ensure_data_source()
            document_model.append_data_item(data_item)
            with document_model.item_transaction(data_item):
                data_item.created = created
        # make sure it reloads
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        with contextlib.closing(document_model):
            self.assertEqual(document_model.data_items[0].created, created)

    def test_data_writes_to_and_reloads_from_file(self):
        cache_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        try:
            data = numpy.random.randn(16, 16)
            storage_cache = Cache.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, storage_cache=storage_cache)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                data_item.created = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                display_specifier.data_item.set_data(data)
                document_model.append_data_item(data_item)
                data_file_path = data_item._test_get_file_path()
                self.assertTrue(os.path.exists(data_file_path))
                self.assertTrue(os.path.isfile(data_file_path))
            # make sure the data reloads
            storage_cache = Cache.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, storage_cache=storage_cache)
            with contextlib.closing(document_model):
                read_data_item = document_model.data_items[0]
                read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
                self.assertTrue(numpy.array_equal(read_display_specifier.data_item.data, data))
                # and then make sure the data file gets removed on disk when removed
                document_model.remove_data_item(document_model.data_items[0])
                self.assertFalse(os.path.exists(data_file_path))
            document_model = None
            storage_cache = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_delete_and_undelete_from_memory_storage_system_restores_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16)))
            document_model.append_data_item(data_item)
            data_item_uuid = data_item.uuid
            document_model.remove_data_item(data_item, safe=True)
            self.assertEqual(0, len(document_model.data_items))
            document_model.restore_data_item(data_item_uuid)
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(data_item_uuid, document_model.data_items[0].uuid)

    def test_delete_and_undelete_from_memory_storage_system_restores_data_item_after_reload(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16)))
            document_model.append_data_item(data_item)
            data_item_uuid = data_item.uuid
            document_model.remove_data_item(data_item, safe=True)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            self.assertEqual(0, len(document_model.data_items))
            document_model.restore_data_item(data_item_uuid)
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(data_item_uuid, document_model.data_items[0].uuid)

    def test_delete_and_undelete_from_memory_storage_system_restores_composite_item_after_reload(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((4, 4)))
            composite_item = DataItem.CompositeLibraryItem()
            document_model.append_data_item(composite_item)
            document_model.append_data_item(data_item)
            composite_item.append_data_item(data_item)
            data_item_uuid = composite_item.uuid
            document_model.remove_data_item(composite_item, safe=True)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            self.assertEqual(1, len(document_model.data_items))
            document_model.restore_data_item(data_item_uuid, 0)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(data_item_uuid, document_model.data_items[0].uuid)
            self.assertEqual(1, len(document_model.data_items[0].data_items))

    def test_delete_and_undelete_from_file_storage_system_restores_data_item(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        try:
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16)))
                document_model.append_data_item(data_item)
                data_item_uuid = data_item.uuid
                document_model.remove_data_item(data_item, safe=True)
                self.assertEqual(0, len(document_model.data_items))
                document_model.restore_data_item(data_item_uuid)
                self.assertEqual(1, len(document_model.data_items))
                self.assertEqual(data_item_uuid, document_model.data_items[0].uuid)
        finally:
            # logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def disabled_test_delete_and_undelete_from_file_storage_system_restores_data_item_after_reload(self):
        # this test is disabled for now; launching the application empties the trash until a user interface
        # is established for restoring items in the trash.
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        try:
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16)))
                document_model.append_data_item(data_item)
                data_item_uuid = data_item.uuid
                document_model.remove_data_item(data_item, safe=True)
            # read it back
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage, log_migrations=False)
            with contextlib.closing(document_model):
                self.assertEqual(0, len(document_model.data_items))
                document_model.restore_data_item(data_item_uuid)
                self.assertEqual(1, len(document_model.data_items))
                self.assertEqual(data_item_uuid, document_model.data_items[0].uuid)
        finally:
            # logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_data_changes_update_large_format_file(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        try:
            zeros = numpy.zeros((8, 8), numpy.uint32)
            ones = numpy.ones((8, 8), numpy.uint32)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(ones)
                data_item.large_format = True
                document_model.append_data_item(data_item)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system)
            with contextlib.closing(document_model):
                document_model.data_items[0].set_data(zeros)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system)
            with contextlib.closing(document_model):
                self.assertTrue(numpy.array_equal(document_model.data_items[0].data, zeros))
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_writing_empty_data_item_returns_expected_values(self):
        cache_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        try:
            storage_cache = Cache.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, storage_cache=storage_cache)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                document_model.append_data_item(data_item)
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                reference = data_item._test_get_file_path()
                self.assertFalse(display_specifier.data_item.has_data)
                self.assertIsNone(display_specifier.data_item.data_shape)
                self.assertIsNone(display_specifier.data_item.data_dtype)
                self.assertIsNotNone(reference)
            document_model = None
            storage_cache = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_writing_data_item_with_no_data_sources_returns_expected_values(self):
        cache_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        try:
            storage_cache = Cache.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, storage_cache=storage_cache)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                document_model.append_data_item(data_item)
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                reference = data_item._test_get_file_path()
                self.assertIsNotNone(reference)
            document_model = None
            storage_cache = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_data_writes_to_file_after_transaction(self):
        cache_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        try:
            storage_cache = Cache.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, storage_cache=storage_cache)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                document_model.append_data_item(data_item)
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                # write data with transaction
                data_file_path = data_item._test_get_file_path()
                with document_model.item_transaction(data_item):
                    display_specifier.data_item.set_data(numpy.zeros((16, 16), numpy.uint32))
                    # make sure data does NOT exist during the transaction
                    handler = data_item.persistent_storage._storage_handler
                    self.assertIsNone(handler.read_data())
                # make sure it DOES exist after the transaction
                self.assertTrue(os.path.exists(data_file_path))
                self.assertTrue(os.path.isfile(data_file_path))
                self.assertIsNotNone(handler.read_data())
            document_model = None
            storage_cache = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_begin_end_transaction_with_no_change_should_not_write(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            # force a write and verify
            with document_model.item_transaction(data_item):
                pass
            self.assertEqual(len(memory_persistent_storage_system.properties.keys()), 1)
            # continue with test
            data_item._set_modified(modified)
            self.assertEqual(document_model.data_items[0].modified, modified)
            # now clear the memory_persistent_storage_system and see if it gets written again
            memory_persistent_storage_system.properties.clear()
            with document_model.item_transaction(data_item):
                pass
            self.assertEqual(document_model.data_items[0].modified, modified)
            # properties should still be empty, unless it was written again
            self.assertEqual(memory_persistent_storage_system.properties, dict())

    def test_begin_end_transaction_with_change_should_write(self):
        # converse of previous test
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            data_item._set_modified(modified)
            self.assertEqual(document_model.data_items[0].modified, modified)
            # now clear the memory_persistent_storage_system and see if it gets written again
            memory_persistent_storage_system.properties.clear()
            with document_model.item_transaction(data_item):
                data_item.metadata = data_item.metadata
            self.assertNotEqual(document_model.data_items[0].modified, modified)
            # properties should still be empty, unless it was written again
            self.assertNotEqual(memory_persistent_storage_system.properties, dict())

    def test_begin_end_transaction_with_non_data_change_should_not_write_data(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            # now clear the memory_persistent_storage_system and see if it gets written again
            memory_persistent_storage_system.data.clear()
            with document_model.item_transaction(data_item):
                data_item.description = data_item.description
            self.assertEqual(memory_persistent_storage_system.data, dict())

    def test_begin_end_transaction_with_data_change_should_write_data(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            # now clear the memory_persistent_storage_system and see if it gets written again
            memory_persistent_storage_system.data.clear()
            with document_model.item_transaction(data_item):
                data_item.set_data(numpy.zeros((17, 17), numpy.uint32))
            self.assertEqual(memory_persistent_storage_system.data[str(data_item.uuid)].shape, (17, 17))

    def test_data_removes_file_after_original_date_and_session_change(self):
        created = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        cache_name = ":memory:"
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        try:
            storage_cache = Cache.DbStorageCache(cache_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, storage_cache=storage_cache)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                data_item.created = created
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                display_specifier.data_item.set_data(numpy.zeros((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                data_file_path = data_item._test_get_file_path()
                # make sure it get written to disk
                self.assertTrue(os.path.exists(data_file_path))
                self.assertTrue(os.path.isfile(data_file_path))
                # change the original date
                data_item.created = datetime.datetime.utcnow()
                data_item.session_id = "20000531-000000"
                document_model.remove_data_item(data_item)
                # make sure it get removed from disk
                self.assertFalse(os.path.exists(data_file_path))
            document_model = None
            storage_cache = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_reloading_data_item_with_display_builds_graphics_properly(self):
        cache_name = ":memory:"
        storage_cache = Cache.DbStorageCache(cache_name)
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.save_document(document_controller)
        read_data_item = document_model.data_items[0]
        read_data_item_uuid = read_data_item.uuid
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        self.assertEqual(len(read_display_specifier.display.graphics), 9)  # verify assumptions
        document_controller.close()
        # read it back
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        read_data_item = document_model.get_data_item_by_uuid(read_data_item_uuid)
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        # verify graphics reload
        self.assertEqual(len(read_display_specifier.display.graphics), 9)
        # clean up
        document_controller.close()

    def test_writing_empty_data_item_followed_by_writing_data_adds_correct_calibrations(self):
        # this failed due to a key aliasing issue.
        cache_name = ":memory:"
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # create empty data item
        data_item = DataItem.DataItem()
        data_item.ensure_data_source()
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        with document_model.item_transaction(data_item):
            display_specifier.data_item.set_data(numpy.zeros((16, 16), numpy.uint32))
        self.assertEqual(len(display_specifier.data_item.dimensional_calibrations), 2)
        document_controller.close()
        # read it back
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        read_data_item = document_controller.document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        # verify calibrations
        self.assertEqual(len(read_display_specifier.data_item.dimensional_calibrations), 2)
        # clean up
        document_controller.close()

    def test_reloading_data_item_establishes_display_connection_to_storage(self):
        cache_name = ":memory:"
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        document_controller.close()
        # read it back
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # clean up
        document_controller.close()

    def test_reloaded_line_profile_operation_binds_to_roi(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            document_model.get_line_profile_new(data_item)
            data_item.displays[0].graphics[0].vector = (0.1, 0.2), (0.3, 0.4)
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = document_model.data_items[0]
            data_item2 = document_model.data_items[1]
            # verify that properties read it correctly
            self.assertEqual(data_item.displays[0].graphics[0].start, (0.1, 0.2))
            self.assertEqual(data_item.displays[0].graphics[0].end, (0.3, 0.4))
            data_item.displays[0].graphics[0].start = 0.11, 0.22
            vector = document_model.resolve_object_specifier(document_model.get_data_item_computation(data_item2).variables[1].specifier).value.vector
            self.assertEqual(vector[0], (0.11, 0.22))
            self.assertEqual(vector[1], (0.3, 0.4))

    def test_reloaded_line_plot_has_valid_calibration_style(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, ), numpy.uint32))
            document_model.append_data_item(data_item)
            self.assertEqual(data_item.displays[0].display_calibrated_values, True)
            self.assertIsNone(data_item.displays[0].dimensional_calibration_style)
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = document_model.data_items[0]
            self.assertEqual(data_item.displays[0].display_calibrated_values, True)
            self.assertEqual(data_item.displays[0].dimensional_calibration_style, "calibrated")

    def test_reloaded_graphics_load_properly(self):
        cache_name = ":memory:"
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        rect_graphic = Graphics.RectangleGraphic()
        rect_graphic.bounds = ((0.25, 0.25), (0.5, 0.5))
        display_specifier.display.add_graphic(rect_graphic)
        document_controller.close()
        # read it back
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        read_data_item = document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        # verify
        self.assertEqual(len(read_display_specifier.display.graphics), 1)
        # clean up
        document_controller.close()

    def test_reloaded_regions_load_properly(self):
        cache_name = ":memory:"
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        point_region = Graphics.PointGraphic()
        point_region.position = (0.6, 0.4)
        point_region_uuid = point_region.uuid
        DataItem.DisplaySpecifier.from_data_item(data_item).display.add_graphic(point_region)
        document_controller.close()
        # read it back
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        read_data_item = document_controller.document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        # verify
        self.assertEqual(read_display_specifier.display.graphics[0].type, "point-graphic")
        self.assertEqual(read_display_specifier.display.graphics[0].uuid, point_region_uuid)
        self.assertEqual(read_display_specifier.display.graphics[0].position, (0.6, 0.4))
        # clean up
        document_controller.close()

    def test_reloaded_empty_data_groups_load_properly(self):
        cache_name = ":memory:"
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_group = DataGroup.DataGroup()
        document_model.append_data_group(data_group)
        document_controller.close()
        # read it back
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        # clean up
        document_controller.close()

    def test_new_data_item_stores_uuid_and_data_info_in_properties_immediately(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        self.assertTrue("data_shape" in data_item.properties.get("data_source"))
        self.assertTrue("data_dtype" in data_item.properties.get("data_source"))
        self.assertTrue("uuid" in data_item.properties)
        self.assertTrue("version" in data_item.properties)
        document_controller.close()

    def test_deleting_dependent_after_deleting_source_succeeds(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        try:
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                display_specifier.data_item.set_data(numpy.zeros((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                data_item2 = document_model.get_invert_new(data_item)
                data_file_path = data_item._test_get_file_path()
                data2_file_path = data_item2._test_get_file_path()
                # make sure assumptions are correct
                self.assertTrue(os.path.exists(data_file_path))
                self.assertTrue(os.path.isfile(data_file_path))
                self.assertTrue(os.path.exists(data2_file_path))
                self.assertTrue(os.path.isfile(data2_file_path))
            document_model = None
            # delete the original file
            os.remove(data_file_path)
            # read it back the library
            file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)
                self.assertTrue(os.path.isfile(data2_file_path))
                # make sure dependent gets deleted
                document_model.remove_data_item(document_model.data_items[0])
                self.assertFalse(os.path.exists(data2_file_path))
            document_model = None
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_properties_are_able_to_be_cleared_and_reloaded(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((8, 8)))
            document_model.append_data_item(data_item)
            display = DataItem.DisplaySpecifier.from_data_item(data_item).display
            display.display_type = "image"
            display.display_type = None
        # make sure it reloads without changing modification
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            display = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0]).display
            self.assertIsNone(display.display_type)

    def test_properties_with_no_data_reloads(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        try:
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                document_model.append_data_item(data_item)
                data_item.title = "TitleX"
            # read it back the library
            file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)
                self.assertEqual(document_model.data_items[0].title, "TitleX")
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_resized_data_reloads(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        try:
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(data=numpy.zeros((16, 16)))
                document_model.append_data_item(data_item)
                data_item.set_data(numpy.zeros((32, 32)))
            # read it back the library
            file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)
                self.assertEqual(document_model.data_items[0].data.shape, (32, 32))
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_resized_data_reclaims_space(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        try:
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(data=numpy.zeros((32, 32)))
                document_model.append_data_item(data_item)
                data_file_path = data_item._test_get_file_path()
                file_size = os.path.getsize(data_file_path)
                data_item.set_data(numpy.zeros((16, 16)))
                self.assertLess(os.path.getsize(data_file_path), file_size)
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_reloaded_display_has_correct_storage_cache(self):
        cache_name = ":memory:"
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        document_controller.close()
        # read it back
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        read_data_item = document_model.data_items[0]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        # check storage caches
        self.assertEqual(read_display_specifier.display._display_cache.storage_cache, read_data_item._suspendable_storage_cache)
        # clean up
        document_controller.close()

    def test_data_items_written_with_newer_version_get_ignored(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            # increment the version on the data item
            list(memory_persistent_storage_system.properties.values())[0]["version"] = DataItem.DataItem.writer_version + 1
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            # check it
            self.assertEqual(len(document_model.data_items), 0)

    def test_reloading_composite_operation_reconnects_when_reloaded(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
            document_model.append_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.add_graphic(crop_region)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_data_item(data_item)
            new_data_item = document_model.get_invert_new(data_item, crop_region)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            read_data_item = document_model.data_items[0]
            read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
            computation_bounds = document_model.resolve_object_specifier(document_model.get_data_item_computation(document_model.data_items[1]).variables[0].secondary_specifier).value.bounds
            self.assertEqual(read_display_specifier.display.graphics[0].bounds, computation_bounds)
            read_display_specifier.display.graphics[0].bounds = ((0.3, 0.4), (0.5, 0.6))
            computation_bounds = document_model.resolve_object_specifier(document_model.get_data_item_computation(document_model.data_items[1]).variables[0].secondary_specifier).value.bounds
            self.assertEqual(read_display_specifier.display.graphics[0].bounds, computation_bounds)

    def test_inverted_data_item_does_not_need_recompute_when_reloaded(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
            document_model.append_data_item(data_item)
            document_model.get_invert_new(data_item)
            document_model.recompute_all()
        # reload and check inverted data item does not need recompute
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            read_data_item2 = document_model.data_items[1]
            read_display_specifier2 = DataItem.DisplaySpecifier.from_data_item(read_data_item2)
            self.assertFalse(document_model.get_data_item_computation(read_display_specifier2.data_item).needs_update)

    def test_data_item_with_persistent_r_value_does_not_need_recompute_when_reloaded(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        try:
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
                document_model.append_data_item(data_item)
                inverted_data_item = document_model.get_invert_new(data_item)
                document_model.recompute_all()
                document_model.assign_variable_to_library_item(data_item)
                file_path = data_item._test_get_file_path()
            file_path_base, file_path_ext = os.path.splitext(file_path)
            shutil.copyfile(file_path, file_path_base + "_" + file_path_ext)
            # read it back
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage, log_migrations=False)
            with contextlib.closing(document_model):
                read_data_item2 = document_model.data_items[1]
                read_display_specifier2 = DataItem.DisplaySpecifier.from_data_item(read_data_item2)
                self.assertFalse(document_model.get_data_item_computation(read_display_specifier2.data_item).needs_update)
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_computations_with_id_update_to_latest_version_when_reloaded(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        modifieds = dict()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
            crop_region = Graphics.RectangleGraphic()
            data_item.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            cropped_inverted_data_item = document_model.get_invert_new(data_item, crop_region)
            document_model.recompute_all()
            modifieds[str(inverted_data_item.uuid)] = inverted_data_item.modified
            modifieds[str(cropped_inverted_data_item.uuid)] = cropped_inverted_data_item.modified
        # modify original expression to be something else
        original_expressions = dict()
        for data_item_uuid in memory_persistent_storage_system.properties.keys():
            computation_dict = memory_persistent_storage_system.properties[data_item_uuid].get("computation", dict())
            original_expression = computation_dict.get("original_expression")
            if original_expression:
                computation_dict["original_expression"] = "incorrect"
                original_expressions[data_item_uuid] = original_expression
        # reload and check inverted data item has updated original expression, does not need recompute, and has not been modified
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            for data_item_uuid in original_expressions.keys():
                data_item = document_model.get_data_item_by_uuid(uuid.UUID(data_item_uuid))
                self.assertEqual(document_model.get_data_item_computation(data_item).original_expression, original_expressions[data_item_uuid])
                self.assertFalse(document_model.get_data_item_computation(data_item).needs_update)
                self.assertEqual(data_item.modified, modifieds[data_item_uuid])

    def test_cropped_data_item_with_region_does_not_need_recompute_when_reloaded(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
            crop_region = Graphics.RectangleGraphic()
            data_item.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            document_model.get_crop_new(data_item, crop_region)
            document_model.recompute_all()
            read_data_item2 = document_model.data_items[1]
            read_display_specifier2 = DataItem.DisplaySpecifier.from_data_item(read_data_item2)
            self.assertFalse(document_model.get_data_item_computation(read_display_specifier2.data_item).needs_update)
        # reload and check inverted data item does not need recompute
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            self.assertFalse(document_model.get_data_item_computation(document_model.data_items[1]).needs_update)

    def test_cropped_data_item_with_region_still_updates_when_reloaded(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            document_model.get_crop_new(data_item, crop_region)
            document_model.recompute_all()
            read_data_item2 = document_model.data_items[1]
            read_display_specifier2 = DataItem.DisplaySpecifier.from_data_item(read_data_item2)
            self.assertFalse(document_model.get_data_item_computation(read_display_specifier2.data_item).needs_update)
            self.assertEqual(read_display_specifier2.data_item.data_shape, (4, 4))
        # reload and check inverted data item does not need recompute
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            document_model.recompute_all()  # shouldn't be necessary unless other tests fail
            read_data_item = document_model.data_items[0]
            read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
            read_data_item2 = document_model.data_items[1]
            read_display_specifier2 = DataItem.DisplaySpecifier.from_data_item(read_data_item2)
            read_display_specifier.display.graphics[0].bounds = (0.25, 0.25), (0.75, 0.75)
            document_model.recompute_all()
            self.assertEqual(read_display_specifier2.data_item.data_shape, (6, 6))

    def test_data_items_v1_migration(self):
        # construct v1 data item
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        data_item_dict["spatial_calibrations"] = [{ "origin": 1.0, "scale": 2.0, "units": "mm" }, { "origin": 1.0, "scale": 2.0, "units": "mm" }]
        data_item_dict["intensity_calibration"] = { "origin": 0.1, "scale": 0.2, "units": "l" }
        data_item_dict["data_source_uuid"] = str(uuid.uuid4())
        data_item_dict["properties"] = { "voltage": 200.0, "session_uuid": str(uuid.uuid4()) }
        data_item_dict["version"] = 1
        memory_persistent_storage_system.data["A"] = numpy.zeros((8, 8), numpy.uint32)
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check it
            self.assertEqual(len(document_model.data_items), 1)
            data_item = document_model.data_items[0]
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)
            self.assertEqual(len(display_specifier.data_item.dimensional_calibrations), 2)
            self.assertEqual(display_specifier.data_item.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
            self.assertEqual(display_specifier.data_item.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
            self.assertEqual(display_specifier.data_item.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))
            self.assertEqual(data_item.metadata.get("hardware_source")["voltage"], 200.0)
            self.assertFalse("session_uuid" in data_item.metadata.get("hardware_source"))
            self.assertIsNone(data_item.session_id)  # v1 is not allowed to set session_id
            self.assertEqual(display_specifier.data_item.data_dtype, numpy.uint32)
            self.assertEqual(display_specifier.data_item.data_shape, (8, 8))

    def test_data_items_v2_migration(self):
        # construct v2 data item
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        data_item_dict["displays"] = [{"graphics": [{"type": "rect-graphic"}]}]
        data_item_dict["operations"] = [{"operation_id": "invert-operation"}]
        data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_item_dict["master_data_shape"] = (8, 8)
        data_item_dict["version"] = 2
        memory_persistent_storage_system.data["A"] = numpy.zeros((8, 8), numpy.uint32)
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check it
            self.assertEqual(len(document_model.data_items), 1)
            data_item = document_model.data_items[0]
            self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)
            self.assertTrue("uuid" in data_item.properties["displays"][0])
            self.assertTrue("uuid" in data_item.properties["displays"][0]["graphics"][0])

    def test_data_items_v3_migration(self):
        # construct v3 data item
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        data_item_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_item_dict["intrinsic_spatial_calibrations"] = [{ "origin": 1.0, "scale": 2.0, "units": "mm" }, { "origin": 1.0, "scale": 2.0, "units": "mm" }]
        data_item_dict["intrinsic_intensity_calibration"] = { "origin": 0.1, "scale": 0.2, "units": "l" }
        data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_item_dict["master_data_shape"] = (8, 8)
        data_item_dict["version"] = 3
        memory_persistent_storage_system.data["A"] = numpy.zeros((8, 8), numpy.uint32)
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check it
            self.assertEqual(len(document_model.data_items), 1)
            data_item = document_model.data_items[0]
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)
            self.assertEqual(len(display_specifier.data_item.dimensional_calibrations), 2)
            self.assertEqual(display_specifier.data_item.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
            self.assertEqual(display_specifier.data_item.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
            self.assertEqual(display_specifier.data_item.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))

    def test_data_items_v4_migration(self):
        # construct v4 data item
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        data_item_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        region_uuid_str = str(uuid.uuid4())
        data_item_dict["regions"] = [{"type": "rectangle-region", "uuid": region_uuid_str}]
        data_item_dict["operations"] = [{"operation_id": "crop-operation", "region_uuid": region_uuid_str}]
        data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_item_dict["master_data_shape"] = (8, 8)
        data_item_dict["version"] = 4
        memory_persistent_storage_system.data["A"] = numpy.zeros((8, 8), numpy.uint32)
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check it
            self.assertEqual(len(document_model.data_items), 1)
            data_item = document_model.data_items[0]
            self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)
            self.assertIsNotNone(document_model.get_data_item_computation(data_item))
            # not really checking beyond this; the program has changed enough to make the region connection not work without a data source

    def test_data_items_v5_migration(self):
        # construct v5 data item
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        data_item_dict["uuid"] = str(uuid.uuid4())
        data_item_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_item_dict["master_data_shape"] = (8, 8)
        data_item_dict["intrinsic_spatial_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        data_item_dict["intrinsic_intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        data_item_dict["datetime_original"] = {'dst': '+60', 'tz': '-0800', 'local_datetime': '2000-06-30T15:01:00.000000'}
        data_item_dict["version"] = 5
        memory_persistent_storage_system.data["A"] = numpy.zeros((8, 8), numpy.uint32)
        data_item2_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        data_item2_dict["uuid"] = str(uuid.uuid4())
        data_item2_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_item2_dict["operations"] = [{"operation_id": "invert-operation"}]
        data_item2_dict["data_sources"] = [data_item_dict["uuid"]]
        data_item2_dict["datetime_original"] = {'dst': '+60', 'tz': '-0800', 'local_datetime': '2000-06-30T15:02:00.000000'}
        data_item2_dict["version"] = 5
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check it
            self.assertEqual(len(document_model.data_items), 2)
            self.assertEqual(str(document_model.data_items[0].uuid), data_item_dict["uuid"])
            self.assertEqual(str(document_model.data_items[1].uuid), data_item2_dict["uuid"])
            data_item = document_model.data_items[1]
            self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)
            self.assertIsNotNone(document_model.get_data_item_computation(data_item))
            self.assertEqual(len(document_model.get_data_item_computation(data_item).variables), 1)
            self.assertEqual(document_model.resolve_object_specifier(document_model.get_data_item_computation(data_item).variables[0].variable_specifier).value.data_item, document_model.data_items[0])
            # calibration renaming
            data_item = document_model.data_items[0]
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(len(display_specifier.data_item.dimensional_calibrations), 2)
            self.assertEqual(display_specifier.data_item.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
            self.assertEqual(display_specifier.data_item.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
            self.assertEqual(display_specifier.data_item.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))

    def test_data_items_v6_migration(self):
        # construct v6 data item
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        data_item_dict["uuid"] = str(uuid.uuid4())
        data_item_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_item_dict["master_data_shape"] = (8, 8)
        data_item_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        data_item_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        data_item_dict["datetime_original"] = {'dst': '+60', 'tz': '-0800', 'local_datetime': '2000-06-30T15:01:00.000000'}
        data_item_dict["version"] = 6
        memory_persistent_storage_system.data["A"] = numpy.zeros((8, 8), numpy.uint32)
        data_item2_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        data_item2_dict["uuid"] = str(uuid.uuid4())
        data_item2_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_item2_dict["operation"] = {"type": "operation", "operation_id": "invert-operation", "data_sources": [{"type": "data-item-data-source", "data_item_uuid": data_item_dict["uuid"]}]}
        data_item2_dict["version"] = 6
        data_item3_dict = memory_persistent_storage_system.properties.setdefault("C", dict())
        data_item3_dict["uuid"] = str(uuid.uuid4())
        data_item3_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_item3_dict["master_data_dtype"] = None
        data_item3_dict["master_data_shape"] = None
        data_item3_dict["dimensional_calibrations"] = []
        data_item3_dict["intensity_calibration"] = {}
        data_item2_dict["datetime_original"] = {'dst': '+60', 'tz': '-0800', 'local_datetime': '2000-06-30T15:02:00.000000'}
        data_item3_dict["version"] = 6
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # # check it
            self.assertEqual(len(document_model.data_items), 3)
            self.assertEqual(str(document_model.data_items[0].uuid), data_item_dict["uuid"])
            self.assertEqual(str(document_model.data_items[1].uuid), data_item2_dict["uuid"])
            self.assertEqual(str(document_model.data_items[2].uuid), data_item3_dict["uuid"])
            data_item = document_model.data_items[1]
            self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)
            self.assertIsNotNone(document_model.get_data_item_computation(data_item))
            self.assertEqual(len(document_model.get_data_item_computation(data_item).variables), 1)
            self.assertEqual(document_model.resolve_object_specifier(document_model.get_data_item_computation(data_item).variables[0].variable_specifier).value.data_item, document_model.data_items[0])
            # calibration renaming
            data_item = document_model.data_items[0]
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(len(display_specifier.data_item.dimensional_calibrations), 2)
            self.assertEqual(display_specifier.data_item.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
            self.assertEqual(display_specifier.data_item.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
            self.assertEqual(display_specifier.data_item.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))

    def test_data_items_v7_migration(self):
        # construct v7 data item
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
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
        data_source_dict["data_shape"] = (8, 8)
        data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        data_item_dict["data_sources"] = [data_source_dict]
        metadata = {"instrument": "a big screwdriver", "extra_high_tension": 42}
        new_metadata = {"instrument": "a big screwdriver", "autostem": { "high_tension_v": 42}, "extra_high_tension": 42 }
        data_item_dict["hardware_source"] = metadata
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 1)
            self.assertEqual(document_model.data_items[0].metadata.get("hardware_source"), new_metadata)
            self.assertEqual(document_model.data_items[0].caption, caption)
            self.assertEqual(document_model.data_items[0].flag, flag)
            self.assertEqual(document_model.data_items[0].rating, rating)
            self.assertEqual(document_model.data_items[0].title, title)
            self.assertEqual(document_model.data_items[0].created, datetime.datetime.strptime("2000-06-30T22:02:00.000000", "%Y-%m-%dT%H:%M:%S.%f"))
            self.assertEqual(document_model.data_items[0].modified, document_model.data_items[0].created)
            self.assertEqual(document_model.data_items[0].metadata.get("hardware_source").get("autostem").get("high_tension_v"), 42)

    def test_data_items_v8_to_v9_fft_migration(self):
        # construct v8 data items
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_data_item_dict["uuid"] = str(uuid.uuid4())
        src_data_item_dict["version"] = 8
        src_data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        src_data_source_dict["uuid"] = src_uuid_str
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        src_data_item_dict["data_sources"] = [src_data_source_dict]
        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 8
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        dst_reference = dict()
        dst_reference["uuid"] = str(uuid.uuid4())
        dst_reference["type"] = "operation"
        dst_reference["values"] = {}  # TODO: make one with values
        dst_reference["region_connections"] = {}  # TODO: make one with region connections
        dst_reference["operation_id"] = "fft-operation"
        dst_reference["data_sources"] = [{"buffered_data_source_uuid": src_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}]
        dst_data_source_dict["data_source"] = dst_reference
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(computation.processing_id, "fft")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.fft(src.cropped_display_xdata)"))
            self.assertEqual(len(computation.variables), 1)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier).value.data_item, document_model.data_items[0])
            data = numpy.arange(64).reshape((8, 8))
            document_model.data_items[0].set_data(data)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_cross_correlate_migration(self):
        # construct v8 data items
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()

        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_data_item_dict["uuid"] = str(uuid.uuid4())
        src_data_item_dict["version"] = 8
        src_data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        src_data_source_dict["uuid"] = src_uuid_str
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        src_data_item_dict["data_sources"] = [src_data_source_dict]

        src2_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        src2_data_item_dict["uuid"] = str(uuid.uuid4())
        src2_data_item_dict["version"] = 8
        src2_data_source_dict = dict()
        src2_uuid_str = str(uuid.uuid4())
        src2_data_source_dict["uuid"] = src2_uuid_str
        src2_data_source_dict["type"] = "buffered-data-source"
        src2_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src2_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src2_data_source_dict["data_shape"] = (8, 8)
        src2_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src2_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        src2_data_item_dict["data_sources"] = [src2_data_source_dict]

        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("C", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 8
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        dst_reference = dict()
        dst_reference["uuid"] = str(uuid.uuid4())
        dst_reference["type"] = "operation"
        dst_reference["values"] = {}  # TODO: make one with values
        dst_reference["region_connections"] = {}  # TODO: make one with region connections
        dst_reference["operation_id"] = "cross-correlate-operation"
        dst_reference["data_sources"] = [{"buffered_data_source_uuid": src_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}, {"buffered_data_source_uuid": src2_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}]
        dst_data_source_dict["data_source"] = dst_reference
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 3)
            computation = document_model.get_data_item_computation(document_model.data_items[2])
            self.assertEqual(computation.processing_id, "cross-correlate")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.crosscorrelate(src1.cropped_display_xdata, src2.cropped_display_xdata)"))
            self.assertEqual(len(computation.variables), 2)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier).value.data_item, document_model.data_items[0])
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[1].variable_specifier).value.data_item, document_model.data_items[1])
            data1 = numpy.arange(64).reshape((8, 8))
            document_model.data_items[0].set_data(data1)
            data2 = numpy.arange(64).reshape((8, 8))
            document_model.data_items[1].set_data(data2)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_gaussian_blur_migration(self):
        # construct v8 data items
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_data_item_dict["uuid"] = str(uuid.uuid4())
        src_data_item_dict["version"] = 8
        src_data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        src_data_source_dict["uuid"] = src_uuid_str
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        crop_uuid_str = str(uuid.uuid4())
        src_data_source_dict["regions"] = [{"type": "rectangle-region", "uuid": crop_uuid_str, "size": (0.4, 0.5), "center": (0.4, 0.55)}]
        src_data_item_dict["data_sources"] = [src_data_source_dict]
        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 8
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        crop_data_source_dict = dict()
        crop_data_source_dict["uuid"] = str(uuid.uuid4())
        crop_data_source_dict["type"] = "buffered-data-source"
        crop_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        crop_data_source_dict["dimensional_calibrations"] = []
        crop_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        crop_reference = dict()
        crop_reference["uuid"] = str(uuid.uuid4())
        crop_reference["type"] = "operation"
        crop_reference["values"] = {"value": {"bounds": ((0.2, 0.3), (0.4, 0.5))}}
        crop_reference["region_connections"] = {"crop": crop_uuid_str}
        crop_reference["operation_id"] = "crop-operation"
        crop_reference["data_sources"] = [{"buffered_data_source_uuid": src_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}]
        dst_reference = dict()
        dst_reference["uuid"] = str(uuid.uuid4())
        dst_reference["type"] = "operation"
        dst_reference["values"] = {"sigma": 1.7}
        dst_reference["region_connections"] = {}
        dst_reference["operation_id"] = "gaussian-blur-operation"
        dst_reference["data_sources"] = [crop_reference]
        dst_data_source_dict["data_source"] = dst_reference
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(computation.processing_id, "gaussian-blur")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.gaussian_blur(src.cropped_display_xdata, sigma)"))
            self.assertEqual(len(computation.variables), 2)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.data_item, document_model.data_items[0])
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.graphic, document_model.data_items[0].displays[0].graphics[0])
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].bounds[0][0], 0.2)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].bounds[0][1], 0.3)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].bounds[1][0], 0.4)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].bounds[1][1], 0.5)
            self.assertAlmostEqual(computation.variables[1].bound_variable.value, 1.7)
            data = numpy.arange(64).reshape((8, 8))
            document_model.data_items[0].set_data(data)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_median_filter_migration(self):
        # construct v8 data items
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_data_item_dict["uuid"] = str(uuid.uuid4())
        src_data_item_dict["version"] = 8
        src_data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        src_data_source_dict["uuid"] = src_uuid_str
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        src_data_item_dict["data_sources"] = [src_data_source_dict]
        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 8
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        dst_reference = dict()
        dst_reference["uuid"] = str(uuid.uuid4())
        dst_reference["type"] = "operation"
        dst_reference["values"] = {"size": 5}
        dst_reference["region_connections"] = {}
        dst_reference["operation_id"] = "median-filter-operation"
        dst_reference["data_sources"] = [{"buffered_data_source_uuid": src_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}]
        dst_data_source_dict["data_source"] = dst_reference
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(computation.processing_id, "median-filter")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.median_filter(src.cropped_display_xdata, filter_size)"))
            self.assertEqual(len(computation.variables), 2)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier).value.data_item, document_model.data_items[0])
            self.assertAlmostEqual(computation.variables[1].bound_variable.value, 5)
            data = numpy.arange(64).reshape((8, 8))
            document_model.data_items[0].set_data(data)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_slice_migration(self):
        # construct v8 data items
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_data_item_dict["uuid"] = str(uuid.uuid4())
        src_data_item_dict["version"] = 8
        src_data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        src_data_source_dict["uuid"] = src_uuid_str
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        src_data_item_dict["data_sources"] = [src_data_source_dict]
        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 8
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        dst_reference = dict()
        dst_reference["uuid"] = str(uuid.uuid4())
        dst_reference["type"] = "operation"
        dst_reference["values"] = {"slice_center": 3, "slice_width": 2}
        dst_reference["region_connections"] = {}
        dst_reference["operation_id"] = "slice-operation"
        dst_reference["data_sources"] = [{"buffered_data_source_uuid": src_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}]
        dst_data_source_dict["data_source"] = dst_reference
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(computation.processing_id, "slice")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.slice_sum(src.cropped_xdata, center, width)"))
            self.assertEqual(len(computation.variables), 3)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier).value.data_item, document_model.data_items[0])
            self.assertAlmostEqual(computation.variables[1].bound_variable.value, 3)
            self.assertAlmostEqual(computation.variables[2].bound_variable.value, 2)
            data = numpy.arange(512).reshape((8, 8, 8))
            document_model.data_items[0].set_data(data)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_crop_migration(self):
        # construct v8 data items
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_data_item_dict["uuid"] = str(uuid.uuid4())
        src_data_item_dict["version"] = 8
        src_data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        src_data_source_dict["uuid"] = src_uuid_str
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        crop_uuid_str = str(uuid.uuid4())
        src_data_source_dict["regions"] = [{"type": "rectangle-region", "uuid": crop_uuid_str, "size": (0.4, 0.5), "center": (0.4, 0.55)}]
        src_data_item_dict["data_sources"] = [src_data_source_dict]
        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 8
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        dst_reference = dict()
        dst_reference["uuid"] = str(uuid.uuid4())
        dst_reference["type"] = "operation"
        dst_reference["values"] = {}
        dst_reference["region_connections"] = {"crop": crop_uuid_str}
        dst_reference["operation_id"] = "crop-operation"
        dst_reference["data_sources"] = [{"buffered_data_source_uuid": src_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}]
        dst_data_source_dict["data_source"] = dst_reference
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(computation.processing_id, "crop")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("src.cropped_display_xdata"))
            self.assertEqual(len(computation.variables), 1)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.data_item, document_model.data_items[0])
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.graphic, document_model.data_items[0].displays[0].graphics[0])
            data = numpy.arange(64).reshape((8, 8))
            document_model.data_items[0].set_data(data)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_projection_migration(self):
        # construct v8 data items
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_data_item_dict["uuid"] = str(uuid.uuid4())
        src_data_item_dict["version"] = 8
        src_data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        src_data_source_dict["uuid"] = src_uuid_str
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        crop_uuid_str = str(uuid.uuid4())
        src_data_source_dict["regions"] = [{"type": "rectangle-region", "uuid": crop_uuid_str, "size": (0.4, 0.5), "center": (0.4, 0.55)}]
        src_data_item_dict["data_sources"] = [src_data_source_dict]
        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 8
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        crop_data_source_dict = dict()
        crop_data_source_dict["uuid"] = str(uuid.uuid4())
        crop_data_source_dict["type"] = "buffered-data-source"
        crop_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        crop_data_source_dict["dimensional_calibrations"] = []
        crop_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        crop_reference = dict()
        crop_reference["uuid"] = str(uuid.uuid4())
        crop_reference["type"] = "operation"
        crop_reference["values"] = {"value": {"bounds": ((0.2, 0.3), (0.4, 0.5))}}
        crop_reference["region_connections"] = {"crop": crop_uuid_str}
        crop_reference["operation_id"] = "crop-operation"
        crop_reference["data_sources"] = [{"buffered_data_source_uuid": src_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}]
        dst_reference = dict()
        dst_reference["uuid"] = str(uuid.uuid4())
        dst_reference["type"] = "operation"
        dst_reference["values"] = {}
        dst_reference["region_connections"] = {}
        dst_reference["operation_id"] = "projection-operation"
        dst_reference["data_sources"] = [crop_reference]
        dst_data_source_dict["data_source"] = dst_reference
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(computation.processing_id, "sum")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.sum(src.cropped_xdata, src.xdata.datum_dimension_indexes[0])"))
            self.assertEqual(len(computation.variables), 1)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.data_item, document_model.data_items[0])
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.graphic, document_model.data_items[0].displays[0].graphics[0])
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].bounds[0][0], 0.2)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].bounds[0][1], 0.3)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].bounds[1][0], 0.4)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].bounds[1][1], 0.5)
            data = numpy.arange(64).reshape((8, 8))
            document_model.data_items[0].set_data(data)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_convert_to_scalar_migration(self):
        # construct v8 data items
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_data_item_dict["uuid"] = str(uuid.uuid4())
        src_data_item_dict["version"] = 8
        src_data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        src_data_source_dict["uuid"] = src_uuid_str
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        crop_uuid_str = str(uuid.uuid4())
        src_data_source_dict["regions"] = [{"type": "rectangle-region", "uuid": crop_uuid_str, "size": (0.4, 0.5), "center": (0.4, 0.55)}]
        src_data_item_dict["data_sources"] = [src_data_source_dict]
        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 8
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        crop_data_source_dict = dict()
        crop_data_source_dict["uuid"] = str(uuid.uuid4())
        crop_data_source_dict["type"] = "buffered-data-source"
        crop_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        crop_data_source_dict["dimensional_calibrations"] = []
        crop_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        crop_reference = dict()
        crop_reference["uuid"] = str(uuid.uuid4())
        crop_reference["type"] = "operation"
        crop_reference["values"] = {"value": {"bounds": ((0.2, 0.3), (0.4, 0.5))}}
        crop_reference["region_connections"] = {"crop": crop_uuid_str}
        crop_reference["operation_id"] = "crop-operation"
        crop_reference["data_sources"] = [{"buffered_data_source_uuid": src_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}]
        dst_reference = dict()
        dst_reference["uuid"] = str(uuid.uuid4())
        dst_reference["type"] = "operation"
        dst_reference["values"] = {}
        dst_reference["region_connections"] = {}
        dst_reference["operation_id"] = "convert-to-scalar-operation"
        dst_reference["data_sources"] = [crop_reference]
        dst_data_source_dict["data_source"] = dst_reference
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(computation.processing_id, "convert-to-scalar")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("src.cropped_display_xdata"))
            self.assertEqual(len(computation.variables), 1)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.data_item, document_model.data_items[0])
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.graphic, document_model.data_items[0].displays[0].graphics[0])
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].bounds[0][0], 0.2)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].bounds[0][1], 0.3)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].bounds[1][0], 0.4)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].bounds[1][1], 0.5)
            data = numpy.arange(64).reshape((8, 8))
            document_model.data_items[0].set_data(data)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_resample_migration(self):
        # construct v8 data items
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_data_item_dict["uuid"] = str(uuid.uuid4())
        src_data_item_dict["version"] = 8
        src_data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        src_data_source_dict["uuid"] = src_uuid_str
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        src_data_item_dict["data_sources"] = [src_data_source_dict]
        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 8
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        dst_reference = dict()
        dst_reference["uuid"] = str(uuid.uuid4())
        dst_reference["type"] = "operation"
        dst_reference["values"] = {"width": 200}  # height intentionally missing
        dst_reference["region_connections"] = {}
        dst_reference["operation_id"] = "resample-operation"
        dst_reference["data_sources"] = [{"buffered_data_source_uuid": src_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}]
        dst_data_source_dict["data_source"] = dst_reference
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(computation.processing_id, "resample")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.resample_image(src.cropped_display_xdata, (height, width))"))
            self.assertEqual(len(computation.variables), 3)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier).value.data_item, document_model.data_items[0])
            self.assertAlmostEqual(computation.variables[1].bound_variable.value, 200)
            self.assertAlmostEqual(computation.variables[2].bound_variable.value, 256)
            data = numpy.arange(64).reshape((8, 8))
            document_model.data_items[0].set_data(data)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_pick_migration(self):
        # construct v8 data items
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_data_item_dict["uuid"] = str(uuid.uuid4())
        src_data_item_dict["version"] = 8
        src_data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        src_data_source_dict["uuid"] = src_uuid_str
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        point_uuid_str = str(uuid.uuid4())
        src_data_source_dict["regions"] = [{"type": "point-region", "uuid": point_uuid_str, "position": (0.4, 0.5)}]
        src_data_item_dict["data_sources"] = [src_data_source_dict]
        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 8
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        dst_reference = dict()
        dst_reference["uuid"] = str(uuid.uuid4())
        dst_reference["type"] = "operation"
        dst_reference["values"] = {}
        dst_reference["region_connections"] = {"pick": point_uuid_str}
        dst_reference["operation_id"] = "pick-operation"
        dst_reference["data_sources"] = [{"buffered_data_source_uuid": src_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}]
        dst_data_source_dict["data_source"] = dst_reference
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(computation.processing_id, "pick-point")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.pick(src.xdata, pick_region.position)"))
            self.assertEqual(len(computation.variables), 2)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier).value.data_item, document_model.data_items[0])
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[1].variable_specifier).value, document_model.data_items[0].displays[0].graphics[0])
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].position[0], 0.4)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].position[1], 0.5)
            data = numpy.arange(512).reshape((8, 8, 8))
            document_model.data_items[0].set_data(data)
            data0 = DocumentModel.evaluate_data(computation).data
            self.assertIsNone(computation.error_text)
            document_model.data_items[0].displays[0].graphics[0].position = 0.0, 0.0
            data1 = DocumentModel.evaluate_data(computation).data
            self.assertIsNone(computation.error_text)
            self.assertFalse(numpy.array_equal(data0, data1))
            self.assertTrue(numpy.array_equal(data1, data[0, 0, :]))
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_line_profile_migration(self):
        # construct v8 data items
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_data_item_dict["uuid"] = str(uuid.uuid4())
        src_data_item_dict["version"] = 8
        src_data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        src_data_source_dict["uuid"] = src_uuid_str
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        line_uuid_str = str(uuid.uuid4())
        src_data_source_dict["regions"] = [{"type": "line-region", "uuid": line_uuid_str, "width": 1.3, "start": (0.2, 0.3), "end": (0.4, 0.5)}]
        src_data_item_dict["data_sources"] = [src_data_source_dict]
        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 8
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        dst_reference = dict()
        dst_reference["uuid"] = str(uuid.uuid4())
        dst_reference["type"] = "operation"
        dst_reference["values"] = {}
        dst_reference["region_connections"] = {"line": line_uuid_str}
        dst_reference["operation_id"] = "line-profile-operation"
        dst_reference["data_sources"] = [{"buffered_data_source_uuid": src_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}]
        dst_data_source_dict["data_source"] = dst_reference
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(computation.processing_id, "line-profile")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.line_profile(src.display_xdata, line_region.vector, line_region.line_width)"))
            self.assertEqual(len(computation.variables), 2)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier).value.data_item, document_model.data_items[0])
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[1].variable_specifier).value, document_model.data_items[0].displays[0].graphics[0])
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].start[0], 0.2)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].start[1], 0.3)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].end[0], 0.4)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].end[1], 0.5)
            self.assertAlmostEqual(document_model.data_items[0].displays[0].graphics[0].width, 1.3)
            data = numpy.arange(64).reshape((8, 8))
            document_model.data_items[0].set_data(data)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_unknown_migration(self):
        # construct v8 data items
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_data_item_dict["uuid"] = str(uuid.uuid4())
        src_data_item_dict["version"] = 8
        src_data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        src_data_source_dict["uuid"] = src_uuid_str
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        src_data_item_dict["data_sources"] = [src_data_source_dict]
        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 8
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        dst_reference = dict()
        dst_reference["uuid"] = str(uuid.uuid4())
        dst_reference["type"] = "operation"
        dst_reference["values"] = {}  # TODO: make one with values
        dst_reference["region_connections"] = {}  # TODO: make one with region connections
        dst_reference["operation_id"] = "unknown-bad-operation"
        dst_reference["data_sources"] = [{"buffered_data_source_uuid": src_uuid_str, "type": "data-item-data-source", "uuid": str(uuid.uuid4())}]
        dst_data_source_dict["data_source"] = dst_reference
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            self.assertIsNone(document_model.get_data_item_computation(document_model.data_items[1]))
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v9_to_v10_migration(self):
        # construct v9 data items with regions, make sure they get translated to graphics
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        data_item_dict["uuid"] = str(uuid.uuid4())
        data_item_dict["version"] = 9
        data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        data_source_dict["uuid"] = src_uuid_str
        data_source_dict["type"] = "buffered-data-source"
        data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_source_dict["data_shape"] = (8, 8)
        data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        point_uuid_str = str(uuid.uuid4())
        line_uuid_str = str(uuid.uuid4())
        rect_uuid_str = str(uuid.uuid4())
        ellipse_uuid_str = str(uuid.uuid4())
        interval_uuid_str = str(uuid.uuid4())
        data_source_dict["regions"] = [
            {"type": "point-region", "uuid": point_uuid_str, "region_id": "point", "label": "PointR", "position": (0.4, 0.5)},
            {"type": "line-region", "uuid": line_uuid_str, "region_id": "line", "label": "LineR", "width": 1.3, "start": (0.2, 0.3), "end": (0.4, 0.5)},
            {"type": "rectangle-region", "uuid": rect_uuid_str, "region_id": "rect", "label": "RectR", "center": (0.4, 0.3), "size": (0.44, 0.33)},
            {"type": "ellipse-region", "uuid": ellipse_uuid_str, "region_id": "ellipse", "label": "EllipseR", "center": (0.4, 0.3), "size": (0.44, 0.33)},
            {"type": "interval-region", "uuid": interval_uuid_str, "region_id": "interval", "label": "IntervalR", "start": 0.2, "end": 0.3},
            # NOTE: channel-region was introduced after 10
        ]
        data_item_dict["data_sources"] = [data_source_dict]
        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 1)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0])
            graphics = display_specifier.display.graphics
            self.assertEqual(len(graphics), 5)
            self.assertIsInstance(graphics[0], Graphics.PointGraphic)
            self.assertEqual(str(graphics[0].uuid), point_uuid_str)
            self.assertEqual(graphics[0].graphic_id, "point")
            self.assertAlmostEqual(graphics[0].position[0], 0.4)
            self.assertAlmostEqual(graphics[0].position[1], 0.5)
            self.assertIsInstance(graphics[1], Graphics.LineProfileGraphic)
            self.assertEqual(str(graphics[1].uuid), line_uuid_str)
            self.assertEqual(graphics[1].graphic_id, "line")
            self.assertAlmostEqual(graphics[1].width, 1.3)
            self.assertAlmostEqual(graphics[1].start[0], 0.2)
            self.assertAlmostEqual(graphics[1].start[1], 0.3)
            self.assertAlmostEqual(graphics[1].end[0], 0.4)
            self.assertAlmostEqual(graphics[1].end[1], 0.5)
            self.assertIsInstance(graphics[2], Graphics.RectangleGraphic)
            self.assertEqual(str(graphics[2].uuid), rect_uuid_str)
            self.assertEqual(graphics[2].graphic_id, "rect")
            self.assertAlmostEqual(graphics[2].bounds[0][0], 0.4 - 0.44/2)
            self.assertAlmostEqual(graphics[2].bounds[0][1], 0.3 - 0.33/2)
            self.assertAlmostEqual(graphics[2].bounds[1][0], 0.44)
            self.assertAlmostEqual(graphics[2].bounds[1][1], 0.33)
            self.assertIsInstance(graphics[3], Graphics.EllipseGraphic)
            self.assertEqual(str(graphics[3].uuid), ellipse_uuid_str)
            self.assertEqual(graphics[3].graphic_id, "ellipse")
            self.assertAlmostEqual(graphics[3].bounds[0][0], 0.4 - 0.44/2)
            self.assertAlmostEqual(graphics[3].bounds[0][1], 0.3 - 0.33/2)
            self.assertAlmostEqual(graphics[3].bounds[1][0], 0.44)
            self.assertAlmostEqual(graphics[3].bounds[1][1], 0.33)
            self.assertIsInstance(graphics[4], Graphics.IntervalGraphic)
            self.assertEqual(str(graphics[4].uuid), interval_uuid_str)
            self.assertEqual(graphics[4].graphic_id, "interval")
            self.assertAlmostEqual(graphics[4].start, 0.2)
            self.assertAlmostEqual(graphics[4].end, 0.3)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v9_to_v10_line_profile_migration(self):
        # construct v9 data items with regions, make sure they get translated to graphics
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()

        data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        data_item_uuid = str(uuid.uuid4())
        data_item_dict["uuid"] = data_item_uuid
        data_item_dict["version"] = 9
        data_source_dict = dict()
        src_uuid_str = str(uuid.uuid4())
        data_source_dict["uuid"] = src_uuid_str
        data_source_dict["type"] = "buffered-data-source"
        data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        data_source_dict["data_shape"] = (8, 8)
        data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        line_uuid_str = str(uuid.uuid4())
        data_source_dict["regions"] = [
            {"type": "line-region", "uuid": line_uuid_str, "region_id": "line", "label": "LineR", "width": 1.3, "start": (0.2, 0.3), "end": (0.4, 0.5)},
        ]
        data_item_dict["data_sources"] = [data_source_dict]

        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_uuid = str(uuid.uuid4())
        dst_data_item_dict["uuid"] = dst_data_item_uuid
        dst_data_item_dict["version"] = 9
        dst_data_source_dict = dict()
        dst_data_source_uuid = str(uuid.uuid4())
        dst_data_source_dict["uuid"] = dst_data_source_uuid
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        computation_dict = {"type": "computation", "processing_id": "line-profile", "uuid": str(uuid.uuid4())}
        computation_dict["original_expression"] = "line_profile(src.display_data, line_region.vector, line_region.width)"
        variables = list()
        computation_dict["variables"] = variables
        variables.append({"name": "src", "specifier": {"type": "data_item", "uuid": data_item_uuid, "version": 1}, "type": "variable", "uuid": str(uuid.uuid4())})
        variables.append({"name": "line_region", "specifier": {"type": "region", "uuid": line_uuid_str, "version": 1}, "type": "variable", "uuid": str(uuid.uuid4())})
        dst_data_source_dict["computation"] = computation_dict
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]
        dst_data_item_dict["connections"] = [{"source_uuid": dst_data_source_uuid, "target_uuid": line_uuid_str, "type": "interval-list-connection", "uuid": str(uuid.uuid4())}]

        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            src_display_specifier = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[0])
            dst_display_specifier = DataItem.DisplaySpecifier.from_data_item(document_model.data_items[1])
            self.assertEqual(src_display_specifier.display.graphics[0], document_model.resolve_object_specifier(document_model.get_data_item_computation(dst_display_specifier.data_item).variables[1].variable_specifier).value)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v10_to_v11_created_date_migration(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()

        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_uuid_str = str(uuid.uuid4())
        src_data_item_dict["uuid"] = src_uuid_str
        src_data_item_dict["version"] = 10
        created_str = "2015-01-22T17:16:12.421290"
        modified_str = "2015-01-22T17:16:12.421291"
        src_data_item_dict["created"] = created_str
        src_data_item_dict["modified"] = modified_str
        src_data_source_dict = dict()
        src_data_source_dict["uuid"] = str(uuid.uuid4())
        src_data_source_dict["type"] = "buffered-data-source"
        crop_uuid_str = str(uuid.uuid4())
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        src_data_item_dict["data_sources"] = [src_data_source_dict]

        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            self.assertEqual(document_model.data_items[0].created.date(), DataItem.DatetimeToStringConverter().convert_back(created_str).date())
            self.assertEqual(document_model.data_items[0].modified.date(), DataItem.DatetimeToStringConverter().convert_back(modified_str).date())

    def test_data_items_v10_to_v11_crop_migration(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()

        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_uuid_str = str(uuid.uuid4())
        src_data_item_dict["uuid"] = src_uuid_str
        src_data_item_dict["version"] = 10
        src_data_source_dict = dict()
        src_data_source_dict["uuid"] = str(uuid.uuid4())
        src_data_source_dict["type"] = "buffered-data-source"
        crop_uuid_str = str(uuid.uuid4())
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4()), "graphics": [{"type": "rect-graphic", "uuid": crop_uuid_str, "bounds": ((0.6, 0.4), (0.5, 0.5))}]}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        src_data_item_dict["data_sources"] = [src_data_source_dict]

        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("C", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 10
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        computation_dict = dict()
        computation_dict["processing_id"] = "crop"
        computation_dict["uuid"] = str(uuid.uuid4())
        variables_list = computation_dict.setdefault("variables", list())
        variables_list.append({"name": "src", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "data_item", "version": 1, "uuid": src_uuid_str}})
        variables_list.append({"name": "crop_region", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "region", "version": 1, "uuid": crop_uuid_str}})
        dst_data_source_dict["computation"] = computation_dict
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]

        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(computation.processing_id, "crop")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("src.cropped_display_xdata"))
            self.assertEqual(len(computation.variables), 1)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.data_item, document_model.data_items[0])
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.graphic, document_model.data_items[0].displays[0].graphics[0])
            data = numpy.arange(64).reshape((8, 8))
            document_model.data_items[0].set_data(data)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v10_to_v11_gaussian_migration(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()

        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_uuid_str = str(uuid.uuid4())
        src_data_item_dict["uuid"] = src_uuid_str
        src_data_item_dict["version"] = 10
        src_data_source_dict = dict()
        src_data_source_dict["uuid"] = str(uuid.uuid4())
        src_data_source_dict["type"] = "buffered-data-source"
        crop_uuid_str = str(uuid.uuid4())
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4()), "graphics": [{"type": "rect-graphic", "uuid": crop_uuid_str, "bounds": ((0.6, 0.4), (0.5, 0.5))}]}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        src_data_item_dict["data_sources"] = [src_data_source_dict]

        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("C", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 10
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        computation_dict = dict()
        computation_dict["processing_id"] = "gaussian-blur"
        computation_dict["uuid"] = str(uuid.uuid4())
        variables_list = computation_dict.setdefault("variables", list())
        variables_list.append({"name": "src", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "data_item", "version": 1, "uuid": src_uuid_str}})
        variables_list.append({"name": "crop_region", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "region", "version": 1, "uuid": crop_uuid_str}})
        variables_list.append({"name": "sigma", "type": "variable", "uuid": str(uuid.uuid4()), "value": 3.0, "value_type": "real"})
        dst_data_source_dict["computation"] = computation_dict
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]

        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 2)
            computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(computation.processing_id, "gaussian-blur")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.gaussian_blur(src.cropped_display_xdata, sigma)"))
            self.assertEqual(len(computation.variables), 2)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.data_item, document_model.data_items[0])
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.graphic, document_model.data_items[0].displays[0].graphics[0])
            data = numpy.arange(64).reshape((8, 8))
            document_model.data_items[0].set_data(data)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v10_to_v11_cross_correlate_migration(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()

        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_uuid_str = str(uuid.uuid4())
        src_data_item_dict["uuid"] = src_uuid_str
        src_data_item_dict["version"] = 10
        src_data_source_dict = dict()
        src_data_source_dict["uuid"] = str(uuid.uuid4())
        src_data_source_dict["type"] = "buffered-data-source"
        crop_uuid_str = str(uuid.uuid4())
        src_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4()), "graphics": [{"type": "rect-graphic", "uuid": crop_uuid_str, "bounds": ((0.6, 0.4), (0.5, 0.5))}]}]
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        src_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        src_data_item_dict["data_sources"] = [src_data_source_dict]

        src2_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        src2_uuid_str = str(uuid.uuid4())
        src2_data_item_dict["uuid"] = src2_uuid_str
        src2_data_item_dict["version"] = 10
        src2_data_source_dict = dict()
        src2_data_source_dict["uuid"] = str(uuid.uuid4())
        src2_data_source_dict["type"] = "buffered-data-source"
        crop2_uuid_str = str(uuid.uuid4())
        src2_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4()), "graphics": [{"type": "rect-graphic", "uuid": crop2_uuid_str, "bounds": ((0.6, 0.4), (0.5, 0.5))}]}]
        src2_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src2_data_source_dict["data_shape"] = (8, 8)
        src2_data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
        src2_data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
        src2_data_item_dict["data_sources"] = [src2_data_source_dict]

        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("C", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 10
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
        dst_data_source_dict["dimensional_calibrations"] = []
        dst_data_source_dict["intensity_calibration"] = { "offset": 0.0, "scale": 1.0, "units": "" }
        computation_dict = dict()
        computation_dict["processing_id"] = "cross-correlate"
        computation_dict["uuid"] = str(uuid.uuid4())
        variables_list = computation_dict.setdefault("variables", list())
        variables_list.append({"name": "src1", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "data_item", "version": 1, "uuid": src_uuid_str}})
        variables_list.append({"name": "src2", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "data_item", "version": 1, "uuid": src2_uuid_str}})
        variables_list.append({"name": "crop_region0", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "region", "version": 1, "uuid": crop_uuid_str}})
        variables_list.append({"name": "crop_region1", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "region", "version": 1, "uuid": crop2_uuid_str}})
        dst_data_source_dict["computation"] = computation_dict
        dst_data_item_dict["data_sources"] = [dst_data_source_dict]

        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(len(document_model.data_items), 3)
            computation = document_model.get_data_item_computation(document_model.data_items[2])
            self.assertEqual(computation.processing_id, "cross-correlate")
            self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.crosscorrelate(src1.cropped_display_xdata, src2.cropped_display_xdata)"))
            self.assertEqual(len(computation.variables), 2)
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.data_item, document_model.data_items[0])
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[0].variable_specifier, computation.variables[0].secondary_specifier).value.graphic, document_model.data_items[0].displays[0].graphics[0])
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[1].variable_specifier, computation.variables[1].secondary_specifier).value.data_item, document_model.data_items[1])
            self.assertEqual(document_model.resolve_object_specifier(computation.variables[1].variable_specifier, computation.variables[1].secondary_specifier).value.graphic, document_model.data_items[1].displays[0].graphics[0])
            self.assertEqual(len(computation.variables), 2)
            data1 = numpy.arange(64).reshape((8, 8))
            document_model.data_items[0].set_data(data1)
            data2 = numpy.arange(64).reshape((8, 8))
            document_model.data_items[1].set_data(data2)
            self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
            self.assertIsNone(computation.error_text)
            for data_item in document_model.data_items:
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v11_to_v12_line_profile_migration(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()

        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_uuid_str = str(uuid.uuid4())
        src_data_item_dict["uuid"] = src_uuid_str
        src_data_item_dict["version"] = 11
        src_data_source_dict = dict()
        src_data_source_dict["uuid"] = str(uuid.uuid4())
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        graphic_uuid_str = str(uuid.uuid4())
        src_data_item_dict["displays"] = [{"uuid": str(uuid.uuid4()), "graphics": [{"type": "line-profile-graphic", "uuid": graphic_uuid_str, "start": (0, 0), "end": (1, 1)}]}]
        src_data_item_dict["data_source"] = src_data_source_dict

        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 11
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        display_uuid_str = str(uuid.uuid4())
        dst_data_item_dict["displays"] = [{"uuid": display_uuid_str}]
        computation_dict = dict()
        computation_dict["processing_id"] = "line-profile"
        computation_dict["uuid"] = str(uuid.uuid4())
        variables_list = computation_dict.setdefault("variables", list())
        variables_list.append({"name": "src", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "data_item", "version": 1, "uuid": src_uuid_str}})
        variables_list.append({"name": "line_region", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "region", "version": 1, "uuid": graphic_uuid_str}})
        dst_data_item_dict["computation"] = computation_dict
        connection_dict = {"type": "interval-list-connection", "source_uuid": display_uuid_str, "target_uuid": graphic_uuid_str, "uuid": str(uuid.uuid4())}
        dst_data_item_dict["connections"] = [connection_dict]
        dst_data_item_dict["data_source"] = dst_data_source_dict

        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(1, len(document_model.connections))
            # ensure dependencies are correct
            self.assertEqual(1, len(document_model.get_dependent_data_items(document_model.data_items[0])))
            self.assertEqual(document_model.get_dependent_data_items(document_model.data_items[0])[0], document_model.data_items[1])
            # finally cascade delete
            document_model.remove_data_item(document_model.data_items[0])
            self.assertEqual(0, len(document_model.data_items))
            self.assertEqual(0, len(document_model.computations))
            self.assertEqual(0, len(document_model.connections))

    def test_data_items_v11_to_v12_pick_migration(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()

        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_uuid_str = str(uuid.uuid4())
        src_data_item_dict["uuid"] = src_uuid_str
        src_data_item_dict["version"] = 11
        src_data_source_dict = dict()
        src_data_source_dict["uuid"] = str(uuid.uuid4())
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8, 8)
        point_graphic_uuid_str = str(uuid.uuid4())
        src_display_uuid_str = str(uuid.uuid4())
        src_data_item_dict["displays"] = [{"uuid": src_display_uuid_str, "graphics": [{"type": "point-graphic", "uuid": point_graphic_uuid_str, "start": (0, 0), "end": (1, 1)}]}]
        src_data_item_dict["data_source"] = src_data_source_dict

        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 11
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        dst_display_uuid_str = str(uuid.uuid4())
        interval_graphic_uuid_str = str(uuid.uuid4())
        dst_data_item_dict["displays"] = [{"uuid": dst_display_uuid_str, "graphics": [{"type": "interval-graphic", "uuid": interval_graphic_uuid_str, "start": 0, "end": 1}]}]
        computation_dict = dict()
        computation_dict["processing_id"] = "pick-point"
        computation_dict["uuid"] = str(uuid.uuid4())
        variables_list = computation_dict.setdefault("variables", list())
        variables_list.append({"name": "src", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "data_item", "version": 1, "uuid": src_uuid_str}})
        variables_list.append({"name": "pick_region", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "region", "version": 1, "uuid": point_graphic_uuid_str}})
        dst_data_item_dict["computation"] = computation_dict
        connection_dict = {"type": "property-connection",
                           "source_uuid": src_display_uuid_str, "source_property": "slice_interval",
                           "target_uuid": interval_graphic_uuid_str, "target_property": "interval",
                           "uuid": str(uuid.uuid4())}
        dst_data_item_dict["connections"] = [connection_dict]
        dst_data_item_dict["data_source"] = dst_data_source_dict

        # read it back
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, log_migrations=False)
        with contextlib.closing(document_model):
            # check metadata transferred to data source
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(document_model.computations))
            self.assertEqual(1, len(document_model.connections))
            # ensure dependencies are correct
            self.assertEqual(1, len(document_model.get_dependent_data_items(document_model.data_items[0])))
            self.assertEqual(document_model.get_dependent_data_items(document_model.data_items[0])[0], document_model.data_items[1])
            # finally cascade delete
            document_model.remove_data_item(document_model.data_items[0])
            self.assertEqual(0, len(document_model.data_items))
            self.assertEqual(0, len(document_model.computations))
            self.assertEqual(0, len(document_model.connections))

    def test_data_items_v11_to_v12_computation_reloads_without_duplicating_computation(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()

        src_data_item_dict = memory_persistent_storage_system.properties.setdefault("A", dict())
        src_uuid_str = str(uuid.uuid4())
        src_data_item_dict["uuid"] = src_uuid_str
        src_data_item_dict["version"] = 11
        src_data_source_dict = dict()
        src_data_source_dict["uuid"] = str(uuid.uuid4())
        src_data_source_dict["type"] = "buffered-data-source"
        src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
        src_data_source_dict["data_shape"] = (8, 8)
        graphic_uuid_str = str(uuid.uuid4())
        src_data_item_dict["displays"] = [{"uuid": str(uuid.uuid4()), "graphics": [{"type": "line-profile-graphic", "uuid": graphic_uuid_str, "start": (0, 0), "end": (1, 1)}]}]
        src_data_item_dict["data_source"] = src_data_source_dict

        dst_data_item_dict = memory_persistent_storage_system.properties.setdefault("B", dict())
        dst_data_item_dict["uuid"] = str(uuid.uuid4())
        dst_data_item_dict["version"] = 11
        dst_data_source_dict = dict()
        dst_data_source_dict["uuid"] = str(uuid.uuid4())
        dst_data_source_dict["type"] = "buffered-data-source"
        display_uuid_str = str(uuid.uuid4())
        dst_data_item_dict["displays"] = [{"uuid": display_uuid_str}]
        computation_dict = dict()
        computation_dict["processing_id"] = "line-profile"
        computation_dict["uuid"] = str(uuid.uuid4())
        variables_list = computation_dict.setdefault("variables", list())
        variables_list.append({"name": "src", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "data_item", "version": 1, "uuid": src_uuid_str}})
        variables_list.append({"name": "line_region", "type": "variable", "uuid": str(uuid.uuid4()), "specifier": {"type": "region", "version": 1, "uuid": graphic_uuid_str}})
        dst_data_item_dict["computation"] = computation_dict
        connection_dict = {"type": "interval-list-connection", "source_uuid": display_uuid_str, "target_uuid": graphic_uuid_str, "uuid": str(uuid.uuid4())}
        dst_data_item_dict["connections"] = [connection_dict]
        dst_data_item_dict["data_source"] = dst_data_source_dict

        memory_persistent_storage_system2 = DocumentModel.MemoryStorageSystem()
        memory_persistent_storage_system2.properties = copy.deepcopy(memory_persistent_storage_system.properties)

        auto_migration = DocumentModel.AutoMigration(log_copying=False, storage_system=memory_persistent_storage_system2)

        # make sure it reloads twice
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, auto_migrations=[auto_migration], library_storage=library_storage, log_migrations=False)
        with contextlib.closing(document_model):
            self.assertEqual(1, len(document_model.computations))

    def test_migrate_overwrites_old_data(self):
        current_working_directory = os.getcwd()
        library_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(library_dir)
        try:
            # construct workspace with old file
            library_filename = "Nion Swift Workspace.nslib"
            library_path = os.path.join(library_dir, library_filename)
            data_path = os.path.join(library_dir, "Nion Swift Data")
            with open(library_path, "w") as fp:
                json.dump({}, fp)
            data_item_dict = dict()
            data_item_dict["uuid"] = str(uuid.uuid4())
            data_item_dict["version"] = 9
            data_source_dict = dict()
            src_uuid_str = str(uuid.uuid4())
            data_source_dict["uuid"] = src_uuid_str
            data_source_dict["type"] = "buffered-data-source"
            data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_source_dict["data_shape"] = (8, 8)
            data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
            data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
            data_item_dict["data_sources"] = [data_source_dict]
            file_handler = DocumentModel.FileStorageSystem._file_handlers[0]
            file_path = pathlib.PurePath(data_path, "File").with_suffix(file_handler.get_extension())
            handler = file_handler(file_path)
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())

            # read workspace
            file_persistent_storage_system = DocumentModel.FileStorageSystem([data_path])
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, log_migrations=False, ignore_older_files=False)
            document_model.close()

            # verify
            handler = DocumentModel.FileStorageSystem._file_handlers[0](file_path)
            with contextlib.closing(handler):
                new_data_item_dict = handler.read_properties()
                self.assertEqual(new_data_item_dict["uuid"], data_item_dict["uuid"])
                self.assertEqual(new_data_item_dict["version"], DataItem.DataItem.writer_version)
        finally:
            #logging.debug("rmtree %s", library_dir)
            shutil.rmtree(library_dir)

    def test_ignore_migrate_does_not_overwrite_old_data(self):
        current_working_directory = os.getcwd()
        library_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(library_dir)
        try:
            # construct workspace with old file
            library_filename = "Nion Swift Workspace.nslib"
            library_path = os.path.join(library_dir, library_filename)
            data_path = os.path.join(library_dir, "Nion Swift Data")
            with open(library_path, "w") as fp:
                json.dump({}, fp)
            data_item_dict = dict()
            data_item_dict["uuid"] = str(uuid.uuid4())
            data_item_dict["version"] = 9
            data_source_dict = dict()
            src_uuid_str = str(uuid.uuid4())
            data_source_dict["uuid"] = src_uuid_str
            data_source_dict["type"] = "buffered-data-source"
            data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_source_dict["data_shape"] = (8, 8)
            data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
            data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
            data_item_dict["data_sources"] = [data_source_dict]
            file_handler = DocumentModel.FileStorageSystem._file_handlers[0]
            file_path = pathlib.PurePath(data_path, "File").with_suffix(file_handler.get_extension())
            handler = file_handler(file_path)
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())

            # read workspace
            file_persistent_storage_system = DocumentModel.FileStorageSystem([data_path])
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, ignore_older_files=True)
            document_model.close()

            # verify
            handler = DocumentModel.FileStorageSystem._file_handlers[0](file_path)
            with contextlib.closing(handler):
                new_data_item_dict = handler.read_properties()
                self.assertEqual(new_data_item_dict["uuid"], data_item_dict["uuid"])
                self.assertEqual(new_data_item_dict["version"], data_item_dict["version"])
        finally:
            #logging.debug("rmtree %s", library_dir)
            shutil.rmtree(library_dir)

    def test_auto_migrate_copies_old_data_to_new_library(self):
        current_working_directory = os.getcwd()
        library_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(library_dir)
        try:
            # construct workspace with old file
            library_filename = "Nion Swift Workspace.nslib"
            library_path = os.path.join(library_dir, library_filename)
            old_data_path = os.path.join(library_dir, "Nion Swift Data")
            with open(library_path, "w") as fp:
                json.dump({}, fp)
            data_item_dict = dict()
            data_item_dict["uuid"] = str(uuid.uuid4())
            data_item_dict["version"] = 9
            data_source_dict = dict()
            src_uuid_str = str(uuid.uuid4())
            data_source_dict["uuid"] = src_uuid_str
            data_source_dict["type"] = "buffered-data-source"
            data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_source_dict["data_shape"] = (8, 8)
            data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
            data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
            data_item_dict["data_sources"] = [data_source_dict]
            file_handler = DocumentModel.FileStorageSystem._file_handlers[0]
            handler = file_handler(pathlib.PurePath(old_data_path, "File").with_suffix(file_handler.get_extension()))
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())

            # auto migrate workspace
            data_path = os.path.join(library_dir, "Nion Swift Data {version}".format(version=DataItem.DataItem.writer_version))
            file_persistent_storage_system = DocumentModel.FileStorageSystem([data_path])
            auto_migration = DocumentModel.AutoMigration([old_data_path], log_copying=False)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, auto_migrations=[auto_migration])
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)
                self.assertEqual(document_model.data_items[0].uuid, uuid.UUID(data_item_dict["uuid"]))
                # double check correct persistent storage context
                document_model.remove_data_item(document_model.data_items[0])

        finally:
            #logging.debug("rmtree %s", library_dir)
            shutil.rmtree(library_dir)

    def test_auto_migrate_only_copies_old_data_to_new_library_once_per_uuid(self):
        current_working_directory = os.getcwd()
        library_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(library_dir)
        try:
            # construct workspace with old file
            library_filename = "Nion Swift Workspace.nslib"
            library_path = os.path.join(library_dir, library_filename)
            old_data_path = os.path.join(library_dir, "Nion Swift Data")
            with open(library_path, "w") as fp:
                json.dump({}, fp)
            data_item_dict = dict()
            data_item_dict["uuid"] = str(uuid.uuid4())
            data_item_dict["version"] = 9
            data_source_dict = dict()
            src_uuid_str = str(uuid.uuid4())
            data_source_dict["uuid"] = src_uuid_str
            data_source_dict["type"] = "buffered-data-source"
            data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_source_dict["data_shape"] = (8, 8)
            data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
            data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
            data_item_dict["data_sources"] = [data_source_dict]
            file_handler = DocumentModel.FileStorageSystem._file_handlers[0]
            handler = file_handler(pathlib.PurePath(old_data_path, "File").with_suffix(file_handler.get_extension()))
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())

            # auto migrate workspace
            data_path = os.path.join(library_dir, "Nion Swift Data {version}".format(version=DataItem.DataItem.writer_version))
            file_persistent_storage_system = DocumentModel.FileStorageSystem([data_path])
            auto_migration1 = DocumentModel.AutoMigration([old_data_path], log_copying=False)
            auto_migration2 = DocumentModel.AutoMigration([old_data_path], log_copying=False)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, auto_migrations=[auto_migration1, auto_migration2])
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)
                self.assertEqual(document_model.data_items[0].uuid, uuid.UUID(data_item_dict["uuid"]))

        finally:
            #logging.debug("rmtree %s", library_dir)
            shutil.rmtree(library_dir)

    def test_auto_migrate_skips_migrated_and_deleted_library_items(self):
        current_working_directory = os.getcwd()
        library_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(library_dir)
        try:
            # construct workspace with old file
            library_filename = "Nion Swift Workspace.nslib"
            library_path = os.path.join(library_dir, library_filename)
            old_data_path = os.path.join(library_dir, "Nion Swift Data")
            with open(library_path, "w") as fp:
                json.dump({}, fp)
            src_uuid_str = str(uuid.uuid4())
            data_item_dict = dict()
            data_item_dict["uuid"] = src_uuid_str
            data_item_dict["version"] = 9
            data_source_dict = dict()
            data_source_dict["uuid"] = str(uuid.uuid4())
            data_source_dict["type"] = "buffered-data-source"
            data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_source_dict["data_shape"] = (8, 8)
            data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
            data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
            data_item_dict["data_sources"] = [data_source_dict]
            file_handler = DocumentModel.FileStorageSystem._file_handlers[0]
            handler = file_handler(pathlib.PurePath(old_data_path, "File").with_suffix(file_handler.get_extension()))
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            library_storage = DocumentModel.FilePersistentStorage()
            library_storage._set_properties({"data_item_deletions": [src_uuid_str, str(uuid.uuid4())]})

            # auto migrate workspace
            data_path = os.path.join(library_dir, "Nion Swift Data {version}".format(version=DataItem.DataItem.writer_version))
            file_persistent_storage_system = DocumentModel.FileStorageSystem([data_path])
            auto_migration = DocumentModel.AutoMigration([old_data_path], log_copying=False)
            document_model = DocumentModel.DocumentModel(library_storage=library_storage, persistent_storage_system=file_persistent_storage_system, auto_migrations=[auto_migration])
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 0)
                self.assertTrue(uuid.UUID(src_uuid_str) in document_model.data_item_deletions)
                self.assertEqual(len(document_model.data_item_deletions), 1)
                self.assertEqual(len(file_persistent_storage_system.find_data_items()), 0)

        finally:
            #logging.debug("rmtree %s", library_dir)
            shutil.rmtree(library_dir)

    def test_auto_migrate_connects_data_references_in_migrated_data(self):
        current_working_directory = os.getcwd()
        library_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(library_dir)
        try:
            # construct workspace with old file
            library_filename = "Nion Swift Workspace.nslib"
            library_path = os.path.join(library_dir, library_filename)
            old_data_path = os.path.join(library_dir, "Nion Swift Data")
            with open(library_path, "w") as fp:
                json.dump({}, fp)
            src_uuid_str = str(uuid.uuid4())
            data_item_dict = dict()
            data_item_dict["uuid"] = src_uuid_str
            data_item_dict["version"] = 9
            data_source_dict = dict()
            data_source_dict["uuid"] = str(uuid.uuid4())
            data_source_dict["type"] = "buffered-data-source"
            data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_source_dict["data_shape"] = (8, 8)
            data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
            data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
            data_item_dict["data_sources"] = [data_source_dict]
            file_handler = DocumentModel.FileStorageSystem._file_handlers[0]
            handler = file_handler(pathlib.PurePath(old_data_path, "File").with_suffix(file_handler.get_extension()))
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            library_storage = DocumentModel.FilePersistentStorage()
            library_storage._set_properties({"data_item_references": {"key": src_uuid_str}})

            # auto migrate workspace
            data_path = os.path.join(library_dir, "Nion Swift Data {version}".format(version=DataItem.DataItem.writer_version))
            file_persistent_storage_system = DocumentModel.FileStorageSystem([data_path])
            auto_migration = DocumentModel.AutoMigration([old_data_path], log_copying=False)
            document_model = DocumentModel.DocumentModel(library_storage=library_storage, persistent_storage_system=file_persistent_storage_system, auto_migrations=[auto_migration])
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)
                self.assertEqual(document_model.get_data_item_reference("key").data_item, document_model.data_items[0])

        finally:
            #logging.debug("rmtree %s", library_dir)
            shutil.rmtree(library_dir)

    def test_data_item_with_connected_crop_region_should_not_update_modification_when_loading(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            crop_region = Graphics.RectangleGraphic()
            data_item.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            data_item_cropped = document_model.get_crop_new(data_item, crop_region)
            document_model.recompute_all()
            data_item._set_modified(modified)
            data_item_cropped._set_modified(modified)
            self.assertEqual(document_model.data_items[0].modified, modified)
            self.assertEqual(document_model.data_items[1].modified, modified)
        # make sure it reloads without changing modification
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            self.assertEqual(document_model.data_items[0].modified, modified)
            self.assertEqual(document_model.data_items[1].modified, modified)
            document_model.recompute_all()  # try recomputing too
            self.assertEqual(document_model.data_items[0].modified, modified)
            self.assertEqual(document_model.data_items[1].modified, modified)

    def test_auto_migrate_handles_secondary_storage_types(self):
        current_working_directory = os.getcwd()
        library_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(library_dir)
        try:
            # construct workspace with old file
            library_filename = "Nion Swift Workspace.nslib"
            library_path = os.path.join(library_dir, library_filename)
            old_data_path = os.path.join(library_dir, "Nion Swift Data")
            with open(library_path, "w") as fp:
                json.dump({}, fp)
            src_uuid_str = str(uuid.uuid4())
            data_item_dict = dict()
            data_item_dict["uuid"] = src_uuid_str
            data_item_dict["version"] = 9
            data_source_dict = dict()
            data_source_dict["uuid"] = str(uuid.uuid4())
            data_source_dict["type"] = "buffered-data-source"
            data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_source_dict["data_shape"] = (8, 8)
            data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
            data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
            data_item_dict["data_sources"] = [data_source_dict]
            file_handler = DocumentModel.FileStorageSystem._file_handlers[1]  # HDF5
            handler = file_handler(pathlib.PurePath(old_data_path, "File").with_suffix(file_handler.get_extension()))
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            library_storage = DocumentModel.FilePersistentStorage()

            # auto migrate workspace
            data_path = os.path.join(library_dir, "Nion Swift Data {version}".format(version=DataItem.DataItem.writer_version))
            file_persistent_storage_system = DocumentModel.FileStorageSystem([data_path])
            auto_migration = DocumentModel.AutoMigration([old_data_path], log_copying=False)
            document_model = DocumentModel.DocumentModel(library_storage=library_storage, persistent_storage_system=file_persistent_storage_system, auto_migrations=[auto_migration])
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)

            # ensure it imports twice
            data_path = os.path.join(library_dir, "Nion Swift Data {version}".format(version=DataItem.DataItem.writer_version))
            file_persistent_storage_system = DocumentModel.FileStorageSystem([data_path])
            auto_migration = DocumentModel.AutoMigration([old_data_path], log_copying=False)
            document_model = DocumentModel.DocumentModel(library_storage=library_storage, persistent_storage_system=file_persistent_storage_system, auto_migrations=[auto_migration])
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)

        finally:
            #logging.debug("rmtree %s", library_dir)
            shutil.rmtree(library_dir)

    @unittest.expectedFailure
    def test_storage_cache_disabled_during_transaction(self):
        storage_cache = Cache.DictStorageCache()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, storage_cache=storage_cache)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            data_item.displays[0].get_calculated_display_values(True).data_range  # trigger storage
            cached_data_range = storage_cache.cache[data_item.displays[0].uuid]["data_range"]
            self.assertEqual(cached_data_range, (1, 1))
            self.assertEqual(data_item.displays[0].get_calculated_display_values(True).data_range, (1, 1))
            with document_model.data_item_transaction(data_item):
                data_item.set_data(numpy.zeros((16, 16), numpy.uint32))
                self.assertEqual(data_item.displays[0].get_calculated_display_values(True).data_range, (0, 0))
                self.assertEqual(cached_data_range, storage_cache.cache[data_item.displays[0].uuid]["data_range"])
                self.assertEqual(cached_data_range, (1, 1))
            self.assertEqual(storage_cache.cache[data_item.displays[0].uuid]["data_range"], (0, 0))

    def test_suspendable_storage_cache_caches_removes(self):
        data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
        storage_cache = Cache.DictStorageCache()
        suspendable_storage_cache = Cache.SuspendableCache(storage_cache)
        suspendable_storage_cache.set_cached_value(data_item, "key", 1.0)
        self.assertEqual(storage_cache.cache[data_item.uuid]["key"], 1.0)
        suspendable_storage_cache.suspend_cache()
        suspendable_storage_cache.remove_cached_value(data_item, "key")
        self.assertEqual(storage_cache.cache[data_item.uuid]["key"], 1.0)
        suspendable_storage_cache.spill_cache()
        self.assertIsNone(storage_cache.cache.get(data_item.uuid, dict()).get("key"))

    def test_suspendable_storage_cache_is_null_for_add_followed_by_remove(self):
        data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
        storage_cache = Cache.DictStorageCache()
        suspendable_storage_cache = Cache.SuspendableCache(storage_cache)
        suspendable_storage_cache.suspend_cache()
        suspendable_storage_cache.set_cached_value(data_item, "key", 1.0)
        suspendable_storage_cache.remove_cached_value(data_item, "key")
        suspendable_storage_cache.spill_cache()
        self.assertIsNone(storage_cache.cache.get(data_item.uuid, dict()).get("key"))

    def test_writing_properties_with_numpy_float32_succeeds(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        try:
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                data_item.displays[0].display_limits = (numpy.float32(1.0), numpy.float32(1.0))
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_data_structure_reloads_basic_value_types(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_structure = document_model.create_data_structure(structure_type="nada")
            data_structure.set_property_value("title", "Title")
            data_structure.set_property_value("width", 8.5)
            document_model.append_data_structure(data_structure)
            data_structure.set_property_value("interval", (0.5, 0.2))
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            self.assertEqual(len(document_model.data_structures), 1)
            self.assertEqual(document_model.data_structures[0].get_property_value("title"), "Title")
            self.assertEqual(document_model.data_structures[0].get_property_value("width"), 8.5)
            self.assertEqual(document_model.data_structures[0].get_property_value("interval"), (0.5, 0.2))
            self.assertEqual(document_model.data_structures[0].structure_type, "nada")

    def test_attached_data_structure_reconnects_after_reload(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            document_model.append_data_item(data_item)
            data_structure = document_model.create_data_structure()
            data_structure.set_property_value("title", "Title")
            document_model.append_data_structure(data_structure)
            document_model.attach_data_structure(data_structure, data_item)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            self.assertEqual(len(document_model.data_structures), 1)
            self.assertEqual(document_model.data_structures[0].source, document_model.data_items[0])
            document_model.remove_data_item(document_model.data_items[0])
            self.assertEqual(len(document_model.data_structures), 0)

    def test_connected_data_structure_reconnects_after_reload(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            data_struct1 = document_model.create_data_structure()
            data_struct2 = document_model.create_data_structure()
            data_struct1.set_property_value("title", "t1")
            data_struct2.set_property_value("title", "t2")
            document_model.append_data_structure(data_struct1)
            document_model.append_data_structure(data_struct2)
            connection = Connection.PropertyConnection(data_struct1, "title", data_struct2, "title", parent=data_item)
            document_model.append_connection(connection)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_struct1 = document_model.data_structures[0]
            data_struct2 = document_model.data_structures[1]
            data_struct1.set_property_value("title", "T1")
            self.assertEqual("T1", data_struct1.get_property_value("title"))
            self.assertEqual("T1", data_struct2.get_property_value("title"))
            data_struct2.set_property_value("title", "T2")
            self.assertEqual("T2", data_struct1.get_property_value("title"))
            self.assertEqual("T2", data_struct2.get_property_value("title"))

    def test_data_structure_references_reconnect_after_reload(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            data_struct = document_model.create_data_structure()
            data_struct.set_referenced_object("master", data_item)
            document_model.append_data_structure(data_struct)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            self.assertEqual(document_model.data_items[0], document_model.data_structures[0].get_referenced_object("master"))

    def test_data_structure_reloads_after_computation(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item)
            data_struct = document_model.create_data_structure()
            data_struct.set_referenced_object("master", data_item)
            document_model.append_data_structure(data_struct)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_object("a", document_model.get_object_specifier(data_item))
            computed_data_item = DataItem.DataItem()
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(1, len(document_model.data_structures))
            self.assertEqual(1, len(document_model.computations))

    def test_library_item_sources_reconnect_after_reload(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item3 = DataItem.DataItem(numpy.zeros((2, 2)))
            data_item1.source = data_item2
            data_item3.source = data_item2
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.append_data_item(data_item3)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            self.assertEqual(3, len(document_model.data_items))
            document_model.remove_data_item(document_model.data_items[1])
            self.assertEqual(0, len(document_model.data_items))

    def test_computation_reconnects_after_reload(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_object("a", document_model.get_object_specifier(data_item))
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            assert numpy.array_equal(-document_model.data_items[0].data, document_model.data_items[1].data)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            read_computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertIsNotNone(read_computation)
            with document_model.data_items[0].data_ref() as data_ref:
                data_ref.data += 1.5
            document_model.recompute_all()
            assert numpy.array_equal(-document_model.data_items[0].data, document_model.data_items[1].data)

    def test_computation_does_not_recompute_on_reload(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
            computation.create_object("a", document_model.get_object_specifier(data_item))
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            assert numpy.array_equal(-document_model.data_items[0].data, document_model.data_items[1].data)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            changed_ref = [False]
            def changed():
                changed_ref[0] = True
            changed_event_listener = document_model.data_items[1].data_item_changed_event.listen(changed)
            with contextlib.closing(changed_event_listener):
                document_model.recompute_all()
                assert numpy.array_equal(-document_model.data_items[0].data, document_model.data_items[1].data)
                self.assertFalse(changed_ref[0])

    def test_computation_with_optional_none_parameters_reloads(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data = numpy.ones((2, 2), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("xd.column(a.xdata)"))
            computation.create_object("a", document_model.get_object_specifier(data_item))
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            read_computation = document_model.get_data_item_computation(document_model.data_items[1])
            with document_model.data_items[0].data_ref() as data_ref:
                data_ref.data += 1.5
            document_model.recompute_all()

    def test_computation_slice_reloads(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data = numpy.ones((8, 4, 4), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata[2:4, :, :] + a.xdata[5]"))
            computation.create_object("a", document_model.get_object_specifier(data_item))
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all()
            data_shape = computed_data_item.data_shape
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            computed_data_item = document_model.data_items[1]
            with document_model.data_items[0].data_ref() as data_ref:
                data_ref.data += 1.5
            document_model.recompute_all()
            self.assertEqual(data_shape, computed_data_item.data_shape)

    def test_computation_pick_and_display_interval_reloads(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data = numpy.ones((8, 4, 4), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            document_model.get_pick_new(data_item)
            document_model.recompute_all()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            self.assertEqual(len(document_model.data_items), 2)

    def test_computation_corrupt_variable_reloads(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data = numpy.ones((8, 4, 4), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata"))
            computation.create_object("a", document_model.get_object_specifier(data_item))
            x = computation.create_variable("x")  # value is intentionally None
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            x.value_type = "integral"
            x.value = 6
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            read_computation = document_model.get_data_item_computation(document_model.data_items[1])
            self.assertEqual(read_computation.variables[1].name, "x")
            self.assertEqual(read_computation.variables[1].value, 6)

    def test_computation_missing_variable_reloads(self):
        library_storage = DocumentModel.MemoryPersistentStorage()
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data = numpy.ones((8, 4, 4), numpy.double)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x + y"))
            computation.create_object("a", document_model.get_object_specifier(data_item))
            computation.create_variable("x", value_type="integral", value=3)
            computation.create_variable("y", value_type="integral", value=4)
            computed_data_item = DataItem.DataItem(data.copy())
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
        library_storage_properties = library_storage.properties
        del library_storage_properties["computations"][0]["variables"][0]
        library_storage_properties["computations"][0]["variables"][0]["uuid"] = str(uuid.uuid4())
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=DocumentModel.MemoryPersistentStorage(library_storage_properties))
        document_model.close()

    computation1_eval_count = 0

    class Computation1:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src):
            TestStorageClass.computation1_eval_count += 1
            self.__xdata = -src.xdata

        def commit(self):
            dst = self.computation.get_result("dst")
            dst.xdata = self.__xdata

    def test_library_computation_reconnects_after_reload(self):
        TestStorageClass.computation1_eval_count = 0
        Symbolic.register_computation_type("computation1", self.Computation1)
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            document_model.append_data_item(data_item)
            dst_data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(dst_data_item)
            computation = document_model.create_computation()
            computation.processing_id = "computation1"
            computation.create_object("src", document_model.get_object_specifier(data_item))
            computation.create_result("dst", document_model.get_object_specifier(dst_data_item, "data_item"))
            document_model.append_computation(computation)
            document_model.recompute_all()
            assert numpy.array_equal(-document_model.data_items[0].data, document_model.data_items[1].data)
            self.assertEqual(len(document_model.computations), 1)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            self.assertEqual(len(document_model.computations), 1)
            document_model.data_items[0].set_data(numpy.random.randn(3, 3))
            document_model.recompute_all()
            self.assertEqual(document_model.data_items[0].data.shape, (3, 3))
            self.assertTrue(numpy.array_equal(-document_model.data_items[0].data, document_model.data_items[1].data))

    def test_library_computation_listens_to_changes_after_reload(self):
        TestStorageClass.computation1_eval_count = 0
        Symbolic.register_computation_type("computation1", self.Computation1)
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            document_model.append_data_item(data_item)
            dst_data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(dst_data_item)
            computation = document_model.create_computation()
            computation.processing_id = "computation1"
            computation.create_object("src", document_model.get_object_specifier(data_item))
            computation.create_result("dst", document_model.get_object_specifier(dst_data_item, "data_item"))
            document_model.append_computation(computation)
            document_model.recompute_all()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = document_model.data_items[0]
            dst_data_item = document_model.data_items[1]
            self.assertEqual(len(document_model.data_items), 2)
            self.assertEqual(document_model.get_dependent_data_items(data_item)[0], dst_data_item)
            new_data_item = DataItem.DataItem(numpy.ones((2, 2)))
            document_model.append_data_item(new_data_item)
            document_model.computations[0].variables[0].specifier = document_model.get_object_specifier(new_data_item)
            self.assertEqual(document_model.get_dependent_data_items(new_data_item)[0], dst_data_item)

    def test_library_computation_does_not_evaluate_with_missing_inputs(self):
        TestStorageClass.computation1_eval_count = 0
        Symbolic.register_computation_type("computation1", self.Computation1)
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        library_storage = DocumentModel.MemoryPersistentStorage()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            document_model.append_data_item(data_item)
            dst_data_item = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(dst_data_item)
            computation = document_model.create_computation()
            computation.processing_id = "computation1"
            computation.create_object("src", document_model.get_object_specifier(data_item))
            computation.create_result("dst", document_model.get_object_specifier(dst_data_item, "data_item"))
            document_model.append_computation(computation)
            document_model.recompute_all()
        library_storage_properties = library_storage.properties
        library_storage_properties["computations"][0]["variables"][0]["specifier"]["uuid"] = str(uuid.uuid4())
        library_storage._set_properties(library_storage_properties)
        self.computation1_eval_count = 0
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system, library_storage=library_storage)
        with contextlib.closing(document_model):
            document_model.data_items[0].set_data(numpy.random.randn(3, 3))
            document_model.recompute_all()
            self.assertEqual(self.computation1_eval_count, 0)

    def test_data_item_with_references_to_another_data_item_reloads(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item0 = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item0)
            composite_item = DataItem.CompositeLibraryItem()
            composite_item.append_data_item(data_item0)
            document_model.append_data_item(composite_item)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            self.assertEqual(len(document_model.data_items), 2)
            self.assertEqual(len(document_model.data_items[1].data_items), 1)
            self.assertEqual(document_model.data_items[1].data_items[0], document_model.data_items[0])

    def test_composite_library_item_reloads_metadata(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item0 = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item0)
            composite_item = DataItem.CompositeLibraryItem()
            composite_item.append_data_item(data_item0)
            composite_item.metadata = {"abc": 1}
            document_model.append_data_item(composite_item)
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            self.assertEqual(len(document_model.data_items), 2)
            self.assertEqual(len(document_model.data_items[1].data_items), 1)
            self.assertEqual(document_model.data_items[1].data_items[0], document_model.data_items[0])
            self.assertEqual(document_model.data_items[1].metadata, {"abc": 1})

    def test_composite_data_item_saves_to_file_storage(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        try:
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage)
            with contextlib.closing(document_model):
                data_item0 = DataItem.DataItem(numpy.zeros((8, 8)))
                document_model.append_data_item(data_item0)
                composite_item = DataItem.CompositeLibraryItem()
                composite_item.append_data_item(data_item0)
                document_model.append_data_item(composite_item)
            # read it back
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage, log_migrations=False)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 2)
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_data_item_with_corrupt_created_still_loads(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            src_data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(src_data_item)
        memory_persistent_storage_system.properties[str(src_data_item.uuid)]["created"] = "todaytodaytodaytodaytoday0"
        memory_persistent_storage_system.properties[str(src_data_item.uuid)]["data_source"]["created"] = "todaytodaytodaytodaytoday0"
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            # for corrupt/missing created dates, a new one matching todays date should be assigned
            self.assertIsNotNone(document_model.data_items[0].created)
            self.assertEqual(document_model.data_items[0].created.date(), datetime.datetime.now().date())

    def test_loading_library_with_two_copies_of_same_uuid_ignores_second_copy(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        try:
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                file_path = data_item._test_get_file_path()
            file_path_base, file_path_ext = os.path.splitext(file_path)
            shutil.copyfile(file_path, file_path_base + "_" + file_path_ext)
            # read it back
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage, log_migrations=False)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_snapshot_copies_storage_format(self):
        current_working_directory = os.getcwd()
        workspace_dir = os.path.join(current_working_directory, "__Test")
        Cache.db_make_directory_if_needed(workspace_dir)
        file_persistent_storage_system = DocumentModel.FileStorageSystem([workspace_dir])
        lib_name = os.path.join(workspace_dir, "Data.nslib")
        try:
            library_storage = DocumentModel.FilePersistentStorage(lib_name)
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage)
            with contextlib.closing(document_model):
                data_item1 = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                data_item2 = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                data_item2.large_format = True
                document_model.append_data_item(data_item1)
                document_model.append_data_item(data_item2)
            # read it back
            document_model = DocumentModel.DocumentModel(persistent_storage_system=file_persistent_storage_system, library_storage=library_storage, log_migrations=False)
            with contextlib.closing(document_model):
                data_item1 = document_model.data_items[0]
                data_item2 = document_model.data_items[1]
                data_item1a = document_model.get_snapshot_new(data_item1)
                data_item2a = document_model.get_snapshot_new(data_item2)
                data_item1b = copy.deepcopy(data_item1)
                data_item2b = copy.deepcopy(data_item2)
                document_model.append_data_item(data_item1b)
                document_model.append_data_item(data_item2b)
                file_path1 = data_item1._test_get_file_path()
                file_path2 = data_item2._test_get_file_path()
                file_path1a = data_item1a._test_get_file_path()
                file_path2a = data_item2a._test_get_file_path()
                file_path1b = data_item1b._test_get_file_path()
                file_path2b = data_item2b._test_get_file_path()
            file_path1_base, file_path1_ext = os.path.splitext(file_path1)
            file_path2_base, file_path2_ext = os.path.splitext(file_path2)
            file_path1a_base, file_path1a_ext = os.path.splitext(file_path1a)
            file_path2a_base, file_path2a_ext = os.path.splitext(file_path2a)
            file_path1b_base, file_path1b_ext = os.path.splitext(file_path1b)
            file_path2b_base, file_path2b_ext = os.path.splitext(file_path2b)
            # check assumptions
            self.assertNotEqual(file_path1_ext, file_path2_ext)
            # check results
            self.assertEqual(file_path1_ext, file_path1a_ext)
            self.assertEqual(file_path2_ext, file_path2a_ext)
            self.assertEqual(file_path1_ext, file_path1b_ext)
            self.assertEqual(file_path2_ext, file_path2b_ext)
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace_dir)

    def test_deleted_data_item_updates_into_deleted_list_and_clears_on_reload(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
            document_model.append_data_item(data_item)
            data_item_cropped = document_model.get_crop_new(data_item)
            document_model.recompute_all()
            self.assertEqual(len(document_model.data_items), 2)
            self.assertEqual(len(document_model.data_item_deletions), 0)
            document_model.remove_data_item(data_item)
            self.assertEqual(len(document_model.data_items), 0)
            self.assertEqual(len(document_model.data_item_deletions), 2)
        # make sure it reloads without changing modification
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            self.assertEqual(len(document_model.data_items), 0)
            self.assertEqual(len(document_model.data_item_deletions), 0)

    def disabled_test_document_controller_disposes_threads(self):
        thread_count = threading.activeCount()
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        document_controller.close()
        gc.collect()
        self.assertEqual(threading.activeCount(), thread_count)

    def disabled_test_document_controller_leaks_no_memory(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(data=numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)

    def disabled_test_document_model_leaks_no_memory(self):
        # numpy min/max leak memory, so make sure they're used before testing data item
        data = numpy.zeros((2000, 2000))
        data.min(), data.max()
        # test memory usage
        memory_start = memory_usage_resource()
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(data=data)
            document_model.append_data_item(data_item)
            data_item = None
        document_model = None
        gc.collect()
        memory_usage = memory_usage_resource() - memory_start
        print(memory_usage)
        self.assertTrue(memory_usage < 0.2)

    def disabled_test_data_item_leaks_no_memory(self):
        # numpy min/max leak memory, so make sure they're used before testing data item
        data = numpy.zeros((2000, 2000))
        data.min(), data.max()
        # test memory usage
        memory_start = memory_usage_resource()
        # data_item = DataItem.DataItem(data=data)
        # data_item.close()
        # data_item = None
        gc.collect()
        memory_usage = memory_usage_resource() - memory_start
        self.assertTrue(memory_usage < 0.2)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
