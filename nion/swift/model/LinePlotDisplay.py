"""A collection of classes to used in line graph drawing."""

from __future__ import annotations

# standard libraries
import dataclasses
import math
import typing
import warnings

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import DisplayInfo
from nion.utils import Color
from nion.utils import Geometry


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


def nice_label(value: float, precision: int) -> str:
    if math.trunc(math.log10(abs(value) + numpy.nextafter(0, 1))) > 4:
        return (u"{0:0." + u"{0:d}".format(precision) + "e}").format(value)
    else:
        return (u"{0:0." + u"{0:d}".format(precision) + "f}").format(value)


class AxisScale(typing.Protocol):

    @property
    def axis_scale_id(self) -> str: ...

    def make_ticker(self, display_min: float, display_max: float) -> Geometry.Ticker: ...

    def convert_calibrated_value_to_scaled_value(self, calibrated_value: float) -> float: ...

    def convert_scaled_value_to_calibrated_value(self, scaled_value: float) -> float: ...

    def convert_calibrated_array_to_scaled_array(self, calibrated_xdata: DataAndMetadata.DataAndMetadata) -> DataAndMetadata.DataAndMetadata | None: ...

    def display_origin(self, display_min: float, display_max: float) -> float: ...

    def adjust_calibrated_limits(self, calibrated_min: float | None, calibrated_max: float | None, min_specified: bool, max_specified: bool) -> tuple[float, float]: ...


class LinearAxisScale(AxisScale):
    axis_scale_id = "linear"

    def make_ticker(self, display_min: float, display_max: float) -> Geometry.Ticker:
        return Geometry.LinearTicker(display_min, display_max)

    def convert_calibrated_value_to_scaled_value(self, calibrated_value: float) -> float:
        return calibrated_value

    def convert_scaled_value_to_calibrated_value(self, scaled_value: float) -> float:
        return scaled_value

    def convert_calibrated_array_to_scaled_array(self, calibrated_xdata: DataAndMetadata.DataAndMetadata) -> DataAndMetadata.DataAndMetadata | None:
        return calibrated_xdata

    def display_origin(self, display_min: float, display_max: float) -> float:
        if display_min <= 0.0 <= display_max:
            return 0.0
        return display_min if 0.0 < display_min else display_max

    def adjust_calibrated_limits(self, calibrated_min: float | None, calibrated_max: float | None, min_specified: bool, max_specified: bool) -> tuple[float, float]:
        if (calibrated_min is None) or (not min_specified and calibrated_min > 0.0):
            calibrated_min = 0.0
        if (calibrated_max is None) or (not max_specified and calibrated_max < 0.0):
            calibrated_max = 0.0
        return calibrated_min, calibrated_max


class LogAxisScale(AxisScale):
    axis_scale_id = "log"

    def make_ticker(self, display_min: float, display_max: float) -> Geometry.Ticker:
        return Geometry.LogTicker(display_min, display_max)

    def convert_calibrated_value_to_scaled_value(self, calibrated_value: float) -> float:
        return math.log10(calibrated_value) if calibrated_value > 0 else float("-inf")

    def convert_scaled_value_to_calibrated_value(self, scaled_value: float) -> float:
        return math.pow(10, scaled_value)

    def convert_calibrated_array_to_scaled_array(self, calibrated_xdata: DataAndMetadata.DataAndMetadata) -> DataAndMetadata.DataAndMetadata | None:
        scaled_data = numpy.log10(numpy.where(calibrated_xdata.data <= 0, numpy.nan, calibrated_xdata.data.astype(float)))
        return DataAndMetadata.new_data_and_metadata(
            scaled_data,
            intensity_calibration=Calibration.Calibration(units=calibrated_xdata.intensity_calibration.units),
            dimensional_calibrations=calibrated_xdata.dimensional_calibrations
        )

    def display_origin(self, display_min: float, display_max: float) -> float:
        return display_min

    def adjust_calibrated_limits(self, calibrated_min: float | None, calibrated_max: float | None, min_specified: bool, max_specified: bool) -> tuple[float, float]:
        min_val = calibrated_min if calibrated_min is not None else 0.0
        max_val = calibrated_max if calibrated_max is not None else 0.0
        return min_val, max_val


