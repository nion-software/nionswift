# standard libraries
import concurrent.futures
import functools
import gettext
import operator
import threading
import time

# third party libraries
import numpy

# local libraries
from nion.data import Image
from nion.swift import Panel
from nion.swift import Widgets
from nion.swift.model import DataItem
from nion.ui import Binding
from nion.ui import CanvasItem
from nion.ui import Event
from nion.ui import Model

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

    def __init__(self, ui, display_stream, histogram_data_future_stream):
        super().__init__(ui.create_column_widget(properties={"min-height": 80, "max-height": 80}))

        self.__histogram_data_future_stream = histogram_data_future_stream

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
        self.__histogram_canvas_item = HistogramCanvasItem()
        self.__histogram_canvas_item.on_set_display_limits = set_display_limits

        histogram_widget = ui.create_canvas_widget()
        histogram_widget.canvas_item.add_canvas_item(self.__histogram_canvas_item)

        def handle_histogram_data_future(histogram_data_future):
            def handle_histogram_data(histogram_data):
                self.__histogram_canvas_item._set_histogram_data(histogram_data)
            histogram_data_future.evaluate(handle_histogram_data)

        self.__histogram_data_stream_listener = histogram_data_future_stream.value_stream.listen(handle_histogram_data_future)
        handle_histogram_data_future(self.__histogram_data_future_stream.value)

        self.content_widget.add(histogram_widget)

    def close(self):
        self.__histogram_data_stream_listener.close()
        self.__histogram_data_stream_listener = None
        self.__histogram_data_future_stream = None
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
            return FutureValue(calculate_histogram_data, data_and_metadata, display_range)

        display_stream = TargetDisplayStream(document_controller)
        display_data_and_calibration_stream = DisplayPropertyStream(display_stream, 'display_data_and_calibration')
        display_range_stream = DisplayPropertyStream(display_stream, 'display_range')
        histogram_data_and_metadata_stream = CombineLatestStream((display_data_and_calibration_stream, display_range_stream), calculate_future_histogram_data)
        if debounce:
            histogram_data_and_metadata_stream = DebounceStream(histogram_data_and_metadata_stream, 0.05)
        if sample:
            histogram_data_and_metadata_stream = SampleStream(histogram_data_and_metadata_stream, 0.5)
        self._histogram_widget = HistogramWidget(self.ui, display_stream, histogram_data_and_metadata_stream)

        def calculate_statistics(display_data_and_metadata, display_data_range):
            data = display_data_and_metadata.data if display_data_and_metadata else None
            data_range = display_data_range
            if data is not None:
                mean = numpy.mean(data)
                std = numpy.std(data)
                rms = numpy.sqrt(numpy.mean(numpy.absolute(data) ** 2))
                sum = mean * functools.reduce(operator.mul, Image.dimensional_shape_from_shape_and_dtype(data.shape, data.dtype))
                data_min, data_max = data_range if data_range is not None else (None, None)
                return { "mean": mean, "std": std, "min": data_min, "max": data_max, "rms": rms, "sum": sum }
            return dict()

        def calculate_future_statistics(display_data_and_metadata, display_data_range):
            return FutureValue(calculate_statistics, display_data_and_metadata, display_data_range)

        display_data_range_stream = DisplayPropertyStream(display_stream, 'data_range')
        statistics_future_stream = CombineLatestStream((display_data_and_calibration_stream, display_data_range_stream), calculate_future_statistics)
        if debounce:
            statistics_future_stream = DebounceStream(statistics_future_stream, 0.05)
        if sample:
            statistics_future_stream = SampleStream(statistics_future_stream, 0.5)
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


