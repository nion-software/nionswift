"""
    A collection of classes facilitating drawing line graphs.

    Several canvas items including the line graph itself, and tick marks, scale,
    and label are also available. All canvas items except for the canvas item
    are auto sizing in the appropriate direction. Canvas items are meant to be
    combined into a grid layout with the line graph.
"""

# standard libraries
import gettext
import json
import math
import typing

# third party libraries
import uuid

import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift import Inspector
from nion.swift import MimeTypes
from nion.swift import Undo
from nion.swift.model import DisplayItem
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.utils import Geometry

_ = gettext.gettext


def nice_label(value: float, precision: int) -> str:
    if math.trunc(math.log10(abs(value) + numpy.nextafter(0,1))) > 4:
        return (u"{0:0." + u"{0:d}".format(precision) + "e}").format(value)
    else:
        return (u"{0:0." + u"{0:d}".format(precision) + "f}").format(value)


def calculate_y_axis(uncalibrated_data_list, data_min, data_max, y_calibration, data_style):
    y_calibration = y_calibration if y_calibration else Calibration.Calibration()

    min_specified = data_min is not None
    max_specified = data_max is not None

    if min_specified:
        uncalibrated_data_min = data_min
    else:
        uncalibrated_data_min = None
        for uncalibrated_data in uncalibrated_data_list:
            if uncalibrated_data is not None and uncalibrated_data.shape[-1] > 0:
                partial_uncalibrated_data_min = numpy.amin(uncalibrated_data)
                if uncalibrated_data_min is not None:
                    uncalibrated_data_min = min(uncalibrated_data_min, partial_uncalibrated_data_min)
                else:
                    uncalibrated_data_min = partial_uncalibrated_data_min
        if uncalibrated_data_min is None:
            uncalibrated_data_min = 0.0

    if max_specified:
        uncalibrated_data_max = data_max
    else:
        uncalibrated_data_max = None
        for uncalibrated_data in uncalibrated_data_list:
            if uncalibrated_data is not None and uncalibrated_data.shape[-1] > 0:
                partial_uncalibrated_data_max = numpy.amax(uncalibrated_data)
                if uncalibrated_data_max is not None:
                    uncalibrated_data_max = max(uncalibrated_data_max, partial_uncalibrated_data_max)
                else:
                    uncalibrated_data_max = partial_uncalibrated_data_max
        if uncalibrated_data_max is None:
            uncalibrated_data_max = 0.0

    calibrated_data_min = y_calibration.convert_to_calibrated_value(uncalibrated_data_min)
    calibrated_data_max = y_calibration.convert_to_calibrated_value(uncalibrated_data_max)

    if data_style == "log":
        calibrated_data_min = math.log10(max(calibrated_data_min, 1.0))
        calibrated_data_max = math.log10(max(calibrated_data_max, 1.0))

    if math.isnan(calibrated_data_min) or math.isnan(calibrated_data_max) or math.isinf(calibrated_data_min) or math.isinf(calibrated_data_max):
        calibrated_data_min = 0.0
        calibrated_data_max = 0.0

    calibrated_data_min, calibrated_data_max = min(calibrated_data_min, calibrated_data_max), max(calibrated_data_min, calibrated_data_max)
    calibrated_data_min = 0.0 if calibrated_data_min > 0 and not min_specified else calibrated_data_min
    calibrated_data_max = 0.0 if calibrated_data_max < 0 and not max_specified else calibrated_data_max

    logarithmic = data_style == "log"
    ticker = Geometry.Ticker(calibrated_data_min, calibrated_data_max, logarithmic=logarithmic)

    if not min_specified:
        calibrated_data_min = ticker.minimum
    if not max_specified:
        calibrated_data_max = ticker.maximum

    return calibrated_data_min, calibrated_data_max, ticker


