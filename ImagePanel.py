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
from nion.swift import CanvasItem
from nion.swift import DataGroup
from nion.swift import DataItem
from nion.swift.Decorators import ProcessingThread
from nion.swift.Decorators import singleton
from nion.swift import Graphics
from nion.swift import Image
from nion.swift import Inspector
from nion.swift import Panel

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

    def __init__(self, data_shape, canvas_size):
        self.data_shape = data_shape
        # double check dimensions are not zero
        if self.data_shape:
            for d in self.data_shape:
                if not d > 0:
                    self.data_shape = None
        # calculate transformed image rect
        self.data_rect = None
        if self.data_shape:
            rect = ((0, 0), canvas_size)
            self.data_rect = Graphics.fit_to_size(rect, self.data_shape)

    def map_point_image_norm_to_widget(self, p):
        if self.data_shape:
            return (float(p[0])*self.data_rect[1][0] + self.data_rect[0][0], float(p[1])*self.data_rect[1][1] + self.data_rect[0][1])
        return None

    def map_size_image_norm_to_widget(self, s):
        ms = self.map_point_image_norm_to_widget(s)
        ms0 = self.map_point_image_norm_to_widget((0,0))
        return (ms[0] - ms0[0], ms[1] - ms0[1])

    def map_size_image_to_image_norm(self, s):
        ms = self.map_point_image_to_image_norm(s)
        ms0 = self.map_point_image_to_image_norm((0,0))
        return (ms[0] - ms0[0], ms[1] - ms0[1])

    def map_point_widget_to_image_norm(self, p):
        if self.data_shape:
            p_image = self.map_point_widget_to_image(p)
            return (float(p_image[0]) / self.data_shape[0], float(p_image[1]) / self.data_shape[1])
        return None

    def map_point_widget_to_image(self, p):
        if self.data_rect and self.data_shape:
            if self.data_rect[1][0] != 0.0:
                image_y = self.data_shape[0] * (float(p[0]) - self.data_rect[0][0])/self.data_rect[1][0]
            else:
                image_y = 0
            if self.data_rect[1][1] != 0.0:
                image_x = self.data_shape[1] * (float(p[1]) - self.data_rect[0][1])/self.data_rect[1][1]
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
    def insert_index(self, new_index):
        new_indexes = set()
        for index in self.__indexes:
            if index < new_index:
                new_indexes.add(index)
            else:
                new_indexes.add(index+1)
        if self.__indexes != new_indexes:
            self.__indexes = new_indexes
            self._notify_listeners()
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
            self._notify_listeners()


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


class FocusRingCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(FocusRingCanvasItem, self).__init__()

        self.focused = False
        self.selected = False

    def _repaint(self, drawing_context):

        if self.selected:

            # canvas size
            canvas_width = self.canvas_size[0]
            canvas_height = self.canvas_size[1]

            stroke_style = "#CCC"  # TODO: platform dependent
            if self.focused:
                stroke_style = "#3876D6"  # TODO: platform dependent

            drawing_context.save()

            drawing_context.begin_path()
            drawing_context.rect(2, 2, canvas_width - 4, canvas_height - 4)
            drawing_context.line_join = "miter"
            drawing_context.stroke_style = stroke_style
            drawing_context.line_width = 4.0
            drawing_context.stroke()

            drawing_context.restore()


class LineGraphCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(LineGraphCanvasItem, self).__init__()
        self.data = None

    def _repaint(self, drawing_context):

        # draw the data, if any
        if (self.data is not None and len(self.data) > 0):

            # canvas size
            canvas_width = self.canvas_size[0]
            canvas_height = self.canvas_size[1]

            rect = ((0, 0), (canvas_height, canvas_width))

            drawing_context.save()

            drawing_context.begin_path()
            drawing_context.rect(rect[0][1], rect[0][0], rect[1][1], rect[1][0])
            drawing_context.fill_style = "#888"
            drawing_context.fill()

            data_min = numpy.amin(self.data)
            data_max = numpy.amax(self.data)
            data_len = self.data.shape[0]
            golden_ratio = 1.618
            display_rect = Graphics.fit_to_aspect_ratio(rect, golden_ratio)
            display_width = int(display_rect[1][1])
            display_height = int(display_rect[1][0])
            display_origin_x = int(display_rect[0][1])
            display_origin_y = int(display_rect[0][0])
            # draw the background
            drawing_context.begin_path()
            drawing_context.rect(display_origin_x, display_origin_y, display_width, display_height)
            drawing_context.fill_style = "#FFF"
            drawing_context.fill()
            # draw the line plot itself
            drawing_context.begin_path()
            drawing_context.move_to(display_origin_x, display_origin_y + display_height)
            for i in xrange(0, display_width,3):
                px = display_origin_x + i
                py = display_origin_y + display_height - (display_height * (float(self.data[int(data_len*float(i)/display_width)]) - data_min) / (data_max - data_min))
                drawing_context.line_to(px, py)
            drawing_context.line_to(display_origin_x + display_width-1, display_origin_y + display_height)
            drawing_context.close_path()
            drawing_context.fill_style = '#AFA'
            drawing_context.fill()
            drawing_context.line_width = 2
            drawing_context.line_cap = 'round'
            drawing_context.line_join = 'round'
            drawing_context.stroke_style = '#2A2'
            drawing_context.stroke()
            drawing_context.begin_path()
            drawing_context.rect(display_origin_x, display_origin_y, display_width, display_height)
            drawing_context.line_width = 1
            drawing_context.stroke_style = '#888'
            drawing_context.stroke()

            drawing_context.restore()


class BitmapCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(BitmapCanvasItem, self).__init__()
        self.rgba_bitmap_data = None

    def _repaint(self, drawing_context):

        # draw the data, if any
        if self.rgba_bitmap_data is not None:

            # canvas size
            canvas_width = self.canvas_size[0]
            canvas_height = self.canvas_size[1]

            if canvas_height > 0 and canvas_width > 0:

                image_size = self.rgba_bitmap_data.shape

                rect = ((0, 0), (canvas_height, canvas_width))

                display_rect = Graphics.fit_to_size(rect, image_size)

                drawing_context.save()

                drawing_context.begin_path()
                drawing_context.rect(rect[0][1], rect[0][0], rect[1][1], rect[1][0])
                drawing_context.fill_style = "#888"
                drawing_context.fill()

                if display_rect and display_rect[1][0] > 0 and display_rect[1][1] > 0:
                    drawing_context.draw_image(self.rgba_bitmap_data, display_rect[0][1], display_rect[0][0], display_rect[1][1], display_rect[1][0])

                drawing_context.restore()


class GraphicsCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(GraphicsCanvasItem, self).__init__()
        self.data_item = None

    def _repaint(self, drawing_context):

        if self.data_item:

            # canvas size
            canvas_width = self.canvas_size[0]
            canvas_height = self.canvas_size[1]

            widget_mapping = WidgetMapping(self.data_item.spatial_shape, (canvas_height, canvas_width))

            drawing_context.save()
            for graphic_index, graphic in enumerate(self.data_item.graphics):
                graphic.draw(drawing_context, widget_mapping, self.graphic_selection.contains(graphic_index))
            drawing_context.restore()


class InfoOverlayCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(InfoOverlayCanvasItem, self).__init__()
        self.data_item = None

    def _repaint(self, drawing_context):

        if self.data_item:

            # canvas size
            canvas_width = self.canvas_size[0]
            canvas_height = self.canvas_size[1]

            drawing_context.save()
            drawing_context.begin_path()

            if self.data_item.is_calibrated:  # display scale marker?
                origin = (canvas_height - 30, 20)
                scale_marker_width = 120
                scale_marker_height = 6
                widget_mapping = WidgetMapping(self.data_item.spatial_shape, (canvas_height, canvas_width))
                screen_pixel_per_image_pixel = widget_mapping.map_size_image_norm_to_widget((1, 1))[0] / self.data_item.spatial_shape[0]
                if screen_pixel_per_image_pixel > 0:
                    scale_marker_image_width = scale_marker_width / screen_pixel_per_image_pixel
                    calibrated_scale_marker_width = make_pretty(scale_marker_image_width * self.data_item.calibrations[0].scale)
                    # update the scale marker width
                    scale_marker_image_width = calibrated_scale_marker_width / self.data_item.calibrations[0].scale
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
                    drawing_context.fill_text(self.data_item.calibrations[0].convert_to_calibrated_size_str(scale_marker_image_width), origin[1], origin[0] - scale_marker_height - 4)
                    data_item_properties = self.data_item.properties
                    info_items = list()
                    voltage = data_item_properties.get("voltage", 0)
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

    def __init__(self, document_controller, image_panel):
        super(LinePlotCanvasItem, self).__init__()

        # ugh
        self.document_controller = document_controller
        self.image_panel = image_panel

        # create the child canvas items
        self.line_graph_canvas_item = LineGraphCanvasItem()
        self.focus_ring_canvas_item = FocusRingCanvasItem()

        # canvas items get added back to front
        self.add_canvas_item(self.line_graph_canvas_item)
        self.add_canvas_item(self.focus_ring_canvas_item)

        # a thread for updating
        self.__paint_thread = DataItemThread(lambda data_item: self.__update_data_item(data_item), 0.04)

    def close(self):
        self.__paint_thread.close()
        self.__paint_thread = None
        super(LinePlotCanvasItem, self).close()

    def mouse_clicked(self, x, y, modifiers):
        if super(LinePlotCanvasItem, self).mouse_clicked(x, y, modifiers):
            return True
        # activate this view. this has the side effect of grabbing focus.
        self.document_controller.selected_image_panel = self.image_panel

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
    def __set_data_item(self, data_item):
        self.__data_item = data_item
        if self.__data_item and self.__paint_thread:
            self.__paint_thread.update_data(data_item)
        else:
            self.line_graph_canvas_item.data = None
            self.line_graph_canvas_item.update()
            self.repaint_if_needed()
    data_item = property(__get_data_item, __set_data_item)

    # this method will be invoked from the paint thread.
    # data is calculated and then sent to the line graph canvas item.
    def __update_data_item(self, data_item):

        # make sure we have the correct data
        assert data_item is not None
        assert data_item.is_data_1d

        # grab the data values
        with data_item.create_data_accessor() as data_accessor:
            data = data_accessor.data
        assert data is not None

        # make sure complex becomes scalar
        data = Image.scalar_from_array(data)
        assert data is not None

        # make sure RGB becomes scalar
        if Image.is_data_rgb(data) or Image.is_data_rgba(data):
            # note 0=b, 1=g, 2=r, 3=a. calculate luminosity.
            data = 0.0722 * data[:,0] + 0.7152 * data[:,1] + 0.2126 * data[:,2]
        assert data is not None

        # update the line graph
        self.line_graph_canvas_item.data = data
        self.line_graph_canvas_item.update()

        self.repaint_if_needed()


# binding to the selected data item in the document controller
class CanvasItemDataItemBinding(DataItem.AbstractDataItemBinding):

    def __init__(self):
        super(CanvasItemDataItemBinding, self).__init__()

    # this message is received from the canvas item.
    def notify_data_item_changed(self, data_item):
        self.notify_listeners("data_item_changed", data_item)


