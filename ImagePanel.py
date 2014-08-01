# standard libraries
import collections
import copy
import gettext
import logging
import math
import uuid

# third party libraries

# local libraries
from nion.swift import Decorators
from nion.swift import HistogramPanel
from nion.swift import Panel
from nion.swift.model import Calibration
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.swift.model import Graphics
from nion.swift.model import Image
from nion.swift.model import LineGraphCanvasItem
from nion.swift.model import Region
from nion.ui import Binding
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
        ms0 = self.map_point_image_norm_to_widget((0,0))
        return ms - ms0

    def map_size_image_to_image_norm(self, s):
        ms = self.map_point_image_to_image_norm(s)
        ms0 = self.map_point_image_to_image_norm((0,0))
        return ms - ms0

    def map_size_widget_to_image_norm(self, s):
        ms = self.map_point_widget_to_image_norm(s)
        ms0 = self.map_point_widget_to_image_norm((0,0))
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
            return Geometry.FloatPoint(y=image_y, x=image_x) # c-indexing
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

        display = self.display

        if display:

            # canvas size
            canvas_width = self.canvas_size[1]
            canvas_height = self.canvas_size[0]

            drawing_context.save()
            drawing_context.begin_path()

            image_canvas_size = self.image_canvas_size
            image_canvas_origin = self.image_canvas_origin
            calibrations = display.data_item.calculated_calibrations
            if calibrations is not None and image_canvas_origin is not None and image_canvas_size is not None:  # display scale marker?
                calibrations = display.data_item.calculated_calibrations
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
                    drawing_context.stroke_style="#000"
                    drawing_context.stroke()
                    drawing_context.font = "normal 14px serif"
                    drawing_context.text_baseline = "bottom"
                    drawing_context.fill_style = "#FFF"
                    drawing_context.fill_text(calibrations[1].convert_to_calibrated_size_str(scale_marker_image_width), origin[1], origin[0] - scale_marker_height - 4)
                    data_item_properties = display.data_item.get_metadata("hardware_source")
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

    def __init__(self, document_controller, image_panel):
        super(LinePlotCanvasItem, self).__init__()

        font_size = 12

        # ugh
        self.document_controller = document_controller
        self.image_panel = image_panel

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
        self.__display = None
        self.__paint_thread = ThreadPool.ThreadIntervalDispatcher(lambda: self.paint_display_on_thread())
        self.__paint_thread.start()

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

        self.__layout_state = "no_info"

    def close(self):
        self.__paint_thread.close()
        self.__paint_thread = None
        self.update_display(None)
        # call super
        super(LinePlotCanvasItem, self).close()

    # when the display changes, set the data using this property.
    # doing this will queue an item in the paint thread to repaint.
    def __get_display(self):
        return self.__display
    display = property(__get_display)

    def update_display(self, display):
        # first take care of listeners and update the __display field
        old_display = self.__display
        if old_display and display != old_display:
            old_display.remove_listener(self)
        self.__display = display
        if display and display != old_display:
            display.add_listener(self)  # for selection_changed
        # next get rid of data associated with canvas items
        if self.__display is None:
            # handle case where display is empty
            data_info = LineGraphCanvasItem.LineGraphDataInfo()
            self.__update_data_info(data_info)
            self.line_graph_regions_canvas_item.regions = list()
            self.__layout_state = "done_layout"
        else:
            self.selection_changed(self.__display.graphic_selection)
            self.__layout_state = "no_info"
        # update the cursor info
        self.__update_cursor_info()
        # finally, trigger the paint thread (if there still is one) to update
        if self.__paint_thread:
            self.__paint_thread.trigger()

    def wait_for_paint(self):
        self.__paint_thread.trigger(wait=True)

    def selection_changed(self, graphic_selection):
        # this message will come directly from the display when the graphic selection changes
        regions = list()
        display = self.display
        data_item = display.data_item
        data_length = data_item.spatial_shape[0]
        spatial_calibration = data_item.calculated_calibrations[0] if display.display_calibrated_values else Calibration.Calibration()
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

    def update_layout(self, canvas_origin, canvas_size):
        super(LinePlotCanvasItem, self).update_layout(canvas_origin, canvas_size)
        self.__layout_state = "done_layout"

    def repaint_if_needed(self):
        if self.__layout_state == "done_layout":
            super(LinePlotCanvasItem, self).repaint_if_needed()
        elif self.__layout_state == "has_info":
            self.update_layout(self.canvas_origin, self.canvas_size)
            self.update()
            super(LinePlotCanvasItem, self).repaint_if_needed()
        else:
            # it is not legal to call 'update' from within repaint. so queue
            # this to the future. overall, this is a bad architecture since
            # the layout is not really complete in this case. hopefully this will
            # go away once the canvas updating is reworked to ensure repaint only
            # happens after layout. for now, this behavior is hacked into this class.
            self.image_panel.add_task("update", lambda: self.update())

    # this method will be invoked from the paint thread.
    # data is calculated and then sent to the line graph canvas item.
    def paint_display_on_thread(self):

        display = self.__display

        if display:
            # grab the data item
            data_item = display.data_item

            # make sure we have the correct data
            assert display is not None
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
            y_min = display.y_min
            y_max = display.y_max
            left_channel = display.left_channel
            right_channel = display.right_channel
            left_channel = left_channel if left_channel is not None else 0
            right_channel = right_channel if right_channel is not None else data.shape[0]
            left_channel, right_channel = min(left_channel, right_channel), max(left_channel, right_channel)
            data_info = LineGraphCanvasItem.LineGraphDataInfo(data)
            data_info.data_min = y_min
            data_info.data_max = y_max
            data_info.data_left = left_channel
            data_info.data_right = right_channel
            data_info.intensity_calibration = data_item.calculated_intensity_calibration if display.display_calibrated_values else None
            data_info.spatial_calibration = data_item.calculated_calibrations[0] if display.display_calibrated_values else None
            self.__update_data_info(data_info)

    def __update_data_info(self, data_info):
        self.line_graph_canvas_item.data_info = copy.copy(data_info)
        # self.line_graph_canvas_item.update()  # unused, setting data_info handles this automatically
        self.line_graph_regions_canvas_item.data_info = data_info
        self.line_graph_regions_canvas_item.update()
        canvas_bounds = self.canvas_bounds
        self.line_graph_vertical_axis_label_canvas_item.data_info = data_info
        if canvas_bounds:
            self.line_graph_vertical_axis_label_canvas_item.size_to_content(self.document_controller.ui, canvas_bounds)
        self.line_graph_vertical_axis_label_canvas_item.update()
        self.line_graph_vertical_axis_scale_canvas_item.data_info = data_info
        if canvas_bounds:
            self.line_graph_vertical_axis_scale_canvas_item.size_to_content(self.document_controller.ui, canvas_bounds)
        self.line_graph_vertical_axis_scale_canvas_item.update()
        self.line_graph_vertical_axis_ticks_canvas_item.data_info = data_info
        self.line_graph_vertical_axis_ticks_canvas_item.update()
        self.line_graph_horizontal_axis_label_canvas_item.data_info = data_info
        if canvas_bounds:
            self.line_graph_horizontal_axis_label_canvas_item.size_to_content(self.document_controller.ui, canvas_bounds)
        self.line_graph_horizontal_axis_label_canvas_item.update()
        self.line_graph_horizontal_axis_scale_canvas_item.data_info = data_info
        self.line_graph_horizontal_axis_scale_canvas_item.update()
        self.line_graph_horizontal_axis_ticks_canvas_item.data_info = data_info
        self.line_graph_horizontal_axis_ticks_canvas_item.update()
        if canvas_bounds:
            self.update_layout(canvas_bounds.origin, canvas_bounds.size)
            self.update()
        self.__layout_state = "has_info"

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
        if self.document_controller.tool_mode == "pointer":
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
        if self.document_controller.tool_mode == "pointer":
            if self.line_graph_regions_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_regions_canvas_item)):
                self.begin_tracking_regions(pos, modifiers)
                return True
            elif self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_horizontal_axis_group_canvas_item)):
                self.begin_tracking_horizontal(pos, rescale=modifiers.control)
                return True
            elif self.line_graph_vertical_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_vertical_axis_group_canvas_item)):
                self.begin_tracking_vertical(pos, rescale=modifiers.control)
                return True
        elif self.document_controller.tool_mode == "interval":
            if self.line_graph_regions_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_regions_canvas_item)):
                data_size = self.__get_data_size()
                display = self.display
                if display and data_size and len(data_size) == 1:
                    widget_mapping = self.__get_mouse_mapping()
                    x = widget_mapping.map_point_widget_to_channel_norm(pos)
                    region = Region.IntervalRegion()
                    region.start = x
                    region.end = x
                    display.data_item.add_region(region)  # this will also make a drawn graphic
                    # hack to select it. it will be the last item.
                    display.graphic_selection.set(len(display.drawn_graphics) - 1)
                    self.begin_tracking_regions(pos, Graphics.NullModifiers())
                return True
        return False

    def mouse_released(self, x, y, modifiers):
        if super(LinePlotCanvasItem, self).mouse_released(x, y, modifiers):
            return True
        self.end_tracking(modifiers)
        return False

    def context_menu_event(self, x, y, gx, gy):
        self.document_controller.show_context_menu_for_data_item(self.document_controller.document_model, self.display.data_item, gx, gy)
        return True

    # ths message comes from the widget
    def key_pressed(self, key):
        if super(LinePlotCanvasItem, self).key_pressed(key):
            return True
        # only handle keys if we're directly embedded in an image panel
        if not self.image_panel:
            return False
        display = self.display
        if display:
            #logging.debug("text=%s key=%s mod=%s", key.text, hex(key.key), key.modifiers)
            all_graphics = display.drawn_graphics
            graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if display.graphic_selection.contains(graphic_index)]
            if len(graphics):
                if key.is_delete:
                    self.document_controller.remove_graphic()
                    return True
                elif key.is_arrow:
                    widget_mapping = self.__get_mouse_mapping()
                    amount = 10.0 if key.modifiers.shift else 1.0
                    if key.is_left_arrow:
                        for graphic in graphics:
                            graphic.nudge(widget_mapping, (0, -amount))
                    elif key.is_right_arrow:
                        for graphic in graphics:
                            graphic.nudge(widget_mapping, (0, amount))
                    return True
        return self.image_panel.key_pressed(key)

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
        left_channel = self.line_graph_canvas_item.drawn_left_channel
        right_channel = self.line_graph_canvas_item.drawn_right_channel
        drawn_channel_per_pixel = float(right_channel - left_channel) / plot_rect.width
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
        self.__tracking_start_left_channel = self.line_graph_canvas_item.drawn_left_channel
        self.__tracking_start_right_channel = self.line_graph_canvas_item.drawn_right_channel
        self.__tracking_start_drawn_channel_per_pixel = float(self.__tracking_start_right_channel - self.__tracking_start_left_channel) / plot_rect.width
        self.__tracking_start_origin_pixel = self.__tracking_start_pos.x - plot_rect.left
        self.__tracking_start_channel = self.__tracking_start_left_channel + self.__tracking_start_origin_pixel * self.__tracking_start_drawn_channel_per_pixel

    def begin_tracking_vertical(self, pos, rescale):
        plot_origin = self.line_graph_horizontal_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
        plot_rect = self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds.translated(plot_origin)
        self.__tracking_vertical = True
        self.__tracking_rescale = rescale
        self.__tracking_start_pos = pos
        self.__tracking_start_drawn_data_min = self.line_graph_canvas_item.drawn_data_min
        self.__tracking_start_drawn_data_max = self.line_graph_canvas_item.drawn_data_max
        self.__tracking_start_drawn_data_per_pixel = self.line_graph_canvas_item.drawn_data_per_pixel  # = float(self.__tracking_start_drawn_data_max - self.__tracking_start_drawn_data_min) / (plot_rect.height - 1)
        self.__tracking_start_calibrated_data_min = self.line_graph_canvas_item.calibrated_data_min
        self.__tracking_start_calibrated_data_max = self.line_graph_canvas_item.calibrated_data_max
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
                data_min = self.__tracking_start_origin_data - new_drawn_data_per_pixel * (self.__tracking_start_origin_y)
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
            self.document_controller.tool_mode = "pointer"
        self.__tracking_horizontal = False
        self.__tracking_vertical = False
        self.__tracking_selections = False

    def __get_data_size(self):
        data_item = self.display.data_item if self.display else None
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
                    last_mouse = self.map_to_canvas_item(self.__last_mouse, self.line_graph_canvas_item)
                    pos = self.line_graph_canvas_item.map_mouse_to_position(last_mouse, data_size)
                self.document_controller.cursor_changed(self, self.display, pos, data_size)
            else:
                self.document_controller.cursor_changed(self, None, None, None)


