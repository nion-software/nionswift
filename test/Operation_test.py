# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DataItem
from nion.swift import DocumentController
from nion.swift import DocumentModel
from nion.swift import Graphics
from nion.swift import Operation
from nion.swift import Storage
from nion.swift import Test


class TestOperationClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)
        db_name = ":memory:"
        storage_writer = Storage.DbStorageWriter(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(storage_writer, storage_cache)
        self.document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.document_controller.document_model.create_default_data_groups()
        default_data_group = self.document_controller.document_model.data_groups[0]
        self.image_panel = self.document_controller.selected_image_panel
        self.data_item = self.document_controller.document_model.set_data_by_key("test", numpy.zeros((1000, 1000)))
        self.image_panel.data_panel_selection = DataItem.DataItemSpecifier(default_data_group, self.data_item)

    def tearDown(self):
        self.image_panel.close()
        self.document_controller.close()

    # make sure we can remove a single operation
    def test_remove_operation(self):
        operation = Operation.InvertOperation()
        self.data_item.operations.append(operation)
        self.assertEqual(len(self.data_item.operations), 1)
        self.document_controller.remove_operation(operation)
        self.assertEqual(len(self.data_item.operations), 0)

    # make sure we can remove the second operation
    def test_multi_remove_operation(self):
        operation = Operation.InvertOperation()
        self.data_item.operations.append(operation)
        self.assertEqual(len(self.data_item.operations), 1)
        operation2 = Operation.Resample2dOperation()
        self.data_item.operations.append(operation2)
        self.assertEqual(len(self.data_item.operations), 2)
        self.document_controller.remove_operation(operation2)
        self.assertEqual(len(self.data_item.operations), 1)

    # make sure defaults get propogated when adding data item to document
    def test_default_propogation(self):
        # first make sure data and calibrations come out OK
        operation = Operation.Resample2dOperation()
        self.data_item.operations.append(operation)
        with self.data_item.create_data_accessor() as data_accessor:
            data_accessor.data  # just calculate it
        self.data_item.calculated_calibrations  # just calculate it
        # now create a new data item and add the operation before its added to document
        data_item = DataItem.DataItem()
        operation2 = Operation.Resample2dOperation()
        data_item.operations.append(operation2)
        self.data_item.data_items.append(data_item)
        self.assertIsNotNone(operation2.description[0]["default"])
        self.assertIsNotNone(operation2.width)

    # make sure crop gets disconnected when deleting
    def test_crop_disconnect(self):
        operation = Operation.Crop2dOperation()
        operation.add_ref()
        graphic = Graphics.RectangleGraphic()
        operation.graphic = graphic
        operation.remove_ref()

    # make sure profile gets disconnected when deleting
    def test_line_profile_disconnect(self):
        operation = Operation.LineProfileOperation()
        operation.add_ref()
        graphic = Graphics.LineGraphic()
        operation.graphic = graphic
        operation.remove_ref()

    # test operations against 1d data. doesn't test for correctness of the operation.
    def test_operations_1d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((256), numpy.double))
        data_item_real.add_ref()

        data_item_complex = DataItem.DataItem(numpy.zeros((256), numpy.complex128))
        data_item_complex.add_ref()

        operation_list = []
        operation_list.append((data_item_real, Operation.FFTOperation()))
        operation_list.append((data_item_complex, Operation.IFFTOperation()))
        operation_list.append((data_item_real, Operation.InvertOperation()))
        operation_list.append((data_item_real, Operation.GaussianBlurOperation()))
        operation_list.append((data_item_real, Operation.HistogramOperation()))
        operation_list.append((data_item_real, Operation.ConvertToScalarOperation()))

        for source_data_item, operation in operation_list:
            data_item = DataItem.DataItem()
            data_item.operations.append(operation)
            source_data_item.data_items.append(data_item)
            with data_item.create_data_accessor() as data_accessor:
                self.assertIsNotNone(data_accessor.data)
                self.assertIsNotNone(data_item.calculated_calibrations)
                self.assertEqual(data_item.data_shape_and_dtype[0], data_accessor.data.shape)
                self.assertEqual(data_item.data_shape_and_dtype[1], data_accessor.data.dtype)

        data_item_real.remove_ref()
        data_item_complex.remove_ref()

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_operations_2d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((256,256), numpy.double))
        data_item_real.add_ref()

        operation_list = []
        operation_list.append((data_item_real, Operation.FFTOperation()))
        operation_list.append((data_item_real, Operation.InvertOperation()))
        operation_list.append((data_item_real, Operation.GaussianBlurOperation()))
        operation_list.append((data_item_real, Operation.Crop2dOperation(Graphics.RectangleGraphic())))
        operation_list.append((data_item_real, Operation.Resample2dOperation(128,128)))
        operation_list.append((data_item_real, Operation.HistogramOperation()))
        operation_list.append((data_item_real, Operation.LineProfileOperation(Graphics.LineGraphic())))
        operation_list.append((data_item_real, Operation.ConvertToScalarOperation()))

        for source_data_item, operation in operation_list:
            data_item = DataItem.DataItem()
            data_item.operations.append(operation)
            source_data_item.data_items.append(data_item)
            with data_item.create_data_accessor() as data_accessor:
                self.assertIsNotNone(data_accessor.data)
                self.assertIsNotNone(data_item.calculated_calibrations)
                self.assertEqual(data_item.data_shape_and_dtype[0], data_accessor.data.shape)
                self.assertEqual(data_item.data_shape_and_dtype[1], data_accessor.data.dtype)

        data_item_real.remove_ref()

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_operations_2d_rgb(self):
        data_item_rgb = DataItem.DataItem(numpy.zeros((256,256,3), numpy.uint8))
        data_item_rgb.add_ref()

        operation_list = []
        operation_list.append((data_item_rgb, Operation.InvertOperation()))
        operation_list.append((data_item_rgb, Operation.GaussianBlurOperation()))
        operation_list.append((data_item_rgb, Operation.Crop2dOperation(Graphics.RectangleGraphic())))
        operation_list.append((data_item_rgb, Operation.Resample2dOperation(128,128)))
        operation_list.append((data_item_rgb, Operation.HistogramOperation()))
        operation_list.append((data_item_rgb, Operation.LineProfileOperation(Graphics.LineGraphic())))
        operation_list.append((data_item_rgb, Operation.ConvertToScalarOperation()))

        for source_data_item, operation in operation_list:
            data_item = DataItem.DataItem()
            data_item.operations.append(operation)
            source_data_item.data_items.append(data_item)
            with data_item.create_data_accessor() as data_accessor:
                self.assertIsNotNone(data_accessor.data)
                self.assertIsNotNone(data_item.calculated_calibrations)
                self.assertEqual(data_item.data_shape_and_dtype[0], data_accessor.data.shape)
                self.assertEqual(data_item.data_shape_and_dtype[1], data_accessor.data.dtype)

        data_item_rgb.remove_ref()

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_operations_2d_rgba(self):
        data_item_rgb = DataItem.DataItem(numpy.zeros((256,256,4), numpy.uint8))
        data_item_rgb.add_ref()

        operation_list = []
        operation_list.append((data_item_rgb, Operation.InvertOperation()))
        operation_list.append((data_item_rgb, Operation.GaussianBlurOperation()))
        operation_list.append((data_item_rgb, Operation.Crop2dOperation(Graphics.RectangleGraphic())))
        operation_list.append((data_item_rgb, Operation.Resample2dOperation(128,128)))
        operation_list.append((data_item_rgb, Operation.HistogramOperation()))
        operation_list.append((data_item_rgb, Operation.LineProfileOperation(Graphics.LineGraphic())))
        operation_list.append((data_item_rgb, Operation.ConvertToScalarOperation()))

        for source_data_item, operation in operation_list:
            data_item = DataItem.DataItem()
            data_item.operations.append(operation)
            source_data_item.data_items.append(data_item)
            with data_item.create_data_accessor() as data_accessor:
                self.assertIsNotNone(data_accessor.data)
                self.assertIsNotNone(data_item.calculated_calibrations)
                self.assertEqual(data_item.data_shape_and_dtype[0], data_accessor.data.shape)
                self.assertEqual(data_item.data_shape_and_dtype[1], data_accessor.data.dtype)

        data_item_rgb.remove_ref()

    def test_operations_2d_complex(self):
        data_item_complex = DataItem.DataItem(numpy.zeros((256,256), numpy.complex128))
        data_item_complex.add_ref()

        operation_list = []
        operation_list.append((data_item_complex, Operation.IFFTOperation()))

        for source_data_item, operation in operation_list:
            data_item = DataItem.DataItem()
            data_item.operations.append(operation)
            source_data_item.data_items.append(data_item)
            with data_item.create_data_accessor() as data_accessor:
                self.assertIsNotNone(data_accessor.data)
                self.assertIsNotNone(data_item.calculated_calibrations)
                self.assertEqual(data_item.data_shape_and_dtype[0], data_accessor.data.shape)
                self.assertEqual(data_item.data_shape_and_dtype[1], data_accessor.data.dtype)

        data_item_complex.remove_ref()

    def test_crop_2d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        data_item_real.add_ref()
        graphic = Graphics.RectangleGraphic()
        graphic.bounds = ((0.2, 0.3), (0.5, 0.5))
        operation = Operation.Crop2dOperation()
        operation.graphic = graphic
        data_item_real.operations.append(operation)
        # make sure we get the right shape
        self.assertEqual(data_item_real.spatial_shape, (1000, 500))
        with data_item_real.create_data_accessor() as data_real_accessor:
            self.assertEqual(data_real_accessor.data.shape, (1000, 500))
        data_item_real.remove_ref()

    def test_fft_2d_dtype(self):
        data_item = DataItem.DataItem(numpy.zeros((512,512), numpy.float64))
        data_item.add_ref()

        fft_data_item = DataItem.DataItem()
        fft_data_item.operations.append(Operation.FFTOperation())
        data_item.data_items.append(fft_data_item)

        with fft_data_item.create_data_accessor() as fft_data_accessor:
            self.assertEqual(fft_data_accessor.data.shape, (512, 512))
            self.assertEqual(fft_data_accessor.data.dtype, numpy.complex128)