_axis_scale_types: dict[str, AxisScale] = {
    "linear": LinearAxisScale(),
    "log": LogAxisScale()
}

def _get_axis_scale(axis_scale_id: str | None) -> AxisScale:
    # return the axis scale for the optional axis_scale_id, or the linear style if not found
    axis_scale = _axis_scale_types.get(axis_scale_id, None) if axis_scale_id else None
    return axis_scale if axis_scale else LinearAxisScale()


def calculate_scaled_xdata(xdata: DataAndMetadata.DataAndMetadata, axis_scale: AxisScale) -> DataAndMetadata.DataAndMetadata | None:
    """Calculate the 'scaled xdata' for the given xdata and axis scale.

    The 'scaled xdata' is the xdata (with a calibration) but with a new intensity calibration where origin=0 and scale=1.
    """
    scalar_uncalibrated_data = xdata.data if not xdata.is_data_rgb_type else Image.convert_to_grayscale(xdata.data)
    calibrated_data = xdata.intensity_calibration.convert_array_to_calibrated_value(scalar_uncalibrated_data)
    calibrated_xdata = DataAndMetadata.new_data_and_metadata(
        calibrated_data,
        intensity_calibration=Calibration.Calibration(units=xdata.intensity_calibration.units),
        dimensional_calibrations=xdata.dimensional_calibrations
    )
    return axis_scale.convert_calibrated_array_to_scaled_array(calibrated_xdata)


def calculate_y_axis(xdata_list: typing.Sequence[DataAndMetadata.DataAndMetadata | None], data_min: float | None, data_max: float | None, axis_scale_id: str | None) -> tuple[float, float, Geometry.Ticker]:
    """Calculate the calibrated min/max and y-axis ticker for list of xdata.

    xdata_list is the original calibrated data
    data_min and data_max are calibrated values

    Returns scaled_data_min, scaled_data_max, ticker
    """
    min_specified = data_min is not None
    max_specified = data_max is not None

    scaled_data_min_opt: float | None = None
    scaled_data_max_opt: float | None = None

    axis_scale = _get_axis_scale(axis_scale_id)

    # Determine min/max in calibrated data space before converting to display space
    for xdata in xdata_list:
        if xdata and xdata.data_shape[-1] > 0:
            scaled_xdata = calculate_scaled_xdata(xdata, axis_scale)
            if scaled_xdata is not None:
                scaled_data = scaled_xdata.data if numpy.issubdtype(scaled_xdata.data.dtype, numpy.floating) else scaled_xdata.data.astype(float)
                if scaled_data is not None and scaled_data.size > 0:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", category=RuntimeWarning)
                        scaled_data_min = float(numpy.nanmin(scaled_data))
                        scaled_data_max = float(numpy.nanmax(scaled_data))
                    if numpy.isfinite(scaled_data_min):
                        scaled_data_min_opt = scaled_data_min if scaled_data_min_opt is None else min(scaled_data_min_opt, scaled_data_min)
                    if numpy.isfinite(scaled_data_max):
                        scaled_data_max_opt = scaled_data_max if scaled_data_max_opt is None else max(scaled_data_max_opt, scaled_data_max)

    if min_specified:
        calibrated_min = typing.cast(float, data_min)
    else:
        if scaled_data_min_opt is not None:
            calibrated_min = axis_scale.convert_scaled_value_to_calibrated_value(scaled_data_min_opt)
        else:
            calibrated_min = None

    if max_specified:
        calibrated_max = typing.cast(float, data_max)
    else:
        if scaled_data_max_opt is not None:
            calibrated_max = axis_scale.convert_scaled_value_to_calibrated_value(scaled_data_max_opt)
        else:
            calibrated_max = None

    adjusted_calibrated_min, adjusted_calibrated_max = axis_scale.adjust_calibrated_limits(calibrated_min, calibrated_max, min_specified, max_specified)

    # Convert calibrated limits to display space
    scaled_data_min = axis_scale.convert_calibrated_value_to_scaled_value(adjusted_calibrated_min)
    scaled_data_max = axis_scale.convert_calibrated_value_to_scaled_value(adjusted_calibrated_max)
    if math.isnan(scaled_data_min) or math.isinf(scaled_data_min):
        scaled_data_min = 0.0
    if math.isnan(scaled_data_max) or math.isinf(scaled_data_max):
        scaled_data_max = 0.0
    scaled_data_min, scaled_data_max = min(scaled_data_min, scaled_data_max), max(scaled_data_min, scaled_data_max)
    if scaled_data_min == scaled_data_max:
        scaled_data_min -= 1.0
        scaled_data_max += 1.0

    ticker = axis_scale.make_ticker(scaled_data_min, scaled_data_max)
    if not min_specified:
        scaled_data_min = ticker.minimum
    if not max_specified:
        scaled_data_max = ticker.maximum

    return scaled_data_min, scaled_data_max, ticker


