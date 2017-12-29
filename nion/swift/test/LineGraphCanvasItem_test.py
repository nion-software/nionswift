# standard libraries
import contextlib
import logging
import math
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift import LineGraphCanvasItem
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import TestUI


class TestLineGraphCanvasItem(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_data_values_give_pretty_limits_when_auto(self):

        test_ranges = (
            ((7.46, 85.36), (0.0, 100.0)),
            ((7.67, 12.95), (0.0, 15.0)),
            ((6.67, 11.95), (0.0, 15.0)),
            ((0.00, 0.00), (0.0, 0.0))
        )

        for data_in, data_out in test_ranges:
            data_min, data_max = data_in
            expected_uncalibrated_data_min, expected_uncalibrated_data_max = data_out
            data = numpy.zeros((16, 16), dtype=numpy.float64)
            irow, icol = numpy.ogrid[0:16, 0:16]
            data[:] = data_min + (data_max - data_min) * (irow / 15.0)
            # auto on min/max
            data_info = LineGraphCanvasItem.LineGraphDataInfo(data)
            self.assertEqual(data_info.uncalibrated_data_min, expected_uncalibrated_data_min)
            self.assertEqual(data_info.uncalibrated_data_max, expected_uncalibrated_data_max)

    def test_display_limits_are_reasonable_when_using_log_scale(self):
        data = numpy.linspace(-0.1, 10.0, 10)
        data_info = LineGraphCanvasItem.LineGraphDataInfo(data, data_style="log")
        self.assertAlmostEqual(data_info.uncalibrated_data_min, 1.0)
        self.assertAlmostEqual(data_info.uncalibrated_data_max, 10.0)
        calibrated_data = data_info.calculate_calibrated_data(data)
        self.assertAlmostEqual(numpy.amin(calibrated_data), math.log10(1.0))
        self.assertAlmostEqual(numpy.amax(calibrated_data), math.log10(10.0))

    def test_display_limits_are_reasonable_when_using_calibrated_log_scale(self):
        intensity_calibration = Calibration.Calibration(-5, 2)
        data = numpy.linspace(-0.1, 10.0, 10)
        data_info = LineGraphCanvasItem.LineGraphDataInfo(data, y_calibration=intensity_calibration, data_style="log")
        self.assertAlmostEqual(data_info.calibrated_data_min, 0.0)
        self.assertAlmostEqual(data_info.calibrated_data_max, 1.5)  # empirically mesaured
        calibrated_data = data_info.calculate_calibrated_data(data)
        self.assertAlmostEqual(numpy.amin(calibrated_data), math.log10(1.0))
        self.assertAlmostEqual(numpy.amax(calibrated_data), math.log10(15.0))

    def test_tool_returns_to_pointer_after_but_not_during_creating_interval(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((100,)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            header_height = display_panel.header_canvas_item.header_height
            display_panel.root_container.layout_immediate((1000 + header_height, 1000))
            # run test
            self.assertEqual(document_controller.tool_mode, "pointer")
            for tool_mode in ["interval"]:
                document_controller.tool_mode = tool_mode
                display_panel.display_canvas_item.simulate_press((100,125))
                display_panel.display_canvas_item.simulate_move((100,125))
                self.assertEqual(document_controller.tool_mode, tool_mode)
                display_panel.display_canvas_item.simulate_move((250,200))
                display_panel.display_canvas_item.simulate_release((250,200))
                self.assertEqual(document_controller.tool_mode, "pointer")

    def test_pointer_tool_makes_intervals(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((100,)))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            # test
            document_controller.tool_mode = "pointer"
            display_panel.display_canvas_item.simulate_drag((240, 160), (240, 480))
            interval_region = data_item.displays[0].graphics[0]
            self.assertEqual(interval_region.type, "interval-graphic")
            self.assertTrue(interval_region.end > interval_region.start)

    def test_pointer_tool_makes_intervals_when_other_intervals_exist(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((100,)))
            region = Graphics.IntervalGraphic()
            region.start = 0.9
            region.end = 0.95
            data_item.displays[0].add_graphic(region)
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            # test
            document_controller.tool_mode = "pointer"
            display_panel.display_canvas_item.simulate_drag((240, 160), (240, 480))
            interval_region = data_item.displays[0].graphics[1]
            self.assertEqual(interval_region.type, "interval-graphic")
            self.assertTrue(interval_region.end > interval_region.start)

    def test_nudge_interval(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((100,)))
            region = Graphics.IntervalGraphic()
            region.start = 0.1
            region.end = 0.9
            data_item.displays[0].add_graphic(region)
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            display_panel.display_canvas_item.prepare_display()  # force layout
            # test
            document_controller.tool_mode = "pointer"
            display_panel.display_canvas_item.simulate_click((240, 320))
            display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left"))
            interval_region = data_item.displays[0].graphics[0]
            self.assertTrue(interval_region.start < 0.1)
            self.assertTrue(interval_region.end < 0.9)
            self.assertAlmostEqual(interval_region.end - interval_region.start, 0.8)

    def test_line_plot_auto_scales_uncalibrated_y_axis(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data = numpy.zeros((100,))
            data[50] = 75
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            data_info = display_panel.display_canvas_item._data_info
            self.assertAlmostEqual(data_info.calibrated_data_min, 0.0)
            self.assertAlmostEqual(data_info.calibrated_data_max, 80.0)
            self.assertAlmostEqual(data_info.uncalibrated_data_min, 0.0)
            self.assertAlmostEqual(data_info.uncalibrated_data_max, 80.0)

    def test_line_plot_auto_scales_calibrated_y_axis(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data = numpy.zeros((10,))
            data[5] = 75
            data_item = DataItem.DataItem(data)
            data_item.set_xdata(DataAndMetadata.new_data_and_metadata(data, Calibration.Calibration(0, 0.5, "x")))
            document_model.append_data_item(data_item)
            display_panel.set_display_panel_data_item(data_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            data_info = display_panel.display_canvas_item._data_info
            self.assertAlmostEqual(data_info.calibrated_data_min, 0.0)
            self.assertAlmostEqual(data_info.calibrated_data_max, 40.0)
            self.assertAlmostEqual(data_info.uncalibrated_data_min, 0.0)
            self.assertAlmostEqual(data_info.uncalibrated_data_max, 80.0)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
