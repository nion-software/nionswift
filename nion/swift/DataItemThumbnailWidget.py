# standard libraries
# None

# third party libraries
# None

# local libraries
from nion.data import Image
from nion.swift import Thumbnails
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.swift.model import DocumentModel
from nion.ui import CanvasItem
from nion.ui import Widgets
from nion.utils import Geometry


class AbstractThumbnailSource:

    def __init__(self):
        self.on_thumbnail_data_changed = None
        self.__thumbnail_data = None
        self.overlay_canvas_item = CanvasItem.EmptyCanvasItem()

    def close(self):
        self.on_thumbnail_data_changed = None

    @property
    def thumbnail_data(self):
        return self.__thumbnail_data

    def _set_thumbnail_data(self, thumbnail_data):
        self.__thumbnail_data = thumbnail_data

    def populate_mime_data_for_drag(self, mime_data, size: Geometry.IntSize):
        return False, None


class BitmapOverlayCanvasItem(CanvasItem.CanvasItemComposition):

    def __init__(self):
        super().__init__()
        self.focusable = True
        self.__dropping = False
        self.__focused = False
        self.wants_drag_events = True
        self.wants_mouse_events = True
        self.__drag_start = None
        self.on_drop_mime_data = None
        self.on_delete = None
        self.on_drag_pressed = None
        self.active = False

    def close(self):
        self.on_drop_mime_data = None
        self.on_delete = None
        self.on_drag_pressed = None
        super().close()

    @property
    def focused(self):
        return self.__focused

    def _set_focused(self, focused):
        if self.__focused != focused:
            self.__focused = focused
            self.update()

    def _repaint(self, drawing_context):
        super()._repaint(drawing_context)
        # canvas size
        canvas_width = self.canvas_size[1]
        canvas_height = self.canvas_size[0]
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
                drawing_context.rect(0, 0, canvas_width, canvas_height)
                drawing_context.fill_style = "rgba(255, 0, 0, 0.10)"
                drawing_context.fill()
        if self.focused:
            stroke_style = focused_style
            drawing_context.begin_path()
            drawing_context.rect(2, 2, canvas_width - 4, canvas_height - 4)
            drawing_context.line_join = "miter"
            drawing_context.stroke_style = stroke_style
            drawing_context.line_width = 4.0
            drawing_context.stroke()

    def drag_enter(self, mime_data):
        self.__dropping = True
        self.update()
        return "ignore"

    def drag_leave(self):
        self.__dropping = False
        self.update()
        return False

    def drop(self, mime_data, x, y):
        if callable(self.on_drop_mime_data):
            result = self.on_drop_mime_data(mime_data, x, y)
            if result:
                return result
        return super().drop(mime_data, x, y)

    def key_pressed(self, key):
        if key.is_delete:
            on_delete = self.on_delete
            if callable(on_delete):
                on_delete()
                return True
        return super().key_pressed(key)

    def mouse_pressed(self, x, y, modifiers):
        self.__drag_start = Geometry.IntPoint(x=x, y=y)
        return True

    def mouse_released(self, x, y, modifiers):
        self.__drag_start = None
        return True

    def mouse_position_changed(self, x, y, modifiers):
        p = Geometry.IntPoint(x=x, y=y)
        if self.__drag_start is not None and Geometry.distance(p, self.__drag_start) > 2:
            self.__drag_start = None
            on_drag_pressed = self.on_drag_pressed
            if on_drag_pressed:
                on_drag_pressed(x, y, modifiers)


class ThumbnailCanvasItem(CanvasItem.CanvasItemComposition):

    def __init__(self, ui, thumbnail_source: AbstractThumbnailSource, size: Geometry.IntSize):
        super().__init__()
        bitmap_overlay_canvas_item = BitmapOverlayCanvasItem()
        bitmap_canvas_item = CanvasItem.BitmapCanvasItem(background_color="#CCC", border_color="#444")
        bitmap_canvas_item.sizing.set_fixed_size(size)
        bitmap_overlay_canvas_item.add_canvas_item(bitmap_canvas_item)
        thumbnail_source.overlay_canvas_item.sizing.set_fixed_size(size)
        bitmap_overlay_canvas_item.add_canvas_item(thumbnail_source.overlay_canvas_item)
        self.__thumbnail_source = thumbnail_source
        self.on_drag = None
        self.on_drop_mime_data = None
        self.on_delete = None

        def drag_pressed(x, y, modifiers):
            on_drag = self.on_drag
            if callable(on_drag):
                mime_data = ui.create_mime_data()
                valid, thumbnail = thumbnail_source.populate_mime_data_for_drag(mime_data, size)
                if valid:
                    on_drag(mime_data, thumbnail, x, y)

        def drop_mime_data(mime_data, x, y):
            if callable(self.on_drop_mime_data):
                return self.on_drop_mime_data(mime_data, x, y)
            return None

        def delete():
            on_delete = self.on_delete
            if callable(on_delete):
                on_delete()

        bitmap_overlay_canvas_item.on_drag_pressed = drag_pressed
        bitmap_overlay_canvas_item.on_drop_mime_data = drop_mime_data
        bitmap_overlay_canvas_item.on_delete = delete

        def thumbnail_data_changed(thumbnail_data):
            bitmap_canvas_item.rgba_bitmap_data = thumbnail_data

        self.__thumbnail_source.on_thumbnail_data_changed = thumbnail_data_changed

        bitmap_canvas_item.rgba_bitmap_data = self.__thumbnail_source.thumbnail_data

        self.add_canvas_item(bitmap_overlay_canvas_item)

    def close(self):
        self.__thumbnail_source.close()
        self.__thumbnail_source = None
        self.on_drag = None
        self.on_drop_mime_data = None
        self.on_delete = None
        super().close()


class ThumbnailWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui, thumbnail_source: AbstractThumbnailSource, size: Geometry.IntSize):
        super().__init__(ui.create_column_widget())
        thumbnail_canvas_item = ThumbnailCanvasItem(ui, thumbnail_source, size)
        bitmap_canvas_widget = ui.create_canvas_widget(properties={"height": size.height, "width": size.width})
        bitmap_canvas_widget.canvas_item.add_canvas_item(thumbnail_canvas_item)
        self.content_widget.add(bitmap_canvas_widget)
        self.on_drop_mime_data = None
        self.on_drag = None
        self.on_delete = None

        def drop_mime_data(mime_data, x, y):
            if callable(self.on_drop_mime_data):
                return self.on_drop_mime_data(mime_data, x, y)
            return None

        def drag(mime_data, thumbnail, x, y):
            on_drag = self.on_drag
            if callable(on_drag):
                on_drag(mime_data, thumbnail, x, y)

        def delete():
            on_delete = self.on_delete
            if callable(on_delete):
                on_delete()

        thumbnail_canvas_item.on_drop_mime_data = drop_mime_data
        thumbnail_canvas_item.on_drag = drag
        thumbnail_canvas_item.on_delete = delete

    def close(self):
        super().close()
        self.on_drop_mime_data = None
        self.on_drag = None
        self.on_delete = None


class DataItemBitmapOverlayCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super().__init__()
        self.__active = False

    @property
    def active(self):
        return self.__active

    @active.setter
    def active(self, value):
        if value != self.__active:
            self.__active = value
            self.update()

    def _repaint(self, drawing_context):
        super()._repaint(drawing_context)
        if self.active:
            with drawing_context.saver():
                drawing_context.begin_path()
                drawing_context.round_rect(2, 2, 6, 6, 3)
                drawing_context.fill_style = "rgba(0, 255, 0, 0.80)"
                drawing_context.fill()


class DataItemThumbnailSource(AbstractThumbnailSource):

    def __init__(self, ui, *, data_item=None, display=None):
        super().__init__()
        self.ui = ui
        self.__thumbnail_source = None
        self.__thumbnail_updated_event_listener = None
        self.overlay_canvas_item = DataItemBitmapOverlayCanvasItem()
        if data_item:
            self.set_data_item(data_item)
        if display:
            self.set_display(display)

    def close(self):
        self.__detach_listeners()
        super().close()

    def __detach_listeners(self):
        if self.__thumbnail_updated_event_listener:
            self.__thumbnail_updated_event_listener.close()
            self.__thumbnail_updated_event_listener = None
        if self.__thumbnail_source:
            self.__thumbnail_source.close()
            self.__thumbnail_source = None

    def __update_thumbnail(self) -> None:
        self._set_thumbnail_data(Thumbnails.ThumbnailManager().thumbnail_data_for_display(self.__display))
        self.overlay_canvas_item.active = self.__display.is_live if self.__display else False
        if callable(self.on_thumbnail_data_changed):
            self.on_thumbnail_data_changed(self.thumbnail_data)

    def set_data_item(self, data_item: DataItem.DataItem) -> None:
        display = data_item.primary_display_specifier.display if data_item else None
        self.set_display(display)

    def set_display(self, display: Display.Display) -> None:
        self.__detach_listeners()
        self.__display = display
        if display:
            self.__thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display(self.ui, display)
            self.__thumbnail_updated_event_listener = self.__thumbnail_source.thumbnail_updated_event.listen(self.__update_thumbnail)
        self.__update_thumbnail()

    def populate_mime_data_for_drag(self, mime_data, size: Geometry.IntSize):
        if self.__display:
            display_specifier = DataItem.DisplaySpecifier.from_display(self.__display)
            if display_specifier.library_item:
                mime_data.set_data_as_string("text/library_item_uuid", str(display_specifier.library_item.uuid))
            if display_specifier.data_item:
                mime_data.set_data_as_string("text/data_item_uuid", str(display_specifier.data_item.uuid))
            rgba_image_data = self.__thumbnail_source.thumbnail_data
            thumbnail = Image.get_rgba_data_from_rgba(Image.scaled(Image.get_rgba_view_from_rgba_data(rgba_image_data), (size.width, size.height))) if rgba_image_data is not None else None
            return True, thumbnail
        return False, None


class DataItemReferenceThumbnailSource(DataItemThumbnailSource):
    """Used to track a data item referenced by a data item reference.

    Useful, for instance, for displaying a live update thumbnail that can be dragged to other locations."""

    def __init__(self, ui, data_item_reference: DocumentModel.DocumentModel.DataItemReference):
        super().__init__(ui, data_item=data_item_reference.data_item)

        def data_item_changed():
            self.set_data_item(data_item_reference.data_item)

        self.__data_item_changed_event_listener = data_item_reference.data_item_changed_event.listen(data_item_changed)

    def close(self):
        self.__data_item_changed_event_listener.close()
        self.__data_item_changed_event_listener = None
        super().close()


DataItemThumbnailWidget = ThumbnailWidget