@dataclasses.dataclass
class LegendEntry:
    label: str
    fill_color: typing.Optional[str]
    stroke_color: typing.Optional[str]


class LineGraphAxes:
    """Track information about line graph axes."""

    def __init__(self, data_scale: float, scaled_data_min: float, scaled_data_max: float, data_left: int,
                 data_right: int, x_calibration: typing.Optional[Calibration.Calibration],
                 y_calibration: typing.Optional[Calibration.Calibration], axis_scale_id: typing.Optional[str],
                 y_ticker: Geometry.Ticker) -> None:
        assert x_calibration is None or x_calibration.is_valid
        assert y_calibration is None or y_calibration.is_valid
        # these items are considered to be input items
        self.data_scale = data_scale
        self.__uncalibrated_left_channel = data_left
        self.__uncalibrated_right_channel = data_right
        self.x_calibration = x_calibration
        self.y_calibration = y_calibration
        self.axis_scale = _get_axis_scale(axis_scale_id)
        self.__scaled_data_min = scaled_data_min
        self.__scaled_data_max = scaled_data_max
        self.__y_ticker = y_ticker

    def __repr__(self) -> str:
        return f"Axes {self.drawn_left_channel}:{self.drawn_right_channel} [{self.scaled_data_min},{self.scaled_data_max} {self.x_calibration} {self.y_calibration} {self.axis_scale} {self.data_scale}"

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, LineGraphAxes):
            return False
        return (self.data_scale == other.data_scale and
                self.__uncalibrated_left_channel == other.__uncalibrated_left_channel and
                self.__uncalibrated_right_channel == other.__uncalibrated_right_channel and
                self.x_calibration == other.x_calibration and
                self.y_calibration == other.y_calibration and
                self.axis_scale.axis_scale_id == other.axis_scale.axis_scale_id and
                self.__scaled_data_min == other.__scaled_data_min and
                self.__scaled_data_max == other.__scaled_data_max and
                self.__y_ticker == other.__y_ticker)

    def __hash__(self) -> int:
        return hash((self.data_scale, self.__uncalibrated_left_channel, self.__uncalibrated_right_channel, self.x_calibration, self.y_calibration, self.axis_scale.axis_scale_id, self.__scaled_data_min, self.__scaled_data_max, self.__y_ticker))

    @property
    def y_ticker(self) -> Geometry.Ticker:
        return self.__y_ticker

    @property
    def uncalibrated_data_min(self) -> float:
        y_calibration = self.y_calibration if self.y_calibration else Calibration.Calibration()
        calibrated_value_min = self.axis_scale.convert_scaled_value_to_calibrated_value(self.scaled_data_min)
        return y_calibration.convert_from_calibrated_value(calibrated_value_min)

    @property
    def uncalibrated_data_max(self) -> float:
        y_calibration = self.y_calibration if self.y_calibration else Calibration.Calibration()
        calibrated_value_max = self.axis_scale.convert_scaled_value_to_calibrated_value(self.scaled_data_max)
        return y_calibration.convert_from_calibrated_value(calibrated_value_max)

    @property
    def scaled_data_min(self) -> float:
        return self.__scaled_data_min

    @property
    def scaled_data_max(self) -> float:
        return self.__scaled_data_max

    @property
    def calibrated_value_max(self) -> float:
        calibrated_value = self.axis_scale.convert_scaled_value_to_calibrated_value(self.__scaled_data_max)
        return calibrated_value

    @property
    def calibrated_value_min(self) -> float:
        calibrated_value = self.axis_scale.convert_scaled_value_to_calibrated_value(self.__scaled_data_min)
        return calibrated_value

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

        calibrated_data_min = self.scaled_data_min
        calibrated_data_max = self.scaled_data_max
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

    def convert_scaled_y_value_to_uncalibrated_value(self, scaled_y_value: float) -> float:
        calibrated_y_value = self.axis_scale.convert_scaled_value_to_calibrated_value(scaled_y_value)
        y_calibration = self.y_calibration
        if y_calibration:
            return y_calibration.convert_from_calibrated_value(calibrated_y_value)
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

    def convert_calibrated_array_to_scaled_array(self, xdata: DataAndMetadata.DataAndMetadata) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        """Calculate the 'calibrated xdata'.

         The 'calibrated xdata' is the xdata (with a calibration) but with a new intensity calibration where origin=0 and scale=1.
         """
        return calculate_scaled_xdata(xdata, self.axis_scale)


