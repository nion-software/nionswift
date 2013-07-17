import numpy
import unittest
import weakref

from nion.swift import DataItem
from nion.swift import Graphics
from nion.swift import Operation


class TestCalibrationClass(unittest.TestCase):

    def test_conversion(self):
        calibration = DataItem.Calibration(3.0, 2.0, "x")
        calibration.add_ref()
        self.assertEqual(calibration.convert_to_calibrated_str(5), "13.0 x")
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
        data_item = DataItem.DataItem()
        data_item.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_item.add_ref()
        data_item.calibrations[0].origin = 3.0
        data_item.calibrations[0].scale = 2.0
        data_item.calibrations[0].units = "x"
        data_item.calibrations[1].origin = 3.0
        data_item.calibrations[1].scale = 2.0
        data_item.calibrations[1].units = "x"
        self.assertEqual(len(data_item.calibrations), 2)
        new_data_item = DataItem.DataItem()
        new_data_item.operations.append(Operation.InvertOperation())
        data_item.data_items.append(new_data_item)
        calculated_calibrations = new_data_item.calculated_calibrations
        self.assertEqual(len(calculated_calibrations), 2)
        self.assertEqual(int(calculated_calibrations[0].origin), 3)
        self.assertEqual(int(calculated_calibrations[0].scale), 2)
        self.assertEqual(calculated_calibrations[0].units, "x")
        self.assertEqual(int(calculated_calibrations[1].origin), 3)
        self.assertEqual(int(calculated_calibrations[1].scale), 2)
        self.assertEqual(calculated_calibrations[1].units, "x")
        new_data_item.operations.append(Operation.FFTOperation())
        calculated_calibrations = new_data_item.calculated_calibrations
        self.assertEqual(int(calculated_calibrations[0].origin), 0)
        self.assertEqual(calculated_calibrations[0].units, "1/x")
        self.assertEqual(int(calculated_calibrations[1].origin), 0)
        self.assertEqual(calculated_calibrations[1].units, "1/x")
        data_item.remove_ref()

    def test_double_dependent_calibration(self):
        data_item = DataItem.DataItem()
        data_item.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_item.add_ref()
        data_item2 = DataItem.DataItem()
        data_item2.add_ref()
        operation2 = Operation.ResampleOperation()
        data_item2.operations.append(operation2)
        data_item.data_items.append(data_item2)
        data_item2.remove_ref()
        data_item3 = DataItem.DataItem()
        data_item3.add_ref()
        operation3 = Operation.ResampleOperation()
        data_item3.operations.append(operation3)
        data_item2.data_items.append(data_item3)
        data_item3.calculated_calibrations
        data_item3.remove_ref()
        data_item.remove_ref()


class TestDataItemClass(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_delete_data_item(self):
        data_item = DataItem.DataItem()
        data_item.add_ref()
        data_item.master_data = numpy.zeros((256, 256), numpy.uint32)
        weak_data_item = weakref.ref(data_item)
        data_item.remove_ref()
        data_item = None
        self.assertIsNone(weak_data_item())

    def test_copy_data_item(self):
        data_item = DataItem.DataItem()
        data_item.add_ref()
        data_item.master_data = numpy.zeros((256, 256), numpy.uint32)
        new_data_item = data_item.copy()
        new_data_item.add_ref()
        new_data_item.remove_ref()
        data_item.remove_ref()

    def test_clear_thumbnail_when_data_item_changed(self):
        data_item = DataItem.DataItem()
        data_item.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_item.add_ref()
        self.assertFalse(data_item.thumbnail_data_valid)
        self.assertIsNotNone(data_item.get_thumbnail_data(64, 64))
        self.assertTrue(data_item.thumbnail_data_valid)
        data_item.master_data = numpy.zeros((256, 256), numpy.uint32)
        self.assertFalse(data_item.thumbnail_data_valid)
        data_item.remove_ref()

    def test_delete_nested_data_item(self):
        data_item = DataItem.DataItem()
        data_item.add_ref()
        data_item.master_data = numpy.zeros((256, 256), numpy.uint32)
        data_item2 = DataItem.DataItem()
        data_item.data_items.append(data_item2)
        data_item3 = DataItem.DataItem()
        data_item2.data_items.append(data_item3)
        data_item.data_items.remove(data_item2)
        data_item.remove_ref()

    def test_copy_data_item_with_graphics(self):
        data_item = DataItem.DataItem()
        data_item.add_ref()
        data_item.master_data = numpy.zeros((256, 256), numpy.uint32)
        rect_graphic = Graphics.RectangleGraphic()
        data_item.graphics.append(rect_graphic)
        self.assertEqual(len(data_item.graphics), 1)
        new_data_item = data_item.copy()
        new_data_item.add_ref()
        self.assertEqual(len(new_data_item.graphics), 1)
        new_data_item.remove_ref()
        data_item.remove_ref()