class ImageCanvasItem(CanvasItem.CanvasItemComposition):

    def __init__(self, document_controller, image_panel):
        super(ImageCanvasItem, self).__init__()

        # ugh
        self.document_controller = document_controller
        self.image_panel = image_panel

        # create a data item binding for adornments to use
        self.data_item_binding = CanvasItemDataItemBinding()

        # create the child canvas items
        self.bitmap_canvas_item = BitmapCanvasItem()
        self.graphics_canvas_item = GraphicsCanvasItem()
        self.info_overlay_canvas_item = InfoOverlayCanvasItem()
        self.focus_ring_canvas_item = FocusRingCanvasItem()

        # canvas items get added back to front
        self.add_canvas_item(self.bitmap_canvas_item)
        self.add_canvas_item(self.graphics_canvas_item)
        self.add_canvas_item(self.info_overlay_canvas_item)
        self.add_canvas_item(self.focus_ring_canvas_item)

        # a thread for updating
        self.__paint_thread = DataItemThread(lambda data_item: self.__update_data_item(data_item), 0.04)

        # used for dragging graphic items
        self.graphic_drag_items = []
        self.graphic_drag_item = None
        self.graphic_part_data = {}
        self.graphic_drag_indexes = []
        self.graphic_selection = GraphicSelection()
        self.graphic_selection.add_listener(self)
        self.__last_mouse = None
        self.__mouse_in = False
        self.graphics_canvas_item.graphic_selection = self.graphic_selection

    def close(self):
        self.__paint_thread.close()
        self.__paint_thread = None
        self.graphic_selection.remove_listener(self)
        self.graphic_selection = None
        self.data_item_binding.close()
        super(ImageCanvasItem, self).close()

    def mouse_clicked(self, x, y, modifiers):
        if super(ImageCanvasItem, self).mouse_clicked(x, y, modifiers):
            return True
        # activate this view. this has the side effect of grabbing focus.
        self.document_controller.selected_image_panel = self.image_panel
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
                widget_mapping = WidgetMapping(self.data_item.spatial_shape, (self.canvas_size[1], self.canvas_size[0]))
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
        self.mouse_position_changed(0, 0, 0)
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
                widget_mapping = WidgetMapping(self.data_item.spatial_shape, (self.canvas_size[1], self.canvas_size[0]))
                graphic.adjust_part(widget_mapping, self.graphic_drag_start_pos, (y, x), part_data, modifiers)
                self.graphic_drag_changed = True
                self.graphics_canvas_item.update()
        self.graphics_canvas_item.repaint_if_needed()
        return True

    # ths message comes from the widget
    def key_pressed(self, key):
        if super(ImageCanvasItem, self).key_pressed(key):
            return True
        #logging.debug("text=%s key=%s mod=%s", key.text, hex(key.key), key.modifiers)
        if key.is_delete:
            all_graphics = self.data_item.graphics if self.data_item else []
            graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if self.graphic_selection.contains(graphic_index)]
            if len(graphics):
                self.document_controller.remove_graphic()
        return ImagePanelManager().key_pressed(self.image_panel, key)

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
    def __set_data_item(self, data_item):
        self.__data_item = data_item
        self.__update_cursor_info()
        self.data_item_binding.notify_data_item_changed(data_item)
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
    data_item = property(__get_data_item, __set_data_item)

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

    # map from widget coordinates to image coordinates
    def __map_widget_to_image(self, p):
        image_size = self.__get_image_size()
        transformed_image_rect = ((0, 0), image_size)  ### TODO: fix me ... self.transformed_image_rect
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

    def __update_cursor_info(self):
        pos = None
        image_size = self.__get_image_size()
        if self.__mouse_in and self.__last_mouse:
            if image_size and len(image_size) > 1:
                pos = self.__map_widget_to_image(self.__last_mouse)
            data_item = self.data_item
            graphics = data_item.graphics if data_item else None
            selected_graphics = [graphics[index] for index in self.graphic_selection.indexes] if graphics else []
            self.document_controller.notify_listeners("cursor_changed", self.data_item, pos, selected_graphics, image_size)

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



class ImagePanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(ImagePanel, self).__init__(document_controller, panel_id, _("Image Panel"))

        self.__data_panel_selection = DataItem.DataItemSpecifier()

        self.__weak_listeners = []

        self.__block_scrollers = False

        self.image_canvas_zoom = 1.0
        self.image_canvas_center = (0.5, 0.5)
        self.image_canvas_mode = "fit"
        self.image_canvas_preserve_pos = True
        # the first time that this object receives the viewport_changed message,
        # the canvas will be exactly the same size as the viewport. this variable
        # helps to avoid setting the scrollbar positions until after the canvas
        # size is set.
        self.image_canvas_first = True

        #self.image_canvas_scroll = self.ui.create_scroll_area_widget(properties={"stylesheet": "background: '#888'"})
        #self.image_canvas_scroll.content = self.image_canvas
        #self.image_canvas_scroll.on_viewport_changed = lambda rect: self.update_image_canvas_size()

        self.image_root_canvas_item = CanvasItem.RootCanvasItem(document_controller.ui)
        self.image_root_canvas_item.focusable = True
        self.image_root_canvas_item.on_focus_changed = lambda focused: self.set_focused(focused)
        self.image_canvas_item = ImageCanvasItem(document_controller, self)
        self.image_root_canvas_item.add_canvas_item(self.image_canvas_item)
        self.image_header_controller = Panel.HeaderWidgetController(self.ui)
        self.image_widget = self.ui.create_column_widget()
        self.image_widget.add(self.image_header_controller.canvas_widget)
        self.image_widget.add(self.image_root_canvas_item.canvas, fill=True)

        self.line_plot_root_canvas_item = CanvasItem.RootCanvasItem(document_controller.ui)
        self.line_plot_root_canvas_item.focusable = True
        self.line_plot_canvas_item = LinePlotCanvasItem(document_controller, self)
        self.line_plot_root_canvas_item.add_canvas_item(self.line_plot_canvas_item)
        self.line_plot_header_controller = Panel.HeaderWidgetController(self.ui)
        self.line_plot_widget = self.ui.create_column_widget()
        self.line_plot_widget.add(self.line_plot_header_controller.canvas_widget)
        self.line_plot_widget.add(self.line_plot_root_canvas_item.canvas, fill=True)

        self.widget = self.ui.create_stack_widget()
        self.widget.add(self.image_widget)
        self.widget.add(self.line_plot_widget)

        self.document_controller.register_image_panel(self)

        self.closed = False

    def close(self):
        self.closed = True
        self.image_root_canvas_item.close()
        self.line_plot_root_canvas_item.close()
        self.document_controller.unregister_image_panel(self)
        self.data_panel_selection = DataItem.DataItemSpecifier()  # required before destructing display thread
        super(ImagePanel, self).close()

    # return a dictionary that can be used to restore the content of this image panel
    def save_content(self):
        content = {}
        data_panel_selection = self.data_panel_selection
        if data_panel_selection.data_group and data_panel_selection.data_item:
            content["data-group"] = data_panel_selection.data_group.uuid
            content["data-item"] = data_panel_selection.data_item.uuid
        return content

    # restore content from dictionary and document controller
    def restore_content(self, content, document_controller):
        if "data-group" in content and "data-item" in content:
            data_group_uuid = content["data-group"]
            data_item_uuid = content["data-item"]
            data_group = DataGroup.get_data_group_in_container_by_uuid(document_controller.document_model, data_group_uuid)
            if data_group:
                data_item = document_controller.document_model.get_data_item_by_key(data_item_uuid)
                if data_item:
                    self.data_panel_selection = DataItem.DataItemSpecifier(data_group, data_item)

    def update_image_canvas_size(self):
        if self.closed: return  # argh
        if self.__block_scrollers: return  # argh2
        viewport_size = self.image_canvas_scroll.viewport[1]
        if viewport_size[0] == 0 or viewport_size[1] == 0: return
        if self.data_item:
            if self.data_item.is_data_2d:
                if self.image_canvas_mode == "fill":
                    spatial_size = self.data_item.spatial_shape
                    scale_h = float(spatial_size[1]) / viewport_size[1]
                    scale_v = float(spatial_size[0]) / viewport_size[0]
                    if scale_v < scale_h:
                        canvas_size = (viewport_size[0] * self.image_canvas_zoom, viewport_size[0] * spatial_size[1] / spatial_size[0] * self.image_canvas_zoom)
                    else:
                        canvas_size = (viewport_size[1] * spatial_size[0] / spatial_size[1] * self.image_canvas_zoom, viewport_size[1] * self.image_canvas_zoom)
                elif self.image_canvas_mode == "1:1":
                    canvas_size = self.data_item.spatial_shape
                    canvas_size = (canvas_size[0] * self.image_canvas_zoom, canvas_size[1] * self.image_canvas_zoom)
                else:  # fit
                    canvas_size = (viewport_size[0] * self.image_canvas_zoom, viewport_size[1] * self.image_canvas_zoom)
                old_block_scrollers = self.__block_scrollers
                self.__block_scrollers = True
                #logging.debug("before")
                #self.image_canvas_scroll.info()
                self.image_canvas.size = canvas_size
                #logging.debug("after")
                #self.image_canvas_scroll.info()
                if not self.image_canvas_first and self.image_canvas_preserve_pos:
