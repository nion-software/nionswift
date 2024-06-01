from __future__ import annotations

# standard libraries
import asyncio
import typing

# third party libraries
import numpy.typing

# local libraries
from nion.data import Image
from nion.swift import MimeTypes
from nion.swift import Thumbnails
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.ui import CanvasItem
from nion.ui import UserInterface
from nion.ui import Widgets
from nion.utils import Geometry
from nion.utils import Process
from nion.utils import ReferenceCounting

if typing.TYPE_CHECKING:
    from nion.swift.model import Persistence
    from nion.ui import DrawingContext
    from nion.ui import Window
    from nion.utils import Binding
    from nion.utils import Event

_ImageDataType = Image._ImageDataType
_NDArray = numpy.typing.NDArray[typing.Any]


class AbstractThumbnailSource:

    def __init__(self) -> None:
        self.on_thumbnail_data_changed: typing.Optional[typing.Callable[[typing.Optional[_NDArray]], None]] = None
        self.__thumbnail_data: typing.Optional[_NDArray] = None
        self.overlay_canvas_item: CanvasItem.AbstractCanvasItem = CanvasItem.EmptyCanvasItem()

    def close(self) -> None:
        self.on_thumbnail_data_changed = None

    @property
    def thumbnail_data(self) -> typing.Optional[_NDArray]:
        return self.__thumbnail_data

    def _set_thumbnail_data(self, thumbnail_data: typing.Optional[_NDArray]) -> None:
        self.__thumbnail_data = thumbnail_data

    def populate_mime_data_for_drag(self, mime_data: UserInterface.MimeData, size: Geometry.IntSize) -> typing.Tuple[bool, typing.Optional[_NDArray]]:
        return False, None


