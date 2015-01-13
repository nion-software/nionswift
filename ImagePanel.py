# standard libraries
import collections
import copy
import gettext
import logging
import math
import threading
import uuid
import weakref

# third party libraries

# local libraries
from nion.swift import Decorators
from nion.swift import Panel
from nion.swift.model import Calibration
from nion.swift.model import DataItem
from nion.swift.model import DataItemsBinding
from nion.swift.model import Display
from nion.swift.model import Graphics
from nion.swift.model import HardwareSource
from nion.swift.model import Image
from nion.swift.model import LineGraphCanvasItem
from nion.swift.model import Region
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.ui import Geometry
from nion.ui import Observable
from nion.ui import ThreadPool

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
# move while dragging                   spacebar-drag
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


class WidgetChannelMapping(object):

    def __init__(self, data_size, plot_rect, left_channel, right_channel):
        self.__data_size = data_size
        self.__plot_rect = plot_rect
        self.__left_channel = left_channel
        self.__right_channel = right_channel
        self.__drawn_channel_per_pixel = float(right_channel - left_channel) / plot_rect.width

    def map_point_widget_to_channel_norm(self, pos):
        return (self.__left_channel + (pos.x - self.__plot_rect.left) * self.__drawn_channel_per_pixel) / self.__data_size[0]

    def map_point_channel_norm_to_widget(self, x):
        return (x * self.__data_size[0] - self.__left_channel) / self.__drawn_channel_per_pixel + self.__plot_rect.left

    def map_point_channel_norm_to_channel(self, x):
        return x * self.__data_size[0]


class WidgetImageMapping(object):

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
        p = Geometry.FloatPoint.make(p)
        if self.data_shape:
            return Geometry.FloatPoint(y=p.y * self.canvas_rect.height + self.canvas_rect.top, x=p.x * self.canvas_rect.width + self.canvas_rect.left)
        return None

    def map_size_image_norm_to_widget(self, s):
        ms = self.map_point_image_norm_to_widget(s)
        ms0 = self.map_point_image_norm_to_widget((0, 0))
        return ms - ms0

    def map_size_image_to_image_norm(self, s):
        ms = self.map_point_image_to_image_norm(s)
        ms0 = self.map_point_image_to_image_norm((0, 0))
        return ms - ms0

    def map_size_widget_to_image_norm(self, s):
        ms = self.map_point_widget_to_image_norm(s)
        ms0 = self.map_point_widget_to_image_norm((0, 0))
        return ms - ms0

    def map_point_widget_to_image_norm(self, p):
        if self.data_shape:
            p = Geometry.FloatPoint.make(p)
            p_image = self.map_point_widget_to_image(p)
            return Geometry.FloatPoint(y=p_image.y / self.data_shape[0], x=p_image.x / self.data_shape[1])
        return None

    def map_point_widget_to_image(self, p):
        if self.canvas_rect and self.data_shape:
            p = Geometry.FloatPoint.make(p)
            if self.canvas_rect.height != 0.0:
                image_y = self.data_shape[0] * (p.y - self.canvas_rect.top) / self.canvas_rect.height
            else:
                image_y = 0.0
            if self.canvas_rect.width != 0.0:
                image_x = self.data_shape[1] * (p.x - self.canvas_rect.left) / self.canvas_rect.width
            else:
                image_x = 0.0
            return Geometry.FloatPoint(y=image_y, x=image_x)  # c-indexing
        return None

    def map_point_image_norm_to_image(self, p):
        if self.data_shape:
            p = Geometry.FloatPoint.make(p)
            return Geometry.FloatPoint(y=p.y * self.data_shape[0], x=p.x * self.data_shape[1])
        return None

    def map_point_image_to_image_norm(self, p):
        if self.data_shape:
            p = Geometry.FloatPoint.make(p)
            return Geometry.FloatPoint(y=p.y / self.data_shape[0], x=p.x / self.data_shape[1])
        return None


class GraphicsCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(GraphicsCanvasItem, self).__init__()
        self.display = None

    def _repaint(self, drawing_context):

        display = self.display

        if display:

            widget_mapping = WidgetImageMapping(display.preview_2d_shape, (0, 0), self.canvas_size)

            drawing_context.save()
            for graphic_index, graphic in enumerate(display.drawn_graphics):
                graphic.draw(drawing_context, widget_mapping, display.graphic_selection.contains(graphic_index))
            drawing_context.restore()


class InfoOverlayCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(InfoOverlayCanvasItem, self).__init__()
        self.data_item = None
        self.display = None
        self.__image_canvas_size = None  # this will be updated by the container
        self.__image_canvas_origin = None  # this will be updated by the container

    def __get_image_canvas_size(self):
        return self.__image_canvas_size

    def __set_image_canvas_size(self, image_canvas_size):
        self.__image_canvas_size = image_canvas_size
        self.update()

    image_canvas_size = property(__get_image_canvas_size, __set_image_canvas_size)

    def __get_image_canvas_origin(self):
        return self.__image_canvas_origin

    def __set_image_canvas_origin(self, image_canvas_origin):
        self.__image_canvas_origin = image_canvas_origin
        self.update()

    image_canvas_origin = property(__get_image_canvas_origin, __set_image_canvas_origin)

    def _repaint(self, drawing_context):

        data_item = self.data_item
        display = self.display

        if display:

            # canvas size
            canvas_height = self.canvas_size[0]

            drawing_context.save()
            drawing_context.begin_path()

            image_canvas_size = self.image_canvas_size
            image_canvas_origin = self.image_canvas_origin
            calibrations = display.data_and_calibration.dimensional_calibrations
            if calibrations is not None and image_canvas_origin is not None and image_canvas_size is not None:  # display scale marker?
                origin = (canvas_height - 30, 20)
                scale_marker_width = 120
                scale_marker_height = 6
                widget_mapping = WidgetImageMapping(display.preview_2d_shape, image_canvas_origin, image_canvas_size)
                screen_pixel_per_image_pixel = widget_mapping.map_size_image_norm_to_widget((1, 1))[0] / display.preview_2d_shape[0]
                if screen_pixel_per_image_pixel > 0:
                    scale_marker_image_width = scale_marker_width / screen_pixel_per_image_pixel
                    calibrated_scale_marker_width = Geometry.make_pretty(scale_marker_image_width * calibrations[1].scale)
                    # update the scale marker width
                    scale_marker_image_width = calibrated_scale_marker_width / calibrations[1].scale
                    scale_marker_width = scale_marker_image_width * screen_pixel_per_image_pixel
                    drawing_context.begin_path()
                    drawing_context.move_to(origin[1], origin[0])
                    drawing_context.line_to(origin[1] + scale_marker_width, origin[0])
                    drawing_context.line_to(origin[1] + scale_marker_width, origin[0] - scale_marker_height)
                    drawing_context.line_to(origin[1], origin[0] - scale_marker_height)
                    drawing_context.close_path()
                    drawing_context.fill_style = "#448"
                    drawing_context.fill()
                    drawing_context.stroke_style = "#000"
                    drawing_context.stroke()
                    drawing_context.font = "normal 14px serif"
                    drawing_context.text_baseline = "bottom"
                    drawing_context.fill_style = "#FFF"
                    drawing_context.fill_text(calibrations[1].convert_to_calibrated_size_str(scale_marker_image_width), origin[1], origin[0] - scale_marker_height - 4)
                    data_item_properties = data_item.get_metadata("hardware_source")
                    info_items = list()
                    voltage = data_item_properties.get("extra_high_tension", 0)
                    if voltage:
                        units = "V"
                        if voltage % 1000 == 0:
                            voltage /= 1000
                            units = "kV"
                        info_items.append("{0} {1}".format(voltage, units))
                    source = data_item_properties.get("hardware_source")
                    if source:
                        info_items.append(str(source))
                    drawing_context.fill_text(" ".join(info_items), origin[1], origin[0] - scale_marker_height - 4 - 20)

            drawing_context.restore()


