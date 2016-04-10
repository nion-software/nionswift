# standard libraries
import functools
import gettext
import operator
import threading
import time

# third party libraries
import numpy

# local libraries
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift import Panel
from nion.swift import Widgets
from nion.swift.model import DataItem
from nion.ui import Binding
from nion.ui import CanvasItem
from nion.ui import Event
from nion.ui import Model
from nion.ui import ThreadPool

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


class HistogramCanvasItem(CanvasItem.CanvasItemComposition):
    """A canvas item to draw and control a histogram."""

    def __init__(self):
        super().__init__()

        # tell the canvas item that we want mouse events.
        self.wants_mouse_events = True

        # create the component canvas items: adornments and the graph.
        self.__adornments_canvas_item = AdornmentsCanvasItem()
        self.__simple_line_graph_canvas_item = SimpleLineGraphCanvasItem()

        # canvas items get added back to front
        self.add_canvas_item(self.__simple_line_graph_canvas_item)
        self.add_canvas_item(self.__adornments_canvas_item)

        # used for mouse tracking.
        self.__pressed = False

        self.on_set_display_limits = None

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
        if super().mouse_position_changed(x, y, modifiers):
            return True
        canvas_width = self.canvas_size[1]
        if self.__pressed:
            current = float(x)/canvas_width
            self.__set_display_limits((min(self.start, current), max(self.start, current)))
        return True


class HistogramWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui, display_dyn, histogram_data):
        super().__init__(ui.create_column_widget(properties={"min-height": 80, "max-height": 80}))

        self.__histogram_data_and_metadata = None
        self.__histogram_data_and_metadata_lock = threading.RLock()
        self.__histogram_data_and_metadata_dirty = False

        self.__thread = ThreadPool.ThreadDispatcher(self.__update_thread, minimum_interval=0.5)
        self.__thread.start()

        self.__histogram_data = histogram_data

        def set_display_limits(display_limits):
            display = display_dyn.display
            if display:
                if display_limits is not None:
                    data_min, data_max = display.display_range
                    lower_display_limit = data_min + display_limits[0] * (data_max - data_min)
                    upper_display_limit = data_min + display_limits[1] * (data_max - data_min)
                    display.display_limits = (lower_display_limit, upper_display_limit)
                else:
                    display.display_limits = None

        # create a canvas widget for this panel and put a histogram canvas item in it.
        self.__histogram_canvas_item = HistogramCanvasItem()
        self.__histogram_canvas_item.on_set_display_limits = set_display_limits

        histogram_widget = ui.create_canvas_widget()
        histogram_widget.canvas_item.add_canvas_item(self.__histogram_canvas_item)

        def histogram_data_changed(histogram_data_and_metadata):
            with self.__histogram_data_and_metadata_lock:
                self.__histogram_data_and_metadata = histogram_data_and_metadata
                self.__histogram_data_and_metadata_dirty = True
                self.__thread.trigger()

        self.__histogram_data_changed_listener = self.__histogram_data.histogram_data_changed_event.listen(histogram_data_changed)

        self.content_widget.add(histogram_widget)

    def close(self):
        self.__histogram_data_changed_listener.close()
        self.__histogram_data_changed_listener = None
        self.__histogram_data = None
        self.__thread.close()
        self.__thread = None
        self.__histogram_canvas_item = None
        super().close()

    def _recompute(self):
        with self.__histogram_data_and_metadata_lock:
            histogram_data_and_metadata = self.__histogram_data_and_metadata
            histogram_data_and_metadata_dirty = self.__histogram_data_and_metadata_dirty
            self.__histogram_data_and_metadata = None
            self.__histogram_data_and_metadata_dirty = False
        if histogram_data_and_metadata_dirty:
            self.__histogram_canvas_item._set_histogram_data(histogram_data_and_metadata.data if histogram_data_and_metadata else None)

    def __update_thread(self):
        time.sleep(0.05)  # delay in case multiple requests arriving
        self._recompute()

    @property
    def _histogram_canvas_item(self):
        return self.__histogram_canvas_item


class StatisticsWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui, statistics):
        super().__init__(ui.create_column_widget(properties={"min-height": 18 * 3, "max-height": 18 * 3}))

        self.__dynamic_statistics = statistics

        self.__statistics = None
        self.__statistics_lock = threading.RLock()
        self.__statistics_dirty = False

        self.__thread = ThreadPool.ThreadDispatcher(self.__update_thread, minimum_interval=0.5)
        self.__thread.start()

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
        self.__stats1_property = Model.PropertyModel()
        self.__stats2_property = Model.PropertyModel()

        stats_column1_label.bind_text(Binding.PropertyBinding(self.__stats1_property, "value"))
        stats_column2_label.bind_text(Binding.PropertyBinding(self.__stats2_property, "value"))

        def statistics_changed(statistics_x):
            with self.__statistics_lock:
                self.__statistics = statistics_x
                self.__statistics_dirty = True
                self.__thread.trigger()

        self.__statistics_changed_listener = statistics.statistics_changed_event.listen(statistics_changed)

        self.content_widget.add(stats_section)

    def close(self):
        self.__statistics_changed_listener.close()
        self.__statistics_changed_listener = None
        self.__statistics = None
        self.__thread.close()
        self.__thread = None
        self.__dynamic_statistics = None
        super().close()

    def _recompute(self):
        with self.__statistics_lock:
            statistics = self.__statistics
            statistics_dirty = self.__statistics_dirty
            self.__statistics = None
            self.__statistics_dirty = False
        if statistics_dirty:
            statistics_data = dict()
            if statistics:
                statistics_data = { "mean": statistics.mean, "std": statistics.std, "min": statistics.data_min, "max": statistics.data_max, "rms": statistics.rms, "sum": statistics.sum }
            statistic_strings = list()
            for key in sorted(statistics_data.keys()):
                value = statistics_data[key]
                if value is not None:
                    statistic_str = "{0} {1:n}".format(key, statistics_data[key])
                else:
                    statistic_str = "{0} {1}".format(key, _("N/A"))
                statistic_strings.append(statistic_str)
            self.__stats1_property.value = "\n".join(statistic_strings[:(len(statistic_strings)+1)//2])
            self.__stats2_property.value = "\n".join(statistic_strings[(len(statistic_strings)+1)//2:])

    def __update_thread(self):
        time.sleep(0.05)  # delay in case multiple requests arriving
        self._recompute()


class HistogramPanel(Panel.Panel):
    """ A panel to present a histogram of the selected data item. """

    def __init__(self, document_controller, panel_id, properties):
        super().__init__(document_controller, panel_id, _("Histogram"))

        # create a binding that updates whenever the selected data item changes
        self.__selected_data_item_binding = document_controller.create_selected_data_item_binding()

        target_display = DynamicTargetDisplay(document_controller)
        display_data = DynamicDisplayData(target_display)
        display_range = DynamicDisplayRange(target_display)
        histogram_data = DynamicHistogramData(display_data, display_range)
        self.__histogram_widget = HistogramWidget(self.ui, target_display, histogram_data)

        data_range = DynamicDataRange(target_display)
        statistics = DynamicStatisticsData(display_data, data_range)
        stats_section = StatisticsWidget(self.ui, statistics)

        # create the main column with the histogram and the statistics section
        column = self.ui.create_column_widget(properties={"height": 80 + 18 * 3 + 12})
        column.add(self.__histogram_widget)
        column.add_spacing(6)
        column.add(stats_section)
        column.add_spacing(6)
        column.add_stretch()

        # this is necessary to make the panel happy
        self.widget = column

    @property
    def _histogram_widget(self):
        return self.__histogram_widget

    @property
    def _histogram_canvas_item(self):
        return self.__histogram_widget._histogram_canvas_item


class DynamicTargetDisplay:

    def __init__(self, document_controller):
        # outgoing messages
        self.display_changed_event = Event.Event()
        # cached values
        self.__display = None
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
    def display(self):
        return self.__display

    def __selected_data_item_changed(self, data_item):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        display = display_specifier.display
        if display != self.__display:
            self.display_changed_event.fire(display)
            self.__display = display


class DynamicDisplayData:
    # TODO: add a display_data_changed to Display class and use it here

    def __init__(self, dynamic_display):
        # outgoing messages
        self.display_data_and_metadata_changed_event = Event.Event()
        # references
        self.__dynamic_display = dynamic_display
        # initialize
        self.__display_mutated_event_listener = None
        self.__display_data_and_metadata = None
        # listen for display changes
        self.__display_changed_event_listener = dynamic_display.display_changed_event.listen(self.__display_changed)
        self.__display_changed(dynamic_display.display)

    def __del__(self):
        self.close()

    def close(self):
        self.__display_changed(None)
        self.__display_changed_event_listener.close()
        self.__display_changed_event_listener = None
        self.__dynamic_display = None

    @property
    def display_data_and_metadata(self):
        return self.__display_data_and_metadata

    def __display_changed(self, display):
        def display_mutated():
            self.__display_data_and_metadata = display.display_data_and_calibration
            self.display_data_and_metadata_changed_event.fire(display.display_data_and_calibration)
        if self.__display_mutated_event_listener:
            self.__display_mutated_event_listener.close()
            self.__display_mutated_event_listener = None
        if display:
            self.__display_mutated_event_listener = display.display_changed_event.listen(display_mutated)
            display_mutated()
        else:
            self.__display_data_and_metadata = None
            self.display_data_and_metadata_changed_event.fire(None)


class DynamicDisplayRange:
    # TODO: add a display_data_changed to Display class and use it here

    def __init__(self, dynamic_display):
        # outgoing messages
        self.display_range_changed_event = Event.Event()
        # references
        self.__dynamic_display = dynamic_display
        # initialize
        self.__display_mutated_event_listener = None
        self.__display_range = None
        # listen for display changes
        self.__display_changed_event_listener = dynamic_display.display_changed_event.listen(self.__display_changed)
        self.__display_changed(dynamic_display.display)

    def __del__(self):
        self.close()

    def close(self):
        self.__display_changed(None)
        self.__display_changed_event_listener.close()
        self.__display_changed_event_listener = None
        self.__dynamic_display = None

    @property
    def display_range(self):
        return self.__display_range

    def __display_changed(self, display):
        def display_mutated():
            display_range = display.display_range
            if display_range != self.__display_range:
                self.__display_range = display_range
                self.display_range_changed_event.fire(display_range)
        if self.__display_mutated_event_listener:
            self.__display_mutated_event_listener.close()
            self.__display_mutated_event_listener = None
        if display:
            self.__display_mutated_event_listener = display.display_changed_event.listen(display_mutated)
            display_mutated()
        else:
            self.display_range_changed_event.fire(None)


class DynamicHistogramData:

    def __init__(self, dynamic_display_data, dynamic_display_range):
        # outgoing messages
        self.histogram_data_changed_event = Event.Event()
        # references
        self.__dynamic_display_data = dynamic_display_data
        self.__dynamic_display_range = dynamic_display_range
        # initialize values
        self.bins = 320
        self.subsample = None  # hard coded subsample size
        self.subsample_fraction = None  # fraction of total pixels
        self.subsample_min = 1024  # minimum subsample size
        self.__display_data_and_metadata = None
        self.__display_range = None
        self.__histogram_data = None
        # listen for display changes
        self.__display_data_and_metadata_changed_event_listener = dynamic_display_data.display_data_and_metadata_changed_event.listen(self.__display_data_and_metadata_changed)
        self.__display_range_changed_event_listener = dynamic_display_range.display_range_changed_event.listen(self.__display_range_changed_event)
        self.__recalculate_histogram_data(dynamic_display_data.display_data_and_metadata, dynamic_display_range.display_range)

    def __del__(self):
        self.close()

    def close(self):
        self.__recalculate_histogram_data(None, None)
        self.__display_data_and_metadata_changed_event_listener.close()
        self.__display_range_changed_event_listener = None
        self.__dynamic_display_data = None
        self.__dynamic_display_range = None

    def __recalculate_histogram_data(self, display_data_and_metadata, display_range):
        if display_data_and_metadata != self.__display_data_and_metadata or display_range != self.__display_range:
            self.__display_data_and_metadata = display_data_and_metadata
            self.__display_range = display_range
            if self.__display_data_and_metadata is not None:
                def get_calculated_data(data_and_metadata):
                    data = data_and_metadata.data
                    subsample = self.subsample
                    total_pixels = numpy.product(data.shape)
                    if not subsample and self.subsample_fraction:
                        subsample = min(max(total_pixels * self.subsample_fraction, self.subsample_min), total_pixels)
                    if subsample:
                        factor = total_pixels / subsample
                        data_sample = numpy.random.choice(data.reshape(numpy.product(data.shape)), subsample)
                    else:
                        factor = 1.0
                        data_sample = numpy.copy(data)
                    if display_range is None or data_sample is None:
                        return None
                    histogram_data = factor * numpy.histogram(data_sample, range=display_range, bins=self.bins)[0]
                    histogram_max = numpy.max(histogram_data)  # assumes that histogram_data is int
                    if histogram_max > 0:
                        histogram_data = histogram_data / float(histogram_max)
                    return histogram_data

                self.__histogram_data = DataAndMetadata.DataAndMetadata(lambda: get_calculated_data(display_data_and_metadata), ((self.bins,), numpy.float64))
                self.histogram_data_changed_event.fire(self.__histogram_data)
            else:
                if self.__histogram_data is not None:
                    self.__histogram_data = None
                    self.histogram_data_changed_event.fire(self.__histogram_data)

    def __display_data_and_metadata_changed(self, display_data_and_metadata):
        self.__recalculate_histogram_data(display_data_and_metadata, self.__display_range)

    def __display_range_changed_event(self, display_range):
        self.__recalculate_histogram_data(self.__display_data_and_metadata, display_range)


class DynamicDataRange:
    # TODO: add a display_data_changed to Display class and use it here

    def __init__(self, dynamic_display):
        # outgoing messages
        self.data_range_changed_event = Event.Event()
        # references
        self.__dynamic_display = dynamic_display
        # initialize
        self.__display_mutated_event_listener = None
        self.__data_range = None
        # listen for display changes
        self.__display_changed_event_listener = dynamic_display.display_changed_event.listen(self.__display_changed)
        self.__display_changed(dynamic_display.display)

    def __del__(self):
        self.close()

    def close(self):
        self.__display_changed(None)
        self.__display_changed_event_listener.close()
        self.__display_changed_event_listener = None
        self.__dynamic_display = None

    @property
    def data_range(self):
        return self.__data_range

    def __display_changed(self, display):
        def display_mutated():
            data_range = display.data_range
            if data_range != self.__data_range:
                self.__data_range = data_range
                self.data_range_changed_event.fire(data_range)
        if self.__display_mutated_event_listener:
            self.__display_mutated_event_listener.close()
            self.__display_mutated_event_listener = None
        if display:
            self.__display_mutated_event_listener = display.display_changed_event.listen(display_mutated)
            display_mutated()
        else:
            self.data_range_changed_event.fire(None)


class StatisticsData:
    def __init__(self, data_fn, data_range_fn):
        self.__data_fn = data_fn
        self.__data_range_fn = data_range_fn
        self.__is_calculated = False
        self.__mean = None
        self.__std = None
        self.__rms = None
        self.__sum = None
        self.__data_min = None
        self.__data_max = None

    def __recalculate(self):
        if not self.__is_calculated:
            data = self.__data_fn()
            if data is not None:
                self.__mean = numpy.mean(data)
                self.__std = numpy.std(data)
                self.__rms = numpy.sqrt(numpy.mean(numpy.absolute(data) ** 2))
                self.__sum = self.__mean * functools.reduce(operator.mul, Image.dimensional_shape_from_shape_and_dtype(data.shape, data.dtype))
                data_range = self.__data_range_fn()
                self.__data_min, self.__data_max = data_range if data_range is not None else (None, None)
            else:
                self.__mean = None
                self.__std = None
                self.__rms = None
                self.__sum = None
                self.__data_min = None
                self.__data_max = None
            self.__is_calculated = True

    @property
    def mean(self):
        self.__recalculate()
        return self.__mean

    @property
    def std(self):
        self.__recalculate()
        return self.__std

    @property
    def rms(self):
        self.__recalculate()
        return self.__rms

    @property
    def sum(self):
        self.__recalculate()
        return self.__sum

    @property
    def data_min(self):
        self.__recalculate()
        return self.__data_min

    @property
    def data_max(self):
        self.__recalculate()
        return self.__data_max


class DynamicStatisticsData:

    def __init__(self, dynamic_display_data, dynamic_display_data_range):
        # outgoing messages
        self.statistics_changed_event = Event.Event()
        # references
        self.__dynamic_display_data = dynamic_display_data
        self.__dynamic_display_data_range = dynamic_display_data_range
        # initialize values
        self.__display_data_and_metadata = None
        self.__display_data_range = None
        self.__statistics_data = None
        # listen for display changes
        self.__display_data_and_metadata_changed_event_listener = dynamic_display_data.display_data_and_metadata_changed_event.listen(self.__display_data_and_metadata_changed)
        self.__display_data_range_changed_event_listener = dynamic_display_data_range.data_range_changed_event.listen(self.__display_data_range_changed)
        self.__display_data_and_metadata_changed(dynamic_display_data.display_data_and_metadata)
        self.__display_data_range_changed(dynamic_display_data_range.data_range)

    def __del__(self):
        self.close()

    def close(self):
        self.__display_data_and_metadata_changed(None)
        self.__display_data_and_metadata_changed_event_listener.close()
        self.__dynamic_display_data = None

    def __statistics_changed(self):
        def get_data():
            return self.__display_data_and_metadata.data if self.__display_data_and_metadata else None
        def get_data_range():
            return self.__display_data_range
        self.__statistics_data = StatisticsData(get_data, get_data_range) if self.__display_data_and_metadata else None
        self.statistics_changed_event.fire(self.__statistics_data)

    def __display_data_and_metadata_changed(self, display_data_and_metadata):
        self.__display_data_and_metadata = display_data_and_metadata
        self.__statistics_changed()

    def __display_data_range_changed(self, display_data_range):
        self.__display_data_range = display_data_range
        self.__statistics_changed()

    @property
    def statistics_data(self):
        return self.__statistics_data


# TODO: threading, reentrancy?
# TODO: long calculations
# TODO: value caching
# TODO: how to persist these snippets? each one is a program with an identifier, inputs. startup establishes them.

# # histogram widget
# target_display = current_target_display(document_controller)
# display_data = extract_display_data(target_display)
# display_limits = extract_display_limits(target_display)
# histogram_data = calculate_histogram_data(display_data, display_limits)
# histogram_widget = make_histogram_widget(histogram_data)
# histogram_widget.on_set_display_limits = set_display_limits(target_display)

# # statistics widget
# target_display = current_target_display(document_controller)
# display_data = extract_display_data(target_display)
# statistics_dict = calculate_statistics(display_data)
# statistics_widget = make_statistics_widget(statistics_dict)

# # statistics of region widget
# target_display = current_target_display(document_controller)
# target_region = current_target_region(document_controller)
# display_data = extract_display_data_in_region(target_display, target_region)
# statistics_dict = calculate_statistics(display_data)
# statistics_widget = make_statistics_widget(statistics_dict)

# # picker tool, data
# data_item = data_item_by_uuid(document_controller, uuid)
# region = region_by_uuid(document_controller, uuid)
# data = extract_data(data_item)
# mask = mask_from_region(data, region)
# set_data(computed_data_item, masked_sum_to_1d(data, mask))

# # picker tool, display slice to interval
# data_item = data_item_by_uuid(document_controller, uuid)
# display_slice_interval_region = extract_region_by_name(computed_data_item, 'display_slice')
# interval = extract_interval_from_region(display_slice_interval_region)
# display = extract_display(data_item)
# set_display_slice_interval(display, interval)

# # picker tool, interval to display slice
# data_item = data_item_by_uuid(document_controller, uuid)
# display_slice_interval_region = extract_region_by_name(computed_data_item, 'display_slice')
# display = extract_display(data_item)
# display_slice = extract_display_slice(display)
# set_region_interval(display_slice_interval_region, display_slice)

# # line profile tool, intervals
# line_profile_region = region_by_uuid(document_controller, uuid)
# line_plot_interval_list = extract_interval_list(line_plot_data_item)
# set_interval_descriptors(line_profile_region, line_plot_interval_list)

# # face finder
# data_item = data_item_by_uuid(document_controller, uuid)
# display = extract_display(data_item)
# display_data = extract_display_data(display)
# face_rectangles = find_faces(display_data)
# clear_regions_by_keyword(data_item, 'face')
# add_regions_from_rectangles(data_item, face_rectangles, 'face')
