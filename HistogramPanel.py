# standard libraries
import gettext
import logging

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.model import Image
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
        super(AdornmentsCanvasItem, self).__init__()
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
        super(SimpleLineGraphCanvasItem, self).__init__()
        self.__data = None
        self.__background_color = None

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
            binned_data = Image.rebin_1d(self.data, int(canvas_width)) if int(canvas_width) != self.data.shape[0] else self.data
            for i in xrange(canvas_width):
                drawing_context.move_to(i, canvas_height)
                drawing_context.line_to(i, canvas_height * (1 - binned_data[i]))
            drawing_context.line_width = 1
            drawing_context.stroke_style = "#444"
            drawing_context.stroke()
            drawing_context.restore()


class HistogramCanvasItem(CanvasItem.CanvasItemComposition):
    """A canvas item to draw and control a histogram."""

    def __init__(self):
        super(HistogramCanvasItem, self).__init__()

        # tell the canvas item that we want mouse events.
        self.wants_mouse_events = True

        # create the component canvas items: adornments and the graph.
        self.__adornments_canvas_item = AdornmentsCanvasItem()
        self.__simple_line_graph_canvas_item = SimpleLineGraphCanvasItem()

        # canvas items get added back to front
        self.add_canvas_item(self.__simple_line_graph_canvas_item)
        self.add_canvas_item(self.__adornments_canvas_item)

        # the display holds the current display to which this histogram is listening.
        self.__display = None

        # used for mouse tracking.
        self.__pressed = False

    def close(self):
        self._set_display(None)
        super(HistogramCanvasItem, self).close()

    @property
    def background_color(self):
        """Return the background color."""
        return self.__simple_line_graph_canvas_item.background_color

    @background_color.setter
    def background_color(self, background_color):
        """Set the background color, in the CSS color format."""
        self.__simple_line_graph_canvas_item.background_color = background_color

    def _get_display(self):
        """Return the display. Used for testing."""
        return self.__display

    def _set_display(self, display):
        """Set the display that this histogram is displaying.

        The display parameter can be None.
        """

        # un-listen to the existing display. then listen to the new display.
        self.__display = display

        # if the user is currently dragging the display limits, we don't want to update
        # from changing data at the same time. but we _do_ want to draw the updated data.
        if not self.__pressed:
            self.__adornments_canvas_item.display_limits = (0, 1)

        # grab the cached data and display it
        histogram_data = self.__display.get_processed_data("histogram") if self.__display else None
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
        if super(HistogramCanvasItem, self).mouse_double_clicked(x, y, modifiers):
            return True
        self.__set_display_limits((0, 1))
        if self.__display:
            self.__display.display_limits = None
        return True

    def mouse_pressed(self, x, y, modifiers):
        if super(HistogramCanvasItem, self).mouse_pressed(x, y, modifiers):
            return True
        self.__pressed = True
        self.start = float(x)/self.canvas_size[1]
        self.__set_display_limits((self.start, self.start))
        return True

    def mouse_released(self, x, y, modifiers):
        if super(HistogramCanvasItem, self).mouse_released(x, y, modifiers):
            return True
        self.__pressed = False
        display_limit_range = self.__adornments_canvas_item.display_limits[1] - self.__adornments_canvas_item.display_limits[0]
        if self.__display and (display_limit_range > 0) and (display_limit_range < 1):
            data_min, data_max = self.__display.display_range
            lower_display_limit = data_min + self.__adornments_canvas_item.display_limits[0] * (data_max - data_min)
            upper_display_limit = data_min + self.__adornments_canvas_item.display_limits[1] * (data_max - data_min)
            self.__display.display_limits = (lower_display_limit, upper_display_limit)
        return True

    def mouse_position_changed(self, x, y, modifiers):
        if super(HistogramCanvasItem, self).mouse_position_changed(x, y, modifiers):
            return True
        canvas_width = self.canvas_size[1]
        if self.__pressed:
            current = float(x)/canvas_width
            self.__set_display_limits((min(self.start, current), max(self.start, current)))
        return True


