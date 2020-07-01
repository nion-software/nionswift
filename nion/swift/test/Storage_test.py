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
import typing
import unittest
import uuid

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift import ComputationPanel
from nion.swift import DisplayPanel
from nion.swift import DocumentController
from nion.swift import Facade
from nion.swift import Thumbnails
from nion.swift.model import Cache
from nion.swift.model import Connection
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import FileStorageSystem
from nion.swift.model import Graphics
from nion.swift.model import HDF5Handler
from nion.swift.model import NDataHandler
from nion.swift.model import Persistence
from nion.swift.model import Profile
from nion.swift.model import Symbolic
from nion.swift.test import TestContext
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


class TempProfileContext:

    def __init__(self, base_directory: pathlib.Path, no_remove: bool = False):
        self.workspace_dir = base_directory / "__Test"
        self.profiles_dir = base_directory / "__Test" / "Profiles"
        self.projects_dir = base_directory / "__Test" / "Projects"
        if self.workspace_dir.exists():
            shutil.rmtree(self.workspace_dir)
        Cache.db_make_directory_if_needed(self.workspace_dir)
        Cache.db_make_directory_if_needed(self.profiles_dir)
        Cache.db_make_directory_if_needed(self.projects_dir)
        self.__profile = None
        self.__no_remove = no_remove
        self.__items_to_close = list()

    def create_profile(self, *, profile_name: str = None, project_name: str = None, project_data_name: str = None) -> Profile.Profile:
        if not self.__profile:
            profile_path = self.profiles_dir / pathlib.Path(profile_name or "Profile").with_suffix(".nsprof")
            profile_json = json.dumps({"version": FileStorageSystem.PROFILE_VERSION, "uuid": str(uuid.uuid4())})
            profile_path.write_text(profile_json, "utf-8")
            project_path = self.projects_dir / pathlib.Path(project_name or "Project").with_suffix(".nsproj")
            project_uuid = uuid.uuid4()
            project_data_json = json.dumps({"version": FileStorageSystem.PROJECT_VERSION, "uuid": str(project_uuid), "project_data_folders": [project_data_name or "Data"]})
            project_path.write_text(project_data_json, "utf-8")
            storage_system = FileStorageSystem.FilePersistentStorageSystem(profile_path)
            storage_system.load_properties()
            storage_cache = Cache.DbStorageCache(self.profiles_dir / "ProfileCache.cache")
            profile = Profile.Profile(storage_system=storage_system, storage_cache=storage_cache)
            project_reference = profile.add_project_index(project_path)
            profile.work_project_reference_uuid = project_reference.uuid
            profile.target_project_reference_uuid = project_reference.uuid
            self.__profile = profile
            return profile
        else:
            profile_path = self.profiles_dir / pathlib.Path(profile_name or "Profile").with_suffix(".nsprof")
            storage_system = FileStorageSystem.FilePersistentStorageSystem(profile_path)
            storage_system.load_properties()
            storage_cache = Cache.DbStorageCache(self.profiles_dir / "ProfileCache.cache")
            profile = Profile.Profile(storage_system=storage_system, storage_cache=storage_cache)
            return profile

    def create_document_model(self, auto_close: bool = False, clear_work: bool = False, project_name: str = None, project_data_name: str = None) -> DocumentModel.DocumentModel:
        profile = self.create_profile(project_name=project_name, project_data_name=project_data_name)
        if clear_work:
            profile.work_project_reference_uuid = None
        document_model = DocumentModel.DocumentModel(profile=profile)
        if auto_close:
            self.__items_to_close.append(document_model)
        return document_model

    def create_document_controller(self, *, auto_close: bool = True) -> DocumentController.DocumentController:
        document_model = DocumentModel.DocumentModel(profile=self.create_profile())
        document_controller = DocumentController.DocumentController(TestUI.UserInterface(), document_model, workspace_id="library")
        if auto_close:
            self.__items_to_close.append(document_controller)
        return document_controller

    def reset_profile(self):
        self.__profile = None

    @property
    def _file_handlers(self):
        return FileStorageSystem.FileProjectStorageSystem._file_handlers

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        self.close()

    def close(self):
        for item in self.__items_to_close:
            item.close()
        self.__items_to_close = list()
        if self.__no_remove:
            import logging
            logging.debug("rmtree %s", self.workspace_dir)
        else:
            shutil.rmtree(self.workspace_dir)


def create_temp_profile_context(no_remove: bool = False) -> TempProfileContext:
    return TempProfileContext(pathlib.Path.cwd(), no_remove=no_remove)


def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


