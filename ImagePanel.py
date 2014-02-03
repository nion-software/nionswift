# standard libraries
import gettext
import logging
import math
import numbers
import random
import threading
import time
import uuid
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import DataGroup
from nion.swift import DataItem
from nion.swift.Decorators import ProcessingThread
from nion.swift import Decorators
from nion.swift import HistogramPanel
from nion.swift import Image
from nion.swift import Inspector
from nion.swift import LineGraphCanvasItem
from nion.swift import Operation
from nion.swift import Panel
from nion.ui import CanvasItem
from nion.ui import Geometry
from nion.ui import Observable

_ = gettext.gettext


# coordinate systems:
#   widget (origin top left, size of the widget)
#   image_norm ((0,0), (1,1))
#   image_pixel (0,0 size of the image in pixels)
#   calibrated


# how sizing works:
#   the canvas is initially set to fit to the space, meaning all of it is visible
#   when the user presses the fit, fill, or 1:1 buttons, the canvas is resized to match that choice
#   when the window is resized, a best attempt is made to keep the view roughly the same. this may
#     be impossible when the shape of the view changes radically.
#   when the user zooms in/out, the canvas is made larger or smaller by the appropriate amount.

# how to make sure it works:
#   if the new view default is 'fill' or '1:1', do the scroll bars come up in the center?
#   for new view, does zoom go into the center point?
#   switch to 'fit', does zoom still go into center point?


# refer to Illustrator / Default keyboard shortcuts
# http://help.adobe.com/en_US/illustrator/cs/using/WS714a382cdf7d304e7e07d0100196cbc5f-6426a.html
# secondary Lightroom:
# http://helpx.adobe.com/lightroom/help/keyboard-shortcuts.html

# KEYS FOR CHOOSING TOOLS               ACTION/KEY
# selection tool (whole object)         v
# direct selection tool (parts)         a
# line tool                             \
# rectangle tool                        m
# ellipse tool                          l
# rotate tool                           r
# scale tool                            s
# hand tool (moving image)              h
# zoom tool (zooming image)             z

# KEYS FOR VIEWING IMAGES               ACTION/KEY
# fit image to area                     double w/ hand tool
# magnify to 100%                       double w/ zoom tool
# fit image to area                     0
# fill image to area                    Shift-0
# make image 1:1                        1
# display original image                o

# KEYS FOR DRAWING GRAPHICS             ACTION/KEY
# constrain shape                       shift-drag
# move while draging                    spacebar-drag
# drag from center                      alt-drag (Windows), option-drag (Mac OS)

# KEYS FOR SELECTING GRAPHICS           ACTION/KEY
# use last used selection tool          ctrl (Windows), command (Mac OS)
# add/subtract from selection           alt (Windows), option (Mac OS)

# KEYS FOR MOVING SELECTION/IMAGE       ACTION/KEY
# move in small increments              arrow keys
# move in 10x increments                shift- arrow keys

# KEYS FOR USING PANELS                 ACTION/KEY
# hide all panels                       tab
# hide all panels except data panel     shift-tab

# FUNCTION KEYS                         ACTION/KEY
# tbd


class WidgetMapping(object):

    def __init__(self, data_shape, canvas_origin, canvas_size):
        self.data_shape = data_shape
        # double check dimensions are not zero
        if self.data_shape:
            for d in self.data_shape:
                if not d > 0:
                    self.data_shape = None
        # calculate transformed image rect
        self.canvas_rect = None
        if self.data_shape:
            rect = (canvas_origin, canvas_size)
            self.canvas_rect = Geometry.fit_to_size(rect, self.data_shape)

    def map_point_image_norm_to_widget(self, p):
        if self.data_shape:
            return (float(p[0])*self.canvas_rect[1][0] + self.canvas_rect[0][0], float(p[1])*self.canvas_rect[1][1] + self.canvas_rect[0][1])
        return None

    def map_size_image_norm_to_widget(self, s):
        ms = self.map_point_image_norm_to_widget(s)
        ms0 = self.map_point_image_norm_to_widget((0,0))
        return (ms[0] - ms0[0], ms[1] - ms0[1])

    def map_size_image_to_image_norm(self, s):
        ms = self.map_point_image_to_image_norm(s)
        ms0 = self.map_point_image_to_image_norm((0,0))
        return (ms[0] - ms0[0], ms[1] - ms0[1])

    def map_size_widget_to_image_norm(self, s):
        ms = self.map_point_widget_to_image_norm(s)
        ms0 = self.map_point_widget_to_image_norm((0,0))
        return (ms[0] - ms0[0], ms[1] - ms0[1])

    def map_point_widget_to_image_norm(self, p):
        if self.data_shape:
            p_image = self.map_point_widget_to_image(p)
            return (float(p_image[0]) / self.data_shape[0], float(p_image[1]) / self.data_shape[1])
        return None

    def map_point_widget_to_image(self, p):
        if self.canvas_rect and self.data_shape:
            if self.canvas_rect[1][0] != 0.0:
                image_y = self.data_shape[0] * (float(p[0]) - self.canvas_rect[0][0])/self.canvas_rect[1][0]
            else:
                image_y = 0
            if self.canvas_rect[1][1] != 0.0:
                image_x = self.data_shape[1] * (float(p[1]) - self.canvas_rect[0][1])/self.canvas_rect[1][1]
            else:
                image_x = 0
            return (image_y, image_x) # c-indexing
        return None

    def map_point_image_norm_to_image(self, p):
        if self.data_shape:
            return (float(p[0]) * self.data_shape[0], float(p[1]) * self.data_shape[1])
        return None

    def map_point_image_to_image_norm(self, p):
        if self.data_shape:
            return (float(p[0]) / self.data_shape[0], float(p[1]) / self.data_shape[1])
        return None