class BitmapOverlayCanvasItem(CanvasItem.CanvasItemComposition):

    def __init__(self) -> None:
        super().__init__()
        self.focusable = True
        self.__dropping = False
        self.__focused = False
        self.wants_drag_events = True
        self.wants_mouse_events = True
        self.__drag_start: typing.Optional[Geometry.IntPoint] = None
        self.on_drop_mime_data: typing.Optional[typing.Callable[[UserInterface.MimeData, int, int], str]] = None
        self.on_delete: typing.Optional[typing.Callable[[], None]] = None
        self.on_drag_pressed: typing.Optional[typing.Callable[[int, int, UserInterface.KeyboardModifiers], None]] = None
        self.active = False

    def close(self) -> None:
        self.on_drop_mime_data = None
        self.on_delete = None
        self.on_drag_pressed = None
        super().close()

    @property
    def focused(self) -> bool:
        return self.__focused

    def _set_focused(self, focused: bool) -> None:
        if self.__focused != focused:
            self.__focused = focused
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        super()._repaint(drawing_context)
        # canvas size
        canvas_size = self.canvas_size
        if canvas_size:
            focused_style = "#3876D6"  # TODO: platform dependent
            if self.active:
                with drawing_context.saver():
                    drawing_context.begin_path()
                    drawing_context.round_rect(2, 2, 6, 6, 3)
                    drawing_context.fill_style = "rgba(0, 255, 0, 0.80)"
                    drawing_context.fill()
            if self.__dropping:
                with drawing_context.saver():
                    drawing_context.begin_path()
                    drawing_context.rect(0, 0, canvas_size.width, canvas_size.height)
                    drawing_context.fill_style = "rgba(255, 0, 0, 0.10)"
                    drawing_context.fill()
            if self.focused:
                stroke_style = focused_style
                drawing_context.begin_path()
                drawing_context.rect(2, 2, canvas_size.width - 4, canvas_size.height - 4)
                drawing_context.line_join = "miter"
                drawing_context.stroke_style = stroke_style
                drawing_context.line_width = 4.0
                drawing_context.stroke()

    def drag_enter(self, mime_data: UserInterface.MimeData) -> str:
        self.__dropping = True
        self.update()
        return "ignore"

    def drag_leave(self) -> str:
        self.__dropping = False
        self.update()
        return "ignore"

    def drop(self, mime_data: UserInterface.MimeData, x: int, y: int) -> str:
        if callable(self.on_drop_mime_data):
            result = self.on_drop_mime_data(mime_data, x, y)
            if result:
                return result
        return super().drop(mime_data, x, y)

    def key_pressed(self, key: UserInterface.Key) -> bool:
        if key.is_delete:
            on_delete = self.on_delete
            if callable(on_delete):
                on_delete()
                return True
        return super().key_pressed(key)

    def mouse_pressed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        self.__drag_start = Geometry.IntPoint(x=x, y=y)
        return True

    def mouse_released(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        self.__drag_start = None
        return True

    def mouse_position_changed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if self.__drag_start is not None and Geometry.distance(Geometry.FloatPoint(y, x), self.__drag_start.to_float_point()) > 2:
            self.__drag_start = None
            on_drag_pressed = self.on_drag_pressed
            if on_drag_pressed:
                on_drag_pressed(x, y, modifiers)
                return True
        return False


class ThumbnailCanvasItem(CanvasItem.CanvasItemComposition):
    """A canvas item that displays a thumbnail and allows dragging the thumbnail.

    To facilitate reusing existing canvas items, set the thumbnail source using set_thumbnail_source.

    This class keeps a bitmap and an overlay canvas item. The overlay canvas item is used for drag and drop events.

    Callers can set the on_drag, on_drop_mime_data, and on_delete callbacks to handle these events.
    """

    def __init__(self, ui: UserInterface.UserInterface, thumbnail_source: AbstractThumbnailSource, size: typing.Optional[Geometry.IntSize] = None) -> None:
        super().__init__()
        self.__ui = ui
        self.__thumbnail_source = thumbnail_source
        self.__thumbnail_size = size

        # define the callbacks
        self.on_drag: typing.Optional[typing.Callable[[UserInterface.MimeData, typing.Optional[_ImageDataType], int, int], None]] = None
        self.on_drop_mime_data: typing.Optional[typing.Callable[[UserInterface.MimeData, int, int], str]] = None
        self.on_delete: typing.Optional[typing.Callable[[], None]] = None

        # set up the initial bitmap and overlay canvas items.
        bitmap_overlay_canvas_item = BitmapOverlayCanvasItem()
        bitmap_canvas_item = CanvasItem.BitmapCanvasItem(background_color="#CCC", border_color="#444")
        bitmap_overlay_canvas_item.add_canvas_item(bitmap_canvas_item)
        if size is not None:
            bitmap_canvas_item.update_sizing(bitmap_canvas_item.sizing.with_fixed_size(size))
            thumbnail_source.overlay_canvas_item.update_sizing(thumbnail_source.overlay_canvas_item.sizing.with_fixed_size(size))
        bitmap_overlay_canvas_item.add_canvas_item(thumbnail_source.overlay_canvas_item)

        # handle overlay drop callback by forwarding to the callback set by the caller.
        def drop_mime_data(mime_data: UserInterface.MimeData, x: int, y: int) -> str:
            if callable(self.on_drop_mime_data):
                return self.on_drop_mime_data(mime_data, x, y)
            return "ignore"

        # handle overlay drag callback by forwarding to the callback set by the caller.
        def delete() -> None:
            on_delete = self.on_delete
            if callable(on_delete):
                on_delete()

        # connect the handlers to the overlay canvas item.
        bitmap_overlay_canvas_item.on_drag_pressed = ReferenceCounting.weak_partial(ThumbnailCanvasItem.__drag_pressed, self)
        bitmap_overlay_canvas_item.on_drop_mime_data = drop_mime_data
        bitmap_overlay_canvas_item.on_delete = delete

        # store these for later use.
        self.__bitmap_canvas_item = bitmap_canvas_item
        self.__bitmap_overlay_canvas_item = bitmap_overlay_canvas_item

        # connect the thumbnail source data changed event to a handler and call the handler to initialize.
        self.__thumbnail_source.on_thumbnail_data_changed = ReferenceCounting.weak_partial(ThumbnailCanvasItem.__thumbnail_data_changed, self)
        self.__thumbnail_data_changed(self.__thumbnail_source.thumbnail_data)

        # add the overlay canvas item (with the bitmap canvas item) to this canvas item.
        self.add_canvas_item(bitmap_overlay_canvas_item)

    def __drag_pressed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> None:
        # handle drag by forwarding to the callback set by the caller.
        on_drag = self.on_drag
        if callable(on_drag):
            mime_data = self.__ui.create_mime_data()
            valid, thumbnail = self.__thumbnail_source.populate_mime_data_for_drag(mime_data, Geometry.IntSize(width=80, height=80))
            if valid:
                on_drag(mime_data, thumbnail, x, y)

    def __thumbnail_data_changed(self, thumbnail_data: typing.Optional[_NDArray]) -> None:
        # update the bitmap canvas item with the new thumbnail data.
        self.__bitmap_canvas_item.rgba_bitmap_data = thumbnail_data

    @property
    def thumbnail_source(self) -> AbstractThumbnailSource:
        return self.__thumbnail_source

    def set_thumbnail_source(self, thumbnail_source: AbstractThumbnailSource) -> None:
        # reconfigure with the new thumbnail source.
        self.__thumbnail_source.close()
        self.__thumbnail_source = thumbnail_source
        if self.__thumbnail_size is not None:
            thumbnail_source.overlay_canvas_item.update_sizing(thumbnail_source.overlay_canvas_item.sizing.with_fixed_size(self.__thumbnail_size))
        self.__bitmap_overlay_canvas_item.remove_canvas_item(self.__bitmap_overlay_canvas_item.canvas_items[-1])
        self.__bitmap_overlay_canvas_item.add_canvas_item(self.__thumbnail_source.overlay_canvas_item)
        self.__thumbnail_source.on_thumbnail_data_changed = ReferenceCounting.weak_partial(ThumbnailCanvasItem.__thumbnail_data_changed, self)
        self.__thumbnail_data_changed(self.__thumbnail_source.thumbnail_data)

    def close(self) -> None:
        self.__thumbnail_source.close()
        self.__thumbnail_source = typing.cast(typing.Any, None)
        self.on_drag = None
        self.on_drop_mime_data = None
        self.on_delete = None
        super().close()


class ThumbnailWidget(Widgets.CompositeWidgetBase):

    # when this widget is placed within a container, it will have no intrinsic size unless size is passed as a
    # parameter. for the case where the size parameter is unspecified, setting the size policy to expanding (in both
    # directions) tells the container that this widget would like to use all available space. however, in order for this
    # to take effect, the container hierarchy cannot utilize unbound stretches or else this widget will not expand. the
    # minimum size is present so that it always uses at least 32x32 pixels. the square canvas layout ensures that the
    # thumbnail area is always square and aligned to the top-left of the container.

    def __init__(self, ui: UserInterface.UserInterface, thumbnail_source: AbstractThumbnailSource,
                 size: typing.Optional[Geometry.IntSize] = None,
                 properties: typing.Optional[Persistence.PersistentDictType] = None) -> None:
        content_widget = ui.create_column_widget()
        super().__init__(content_widget)
        size = size or Geometry.IntSize(width=80, height=80)
        thumbnail_canvas_item = ThumbnailCanvasItem(ui, thumbnail_source, size)
        thumbnail_canvas_item.update_sizing(thumbnail_canvas_item.sizing.with_preferred_aspect_ratio(1.0))
        properties = properties or ({"height": size.height, "width": size.width} if size else dict())
        bitmap_canvas_widget = ui.create_canvas_widget(properties=properties)
        thumbnail_square_row = CanvasItem.CanvasItemComposition()
        thumbnail_square_row.layout = CanvasItem.CanvasItemRowLayout()
        thumbnail_square_row.add_canvas_item(thumbnail_canvas_item)
        thumbnail_square_row.add_stretch()
        thumbnail_square_column = CanvasItem.CanvasItemComposition()
        thumbnail_square_column.layout = CanvasItem.CanvasItemColumnLayout()
        thumbnail_square_column.add_canvas_item(thumbnail_square_row)
        thumbnail_square_column.add_stretch()
        bitmap_canvas_widget.canvas_item.add_canvas_item(thumbnail_square_column)
        content_widget.add(bitmap_canvas_widget)
        self.on_drop_mime_data: typing.Optional[typing.Callable[[UserInterface.MimeData, int, int], str]] = None
        self.on_drag: typing.Optional[typing.Callable[[UserInterface.MimeData, typing.Optional[_ImageDataType], int, int], None]] = None
        self.on_delete: typing.Optional[typing.Callable[[], None]] = None

        def drop_mime_data(mime_data: UserInterface.MimeData, x: int, y: int) -> str:
            if callable(self.on_drop_mime_data):
                return self.on_drop_mime_data(mime_data, x, y)
            return "ignore"

        def drag(mime_data: UserInterface.MimeData, thumbnail: typing.Optional[_NDArray], x: int, y: int) -> None:
            on_drag = self.on_drag
            if callable(on_drag):
                on_drag(mime_data, thumbnail, x, y)

        def delete() -> None:
            on_delete = self.on_delete
            if callable(on_delete):
                on_delete()

        thumbnail_canvas_item.on_drop_mime_data = drop_mime_data
        thumbnail_canvas_item.on_drag = drag
        thumbnail_canvas_item.on_delete = delete

    def close(self) -> None:
        self.on_drop_mime_data = None
        self.on_drag = None
        self.on_delete = None
        super().close()


class DataItemBitmapOverlayCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self) -> None:
        super().__init__()
        self.__active = False

    @property
    def active(self) -> bool:
        return self.__active

    @active.setter
    def active(self, value: bool) -> None:
        if value != self.__active:
            self.__active = value
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        super()._repaint(drawing_context)
        if self.active:
            with drawing_context.saver():
                drawing_context.begin_path()
                drawing_context.round_rect(2, 2, 6, 6, 3)
                drawing_context.fill_style = "rgba(0, 255, 0, 0.80)"
                drawing_context.fill()


