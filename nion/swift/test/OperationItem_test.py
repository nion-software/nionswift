# standard libraries
import contextlib
import copy
import functools
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Facade
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.test import TestContext
from nion.utils import Geometry


Facade.initialize()


class TestProcessingClass(unittest.TestCase):

    def setUp(self):
        self.test_context = TestContext.create_memory_context()
        self.document_controller = self.test_context.create_document_controller_with_application()
        self.document_model = self.document_controller.document_model
        self.display_panel = self.document_controller.selected_display_panel
        self.data_item = DataItem.DataItem(numpy.zeros((10, 10)))
        self.display_item = self.document_model.get_display_item_for_data_item(self.data_item)
        self.document_model.append_data_item(self.data_item)
        self.display_panel.set_display_panel_display_item(self.display_item)

    def tearDown(self):
        self.test_context.close()

    # test processing against 1d data. doesn't test for correctness of the processing.
    def test_processing_1d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((256), numpy.double))
        self.document_model.append_data_item(data_item_real)

        data_item_complex = DataItem.DataItem(numpy.zeros((256), numpy.complex128))
        self.document_model.append_data_item(data_item_complex)

        processing_list = []
        processing_list.append((data_item_real, self.document_model.get_fft_new, {}))
        processing_list.append((data_item_complex, self.document_model.get_ifft_new, {}))
        processing_list.append((data_item_real, self.document_model.get_invert_new, {}))
        processing_list.append((data_item_real, self.document_model.get_sobel_new, {}))
        processing_list.append((data_item_real, self.document_model.get_laplace_new, {}))
        processing_list.append((data_item_real, self.document_model.get_gaussian_blur_new, {}))
        processing_list.append((data_item_real, self.document_model.get_median_filter_new, {}))
        processing_list.append((data_item_real, self.document_model.get_uniform_filter_new, {}))
        processing_list.append((data_item_real, self.document_model.get_histogram_new, {}))
        processing_list.append((data_item_real, self.document_model.get_convert_to_scalar_new, {}))
        processing_list.append((data_item_real, self.document_model.get_transpose_flip_new, {"do_transpose": True, "do_flip_v": True, "do_flip_h": True}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(self.document_model.get_display_item_for_data_item(source_data_item), source_data_item)
            for name, value in params.items():
                self.document_model.get_data_item_computation(data_item)._set_variable_value(name, value)
            display_item = self.document_model.get_display_item_for_data_item(data_item)
            self.document_model.recompute_all()
            with display_item.data_item.data_ref() as data_ref:
                src_data_item = self.document_model.get_data_item_computation(data_item).get_input("src").data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_item.data_item.dimensional_calibrations)
                self.assertEqual(display_item.data_item.data_shape, data_ref.data.shape)
                self.assertEqual(display_item.data_item.data_dtype, data_ref.data.dtype)
                self.assertIsNotNone(display_item.data_item.data_dtype.type)  # make sure we're returning a dtype
                self.assertEqual(len(display_item.data_item.dimensional_shape), len(display_item.data_item.dimensional_calibrations))

    # test processing against 2d data. doesn't test for correctness of the processing.
    def test_processing_2d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((8, 8), numpy.double))
        self.document_model.append_data_item(data_item_real)

        processing_list = []
        processing_list.append((data_item_real, self.document_model.get_fft_new, {}))
        processing_list.append((data_item_real, self.document_model.get_invert_new, {}))
        processing_list.append((data_item_real, self.document_model.get_sobel_new, {}))
        processing_list.append((data_item_real, self.document_model.get_laplace_new, {}))
        processing_list.append((data_item_real, self.document_model.get_auto_correlate_new, {}))
        processing_list.append((data_item_real, self.document_model.get_gaussian_blur_new, {}))
        processing_list.append((data_item_real, self.document_model.get_median_filter_new, {}))
        processing_list.append((data_item_real, self.document_model.get_uniform_filter_new, {}))
        processing_list.append((data_item_real, self.document_model.get_crop_new, {}))
        processing_list.append((data_item_real, self.document_model.get_transpose_flip_new, {"do_transpose": True, "do_flip_v": True, "do_flip_h": True}))
        processing_list.append((data_item_real, self.document_model.get_rebin_new, {"width": 128, "height": 128}))
        processing_list.append((data_item_real, self.document_model.get_resample_new, {"width": 128, "height": 128}))
        processing_list.append((data_item_real, self.document_model.get_resize_new, {"width": 128, "height": 128}))
        processing_list.append((data_item_real, self.document_model.get_histogram_new, {}))
        processing_list.append((data_item_real, self.document_model.get_line_profile_new, {}))
        processing_list.append((data_item_real, self.document_model.get_projection_new, {}))
        processing_list.append((data_item_real, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(self.document_model.get_display_item_for_data_item(source_data_item), source_data_item)
            for name, value in params.items():
                self.document_model.get_data_item_computation(data_item)._set_variable_value(name, value)
            display_item = self.document_model.get_display_item_for_data_item(data_item)
            self.document_model.recompute_all()
            with display_item.data_item.data_ref() as data_ref:
                src_data_item = self.document_model.get_data_item_computation(data_item).get_input("src").data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_item.data_item.dimensional_calibrations)
                self.assertEqual(display_item.data_item.data_shape, data_ref.data.shape)
                self.assertEqual(display_item.data_item.data_dtype, data_ref.data.dtype)
                self.assertIsNotNone(display_item.data_item.data_dtype.type)  # make sure we're returning a dtype
                self.assertEqual(len(display_item.data_item.dimensional_shape), len(display_item.data_item.dimensional_calibrations))

    # test processing against 2d data. doesn't test for correctness of the processing.
    def test_processing_3d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((16,16,256), numpy.double))
        self.document_model.append_data_item(data_item_real)

        processing_list = []
        processing_list.append((data_item_real, self.document_model.get_slice_sum_new, {}))
        processing_list.append((data_item_real, self.document_model.get_pick_new, {}))
        processing_list.append((data_item_real, self.document_model.get_pick_region_new, {}))
        processing_list.append((data_item_real, self.document_model.get_pick_region_average_new, {}))
        processing_list.append((data_item_real, self.document_model.get_subtract_region_average_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(self.document_model.get_display_item_for_data_item(source_data_item), source_data_item)
            for name, value in params.items():
                self.document_model.get_data_item_computation(data_item)._set_variable_value(name, value)
            display_item = self.document_model.get_display_item_for_data_item(data_item)
            self.document_model.recompute_all()
            with display_item.data_item.data_ref() as data_ref:
                src_data_item = self.document_model.get_data_item_computation(data_item).get_input("src").data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_item.data_item.dimensional_calibrations)
                self.assertEqual(display_item.data_item.data_shape, data_ref.data.shape)
                self.assertEqual(display_item.data_item.data_dtype, data_ref.data.dtype)
                self.assertIsNotNone(display_item.data_item.data_dtype.type)  # make sure we're returning a dtype
                self.assertEqual(len(display_item.data_item.dimensional_shape), len(display_item.data_item.dimensional_calibrations))

    # test processing against 2d data. doesn't test for correctness of the processing.
    def test_processing_2d_rgb(self):
        data_item_rgb = DataItem.DataItem(numpy.zeros((8, 8, 3), numpy.uint8))
        self.document_model.append_data_item(data_item_rgb)

        processing_list = []
        processing_list.append((data_item_rgb, self.document_model.get_invert_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_sobel_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_laplace_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_gaussian_blur_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_median_filter_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_uniform_filter_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_crop_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_transpose_flip_new, {"do_transpose": True, "do_flip_v": True, "do_flip_h": True}))
        # processing_list.append((data_item_rgb, self.document_model.get_rebin_new, {"width": 128, "height": 128}))
        processing_list.append((data_item_rgb, self.document_model.get_resample_new, {"width": 128, "height": 128}))
        # processing_list.append((data_item_rgb, self.document_model.get_resize_new, {"width": 128, "height": 128}))
        processing_list.append((data_item_rgb, self.document_model.get_histogram_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_line_profile_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_projection_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(self.document_model.get_display_item_for_data_item(source_data_item), source_data_item)
            for name, value in params.items():
                self.document_model.get_data_item_computation(data_item)._set_variable_value(name, value)
            display_item = self.document_model.get_display_item_for_data_item(data_item)
            self.document_model.recompute_all()
            with display_item.data_item.data_ref() as data_ref:
                src_data_item = self.document_model.get_data_item_computation(data_item).get_input("src").data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_item.data_item.dimensional_calibrations)
                self.assertEqual(display_item.data_item.data_shape, data_ref.data.shape)
                self.assertEqual(display_item.data_item.data_dtype, data_ref.data.dtype)
                self.assertIsNotNone(display_item.data_item.data_dtype.type)  # make sure we're returning a dtype
                self.assertEqual(len(display_item.data_item.dimensional_shape), len(display_item.data_item.dimensional_calibrations))

    # test processing against 2d data. doesn't test for correctness of the processing.
    def test_processing_2d_rgba(self):
        data_item_rgb = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
        self.document_model.append_data_item(data_item_rgb)

        processing_list = []
        processing_list.append((data_item_rgb, self.document_model.get_invert_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_sobel_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_laplace_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_gaussian_blur_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_median_filter_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_uniform_filter_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_crop_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_transpose_flip_new, {"do_transpose": True, "do_flip_v": True, "do_flip_h": True}))
        # processing_list.append((data_item_rgb, self.document_model.get_rebin_new, {"width": 128, "height": 128}))
        processing_list.append((data_item_rgb, self.document_model.get_resample_new, {"width": 128, "height": 128}))
        # processing_list.append((data_item_rgb, self.document_model.get_resize_new, {"width": 128, "height": 128}))
        processing_list.append((data_item_rgb, self.document_model.get_histogram_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_line_profile_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_projection_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(self.document_model.get_display_item_for_data_item(source_data_item), source_data_item)
            for name, value in params.items():
                self.document_model.get_data_item_computation(data_item)._set_variable_value(name, value)
            display_item = self.document_model.get_display_item_for_data_item(data_item)
            self.document_model.recompute_all()
            with display_item.data_item.data_ref() as data_ref:
                src_data_item = self.document_model.get_data_item_computation(data_item).get_input("src").data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_item.data_item.dimensional_calibrations)
                self.assertEqual(display_item.data_item.data_shape, data_ref.data.shape)
                self.assertEqual(display_item.data_item.data_dtype, data_ref.data.dtype)
                self.assertIsNotNone(display_item.data_item.data_dtype.type)  # make sure we're returning a dtype
                self.assertEqual(len(display_item.data_item.dimensional_shape), len(display_item.data_item.dimensional_calibrations))

    def test_processing_2d_complex128(self):
        data_item_complex = DataItem.DataItem(numpy.zeros((8, 8), numpy.complex128))
        self.document_model.append_data_item(data_item_complex)

        processing_list = []
        processing_list.append((data_item_complex, self.document_model.get_ifft_new, {}))
        processing_list.append((data_item_complex, self.document_model.get_projection_new, {}))
        processing_list.append((data_item_complex, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(self.document_model.get_display_item_for_data_item(source_data_item), source_data_item)
            for name, value in params.items():
                self.document_model.get_data_item_computation(data_item)._set_variable_value(name, value)
            display_item = self.document_model.get_display_item_for_data_item(data_item)
            self.document_model.recompute_all()
            with display_item.data_item.data_ref() as data_ref:
                src_data_item = self.document_model.get_data_item_computation(data_item).get_input("src").data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_item.data_item.dimensional_calibrations)
                self.assertEqual(display_item.data_item.data_shape, data_ref.data.shape)
                self.assertEqual(display_item.data_item.data_dtype, data_ref.data.dtype)
                self.assertIsNotNone(display_item.data_item.data_dtype.type)  # make sure we're returning a dtype
                self.assertEqual(len(display_item.data_item.dimensional_shape), len(display_item.data_item.dimensional_calibrations))

    def test_processing_2d_complex64(self):
        data_item_complex = DataItem.DataItem(numpy.zeros((8, 8), numpy.complex64))
        self.document_model.append_data_item(data_item_complex)

        processing_list = []
        processing_list.append((data_item_complex, self.document_model.get_ifft_new, {}))
        processing_list.append((data_item_complex, self.document_model.get_projection_new, {}))
        processing_list.append((data_item_complex, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(self.document_model.get_display_item_for_data_item(source_data_item), source_data_item)
            for name, value in params.items():
                self.document_model.get_data_item_computation(data_item)._set_variable_value(name, value)
            display_item = self.document_model.get_display_item_for_data_item(data_item)
            self.document_model.recompute_all()
            with display_item.data_item.data_ref() as data_ref:
                src_data_item = self.document_model.get_data_item_computation(data_item).get_input("src").data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_item.data_item.dimensional_calibrations)
                self.assertEqual(display_item.data_item.data_shape, data_ref.data.shape)
                self.assertEqual(display_item.data_item.data_dtype, data_ref.data.dtype)
                self.assertIsNotNone(display_item.data_item.data_dtype.type)  # make sure we're returning a dtype
                self.assertEqual(len(display_item.data_item.dimensional_shape), len(display_item.data_item.dimensional_calibrations))

    def test_processing_2d_2d_float(self):
        d = numpy.random.randn(4, 4, 3, 3)
        data_and_metadata = DataAndMetadata.new_data_and_metadata(d, data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2))
        data_item = DataItem.new_data_item(data_and_metadata)
        self.document_model.append_data_item(data_item)

        processing_list = []
        processing_list.append((data_item, self.document_model.get_projection_new, {}))
        processing_list.append((data_item, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(self.document_model.get_display_item_for_data_item(source_data_item), source_data_item)
            for name, value in params.items():
                self.document_model.get_data_item_computation(data_item)._set_variable_value(name, value)
            display_item = self.document_model.get_display_item_for_data_item(data_item)
            self.document_model.recompute_all()
            with display_item.data_item.data_ref() as data_ref:
                src_data_item = self.document_model.get_data_item_computation(data_item).get_input("src").data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_item.data_item.dimensional_calibrations)
                self.assertEqual(display_item.data_item.data_shape, data_ref.data.shape)
                self.assertEqual(display_item.data_item.data_dtype, data_ref.data.dtype)
                self.assertIsNotNone(display_item.data_item.data_dtype.type)  # make sure we're returning a dtype
                self.assertEqual(len(display_item.data_item.dimensional_shape), len(display_item.data_item.dimensional_calibrations))

    # test processing against 2d data. doesn't test for correctness of the processing.
    def test_invalid_processings(self):

        data_item_none = DataItem.DataItem()
        self.document_model.append_data_item(data_item_none)

        data_item_real_0l = DataItem.DataItem(numpy.zeros((0), numpy.double))
        self.document_model.append_data_item(data_item_real_0l)
        data_item_real_0w = DataItem.DataItem(numpy.zeros((256,0), numpy.double))
        self.document_model.append_data_item(data_item_real_0w)
        data_item_real_0h = DataItem.DataItem(numpy.zeros((0,256), numpy.double))
        self.document_model.append_data_item(data_item_real_0h)
        data_item_real_0z = DataItem.DataItem(numpy.zeros((8, 8, 0), numpy.double))
        self.document_model.append_data_item(data_item_real_0z)
        data_item_real_0z0w = DataItem.DataItem(numpy.zeros((0,256,16), numpy.double))
        self.document_model.append_data_item(data_item_real_0z0w)
        data_item_real_0z0h = DataItem.DataItem(numpy.zeros((256,0,16), numpy.double))
        self.document_model.append_data_item(data_item_real_0z0h)

        data_item_complex_0l = DataItem.DataItem(numpy.zeros((0), numpy.double))
        self.document_model.append_data_item(data_item_complex_0l)
        data_item_complex_0w = DataItem.DataItem(numpy.zeros((256,0), numpy.double))
        self.document_model.append_data_item(data_item_complex_0w)
        data_item_complex_0h = DataItem.DataItem(numpy.zeros((0,256), numpy.double))
        self.document_model.append_data_item(data_item_complex_0h)
        data_item_complex_0z = DataItem.DataItem(numpy.zeros((8, 8, 0), numpy.double))
        self.document_model.append_data_item(data_item_complex_0z)
        data_item_complex_0z0w = DataItem.DataItem(numpy.zeros((0,256,16), numpy.double))
        self.document_model.append_data_item(data_item_complex_0z0w)
        data_item_complex_0z0h = DataItem.DataItem(numpy.zeros((256,0,16), numpy.double))
        self.document_model.append_data_item(data_item_complex_0z0h)

        data_item_rgb_0w = DataItem.DataItem(numpy.zeros((256,0, 3), numpy.uint8))
        self.document_model.append_data_item(data_item_rgb_0w)
        data_item_rgb_0h = DataItem.DataItem(numpy.zeros((0,256, 3), numpy.uint8))
        self.document_model.append_data_item(data_item_rgb_0h)

        data_item_rgba_0w = DataItem.DataItem(numpy.zeros((256,0, 4), numpy.uint8))
        self.document_model.append_data_item(data_item_rgba_0w)
        data_item_rgba_0h = DataItem.DataItem(numpy.zeros((0,256, 4), numpy.uint8))
        self.document_model.append_data_item(data_item_rgba_0h)

        data_list = (
            # data_item_none,
            data_item_real_0l, data_item_real_0w, data_item_real_0h, data_item_real_0z,
            data_item_real_0z0w, data_item_real_0z0h, data_item_complex_0l, data_item_complex_0w, data_item_complex_0h,
            data_item_complex_0z, data_item_complex_0z0w, data_item_complex_0z0h, data_item_rgb_0w, data_item_rgb_0h,
            data_item_rgba_0w, data_item_rgba_0h)

        processing_list = []
        for data_item in data_list:
            processing_list.append((data_item, self.document_model.get_fft_new, {}))
            processing_list.append((data_item, self.document_model.get_ifft_new, {}))
            processing_list.append((data_item, self.document_model.get_auto_correlate_new, {}))
            processing_list.append((data_item, functools.partial(self.document_model.get_cross_correlate_new, self.document_model.get_display_item_for_data_item(data_item), data_item), {}))
            processing_list.append((data_item, self.document_model.get_invert_new, {}))
            processing_list.append((data_item, self.document_model.get_sobel_new, {}))
            processing_list.append((data_item, self.document_model.get_laplace_new, {}))
            processing_list.append((data_item, self.document_model.get_gaussian_blur_new, {}))
            processing_list.append((data_item, self.document_model.get_median_filter_new, {}))
            processing_list.append((data_item, self.document_model.get_uniform_filter_new, {}))
            processing_list.append((data_item, self.document_model.get_crop_new, {}))
            processing_list.append((data_item, self.document_model.get_transpose_flip_new, {"do_transpose": True, "do_flip_v": True, "do_flip_h": True}))
            processing_list.append((data_item, self.document_model.get_slice_sum_new, {}))
            processing_list.append((data_item, self.document_model.get_pick_new, {}))
            processing_list.append((data_item, self.document_model.get_pick_region_new, {}))
            processing_list.append((data_item, self.document_model.get_pick_region_average_new, {}))
            processing_list.append((data_item, self.document_model.get_rebin_new, {"width": 128, "height": 128}))
            processing_list.append((data_item, self.document_model.get_resample_new, {"width": 128, "height": 128}))
            processing_list.append((data_item, self.document_model.get_resize_new, {"width": 128, "height": 128}))
            processing_list.append((data_item, self.document_model.get_histogram_new, {}))
            processing_list.append((data_item, self.document_model.get_line_profile_new, {}))
            processing_list.append((data_item, self.document_model.get_projection_new, {}))
            processing_list.append((data_item, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(self.document_model.get_display_item_for_data_item(source_data_item), source_data_item)
            if data_item:
                computation = self.document_model.get_data_item_computation(data_item)
                for name, value in params.items():
                    computation._set_variable_value(name, value)
                display_item = self.document_model.get_display_item_for_data_item(data_item)
                self.document_model.recompute_all()
                with display_item.data_item.data_ref() as data_ref:
                    src_data_item = computation.get_input(computation.variables[0].name).data_item
                    self.assertEqual(src_data_item, source_data_item)
                    self.assertIsNone(data_ref.data)
                    self.assertFalse(display_item.data_item.dimensional_calibrations)

    def test_processing_on_none(self):
        # TODO: this test makes less sense with computations; but leave it here until data_item and data_item merge.
        data_item = DataItem.DataItem()
        self.document_model.append_data_item(data_item)

        processing_list = []
        processing_list.append((data_item, self.document_model.get_fft_new, {}))
        processing_list.append((data_item, self.document_model.get_ifft_new, {}))
        processing_list.append((data_item, self.document_model.get_auto_correlate_new, {}))
        processing_list.append((data_item, functools.partial(self.document_model.get_cross_correlate_new, self.document_model.get_display_item_for_data_item(data_item), data_item), {}))
        processing_list.append((data_item, self.document_model.get_invert_new, {}))
        processing_list.append((data_item, self.document_model.get_sobel_new, {}))
        processing_list.append((data_item, self.document_model.get_laplace_new, {}))
        processing_list.append((data_item, self.document_model.get_gaussian_blur_new, {}))
        processing_list.append((data_item, self.document_model.get_median_filter_new, {}))
        processing_list.append((data_item, self.document_model.get_uniform_filter_new, {}))
        processing_list.append((data_item, self.document_model.get_crop_new, {}))
        processing_list.append((data_item, self.document_model.get_transpose_flip_new, {"do_transpose": True, "do_flip_v": True, "do_flip_h": True}))
        processing_list.append((data_item, self.document_model.get_slice_sum_new, {}))
        processing_list.append((data_item, self.document_model.get_pick_new, {}))
        processing_list.append((data_item, self.document_model.get_pick_region_new, {}))
        processing_list.append((data_item, self.document_model.get_pick_region_average_new, {}))
        processing_list.append((data_item, self.document_model.get_subtract_region_average_new, {}))
        processing_list.append((data_item, self.document_model.get_rebin_new, {"width": 128, "height": 128}))
        processing_list.append((data_item, self.document_model.get_resample_new, {"width": 128, "height": 128}))
        processing_list.append((data_item, self.document_model.get_resize_new, {"width": 128, "height": 128}))
        processing_list.append((data_item, self.document_model.get_histogram_new, {}))
        processing_list.append((data_item, self.document_model.get_line_profile_new, {}))
        processing_list.append((data_item, self.document_model.get_projection_new, {}))
        processing_list.append((data_item, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(self.document_model.get_display_item_for_data_item(source_data_item), source_data_item)
            if data_item:
                computation = self.document_model.get_data_item_computation(data_item)
                for name, value in params.items():
                    computation._set_variable_value(name, value)
                display_item = self.document_model.get_display_item_for_data_item(data_item)
                self.document_model.recompute_all()
                with display_item.data_item.data_ref() as data_ref:
                    src_data_item = computation.get_input(computation.variables[0].name).data_item
                    self.assertEqual(src_data_item, source_data_item)
                    self.assertIsNone(data_ref.data)
                    self.assertEqual(display_item.data_item.dimensional_calibrations, [])

    def test_crop_2d_processing_returns_correct_dimensional_shape_and_data_shape(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((20,10), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.2, 0.3), (0.5, 0.5)
            display_item.add_graphic(crop_region)
            real_data_item = document_model.get_crop_new(display_item, display_item.data_item, crop_region)
            real_display_item = document_model.get_display_item_for_data_item(real_data_item)
            document_model.recompute_all()
            # make sure we get the right shape
            self.assertEqual(real_display_item.data_item.dimensional_shape, (10, 5))
            with real_display_item.data_item.data_ref() as data_real_accessor:
                self.assertEqual(data_real_accessor.data.shape, (10, 5))

    def test_fft_2d_dtype(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.float64))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            fft_data_item = document_model.get_fft_new(display_item, display_item.data_item)
            fft_display_item = document_model.get_display_item_for_data_item(fft_data_item)
            document_model.recompute_all()
            with fft_display_item.data_item.data_ref() as fft_data_ref:
                self.assertEqual(fft_data_ref.data.shape, (16, 16))
                self.assertEqual(fft_data_ref.data.dtype, numpy.dtype(numpy.complex128))

    def test_convert_complex128_to_scalar_results_in_float64(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.complex128))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            scalar_data_item = document_model.get_convert_to_scalar_new(display_item, display_item.data_item)
            scalar_display_item = document_model.get_display_item_for_data_item(scalar_data_item)
            document_model.recompute_all()
            with scalar_display_item.data_item.data_ref() as scalar_data_ref:
                self.assertEqual(scalar_data_ref.data.dtype, numpy.dtype(numpy.float64))

    def test_rgba_invert_processing_should_retain_alpha(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            rgba_data_item = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
            document_model.append_data_item(rgba_data_item)
            rgba_display_item = document_model.get_display_item_for_data_item(rgba_data_item)
            with rgba_display_item.data_item.data_ref() as data_ref:
                data_ref.master_data[:] = (20,40,60,100)
                data_ref.master_data_updated()
            rgba2_data_item = document_model.get_invert_new(rgba_display_item, rgba_display_item.data_item)
            rgba2_display_item = document_model.get_display_item_for_data_item(rgba2_data_item)
            document_model.recompute_all()
            with rgba2_display_item.data_item.data_ref() as data_ref:
                pixel = data_ref.data[0,0,...]
                self.assertEqual(pixel[0], 255 - 20)
                self.assertEqual(pixel[1], 255 - 40)
                self.assertEqual(pixel[2], 255 - 60)
                self.assertEqual(pixel[3], 100)

    def test_deepcopy_of_crop_processing_should_copy_roi(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item_rgba = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
            document_model.append_data_item(data_item_rgba)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            display_item_rgba = document_model.get_display_item_for_data_item(data_item_rgba)
            display_item_rgba.add_graphic(crop_region)
            data_item_rgba2 = document_model.get_crop_new(display_item_rgba, display_item_rgba.data_item, crop_region)
            data_item_rgba2_copy = copy.deepcopy(data_item_rgba2)
            # make sure the computation was not copied
            self.assertNotEqual(document_model.get_data_item_computation(data_item_rgba2), document_model.get_data_item_computation(data_item_rgba2_copy))

    def test_snapshot_of_processing_should_copy_data(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item_rgba = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
            document_model.append_data_item(data_item_rgba)
            display_item_rgba = document_model.get_display_item_for_data_item(data_item_rgba)
            data_item_rgba2 = document_model.get_invert_new(display_item_rgba, display_item_rgba.data_item)
            document_model.recompute_all()
            data_item_rgba2_ss = document_model.get_display_item_snapshot_new(document_model.get_display_item_for_data_item(data_item_rgba2)).data_item
            self.assertTrue(data_item_rgba2_ss.has_data)

    def test_snapshot_empty_data_item_should_produce_empty_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem()
            data_item.ensure_data_source()
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            self.assertIsNone(display_item.data_item.data)
            self.assertIsNone(display_item.data_item.data_dtype)
            self.assertIsNone(display_item.data_item.data_shape)
            snapshot_data_item = data_item.snapshot()
            document_model.append_data_item(snapshot_data_item)
            snapshot_display_item = document_model.get_display_item_for_data_item(snapshot_data_item)
            self.assertIsNone(snapshot_display_item.data_item.data)
            self.assertIsNone(snapshot_display_item.data_item.data_dtype)
            self.assertIsNone(snapshot_display_item.data_item.data_shape)

    def test_snapshot_of_processing_should_copy_calibrations_not_dimensional_calibrations(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            # setup
            data_item.set_dimensional_calibration(0, Calibration.Calibration(5.0, 2.0, u"nm"))
            data_item.set_dimensional_calibration(1, Calibration.Calibration(5.0, 2.0, u"nm"))
            data_item.set_intensity_calibration(Calibration.Calibration(7.5, 2.5, u"ll"))
            data_item2 = document_model.get_invert_new(display_item, display_item.data_item)
            document_model.recompute_all()
            # make sure our assumptions are correct
            self.assertEqual(len(data_item.dimensional_calibrations), 2)
            self.assertEqual(len(data_item2.dimensional_calibrations), 2)
            # take snapshot
            snapshot_data_item = document_model.get_display_item_snapshot_new(document_model.get_display_item_for_data_item(data_item2)).data_item
            # check calibrations
            self.assertEqual(len(snapshot_data_item.dimensional_calibrations), 2)
            self.assertEqual(snapshot_data_item.dimensional_calibrations[0].scale, 2.0)
            self.assertEqual(snapshot_data_item.dimensional_calibrations[0].offset, 5.0)
            self.assertEqual(snapshot_data_item.dimensional_calibrations[0].units, u"nm")
            self.assertEqual(snapshot_data_item.dimensional_calibrations[1].scale, 2.0)
            self.assertEqual(snapshot_data_item.dimensional_calibrations[1].offset, 5.0)
            self.assertEqual(snapshot_data_item.dimensional_calibrations[1].units, u"nm")
            self.assertEqual(snapshot_data_item.intensity_calibration.scale, 2.5)
            self.assertEqual(snapshot_data_item.intensity_calibration.offset, 7.5)
            self.assertEqual(snapshot_data_item.intensity_calibration.units, u"ll")

    def test_crop_2d_processing_on_calibrated_data_results_in_calibration_with_correct_offset(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((20, 10), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.2, 0.3), (0.5, 0.5)
            display_item.add_graphic(crop_region)
            spatial_calibration_0 = data_item.dimensional_calibrations[0]
            spatial_calibration_0.offset = 20.0
            spatial_calibration_0.scale = 5.0
            spatial_calibration_0.units = "dogs"
            spatial_calibration_1 = data_item.dimensional_calibrations[1]
            spatial_calibration_1.offset = 55.0
            spatial_calibration_1.scale = 5.5
            spatial_calibration_1.units = "cats"
            data_item.set_dimensional_calibration(0, spatial_calibration_0)
            data_item.set_dimensional_calibration(1, spatial_calibration_1)
            data_item2 = document_model.get_crop_new(display_item, display_item.data_item, crop_region)
            document_model.recompute_all()
            # make sure the calibrations are correct
            self.assertAlmostEqual(data_item2.dimensional_calibrations[0].offset, 20.0 + 20 * 0.2 * 5.0)
            self.assertAlmostEqual(data_item2.dimensional_calibrations[1].offset, 55.0 + 10 * 0.3 * 5.5)
            self.assertAlmostEqual(data_item2.dimensional_calibrations[0].scale, 5.0)
            self.assertAlmostEqual(data_item2.dimensional_calibrations[1].scale, 5.5)
            self.assertEqual(data_item2.dimensional_calibrations[0].units, "dogs")
            self.assertEqual(data_item2.dimensional_calibrations[1].units, "cats")

    def test_projection_2d_processing_on_calibrated_data_results_in_calibration_with_correct_offset(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((20, 10), numpy.double))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            spatial_calibration_0 = data_item.dimensional_calibrations[0]
            spatial_calibration_0.offset = 20.0
            spatial_calibration_0.scale = 5.0
            spatial_calibration_0.units = "dogs"
            spatial_calibration_1 = data_item.dimensional_calibrations[1]
            spatial_calibration_1.offset = 55.0
            spatial_calibration_1.scale = 5.5
            spatial_calibration_1.units = "cats"
            data_item.set_dimensional_calibration(0, spatial_calibration_0)
            data_item.set_dimensional_calibration(1, spatial_calibration_1)
            data_item2 = document_model.get_projection_new(display_item, display_item.data_item)
            document_model.recompute_all()
            # make sure the calibrations are correct
            self.assertAlmostEqual(data_item2.dimensional_calibrations[0].offset, 55.0)
            self.assertAlmostEqual(data_item2.dimensional_calibrations[0].scale, 5.5)
            self.assertEqual(data_item2.dimensional_calibrations[0].units, "cats")

    def disabled_test_removing_computation_with_multiple_associated_regions_removes_all_regions(self):
        self.assertFalse(True)

    def test_crop_works_on_selected_region_without_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            self.assertEqual(len(display_item.graphics), 0)
            crop_region = Graphics.RectangleGraphic()
            crop_region.center = (0.5, 0.5)
            crop_region.size = (0.5, 1.0)
            display_item.add_graphic(crop_region)
            display_item.graphic_selection.set(0)
            document_controller.processing_crop().data_item

    def test_remove_graphic_for_crop_removes_processed_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            self.assertEqual(len(display_item.graphics), 0)
            crop_region = Graphics.RectangleGraphic()
            crop_region.center = (0.5, 0.5)
            crop_region.size = (0.5, 1.0)
            display_item.add_graphic(crop_region)
            display_item.graphic_selection.set(0)
            cropped_data_item = document_controller.processing_crop().data_item
            document_controller.periodic()  # TODO: remove need to let the inspector catch up
            self.assertEqual(len(display_item.graphics), 1)
            self.assertTrue(cropped_data_item in document_model.data_items)
            display_item.graphic_selection.clear()
            display_item.graphic_selection.add(0)
            # make sure assumptions are correct
            self.assertEqual(document_model.get_source_data_items(cropped_data_item)[0], data_item)
            self.assertTrue(cropped_data_item in document_model.data_items)
            # remove the graphic and make sure things are as expected
            display_panel.set_display_panel_display_item(display_item)
            document_controller.remove_selected_graphics()
            self.assertEqual(len(display_item.graphics), 0)
            self.assertEqual(len(display_item.graphic_selection.indexes), 0)  # disabled until test_remove_line_profile_updates_graphic_selection
            self.assertFalse(cropped_data_item in document_model.data_items)

    def test_remove_graphic_for_crop_combined_with_another_processing_removes_processed_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            self.assertEqual(len(display_item.graphics), 0)
            crop_region = Graphics.RectangleGraphic()
            crop_region.center = (0.5, 0.5)
            crop_region.size = (0.5, 1.0)
            display_item.add_graphic(crop_region)
            display_item.graphic_selection.set(0)
            projection_data_item = document_controller.processing_projection().data_item
            document_controller.periodic()
            self.assertTrue(projection_data_item in document_model.data_items)
            display_item.graphic_selection.clear()
            display_item.graphic_selection.add(0)
            # make sure assumptions are correct
            self.assertEqual(document_model.get_source_data_items(projection_data_item)[0], data_item)
            self.assertTrue(projection_data_item in document_model.data_items)
            # remove the graphic and make sure things are as expected
            display_panel.set_display_panel_display_item(display_item)
            document_controller.remove_selected_graphics()
            self.assertEqual(len(display_item.graphics), 0)
            self.assertEqual(len(display_item.graphic_selection.indexes), 0)  # disabled until test_remove_line_profile_updates_graphic_selection
            self.assertFalse(projection_data_item in document_model.data_items)

    def test_modifying_processing_results_in_data_computation(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # set up the data items
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            blurred_data_item = document_model.get_gaussian_blur_new(display_item, display_item.data_item)
            blurred_display_item = document_model.get_display_item_for_data_item(blurred_data_item)
            # establish listeners
            data_changed_ref = [False]
            display_changed_ref = [False]
            def data_item_content_changed():
                data_changed_ref[0] = True
            with contextlib.closing(blurred_data_item.data_item_changed_event.listen(data_item_content_changed)):
                def display_changed():
                    display_changed_ref[0] = True
                with contextlib.closing(blurred_display_item.display_changed_event.listen(display_changed)):
                    # modify processing. make sure data and dependent data gets updated.
                    data_changed_ref[0] = False
                    display_changed_ref[0] = False
                    document_model.get_data_item_computation(blurred_data_item)._set_variable_value("sigma", 0.1)
                    document_model.recompute_all()
                    self.assertTrue(data_changed_ref[0])
                    self.assertTrue(display_changed_ref[0])

    def test_modifying_processing_region_results_in_data_computation(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            # set up the data items
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            display_item.add_graphic(crop_region)
            cropped_data_item = document_model.get_crop_new(display_item, display_item.data_item, crop_region)
            cropped_display_item = document_model.get_display_item_for_data_item(cropped_data_item)
            # establish listeners
            data_changed_ref = [False]
            display_changed_ref = [False]
            def data_item_content_changed():
                data_changed_ref[0] = True
            with contextlib.closing(cropped_data_item.data_item_changed_event.listen(data_item_content_changed)):
                def display_changed():
                    display_changed_ref[0] = True
                with contextlib.closing(cropped_display_item.display_changed_event.listen(display_changed)):
                    # modify processing. make sure data and dependent data gets updated.
                    data_changed_ref[0] = False
                    display_changed_ref[0] = False
                    crop_region.center = (0.51, 0.51)
                    document_model.recompute_all()
                    self.assertTrue(data_changed_ref[0])
                    self.assertTrue(display_changed_ref[0])

    def test_changing_region_does_not_trigger_fft_recompute(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            display_item.add_graphic(crop_region)
            fft_data_item = document_model.get_fft_new(display_item, display_item.data_item)
            crop_data_item = document_model.get_crop_new(display_item, display_item.data_item, crop_region)
            document_model.recompute_all()
            self.assertFalse(document_model.get_data_item_computation(fft_data_item).needs_update)
            self.assertFalse(document_model.get_data_item_computation(crop_data_item).needs_update)
            crop_region.bounds = Geometry.FloatRect(crop_region.bounds[0], Geometry.FloatPoint(0.1, 0.1))
            self.assertTrue(document_model.get_data_item_computation(crop_data_item).needs_update)
            self.assertFalse(document_model.get_data_item_computation(fft_data_item).needs_update)

    def test_removing_source_of_cross_correlation_does_not_throw_exception(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item2 = document_model.get_display_item_for_data_item(data_item2)
            document_model.get_cross_correlate_new(display_item1, display_item1.data_item, display_item2, display_item2.data_item)
            document_model.recompute_all()
            document_model.remove_data_item(data_item1)
            document_model.recompute_all()

    def test_crop_of_slice_of_3d_handles_dimensions(self):
        # the bug was that slice processing returned the wrong number of dimensions
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((32, 32, 16), numpy.float))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            slice_data_item = document_model.get_slice_sum_new(display_item, display_item.data_item)
            slice_display_item = document_model.get_display_item_for_data_item(slice_data_item)
            document_model.recompute_all()
            crop_region = Graphics.RectangleGraphic()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            slice_display_item.add_graphic(crop_region)
            crop_data_item = document_model.get_crop_new(slice_display_item, slice_display_item.data_item, crop_region)
            document_model.recompute_all()

    def test_projection_of_2d_by_2d_sums_first_datum_dimension(self):
        # the bug was that slice processing returned the wrong number of dimensions
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            d = numpy.random.randn(4, 4, 3, 3)
            data_and_metadata = DataAndMetadata.new_data_and_metadata(d, data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            slice_data_item = document_model.get_projection_new(display_item, display_item.data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(numpy.sum(d, 2), slice_data_item.xdata.data))

    def test_cross_correlate_works_in_1d(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = ((numpy.abs(numpy.random.randn(8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.perform_action("processing.cross_correlate")

    def test_cross_correlate_works_in_2d(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = ((numpy.abs(numpy.random.randn(8, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            document_controller.perform_action("processing.cross_correlate")

    def test_get_two_data_sources_handles_no_selection(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            self.assertIsNone(document_controller._get_two_data_sources())
            data = ((numpy.abs(numpy.random.randn(8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            self.assertIsNone(document_controller._get_two_data_sources())

    def test_get_two_data_sources_handles_one_selected_data_item(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            self.assertIsNone(document_controller._get_two_data_sources())
            data = ((numpy.abs(numpy.random.randn(8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            self.assertIsNone(document_controller._get_two_data_sources())
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            data_sources = document_controller._get_two_data_sources()
            self.assertEqual(data_sources[0][0], display_item)
            self.assertEqual(data_sources[0][1], None)
            self.assertEqual(data_sources[1][0], display_item)
            self.assertEqual(data_sources[1][1], None)

    def test_get_two_data_sources_handles_two_selected_data_items(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            self.assertIsNone(document_controller._get_two_data_sources())
            data = ((numpy.abs(numpy.random.randn(8)) + 1) * 10).astype(numpy.uint32)
            data_item1 = DataItem.DataItem(data)
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.random.randn(8))
            document_model.append_data_item(data_item2)
            self.assertIsNone(document_controller._get_two_data_sources())
            document_controller.selected_display_panel = None  # use data panel selection
            document_controller.select_data_items_in_data_panel([data_item1, data_item2])
            data_sources = document_controller._get_two_data_sources()
            self.assertIn(document_model.get_display_item_for_data_item(data_item1), (data_sources[0][0], data_sources[1][0]))
            self.assertIn(document_model.get_display_item_for_data_item(data_item2), (data_sources[0][0], data_sources[1][0]))
            self.assertEqual(data_sources[0][1], None)
            self.assertEqual(data_sources[1][1], None)

    def test_get_two_data_sources_handles_three_selected_data_items(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_items = list()
            for i in range(3):
                data_item = DataItem.DataItem(numpy.random.randn(8))
                document_model.append_data_item(data_item)
            document_controller.select_data_items_in_data_panel(document_model.data_items)
            self.assertIsNone(document_controller._get_two_data_sources())

    def test_get_two_data_sources_handles_one_selected_data_item_and_one_crop_graphic(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            self.assertIsNone(document_controller._get_two_data_sources())
            data = ((numpy.abs(numpy.random.randn(8, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.center = (0.5, 0.5)
            crop_region.size = (0.5, 1.0)
            display_item.add_graphic(crop_region)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_item.graphic_selection.set(0)
            data_sources = document_controller._get_two_data_sources()
            self.assertEqual(data_sources[0][0], display_item)
            self.assertEqual(data_sources[0][1], crop_region)
            self.assertEqual(data_sources[1][0], display_item)
            self.assertEqual(data_sources[1][1], crop_region)

    def test_get_two_data_sources_handles_one_selected_data_item_and_two_crop_graphics(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            self.assertIsNone(document_controller._get_two_data_sources())
            data = ((numpy.abs(numpy.random.randn(8, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region1 = Graphics.RectangleGraphic()
            crop_region1.center = (0.5, 0.5)
            crop_region1.size = (0.5, 1.0)
            display_item.add_graphic(crop_region1)
            crop_region2 = Graphics.RectangleGraphic()
            crop_region2.center = (0.6, 0.5)
            crop_region2.size = (0.5, 1.0)
            display_item.add_graphic(crop_region2)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_item.graphic_selection.set(0)
            display_item.graphic_selection.add(1)
            data_sources = document_controller._get_two_data_sources()
            self.assertEqual(data_sources[0][0], display_item)
            self.assertEqual(data_sources[0][1], crop_region1)
            self.assertEqual(data_sources[1][0], display_item)
            self.assertEqual(data_sources[1][1], crop_region2)

    def test_get_two_data_sources_handles_one_selected_data_item_and_three_crop_graphics(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            self.assertIsNone(document_controller._get_two_data_sources())
            data = ((numpy.abs(numpy.random.randn(8, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            for i in range(3):
                display_item.add_graphic(Graphics.RectangleGraphic())
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_item.graphic_selection.add_range(range(3))
            data_sources = document_controller._get_two_data_sources()
            self.assertEqual(data_sources[0][0], display_item)
            self.assertEqual(data_sources[0][1], None)
            self.assertEqual(data_sources[1][0], display_item)
            self.assertEqual(data_sources[1][1], None)

    def test_crop_handles_1d_case_with_existing_interval(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = ((numpy.abs(numpy.random.randn(8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.IntervalGraphic()
            crop_region.interval = (0.5, 1.0)
            display_item.add_graphic(crop_region)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_item.graphic_selection.set(0)
            cropped_data_item = document_controller.processing_crop().data_item
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(cropped_data_item.data, data_item.data[4:8]))

    def test_crop_handles_2d_case_with_existing_rectangle(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = ((numpy.abs(numpy.random.randn(8, 8)) + 1) * 10).astype(numpy.uint32)
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.center = (0.5, 0.5)
            crop_region.size = (0.5, 1.0)
            display_item.add_graphic(crop_region)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_item.graphic_selection.set(0)
            cropped_data_item = document_controller.processing_crop().data_item
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(cropped_data_item.data, data_item.data[2:6, 0:8]))

    def test_basic_redimension_command_works(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = numpy.zeros((2, 2, 2))
            data_descriptor = DataAndMetadata.DataDescriptor(False, 2, 1)
            dimensional_calibrations = [
                Calibration.Calibration(1),
                Calibration.Calibration(2),
                Calibration.Calibration(3),
            ]
            xdata = DataAndMetadata.new_data_and_metadata(data, data_descriptor=data_descriptor, dimensional_calibrations=dimensional_calibrations)
            data_item = DataItem.new_data_item(xdata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            document_controller._perform_redimension(display_item, DataAndMetadata.DataDescriptor(False, 1, 2))
            document_model.recompute_all()
            redim_data_item = document_model.data_items[1]
            self.assertEqual(redim_data_item.xdata.data_descriptor, DataAndMetadata.DataDescriptor(False, 1, 2))
            self.assertEqual(redim_data_item.xdata.dimensional_calibrations, [Calibration.Calibration(1), Calibration.Calibration(2), Calibration.Calibration(3)])

    def test_squeeze_removes_proper_dimensions(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = numpy.zeros((1, 2, 1, 1))
            data_descriptor = DataAndMetadata.DataDescriptor(True, 2, 1)
            dimensional_calibrations = [
                Calibration.Calibration(1),
                Calibration.Calibration(2),
                Calibration.Calibration(3),
                Calibration.Calibration(4),
            ]
            xdata = DataAndMetadata.new_data_and_metadata(data, data_descriptor=data_descriptor, dimensional_calibrations=dimensional_calibrations)
            data_item = DataItem.new_data_item(xdata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            document_controller._perform_squeeze(display_item)
            document_model.recompute_all()
            squeezed_data_item = document_model.data_items[1]
            self.assertEqual(squeezed_data_item.xdata.data_descriptor, DataAndMetadata.DataDescriptor(False, 1, 1))
            self.assertEqual(squeezed_data_item.xdata.dimensional_calibrations, [Calibration.Calibration(2), Calibration.Calibration(4)])

    def test_squeeze_removes_proper_dimensions_when_both_datum_is_1(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data = numpy.zeros((1, 2, 1, 1, 1))
            data_descriptor = DataAndMetadata.DataDescriptor(True, 2, 2)
            dimensional_calibrations = [
                Calibration.Calibration(1),
                Calibration.Calibration(2),
                Calibration.Calibration(3),
                Calibration.Calibration(4),
                Calibration.Calibration(5),
            ]
            xdata = DataAndMetadata.new_data_and_metadata(data, data_descriptor=data_descriptor, dimensional_calibrations=dimensional_calibrations)
            data_item = DataItem.new_data_item(xdata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            document_controller._perform_squeeze(display_item)
            document_model.recompute_all()
            squeezed_data_item = document_model.data_items[1]
            self.assertEqual(squeezed_data_item.xdata.data_descriptor, DataAndMetadata.DataDescriptor(False, 1, 1))
            self.assertEqual(squeezed_data_item.xdata.dimensional_calibrations, [Calibration.Calibration(2), Calibration.Calibration(5)])

    def test_invalid_processing_produces_no_output(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((3, 3)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            document_controller._perform_processing(display_item, data_item, None, document_model.get_pick_new)

    def test_mapped_sum_is_registered_and_functional(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data = numpy.zeros((8, 8, 4, 4))
            data[0:4, 0:4, ...] = 1
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            crop_region = Graphics.RectangleGraphic()
            crop_region.center = (0.25, 0.25)
            crop_region.size = (0.5, 0.5)
            display_item.add_graphic(crop_region)
            document_model.get_processing_new("mapped_sum", display_item, display_item.data_item, crop_region)
            document_model.recompute_all()

    def test_line_profile_on_sequence_works(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_and_metadata = DataAndMetadata.new_data_and_metadata(numpy.zeros((20, 8, 6)), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
            data_item = DataItem.new_data_item(data_and_metadata)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            line_profile_data_item = document_model.get_line_profile_new(display_item, data_item)
            document_model.recompute_all()
            self.assertIsNotNone(line_profile_data_item.xdata)
            self.assertEqual((5, ), line_profile_data_item.xdata.data_shape)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