class LineGraphLayer:
    """Represents a layer of the line graph.

    xdata is calibrated data.

    Tracks the data, calibrated data, axes. Provides methods to calculate the segments and draw fills/strokes separately.
    """

    def __init__(self,
                 xdata: typing.Optional[DataAndMetadata.DataAndMetadata],
                 axes: typing.Optional[LineGraphAxes],
                 fill_color: typing.Optional[Color.Color],
                 stroke_color: typing.Optional[Color.Color],
                 stroke_width: typing.Optional[float]) -> None:
        self.__xdata = xdata
        self.__fill_color = fill_color
        self.__stroke_color = stroke_color
        self.__stroke_width = stroke_width or 0.5
        self.__canvas_bounds: typing.Optional[Geometry.IntRect] = None
        self.__calibrated_xdata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.__axes = axes

    def __repr__(self) -> str:
        data_sum = numpy.sum(self.__xdata) if self.__xdata else 0.0
        return f"LineGraphLayer {data_sum} {self.__fill_color} {self.__stroke_color} {self.__stroke_width} {self.__axes}"

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, LineGraphLayer):
            return False
        return (self.__xdata is not None and other.__xdata is not None and self.__xdata.data is other.__xdata.data and
                self.__fill_color == other.__fill_color and
                self.__stroke_color == other.__stroke_color and
                self.__stroke_width == other.__stroke_width and
                self.__axes == other.__axes)

    @property
    def xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__xdata

    @property
    def fill_color(self) -> typing.Optional[Color.Color]:
        return self.__fill_color

    @property
    def stroke_color(self) -> typing.Optional[Color.Color]:
        return self.__stroke_color

    @property
    def stroke_width(self) -> float:
        return self.__stroke_width

    @property
    def axes(self) -> typing.Optional[LineGraphAxes]:
        return self.__axes


MAX_LAYER_COUNT = 16


