from __future__ import annotations

# standard libraries
import asyncio
import concurrent.futures
import copy
import dataclasses
import logging
import math
import threading
import time
import typing
import uuid

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
from nion.utils import Model
from nion.utils import Registry
from nion.utils import Stream
from nion.utils import ReferenceCounting

if typing.TYPE_CHECKING:
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


class GraphicsCanvasItemComposer(CanvasItem.BaseComposer):
    def __init__(self, canvas_item: CanvasItem.AbstractCanvasItem, layout_sizing: CanvasItem.Sizing, cache: CanvasItem.ComposerCache,
                 ui_settings: UISettings.UISettings, graphics: typing.List[Graphics.Graphic], graphic_selection: DisplayItem.GraphicSelection,
                 displayed_shape: typing.Optional[DataAndMetadata.ShapeType], coordinate_system: typing.List[Calibration.Calibration],
                 is_focused: bool) -> None:
        super().__init__(canvas_item, layout_sizing, cache)
        self.__ui_settings = ui_settings
        self.__graphics = graphics
        self.__graphic_selection = graphic_selection
        self.__displayed_shape = displayed_shape
        self.__coordinate_system = coordinate_system
        self.__is_focused = is_focused

    def _repaint(self, drawing_context: DrawingContext.DrawingContext, canvas_bounds: Geometry.IntRect, composer_cache: CanvasItem.ComposerCache) -> None:
        ui_settings = self.__ui_settings
        graphics = self.__graphics
        graphic_selection = self.__graphic_selection
        displayed_shape = self.__displayed_shape
        coordinate_system = self.__coordinate_system
        is_focused = self.__is_focused
        widget_mapping = ImageCanvasItemMapping.make(displayed_shape, canvas_bounds, coordinate_system)
        if graphics and widget_mapping:
            with drawing_context.saver():
                drawing_context.translate(canvas_bounds.left, canvas_bounds.top)
                for graphic_index, graphic in enumerate(graphics):
                    if graphic.has_attribute(Graphics.GraphicAttributeEnum.TWO_DIMENSIONAL):
                        try:
                            graphic.draw(drawing_context, ui_settings, widget_mapping, graphic_selection.contains(graphic_index), is_focused)
                        except Exception as e:
                            import traceback
                            logging.debug("Graphic Repaint Error: %s", e)
                            traceback.print_exc()
                            traceback.print_stack()


class GraphicsCanvasItem(CanvasItem.AbstractCanvasItem):
    """A canvas item to paint the graphic items on the image.

    Callers should call update_graphics when the graphics changes.
    """

    def __init__(self, ui_settings: UISettings.UISettings) -> None:
        super().__init__()
        self.__ui_settings = ui_settings
        self.__displayed_shape: typing.Optional[DataAndMetadata.ShapeType] = None
        self.__graphics: typing.List[Graphics.Graphic] = list()
        self.__graphics_for_compare: list[tuple[uuid.UUID, int]] = list()
        self.__graphic_selection = DisplayItem.GraphicSelection()
        self.__coordinate_system: typing.List[Calibration.Calibration] = list()
        self.__is_focused = False

    @property
    def is_focused(self) -> bool:
        return self.__is_focused

    @is_focused.setter
    def is_focused(self, value: bool) -> None:
        self.__is_focused = value
        self.update()

    def update_coordinate_system(self, displayed_shape: typing.Optional[DataAndMetadata.ShapeType], coordinate_system: typing.Sequence[Calibration.Calibration], graphics: typing.Sequence[Graphics.Graphic], graphic_selection: DisplayItem.GraphicSelection) -> None:
        needs_update = False
        if coordinate_system != self.__coordinate_system:
            self.__coordinate_system = list(coordinate_system)
            needs_update = True
        if displayed_shape is None or len(displayed_shape) != 2:
            displayed_shape = None
            graphics = list()
            graphic_selection = DisplayItem.GraphicSelection()
        assert displayed_shape is None or len(displayed_shape) == 2
        if ((self.__displayed_shape is None) != (displayed_shape is None)) or (self.__displayed_shape != displayed_shape):
            self.__displayed_shape = displayed_shape
            needs_update = True
        graphics_for_compare = [(graphic.uuid, graphic.modified_count) for graphic in graphics]
        if graphics_for_compare != self.__graphics_for_compare:
            self.__graphics = list(graphics)
            self.__graphics_for_compare = graphics_for_compare
            needs_update = True
        if self.__graphic_selection != graphic_selection:
            self.__graphic_selection = graphic_selection
            needs_update = True
        if needs_update:
            self.update()

    def _get_composer(self, composer_cache: CanvasItem.ComposerCache) -> typing.Optional[CanvasItem.BaseComposer]:
        return GraphicsCanvasItemComposer(self, self.sizing, composer_cache, self.__ui_settings, self.__graphics, self.__graphic_selection, self.__displayed_shape, self.__coordinate_system, self.__is_focused)


class ScaleMarkerCanvasItemComposer(CanvasItem.BaseComposer):
    def __init__(self, canvas_item: CanvasItem.AbstractCanvasItem, layout_sizing: CanvasItem.Sizing,
                 cache: CanvasItem.ComposerCache, dimensional_calibration: typing.Optional[Calibration.Calibration],
                 info_text: str, screen_pixel_per_image_pixel: typing.Optional[float],
                 get_font_metrics_fn: typing.Callable[[str, str], UISettings.FontMetrics]) -> None:
        super().__init__(canvas_item, layout_sizing, cache)
        self.__dimensional_calibration = dimensional_calibration
        self.__info_text = info_text
        self.__screen_pixel_per_image_pixel = screen_pixel_per_image_pixel
        self.__get_font_metrics_fn = get_font_metrics_fn

    def _repaint(self, drawing_context: DrawingContext.DrawingContext, canvas_bounds: Geometry.IntRect, composer_cache: CanvasItem.ComposerCache) -> None:
        dimensional_calibration = self.__dimensional_calibration
        info_text = self.__info_text
        screen_pixel_per_image_pixel = self.__screen_pixel_per_image_pixel
        scale_marker_width = max(16, min(round(canvas_bounds.width * 0.8), 120))
        scale_marker_height = 6
        scale_marker_font = "normal 14px serif"
        get_font_metrics_fn = self.__get_font_metrics_fn
        if dimensional_calibration:  # display scale marker?
            with drawing_context.saver():
                drawing_context.translate(canvas_bounds.left, canvas_bounds.top)
                if screen_pixel_per_image_pixel and screen_pixel_per_image_pixel > 0.0:
                    scale_marker_image_width = scale_marker_width / screen_pixel_per_image_pixel
                    calibrated_scale_marker_width = Geometry.make_pretty2(scale_marker_image_width * dimensional_calibration.scale, True)
                    # update the scale marker width
                    scale_marker_image_width = calibrated_scale_marker_width / dimensional_calibration.scale
                    scale_marker_calculated_width = scale_marker_image_width * screen_pixel_per_image_pixel
                    baseline = canvas_bounds.height
                    drawing_context.begin_path()
                    drawing_context.move_to(0, baseline)
                    drawing_context.line_to(0 + scale_marker_calculated_width, baseline)
                    drawing_context.line_to(0 + scale_marker_calculated_width, baseline - scale_marker_height)
                    drawing_context.line_to(0, baseline - scale_marker_height)
                    drawing_context.close_path()
                    drawing_context.fill_style = "#448"
                    drawing_context.fill()
                    drawing_context.stroke_style = "#000"
                    drawing_context.stroke()
                    drawing_context.font = scale_marker_font
                    drawing_context.text_baseline = "bottom"
                    drawing_context.fill_style = "#FFF"
                    text1 = dimensional_calibration.convert_to_calibrated_size_str(scale_marker_image_width)
                    text2 = info_text
                    fm1 = get_font_metrics_fn(scale_marker_font, text1)
                    drawing_context.fill_text(text1, 0, baseline - scale_marker_height - 4)
                    drawing_context.fill_text(text2, 0, baseline - scale_marker_height - 4 - fm1.height)


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
        self.__scale_marker_width = 0

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
        height = self.scale_marker_height + 4 + 2 * self.__get_font_metrics_fn(self.scale_marker_font, "MMM").height
        scale_marker_width = 0
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
        self.__scale_marker_width = scale_marker_width
        new_sizing = self.copy_sizing()
        new_sizing = new_sizing.with_unconstrained_width()
        new_sizing = new_sizing.with_fixed_height(height)
        self.update_sizing(new_sizing)
        self.update()

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

    def _get_composer(self, composer_cache: CanvasItem.ComposerCache) -> typing.Optional[CanvasItem.BaseComposer]:
        return ScaleMarkerCanvasItemComposer(self, self.sizing, composer_cache, self.__dimensional_calibration, self.__info_text, self.__screen_pixel_per_image_pixel_stream.value, self.__get_font_metrics_fn)


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


