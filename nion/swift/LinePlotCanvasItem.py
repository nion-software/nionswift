# standard libraries
import collections
import copy
import math
import threading

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import Image
from nion.swift import LineGraphCanvasItem
from nion.swift.model import Graphics
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.utils import Geometry


class LinePlotCanvasItemMapping(object):

    def __init__(self, data_size, plot_rect, left_channel, right_channel):
        self.__data_size = data_size
        self.__plot_rect = plot_rect
        self.__left_channel = left_channel
        self.__right_channel = right_channel
        self.__drawn_channel_per_pixel = float(right_channel - left_channel) / plot_rect.width

    def map_point_widget_to_channel_norm(self, pos):
        return (self.__left_channel + (pos.x - self.__plot_rect.left) * self.__drawn_channel_per_pixel) / self.__data_size[-1]

    def map_point_channel_norm_to_widget(self, x):
        return (x * self.__data_size[-1] - self.__left_channel) / self.__drawn_channel_per_pixel + self.__plot_rect.left

    def map_point_channel_norm_to_channel(self, x):
        return x * self.__data_size[-1]


class LinePlotCanvasItem(CanvasItem.LayerCanvasItem):
    """Display a line plot.

    Callers are expected to pass in a font metrics function and a delegate.

    They are expected to call the following functions to update the display:
        update_line_plot_display_state
        update_regions

    The delegate is expected to handle the following events:
        add_index_to_selection(index)
        remove_index_from_selection(index)
        set_selection(index)
        clear_selection()
        add_and_select_region(region)
        nudge_selected_graphics(mapping, delta)
        update_graphics(widget_mapping, graphic_drag_items, graphic_drag_part, graphic_part_data, graphic_drag_start_pos, pos, modifiers)
        tool_mode (property)
        show_display_context_menu(gx, gy)
        begin_mouse_tracking(self)
        end_mouse_tracking()
        mouse_clicked(image_position, modifiers)
        delete_key_pressed()
        cursor_changed(pos)
        update_display_properties(display_properties)

    The line plot display layout is dependent on the data of the line plot since the width of the vertical axis is
    dependent on the data. This display currently handles that within the _repaint method, but care must be taken to
    not trigger another repaint from within the existing repaint.
    """

    def __init__(self, get_font_metrics_fn, delegate, event_loop, draw_background: bool=True):
        super(LinePlotCanvasItem, self).__init__()

        self.__get_font_metrics_fn = get_font_metrics_fn
        self.delegate = delegate

        self.wants_mouse_events = True

        font_size = 12

        self.__closing_lock = threading.RLock()
        self.__closed = False

        self.__data = None
        self.__last_data = None

        self.line_graph_canvas_item = None

        self.__line_graph_area_stack = CanvasItem.CanvasItemComposition()
        self.__line_graph_background_canvas_item = LineGraphCanvasItem.LineGraphBackgroundCanvasItem()
        self.__line_graph_stack = CanvasItem.CanvasItemComposition()
        self.__line_graph_regions_canvas_item = LineGraphCanvasItem.LineGraphRegionsCanvasItem()
        self.__line_graph_legend_canvas_item = LineGraphCanvasItem.LineGraphLegendCanvasItem(get_font_metrics_fn)
        self.__line_graph_frame_canvas_item = LineGraphCanvasItem.LineGraphFrameCanvasItem()
        self.__line_graph_area_stack.add_canvas_item(self.__line_graph_background_canvas_item)
        self.__line_graph_area_stack.add_canvas_item(self.__line_graph_stack)
        self.__line_graph_area_stack.add_canvas_item(self.__line_graph_regions_canvas_item)
        self.__line_graph_area_stack.add_canvas_item(self.__line_graph_legend_canvas_item)
        self.__line_graph_area_stack.add_canvas_item(self.__line_graph_frame_canvas_item)

        self.line_graph_canvas_item = LineGraphCanvasItem.LineGraphCanvasItem()
        self.__line_graph_stack.add_canvas_item(self.line_graph_canvas_item)

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
        line_graph_group_canvas_item.add_canvas_item(self.__line_graph_area_stack, Geometry.IntPoint(x=1, y=0))
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

        self.__last_data_info = None
        self.__last_data_info_data = None
        self.__data_fn = None
        self.__data_shape = None
        self.__dimensional_calibration = None
        self.__intensity_calibration = None
        self.__y_min = None
        self.__y_max = None
        self.__y_style = None
        self.__left_channel = None
        self.__right_channel = None
        self.__legend_labels = None

        self.__graphics = list()
        self.__graphic_selection = set()

        # frame rate
        self.__display_frame_rate_id = None
        self.__display_frame_rate_last_index = 0

    def close(self):
        # call super
        with self.__closing_lock:
            self.__closed = True
        super().close()

    @property
    def default_aspect_ratio(self):
        return (1 + 5 ** 0.5) / 2  # golden ratio

    def display_rgba_changed(self, display, display_values):
        # when the display rgba data changes, no need to do anything
        pass

    def display_data_and_metadata_changed(self, display, display_values):
        # when the data changes, update the display.
        self.update_display_values(display, display_values)

    def update_display_values(self, display, display_values):
        data_and_metadata = display.data_and_metadata_for_display_panel
        if data_and_metadata:
            display_properties = {
                "y_min": display.y_min,
                "y_max": display.y_max,
                "y_style": display.y_style,
                "left_channel": display.left_channel,
                "right_channel": display.right_channel,
                "legend_labels": display.legend_labels
            }
            display_data_and_metadata = display_values.display_data_and_metadata
            display_data = display_data_and_metadata.data if display_data_and_metadata else None
            dimensional_shape = data_and_metadata.dimensional_shape
            displayed_intensity_calibration = copy.deepcopy(data_and_metadata.intensity_calibration)
            displayed_dimensional_calibrations = display.displayed_dimensional_calibrations
            displayed_dimensional_calibration = displayed_dimensional_calibrations[-1] if len(displayed_dimensional_calibrations) > 0 else Calibration.Calibration()

            data = display_data
            data_shape = dimensional_shape
            metadata = data_and_metadata.metadata

            # this method may trigger a layout of its parent scroll area. however, the parent scroll
            # area may already be closed. this is a stop-gap guess at a solution - the basic idea being
            # that this object is not closeable while this method is running; and this method should not
            # run if the object is already closed.
            with self.__closing_lock:
                if self.__closed:
                    return
                assert not self.__closed
                # Update the display state.
                changed = False
                changed = changed or data is not self.__data
                changed = changed or displayed_intensity_calibration != self.__intensity_calibration
                changed = changed or displayed_dimensional_calibration != self.__dimensional_calibration
                changed = changed or self.__y_min != display_properties["y_min"]
                changed = changed or self.__y_max != display_properties["y_max"]
                changed = changed or self.__y_style != display_properties["y_style"]
                changed = changed or self.__left_channel != display_properties["left_channel"]
                changed = changed or self.__right_channel != display_properties["right_channel"]
                changed = changed or self.__legend_labels != display_properties["legend_labels"]
                if changed:
                    self.__data = data
                    self.__data_shape = data_shape
                    self.__dimensional_calibration = displayed_dimensional_calibration
                    self.__intensity_calibration = displayed_intensity_calibration
                    self.__y_min = display_properties["y_min"]
                    self.__y_max = display_properties["y_max"]
                    self.__y_style = display_properties["y_style"]
                    self.__left_channel = display_properties["left_channel"]
                    self.__right_channel = display_properties["right_channel"]
                    self.__legend_labels = display_properties["legend_labels"]
                    if self.__display_frame_rate_id:
                        frame_index = metadata.get("hardware_source", dict()).get("frame_index", 0)
                        if frame_index != self.__display_frame_rate_last_index:
                            Utility.fps_tick("frame_"+self.__display_frame_rate_id)
                            self.__display_frame_rate_last_index = frame_index
                        if id(self.__data) != id(self.__last_data):
                            Utility.fps_tick("update_"+self.__display_frame_rate_id)
                            self.__last_data = self.__data
                    # update the cursor info
                    self.__update_cursor_info()
                    # mark all items as needing updates; the actual data updates will be done on the
                    # render thread during prepare_render.
                    self.update()
                    self.line_graph_canvas_item.update()
                    self.__line_graph_background_canvas_item.update()
                    self.__line_graph_regions_canvas_item.update()
                    self.__line_graph_frame_canvas_item.update()
                    self.__line_graph_legend_canvas_item.update()
                    self.__line_graph_vertical_axis_label_canvas_item.update()
                    self.__line_graph_vertical_axis_scale_canvas_item.update()
                    self.__line_graph_vertical_axis_ticks_canvas_item.update()
                    self.__line_graph_horizontal_axis_label_canvas_item.update()
                    self.__line_graph_horizontal_axis_scale_canvas_item.update()
                    self.__line_graph_horizontal_axis_ticks_canvas_item.update()

    def update_regions(self, display, graphic_selection):
        displayed_shape = display.preview_2d_shape
        graphics = display.graphics

        self.__graphics = copy.copy(graphics)
        self.__graphic_selection = copy.copy(graphic_selection)

        if displayed_shape is None or len(displayed_shape) == 0:
            return

        data_length = displayed_shape[-1]
        dimensional_calibration = display.displayed_dimensional_calibrations[-1]

        def convert_to_calibrated_value_str(f):
            return u"{0}".format(dimensional_calibration.convert_to_calibrated_value_str(f, value_range=(0, data_length), samples=data_length, include_units=False))

        def convert_to_calibrated_size_str(f):
            return u"{0}".format(dimensional_calibration.convert_to_calibrated_size_str(f, value_range=(0, data_length), samples=data_length, include_units=False))

        regions = list()
        for graphic_index, graphic in enumerate(graphics):
            if isinstance(graphic, Graphics.IntervalGraphic):
                graphic_start, graphic_end = graphic.start, graphic.end
                graphic_start, graphic_end = min(graphic_start, graphic_end), max(graphic_start, graphic_end)
                left_channel = graphic_start * data_length
                right_channel = graphic_end * data_length
                left_text = convert_to_calibrated_value_str(left_channel)
                right_text = convert_to_calibrated_value_str(right_channel)
                middle_text = convert_to_calibrated_size_str(right_channel - left_channel)
                RegionInfo = collections.namedtuple("RegionInfo", ["channels", "selected", "index", "left_text", "right_text", "middle_text", "label", "style"])
                region = RegionInfo((graphic_start, graphic_end), graphic_selection.contains(graphic_index), graphic_index, left_text, right_text, middle_text, graphic.label, None)
                regions.append(region)
            elif isinstance(graphic, Graphics.ChannelGraphic):
                graphic_start, graphic_end = graphic.position, graphic.position
                graphic_start, graphic_end = min(graphic_start, graphic_end), max(graphic_start, graphic_end)
                left_channel = graphic_start * data_length
                right_channel = graphic_end * data_length
                left_text = convert_to_calibrated_value_str(left_channel)
                right_text = convert_to_calibrated_value_str(right_channel)
                middle_text = convert_to_calibrated_size_str(right_channel - left_channel)
                RegionInfo = collections.namedtuple("RegionInfo", ["channels", "selected", "index", "left_text", "right_text", "middle_text", "label", "style"])
                region = RegionInfo((graphic_start, graphic_end), graphic_selection.contains(graphic_index), graphic_index, left_text, right_text, middle_text, graphic.label, "tag")
                regions.append(region)

        if self.__line_graph_regions_canvas_item.regions is None or self.__line_graph_regions_canvas_item.regions != regions:
            self.__line_graph_regions_canvas_item.regions = regions
            self.__line_graph_regions_canvas_item.update()

    def handle_auto_display(self, display) -> bool:
        # enter key has been pressed
        data_and_metadata = display.data_and_metadata_for_display_panel
        display.view_to_selected_graphics(data_and_metadata)
        return True

    def prepare_display(self):
        # thread safe. no UI.
        if self.__data_shape:
            data_shape = self.__data_shape
            dimensional_calibration = self.__dimensional_calibration
            intensity_calibration = self.__intensity_calibration
            y_min = self.__y_min
            y_max = self.__y_max
            y_style = self.__y_style
            left_channel = self.__left_channel
            right_channel = self.__right_channel
            legend_labels = self.__legend_labels

            # this can be done here -- it is always in a thread (paint)
            scalar_data = self.__data

            if scalar_data is not None and data_shape is not None and len(data_shape) > 0:

                # update the line graph data
                left_channel = left_channel if left_channel is not None else 0
                right_channel = right_channel if right_channel is not None else data_shape[-1]
                left_channel, right_channel = min(left_channel, right_channel), max(left_channel, right_channel)

                # make sure complex becomes scalar
                scalar_data = Image.scalar_from_array(scalar_data)
                assert scalar_data is not None
                # make sure RGB becomes scalar
                scalar_data = Image.convert_to_grayscale(scalar_data)
                assert scalar_data is not None

                if not numpy.array_equal(self.__last_data_info_data, scalar_data) or self.__last_data_info != (y_min, y_max, left_channel, right_channel, dimensional_calibration, intensity_calibration, y_style):
                    data_info = LineGraphCanvasItem.LineGraphDataInfo(scalar_data, y_min, y_max, left_channel, right_channel,
                                                                      dimensional_calibration, intensity_calibration, y_style, legend_labels)
                    self.__update_data_info(data_info)
                    self.__last_data_info = (y_min, y_max, left_channel, right_channel, dimensional_calibration, intensity_calibration, y_style)
                    self.__last_data_info_data = numpy.copy(scalar_data)
            else:
                self.__update_data_info(LineGraphCanvasItem.LineGraphDataInfo())
                self.__last_data_info = None
                self.__last_data_info_data = None
        else:
            self.__update_data_info(LineGraphCanvasItem.LineGraphDataInfo())
            self.__last_data_info = None
            self.__last_data_info_data = None

    def _inserted(self, container):
        # make sure we get 'prepare_render' calls
        self.register_prepare_canvas_item(self)

    def _removed(self, container):
        # turn off 'prepare_render' calls
        self.unregister_prepare_canvas_item(self)

    def prepare_render(self):
        self.prepare_display()

    def _repaint(self, drawing_context):
        super(LinePlotCanvasItem, self)._repaint(drawing_context)

        if self.__display_frame_rate_id:
            Utility.fps_tick("display_"+self.__display_frame_rate_id)

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
                drawing_context.line_to(text_pos.x + 120, text_pos.y)
                drawing_context.line_to(text_pos.x + 120, text_pos.y + 60)
                drawing_context.line_to(text_pos.x, text_pos.y + 60)
                drawing_context.close_path()
                drawing_context.fill_style = "rgba(255, 255, 255, 0.6)"
                drawing_context.fill()
                drawing_context.font = font
                drawing_context.text_baseline = "middle"
                drawing_context.text_align = "left"
                drawing_context.fill_style = "#000"
                drawing_context.fill_text("display:" + fps, text_pos.x + 8, text_pos.y + 10)
                drawing_context.fill_text("frame:" + fps2, text_pos.x + 8, text_pos.y + 30)
                drawing_context.fill_text("update:" + fps3, text_pos.x + 8, text_pos.y + 50)
            finally:
                drawing_context.restore()

    def __update_data_info(self, data_info):
        # the display has been changed, so this method has been called. it must be called on the ui thread.
        # data_info is a new copy of data info. it will be owned by this line plot after calling this method.
        # this method stores the data_info into each line plot canvas item and updates the canvas item.
        # thread safe. no UI.
        data = data_info.data
        if Image.is_data_1d(data):
            if len(self.line_graph_canvas_item.line_graph_data_list) != 1:
                self.line_graph_canvas_item.line_graph_data_list = [LineGraphCanvasItem.LineGraphData(data_info)]
        elif Image.is_data_2d(data):
            rows = min(16, data.shape[0])
            if len(self.line_graph_canvas_item.line_graph_data_list) != rows:
                colors = ('#1E90FF', "#F00", "#0F0", "#00F", "#FF0", "#0FF", "#F0F", "#888", "#800", "#080", "#008", "#CCC", "#880", "#088", "#808", "#964B00")
                filled = True
                line_graph_data_list = list()
                for row in range(rows):
                    line_graph_data_list.append(LineGraphCanvasItem.LineGraphData(data_info, slice(row, row + 1), filled, colors[row]))
                    filled = False
                self.line_graph_canvas_item.line_graph_data_list = line_graph_data_list

        # update the data info for each item; also call update so that they're forced to be drawn.

        for line_graph_data in self.line_graph_canvas_item.line_graph_data_list:
            line_graph_data.data_info = data_info
        self.line_graph_canvas_item.update()

        self.__line_graph_background_canvas_item.data_info = data_info
        self.__line_graph_background_canvas_item.update()
        self.__line_graph_regions_canvas_item.data_info = data_info
        self.__line_graph_regions_canvas_item.update()
        self.__line_graph_frame_canvas_item.data_info = data_info
        self.__line_graph_frame_canvas_item.update()
        self.__line_graph_legend_canvas_item.data_info = data_info
        self.__line_graph_legend_canvas_item.update()
        self.__line_graph_vertical_axis_label_canvas_item.data_info = data_info
        self.__line_graph_vertical_axis_label_canvas_item.size_to_content()
        self.__line_graph_vertical_axis_label_canvas_item.update()
        self.__line_graph_vertical_axis_scale_canvas_item.data_info = data_info
        self.__line_graph_vertical_axis_scale_canvas_item.size_to_content(self.__get_font_metrics_fn)
        self.__line_graph_vertical_axis_scale_canvas_item.update()
        self.__line_graph_vertical_axis_ticks_canvas_item.data_info = data_info
        self.__line_graph_vertical_axis_ticks_canvas_item.update()
        self.__line_graph_horizontal_axis_label_canvas_item.data_info = data_info
        self.__line_graph_horizontal_axis_label_canvas_item.size_to_content()
        self.__line_graph_horizontal_axis_label_canvas_item.update()
        self.__line_graph_horizontal_axis_scale_canvas_item.data_info = data_info
        self.__line_graph_horizontal_axis_scale_canvas_item.update()
        self.__line_graph_horizontal_axis_ticks_canvas_item.data_info = data_info
        self.__line_graph_horizontal_axis_ticks_canvas_item.update()

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
        if self.delegate:  # allow display to work without delegate
            # whenever the cursor exits, clear the cursor display
            self.delegate.cursor_changed(None)
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
            if self.__data_shape is not None:
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
        if self.__data_shape is None:
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
        if self.delegate.tool_mode == "interval":
            if self.__line_graph_regions_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.__line_graph_regions_canvas_item)):
                data_shape = self.__data_shape
                if data_shape and len(data_shape) > 0:
                    widget_mapping = self.__get_mouse_mapping()
                    x = widget_mapping.map_point_widget_to_channel_norm(pos)
                    region = Graphics.IntervalGraphic()
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
        return self.delegate.show_display_context_menu(gx, gy)

    # ths message comes from the widget
    def key_pressed(self, key):
        if super(LinePlotCanvasItem, self).key_pressed(key):
            return True
        # only handle keys if we're directly embedded in an image panel
        if key.is_delete:
            self.delegate.delete_key_pressed()
            return True
        if key.is_enter_or_return:
            self.delegate.enter_key_pressed()
            return True
        if key.is_arrow:
            mapping = self.__get_mouse_mapping()
            amount = 10.0 if key.modifiers.shift else 1.0
            if key.is_left_arrow:
                self.delegate.nudge_selected_graphics(mapping, Geometry.FloatPoint(y=0, x=-amount))
            elif key.is_right_arrow:
                self.delegate.nudge_selected_graphics(mapping, Geometry.FloatPoint(y=0, x=amount))
            return True
        if key.key == 70 and key.modifiers.shift and key.modifiers.alt:
            if self.__display_frame_rate_id is None:
                self.__display_frame_rate_id = str(id(self))
            else:
                self.__display_frame_rate_id = None
            return True
        return False

    def __get_mouse_mapping(self):
        plot_origin = self.__line_graph_regions_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
        plot_rect = self.__line_graph_regions_canvas_item.canvas_bounds.translated(plot_origin)
        x_properties = self.__data_info.x_properties
        left_channel = x_properties.drawn_left_channel
        right_channel = x_properties.drawn_right_channel
        return LinePlotCanvasItemMapping(self.__data_shape, plot_rect, left_channel, right_channel)

    def begin_tracking_regions(self, pos, modifiers):
        # keep track of general drag information
        self.__graphic_drag_start_pos = Geometry.IntPoint.make(pos)
        self.__graphic_drag_changed = False
        data_shape = self.__data_shape
        if data_shape is not None and len(data_shape) > 0:
            self.__tracking_selections = True
            graphics = self.__graphics
            selection_indexes = self.__graphic_selection.indexes
            for graphic_index, graphic in enumerate(graphics):
                if isinstance(graphic, (Graphics.IntervalGraphic, Graphics.ChannelGraphic)):
                    already_selected = graphic_index in selection_indexes
                    multiple_items_selected = len(selection_indexes) > 1
                    move_only = not already_selected or multiple_items_selected
                    widget_mapping = self.__get_mouse_mapping()
                    part, specific = graphic.test(widget_mapping, self.__get_font_metrics_fn, self.__graphic_drag_start_pos, move_only)
                    if part:
                        # select item and prepare for drag
                        self.graphic_drag_item_was_selected = already_selected
                        if not self.graphic_drag_item_was_selected:
                            if modifiers.control:
                                self.delegate.add_index_to_selection(graphic_index)
                                selection_indexes.add(graphic_index)
                            else:
                                self.delegate.set_selection(graphic_index)
                                selection_indexes.clear()
                                selection_indexes.add(graphic_index)
                        # keep track of info for the specific item that was clicked
                        self.__graphic_drag_item = graphic
                        self.__graphic_drag_part = part
                        # keep track of drag information for each item in the set
                        self.__graphic_drag_indexes = selection_indexes
                        for index in self.__graphic_drag_indexes:
                            graphic = graphics[index]
                            self.__graphic_drag_items.append(graphic)
                            self.__graphic_part_data[index] = graphic.begin_drag()
                        break

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
        plot_height = self.__line_graph_area_stack.canvas_bounds.height - 1
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
            if self.__graphic_drag_item is None and not self.__graphic_drag_changed:
                pos = self.__graphic_drag_start_pos
                widget_mapping = self.__get_mouse_mapping()
                x = widget_mapping.map_point_widget_to_channel_norm(pos)
                region = Graphics.IntervalGraphic()
                region.start = x
                region.end = x
                self.delegate.add_and_select_region(region)
                selection_indexes = self.__graphic_selection.indexes
                for graphic_index, graphic in enumerate(self.__graphics):
                    if graphic == region:
                        part, specific = graphic.test(widget_mapping, self.__get_font_metrics_fn, self.__graphic_drag_start_pos, False)
                        if part:
                            self.graphic_drag_item_was_selected = False
                            self.delegate.set_selection(graphic_index)
                            selection_indexes.clear()
                            selection_indexes.add(graphic_index)
                            self.__graphic_drag_item = graphic
                            self.__graphic_drag_part = part
                            self.__graphic_drag_indexes = selection_indexes
                            self.__graphic_drag_items.append(graphic)
                            self.__graphic_part_data[graphic_index] = graphic.begin_drag()
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
        if not self.__graphic_drag_items and not modifiers.control:
            self.delegate.clear_selection()
        if self.__tracking_selections:
            if self.__data_shape is not None:
                graphics = self.__graphics
                for index in self.__graphic_drag_indexes:
                    graphic = graphics[index]
                    graphic.end_drag(self.__graphic_part_data[index])
                if self.__graphic_drag_items and not self.__graphic_drag_changed:
                    graphic_index = graphics.index(self.__graphic_drag_item)
                    # user didn't move graphic
                    if not modifiers.control:
                        # user clicked on a single graphic
                        self.delegate.set_selection(graphic_index)
                    else:
                        # user control clicked. toggle selection
                        # if control is down and item is already selected, toggle selection of item
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

    def __update_cursor_info(self):
        if not self.delegate:  # allow display to work without delegate
            return
        if self.__mouse_in and self.__last_mouse:
            data_shape = self.__data_shape
            pos_1d = None
            if data_shape and self.line_graph_canvas_item:
                last_mouse = self.map_to_canvas_item(self.__last_mouse, self.line_graph_canvas_item)
                pos_1d = self.line_graph_canvas_item.map_mouse_to_position(last_mouse, data_shape)
            self.delegate.cursor_changed(pos_1d)
