from __future__ import annotations

# standard libraries
import asyncio
import dataclasses
import functools
import gettext
import operator
import threading
import time
import typing
import weakref

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import Core
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift import DisplayPanel
from nion.swift import Panel
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import Widgets
from nion.utils import Binding
from nion.utils import Event
from nion.utils import Model
from nion.utils import Observable
from nion.utils import Stream

from nion.utils.ReferenceCounting import weak_partial

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.swift.model import Persistence
    from nion.ui import UserInterface

_RGBA8ImageDataType = Image._RGBA8ImageDataType

_NDArray = numpy.typing.NDArray[typing.Any]

_StatisticsTable = typing.Dict[str, str]

_ = gettext.gettext

T = typing.TypeVar('T')
IT = typing.TypeVar('IT')
OT = typing.TypeVar('OT')


class AdornmentsCanvasItem(CanvasItem.AbstractCanvasItem):
    """A canvas item to draw the adornments on top of the histogram.

    The adornments are the black and white lines shown during mouse
     adjustment of the display limits.

    Callers are expected to set the display_limits property and
     then call update.
    """

    def __init__(self) -> None:
        super().__init__()
        self.display_limits: typing.Tuple[float, float] = (0.0, 1.0)

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        """Repaint the canvas item. This will occur on a thread."""

        # canvas size
        canvas_size = self.canvas_size
        if canvas_size:
            left = self.display_limits[0]
            right = self.display_limits[1]

            # draw left display limit
            if left > 0.0:
                with drawing_context.saver():
                    drawing_context.begin_path()
                    drawing_context.move_to(left * canvas_size.width, 1)
                    drawing_context.line_to(left * canvas_size.width, canvas_size.height - 1)
                    drawing_context.line_width = 2
                    drawing_context.stroke_style = "#000"
                    drawing_context.stroke()

            # draw right display limit
            if right < 1.0:
                with drawing_context.saver():
                    drawing_context.begin_path()
                    drawing_context.move_to(right * canvas_size.width, 1)
                    drawing_context.line_to(right * canvas_size.width, canvas_size.height - 1)
                    drawing_context.line_width = 2
                    drawing_context.stroke_style = "#FFF"
                    drawing_context.stroke()

            # draw border
            with drawing_context.saver():
                drawing_context.begin_path()
                drawing_context.move_to(0, canvas_size.height)
                drawing_context.line_to(canvas_size.width, canvas_size.height)
                drawing_context.line_width = 1
                drawing_context.stroke_style = "#444"
                drawing_context.stroke()


class SimpleLineGraphCanvasItem(CanvasItem.AbstractCanvasItem):
    """A canvas item to draw a simple line graph.

    The caller can specify a background color by setting the background_color
     property in the format of a CSS color.

    The caller must update the data by setting the data property. The data must
     be a numpy array with a range from 0,1. The data will be re-binned to the
     width of the canvas item and plotted.
    """

    def __init__(self) -> None:
        super().__init__()
        self.__data: typing.Optional[_NDArray] = None
        self.__background_color: typing.Optional[str] = None
        self.__retained_rebin_1d: typing.Dict[str, typing.Any] = dict()

    @property
    def data(self) -> typing.Optional[_NDArray]:
        """Return the data."""
        return self.__data

    @data.setter
    def data(self, data: typing.Optional[_NDArray]) -> None:
        """Set the data and mark the canvas item for updating.

        Data should be a numpy array with a range from 0,1.
        """
        self.__data = data
        self.update()

    @property
    def background_color(self) -> typing.Optional[str]:
        """Return the background color."""
        return self.__background_color

    @background_color.setter
    def background_color(self, background_color: typing.Optional[str]) -> None:
        """Set the background color. Use CSS color format."""
        self.__background_color = background_color
        self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        """Repaint the canvas item. This will occur on a thread."""
        canvas_size = self.canvas_size
        if canvas_size:
            # draw background
            if self.background_color:
                with drawing_context.saver():
                    drawing_context.begin_path()
                    drawing_context.move_to(0, 0)
                    drawing_context.line_to(canvas_size.width, 0)
                    drawing_context.line_to(canvas_size.width, canvas_size.height)
                    drawing_context.line_to(0, canvas_size.height)
                    drawing_context.close_path()
                    drawing_context.fill_style = self.background_color
                    drawing_context.fill()

            # draw the data, if any
            if (self.data is not None and len(self.data) > 0):

                # draw the histogram itself
                with drawing_context.saver():
                    drawing_context.begin_path()
                    binned_data = Image.rebin_1d(self.data, int(canvas_size.width), self.__retained_rebin_1d) if int(canvas_size.width) != self.data.shape[0] else self.data
                    for i in range(canvas_size.width):
                        drawing_context.move_to(i, canvas_size.height)
                        drawing_context.line_to(i, canvas_size.height * (1 - binned_data[i]))
                    drawing_context.line_width = 1
                    drawing_context.stroke_style = "#444"
                    drawing_context.stroke()


class ColorMapCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self) -> None:
        super().__init__()
        self.update_sizing(self.sizing.with_fixed_height(4))
        self.__color_map_data: typing.Optional[_RGBA8ImageDataType] = None

    @property
    def color_map_data(self) -> typing.Optional[_RGBA8ImageDataType]:
        """Return the data."""
        return self.__color_map_data

    @color_map_data.setter
    def color_map_data(self, data: typing.Optional[_RGBA8ImageDataType]) -> None:
        """Set the data and mark the canvas item for updating.

        Data should be an ndarray of shape (256, 3) with type uint8
        """
        self.__color_map_data = data
        self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        """Repaint the canvas item. This will occur on a thread."""
        canvas_size = self.canvas_size
        if canvas_size:
            with drawing_context.saver():
                if self.__color_map_data is not None:
                    rgba_image: numpy.typing.NDArray[numpy.uint32] = numpy.empty((4,) + self.__color_map_data.shape[:-1], dtype=numpy.uint32)
                    Image.get_rgb_view(rgba_image)[:] = self.__color_map_data[numpy.newaxis, :, :]  # scalar data assigned to each component of rgb view
                    Image.get_alpha_view(rgba_image)[:] = 255
                    drawing_context.draw_image(rgba_image, 0, 0, canvas_size.width, canvas_size.height)