class TestStorageClass(unittest.TestCase):

    def setUp(self):
        NDataHandler.NDataHandler.count = 0
        HDF5Handler.HDF5Handler.count = 0
        Cache.DbStorageCache.count = 0
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)
        # self.__memory_start = memory_usage_resource()

    def tearDown(self):
        # gc.collect()
        # memory_usage = memory_usage_resource() - self.__memory_start
        # if memory_usage > 0.5:
        #     logging.debug("{} {}".format(self.id(), memory_usage))
        self.assertEqual(0, Cache.DbStorageCache.count)
        self.assertEqual(0, NDataHandler.NDataHandler.count)
        self.assertEqual(0, HDF5Handler.HDF5Handler.count)

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
        metadata = data_item.metadata
        metadata.setdefault("test", dict())["one"] = 1
        data_item.metadata = metadata
        document_controller.document_model.append_data_item(data_item)
        display_item = document_controller.document_model.get_display_item_for_data_item(data_item)
        display_item.add_graphic(Graphics.PointGraphic())
        display_item.add_graphic(Graphics.LineGraphic())
        display_item.add_graphic(Graphics.RectangleGraphic())
        display_item.add_graphic(Graphics.EllipseGraphic())
        display_item.display_data_channels[0].display_limits = (500, 1000)
        display_item.data_item.set_intensity_calibration(Calibration.Calibration(1.0, 2.0, "three"))
        data_group = DataGroup.DataGroup()
        data_group.append_display_item(document_controller.document_model.get_display_item_for_data_item(data_item))
        document_controller.document_model.append_data_group(data_group)
        data_item2 = DataItem.DataItem(numpy.zeros((12, 12), dtype=numpy.int64))
        document_controller.document_model.append_data_item(data_item2)
        display_item2 = document_controller.document_model.get_display_item_for_data_item(data_item2)
        data_group.append_display_item(document_controller.document_model.get_display_item_for_data_item(data_item2))
        data_item3 = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
        document_controller.document_model.append_data_item(data_item3)
        data_group.append_display_item(document_controller.document_model.get_display_item_for_data_item(data_item3))
        data_item2a = DataItem.DataItem()
        data_item2a.ensure_data_source()
        data_item2b = DataItem.DataItem()
        data_item2b.ensure_data_source()
        document_controller.document_model.append_data_item(data_item2a)
        document_controller.document_model.append_data_item(data_item2b)
        data_group.append_display_item(document_controller.document_model.get_display_item_for_data_item(data_item2a))
        data_group.append_display_item(document_controller.document_model.get_display_item_for_data_item(data_item2b))
        display_panel = document_controller.workspace_controller.display_panels[0]
        document_controller.selected_display_panel = display_panel
        display_panel.set_display_panel_display_item(display_item)
        self.assertEqual(document_controller.selected_data_item, data_item)
        document_controller.add_line_graphic()
        document_controller.add_rectangle_graphic()
        document_controller.add_ellipse_graphic()
        document_controller.add_point_graphic()
        display_panel.set_display_panel_display_item(display_item)
        self.assertEqual(document_controller.selected_data_item, data_item)
        document_controller.perform_action("processing.gaussian_blur")
        display_panel.set_display_panel_display_item(display_item)
        document_controller.perform_action("processing.resample")
        display_panel.set_display_panel_display_item(display_item)
        document_controller.processing_invert()
        display_panel.set_display_panel_display_item(display_item)
        document_controller.perform_action("processing.crop")
        display_panel.set_display_panel_display_item(display_item2)
        self.assertEqual(document_controller.selected_data_item, data_item2)
        document_controller.perform_action("processing.fft")
        document_controller.perform_action("processing.inverse_fft")

    def test_write_read_empty_data_item(self):
        # basic test (redundant, but useful for debugging)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((8, 8)))
                document_model.append_data_item(data_item)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(1, len(document_model.data_items))

    def test_set_data_item_data(self):
        # basic test (redundant, but useful for debugging)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((2, 2)))
                document_model.append_data_item(data_item)
                self.assertTrue(numpy.array_equal(data_item.data, numpy.zeros((2, 2))))
                data_item.set_data(numpy.ones((2, 2)))
                self.assertTrue(numpy.array_equal(data_item.data, numpy.ones((2, 2))))

    def test_save_document(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller()
            self.save_document(document_controller)

    def test_save_load_document(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            with contextlib.closing(document_controller):
                self.save_document(document_controller)
                data_items_count = len(document_controller.document_model.data_items)
                data_items_type = type(document_controller.document_model.data_items)
            # # read it back
            document_controller = profile_context.create_document_controller(auto_close=False)
            with contextlib.closing(document_controller):
                self.assertEqual(data_items_count, len(document_controller.document_model.data_items))
                self.assertEqual(data_items_type, type(document_controller.document_model.data_items))

    def test_storage_cache_closing_twice_throws_exception(self):
        storage_cache = Cache.DbStorageCache(":memory:")
        with self.assertRaises(AssertionError):
            storage_cache.close()
            storage_cache.close()

    def test_storage_cache_validates_data_range_upon_reading(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                data_range = display_item.display_data_channels[0].get_calculated_display_values(True).data_range
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                read_data_item = document_model.data_items[0]
                read_display_item = document_model.get_display_item_for_data_item(read_data_item)
                self.assertEqual(read_display_item.display_data_channels[0].get_calculated_display_values(True).data_range, data_range)

    def test_thumbnail_does_not_get_invalidated_upon_reading(self):
        # tests caching on display
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                profile.storage_cache.set_cached_value(display_item, "thumbnail_data", numpy.zeros((128, 128, 4), dtype=numpy.uint8))
                self.assertFalse(profile.storage_cache.is_cached_value_dirty(display_item, "thumbnail_data"))
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            with contextlib.closing(document_model):
                read_data_item = document_model.data_items[0]
                read_display_item = document_model.get_display_item_for_data_item(read_data_item)
                # thumbnail data should still be valid
                self.assertFalse(profile.storage_cache.is_cached_value_dirty(read_display_item, "thumbnail_data"))

    def test_reloading_thumbnail_from_cache_does_not_mark_it_as_dirty(self):
        # tests caching on display
        with create_memory_profile_context() as profile_context:
            storage_cache = profile_context.storage_cache
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                storage_cache.set_cached_value(display_item, "thumbnail_data", numpy.zeros((128, 128, 4), dtype=numpy.uint8))
                self.assertFalse(storage_cache.is_cached_value_dirty(display_item, "thumbnail_data"))
                with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.app.ui, display_item)) as thumbnail_source:
                    thumbnail_source.recompute_data()
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                read_data_item = document_model.data_items[0]
                read_display_item = document_model.get_display_item_for_data_item(read_data_item)
                # thumbnail data should still be valid
                self.assertFalse(storage_cache.is_cached_value_dirty(read_display_item, "thumbnail_data"))
                with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.app.ui, read_display_item)) as thumbnail_source:
                    self.assertFalse(thumbnail_source._is_thumbnail_dirty)

    def test_reload_data_item_initializes_display_data_range(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(document_model.data_items[0])
                self.assertIsNotNone(display_item.display_data_channels[0].get_calculated_display_values(True).data_range)
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                display_item = document_model.get_display_item_for_data_item(document_model.data_items[0])
                self.assertIsNotNone(display_item.display_data_channels[0].get_calculated_display_values(True).data_range)

    @unittest.expectedFailure
    def test_reload_data_item_does_not_recalculate_display_data_range(self):
        with create_memory_profile_context() as profile_context:
            storage_cache = profile_context.storage_cache
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item_uuid = document_model.get_display_item_for_data_item(document_model.data_items[0]).uuid
            # read it back
            data_range = 1, 4
            storage_cache.cache[display_item_uuid]["data_range"] = data_range
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                display_item = document_model.get_display_item_for_data_item(document_model.data_items[0])
                self.assertEqual(display_item.display_data_channels[0].get_calculated_display_values(True).data_range, data_range)

    def test_reload_data_item_does_not_load_actual_data(self):
        # reloading data from disk should not have to load the data, otherwise bad performance ensues
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
            # read it back
            data_read_count_ref = [0]
            def data_read(uuid):
                data_read_count_ref[0] += 1
            listener = profile_context._test_data_read_event.listen(data_read)
            with contextlib.closing(listener):
                document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                    self.assertEqual(data_read_count_ref[0], 0)

    def test_reload_data_item_initializes_display_slice(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((4, 4, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(document_model.data_items[0])
                display_data_channel = display_item.display_data_channels[0]
                display_data_channel.slice_center = 5
                display_data_channel.slice_width = 3
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                display_item = document_model.get_display_item_for_data_item(document_model.data_items[0])
                display_data_channel = display_item.display_data_channels[0]
                self.assertEqual(display_data_channel.slice_center, 5)
                self.assertEqual(display_data_channel.slice_width, 3)

    def test_reload_data_item_validates_display_slice_and_has_valid_data_and_stats(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data = numpy.zeros((4, 4, 8), numpy.uint32)
                data[..., 7] = 1
                data_item = DataItem.DataItem(data)
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(document_model.data_items[0])
                display_data_channel = display_item.display_data_channels[0]
                display_data_channel.slice_center = 5
                display_data_channel.slice_width = 1
                self.assertEqual(display_data_channel.get_calculated_display_values(True).data_range, (0, 0))
            # make the slice_center be out of bounds
            profile_context.project_properties["display_items"][0]["display_data_channels"][0]["slice_center"] = 20
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                display_item = document_model.get_display_item_for_data_item(document_model.data_items[0])
                display_data_channel = display_item.display_data_channels[0]
                self.assertEqual(display_data_channel.slice_center, 7)
                self.assertEqual(display_data_channel.slice_width, 1)
                self.assertIsNotNone(document_model.data_items[0].data)
                self.assertEqual(display_data_channel.get_calculated_display_values(True).data_range, (1, 1))

    def test_save_load_document_to_files(self):
        with create_temp_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            with contextlib.closing(document_controller):
                self.save_document(document_controller)
                data_items_count = len(document_controller.document_model.data_items)
                data_items_type = type(document_controller.document_model.data_items)
            # read it back
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_model):
                self.assertEqual(data_items_count, len(document_model.data_items))
                self.assertEqual(data_items_type, type(document_model.data_items))

    def test_db_storage(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                self.save_document(document_controller)
                document_model_uuid = document_controller.profile.uuid
                data_items_count = len(document_controller.document_model.data_items)
                data_items_type = type(document_controller.document_model.data_items)
                data_item0 = document_controller.document_model.data_items[0]
                data_item1 = document_controller.document_model.data_items[1]
                data_item0_specifier = data_item0.project.create_specifier(data_item0, allow_partial=False)
                data_item1_specifier = data_item1.project.create_specifier(data_item1, allow_partial=False)
                data_item0_display_item = document_model.get_display_item_for_data_item(data_item0)
                data_item0_calibration_len = len(data_item0_display_item.data_item.dimensional_calibrations)
                data_item1_data_items_len = len(document_controller.document_model.get_dependent_data_items(data_item1))
            # read it back
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                new_data_item0 = typing.cast(DataItem.DataItem, document_model.resolve_item_specifier(data_item0_specifier))
                new_data_item0_display_item = document_model.get_display_item_for_data_item(new_data_item0)
                self.assertIsNotNone(new_data_item0)
                self.assertEqual(document_model_uuid, document_controller.profile.uuid)
                self.assertEqual(data_items_count, len(document_controller.document_model.data_items))
                self.assertEqual(data_items_type, type(document_controller.document_model.data_items))
                self.assertIsNotNone(new_data_item0_display_item.data_item.data)
                self.assertEqual(data_item0_calibration_len, len(new_data_item0_display_item.data_item.dimensional_calibrations))
                new_data_item1 = typing.cast(DataItem.DataItem, document_model.resolve_item_specifier(data_item1_specifier))
                new_data_item1_data_items_len = len(document_controller.document_model.get_dependent_data_items(new_data_item1))
                self.assertEqual(data_item1_data_items_len, new_data_item1_data_items_len)
                # check over the data item
                self.assertEqual(new_data_item0_display_item.display_data_channels[0].display_limits, (500, 1000))
                self.assertEqual(new_data_item0_display_item.data_item.intensity_calibration.offset, 1.0)
                self.assertEqual(new_data_item0_display_item.data_item.intensity_calibration.scale, 2.0)
                self.assertEqual(new_data_item0_display_item.data_item.intensity_calibration.units, "three")
                self.assertEqual(new_data_item0.metadata.get("test")["one"], 1)

    def test_dependencies_are_correct_when_dependent_read_before_source(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                src_data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                src_data_item.category = "temporary"
                document_model.append_data_item(src_data_item)
                src_display_item = document_model.get_display_item_for_data_item(src_data_item)
                dst_data_item = document_model.get_fft_new(src_display_item)
                document_model.recompute_all()
                dst_data_item.created = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
                src_data_item_specifier = src_data_item.project.create_specifier(src_data_item, allow_partial=False)
                dst_data_item_specifier = dst_data_item.project.create_specifier(dst_data_item, allow_partial=False)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                src_data_item = typing.cast(DataItem.DataItem, document_model.resolve_item_specifier(src_data_item_specifier))
                dst_data_item = typing.cast(DataItem.DataItem, document_model.resolve_item_specifier(dst_data_item_specifier))
                # make sure the items are loading how we expect them to load (dependent first, then source)
                self.assertEqual(document_model.data_items[0], dst_data_item)
                self.assertEqual(document_model.data_items[1], src_data_item)
                # now the check to ensure the dependency is correct
                self.assertEqual(document_model.get_dependent_data_items(src_data_item)[0], dst_data_item)

    def test_dependencies_load_correctly_when_initially_loaded(self):
        # configure list of data items so that after sorted (on creation date) they will still be listed in this order.
        # this makes one dependency (86d982d1) load before the main item (71ab9215) and one (7d3b374e) load after.
        # this tests the get_dependent_data_items after reading data.
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item1 = DataItem.DataItem(item_uuid=uuid.UUID('86d982d1-6d81-46fa-b19e-574e904902de'))
                data_item2 = DataItem.DataItem(item_uuid=uuid.UUID('71ab9215-c6ae-4c36-aaf5-92ce78db02b6'))
                data_item3 = DataItem.DataItem(item_uuid=uuid.UUID('7d3b374e-e48b-460f-91de-7ff4e1a1a63c'))
                document_model.append_data_item(data_item1)
                document_model.append_data_item(data_item2)
                document_model.append_data_item(data_item3)
                computation1 = document_model.create_computation(Symbolic.xdata_expression("xd.ifft(a.xdata)"))
                computation1.create_input_item("a", Symbolic.make_item(data_item2))
                document_model.set_data_item_computation(data_item1, computation1)
                computation2 = document_model.create_computation(Symbolic.xdata_expression("xd.fft(a.xdata)"))
                computation2.create_input_item("a", Symbolic.make_item(data_item2))
                document_model.set_data_item_computation(data_item3, computation2)
            profile_context.data_properties_map["86d982d1-6d81-46fa-b19e-574e904902de"]["created"] = "2015-01-22T17:16:12.421290"
            profile_context.data_properties_map["71ab9215-c6ae-4c36-aaf5-92ce78db02b6"]["created"] = "2015-01-22T17:16:12.219730"
            profile_context.data_properties_map["7d3b374e-e48b-460f-91de-7ff4e1a1a63c"]["created"] = "2015-01-22T17:16:12.308003"
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                new_data_item1_specifier = Persistence.PersistentObjectSpecifier(item_uuid=uuid.UUID("71ab9215-c6ae-4c36-aaf5-92ce78db02b6"),
                                                                                 context_uuid=document_model._project.uuid)
                new_data_item1 = typing.cast(DataItem.DataItem, document_model.resolve_item_specifier(new_data_item1_specifier))
                new_data_item1_data_items_len = len(document_model.get_dependent_data_items(new_data_item1))
                self.assertEqual(2, new_data_item1_data_items_len)

    def test_dependencies_load_correctly_for_data_item_with_multiple_displays(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                document_model.get_invert_new(display_item)
                document_model.get_display_item_copy_new(display_item)
                self.assertEqual(1, len(document_model.get_dependent_data_items(data_item)))
                self.assertEqual(document_model.data_items[1], document_model.get_dependent_data_items(data_item)[0])
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = document_model.data_items[0]
                self.assertEqual(1, len(document_model.get_dependent_data_items(data_item)))
                self.assertEqual(document_model.data_items[1], document_model.get_dependent_data_items(data_item)[0])

    # test whether we can update master_data and have it written to the db
    def test_db_storage_write_data(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data1 = numpy.zeros((16, 16), numpy.uint32)
                data1[0,0] = 1
                data_item = DataItem.DataItem(data1)
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                data_group = DataGroup.DataGroup()
                data_group.append_display_item(document_model.get_display_item_for_data_item(data_item))
                document_controller.document_model.append_data_group(data_group)
                data2 = numpy.zeros((16, 16), numpy.uint32)
                data2[0,0] = 2
                display_item.data_item.set_data(data2)
            # read it back
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_item = document_controller.document_model.data_items[0]
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual(display_item.data_item.data[0 , 0], 2)

    # test whether we can update the db from a thread
    def test_db_storage_write_on_thread(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data1 = numpy.zeros((16, 16), numpy.uint32)
                data1[0,0] = 1
                data_item = DataItem.DataItem(data1)
                document_model.append_data_item(data_item)
                data_group = DataGroup.DataGroup()
                data_group.append_display_item(document_model.get_display_item_for_data_item(data_item))
                document_controller.document_model.append_data_group(data_group)

                def update_data(event_loop, data_item):
                    display_item = document_model.get_display_item_for_data_item(data_item)
                    data2 = numpy.zeros((16, 16), numpy.uint32)
                    data2[0,0] = 2
                    def update_data_soon():
                        display_item.data_item.set_data(data2)
                    event_loop.call_soon_threadsafe(update_data_soon)

                thread = threading.Thread(target=update_data, args=[document_controller.event_loop, data_item])
                thread.start()
                thread.join()
                document_controller.periodic()
            # read it back
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                read_data_item = document_controller.document_model.data_items[0]
                read_display_item = document_model.get_display_item_for_data_item(read_data_item)
                self.assertEqual(read_display_item.data_item.data[0, 0], 2)

    def test_storage_insert_items(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller()
            self.save_document(document_controller)
            # insert and append items
            data_group1 = DataGroup.DataGroup()
            data_group2 = DataGroup.DataGroup()
            data_group3 = DataGroup.DataGroup()
            document_controller.document_model.data_groups[0].append_data_group(data_group1)
            document_controller.document_model.data_groups[0].insert_data_group(0, data_group2)
            document_controller.document_model.data_groups[0].append_data_group(data_group3)
            self.assertEqual(len(profile_context.project_properties["data_groups"][0]["data_groups"]), 3)
            # delete items to generate key error unless primary keys handled carefully. need to delete an item that is at index >= 2 to test for this problem.
            data_group4 = DataGroup.DataGroup()
            data_group5 = DataGroup.DataGroup()
            document_controller.document_model.data_groups[0].insert_data_group(1, data_group4)
            document_controller.document_model.data_groups[0].insert_data_group(1, data_group5)
            document_controller.document_model.data_groups[0].remove_data_group(document_controller.document_model.data_groups[0].data_groups[2])
            # make sure indexes are in sequence still
            self.assertEqual(len(profile_context.project_properties["data_groups"][0]["data_groups"]), 4)

    def test_copy_data_group(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            self.save_document(document_controller)
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            with self.assertRaises(AssertionError):
                document_model.append_data_item(data_item)

    def test_adding_data_item_to_data_group_twice_raises_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            self.save_document(document_controller)
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            document_model.data_groups[0].append_display_item(document_model.get_display_item_for_data_item(data_item))
            with self.assertRaises(AssertionError):
                document_model.data_groups[0].append_display_item(document_model.get_display_item_for_data_item(data_item))

    def test_reading_data_group_with_duplicate_data_items_discards_duplicates(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8))))
                document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8))))
                document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8))))
                document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8))))
                data_group = DataGroup.DataGroup()
                data_group.append_display_item(document_model.display_items[0])
                data_group.append_display_item(document_model.display_items[1])
                document_model.append_data_group(data_group)
            profile_context.project_properties['data_groups'][0]['display_item_references'][1] = profile_context.project_properties['data_groups'][0]['display_item_references'][0]
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(1, len(document_model.data_groups[0].display_items))

    def test_insert_item_with_transaction(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_group = DataGroup.DataGroup()
                document_model.append_data_group(data_group)
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                data_item.title = 'title'
                with document_model.item_transaction(data_item):
                    data_item.set_data(numpy.zeros((16, 16), numpy.uint32))
                    document_model.append_data_item(data_item)
                    data_group.append_display_item(document_model.get_display_item_for_data_item(data_item))
            # make sure it reloads
            document_model = profile_context.create_document_model(auto_close=False)
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
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                document_model.append_data_item(data_item)
                data_item._set_modified(modified)
            # make sure it reloads
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(document_model.data_items[0].modified, modified)

    def test_data_item_should_store_modifications_within_transactions(self):
        created = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                document_model.append_data_item(data_item)
                with document_model.item_transaction(data_item):
                    data_item.created = created
            # make sure it reloads
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(document_model.data_items[0].created, created)

    def test_data_writes_to_and_reloads_from_file(self):
        with create_temp_profile_context() as profile_context:
            data = numpy.random.randn(16, 16)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                data_item.created = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
                data_item.set_data(data)
                document_model.append_data_item(data_item)
                data_file_path = data_item._test_get_file_path()
                self.assertTrue(os.path.exists(data_file_path))
                self.assertTrue(os.path.isfile(data_file_path))
            # make sure the data reloads
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                read_data_item = document_model.data_items[0]
                self.assertTrue(numpy.array_equal(read_data_item.data, data))
                # and then make sure the data file gets removed on disk when removed
                document_model.remove_data_item(document_model.data_items[0])
                self.assertFalse(os.path.exists(data_file_path))
            document_model = None
            storage_cache = None

    def test_data_rewrites_to_same_file(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.created = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
                data_item.set_data(numpy.random.randn(16, 16))
                document_model.append_data_item(data_item)
                data_file_path = data_item._test_get_file_path()
            new_data_file_path = pathlib.Path(data_file_path).parents[4] / pathlib.Path(data_file_path).name
            shutil.move(data_file_path, new_data_file_path)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                read_data_item = document_model.data_items[0]
                read_data_file_path = pathlib.Path(read_data_item._test_get_file_path())
                self.assertEqual(new_data_file_path, read_data_file_path)

    def test_delete_and_undelete_from_memory_storage_system_restores_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((16, 16)))
            document_model.append_data_item(data_item)
            data_item_uuid = data_item.uuid
            document_model.remove_data_item(data_item, safe=True)
            self.assertEqual(0, len(document_model.data_items))
            document_model.restore_data_item(document_model.projects[0], data_item_uuid)
            self.assertEqual(1, len(document_model.data_items))
            self.assertEqual(data_item_uuid, document_model.data_items[0].uuid)

    def test_delete_and_undelete_from_memory_storage_system_restores_data_item_after_reload(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16)))
                document_model.append_data_item(data_item)
                data_item_uuid = data_item.uuid
                document_model.remove_data_item(data_item, safe=True)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(0, len(document_model.data_items))
                document_model.restore_data_item(document_model.projects[0], data_item_uuid)
                self.assertEqual(1, len(document_model.data_items))
                self.assertEqual(data_item_uuid, document_model.data_items[0].uuid)

    def test_delete_and_undelete_from_file_storage_system_restores_data_item(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16)))
                document_model.append_data_item(data_item)
                data_item_uuid = data_item.uuid
                document_model.remove_data_item(data_item, safe=True)
                self.assertEqual(0, len(document_model.data_items))
                document_model.restore_data_item(document_model.projects[0], data_item_uuid)
                self.assertEqual(1, len(document_model.data_items))
                self.assertEqual(data_item_uuid, document_model.data_items[0].uuid)

    def test_deleted_file_removed_from_file_storage_system_restores_data_item_after_reload(self):
        # is established for restoring items in the trash.
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16)))
                document_model.append_data_item(data_item)
                data_item_uuid = data_item.uuid
                document_model.remove_data_item(data_item, safe=True)
            # # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(len(list(document_model.projects[0].project_storage_system._trash_dir.rglob("*"))), 0)

    def disabled_test_delete_and_undelete_from_file_storage_system_restores_data_item_after_reload(self):
        # this test is disabled for now; launching the application empties the trash until a user interface
        # is established for restoring items in the trash.
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16)))
                document_model.append_data_item(data_item)
                data_item_uuid = data_item.uuid
                document_model.remove_data_item(data_item, safe=True)
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(0, len(document_model.data_items))
                document_model.restore_data_item(document_model.projects[0], data_item_uuid)
                self.assertEqual(1, len(document_model.data_items))
                self.assertEqual(data_item_uuid, document_model.data_items[0].uuid)

    def test_data_changes_update_large_format_file(self):
        with create_temp_profile_context() as profile_context:
            zeros = numpy.zeros((8, 8), numpy.uint32)
            ones = numpy.ones((8, 8), numpy.uint32)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(ones)
                data_item.large_format = True
                document_model.append_data_item(data_item)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.data_items[0].set_data(zeros)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertTrue(numpy.array_equal(document_model.data_items[0].data, zeros))

    def test_data_changes_reserve_large_format_file(self):
        with create_temp_profile_context() as profile_context:
            zeros = numpy.zeros((8, 8), numpy.uint32)
            ones = numpy.ones((8, 8), numpy.uint32)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.large_format = True
                document_model.append_data_item(data_item)
                data_item.reserve_data(data_shape=ones.shape, data_dtype=ones.dtype, data_descriptor=DataAndMetadata.DataDescriptor(False, 0, 2))
                self.assertTrue(numpy.array_equal(zeros, data_item.data))
                data_item.set_data_and_metadata_partial(data_item.xdata.data_metadata,
                                                  DataAndMetadata.new_data_and_metadata(ones), (slice(0,8), slice(0, 8)),
                                                  (slice(0,8), slice(0, 8)))
                self.assertTrue(numpy.array_equal(ones, data_item.data))
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertTrue(numpy.array_equal(document_model.data_items[0].data, ones))
                document_model.data_items[0].set_data(zeros)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertTrue(numpy.array_equal(document_model.data_items[0].data, zeros))

    def test_writing_empty_data_item_returns_expected_values(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                reference = data_item._test_get_file_path()
                self.assertFalse(display_item.data_item.has_data)
                self.assertIsNone(display_item.data_item.data_shape)
                self.assertIsNone(display_item.data_item.data_dtype)
                self.assertIsNotNone(reference)
            document_model = None
            storage_cache = None

    def test_writing_data_item_with_no_data_sources_returns_expected_values(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                reference = data_item._test_get_file_path()
                self.assertIsNotNone(reference)
            document_model = None
            storage_cache = None

    def test_data_writes_to_file_after_transaction(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                # write data with transaction
                data_file_path = data_item._test_get_file_path()
                with document_model.item_transaction(data_item):
                    display_item.data_item.set_data(numpy.zeros((16, 16), numpy.uint32))
                    # make sure data does NOT exist during the transaction
                    self.assertIsNone(data_item.read_external_data("data"))
                # make sure it DOES exist after the transaction
                self.assertTrue(os.path.exists(data_file_path))
                self.assertTrue(os.path.isfile(data_file_path))
                self.assertIsNotNone(data_item.read_external_data("data"))
            document_model = None
            storage_cache = None

    def test_begin_end_transaction_with_no_change_should_not_write(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                # force a write and verify
                with document_model.item_transaction(data_item):
                    pass
                self.assertEqual(len(profile_context.data_properties_map.keys()), 1)
                # continue with test
                data_item._set_modified(modified)
                self.assertEqual(document_model.data_items[0].modified, modified)
                # now clear the memory_persistent_storage_system and see if it gets written again
                profile_context.data_properties_map.clear()
                with document_model.item_transaction(data_item):
                    pass
                self.assertEqual(document_model.data_items[0].modified, modified)
                # properties should still be empty, unless it was written again
                self.assertEqual(profile_context.data_properties_map, dict())

    def test_begin_end_transaction_with_change_should_write(self):
        # converse of previous test
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                data_item._set_modified(modified)
                self.assertEqual(document_model.data_items[0].modified, modified)
                # now clear the memory_persistent_storage_system and see if it gets written again
                profile_context.data_properties_map.clear()
                with document_model.item_transaction(data_item):
                    data_item.category = "category"
                self.assertNotEqual(document_model.data_items[0].modified, modified)
                # properties should still be empty, unless it was written again
                self.assertNotEqual(profile_context.data_properties_map, dict())

    def test_begin_end_transaction_with_non_data_change_should_not_write_data(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                # now clear the memory_persistent_storage_system and see if it gets written again
                profile_context.data_map.clear()
                with document_model.item_transaction(data_item):
                    data_item.caption = "caption"
                self.assertEqual(profile_context.data_map, dict())

    def test_begin_end_transaction_with_data_change_should_write_data(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                # now clear the memory_persistent_storage_system and see if it gets written again
                profile_context.data_map.clear()
                with document_model.item_transaction(data_item):
                    data_item.set_data(numpy.zeros((17, 17), numpy.uint32))
                self.assertEqual(profile_context.data_map[str(data_item.uuid)].shape, (17, 17))

    def test_begin_end_transaction_with_data_change_should_write_display_item(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                graphic = Graphics.PointGraphic()
                display_item.add_graphic(graphic)
                # now clear the memory_persistent_storage_system and see if it gets written again
                profile_context.project_properties["display_items"][0]["graphics"][0].clear()
                self.assertFalse(profile_context.project_properties["display_items"][0]["graphics"][0])
                with document_model.item_transaction(display_item):
                    graphic.label = "Fred"
                    self.assertFalse(profile_context.project_properties["display_items"][0]["graphics"][0])
                self.assertEqual("Fred", profile_context.project_properties["display_items"][0]["graphics"][0]["label"])
                graphic.label = "Grumble"
                self.assertEqual("Grumble", profile_context.project_properties["display_items"][0]["graphics"][0]["label"])

    def test_data_removes_file_after_original_date_and_session_change(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                data_item.created = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
                data_item.set_data(numpy.zeros((16, 16), numpy.uint32))
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

    def test_reloading_data_item_with_display_builds_graphics_properly(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                self.save_document(document_controller)
                read_data_item = document_model.data_items[0]
                read_data_item_specifier = read_data_item.project.create_specifier(read_data_item, allow_partial=False)
                read_display_item = document_model.get_display_item_for_data_item(read_data_item)
                self.assertEqual(len(read_display_item.graphics), 9)  # verify assumptions
            # read it back
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                read_data_item = typing.cast(DataItem.DataItem, document_model.resolve_item_specifier(read_data_item_specifier))
                read_display_item = document_model.get_display_item_for_data_item(read_data_item)
                # verify graphics reload
                self.assertEqual(len(read_display_item.graphics), 9)

    def test_writing_empty_data_item_followed_by_writing_data_adds_correct_calibrations(self):
        # this failed due to a key aliasing issue.
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                # create empty data item
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                with document_model.item_transaction(data_item):
                    display_item.data_item.set_data(numpy.zeros((16, 16), numpy.uint32))
                self.assertEqual(len(display_item.data_item.dimensional_calibrations), 2)
            # read it back
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                read_data_item = document_controller.document_model.data_items[0]
                read_display_item = document_model.get_display_item_for_data_item(read_data_item)
                # verify calibrations
                self.assertEqual(len(read_display_item.data_item.dimensional_calibrations), 2)

    def test_reloading_data_item_establishes_display_connection_to_storage(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
            # read it back
            document_controller = profile_context.create_document_controller(auto_close=False)
            with contextlib.closing(document_controller):
                pass

    def test_reloaded_line_profile_operation_binds_to_roi(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                document_model.get_line_profile_new(display_item)
                display_item.graphics[0].vector = (0.1, 0.2), (0.3, 0.4)
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = document_model.data_items[0]
                data_item2 = document_model.data_items[1]
                display_item = document_model.get_display_item_for_data_item(data_item)
                # verify that properties read it correctly
                self.assertEqual(display_item.graphics[0].start, (0.1, 0.2))
                self.assertEqual(display_item.graphics[0].end, (0.3, 0.4))
                display_item.graphics[0].start = 0.11, 0.22
                vector = document_model.get_data_item_computation(data_item2).get_input("line_region").vector
                self.assertEqual(vector[0], (0.11, 0.22))
                self.assertEqual(vector[1], (0.3, 0.4))

    def test_reloaded_line_plot_has_valid_calibration_style(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((8, ), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual("calibrated", display_item.calibration_style_id)
                self.assertEqual("calibrated", display_item.calibration_style.calibration_style_id)
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = document_model.data_items[0]
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual("calibrated", display_item.calibration_style_id)
                self.assertEqual("calibrated", display_item.calibration_style.calibration_style_id)

    def test_reloaded_graphics_load_properly(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                rect_graphic = Graphics.RectangleGraphic()
                rect_graphic.bounds = ((0.25, 0.25), (0.5, 0.5))
                display_item.add_graphic(rect_graphic)
            # read it back
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                read_data_item = document_model.data_items[0]
                read_display_item = document_model.get_display_item_for_data_item(read_data_item)
                # verify
                self.assertEqual(len(read_display_item.graphics), 1)

    def test_unknown_graphics_load_properly(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                rect_graphic = Graphics.RectangleGraphic()
                rect_graphic.bounds = ((0.25, 0.25), (0.5, 0.5))
                display_item.add_graphic(rect_graphic)
            profile_context.project_properties["display_items"][0]["graphics"][0]["type"] = "magical-graphic"
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            document_model.close()

    def test_reloaded_regions_load_properly(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                point_region = Graphics.PointGraphic()
                point_region.position = (0.6, 0.4)
                point_region_uuid = point_region.uuid
                document_model.get_display_item_for_data_item(data_item).add_graphic(point_region)
            # read it back
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                read_data_item = document_controller.document_model.data_items[0]
                read_display_item = document_model.get_display_item_for_data_item(read_data_item)
                # verify
                self.assertEqual(read_display_item.graphics[0].type, "point-graphic")
                self.assertEqual(read_display_item.graphics[0].uuid, point_region_uuid)
                self.assertEqual(read_display_item.graphics[0].position, (0.6, 0.4))

    def test_reloaded_empty_data_groups_load_properly(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_group = DataGroup.DataGroup()
                document_model.append_data_group(data_group)
            # read it back
            document_controller = profile_context.create_document_controller(auto_close=False)
            with contextlib.closing(document_controller):
                pass

    def test_new_data_item_stores_uuid_and_data_info_in_properties_immediately(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            self.assertTrue("data_shape" in data_item.properties)
            self.assertTrue("data_dtype" in data_item.properties)
            self.assertTrue("uuid" in data_item.properties)
            self.assertTrue("version" in data_item.properties)

    def test_deleting_dependent_after_deleting_source_succeeds(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                display_item = document_model.get_display_item_for_data_item(data_item)
                data_item.set_data(numpy.zeros((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                data_item2 = document_model.get_invert_new(display_item)
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)
                self.assertTrue(os.path.isfile(data2_file_path))
                # make sure dependent gets deleted
                document_model.remove_data_item(document_model.data_items[0])
                self.assertFalse(os.path.exists(data2_file_path))
            document_model = None

    def test_properties_are_able_to_be_cleared_and_reloaded(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((8, 8)))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_item.display_type = "image"
                display_item.display_type = None
            # make sure it reloads without changing modification
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                display_item = document_model.get_display_item_for_data_item(document_model.data_items[0])
                self.assertIsNone(display_item.display_type)

    def test_properties_with_no_data_reloads(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem()
                document_model.append_data_item(data_item)
                data_item.title = "TitleX"
            # read it back the library
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)
                self.assertEqual(document_model.data_items[0].title, "TitleX")

    def test_resized_data_reloads(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(data=numpy.zeros((16, 16)))
                document_model.append_data_item(data_item)
                data_item.set_data(numpy.zeros((32, 32)))
            # read it back the library
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)
                self.assertEqual(document_model.data_items[0].data.shape, (32, 32))

    def test_resized_data_reclaims_space(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(data=numpy.zeros((32, 32)))
                document_model.append_data_item(data_item)
                data_file_path = data_item._test_get_file_path()
                file_size = os.path.getsize(data_file_path)
                data_item.set_data(numpy.zeros((16, 16)))
                self.assertLess(os.path.getsize(data_file_path), file_size)

    def test_reloaded_display_has_correct_storage_cache(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
            # read it back
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                read_data_item = document_model.data_items[0]
                read_display_item = document_model.get_display_item_for_data_item(read_data_item)
                # check storage caches
                self.assertEqual(read_display_item._display_cache.storage_cache, read_display_item._suspendable_storage_cache)

    def test_data_items_written_with_newer_version_get_ignored(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                # increment the version on the data item
                list(profile_context.data_properties_map.values())[0]["version"] = DataItem.DataItem.writer_version + 1
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                # check it
                self.assertEqual(len(document_model.data_items), 0)

    def test_reloading_composite_operation_reconnects_when_reloaded(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
                document_model.append_data_item(data_item)
                crop_region = Graphics.RectangleGraphic()
                crop_region.bounds = ((0.25, 0.25), (0.5, 0.5))
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_item.add_graphic(crop_region)
                display_panel = document_controller.selected_display_panel
                display_panel.set_display_panel_display_item(display_item)
                new_data_item = document_model.get_invert_new(display_item, crop_region)
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                read_data_item = document_model.data_items[0]
                read_display_item = document_model.get_display_item_for_data_item(read_data_item)
                computation_bounds = document_model.get_data_item_computation(document_model.data_items[1]).get_input("src").graphic.bounds
                self.assertEqual(read_display_item.graphics[0].bounds, computation_bounds)
                read_display_item.graphics[0].bounds = ((0.3, 0.4), (0.5, 0.6))
                computation_bounds = document_model.get_data_item_computation(document_model.data_items[1]).get_input("src").graphic.bounds
                self.assertEqual(read_display_item.graphics[0].bounds, computation_bounds)

    def test_inverted_data_item_does_not_need_recompute_when_reloaded(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                document_model.get_invert_new(display_item)
                document_model.recompute_all()
            # reload and check inverted data item does not need recompute
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                read_data_item2 = document_model.data_items[1]
                read_display_item2 = document_model.get_display_item_for_data_item(read_data_item2)
                self.assertFalse(document_model.get_data_item_computation(read_display_item2.data_item).needs_update)

    def test_data_item_with_persistent_r_value_does_not_need_recompute_when_reloaded(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                document_model.get_invert_new(display_item)
                document_model.recompute_all()
                document_model.assign_variable_to_data_item(data_item)
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                read_data_item2 = document_model.data_items[1]
                read_display_item2 = document_model.get_display_item_for_data_item(read_data_item2)
                self.assertFalse(document_model.get_data_item_computation(read_display_item2.data_item).needs_update)

    def test_computations_with_id_update_to_latest_version_when_reloaded(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            modifieds = dict()
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                crop_region = Graphics.RectangleGraphic()
                display_item.add_graphic(crop_region)
                inverted_data_item = document_model.get_invert_new(display_item)
                cropped_inverted_data_item = document_model.get_invert_new(display_item, crop_region)
                document_model.recompute_all()
                modifieds[str(inverted_data_item.uuid)] = inverted_data_item.modified
                modifieds[str(cropped_inverted_data_item.uuid)] = cropped_inverted_data_item.modified
            # modify original expression to be something else
            original_expressions = dict()
            for data_item_uuid in profile_context.data_properties_map.keys():
                computation_dict = profile_context.data_properties_map[data_item_uuid].get("computation", dict())
                original_expression = computation_dict.get("original_expression")
                if original_expression:
                    computation_dict["original_expression"] = "incorrect"
                    original_expressions[data_item_uuid] = original_expression
            # reload and check inverted data item has updated original expression, does not need recompute, and has not been modified
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                for data_item_uuid in original_expressions.keys():
                    data_item_specifier = Persistence.PersistentObjectSpecifier(item_uuid=uuid.UUID(data_item_uuid))
                    data_item = typing.cast(DataItem.DataItem, document_model.resolve_item_specifier(data_item_specifier))
                    self.assertEqual(document_model.get_data_item_computation(data_item).original_expression, original_expressions[data_item_uuid])
                    self.assertFalse(document_model.get_data_item_computation(data_item).needs_update)
                    self.assertEqual(data_item.modified, modifieds[data_item_uuid])

    def test_line_profile_with_intervals_does_not_recompute_when_reloaded(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                line_profile_data_item = document_model.get_line_profile_new(display_item)
                line_profile_display_item = document_model.get_display_item_for_data_item(line_profile_data_item)
                line_profile_display_item.add_graphic(Graphics.IntervalGraphic())
                document_model.recompute_all()
                self.assertFalse(document_model.get_data_item_computation(document_model.data_items[1]).needs_update)
            # reload and check data item does not need recompute
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertFalse(document_model.get_data_item_computation(document_model.data_items[1]).needs_update)

    def test_cropped_data_item_with_region_does_not_need_recompute_when_reloaded(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                crop_region = Graphics.RectangleGraphic()
                display_item.add_graphic(crop_region)
                document_model.get_crop_new(display_item, crop_region)
                document_model.recompute_all()
                read_data_item2 = document_model.data_items[1]
                read_display_item2 = document_model.get_display_item_for_data_item(read_data_item2)
                self.assertFalse(document_model.get_data_item_computation(read_display_item2.data_item).needs_update)
            # reload and check inverted data item does not need recompute
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertFalse(document_model.get_data_item_computation(document_model.data_items[1]).needs_update)

    def test_cropped_data_item_with_region_still_updates_when_reloaded(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.float))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                crop_region = Graphics.RectangleGraphic()
                crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
                display_item.add_graphic(crop_region)
                document_model.get_crop_new(display_item, crop_region)
                document_model.recompute_all()
                read_data_item2 = document_model.data_items[1]
                read_display_item2 = document_model.get_display_item_for_data_item(read_data_item2)
                self.assertFalse(document_model.get_data_item_computation(read_display_item2.data_item).needs_update)
                self.assertEqual(read_display_item2.data_item.data_shape, (4, 4))
            # reload and check inverted data item does not need recompute
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.recompute_all()  # shouldn't be necessary unless other tests fail
                read_data_item = document_model.data_items[0]
                read_display_item = document_model.get_display_item_for_data_item(read_data_item)
                read_data_item2 = document_model.data_items[1]
                read_display_item2 = document_model.get_display_item_for_data_item(read_data_item2)
                read_display_item.graphics[0].bounds = (0.25, 0.25), (0.75, 0.75)
                document_model.recompute_all()
                self.assertEqual(read_display_item2.data_item.data_shape, (6, 6))

    def test_data_items_v1_migration(self):
        # construct v1 data item
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
            data_item_dict["spatial_calibrations"] = [{ "origin": 1.0, "scale": 2.0, "units": "mm" }, { "origin": 1.0, "scale": 2.0, "units": "mm" }]
            data_item_dict["intensity_calibration"] = { "origin": 0.1, "scale": 0.2, "units": "l" }
            data_item_dict["data_source_uuid"] = str(uuid.uuid4())
            data_item_dict["properties"] = { "voltage": 200.0, "session_uuid": str(uuid.uuid4()) }
            data_item_dict["version"] = 1
            profile_context.data_map["A"] = numpy.zeros((8, 8), numpy.uint32)
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check it
                self.assertEqual(len(document_model.data_items), 1)
                data_item = document_model.data_items[0]
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)
                self.assertEqual(len(display_item.data_item.dimensional_calibrations), 2)
                self.assertEqual(display_item.data_item.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
                self.assertEqual(display_item.data_item.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
                self.assertEqual(display_item.data_item.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))
                self.assertEqual(data_item.metadata.get("hardware_source")["voltage"], 200.0)
                self.assertFalse("session_uuid" in data_item.metadata.get("hardware_source"))
                self.assertIsNone(data_item.session_id)  # v1 is not allowed to set session_id
                self.assertEqual(display_item.data_item.data_dtype, numpy.uint32)
                self.assertEqual(display_item.data_item.data_shape, (8, 8))

    def test_data_items_v2_migration(self):
        # construct v2 data item
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
            data_item_dict["displays"] = [{"graphics": [{"type": "rect-graphic"}]}]
            data_item_dict["operations"] = [{"operation_id": "invert-operation"}]
            data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_item_dict["master_data_shape"] = (8, 8)
            data_item_dict["version"] = 2
            profile_context.data_map["A"] = numpy.zeros((8, 8), numpy.uint32)
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check it
                self.assertEqual(len(document_model.data_items), 1)
                data_item = document_model.data_items[0]
                display_item = document_model.display_items[0]
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)
                self.assertTrue("uuid" in display_item.properties)
                self.assertTrue("uuid" in display_item.properties["graphics"][0])

    def test_data_items_v3_migration(self):
        # construct v3 data item
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
            data_item_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_item_dict["intrinsic_spatial_calibrations"] = [{ "origin": 1.0, "scale": 2.0, "units": "mm" }, { "origin": 1.0, "scale": 2.0, "units": "mm" }]
            data_item_dict["intrinsic_intensity_calibration"] = { "origin": 0.1, "scale": 0.2, "units": "l" }
            data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_item_dict["master_data_shape"] = (8, 8)
            data_item_dict["version"] = 3
            profile_context.data_map["A"] = numpy.zeros((8, 8), numpy.uint32)
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check it
                self.assertEqual(len(document_model.data_items), 1)
                data_item = document_model.data_items[0]
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)
                self.assertEqual(len(display_item.data_item.dimensional_calibrations), 2)
                self.assertEqual(display_item.data_item.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
                self.assertEqual(display_item.data_item.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
                self.assertEqual(display_item.data_item.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))

    def test_data_items_v4_migration(self):
        # construct v4 data item
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
            data_item_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            region_uuid_str = str(uuid.uuid4())
            data_item_dict["regions"] = [{"type": "rectangle-region", "uuid": region_uuid_str}]
            data_item_dict["operations"] = [{"operation_id": "crop-operation", "region_uuid": region_uuid_str}]
            data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_item_dict["master_data_shape"] = (8, 8)
            data_item_dict["version"] = 4
            profile_context.data_map["A"] = numpy.zeros((8, 8), numpy.uint32)
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check it
                self.assertEqual(len(document_model.data_items), 1)
                data_item = document_model.data_items[0]
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)
                self.assertIsNotNone(document_model.get_data_item_computation(data_item))
                # not really checking beyond this; the program has changed enough to make the region connection not work without a data source

    def test_data_items_v5_migration(self):
        # construct v5 data item
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
            data_item_dict["uuid"] = str(uuid.uuid4())
            data_item_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_item_dict["master_data_shape"] = (8, 8)
            data_item_dict["intrinsic_spatial_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
            data_item_dict["intrinsic_intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
            data_item_dict["datetime_original"] = {'dst': '+60', 'tz': '-0800', 'local_datetime': '2000-06-30T15:01:00.000000'}
            data_item_dict["version"] = 5
            profile_context.data_map["A"] = numpy.zeros((8, 8), numpy.uint32)
            data_item2_dict = profile_context.data_properties_map.setdefault("B", dict())
            data_item2_dict["uuid"] = str(uuid.uuid4())
            data_item2_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_item2_dict["operations"] = [{"operation_id": "invert-operation"}]
            data_item2_dict["data_sources"] = [data_item_dict["uuid"]]
            data_item2_dict["datetime_original"] = {'dst': '+60', 'tz': '-0800', 'local_datetime': '2000-06-30T15:02:00.000000'}
            data_item2_dict["version"] = 5
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check it
                self.assertEqual(len(document_model.data_items), 2)
                self.assertEqual(str(document_model.data_items[0].uuid), data_item_dict["uuid"])
                self.assertEqual(str(document_model.data_items[1].uuid), data_item2_dict["uuid"])
                data_item = document_model.data_items[1]
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)
                self.assertIsNotNone(document_model.get_data_item_computation(data_item))
                self.assertEqual(len(document_model.get_data_item_computation(data_item).variables), 1)
                self.assertEqual(document_model.get_data_item_computation(data_item).get_input("src").data_item, document_model.data_items[0])
                # calibration renaming
                data_item = document_model.data_items[0]
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual(len(display_item.data_item.dimensional_calibrations), 2)
                self.assertEqual(display_item.data_item.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
                self.assertEqual(display_item.data_item.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
                self.assertEqual(display_item.data_item.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))

    def test_data_items_v6_migration(self):
        # construct v6 data item
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
            data_item_dict["uuid"] = str(uuid.uuid4())
            data_item_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_item_dict["master_data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_item_dict["master_data_shape"] = (8, 8)
            data_item_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
            data_item_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
            data_item_dict["datetime_original"] = {'dst': '+60', 'tz': '-0800', 'local_datetime': '2000-06-30T15:01:00.000000'}
            data_item_dict["version"] = 6
            profile_context.data_map["A"] = numpy.zeros((8, 8), numpy.uint32)
            data_item2_dict = profile_context.data_properties_map.setdefault("B", dict())
            data_item2_dict["uuid"] = str(uuid.uuid4())
            data_item2_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_item2_dict["operation"] = {"type": "operation", "operation_id": "invert-operation", "data_sources": [{"type": "data-item-data-source", "data_item_uuid": data_item_dict["uuid"]}]}
            data_item2_dict["version"] = 6
            data_item3_dict = profile_context.data_properties_map.setdefault("C", dict())
            data_item3_dict["uuid"] = str(uuid.uuid4())
            data_item3_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_item3_dict["master_data_dtype"] = None
            data_item3_dict["master_data_shape"] = None
            data_item3_dict["dimensional_calibrations"] = []
            data_item3_dict["intensity_calibration"] = {}
            data_item2_dict["datetime_original"] = {'dst': '+60', 'tz': '-0800', 'local_datetime': '2000-06-30T15:02:00.000000'}
            data_item3_dict["version"] = 6
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check it
                self.assertEqual(len(document_model.data_items), 3)
                self.assertEqual(str(document_model.data_items[0].uuid), data_item_dict["uuid"])
                self.assertEqual(str(document_model.data_items[1].uuid), data_item2_dict["uuid"])
                self.assertEqual(str(document_model.data_items[2].uuid), data_item3_dict["uuid"])
                data_item = document_model.data_items[1]
                self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)
                self.assertIsNotNone(document_model.get_data_item_computation(data_item))
                self.assertEqual(len(document_model.get_data_item_computation(data_item).variables), 1)
                self.assertEqual(document_model.get_data_item_computation(data_item).get_input("src").data_item, document_model.data_items[0])
                # calibration renaming
                data_item = document_model.data_items[0]
                display_item = document_model.get_display_item_for_data_item(data_item)
                self.assertEqual(len(display_item.data_item.dimensional_calibrations), 2)
                self.assertEqual(display_item.data_item.dimensional_calibrations[0], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
                self.assertEqual(display_item.data_item.dimensional_calibrations[1], Calibration.Calibration(offset=1.0, scale=2.0, units="mm"))
                self.assertEqual(display_item.data_item.intensity_calibration, Calibration.Calibration(offset=0.1, scale=0.2, units="l"))

    def test_data_items_v7_migration(self):
        # construct v7 data item
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
            data_item_dict["uuid"] = str(uuid.uuid4())
            data_item_dict["version"] = 7
            caption, title = "caption", "title"
            data_item_dict["caption"] = caption
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 1)
                self.assertEqual(document_model.data_items[0].metadata.get("hardware_source"), new_metadata)
                self.assertEqual(document_model.data_items[0].caption, caption)
                self.assertEqual(document_model.data_items[0].title, title)
                self.assertEqual(document_model.data_items[0].created, datetime.datetime.strptime("2000-06-30T22:02:00.000000", "%Y-%m-%dT%H:%M:%S.%f"))
                self.assertEqual(document_model.data_items[0].modified, document_model.data_items[0].created)
                self.assertEqual(document_model.data_items[0].metadata.get("hardware_source").get("autostem").get("high_tension_v"), 42)

    def test_data_items_v8_to_v9_fft_migration(self):
        # construct v8 data items
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(computation.processing_id, "fft")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.fft(src.cropped_display_xdata)"))
                self.assertEqual(len(computation.variables), 1)
                self.assertEqual(computation.get_input("src").data_item, document_model.data_items[0])
                self.assertEqual(computation.get_output("target"), document_model.data_items[1])
                data = numpy.arange(64).reshape((8, 8))
                document_model.data_items[0].set_data(data)
                self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
                self.assertIsNone(computation.error_text)
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_cross_correlate_migration(self):
        # construct v8 data items
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()

            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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

            src2_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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

            dst_data_item_dict = profile_context.data_properties_map.setdefault("C", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 3)
                computation = document_model.get_data_item_computation(document_model.data_items[2])
                self.assertEqual(computation.processing_id, "cross-correlate")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.crosscorrelate(src1.cropped_display_xdata, src2.cropped_display_xdata)"))
                self.assertEqual(len(computation.variables), 2)
                self.assertEqual(computation.get_input("src1").data_item, document_model.data_items[0])
                self.assertEqual(computation.get_input("src2").data_item, document_model.data_items[1])
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
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(computation.processing_id, "gaussian-blur")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.gaussian_blur(src.cropped_display_xdata, sigma)"))
                self.assertEqual(len(computation.variables), 2)
                self.assertEqual(computation.get_input("src").data_item, document_model.data_items[0])
                self.assertEqual(computation.get_input("src").graphic, document_model.display_items[0].graphics[0])
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].bounds[0][0], 0.2)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].bounds[0][1], 0.3)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].bounds[1][0], 0.4)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].bounds[1][1], 0.5)
                self.assertAlmostEqual(1.7, computation.get_input_value("sigma"))
                data = numpy.arange(64).reshape((8, 8))
                document_model.data_items[0].set_data(data)
                self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
                self.assertIsNone(computation.error_text)
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_median_filter_migration(self):
        # construct v8 data items
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(computation.processing_id, "median-filter")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.median_filter(src.cropped_display_xdata, filter_size)"))
                self.assertEqual(len(computation.variables), 2)
                self.assertEqual(computation.get_input("src").data_item, document_model.data_items[0])
                self.assertAlmostEqual(5, computation.get_input_value("filter_size"))
                data = numpy.arange(64).reshape((8, 8))
                document_model.data_items[0].set_data(data)
                self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
                self.assertIsNone(computation.error_text)
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_slice_migration(self):
        # construct v8 data items
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(computation.processing_id, "slice")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.slice_sum(src.cropped_xdata, center, width)"))
                self.assertEqual(len(computation.variables), 3)
                self.assertEqual(computation.get_input("src").data_item, document_model.data_items[0])
                self.assertAlmostEqual(3, computation.get_input_value("center"))
                self.assertAlmostEqual(2, computation.get_input_value("width"))
                data = numpy.arange(512).reshape((8, 8, 8))
                document_model.data_items[0].set_data(data)
                self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
                self.assertIsNone(computation.error_text)
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_crop_migration(self):
        # construct v8 data items
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(computation.processing_id, "crop")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("src.cropped_display_xdata"))
                self.assertEqual(len(computation.variables), 1)
                self.assertEqual(computation.get_input("src").data_item, document_model.data_items[0])
                self.assertEqual(computation.get_input("src").graphic, document_model.display_items[0].graphics[0])
                data = numpy.arange(64).reshape((8, 8))
                document_model.data_items[0].set_data(data)
                self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
                self.assertIsNone(computation.error_text)
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_projection_migration(self):
        # construct v8 data items
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(computation.processing_id, "sum")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.sum(src.cropped_xdata, src.xdata.datum_dimension_indexes[0])"))
                self.assertEqual(len(computation.variables), 1)
                self.assertEqual(computation.get_input("src").data_item, document_model.data_items[0])
                self.assertEqual(computation.get_input("src").graphic, document_model.display_items[0].graphics[0])
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].bounds[0][0], 0.2)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].bounds[0][1], 0.3)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].bounds[1][0], 0.4)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].bounds[1][1], 0.5)
                data = numpy.arange(64).reshape((8, 8))
                document_model.data_items[0].set_data(data)
                self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
                self.assertIsNone(computation.error_text)
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_convert_to_scalar_migration(self):
        # construct v8 data items
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(computation.processing_id, "convert-to-scalar")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("src.cropped_display_xdata"))
                self.assertEqual(len(computation.variables), 1)
                self.assertEqual(computation.get_input("src").data_item, document_model.data_items[0])
                self.assertEqual(computation.get_input("src").graphic, document_model.display_items[0].graphics[0])
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].bounds[0][0], 0.2)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].bounds[0][1], 0.3)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].bounds[1][0], 0.4)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].bounds[1][1], 0.5)
                data = numpy.arange(64).reshape((8, 8))
                document_model.data_items[0].set_data(data)
                self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
                self.assertIsNone(computation.error_text)
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_resample_migration(self):
        # construct v8 data items
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(computation.processing_id, "resample")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.resample_image(src.cropped_display_xdata, (height, width))"))
                self.assertEqual(len(computation.variables), 3)
                self.assertEqual(computation.get_input("src").data_item, document_model.data_items[0])
                self.assertAlmostEqual(200, computation.get_input_value("width"))
                self.assertAlmostEqual(256, computation.get_input_value("height"))
                data = numpy.arange(64).reshape((8, 8))
                document_model.data_items[0].set_data(data)
                self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
                self.assertIsNone(computation.error_text)
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_pick_migration(self):
        # construct v8 data items
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(computation.processing_id, "pick-point")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.pick(src.xdata, pick_region.position)"))
                self.assertEqual(len(computation.variables), 2)
                self.assertEqual(computation.get_input("src").data_item, document_model.data_items[0])
                self.assertEqual(computation.get_input("pick_region"), document_model.display_items[0].graphics[0])
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].position[0], 0.4)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].position[1], 0.5)
                data = numpy.arange(512).reshape((8, 8, 8))
                document_model.data_items[0].set_data(data)
                data0 = DocumentModel.evaluate_data(computation).data
                self.assertIsNone(computation.error_text)
                document_model.display_items[0].graphics[0].position = 0.0, 0.0
                data1 = DocumentModel.evaluate_data(computation).data
                self.assertIsNone(computation.error_text)
                self.assertFalse(numpy.array_equal(data0, data1))
                self.assertTrue(numpy.array_equal(data1, data[0, 0, :]))
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_line_profile_migration(self):
        # construct v8 data items
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(computation.processing_id, "line-profile")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.line_profile(src.display_xdata, line_region.vector, line_region.line_width)"))
                self.assertEqual(len(computation.variables), 2)
                self.assertEqual(computation.get_input("src").data_item, document_model.data_items[0])
                self.assertEqual(computation.get_input("line_region"), document_model.display_items[0].graphics[0])
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].start[0], 0.2)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].start[1], 0.3)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].end[0], 0.4)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].end[1], 0.5)
                self.assertAlmostEqual(document_model.display_items[0].graphics[0].width, 1.3)
                data = numpy.arange(64).reshape((8, 8))
                document_model.data_items[0].set_data(data)
                self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
                self.assertIsNone(computation.error_text)
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v8_to_v9_unknown_migration(self):
        # construct v8 data items
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                self.assertIsNone(document_model.get_data_item_computation(document_model.data_items[1]))
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v9_to_v10_migration(self):
        # construct v9 data items with regions, make sure they get translated to graphics
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()
            data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 1)
                display_item = document_model.get_display_item_for_data_item(document_model.data_items[0])
                graphics = display_item.graphics
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
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()

            data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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

            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                src_display_item = document_model.get_display_item_for_data_item(document_model.data_items[0])
                dst_display_item = document_model.get_display_item_for_data_item(document_model.data_items[1])
                self.assertEqual(src_display_item.graphics[0], document_model.get_data_item_computation(dst_display_item.data_item).get_input("line_region"))
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v10_to_v11_created_date_migration(self):
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()

            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                self.assertEqual(document_model.data_items[0].created.date(), DataItem.DatetimeToStringConverter().convert_back(created_str).date())
                self.assertEqual(document_model.data_items[0].modified.date(), DataItem.DatetimeToStringConverter().convert_back(modified_str).date())

    def test_data_items_v10_to_v11_crop_migration(self):
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()

            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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

            dst_data_item_dict = profile_context.data_properties_map.setdefault("C", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(computation.processing_id, "crop")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("src.cropped_display_xdata"))
                self.assertEqual(len(computation.variables), 1)
                self.assertEqual(computation.get_input("src").data_item, document_model.data_items[0])
                self.assertEqual(computation.get_input("src").graphic, document_model.display_items[0].graphics[0])
                data = numpy.arange(64).reshape((8, 8))
                document_model.data_items[0].set_data(data)
                self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
                self.assertIsNone(computation.error_text)
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v10_to_v11_gaussian_migration(self):
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()

            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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

            dst_data_item_dict = profile_context.data_properties_map.setdefault("C", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 2)
                computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(computation.processing_id, "gaussian-blur")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.gaussian_blur(src.cropped_display_xdata, sigma)"))
                self.assertEqual(len(computation.variables), 2)
                self.assertEqual(computation.get_input("src").data_item, document_model.data_items[0])
                self.assertEqual(computation.get_input("src").graphic, document_model.display_items[0].graphics[0])
                data = numpy.arange(64).reshape((8, 8))
                document_model.data_items[0].set_data(data)
                self.assertIsNotNone(DocumentModel.evaluate_data(computation).data)
                self.assertIsNone(computation.error_text)
                for data_item in document_model.data_items:
                    self.assertEqual(data_item.properties["version"], DataItem.DataItem.writer_version)

    def test_data_items_v10_to_v11_cross_correlate_migration(self):
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()

            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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

            src2_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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

            dst_data_item_dict = profile_context.data_properties_map.setdefault("C", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                # check metadata transferred to data source
                self.assertEqual(len(document_model.data_items), 3)
                computation = document_model.get_data_item_computation(document_model.data_items[2])
                self.assertEqual(computation.processing_id, "cross-correlate")
                self.assertEqual(computation.expression, Symbolic.xdata_expression("xd.crosscorrelate(src1.cropped_display_xdata, src2.cropped_display_xdata)"))
                self.assertEqual(len(computation.variables), 2)
                self.assertEqual(computation.get_input("src1").data_item, document_model.data_items[0])
                self.assertEqual(computation.get_input("src1").graphic, document_model.display_items[0].graphics[0])
                self.assertEqual(computation.get_input("src2").data_item, document_model.data_items[1])
                self.assertEqual(computation.get_input("src2").graphic, document_model.display_items[1].graphics[0])
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
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()

            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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

            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
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
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()

            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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

            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
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
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()

            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
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

            dst_data_item_dict = profile_context.data_properties_map.setdefault("B", dict())
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

            # make sure it reloads twice
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                self.assertEqual(1, len(document_model.computations))

    def test_data_items_v12_to_v13(self):
        with create_memory_profile_context() as profile_context:
            profile_context.create_legacy_project()

            src_data_item_dict = profile_context.data_properties_map.setdefault("A", dict())
            src_uuid_str = str(uuid.uuid4())
            src_data_item_dict["uuid"] = src_uuid_str
            src_data_item_dict["version"] = 12
            src_data_source_dict = dict()
            src_data_source_dict["uuid"] = str(uuid.uuid4())
            src_data_source_dict["type"] = "buffered-data-source"
            src_data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
            src_data_source_dict["data_shape"] = (8, 8)
            src_data_source_dict["metadata"] = {"a": "AAA", "description": {"timezone": "America/Los_Angeles"}}
            graphic_uuid_str = str(uuid.uuid4())
            src_data_item_dict["displays"] = [{"uuid": str(uuid.uuid4()), "dimensional_calibration_style": "pixels-center", "display_calibrated_values": True, "y_style": "log", "graphics": [{"type": "line-graphic", "uuid": graphic_uuid_str, "start": (0, 0), "end": (1, 1)}]}]
            src_data_item_dict["data_source"] = src_data_source_dict
            src_data_item_dict.setdefault("description", dict())["title"] = "title"
            src_data_item_dict.setdefault("description", dict())["caption"] = "caption"
            src_data_item_dict["session_id"] = "20170101-120000"
            src_data_item_dict["category"] = "temporary"
            src_data_item_dict["timezone"] = "Europe/Athens"
            src_data_item_dict["timezone_offset"] = "+0300"
            src_data_item_dict["session_metadata"] = {"instrument": "a big screwdriver"}
            src_data_item_dict["data_item_uuids"] = []
            src_data_item_dict["connections"] = []

            # make sure it reloads twice
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                data_item = document_model.data_items[0]
                display_item = document_model.display_items[0]
                data_item_properties = data_item.properties
                self.assertEqual("title", data_item.title)
                self.assertEqual("caption", data_item.caption)
                self.assertEqual("20170101-120000", data_item.session_id)
                self.assertEqual("temporary", data_item.category)
                self.assertEqual("a big screwdriver", data_item.session_data["instrument"])
                self.assertEqual("a big screwdriver", data_item.session_metadata["instrument"])
                self.assertEqual({"a": "AAA"}, data_item.metadata)
                self.assertNotIn("description", data_item_properties)
                self.assertNotIn("session_metadata", data_item_properties)
                self.assertEqual("Europe/Athens", data_item_properties["timezone"])
                self.assertEqual("+0300", data_item_properties["timezone_offset"])
                self.assertEqual("20170101-120000", data_item_properties["session_id"])
                self.assertEqual("temporary", data_item_properties["category"])
                self.assertNotIn("data_item_uuids", data_item_properties)
                self.assertNotIn("connections", data_item_properties)
                self.assertEqual(document_model.get_display_items_for_data_item(data_item), {display_item})
                self.assertEqual(display_item.data_item, data_item)
                self.assertEqual(display_item.session_id, data_item.session_id)
                self.assertEqual(display_item.calibration_style_id, "pixels-center")
                self.assertEqual(display_item.get_display_property("y_style"), "log")

    def test_migrate_overwrites_old_data(self):
        with create_temp_profile_context() as profile_context:
            library_path = profile_context.projects_dir / "Nion Swift Workspace.nslib"
            data_path = profile_context.projects_dir / "Nion Swift Data"
            with library_path.open("w") as fp:
                json.dump({}, fp)
            # construct older data
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
            file_handler = profile_context._file_handlers[0]
            file_path = pathlib.Path(data_path, "File").with_suffix(file_handler.get_extension())
            handler = file_handler(file_path)
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            # read workspace
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                file_path = document_model.data_items[0]._test_get_file_path()
            # verify
            handler = profile_context._file_handlers[0](file_path)
            with contextlib.closing(handler):
                new_data_item_dict = handler.read_properties()
                self.assertEqual(new_data_item_dict["uuid"], data_item_dict["uuid"])
                self.assertEqual(new_data_item_dict["version"], DataItem.DataItem.storage_version)

    # should be separately testing a migration of profile and project
    @unittest.expectedFailure
    def test_migrate_update_library_version(self):
        with create_temp_profile_context() as profile_context:
            # construct workspace with old file
            library_path = profile_context.projects_dir / "Data.nsproj"
            with library_path.open("w") as fp:
                json.dump({}, fp)
            # read workspace
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
            # verify
            with library_path.open("r") as fp:
                library_properties = json.load(fp)
                self.assertEqual(library_properties["version"], FileStorageSystem.PROJECT_VERSION)

    def test_ignore_migrate_does_not_overwrite_old_data(self):
        with create_temp_profile_context() as profile_context:
            # construct workspace with old file
            library_path = profile_context.projects_dir / "Nion Swift Workspace.nslib"
            data_path = profile_context.projects_dir / "Nion Swift Data"
            with library_path.open("w") as fp:
                json.dump({}, fp)
            # construct older data
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
            file_handler = profile_context._file_handlers[0]
            file_path = pathlib.Path(data_path, "File").with_suffix(file_handler.get_extension())
            handler = file_handler(file_path)
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            # read workspace
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
            # verify
            handler = profile_context._file_handlers[0](file_path)
            with contextlib.closing(handler):
                new_data_item_dict = handler.read_properties()
                self.assertEqual(new_data_item_dict["uuid"], data_item_dict["uuid"])
                self.assertEqual(new_data_item_dict["version"], data_item_dict["version"])

    def test_auto_migrate_copies_old_data_to_new_library(self):
        with create_temp_profile_context() as profile_context:
            # construct workspace with old file
            library_path = profile_context.projects_dir / "Nion Swift Workspace.nslib"
            data_path = profile_context.projects_dir / "Nion Swift Data"
            with library_path.open("w") as fp:
                json.dump({}, fp)
            # construct older data
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
            file_handler = profile_context._file_handlers[0]
            handler = file_handler(pathlib.Path(data_path, "File").with_suffix(file_handler.get_extension()))
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            # auto migrate workspace
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                self.assertEqual(len(document_model.data_items), 1)
                self.assertEqual(document_model.data_items[0].uuid, uuid.UUID(data_item_dict["uuid"]))
                # double check correct persistent storage context
                document_model.remove_data_item(document_model.data_items[0])

    def test_auto_migrate_only_copies_old_data_to_new_library_once_per_uuid(self):
        with create_temp_profile_context() as profile_context:
            # construct workspace with old file
            library_path = profile_context.projects_dir / "Nion Swift Workspace.nslib"
            data_path = profile_context.projects_dir / "Nion Swift Data"
            with library_path.open("w") as fp:
                json.dump({}, fp)
            # construct older data
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
            file_handler = profile_context._file_handlers[0]
            handler = file_handler(pathlib.Path(data_path, "File").with_suffix(file_handler.get_extension()))
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            # auto migrate workspace
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                self.assertEqual(len(document_model.data_items), 1)
                self.assertEqual(document_model.data_items[0].uuid, uuid.UUID(data_item_dict["uuid"]))

    def test_auto_migrate_migrates_new_data_items(self):
        with create_temp_profile_context() as profile_context:
            # construct workspace with old file
            library_path = profile_context.projects_dir / "Nion Swift Workspace.nslib"
            data_path = profile_context.projects_dir / "Nion Swift Data"
            with library_path.open("w") as fp:
                json.dump({}, fp)
            # construct older data
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
            file_handler = profile_context._file_handlers[0]
            handler = file_handler(pathlib.Path(data_path, "File").with_suffix(file_handler.get_extension()))
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            # make new library
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                new_data_item_specifier = data_item.project.create_specifier(data_item, allow_partial=False)
            # auto migrate workspace
            document_model = profile_context.create_document_model(auto_close=False)
            # this migrate is not allowed since it is already migrated.
            # in the future, maybe there will be a "migrate_data_items" but it doesn't exist yet. it's currently all or nothing.
            # document_model.projects[0].migrate_to_latest()
            with contextlib.closing(document_model):
                self.assertEqual(2, len(document_model.data_items))
                self.assertEqual(2, len(document_model.display_items))
                data_item_specifier = Persistence.PersistentObjectSpecifier(item_uuid=uuid.UUID(src_uuid_str), context_uuid=document_model._project.uuid)
                self.assertIsNotNone(typing.cast(DataItem.DataItem, document_model.resolve_item_specifier(data_item_specifier)))
                self.assertIsNotNone(typing.cast(DataItem.DataItem, document_model.resolve_item_specifier(new_data_item_specifier)))

    def test_auto_migrate_skips_migrated_and_deleted_data_items(self):
        with create_temp_profile_context() as profile_context:
            src_uuid_str = str(uuid.uuid4())
            # construct workspace with old file
            library_path = profile_context.projects_dir / "Nion Swift Workspace.nslib"
            data_path = profile_context.projects_dir / "Nion Swift Data"
            with library_path.open("w") as fp:
                json.dump({"data_item_deletions": [src_uuid_str, str(uuid.uuid4())]}, fp)
            # construct older data
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
            file_handler = profile_context._file_handlers[0]
            handler = file_handler(pathlib.Path(data_path, "File").with_suffix(file_handler.get_extension()))
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            # auto migrate workspace
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                self.assertEqual(len(document_model.data_items), 0)
                self.assertEqual(len(document_model.projects[0].project_storage_system.find_data_items()), 0)

    def test_auto_migrate_does_not_overwrite_newer_items(self):
        with create_temp_profile_context() as profile_context:
            # construct workspace with old file
            library_path = profile_context.projects_dir / "Nion Swift Workspace.nslib"
            data_path = profile_context.projects_dir / "Nion Swift Data"
            with library_path.open("w") as fp:
                json.dump({}, fp)
            # construct older data
            src_uuid_str = str(uuid.uuid4())
            data_item_dict = dict()
            data_item_dict["uuid"] = src_uuid_str
            data_item_dict["version"] = 9
            data_source_dict = dict()
            data_source_dict["uuid"] = str(uuid.uuid4())
            data_source_dict["type"] = "buffered-data-source"
            data_source_dict["title"] = "Title9"
            data_source_dict["displays"] = [{"uuid": str(uuid.uuid4())}]
            data_source_dict["data_dtype"] = str(numpy.dtype(numpy.uint32))
            data_source_dict["data_shape"] = (8, 8)
            data_source_dict["dimensional_calibrations"] = [{ "offset": 1.0, "scale": 2.0, "units": "mm" }, { "offset": 1.0, "scale": 2.0, "units": "mm" }]
            data_source_dict["intensity_calibration"] = { "offset": 0.1, "scale": 0.2, "units": "l" }
            data_item_dict["data_sources"] = [data_source_dict]
            file_handler = profile_context._file_handlers[0]
            handler = file_handler(pathlib.Path(data_path, "File").with_suffix(file_handler.get_extension()))
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            # write a newer item with same uuid
            data_item = DataItem.DataItem(numpy.zeros((8,8)), item_uuid=uuid.UUID(src_uuid_str))
            data_item.title = "Title"
            profile = profile_context.create_profile()
            profile.read_profile()
            with contextlib.closing(profile):
                with contextlib.closing(profile.projects[0].project_storage_system._make_storage_handler(data_item)) as handler:
                    handler.write_properties(data_item.write_to_dict(), datetime.datetime.utcnow())
                    handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            # read the document and migrate
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                self.assertEqual(len(document_model.data_items), 1)
                data_items = document_model.projects[0].project_storage_system.find_data_items()
                self.assertEqual(len(data_items), 1)
                for data_item in data_items:
                    data_item.close()
                self.assertEqual("Title", document_model.data_items[0].title)

    # there is no defined migration for data item references
    @unittest.expectedFailure
    def test_auto_migrate_connects_data_references_in_migrated_data(self):
        with create_temp_profile_context() as profile_context:
            src_uuid_str = str(uuid.uuid4())
            # construct workspace with old file
            library_path = profile_context.projects_dir / "Nion Swift Workspace.nslib"
            data_path = profile_context.projects_dir / "Nion Swift Data"
            with library_path.open("w") as fp:
                json.dump({"data_item_references": {"key": src_uuid_str}}, fp)
            # construct older data
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
            file_handler = profile_context._file_handlers[0]
            handler = file_handler(pathlib.Path(data_path, "File").with_suffix(file_handler.get_extension()))
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            # auto migrate workspace
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                self.assertEqual(len(document_model.data_items), 1)
                self.assertEqual(document_model.get_data_item_reference("key").data_item, document_model.data_items[0])

    def test_data_reference_is_reloaded(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                self.assertEqual(len(document_model.data_items), 0)
                data_item = DataItem.DataItem(numpy.zeros((256, 256)))
                document_model.append_data_item(data_item)
                document_model.setup_channel("key", data_item)
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                self.assertEqual(document_model.data_items[0], document_model.get_data_item_reference('key').data_item)

    def test_data_reference_is_reloaded_with_multiple_projects(self):
        # test a data item reference pointing to a data item in the non-initial project that gets reloaded
        # resolves its reference.
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_controller):
                profile.set_work_project_reference(profile.project_references[1])
                self.assertEqual(len(document_model.data_items), 0)
                data_item = DataItem.DataItem(numpy.zeros((256, 256)))
                document_model.append_data_item(data_item, project=profile.projects[0])
                data_item = DataItem.DataItem(numpy.zeros((256, 256)))
                document_model.append_data_item(data_item, project=profile.projects[1])
                document_model.setup_channel("key", data_item)
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                self.assertEqual(document_model.data_items[1], document_model.get_data_item_reference('key').data_item)

    def test_data_item_with_connected_crop_region_should_not_update_modification_when_loading(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                crop_region = Graphics.RectangleGraphic()
                display_item.add_graphic(crop_region)
                data_item_cropped = document_model.get_crop_new(display_item, crop_region)
                document_model.recompute_all()
                data_item._set_modified(modified)
                data_item_cropped._set_modified(modified)
                self.assertEqual(document_model.data_items[0].modified, modified)
                self.assertEqual(document_model.data_items[1].modified, modified)
            # make sure it reloads without changing modification
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(document_model.data_items[0].modified, modified)
                self.assertEqual(document_model.data_items[1].modified, modified)
                document_model.recompute_all()  # try recomputing too
                self.assertEqual(document_model.data_items[0].modified, modified)
                self.assertEqual(document_model.data_items[1].modified, modified)

    def test_data_modified_property_is_persistent(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                data_item.data_modified = modified
                document_model.append_data_item(data_item)
            # make sure it reloads without changing modification
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(modified, document_model.data_items[0].data_modified)

    def test_copy_retains_data_modified_property(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                data_item.data_modified = modified
                document_model.append_data_item(data_item)
                data_item_copy = document_model.copy_data_item(data_item)
                self.assertEqual(modified, data_item_copy.data_modified)

    def test_snapshot_retains_data_modified_property(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                data_item.data_modified = modified
                document_model.append_data_item(data_item)
                data_item_copy = document_model.get_display_item_snapshot_new(document_model.get_display_item_for_data_item(data_item)).data_item
                self.assertEqual(modified, data_item_copy.data_modified)

    def test_data_modified_and_modified_are_updated_when_modifying_data(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                data_item.created = modified
                data_item.data_modified = modified
                data_item._set_modified(modified)
                document_model.append_data_item(data_item)
                data_item.set_data(numpy.zeros((16, 16)))
                self.assertEqual(modified, data_item.created)
                self.assertLess(modified, data_item.modified)
                self.assertLess(modified, data_item.data_modified)

    def test_only_modified_are_updated_when_modifying_metadata(self):
        modified = datetime.datetime(year=2000, month=6, day=30, hour=15, minute=2)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                data_item.created = modified
                data_item.data_modified = modified
                data_item._set_modified(modified)
                document_model.append_data_item(data_item)
                data_item.title = "BBB"
                data_item.metadata = {"A": "B"}
                self.assertEqual(modified, data_item.created)
                self.assertLess(modified, data_item.modified)
                self.assertEqual(modified, data_item.data_modified)

    def test_auto_migrate_handles_secondary_storage_types(self):
        with create_temp_profile_context() as profile_context:
            # construct workspace with old file
            library_path = profile_context.projects_dir / "Nion Swift Workspace.nslib"
            data_path = profile_context.projects_dir / "Nion Swift Data"
            with library_path.open("w") as fp:
                json.dump({}, fp)
            # construct older data
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
            file_handler = profile_context._file_handlers[1]  # HDF5
            handler = file_handler(pathlib.Path(data_path, "File").with_suffix(file_handler.get_extension()))
            with contextlib.closing(handler):
                handler.write_properties(data_item_dict, datetime.datetime.utcnow())
                handler.write_data(numpy.zeros((8,8)), datetime.datetime.utcnow())
            # auto migrate workspace
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                self.assertEqual(len(document_model.data_items), 1)
            # ensure it imports twice
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.projects[0].migrate_to_latest()
                self.assertEqual(len(document_model.data_items), 1)

    @unittest.expectedFailure
    def test_storage_cache_disabled_during_transaction(self):
        with create_memory_profile_context() as profile_context:
            storage_cache = profile_context.storage_cache
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_data_channel = display_item.display_data_channels[0]
                display_data_channel.get_calculated_display_values(True).data_range  # trigger storage
                cached_data_range = storage_cache.cache[display_item.uuid]["data_range"]
                self.assertEqual(cached_data_range, (1, 1))
                self.assertEqual(display_data_channel.get_calculated_display_values(True).data_range, (1, 1))
                with document_model.data_item_transaction(data_item):
                    data_item.set_data(numpy.zeros((16, 16), numpy.uint32))
                    self.assertEqual(display_data_channel.get_calculated_display_values(True).data_range, (0, 0))
                    self.assertEqual(cached_data_range, storage_cache.cache[display_item.uuid]["data_range"])
                    self.assertEqual(cached_data_range, (1, 1))
                self.assertEqual(storage_cache.cache[display_item.uuid]["data_range"], (0, 0))

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
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                display_item.display_data_channels[0].display_limits = (numpy.float32(1.0), numpy.float32(1.0))

    def test_data_structure_reloads_basic_value_types(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_structure = document_model.create_data_structure(structure_type="nada")
                data_structure.set_property_value("title", "Title")
                data_structure.set_property_value("width", 8.5)
                document_model.append_data_structure(data_structure)
                data_structure.set_property_value("interval", (0.5, 0.2))
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_structures), 1)
                self.assertEqual(document_model.data_structures[0].get_property_value("title"), "Title")
                self.assertEqual(document_model.data_structures[0].get_property_value("width"), 8.5)
                self.assertEqual(document_model.data_structures[0].get_property_value("interval"), (0.5, 0.2))
                self.assertEqual(document_model.data_structures[0].structure_type, "nada")

    def test_attached_data_structure_reconnects_after_reload(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((2, 2)))
                document_model.append_data_item(data_item)
                data_structure = document_model.create_data_structure()
                data_structure.set_property_value("title", "Title")
                document_model.append_data_structure(data_structure)
                document_model.attach_data_structure(data_structure, data_item)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_structures), 1)
                self.assertEqual(document_model.data_structures[0].source, document_model.data_items[0])
                document_model.remove_data_item(document_model.data_items[0])
                self.assertEqual(len(document_model.data_structures), 0)

    def test_connected_data_structure_reconnects_after_reload(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
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
            document_model = profile_context.create_document_model(auto_close=False)
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
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((2, 2)))
                document_model.append_data_item(data_item)
                data_struct = document_model.create_data_structure()
                data_struct.set_referenced_object("master", data_item)
                document_model.append_data_structure(data_struct)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(document_model.data_items[0], document_model.data_structures[0].get_referenced_object("master"))

    def test_data_structure_reloads_after_computation(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.zeros((2, 2)))
                document_model.append_data_item(data_item)
                data_struct = document_model.create_data_structure()
                data_struct.set_referenced_object("master", data_item)
                document_model.append_data_structure(data_struct)
                computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
                computation.create_input_item("a", Symbolic.make_item(data_item))
                computed_data_item = DataItem.DataItem()
                document_model.append_data_item(computed_data_item)
                document_model.set_data_item_computation(computed_data_item, computation)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(2, len(document_model.data_items))
                self.assertEqual(1, len(document_model.data_structures))
                self.assertEqual(1, len(document_model.computations))

    def test_data_item_sources_reconnect_after_reload(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
                data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
                data_item3 = DataItem.DataItem(numpy.zeros((2, 2)))
                document_model.append_data_item(data_item1)
                document_model.append_data_item(data_item2)
                document_model.append_data_item(data_item3)
                data_item1.source = data_item2
                data_item3.source = data_item2
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(3, len(document_model.data_items))
                document_model.remove_data_item(document_model.data_items[1])
                self.assertEqual(0, len(document_model.data_items))

    def test_computation_reconnects_after_reload(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data = numpy.ones((2, 2), numpy.double)
                data_item = DataItem.DataItem(data)
                document_model.append_data_item(data_item)
                computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
                computation.create_input_item("a", Symbolic.make_item(data_item))
                computed_data_item = DataItem.DataItem(data.copy())
                document_model.append_data_item(computed_data_item)
                document_model.set_data_item_computation(computed_data_item, computation)
                document_model.recompute_all()
                assert numpy.array_equal(-document_model.data_items[0].data, document_model.data_items[1].data)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                read_computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertIsNotNone(read_computation)
                with document_model.data_items[0].data_ref() as data_ref:
                    data_ref.data += 1.5
                document_model.recompute_all()
                assert numpy.array_equal(-document_model.data_items[0].data, document_model.data_items[1].data)

    def test_computation_does_not_recompute_on_reload(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data = numpy.ones((2, 2), numpy.double)
                data_item = DataItem.DataItem(data)
                document_model.append_data_item(data_item)
                computation = document_model.create_computation(Symbolic.xdata_expression("-a.xdata"))
                computation.create_input_item("a", Symbolic.make_item(data_item))
                computed_data_item = DataItem.DataItem(data.copy())
                document_model.append_data_item(computed_data_item)
                document_model.set_data_item_computation(computed_data_item, computation)
                document_model.recompute_all()
                assert numpy.array_equal(-document_model.data_items[0].data, document_model.data_items[1].data)
            document_model = profile_context.create_document_model(auto_close=False)
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
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data = numpy.ones((2, 2), numpy.double)
                data_item = DataItem.DataItem(data)
                document_model.append_data_item(data_item)
                computation = document_model.create_computation(Symbolic.xdata_expression("xd.column(a.xdata)"))
                computation.create_input_item("a", Symbolic.make_item(data_item))
                computed_data_item = DataItem.DataItem(data.copy())
                document_model.append_data_item(computed_data_item)
                document_model.set_data_item_computation(computed_data_item, computation)
                document_model.recompute_all()
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                read_computation = document_model.get_data_item_computation(document_model.data_items[1])
                with document_model.data_items[0].data_ref() as data_ref:
                    data_ref.data += 1.5
                document_model.recompute_all()

    def test_computation_slice_reloads(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data = numpy.ones((8, 4, 4), numpy.double)
                data_item = DataItem.DataItem(data)
                document_model.append_data_item(data_item)
                computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata[2:4, :, :] + a.xdata[5]"))
                computation.create_input_item("a", Symbolic.make_item(data_item))
                computed_data_item = DataItem.DataItem(data.copy())
                document_model.append_data_item(computed_data_item)
                document_model.set_data_item_computation(computed_data_item, computation)
                document_model.recompute_all()
                data_shape = computed_data_item.data_shape
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                computed_data_item = document_model.data_items[1]
                with document_model.data_items[0].data_ref() as data_ref:
                    data_ref.data += 1.5
                document_model.recompute_all()
                self.assertEqual(data_shape, computed_data_item.data_shape)

    def test_computation_pick_and_display_interval_reloads(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data = numpy.ones((8, 4, 100), numpy.double)
                data_item = DataItem.DataItem(data)
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                document_model.get_pick_new(display_item)
                document_model.recompute_all()
                # check assumptions
                self.assertEqual((0.05, 0.15), document_model.get_display_item_for_data_item(document_model.data_items[0]).display_data_channels[0].slice_interval)
                self.assertEqual((0.05, 0.15), document_model.get_display_item_for_data_item(document_model.data_items[1]).graphics[0].interval)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                # check initial assumptions
                self.assertEqual(len(document_model.data_items), 2)
                self.assertEqual((0.05, 0.15), document_model.get_display_item_for_data_item(document_model.data_items[0]).display_data_channels[0].slice_interval)
                self.assertEqual((0.05, 0.15), document_model.get_display_item_for_data_item(document_model.data_items[1]).graphics[0].interval)
                # check still connected
                document_model.get_display_item_for_data_item(document_model.data_items[0]).display_data_channels[0].slice_interval = (0.3, 0.5)
                self.assertEqual((0.3, 0.5), document_model.get_display_item_for_data_item(document_model.data_items[0]).display_data_channels[0].slice_interval)
                self.assertEqual((0.3, 0.5), document_model.get_display_item_for_data_item(document_model.data_items[1]).graphics[0].interval)
                # check still connected, both directions
                document_model.get_display_item_for_data_item(document_model.data_items[1]).graphics[0].interval = (0.4, 0.6)
                self.assertEqual((0.4, 0.6), document_model.get_display_item_for_data_item(document_model.data_items[0]).display_data_channels[0].slice_interval)
                self.assertEqual((0.4, 0.6), document_model.get_display_item_for_data_item(document_model.data_items[1]).graphics[0].interval)

    def test_computation_corrupt_variable_reloads(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data = numpy.ones((8, 4, 4), numpy.double)
                data_item = DataItem.DataItem(data)
                document_model.append_data_item(data_item)
                computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata"))
                computation.create_input_item("a", Symbolic.make_item(data_item))
                x = computation.create_variable("x")  # value is intentionally None
                computed_data_item = DataItem.DataItem(data.copy())
                document_model.append_data_item(computed_data_item)
                document_model.set_data_item_computation(computed_data_item, computation)
                x.value_type = "integral"
                x.value = 6
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                read_computation = document_model.get_data_item_computation(document_model.data_items[1])
                self.assertEqual(read_computation.variables[1].name, "x")
                self.assertEqual(read_computation.variables[1].value, 6)

    def test_computation_missing_variable_reloads(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data = numpy.ones((8, 4, 4), numpy.double)
                data_item = DataItem.DataItem(data)
                document_model.append_data_item(data_item)
                computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x + y"))
                computation.create_input_item("a", Symbolic.make_item(data_item))
                computation.create_variable("x", value_type="integral", value=3)
                computation.create_variable("y", value_type="integral", value=4)
                computed_data_item = DataItem.DataItem(data.copy())
                document_model.append_data_item(computed_data_item)
                document_model.set_data_item_computation(computed_data_item, computation)
            del profile_context.project_properties["computations"][0]["variables"][0]
            profile_context.project_properties["computations"][0]["variables"][0]["uuid"] = str(uuid.uuid4())
            document_model = profile_context.create_document_model(auto_close=False)
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
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((2, 2)))
                document_model.append_data_item(data_item)
                dst_data_item = DataItem.DataItem(numpy.zeros((2, 2)))
                document_model.append_data_item(dst_data_item)
                computation = document_model.create_computation()
                computation.processing_id = "computation1"
                computation.create_input_item("src", Symbolic.make_item(data_item))
                computation.create_output_item("dst", Symbolic.make_item(dst_data_item))
                document_model.append_computation(computation)
                document_model.recompute_all()
                assert numpy.array_equal(-document_model.data_items[0].data, document_model.data_items[1].data)
                self.assertEqual(len(document_model.computations), 1)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.computations), 1)
                document_model.data_items[0].set_data(numpy.random.randn(3, 3))
                document_model.recompute_all()
                self.assertEqual(document_model.data_items[0].data.shape, (3, 3))
                self.assertTrue(numpy.array_equal(-document_model.data_items[0].data, document_model.data_items[1].data))

    def test_library_computation_listens_to_changes_after_reload(self):
        TestStorageClass.computation1_eval_count = 0
        Symbolic.register_computation_type("computation1", self.Computation1)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((2, 2)))
                document_model.append_data_item(data_item)
                dst_data_item = DataItem.DataItem(numpy.zeros((2, 2)))
                document_model.append_data_item(dst_data_item)
                computation = document_model.create_computation()
                computation.processing_id = "computation1"
                computation.create_input_item("src", Symbolic.make_item(data_item))
                computation.create_output_item("dst", Symbolic.make_item(dst_data_item))
                document_model.append_computation(computation)
                document_model.recompute_all()
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = document_model.data_items[0]
                dst_data_item = document_model.data_items[1]
                self.assertEqual(len(document_model.data_items), 2)
                self.assertEqual(document_model.get_dependent_data_items(data_item)[0], dst_data_item)
                new_data_item = DataItem.DataItem(numpy.ones((2, 2)))
                document_model.append_data_item(new_data_item)
                document_model.computations[0].set_input_item("src", Symbolic.make_item(new_data_item))
                self.assertEqual(document_model.get_dependent_data_items(new_data_item)[0], dst_data_item)

    def test_library_computation_does_not_evaluate_with_missing_inputs(self):
        TestStorageClass.computation1_eval_count = 0
        Symbolic.register_computation_type("computation1", self.Computation1)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((2, 2)))
                document_model.append_data_item(data_item)
                dst_data_item = DataItem.DataItem(numpy.zeros((2, 2)))
                document_model.append_data_item(dst_data_item)
                computation = document_model.create_computation()
                computation.processing_id = "computation1"
                computation.create_input_item("src", Symbolic.make_item(data_item))
                computation.create_output_item("dst", Symbolic.make_item(dst_data_item))
                document_model.append_computation(computation)
                document_model.recompute_all()
            profile_context.project_properties["computations"][0]["variables"][0]["specifier"]["uuid"] = str(uuid.uuid4())
            self.computation1_eval_count = 0
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.data_items[0].set_data(numpy.random.randn(3, 3))
                document_model.recompute_all()
                self.assertEqual(self.computation1_eval_count, 0)

    class AddN:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src_list):
            if len(set(src.data_shape for src in src_list)) == 1:
                self.__new_data = numpy.sum([src.data for src in src_list], axis=0)
            else:
                self.__new_data = None

        def commit(self):
            if self.__new_data is not None:
                self.computation.set_referenced_data("dst", self.__new_data)
            else:
                self.computation.clear_referenced_data("dst")

    def test_library_computation_with_list_input_reloads(self):
        Symbolic.register_computation_type("add_n", self.AddN)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.app._set_document_model(document_model)  # required to allow API to find document model
                data_item1 = DataItem.DataItem(numpy.full((2, 2), 1))
                document_model.append_data_item(data_item1)
                display_item1 = document_model.get_display_item_for_data_item(data_item1)
                data_item2 = DataItem.DataItem(numpy.full((2, 2), 2))
                document_model.append_data_item(data_item2)
                display_item2 = document_model.get_display_item_for_data_item(data_item2)
                computation = document_model.create_computation()
                items = Symbolic.make_item_list([display_item1.display_data_channel, display_item2.display_data_channel], type="display_xdata")
                computation.create_input_item("src_list", items)
                computation.processing_id = "add_n"
                document_model.append_computation(computation)
                document_model.recompute_all()
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.data_items[0].set_data(numpy.full((2, 2), 3))
                document_model.recompute_all()
                self.assertTrue(numpy.array_equal(document_model.data_items[2].data, numpy.full((2, 2), 5)))

    def test_library_computation_with_list_input_with_missing_reloads_and_library_remove_data_item_still_functions(self):
        Symbolic.register_computation_type("add_n", self.AddN)
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.app._set_document_model(document_model)  # required to allow API to find document model
                data_item1 = DataItem.DataItem(numpy.full((2, 2), 1))
                document_model.append_data_item(data_item1)
                display_item1 = document_model.get_display_item_for_data_item(data_item1)
                data_item2 = DataItem.DataItem(numpy.full((2, 2), 2))
                document_model.append_data_item(data_item2)
                display_item2 = document_model.get_display_item_for_data_item(data_item2)
                computation = document_model.create_computation()
                items = Symbolic.make_item_list([display_item1.display_data_channel, display_item2.display_data_channel], type="display_xdata")
                computation.create_input_item("src_list", items)
                computation.processing_id = "add_n"
                document_model.append_computation(computation)
                document_model.recompute_all()
            profile_context.project_properties["computations"][0]["variables"][0]["object_specifiers"][0]["uuid"] = str(uuid.uuid4())
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                document_model.remove_data_item(document_model.data_items[0])

    def test_data_item_with_corrupt_created_still_loads(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                src_data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(src_data_item)
            profile_context.data_properties_map[str(src_data_item.uuid)]["created"] = "todaytodaytodaytodaytoday0"
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                # for corrupt/missing created dates, a new one matching todays date should be assigned
                self.assertIsNotNone(document_model.data_items[0].created)
                self.assertEqual(document_model.data_items[0].created.date(), datetime.datetime.now().date())

    def test_loading_library_with_two_copies_of_same_uuid_ignores_second_copy(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                file_path = data_item._test_get_file_path()
            file_path_base, file_path_ext = os.path.splitext(file_path)
            shutil.copyfile(file_path, file_path_base + "_" + file_path_ext)
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                self.assertEqual(len(document_model.data_items), 1)

    def test_snapshot_copies_storage_format(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item1 = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                data_item2 = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                data_item2.large_format = True
                document_model.append_data_item(data_item1)
                document_model.append_data_item(data_item2)
            # read it back
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item1 = document_model.data_items[0]
                data_item2 = document_model.data_items[1]
                data_item1a = document_model.get_display_item_snapshot_new(document_model.get_display_item_for_data_item(data_item1)).data_item
                data_item2a = document_model.get_display_item_snapshot_new(document_model.get_display_item_for_data_item(data_item2)).data_item
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

    def test_pending_data_on_new_data_item_updates_properly(self):
        with create_temp_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem()
            with document_model.item_transaction(data_item):
                document_model.append_data_item(data_item)
                data_item.set_data(numpy.ones((2, 2)))
                # simulate situation in the histogram panel where xdata is stored and used later
                data_and_metadata = data_item.data_and_metadata  # this xdata contains ability to reload from data item
                data_item.set_data(numpy.ones((2, 2)))  # but it is overwritten here and may be unloaded
                self.assertIsNotNone(data_and_metadata.data)  # ensure that it isn't actually unloaded

    def test_undo_redo_is_written_to_storage(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            command = DocumentController.DocumentController.InsertDataItemsCommand(document_controller, [data_item], 0)
            command.perform()
            document_controller.push_undo_command(command)
            self.assertEqual(1, len(profile_context.data_properties_map.keys()))
            document_controller.handle_undo()
            self.assertEqual(0, len(profile_context.data_properties_map.keys()))
            document_controller.handle_redo()
            self.assertEqual(1, len(profile_context.data_properties_map.keys()))

    def test_undo_graphic_move_is_written_to_storage(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                crop_region = Graphics.RectangleGraphic()
                display_item.add_graphic(crop_region)
                command = DisplayPanel.ChangeGraphicsCommand(document_model, display_item, [crop_region], command_id="nudge", is_mergeable=True)
                old_bounds = crop_region.bounds
                new_bounds = ((0.1, 0.1), (0.2, 0.2))
                crop_region.bounds = new_bounds
                document_controller.push_undo_command(command)
                self.assertEqual(new_bounds, crop_region.bounds)
                document_controller.handle_undo()
                self.assertEqual(old_bounds, crop_region.bounds)
            # make sure it reloads with the OLD bounds
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                self.assertEqual(old_bounds, document_model.display_items[0].graphics[0].bounds)

    def test_undo_computation_edit_is_written_to_storage(self):
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                computation = document_model.create_computation()
                computation.label = "DEF"
                document_model.append_computation(computation)
                command = ComputationPanel.ComputationModel.ChangeComputationCommand(document_model, computation, command_id="computation_change_label", is_mergeable=True, label="ABC")
                command.perform()
                document_controller.push_undo_command(command)
                self.assertEqual("ABC", document_model.computations[0].label)
                document_controller.handle_undo()
                self.assertEqual("DEF", document_model.computations[0].label)
            # make sure it reloads with the OLD bounds
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                self.assertEqual("DEF", document_model.computations[0].label)

    def test_undo_display_item_is_written_to_storage(self):
        # this bug was caused because restoring data items didn't remove the data item from data item deletions.
        with create_memory_profile_context() as profile_context:
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                data_item = DataItem.DataItem(numpy.zeros((2, )))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                # check assumptions
                self.assertEqual(1, len(document_model.display_items[0].data_items))
                self.assertEqual(document_model.data_items[0], document_model.display_items[0].data_items[0])
                # remove display
                command = DocumentController.DocumentController.RemoveDisplayItemCommand(document_controller, display_item)
                command.perform()
                document_controller.push_undo_command(command)
                document_controller.handle_undo()
                # check assumptions
                self.assertEqual(1, len(document_model.display_items[0].data_items))
                self.assertEqual(document_model.data_items[0], document_model.display_items[0].data_items[0])
            # make sure it reloads with the OLD bounds
            document_controller = profile_context.create_document_controller(auto_close=False)
            document_model = document_controller.document_model
            with contextlib.closing(document_controller):
                self.assertEqual(1, len(document_model.display_items[0].data_items))
                self.assertEqual(document_model.data_items[0], document_model.display_items[0].data_items[0])

    def test_display_item_display_layers_reload_with_same_data_indexes(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                data_item1 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
                document_model.append_data_item(data_item1)
                data_item2 = DataItem.DataItem(numpy.zeros((8,), numpy.uint32))
                document_model.append_data_item(data_item2)
                display_item = document_model.get_display_item_for_data_item(data_item1)
                display_item.append_display_data_channel_for_data_item(data_item2)
                display_item._set_display_layer_property(0, "ref", "A")
                display_item._set_display_layer_property(1, "ref", "B")
                self.assertEqual(2, len(display_item.display_data_channels))
                self.assertEqual(0, display_item.get_display_layer_property(0, "data_index"))
                self.assertEqual(1, display_item.get_display_layer_property(1, "data_index"))
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                display_item = document_model.display_items[0]
                self.assertEqual(2, len(display_item.display_data_channels))
                self.assertEqual(0, display_item.get_display_layer_property(0, "data_index"))
                self.assertEqual(1, display_item.get_display_layer_property(1, "data_index"))

    def test_work_project_is_created_if_not_found(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False, clear_work=True)
            profile = document_model.profile
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                self.assertTrue(all(project.project_state == "loaded" for project in profile.projects))

    def test_work_project_is_created_if_not_valid(self):
        with create_temp_profile_context() as profile_context:
            # create a normal profile
            document_model = profile_context.create_document_model(auto_close=False, clear_work=True)
            profile = document_model.profile
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                work_project_path = profile.work_project_reference.project_path
            # corrupt it (old version)
            work_project_data_json = json.dumps({"version": 2, "uuid": str(uuid.uuid4())})
            work_project_path.write_text(work_project_data_json, "utf-8")
            # load normal profile
            document_model = profile_context.create_document_model(auto_close=False, clear_work=True)
            profile = document_model.profile
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                # confirm a new work project was created
                self.assertNotEqual(work_project_path, profile.work_project_reference.project_path)

    def test_file_project_opens_with_same_uuid(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False, project_name="Project2", project_data_name="Data2")
            profile = document_model.profile
            with contextlib.closing(document_model):
                data_item = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32))
                document_model.append_data_item(data_item)
                project_uuid = document_model.projects[0].uuid
                project_specifier = document_model.projects[0].item_specifier
                project_path = profile.project_references[0].project_path
            profile_context.reset_profile()
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            with contextlib.closing(document_model):
                profile.add_project_index(project_path)
                self.assertEqual(project_uuid, document_model.projects[1].uuid)
                self.assertEqual(document_model.projects[1], profile.persistent_object_context.get_registered_object(project_specifier))

    def test_missing_project_does_not_prevent_other_projects_from_loading(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            # create a 2nd project
            project_path = profile_context.projects_dir / pathlib.Path("Project2").with_suffix(".nsproj")
            project_data_json = json.dumps({"version": FileStorageSystem.PROJECT_VERSION, "uuid": str(uuid.uuid4()), "project_data_folders": ["Data2"]})
            project_path.write_text(project_data_json, "utf-8")
            profile.add_project_index(project_path)
            # first load document normally
            with contextlib.closing(document_model):
                self.assertEqual(2, len(document_model.projects))
                self.assertEqual("loaded", document_model.projects[0].project_state)
                self.assertEqual("loaded", document_model.projects[1].project_state)
            # now load with missing 2nd project
            project_path.unlink()
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            with contextlib.closing(document_model):
                self.assertEqual(1, len(document_model.projects))
                self.assertEqual("loaded", document_model.projects[0].project_state)
                self.assertIsNone(profile.project_references[1].project)

    def test_importing_project_twice_only_enables_existing_version(self):
        with create_temp_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            # create a 2nd project
            project_path = profile_context.projects_dir / pathlib.Path("Project2").with_suffix(".nsproj")
            project_data_json = json.dumps({"version": FileStorageSystem.PROJECT_VERSION, "uuid": str(uuid.uuid4()), "project_data_folders": ["Data2"]})
            project_path.write_text(project_data_json, "utf-8")
            profile.add_project_index(project_path)
            # first load document normally
            with contextlib.closing(document_model):
                self.assertEqual(2, len(document_model.projects))
                profile.unload_project_reference(profile.project_references[1])
                self.assertFalse(profile.project_references[1].is_active)
                profile.add_project_index(profile.project_references[1].project_path)
                self.assertEqual(2, len(document_model.projects))
                self.assertTrue(profile.project_references[1].is_active)

    def test_data_item_variable_reloads(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            profile = document_model.profile
            TestContext.add_project_memory(profile)
            with contextlib.closing(document_model):
                item_uuid = uuid.uuid4()
                data_item0 = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32), item_uuid=item_uuid)
                document_model.append_data_item(data_item0, project=profile.projects[0])
                data_item1 = DataItem.DataItem(numpy.ones((16, 16), numpy.uint32), item_uuid=item_uuid)
                document_model.append_data_item(data_item1, project=profile.projects[1])
                key0 = document_model.assign_variable_to_data_item(data_item0)
                key1 = document_model.assign_variable_to_data_item(data_item1)
                self.assertEqual(key0, document_model.data_items[0].r_var)
                self.assertEqual(key1, document_model.data_items[1].r_var)
            document_model = profile_context.create_document_model(auto_close=False)
            with contextlib.closing(document_model):
                variable_to_data_item_map = document_model.variable_to_data_item_map()
                self.assertEqual(key0, document_model.data_items[0].r_var)
                self.assertEqual(key1, document_model.data_items[1].r_var)

    def disabled_test_document_controller_disposes_threads(self):
        thread_count = threading.activeCount()
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
        gc.collect()
        self.assertEqual(threading.activeCount(), thread_count)

    def disabled_test_document_controller_leaks_no_memory(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(data=numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)

    def disabled_test_document_model_leaks_no_memory(self):
        # numpy min/max leak memory, so make sure they're used before testing data item
        data = numpy.zeros((2000, 2000))
        data.min(), data.max()
        # test memory usage
        memory_start = memory_usage_resource()
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
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