# scroll bar has a range of 0 to canvas_size - viewport_size
# when scroll bar is minimum, viewport ranges from 0 to viewport_size/canvas_zoom
# when scroll bar is maximum, viewport ranges from (canvas_size - viewportsize)/canvas_zoom to canvas_size/canvas_zoom
# when scroll bar has value, viewport ranges from value/canvas_zoom to (value + viewport_size)/canvas_zoom
# and viewport center is (value + value + viewport_size)/2 / canvas_zoom = (value + viewport_size / 2) / canvas_zoom
# which means value = canvas_center * canvas_zoom - viewport_size / 2
# center = viewport_center / (canvas_size * canvas_zoom)
                    viewport_center = self.map_image_norm_to_widget(self.image_canvas_center)
                    h_range = canvas_size[1] - viewport_size[1]
                    v_range = canvas_size[0] - viewport_size[0]
                    h_offset = (viewport_center[1] - viewport_size[1]*0.5) / h_range if h_range else 0.0
                    v_offset = (viewport_center[0] - viewport_size[0]*0.5) / v_range if v_range else 0.0
                    h_offset = min(max(h_offset, 0.0), 1.0)
                    v_offset = min(max(v_offset, 0.0), 1.0)
                    #logging.debug("self.image_canvas_center %s", self.image_canvas_center)
                    #logging.debug("viewport_center %s", viewport_center)
                    #logging.debug("canvas_size %s  self.image_canvas_zoom %s", canvas_size, self.image_canvas_zoom)
                    #logging.debug("h_offset %s  v_offset %s", h_offset, v_offset)
                    self.image_canvas_scroll.scroll_to(h_offset, v_offset)
                    self.image_canvas_preserve_pos = False
                elif not self.image_canvas_first:
                    viewport = self.image_canvas_scroll.viewport
                    viewport_center = (viewport[0][0] + viewport[1][0]*0.5, viewport[0][1] + viewport[1][1]*0.5)
                    self.image_canvas_center = self.map_widget_to_image_norm(viewport_center)
                    #logging.debug("viewport %s", viewport)
                    #logging.debug("viewport_center %s", viewport_center)
                    #logging.debug("SET self.image_canvas_center %s", self.image_canvas_center)
                self.image_canvas_first = False
                self.__block_scrollers = old_block_scrollers
            else:
                self.image_canvas.size = viewport_size
        else:
            self.image_canvas.size = viewport_size
        self.display_changed()

    def set_selected(self, selected):
        if self.closed: return  # argh
        self.image_canvas_item.selected = selected
        self.line_plot_canvas_item.selected = selected

    def set_focused(self, focused):
        if self.closed: return  # argh
        self.image_canvas_item.focused = focused
        self.line_plot_canvas_item.focused = focused

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
        assert isinstance(data_panel_selection, DataItem.DataItemSpecifier)
        # track data item in this class to report changes
        if self.data_item_container:
            self.data_item_container.remove_listener(self)
            self.data_item_container.remove_ref()
        if self.data_item:
            self.data_item.remove_observer(self)
            self.data_item.remove_listener(self)
            self.data_item.remove_ref()
        if data_panel_selection and data_panel_selection.data_item:
            data_panel_selection.data_item.increment_accessor_count()
        if self.__data_panel_selection and self.__data_panel_selection.data_item:
            self.__data_panel_selection.data_item.decrement_accessor_count()
        self.__data_panel_selection = data_panel_selection
        # send out messages telling everyone we changed
        for weak_listener in self.__weak_listeners:
            listener = weak_listener()
            listener.data_panel_selection_changed_from_image_panel(data_panel_selection)
        self.data_item_changed(self.data_item, set([DataItem.SOURCE]))
        #self.update_image_canvas_size()
        # these connections should be configured after the messages above.
        # the instant these are added, we may be receiving messages from threads.
        data_item = self.data_item
        data_item_container = self.data_item_container
        if data_item:
            data_item.add_ref()
            data_item.add_listener(self)
            data_item.add_observer(self)  # watch for graphics being added/removed
        if data_item_container:
            data_item_container.add_ref()
            data_item_container.add_listener(self)
        # let the image panel manager know the data item changed
        ImagePanelManager().data_item_changed(self)
    data_panel_selection = property(__get_data_panel_selection, __set_data_panel_selection)


    # watch for changes to the graphic item list
    def item_inserted(self, object, key, value, before_index):
        self.image_canvas_item.item_inserted(object, key, value, before_index)
    def item_removed(self, object, key, value, index):
        self.image_canvas_item.item_removed(object, key, value, index)

    def data_item_removed(self, container, data_item, index):
        # if our item gets deleted, clear the selection
        if container == self.data_item_container and data_item == self.data_item:
            self.data_panel_selection = DataItem.DataItemSpecifier(self.__data_panel_selection.data_group)

    # tell our listeners the we changed.
    def notify_image_panel_data_item_changed(self, changes):
        for weak_listener in self.__weak_listeners:
            listener = weak_listener()
            listener.image_panel_data_item_changed(self, changes)

    # this will result in data_item_changed being called when the data item changes.
    def add_listener(self, listener):
        self.__weak_listeners.append(weakref.ref(listener))

    def remove_listener(self, listener):
        self.__weak_listeners.remove(weakref.ref(listener))

    # this message comes from the data item associated with this panel.
    # the connection is established in __set_data_item via data_item.add_listener.
    def data_item_changed(self, data_item, changes):
        if data_item == self.data_item:  # we can get messages from our source data items too
            self.notify_image_panel_data_item_changed(changes)
            self.image_header_controller.title = str(data_item)
            self.line_plot_header_controller.title = str(data_item)
            selected = self.document_controller.selected_image_panel == self
            if data_item:
                if data_item.is_data_1d:
                    self.widget.current_index = 1
                    self.line_plot_canvas_item.data_item = data_item
                    self.line_plot_canvas_item.selected = selected
                    self.image_canvas_item.data_item = None
                    self.image_canvas_item.selected = False
                elif data_item.is_data_2d:
                    self.widget.current_index = 0
                    self.image_canvas_item.data_item = data_item
                    self.image_canvas_item.selected = selected
                    self.line_plot_canvas_item.data_item = None
                    self.line_plot_canvas_item.selected = False
            else:
                self.image_canvas_item.data_item = None
                self.image_canvas_item.selected = False
                self.line_plot_canvas_item.data_item = None
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

    # map from image coordinates to widget coordinates
    def map_image_to_widget(self, p):
        image_size = self.image_size
        if image_size:
            return self.map_image_norm_to_widget((float(p[0])/image_size[0], float(p[1])/image_size[1]))
        return None

    # map from image normalized coordinates to widget coordinates
    def map_image_norm_to_widget(self, p):
        image_size = self.image_size
        transformed_image_rect = ((0, 0), image_size)  ### TODO: fix me ... self.transformed_image_rect
        if transformed_image_rect:
            return (p[0]*transformed_image_rect[1][0] + transformed_image_rect[0][0], p[1]*transformed_image_rect[1][1] + transformed_image_rect[0][1])
        return None

    # map from widget coordinates to image coordinates
    def map_widget_to_image(self, p):
        image_size = self.image_size
        transformed_image_rect = ((0, 0), image_size)  ### TODO: fix me ... self.transformed_image_rect
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

    # map from widget coordinates to image normalized coordinates
    def map_widget_to_image_norm(self, p):
        image_size = self.image_size
        if image_size:
            p_image = self.map_widget_to_image(p)
            return (float(p_image[0]) / image_size[0], float(p_image[1]) / image_size[1])
        return None

    # map from image normalized coordinates to image coordinates
    def map_image_norm_to_image(self, p):
        image_size = self.image_size
        if image_size:
            return (p[0] * image_size[0], p[1] * image_size[1])
        return None

    # map from image normalized coordinates to image coordinates
    def map_image_to_image_norm(self, p):
        image_size = self.image_size
        if image_size:
            return (p[0] / image_size[0], p[1] / image_size[1])
        return None

    def __set_fit_mode(self):
        #logging.debug("---------> fit")
        self.image_canvas_mode = "fit"
        self.image_canvas_preserve_pos = True
        self.image_canvas_zoom = 1.0
        self.image_canvas_center = (0.5, 0.5)
        #self.update_image_canvas_size()

    def __set_fill_mode(self):
        #logging.debug("---------> fill")
        self.image_canvas_mode = "fill"
        self.image_canvas_preserve_pos = True
        self.image_canvas_zoom = 1.0
        self.image_canvas_center = (0.5, 0.5)
        #self.update_image_canvas_size()

    def __set_one_to_one_mode(self):
        #logging.debug("---------> 1:1")
        self.image_canvas_mode = "1:1"
        self.image_canvas_preserve_pos = True
        self.image_canvas_zoom = 1.0
        self.image_canvas_center = (0.5, 0.5)
        #self.update_image_canvas_size()

    def __zoom_in(self):
        self.image_canvas_zoom = self.image_canvas_zoom * 1.05
        self.image_canvas_preserve_pos = True
        #self.update_image_canvas_size()

    def __zoom_out(self):
        self.image_canvas_zoom = self.image_canvas_zoom / 1.05
        self.image_canvas_preserve_pos = True
        #self.update_image_canvas_size()

    def __show_data_source(self):
        data_source = self.data_item.data_source
        if data_source:
            self.data_panel_selection = DataItem.DataItemSpecifier(self.__data_panel_selection.data_group, data_source)

    # ths message comes from the widget
    def key_pressed(self, key):
        #logging.debug("text=%s key=%s mod=%s", key.text, hex(key.key), key.modifiers)
        if key.is_delete:
            all_graphics = self.data_item.graphics if self.data_item else []
            graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if self.graphic_selection.contains(graphic_index)]
            if len(graphics):
                self.document_controller.remove_graphic()
        if key.text == "-":
            self.__zoom_out()
        if key.text == "+":
            self.__zoom_in()
        if key.text == "1":
            self.__set_one_to_one_mode()
        if key.text == "0":
            self.__set_fit_mode()
        if key.text == ")":
            self.__set_fill_mode()
        if key.text == "o":
            self.__show_data_source()

        return ImagePanelManager().key_pressed(self, key)


