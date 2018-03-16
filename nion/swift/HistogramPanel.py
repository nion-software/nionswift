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
from nion.swift import DisplayPanel
from nion.swift import Panel
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import Widgets
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
        canvas_height = self.canvas_size[0]

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
        self.sizing.set_fixed_height(4)
        self.__color_map_data = None

    @property
    def color_map_data(self) -> numpy.ndarray:
        """Return the data."""
        return self.__color_map_data

    @color_map_data.setter
    def color_map_data(self, data: numpy.ndarray) -> None:
        """Set the data and mark the canvas item for updating.

        Data should be an ndarray of shape (256, 3) with type uint8
        """
        self.__color_map_data = data
        self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext):
        """Repaint the canvas item. This will occur on a thread."""

        # canvas size
        canvas_width = self.canvas_size.width
        canvas_height = self.canvas_size.height

        with drawing_context.saver():
            if self.__color_map_data is not None:
                rgba_image = numpy.empty((4,) + self.__color_map_data.shape[:-1], dtype=numpy.uint32)
                Image.get_rgb_view(rgba_image)[:] = self.__color_map_data[numpy.newaxis, :, :]  # scalar data assigned to each component of rgb view
                Image.get_alpha_view(rgba_image)[:] = 255
                drawing_context.draw_image(rgba_image, 0, 0, canvas_width, canvas_height)


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

    @property
    def histogram_data(self):
        return self.__simple_line_graph_canvas_item.data

    @histogram_data.setter
    def histogram_data(self, histogram_data):
        self.__simple_line_graph_canvas_item.data = histogram_data

    @property
    def color_map_data(self) -> numpy.ndarray:
        return self.__histogram_color_map_canvas_item.color_map_data

    @color_map_data.setter
    def color_map_data(self, color_map_data: numpy.ndarray) -> None:
        self.__histogram_color_map_canvas_item.color_map_data = color_map_data

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
        self.__set_display_limits((0, 1))
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


class HistogramWidgetData:
    def __init__(self, data=None, display_range=None):
        self.data = data
        self.display_range = display_range


class HistogramWidget(Widgets.CompositeWidgetBase):

    def __init__(self, document_controller, display_stream, histogram_widget_data_model, color_map_data_model, cursor_changed_fn):
        super().__init__(document_controller.ui.create_column_widget(properties={"min-height": 84, "max-height": 84}))

        ui = document_controller.ui

        self.__display_stream = display_stream.add_ref()

        self.__histogram_data_model = histogram_widget_data_model
        self.__color_map_data_model = color_map_data_model

        self.__display_range = None

        def histogram_data_changed(key: str) -> None:
            if key == "value":
                histogram_widget_data = self.__histogram_data_model.value
                self.__histogram_canvas_item._set_histogram_data(histogram_widget_data.data)
                self.__display_range = histogram_widget_data.display_range

        self.__histogram_data_property_changed_event_listener = self.__histogram_data_model.property_changed_event.listen(histogram_data_changed)

        def set_display_limits(display_limits):
            # display_limits in this context are in the range of 0,1
            # we ask for the display_range from the display to get actual
            # data values (never None), and create new display limits
            # based on those data values combined with display_limits.
            # then we set the display_limits on the display, which have
            # the same units as the data values.
            display = self.__display_stream.value
            if display:
                new_display_limits = None
                if display_limits is not None and self.__display_range is not None:
                    data_min, data_max = self.__display_range
                    lower_display_limit = data_min + display_limits[0] * (data_max - data_min)
                    upper_display_limit = data_min + display_limits[1] * (data_max - data_min)
                    new_display_limits = (lower_display_limit, upper_display_limit)

                command = DisplayPanel.ChangeDisplayCommand(document_controller.document_model, display, display_limits=new_display_limits, title=_("Change Display Limits"))
                command.perform()
                document_controller.push_undo_command(command)

        def cursor_changed(canvas_x):
            if callable(cursor_changed_fn):
                cursor_changed_fn(canvas_x, self.__display_range)

        # create a canvas widget for this panel and put a histogram canvas item in it.
        self.__histogram_canvas_item = HistogramCanvasItem(cursor_changed)
        self.__histogram_canvas_item.on_set_display_limits = set_display_limits

        histogram_widget = ui.create_canvas_widget()
        histogram_widget.canvas_item.add_canvas_item(self.__histogram_canvas_item)

        def handle_update_color_map_data(color_map_data):
            self.__histogram_canvas_item.color_map_data = color_map_data

        def color_map_data_changed(key: str) -> None:
            if key == "value":
                self.__histogram_canvas_item.color_map_data = self.__color_map_data_model.value

        self.__color_map_data_stream_listener = self.__color_map_data_model.property_changed_event.listen(color_map_data_changed)

        histogram_data_changed("value")

        color_map_data_changed("value")

        self.content_widget.add(histogram_widget)

    def close(self):
        self.__color_map_data_stream_listener.close()
        self.__color_map_data_stream_listener = None
        self.__display_stream.remove_ref()
        self.__display_stream = None
        self.__histogram_canvas_item = None
        self.__histogram_data_property_changed_event_listener.close()
        self.__histogram_data_property_changed_event_listener = None
        super().close()

    def _recompute(self):
        pass

    @property
    def _histogram_canvas_item(self):
        return self.__histogram_canvas_item

    @property
    def _histogram_data_func_value_model(self):
        # for testing
        return self.__histogram_data_model


class StatisticsWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui, statistics_model):
        super().__init__(ui.create_column_widget(properties={"min-height": 18 * 3, "max-height": 18 * 3}))

        # create property models for the UI
        self._stats1_property = Model.PropertyModel(str())
        self._stats2_property = Model.PropertyModel(str())

        self.__statistics_model = statistics_model

        def statistics_changed(key: str) -> None:
            if key == "value":
                statistics_data = self.__statistics_model.value
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

        self.content_widget.add(stats_section)

    def close(self):
        self.__statistics_property_changed_event_listener.close()
        self.__statistics_property_changed_event_listener = None
        super().close()

    @property
    def _statistics_func_value_model(self):
        # for testing
        return self.__statistics_model

    def _recompute(self):
        pass


# import asyncio

class HistogramPanel(Panel.Panel):
    """ A panel to present a histogram of the selected data item. """

    def __init__(self, document_controller, panel_id, properties, debounce=True, sample=True):
        super().__init__(document_controller, panel_id, _("Histogram"))

        def calculate_region_data(display_data_and_metadata, region):
            if region is not None and display_data_and_metadata is not None:
                if display_data_and_metadata.is_data_1d and isinstance(region, Graphics.IntervalGraphic):
                    interval = region.interval
                    if 0 <= interval[0] < 1 and 0 < interval[1] <= 1:
                        start, end = int(interval[0] * display_data_and_metadata.data_shape[0]), int(interval[1] * display_data_and_metadata.data_shape[0])
                        if end - start >= 1:
                            cropped_data_and_metadata = Core.function_crop_interval(display_data_and_metadata, interval)
                            if cropped_data_and_metadata:
                                return cropped_data_and_metadata
                elif display_data_and_metadata.is_data_2d and isinstance(region, Graphics.RectangleTypeGraphic):
                    cropped_data_and_metadata = Core.function_crop(display_data_and_metadata, region.bounds)
                    if cropped_data_and_metadata:
                        return cropped_data_and_metadata
            return display_data_and_metadata

        def calculate_region_data_func(display_data_and_metadata, region):
            return functools.partial(calculate_region_data, display_data_and_metadata, region)

        def calculate_histogram_widget_data(display_data_and_metadata_func, display_range):
            bins = 320
            subsample = 0  # hard coded subsample size
            subsample_fraction = None  # fraction of total pixels
            subsample_min = 1024  # minimum subsample size
            display_data_and_metadata = display_data_and_metadata_func()
            display_data = display_data_and_metadata.data if display_data_and_metadata else None
            if display_data is not None:
                total_pixels = numpy.product(display_data.shape)
                if not subsample and subsample_fraction:
                    subsample = min(max(total_pixels * subsample_fraction, subsample_min), total_pixels)
                if subsample:
                    factor = total_pixels / subsample
                    data_sample = numpy.random.choice(display_data.reshape(numpy.product(display_data.shape)), subsample)
                else:
                    factor = 1.0
                    data_sample = numpy.copy(display_data)
                if display_range is None or data_sample is None:
                    return HistogramWidgetData()
                histogram_data = factor * numpy.histogram(data_sample, range=display_range, bins=bins)[0]
                histogram_max = numpy.max(histogram_data)  # assumes that histogram_data is int
                if histogram_max > 0:
                    histogram_data = histogram_data / float(histogram_max)
                return HistogramWidgetData(histogram_data, display_range)
            return HistogramWidgetData()

        def calculate_histogram_widget_data_func(display_data_and_metadata_model_func, display_range):
            return functools.partial(calculate_histogram_widget_data, display_data_and_metadata_model_func, display_range)

        display_stream = TargetDisplayStream(document_controller)
        region_stream = TargetRegionStream(display_stream)
        def compare_data(a, b):
            return numpy.array_equal(a.data if a else None, b.data if b else None)
        display_data_and_metadata_stream = DisplayTransientsStream(display_stream, "display_data_and_metadata", cmp=compare_data)
        display_range_stream = DisplayTransientsStream(display_stream, "display_range")
        region_data_and_metadata_func_stream = Stream.CombineLatestStream((display_data_and_metadata_stream, region_stream), calculate_region_data_func)
        histogram_widget_data_func_stream = Stream.CombineLatestStream((region_data_and_metadata_func_stream, display_range_stream), calculate_histogram_widget_data_func)
        color_map_data_stream = DisplayPropertyStream(display_stream, "color_map_data", cmp=numpy.array_equal)
        if debounce:
            histogram_widget_data_func_stream = Stream.DebounceStream(histogram_widget_data_func_stream, 0.05, document_controller.event_loop)
        if sample:
            histogram_widget_data_func_stream = Stream.SampleStream(histogram_widget_data_func_stream, 0.5, document_controller.event_loop)

        def cursor_changed_fn(canvas_x: float, display_range) -> None:
            if not canvas_x:
                document_controller.cursor_changed(None)
            if display_stream and display_stream.value and canvas_x:
                if display_range is not None:  # can be None with empty data
                    displayed_intensity_calibration = display_stream.value.displayed_intensity_calibration
                    adjusted_x = display_range[0] + canvas_x * (display_range[1] - display_range[0])
                    adjusted_x = displayed_intensity_calibration.convert_to_calibrated_value_str(adjusted_x)
                    document_controller.cursor_changed([_('Intensity: ') + str(adjusted_x)])
                else:
                    document_controller.cursor_changed(None)

        self.__histogram_widget_data_model = Model.FuncStreamValueModel(histogram_widget_data_func_stream, document_controller.event_loop, value=HistogramWidgetData(), cmp=numpy.array_equal)
        self.__color_map_data_model = Model.StreamValueModel(color_map_data_stream, cmp=numpy.array_equal)

        self._histogram_widget = HistogramWidget(document_controller, display_stream, self.__histogram_widget_data_model, self.__color_map_data_model, cursor_changed_fn)

        def calculate_statistics(display_data_and_metadata_func, display_data_range, region, displayed_intensity_calibration):
            display_data_and_metadata = display_data_and_metadata_func()
            data = display_data_and_metadata.data if display_data_and_metadata else None
            data_range = display_data_range
            if data is not None and data.size > 0 and displayed_intensity_calibration:
                mean = numpy.mean(data)
                std = numpy.std(data)
                rms = numpy.sqrt(numpy.mean(numpy.square(numpy.absolute(data))))
                sum_data = mean * functools.reduce(operator.mul, Image.dimensional_shape_from_shape_and_dtype(data.shape, data.dtype))
                if region is None:
                    data_min, data_max = data_range if data_range is not None else (None, None)
                else:
                    data_min, data_max = numpy.amin(data), numpy.amax(data)
                mean_str = displayed_intensity_calibration.convert_to_calibrated_value_str(mean)
                std_str = displayed_intensity_calibration.convert_to_calibrated_value_str(std)
                data_min_str = displayed_intensity_calibration.convert_to_calibrated_value_str(data_min)
                data_max_str = displayed_intensity_calibration.convert_to_calibrated_value_str(data_max)
                rms_str = displayed_intensity_calibration.convert_to_calibrated_value_str(rms)
                sum_data_str = displayed_intensity_calibration.convert_to_calibrated_value_str(sum_data)

                return { "mean": mean_str, "std": std_str, "min": data_min_str, "max": data_max_str, "rms": rms_str, "sum": sum_data_str }
            return dict()

        def calculate_statistics_func(display_data_and_metadata_model_func, display_data_range, region, displayed_intensity_calibration):
            return functools.partial(calculate_statistics, display_data_and_metadata_model_func, display_data_range, region, displayed_intensity_calibration)

        display_data_range_stream = DisplayTransientsStream(display_stream, "data_range")
        displayed_intensity_calibration_stream = DisplayPropertyStream(display_stream, 'displayed_intensity_calibration')
        statistics_func_stream = Stream.CombineLatestStream((region_data_and_metadata_func_stream, display_data_range_stream, region_stream, displayed_intensity_calibration_stream), calculate_statistics_func)
        if debounce:
            statistics_func_stream = Stream.DebounceStream(statistics_func_stream, 0.05, document_controller.event_loop)
        if sample:
            statistics_func_stream = Stream.SampleStream(statistics_func_stream, 0.5, document_controller.event_loop)

        self.__statistics_model = Model.FuncStreamValueModel(statistics_func_stream, document_controller.event_loop, value=dict(), cmp=numpy.array_equal)

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

    def close(self):
        self.__histogram_widget_data_model.close()
        self.__histogram_widget_data_model = None
        self.__color_map_data_model.close()
        self.__color_map_data_model = None
        self.__statistics_model.close()
        self.__statistics_model = None
        super().close()


