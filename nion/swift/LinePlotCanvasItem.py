# standard libraries
import collections
import copy
import math
import threading

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift import LineGraphCanvasItem
from nion.swift import Undo
from nion.swift.model import Graphics
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.utils import Geometry


class LinePlotCanvasItemMapping:

    def __init__(self, scale, plot_rect, left_channel, right_channel):
        self.__scale = scale
        self.__plot_rect = plot_rect
        self.__left_channel = left_channel
        self.__right_channel = right_channel
        self.__drawn_channel_per_pixel = float(right_channel - left_channel) / plot_rect.width

    def map_point_widget_to_channel_norm(self, pos):
        return (self.__left_channel + (pos.x - self.__plot_rect.left) * self.__drawn_channel_per_pixel) / self.__scale

    def map_point_channel_norm_to_widget(self, x):
        return (x * self.__scale - self.__left_channel) / self.__drawn_channel_per_pixel + self.__plot_rect.left

    def map_point_channel_norm_to_channel(self, x):
        return x * self.__scale


class LinePlotCanvasItemDelegate:
    # interface must be implemented by the delegate

    def begin_mouse_tracking(self) -> None: ...

    def end_mouse_tracking(self, undo_command) -> None: ...

    def delete_key_pressed(self) -> None: ...

    def enter_key_pressed(self) -> None: ...

    def cursor_changed(self, pos): ...

    def update_display_properties(self, display_properties: dict) -> None: ...

    def create_change_display_command(self, *, command_id: str=None, is_mergeable: bool=False) -> Undo.UndoableCommand: ...

    def create_change_graphics_command(self) -> Undo.UndoableCommand: ...

    def push_undo_command(self, command: Undo.UndoableCommand) -> None: ...

    def add_index_to_selection(self, index: int) -> None: ...

    def remove_index_from_selection(self, index: int) -> None: ...

    def set_selection(self, index: int) -> None: ...

    def clear_selection(self) -> None: ...

    def add_and_select_region(self, region: Graphics.Graphic) -> Undo.UndoableCommand: ...

    def nudge_selected_graphics(self, mapping, delta) -> None: ...

    def update_graphics(self, widget_mapping, graphic_drag_items, graphic_drag_part, graphic_part_data, graphic_drag_start_pos, pos, modifiers) -> None: ...

    def show_display_context_menu(self, gx, gy) -> bool: ...

    @property
    def tool_mode(self) -> str: return str()

    @tool_mode.setter
    def tool_mode(self, value: str) -> None: ...