# image panel manager acts as a broker for significant events occurring
# regarding image panels. listeners can attach themselves to this object
# and receive messages regarding image panels. for instance, when the user
# presses a key on an image panel that isn't handled directly by the image
# panel, listeners can be advised of this event.
@singleton
class ImagePanelManager(object):
    def __init__(self):
        self.__weak_listeners = []
    # implement listener architecture
    def notify_listeners(self, fn, *args, **keywords):
        try:
            listeners = [weak_listener() for weak_listener in self.__weak_listeners]
            for listener in listeners:
                if hasattr(listener, fn):
                    if getattr(listener, fn)(*args, **keywords):
                        return True
            return False
        except Exception as e:
            import traceback
            traceback.print_exc()
            logging.debug("Notify Error: %s", e)
    def add_listener(self, listener):
        self.__weak_listeners.append(weakref.ref(listener))
    def remove_listener(self, listener):
        self.__weak_listeners.remove(weakref.ref(listener))
    # events from the image panels
    def key_pressed(self, image_panel, key):
        return self.notify_listeners("image_panel_key_pressed", image_panel, key)
    def data_item_changed(self, image_panel):
        self.notify_listeners("image_panel_data_item_changed", image_panel)


class InfoPanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(InfoPanel, self).__init__(document_controller, panel_id, _("Info"))

        ui = document_controller.ui

        self.closed = False

        self.__pending_info = None
        self.__pending_info_mutex = threading.RLock()

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

        # connect self as listener. this will result in calls to selected_data_item_changed and cursor_changed
        self.document_controller.add_listener(self)

    def close(self):
        self.closed = True
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # finish closing
        super(InfoPanel, self).close()

    def periodic(self):
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
    def cursor_changed(self, data_item, pos, selected_graphics, image_size):
        position_text = ""
        value_text = ""
        graphic_text = ""
        if data_item and image_size:
            calibrations = data_item.calculated_calibrations
            if pos:
                # make sure the position is within the bounds of the image
                if pos[0] >= 0 and pos[0] < image_size[0] and pos[1] >= 0 and pos[1] < image_size[1]:
                    position_text = u"{0},{1}".format(calibrations[1].convert_to_calibrated_value_str(pos[1] - 0.5 * image_size[1]),
                                                     calibrations[0].convert_to_calibrated_value_str(0.5 * image_size[0] - pos[0]))
                    value = data_item.get_data_value(pos)
                    if isinstance(value, numbers.Integral):
                        value_text = '{0:d}'.format(value)
                    elif isinstance(value, numbers.Real) or isinstance(value, numbers.Complex):
                        value_text = '{0:f}'.format(value)
                    elif value is None:
                        value_text = _("N/A")
                    else:
                        value_text = str(value)
            if len(selected_graphics) == 1:
                graphic = selected_graphics[0]
                graphic_text = graphic.calibrated_description(image_size, calibrations)
        with self.__pending_info_mutex:
            self.__pending_info = (position_text, value_text, graphic_text)


# make val into a pretty number
def make_pretty(val):
    factor10 = math.pow(10, int(math.log10(abs(val))))
    val_norm = val/factor10
    if val_norm < 1.0:
        val_norm = val_norm * 10
        factor10 = factor10 / 10
    # val_norm is now between 1 and 10
    if val_norm < 5.0:
        return 0.5 * round(val_norm/0.5) * factor10
    else:
        return round(val_norm) * factor10