class DataItemThumbnailSource(AbstractThumbnailSource):

    def __init__(self, ui: UserInterface.UserInterface, *,
                 display_item: typing.Optional[DisplayItem.DisplayItem] = None,
                 window: typing.Optional[Window.Window] = None) -> None:
        super().__init__()
        self.ui = ui
        self.__display_item: typing.Optional[DisplayItem.DisplayItem] = None
        self.__window = window
        self.__display_item_binding: typing.Optional[Binding.Binding] = None
        self.__thumbnail_source: typing.Optional[Thumbnails.ThumbnailSource] = None
        self.__thumbnail_updated_event_listener: typing.Optional[Event.EventListener] = None
        self.overlay_canvas_item = DataItemBitmapOverlayCanvasItem()
        if display_item:
            self.set_display_item(display_item)
        self.__update_display_item_task: typing.Optional[asyncio.Task[None]] = None

    def close(self) -> None:
        self.__detach_listeners()
        if self.__display_item_binding:
            self.__display_item_binding.close()
            self.__display_item_binding = None
        if self.__update_display_item_task:
            self.__update_display_item_task.cancel()
            self.__update_display_item_task = None
        super().close()

    def __detach_listeners(self) -> None:
        if self.__thumbnail_updated_event_listener:
            self.__thumbnail_updated_event_listener.close()
            self.__thumbnail_updated_event_listener = None
        if self.__thumbnail_source:
            self.__thumbnail_source.remove_ref()
            self.__thumbnail_source = None

    def __update_thumbnail(self) -> None:
        if self.__display_item:
            self._set_thumbnail_data(Thumbnails.ThumbnailManager().thumbnail_data_for_display_item(self.__display_item))
            setattr(self.overlay_canvas_item, "active", self.__display_item.is_live)
        else:
            self._set_thumbnail_data(None)
            setattr(self.overlay_canvas_item, "active", False)
        if callable(self.on_thumbnail_data_changed):
            self.on_thumbnail_data_changed(self.thumbnail_data)

    def set_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        if self.__display_item != display_item:
            self.__detach_listeners()
            self.__display_item = display_item
            if display_item:
                self.__thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.ui, display_item).add_ref()
                self.__thumbnail_updated_event_listener = self.__thumbnail_source.thumbnail_updated_event.listen(self.__update_thumbnail)
            self.__update_thumbnail()
            if self.__display_item_binding:
                self.__display_item_binding.update_source(display_item)

    def populate_mime_data_for_drag(self, mime_data: UserInterface.MimeData, size: Geometry.IntSize) -> typing.Tuple[bool, typing.Optional[_NDArray]]:
        if self.__display_item:
            MimeTypes.mime_data_put_display_item(mime_data, self.__display_item)
            rgba_image_data = self.__thumbnail_source.thumbnail_data if self.__thumbnail_source else None
            thumbnail = Image.get_rgba_data_from_rgba(Image.scaled(Image.get_rgba_view_from_rgba_data(rgba_image_data), (80, 80))) if rgba_image_data is not None else None
            return True, thumbnail
        return False, None

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        return self.__display_item

    @display_item.setter
    def display_item(self, value: typing.Optional[DisplayItem.DisplayItem]) -> None:
        self.set_display_item(value)

    def bind_display_item(self, binding: Binding.Binding) -> None:
        if self.__display_item_binding:
            self.__display_item_binding.close()
            self.__display_item_binding = None
        self.display_item = binding.get_target_value()
        self.__display_item_binding = binding

        def update_display_item(display_item: DisplayItem.DisplayItem) -> None:
            if self.__window:
                async def update_display_item_() -> None:
                    with Process.audit("thumbnail_source.update_display_item"):
                        self.display_item = display_item
                        self.__update_display_item_task = None

                self.__update_display_item_task = self.__window.event_loop.create_task(update_display_item_())

        self.__display_item_binding.target_setter = update_display_item

    def unbind_display_item(self) -> None:
        if self.__display_item_binding:
            self.__display_item_binding.close()
            self.__display_item_binding = None


class DataItemReferenceThumbnailSource(DataItemThumbnailSource):
    """Used to track a data item referenced by a data item reference.

    Useful, for instance, for displaying a live update thumbnail that can be dragged to other locations."""

    def __init__(self, ui: UserInterface.UserInterface, document_model: DocumentModel.DocumentModel, data_item_reference: DocumentModel.DocumentModel.DataItemReference) -> None:
        data_item = data_item_reference.data_item
        display_item = document_model.get_display_item_for_data_item(data_item) if data_item else None
        super().__init__(ui, display_item=display_item)

        def data_item_changed() -> None:
            data_item = data_item_reference.data_item
            display_item = document_model.get_display_item_for_data_item(data_item) if data_item else None
            self.set_display_item(display_item)

        self.__data_item_reference_changed_event_listener = data_item_reference.data_item_reference_changed_event.listen(
            data_item_changed)

    def close(self) -> None:
        self.__data_item_reference_changed_event_listener.close()
        self.__data_item_reference_changed_event_listener = typing.cast(typing.Any, None)
        super().close()


DataItemThumbnailWidget = ThumbnailWidget
