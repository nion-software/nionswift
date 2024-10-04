# standard libraries
import logging
import math
import operator
import typing
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift import LineGraphCanvasItem
from nion.swift import LinePlotCanvasItem
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.test import TestContext
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import TestUI
from nion.utils import Color
from nion.utils import Geometry


def _enumerate_child_canvas_items_postorder(
        canvas_item: CanvasItem.AbstractCanvasItem,
        depth: int
) -> typing.Iterator[typing.Tuple[CanvasItem.AbstractCanvasItem, int]]:
    if isinstance(canvas_item, CanvasItem.CanvasItemComposition):
        for child_canvas_item in canvas_item.canvas_items:
            yield from _enumerate_child_canvas_items_postorder(child_canvas_item, depth+1)

    yield canvas_item, depth


def _find_first_descendant_of_type_postorder(
        canvas_item: CanvasItem.AbstractCanvasItem,
        canvas_item_type
) -> typing.Optional[CanvasItem.AbstractCanvasItem]:
    return next(
        filter(
            (lambda _: isinstance(_, canvas_item_type)),
            map(operator.itemgetter(0), _enumerate_child_canvas_items_postorder(canvas_item, 0))
        ),
        None
    )

def _print_canvas_item_tree_preorder(canvas_item: CanvasItem.AbstractCanvasItem):

    for ci, depth in _enumerate_child_canvas_items_postorder(canvas_item, 0):
        print("0x{:016x} - {} {} - {}".format(id(ci), depth * '   ', type(ci).__name__, ci.canvas_bounds))

def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


