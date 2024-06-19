"""
    A collection of classes facilitating drawing line graphs.

    Several canvas items including the line graph itself, and tick marks, scale,
    and label are also available. All canvas items except for the canvas item
    are auto sizing in the appropriate direction. Canvas items are meant to be
    combined into a grid layout with the line graph.
"""
from __future__ import annotations

# standard libraries
import copy
import dataclasses
import gettext
import math
import re
import typing

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift import MimeTypes
from nion.swift import Undo
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import UISettings
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import UserInterface
from nion.utils import Color
from nion.utils import Geometry

_NDArray = numpy.typing.NDArray[typing.Any]


@dataclasses.dataclass
class RegionInfo:
    channels: typing.Tuple[float, float]
    selected: bool
    index: int
    left_text: str
    right_text: str
    middle_text: str
    label: typing.Optional[str]
    style: typing.Optional[str]
    color: typing.Optional[str]

_ = gettext.gettext


def nice_label(value: float, precision: int) -> str:
    if math.trunc(math.log10(abs(value) + numpy.nextafter(0,1))) > 4:
        return (u"{0:0." + u"{0:d}".format(precision) + "e}").format(value)
    else:
        return (u"{0:0." + u"{0:d}".format(precision) + "f}").format(value)


def calculate_y_axis(xdata_list: typing.Sequence[typing.Optional[DataAndMetadata.DataAndMetadata]], data_min: typing.Optional[float], data_max: typing.Optional[float], data_style: typing.Optional[str]) -> typing.Tuple[float, float, Geometry.Ticker]:
    """Calculate the calibrated min/max and y-axis ticker for list of xdata.

    xdata_list is the original calibrated data
    data_min and data_max are calibrated values
    """

    min_specified = data_min is not None
    max_specified = data_max is not None

    if min_specified:
        calibrated_data_min = data_min
    else:
        calibrated_data_min = None
        for xdata in xdata_list:
            if xdata and xdata.data_shape[-1] > 0:
                # force the uncalibrated_data to be float so that numpy.amin with a numpy.inf initial value works.
                uncalibrated_data = xdata.data if numpy.issubdtype(xdata.data.dtype, numpy.floating) else xdata.data.astype(float)
                if uncalibrated_data is not None:
                    if data_style == "log":
                        calibrated_origin = xdata.intensity_calibration.convert_from_calibrated_value(0.0)
                        partial_uncalibrated_data_min = numpy.amin(uncalibrated_data[uncalibrated_data > calibrated_origin], initial=numpy.inf)
                    else:
                        partial_uncalibrated_data_min = numpy.amin(uncalibrated_data)
                    calibrated_value = xdata.intensity_calibration.convert_to_calibrated_value(partial_uncalibrated_data_min)
                    if calibrated_data_min is not None:
                        calibrated_data_min = min(calibrated_data_min, calibrated_value)
                    else:
                        calibrated_data_min = calibrated_value
    if calibrated_data_min is None or not numpy.isfinite(calibrated_data_min):
        calibrated_data_min = 0.0

    if max_specified:
        calibrated_data_max = data_max
    else:
        calibrated_data_max = None
        for xdata in xdata_list:
            if xdata and xdata.data_shape[-1] > 0:
                # force the uncalibrated_data to be float so that numpy.amin with a numpy.inf initial value works.
                uncalibrated_data = xdata.data if numpy.issubdtype(xdata.data.dtype, numpy.floating) else xdata.data.astype(float)
                if uncalibrated_data is not None:
                    if data_style == "log":
                        calibrated_origin = xdata.intensity_calibration.convert_from_calibrated_value(0.0)
                        partial_uncalibrated_data_max = numpy.amax(uncalibrated_data[uncalibrated_data > calibrated_origin], initial=-numpy.inf)
                    else:
                        partial_uncalibrated_data_max = numpy.amax(uncalibrated_data)
                    calibrated_value = xdata.intensity_calibration.convert_to_calibrated_value(partial_uncalibrated_data_max)
                    if calibrated_data_max is not None:
                        calibrated_data_max = max(calibrated_data_max, calibrated_value)
                    else:
                        calibrated_data_max = calibrated_value
    if calibrated_data_max is None or not numpy.isfinite(calibrated_data_max):
        calibrated_data_max = 0.0

    if data_style == "log":
        calibrated_data_min = math.log10(calibrated_data_min) if calibrated_data_min > 0 else 0.0
        calibrated_data_max = math.log10(calibrated_data_max) if calibrated_data_max > 0 else 0.0

    if math.isnan(calibrated_data_min) or math.isnan(calibrated_data_max) or math.isinf(calibrated_data_min) or math.isinf(calibrated_data_max):
        calibrated_data_min = 0.0
        calibrated_data_max = 0.0

    calibrated_data_min, calibrated_data_max = min(calibrated_data_min, calibrated_data_max), max(calibrated_data_min, calibrated_data_max)
    if not data_style == "log":
        calibrated_data_min = 0.0 if calibrated_data_min > 0 and not min_specified else calibrated_data_min
        calibrated_data_max = 0.0 if calibrated_data_max < 0 and not max_specified else calibrated_data_max

    if calibrated_data_min == calibrated_data_max:
        calibrated_data_min -= 1.0
        calibrated_data_max += 1.0

    ticker: Geometry.Ticker
    if data_style == "log":
        ticker = Geometry.LogTicker(calibrated_data_min, calibrated_data_max)
    else:
        ticker = Geometry.LinearTicker(calibrated_data_min, calibrated_data_max)

    if not min_specified:
        calibrated_data_min = ticker.minimum
    if not max_specified:
        calibrated_data_max = ticker.maximum

    return calibrated_data_min, calibrated_data_max, ticker


@dataclasses.dataclass
class LegendEntry:
    label: str
    fill_color: typing.Optional[str]
    stroke_color: typing.Optional[str]