class LinePlotCanvasItem(CanvasItem.CanvasItemComposition):

    def __init__(self, delegate):
        super(LinePlotCanvasItem, self).__init__()

        self.delegate = delegate

        self.wants_mouse_events = True

        font_size = 12

        self.line_graph_canvas_area_item = CanvasItem.CanvasItemComposition()
        self.line_graph_canvas_item = LineGraphCanvasItem.LineGraphCanvasItem()
        self.line_graph_regions_canvas_item = LineGraphCanvasItem.LineGraphRegionsCanvasItem()
        self.line_graph_canvas_area_item.add_canvas_item(self.line_graph_canvas_item)
        self.line_graph_canvas_area_item.add_canvas_item(self.line_graph_regions_canvas_item)

        self.line_graph_vertical_axis_label_canvas_item = LineGraphCanvasItem.LineGraphVerticalAxisLabelCanvasItem()
        self.line_graph_vertical_axis_scale_canvas_item = LineGraphCanvasItem.LineGraphVerticalAxisScaleCanvasItem()
        self.line_graph_vertical_axis_ticks_canvas_item = LineGraphCanvasItem.LineGraphVerticalAxisTicksCanvasItem()
        self.line_graph_vertical_axis_group_canvas_item = CanvasItem.CanvasItemComposition()
        self.line_graph_vertical_axis_group_canvas_item.layout = CanvasItem.CanvasItemRowLayout(spacing=4)
        self.line_graph_vertical_axis_group_canvas_item.add_canvas_item(self.line_graph_vertical_axis_label_canvas_item)
        self.line_graph_vertical_axis_group_canvas_item.add_canvas_item(self.line_graph_vertical_axis_scale_canvas_item)
        self.line_graph_vertical_axis_group_canvas_item.add_canvas_item(self.line_graph_vertical_axis_ticks_canvas_item)

        self.line_graph_horizontal_axis_label_canvas_item = LineGraphCanvasItem.LineGraphHorizontalAxisLabelCanvasItem()
        self.line_graph_horizontal_axis_scale_canvas_item = LineGraphCanvasItem.LineGraphHorizontalAxisScaleCanvasItem()
        self.line_graph_horizontal_axis_ticks_canvas_item = LineGraphCanvasItem.LineGraphHorizontalAxisTicksCanvasItem()
        self.line_graph_horizontal_axis_group_canvas_item = CanvasItem.CanvasItemComposition()
        self.line_graph_horizontal_axis_group_canvas_item.layout = CanvasItem.CanvasItemColumnLayout(spacing=4)
        self.line_graph_horizontal_axis_group_canvas_item.add_canvas_item(self.line_graph_horizontal_axis_ticks_canvas_item)
        self.line_graph_horizontal_axis_group_canvas_item.add_canvas_item(self.line_graph_horizontal_axis_scale_canvas_item)
        self.line_graph_horizontal_axis_group_canvas_item.add_canvas_item(self.line_graph_horizontal_axis_label_canvas_item)

        # create the grid item holding the line graph and each axes label
        self.line_graph_group_canvas_item = CanvasItem.CanvasItemComposition()
        margins = Geometry.Margins(left=6, right=12, top=font_size + 4, bottom=6)
        self.line_graph_group_canvas_item.layout = CanvasItem.CanvasItemGridLayout(Geometry.IntSize(2, 2), margins=margins)
        self.line_graph_group_canvas_item.add_canvas_item(self.line_graph_vertical_axis_group_canvas_item, Geometry.IntPoint(x=0, y=0))
        self.line_graph_group_canvas_item.add_canvas_item(self.line_graph_canvas_area_item, Geometry.IntPoint(x=1, y=0))
        self.line_graph_group_canvas_item.add_canvas_item(self.line_graph_horizontal_axis_group_canvas_item, Geometry.IntPoint(x=1, y=1))

        # draw the background
        self.line_graph_background_canvas_item = CanvasItem.CanvasItemComposition()
        #self.line_graph_background_canvas_item.sizing.minimum_aspect_ratio = 1.5  # note: no maximum aspect ratio; line plot looks nice wider.
        self.line_graph_background_canvas_item.add_canvas_item(CanvasItem.BackgroundCanvasItem("#FFF"))
        self.line_graph_background_canvas_item.add_canvas_item(self.line_graph_group_canvas_item)

        # canvas items get added back to front
        # create the child canvas items
        # the background
        self.add_canvas_item(CanvasItem.BackgroundCanvasItem())
        self.add_canvas_item(self.line_graph_background_canvas_item)

        # thread for drawing
        self.__data_item = None
        self.__buffered_data_source = None
        self.__display = None
        self.__prepare_data_thread = ThreadPool.ThreadDispatcher(lambda: self.prepare_display_on_thread())
        self.__prepare_data_thread.start()

        self.preferred_aspect_ratio = 1.618  # the golden ratio

        # used for dragging graphic items
        self.graphic_drag_items = []
        self.graphic_drag_item = None
        self.graphic_part_data = {}
        self.graphic_drag_indexes = []
        self.__last_mouse = None
        self.__mouse_in = False
        self.__tracking_selections = False
        self.__tracking_horizontal = False
        self.__tracking_vertical = False

        self.__data_info = None

    def close(self):
        if self.__prepare_data_thread:
            self.__prepare_data_thread.close()
            self.__prepare_data_thread = None
        self.update_display(DataItem.DisplaySpecifier())
        self.delegate.clear_task("prepare")
        # call super
        super(LinePlotCanvasItem, self).close()

    def about_to_close(self):
        # message received when image panel closes; otherwise thread is shut down when parent canvas item closes
        if self.__prepare_data_thread:
            self.__prepare_data_thread.close()
            self.__prepare_data_thread = None

    # when the display changes, set the data using this property.
    # doing this will queue an item in the paint thread to repaint.
    def __get_display(self):
        return self.__display
    display = property(__get_display)

    def update_display(self, display_specifier):
        """ Update the display (model) associated with this canvas item. """
        data_item, buffered_data_source, display = display_specifier.data_item, display_specifier.buffered_data_source, display_specifier.display
        # first take care of listeners and update the __display field
        old_display = self.__display
        if old_display and display != old_display:
            old_display.remove_listener(self)
        self.__data_item = data_item
        self.__buffered_data_source = buffered_data_source
        self.__display = display
        if display and display != old_display:
            display.add_listener(self)  # for display_graphic_selection_changed
        # next get rid of data associated with canvas items
        if self.__display is None:
            # handle case where display is empty
            data_info = LineGraphCanvasItem.LineGraphDataInfo()
            self.__update_data_info(data_info)
            self.line_graph_regions_canvas_item.regions = list()
        else:
            self.display_graphic_selection_changed(self.__display, self.__display.graphic_selection)
        # update the cursor info
        self.__update_cursor_info()
        # finally, trigger the paint thread (if there still is one) to update
        if self.__prepare_data_thread:
            self.__prepare_data_thread.trigger()

    def wait_for_prepare_data(self):
        self.__prepare_data_thread.trigger(wait=True)

    def display_graphic_selection_changed(self, display, graphic_selection):
        # this message will come directly from the display when the graphic selection changes
        regions = list()
        display = self.display
        data_and_calibration = display.data_and_calibration
        data_length = data_and_calibration.dimensional_shape[0]
        spatial_calibration = data_and_calibration.dimensional_calibrations[0] if display.display_calibrated_values else Calibration.Calibration()
        calibrated_data_left = spatial_calibration.convert_to_calibrated_value(0)
        calibrated_data_right = spatial_calibration.convert_to_calibrated_value(data_length)
        calibrated_data_left, calibrated_data_right = min(calibrated_data_left, calibrated_data_right), max(calibrated_data_left, calibrated_data_right)
        graph_left, graph_right, ticks, division, precision = Geometry.make_pretty_range(calibrated_data_left, calibrated_data_right)

        def convert_to_calibrated_value_str(f):
            return (u"{0:0." + u"{0:d}".format(precision+2) + "f}").format(f)

        for graphic_index, graphic in enumerate(self.__display.drawn_graphics):
            graphic_start, graphic_end = graphic.start, graphic.end
            graphic_start, graphic_end = min(graphic_start, graphic_end), max(graphic_start, graphic_end)
            left_channel = graphic_start * data_length
            right_channel = graphic_end * data_length
            left_text = convert_to_calibrated_value_str(spatial_calibration.convert_to_calibrated_value(left_channel))
            right_text = convert_to_calibrated_value_str(spatial_calibration.convert_to_calibrated_value(right_channel))
            middle_text = convert_to_calibrated_value_str(spatial_calibration.convert_to_calibrated_size(right_channel - left_channel))
            RegionInfo = collections.namedtuple("RegionInfo", ["channels", "selected", "index", "left_text", "right_text", "middle_text"])
            region = RegionInfo((graphic_start, graphic_end), graphic_selection.contains(graphic_index), graphic_index, left_text, right_text, middle_text)
            regions.append(region)
        self.line_graph_regions_canvas_item.regions = regions
        self.line_graph_regions_canvas_item.update()

    # this method will be invoked from the paint thread.
    # data is calculated and then sent to the line graph canvas items.
    def prepare_display_on_thread(self):

        display = self.__display

        if display:

            # grab the data item
            data_and_calibration = display.data_and_calibration

            # make sure we have the correct data
            assert display is not None
            assert data_and_calibration.is_data_1d

            # grab the data values
            data = data_and_calibration.data

            if data is not None:
                # make sure complex becomes scalar
                data = Image.scalar_from_array(data)
                assert data is not None

                # make sure RGB becomes scalar
                data = Image.convert_to_grayscale(data)
                assert data is not None

                # update the line graph data
                y_min = display.y_min
                y_max = display.y_max
                left_channel = display.left_channel
                right_channel = display.right_channel
                left_channel = left_channel if left_channel is not None else 0
                right_channel = right_channel if right_channel is not None else data.shape[0]
                left_channel, right_channel = min(left_channel, right_channel), max(left_channel, right_channel)
                dimensional_calibration = data_and_calibration.dimensional_calibrations[0] if display.display_calibrated_values else None
                intensity_calibration = data_and_calibration.intensity_calibration if display.display_calibrated_values else None
                data_info = LineGraphCanvasItem.LineGraphDataInfo(data, y_min, y_max, left_channel, right_channel,
                                                                  dimensional_calibration, intensity_calibration)
            else:
                data_info = LineGraphCanvasItem.LineGraphDataInfo()

            def update_data_info():
                self.__update_data_info(data_info)

            self.delegate.add_task("prepare", update_data_info)

    def __update_data_info(self, data_info):
        # the display has been changed, so this method has been called. it must be called on the ui thread.
        # data_info is a new copy of data info. it will be owned by this line plot after calling this method.
        # this method stores the data_info into each line plot canvas item and updates the canvas item.
        self.line_graph_canvas_item.data_info = data_info
        # self.line_graph_canvas_item.update()  # unused, setting data_info handles this automatically
        self.line_graph_regions_canvas_item.data_info = data_info
        self.line_graph_regions_canvas_item.update()
        self.line_graph_vertical_axis_label_canvas_item.data_info = data_info
        self.line_graph_vertical_axis_label_canvas_item.size_to_content()
        self.line_graph_vertical_axis_label_canvas_item.update()
        self.line_graph_vertical_axis_scale_canvas_item.data_info = data_info
        self.line_graph_vertical_axis_scale_canvas_item.size_to_content(self.delegate.image_panel_get_font_metrics)
        self.line_graph_vertical_axis_scale_canvas_item.update()
        self.line_graph_vertical_axis_ticks_canvas_item.data_info = data_info
        self.line_graph_vertical_axis_ticks_canvas_item.update()
        self.line_graph_horizontal_axis_label_canvas_item.data_info = data_info
        self.line_graph_horizontal_axis_label_canvas_item.size_to_content()
        self.line_graph_horizontal_axis_label_canvas_item.update()
        self.line_graph_horizontal_axis_scale_canvas_item.data_info = data_info
        self.line_graph_horizontal_axis_scale_canvas_item.update()
        self.line_graph_horizontal_axis_ticks_canvas_item.data_info = data_info
        self.line_graph_horizontal_axis_ticks_canvas_item.update()
        self.refresh_layout()
        self.__data_info = data_info

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

    def mouse_double_clicked(self, x, y, modifiers):
        if super(LinePlotCanvasItem, self).mouse_clicked(x, y, modifiers):
            return True
        if self.delegate.image_panel_get_tool_mode() == "pointer":
            pos = Geometry.IntPoint(x=x, y=y)
            if self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_horizontal_axis_group_canvas_item)):
                self.reset_horizontal()
                return True
            elif self.line_graph_vertical_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_vertical_axis_group_canvas_item)):
                self.reset_vertical()
                return True
        return False

    def mouse_position_changed(self, x, y, modifiers):
        if super(LinePlotCanvasItem, self).mouse_position_changed(x, y, modifiers):
            return True
        self.__last_mouse = Geometry.IntPoint(x=x, y=y)
        self.__update_cursor_info()
        new_rescale = modifiers.control
        if self.__tracking_horizontal and self.__tracking_rescale != new_rescale:
            self.end_tracking(modifiers)
            self.begin_tracking_horizontal(Geometry.IntPoint(x=x, y=y), rescale=new_rescale)
        elif self.__tracking_vertical and self.__tracking_rescale != new_rescale:
            self.end_tracking(modifiers)
            self.begin_tracking_vertical(Geometry.IntPoint(x=x, y=y), rescale=new_rescale)
        return self.continue_tracking(Geometry.IntPoint(x=x, y=y), modifiers)

    def mouse_pressed(self, x, y, modifiers):
        if super(LinePlotCanvasItem, self).mouse_pressed(x, y, modifiers):
            return True
        pos = Geometry.IntPoint(x=x, y=y)
        data_item = self.__data_item
        display = self.__display
        if not display:
            return False
        data_item.begin_transaction()
        if self.delegate.image_panel_get_tool_mode() == "pointer":
            if self.line_graph_regions_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_regions_canvas_item)):
                self.begin_tracking_regions(pos, modifiers)
                return True
            elif self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_horizontal_axis_group_canvas_item)):
                self.begin_tracking_horizontal(pos, rescale=modifiers.control)
                return True
            elif self.line_graph_vertical_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_vertical_axis_group_canvas_item)):
                self.begin_tracking_vertical(pos, rescale=modifiers.control)
                return True
        elif self.delegate.image_panel_get_tool_mode() == "interval":
            if self.line_graph_regions_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_regions_canvas_item)):
                data_size = self.__get_data_size()
                if data_size and len(data_size) == 1:
                    widget_mapping = self.__get_mouse_mapping()
                    x = widget_mapping.map_point_widget_to_channel_norm(pos)
                    region = Region.IntervalRegion()
                    region.start = x
                    region.end = x
                    data_item.add_region(region)  # this will also make a drawn graphic
                    # hack to select it. it will be the last item.
                    display.graphic_selection.set(len(display.drawn_graphics) - 1)
                    self.begin_tracking_regions(pos, Graphics.NullModifiers())
                return True
        return False

    def mouse_released(self, x, y, modifiers):
        if super(LinePlotCanvasItem, self).mouse_released(x, y, modifiers):
            return True
        self.end_tracking(modifiers)
        data_item = self.__data_item
        display = self.__display
        if display:
            data_item.end_transaction()
        return False

    def context_menu_event(self, x, y, gx, gy):
        self.delegate.image_panel_show_context_menu(gx, gy)
        return True

    # ths message comes from the widget
    def key_pressed(self, key):
        if super(LinePlotCanvasItem, self).key_pressed(key):
            return True
        # only handle keys if we're directly embedded in an image panel
        if not self.delegate:
            return False
        if key.is_delete:
            self.delegate.image_panel_delete_key_pressed()
            return True
        display = self.display
        if display:
            #logging.debug("text=%s key=%s mod=%s", key.text, hex(key.key), key.modifiers)
            all_graphics = display.drawn_graphics
            graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if display.graphic_selection.contains(graphic_index)]
            if len(graphics):
                if key.is_arrow:
                    widget_mapping = self.__get_mouse_mapping()
                    amount = 10.0 if key.modifiers.shift else 1.0
                    if key.is_left_arrow:
                        for graphic in graphics:
                            graphic.nudge(widget_mapping, (0, -amount))
                    elif key.is_right_arrow:
                        for graphic in graphics:
                            graphic.nudge(widget_mapping, (0, amount))
                    return True
        return self.delegate.image_panel_key_pressed(key)

    def reset_horizontal(self):
        self.__display.left_channel = None
        self.__display.right_channel = None

    def reset_vertical(self):
        self.__display.y_min = None
        self.__display.y_max = None

    def __get_mouse_mapping(self):
        data_size = self.__get_data_size()
        plot_origin = self.line_graph_regions_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
        plot_rect = self.line_graph_regions_canvas_item.canvas_bounds.translated(plot_origin)
        left_channel = self.__data_info.drawn_left_channel
        right_channel = self.__data_info.drawn_right_channel
        return WidgetChannelMapping(data_size, plot_rect, left_channel, right_channel)

    def begin_tracking_regions(self, pos, modifiers):
        data_size = self.__get_data_size()
        display = self.display
        if display and data_size and len(data_size) == 1:
            self.__tracking_selections = True
            drawn_graphics = display.drawn_graphics
            for graphic_index, graphic in enumerate(drawn_graphics):
                start_drag_pos = Geometry.IntPoint.make(pos)
                already_selected = display.graphic_selection.contains(graphic_index)
                multiple_items_selected = len(display.graphic_selection.indexes) > 1
                move_only = not already_selected or multiple_items_selected
                widget_mapping = self.__get_mouse_mapping()
                part = graphic.test(widget_mapping, start_drag_pos, move_only)
                if part:
                    # select item and prepare for drag
                    self.graphic_drag_item_was_selected = already_selected
                    if not self.graphic_drag_item_was_selected:
                        if modifiers.shift:
                            display.graphic_selection.add(graphic_index)
                        elif not already_selected:
                            display.graphic_selection.set(graphic_index)
                    # keep track of general drag information
                    self.graphic_drag_start_pos = start_drag_pos
                    self.graphic_drag_changed = False
                    # keep track of info for the specific item that was clicked
                    self.graphic_drag_item = drawn_graphics[graphic_index]
                    self.graphic_drag_part = part
                    # keep track of drag information for each item in the set
                    self.graphic_drag_indexes = display.graphic_selection.indexes
                    for index in self.graphic_drag_indexes:
                        graphic = drawn_graphics[index]
                        self.graphic_drag_items.append(graphic)
                        self.graphic_part_data[index] = graphic.begin_drag()
                    break
            if not self.graphic_drag_items and not modifiers.shift:
                display.graphic_selection.clear()

    def begin_tracking_horizontal(self, pos, rescale):
        plot_origin = self.line_graph_horizontal_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
        plot_rect = self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds.translated(plot_origin)
        self.__tracking_horizontal = True
        self.__tracking_rescale = rescale
        self.__tracking_start_pos = pos
        self.__tracking_start_left_channel = self.__data_info.drawn_left_channel
        self.__tracking_start_right_channel = self.__data_info.drawn_right_channel
        self.__tracking_start_drawn_channel_per_pixel = float(self.__tracking_start_right_channel - self.__tracking_start_left_channel) / plot_rect.width
        self.__tracking_start_origin_pixel = self.__tracking_start_pos.x - plot_rect.left
        self.__tracking_start_channel = self.__tracking_start_left_channel + self.__tracking_start_origin_pixel * self.__tracking_start_drawn_channel_per_pixel

    def begin_tracking_vertical(self, pos, rescale):
        plot_height = self.line_graph_canvas_item.canvas_bounds.height - 1
        self.__tracking_vertical = True
        self.__tracking_rescale = rescale
        self.__tracking_start_pos = pos
        self.__tracking_start_drawn_data_min = self.__data_info.drawn_data_min
        self.__tracking_start_drawn_data_max = self.__data_info.drawn_data_max
        self.__tracking_start_drawn_data_per_pixel = self.__data_info.get_drawn_data_per_pixel(plot_height)
        self.__tracking_start_calibrated_data_min = self.__data_info.calibrated_data_min
        self.__tracking_start_calibrated_data_max = self.__data_info.calibrated_data_max
        plot_origin = self.line_graph_vertical_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
        plot_rect = self.line_graph_vertical_axis_group_canvas_item.canvas_bounds.translated(plot_origin)
        if 0.0 >= self.__tracking_start_calibrated_data_min and 0.0 <= self.__tracking_start_calibrated_data_max:
            calibrated_unit_per_pixel = (self.__tracking_start_calibrated_data_max - self.__tracking_start_calibrated_data_min) / (plot_rect.height - 1)
            origin_offset_pixels = (0.0 - self.__tracking_start_calibrated_data_min) / calibrated_unit_per_pixel
            origin_offset_data = self.__tracking_start_drawn_data_min + origin_offset_pixels * self.__tracking_start_drawn_data_per_pixel
            self.__tracking_start_origin_y = origin_offset_pixels
            self.__tracking_start_origin_data = origin_offset_data
        else:
            self.__tracking_start_origin_y = 0  # the distance the origin is up from the bottom
            self.__tracking_start_origin_data = self.__tracking_start_drawn_data_min

    def continue_tracking(self, pos, modifiers):
        if self.__tracking_selections:
            # x,y already have transform applied
            self.__last_mouse = copy.copy(pos)
            self.__update_cursor_info()
            if self.graphic_drag_items:
                with self.__data_item.data_item_changes():
                    for graphic in self.graphic_drag_items:
                        index = self.display.drawn_graphics.index(graphic)
                        part_data = (self.graphic_drag_part, ) + self.graphic_part_data[index]
                        widget_mapping = self.__get_mouse_mapping()
                        graphic.adjust_part(widget_mapping, self.graphic_drag_start_pos, Geometry.IntPoint.make(pos), part_data, modifiers)
                        self.graphic_drag_changed = True
                        self.line_graph_regions_canvas_item.update()
        elif self.__tracking_horizontal:
            if self.__tracking_rescale:
                plot_origin = self.line_graph_horizontal_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
                plot_rect = self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds.translated(plot_origin)
                pixel_offset_x = pos.x - self.__tracking_start_pos.x
                scaling = math.pow(10, pixel_offset_x/96.0)  # 10x per inch of travel, assume 96dpi
                new_drawn_channel_per_pixel = self.__tracking_start_drawn_channel_per_pixel / scaling
                self.__display.left_channel = int(round(self.__tracking_start_channel - new_drawn_channel_per_pixel * self.__tracking_start_origin_pixel))
                self.__display.right_channel = int(round(self.__tracking_start_channel + new_drawn_channel_per_pixel * (plot_rect.width - self.__tracking_start_origin_pixel)))
            else:
                delta = pos - self.__tracking_start_pos
                self.__display.left_channel = int(self.__tracking_start_left_channel - self.__tracking_start_drawn_channel_per_pixel * delta.x)
                self.__display.right_channel = int(self.__tracking_start_right_channel - self.__tracking_start_drawn_channel_per_pixel * delta.x)
                return True
        elif self.__tracking_vertical:
            if self.__tracking_rescale:
                plot_origin = self.line_graph_vertical_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
                plot_rect = self.line_graph_vertical_axis_group_canvas_item.canvas_bounds.translated(plot_origin)
                origin_y = plot_rect.bottom - 1 - self.__tracking_start_origin_y  # pixel position of y-origin
                data_offset = self.__tracking_start_drawn_data_per_pixel * (origin_y - self.__tracking_start_pos.y)
                pixel_offset = origin_y - pos.y
                pixel_offset = max(pixel_offset, 1) if origin_y > self.__tracking_start_pos.y else min(pixel_offset, -1)
                new_drawn_data_per_pixel = data_offset / pixel_offset
                data_min = self.__tracking_start_origin_data - new_drawn_data_per_pixel * self.__tracking_start_origin_y
                data_max = self.__tracking_start_origin_data + new_drawn_data_per_pixel * (plot_rect.height - 1 - self.__tracking_start_origin_y)
                self.__display.y_min = data_min
                self.__display.y_max = data_max
                return True
            else:
                delta = pos - self.__tracking_start_pos
                data_min = self.__tracking_start_drawn_data_min + self.__tracking_start_drawn_data_per_pixel * delta.y
                data_max = self.__tracking_start_drawn_data_max + self.__tracking_start_drawn_data_per_pixel * delta.y
                self.__display.y_min = data_min
                self.__display.y_max = data_max
                return True
        return False

    def end_tracking(self, modifiers):
        if self.__tracking_selections:
            display = self.display
            if display:
                drawn_graphics = display.drawn_graphics
                for index in self.graphic_drag_indexes:
                    graphic = drawn_graphics[index]
                    graphic.end_drag(self.graphic_part_data[index])
                if self.graphic_drag_items and not self.graphic_drag_changed:
                    graphic_index = drawn_graphics.index(self.graphic_drag_item)
                    # user didn't move graphic
                    if not modifiers.shift:
                        # user clicked on a single graphic
                        display.graphic_selection.set(graphic_index)
                    else:
                        # user shift clicked. toggle selection
                        # if shift is down and item is already selected, toggle selection of item
                        if self.graphic_drag_item_was_selected:
                            display.graphic_selection.remove(graphic_index)
                        else:
                            display.graphic_selection.add(graphic_index)
            self.graphic_drag_items = []
            self.graphic_drag_item = None
            self.graphic_part_data = {}
            self.graphic_drag_indexes = []
            self.delegate.image_panel_set_tool_mode("pointer")
        self.__tracking_horizontal = False
        self.__tracking_vertical = False
        self.__tracking_selections = False

    def __get_data_size(self):
        data_and_calibration = self.display.data_and_calibration if self.display else None
        data_shape = data_and_calibration.dimensional_shape if data_and_calibration else None
        if not data_shape:
            return None
        for d in data_shape:
            if not d > 0:
                return None
        return data_shape

    def __update_cursor_info(self):
        pos = None
        data_size = self.__get_data_size()
        if self.__mouse_in and self.__last_mouse:
            if data_size and len(data_size) == 1:
                last_mouse = self.map_to_canvas_item(self.__last_mouse, self.line_graph_canvas_item)
                pos = self.line_graph_canvas_item.map_mouse_to_position(last_mouse, data_size)
            self.delegate.image_panel_cursor_changed(self, self.display, pos, data_size)
        else:
            self.delegate.image_panel_cursor_changed(self, None, None, None)