class LineGraphAxes:
    """Track information about line graph axes."""

    def __init__(self, data_scale=None, calibrated_data_min=None, calibrated_data_max=None, data_left=None, data_right=None, x_calibration=None, y_calibration=None, data_style=None, y_ticker=None):
        # these items are considered to be input items
        self.data_scale = data_scale
        self.__uncalibrated_left_channel = data_left
        self.__uncalibrated_right_channel = data_right
        self.x_calibration = x_calibration
        self.y_calibration = y_calibration
        self.data_style = data_style if data_style else "linear"
        self.__calibrated_data_min = calibrated_data_min
        self.__calibrated_data_max = calibrated_data_max
        self.__y_ticker = y_ticker

    @property
    def is_valid(self):
        return self.data_scale is not None and self.__uncalibrated_left_channel is not None and self.__uncalibrated_right_channel is not None and self.__calibrated_data_min is not None and self.__calibrated_data_max is not None

    @property
    def y_ticker(self):
        return self.__y_ticker

    @property
    def uncalibrated_data_min(self):
        y_calibration = self.y_calibration if self.y_calibration else Calibration.Calibration()
        calibrated_data_min = self.calibrated_data_min
        if self.data_style == "log":
            return y_calibration.convert_from_calibrated_value(math.pow(10, calibrated_data_min))
        else:
            return y_calibration.convert_from_calibrated_value(calibrated_data_min)

    @property
    def uncalibrated_data_max(self):
        y_calibration = self.y_calibration if self.y_calibration else Calibration.Calibration()
        calibrated_data_max = self.calibrated_data_max
        if self.data_style == "log":
            return y_calibration.convert_from_calibrated_value(math.pow(10, calibrated_data_max))
        else:
            return y_calibration.convert_from_calibrated_value(calibrated_data_max)

    @property
    def calibrated_data_min(self):
        return self.__calibrated_data_min

    @property
    def calibrated_data_max(self):
        return self.__calibrated_data_max

    @property
    def drawn_left_channel(self):
        assert self.is_valid
        return self.__uncalibrated_left_channel

    @property
    def drawn_right_channel(self):
        assert self.is_valid
        return self.__uncalibrated_right_channel

    @property
    def calibrated_left_channel(self):
        assert self.is_valid
        return self.x_calibration.convert_to_calibrated_value(self.drawn_left_channel)

    @property
    def calibrated_right_channel(self):
        assert self.is_valid
        return self.x_calibration.convert_to_calibrated_value(self.drawn_right_channel)

    def calculate_y_ticks(self, plot_height):
        """Calculate the y-axis items dependent on the plot height."""

        calibrated_data_min = self.calibrated_data_min
        calibrated_data_max = self.calibrated_data_max
        calibrated_data_range = calibrated_data_max - calibrated_data_min

        ticker = self.y_ticker
        y_ticks = list()
        for tick_value, tick_label in zip(ticker.values, ticker.labels):
            if calibrated_data_range != 0.0:
                y_tick = plot_height - plot_height * (tick_value - calibrated_data_min) / calibrated_data_range
            else:
                y_tick = plot_height - plot_height * 0.5
            if y_tick >= 0 and y_tick <= plot_height:
                y_ticks.append((y_tick, tick_label))

        return y_ticks

    def uncalibrate_y(self, calibrated_y_value):
        y_calibration = self.y_calibration
        if self.data_style == "log":
            if y_calibration:
                return y_calibration.convert_from_calibrated_value(math.pow(10, calibrated_y_value))
            else:
                return math.pow(10, calibrated_y_value)
        else:
            if y_calibration:
                return y_calibration.convert_from_calibrated_value(calibrated_y_value)
            else:
                return calibrated_y_value

    def calculate_x_ticks(self, plot_width):
        """Calculate the x-axis items dependent on the plot width."""

        x_calibration = self.x_calibration

        uncalibrated_data_left = self.__uncalibrated_left_channel
        uncalibrated_data_right = self.__uncalibrated_right_channel

        calibrated_data_left = x_calibration.convert_to_calibrated_value(uncalibrated_data_left) if x_calibration is not None else uncalibrated_data_left
        calibrated_data_right = x_calibration.convert_to_calibrated_value(uncalibrated_data_right) if x_calibration is not None else uncalibrated_data_right
        calibrated_data_left, calibrated_data_right = min(calibrated_data_left, calibrated_data_right), max(calibrated_data_left, calibrated_data_right)

        graph_left, graph_right, tick_values, division, precision = Geometry.make_pretty_range(calibrated_data_left, calibrated_data_right)

        drawn_data_width = self.drawn_right_channel - self.drawn_left_channel

        x_ticks = list()
        if drawn_data_width > 0.0:
            for tick_value in tick_values:
                label = nice_label(tick_value, precision)
                data_tick = x_calibration.convert_from_calibrated_value(tick_value) if x_calibration else tick_value
                x_tick = plot_width * (data_tick - self.drawn_left_channel) / drawn_data_width
                if x_tick >= 0 and x_tick <= plot_width:
                    x_ticks.append((x_tick, label))

        return x_ticks

    def calculate_calibrated_xdata(self, uncalibrated_xdata):
        calibrated_data = None
        if uncalibrated_xdata is not None:
            y_calibration = self.y_calibration
            if y_calibration:
                if self.data_style == "log":
                    calibrated_data = numpy.log10(numpy.maximum(y_calibration.offset + y_calibration.scale * uncalibrated_xdata.data, 1.0))
                else:
                    calibrated_data = y_calibration.offset + y_calibration.scale * uncalibrated_xdata.data
            else:
                if self.data_style == "log":
                    calibrated_data = numpy.log10(numpy.maximum(uncalibrated_xdata.data, 1.0))
                else:
                    calibrated_data = uncalibrated_xdata.data
        return DataAndMetadata.new_data_and_metadata(calibrated_data, dimensional_calibrations=uncalibrated_xdata.dimensional_calibrations)


def are_axes_equal(axes1: LineGraphAxes, axes2: LineGraphAxes) -> bool:
    if (axes1 is None) != (axes2 is None):
        return False
    if axes1 is None:
        return True
    if axes1.is_valid != axes2.is_valid:
        return False
    if not axes1.is_valid:
        return True
    if axes1.drawn_left_channel != axes2.drawn_left_channel:
        return False
    if axes1.drawn_right_channel != axes2.drawn_right_channel:
        return False
    if axes1.calibrated_data_min != axes2.calibrated_data_min:
        return False
    if axes1.calibrated_data_max != axes2.calibrated_data_max:
        return False
    if axes1.x_calibration != axes2.x_calibration:
        return False
    if axes1.y_calibration != axes2.y_calibration:
        return False
    if axes1.data_style != axes2.data_style:
        return False
    return True


def draw_background(drawing_context, plot_rect, background_color):
    with drawing_context.saver():
        drawing_context.begin_path()
        drawing_context.rect(plot_rect[0][1], plot_rect[0][0], plot_rect[1][1], plot_rect[1][0])
        drawing_context.fill_style = background_color
        drawing_context.fill()


def draw_horizontal_grid_lines(drawing_context, plot_width, plot_origin_x, y_ticks):
    with drawing_context.saver():
        drawing_context.begin_path()
        for y, _ in y_ticks:
            drawing_context.move_to(plot_origin_x, y)
            drawing_context.line_to(plot_origin_x + plot_width, y)
        drawing_context.line_width = 0.5
        drawing_context.stroke_style = '#DDD'
        drawing_context.stroke()


