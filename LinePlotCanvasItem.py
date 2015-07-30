# futures
from __future__ import absolute_import
from __future__ import division

# standard libraries
import collections
import copy
import math

# third party libraries
# None

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import Graphics
from nion.swift.model import Image
from nion.swift.model import LineGraphCanvasItem
from nion.swift.model import Region
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.ui import Geometry


class LinePlotCanvasItemMapping(object):

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


class LinePlotCanvasItem(CanvasItem.LayerCanvasItem):

    """Display a line plot.

    Callers are expected to pass in a font metrics function and a delegate.

    They are expected to call the following functions to update the display:
        update_display_state(data_and_calibration, display_properties, display_calibrated_values)
        update_regions(data_and_calibration, graphic_selection, graphics, display_calibrated_values)

    The delegate is expected to handle the following events:
        add_index_to_selection(index)
        remove_index_from_selection(index)
        set_selection(index)
        clear_selection()
        add_and_select_region(region)
        nudge_selected_graphics(mapping, delta)
        update_graphics(widget_mapping, graphic_drag_items, graphic_drag_part, graphic_part_data, graphic_drag_start_pos, pos, modifiers)
        tool_mode (property)
        show_context_menu(gx, gy)
        begin_mouse_tracking(self)
        end_mouse_tracking()
        mouse_clicked(image_position, modifiers)
        delete_key_pressed()
        cursor_changed(source, pos)
        update_display_properties(display_properties)

    The line plot display layout is dependent on the data of the line plot since the width of the vertical axis is
    dependent on the data. This display currently handles that within the _repaint method, but care must be taken to
    not trigger another repaint from within the existing repaint.
    """

    def __init__(self, get_font_metrics_fn, delegate):
        super(LinePlotCanvasItem, self).__init__()

        self.__get_font_metrics_fn = get_font_metrics_fn
        self.delegate = delegate

        self.wants_mouse_events = True

        font_size = 12

        line_graph_canvas_area_item = CanvasItem.CanvasItemComposition()
        self.line_graph_canvas_item = LineGraphCanvasItem.LineGraphCanvasItem()
        self.__line_graph_regions_canvas_item = LineGraphCanvasItem.LineGraphRegionsCanvasItem()
        line_graph_canvas_area_item.add_canvas_item(self.line_graph_canvas_item)
        line_graph_canvas_area_item.add_canvas_item(self.__line_graph_regions_canvas_item)

        self.__line_graph_vertical_axis_label_canvas_item = LineGraphCanvasItem.LineGraphVerticalAxisLabelCanvasItem()
        self.__line_graph_vertical_axis_scale_canvas_item = LineGraphCanvasItem.LineGraphVerticalAxisScaleCanvasItem()
        self.__line_graph_vertical_axis_ticks_canvas_item = LineGraphCanvasItem.LineGraphVerticalAxisTicksCanvasItem()
        self.__line_graph_vertical_axis_group_canvas_item = CanvasItem.CanvasItemComposition()
        self.__line_graph_vertical_axis_group_canvas_item.layout = CanvasItem.CanvasItemRowLayout(spacing=4)
        self.__line_graph_vertical_axis_group_canvas_item.add_canvas_item(self.__line_graph_vertical_axis_label_canvas_item)
        self.__line_graph_vertical_axis_group_canvas_item.add_canvas_item(self.__line_graph_vertical_axis_scale_canvas_item)
        self.__line_graph_vertical_axis_group_canvas_item.add_canvas_item(self.__line_graph_vertical_axis_ticks_canvas_item)

        self.__line_graph_horizontal_axis_label_canvas_item = LineGraphCanvasItem.LineGraphHorizontalAxisLabelCanvasItem()
        self.__line_graph_horizontal_axis_scale_canvas_item = LineGraphCanvasItem.LineGraphHorizontalAxisScaleCanvasItem()
        self.__line_graph_horizontal_axis_ticks_canvas_item = LineGraphCanvasItem.LineGraphHorizontalAxisTicksCanvasItem()
        self.line_graph_horizontal_axis_group_canvas_item = CanvasItem.CanvasItemComposition()
        self.line_graph_horizontal_axis_group_canvas_item.layout = CanvasItem.CanvasItemColumnLayout(spacing=4)
        self.line_graph_horizontal_axis_group_canvas_item.add_canvas_item(self.__line_graph_horizontal_axis_ticks_canvas_item)
        self.line_graph_horizontal_axis_group_canvas_item.add_canvas_item(self.__line_graph_horizontal_axis_scale_canvas_item)
        self.line_graph_horizontal_axis_group_canvas_item.add_canvas_item(self.__line_graph_horizontal_axis_label_canvas_item)

        # create the grid item holding the line graph and each axes label
        line_graph_group_canvas_item = CanvasItem.CanvasItemComposition()
        margins = Geometry.Margins(left=6, right=12, top=font_size + 4, bottom=6)
        line_graph_group_canvas_item.layout = CanvasItem.CanvasItemGridLayout(Geometry.IntSize(2, 2), margins=margins)
        line_graph_group_canvas_item.add_canvas_item(self.__line_graph_vertical_axis_group_canvas_item, Geometry.IntPoint(x=0, y=0))
        line_graph_group_canvas_item.add_canvas_item(line_graph_canvas_area_item, Geometry.IntPoint(x=1, y=0))
        line_graph_group_canvas_item.add_canvas_item(self.line_graph_horizontal_axis_group_canvas_item, Geometry.IntPoint(x=1, y=1))

        # draw the background
        line_graph_background_canvas_item = CanvasItem.CanvasItemComposition()
        #line_graph_background_canvas_item.sizing.minimum_aspect_ratio = 1.5  # note: no maximum aspect ratio; line plot looks nice wider.
        line_graph_background_canvas_item.add_canvas_item(CanvasItem.BackgroundCanvasItem("#FFF"))
        line_graph_background_canvas_item.add_canvas_item(line_graph_group_canvas_item)

        # canvas items get added back to front
        # create the child canvas items
        # the background
        self.add_canvas_item(CanvasItem.BackgroundCanvasItem())
        self.add_canvas_item(line_graph_background_canvas_item)

        # used for dragging graphic items
        self.__graphic_drag_items = []
        self.__graphic_drag_item = None
        self.__graphic_part_data = {}
        self.__graphic_drag_indexes = []
        self.__last_mouse = None
        self.__mouse_in = False
        self.__tracking_selections = False
        self.__tracking_horizontal = False
        self.__tracking_vertical = False

        self.__data_info = None

        self.__data_and_calibration = None
        self.__y_min = None
        self.__y_max = None
        self.__y_style = None
        self.__left_channel = None
        self.__right_channel = None
        self.__display_calibrated_values = False

        self.__graphics = list()
        self.__graphic_selection = set()

        # frame rate
        self.__display_frame_rate_id = None
        self.__display_frame_rate_last_index = 0

    def close(self):
        # call super
        super(LinePlotCanvasItem, self).close()

    def about_to_close(self):
        pass

    def update_display_state(self, data_and_calibration, display_properties, display_calibrated_values):
        """ Update the display state. """
        if data_and_calibration:
            self.__data_and_calibration = data_and_calibration
            self.__y_min = display_properties["y_min"]
            self.__y_max = display_properties["y_max"]
            self.__y_style = display_properties["y_style"]
            self.__left_channel = display_properties["left_channel"]
            self.__right_channel = display_properties["right_channel"]
            self.__display_calibrated_values = display_calibrated_values
            if self.__display_frame_rate_id:
                frame_index = data_and_calibration.metadata.get("hardware_source", dict()).get("frame_index", 0)
                if frame_index != self.__display_frame_rate_last_index:
                    Utility.fps_tick("frame_"+self.__display_frame_rate_id)
                    self.__display_frame_rate_last_index = frame_index
                Utility.fps_tick("update_"+self.__display_frame_rate_id)
        else:
            self.__data_and_calibration = None
            self.__y_min = None
            self.__y_max = None
            self.__y_style = None
            self.__left_channel = None
            self.__right_channel = None
            self.__display_calibrated_values = False
            self.__line_graph_regions_canvas_item.regions = list()
            self.__line_graph_regions_canvas_item.update()
            data_info = LineGraphCanvasItem.LineGraphDataInfo()
            self.__update_data_info(data_info)
        # update the cursor info
        self.__update_cursor_info()
        # finally, trigger the paint thread (if there still is one) to update
        self.update()

    def update_regions(self, data_and_calibration, graphic_selection, graphics, display_calibrated_values):
        self.__graphics = copy.copy(graphics)
        self.__graphic_selection = copy.copy(graphic_selection)

        data_length = data_and_calibration.dimensional_shape[0]
        dimensional_calibration = data_and_calibration.dimensional_calibrations[0] if display_calibrated_values else Calibration.Calibration()
        calibrated_data_left = dimensional_calibration.convert_to_calibrated_value(0)
        calibrated_data_right = dimensional_calibration.convert_to_calibrated_value(data_length)
        calibrated_data_left, calibrated_data_right = min(calibrated_data_left, calibrated_data_right), max(calibrated_data_left, calibrated_data_right)
        graph_left, graph_right, ticks, division, precision = Geometry.make_pretty_range(calibrated_data_left, calibrated_data_right)

        def convert_to_calibrated_value_str(f):
            return (u"{0:0." + u"{0:d}".format(precision + 2) + "f}").format(f)

        regions = list()
        for graphic_index, graphic in enumerate(graphics):
            if isinstance(graphic, Graphics.IntervalGraphic):
                graphic_start, graphic_end = graphic.start, graphic.end
                graphic_start, graphic_end = min(graphic_start, graphic_end), max(graphic_start, graphic_end)
                left_channel = graphic_start * data_length
                right_channel = graphic_end * data_length
                left_text = convert_to_calibrated_value_str(dimensional_calibration.convert_to_calibrated_value(left_channel))
                right_text = convert_to_calibrated_value_str(dimensional_calibration.convert_to_calibrated_value(right_channel))
                middle_text = convert_to_calibrated_value_str(dimensional_calibration.convert_to_calibrated_size(right_channel - left_channel))
                RegionInfo = collections.namedtuple("RegionInfo", ["channels", "selected", "index", "left_text", "right_text", "middle_text", "label"])
                region = RegionInfo((graphic_start, graphic_end), graphic_selection.contains(graphic_index), graphic_index, left_text, right_text, middle_text, graphic.label)
                regions.append(region)

        if self.__line_graph_regions_canvas_item.regions is None or self.__line_graph_regions_canvas_item.regions != regions:
            self.__line_graph_regions_canvas_item.regions = regions
            self.__line_graph_regions_canvas_item.update()

    def prepare_display(self):
        if self.__data_and_calibration:
            data_and_calibration = self.__data_and_calibration
            y_min = self.__y_min
            y_max = self.__y_max
            y_style = self.__y_style
            left_channel = self.__left_channel
            right_channel = self.__right_channel
            display_calibrated_values = self.__display_calibrated_values

            if data_and_calibration:
                # make sure we have the correct data
                assert data_and_calibration.is_data_1d

                # update the line graph data
                left_channel = left_channel if left_channel is not None else 0
                right_channel = right_channel if right_channel is not None else data_and_calibration.dimensional_shape[0]
                left_channel, right_channel = min(left_channel, right_channel), max(left_channel, right_channel)
                dimensional_calibration = data_and_calibration.dimensional_calibrations[0] if display_calibrated_values else None
                intensity_calibration = data_and_calibration.intensity_calibration if display_calibrated_values else None

                def get_data():
                    data = data_and_calibration.data
                    # make sure complex becomes scalar
                    data = Image.scalar_from_array(data)
                    assert data is not None
                    # make sure RGB becomes scalar
                    data = Image.convert_to_grayscale(data)
                    assert data is not None
                    return data

                data_info = LineGraphCanvasItem.LineGraphDataInfo(get_data, y_min, y_max, left_channel, right_channel,
                                                                  dimensional_calibration, intensity_calibration, y_style)
            else:
                data_info = LineGraphCanvasItem.LineGraphDataInfo()

            self.__update_data_info(data_info)
        else:
            self.__update_data_info(LineGraphCanvasItem.LineGraphDataInfo())

    def _repaint(self, drawing_context):
        super(LinePlotCanvasItem, self)._repaint(drawing_context)

        if self.__display_frame_rate_id:
            fps = Utility.fps_get("display_"+self.__display_frame_rate_id)
            fps2 = Utility.fps_get("frame_"+self.__display_frame_rate_id)
            fps3 = Utility.fps_get("update_"+self.__display_frame_rate_id)

            rect = self.canvas_bounds

            drawing_context.save()
            try:
                font = "normal 11px serif"
                text_pos = Geometry.IntPoint(y=rect[0][0], x=rect[0][1] + rect[1][1] - 100)
                drawing_context.begin_path()
                drawing_context.move_to(text_pos.x, text_pos.y)
                drawing_context.line_to(text_pos.x + 100, text_pos.y)
                drawing_context.line_to(text_pos.x + 100, text_pos.y + 60)
                drawing_context.line_to(text_pos.x, text_pos.y + 60)
                drawing_context.close_path()
                drawing_context.fill_style = "rgba(255, 255, 255, 0.6)"
                drawing_context.fill()
                drawing_context.font = font
                drawing_context.text_baseline = "middle"
                drawing_context.text_align = "left"
                drawing_context.fill_style = "#000"
                drawing_context.fill_text("display:" + str(int(fps*100)/100.0), text_pos.x + 8, text_pos.y + 10)
                drawing_context.fill_text("frame:" + str(int(fps2*100)/100.0), text_pos.x + 8, text_pos.y + 30)
                drawing_context.fill_text("update:" + str(int(fps3*100)/100.0), text_pos.x + 8, text_pos.y + 50)
            finally:
                drawing_context.restore()

    def _repaint_layer(self, drawing_context):
        self.prepare_display()
        if self.__display_frame_rate_id:
            Utility.fps_tick("display_"+self.__display_frame_rate_id)
        super(LinePlotCanvasItem, self)._repaint_layer(drawing_context)

    def __update_data_info(self, data_info):
        # the display has been changed, so this method has been called. it must be called on the ui thread.
        # data_info is a new copy of data info. it will be owned by this line plot after calling this method.
        # this method stores the data_info into each line plot canvas item and updates the canvas item.
        self.line_graph_canvas_item.data_info = data_info
        self.__line_graph_regions_canvas_item.data_info = data_info
        self.__line_graph_vertical_axis_label_canvas_item.data_info = data_info
        self.__line_graph_vertical_axis_label_canvas_item.size_to_content()
        self.__line_graph_vertical_axis_scale_canvas_item.data_info = data_info
        self.__line_graph_vertical_axis_scale_canvas_item.size_to_content(self.__get_font_metrics_fn)
        self.__line_graph_vertical_axis_ticks_canvas_item.data_info = data_info
        self.__line_graph_horizontal_axis_label_canvas_item.data_info = data_info
        self.__line_graph_horizontal_axis_label_canvas_item.size_to_content()
        self.__line_graph_horizontal_axis_scale_canvas_item.data_info = data_info
        self.__line_graph_horizontal_axis_ticks_canvas_item.data_info = data_info
        self.refresh_layout(trigger_update=False)
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
        if self.delegate.tool_mode == "pointer":
            pos = Geometry.IntPoint(x=x, y=y)
            if self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_horizontal_axis_group_canvas_item)):
                self.delegate.update_display_properties({"left_channel": None, "right_channel": None})
                return True
            elif self.__line_graph_vertical_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.__line_graph_vertical_axis_group_canvas_item)):
                self.delegate.update_display_properties({"y_min": None, "y_max": None})
                return True
        return False

    def mouse_position_changed(self, x, y, modifiers):
        if super(LinePlotCanvasItem, self).mouse_position_changed(x, y, modifiers):
            return True
        if self.delegate.tool_mode == "pointer":
            if self.__data_and_calibration:
                pos = Geometry.IntPoint(x=x, y=y)
                if self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_horizontal_axis_group_canvas_item)):
                    if modifiers.control:
                        self.cursor_shape = "split_horizontal"
                    else:
                        self.cursor_shape = "hand"
                elif self.__line_graph_vertical_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.__line_graph_vertical_axis_group_canvas_item)):
                    if modifiers.control:
                        self.cursor_shape = "split_vertical"
                    else:
                        self.cursor_shape = "hand"
                else:
                    self.cursor_shape = "arrow"
        elif self.delegate.tool_mode == "interval":
            self.cursor_shape = "cross"
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
        if not self.__data_and_calibration:
            return False
        pos = Geometry.IntPoint(x=x, y=y)
        self.delegate.begin_mouse_tracking()
        if self.delegate.tool_mode == "pointer":
            if self.__line_graph_regions_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.__line_graph_regions_canvas_item)):
                self.begin_tracking_regions(pos, modifiers)
                return True
            elif self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_horizontal_axis_group_canvas_item)):
                self.begin_tracking_horizontal(pos, rescale=modifiers.control)
                return True
            elif self.__line_graph_vertical_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.__line_graph_vertical_axis_group_canvas_item)):
                self.begin_tracking_vertical(pos, rescale=modifiers.control)
                return True
        elif self.delegate.tool_mode == "interval":
            if self.__line_graph_regions_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.__line_graph_regions_canvas_item)):
                data_size = self.__get_dimensional_shape()
                if data_size and len(data_size) == 1:
                    widget_mapping = self.__get_mouse_mapping()
                    x = widget_mapping.map_point_widget_to_channel_norm(pos)
                    region = Region.IntervalRegion()
                    region.start = x
                    region.end = x
                    self.delegate.add_and_select_region(region)
                    self.begin_tracking_regions(pos, Graphics.NullModifiers())
                return True
        return False

    def mouse_released(self, x, y, modifiers):
        if super(LinePlotCanvasItem, self).mouse_released(x, y, modifiers):
            return True
        self.end_tracking(modifiers)
        self.delegate.end_mouse_tracking()
        return False

    def context_menu_event(self, x, y, gx, gy):
        return self.delegate.show_context_menu(gx, gy)

    # ths message comes from the widget
    def key_pressed(self, key):
        if super(LinePlotCanvasItem, self).key_pressed(key):
            return True
        # only handle keys if we're directly embedded in an image panel
        if key.is_delete:
            self.delegate.delete_key_pressed()
            return True
        if key.is_arrow:
            mapping = self.__get_mouse_mapping()
            amount = 10.0 if key.modifiers.shift else 1.0
            if key.is_left_arrow:
                self.delegate.nudge_selected_graphics(mapping, Geometry.FloatPoint(y=0, x=-amount))
            elif key.is_right_arrow:
                self.delegate.nudge_selected_graphics(mapping, Geometry.FloatPoint(y=0, x=amount))
            return True
        if key.key == 70 and key.modifiers.control and key.modifiers.alt:
            if self.__display_frame_rate_id is None:
                self.__display_frame_rate_id = str(id(self))
            else:
                self.__display_frame_rate_id = None
            return True
        return False

    def __get_mouse_mapping(self):
        data_size = self.__get_dimensional_shape()
        plot_origin = self.__line_graph_regions_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
        plot_rect = self.__line_graph_regions_canvas_item.canvas_bounds.translated(plot_origin)
        x_properties = self.__data_info.x_properties
        left_channel = x_properties.drawn_left_channel
        right_channel = x_properties.drawn_right_channel
        return LinePlotCanvasItemMapping(data_size, plot_rect, left_channel, right_channel)

    def begin_tracking_regions(self, pos, modifiers):
        data_size = self.__get_dimensional_shape()
        if self.__data_and_calibration and data_size and len(data_size) == 1:
            self.__tracking_selections = True
            graphics = self.__graphics
            selection_indexes = self.__graphic_selection.indexes
            for graphic_index, graphic in enumerate(graphics):
                start_drag_pos = Geometry.IntPoint.make(pos)
                already_selected = graphic_index in selection_indexes
                multiple_items_selected = len(selection_indexes) > 1
                move_only = not already_selected or multiple_items_selected
                widget_mapping = self.__get_mouse_mapping()
                part = graphic.test(widget_mapping, self.__get_font_metrics_fn, start_drag_pos, move_only)
                if part:
                    # select item and prepare for drag
                    self.graphic_drag_item_was_selected = already_selected
                    if not self.graphic_drag_item_was_selected:
                        if modifiers.shift:
                            self.delegate.add_index_to_selection(graphic_index)
                            selection_indexes.add(graphic_index)
                        else:
                            self.delegate.set_selection(graphic_index)
                            selection_indexes.clear()
                            selection_indexes.add(graphic_index)
                    # keep track of general drag information
                    self.__graphic_drag_start_pos = start_drag_pos
                    self.__graphic_drag_changed = False
                    # keep track of info for the specific item that was clicked
                    self.__graphic_drag_item = graphics[graphic_index]
                    self.__graphic_drag_part = part
                    # keep track of drag information for each item in the set
                    self.__graphic_drag_indexes = selection_indexes
                    for index in self.__graphic_drag_indexes:
                        graphic = graphics[index]
                        self.__graphic_drag_items.append(graphic)
                        self.__graphic_part_data[index] = graphic.begin_drag()
                    break
            if not self.__graphic_drag_items and not modifiers.shift:
                self.delegate.clear_selection()

    def begin_tracking_horizontal(self, pos, rescale):
        plot_origin = self.line_graph_horizontal_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
        plot_rect = self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds.translated(plot_origin)
        x_properties = self.__data_info.x_properties
        self.__tracking_horizontal = True
        self.__tracking_rescale = rescale
        self.__tracking_start_pos = pos
        self.__tracking_start_left_channel = x_properties.drawn_left_channel
        self.__tracking_start_right_channel = x_properties.drawn_right_channel
        self.__tracking_start_drawn_channel_per_pixel = float(self.__tracking_start_right_channel - self.__tracking_start_left_channel) / plot_rect.width
        self.__tracking_start_origin_pixel = self.__tracking_start_pos.x - plot_rect.left
        self.__tracking_start_channel = self.__tracking_start_left_channel + self.__tracking_start_origin_pixel * self.__tracking_start_drawn_channel_per_pixel

    def begin_tracking_vertical(self, pos, rescale):
        plot_height = self.line_graph_canvas_item.canvas_bounds.height - 1
        y_properties = self.__data_info.y_properties
        self.__tracking_vertical = True
        self.__tracking_rescale = rescale
        self.__tracking_start_pos = pos
        self.__tracking_start_calibrated_data_min = y_properties.calibrated_data_min
        self.__tracking_start_calibrated_data_max = y_properties.calibrated_data_max
        self.__tracking_start_calibrated_data_per_pixel = (self.__tracking_start_calibrated_data_max - self.__tracking_start_calibrated_data_min) / plot_height
        plot_origin = self.__line_graph_vertical_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
        plot_rect = self.__line_graph_vertical_axis_group_canvas_item.canvas_bounds.translated(plot_origin)
        if 0.0 >= self.__tracking_start_calibrated_data_min and 0.0 <= self.__tracking_start_calibrated_data_max:
            calibrated_unit_per_pixel = (self.__tracking_start_calibrated_data_max - self.__tracking_start_calibrated_data_min) / (plot_rect.height - 1)
            origin_offset_pixels = (0.0 - self.__tracking_start_calibrated_data_min) / calibrated_unit_per_pixel
            calibrated_origin = self.__tracking_start_calibrated_data_min + origin_offset_pixels * self.__tracking_start_calibrated_data_per_pixel
            self.__tracking_start_origin_y = origin_offset_pixels
            self.__tracking_start_calibrated_origin = calibrated_origin
        else:
            self.__tracking_start_origin_y = 0  # the distance the origin is up from the bottom
            self.__tracking_start_calibrated_origin = self.__tracking_start_calibrated_data_min

    def continue_tracking(self, pos, modifiers):
        if self.__tracking_selections:
            # x,y already have transform applied
            self.__last_mouse = copy.copy(pos)
            self.__update_cursor_info()
            if self.__graphic_drag_items:
                widget_mapping = self.__get_mouse_mapping()
                self.delegate.update_graphics(widget_mapping, self.__graphic_drag_items, self.__graphic_drag_part,
                                              self.__graphic_part_data, self.__graphic_drag_start_pos, pos, modifiers)
                self.__graphic_drag_changed = True
                self.__line_graph_regions_canvas_item.update()
        elif self.__tracking_horizontal:
            if self.__tracking_rescale:
                plot_origin = self.line_graph_horizontal_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
                plot_rect = self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds.translated(plot_origin)
                pixel_offset_x = pos.x - self.__tracking_start_pos.x
                scaling = math.pow(10, pixel_offset_x/96.0)  # 10x per inch of travel, assume 96dpi
                new_drawn_channel_per_pixel = self.__tracking_start_drawn_channel_per_pixel / scaling
                left_channel = int(round(self.__tracking_start_channel - new_drawn_channel_per_pixel * self.__tracking_start_origin_pixel))
                right_channel = int(round(self.__tracking_start_channel + new_drawn_channel_per_pixel * (plot_rect.width - self.__tracking_start_origin_pixel)))
                self.delegate.update_display_properties({"left_channel": left_channel, "right_channel": right_channel})
                return True
            else:
                delta = pos - self.__tracking_start_pos
                left_channel = int(self.__tracking_start_left_channel - self.__tracking_start_drawn_channel_per_pixel * delta.x)
                right_channel = int(self.__tracking_start_right_channel - self.__tracking_start_drawn_channel_per_pixel * delta.x)
                self.delegate.update_display_properties({"left_channel": left_channel, "right_channel": right_channel})
                return True
        elif self.__tracking_vertical:
            if self.__tracking_rescale:
                plot_origin = self.__line_graph_vertical_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
                plot_rect = self.__line_graph_vertical_axis_group_canvas_item.canvas_bounds.translated(plot_origin)
                origin_y = plot_rect.bottom - 1 - self.__tracking_start_origin_y  # pixel position of y-origin
                calibrated_offset = self.__tracking_start_calibrated_data_per_pixel * (origin_y - self.__tracking_start_pos.y)
                pixel_offset = origin_y - pos.y
                pixel_offset = max(pixel_offset, 1) if origin_y > self.__tracking_start_pos.y else min(pixel_offset, -1)
                new_calibrated_data_per_pixel = calibrated_offset / pixel_offset
                calibrated_data_min = self.__tracking_start_calibrated_origin - new_calibrated_data_per_pixel * self.__tracking_start_origin_y
                calibrated_data_max = self.__tracking_start_calibrated_origin + new_calibrated_data_per_pixel * (plot_rect.height - 1 - self.__tracking_start_origin_y)
                uncalibrated_data_min = self.__data_info.uncalibrate_y(calibrated_data_min)
                uncalibrated_data_max = self.__data_info.uncalibrate_y(calibrated_data_max)
                self.delegate.update_display_properties({"y_min": uncalibrated_data_min, "y_max": uncalibrated_data_max})
                return True
            else:
                delta = pos - self.__tracking_start_pos
                calibrated_data_min = self.__tracking_start_calibrated_data_min + self.__tracking_start_calibrated_data_per_pixel * delta.y
                calibrated_data_max = self.__tracking_start_calibrated_data_max + self.__tracking_start_calibrated_data_per_pixel * delta.y
                uncalibrated_data_min = self.__data_info.uncalibrate_y(calibrated_data_min)
                uncalibrated_data_max = self.__data_info.uncalibrate_y(calibrated_data_max)
                self.delegate.update_display_properties({"y_min": uncalibrated_data_min, "y_max": uncalibrated_data_max})
                return True
        return False

    def end_tracking(self, modifiers):
        if self.__tracking_selections:
            if self.__data_and_calibration:
                graphics = self.__graphics
                for index in self.__graphic_drag_indexes:
                    graphic = graphics[index]
                    graphic.end_drag(self.__graphic_part_data[index])
                if self.__graphic_drag_items and not self.__graphic_drag_changed:
                    graphic_index = graphics.index(self.__graphic_drag_item)
                    # user didn't move graphic
                    if not modifiers.shift:
                        # user clicked on a single graphic
                        self.delegate.set_selection(graphic_index)
                    else:
                        # user shift clicked. toggle selection
                        # if shift is down and item is already selected, toggle selection of item
                        if self.graphic_drag_item_was_selected:
                            self.delegate.remove_index_from_selection(graphic_index)
                        else:
                            self.delegate.add_index_to_selection(graphic_index)
            self.__graphic_drag_items = []
            self.__graphic_drag_item = None
            self.__graphic_part_data = {}
            self.__graphic_drag_indexes = []
            self.delegate.tool_mode = "pointer"
        self.__tracking_horizontal = False
        self.__tracking_vertical = False
        self.__tracking_selections = False
        self.prepare_display()

    def __get_dimensional_shape(self):
        data_and_calibration = self.__data_and_calibration
        dimensional_shape = data_and_calibration.dimensional_shape if data_and_calibration else None
        if not dimensional_shape:
            return None
        return dimensional_shape

    def __update_cursor_info(self):
        if not self.delegate:  # allow display to work without delegate
            return
        if self.__mouse_in and self.__last_mouse:
            data_size = self.__get_dimensional_shape()
            pos_1d = None
            if data_size and len(data_size) == 1:
                last_mouse = self.map_to_canvas_item(self.__last_mouse, self.line_graph_canvas_item)
                pos_1d = self.line_graph_canvas_item.map_mouse_to_position(last_mouse, data_size)
            self.delegate.cursor_changed(self, pos_1d)
        else:
            self.delegate.cursor_changed(self, None)
