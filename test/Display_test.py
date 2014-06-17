# standard libraries
import threading
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
        event = threading.Event()
        def update_histogram_data(histogram_data):
            event.set()
        display.get_processed_data("histogram", None, completion_fn=update_histogram_data)
        event.wait()
        self.assertFalse(display.is_cached_value_dirty("histogram_data"))
        display.display_limits = (0.25, 0.75)
        self.assertTrue(display.is_cached_value_dirty("histogram_data"))

    def test_changing_display_limits_clears_histogram_data_cache_before_reporting_display_change(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        display = data_item.displays[0]
        self.assertTrue(display.is_cached_value_dirty("histogram_data"))
        event = threading.Event()
        def update_histogram_data(histogram_data):
            event.set()
        display.get_processed_data("histogram", None, completion_fn=update_histogram_data)
        event.wait()
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

if __name__ == '__main__':
    unittest.main()
