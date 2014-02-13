# standard libraries
import unittest

# third party libraries
import numpy

# local libraries
from nion.imaging import Image


class TestImageClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_create_rgba_image_from_array(self):
        image_1d_16 = numpy.zeros((16, ), dtype=numpy.double)
        image_1d_16x1 = numpy.zeros((16, 1), dtype=numpy.double)
        self.assertIsNotNone(Image.create_rgba_image_from_array(image_1d_16))
        self.assertIsNotNone(Image.create_rgba_image_from_array(image_1d_16x1))
        image_1d_rgb = numpy.zeros((16, 3), dtype=numpy.uint8)
        self.assertIsNotNone(Image.create_rgba_image_from_array(image_1d_rgb))
