# futures
from __future__ import absolute_import

# standard libraries
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift.model import Image


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

    def test_rebin_expand_has_even_expansion(self):
        # NOTE: statistical tests are only valid if expanded length is multiple of src length
        src = numpy.arange(0, 10)
        expanded = Image.rebin_1d(src, 50)
        self.assertAlmostEqual(numpy.mean(src), numpy.mean(expanded))
        self.assertAlmostEqual(numpy.var(src), numpy.var(expanded))
        src = numpy.arange(0, 10)
        expanded = Image.rebin_1d(src, 500)
        self.assertAlmostEqual(numpy.mean(src), numpy.mean(expanded))
        self.assertAlmostEqual(numpy.var(src), numpy.var(expanded))
        # test larger values to make sure linear mapping works (failed once)
        src = numpy.arange(0, 200)
        expanded = Image.rebin_1d(src, 600)
        self.assertAlmostEqual(numpy.mean(src), numpy.mean(expanded))
        self.assertAlmostEqual(numpy.var(src), numpy.var(expanded))
