# standard libraries
import functools
import gettext
import operator
import typing

# third party libraries
import numpy

# local libraries
from nion.data import Core
from nion.data import Image
from nion.swift import Panel
from nion.swift import Widgets
from nion.swift.model import ColorMaps
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.utils import Binding
from nion.utils import Event
from nion.utils import Model
from nion.utils import Stream

_ = gettext.gettext


class AdornmentsCanvasItem(CanvasItem.AbstractCanvasItem):
    """A canvas item to draw the adornments on top of the histogram.

    The adornments are the black and white lines shown during mouse
     adjustment of the display limits.

    Callers are expected to set the display_limits property and
     then call update.
    """

    def __init__(self):
        super().__init__()
        self.display_limits = (0,1)

    def _repaint(self, drawing_context):
        """Repaint the canvas item. This will occur on a thread."""

        # canvas size
        canvas_width = self.canvas_size[1]
        canvas_height = self.canvas_size[0]

        left = self.display_limits[0]
        right = self.display_limits[1]

        # draw left display limit
        if left > 0.0:
            drawing_context.save()
            drawing_context.begin_path()
            drawing_context.move_to(left * canvas_width, 1)
            drawing_context.line_to(left * canvas_width, canvas_height-1)
            drawing_context.line_width = 2
            drawing_context.stroke_style = "#000"
            drawing_context.stroke()
            drawing_context.restore()

        # draw right display limit
        if right < 1.0:
            drawing_context.save()
            drawing_context.begin_path()
            drawing_context.move_to(right * canvas_width, 1)
            drawing_context.line_to(right * canvas_width, canvas_height-1)
            drawing_context.line_width = 2
            drawing_context.stroke_style = "#FFF"
            drawing_context.stroke()
            drawing_context.restore()

        # draw border
        drawing_context.save()
        drawing_context.begin_path()
        drawing_context.move_to(0,canvas_height)
        drawing_context.line_to(canvas_width,canvas_height)
        drawing_context.line_width = 1
        drawing_context.stroke_style = "#444"
        drawing_context.stroke()
        drawing_context.restore()


class SimpleLineGraphCanvasItem(CanvasItem.AbstractCanvasItem):
    """A canvas item to draw a simple line graph.

    The caller can specify a background color by setting the background_color
     property in the format of a CSS color.

    The caller must update the data by setting the data property. The data must
     be a numpy array with a range from 0,1. The data will be re-binned to the
     width of the canvas item and plotted.
    """

    def __init__(self):
        super().__init__()
        self.__data = None
        self.__background_color = None
        self.__retained_rebin_1d = dict()

    @property
    def data(self):
        """Return the data."""
        return self.__data

    @data.setter
    def data(self, data):
        """Set the data and mark the canvas item for updating.

        Data should be a numpy array with a range from 0,1.
        """
        self.__data = data
        self.update()

    @property
    def background_color(self):
        """Return the background color."""
        return self.__background_color

    @background_color.setter
    def background_color(self, background_color):
        """Set the background color. Use CSS color format."""
        self.__background_color = background_color
        self.update()

    def _repaint(self, drawing_context):
        """Repaint the canvas item. This will occur on a thread."""

        # canvas size
        canvas_width = self.canvas_size[1]
        canvas_height = self.canvas_size[0] - 4

        # draw background
        if self.background_color:
            drawing_context.save()
            drawing_context.begin_path()
            drawing_context.move_to(0,0)
            drawing_context.line_to(canvas_width,0)
            drawing_context.line_to(canvas_width,canvas_height)
            drawing_context.line_to(0,canvas_height)
            drawing_context.close_path()
            drawing_context.fill_style = self.background_color
            drawing_context.fill()
            drawing_context.restore()

        # draw the data, if any
        if (self.data is not None and len(self.data) > 0):

            # draw the histogram itself
            drawing_context.save()
            drawing_context.begin_path()
            binned_data = Image.rebin_1d(self.data, int(canvas_width), self.__retained_rebin_1d) if int(canvas_width) != self.data.shape[0] else self.data
            for i in range(canvas_width):
                drawing_context.move_to(i, canvas_height)
                drawing_context.line_to(i, canvas_height * (1 - binned_data[i]))
            drawing_context.line_width = 1
            drawing_context.stroke_style = "#444"
            drawing_context.stroke()
            drawing_context.restore()


class ColorMapCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super().__init__()
        self.__data = None

    @property
    def data(self):
        """Return the data."""
        return self.__data

    @data.setter
    def data(self, data):
        """Set the data and mark the canvas item for updating.

        Data should be a numpy array with a range from 0,1.
        """
        self.__data = data
        self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext):
        """Repaint the canvas item. This will occur on a thread."""

        # canvas size
        canvas_width = self.canvas_size[1]
        canvas_height = self.canvas_size[0]

        drawing_context.save()
        drawing_context.begin_path()
        drawing_context.move_to(0, canvas_height - 4)
        drawing_context.line_to(canvas_width, canvas_height - 4)
        drawing_context.line_to(canvas_width, canvas_height)
        drawing_context.line_to(0, canvas_height)
        drawing_context.close_path()
        drawing_context.fill_style = "#F00"
        color_map_gradient = drawing_context.create_linear_gradient(canvas_width, 4, 0, canvas_height - 4, canvas_width, canvas_height)
        color_map = ColorMaps.color_maps.get(self.__data)
        if color_map is not None:
            index = 0
            for stop in color_map:
                stop_ints = stop.astype(int)
                color_map_gradient.add_color_stop(index * (1 / (len(color_map) - 1)), "#{2:02X}{1:02X}{0:02X}".format(*stop_ints))
                index += 1
        else:
            color_map_gradient.add_color_stop(0.0, '#000')
            color_map_gradient.add_color_stop(1.0, '#FFF')
        drawing_context.fill_style = color_map_gradient
        drawing_context.fill()
        drawing_context.restore()


