# futures
from __future__ import absolute_import

# standard libraries
import logging
import unittest

# third party libraries
# None

# local libraries
from nion.swift import Application
from nion.swift import ImageCanvasItem
from nion.ui import Geometry
from nion.ui import Test


class TestOperationClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    # make sure we can remove a single operation
    def test_mapping_widget_to_image_on_3d_data_uses_last_two_dimensions(self):
        canvas_size = Geometry.FloatSize(100, 100)
        canvas_origin = Geometry.FloatPoint(0, 0)
        dimensional_size = (256, 16, 16)
        widget_mapping = ImageCanvasItem.ImageCanvasItemMapping(dimensional_size, canvas_origin, canvas_size)
        # image_norm_to_widget
        image_norm_point = Geometry.FloatPoint(0.5, 0.5)
        widget_point = widget_mapping.map_point_image_norm_to_widget(image_norm_point)
        self.assertEqual(widget_point, Geometry.FloatPoint(50, 50))
        # widget_to_image
        self.assertEqual(widget_mapping.map_point_widget_to_image(Geometry.FloatPoint(50, 50)), Geometry.FloatPoint(8, 8))

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