class GraphicSelection(Observable.Broadcaster):
    def __init__(self):
        super(GraphicSelection, self).__init__()
        self.__indexes = set()
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
            self.notify_listeners("selection_changed", self)
    def add(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes.add(index)
        if old_index != self.__indexes:
            self.notify_listeners("selection_changed", self)
    def remove(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes.remove(index)
        if old_index != self.__indexes:
            self.notify_listeners("selection_changed", self)
    def set(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes = set()
        self.__indexes.add(index)
        if old_index != self.__indexes:
            self.notify_listeners("selection_changed", self)
    def toggle(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        if index in self.__indexes:
            self._indexes.remove(index)
        else:
            self._indexes.add(index)
        if old_index != self.__indexes:
            self.notify_listeners("selection_changed", self)
    def insert_index(self, new_index):
        new_indexes = set()
        for index in self.__indexes:
            if index < new_index:
                new_indexes.add(index)
            else:
                new_indexes.add(index+1)
        if self.__indexes != new_indexes:
            self.__indexes = new_indexes
            self.notify_listeners("selection_changed", self)
    def remove_index(self, remove_index):
        new_indexes = set()
        for index in self.__indexes:
            if index != remove_index:
                if index > remove_index:
                    new_indexes.add(index-1)
                else:
                    new_indexes.add(index)
        if self.__indexes != new_indexes:
            self.__indexes = new_indexes
            self.notify_listeners("selection_changed", self)


class DataItemThread(ProcessingThread):

    def __init__(self, on_process_data, minimum_interval):
        super(DataItemThread, self).__init__(minimum_interval)
        self.__data_item = None
        self.__on_process_data = on_process_data
        self.__mutex = threading.RLock()  # access to the data item
        # mutex is needed to avoid case where grab data is called
        # simultaneously to handle_data and data item would get
        # released twice, once in handle data and once in the final
        # call to release data.
        # don't start until everything is initialized
        self.start()

    def close(self):
        super(DataItemThread, self).close()
        # protect against handle_data being called, but the data
        # was never grabbed. this must go _after_ the super.close
        with self.__mutex:
            if self.__data_item:
                self.__data_item.remove_ref()

    def handle_data(self, data_item):
        with self.__mutex:
            if self.__data_item:
                self.__data_item.remove_ref()
            self.__data_item = data_item
        if data_item:
            data_item.add_ref()

    def grab_data(self):
        with self.__mutex:
            data_item = self.__data_item
            self.__data_item = None
            return data_item

    def process_data(self, data_item):
        assert data_item is not None
        self.__on_process_data(data_item)

    def release_data(self, data_item):
        assert data_item is not None
        data_item.remove_ref()


class GraphicsCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(GraphicsCanvasItem, self).__init__()
        self.data_item = None

    def _repaint(self, drawing_context):

        if self.data_item:

            widget_mapping = WidgetMapping(self.data_item.spatial_shape, (0, 0), self.canvas_size)

            drawing_context.save()
            for graphic_index, graphic in enumerate(self.data_item.graphics):
                graphic.draw(drawing_context, widget_mapping, self.graphic_selection.contains(graphic_index))
            drawing_context.restore()


class InfoOverlayCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(InfoOverlayCanvasItem, self).__init__()
        self.data_item = None
        self.__image_canvas_size = None  # this will be updated by the container
        self.__image_canvas_origin = None  # this will be updated by the container

    def __get_image_canvas_size(self):
        return self.__image_canvas_size
    def __set_image_canvas_size(self, image_canvas_size):
        self.__image_canvas_size = image_canvas_size
        self.update()
        self.repaint_if_needed()
    image_canvas_size = property(__get_image_canvas_size, __set_image_canvas_size)

    def __get_image_canvas_origin(self):
        return self.__image_canvas_origin
    def __set_image_canvas_origin(self, image_canvas_origin):
        self.__image_canvas_origin = image_canvas_origin
        self.update()
        self.repaint_if_needed()
    image_canvas_origin = property(__get_image_canvas_origin, __set_image_canvas_origin)

    def _repaint(self, drawing_context):

        if self.data_item:

            # canvas size
            canvas_width = self.canvas_size[1]
            canvas_height = self.canvas_size[0]

            drawing_context.save()
            drawing_context.begin_path()

            image_canvas_size = self.image_canvas_size
            image_canvas_origin = self.image_canvas_origin
            if self.data_item.is_calibrated and image_canvas_origin is not None and image_canvas_size is not None:  # display scale marker?
                calibrations = self.data_item.calculated_calibrations
                origin = (canvas_height - 30, 20)
                scale_marker_width = 120
                scale_marker_height = 6
                widget_mapping = WidgetMapping(self.data_item.spatial_shape, image_canvas_origin, image_canvas_size)
                screen_pixel_per_image_pixel = widget_mapping.map_size_image_norm_to_widget((1, 1))[0] / self.data_item.spatial_shape[0]
                if screen_pixel_per_image_pixel > 0:
                    scale_marker_image_width = scale_marker_width / screen_pixel_per_image_pixel
                    calibrated_scale_marker_width = Geometry.make_pretty(scale_marker_image_width * calibrations[0].scale)
                    # update the scale marker width
                    scale_marker_image_width = calibrated_scale_marker_width / calibrations[0].scale
                    scale_marker_width = scale_marker_image_width * screen_pixel_per_image_pixel
                    drawing_context.begin_path()
                    drawing_context.move_to(origin[1], origin[0])
                    drawing_context.line_to(origin[1] + scale_marker_width, origin[0])
                    drawing_context.line_to(origin[1] + scale_marker_width, origin[0] - scale_marker_height)
                    drawing_context.line_to(origin[1], origin[0] - scale_marker_height)
                    drawing_context.close_path()
                    drawing_context.fill_style = "#448"
                    drawing_context.fill()
                    drawing_context.stroke_style="#000"
                    drawing_context.stroke()
                    drawing_context.font = "normal 14px serif"
                    drawing_context.text_baseline = "bottom"
                    drawing_context.fill_style = "#FFF"
                    drawing_context.fill_text(calibrations[0].convert_to_calibrated_size_str(scale_marker_image_width), origin[1], origin[0] - scale_marker_height - 4)
                    data_item_properties = self.data_item.properties
                    info_items = list()
                    voltage = data_item_properties.get("extra_high_tension", 0)
                    if voltage:
                        units = "V"
                        if voltage % 1000 == 0:
                            voltage = voltage / 1000
                            units = "kV"
                        info_items.append("{0} {1}".format(voltage, units))
                    source = data_item_properties.get("hardware_source")
                    if source:
                        info_items.append(str(source))
                    drawing_context.fill_text(" ".join(info_items), origin[1], origin[0] - scale_marker_height - 4 - 20)

            drawing_context.restore()


class LinePlotCanvasItem(CanvasItem.CanvasItemComposition):

    def __init__(self, data_item_binding, document_controller, image_panel):
        super(LinePlotCanvasItem, self).__init__()

        # connect self as listener. this will result in calls to data_item_binding_data_item_changed
        # and data_item_binding_data_item_content_changed
        self.data_item_binding = data_item_binding
        self.data_item_binding.add_listener(self)

        # ugh
        self.document_controller = document_controller
        self.image_panel = image_panel

        # create the child canvas items
        #self.horizontal_canvas_item = CanvasItem.CanvasItemComposition()
        #self.horizontal_canvas_item.layout = CanvasItem.CanvasItemRowLayout()
        #self.vertical_canvas_item = CanvasItem.CanvasItemComposition()
        #self.vertical_canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        self.line_graph_canvas_item = LineGraphCanvasItem.LineGraphCanvasItem()
        self.focus_ring_canvas_item = CanvasItem.FocusRingCanvasItem()

        # canvas items get added back to front
        #self.vertical_canvas_item.add_canvas_item(self.line_graph_canvas_item)
        #self.horizontal_canvas_item.add_canvas_item(self.vertical_canvas_item)
        #self.horizontal_canvas_item.add_canvas_item(self.vertical_canvas_item)
        #self.add_canvas_item(self.horizontal_canvas_item)
        self.add_canvas_item(self.line_graph_canvas_item)
        self.add_canvas_item(self.focus_ring_canvas_item)

        class LinePlotLayout(object):
            def __init__(self, line_plot_canvas_item):
                self.line_plot_canvas_item = line_plot_canvas_item
            def layout(self, canvas_origin, canvas_size, canvas_items):
                canvas_items[0].update_layout((canvas_origin[0], canvas_origin[1] + 80), (canvas_size[0], canvas_size[1] - 80))
                canvas_items[1].update_layout(canvas_origin, canvas_size)
        #self.layout = LinePlotLayout(self)

        # a thread for updating
        self.__paint_thread = DataItemThread(lambda data_item: self.__update_data_item(data_item), 0.05)

        self.preferred_aspect_ratio = 1.618  # the golden ratio
        
        self.__last_mouse = None
        self.__mouse_in = False

        # initial data item changed message
        self.data_item_binding_data_item_changed(self.data_item_binding.data_item)

    def close(self):
        self.__paint_thread.close()
        self.__paint_thread = None
        # disconnect self as listener
        self.data_item_binding.remove_listener(self)
        # call super
        super(LinePlotCanvasItem, self).close()

    def mouse_clicked(self, x, y, modifiers):
        if super(LinePlotCanvasItem, self).mouse_clicked(x, y, modifiers):
            return True
        return False

    def __get_focused(self):
        return self.focus_ring_canvas_item.focused
    def __set_focused(self, focused):
        self.focus_ring_canvas_item.focused = focused
        self.focus_ring_canvas_item.update()
        self.repaint_if_needed()
    focused = property(__get_focused, __set_focused)

    def __get_selected(self):
        return self.focus_ring_canvas_item.selected
    def __set_selected(self, selected):
        self.focus_ring_canvas_item.selected = selected
        self.focus_ring_canvas_item.update()
        self.repaint_if_needed()
    selected = property(__get_selected, __set_selected)

    # when the data item changes, set the data using this property.
    # doing this will queue an item in the paint thread to repaint.
    def __get_data_item(self):
        return self.__data_item
    data_item = property(__get_data_item)

    def data_item_binding_data_item_changed(self, data_item):
        self.__data_item = data_item
        if self.__data_item and self.__paint_thread:
            self.__paint_thread.update_data(data_item)
        else:
            self.line_graph_canvas_item.data = None
            self.line_graph_canvas_item.update()
            self.repaint_if_needed()

    def data_item_binding_data_item_content_changed(self, data_item, changes):
        self.data_item_binding_data_item_changed(data_item)

    # this method will be invoked from the paint thread.
    # data is calculated and then sent to the line graph canvas item.
    def __update_data_item(self, data_item):

        # make sure we have the correct data
        assert data_item is not None
        assert data_item.is_data_1d

        # grab the data values
        with data_item.data_ref() as data_ref:
            data = data_ref.data
        assert data is not None

        # make sure complex becomes scalar
        data = Image.scalar_from_array(data)
        assert data is not None

        # make sure RGB becomes scalar
        data = Image.convert_to_grayscale(data)
        assert data is not None

        # update the line graph
        self.line_graph_canvas_item.data = data
        self.line_graph_canvas_item.intensity_calibration = data_item.calculated_intensity_calibration if data_item.display_calibrated_values else None
        self.line_graph_canvas_item.spatial_calibration = data_item.calculated_calibrations[0] if data_item.display_calibrated_values else None
        self.line_graph_canvas_item.update()

        self.repaint_if_needed()

    def mouse_entered(self):
        if super(LinePlotCanvasItem, self).mouse_entered():
            return True
        self.__mouse_in = True
        return True

    def mouse_exited(self):
        if super(LinePlotCanvasItem, self).mouse_exited():
            return True
        self.__mouse_in = False
        self.__update_cursor_info()
        return True

    def mouse_position_changed(self, x, y, modifiers):
        if super(LinePlotCanvasItem, self).mouse_position_changed(x, y, modifiers):
            return True
        # x,y already have transform applied
        self.__last_mouse = (y, x)
        self.__update_cursor_info()
        return True

    def __get_data_size(self):
        data_item = self.data_item
        data_shape = data_item.spatial_shape if data_item else None
        if not data_shape:
            return None
        for d in data_shape:
            if not d > 0:
                return None
        return data_shape

    def __update_cursor_info(self):
        if self.document_controller:
            pos = None
            data_size = self.__get_data_size()
            if self.__mouse_in and self.__last_mouse:
                if data_size and len(data_size) == 1:
                    pos = self.line_graph_canvas_item.map_mouse_to_position(self.__last_mouse, data_size)
                self.document_controller.cursor_changed(self, self.data_item, pos, list(), data_size)
            else:
                self.document_controller.cursor_changed(self, None, None, list(), None)

    def drag_enter(self, mime_data):
        if mime_data.has_format("text/data_item_uuid"):
            return "copy"
        return "ignore"

    def drag_leave(self):
        return False

    def drag_move(self, mime_data, x, y):
        if mime_data.has_format("text/data_item_uuid"):
            return "copy"
        return "ignore"

    def drop(self, mime_data, x, y):
        if mime_data.has_format("text/data_item_uuid"):
            data_item_uuid = uuid.UUID(mime_data.data_as_string("text/data_item_uuid"))
            data_item = self.document_controller.document_model.get_data_item_by_key(data_item_uuid)
            if self.image_panel:
                self.image_panel.data_item = data_item
            return "copy"
        return "ignore"


# binding to a child of another data item binding
class CanvasItemChildDataItemBinding(DataItem.DataItemBinding):

    def __init__(self, data_item_binding, uuid):
        super(CanvasItemChildDataItemBinding, self).__init__()
        self.data_item_binding = data_item_binding
        self.uuid = uuid
        # connect self as listener. this will result in calls to data_item_binding_data_item_changed
        # and data_item_binding_data_item_content_changed
        self.data_item_binding.add_listener(self)

        # initial data item changed message
        self.data_item_binding_data_item_changed(self.data_item_binding.data_item)

    def close(self):
        # disconnect self as listener
        self.data_item_binding.remove_listener(self)
        super(CanvasItemChildDataItemBinding, self).close()

    # this message is received from the enclosing data item binding.
    def data_item_binding_data_item_changed(self, data_item):
        if data_item:
            for child_data_item in data_item.data_items:
                if child_data_item.uuid == self.uuid:
                    self.notify_data_item_binding_data_item_changed(child_data_item)
                    return
        self.notify_data_item_binding_data_item_changed(None)

    def data_item_binding_data_item_content_changed(self, data_item, changes):
        if data_item:
            for child_data_item in data_item.data_items:
                if child_data_item.uuid == self.uuid:
                    self.notify_data_item_binding_data_item_content_changed(child_data_item, changes)
                    return
        # do not pass on if no content changed


class ImageCanvasItem(CanvasItem.CanvasItemComposition):

    def __init__(self, data_item_binding, document_controller, image_panel):
        super(ImageCanvasItem, self).__init__()

        # connect self as listener. this will result in calls to data_item_binding_data_item_changed
        # and data_item_binding_data_item_content_changed
        self.data_item_binding = data_item_binding
        self.data_item_binding.add_listener(self)

        # ugh. these are optional.
        self.document_controller = document_controller
        self.image_panel = image_panel

        self.accessories = dict()

        self.__last_image_zoom = 1.0
        self.__last_image_norm_center = (0.5, 0.5)
        self.image_canvas_mode = "fit"

        # create the child canvas items
        # the background
        self.background_canvas_item = CanvasItem.BackgroundCanvasItem()
        # next the zoomable items
        self.bitmap_canvas_item = CanvasItem.BitmapCanvasItem()
        self.graphics_canvas_item = GraphicsCanvasItem()
        # put the zoomable items into a composition
        self.composite_canvas_item = CanvasItem.CanvasItemComposition()
        self.composite_canvas_item.add_canvas_item(self.bitmap_canvas_item)
        self.composite_canvas_item.add_canvas_item(self.graphics_canvas_item)
        # and put the composition into a scroll area
        self.scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(self.composite_canvas_item)
        self.scroll_area_canvas_item.updated_layout = lambda canvas_origin, canvas_size: self.scroll_area_canvas_item_updated_layout(canvas_size)
        # next the accessory canvas
        self.accessory_canvas_item = CanvasItem.CanvasItemComposition()
        self.accessory_canvas_item.layout = CanvasItem.CanvasItemColumnLayout(origin=(16, 20), spacing=12, fraction=0.25, min_width=200, max_width=320)
        # info overlay (scale marker, etc.)
        self.info_overlay_canvas_item = InfoOverlayCanvasItem()
        # and focus ring
        self.focus_ring_canvas_item = CanvasItem.FocusRingCanvasItem()
        # canvas items get added back to front
        self.add_canvas_item(self.background_canvas_item)
        self.add_canvas_item(self.scroll_area_canvas_item)
        self.add_canvas_item(self.accessory_canvas_item)
        self.add_canvas_item(self.info_overlay_canvas_item)
        self.add_canvas_item(self.focus_ring_canvas_item)

        # a thread for updating
        self.__paint_thread = DataItemThread(lambda data_item: self.__update_data_item(data_item), 0.05)

        # used for dragging graphic items
        self.graphic_drag_items = []
        self.graphic_drag_item = None
        self.graphic_part_data = {}
        self.graphic_drag_indexes = []
        self.graphic_selection = GraphicSelection()
        self.graphic_selection.add_listener(self)
        self.__last_mouse = None
        self.__is_dragging = False
        self.__mouse_in = False
        self.graphics_canvas_item.graphic_selection = self.graphic_selection

        # initial data item changed message
        self.data_item_binding_data_item_changed(self.data_item_binding.data_item)

    def close(self):
        self.__paint_thread.close()
        self.__paint_thread = None
        self.__data_item = None
        self.graphic_selection.remove_listener(self)
        self.graphic_selection = None
        # disconnect self as listener
        self.data_item_binding.remove_listener(self)
        # call super
        super(ImageCanvasItem, self).close()

    def __get_preferred_aspect_ratio(self):
        if self.data_item:
            spatial_shape = self.data_item.spatial_shape
            return spatial_shape[1] / spatial_shape[0] if spatial_shape[0] != 0 else 1.0
        return 1.0
    preferred_aspect_ratio = property(__get_preferred_aspect_ratio)

    def update_image_canvas_zoom(self, new_image_zoom):
        if self.data_item:
            self.image_canvas_mode = "custom"
            self.__last_image_zoom = new_image_zoom
            self.update_image_canvas_size()

    # update the image canvas position by the widget delta amount
    def update_image_canvas_position(self, widget_delta):
        if self.data_item:
            # create a widget mapping to get from image norm to widget coordinates and back
            widget_mapping = WidgetMapping(self.data_item.spatial_shape, (0, 0), self.composite_canvas_item.canvas_size)
            # figure out what composite canvas point lies at the center of the scroll area.
            last_widget_center = widget_mapping.map_point_image_norm_to_widget(self.__last_image_norm_center)
            # determine what new point will lie at the center of the scroll area by adding delta
            new_widget_center = (last_widget_center[0] + widget_delta[0], last_widget_center[1] + widget_delta[1])
            # map back to image norm coordinates
            new_image_norm_center = widget_mapping.map_point_widget_to_image_norm(new_widget_center)
            # ensure that at least half of the image is always visible
            new_image_norm_center_0 = max(min(new_image_norm_center[0], 1.0), 0.0)
            new_image_norm_center_1 = max(min(new_image_norm_center[1], 1.0), 0.0)
            # save the new image norm center
            self.__last_image_norm_center = (new_image_norm_center_0, new_image_norm_center_1)
            # and update the image canvas accordingly
            self.image_canvas_mode = "custom"
            self.update_image_canvas_size()

    # update the image canvas origin and size
    def scroll_area_canvas_item_updated_layout(self, scroll_area_canvas_size):
        if not self.data_item:
            self.__last_image_norm_center = (0.5, 0.5)
            self.__last_image_zoom = 1.0
            self.info_overlay_canvas_item.image_canvas_origin = None
            self.info_overlay_canvas_item.image_canvas_size = None
            return
        if self.image_canvas_mode == "fill":
            spatial_shape = self.data_item.spatial_shape
            scale_h = float(spatial_shape[1]) / scroll_area_canvas_size[1]
            scale_v = float(spatial_shape[0]) / scroll_area_canvas_size[0]
            if scale_v < scale_h:
                image_canvas_size = (scroll_area_canvas_size[0], scroll_area_canvas_size[0] * spatial_shape[1] / spatial_shape[0])
            else:
                image_canvas_size = (scroll_area_canvas_size[1] * spatial_shape[0] / spatial_shape[1], scroll_area_canvas_size[1])
            image_canvas_origin = (scroll_area_canvas_size[0] * 0.5 - image_canvas_size[0] * 0.5, scroll_area_canvas_size[1] * 0.5 - image_canvas_size[1] * 0.5)
            self.composite_canvas_item.update_layout(image_canvas_origin, image_canvas_size)
        elif self.image_canvas_mode == "fit":
            image_canvas_size = scroll_area_canvas_size
            image_canvas_origin = (0, 0)
            self.composite_canvas_item.update_layout(image_canvas_origin, image_canvas_size)
        elif self.image_canvas_mode == "1:1":
            image_canvas_size = self.data_item.spatial_shape
            image_canvas_origin = (scroll_area_canvas_size[0] * 0.5 - image_canvas_size[0] * 0.5, scroll_area_canvas_size[1] * 0.5 - image_canvas_size[1] * 0.5)
            self.composite_canvas_item.update_layout(image_canvas_origin, image_canvas_size)
        else:
            c = self.__last_image_norm_center
            spatial_shape = self.data_item.spatial_shape
            image_canvas_size = (scroll_area_canvas_size[0] * self.__last_image_zoom, scroll_area_canvas_size[1] * self.__last_image_zoom)
            canvas_rect = Geometry.fit_to_size(((0, 0), image_canvas_size), spatial_shape)
            # c[0] = ((scroll_area_canvas_size[0] * 0.5 - image_canvas_origin[0]) - canvas_rect[0][0])/canvas_rect[1][0]
            image_canvas_origin_y = (scroll_area_canvas_size[0] * 0.5) - c[0] * canvas_rect[1][0] - canvas_rect[0][0]
            image_canvas_origin_x = (scroll_area_canvas_size[1] * 0.5) - c[1] * canvas_rect[1][1] - canvas_rect[0][1]
            image_canvas_origin = (image_canvas_origin_y, image_canvas_origin_x)
            self.composite_canvas_item.update_layout(image_canvas_origin, image_canvas_size)
        # the image will be drawn centered within the canvas size
        spatial_shape = self.data_item.spatial_shape
        #logging.debug("scroll_area_canvas_size %s", scroll_area_canvas_size)
        #logging.debug("image_canvas_origin %s", image_canvas_origin)
        #logging.debug("image_canvas_size %s", image_canvas_size)
        #logging.debug("spatial_shape %s", spatial_shape)
        #logging.debug("c %s %s", (scroll_area_canvas_size[0] * 0.5 - image_canvas_origin[0]) / spatial_shape[0], (scroll_area_canvas_size[1] * 0.5 - image_canvas_origin[1]) / spatial_shape[1])
        widget_mapping = WidgetMapping(self.data_item.spatial_shape, (0, 0), image_canvas_size)
        #logging.debug("c2 %s", widget_mapping.map_point_widget_to_image_norm((scroll_area_canvas_size[0] * 0.5 - image_canvas_origin[0], scroll_area_canvas_size[1] * 0.5 - image_canvas_origin[1])))
        self.__last_image_norm_center = widget_mapping.map_point_widget_to_image_norm((scroll_area_canvas_size[0] * 0.5 - image_canvas_origin[0], scroll_area_canvas_size[1] * 0.5 - image_canvas_origin[1]))
        canvas_rect = Geometry.fit_to_size(((0, 0), image_canvas_size), spatial_shape)
        scroll_rect = Geometry.fit_to_size(((0, 0), scroll_area_canvas_size), spatial_shape)
        self.__last_image_zoom = float(canvas_rect[1][0]) / scroll_rect[1][0]
        #logging.debug("z %s (%s)", self.__last_image_zoom, float(canvas_rect[1][1]) / scroll_rect[1][1])
        self.info_overlay_canvas_item.image_canvas_origin = image_canvas_origin
        self.info_overlay_canvas_item.image_canvas_size = image_canvas_size

    def update_image_canvas_size(self):
        scroll_area_canvas_size = self.scroll_area_canvas_item.canvas_size
        if scroll_area_canvas_size is not None:
            self.scroll_area_canvas_item_updated_layout(scroll_area_canvas_size)
            self.composite_canvas_item.update()
            self.scroll_area_canvas_item.repaint_if_needed()

    def mouse_clicked(self, x, y, modifiers):
        if super(ImageCanvasItem, self).mouse_clicked(x, y, modifiers):
            return True
        # now let the image panel handle mouse clicking if desired
        image_position = self.__get_mouse_mapping().map_point_widget_to_image((y, x))
        ImagePanelManager().mouse_clicked(self.image_panel, self.data_item, image_position, modifiers)
        return True

    def mouse_double_clicked(self, x, y, modifiers):
        self.set_fit_mode()
        return True

    def mouse_pressed(self, x, y, modifiers):
        if super(ImageCanvasItem, self).mouse_pressed(x, y, modifiers):
            return True
        # figure out clicked graphic
        self.graphic_drag_items = []
        self.graphic_drag_item = None
        self.graphic_drag_item_was_selected = False
        self.graphic_part_data = {}
        self.graphic_drag_indexes = []
        if self.data_item:
            for graphic_index, graphic in enumerate(self.data_item.graphics):
                start_drag_pos = y, x
                already_selected = self.graphic_selection.contains(graphic_index)
                multiple_items_selected = len(self.graphic_selection.indexes) > 1
                move_only = not already_selected or multiple_items_selected
                widget_mapping = self.__get_mouse_mapping()
                part = graphic.test(widget_mapping, start_drag_pos, move_only)
                if part:
                    # select item and prepare for drag
                    self.graphic_drag_item_was_selected = self.graphic_selection.contains(graphic_index)
                    if not self.graphic_drag_item_was_selected:
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
            self.__start_drag_pos = (y, x)
            self.__last_drag_pos = (y, x)
            self.__is_dragging = True
        return True

    def mouse_released(self, x, y, modifiers):
        if super(ImageCanvasItem, self).mouse_released(x, y, modifiers):
            return True
        for index in self.graphic_drag_indexes:
            graphic = self.data_item.graphics[index]
            graphic.end_drag(self.graphic_part_data[index])
        if self.graphic_drag_items and not self.graphic_drag_changed:
            graphic_index = self.data_item.graphics.index(self.graphic_drag_item)
            # user didn't move graphic
            if not modifiers.shift:
                # user clicked on a single graphic
                assert self.data_item
                self.graphic_selection.set(graphic_index)
            else:
                # user shift clicked. toggle selection
                # if shift is down and item is already selected, toggle selection of item
                if self.graphic_drag_item_was_selected:
                    self.graphic_selection.remove(graphic_index)
                else:
                    self.graphic_selection.add(graphic_index)
        self.graphic_drag_items = []
        self.graphic_drag_item = None
        self.graphic_part_data = {}
        self.graphic_drag_indexes = []
        self.__start_drag_pos = None
        self.__last_drag_pos = None
        self.__is_dragging = False
        return True

    def mouse_entered(self):
        if super(ImageCanvasItem, self).mouse_entered():
            return True
        self.__mouse_in = True
        return True

    def mouse_exited(self):
        if super(ImageCanvasItem, self).mouse_exited():
            return True
        self.__mouse_in = False
        self.__update_cursor_info()
        return True

    def mouse_position_changed(self, x, y, modifiers):
        if super(ImageCanvasItem, self).mouse_position_changed(x, y, modifiers):
            return True
        # x,y already have transform applied
        self.__last_mouse = (y, x)
        self.__update_cursor_info()
        if self.graphic_drag_items:
            for graphic in self.graphic_drag_items:
                index = self.data_item.graphics.index(graphic)
                part_data = (self.graphic_drag_part, ) + self.graphic_part_data[index]
                widget_mapping = self.__get_mouse_mapping()
                graphic.adjust_part(widget_mapping, self.graphic_drag_start_pos, (y, x), part_data, modifiers)
                self.graphic_drag_changed = True
                self.graphics_canvas_item.update()
        elif self.__is_dragging:
            delta = (y - self.__last_drag_pos[0], x - self.__last_drag_pos[1])
            self.update_image_canvas_position((-delta[0], -delta[1]))
            self.__last_drag_pos = (y, x)
        self.graphics_canvas_item.repaint_if_needed()
        return True

    def wheel_changed(self, dx, dy, is_horizontal):
        dx = dx if is_horizontal else 0.0
        dy = dy if not is_horizontal else 0.0
        self.update_image_canvas_position((-dy, -dx))

    def pan_gesture(self, dx, dy):
        self.update_image_canvas_position((dy, dx))
        return True

    # ths message comes from the widget
    def key_pressed(self, key):
        if super(ImageCanvasItem, self).key_pressed(key):
            return True
        # only handle keys if we're directly embedded in an image panel
        if not self.image_panel:
            return False
        #logging.debug("text=%s key=%s mod=%s", key.text, hex(key.key), key.modifiers)
        all_graphics = self.data_item.graphics if self.data_item else []
        graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if self.graphic_selection.contains(graphic_index)]
        if len(graphics):
            if key.is_delete:
                self.document_controller.remove_graphic()
            elif key.is_arrow:
                widget_mapping = self.__get_mouse_mapping()
                amount = 10.0 if key.modifiers.shift else 1.0
                if key.is_left_arrow:
                    for graphic in graphics:
                        graphic.nudge(widget_mapping, (0, -amount))
                elif key.is_up_arrow:
                    for graphic in graphics:
                        graphic.nudge(widget_mapping, (-amount, 0))
                elif key.is_right_arrow:
                    for graphic in graphics:
                        graphic.nudge(widget_mapping, (0, amount))
                elif key.is_down_arrow:
                    for graphic in graphics:
                        graphic.nudge(widget_mapping, (amount, 0))
                return True
        if key.is_arrow:
            amount = 100.0 if key.modifiers.shift else 10.0
            if key.is_left_arrow:
                self.move_left(amount)
            elif key.is_up_arrow:
                self.move_up(amount)
            elif key.is_right_arrow:
                self.move_right(amount)
            elif key.is_down_arrow:
                self.move_down(amount)
            return True
        if key.text == "H":
            histogram_canvas_item = self.accessories.get("histogram")
            if histogram_canvas_item:
                self.accessory_canvas_item.remove_canvas_item(histogram_canvas_item)
                histogram_canvas_item.close()
                del self.accessories["histogram"]
                self.repaint_if_needed()
            else:
                histogram_canvas_item = HistogramPanel.HistogramCanvasItem(self.data_item_binding)
                histogram_canvas_item.background_color = "#EEEEEE"
                self.accessory_canvas_item.add_canvas_item(histogram_canvas_item)
                self.accessories["histogram"] = histogram_canvas_item
                self.repaint_if_needed()
            return True
        if key.text == "F":
            fft_canvas_item = self.accessories.get("fft")
            if fft_canvas_item:
                self.accessory_canvas_item.remove_canvas_item(fft_canvas_item)
                fft_canvas_item.close()
                del self.accessories["fft"]
                self.repaint_if_needed()
            else:
                data_item = None
                for child_data_item in self.__data_item.data_items:
                    if len(child_data_item.operations) and child_data_item.operations[0].operation_id == "fft-operation":
                        data_item = child_data_item
                if not data_item:
                    data_item = self.document_controller.processing_fft(select=False)
                data_item_binding = CanvasItemChildDataItemBinding(self.data_item_binding, data_item.uuid)
                fft_canvas_item = ImageCanvasItem(data_item_binding, None, None)
                self.accessory_canvas_item.add_canvas_item(fft_canvas_item)
                self.accessories["fft"] = fft_canvas_item
                self.repaint_if_needed()
            return True
        if key.text == "P":
            line_profile_canvas_item = self.accessories.get("line_profile")
            if line_profile_canvas_item:
                self.accessory_canvas_item.remove_canvas_item(line_profile_canvas_item)
                line_profile_canvas_item.close()
                del self.accessories["line_profile"]
                self.repaint_if_needed()
            else:
                data_item = None
                for child_data_item in self.__data_item.data_items:
                    if len(child_data_item.operations) and child_data_item.operations[0].operation_id == "line-profile-operation":
                        data_item = child_data_item
                if not data_item:
                    data_item = self.document_controller.processing_line_profile(select=False)
                data_item_binding = CanvasItemChildDataItemBinding(self.data_item_binding, data_item.uuid)
                line_profile_canvas_item = LinePlotCanvasItem(data_item_binding, None, None)
                self.accessory_canvas_item.add_canvas_item(line_profile_canvas_item)
                self.accessories["line_profile"] = line_profile_canvas_item
                self.repaint_if_needed()
            return True
        if key.text == "-":
            self.zoom_out()
            return True
        if key.text == "+":
            self.zoom_in()
            return True
        if key.text == "j":
            self.move_left()
            return True
        if key.text == "k":
            self.move_right()
            return True
        if key.text == "i":
            self.move_up()
            return True
        if key.text == "m":
            self.move_down()
            return True
        if key.text == "1":
            self.set_one_to_one_mode()
            return True
        if key.text == "0":
            self.set_fit_mode()
            return True
        if key.text == ")":
            self.set_fill_mode()
            return True
        return self.image_panel.key_pressed(key)

    def __get_focused(self):
        return self.focus_ring_canvas_item.focused
    def __set_focused(self, focused):
        self.focus_ring_canvas_item.focused = focused
        self.focus_ring_canvas_item.update()
        self.repaint_if_needed()
    focused = property(__get_focused, __set_focused)

    def __get_selected(self):
        return self.focus_ring_canvas_item.selected
    def __set_selected(self, selected):
        self.focus_ring_canvas_item.selected = selected
        self.focus_ring_canvas_item.update()
        self.repaint_if_needed()
    selected = property(__get_selected, __set_selected)

    # when the data item changes, set the data using this property.
    # doing this will queue an item in the paint thread to repaint.
    def __get_data_item(self):
        return self.__data_item
    data_item = property(__get_data_item)

    def data_item_binding_data_item_changed(self, data_item):
        self.__data_item = data_item
        self.__update_cursor_info()
        if self.__data_item and self.__paint_thread:
            self.__paint_thread.update_data(data_item)
        else:
            self.bitmap_canvas_item.rgba_bitmap_data = None
            self.bitmap_canvas_item.update()
            self.graphics_canvas_item.data_item = None
            self.graphics_canvas_item.update()
            self.info_overlay_canvas_item.data_item = None
            self.info_overlay_canvas_item.update()
            self.repaint_if_needed()

    def data_item_binding_data_item_content_changed(self, data_item, changes):
        self.data_item_binding_data_item_changed(data_item)

    def selection_changed(self, graphic_selection):
        self.graphics_canvas_item.update()
        self.repaint_if_needed()

    # watch for changes to the graphic item list
    def item_inserted(self, object, key, value, before_index):
        if object == self.data_item and key == "graphics":
            # selection is 5,6,7
            # if inserted at 4, new selection is 6,7,8
            # if inserted at 6, new selection is 5,7,8
            # indexes greater or equal to new index are incremented
            self.graphic_selection.insert_index(before_index)
            self.graphics_canvas_item.update()
            self.graphics_canvas_item.repaint_if_needed()
    def item_removed(self, object, key, value, index):
        if object == self.data_item and key == "graphics":
            # selection is 5,6,7
            # if 4 is removed, new selection is 4,5,6
            # if 6 is removed, new selection is 5,6
            # the index is removed; and remaining indexes greater than removed one are decremented
            self.graphic_selection.remove_index(index)
            self.graphics_canvas_item.update()
            self.graphics_canvas_item.repaint_if_needed()

    def __get_image_size(self):
        data_item = self.data_item
        data_shape = data_item.spatial_shape if data_item else None
        if not data_shape:
            return None
        for d in data_shape:
            if not d > 0:
                return None
        return data_shape

    def __get_mouse_mapping(self):
        image_size = self.__get_image_size()
        return WidgetMapping(image_size, self.composite_canvas_item.canvas_origin, self.composite_canvas_item.canvas_size)

    # map from widget coordinates to image coordinates
    def map_widget_to_image(self, p):
        image_size = self.__get_image_size()
        transformed_image_rect = self.__get_mouse_mapping().canvas_rect
        if transformed_image_rect and image_size:
            if transformed_image_rect[1][0] != 0.0:
                image_y = image_size[0] * (p[0] - transformed_image_rect[0][0])/transformed_image_rect[1][0]
            else:
                image_y = 0
            if transformed_image_rect[1][1] != 0.0:
                image_x = image_size[1] * (p[1] - transformed_image_rect[0][1])/transformed_image_rect[1][1]
            else:
                image_x = 0
            return (image_y, image_x) # c-indexing
        return None

    # map from image normalized coordinates to image coordinates
    def map_image_norm_to_image(self, p):
        image_size = self.__get_image_size()
        if image_size:
            return (p[0] * image_size[0], p[1] * image_size[1])
        return None

    def __update_cursor_info(self):
        if self.document_controller:
            pos = None
            image_size = self.__get_image_size()
            if self.__mouse_in and self.__last_mouse:
                if image_size and len(image_size) > 1:
                    pos = self.map_widget_to_image(self.__last_mouse)
                data_item = self.data_item
                graphics = data_item.graphics if data_item else None
                selected_graphics = [graphics[index] for index in self.graphic_selection.indexes] if graphics else []
                self.document_controller.cursor_changed(self, self.data_item, pos, selected_graphics, image_size)
            else:
                self.document_controller.cursor_changed(self, None, None, list(), None)

    # this method will be invoked from the paint thread.
    # data is calculated and then sent to the line graph canvas item.
    def __update_data_item(self, data_item):

        # make sure we have the correct data
        assert data_item is not None
        assert data_item.is_data_2d

        # grab the bitmap image
        rgba_image = data_item.preview_2d
        self.bitmap_canvas_item.rgba_bitmap_data = rgba_image
        self.bitmap_canvas_item.update()

        self.graphics_canvas_item.data_item = data_item
        self.graphics_canvas_item.update()

        self.info_overlay_canvas_item.data_item = data_item
        self.info_overlay_canvas_item.update()

        self.repaint_if_needed()

    def drag_enter(self, mime_data):
        if mime_data.has_format("text/data_item_uuid"):
            return "copy"
        return "ignore"

    def drag_leave(self):
        return False

    def drag_move(self, mime_data, x, y):
        if mime_data.has_format("text/data_item_uuid"):
            return "copy"
        return "ignore"

    def drop(self, mime_data, x, y):
        if mime_data.has_format("text/data_item_uuid"):
            data_item_uuid = uuid.UUID(mime_data.data_as_string("text/data_item_uuid"))
            data_item = self.document_controller.document_model.get_data_item_by_key(data_item_uuid)
            if self.image_panel:
                self.image_panel.data_item = data_item
            return "copy"
        return "ignore"

    def set_fit_mode(self):
        #logging.debug("---------> fit")
        self.image_canvas_mode = "fit"
        self.__last_image_zoom = 1.0
        self.__last_image_norm_center = (0.5, 0.5)
        self.update_image_canvas_size()

    def set_fill_mode(self):
        #logging.debug("---------> fill")
        self.image_canvas_mode = "fill"
        self.__last_image_zoom = 1.0
        self.__last_image_norm_center = (0.5, 0.5)
        self.update_image_canvas_size()

    def set_one_to_one_mode(self):
        #logging.debug("---------> 1:1")
        self.image_canvas_mode = "1:1"
        self.__last_image_zoom = 1.0
        self.__last_image_norm_center = (0.5, 0.5)
        self.update_image_canvas_size()

    def zoom_in(self):
        self.update_image_canvas_zoom(self.__last_image_zoom * 1.05)

    def zoom_out(self):
        self.update_image_canvas_zoom(self.__last_image_zoom / 1.05)

    def move_left(self, amount=10.0):
        self.update_image_canvas_position((0.0, amount))

    def move_right(self, amount=10.0):
        self.update_image_canvas_position((0.0, -amount))

    def move_up(self, amount=10.0):
        self.update_image_canvas_position((amount, 0.0))

    def move_down(self, amount=10.0):
        self.update_image_canvas_position((-amount, 0.0))


class ImagePanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(ImagePanel, self).__init__(document_controller, panel_id, _("Image Panel"))

        self.__data_item = None

        self.image_root_canvas_item = CanvasItem.RootCanvasItem(document_controller.ui)
        self.image_root_canvas_item.focusable = True
        self.image_root_canvas_item.on_focus_changed = lambda focused: self.set_focused(focused)
        self.image_data_item_binding = DataItem.DataItemBinding()
        self.image_canvas_item = ImageCanvasItem(self.image_data_item_binding, document_controller, self)
        self.image_root_canvas_item.add_canvas_item(self.image_canvas_item)
        self.image_header_controller = Panel.HeaderWidgetController(self.ui)
        self.image_widget = self.ui.create_column_widget()
        self.image_widget.add(self.image_header_controller.canvas_widget)
        self.image_widget.add(self.image_root_canvas_item.canvas, fill=True)

        self.line_plot_root_canvas_item = CanvasItem.RootCanvasItem(document_controller.ui)
        self.line_plot_root_canvas_item.focusable = True
        self.line_plot_root_canvas_item.on_focus_changed = lambda focused: self.set_focused(focused)
        self.line_plot_item_binding = DataItem.DataItemBinding()
        self.line_plot_canvas_item = LinePlotCanvasItem(self.line_plot_item_binding, document_controller, self)
        self.line_plot_root_canvas_item.add_canvas_item(self.line_plot_canvas_item)
        self.line_plot_header_controller = Panel.HeaderWidgetController(self.ui)
        self.line_plot_widget = self.ui.create_column_widget()
        self.line_plot_widget.add(self.line_plot_header_controller.canvas_widget)
        self.line_plot_widget.add(self.line_plot_root_canvas_item.canvas, fill=True)

        self.widget = self.ui.create_stack_widget()
        self.widget.add(self.image_widget)
        self.widget.add(self.line_plot_widget)

        self.document_controller.register_image_panel(self)

        self.document_controller.document_model.add_listener(self)

        self.closed = False

    def close(self):
        self.closed = True
        self.image_data_item_binding.notify_data_item_binding_data_item_changed(None)  # not strictly necessary except to make test_image_panel_releases_data_item pass
        self.image_root_canvas_item.close()
        self.image_root_canvas_item = None
        self.line_plot_item_binding.notify_data_item_binding_data_item_changed(None)  # not strictly necessary except to make test_image_panel_releases_data_item pass
        self.line_plot_root_canvas_item.close()
        self.line_plot_root_canvas_item = None
        self.line_plot_item_binding.close()
        self.line_plot_item_binding = None
        self.image_data_item_binding.close()
        self.image_data_item_binding = None
        self.document_controller.document_model.remove_listener(self)
        self.document_controller.unregister_image_panel(self)
        self.data_item = None  # required before destructing display thread
        super(ImagePanel, self).close()

    # return a dictionary that can be used to restore the content of this image panel
    def save_content(self):
        content = {}
        data_item = self.data_item
        if data_item:
            content["data-item"] = data_item.uuid
        return content

    # restore content from dictionary and document controller
    def restore_content(self, content, document_controller):
        if "data-item" in content:
            data_item_uuid = content["data-item"]
            data_item = document_controller.document_model.get_data_item_by_key(data_item_uuid)
            if data_item:
                self.data_item = data_item

    def set_selected(self, selected):
        if self.closed: return  # argh
        self.image_canvas_item.selected = selected
        self.line_plot_canvas_item.selected = selected

    # this message comes from the canvas items via the on_focus_changed when their focus changes
    def set_focused(self, focused):
        if self.closed: return  # argh
        self.image_canvas_item.focused = focused
        self.line_plot_canvas_item.focused = focused
        self.document_controller.selected_image_panel = self
        self.document_controller.set_selected_data_item(self.data_item)

    # sets the data item that this panel displays
    def set_data_item(self, data_item):
        self.data_item = data_item

    def __get_data_item(self):
        return self.__data_item
    def __set_data_item(self, data_item):
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            # keep new data in memory. if new and old values are the same, putting
            # this here will prevent the data from unloading and then reloading.
            data_item.increment_data_ref_count()
        # track data item in this class to report changes
        if self.__data_item:
            self.__data_item.decrement_data_ref_count()  # don't keep data in memory anymore
            self.__data_item.remove_observer(self)
            self.__data_item.remove_listener(self)
            self.__data_item.remove_ref()
        self.__data_item = data_item
        self.data_item_content_changed(self.__data_item, set([DataItem.SOURCE]))
        self.image_canvas_item.image_canvas_mode = "fit"
        self.image_canvas_item.update_image_canvas_size()
        # these connections should be configured after the messages above.
        # the instant these are added, we may be receiving messages from threads.
        if self.__data_item:
            self.__data_item.add_ref()
            self.__data_item.add_listener(self)
            self.__data_item.add_observer(self)  # watch for graphics being added/removed
            # note: data_ref_count has already been incremented above.
        # let the image panel manager know the data item changed
        ImagePanelManager().data_item_changed(self)
    data_item = property(__get_data_item, __set_data_item)

    # watch for changes to the graphic item list
    def item_inserted(self, object, key, value, before_index):
        self.image_canvas_item.item_inserted(object, key, value, before_index)
    def item_removed(self, object, key, value, index):
        self.image_canvas_item.item_removed(object, key, value, index)

    def data_item_deleted(self, data_item):
        # if our item gets deleted, clear the selection
        if data_item == self.data_item:
            self.data_item = None

    # this message comes from the data item associated with this panel.
    # the connection is established in __set_data_item via data_item.add_listener.
    # this will be called when anything in the data item changes, including things
    # like graphics or the data itself.
    def data_item_content_changed(self, data_item, changes):
        if data_item == self.data_item:  # we can get messages from our source data items too
            self.image_header_controller.title = data_item.title if data_item else unicode()
            self.line_plot_header_controller.title = data_item.title if data_item else unicode()
            selected = self.document_controller.selected_image_panel == self
            if data_item:
                if data_item.is_data_1d:
                    self.widget.current_index = 1
                    self.line_plot_item_binding.notify_data_item_binding_data_item_changed(data_item)
                    self.line_plot_canvas_item.selected = selected
                    self.image_data_item_binding.notify_data_item_binding_data_item_changed(None)
                    self.image_canvas_item.selected = False
                elif data_item.is_data_2d:
                    self.widget.current_index = 0
                    self.image_data_item_binding.notify_data_item_binding_data_item_changed(data_item)
                    self.image_canvas_item.selected = selected
                    self.line_plot_item_binding.notify_data_item_binding_data_item_changed(None)
                    self.line_plot_canvas_item.selected = False
            else:
                if self.line_plot_item_binding:
                    self.line_plot_item_binding.notify_data_item_binding_data_item_changed(None)
                if self.image_data_item_binding:
                    self.image_data_item_binding.notify_data_item_binding_data_item_changed(None)
                self.image_canvas_item.selected = False
                self.line_plot_canvas_item.selected = False

    def __get_graphic_selection(self):
        return self.image_canvas_item.graphic_selection
    graphic_selection = property(__get_graphic_selection)

    def __get_image_size(self):
        data_item = self.data_item
        data_shape = data_item.spatial_shape if data_item else None
        if not data_shape:
            return None
        for d in data_shape:
            if not d > 0:
                return None
        return data_shape
    image_size = property(__get_image_size)

    def __show_data_source(self):
        # TODO: implement show data source again
        pass

    # ths message comes from the widget
    def key_pressed(self, key):
        #logging.debug("text=%s key=%s mod=%s", key.text, hex(key.key), key.modifiers)

        if key.text == "o":
            self.__show_data_source()

        return ImagePanelManager().key_pressed(self, key)


# image panel manager acts as a broker for significant events occurring
# regarding image panels. listeners can attach themselves to this object
# and receive messages regarding image panels. for instance, when the user
# presses a key on an image panel that isn't handled directly by the image
# panel, listeners can be advised of this event.
class ImagePanelManager(Observable.Broadcaster):
    __metaclass__ = Decorators.Singleton
    def __init__(self):
        super(ImagePanelManager, self).__init__()
        pass
    # events from the image panels
    def key_pressed(self, image_panel, key):
        return self.notify_listeners("image_panel_key_pressed", image_panel, key)
    def mouse_clicked(self, image_panel, data_item, image_position, modifiers):
        return self.notify_listeners("image_panel_key_clicked", image_panel, data_item, image_position, modifiers)
    def data_item_changed(self, image_panel):
        self.notify_listeners("image_panel_manager_data_item_changed", image_panel)


class InfoPanel(Panel.Panel):

    """
    The info panel will display cursor information. user interface items that want to
    update the cursor info should called cursor_changed on the document controller.
    This info panel will listen to the document controller for cursor updates and update
    itself in respsone. all cursor update calls are thread safe. this class uses periodic
    to do ui updates from the main thread.
    """

    def __init__(self, document_controller, panel_id, properties):
        super(InfoPanel, self).__init__(document_controller, panel_id, _("Info"))

        ui = document_controller.ui

        self.closed = False

        self.__pending_info = None
        self.__pending_info_mutex = threading.RLock()

        self.__last_source = None

        position_label = ui.create_label_widget(_("Position:"))
        self.position_text = ui.create_label_widget()
        value_label = ui.create_label_widget(_("Value:"))
        self.value_text = ui.create_label_widget()
        self.graphic_text = ui.create_label_widget()

        position_row = ui.create_row_widget(properties={"spacing": 6})
        position_row.add(position_label)
        position_row.add(self.position_text)
        position_row.add_stretch()

        value_row = ui.create_row_widget(properties={"spacing": 6})
        value_row.add(value_label)
        value_row.add(self.value_text)
        value_row.add_stretch()

        graphic_row = ui.create_row_widget(properties={"spacing": 6})
        graphic_row.add(self.graphic_text)
        graphic_row.add_stretch()

        properties["spacing"] = 2
        properties["margin"] = 6
        column = ui.create_column_widget(properties)
        column.add(position_row)
        column.add(value_row)
        column.add(graphic_row)
        column.add_stretch()

        self.widget = column

        # connect self as listener. this will result in calls to cursor_changed
        self.document_controller.add_listener(self)

    def close(self):
        self.closed = True
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # finish closing
        super(InfoPanel, self).close()

    def periodic(self):
        super(InfoPanel, self).periodic()
        with self.__pending_info_mutex:
            do_update = self.__pending_info is not None
            if do_update:
                position_text, value_text, graphic_text = self.__pending_info
                self.__pending_info = None
        if do_update:
            self.position_text.text = position_text
            self.value_text.text = value_text
            self.graphic_text.text = graphic_text

    # this message is received from the document controller.
    # it is established using add_listener
    def cursor_changed(self, source, data_item, pos, selected_graphics, data_size):
        def get_value_text(value, intensity_calibration):
            if value is not None:
                return unicode(intensity_calibration.convert_to_calibrated_value_str(value))
            elif value is None:
                return _("N/A")
            else:
                return str(value)
        position_text = ""
        value_text = ""
        graphic_text = ""
        if data_item and data_size:
            calibrations = data_item.calculated_calibrations
            intensity_calibration = data_item.calculated_intensity_calibration
            if pos and len(pos) == 2:
                # 2d image
                # make sure the position is within the bounds of the image
                if pos[0] >= 0 and pos[0] < data_size[0] and pos[1] >= 0 and pos[1] < data_size[1]:
                    position_text = u"{0}, {1}".format(calibrations[1].convert_to_calibrated_value_str(pos[1] - 0.5 * data_size[1]),
                                                     calibrations[0].convert_to_calibrated_value_str(0.5 * data_size[0] - pos[0]))
                    value_text = get_value_text(data_item.get_data_value(pos), intensity_calibration)
            if pos and len(pos) == 1:
                # 1d plot
                # make sure the position is within the bounds of the line plot
                if pos[0] >= 0 and pos[0] < data_size[0]:
                    position_text = u"{0}".format(calibrations[0].convert_to_calibrated_value_str(pos[0]))
                    value_text = get_value_text(data_item.get_data_value(pos), intensity_calibration)
            if len(selected_graphics) == 1:
                graphic = selected_graphics[0]
                graphic_text = graphic.calibrated_description(data_size, calibrations)
            self.__last_source = source
        if self.__last_source == source:
            with self.__pending_info_mutex:
                self.__pending_info = (position_text, value_text, graphic_text)