class LineGraphAxes:
    """Track information about line graph axes."""

    def __init__(self, data_scale: float, calibrated_data_min: float, calibrated_data_max: float, data_left: int,
                 data_right: int, x_calibration: typing.Optional[Calibration.Calibration],
                 y_calibration: typing.Optional[Calibration.Calibration], data_style: typing.Optional[str],
                 y_ticker: Geometry.Ticker) -> None:
        assert x_calibration is None or x_calibration.is_valid
        assert y_calibration is None or y_calibration.is_valid
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
    def y_ticker(self) -> Geometry.Ticker:
        return self.__y_ticker

    @property
    def uncalibrated_data_min(self) -> float:
        y_calibration = self.y_calibration if self.y_calibration else Calibration.Calibration()
        calibrated_data_min = self.calibrated_data_min
        if self.data_style == "log":
            return y_calibration.convert_from_calibrated_value(math.pow(10, calibrated_data_min))
        else:
            return y_calibration.convert_from_calibrated_value(calibrated_data_min)

    @property
    def uncalibrated_data_max(self) -> float:
        y_calibration = self.y_calibration if self.y_calibration else Calibration.Calibration()
        calibrated_data_max = self.calibrated_data_max
        if self.data_style == "log":
            return y_calibration.convert_from_calibrated_value(math.pow(10, calibrated_data_max))
        else:
            return y_calibration.convert_from_calibrated_value(calibrated_data_max)

    @property
    def calibrated_data_min(self) -> float:
        return self.__calibrated_data_min

    @property
    def calibrated_data_max(self) -> float:
        return self.__calibrated_data_max

    @property
    def calibrated_value_max(self) -> float:
        if self.data_style == "log":
            return math.pow(10, self.__calibrated_data_max)
        return self.__calibrated_data_max

    @property
    def calibrated_value_min(self) -> float:
        if self.data_style == "log":
            return math.pow(10, self.__calibrated_data_min)
        return self.__calibrated_data_min

    @property
    def drawn_left_channel(self) -> int:
        return self.__uncalibrated_left_channel

    @property
    def drawn_right_channel(self) -> int:
        return self.__uncalibrated_right_channel

    @property
    def calibrated_left_channel(self) -> float:
        return self.x_calibration.convert_to_calibrated_value(self.drawn_left_channel) if self.x_calibration else float(self.__uncalibrated_left_channel)

    @property
    def calibrated_right_channel(self) -> float:
        return self.x_calibration.convert_to_calibrated_value(self.drawn_right_channel) if self.x_calibration else float(self.__uncalibrated_right_channel)

    def calculate_y_ticks(self, plot_height: int, flag_minor: bool = False) -> typing.Sequence[typing.Tuple[float, str, bool]]:
        """Calculate the y-axis items dependent on the plot height."""

        calibrated_data_min = self.calibrated_data_min
        calibrated_data_max = self.calibrated_data_max
        calibrated_data_range = calibrated_data_max - calibrated_data_min

        ticker = self.y_ticker
        y_ticks: typing.List[typing.Tuple[float, str, bool]] = list()

        for i, (tick_value, tick_label) in enumerate(zip(ticker.values, ticker.labels)):
            if calibrated_data_range != 0.0:
                y_tick = plot_height - plot_height * (tick_value - calibrated_data_min) / calibrated_data_range
            else:
                y_tick = plot_height - plot_height * 0.5
            if y_tick >= 0 and y_tick <= plot_height:
                if flag_minor:
                    y_ticks.append((y_tick, tick_label, i in ticker.minor_tick_indices))
                else:
                    y_ticks.append((y_tick, tick_label, False))

        return y_ticks

    def uncalibrate_y(self, calibrated_y_value: float) -> float:
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

    def calculate_x_ticks(self, plot_width: int) -> typing.Sequence[typing.Tuple[float, str]]:
        """Calculate the x-axis items dependent on the plot width."""

        x_calibration = self.x_calibration

        uncalibrated_data_left = self.__uncalibrated_left_channel
        uncalibrated_data_right = self.__uncalibrated_right_channel

        calibrated_data_left = x_calibration.convert_to_calibrated_value(uncalibrated_data_left) if x_calibration is not None else uncalibrated_data_left
        calibrated_data_right = x_calibration.convert_to_calibrated_value(uncalibrated_data_right) if x_calibration is not None else uncalibrated_data_right
        calibrated_data_left, calibrated_data_right = min(calibrated_data_left, calibrated_data_right), max(calibrated_data_left, calibrated_data_right)

        graph_left, graph_right, tick_values, division, precision = Geometry.make_pretty_range(calibrated_data_left, calibrated_data_right)

        drawn_data_width = self.drawn_right_channel - self.drawn_left_channel

        x_ticks: typing.List[typing.Tuple[float, str]] = list()
        if drawn_data_width > 0.0:
            for tick_value in tick_values:
                label = nice_label(tick_value, precision)
                data_tick = x_calibration.convert_from_calibrated_value(tick_value) if x_calibration else tick_value
                x_tick = plot_width * (data_tick - self.drawn_left_channel) / drawn_data_width
                if x_tick >= 0 and x_tick <= plot_width:
                    x_ticks.append((x_tick, label))

        return x_ticks

    def calculate_calibrated_xdata(self, xdata: DataAndMetadata.DataAndMetadata) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        """Calculate the 'calibrated xdata'.

         The 'calibrated xdata' is the xdata (with a calibration) but with a new intensity calibration where origin=0 and scale=1.
         """
        calibrated_data: typing.Optional[_NDArray]
        intensity_calibration = xdata.intensity_calibration
        if intensity_calibration:
            data = xdata.data
            if self.data_style == "log":
                calibrated_data = intensity_calibration.offset + intensity_calibration.scale * data
                calibrated_data[calibrated_data <= 0] = numpy.nan
                numpy.log10(calibrated_data, out=calibrated_data)
            else:
                calibrated_data = intensity_calibration.offset + intensity_calibration.scale * data
            return DataAndMetadata.new_data_and_metadata(calibrated_data, intensity_calibration=Calibration.Calibration(units=intensity_calibration.units), dimensional_calibrations=xdata.dimensional_calibrations)
        else:
            return xdata


def are_axes_equal(axes1: typing.Optional[LineGraphAxes], axes2: typing.Optional[LineGraphAxes]) -> bool:
    if (axes1 is None) != (axes2 is None):
        return False
    if axes1 is None or axes2 is None:
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


def draw_background(drawing_context: DrawingContext.DrawingContext, plot_rect: Geometry.IntRect, background_color: typing.Optional[typing.Union[str, DrawingContext.LinearGradient]]) -> None:
    with drawing_context.saver():
        drawing_context.begin_path()
        drawing_context.rect(plot_rect.left, plot_rect.top, plot_rect.width, plot_rect.height)
        drawing_context.fill_style = background_color
        drawing_context.fill()


def draw_horizontal_grid_lines(drawing_context: DrawingContext.DrawingContext, plot_width: float, plot_origin_x: float, y_ticks: typing.Sequence[typing.Tuple[float, str, bool]]) -> None:
    with drawing_context.saver():
        drawing_context.begin_path()
        for y, _, _ in y_ticks:
            drawing_context.move_to(plot_origin_x, y)
            drawing_context.line_to(plot_origin_x + plot_width, y)
        drawing_context.line_width = 0.5
        drawing_context.stroke_style = '#DDD'
        drawing_context.stroke()


def draw_vertical_grid_lines(drawing_context: DrawingContext.DrawingContext, plot_height: float, plot_origin_y: float, x_ticks: typing.Sequence[typing.Tuple[float, str]]) -> None:
    with drawing_context.saver():
        drawing_context.begin_path()
        for x, _ in x_ticks:
            drawing_context.move_to(x, plot_origin_y)
            drawing_context.line_to(x, plot_origin_y + plot_height)
        drawing_context.line_width = 0.5
        drawing_context.stroke_style = '#DDD'
        drawing_context.stroke()