class ImageCanvasItem(CanvasItem.CanvasItemComposition):

    def __init__(self, delegate):
        super(ImageCanvasItem, self).__init__()

        self.delegate = delegate

        self.wants_mouse_events = True

        self.__last_image_zoom = 1.0
        self.__last_image_norm_center = (0.5, 0.5)
        self.image_canvas_mode = "fit"

        # create the child canvas items
        # the background
        self.background_canvas_item = CanvasItem.BackgroundCanvasItem()
        # next the zoomable items
        self.bitmap_canvas_item = CanvasItem.BitmapCanvasItem(background_color="#888")
        self.graphics_canvas_item = GraphicsCanvasItem()
        # put the zoomable items into a composition
        self.composite_canvas_item = CanvasItem.CanvasItemComposition()
        self.composite_canvas_item.add_canvas_item(self.bitmap_canvas_item)
        self.composite_canvas_item.add_canvas_item(self.graphics_canvas_item)
        # and put the composition into a scroll area
        self.scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(self.composite_canvas_item)
        self.scroll_area_canvas_item.on_layout_updated = lambda canvas_origin, canvas_size: self.scroll_area_canvas_item_layout_updated(canvas_size)
        # info overlay (scale marker, etc.)
        self.info_overlay_canvas_item = InfoOverlayCanvasItem()
        # canvas items get added back to front
        self.add_canvas_item(self.background_canvas_item)
        self.add_canvas_item(self.scroll_area_canvas_item)
        self.add_canvas_item(self.info_overlay_canvas_item)

        # thread for drawing
        self.__data_item = None
        self.__buffered_data_source = None
        self.__display = None
        self.__prepare_data_thread = ThreadPool.ThreadDispatcher(lambda: self.prepare_display_on_thread())
        self.__prepare_data_thread.start()

        # used for dragging graphic items
        self.graphic_drag_items = []
        self.graphic_drag_item = None
        self.graphic_part_data = {}
        self.graphic_drag_indexes = []
        self.__last_mouse = None
        self.__is_dragging = False
        self.__mouse_in = False

    def close(self):
        if self.__prepare_data_thread:
            self.__prepare_data_thread.close()
            self.__prepare_data_thread = None
        self.update_display(DataItem.DisplaySpecifier())
        self.delegate.clear_task("prepare")
        # call super
        super(ImageCanvasItem, self).close()

    def about_to_close(self):
        # message received when image panel closes; otherwise thread is shut down when parent canvas item closes
        if self.__prepare_data_thread:
            self.__prepare_data_thread.close()
            self.__prepare_data_thread = None

    def __get_preferred_aspect_ratio(self):
        if self.display:
            dimensional_shape = self.display.preview_2d_shape
            return dimensional_shape[1] / dimensional_shape[0] if dimensional_shape[0] != 0 else 1.0
        return 1.0
    preferred_aspect_ratio = property(__get_preferred_aspect_ratio)

    @property
    def display(self):
        return self.__display

    # when the display changes, set the data using this property.
    # doing this will queue an item in the paint thread to repaint.
    def update_display(self, display_specifier):
        # first take care of listeners and update the __display field
        data_item, buffered_data_source, display = display_specifier.data_item, display_specifier.buffered_data_source, display_specifier.display
        old_display = self.__display
        if old_display and display != old_display:
            old_display.remove_listener(self)
        self.__data_item = data_item
        self.__buffered_data_source = buffered_data_source
        self.__display = display
        if display and display != old_display:
            display.add_listener(self)  # for display_graphic_selection_changed
        # next get rid of data associated with canvas items
        if self.__display is None:
            self.bitmap_canvas_item.rgba_bitmap_data = None
            self.bitmap_canvas_item.update()
            self.graphics_canvas_item.display = None
            self.graphics_canvas_item.update()
            self.info_overlay_canvas_item.data_item = None
            self.info_overlay_canvas_item.display = None
            self.info_overlay_canvas_item.update()
        else:
            self.display_graphic_selection_changed(self.__display, self.__display.graphic_selection)
        # update the cursor info
        self.__update_cursor_info()
        # finally, trigger the paint thread (if there still is one) to update
        if self.__prepare_data_thread:
            self.__prepare_data_thread.trigger()

    def wait_for_prepare_data(self):
        self.__prepare_data_thread.trigger(wait=True)

    def display_graphic_selection_changed(self, display, graphic_selection):
        # this message will come directly from the display when the graphic selection changes
        self.graphics_canvas_item.update()

    def update_image_canvas_zoom(self, new_image_zoom):
        if self.display:
            self.image_canvas_mode = "custom"
            self.__last_image_zoom = new_image_zoom
            self.update_image_canvas_size()

    # update the image canvas position by the widget delta amount
    def update_image_canvas_position(self, widget_delta):
        if self.display:
            # create a widget mapping to get from image norm to widget coordinates and back
            widget_mapping = WidgetImageMapping(self.display.preview_2d_shape, (0, 0), self.composite_canvas_item.canvas_size)
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
    def scroll_area_canvas_item_layout_updated(self, scroll_area_canvas_size):
        if not self.display:
            self.__last_image_norm_center = (0.5, 0.5)
            self.__last_image_zoom = 1.0
            self.info_overlay_canvas_item.image_canvas_origin = None
            self.info_overlay_canvas_item.image_canvas_size = None
            return
        if self.image_canvas_mode == "fill":
            dimensional_shape = self.display.preview_2d_shape
            scale_h = float(dimensional_shape[1]) / scroll_area_canvas_size[1]
            scale_v = float(dimensional_shape[0]) / scroll_area_canvas_size[0]
            if scale_v < scale_h:
                image_canvas_size = (scroll_area_canvas_size[0], scroll_area_canvas_size[0] * dimensional_shape[1] / dimensional_shape[0])
            else:
                image_canvas_size = (scroll_area_canvas_size[1] * dimensional_shape[0] / dimensional_shape[1], scroll_area_canvas_size[1])
            image_canvas_origin = (scroll_area_canvas_size[0] * 0.5 - image_canvas_size[0] * 0.5, scroll_area_canvas_size[1] * 0.5 - image_canvas_size[1] * 0.5)
            self.composite_canvas_item.update_layout(image_canvas_origin, image_canvas_size)
        elif self.image_canvas_mode == "fit":
            image_canvas_size = scroll_area_canvas_size
            image_canvas_origin = (0, 0)
            self.composite_canvas_item.update_layout(image_canvas_origin, image_canvas_size)
        elif self.image_canvas_mode == "1:1":
            image_canvas_size = self.display.preview_2d_shape
            image_canvas_origin = (scroll_area_canvas_size[0] * 0.5 - image_canvas_size[0] * 0.5, scroll_area_canvas_size[1] * 0.5 - image_canvas_size[1] * 0.5)
            self.composite_canvas_item.update_layout(image_canvas_origin, image_canvas_size)
        else:
            c = self.__last_image_norm_center
            dimensional_shape = self.display.preview_2d_shape
            image_canvas_size = (scroll_area_canvas_size[0] * self.__last_image_zoom, scroll_area_canvas_size[1] * self.__last_image_zoom)
            canvas_rect = Geometry.fit_to_size(((0, 0), image_canvas_size), dimensional_shape)
            # c[0] = ((scroll_area_canvas_size[0] * 0.5 - image_canvas_origin[0]) - canvas_rect[0][0])/canvas_rect[1][0]
            image_canvas_origin_y = (scroll_area_canvas_size[0] * 0.5) - c[0] * canvas_rect[1][0] - canvas_rect[0][0]
            image_canvas_origin_x = (scroll_area_canvas_size[1] * 0.5) - c[1] * canvas_rect[1][1] - canvas_rect[0][1]
            image_canvas_origin = (image_canvas_origin_y, image_canvas_origin_x)
            self.composite_canvas_item.update_layout(image_canvas_origin, image_canvas_size)
        # the image will be drawn centered within the canvas size
        dimensional_shape = self.display.preview_2d_shape
        #logging.debug("scroll_area_canvas_size %s", scroll_area_canvas_size)
        #logging.debug("image_canvas_origin %s", image_canvas_origin)
        #logging.debug("image_canvas_size %s", image_canvas_size)
        #logging.debug("dimensional_shape %s", dimensional_shape)
        #logging.debug("c %s %s", (scroll_area_canvas_size[0] * 0.5 - image_canvas_origin[0]) / dimensional_shape[0], (scroll_area_canvas_size[1] * 0.5 - image_canvas_origin[1]) / dimensional_shape[1])
        widget_mapping = WidgetImageMapping(self.display.preview_2d_shape, (0, 0), image_canvas_size)
        #logging.debug("c2 %s", widget_mapping.map_point_widget_to_image_norm((scroll_area_canvas_size[0] * 0.5 - image_canvas_origin[0], scroll_area_canvas_size[1] * 0.5 - image_canvas_origin[1])))
        self.__last_image_norm_center = widget_mapping.map_point_widget_to_image_norm((scroll_area_canvas_size[0] * 0.5 - image_canvas_origin[0], scroll_area_canvas_size[1] * 0.5 - image_canvas_origin[1]))
        canvas_rect = Geometry.fit_to_size(((0, 0), image_canvas_size), dimensional_shape)
        scroll_rect = Geometry.fit_to_size(((0, 0), scroll_area_canvas_size), dimensional_shape)
        self.__last_image_zoom = float(canvas_rect[1][0]) / scroll_rect[1][0]
        #logging.debug("z %s (%s)", self.__last_image_zoom, float(canvas_rect[1][1]) / scroll_rect[1][1])
        self.info_overlay_canvas_item.image_canvas_origin = image_canvas_origin
        self.info_overlay_canvas_item.image_canvas_size = image_canvas_size

    def update_image_canvas_size(self):
        scroll_area_canvas_size = self.scroll_area_canvas_item.canvas_size
        if scroll_area_canvas_size is not None:
            self.scroll_area_canvas_item_layout_updated(scroll_area_canvas_size)
            self.composite_canvas_item.update()

    def mouse_clicked(self, x, y, modifiers):
        if super(ImageCanvasItem, self).mouse_clicked(x, y, modifiers):
            return True
        # now let the image panel handle mouse clicking if desired
        image_position = self.__get_mouse_mapping().map_point_widget_to_image((y, x))
        self.delegate.image_panel_mouse_clicked(image_position, modifiers)
        return True

    def mouse_double_clicked(self, x, y, modifiers):
        self.set_fit_mode()
        return True

    def mouse_pressed(self, x, y, modifiers):
        if super(ImageCanvasItem, self).mouse_pressed(x, y, modifiers):
            return True
        data_item = self.__data_item
        display = self.__display
        if not display:
            return False
        data_item.begin_transaction()
        # figure out clicked graphic
        self.graphic_drag_items = []
        self.graphic_drag_item = None
        self.graphic_drag_item_was_selected = False
        self.graphic_part_data = {}
        self.graphic_drag_indexes = []
        if self.delegate.image_panel_get_tool_mode() == "pointer":
            drawn_graphics = display.drawn_graphics
            for graphic_index, graphic in enumerate(drawn_graphics):
                start_drag_pos = Geometry.IntPoint(y=y, x=x)
                already_selected = display.graphic_selection.contains(graphic_index)
                multiple_items_selected = len(display.graphic_selection.indexes) > 1
                move_only = not already_selected or multiple_items_selected
                widget_mapping = self.__get_mouse_mapping()
                part = graphic.test(widget_mapping, start_drag_pos, move_only)
                if part:
                    # select item and prepare for drag
                    self.graphic_drag_item_was_selected = already_selected
                    if not self.graphic_drag_item_was_selected:
                        if modifiers.shift:
                            display.graphic_selection.add(graphic_index)
                        elif not already_selected:
                            display.graphic_selection.set(graphic_index)
                    # keep track of general drag information
                    self.graphic_drag_start_pos = start_drag_pos
                    self.graphic_drag_changed = False
                    # keep track of info for the specific item that was clicked
                    self.graphic_drag_item = drawn_graphics[graphic_index]
                    self.graphic_drag_part = part
                    # keep track of drag information for each item in the set
                    self.graphic_drag_indexes = display.graphic_selection.indexes
                    for index in self.graphic_drag_indexes:
                        graphic = drawn_graphics[index]
                        self.graphic_drag_items.append(graphic)
                        self.graphic_part_data[index] = graphic.begin_drag()
                    break
            if not self.graphic_drag_items and not modifiers.shift:
                display.graphic_selection.clear()
        elif self.delegate.image_panel_get_tool_mode() == "hand":
            self.__start_drag_pos = (y, x)
            self.__last_drag_pos = (y, x)
            self.__is_dragging = True
        return True

    def mouse_released(self, x, y, modifiers):
        if super(ImageCanvasItem, self).mouse_released(x, y, modifiers):
            return True
        data_item = self.__data_item
        display = self.__display
        if display:
            drawn_graphics = display.drawn_graphics
            for index in self.graphic_drag_indexes:
                graphic = drawn_graphics[index]
                graphic.end_drag(self.graphic_part_data[index])
            if self.graphic_drag_items and not self.graphic_drag_changed:
                graphic_index = drawn_graphics.index(self.graphic_drag_item)
                # user didn't move graphic
                if not modifiers.shift:
                    # user clicked on a single graphic
                    display.graphic_selection.set(graphic_index)
                else:
                    # user shift clicked. toggle selection
                    # if shift is down and item is already selected, toggle selection of item
                    if self.graphic_drag_item_was_selected:
                        display.graphic_selection.remove(graphic_index)
                    else:
                        display.graphic_selection.add(graphic_index)
            data_item.end_transaction()
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
        self.__last_mouse = Geometry.IntPoint(x=x, y=y)
        self.__update_cursor_info()
        if self.graphic_drag_items:
            with self.__data_item.data_item_changes():
                for graphic in self.graphic_drag_items:
                    index = self.display.drawn_graphics.index(graphic)
                    part_data = (self.graphic_drag_part, ) + self.graphic_part_data[index]
                    widget_mapping = self.__get_mouse_mapping()
                    graphic.adjust_part(widget_mapping, self.graphic_drag_start_pos, (y, x), part_data, modifiers)
                    self.graphic_drag_changed = True
                    self.graphics_canvas_item.update()
        elif self.__is_dragging:
            delta = (y - self.__last_drag_pos[0], x - self.__last_drag_pos[1])
            self.update_image_canvas_position((-delta[0], -delta[1]))
            self.__last_drag_pos = (y, x)
        return True

    def wheel_changed(self, dx, dy, is_horizontal):
        if self.__mouse_in:
            dx = dx if is_horizontal else 0.0
            dy = dy if not is_horizontal else 0.0
            self.update_image_canvas_position((-dy, -dx))
            return True
        return False

    def pan_gesture(self, dx, dy):
        self.update_image_canvas_position((dy, dx))
        return True

    def context_menu_event(self, x, y, gx, gy):
        self.delegate.image_panel_show_context_menu(gx, gy)
        return True

    # ths message comes from the widget
    def key_pressed(self, key):
        if super(ImageCanvasItem, self).key_pressed(key):
            return True
        # only handle keys if we're directly embedded in an image panel
        if not self.delegate:
            return False
        if key.is_delete:
            self.delegate.image_panel_delete_key_pressed()
            return True
        display = self.display
        if display:
            #logging.debug("text=%s key=%s mod=%s", key.text, hex(key.key), key.modifiers)
            all_graphics = display.drawn_graphics
            graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if display.graphic_selection.contains(graphic_index)]
            if len(graphics):
                if key.is_arrow:
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
        return self.delegate.image_panel_key_pressed(key)

    def __get_image_size(self):
        data_shape = self.display.preview_2d_shape if self.display else None
        if not data_shape:
            return None
        for d in data_shape:
            if not d > 0:
                return None
        return data_shape

    def __get_mouse_mapping(self):
        image_size = self.__get_image_size()
        return WidgetImageMapping(image_size, self.composite_canvas_item.canvas_origin, self.composite_canvas_item.canvas_size)

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
            return image_y, image_x  # c-indexing
        return None

    # map from image normalized coordinates to image coordinates
    def map_image_norm_to_image(self, p):
        image_size = self.__get_image_size()
        if image_size:
            return p[0] * image_size[0], p[1] * image_size[1]
        return None

    def __update_cursor_info(self):
        pos = None
        image_size = self.__get_image_size()
        if self.__mouse_in and self.__last_mouse:
            if image_size and len(image_size) > 1:
                pos = self.map_widget_to_image(self.__last_mouse)
            self.delegate.image_panel_cursor_changed(self, self.display, pos, image_size)
        else:
            self.delegate.image_panel_cursor_changed(self, None, None, None)

    # this method will be invoked from the paint thread.
    # data is calculated and then sent to the image canvas item.
    def prepare_display_on_thread(self):

        data_item = self.__data_item
        display = self.__display

        if display:
            # grab the data item too
            data_and_calibration = display.data_and_calibration

            # make sure we have the correct data
            assert data_and_calibration is not None
            # TODO: fix me 3d
            assert data_and_calibration.is_data_2d or data_and_calibration.is_data_3d

            def update_ui():
                # grab the bitmap image
                rgba_image = display.preview_2d
                self.bitmap_canvas_item.rgba_bitmap_data = rgba_image
                # update the graphics canvas
                self.graphics_canvas_item.display = display
                self.graphics_canvas_item.update()
                # update the info overlay
                self.info_overlay_canvas_item.data_item = data_item
                self.info_overlay_canvas_item.display = display
                self.info_overlay_canvas_item.update()

            self.delegate.add_task("prepare", update_ui)

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


