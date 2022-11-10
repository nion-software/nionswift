from __future__ import annotations

# standard libraries
import asyncio
import copy
import logging
import math
import threading
import typing

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import DisplayCanvasItem
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import UISettings
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.utils import Geometry
from nion.utils import Registry
from nion.utils import Stream

if typing.TYPE_CHECKING:
    from nion.swift import Undo
    from nion.swift.model import Persistence
    from nion.ui import DrawingContext
    from nion.ui import UserInterface



def _is_valid_data_shape(data_shape: typing.Optional[DataAndMetadata.ShapeType], canvas_rect: typing.Optional[Geometry.IntRect]) -> bool:
    if not data_shape or len(data_shape) != 2:
        return False
    for d in data_shape:
        if not d > 0:
            return False
    return canvas_rect is not None


class ImageCanvasItemMapping(Graphics.CoordinateMappingLike):

    def __init__(self, data_shape: DataAndMetadata.Shape2dType, canvas_rect: Geometry.IntRect, calibrations: typing.Sequence[Calibration.Calibration]) -> None:
        assert _is_valid_data_shape(data_shape, canvas_rect)
        self.__data_shape = Geometry.IntSize(data_shape[0], data_shape[1])
        self.canvas_rect = Geometry.fit_to_size(canvas_rect, self.__data_shape)
        self.calibrations = calibrations

    @classmethod
    def make(cls, data_shape: typing.Optional[DataAndMetadata.ShapeType], canvas_rect: typing.Optional[Geometry.IntRect], calibrations: typing.Sequence[Calibration.Calibration]) -> typing.Optional[ImageCanvasItemMapping]:
        if _is_valid_data_shape(data_shape, canvas_rect):
            return cls(typing.cast(DataAndMetadata.Shape2dType, data_shape), typing.cast(Geometry.IntRect, canvas_rect), calibrations)
        return None

    @property
    def data_shape(self) -> DataAndMetadata.Shape2dType:
        return self.__data_shape.as_tuple()

    def map_point_image_norm_to_widget(self, p: Geometry.FloatPoint) -> Geometry.FloatPoint:
        canvas_rect = self.canvas_rect
        return Geometry.FloatPoint(y=p.y * canvas_rect.height + canvas_rect.top, x=p.x * canvas_rect.width + canvas_rect.left)

    def map_size_image_norm_to_widget(self, s: Geometry.FloatSize) -> Geometry.FloatSize:
        ms = self.map_point_image_norm_to_widget(s.as_point())
        ms0 = self.map_point_image_norm_to_widget(Geometry.FloatPoint())
        return (ms - ms0).as_size()

    def map_size_image_to_image_norm(self, s: Geometry.FloatSize) -> Geometry.FloatSize:
        ms = self.map_point_image_to_image_norm(s.as_point())
        ms0 = self.map_point_image_to_image_norm(Geometry.FloatPoint())
        return (ms - ms0).as_size()

    def map_size_image_to_widget(self, s: Geometry.FloatSize) -> Geometry.FloatSize:
        ms = self.map_point_image_to_widget(s.as_point())
        ms0 = self.map_point_image_to_widget(Geometry.FloatPoint())
        return (ms - ms0).as_size()

    def map_size_widget_to_image_norm(self, s: Geometry.FloatSize) -> Geometry.FloatSize:
        ms = self.map_point_widget_to_image_norm(s.as_point())
        ms0 = self.map_point_widget_to_image_norm(Geometry.FloatPoint())
        return (ms - ms0).as_size()

    def map_point_widget_to_image_norm(self, p: Geometry.FloatPoint) -> Geometry.FloatPoint:
        p_image = self.map_point_widget_to_image(p)
        return Geometry.FloatPoint(y=p_image.y / self.__data_shape.height, x=p_image.x / self.__data_shape.width)

    def map_point_widget_to_image(self, p: Geometry.FloatPoint) -> Geometry.FloatPoint:
        canvas_rect = self.canvas_rect
        data_shape = self.__data_shape
        if canvas_rect.height != 0.0:
            image_y = data_shape.height * (p.y - canvas_rect.top) / canvas_rect.height
        else:
            image_y = 0.0
        if canvas_rect.width != 0.0:
            image_x = data_shape.width * (p.x - canvas_rect.left) / canvas_rect.width
        else:
            image_x = 0.0
        return Geometry.FloatPoint(y=image_y, x=image_x)  # c-indexing

    def map_point_image_norm_to_image(self, p: Geometry.FloatPoint) -> Geometry.FloatPoint:
        data_shape = self.__data_shape
        return Geometry.FloatPoint(y=p.y * data_shape.height, x=p.x * data_shape.width)

    def map_point_image_to_image_norm(self, p: Geometry.FloatPoint) -> Geometry.FloatPoint:
        data_shape = self.__data_shape
        return Geometry.FloatPoint(y=p.y / data_shape.height, x=p.x / data_shape.width)

    def map_point_image_to_widget(self, p: Geometry.FloatPoint) -> Geometry.FloatPoint:
        canvas_rect = self.canvas_rect
        data_shape = self.__data_shape
        return Geometry.FloatPoint(
            y=p.y * canvas_rect.height / data_shape.height + canvas_rect.top,
            x=p.x * canvas_rect.width / data_shape.width + canvas_rect.left
        )

    @property
    def calibrated_origin_image(self) -> Geometry.FloatPoint:
        if self.calibrations:
            return Geometry.FloatPoint(
                self.calibrations[0].convert_from_calibrated_value(0.0),
                self.calibrations[1].convert_from_calibrated_value(0.0)
            )
        return Geometry.FloatPoint()

    @property
    def calibrated_origin_image_norm(self) -> Geometry.FloatPoint:
        return self.map_point_image_to_image_norm(self.calibrated_origin_image)

    @property
    def calibrated_origin_widget(self) -> Geometry.FloatPoint:
        return self.map_point_image_to_widget(self.calibrated_origin_image)

    def map_point_channel_norm_to_channel(self, x: float) -> float:
        raise NotImplementedError()

    def map_point_channel_norm_to_widget(self, x: float) -> float:
        raise NotImplementedError()

    def map_point_widget_to_channel_norm(self, pos: Geometry.FloatPoint) -> float:
        raise NotImplementedError()


