# standard libraries
import gettext
import logging

# third party libraries
import numpy

# local libraries
from nion.swift.Decorators import queue_main_thread
from nion.swift import Panel

_ = gettext.gettext


class HistogramPanel(Panel.Panel):

    delay_queue = property(lambda self: self.document_controller.delay_queue)

    def __init__(self, document_controller, panel_id):
        Panel.Panel.__init__(self, document_controller, panel_id, _("Histogram"))

        # load the Qml and associate it with this panel.
        self.widget = self.loadIntrinsicWidget("histogram")
        self.ui.Histogram_setDelegate(self.widget, self)

        # connect self as listener. this will result in calls to selected_data_item_changed
        self.document_controller.add_listener(self)

        self.data_item = None

        self.display_limits = (0,1)

    def close(self):
        # first set the data item to None
        self.selected_data_item_changed(None, {"property": "source"})
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # finish closing
        Panel.Panel.close(self)

    def mousePressEvent(self, x, y, w, h, raw_modifiers):
        self.start = float(x)/w
        self.display_limits = (self.start, self.start)
        self.ui.Histogram_setLeftRight(self.widget, self.start, self.start)

    def mouseMoveEvent(self, x, y, w, h, raw_modifiers):
        current = float(x)/w
        self.display_limits = (min(self.start, current), max(self.start, current))
        self.ui.Histogram_setLeftRight(self.widget, self.display_limits[0], self.display_limits[1])

    def mouseReleaseEvent(self, x, y, w, h, raw_modifiers):
        if self.data_item and (self.display_limits[1] - self.display_limits[0] > 0):
            self.data_item.display_limits = self.display_limits

    def mouseDoubleClickEvent(self, x, y, w, h, raw_modifiers):
        self.display_limits = (0, 1)
        self.ui.Histogram_setLeftRight(self.widget, self.display_limits[0], self.display_limits[1])

    # used for queue_main_thread decorator
    @queue_main_thread
    def __update_histogram(self, data, display_limits):
        if self.widget:
            self.ui.Histogram_setData(self.widget, data)
            self.ui.Histogram_setLeftRight(self.widget, display_limits[0], display_limits[1])

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_data_item_changed(self, data_item, info):
        self.data_item = data_item
        if self.data_item:
            image = self.data_item.image
            if image is not None:
                histogram_data = numpy.histogram(image, bins=256)
                histogram_data = histogram_data[0]
                histogram_max = float(numpy.max(histogram_data))
                histogram_data = histogram_data / histogram_max
                self.__update_histogram(histogram_data.astype(numpy.float32), self.display_limits)
                return
        self.__update_histogram([], (0,1))