class ImagePanelOverlayCanvasItem(CanvasItem.AbstractCanvasItem):
    """
        An overlay for image panels to draw and handle focus, selection, and drop targets.

        The overlay has a focused property, but this is not the same as the canvas focused_item.
        The focused property here is just a flag to indicate whether to draw the focus ring.
    """

    def __init__(self, image_panel):
        super(ImagePanelOverlayCanvasItem, self).__init__()
        self.wants_drag_events = True
        self.image_panel = image_panel
        self.__dropping = False
        self.__drop_region = "none"
        self.__focused = False
        self.__selected = False
        self.__selected_style = "#CCC"  # TODO: platform dependent
        self.__focused_style = "#3876D6"  # TODO: platform dependent

    def close(self):
        self.image_panel = None
        super(ImagePanelOverlayCanvasItem, self).close()

    def __get_focused(self):
        return self.__focused

    def __set_focused(self, focused):
        if self.__focused != focused:
            self.__focused = focused
            self.update()

    focused = property(__get_focused, __set_focused)

    def __get_selected(self):
        return self.__selected

    def __set_selected(self, selected):
        if self.__selected != selected:
            self.__selected = selected
            self.update()

    selected = property(__get_selected, __set_selected)

    def __set_drop_region(self, drop_region):
        if self.__drop_region != drop_region:
            self.__drop_region = drop_region
            self.update()

    def _repaint(self, drawing_context):

        super(ImagePanelOverlayCanvasItem, self)._repaint(drawing_context)

        # canvas size
        canvas_width = self.canvas_size[1]
        canvas_height = self.canvas_size[0]

        if self.__drop_region != "none":

            drawing_context.save()

            drawing_context.begin_path()
            if self.__drop_region == "left":
                drawing_context.rect(0, 0, int(canvas_width * 0.10), canvas_height)
            elif self.__drop_region == "right":
                drawing_context.rect(int(canvas_width * 0.90), 0, int(canvas_width - canvas_width * 0.90), canvas_height)
            elif self.__drop_region == "top":
                drawing_context.rect(0, 0, canvas_width, int(canvas_height * 0.10))
            elif self.__drop_region == "bottom":
                drawing_context.rect(0, int(canvas_height * 0.90), canvas_width, int(canvas_height - canvas_height * 0.90))
            else:
                drawing_context.rect(0, 0, canvas_width, canvas_height)
            drawing_context.fill_style = "rgba(255, 0, 0, 0.10)"
            drawing_context.fill()

            drawing_context.restore()

        if self.selected:

            stroke_style = self.__focused_style if self.focused else self.__selected_style

            drawing_context.save()

            drawing_context.begin_path()
            drawing_context.rect(2, 2, canvas_width - 4, canvas_height - 4)
            drawing_context.line_join = "miter"
            drawing_context.stroke_style = stroke_style
            drawing_context.line_width = 4.0
            drawing_context.stroke()

            drawing_context.restore()

    def drag_enter(self, mime_data):
        self.__dropping = True
        self.__set_drop_region("none")
        if self.image_panel:
            return self.image_panel.handle_drag_enter(mime_data)
        return "ignore"

    def drag_leave(self):
        self.__dropping = False
        self.__set_drop_region("none")
        if self.image_panel:
            self.image_panel.handle_drag_leave()
        return False

    def drag_move(self, mime_data, x, y):
        if self.image_panel:
            result = self.image_panel.handle_drag_move(mime_data, x, y)
            if result != "ignore":
                canvas_size = Geometry.IntSize.make(self.canvas_size)
                if x < int(canvas_size.width * 0.10):
                    self.__set_drop_region("left")
                elif x > int(canvas_size.width * 0.90):
                    self.__set_drop_region("right")
                elif y < int(canvas_size.height * 0.10):
                    self.__set_drop_region("top")
                elif y > int(canvas_size.height * 0.90):
                    self.__set_drop_region("bottom")
                else:
                    self.__set_drop_region("middle")
                return result
        self.__set_drop_region("none")
        return "ignore"

    def drop(self, mime_data, x, y):
        drop_region = self.__drop_region
        self.__dropping = False
        self.__set_drop_region("none")
        if self.image_panel:
            return self.image_panel.handle_drop(mime_data, drop_region, x, y)
        return "ignore"


