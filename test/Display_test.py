# standard libraries
import copy
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.ui import Test


class TestDisplayClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_changing_display_limits_clears_histogram_data_cache(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        display = data_item.displays[0]
        self.assertTrue(display.is_cached_value_dirty("histogram_data"))
        display.get_processor("histogram").recompute_data(None)
        display.get_processed_data("histogram")
        self.assertFalse(display.is_cached_value_dirty("histogram_data"))
        display.display_limits = (0.25, 0.75)
        self.assertTrue(display.is_cached_value_dirty("histogram_data"))

    def test_changing_display_limits_clears_histogram_data_cache_before_reporting_display_change(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        display = data_item.displays[0]
        self.assertTrue(display.is_cached_value_dirty("histogram_data"))
        display.get_processor("histogram").recompute_data(None)
        display.get_processed_data("histogram")
        self.assertFalse(display.is_cached_value_dirty("histogram_data"))
        class Listener(object):
            def __init__(self):
                self.reset()
            def reset(self):
                self._dirty = False
            def display_changed(self, display):
                self._dirty = display.is_cached_value_dirty("histogram_data")
        listener = Listener()
        display.add_listener(listener)
        display.display_limits = (0.25, 0.75)
        self.assertTrue(listener._dirty)

    def test_setting_inverted_display_limits_reverses_them(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        display = data_item.displays[0]
        display.display_limits = (0.75, 0.25)
        self.assertEqual(display.display_limits, (0.25, 0.75))
        display.display_limits = None
        self.assertIsNone(display.display_limits)

    def test_display_produces_valid_preview_when_viewing_3d_data_set(self):
        data_item = DataItem.DataItem(numpy.zeros((16, 16, 16), numpy.float64))
        display = data_item.displays[0]
        self.assertIsNotNone(display.preview_2d_data)

    def test_changing_data_updates_display_range(self):
        irow, icol = numpy.ogrid[0:16, 0:16]
        data_item = DataItem.DataItem(icol, numpy.uint32)
        display = data_item.displays[0]
        self.assertEqual(display.display_range, (0, 15))
        self.assertEqual(display.data_range, (0, 15))
        with data_item.maybe_data_source.data_ref() as dr:
            dr.data = irow / 2 + 4
        self.assertEqual(display.display_range, (4, 11))
        self.assertEqual(display.data_range, (4, 11))

    def test_changing_data_notifies_data_and_display_range_change(self):
        # this is used to update the inspector
        irow, icol = numpy.ogrid[0:16, 0:16]
        data_item = DataItem.DataItem(icol, numpy.uint32)
        display = data_item.displays[0]
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
        with data_item.maybe_data_source.data_ref() as dr:
            dr.data = irow / 2 + 4
        self.assertEqual(o.data_range, (4, 11))
        self.assertEqual(o.display_range, (4, 11))

    def test_data_item_copy_initialized_display_data_range(self):
        source_data_item = DataItem.DataItem(numpy.zeros((16, 16, 16), numpy.float64))
        data_item = copy.deepcopy(source_data_item)
        display = data_item.maybe_data_source.displays[0]
        self.assertIsNotNone(display.data_range)


if __name__ == '__main__':
    unittest.main()