class TargetDataItemStream(Stream.AbstractStream):

    def __init__(self, document_controller):
        super().__init__()
        # outgoing messages
        self.value_stream = Event.Event()
        # cached values
        self.__value = None
        # listen for selected data item changes
        self.__focused_data_item_changed_event_listener = document_controller.focused_data_item_changed_event.listen(self.__focused_data_item_changed)
        # manually send the first data item changed message to set things up.
        self.__focused_data_item_changed(document_controller.selected_display_specifier.data_item)

    def close(self):
        # disconnect data item binding
        self.__focused_data_item_changed(None)
        self.__focused_data_item_changed_event_listener.close()
        self.__focused_data_item_changed_event_listener = None
        super().close()

    @property
    def value(self):
        return self.__value

    def __focused_data_item_changed(self, data_item: typing.Optional[DataItem.DataItem]) -> None:
        if data_item != self.__value:
            self.value_stream.fire(data_item)
            self.__value = data_item


class TargetDisplayStream(Stream.AbstractStream):

    def __init__(self, document_controller):
        super().__init__()
        # outgoing messages
        self.value_stream = Event.Event()
        # cached values
        self.__value = None
        # listen for selected data item changes
        self.__focused_data_item_changed_event_listener = document_controller.focused_data_item_changed_event.listen(self.__focused_data_item_changed)
        # manually send the first data item changed message to set things up.
        self.__focused_data_item_changed(document_controller.selected_display_specifier.data_item)

    def close(self):
        # disconnect data item binding
        self.__focused_data_item_changed(None)
        self.__focused_data_item_changed_event_listener.close()
        self.__focused_data_item_changed_event_listener = None
        super().close()

    @property
    def value(self):
        return self.__value

    def __focused_data_item_changed(self, data_item: typing.Optional[DataItem.DataItem]) -> None:
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        if display != self.__value:
            self.value_stream.fire(display)
            self.__value = display


