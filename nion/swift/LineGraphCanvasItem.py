"""
    A collection of classes facilitating drawing line graphs.

    LineGraphDataInfo is used to pass data, drawing limits, and calibrations to
    various canvas items.

    Several canvas items including the line graph itself, and tick marks, scale,
    and label are also available. All canvas items except for the canvas item
    are auto sizing in the appropriate direction. Canvas items are meant to be
    combined into a grid layout with the line graph.
"""

# standard libraries
import collections
import gettext
import math
import typing

# third party libraries
import numpy

# local libraries
from nion.data import Image
from nion.ui import CanvasItem
from nion.utils import Geometry

_ = gettext.gettext


def nice_label(value: float, precision: int) -> str:
    if math.trunc(math.log10(abs(value) + numpy.nextafter(0,1))) > 4:
        return (u"{0:0." + u"{0:d}".format(precision) + "e}").format(value)
    else:
        return (u"{0:0." + u"{0:d}".format(precision) + "f}").format(value)


class LineGraphDataInfo:
    """Cache data, statistics about the data, and other information about a line graph.

    Some operations such as calculating statistics or even calculating optimal tick positions
    are somewhat expensive. This object caches that information and can be shared between
    the different drawing components such as the graph, tick marks, labels, etc. of a line graph.

    This object is read-only.
    """

    def __init__(self, data=None, data_min=None, data_max=None, data_left=None, data_right=None, spatial_calibration=None, intensity_calibration=None, data_style=None, legend_labels=None):
        # these items are considered to be input items
        self.__uncalibrated_data = data
        self.__data = None
        self.data_min = data_min
        self.data_max = data_max
        self.data_left = data_left
        self.data_right = data_right
        self.spatial_calibration = spatial_calibration
        self.intensity_calibration = intensity_calibration
        self.data_style = data_style if data_style else "linear"
        self.legend_labels = legend_labels
        # these items are considered to be output items
        self.__x_axis_valid = False
        self.__y_axis_valid = False
        # y-axis
        self.__uncalibrated_data_min = None
        self.__uncalibrated_data_max = None
        self.__calibrated_data_min = None
        self.__calibrated_data_max = None
        # x-axis
        self.__drawn_left_channel = None
        self.__drawn_right_channel = None
        self.__x_tick_precision = None
        self.__x_tick_values = None

    @property
    def uncalibrated_data(self):
        return self.__uncalibrated_data

    @property
    def data(self):
        if self.__data is None:
            uncalibrated_data = self.uncalibrated_data
            if uncalibrated_data is not None:
                calibration = self.intensity_calibration
                if calibration:
                    if self.data_style == "log":
                        self.__data = numpy.log10(numpy.maximum(calibration.offset + calibration.scale * uncalibrated_data, 1.0))
                    else:
                        self.__data = calibration.offset + calibration.scale * uncalibrated_data
                else:
                    if self.data_style == "log":
                        self.__data = numpy.log10(numpy.maximum(uncalibrated_data, 1.0))
                    else:
                        self.__data = uncalibrated_data
        return self.__data

    def __prepare_y_axis(self):
        """Calculate various parameters relating to the y-axis.

        The specific parameters calculated from this method are:
            y_tick_precision, y_tick_values
            calibrated_data_min, calibrated_data_max
            calibrated_data_min, calibrated_data_max
        """

        if not self.__y_axis_valid:

            calibration = self.intensity_calibration

            min_specified = self.data_min is not None
            max_specified = self.data_max is not None
            if self.data.shape[-1] > 0:
                raw_data_min = self.data_min if min_specified else numpy.amin(self.uncalibrated_data)
                raw_data_max = self.data_max if max_specified else numpy.amax(self.uncalibrated_data)
            else:
                raw_data_min = 0.0
                raw_data_max = 0.0

            calibrated_data_min = calibration.convert_to_calibrated_value(raw_data_min) if calibration else raw_data_min
            calibrated_data_max = calibration.convert_to_calibrated_value(raw_data_max) if calibration else raw_data_max

            if self.data_style == "log":
                calibrated_data_min = math.log10(max(calibrated_data_min, 1.0))
                calibrated_data_max = math.log10(max(calibrated_data_max, 1.0))

            if math.isnan(calibrated_data_min) or math.isnan(calibrated_data_max) or math.isinf(calibrated_data_min) or math.isinf(calibrated_data_max):
                calibrated_data_min = 0.0
                calibrated_data_max = 0.0

            calibrated_data_min, calibrated_data_max = min(calibrated_data_min, calibrated_data_max), max(calibrated_data_min, calibrated_data_max)
            calibrated_data_min = 0.0 if calibrated_data_min > 0 and not min_specified else calibrated_data_min
            calibrated_data_max = 0.0 if calibrated_data_max < 0 and not max_specified else calibrated_data_max

            logarithmic = self.data_style == "log"
            ticker = Geometry.Ticker(calibrated_data_min, calibrated_data_max, logarithmic=logarithmic)

            if min_specified:
                self.__calibrated_data_min = calibrated_data_min
            else:
                self.__calibrated_data_min = ticker.minimum
            if max_specified:
                self.__calibrated_data_max = calibrated_data_max
            else:
                self.__calibrated_data_max = ticker.maximum

            self.__y_ticker = ticker

            if self.data_style == "log":
                self.__uncalibrated_data_min = math.pow(10, self.__calibrated_data_min)
                self.__uncalibrated_data_max = math.pow(10, self.__calibrated_data_max)
            else:
                self.__uncalibrated_data_min = self.__calibrated_data_min
                self.__uncalibrated_data_max = self.__calibrated_data_max

            if calibration:
                self.__uncalibrated_data_min = calibration.convert_from_calibrated_value(self.__uncalibrated_data_min)
                self.__uncalibrated_data_max = calibration.convert_from_calibrated_value(self.__uncalibrated_data_max)

            self.__y_axis_valid = True

    def calculate_y_ticks(self, plot_height):
        """Calculate the y-axis items dependent on the plot height."""

        y_properties = self.y_properties

        calibrated_data_min = y_properties.calibrated_data_min
        calibrated_data_max = y_properties.calibrated_data_max
        calibrated_data_range = calibrated_data_max - calibrated_data_min

        ticker = y_properties.ticker
        y_ticks = list()
        for tick_value, tick_label in zip(ticker.values, ticker.labels):
            if calibrated_data_range != 0.0:
                y_tick = plot_height - plot_height * (tick_value - calibrated_data_min) / calibrated_data_range
            else:
                y_tick = plot_height - plot_height * 0.5
            if y_tick >= 0 and y_tick <= plot_height:
                y_ticks.append((y_tick, tick_label))

        return y_ticks

    @property
    def y_properties(self):
        if self.uncalibrated_data is None:
            return None
        y_properties = collections.namedtuple("YProperties", ["ticker", "calibrated_data_min", "calibrated_data_max", "uncalibrated_data_min", "uncalibrated_data_max"])
        self.__prepare_y_axis()
        return y_properties(self.__y_ticker, self.__calibrated_data_min, self.__calibrated_data_max, self.__uncalibrated_data_min, self.__uncalibrated_data_max)

    def uncalibrate_y(self, uncalibrated_y_value):
        calibration = self.intensity_calibration
        if self.data_style == "log":
            if calibration:
                return calibration.convert_from_calibrated_value(math.pow(10, uncalibrated_y_value))
            else:
                return math.pow(10, uncalibrated_y_value)
        else:
            if calibration:
                return calibration.convert_from_calibrated_value(uncalibrated_y_value)
            else:
                return uncalibrated_y_value

    def __prepare_x_axis(self):
        """Calculate various parameters relating to the x-axis.

        The specific parameters calculated from this method are: drawn_left_channel, drawn_right_channel,
        x_tick_precision, x_tick_values.
        """

        if not self.__x_axis_valid:

            calibration = self.spatial_calibration

            left_specified = self.data_left is not None
            right_specified = self.data_right is not None
            raw_data_left = self.data_left if left_specified else 0.0
            raw_data_right = self.data_right if right_specified else self.data.shape[-1]

            calibrated_data_left = calibration.convert_to_calibrated_value(raw_data_left) if calibration is not None else raw_data_left
            calibrated_data_right = calibration.convert_to_calibrated_value(raw_data_right) if calibration is not None else raw_data_right
            calibrated_data_left, calibrated_data_right = min(calibrated_data_left, calibrated_data_right), max(calibrated_data_left, calibrated_data_right)

            graph_left, graph_right, tick_values, division, precision = Geometry.make_pretty_range(calibrated_data_left, calibrated_data_right)

            if left_specified:
                self.__drawn_left_channel = raw_data_left
            else:
                self.__drawn_left_channel = calibration.convert_from_calibrated_value(graph_left) if calibration else graph_left
            if right_specified:
                self.__drawn_right_channel = raw_data_right
            else:
                self.__drawn_right_channel = calibration.convert_from_calibrated_value(graph_right) if calibration else graph_right

            self.__x_tick_precision = precision
            self.__x_tick_values = tick_values

            self.__x_axis_valid = True

    def calculate_x_ticks(self, plot_width):
        """Calculate the x-axis items dependent on the plot width."""

        calibration = self.spatial_calibration
        x_properties = self.x_properties
        drawn_data_width = x_properties.drawn_right_channel - x_properties.drawn_left_channel

        x_ticks = list()
        if drawn_data_width > 0.0:
            for tick_value in x_properties.x_tick_values:
                label = nice_label(tick_value, x_properties.x_tick_precision)
                data_tick = calibration.convert_from_calibrated_value(tick_value) if calibration else tick_value
                x_tick = plot_width * (data_tick - x_properties.drawn_left_channel) / drawn_data_width
                if x_tick >= 0 and x_tick <= plot_width:
                    x_ticks.append((x_tick, label))

        return x_ticks

    @property
    def x_properties(self):
        if self.uncalibrated_data is None:
            return None
        x_properties = collections.namedtuple("XProperties",
                                              ["drawn_left_channel", "drawn_right_channel", "x_tick_precision",
                                                  "x_tick_values"])
        self.__prepare_x_axis()
        return x_properties(self.__drawn_left_channel, self.__drawn_right_channel, self.__x_tick_precision,
                            self.__x_tick_values)


