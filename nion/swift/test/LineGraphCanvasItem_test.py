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
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.ui import DrawingContext
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
            calibrated_data_min, calibrated_data_max, y_ticker = LineGraphCanvasItem.calculate_y_axis([data], None, None, None, None)
            axes = LineGraphCanvasItem.LineGraphAxes(1.0, calibrated_data_min, calibrated_data_max, y_ticker=y_ticker)
            self.assertEqual(axes.uncalibrated_data_min, expected_uncalibrated_data_min)
            self.assertEqual(axes.uncalibrated_data_max, expected_uncalibrated_data_max)

    def test_display_limits_are_reasonable_when_using_log_scale(self):
        data = numpy.linspace(-0.1, 10.0, 10)
        data_style = "log"
        calibrated_data_min, calibrated_data_max, y_ticker = LineGraphCanvasItem.calculate_y_axis([data], None, None, None, data_style)
        axes = LineGraphCanvasItem.LineGraphAxes(1.0, calibrated_data_min, calibrated_data_max, data_style=data_style, y_ticker=y_ticker)
        self.assertAlmostEqual(axes.uncalibrated_data_min, 1.0)
        self.assertAlmostEqual(axes.uncalibrated_data_max, 10.0)
        calibrated_data = axes.calculate_calibrated_xdata(DataAndMetadata.new_data_and_metadata(data)).data
        self.assertAlmostEqual(numpy.amin(calibrated_data), math.log10(1.0))
        self.assertAlmostEqual(numpy.amax(calibrated_data), math.log10(10.0))

    def test_display_limits_are_reasonable_when_using_calibrated_log_scale(self):
        intensity_calibration = Calibration.Calibration(-5, 2)
        data = numpy.linspace(-0.1, 10.0, 10)
        data_style = "log"
        calibrated_data_min, calibrated_data_max, y_ticker = LineGraphCanvasItem.calculate_y_axis([data], None, None, intensity_calibration, data_style)
        axes = LineGraphCanvasItem.LineGraphAxes(1.0, calibrated_data_min, calibrated_data_max, y_calibration=intensity_calibration, data_style=data_style, y_ticker=y_ticker)
        self.assertAlmostEqual(axes.calibrated_data_min, 0.0)
        self.assertAlmostEqual(axes.calibrated_data_max, 1.5)  # empirically mesaured
        calibrated_data = axes.calculate_calibrated_xdata(DataAndMetadata.new_data_and_metadata(data)).data
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
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate((800, 1000))
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
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            # test
            document_controller.tool_mode = "pointer"
            display_panel.display_canvas_item.simulate_drag((240, 160), (240, 480))
            interval_region = display_item.graphics[0]
            self.assertEqual(interval_region.type, "interval-graphic")
            self.assertTrue(interval_region.end > interval_region.start)

    def test_pointer_tool_makes_intervals_when_other_intervals_exist(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((100,)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.IntervalGraphic()
            region.start = 0.9
            region.end = 0.95
            display_item.add_graphic(region)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            # test
            document_controller.tool_mode = "pointer"
            display_panel.display_canvas_item.simulate_drag((240, 160), (240, 480))
            interval_region = display_item.graphics[1]
            self.assertEqual(interval_region.type, "interval-graphic")
            self.assertTrue(interval_region.end > interval_region.start)

    def test_nudge_interval(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((100,)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.IntervalGraphic()
            region.start = 0.1
            region.end = 0.9
            display_item.add_graphic(region)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            display_panel.display_canvas_item.prepare_display()  # force layout
            # test
            document_controller.tool_mode = "pointer"
            display_panel.display_canvas_item.simulate_click((240, 320))
            display_panel.display_canvas_item.key_pressed(self.app.ui.create_key_by_id("left"))
            interval_region = display_item.graphics[0]
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
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            axes = display_panel.display_canvas_item._axes
            self.assertAlmostEqual(axes.calibrated_data_min, 0.0)
            self.assertAlmostEqual(axes.calibrated_data_max, 80.0)
            self.assertAlmostEqual(axes.uncalibrated_data_min, 0.0)
            self.assertAlmostEqual(axes.uncalibrated_data_max, 80.0)

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
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            axes = display_panel.display_canvas_item._axes
            self.assertAlmostEqual(axes.calibrated_data_min, 0.0)
            self.assertAlmostEqual(axes.calibrated_data_max, 40.0)
            self.assertAlmostEqual(axes.uncalibrated_data_min, 0.0)
            self.assertAlmostEqual(axes.uncalibrated_data_max, 80.0)

    def test_line_plot_handle_calibrated_x_axis_with_negative_scale(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data = numpy.random.randn(100)
            data_item = DataItem.DataItem(data)
            data_item.set_xdata(DataAndMetadata.new_data_and_metadata(data, dimensional_calibrations=[Calibration.Calibration(0, -1.0, "e")]))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            axes = display_panel.display_canvas_item._axes
            drawing_context = DrawingContext.DrawingContext()
            calibrated_data_min = axes.calibrated_data_min
            calibrated_data_max = axes.calibrated_data_max
            calibrated_data_range = calibrated_data_max - calibrated_data_min
            LineGraphCanvasItem.draw_line_graph(drawing_context, 480, 640, 0, 0, data_item.xdata, calibrated_data_min, calibrated_data_range, axes.calibrated_left_channel, axes.calibrated_right_channel, axes.x_calibration, "black", "black", None, axes.data_style)
            # ensure that the drawing commands are sufficiently populated to have drawn the graph
            self.assertGreater(len(drawing_context.commands), 100)

    def test_line_plot_handles_data_below_one_in_log_scale(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_panel = document_controller.selected_display_panel
            data = numpy.random.rand(100)
            data_item = DataItem.DataItem(data)
            data_item.set_xdata(DataAndMetadata.new_data_and_metadata(data))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.set_display_property("y_style", "log")
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            axes = display_panel.display_canvas_item._axes
            self.assertEqual(axes.data_style, "log")
            drawing_context = DrawingContext.DrawingContext()
            calibrated_data_min = axes.calibrated_data_min
            calibrated_data_max = axes.calibrated_data_max
            calibrated_data_range = calibrated_data_max - calibrated_data_min
            display_xdata = display_panel.display_canvas_item.line_graph_canvas_item.calibrated_xdata
            LineGraphCanvasItem.draw_line_graph(drawing_context, 480, 640, 0, 0, display_xdata, calibrated_data_min, calibrated_data_range, axes.calibrated_left_channel, axes.calibrated_right_channel, axes.x_calibration, "black", "black", None, axes.data_style)
            # ensure that the drawing commands are sufficiently populated to have drawn the graph
            self.assertGreater(len(drawing_context.commands), 100)

    def test_line_plot_with_no_data_displays_gracefully(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.ones((8,), numpy.float))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.data_item.set_xdata(DataAndMetadata.DataAndMetadata(lambda: None, ((8, 0), numpy.float)))
            display_item.display_type = "line_plot"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))

    def test_line_plot_calculates_calibrated_vs_uncalibrated_display_y_values(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(numpy.ones((8, )), intensity_calibration=Calibration.Calibration(offset=0, scale=10, units="nm")))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            self.assertTrue(numpy.array_equal(display_panel.display_canvas_item.line_graph_canvas_item.calibrated_xdata.data, numpy.full((8, ), 10)))
            display_item.calibration_style_id = "pixels-top-left"
            display_panel.display_canvas_item.layout_immediate((640, 480))
            self.assertTrue(numpy.array_equal(display_panel.display_canvas_item.line_graph_canvas_item.calibrated_xdata.data, numpy.ones((8, ))))

    def test_line_plot_handles_calibrated_vs_uncalibrated_display(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(numpy.ones((8, )), dimensional_calibrations=[Calibration.Calibration(offset=0, scale=10, units="nm")]))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            self.assertEqual(display_panel.display_canvas_item.line_graph_canvas_item.calibrated_xdata.dimensional_calibrations[-1].units, "nm")
            display_item.calibration_style_id = "pixels-top-left"
            display_panel.display_canvas_item.layout_immediate((640, 480))
            self.assertFalse(display_panel.display_canvas_item.line_graph_canvas_item.calibrated_xdata.dimensional_calibrations[-1].units)

    def test_line_plot_with_no_data_handles_clicks(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            display_item = DisplayItem.DisplayItem()
            document_model.append_display_item(display_item)
            display_item.display_type = "line_plot"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.layout_immediate((640, 480))
            display_panel.display_canvas_item.simulate_click((240, 16))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
