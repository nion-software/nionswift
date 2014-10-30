# standard libraries
import logging
import numpy
import unittest

# third party libraries
# None

# local libraries
from nion.swift import Application
from nion.swift.model import LineGraphCanvasItem
from nion.ui import Test


class TestLineGraphCanvasItem(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_data_values_give_pretty_limits_when_auto(self):

        test_ranges = (
            ((7.46, 85.36), (0.0, 100.0)),
            ((7.67, 12.95), (0.0, 15.0)),
            ((6.67, 11.95), (0.0, 15.0)),
            ((0.00, 0.00), (0.0, 0.0))
        )

        for data_in, data_out in test_ranges:
            data_min, data_max = data_in
            expected_drawn_data_min, expected_drawn_data_max = data_out
            data = numpy.zeros((16, 16), dtype=numpy.float64)
            irow, icol = numpy.ogrid[0:16, 0:16]
            data[:] = data_min + (data_max - data_min) * (irow / 15.0)
            # auto on min/max
            data_info = LineGraphCanvasItem.LineGraphDataInfo(data, None, None)
            self.assertEqual(data_info.drawn_data_min, expected_drawn_data_min)
            self.assertEqual(data_info.drawn_data_max, expected_drawn_data_max)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