def draw_background(drawing_context, plot_rect, background_color):
    with drawing_context.saver():
        drawing_context.begin_path()
        drawing_context.rect(plot_rect[0][1], plot_rect[0][0], plot_rect[1][1], plot_rect[1][0])
        drawing_context.fill_style = background_color
        drawing_context.fill()


def draw_horizontal_grid_lines(drawing_context, plot_width, plot_origin_x, y_ticks):
    with drawing_context.saver():
        for y, _ in y_ticks:
            drawing_context.begin_path()
            drawing_context.move_to(plot_origin_x, y)
            drawing_context.line_to(plot_origin_x + plot_width, y)
        drawing_context.line_width = 1
        drawing_context.stroke_style = '#DDD'
        drawing_context.stroke()


def draw_vertical_grid_lines(drawing_context, plot_height, plot_origin_y, x_ticks):
    with drawing_context.saver():
        for x, _ in x_ticks:
            drawing_context.begin_path()
            drawing_context.move_to(x, plot_origin_y)
            drawing_context.line_to(x, plot_origin_y + plot_height)
        drawing_context.line_width = 1
        drawing_context.stroke_style = '#DDD'
        drawing_context.stroke()


def draw_line_graph(drawing_context, plot_height, plot_width, plot_origin_y, plot_origin_x, data, calibrated_data_min, calibrated_data_range, data_left, data_width, fill: bool, color: str, rebin_cache):
    # TODO: optimize filled case using not-filled drawing. be careful to handle baseline crossings.
    with drawing_context.saver():
        drawing_context.begin_path()
        if calibrated_data_range != 0.0 and data_width > 0.0:
            baseline = plot_origin_y + plot_height - (plot_height * float(0.0 - calibrated_data_min) / calibrated_data_range)
            baseline = min(plot_origin_y + plot_height, baseline)
            baseline = max(plot_origin_y, baseline)
            # rebin so that data_width corresponds to plot width
            binned_length = int(data.shape[-1] * plot_width / data_width)
            if binned_length > 0:
                binned_data = Image.rebin_1d(data, binned_length, rebin_cache)
                binned_left = int(data_left * plot_width / data_width)
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
                    if fill:
                        drawing_context.move_to(px, baseline)
                        drawing_context.line_to(px, py)
                    else:
                        if i == 0:
                            drawing_context.move_to(px, py)
                        else:
                            # only draw horizontal lines when necessary
                            if py != last_py:
                                # draw forward from last_px to px at last_py level
                                drawing_context.line_to(px, last_py)
                                drawing_context.line_to(px, py)
                        last_py = py
                if not fill:
                    drawing_context.line_to(plot_origin_x + plot_width, last_py)
        else:
            drawing_context.move_to(plot_origin_x, plot_origin_y + plot_height * 0.5)
            drawing_context.line_to(plot_origin_x + plot_width, plot_origin_y + plot_height * 0.5)
        drawing_context.line_width = 1.0 if fill else 0.5
        drawing_context.stroke_style = color
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
        self.__data_info = None
        self.draw_grid = True
        self.background_color = "#FFF"

    @property
    def data_info(self):
        return self.__data_info

    @data_info.setter
    def data_info(self, value):
        self.__data_info = value

    def _repaint(self, drawing_context):
        # draw the data, if any
        data_info = self.data_info
        y_properties = self.data_info.y_properties if data_info else None
        x_properties = self.data_info.x_properties if data_info else None
        if data_info and y_properties and x_properties:
            plot_rect = self.canvas_bounds
            plot_width = int(plot_rect[1][1]) - 1
            plot_height = int(plot_rect[1][0]) - 1
            plot_origin_x = int(plot_rect[0][1])
            plot_origin_y = int(plot_rect[0][0])

            # extract the data we need for drawing axes
            y_ticks = data_info.calculate_y_ticks(plot_height)
            x_ticks = data_info.calculate_x_ticks(plot_width)

            draw_background(drawing_context, plot_rect, self.background_color)

            # draw the horizontal grid lines
            if self.draw_grid:
                draw_horizontal_grid_lines(drawing_context, plot_width, plot_origin_x, y_ticks)

            # draw the vertical grid lines
            if self.draw_grid:
                draw_vertical_grid_lines(drawing_context, plot_height, plot_origin_y, x_ticks)


