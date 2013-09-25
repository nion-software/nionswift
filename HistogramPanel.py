# standard libraries
import gettext
import logging
import threading
import time

# third party libraries
import numpy

# local libraries
from nion.swift.Decorators import ProcessingThread
from nion.swift.Decorators import relative_file
from nion.swift.Decorators import queue_main_thread_sync
from nion.swift import Panel
from nion.swift import UserInterface

_ = gettext.gettext


class HistogramThread(ProcessingThread):

    def __init__(self, histogram_panel):
        super(HistogramThread, self).__init__()
        self.__histogram_panel = histogram_panel
        self.__data_item = None
        # don't start until everything is initialized
        self.start()

    def close(self):
        if self.__data_item:
            self.__data_item.remove_ref()
        super(HistogramThread, self).close()

    def handle_data(self, data_item):
        if self.__data_item:
            self.__data_item.remove_ref()
        self.__data_item = data_item
        if data_item:
            data_item.add_ref()

    def grab_data(self):
        data_item = self.__data_item
        self.__data_item = None
        return data_item

    def process_data(self, data_item):
        self.__histogram_panel.data_item = data_item

    def release_data(self, data_item):
        data_item.remove_ref()


class HistogramPanel(Panel.Panel):

    delay_queue = property(lambda self: self.document_controller.delay_queue)

    def __init__(self, document_controller, panel_id):
        super(HistogramPanel, self).__init__(document_controller, panel_id, _("Histogram"))

        ui = document_controller.ui

        self.canvas = ui.create_canvas_widget(document_controller)

        self.canvas.on_size_changed = lambda width, height: self.on_size_changed(width, height)
        self.canvas.on_mouse_double_clicked = lambda x, y, modifiers: self.on_mouse_double_clicked(x, y, modifiers)
        self.canvas.on_mouse_pressed = lambda x, y, modifiers: self.on_mouse_pressed(x, y, modifiers)
        self.canvas.on_mouse_released = lambda x, y, modifiers: self.on_mouse_released(x, y, modifiers)
        self.canvas.on_mouse_position_changed = lambda x, y, modifiers: self.on_mouse_position_changed(x, y, modifiers)

        self.widget = self.canvas.widget

        # connect self as listener. this will result in calls to selected_data_item_changed
        self.document_controller.add_listener(self)

        self.__data_item = None

        self.__display_limits = (0,1)

        self.pressed = False

        self.__histogram_data = None

        self.__histogram_layer = self.canvas.create_layer()
        self.__adornments_layer = self.canvas.create_layer()

        self.__histogram_dirty = True
        self.__adornments_dirty = True

        self.__update_lock = threading.Lock()

        self.__histogram_thread = HistogramThread(self)

    def close(self):
        self.__histogram_thread.close()
        self.__histogram_thread = None
        # first set the data item to None
        self.selected_data_item_changed(None, {"property": "source"})
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # finish closing
        super(HistogramPanel, self).close()

    def __get_display_limits(self):
        return self.__display_limits
    def __set_display_limits(self, display_limits):
        self.__display_limits = display_limits
        self.__adornments_dirty = True
        self.__update_histogram()
    display_limits = property(__get_display_limits, __set_display_limits)

    def on_size_changed(self, width, height):
        if width > 0 and height > 0:
            self.__histogram_dirty = True
            self.__update_histogram()

    def on_mouse_double_clicked(self, x, y, modifiers):
        self.display_limits = (0, 1)

    def on_mouse_pressed(self, x, y, modifiers):
        self.pressed = True
        self.start = float(x)/self.canvas.width
        self.display_limits = (self.start, self.start)

    def on_mouse_released(self, x, y, modifiers):
        self.pressed = False
        if self.data_item and (self.display_limits[1] - self.display_limits[0] > 0):
            self.data_item.display_limits = self.display_limits

    def on_mouse_position_changed(self, x, y, modifiers):
        canvas_width = self.canvas.width
        canvas_height = self.canvas.height
        if self.pressed:
            current = float(x)/canvas_width
            self.display_limits = (min(self.start, current), max(self.start, current))

    # make the histogram from the data item.
    # at the end of this method, both histogram_data and histogram_js will be valid, although data may be None.
    # histogram_js will never be None after this method is called as long as the widget is valid.
    def __make_histogram(self):

        if self.__histogram_data is None:
            if self.data_item:
                image = self.data_item.image
                if image is not None:
                    histogram_data = numpy.histogram(image, bins=256)
                    histogram_data = histogram_data[0]
                    histogram_max = float(numpy.max(histogram_data))
                    self.__histogram_data = histogram_data / histogram_max

        # testing the decoupling of the data item change vs. histogram calculation
        # time.sleep(1.0)

        data = self.__histogram_data

        if self.__histogram_dirty and (data is not None and len(data) > 0):

            self.__histogram_dirty = False

            canvas_width = self.canvas.width
            canvas_height = self.canvas.height

            ctx = self.__histogram_layer.drawing_context

            ctx.clear()
            
            # draw the histogram itself
            ctx.save()
            ctx.beginPath()
            ctx.moveTo(0, canvas_height)
            ctx.lineTo(0, canvas_height * (1 - data[0]))
            for i in xrange(1,canvas_width,2):
                ctx.lineTo(i, canvas_height * (1 - data[int(len(data)*float(i)/canvas_width)]))
            ctx.lineTo(canvas_width, canvas_height)
            ctx.closePath()
            ctx.fillStyle = "#888"
            ctx.fill()
            ctx.lineWidth = 1
            ctx.strokeStyle = "#00F"
            ctx.stroke()
            ctx.restore()

    def __make_adornments(self):

        if self.widget and self.__adornments_dirty:

            self.__adornments_dirty = False

            canvas_width = self.canvas.width
            canvas_height = self.canvas.height

            ctx = self.__adornments_layer.drawing_context

            ctx.clear()

            left = self.display_limits[0]
            right = self.display_limits[1]

            # draw left display limit
            ctx.save()
            ctx.beginPath()
            ctx.moveTo(left * canvas_width, 0)
            ctx.lineTo(left * canvas_width, canvas_height)
            ctx.closePath()
            ctx.lineWidth = 2
            ctx.strokeStyle = "#000"
            ctx.stroke()
            ctx.restore()

            # draw right display limit
            ctx.save()
            ctx.beginPath()
            ctx.moveTo(right * canvas_width, 0)
            ctx.lineTo(right * canvas_width, canvas_height)
            ctx.closePath()
            ctx.lineWidth = 2
            ctx.strokeStyle = "#FFF"
            ctx.stroke()
            ctx.restore()

            # draw border
            ctx.save()
            ctx.beginPath()
            ctx.moveTo(0,0)
            ctx.lineTo(canvas_width,0)
            ctx.lineTo(canvas_width,canvas_height)
            ctx.lineTo(0,canvas_height)
            ctx.closePath()
            ctx.lineWidth = 1
            ctx.strokeStyle = "#000"
            ctx.stroke()
            ctx.restore()

    # used for queue_main_thread decorator
    delay_queue = property(lambda self: self.document_controller.delay_queue)

    def __update_canvas(self):
        if self.ui and self.widget:
            self.canvas.draw()

    def __update_histogram(self):
        if self.ui and self.widget:
            with self.__update_lock:
                self.__make_histogram()
                self.__make_adornments()
                self.__update_canvas()

    def __get_data_item(self):
        return self.__data_item
    def __set_data_item(self, data_item):
        self.__data_item = data_item
        self.__histogram_data = None
        self.__histogram_dirty = True
        self.__update_histogram()
    data_item = property(__get_data_item, __set_data_item)

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_data_item_changed(self, data_item, info):
        if self.__histogram_thread:
            self.__histogram_thread.update_data(data_item)
