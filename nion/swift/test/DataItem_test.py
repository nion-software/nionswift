# standard libraries
import contextlib
import copy
import datetime
import functools
import gc
import logging
import math
import threading
import time
import unittest
import weakref

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift import Application
from nion.swift import Facade
from nion.swift import Thumbnails
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Utility
from nion.ui import TestUI
from nion.utils import Recorder


Facade.initialize()


class TestDataItemClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_delete_data_item(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        weak_data_item = weakref.ref(data_item)
        data_item = None
        gc.collect()
        self.assertIsNone(weak_data_item())

    def test_copy_data_item(self):
        # NOTE: does not test computation, which is tested elsewhere
        source_data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        h, w = 8, 8
        data = numpy.zeros((h, w), numpy.uint32)
        data[h//2, w//2] = 1000  # data range (0, 1000)
        data_item = DataItem.DataItem(data)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        data_item.title = "data_item"
        data_item.timezone = "Europe/Athens"
        data_item.timezone_offset = "+0300"
        metadata = data_item.metadata
        metadata.setdefault("test", dict())["one"] = 1
        metadata.setdefault("test", dict())["two"] = 22
        data_item.metadata = metadata
        display_specifier.display.display_limits = (100, 900)
        display_specifier.display.add_graphic(Graphics.RectangleGraphic())
        data_item_copy = copy.deepcopy(data_item)
        display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item_copy)
        self.assertNotEqual(id(data), id(display_specifier2.data_item.data))
        # make sure properties and other items got copied
        #self.assertEqual(len(data_item_copy.properties), 19)  # not valid since properties only exist if in document
        self.assertIsNot(data_item.properties, data_item_copy.properties)
        # uuid should not match
        self.assertNotEqual(data_item.uuid, data_item_copy.uuid)
        # metadata get copied?
        self.assertEqual(len(data_item.metadata.get("test")), 2)
        self.assertIsNot(data_item.metadata.get("test"), data_item_copy.metadata.get("test"))
        # make sure display counts match
        self.assertEqual(len(display_specifier.data_item.displays), len(display_specifier2.data_item.displays))
        # tuples and strings are immutable, so test to make sure old/new are independent
        self.assertEqual(data_item.title, data_item_copy.title)
        self.assertEqual(data_item.timezone, data_item_copy.timezone)
        self.assertEqual(data_item.timezone_offset, data_item_copy.timezone_offset)
        data_item.title = "data_item1"
        self.assertNotEqual(data_item.title, data_item_copy.title)
        self.assertEqual(display_specifier.display.display_limits, display_specifier2.display.display_limits)
        display_specifier.display.display_limits = (150, 200)
        self.assertNotEqual(display_specifier.display.display_limits, display_specifier2.display.display_limits)
        # make sure dates are independent
        self.assertIsNot(data_item.created, data_item_copy.created)
        self.assertIsNot(display_specifier.data_item.created, display_specifier2.data_item.created)
        # make sure calibrations, computations, nor graphics are not shared.
        # there is a subtlety here: the dimensional_calibrations property accessor will return a copy of
        # the list each time it is called. store these in variables do make sure they don't get deallocated
        # and re-used immediately (causing a test failure).
        dimensional_calibrations = display_specifier.data_item.dimensional_calibrations
        dimensional_calibrations2 = display_specifier2.data_item.dimensional_calibrations
        self.assertNotEqual(id(dimensional_calibrations[0]), id(dimensional_calibrations2[0]))
        self.assertNotEqual(display_specifier.display.graphics[0], display_specifier2.display.graphics[0])

    def test_data_item_with_existing_computation_initializes_dependencies(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2a = DataItem.DataItem()
            data_item2a.ensure_data_source()
            computation = document_model.create_computation("target.xdata = resample_image(src.xdata, shape(12, 12)")
            computation.create_object("src", document_model.get_object_specifier(data_item2))
            document_model.append_data_item(data_item2)  # add this first
            document_model.append_data_item(data_item2a)  # add this second
            document_model.set_data_item_computation(data_item2a, computation)
            # verify
            self.assertEqual(document_model.get_source_data_items(data_item2a)[0], data_item2)

    def test_removing_data_item_with_computation_deinitializes_dependencies(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2a = DataItem.DataItem()
            data_item2a.ensure_data_source()
            computation = document_model.create_computation("target.xdata = resample_image(src.xdata, shape(12, 12)")
            computation.create_object("src", document_model.get_object_specifier(data_item2))
            document_model.append_data_item(data_item2)  # add this first
            document_model.append_data_item(data_item2a)  # add this second
            document_model.set_data_item_computation(data_item2a, computation)
            # verify
            self.assertEqual(document_model.get_source_data_items(data_item2a)[0], data_item2)
            self.assertEqual(document_model.get_dependent_data_items(data_item2)[0], data_item2a)
            # remove target
            document_model.remove_data_item(data_item2a)
            # verify
            self.assertEqual(len(document_model.get_dependent_data_items(data_item2)), 0)

    def test_removing_source_for_data_item_with_computation_deinitializes_dependencies(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2a = DataItem.DataItem()
            data_item2a.ensure_data_source()
            computation = document_model.create_computation("target.xdata = resample_image(src.xdata, shape(12, 12)")
            computation.create_object("src", document_model.get_object_specifier(data_item2))
            document_model.append_data_item(data_item2)  # add this first
            document_model.append_data_item(data_item2a)  # add this second
            document_model.set_data_item_computation(data_item2a, computation)
            # verify
            self.assertEqual(document_model.get_source_data_items(data_item2a)[0], data_item2)
            # remove source
            document_model.remove_data_item(data_item2)
            # verify
            self.assertEqual(len(document_model.get_source_data_items(data_item2a)), 0)

    def test_removing_data_item_removes_associated_computation(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # setup by adding data item and a dependent data item
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            data_item.displays[0].add_graphic(crop_region)
            data_item1 = document_model.get_crop_new(data_item, crop_region)
            # verify
            self.assertEqual(document_model.get_source_data_items(data_item1)[0], data_item)
            self.assertEqual(document_model.get_dependent_data_items(data_item)[0], data_item1)
            # remove dependent
            self.assertEqual(1, len(document_model.computations))
            document_model.remove_data_item(data_item1)
            self.assertEqual(0, len(document_model.computations))
            # verify
            self.assertEqual(len(document_model.get_dependent_data_items(data_item)), 0)

    def test_copy_data_item_properly_copies_computation(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2a = DataItem.DataItem()
            data_item2a.ensure_data_source()
            computation = document_model.create_computation("target.xdata = resample_image(src.xdata, shape(12, 12)")
            computation.create_object("src", document_model.get_object_specifier(data_item2))
            document_model.append_data_item(data_item2)  # add this first
            document_model.append_data_item(data_item2a)  # add this second
            document_model.set_data_item_computation(data_item2a, computation)
            # copy the dependent item
            data_item2a_copy = document_model.copy_data_item(data_item2a)
            # verify data source
            self.assertEqual(document_model.get_source_data_items(data_item2a_copy)[0], data_item2)
            self.assertIn(data_item2a_copy, document_model.get_dependent_data_items(data_item2))

    def test_copy_data_item_properly_copies_data_source_and_connects_it(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item2)  # add this first
            data_item2a = document_model.get_invert_new(data_item2)
            # copy the dependent item
            data_item2a_copy = document_model.copy_data_item(data_item2a)
            # verify data source
            self.assertEqual(document_model.resolve_object_specifier(document_model.get_data_item_computation(data_item2a).variables[0].variable_specifier).value.data_item, data_item2)
            self.assertEqual(document_model.resolve_object_specifier(document_model.get_data_item_computation(data_item2a_copy).variables[0].variable_specifier).value.data_item, data_item2)

    def test_copy_data_item_with_crop(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            source_data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25,0.25), (0.5,0.5)
            source_data_item.displays[0].add_graphic(crop_region)
            document_model.append_data_item(source_data_item)
            data_item = document_model.get_crop_new(source_data_item, crop_region)
            data_item_copy = document_model.copy_data_item(data_item)
            self.assertNotEqual(document_model.get_data_item_computation(data_item_copy), document_model.get_data_item_computation(data_item))
            document_model.recompute_all()
            self.assertEqual(document_model.resolve_object_specifier(document_model.get_data_item_computation(data_item_copy).variables[0].secondary_specifier).value,
                             document_model.resolve_object_specifier(document_model.get_data_item_computation(data_item).variables[0].secondary_specifier).value)

    def test_copy_data_item_with_transaction(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((4, 4), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            with document_model.item_transaction(data_item):
                with display_specifier.data_item.data_ref() as data_ref:
                    data_ref.master_data = numpy.ones((4, 4), numpy.uint32)
                    data_item_copy = copy.deepcopy(data_item)
            display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item_copy)
            with display_specifier.data_item.data_ref() as data_ref:
                with display_specifier2.data_item.data_ref() as data_copy_accessor:
                    self.assertEqual(data_copy_accessor.master_data.shape, (4, 4))
                    self.assertTrue(numpy.array_equal(data_ref.master_data, data_copy_accessor.master_data))
                    data_ref.master_data = numpy.ones((4, 4), numpy.uint32) + 1
                    self.assertFalse(numpy.array_equal(data_ref.master_data, data_copy_accessor.master_data))

    def test_clear_thumbnail_when_data_item_changed(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        self.assertTrue(display._display_cache.is_cached_value_dirty(display, "thumbnail_data"))
        with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.app.ui, display)) as thumbnail_source:
            thumbnail_source.recompute_data()
            self.assertIsNotNone(thumbnail_source.thumbnail_data)
            self.assertFalse(display._display_cache.is_cached_value_dirty(display, "thumbnail_data"))
            with display_specifier.data_item.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((8, 8), numpy.uint32)
            self.assertTrue(display._display_cache.is_cached_value_dirty(display, "thumbnail_data"))

    def test_thumbnail_2d_handles_small_dimension_without_producing_invalid_thumbnail(self):
        data_item = DataItem.DataItem(numpy.zeros((1, 300), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.app.ui, display)) as thumbnail_source:
            thumbnail_source.recompute_data()
            thumbnail_data = thumbnail_source.thumbnail_data
            self.assertTrue(functools.reduce(lambda x, y: x * y, thumbnail_data.shape) > 0)

    def test_thumbnail_2d_handles_nan_data(self):
        data = numpy.zeros((16, 16), numpy.float)
        data[:] = numpy.nan
        data_item = DataItem.DataItem(data)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.app.ui, display)) as thumbnail_source:
            thumbnail_source.recompute_data()
            self.assertIsNotNone(thumbnail_source.thumbnail_data)

    def test_thumbnail_2d_handles_inf_data(self):
        data = numpy.zeros((16, 16), numpy.float)
        data[:] = numpy.inf
        data_item = DataItem.DataItem(data)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.app.ui, display)) as thumbnail_source:
            thumbnail_source.recompute_data()
            self.assertIsNotNone(thumbnail_source.thumbnail_data)

    def test_thumbnail_1d(self):
        data_item = DataItem.DataItem(numpy.zeros((256), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.app.ui, display)) as thumbnail_source:
            thumbnail_source.recompute_data()
            self.assertIsNotNone(thumbnail_source.thumbnail_data)

    def test_thumbnail_1d_handles_nan_data(self):
        data = numpy.zeros((256), numpy.float)
        data[:] = numpy.nan
        data_item = DataItem.DataItem(data)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.app.ui, display)) as thumbnail_source:
            thumbnail_source.recompute_data()
            self.assertIsNotNone(thumbnail_source.thumbnail_data)

    def test_thumbnail_1d_handles_inf_data(self):
        data = numpy.zeros((256), numpy.float)
        data[:] = numpy.inf
        data_item = DataItem.DataItem(data)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.app.ui, display)) as thumbnail_source:
            thumbnail_source.recompute_data()
            self.assertIsNotNone(thumbnail_source.thumbnail_data)

    def test_thumbnail_marked_dirty_when_source_data_changed(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.double))
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            document_model.append_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_inverted)
            document_model.recompute_all()
            data_item_inverted_display = inverted_display_specifier.display
            with contextlib.closing(Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.app.ui, data_item_inverted_display)) as thumbnail_source:
                thumbnail_source.recompute_data()
                thumbnail_source.thumbnail_data
                # here the data should be computed and the thumbnail should not be dirty
                self.assertFalse(data_item_inverted_display._display_cache.is_cached_value_dirty(data_item_inverted_display, "thumbnail_data"))
                # now the source data changes and the inverted data needs computing.
                # the thumbnail should also be dirty.
                with display_specifier.data_item.data_ref() as data_ref:
                    data_ref.master_data = data_ref.master_data + 1.0
                document_model.recompute_all()
                self.assertTrue(data_item_inverted_display._display_cache.is_cached_value_dirty(data_item_inverted_display, "thumbnail_data"))

    def test_delete_nested_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item2)  # add this first
            data_item2a = document_model.get_invert_new(data_item2)
            data_item2a1 = document_model.get_invert_new(data_item2a)
            # remove item (and implicitly its dependency)
            document_model.remove_data_item(data_item2a)
            self.assertEqual(len(document_model.data_items), 1)

    def test_copy_data_item_with_display_and_graphics_should_copy_graphics(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        rect_graphic = Graphics.RectangleGraphic()
        display_specifier.display.add_graphic(rect_graphic)
        self.assertEqual(len(display_specifier.display.graphics), 1)
        data_item_copy = copy.deepcopy(data_item)
        display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item_copy)
        self.assertEqual(len(display_specifier2.display.graphics), 1)

    def test_deepcopy_data_item_should_produce_new_uuid(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        data_item_copy = copy.deepcopy(data_item)
        self.assertNotEqual(data_item.uuid, data_item_copy.uuid)

    def test_deepcopy_data_item_should_produce_new_data(self):
        data = numpy.zeros((8, 8), numpy.uint32)
        data_item = DataItem.DataItem(data)
        data_item_copy = copy.deepcopy(data_item)
        data_item_snap = data_item.snapshot()
        self.assertTrue(numpy.array_equal(data_item.data, data))
        self.assertTrue(numpy.array_equal(data_item.data, data_item_copy.data))
        self.assertTrue(numpy.array_equal(data_item.data, data_item_snap.data))
        data[0, 0] = 1
        self.assertTrue(numpy.array_equal(data_item.data, data))
        self.assertFalse(numpy.array_equal(data_item.data, data_item_copy.data))
        self.assertFalse(numpy.array_equal(data_item.data, data_item_snap.data))

    def test_snapshot_data_item_should_not_copy_computation(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data1 = (numpy.random.randn(8, 8) * 100).astype(numpy.int32)
            data2 = (numpy.random.randn(8, 8) * 100).astype(numpy.int32)
            data_item = DataItem.DataItem(data1)
            document_model.append_data_item(data_item)
            data_item_copy = document_model.get_crop_new(data_item)
            document_model.recompute_all()
            data_item_snap = document_model.get_snapshot_new(data_item_copy)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item.data, data1))
            self.assertTrue(numpy.array_equal(data_item_copy.data, data1[2:6, 2:6]))
            self.assertTrue(numpy.array_equal(data_item_snap.data, data1[2:6, 2:6]))
            data_item.set_data(data2)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(data_item.data, data2))
            self.assertTrue(numpy.array_equal(data_item_copy.data, data2[2:6, 2:6]))
            self.assertTrue(numpy.array_equal(data_item_snap.data, data1[2:6, 2:6]))
            self.assertIsNotNone(document_model.get_data_item_computation(data_item_copy))
            self.assertIsNone(document_model.get_data_item_computation(data_item_snap))

    def test_copy_data_item_should_raise_exception(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        with self.assertRaises(AssertionError):
            copy.copy(data_item)

    def test_appending_data_item_should_trigger_recompute(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            document_model.recompute_all()
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted_data_item)
            self.assertFalse(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)

    def test_data_range(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        # test scalar
        xx, yy = numpy.meshgrid(numpy.linspace(0,1,256), numpy.linspace(0,1,256))
        with display_specifier.data_item.data_ref() as data_ref:
            data_ref.master_data = 50 * (xx + yy) + 25
            data_range = display_specifier.display.get_calculated_display_values(True).data_range
            self.assertEqual(data_range, (25, 125))
            # now test complex
            data_ref.master_data = numpy.zeros((8, 8), numpy.complex64)
            xx, yy = numpy.meshgrid(numpy.linspace(0,1,256), numpy.linspace(0,1,256))
            data_ref.master_data = (2 + xx * 10) + 1j * (3 + yy * 10)
        data_range = display_specifier.display.get_calculated_display_values(True).data_range
        data_min = math.log(math.sqrt(2*2 + 3*3))
        data_max = math.log(math.sqrt(12*12 + 13*13))
        self.assertEqual(int(data_min*1e6), int(data_range[0]*1e6))
        self.assertEqual(int(data_max*1e6), int(data_range[1]*1e6))

    def test_data_range_gets_updated_after_data_ref_data_updated(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        self.assertEqual(data_item.displays[0].get_calculated_display_values(True).data_range, (0, 0))
        with data_item.data_ref() as data_ref:
            data_ref.data[:] = 1
            data_ref.data_updated()
        self.assertEqual(data_item.displays[0].get_calculated_display_values(True).data_range, (1, 1))

    def test_removing_dependent_data_item_with_graphic(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item.displays[0].add_graphic(Graphics.RectangleGraphic())
            document_model.append_data_item(data_item)
            document_model.get_crop_new(data_item)
            # should remove properly when shutting down.

    def test_removing_derived_data_item_updates_dependency_info_on_source(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "1"
            document_model.append_data_item(data_item1)
            data_item1a = document_model.get_invert_new(data_item1)
            data_item1a.title = "1a"
            self.assertEqual(len(document_model.get_dependent_data_items(data_item1)), 1)
            document_model.remove_data_item(data_item1a)
            self.assertEqual(len(document_model.get_dependent_data_items(data_item1)), 0)

    def test_recomputing_data_should_not_leave_it_loaded(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted_data_item)
            document_model.recompute_all()
            self.assertFalse(inverted_display_specifier.data_item.is_data_loaded)

    def test_loading_dependent_data_should_not_cause_source_data_to_load(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_inverted)
            # begin checks
            document_model.recompute_all()
            self.assertFalse(display_specifier.data_item.is_data_loaded)
            with inverted_display_specifier.data_item.data_ref() as d:
                self.assertFalse(display_specifier.data_item.is_data_loaded)
            self.assertFalse(display_specifier.data_item.is_data_loaded)

    def test_modifying_source_data_should_trigger_data_changed_notification_from_dependent_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_inverted)
            document_model.recompute_all()
            data_changed_ref = [False]
            def data_item_content_changed():
                data_changed_ref[0] = True
            with contextlib.closing(data_item_inverted.library_item_changed_event.listen(data_item_content_changed)):
                display_specifier.data_item.set_data(numpy.ones((8, 8), numpy.uint32))
                document_model.recompute_all()
                self.assertTrue(data_changed_ref)
                self.assertFalse(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)

    def test_modifying_source_data_should_trigger_data_item_stale_from_dependent_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            document_model.append_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted_data_item)
            document_model.recompute_all()
            display_specifier.data_item.set_data(numpy.ones((8, 8), numpy.uint32))
            self.assertTrue(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)

    def test_modifying_source_data_should_queue_recompute_in_document_model(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted_data_item)
            document_model.recompute_all()
            display_specifier.data_item.set_data(numpy.ones((8, 8), numpy.uint32))
            self.assertTrue(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)

    def test_is_data_stale_should_propagate_to_data_items_dependent_on_source(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.full((2, 2), 2, numpy.int32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted_data_item)
            inverted2_data_item = document_model.get_invert_new(inverted_data_item)
            inverted2_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted2_data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)
            self.assertFalse(document_model.get_data_item_computation(inverted2_display_specifier.data_item).needs_update)
            display_specifier.data_item.set_data(numpy.ones((2, 2), numpy.int32))
            self.assertTrue(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)
            self.assertFalse(document_model.get_data_item_computation(inverted2_display_specifier.data_item).needs_update)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)
            self.assertFalse(document_model.get_data_item_computation(inverted2_display_specifier.data_item).needs_update)

    def test_data_item_that_is_recomputed_notifies_listeners_of_a_single_data_change(self):
        # this test ensures that doing a recompute_data is efficient and doesn't produce
        # extra data_item_content_changed messages.
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted_data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)
            data_changed_ref = [0]
            def data_item_content_changed():
                data_changed_ref[0] += 1
            with contextlib.closing(inverted_data_item.library_item_changed_event.listen(data_item_content_changed)):
                display_specifier.data_item.set_data(numpy.ones((8, 8), numpy.uint32))
                self.assertTrue(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)
                self.assertEqual(data_changed_ref[0], 0)
                document_model.recompute_all()
                self.assertFalse(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)
                self.assertEqual(data_changed_ref[0], 1)

    def test_adding_removing_data_item_with_crop_computation_updates_graphics(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item_crop = document_model.get_crop_new(data_item, crop_region)
            self.assertEqual(len(display_specifier.display.graphics), 1)
            document_model.remove_data_item(data_item_crop)
            self.assertEqual(len(display_specifier.display.graphics), 0)

    def disabled_test_adding_removing_crop_computation_to_existing_data_item_updates_graphics(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item_crop = document_model.get_crop_new(data_item, crop_region)
            self.assertEqual(len(display_specifier.display.graphics), 1)
            document_model.set_data_item_computation(data_item, None)
            # the associated graphic should now be deleted.
            self.assertEqual(len(display_specifier.display.graphics), 0)

    def test_updating_computation_graphic_property_notifies_data_item(self):
        display_changed_ref = [False]
        def display_changed():
            display_changed_ref[0] = True
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            with contextlib.closing(display_specifier.display.display_changed_event.listen(display_changed)):
                document_model.get_crop_new(data_item, crop_region)
                display_changed_ref[0] = False
                display_specifier.display.graphics[0].bounds = ((0.2,0.3), (0.8,0.7))
                self.assertTrue(display_changed_ref[0])

    # necessary to make inspector display updated values properly
    def test_updating_computation_graphic_property_with_same_value_notifies_data_item(self):
        display_changed_ref = [False]
        def display_changed():
            display_changed_ref[0] = True
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.displays[0].add_graphic(crop_region)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            document_model.append_data_item(data_item)
            with contextlib.closing(display_specifier.display.display_changed_event.listen(display_changed)):
                document_model.get_crop_new(data_item, crop_region)
                display_specifier.display.graphics[0].bounds = ((0.2,0.3), (0.8,0.7))
                display_changed_ref[0] = False
                display_specifier.display.graphics[0].bounds = ((0.2,0.3), (0.8,0.7))
                self.assertTrue(display_changed_ref[0])

    def test_snapshot_should_copy_raw_metadata(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        metadata = data_item.metadata
        metadata.setdefault("test", dict())["one"] = 1
        data_item.metadata = metadata
        data_item_copy = data_item.snapshot()
        self.assertEqual(data_item_copy.metadata.get("test")["one"], 1)

    def test_snapshot_should_copy_timezone(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        data_item.timezone = "Europe/Athens"
        data_item.timezone_offset = "+0300"
        data_item_copy = data_item.snapshot()
        self.assertEqual(data_item.timezone, data_item_copy.timezone)
        self.assertEqual(data_item.timezone_offset, data_item_copy.timezone_offset)

    def test_data_item_allows_adding_of_two_data_sources(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item2)
            document_model.get_cross_correlate_new(data_item1, data_item2)

    def test_region_graphic_gets_added_to_existing_display(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertEqual(len(display_specifier.display.graphics), 0)
            display_specifier.display.add_graphic(Graphics.PointGraphic())
            self.assertEqual(len(display_specifier.display.graphics), 1)

    # necessary to make inspector display updated values properly
    def test_adding_region_generates_display_changed(self):
        display_changed_ref = [False]
        def display_changed():
            display_changed_ref[0] = True
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            with contextlib.closing(display_specifier.display.display_changed_event.listen(display_changed)):
                crop_region = Graphics.RectangleGraphic()
                display_specifier.display.add_graphic(crop_region)
                self.assertTrue(display_changed_ref[0])
                display_changed_ref[0] = False
                display_specifier.display.remove_graphic(crop_region)
                self.assertTrue(display_changed_ref[0])

    def test_connecting_data_source_updates_dependent_data_items_property_on_source(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            # configure the dependent item
            data_item2 = document_model.get_invert_new(data_item)
            # make sure the dependency list is updated
            self.assertEqual(document_model.get_dependent_data_items(data_item), [data_item2])

    def test_begin_transaction_also_begins_transaction_for_dependent_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            # configure the dependent item
            data_item2 = document_model.get_invert_new(data_item)
            # begin the transaction
            with document_model.item_transaction(data_item):
                self.assertTrue(data_item.in_transaction_state)
                self.assertTrue(data_item2.in_transaction_state)
            self.assertFalse(data_item.in_transaction_state)
            self.assertFalse(data_item2.in_transaction_state)

    def test_data_item_added_to_data_item_under_transaction_becomes_transacted_too(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            # begin the transaction
            with document_model.item_transaction(data_item):
                # configure the dependent item
                data_item2 = document_model.get_invert_new(data_item)
                # check to make sure it is under transaction
                self.assertTrue(data_item.in_transaction_state)
                self.assertTrue(data_item2.in_transaction_state)
            self.assertFalse(data_item.in_transaction_state)
            self.assertFalse(data_item2.in_transaction_state)

    def test_data_item_added_to_data_item_under_transaction_configures_dependency(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            # begin the transaction
            with document_model.item_transaction(data_item):
                data_item_crop1 = document_model.get_crop_new(data_item, crop_region)
                # change the bounds of the graphic
                display_specifier.display.graphics[0].bounds = ((0.31, 0.32), (0.6, 0.4))
                # make sure it is connected to the crop computation
                bounds = crop_region.bounds
                self.assertAlmostEqual(bounds[0][0], 0.31)
                self.assertAlmostEqual(bounds[0][1], 0.32)
                self.assertAlmostEqual(bounds[1][0], 0.6)
                self.assertAlmostEqual(bounds[1][1], 0.4)

    def test_data_item_under_transaction_added_to_document_does_write_delay(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            # begin the transaction
            with document_model.item_transaction(data_item):
                document_model.append_data_item(data_item)
                persistent_storage = data_item.persistent_storage
                self.assertTrue(persistent_storage.write_delayed)

    def test_data_item_added_to_live_data_item_becomes_live_and_unlive_based_on_parent_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            with document_model.data_item_live(data_item):
                data_item_crop1 = document_model.get_invert_new(data_item)
                self.assertTrue(data_item_crop1.is_live)
            self.assertFalse(data_item.is_live)
            self.assertFalse(data_item_crop1.is_live)

    def slow_test_dependent_data_item_removed_while_live_data_item_becomes_unlive(self):
        # an intermittent race condition. run several times. see the changes that accompanied
        # the addition of this code.
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            def live_it(n):
                for _ in range(n):
                    with document_model.data_item_live(data_item):
                        pass
            threading.Thread(target=live_it, args=(1000, )).start()
            with document_model.data_item_live(data_item):
                for _ in range(100):
                    data_item_inverted = document_model.get_invert_new(data_item)
                    document_model.remove_data_item(data_item_inverted)

    def test_changing_metadata_or_data_does_not_mark_the_data_as_stale(self):
        # changing metadata or data will override what has been computed
        # from the data sources, if there are any.
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(src_data_item)
            data_item = document_model.get_invert_new(src_data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(display_specifier.data_item).needs_update)
            display_specifier.data_item.set_data(numpy.zeros((8, 8), numpy.uint32))
            display_specifier.data_item.set_intensity_calibration(Calibration.Calibration())
            self.assertFalse(document_model.get_data_item_computation(display_specifier.data_item).needs_update)

    def test_changing_metadata_or_data_does_not_mark_the_data_as_stale_for_data_item_with_data_source(self):
        # changing metadata or data will override what has been computed
        # from the data sources, if there are any.
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            copied_data_item = document_model.get_invert_new(data_item)
            copied_display_specifier = DataItem.DisplaySpecifier.from_data_item(copied_data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(copied_display_specifier.data_item).needs_update)
            copied_display_specifier.data_item.set_intensity_calibration(Calibration.Calibration())
            self.assertFalse(document_model.get_data_item_computation(copied_display_specifier.data_item).needs_update)

    def test_removing_computation_should_not_mark_the_data_as_stale(self):
        # is this test valid any more?
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            copied_data_item = document_model.get_invert_new(data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(copied_data_item).needs_update)
            document_model.set_data_item_computation(copied_data_item, None)
            document_model.recompute_all()
            self.assertIsNotNone(copied_data_item.data)

    def test_changing_computation_should_mark_the_data_as_stale(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            copied_data_item = document_model.get_gaussian_blur_new(data_item)
            copied_display_specifier = DataItem.DisplaySpecifier.from_data_item(copied_data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(copied_display_specifier.data_item).needs_update)
            document_model.get_data_item_computation(copied_data_item).variables[1].value = 0.1
            self.assertTrue(document_model.get_data_item_computation(copied_display_specifier.data_item).needs_update)

    def test_reloading_stale_data_should_still_be_stale(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted_data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)
            self.assertAlmostEqual(inverted_display_specifier.data_item.data[0, 0], -1.0)
            # now the source data changes and the inverted data needs computing.
            with display_specifier.data_item.data_ref() as data_ref:
                data_ref.master_data = data_ref.master_data + 2.0
            self.assertTrue(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)
            # data is now unloaded and stale.
            self.assertFalse(inverted_display_specifier.data_item.is_data_loaded)
            # don't recompute
            self.assertAlmostEqual(inverted_display_specifier.data_item.data[0, 0], -1.0)
            # data should still be stale
            self.assertTrue(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)

    def test_recomputing_data_gives_correct_result(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_inverted)
            document_model.recompute_all()
            self.assertAlmostEqual(inverted_display_specifier.data_item.data[0, 0], -1.0)
            # now the source data changes and the inverted data needs computing.
            with display_specifier.data_item.data_ref() as data_ref:
                data_ref.master_data = data_ref.master_data + 2.0
            document_model.recompute_all()
            self.assertAlmostEqual(inverted_display_specifier.data_item.data[0, 0], -3.0)

    def test_recomputing_data_after_cached_data_is_called_gives_correct_result(self):
        # verify that this works, the more fundamental test is in test_reloading_stale_data_should_still_be_stale
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted_data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(inverted_display_specifier.data_item).needs_update)
            self.assertAlmostEqual(inverted_display_specifier.data_item.data[0, 0], -1.0)
            # now the source data changes and the inverted data needs computing.
            with display_specifier.data_item.data_ref() as data_ref:
                data_ref.master_data = data_ref.master_data + 2.0
            # verify the actual data values are still stale
            self.assertAlmostEqual(inverted_display_specifier.data_item.data[0, 0], -1.0)
            # recompute and verify the data values are valid
            document_model.recompute_all()
            self.assertAlmostEqual(inverted_display_specifier.data_item.data[0, 0], -3.0)

    def test_modifying_data_item_modified_property_works(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            modified = datetime.datetime(2000, 1, 1)
            data_item._set_modified(modified)
            self.assertEqual(data_item.modified, modified)

    def test_modifying_data_item_metadata_updates_modified(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            data_item._set_modified(datetime.datetime(2000, 1, 1))
            modified = data_item.modified
            data_item.metadata = data_item.metadata
            self.assertGreater(data_item.modified, modified)

    def test_changing_property_on_display_updates_modified(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            data_item._set_modified(datetime.datetime(2000, 1, 1))
            modified = data_item.modified
            data_item.displays[0].dimensional_calibration_style = "relative-top-left"
            self.assertGreater(data_item.modified, modified)

    def test_changing_data_on_data_item_updates_modified(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            data_item._set_modified(datetime.datetime(2000, 1, 1))
            modified = data_item.modified
            data_item.set_data(numpy.zeros((2, 2)))
            self.assertGreater(data_item.modified, modified)

    def test_changing_data_updates_xdata_timestamp(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            timestamp = datetime.datetime(2000, 1, 1)
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((2, 2)), timestamp=timestamp)
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            data_item.set_data(numpy.zeros((2, 2)))
            self.assertGreater(data_item.xdata.timestamp, timestamp)

    def test_data_item_in_transaction_does_not_write_until_end_of_transaction(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            with document_model.item_transaction(data_item):
                document_model.append_data_item(data_item)
                self.assertEqual(len(memory_persistent_storage_system.data.keys()), 0)
            self.assertEqual(len(memory_persistent_storage_system.data.keys()), 1)

    def test_extra_changing_data_item_session_id_in_transaction_does_not_result_in_duplicated_data_items(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            with document_model.item_transaction(data_item):
                data_item.session_id = "20000630-150200"
                document_model.append_data_item(data_item)
                self.assertEqual(len(memory_persistent_storage_system.data.keys()), 0)
                data_item.session_id = "20000630-150201"
            self.assertEqual(len(memory_persistent_storage_system.data.keys()), 1)

    def test_changing_data_item_session_id_in_transaction_does_not_result_in_duplicated_data_items(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            with document_model.item_transaction(data_item):
                data_item.session_id = "20000630-150200"
                document_model.append_data_item(data_item)
            self.assertEqual(len(memory_persistent_storage_system.data.keys()), 1)
            with document_model.item_transaction(data_item):
                data_item.session_id = "20000630-150201"
            self.assertEqual(len(memory_persistent_storage_system.data.keys()), 1)

    def test_data_item_added_to_library_gets_current_session(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            document_model.append_data_item(data_item)
            self.assertEqual(data_item.session_id, document_model.session_id)

    def test_data_item_gets_current_session_when_data_is_modified(self):
        document_model = DocumentModel.DocumentModel()
        document_model.session_id = '20000630-150200'
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            data_item.category = 'temporary'
            document_model.append_data_item(data_item)
            document_model.start_new_session()
            self.assertNotEqual(data_item.session_id, document_model.session_id)
            data_item.set_data(numpy.ones((4, 4)))
            self.assertEqual(data_item.session_id, document_model.session_id)

    def test_data_item_keeps_session_unmodified_when_metadata_is_changed(self):
        document_model = DocumentModel.DocumentModel()
        document_model.session_id = '20000630-150200'
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            data_item.category = 'temporary'
            document_model.append_data_item(data_item)
            document_model.start_new_session()
            self.assertNotEqual(data_item.session_id, document_model.session_id)
            data_item.title = 'new title'
            self.assertEqual(data_item.session_id, '20000630-150200')

    def test_data_item_copy_copies_session_info(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            session_metadata = data_item.session_metadata
            session_metadata['site'] = 'Home'
            data_item.session_metadata = session_metadata
            document_model.append_data_item(data_item)
            data_item_copy = copy.deepcopy(data_item)
            document_model.append_data_item(data_item_copy)
            self.assertEqual(data_item_copy.session_metadata, data_item.session_metadata)

    def test_processed_data_item_has_source_data_modified_equal_to_sources_data_modifed(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            document_model.append_data_item(src_data_item)
            time.sleep(0.01)
            data_item = document_model.get_invert_new(src_data_item)
            document_model.recompute_all()
            self.assertIsNotNone(src_data_item.data_modified)
            self.assertGreaterEqual(data_item.data_modified, src_data_item.data_modified)

    def test_processed_data_item_has_source_data_modified_equal_to_sources_created_when_sources_data_modified_is_none(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            src_data_item.data_modified = None
            document_model.append_data_item(src_data_item)
            time.sleep(0.01)
            data_item = document_model.get_invert_new(src_data_item)
            document_model.recompute_all()
            self.assertGreaterEqual(data_item.data_modified, src_data_item.created)

    def test_transaction_does_not_cascade_to_data_item_refs(self):
        # no reason to cascade since there is no high cost data to be loaded for aggregate data items
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((4, 4))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((4, 4))))
            master_data_item = DataItem.CompositeLibraryItem()
            master_data_item.append_data_item(document_model.data_items[0])
            master_data_item.append_data_item(document_model.data_items[1])
            document_model.append_data_item(master_data_item)
            self.assertFalse(master_data_item.in_transaction_state)
            self.assertFalse(document_model.data_items[0].in_transaction_state)
            self.assertFalse(document_model.data_items[1].in_transaction_state)
            with document_model.item_transaction(master_data_item):
                self.assertTrue(master_data_item.in_transaction_state)
                self.assertFalse(document_model.data_items[0].in_transaction_state)
                self.assertFalse(document_model.data_items[1].in_transaction_state)

    def test_increment_data_ref_counts_cascades_to_data_item_refs(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((4, 4))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((4, 4))))
            master_data_item = DataItem.CompositeLibraryItem()
            master_data_item.append_data_item(document_model.data_items[0])
            master_data_item.append_data_item(document_model.data_items[1])
            document_model.append_data_item(master_data_item)
            self.assertFalse(document_model.data_items[0].is_data_loaded)
            self.assertFalse(document_model.data_items[1].is_data_loaded)
            master_data_item.increment_display_ref_count()
            self.assertTrue(document_model.data_items[0].is_data_loaded)
            self.assertTrue(document_model.data_items[1].is_data_loaded)
            master_data_item.decrement_display_ref_count()
            self.assertFalse(document_model.data_items[0].is_data_loaded)
            self.assertFalse(document_model.data_items[1].is_data_loaded)

    def test_adding_data_item_twice_to_composite_item_fails(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((4, 4)))
            document_model.append_data_item(data_item)
            master_data_item = DataItem.CompositeLibraryItem()
            master_data_item.append_data_item(data_item)
            with self.assertRaises(Exception):
                master_data_item.append_data_item(data_item)

    def test_dependent_calibration(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.data_item.set_dimensional_calibration(0, Calibration.Calibration(3.0, 2.0, u"x"))
            display_specifier.data_item.set_dimensional_calibration(1, Calibration.Calibration(3.0, 2.0, u"x"))
            self.assertEqual(len(display_specifier.data_item.dimensional_calibrations), 2)
            data_item_copy = document_model.get_invert_new(data_item)
            display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item_copy)
            document_model.recompute_all()
            dimensional_calibrations = display_specifier2.data_item.dimensional_calibrations
            self.assertEqual(len(dimensional_calibrations), 2)
            self.assertEqual(int(dimensional_calibrations[0].offset), 3)
            self.assertEqual(int(dimensional_calibrations[0].scale), 2)
            self.assertEqual(dimensional_calibrations[0].units, "x")
            self.assertEqual(int(dimensional_calibrations[1].offset), 3)
            self.assertEqual(int(dimensional_calibrations[1].scale), 2)
            self.assertEqual(dimensional_calibrations[1].units, "x")
            fft_data_item = document_model.get_fft_new(data_item)
            document_model.recompute_all()
            dimensional_calibrations = fft_data_item.dimensional_calibrations
            self.assertEqual(int(dimensional_calibrations[0].offset), 0)
            self.assertEqual(dimensional_calibrations[0].units, "1/x")
            self.assertEqual(int(dimensional_calibrations[1].offset), 0)
            self.assertEqual(dimensional_calibrations[1].units, "1/x")

    def test_double_dependent_calibration(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            data_item2 = document_model.get_invert_new(data_item)
            data_item3 = document_model.get_invert_new(data_item2)
            display_specifier3 = DataItem.DisplaySpecifier.from_data_item(data_item3)
            document_model.recompute_all()
            self.assertIsNotNone(display_specifier3.data_item.dimensional_calibrations)

    def test_spatial_calibration_on_rgb(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertTrue(Image.is_shape_and_dtype_2d(display_specifier.data_item.data_shape, display_specifier.data_item.data_dtype))
        self.assertTrue(Image.is_shape_and_dtype_rgba(display_specifier.data_item.data_shape, display_specifier.data_item.data_dtype))
        self.assertEqual(len(display_specifier.data_item.dimensional_calibrations), 2)

    def test_metadata_is_valid_when_a_data_item_has_no_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.double))
            document_model.append_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_inverted)
            self.assertIsInstance(inverted_display_specifier.data_item.metadata, dict)

    def test_data_item_recorder_records_intensity_calibration_changes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.double))
            document_model.append_data_item(data_item)
            data_item_clone = data_item.clone()
            data_item_clone_recorder = Recorder.Recorder(data_item_clone)
            data_item_clone.set_intensity_calibration(Calibration.Calibration(units="mmm"))
            data_item_clone_recorder.apply(data_item)
            self.assertEqual(data_item.intensity_calibration.units, data_item_clone.intensity_calibration.units)

    def test_data_item_recorder_records_title_changes(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.double))
            document_model.append_data_item(data_item)
            data_item_clone = data_item.clone()
            data_item_clone_recorder = Recorder.Recorder(data_item_clone)
            data_item_clone.title = "Firefly"
            data_item_clone_recorder.apply(data_item)
            self.assertEqual(data_item.title, data_item_clone.title)

    def test_timezone_is_stored_on_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            try:
                Utility.local_timezone_override = ["Europe/Athens"]
                Utility.local_utcoffset_override = [180]
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                self.assertEqual(data_item.timezone, "Europe/Athens")
                self.assertEqual(data_item.timezone_offset, "+0300")
            finally:
                Utility.local_timezone_override = None
                Utility.local_utcoffset_override = None

    def test_timezone_is_encapsulated_in_data_and_metadata(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            try:
                Utility.local_timezone_override = ["Europe/Athens"]
                Utility.local_utcoffset_override = [180]
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                xdata = data_item.xdata
                self.assertEqual(xdata.timezone, "Europe/Athens")
                self.assertEqual(xdata.timezone_offset, "+0300")
                Utility.local_timezone_override = ["America/Los_Angeles"]
                Utility.local_utcoffset_override = [-420]
                data_item.set_data(numpy.zeros((10, 10)))
                xdata = data_item.xdata
                self.assertEqual(xdata.timezone, "America/Los_Angeles")
                self.assertEqual(xdata.timezone_offset, "-0700")
            finally:
                Utility.local_timezone_override = None
                Utility.local_utcoffset_override = None

    # modify property/item/relationship on data source, display, region, etc.
    # copy or snapshot

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
