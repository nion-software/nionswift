# standard libraries
import logging
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

    def test_data_values_give_pretty_limits(self):

        test_ranges = (
            ((7.46, 85.36), (0.0, 90.0)),
            ((7.67, 12.95), (0.0, 14.0)),
            ((6.67, 11.95), (0.0, 12.0))
        )

        for data_in, data_out in test_ranges:
            data_min, data_max = data_in
            expected_drawn_data_min, expected_drawn_data_max = data_out
            drawn_data_min, drawn_data_max = LineGraphCanvasItem.get_drawn_data_limits(data_min, data_max)
            self.assertEqual(drawn_data_min, expected_drawn_data_min)
            self.assertEqual(drawn_data_max, expected_drawn_data_max)
            drawn_data_min, drawn_data_max = LineGraphCanvasItem.get_drawn_data_limits(-data_min, -data_max)
            self.assertEqual(drawn_data_min, -expected_drawn_data_max)
            self.assertEqual(drawn_data_max, -expected_drawn_data_min)



if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
