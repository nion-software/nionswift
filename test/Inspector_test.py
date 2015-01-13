# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import ImagePanel
from nion.swift import Inspector
from nion.swift.model import Calibration
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Storage
from nion.ui import Binding
from nion.ui import Observable
from nion.ui import Test


class TestInspectorClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_display_limits_inspector_should_bind_to_display_without_errors(self):
        cache_name = ":memory:"
        storage_cache = Storage.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(storage_cache=storage_cache)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        document_model.append_data_item(data_item)
        # configure the inspectors
        document_controller.notify_selected_data_item_changed(data_item)
        document_controller.periodic()  # force UI to update
        document_controller.notify_selected_data_item_changed(None)
        # clean up
        document_controller.close()

    def test_calibration_value_and_size_float_to_string_converter_works_with_display(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        display = data_item.displays[0]
        converter = Inspector.CalibratedValueFloatToStringConverter(display, 0, 256)
        converter.convert(0.5)
        converter = Inspector.CalibratedSizeFloatToStringConverter(display, 0, 256)
        converter.convert(0.5)

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
        display = data_item.displays[0]
        y_converter = Inspector.CalibratedValueFloatToStringConverter(display, 0, 256)
        height_converter = Inspector.CalibratedSizeFloatToStringConverter(display, 0, 256)
        bool_model = BoolModel()
        display_calibrated_values_binding = Binding.PropertyBinding(bool_model, "display_calibrated_values")
        display_calibrated_values_binding2 = Binding.PropertyBinding(bool_model, "display_calibrated_values")
        center_y_binding = Inspector.CalibratedValueBinding(Binding.TuplePropertyBinding(rect_graphic, "center", 0), display_calibrated_values_binding, y_converter)
        size_width_binding = Inspector.CalibratedValueBinding(Binding.TuplePropertyBinding(rect_graphic, "size", 0), display_calibrated_values_binding2, height_converter)
        size_width_binding.update_source("0.6")
        self.assertEqual(center, rect_graphic.center)

    def test_calibration_inspector_section_binds_initially(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        display = data_item.displays[0]
        Inspector.CalibrationsInspectorSection(self.app.ui, display)

    def test_calibration_inspector_section_follows_spatial_calibration_change(self):
        data_item = DataItem.DataItem(numpy.zeros((256, 256), numpy.uint32))
        display = data_item.displays[0]
        inspector_section = Inspector.CalibrationsInspectorSection(self.app.ui, display)
        data_item.maybe_data_source.set_dimensional_calibration(0, Calibration.Calibration(units="mm"))
        data_item.maybe_data_source.set_dimensional_calibration(1, Calibration.Calibration(units="mm"))

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
