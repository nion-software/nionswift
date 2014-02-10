# standard libraries
import copy
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
from nion.swift import ImagePanel
from nion.swift import Operation
from nion.swift import Storage
from nion.ui import Test


class TestOperationClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        self.document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        self.document_controller = DocumentController.DocumentController(self.app.ui, self.document_model, workspace_id="library")
        self.image_panel = self.document_controller.selected_image_panel
        self.data_item = self.document_controller.document_model.set_data_by_key("test", numpy.zeros((1000, 1000)))
        self.image_panel.data_item = self.data_item

    def tearDown(self):
        self.image_panel.close()
        self.document_controller.close()

    # make sure we can remove a single operation
    def test_remove_operation(self):
        operation = Operation.Operation("invert-operation")
        self.data_item.operations.append(operation)
        self.assertEqual(len(self.data_item.operations), 1)
        self.document_controller.remove_operation(operation)
        self.assertEqual(len(self.data_item.operations), 0)

    # make sure we can remove the second operation
    def test_multi_remove_operation(self):
        operation = Operation.Operation("invert-operation")
        self.data_item.operations.append(operation)
        self.assertEqual(len(self.data_item.operations), 1)
        operation2 = Operation.Operation("resample-operation")
        self.data_item.operations.append(operation2)
        self.assertEqual(len(self.data_item.operations), 2)
        self.document_controller.remove_operation(operation2)
        self.assertEqual(len(self.data_item.operations), 1)

    # make sure defaults get propogated when adding data item to document
    def test_default_propogation(self):
        # first make sure data and calibrations come out OK
        operation = Operation.Operation("resample-operation")
        self.data_item.operations.append(operation)
        with self.data_item.data_ref() as data_ref:
            data_ref.data  # just calculate it
        self.data_item.calculated_calibrations  # just calculate it
        # now create a new data item and add the operation before its added to document
        data_item = DataItem.DataItem()
        operation2 = Operation.Operation("resample-operation")
        data_item.operations.append(operation2)
        self.data_item.data_items.append(data_item)
        self.assertIsNotNone(operation2.description[0]["default"])
        self.assertIsNotNone(operation2.get_property("width"))

    # make sure crop gets disconnected when deleting
    def test_crop_disconnect(self):
        operation = Operation.Operation("crop-operation")
        operation.add_ref()
        graphic = Graphics.RectangleGraphic()
        operation.set_graphic("graphic", graphic)
        operation.remove_ref()

    # make sure profile gets disconnected when deleting
    def test_line_profile_disconnect(self):
        operation = Operation.Operation("line-profile-operation")
        operation.add_ref()
        graphic = Graphics.LineGraphic()
        operation.set_graphic("graphic", graphic)
        operation.remove_ref()

    # test operations against 1d data. doesn't test for correctness of the operation.
    def test_operations_1d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((256), numpy.double))
        data_item_real.add_ref()

        data_item_complex = DataItem.DataItem(numpy.zeros((256), numpy.complex128))
        data_item_complex.add_ref()

        operation_list = []
        operation_list.append((data_item_real, Operation.Operation("fft-operation")))
        operation_list.append((data_item_complex, Operation.Operation("inverse-fft-operation")))
        operation_list.append((data_item_real, Operation.Operation("invert-operation")))
        operation_list.append((data_item_real, Operation.Operation("gaussian-blur-operation")))
        operation_list.append((data_item_real, Operation.Operation("histogram-operation")))
        operation_list.append((data_item_real, Operation.Operation("convert-to-scale_operation")))

        for source_data_item, operation in operation_list:
            data_item = DataItem.DataItem()
            data_item.operations.append(operation)
            source_data_item.data_items.append(data_item)
            with data_item.data_ref() as data_ref:
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(data_item.calculated_calibrations)
                self.assertEqual(data_item.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(data_item.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(data_item.data_shape_and_dtype[1].type)  # make sure we're returning a dtype

        data_item_real.remove_ref()
        data_item_complex.remove_ref()

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_operations_2d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((256,256), numpy.double))
        data_item_real.add_ref()

        operation_list = []
        operation_list.append((data_item_real, Operation.Operation("fft-operation")))
        operation_list.append((data_item_real, Operation.Operation("invert-operation")))
        operation_list.append((data_item_real, Operation.Operation("gaussian-blur-operation")))
        crop_2d_operation = Operation.Operation("crop-operation")
        crop_2d_operation.set_graphic("graphic", Graphics.RectangleGraphic())
        operation_list.append((data_item_real, crop_2d_operation))
        resample_2d_operation = Operation.Operation("resample-operation")
        resample_2d_operation.width = 128
        resample_2d_operation.height = 128
        operation_list.append((data_item_real, resample_2d_operation))
        operation_list.append((data_item_real, Operation.Operation("histogram-operation")))
        line_profile_operation = Operation.Operation("line-profile-operation")
        line_profile_operation.set_graphic("graphic", Graphics.LineGraphic())
        operation_list.append((data_item_real, line_profile_operation))
        operation_list.append((data_item_real, Operation.Operation("convert-to-scale_operation")))

        for source_data_item, operation in operation_list:
            data_item = DataItem.DataItem()
            data_item.operations.append(operation)
            source_data_item.data_items.append(data_item)
            with data_item.data_ref() as data_ref:
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(data_item.calculated_calibrations)
                self.assertEqual(data_item.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(data_item.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(data_item.data_shape_and_dtype[1].type)  # make sure we're returning a dtype

        data_item_real.remove_ref()

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_operations_2d_rgb(self):
        data_item_rgb = DataItem.DataItem(numpy.zeros((256,256,3), numpy.uint8))
        data_item_rgb.add_ref()

        operation_list = []
        operation_list.append((data_item_rgb, Operation.Operation("invert-operation")))
        operation_list.append((data_item_rgb, Operation.Operation("gaussian-blur-operation")))
        crop_2d_operation = Operation.Operation("crop-operation")
        crop_2d_operation.set_graphic("graphic", Graphics.RectangleGraphic())
        operation_list.append((data_item_rgb, crop_2d_operation))
        resample_2d_operation = Operation.Operation("resample-operation")
        resample_2d_operation.width = 128
        resample_2d_operation.height = 128
        operation_list.append((data_item_rgb, resample_2d_operation))
        operation_list.append((data_item_rgb, Operation.Operation("histogram-operation")))
        line_profile_operation = Operation.Operation("line-profile-operation")
        line_profile_operation.set_graphic("graphic", Graphics.LineGraphic())
        operation_list.append((data_item_rgb, line_profile_operation))
        operation_list.append((data_item_rgb, Operation.Operation("convert-to-scale_operation")))

        for source_data_item, operation in operation_list:
            data_item = DataItem.DataItem()
            data_item.operations.append(operation)
            source_data_item.data_items.append(data_item)
            with data_item.data_ref() as data_ref:
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(data_item.calculated_calibrations)
                self.assertEqual(data_item.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(data_item.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(data_item.data_shape_and_dtype[1].type)  # make sure we're returning a dtype

        data_item_rgb.remove_ref()

    # test operations against 2d data. doesn't test for correctness of the operation.
    def test_operations_2d_rgba(self):
        data_item_rgb = DataItem.DataItem(numpy.zeros((256,256,4), numpy.uint8))
        with data_item_rgb.ref():

            operation_list = []
            operation_list.append((data_item_rgb, Operation.Operation("invert-operation")))
            operation_list.append((data_item_rgb, Operation.Operation("gaussian-blur-operation")))
            crop_2d_operation = Operation.Operation("crop-operation")
            crop_2d_operation.set_graphic("graphic", Graphics.RectangleGraphic())
            operation_list.append((data_item_rgb, crop_2d_operation))
            resample_2d_operation = Operation.Operation("resample-operation")
            resample_2d_operation.width = 128
            resample_2d_operation.height = 128
            operation_list.append((data_item_rgb, resample_2d_operation))
            operation_list.append((data_item_rgb, Operation.Operation("histogram-operation")))
            line_profile_operation = Operation.Operation("line-profile-operation")
            line_profile_operation.set_graphic("graphic", Graphics.LineGraphic())
            operation_list.append((data_item_rgb, line_profile_operation))
            operation_list.append((data_item_rgb, Operation.Operation("convert-to-scale_operation")))

            for source_data_item, operation in operation_list:
                data_item = DataItem.DataItem()
                data_item.operations.append(operation)
                source_data_item.data_items.append(data_item)
                with data_item.data_ref() as data_ref:
                    self.assertIsNotNone(data_ref.data)
                    self.assertIsNotNone(data_item.calculated_calibrations)
                    self.assertEqual(data_item.data_shape_and_dtype[0], data_ref.data.shape)
                    self.assertEqual(data_item.data_shape_and_dtype[1], data_ref.data.dtype)
                    self.assertIsNotNone(data_item.data_shape_and_dtype[1].type)  # make sure we're returning a dtype

    def test_operations_2d_complex(self):
        data_item_complex = DataItem.DataItem(numpy.zeros((256,256), numpy.complex128))
        data_item_complex.add_ref()

        operation_list = []
        operation_list.append((data_item_complex, Operation.Operation("inverse-fft-operation")))

        for source_data_item, operation in operation_list:
            data_item = DataItem.DataItem()
            data_item.operations.append(operation)
            source_data_item.data_items.append(data_item)
            with data_item.data_ref() as data_ref:
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(data_item.calculated_calibrations)
                self.assertEqual(data_item.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(data_item.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(data_item.data_shape_and_dtype[1].type)  # make sure we're returning a dtype

        data_item_complex.remove_ref()

    def test_crop_2d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        data_item_real.add_ref()
        graphic = Graphics.RectangleGraphic()
        graphic.bounds = ((0.2, 0.3), (0.5, 0.5))
        operation = Operation.Operation("crop-operation")
        operation.set_graphic("graphic", graphic)
        data_item_real.operations.append(operation)
        # make sure we get the right shape
        self.assertEqual(data_item_real.spatial_shape, (1000, 500))
        with data_item_real.data_ref() as data_real_accessor:
            self.assertEqual(data_real_accessor.data.shape, (1000, 500))
        data_item_real.remove_ref()

    def test_fft_2d_dtype(self):
        data_item = DataItem.DataItem(numpy.zeros((512,512), numpy.float64))
        data_item.add_ref()

        fft_data_item = DataItem.DataItem()
        fft_data_item.operations.append(Operation.Operation("fft-operation"))
        data_item.data_items.append(fft_data_item)

        with fft_data_item.data_ref() as fft_data_ref:
            self.assertEqual(fft_data_ref.data.shape, (512, 512))
            self.assertEqual(fft_data_ref.data.dtype, numpy.complex128)

    class DummyOperationBehavior(Operation.OperationBehavior):
        def __init__(self):
            description = [ { "name": "Param", "property": "param", "type": "scalar", "default": 0.0 } ]
            super(TestOperationClass.DummyOperationBehavior, self).__init__("Dummy", "dummy-operation", description)
        def process_data_copy(self, data_copy):
            return numpy.zeros((16, 16))

    # test to ensure that no duplicate relationships are created
    def test_missing_operations_should_preserve_properties_when_saved(self):
        db_name = ":memory:"
        datastore = Storage.DbDatastore(None, db_name)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = document_controller.document_model.set_data_by_key("test", numpy.zeros((1000, 1000)))
        Operation.OperationManager().register_operation_behavior("dummy-operation", lambda: TestOperationClass.DummyOperationBehavior())
        dummy_operation = Operation.Operation("dummy-operation")
        data_item.operations.append(dummy_operation)
        dummy_operation.set_property("param", 5)
        storage_data = document_model.datastore.to_data()
        document_controller.close()
        # unregister and read it back
        Operation.OperationManager().unregister_operation_behavior("dummy-operation")
        datastore = Storage.DbDatastore(None, db_name, storage_data=storage_data)
        storage_cache = Storage.DbStorageCache(db_name)
        document_model = DocumentModel.DocumentModel(datastore, storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        self.assertEqual(document_model.data_items[0].operations[0].get_property("param"), 5)

    def test_rgba_invert_operation_should_retain_alpha(self):
        data_item_rgba = DataItem.DataItem(numpy.zeros((256,256,4), numpy.uint8))
        with data_item_rgba.ref():
            with data_item_rgba.data_ref() as data_ref:
                data_ref.master_data[:] = (20,40,60,100)
            data_item_rgba.operations.append(Operation.Operation("invert-operation"))
            with data_item_rgba.data_ref() as data_ref:
                pixel = data_ref.data[0,0,...]
                self.assertEqual(pixel[0], 255 - 20)
                self.assertEqual(pixel[1], 255 - 40)
                self.assertEqual(pixel[2], 255 - 60)
                self.assertEqual(pixel[3], 100)

    def test_deepcopy_of_crop_operation_should_copy_roi(self):
        data_item_rgba = DataItem.DataItem(numpy.zeros((256,256,4), numpy.uint8))
        with data_item_rgba.ref():
            data_item_rgba2 = DataItem.DataItem()
            with data_item_rgba2.ref():
                data_item_rgba2.data_source = data_item_rgba
                graphic1 = Graphics.RectangleGraphic()
                graphic1.bounds = ((0.25, 0.25), (0.5, 0.5))
                data_item_rgba.graphics.append(graphic1)
                operation = Operation.Operation("crop-operation")
                operation.set_graphic("graphic", graphic1)
                data_item_rgba2.operations.append(operation)
                data_item_rgba2_copy = copy.deepcopy(data_item_rgba2)
                with data_item_rgba2_copy.ref():
                    # make sure the operation was copied
                    self.assertNotEqual(data_item_rgba2.operations[0], data_item_rgba2_copy.operations[0])
                    # and that the two operations shared the same graphic
                    self.assertEqual(data_item_rgba2.operations[0].graphic, data_item_rgba2_copy.operations[0].graphic)
                    # and for safety that the graphic is what we expect it to be
                    self.assertEqual(data_item_rgba.graphics[0], data_item_rgba2.operations[0].graphic)

    def test_snapshot_of_operation_should_copy_data_items(self):
        data_item_rgba = DataItem.DataItem(numpy.zeros((256,256,4), numpy.uint8))
        self.document_model.append_data_item(data_item_rgba)
        data_item_rgba2 = DataItem.DataItem()
        data_item_rgba2.operations.append(Operation.Operation("invert-operation"))
        data_item_rgba.data_items.append(data_item_rgba2)
        self.image_panel.data_item = data_item_rgba2
        self.assertEqual(self.document_controller.selected_data_item, data_item_rgba2)
        self.document_controller.processing_snapshot()
        data_item_rgba_copy = self.document_model.data_items[2]
        self.assertTrue(data_item_rgba_copy.has_master_data)

    def test_snapshot_of_operation_should_result_in_new_master_data(self):
        data_item2 = DataItem.DataItem()
        data_item2.operations.append(Operation.Operation("invert-operation"))
        self.data_item.data_items.append(data_item2)
        self.image_panel.data_item = self.data_item
        self.assertEqual(self.document_controller.selected_data_item, self.data_item)
        self.document_controller.processing_snapshot()
        data_item_copy = self.document_model.data_items[1]
        self.assertEqual(len(data_item_copy.data_items), 1)
        self.assertEqual(data_item_copy.data_items[0].data_source, data_item_copy)

    def test_snapshot_of_operation_should_copy_calibrations_not_intrinsic_calibrations(self):
        # setup
        self.data_item.intrinsic_calibrations[0].scale = 2.0
        self.data_item.intrinsic_calibrations[0].origin = 5.0
        self.data_item.intrinsic_calibrations[0].units = u"nm"
        self.data_item.intrinsic_calibrations[1].scale = 2.0
        self.data_item.intrinsic_calibrations[1].origin = 5.0
        self.data_item.intrinsic_calibrations[1].units = u"nm"
        self.data_item.intrinsic_intensity_calibration.scale = 2.5
        self.data_item.intrinsic_intensity_calibration.origin = 7.5
        self.data_item.intrinsic_intensity_calibration.units = u"ll"
        data_item2 = DataItem.DataItem()
        data_item2.operations.append(Operation.Operation("invert-operation"))
        self.data_item.data_items.append(data_item2)
        # make sure our assumptions are correct
        self.assertEqual(len(self.data_item.calculated_calibrations), 2)
        self.assertEqual(len(self.data_item.intrinsic_calibrations), 2)
        self.assertEqual(len(data_item2.calculated_calibrations), 2)
        self.assertEqual(len(data_item2.intrinsic_calibrations), 0)
        # take snapshot
        self.image_panel.data_item = data_item2
        self.assertEqual(self.document_controller.selected_data_item, data_item2)
        self.document_controller.processing_snapshot()
        data_item_copy = self.document_model.data_items[1]
        # check calibrations
        self.assertEqual(len(data_item_copy.calculated_calibrations), 2)
        self.assertEqual(len(data_item_copy.intrinsic_calibrations), 2)
        self.assertEqual(data_item_copy.intrinsic_calibrations[0].scale, 2.0)
        self.assertEqual(data_item_copy.intrinsic_calibrations[0].origin, 5.0)
        self.assertEqual(data_item_copy.intrinsic_calibrations[0].units, u"nm")
        self.assertEqual(data_item_copy.intrinsic_calibrations[1].scale, 2.0)
        self.assertEqual(data_item_copy.intrinsic_calibrations[1].origin, 5.0)
        self.assertEqual(data_item_copy.intrinsic_calibrations[1].units, u"nm")
        self.assertEqual(data_item_copy.intrinsic_intensity_calibration.scale, 2.5)
        self.assertEqual(data_item_copy.intrinsic_intensity_calibration.origin, 7.5)
        self.assertEqual(data_item_copy.intrinsic_intensity_calibration.units, u"ll")

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
