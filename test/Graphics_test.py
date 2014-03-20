# standard libraries
import copy
import logging
import unittest

# third party libraries
# None

# local libraries
from nion.swift.model import Graphics


class TestGraphicsClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    class Mapping(object):
        def __init__(self, size):
            self.size = size
        def map_point_image_norm_to_widget(self, p):
            return (p[0] * self.size[0], p[1] * self.size[1])
        def map_size_image_norm_to_widget(self, s):
            return (s[0] * self.size[0], s[1] * self.size[1])
        def map_point_widget_to_image_norm(self, p):
            return (s[0]/self.size[0], s[1]/self.size[1])

    def test_copy_graphic(self):
        rect_graphic = Graphics.RectangleGraphic()
        copy.deepcopy(rect_graphic)
        ellipse_graphic = Graphics.EllipseGraphic()
        copy.deepcopy(ellipse_graphic)
        line_graphic = Graphics.LineGraphic()
        copy.deepcopy(line_graphic)

    def test_line_test(self):
        mapping = TestGraphicsClass.Mapping((1000, 1000))
        line_graphic = Graphics.LineGraphic()
        line_graphic.start = (0.25,0.25)
        line_graphic.end = (0.75,0.75)
        self.assertEqual(line_graphic.test(mapping, (500, 500), move_only=True), "all")
        self.assertEqual(line_graphic.test(mapping, (250, 250), move_only=True), "all")
        self.assertEqual(line_graphic.test(mapping, (750, 750), move_only=True), "all")
        self.assertEqual(line_graphic.test(mapping, (250, 250), move_only=False), "start")
        self.assertEqual(line_graphic.test(mapping, (750, 750), move_only=False), "end")
        self.assertIsNone(line_graphic.test(mapping, (240, 240), move_only=False))
        self.assertIsNone(line_graphic.test(mapping, (760, 760), move_only=False))
        self.assertIsNone(line_graphic.test(mapping, (0, 0), move_only=False))

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
