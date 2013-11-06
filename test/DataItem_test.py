# standard libraries
import copy
import math
import threading
import unittest
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import DataItem
from nion.swift import Graphics
from nion.swift import Image
from nion.swift import Operation


class TestCalibrationClass(unittest.TestCase):

    def test_conversion(self):
        calibration = DataItem.Calibration(3.0, 2.0, "x")
        calibration.add_ref()
        self.assertEqual(calibration.convert_to_calibrated_value_str(5), u"13.0 x")
        calibration.remove_ref()

    def test_calibration_relationship(self):
        data_item = DataItem.DataItem()
        data_item.add_ref()
        self.assertEqual(len(data_item.calibrations), 0)
        data_item.calibrations.append(DataItem.Calibration(3.0, 2.0, "x"))
        self.assertEqual(len(data_item.calibrations), 1)
        self.assertIsNotNone(data_item.calibrations[0])
        data_item.remove_ref()

    def test_dependent_calibration(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.add_ref()
        data_item.calibrations[0].origin = 3.0
        data_item.calibrations[0].scale = 2.0
        data_item.calibrations[0].units = "x"
        data_item.calibrations[1].origin = 3.0
        data_item.calibrations[1].scale = 2.0
        data_item.calibrations[1].units = "x"
        self.assertEqual(len(data_item.calibrations), 2)
        data_item_copy = DataItem.DataItem()
        data_item_copy.operations.append(Operation.InvertOperation())
        data_item.data_items.append(data_item_copy)
        calculated_calibrations = data_item_copy.calculated_calibrations
        self.assertEqual(len(calculated_calibrations), 2)
        self.assertEqual(int(calculated_calibrations[0].origin), 3)
        self.assertEqual(int(calculated_calibrations[0].scale), 2)
        self.assertEqual(calculated_calibrations[0].units, "x")
        self.assertEqual(int(calculated_calibrations[1].origin), 3)
        self.assertEqual(int(calculated_calibrations[1].scale), 2)
        self.assertEqual(calculated_calibrations[1].units, "x")
        data_item_copy.operations.append(Operation.FFTOperation())
        calculated_calibrations = data_item_copy.calculated_calibrations
        self.assertEqual(int(calculated_calibrations[0].origin), 0)
        self.assertEqual(calculated_calibrations[0].units, "1/x")
        self.assertEqual(int(calculated_calibrations[1].origin), 0)
        self.assertEqual(calculated_calibrations[1].units, "1/x")
        data_item.remove_ref()

    def test_double_dependent_calibration(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.add_ref()
        data_item2 = DataItem.DataItem()
        data_item2.add_ref()
        operation2 = Operation.Resample2dOperation()
        data_item2.operations.append(operation2)
        data_item.data_items.append(data_item2)
        data_item2.remove_ref()
        data_item3 = DataItem.DataItem()
        data_item3.add_ref()
        operation3 = Operation.Resample2dOperation()
        data_item3.operations.append(operation3)
        data_item2.data_items.append(data_item3)
        data_item3.calculated_calibrations
        data_item3.remove_ref()
        data_item.remove_ref()

    def test_spatial_calibration_on_rgb(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256, 4), numpy.uint8))
        data_item.add_ref()
        self.assertTrue(Image.is_shape_and_dtype_2d(*data_item.data_shape_and_dtype))
        self.assertTrue(Image.is_shape_and_dtype_rgba(*data_item.data_shape_and_dtype))
        self.assertEqual(len(data_item.calibrations), 2)
        data_item.remove_ref()


