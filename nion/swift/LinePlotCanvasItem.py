from __future__ import annotations

# standard libraries
import copy
import math
import threading
import typing

# third party libraries
import numpy
import numpy.typing

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift import DisplayCanvasItem
from nion.swift import LineGraphCanvasItem
from nion.swift import MimeTypes
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import UISettings
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.utils import Geometry
from nion.utils import Registry

if typing.TYPE_CHECKING:
    from nion.swift.model import Persistence
    from nion.swift import Undo
    from nion.ui import DrawingContext
    from nion.ui import UserInterface

_NDArray = numpy.typing.NDArray[typing.Any]


class LinePlotCanvasItemMapping(Graphics.CoordinateMappingLike):

    def __init__(self, scale: float, plot_rect: Geometry.IntRect, left_channel: int, right_channel: int) -> None:
        self.__scale = scale
        self.__plot_rect = plot_rect
        self.__left_channel = left_channel
        self.__right_channel = right_channel
        self.__drawn_channel_per_pixel = float(right_channel - left_channel) / plot_rect.width

    def map_point_widget_to_channel_norm(self, pos: Geometry.FloatPoint) -> float:
        return (self.__left_channel + (pos.x - self.__plot_rect.left) * self.__drawn_channel_per_pixel) / self.__scale

    def map_point_channel_norm_to_widget(self, x: float) -> float:
        return (x * self.__scale - self.__left_channel) / self.__drawn_channel_per_pixel + self.__plot_rect.left

    def map_point_channel_norm_to_channel(self, x: float) -> float:
        return x * self.__scale

    @property
    def data_shape(self) -> DataAndMetadata.Shape2dType:
        return (0, 0)

    @property
    def calibrated_origin_image_norm(self) -> Geometry.FloatPoint:
        return Geometry.FloatPoint()

    @property
    def calibrated_origin_widget(self) -> Geometry.FloatPoint:
        return Geometry.FloatPoint()