class HardwareSourceStateController(object):

    """
    Track the state of a hardware source, as it relates to the UI.

    hardware_source may be None

    Clients should call:
        handle_play_clicked(workspace_controller)
        handle_abort_clicked()

    Clients can respond to:
        on_display_name_changed(display_name)
        on_play_button_state_changed(enabled, play_button_state)  play, scan, pause, stop
        on_abort_button_state_changed(visible, enabled)
    """

    def __init__(self, hardware_source):
        self.__hardware_source = hardware_source
        if self.__hardware_source:
            self.__hardware_source.add_listener(self)
            self.__hardware_source.data_buffer.add_listener(self)
        self.on_display_name_changed = None
        self.on_play_button_state_changed = None
        self.on_abort_button_state_changed = None
        self.on_data_item_states_changed = None

    def close(self):
        if self.__hardware_source:
            self.__hardware_source.data_buffer.remove_listener(self)
            self.__hardware_source.remove_listener(self)
        self.__hardware_source = None

    def __update_play_button_state(self):
        if self.on_play_button_state_changed:
            enabled = self.__hardware_source is not None
            if self.__hardware_source and self.__hardware_source.features.get("is_scanning", False):
                self.on_play_button_state_changed(enabled, "stop" if self.is_playing else "scan")
            else:
                self.on_play_button_state_changed(enabled, "pause" if self.is_playing else "play")

    def __update_abort_button_state(self):
        if self.on_abort_button_state_changed:
            if self.__hardware_source and self.__hardware_source.features.get("is_scanning", False):
                self.on_abort_button_state_changed(True, self.is_playing)
            else:
                self.on_abort_button_state_changed(False, False)

    def initialize_state(self):
        """ Call this to initialize the state of the UI after everything has been connected. """
        if self.on_display_name_changed:
            self.on_display_name_changed(self.display_name)
        self.__update_play_button_state()
        self.__update_abort_button_state()
        if self.on_data_item_states_changed:
            self.on_data_item_states_changed(list())

    def handle_play_clicked(self, workspace_controller):
        """ Call this when the user clicks the play/pause button. """
        if self.__hardware_source:
            if self.is_playing:
                self.__hardware_source.stop_playing()
            else:
                self.__hardware_source.start_playing(workspace_controller)

    def handle_abort_clicked(self):
        """ Call this when the user clicks the abort button. """
        if self.__hardware_source:
            self.__hardware_source.abort_playing()

    @property
    def is_playing(self):
        """ Returns whether the hardware source is playing or not. """
        return self.__hardware_source.data_buffer.is_playing if self.__hardware_source else False

    @property
    def display_name(self):
        """ Returns the display name for the hardware source. """
        return self.__hardware_source.display_name if self.__hardware_source else _("N/A")

    # this message comes from the data buffer. it will always be invoked on the UI thread.
    def playing_state_changed(self, hardware_source, is_playing):
        if hardware_source == self.__hardware_source:
            self.__update_play_button_state()
            self.__update_abort_button_state()

    # this message comes from the hardware source. may be called from thread.
    def hardware_source_started(self, hardware_source):
        pass

    # this message comes from the hardware source. may be called from thread.
    def hardware_source_stopped(self, hardware_source):
        if self.on_data_item_states_changed:
            self.on_data_item_states_changed(list())

    # this message comes from the hardware source. may be called from thread.
    def hardware_source_updated_data_item_states(self, hardware_source, data_item_states):
        if self.on_data_item_states_changed:
            self.on_data_item_states_changed(data_item_states)