class ImageAreaCanvasItemLayout(CanvasItem.CanvasItemLayout):
    def __init__(self, data_shape: typing.Optional[DataAndMetadata.Shape2dType] = None, image_zoom: float = 1.0, image_position: Geometry.FloatPoint = Geometry.FloatPoint(0.5, 0.5), image_canvas_mode: str = "fit") -> None:
        super().__init__()
        self.__data_shape: typing.Optional[DataAndMetadata.Shape2dType] = data_shape
        self.__image_zoom = image_zoom
        self.__image_position = image_position
        self.__image_canvas_mode = image_canvas_mode

    def copy(self) -> ImageAreaCanvasItemLayout:
        return ImageAreaCanvasItemLayout(self.__data_shape, self.__image_zoom, self.__image_position, self.__image_canvas_mode)

    @property
    def data_shape(self) -> typing.Optional[DataAndMetadata.Shape2dType]:
        return self.__data_shape

    @data_shape.setter
    def data_shape(self, value: typing.Optional[DataAndMetadata.Shape2dType]) -> None:
        self.__data_shape = value

    @property
    def image_zoom(self) -> float:
        return self.__image_zoom

    @image_zoom.setter
    def image_zoom(self, value: float) -> None:
        self.__image_zoom = value

    @property
    def image_position(self) -> Geometry.FloatPoint:
        return self.__image_position

    @image_position.setter
    def image_position(self, value: Geometry.FloatPoint) -> None:
        self.__image_position = value

    @property
    def image_canvas_mode(self) -> str:
        return self.__image_canvas_mode

    @image_canvas_mode.setter
    def image_canvas_mode(self, value: str) -> None:
        self.__image_canvas_mode = value

    def layout(self, canvas_origin: Geometry.IntPoint, canvas_size: Geometry.IntSize, canvas_items: typing.Sequence[CanvasItem.LayoutItem], *, immediate: bool = False) -> None:
        content = canvas_items[0] if canvas_items else None
        if content:
            if not content._has_layout:
                # if the content has not layout yet, always update it.
                self.update_canvas_item_layout(canvas_origin, canvas_size, content)
            if canvas_size:
                widget_mapping = ImageCanvasItemMapping.make(self.__data_shape, Geometry.IntRect(canvas_origin, canvas_size), list())
                if widget_mapping:
                    image_canvas_rect = calculate_origin_and_size(canvas_size, widget_mapping.data_shape, self.__image_canvas_mode, self.__image_zoom, self.__image_position)
                    content.update_layout(image_canvas_rect.origin, image_canvas_rect.size)


class ImageAreaCompositeCanvasItem(CanvasItem.CanvasItemComposition):
    """A composite canvas item that will hold the bitmap and graphics canvas item.

    Also handles the screen pixel per image pixel stream, used for the scale marker.
    """

    def __init__(self) -> None:
        super().__init__()
        self.__data_shape: typing.Optional[DataAndMetadata.Shape2dType] = None
        self.__lock = threading.RLock()
        self.screen_pixel_per_image_pixel_stream = Stream.ValueStream(0.0)
        self.__listener = self._canvas_size_stream.value_stream.listen(ReferenceCounting.weak_partial(ImageAreaCompositeCanvasItem.__on_canvas_size_changed, self))

    def __on_canvas_size_changed(self, canvas_size: typing.Optional[Geometry.IntSize]) -> None:
        self.__update_screen_pixel_per_image()

    @property
    def _data_shape(self) -> typing.Optional[DataAndMetadata.Shape2dType]:
        return self.__data_shape

    @_data_shape.setter
    def _data_shape(self, value: typing.Optional[DataAndMetadata.Shape2dType]) -> None:
        if self.__data_shape != value:
            self.__data_shape = value
            self.__update_screen_pixel_per_image()
            self.update()

    def __update_screen_pixel_per_image(self) -> None:
        screen_pixel_per_image_pixel = 0.0
        widget_mapping = ImageCanvasItemMapping.make(self._data_shape, self.canvas_rect, list())
        if widget_mapping:
            data_shape = widget_mapping.data_shape
            screen_pixel_per_image_pixel = widget_mapping.map_size_image_norm_to_widget(Geometry.FloatSize(1, 1)).height / data_shape[0]
        # until threading is cleaned up, this is a hack to avoid setting the value from two different threads at once.
        with self.__lock:
            self.screen_pixel_per_image_pixel_stream.value = screen_pixel_per_image_pixel


class ImageAreaCanvasItemComposer(CanvasItem.CanvasItemCompositionComposer):
    def __init__(self,
                 canvas_item: CanvasItem.AbstractCanvasItem,
                 layout_sizing: CanvasItem.Sizing,
                 composer_cache: CanvasItem.ComposerCache,
                 layout: CanvasItem.CanvasItemAbstractLayout,
                 child_composers: typing.Sequence[CanvasItem.BaseComposer],
                 background_color: typing.Optional[typing.Union[str, DrawingContext.LinearGradient]],
                 border_color: typing.Optional[str]) -> None:
        super().__init__(canvas_item, layout_sizing, composer_cache, layout, child_composers, background_color, border_color)
        self.__child_composers = child_composers

    def _repaint_children(self, drawing_context: DrawingContext.DrawingContext, canvas_rect: Geometry.IntRect, visible_rect: Geometry.IntRect, child_composers: typing.Sequence[CanvasItem.BaseComposer]) -> None:
        with drawing_context.saver():
            drawing_context.translate(canvas_rect.left, canvas_rect.top)
            drawing_context.clip_rect(0, 0, canvas_rect.width, canvas_rect.height)
            visible_rect = Geometry.IntRect(origin=Geometry.IntPoint(), size=canvas_rect.size)
            child_composer = self.__child_composers[0]
            child_canvas_rect = child_composer._canvas_bounds
            if visible_rect.intersects_rect(child_canvas_rect):
                child_composer.repaint(drawing_context, child_canvas_rect, visible_rect)


