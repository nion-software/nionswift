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
from nion.data import Image
from nion.swift import Application
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import TestUI


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
        metadata = data_item.metadata
        metadata.setdefault("test", dict())["one"] = 1
        metadata.setdefault("test", dict())["two"] = 22
        data_item.set_metadata(metadata)
        display_specifier.display.display_limits = (100, 900)
        display_specifier.display.add_graphic(Graphics.RectangleGraphic())
        data_item_copy = copy.deepcopy(data_item)
        display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item_copy)
        self.assertNotEqual(id(data), id(display_specifier2.buffered_data_source.data))
        # make sure properties and other items got copied
        #self.assertEqual(len(data_item_copy.properties), 19)  # not valid since properties only exist if in document
        self.assertIsNot(data_item.properties, data_item_copy.properties)
        # uuid should not match
        self.assertNotEqual(data_item.uuid, data_item_copy.uuid)
        # metadata get copied?
        self.assertEqual(len(data_item.metadata.get("test")), 2)
        self.assertIsNot(data_item.metadata.get("test"), data_item_copy.metadata.get("test"))
        # make sure display counts match
        self.assertEqual(len(display_specifier.buffered_data_source.displays), len(display_specifier2.buffered_data_source.displays))
        # tuples and strings are immutable, so test to make sure old/new are independent
        self.assertEqual(data_item.title, data_item_copy.title)
        data_item.title = "data_item1"
        self.assertNotEqual(data_item.title, data_item_copy.title)
        self.assertEqual(display_specifier.display.display_limits, display_specifier2.display.display_limits)
        display_specifier.display.display_limits = (150, 200)
        self.assertNotEqual(display_specifier.display.display_limits, display_specifier2.display.display_limits)
        # make sure dates are independent
        self.assertIsNot(data_item.created, data_item_copy.created)
        self.assertIsNot(display_specifier.buffered_data_source.created, display_specifier2.buffered_data_source.created)
        # make sure calibrations, computations, nor graphics are not shared.
        # there is a subtlety here: the dimensional_calibrations property accessor will return a copy of
        # the list each time it is called. store these in variables do make sure they don't get deallocated
        # and re-used immediately (causing a test failure).
        dimensional_calibrations = display_specifier.buffered_data_source.dimensional_calibrations
        dimensional_calibrations2 = display_specifier2.buffered_data_source.dimensional_calibrations
        self.assertNotEqual(id(dimensional_calibrations[0]), id(dimensional_calibrations2[0]))
        self.assertNotEqual(display_specifier.display.graphics[0], display_specifier2.display.graphics[0])

    def test_data_item_with_existing_computation_initializes_dependencies(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2a = DataItem.DataItem()
            computation = document_model.create_computation("resample_image(src, shape(12, 12)")
            computation.create_object("src", document_model.get_object_specifier(data_item2, "data"))
            data_item2a.append_data_source(DataItem.BufferedDataSource())
            data_item2a.maybe_data_source.set_computation(computation)
            document_model.append_data_item(data_item2)  # add this first
            document_model.append_data_item(data_item2a)  # add this second
            # verify
            self.assertEqual(document_model.get_source_data_items(data_item2a)[0], data_item2)

    def test_removing_data_item_with_computation_deinitializes_dependencies(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2a = DataItem.DataItem()
            computation = document_model.create_computation("resample_image(src, shape(12, 12)")
            computation.create_object("src", document_model.get_object_specifier(data_item2, "data"))
            data_item2a.append_data_source(DataItem.BufferedDataSource())
            data_item2a.maybe_data_source.set_computation(computation)
            document_model.append_data_item(data_item2)  # add this first
            document_model.append_data_item(data_item2a)  # add this second
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
            computation = document_model.create_computation("resample_image(src, shape(12, 12)")
            computation.create_object("src", document_model.get_object_specifier(data_item2, "data"))
            data_item2a.append_data_source(DataItem.BufferedDataSource())
            data_item2a.maybe_data_source.set_computation(computation)
            document_model.append_data_item(data_item2)  # add this first
            document_model.append_data_item(data_item2a)  # add this second
            # verify
            self.assertEqual(document_model.get_source_data_items(data_item2a)[0], data_item2)
            # remove source
            document_model.remove_data_item(data_item2)
            # verify
            self.assertEqual(len(document_model.get_source_data_items(data_item2a)), 0)

    def test_copy_data_item_properly_copies_computation(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # setup by adding data item and a dependent data item
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2a = DataItem.DataItem()
            computation = document_model.create_computation("resample_image(src, shape(12, 12)")
            computation.create_object("src", document_model.get_object_specifier(data_item2, "data"))
            data_item2a.append_data_source(DataItem.BufferedDataSource())
            data_item2a.maybe_data_source.set_computation(computation)
            document_model.append_data_item(data_item2)  # add this first
            document_model.append_data_item(data_item2a)  # add this second
            # copy the dependent item
            data_item2a_copy = copy.deepcopy(data_item2a)
            document_model.append_data_item(data_item2a_copy)
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
            data_item2a_copy = copy.deepcopy(data_item2a)
            document_model.append_data_item(data_item2a_copy)
            # verify data source
            self.assertEqual(document_model.resolve_object_specifier(data_item2a.maybe_data_source.computation.variables[0].variable_specifier).data_item, data_item2)
            self.assertEqual(document_model.resolve_object_specifier(data_item2a_copy.maybe_data_source.computation.variables[0].variable_specifier).data_item, data_item2)

    def test_copy_data_item_with_crop(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            source_data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25,0.25), (0.5,0.5)
            source_data_item.maybe_data_source.displays[0].add_graphic(crop_region)
            document_model.append_data_item(source_data_item)
            data_item = document_model.get_crop_new(source_data_item, crop_region)
            data_item_copy = copy.deepcopy(data_item)
            document_model.append_data_item(data_item_copy)
            self.assertNotEqual(data_item_copy.maybe_data_source.computation, data_item.maybe_data_source.computation)
            document_model.recompute_all()
            self.assertEqual(document_model.resolve_object_specifier(data_item_copy.maybe_data_source.computation.variables[1].variable_specifier).value,
                             document_model.resolve_object_specifier(data_item.maybe_data_source.computation.variables[1].variable_specifier).value)

    def test_copy_data_item_with_transaction(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((4, 4), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            with document_model.data_item_transaction(data_item):
                with display_specifier.buffered_data_source.data_ref() as data_ref:
                    data_ref.master_data = numpy.ones((4, 4), numpy.uint32)
                    data_item_copy = copy.deepcopy(data_item)
            display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item_copy)
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                with display_specifier2.buffered_data_source.data_ref() as data_copy_accessor:
                    self.assertEqual(data_copy_accessor.master_data.shape, (4, 4))
                    self.assertTrue(numpy.array_equal(data_ref.master_data, data_copy_accessor.master_data))
                    data_ref.master_data = numpy.ones((4, 4), numpy.uint32) + 1
                    self.assertFalse(numpy.array_equal(data_ref.master_data, data_copy_accessor.master_data))

    def test_clear_thumbnail_when_data_item_changed(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        self.assertTrue(display.is_cached_value_dirty("thumbnail_data"))
        display.get_processor("thumbnail").recompute_data(self.app.ui)
        self.assertIsNotNone(display.get_processed_data("thumbnail"))
        self.assertFalse(display.is_cached_value_dirty("thumbnail_data"))
        with display_specifier.buffered_data_source.data_ref() as data_ref:
            data_ref.master_data = numpy.zeros((8, 8), numpy.uint32)
        self.assertTrue(display.is_cached_value_dirty("thumbnail_data"))

    def test_thumbnail_2d_handles_small_dimension_without_producing_invalid_thumbnail(self):
        data_item = DataItem.DataItem(numpy.zeros((1, 300), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        display.get_processor("thumbnail").recompute_data(self.app.ui)
        thumbnail_data = display.get_processed_data("thumbnail")
        self.assertTrue(functools.reduce(lambda x, y: x * y, thumbnail_data.shape) > 0)

    def test_thumbnail_2d_handles_nan_data(self):
        data = numpy.zeros((16, 16), numpy.float)
        data[:] = numpy.nan
        data_item = DataItem.DataItem(data)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        display.get_processor("thumbnail").recompute_data(self.app.ui)
        self.assertIsNotNone(display_specifier.display.get_processed_data("thumbnail"))

    def test_thumbnail_2d_handles_inf_data(self):
        data = numpy.zeros((16, 16), numpy.float)
        data[:] = numpy.inf
        data_item = DataItem.DataItem(data)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        display.get_processor("thumbnail").recompute_data(self.app.ui)
        self.assertIsNotNone(display_specifier.display.get_processed_data("thumbnail"))

    def test_thumbnail_1d(self):
        data_item = DataItem.DataItem(numpy.zeros((256), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        display.get_processor("thumbnail").recompute_data(self.app.ui)
        self.assertIsNotNone(display_specifier.display.get_processed_data("thumbnail"))

    def test_thumbnail_1d_handles_nan_data(self):
        data = numpy.zeros((256), numpy.float)
        data[:] = numpy.nan
        data_item = DataItem.DataItem(data)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        display.get_processor("thumbnail").recompute_data(self.app.ui)
        self.assertIsNotNone(display_specifier.display.get_processed_data("thumbnail"))

    def test_thumbnail_1d_handles_inf_data(self):
        data = numpy.zeros((256), numpy.float)
        data[:] = numpy.inf
        data_item = DataItem.DataItem(data)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        display.get_processor("thumbnail").recompute_data(self.app.ui)
        self.assertIsNotNone(display_specifier.display.get_processed_data("thumbnail"))

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
            data_item_inverted_display.get_processor("thumbnail").recompute_data(self.app.ui)
            data_item_inverted_display.get_processed_data("thumbnail")
            # here the data should be computed and the thumbnail should not be dirty
            self.assertFalse(data_item_inverted_display.is_cached_value_dirty("thumbnail_data"))
            # now the source data changes and the inverted data needs computing.
            # the thumbnail should also be dirty.
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = data_ref.master_data + 1.0
            document_model.recompute_all()
            self.assertTrue(data_item_inverted_display.is_cached_value_dirty("thumbnail_data"))

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
            self.assertFalse(inverted_display_specifier.buffered_data_source.computation.needs_update)

    def test_data_range(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        # test scalar
        xx, yy = numpy.meshgrid(numpy.linspace(0,1,256), numpy.linspace(0,1,256))
        with display_specifier.buffered_data_source.data_ref() as data_ref:
            data_ref.master_data = 50 * (xx + yy) + 25
            data_range = display_specifier.display.data_range
            self.assertEqual(data_range, (25, 125))
            # now test complex
            data_ref.master_data = numpy.zeros((8, 8), numpy.complex64)
            xx, yy = numpy.meshgrid(numpy.linspace(0,1,256), numpy.linspace(0,1,256))
            data_ref.master_data = (2 + xx * 10) + 1j * (3 + yy * 10)
        data_range = display_specifier.display.data_range
        data_min = math.log(math.sqrt(2*2 + 3*3))
        data_max = math.log(math.sqrt(12*12 + 13*13))
        self.assertEqual(int(data_min*1e6), int(data_range[0]*1e6))
        self.assertEqual(int(data_max*1e6), int(data_range[1]*1e6))

    def test_data_range_gets_updated_after_data_ref_data_updated(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        self.assertEqual(data_item.maybe_data_source.displays[0].data_range, (0, 0))
        with data_item.maybe_data_source.data_ref() as data_ref:
            data_ref.data[:] = 1
            data_ref.data_updated()
        self.assertEqual(data_item.maybe_data_source.displays[0].data_range, (1, 1))

    def test_removing_dependent_data_item_with_graphic(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item.maybe_data_source.displays[0].add_graphic(Graphics.RectangleGraphic())
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
            self.assertFalse(inverted_display_specifier.buffered_data_source.is_data_loaded)

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
            self.assertFalse(display_specifier.buffered_data_source.is_data_loaded)
            with inverted_display_specifier.buffered_data_source.data_ref() as d:
                self.assertFalse(display_specifier.buffered_data_source.is_data_loaded)
            self.assertFalse(display_specifier.buffered_data_source.is_data_loaded)

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
            def data_item_content_changed(changes):
                data_changed_ref[0] = data_changed_ref[0] or DataItem.DATA in changes
            with contextlib.closing(data_item_inverted.data_item_content_changed_event.listen(data_item_content_changed)):
                with display_specifier.buffered_data_source.data_ref() as data_ref:
                    data_ref.master_data = numpy.ones((8, 8), numpy.uint32)
                document_model.recompute_all()
                self.assertTrue(data_changed_ref)
                self.assertFalse(inverted_display_specifier.buffered_data_source.computation.needs_update)

    def test_modifying_source_data_should_trigger_data_item_stale_from_dependent_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            document_model.append_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted_data_item)
            document_model.recompute_all()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = numpy.ones((8, 8), numpy.uint32)
            self.assertTrue(inverted_display_specifier.buffered_data_source.computation.needs_update)

    def test_modifying_source_data_should_queue_recompute_in_document_model(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted_data_item)
            document_model.recompute_all()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = numpy.ones((8, 8), numpy.uint32)
            self.assertTrue(inverted_display_specifier.buffered_data_source.computation.needs_update)
            document_model.recompute_all()
            self.assertFalse(inverted_display_specifier.buffered_data_source.computation.needs_update)

    def test_is_data_stale_should_propagate_to_data_items_dependent_on_source(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted_data_item)
            inverted2_data_item = document_model.get_invert_new(inverted_data_item)
            inverted2_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted2_data_item)
            document_model.recompute_all()
            self.assertFalse(inverted_display_specifier.buffered_data_source.computation.needs_update)
            document_model.recompute_all()
            self.assertFalse(inverted2_display_specifier.buffered_data_source.computation.needs_update)
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = numpy.ones((8, 8), numpy.uint32)
            self.assertTrue(inverted_display_specifier.buffered_data_source.computation.needs_update)
            document_model.recompute_one()
            self.assertTrue(inverted2_display_specifier.buffered_data_source.computation.needs_update)
            document_model.recompute_all()
            self.assertFalse(inverted_display_specifier.buffered_data_source.computation.needs_update)
            self.assertFalse(inverted2_display_specifier.buffered_data_source.computation.needs_update)

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
            self.assertFalse(inverted_display_specifier.buffered_data_source.computation.needs_update)
            data_changed_ref = [0]
            def data_item_content_changed(changes):
                if DataItem.DATA in changes:
                    data_changed_ref[0] += 1
            with contextlib.closing(inverted_data_item.data_item_content_changed_event.listen(data_item_content_changed)):
                with display_specifier.buffered_data_source.data_ref() as data_ref:
                    data_ref.master_data = numpy.ones((8, 8), numpy.uint32)
                self.assertTrue(inverted_display_specifier.buffered_data_source.computation.needs_update)
                self.assertEqual(data_changed_ref[0], 0)
                document_model.recompute_all()
                self.assertFalse(inverted_display_specifier.buffered_data_source.computation.needs_update)
                self.assertEqual(data_changed_ref[0], 1)

    def test_adding_removing_data_item_with_crop_computation_updates_graphics(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.maybe_data_source.displays[0].add_graphic(crop_region)
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
            data_item.maybe_data_source.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item_crop = document_model.get_crop_new(data_item, crop_region)
            self.assertEqual(len(display_specifier.display.graphics), 1)
            data_item_crop.maybe_data_source.set_computation(None)
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
            data_item.maybe_data_source.displays[0].add_graphic(crop_region)
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
            data_item.maybe_data_source.displays[0].add_graphic(crop_region)
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
        data_item.set_metadata(metadata)
        data_item_copy = data_item.snapshot()
        self.assertEqual(data_item_copy.metadata.get("test")["one"], 1)

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
            with document_model.data_item_transaction(data_item):
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
            with document_model.data_item_transaction(data_item):
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
            data_item.maybe_data_source.displays[0].add_graphic(crop_region)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            # begin the transaction
            with document_model.data_item_transaction(data_item):
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
            with document_model.data_item_transaction(data_item):
                document_model.append_data_item(data_item)
                persistent_storage = data_item.persistent_object_context._get_persistent_storage_for_object(data_item)
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
            self.assertFalse(display_specifier.buffered_data_source.computation.needs_update)
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((8, 8), numpy.uint32)
            display_specifier.buffered_data_source.set_intensity_calibration(Calibration.Calibration())
            self.assertFalse(display_specifier.buffered_data_source.computation.needs_update)

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
            self.assertFalse(copied_display_specifier.buffered_data_source.computation.needs_update)
            copied_display_specifier.buffered_data_source.set_intensity_calibration(Calibration.Calibration())
            self.assertFalse(copied_display_specifier.buffered_data_source.computation.needs_update)

    def test_removing_computation_should_not_mark_the_data_as_stale(self):
        # is this test valid any more?
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            copied_data_item = document_model.get_invert_new(data_item)
            document_model.recompute_all()
            self.assertFalse(copied_data_item.maybe_data_source.computation.needs_update)
            copied_data_item.maybe_data_source.set_computation(None)
            document_model.recompute_all()
            self.assertIsNotNone(copied_data_item.maybe_data_source.data)

    def test_changing_computation_should_mark_the_data_as_stale(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.double))
            document_model.append_data_item(data_item)
            copied_data_item = document_model.get_gaussian_blur_new(data_item)
            copied_display_specifier = DataItem.DisplaySpecifier.from_data_item(copied_data_item)
            document_model.recompute_all()
            self.assertFalse(copied_display_specifier.buffered_data_source.computation.needs_update)
            copied_data_item.maybe_data_source.computation.variables[1].value = 0.1
            self.assertTrue(copied_display_specifier.buffered_data_source.computation.needs_update)

    def test_reloading_stale_data_should_still_be_stale(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(inverted_data_item)
            document_model.recompute_all()
            self.assertFalse(inverted_display_specifier.buffered_data_source.computation.needs_update)
            self.assertAlmostEqual(inverted_display_specifier.buffered_data_source.data[0, 0], -1.0)
            # now the source data changes and the inverted data needs computing.
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = data_ref.master_data + 2.0
            self.assertTrue(inverted_display_specifier.buffered_data_source.computation.needs_update)
            # data is now unloaded and stale.
            self.assertFalse(inverted_display_specifier.buffered_data_source.is_data_loaded)
            # don't recompute
            self.assertAlmostEqual(inverted_display_specifier.buffered_data_source.data[0, 0], -1.0)
            # data should still be stale
            self.assertTrue(inverted_display_specifier.buffered_data_source.computation.needs_update)

    def test_recomputing_data_gives_correct_result(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_inverted)
            document_model.recompute_all()
            self.assertAlmostEqual(inverted_display_specifier.buffered_data_source.data[0, 0], -1.0)
            # now the source data changes and the inverted data needs computing.
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = data_ref.master_data + 2.0
            document_model.recompute_all()
            self.assertAlmostEqual(inverted_display_specifier.buffered_data_source.data[0, 0], -3.0)

    def test_recomputing_data_does_not_notify_listeners_of_stale_data_unless_it_is_really_stale(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.assertTrue(display_specifier.display.is_cached_value_dirty("statistics_data"))
            document_model.recompute_all()
            display_specifier.display.get_processor("statistics").recompute_data(None)
            self.assertFalse(display_specifier.display.is_cached_value_dirty("statistics_data_2"))
            document_model.recompute_all()
            self.assertFalse(display_specifier.display.is_cached_value_dirty("statistics_data_2"))

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
            self.assertFalse(inverted_display_specifier.buffered_data_source.computation.needs_update)
            self.assertAlmostEqual(inverted_display_specifier.buffered_data_source.data[0, 0], -1.0)
            # now the source data changes and the inverted data needs computing.
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = data_ref.master_data + 2.0
            # verify the actual data values are still stale
            self.assertAlmostEqual(inverted_display_specifier.buffered_data_source.data[0, 0], -1.0)
            # recompute and verify the data values are valid
            document_model.recompute_all()
            self.assertAlmostEqual(inverted_display_specifier.buffered_data_source.data[0, 0], -3.0)

    def test_statistics_marked_dirty_when_data_changed(self):
        data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertTrue(display_specifier.display.is_cached_value_dirty("statistics_data_2"))
        display_specifier.display.get_processor("statistics").recompute_data(None)
        self.assertIsNotNone(display_specifier.display.get_processed_data("statistics"))
        self.assertFalse(display_specifier.display.is_cached_value_dirty("statistics_data_2"))
        with display_specifier.buffered_data_source.data_ref() as data_ref:
            data_ref.master_data = data_ref.master_data + 1.0
        self.assertTrue(display_specifier.display.is_cached_value_dirty("statistics_data_2"))

    def test_statistics_marked_dirty_when_source_data_changed(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((8, 8), numpy.double))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_inverted)
            inverted_display_specifier.display.get_processor("statistics").recompute_data(None)
            inverted_display_specifier.display.get_processed_data("statistics")
            # here the data should be computed and the statistics should not be dirty
            self.assertFalse(inverted_display_specifier.display.is_cached_value_dirty("statistics_data_2"))
            # now the source data changes and the inverted data needs computing.
            # the statistics should also be dirty.
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = data_ref.master_data + 1.0
            document_model.recompute_all()
            self.assertTrue(inverted_display_specifier.display.is_cached_value_dirty("statistics_data_2"))

    def test_statistics_marked_dirty_when_source_data_recomputed(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item_inverted = document_model.get_invert_new(data_item)
            inverted_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_inverted)
            inverted_display_specifier.display.get_processor("statistics").recompute_data(None)
            inverted_display_specifier.display.get_processed_data("statistics")
            # here the data should be computed and the statistics should not be dirty
            self.assertFalse(inverted_display_specifier.display.is_cached_value_dirty("statistics_data_2"))
            # now the source data changes and the inverted data needs computing.
            # the statistics should also be dirty.
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data = data_ref.master_data + 2.0
            document_model.recompute_all()
            self.assertTrue(inverted_display_specifier.display.is_cached_value_dirty("statistics_data_2"))
            # next recompute data, the statistics should be dirty now.
            document_model.recompute_all()
            self.assertTrue(inverted_display_specifier.display.is_cached_value_dirty("statistics_data_2"))
            # get the new statistics and verify they are correct.
            inverted_display_specifier.display.get_processor("statistics").recompute_data(None)
            good_statistics = inverted_display_specifier.display.get_processed_data("statistics")
            self.assertTrue(good_statistics["mean"] == -3.0)

    def test_statistics_calculated_on_slice_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.abs(numpy.random.randn(8, 2, 2) * 100).astype(numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.get_processor("statistics").recompute_data(None)
            stats = display_specifier.display.get_processed_data("statistics")
            self.assertAlmostEqual(stats.get("sum"), numpy.sum(data_item.maybe_data_source.data[0:1]))
            display_specifier.display.slice_center = 3
            display_specifier.display.slice_width = 3
            display_specifier.display.get_processor("statistics").recompute_data(None)
            stats = display_specifier.display.get_processed_data("statistics")
            self.assertAlmostEqual(stats.get("sum"), numpy.sum(data_item.maybe_data_source.data[2:5]))
            display_specifier.display.slice_center = 4
            display_specifier.display.slice_width = 4
            display_specifier.display.get_processor("statistics").recompute_data(None)
            stats = display_specifier.display.get_processed_data("statistics")
            self.assertAlmostEqual(stats.get("sum"), numpy.sum(data_item.maybe_data_source.data[2:6]))

    def test_histogram_calculated_on_slice_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(((numpy.random.randn(8, 20, 20) * 100) ** 2).astype(numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.display.get_processor("histogram").recompute_data(None)
            histogram = display_specifier.display.get_processed_data("histogram")
            display_specifier.display.slice_center = 4
            display_specifier.display.slice_width = 4
            display_specifier.display.get_processor("histogram").recompute_data(None)
            histogram = display_specifier.display.get_processed_data("histogram")

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
            data_item.set_metadata(data_item.metadata)
            self.assertGreater(data_item.modified, modified)

    def test_adding_data_source_updates_modified(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            data_item._set_modified(datetime.datetime(2000, 1, 1))
            modified = data_item.modified
            data_item.append_data_source(DataItem.BufferedDataSource())
            self.assertGreater(data_item.modified, modified)

    def test_changing_property_on_display_updates_modified(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            data_item._set_modified(datetime.datetime(2000, 1, 1))
            modified = data_item.modified
            data_item.data_sources[0].displays[0].display_calibrated_values = False
            self.assertGreater(data_item.modified, modified)

    def test_changing_data_on_buffered_data_source_updates_modified(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
            document_model.append_data_item(data_item)
            data_item._set_modified(datetime.datetime(2000, 1, 1))
            modified = data_item.modified
            with data_item.data_sources[0].data_ref() as data_ref:
                data_ref.master_data = numpy.zeros((2, 2))
            self.assertGreater(data_item.modified, modified)

    def test_data_item_in_transaction_does_not_write_until_end_of_transaction(self):
        memory_persistent_storage_system = DocumentModel.MemoryPersistentStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            with document_model.data_item_transaction(data_item):
                document_model.append_data_item(data_item)
                self.assertEqual(len(memory_persistent_storage_system.data.keys()), 0)
            self.assertEqual(len(memory_persistent_storage_system.data.keys()), 1)

    def test_extra_changing_data_item_session_id_in_transaction_does_not_result_in_duplicated_data_items(self):
        memory_persistent_storage_system = DocumentModel.MemoryPersistentStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            with document_model.data_item_transaction(data_item):
                data_item.session_id = "20000630-150200"
                document_model.append_data_item(data_item)
                self.assertEqual(len(memory_persistent_storage_system.data.keys()), 0)
                data_item.session_id = "20000630-150201"
            self.assertEqual(len(memory_persistent_storage_system.data.keys()), 1)

    def test_changing_data_item_session_id_in_transaction_does_not_result_in_duplicated_data_items(self):
        memory_persistent_storage_system = DocumentModel.MemoryPersistentStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            with document_model.data_item_transaction(data_item):
                data_item.session_id = "20000630-150200"
                document_model.append_data_item(data_item)
            self.assertEqual(len(memory_persistent_storage_system.data.keys()), 1)
            with document_model.data_item_transaction(data_item):
                data_item.session_id = "20000630-150201"
            self.assertEqual(len(memory_persistent_storage_system.data.keys()), 1)

    def test_processed_data_item_has_source_data_modified_equal_to_sources_data_modifed(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            document_model.append_data_item(src_data_item)
            time.sleep(0.01)
            data_item = document_model.get_invert_new(src_data_item)
            document_model.recompute_all()
            self.assertIsNotNone(src_data_item.maybe_data_source.data_modified)
            self.assertGreaterEqual(data_item.maybe_data_source.data_modified, src_data_item.maybe_data_source.data_modified)

    def test_processed_data_item_has_source_data_modified_equal_to_sources_created_when_sources_data_modified_is_none(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            src_data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.uint32))
            src_data_item.maybe_data_source.data_modified = None
            document_model.append_data_item(src_data_item)
            time.sleep(0.01)
            data_item = document_model.get_invert_new(src_data_item)
            document_model.recompute_all()
            self.assertGreaterEqual(data_item.maybe_data_source.data_modified, src_data_item.maybe_data_source.created)

    def test_transaction_does_not_cascade_to_data_item_refs(self):
        # no reason to cascade since there is no high cost data to be loaded for aggregate data items
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((4, 4))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((4, 4))))
            master_data_item = DataItem.DataItem()
            master_data_item.append_data_item(document_model.data_items[0])
            master_data_item.append_data_item(document_model.data_items[1])
            document_model.append_data_item(master_data_item)
            self.assertFalse(master_data_item.in_transaction_state)
            self.assertFalse(document_model.data_items[0].in_transaction_state)
            self.assertFalse(document_model.data_items[1].in_transaction_state)
            with document_model.data_item_transaction(master_data_item):
                self.assertTrue(master_data_item.in_transaction_state)
                self.assertFalse(document_model.data_items[0].in_transaction_state)
                self.assertFalse(document_model.data_items[1].in_transaction_state)

    def test_increment_data_ref_counts_cascades_to_data_item_refs(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((4, 4))))
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((4, 4))))
            master_data_item = DataItem.DataItem()
            master_data_item.append_data_item(document_model.data_items[0])
            master_data_item.append_data_item(document_model.data_items[1])
            document_model.append_data_item(master_data_item)
            self.assertFalse(document_model.data_items[0].maybe_data_source.is_data_loaded)
            self.assertFalse(document_model.data_items[1].maybe_data_source.is_data_loaded)
            master_data_item.increment_data_ref_counts()
            self.assertTrue(document_model.data_items[0].maybe_data_source.is_data_loaded)
            self.assertTrue(document_model.data_items[1].maybe_data_source.is_data_loaded)
            master_data_item.decrement_data_ref_counts()
            self.assertFalse(document_model.data_items[0].maybe_data_source.is_data_loaded)
            self.assertFalse(document_model.data_items[1].maybe_data_source.is_data_loaded)

    def test_dependent_calibration(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            display_specifier.buffered_data_source.set_dimensional_calibration(0, Calibration.Calibration(3.0, 2.0, u"x"))
            display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(3.0, 2.0, u"x"))
            self.assertEqual(len(display_specifier.buffered_data_source.dimensional_calibrations), 2)
            data_item_copy = document_model.get_invert_new(data_item)
            display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item_copy)
            document_model.recompute_all()
            dimensional_calibrations = display_specifier2.buffered_data_source.dimensional_calibrations
            self.assertEqual(len(dimensional_calibrations), 2)
            self.assertEqual(int(dimensional_calibrations[0].offset), 3)
            self.assertEqual(int(dimensional_calibrations[0].scale), 2)
            self.assertEqual(dimensional_calibrations[0].units, "x")
            self.assertEqual(int(dimensional_calibrations[1].offset), 3)
            self.assertEqual(int(dimensional_calibrations[1].scale), 2)
            self.assertEqual(dimensional_calibrations[1].units, "x")
            fft_data_item = document_model.get_fft_new(data_item)
            document_model.recompute_all()
            dimensional_calibrations = fft_data_item.maybe_data_source.dimensional_calibrations
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
            self.assertIsNotNone(display_specifier3.buffered_data_source.dimensional_calibrations)

    def test_spatial_calibration_on_rgb(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertTrue(Image.is_shape_and_dtype_2d(*display_specifier.buffered_data_source.data_shape_and_dtype))
        self.assertTrue(Image.is_shape_and_dtype_rgba(*display_specifier.buffered_data_source.data_shape_and_dtype))
        self.assertEqual(len(display_specifier.buffered_data_source.dimensional_calibrations), 2)

    # modify property/item/relationship on data source, display, region, etc.
    # copy or snapshot

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