class LinePlotCanvasItem(CanvasItem.LayerCanvasItem):
    """Display a line plot.

    The layout is dependent on the axes due to the dependence on the width of the text labels in the vertical axis. The
    layout is handled by the canvas items after `refresh_layout` is called, which is only called when a change in axes
    will result in different text widths.

    The graph for each data layer is dependent on the layout, data and axes. It is possible for the axes to change
    without the layout changing if, for example, only the calibrations change but the axes stay the same. If the axes or
    the data changes, however, the plot is always redrawn. Drawing is handled by the canvas item after `update` is
    called.

    axis_y = AxisYFunction(data)
    layout = LayoutFunction(axis_y)
    axis_x = AxesXFunction(layout, data)
    plot = PlotFunction(layout, data, axis_y, axis_x)
    painting = PaintFunction(layout, plot)
    """

    def __init__(self, get_font_metrics_fn, delegate: LinePlotCanvasItemDelegate, event_loop, draw_background: bool=True):
        super().__init__()

        self.__get_font_metrics_fn = get_font_metrics_fn
        self.delegate = delegate

        self.wants_mouse_events = True

        font_size = 12

        self.__closing_lock = threading.RLock()
        self.__closed = False

        self.__line_graph_xdata_list = list()

        self.__is_data1 = False
        self.__xdata_list = list()
        self.__last_data_list = list()

        # frame rate
        self.__display_frame_rate_id = None
        self.__display_frame_rate_last_index = 0

        # child displays
        self.__display_listeners = list()

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

        for i in range(16):
            self.__line_graph_stack.add_canvas_item(LineGraphCanvasItem.LineGraphCanvasItem())

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

        # used for tracking undo
        self.__undo_command = None

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

        self.__axes = None

        self.__data_scale = None
        self.__dimensional_calibration = None
        self.__displayed_dimensional_calibration = None
        self.__intensity_calibration = None
        self.__dimensional_calibration_style = None
        self.__y_min = None
        self.__y_max = None
        self.__y_style = None
        self.__left_channel = None
        self.__right_channel = None
        self.__legend_labels = None

        self.__graphics = list()
        self.__graphic_selection = None

    def close(self):
        # call super
        with self.__closing_lock:
            self.__closed = True
        super().close()

    @property
    def line_graph_stack(self):
        return self.__line_graph_stack

    @property
    def line_graph_canvas_item(self):
        return self.__line_graph_stack.canvas_items[0] if (self.__line_graph_stack and len(self.__line_graph_xdata_list) > 0) else None

    # for testing
    @property
    def _axes(self) -> LineGraphCanvasItem.LineGraphAxes:
        return self.__axes

    @property
    def default_aspect_ratio(self):
        return (1 + 5 ** 0.5) / 2  # golden ratio

    def display_inserted(self, display, index):

        def display_changed():
            # update the data
            display_values = display.get_calculated_display_values()
            display_data_and_metadata = display_values.display_data_and_metadata
            if display_data_and_metadata:
                self.__xdata_list[index] = display_data_and_metadata
            else:
                self.__xdata_list[index] = None
            # update the cursor info
            self.__update_cursor_info()
            # mark for update. prepare display will mark children for update if necesssary.
            self.update()

        self.__xdata_list.insert(index, None)
        self.__display_listeners.insert(index, display.display_changed_event.listen(display_changed))

        display_changed()

    def display_removed(self, display, index):
        del self.__xdata_list[index]
        self.__display_listeners[index].close()
        del self.__display_listeners[index]
        # update the cursor info
        self.delegate.cursor_changed(None)
        # mark for update. prepare display will mark children for update if necesssary.
        self.update()

    def display_rgba_changed(self, display, display_values):
        # when the display rgba data changes, no need to do anything
        pass

    def display_data_and_metadata_changed(self, display, display_values):
        # when the data changes, update the display.
        self.update_display_values(display, display_values)

    def update_display_values(self, display, display_values):
        """Update the display values. Called from display panel.

        This method saves the display values and data and triggers an update. It should be as fast as possible.

        As a layer, this canvas item will respond to the update by calling prepare_render on the layer's rendering
        thread. Prepare render will call prepare_display which will construct new axes and update all of the constituent
        canvas items such as the axes labels and the graph layers. Each will trigger its own update if its inputs have
        changed.

        The inefficiencies in this process are that the layer must re-render on each call to this function. There is
        also a cost within the constituent canvas items to check whether the axes or their data has changed.

        When the display is associated with a single data item, the data will be
        """

        # may be called from thread; prevent a race condition with closing.
        with self.__closing_lock:
            if self.__closed:
                return

            dimensional_calibrations = display.dimensional_calibrations
            displayed_dimensional_scales = display.displayed_dimensional_scales
            displayed_dimensional_calibrations = display.displayed_dimensional_calibrations
            self.__data_scale = displayed_dimensional_scales[-1] if len(displayed_dimensional_scales) > 0 else 1
            self.__dimensional_calibration = dimensional_calibrations[-1] if dimensional_calibrations else None
            self.__displayed_dimensional_calibration = displayed_dimensional_calibrations[-1] if len(displayed_dimensional_calibrations) > 0 else Calibration.Calibration(scale=displayed_dimensional_scales[-1])
            self.__intensity_calibration = display.displayed_intensity_calibration
            self.__dimensional_calibration_style = display.get_calibration_style_for_id(display.dimensional_calibration_style)
            self.__y_min = display.y_min
            self.__y_max = display.y_max
            self.__y_style = display.y_style
            self.__left_channel = display.left_channel
            self.__right_channel = display.right_channel
            self.__legend_labels = display.legend_labels

            display_data_and_metadata = display_values.display_data_and_metadata
            if display_data_and_metadata:
                # store the pending display parameters
                self.__is_data1 = True
                self.__xdata_list = [display_data_and_metadata]
                self.__update_frame(display.data_and_metadata_for_display_panel.metadata)
            else:
                if self.__is_data1:
                    self.__is_data1 = False
                    self.__xdata_list = list()

            # update the cursor info
            self.__update_cursor_info()

            # mark for update. prepare display will mark children for update if necesssary.
            self.update()

    def __update_frame(self, metadata):
        # update frame rate info
        if self.__display_frame_rate_id:
            frame_index = metadata.get("hardware_source", dict()).get("frame_index", 0)
            if frame_index != self.__display_frame_rate_last_index:
                Utility.fps_tick("frame_"+self.__display_frame_rate_id)
                self.__display_frame_rate_last_index = frame_index

    def update(self):
        if self.__display_frame_rate_id:
            if len(self.__xdata_list) != len(self.__last_data_list) or not all([a is b for a, b in zip(self.__xdata_list, self.__last_data_list)]):
                Utility.fps_tick("update_"+self.__display_frame_rate_id)
                self.__last_data_list = copy.copy(self.__xdata_list)
        super().update()

    def update_regions(self, display, graphic_selection):
        dimensional_scales = display.displayed_dimensional_scales
        graphics = display.graphics

        self.__graphics = copy.copy(graphics)
        self.__graphic_selection = copy.copy(graphic_selection)

        if dimensional_scales is None or len(dimensional_scales) == 0:
            return

        data_scale = dimensional_scales[-1]
        dimensional_calibration = display.displayed_dimensional_calibrations[-1] if len(display.displayed_dimensional_calibrations) > 0 else Calibration.Calibration(scale=display.displayed_dimensional_scales[-1])

        def convert_to_calibrated_value_str(f):
            return u"{0}".format(dimensional_calibration.convert_to_calibrated_value_str(f, value_range=(0, data_scale), samples=data_scale, include_units=False))

        def convert_to_calibrated_size_str(f):
            return u"{0}".format(dimensional_calibration.convert_to_calibrated_size_str(f, value_range=(0, data_scale), samples=data_scale, include_units=False))

        regions = list()
        for graphic_index, graphic in enumerate(graphics):
            if isinstance(graphic, Graphics.IntervalGraphic):
                graphic_start, graphic_end = graphic.start, graphic.end
                graphic_start, graphic_end = min(graphic_start, graphic_end), max(graphic_start, graphic_end)
                left_channel = graphic_start * data_scale
                right_channel = graphic_end * data_scale
                left_text = convert_to_calibrated_value_str(left_channel)
                right_text = convert_to_calibrated_value_str(right_channel)
                middle_text = convert_to_calibrated_size_str(right_channel - left_channel)
                RegionInfo = collections.namedtuple("RegionInfo", ["channels", "selected", "index", "left_text", "right_text", "middle_text", "label", "style"])
                region = RegionInfo((graphic_start, graphic_end), graphic_selection.contains(graphic_index), graphic_index, left_text, right_text, middle_text, graphic.label, None)
                regions.append(region)
            elif isinstance(graphic, Graphics.ChannelGraphic):
                graphic_start, graphic_end = graphic.position, graphic.position
                graphic_start, graphic_end = min(graphic_start, graphic_end), max(graphic_start, graphic_end)
                left_channel = graphic_start * data_scale
                right_channel = graphic_end * data_scale
                left_text = convert_to_calibrated_value_str(left_channel)
                right_text = convert_to_calibrated_value_str(right_channel)
                middle_text = convert_to_calibrated_size_str(right_channel - left_channel)
                RegionInfo = collections.namedtuple("RegionInfo", ["channels", "selected", "index", "left_text", "right_text", "middle_text", "label", "style"])
                region = RegionInfo((graphic_start, graphic_end), graphic_selection.contains(graphic_index), graphic_index, left_text, right_text, middle_text, graphic.label, "tag")
                regions.append(region)

        self.__line_graph_regions_canvas_item.set_regions(regions)

    def handle_auto_display(self, display) -> bool:
        # enter key has been pressed
        data_and_metadata = display.data_and_metadata_for_display_panel
        display.view_to_selected_graphics(data_and_metadata)
        return True

    def prepare_display(self):
        """Prepare the display.

        This method gets called by the canvas layout/draw engine after being triggered by a call to `update`.

        When data or display parameters change, the internal state of the line plot gets updated. This method takes
        that internal state and updates the child canvas items.

        This method is always run on a thread and should be fast but doesn't need to be instant.
        """
        displayed_dimensional_calibration = self.__displayed_dimensional_calibration
        intensity_calibration = self.__intensity_calibration
        dimensional_calibration_style = self.__dimensional_calibration_style
        y_min = self.__y_min
        y_max = self.__y_max
        y_style = self.__y_style
        left_channel = self.__left_channel
        right_channel = self.__right_channel
        legend_labels = self.__legend_labels

        scalar_xdata_list = None

        def calculate_scalar_xdata(xdata_list):
            scalar_xdata_list = list()
            for xdata in xdata_list:
                if xdata:
                    scalar_data = Image.scalar_from_array(xdata.data)
                    scalar_data = Image.convert_to_grayscale(scalar_data)
                    scalar_intensity_calibration = dimensional_calibration_style.get_intensity_calibration(xdata)
                    scalar_dimensional_calibrations = dimensional_calibration_style.get_dimensional_calibrations(xdata.dimensional_shape, xdata.dimensional_calibrations)
                    # check whether there is common units between the data and the display
                    if not displayed_dimensional_calibration.units and self.__dimensional_calibration and scalar_dimensional_calibrations[-1].units == self.__dimensional_calibration.units:
                        scalar_dimensional_calibrations = scalar_dimensional_calibrations[0:-1] + [Calibration.Calibration(scale=self.__data_scale)]
                    if displayed_dimensional_calibration.units == scalar_dimensional_calibrations[-1].units:
                        scalar_xdata_list.append(DataAndMetadata.new_data_and_metadata(scalar_data, scalar_intensity_calibration, scalar_dimensional_calibrations))
                else:
                    scalar_xdata_list.append(None)
            return scalar_xdata_list

        data_scale = self.__data_scale
        xdata_list = self.__xdata_list

        if data_scale is not None:
            # update the line graph data
            left_channel = left_channel if left_channel is not None else 0
            right_channel = right_channel if right_channel is not None else data_scale
            left_channel, right_channel = min(left_channel, right_channel), max(left_channel, right_channel)

            scalar_data_list = None
            if y_min is None or y_max is None and len(xdata_list) > 0:
                scalar_xdata_list = calculate_scalar_xdata(xdata_list)
                scalar_data_list = [xdata.data if xdata else None for xdata in scalar_xdata_list]
            calibrated_data_min, calibrated_data_max, y_ticker = LineGraphCanvasItem.calculate_y_axis(scalar_data_list, y_min, y_max, intensity_calibration, y_style)
            axes = LineGraphCanvasItem.LineGraphAxes(data_scale, calibrated_data_min, calibrated_data_max, left_channel, right_channel, displayed_dimensional_calibration, intensity_calibration, y_style, y_ticker)

            if scalar_xdata_list is None:
                if len(xdata_list) > 0:
                    scalar_xdata_list = calculate_scalar_xdata(xdata_list)
                else:
                    scalar_xdata_list = list()

            line_graph_xdata_list = list()

            if self.__display_frame_rate_id:
                Utility.fps_tick("prepare_"+self.__display_frame_rate_id)

            for scalar_xdata in scalar_xdata_list:
                if scalar_xdata and scalar_xdata.is_data_1d:
                    line_graph_xdata_list.append(scalar_xdata)
                elif scalar_xdata and scalar_xdata.is_data_2d:
                    rows = min(16, scalar_xdata.dimensional_shape[0])
                    intensity_calibration = scalar_xdata.intensity_calibration
                    displayed_dimensional_calibration = scalar_xdata.dimensional_calibrations[-1]
                    for row in range(rows):
                        scalar_data_row = scalar_xdata.data[row:row + 1, :].reshape((scalar_xdata.dimensional_shape[-1],))
                        scalar_xdata_row = DataAndMetadata.new_data_and_metadata(scalar_data_row, intensity_calibration, [displayed_dimensional_calibration])
                        line_graph_xdata_list.append(scalar_xdata_row)
                else:
                    line_graph_xdata_list.append(None)

            line_graph_xdata_list = line_graph_xdata_list[0:16]

            colors = ('#1E90FF', "#F00", "#0F0", "#00F", "#FF0", "#0FF", "#F0F", "#888", "#800", "#080", "#008", "#CCC", "#880", "#088", "#808", "#964B00")

            for index, line_graph_canvas_item in enumerate(self.__line_graph_stack.canvas_items):
                if index < len(line_graph_xdata_list):
                    line_graph_canvas_item.set_is_filled(index == 0)
                    line_graph_canvas_item.set_color(colors[index])
                    line_graph_canvas_item.set_axes(axes)
                    line_graph_canvas_item.set_uncalibrated_xdata(line_graph_xdata_list[index])
                else:
                    line_graph_canvas_item.set_axes(None)
                    line_graph_canvas_item.set_uncalibrated_xdata(None)

            self.__line_graph_xdata_list = line_graph_xdata_list

            self.__update_canvas_items(axes, legend_labels)
        else:
            for line_graph_canvas_item in self.__line_graph_stack.canvas_items:
                line_graph_canvas_item.set_axes(None)
                line_graph_canvas_item.set_uncalibrated_xdata(None)
            self.__line_graph_xdata_list = list()
            self.__update_canvas_items(LineGraphCanvasItem.LineGraphAxes(), None)

    def _inserted(self, container):
        # make sure we get 'prepare_render' calls
        self.register_prepare_canvas_item(self)

    def _removed(self, container):
        # turn off 'prepare_render' calls
        self.unregister_prepare_canvas_item(self)

    def prepare_render(self):
        self.prepare_display()

    def _repaint(self, drawing_context):
        super()._repaint(drawing_context)

        if self.__display_frame_rate_id:
            Utility.fps_tick("display_"+self.__display_frame_rate_id)

        if self.__display_frame_rate_id:
            fps = Utility.fps_get("display_"+self.__display_frame_rate_id)
            fps2 = Utility.fps_get("frame_"+self.__display_frame_rate_id)
            fps3 = Utility.fps_get("update_"+self.__display_frame_rate_id)
            fps4 = Utility.fps_get("prepare_"+self.__display_frame_rate_id)

            rect = self.canvas_bounds

            with drawing_context.saver():
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
                drawing_context.fill_text("prepare:" + fps4, text_pos.x + 8, text_pos.y + 70)

    def __update_canvas_items(self, axes, legend_labels):
        self.__line_graph_background_canvas_item.set_axes(axes)
        self.__line_graph_regions_canvas_item.set_axes(axes)
        self.__line_graph_regions_canvas_item.set_calibrated_data(self.line_graph_canvas_item.calibrated_xdata.data if self.line_graph_canvas_item and self.line_graph_canvas_item.calibrated_xdata else None)
        self.__line_graph_frame_canvas_item.set_draw_frame(axes.is_valid)
        self.__line_graph_legend_canvas_item.set_legend_labels(legend_labels)
        self.__line_graph_vertical_axis_label_canvas_item.set_axes(axes)
        self.__line_graph_vertical_axis_scale_canvas_item.set_axes(axes, self.__get_font_metrics_fn)
        self.__line_graph_vertical_axis_ticks_canvas_item.set_axes(axes)
        self.__line_graph_horizontal_axis_label_canvas_item.set_axes(axes)
        self.__line_graph_horizontal_axis_scale_canvas_item.set_axes(axes)
        self.__line_graph_horizontal_axis_ticks_canvas_item.set_axes(axes)

        self.__axes = axes

    def mouse_entered(self):
        if super().mouse_entered():
            return True
        self.__mouse_in = True
        return True

    def mouse_exited(self):
        if super().mouse_exited():
            return True
        self.__mouse_in = False
        self.__update_cursor_info()
        if self.delegate:  # allow display to work without delegate
            # whenever the cursor exits, clear the cursor display
            self.delegate.cursor_changed(None)
        return True

    def mouse_double_clicked(self, x, y, modifiers):
        if super().mouse_clicked(x, y, modifiers):
            return True
        if self.delegate.tool_mode == "pointer":
            pos = Geometry.IntPoint(x=x, y=y)
            if self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_horizontal_axis_group_canvas_item)):
                command = self.delegate.create_change_display_command()
                self.delegate.update_display_properties({"left_channel": None, "right_channel": None})
                self.delegate.push_undo_command(command)
                return True
            elif self.__line_graph_vertical_axis_group_canvas_item.canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.__line_graph_vertical_axis_group_canvas_item)):
                command = self.delegate.create_change_display_command()
                self.delegate.update_display_properties({"y_min": None, "y_max": None})
                self.delegate.push_undo_command(command)
                return True
        return False

    def mouse_position_changed(self, x, y, modifiers):
        if super().mouse_position_changed(x, y, modifiers):
            return True
        if self.delegate.tool_mode == "pointer":
            if self.__axes and self.__axes.is_valid:
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
        if super().mouse_pressed(x, y, modifiers):
            return True
        if not self.__axes or not self.__axes.is_valid:
            return False
        self.__undo_command = None
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
                widget_mapping = self.__get_mouse_mapping()
                x = widget_mapping.map_point_widget_to_channel_norm(pos)
                region = Graphics.IntervalGraphic()
                region.start = x
                region.end = x
                self.__undo_command = self.delegate.add_and_select_region(region)
                self.begin_tracking_regions(pos, Graphics.NullModifiers())
                return True
        return False

    def mouse_released(self, x, y, modifiers):
        if super().mouse_released(x, y, modifiers):
            return True
        if not self.__axes or not self.__axes.is_valid:
            return False
        self.end_tracking(modifiers)
        self.delegate.end_mouse_tracking(self.__undo_command)
        return False

    def _mouse_dragged(self, start: float, end: float, modifiers=None) -> None:
        # for testing
        plot_origin = self.line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
        plot_left = self.line_graph_canvas_item.canvas_rect.left + plot_origin.x
        plot_width = self.line_graph_canvas_item.canvas_rect.width
        modifiers = modifiers if modifiers else CanvasItem.KeyboardModifiers()
        self.mouse_pressed(plot_left + plot_width * start, 100, modifiers)
        self.mouse_position_changed(plot_left + plot_width * start, 100, modifiers)
        self.mouse_position_changed(plot_left + plot_width * (start + end) / 2, 100, modifiers)
        self.mouse_position_changed(plot_left + plot_width * end, 100, modifiers)
        self.mouse_released(plot_left + plot_width * end, 100, modifiers)

    def context_menu_event(self, x, y, gx, gy):
        return self.delegate.show_display_context_menu(gx, gy)

    # ths message comes from the widget
    def key_pressed(self, key):
        if super().key_pressed(key):
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
        data_scale = self.__data_scale
        plot_origin = self.__line_graph_regions_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
        plot_rect = self.__line_graph_regions_canvas_item.canvas_bounds.translated(plot_origin)
        left_channel = self.__axes.drawn_left_channel
        right_channel = self.__axes.drawn_right_channel
        return LinePlotCanvasItemMapping(data_scale, plot_rect, left_channel, right_channel)

    def begin_tracking_regions(self, pos, modifiers):
        # keep track of general drag information
        self.__graphic_drag_start_pos = Geometry.IntPoint.make(pos)
        self.__graphic_drag_changed = False
        if self.__axes and self.__axes.is_valid:
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
        self.__tracking_horizontal = True
        self.__tracking_rescale = rescale
        self.__tracking_start_pos = pos
        self.__tracking_start_left_channel = self.__axes.drawn_left_channel
        self.__tracking_start_right_channel = self.__axes.drawn_right_channel
        self.__tracking_start_drawn_channel_per_pixel = float(self.__tracking_start_right_channel - self.__tracking_start_left_channel) / plot_rect.width
        self.__tracking_start_origin_pixel = self.__tracking_start_pos.x - plot_rect.left
        self.__tracking_start_channel = self.__tracking_start_left_channel + self.__tracking_start_origin_pixel * self.__tracking_start_drawn_channel_per_pixel

    def begin_tracking_vertical(self, pos, rescale):
        plot_height = self.__line_graph_area_stack.canvas_bounds.height - 1
        self.__tracking_vertical = True
        self.__tracking_rescale = rescale
        self.__tracking_start_pos = pos
        self.__tracking_start_calibrated_data_min = self.__axes.calibrated_data_min
        self.__tracking_start_calibrated_data_max = self.__axes.calibrated_data_max
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
                self.__undo_command = self.delegate.add_and_select_region(region)
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
            else:
                if not self.__undo_command:
                    self.__undo_command = self.delegate.create_change_graphics_command()
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
            if not self.__undo_command:
                self.__undo_command = self.delegate.create_change_display_command()
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
            if not self.__undo_command:
                self.__undo_command = self.delegate.create_change_display_command()
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
                uncalibrated_data_min = self.__axes.uncalibrate_y(calibrated_data_min)
                uncalibrated_data_max = self.__axes.uncalibrate_y(calibrated_data_max)
                self.delegate.update_display_properties({"y_min": uncalibrated_data_min, "y_max": uncalibrated_data_max})
                return True
            else:
                delta = pos - self.__tracking_start_pos
                calibrated_data_min = self.__tracking_start_calibrated_data_min + self.__tracking_start_calibrated_data_per_pixel * delta.y
                calibrated_data_max = self.__tracking_start_calibrated_data_max + self.__tracking_start_calibrated_data_per_pixel * delta.y
                uncalibrated_data_min = self.__axes.uncalibrate_y(calibrated_data_min)
                uncalibrated_data_max = self.__axes.uncalibrate_y(calibrated_data_max)
                self.delegate.update_display_properties({"y_min": uncalibrated_data_min, "y_max": uncalibrated_data_max})
                return True
        return False

    def end_tracking(self, modifiers):
        if not self.__graphic_drag_items and not modifiers.control:
            self.delegate.clear_selection()
        if self.__tracking_selections:
            if self.__axes and self.__axes.is_valid:
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
        """ Map the mouse to the 1-d position within the line graph. """

        if not self.delegate:  # allow display to work without delegate
            return

        if self.__mouse_in and self.__last_mouse:
            pos_1d = None
            axes = self.__axes
            line_graph_canvas_item = self.line_graph_canvas_item
            if axes and axes.is_valid and line_graph_canvas_item:
                mouse = self.map_to_canvas_item(self.__last_mouse, line_graph_canvas_item)
                plot_rect = line_graph_canvas_item.canvas_bounds
                if plot_rect.contains_point(mouse):
                    mouse = mouse - plot_rect.origin
                    x = float(mouse.x) / plot_rect.width
                    px = axes.drawn_left_channel + x * (axes.drawn_right_channel - axes.drawn_left_channel)
                    pos_1d = px,
            self.delegate.cursor_changed(pos_1d)