class LiveImagePanelController(object):
    """
        Represents a controller for the content of an image panel.
    """

    def __init__(self, image_panel, hardware_source_id, hardware_source_channel_id):
        assert hardware_source_id is not None
        hardware_source = HardwareSource.HardwareSourceManager().get_hardware_source_for_hardware_source_id(hardware_source_id)
        workspace_controller = image_panel.document_controller.workspace_controller
        self.type = "live"

        # configure the user interface
        self.__image_panel = image_panel
        self.__image_panel.header_canvas_item.end_header_color = "#FF9999"
        self.__playback_controls_composition = CanvasItem.CanvasItemComposition()
        self.__playback_controls_composition.layout = CanvasItem.CanvasItemLayout()
        self.__playback_controls_composition.sizing.set_fixed_height(30)
        playback_controls_row = CanvasItem.CanvasItemComposition()
        playback_controls_row.layout = CanvasItem.CanvasItemRowLayout()
        play_button_canvas_item = CanvasItem.TextButtonCanvasItem()
        abort_button_canvas_item = CanvasItem.TextButtonCanvasItem()
        state_text_canvas_item = CanvasItem.StaticTextCanvasItem(str())
        hardware_source_display_name_canvas_item = CanvasItem.StaticTextCanvasItem(str())
        playback_controls_row.add_canvas_item(play_button_canvas_item)
        playback_controls_row.add_canvas_item(abort_button_canvas_item)
        playback_controls_row.add_canvas_item(state_text_canvas_item)
        playback_controls_row.add_canvas_item(CanvasItem.EmptyCanvasItem())
        playback_controls_row.add_canvas_item(hardware_source_display_name_canvas_item)
        self.__playback_controls_composition.add_canvas_item(CanvasItem.BackgroundCanvasItem("#FF9999"))
        self.__playback_controls_composition.add_canvas_item(playback_controls_row)
        self.__image_panel.footer_canvas_item.insert_canvas_item(0, self.__playback_controls_composition)

        # configure the hardware source state controller
        self.__hardware_source_state_controller = HardwareSourceStateController(hardware_source)

        def display_name_changed(display_name):
            hardware_source_display_name_canvas_item.text = display_name
            hardware_source_display_name_canvas_item.size_to_content(image_panel.image_panel_get_font_metrics)
            self.__playback_controls_composition.refresh_layout()

        def play_button_state_changed(enabled, play_button_state):
            play_button_canvas_item.enabled = enabled
            map_play_button_state_to_text = {"play": _("Play"), "pause": _("Pause"), "scan": _("Scan"), "stop": _("Stop")}
            play_button_canvas_item.text = map_play_button_state_to_text[play_button_state]
            play_button_canvas_item.size_to_content(image_panel.image_panel_get_font_metrics)
            self.__playback_controls_composition.refresh_layout()

        def abort_button_state_changed(visible, enabled):
            abort_button_canvas_item.text = _("Abort") if visible else str()
            abort_button_canvas_item.enabled = enabled
            abort_button_canvas_item.size_to_content(image_panel.image_panel_get_font_metrics)
            self.__playback_controls_composition.refresh_layout()

        def data_item_states_changed(data_item_states):
            map_channel_state_to_text = {"stopped": _("Stopped"), "complete": _("Acquiring"),
                "partial": _("Acquiring"), "marked": _("Stopping")}
            for data_item_state in data_item_states:
                if data_item_state["data_item"] == image_panel.display_specifier.data_item:
                    channel_state = data_item_state["channel_state"]
                    partial_str = str()
                    data_item = data_item_state.get("data_item")
                    scan_position = data_item.get_metadata("hardware_source").get("scan_position")
                    if scan_position is not None:
                        partial_str = " " + str(int(100 * scan_position["y"] / data_item.maybe_data_source.dimensional_shape[0])) + "%"
                    state_text_canvas_item.text = map_channel_state_to_text[channel_state] + partial_str
                    state_text_canvas_item.size_to_content(image_panel.image_panel_get_font_metrics)
                    self.__playback_controls_composition.refresh_layout()
                    return
            state_text_canvas_item.text = map_channel_state_to_text["stopped"]
            state_text_canvas_item.size_to_content(image_panel.image_panel_get_font_metrics)
            self.__playback_controls_composition.refresh_layout()

        self.__hardware_source_state_controller.on_display_name_changed = display_name_changed
        self.__hardware_source_state_controller.on_play_button_state_changed = play_button_state_changed
        self.__hardware_source_state_controller.on_abort_button_state_changed = abort_button_state_changed
        self.__hardware_source_state_controller.on_data_item_states_changed = data_item_states_changed

        play_button_canvas_item.on_button_clicked = lambda: self.__hardware_source_state_controller.handle_play_clicked(workspace_controller)
        abort_button_canvas_item.on_button_clicked = self.__hardware_source_state_controller.handle_abort_clicked

        self.__hardware_source_state_controller.initialize_state()

        # configure the display item update
        self.__hardware_source_id = hardware_source_id
        self.__hardware_source_channel_id = hardware_source_channel_id
        self.__filtered_data_items_binding = DataItemsBinding.DataItemsFilterBinding(self.__image_panel.document_controller.data_items_binding)

        def matches_hardware_source(data_item):
            hardware_source_id = data_item.get_metadata("hardware_source").get("hardware_source_id")
            hardware_source_channel_id = data_item.get_metadata("hardware_source").get("hardware_source_channel_id")
            return hardware_source_id == self.__hardware_source_id and hardware_source_channel_id == self.__hardware_source_channel_id

        def sort_by_date_key(data_item):
            """ A sort key to for the datetime_original field of a data item. """
            return data_item.title + str(data_item.uuid) if data_item.is_live else str(), Utility.get_datetime_from_datetime_item(data_item.datetime_original)

        self.__filtered_data_items_binding.sort_key = sort_by_date_key
        self.__filtered_data_items_binding.sort_reverse = True
        self.__filtered_data_items_binding.filter = matches_hardware_source

        def update_display_data_item():
            data_items = self.__filtered_data_items_binding.data_items
            if len(data_items) > 0:
                self.__image_panel.set_displayed_data_item(data_items[0])
            else:
                self.__image_panel.set_displayed_data_item(None)

        self.__filtered_data_items_binding.inserters[id(self)] = lambda data_item, before_index: self.__image_panel.queue_task(update_display_data_item)
        self.__filtered_data_items_binding.removers[id(self)] = lambda data_item, index: self.__image_panel.queue_task(update_display_data_item)

        update_display_data_item()

    def close(self):
        del self.__filtered_data_items_binding.inserters[id(self)]
        del self.__filtered_data_items_binding.removers[id(self)]
        self.__image_panel.header_canvas_item.reset_header_colors()
        self.__image_panel.footer_canvas_item.remove_canvas_item(self.__playback_controls_composition)
        self.__image_panel = None
        self.__hardware_source_state_controller.close()
        self.__hardware_source_state_controller = None

    @classmethod
    def make(cls, image_panel, d):
        hardware_source_id = d.get("hardware_source_id")
        hardware_source_channel_id = d.get("hardware_source_channel_id")
        if hardware_source_id:
            return LiveImagePanelController(image_panel, hardware_source_id, hardware_source_channel_id)
        return None

    def save(self, d):
        d["hardware_source_id"] = self.__hardware_source_id
        if self.__hardware_source_channel_id is not None:
            d["hardware_source_channel_id"] = self.__hardware_source_channel_id