class LineGraphSegment:
    """Helper for constructing a segment of a line graph.

    Keeps a path, provides drawing methods and methods to fill/stroke.
    """

    def __init__(self, path: typing.Optional[DrawingContext.DrawingContext] = None) -> None:
        self.__path = path or DrawingContext.DrawingContext()
        self.__first_point = Geometry.FloatPoint()
        self.__last_point = Geometry.FloatPoint()
        self.line_commands: typing.List[typing.Tuple[float, float]] = list()  # used for optimization

    def __deepcopy__(self, memo: typing.Dict[typing.Any, typing.Any]) -> LineGraphSegment:
        return LineGraphSegment(copy.deepcopy(self.__path))

    @property
    def path(self) -> DrawingContext.DrawingContext:
        return self.__path

    def move_to(self, x: float, y: float) -> None:
        self.__path.move_to(x, y)
        self.__first_point = Geometry.FloatPoint(x=x, y=y)

    def line_to(self, x: float, y: float) -> None:
        self.__path.line_to(x, y)

    def final_line_to(self, x: float, y: float) -> None:
        self.__path._line_to_multi(self.line_commands)
        self.line_commands = list()
        self.__path.line_to(x, y)
        self.__last_point = Geometry.FloatPoint(x=x, y=y)

    def fill(self, drawing_context: DrawingContext.DrawingContext, baseline: float, fill_color: Color.Color) -> None:
        with drawing_context.saver():
            drawing_context.begin_path()
            drawing_context.add(self.__path)
            drawing_context.line_to(self.__last_point.x, baseline)
            drawing_context.line_to(self.__first_point.x, baseline)
            drawing_context.close_path()
            drawing_context.fill_style = fill_color.color_str
            drawing_context.fill()

    def stroke(self, drawing_context: DrawingContext.DrawingContext, baseline: float, stroke_color: Color.Color, stroke_width: float) -> None:
        with drawing_context.saver():
            drawing_context.begin_path()
            drawing_context.add(self.__path)
            drawing_context.line_to(self.__last_point.x, baseline)
            drawing_context.line_width = stroke_width
            drawing_context.stroke_style = stroke_color.color_str
            drawing_context.stroke()


def calculate_line_graph(plot_height: int, plot_width: int, plot_origin_y: int, plot_origin_x: int,
                    calibrated_xdata: DataAndMetadata.DataAndMetadata, calibrated_data_min: float,
                    calibrated_data_range: float, calibrated_left_channel: float, calibrated_right_channel: float,
                    x_calibration: Calibration.Calibration,
                    rebin_cache: typing.Optional[typing.Dict[str, typing.Any]],
                    data_style: str) -> typing.Tuple[typing.List[LineGraphSegment], int]:
    # calculate how the data is displayed
    xdata_calibration = calibrated_xdata.dimensional_calibrations[-1]
    assert xdata_calibration.units == x_calibration.units
    if x_calibration.scale < 0:
        displayed_calibrated_left_channel = min(calibrated_left_channel, xdata_calibration.convert_to_calibrated_value(0))
        displayed_calibrated_right_channel = max(calibrated_right_channel, xdata_calibration.convert_to_calibrated_value(calibrated_xdata.dimensional_shape[-1]))
        if displayed_calibrated_left_channel <= calibrated_right_channel or displayed_calibrated_right_channel >= calibrated_left_channel:
            return list(), 0  # data is outside drawing area
    else:
        displayed_calibrated_left_channel = max(calibrated_left_channel, xdata_calibration.convert_to_calibrated_value(0))
        displayed_calibrated_right_channel = min(calibrated_right_channel, xdata_calibration.convert_to_calibrated_value(calibrated_xdata.dimensional_shape[-1]))
        if displayed_calibrated_left_channel >= calibrated_right_channel or displayed_calibrated_right_channel <= calibrated_left_channel:
            return list(), 0  # data is outside drawing area
    data_left_channel = round(xdata_calibration.convert_from_calibrated_value(displayed_calibrated_left_channel))
    data_right_channel = round(xdata_calibration.convert_from_calibrated_value(displayed_calibrated_right_channel))
    left = round((displayed_calibrated_left_channel - calibrated_left_channel) / (calibrated_right_channel - calibrated_left_channel) * plot_width + plot_origin_x)
    right = round((displayed_calibrated_right_channel - calibrated_left_channel) / (calibrated_right_channel - calibrated_left_channel) * plot_width + plot_origin_x)

    # update input parameters, then fall back to old algorithm
    plot_width = right - left
    plot_origin_x = left
    if 0 <= data_left_channel < data_right_channel and data_right_channel <= calibrated_xdata.dimensional_shape[-1]:
        calibrated_xdata = calibrated_xdata[data_left_channel:data_right_channel]
    else:
        return list(), 0
    x_calibration = calibrated_xdata.dimensional_calibrations[-1]
    calibrated_left_channel = x_calibration.convert_to_calibrated_value(0)
    calibrated_right_channel = x_calibration.convert_to_calibrated_value(calibrated_xdata.dimensional_shape[-1])

    uncalibrated_left_channel = x_calibration.convert_from_calibrated_value(calibrated_left_channel)
    uncalibrated_right_channel = x_calibration.convert_from_calibrated_value(calibrated_right_channel)
    uncalibrated_width = uncalibrated_right_channel - uncalibrated_left_channel
    segments: typing.List[LineGraphSegment] = list()
    segment = LineGraphSegment()
    # use line_commands as an optimization for adding line commands to the path. this is critical for performance.
    line_commands = segment.line_commands
    # segment_path = segment.path  # partially optimized; see note below
    # note: testing performance using a loop around drawing commands in test_line_plot_handle_calibrated_x_axis_with_negative_scale
    if calibrated_data_range != 0.0 and uncalibrated_width > 0.0:
        if data_style == "log":
            baseline = plot_origin_y + plot_height
        else:
            baseline = plot_origin_y + plot_height - int(plot_height * float(0.0 - calibrated_data_min) / calibrated_data_range)

        baseline = min(plot_origin_y + plot_height, baseline)
        baseline = max(plot_origin_y, baseline)
        # rebin so that uncalibrated_width corresponds to plot width
        calibrated_data = calibrated_xdata._data_ex
        binned_length = int(calibrated_data.shape[-1] * plot_width / uncalibrated_width)
        did_draw = False
        if binned_length > 0:
            binned_data = Image.rebin_1d(calibrated_data, binned_length, rebin_cache)
            binned_data_is_nan = numpy.isnan(binned_data)
            binned_left = int(uncalibrated_left_channel * plot_width / uncalibrated_width)
            # draw the plot
            last_py = baseline
            for i in range(0, plot_width):
                px = plot_origin_x + i
                binned_index = binned_left + i
                if binned_index >= 0 and binned_index < binned_length and not binned_data_is_nan[binned_index]:
                    data_value = binned_data[binned_index]
                    # plot_origin_y is the TOP of the drawing
                    # py extends DOWNWARDS
                    py = plot_origin_y + plot_height - (plot_height * (data_value - calibrated_data_min) / calibrated_data_range)
                    py = max(plot_origin_y, py)
                    py = min(plot_origin_y + plot_height, py)
                    if did_draw:
                        # only draw horizontal lines when necessary
                        if py != last_py:
                            # draw forward from last_px to px at last_py level
                            # note: using optimized line commands to optimize this critical code.
                            line_commands.append((px, last_py))
                            line_commands.append((px, py))
                            # partially optimized code below.
                            # segment_path.line_to(px, last_py)
                            # segment_path.line_to(px, py)
                    else:
                        did_draw = True
                        if i == 0:
                            segment.move_to(px, py)
                        else:
                            segment.move_to(px, baseline)
                            segment.line_to(px, py)
                    last_py = py
                else:
                    if did_draw:
                        did_draw = False
                        segment.final_line_to(px, last_py)
                        segments.append(segment)
                        segment = LineGraphSegment()
                        # update line_commands (a path drawing optimization) for the new segment.
                        line_commands = segment.line_commands

            segment.final_line_to(plot_origin_x + plot_width, last_py)

            if did_draw:
                segments.append(segment)
        return segments, baseline
    return list(), 0


def draw_frame(drawing_context: DrawingContext.DrawingContext, plot_height: int, plot_origin_x: int, plot_origin_y: int, plot_width: int) -> None:
    with drawing_context.saver():
        drawing_context.begin_path()
        drawing_context.rect(plot_origin_x, plot_origin_y, plot_width, plot_height)
        drawing_context.line_width = 1
        drawing_context.stroke_style = '#888'
        drawing_context.stroke()


