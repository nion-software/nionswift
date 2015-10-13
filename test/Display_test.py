# futures
from __future__ import absolute_import
from __future__ import division

# standard libraries
import contextlib
import copy
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.ui import Test


class TestDisplayClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_changing_display_limits_clears_histogram_data_cache(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        self.assertTrue(display.is_cached_value_dirty("histogram_data"))
        display.get_processor("histogram").recompute_data(None)
        display.get_processed_data("histogram")
        self.assertFalse(display.is_cached_value_dirty("histogram_data"))
        display.display_limits = (0.25, 0.75)
        self.assertTrue(display.is_cached_value_dirty("histogram_data"))

    def test_changing_display_limits_clears_histogram_data_cache_before_reporting_display_change(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        self.assertTrue(display.is_cached_value_dirty("histogram_data"))
        display.get_processor("histogram").recompute_data(None)
        display.get_processed_data("histogram")
        self.assertFalse(display.is_cached_value_dirty("histogram_data"))
        dirty_ref = [False]
        def display_changed():
            dirty_ref[0] = display.is_cached_value_dirty("histogram_data")
        with contextlib.closing(display.display_changed_event.listen(display_changed)):
            display.display_limits = (0.25, 0.75)
            self.assertTrue(dirty_ref[0])

    def test_setting_inverted_display_limits_reverses_them(self):
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        display.display_limits = (0.75, 0.25)
        self.assertEqual(display.display_limits, (0.25, 0.75))
        display.display_limits = None
        self.assertIsNone(display.display_limits)

    def test_display_produces_valid_preview_when_viewing_3d_data_set(self):
        data_item = DataItem.DataItem(numpy.zeros((16, 16, 16), numpy.float64))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        self.assertIsNotNone(display.preview_2d_data)

    def test_changing_data_updates_display_range(self):
        irow, icol = numpy.ogrid[0:16, 0:16]
        data_item = DataItem.DataItem(icol, numpy.uint32)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        self.assertEqual(display.display_range, (0, 15))
        self.assertEqual(display.data_range, (0, 15))
        with display_specifier.buffered_data_source.data_ref() as dr:
            dr.data = irow // 2 + 4
        self.assertEqual(display.display_range, (4, 11))
        self.assertEqual(display.data_range, (4, 11))

    def test_changing_data_notifies_data_and_display_range_change(self):
        # this is used to update the inspector
        irow, icol = numpy.ogrid[0:16, 0:16]
        data_item = DataItem.DataItem(icol, numpy.uint32)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        class Observer(object):
            def __init__(self):
                self.data_range = None
                self.display_range = None
            def property_changed(self, object, property, value):
                if property == "display_range":
                    self.display_range = value
                if property == "data_range":
                    self.data_range = value
        o = Observer()
        display.add_observer(o)
        with display_specifier.buffered_data_source.data_ref() as dr:
            dr.data = irow // 2 + 4
        self.assertEqual(o.data_range, (4, 11))
        self.assertEqual(o.display_range, (4, 11))

    def test_data_item_copy_initialized_display_data_range(self):
        source_data_item = DataItem.DataItem(numpy.zeros((16, 16, 16), numpy.float64))
        data_item = copy.deepcopy(source_data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertIsNotNone(display_specifier.display.data_range)

    def test_data_item_setting_slice_width_validates_when_invalid(self):
        data_item = DataItem.DataItem(numpy.ones((16, 16, 16), numpy.float64))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_specifier.display.slice_center = 8
        display_specifier.display.slice_width = 0
        self.assertEqual(display_specifier.display.slice_width, 1)
        display_specifier.display.slice_width = -1
        self.assertEqual(display_specifier.display.slice_width, 1)
        display_specifier.display.slice_width = 20
        self.assertEqual(display_specifier.display.slice_width, 16)

    def test_data_item_setting_slice_center_validates_when_invalid(self):
        data_item = DataItem.DataItem(numpy.ones((16, 16, 16), numpy.float64))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display_specifier.display.slice_center = 8
        display_specifier.display.slice_width = 8
        display_specifier.display.slice_center = 0
        self.assertEqual(display_specifier.display.slice_center, 4)
        display_specifier.display.slice_center = 3
        self.assertEqual(display_specifier.display.slice_center, 4)
        display_specifier.display.slice_center = -1
        self.assertEqual(display_specifier.display.slice_center, 4)
        display_specifier.display.slice_center = 5.5
        self.assertEqual(display_specifier.display.slice_center, 5)
        display_specifier.display.slice_center = 12
        self.assertEqual(display_specifier.display.slice_center, 12)
        display_specifier.display.slice_center = 13
        self.assertEqual(display_specifier.display.slice_center, 12)
        display_specifier.display.slice_center = 20
        self.assertEqual(display_specifier.display.slice_center, 12)

    def test_data_item_setting_slice_validates_when_data_changes(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            d = numpy.random.randn(12, 8, 8)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            map = {"a": document_model.get_object_specifier(data_item)}
            data_item2 = document_controller.processing_calculation("a[0:8,:,:]", map)
            document_model.recompute_all()
            assert numpy.array_equal(data_item2.maybe_data_source.data, d[0:8,:,:])
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item2)
            display_specifier.display.slice_center = 6
            display_specifier.display.slice_width = 4
            self.assertEqual(display_specifier.display.slice_center, 6)
            self.assertEqual(display_specifier.display.slice_width, 4)
            display_specifier.buffered_data_source.computation.parse_expression(document_model, "a[0:4, :, :]", map)
            document_model.recompute_all()
            self.assertEqual(display_specifier.display.slice_center, 3)
            self.assertEqual(display_specifier.display.slice_width, 2)


if __name__ == '__main__':
    unittest.main()