class HistogramCanvasItem(CanvasItem.CanvasItemComposition):
    """A canvas item to draw and control a histogram."""

    def __init__(self, cursor_changed_fn: typing.Callable[[typing.Optional[float]], None]) -> None:
        super().__init__()

        # tell the canvas item that we want mouse events.
        self.wants_mouse_events = True

        # create the component canvas items: adornments and the graph.
        self.__adornments_canvas_item = AdornmentsCanvasItem()
        self.__simple_line_graph_canvas_item = SimpleLineGraphCanvasItem()
        self.__histogram_color_map_canvas_item = ColorMapCanvasItem()

        # canvas items get added back to front

        column = CanvasItem.CanvasItemComposition()
        column.layout = CanvasItem.CanvasItemColumnLayout()

        graph_and_adornments = CanvasItem.CanvasItemComposition()
        graph_and_adornments.add_canvas_item(self.__simple_line_graph_canvas_item)
        graph_and_adornments.add_canvas_item(self.__adornments_canvas_item)

        column.add_canvas_item(graph_and_adornments)
        column.add_canvas_item(self.__histogram_color_map_canvas_item)

        self.add_canvas_item(column)

        # used for mouse tracking.
        self.__pressed = False

        self.on_set_display_limits: typing.Optional[typing.Callable[[typing.Optional[typing.Tuple[float, float]]], None]] = None

        self.__cursor_changed = cursor_changed_fn

    def close(self) -> None:
        self._set_histogram_data(None)
        super().close()

    @property
    def background_color(self) -> typing.Optional[str]:
        """Return the background color."""
        return self.__simple_line_graph_canvas_item.background_color

    @background_color.setter
    def background_color(self, background_color: typing.Optional[str]) -> None:
        """Set the background color, in the CSS color format."""
        self.__simple_line_graph_canvas_item.background_color = background_color

    def _set_histogram_data(self, histogram_data: typing.Optional[_NDArray]) -> None:
        # if the user is currently dragging the display limits, we don't want to update
        # from changing data at the same time. but we _do_ want to draw the updated data.
        if not self.__pressed:
            self.__adornments_canvas_item.display_limits = (0, 1)

        self.histogram_data = histogram_data

        # make sure the adornments get updated
        self.__adornments_canvas_item.update()

    @property
    def histogram_data(self) -> typing.Optional[_NDArray]:
        return self.__simple_line_graph_canvas_item.data

    @histogram_data.setter
    def histogram_data(self, histogram_data: typing.Optional[_NDArray]) -> None:
        self.__simple_line_graph_canvas_item.data = histogram_data

    @property
    def color_map_data(self) -> typing.Optional[_RGBA8ImageDataType]:
        return self.__histogram_color_map_canvas_item.color_map_data

    @color_map_data.setter
    def color_map_data(self, color_map_data: typing.Optional[_RGBA8ImageDataType]) -> None:
        self.__histogram_color_map_canvas_item.color_map_data = color_map_data

    def __set_display_limits(self, display_limits: typing.Tuple[float, float]) -> None:
        self.__adornments_canvas_item.display_limits = display_limits
        self.__adornments_canvas_item.update()

    def mouse_double_clicked(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_double_clicked(x, y, modifiers):
            return True
        self.__set_display_limits((0, 1))
        if callable(self.on_set_display_limits):
            self.on_set_display_limits(None)
        return True

    def mouse_pressed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_pressed(x, y, modifiers):
            return True
        canvas_size = self.canvas_size
        if canvas_size:
            self.__pressed = True
            self.start = float(x) / canvas_size.width
            self.__set_display_limits((self.start, self.start))
            return True
        return False

    def mouse_released(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_released(x, y, modifiers):
            return True
        self.__pressed = False
        display_limit_range = self.__adornments_canvas_item.display_limits[1] - self.__adornments_canvas_item.display_limits[0]
        if 0 < display_limit_range < 1:
            if callable(self.on_set_display_limits):
                self.on_set_display_limits(self.__adornments_canvas_item.display_limits)
        self.__set_display_limits((0, 1))
        return True

    def mouse_position_changed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        canvas_size = self.canvas_size
        if canvas_size:
            if callable(self.__cursor_changed):
                self.__cursor_changed(x / canvas_size.width)
            if super().mouse_position_changed(x, y, modifiers):
                return True
            if self.__pressed:
                current = float(x) / canvas_size.width
                self.__set_display_limits((min(self.start, current), max(self.start, current)))
            return True
        return False

    def mouse_exited(self) -> bool:
        if callable(self.__cursor_changed):
            self.__cursor_changed(None)
        return True


@dataclasses.dataclass
class HistogramWidgetData:
    data: typing.Optional[_NDArray] = None
    display_range: typing.Optional[typing.Tuple[float, float]] = None

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, self.__class__):
            return numpy.array_equal(self.data, other.data) and self.display_range == other.display_range  # type: ignore
        return False


class HistogramWidget(Widgets.CompositeWidgetBase):

    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item_stream: Stream.AbstractStream[DisplayItem.DisplayItem],
                 histogram_widget_data_model: Model.PropertyModel[HistogramWidgetData],
                 color_map_data_model: Model.PropertyModel[_RGBA8ImageDataType],
                 cursor_changed_fn: typing.Callable[[typing.Optional[float], typing.Optional[typing.Tuple[float, float]]], None]) -> None:
        content_widget = document_controller.ui.create_column_widget(properties={"min-height": 84, "max-height": 84})
        super().__init__(content_widget)

        ui = document_controller.ui

        self.__display_item_stream = display_item_stream.add_ref()

        self.__histogram_data_model = histogram_widget_data_model
        self.__color_map_data_model = color_map_data_model

        self.__display_range: typing.Optional[typing.Tuple[float, float]] = None

        def histogram_data_changed(key: str) -> None:
            if key == "value":
                histogram_widget_data = self.__histogram_data_model.value
                if histogram_widget_data:
                    self.__histogram_canvas_item._set_histogram_data(histogram_widget_data.data)
                    self.__display_range = histogram_widget_data.display_range

        self.__histogram_data_property_changed_event_listener = self.__histogram_data_model.property_changed_event.listen(histogram_data_changed)

        def set_display_limits(display_limits: typing.Optional[typing.Tuple[float, float]]) -> None:
            # display_limits in this context are in the range of 0,1
            # we ask for the display_range from the display to get actual
            # data values (never None), and create new display limits
            # based on those data values combined with display_limits.
            # then we set the display_limits on the display, which have
            # the same units as the data values.
            display_item = self.__display_item_stream.value
            display_data_channel = display_item.display_data_channel if display_item else None
            if display_data_channel:
                new_display_limits = None
                if display_limits is not None and self.__display_range is not None:
                    data_min, data_max = self.__display_range
                    lower_display_limit = data_min + display_limits[0] * (data_max - data_min)
                    upper_display_limit = data_min + display_limits[1] * (data_max - data_min)
                    new_display_limits = (lower_display_limit, upper_display_limit)

                command = DisplayPanel.ChangeDisplayDataChannelCommand(document_controller.document_model, display_data_channel, display_limits=new_display_limits, title=_("Change Display Limits"))
                command.perform()
                document_controller.push_undo_command(command)

        def cursor_changed(canvas_x: typing.Optional[float]) -> None:
            if callable(cursor_changed_fn):
                cursor_changed_fn(canvas_x, self.__display_range)

        # create a canvas widget for this panel and put a histogram canvas item in it.
        self.__histogram_canvas_item = HistogramCanvasItem(cursor_changed)
        self.__histogram_canvas_item.on_set_display_limits = set_display_limits

        histogram_widget = ui.create_canvas_widget()
        histogram_widget.canvas_item.add_canvas_item(self.__histogram_canvas_item)

        def color_map_data_changed(key: str) -> None:
            if key == "value":
                self.__histogram_canvas_item.color_map_data = self.__color_map_data_model.value

        self.__color_map_data_stream_listener = self.__color_map_data_model.property_changed_event.listen(color_map_data_changed)

        histogram_data_changed("value")

        color_map_data_changed("value")

        content_widget.add(histogram_widget)

    def close(self) -> None:
        self.__color_map_data_stream_listener.close()
        self.__color_map_data_stream_listener = typing.cast(typing.Any, None)
        self.__display_item_stream.remove_ref()
        self.__display_item_stream = typing.cast(typing.Any, None)
        self.__histogram_canvas_item = typing.cast(typing.Any, None)
        self.__histogram_data_property_changed_event_listener.close()
        self.__histogram_data_property_changed_event_listener = typing.cast(typing.Any, None)
        self.__histogram_data_model = typing.cast(typing.Any, None)
        self.__color_map_data_model = typing.cast(typing.Any, None)
        super().close()

    @property
    def _histogram_canvas_item(self) -> HistogramCanvasItem:
        return self.__histogram_canvas_item

    @property
    def _histogram_data_func_value_model(self) -> Model.PropertyModel[HistogramWidgetData]:
        # for testing
        return self.__histogram_data_model


class StatisticsWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui: UserInterface.UserInterface, statistics_model: Model.PropertyModel[typing.Dict[str, str]]) -> None:
        content_widget = ui.create_column_widget(properties={"min-height": 18 * 3, "max-height": 18 * 3})
        super().__init__(content_widget)

        # create property models for the UI
        self._stats1_property = Model.PropertyModel[str](str())
        self._stats2_property = Model.PropertyModel[str](str())

        self.__statistics_model = statistics_model

        def statistics_changed(key: str) -> None:
            if key == "value":
                statistics_data = self.__statistics_model.value or dict()
                statistic_strings = list()
                for key in sorted(statistics_data.keys()):
                    value = statistics_data[key]
                    if value is not None:
                        statistic_str = "{0} {1}".format(key, value)
                    else:
                        statistic_str = "{0} {1}".format(key, _("N/A"))
                    statistic_strings.append(statistic_str)
                self._stats1_property.value = "\n".join(statistic_strings[:(len(statistic_strings) + 1) // 2])
                self._stats2_property.value = "\n".join(statistic_strings[(len(statistic_strings) + 1) // 2:])

        self.__statistics_property_changed_event_listener = self.__statistics_model.property_changed_event.listen(statistics_changed)

        statistics_changed("value")

        stats_column1 = ui.create_column_widget(properties={"min-width": 140, "max-width": 140})
        stats_column2 = ui.create_column_widget(properties={"min-width": 140, "max-width": 140})
        stats_column1_label = ui.create_label_widget()
        stats_column2_label = ui.create_label_widget()
        stats_column1.add(stats_column1_label)
        stats_column2.add(stats_column2_label)
        stats_section = ui.create_row_widget()
        stats_section.add_spacing(13)
        stats_section.add(stats_column1)
        stats_section.add_stretch()
        stats_section.add(stats_column2)
        stats_section.add_spacing(13)

        stats_column1_label.bind_text(Binding.PropertyBinding(self._stats1_property, "value"))
        stats_column2_label.bind_text(Binding.PropertyBinding(self._stats2_property, "value"))

        content_widget.add(stats_section)

    def close(self) -> None:
        self.__statistics_property_changed_event_listener.close()
        self.__statistics_property_changed_event_listener = typing.cast(typing.Any, None)
        self.__statistics_model = typing.cast(typing.Any, None)
        super().close()


# Python 3.9+: weakref typing
def calculate_region_data(display_data_and_metadata_ref: typing.Any, region_ref: typing.Any) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
    display_data_and_metadata = typing.cast(typing.Optional[DataAndMetadata.DataAndMetadata], display_data_and_metadata_ref() if display_data_and_metadata_ref else None)
    region = typing.cast(typing.Optional[Graphics.Graphic], region_ref() if region_ref else None)
    if region and display_data_and_metadata:
        if display_data_and_metadata.is_data_1d and isinstance(region, Graphics.IntervalGraphic):
            interval = region.interval
            if 0 <= interval[0] < 1 and 0 < interval[1] <= 1:
                start, end = int(interval[0] * display_data_and_metadata.data_shape[0]), int(interval[1] * display_data_and_metadata.data_shape[0])
                if end - start >= 1:
                    cropped_data_and_metadata = Core.function_crop_interval(display_data_and_metadata, interval)
                    if cropped_data_and_metadata:
                        return cropped_data_and_metadata
        elif display_data_and_metadata.is_data_2d and isinstance(region, Graphics.RectangleTypeGraphic):
            cropped_data_and_metadata = Core.function_crop(display_data_and_metadata, region.bounds.as_tuple())
            if cropped_data_and_metadata:
                return cropped_data_and_metadata
    return display_data_and_metadata


def calculate_histogram_widget_data(display_data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata], display_range: typing.Optional[typing.Tuple[float, float]]) -> HistogramWidgetData:
    bins = 320
    subsample = 0  # hard coded subsample size
    subsample_fraction = None  # fraction of total pixels
    subsample_min = 1024  # minimum subsample size
    display_data = display_data_and_metadata.data if display_data_and_metadata else None
    display_data_and_metadata = None  # release ref for gc. needed for tests, because this may occur on a thread.
    if display_data is not None:
        total_pixels = numpy.product(display_data.shape, dtype=numpy.uint64)  # type: ignore
        if not subsample and subsample_fraction:
            subsample = min(max(total_pixels * subsample_fraction, subsample_min), total_pixels)
        if subsample:
            data_sample = numpy.random.choice(display_data.reshape(numpy.product(display_data.shape, dtype=numpy.uint64)), subsample)  # type: ignore
        else:
            data_sample = numpy.copy(display_data)  # type: ignore
        if display_range is None or data_sample is None:
            return HistogramWidgetData()
        # numpy is slow because it throws out data less/greater than the min/max values
        # the alternate algorithm here takes a different, faster approach and allows the binning
        # to occur; but throws out the data in the first and last bin. this is not as accurate
        # but improves the speed (compared to numpy) by a factor of 10x.
        range_ = (display_range[1] - display_range[0])
        if range_ > 0.0:
            # int clipping seems faster
            histogram_data = numpy.bincount(numpy.clip(((bins + 2) * ((data_sample.ravel() - display_range[0]) / range_)).astype(int), 0, bins + 2), minlength=bins + 2)[1:bins + 1]
            # histogram_data = numpy.bincount(((bins + 2) * numpy.clip((data_sample - display_range[0]) / (display_range[1] - display_range[0]), 0.0, 1.0)).astype(int).ravel())[1:bins+1]
        else:
            histogram_data = numpy.zeros((bins,), dtype=int)
        # why can't numpy make this optimization?
        # histogram_data = factor * numpy.histogram(data_sample, range=display_range, bins=bins)[0]  # type: ignore
        histogram_max = numpy.max(histogram_data)  # type: ignore  # assumes that histogram_data is int
        if histogram_max > 0:
            histogram_data = histogram_data / float(histogram_max)  # type: ignore
        return HistogramWidgetData(histogram_data, display_range)
    return HistogramWidgetData()


def calculate_statistics(display_data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata], display_data_range: typing.Optional[typing.Tuple[float, float]], region: typing.Optional[Graphics.Graphic], displayed_intensity_calibration: typing.Optional[Calibration.Calibration]) -> _StatisticsTable:
    data = display_data_and_metadata.data if display_data_and_metadata else None
    display_data_and_metadata = None  # release ref for gc. needed for tests, because this may occur on a thread.
    data_range = display_data_range
    if data is not None and data.size > 0 and displayed_intensity_calibration:
        mean = numpy.mean(data).item()
        std = numpy.std(data).item()
        rms = numpy.sqrt(numpy.mean(numpy.square(numpy.absolute(data)))).item()
        dimensional_shape = Image.dimensional_shape_from_shape_and_dtype(data.shape, data.dtype) or (1, 1)
        sum_data = mean * functools.reduce(operator.mul, dimensional_shape)
        if region is None:
            data_min, data_max = data_range if data_range is not None else (None, None)
        else:
            data_min, data_max = numpy.amin(data), numpy.amax(data)
        mean_str = displayed_intensity_calibration.convert_to_calibrated_value_str(mean)
        std_str = displayed_intensity_calibration.convert_to_calibrated_value_str(std)
        data_min_str = displayed_intensity_calibration.convert_to_calibrated_value_str(data_min) if data_min is not None else str()
        data_max_str = displayed_intensity_calibration.convert_to_calibrated_value_str(data_max) if data_max is not None else str()
        rms_str = displayed_intensity_calibration.convert_to_calibrated_value_str(rms)
        sum_data_str = displayed_intensity_calibration.convert_to_calibrated_value_str(sum_data)

        return { "mean": mean_str, "std": std_str, "min": data_min_str, "max": data_max_str, "rms": rms_str, "sum": sum_data_str }
    return dict()


class PropertySetter(typing.Generic[T]):
    def __init__(self, stream: Stream.AbstractStream[T], target: typing.Any, property: str) -> None:
        self.__stream = stream

        # define a stub and use weak_partial to avoid holding references to self.
        def value_changed(value: typing.Optional[T]) -> None:
            setattr(target, property, value)

        self.__stream_listener = self.__stream.value_stream.listen(value_changed)


class HistogramProcessor(Observable.Observable):
    """Computes a histogram and statistics."""

    def __init__(self, event_loop: typing.Optional[asyncio.AbstractEventLoop] = None) -> None:
        super().__init__()
        event_loop = event_loop or asyncio.get_running_loop()
        assert event_loop
        self.__lock = threading.RLock()
        self.__event = asyncio.Event()
        # these fields are used for inputs.
        self.__display_data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.__region: typing.Optional[Graphics.Graphic] = None
        self.__display_range: typing.Optional[typing.Tuple[float, float]] = None
        self.__display_data_range: typing.Optional[typing.Tuple[float, float]] = None
        self.__displayed_intensity_calibration: typing.Optional[Calibration.Calibration] = None
        # these fields are used for computation.
        self.__histogram_widget_data_dirty = False
        self.__statistics_dirty = False
        self.__region_data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        # these fields are used for outputs.
        self.__histogram_widget_data = HistogramWidgetData()
        self.__statistics: _StatisticsTable = dict()

        # Python 3.9: use ReferenceType[FuncStreamValueModel] for model_ref
        async def loop(processor_ref: typing.Any, event: asyncio.Event) -> None:
            assert event_loop
            while True:
                await event.wait()
                event.clear()

                await asyncio.sleep(0.25)  # gather changes for 250ms

                processor = processor_ref()
                if processor:
                    old_histogram_widget_data = processor.__histogram_widget_data
                    old_statistics = processor.__statistics

                    await event_loop.run_in_executor(None, processor.__evaluate)

                    if old_histogram_widget_data != processor.__histogram_widget_data:
                        processor.notify_property_changed("histogram_widget_data")
                    if old_statistics != processor.__statistics:
                        processor.notify_property_changed("statistics")
                    processor = None  # don't keep this reference while in the next iteration of the loop

        self.__task = event_loop.create_task(loop(weakref.ref(self), self.__event))

        def finalize(task: asyncio.Task[None]) -> None:
            task.cancel()

        weakref.finalize(self, finalize, self.__task)

    # inputs

    @property
    def display_data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__display_data_and_metadata

    @display_data_and_metadata.setter
    def display_data_and_metadata(self, value: typing.Optional[DataAndMetadata.DataAndMetadata]) -> None:
        with self.__lock:
            self.__display_data_and_metadata = value
            self.__region_data_and_metadata = None
            self.__histogram_widget_data_dirty = True
            self.__statistics_dirty = True
        self.__event.set()

    @property
    def region(self) -> typing.Optional[Graphics.Graphic]:
        return self.__region

    @region.setter
    def region(self, value: typing.Optional[Graphics.Graphic]) -> None:
        with self.__lock:
            self.__region = value
            self.__region_data_and_metadata = None
            self.__histogram_widget_data_dirty = True
            self.__statistics_dirty = True
        self.__event.set()

    @property
    def display_range(self) -> typing.Optional[typing.Tuple[float, float]]:
        return self.__display_range

    @display_range.setter
    def display_range(self, value: typing.Optional[typing.Tuple[float, float]]) -> None:
        with self.__lock:
            self.__display_range = value
            self.__histogram_widget_data_dirty = True
        self.__event.set()

    @property
    def display_data_range(self) -> typing.Optional[typing.Tuple[float, float]]:
        return self.__display_data_range

    @display_data_range.setter
    def display_data_range(self, value: typing.Optional[typing.Tuple[float, float]]) -> None:
        with self.__lock:
            self.__display_data_range = value
            self.__statistics_dirty = True
        self.__event.set()

    @property
    def displayed_intensity_calibration(self) -> typing.Optional[Calibration.Calibration]:
        return self.__displayed_intensity_calibration

    @displayed_intensity_calibration.setter
    def displayed_intensity_calibration(self, value: typing.Optional[Calibration.Calibration]) -> None:
        with self.__lock:
            self.__displayed_intensity_calibration = value
            self.__statistics_dirty = True
        self.__event.set()

    # outputs

    @property
    def histogram_widget_data(self) -> HistogramWidgetData:
        return self.__histogram_widget_data

    @histogram_widget_data.setter
    def histogram_widget_data(self, value: HistogramWidgetData) -> None:
        pass  # dummy implementation to be compatible with PropertyChangedPropertyModel

    @property
    def statistics(self) -> _StatisticsTable:
        return self.__statistics

    @statistics.setter
    def statistics(self, value: _StatisticsTable) -> None:
        pass  # dummy implementation to be compatible with PropertyChangedPropertyModel

    # private methods

    def __evaluate(self) -> None:
        try:
            with self.__lock:
                display_data_and_metadata = self.__display_data_and_metadata
                region = self.__region
                display_range = self.__display_range
                display_data_range = self.__display_data_range
                displayed_intensity_calibration = self.__displayed_intensity_calibration
                region_data_and_metadata = self.__region_data_and_metadata
                histogram_widget_data_dirty = self.__histogram_widget_data_dirty
                statistics_dirty = self.__statistics_dirty
                histogram_widget_data = self.__histogram_widget_data
                statistics = self.__statistics
                self.__histogram_widget_data_dirty = False
                self.__statistics_dirty = False
            if not region_data_and_metadata:
                region_data_and_metadata = calculate_region_data(
                    weakref.ref(display_data_and_metadata) if display_data_and_metadata else None,
                    weakref.ref(region) if region else None
                )
            if histogram_widget_data_dirty:
                histogram_widget_data = calculate_histogram_widget_data(region_data_and_metadata, display_range)
            if statistics_dirty:
                statistics = calculate_statistics(region_data_and_metadata, display_data_range, region, displayed_intensity_calibration)
            with self.__lock:
                if not self.__histogram_widget_data_dirty and not self.__statistics_dirty:
                    self.__region_data_and_metadata = region_data_and_metadata
                self.__histogram_widget_data = histogram_widget_data
                self.__statistics = statistics
        except Exception as e:
            import traceback
            traceback.print_exc()

    # test methods

    def _evaluate_immediate(self) -> None:
        self.__evaluate()
        self.notify_property_changed("histogram_widget_data")
        self.notify_property_changed("statistics")


class HistogramPanel(Panel.Panel):
    """ A panel to present a histogram of the selected data item. """

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str,
                 properties: Persistence.PersistentDictType, debounce: bool = True, sample: bool = True) -> None:
        super().__init__(document_controller, panel_id, _("Histogram"))

        def compare_data(a: typing.Any, b: typing.Any) -> bool:
            return numpy.array_equal(a.data if a else None, b.data if b else None)  # type: ignore

        display_item_stream = TargetDisplayItemStream(document_controller)
        display_data_channel_stream = StreamPropertyStream[DisplayItem.DisplayDataChannel](typing.cast(Stream.AbstractStream[Observable.Observable], display_item_stream), "display_data_channel")
        display_data_and_metadata_stream = DisplayDataChannelTransientsStream[DataAndMetadata.DataAndMetadata](display_data_channel_stream, "display_data_and_metadata", cmp=compare_data)
        region_stream = TargetRegionStream(display_item_stream)
        display_range_stream = DisplayDataChannelTransientsStream[typing.Tuple[float, float]](display_data_channel_stream, "display_range")
        display_data_range_stream = DisplayDataChannelTransientsStream[typing.Tuple[float, float]](display_data_channel_stream, "data_range")
        displayed_intensity_calibration_stream = StreamPropertyStream[Calibration.Calibration](typing.cast(Stream.AbstractStream[Observable.Observable], display_item_stream), "displayed_intensity_calibration")

        self._histogram_processor = HistogramProcessor(document_controller.event_loop)

        self.__setters = [
            PropertySetter(display_data_and_metadata_stream, self._histogram_processor, "display_data_and_metadata"),
            PropertySetter(region_stream, self._histogram_processor, "region"),
            PropertySetter(display_range_stream, self._histogram_processor, "display_range"),
            PropertySetter(display_data_range_stream, self._histogram_processor, "display_data_range"),
            PropertySetter(displayed_intensity_calibration_stream, self._histogram_processor, "displayed_intensity_calibration"),
        ]

        self.__histogram_widget_data_model = Model.PropertyChangedPropertyModel[HistogramWidgetData](self._histogram_processor, "histogram_widget_data")
        self.__statistics_model = Model.PropertyChangedPropertyModel[_StatisticsTable](self._histogram_processor, "statistics")

        color_map_data_stream = StreamPropertyStream[_RGBA8ImageDataType](typing.cast(Stream.AbstractStream[Observable.Observable], display_data_channel_stream), "color_map_data", cmp=typing.cast(typing.Callable[[typing.Optional[T], typing.Optional[T]], bool], numpy.array_equal))

        def cursor_changed_fn(canvas_x: typing.Optional[float], display_range: typing.Optional[typing.Tuple[float, float]]) -> None:
            if not canvas_x:
                document_controller.cursor_changed(None)
            if display_item_stream and display_item_stream.value and canvas_x:
                if display_range is not None:  # can be None with empty data
                    displayed_intensity_calibration = display_item_stream.value.displayed_intensity_calibration
                    adjusted_x = display_range[0] + canvas_x * (display_range[1] - display_range[0])
                    adjusted_x_str = displayed_intensity_calibration.convert_to_calibrated_value_str(adjusted_x)
                    document_controller.cursor_changed([_('Intensity: ') + adjusted_x_str])
                else:
                    document_controller.cursor_changed(None)

        self.__color_map_data_model: Model.PropertyModel[_RGBA8ImageDataType] = Model.StreamValueModel(color_map_data_stream, cmp=numpy.array_equal)

        self._histogram_widget = HistogramWidget(document_controller, display_item_stream, self.__histogram_widget_data_model, self.__color_map_data_model, cursor_changed_fn)
        self._statistics_widget = StatisticsWidget(self.ui, self.__statistics_model)

        # create the main column with the histogram and the statistics section
        column = self.ui.create_column_widget(properties={"height": 80 + 18 * 3 + 12})
        column.add(self._histogram_widget)
        column.add_spacing(6)
        column.add(self._statistics_widget)
        column.add_spacing(6)
        column.add_stretch()

        # this is necessary to make the panel happy
        self.widget = column

    def close(self) -> None:
        self.__histogram_widget_data_model.close()
        self.__histogram_widget_data_model = typing.cast(typing.Any, None)
        self.__color_map_data_model.close()
        self.__color_map_data_model = typing.cast(typing.Any, None)
        self.__statistics_model.close()
        self.__statistics_model = typing.cast(typing.Any, None)
        self._statistics_widget = typing.cast(typing.Any, None)
        self.__histogram_widget_data_model = typing.cast(typing.Any, None)
        self.__color_map_data_model = typing.cast(typing.Any, None)
        self._histogram_processor = typing.cast(typing.Any, None)
        self.__setters = typing.cast(typing.Any, None)
        super().close()


class TargetDisplayItemStream(Stream.AbstractStream[DisplayItem.DisplayItem]):

    def __init__(self, document_controller: DocumentController.DocumentController):
        super().__init__()
        # outgoing messages
        self.value_stream = Event.Event()
        # cached values
        self.__value: typing.Optional[DisplayItem.DisplayItem] = None
        # listen for selected data item changes
        self.__focused_display_item_changed_event_listener = document_controller.focused_display_item_changed_event.listen(self.__focused_display_item_changed)
        # manually send the first data item changed message to set things up.
        self.__focused_display_item_changed(document_controller.selected_display_item)

    def about_to_delete(self) -> None:
        # disconnect data item binding
        self.__value = None
        self.__focused_display_item_changed_event_listener.close()
        self.__focused_display_item_changed_event_listener = typing.cast(typing.Any, None)
        super().about_to_delete()

    @property
    def value(self) -> typing.Optional[DisplayItem.DisplayItem]:
        return self.__value

    def __focused_display_item_changed(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        if display_item != self.__value:
            self.__value = display_item
            self.value_stream.fire(display_item)


class TargetRegionStream(Stream.AbstractStream[Graphics.Graphic]):

    def __init__(self, display_item_stream: TargetDisplayItemStream) -> None:
        super().__init__()
        # outgoing messages
        self.value_stream = Event.Event()
        # references
        self.__display_item_stream = display_item_stream.add_ref()
        # initialize
        self.__display_graphic_selection_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.__value: typing.Optional[Graphics.Graphic] = None
        # listen for display changes
        self.__display_stream_listener = display_item_stream.value_stream.listen(self.__display_item_changed)
        self.__graphic_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.__graphic_about_to_be_removed_event_listener: typing.Optional[Event.EventListener] = None
        self.__display_item_changed(display_item_stream.value)

    def about_to_delete(self) -> None:
        self.__display_stream_listener.close()
        self.__display_stream_listener = typing.cast(typing.Any, None)
        self.__display_item_stream.remove_ref()
        self.__display_item_stream = typing.cast(typing.Any, None)
        if self.__graphic_changed_event_listener:
            self.__graphic_changed_event_listener.close()
            self.__graphic_changed_event_listener = None
        if self.__graphic_about_to_be_removed_event_listener:
            self.__graphic_about_to_be_removed_event_listener.close()
            self.__graphic_about_to_be_removed_event_listener = None
        if self.__display_graphic_selection_changed_event_listener:
            self.__display_graphic_selection_changed_event_listener.close()
            self.__display_graphic_selection_changed_event_listener = None
        self.__value = None
        super().about_to_delete()

    @property
    def value(self) -> typing.Optional[Graphics.Graphic]:
        return self.__value

    def __display_item_changed(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        def display_graphic_selection_changed(graphic_selection: DisplayItem.GraphicSelection) -> None:
            current_index = graphic_selection.current_index
            if current_index is not None:
                assert display_item
                new_value = display_item.graphics[current_index]
                if new_value != self.__value:
                    self.__value = new_value
                    def graphic_changed(property: str) -> None:
                        self.value_stream.fire(self.__value)
                    def graphic_removed() -> None:
                        self.__value = None
                        self.value_stream.fire(None)
                    if self.__graphic_changed_event_listener:
                        self.__graphic_changed_event_listener.close()
                        self.__graphic_changed_event_listener = None
                    if self.__graphic_about_to_be_removed_event_listener:
                        self.__graphic_about_to_be_removed_event_listener.close()
                        self.__graphic_about_to_be_removed_event_listener = None
                    if self.__value:
                        self.__graphic_changed_event_listener = self.__value.property_changed_event.listen(graphic_changed)
                        self.__graphic_about_to_be_removed_event_listener = self.__value.about_to_be_removed_event.listen(graphic_removed)
                    graphic_changed("role")  # pass a dummy property
            elif self.__value is not None:
                self.__value = None
                if self.__graphic_changed_event_listener:
                    self.__graphic_changed_event_listener.close()
                    self.__graphic_changed_event_listener = None
                if self.__graphic_about_to_be_removed_event_listener:
                    self.__graphic_about_to_be_removed_event_listener.close()
                    self.__graphic_about_to_be_removed_event_listener = None
                self.value_stream.fire(None)
        if self.__graphic_changed_event_listener:
            self.__graphic_changed_event_listener.close()
            self.__graphic_changed_event_listener = None
        if self.__graphic_about_to_be_removed_event_listener:
            self.__graphic_about_to_be_removed_event_listener.close()
            self.__graphic_about_to_be_removed_event_listener = None
        if self.__display_graphic_selection_changed_event_listener:
            self.__display_graphic_selection_changed_event_listener.close()
            self.__display_graphic_selection_changed_event_listener = None
        if display_item:
            self.__display_graphic_selection_changed_event_listener = display_item.graphic_selection_changed_event.listen(display_graphic_selection_changed)
            display_graphic_selection_changed(display_item.graphic_selection)
        elif self.__value is not None:
            self.__value = None
            self.value_stream.fire(None)


class ConcatStream(Stream.AbstractStream[T], typing.Generic[T]):
    """Make a new stream for each new value of input stream and concatenate new stream output."""

    def __init__(self, stream: Stream.AbstractStream[Observable.Observable],
                 concat_fn: typing.Callable[[typing.Optional[Observable.Observable]], Stream.AbstractStream[T]]) -> None:
        super().__init__()
        # outgoing messages
        self.value_stream = Event.Event()
        # references
        self.__stream = stream.add_ref()
        # initialize
        self.__concat_fn = concat_fn
        self.__value: typing.Optional[T] = None
        self.__out_stream: typing.Optional[Stream.AbstractStream[T]] = None
        self.__out_stream_listener: typing.Optional[Event.EventListener] = None

        # define a stub and use weak_partial to avoid holding references to self.
        def stream_changed(stream: ConcatStream[T], value: typing.Optional[Observable.Observable]) -> None:
            stream.__stream_changed(value)

        self.__stream_listener = stream.value_stream.listen(weak_partial(stream_changed, self))
        self.__stream_changed(stream.value)

    def about_to_delete(self) -> None:
        if self.__out_stream_listener:
            self.__out_stream_listener.close()
            self.__out_stream_listener = None
        if self.__out_stream:
            self.__out_stream.remove_ref()
            self.__out_stream = typing.cast(typing.Any, None)
        self.__value = None
        self.__stream_listener.close()
        self.__stream_listener = typing.cast(Event.EventListener, None)
        self.__stream.remove_ref()
        self.__stream = typing.cast(typing.Any, None)
        super().about_to_delete()

    @property
    def value(self) -> typing.Optional[T]:
        return self.__value

    def send_value(self, value: typing.Optional[T]) -> None:
        self.__value = value
        self.value_stream.fire(self.value)

    def __stream_changed(self, item: typing.Optional[Observable.Observable]) -> None:
        if self.__out_stream_listener:
            self.__out_stream_listener.close()
            self.__out_stream_listener = None
        if self.__out_stream:
            self.__out_stream.remove_ref()
            self.__out_stream = typing.cast(typing.Any, None)
        if item:
            # define a stub and use weak_partial to avoid holding references to self.
            def out_stream_changed(stream: ConcatStream[T], new_value: typing.Optional[T]) -> None:
                stream.send_value(new_value)

            self.__out_stream = self.__concat_fn(item)
            self.__out_stream.add_ref()
            self.__out_stream_listener = self.__out_stream.value_stream.listen(weak_partial(out_stream_changed, self))
            out_stream_changed(self, self.__out_stream.value)
        else:
            self.__value = None
            self.value_stream.fire(None)


class StreamPropertyStream(ConcatStream[T], typing.Generic[T]):
    def __init__(self, stream: Stream.AbstractStream[Observable.Observable], property_name: str, cmp: typing.Optional[typing.Callable[[typing.Optional[T], typing.Optional[T]], bool]] = None) -> None:
        def fn(x: typing.Optional[Observable.Observable]) -> Stream.AbstractStream[T]:
            assert x
            return Stream.PropertyChangedEventStream[T](x, property_name, cmp)
        super().__init__(stream, fn)


class DisplayDataChannelTransientsStream(Stream.AbstractStream[T], typing.Generic[T]):
    # TODO: add a display_data_changed to Display class and use it here

    def __init__(self, display_data_channel_stream: Stream.AbstractStream[DisplayItem.DisplayDataChannel], property_name: str, cmp: typing.Optional[typing.Callable[[typing.Optional[T], typing.Optional[T]], bool]] = None) -> None:
        super().__init__()
        # outgoing messages
        self.value_stream = Event.Event()
        # initialize
        self.__property_name = property_name
        self.__value: typing.Optional[T] = None
        self.__display_values_changed_listener: typing.Optional[Event.EventListener] = None
        self.__next_calculated_display_values_listener: typing.Optional[Event.EventListener] = None
        self.__cmp: typing.Callable[[typing.Optional[T], typing.Optional[T]], bool] = cmp if cmp else typing.cast(typing.Callable[[typing.Optional[T], typing.Optional[T]], bool], operator.eq)
        # listen for display changes
        self.__display_data_channel_stream = display_data_channel_stream.add_ref()
        self.__display_data_channel_stream_listener = display_data_channel_stream.value_stream.listen(weak_partial(DisplayDataChannelTransientsStream.__display_data_channel_changed, self))
        self.__display_data_channel_changed(display_data_channel_stream.value)

    def about_to_delete(self) -> None:
        if self.__next_calculated_display_values_listener:
            self.__next_calculated_display_values_listener.close()
            self.__next_calculated_display_values_listener = None
        if self.__display_values_changed_listener:
            self.__display_values_changed_listener.close()
            self.__display_values_changed_listener = None
        self.__value = None
        self.__display_data_channel_stream_listener.close()
        self.__display_data_channel_stream_listener = typing.cast(typing.Any, None)
        self.__display_data_channel_stream.remove_ref()
        self.__display_data_channel_stream = typing.cast(typing.Any, None)
        super().about_to_delete()

    @property
    def value(self) -> typing.Optional[T]:
        return self.__value

    def __display_values_changed(self, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        display_values = display_data_channel.get_calculated_display_values(True)
        new_value = getattr(display_values, self.__property_name) if display_values else None
        if not self.__cmp(new_value, self.__value):
            self.__value = new_value
            self.value_stream.fire(self.__value)

    def __display_data_channel_changed(self, display_data_channel: typing.Optional[DisplayItem.DisplayDataChannel]) -> None:
        if self.__next_calculated_display_values_listener:
            self.__next_calculated_display_values_listener.close()
            self.__next_calculated_display_values_listener = None
        if self.__display_values_changed_listener:
            self.__display_values_changed_listener.close()
            self.__display_values_changed_listener = None
        if display_data_channel:
            # there are two listeners - the first when new display properties have triggered new display values.
            # the second whenever actual new display values arrive. this ensures the display gets updated after
            # the user changes it. could use some rethinking.
            self.__next_calculated_display_values_listener = display_data_channel.add_calculated_display_values_listener(weak_partial(DisplayDataChannelTransientsStream.__display_values_changed, self, display_data_channel))
            self.__display_values_changed_listener = display_data_channel.display_values_changed_event.listen(weak_partial(DisplayDataChannelTransientsStream.__display_values_changed, self, display_data_channel))
            self.__display_values_changed(display_data_channel)
        else:
            self.__value = None
            self.value_stream.fire(None)


class StreamValueFuncModel(Model.PropertyModel[OT], typing.Generic[T, OT]):
    """Converts a stream to a property model."""

    def __init__(self, value_stream: Stream.AbstractStream[typing.Any], event_loop: asyncio.AbstractEventLoop, fn: typing.Callable[[T], OT], value: typing.Optional[OT] = None, cmp: typing.Optional[Model.EqualityOperator] = None) -> None:
        super().__init__(value=value, cmp=cmp)
        self.__value_stream = value_stream
        self.__event_loop = event_loop
        self.__pending_task = Stream.StreamTask(None, event_loop)
        self.__event = asyncio.Event()
        self.__evaluating = [False]
        self.__value: T = typing.cast(typing.Any, None)

        # Python 3.9: use ReferenceType[FuncStreamValueModel] for model_ref
        async def update_value(event: asyncio.Event, evaluating: typing.List[bool], model_ref: typing.Any) -> None:
            while True:
                await event.wait()
                evaluating[0] = True
                event.clear()
                value = None

                def eval() -> None:
                    nonlocal value
                    try:
                        value = fn(self.__value)
                    except Exception as e:
                        pass

                await event_loop.run_in_executor(None, eval)
                model = model_ref()
                if model:
                    model.value = value
                    model = None  # immediately release value for gc
                evaluating[0] = event.is_set()

        self.__pending_task.create_task(update_value(self.__event, self.__evaluating, weakref.ref(self)))
        self.__stream_listener = value_stream.value_stream.listen(weak_partial(StreamValueFuncModel.__handle_value, self))
        self.__handle_value(value_stream.value)

        def finalize(pending_task: Stream.StreamTask) -> None:
            pending_task.clear()

        weakref.finalize(self, finalize, self.__pending_task)

    def __handle_value(self, value: typing.Any) -> None:
        self.__value = value
        self.__event.set()