class BrowserImagePanelController(object):
    """
        Represents a controller for the content of an image panel.

        Image panels have the ability to update their content spontaneously in response to
        external events such as a selection in another panel changing, acquisition starting,
        and more.
    """
    def __init__(self, image_panel):
        self.type = "browser"
        self.__image_panel = image_panel
        self.__image_panel.document_controller.add_listener(self)
        self.__image_panel.header_canvas_item.end_header_color = "#996633"
        self.browser_data_item_changed(self.__image_panel.document_controller.browser_data_item)

    def close(self):
        self.__image_panel.header_canvas_item.reset_header_colors()
        self.__image_panel.document_controller.remove_listener(self)
        self.__image_panel = None

    @classmethod
    def make(cls, image_panel, d):
        return BrowserImagePanelController(image_panel)

    def save(self, d):
        pass

    def browser_data_item_changed(self, data_item):
        self.__image_panel.set_displayed_data_item(data_item)


class ImagePanel(object):

    def __init__(self, document_controller):

        self.document_controller = document_controller
        self.ui = document_controller.ui

        self.__weak_workspace = None

        self.__display_specifier = DataItem.DisplaySpecifier()

        self.__pending_update_lock = threading.RLock()
        self.__pending_display_specifier = DataItem.DisplaySpecifier()

        class ContentCanvasItem(CanvasItem.CanvasItemComposition):

            def __init__(self, image_panel):
                super(ContentCanvasItem, self).__init__()
                self.image_panel = image_panel

            def close(self):
                self.image_panel = None
                super(ContentCanvasItem, self).close()

            def key_pressed(self, key):
                if self.image_panel.display_canvas_item:
                    return self.image_panel.display_canvas_item.key_pressed(key)
                return super(ContentCanvasItem, self).key_pressed(key)

        self.__content_canvas_item = ContentCanvasItem(self)
        self.__content_canvas_item.wants_mouse_events = True  # only when display_canvas_item is None
        self.__content_canvas_item.focusable = True
        self.__content_canvas_item.on_focus_changed = lambda focused: self.set_focused(focused)
        self.__overlay_canvas_item = ImagePanelOverlayCanvasItem(self)
        self.__content_canvas_item.add_canvas_item(self.__overlay_canvas_item)
        self.__header_canvas_item = Panel.HeaderCanvasItem(display_drag_control=True, display_sync_control=True, display_close_control=True)
        self.__header_canvas_item.on_drag_pressed = lambda: self.__begin_drag()
        self.__header_canvas_item.on_sync_clicked = lambda: self.__sync_data_item()
        self.__header_canvas_item.on_close_clicked = lambda: self.__close_image_panel()
        self.__footer_canvas_item = CanvasItem.CanvasItemComposition()
        self.__footer_canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        self.__footer_canvas_item.sizing.collapsible = True

        self.canvas_item = CanvasItem.CanvasItemComposition()
        self.canvas_item.layout = CanvasItem.CanvasItemColumnLayout()

        self.canvas_item.add_canvas_item(self.__header_canvas_item)
        self.canvas_item.add_canvas_item(self.__content_canvas_item)
        self.canvas_item.add_canvas_item(self.__footer_canvas_item)

        self.document_controller.register_image_panel(self)

        # this results in data_item_deleted messages
        self.document_controller.document_model.add_listener(self)

        self.__image_panel_controller = None

        self.display_canvas_item = None
        self.__display_type = None

    def close(self):
        # self.canvas_item.close()  # the creator of the image panel is responsible for closing the canvas item
        self.canvas_item = None
        if self.display_canvas_item:
            self.display_canvas_item.about_to_close()
            self.display_canvas_item = None
        self.__content_canvas_item.on_focus_changed = None  # only necessary during tests
        if self.__image_panel_controller:
            self.__image_panel_controller.close()
            self.__image_panel_controller = None
        self.document_controller.document_model.remove_listener(self)
        self.document_controller.unregister_image_panel(self)
        self.__set_display(DataItem.DisplaySpecifier())  # required before destructing display thread
        # release references
        self.workspace_controller = None
        self.__content_canvas_item = None
        self.__overlay_canvas_item = None
        self.__header_canvas_item = None

    @property
    def workspace(self):
        return self.__weak_workspace() if self.__weak_workspace else None

    @workspace.setter
    def workspace(self, workspace):
        self.__weak_workspace = weakref.ref(workspace) if workspace else None

    @property
    def header_canvas_item(self):
        return self.__header_canvas_item

    @property
    def footer_canvas_item(self):
        return self.__footer_canvas_item

    # tasks can be added in two ways, queued or added
    # queued tasks are guaranteed to be executed in the order queued.
    # added tasks are only executed if not replaced before execution.
    # added tasks do not guarantee execution order or execution at all.

    def add_task(self, key, task):
        self.document_controller.add_task(key + str(id(self)), task)

    def clear_task(self, key):
        self.document_controller.clear_task(key + str(id(self)))

    def queue_task(self, task):
        self.document_controller.queue_task(task)

    # save and restore the contents of the image panel

    def save_contents(self, d):
        if self.__image_panel_controller:
            d["controller_type"] = self.__image_panel_controller.type
            self.__image_panel_controller.save(d)
        else:
            data_item = self.display_specifier.data_item
            if data_item:
                d["data_item_uuid"] = str(data_item.uuid)

    def restore_contents(self, d):
        controller_type = d.get("controller_type")
        self.__image_panel_controller = ImagePanelManager().make_image_panel_controller(controller_type, self, d)
        if not self.__image_panel_controller:
            data_item_uuid_str = d.get("data_item_uuid")
            if data_item_uuid_str:
                data_item = self.document_controller.document_model.get_data_item_by_uuid(uuid.UUID(data_item_uuid_str))
                if data_item:
                    self.set_displayed_data_item(data_item)

    # handle selection. selection means that the image panel is the most recent
    # item to have focus within the workspace, although it can be selected without
    # having focus. this can happen, for instance, when the user switches focus
    # to the data panel.

    def set_selected(self, selected):
        if self.__overlay_canvas_item:  # may be closed
            self.__overlay_canvas_item.selected = selected

    def _is_selected(self):
        """ Used for testing. """
        return self.__overlay_canvas_item.selected

    # this message comes from the canvas items via the on_focus_changed when their focus changes
    def set_focused(self, focused):
        self.__overlay_canvas_item.focused = focused
        if focused:
            self.document_controller.selected_image_panel = self
            self.document_controller.notify_selected_display_specifier_changed(self.display_specifier)

    def _is_focused(self):
        """ Used for testing. """
        return self.__overlay_canvas_item.focused

    @property
    def display_specifier(self):
        """Return the display specifier for the Display in this image panel."""
        return self.__display_specifier

    # sets the data item that this panel displays
    # not thread safe
    def set_displayed_data_item_and_display(self, display_specifier):
        self.__set_display(display_specifier)

    # set the default display for the data item. just a simpler method to call.
    def set_displayed_data_item(self, data_item):
        buffered_data_source = data_item.maybe_data_source if data_item else None
        display = buffered_data_source.displays[0] if buffered_data_source else None
        self.set_displayed_data_item_and_display(DataItem.DisplaySpecifier(data_item, buffered_data_source, display))

    def replace_displayed_data_item_and_display(self, display_specifier):
        """
        Replace the displayed data item. This method differs from set_display_data_item
        in that it will recognize when it is receiving a live acquisition and automatically
        set up the live image panel controller.
        """
        if self.__image_panel_controller:
            self.__image_panel_controller.close()
            self.__image_panel_controller = None
        data_item = display_specifier.data_item
        if data_item.is_live:
            hardware_source_id = data_item.get_metadata("hardware_source").get("hardware_source_id")
            hardware_source_channel_id = data_item.get_metadata("hardware_source").get("hardware_source_channel_id")
            if hardware_source_id:
                self.__image_panel_controller = LiveImagePanelController(self, hardware_source_id, hardware_source_channel_id)
        self.set_displayed_data_item_and_display(display_specifier)

    @property
    def buffered_data_source(self):
        return self.__display_specifier.buffered_data_source

    @property
    def display(self):
        return self.__display_specifier.display

    # not thread safe
    def __set_display(self, display_specifier):
        if display_specifier.buffered_data_source:
            assert isinstance(display_specifier.buffered_data_source, DataItem.BufferedDataSource)
            # keep new data in memory. if new and old values are the same, putting
            # this here will prevent the data from unloading and then reloading.
            display_specifier.buffered_data_source.increment_data_ref_count()
        # track data item in this class to report changes
        if self.__display_specifier.buffered_data_source:
            self.__display_specifier.buffered_data_source.decrement_data_ref_count()  # don't keep data in memory anymore
        if self.__display_specifier.display:
            self.__display_specifier.display.remove_listener(self)
        self.__display_specifier = copy.copy(display_specifier)
        # these connections should be configured after the messages above.
        # the instant these are added, we may be receiving messages from threads.
        if self.__display_specifier.display:
            self.__display_specifier.display.add_listener(self)  # for display_changed
        self.__update_display_canvas(self.__display_specifier)

    # this message comes from the document model.
    def data_item_deleted(self, deleted_data_item):
        data_item = self.display_specifier.data_item
        # if our item gets deleted, clear the selection
        if deleted_data_item == data_item:
            self.__set_display(DataItem.DisplaySpecifier())

    # this gets called when the user initiates a drag in the drag control to move the panel around
    def __begin_drag(self):
        if self.__display_specifier.data_item is not None:
            mime_data = self.ui.create_mime_data()
            mime_data.set_data_as_string("text/data_item_uuid", str(self.__display_specifier.data_item.uuid))
            root_canvas_item = self.canvas_item.root_container
            thumbnail_data = self.__display_specifier.display.get_processed_data("thumbnail")
            def drag_finished(action):
                if action == "move" and self.document_controller.replaced_data_item is not None:
                    data_item = self.document_controller.replaced_data_item
                    buffered_data_source = data_item.maybe_data_source if data_item else None
                    display = buffered_data_source.displays[0] if buffered_data_source else None
                    display_specifier = DataItem.DisplaySpecifier(data_item, buffered_data_source, display)
                    self.__set_display(display_specifier)
                    self.document_controller.replaced_data_item = None
            root_canvas_item.canvas_widget.drag(mime_data, thumbnail_data, drag_finished_fn=drag_finished)

    def __sync_data_item(self):
        if self.__display_specifier.data_item is not None:
            self.document_controller.select_data_item_in_data_panel(self.__display_specifier.data_item)

    def __close_image_panel(self):
        if len(self.workspace_controller.image_panels) > 1:
            self.workspace_controller.remove_image_panel(self)

    # this message comes from the display associated with this panel.
    # the connection is established in __set_display via display.add_listener.
    # this will be called when anything in the data item changes, including things
    # like graphics or the data itself.
    # thread safe (may be called from data_item_content_changed).
    def display_changed(self, display):
        with self.__pending_update_lock:
            self.__pending_display_specifier = copy.copy(self.__display_specifier)
            self.__pending_display_specifier.display = display
        def update_display_canvas_task():
            # if there is a pending display update, do it.
            # update_display_canvas will clear pending updates.
            # this ensures only the latest one is done.
            with self.__pending_update_lock:
                if self.__pending_display_specifier.display:
                    self.__update_display_canvas(self.__pending_display_specifier)
        self.queue_task(update_display_canvas_task)

    # update the display canvas, etc.
    # clear any pending display update at the end
    # not thread safe
    def __update_display_canvas(self, display_specifier):
        if self.__header_canvas_item:  # may be closed
            self.__header_canvas_item.title = self.document_controller.get_displayed_title_for_data_item(display_specifier.data_item)
        display_type = None
        data_and_calibration = display_specifier.display.data_and_calibration if display_specifier.display else None
        if data_and_calibration:
            if data_and_calibration.is_data_1d:
                display_type = "line_plot"
            elif data_and_calibration.is_data_2d or data_and_calibration.is_data_3d:
                display_type = "image"
        if display_type != self.__display_type:
            if self.display_canvas_item:
                self.__content_canvas_item.remove_canvas_item(self.display_canvas_item)
                self.display_canvas_item = None
            if display_type == "line_plot":
                self.display_canvas_item = LinePlotCanvasItem(self)
                self.__content_canvas_item.insert_canvas_item(0, self.display_canvas_item)
            elif display_type == "image":
                self.display_canvas_item = ImageCanvasItem(self)
                self.__content_canvas_item.insert_canvas_item(0, self.display_canvas_item)
                self.display_canvas_item.image_canvas_mode = "fit"
                self.display_canvas_item.update_image_canvas_size()
            self.__display_type = display_type
            if self.__content_canvas_item:
                self.__content_canvas_item.update()
        if self.display_canvas_item:  # may be closed
            self.display_canvas_item.update_display(display_specifier)
        if self.__content_canvas_item:  # may be closed
            self.__content_canvas_item.wants_mouse_events = self.display_canvas_item is None
        selected = self.document_controller.selected_image_panel == self
        if self.__overlay_canvas_item:  # may be closed
            self.__overlay_canvas_item.selected = display_specifier.display is not None and selected
        with self.__pending_update_lock:
            self.__pending_display_specifier = DataItem.DisplaySpecifier()

    # ths message comes from the canvas item via the delegate.
    def image_panel_key_pressed(self, key):
        #logging.debug("text=%s key=%s mod=%s", key.text, hex(key.key), key.modifiers)
        # if key.text == "b" or key.text == "a":
        #     if self.__image_panel_controller:
        #         self.__image_panel_controller.close()
        #         self.__image_panel_controller = None
        #     elif key.text == "a":
        #         self.__image_panel_controller = LiveImagePanelController(self)
        #     elif key.text == "b":
        #         self.__image_panel_controller = BrowserImagePanelController(self)
        #     return True
        return ImagePanelManager().key_pressed(self, key)

    def image_panel_mouse_clicked(self, image_position, modifiers):
        ImagePanelManager().mouse_clicked(self, self.display_specifier.data_item, image_position, modifiers)

    def image_panel_get_font_metrics(self, font, text):
        return self.ui.get_font_metrics(font, text)

    def image_panel_get_tool_mode(self):
        return self.document_controller.tool_mode

    def image_panel_set_tool_mode(self, tool_mode):
        self.document_controller.tool_mode = tool_mode

    def image_panel_show_context_menu(self, gx, gy):
        self.document_controller.show_context_menu_for_data_item(self.document_controller.document_model, self.display_specifier.data_item, gx, gy)

    def image_panel_cursor_changed(self, source, display, pos, image_size):
        self.document_controller.cursor_changed(source, display, pos, image_size)

    def image_panel_delete_key_pressed(self):
        if self.document_controller.remove_graphic():
            return True
        self.set_displayed_data_item(None)
        return False

    def __replace_displayed_data_item(self, data_item):
        self.document_controller.replaced_data_item = self.display_specifier.data_item
        self.set_displayed_data_item(data_item)

    def handle_drag_enter(self, mime_data):
        if self.workspace_controller:
            return self.workspace_controller.handle_drag_enter(self, mime_data)
        return "ignore"

    def handle_drag_leave(self):
        if self.workspace_controller:
            return self.workspace_controller.handle_drag_leave(self)
        return False

    def handle_drag_move(self, mime_data, x, y):
        if self.workspace_controller:
            return self.workspace_controller.handle_drag_move(self, mime_data, x, y)
        return "ignore"

    def handle_drop(self, mime_data, region, x, y):
        if self.workspace_controller:
            return self.workspace_controller.handle_drop(self, mime_data, region, x, y)
        return "ignore"