class TestLineGraphCanvasItem(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        TestContext.end_leaks(self)

    def test_data_values_give_pretty_limits_when_auto(self):

        test_ranges = (
            ((7.46, 85.36), (0.0, 100.0)),
            ((7.67, 12.95), (0.0, 15.0)),
            ((6.67, 11.95), (0.0, 15.0)),
            ((0.00, 0.00), (-1.0, 1.0))
        )

        for data_in, data_out in test_ranges:
            data_min, data_max = data_in
            expected_uncalibrated_data_min, expected_uncalibrated_data_max = data_out
            data = numpy.zeros((16, 16), dtype=float)
            irow, icol = numpy.ogrid[0:16, 0:16]
            data[:] = data_min + (data_max - data_min) * (irow / 15.0)
            # auto on min/max
            xdata = DataAndMetadata.new_data_and_metadata(data)
            calibrated_data_min, calibrated_data_max, y_ticker = LineGraphCanvasItem.calculate_y_axis([xdata], None, None, None)
            axes = LineGraphCanvasItem.LineGraphAxes(1.0, calibrated_data_min, calibrated_data_max, 0, 100, None, None, None, y_ticker)
            self.assertEqual(axes.uncalibrated_data_min, expected_uncalibrated_data_min)
            self.assertEqual(axes.uncalibrated_data_max, expected_uncalibrated_data_max)

    def test_display_limits_are_reasonable_when_using_log_scale(self):

        test_ranges = (
            ((-0.1, 11.0), (0.0, 100.0)),
            ((1000.0, 1100.0), (998.85, 1122.02)),
            ((1.0, 2.0), (0.99, 2.0)),
            ((3.0, 4.0), (2.98, 5.01)),
            ((2.0, 2.1), (2.0, 2.14)),
            ((0.0, 5.0), (0.05, 5.0))
        )

        for data_in, data_out in test_ranges:
            with self.subTest(data_in=data_in, data_out=data_out):
                data = numpy.linspace(data_in[0], data_in[1], 100, endpoint=False)
                data_style = "log"
                xdata = DataAndMetadata.new_data_and_metadata(data)
                calibrated_data_min, calibrated_data_max, y_ticker = LineGraphCanvasItem.calculate_y_axis([xdata], None, None, data_style)
                axes = LineGraphCanvasItem.LineGraphAxes(1.0, calibrated_data_min, calibrated_data_max, 0, 100, None, None, data_style, y_ticker)
                self.assertAlmostEqual(axes.uncalibrated_data_min, data_out[0], places=1)
                self.assertAlmostEqual(axes.uncalibrated_data_max, data_out[1], places=1)
                calibrated_data = axes.calculate_calibrated_xdata(DataAndMetadata.new_data_and_metadata(data)).data
                assert calibrated_data is not None
                data[data <= 0] = numpy.nan
                self.assertAlmostEqual(numpy.nanmin(calibrated_data), math.log10(numpy.nanmin(data)))
                self.assertAlmostEqual(numpy.nanmax(calibrated_data), math.log10(numpy.nanmax(data)))

    def test_display_limits_are_reasonable_when_using_calibrated_log_scale(self):

        test_ranges = (
            ((-0.1, 11.0), (2.6, 52.5)),
            ((1000.0, 1100.0), (998.9, 1121.9)),
            ((1.0, 2.0), (2.5, 12.5)),
            ((3.0, 4.0), (3.0, 4.0)),
            ((2.0, 2.1), (2.5, 12.5)),
            ((0.0, 5.0), (2.5, 7.5))
        )

        for data_in, data_out in test_ranges:
            with self.subTest(data_in=data_in, data_out=data_out):
                data = numpy.linspace(data_in[0], data_in[1], 100, endpoint=False)
                intensity_calibration = Calibration.Calibration(-5, 2)
                data_style = "log"
                xdata = DataAndMetadata.new_data_and_metadata(data, intensity_calibration=intensity_calibration)
                calibrated_data_min, calibrated_data_max, y_ticker = LineGraphCanvasItem.calculate_y_axis([xdata], None, None, data_style)
                axes = LineGraphCanvasItem.LineGraphAxes(1.0, calibrated_data_min, calibrated_data_max, 0, 100, None, intensity_calibration, data_style, y_ticker)
                self.assertAlmostEqual(axes.uncalibrated_data_min, data_out[0], places=1)
                self.assertAlmostEqual(axes.uncalibrated_data_max, data_out[1], places=1)
                calibrated_data = axes.calculate_calibrated_xdata(DataAndMetadata.new_data_and_metadata(data)).data
                assert calibrated_data is not None
                data[data <= 0] = numpy.nan
                self.assertAlmostEqual(numpy.nanmin(calibrated_data), math.log10(numpy.nanmin(data)))
                self.assertAlmostEqual(numpy.nanmax(calibrated_data), math.log10(numpy.nanmax(data)))

    def test_line_plot_with_log_scale_displays_integers(self):
        data = numpy.array([1,2,3], dtype=int)
        data_style = "log"
        xdata = DataAndMetadata.new_data_and_metadata(data)
        # at some point, calculate_y_axis failed to return without exception when the data type was int.
        # so the main point of this test is to ensure that the function returns without exception.
        calibrated_data_min, calibrated_data_max, y_ticker = LineGraphCanvasItem.calculate_y_axis([xdata], None, None, data_style)
        # the asserts below are a sanity check to ensure that the function is returning reasonable values.
        # note: these are calibrated values for the AXES not the original data. furthermore they will be log10.
        # so checking that the first value is negative (original axes value is less than 1), and the second value
        # is positive (original axes value is greater than 1) is a reasonable check.
        self.assertLess(calibrated_data_min, 0.0)
        self.assertGreater(calibrated_data_max, 0.0)

    def test_graph_segments_are_calculated_correctly_with_nans(self):
        # this was a bug in the original implementation
        data = numpy.zeros((16,))
        data[0] = numpy.nan
        data[1] = 1
        data[2] = numpy.nan
        data[3:] = range(3,16,1)
        segments, baseline = LineGraphCanvasItem.calculate_line_graph(
            100, 32, 0, 0, DataAndMetadata.new_data_and_metadata(data),
            0, 16, 0, 16, Calibration.Calibration(), None, "linear"
        )
        self.assertEqual(2, len(segments))
        # make a rough check to ensure that the first segment is minimal; and the second one has some content.
        self.assertLess(len(segments[0].path.commands), 8)
        self.assertGreater(len(segments[1].path.commands), 8)

    def test_tool_returns_to_pointer_after_but_not_during_creating_interval(self):
        # setup
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((100,)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
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
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((100,)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
            # test
            document_controller.tool_mode = "pointer"
            display_panel.display_canvas_item.simulate_drag((240, 160), (240, 480))
            interval_region = display_item.graphics[0]
            self.assertEqual(interval_region.type, "interval-graphic")
            self.assertTrue(interval_region.end > interval_region.start)

    def test_pointer_tool_makes_intervals_when_other_intervals_exist(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((100,)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.IntervalGraphic()
            region.start = 0.9
            region.end = 0.95
            display_item.add_graphic(region)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
            # test
            document_controller.tool_mode = "pointer"
            display_panel.display_canvas_item.simulate_drag((240, 160), (240, 480))
            interval_region = display_item.graphics[1]
            self.assertEqual(interval_region.type, "interval-graphic")
            self.assertTrue(interval_region.end > interval_region.start)

    def test_nudge_interval(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data_item = DataItem.DataItem(numpy.zeros((100,)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            region = Graphics.IntervalGraphic()
            region.start = 0.1
            region.end = 0.9
            display_item.add_graphic(region)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
            # test
            document_controller.tool_mode = "pointer"
            display_panel.display_canvas_item.simulate_click((240, 320))
            display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self.app.ui).create_key_by_id("left"))
            interval_region = display_item.graphics[0]
            self.assertTrue(interval_region.start < 0.1)
            self.assertTrue(interval_region.end < 0.9)
            self.assertAlmostEqual(interval_region.end - interval_region.start, 0.8)

    def test_line_plot_auto_scales_uncalibrated_y_axis(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data = numpy.zeros((100,))
            data[50] = 75
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
            axes = display_panel.display_canvas_item._axes
            self.assertAlmostEqual(axes.calibrated_data_min, 0.0)
            self.assertAlmostEqual(axes.calibrated_data_max, 80.0)
            self.assertAlmostEqual(axes.uncalibrated_data_min, 0.0)
            self.assertAlmostEqual(axes.uncalibrated_data_max, 80.0)

    def test_line_plot_auto_scales_calibrated_y_axis(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data = numpy.zeros((10,))
            data[5] = 75
            data_item = DataItem.DataItem(data)
            data_item.set_xdata(DataAndMetadata.new_data_and_metadata(data, Calibration.Calibration(0, 0.5, "x")))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
            axes = display_panel.display_canvas_item._axes
            self.assertAlmostEqual(axes.calibrated_data_min, 0.0)
            self.assertAlmostEqual(axes.calibrated_data_max, 40.0)
            self.assertAlmostEqual(axes.uncalibrated_data_min, 0.0)
            self.assertAlmostEqual(axes.uncalibrated_data_max, 80.0)

    def test_line_plot_handle_calibrated_x_axis_with_negative_scale(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data = numpy.random.randn(100)
            data_item = DataItem.DataItem(data)
            data_item.set_xdata(DataAndMetadata.new_data_and_metadata(data, dimensional_calibrations=[Calibration.Calibration(0, -1.0, "e")]))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
            axes = display_panel.display_canvas_item._axes
            drawing_context = DrawingContext.DrawingContext()
            line_graph_layer = LineGraphCanvasItem.LineGraphLayer(data_item.xdata, Color.Color("black"), Color.Color("black"), None)
            line_graph_layer.set_axes(axes)
            line_graph_layer.calculate(Geometry.IntRect.from_tlbr(0, 0, 480, 640))
            line_graph_layer.draw_fills(drawing_context)
            line_graph_layer.draw_strokes(drawing_context)
            # ensure that the drawing commands are sufficiently populated to have drawn the graph
            self.assertGreater(len(drawing_context.commands), 100)

    def test_line_plot_handles_data_below_one_in_log_scale(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data = numpy.random.rand(100)
            data_item = DataItem.DataItem(data)
            data_item.set_xdata(DataAndMetadata.new_data_and_metadata(data))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.set_display_property("y_style", "log")
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
            axes = display_panel.display_canvas_item._axes
            self.assertEqual(axes.data_style, "log")
            drawing_context = DrawingContext.DrawingContext()
            line_graph_layer = LineGraphCanvasItem.LineGraphLayer(data_item.xdata, Color.Color("black"), Color.Color("black"), None)
            line_graph_layer.set_axes(axes)
            line_graph_layer.calculate(Geometry.IntRect.from_tlbr(0, 0, 480, 640))
            line_graph_layer.draw_fills(drawing_context)
            line_graph_layer.draw_strokes(drawing_context)
            # ensure that the drawing commands are sufficiently populated to have drawn the graph
            self.assertGreater(len(drawing_context.commands), 100)

    def test_line_plot_with_no_data_displays_gracefully(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8,), float))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.data_item._force_unload()
            display_item.display_type = "line_plot"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))

    def test_line_plot_calculates_calibrated_vs_uncalibrated_display_y_values(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(numpy.ones((8, )), intensity_calibration=Calibration.Calibration(offset=0, scale=10, units="nm")))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
            self.assertTrue(numpy.array_equal(display_panel.display_canvas_item.line_graph_layers_canvas_item.calibrated_xdata.data, numpy.full((8, ), 10)))
            display_item.intensity_calibration_style_id = "uncalibrated"
            display_panel.layout_immediate((640, 480))
            self.assertTrue(numpy.array_equal(display_panel.display_canvas_item.line_graph_layers_canvas_item.calibrated_xdata.data, numpy.ones((8, ))))

    def test_line_plot_handles_calibrated_vs_uncalibrated_display(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(numpy.ones((8, )), dimensional_calibrations=[Calibration.Calibration(offset=0, scale=10, units="nm")]))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
            self.assertEqual(display_panel.display_canvas_item.line_graph_layers_canvas_item.calibrated_xdata.dimensional_calibrations[-1].units, "nm")
            display_item.calibration_style_id = "pixels-top-left"
            display_panel.layout_immediate((640, 480))
            self.assertFalse(display_panel.display_canvas_item.line_graph_layers_canvas_item.calibrated_xdata.dimensional_calibrations[-1].units)

    def test_line_plot_with_no_data_handles_clicks(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_item = DisplayItem.DisplayItem()
            document_model.append_display_item(display_item)
            display_item.display_type = "line_plot"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
            display_panel.display_canvas_item.simulate_click((240, 16))

    def test_narrow_line_plot_with_nans_is_drawn_properly(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data = numpy.random.rand(200)
            data[0] = numpy.nan
            data_item = DataItem.DataItem(data)
            data_item.set_xdata(DataAndMetadata.new_data_and_metadata(data))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
            axes = display_panel.display_canvas_item._axes
            drawing_context = DrawingContext.DrawingContext()
            line_graph_layer = LineGraphCanvasItem.LineGraphLayer(data_item.xdata, Color.Color("black"), Color.Color("black"), None)
            line_graph_layer.set_axes(axes)
            line_graph_layer.calculate(Geometry.IntRect.from_tlbr(0, 0, 480, 640))
            line_graph_layer.draw_fills(drawing_context)
            line_graph_layer.draw_strokes(drawing_context)
            # ensure that the drawing commands are sufficiently populated to have drawn the graph
            self.assertGreater(len(drawing_context.commands), 100)

    def test_line_plot_with_many_lines_displays_gracefully(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((100,100), float))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))

    def test_line_plot_with_too_few_layers_displays_gracefully(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8,100), float))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "line_plot"
            self.assertEqual(8, len(display_item.display_layers))
            display_item.remove_display_layer(7).close()
            display_item.remove_display_layer(6).close()
            display_item.remove_display_layer(5).close()
            display_item.remove_display_layer(4).close()
            self.assertEqual(4, len(display_item.display_layers))
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))

    def test_line_plot_displays_gracefully_when_switching_layers(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8,100), float))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.layout_immediate((640, 480))
            display_item.display_type = "line_plot"
            display_panel.layout_immediate((640, 480))
            display_item.display_type = None
            display_panel.layout_immediate((640, 480))

    def test_line_plot_handles_composite_layers_when_display_type_is_line_plot(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.ones((100,), float))
            data_item2 = DataItem.DataItem(numpy.ones((100,), float))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            display_item1 = document_model.get_display_item_for_data_item(data_item1)
            display_item1.append_display_data_channel_for_data_item(data_item2)
            self.assertEqual(2, len(display_item1.display_layers))
            display_item1.display_type = "line_plot"
            self.assertEqual(2, len(display_item1.display_layers))
            display_item1.display_type = None
            self.assertEqual(2, len(display_item1.display_layers))

    def test_line_plot_width_doesnt_jitter_for_small_vertical_bounds_changes(self):
        """
        Create a line plot with data that has been shown, when dragged vertically, produces bounds with
        a reasonable distribution of different digits. Verify that the layout calclated for these bounds
        does not change for moderate sized drags.
        """
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data = numpy.sin(numpy.linspace(0, 20, 100)) * 53488.2
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)

            lp_ci = _find_first_descendant_of_type_postorder(
                display_panel,
                LinePlotCanvasItem.LinePlotCanvasItem)
            lp_graph_frame_ci = _find_first_descendant_of_type_postorder(
                display_panel,
                LineGraphCanvasItem.LineGraphFrameCanvasItem
            )
            lp_vert_axis_scale_ci = _find_first_descendant_of_type_postorder(
                display_panel,
                LineGraphCanvasItem.LineGraphVerticalAxisScaleCanvasItem
            )
            display_panel.layout_immediate((960, 1200))

            # _print_canvas_item_tree_preorder(display_panel)

            # Drag vertical axis, and force re-layout every few pixels of drag.
            # Record the distinct sizes calculate for line graph and vertical axis items.
            lp_graph_frame_ci_sizes = set()
            lp_vert_axis_scale_ci_sizes = set()

            drag_start_pos_x = lp_vert_axis_scale_ci.canvas_size.width
            drag_start_pos_y = lp_vert_axis_scale_ci.canvas_size.height // 2
            for y_offset in range(0, 30):
                lp_ci.simulate_drag(
                    (drag_start_pos_y + 2*y_offset, drag_start_pos_x),
                    (drag_start_pos_y + 2*(y_offset+1), drag_start_pos_x))

                display_panel.refresh_layout_immediate()

                lp_graph_frame_ci_sizes.add((lp_graph_frame_ci.canvas_size.width, lp_graph_frame_ci.canvas_size.height))
                lp_vert_axis_scale_ci_sizes.add((lp_vert_axis_scale_ci.canvas_size.width, lp_vert_axis_scale_ci.canvas_size.height))

            # Verify that there is only one size that the line plot grapn and vertical axis scale
            # items take during the drag, indicating that the layout is stable against small changes
            # in bounds.
            self.assertEqual(len(lp_graph_frame_ci_sizes), 1)
            self.assertEqual(len(lp_vert_axis_scale_ci_sizes), 1)

    def test_check_exponents(self):
        e = LineGraphCanvasItem.Exponenter()
        e.add_label("5e+05")
        e.add_label("6e+05")
        self.assertEqual(("5 x 10", "5"), e.used_labels("5e+05"))
        self.assertEqual(("6 x 10", "5"), e.used_labels("6e+05"))
        e = LineGraphCanvasItem.Exponenter()
        e.add_label("5e+00")
        e.add_label("6e+00")
        self.assertEqual(("5", ""), e.used_labels("5e+00"))
        self.assertEqual(("6", ""), e.used_labels("6e+00"))
        e = LineGraphCanvasItem.Exponenter()
        e.add_label("5e+00")
        e.add_label("6e+05")
        self.assertEqual(("5 x 10", "0"), e.used_labels("5e+00"))
        self.assertEqual(("6 x 10", "5"), e.used_labels("6e+05"))
        e = LineGraphCanvasItem.Exponenter()
        e.add_label("1e+02")
        e.add_label("1e+05")
        self.assertEqual(("10", "2"), e.used_labels("1e+02"))
        self.assertEqual(("10", "5"), e.used_labels("1e+05"))
        e = LineGraphCanvasItem.Exponenter()
        e.add_label("5e-02")
        e.add_label("5e+00")
        self.assertEqual(("5 x 10", "-2"), e.used_labels("5e-02"))
        self.assertEqual(("5 x 10", "0"), e.used_labels("5e+00"))
        e = LineGraphCanvasItem.Exponenter()
        e.add_label("1e-03")
        e.add_label("1e+03")
        self.assertEqual(("10", "-3"), e.used_labels("1e-03"))
        self.assertEqual(("10", "3"), e.used_labels("1e+03"))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
