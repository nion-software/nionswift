# standard libraries
import copy
import logging
import math
import threading
import typing

# third party libraries
import numpy
import scipy.ndimage

# local libraries
from nion.data import Calibration
from nion.swift import Undo
from nion.swift.model import Graphics
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.utils import Geometry


class ImageCanvasItemMapping:

    def __init__(self, data_shape, canvas_origin, canvas_size):
        assert data_shape is None or len(data_shape) == 2
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

    def map_size_image_to_widget(self, s):
        ms = self.map_point_image_to_widget(s)
        ms0 = self.map_point_image_to_widget((0, 0))
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

    def map_point_image_to_widget(self, p):
        p = Geometry.FloatPoint.make(p)
        if self.data_shape:
            return Geometry.FloatPoint(y=p.y * self.canvas_rect.height / self.data_shape[0] + self.canvas_rect.top, x=p.x * self.canvas_rect.width / self.data_shape[1] + self.canvas_rect.left)
        return None


class GraphicsCanvasItem(CanvasItem.AbstractCanvasItem):
    """A canvas item to paint the graphic items on the image.

    Callers should call update_graphics when the graphics changes.
    """

    def __init__(self, get_font_metrics_fn):
        super(GraphicsCanvasItem, self).__init__()
        self.__get_font_metrics_fn = get_font_metrics_fn
        self.__displayed_shape = None
        self.__graphics = None
        self.__graphics_for_compare = list()
        self.__graphic_selection = None

    def update_graphics(self, displayed_shape, graphics, graphic_selection):
        if displayed_shape is None or len(displayed_shape) != 2:
            displayed_shape = None
            graphics = None
            graphic_selection = None
        assert displayed_shape is None or len(displayed_shape) == 2
        needs_update = False
        if ((self.__displayed_shape is None) != (displayed_shape is None)) or (self.__displayed_shape != displayed_shape):
            self.__displayed_shape = displayed_shape
            needs_update = True
        graphics_for_compare = [graphic.mime_data_dict() for graphic in (graphics or list())]
        if graphics_for_compare != self.__graphics_for_compare:
            self.__graphics = graphics
            self.__graphics_for_compare = graphics_for_compare
            needs_update = True
        if self.__graphic_selection != graphic_selection:
            self.__graphic_selection = graphic_selection
            needs_update = True
        if needs_update:
            self.update()

    def _repaint(self, drawing_context):
        if self.__graphics:
            widget_mapping = ImageCanvasItemMapping(self.__displayed_shape, (0, 0), self.canvas_size)
            with drawing_context.saver():
                for graphic_index, graphic in enumerate(self.__graphics):
                    if isinstance(graphic, (Graphics.PointTypeGraphic, Graphics.LineTypeGraphic, Graphics.RectangleTypeGraphic, Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                        try:
                            graphic.draw(drawing_context, self.__get_font_metrics_fn, widget_mapping, self.__graphic_selection.contains(graphic_index))
                        except Exception as e:
                            import traceback
                            logging.debug("Graphic Repaint Error: %s", e)
                            traceback.print_exc()
                            traceback.print_stack()


class InfoOverlayCanvasItem(CanvasItem.AbstractCanvasItem):
    """A canvas item to paint the scale marker as an overlay.

    Callers should set the image_canvas_origin and image_canvas_size properties.

    Callers should also call set_data_info when the data changes.
    """

    def __init__(self):
        super(InfoOverlayCanvasItem, self).__init__()
        self.__image_canvas_size = None  # this will be updated by the container
        self.__image_canvas_origin = None  # this will be updated by the container
        self.__data_shape = None
        self.__dimensional_calibration = None
        self.__info_text = None

    @property
    def _dimension_calibration_for_test(self):
        return self.__dimensional_calibration

    @property
    def image_canvas_size(self):
        return self.__image_canvas_size

    @image_canvas_size.setter
    def image_canvas_size(self, value):
        if self.__image_canvas_size is None or value != self.__image_canvas_size:
            self.__image_canvas_size = value
            self.update()

    @property
    def image_canvas_origin(self):
        return self.__image_canvas_origin

    @image_canvas_origin.setter
    def image_canvas_origin(self, value):
        if self.__image_canvas_origin is None or value != self.__image_canvas_origin:
            self.__image_canvas_origin = value
            self.update()

    def set_data_info(self, data_shape, dimensional_calibration: Calibration.Calibration, metadata: dict) -> None:
        needs_update = False
        if self.__data_shape is None or data_shape != self.__data_shape:
            self.__data_shape = data_shape
            needs_update = True
        if self.__dimensional_calibration is None or dimensional_calibration != self.__dimensional_calibration:
            self.__dimensional_calibration = dimensional_calibration
            needs_update = True
        info_items = list()
        hardware_source_metadata = metadata.get("hardware_source", dict())
        voltage = hardware_source_metadata.get("autostem", dict()).get("high_tension_v", 0)
        if voltage:
            units = "V"
            if voltage % 1000 == 0:
                voltage = voltage // 1000
                units = "kV"
            info_items.append("{0} {1}".format(voltage, units))
        hardware_source_name = hardware_source_metadata.get("hardware_source_name")
        if hardware_source_name:
            info_items.append(str(hardware_source_name))
        info_text = " ".join(info_items)
        if self.__info_text is None or self.__info_text != info_text:
            self.__info_text = info_text
            needs_update = True
        if needs_update:
            self.update()

    def _repaint(self, drawing_context):
        canvas_size = self.canvas_size
        canvas_height = canvas_size[0]
        image_canvas_size = self.image_canvas_size
        image_canvas_origin = self.image_canvas_origin
        dimensional_calibration = self.__dimensional_calibration
        if dimensional_calibration is not None and image_canvas_origin is not None and image_canvas_size is not None:  # display scale marker?
            origin = (canvas_height - 30, 20)
            scale_marker_width = 120
            scale_marker_height = 6
            data_shape = self.__data_shape
            widget_mapping = ImageCanvasItemMapping(data_shape, image_canvas_origin, image_canvas_size)
            if data_shape[0] > 1.0 and data_shape[1] > 0.0:
                screen_pixel_per_image_pixel = widget_mapping.map_size_image_norm_to_widget((1, 1))[0] / data_shape[0]
                if screen_pixel_per_image_pixel > 0:
                    scale_marker_image_width = scale_marker_width / screen_pixel_per_image_pixel
                    calibrated_scale_marker_width = Geometry.make_pretty2(scale_marker_image_width * dimensional_calibration.scale, True)
                    # update the scale marker width
                    scale_marker_image_width = calibrated_scale_marker_width / dimensional_calibration.scale
                    scale_marker_width = scale_marker_image_width * screen_pixel_per_image_pixel
                    with drawing_context.saver():
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
                        drawing_context.fill_text(dimensional_calibration.convert_to_calibrated_size_str(scale_marker_image_width), origin[1], origin[0] - scale_marker_height - 4)
                        drawing_context.fill_text(self.__info_text, origin[1], origin[0] - scale_marker_height - 4 - 20)


class ImageCanvasItemDelegate:
    # interface must be implemented by the delegate

    def begin_mouse_tracking(self) -> None: ...

    def end_mouse_tracking(self, undo_command) -> None: ...

    def delete_key_pressed(self) -> None: ...

    def enter_key_pressed(self) -> None: ...

    def cursor_changed(self, pos): ...

    def update_display_properties(self, display_properties: typing.Mapping) -> None: ...

    def create_insert_graphics_command(self, graphics: typing.Sequence[Graphics.Graphic]) -> Undo.UndoableCommand: ...

    def create_change_display_command(self, *, command_id: str=None, is_mergeable: bool=False) -> Undo.UndoableCommand: ...

    def create_change_graphics_command(self) -> Undo.UndoableCommand: ...

    def push_undo_command(self, command: Undo.UndoableCommand) -> None: ...

    def add_index_to_selection(self, index: int) -> None: ...

    def remove_index_from_selection(self, index: int) -> None: ...

    def set_selection(self, index: int) -> None: ...

    def clear_selection(self) -> None: ...

    def nudge_selected_graphics(self, mapping, delta) -> None: ...

    def drag_graphics(self, graphics) -> None: ...

    def update_graphics(self, widget_mapping, graphic_drag_items, graphic_drag_part, graphic_part_data, graphic_drag_start_pos, pos, modifiers) -> None: ...

    def image_clicked(self, image_position, modifiers) -> bool: ...

    def image_mouse_pressed(self, image_position, modifiers) -> bool: ...

    def image_mouse_released(self, image_position, modifiers) -> bool: ...

    def image_mouse_position_changed(self, image_position, modifiers) -> bool: ...

    def show_display_context_menu(self, gx, gy) -> bool: ...

    def create_rectangle(self, pos): ...

    def create_ellipse(self, pos): ...

    def create_line(self, pos): ...

    def create_point(self, pos): ...

    def create_line_profile(self, pos): ...

    def create_spot(self, pos): ...

    def create_wedge(self, angle): ...

    def create_ring(self, radius): ...

    @property
    def tool_mode(self) -> str: return str()

    @tool_mode.setter
    def tool_mode(self, value: str) -> None: ...


def calculate_origin_and_size(canvas_size, data_shape, image_canvas_mode, image_zoom, image_position) -> typing.Tuple[typing.Any, typing.Any]:
    """Calculate origin and size for canvas size, data shape, and image display parameters."""
    if data_shape is None:
        return None, None
    if image_canvas_mode == "fill":
        data_shape = data_shape
        scale_h = float(data_shape[1]) / canvas_size[1]
        scale_v = float(data_shape[0]) / canvas_size[0]
        if scale_v < scale_h:
            image_canvas_size = (canvas_size[0], canvas_size[0] * data_shape[1] / data_shape[0])
        else:
            image_canvas_size = (canvas_size[1] * data_shape[0] / data_shape[1], canvas_size[1])
        image_canvas_origin = (canvas_size[0] * 0.5 - image_canvas_size[0] * 0.5, canvas_size[1] * 0.5 - image_canvas_size[1] * 0.5)
    elif image_canvas_mode == "fit":
        image_canvas_size = canvas_size
        image_canvas_origin = (0, 0)
    elif image_canvas_mode == "1:1":
        image_canvas_size = data_shape
        image_canvas_origin = (canvas_size[0] * 0.5 - image_canvas_size[0] * 0.5, canvas_size[1] * 0.5 - image_canvas_size[1] * 0.5)
    elif image_canvas_mode == "2:1":
        image_canvas_size = (data_shape[0] * 0.5, data_shape[1] * 0.5)
        image_canvas_origin = (canvas_size[0] * 0.5 - image_canvas_size[0] * 0.5, canvas_size[1] * 0.5 - image_canvas_size[1] * 0.5)
    else:
        image_canvas_size = (canvas_size[0] * image_zoom, canvas_size[1] * image_zoom)
        canvas_rect = Geometry.fit_to_size(((0, 0), image_canvas_size), data_shape)
        image_canvas_origin_y = (canvas_size[0] * 0.5) - image_position[0] * canvas_rect[1][0] - canvas_rect[0][0]
        image_canvas_origin_x = (canvas_size[1] * 0.5) - image_position[1] * canvas_rect[1][1] - canvas_rect[0][1]
        image_canvas_origin = (image_canvas_origin_y, image_canvas_origin_x)
    return image_canvas_origin, image_canvas_size


class ImageCanvasItem(CanvasItem.LayerCanvasItem):
    """A canvas item to paint an image.

    Callers are expected to pass in a delegate.

    They are expected to call the following functions to update the display:
        update_image_display_state
        update_regions

    The delegate is expected to handle the following events:
        add_index_to_selection(index)
        remove_index_from_selection(index)
        set_selection(index)
        clear_selection()
        nudge_selected_graphics(mapping, delta)
        update_graphics(widget_mapping, graphic_drag_items, graphic_drag_part, graphic_part_data, graphic_drag_start_pos, pos, modifiers)
        tool_mode (property)
        show_display_context_menu(gx, gy)
        begin_mouse_tracking(self)
        end_mouse_tracking()
        mouse_clicked(image_position, modifiers)
        delete_key_pressed()
        enter_key_pressed()
        cursor_changed(pos)
    """

    def __init__(self, get_font_metrics_fn, delegate: ImageCanvasItemDelegate, event_loop, draw_background: bool=True):
        super().__init__()

        self.__get_font_metrics_fn = get_font_metrics_fn
        self.delegate = delegate
        self.__event_loop = event_loop

        self.wants_mouse_events = True

        self.__update_layout_handle = None
        self.__update_layout_handle_lock = threading.RLock()

        self.__closing_lock = threading.RLock()
        self.__closed = False

        self.__image_zoom = 1.0
        self.__image_position = (0.5, 0.5)
        self.__image_canvas_mode = "fit"

        self.__last_display_values = None
        self.__graphics_changed = False

        # create the child canvas items
        # the background
        # next the zoomable items
        self.__bitmap_canvas_item = CanvasItem.BitmapCanvasItem(background_color="#888" if draw_background else "transparent")
        self.__graphics_canvas_item = GraphicsCanvasItem(get_font_metrics_fn)
        self.__timestamp_canvas_item = CanvasItem.TimestampCanvasItem()
        # put the zoomable items into a composition
        self.__composite_canvas_item = CanvasItem.CanvasItemComposition()
        self.__composite_canvas_item.add_canvas_item(self.__bitmap_canvas_item)
        self.__composite_canvas_item.add_canvas_item(self.__graphics_canvas_item)
        self.__composite_canvas_item.add_canvas_item(self.__timestamp_canvas_item)
        # and put the composition into a scroll area
        self.scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(self.__composite_canvas_item)
        self.scroll_area_canvas_item._constrain_position = False  # temporary until scroll bars are implemented

        def layout_updated(canvas_origin, canvas_size, *, immediate=False):
            self.__update_overlay_canvas_item(canvas_size, immediate=immediate)

        self.scroll_area_canvas_item.on_layout_updated = layout_updated
        # info overlay (scale marker, etc.)
        self.__info_overlay_canvas_item = InfoOverlayCanvasItem()
        # canvas items get added back to front
        if draw_background:
            self.add_canvas_item(CanvasItem.BackgroundCanvasItem())
        self.add_canvas_item(self.scroll_area_canvas_item)
        self.add_canvas_item(self.__info_overlay_canvas_item)

        self.__display_values = None
        self.__data_shape = None
        self.__graphics = list()
        self.__graphic_selection = None

        # used for tracking undo
        self.__undo_command = None

        # used for dragging graphic items
        self.__graphic_drag_items = []
        self.__graphic_drag_item = None
        self.__graphic_part_data = {}
        self.__graphic_drag_indexes = []
        self.__last_mouse = None
        self.__is_dragging = False
        self.__mouse_in = False

        # frame rate and latency
        self.__display_frame_rate_id = None
        self.__display_frame_rate_last_index = 0
        self.__display_latency = False

    def close(self):
        with self.__closing_lock:
            with self.__update_layout_handle_lock:
                update_layout_handle = self.__update_layout_handle
                if update_layout_handle:
                    update_layout_handle.cancel()
                    self.__update_layout_handle = None
            self.__closed = True
        super().close()

    @property
    def default_aspect_ratio(self):
        return 1.0

    @property
    def _info_overlay_canvas_item_for_test(self):
        return self.__info_overlay_canvas_item

    def display_inserted(self, display, index):
        pass

    def display_removed(self, display, index):
        pass

    def display_rgba_changed(self, display, display_values):
        # when the display rgba data changes, update the display.
        self.update_display_values(display, display_values)

    def display_data_and_metadata_changed(self, display, display_values):
        # when the data changes, no need to do anything. waits for the display rgba to change instead.
        pass

    def update_display_values(self, display, display_values):
        # threadsafe
        data_and_metadata = display.data_and_metadata_for_display_panel
        if data_and_metadata:
            displayed_dimensional_calibrations = display.displayed_dimensional_calibrations
            if len(displayed_dimensional_calibrations) == 0:
                dimensional_calibration = Calibration.Calibration()
            elif len(displayed_dimensional_calibrations) == 1:
                dimensional_calibration = displayed_dimensional_calibrations[0]
            else:
                if data_and_metadata:
                    datum_dimensions = data_and_metadata.datum_dimension_indexes
                    collection_dimensions = data_and_metadata.collection_dimension_indexes
                    if len(collection_dimensions) > 0:
                        dimensional_calibration = data_and_metadata.dimensional_calibrations[collection_dimensions[-1]]
                    elif len(datum_dimensions) > 0:
                        dimensional_calibration = data_and_metadata.dimensional_calibrations[datum_dimensions[-1]]
                    else:
                        dimensional_calibration = Calibration.Calibration()
                else:
                    dimensional_calibration = Calibration.Calibration()

            data_shape = display.preview_2d_shape
            metadata = data_and_metadata.metadata

            # this method may trigger a layout of its parent scroll area. however, the parent scroll
            # area may already be closed. this is a stop-gap guess at a solution - the basic idea being
            # that this object is not closeable while this method is running; and this method should not
            # run if the object is already closed.
            with self.__closing_lock:
                if self.__closed:
                    return

                if self.__image_zoom != display.image_zoom or self.__image_position != display.image_position or self.__image_canvas_mode != display.image_canvas_mode:
                    if display.image_zoom is not None:
                        self.__image_zoom = display.image_zoom
                    if display.image_position is not None:
                        self.__image_position = display.image_position
                    if display.image_canvas_mode is not None:
                        self.__image_canvas_mode = display.image_canvas_mode

                # setting the bitmap on the bitmap_canvas_item is delayed until paint, so that it happens on a thread, since it may be time consuming
                self.__info_overlay_canvas_item.set_data_info(data_shape, dimensional_calibration, metadata)
                # if the data changes, update the display.
                if display_values is not self.__display_values or self.__graphics_changed:
                    self.__graphics_changed = False
                    self.__display_values = display_values
                    self.__data_shape = data_shape
                    if self.__display_frame_rate_id:
                        frame_index = metadata.get("hardware_source", dict()).get("frame_index", 0)
                        if frame_index != self.__display_frame_rate_last_index:
                            Utility.fps_tick("frame_"+self.__display_frame_rate_id)
                            self.__display_frame_rate_last_index = frame_index
                        if id(self.__display_values) != id(self.__last_display_values):
                            Utility.fps_tick("update_"+self.__display_frame_rate_id)
                            self.__last_display_values = self.__display_values
                    # update the cursor info
                    self.__update_cursor_info()

                    def update_layout():
                        # layout. this makes sure that the info overlay gets updated too.
                        with self.update_context():
                            self.__update_image_canvas_size()
                            # trigger updates
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
                                image_canvas_origin, image_canvas_size = calculate_origin_and_size(scroll_area_canvas_size, self.__data_shape, self.__image_canvas_mode, self.__image_zoom, self.__image_position)
                                if image_canvas_origin != self.__composite_canvas_item.canvas_origin or image_canvas_size != self.__composite_canvas_item.canvas_size:
                                    self.__update_layout_handle = self.__event_loop.call_soon_threadsafe(update_layout)
                                else:
                                    # trigger updates
                                    self.__bitmap_canvas_item.update()
                                    with self.__update_layout_handle_lock:
                                        update_layout_handle = self.__update_layout_handle
                                        if update_layout_handle:
                                            update_layout_handle.cancel()
                                        self.__update_layout_handle = None

    def update_regions(self, display, graphic_selection):
        self.__graphics = copy.copy(display.graphics)
        self.__graphic_selection = copy.copy(graphic_selection)
        self.__graphics_canvas_item.update_graphics(display.preview_2d_shape, self.__graphics, self.__graphic_selection)
        self.__graphics_changed = True

    def handle_auto_display(self, display) -> bool:
        # enter key has been pressed
        display.auto_display_limits()
        return True

    def __update_image_canvas_zoom(self, new_image_zoom):
        if self.__data_shape is not None:
            self.__image_canvas_mode = "custom"
            self.__image_zoom = new_image_zoom
            self.__update_image_canvas_size()

    # update the image canvas position by the widget delta amount
    def __update_image_canvas_position(self, widget_delta):
        if self.__data_shape is not None:
            # create a widget mapping to get from image norm to widget coordinates and back
            widget_mapping = ImageCanvasItemMapping(self.__data_shape, (0, 0), self.__composite_canvas_item.canvas_size)
            # figure out what composite canvas point lies at the center of the scroll area.
            last_widget_center = widget_mapping.map_point_image_norm_to_widget(self.__image_position)
            # determine what new point will lie at the center of the scroll area by adding delta
            new_widget_center = (last_widget_center[0] + widget_delta[0], last_widget_center[1] + widget_delta[1])
            # map back to image norm coordinates
            new_image_norm_center = widget_mapping.map_point_widget_to_image_norm(new_widget_center)
            # ensure that at least half of the image is always visible
            new_image_norm_center_0 = max(min(new_image_norm_center[0], 1.0), 0.0)
            new_image_norm_center_1 = max(min(new_image_norm_center[1], 1.0), 0.0)
            # save the new image norm center
            self.delegate.update_display_properties({"image_position": list(self.__image_position), "image_canvas_mode": "custom"})
            self.__image_position = (new_image_norm_center_0, new_image_norm_center_1)
            # and update the image canvas accordingly
            self.__image_canvas_mode = "custom"
            self.__update_image_canvas_size()

    # update the image canvas origin and size
    def __update_overlay_canvas_item(self, scroll_area_canvas_size, *, immediate=False):
        image_canvas_origin, image_canvas_size = calculate_origin_and_size(scroll_area_canvas_size, self.__data_shape, self.__image_canvas_mode, self.__image_zoom, self.__image_position)
        if image_canvas_origin is None or image_canvas_size is None:
            self.__info_overlay_canvas_item.image_canvas_origin = None
            self.__info_overlay_canvas_item.image_canvas_size = None
        else:
            self.__composite_canvas_item.update_layout(image_canvas_origin, image_canvas_size, immediate=immediate)
            self.__info_overlay_canvas_item.image_canvas_origin = image_canvas_origin
            self.__info_overlay_canvas_item.image_canvas_size = image_canvas_size

    def __update_image_canvas_size(self):
        scroll_area_canvas_size = self.scroll_area_canvas_item.canvas_size
        if scroll_area_canvas_size is not None:
            self.__update_overlay_canvas_item(scroll_area_canvas_size)
            self.__composite_canvas_item.update()

    def mouse_clicked(self, x, y, modifiers):
        if super().mouse_clicked(x, y, modifiers):
            return True
        # now let the image panel handle mouse clicking if desired
        image_position = self.__get_mouse_mapping().map_point_widget_to_image((y, x))
        return self.delegate.image_clicked(image_position, modifiers)

    def mouse_double_clicked(self, x, y, modifiers):
        self.set_fit_mode()
        return True

    def mouse_pressed(self, x, y, modifiers):
        if super().mouse_pressed(x, y, modifiers):
            return True
        if self.__data_shape is None:
            return False
        image_position = self.__get_mouse_mapping().map_point_widget_to_image((y, x))
        if self.delegate.image_mouse_pressed(image_position, modifiers):
            return True
        self.__undo_command = None
        self.delegate.begin_mouse_tracking()
        # figure out clicked graphic
        self.__graphic_drag_items = []
        self.__graphic_drag_item = None
        self.graphic_drag_item_was_selected = False
        self.__graphic_part_data = {}
        self.__graphic_drag_indexes = []
        if self.delegate.tool_mode == "pointer":
            graphics = self.__graphics
            selection_indexes = self.__graphic_selection.indexes
            start_drag_pos = Geometry.IntPoint(y=y, x=x)
            multiple_items_selected = len(selection_indexes) > 1
            widget_mapping = self.__get_mouse_mapping()
            part_specs = list()
            specific_part_spec = None
            # the graphics are drawn in order, which means the graphics with the higher index are "on top" of the
            # graphics with the lower index. but priority should also be given to selected graphics. so sort the
            # graphics according to whether they are selected or not (selected ones go later), then by their index.
            for graphic_index, graphic in sorted(enumerate(graphics), key=lambda ig: (ig[0] in selection_indexes, ig[0])):
                if isinstance(graphic, (Graphics.PointTypeGraphic, Graphics.LineTypeGraphic, Graphics.RectangleTypeGraphic, Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                    already_selected = graphic_index in selection_indexes
                    move_only = not already_selected or multiple_items_selected
                    try:
                        part, specific = graphic.test(widget_mapping, self.__get_font_metrics_fn, start_drag_pos, move_only)
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
                part = part if specific_part_spec is not None else "all"
                # select item and prepare for drag
                self.graphic_drag_item_was_selected = already_selected
                if not self.graphic_drag_item_was_selected:
                    if modifiers.control:
                        self.delegate.add_index_to_selection(graphic_index)
                        selection_indexes.add(graphic_index)
                    elif not already_selected:
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
            if not self.__graphic_drag_items and not modifiers.control:
                self.delegate.clear_selection()
        elif self.delegate.tool_mode == "line":
            widget_mapping = self.__get_mouse_mapping()
            pos = widget_mapping.map_point_widget_to_image_norm(Geometry.FloatPoint(y, x))
            graphic = self.delegate.create_line(pos)
            self.delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                start_drag_pos = Geometry.IntPoint(y=y, x=x)
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
                self.__undo_command = self.delegate.create_insert_graphics_command([graphic])
        elif self.delegate.tool_mode == "rectangle":
            widget_mapping = self.__get_mouse_mapping()
            pos = widget_mapping.map_point_widget_to_image_norm(Geometry.FloatPoint(y, x))
            graphic = self.delegate.create_rectangle(pos)
            self.delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                start_drag_pos = Geometry.IntPoint(y=y, x=x)
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
                self.__undo_command = self.delegate.create_insert_graphics_command([graphic])
        elif self.delegate.tool_mode == "ellipse":
            widget_mapping = self.__get_mouse_mapping()
            pos = widget_mapping.map_point_widget_to_image_norm(Geometry.FloatPoint(y, x))
            graphic = self.delegate.create_ellipse(pos)
            self.delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                start_drag_pos = Geometry.IntPoint(y=y, x=x)
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
                self.__undo_command = self.delegate.create_insert_graphics_command([graphic])
        elif self.delegate.tool_mode == "point":
            widget_mapping = self.__get_mouse_mapping()
            pos = widget_mapping.map_point_widget_to_image_norm(Geometry.FloatPoint(y, x))
            graphic = self.delegate.create_point(pos)
            self.delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                start_drag_pos = Geometry.IntPoint(y=y, x=x)
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
                self.__undo_command = self.delegate.create_insert_graphics_command([graphic])
        elif self.delegate.tool_mode == "line-profile":
            widget_mapping = self.__get_mouse_mapping()
            pos = widget_mapping.map_point_widget_to_image_norm(Geometry.FloatPoint(y, x))
            graphic = self.delegate.create_line_profile(pos)
            self.delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                start_drag_pos = Geometry.IntPoint(y=y, x=x)
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
                self.__undo_command = self.delegate.create_insert_graphics_command([graphic])
        elif self.delegate.tool_mode == "spot":
            widget_mapping = self.__get_mouse_mapping()
            pos = widget_mapping.map_point_widget_to_image_norm(Geometry.FloatPoint(y, x))
            graphic = self.delegate.create_spot(pos)
            self.delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                start_drag_pos = Geometry.IntPoint(y=y, x=x)
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
                self.__undo_command = self.delegate.create_insert_graphics_command([graphic])
        elif self.delegate.tool_mode == "wedge":
            widget_mapping = self.__get_mouse_mapping()
            pos = widget_mapping.map_point_widget_to_image_norm(Geometry.FloatPoint(y, x))
            mouse_angle = math.pi - math.atan2(0.5 - pos[0], 0.5 - pos[1])
            graphic = self.delegate.create_wedge(mouse_angle)
            self.delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                start_drag_pos = Geometry.IntPoint(y=y, x=x)
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
                self.__undo_command = self.delegate.create_insert_graphics_command([graphic])
        elif self.delegate.tool_mode == "ring":
            widget_mapping = self.__get_mouse_mapping()
            pos = widget_mapping.map_point_widget_to_image_norm(Geometry.FloatPoint(y, x))
            radius = math.sqrt((pos[0] - 0.5) ** 2 + (pos[1] - 0.5) ** 2)
            graphic = self.delegate.create_ring(radius)
            self.delegate.add_index_to_selection(self.__graphics.index(graphic))
            if graphic:
                # setup drag
                start_drag_pos = Geometry.IntPoint(y=y, x=x)
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
                self.__undo_command = self.delegate.create_insert_graphics_command([graphic])
        elif self.delegate.tool_mode == "hand":
            self.__start_drag_pos = (y, x)
            self.__last_drag_pos = (y, x)
            self.__is_dragging = True
        return True

    def mouse_released(self, x, y, modifiers):
        if super().mouse_released(x, y, modifiers):
            return True
        image_position = self.__get_mouse_mapping().map_point_widget_to_image((y, x))
        if self.delegate.image_mouse_released(image_position, modifiers):
            return True
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
            self.delegate.end_mouse_tracking(self.__undo_command)
        self.__graphic_drag_items = []
        self.__graphic_drag_item = None
        self.__graphic_part_data = {}
        self.__graphic_drag_indexes = []
        self.__start_drag_pos = None
        self.__last_drag_pos = None
        self.__is_dragging = False
        if self.delegate.tool_mode != "hand":
            self.delegate.tool_mode = "pointer"
        return True

    def mouse_entered(self):
        if super().mouse_entered():
            return True
        self.__mouse_in = True
        return True

    def mouse_exited(self):
        if super().mouse_exited():
            return True
        self.__mouse_in = False
        if self.delegate:  # allow display to work without delegate
            # whenever the cursor exits, clear the cursor display
            self.delegate.cursor_changed(None)
        return True

    def mouse_position_changed(self, x, y, modifiers):
        if super().mouse_position_changed(x, y, modifiers):
            return True
        image_position = self.__get_mouse_mapping().map_point_widget_to_image((y, x))
        if self.delegate.image_mouse_position_changed(image_position, modifiers):
            return True
        if self.delegate.tool_mode == "pointer":
            self.cursor_shape = "arrow"
        elif self.delegate.tool_mode == "line":
            self.cursor_shape = "cross"
        elif self.delegate.tool_mode == "rectangle":
            self.cursor_shape = "cross"
        elif self.delegate.tool_mode == "ellipse":
            self.cursor_shape = "cross"
        elif self.delegate.tool_mode == "point":
            self.cursor_shape = "cross"
        elif self.delegate.tool_mode == "line-profile":
            self.cursor_shape = "cross"
        elif self.delegate.tool_mode == "spot":
            self.cursor_shape = "cross"
        elif self.delegate.tool_mode == "wedge":
            self.cursor_shape = "cross"
        elif self.delegate.tool_mode == "ring":
            self.cursor_shape = "cross"
        elif self.delegate.tool_mode == "hand":
            self.cursor_shape = "hand"
        # x,y already have transform applied
        self.__last_mouse = Geometry.IntPoint(x=x, y=y)
        self.__update_cursor_info()
        if self.__graphic_drag_items:
            if not self.__undo_command:
                self.__undo_command = self.delegate.create_change_graphics_command()
            force_drag = modifiers.only_option
            if force_drag and self.__graphic_drag_part == "all":
                if Geometry.distance(self.__last_mouse, self.__graphic_drag_start_pos) <= 2:
                    self.delegate.drag_graphics(self.__graphic_drag_items)
                    return True
            widget_mapping = self.__get_mouse_mapping()
            self.delegate.update_graphics(widget_mapping, self.__graphic_drag_items, self.__graphic_drag_part,
                                          self.__graphic_part_data, self.__graphic_drag_start_pos,
                                          Geometry.FloatPoint(y=y, x=x), modifiers)
            self.__graphic_drag_changed = True
        elif self.__is_dragging:
            if not self.__undo_command:
                self.__undo_command = self.delegate.create_change_display_command()
            delta = (y - self.__last_drag_pos[0], x - self.__last_drag_pos[1])
            self.__update_image_canvas_position((-delta[0], -delta[1]))
            self.__last_drag_pos = (y, x)
        return True

    def wheel_changed(self, x, y, dx, dy, is_horizontal):
        if self.__mouse_in:
            dx = dx if is_horizontal else 0.0
            dy = dy if not is_horizontal else 0.0
            command = self.delegate.create_change_display_command(command_id="image_position", is_mergeable=True)
            self.__update_image_canvas_position((-dy, -dx))
            self.delegate.push_undo_command(command)
            return True
        return False

    def pan_gesture(self, dx, dy):
        self.__update_image_canvas_position((dy, dx))
        return True

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
        if self.__data_shape is not None:
            if self.__graphic_selection.has_selection:
                if key.is_arrow:
                    widget_mapping = self.__get_mouse_mapping()
                    amount = 10.0 if key.modifiers.shift else 1.0
                    if key.is_left_arrow:
                        self.delegate.nudge_selected_graphics(widget_mapping, Geometry.FloatPoint(y=0, x=-amount))
                    elif key.is_up_arrow:
                        self.delegate.nudge_selected_graphics(widget_mapping, Geometry.FloatPoint(y=-amount, x=0))
                    elif key.is_right_arrow:
                        self.delegate.nudge_selected_graphics(widget_mapping, Geometry.FloatPoint(y=0, x=amount))
                    elif key.is_down_arrow:
                        self.delegate.nudge_selected_graphics(widget_mapping, Geometry.FloatPoint(y=amount, x=0))
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
            if key.text == "+" or key.text == "=":
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
            if key.text == "2":
                self.set_two_to_one_mode()
                return True
            if key.text == "0":
                self.set_fit_mode()
                return True
            if key.text == ")":
                self.set_fill_mode()
                return True
            if key.key == 70 and key.modifiers.shift and key.modifiers.alt:
                if self.__display_frame_rate_id is None:
                    self.__display_frame_rate_id = str(id(self))
                else:
                    self.__display_frame_rate_id = None
                return True
            if key.key == 76 and key.modifiers.shift and key.modifiers.alt:
                self.__display_latency = not self.__display_latency
                return True
        return False

    def __get_mouse_mapping(self):
        return ImageCanvasItemMapping(self.__data_shape, self.__composite_canvas_item.canvas_origin, self.__composite_canvas_item.canvas_size)

    # map from widget coordinates to image coordinates
    def map_widget_to_image(self, p):
        image_size = self.__data_shape
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
        image_size = self.__data_shape
        if image_size:
            return p[0] * image_size[0], p[1] * image_size[1]
        return None

    def __update_cursor_info(self):
        if not self.delegate:  # allow display to work without delegate
            return
        image_size = self.__data_shape
        if self.__mouse_in and self.__last_mouse:
            pos_2d = None
            if image_size and len(image_size) > 1:
                pos_2d = self.map_widget_to_image(self.__last_mouse)
            self.delegate.cursor_changed(pos_2d)

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

            rect = self.canvas_bounds

            drawing_context.save()
            try:
                font = "normal 11px serif"
                text_pos = Geometry.IntPoint(y=rect[0][1], x=rect[0][0])
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
                drawing_context.statistics("display")
            finally:
                drawing_context.restore()

    # this method will be invoked from the paint thread.
    # data is calculated and then sent to the image canvas item.
    def prepare_display(self):
        if self.__data_shape is not None:
            # configure the bitmap canvas item
            display_values = self.__display_values
            display_data = display_values.display_data_and_metadata
            if display_data and display_data.data.dtype == numpy.float32:
                display_range = display_values.display_range
                color_map_data = display_values.color_map_data
                display_values.finalize()
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
                if False:
                    # the next section does gaussian blur for image decimation in the case where the destination rectangle
                    # is smaller than the source. this results in lower performance, but higher quality display.
                    height_ratio = (self.__bitmap_canvas_item.canvas_size.height / data_rgba.shape[0]) if data_rgba is not None and data_rgba.shape[0] > 0 else 1
                    if height_ratio < 1:
                        sigma = 0.5 * ((1.0 / height_ratio) - 1.0)
                        data_rgba_copy = numpy.empty_like(data_rgba)
                        data_rgba_u8_view = data_rgba.view(numpy.uint8).reshape(data_rgba.shape + (-1, ))
                        data_rgba_u8_copy_view = data_rgba_copy.view(numpy.uint8).reshape(data_rgba_copy.shape + (-1, ))
                        data_rgba_u8_copy_view[..., 0] = scipy.ndimage.gaussian_filter(data_rgba_u8_view[..., 0], sigma=sigma)
                        data_rgba_u8_copy_view[..., 1] = scipy.ndimage.gaussian_filter(data_rgba_u8_view[..., 1], sigma=sigma)
                        data_rgba_u8_copy_view[..., 2] = scipy.ndimage.gaussian_filter(data_rgba_u8_view[..., 2], sigma=sigma)
                        if data_rgba_u8_view.shape[-1] == 4:
                            data_rgba_u8_copy_view[..., 3] = data_rgba_u8_view[..., 3]
                        data_rgba = data_rgba_copy
                self.__bitmap_canvas_item.set_rgba_bitmap_data(data_rgba, trigger_update=False)
            self.__timestamp_canvas_item.timestamp = display_values.display_rgba_timestamp if self.__display_latency else None

    @property
    def image_canvas_mode(self):
        return self.__image_canvas_mode

    def __apply_display_properties_command(self, display_properties: typing.Mapping):
        command = self.delegate.create_change_display_command()
        self.delegate.update_display_properties(display_properties)
        self.delegate.push_undo_command(command)

    def __apply_move_command(self, delta):
        command = self.delegate.create_change_display_command(command_id="image_nudge", is_mergeable=True)
        self.__update_image_canvas_position(delta)
        self.delegate.push_undo_command(command)

    def set_fit_mode(self):
        self.__apply_display_properties_command({"image_zoom": 1.0, "image_position": (0.5, 0.5), "image_canvas_mode": "fit"})

    def set_fill_mode(self):
        self.__apply_display_properties_command({"image_zoom": 1.0, "image_position": (0.5, 0.5), "image_canvas_mode": "fill"})

    def set_one_to_one_mode(self):
        self.__apply_display_properties_command({"image_zoom": 1.0, "image_position": (0.5, 0.5), "image_canvas_mode": "1:1"})

    def set_two_to_one_mode(self):
        self.__apply_display_properties_command({"image_zoom": 0.5, "image_position": (0.5, 0.5), "image_canvas_mode": "2:1"})

    def zoom_in(self):
        self.__apply_display_properties_command({"image_zoom": self.__image_zoom * 1.25, "image_canvas_mode": "custom"})

    def zoom_out(self):
        self.__apply_display_properties_command({"image_zoom": self.__image_zoom / 1.25, "image_canvas_mode": "custom"})

    def move_left(self, amount=10.0):
        self.__apply_move_command((0.0, amount))

    def move_right(self, amount=10.0):
        self.__apply_move_command((0.0, -amount))

    def move_up(self, amount=10.0):
        self.__apply_move_command((amount, 0.0))

    def move_down(self, amount=10.0):
        self.__apply_move_command((-amount, 0.0))
