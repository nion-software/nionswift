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
from nion.swift import LineGraphCanvasItem
from nion.swift import MimeTypes
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import LinePlotDisplay
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
        self._test_setup = TestContext.TestSetup()

    def tearDown(self):
        self._test_setup = typing.cast(typing.Any, None)
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
            scaled_data_min, scaled_data_max, y_ticker = LinePlotDisplay.calculate_y_axis([xdata], None, None, None)
            axes = LinePlotDisplay.LineGraphAxes(1.0, scaled_data_min, scaled_data_max, 0, 100, None, None, None, y_ticker)
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
                axis_scale_id = "log"
                xdata = DataAndMetadata.new_data_and_metadata(data)
                scaled_data_min, scaled_data_max, y_ticker = LinePlotDisplay.calculate_y_axis([xdata], None, None, axis_scale_id)
                axes = LinePlotDisplay.LineGraphAxes(1.0, scaled_data_min, scaled_data_max, 0, 100, None, None, axis_scale_id, y_ticker)
                self.assertAlmostEqual(axes.uncalibrated_data_min, data_out[0], places=1)
                self.assertAlmostEqual(axes.uncalibrated_data_max, data_out[1], places=1)
                scaled_data = axes.convert_calibrated_array_to_scaled_array(DataAndMetadata.new_data_and_metadata(data)).data
                assert scaled_data is not None
                data[data <= 0] = numpy.nan
                self.assertAlmostEqual(numpy.nanmin(scaled_data), math.log10(numpy.nanmin(data)))
                self.assertAlmostEqual(numpy.nanmax(scaled_data), math.log10(numpy.nanmax(data)))

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
                axis_scale_id = "log"
                xdata = DataAndMetadata.new_data_and_metadata(data, intensity_calibration=intensity_calibration)
                scaled_data_min, scaled_data_max, y_ticker = LinePlotDisplay.calculate_y_axis([xdata], None, None, axis_scale_id)
                axes = LinePlotDisplay.LineGraphAxes(1.0, scaled_data_min, scaled_data_max, 0, 100, None, intensity_calibration, axis_scale_id, y_ticker)
                self.assertAlmostEqual(axes.uncalibrated_data_min, data_out[0], places=1)
                self.assertAlmostEqual(axes.uncalibrated_data_max, data_out[1], places=1)
                scaled_data = axes.convert_calibrated_array_to_scaled_array(DataAndMetadata.new_data_and_metadata(data)).data
                assert scaled_data is not None
                data[data <= 0] = numpy.nan
                self.assertAlmostEqual(numpy.nanmin(scaled_data), math.log10(numpy.nanmin(data)))
                self.assertAlmostEqual(numpy.nanmax(scaled_data), math.log10(numpy.nanmax(data)))

    def test_line_plot_with_negative_lower_display_limit_in_log_scale_displays_reasonable_limits(self):
        # tests that entering a invalid lower display limit (negative) still results in a mapped calibrated data limits.
        data = numpy.linspace(0, 10, 100, endpoint=False)
        intensity_calibration = Calibration.Calibration()
        xdata = DataAndMetadata.new_data_and_metadata(data, intensity_calibration=intensity_calibration)
        scaled_data_min, scaled_data_max, y_ticker = LinePlotDisplay.calculate_y_axis([xdata], -2, 12, "log")
        # the mapped calibrated data min should be 0.0 (a reasonable value for negative data)
        # the unmapped mapped calibrated data max should match the upper display limit (12).
        self.assertAlmostEqual(0.0, scaled_data_min)
        self.assertAlmostEqual(12.0, math.pow(10, scaled_data_max))

    def test_line_plot_with_log_scale_displays_integers(self):
        data = numpy.array([1,2,3], dtype=int)
        axis_scale_id = "log"
        xdata = DataAndMetadata.new_data_and_metadata(data)
        # at some point, calculate_y_axis failed to return without exception when the data type was int.
        # so the main point of this test is to ensure that the function returns without exception.
        scaled_data_min, scaled_data_max, y_ticker = LinePlotDisplay.calculate_y_axis([xdata], None, None, axis_scale_id)
        # the asserts below are a sanity check to ensure that the function is returning reasonable values.
        # note: these are calibrated values for the AXES not the original data. furthermore they will be log10.
        # so checking that the first value is negative (original axes value is less than 1), and the second value
        # is positive (original axes value is greater than 1) is a reasonable check.
        self.assertLess(scaled_data_min, 0.0)
        self.assertGreater(scaled_data_max, 0.0)

    def test_graph_segments_are_calculated_correctly_with_nans(self):
        # this was a bug in the original implementation
        data = numpy.zeros((16,))
        data[0] = numpy.nan
        data[1] = 1
        data[2] = numpy.nan
        data[3:] = range(3,16,1)
        plot_points = LineGraphCanvasItem.calculate_step_plot_points(
            100, 32, 0, 0, DataAndMetadata.new_data_and_metadata(data),
            0, 16, 0, 16, LinePlotDisplay._get_axis_scale("linear")
        )
        # each channel is two pixels wide, so the channel between the NaNs gives a run of two pixels.
        self.assertEqual([(2, 4), (6, 32)], [(run.starts[0], run.ends[-1]) for run in plot_points.runs])

    def test_plot_points_are_at_the_centers_of_channels_wider_than_a_pixel(self):
        # four values across 400 pixels give channels 100 pixels wide.
        plot_points = LineGraphCanvasItem.calculate_channel_plot_points(
            100, 400, 0, 0, DataAndMetadata.new_data_and_metadata(numpy.array([0.0, 1.0, 2.0, 3.0])),
            0, 4, 0, 4, LinePlotDisplay._get_axis_scale("linear"))
        self.assertEqual(100, plot_points.baseline)
        self.assertEqual([[(0, 50, 100, 100), (100, 150, 200, 75), (200, 250, 300, 50), (300, 350, 400, 25)]],
                         [list(zip(run.starts, run.xs, run.ends, run.ys)) for run in plot_points.runs])

    def test_plot_points_of_channels_narrower_than_a_pixel_are_one_for_each_pixel(self):
        plot_points = LineGraphCanvasItem.calculate_channel_plot_points(
            100, 100, 0, 0, DataAndMetadata.new_data_and_metadata(numpy.linspace(0.0, 1.0, 1000)),
            0, 1, 0, 1000, LinePlotDisplay._get_axis_scale("linear"))
        self.assertEqual([(100, 0, 100)], [(len(run.ys), run.starts[0], run.ends[-1]) for run in plot_points.runs])

    def test_plot_points_are_split_where_a_value_is_nan_or_infinite(self):
        plot_points = LineGraphCanvasItem.calculate_channel_plot_points(
            100, 500, 0, 0, DataAndMetadata.new_data_and_metadata(numpy.array([0.0, numpy.nan, 2.0, numpy.inf, 4.0])),
            0, 4, 0, 5, LinePlotDisplay._get_axis_scale("linear"))
        self.assertEqual([[50], [250], [450]], [list(run.xs) for run in plot_points.runs])

    def test_plot_points_of_a_zoomed_view_include_the_channel_beyond_each_edge(self):
        # the view of channels 1.3 to 2.7 across 140 pixels gives channels 100 pixels wide.
        plot_points = LineGraphCanvasItem.calculate_channel_plot_points(
            100, 140, 0, 0, DataAndMetadata.new_data_and_metadata(numpy.array([0.0, 1.0, 2.0, 3.0])),
            0, 4, 1.3, 2.7, LinePlotDisplay._get_axis_scale("linear"))
        self.assertEqual([[-80, 20, 120, 220]], [[round(x) for x in run.xs] for run in plot_points.runs])

    def test_line_plot_draws_values_it_does_not_know_as_defaults(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            document_model.append_data_item(DataItem.DataItem(numpy.arange(8.0)))
            display_item = document_model.display_items[0]
            display_layer = display_item.display_layers[0]
            display_layer.plot_kind = "spline"
            display_layer.marker_shape = "star"
            display_layer.marker_size = 0.0
            display_layer.stroke_dash = "dash_dot"
            line_graph_layer = LinePlotDisplay.LinePlotDisplayInfo(display_item.display_info).line_graph_layers[0]
            self.assertEqual(("step", "none", 6.0, "solid"), (line_graph_layer.plot_kind, line_graph_layer.marker_shape, line_graph_layer.marker_size, line_graph_layer.stroke_dash))
            display_layer.marker_size = math.inf
            self.assertEqual(6.0, LinePlotDisplay.LinePlotDisplayInfo(display_item.display_info).line_graph_layers[0].marker_size)

    def test_plot_points_of_data_with_a_negative_calibration_scale_are_in_channel_order(self):
        # the axes count the calibrated values down from 4, and draw the channels from left to right, as the steps do.
        calibration = Calibration.Calibration(4.0, -1.0, "eV")
        xdata = DataAndMetadata.new_data_and_metadata(numpy.array([0.0, 1.0, 2.0, 3.0]), dimensional_calibrations=[calibration])
        scaled_data_min, scaled_data_max, y_ticker = LinePlotDisplay.calculate_y_axis([xdata], None, None, None)
        axes = LinePlotDisplay.LineGraphAxes(1.0, scaled_data_min, scaled_data_max, 0, 4, calibration, None, None, y_ticker)
        scaled_xdata = LineGraphCanvasItem.MappedCalibratedDataAndMetadataCacheItem(xdata, axes).calculate()
        run = LineGraphCanvasItem.ChannelPlotPointsCacheItem(scaled_xdata, axes, Geometry.IntRect.from_tlbr(0, 0, 100, 401)).calculate().runs[0]
        self.assertEqual(([50, 150, 250, 350], sorted(run.ys, reverse=True)), (list(run.xs), list(run.ys)))

    def test_plot_points_of_a_view_deep_inside_a_channel_put_its_center_at_its_place(self):
        # a view a ten-billionth of a channel wide, centered in channel 10, puts that channel's edges far outside the plot.
        plot_points = LineGraphCanvasItem.calculate_channel_plot_points(
            100, 400, 0, 0, DataAndMetadata.new_data_and_metadata(numpy.arange(24.0)),
            0, 24, 10.5 - 0.5e-10, 10.5 + 0.5e-10, LinePlotDisplay._get_axis_scale("linear"))
        run = plot_points.runs[0]
        self.assertAlmostEqual(200, run.xs[1], places=2)
        self.assertTrue(run.starts[1] < 0 and run.ends[1] > 400)

    def test_plot_points_outside_the_value_range_keep_their_height(self):
        # a value of 100 on an axis to 1 is 99 plot heights above the top, and the drawing clips it.
        plot_points = LineGraphCanvasItem.calculate_channel_plot_points(
            100, 400, 0, 0, DataAndMetadata.new_data_and_metadata(numpy.array([0.0, 100.0])),
            0, 1, 0, 2, LinePlotDisplay._get_axis_scale("linear"))
        self.assertEqual([[100, -9900]], [list(run.ys) for run in plot_points.runs])

    def test_line_graph_layer_follows_changes_to_its_display_layer_plot_kind_and_style(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.arange(8.0))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.update_canvas_items()
            display_layer = display_item.display_layers[0]
            line_graph_layers_canvas_item = display_panel.display_canvas_item.line_graph_layers_canvas_item
            # change one property at a time, so that the drawn layer follows each one only if the layer compares it.
            for name, value in (("plot_kind", "line"), ("marker_shape", "circle"), ("marker_size", 4.0), ("stroke_dash", "dashed")):
                setattr(display_layer, name, value)
                display_panel.display_canvas_item.update_canvas_items()
                line_graph_layers = [typing.cast(LineGraphCanvasItem.LineGraphLayerCanvasItem, canvas_item)._line_graph_layer_for_testing for canvas_item in line_graph_layers_canvas_item.canvas_items]
                self.assertEqual({value}, {getattr(line_graph_layer, name) for line_graph_layer in line_graph_layers if line_graph_layer}, name)

    def test_dragging_a_layer_without_a_fill_color_onto_another_legend_shows_it_there(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            source_data_item = DataItem.DataItem(numpy.arange(8.0))
            target_data_item = DataItem.DataItem(numpy.ones((8,)))
            document_model.append_data_item(source_data_item)
            document_model.append_data_item(target_data_item)
            source_display_item = document_model.get_display_item_for_data_item(source_data_item)
            source_display_item.display_layers[0].fill_color = None
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(document_model.get_display_item_for_data_item(target_data_item))
            display_panel.display_canvas_item.update_canvas_items()
            # the legend puts the layer's legend entry into the mime data when the drag starts.
            mime_data = TestUI.MimeData()
            legend_entry = LinePlotDisplay.LinePlotDisplayInfo(source_display_item.display_info).legend_entries[0]
            MimeTypes.mime_data_put_layer(mime_data, 0, source_display_item, legend_entry.label, legend_entry.fill_color, legend_entry.stroke_color)
            legend_canvas_item = display_panel.display_canvas_item._line_graph_legend_canvas_item_for_testing
            self.assertEqual("move", legend_canvas_item.drag_enter(mime_data))

    def test_step_plot_of_a_view_starting_partway_into_a_channel_draws_each_channel_at_its_place(self):
        # the view of channels 2.5 to 22.5 across 400 pixels gives channels 20 pixels wide, so channel 3 starts at pixel 10.
        plot_points = LineGraphCanvasItem.calculate_step_plot_points(
            100, 400, 0, 0, DataAndMetadata.new_data_and_metadata(numpy.arange(24.0)),
            0, 24, 2.5, 22.5, LinePlotDisplay._get_axis_scale("linear"))
        run = plot_points.runs[0]
        steps = [start for start, last_y, y in zip(run.starts[1:], run.ys, run.ys[1:]) if y != last_y]
        self.assertEqual((0, [10, 30, 50], 400), (run.starts[0], steps[:3], run.ends[-1]))

    def test_step_plot_of_more_channels_than_pixels_averages_the_channels_under_each_pixel(self):
        # the view of channels 0.5 to 800.5 across 400 pixels puts two channels under each pixel, and the data is the
        # channel index, so a pixel's value lies between the first and last channel under it.
        plot_points = LineGraphCanvasItem.calculate_step_plot_points(
            100, 400, 0, 0, DataAndMetadata.new_data_and_metadata(numpy.arange(1600.0)),
            0, 1600, 0.5, 800.5, LinePlotDisplay._get_axis_scale("linear"))
        run = plot_points.runs[0]
        first_value, last_value = ((100 - y) * 16 for y in (run.ys[0], run.ys[-1]))
        self.assertEqual((0, 400), (run.starts[0], run.ends[-1]))
        self.assertTrue(0 <= first_value <= 2.5 and 798 <= last_value <= 800.5, (first_value, last_value))

    def test_step_plot_of_data_with_a_large_calibration_offset_draws_each_channel_at_its_place(self):
        # converting a view edge to a calibrated value and back to a channel isn't exact with a large offset.
        calibration = Calibration.Calibration(5e5, 1e-5, "s")
        xdata = DataAndMetadata.new_data_and_metadata(numpy.arange(24.0), dimensional_calibrations=[calibration])
        scaled_data_min, scaled_data_max, y_ticker = LinePlotDisplay.calculate_y_axis([xdata], None, None, None)
        axes = LinePlotDisplay.LineGraphAxes(1.0, scaled_data_min, scaled_data_max, 0, 24, calibration, None, None, y_ticker)
        scaled_xdata = LineGraphCanvasItem.MappedCalibratedDataAndMetadataCacheItem(xdata, axes).calculate()
        run = LineGraphCanvasItem.StepPlotPointsCacheItem(scaled_xdata, axes, Geometry.IntRect.from_tlbr(0, 0, 100, 401)).calculate().runs[0]
        steps = [start for start, last_y, y in zip(run.starts[1:], run.ys, run.ys[1:]) if y != last_y]
        # 24 channels across 400 pixels end at 400, and channels 22 and 23 start at 366.7 and 383.3.
        self.assertEqual((0, 400, [367, 384]), (run.starts[0], run.ends[-1], steps[-2:]))

    def test_step_plot_of_a_view_within_one_channel_draws_the_channel_across_the_plot(self):
        plot_points = LineGraphCanvasItem.calculate_step_plot_points(
            100, 400, 0, 0, DataAndMetadata.new_data_and_metadata(numpy.arange(24.0)),
            0, 24, 11.2, 11.20001, LinePlotDisplay._get_axis_scale("linear"))
        self.assertEqual([(0, 400, {100 - 100 * 11 / 24})], [(run.starts[0], run.ends[-1], set(run.ys)) for run in plot_points.runs])

    def test_step_plot_of_a_view_with_a_subnormal_width_draws_its_channel_across_the_plot(self):
        plot_points = LineGraphCanvasItem.calculate_step_plot_points(
            100, 400, 0, 0, DataAndMetadata.new_data_and_metadata(numpy.arange(24.0)),
            0, 24, 0.0, 1e-310, LinePlotDisplay._get_axis_scale("linear"))
        self.assertEqual([(0, 400, {100.0})], [(run.starts[0], run.ends[-1], set(run.ys)) for run in plot_points.runs])

    def test_layers_draw_every_fill_then_every_stroke_then_every_marker(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.arange(8.0))
            data_item2 = DataItem.DataItem(numpy.ones((8,)))
            document_model.append_data_item(data_item)
            document_model.append_data_item(data_item2, False)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.append_display_data_channel_for_data_item(data_item2)
            display_panel = document_controller.selected_display_panel
            display_panel.set_display_panel_display_item(display_item)
            display_panel.display_canvas_item.update_canvas_items()
            line_graph_layers_canvas_item = display_panel.display_canvas_item.line_graph_layers_canvas_item
            parts = [typing.cast(LineGraphCanvasItem.LineGraphLayerCanvasItem, canvas_item)._part_for_testing for canvas_item in line_graph_layers_canvas_item.canvas_items]
            self.assertEqual([LineGraphCanvasItem.LineGraphLayerPart.FILL] * 2 + [LineGraphCanvasItem.LineGraphLayerPart.STROKE] * 2 + [LineGraphCanvasItem.LineGraphLayerPart.MARKERS] * 2, parts)

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
            display_panel._handle_key_pressed(typing.cast(TestUI.UserInterface, self._test_setup.app.ui).create_key_by_id("left"))
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
            axes = display_panel.display_canvas_item._axes_for_testing
            self.assertAlmostEqual(axes.scaled_data_min, 0.0)
            self.assertAlmostEqual(axes.scaled_data_max, 80.0)
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
            axes = display_panel.display_canvas_item._axes_for_testing
            self.assertAlmostEqual(axes.scaled_data_min, 0.0)
            self.assertAlmostEqual(axes.scaled_data_max, 40.0)
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
            axes = display_panel.display_canvas_item._axes_for_testing
            drawing_context = DrawingContext.DrawingContext()
            line_graph_layer = LinePlotDisplay.LineGraphLayer(data_item.xdata, axes, Color.Color("black"), Color.Color("black"), None)
            canvas_bounds = Geometry.IntRect.from_tlbr(0, 0, 480, 640)
            composer_cache = CanvasItem.ComposerCache()
            LineGraphCanvasItem.draw_fills(line_graph_layer, drawing_context, canvas_bounds, composer_cache)
            LineGraphCanvasItem.draw_strokes(line_graph_layer, drawing_context, canvas_bounds, composer_cache, display_panel.display_canvas_item.drawing_metrics)
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
            axes = display_panel.display_canvas_item._axes_for_testing
            self.assertEqual(axes.axis_scale.axis_scale_id, "log")
            drawing_context = DrawingContext.DrawingContext()
            line_graph_layer = LinePlotDisplay.LineGraphLayer(data_item.xdata, axes, Color.Color("black"), Color.Color("black"), None)
            canvas_bounds = Geometry.IntRect.from_tlbr(0, 0, 480, 640)
            composer_cache = CanvasItem.ComposerCache()
            LineGraphCanvasItem.draw_fills(line_graph_layer, drawing_context, canvas_bounds, composer_cache)
            LineGraphCanvasItem.draw_strokes(line_graph_layer, drawing_context, canvas_bounds, composer_cache, display_panel.display_canvas_item.drawing_metrics)
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
            self.assertTrue(numpy.array_equal(display_panel.display_canvas_item.line_graph_layers_canvas_item._scaled_xdata_for_testing.data, numpy.full((8, ), 10)))
            display_item.intensity_calibration_style_id = "uncalibrated"
            display_panel.layout_immediate((640, 480))
            self.assertTrue(numpy.array_equal(display_panel.display_canvas_item.line_graph_layers_canvas_item._scaled_xdata_for_testing.data, numpy.ones((8, ))))

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
            self.assertEqual(display_panel.display_canvas_item.line_graph_layers_canvas_item._scaled_xdata_for_testing.dimensional_calibrations[-1].units, "nm")
            display_item.calibration_style_id = "pixels-top-left"
            display_panel.layout_immediate((640, 480))
            self.assertFalse(display_panel.display_canvas_item.line_graph_layers_canvas_item._scaled_xdata_for_testing.dimensional_calibrations[-1].units)

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
            axes = display_panel.display_canvas_item._axes_for_testing
            drawing_context = DrawingContext.DrawingContext()
            line_graph_layer = LinePlotDisplay.LineGraphLayer(data_item.xdata, axes, Color.Color("black"), Color.Color("black"), None)
            canvas_bounds = Geometry.IntRect.from_tlbr(0, 0, 480, 640)
            composer_cache = CanvasItem.ComposerCache()
            LineGraphCanvasItem.draw_fills(line_graph_layer, drawing_context, canvas_bounds, composer_cache)
            LineGraphCanvasItem.draw_strokes(line_graph_layer, drawing_context, canvas_bounds, composer_cache, display_panel.display_canvas_item.drawing_metrics)
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
        # Create a line plot with data that has been shown, when dragged vertically, produces bounds with a
        # reasonable distribution of different digits. Verify that the layout calclated for these bounds does not
        # change for moderate sized drags.
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            data = numpy.sin(numpy.linspace(0, 20, 100)) * 53488.2
            data_item = DataItem.DataItem(data)
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)

            display_panel.layout_immediate((960, 1200))

            lp_ci = display_panel.display_canvas_item
            lp_graph_frame_ci = _find_first_descendant_of_type_postorder(
                display_panel.display_canvas_item,
                LineGraphCanvasItem.LineGraphFrameCanvasItem
            )
            lp_vert_axis_scale_ci = _find_first_descendant_of_type_postorder(
                display_panel.display_canvas_item,
                LineGraphCanvasItem.LineGraphVerticalAxisScaleCanvasItem
            )

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

    # test rgb 1d data in line plot.
    def test_line_plot_handles_rgb_1d(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            display_panel = document_controller.selected_display_panel
            # rgb 1d
            data_item = DataItem.DataItem(numpy.zeros((8, 4), numpy.uint8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_panel.set_display_panel_display_item(display_item)
            display_panel.repaint_immediate(DrawingContext.DrawingContext(), Geometry.IntSize(100, 100))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
