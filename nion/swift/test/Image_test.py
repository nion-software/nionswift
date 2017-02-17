# futures
from __future__ import absolute_import

# standard libraries
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Image


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

    def test_scale_cubic_is_symmetry(self):
        src1 = numpy.zeros((8, 8))
        src2 = numpy.zeros((9, 9))
        src1[3:5, 3:5] = 1
        src2[3:6, 3:6] = 1
        src1s = (Image.scaled(src1, (12, 12), 'cubic')*1000).astype(numpy.int)
        src2s = (Image.scaled(src1, (12, 12), 'cubic')*1000).astype(numpy.int)
        src1t = (Image.scaled(src1, (13, 13), 'cubic')*1000).astype(numpy.int)
        src2t = (Image.scaled(src1, (13, 13), 'cubic')*1000).astype(numpy.int)
        self.assertTrue(numpy.array_equal(src1s[0:6, 0:6], src1s[0:6, 12:5:-1]))
        self.assertTrue(numpy.array_equal(src1s[0:6, 0:6], src1s[12:5:-1, 12:5:-1]))
        self.assertTrue(numpy.array_equal(src1s[0:6, 0:6], src1s[12:5:-1, 0:6]))
        self.assertTrue(numpy.array_equal(src2s[0:6, 0:6], src2s[0:6, 12:5:-1]))
        self.assertTrue(numpy.array_equal(src2s[0:6, 0:6], src2s[12:5:-1, 12:5:-1]))
        self.assertTrue(numpy.array_equal(src2s[0:6, 0:6], src2s[12:5:-1, 0:6]))
        self.assertTrue(numpy.array_equal(src1t[0:6, 0:6], src1t[0:6, 13:6:-1]))
        self.assertTrue(numpy.array_equal(src1t[0:6, 0:6], src1t[13:6:-1, 13:6:-1]))
        self.assertTrue(numpy.array_equal(src1t[0:6, 0:6], src1t[13:6:-1, 0:6]))
        self.assertTrue(numpy.array_equal(src2t[0:6, 0:6], src2t[0:6, 13:6:-1]))
        self.assertTrue(numpy.array_equal(src2t[0:6, 0:6], src2t[13:6:-1, 13:6:-1]))
        self.assertTrue(numpy.array_equal(src2t[0:6, 0:6], src2t[13:6:-1, 0:6]))

    def test_scale_linear_is_symmetry(self):
        src1 = numpy.zeros((8, 8))
        src2 = numpy.zeros((9, 9))
        src1[3:5, 3:5] = 1
        src2[3:6, 3:6] = 1
        src1s = (Image.scaled(src1, (12, 12), 'linear')*1000).astype(numpy.int)
        src2s = (Image.scaled(src1, (12, 12), 'linear')*1000).astype(numpy.int)
        src1t = (Image.scaled(src1, (13, 13), 'linear')*1000).astype(numpy.int)
        src2t = (Image.scaled(src1, (13, 13), 'linear')*1000).astype(numpy.int)
        self.assertTrue(numpy.array_equal(src1s[0:6, 0:6], src1s[0:6, 12:5:-1]))
        self.assertTrue(numpy.array_equal(src1s[0:6, 0:6], src1s[12:5:-1, 12:5:-1]))
        self.assertTrue(numpy.array_equal(src1s[0:6, 0:6], src1s[12:5:-1, 0:6]))
        self.assertTrue(numpy.array_equal(src2s[0:6, 0:6], src2s[0:6, 12:5:-1]))
        self.assertTrue(numpy.array_equal(src2s[0:6, 0:6], src2s[12:5:-1, 12:5:-1]))
        self.assertTrue(numpy.array_equal(src2s[0:6, 0:6], src2s[12:5:-1, 0:6]))
        self.assertTrue(numpy.array_equal(src1t[0:6, 0:6], src1t[0:6, 13:6:-1]))
        self.assertTrue(numpy.array_equal(src1t[0:6, 0:6], src1t[13:6:-1, 13:6:-1]))
        self.assertTrue(numpy.array_equal(src1t[0:6, 0:6], src1t[13:6:-1, 0:6]))
        self.assertTrue(numpy.array_equal(src2t[0:6, 0:6], src2t[0:6, 13:6:-1]))
        self.assertTrue(numpy.array_equal(src2t[0:6, 0:6], src2t[13:6:-1, 13:6:-1]))
        self.assertTrue(numpy.array_equal(src2t[0:6, 0:6], src2t[13:6:-1, 0:6]))
