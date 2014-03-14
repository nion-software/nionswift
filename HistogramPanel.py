# standard libraries
import gettext
import logging
import threading

# third party libraries
# None

# local libraries
from nion.swift import DataItem
from nion.swift import DocumentController
from nion.swift import Panel
from nion.ui import CanvasItem
from nion.ui import ThreadPool

_ = gettext.gettext


class AdornmentsCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(AdornmentsCanvasItem, self).__init__()
        self.display_limits = (0,1)

    def _repaint(self, drawing_context):

        # canvas size
        canvas_width = self.canvas_size[1]
        canvas_height = self.canvas_size[0]

        left = self.display_limits[0]
        right = self.display_limits[1]

        # draw left display limit
        drawing_context.save()
        drawing_context.begin_path()
        drawing_context.move_to(left * canvas_width, 1)
        drawing_context.line_to(left * canvas_width, canvas_height-1)
        drawing_context.line_width = 2
        drawing_context.stroke_style = "#000"
        drawing_context.stroke()
        drawing_context.restore()

        # draw right display limit
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
        drawing_context.move_to(0,0)
        drawing_context.line_to(canvas_width,0)
        drawing_context.line_to(canvas_width,canvas_height)
        drawing_context.line_to(0,canvas_height)
        drawing_context.close_path()
        drawing_context.line_width = 1
        drawing_context.stroke_style = "#000"
        drawing_context.stroke()
        drawing_context.restore()


class SimpleLineGraphCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(SimpleLineGraphCanvasItem, self).__init__()
        self.__data = None
        self.__background_color = None

    def __get_data(self):
        return self.__data
    def __set_data(self, data):
        self.__data = data
        self.update()
    data = property(__get_data, __set_data)

    def __get_background_color(self):
        return self.__background_color
    def __set_background_color(self, background_color):
        self.__background_color = background_color
        self.update()
    background_color = property(__get_background_color, __set_background_color)

    def _repaint(self, drawing_context):

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
            drawing_context.move_to(0, canvas_height)
            drawing_context.line_to(0, canvas_height * (1 - self.data[0]))
            for i in xrange(1,canvas_width,2):
                drawing_context.line_to(i, canvas_height * (1 - self.data[int(len(self.data)*float(i)/canvas_width)]))
            drawing_context.line_to(canvas_width, canvas_height)
            drawing_context.close_path()
            drawing_context.fill_style = "#888"
            drawing_context.fill()
            drawing_context.line_width = 1
            drawing_context.stroke_style = "#00F"
            drawing_context.stroke()
            drawing_context.restore()


class HistogramCanvasItem(CanvasItem.CanvasItemComposition):

    def __init__(self, data_item_binding):
        super(HistogramCanvasItem, self).__init__()
        self.data_item_binding = data_item_binding
        self.adornments_canvas_item = AdornmentsCanvasItem()
        self.simple_line_graph_canvas_item = SimpleLineGraphCanvasItem()
        # canvas items get added back to front
        self.add_canvas_item(self.simple_line_graph_canvas_item)
        self.add_canvas_item(self.adornments_canvas_item)
        self.__data_item = None
        self.__pressed = False

        # connect self as listener. this will result in calls to data_item_binding_data_item_changed
        # and data_item_binding_data_item_content_changed
        self.data_item_binding.add_listener(self)

        self.__shared_thread_pool = ThreadPool.create_thread_queue()

        self.preferred_aspect_ratio = 1.618  # golden ratio

        # initial data item changed message
        self.data_item_binding_data_item_changed(self.data_item_binding.data_item)

    def close(self):
        self.__shared_thread_pool.close()
        self.__shared_thread_pool = None
        # first set the data item to None
        self.data_item_binding_data_item_changed(None)
        # disconnect self as listener
        self.data_item_binding.remove_listener(self)
        super(HistogramCanvasItem, self).close()

    # pass this along to the simple line graph canvas item
    def __get_background_color(self):
        return self.simple_line_graph_canvas_item.background_color
    def __set_background_color(self, background_color):
        self.simple_line_graph_canvas_item.background_color = background_color
    background_color = property(__get_background_color, __set_background_color)

    # _get_data_item is only used for testing
    def _get_data_item(self):
        return self.__data_item
    def _set_data_item(self, data_item):
        # this will get invoked whenever the data item changes too. it gets invoked
        # from the histogram thread which gets triggered via the data_item_binding_data_item_changed
        # or data_item_binding_data_item_content_changed message from the data item binding.
        self.__data_item = data_item
        # if the user is currently dragging the display limits, we don't want to update
        # from changing data at the same time. but we _do_ want to draw the updated data.
        if not self.__pressed:
            self.adornments_canvas_item.display_limits = (0, 1)
        # this will get called twice: once with the initial return values
        # and once with the updated return values once the thread completes.
        def update_histogram_data(histogram_data):
            self.simple_line_graph_canvas_item.data = histogram_data
            self.adornments_canvas_item.update()
        histogram_data = self.__data_item.get_processor("histogram").get_data(completion_fn=update_histogram_data) if self.__data_item else None
        update_histogram_data(histogram_data)

    # this message is received from the data item binding.
    # it is established using add_listener
    # TODO: histogram gets updated unnecessarily when dragging graphic items
    def data_item_binding_data_item_changed(self, data_item):
        if self.__shared_thread_pool and data_item:
            def update_histogram_data_on_thread():
                self._set_data_item(data_item)
            self.__shared_thread_pool.add_task("update-histogram-data", data_item, lambda: update_histogram_data_on_thread())

    # this message is received from the data item binding.
    # it is established using add_listener
    def data_item_binding_data_item_content_changed(self, data_item, changes):
        self.data_item_binding_data_item_changed(data_item)

    def __set_display_limits(self, display_limits):
        self.adornments_canvas_item.display_limits = display_limits
        self.adornments_canvas_item.update()

    def mouse_double_clicked(self, x, y, modifiers):
        if super(HistogramCanvasItem, self).mouse_double_clicked(x, y, modifiers):
            return True
        self.__set_display_limits((0, 1))
        if self.__data_item:
            self.__data_item.display_limits = None
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
        display_limit_range = self.adornments_canvas_item.display_limits[1] - self.adornments_canvas_item.display_limits[0]
        if self.__data_item and (display_limit_range > 0) and (display_limit_range < 1):
            data_min, data_max = self.__data_item.display_range
            lower_display_limit = data_min + self.adornments_canvas_item.display_limits[0] * (data_max - data_min)
            upper_display_limit = data_min + self.adornments_canvas_item.display_limits[1] * (data_max - data_min)
            self.__data_item.display_limits = (lower_display_limit, upper_display_limit)
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

    def __init__(self, document_controller, panel_id, properties):
        super(HistogramPanel, self).__init__(document_controller, panel_id, _("Histogram"))
        self.root_canvas_item = CanvasItem.RootCanvasItem(document_controller.ui, properties)
        self.widget = self.root_canvas_item.canvas
        self.data_item_binding = document_controller.create_selected_data_item_binding()
        self.root_canvas_item.add_canvas_item(HistogramCanvasItem(self.data_item_binding))

    def close(self):
        self.root_canvas_item.close()
        self.data_item_binding.close()
        super(HistogramPanel, self).close()