def draw_marker(drawing_context: DrawingContext.DrawingContext, p: Geometry.FloatPoint,
                fill: typing.Optional[str] = None, stroke: typing.Optional[str] = None) -> None:
    with drawing_context.saver():
        drawing_context.begin_path()
        drawing_context.move_to(p.x - 3, p.y - 3)
        drawing_context.line_to(p.x + 3, p.y - 3)
        drawing_context.line_to(p.x + 3, p.y + 3)
        drawing_context.line_to(p.x - 3, p.y + 3)
        drawing_context.close_path()
        if fill:
            drawing_context.fill_style = fill
            drawing_context.fill()
        if stroke:
            drawing_context.stroke_style = stroke
            drawing_context.stroke()


class LineGraphBackgroundCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot background and grid lines."""

    def __init__(self) -> None:
        super().__init__()
        self.__axes: typing.Optional[LineGraphAxes] = None
        self.draw_grid = True
        self.background_color = "#FFF"

    def set_axes(self, axes: typing.Optional[LineGraphAxes]) -> None:
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        # draw the data, if any
        axes = self.__axes
        canvas_bounds = self.canvas_bounds
        if axes and canvas_bounds:
            plot_width = canvas_bounds.width - 1
            plot_height = canvas_bounds.height - 1
            plot_origin_x = canvas_bounds.left
            plot_origin_y = canvas_bounds.top

            # extract the data we need for drawing axes
            y_ticks = axes.calculate_y_ticks(plot_height)
            x_ticks = axes.calculate_x_ticks(plot_width)

            draw_background(drawing_context, canvas_bounds, self.background_color)

            # draw the horizontal grid lines
            if self.draw_grid:
                draw_horizontal_grid_lines(drawing_context, plot_width, plot_origin_x, y_ticks)

            # draw the vertical grid lines
            if self.draw_grid:
                draw_vertical_grid_lines(drawing_context, plot_height, plot_origin_y, x_ticks)


class LineGraphLayer:
    """Represents a layer of the line graph.

    xdata is calibrated data.

    Tracks the data, calibrated data, axes. Provides methods to calculate the segments and draw fills/strokes separately.
    """

    def __init__(self, xdata: typing.Optional[DataAndMetadata.DataAndMetadata], fill_color: typing.Optional[Color.Color],
                 stroke_color: typing.Optional[Color.Color], stroke_width: typing.Optional[float]) -> None:
        self.__xdata = xdata
        self.fill_color = fill_color
        self.stroke_color = stroke_color
        self.stroke_width = stroke_width or 0.5
        self.__calibrated_xdata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.retained_rebin_1d: typing.Dict[str, typing.Any] = dict()
        self.__axes: typing.Optional[LineGraphAxes] = None
        self.segments: typing.List[LineGraphSegment] = list()
        self.baseline = 0.0

    def set_axes(self, axes: typing.Optional[LineGraphAxes]) -> None:
        self.__axes = axes
        self.__calibrated_xdata = None

    @property
    def calibrated_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        if self.__axes and self.__xdata and not self.__calibrated_xdata:
            self.__calibrated_xdata = self.__axes.calculate_calibrated_xdata(self.__xdata)
        return self.__calibrated_xdata

    def calculate(self, canvas_bounds: Geometry.IntRect) -> None:
        calibrated_xdata = self.calibrated_xdata
        segments: typing.List[LineGraphSegment] = list()
        baseline = 0.0
        if calibrated_xdata is not None and self.__axes:
            axes = self.__axes

            plot_width = canvas_bounds.width - 1
            plot_height = canvas_bounds.height - 1
            plot_origin_x = canvas_bounds.left
            plot_origin_y = canvas_bounds.top

            # extract the data we need for drawing y-axis
            calibrated_data_min = axes.calibrated_data_min
            calibrated_data_max = axes.calibrated_data_max
            calibrated_data_range = calibrated_data_max - calibrated_data_min

            # extract the data we need for drawing x-axis
            calibrated_left_channel = axes.calibrated_left_channel
            calibrated_right_channel = axes.calibrated_right_channel
            x_calibration = axes.x_calibration

            # draw the line plot itself
            if x_calibration and x_calibration.units == calibrated_xdata.dimensional_calibrations[-1].units:
                segments, baseline = calculate_line_graph(plot_height, plot_width, plot_origin_y, plot_origin_x,
                                                          calibrated_xdata,
                                                          calibrated_data_min, calibrated_data_range,
                                                          calibrated_left_channel,
                                                          calibrated_right_channel, x_calibration,
                                                          self.retained_rebin_1d, axes.data_style)
        self.segments = segments
        self.baseline = baseline

    def draw_fills(self, drawing_context: DrawingContext.DrawingContext) -> None:
        if self.fill_color:
            for segment in self.segments:
                segment.fill(drawing_context, self.baseline, Color.Color(self.fill_color))

    def draw_strokes(self, drawing_context: DrawingContext.DrawingContext) -> None:
        if self.stroke_color:
            for segment in self.segments:
                segment.stroke(drawing_context, self.baseline, Color.Color(self.stroke_color), self.stroke_width)


class LineGraphLayersCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot layer by layer.

    Draws the fills followed by the strokes.
    """

    def __init__(self) -> None:
        super().__init__()
        self.__axes: typing.Optional[LineGraphAxes] = None
        self.__line_graph_layers: typing.List[LineGraphLayer] = list()

    @property
    def _axes(self) -> typing.Optional[LineGraphAxes]:  # for testing only
        return self.__axes

    def set_axes(self, axes: typing.Optional[LineGraphAxes]) -> None:
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            for line_graph_layer in self.__line_graph_layers:
                line_graph_layer.set_axes(axes)
            self.update()

    def update_line_graph_layers(self, line_graph_layers: typing.Sequence[LineGraphLayer], axes: typing.Optional[LineGraphAxes]) -> None:
        self.__line_graph_layers.clear()
        self.__line_graph_layers.extend(line_graph_layers)
        self.__axes = None  # forces set_axes to update
        self.set_axes(axes)

    @property
    def calibrated_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        # convenience function make older tests run
        return self.__line_graph_layers[0].calibrated_xdata if len(self.__line_graph_layers) > 0 else None

    @property
    def calibrated_data(self) -> typing.Optional[DataAndMetadata._ImageDataType]:
        # convenience function make older tests run
        calibrated_xdata = self.calibrated_xdata
        return calibrated_xdata.data if calibrated_xdata else None

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        canvas_bounds = self.canvas_bounds
        if canvas_bounds:
            line_graph_layers = list(self.__line_graph_layers)
            for line_graph_layer in reversed(line_graph_layers):
                line_graph_layer.calculate(canvas_bounds)
            for line_graph_layer in reversed(line_graph_layers):
                line_graph_layer.draw_fills(drawing_context)
            for line_graph_layer in reversed(line_graph_layers):
                line_graph_layer.draw_strokes(drawing_context)


class LineGraphRegionsCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot itself."""

    def __init__(self) -> None:
        super().__init__()
        self.font_size = 12
        self.__axes: typing.Optional[LineGraphAxes] = None
        self.__calibrated_data: typing.Optional[_NDArray] = None
        self.__regions: typing.List[RegionInfo] = list()

    def set_axes(self, axes: typing.Optional[LineGraphAxes]) -> None:
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.update()

    def set_calibrated_data(self, calibrated_data: typing.Optional[_NDArray]) -> None:
        if calibrated_data is None or self.__calibrated_data is None or not numpy.array_equal(calibrated_data, self.__calibrated_data):
            self.__calibrated_data = calibrated_data
            self.update()

    def set_regions(self, regions: typing.Sequence[RegionInfo]) -> None:
        if (self.__regions is None and regions is not None) or (self.__regions != regions):
            self.__regions = list(regions)
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        # draw the data, if any
        canvas_size = self.canvas_size
        if not canvas_size:
            return
        assert canvas_size

        data = self.__calibrated_data
        regions = self.__regions
        font_size = self.font_size

        if data is not None and len(data.shape) > 1:
            data = data[0, ...]

        axes = self.__axes
        if axes:
            # extract the data we need for drawing y-axis
            calibrated_data_min = axes.calibrated_data_min
            calibrated_data_max = axes.calibrated_data_max
            data_left = axes.drawn_left_channel
            data_right = axes.drawn_right_channel
            data_scale = axes.data_scale

            if data_right <= data_left:
                return

            plot_height = canvas_size.height - 1
            plot_origin_y = 0

            calibrated_data_range = calibrated_data_max - calibrated_data_min

            def convert_coordinate_to_pixel(canvas_size: Geometry.IntSize, c: float, data_scale: float, data_left: float, data_right: float) -> float:
                px = c * data_scale
                return canvas_size.width * (px - data_left) / (data_right - data_left)

            for region in regions:
                left_channel, right_channel = region.channels
                region_selected = region.selected
                index = region.index
                level = canvas_size.height - canvas_size.height * 0.8 + index * 8
                with drawing_context.saver():
                    drawing_context.clip_rect(0, 0, canvas_size.width, canvas_size.height)
                    if region.style == "tag" and data is not None:
                        if calibrated_data_range != 0.0:
                            channel = (left_channel + right_channel) / 2
                            data_index = int(channel * data.shape[0])
                            data_value = data[data_index] if 0 <= data_index < data.shape[0] else 0
                            py = plot_origin_y + plot_height - (plot_height * (data_value - calibrated_data_min) / calibrated_data_range)
                            py = max(plot_origin_y, py)
                            py = min(plot_origin_y + plot_height, py)
                            x = convert_coordinate_to_pixel(canvas_size, channel, data_scale, data_left, data_right)
                            with drawing_context.saver():
                                drawing_context.begin_path()
                                drawing_context.move_to(x, py - 3)
                                drawing_context.line_to(x, py - 13)
                                drawing_context.line_width = 1
                                drawing_context.stroke_style = region.color
                                if not region_selected:
                                    drawing_context.line_dash = 2
                                drawing_context.stroke()

                                label = region.label
                                if label:
                                    drawing_context.line_dash = 0
                                    drawing_context.fill_style = region.color
                                    drawing_context.font = "{0:d}px".format(font_size)
                                    drawing_context.text_align = "center"
                                    drawing_context.text_baseline = "bottom"
                                    drawing_context.fill_text(label, x, py - 16)
                    else:
                        drawing_context.begin_path()

                        left = convert_coordinate_to_pixel(canvas_size, left_channel, data_scale, data_left, data_right)
                        drawing_context.move_to(left, plot_origin_y)
                        drawing_context.line_to(left, plot_origin_y + plot_height)

                        right = convert_coordinate_to_pixel(canvas_size, right_channel, data_scale, data_left, data_right)
                        drawing_context.move_to(right, plot_origin_y)
                        drawing_context.line_to(right, plot_origin_y + plot_height)

                        drawing_context.line_width = 1
                        drawing_context.stroke_style = region.color
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
                            draw_marker(drawing_context, Geometry.FloatPoint(level, mid_x), fill=region.color, stroke=region.color)
                            drawing_context.fill_style = region.color
                            drawing_context.font = "{0:d}px".format(font_size)
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
                            draw_marker(drawing_context, Geometry.FloatPoint(level, mid_x), stroke=region.color)

                        label = region.label
                        if label:
                            drawing_context.line_dash = 0
                            drawing_context.fill_style = region.color
                            drawing_context.font = "{0:d}px".format(font_size)
                            drawing_context.text_align = "center"
                            drawing_context.text_baseline = "top"
                            drawing_context.fill_text(label, mid_x, level + 6)


class LineGraphFrameCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot frame."""

    def __init__(self) -> None:
        super().__init__()
        self.__draw_frame = True

    def set_draw_frame(self, draw_frame: bool) -> None:
        if self.__draw_frame != draw_frame:
            self.__draw_frame = draw_frame
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        canvas_bounds = self.canvas_bounds
        if canvas_bounds and self.__draw_frame:
            draw_frame(drawing_context, canvas_bounds.height - 1, canvas_bounds.left, canvas_bounds.top, canvas_bounds.width - 1)


class LineGraphHorizontalAxisTicksCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the horizontal tick marks."""

    def __init__(self) -> None:
        super().__init__()
        self.__axes: typing.Optional[LineGraphAxes] = None
        self.tick_height = 4
        self.update_sizing(self.sizing.with_fixed_height(self.tick_height))

    def set_axes(self, axes: typing.Optional[LineGraphAxes]) -> None:
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        # draw the data, if any
        axes = self.__axes
        canvas_size = self.canvas_size
        if axes and canvas_size:
            plot_width = canvas_size.width - 1
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

    def __init__(self) -> None:
        super().__init__()
        self.__axes: typing.Optional[LineGraphAxes] = None
        self.font_size = 12
        self.update_sizing(self.sizing.with_fixed_height(self.font_size + 4))

    def set_axes(self, axes: typing.Optional[LineGraphAxes]) -> None:
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:

        # draw the data, if any
        axes = self.__axes
        canvas_size = self.canvas_size
        if axes and canvas_size:

            # extract the data we need for drawing x-axis
            x_ticks = axes.calculate_x_ticks(canvas_size.width - 1)

            # draw the tick marks
            with drawing_context.saver():
                drawing_context.font = "{0:d}px".format(self.font_size)
                for x, label in x_ticks:
                    drawing_context.text_align = "center"
                    drawing_context.text_baseline = "middle"
                    drawing_context.fill_style = "#000"
                    drawing_context.fill_text(label, x, canvas_size.height * 0.5)


class LineGraphHorizontalAxisLabelCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the horizontal label."""

    def __init__(self) -> None:
        super().__init__()
        self.__axes: typing.Optional[LineGraphAxes] = None
        self.font_size = 12
        self.update_sizing(self.sizing.with_fixed_height(self.font_size + 4))

    def size_to_content(self) -> None:
        """ Size the canvas item to the proper height. """
        new_sizing = self.copy_sizing()
        new_sizing = new_sizing.with_minimum_height(0)
        new_sizing = new_sizing.with_maximum_height(0)
        axes = self.__axes
        if axes:
            if axes.x_calibration and axes.x_calibration.units:
                new_sizing = new_sizing.with_minimum_height(self.font_size + 4)
                new_sizing = new_sizing.with_maximum_height(self.font_size + 4)
        self.update_sizing(new_sizing)

    def set_axes(self, axes: typing.Optional[LineGraphAxes]) -> None:
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.size_to_content()
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        # draw the data, if any
        axes = self.__axes
        canvas_size = self.canvas_size
        if axes and canvas_size:
            # draw the horizontal axis
            if axes.x_calibration and axes.x_calibration.units:
                plot_width = canvas_size.width - 1
                with drawing_context.saver():
                    drawing_context.text_align = "center"
                    drawing_context.text_baseline = "middle"
                    drawing_context.fill_style = "#000"
                    value_str = u"({0})".format(axes.x_calibration.units)
                    drawing_context.font = "{0:d}px".format(self.font_size)
                    drawing_context.fill_text(value_str, plot_width * 0.5, canvas_size.height * 0.5)


class LineGraphVerticalAxisTicksCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the vertical tick marks."""

    def __init__(self) -> None:
        super().__init__()
        self.__axes: typing.Optional[LineGraphAxes] = None
        self.tick_width = 4
        self.update_sizing(self.sizing.with_fixed_width(self.tick_width))

    def set_axes(self, axes: typing.Optional[LineGraphAxes]) -> None:
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        # draw the data, if any
        axes = self.__axes
        canvas_size = self.canvas_size
        if axes and canvas_size:
            # extract the data we need for drawing y-axis
            y_ticks = axes.calculate_y_ticks(canvas_size.height - 1)
            # draw the y_ticks and labels
            with drawing_context.saver():
                for y, _, _ in y_ticks:
                    drawing_context.begin_path()
                    drawing_context.move_to(canvas_size.width, y)
                    drawing_context.line_to(canvas_size.width - self.tick_width, y)
                    drawing_context.line_width = 1
                    drawing_context.stroke_style = '#888'
                    drawing_context.stroke()


class Exponenter:

    def __init__(self) -> None:
        self.__labels_list: typing.List[typing.List[str]] = list()

    def add_label(self, label: str) -> None:
        labels = label.lower().split("e")
        if len(labels) == 2:
            labels[1] = str(int(labels[1]))
            self.__labels_list.append(labels)
        else:
            self.__labels_list.append(labels + [""])

    def used_labels(self, label: str) -> typing.Tuple[str, str]:
        labels = label.lower().split("e")
        if len(labels) == 2:
            labels[1] = str(int(labels[1]))
            if set(labels[1] for labels in self.__labels_list) == {"0"}:
                return labels[0], ""
            if set(labels[0] for labels in self.__labels_list) == {"1"}:
                return "10", labels[1]
            return labels[0] + " x 10", labels[1]
        else:
            return labels[0], ""

    def draw_scientific_notation(self, drawing_context: DrawingContext.DrawingContext, ui_settings: UISettings.UISettings, fonts: typing.Tuple[str, str], label: str, width: int, y: float) -> None:
        labels = self.used_labels(label)
        if labels[1] is not None:
            mw = max([ui_settings.get_font_metrics(fonts[1], _labels[1]).width for _labels in self.__labels_list], default=0)
            drawing_context.font = fonts[0]
            drawing_context.text_align = "right"
            drawing_context.fill_text(labels[0], width - mw, y)
            drawing_context.font = fonts[1]
            drawing_context.text_align = "left"
            drawing_context.fill_text(labels[1], width - mw, y - 4)
        else:
            drawing_context.fill_text(label, width, y)


_LABEL_SIZE_CALCULATION_NORMALIZE_RE = re.compile(r"\d")


def _normalize_label_for_size_calculation(label: str) -> str:
    return _LABEL_SIZE_CALCULATION_NORMALIZE_RE.sub("0", label)


def calculate_scientific_notation_drawing_width(ui_settings: UISettings.UISettings, fonts: typing.Tuple[str, str], label: str) -> int:
    labels = label.lower().split("e")
    if len(labels) == 2:
        labels[0] = labels[0] + " x 10"
        labels[1] = str(int(labels[1]))
    return sum(ui_settings.get_font_metrics(font, _normalize_label_for_size_calculation(label)).width
               for font, label in zip(fonts, labels))



class LineGraphVerticalAxisScaleCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the vertical scale."""

    def __init__(self) -> None:
        super().__init__()
        self.__axes: typing.Optional[LineGraphAxes] = None
        self.font_size = 12
        self.__fonts = ("{0:d}px".format(self.font_size), "{0:d}px".format(int(self.font_size * 0.8)))
        self.__ui_settings: typing.Optional[UISettings.UISettings] = None

    def size_to_content(self, ui_settings: UISettings.UISettings) -> None:
        """ Size the canvas item to the proper width, the maximum of any label. """
        new_sizing = self.copy_sizing()

        new_sizing = new_sizing.with_minimum_width(0)
        new_sizing = new_sizing.with_maximum_width(0)

        axes = self.__axes
        if axes:
            # calculate the width based on the label lengths
            max_width = 0
            y_range = axes.calibrated_value_max - axes.calibrated_value_min
            max_width = max(max_width, calculate_scientific_notation_drawing_width(ui_settings, self.__fonts, axes.y_ticker.value_label(axes.calibrated_value_max + y_range * 5)))
            max_width = max(max_width, calculate_scientific_notation_drawing_width(ui_settings, self.__fonts, axes.y_ticker.value_label(axes.calibrated_value_min - y_range * 5)))
            new_sizing = new_sizing.with_minimum_width(max_width)
            new_sizing = new_sizing.with_maximum_width(max_width)

        self.update_sizing(new_sizing)

        self.__ui_settings = ui_settings  # hack

    def set_axes(self, axes: typing.Optional[LineGraphAxes], ui_settings: UISettings.UISettings) -> None:
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.size_to_content(ui_settings)
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        # draw the data, if any
        axes = self.__axes
        canvas_size = self.canvas_size
        if canvas_size and axes:
            label: typing.Optional[str] = None
            y: typing.Optional[float] = None

            # canvas size
            width = canvas_size.width
            plot_height = canvas_size.height - 1

            # extract the data we need for drawing y-axis
            y_ticks = axes.calculate_y_ticks(plot_height, flag_minor=True)
            include_minor_ticks = plot_height / self.font_size > 2.5 * axes.y_ticker.ticks
            at_least_one = False

            e = Exponenter()
            for y, label, is_minor in y_ticks:
                if include_minor_ticks or not is_minor:
                    e.add_label(label)
                    at_least_one = True

            # draw the y_ticks and labels
            with drawing_context.saver():
                drawing_context.text_baseline = "middle"
                drawing_context.font = "{0:d}px".format(self.font_size)
                for y, label, is_minor in y_ticks:
                    drawing_context.begin_path()
                    drawing_context.stroke_style = '#888'
                    drawing_context.stroke()
                    if (include_minor_ticks or not is_minor) and self.__ui_settings:
                        drawing_context.fill_style = "#000"
                        e.draw_scientific_notation(drawing_context, self.__ui_settings, self.__fonts, label, width, y)
                        at_least_one = True
                if not at_least_one and y_ticks and y is not None and label is not None and self.__ui_settings:
                    drawing_context.fill_style = "#000"
                    e.draw_scientific_notation(drawing_context, self.__ui_settings, self.__fonts, label, width, y)


class LineGraphVerticalAxisLabelCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the vertical label."""

    def __init__(self) -> None:
        super().__init__()
        self.__axes: typing.Optional[LineGraphAxes] = None
        self.font_size = 12
        self.update_sizing(self.sizing.with_fixed_width(self.font_size + 4))

    def size_to_content(self) -> None:
        """ Size the canvas item to the proper width. """
        new_sizing = self.copy_sizing()
        new_sizing = new_sizing.with_minimum_width(0)
        new_sizing = new_sizing.with_maximum_width(0)
        axes = self.__axes
        if axes:
            if axes.y_calibration and axes.y_calibration.units:
                new_sizing = new_sizing.with_minimum_width(self.font_size + 4)
                new_sizing = new_sizing.with_maximum_width(self.font_size + 4)
        self.update_sizing(new_sizing)

    def set_axes(self, axes: typing.Optional[LineGraphAxes]) -> None:
        if not are_axes_equal(self.__axes, axes):
            self.__axes = axes
            self.size_to_content()
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:

        # draw the data, if any
        axes = self.__axes
        canvas_size = self.canvas_size
        if axes and canvas_size:
            if axes.y_calibration and axes.y_calibration.units:
                with drawing_context.saver():
                    drawing_context.font = "{0:d}px".format(self.font_size)
                    drawing_context.text_align = "center"
                    drawing_context.text_baseline = "middle"
                    drawing_context.fill_style = "#000"
                    x = canvas_size.width * 0.5
                    y = (canvas_size.height - 1) // 2
                    drawing_context.translate(x, y)
                    drawing_context.rotate(-math.pi*0.5)
                    drawing_context.translate(-x, -y)
                    drawing_context.font = "{0:d}px".format(self.font_size)
                    drawing_context.fill_text(axes.y_calibration.units, x, y)
                    drawing_context.translate(x, y)
                    drawing_context.rotate(+math.pi*0.5)
                    drawing_context.translate(-x, -y)


class LineGraphLegendCanvasItemDelegate(typing.Protocol):
    """Delegate for the line graph legend canvas item.

    A set of actions initiated by the legend canvas item that the delegate must implement.
    """

    def create_move_display_layer_command(self, display_item: DisplayItem.DisplayItem, src_index: int, target_index: int) -> Undo.UndoableCommand: ...

    def push_undo_command(self, command: Undo.UndoableCommand) -> None: ...

    def create_mime_data(self) -> UserInterface.MimeData: ...

    def get_display_item(self) -> DisplayItem.DisplayItem: ...

    def get_document_model(self) -> DocumentModel.DocumentModel: ...

    def create_rgba_image(self, drawing_context: DrawingContext.DrawingContext, width: int, height: int) -> _NDArray: ...


class LineGraphLegendCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw the line plot legend."""

    def __init__(self, ui_settings: UISettings.UISettings, delegate: LineGraphLegendCanvasItemDelegate) -> None:
        super().__init__()

        self.__delegate = delegate

        # current legend items corresponding to layers of the display item
        self.__legend_entries: typing.List[LegendEntry] = list()

        # reordered/inserted entries that have not yet been applied
        self.__effective_entries: typing.List[LegendEntry] = list()

        # True when a user is clicking, but a drag hasn't started because they haven't moved the mouse enough
        self.__mouse_pressed_for_dragging = False

        # This is true when we're dragging from a local display item or foreign display item.
        self.__mouse_dragging = False

        # Tracks where the drag started from
        self._drag_start_position: typing.Optional[Geometry.IntPoint] = None

        # The index of the local entry we're currently dragging
        self.__dragging_index: typing.Optional[int] = None

        # The entry where the mouse is over so we know where to reorder the entry to
        self.__entry_to_insert: typing.Optional[int] = None

        # An entry from another display item that we're dragging into this one
        self.__foreign_legend_entry: typing.Optional[LegendEntry] = None

        # The index and UUID of the other display item layer we're dragging here
        self.__foreign_legend_uuid_and_index: typing.Optional[typing.Tuple[DisplayItem.DisplayItem, int]] = None

        # canvas item settings
        self.wants_mouse_events = True
        self.wants_drag_events = True
        self.__ui_settings = ui_settings
        self.font_size = 12

    def __generate_effective_entries(self) -> None:
        """
        This function generates a new effective entries array based on how the user is dragging legend items and updates
        the bounds of the canvas item as needed.
        """
        effective_entries = list(self.__legend_entries)  # copy

        if self.__mouse_dragging and self.__entry_to_insert is not None and self.__dragging_index is not None:
            # move legend entry from dragging_index to entry_to_insert
            effective_entries.insert(self.__entry_to_insert, effective_entries.pop(self.__dragging_index))

        self.__effective_entries = effective_entries

        self.size_to_content()

    def size_to_content(self) -> None:
        line_height = self.font_size + 4
        border = 4

        legend_height = len(self.__effective_entries) * line_height + border * 2

        if len(self.effective_entries) == 0:
            legend_height = 0

        text_width = 0
        font = "{0:d}px".format(self.font_size)

        for index, legend_entry in enumerate(self.effective_entries):
            text_width = max(text_width, self.__ui_settings.get_font_metrics(font, legend_entry.label).width)

        legend_width = text_width + border * 2 + line_height

        new_sizing = self.copy_sizing().with_fixed_width(legend_width).with_fixed_height(legend_height)
        self.update_sizing(new_sizing)

    def wants_drag_event(self, mime_data: UserInterface.MimeData, x: int, y: int) -> bool:
        return mime_data.has_format(MimeTypes.LAYER_MIME_TYPE)

    def set_legend_entries(self, legend_entries: typing.Sequence[LegendEntry]) -> None:
        if self.__legend_entries != legend_entries:
            self.__legend_entries = list(legend_entries)
            self.__generate_effective_entries()
            self.update()

    def __get_legend_index(self, x: int, y: int, ignore_y: bool = False, insertion: bool = False) -> int:
        # Returns the current index at a certain x and y if over a legend item, otherwise returns -1. If ignore_y is set,
        # it will always return a value at the closest y value. (useful for determining where to drop an item). If
        # insertion is set, the index will be capped between 0 and length (instead of 0 and length-1) so that we can tell
        # if a user is trying to drop the item at the end of the list.

        legend_entries = self.__legend_entries

        legend_width = 0
        line_height = self.font_size + 4
        border = 4
        font = "{0:d}px".format(self.font_size)

        for index, legend_entry in enumerate(legend_entries):
            legend_width = max(legend_width, self.__ui_settings.get_font_metrics(font, legend_entry.label).width)

        end_x = legend_width + line_height + border * 2

        index = y // line_height

        # if ignore_y is not on, we return the index if in bounds and -1 otherwise
        if not ignore_y:
            if 0 <= x <= end_x and 0 <= index < len(self.__legend_entries):
                return index
            else:
                return -1
        else:
            end_index = len(self.__legend_entries) - (1 if not insertion else 0)
            # return the current item, clamped to length-1 and 0
            return max(min(index, end_index), 0)

    def __get_icon_for_layer(self, fill: typing.Optional[str]) -> _NDArray:
        border = 1
        drawing_context = DrawingContext.DrawingContext()
        icon_size = 16
        with drawing_context.saver():
            drawing_context.begin_path()
            drawing_context.rect(0, 0, icon_size, icon_size)
            drawing_context.fill_style = "rgba(0, 0, 0, 1.0)"
            drawing_context.fill()

        with drawing_context.saver():
            drawing_context.begin_path()
            drawing_context.rect(border, border, icon_size - 2 * border, icon_size - 2 * border)
            drawing_context.fill_style = fill
            drawing_context.fill()

        return self.__delegate.create_rgba_image(drawing_context, icon_size, icon_size)

    def mouse_position_changed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        # if the mouse is pressed and the distance it greater than the distance to start dragging, start the drag using
        # the selected layer as the mime type.
        drag_start_position = self._drag_start_position
        dragging_index = self.__dragging_index
        if drag_start_position is None or dragging_index is None:
            return False
        if self.__mouse_pressed_for_dragging and Geometry.distance(drag_start_position.to_float_point(), Geometry.FloatPoint(y=y, x=x)) > 1:
            mime_data = self.__delegate.create_mime_data()
            layer = self.__legend_entries[dragging_index]
            MimeTypes.mime_data_put_layer(mime_data, dragging_index, self.__delegate.get_display_item(), layer.label, layer.fill_color, layer.stroke_color)
            thumbnail_data = self.__get_icon_for_layer(layer.fill_color)
            self.drag(mime_data, thumbnail_data)
            self.update()
            return True
        return False

    def drag_move(self, mime_data: UserInterface.MimeData, x: int, y: int) -> str:
        # get the entry the mouse was over
        old_entry = self.__entry_to_insert

        # find the current entry the mouse is over
        self.__entry_to_insert = self.__get_legend_index(x, y, True, self.__foreign_legend_entry is not None)
        if old_entry != self.__entry_to_insert:
            # update effective entries and the display if it changed
            self.__generate_effective_entries()
            self.update()
        return "ignore"

    def mouse_pressed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        # if there are less than 2 entries, ignore this because a data item can't be empty
        if self.__legend_entries and len(self.__legend_entries) > 1:
            # find the current legend index if there is one
            i = self.__get_legend_index(x, y)
            if i != -1:
                # signal we want to start dragging with this item
                self.__mouse_pressed_for_dragging = True
                self.__dragging_index = i
                self._drag_start_position = Geometry.IntPoint(x=x, y=y)
                self.__entry_to_insert = i
                self.update()

                return True
        return False

    def mouse_released(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        self.__mouse_pressed_for_dragging = False
        self.__dragging_index = None
        self._drag_start_position = None
        self.__entry_to_insert = None
        self.__generate_effective_entries()
        self.update()
        return True

    def drag_leave(self) -> str:
        self._drag_start_position = None
        self.__mouse_dragging = False
        self.__mouse_pressed_for_dragging = False
        self.__entry_to_insert = None
        self.__dragging_index = None
        self.__foreign_legend_entry = None
        self.__foreign_legend_uuid_and_index = None
        # when we leave the drag area, update the effective entries because we're no longer previewing a shift
        self.__generate_effective_entries()
        self.update()
        return "ignore"

    def drag_enter(self, mime_data: UserInterface.MimeData) -> str:
        # if a new drag comes in with layer mime data, check if we're the source or if this is a foreign layer
        if mime_data.has_format(MimeTypes.LAYER_MIME_TYPE):
            self.__mouse_dragging = True
            legend_data, display_item = MimeTypes.mime_data_get_layer(mime_data, self.__delegate.get_document_model())
            if display_item == self.__delegate.get_display_item():
                # if we're the source, setup the index and update the drag preview
                self.__dragging_index = legend_data["index"]
                self.__mouse_pressed_for_dragging = True
                self.__generate_effective_entries()
                self.update()
            else:
                # if we aren't the source, setup foreign_legend_* and update the display
                assert display_item
                self.__foreign_legend_entry = LegendEntry(label=legend_data["label"], fill_color=legend_data["fill_color"], stroke_color=legend_data["stroke_color"])
                self.__foreign_legend_uuid_and_index = (display_item, typing.cast(int, legend_data["index"]))
                self.update()
            return "move"
        return "ignore"

    def drop(self, mime_data: UserInterface.MimeData, x: int, y: int) -> str:
        # stop dragging
        self._drag_start_position = None
        self.__mouse_pressed_for_dragging = False
        self.__mouse_dragging = False

        if mime_data.has_format(MimeTypes.LAYER_MIME_TYPE):
            legend_data, source_display_item = MimeTypes.mime_data_get_layer(mime_data, self.__delegate.get_document_model())
            from_index = legend_data["index"]
            if source_display_item == self.__delegate.get_display_item():
                # if we're the source item, just shift the layers
                if from_index != self.__entry_to_insert:
                    assert self.__entry_to_insert is not None
                    command = self.__delegate.create_move_display_layer_command(source_display_item, from_index, self.__entry_to_insert)
                    command.perform()
                    self.__entry_to_insert = None
                    self.__delegate.push_undo_command(command)
            else:
                assert self.__entry_to_insert is not None
                assert source_display_item

                # if we aren't the source item, move the display layer between display items
                command = self.__delegate.create_move_display_layer_command(source_display_item, from_index, self.__entry_to_insert)

                self.__foreign_legend_entry = None
                self.__foreign_legend_uuid_and_index = None

                # TODO: perform only if the display channel doesn't exist in the target
                command.perform()
                self.__delegate.push_undo_command(command)
            self.update()
            return "move"
        return "ignore"

    @property
    def effective_entries(self) -> typing.Sequence[LegendEntry]:
        return self.__effective_entries

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        # don't display the canvas item if there are less than two items
        if self.__legend_entries is None or len(self.__legend_entries) < 2:
            return

        font = "{0:d}px".format(self.font_size)

        legend_width = 0
        for index, legend_entry in enumerate(self.__effective_entries):
            legend_width = max(legend_width, self.__ui_settings.get_font_metrics(font, legend_entry.label).width)

        line_height = self.font_size + 4
        border = 4
        font = "{0:d}px".format(self.font_size)

        effective_entries_and_foreign = list(self.__effective_entries)
        if self.__foreign_legend_entry is not None and self.__entry_to_insert is not None:
            effective_entries_and_foreign.insert(self.__entry_to_insert, self.__foreign_legend_entry)

        legend_height = len(effective_entries_and_foreign) * line_height

        with drawing_context.saver():
            drawing_context.begin_path()
            drawing_context.rect(0,
                                 0,
                                 legend_width + border * 2 + line_height,
                                 legend_height + border * 2)
            drawing_context.fill_style = "rgba(192, 192, 192, 0.5)"
            drawing_context.fill()

        if self.__mouse_pressed_for_dragging or self.__foreign_legend_entry is not None:
            with drawing_context.saver():
                drawing_context.begin_path()
                entry_to_insert = self.__entry_to_insert or 0  # for type checking
                drawing_context.rect(0,
                                     entry_to_insert * line_height + border,
                                     legend_width + border * 2 + line_height,
                                     line_height)
                drawing_context.fill_style = "rgba(192, 192, 192, 0.5)"
                drawing_context.fill()

        for index, legend_entry in enumerate(effective_entries_and_foreign):
            with drawing_context.saver():
                drawing_context.font = font
                drawing_context.text_align = "right"
                drawing_context.text_baseline = "bottom"
                drawing_context.fill_style = "#000"
                drawing_context.fill_text(legend_entry.label, legend_width + border, line_height * (index + 1) - 4 + border)

                drawing_context.begin_path()
                drawing_context.rect(legend_width + border + 3, line_height * index + 3 + border, line_height - 6, line_height - 6)
                if legend_entry.fill_color:
                    drawing_context.fill_style = legend_entry.fill_color
                    drawing_context.fill()
                if legend_entry.stroke_color:
                    drawing_context.stroke_style = legend_entry.stroke_color
                    drawing_context.stroke()