class TargetRegionStream(Stream.AbstractStream):

    def __init__(self, display_stream):
        super().__init__()
        # outgoing messages
        self.value_stream = Event.Event()
        # references
        self.__display_stream = display_stream.add_ref()
        # initialize
        self.__display_graphic_selection_changed_event_listener = None
        self.__value = None
        # listen for display changes
        self.__display_stream_listener = display_stream.value_stream.listen(self.__display_changed)
        self.__graphic_changed_event_listener = None
        self.__display_changed(display_stream.value)

    def close(self):
        self.__display_changed(None)
        self.__display_stream_listener.close()
        self.__display_stream_listener = None
        self.__display_stream.remove_ref()
        self.__display_stream = None
        super().close()

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
                    def graphic_changed():
                        self.value_stream.fire(self.__value)
                    if self.__graphic_changed_event_listener:
                        self.__graphic_changed_event_listener.close()
                        self.__graphic_changed_event_listener = None
                    if self.__value:
                        self.__graphic_changed_event_listener = self.__value.graphic_changed_event.listen(graphic_changed)
                    graphic_changed()
            elif self.__value is not None:
                self.__value = None
                self.value_stream.fire(None)
        if self.__graphic_changed_event_listener:
            self.__graphic_changed_event_listener.close()
            self.__graphic_changed_event_listener = None
        if self.__display_graphic_selection_changed_event_listener:
            self.__display_graphic_selection_changed_event_listener.close()
            self.__display_graphic_selection_changed_event_listener = None
        if display:
            self.__display_graphic_selection_changed_event_listener = display.display_graphic_selection_changed_event.listen(display_graphic_selection_changed)
            display_graphic_selection_changed(display.graphic_selection)
        elif self.__value is not None:
            self.__value = None
            self.value_stream.fire(None)