def draw_vertical_grid_lines(drawing_context, plot_height, plot_origin_y, x_ticks):
    with drawing_context.saver():
        drawing_context.begin_path()
        for x, _ in x_ticks:
            drawing_context.move_to(x, plot_origin_y)
            drawing_context.line_to(x, plot_origin_y + plot_height)
        drawing_context.line_width = 0.5
        drawing_context.stroke_style = '#DDD'
        drawing_context.stroke()


def draw_line_graph(drawing_context, plot_height, plot_width, plot_origin_y, plot_origin_x, calibrated_xdata, calibrated_data_min, calibrated_data_range, calibrated_left_channel, calibrated_right_channel, x_calibration, fill_color: str, stroke_color: str, rebin_cache):
    # calculate how the data is displayed
    xdata_calibration = calibrated_xdata.dimensional_calibrations[-1]
    assert xdata_calibration.units == x_calibration.units
    displayed_calibrated_left_channel = max(calibrated_left_channel, xdata_calibration.convert_to_calibrated_value(0))
    displayed_calibrated_right_channel = min(calibrated_right_channel, xdata_calibration.convert_to_calibrated_value(calibrated_xdata.dimensional_shape[-1]))
    if displayed_calibrated_left_channel >= calibrated_right_channel or displayed_calibrated_right_channel <= calibrated_left_channel:
        return  # data is outside drawing area
    data_left_channel = int(xdata_calibration.convert_from_calibrated_value(displayed_calibrated_left_channel))
    data_right_channel = int(xdata_calibration.convert_from_calibrated_value(displayed_calibrated_right_channel))
    left = int((displayed_calibrated_left_channel - calibrated_left_channel) / (calibrated_right_channel - calibrated_left_channel) * plot_width + plot_origin_x)
    right = int((displayed_calibrated_right_channel - calibrated_left_channel) / (calibrated_right_channel - calibrated_left_channel) * plot_width + plot_origin_x)

    # update input parameters, then fall back to old algorithm
    plot_width = right - left
    plot_origin_x = left
    if 0 <= data_left_channel < data_right_channel and data_right_channel <= calibrated_xdata.dimensional_shape[-1]:
        calibrated_xdata = calibrated_xdata[data_left_channel:data_right_channel]
    else:
        return
    x_calibration = calibrated_xdata.dimensional_calibrations[-1]
    calibrated_left_channel = x_calibration.convert_to_calibrated_value(0)
    calibrated_right_channel = x_calibration.convert_to_calibrated_value(calibrated_xdata.dimensional_shape[-1])

    uncalibrated_left_channel = x_calibration.convert_from_calibrated_value(calibrated_left_channel)
    uncalibrated_right_channel = x_calibration.convert_from_calibrated_value(calibrated_right_channel)
    uncalibrated_width = uncalibrated_right_channel - uncalibrated_left_channel
    with drawing_context.saver():
        stroke_path = DrawingContext.DrawingContext()
        drawing_context.begin_path()
        if calibrated_data_range != 0.0 and uncalibrated_width > 0.0:
            baseline = plot_origin_y + plot_height - (plot_height * float(0.0 - calibrated_data_min) / calibrated_data_range)
            baseline = min(plot_origin_y + plot_height, baseline)
            baseline = max(plot_origin_y, baseline)
            # rebin so that uncalibrated_width corresponds to plot width
            calibrated_data = calibrated_xdata.data
            binned_length = int(calibrated_data.shape[-1] * plot_width / uncalibrated_width)
            if binned_length > 0:
                binned_data = Image.rebin_1d(calibrated_data, binned_length, rebin_cache)
                binned_left = int(uncalibrated_left_channel * plot_width / uncalibrated_width)
                # draw the plot
                last_py = baseline
                for i in range(0, plot_width):
                    px = plot_origin_x + i
                    binned_index = binned_left + i
                    data_value = binned_data[binned_index] if binned_index >= 0 and binned_index < binned_length else 0.0
                    # plot_origin_y is the TOP of the drawing
                    # py extends DOWNWARDS
                    py = plot_origin_y + plot_height - (plot_height * (data_value - calibrated_data_min) / calibrated_data_range)
                    py = max(plot_origin_y, py)
                    py = min(plot_origin_y + plot_height, py)
                    if i == 0:
                        stroke_path.move_to(px, py)
                    else:
                        # only draw horizontal lines when necessary
                        if py != last_py:
                            # draw forward from last_px to px at last_py level
                            stroke_path.line_to(px, last_py)
                            stroke_path.line_to(px, py)
                    last_py = py
                stroke_path.line_to(plot_origin_x + plot_width, last_py)
            if fill_color:
                drawing_context.add(stroke_path)
                drawing_context.line_to(plot_origin_x + plot_width, baseline)
                drawing_context.line_to(plot_origin_x, baseline)
                drawing_context.close_path()
                drawing_context.fill_style = fill_color
                drawing_context.fill()
            if stroke_color:
                drawing_context.add(stroke_path)
                drawing_context.line_width = 0.5
                drawing_context.stroke_style = stroke_color
                drawing_context.stroke()
        else:
            if fill_color or stroke_color:
                drawing_context.move_to(plot_origin_x, plot_origin_y + plot_height * 0.5)
                drawing_context.line_to(plot_origin_x + plot_width, plot_origin_y + plot_height * 0.5)
                drawing_context.line_width = 0.5
                drawing_context.stroke_style = fill_color or stroke_color
                drawing_context.stroke()