class ImageCanvasItem(CanvasItem.CanvasItemComposition):

    def __init__(self, document_controller, image_panel):
        super(ImageCanvasItem, self).__init__()

        # ugh. these are optional.
        self.document_controller = document_controller
        self.image_panel = image_panel

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
        # info overlay (scale marker, etc.)
        self.info_overlay_canvas_item = InfoOverlayCanvasItem()
        # canvas items get added back to front
        self.add_canvas_item(self.background_canvas_item)
        self.add_canvas_item(self.scroll_area_canvas_item)
        self.add_canvas_item(self.info_overlay_canvas_item)

        # thread for drawing
        self.__display = None
        self.__paint_thread = ThreadPool.ThreadIntervalDispatcher(lambda: self.paint_display_on_thread())
        self.__paint_thread.start()

        # used for dragging graphic items
        self.graphic_drag_items = []
        self.graphic_drag_item = None
        self.graphic_part_data = {}
        self.graphic_drag_indexes = []
        self.__last_mouse = None
        self.__is_dragging = False
        self.__mouse_in = False

    def close(self):
        self.__paint_thread.close()
        self.__paint_thread = None
        self.update_display(None)
        # call super
        super(ImageCanvasItem, self).close()

    def __get_preferred_aspect_ratio(self):
        if self.display:
            spatial_shape = self.display.preview_2d_shape
            return spatial_shape[1] / spatial_shape[0] if spatial_shape[0] != 0 else 1.0
        return 1.0
    preferred_aspect_ratio = property(__get_preferred_aspect_ratio)

    # when the display changes, set the data using this property.
    # doing this will queue an item in the paint thread to repaint.
    def __get_display(self):
        return self.__display
    display = property(__get_display)

    def update_display(self, display):
        # first take care of listeners and update the __display field
        old_display = self.__display
        if old_display and display != old_display:
            old_display.remove_listener(self)
        self.__display = display
        if display and display != old_display:
            display.add_listener(self)  # for selection_changed
        # next get rid of data associated with canvas items
        if self.__display is None:
            self.bitmap_canvas_item.rgba_bitmap_data = None
            self.bitmap_canvas_item.update()
            self.graphics_canvas_item.display = None
            self.graphics_canvas_item.update()
            self.info_overlay_canvas_item.display = None
            self.info_overlay_canvas_item.update()
        else:
            self.selection_changed(self.__display.graphic_selection)
        # update the cursor info
        self.__update_cursor_info()
        # finally, trigger the paint thread (if there still is one) to update
        if self.__paint_thread:
            self.__paint_thread.trigger()

    def selection_changed(self, graphic_selection):
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
    def scroll_area_canvas_item_updated_layout(self, scroll_area_canvas_size):
        if not self.display:
            self.__last_image_norm_center = (0.5, 0.5)
            self.__last_image_zoom = 1.0
            self.info_overlay_canvas_item.image_canvas_origin = None
            self.info_overlay_canvas_item.image_canvas_size = None
            return
        if self.image_canvas_mode == "fill":
            spatial_shape = self.display.preview_2d_shape
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
            image_canvas_size = self.display.preview_2d_shape
            image_canvas_origin = (scroll_area_canvas_size[0] * 0.5 - image_canvas_size[0] * 0.5, scroll_area_canvas_size[1] * 0.5 - image_canvas_size[1] * 0.5)
            self.composite_canvas_item.update_layout(image_canvas_origin, image_canvas_size)
        else:
            c = self.__last_image_norm_center
            spatial_shape = self.display.preview_2d_shape
            image_canvas_size = (scroll_area_canvas_size[0] * self.__last_image_zoom, scroll_area_canvas_size[1] * self.__last_image_zoom)
            canvas_rect = Geometry.fit_to_size(((0, 0), image_canvas_size), spatial_shape)
            # c[0] = ((scroll_area_canvas_size[0] * 0.5 - image_canvas_origin[0]) - canvas_rect[0][0])/canvas_rect[1][0]
            image_canvas_origin_y = (scroll_area_canvas_size[0] * 0.5) - c[0] * canvas_rect[1][0] - canvas_rect[0][0]
            image_canvas_origin_x = (scroll_area_canvas_size[1] * 0.5) - c[1] * canvas_rect[1][1] - canvas_rect[0][1]
            image_canvas_origin = (image_canvas_origin_y, image_canvas_origin_x)
            self.composite_canvas_item.update_layout(image_canvas_origin, image_canvas_size)
        # the image will be drawn centered within the canvas size
        spatial_shape = self.display.preview_2d_shape
        #logging.debug("scroll_area_canvas_size %s", scroll_area_canvas_size)
        #logging.debug("image_canvas_origin %s", image_canvas_origin)
        #logging.debug("image_canvas_size %s", image_canvas_size)
        #logging.debug("spatial_shape %s", spatial_shape)
        #logging.debug("c %s %s", (scroll_area_canvas_size[0] * 0.5 - image_canvas_origin[0]) / spatial_shape[0], (scroll_area_canvas_size[1] * 0.5 - image_canvas_origin[1]) / spatial_shape[1])
        widget_mapping = WidgetImageMapping(self.display.preview_2d_shape, (0, 0), image_canvas_size)
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

    def mouse_clicked(self, x, y, modifiers):
        if super(ImageCanvasItem, self).mouse_clicked(x, y, modifiers):
            return True
        # now let the image panel handle mouse clicking if desired
        image_position = self.__get_mouse_mapping().map_point_widget_to_image((y, x))
        ImagePanelManager().mouse_clicked(self.image_panel, self.display.data_item, image_position, modifiers)
        return True

    def mouse_double_clicked(self, x, y, modifiers):
        self.set_fit_mode()
        return True

    def mouse_pressed(self, x, y, modifiers):
        if super(ImageCanvasItem, self).mouse_pressed(x, y, modifiers):
            return True
        display = self.display
        if not display:
            return False
        # figure out clicked graphic
        self.graphic_drag_items = []
        self.graphic_drag_item = None
        self.graphic_drag_item_was_selected = False
        self.graphic_part_data = {}
        self.graphic_drag_indexes = []
        if self.document_controller.tool_mode == "pointer":
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
        elif self.document_controller.tool_mode == "hand":
            self.__start_drag_pos = (y, x)
            self.__last_drag_pos = (y, x)
            self.__is_dragging = True
        return True

    def mouse_released(self, x, y, modifiers):
        if super(ImageCanvasItem, self).mouse_released(x, y, modifiers):
            return True
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
        dx = dx if is_horizontal else 0.0
        dy = dy if not is_horizontal else 0.0
        self.update_image_canvas_position((-dy, -dx))

    def pan_gesture(self, dx, dy):
        self.update_image_canvas_position((dy, dx))
        return True

    def context_menu_event(self, x, y, gx, gy):
        self.document_controller.show_context_menu_for_data_item(self.document_controller.document_model, self.display.data_item, gx, gy)
        return True

    # ths message comes from the widget
    def key_pressed(self, key):
        if super(ImageCanvasItem, self).key_pressed(key):
            return True
        # only handle keys if we're directly embedded in an image panel
        if not self.image_panel:
            return False
        display = self.display
        if display:
            #logging.debug("text=%s key=%s mod=%s", key.text, hex(key.key), key.modifiers)
            all_graphics = display.drawn_graphics
            graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if display.graphic_selection.contains(graphic_index)]
            if len(graphics):
                if key.is_delete:
                    self.document_controller.remove_graphic()
                    return True
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
                self.document_controller.cursor_changed(self, self.display, pos, image_size)
            else:
                self.document_controller.cursor_changed(self, None, None, None)

    # this method will be invoked from the paint thread.
    # data is calculated and then sent to the image canvas item.
    def paint_display_on_thread(self):

        display = self.__display

        if display:
            # grab the data item too
            data_item = display.data_item

            # make sure we have the correct data
            assert data_item is not None
            # TODO: fix me 3d
            assert data_item.is_data_2d or data_item.is_data_3d

            # grab the bitmap image
            rgba_image = display.preview_2d
            self.bitmap_canvas_item.rgba_bitmap_data = rgba_image

            self.graphics_canvas_item.display = display
            self.graphics_canvas_item.update()

            self.info_overlay_canvas_item.display = display
            self.info_overlay_canvas_item.update()

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

    def __init__(self, image_panel):
        super(ImagePanelOverlayCanvasItem, self).__init__()
        self.image_panel = image_panel
        self.__dimmed = False
        self.__focused = False
        self.__selected = False
        self.__selected_style = "#CCC"  # TODO: platform dependent
        self.__focused_style = "#3876D6"  # TODO: platform dependent

    def __get_dimmed(self):
        return self.__dimmed
    def __set_dimmed(self, dimmed):
        if self.__dimmed != dimmed:
            self.__dimmed = dimmed
            self.update()
    dimmed = property(__get_dimmed, __set_dimmed)

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

    def _repaint(self, drawing_context):

        super(ImagePanelOverlayCanvasItem, self)._repaint(drawing_context)

        # canvas size
        canvas_width = self.canvas_size[1]
        canvas_height = self.canvas_size[0]

        if self.__dimmed:

            drawing_context.save()

            drawing_context.begin_path()
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
        self.dimmed = True
        if self.image_panel:
            return self.image_panel.handle_drag_enter(mime_data)
        return "ignore"

    def drag_leave(self):
        self.dimmed = False
        if self.image_panel:
            self.image_panel.handle_drag_leave()
        return False

    def drag_move(self, mime_data, x, y):
        if self.image_panel:
            return self.image_panel.handle_drag_move(mime_data, x, y)
        return "ignore"

    def drop(self, mime_data, x, y):
        self.dimmed = False
        if self.image_panel:
            return self.image_panel.handle_drop(mime_data, x, y)
        return "ignore"


class ImagePanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(ImagePanel, self).__init__(document_controller, panel_id, _("Image Panel"))

        self.__display = None

        self.root_canvas_item = CanvasItem.RootCanvasItem(document_controller.ui)
        self.root_canvas_item.focusable = True
        self.root_canvas_item.on_focus_changed = lambda focused: self.set_focused(focused)
        self.overlay_canvas_item = ImagePanelOverlayCanvasItem(self)
        self.root_canvas_item.add_canvas_item(self.overlay_canvas_item)
        self.header_controller = Panel.HeaderWidgetController(self.ui, display_drag_control=True, display_sync_control=True)
        self.header_controller.on_drag_pressed = lambda: self.__begin_drag()
        self.header_controller.on_sync_clicked = lambda: self.__sync_data_item()
        self.widget = self.ui.create_column_widget()
        self.widget.add(self.header_controller.canvas_widget)
        self.widget.add(self.root_canvas_item.canvas_widget, fill=True)

        self.document_controller.register_image_panel(self)

        # this results in data_item_deleted messages
        self.document_controller.document_model.add_listener(self)

        self.display_canvas_item = None
        self.__display_type = None

        self.closed = False

    def close(self):
        self.closed = True
        self.root_canvas_item.close()
        self.display_canvas_item = None  # now closed
        self.document_controller.document_model.remove_listener(self)
        self.document_controller.unregister_image_panel(self)
        self.__set_display(None)  # required before destructing display thread
        super(ImagePanel, self).close()

    # return a dictionary that can be used to restore the content of this image panel
    def save_content(self):
        content = {}
        data_item = self.get_displayed_data_item()
        if data_item:
            content["data-item"] = data_item.uuid
        return content

    # restore content from dictionary and document controller
    def restore_content(self, content, document_controller):
        if "data-item" in content:
            data_item_uuid = content["data-item"]
            data_item = document_controller.document_model.get_data_item_by_key(data_item_uuid)
            if data_item:
                self.__set_display(data_item.displays[0])

    def set_selected(self, selected):
        self.overlay_canvas_item.selected = selected

    # this message comes from the canvas items via the on_focus_changed when their focus changes
    def set_focused(self, focused):
        if self.closed: return  # argh
        self.overlay_canvas_item.focused = focused
        if focused:
            self.document_controller.selected_image_panel = self
            self.document_controller.set_selected_data_item(self.get_displayed_data_item())

    # gets the data item that this panel displays
    def get_displayed_data_item(self):
        return self.__display.data_item if self.__display else None

    # sets the data item that this panel displays
    def set_displayed_data_item(self, data_item):
        assert data_item is None or isinstance(data_item, DataItem.DataItem), data_item
        self.__set_display(data_item.displays[0] if data_item else None)

    def __get_display(self):
        return self.__display
    def __set_display(self, display):
        if display:
            assert isinstance(display, Display.Display)
            # keep new data in memory. if new and old values are the same, putting
            # this here will prevent the data from unloading and then reloading.
            display.data_item.increment_data_ref_count()
        # track data item in this class to report changes
        if self.__display:
            self.__display.data_item.decrement_data_ref_count()  # don't keep data in memory anymore
            self.__display.remove_listener(self)
        data_item = display.data_item if display else None
        self.__display = display
        # these connections should be configured after the messages above.
        # the instant these are added, we may be receiving messages from threads.
        if self.__display:
            self.__display.add_listener(self)  # for display_changed
        self.display_changed(self.__display)
    display = property(__get_display)  # read only, for tests only

    # this message comes from the document model.
    def data_item_deleted(self, deleted_data_item):
        data_item = self.get_displayed_data_item()
        # if our item gets deleted, clear the selection
        if deleted_data_item == data_item:
            self.__set_display(None)

    # this gets called when the user initiates a drag in the drag control to move the panel around
    def __begin_drag(self):
        data_item = self.get_displayed_data_item()
        if data_item is not None:
            mime_data = self.ui.create_mime_data()
            mime_data.set_data_as_string("text/data_item_uuid", str(data_item.uuid))
            action = self.widget.drag(mime_data)
            if action == "move" and self.document_controller.replaced_data_item is not None:
                self.__set_display(self.document_controller.replaced_data_item.displays[0])
                self.document_controller.replaced_data_item = None

    def __sync_data_item(self):
        data_item = self.get_displayed_data_item()
        if data_item is not None:
            self.document_controller.sync_data_item(data_item)

    # this message comes from the data item associated with this panel.
    # the connection is established in __set_display via data_item.add_listener.
    # this will be called when anything in the data item changes, including things
    # like graphics or the data itself.
    def display_changed(self, display):
        data_item = display.data_item if display else None
        self.header_controller.title = data_item.title if data_item else unicode()
        display_type = None
        if data_item:
            if data_item.is_data_1d:
                display_type = "line_plot"
            elif data_item.is_data_2d or data_item.is_data_3d:
                display_type = "image"
        if display_type != self.__display_type:
            if self.display_canvas_item:
                self.root_canvas_item.remove_canvas_item(self.display_canvas_item)
                self.display_canvas_item = None
            if display_type == "line_plot":
                self.display_canvas_item = LinePlotCanvasItem(self.document_controller, self)
                self.root_canvas_item.insert_canvas_item(0, self.display_canvas_item)
            elif display_type == "image":
                self.display_canvas_item = ImageCanvasItem(self.document_controller, self)
                self.root_canvas_item.insert_canvas_item(0, self.display_canvas_item)
                self.display_canvas_item.image_canvas_mode = "fit"
                self.display_canvas_item.update_image_canvas_size()
            self.__display_type = display_type
            self.root_canvas_item.update()
        if self.display_canvas_item:
            self.display_canvas_item.update_display(display)
        selected = self.document_controller.selected_image_panel == self
        self.overlay_canvas_item.selected = display is not None and selected

    # ths message comes from the widget
    def key_pressed(self, key):
        #logging.debug("text=%s key=%s mod=%s", key.text, hex(key.key), key.modifiers)
        return ImagePanelManager().key_pressed(self, key)

    def handle_drag_enter(self, mime_data):
        if mime_data.has_format("text/data_item_uuid"):
            return "copy"
        if mime_data.has_format("text/uri-list"):
            return "copy"
        return "ignore"

    def handle_drag_leave(self):
        return False

    def handle_drag_move(self, mime_data, x, y):
        if mime_data.has_format("text/data_item_uuid"):
            return "copy"
        if mime_data.has_format("text/uri-list"):
            return "copy"
        return "ignore"

    def handle_drop(self, mime_data, x, y):
        if mime_data.has_format("text/data_item_uuid"):
            data_item_uuid = uuid.UUID(mime_data.data_as_string("text/data_item_uuid"))
            data_item = self.document_controller.document_model.get_data_item_by_key(data_item_uuid)
            self.document_controller.replaced_data_item = self.get_displayed_data_item()
            self.__set_display(data_item.displays[0])
            return "copy"
        if mime_data.has_format("text/uri-list"):
            def receive_files_complete(received_data_items):
                def update_displayed_data_item():
                    self.document_controller.replaced_data_item = self.get_displayed_data_item()
                    self.__set_display(received_data_items[0].displays[0])
                if len(received_data_items) > 0:
                    self.queue_task(update_displayed_data_item)
            index = len(self.document_controller.document_model.data_items)
            self.document_controller.receive_files(mime_data.file_paths, None, index, threaded=True, completion_fn=receive_files_complete)
            return "copy"
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
        pass
    # events from the image panels
    def key_pressed(self, image_panel, key):
        return self.notify_listeners("image_panel_key_pressed", image_panel, key)
    def mouse_clicked(self, image_panel, data_item, image_position, modifiers):
        return self.notify_listeners("image_panel_mouse_clicked", image_panel, data_item, image_position, modifiers)


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
        self.closed = True
        # disconnect self as listener
        self.document_controller.remove_listener(self)
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
        if display and data_size:
            calibrations = display.data_item.calculated_calibrations if display.display_calibrated_values else [Calibration.Calibration() for i in xrange(0, len(display.preview_2d_shape))]
            intensity_calibration = display.data_item.calculated_intensity_calibration if display.display_calibrated_values else Calibration.Calibration()
            if pos and len(pos) == 3:
                # TODO: fix me 3d
                # 3d image
                # make sure the position is within the bounds of the image
                if pos[0] >= 0 and pos[0] < data_size[0] and pos[1] >= 0 and pos[1] < data_size[1] and pos[2] >= 0 and pos[2] < data_size[2]:
                    position_text = u"{0}, {1}, {2}".format(calibrations[2].convert_to_calibrated_value_str(pos[2]),
                                                            calibrations[1].convert_to_calibrated_value_str(pos[1]),
                                                            calibrations[0].convert_to_calibrated_value_str(pos[0]))
                    value_text = get_value_text(display.data_item.get_data_value(pos), intensity_calibration)
            if pos and len(pos) == 2:
                # 2d image
                # make sure the position is within the bounds of the image
                if pos[0] >= 0 and pos[0] < data_size[0] and pos[1] >= 0 and pos[1] < data_size[1]:
                    position_text = u"{0}, {1}".format(calibrations[1].convert_to_calibrated_value_str(pos[1]),
                                                       calibrations[0].convert_to_calibrated_value_str(pos[0]))
                    value_text = get_value_text(display.data_item.get_data_value(pos), intensity_calibration)
            if pos and len(pos) == 1:
                # 1d plot
                # make sure the position is within the bounds of the line plot
                if pos[0] >= 0 and pos[0] < data_size[0]:
                    position_text = u"{0}".format(calibrations[0].convert_to_calibrated_value_str(pos[0]))
                    value_text = get_value_text(display.data_item.get_data_value(pos), intensity_calibration)
            self.__last_source = source
        if self.__last_source == source:
            def update_position_and_value(position_text, value_text):
                self.position_text.text = position_text
                self.value_text.text = value_text
            self.add_task("position_and_value", lambda: update_position_and_value(position_text, value_text))