class ImageAreaCanvasItem(CanvasItem.CanvasItemComposition):
    def __init__(self, content: CanvasItem.AbstractCanvasItem) -> None:
        super().__init__()
        self.__scroll_area_layout = ImageAreaCanvasItemLayout()
        self.layout = self.__scroll_area_layout
        self.add_canvas_item(content)

    @property
    def _data_shape(self) -> typing.Optional[DataAndMetadata.Shape2dType]:
        return self.__scroll_area_layout.data_shape

    @_data_shape.setter
    def _data_shape(self, value: typing.Optional[DataAndMetadata.Shape2dType]) -> None:
        if self.__scroll_area_layout.data_shape != value:
            self.__scroll_area_layout.data_shape = value
            self.update()

    @property
    def _image_zoom(self) -> float:
        return self.__scroll_area_layout.image_zoom

    @_image_zoom.setter
    def _image_zoom(self, value: float) -> None:
        if self.__scroll_area_layout.image_zoom != value:
            self.__scroll_area_layout.image_zoom = value
            self.update()

    @property
    def _image_position(self) -> Geometry.FloatPoint:
        return self.__scroll_area_layout.image_position

    @_image_position.setter
    def _image_position(self, value: Geometry.FloatPoint) -> None:
        if self.__scroll_area_layout.image_position != value:
            self.__scroll_area_layout.image_position = value
            self.update()

    @property
    def _image_canvas_mode(self) -> str:
        return self.__scroll_area_layout.image_canvas_mode

    @_image_canvas_mode.setter
    def _image_canvas_mode(self, value: str) -> None:
        if self.__scroll_area_layout.image_canvas_mode != value:
            self.__scroll_area_layout.image_canvas_mode = value
            self.update()

    def _get_composition_composer(self, child_composers: typing.Sequence[CanvasItem.BaseComposer], composer_cache: CanvasItem.ComposerCache) -> CanvasItem.BaseComposer:
        return ImageAreaCanvasItemComposer(self, self.layout_sizing, composer_cache, self.__scroll_area_layout.copy(), child_composers, self.background_color, self.border_color)

    def canvas_items_at_point(self, x: int, y: int) -> typing.List[CanvasItem.AbstractCanvasItem]:
        canvas_items: typing.List[CanvasItem.AbstractCanvasItem] = []
        point = Geometry.IntPoint(x=x, y=y)
        content = self.canvas_items[0]
        if content.canvas_rect and content.canvas_rect.contains_point(point):
            content_canvas_origin = content.canvas_origin
            if content_canvas_origin:
                canvas_point = point - content_canvas_origin
                canvas_items.extend(content.canvas_items_at_point(canvas_point.x, canvas_point.y))
        canvas_items.extend(super().canvas_items_at_point(x, y))
        return canvas_items

    def wheel_changed(self, x: int, y: int, dx: int, dy: int, is_horizontal: bool) -> bool:
        canvas_origin = self.canvas_origin
        if canvas_origin:
            x -= canvas_origin.x
            y -= canvas_origin.y
            content = self.canvas_items[0]
            # give the content a chance to handle the wheel changed itself.
            if content.wheel_changed(x, y, dx, dy, is_horizontal):
                return True
            # if the content didn't handle the wheel changed, then scroll the content here.
            dx = dx if is_horizontal else 0
            dy = dy if not is_horizontal else 0
            canvas_rect = content.canvas_rect
            if canvas_rect:
                new_canvas_origin = canvas_rect.origin + Geometry.IntPoint(x=dx, y=dy)
                content.update_layout(new_canvas_origin, canvas_rect.size)
                content.update()
            return True
        return False


class ImageBitmapCanvasItemComposer(CanvasItem.CellCanvasItemComposer):
    def __init__(self, canvas_item: CanvasItem.AbstractCanvasItem, layout_sizing: CanvasItem.Sizing, cache: CanvasItem.ComposerCache, cell: CanvasItem.CellLike, style: typing.Set[str], display_frame_rate_id: typing.Optional[str]) -> None:
        super().__init__(canvas_item, layout_sizing, cache, cell, style)
        self.__display_frame_rate_id = display_frame_rate_id

    def _repaint(self, drawing_context: DrawingContext.DrawingContext, canvas_bounds: Geometry.IntRect, composer_cache: CanvasItem.ComposerCache) -> None:
        super()._repaint(drawing_context, canvas_bounds, composer_cache)
        if self.__display_frame_rate_id:
            Utility.fps_tick("display_" + self.__display_frame_rate_id)



class ImageBitmapCanvasItem(CanvasItem.BitmapCanvasItem):
    def __init__(self, draw_background: bool = True) -> None:
        super().__init__(background_color="#888" if draw_background else "transparent")
        self.__display_frame_rate_id: typing.Optional[str] = None

    @property
    def display_frame_rate_id(self) -> typing.Optional[str]:
        return self.__display_frame_rate_id

    @display_frame_rate_id.setter
    def display_frame_rate_id(self, value: typing.Optional[str]) -> None:
        self.__display_frame_rate_id = value
        self.update()

    def _get_composer(self, composer_cache: CanvasItem.ComposerCache) -> typing.Optional[CanvasItem.BaseComposer]:
        if cell := self.cell:
            return ImageBitmapCanvasItemComposer(self, self.layout_sizing, composer_cache, cell, self.style, self.__display_frame_rate_id)
        return None


MousePositionAndModifiers = typing.Tuple[Geometry.IntPoint, "UserInterface.KeyboardModifiers"]
MouseHandlerReactorFn = typing.Callable[[Stream.ValueChangeStreamReactorInterface[MousePositionAndModifiers]], typing.Coroutine[typing.Any, typing.Any, typing.Any]]


class MouseHandler:
    def __init__(self, image_canvas_item: ImageCanvasItem, event_loop: asyncio.AbstractEventLoop) -> None:
        self.__image_canvas_item = image_canvas_item
        self.__mouse_value_stream = Stream.ValueStream[MousePositionAndModifiers]()
        self.__mouse_value_change_stream = Stream.ValueChangeStream(self.__mouse_value_stream)
        self.__reactor = Stream.ValueChangeStreamReactor[MousePositionAndModifiers](self.__mouse_value_change_stream, self.reactor_loop, event_loop)
        self.cursor_shape = "arrow"

    def mouse_pressed(self, mouse_pos: Geometry.IntPoint, modifiers: UserInterface.KeyboardModifiers) -> None:
        self.__mouse_value_stream.value = mouse_pos, modifiers
        self.__mouse_value_change_stream.begin()

    def mouse_position_changed(self, mouse_pos: Geometry.IntPoint, modifiers: UserInterface.KeyboardModifiers) -> None:
        self.__mouse_value_stream.value = (mouse_pos, modifiers)

    def mouse_released(self, mouse_pos: Geometry.IntPoint, modifiers: UserInterface.KeyboardModifiers) -> None:
        self.__mouse_value_stream.value = mouse_pos, modifiers
        self.__mouse_value_change_stream.end()

    async def reactor_loop(self, r: Stream.ValueChangeStreamReactorInterface[MousePositionAndModifiers]) -> None:
        await self._reactor_loop(r, self.__image_canvas_item)

    async def _reactor_loop(self, r: Stream.ValueChangeStreamReactorInterface[MousePositionAndModifiers], image_canvas_item: ImageCanvasItem) -> None:
        return