class DisplayPropertyStream(Stream.AbstractStream):
    # TODO: add a display_data_changed to Display class and use it here

    def __init__(self, display_stream, property_name, cmp=None):
        super().__init__()
        # outgoing messages
        self.value_stream = Event.Event()
        # references
        self.__display_stream = display_stream.add_ref()
        # initialize
        self.__property_name = property_name
        self.__property_changed_event_listener = None
        self.__value = None
        self.__cmp = cmp if cmp else operator.eq
        # listen for display changes
        self.__display_stream_listener = display_stream.value_stream.listen(self.__display_changed)
        self.__display_changed(display_stream.value)

    def close(self):
        self.__display_changed(None)
        self.__display_stream_listener.close()
        self.__display_stream_listener = None
        self.__display_stream.remove_ref()
        self.__display_stream = None
        super().close()

    @property
    def value(self):
        return self.__value

    def __display_changed(self, display):
        def property_changed(key):
            if key == self.__property_name:
                new_value = getattr(display, self.__property_name)
                if not self.__cmp(new_value, self.__value):
                    self.__value = new_value
                    self.value_stream.fire(self.__value)
        if self.__property_changed_event_listener:
            self.__property_changed_event_listener.close()
            self.__property_changed_event_listener = None
        if display:
            self.__property_changed_event_listener = display.property_changed_event.listen(property_changed)
            property_changed(self.__property_name)
        else:
            self.__value = None
            self.value_stream.fire(None)


class DisplayTransientsStream(Stream.AbstractStream):
    # TODO: add a display_data_changed to Display class and use it here

    def __init__(self, display_stream, property_name, cmp=None):
        super().__init__()
        # outgoing messages
        self.value_stream = Event.Event()
        # initialize
        self.__property_name = property_name
        self.__value = None
        self.__display_values_changed_listener = None
        self.__next_calculated_display_values_listener = None
        self.__cmp = cmp if cmp else operator.eq
        # listen for display changes
        self.__display_stream = display_stream.add_ref()
        self.__display_stream_listener = display_stream.value_stream.listen(self.__display_changed)
        self.__display_changed(display_stream.value)

    def close(self):
        self.__display_changed(None)
        self.__display_stream_listener.close()
        self.__display_stream_listener = None
        self.__display_stream.remove_ref()
        self.__display_stream = None
        super().close()

    @property
    def value(self):
        return self.__value

    def __display_changed(self, display):
        def display_values_changed():
            display_values = display.get_calculated_display_values(True)
            new_value = getattr(display_values, self.__property_name)
            if not self.__cmp(new_value, self.__value):
                self.__value = new_value
                self.value_stream.fire(self.__value)
        if self.__next_calculated_display_values_listener:
            self.__next_calculated_display_values_listener.close()
            self.__next_calculated_display_values_listener = None
        if self.__display_values_changed_listener:
            self.__display_values_changed_listener.close()
            self.__display_values_changed_listener = None
        if display:
            # there are two listeners - the first when new display properties have triggered new display values.
            # the second whenever actual new display values arrive. this ensures the display gets updated after
            # the user changes it. could use some rethinking.
            self.__next_calculated_display_values_listener = display.add_calculated_display_values_listener(display_values_changed)
            self.__display_values_changed_listener = display.display_values_changed_event.listen(display_values_changed)
            display_values_changed()
        else:
            self.__value = None
            self.value_stream.fire(None)
