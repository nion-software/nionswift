# futures
from __future__ import absolute_import

# standard libraries
import contextlib
import copy
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import Calibration
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Operation
from nion.swift.model import Region
from nion.swift.model import Storage
from nion.ui import Geometry
from nion.ui import Test


class TestOperationClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)
        cache_name = ":memory:"
        storage_cache = Storage.DbStorageCache(cache_name)
        self.document_model = DocumentModel.DocumentModel(storage_cache=storage_cache)
        self.document_controller = DocumentController.DocumentController(self.app.ui, self.document_model, workspace_id="library")
        self.display_panel = self.document_controller.selected_display_panel
        self.data_item = DataItem.DataItem(numpy.zeros((10, 10)))
        self.display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
        self.document_model.append_data_item(self.data_item)
        self.display_panel.set_displayed_data_item(self.data_item)

    def tearDown(self):
        self.document_controller.close()

    # make sure we can remove a single operation
    def test_remove_operation(self):
        operation = Operation.OperationItem("invert-operation")
        self.data_item.set_operation(operation)
        self.assertIsNotNone(self.data_item.operation)
        self.data_item.set_operation(None)
        self.assertIsNone(self.data_item.operation)

    # make sure defaults get propagated when adding data item to document
    def test_default_propagation(self):
        # first make sure data and calibrations come out OK
        source_data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        self.document_model.append_data_item(source_data_item)
        operation = Operation.OperationItem("resample-operation")
        operation.add_data_source(source_data_item._create_test_data_source())
        self.data_item.set_operation(operation)
        with self.display_specifier.buffered_data_source.data_ref() as data_ref:
            data_ref.data  # just calculate it
        self.display_specifier.buffered_data_source.dimensional_calibrations  # just calculate it
        # now create a new data item and add the operation before its added to document
        data_item = DataItem.DataItem()
        operation2 = Operation.OperationItem("resample-operation")
        operation2.add_data_source(self.data_item._create_test_data_source())
        data_item.set_operation(operation2)
        self.document_model.append_data_item(data_item)
        self.assertEqual(operation2.get_realized_values([self.display_specifier.buffered_data_source.data_and_calibration])["width"], self.display_specifier.buffered_data_source.data_shape[1])

    # test operations against 1d data. doesn't test for correctness of the operation.
    def test_operations_1d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((256), numpy.double))
        self.document_model.append_data_item(data_item_real)

        data_item_complex = DataItem.DataItem(numpy.zeros((256), numpy.complex128))
        self.document_model.append_data_item(data_item_complex)

        operation_list = []
        operation_list.append((data_item_real, Operation.OperationItem("fft-operation")))
        operation_list.append((data_item_complex, Operation.OperationItem("inverse-fft-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("invert-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("sobel-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("laplace-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("gaussian-blur-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("median-filter-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("uniform-filter-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("histogram-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("convert-to-scalar-operation")))
        transpose_operation = Operation.OperationItem("transpose-flip-operation")
        transpose_operation.transpose = True
        transpose_operation.flip_horizontal = True
        transpose_operation.flip_vertical = True
        operation_list.append((data_item_real, transpose_operation))

        for source_data_item, operation in operation_list:
            operation.add_data_source(source_data_item._create_test_data_source())
            data_item = DataItem.DataItem()
            data_item.set_operation(operation)
            self.document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item.recompute_data()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                self.assertEqual(data_item.operation.data_sources[0].source_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_operations_2d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((8, 8), numpy.double))
        self.document_model.append_data_item(data_item_real)

        operation_list = []
        operation_list.append((data_item_real, Operation.OperationItem("fft-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("invert-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("sobel-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("laplace-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("auto-correlate-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("gaussian-blur-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("median-filter-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("uniform-filter-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("crop-operation")))
        transpose_operation = Operation.OperationItem("transpose-flip-operation")
        transpose_operation.transpose = True
        transpose_operation.flip_horizontal = True
        transpose_operation.flip_vertical = True
        operation_list.append((data_item_real, transpose_operation))
        resample_2d_operation = Operation.OperationItem("resample-operation")
        resample_2d_operation.width = 128
        resample_2d_operation.height = 128
        operation_list.append((data_item_real, resample_2d_operation))
        operation_list.append((data_item_real, Operation.OperationItem("histogram-operation")))
        line_profile_operation = Operation.OperationItem("line-profile-operation")
        operation_list.append((data_item_real, line_profile_operation))
        operation_list.append((data_item_real, Operation.OperationItem("projection-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("convert-to-scalar-operation")))

        for source_data_item, operation in operation_list:
            operation.add_data_source(source_data_item._create_test_data_source())
            data_item = DataItem.DataItem()
            data_item.set_operation(operation)
            self.document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item.recompute_data()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                self.assertEqual(data_item.operation.data_sources[0].source_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_operations_3d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((256,16,16), numpy.double))
        self.document_model.append_data_item(data_item_real)

        operation_list = []
        operation_list.append((data_item_real, Operation.OperationItem("slice-operation")))
        operation_list.append((data_item_real, Operation.OperationItem("pick-operation")))

        for source_data_item, operation in operation_list:
            operation.add_data_source(source_data_item._create_test_data_source())
            data_item = DataItem.DataItem()
            data_item.set_operation(operation)
            self.document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item.recompute_data()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                self.assertEqual(data_item.operation.data_sources[0].source_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_operations_2d_rgb(self):
        data_item_rgb = DataItem.DataItem(numpy.zeros((8, 8, 3), numpy.uint8))
        self.document_model.append_data_item(data_item_rgb)

        operation_list = []
        operation_list.append((data_item_rgb, Operation.OperationItem("invert-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("sobel-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("laplace-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("gaussian-blur-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("median-filter-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("uniform-filter-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("crop-operation")))
        transpose_operation = Operation.OperationItem("transpose-flip-operation")
        transpose_operation.transpose = True
        transpose_operation.flip_horizontal = True
        transpose_operation.flip_vertical = True
        operation_list.append((data_item_rgb, transpose_operation))
        resample_2d_operation = Operation.OperationItem("resample-operation")
        resample_2d_operation.width = 128
        resample_2d_operation.height = 128
        operation_list.append((data_item_rgb, resample_2d_operation))
        operation_list.append((data_item_rgb, Operation.OperationItem("histogram-operation")))
        line_profile_operation = Operation.OperationItem("line-profile-operation")
        operation_list.append((data_item_rgb, line_profile_operation))
        operation_list.append((data_item_rgb, Operation.OperationItem("projection-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("convert-to-scalar-operation")))

        for source_data_item, operation in operation_list:
            operation.add_data_source(source_data_item._create_test_data_source())
            data_item = DataItem.DataItem()
            data_item.set_operation(operation)
            self.document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item.recompute_data()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                self.assertEqual(data_item.operation.data_sources[0].source_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_operations_2d_rgba(self):
        data_item_rgb = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
        self.document_model.append_data_item(data_item_rgb)

        operation_list = []
        operation_list.append((data_item_rgb, Operation.OperationItem("invert-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("sobel-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("laplace-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("gaussian-blur-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("median-filter-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("uniform-filter-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("crop-operation")))
        transpose_operation = Operation.OperationItem("transpose-flip-operation")
        transpose_operation.transpose = True
        transpose_operation.flip_horizontal = True
        transpose_operation.flip_vertical = True
        operation_list.append((data_item_rgb, transpose_operation))
        resample_2d_operation = Operation.OperationItem("resample-operation")
        resample_2d_operation.width = 128
        resample_2d_operation.height = 128
        operation_list.append((data_item_rgb, resample_2d_operation))
        operation_list.append((data_item_rgb, Operation.OperationItem("histogram-operation")))
        line_profile_operation = Operation.OperationItem("line-profile-operation")
        operation_list.append((data_item_rgb, line_profile_operation))
        operation_list.append((data_item_rgb, Operation.OperationItem("projection-operation")))
        operation_list.append((data_item_rgb, Operation.OperationItem("convert-to-scalar-operation")))

        for source_data_item, operation in operation_list:
            operation.add_data_source(source_data_item._create_test_data_source())
            data_item = DataItem.DataItem()
            data_item.set_operation(operation)
            self.document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item.recompute_data()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                self.assertEqual(data_item.operation.data_sources[0].source_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    def test_operations_2d_complex128(self):
        data_item_complex = DataItem.DataItem(numpy.zeros((8, 8), numpy.complex128))
        self.document_model.append_data_item(data_item_complex)

        operation_list = []
        operation_list.append((data_item_complex, Operation.OperationItem("inverse-fft-operation")))
        operation_list.append((data_item_complex, Operation.OperationItem("projection-operation")))
        operation_list.append((data_item_complex, Operation.OperationItem("convert-to-scalar-operation")))

        for source_data_item, operation in operation_list:
            operation.add_data_source(source_data_item._create_test_data_source())
            data_item = DataItem.DataItem()
            data_item.set_operation(operation)
            self.document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item.recompute_data()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                self.assertEqual(data_item.operation.data_sources[0].source_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    def test_operations_2d_complex64(self):
        data_item_complex = DataItem.DataItem(numpy.zeros((8, 8), numpy.complex64))
        self.document_model.append_data_item(data_item_complex)

        operation_list = []
        operation_list.append((data_item_complex, Operation.OperationItem("inverse-fft-operation")))
        operation_list.append((data_item_complex, Operation.OperationItem("projection-operation")))
        operation_list.append((data_item_complex, Operation.OperationItem("convert-to-scalar-operation")))

        for source_data_item, operation in operation_list:
            operation.add_data_source(source_data_item._create_test_data_source())
            data_item = DataItem.DataItem()
            data_item.set_operation(operation)
            self.document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item.recompute_data()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                self.assertEqual(data_item.operation.data_sources[0].source_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_invalid_operations(self):

        data_item_none = DataItem.DataItem()
        self.document_model.append_data_item(data_item_none)

        data_item_real_0l = DataItem.DataItem(numpy.zeros((0), numpy.double))
        self.document_model.append_data_item(data_item_real_0l)
        data_item_real_0w = DataItem.DataItem(numpy.zeros((256,0), numpy.double))
        self.document_model.append_data_item(data_item_real_0w)
        data_item_real_0h = DataItem.DataItem(numpy.zeros((0,256), numpy.double))
        self.document_model.append_data_item(data_item_real_0h)
        data_item_real_0z = DataItem.DataItem(numpy.zeros((0, 8, 8), numpy.double))
        self.document_model.append_data_item(data_item_real_0z)
        data_item_real_0z0w = DataItem.DataItem(numpy.zeros((16,0,256), numpy.double))
        self.document_model.append_data_item(data_item_real_0z0w)
        data_item_real_0z0h = DataItem.DataItem(numpy.zeros((16,256,0), numpy.double))
        self.document_model.append_data_item(data_item_real_0z0h)

        data_item_complex_0l = DataItem.DataItem(numpy.zeros((0), numpy.double))
        self.document_model.append_data_item(data_item_complex_0l)
        data_item_complex_0w = DataItem.DataItem(numpy.zeros((256,0), numpy.double))
        self.document_model.append_data_item(data_item_complex_0w)
        data_item_complex_0h = DataItem.DataItem(numpy.zeros((0,256), numpy.double))
        self.document_model.append_data_item(data_item_complex_0h)
        data_item_complex_0z = DataItem.DataItem(numpy.zeros((0, 8, 8), numpy.double))
        self.document_model.append_data_item(data_item_complex_0z)
        data_item_complex_0z0w = DataItem.DataItem(numpy.zeros((16,0,256), numpy.double))
        self.document_model.append_data_item(data_item_complex_0z0w)
        data_item_complex_0z0h = DataItem.DataItem(numpy.zeros((16,256,0), numpy.double))
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

        operation_list = []
        for data_item in data_list:
            operation_list.append((data_item, Operation.OperationItem("fft-operation")))
            operation_list.append((data_item, Operation.OperationItem("inverse-fft-operation")))
            operation_list.append((data_item, Operation.OperationItem("auto-correlate-operation")))
            operation_list.append((data_item, Operation.OperationItem("cross-correlate-operation")))
            operation_list.append((data_item, Operation.OperationItem("invert-operation")))
            operation_list.append((data_item, Operation.OperationItem("sobel-operation")))
            operation_list.append((data_item, Operation.OperationItem("laplace-operation")))
            operation_list.append((data_item, Operation.OperationItem("gaussian-blur-operation")))
            operation_list.append((data_item, Operation.OperationItem("median-filter-operation")))
            operation_list.append((data_item, Operation.OperationItem("uniform-filter-operation")))
            transpose_operation = Operation.OperationItem("transpose-flip-operation")
            transpose_operation.transpose = True
            transpose_operation.flip_horizontal = True
            transpose_operation.flip_vertical = True
            operation_list.append((data_item, transpose_operation))
            operation_list.append((data_item, Operation.OperationItem("crop-operation")))
            operation_list.append((data_item, Operation.OperationItem("slice-operation")))
            operation_list.append((data_item, Operation.OperationItem("pick-operation")))
            operation_list.append((data_item, Operation.OperationItem("projection-operation")))
            resample_2d_operation = Operation.OperationItem("resample-operation")
            resample_2d_operation.width = 128
            resample_2d_operation.height = 128
            operation_list.append((data_item, resample_2d_operation))
            operation_list.append((data_item, Operation.OperationItem("histogram-operation")))
            line_profile_operation = Operation.OperationItem("line-profile-operation")
            operation_list.append((data_item, line_profile_operation))
            operation_list.append((data_item, Operation.OperationItem("convert-to-scalar-operation")))

        for source_data_item, operation in operation_list:
            # logging.debug("%s, %s", source_data_item.maybe_data_source.data_shape_and_dtype, operation.operation_id)
            operation.add_data_source(source_data_item._create_test_data_source())
            data_item = DataItem.DataItem()
            data_item.set_operation(operation)
            self.document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item.recompute_data()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                self.assertEqual(data_item.operation.data_sources[0].source_data_item, source_data_item)
                self.assertIsNone(data_ref.data)
                self.assertEqual(display_specifier.buffered_data_source.dimensional_calibrations, [])

    def test_operations_on_none(self):

        data_item = DataItem.DataItem()
        self.document_model.append_data_item(data_item)

        operation_list = []
        operation_list.append((data_item, Operation.OperationItem("fft-operation")))
        operation_list.append((data_item, Operation.OperationItem("inverse-fft-operation")))
        operation_list.append((data_item, Operation.OperationItem("auto-correlate-operation")))
        operation_list.append((data_item, Operation.OperationItem("cross-correlate-operation")))
        operation_list.append((data_item, Operation.OperationItem("invert-operation")))
        operation_list.append((data_item, Operation.OperationItem("sobel-operation")))
        operation_list.append((data_item, Operation.OperationItem("laplace-operation")))
        operation_list.append((data_item, Operation.OperationItem("gaussian-blur-operation")))
        operation_list.append((data_item, Operation.OperationItem("median-filter-operation")))
        operation_list.append((data_item, Operation.OperationItem("uniform-filter-operation")))
        transpose_operation = Operation.OperationItem("transpose-flip-operation")
        transpose_operation.transpose = True
        transpose_operation.flip_horizontal = True
        transpose_operation.flip_vertical = True
        operation_list.append((data_item, transpose_operation))
        operation_list.append((data_item, Operation.OperationItem("crop-operation")))
        operation_list.append((data_item, Operation.OperationItem("slice-operation")))
        operation_list.append((data_item, Operation.OperationItem("pick-operation")))
        operation_list.append((data_item, Operation.OperationItem("projection-operation")))
        resample_2d_operation = Operation.OperationItem("resample-operation")
        resample_2d_operation.width = 128
        resample_2d_operation.height = 128
        operation_list.append((data_item, resample_2d_operation))
        operation_list.append((data_item, Operation.OperationItem("histogram-operation")))
        line_profile_operation = Operation.OperationItem("line-profile-operation")
        operation_list.append((data_item, line_profile_operation))
        operation_list.append((data_item, Operation.OperationItem("convert-to-scalar-operation")))

        for source_data_item, operation in operation_list:
            # logging.debug("%s, %s", source_data_item.maybe_data_source.data_shape_and_dtype, operation.operation_id)
            operation.add_data_source(source_data_item._create_test_data_source())
            data_item = DataItem.DataItem()
            data_item.set_operation(operation)
            self.document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            data_item.recompute_data()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                self.assertIsNone(data_item.operation.data_sources[0].source_data_item)
                self.assertIsNone(data_ref.data)
                self.assertEqual(display_specifier.buffered_data_source.dimensional_calibrations, [])

    def test_crop_2d_operation_returns_correct_dimensional_shape_and_data_shape(self):
        data_item = DataItem.DataItem(numpy.zeros((20,10), numpy.double))
        real_data_item = DataItem.DataItem()
        operation = Operation.OperationItem("crop-operation")
        operation.set_property("bounds", ((0.2, 0.3), (0.5, 0.5)))
        operation.add_data_source(data_item._create_test_data_source())
        real_data_item.set_operation(operation)
        real_display_specifier = DataItem.DisplaySpecifier.from_data_item(real_data_item)
        real_data_item.recompute_data()
        # make sure we get the right shape
        self.assertEqual(real_display_specifier.buffered_data_source.dimensional_shape, (10, 5))
        with real_display_specifier.buffered_data_source.data_ref() as data_real_accessor:
            self.assertEqual(data_real_accessor.data.shape, (10, 5))

    def test_fft_2d_dtype(self):
        data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.float64))
        self.document_model.append_data_item(data_item)

        fft_data_item = DataItem.DataItem()
        fft_operation = Operation.OperationItem("fft-operation")
        fft_operation.add_data_source(data_item._create_test_data_source())
        fft_data_item.set_operation(fft_operation)
        self.document_model.append_data_item(fft_data_item)
        fft_display_specifier = DataItem.DisplaySpecifier.from_data_item(fft_data_item)
        fft_data_item.recompute_data()

        with fft_display_specifier.buffered_data_source.data_ref() as fft_data_ref:
            self.assertEqual(fft_data_ref.data.shape, (16, 16))
            self.assertEqual(fft_data_ref.data.dtype, numpy.dtype(numpy.complex128))

    def test_convert_complex128_to_scalar_results_in_float64(self):
        data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.complex128))
        self.document_model.append_data_item(data_item)
        scalar_data_item = DataItem.DataItem()
        scalar_operation = Operation.OperationItem("convert-to-scalar-operation")
        scalar_operation.add_data_source(data_item._create_test_data_source())
        scalar_data_item.set_operation(scalar_operation)
        self.document_model.append_data_item(scalar_data_item)
        scalar_display_specifier = DataItem.DisplaySpecifier.from_data_item(scalar_data_item)
        scalar_data_item.recompute_data()
        with scalar_display_specifier.buffered_data_source.data_ref() as scalar_data_ref:
            self.assertEqual(scalar_data_ref.data.dtype, numpy.dtype(numpy.float64))

    class DummyOperation(Operation.Operation):
        def __init__(self):
            description = [ { "name": "Param", "property": "param", "type": "scalar", "default": 0.0 } ]
            super(TestOperationClass.DummyOperation, self).__init__("Dummy", "dummy-operation", description)
        def get_processed_data(self, data_sources, values):
            d = numpy.zeros((16, 16))
            d[:] = values.get("param")
            return d

    # test to ensure that no duplicate relationships are created
    def test_missing_operations_should_preserve_properties_when_saved(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((10, 10)))
        document_model.append_data_item(data_item)
        Operation.OperationManager().register_operation("dummy-operation", lambda: TestOperationClass.DummyOperation())
        dummy_operation = Operation.OperationItem("dummy-operation")
        data_item.set_operation(dummy_operation)
        dummy_operation.set_property("param", 5)
        document_controller.close()
        # unregister and read it back
        Operation.OperationManager().unregister_operation("dummy-operation")
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler, storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.assertEqual(document_model.data_items[0].operation.get_property("param"), 5)
        document_controller.close()

    def test_operation_should_reload_properties_when_saved(self):
        cache_name = ":memory:"
        data_reference_handler = DocumentModel.DataReferenceMemoryHandler()
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((4, 4)))
        document_model.append_data_item(data_item)
        Operation.OperationManager().register_operation("dummy-operation", lambda: TestOperationClass.DummyOperation())
        dummy_operation = Operation.OperationItem("dummy-operation")
        dummy_operation.add_data_source(data_item._create_test_data_source())
        data_item2 = DataItem.DataItem()
        data_item2.set_operation(dummy_operation)
        document_model.append_data_item(data_item2)
        dummy_operation.set_property("param", 5.2)
        data_item2.recompute_data()
        document_controller.close()
        # read it back then make sure parameter was actually updated
        document_model = DocumentModel.DocumentModel(data_reference_handler=data_reference_handler)
        read_data_item = document_model.data_items[1]
        read_display_specifier = DataItem.DisplaySpecifier.from_data_item(read_data_item)
        self.assertEqual(read_data_item.operation.get_property("param"), 5.2)
        with read_display_specifier.buffered_data_source.data_ref() as d:
            self.assertEqual(d.data[0, 0], 5.2)

    def test_rgba_invert_operation_should_retain_alpha(self):
        rgba_data_item = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
        rgba_display_specifier = DataItem.DisplaySpecifier.from_data_item(rgba_data_item)
        with rgba_display_specifier.buffered_data_source.data_ref() as data_ref:
            data_ref.master_data[:] = (20,40,60,100)
            data_ref.master_data_updated()
        rgba2_data_item = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(rgba_data_item._create_test_data_source())
        rgba2_data_item.set_operation(invert_operation)
        rgba2_display_specifier = DataItem.DisplaySpecifier.from_data_item(rgba2_data_item)
        rgba2_data_item.recompute_data()
        with rgba2_display_specifier.buffered_data_source.data_ref() as data_ref:
            pixel = data_ref.data[0,0,...]
            self.assertEqual(pixel[0], 255 - 20)
            self.assertEqual(pixel[1], 255 - 40)
            self.assertEqual(pixel[2], 255 - 60)
            self.assertEqual(pixel[3], 100)

    def test_deepcopy_of_crop_operation_should_copy_roi(self):
        data_item_rgba = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
        self.document_model.append_data_item(data_item_rgba)
        data_item_rgba2 = DataItem.DataItem()
        self.document_model.append_data_item(data_item_rgba2)
        operation = Operation.OperationItem("crop-operation")
        operation.set_property("bounds", ((0.25, 0.25), (0.5, 0.5)))
        operation.add_data_source(data_item_rgba._create_test_data_source())
        data_item_rgba2.set_operation(operation)
        data_item_rgba2_copy = copy.deepcopy(data_item_rgba2)
        # make sure the operation was copied
        self.assertNotEqual(data_item_rgba2.operation, data_item_rgba2_copy.operation)

    def test_snapshot_of_operation_should_copy_data_items(self):
        data_item_rgba = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
        self.document_model.append_data_item(data_item_rgba)
        data_item_rgba2 = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(data_item_rgba._create_test_data_source())
        data_item_rgba2.set_operation(invert_operation)
        self.document_model.append_data_item(data_item_rgba2)
        data_item_rgba2.recompute_data()
        self.display_panel.set_displayed_data_item(data_item_rgba2)
        self.assertEqual(self.document_controller.selected_display_specifier.data_item, data_item_rgba2)
        rgba_copy_buffered_data_source = self.document_controller.processing_snapshot().buffered_data_source
        self.assertTrue(rgba_copy_buffered_data_source.has_data)

    def test_snapshot_empty_data_item_should_produce_empty_data_item(self):
        data_item = DataItem.DataItem()
        data_item.append_data_source(DataItem.BufferedDataSource())
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertIsNone(display_specifier.buffered_data_source.data)
        self.assertIsNone(display_specifier.buffered_data_source.data_dtype)
        self.assertIsNone(display_specifier.buffered_data_source.data_shape)
        snapshot_data_item = data_item.snapshot()
        snapshot_display_specifier = DataItem.DisplaySpecifier.from_data_item(snapshot_data_item)
        self.assertIsNone(snapshot_display_specifier.buffered_data_source.data)
        self.assertIsNone(snapshot_display_specifier.buffered_data_source.data_dtype)
        self.assertIsNone(snapshot_display_specifier.buffered_data_source.data_shape)

    def test_snapshot_of_operation_should_copy_calibrations_not_dimensional_calibrations(self):
        # setup
        self.display_specifier.buffered_data_source.set_dimensional_calibration(0, Calibration.Calibration(5.0, 2.0, u"nm"))
        self.display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(5.0, 2.0, u"nm"))
        self.display_specifier.buffered_data_source.set_intensity_calibration(Calibration.Calibration(7.5, 2.5, u"ll"))
        data_item2 = DataItem.DataItem()
        operation = Operation.OperationItem("invert-operation")
        operation.add_data_source(self.data_item._create_test_data_source())
        data_item2.set_operation(operation)
        self.document_model.append_data_item(data_item2)
        display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item2)
        data_item2.recompute_data()
        # make sure our assumptions are correct
        self.assertEqual(len(self.display_specifier.buffered_data_source.dimensional_calibrations), 2)
        self.assertEqual(len(display_specifier2.buffered_data_source.dimensional_calibrations), 2)
        # take snapshot
        self.display_panel.set_displayed_data_item(data_item2)
        self.assertEqual(self.document_controller.selected_display_specifier.data_item, data_item2)
        buffered_data_source = self.document_controller.processing_snapshot().buffered_data_source
        # check calibrations
        self.assertEqual(len(buffered_data_source.dimensional_calibrations), 2)
        self.assertEqual(buffered_data_source.dimensional_calibrations[0].scale, 2.0)
        self.assertEqual(buffered_data_source.dimensional_calibrations[0].offset, 5.0)
        self.assertEqual(buffered_data_source.dimensional_calibrations[0].units, u"nm")
        self.assertEqual(buffered_data_source.dimensional_calibrations[1].scale, 2.0)
        self.assertEqual(buffered_data_source.dimensional_calibrations[1].offset, 5.0)
        self.assertEqual(buffered_data_source.dimensional_calibrations[1].units, u"nm")
        self.assertEqual(buffered_data_source.intensity_calibration.scale, 2.5)
        self.assertEqual(buffered_data_source.intensity_calibration.offset, 7.5)
        self.assertEqual(buffered_data_source.intensity_calibration.units, u"ll")

    def test_crop_2d_operation_on_calibrated_data_results_in_calibration_with_correct_offset(self):
        data_item = DataItem.DataItem(numpy.zeros((20, 10), numpy.double))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        spatial_calibration_0 = display_specifier.buffered_data_source.dimensional_calibrations[0]
        spatial_calibration_0.offset = 20.0
        spatial_calibration_0.scale = 5.0
        spatial_calibration_0.units = "dogs"
        spatial_calibration_1 = display_specifier.buffered_data_source.dimensional_calibrations[1]
        spatial_calibration_1.offset = 55.0
        spatial_calibration_1.scale = 5.5
        spatial_calibration_1.units = "cats"
        display_specifier.buffered_data_source.set_dimensional_calibration(0, spatial_calibration_0)
        display_specifier.buffered_data_source.set_dimensional_calibration(1, spatial_calibration_1)
        operation = Operation.OperationItem("crop-operation")
        operation.set_property("bounds", ((0.2, 0.3), (0.5, 0.5)))
        operation.add_data_source(data_item._create_test_data_source())
        data_item2 = DataItem.DataItem()
        data_item2.set_operation(operation)
        display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item2)
        data_item2.recompute_data()
        # make sure the calibrations are correct
        self.assertAlmostEqual(display_specifier2.buffered_data_source.dimensional_calibrations[0].offset, 20.0 + 20 * 0.2 * 5.0)
        self.assertAlmostEqual(display_specifier2.buffered_data_source.dimensional_calibrations[1].offset, 55.0 + 10 * 0.3 * 5.5)
        self.assertAlmostEqual(display_specifier2.buffered_data_source.dimensional_calibrations[0].scale, 5.0)
        self.assertAlmostEqual(display_specifier2.buffered_data_source.dimensional_calibrations[1].scale, 5.5)
        self.assertEqual(display_specifier2.buffered_data_source.dimensional_calibrations[0].units, "dogs")
        self.assertEqual(display_specifier2.buffered_data_source.dimensional_calibrations[1].units, "cats")

    def test_projection_2d_operation_on_calibrated_data_results_in_calibration_with_correct_offset(self):
        data_item = DataItem.DataItem(numpy.zeros((20, 10), numpy.double))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        spatial_calibration_0 = display_specifier.buffered_data_source.dimensional_calibrations[0]
        spatial_calibration_0.offset = 20.0
        spatial_calibration_0.scale = 5.0
        spatial_calibration_0.units = "dogs"
        spatial_calibration_1 = display_specifier.buffered_data_source.dimensional_calibrations[1]
        spatial_calibration_1.offset = 55.0
        spatial_calibration_1.scale = 5.5
        spatial_calibration_1.units = "cats"
        display_specifier.buffered_data_source.set_dimensional_calibration(0, spatial_calibration_0)
        display_specifier.buffered_data_source.set_dimensional_calibration(1, spatial_calibration_1)
        operation = Operation.OperationItem("projection-operation")
        operation.add_data_source(data_item._create_test_data_source())
        data_item2 = DataItem.DataItem()
        data_item2.set_operation(operation)
        display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item2)
        data_item2.recompute_data()
        # make sure the calibrations are correct
        self.assertAlmostEqual(display_specifier2.buffered_data_source.dimensional_calibrations[0].offset, 55.0)
        self.assertAlmostEqual(display_specifier2.buffered_data_source.dimensional_calibrations[0].scale, 5.5)
        self.assertEqual(display_specifier2.buffered_data_source.dimensional_calibrations[0].units, "cats")

    def test_crop_2d_region_connects_if_operation_added_after_data_item_is_in_document(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((20, 10), numpy.double))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            # configure the dependent item
            data_item2 = DataItem.DataItem()
            document_model.append_data_item(data_item2)
            crop_operation = Operation.OperationItem("crop-operation")
            crop_region = Region.RectRegion()
            DataItem.DisplaySpecifier.from_data_item(data_item).buffered_data_source.add_region(crop_region)
            crop_operation.add_data_source(data_item._create_test_data_source())
            crop_operation.establish_associated_region("crop", display_specifier.buffered_data_source, crop_region)
            data_item2.set_operation(crop_operation)
            # see if the region is connected to the operation
            self.assertEqual(crop_operation.get_property("bounds"), crop_region.bounds)
            bounds = ((0.3, 0.4), (0.5, 0.6))
            crop_operation.set_property("bounds", bounds)
            self.assertEqual(crop_operation.get_property("bounds"), crop_region.bounds)

    class Dummy2Operation(Operation.Operation):
        def __init__(self):
            description = [ { "name": "A", "property": "a", "type": "point", "default": (0.0, 0.0) }, { "name": "B", "property": "b", "type": "point", "default": (1.0, 1.0) } ]
            super(TestOperationClass.Dummy2Operation, self).__init__("Dummy", "dummy-operation", description)
            self.region_types = {"a": "point-region", "b": "point-region"}
            self.region_bindings = {"a": [Operation.RegionBinding("a", "position")], "b": [Operation.RegionBinding("b", "position")]}
        def get_processed_data(self, data_sources, values):
            return numpy.zeros((16, 16))

    def test_removing_operation_with_multiple_associated_regions_removes_all_regions(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # configure the source item
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            # configure the dependent item
            data_item2 = DataItem.DataItem()
            document_model.append_data_item(data_item2)
            Operation.OperationManager().register_operation("dummy2-operation", lambda: TestOperationClass.Dummy2Operation())
            dummy_operation = Operation.OperationItem("dummy2-operation")
            dummy_operation.establish_associated_region("a", display_specifier.buffered_data_source)
            dummy_operation.establish_associated_region("b", display_specifier.buffered_data_source)
            dummy_operation.add_data_source(data_item._create_test_data_source())
            data_item2.set_operation(dummy_operation)
            # assumptions
            self.assertEqual(len(display_specifier.buffered_data_source.regions), 2)
            # now remove the operation
            data_item2.set_operation(None)
            # check to make sure regions were removed
            self.assertEqual(len(display_specifier.buffered_data_source.regions), 0)

    def test_crop_works_on_selected_region_without_exception(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        display_panel.set_displayed_data_item(data_item)
        self.assertEqual(len(display_specifier.display.drawn_graphics), 0)
        crop_region = Region.RectRegion()
        crop_region.center = (0.5, 0.5)
        crop_region.size = (0.5, 1.0)
        data_item.maybe_data_source.add_region(crop_region)
        display_specifier.display.graphic_selection.set(0)
        document_controller.processing_crop().data_item
        document_controller.close()

    def test_remove_graphic_for_crop_removes_processed_data_item(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        display_panel.set_displayed_data_item(data_item)
        self.assertEqual(len(display_specifier.display.drawn_graphics), 0)
        crop_region = Region.RectRegion()
        crop_region.center = (0.5, 0.5)
        crop_region.size = (0.5, 1.0)
        data_item.maybe_data_source.add_region(crop_region)
        display_specifier.display.graphic_selection.set(0)
        cropped_data_item = document_controller.processing_crop().data_item
        document_controller.periodic()  # TODO: remove need to let the inspector catch up
        self.assertEqual(len(display_specifier.display.drawn_graphics), 1)
        self.assertTrue(cropped_data_item in document_model.data_items)
        display_specifier.display.graphic_selection.clear()
        display_specifier.display.graphic_selection.add(0)
        # make sure assumptions are correct
        self.assertEqual(cropped_data_item.operation.data_sources[0].source_data_item, data_item)
        self.assertTrue(cropped_data_item in document_model.data_items)
        # remove the graphic and make sure things are as expected
        document_controller.remove_graphic()
        self.assertEqual(len(display_specifier.display.drawn_graphics), 0)
        self.assertEqual(len(display_specifier.display.graphic_selection.indexes), 0)  # disabled until test_remove_line_profile_updates_graphic_selection
        self.assertFalse(cropped_data_item in document_model.data_items)
        # clean up
        document_controller.close()

    def test_remove_graphic_for_crop_combined_with_another_operation_removes_processed_data_item(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        display_panel.set_displayed_data_item(data_item)
        self.assertEqual(len(display_specifier.display.drawn_graphics), 0)
        crop_region = Region.RectRegion()
        crop_region.center = (0.5, 0.5)
        crop_region.size = (0.5, 1.0)
        data_item.maybe_data_source.add_region(crop_region)
        display_specifier.display.graphic_selection.set(0)
        projection_data_item = document_controller.processing_projection().data_item
        document_controller.periodic()  # TODO: remove need to let the inspector catch up
        self.assertTrue(projection_data_item in document_model.data_items)
        display_specifier.display.graphic_selection.clear()
        display_specifier.display.graphic_selection.add(0)
        # make sure assumptions are correct
        self.assertEqual(projection_data_item.operation.data_sources[0].data_sources[0].source_data_item, data_item)
        self.assertTrue(projection_data_item in document_model.data_items)
        # remove the graphic and make sure things are as expected
        document_controller.remove_graphic()
        self.assertEqual(len(display_specifier.display.drawn_graphics), 0)
        self.assertEqual(len(display_specifier.display.graphic_selection.indexes), 0)  # disabled until test_remove_line_profile_updates_graphic_selection
        self.assertFalse(projection_data_item in document_model.data_items)
        # clean up
        document_controller.close()

    def test_modifying_operation_results_in_data_computation(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # set up the data items
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            blurred_data_item = DataItem.DataItem()
            blur_operation = Operation.OperationItem("gaussian-blur-operation")
            blur_operation.add_data_source(data_item._create_test_data_source())
            blurred_data_item.set_operation(blur_operation)
            document_model.append_data_item(blurred_data_item)
            blurred_display_specifier = DataItem.DisplaySpecifier.from_data_item(blurred_data_item)
            # establish listeners
            class Listener(object):
                def __init__(self):
                    self.reset()
                def reset(self):
                    self._data_changed = False
                    self._display_changed = False
                def data_item_content_changed(self, data_item, changes):
                    self._data_changed = self._data_changed or DataItem.DATA in changes
            listener = Listener()
            blurred_data_item.add_listener(listener)
            def display_changed():
                listener._display_changed = True
            with contextlib.closing(blurred_display_specifier.display.display_changed_event.listen(display_changed)):
                # modify an operation. make sure data and dependent data gets updated.
                listener.reset()
                blur_operation.set_property("sigma", 0.1)
                document_model.recompute_all()
                self.assertTrue(listener._data_changed)
                self.assertTrue(listener._display_changed)

    def test_modifying_operation_region_results_in_data_computation(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # set up the data items
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            blurred_data_item = DataItem.DataItem()
            blur_operation = Operation.OperationItem("gaussian-blur-operation")
            blur_operation.add_data_source(data_item._create_test_data_source())
            blurred_data_item.set_operation(blur_operation)
            document_model.append_data_item(blurred_data_item)
            blurred_display_specifier = DataItem.DisplaySpecifier.from_data_item(blurred_data_item)
            # establish listeners
            class Listener(object):
                def __init__(self):
                    self.reset()
                def reset(self):
                    self._data_changed = False
                    self._display_changed = False
                def data_item_content_changed(self, data_item, changes):
                    self._data_changed = self._data_changed or DataItem.DATA in changes
            listener = Listener()
            blurred_data_item.add_listener(listener)
            def display_changed():
                listener._display_changed = True
            with contextlib.closing(blurred_display_specifier.display.display_changed_event.listen(display_changed)):
                # modify an operation. make sure data and dependent data gets updated.
                listener.reset()
                blur_operation.set_property("sigma", 0.1)
                document_model.recompute_all()
                self.assertTrue(listener._data_changed)
                self.assertTrue(listener._display_changed)

    def test_changing_region_does_not_trigger_fft_recompute(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            fft_data_item = DataItem.DataItem()
            fft_operation = Operation.OperationItem("fft-operation")
            fft_operation.add_data_source(data_item._create_test_data_source())
            fft_data_item.set_operation(fft_operation)
            document_model.append_data_item(fft_data_item)
            fft_display_specifier = DataItem.DisplaySpecifier.from_data_item(fft_data_item)
            crop_data_item = DataItem.DataItem()
            crop_operation = Operation.OperationItem("crop-operation")
            crop_region = Region.RectRegion()
            display_specifier.buffered_data_source.add_region(crop_region)
            crop_operation.establish_associated_region("crop", display_specifier.buffered_data_source, crop_region)
            crop_operation.add_data_source(data_item._create_test_data_source())
            crop_data_item.set_operation(crop_operation)
            crop_display_specifier = DataItem.DisplaySpecifier.from_data_item(crop_data_item)
            document_model.append_data_item(crop_data_item)
            document_model.recompute_all()
            self.assertFalse(fft_display_specifier.buffered_data_source.is_data_stale)
            self.assertFalse(crop_display_specifier.buffered_data_source.is_data_stale)
            crop_region.bounds = Geometry.FloatRect(crop_region.bounds[0], Geometry.FloatPoint(0.1, 0.1))
            self.assertTrue(crop_display_specifier.buffered_data_source.is_data_stale)
            self.assertFalse(fft_display_specifier.buffered_data_source.is_data_stale)

    def test_removing_source_of_cross_correlation_does_not_throw_exception(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            operation = Operation.OperationItem("cross-correlate-operation")
            operation.add_data_source(data_item1._create_test_data_source())
            operation.add_data_source(data_item2._create_test_data_source())
            cc_data_item = DataItem.DataItem()
            cc_data_item.set_operation(operation)
            document_model.append_data_item(cc_data_item)
            cc_data_item.recompute_data()
            document_model.remove_data_item(data_item1)
            cc_data_item.recompute_data()

    def test_crop_of_slice_of_3d_handles_dimensions(self):
        # the bug was that slice operation returned the wrong number of dimensions
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((16, 32, 32), numpy.float))
            document_model.append_data_item(data_item)
            slice_operation = Operation.OperationItem("slice-operation")
            slice_operation.add_data_source(data_item._create_test_data_source())
            slice_data_item = DataItem.DataItem()
            slice_data_item.set_operation(slice_operation)
            document_model.append_data_item(slice_data_item)
            document_model.recompute_all()
            crop_operation = Operation.OperationItem("crop-operation")
            crop_region = Region.RectRegion()
            slice_data_item.maybe_data_source.add_region(crop_region)
            crop_operation.establish_associated_region("crop", slice_data_item.maybe_data_source, crop_region)
            crop_operation.add_data_source(slice_data_item._create_test_data_source())
            crop_data_item = DataItem.DataItem()
            crop_data_item.set_operation(crop_operation)
            document_model.append_data_item(crop_data_item)
            document_model.recompute_all()


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