class GraphicsCanvasItem(CanvasItem.AbstractCanvasItem):
    """A canvas item to paint the graphic items on the image.

    Callers should call update_graphics when the graphics changes.
    """

    def __init__(self, ui_settings: UISettings.UISettings) -> None:
        super().__init__()
        self.__ui_settings = ui_settings
        self.__displayed_shape: typing.Optional[DataAndMetadata.ShapeType] = None
        self.__graphics: typing.List[Graphics.Graphic] = list()
        self.__graphics_for_compare: typing.List[Persistence.PersistentDictType] = list()
        self.__graphic_selection = DisplayItem.GraphicSelection()
        self.__coordinate_system: typing.List[Calibration.Calibration] = list()

    def update_coordinate_system(self, displayed_shape: typing.Optional[DataAndMetadata.ShapeType], coordinate_system: typing.Sequence[Calibration.Calibration], graphics: typing.Sequence[Graphics.Graphic], graphic_selection: DisplayItem.GraphicSelection) -> None:
        self.__coordinate_system = list(coordinate_system)
        if displayed_shape is None or len(displayed_shape) != 2:
            displayed_shape = None
            graphics = list()
            graphic_selection = DisplayItem.GraphicSelection()
        assert displayed_shape is None or len(displayed_shape) == 2
        needs_update = False
        if ((self.__displayed_shape is None) != (displayed_shape is None)) or (self.__displayed_shape != displayed_shape):
            self.__displayed_shape = displayed_shape
            needs_update = True
        graphics_for_compare = [graphic.write_to_dict() for graphic in graphics]
        if graphics_for_compare != self.__graphics_for_compare:
            self.__graphics = list(graphics)
            self.__graphics_for_compare = graphics_for_compare
            needs_update = True
        if self.__graphic_selection != graphic_selection:
            self.__graphic_selection = graphic_selection
            needs_update = True
        if needs_update:
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        widget_mapping = ImageCanvasItemMapping.make(self.__displayed_shape, self.canvas_bounds, self.__coordinate_system)
        if self.__graphics and widget_mapping:
            with drawing_context.saver():
                for graphic_index, graphic in enumerate(self.__graphics):
                    if isinstance(graphic, (Graphics.PointTypeGraphic, Graphics.LineTypeGraphic, Graphics.RectangleTypeGraphic, Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
                        try:
                            graphic.draw(drawing_context, self.__ui_settings, widget_mapping, self.__graphic_selection.contains(graphic_index))
                        except Exception as e:
                            import traceback
                            logging.debug("Graphic Repaint Error: %s", e)
                            traceback.print_exc()
                            traceback.print_stack()


class ScaleMarkerCanvasItem(CanvasItem.AbstractCanvasItem):
    """A canvas item to paint the scale marker as an overlay.

    Callers should set the image_canvas_origin and image_canvas_size properties.

    Callers should also call set_data_info when the data changes.
    """
    scale_marker_width = 120
    scale_marker_height = 6
    scale_marker_font = "normal 14px serif"

    def __init__(self, screen_pixel_per_image_pixel_stream: Stream.ValueStream[float], get_font_metrics_fn: typing.Callable[[str, str], UISettings.FontMetrics]) -> None:
        super().__init__()
        self.__get_font_metrics_fn = get_font_metrics_fn
        self.__dimensional_calibration: typing.Optional[Calibration.Calibration] = None
        self.__info_text = str()
        self.__screen_pixel_per_image_pixel_stream = screen_pixel_per_image_pixel_stream.add_ref()
        self.__screen_pixel_per_image_pixel_action = Stream.ValueStreamAction(screen_pixel_per_image_pixel_stream, lambda x: self.__update_sizing())

    def close(self) -> None:
        self.__screen_pixel_per_image_pixel_stream.remove_ref()
        self.__screen_pixel_per_image_pixel_stream = typing.cast(typing.Any, None)
        self.__screen_pixel_per_image_pixel_action.close()
        self.__screen_pixel_per_image_pixel_action = typing.cast(typing.Any, None)
        super().close()

    @property
    def _dimension_calibration_for_test(self) -> typing.Optional[Calibration.Calibration]:
        return self.__dimensional_calibration

    def __update_sizing(self) -> None:
        height = self.scale_marker_height
        width = 20
        dimensional_calibration = self.__dimensional_calibration
        if dimensional_calibration is not None:  # display scale marker?
            screen_pixel_per_image_pixel = self.__screen_pixel_per_image_pixel_stream.value
            dimensional_scale = dimensional_calibration.scale
            if screen_pixel_per_image_pixel and screen_pixel_per_image_pixel > 0.0 and not math.isnan(dimensional_scale):
                scale_marker_image_width = self.scale_marker_width / screen_pixel_per_image_pixel
                calibrated_scale_marker_width = Geometry.make_pretty2(scale_marker_image_width * dimensional_scale, True)
                # update the scale marker width
                scale_marker_image_width = calibrated_scale_marker_width / dimensional_scale
                scale_marker_width = round(scale_marker_image_width * screen_pixel_per_image_pixel)
                text1 = dimensional_calibration.convert_to_calibrated_size_str(scale_marker_image_width)
                text2 = self.__info_text
                fm1 = self.__get_font_metrics_fn(self.scale_marker_font, text1)
                fm2 = self.__get_font_metrics_fn(self.scale_marker_font, text2)
                height = height + 4 + fm1.height + fm2.height
                width = 20 + max(scale_marker_width, fm1.width, fm2.width)
        new_sizing = self.copy_sizing()
        new_sizing._set_fixed_width(width)
        new_sizing._set_fixed_height(height)
        self.update_sizing(new_sizing)

    def set_data_info(self, dimensional_calibration: Calibration.Calibration, info_items: typing.Sequence[str]) -> None:
        needs_update = False
        if self.__dimensional_calibration is None or dimensional_calibration != self.__dimensional_calibration:
            self.__dimensional_calibration = dimensional_calibration
            needs_update = True
        info_text = " ".join(info_items)
        if self.__info_text is None or self.__info_text != info_text:
            self.__info_text = info_text
            needs_update = True
        if needs_update:
            self.__update_sizing()
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        canvas_size = self.canvas_size
        dimensional_calibration = self.__dimensional_calibration
        if canvas_size and dimensional_calibration:  # display scale marker?
            screen_pixel_per_image_pixel = self.__screen_pixel_per_image_pixel_stream.value
            if screen_pixel_per_image_pixel and screen_pixel_per_image_pixel > 0.0:
                scale_marker_image_width = self.scale_marker_width / screen_pixel_per_image_pixel
                calibrated_scale_marker_width = Geometry.make_pretty2(scale_marker_image_width * dimensional_calibration.scale, True)
                # update the scale marker width
                scale_marker_image_width = calibrated_scale_marker_width / dimensional_calibration.scale
                scale_marker_width = scale_marker_image_width * screen_pixel_per_image_pixel
                baseline = canvas_size.height
                with drawing_context.saver():
                    drawing_context.begin_path()
                    drawing_context.move_to(0, baseline)
                    drawing_context.line_to(0 + scale_marker_width, baseline)
                    drawing_context.line_to(0 + scale_marker_width, baseline - self.scale_marker_height)
                    drawing_context.line_to(0, baseline - self.scale_marker_height)
                    drawing_context.close_path()
                    drawing_context.fill_style = "#448"
                    drawing_context.fill()
                    drawing_context.stroke_style = "#000"
                    drawing_context.stroke()
                    drawing_context.font = self.scale_marker_font
                    drawing_context.text_baseline = "bottom"
                    drawing_context.fill_style = "#FFF"
                    text1 = dimensional_calibration.convert_to_calibrated_size_str(scale_marker_image_width)
                    text2 = self.__info_text
                    fm1 = self.__get_font_metrics_fn(self.scale_marker_font, text1)
                    drawing_context.fill_text(text1, 0, baseline - self.scale_marker_height - 4)
                    drawing_context.fill_text(text2, 0, baseline - self.scale_marker_height - 4 - fm1.height)


def calculate_origin_and_size(canvas_size: Geometry.IntSize, data_shape: DataAndMetadata.Shape2dType, image_canvas_mode: str, image_zoom: float, image_position: Geometry.FloatPoint) -> Geometry.IntRect:
    """Calculate origin and size for canvas size, data shape, and image display parameters."""
    if image_canvas_mode == "fill":
        data_shape = data_shape
        scale_h = float(data_shape[1]) / canvas_size.width
        scale_v = float(data_shape[0]) / canvas_size.height
        if scale_v < scale_h:
            image_canvas_size = Geometry.IntSize(canvas_size[0], round(canvas_size.height * data_shape[1] / data_shape[0]))
        else:
            image_canvas_size = Geometry.IntSize(round(canvas_size.width * data_shape[0] / data_shape[1]), canvas_size.width)
        image_canvas_origin = Geometry.IntPoint(round(canvas_size.height * 0.5 - image_canvas_size.height * 0.5),
                                                round(canvas_size.width * 0.5 - image_canvas_size.width * 0.5))
        return Geometry.IntRect(image_canvas_origin, image_canvas_size)
    elif image_canvas_mode == "fit":
        return Geometry.IntRect(Geometry.IntPoint(), canvas_size)
    elif image_canvas_mode == "1:1":
        image_canvas_origin = Geometry.IntPoint(round(canvas_size.height * 0.5 - data_shape[0] * 0.5), round(canvas_size.width * 0.5 - data_shape[1] * 0.5))
        return Geometry.IntRect(image_canvas_origin, Geometry.IntSize.make(data_shape))
    elif image_canvas_mode == "2:1":
        image_canvas_size = Geometry.IntSize(round(data_shape[0] * 0.5), round(data_shape[1] * 0.5))
        image_canvas_origin = Geometry.IntPoint(round(canvas_size.height * 0.5 - data_shape[0] * 0.25),
                                                round(canvas_size.width * 0.5 - data_shape[1] * 0.25))
        return Geometry.IntRect(image_canvas_origin, image_canvas_size)
    else:
        image_canvas_size_f = Geometry.FloatSize(canvas_size.height * image_zoom, canvas_size.width * image_zoom)
        canvas_rect_f = Geometry.fit_to_size(Geometry.FloatRect(Geometry.FloatPoint(), image_canvas_size_f), data_shape)
        image_canvas_origin_y = (canvas_size.height * 0.5) - image_position.y * canvas_rect_f.height - canvas_rect_f.top
        image_canvas_origin_x = (canvas_size.width * 0.5) - image_position.x * canvas_rect_f.width - canvas_rect_f.left
        image_canvas_origin_f = Geometry.FloatPoint(image_canvas_origin_y, image_canvas_origin_x)
        return Geometry.FloatRect(image_canvas_origin_f, image_canvas_size_f).to_int_rect()


class ImageCanvasItem(DisplayCanvasItem.DisplayCanvasItem):
    """A canvas item to paint an image.

    Callers are expected to pass in a delegate.

    They are expected to call the following functions to update the display:
        update_image_display_state
        update_graphics

    The delegate is expected to handle the following events:
        add_index_to_selection(index)
        remove_index_from_selection(index)
        set_selection(index)
        clear_selection()
        nudge_selected_graphics(mapping, delta)
        adjust_graphics(widget_mapping, graphic_drag_items, graphic_drag_part, graphic_part_data, graphic_drag_start_pos, pos, modifiers)
        tool_mode (property)
        show_display_context_menu(gx, gy)
        begin_mouse_tracking(self)
        end_mouse_tracking()
        mouse_clicked(image_position, modifiers)
        delete_key_pressed()
        enter_key_pressed()
        cursor_changed(pos)
    """

    def __init__(self, ui_settings: UISettings.UISettings,
                 delegate: typing.Optional[DisplayCanvasItem.DisplayCanvasItemDelegate],
                 event_loop: typing.Optional[asyncio.AbstractEventLoop], draw_background: bool = True) -> None:
        super().__init__()

        self.__ui_settings = ui_settings
        self.delegate = delegate
        self.__event_loop = event_loop

        self.wants_mouse_events = True

        self.__update_layout_handle: typing.Optional[asyncio.Handle] = None
        self.__update_layout_handle_lock = threading.RLock()

        self.__closing_lock = threading.RLock()
        self.__closed = False

        self.__image_zoom = 1.0
        self.__image_position = Geometry.FloatPoint(0.5, 0.5)
        self.__image_canvas_mode = "fit"

        self.__last_display_calibration_info: typing.Optional[DisplayItem.DisplayCalibrationInfo] = None
        self.__last_display_properties: typing.Optional[Persistence.PersistentDictType] = None

        # create the child canvas items
        # the background
        # next the zoom-able items
        self.__bitmap_canvas_item = CanvasItem.BitmapCanvasItem(background_color="#888" if draw_background else "transparent")
        self.__graphics_canvas_item = GraphicsCanvasItem(ui_settings)
        # put the zoom-able items into a composition
        self.__composite_canvas_item = CanvasItem.CanvasItemComposition()
        self.__composite_canvas_item.add_canvas_item(self.__bitmap_canvas_item)
        self.__composite_canvas_item.add_canvas_item(self.__graphics_canvas_item)
        # and put the composition into a scroll area
        self.scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(self.__composite_canvas_item)
        self.scroll_area_canvas_item._constrain_position = False  # temporary until scroll bars are implemented

        def layout_updated(canvas_origin: typing.Optional[Geometry.IntPoint], canvas_size: typing.Optional[Geometry.IntSize], immediate: bool = False) -> None:
            # when the scroll area layout is updated, also update the overlay items since they have no way to
            # be sized otherwise. will be called on render thread.
            if canvas_size:
                self.__update_overlay_canvas_item(canvas_size, immediate=immediate)

        self.scroll_area_canvas_item.on_layout_updated = layout_updated
        # info overlay (scale marker, etc.)
        self.__screen_pixel_per_image_pixel_stream_lock = threading.RLock()
        self.__screen_pixel_per_image_pixel_stream = Stream.ValueStream(0.0).add_ref()
        self.__scale_marker_canvas_item = ScaleMarkerCanvasItem(self.__screen_pixel_per_image_pixel_stream, ui_settings.get_font_metrics)
        info_overlay_row = CanvasItem.CanvasItemComposition()
        info_overlay_row.layout = CanvasItem.CanvasItemRowLayout()
        info_overlay_row.add_spacing(12)
        info_overlay_row.add_canvas_item(self.__scale_marker_canvas_item)
        info_overlay_row.add_stretch()
        self.__timestamp_canvas_item = CanvasItem.TimestampCanvasItem()
        self.__overlay_canvas_item = CanvasItem.CanvasItemComposition()
        self.__overlay_canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        self.__overlay_canvas_item.add_stretch()
        self.__overlay_canvas_item.add_canvas_item(info_overlay_row)
        self.__overlay_canvas_item.add_spacing(8)
        # canvas items get added back to front
        if draw_background:
            self.add_canvas_item(CanvasItem.BackgroundCanvasItem())
        self.add_canvas_item(self.scroll_area_canvas_item)
        self.add_canvas_item(self.__overlay_canvas_item)
        self.add_canvas_item(self.__timestamp_canvas_item)

        self.__display_values_dirty = False
        self.__display_values: typing.Optional[DisplayItem.DisplayValues] = None
        self.__data_shape: typing.Optional[DataAndMetadata.Shape2dType] = None
        self.__coordinate_system: typing.List[Calibration.Calibration] = list()
        self.__graphics: typing.List[Graphics.Graphic] = list()
        self.__graphic_selection: DisplayItem.GraphicSelection = DisplayItem.GraphicSelection()

        # used for tracking undo
        self.__undo_command: typing.Optional[Undo.UndoableCommand] = None

        # used for dragging graphic items
        self.__graphic_drag_items: typing.List[Graphics.Graphic] = list()
        self.__graphic_drag_item: typing.Optional[Graphics.Graphic] = None
        self.__graphic_part_data: typing.Dict[int, Graphics.DragPartData] = dict()
        self.__graphic_drag_indexes: typing.Set[int] = set()
        self.__last_drag_pos: typing.Optional[Geometry.FloatPoint] = None
        self.__last_mouse: typing.Optional[Geometry.IntPoint] = None
        self.__is_dragging = False
        self.__mouse_in = False

        # frame rate and latency
        self.__display_frame_rate_id: typing.Optional[str] = None
        self.__display_frame_rate_last_index = 0
        self.__display_latency = False

    def close(self) -> None:
        self.__screen_pixel_per_image_pixel_stream.remove_ref()
        self.__screen_pixel_per_image_pixel_stream = typing.cast(typing.Any, None)
        if self.__undo_command:
            self.__undo_command.close()
            self.__undo_command = None
        with self.__closing_lock:
            with self.__update_layout_handle_lock:
                update_layout_handle = self.__update_layout_handle
                if update_layout_handle:
                    update_layout_handle.cancel()
                    self.__update_layout_handle = None
            self.__closed = True
        self.__display_values = None
        super().close()

    @property
    def default_aspect_ratio(self) -> float:
        return 1.0

    @property
    def _scale_marker_canvas_item_for_test(self) -> ScaleMarkerCanvasItem:
        return self.__scale_marker_canvas_item

    def add_display_control(self, display_control_canvas_item: CanvasItem.AbstractCanvasItem, role: typing.Optional[str] = None) -> None:
        self.__overlay_canvas_item.add_canvas_item(display_control_canvas_item)

    def update_display_values(self, display_values_list: typing.Sequence[typing.Optional[DisplayItem.DisplayValues]]) -> None:
        self.__display_values = display_values_list[0] if display_values_list else None
        self.__display_values_dirty = True

    def update_display_properties_and_layers(self, display_calibration_info: DisplayItem.DisplayCalibrationInfo, display_properties: Persistence.PersistentDictType, display_layers: typing.Sequence[Persistence.PersistentDictType]) -> None:
        # threadsafe
        data_and_metadata = self.__display_values.data_and_metadata if self.__display_values else None
        if data_and_metadata:
            displayed_dimensional_calibrations = display_calibration_info.displayed_dimensional_calibrations
            if len(displayed_dimensional_calibrations) == 0:
                dimensional_calibration = Calibration.Calibration()
            elif len(displayed_dimensional_calibrations) == 1:
                dimensional_calibration = displayed_dimensional_calibrations[0]
            else:
                if data_and_metadata:
                    datum_dimensions = data_and_metadata.datum_dimension_indexes
                    collection_dimensions = data_and_metadata.collection_dimension_indexes
                    if len(datum_dimensions) == 2:
                        dimensional_calibration = data_and_metadata.dimensional_calibrations[datum_dimensions[-1]]
                    elif len(collection_dimensions) > 0:
                        dimensional_calibration = data_and_metadata.dimensional_calibrations[collection_dimensions[-1]]
                    elif len(datum_dimensions) > 0:
                        dimensional_calibration = data_and_metadata.dimensional_calibrations[datum_dimensions[-1]]
                    else:
                        dimensional_calibration = Calibration.Calibration()
                else:
                    dimensional_calibration = Calibration.Calibration()

            data_shape = display_calibration_info.display_data_shape
            metadata = data_and_metadata.metadata

            # allow registered metadata_display components to populate a dictionary
            # the image canvas item will look at "frame_index" and "info_items"
            d: Persistence.PersistentDictType = dict()
            for component in Registry.get_components_by_type("metadata_display"):
                component.populate(d, metadata)

            # pull out the frame_index and info_items keys
            frame_index = d.get("frame_index", 0)
            info_items = d.get("info_items", list())

            # this method may trigger a layout of its parent scroll area. however, the parent scroll
            # area may already be closed. this is a stop-gap guess at a solution - the basic idea being
            # that this object is not closeable while this method is running; and this method should not
            # run if the object is already closed.
            with self.__closing_lock:
                if self.__closed:
                    return

                image_zoom = display_properties.get("image_zoom", 1.0)
                image_position = Geometry.FloatPoint.make(display_properties.get("image_position", (0.5, 0.5)))
                image_canvas_mode = display_properties.get("image_canvas_mode", "fit")

                if self.__image_zoom != image_zoom or self.__image_position != image_position or self.__image_canvas_mode != image_canvas_mode:
                    if image_zoom is not None:
                        self.__image_zoom = image_zoom
                    if image_position is not None:
                        self.__image_position = image_position
                    if image_canvas_mode is not None:
                        self.__image_canvas_mode = image_canvas_mode

                # if the data changes, update the display.
                if data_shape is not None and len(data_shape) == 2 and ((display_properties != self.__last_display_properties) or (display_calibration_info != self.__last_display_calibration_info) or (self.__display_values_dirty)):
                    self.__display_values_dirty = False
                    self.__last_display_properties = copy.deepcopy(display_properties)
                    self.__last_display_calibration_info = copy.deepcopy(display_calibration_info)
                    self.__data_shape = data_shape[0], data_shape[1]
                    self.__coordinate_system = display_calibration_info.datum_calibrations
                    if self.__display_frame_rate_id:
                        if frame_index != self.__display_frame_rate_last_index:
                            Utility.fps_tick("frame_"+self.__display_frame_rate_id)
                            self.__display_frame_rate_last_index = frame_index
                        Utility.fps_tick("update_"+self.__display_frame_rate_id)
                    # update the cursor info
                    self.__update_cursor_info()

                    def update_layout() -> None:
                        # layout. this makes sure that the info overlay gets updated too.
                        # called on the main thread.
                        self.__update_image_canvas_size()
                        # trigger updates
                        self.update()
                        self.__composite_canvas_item.update()
                        self.__bitmap_canvas_item.update()
                        with self.__update_layout_handle_lock:
                            self.__update_layout_handle = None

                    if self.__event_loop:
                        with self.__update_layout_handle_lock:
                            update_layout_handle = self.__update_layout_handle
                            if update_layout_handle:
                                update_layout_handle.cancel()
                            scroll_area_canvas_size = self.scroll_area_canvas_item.canvas_size
                            if scroll_area_canvas_size is not None:
                                # only update layout if the size/origin will change. it is slow.
                                image_canvas_rect: typing.Optional[Geometry.IntRect]
                                if self.__data_shape is not None:
                                    image_canvas_rect = calculate_origin_and_size(scroll_area_canvas_size, self.__data_shape, self.__image_canvas_mode, self.__image_zoom, self.__image_position)
                                else:
                                    image_canvas_rect = None
                                if image_canvas_rect != self.__composite_canvas_item.canvas_rect:
                                    self.__update_layout_handle = self.__event_loop.call_soon_threadsafe(update_layout)
                                else:
                                    # trigger updates
                                    self.__bitmap_canvas_item.update()
                                    with self.__update_layout_handle_lock:
                                        update_layout_handle = self.__update_layout_handle
                                        if update_layout_handle:
                                            update_layout_handle.cancel()
                                        self.__update_layout_handle = None

                # setting the bitmap on the bitmap_canvas_item is delayed until paint, so that it happens on a thread, since it may be time consuming
                self.__scale_marker_canvas_item.set_data_info(dimensional_calibration, info_items)
                self.__update_scale_stream()

    def update_graphics_coordinate_system(self, graphics: typing.Sequence[Graphics.Graphic], graphic_selection: DisplayItem.GraphicSelection, display_calibration_info: DisplayItem.DisplayCalibrationInfo) -> None:
        self.__graphics = list(graphics)
        self.__graphic_selection = copy.copy(graphic_selection)
        self.__graphics_canvas_item.update_coordinate_system(display_calibration_info.display_data_shape, display_calibration_info.datum_calibrations, self.__graphics, self.__graphic_selection)

    def handle_auto_display(self) -> bool:
        # enter key has been pressed. calculate best display limits and set them.
        delegate = self.delegate
        if delegate and self.__display_values:
            display_data_and_metadata = self.__display_values.display_data_and_metadata if self.__display_values else None
            data = display_data_and_metadata.data if display_data_and_metadata else None
            if data is not None:
                # The old algorithm was a problem during EELS where the signal data
                # is a small percentage of the overall data and was falling outside
                # the included range. This is the new simplified algorithm. Future
                # feature may allow user to select more complex algorithms.
                mn, mx = numpy.nanmin(data), numpy.nanmax(data)
                delegate.update_display_data_channel_properties({"display_limits": (mn, mx)})
        return True

    # update the image canvas position by the widget delta amount. called on main thread.
    def __update_image_canvas_position(self, widget_delta: Geometry.FloatSize) -> None:
        # create a widget mapping to get from image norm to widget coordinates and back
        delegate = self.delegate
        widget_mapping = ImageCanvasItemMapping.make(self.__data_shape, self.__composite_canvas_item.canvas_bounds, list())
        if delegate and widget_mapping:
            # figure out what composite canvas point lies at the center of the scroll area.
            last_widget_center = widget_mapping.map_point_image_norm_to_widget(self.__image_position)
            # determine what new point will lie at the center of the scroll area by adding delta
            new_widget_center = last_widget_center + widget_delta
            # map back to image norm coordinates
            new_image_norm_center = widget_mapping.map_point_widget_to_image_norm(new_widget_center)
            # ensure that at least half of the image is always visible
            new_image_norm_center_0 = max(min(new_image_norm_center[0], 1.0), 0.0)
            new_image_norm_center_1 = max(min(new_image_norm_center[1], 1.0), 0.0)
            # save the new image norm center
            self.__image_position = Geometry.FloatPoint(new_image_norm_center_0, new_image_norm_center_1)
            delegate.update_display_properties({"image_position": list(self.__image_position), "image_canvas_mode": "custom"})
            # and update the image canvas accordingly
            self.__image_canvas_mode = "custom"
            self.__update_image_canvas_size()
            self.__composite_canvas_item.update()

    # may be called on main thread or a render thread.
    def __update_scale_stream(self) -> None:
        screen_pixel_per_image_pixel = 0.0
        scroll_area_canvas_size = self.scroll_area_canvas_item.canvas_size
        widget_mapping = ImageCanvasItemMapping.make(self.__data_shape, self.__composite_canvas_item.canvas_rect, list())
        if scroll_area_canvas_size is not None and widget_mapping:
            data_shape = widget_mapping.data_shape
            image_canvas_rect = calculate_origin_and_size(scroll_area_canvas_size, data_shape, self.__image_canvas_mode, self.__image_zoom, self.__image_position)
            widget_mapping = ImageCanvasItemMapping(data_shape, image_canvas_rect, list())
            screen_pixel_per_image_pixel = widget_mapping.map_size_image_norm_to_widget(Geometry.FloatSize(1, 1)).height / data_shape[0]
        # until threading is cleaned up, this is a hack to avoid setting the value from two different threads at once.
        with self.__screen_pixel_per_image_pixel_stream_lock:
            self.__screen_pixel_per_image_pixel_stream.value = screen_pixel_per_image_pixel

    # update the image canvas origin and size. may be called on main thread or a render thread.
    def __update_overlay_canvas_item(self, scroll_area_canvas_size: Geometry.IntSize, immediate: bool = False) -> None:
        widget_mapping = ImageCanvasItemMapping.make(self.__data_shape, self.__composite_canvas_item.canvas_rect, list())
        if widget_mapping:
            image_canvas_rect = calculate_origin_and_size(scroll_area_canvas_size, widget_mapping.data_shape, self.__image_canvas_mode, self.__image_zoom, self.__image_position)
            self.__composite_canvas_item.update_layout(image_canvas_rect.origin, image_canvas_rect.size, immediate=immediate)
        self.__update_scale_stream()

    def __update_image_canvas_size(self) -> None:
        # called on the main thread.
        assert threading.current_thread() == threading.main_thread()
        scroll_area_canvas_size = self.scroll_area_canvas_item.canvas_size
        if scroll_area_canvas_size:
            self.__update_overlay_canvas_item(scroll_area_canvas_size)

    def mouse_clicked(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_clicked(x, y, modifiers):
            return True
        delegate = self.delegate
        widget_mapping = self.mouse_mapping
        if delegate and widget_mapping:
            # now let the image panel handle mouse clicking if desired
            image_position = widget_mapping.map_point_widget_to_image(Geometry.FloatPoint(y, x))
            return delegate.image_clicked(image_position, modifiers)
        return False

    def mouse_pressed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_pressed(x, y, modifiers):
            return True
        delegate = self.delegate
        widget_mapping = self.mouse_mapping
        if not delegate or not widget_mapping:
            return False
        mouse_pos = Geometry.FloatPoint(y, x)
        image_position = widget_mapping.map_point_widget_to_image(mouse_pos)
        pos = widget_mapping.map_point_widget_to_image_norm(mouse_pos)
        start_drag_pos = mouse_pos
        if delegate.image_mouse_pressed(image_position, modifiers):
            return True
        self.__undo_command = None
        delegate.begin_mouse_tracking()
        # figure out clicked graphic
        self.__graphic_drag_items = list()
        self.__graphic_drag_item = None
        self.graphic_drag_item_was_selected = False
        self.__graphic_part_data = dict()
        self.__graphic_drag_indexes = set()
        if delegate.tool_mode == "pointer":
            graphics = self.__graphics
            selection_indexes = self.__graphic_selection.indexes
            multiple_items_selected = len(selection_indexes) > 1
            part_specs: typing.List[typing.Tuple[int, Graphics.Graphic, bool, str]] = list()
            part_spec: typing.Optional[typing.Tuple[int, Graphics.Graphic, bool, str]] = None
            specific_part_spec: typing.Optional[typing.Tuple[int, Graphics.Graphic, bool, str]] = None
            # the graphics are drawn in order, which means the graphics with the higher index are "on top" of the
            # graphics with the lower index. but priority should also be given to selected graphics. so sort the
            # graphics according to whether they are selected or not (selected ones go later), then by their index.
            for graphic_index, graphic in sorted(enumerate(graphics), key=lambda ig: (ig[0] in selection_indexes, ig[0])):
                if isinstance(graphic, (Graphics.PointTypeGraphic, Graphics.LineTypeGraphic, Graphics.RectangleTypeGraphic, Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
                    already_selected = graphic_index in selection_indexes
                    move_only = not already_selected or multiple_items_selected
                    try:
                        part, specific = graphic.test(widget_mapping, self.__ui_settings, start_drag_pos, move_only)
                    except Exception as e:
                        import traceback
                        logging.debug("Graphic Test Error: %s", e)
                        traceback.print_exc()
                        traceback.print_stack()
                        continue
                    if part:
                        part_spec = graphic_index, graphic, already_selected, "all" if move_only and not part.startswith("inverted") else part
                        part_specs.append(part_spec)
                        if specific:
                            specific_part_spec = part_spec
            # import logging
            # logging.debug(specific_part_spec)
            # logging.debug(part_specs)
            part_spec = specific_part_spec if specific_part_spec is not None else part_specs[-1] if len(part_specs) > 0 else None
            if part_spec is not None:
                graphic_index, graphic, already_selected, part = part_spec
                part = part if specific_part_spec is not None else part_spec[-1]
                # select item and prepare for drag
                self.graphic_drag_item_was_selected = already_selected
                if not self.graphic_drag_item_was_selected:
                    if modifiers.control:
                        delegate.add_index_to_selection(graphic_index)
                        selection_indexes.add(graphic_index)
                    elif not already_selected:
                        delegate.set_selection(graphic_index)
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
            if not self.__graphic_drag_items and not modifiers.control:
                delegate.clear_selection()
        elif delegate.tool_mode == "line":
            graphic = delegate.create_line(pos)
            delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                selection_indexes = self.__graphic_selection.indexes
                assert len(selection_indexes) == 1
                self.graphic_drag_item_was_selected = True
                # keep track of general drag information
                self.__graphic_drag_start_pos = start_drag_pos
                self.__graphic_drag_changed = False
                # keep track of info for the specific item that was clicked
                self.__graphic_drag_item = graphic
                self.__graphic_drag_part = "end"
                # keep track of drag information for each item in the set
                self.__graphic_drag_indexes = selection_indexes
                self.__graphic_drag_items.append(graphic)
                self.__graphic_part_data[list(selection_indexes)[0]] = graphic.begin_drag()
                self.__undo_command = delegate.create_insert_graphics_command([graphic])
        elif delegate.tool_mode == "rectangle":
            graphic = delegate.create_rectangle(pos)
            delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                selection_indexes = self.__graphic_selection.indexes
                assert len(selection_indexes) == 1
                self.graphic_drag_item_was_selected = True
                # keep track of general drag information
                self.__graphic_drag_start_pos = start_drag_pos
                self.__graphic_drag_changed = False
                # keep track of info for the specific item that was clicked
                self.__graphic_drag_item = graphic
                self.__graphic_drag_part = "bottom-right"
                # keep track of drag information for each item in the set
                self.__graphic_drag_indexes = selection_indexes
                self.__graphic_drag_items.append(graphic)
                self.__graphic_part_data[list(selection_indexes)[0]] = graphic.begin_drag()
                self.__undo_command = delegate.create_insert_graphics_command([graphic])
        elif delegate.tool_mode == "ellipse":
            graphic = delegate.create_ellipse(pos)
            delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                selection_indexes = self.__graphic_selection.indexes
                assert len(selection_indexes) == 1
                self.graphic_drag_item_was_selected = True
                # keep track of general drag information
                self.__graphic_drag_start_pos = start_drag_pos
                self.__graphic_drag_changed = False
                # keep track of info for the specific item that was clicked
                self.__graphic_drag_item = graphic
                self.__graphic_drag_part = "bottom-right"
                # keep track of drag information for each item in the set
                self.__graphic_drag_indexes = selection_indexes
                self.__graphic_drag_items.append(graphic)
                self.__graphic_part_data[list(selection_indexes)[0]] = graphic.begin_drag()
                self.__undo_command = delegate.create_insert_graphics_command([graphic])
        elif delegate.tool_mode == "point":
            graphic = delegate.create_point(pos)
            delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                selection_indexes = self.__graphic_selection.indexes
                assert len(selection_indexes) == 1
                self.graphic_drag_item_was_selected = True
                # keep track of general drag information
                self.__graphic_drag_start_pos = start_drag_pos
                self.__graphic_drag_changed = False
                # keep track of info for the specific item that was clicked
                self.__graphic_drag_item = graphic
                self.__graphic_drag_part = "all"
                # keep track of drag information for each item in the set
                self.__graphic_drag_indexes = selection_indexes
                self.__graphic_drag_items.append(graphic)
                self.__graphic_part_data[list(selection_indexes)[0]] = graphic.begin_drag()
                self.__undo_command = delegate.create_insert_graphics_command([graphic])
        elif delegate.tool_mode == "line-profile":
            graphic = delegate.create_line_profile(pos)
            delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                selection_indexes = self.__graphic_selection.indexes
                assert len(selection_indexes) == 1
                self.graphic_drag_item_was_selected = True
                # keep track of general drag information
                self.__graphic_drag_start_pos = start_drag_pos
                self.__graphic_drag_changed = False
                # keep track of info for the specific item that was clicked
                self.__graphic_drag_item = graphic
                self.__graphic_drag_part = "end"
                # keep track of drag information for each item in the set
                self.__graphic_drag_indexes = selection_indexes
                self.__graphic_drag_items.append(graphic)
                self.__graphic_part_data[list(selection_indexes)[0]] = graphic.begin_drag()
                self.__undo_command = delegate.create_insert_graphics_command([graphic])
        elif delegate.tool_mode == "spot":
            graphic = delegate.create_spot(pos)
            delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                selection_indexes = self.__graphic_selection.indexes
                assert len(selection_indexes) == 1
                self.graphic_drag_item_was_selected = True
                # keep track of general drag information
                self.__graphic_drag_start_pos = start_drag_pos
                self.__graphic_drag_changed = False
                # keep track of info for the specific item that was clicked
                self.__graphic_drag_item = graphic
                self.__graphic_drag_part = "bottom-right"
                # keep track of drag information for each item in the set
                self.__graphic_drag_indexes = selection_indexes
                self.__graphic_drag_items.append(graphic)
                self.__graphic_part_data[list(selection_indexes)[0]] = graphic.begin_drag()
                self.__undo_command = delegate.create_insert_graphics_command([graphic])
        elif delegate.tool_mode == "wedge":
            mouse_angle = math.pi - math.atan2(0.5 - pos[0], 0.5 - pos[1])
            graphic = delegate.create_wedge(mouse_angle)
            delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                selection_indexes = self.__graphic_selection.indexes
                assert len(selection_indexes) == 1
                self.graphic_drag_item_was_selected = True
                # keep track of general drag information
                self.__graphic_drag_start_pos = start_drag_pos
                self.__graphic_drag_changed = False
                # keep track of info for the specific item that was clicked
                self.__graphic_drag_item = graphic
                self.__graphic_drag_part = "start-angle"
                # keep track of drag information for each item in the set
                self.__graphic_drag_indexes = selection_indexes
                self.__graphic_drag_items.append(graphic)
                self.__graphic_part_data[list(selection_indexes)[0]] = graphic.begin_drag()
                self.__undo_command = delegate.create_insert_graphics_command([graphic])
        elif delegate.tool_mode == "ring":
            radius = math.sqrt((pos[0] - 0.5) ** 2 + (pos[1] - 0.5) ** 2)
            graphic = delegate.create_ring(radius)
            delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                selection_indexes = self.__graphic_selection.indexes
                assert len(selection_indexes) == 1
                self.graphic_drag_item_was_selected = True
                # keep track of general drag information
                self.__graphic_drag_start_pos = start_drag_pos
                self.__graphic_drag_changed = False
                # keep track of info for the specific item that was clicked
                self.__graphic_drag_item = graphic
                self.__graphic_drag_part = "radius_1"
                # keep track of drag information for each item in the set
                self.__graphic_drag_indexes = selection_indexes
                self.__graphic_drag_items.append(graphic)
                self.__graphic_part_data[list(selection_indexes)[0]] = graphic.begin_drag()
                self.__undo_command = delegate.create_insert_graphics_command([graphic])
        elif delegate.tool_mode == "lattice":
            graphic = delegate.create_lattice(pos.as_size())
            delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                selection_indexes = self.__graphic_selection.indexes
                assert len(selection_indexes) == 1
                self.graphic_drag_item_was_selected = True
                # keep track of general drag information
                self.__graphic_drag_start_pos = start_drag_pos
                self.__graphic_drag_changed = False
                # keep track of info for the specific item that was clicked
                self.__graphic_drag_item = graphic
                self.__graphic_drag_part = "u-all"
                # keep track of drag information for each item in the set
                self.__graphic_drag_indexes = selection_indexes
                self.__graphic_drag_items.append(graphic)
                self.__graphic_part_data[list(selection_indexes)[0]] = graphic.begin_drag()
                self.__undo_command = delegate.create_insert_graphics_command([graphic])
        elif delegate.tool_mode == "hand":
            self.__last_drag_pos = mouse_pos
            self.__is_dragging = True
        return True

    def mouse_released(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_released(x, y, modifiers):
            return True
        delegate = self.delegate
        widget_mapping = self.mouse_mapping
        if not delegate or not widget_mapping:
            return False
        mouse_pos = Geometry.FloatPoint(y, x)
        image_position = widget_mapping.map_point_widget_to_image(mouse_pos)
        if delegate.image_mouse_released(image_position, modifiers):
            return True
        graphics = self.__graphics
        for index in self.__graphic_drag_indexes:
            graphic = graphics[index]
            graphic.end_drag(self.__graphic_part_data[index])
        if self.__graphic_drag_items and not self.__graphic_drag_changed:
            graphic_index = graphics.index(self.__graphic_drag_item) if self.__graphic_drag_item else 0
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
        delegate.end_mouse_tracking(self.__undo_command)
        self.__undo_command = None
        self.__graphic_drag_items = list()
        self.__graphic_drag_item = None
        self.__graphic_part_data = dict()
        self.__graphic_drag_indexes = set()
        self.__last_drag_pos = None
        self.__is_dragging = False
        if delegate.tool_mode != "hand":
            delegate.tool_mode = "pointer"
        return True

    def mouse_entered(self) -> bool:
        if super().mouse_entered():
            return True
        self.__mouse_in = True
        return True

    def mouse_exited(self) -> bool:
        if super().mouse_exited():
            return True
        self.__mouse_in = False
        if self.delegate:  # allow display to work without delegate
            # whenever the cursor exits, clear the cursor display
            self.delegate.cursor_changed(None)
        return True

    def mouse_position_changed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_position_changed(x, y, modifiers):
            return True
        delegate = self.delegate
        widget_mapping = self.mouse_mapping
        if not delegate or not widget_mapping:
            return False
        mouse_pos = Geometry.FloatPoint(y, x)
        image_position = widget_mapping.map_point_widget_to_image(mouse_pos)
        if delegate.image_mouse_position_changed(image_position, modifiers):
            return True
        if delegate.tool_mode == "pointer":
            def get_pointer_tool_shape() -> str:
                for graphic in self.__graphics:
                    if isinstance(graphic, (Graphics.RectangleTypeGraphic, Graphics.SpotGraphic)):
                        part, specific = graphic.test(self.__get_mouse_mapping(), self.__ui_settings, Geometry.FloatPoint(x=x, y=y), False)
                        if part and part.endswith("rotate"):
                            return "cross"
                return "arrow"
            self.cursor_shape = get_pointer_tool_shape()
        elif delegate.tool_mode == "line":
            self.cursor_shape = "cross"
        elif delegate.tool_mode == "rectangle":
            self.cursor_shape = "cross"
        elif delegate.tool_mode == "ellipse":
            self.cursor_shape = "cross"
        elif delegate.tool_mode == "point":
            self.cursor_shape = "cross"
        elif delegate.tool_mode == "line-profile":
            self.cursor_shape = "cross"
        elif delegate.tool_mode == "spot":
            self.cursor_shape = "cross"
        elif delegate.tool_mode == "wedge":
            self.cursor_shape = "cross"
        elif delegate.tool_mode == "ring":
            self.cursor_shape = "cross"
        elif delegate.tool_mode == "hand":
            self.cursor_shape = "hand"
        # x,y already have transform applied
        self.__last_mouse = mouse_pos.to_int_point()
        self.__update_cursor_info()
        if self.__graphic_drag_items:
            if not self.__undo_command:
                self.__undo_command = delegate.create_change_graphics_command()
            force_drag = modifiers.only_option
            if force_drag and self.__graphic_drag_part == "all":
                if Geometry.distance(mouse_pos, self.__graphic_drag_start_pos) <= 2:
                    delegate.drag_graphics(self.__graphic_drag_items)
                    return True
            widget_mapping = self.__get_mouse_mapping()
            delegate.adjust_graphics(widget_mapping, self.__graphic_drag_items, self.__graphic_drag_part,
                                     self.__graphic_part_data, self.__graphic_drag_start_pos, mouse_pos, modifiers)
            self.__graphic_drag_changed = True
        elif self.__is_dragging:
            assert self.__last_drag_pos
            if not self.__undo_command:
                self.__undo_command = delegate.create_change_display_command()
            delta = mouse_pos - self.__last_drag_pos
            self.__update_image_canvas_position(-delta.as_size())
            self.__last_drag_pos = mouse_pos
        return True

    def wheel_changed(self, x: int, y: int, dx: int, dy: int, is_horizontal: bool) -> bool:
        delegate = self.delegate
        if delegate and self.__mouse_in:
            dx = dx if is_horizontal else 0
            dy = dy if not is_horizontal else 0
            command = delegate.create_change_display_command(command_id="image_position", is_mergeable=True)
            self.__update_image_canvas_position(Geometry.FloatSize(-dy, -dx))
            delegate.push_undo_command(command)
            return True
        return False

    def pan_gesture(self, dx: int, dy: int) -> bool:
        self.__update_image_canvas_position(Geometry.FloatSize(dy, dx))
        return True

    def context_menu_event(self, x: int, y: int, gx: int, gy: int) -> bool:
        delegate = self.delegate
        if delegate:
            return delegate.show_display_context_menu(gx, gy)
        return False

    @property
    def key_contexts(self) -> typing.Sequence[str]:
        # key contexts provide an ordered list of contexts that are used to determine
        # which actions are valid at a given time. the contexts are checked in reverse
        # order (i.e. last added have highest precedence).
        key_contexts = ["display_panel"]
        if self.__data_shape is not None:
            key_contexts.append("raster_display")
            if self.__graphic_selection.has_selection:
                key_contexts.append("raster_display_graphics")
            graphic_type: typing.Optional[str] = None
            for graphic_index in self.__graphic_selection.indexes:
                graphic = self.__graphics[graphic_index]
                if graphic_type and graphic.type != graphic_type:
                    graphic_type = None
                    break
                graphic_type = graphic.type
            if graphic_type:
                key_contexts.append(graphic_type.replace("-", "_"))
        return key_contexts

    def toggle_frame_rate(self) -> None:
        if self.__display_frame_rate_id is None:
            self.__display_frame_rate_id = str(id(self))
        else:
            self.__display_frame_rate_id = None

    def toggle_latency(self) -> None:
        self.__display_latency = not self.__display_latency

    def __get_mouse_mapping(self) -> ImageCanvasItemMapping:
        widget_mapping = ImageCanvasItemMapping.make(self.__data_shape, self.__composite_canvas_item.canvas_rect, self.__coordinate_system)
        assert widget_mapping
        return widget_mapping

    @property
    def mouse_mapping(self) -> ImageCanvasItemMapping:
        return self.__get_mouse_mapping()

    # map from widget coordinates to image coordinates
    def map_widget_to_image(self, p: Geometry.IntPoint) -> typing.Optional[typing.Tuple[int, int]]:
        transformed_image_rect = self.__get_mouse_mapping().canvas_rect
        if transformed_image_rect and self.__data_shape:
            image_size = Geometry.IntSize.make(self.__data_shape)
            if transformed_image_rect.height != 0.0:
                image_y = math.floor(image_size.height * (p.y - transformed_image_rect.top) / transformed_image_rect.height)
            else:
                image_y = 0
            if transformed_image_rect.width != 0.0:
                image_x = math.floor(image_size.width * (p.x - transformed_image_rect.left) / transformed_image_rect.width)
            else:
                image_x = 0
            return image_y, image_x
        return None

    # map from image normalized coordinates to image coordinates
    def map_image_norm_to_image(self, p: Geometry.FloatPoint) -> typing.Optional[Geometry.FloatPoint]:
        image_size = self.__data_shape
        if image_size:
            return Geometry.FloatPoint(p.y * image_size[0], p.x * image_size[1])
        return None

    def __update_cursor_info(self) -> None:
        delegate = self.delegate
        if delegate:
            image_size = self.__data_shape
            if self.__mouse_in and self.__last_mouse:
                pos_2d = None
                if image_size is not None and len(image_size) > 1:
                    pos_2d = self.map_widget_to_image(self.__last_mouse)
                delegate.cursor_changed(pos_2d)

    def _prepare_render(self) -> None:
        # this is called before layout and repainting. it gives this display item a chance
        # to update anything required for layout and trigger a layout before a repaint if
        # anything has changed.
        self.prepare_display()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        super()._repaint(drawing_context)
        canvas_bounds = self.canvas_bounds
        if canvas_bounds and self.__display_frame_rate_id:
            Utility.fps_tick("display_"+self.__display_frame_rate_id)
            fps = Utility.fps_get("display_"+self.__display_frame_rate_id)
            fps2 = Utility.fps_get("frame_"+self.__display_frame_rate_id)
            fps3 = Utility.fps_get("update_"+self.__display_frame_rate_id)
            with drawing_context.saver():
                font = "normal 11px serif"
                text_pos = canvas_bounds.top_left
                drawing_context.begin_path()
                drawing_context.move_to(text_pos.x, text_pos.y)
                drawing_context.line_to(text_pos.x + 200, text_pos.y)
                drawing_context.line_to(text_pos.x + 200, text_pos.y + 60)
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
                drawing_context.statistics("display")

    # this method will be invoked from the paint thread.
    # data is calculated and then sent to the image canvas item.
    def prepare_display(self) -> None:
        if self.__data_shape is not None:
            # configure the bitmap canvas item
            display_values = self.__display_values
            if display_values:
                display_data = display_values.adjusted_data_and_metadata
                if display_data and display_data.data_dtype == numpy.float32:
                    display_range = display_values.transformed_display_range
                    color_map_data = display_values.color_map_data
                    display_values.finalize()
                    color_map_rgba: typing.Optional[DrawingContext.RGBA32Type]
                    if color_map_data is not None:
                        color_map_rgba = numpy.empty(color_map_data.shape[:-1] + (4,), numpy.uint8)
                        color_map_rgba[..., 0:3] = color_map_data
                        color_map_rgba[..., 3] = 255
                        color_map_rgba = color_map_rgba.view(numpy.uint32).reshape(color_map_rgba.shape[:-1])
                    else:
                        color_map_rgba = None
                    self.__bitmap_canvas_item.set_data(display_data.data, display_range, color_map_rgba, trigger_update=False)
                else:
                    data_rgba = display_values.display_rgba
                    display_values.finalize()
                    self.__bitmap_canvas_item.set_rgba_bitmap_data(data_rgba, trigger_update=False)
                self.__timestamp_canvas_item.timestamp = display_values.display_rgba_timestamp if self.__display_latency else None

    @property
    def image_canvas_mode(self) -> str:
        return self.__image_canvas_mode

    @property
    def _bitmap_canvas_item(self) -> CanvasItem.BitmapCanvasItem:
        return self.__bitmap_canvas_item

    @property
    def _display_values(self) -> typing.Optional[DisplayItem.DisplayValues]:
        return self.__display_values

    @property
    def _display_values_dirty(self) -> bool:
        return self.__display_values_dirty

    def __apply_display_properties_command(self, display_properties: Persistence.PersistentDictType) -> None:
        delegate = self.delegate
        if delegate:
            command = delegate.create_change_display_command()
            delegate.update_display_properties(display_properties)
            delegate.push_undo_command(command)

    def apply_move_command(self, delta: Geometry.FloatSize) -> None:
        delegate = self.delegate
        if delegate:
            command = delegate.create_change_display_command(command_id="image_nudge", is_mergeable=True)
            self.__update_image_canvas_position(delta)
            delegate.push_undo_command(command)

    def set_fit_mode(self) -> None:
        self.__apply_display_properties_command({"image_zoom": 1.0, "image_position": (0.5, 0.5), "image_canvas_mode": "fit"})

    def set_fill_mode(self) -> None:
        self.__apply_display_properties_command({"image_zoom": 1.0, "image_position": (0.5, 0.5), "image_canvas_mode": "fill"})

    def set_one_to_one_mode(self) -> None:
        self.__apply_display_properties_command({"image_zoom": 1.0, "image_position": (0.5, 0.5), "image_canvas_mode": "1:1"})

    def set_two_to_one_mode(self) -> None:
        self.__apply_display_properties_command({"image_zoom": 0.5, "image_position": (0.5, 0.5), "image_canvas_mode": "2:1"})

    def zoom_in(self) -> None:
        self.__apply_display_properties_command({"image_zoom": self.__image_zoom * 1.25, "image_canvas_mode": "custom"})

    def zoom_out(self) -> None:
        self.__apply_display_properties_command({"image_zoom": self.__image_zoom / 1.25, "image_canvas_mode": "custom"})

    def move_left(self, amount: float = 10.0) -> None:
        self.apply_move_command(Geometry.FloatSize(0.0, amount))

    def move_right(self, amount: float = 10.0) -> None:
        self.apply_move_command(Geometry.FloatSize(0.0, -amount))

    def move_up(self, amount: float = 10.0) -> None:
        self.apply_move_command(Geometry.FloatSize(amount, 0.0))

    def move_down(self, amount: float = 10.0) -> None:
        self.apply_move_command(Geometry.FloatSize(-amount, 0.0))
