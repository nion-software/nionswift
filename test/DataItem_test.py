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
        data_item.set_dimensional_calibration(0, Calibration.Calibration(3.0, 2.0, u"x"))
        data_item.set_dimensional_calibration(1, Calibration.Calibration(3.0, 2.0, u"x"))
        self.assertEqual(len(data_item.dimensional_calibrations), 2)
        data_item_copy = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_copy.set_operation(invert_operation)
        dimensional_calibrations = data_item_copy.dimensional_calibrations
        self.assertEqual(len(dimensional_calibrations), 2)
        self.assertEqual(int(dimensional_calibrations[0].offset), 3)
        self.assertEqual(int(dimensional_calibrations[0].scale), 2)
        self.assertEqual(dimensional_calibrations[0].units, "x")
        self.assertEqual(int(dimensional_calibrations[1].offset), 3)
        self.assertEqual(int(dimensional_calibrations[1].scale), 2)
        self.assertEqual(dimensional_calibrations[1].units, "x")
        fft_operation = Operation.OperationItem("fft-operation")
        fft_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_copy.set_operation(fft_operation)
        dimensional_calibrations = data_item_copy.dimensional_calibrations
        self.assertEqual(int(dimensional_calibrations[0].offset), 0)
        self.assertEqual(dimensional_calibrations[0].units, "1/x")
        self.assertEqual(int(dimensional_calibrations[1].offset), 0)
        self.assertEqual(dimensional_calibrations[1].units, "1/x")

    def test_double_dependent_calibration(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item2 = DataItem.DataItem()
        operation2 = Operation.OperationItem("resample-operation")
        operation2.add_data_source(Operation.DataItemDataSource(data_item))
        data_item2.set_operation(operation2)
        data_item3 = DataItem.DataItem()
        operation3 = Operation.OperationItem("resample-operation")
        operation3.add_data_source(Operation.DataItemDataSource(data_item2))
        data_item3.set_operation(operation3)
        data_item3.dimensional_calibrations

    def test_spatial_calibration_on_rgb(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256, 4), numpy.uint8))
        self.assertTrue(Image.is_shape_and_dtype_2d(*data_item.data_shape_and_dtype))
        self.assertTrue(Image.is_shape_and_dtype_rgba(*data_item.data_shape_and_dtype))
        self.assertEqual(len(data_item.dimensional_calibrations), 2)

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
        source_data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.title = "data_item"
        with data_item.open_metadata("test") as metadata:
            metadata["one"] = 1
            metadata["two"] = 22
        with data_item.data_ref() as data_ref:
            data_ref.master_data[128, 128] = 1000  # data range (0, 1000)
            data_ref.master_data_updated()
        data_item.displays[0].display_limits = (100, 900)
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(source_data_item))
        data_item.set_operation(invert_operation)
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
        self.assertEqual(data_item.operation.operation_id, data_item_copy.operation.operation_id)
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
        self.assertNotEqual(data_item.dimensional_calibrations[0], data_item_copy.dimensional_calibrations[0])
        self.assertNotEqual(data_item.operation, data_item_copy.operation)
        self.assertNotEqual(data_item.displays[0].graphics[0], data_item_copy.displays[0].graphics[0])

    def test_copy_data_item_properly_copies_data_source_and_connects_it(self):
        document_model = DocumentModel.DocumentModel()
        # setup by adding data item and a dependent data item
        data_item2 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item2a = DataItem.DataItem()
        operation2a = Operation.OperationItem("resample-operation")
        operation2a.add_data_source(Operation.DataItemDataSource(data_item2))
        data_item2a.set_operation(operation2a)
        document_model.append_data_item(data_item2)  # add this first
        document_model.append_data_item(data_item2a)  # add this second
        # verify
        self.assertEqual(data_item2a.operation.data_sources[0].data_item, data_item2)
        # copy the dependent item
        data_item2a_copy = copy.deepcopy(data_item2a)
        document_model.append_data_item(data_item2a_copy)
        # verify data source
        self.assertEqual(data_item2a.operation.data_sources[0].data_item, data_item2)
        self.assertEqual(data_item2a_copy.operation.data_sources[0].data_item, data_item2)

    def test_copy_data_item_with_crop(self):
        source_data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.set_property("bounds", ((0.25,0.25), (0.5,0.5)))
        crop_operation.add_data_source(Operation.DataItemDataSource(source_data_item))
        data_item.set_operation(crop_operation)
        data_item_copy = copy.deepcopy(data_item)
        self.assertNotEqual(data_item_copy.operation, data_item.operation)
        self.assertEqual(data_item_copy.operation.get_property("bounds"), data_item.operation.get_property("bounds"))

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
        display.get_processor("thumbnail").recompute_data(self.app.ui)
        self.assertIsNotNone(display.get_processed_data("thumbnail"))
        self.assertFalse(display.is_cached_value_dirty("thumbnail_data"))
        with data_item.data_ref() as data_ref:
            data_ref.master_data = numpy.zeros((256, 256), numpy.uint32)
        self.assertTrue(display.is_cached_value_dirty("thumbnail_data"))

    def test_thumbnail_1d(self):
        data_item = DataItem.DataItem(numpy.zeros((256), numpy.uint32))
        self.assertIsNotNone(data_item.displays[0].get_processed_data("thumbnail"))

    def test_thumbnail_marked_dirty_when_source_data_changed(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.double))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted.recompute_data()
        data_item_inverted_display = data_item_inverted.displays[0]
        data_item_inverted_display.get_processor("thumbnail").recompute_data(self.app.ui)
        data_item_inverted_display.get_processed_data("thumbnail")
        # here the data should be computed and the thumbnail should not be dirty
        self.assertFalse(data_item_inverted_display.is_cached_value_dirty("thumbnail_data"))
        # now the source data changes and the inverted data needs computing.
        # the thumbnail should also be dirty.
        with data_item.data_ref() as data_ref:
            data_ref.master_data = data_ref.master_data + 1.0
        self.assertTrue(data_item_inverted_display.is_cached_value_dirty("thumbnail_data"))

    def test_delete_nested_data_item(self):
        document_model = DocumentModel.DocumentModel()
        # setup by adding data item and a dependent data item
        data_item2 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item2a = DataItem.DataItem()
        operation2a = Operation.OperationItem("resample-operation")
        operation2a.add_data_source(Operation.DataItemDataSource(data_item2))
        data_item2a.set_operation(operation2a)
        data_item2a1 = DataItem.DataItem()
        operation2a1 = Operation.OperationItem("resample-operation")
        operation2a1.add_data_source(Operation.DataItemDataSource(data_item2a))
        data_item2a1.set_operation(operation2a1)
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
        # TODO: split this large monolithic test into smaller parts (some done already)
        document_model = DocumentModel.DocumentModel()
        # set up the data items
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item_graphic = Graphics.LineGraphic()
        data_item.displays[0].append_graphic(data_item_graphic)
        document_model.append_data_item(data_item)
        data_item2 = DataItem.DataItem()
        fft_operation = Operation.OperationItem("fft-operation")
        fft_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item2.set_operation(fft_operation)
        document_model.append_data_item(data_item2)
        data_item3 = DataItem.DataItem()
        ifft_operation = Operation.OperationItem("inverse-fft-operation")
        ifft_operation.add_data_source(Operation.DataItemDataSource(data_item2))
        data_item3.set_operation(ifft_operation)
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
        document_model.recompute_all()
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
        spatial_calibration_0 = data_item.dimensional_calibrations[0]
        spatial_calibration_0.offset = 1.0
        data_item.set_dimensional_calibration(0, spatial_calibration_0)
        self.assertTrue(not listener._data_changed and listener._display_changed)
        self.assertTrue(not listener2._data_changed and not listener2._display_changed)
        self.assertTrue(not listener3._data_changed and not listener3._display_changed)
        # add/remove an operation. should change primary and dependent data and display
        map(Listener.reset, listeners)
        source_data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(source_data_item)
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(source_data_item))
        data_item.set_operation(invert_operation)
        document_model.recompute_all()
        self.assertTrue(listener._data_changed and listener._display_changed)
        self.assertTrue(listener2._data_changed and listener2._display_changed)
        self.assertTrue(listener3._data_changed and listener3._display_changed)
        map(Listener.reset, listeners)
        data_item.set_operation(None)
        document_model.recompute_all()
        self.assertTrue(listener._data_changed and listener._display_changed)
        self.assertTrue(listener2._data_changed and listener2._display_changed)
        self.assertTrue(listener3._data_changed and listener3._display_changed)
        # add/remove a data item should NOT change data or dependent data or display
        map(Listener.reset, listeners)
        data_item4 = DataItem.DataItem()
        invert_operation4 = Operation.OperationItem("invert-operation")
        invert_operation4.add_data_source(Operation.DataItemDataSource(data_item))
        data_item4.set_operation(invert_operation4)
        document_model.append_data_item(data_item4)
        self.assertTrue(not listener._data_changed and not listener._display_changed)
        self.assertTrue(not listener2._data_changed and not listener2._display_changed)
        self.assertTrue(not listener3._data_changed and not listener3._display_changed)
        map(Listener.reset, listeners)
        document_model.remove_data_item(data_item4)
        self.assertTrue(not listener._data_changed and not listener._display_changed)
        self.assertTrue(not listener2._data_changed and not listener2._display_changed)
        self.assertTrue(not listener3._data_changed and not listener3._display_changed)

    def test_appending_data_item_should_trigger_recompute(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        invert_data_item = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        invert_data_item.set_operation(invert_operation)
        document_model.append_data_item(invert_data_item)
        document_model.recompute_all()
        self.assertFalse(invert_data_item.is_data_stale)

    def test_data_range(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        # test scalar
        xx, yy = numpy.meshgrid(numpy.linspace(0,1,256), numpy.linspace(0,1,256))
        with data_item.data_ref() as data_ref:
            data_ref.master_data = 50 * (xx + yy) + 25
            data_range = data_item.data_range
            self.assertEqual(data_range, (25, 125))
            # now test complex
            data_ref.master_data = numpy.zeros((256, 256), numpy.complex64)
            xx, yy = numpy.meshgrid(numpy.linspace(0,1,256), numpy.linspace(0,1,256))
            data_ref.master_data = (2 + xx * 10) + 1j * (3 + yy * 10)
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
        crop_operation.add_data_source(Operation.DataItemDataSource(data_item))
        crop_data_item.set_operation(crop_operation)
        document_model.append_data_item(crop_data_item)
        # should remove properly when shutting down.

    def test_recomputing_data_should_not_leave_it_loaded(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted.recompute_data()
        self.assertFalse(data_item_inverted.is_data_loaded)

    def test_loading_dependent_data_should_not_cause_source_data_to_load(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        # begin checks
        data_item_inverted.recompute_data()
        self.assertFalse(data_item.is_data_loaded)
        with data_item_inverted.data_ref() as d:
            self.assertFalse(data_item.is_data_loaded)
        self.assertFalse(data_item.is_data_loaded)

    def test_modifying_source_data_should_not_trigger_data_changed_notification_from_dependent_data(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted.recompute_data()
        class Listener(object):
            def __init__(self):
                self.data_changed = False
            def data_item_content_changed(self, data_item, changes):
                self.data_changed = self.data_changed or DataItem.DATA in changes
        listener = Listener()
        data_item_inverted.add_listener(listener)
        with data_item.data_ref() as data_ref:
            data_ref.master_data = numpy.ones((256, 256), numpy.uint32)
        self.assertFalse(listener.data_changed)

    def test_modifying_source_data_should_trigger_data_item_stale_from_dependent_data_item(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted.recompute_data()
        class Listener(object):
            def __init__(self):
                self.needs_recompute = False
            def data_item_needs_recompute(self, data_item):
                self.needs_recompute = True
        listener = Listener()
        data_item_inverted.add_listener(listener)
        with data_item.data_ref() as data_ref:
            data_ref.master_data = numpy.ones((256, 256), numpy.uint32)
        self.assertTrue(listener.needs_recompute)

    def test_modifying_source_data_should_queue_recompute_in_document_model(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted.recompute_data()
        with data_item.data_ref() as data_ref:
            data_ref.master_data = numpy.ones((256, 256), numpy.uint32)
        self.assertTrue(data_item_inverted.is_data_stale)
        document_model.recompute_all()
        self.assertFalse(data_item_inverted.is_data_stale)

    def test_is_data_stale_should_propagate_to_data_items_dependent_on_source(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted2 = DataItem.DataItem()
        invert_operation2 = Operation.OperationItem("invert-operation")
        invert_operation2.add_data_source(Operation.DataItemDataSource(data_item_inverted))
        data_item_inverted2.set_operation(invert_operation2)
        document_model.append_data_item(data_item_inverted2)
        data_item_inverted2.recompute_data()
        with data_item.data_ref() as data_ref:
            data_ref.master_data = numpy.ones((256, 256), numpy.uint32)
        self.assertTrue(data_item_inverted.is_data_stale)
        self.assertTrue(data_item_inverted2.is_data_stale)

    def test_data_item_that_is_recomputed_notifies_listeners_of_a_single_data_change(self):
        # this test ensures that doing a recompute_data is efficient and doesn't produce
        # extra data_item_content_changed messages.
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        class Listener(object):
            def __init__(self):
                self.data_changed = 0
            def data_item_content_changed(self, data_item, changes):
                if DataItem.DATA in changes:
                    self.data_changed += 1
        listener = Listener()
        data_item_inverted.add_listener(listener)
        with data_item.data_ref() as data_ref:
            data_ref.master_data = numpy.ones((256, 256), numpy.uint32)
        self.assertTrue(data_item_inverted.is_data_stale)
        self.assertEqual(listener.data_changed, 0)
        data_item_inverted.recompute_data()
        self.assertFalse(data_item_inverted.is_data_stale)
        self.assertEqual(listener.data_changed, 1)

    class DummyOperation(Operation.Operation):
        def __init__(self):
            description = [ { "name": "Param", "property": "param", "type": "scalar", "default": 0.0 } ]
            super(TestDataItemClass.DummyOperation, self).__init__("Dummy", "dummy-operation", description)
            self.count = 0
        def get_processed_data(self, data_sources):
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
        dummy_operation_item.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_dummy.set_operation(dummy_operation_item)
        document_model.append_data_item(data_item_dummy)
        document_model.sync_data_item(data_item_dummy)
        with data_item_dummy.data_ref() as d:
            start_count = dummy_operation.count
            d.data
            self.assertEqual(dummy_operation.count, start_count)
            d.data
            self.assertEqual(dummy_operation.count, start_count)

    class SumOperation(Operation.Operation):

        def __init__(self):
            super(TestDataItemClass.SumOperation, self).__init__("Add2", "add2-operation")

        def get_processed_data(self, data_sources):
            result = None
            for data_item in data_sources:
                if result is None:
                    result = data_item.data
                else:
                    result += data_item.data
            return result

    def test_operation_with_multiple_data_sources_is_allowed(self):
        document_model = DocumentModel.DocumentModel()
        data_item1 = DataItem.DataItem(numpy.ones((256, 256), numpy.uint32))
        data_item2 = DataItem.DataItem(numpy.ones((256, 256), numpy.uint32))
        data_item3 = DataItem.DataItem(numpy.ones((256, 256), numpy.uint32))
        document_model.append_data_item(data_item1)
        document_model.append_data_item(data_item2)
        document_model.append_data_item(data_item3)
        data_item_sum = DataItem.DataItem()
        sum_operation = TestDataItemClass.SumOperation()
        Operation.OperationManager().register_operation("sum-operation", lambda: sum_operation)
        sum_operation_item = Operation.OperationItem("sum-operation")
        sum_operation_item.add_data_source(Operation.DataItemDataSource(data_item1))
        sum_operation_item.add_data_source(Operation.DataItemDataSource(data_item2))
        sum_operation_item.add_data_source(Operation.DataItemDataSource(data_item3))
        data_item_sum.set_operation(sum_operation_item)
        document_model.append_data_item(data_item_sum)
        summed_data = data_item_sum.data
        self.assertEqual(summed_data[0, 0], 3)

    def test_adding_removing_data_item_with_crop_operation_updates_drawn_graphics(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 0)
        data_item_crop = DataItem.DataItem()
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.set_property("bounds", ((0.25, 0.25), (0.5, 0.5)))
        crop_operation.establish_associated_region("crop", data_item)
        crop_operation.add_data_source(Operation.DataItemDataSource(data_item))
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 1)
        data_item_crop.set_operation(crop_operation)
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
        document_model.append_data_item(data_item_crop)
        crop_operation = Operation.OperationItem("crop-operation")
        crop_operation.set_property("bounds", ((0.25, 0.25), (0.5, 0.5)))
        crop_operation.establish_associated_region("crop", data_item)
        crop_operation.add_data_source(Operation.DataItemDataSource(data_item))
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 1)
        data_item_crop.set_operation(crop_operation)
        self.assertEqual(len(data_item.displays[0].drawn_graphics), 1)
        data_item_crop.set_operation(None)
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
        crop_operation.establish_associated_region("crop", data_item)
        crop_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_crop.set_operation(crop_operation)
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
        crop_operation.establish_associated_region("crop", data_item)
        crop_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_crop.set_operation(crop_operation)
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
        data_item.add_region(crop_region)
        crop_operation.establish_associated_region("crop", data_item, crop_region)
        crop_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_crop.set_operation(crop_operation)
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
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item1))
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item2))
        data_item.set_operation(invert_operation)
        document_model.append_data_item(data_item)

    def test_data_item_allows_remove_second_of_two_data_sources(self):
        # two data sources are not currently supported
        document_model = DocumentModel.DocumentModel()
        data_item1 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item1)
        data_item2 = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item2)
        data_item = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item1))
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item2))
        data_item.set_operation(invert_operation)
        document_model.append_data_item(data_item)
        invert_operation.remove_data_source(invert_operation.data_sources[1])

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
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item2.set_operation(invert_operation)
        # see if the data source got connected
        self.assertIsNotNone(data_item2.data)
        self.assertEqual(data_item2.operation.data_sources[0].data_item, data_item)

    def test_connecting_data_source_updates_dependent_data_items_property_on_source(self):
        document_model = DocumentModel.DocumentModel()
        # configure the source item
        data_item = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        document_model.append_data_item(data_item)
        # configure the dependent item
        data_item2 = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item2.set_operation(invert_operation)
        document_model.append_data_item(data_item2)
        # make sure the dependency list is updated
        self.assertEqual(data_item.dependent_data_items, [data_item2])

    def test_begin_transaction_also_begins_transaction_for_dependent_data_item(self):
        document_model = DocumentModel.DocumentModel()
        # configure the source item
        data_item = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        document_model.append_data_item(data_item)
        # configure the dependent item
        data_item2 = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item2.set_operation(invert_operation)
        document_model.append_data_item(data_item2)
        # begin the transaction
        with data_item.transaction():
            self.assertTrue(data_item.transaction_count > 0)
            self.assertTrue(data_item2.transaction_count > 0)
        self.assertEqual(data_item.transaction_count, 0)
        self.assertEqual(data_item2.transaction_count, 0)

    def test_data_item_added_to_data_item_under_transaction_becomes_transacted_too(self):
        document_model = DocumentModel.DocumentModel()
        # configure the source item
        data_item = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        document_model.append_data_item(data_item)
        # begin the transaction
        with data_item.transaction():
            # configure the dependent item
            data_item2 = DataItem.DataItem()
            invert_operation = Operation.OperationItem("invert-operation")
            invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
            data_item2.set_operation(invert_operation)
            document_model.append_data_item(data_item2)
            # check to make sure it is under transaction
            self.assertTrue(data_item.transaction_count > 0)
            self.assertTrue(data_item2.transaction_count > 0)
        self.assertEqual(data_item.transaction_count, 0)
        self.assertEqual(data_item2.transaction_count, 0)

    def test_data_item_added_to_data_item_under_transaction_configures_dependency(self):
        document_model = DocumentModel.DocumentModel()
        # configure the source item
        data_item = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        document_model.append_data_item(data_item)
        # begin the transaction
        with data_item.transaction():
            data_item_crop1 = DataItem.DataItem()
            crop_operation = Operation.OperationItem("crop-operation")
            crop_operation.set_property("bounds", ((0.25, 0.25), (0.5, 0.5)))
            crop_region = Region.RectRegion()
            crop_operation.establish_associated_region("crop", data_item)
            crop_operation.add_data_source(Operation.DataItemDataSource(data_item))
            data_item_crop1.set_operation(crop_operation)
            document_model.append_data_item(data_item_crop1)
            # change the bounds of the graphic
            data_item.displays[0].drawn_graphics[0].bounds = ((0.31, 0.32), (0.6, 0.4))
            # make sure it is connected to the crop operation
            bounds = crop_operation.get_property("bounds")
            self.assertAlmostEqual(bounds[0][0], 0.31)
            self.assertAlmostEqual(bounds[0][1], 0.32)
            self.assertAlmostEqual(bounds[1][0], 0.6)
            self.assertAlmostEqual(bounds[1][1], 0.4)

    def test_data_item_under_transaction_added_to_document_does_write_delay(self):
        document_model = DocumentModel.DocumentModel()
        # configure the source item
        data_item = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        # begin the transaction
        with data_item.transaction():
            document_model.append_data_item(data_item)
            persistent_storage = data_item.managed_object_context.get_persistent_storage_for_object(data_item)
            self.assertTrue(persistent_storage.write_delayed)

    def test_data_item_added_to_live_data_item_becomes_live_and_unlive_based_on_parent_item(self):
        document_model = DocumentModel.DocumentModel()
        # configure the source item
        data_item = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        document_model.append_data_item(data_item)
        with data_item.live():
            data_item_crop1 = DataItem.DataItem()
            crop_operation = Operation.OperationItem("crop-operation")
            crop_operation.set_property("bounds", ((0.25, 0.25), (0.5, 0.5)))
            crop_region = Region.RectRegion()
            crop_operation.establish_associated_region("crop", data_item, crop_region)
            crop_operation.add_data_source(Operation.DataItemDataSource(data_item))
            data_item_crop1.set_operation(crop_operation)
            document_model.append_data_item(data_item_crop1)
            self.assertTrue(data_item_crop1.is_live)
        self.assertFalse(data_item.is_live)
        self.assertFalse(data_item_crop1.is_live)

    def test_data_item_removed_from_live_data_item_becomes_unlive(self):
        document_model = DocumentModel.DocumentModel()
        # configure the source item
        data_item = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        document_model.append_data_item(data_item)
        data_item_crop1 = DataItem.DataItem()
        sum_operation = TestDataItemClass.SumOperation()
        Operation.OperationManager().register_operation("sum-operation", lambda: sum_operation)
        sum_operation_item = Operation.OperationItem("sum-operation")
        sum_operation_item.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_crop1.set_operation(sum_operation_item)
        document_model.append_data_item(data_item_crop1)
        with data_item.live():
            # check assumptions
            self.assertTrue(data_item.is_live)
            self.assertTrue(data_item_crop1.is_live)
            sum_operation_item.remove_data_source(sum_operation_item.data_sources[0])
            self.assertFalse(data_item_crop1.is_live)
        self.assertFalse(data_item.is_live)
        self.assertFalse(data_item_crop1.is_live)

    def test_changing_metadata_or_data_does_not_mark_the_data_as_stale(self):
        # changing metadata or data will override what has been computed
        # from the data sources, if there are any.
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        document_model.append_data_item(data_item)
        self.assertFalse(data_item.is_data_stale)
        with data_item.data_ref() as data_ref:
            data_ref.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_item.set_intensity_calibration(Calibration.Calibration())
        self.assertFalse(data_item.is_data_stale)

    def test_changing_metadata_or_data_does_not_mark_the_data_as_stale_for_data_item_with_data_source(self):
        # changing metadata or data will override what has been computed
        # from the data sources, if there are any.
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        document_model.append_data_item(data_item)
        data_item_copy = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_copy.set_operation(invert_operation)
        document_model.append_data_item(data_item_copy)
        data_item_copy.recompute_data()
        self.assertFalse(data_item_copy.is_data_stale)
        data_item_copy.set_intensity_calibration(Calibration.Calibration())
        self.assertFalse(data_item_copy.is_data_stale)

    def test_adding_or_removing_operation_should_mark_the_data_as_stale(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        document_model.append_data_item(data_item)
        data_item_copy = DataItem.DataItem()
        blur_operation = Operation.OperationItem("gaussian-blur-operation")
        blur_operation.add_data_source(Operation.DataItemDataSource(data_item))
        document_model.append_data_item(data_item_copy)
        data_item_copy.recompute_data()
        self.assertFalse(data_item_copy.is_data_stale)
        data_item_copy.set_operation(blur_operation)
        self.assertTrue(data_item_copy.is_data_stale)
        data_item_copy.recompute_data()
        self.assertFalse(data_item_copy.is_data_stale)
        data_item_copy.set_operation(None)
        self.assertTrue(data_item_copy.is_data_stale)

    def test_changing_operation_should_mark_the_data_as_stale(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((2000,1000), numpy.double))
        document_model.append_data_item(data_item)
        data_item_copy = DataItem.DataItem()
        blur_operation = Operation.OperationItem("gaussian-blur-operation")
        blur_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_copy.set_operation(blur_operation)
        document_model.append_data_item(data_item_copy)
        data_item_copy.recompute_data()
        self.assertFalse(data_item_copy.is_data_stale)
        blur_operation.set_property("sigma", 0.1)
        self.assertTrue(data_item_copy.is_data_stale)

    def test_reloading_stale_data_should_still_be_stale(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted.recompute_data()
        self.assertFalse(data_item_inverted.is_data_stale)
        self.assertAlmostEqual(data_item_inverted.cached_data[0, 0], -1.0)
        # now the source data changes and the inverted data needs computing.
        with data_item.data_ref() as data_ref:
            data_ref.master_data = data_ref.master_data + 2.0
        self.assertTrue(data_item_inverted.is_data_stale)
        # data is now unloaded and stale.
        self.assertFalse(data_item_inverted.is_data_loaded)
        self.assertTrue(data_item_inverted.is_data_stale)
        # force the data to reload, but don't recompute, by using cached_data
        self.assertAlmostEqual(data_item_inverted.cached_data[0, 0], -1.0)
        # data should still be stale
        self.assertTrue(data_item_inverted.is_data_stale)

    def test_recomputing_data_gives_correct_result(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted.recompute_data()
        self.assertAlmostEqual(data_item_inverted.cached_data[0, 0], -1.0)
        # now the source data changes and the inverted data needs computing.
        with data_item.data_ref() as data_ref:
            data_ref.master_data = data_ref.master_data + 2.0
        data_item_inverted.recompute_data()
        self.assertAlmostEqual(data_item_inverted.cached_data[0, 0], -3.0)

    def test_recomputing_data_does_not_notify_listeners_of_stale_data_unless_it_is_really_stale(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
        document_model.append_data_item(data_item)
        self.assertTrue(data_item.is_cached_value_dirty("statistics_data"))
        document_model.recompute_all()
        data_item.get_processor("statistics").recompute_data(None)
        self.assertFalse(data_item.is_cached_value_dirty("statistics_data"))
        data_item.recompute_data()
        self.assertFalse(data_item.is_cached_value_dirty("statistics_data"))

    def test_recomputing_data_after_cached_data_is_called_gives_correct_result(self):
        # verify that this works, the more fundamental test is in test_reloading_stale_data_should_still_be_stale
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted.recompute_data()
        self.assertFalse(data_item_inverted.is_data_stale)
        self.assertAlmostEqual(data_item_inverted.cached_data[0, 0], -1.0)
        # now the source data changes and the inverted data needs computing.
        with data_item.data_ref() as data_ref:
            data_ref.master_data = data_ref.master_data + 2.0
        # verify the actual data values are still stale
        self.assertAlmostEqual(data_item_inverted.cached_data[0, 0], -1.0)
        # recompute and verify the data values are valid
        data_item_inverted.recompute_data()
        self.assertAlmostEqual(data_item_inverted.cached_data[0, 0], -3.0)

    def test_statistics_marked_dirty_when_data_changed(self):
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.uint32))
        self.assertTrue(data_item.is_cached_value_dirty("statistics_data"))
        data_item.get_processor("statistics").recompute_data(None)
        self.assertIsNotNone(data_item.get_processed_data("statistics"))
        self.assertFalse(data_item.is_cached_value_dirty("statistics_data"))
        with data_item.data_ref() as data_ref:
            data_ref.master_data = data_ref.master_data + 1.0
        self.assertTrue(data_item.is_cached_value_dirty("statistics_data"))

    def test_statistics_marked_dirty_when_source_data_changed(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.ones((256, 256), numpy.double))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted.get_processor("statistics").recompute_data(None)
        data_item_inverted.get_processed_data("statistics")
        # here the data should be computed and the statistics should not be dirty
        self.assertFalse(data_item_inverted.is_cached_value_dirty("statistics_data"))
        # now the source data changes and the inverted data needs computing.
        # the statistics should also be dirty.
        with data_item.data_ref() as data_ref:
            data_ref.master_data = data_ref.master_data + 1.0
        self.assertTrue(data_item_inverted.is_cached_value_dirty("statistics_data"))

    def test_statistics_marked_dirty_when_source_data_recomputed(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.double))
        document_model.append_data_item(data_item)
        data_item_inverted = DataItem.DataItem()
        invert_operation = Operation.OperationItem("invert-operation")
        invert_operation.add_data_source(Operation.DataItemDataSource(data_item))
        data_item_inverted.set_operation(invert_operation)
        document_model.append_data_item(data_item_inverted)
        data_item_inverted.get_processor("statistics").recompute_data(None)
        data_item_inverted.get_processed_data("statistics")
        # here the data should be computed and the statistics should not be dirty
        self.assertFalse(data_item_inverted.is_cached_value_dirty("statistics_data"))
        # now the source data changes and the inverted data needs computing.
        # the statistics should also be dirty.
        with data_item.data_ref() as data_ref:
            data_ref.master_data = data_ref.master_data + 2.0
        self.assertTrue(data_item_inverted.is_cached_value_dirty("statistics_data"))
        # next recompute data, the statistics should be dirty now.
        data_item_inverted.recompute_data()
        self.assertTrue(data_item_inverted.is_cached_value_dirty("statistics_data"))
        # get the new statistics and verify they are correct.
        data_item_inverted.get_processor("statistics").recompute_data(None)
        good_statistics = data_item_inverted.get_processed_data("statistics")
        self.assertTrue(good_statistics["mean"] == -3.0)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
