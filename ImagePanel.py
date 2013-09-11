# standard libraries
import gettext
import logging
import numbers
import random
import threading
import uuid
import weakref

# third party libraries
import numpy

# local libraries
import DataItem
import DataPanel
from Decorators import relative_file
from Decorators import queue_main_thread
import DocumentController  # temp
import Graphics
import Image
import Operation
import Panel
import Storage
import UserInterface

_ = gettext.gettext


# coordinate systems:
#   widget (origin top left, size of the widget)
#   mouse (origin where it goes, size of the qml image item)
#   image_norm ((0,0), (1,1))
#   image_pixel (0,0 size of the image in pixels)
#   calibrated


# special note: maps mouse on the way in; widget on the way out
class WidgetMapping(object):
    def __init__(self, image_panel):
        self.image_panel = image_panel
    def map_point_graphic_to_container(self, p):
        return self.image_panel.map_image_norm_to_widget(p)
    def map_size_graphic_to_container(self, s):
        ms = self.map_point_graphic_to_container(s)
        ms0 = self.map_point_graphic_to_container((0,0))
        return (ms[0] - ms0[0], ms[1] - ms0[1])
    def map_point_container_to_graphic(self, p):
        return self.image_panel.map_mouse_to_image_norm(p)


class GraphicSelection(object):
    def __init__(self):
        self.__weak_listeners = []
        self.__indexes = set()
    # implement listener architecture
    def _notify_listeners(self):
        for weak_listener in self.__weak_listeners:
            listener = weak_listener()
            listener.selection_changed(self)
    def add_listener(self, listener):
        self.__weak_listeners.append(weakref.ref(listener))
    def remove_listener(self, listener):
        self.__weak_listeners.remove(weakref.ref(listener))
    # manage selection
    def __get_current_index(self):
        if len(self.__indexes) == 1:
            for index in self.__indexes:
                return index
        return None
    current_index = property(__get_current_index)
    def has_selection(self):
        return len(self.__indexes) > 0
    def contains(self, index):
        return index in self.__indexes
    def __get_indexes(self):
        return self.__indexes
    indexes = property(__get_indexes)
    def clear(self):
        old_index = self.__indexes.copy()
        self.__indexes = set()
        if old_index != self.__indexes:
            self._notify_listeners()
    def add(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes.add(index)
        if old_index != self.__indexes:
            self._notify_listeners()
    def remove(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes.remove(index)
        if old_index != self.__indexes:
            self._notify_listeners()
    def set(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes = set()
        self.__indexes.add(index)
        if old_index != self.__indexes:
            self._notify_listeners()
    def toggle(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        if index in self.__indexes:
            self._indexes.remove(index)
        else:
            self._indexes.add(index)
        if old_index != self.__indexes:
            self._notify_listeners()


class ImagePanel(Panel.Panel):

    def __init__(self, document_controller, panel_id):
        super(ImagePanel, self).__init__(document_controller, panel_id, _("Image Panel"))

        self.graphic_drag_items = []
        self.graphic_drag_item = None
        self.graphic_part_data = {}
        self.graphic_drag_indexes = []

        self.graphic_selection = GraphicSelection()
        self.graphic_selection.add_listener(self)

        self.last_mouse = None

        self.__data_panel_selection = DataPanel.DataItemSpecifier()

        self.__weak_listeners = []

        self.__mouse_in = False

        self.view = None  # some bootstrapping magic in case view is used before assigned

        self.view = self.ui.create_image_view(self)

        self.widget = self.view.widget  # panel needs this to be dockable

        self.document_controller.register_image_panel(self)

        self.closed = False

    def close(self):
        self.closed = True
        self.document_controller.unregister_image_panel(self)
        self.graphic_selection.remove_listener(self)
        self.graphic_selection = None
        self.data_panel_selection = DataPanel.DataItemSpecifier()  # required before destructing display thread
        self.view.close()
        self.view = None
        super(ImagePanel, self).close()

    def set_focused(self, focused):
        self.view.set_focused(focused)

    def update_graphics(self):
        data_item = self.data_item
        graphics = data_item.graphics if data_item else None
        if not self.closed and self.view:
            self.view.draw_graphics(self.image_size, graphics, self.graphic_selection, WidgetMapping(self))

    def update_underlay(self):
        if self.view:
            ctx = UserInterface.DrawingContext()
            ctx.save()

            if self.data_item:
                data = Image.scalarFromArray(self.data_item.data)  # make sure complex becomes scalar
                if Image.is_data_1d(data):
                    if Image.is_data_rgb(data) or Image.is_data_rgba(data):
                        # note 0=b, 1=g, 2=r, 3=a. calculate luminosity.
                        data = 0.0722 * data[:,0] + 0.7152 * data[:,1] + 0.2126 * data[:,2]
                    rect = self.view.rect
                    data_min = numpy.amin(data)
                    data_max = numpy.amax(data)
                    data_len = data.shape[0]
                    display_width = int(rect[1][1])
                    display_height = int(rect[1][0])
                    for i in range(0,display_width):
                        ctx.beginPath()
                        ctx.moveTo(i, display_height)
                        ctx.lineTo(i, display_height - (display_height * (float(data[data_len*float(i)/display_width]) - data_min) / (data_max - data_min)))
                        ctx.closePath()
                        ctx.lineWidth = 1
                        ctx.strokeStyle = '#00FF00'
                        ctx.stroke()

            ctx.restore()
            self.view.set_underlay_script(ctx.js)


    # message comes from the view
    def resized(self, rect):
        self.update_underlay()
        self.update_graphics()

    def display_changed(self):
        self.update_graphics()

    def selection_changed(self, graphic_selection):
        self.update_graphics()

    def __get_data_item(self):
        return self.__data_panel_selection.data_item
    data_item = property(__get_data_item)

    def __get_data_item_container(self):
        return self.__data_panel_selection.data_item_container
    data_item_container = property(__get_data_item_container)

    def __get_data_panel_selection(self):
        return self.__data_panel_selection
    def __set_data_panel_selection(self, data_panel_selection):
        assert data_panel_selection is not None
        # assert that either data_group is not None or both are None. it is acceptable
        # to not have a data_item, but not acceptable to have a data_item without a container
        assert data_panel_selection.data_group is not None or data_panel_selection.data_item is None
        assert isinstance(data_panel_selection, DataPanel.DataItemSpecifier)
        # track data item in this class to report changes
        if self.data_item_container:
            self.data_item_container.remove_listener(self)
            self.data_item_container.remove_ref()
        if self.data_item:
            self.data_item.remove_listener(self)
            self.data_item.remove_ref()
        self.__data_panel_selection = data_panel_selection
        data_item = self.data_item
        data_item_container = self.data_item_container
        if data_item:
            data_item.add_ref()
            data_item.add_listener(self)
        if data_item_container:
            data_item_container.add_ref()
            data_item_container.add_listener(self)
        for weak_listener in self.__weak_listeners:
            listener = weak_listener()
            listener.data_panel_selection_changed_from_image_panel(data_panel_selection)
        self.data_item_changed(self.data_item, {"property": "source"})
        # tell the view about the new data item
        # this should be called just once so that the display thread
        # doesn't flash
        self.view.data_item = self.data_item
    data_panel_selection = property(__get_data_panel_selection, __set_data_panel_selection)

    def data_item_removed(self, container, data_item, index):
        # if our item gets deleted, clear the selection
        if container == self.data_item_container and data_item == self.data_item:
            self.data_panel_selection = DataPanel.DataItemSpecifier(self.__data_panel_selection.data_group)

    # tell our listeners the we changed.
    def notify_image_panel_data_item_changed(self, info):
        for weak_listener in self.__weak_listeners:
            listener = weak_listener()
            listener.image_panel_data_item_changed(self, info)

    # this will result in data_item_changed being called when the data item changes.
    def add_listener(self, listener):
        self.__weak_listeners.append(weakref.ref(listener))

    def remove_listener(self, listener):
        self.__weak_listeners.remove(weakref.ref(listener))

    # this message comes from the data item associated with this panel.
    # the connection is established in __set_data_item via data_item.add_listener.
    def data_item_changed(self, data_item, info):
        self.notify_image_panel_data_item_changed(info)
        self.update_cursor_info()
        self.update_underlay()
        self.update_graphics()

    def mouse_clicked(self, p, modifiers):
        # activate this view
        self.document_controller.selected_image_panel = self

    def mouse_pressed(self, p, modifiers):
        # figure out clicked graphic
        self.graphic_drag_items = []
        self.graphic_drag_item = None
        self.graphic_part_data = {}
        self.graphic_drag_indexes = []
        if self.data_item:
            for graphic_index, graphic in enumerate(self.data_item.graphics):
                # de-transform mouse coords
                start_drag_pos = self.map_mouse_to_widget(p)
                already_selected = self.graphic_selection.contains(graphic_index)
                multiple_items_selected = len(self.graphic_selection.indexes) > 1
                move_only = not already_selected or multiple_items_selected
                part = graphic.test(WidgetMapping(self), start_drag_pos, move_only)
                if part:
                    # if shift is down and item is already selected, toggle selection of item
                    if modifiers.shift and self.graphic_selection.contains(graphic_index):
                        self.graphic_selection.remove(graphic_index)
                    # otherwise, select it and prepare for drag
                    else:
                        if modifiers.shift:
                            self.graphic_selection.add(graphic_index)
                        elif not already_selected:
                            self.graphic_selection.set(graphic_index)
                        # keep track of general drag information
                        self.graphic_drag_start_pos = start_drag_pos
                        self.graphic_drag_changed = False
                        # keep track of info for the specific item that was clicked
                        self.graphic_drag_item = self.data_item.graphics[graphic_index]
                        self.graphic_drag_part = part
                        # keep track of drag information for each item in the set
                        self.graphic_drag_indexes = self.graphic_selection.indexes
                        for index in self.graphic_drag_indexes:
                            graphic = self.data_item.graphics[index]
                            self.graphic_drag_items.append(graphic)
                            self.graphic_part_data[index] = graphic.begin_drag()
                    break
        if not self.graphic_drag_items and not modifiers.shift:
            self.graphic_selection.clear()

    def mouse_released(self, p, modifiers):
        for index in self.graphic_drag_indexes:
            graphic = self.data_item.graphics[index]
            graphic.end_drag(self.graphic_part_data[index])
        if self.graphic_drag_items and not self.graphic_drag_changed and not modifiers.shift:
            assert self.data_item
            self.graphic_selection.set(self.data_item.graphics.index(self.graphic_drag_item))
        self.graphic_drag_items = []
        self.graphic_drag_item = None
        self.graphic_part_data = {}
        self.graphic_drag_indexes = []

    def mouse_entered(self):
        self.__mouse_in = True

    def mouse_exited(self):
        self.__mouse_in = False
        self.mouse_position_changed((0, 0), 0)

    def mouse_position_changed(self, p, modifiers):
        # x,y already have transform applied
        self.last_mouse = p
        self.update_cursor_info()
        if self.graphic_drag_items:
            for graphic in self.graphic_drag_items:
                index = self.data_item.graphics.index(graphic)
                part_data = (self.graphic_drag_part, ) + self.graphic_part_data[index]
                graphic.adjust_part(WidgetMapping(self), self.graphic_drag_start_pos, p, part_data, modifiers)
                self.graphic_drag_changed = True
                self.update_graphics()

    def update_cursor_info(self):
        pos = None
        image_size = self.image_size
        if self.__mouse_in and self.last_mouse:
            if image_size and len(image_size) > 1:
                pos = self.map_mouse_to_image(self.last_mouse)
            data_item = self.data_item
            graphics = data_item.graphics if data_item else None
            selected_graphics = [graphics[index] for index in self.graphic_selection.indexes] if graphics else []
            self.document_controller.notify_listeners("cursor_changed", self.data_item, pos, selected_graphics, image_size)

    def __get_image_size(self):
        data_item = self.data_item
        image = data_item.image if data_item else None
        shape = image.shape if image is not None else (0,0)
        for d in shape:
            if not d > 0:
                return None
        return shape
    image_size = property(__get_image_size)

    # map from image coordinates to widget coordinates
    def map_image_to_widget(self, p):
        image_size = self.image_size
        if image_size:
            return self.map_image_norm_to_widget((float(p[0])/image_size[0], float(p[1])/image_size[1]))
        return None

    # map from image normalized coordinates to widget coordinates
    def map_image_norm_to_widget(self, p):
        return self.view.map_image_norm_to_widget(self.image_size, p)

    # map from widget coordinates to image coordinates
    def map_mouse_to_image(self, p):
        return self.view.map_mouse_to_image(self.image_size, p)

    # map from widget coordinates to image normalized coordinates
    def map_mouse_to_image_norm(self, p):
        image_size = self.image_size
        if image_size:
            p_image = self.map_mouse_to_image(p)
            return (float(p_image[0]) / image_size[0], float(p_image[1]) / image_size[1])
        return None

    def map_mouse_to_widget(self, p):
        return self.map_image_to_widget(self.map_mouse_to_image(p))

    # ths message comes fro Qml
    def key_pressed(self, text, key, modifiers):
        #logging.debug("text=%s key=%s mod=%s", text, hex(key), modifiers)
        if key == 0x1000012:  # left arrow
            zoom = self.getWidgetProperty("zoom") * (10.0 if modifiers.shift else 1.0)
            self.setWidgetProperty("translateX", self.getWidgetProperty("translateX") - zoom)
            self.update_graphics()
        if key == 0x1000014:  # right arrow
            zoom = self.getWidgetProperty("zoom") * (10.0 if modifiers.shift else 1.0)
            self.setWidgetProperty("translateX", self.getWidgetProperty("translateX") + zoom)
        if key == 0x1000013:  # up arrow
            zoom = self.getWidgetProperty("zoom") * (10.0 if modifiers.shift else 1.0)
            self.setWidgetProperty("translateY", self.getWidgetProperty("translateY") - zoom)
        if key == 0x1000015:  # down arrow
            zoom = self.getWidgetProperty("zoom") * (10.0 if modifiers.shift else 1.0)
            self.setWidgetProperty("translateY", self.getWidgetProperty("translateY") + zoom)
        if text == "-":
            zoom = self.getWidgetProperty("zoom")
            self.setWidgetProperty("zoom", zoom / 1.05)
        if text == "+":
            zoom = self.getWidgetProperty("zoom")
            self.setWidgetProperty("zoom", zoom * 1.05)
        if text == "0":
            self.setWidgetProperty("zoom", 1.0)
            self.setWidgetProperty("translateX", 0.0)
            self.setWidgetProperty("translateY", 0.0)
        return False


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


class InfoPanel(Panel.Panel):

    delay_queue = property(lambda self: self.document_controller.delay_queue)

    def __init__(self, document_controller, panel_id):
        Panel.Panel.__init__(self, document_controller, panel_id, _("Info"))

        # load the Qml and associate it with this panel.
        context_properties = {
            "position_text": "",
            "value_text": "",
            "graphic_text": ""
        }
        qml_filename = relative_file(__file__, "InfoView.qml")
        self.widget = self.ui.DocumentWindow_loadQmlWidget(self.document_controller.document_window, qml_filename, self, context_properties)

        # connect self as listener. this will result in calls to selected_data_item_changed and cursor_changed
        self.document_controller.add_listener(self)

    def close(self):
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # finish closing
        Panel.Panel.close(self)

    # this message is received from the document controller.
    # it is established using add_listener
    @queue_main_thread
    def cursor_changed(self, data_item, pos, selected_graphics, image_size):
        position_text = ""
        value_text = ""
        graphic_text = ""
        if data_item:
            calibrations = data_item.calculated_calibrations
            if pos:
                # make sure the position is within the bounds of the image
                if pos[0] >= 0 and pos[0] < image_size[0] and pos[1] >= 0 and pos[1] < image_size[1]:
                    position_text = '{0},{1}'.format(calibrations[1].convert_to_calibrated_str(pos[1] - 0.5 * image_size[1]),
                                                     calibrations[0].convert_to_calibrated_str(0.5 * image_size[0] - pos[0]))
                    value = data_item.image[pos[0], pos[1]]
                    if isinstance(value, numbers.Integral):
                        value_text = '{0:d}'.format(value)
                    elif isinstance(value, numbers.Real) or isinstance(value, numbers.Complex):
                        value_text = '{0:f}'.format(value)
                    else:
                        value_text = str(value)
            if len(selected_graphics) == 1:
                graphic = selected_graphics[0]
                graphic_text = graphic.calibrated_description(image_size, calibrations)
        self.ui.Widget_setContextProperty(self.widget, "position_text", position_text)
        self.ui.Widget_setContextProperty(self.widget, "value_text", value_text)
        self.ui.Widget_setContextProperty(self.widget, "graphic_text", graphic_text)


class InspectorPanel(Panel.Panel):
    def __init__(self, document_controller, panel_id):
        Panel.Panel.__init__(self, document_controller, panel_id, _("Inspector"))

        self.widget = self.loadIntrinsicWidget("column")

        self.__data_item = None
        self.__pec = None

        self.data_item = None

        # connect self as listener. this will result in calls to selected_data_item_changed
        self.document_controller.add_listener(self)

    def close(self):
        # close the property controller
        self.data_item = None
        # first set the data item to None
        self.selected_data_item_changed(None, {"property": "source"})
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # finish closing
        Panel.Panel.close(self)

    delay_queue = property(lambda self: self.document_controller.delay_queue)
    @queue_main_thread
    def __update_property_editor_controller(self):
        if self.__pec:
            self.__pec.close()
            self.__pec = None
        if self.__data_item:
            self.__pec = DocumentController.PropertyEditorController(self.ui, self.__data_item, self.widget)

    def __get_data_item(self):
        return self.__data_item
    def __set_data_item(self, data_item):
        if self.__data_item != data_item:
            self.__data_item = data_item
            self.__update_property_editor_controller()
    data_item = property(__get_data_item, __set_data_item)

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_data_item_changed(self, data_item, info):
        if self.data_item != data_item:
            self.data_item = data_item
