# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DataItem
from nion.swift import DocumentController
from nion.swift import Graphics
from nion.swift import Operation
from nion.swift import Storage
from nion.swift import Test


class TestOperationClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)
        db_name = ":memory:"
        storage_writer = Storage.DbStorageWriter(db_name, create=True)
        self.document_controller = DocumentController.DocumentController(self.app.ui, None, storage_writer)
        self.document_controller.create_default_data_groups()
        default_data_group = self.document_controller.data_groups[0]
        self.image_panel = self.document_controller.selected_image_panel
        self.data_item = self.document_controller.set_data_by_key("test", numpy.zeros((1000, 1000)))
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
        self.data_item.data  # just calculate it
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
        data_item_real = DataItem.DataItem()
        data_item_real.master_data = numpy.zeros((256), numpy.double)
        data_item_real.add_ref()

        data_item_complex = DataItem.DataItem()
        data_item_complex.master_data = numpy.zeros((256), numpy.complex128)
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
            self.assertIsNotNone(data_item.data)
            self.assertIsNotNone(data_item.calculated_calibrations)

        data_item_real.remove_ref()
        data_item_complex.remove_ref()

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_operations_2d(self):
        data_item_real = DataItem.DataItem()
        data_item_real.master_data = numpy.zeros((256,256), numpy.double)
        data_item_real.add_ref()

        data_item_complex = DataItem.DataItem()
        data_item_complex.master_data = numpy.zeros((256,256), numpy.complex128)
        data_item_complex.add_ref()

        operation_list = []
        operation_list.append((data_item_real, Operation.FFTOperation()))
        operation_list.append((data_item_complex, Operation.IFFTOperation()))
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
            self.assertIsNotNone(data_item.data)
            self.assertIsNotNone(data_item.calculated_calibrations)

        data_item_real.remove_ref()
        data_item_complex.remove_ref()

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_operations_2d(self):
        data_item_rgb = DataItem.DataItem()
        data_item_rgb.master_data = numpy.zeros((256,256), numpy.double)
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
            self.assertIsNotNone(data_item.data)
            self.assertIsNotNone(data_item.calculated_calibrations)

        data_item_rgb.remove_ref()

    def test_crop_2d(self):
        data_item_real = DataItem.DataItem()
        data_item_real.master_data = numpy.zeros((2000,1000), numpy.double)
        data_item_real.add_ref()
        graphic = Graphics.RectangleGraphic()
        graphic.bounds = ((0.2, 0.3), (0.5, 0.5))
        operation = Operation.Crop2dOperation()
        operation.graphic = graphic
        data_item_real.operations.append(operation)
        # make sure we get the right shape
        self.assertEqual(data_item_real.spatial_shape, (1000, 500))
        self.assertEqual(data_item_real.data.shape, (1000, 500))
        data_item_real.remove_ref()