class TestDataItemClass(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_delete_data_item(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.add_ref()
        weak_data_item = weakref.ref(data_item)
        data_item.remove_ref()
        data_item = None
        self.assertIsNone(weak_data_item())

    def test_copy_data_item(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.title = "data_item"
        data_item.add_ref()
        with data_item.create_data_accessor() as data_accessor:
            data_accessor.master_data[128, 128] = 1000  # data range (0, 1000)
            data_accessor.master_data_updated()
            data_item.operations.append(Operation.InvertOperation())
            data_item.graphics.append(Graphics.RectangleGraphic())
            data_item2 = DataItem.DataItem()
            data_item2.title = "data_item2"
            data_item.data_items.append(data_item2)
            data_item_copy = copy.deepcopy(data_item)
            with data_item_copy.create_data_accessor() as data_copy_accessor:
                # make sure the data is not shared between the original and the copy
                self.assertEqual(data_accessor.master_data[0,0], 0)
                self.assertEqual(data_copy_accessor.master_data[0,0], 0)
                data_accessor.master_data[:] = 1
                data_accessor.master_data_updated()
                self.assertEqual(data_accessor.master_data[0,0], 1)
                self.assertEqual(data_copy_accessor.master_data[0,0], 0)
        # make sure calibrations, operations, nor graphics are not shared
        self.assertNotEqual(data_item.calibrations[0], data_item_copy.calibrations[0])
        self.assertNotEqual(data_item.operations[0], data_item_copy.operations[0])
        self.assertNotEqual(data_item.graphics[0], data_item_copy.graphics[0])
        # make sure data_items are not shared
        self.assertNotEqual(data_item.data_items[0], data_item_copy.data_items[0])
        # make sure data sources get handled
        self.assertEqual(data_item2.data_source, data_item)
        self.assertEqual(data_item.data_items[0].data_source, data_item)
        self.assertEqual(data_item_copy.data_items[0].data_source, data_item_copy)
        # clean up
        data_item_copy.add_ref()
        data_item_copy.remove_ref()
        data_item.remove_ref()

    def test_copy_data_item_with_crop(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.add_ref()
        crop_graphic = Graphics.RectangleGraphic()
        crop_graphic.bounds = ((0.25,0.25), (0.5,0.5))
        data_item.graphics.append(crop_graphic)
        crop_operation = Operation.Crop2dOperation()
        crop_operation.graphic = crop_graphic
        data_item.operations.append(crop_operation)
        data_item_copy = copy.deepcopy(data_item)
        data_item_copy.add_ref()
        self.assertEqual(len(data_item_copy.graphics), len(data_item.graphics))
        self.assertEqual(data_item_copy.graphics[0].bounds, data_item.graphics[0].bounds)
        self.assertNotEqual(data_item_copy.graphics[0], data_item.graphics[0])
        self.assertNotEqual(data_item_copy.operations[0], data_item.operations[0])
        # clean up
        data_item_copy.remove_ref()
        data_item.remove_ref()

    def test_clear_thumbnail_when_data_item_changed(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.add_ref()
        self.assertTrue(data_item.thumbnail_data_dirty)
        # configure a listener to know when the thumbnail is finished
        event = threading.Event()
        class Listener(object):
            def data_item_changed(self, data_item, changes):
                if DataItem.THUMBNAIL in changes:
                    event.set()
        listener = Listener()
        data_item.add_listener(listener)
        # the next line also triggers the thumbnail calculation
        self.assertIsNotNone(data_item.get_thumbnail_data(64, 64))
        # wait for the thumbnail
        event.wait()
        data_item.remove_listener(listener)
        self.assertFalse(data_item.thumbnail_data_dirty)
        with data_item.create_data_accessor() as data_accessor:
            data_accessor.master_data = numpy.zeros((256, 256), numpy.uint32)
        self.assertTrue(data_item.thumbnail_data_dirty)
        data_item.remove_ref()

    def test_thumbnail_1d(self):
        data_item = DataItem.DataItem(numpy.zeros((256), numpy.uint32))
        data_item.add_ref()
        self.assertIsNotNone(data_item.get_thumbnail_data(64, 64))
        data_item.remove_ref()

    # make sure thumbnail raises exception if a bad operation is involved
    def test_thumbnail_bad_operation(self):
        class BadOperation(Operation.FFTOperation):
            def process_data_in_place(self, data_array):
                raise NotImplementedError()
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.add_ref()
        data_item2 = DataItem.DataItem()
        data_item2.operations.append(BadOperation())
        data_item.data_items.append(data_item2)
        with self.assertRaises(NotImplementedError):
            with data_item2.create_data_accessor() as data2_accessor:
                data2_accessor.data  # trigger the data calculation
            # NOTE: this test is no longer quite valid since the data call
            # is required to trigger the thumbnail data functionality.
            # thumbnails no longer trigger a call to data.
            # CEM 2013-10-18
            data_item2.get_thumbnail_data(64, 64)
        data_item.remove_ref()

    def test_delete_nested_data_item(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.add_ref()
        data_item2 = DataItem.DataItem()
        data_item.data_items.append(data_item2)
        data_item3 = DataItem.DataItem()
        data_item2.data_items.append(data_item3)
        data_item.data_items.remove(data_item2)
        data_item.remove_ref()

    def test_copy_data_item_with_graphics(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.add_ref()
        rect_graphic = Graphics.RectangleGraphic()
        data_item.graphics.append(rect_graphic)
        self.assertEqual(len(data_item.graphics), 1)
        data_item_copy = copy.deepcopy(data_item)
        data_item_copy.add_ref()
        self.assertEqual(len(data_item_copy.graphics), 1)
        data_item_copy.remove_ref()
        data_item.remove_ref()

    def test_data_item_data_changed(self):
        # set up the data items
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.add_ref()
        data_item_roi = Graphics.LineGraphic()
        data_item.graphics.append(data_item_roi)
        data_item2 = DataItem.DataItem()
        data_item2.operations.append(Operation.FFTOperation())
        data_item.data_items.append(data_item2)
        data_item3 = DataItem.DataItem()
        data_item3.operations.append(Operation.IFFTOperation())
        data_item2.data_items.append(data_item3)
        # establish listeners
        class Listener(object):
            def __init__(self):
                self.reset()
            def reset(self):
                self.data_changed = False
                self.display_changed = False
                self.children_changed = False
            def data_item_changed(self, data_item, changes):
                self.data_changed = self.data_changed or DataItem.DATA in changes
                self.display_changed = self.display_changed or DataItem.DISPLAY in changes or DataItem.DATA in changes
                self.children_changed = self.children_changed or DataItem.CHILDREN in changes
        listener = Listener()
        data_item.add_listener(listener)
        listener2 = Listener()
        data_item2.add_listener(listener2)
        listener3 = Listener()
        data_item3.add_listener(listener3)
        listeners = (listener, listener2, listener3)
        # changing the master data of the source should trigger a data changed message
        # subsequently that should trigger a changed message for dependent items
        map(Listener.reset, listeners)
        with data_item.create_data_accessor() as data_accessor:
            data_accessor.master_data = numpy.zeros((256, 256), numpy.uint32)
        self.assertTrue(listener.data_changed and listener.display_changed)
        self.assertTrue(listener2.data_changed and listener2.display_changed)
        self.assertTrue(listener3.data_changed and listener3.display_changed)
        # changing the param of the source should trigger a display changed message
        # but no data changed. nothing should change on the dependent items.
        map(Listener.reset, listeners)
        data_item.param = 0.6
        self.assertTrue(not listener.data_changed and listener.display_changed)
        self.assertTrue(not listener2.data_changed and not listener2.display_changed)
        self.assertTrue(not listener3.data_changed and not listener3.display_changed)
        # changing a graphic on source should NOT change dependent data
        # it should change the primary data item display, but not its data
        map(Listener.reset, listeners)
        data_item_roi.start = (0.8, 0.2)
        self.assertTrue(not listener.data_changed)
        self.assertTrue(listener.display_changed)
        self.assertTrue(not listener.data_changed and listener.display_changed)
        self.assertTrue(not listener2.data_changed and not listener2.display_changed)
        self.assertTrue(not listener3.data_changed and not listener3.display_changed)
        # changing the display limit of source should NOT change dependent data
        map(Listener.reset, listeners)
        data_item.display_limits = (0.1, 0.9)
        self.assertTrue(not listener.data_changed and listener.display_changed)
        self.assertTrue(not listener2.data_changed and not listener2.display_changed)
        self.assertTrue(not listener3.data_changed and not listener3.display_changed)
        # modify a calibration should NOT change dependent data, but should change dependent display
        map(Listener.reset, listeners)
        data_item.calibrations[0].origin = 1.0
        self.assertTrue(not listener.data_changed and listener.display_changed)
        self.assertTrue(not listener2.data_changed and not listener2.display_changed)
        self.assertTrue(not listener3.data_changed and not listener3.display_changed)
        # add/remove an operation. should change primary and dependent data and display
        map(Listener.reset, listeners)
        invert_operation = Operation.InvertOperation()
        data_item.operations.append(invert_operation)
        self.assertTrue(listener.data_changed and listener.display_changed)
        self.assertTrue(listener2.data_changed and listener2.display_changed)
        self.assertTrue(listener3.data_changed and listener3.display_changed)
        map(Listener.reset, listeners)
        data_item.operations.remove(invert_operation)
        self.assertTrue(listener.data_changed and listener.display_changed)
        self.assertTrue(listener2.data_changed and listener2.display_changed)
        self.assertTrue(listener3.data_changed and listener3.display_changed)
        # add/remove a data item should NOT change data or dependent data or display
        map(Listener.reset, listeners)
        data_item4 = DataItem.DataItem()
        data_item.data_items.append(data_item4)
        self.assertTrue(not listener.data_changed and not listener.display_changed)
        self.assertTrue(not listener2.data_changed and not listener2.display_changed)
        self.assertTrue(not listener3.data_changed and not listener3.display_changed)
        map(Listener.reset, listeners)
        data_item.data_items.remove(data_item4)
        self.assertTrue(not listener.data_changed and not listener.display_changed)
        self.assertTrue(not listener2.data_changed and not listener2.display_changed)
        self.assertTrue(not listener3.data_changed and not listener3.display_changed)
        # modify an operation. make sure data and dependent data gets updated.
        blur_operation = Operation.GaussianBlurOperation()
        data_item.operations.append(blur_operation)
        map(Listener.reset, listeners)
        blur_operation.sigma = 0.1
        self.assertTrue(listener.data_changed and listener.display_changed)
        self.assertTrue(listener2.data_changed and listener2.display_changed)
        self.assertTrue(listener3.data_changed and listener3.display_changed)
        data_item.operations.remove(blur_operation)
        # modify an operation roi. make sure data and dependent data gets updated.
        crop_graphic = Graphics.RectangleGraphic()
        crop_graphic.bounds = ((0.25,0.25), (0.5,0.5))
        data_item.graphics.append(crop_graphic)
        crop_operation = Operation.Crop2dOperation()
        crop_operation.graphic = crop_graphic
        data_item.operations.append(crop_operation)
        map(Listener.reset, listeners)
        crop_operation.graphic.bounds = ((0,0), (0.5, 0.5))
        self.assertTrue(listener.data_changed and listener.display_changed)
        self.assertTrue(listener2.data_changed and listener2.display_changed)
        self.assertTrue(listener3.data_changed and listener3.display_changed)
        data_item.operations.remove(crop_operation)
        # finish up
        data_item.remove_ref()

    def test_data_range(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        data_item.add_ref()
        # test scalar
        xx, yy = numpy.meshgrid(numpy.linspace(0,1,256), numpy.linspace(0,1,256))
        with data_item.create_data_accessor() as data_accessor:
            data_accessor.master_data = 50 * (xx + yy) + 25
            data_accessor.data  # TODO: this should not be required
            data_range = data_item.display_range
            self.assertEqual(data_range, (25, 125))
            # now test complex
            data_accessor.master_data = numpy.zeros((256, 256), numpy.complex64)
            xx, yy = numpy.meshgrid(numpy.linspace(0,1,256), numpy.linspace(0,1,256))
            data_accessor.master_data = (2 + xx * 10) + 1j * (3 + yy * 10)
            data_accessor.data  # TODO: this should not be required
        data_range = data_item.display_range
        data_min = math.log(math.sqrt(2*2 + 3*3) + 1)
        data_max = math.log(math.sqrt(12*12 + 13*13) + 1)
        self.assertEqual(int(data_min*1e6), int(data_range[0]*1e6))
        self.assertEqual(int(data_max*1e6), int(data_range[1]*1e6))
        # clean up
        data_item.remove_ref()

if __name__ == '__main__':
    unittest.main()