class LinePlotCanvasItem(DisplayCanvasItem.DisplayCanvasItem):
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

    def __init__(self, ui_settings: UISettings.UISettings,
                 delegate: typing.Optional[DisplayCanvasItem.DisplayCanvasItemDelegate]) -> None:
        super().__init__()

        self.__ui_settings = ui_settings
        self.delegate = delegate

        self.wants_mouse_events = True

        font_size = 12

        self.__closing_lock = threading.RLock()
        self.__closed = False

        self.___has_valid_drawn_graph_data = False

        self.__xdata_list: typing.List[typing.Optional[DataAndMetadata.DataAndMetadata]] = list()
        self.__last_xdata_list: typing.List[typing.Optional[DataAndMetadata.DataAndMetadata]] = list()

        # frame rate
        self.__display_frame_rate_id: typing.Optional[str] = None
        self.__display_frame_rate_last_index = 0

        self.__line_graph_area_stack = CanvasItem.CanvasItemComposition()
        self.__line_graph_background_canvas_item = LineGraphCanvasItem.LineGraphBackgroundCanvasItem()
        self.__line_graph_stack = CanvasItem.CanvasItemComposition()
        self.__line_graph_regions_canvas_item = LineGraphCanvasItem.LineGraphRegionsCanvasItem()
        self.__line_graph_legend_row = CanvasItem.CanvasItemComposition()
        self.__line_graph_legend_row.layout = CanvasItem.CanvasItemRowLayout(margins=Geometry.Margins(4, 8, 4, 8))
        self.__line_graph_legend_canvas_item = LineGraphCanvasItem.LineGraphLegendCanvasItem(ui_settings, typing.cast(LineGraphCanvasItem.LineGraphLegendCanvasItemDelegate, delegate))
        self.__line_graph_legend_row.add_stretch()
        self.__line_graph_legend_row.add_canvas_item(self.__line_graph_legend_canvas_item)
        self.__line_graph_legend_row.add_stretch()
        self.__line_graph_legend_column = CanvasItem.CanvasItemComposition()
        self.__line_graph_legend_column.layout = CanvasItem.CanvasItemColumnLayout()
        self.__line_graph_legend_column.add_canvas_item(self.__line_graph_legend_row)
        self.__line_graph_legend_column.add_stretch()
        self.__line_graph_outer_left_column = CanvasItem.CanvasItemComposition()
        self.__line_graph_outer_left_column.layout = CanvasItem.CanvasItemColumnLayout(margins=Geometry.Margins(16, 16, 0, 0))
        self.__line_graph_outer_left_legend = LineGraphCanvasItem.LineGraphLegendCanvasItem(ui_settings, typing.cast(LineGraphCanvasItem.LineGraphLegendCanvasItemDelegate, delegate))
        self.__line_graph_outer_left_column.add_canvas_item(self.__line_graph_outer_left_legend)
        self.__line_graph_outer_left_column.add_stretch()
        self.__line_graph_outer_right_column = CanvasItem.CanvasItemComposition()
        self.__line_graph_outer_right_column.layout = CanvasItem.CanvasItemColumnLayout(margins=Geometry.Margins(16, 0, 0, 16))
        self.__line_graph_outer_right_legend = LineGraphCanvasItem.LineGraphLegendCanvasItem(ui_settings, typing.cast(LineGraphCanvasItem.LineGraphLegendCanvasItemDelegate, delegate))
        self.__line_graph_outer_right_column.add_canvas_item(self.__line_graph_outer_right_legend)
        self.__line_graph_outer_right_column.add_stretch()
        self.__line_graph_frame_canvas_item = LineGraphCanvasItem.LineGraphFrameCanvasItem()
        self.__line_graph_area_stack.add_canvas_item(self.__line_graph_background_canvas_item)
        self.__line_graph_area_stack.add_canvas_item(self.__line_graph_stack)
        self.__line_graph_area_stack.add_canvas_item(self.__line_graph_regions_canvas_item)
        self.__line_graph_area_stack.add_canvas_item(self.__line_graph_legend_column)
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

        self.__overlap_controls = CanvasItem.CanvasItemComposition()
        self.__overlap_controls.layout = CanvasItem.CanvasItemColumnLayout()
        self.__overlap_controls.add_stretch()

        # create and add the outer level labels
        legend_row = CanvasItem.CanvasItemComposition()
        legend_row.layout = CanvasItem.CanvasItemRowLayout()
        legend_row.add_canvas_item(self.__line_graph_outer_left_column)
        legend_row.add_canvas_item(line_graph_group_canvas_item)
        legend_row.add_canvas_item(self.__line_graph_outer_right_column)

        # draw the background
        line_graph_background_canvas_item = CanvasItem.CanvasItemComposition()
        #line_graph_background_canvas_item.update_sizing(line_graph_background_canvas_item.size.with_minimum_aspect_ratio(1.5))  # note: no maximum aspect ratio; line plot looks nice wider.
        line_graph_background_canvas_item.add_canvas_item(CanvasItem.BackgroundCanvasItem("#FFF"))
        line_graph_background_canvas_item.add_canvas_item(self.__overlap_controls)

        line_graph_background_canvas_item.add_canvas_item(legend_row)

        self.__display_controls = CanvasItem.CanvasItemComposition()
        self.__display_controls.layout = CanvasItem.CanvasItemColumnLayout()
        self.__display_controls.add_canvas_item(line_graph_background_canvas_item)

        # canvas items get added back to front
        # create the child canvas items
        # the background
        self.add_canvas_item(CanvasItem.BackgroundCanvasItem("#FFF"))
        # self.add_canvas_item(line_graph_background_canvas_item)
        self.add_canvas_item(self.__display_controls)

        self.__display_values_list: typing.List[typing.Optional[DisplayItem.DisplayValues]] = list()

        # used for tracking undo
        self.__undo_command: typing.Optional[Undo.UndoableCommand] = None

        # used for dragging graphic items
        self.__graphic_drag_items: typing.List[Graphics.Graphic] = list()
        self.__graphic_drag_item: typing.Optional[Graphics.Graphic] = None
        self.__graphic_part_data: typing.Dict[int, Graphics.DragPartData] = dict()
        self.__graphic_drag_indexes: typing.Set[int] = set()
        self.__last_mouse: typing.Optional[Geometry.IntPoint] = None
        self.__mouse_in = False
        self.__tracking_selections = False
        self.__tracking_horizontal = False
        self.__tracking_vertical = False

        self.__graphic_drag_start_pos: Geometry.IntPoint = Geometry.IntPoint()
        self.__graphic_drag_changed = False

        self.__axes: typing.Optional[LineGraphCanvasItem.LineGraphAxes] = None

        self.__data_scale: typing.Optional[float] = None
        self.__displayed_dimensional_calibration: typing.Optional[Calibration.Calibration] = None
        self.__intensity_calibration: typing.Optional[Calibration.Calibration] = None
        self.__calibration_style: typing.Optional[DisplayItem.CalibrationStyle] = None
        self.__y_min = None
        self.__y_max = None
        self.__y_style = None
        self.__left_channel = None
        self.__right_channel = None
        self.__legend_position = None

        self.__graphics: typing.List[Graphics.Graphic] = list()
        self.__graphic_selection: typing.Optional[DisplayItem.GraphicSelection] = None
        self.__pending_interval: typing.Optional[Graphics.IntervalGraphic] = None

    def close(self) -> None:
        if self.__undo_command:
            self.__undo_command.close()
            self.__undo_command = None
        with self.__closing_lock:
            self.__closed = True
        self.__display_values_list = typing.cast(typing.Any, None)
        super().close()

    @property
    def line_graph_stack(self) -> CanvasItem.CanvasItemComposition:
        return self.__line_graph_stack

    @property
    def default_aspect_ratio(self) -> float:
        return (1 + 5 ** 0.5) / 2  # golden ratio

    @property
    def line_graph_canvas_item(self) -> typing.Optional[LineGraphCanvasItem.LineGraphCanvasItem]:
        return typing.cast(LineGraphCanvasItem.LineGraphCanvasItem, self.__line_graph_stack.canvas_items[0]) if self.__line_graph_stack else None

    # for testing
    @property
    def _axes(self) -> typing.Optional[LineGraphCanvasItem.LineGraphAxes]:
        return self.__axes

    @property
    def _has_valid_drawn_graph_data(self) -> bool:
        return self.___has_valid_drawn_graph_data

    def __update_legend_origin(self) -> None:
        self.__line_graph_legend_canvas_item.size_to_content()
        self.__line_graph_outer_left_legend.size_to_content()
        self.__line_graph_outer_right_legend.size_to_content()

        self.__line_graph_legend_row.visible = False
        self.__line_graph_legend_row.canvas_items[0].visible = False
        self.__line_graph_legend_row.canvas_items[2].visible = False
        self.__line_graph_outer_right_column.visible = False
        self.__line_graph_outer_left_column.visible = False

        if self.__legend_position == "top-left":
            self.__line_graph_legend_row.visible= True
            self.__line_graph_legend_row.canvas_items[2].visible = True
        elif self.__legend_position == "top-right":
            self.__line_graph_legend_row.visible = True
            self.__line_graph_legend_row.canvas_items[0].visible = True
        elif self.__legend_position == "outer-left":
            self.__line_graph_outer_left_column.visible = True
        elif self.__legend_position == "outer-right":
            self.__line_graph_outer_right_column.visible = True

    def add_display_control(self, display_control_canvas_item: CanvasItem.AbstractCanvasItem, role: typing.Optional[str] = None) -> None:
        if role == "related_icons":
            self.__overlap_controls.add_canvas_item(display_control_canvas_item)
        else:
            self.__display_controls.add_canvas_item(display_control_canvas_item)

    def update_display_values(self, display_values_list: typing.Sequence[typing.Optional[DisplayItem.DisplayValues]]) -> None:
        self.__display_values_list = list(display_values_list)

    def update_display_properties_and_layers(self, display_calibration_info: DisplayItem.DisplayCalibrationInfo,
                                             display_properties: Persistence.PersistentDictType,
                                             display_layers: typing.Sequence[Persistence.PersistentDictType]) -> None:
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

            displayed_dimensional_scales: typing.Tuple[float, ...] = display_calibration_info.displayed_dimensional_scales or tuple()
            displayed_dimensional_calibrations = display_calibration_info.displayed_dimensional_calibrations
            self.__data_scale = displayed_dimensional_scales[-1] if len(displayed_dimensional_scales) > 0 else 1.0
            self.__displayed_dimensional_calibration = displayed_dimensional_calibrations[-1] if len(displayed_dimensional_calibrations) > 0 else Calibration.Calibration(scale=displayed_dimensional_scales[-1])
            self.__intensity_calibration = display_calibration_info.displayed_intensity_calibration
            self.__calibration_style = display_calibration_info.calibration_style
            self.__y_min = display_properties.get("y_min")
            self.__y_max = display_properties.get("y_max")
            self.__y_style = display_properties.get("y_style", "linear")
            self.__left_channel = display_properties.get("left_channel")
            self.__right_channel = display_properties.get("right_channel")
            self.__legend_position = display_properties.get("legend_position")
            self.__display_layers = display_layers

            if len(self.__display_values_list) > 0:
                self.__xdata_list = [display_values.display_data_and_metadata if display_values else None for display_values in self.__display_values_list]
                xdata0 = self.__xdata_list[0]
                if xdata0:
                    self.__update_frame(xdata0.metadata)
            else:
                self.__xdata_list = list()

            # update the cursor info
            self.__update_cursor_info()

            # mark for update. prepare display will mark children for update if necesssary.
            self.update()

    def __update_frame(self, metadata: DataAndMetadata.MetadataType) -> None:
        # update frame rate info
        if self.__display_frame_rate_id:
            # allow registered metadata_display components to populate a dictionary
            # the line plot canvas item will look at "frame_index"
            d: Persistence.PersistentDictType = dict()
            for component in Registry.get_components_by_type("metadata_display"):
                component.populate(d, metadata)

            # pull out the frame_index key
            frame_index = d.get("frame_index", 0)

            if frame_index != self.__display_frame_rate_last_index:
                Utility.fps_tick("frame_"+self.__display_frame_rate_id)
                self.__display_frame_rate_last_index = frame_index

    def update(self) -> None:
        if self.__display_frame_rate_id:
            if len(self.__xdata_list) != len(self.__last_xdata_list) or not all([a is b for a, b in zip(self.__xdata_list, self.__last_xdata_list)]):
                Utility.fps_tick("update_"+self.__display_frame_rate_id)
                self.__last_xdata_list = copy.copy(self.__xdata_list)
        super().update()

    def update_graphics_coordinate_system(self, graphics: typing.Sequence[Graphics.Graphic],
                                          graphic_selection: DisplayItem.GraphicSelection,
                                          display_calibration_info: DisplayItem.DisplayCalibrationInfo) -> None:
        dimensional_scales = display_calibration_info.displayed_dimensional_scales

        self.__graphics = copy.copy(list(graphics))
        self.__graphic_selection = copy.copy(graphic_selection)

        if dimensional_scales is None or len(dimensional_scales) == 0:
            return
        assert dimensional_scales is not None

        data_scale = dimensional_scales[-1]
        dimensional_calibration = display_calibration_info.displayed_dimensional_calibrations[-1] if len(display_calibration_info.displayed_dimensional_calibrations) > 0 else Calibration.Calibration(scale=data_scale)

        def convert_to_calibrated_value_str(f: float) -> str:
            return u"{0}".format(dimensional_calibration.convert_to_calibrated_value_str(f, value_range=(0, data_scale),
                                                                                         samples=round(data_scale),
                                                                                         include_units=False))

        def convert_to_calibrated_size_str(f: float) -> str:
            return u"{0}".format(dimensional_calibration.convert_to_calibrated_size_str(f, value_range=(0, data_scale),
                                                                                        samples=round(data_scale),
                                                                                        include_units=False))

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
                region = LineGraphCanvasItem.RegionInfo((graphic_start, graphic_end), graphic_selection.contains(graphic_index), graphic_index, left_text, right_text, middle_text, graphic.label, None, graphic.color)
                regions.append(region)
            elif isinstance(graphic, Graphics.ChannelGraphic):
                graphic_start, graphic_end = graphic.position, graphic.position
                graphic_start, graphic_end = min(graphic_start, graphic_end), max(graphic_start, graphic_end)
                left_channel = graphic_start * data_scale
                right_channel = graphic_end * data_scale
                left_text = convert_to_calibrated_value_str(left_channel)
                right_text = convert_to_calibrated_value_str(right_channel)
                middle_text = convert_to_calibrated_size_str(right_channel - left_channel)
                region = LineGraphCanvasItem.RegionInfo((graphic_start, graphic_end), graphic_selection.contains(graphic_index), graphic_index, left_text, right_text, middle_text, graphic.label, "tag", graphic.color)
                regions.append(region)

        self.__line_graph_regions_canvas_item.set_regions(regions)

    def __view_to_intervals(self, data_and_metadata: DataAndMetadata.DataAndMetadata, intervals: typing.List[typing.Tuple[float, float]]) -> None:
        """Change the view to encompass the channels and data represented by the given intervals."""
        left = None
        right = None
        for interval in intervals:
            if left is not None:
                left = min(left, interval[0])
            else:
                left = interval[0]
            if right is not None:
                right = max(right, interval[1])
            else:
                right = interval[1]
        left = left if left is not None else 0.0
        right = right if right is not None else 1.0
        left_channel = int(max(0.0, left) * data_and_metadata.data_shape[-1])
        right_channel = int(min(1.0, right) * data_and_metadata.data_shape[-1])
        data_in_channel = data_and_metadata.data
        assert data_in_channel is not None
        data_min = numpy.amin(data_in_channel[..., left_channel:right_channel])
        data_max = numpy.amax(data_in_channel[..., left_channel:right_channel])
        if data_min > 0 and data_max > 0:
            y_min = 0.0
            y_max = data_max * 1.2
        elif data_min < 0 and data_max < 0:
            y_min = data_min * 1.2
            y_max = 0.0
        else:
            y_min = data_min * 1.2
            y_max = data_max * 1.2
        extra = (right - left) * 0.5
        display_left_channel = int((left - extra) * data_and_metadata.data_shape[-1])
        display_right_channel = int((right + extra) * data_and_metadata.data_shape[-1])
        # command = self.delegate.create_change_display_command()
        assert self.delegate
        self.delegate.update_display_properties({"left_channel": display_left_channel, "right_channel": display_right_channel, "y_min": y_min, "y_max": y_max})
        # self.delegate.push_undo_command(command)

    def __view_to_selected_graphics(self, data_and_metadata: DataAndMetadata.DataAndMetadata) -> None:
        """Change the view to encompass the selected graphic intervals."""
        all_graphics = self.__graphics
        graphics: typing.List[Graphics.Graphic]
        if self.__graphic_selection:
            graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if self.__graphic_selection.contains(graphic_index)]
        else:
            graphics = list()
        intervals = list()
        for graphic in graphics:
            if isinstance(graphic, Graphics.IntervalGraphic):
                intervals.append(graphic.interval)
        self.__view_to_intervals(data_and_metadata, intervals)

    def handle_auto_display(self) -> bool:
        if len(self.__xdata_list) > 0:
            xdata0 = self.__xdata_list[0]
            if xdata0:
                self.__view_to_selected_graphics(xdata0)
        return True

    def prepare_display(self) -> None:
        """Prepare the display.

        This method gets called by the canvas layout/draw engine after being triggered by a call to `update`.

        When data or display parameters change, the internal state of the line plot gets updated. This method takes
        that internal state and updates the child canvas items.

        This method is always run on a thread and should be fast but doesn't need to be instant.
        """
        displayed_dimensional_calibration = self.__displayed_dimensional_calibration or Calibration.Calibration()
        intensity_calibration = self.__intensity_calibration or Calibration.Calibration()
        calibration_style = self.__calibration_style or DisplayItem.CalibrationStyle()
        y_min = self.__y_min
        y_max = self.__y_max
        y_style = self.__y_style
        left_channel_opt = self.__left_channel
        right_channel_opt = self.__right_channel

        scalar_xdata_list = None

        def calculate_scalar_xdata(xdata_list: typing.Sequence[typing.Optional[DataAndMetadata.DataAndMetadata]]) -> typing.Sequence[typing.Optional[DataAndMetadata.DataAndMetadata]]:
            scalar_xdata_list: typing.List[typing.Optional[DataAndMetadata.DataAndMetadata]] = list()
            for xdata in xdata_list:
                if xdata:
                    scalar_data = Image.convert_to_grayscale(numpy.array(xdata.data))  # note: ensure scalar_data is numpy.array
                    scalar_intensity_calibration = calibration_style.get_intensity_calibration(xdata)
                    scalar_dimensional_calibrations = calibration_style.get_dimensional_calibrations(xdata.dimensional_shape, xdata.dimensional_calibrations)
                    if displayed_dimensional_calibration.units == scalar_dimensional_calibrations[-1].units and intensity_calibration.units == scalar_intensity_calibration.units:
                        # the data needs to have an intensity scale matching intensity_calibration. convert the data to use the common scale.
                        scale = scalar_intensity_calibration.scale / intensity_calibration.scale
                        offset = (scalar_intensity_calibration.offset - intensity_calibration.offset) / intensity_calibration.scale
                        scalar_data = scalar_data * scale + offset  # type: ignore
                        scalar_xdata_list.append(DataAndMetadata.new_data_and_metadata(scalar_data, scalar_intensity_calibration, scalar_dimensional_calibrations))
                else:
                    scalar_xdata_list.append(None)
            return scalar_xdata_list

        data_scale = self.__data_scale
        xdata_list = self.__xdata_list

        if data_scale is not None:
            # update the line graph data
            left_channel = left_channel_opt if left_channel_opt is not None else 0
            right_channel = right_channel_opt if right_channel_opt is not None else data_scale
            left_channel = typing.cast(int, min(left_channel, right_channel))
            right_channel = typing.cast(int, max(left_channel, right_channel))

            scalar_data_list: typing.List[typing.Optional[_NDArray]] = list()
            if y_min is None or y_max is None and len(xdata_list) > 0:
                scalar_xdata_list = calculate_scalar_xdata(xdata_list)
                scalar_data_list = [xdata.data if xdata else None for xdata in scalar_xdata_list]
            calibrated_data_min, calibrated_data_max, y_ticker = LineGraphCanvasItem.calculate_y_axis(scalar_data_list, y_min, y_max, intensity_calibration, y_style)
            axes = LineGraphCanvasItem.LineGraphAxes(data_scale, calibrated_data_min, calibrated_data_max, left_channel, right_channel, displayed_dimensional_calibration, intensity_calibration, y_style, y_ticker)

            if scalar_xdata_list is None:
                scalar_xdata_list = calculate_scalar_xdata(xdata_list)

            if self.__display_frame_rate_id:
                Utility.fps_tick("prepare_"+self.__display_frame_rate_id)

            colors = ('#1E90FF', "#F00", "#0F0", "#00F", "#FF0", "#0FF", "#F0F", "#888", "#800", "#080", "#008", "#CCC", "#880", "#088", "#808", "#964B00")

            max_layer_count = len(self.__line_graph_stack.canvas_items)

            display_layers = list(self.__display_layers)

            if len(display_layers) == 0:
                index = 0
                for scalar_index, scalar_xdata in enumerate(scalar_xdata_list):
                    if scalar_xdata and scalar_xdata.is_data_1d:
                        if index < max_layer_count:
                            display_layers.append({"fill_color": colors[index] if index == 0 else None, "stroke_color": colors[index] if index > 0 else None, "data_index": scalar_index})
                            index += 1
                    if scalar_xdata and scalar_xdata.is_data_2d:
                        for row in range(min(scalar_xdata.data_shape[-1], max_layer_count)):
                            if index < max_layer_count:
                                display_layers.append({"fill_color": colors[index] if index == 0 else None, "stroke_color": colors[index] if index > 0 else None, "data_index": scalar_index, "data_row": row})
                                index += 1

            self.___has_valid_drawn_graph_data = False

            display_layer_count = len(self.__display_layers[0:max_layer_count])

            for index, display_layer in enumerate(self.__display_layers[0:max_layer_count]):
                fill_color = display_layer.get("fill_color")
                stroke_color = display_layer.get("stroke_color")
                stroke_width = display_layer.get("stroke_width")
                data_index = display_layer.get("data_index", 0)
                data_row = display_layer.get("data_row", 0)
                if 0 <= data_index < len(scalar_xdata_list):
                    scalar_xdata = scalar_xdata_list[data_index]
                    if scalar_xdata:
                        data_row = max(0, min(scalar_xdata.dimensional_shape[0] - 1, data_row))
                        intensity_calibration = scalar_xdata.intensity_calibration
                        displayed_dimensional_calibration = scalar_xdata.dimensional_calibrations[-1]
                        if scalar_xdata.is_data_2d:
                            scalar_data = scalar_xdata.data[data_row:data_row + 1, :].reshape((scalar_xdata.dimensional_shape[-1],))  # type: ignore
                            scalar_xdata = DataAndMetadata.new_data_and_metadata(scalar_data, intensity_calibration, [displayed_dimensional_calibration])
                    line_graph_canvas_item = typing.cast(LineGraphCanvasItem.LineGraphCanvasItem, self.__line_graph_stack.canvas_items[display_layer_count - (index + 1)])
                    line_graph_canvas_item.set_fill_color(fill_color)
                    line_graph_canvas_item.set_stroke_color(stroke_color)
                    line_graph_canvas_item.set_stroke_width(stroke_width)
                    line_graph_canvas_item.set_axes(axes)
                    line_graph_canvas_item.set_uncalibrated_xdata(scalar_xdata)
                    self.___has_valid_drawn_graph_data = scalar_xdata is not None

            # clear the remaining layers
            for index in range(len(display_layers), max_layer_count):
                line_graph_canvas_item = typing.cast(LineGraphCanvasItem.LineGraphCanvasItem, self.__line_graph_stack.canvas_items[index])
                line_graph_canvas_item.set_axes(None)
                line_graph_canvas_item.set_uncalibrated_xdata(None)

            legend_position = self.__legend_position
            legend_entries = list()
            for index, display_layer in enumerate(self.__display_layers[0:max_layer_count]):
                data_index = display_layer.get("data_index", None)
                data_row = display_layer.get("data_row", None)
                label = display_layer.get("label", str())
                if not label:
                    if data_index is not None and data_row is not None:
                        label = "Data {}:{}".format(data_index, data_row)
                    elif data_index is not None:
                        label = "Data {}".format(data_index)
                    else:
                        label = "Unknown"
                fill_color = display_layer.get("fill_color")
                stroke_color = display_layer.get("stroke_color")
                legend_entries.append(LineGraphCanvasItem.LegendEntry(label, fill_color, stroke_color))

            self.__update_canvas_items(axes, legend_entries)
        else:
            for line_graph_canvas_item in typing.cast(typing.Sequence[LineGraphCanvasItem.LineGraphCanvasItem], self.__line_graph_stack.canvas_items):
                line_graph_canvas_item.set_axes(None)
                line_graph_canvas_item.set_uncalibrated_xdata(None)
            self.__update_canvas_items(None, list())

    def _prepare_render(self) -> None:
        # this is called before layout and repainting. it gives this display item a chance
        # to update anything required for layout and trigger a layout before a repaint if
        # anything has changed.
        self.prepare_display()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        super()._repaint(drawing_context)

        if self.__display_frame_rate_id:
            Utility.fps_tick("display_"+self.__display_frame_rate_id)

        if self.__display_frame_rate_id:
            fps = Utility.fps_get("display_"+self.__display_frame_rate_id)
            fps2 = Utility.fps_get("frame_"+self.__display_frame_rate_id)
            fps3 = Utility.fps_get("update_"+self.__display_frame_rate_id)
            fps4 = Utility.fps_get("prepare_"+self.__display_frame_rate_id)

            rect = self.canvas_bounds
            if rect:
                with drawing_context.saver():
                    font = "normal 11px serif"
                    text_pos = Geometry.IntPoint(y=rect.top, x=rect.right - 100)
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

    def __update_canvas_items(self, axes: typing.Optional[LineGraphCanvasItem.LineGraphAxes], legend_entries: typing.Sequence[LineGraphCanvasItem.LegendEntry]) -> None:
        self.__line_graph_background_canvas_item.set_axes(axes)
        self.__line_graph_regions_canvas_item.set_axes(axes)
        self.__line_graph_regions_canvas_item.set_calibrated_data(self.line_graph_canvas_item.calibrated_xdata.data if self.line_graph_canvas_item and self.line_graph_canvas_item.calibrated_xdata else None)
        self.__line_graph_frame_canvas_item.set_draw_frame(bool(axes))
        self.__line_graph_legend_canvas_item.set_legend_entries(legend_entries)
        self.__line_graph_outer_left_legend.set_legend_entries(legend_entries)
        self.__line_graph_outer_right_legend.set_legend_entries(legend_entries)
        self.__update_legend_origin()
        self.__line_graph_vertical_axis_label_canvas_item.set_axes(axes)
        self.__line_graph_vertical_axis_scale_canvas_item.set_axes(axes, self.__ui_settings)
        self.__line_graph_vertical_axis_ticks_canvas_item.set_axes(axes)
        self.__line_graph_horizontal_axis_label_canvas_item.set_axes(axes)
        self.__line_graph_horizontal_axis_scale_canvas_item.set_axes(axes)
        self.__line_graph_horizontal_axis_ticks_canvas_item.set_axes(axes)
        self.__axes = axes

    def mouse_entered(self) -> bool:
        if super().mouse_entered():
            return True
        self.__mouse_in = True
        return True

    def mouse_exited(self) -> bool:
        if super().mouse_exited():
            return True
        self.__mouse_in = False
        self.__update_cursor_info()
        if self.delegate:  # allow display to work without delegate
            # whenever the cursor exits, clear the cursor display
            self.delegate.cursor_changed(None)
        return True

    def mouse_double_clicked(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_clicked(x, y, modifiers):
            return True
        delegate = self.delegate
        if delegate and delegate.tool_mode == "pointer":
            pos = Geometry.IntPoint(x=x, y=y)
            h_axis_canvas_bounds = self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds
            v_axis_canvas_bounds = self.__line_graph_vertical_axis_group_canvas_item.canvas_bounds
            if h_axis_canvas_bounds and h_axis_canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_horizontal_axis_group_canvas_item)):
                command = delegate.create_change_display_command()
                delegate.update_display_properties({"left_channel": None, "right_channel": None})
                delegate.push_undo_command(command)
                return True
            elif v_axis_canvas_bounds and v_axis_canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.__line_graph_vertical_axis_group_canvas_item)):
                command = delegate.create_change_display_command()
                delegate.update_display_properties({"y_min": None, "y_max": None})
                delegate.push_undo_command(command)
                return True
        return False

    def mouse_position_changed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_position_changed(x, y, modifiers):
            return True
        delegate = self.delegate
        if delegate and delegate.tool_mode == "pointer" and not self.__graphic_drag_items:
            if self.__axes:
                pos = Geometry.IntPoint(x=x, y=y)
                h_axis_canvas_bounds = self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds
                v_axis_canvas_bounds = self.__line_graph_vertical_axis_group_canvas_item.canvas_bounds
                if h_axis_canvas_bounds and h_axis_canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_horizontal_axis_group_canvas_item)):
                    if modifiers.control:
                        self.cursor_shape = "split_horizontal"
                    else:
                        self.cursor_shape = "hand"
                elif v_axis_canvas_bounds and v_axis_canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.__line_graph_vertical_axis_group_canvas_item)):
                    if modifiers.control:
                        self.cursor_shape = "split_vertical"
                    else:
                        self.cursor_shape = "hand"
                elif self.__graphics:
                    graphics = self.__graphics
                    for graphic_index, graphic in enumerate(graphics):
                        if isinstance(graphic, (Graphics.IntervalGraphic, Graphics.ChannelGraphic)):
                            widget_mapping = self.__get_mouse_mapping()
                            part, specific = graphic.test(widget_mapping, self.__ui_settings, pos.to_float_point(), False)
                            if part in {"start", "end"} and not modifiers.control:
                                self.cursor_shape = "size_horizontal"
                                break
                            elif part:
                                self.cursor_shape = "hand"
                                break
                    else:
                        self.cursor_shape = "arrow"
                else:
                    self.cursor_shape = "arrow"
        elif delegate and delegate.tool_mode == "interval":
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

    def mouse_clicked(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_clicked(x, y, modifiers):
            return True
        delegate = self.delegate
        if delegate:
            return delegate.display_clicked(modifiers)
        return False

    def mouse_pressed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_pressed(x, y, modifiers):
            return True
        if not self.__axes:
            return False
        self.__undo_command = None
        pos = Geometry.IntPoint(x=x, y=y)
        delegate = self.delegate
        if delegate:
            delegate.begin_mouse_tracking()
            regions_canvas_bounds = self.__line_graph_regions_canvas_item.canvas_bounds
            if delegate.tool_mode == "pointer":
                h_axis_canvas_bounds = self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds
                v_axis_canvas_bounds = self.__line_graph_vertical_axis_group_canvas_item.canvas_bounds
                if regions_canvas_bounds and regions_canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.__line_graph_regions_canvas_item)):
                    self.begin_tracking_regions(pos, modifiers)
                    return True
                elif h_axis_canvas_bounds and h_axis_canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.line_graph_horizontal_axis_group_canvas_item)):
                    self.begin_tracking_horizontal(pos, rescale=modifiers.control)
                    return True
                elif v_axis_canvas_bounds and v_axis_canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.__line_graph_vertical_axis_group_canvas_item)):
                    self.begin_tracking_vertical(pos, rescale=modifiers.control)
                    return True
            if delegate.tool_mode == "interval":
                if regions_canvas_bounds and regions_canvas_bounds.contains_point(self.map_to_canvas_item(pos, self.__line_graph_regions_canvas_item)):
                    widget_mapping = self.__get_mouse_mapping()
                    channel_norm = widget_mapping.map_point_widget_to_channel_norm(pos.to_float_point())
                    region = Graphics.IntervalGraphic()
                    region.start = channel_norm
                    region.end = channel_norm
                    self.__undo_command = delegate.add_and_select_region(region)
                    self.begin_tracking_regions(pos, Graphics.NullModifiers())
                    return True
        return False

    def mouse_released(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_released(x, y, modifiers):
            return True
        if not self.__axes:
            return False
        self.end_tracking(modifiers)
        delegate = self.delegate
        if delegate:
            delegate.end_mouse_tracking(self.__undo_command)
        self.__undo_command = None
        return False

    def _mouse_dragged(self, start: float, end: float, modifiers: typing.Optional[UserInterface.KeyboardModifiers] = None) -> None:
        # for testing
        line_graph_canvas_item = self.line_graph_canvas_item
        if line_graph_canvas_item:
            canvas_rect = line_graph_canvas_item.canvas_rect
            if canvas_rect:
                plot_origin = line_graph_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
                plot_left = canvas_rect.left + plot_origin.x
                plot_width = canvas_rect.width
                modifiers = modifiers if modifiers else CanvasItem.KeyboardModifiers()
                self.mouse_pressed(plot_left + round(plot_width * start), 100, modifiers)
                self.mouse_position_changed(plot_left + round(plot_width * start), 100, modifiers)
                self.mouse_position_changed(plot_left + round(plot_width * (start + end) / 2), 100, modifiers)
                self.mouse_position_changed(plot_left + round(plot_width * end), 100, modifiers)
                self.mouse_released(plot_left + round(plot_width * end), 100, modifiers)

    def context_menu_event(self, x: int, y: int, gx: int, gy: int) -> bool:
        assert self.delegate
        return self.delegate.show_display_context_menu(gx, gy)

    @property
    def key_contexts(self) -> typing.Sequence[str]:
        key_contexts = ["display_panel"]
        key_contexts.append("line_plot_display")
        if self.__graphic_selection and self.__graphic_selection.has_selection:
            key_contexts.append("line_plot_display_graphics")
        return key_contexts

    # ths message comes from the widget
    def key_pressed(self, key: UserInterface.Key) -> bool:
        if super().key_pressed(key):
            return True
        # This will update the cursor shape when the user presses a modifier key.
        if self.__last_mouse:
            last_mouse = self.__last_mouse
            self.mouse_position_changed(last_mouse.x, last_mouse.y, key.modifiers)
        return False

    def toggle_frame_rate(self) -> None:
        if self.__display_frame_rate_id is None:
            self.__display_frame_rate_id = str(id(self))
        else:
            self.__display_frame_rate_id = None

    def key_released(self, key: UserInterface.Key) -> bool:
        if super().key_released(key):
            return True
        # This will update the cursor shape when the user releases a modifier key
        if self.__last_mouse:
            last_mouse = self.__last_mouse
            self.mouse_position_changed(last_mouse.x, last_mouse.y, key.modifiers)
        return True

    def __get_mouse_mapping(self) -> LinePlotCanvasItemMapping:
        data_scale = self.__data_scale
        plot_origin = self.__line_graph_regions_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
        canvas_bounds = self.__line_graph_regions_canvas_item.canvas_bounds
        assert canvas_bounds
        assert data_scale is not None
        plot_rect = canvas_bounds.translated(plot_origin)
        left_channel = self.__axes.drawn_left_channel if self.__axes else 0
        right_channel = self.__axes.drawn_right_channel if self.__axes else 0
        return LinePlotCanvasItemMapping(data_scale, plot_rect, left_channel, right_channel)

    @property
    def mouse_mapping(self) -> LinePlotCanvasItemMapping:
        return self.__get_mouse_mapping()

    def begin_tracking_regions(self, pos: Geometry.IntPoint, modifiers: Graphics.ModifiersLike) -> None:
        # keep track of general drag information
        self.__graphic_drag_start_pos = pos
        self.__graphic_drag_changed = False
        if self.__axes and self.__graphic_selection:
            self.__tracking_selections = True
            graphics = self.__graphics
            selection_indexes = self.__graphic_selection.indexes
            for graphic_index, graphic in enumerate(graphics):
                if isinstance(graphic, (Graphics.IntervalGraphic, Graphics.ChannelGraphic)):
                    already_selected = graphic_index in selection_indexes
                    multiple_items_selected = len(selection_indexes) > 1
                    move_only = not already_selected or multiple_items_selected
                    widget_mapping = self.__get_mouse_mapping()
                    part, specific = graphic.test(widget_mapping, self.__ui_settings, self.__graphic_drag_start_pos.to_float_point(), move_only)
                    if part:
                        # select item and prepare for drag
                        self.graphic_drag_item_was_selected = already_selected
                        delegate = self.delegate
                        if delegate and not self.graphic_drag_item_was_selected:
                            if modifiers.control:
                                delegate.add_index_to_selection(graphic_index)
                                selection_indexes.add(graphic_index)
                            else:
                                delegate.set_selection(graphic_index)
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

    def begin_tracking_horizontal(self, pos: Geometry.IntPoint, rescale: bool) -> None:
        plot_origin = self.line_graph_horizontal_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
        canvas_bounds = self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds
        if canvas_bounds and self.__axes:
            plot_rect = canvas_bounds.translated(plot_origin)
            self.__tracking_horizontal = True
            self.__tracking_rescale = rescale
            self.__tracking_start_pos = pos
            self.__tracking_start_left_channel = self.__axes.drawn_left_channel
            self.__tracking_start_right_channel = self.__axes.drawn_right_channel
            self.__tracking_start_drawn_channel_per_pixel = float(self.__tracking_start_right_channel - self.__tracking_start_left_channel) / plot_rect.width
            self.__tracking_start_origin_pixel = self.__tracking_start_pos.x - plot_rect.left
            self.__tracking_start_channel = self.__tracking_start_left_channel + self.__tracking_start_origin_pixel * self.__tracking_start_drawn_channel_per_pixel

    def begin_tracking_vertical(self, pos: Geometry.IntPoint, rescale: bool) -> None:
        graph_area_canvas_bounds = self.__line_graph_area_stack.canvas_bounds
        v_axis_canvas_bounds = self.__line_graph_vertical_axis_group_canvas_item.canvas_bounds
        if graph_area_canvas_bounds and v_axis_canvas_bounds and self.__axes:
            plot_height = graph_area_canvas_bounds.height - 1
            self.__tracking_vertical = True
            self.__tracking_rescale = rescale
            self.__tracking_start_pos = pos
            self.__tracking_start_calibrated_data_min = self.__axes.calibrated_data_min
            self.__tracking_start_calibrated_data_max = self.__axes.calibrated_data_max
            self.__tracking_start_calibrated_data_per_pixel = (self.__tracking_start_calibrated_data_max - self.__tracking_start_calibrated_data_min) / plot_height
            plot_origin = self.__line_graph_vertical_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
            plot_rect = v_axis_canvas_bounds.translated(plot_origin)
            if 0.0 >= self.__tracking_start_calibrated_data_min and 0.0 <= self.__tracking_start_calibrated_data_max and not self.__axes.data_style == "log":
                calibrated_unit_per_pixel = (self.__tracking_start_calibrated_data_max - self.__tracking_start_calibrated_data_min) / (plot_rect.height - 1) if plot_rect.height > 1 else 1.0
                calibrated_unit_per_pixel = calibrated_unit_per_pixel if calibrated_unit_per_pixel else 1.0  # handle case where calibrated_unit_per_pixel is zero
                origin_offset_pixels = (0.0 - self.__tracking_start_calibrated_data_min) / calibrated_unit_per_pixel
                calibrated_origin = self.__tracking_start_calibrated_data_min + origin_offset_pixels * self.__tracking_start_calibrated_data_per_pixel
                self.__tracking_start_origin_y = origin_offset_pixels
                self.__tracking_start_calibrated_origin = calibrated_origin
            else:
                self.__tracking_start_origin_y = 0  # the distance the origin is up from the bottom
                self.__tracking_start_calibrated_origin = self.__tracking_start_calibrated_data_min

    def continue_tracking(self, pos: Geometry.IntPoint, modifiers: UserInterface.KeyboardModifiers) -> bool:
        delegate = self.delegate
        if not delegate:
            return False
        if self.__tracking_selections:
            if self.__graphic_drag_item is None and not self.__graphic_drag_changed and self.__graphic_selection:
                widget_mapping = self.__get_mouse_mapping()
                x = widget_mapping.map_point_widget_to_channel_norm(self.__graphic_drag_start_pos.to_float_point())
                if not self.__pending_interval:
                    region: typing.Optional[Graphics.IntervalGraphic] = Graphics.IntervalGraphic()
                    assert region
                    region.start = x
                    region.end = x
                    self.__pending_interval = region
                    region = None
                elif abs(widget_mapping.map_point_channel_norm_to_widget(self.__pending_interval.start) - pos.x) > self.__ui_settings.cursor_tolerance:
                    region = self.__pending_interval
                    self.__pending_interval = None
                    region.end = widget_mapping.map_point_widget_to_channel_norm(pos.to_float_point())
                    self.__undo_command = delegate.add_and_select_region(region)
                else:
                    region = None
                selection_indexes = self.__graphic_selection.indexes
                for graphic_index, graphic in enumerate(self.__graphics):
                    if graphic == region:
                        part, specific = graphic.test(widget_mapping, self.__ui_settings, pos.to_float_point(), False)
                        if part:
                            self.graphic_drag_item_was_selected = False
                            delegate.set_selection(graphic_index)
                            selection_indexes.clear()
                            selection_indexes.add(graphic_index)
                            self.__graphic_drag_item = graphic
                            self.__graphic_drag_part = part
                            self.__graphic_drag_indexes = selection_indexes
                            self.__graphic_drag_items.append(graphic)
                            self.__graphic_part_data[graphic_index] = graphic.begin_drag()
            else:
                if not self.__undo_command:
                    self.__undo_command = delegate.create_change_graphics_command()
            # x,y already have transform applied
            self.__last_mouse = copy.copy(pos)
            self.__update_cursor_info()
            if self.__graphic_drag_items:
                widget_mapping = self.__get_mouse_mapping()
                delegate.adjust_graphics(widget_mapping, self.__graphic_drag_items, self.__graphic_drag_part,
                                         self.__graphic_part_data, self.__graphic_drag_start_pos.to_float_point(), pos.to_float_point(), modifiers)
                self.__graphic_drag_changed = True
                self.__line_graph_regions_canvas_item.update()
        elif self.__tracking_horizontal:
            if not self.__undo_command:
                self.__undo_command = delegate.create_change_display_command()
            h_axis_canvas_bounds = self.line_graph_horizontal_axis_group_canvas_item.canvas_bounds
            if h_axis_canvas_bounds and self.__tracking_rescale:
                plot_origin = self.line_graph_horizontal_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
                plot_rect = h_axis_canvas_bounds.translated(plot_origin)
                pixel_offset_x = pos.x - self.__tracking_start_pos.x
                scaling = math.pow(10, pixel_offset_x/96.0)  # 10x per inch of travel, assume 96dpi
                new_drawn_channel_per_pixel = self.__tracking_start_drawn_channel_per_pixel / scaling
                left_channel = int(round(self.__tracking_start_channel - new_drawn_channel_per_pixel * self.__tracking_start_origin_pixel))
                right_channel = int(round(self.__tracking_start_channel + new_drawn_channel_per_pixel * (plot_rect.width - self.__tracking_start_origin_pixel)))
                delegate.update_display_properties({"left_channel": left_channel, "right_channel": right_channel})
                return True
            else:
                delta = pos - self.__tracking_start_pos
                left_channel = int(self.__tracking_start_left_channel - self.__tracking_start_drawn_channel_per_pixel * delta.x)
                right_channel = int(self.__tracking_start_right_channel - self.__tracking_start_drawn_channel_per_pixel * delta.x)
                delegate.update_display_properties({"left_channel": left_channel, "right_channel": right_channel})
                return True
        elif self.__tracking_vertical:
            if not self.__undo_command:
                self.__undo_command = delegate.create_change_display_command()
            v_axis_canvas_bounds = self.__line_graph_vertical_axis_group_canvas_item.canvas_bounds
            axes = self.__axes
            if axes:
                if v_axis_canvas_bounds and self.__tracking_rescale:
                    plot_origin = self.__line_graph_vertical_axis_group_canvas_item.map_to_canvas_item(Geometry.IntPoint(), self)
                    plot_rect = v_axis_canvas_bounds.translated(plot_origin)
                    origin_y = plot_rect.bottom - 1 - self.__tracking_start_origin_y  # pixel position of y-origin
                    calibrated_offset = self.__tracking_start_calibrated_data_per_pixel * (origin_y - self.__tracking_start_pos.y)
                    pixel_offset = origin_y - pos.y
                    pixel_offset = max(pixel_offset, 1) if origin_y > self.__tracking_start_pos.y else min(pixel_offset, -1)
                    new_calibrated_data_per_pixel = calibrated_offset / pixel_offset
                    calibrated_data_min = self.__tracking_start_calibrated_origin - new_calibrated_data_per_pixel * self.__tracking_start_origin_y
                    calibrated_data_max = self.__tracking_start_calibrated_origin + new_calibrated_data_per_pixel * (plot_rect.height - 1 - self.__tracking_start_origin_y)
                    uncalibrated_data_min = axes.uncalibrate_y(calibrated_data_min)
                    uncalibrated_data_max = axes.uncalibrate_y(calibrated_data_max)
                    delegate.update_display_properties({"y_min": uncalibrated_data_min, "y_max": uncalibrated_data_max})
                    return True
                else:
                    delta = pos - self.__tracking_start_pos
                    calibrated_data_min = self.__tracking_start_calibrated_data_min + self.__tracking_start_calibrated_data_per_pixel * delta.y
                    calibrated_data_max = self.__tracking_start_calibrated_data_max + self.__tracking_start_calibrated_data_per_pixel * delta.y
                    uncalibrated_data_min = axes.uncalibrate_y(calibrated_data_min)
                    uncalibrated_data_max = axes.uncalibrate_y(calibrated_data_max)
                    delegate.update_display_properties({"y_min": uncalibrated_data_min, "y_max": uncalibrated_data_max})
                    return True
        return False

    def end_tracking(self, modifiers: UserInterface.KeyboardModifiers) -> None:
        delegate = self.delegate
        if not delegate:
            return
        if not self.__graphic_drag_items and not modifiers.control:
            delegate.clear_selection()
        if self.__tracking_selections and self.__graphic_drag_item:
            graphics = self.__graphics
            if self.__axes and graphics is not None:
                for index in self.__graphic_drag_indexes:
                    graphic = graphics[index]
                    graphic.end_drag(self.__graphic_part_data[index])
                if self.__graphic_drag_items and not self.__graphic_drag_changed:
                    graphic_index = graphics.index(self.__graphic_drag_item)
                    # user didn't move graphic
                    if not modifiers.control:
                        # user clicked on a single graphic
                        delegate.set_selection(graphic_index)
                    else:
                        # user control clicked. toggle selection
                        # if control is down and item is already selected, toggle selection of item
                        if self.graphic_drag_item_was_selected:
                            delegate.remove_index_from_selection(graphic_index)
                        else:
                            delegate.add_index_to_selection(graphic_index)
            self.__graphic_drag_items = list()
            self.__graphic_drag_item = None
            self.__graphic_part_data = dict()
            self.__graphic_drag_indexes = set()
        delegate.tool_mode = "pointer"
        self.__tracking_horizontal = False
        self.__tracking_vertical = False
        self.__tracking_selections = False
        self.__pending_interval = None
        self.prepare_display()

    def __update_cursor_info(self) -> None:
        """ Map the mouse to the 1-d position within the line graph. """

        if not self.delegate:  # allow display to work without delegate
            return

        if self.__mouse_in and self.__last_mouse:
            pos_1d = None
            axes = self.__axes
            line_graph_canvas_item = self.line_graph_canvas_item
            if axes and line_graph_canvas_item:
                mouse = self.map_to_canvas_item(self.__last_mouse, line_graph_canvas_item)
                canvas_bounds = line_graph_canvas_item.canvas_bounds
                if canvas_bounds and canvas_bounds.contains_point(mouse):
                    mouse = mouse - canvas_bounds.origin
                    x = float(mouse.x) / canvas_bounds.width
                    px = axes.drawn_left_channel + round(x * (axes.drawn_right_channel - axes.drawn_left_channel))
                    pos_1d = px,
            self.delegate.cursor_changed(pos_1d)

    def get_drop_regions_map(self, display_item: DisplayItem.DisplayItem) -> typing.Optional[typing.Mapping[str, typing.Tuple[Geometry.IntRect, Geometry.IntRect]]]:
        # partial logic overlap in if chain with display_item.used_display_type
        if self.__line_graph_area_stack.canvas_rect and display_item and display_item.display_data_channel and display_item.display_data_channel.is_display_1d_preferred:
            canvas_rect = self.__line_graph_area_stack.canvas_rect
            hit_rect = Geometry.IntRect.from_center_and_size(canvas_rect.center, Geometry.IntSize(height=canvas_rect.height // 2, width=canvas_rect.width // 2))
            return {"plus": (hit_rect, self.__line_graph_area_stack.canvas_rect)}
        return None

    def wants_drag_event(self, mime_data: UserInterface.MimeData, x: int, y: int) -> bool:
        return mime_data.has_format(MimeTypes.LAYER_MIME_TYPE)

    def drop(self, mime_data: UserInterface.MimeData, x: int, y: int) -> str:
        if not mime_data.has_format(MimeTypes.LAYER_MIME_TYPE) or not self.delegate:
            return "ignore"

        legend_data, source_display_item = MimeTypes.mime_data_get_layer(mime_data, self.delegate.get_document_model())

        if source_display_item:
            from_index = legend_data["index"]
            # if we aren't the source item, move the display layer between display items
            command = self.delegate.create_move_display_layer_command(source_display_item, from_index, len(self.__display_layers))
            # TODO: perform only if the display channel doesn't exist in the target
            command.perform()
            self.delegate.push_undo_command(command)

        return "ignore"