# image panel manager acts as a broker for significant events occurring
# regarding image panels. listeners can attach themselves to this object
# and receive messages regarding image panels. for instance, when the user
# presses a key on an image panel that isn't handled directly by the image
# panel, listeners can be advised of this event.
class ImagePanelManager(Observable.Broadcaster):
    __metaclass__ = Decorators.Singleton

    def __init__(self):
        super(ImagePanelManager, self).__init__()
        self.__image_panel_controllers = dict()  # maps controller_type to make_fn

    # events from the image panels
    def key_pressed(self, image_panel, key):
        self.notify_listeners("image_panel_key_pressed", image_panel, key)
        return False

    def mouse_clicked(self, image_panel, data_item, image_position, modifiers):
        self.notify_listeners("image_panel_mouse_clicked", image_panel, data_item, image_position, modifiers)
        return False

    def register_image_panel_controller(self, controller_type, make_fn):
        self.__image_panel_controllers[controller_type] = make_fn

    def unregister_image_panel_controller(self, controller_type):
        del self.__image_panel_controllers[controller_type]

    def make_image_panel_controller(self, controller_type, image_panel, d):
        if controller_type in self.__image_panel_controllers:
            return self.__image_panel_controllers[controller_type].make(image_panel, d)
        return None


ImagePanelManager().register_image_panel_controller("browser", BrowserImagePanelController)
ImagePanelManager().register_image_panel_controller("live", LiveImagePanelController)


class InfoPanel(Panel.Panel):

    """
    The info panel will display cursor information. user interface items that want to
    update the cursor info should called cursor_changed on the document controller.
    This info panel will listen to the document controller for cursor updates and update
    itself in response. all cursor update calls are thread safe. this class uses periodic
    to do ui updates from the main thread.
    """

    def __init__(self, document_controller, panel_id, properties):
        super(InfoPanel, self).__init__(document_controller, panel_id, _("Info"))

        ui = document_controller.ui

        # used to maintain the display when cursor is not moving
        self.__last_source = None

        position_label = ui.create_label_widget(_("Position:"))
        self.position_text = ui.create_label_widget()
        value_label = ui.create_label_widget(_("Value:"))
        self.value_text = ui.create_label_widget()

        position_row = ui.create_row_widget(properties={"spacing": 6})
        position_row.add(position_label)
        position_row.add(self.position_text)
        position_row.add_stretch()

        value_row = ui.create_row_widget(properties={"spacing": 6})
        value_row.add(value_label)
        value_row.add(self.value_text)
        value_row.add_stretch()

        properties["spacing"] = 2
        properties["margin"] = 6
        column = ui.create_column_widget(properties)
        column.add(position_row)
        column.add(value_row)
        column.add_stretch()

        self.widget = column

        # connect self as listener. this will result in calls to cursor_changed
        self.document_controller.add_listener(self)

    def close(self):
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        self.clear_task("position_and_value")
        # finish closing
        super(InfoPanel, self).close()

    # this message is received from the document controller.
    # it is established using add_listener
    def cursor_changed(self, source, display, pos, data_size):
        def get_value_text(value, intensity_calibration):
            if value is not None:
                return unicode(intensity_calibration.convert_to_calibrated_value_str(value))
            elif value is None:
                return _("N/A")
            else:
                return str(value)
        position_text = ""
        value_text = ""
        data_and_calibration = display.data_and_calibration if display else None
        if data_and_calibration and data_size:
            dimensional_calibrations = data_and_calibration.dimensional_calibrations if display.display_calibrated_values else [Calibration.Calibration() for i in xrange(0, len(display.preview_2d_shape))]
            intensity_calibration = data_and_calibration.intensity_calibration if display.display_calibrated_values else Calibration.Calibration()
            if pos and len(pos) == 3:
                # TODO: fix me 3d
                # 3d image
                # make sure the position is within the bounds of the image
                if pos[0] >= 0 and pos[0] < data_size[0] and pos[1] >= 0 and pos[1] < data_size[1] and pos[2] >= 0 and pos[2] < data_size[2]:
                    position_text = u"{0}, {1}, {2}".format(dimensional_calibrations[2].convert_to_calibrated_value_str(pos[2]),
                                                            dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1]),
                                                            dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0]))
                    value_text = get_value_text(data_and_calibration.get_data_value(pos), intensity_calibration)
            if pos and len(pos) == 2:
                # 2d image
                # make sure the position is within the bounds of the image
                if pos[0] >= 0 and pos[0] < data_size[0] and pos[1] >= 0 and pos[1] < data_size[1]:
                    position_text = u"{0}, {1}".format(dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1]),
                                                       dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0]))
                    value_text = get_value_text(data_and_calibration.get_data_value(pos), intensity_calibration)
            if pos and len(pos) == 1:
                # 1d plot
                # make sure the position is within the bounds of the line plot
                if pos[0] >= 0 and pos[0] < data_size[0]:
                    position_text = u"{0}".format(dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0]))
                    value_text = get_value_text(data_and_calibration.get_data_value(pos), intensity_calibration)
            self.__last_source = source
        if self.__last_source == source:
            def update_position_and_value(position_text, value_text):
                self.position_text.text = position_text
                self.value_text.text = value_text
            self.add_task("position_and_value", lambda: update_position_and_value(position_text, value_text))