def draw_frame(drawing_context, plot_height, plot_origin_x, plot_origin_y, plot_width):
    with drawing_context.saver():
        drawing_context.begin_path()
        drawing_context.rect(plot_origin_x, plot_origin_y, plot_width, plot_height)
        drawing_context.line_width = 1
        drawing_context.stroke_style = '#888'
        drawing_context.stroke()


def draw_marker(drawing_context, p, fill=None, stroke=None):
    with drawing_context.saver():
        drawing_context.begin_path()
        drawing_context.move_to(p[1] - 3, p[0] - 3)
        drawing_context.line_to(p[1] + 3, p[0] - 3)
        drawing_context.line_to(p[1] + 3, p[0] + 3)
        drawing_context.line_to(p[1] - 3, p[0] + 3)
        drawing_context.close_path()
        if fill:
            drawing_context.fill_style = fill
            drawing_context.fill()
        if stroke:
            drawing_context.stroke_style = stroke
            drawing_context.stroke()


class LineGraphBackgroundCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot background and grid lines."""

    def __init__(self):
        super().__init__()
        self.__drawing_context = None
        self.__axes = None
        self.draw_grid = True
        self.background_color = "#FFF"

    def set_axes(self, axes):
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.update()

    def _repaint(self, drawing_context):
        # draw the data, if any
        axes = self.__axes
        if axes and axes.is_valid:
            plot_rect = self.canvas_bounds
            plot_width = int(plot_rect[1][1]) - 1
            plot_height = int(plot_rect[1][0]) - 1
            plot_origin_x = int(plot_rect[0][1])
            plot_origin_y = int(plot_rect[0][0])

            # extract the data we need for drawing axes
            y_ticks = axes.calculate_y_ticks(plot_height)
            x_ticks = axes.calculate_x_ticks(plot_width)

            draw_background(drawing_context, plot_rect, self.background_color)

            # draw the horizontal grid lines
            if self.draw_grid:
                draw_horizontal_grid_lines(drawing_context, plot_width, plot_origin_x, y_ticks)

            # draw the vertical grid lines
            if self.draw_grid:
                draw_vertical_grid_lines(drawing_context, plot_height, plot_origin_y, x_ticks)


class LineGraphCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot itself."""

    def __init__(self):
        super().__init__()
        self.__drawing_context = None
        self.__axes = None
        self.__fill_color = None
        self.__stroke_color = None
        self.__uncalibrated_xdata = None
        self.__calibrated_xdata = None
        self.__retained_rebin_1d = dict()

    def set_fill_color(self, color):
        if self.__fill_color != color:
            self.__fill_color = color
            self.update()

    def set_stroke_color(self, color):
        if self.__stroke_color != color:
            self.__stroke_color = color
            self.update()

    def set_uncalibrated_xdata(self, uncalibrated_xdata):
        if not DataAndMetadata.is_equal(uncalibrated_xdata, self.__uncalibrated_xdata):
            self.__uncalibrated_xdata = uncalibrated_xdata
            self.__calibrated_xdata = None
            self.update()

    @property
    def calibrated_xdata(self):
        if self.__calibrated_xdata is None and self.__uncalibrated_xdata is not None:
            self.__calibrated_xdata = self.__axes.calculate_calibrated_xdata(self.__uncalibrated_xdata)
        return self.__calibrated_xdata

    @property
    def _axes(self):  # for testing only
        return self.__axes

    def set_axes(self, axes):
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.__calibrated_xdata = None
            self.update()

    def _repaint(self, drawing_context):
        # draw the data, if any
        axes = self.__axes
        calibrated_xdata = self.calibrated_xdata
        stroke_color = self.__stroke_color
        fill_color = self.__fill_color
        if axes and axes.is_valid and calibrated_xdata is not None:

            plot_rect = self.canvas_bounds
            plot_width = int(plot_rect[1][1]) - 1
            plot_height = int(plot_rect[1][0]) - 1
            plot_origin_x = int(plot_rect[0][1])
            plot_origin_y = int(plot_rect[0][0])

            # extract the data we need for drawing y-axis
            calibrated_data_min = axes.calibrated_data_min
            calibrated_data_max = axes.calibrated_data_max
            calibrated_data_range = calibrated_data_max - calibrated_data_min

            # extract the data we need for drawing x-axis
            calibrated_left_channel = axes.calibrated_left_channel
            calibrated_right_channel = axes.calibrated_right_channel
            x_calibration = axes.x_calibration

            # draw the line plot itself
            if x_calibration.units == calibrated_xdata.dimensional_calibrations[-1].units:
                draw_line_graph(drawing_context, plot_height, plot_width, plot_origin_y, plot_origin_x, calibrated_xdata, calibrated_data_min, calibrated_data_range, calibrated_left_channel, calibrated_right_channel, x_calibration, fill_color, stroke_color, self.__retained_rebin_1d)


class LineGraphRegionsCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot itself."""

    def __init__(self):
        super().__init__()
        self.font_size = 12
        self.__axes = None
        self.__calibrated_data = None
        self.__regions = list()

    def set_axes(self, axes):
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.update()

    def set_calibrated_data(self, calibrated_data):
        if not numpy.array_equal(calibrated_data, self.__calibrated_data):
            self.__calibrated_data = calibrated_data
            self.update()

    def set_regions(self, regions):
        if (self.__regions is None and regions is not None) or (self.__regions != regions):
            self.__regions = regions
            self.update()

    def _repaint(self, drawing_context):

        # draw the data, if any
        axes = self.__axes
        data = self.__calibrated_data
        regions = self.__regions
        if axes and axes.is_valid:

            plot_rect = self.canvas_bounds
            plot_height = int(plot_rect[1][0]) - 1
            plot_origin_y = int(plot_rect[0][0])

            # extract the data we need for drawing y-axis
            calibrated_data_min = axes.calibrated_data_min
            calibrated_data_max = axes.calibrated_data_max
            calibrated_data_range = calibrated_data_max - calibrated_data_min

            if data is not None and len(data.shape) > 1:
                data = data[0, ...]

            data_left = axes.drawn_left_channel
            data_right = axes.drawn_right_channel

            data_scale = axes.data_scale

            if data_right <= data_left:
                return

            def convert_coordinate_to_pixel(c):
                px = c * data_scale
                return plot_rect.width * (px - data_left) / (data_right - data_left)

            canvas_width = self.canvas_size.width
            canvas_height = self.canvas_size.height

            for region in regions:
                left_channel, right_channel = region.channels
                region_selected = region.selected
                index = region.index
                level = plot_rect.bottom - plot_rect.height * 0.8 + index * 8
                with drawing_context.saver():
                    drawing_context.clip_rect(0, 0, canvas_width, canvas_height)
                    if region.style == "tag" and data is not None:
                        if calibrated_data_range != 0.0:
                            channel = (left_channel + right_channel) / 2
                            data_value = data[int(channel * data.shape[0])]
                            py = plot_origin_y + plot_height - (plot_height * (data_value - calibrated_data_min) / calibrated_data_range)
                            py = max(plot_origin_y, py)
                            py = min(plot_origin_y + plot_height, py)
                            x = convert_coordinate_to_pixel(channel)
                            with drawing_context.saver():
                                drawing_context.begin_path()
                                drawing_context.move_to(x, py - 3)
                                drawing_context.line_to(x, py - 13)
                                drawing_context.line_width = 1
                                drawing_context.stroke_style = '#F00'
                                if not region_selected:
                                    drawing_context.line_dash = 2
                                drawing_context.stroke()

                                label = region.label
                                if label:
                                    drawing_context.line_dash = 0
                                    drawing_context.fill_style = '#F00'
                                    drawing_context.font = "{0:d}px".format(self.font_size)
                                    drawing_context.text_align = "center"
                                    drawing_context.text_baseline = "bottom"
                                    drawing_context.fill_text(label, x, py - 16)

                                # drawing_context.begin_path()
                                # drawing_context.move_to(x - 3, py - 3)
                                # drawing_context.line_to(x + 2, py + 2)
                                # drawing_context.move_to(x - 3, py + 3)
                                # drawing_context.line_to(x + 2, py - 2)
                                # drawing_context.line_width = 1
                                # drawing_context.stroke_style = '#000'
                                # drawing_context.stroke()
                    else:
                        drawing_context.begin_path()

                        left = convert_coordinate_to_pixel(left_channel)
                        drawing_context.move_to(left, plot_origin_y)
                        drawing_context.line_to(left, plot_origin_y + plot_height)

                        right = convert_coordinate_to_pixel(right_channel)
                        drawing_context.move_to(right, plot_origin_y)
                        drawing_context.line_to(right, plot_origin_y + plot_height)

                        drawing_context.line_width = 1
                        drawing_context.stroke_style = '#F00'
                        if not region_selected:
                            drawing_context.line_dash = 2
                        drawing_context.stroke()

                        mid_x = (left + right) // 2
                        drawing_context.move_to(left, level)
                        drawing_context.line_to(mid_x - 3, level)
                        drawing_context.move_to(mid_x + 3, level)
                        drawing_context.line_to(right - 3, level)
                        drawing_context.stroke()
                        drawing_context.line_dash = 0
                        if region_selected:
                            draw_marker(drawing_context, (level, mid_x), fill='#F00', stroke='#F00')
                            drawing_context.fill_style = '#F00'
                            drawing_context.font = "{0:d}px".format(self.font_size)
                            left_text = region.left_text
                            right_text = region.right_text
                            middle_text = region.middle_text
                            if middle_text:
                                drawing_context.text_align = "center"
                                drawing_context.text_baseline = "bottom"
                                drawing_context.fill_text(middle_text, mid_x, level - 6)
                            if left_text:
                                drawing_context.text_align = "right"
                                drawing_context.text_baseline = "center"
                                drawing_context.fill_text(left_text, left - 4, level)
                            if right_text:
                                drawing_context.text_align = "left"
                                drawing_context.text_baseline = "center"
                                drawing_context.fill_text(right_text, right + 4, level)
                        else:
                            draw_marker(drawing_context, (level, mid_x), stroke='#F00')

                        label = region.label
                        if label:
                            drawing_context.line_dash = 0
                            drawing_context.fill_style = '#F00'
                            drawing_context.font = "{0:d}px".format(self.font_size)
                            drawing_context.text_align = "center"
                            drawing_context.text_baseline = "top"
                            drawing_context.fill_text(label, mid_x, level + 6)


class LineGraphFrameCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot frame."""

    def __init__(self):
        super().__init__()
        self.__drawing_context = None
        self.__draw_frame = True

    def set_draw_frame(self, draw_frame):
        if self.__draw_frame != draw_frame:
            self.__draw_frame = draw_frame
            self.update()

    def _repaint(self, drawing_context):
        plot_rect = self.canvas_bounds
        plot_width = int(plot_rect[1][1]) - 1
        plot_height = int(plot_rect[1][0]) - 1
        plot_origin_x = int(plot_rect[0][1])
        plot_origin_y = int(plot_rect[0][0])

        if self.__draw_frame:
            draw_frame(drawing_context, plot_height, plot_origin_x, plot_origin_y, plot_width)


class LineGraphHorizontalAxisTicksCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the horizontal tick marks."""

    def __init__(self):
        super().__init__()
        self.__axes = None
        self.tick_height = 4
        self.sizing.minimum_height = self.tick_height
        self.sizing.maximum_height = self.tick_height

    def set_axes(self, axes):
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.update()

    def _repaint(self, drawing_context):

        # draw the data, if any
        axes = self.__axes
        if axes and axes.is_valid:

            plot_width = int(self.canvas_size[1]) - 1

            # extract the data we need for drawing x-axis
            x_ticks = axes.calculate_x_ticks(plot_width)

            # draw the tick marks
            with drawing_context.saver():
                for x, _ in x_ticks:
                    drawing_context.begin_path()
                    drawing_context.move_to(x, 0)
                    drawing_context.line_to(x, self.tick_height)
                    drawing_context.line_width = 1
                    drawing_context.stroke_style = '#888'
                    drawing_context.stroke()


class LineGraphHorizontalAxisScaleCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the horizontal scale."""

    def __init__(self):
        super().__init__()
        self.__axes = None
        self.font_size = 12
        self.sizing.minimum_height = self.font_size + 4
        self.sizing.maximum_height = self.font_size + 4

    def set_axes(self, axes):
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.update()

    def _repaint(self, drawing_context):

        # draw the data, if any
        axes = self.__axes
        if axes and axes.is_valid:

            height = self.canvas_size[0]
            plot_width = int(self.canvas_size[1]) - 1

            # extract the data we need for drawing x-axis
            x_ticks = axes.calculate_x_ticks(plot_width)

            # draw the tick marks
            with drawing_context.saver():
                drawing_context.font = "{0:d}px".format(self.font_size)
                for x, label in x_ticks:
                    drawing_context.text_align = "center"
                    drawing_context.text_baseline = "middle"
                    drawing_context.fill_style = "#000"
                    drawing_context.fill_text(label, x, height * 0.5)


class LineGraphHorizontalAxisLabelCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the horizontal label."""

    def __init__(self):
        super().__init__()
        self.__axes = None
        self.font_size = 12
        self.sizing.minimum_height = self.font_size + 4
        self.sizing.maximum_height = self.font_size + 4

    def size_to_content(self):
        """ Size the canvas item to the proper height. """
        new_sizing = self.copy_sizing()
        new_sizing.minimum_height = 0
        new_sizing.maximum_height = 0
        axes = self.__axes
        if axes and axes.is_valid:
            if axes.x_calibration and axes.x_calibration.units:
                new_sizing.minimum_height = self.font_size + 4
                new_sizing.maximum_height = self.font_size + 4
        self.update_sizing(new_sizing)

    def set_axes(self, axes):
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.size_to_content()
            self.update()

    def _repaint(self, drawing_context):

        # draw the data, if any
        axes = self.__axes
        if axes and axes.is_valid:

            # draw the horizontal axis
            if axes.x_calibration and axes.x_calibration.units:

                height = self.canvas_size[0]
                plot_width = int(self.canvas_size[1]) - 1

                with drawing_context.saver():
                    drawing_context.text_align = "center"
                    drawing_context.text_baseline = "middle"
                    drawing_context.fill_style = "#000"
                    value_str = u"({0})".format(axes.x_calibration.units)
                    drawing_context.font = "{0:d}px".format(self.font_size)
                    drawing_context.fill_text(value_str, plot_width * 0.5, height * 0.5)


class LineGraphVerticalAxisTicksCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the vertical tick marks."""

    def __init__(self):
        super().__init__()
        self.__axes = None
        self.tick_width = 4
        self.sizing.minimum_width = self.tick_width
        self.sizing.maximum_width = self.tick_width

    def set_axes(self, axes):
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.update()

    def _repaint(self, drawing_context):

        # draw the data, if any
        axes = self.__axes
        if axes and axes.is_valid:

            # canvas size
            width = self.canvas_size[1]
            plot_height = int(self.canvas_size[0]) - 1

            # extract the data we need for drawing y-axis
            y_ticks = axes.calculate_y_ticks(plot_height)

            # draw the y_ticks and labels
            with drawing_context.saver():
                for y, _ in y_ticks:
                    drawing_context.begin_path()
                    drawing_context.move_to(width, y)
                    drawing_context.line_to(width - self.tick_width, y)
                    drawing_context.line_width = 1
                    drawing_context.stroke_style = '#888'
                    drawing_context.stroke()


class LineGraphVerticalAxisScaleCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the vertical scale."""

    def __init__(self):
        super().__init__()
        self.__axes = None
        self.font_size = 12

    def size_to_content(self, get_font_metrics_fn):
        """ Size the canvas item to the proper width, the maximum of any label. """
        new_sizing = self.copy_sizing()

        new_sizing.minimum_width = 0
        new_sizing.maximum_width = 0

        axes = self.__axes
        if axes and axes.is_valid:

            # calculate the width based on the label lengths
            font = "{0:d}px".format(self.font_size)

            max_width = 0
            y_range = axes.calibrated_data_max - axes.calibrated_data_min
            label = axes.y_ticker.value_label(axes.calibrated_data_max + y_range * 5)
            max_width = max(max_width, get_font_metrics_fn(font, label).width)
            label = axes.y_ticker.value_label(axes.calibrated_data_min - y_range * 5)
            max_width = max(max_width, get_font_metrics_fn(font, label).width)

            new_sizing.minimum_width = max_width
            new_sizing.maximum_width = max_width

        self.update_sizing(new_sizing)

    def set_axes(self, axes, get_font_metrics_fn):
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.size_to_content(get_font_metrics_fn)
            self.update()

    def _repaint(self, drawing_context):

        # draw the data, if any
        axes = self.__axes
        if axes and axes.is_valid:

            # canvas size
            width = self.canvas_size[1]
            plot_height = int(self.canvas_size[0]) - 1

            # extract the data we need for drawing y-axis
            y_ticks = axes.calculate_y_ticks(plot_height)

            # draw the y_ticks and labels
            with drawing_context.saver():
                drawing_context.text_baseline = "middle"
                drawing_context.font = "{0:d}px".format(self.font_size)
                for y, label in y_ticks:
                    drawing_context.begin_path()
                    drawing_context.stroke_style = '#888'
                    drawing_context.stroke()
                    drawing_context.text_align = "right"
                    drawing_context.fill_style = "#000"
                    drawing_context.fill_text(label, width, y)


class LineGraphVerticalAxisLabelCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the vertical label."""

    def __init__(self):
        super().__init__()
        self.__axes = None
        self.font_size = 12
        self.sizing.minimum_width = self.font_size + 4
        self.sizing.maximum_width = self.font_size + 4

    def size_to_content(self):
        """ Size the canvas item to the proper width. """
        new_sizing = self.copy_sizing()
        new_sizing.minimum_width = 0
        new_sizing.maximum_width = 0
        axes = self.__axes
        if axes and axes.is_valid:
            if axes.y_calibration and axes.y_calibration.units:
                new_sizing.minimum_width = self.font_size + 4
                new_sizing.maximum_width = self.font_size + 4
        self.update_sizing(new_sizing)

    def set_axes(self, axes):
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.size_to_content()
            self.update()

    def _repaint(self, drawing_context):

        # draw the data, if any
        axes = self.__axes
        if axes and axes.is_valid:

            # draw
            if axes.y_calibration and axes.y_calibration.units:
                # canvas size
                width = self.canvas_size[1]
                plot_height = int(self.canvas_size[0]) - 1

                with drawing_context.saver():
                    drawing_context.font = "{0:d}px".format(self.font_size)
                    drawing_context.text_align = "center"
                    drawing_context.text_baseline = "middle"
                    drawing_context.fill_style = "#000"
                    x = width * 0.5
                    y = int(plot_height * 0.5)
                    drawing_context.translate(x, y)
                    drawing_context.rotate(-math.pi*0.5)
                    drawing_context.translate(-x, -y)
                    drawing_context.font = "{0:d}px".format(self.font_size)
                    drawing_context.fill_text(u"{0} ({1})".format(_("Intensity"), axes.y_calibration.units), x, y)
                    drawing_context.translate(x, y)
                    drawing_context.rotate(+math.pi*0.5)
                    drawing_context.translate(-x, -y)


class LineGraphLegendCanvasItemDelegate:
    # interface must be implemented by the delegate

    def create_change_display_item_property_command(self, property_name: str, value) -> Inspector.ChangeDisplayItemPropertyCommand: ...

    def push_undo_command(self, command: Undo.UndoableCommand) -> None: ...

    def create_mime_data(self) -> typing.Any: ...

    def get_display_item_uuid(self) -> uuid.UUID: ...


class LineGraphLegendCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot background and grid lines."""

    def __init__(self, get_font_metrics_fn, delegate: LineGraphLegendCanvasItemDelegate):
        super().__init__()

        self.delegate = delegate

        self.__drawing_context = None
        self.__legend_position = None
        self.__legend_entries = None
        self.__mouse_pressed_for_dragging = False
        self.__mouse_dragging = False
        self.__mouse_position = None
        self.__display_layers = None
        self.wants_mouse_events = True
        self.wants_drag_events = True
        self.__get_font_metrics_fn = get_font_metrics_fn
        self.font_size = 12

        self.__dragging_index = None
        self.__entry_to_insert = None

    def set_legend_entries(self, legend_position: typing.Optional[str], legend_entries: typing.Optional[typing.Sequence], display_layers: typing.Optional[typing.Sequence]):
        if self.__legend_entries != legend_entries or self.__legend_position != legend_position or self.__display_layers != display_layers:
            self.__legend_position = legend_position
            self.__legend_entries = legend_entries
            self.__display_layers = display_layers
            self.update()

    def __get_legend_index(self, x, y, ignore_y = False) -> int:
        """
        Returns the current index at a certain x and y if over a legend item, otherwise returns -1. If ignore_y is set,
        it will always return a value at the closest y value. (useful for determining where to drop an item)
        """
        legend_position = self.__legend_position
        legend_entries = self.__legend_entries
        plot_rect = self.canvas_bounds
        plot_width = int(plot_rect[1][1]) - 1
        plot_origin_x = int(plot_rect[0][1])
        plot_origin_y = int(plot_rect[0][0])

        legend_width = 0
        line_height = self.font_size + 4
        border = 4
        font = "{0:d}px".format(self.font_size)

        for index, legend_entry in enumerate(legend_entries):
            legend_width = max(legend_width, self.__get_font_metrics_fn(font, legend_entry.label).width)

        if legend_position == "top-left":
            legend_origin = Geometry.IntPoint(x=plot_origin_x + 10, y=plot_origin_y + line_height * 0.5 - border)
        else:
            legend_origin = Geometry.IntPoint(x=plot_origin_x + plot_width - 10 - line_height - legend_width - border,
                                              y=plot_origin_y + line_height * 0.5 - border)

        start_x = legend_origin.x
        end_x = start_x + legend_width + line_height + border * 2

        index = (y - legend_origin.y) // line_height

        if not ignore_y:
            if start_x <= x <= end_x and 0 <= index < len(self.__legend_entries):
                return index
            else:
                return -1
        else:
            # return the current item, clamped to length-1 and 0
            return max(min((y - legend_origin.y) // line_height, len(self.__legend_entries)-1), 0)

    def mouse_position_changed(self, x, y, modifiers):
        if self.__mouse_pressed_for_dragging:
            if not self.__mouse_dragging and Geometry.distance(self.__mouse_position, Geometry.IntPoint(y=y, x=x)) > 1:
                mime_data = self.delegate.create_mime_data()

                legend_data = {
                    "index": self.__dragging_index,
                    "display_item": str(self.delegate.get_display_item_uuid())
                }

                mime_data.set_data_as_string(MimeTypes.LAYER_MIME_TYPE, json.dumps(legend_data))
                self.__mouse_dragging = True
                self.drag(mime_data)
                self.update()
                return True

    def drag_move(self, mime_data, x, y):
        old_entry = self.__entry_to_insert
        self.__entry_to_insert = self.__get_legend_index(x, y, True)
        if old_entry != self.__entry_to_insert:
            self.update()
        return True

    def mouse_pressed(self, x, y, modifiers):
        if self.__legend_entries:
            i = self.__get_legend_index(x, y)
            if i != -1:
                self.__mouse_pressed_for_dragging = True
                self.__dragging_index = i
                self.__mouse_position = Geometry.IntPoint(x=x, y=y)
                self.__entry_to_insert = i
                self.update()

    def drag_leave(self):
        self.__mouse_dragging = False
        self.__mouse_position = None
        self.__mouse_pressed_for_dragging = False
        self.__entry_to_insert = None
        self.__dragging_index = None
        self.update()

    def drag_enter(self, mime_data):
        legend_data = json.loads(mime_data.data_as_string(MimeTypes.LAYER_MIME_TYPE))

        if uuid.UUID(legend_data["display_item"]) == self.delegate.get_display_item_uuid():
            self.__mouse_dragging = True
            self.__dragging_index = legend_data["index"]
            self.__mouse_pressed_for_dragging = True
            self.update()

    def drop(self, mime_data, x, y):
        self.__mouse_dragging = False
        self.__mouse_position = None
        self.__mouse_pressed_for_dragging = False

        legend_data = json.loads(mime_data.data_as_string(MimeTypes.LAYER_MIME_TYPE))

        if uuid.UUID(legend_data["display_item"]) == self.delegate.get_display_item_uuid():
            from_index = legend_data["index"]

            if from_index != self.__entry_to_insert:
                new_display_layers = DisplayItem.shift_display_layers(self.__display_layers, from_index,
                                                                      self.__entry_to_insert)

                self.__entry_to_insert = None

                command = self.delegate.create_change_display_item_property_command("display_layers",
                                                                                    new_display_layers)
                command.perform()
                self.delegate.push_undo_command(command)

        self.update()

    def _repaint(self, drawing_context):
        # draw the data, if any
        legend_position = self.__legend_position
        legend_entries = self.__legend_entries
        if legend_entries and legend_position in ("top-left", "top-right"):
            plot_rect = self.canvas_bounds
            plot_width = int(plot_rect[1][1]) - 1
            plot_origin_x = int(plot_rect[0][1])
            plot_origin_y = int(plot_rect[0][0])

            legend_width = 0
            line_height = self.font_size + 4
            border = 4
            font = "{0:d}px".format(self.font_size)

            effective_entries = legend_entries[:]

            if self.__mouse_dragging and self.__entry_to_insert is not None:
                DisplayItem.shift_display_layers(effective_entries, self.__dragging_index, self.__entry_to_insert)

            for index, legend_entry in enumerate(effective_entries):
                with drawing_context.saver():
                    legend_width = max(legend_width, self.__get_font_metrics_fn(font, legend_entry.label).width)

            if legend_position == "top-left":
                legend_origin = Geometry.IntPoint(x=plot_origin_x + 10, y=plot_origin_y + line_height * 0.5 - border)
            else:
                legend_origin = Geometry.IntPoint(x=plot_origin_x + plot_width - 10 - line_height - legend_width - border, y=plot_origin_y + line_height * 0.5 - border)

            with drawing_context.saver():
                drawing_context.begin_path()
                drawing_context.rect(legend_origin.x,
                                     legend_origin.y,
                                     legend_width + border * 2 + line_height,
                                     len(legend_entries) * line_height + border * 2)
                drawing_context.fill_style = "rgba(192, 192, 192, 0.5)"
                drawing_context.fill()

            if self.__mouse_pressed_for_dragging:
                with drawing_context.saver():
                    drawing_context.begin_path()
                    drawing_context.rect(legend_origin.x,
                                         self.__entry_to_insert * line_height + border * 2,
                                         legend_width + border * 2 + line_height,
                                         line_height)
                    drawing_context.fill_style = "rgba(192, 192, 192, 0.5)"
                    drawing_context.fill()

            for index, legend_entry in enumerate(effective_entries):
                with drawing_context.saver():
                    drawing_context.font = font
                    drawing_context.text_align = "right"
                    drawing_context.text_baseline = "bottom"
                    drawing_context.fill_style = "#000"
                    drawing_context.fill_text(legend_entry.label, legend_origin.x + legend_width + border, legend_origin.y + line_height * (index + 1))

                    drawing_context.begin_path()
                    drawing_context.rect(legend_origin.x + legend_width + border + 3, legend_origin.y + line_height * index + 3 + 4, line_height - 6, line_height - 6)
                    if legend_entry.fill_color:
                        drawing_context.fill_style = legend_entry.fill_color
                        drawing_context.fill()
                    if legend_entry.stroke_color:
                        drawing_context.stroke_style = legend_entry.stroke_color
                        drawing_context.stroke()