class PointerMouseHandler(MouseHandler):
    def __init__(self, image_canvas_item: ImageCanvasItem, event_loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(image_canvas_item, event_loop)
        self.cursor_shape = "arrow"

    async def _reactor_loop(self, r: Stream.ValueChangeStreamReactorInterface[MousePositionAndModifiers], image_canvas_item: ImageCanvasItem) -> None:
        delegate = image_canvas_item.delegate
        assert delegate

        # get the beginning mouse position
        value_change = await r.next_value_change()
        value_change_value = value_change.value
        assert value_change.is_begin
        assert value_change_value is not None

        # preliminary setup for the tracking loop.
        mouse_pos_, modifiers = value_change_value
        mouse_pos = Geometry.FloatPoint(x=mouse_pos_.x, y=mouse_pos_.y)
        widget_mapping = image_canvas_item.mouse_mapping
        assert widget_mapping
        start_drag_pos = mouse_pos

        graphic_drag_items: typing.List[Graphics.Graphic] = list()
        graphic_drag_item: typing.Optional[Graphics.Graphic] = None
        graphic_drag_item_was_selected = False
        graphic_part_data: typing.Dict[int, Graphics.DragPartData] = dict()
        graphic_drag_indexes = set()

        graphics = image_canvas_item.graphics
        selection_indexes = image_canvas_item.graphic_selection.indexes
        multiple_items_selected = len(selection_indexes) > 1
        part_specs: typing.List[typing.Tuple[int, Graphics.Graphic, bool, str]] = list()
        part_spec: typing.Optional[typing.Tuple[int, Graphics.Graphic, bool, str]]
        specific_part_spec: typing.Optional[typing.Tuple[int, Graphics.Graphic, bool, str]] = None
        # the graphics are drawn in order, which means the graphics with the higher index are "on top" of the
        # graphics with the lower index. but priority should also be given to selected graphics. so sort the
        # graphics according to whether they are selected or not (selected ones go later), then by their index.
        for graphic_index, graphic in sorted(enumerate(graphics), key=lambda ig: (ig[0] in selection_indexes, ig[0])):
            if graphic.has_attribute(Graphics.GraphicAttributeEnum.TWO_DIMENSIONAL):
                already_selected = graphic_index in selection_indexes
                move_only = not already_selected or multiple_items_selected
                try:
                    part, specific = graphic.test(widget_mapping, image_canvas_item.ui_settings, start_drag_pos, move_only)
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
        part_spec = specific_part_spec if specific_part_spec is not None else part_specs[-1] if len(part_specs) > 0 else None
        if part_spec is not None:
            graphic_index, graphic, already_selected, part = part_spec
            part = part if specific_part_spec is not None else part_spec[-1]
            # select item and prepare for drag
            graphic_drag_item_was_selected = already_selected
            if not graphic_drag_item_was_selected:
                if modifiers.control:
                    delegate.add_index_to_selection(graphic_index)
                    selection_indexes.add(graphic_index)
                elif not already_selected:
                    delegate.set_selection(graphic_index)
                    selection_indexes.clear()
                    selection_indexes.add(graphic_index)
            # keep track of general drag information
            graphic_drag_start_pos = start_drag_pos
            graphic_drag_changed = False
            graphic_drag_external = False
            # keep track of info for the specific item that was clicked
            graphic_drag_item = graphics[graphic_index]
            graphic_drag_part = part
            # keep track of drag information for each item in the set
            graphic_drag_indexes = selection_indexes
            for index in graphic_drag_indexes:
                graphic = graphics[index]
                graphic_drag_items.append(graphic)
                graphic_part_data[index] = graphic.begin_drag()
        if not graphic_drag_items and not modifiers.control:
            delegate.clear_selection()

        def get_pointer_tool_shape(mouse_pos: Geometry.FloatPoint) -> str:
            for graphic in graphics:
                if isinstance(graphic, (Graphics.RectangleTypeGraphic, Graphics.SpotGraphic)):
                    part, specific = graphic.test(image_canvas_item.mouse_mapping, image_canvas_item.ui_settings, mouse_pos, False)
                    if part and part.endswith("rotate"):
                        return "cross"
            return "arrow"

        with delegate.create_change_graphics_task() as change_graphics_task:
            while True:
                value_change = await r.next_value_change()
                if value_change.is_end:
                    break
                if value_change.value is not None:
                    mouse_pos_, modifiers = value_change.value
                    mouse_pos = Geometry.FloatPoint(x=mouse_pos_.x, y=mouse_pos_.y)

                    if graphic_drag_items:
                        graphic_drag_changed = True
                        force_drag = modifiers.only_option
                        if force_drag and graphic_drag_part == "all":
                            if Geometry.distance(mouse_pos, graphic_drag_start_pos) <= 2:
                                delegate.drag_graphics(graphic_drag_items)
                                graphic_drag_external = True
                                continue
                        if not graphic_drag_external:
                            delegate.adjust_graphics(widget_mapping, graphic_drag_items, graphic_drag_part, graphic_part_data, graphic_drag_start_pos, mouse_pos, modifiers)

                    self.cursor_shape = get_pointer_tool_shape(mouse_pos)

            graphics = list(image_canvas_item.graphics)
            for index in graphic_drag_indexes:
                graphic_ = graphics[index]
                graphic_.end_drag(graphic_part_data[index])
            if graphic_drag_items and not graphic_drag_changed:
                graphic_index = graphics.index(graphic_drag_item) if graphic_drag_item else 0
                # user didn't move graphic
                if not modifiers.control:
                    # user clicked on a single graphic
                    delegate.set_selection(graphic_index)
                else:
                    # user control clicked. toggle selection
                    # if control is down and item is already selected, toggle selection of item
                    if graphic_drag_item_was_selected:
                        delegate.remove_index_from_selection(graphic_index)
                    else:
                        delegate.add_index_to_selection(graphic_index)

            # if graphic_drag_changed, it means the user moved the image. perform the task.
            if graphic_drag_changed and not graphic_drag_external:
                change_graphics_task.commit()


class HandMouseHandler(MouseHandler):
    def __init__(self, image_canvas_item: ImageCanvasItem, event_loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(image_canvas_item, event_loop)
        self.cursor_shape = "hand"

    async def _reactor_loop(self, r: Stream.ValueChangeStreamReactorInterface[MousePositionAndModifiers], image_canvas_item: ImageCanvasItem) -> None:
        delegate = image_canvas_item.delegate
        assert delegate

        # get the beginning mouse position
        value_change = await r.next_value_change()
        value_change_value = value_change.value
        assert value_change.is_begin
        assert value_change_value is not None

        image_position: typing.Optional[Geometry.FloatPoint] = None

        # preliminary setup for the tracking loop.
        mouse_pos, modifiers = value_change_value
        last_drag_pos = mouse_pos

        with delegate.create_change_display_properties_task() as change_display_properties_task:
            # mouse tracking loop. wait for values and update the image position.
            while True:
                value_change = await r.next_value_change()
                if value_change.is_end:
                    break
                if value_change.value is not None:
                    mouse_pos, modifiers = value_change.value
                    assert last_drag_pos
                    delta = mouse_pos - last_drag_pos
                    image_position = image_canvas_item._update_image_canvas_position(-delta.as_size().to_float_size())
                    last_drag_pos = mouse_pos

            # if the image position was set, it means the user moved the image. perform the task.
            if image_position:
                change_display_properties_task.commit()


class CreateGraphicMouseHandler(MouseHandler):
    def __init__(self, image_canvas_item: ImageCanvasItem, event_loop: asyncio.AbstractEventLoop, graphic_type: str) -> None:
        super().__init__(image_canvas_item, event_loop)
        self.graphic_type = graphic_type

    async def _reactor_loop(self, r: Stream.ValueChangeStreamReactorInterface[MousePositionAndModifiers], image_canvas_item: ImageCanvasItem) -> None:
        delegate = image_canvas_item.delegate
        assert delegate

        # get the beginning mouse position
        value_change = await r.next_value_change()
        value_change_value = value_change.value
        assert value_change.is_begin
        assert value_change_value is not None

        # preliminary setup for the tracking loop.
        mouse_pos_, modifiers = value_change_value
        mouse_pos = Geometry.FloatPoint(x=mouse_pos_.x, y=mouse_pos_.y)
        widget_mapping = image_canvas_item.mouse_mapping
        assert widget_mapping
        pos = widget_mapping.map_point_widget_to_image_norm(mouse_pos)
        start_drag_pos = mouse_pos

        # bypass multi-select if this tool is started with only the shift key selected. see notes where
        # bypass_multi_select is defined.
        image_canvas_item.bypass_multi_select = modifiers.only_shift

        with delegate.create_create_graphic_task(self.graphic_type, pos) as create_create_graphic_task:
            # create the graphic and assign a drag part
            graphic = getattr(create_create_graphic_task, "_graphic")
            graphic_drag_part = graphic._default_drag_part

            delegate.add_index_to_selection(image_canvas_item.graphic_index(graphic))
            # setup drag
            selection_indexes = image_canvas_item.graphic_selection.indexes
            assert len(selection_indexes) == 1
            graphic_drag_item_was_selected = True
            # keep track of general drag information
            graphic_drag_start_pos = start_drag_pos
            graphic_drag_changed = False
            # keep track of info for the specific item that was clicked
            # keep track of drag information for each item in the set
            graphic_drag_indexes = selection_indexes
            graphic_drag_items: typing.List[Graphics.Graphic] = list()
            graphic_drag_items.append(graphic)
            graphic_part_data: typing.Dict[int, Graphics.DragPartData] = dict()
            graphic_part_data[list(selection_indexes)[0]] = graphic.begin_drag()

            # mouse tracking loop. wait for values and update the graphics.
            while True:
                value_change = await r.next_value_change()
                if value_change.is_end:
                    break
                if value_change.value is not None:
                    mouse_pos_, modifiers = value_change.value
                    mouse_pos = Geometry.FloatPoint(x=mouse_pos_.x, y=mouse_pos_.y)
                    force_drag = modifiers.only_option
                    if force_drag and graphic_drag_part == "all":
                        if Geometry.distance(mouse_pos, graphic_drag_start_pos) <= 2:
                            delegate.drag_graphics(graphic_drag_items)
                            continue
                    delegate.adjust_graphics(widget_mapping, graphic_drag_items, graphic_drag_part, graphic_part_data, graphic_drag_start_pos, mouse_pos, modifiers)
                    graphic_drag_changed = True

            graphics = list(image_canvas_item.graphics)
            for index in graphic_drag_indexes:
                graphic_ = graphics[index]
                graphic_.end_drag(graphic_part_data[index])

            if graphic_drag_items and not graphic_drag_changed:
                graphic_index = graphics.index(graphic)
                # user didn't move graphic
                if not modifiers.control:
                    # user clicked on a single graphic
                    delegate.set_selection(graphic_index)
                else:
                    # user control clicked. toggle selection
                    # if control is down and item is already selected, toggle selection of item
                    if graphic_drag_item_was_selected:
                        delegate.remove_index_from_selection(graphic_index)
                    else:
                        delegate.add_index_to_selection(graphic_index)

            # if graphic_drag_changed, it means the user moved the image. perform the task.
            if graphic_drag_changed:
                create_create_graphic_task.commit()


def calculate_dimensional_calibration(data_and_metadata: DataAndMetadata.DataMetadata,
                                      displayed_dimensional_calibrations: typing.Sequence[
                                          Calibration.Calibration]) -> Calibration.Calibration:
    if len(displayed_dimensional_calibrations) == 0:
        dimensional_calibration = Calibration.Calibration()
    elif len(displayed_dimensional_calibrations) == 1:
        dimensional_calibration = displayed_dimensional_calibrations[0]
    else:
        datum_dimensions = data_and_metadata.datum_dimension_indexes
        collection_dimensions = data_and_metadata.collection_dimension_indexes
        if len(datum_dimensions) == 2:
            if displayed_dimensional_calibrations[-1].units:
                dimensional_calibration = displayed_dimensional_calibrations[-1]
            else:
                dimensional_calibration = data_and_metadata.dimensional_calibrations[datum_dimensions[-1]]
        elif len(collection_dimensions) > 0:
            dimensional_calibration = data_and_metadata.dimensional_calibrations[collection_dimensions[-1]]
        elif len(datum_dimensions) > 0:
            dimensional_calibration = data_and_metadata.dimensional_calibrations[datum_dimensions[-1]]
        else:
            dimensional_calibration = Calibration.Calibration()
    return dimensional_calibration



@dataclasses.dataclass
class FrameInfo:
    frame_index: int
    info_items: typing.Sequence[str]

def get_frame_info(data_metadata: DataAndMetadata.DataMetadata) -> FrameInfo:
    # extracts the dict from metadata. packages can provide components which get called to extract
    # the metadata and form the info_items and frame_index, if available.
    # allow registered metadata_display components to populate a dictionary
    # the image canvas item will look at "frame_index" and "info_items"
    d: Persistence.PersistentDictType = dict()
    for component in Registry.get_components_by_type("metadata_display"):
        component.populate(d, data_metadata.metadata)
    # pull out the frame_index and info_items keys
    frame_index = d.get("frame_index", 0)
    info_items = d.get("info_items", list[str]())
    return FrameInfo(frame_index, info_items)


# map the tool mode to the graphic type
graphic_type_map = {
    "line": "line-graphic",
    "rectangle": "rectangle-graphic",
    "ellipse": "ellipse-graphic",
    "point": "point-graphic",
    "line-profile": "line-profile-graphic",
    "spot": "spot-graphic",
    "wedge": "wedge-graphic",
    "ring": "ring-graphic",
    "lattice": "lattice-graphic",
}


class DisplayValueProcessor:
    """Process display values in a separate thread.

    The executor is shared between all instances of this class.

    Clients should call put_display_values to put display values into the processor. The processor will run
    process_display_values on a thread if it is not already running. The processor will apply the display values to
    the bitmap and timestamp canvas items.

    Clients should call stop to stop the processor when it is no longer needed. This will stop the processing thread.
    """
    def __init__(self,
                 executor: concurrent.futures.ThreadPoolExecutor,
                 bitmap_canvas_item: CanvasItem.BitmapCanvasItem,
                 timestamp_canvas_item: CanvasItem.TimestampCanvasItem,
                 display_latency_model: Model.PropertyModel[bool]) -> None:
        self.__executor = executor
        self.__display_values: DisplayItem.DisplayValues | None = None
        self.__bitmap_canvas_item = bitmap_canvas_item
        self.__timestamp_canvas_item = timestamp_canvas_item
        self.__display_latency_model = display_latency_model
        self.__stopped = False
        self.__lock = threading.RLock()
        self.__future: concurrent.futures.Future[None] | None = None

    def stop(self) -> None:
        # set the stopped flag and wait for the future (if any) to complete.
        self.__stopped = True
        with self.__lock:
            future = self.__future
            self.__display_values = None
        if future:
            future.result()

    def __process_display_values(self) -> None:
        # runs on a thread until stopped, loop while new display values are available, apply them to the bitmap
        # and timestamp canvas items. after the loop is exited, check again for display values to avoid a race
        # condition where the display values get set after the lock within the loop but where the current value
        # was None, causing a break out of the loop.
        while not self.__stopped:
            # put_display_values only sets display values under the lock.
            # retrieve them here under the lock and clear them.
            with self.__lock:
                display_values = self.__display_values
                self.__display_values = None
            # at this point forward, the display values may be set again, so we need to check
            if display_values:
                self.apply(display_values)
                display_values = None  # clear the reference to the display values
            else:
                break
        with self.__lock:
            if self.__display_values:
                self.__future = self.__executor.submit(self.__process_display_values)
            else:
                self.__future = None

    def put_display_values(self, display_values: DisplayItem.DisplayValues) -> None:
        with self.__lock:
            # always set the new display values
            self.__display_values = display_values

            # launch processing on a thread if not already running
            if not self.__future:
                self.__future = self.__executor.submit(self.__process_display_values)

    def wait_for_update(self) -> None:
        while True:
            with self.__lock:
                if not self.__future:
                    break
            time.sleep(0.01)  # wait for the display values to be processed

    def apply(self, display_values: DisplayItem.DisplayValues) -> None:
        bitmap_canvas_item = self.__bitmap_canvas_item
        timestamp_canvas_item = self.__timestamp_canvas_item
        display_latency_model = self.__display_latency_model
        display_data = display_values.adjusted_data_and_metadata
        if display_data and display_data.data_dtype == numpy.float32:
            display_range = display_values.transformed_display_range
            color_map_data = display_values.color_map_data
            color_map_rgba: typing.Optional[DrawingContext.RGBA32Type]
            if color_map_data is not None:
                color_map_rgba = numpy.empty(color_map_data.shape[:-1] + (4,), numpy.uint8)
                color_map_rgba[..., 0:3] = color_map_data
                color_map_rgba[..., 3] = 255
                color_map_rgba = color_map_rgba.view(numpy.uint32).reshape(color_map_rgba.shape[:-1])
            else:
                color_map_rgba = None
            # the canvas item expects a ndarray. since the data is being accessed directly here, it could
            # be an array compatible that might be deleted (e.g. a hdf5 dataset). so convert it to a numpy
            # if not already.
            display_data_data = display_data.data
            if not isinstance(display_data_data, numpy.ndarray):
                display_data_data = numpy.array(display_data_data)
            bitmap_canvas_item.set_data(display_data_data, display_range, color_map_rgba)
        else:
            data_rgba = display_values.display_rgba
            bitmap_canvas_item.set_rgba_bitmap_data(data_rgba)
        data_and_metadata = display_values.data_and_metadata
        metadata_d = data_and_metadata.metadata if data_and_metadata else dict()
        timestamp_ns = metadata_d.get("hardware_source", dict()).get("system_time_ns", time.perf_counter_ns()) if display_latency_model.value else 0
        timestamp_canvas_item.timestamp_ns = timestamp_ns


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
    _executor = concurrent.futures.ThreadPoolExecutor()

    def __init__(self, ui_settings: UISettings.UISettings,
                 delegate: typing.Optional[DisplayCanvasItem.DisplayCanvasItemDelegate],
                 event_loop: typing.Optional[asyncio.AbstractEventLoop], draw_background: bool = True) -> None:
        super().__init__()

        self.__ui_settings = ui_settings
        self.delegate = delegate
        self.__event_loop = event_loop

        self.wants_mouse_events = True

        self.__closing_lock = threading.RLock()
        self.__closed = False

        self.__image_zoom = 1.0
        self.__image_position = Geometry.FloatPoint(0.5, 0.5)
        self.__image_canvas_mode = "fit"

        self.__display_calibration_info_dirty = False
        self.__display_properties_dirty = False

        # create the child canvas items
        # the background
        # next the zoom-able items
        self.__bitmap_canvas_item = ImageBitmapCanvasItem(draw_background)
        self.__graphics_canvas_item = GraphicsCanvasItem(ui_settings)
        # put the zoom-able items into a composition
        self.__composite_canvas_item = ImageAreaCompositeCanvasItem()
        self.__composite_canvas_item.add_canvas_item(self.__bitmap_canvas_item)
        self.__composite_canvas_item.add_canvas_item(self.__graphics_canvas_item)
        # and put the composition into a scroll area
        self.scroll_area_canvas_item = ImageAreaCanvasItem(self.__composite_canvas_item)
        # info overlay (scale marker, etc.)
        self.__scale_marker_canvas_item = ScaleMarkerCanvasItem(self.__composite_canvas_item.screen_pixel_per_image_pixel_stream, ui_settings.get_font_metrics)
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
        self.__frame_rate_canvas_item = DisplayCanvasItem.FrameRateCanvasItem()
        # canvas items get added back to front
        if draw_background:
            self.add_canvas_item(CanvasItem.BackgroundCanvasItem())
        self.add_canvas_item(self.scroll_area_canvas_item)
        self.add_canvas_item(self.__overlay_canvas_item)
        self.add_canvas_item(self.__timestamp_canvas_item)
        self.add_canvas_item(self.__frame_rate_canvas_item)

        self.__display_values_dirty = False
        self.__display_values: typing.Optional[DisplayItem.DisplayValues] = None
        self.__pending_display_values_lock = threading.RLock()
        self.__pending_display_values = list[DisplayItem.DisplayValues]()
        self.__data_shape: typing.Optional[DataAndMetadata.Shape2dType] = None
        self.__coordinate_system: typing.List[Calibration.Calibration] = list()
        self.__graphics: typing.List[Graphics.Graphic] = list()
        self.__graphic_selection: DisplayItem.GraphicSelection = DisplayItem.GraphicSelection()

        # used for dragging graphic items
        self.__last_mouse: typing.Optional[Geometry.IntPoint] = None
        self.__mouse_in = False
        self.__mouse_handler: typing.Optional[MouseHandler] = None

        # frame rate and latency
        self.__display_latency_model = Model.PropertyModel[bool](False)

        # display values queue
        self.__display_values_processor = DisplayValueProcessor(ImageCanvasItem._executor, self.__bitmap_canvas_item, self.__timestamp_canvas_item, self.__display_latency_model)

    def close(self) -> None:
        self.__display_values_processor.stop()
        self.__display_values_processor = typing.cast(typing.Any, None)
        with self.__closing_lock:
            self.__closed = True
        self.__display_values = None
        super().close()

    @property
    def _scale_marker_canvas_item_for_test(self) -> ScaleMarkerCanvasItem:
        return self.__scale_marker_canvas_item

    def add_display_control(self, display_control_canvas_item: CanvasItem.AbstractCanvasItem, role: typing.Optional[str] = None) -> None:
        self.__overlay_canvas_item.add_canvas_item(display_control_canvas_item)

    def __update_display_values(self, display_values_list: typing.Sequence[typing.Optional[DisplayItem.DisplayValues]]) -> None:
        self.__display_values = display_values_list[0] if display_values_list else None
        self.__display_values_dirty = True

    def __display_info_changed(self) -> None:
        if self.__data_shape is not None:
            # configure the bitmap canvas item
            display_values = self.__display_values
            if display_values:
                self.__display_values_processor.put_display_values(display_values)

    def __update_display_properties_and_layers(self, display_calibration_info: DisplayItem.DisplayCalibrationInfo, display_properties: Persistence.PersistentDictType, display_layers: typing.Sequence[DisplayItem.DisplayLayerInfo]) -> None:
        # thread-safe
        data_and_metadata = self.__display_values.data_and_metadata if self.__display_values else None
        data_metadata = data_and_metadata.data_metadata if data_and_metadata else None
        if data_metadata:
            frame_info = get_frame_info(data_metadata)

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
                        self.scroll_area_canvas_item._image_zoom = self.__image_zoom
                    if image_position is not None:
                        self.__image_position = image_position
                        self.scroll_area_canvas_item._image_position = self.__image_position
                    if image_canvas_mode is not None:
                        self.__image_canvas_mode = image_canvas_mode
                        self.scroll_area_canvas_item._image_canvas_mode = self.__image_canvas_mode

                # if the data changes, update the display.
                data_shape = display_calibration_info.display_data_shape
                if data_shape is not None and len(data_shape) == 2 and (self.__display_properties_dirty or self.__display_calibration_info_dirty or self.__display_values_dirty):
                    self.__display_values_dirty = False
                    self.__display_properties_dirty = False
                    self.__display_calibration_info_dirty = False
                    self.__data_shape = data_shape[0], data_shape[1]
                    self.scroll_area_canvas_item._data_shape = self.__data_shape
                    self.__composite_canvas_item._data_shape = self.__data_shape
                    self.__coordinate_system = display_calibration_info.datum_calibrations
                    self.__frame_rate_canvas_item.frame_tick(frame_info.frame_index)
                    # update the cursor info
                    self.__update_cursor_info()

                    scroll_area_canvas_size = self.scroll_area_canvas_item.canvas_size
                    if scroll_area_canvas_size is not None:
                        # only update layout if the size/origin will change. it is slow.
                        image_canvas_rect: typing.Optional[Geometry.IntRect]
                        if self.__data_shape is not None:
                            image_canvas_rect = calculate_origin_and_size(scroll_area_canvas_size, self.__data_shape, self.__image_canvas_mode, self.__image_zoom, self.__image_position)
                        else:
                            image_canvas_rect = None
                        if image_canvas_rect != self.__composite_canvas_item.canvas_rect:
                            # layout. this makes sure that the info overlay gets updated too.
                            self.update_layout(self.canvas_origin, self.canvas_size)
                            # trigger updates
                            self.__composite_canvas_item.update()

                    # note: bitmap canvas item will be updated in the display_info_changed method.
                    # doing it in display_info_changed ensures that the repaint (on a thread) does not occur
                    # before setting the data. if the update were done above, as it used to be, the repaint
                    # could occur before the new data was sent to the bitmap canvas item.

                # update bitmaps. this will update the bitmap canvas item, too.
                self.__display_info_changed()

                # setting the bitmap on the bitmap_canvas_item is delayed until paint, so that it happens on a thread, since it may be time consuming
                dimensional_calibration = calculate_dimensional_calibration(data_metadata, display_calibration_info.displayed_dimensional_calibrations)
                self.__scale_marker_canvas_item.set_data_info(dimensional_calibration, frame_info.info_items)

    def __update_graphics_coordinate_system(self, graphics: typing.Sequence[Graphics.Graphic], graphic_selection: DisplayItem.GraphicSelection, display_calibration_info: DisplayItem.DisplayCalibrationInfo) -> None:
        self.__graphics = list(graphics)
        self.__graphic_selection = copy.copy(graphic_selection)
        self.__graphics_canvas_item.update_coordinate_system(display_calibration_info.display_data_shape, display_calibration_info.datum_calibrations, self.__graphics, self.__graphic_selection)

    def update_display_data_delta(self, display_data_delta: DisplayItem.DisplayDataDelta) -> None:
        if display_data_delta.display_values_list_changed:
            self.__update_display_values(display_data_delta.display_values_list)
        if display_data_delta.display_values_list_changed or display_data_delta.display_calibration_info_changed or display_data_delta.display_layers_list_changed or display_data_delta.display_properties_changed:
            self.__display_properties_dirty = self.__display_properties_dirty or display_data_delta.display_properties_changed
            self.__display_calibration_info_dirty = self.__display_calibration_info_dirty or display_data_delta.display_calibration_info_changed
            self.__update_display_properties_and_layers(display_data_delta.display_calibration_info,
                                                        display_data_delta.display_properties,
                                                        display_data_delta.display_layers_list)
        if display_data_delta.graphics_changed or display_data_delta.graphic_selection_changed or display_data_delta.display_calibration_info_changed:
            self.__update_graphics_coordinate_system(display_data_delta.graphics,
                                                     display_data_delta.graphic_selection,
                                                     display_data_delta.display_calibration_info)

    def _wait_for_update(self) -> None:
        # used for testing
        self.__display_values_processor.wait_for_update()

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

    def set_focused(self, is_focused: bool) -> None:
        self.__graphics_canvas_item.is_focused = is_focused

    @property
    def graphics(self) -> typing.Sequence[Graphics.Graphic]:
        return self.__graphics

    def graphic_index(self, graphic: Graphics.Graphic) -> int:
        return self.__graphics.index(graphic)

    @property
    def graphic_selection(self) -> DisplayItem.GraphicSelection:
        return self.__graphic_selection

    @property
    def ui_settings(self) -> UISettings.UISettings:
        return self.__ui_settings

    def _set_image_canvas_position(self, image_position: Geometry.FloatPoint) -> None:
        # create a widget mapping to get from image norm to widget coordinates and back
        delegate = self.delegate
        widget_mapping = ImageCanvasItemMapping.make(self.__data_shape, self.__composite_canvas_item.canvas_bounds, list())
        if delegate and widget_mapping:
            delegate.update_display_properties({"image_position": list(image_position), "image_canvas_mode": "custom"})

    # update the image canvas position by the widget delta amount. called on main thread.
    def _update_image_canvas_position(self, widget_delta: Geometry.FloatSize) -> Geometry.FloatPoint:
        # create a widget mapping to get from image norm to widget coordinates and back
        new_image_canvas_position = Geometry.FloatPoint()
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
            new_image_canvas_position = Geometry.FloatPoint(new_image_norm_center_0, new_image_norm_center_1)
            self._set_image_canvas_position(new_image_canvas_position)
        return new_image_canvas_position

    def convert_pixel_to_normalised(self, coord: Geometry.IntPoint) -> Geometry.FloatPoint:
        if coord:
            widget_mapping = ImageCanvasItemMapping.make(self.__data_shape, self.__composite_canvas_item.canvas_bounds,
                                                         list())
            if widget_mapping:
                mapped = self.map_widget_to_image(coord)
                if (mapped is not None) and (self.__data_shape is not None):
                    norm_coord = tuple(mapped_coord / shape_dim for mapped_coord, shape_dim in zip(iter(mapped), iter(self.__data_shape)))
                    return Geometry.FloatPoint(norm_coord[0], norm_coord[1])  # y,x
        return Geometry.FloatPoint(-1, -1)

    # Apply a zoom factor to the widget, optionally focused on a specific point
    def apply_fixed_zoom(self, zoom_in: bool, coord: typing.Optional[Geometry.IntPoint]) -> None:
        if zoom_in:
            self.zoom_in(focused_position=coord)
        else:
            self.zoom_out(focused_position=coord)

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
        if delegate.image_mouse_pressed(image_position, modifiers):
            return True
        if delegate.tool_mode == "pointer":
            assert not self.__mouse_handler
            assert self.__event_loop
            self.__mouse_handler = PointerMouseHandler(self, self.__event_loop)
            self.__mouse_handler.mouse_pressed(Geometry.IntPoint(y=y, x=x), modifiers)
        elif delegate.tool_mode == "hand":
            assert not self.__mouse_handler
            assert self.__event_loop
            self.__mouse_handler = HandMouseHandler(self, self.__event_loop)
            self.__mouse_handler.mouse_pressed(Geometry.IntPoint(y=y, x=x), modifiers)
        elif delegate.tool_mode == "zoom":
            self.apply_fixed_zoom(not modifiers.alt, Geometry.IntPoint(y=y, x=x))
        elif delegate.tool_mode in graphic_type_map.keys():
            assert not self.__mouse_handler
            assert self.__event_loop
            self.__mouse_handler = CreateGraphicMouseHandler(self, self.__event_loop, graphic_type_map[delegate.tool_mode])
            self.__mouse_handler.mouse_pressed(Geometry.IntPoint(y=y, x=x), modifiers)
        return True

    def mouse_double_clicked(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        # NOTE: clicking quickly to zoom in/out will be treated as double clicks. as a temporary solution, handle
        # double clicks here by zooming. in the future, we may add support for handling mouse releases that occur
        # not as part of double-clicking.
        if super().mouse_double_clicked(x, y, modifiers):
            return True
        delegate = self.delegate
        widget_mapping = self.mouse_mapping
        if not delegate or not widget_mapping:
            return False
        if delegate.tool_mode == "zoom":
            self.apply_fixed_zoom(not modifiers.alt, Geometry.IntPoint(y=y, x=x))
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
        if self.__mouse_handler:
            self.__mouse_handler.mouse_released(Geometry.IntPoint(y, x), modifiers)
            self.__mouse_handler = None

        if delegate.tool_mode == "hand":
            pass
        elif delegate.tool_mode == "zoom":
            pass
        else:
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
            self.cursor_shape = self.__mouse_handler.cursor_shape if self.__mouse_handler else "arrow"
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
        elif delegate.tool_mode == "zoom":
            self.cursor_shape = "cross"

        # x,y already have transform applied
        self.__last_mouse = mouse_pos.to_int_point()
        self.__update_cursor_info()
        if self.__mouse_handler:
            self.__mouse_handler.mouse_position_changed(Geometry.IntPoint(y, x), modifiers)
        return True

    def wheel_changed(self, x: int, y: int, dx: int, dy: int, is_horizontal: bool) -> bool:
        delegate = self.delegate
        if delegate and self.__mouse_in:
            dx = dx if is_horizontal else 0
            dy = dy if not is_horizontal else 0
            command = delegate.create_change_display_command(command_id="image_position", is_mergeable=True)
            self._update_image_canvas_position(Geometry.FloatSize(-dy, -dx))
            delegate.push_undo_command(command)
            return True
        return False

    def pan_gesture(self, dx: int, dy: int) -> bool:
        self._update_image_canvas_position(Geometry.FloatSize(dy, dx))
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
        self.__frame_rate_canvas_item.toggle_display(str(id(self)))
        self.__bitmap_canvas_item.display_frame_rate_id = self.__frame_rate_canvas_item.display_frame_rate_id

    def toggle_latency(self) -> None:
        self.__display_latency_model.value = not self.__display_latency_model.value

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
            self._update_image_canvas_position(delta)
            delegate.push_undo_command(command)

    def set_fit_mode(self) -> None:
        self.__apply_display_properties_command({"image_zoom": 1.0, "image_position": (0.5, 0.5), "image_canvas_mode": "fit"})

    def set_fill_mode(self) -> None:
        self.__apply_display_properties_command({"image_zoom": 1.0, "image_position": (0.5, 0.5), "image_canvas_mode": "fill"})

    def set_one_to_one_mode(self) -> None:
        self.__apply_display_properties_command({"image_zoom": 1.0, "image_position": (0.5, 0.5), "image_canvas_mode": "1:1"})

    def set_two_to_one_mode(self) -> None:
        self.__apply_display_properties_command({"image_zoom": 0.5, "image_position": (0.5, 0.5), "image_canvas_mode": "2:1"})

    def get_current_zoom(self) -> float:
        if self.image_canvas_mode == "custom":
            # Already in custom, just return current zoom
            return self.__image_zoom

        if self.canvas_bounds and self.__data_shape:
            new_zoom = 1.0
            if self.image_canvas_mode == "fit":
                # defaults to zoom of 1
                pass
            elif self.image_canvas_mode == "fill":
                x_zoom = self.canvas_bounds.width / self.__data_shape[1]
                y_zoom = self.canvas_bounds.height / self.__data_shape[0]
                new_zoom = max(y_zoom, x_zoom) / min(y_zoom, x_zoom)
                pass
            elif self.image_canvas_mode == "1:1":
                x_zoom = self.__data_shape[1] / self.canvas_bounds.width
                y_zoom = self.__data_shape[0] / self.canvas_bounds.height
                new_zoom = max(y_zoom, x_zoom)
            elif self.image_canvas_mode == "2:1":
                x_zoom = self.__data_shape[1] / self.canvas_bounds.width
                y_zoom = self.__data_shape[0] / self.canvas_bounds.height
                new_zoom = max(y_zoom, x_zoom)
                new_zoom /= 2
            return new_zoom
        return float("nan")  # No defined canvas or data sizes, zoom is undefined

    def zoom(self, factor: float, focused_position: typing.Optional[Geometry.IntPoint] = None) -> None:
        display_properties: dict[str, float | str | list[float]] = {}

        # Image zoom appears undefined in some non-custom modes
        if self.__image_canvas_mode != "custom":
            previous_zoom = self.get_current_zoom()
            new_zoom = previous_zoom * factor
            display_properties["image_zoom"] = new_zoom
            display_properties["image_canvas_mode"] = "custom"
        else:
            display_properties["image_zoom"] = self.__image_zoom * factor

        if focused_position and self.scroll_area_canvas_item.canvas_size and self.__data_shape:
            # Position to focus the zoom on here, so need to keep that position under the cursor
            mapped = self.map_widget_to_image(focused_position)
            if mapped:
                mapped_center = self.map_widget_to_image(
                    Geometry.IntPoint(self.scroll_area_canvas_item.canvas_size.height // 2,
                                      self.scroll_area_canvas_item.canvas_size.width // 2))
                if mapped_center is not None:
                    # Vector from clicked position to image center
                    mapped_vector = (mapped_center[0] - mapped[0], mapped_center[1] - mapped[1])
                    # Scale by the inverse of the zoom factor to get the vector from
                    # Click point to what the new center needs to be
                    scaled_mapped_vector = (mapped_vector[0] / factor, mapped_vector[1] / factor)
                    new_image_center = (mapped[0] + scaled_mapped_vector[0],
                                        mapped[1] + scaled_mapped_vector[1])
                    norm_coord = tuple(new_mapped_coord / shape_dim for new_mapped_coord, shape_dim in
                                       zip(iter(new_image_center), iter(self.__data_shape)))
                    display_properties["image_position"] = list(Geometry.FloatPoint(norm_coord[0], norm_coord[1]))

        self.__apply_display_properties_command(display_properties)

    def zoom_in(self, factor: float = 1.25, focused_position: typing.Optional[Geometry.IntPoint] = None) -> None:
        self.zoom(factor, focused_position)

    def zoom_out(self, factor: float = 1.25, focused_position: typing.Optional[Geometry.IntPoint] = None) -> None:
        self.zoom(1 / factor, focused_position)

    def move_left(self, amount: float = 10.0) -> None:
        self.apply_move_command(Geometry.FloatSize(0.0, amount))

    def move_right(self, amount: float = 10.0) -> None:
        self.apply_move_command(Geometry.FloatSize(0.0, -amount))

    def move_up(self, amount: float = 10.0) -> None:
        self.apply_move_command(Geometry.FloatSize(amount, 0.0))

    def move_down(self, amount: float = 10.0) -> None:
        self.apply_move_command(Geometry.FloatSize(-amount, 0.0))
