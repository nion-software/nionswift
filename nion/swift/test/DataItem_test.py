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
from nion.swift import DataItemThumbnailWidget
from nion.swift import Facade
from nion.swift import Thumbnails
from nion.swift.model import DataItem
from nion.swift.model import DynamicString
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.swift.model import Utility
from nion.swift.test import TestContext
from nion.ui import TestUI
from nion.utils import Recorder


Facade.initialize()


def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


class TestDataItemClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        TestContext.end_leaks(self)

    def disabled_test_delete_data_item(self):  # does not pass leak tests
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        weak_data_item = weakref.ref(data_item)
        data_item = None
        gc.collect()
        self.assertIsNone(weak_data_item())

    def test_copy_data_item(self):
        # NOTE: does not test computation, which is tested elsewhere
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            h, w = 8, 8
            data = numpy.zeros((h, w), numpy.uint32)
            data[h//2, w//2] = 1000  # data range (0, 1000)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item.title = "data_item"
            data_item.timezone = "Europe/Athens"
            data_item.timezone_offset = "+0300"
            metadata = data_item.metadata
            metadata.setdefault("test", dict())["one"] = 1
            metadata.setdefault("test", dict())["two"] = 22
            data_item.metadata = metadata
            display_item.display_data_channels[0].display_limits = (100, 900)
            display_item.add_graphic(Graphics.RectangleGraphic())
            display_item2 = document_model.deepcopy_display_item(display_item)
            data_item_copy = display_item2.data_item
            self.assertNotEqual(id(data), id(data_item_copy.data))
            # make sure properties and other items got copied
            #self.assertEqual(len(data_item_copy.properties), 19)  # not valid since properties only exist if in document
            self.assertIsNot(data_item.properties, data_item_copy.properties)
            # uuid should not match
            self.assertNotEqual(data_item.uuid, data_item_copy.uuid)
            # metadata get copied?
            self.assertEqual(len(data_item.metadata.get("test")), 2)
            self.assertIsNot(data_item.metadata.get("test"), data_item_copy.metadata.get("test"))
            # make sure display counts match
            self.assertIsNotNone(display_item)
            self.assertIsNotNone(display_item2)
            # tuples and strings are immutable, so test to make sure old/new are independent
            self.assertEqual(data_item.title, data_item_copy.title)
            self.assertEqual(data_item.timezone, data_item_copy.timezone)
            self.assertEqual(data_item.timezone_offset, data_item_copy.timezone_offset)
            data_item.title = "data_item1"
            self.assertNotEqual(data_item.title, data_item_copy.title)
            self.assertEqual(display_item.display_data_channels[0].display_limits, display_item2.display_data_channels[0].display_limits)
            display_item.display_data_channels[0].display_limits = (150, 200)
            self.assertNotEqual(display_item.display_data_channels[0].display_limits, display_item2.display_data_channels[0].display_limits)
            # make sure dates are independent
            self.assertIsNot(data_item.created, data_item_copy.created)
            # make sure calibrations, computations, nor graphics are not shared.
            # there is a subtlety here: the dimensional_calibrations property accessor will return a copy of
            # the list each time it is called. store these in variables do make sure they don't get deallocated
            # and re-used immediately (causing a test failure).
            dimensional_calibrations = data_item.dimensional_calibrations
            dimensional_calibrations2 = data_item_copy.dimensional_calibrations
            self.assertNotEqual(id(dimensional_calibrations[0]), id(dimensional_calibrations2[0]))
            self.assertNotEqual(display_item.graphics[0], display_item2.graphics[0])

    def test_setting_title_on_data_item_sets_title_on_data_source(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            data_item.title = "123"
            data_item.caption = "234"
            data_item.description = "345"
            self.assertEqual("123", data_item.title)
            self.assertEqual("234", data_item.caption)
            self.assertEqual("345", data_item.description)

    def test_setting_title_on_data_item_with_no_data_source_works_after_adding_data_source(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            data_item.title = "123"
            self.assertEqual("123", data_item.title)
            data_item.set_data(numpy.zeros((8, 8)))
            data_item.title = "456"
            self.assertEqual("456", data_item.title)

    def test_data_item_with_existing_computation_initializes_dependencies(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2a = DataItem.DataItem()
            document_model.append_data_item(data_item2)  # add this first
            document_model.append_data_item(data_item2a)  # add this second
            computation = document_model.create_computation("target.xdata = resample_image(src.xdata, shape(12, 12)")
            computation.create_input_item("src", Symbolic.make_item(data_item2))
            document_model.set_data_item_computation(data_item2a, computation)
            # verify
            self.assertEqual(document_model.get_source_data_items(data_item2a)[0], data_item2)

    def test_removing_data_item_with_computation_deinitializes_dependencies(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2a = DataItem.DataItem()
            document_model.append_data_item(data_item2)  # add this first
            document_model.append_data_item(data_item2a)  # add this second
            computation = document_model.create_computation("target.xdata = resample_image(src.xdata, shape(12, 12)")
            computation.create_input_item("src", Symbolic.make_item(data_item2))
            document_model.set_data_item_computation(data_item2a, computation)
            # verify
            self.assertEqual(document_model.get_source_data_items(data_item2a)[0], data_item2)
            self.assertEqual(document_model.get_dependent_data_items(data_item2)[0], data_item2a)
            # remove target
            document_model.remove_data_item(data_item2a)
            # verify
            self.assertEqual(len(document_model.get_dependent_data_items(data_item2)), 0)

    def test_removing_source_for_data_item_with_computation_deinitializes_dependencies(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2a = DataItem.DataItem()
            document_model.append_data_item(data_item2)  # add this first
            document_model.append_data_item(data_item2a)  # add this second
            computation = document_model.create_computation("target.xdata = resample_image(src.xdata, shape(12, 12)")
            computation.create_input_item("src", Symbolic.make_item(data_item2))
            document_model.set_data_item_computation(data_item2a, computation)
            # verify
            self.assertEqual(document_model.get_source_data_items(data_item2a)[0], data_item2)
            # remove source
            document_model.remove_data_item(data_item2)
            # verify
            self.assertEqual(len(document_model.get_source_data_items(data_item2a)), 0)

    def test_removing_data_item_removes_associated_computation(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # setup by adding data item and a dependent data item
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            display_item.add_graphic(crop_region)
            data_item1 = document_model.get_crop_new(display_item, display_item.data_item, crop_region)
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
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2a = DataItem.DataItem()
            document_model.append_data_item(data_item2)  # add this first
            document_model.append_data_item(data_item2a)  # add this second
            computation = document_model.create_computation("target.xdata = resample_image(src.xdata, shape(12, 12)")
            computation.create_input_item("src", Symbolic.make_item(data_item2))
            document_model.set_data_item_computation(data_item2a, computation)
            # copy the dependent item
            data_item2a_copy = document_model.copy_data_item(data_item2a)
            # verify data source
            self.assertEqual(document_model.get_source_data_items(data_item2a_copy)[0], data_item2)
            self.assertIn(data_item2a_copy, document_model.get_dependent_data_items(data_item2))

    def test_copy_data_item_properly_copies_data_source_and_connects_it(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item2)  # add this first
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            data_item2a = document_model.get_invert_new(display_item2, display_item2.data_item)
            # copy the dependent item
            data_item2a_copy = document_model.copy_data_item(data_item2a)
            # verify data source
            self.assertEqual(document_model.get_data_item_computation(data_item2a).get_input("src").data_item, data_item2)
            self.assertEqual(document_model.get_data_item_computation(data_item2a_copy).get_input("src").data_item, data_item2)

    def test_copy_data_item_with_crop(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            source_data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(source_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25,0.25), (0.5,0.5)
            source_display_item.add_graphic(crop_region)
            data_item = document_model.get_crop_new(source_display_item, source_display_item.data_item, crop_region)
            data_item_copy = document_model.copy_data_item(data_item)
            self.assertNotEqual(document_model.get_data_item_computation(data_item_copy), document_model.get_data_item_computation(data_item))
            document_model.recompute_all()
            self.assertEqual(document_model.get_data_item_computation(data_item_copy).get_input("src").graphic,
                             document_model.get_data_item_computation(data_item).get_input("src").graphic)

    def test_copy_data_item_with_transaction(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((4, 4), numpy.uint32))
            document_model.append_data_item(data_item)
            with document_model.item_transaction(data_item):
                with data_item.data_ref() as data_ref:
                    data_ref.data = numpy.ones((4, 4), numpy.uint32)
                    data_item_copy = copy.deepcopy(data_item)
            with contextlib.closing(data_item_copy):
                display_item2 = document_model.get_display_item_for_data_item(data_item_copy)
                with data_item.data_ref() as data_ref:
                    with data_item_copy.data_ref() as data_copy_accessor:
                        self.assertEqual(data_copy_accessor.data.shape, (4, 4))
                        self.assertTrue(numpy.array_equal(data_ref.data, data_copy_accessor.data))
                        data_ref.data = numpy.ones((4, 4), numpy.uint32) + 1
                        self.assertFalse(numpy.array_equal(data_ref.data, data_copy_accessor.data))

    def test_data_item_in_transaction_is_not_unloadable(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            with document_model.item_transaction(data_item):
                document_model.append_data_item(data_item)
                # under transaction, data should not be unloadable
                self.assertFalse(data_item.is_unloadable)
                self.assertTrue(data_item.is_data_loaded)
            # no longer under transaction, data should not be unloadable
            self.assertTrue(data_item.is_unloadable)
            self.assertFalse(data_item.is_data_loaded)

    def test_clear_thumbnail_when_data_item_changed(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            self.assertTrue(display_item._display_cache.is_cached_value_dirty(display_item, "thumbnail_data"))
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.app.ui, display_item)
            with thumbnail_source.ref():
                thumbnail_source.recompute_data()
                self.assertIsNotNone(thumbnail_source.thumbnail_data)
                self.assertFalse(display_item._display_cache.is_cached_value_dirty(display_item, "thumbnail_data"))
                with display_item.data_item.data_ref() as data_ref:
                    data_ref.data = numpy.zeros((8, 8), numpy.uint32)
                self.assertTrue(display_item._display_cache.is_cached_value_dirty(display_item, "thumbnail_data"))

    def test_thumbnail_2d_handles_small_dimension_without_producing_invalid_thumbnail(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((1, 300), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.app.ui, display_item)
            with thumbnail_source.ref():
                thumbnail_source.recompute_data()
                thumbnail_data = thumbnail_source.thumbnail_data
                self.assertTrue(functools.reduce(lambda x, y: x * y, thumbnail_data.shape) > 0)

    def test_thumbnail_2d_handles_nan_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.zeros((16, 16), float)
            data[:] = numpy.nan
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.app.ui, display_item)
            with thumbnail_source.ref():
                thumbnail_source.recompute_data()
                self.assertIsNotNone(thumbnail_source.thumbnail_data)

    def test_thumbnail_2d_handles_inf_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.zeros((16, 16), float)
            data[:] = numpy.inf
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.app.ui, display_item)
            with thumbnail_source.ref():
                thumbnail_source.recompute_data()
                self.assertIsNotNone(thumbnail_source.thumbnail_data)

    def test_thumbnail_1d(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((256), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.app.ui, display_item)
            with thumbnail_source.ref():
                thumbnail_source.recompute_data()
                self.assertIsNotNone(thumbnail_source.thumbnail_data)

    def test_thumbnail_1d_handles_nan_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.zeros((256), float)
            data[:] = numpy.nan
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.app.ui, display_item)
            with thumbnail_source.ref():
                thumbnail_source.recompute_data()
                self.assertIsNotNone(thumbnail_source.thumbnail_data)

    def test_thumbnail_1d_handles_inf_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.zeros((256), float)
            data[:] = numpy.inf
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.app.ui, display_item)
            with thumbnail_source.ref():
                thumbnail_source.recompute_data()
                self.assertIsNotNone(thumbnail_source.thumbnail_data)

    def test_thumbnail_marked_dirty_when_source_data_changed(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(display_item, display_item.data_item)
            inverted_display_item = document_model.get_display_item_for_data_item(data_item_inverted)
            document_model.recompute_all()
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.app.ui, inverted_display_item)
            with thumbnail_source.ref():
                thumbnail_source.recompute_data()
                thumbnail_source.thumbnail_data
                # here the data should be computed and the thumbnail should not be dirty
                self.assertFalse(inverted_display_item._display_cache.is_cached_value_dirty(inverted_display_item, "thumbnail_data"))
                # now the source data changes and the inverted data needs computing.
                # the thumbnail should also be dirty.
                with data_item.data_ref() as data_ref:
                    data_ref.data = data_ref.data + 1.0
                document_model.recompute_all()
                self.assertTrue(inverted_display_item._display_cache.is_cached_value_dirty(inverted_display_item, "thumbnail_data"))

    def test_thumbnail_widget_when_data_item_has_no_associated_display_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item_reference = document_model.get_data_item_reference(document_model.make_data_item_reference_key("abc"))
            with contextlib.closing(DataItemThumbnailWidget.DataItemReferenceThumbnailSource(self.app.ui, document_model, data_item_reference)):
                data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
                document_model.append_data_item(data_item)
                data_item_reference.data_item = data_item

    def test_delete_nested_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item2)  # add this first
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            data_item2a = document_model.get_invert_new(display_item2, display_item2.data_item)
            display_item2a = document_model.get_display_item_for_data_item(data_item2a)
            data_item2a1 = document_model.get_invert_new(display_item2a, display_item2a.data_item)
            # remove item (and implicitly its dependency)
            document_model.remove_data_item(data_item2a)
            self.assertEqual(len(document_model.data_items), 1)

    def test_copy_data_item_with_display_and_graphics_should_copy_graphics(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            rect_graphic = Graphics.RectangleGraphic()
            display_item.add_graphic(rect_graphic)
            self.assertEqual(len(display_item.graphics), 1)
            display_item2 = document_model.deepcopy_display_item(display_item)
            self.assertEqual(2, len(document_model.data_items))
            self.assertEqual(2, len(document_model.display_items))
            self.assertEqual(1, len(display_item2.graphics))

    def test_deepcopy_data_item_should_produce_new_uuid(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        data_item_copy = copy.deepcopy(data_item)
        self.assertNotEqual(data_item.uuid, data_item_copy.uuid)
        data_item_copy.close()
        data_item.close()

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
        data_item_snap.close()
        data_item_copy.close()
        data_item.close()

    def test_copy_and_snapshot_should_copy_internal_title_caption_description(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            data_item.title = "123"
            data_item.caption = "234"
            data_item.description = "345"
            data_item_copy = copy.deepcopy(data_item)
            with contextlib.closing(data_item_copy):
                data_item_snapshot = data_item.snapshot()
                with contextlib.closing(data_item_snapshot):
                    self.assertEqual("123", data_item_copy.title)
                    self.assertEqual("234", data_item_copy.caption)
                    self.assertEqual("345", data_item_copy.description)
                    self.assertEqual("123", data_item_snapshot.title)
                    self.assertEqual("234", data_item_snapshot.caption)
                    self.assertEqual("345", data_item_snapshot.description)
                    # ensure there isn't an override stored in new data items
                    data_item_copy.title = "aaa"
                    data_item_copy.caption = "bbb"
                    data_item_copy.description = "ccc"
                    data_item_snapshot.title = "aaa"
                    data_item_snapshot.caption = "bbb"
                    data_item_snapshot.description = "ccc"
                    self.assertEqual("aaa", data_item_copy.title)
                    self.assertEqual("bbb", data_item_copy.caption)
                    self.assertEqual("ccc", data_item_copy.description)
                    self.assertEqual("aaa", data_item_snapshot.title)
                    self.assertEqual("bbb", data_item_snapshot.caption)
                    self.assertEqual("ccc", data_item_snapshot.description)

    def test_snapshot_data_item_should_not_copy_computation(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data1 = (numpy.random.randn(8, 8) * 100).astype(numpy.int32)
            data2 = (numpy.random.randn(8, 8) * 100).astype(numpy.int32)
            data_item = DataItem.DataItem(data1)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item_copy = document_model.get_crop_new(display_item, display_item.data_item)
            document_model.recompute_all()
            data_item_snap = document_model.get_display_item_snapshot_new(document_model.get_display_item_for_data_item(data_item_copy)).data_item
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

    def test_copy_data_item_should_succeed(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        with contextlib.closing(data_item):
            copy.copy(data_item).close()
            copy.deepcopy(data_item).close()
            data_item.snapshot().close()

    def test_appending_data_item_should_trigger_recompute(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            document_model.recompute_all()
            inverted_display_item = document_model.get_display_item_for_data_item(inverted_data_item)
            self.assertFalse(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)

    def test_data_range(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # test scalar
            xx, yy = numpy.meshgrid(numpy.linspace(0,1,256), numpy.linspace(0,1,256))
            with display_item.data_item.data_ref() as data_ref:
                data_ref.data = 50 * (xx + yy) + 25
                data_range = display_item.display_data_channels[0].get_latest_computed_display_values().data_range
                self.assertEqual(data_range, (25, 125))
                # now test complex
                data_ref.data = numpy.zeros((8, 8), numpy.complex64)
                xx, yy = numpy.meshgrid(numpy.linspace(0,1,256), numpy.linspace(0,1,256))
                data_ref.data = (2 + xx * 10) + 1j * (3 + yy * 10)
            data_range = display_item.display_data_channels[0].get_latest_computed_display_values().data_range
            data_min = math.log(math.sqrt(2*2 + 3*3))
            data_max = math.log(math.sqrt(12*12 + 13*13))
            self.assertEqual(int(data_min*1e6), int(data_range[0]*1e6))
            self.assertEqual(int(data_max*1e6), int(data_range[1]*1e6))

    def test_data_range_gets_updated_after_data_ref_data_updated(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            self.assertEqual(display_item.display_data_channels[0].get_latest_computed_display_values().data_range, (0, 0))
            with data_item.data_ref() as data_ref:
                data_ref.data[:] = 1
                data_ref.data_updated()
            self.assertEqual(display_item.display_data_channels[0].get_latest_computed_display_values().data_range, (1, 1))

    def test_data_descriptor_is_correct_after_data_ref_data_updated(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_descriptor = DataAndMetadata.DataDescriptor(True, 2, 2)
            data_item = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(numpy.zeros((6, 5, 4, 3, 2)), data_descriptor=data_descriptor))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            with data_item.data_ref() as data_ref:
                data_ref.data[:] = 1
                data_ref.data_updated()
            self.assertEqual(data_descriptor, data_item.xdata.data_descriptor)

    def test_removing_dependent_data_item_with_graphic(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(Graphics.RectangleGraphic())
            document_model.get_crop_new(display_item, display_item.data_item)
            # should remove properly when shutting down.

    def test_removing_derived_data_item_updates_dependency_info_on_source(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item1.title = "1"
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_item1a = document_model.get_invert_new(display_item1, display_item1.data_item)
            data_item1a.title = "1a"
            self.assertEqual(len(document_model.get_dependent_data_items(data_item1)), 1)
            document_model.remove_data_item(data_item1a)
            self.assertEqual(len(document_model.get_dependent_data_items(data_item1)), 0)

    def test_recomputing_data_should_not_leave_it_loaded(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            inverted_display_item = document_model.get_display_item_for_data_item(inverted_data_item)
            document_model.recompute_all()
            self.assertFalse(inverted_display_item.data_item.is_data_loaded)

    def test_loading_dependent_data_should_not_cause_source_data_to_load(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(display_item, display_item.data_item)
            inverted_display_item = document_model.get_display_item_for_data_item(data_item_inverted)
            # begin checks
            document_model.recompute_all()
            self.assertFalse(display_item.data_item.is_data_loaded)
            with inverted_display_item.data_item.data_ref() as d:
                self.assertFalse(display_item.data_item.is_data_loaded)
            self.assertFalse(display_item.data_item.is_data_loaded)

    def test_modifying_source_data_should_trigger_data_changed_notification_from_dependent_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(display_item, display_item.data_item)
            inverted_display_item = document_model.get_display_item_for_data_item(data_item_inverted)
            document_model.recompute_all()
            data_changed_ref = [False]
            def data_item_content_changed():
                data_changed_ref[0] = True
            with contextlib.closing(data_item_inverted.data_item_changed_event.listen(data_item_content_changed)):
                display_item.data_item.set_data(numpy.ones((8, 8), numpy.uint32))
                document_model.recompute_all()
                self.assertTrue(data_changed_ref)
                self.assertFalse(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)

    def test_modifying_source_data_should_trigger_data_item_stale_from_dependent_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            document_model.recompute_all()
            data_item.set_data(numpy.ones((8, 8), numpy.uint32))
            self.assertTrue(document_model.get_data_item_computation(inverted_data_item).needs_update)

    def test_modifying_source_data_should_queue_recompute_in_document_model(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            inverted_display_item = document_model.get_display_item_for_data_item(inverted_data_item)
            document_model.recompute_all()
            display_item.data_item.set_data(numpy.ones((8, 8), numpy.uint32))
            self.assertTrue(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)

    def test_is_data_stale_should_propagate_to_data_items_dependent_on_source(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.full((2, 2), 2, numpy.int32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            inverted_display_item = document_model.get_display_item_for_data_item(inverted_data_item)
            inverted2_data_item = document_model.get_invert_new(inverted_display_item, inverted_display_item.data_item)
            inverted2_display_item = document_model.get_display_item_for_data_item(inverted2_data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)
            self.assertFalse(document_model.get_data_item_computation(inverted2_display_item.data_item).needs_update)
            display_item.data_item.set_data(numpy.ones((2, 2), numpy.int32))
            self.assertTrue(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)
            self.assertFalse(document_model.get_data_item_computation(inverted2_display_item.data_item).needs_update)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)
            self.assertFalse(document_model.get_data_item_computation(inverted2_display_item.data_item).needs_update)

    def test_data_item_that_is_recomputed_notifies_listeners_of_a_single_data_change(self):
        # this test ensures that doing a recompute_data is efficient and doesn't produce
        # extra data_item_content_changed messages.
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            inverted_display_item = document_model.get_display_item_for_data_item(inverted_data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)
            data_changed_ref = [0]
            def data_item_content_changed():
                data_changed_ref[0] += 1
            with contextlib.closing(inverted_data_item.data_item_changed_event.listen(data_item_content_changed)):
                display_item.data_item.set_data(numpy.ones((8, 8), numpy.uint32))
                self.assertTrue(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)
                self.assertEqual(data_changed_ref[0], 0)
                document_model.recompute_all()
                self.assertFalse(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)
                self.assertEqual(data_changed_ref[0], 1)

    def test_adding_removing_data_item_with_crop_computation_updates_graphics(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            display_item.add_graphic(crop_region)
            data_item_crop = document_model.get_crop_new(display_item, display_item.data_item, crop_region)
            self.assertEqual(len(display_item.graphics), 1)
            document_model.remove_data_item(data_item_crop)
            self.assertEqual(len(display_item.graphics), 0)

    def disabled_test_adding_removing_crop_computation_to_existing_data_item_updates_graphics(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            display_item.add_graphic(crop_region)
            data_item_crop = document_model.get_crop_new(display_item, display_item.data_item, crop_region)
            self.assertEqual(len(display_item.graphics), 1)
            document_model.set_data_item_computation(data_item, None)
            # the associated graphic should now be deleted.
            self.assertEqual(len(display_item.graphics), 0)

    def test_updating_computation_graphic_property_notifies_data_item(self):
        graphics_changed_ref = [False]
        def graphics_changed(s):
            graphics_changed_ref[0] = True
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(crop_region)
            display_item = document_model.get_display_item_for_data_item(data_item)
            with contextlib.closing(display_item.graphics_changed_event.listen(graphics_changed)):
                document_model.get_crop_new(display_item, display_item.data_item, crop_region)
                graphics_changed_ref[0] = False
                display_item.graphics[0].bounds = ((0.2,0.3), (0.8,0.7))
                self.assertTrue(graphics_changed_ref[0])

    # necessary to make inspector display updated values properly
    def test_updating_computation_graphic_property_with_same_value_notifies_data_item(self):
        graphics_changed_ref = [False]
        def graphics_changed(s):
            graphics_changed_ref[0] = True
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(crop_region)
            with contextlib.closing(display_item.graphics_changed_event.listen(graphics_changed)):
                document_model.get_crop_new(display_item, display_item.data_item, crop_region)
                display_item.graphics[0].bounds = ((0.2,0.3), (0.8,0.7))
                graphics_changed_ref[0] = False
                display_item.graphics[0].bounds = ((0.2,0.3), (0.8,0.7))
                self.assertFalse(graphics_changed_ref[0])

    def test_snapshot_should_copy_raw_metadata(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        metadata = data_item.metadata
        metadata.setdefault("test", dict())["one"] = 1
        data_item.metadata = metadata
        data_item_copy = data_item.snapshot()
        self.assertEqual(data_item_copy.metadata.get("test")["one"], 1)
        data_item_copy.close()
        data_item.close()

    def test_snapshot_should_copy_timezone(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        data_item.timezone = "Europe/Athens"
        data_item.timezone_offset = "+0300"
        data_item_copy = data_item.snapshot()
        self.assertEqual(data_item.timezone, data_item_copy.timezone)
        self.assertEqual(data_item.timezone_offset, data_item_copy.timezone_offset)
        data_item_copy.close()
        data_item.close()

    def test_snapshot_should_not_copy_category(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        data_item.category = "temporary"
        data_item_copy = data_item.snapshot()
        self.assertNotEqual("temporary", data_item_copy.category)
        data_item_copy.close()
        data_item.close()

    def test_data_item_allows_adding_of_two_data_sources(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item1)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item2)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            document_model.get_cross_correlate_new(display_item1, display_item1.data_item, display_item2, display_item2.data_item)

    def test_region_graphic_gets_added_to_existing_display(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            self.assertEqual(len(display_item.graphics), 0)
            display_item.add_graphic(Graphics.PointGraphic())
            self.assertEqual(len(display_item.graphics), 1)

    # necessary to make inspector display updated values properly
    def test_adding_region_generates_display_changed(self):
        graphics_changed_ref = [False]
        def graphics_changed(s):
            graphics_changed_ref[0] = True
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            with contextlib.closing(display_item.graphics_changed_event.listen(graphics_changed)):
                crop_region = Graphics.RectangleGraphic()
                display_item.add_graphic(crop_region)
                self.assertTrue(graphics_changed_ref[0])
                graphics_changed_ref[0] = False
                display_item.remove_graphic(crop_region).close()
                self.assertTrue(graphics_changed_ref[0])

    def test_changing_calibration_updates_interval_graphics(self):
        # note: this only tests whether the display is sent the proper data, not whether it draws properly
        graphics_changed_ref = [False]
        def graphics_changed(s):
            graphics_changed_ref[0] = True
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8,)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            with contextlib.closing(display_item.graphics_changed_event.listen(graphics_changed)):
                graphic = Graphics.IntervalGraphic()
                display_item.add_graphic(graphic)
                self.assertTrue(graphics_changed_ref[0])
                graphics_changed_ref[0] = False
                data_item.set_dimensional_calibration(0, Calibration.Calibration(1, 2, "g"))
                self.assertTrue(graphics_changed_ref[0])

    def test_line_profile_interval_updates_line_profile_graphic(self):
        # note: this only tests whether the display is sent the proper data, not whether it draws properly
        graphics_changed_ref = [False]
        def graphics_changed(s):
            graphics_changed_ref[0] = True
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_plot_data_item = document_model.get_line_profile_new(display_item, display_item.data_item)
            line_plot_display_item = document_model.get_display_item_for_data_item(line_plot_data_item)
            line_profile_graphic = display_item.graphics[0]
            with contextlib.closing(display_item.graphics_changed_event.listen(graphics_changed)):
                interval_graphic = Graphics.IntervalGraphic()
                line_plot_display_item.add_graphic(interval_graphic)
                self.assertTrue(graphics_changed_ref[0])
                self.assertEqual((0.0, 1.0), line_profile_graphic.interval_descriptors[0]["interval"])
                graphics_changed_ref[0] = False
                interval_graphic.interval = (0.2, 0.3)
                self.assertTrue(graphics_changed_ref[0])
                self.assertEqual((0.2, 0.3), line_profile_graphic.interval_descriptors[0]["interval"])

    def test_connecting_data_source_updates_dependent_data_items_property_on_source(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # configure the dependent item
            data_item2 = document_model.get_invert_new(display_item, display_item.data_item)
            # make sure the dependency list is updated
            self.assertEqual(document_model.get_dependent_data_items(data_item), [data_item2])

    def test_begin_transaction_also_begins_transaction_for_dependent_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # configure the dependent item
            data_item2 = document_model.get_invert_new(display_item, display_item.data_item)
            # begin the transaction
            with document_model.item_transaction(data_item):
                self.assertTrue(data_item.in_transaction_state)
                self.assertTrue(data_item2.in_transaction_state)
            self.assertFalse(data_item.in_transaction_state)
            self.assertFalse(data_item2.in_transaction_state)

    def test_data_item_added_to_data_item_under_transaction_becomes_transacted_too(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # begin the transaction
            with document_model.item_transaction(data_item):
                # configure the dependent item
                data_item2 = document_model.get_invert_new(display_item, display_item.data_item)
                # check to make sure it is under transaction
                self.assertTrue(data_item.in_transaction_state)
                self.assertTrue(data_item2.in_transaction_state)
            self.assertFalse(data_item.in_transaction_state)
            self.assertFalse(data_item2.in_transaction_state)

    def test_data_item_added_to_data_item_under_transaction_configures_dependency(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.add_graphic(crop_region)
            # begin the transaction
            with document_model.item_transaction(data_item):
                data_item_crop1 = document_model.get_crop_new(display_item, display_item.data_item, crop_region)
                # change the bounds of the graphic
                display_item.graphics[0].bounds = ((0.31, 0.32), (0.6, 0.4))
                # make sure it is connected to the crop computation
                bounds = crop_region.bounds
                self.assertAlmostEqual(bounds[0][0], 0.31)
                self.assertAlmostEqual(bounds[0][1], 0.32)
                self.assertAlmostEqual(bounds[1][0], 0.6)
                self.assertAlmostEqual(bounds[1][1], 0.4)

    def test_data_item_under_transaction_added_to_document_does_write_delay(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            # begin the transaction
            with document_model.item_transaction(data_item):
                document_model.append_data_item(data_item)
                self.assertTrue(data_item.is_write_delayed)

    def test_data_item_added_to_live_data_item_becomes_live_and_unlive_based_on_parent_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            with document_model.data_item_live(data_item):
                data_item_crop1 = document_model.get_invert_new(display_item, display_item.data_item)
                self.assertTrue(data_item_crop1.is_live)
            self.assertFalse(data_item.is_live)
            self.assertFalse(data_item_crop1.is_live)

    def slow_test_dependent_data_item_removed_while_live_data_item_becomes_unlive(self):
        # an intermittent race condition. run several times. see the changes that accompanied
        # the addition of this code.
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            def live_it(n):
                for _ in range(n):
                    with document_model.data_item_live(data_item):
                        pass
            threading.Thread(target=live_it, args=(1000, )).start()
            with document_model.data_item_live(data_item):
                for _ in range(100):
                    data_item_inverted = document_model.get_invert_new(display_item, display_item.data_item)
                    document_model.remove_data_item(data_item_inverted)

    def test_changing_metadata_or_data_does_not_mark_the_data_as_stale(self):
        # changing metadata or data will override what has been computed
        # from the data sources, if there are any.
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(src_data_item)
            src_display_item = document_model.get_display_item_for_data_item(src_data_item)
            data_item = document_model.get_invert_new(src_display_item, src_display_item.data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(display_item.data_item).needs_update)
            display_item.data_item.set_data(numpy.zeros((8, 8), numpy.uint32))
            display_item.data_item.set_intensity_calibration(Calibration.Calibration())
            self.assertFalse(document_model.get_data_item_computation(display_item.data_item).needs_update)

    def test_changing_metadata_or_data_does_not_mark_the_data_as_stale_for_data_item_with_data_source(self):
        # changing metadata or data will override what has been computed
        # from the data sources, if there are any.
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            copied_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            copied_display_item = document_model.get_display_item_for_data_item(copied_data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(copied_display_item.data_item).needs_update)
            copied_display_item.data_item.set_intensity_calibration(Calibration.Calibration())
            self.assertFalse(document_model.get_data_item_computation(copied_display_item.data_item).needs_update)

    def test_removing_computation_should_not_mark_the_data_as_stale(self):
        # is this test valid any more?
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            copied_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(copied_data_item).needs_update)
            document_model.set_data_item_computation(copied_data_item, None)
            document_model.recompute_all()
            self.assertIsNotNone(copied_data_item.data)

    def test_changing_computation_should_mark_the_data_as_stale(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            copied_data_item = document_model.get_gaussian_blur_new(display_item, display_item.data_item)
            copied_display_item = document_model.get_display_item_for_data_item(copied_data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(copied_display_item.data_item).needs_update)
            document_model.get_data_item_computation(copied_data_item).set_input_value("sigma", 0.1)
            self.assertTrue(document_model.get_data_item_computation(copied_display_item.data_item).needs_update)
            computation = document_model.get_data_item_computation(copied_display_item.data_item)
            # import pprint
            # pprint.pprint(computation.write_to_dict())

    def test_reloading_stale_data_should_still_be_stale(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            inverted_display_item = document_model.get_display_item_for_data_item(inverted_data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)
            self.assertAlmostEqual(inverted_display_item.data_item.data[0, 0], -1.0)
            # now the source data changes and the inverted data needs computing.
            with display_item.data_item.data_ref() as data_ref:
                data_ref.data = data_ref.data + 2.0
            self.assertTrue(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)
            # data is now unloaded and stale.
            self.assertFalse(inverted_display_item.data_item.is_data_loaded)
            # don't recompute
            self.assertAlmostEqual(inverted_display_item.data_item.data[0, 0], -1.0)
            # data should still be stale
            self.assertTrue(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)

    def test_recomputing_data_gives_correct_result(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(display_item, display_item.data_item)
            inverted_display_item = document_model.get_display_item_for_data_item(data_item_inverted)
            document_model.recompute_all()
            self.assertAlmostEqual(inverted_display_item.data_item.data[0, 0], -1.0)
            # now the source data changes and the inverted data needs computing.
            with display_item.data_item.data_ref() as data_ref:
                data_ref.data = data_ref.data + 2.0
            document_model.recompute_all()
            self.assertAlmostEqual(inverted_display_item.data_item.data[0, 0], -3.0)

    def test_recomputing_data_after_cached_data_is_called_gives_correct_result(self):
        # verify that this works, the more fundamental test is in test_reloading_stale_data_should_still_be_stale
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(display_item, display_item.data_item)
            inverted_display_item = document_model.get_display_item_for_data_item(inverted_data_item)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(inverted_display_item.data_item).needs_update)
            self.assertAlmostEqual(inverted_display_item.data_item.data[0, 0], -1.0)
            # now the source data changes and the inverted data needs computing.
            with display_item.data_item.data_ref() as data_ref:
                data_ref.data = data_ref.data + 2.0
            # verify the actual data values are still stale
            self.assertAlmostEqual(inverted_display_item.data_item.data[0, 0], -1.0)
            # recompute and verify the data values are valid
            document_model.recompute_all()
            self.assertAlmostEqual(inverted_display_item.data_item.data[0, 0], -3.0)

    def test_modifying_data_item_modified_property_works(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            modified = datetime.datetime(2000, 1, 1)
            data_item._set_modified(modified)
            self.assertEqual(data_item.modified, modified)

    def test_modifying_data_item_metadata_updates_modified(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            data_item._set_modified(datetime.datetime(2000, 1, 1))
            modified = data_item.modified
            time.sleep(0.001)  # windows has a time resolution of 1ms. sleep to avoid duplicate.
            data_item.category = "category"
            self.assertGreater(data_item.modified, modified)

    def test_changing_property_on_display_updates_modified(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item._set_modified(datetime.datetime(2000, 1, 1))
            display_item._set_modified(datetime.datetime(2000, 1, 1))
            data_item_modified = data_item.modified
            display_item_modified = display_item.modified
            time.sleep(0.001)  # windows has a time resolution of 1ms. sleep to avoid duplicate.
            display_item.calibration_style_id = "relative-top-left"
            self.assertEqual(data_item.modified, data_item_modified)
            self.assertGreater(display_item.modified, display_item_modified)

    def test_changing_data_on_data_item_updates_modified(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            data_item._set_modified(datetime.datetime(2000, 1, 1))
            modified = data_item.modified
            time.sleep(0.001)  # windows has a time resolution of 1ms. sleep to avoid duplicate.
            data_item.set_data(numpy.zeros((2, 2)))
            self.assertGreater(data_item.modified, modified)

    def test_changing_partial_data_on_data_item_updates_modified(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            data_item._set_modified(datetime.datetime(2000, 1, 1))
            modified = data_item.modified
            time.sleep(0.001)  # windows has a time resolution of 1ms. sleep to avoid duplicate.
            data_item.set_data_and_metadata_partial(data_item.xdata.data_metadata, data_item.xdata, [slice(0, 1, 1), slice(0, 2, 1)], [slice(0, 1, 1), slice(0, 2, 1)], update_metadata=True)
            # data_item.set_data(numpy.zeros((2, 2)))
            self.assertGreater(data_item.modified, modified)

    def test_changing_data_updates_xdata_timestamp(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            timestamp = datetime.datetime(2000, 1, 1)
            time.sleep(0.001)  # windows has a time resolution of 1ms. sleep to avoid duplicate.
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((2, 2)), timestamp=timestamp)
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            data_item.set_data(numpy.zeros((2, 2)))
            self.assertGreater(data_item.xdata.timestamp, timestamp)

    def test_data_item_in_transaction_does_not_write_until_end_of_transaction(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            with document_model.item_transaction(data_item):
                document_model.append_data_item(data_item)
                self.assertEqual(len(profile_context.data_map.keys()), 0)
            self.assertEqual(len(profile_context.data_map.keys()), 1)

    def test_extra_changing_data_item_session_id_in_transaction_does_not_result_in_duplicated_data_items(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            with document_model.item_transaction(data_item):
                data_item.session_id = "20000630-150200"
                document_model.append_data_item(data_item)
                self.assertEqual(len(profile_context.data_map.keys()), 0)
                data_item.session_id = "20000630-150201"
            self.assertEqual(len(profile_context.data_map.keys()), 1)

    def test_changing_data_item_session_id_in_transaction_does_not_result_in_duplicated_data_items(self):
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            with document_model.item_transaction(data_item):
                data_item.session_id = "20000630-150200"
                document_model.append_data_item(data_item)
            self.assertEqual(len(profile_context.data_map.keys()), 1)
            with document_model.item_transaction(data_item):
                data_item.session_id = "20000630-150201"
            self.assertEqual(len(profile_context.data_map.keys()), 1)

    def test_data_item_added_to_library_gets_current_session(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            document_model.append_data_item(data_item)
            self.assertEqual(data_item.session_id, document_model.session_id)

    def test_data_item_gets_current_session_when_data_is_modified(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            document_model.session_id = '20000630-150200'
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            data_item.category = 'temporary'
            document_model.append_data_item(data_item)
            document_model.start_new_session()
            self.assertNotEqual(data_item.session_id, document_model.session_id)
            data_item.set_data(numpy.ones((4, 4)))
            self.assertEqual(data_item.session_id, document_model.session_id)

    def test_data_item_keeps_session_unmodified_when_metadata_is_changed(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            document_model.session_id = '20000630-150200'
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            data_item.category = 'temporary'
            document_model.append_data_item(data_item)
            document_model.start_new_session()
            self.assertNotEqual(data_item.session_id, document_model.session_id)
            data_item.title = 'new title'
            self.assertEqual(data_item.session_id, '20000630-150200')

    def test_data_item_copy_copies_session_info(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            session_metadata = data_item.session_metadata
            session_metadata['site'] = 'Home'
            data_item.session_metadata = session_metadata
            document_model.append_data_item(data_item)
            data_item_copy = copy.deepcopy(data_item)
            document_model.append_data_item(data_item_copy)
            self.assertEqual(data_item_copy.session_metadata, data_item.session_metadata)
            self.assertEqual(data_item_copy.session_id, document_model.session_id)

    def test_data_item_setting_session_data_trigger_property_changed_event(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            document_model.append_data_item(data_item)

            received_session_changed = False
            received_session_metadata_changed = False

            def property_changed(name: str) -> None:
                nonlocal received_session_changed, received_session_metadata_changed
                if name == 'session':
                    received_session_changed = True
                elif name == 'session_metadata':
                    received_session_metadata_changed = True

            listener = data_item.property_changed_event.listen(property_changed)

            session_metadata = data_item.session_metadata
            session_metadata['site'] = 'Home'
            data_item.session_metadata = session_metadata

            listener = None

            self.assertTrue(received_session_changed)
            self.assertTrue(received_session_metadata_changed)


    def test_data_item_session_id_independent_from_data_source_session_id(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((2, 2)))
            document_model.append_data_item(data_item)
            data_item.session_id = "20000630-150200"
            self.assertEqual("20000630-150200", data_item.session_id)
            data_item.session_id = "20000630-150201"
            self.assertEqual("20000630-150201", data_item.session_id)

    def test_processed_data_item_has_source_data_modified_equal_to_sources_data_modifed(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            document_model.append_data_item(src_data_item)
            src_display_item = document_model.get_display_item_for_data_item(src_data_item)
            time.sleep(0.01)
            data_item = document_model.get_invert_new(src_display_item, src_display_item.data_item)
            document_model.recompute_all()
            self.assertIsNotNone(src_data_item.data_modified)
            self.assertGreaterEqual(data_item.data_modified, src_data_item.data_modified)

    def test_processed_data_item_has_source_data_modified_equal_to_sources_created_when_sources_data_modified_is_none(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            src_data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            src_data_item.data_modified = None
            document_model.append_data_item(src_data_item)
            src_display_item = document_model.get_display_item_for_data_item(src_data_item)
            time.sleep(0.01)
            data_item = document_model.get_invert_new(src_display_item, src_display_item.data_item)
            document_model.recompute_all()
            self.assertGreaterEqual(data_item.data_modified, src_data_item.created)

    def test_dependent_calibration(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.data_item.set_dimensional_calibration(0, Calibration.Calibration(3.0, 2.0, u"x"))
            display_item.data_item.set_dimensional_calibration(1, Calibration.Calibration(3.0, 2.0, u"x"))
            self.assertEqual(len(display_item.data_item.dimensional_calibrations), 2)
            data_item_copy = document_model.get_invert_new(display_item, display_item.data_item)
            display_item2 = document_model.get_display_item_for_data_item(data_item_copy)
            document_model.recompute_all()
            dimensional_calibrations = display_item2.data_item.dimensional_calibrations
            self.assertEqual(len(dimensional_calibrations), 2)
            self.assertEqual(int(dimensional_calibrations[0].offset), 3)
            self.assertEqual(int(dimensional_calibrations[0].scale), 2)
            self.assertEqual(dimensional_calibrations[0].units, "x")
            self.assertEqual(int(dimensional_calibrations[1].offset), 3)
            self.assertEqual(int(dimensional_calibrations[1].scale), 2)
            self.assertEqual(dimensional_calibrations[1].units, "x")
            fft_data_item = document_model.get_fft_new(display_item, display_item.data_item)
            document_model.recompute_all()
            dimensional_calibrations = fft_data_item.dimensional_calibrations
            self.assertEqual(int(dimensional_calibrations[0].offset), 0)
            self.assertEqual(dimensional_calibrations[0].units, "1/x")
            self.assertEqual(int(dimensional_calibrations[1].offset), 0)
            self.assertEqual(dimensional_calibrations[1].units, "1/x")

    def test_double_dependent_calibration(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item2 = document_model.get_invert_new(display_item, display_item.data_item)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            data_item3 = document_model.get_invert_new(display_item2, display_item2.data_item)
            display_item3 = document_model.get_display_item_for_data_item(data_item3)
            document_model.recompute_all()
            self.assertIsNotNone(display_item3.data_item.dimensional_calibrations)

    def test_spatial_calibration_on_rgb(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            self.assertTrue(Image.is_shape_and_dtype_2d(display_item.data_item.data_shape, display_item.data_item.data_dtype))
            self.assertTrue(Image.is_shape_and_dtype_rgba(display_item.data_item.data_shape, display_item.data_item.data_dtype))
            self.assertEqual(len(display_item.data_item.dimensional_calibrations), 2)

    def test_metadata_is_valid_when_a_data_item_has_no_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(display_item, display_item.data_item)
            inverted_display_item = document_model.get_display_item_for_data_item(data_item_inverted)
            self.assertIsInstance(inverted_display_item.data_item.metadata, dict)

    def test_data_item_recorder_records_intensity_calibration_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.double))
            document_model.append_data_item(data_item)
            data_item_clone = data_item.clone()
            data_item_clone_recorder = Recorder.Recorder(data_item_clone)
            data_item_clone.set_intensity_calibration(Calibration.Calibration(units="mmm"))
            data_item_clone_recorder.apply(data_item)
            self.assertEqual(data_item.intensity_calibration.units, data_item_clone.intensity_calibration.units)
            data_item_clone_recorder.close()
            data_item_clone.close()

    def test_data_item_recorder_records_title_changes(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.double))
            document_model.append_data_item(data_item)
            data_item_clone = data_item.clone()
            data_item_clone_recorder = Recorder.Recorder(data_item_clone)
            data_item_clone.title = "Firefly"
            data_item_clone_recorder.apply(data_item)
            self.assertEqual(data_item.title, data_item_clone.title)
            data_item_clone_recorder.close()
            data_item_clone.close()

    def test_timezone_is_stored_on_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
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
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
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

    def test_xdata_data_ref_counts_are_correct_after_setting_xdata_on_data_item_in_transaction(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((16, 16)))
            document_model.append_data_item(data_item)
            data_item_xdata = data_item.xdata
            self.assertEqual(0, data_item._data_ref_count)
            with document_model.item_transaction(data_item):
                self.assertEqual(1, data_item._data_ref_count)
                data_item.set_data(numpy.zeros((16, 16)))
            self.assertEqual(0, data_item._data_ref_count)

    def test_filter_xdata_returns_ones_when_no_graphics(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # setup by adding data item and a dependent data item
            data_item = DataItem.DataItem(numpy.zeros((8, 8)))
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("target.xdata = src")
            display_item = document_model.get_display_item_for_data_item(data_item)
            computation.create_input_item("src", Symbolic.make_item(display_item.display_data_channel, type="filter_xdata"))
            document_model.set_data_item_computation(data_item2, computation)
            document_model.recompute_all()
            # verify
            self.assertTrue(numpy.array_equal(data_item2.xdata.data, numpy.ones((8, 8))))

    def test_reserving_data_keeps_metadata(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem()
            data_item.metadata = {"abc": 33}
            data_item.session_metadata = {"def": 55}
            document_model.append_data_item(data_item)
            data_item.reserve_data(data_shape=(2, 2), data_dtype=numpy.dtype(numpy.float32), data_descriptor=DataAndMetadata.DataDescriptor(False, 0, 2))
            self.assertEqual(33, data_item.metadata.get("abc"))
            self.assertEqual(55, data_item.session_metadata.get("def"))

    def test_setting_title_after_dynamic_title_updates_correctly(self):
        # requirement: dynamic_titles
        with create_memory_profile_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.zeros((8,)))
                data_item.dynamic_title = DynamicString._TestDynamicString()
                document_model.append_data_item(data_item)
                self.assertEqual("green", data_item.title)
                data_item.title = "red"
                self.assertEqual("red", data_item.title)

    def test_computed_data_item_title(self):
        # requirement: dynamic_titles
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem()
            data_item.title = "source"
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            data_item2 = document_model.get_invert_new(display_item, display_item.data_item)
            self.assertEqual("source (Negate)", data_item2.title)
            data_item.title = "source2"
            self.assertEqual("source2 (Negate)", data_item2.title)

    def test_setting_dynamic_title_immediately_updates_title_stream(self):
        # requirement: dynamic_titles
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem()
            data_item.metadata = {"_slug_test": "nome"}
            document_model.append_data_item(data_item)
            # dynamic title is initially enabled so that empty title uses source/computation
            self.assertEqual("Untitled", data_item.title)
            self.assertTrue(data_item.dynamic_title_enabled)
            # update the dynamic title and check
            data_item.set_dynamic_title_by_id("_slug_test")
            self.assertEqual("nome", data_item.title)
            self.assertTrue(data_item.dynamic_title_enabled)
            # set the title and check
            data_item.title = "title"
            self.assertEqual("title", data_item.title)
            self.assertFalse(data_item.dynamic_title_enabled)
            # clear the title and ensure dynamic title is used again
            data_item.title = str()
            self.assertEqual("nome", data_item.title)
            self.assertTrue(data_item.dynamic_title_enabled)

    def test_setting_dynamic_title_when_not_already_enabled_updates_title_immediately(self):
        # requirement: dynamic_titles
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem()
            data_item.metadata = {"_slug_test": ""}
            data_item.title = "red"
            self.assertFalse(data_item.dynamic_title_enabled)
            data_item.set_dynamic_title_by_id("_slug_test")
            self.assertTrue(data_item.dynamic_title_enabled)
            self.assertEqual("red", data_item.title)
            document_model.append_data_item(data_item)
            data_item.metadata = {"_slug_test": "green"}
            self.assertEqual("green", data_item.title)

    def test_update_partial_uses_timestamp_from_xdata_on_first_update_only(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem()
            document_model.append_data_item(data_item)
            data_shape_and_dtype = (4, 4), float
            intensity_calibration = Calibration.Calibration()
            dimensional_calibrations = [Calibration.Calibration(), Calibration.Calibration()]
            data_descriptor = DataAndMetadata.DataDescriptor(False, 0, 2)
            data_metadata = DataAndMetadata.DataMetadata(data_shape_and_dtype,
                                                         intensity_calibration,
                                                         dimensional_calibrations,
                                                         data_descriptor=data_descriptor,
                                                         timestamp=datetime.datetime(2000, 1, 1))
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((2, 4), data_shape_and_dtype[1]))
            data_item.reserve_data(data_shape=(4, 4), data_dtype=float, data_descriptor=DataAndMetadata.DataDescriptor(False, 0, 2))
            document_model.update_data_item_partial(data_item, data_metadata, data_and_metadata, [slice(0, 2), slice(None)], [slice(0, 2), slice(None)])
            document_model.perform_data_item_updates()
            self.assertEqual(data_item.xdata.timestamp, datetime.datetime(2000, 1, 1))
            data_metadata._set_timestamp(datetime.datetime(2000, 1, 2))
            document_model.update_data_item_partial(data_item, data_metadata, data_and_metadata, [slice(0, 2), slice(None)], [slice(2, 4), slice(None)])
            document_model.perform_data_item_updates()
            self.assertEqual(data_item.xdata.timestamp, datetime.datetime(2000, 1, 1))

    def test_queue_update_uses_timestamp_from_xdata(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((4, 4), float))
            document_model.append_data_item(data_item)
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.ones((4, 4), float), timestamp=datetime.datetime(2000, 1, 1))
            document_model._queue_data_item_update(data_item, data_and_metadata)
            document_model.perform_data_item_updates()
            self.assertEqual(data_item.xdata.timestamp, datetime.datetime(2000, 1, 1))

    # modify property/item/relationship on data source, display, region, etc.
    # copy or snapshot

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