class HistogramPanel(Panel.Panel):
    """ A panel to present a histogram of the selected data item. """

    def __init__(self, document_controller, panel_id, properties):
        super(HistogramPanel, self).__init__(document_controller, panel_id, _("Histogram"))

        # create a binding that updates whenever the selected data item changes
        self.__selected_data_item_binding = document_controller.create_selected_data_item_binding()

        # create a root canvas item for this panel and put a histogram canvas item in it.
        self.__root_histogram_canvas_item = CanvasItem.RootCanvasItem(document_controller.ui, properties={"min-height": 80, "max-height": 80})
        self.__histogram_canvas_item = HistogramCanvasItem()
        self.__root_histogram_canvas_item.add_canvas_item(self.__histogram_canvas_item)

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
        column.add(self.__root_histogram_canvas_item.canvas_widget)
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
        self.__display = None

        # connect self as listener. this will result in calls to data_item_binding_display_changed
        # then manually send the first initial data item changed message to set things up.
        self.__selected_data_item_binding.add_listener(self)
        self.data_item_binding_display_changed(self.__selected_data_item_binding.display)

    def close(self):
        self.__root_histogram_canvas_item.close()
        self.__root_histogram_canvas_item = None
        # disconnect data item binding
        self.data_item_binding_display_changed(None)
        self.__selected_data_item_binding.remove_listener(self)
        self.__selected_data_item_binding.close()
        self.__selected_data_item_binding = None
        self.__set_display(None)
        self.clear_task("statistics")
        super(HistogramPanel, self).close()

    @property
    def _histogram_canvas_item(self):
        return self.__histogram_canvas_item

    def __update_statistics(self, statistics_data):
        """Update the widgets with new statistics data. Must be called on UI thread."""
        statistic_strings = list()
        for key in sorted(statistics_data.keys()):
            value = statistics_data[key]
            if value is not None:
                statistic_str = "{0} {1:n}".format(key, statistics_data[key])
            else:
                statistic_str = "{0} {1}".format(key, _("N/A"))
            statistic_strings.append(statistic_str)
        self.stats1_property.value = "\n".join(statistic_strings[:(len(statistic_strings)+1)/2])
        self.stats2_property.value = "\n".join(statistic_strings[(len(statistic_strings)+1)/2:])

    def __set_display(self, display):
        if self.__display:
            self.__display.remove_listener(self)
            self.__display.data_item.remove_listener(self)
        self.__display = display
        if self.__display:
            self.__display.add_listener(self)
            self.__display.data_item.add_listener(self)

    # this message is received from the data item binding.
    # when a new display is set, this panel becomes a listener
    # of the display. it will receive messages from the processors
    # when data needs to be recomputed and when data gets updated.
    # in response to a needs recompute message, this object will
    # queue the processor to compute its data on the document model.
    # in response to a data changed message, this object will update
    # the data and trigger a repaint.
    def data_item_binding_display_changed(self, display):
        self.__set_display(display)
        self.__histogram_canvas_item._set_display(display)
        statistics_data = display.data_item.get_processed_data("statistics") if display else dict()
        if display:
            document_model = self.document_controller.document_model
            document_model.dispatch_task(lambda: display.data_item.get_processor("statistics").recompute_data_limited(None), "statistics")
            document_model.dispatch_task(lambda: display.get_processor("histogram").recompute_data_limited(None), "histogram")
        self.__update_statistics(statistics_data)

    # notification from display
    def display_processor_needs_recompute(self, display, processor):
        document_model = self.document_controller.document_model
        if processor == self.__display.get_processor("histogram"):
            document_model.dispatch_task(lambda: processor.recompute_data_limited(None), "histogram")

    # notification from display
    def display_processor_data_updated(self, display, processor):
        if processor == self.__display.get_processor("histogram"):
            histogram_data = self.__display.get_processed_data("histogram")
            self.__histogram_canvas_item.histogram_data = histogram_data

    # notification from display
    def data_item_processor_needs_recompute(self, data_item, processor):
        document_model = self.document_controller.document_model
        if processor == self.__display.data_item.get_processor("statistics"):
            document_model.dispatch_task(lambda: processor.recompute_data_limited(None), "statistics")

    # notification from display
    def data_item_processor_data_updated(self, data_item, processor):
        if processor == self.__display.data_item.get_processor("statistics"):
            statistics_data = self.__display.data_item.get_processed_data("statistics")
            self.__update_statistics(statistics_data)