class LineGraphData:

    def __init__(self, data_info, slice=None, filled=True, color=None):
        self.data_info = data_info
        self.slice = slice
        self.filled = filled
        self.color = color if color is not None else '#1E90FF'  # dodger blue
        self.retained_rebin_1d = dict()


class LineGraphCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot itself."""

    def __init__(self):
        super().__init__()
        self.__drawing_context = None
        self.__line_graph_data_list = list()  # type: typing.List[LineGraphData]

    @property
    def line_graph_data_list(self):
        return self.__line_graph_data_list

    @line_graph_data_list.setter
    def line_graph_data_list(self, value):
        self.__line_graph_data_list = value

    @property
    def _data_info(self):  # for testing only
        return self.__line_graph_data_list[0].data_info if len(self.__line_graph_data_list) > 0 else None

    def map_mouse_to_position(self, mouse, data_size):
        """ Map the mouse to the 1-d position within the line graph. """
        data_info = self.__line_graph_data_list[0].data_info if len(self.__line_graph_data_list) > 0 else None
        x_properties = data_info.x_properties if data_info else None
        if x_properties and x_properties.drawn_left_channel is not None and x_properties.drawn_right_channel is not None:
            mouse = Geometry.IntPoint.make(mouse)
            plot_rect = self.canvas_bounds
            if plot_rect.contains_point(mouse):
                mouse = mouse - plot_rect.origin
                x = float(mouse.x) / plot_rect.width
                px = x_properties.drawn_left_channel + x * (x_properties.drawn_right_channel - x_properties.drawn_left_channel)
                return px,
        # not in bounds
        return None

    def _repaint(self, drawing_context):
        # draw the data, if any
        for line_graph_data in self.__line_graph_data_list:
            data_info = line_graph_data.data_info
            y_properties = data_info.y_properties if data_info else None
            x_properties = data_info.x_properties if data_info else None
            if data_info and data_info.data is not None and y_properties and x_properties:

                plot_rect = self.canvas_bounds
                plot_width = int(plot_rect[1][1]) - 1
                plot_height = int(plot_rect[1][0]) - 1
                plot_origin_x = int(plot_rect[0][1])
                plot_origin_y = int(plot_rect[0][0])

                # extract the data we need for drawing y-axis
                calibrated_data_min = y_properties.calibrated_data_min
                calibrated_data_max = y_properties.calibrated_data_max
                calibrated_data_range = calibrated_data_max - calibrated_data_min

                # extract the data we need for drawing x-axis
                data_left = x_properties.drawn_left_channel
                data_width = x_properties.drawn_right_channel - x_properties.drawn_left_channel

                # draw the line plot itself
                if line_graph_data.slice is not None:
                    data = data_info.data[line_graph_data.slice].reshape((data_info.data.shape[-1], ))
                else:
                    data = data_info.data
                draw_line_graph(drawing_context, plot_height, plot_width, plot_origin_y, plot_origin_x, data, calibrated_data_min, calibrated_data_range, data_left, data_width, line_graph_data.filled, line_graph_data.color, line_graph_data.retained_rebin_1d)


class LineGraphRegionsCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot itself."""

    def __init__(self):
        super(LineGraphRegionsCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12
        self.regions = list()

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        y_properties = self.data_info.y_properties if data_info else None
        x_properties = self.data_info.x_properties if data_info else None
        if data_info and data_info.data is not None and y_properties and x_properties:

            plot_rect = self.canvas_bounds
            plot_width = int(plot_rect[1][1]) - 1
            plot_height = int(plot_rect[1][0]) - 1
            plot_origin_y = int(plot_rect[0][0])

            # extract the data we need for drawing y-axis
            calibrated_data_min = y_properties.calibrated_data_min
            calibrated_data_max = y_properties.calibrated_data_max
            calibrated_data_range = calibrated_data_max - calibrated_data_min

            data = data_info.data
            if len(data.shape) > 1:
                data = data[0, ...]

            # calculate the axes drawing info
            data_info.calculate_x_ticks(plot_width)

            data_left = x_properties.drawn_left_channel
            data_right = x_properties.drawn_right_channel

            if data_right <= data_left:
                return

            def convert_coordinate_to_pixel(c):
                px = c * data_info.data.shape[-1]
                return plot_rect.width * (px - data_left) / (data_right - data_left)

            canvas_width = self.canvas_size.width
            canvas_height = self.canvas_size.height

            for region in self.regions:
                left_channel, right_channel = region.channels
                region_selected = region.selected
                index = region.index
                level = plot_rect.bottom - plot_rect.height * 0.8 + index * 8
                with drawing_context.saver():
                    drawing_context.clip_rect(0, 0, canvas_width, canvas_height)
                    if region.style == "tag":
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
        self.__data_info = None
        self.draw_frame = True

    @property
    def data_info(self):
        return self.__data_info

    @data_info.setter
    def data_info(self, value):
        self.__data_info = value

    def _repaint(self, drawing_context):
        # draw the data, if any
        data_info = self.data_info
        y_properties = self.data_info.y_properties if data_info else None
        x_properties = self.data_info.x_properties if data_info else None
        if data_info and y_properties and x_properties:

            plot_rect = self.canvas_bounds
            plot_width = int(plot_rect[1][1]) - 1
            plot_height = int(plot_rect[1][0]) - 1
            plot_origin_x = int(plot_rect[0][1])
            plot_origin_y = int(plot_rect[0][0])

            if self.draw_frame:
                draw_frame(drawing_context, plot_height, plot_origin_x, plot_origin_y, plot_width)


class LineGraphHorizontalAxisTicksCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the horizontal tick marks."""

    def __init__(self):
        super(LineGraphHorizontalAxisTicksCanvasItem, self).__init__()
        self.data_info = None
        self.tick_height = 4
        self.sizing.minimum_height = self.tick_height
        self.sizing.maximum_height = self.tick_height

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        if data_info and data_info.x_properties:

            plot_width = int(self.canvas_size[1]) - 1

            # extract the data we need for drawing x-axis
            x_ticks = data_info.calculate_x_ticks(plot_width)

            # draw the tick marks
            drawing_context.save()
            for x, _ in x_ticks:
                drawing_context.begin_path()
                drawing_context.move_to(x, 0)
                drawing_context.line_to(x, self.tick_height)
                drawing_context.line_width = 1
                drawing_context.stroke_style = '#888'
                drawing_context.stroke()
            drawing_context.restore()


class LineGraphHorizontalAxisScaleCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the horizontal scale."""

    def __init__(self):
        super(LineGraphHorizontalAxisScaleCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12
        self.sizing.minimum_height = self.font_size + 4
        self.sizing.maximum_height = self.font_size + 4

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        if data_info and data_info.x_properties:

            height = self.canvas_size[0]
            plot_width = int(self.canvas_size[1]) - 1

            # extract the data we need for drawing x-axis
            x_ticks = data_info.calculate_x_ticks(plot_width)

            # draw the tick marks
            drawing_context.save()
            drawing_context.font = "{0:d}px".format(self.font_size)
            for x, label in x_ticks:
                drawing_context.text_align = "center"
                drawing_context.text_baseline = "middle"
                drawing_context.fill_style = "#000"
                drawing_context.fill_text(label, x, height * 0.5)
            drawing_context.restore()


class LineGraphHorizontalAxisLabelCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the horizontal label."""

    def __init__(self):
        super(LineGraphHorizontalAxisLabelCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12
        self.sizing.minimum_height = self.font_size + 4
        self.sizing.maximum_height = self.font_size + 4

    def size_to_content(self):
        """ Size the canvas item to the proper height. """
        new_sizing = self.copy_sizing()
        new_sizing.minimum_height = 0
        new_sizing.maximum_height = 0
        data_info = self.data_info
        if data_info:
            if data_info.spatial_calibration and data_info.spatial_calibration.units:
                new_sizing.minimum_height = self.font_size + 4
                new_sizing.maximum_height = self.font_size + 4
        self.update_sizing(new_sizing)

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        if data_info:

            # draw the horizontal axis
            if data_info.spatial_calibration and data_info.spatial_calibration.units:

                height = self.canvas_size[0]
                plot_width = int(self.canvas_size[1]) - 1

                drawing_context.save()
                drawing_context.text_align = "center"
                drawing_context.text_baseline = "middle"
                drawing_context.fill_style = "#000"
                value_str = u"({0})".format(data_info.spatial_calibration.units)
                drawing_context.font = "{0:d}px".format(self.font_size)
                drawing_context.fill_text(value_str, plot_width * 0.5, height * 0.5)
                drawing_context.restore()


class LineGraphVerticalAxisTicksCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the vertical tick marks."""

    def __init__(self):
        super(LineGraphVerticalAxisTicksCanvasItem, self).__init__()
        self.data_info = None
        self.tick_width = 4
        self.sizing.minimum_width = self.tick_width
        self.sizing.maximum_width = self.tick_width

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        if data_info and data_info.y_properties:

            # canvas size
            width = self.canvas_size[1]
            plot_height = int(self.canvas_size[0]) - 1

            # extract the data we need for drawing y-axis
            y_ticks = data_info.calculate_y_ticks(plot_height)

            # draw the y_ticks and labels
            drawing_context.save()
            for y, _ in y_ticks:
                drawing_context.begin_path()
                drawing_context.move_to(width, y)
                drawing_context.line_to(width - self.tick_width, y)
                drawing_context.line_width = 1
                drawing_context.stroke_style = '#888'
                drawing_context.stroke()
            drawing_context.restore()


class LineGraphVerticalAxisScaleCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the vertical scale."""

    def __init__(self):
        super(LineGraphVerticalAxisScaleCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12

    def size_to_content(self, get_font_metrics_fn):
        """ Size the canvas item to the proper width, the maximum of any label. """
        new_sizing = self.copy_sizing()

        new_sizing.minimum_width = 0
        new_sizing.maximum_width = 0

        y_properties = self.data_info.y_properties if self.data_info else None
        if y_properties:

            # calculate the width based on the label lengths
            font = "{0:d}px".format(self.font_size)

            max_width = 0
            y_range = y_properties.calibrated_data_max - y_properties.calibrated_data_min
            label = y_properties.ticker.value_label(y_properties.calibrated_data_max + y_range * 5)
            max_width = max(max_width, get_font_metrics_fn(font, label).width)
            label = y_properties.ticker.value_label(y_properties.calibrated_data_min - y_range * 5)
            max_width = max(max_width, get_font_metrics_fn(font, label).width)

            new_sizing.minimum_width = max_width
            new_sizing.maximum_width = max_width

        self.update_sizing(new_sizing)

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        if data_info and data_info.y_properties:

            # canvas size
            width = self.canvas_size[1]
            plot_height = int(self.canvas_size[0]) - 1

            # extract the data we need for drawing y-axis
            y_ticks = data_info.calculate_y_ticks(plot_height)

            # draw the y_ticks and labels
            drawing_context.save()
            drawing_context.text_baseline = "middle"
            drawing_context.font = "{0:d}px".format(self.font_size)
            for y, label in y_ticks:
                drawing_context.begin_path()
                drawing_context.stroke_style = '#888'
                drawing_context.stroke()
                drawing_context.text_align = "right"
                drawing_context.fill_style = "#000"
                drawing_context.fill_text(label, width, y)
            drawing_context.restore()


class LineGraphVerticalAxisLabelCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the vertical label."""

    def __init__(self):
        super(LineGraphVerticalAxisLabelCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12
        self.sizing.minimum_width = self.font_size + 4
        self.sizing.maximum_width = self.font_size + 4

    def size_to_content(self):
        """ Size the canvas item to the proper width. """
        new_sizing = self.copy_sizing()
        new_sizing.minimum_width = 0
        new_sizing.maximum_width = 0
        data_info = self.data_info
        if data_info:
            if data_info.intensity_calibration and data_info.intensity_calibration.units:
                new_sizing.minimum_width = self.font_size + 4
                new_sizing.maximum_width = self.font_size + 4
        self.update_sizing(new_sizing)

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        if data_info:

            # draw
            if data_info.intensity_calibration and data_info.intensity_calibration.units:
                # canvas size
                width = self.canvas_size[1]
                plot_height = int(self.canvas_size[0]) - 1

                drawing_context.save()
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
                drawing_context.fill_text(u"{0} ({1})".format(_("Intensity"), data_info.intensity_calibration.units), x, y)
                drawing_context.translate(x, y)
                drawing_context.rotate(+math.pi*0.5)
                drawing_context.translate(-x, -y)
                drawing_context.restore()


class LineGraphLegendCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot background and grid lines."""

    def __init__(self, get_font_metrics_fn):
        super().__init__()
        self.__drawing_context = None
        self.__data_info = None
        self.__get_font_metrics_fn = get_font_metrics_fn
        self.font_size = 12

    @property
    def data_info(self):
        return self.__data_info

    @data_info.setter
    def data_info(self, value):
        self.__data_info = value

    def _repaint(self, drawing_context):
        # draw the data, if any
        data_info = self.data_info
        legend_labels = self.data_info.legend_labels if data_info else None
        if data_info and legend_labels and len(legend_labels) > 0:
            plot_rect = self.canvas_bounds
            plot_width = int(plot_rect[1][1]) - 1
            plot_origin_x = int(plot_rect[0][1])
            plot_origin_y = int(plot_rect[0][0])

            legend_width = 0
            line_height = self.font_size + 4
            base_y = plot_origin_y + line_height * 1.5 - 4
            font = "{0:d}px".format(self.font_size)
            border = 4

            colors = ('#1E90FF', "#F00", "#0F0", "#00F", "#FF0", "#0FF", "#F0F", "#888", "#800", "#080", "#008", "#CCC", "#880", "#088", "#808", "#964B00")
            for index, legend_label in enumerate(legend_labels):
                with drawing_context.saver():
                    drawing_context.font = font
                    drawing_context.text_align = "right"
                    drawing_context.text_baseline = "bottom"
                    drawing_context.fill_style = "#000"
                    legend_width = max(legend_width, self.__get_font_metrics_fn(font, legend_label).width)
                    drawing_context.fill_text(legend_label, plot_origin_x + plot_width - 10 - line_height, base_y)

                    drawing_context.begin_path()
                    drawing_context.rect(plot_origin_x + plot_width - 10 - line_height + 3, base_y - line_height + 3 + 4, line_height - 6, line_height - 6)
                    drawing_context.fill_style = colors[index]
                    drawing_context.fill()

                    base_y += line_height

            with drawing_context.saver():
                drawing_context.begin_path()
                drawing_context.rect(plot_origin_x + plot_width - 10 - line_height - legend_width - border, plot_origin_y + line_height * 0.5 - border, legend_width + border * 2 + line_height, len(legend_labels) * line_height + border * 2)
                drawing_context.fill_style = "rgba(192, 192, 192, 0.50)"
                drawing_context.fill()