class HistogramCanvasItem(CanvasItem.CanvasItemComposition):
    """A canvas item to draw and control a histogram."""

    def __init__(self, cursor_changed_fn: typing.Callable[[float], None]):
        super().__init__()

        # tell the canvas item that we want mouse events.
        self.wants_mouse_events = True

        # create the component canvas items: adornments and the graph.
        self.__adornments_canvas_item = AdornmentsCanvasItem()
        self.__simple_line_graph_canvas_item = SimpleLineGraphCanvasItem()
        self.__histogram_color_map_canvas_item = ColorMapCanvasItem()

        # canvas items get added back to front
        self.add_canvas_item(self.__simple_line_graph_canvas_item)
        self.add_canvas_item(self.__adornments_canvas_item)
        self.add_canvas_item(self.__histogram_color_map_canvas_item)

        # used for mouse tracking.
        self.__pressed = False

        self.on_set_display_limits = None

        self.__cursor_changed = cursor_changed_fn

    def close(self):
        self._set_histogram_data(None)
        super().close()

    @property
    def background_color(self):
        """Return the background color."""
        return self.__simple_line_graph_canvas_item.background_color

    @background_color.setter
    def background_color(self, background_color):
        """Set the background color, in the CSS color format."""
        self.__simple_line_graph_canvas_item.background_color = background_color

    def _set_histogram_data(self, histogram_data):
        # if the user is currently dragging the display limits, we don't want to update
        # from changing data at the same time. but we _do_ want to draw the updated data.
        if not self.__pressed:
            self.__adornments_canvas_item.display_limits = (0, 1)

        self.histogram_data = histogram_data

        # make sure the adornments get updated
        self.__adornments_canvas_item.update()

    def _set_color_map_data(self, color_map_id):
        self.color_map = color_map_id

    @property
    def histogram_data(self):
        return self.__simple_line_graph_canvas_item.data

    @histogram_data.setter
    def histogram_data(self, histogram_data):
        self.__simple_line_graph_canvas_item.data = histogram_data

    @property
    def color_map(self):
        return self.__histogram_color_map_canvas_item.data

    @color_map.setter
    def color_map(self, color_map_id):
        self.__histogram_color_map_canvas_item.data = color_map_id

    def __set_display_limits(self, display_limits):
        self.__adornments_canvas_item.display_limits = display_limits
        self.__adornments_canvas_item.update()

    def mouse_double_clicked(self, x, y, modifiers):
        if super().mouse_double_clicked(x, y, modifiers):
            return True
        self.__set_display_limits((0, 1))
        if callable(self.on_set_display_limits):
            self.on_set_display_limits(None)
        return True

    def mouse_pressed(self, x, y, modifiers):
        if super().mouse_pressed(x, y, modifiers):
            return True
        self.__pressed = True
        self.start = float(x)/self.canvas_size[1]
        self.__set_display_limits((self.start, self.start))
        return True

    def mouse_released(self, x, y, modifiers):
        if super().mouse_released(x, y, modifiers):
            return True
        self.__pressed = False
        display_limit_range = self.__adornments_canvas_item.display_limits[1] - self.__adornments_canvas_item.display_limits[0]
        if 0 < display_limit_range < 1:
            if callable(self.on_set_display_limits):
                self.on_set_display_limits(self.__adornments_canvas_item.display_limits)
        return True

    def mouse_position_changed(self, x, y, modifiers):
        if callable(self.__cursor_changed):
            self.__cursor_changed(x / self.canvas_size[1])
        if super().mouse_position_changed(x, y, modifiers):
            return True
        canvas_width = self.canvas_size[1]
        if self.__pressed:
            current = float(x)/canvas_width
            self.__set_display_limits((min(self.start, current), max(self.start, current)))
        return True

    def mouse_exited(self) -> bool:
        if callable(self.__cursor_changed):
            self.__cursor_changed(None)
        return True


class HistogramWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui, display_stream, histogram_data_future_stream, cursor_changed_fn):
        super().__init__(ui.create_column_widget(properties={"min-height": 80, "max-height": 84}))

        self.__histogram_data_future_stream = histogram_data_future_stream
        self.__display_future_stream = display_stream

        def set_display_limits(display_limits):
            display = display_stream.value
            if display:
                if display_limits is not None:
                    data_min, data_max = display.display_range
                    lower_display_limit = data_min + display_limits[0] * (data_max - data_min)
                    upper_display_limit = data_min + display_limits[1] * (data_max - data_min)
                    display.display_limits = (lower_display_limit, upper_display_limit)
                else:
                    display.display_limits = None

        # create a canvas widget for this panel and put a histogram canvas item in it.
        self.__histogram_canvas_item = HistogramCanvasItem(cursor_changed_fn)
        self._histogram_canvas_item.color_map = 'ice'
        self.__histogram_canvas_item.on_set_display_limits = set_display_limits

        histogram_widget = ui.create_canvas_widget()
        histogram_widget.canvas_item.add_canvas_item(self.__histogram_canvas_item)

        def handle_histogram_data_future(histogram_data_future):
            def handle_histogram_data(histogram_data):
                if self.__histogram_canvas_item:  # hack to fix closing issues.
                    self.__histogram_canvas_item._set_histogram_data(histogram_data)
            histogram_data_future.evaluate(handle_histogram_data)

        self.__histogram_data_stream_listener = histogram_data_future_stream.value_stream.listen(handle_histogram_data_future)
        handle_histogram_data_future(self.__histogram_data_future_stream.value)

        def handle_update_color_map(color_map):
            self.__histogram_canvas_item.color_map = color_map

        self.__color_map_stream = DisplayPropertyStream(self.__display_future_stream, "color_map")
        self.__color_map_stream_listener = self.__color_map_stream.value_stream.listen(handle_update_color_map)
        handle_update_color_map(self.__display_future_stream.value)

        self.content_widget.add(histogram_widget)

    def close(self):
        self.__histogram_data_stream_listener.close()
        self.__histogram_data_stream_listener = None
        self.__histogram_data_future_stream = None
        self.__color_map_stream_listener.close()
        self.__color_map_stream_listener = None
        self.__color_map_stream = None
        self.__histogram_canvas_item = None
        super().close()

    def _recompute(self):
        pass

    @property
    def _histogram_canvas_item(self):
        return self.__histogram_canvas_item


class StatisticsWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui, statistics_future_stream):
        super().__init__(ui.create_column_widget(properties={"min-height": 18 * 3, "max-height": 18 * 3}))

        self.__statistics_future_stream = statistics_future_stream

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

        # create property models for the
        self._stats1_property = Model.PropertyModel(str())
        self._stats2_property = Model.PropertyModel(str())

        stats_column1_label.bind_text(Binding.PropertyBinding(self._stats1_property, "value"))
        stats_column2_label.bind_text(Binding.PropertyBinding(self._stats2_property, "value"))

        def handle_statistics_future(statistics_future):
            def handle_statistics(statistics_data):
                statistic_strings = list()
                for key in sorted(statistics_data.keys()):
                    value = statistics_data[key]
                    if value is not None:
                        statistic_str = "{0} {1:n}".format(key, statistics_data[key])
                    else:
                        statistic_str = "{0} {1}".format(key, _("N/A"))
                    statistic_strings.append(statistic_str)
                self._stats1_property.value = "\n".join(statistic_strings[:(len(statistic_strings) + 1) // 2])
                self._stats2_property.value = "\n".join(statistic_strings[(len(statistic_strings) + 1) // 2:])
            statistics_future.evaluate(handle_statistics)

        self.__statistics_stream_listener = statistics_future_stream.value_stream.listen(handle_statistics_future)
        handle_statistics_future(self.__statistics_future_stream.value)

        self.content_widget.add(stats_section)

    def close(self):
        self.__statistics_stream_listener.close()
        self.__statistics_stream_listener = None
        self.__statistics_future_stream = None
        super().close()

    def _recompute(self):
        pass


class HistogramPanel(Panel.Panel):
    """ A panel to present a histogram of the selected data item. """

    def __init__(self, document_controller, panel_id, properties, debounce=True, sample=True):
        super().__init__(document_controller, panel_id, _("Histogram"))

        # create a binding that updates whenever the selected data item changes
        self.__selected_data_item_binding = document_controller.create_selected_data_item_binding()

        def calculate_region_data(data_and_metadata, region):
            if region is not None and data_and_metadata is not None:
                if data_and_metadata.is_data_1d and isinstance(region, Graphics.IntervalGraphic):
                    interval = region.interval
                    if 0 <= interval[0] < 1 and 0 < interval[1] <= 1:
                        start, end = int(interval[0] * data_and_metadata.data_shape[0]), int(interval[1] * data_and_metadata.data_shape[0])
                        if end - start >= 1:
                            cropped_data_and_metadata = Core.function_crop_interval(data_and_metadata, interval)
                            if cropped_data_and_metadata:
                                return cropped_data_and_metadata
                elif data_and_metadata.is_data_2d and isinstance(region, Graphics.RectangleTypeGraphic):
                    cropped_data_and_metadata = Core.function_crop(data_and_metadata, region.bounds)
                    if cropped_data_and_metadata:
                        return cropped_data_and_metadata
            return data_and_metadata

        def calculate_histogram_data(data_and_metadata, display_range):
            bins = 320
            subsample = 0  # hard coded subsample size
            subsample_fraction = None  # fraction of total pixels
            subsample_min = 1024  # minimum subsample size
            data = data_and_metadata.data if data_and_metadata else None
            if data is not None:
                total_pixels = numpy.product(data.shape)
                if not subsample and subsample_fraction:
                    subsample = min(max(total_pixels * subsample_fraction, subsample_min), total_pixels)
                if subsample:
                    factor = total_pixels / subsample
                    data_sample = numpy.random.choice(data.reshape(numpy.product(data.shape)), subsample)
                else:
                    factor = 1.0
                    data_sample = numpy.copy(data)
                if display_range is None or data_sample is None:
                    return None
                histogram_data = factor * numpy.histogram(data_sample, range=display_range, bins=bins)[0]
                histogram_max = numpy.max(histogram_data)  # assumes that histogram_data is int
                if histogram_max > 0:
                    histogram_data = histogram_data / float(histogram_max)
                return histogram_data
            return None

        def calculate_future_histogram_data(data_and_metadata, display_range):
            return Stream.FutureValue(calculate_histogram_data, data_and_metadata, display_range)

        display_stream = TargetDisplayStream(document_controller)
        region_stream = TargetRegionStream(display_stream)
        display_data_and_calibration_stream = DisplayPropertyStream(display_stream, 'display_data_and_calibration')
        display_range_stream = DisplayPropertyStream(display_stream, 'display_range')
        display_data_and_calibration_stream = Stream.CombineLatestStream((display_data_and_calibration_stream, region_stream), calculate_region_data)
        histogram_data_and_metadata_stream = Stream.CombineLatestStream((display_data_and_calibration_stream, display_range_stream), calculate_future_histogram_data)
        if debounce:
            histogram_data_and_metadata_stream = Stream.DebounceStream(histogram_data_and_metadata_stream, 0.05)
        if sample:
            histogram_data_and_metadata_stream = Stream.SampleStream(histogram_data_and_metadata_stream, 0.5)

        def cursor_changed_fn(canvas_x: float) -> None:
            if not canvas_x:
                document_controller.cursor_changed(None)
            if display_stream and display_stream.value and canvas_x:
                display_range = display_stream.value.display_range
                intensity_calibration = display_stream.value.data_and_calibration.intensity_calibration
                data_shape = display_stream.value.data_and_calibration.data_shape

                adjusted_x = display_range[0] + canvas_x * (display_range[1] - display_range[0])
                adjusted_x = intensity_calibration.convert_to_calibrated_value_str(adjusted_x)

                document_controller.cursor_changed([_('Intensity: ') + str(adjusted_x)])

        self._histogram_widget = HistogramWidget(self.ui, display_stream, histogram_data_and_metadata_stream, cursor_changed_fn)

        def calculate_statistics(display_data_and_metadata, display_data_range, region):
            data = display_data_and_metadata.data if display_data_and_metadata else None
            data_range = display_data_range
            if data is not None:
                mean = numpy.mean(data)
                std = numpy.std(data)
                rms = numpy.sqrt(numpy.mean(numpy.square(numpy.absolute(data))))
                sum = mean * functools.reduce(operator.mul, Image.dimensional_shape_from_shape_and_dtype(data.shape, data.dtype))
                if region is None:
                    data_min, data_max = data_range if data_range is not None else (None, None)
                else:
                    data_min, data_max = numpy.amin(data), numpy.amax(data)
                return { "mean": mean, "std": std, "min": data_min, "max": data_max, "rms": rms, "sum": sum }
            return dict()

        def calculate_future_statistics(display_data_and_metadata, display_data_range, region):
            return Stream.FutureValue(calculate_statistics, display_data_and_metadata, display_data_range, region)

        display_data_range_stream = DisplayPropertyStream(display_stream, 'data_range')
        statistics_future_stream = Stream.CombineLatestStream((display_data_and_calibration_stream, display_data_range_stream, region_stream), calculate_future_statistics)
        if debounce:
            statistics_future_stream = Stream.DebounceStream(statistics_future_stream, 0.05)
        if sample:
            statistics_future_stream = Stream.SampleStream(statistics_future_stream, 0.5)
        self._statistics_widget = StatisticsWidget(self.ui, statistics_future_stream)

        # create the main column with the histogram and the statistics section
        column = self.ui.create_column_widget(properties={"height": 80 + 18 * 3 + 12})
        column.add(self._histogram_widget)
        column.add_spacing(6)
        column.add(self._statistics_widget)
        column.add_spacing(6)
        column.add_stretch()

        # this is necessary to make the panel happy
        self.widget = column


class TargetDisplayStream:

    def __init__(self, document_controller):
        # outgoing messages
        self.value_stream = Event.Event()
        # cached values
        self.__value = None
        # listen for selected data item changes
        self.__selected_data_item_changed_event_listener = document_controller.selected_data_item_changed_event.listen(self.__selected_data_item_changed)
        # manually send the first data item changed message to set things up.
        self.__selected_data_item_changed(document_controller.selected_display_specifier.data_item)

    def __del__(self):
        self.close()

    def close(self):
        # disconnect data item binding
        self.__selected_data_item_changed(None)
        self.__selected_data_item_changed_event_listener.close()
        self.__selected_data_item_changed_event_listener = None

    @property
    def value(self):
        return self.__value

    def __selected_data_item_changed(self, data_item):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        if display != self.__value:
            self.value_stream.fire(display)
            self.__value = display


class TargetRegionStream:

    def __init__(self, display_stream):
        # outgoing messages
        self.value_stream = Event.Event()
        # references
        self.__display_stream = display_stream
        # initialize
        self.__display_graphic_selection_changed_event_listener = None
        self.__value = None
        # listen for display changes
        self.__display_stream_listener = display_stream.value_stream.listen(self.__display_changed)
        self.__display_changed(display_stream.value)

    def __del__(self):
        self.close()

    def close(self):
        self.__display_changed(None)
        self.__display_stream_listener.close()
        self.__display_stream_listener = None
        self.__display_stream = None

    @property
    def value(self):
        return self.__value

    def __display_changed(self, display):
        def display_graphic_selection_changed(graphic_selection):
            current_index = graphic_selection.current_index
            if current_index is not None:
                new_value = display.graphics[current_index]
                if new_value != self.__value:
                    self.__value = new_value
                    self.value_stream.fire(self.__value)
            elif self.__value is not None:
                self.__value = None
                self.value_stream.fire(None)
        if self.__display_graphic_selection_changed_event_listener:
            self.__display_graphic_selection_changed_event_listener.close()
            self.__display_graphic_selection_changed_event_listener = None
        if display:
            self.__display_graphic_selection_changed_event_listener = display.display_graphic_selection_changed_event.listen(display_graphic_selection_changed)
            display_graphic_selection_changed(display.graphic_selection)
        elif self.__value is not None:
            self.__value = None
            self.value_stream.fire(None)


class DisplayPropertyStream:
    # TODO: add a display_data_changed to Display class and use it here

    def __init__(self, display_stream, property_name):
        # outgoing messages
        self.value_stream = Event.Event()
        # references
        self.__display_stream = display_stream
        # initialize
        self.__property_name = property_name
        self.__display_mutated_event_listener = None
        self.__value = None
        # listen for display changes
        self.__display_stream_listener = display_stream.value_stream.listen(self.__display_changed)
        self.__display_changed(display_stream.value)

    def __del__(self):
        self.close()

    def close(self):
        self.__display_changed(None)
        self.__display_stream_listener.close()
        self.__display_stream_listener = None
        self.__display_stream = None

    @property
    def value(self):
        return self.__value

    def __display_changed(self, display):
        def display_mutated():
            new_value = getattr(display, self.__property_name)
            if new_value != self.__value:
                self.__value = new_value
                self.value_stream.fire(self.__value)
        if self.__display_mutated_event_listener:
            self.__display_mutated_event_listener.close()
            self.__display_mutated_event_listener = None
        if display:
            self.__display_mutated_event_listener = display.display_changed_event.listen(display_mutated)
            display_mutated()
        else:
            self.__value = None
            self.value_stream.fire(None)