class LinePlotDisplayInfo(DisplayInfo.DisplayInfo):
    """Represents the information needed to display a line plot, including the data, calibrations, axes and legend information.

    This object is effectively immutable, i.e. outside of caching.
    """

    def __init__(self, display_info: DisplayInfo.DisplayInfo) -> None:
        super().__init__(display_info.display_calibration_info, display_info.display_properties, display_info.display_data_info_list, display_info.display_layers, display_info.graphics, display_info.graphic_selection)

        # cached values
        display_properties = self.display_properties
        self.__y_min: float | None = display_properties.get("y_min", None)
        self.__y_max: float | None = display_properties.get("y_max", None)
        self.__y_axis_scale_id: str | None = display_properties.get("y_style", "linear")  # 'y_style' for backward compatibility
        self.__left_channel: int | None = display_properties.get("left_channel", None)
        self.__right_channel: int | None = display_properties.get("right_channel", None)
        self.__legend_position: str | None = display_properties.get("legend_position", None)
        self.__xdata_list: typing.Optional[typing.List[typing.Optional[DataAndMetadata.DataAndMetadata]]] = None
        self.__axes: typing.Optional[LineGraphAxes] = None
        self.__line_graph_layers: typing.Optional[typing.List[LineGraphLayer]] = None
        self.__legend_entries: typing.Optional[typing.List[LegendEntry]] = None
        self.__regions: typing.Sequence[RegionInfo] | None = None

        # for testing
        self._has_valid_drawn_graph_data = False

    @property
    def regions(self) -> typing.Sequence[RegionInfo]:
        display_calibration_info = self.display_calibration_info
        if self.__regions is None and display_calibration_info:
            dimensional_scales = display_calibration_info.displayed_dimensional_scales
            graphics = self.graphics
            graphic_selection = self.graphic_selection or DisplayItem.GraphicSelection()
            regions = list[RegionInfo]()
            if dimensional_scales and graphics:
                data_scale = dimensional_scales[-1]
                dimensional_calibration = display_calibration_info.displayed_dimensional_calibrations[-1] if len(
                    display_calibration_info.displayed_dimensional_calibrations) > 0 else Calibration.Calibration(
                    scale=data_scale)

                def convert_to_calibrated_value_str(f: float) -> str:
                    return u"{0}".format(
                        dimensional_calibration.convert_to_calibrated_value_str(f, value_range=(0, data_scale),
                                                                                samples=round(data_scale),
                                                                                include_units=False))

                def convert_to_calibrated_size_str(f: float) -> str:
                    return u"{0}".format(
                        dimensional_calibration.convert_to_calibrated_size_str(f, value_range=(0, data_scale),
                                                                               samples=round(data_scale),
                                                                               include_units=False))

                for graphic_index, graphic in enumerate(graphics):
                    if isinstance(graphic, Graphics.IntervalGraphic):
                        graphic_start, graphic_end = graphic.start, graphic.end
                        graphic_start, graphic_end = min(graphic_start, graphic_end), max(graphic_start, graphic_end)
                        left_channel = graphic_start * data_scale
                        right_channel = graphic_end * data_scale
                        left_text = convert_to_calibrated_value_str(left_channel)
                        right_text = convert_to_calibrated_value_str(right_channel)
                        middle_text = convert_to_calibrated_size_str(right_channel - left_channel)
                        region = RegionInfo((graphic_start, graphic_end),
                                            graphic_selection.contains(graphic_index),
                                            graphic_index, left_text, right_text, middle_text,
                                            graphic.label, None, graphic.color)
                        regions.append(region)
                    elif isinstance(graphic, Graphics.ChannelGraphic):
                        graphic_start, graphic_end = graphic.position, graphic.position
                        graphic_start, graphic_end = min(graphic_start, graphic_end), max(graphic_start, graphic_end)
                        left_channel = graphic_start * data_scale
                        right_channel = graphic_end * data_scale
                        left_text = convert_to_calibrated_value_str(left_channel)
                        right_text = convert_to_calibrated_value_str(right_channel)
                        middle_text = convert_to_calibrated_size_str(right_channel - left_channel)
                        region = RegionInfo((graphic_start, graphic_end),
                                            graphic_selection.contains(graphic_index),
                                            graphic_index, left_text, right_text, middle_text,
                                            graphic.label, "tag", graphic.color)
                        regions.append(region)
            self.__regions = regions
        return self.__regions or list()

    @property
    def data_scale(self) -> float:
        display_calibration_info = self.display_calibration_info
        return display_calibration_info.displayed_dimensional_scales[-1] if display_calibration_info and display_calibration_info.displayed_dimensional_scales else 1.0

    @property
    def displayed_dimensional_calibration(self) -> Calibration.Calibration:
        display_calibration_info = self.display_calibration_info
        if display_calibration_info:
            displayed_dimensional_scales: typing.Tuple[float, ...] = display_calibration_info.displayed_dimensional_scales or tuple()
            displayed_dimensional_calibrations = display_calibration_info.displayed_dimensional_calibrations
            displayed_dimensional_calibration = displayed_dimensional_calibrations[-1] if displayed_dimensional_calibrations else Calibration.Calibration(scale=displayed_dimensional_scales[-1])
            assert displayed_dimensional_calibration.is_valid
            return displayed_dimensional_calibration
        return Calibration.Calibration()

    @property
    def displayed_intensity_calibration(self) -> Calibration.Calibration:
        display_calibration_info = self.display_calibration_info
        if display_calibration_info:
            return display_calibration_info.displayed_intensity_calibration
        return Calibration.Calibration()

    @property
    def xdata_list(self) -> typing.List[typing.Optional[DataAndMetadata.DataAndMetadata]]:
        if self.__xdata_list is None:
            display_calibration_info = self.display_calibration_info
            display_data_info_list = self.display_data_info_list
            if display_calibration_info and display_data_info_list:
                self.__xdata_list = list()
                for display_data_info in display_data_info_list:
                    # for each xdata in display values, create a new xdata (with a numpy array) where the
                    # calibration is set from the calibration style in display_calibration_info. each xdata will
                    # have to look at its metadata and create the calibration specific to it. the xdata should
                    # support the given calibration style, but falls back to the default calibration if it doesn't.
                    # handles both intensity and dimensional calibrations.
                    xdata = display_data_info.display_data_and_metadata if display_data_info else None
                    calibration_styles = display_data_info.calibration_styles if display_data_info else tuple()
                    intensity_calibration_styles = display_data_info.intensity_calibration_styles if display_data_info else tuple()
                    calibration_style: typing.Optional[DisplayItem.CalibrationStyle] = None
                    intensity_calibration_style: typing.Optional[DisplayItem.CalibrationStyle] = None
                    for calibration_style_ in calibration_styles:
                        if calibration_style_.calibration_style_id == display_calibration_info.calibration_style.calibration_style_id:
                            calibration_style = calibration_style_
                    for intensity_calibration_style_ in intensity_calibration_styles:
                        if intensity_calibration_style_.calibration_style_id == display_calibration_info.intensity_calibration_style.calibration_style_id:
                            intensity_calibration_style = intensity_calibration_style_
                    if xdata and calibration_style:
                        dimensional_calibrations = calibration_style.get_dimensional_calibrations(xdata.data_shape,
                                                                                                  xdata.dimensional_calibrations,
                                                                                                  xdata.metadata)
                    else:
                        dimensional_calibrations = None
                    if xdata and intensity_calibration_style:
                        intensity_calibration = intensity_calibration_style.get_intensity_calibration(
                            xdata.intensity_calibration)
                    else:
                        intensity_calibration = None
                    if xdata:
                        # xdata.data may not be a numpy array, so convert it to one.
                        xdata = DataAndMetadata.new_data_and_metadata(numpy.asarray(xdata.data),
                                                                      intensity_calibration,
                                                                      dimensional_calibrations, xdata.metadata,
                                                                      xdata.timestamp, xdata.data_descriptor,
                                                                      xdata.timezone, xdata.timezone_offset)
                        self.__xdata_list.append(xdata)
                    else:
                        self.__xdata_list.append(None)
        return self.__xdata_list or list()

    @property
    def axes(self) -> LineGraphAxes:
        if self.__axes is None:
            displayed_dimensional_calibration = self.displayed_dimensional_calibration
            displayed_intensity_calibration = self.displayed_intensity_calibration
            y_min = self.__y_min
            y_max = self.__y_max
            y_axis_scale_id = self.__y_axis_scale_id
            left_channel_opt = self.__left_channel
            right_channel_opt = self.__right_channel
            data_scale = self.data_scale
            xdata_list = self.xdata_list
            # update the line graph data
            left_channel = left_channel_opt if left_channel_opt is not None else 0
            right_channel = right_channel_opt if right_channel_opt is not None else data_scale
            left_channel = typing.cast(int, min(left_channel, right_channel))
            right_channel = typing.cast(int, max(left_channel, right_channel))

            if y_min is not None:
                y_min_calibrated = displayed_intensity_calibration.convert_to_calibrated_value(y_min)
            else:
                y_min_calibrated = None
            if y_max is not None:
                y_max_calibration = displayed_intensity_calibration.convert_to_calibrated_value(y_max)
            else:
                y_max_calibration = None
            scaled_data_min, scaled_data_max, y_ticker = calculate_y_axis(xdata_list,
                                                                          y_min_calibrated,
                                                                          y_max_calibration,
                                                                          y_axis_scale_id)
            self.__axes = LineGraphAxes(data_scale,
                                        scaled_data_min,
                                        scaled_data_max,
                                        left_channel,
                                        right_channel,
                                        displayed_dimensional_calibration,
                                        displayed_intensity_calibration,
                                        y_axis_scale_id,
                                        y_ticker)
        return self.__axes

    @property
    def line_graph_layers(self) -> typing.List[LineGraphLayer]:
        if self.__line_graph_layers is None:
            line_graph_layers: typing.List[LineGraphLayer] = list()

            xdata_list = self.xdata_list

            axes = self.axes

            for index, display_layer in enumerate(self.display_layers[0:MAX_LAYER_COUNT]):
                fill_color_str = display_layer.fill_color
                stroke_color_str = display_layer.stroke_color
                stroke_width = display_layer.stroke_width
                data_index = display_layer.data_index or 0
                data_row = display_layer.data_row or 0
                if 0 <= data_index < len(xdata_list):
                    fill_color = Color.Color(fill_color_str) if fill_color_str else None
                    stroke_color = Color.Color(stroke_color_str) if stroke_color_str else None
                    xdata = xdata_list[data_index]
                    if xdata:
                        data_row = max(0, min(xdata.dimensional_shape[0] - 1, data_row))
                        if xdata.is_data_2d:
                            scalar_data = xdata.data[data_row:data_row + 1, :].reshape((xdata.dimensional_shape[-1],))
                            intensity_calibration = xdata.intensity_calibration
                            displayed_dimensional_calibration = xdata.dimensional_calibrations[-1]
                            xdata = DataAndMetadata.new_data_and_metadata(scalar_data, intensity_calibration, [displayed_dimensional_calibration])
                    line_graph_layers.append(LineGraphLayer(xdata, axes, fill_color, stroke_color, stroke_width))
                    self._has_valid_drawn_graph_data = xdata is not None
            self.__line_graph_layers = line_graph_layers
        return self.__line_graph_layers

    @property
    def legend_position(self) -> typing.Optional[str]:
        return self.__legend_position

    @property
    def legend_entries(self) -> typing.List[LegendEntry]:
        if self.__legend_entries is None:
            legend_entries = list()
            for index, display_layer in enumerate(self.display_layers[0:MAX_LAYER_COUNT]):
                data_index = display_layer.data_index
                data_row = display_layer.data_row
                label = display_layer.label
                if not label:
                    if data_index is not None and data_row is not None:
                        label = "Data {}:{}".format(data_index, data_row)
                    elif data_index is not None:
                        label = "Data {}".format(data_index)
                    else:
                        label = "Unknown"
                fill_color = display_layer.fill_color
                stroke_color = display_layer.stroke_color
                legend_entries.append(LegendEntry(label, fill_color, stroke_color))
            self.__legend_entries = legend_entries
        return self.__legend_entries