class FutureValue:
    def __init__(self, evaluation_fn, *args):
        self.__evaluation_fn = functools.partial(evaluation_fn, *args)
        self.__is_evaluated = False
        self.__value = dict()
        self.__executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def close(self):
        self.__executor.shutdown()
        self.__executor = None
        self.__evaluation_fn = None

    def __evaluate(self):
        if not self.__is_evaluated:
            self.__value = self.__evaluation_fn()
            self.__is_evaluated = True

    @property
    def value(self):
        self.__evaluate()
        return self.__value

    def evaluate(self, done_fn):
        def call_done(future):
            done_fn(self.value)
        future = self.__executor.submit(self.__evaluate)
        future.add_done_callback(call_done)


class CombineLatestStream:

    def __init__(self, stream_list, value_fn):
        # outgoing messages
        self.value_stream = Event.Event()
        # references
        self.__stream_list = stream_list
        self.__value_fn = value_fn
        # initialize values
        self.__values = [None] * len(stream_list)
        self.__value = None
        # listen for display changes
        self.__listeners = dict()  # index
        for index, stream in enumerate(self.__stream_list):
            self.__listeners[index] = stream.value_stream.listen(functools.partial(self.__handle_stream_value, index))
            self.__values[index] = stream.value
        self.__values_changed()

    def __del__(self):
        self.close()

    def close(self):
        self.value_stream.fire(self.value)
        for index, stream in enumerate(self.__stream_list):
            self.__listeners[index].close()
            self.__values[index] = None
        self.__stream_list = None
        self.__values = None
        self.__value = None

    def __handle_stream_value(self, index, value):
        self.__values[index] = value
        self.__values_changed()

    def __values_changed(self):
        self.__value = self.__value_fn(*self.__values)
        self.value_stream.fire(self.__value)

    @property
    def value(self):
        return self.__value


class DebounceStream:

    def __init__(self, input_stream, period):
        self.value_stream = Event.Event()
        self.__input_stream = input_stream
        self.__period = period
        self.__last_time = 0
        self.__value = None
        self.__executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.__listener = input_stream.value_stream.listen(self.__value_changed)
        self.__value_changed(input_stream.value)

    def __del__(self):
        self.close()

    def close(self):
        self.__listener.close()
        self.__listener = None
        self.__input_stream = None
        self.__executor.shutdown()
        self.__executor = None

    def __value_changed(self, value):
        self.__value = value
        current_time = time.time()
        if current_time - self.__last_time > self.__period:
            def do_sleep():
                time.sleep(self.__period)
            def call_done(future):
                self.value_stream.fire(self.__value)
            self.__last_time = current_time
            future = self.__executor.submit(do_sleep)
            future.add_done_callback(call_done)

    @property
    def value(self):
        return self.__value


class SampleStream:

    def __init__(self, input_stream, period):
        self.value_stream = Event.Event()
        self.__input_stream = input_stream
        self.__period = period
        self.__last_time = 0
        self.__pending_value = None
        self.__value = None
        self.__executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.__executor_lock = threading.RLock()
        self.__listener = input_stream.value_stream.listen(self.__value_changed)
        self.__value = input_stream.value
        self.__value_dirty = True
        self.__value_dirty_lock = threading.RLock()
        self.__queue_executor()

    def __del__(self):
        self.close()

    def close(self):
        self.__listener.close()
        self.__listener = None
        self.__input_stream = None
        with self.__executor_lock:  # deadlock?
            self.__executor.shutdown()
            self.__executor = None

    def __do_sleep(self):
        time.sleep(self.__period)

    def __call_done(self, future):
        with self.__value_dirty_lock:
            value_dirty = self.__value_dirty
            self.__value_dirty = False
        if value_dirty:
            self.__value = self.__pending_value
            self.value_stream.fire(self.__pending_value)
        self.__queue_executor()

    def __queue_executor(self):
        with self.__executor_lock:
            future = self.__executor.submit(self.__do_sleep)
            future.add_done_callback(self.__call_done)

    def __value_changed(self, value):
        with self.__value_dirty_lock:
            self.__value_dirty = True
        self.__pending_value = value

    @property
    def value(self):
        return self.__value


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
