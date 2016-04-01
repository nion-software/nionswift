# standard libraries
import gettext
import threading

# third party libraries
# None

# local libraries
from nion.data import Image
from nion.swift import Panel
from nion.swift.model import DataItem
from nion.ui import Binding
from nion.ui import CanvasItem
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


class HistogramPanel(Panel.Panel):
    """ A panel to present a histogram of the selected data item. """

    def __init__(self, document_controller, panel_id, properties):
        super().__init__(document_controller, panel_id, _("Histogram"))

        # create a binding that updates whenever the selected data item changes
        self.__selected_data_item_binding = document_controller.create_selected_data_item_binding()

        # create a canvas widget for this panel and put a histogram canvas item in it.
        self.__histogram_canvas_item = HistogramCanvasItem()

        histogram_widget = self.ui.create_canvas_widget(properties={"min-height": 80, "max-height": 80})
        histogram_widget.canvas_item.add_canvas_item(self.__histogram_canvas_item)

        # create a statistics section
        stats_column1 = self.ui.create_column_widget(properties={"min-width": 140, "max-width": 140})
        stats_column2 = self.ui.create_column_widget(properties={"min-width": 140, "max-width": 140})
        stats_column1_label = self.ui.create_label_widget()
        stats_column2_label = self.ui.create_label_widget()
        stats_column1.add(stats_column1_label)
        stats_column2.add(stats_column2_label)
        stats_section = self.ui.create_row_widget()
        stats_section.add_spacing(13)
        stats_section.add(stats_column1)
        stats_section.add_stretch()
        stats_section.add(stats_column2)
        stats_section.add_spacing(13)

        # create the main column with the histogram and the statistics section
        column = self.ui.create_column_widget(properties={"height": 80 + 18 * 3})
        column.add(histogram_widget)
        column.add_spacing(6)
        column.add(stats_section)
        column.add_spacing(6)
        column.add_stretch()

        # create property models for the
        self.stats1_property = Model.PropertyModel()
        self.stats2_property = Model.PropertyModel()

        stats_column1_label.bind_text(Binding.PropertyBinding(self.stats1_property, "value"))
        stats_column2_label.bind_text(Binding.PropertyBinding(self.stats2_property, "value"))

        # this is necessary to make the panel happy
        self.widget = column

        # the display holds the current display to which this histogram is listening.
        self.__data_item = None
        self.__display = None
        self.__display_lock = threading.RLock()

        # listen for selected display binding changes
        self.__data_item_changed_event_listener = self.__selected_data_item_binding.data_item_changed_event.listen(self.__data_item_changed)
        # manually send the first initial data item changed message to set things up.
        self.__data_item_changed(self.__selected_data_item_binding.data_item)

        def set_display_limits(display_limits):
            if self.__display:
                if display_limits is not None:
                    data_min, data_max = self.__display.display_range
                    lower_display_limit = data_min + display_limits[0] * (data_max - data_min)
                    upper_display_limit = data_min + display_limits[1] * (data_max - data_min)
                    self.__display.display_limits = (lower_display_limit, upper_display_limit)
                else:
                    self.__display.display_limits = None

        self.__histogram_canvas_item.on_set_display_limits = set_display_limits

    def close(self):
        # disconnect data item binding
        self.__data_item_changed(None)
        self.__data_item_changed_event_listener.close()
        self.__data_item_changed_event_listener = None
        self.__selected_data_item_binding.close()
        self.__selected_data_item_binding = None
        self.__set_display(None, None)
        self.clear_task("statistics")
        super().close()

    @property
    def _histogram_canvas_item(self):
        return self.__histogram_canvas_item

    # thread safe
    def __update_statistics(self, statistics_data):
        """Update the widgets with new statistics data."""
        statistic_strings = list()
        for key in sorted(statistics_data.keys()):
            value = statistics_data[key]
            if value is not None:
                statistic_str = "{0} {1:n}".format(key, statistics_data[key])
            else:
                statistic_str = "{0} {1}".format(key, _("N/A"))
            statistic_strings.append(statistic_str)
        self.stats1_property.value = "\n".join(statistic_strings[:(len(statistic_strings)+1)//2])
        self.stats2_property.value = "\n".join(statistic_strings[(len(statistic_strings)+1)//2:])

    # thread safe
    def __set_display(self, data_item, display):
        # typically could be updated from an acquisition thread and a
        # focus changed thread (why?).
        with self.__display_lock:
            if self.__display:
                self.__display_processor_needs_recompute_event_listener.close()
                self.__display_processor_needs_recompute_event_listener = None
                self.__display_processor_data_updated_event_listener.close()
                self.__display_processor_data_updated_event_listener = None
            self.__data_item = data_item
            self.__display = display
            if self.__display:

                def display_processor_needs_recompute(processor):
                    document_model = self.document_controller.document_model
                    with self.__display_lock:
                        display = self.__display
                    if processor == display.get_processor("histogram"):
                        processor.recompute_if_necessary(document_model.dispatch_task, None)
                    if processor == display.get_processor("statistics"):
                        processor.recompute_if_necessary(document_model.dispatch_task, None)

                def display_processor_data_updated(processor):
                    with self.__display_lock:
                        display = self.__display
                    if processor == display.get_processor("histogram"):
                        histogram_data = display.get_processed_data("histogram")
                        self.__histogram_canvas_item.histogram_data = histogram_data
                    if processor == display.get_processor("statistics"):
                        statistics_data = display.get_processed_data("statistics")
                        self.__update_statistics(statistics_data)

                self.__display_processor_needs_recompute_event_listener = display.display_processor_needs_recompute_event.listen(display_processor_needs_recompute)
                self.__display_processor_data_updated_event_listener = display.display_processor_data_updated_event.listen(display_processor_data_updated)

                self.__display.add_listener(self)

    # this message is received from the data item binding.
    # when a new display is set, this panel becomes a listener
    # of the display. it will receive messages from the processors
    # when data needs to be recomputed and when data gets updated.
    # in response to a needs recompute message, this object will
    # queue the processor to compute its data on the document model.
    # in response to a data changed message, this object will update
    # the data and trigger a repaint.
    # thread safe
    def __data_item_changed(self, data_item):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.__set_display(display_specifier.data_item, display_specifier.display)
        histogram_data = display_specifier.display.get_processed_data("histogram") if display_specifier.display else None
        self.__histogram_canvas_item._set_histogram_data(histogram_data)
        if display_specifier.display:
            statistics_data = display_specifier.display.get_processed_data("statistics")
            document_model = self.document_controller.document_model
            display_specifier.display.get_processor("statistics").recompute_if_necessary(document_model.dispatch_task, None)
            display_specifier.display.get_processor("histogram").recompute_if_necessary(document_model.dispatch_task, None)
        else:
            statistics_data = dict()
        self.__update_statistics(statistics_data)
