# standard libraries
import copy
import gc
import logging
import math
import threading
import unittest
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift.model import Calibration
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Image
from nion.swift.model import Operation
from nion.swift.model import Region
from nion.swift.model import Storage
from nion.ui import Test


class TestCalibrationClass(unittest.TestCase):

    def test_conversion(self):
        calibration = Calibration.Calibration(3.0, 2.0, "x")
        self.assertEqual(calibration.convert_to_calibrated_value_str(5.0), u"13 x")

    def test_dependent_calibration(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.set_spatial_calibration(0, Calibration.Calibration(3.0, 2.0, u"x"))
        data_item.set_spatial_calibration(1, Calibration.Calibration(3.0, 2.0, u"x"))
        self.assertEqual(len(data_item.intrinsic_calibrations), 2)
        data_item_copy = DataItem.DataItem()
        data_item_copy.add_operation(Operation.OperationItem("invert-operation"))
        data_item_copy.add_data_source(data_item)
        data_item_copy.connect_data_sources(direct_data_sources=[data_item])
        calculated_calibrations = data_item_copy.calculated_calibrations
        self.assertEqual(len(calculated_calibrations), 2)
        self.assertEqual(int(calculated_calibrations[0].offset), 3)
        self.assertEqual(int(calculated_calibrations[0].scale), 2)
        self.assertEqual(calculated_calibrations[0].units, "x")
        self.assertEqual(int(calculated_calibrations[1].offset), 3)
        self.assertEqual(int(calculated_calibrations[1].scale), 2)
        self.assertEqual(calculated_calibrations[1].units, "x")
        data_item_copy.add_operation(Operation.OperationItem("fft-operation"))
        calculated_calibrations = data_item_copy.calculated_calibrations
        self.assertEqual(int(calculated_calibrations[0].offset), 0)
        self.assertEqual(calculated_calibrations[0].units, "1/x")
        self.assertEqual(int(calculated_calibrations[1].offset), 0)
        self.assertEqual(calculated_calibrations[1].units, "1/x")

    def test_double_dependent_calibration(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item2 = DataItem.DataItem()
        operation2 = Operation.OperationItem("resample-operation")
        data_item2.add_operation(operation2)
        data_item2.add_data_source(data_item)
        data_item2.connect_data_sources(direct_data_sources=[data_item])
        data_item3 = DataItem.DataItem()
        operation3 = Operation.OperationItem("resample-operation")
        data_item3.add_operation(operation3)
        data_item3.add_data_source(data_item2)
        data_item3.connect_data_sources(direct_data_sources=[data_item2])
        data_item3.calculated_calibrations

    def test_spatial_calibration_on_rgb(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256, 4), numpy.uint8))
        self.assertTrue(Image.is_shape_and_dtype_2d(*data_item.data_shape_and_dtype))
        self.assertTrue(Image.is_shape_and_dtype_rgba(*data_item.data_shape_and_dtype))
        self.assertEqual(len(data_item.intrinsic_calibrations), 2)

    def test_calibration_should_work_for_complex_data(self):
        calibration = Calibration.Calibration(1.0, 2.0, "c")
        value_array = numpy.zeros((1, ), dtype=numpy.complex128)
        value_array[0] = 3 + 4j
        self.assertEqual(calibration.convert_to_calibrated_value_str(value_array[0]), u"7+8j c")
        self.assertEqual(calibration.convert_to_calibrated_size_str(value_array[0]), u"6+8j c")

    def test_calibration_should_work_for_rgb_data(self):
        calibration = Calibration.Calibration(1.0, 2.0, "c")
        value = numpy.zeros((4, ), dtype=numpy.uint8)
        self.assertEqual(calibration.convert_to_calibrated_value_str(value), "0, 0, 0, 0")
        self.assertEqual(calibration.convert_to_calibrated_size_str(value), "0, 0, 0, 0")

    def test_calibration_conversion_to_string_can_handle_numpy_types(self):
        calibration = Calibration.Calibration(1.0, 2.0, "c")
        self.assertEqual(calibration.convert_to_calibrated_value_str(numpy.uint32(14)), "29 c")


class TestDataItemClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_delete_data_item(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        weak_data_item = weakref.ref(data_item)
        data_item = None
        gc.collect()
        self.assertIsNone(weak_data_item())

    def test_copy_data_item(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.title = "data_item"
        with data_item.open_metadata("test") as metadata:
            metadata["one"] = 1
            metadata["two"] = 22
        with data_item.data_ref() as data_ref:
            data_ref.master_data[128, 128] = 1000  # data range (0, 1000)
            data_ref.master_data_updated()
        data_item.displays[0].display_limits = (100, 900)
        data_item.add_operation(Operation.OperationItem("invert-operation"))
        data_item.displays[0].append_graphic(Graphics.RectangleGraphic())
        data_item_copy = copy.deepcopy(data_item)
        with data_item_copy.data_ref() as data_copy_accessor:
            # make sure the data is not shared between the original and the copy
            self.assertEqual(data_ref.master_data[0,0], 0)
            self.assertEqual(data_copy_accessor.master_data[0,0], 0)
            data_ref.master_data[:] = 1
            data_ref.master_data_updated()
            self.assertEqual(data_ref.master_data[0,0], 1)
            self.assertEqual(data_copy_accessor.master_data[0,0], 0)
        # make sure properties and other items got copied
        #self.assertEqual(len(data_item_copy.properties), 19)  # not valid since properties only exist if in document
        self.assertIsNot(data_item.properties, data_item_copy.properties)
        # uuid should not match
        self.assertNotEqual(data_item.uuid, data_item_copy.uuid)
        self.assertEqual(data_item.writer_version, data_item_copy.writer_version)
        # metadata get copied?
        self.assertEqual(len(data_item.get_metadata("test")), 2)
        self.assertIsNot(data_item.get_metadata("test"), data_item_copy.get_metadata("test"))
        # make sure display counts match
        self.assertEqual(len(data_item.displays), len(data_item_copy.displays))
        self.assertEqual(len(data_item.operations), len(data_item_copy.operations))
        # tuples and strings are immutable, so test to make sure old/new are independent
        self.assertEqual(data_item.title, data_item_copy.title)
        data_item.title = "data_item1"
        self.assertNotEqual(data_item.title, data_item_copy.title)
        self.assertEqual(data_item.displays[0].display_limits, data_item_copy.displays[0].display_limits)
        data_item.displays[0].display_limits = (150, 200)
        self.assertNotEqual(data_item.displays[0].display_limits, data_item_copy.displays[0].display_limits)
        # make sure dates are independent
        self.assertIsNot(data_item.datetime_modified, data_item_copy.datetime_modified)
        self.assertIsNot(data_item.datetime_original, data_item_copy.datetime_original)
        # make sure calibrations, operations, nor graphics are not shared
        self.assertNotEqual(data_item.intrinsic_calibrations[0], data_item_copy.intrinsic_calibrations[0])
        self.assertNotEqual(data_item.operations[0], data_item_copy.operations[0])
        self.assertNotEqual(data_item.displays[0].graphics[0], data_item_copy.displays[0].graphics[0])

    def test_copy_data_item_properly_copies_data_source_and_connects_it(self):
        document_model = DocumentModel.DocumentModel()
        # setup by adding data item and a dependent data item
        data_item2 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item2a = DataItem.DataItem()
        operation2a = Operation.OperationItem("resample-operation")
        data_item2a.add_operation(operation2a)
        data_item2a.add_data_source(data_item2)
        document_model.append_data_item(data_item2)  # add this first
        document_model.append_data_item(data_item2a)  # add this second
        # verify
        self.assertEqual(data_item2a.data_source, data_item2)
        # copy the dependent item
        data_item2a_copy = copy.deepcopy(data_item2a)
        document_model.append_data_item(data_item2a_copy)
        # verify data source
        self.assertEqual(data_item2a.data_source, data_item2)
        self.assertEqual(data_item2a_copy.data_source, data_item2)

    def test_copy_data_item_with_crop(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.set_property("bounds", ((0.25,0.25), (0.5,0.5)))
        data_item.add_operation(crop_operation)
        data_item_copy = copy.deepcopy(data_item)
        self.assertNotEqual(data_item_copy.operations[0], data_item.operations[0])
        self.assertEqual(data_item_copy.operations[0].get_property("bounds"), data_item.operations[0].get_property("bounds"))

    def test_copy_data_item_with_transaction(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.begin_transaction()
        with data_item.data_ref() as data_ref:
            data_ref.master_data[:] = 1
            data_item_copy = copy.deepcopy(data_item)
        data_item.end_transaction()
        with data_item.data_ref() as data_ref:
            with data_item_copy.data_ref() as data_copy_accessor:
                self.assertEqual(data_copy_accessor.master_data.shape, (256, 256))
                self.assertTrue(numpy.array_equal(data_ref.master_data, data_copy_accessor.master_data))
                data_ref.master_data[:] = 2
                self.assertFalse(numpy.array_equal(data_ref.master_data, data_copy_accessor.master_data))

    def test_clear_thumbnail_when_data_item_changed(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        display = data_item.displays[0]
        self.assertTrue(display.is_cached_value_dirty("thumbnail_data"))
        # configure a listener to know when the thumbnail is finished
        event = threading.Event()
        def thumbnail_loaded(thumbnail_data):
            event.set()
        # the next line also triggers the thumbnail calculation
        self.assertIsNotNone(display.get_processor("thumbnail").get_data(self.app.ui, completion_fn=thumbnail_loaded))
        # wait for the thumbnail
        event.wait()
        self.assertFalse(display.is_cached_value_dirty("thumbnail_data"))
        with data_item.data_ref() as data_ref:
            data_ref.master_data = numpy.zeros((256, 256), numpy.uint32)
        self.assertTrue(display.is_cached_value_dirty("thumbnail_data"))

    def test_thumbnail_1d(self):
        data_item = DataItem.DataItem(numpy.zeros((256), numpy.uint32))
        self.assertIsNotNone(data_item.displays[0].get_processor("thumbnail").get_data(self.app.ui))

    def test_delete_nested_data_item(self):
        document_model = DocumentModel.DocumentModel()
        # setup by adding data item and a dependent data item
        data_item2 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item2a = DataItem.DataItem()
        operation2a = Operation.OperationItem("resample-operation")
        data_item2a.add_operation(operation2a)
        data_item2a.add_data_source(data_item2)
        data_item2a1 = DataItem.DataItem()
        operation2a1 = Operation.OperationItem("resample-operation")
        data_item2a1.add_operation(operation2a1)
        data_item2a1.add_data_source(data_item2a)
        document_model.append_data_item(data_item2)  # add this first
        document_model.append_data_item(data_item2a)  # add this second
        document_model.append_data_item(data_item2a1)
        # verify
        self.assertEqual(len(document_model.data_items), 3)
        # remove item (and implicitly its dependency)
        document_model.remove_data_item(data_item2a)
        self.assertEqual(len(document_model.data_items), 1)

    def test_copy_data_item_with_display_and_graphics_should_copy_graphics(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        rect_graphic = Graphics.RectangleGraphic()
        data_item.displays[0].append_graphic(rect_graphic)
        self.assertEqual(len(data_item.displays[0].graphics), 1)
        data_item_copy = copy.deepcopy(data_item)
        self.assertEqual(len(data_item_copy.displays[0].graphics), 1)

    def test_data_item_data_changed(self):
        document_model = DocumentModel.DocumentModel()
        # set up the data items
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item_graphic = Graphics.LineGraphic()
        data_item.displays[0].append_graphic(data_item_graphic)
        document_model.append_data_item(data_item)
        data_item2 = DataItem.DataItem()
        data_item2.add_operation(Operation.OperationItem("fft-operation"))
        data_item2.add_data_source(data_item)
        document_model.append_data_item(data_item2)
        data_item3 = DataItem.DataItem()
        data_item3.add_operation(Operation.OperationItem("inverse-fft-operation"))
        data_item3.add_data_source(data_item2)
        document_model.append_data_item(data_item3)
        # establish listeners
        class Listener(object):
            def __init__(self):
                self.reset()
            def reset(self):
                self._data_changed = False
                self._display_changed = False
            def data_item_content_changed(self, data_item, changes):
                self._data_changed = self._data_changed or DataItem.DATA in changes
            def display_changed(self, display):
                self._display_changed = True
        listener = Listener()
        data_item.add_listener(listener)
        data_item.displays[0].add_listener(listener)
        listener2 = Listener()
        data_item2.add_listener(listener2)
        data_item2.displays[0].add_listener(listener2)
        listener3 = Listener()
        data_item3.add_listener(listener3)
        data_item3.displays[0].add_listener(listener3)
        listeners = (listener, listener2, listener3)
        # changing the master data of the source should trigger a data changed message
        # subsequently that should trigger a changed message for dependent items
        map(Listener.reset, listeners)
        with data_item.data_ref() as data_ref:
            data_ref.master_data = numpy.zeros((256, 256), numpy.uint32)
        self.assertTrue(listener._data_changed and listener._display_changed)
        self.assertTrue(listener2._data_changed and listener2._display_changed)
        self.assertTrue(listener3._data_changed and listener3._display_changed)
        # changing the param of the source should trigger a display changed message
        # but no data changed. nothing should change on the dependent items.
        map(Listener.reset, listeners)
        data_item.title = "new title"
        self.assertTrue(not listener._data_changed and listener._display_changed)
        self.assertTrue(not listener2._data_changed and not listener2._display_changed)
        self.assertTrue(not listener3._data_changed and not listener3._display_changed)
        # changing a graphic on source should NOT change dependent data
        # it should change the primary data item display, but not its data
        map(Listener.reset, listeners)
        data_item_graphic.start = (0.8, 0.2)
        self.assertTrue(not listener._data_changed)
        self.assertTrue(listener._display_changed)
        self.assertTrue(not listener._data_changed and listener._display_changed)
        self.assertTrue(not listener2._data_changed and not listener2._display_changed)
        self.assertTrue(not listener3._data_changed and not listener3._display_changed)
        # changing the display limit of source should NOT change dependent data
        map(Listener.reset, listeners)
        data_item.displays[0].display_limits = (0.1, 0.9)
        self.assertTrue(not listener._data_changed and listener._display_changed)
        self.assertTrue(not listener2._data_changed and not listener2._display_changed)
        self.assertTrue(not listener3._data_changed and not listener3._display_changed)
        # modify a calibration should NOT change dependent data, but should change dependent display
        map(Listener.reset, listeners)
        spatial_calibration_0 = data_item.intrinsic_calibrations[0]
        spatial_calibration_0.offset = 1.0
        data_item.set_spatial_calibration(0, spatial_calibration_0)
        self.assertTrue(not listener._data_changed and listener._display_changed)
        self.assertTrue(not listener2._data_changed and not listener2._display_changed)
        self.assertTrue(not listener3._data_changed and not listener3._display_changed)
        # add/remove an operation. should change primary and dependent data and display
        map(Listener.reset, listeners)
        invert_operation = Operation.OperationItem("invert-operation")
        data_item.add_operation(invert_operation)
        self.assertTrue(listener._data_changed and listener._display_changed)
        self.assertTrue(listener2._data_changed and listener2._display_changed)
        self.assertTrue(listener3._data_changed and listener3._display_changed)
        map(Listener.reset, listeners)
        data_item.remove_operation(invert_operation)
        self.assertTrue(listener._data_changed and listener._display_changed)
        self.assertTrue(listener2._data_changed and listener2._display_changed)
        self.assertTrue(listener3._data_changed and listener3._display_changed)
        # add/remove a data item should NOT change data or dependent data or display
        map(Listener.reset, listeners)
        data_item4 = DataItem.DataItem()
        data_item4.add_data_source(data_item)
        document_model.append_data_item(data_item4)
        self.assertTrue(not listener._data_changed and not listener._display_changed)
        self.assertTrue(not listener2._data_changed and not listener2._display_changed)
        self.assertTrue(not listener3._data_changed and not listener3._display_changed)
        map(Listener.reset, listeners)
        document_model.remove_data_item(data_item4)
        self.assertTrue(not listener._data_changed and not listener._display_changed)
        self.assertTrue(not listener2._data_changed and not listener2._display_changed)
        self.assertTrue(not listener3._data_changed and not listener3._display_changed)
        # modify an operation. make sure data and dependent data gets updated.
        blur_operation = Operation.OperationItem("gaussian-blur-operation")
        data_item.add_operation(blur_operation)
        map(Listener.reset, listeners)
        blur_operation.set_property("sigma", 0.1)
        self.assertTrue(listener._data_changed and listener._display_changed)
        self.assertTrue(listener2._data_changed and listener2._display_changed)
        self.assertTrue(listener3._data_changed and listener3._display_changed)
        data_item.remove_operation(blur_operation)
        # modify an operation graphic. make sure data and dependent data gets updated.
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.set_property("bounds", ((0.25,0.25), (0.5,0.5)))
        data_item.add_operation(crop_operation)
        map(Listener.reset, listeners)
        crop_operation.set_property("bounds", ((0,0), (0.5, 0.5)))
        self.assertTrue(listener._data_changed and listener._display_changed)
        self.assertTrue(listener2._data_changed and listener2._display_changed)
        self.assertTrue(listener3._data_changed and listener3._display_changed)
        data_item.remove_operation(crop_operation)

    def test_data_range(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        # test scalar
        xx, yy = numpy.meshgrid(numpy.linspace(0,1,256), numpy.linspace(0,1,256))
        with data_item.data_ref() as data_ref:
            data_ref.master_data = 50 * (xx + yy) + 25
            data_ref.data  # TODO: this should not be required
            data_range = data_item.data_range
            self.assertEqual(data_range, (25, 125))
            # now test complex
            data_ref.master_data = numpy.zeros((256, 256), numpy.complex64)
            xx, yy = numpy.meshgrid(numpy.linspace(0,1,256), numpy.linspace(0,1,256))
            data_ref.master_data = (2 + xx * 10) + 1j * (3 + yy * 10)
            data_ref.data  # TODO: this should not be required
        data_range = data_item.data_range
        data_min = math.log(math.sqrt(2*2 + 3*3) + 1)
        data_max = math.log(math.sqrt(12*12 + 13*13) + 1)
        self.assertEqual(int(data_min*1e6), int(data_range[0]*1e6))
        self.assertEqual(int(data_max*1e6), int(data_range[1]*1e6))

    def test_removing_dependent_data_item_with_graphic(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        crop_data_item = DataItem.DataItem()
        crop_operation = Operation.OperationItem("crop-operation")
        crop_data_item.add_operation(crop_operation)
        crop_data_item.add_data_source(data_item)
        document_model.append_data_item(crop_data_item)
        # should remove properly when shutting down.

    def test_inherited_session_id_during_processing(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.session_id = "20131231-235959"
        document_model.append_data_item(data_item)
        crop_data_item = DataItem.DataItem()
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.set_property("bounds", ((0.25,0.25), (0.5,0.5)))
        crop_data_item.add_operation(crop_operation)
        crop_data_item.add_data_source(data_item)
        document_model.append_data_item(crop_data_item)
        self.assertEqual(crop_data_item.session_id, data_item.session_id)

    def test_adding_ref_to_dependent_data_causes_source_data_to_load(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        data_item_inverted.add_operation(Operation.OperationItem("invert-operation"))
        data_item_inverted.add_data_source(data_item)
        document_model.append_data_item(data_item_inverted)
        # begin checks
        with data_item.data_ref():
            pass
        self.assertFalse(data_item.is_data_loaded)
        with data_item_inverted.data_ref() as d:
            self.assertTrue(data_item.is_data_loaded)
        self.assertFalse(data_item.is_data_loaded)

    class DummyOperation(Operation.Operation):
        def __init__(self):
            description = [ { "name": "Param", "property": "param", "type": "scalar", "default": 0.0 } ]
            super(TestDataItemClass.DummyOperation, self).__init__("Dummy", "dummy-operation", description)
            self.count = 0
        def process(self, data):
            self.count += 1
            return numpy.zeros((16, 16))

    def test_operation_data_gets_cached(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item_dummy = DataItem.DataItem()
        dummy_operation = TestDataItemClass.DummyOperation()
        Operation.OperationManager().register_operation("dummy-operation", lambda: dummy_operation)
        dummy_operation_item = Operation.OperationItem("dummy-operation")
        data_item_dummy.add_operation(dummy_operation_item)
        data_item_dummy.add_data_source(data_item)
        document_model.append_data_item(data_item_dummy)
        with data_item_dummy.data_ref() as d:
            start_count = dummy_operation.count
            d.data
            self.assertEqual(dummy_operation.count, start_count + 1)
            d.data
            self.assertEqual(dummy_operation.count, start_count + 1)

    def test_updating_thumbnail_does_not_cause_cached_data_to_be_cleared(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item_dummy = DataItem.DataItem()
        dummy_operation = TestDataItemClass.DummyOperation()
        Operation.OperationManager().register_operation("dummy-operation", lambda: dummy_operation)
        dummy_operation_item = Operation.OperationItem("dummy-operation")
        data_item_dummy.add_operation(dummy_operation_item)
        data_item_dummy.add_data_source(data_item)
        document_model.append_data_item(data_item_dummy)
        with data_item_dummy.data_ref() as d:
            start_count = dummy_operation.count
            d.data
            self.assertEqual(dummy_operation.count, start_count + 1)
            data_item_dummy.notify_data_item_content_changed([])  # NOTE: this test may no longer be valid
            d.data
            self.assertEqual(dummy_operation.count, start_count + 1)

    def test_adding_removing_data_item_with_crop_operation_updates_drawn_graphics(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 0)
        data_item_crop = DataItem.DataItem()
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.set_property("bounds", ((0.25, 0.25), (0.5, 0.5)))
        crop_operation.establish_associated_region("crop", data_item, Region.RectRegion())
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 1)
        data_item_crop.add_operation(crop_operation)
        data_item_crop.add_data_source(data_item)
        document_model.append_data_item(data_item_crop)
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 1)
        document_model.remove_data_item(data_item_crop)
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 0)

    def test_adding_removing_crop_operation_to_existing_data_item_updates_drawn_graphics(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 0)
        data_item_crop = DataItem.DataItem()
        data_item_crop.add_data_source(data_item)
        document_model.append_data_item(data_item_crop)
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.set_property("bounds", ((0.25, 0.25), (0.5, 0.5)))
        crop_operation.establish_associated_region("crop", data_item, Region.RectRegion())
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 1)
        data_item_crop.add_operation(crop_operation)
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 1)
        data_item_crop.remove_operation(crop_operation)
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 0)

    def test_updating_operation_graphic_property_notifies_data_item(self):
        # data_item_content_changed
        class Listener(object):
            def __init__(self):
                self.reset()
            def reset(self):
                self._display_changed = False
            def display_changed(self, display):
                self._display_changed = True
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        listener = Listener()
        data_item.displays[0].add_listener(listener)
        data_item_crop = DataItem.DataItem()
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.set_property("bounds", ((0.25, 0.25), (0.5, 0.5)))
        crop_operation.establish_associated_region("crop", data_item, Region.RectRegion())
        data_item_crop.add_operation(crop_operation)
        data_item_crop.add_data_source(data_item)
        document_model.append_data_item(data_item_crop)
        listener.reset()
        data_item.displays[0].drawn_graphics[0].bounds = ((0.2,0.3), (0.8,0.7))
        self.assertTrue(listener._display_changed)

    # necessary to make inspector display updated values properly
    def test_updating_operation_graphic_property_with_same_value_notifies_data_item(self):
        # data_item_content_changed
        class Listener(object):
            def __init__(self):
                self.reset()
            def reset(self):
                self._display_changed = False
            def display_changed(self, display):
                self._display_changed = True
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        listener = Listener()
        data_item.displays[0].add_listener(listener)
        data_item_crop = DataItem.DataItem()
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.set_property("bounds", ((0.25, 0.25), (0.5, 0.5)))
        crop_operation.establish_associated_region("crop", data_item, Region.RectRegion())
        data_item_crop.add_operation(crop_operation)
        data_item_crop.add_data_source(data_item)
        document_model.append_data_item(data_item_crop)
        data_item.displays[0].drawn_graphics[0].bounds = ((0.2,0.3), (0.8,0.7))
        listener.reset()
        data_item.displays[0].drawn_graphics[0].bounds = ((0.2,0.3), (0.8,0.7))
        self.assertTrue(listener._display_changed)

    def test_updating_region_bounds_updates_crop_graphic(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item_crop = DataItem.DataItem()
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.set_property("bounds", ((0.25, 0.25), (0.5, 0.5)))
        crop_region = Region.RectRegion()
        crop_operation.establish_associated_region("crop", data_item, crop_region)
        data_item_crop.add_operation(crop_operation)
        data_item_crop.add_data_source(data_item)
        document_model.append_data_item(data_item_crop)
        # verify assumptions
        self.assertEqual(crop_operation.get_property("bounds"), ((0.25, 0.25), (0.5, 0.5)))
        # operation should now match the region
        self.assertEqual(crop_region.center, (0.5, 0.5))
        self.assertEqual(crop_region.size, (0.5, 0.5))
        # make change and verify it changed
        crop_region.center = 0.6, 0.6
        bounds = crop_operation.get_property("bounds")
        self.assertAlmostEqual(bounds[0][0], 0.35)
        self.assertAlmostEqual(bounds[0][1], 0.35)
        self.assertAlmostEqual(bounds[1][0], 0.5)
        self.assertAlmostEqual(bounds[1][1], 0.5)

    def test_snapshot_should_copy_raw_metadata(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        with data_item.open_metadata("test") as metadata:
            metadata["one"] = 1
        data_item_copy = data_item.snapshot()
        self.assertEqual(data_item_copy.get_metadata("test")["one"], 1)

    def test_data_item_allows_adding_of_two_data_sources(self):
        document_model = DocumentModel.DocumentModel()
        data_item1 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item1)
        data_item2 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item2)
        data_item = DataItem.DataItem()
        data_item.add_data_source(data_item1)
        data_item.add_data_source(data_item2)
        document_model.append_data_item(data_item)

    def test_data_item_allows_remove_second_of_two_data_sources(self):
        document_model = DocumentModel.DocumentModel()
        data_item1 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item1)
        data_item2 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item2)
        data_item = DataItem.DataItem()
        data_item.add_data_source(data_item1)
        data_item.add_data_source(data_item2)
        document_model.append_data_item(data_item)
        data_item.remove_data_source(data_item2)

    def test_region_graphic_gets_added_to_existing_display(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 0)
        data_item.add_region(Region.PointRegion())
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 1)

    def test_region_graphic_gets_added_to_new_display(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item.add_region(Region.PointRegion())
        data_item.add_display(Display.Display())
        self.assertEqual(len(data_item.displays[1].drawn_graphics), 1)

    # necessary to make inspector display updated values properly
    def test_adding_region_generates_display_changed(self):
        # data_item_content_changed
        class Listener(object):
            def __init__(self):
                self.reset()
            def reset(self):
                self._display_changed = False
            def display_changed(self, display):
                self._display_changed = True
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        listener = Listener()
        data_item.displays[0].add_listener(listener)
        crop_region = Region.RectRegion()
        data_item.add_region(crop_region)
        self.assertTrue(listener._display_changed)
        listener.reset()
        data_item.remove_region(crop_region)
        self.assertTrue(listener._display_changed)

    def test_data_source_connects_if_added_after_data_item_is_already_in_document(self):
        document_model = DocumentModel.DocumentModel()
        # configure the source item
        data_item = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        document_model.append_data_item(data_item)
        # configure the dependent item
        data_item2 = DataItem.DataItem()
        document_model.append_data_item(data_item2)
        # add data source AFTER data_item2 is in library
        data_item2.add_data_source(data_item)
        # see if the data source got connected
        self.assertIsNotNone(data_item2.data)
        self.assertIsNotNone(data_item2.data_source)



if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
