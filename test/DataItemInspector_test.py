# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DataItemInspector
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.ui import Observable
from nion.ui import Test
from nion.ui import UserInterfaceUtility


class TestDataItemInspectorClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    # necessary to make inspector display updated values properly
    def test_adjusting_rectangle_width_should_keep_center_constant(self):
        rect_graphic = Graphics.RectangleGraphic()
        rect_graphic.bounds = ((0.25, 0.25), (0.5, 0.5))
        center = rect_graphic.center
        class BoolModel(Observable.Observable):
            def __init__(self):
                super(BoolModel, self).__init__()
                self.display_calibrated_values = False
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        y_converter = DataItem.CalibratedValueFloatToStringConverter(data_item, 0, 256)
        height_converter = DataItem.CalibratedSizeFloatToStringConverter(data_item, 0, 256)
        bool_model = BoolModel()
        display_calibrated_values_binding = UserInterfaceUtility.PropertyBinding(bool_model, "display_calibrated_values")
        display_calibrated_values_binding2 = UserInterfaceUtility.PropertyBinding(bool_model, "display_calibrated_values")
        center_y_binding = DataItemInspector.CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(rect_graphic, "center", 0), display_calibrated_values_binding, y_converter)
        size_width_binding = DataItemInspector.CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(rect_graphic, "size", 0), display_calibrated_values_binding2, height_converter)
        size_width_binding.update_source("0.6")
        center_y_binding.periodic()
        size_width_binding.periodic()
        self.assertEqual(center, rect_graphic.center)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
