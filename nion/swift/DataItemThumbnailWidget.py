# standard libraries
import abc
import uuid

# third party libraries
# None

# local libraries
from nion.data import Image
from nion.swift import Widgets
from nion.swift.model import DataItem
from nion.swift.model import DataItemsBinding
from nion.swift.model import DocumentModel
from nion.ui import CanvasItem
from nion.ui import Geometry


class AbstractDataItemThumbnailSource(metaclass=abc.ABCMeta):

    def __init__(self):
        self.on_rgba_bitmap_data_changed = None
        self.__thumbnail_data = None

    def close(self):
        self.on_rgba_bitmap_data_changed = None

    @property
    @abc.abstractmethod
    def data_item(self):
        pass

    @property
    def thumbnail_data(self):
        return self.__thumbnail_data

    def _set_thumbnail_data(self, thumbnail_data):
        self.__thumbnail_data = thumbnail_data

    def _update_thumbnail(self, data_item: DataItem.DataItem) -> None:
        display = data_item.primary_display_specifier.display if data_item else None
        self._set_thumbnail_data(display.get_processed_data("thumbnail") if display else None)
        if callable(self.on_rgba_bitmap_data_changed):
            self.on_rgba_bitmap_data_changed(data_item, self.__thumbnail_data)


class DataItemThumbnailSource(AbstractDataItemThumbnailSource):

    def __init__(self, data_item):
        super().__init__()
        self.__data_item = None
        self.set_data_item(data_item)

    @property
    def data_item(self):
        return self.__data_item

    def set_data_item(self, data_item):
        self.__data_item = data_item
        self._update_thumbnail(data_item)


class FilteredDataItemThumbnailSource(AbstractDataItemThumbnailSource):

    def __init__(self, ui, filtered_data_items_binding: DataItemsBinding.DataItemsInContainerBinding, dispatch_task):
        super().__init__()
        self.__data_item = None
        self.__data_item_content_changed_event_listener = None
        self.__filtered_data_items_binding = filtered_data_items_binding

        def update_display_data_item():
            if self.__data_item_content_changed_event_listener:
                self.__data_item_content_changed_event_listener.close()
                self.__data_item_content_changed_event_listener = None
            data_items = self.__filtered_data_items_binding.data_items
            if len(data_items) > 0:
                data_item = data_items[0]
                if data_item:
                    self.__data_item = data_item
                    def data_item_content_changed(changes):
                        data_item = self.__data_item
                        display = data_item.primary_display_specifier.display if data_item else None
                        display.get_processor("thumbnail").recompute_if_necessary(dispatch_task, ui)
                        self._update_thumbnail(data_item)
                    self.__data_item_content_changed_event_listener = data_item.data_item_content_changed_event.listen(data_item_content_changed)
            else:
                self.__data_item = None
                self._update_thumbnail(self.__data_item)

        self.__filtered_data_items_binding.inserters[id(self)] = lambda data_item, before_index: update_display_data_item()
        self.__filtered_data_items_binding.removers[id(self)] = lambda data_item, index: update_display_data_item()

        update_display_data_item()
        self._update_thumbnail(self.__data_item)

    def close(self):
        if self.__data_item_content_changed_event_listener:
            self.__data_item_content_changed_event_listener.close()
            self.__data_item_content_changed_event_listener = None
        self.__filtered_data_items_binding.close()
        self.__filtered_data_items_binding = None
        super().close()

    @property
    def data_item(self):
        return self.__data_item


class DataItemReferenceThumbnailSource(AbstractDataItemThumbnailSource):

    def __init__(self, ui, data_item_reference: DocumentModel.DocumentModel.DataItemReference, dispatch_task):
        super().__init__()
        self.__data_item = None
        self.__data_item_content_changed_event_listener = None

        def data_item_changed():
            if self.__data_item_content_changed_event_listener:
                self.__data_item_content_changed_event_listener.close()
                self.__data_item_content_changed_event_listener = None
            data_item = data_item_reference.data_item
            if data_item:
                self.__data_item = data_item
                def data_item_content_changed(changes):
                    data_item = self.__data_item
                    display = data_item.primary_display_specifier.display if data_item else None
                    display.get_processor("thumbnail").recompute_if_necessary(dispatch_task, ui)
                    self._update_thumbnail(data_item)
                self.__data_item_content_changed_event_listener = data_item.data_item_content_changed_event.listen(data_item_content_changed)
            else:
                self.__data_item = None
                self._update_thumbnail(self.__data_item)

        self.__data_item_changed_event_listener = data_item_reference.data_item_changed_event.listen(data_item_changed)

        data_item_changed()
        self._update_thumbnail(self.__data_item)

    def close(self):
        if self.__data_item_content_changed_event_listener:
            self.__data_item_content_changed_event_listener.close()
            self.__data_item_content_changed_event_listener = None
        self.__data_item_changed_event_listener.close()
        self.__data_item_changed_event_listener = None
        super().close()

    @property
    def data_item(self):
        return self.__data_item


class BitmapOverlayCanvasItem(CanvasItem.CanvasItemComposition):

    def __init__(self):
        super().__init__()
        self.focusable = True
        self.__dropping = False
        self.__focused = False
        self.wants_drag_events = True
        self.wants_mouse_events = True
        self.on_data_item_drop = None
        self.on_data_item_delete = None
        self.on_drag_pressed = None
        self.active = False

    def close(self):
        self.on_data_item_drop = None
        self.on_data_item_delete = None
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
                    focused_style = "#3876D6"  # TODO: platform dependent
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
        if mime_data.has_format("text/data_item_uuid"):
            data_item_uuid = uuid.UUID(mime_data.data_as_string("text/data_item_uuid"))
            on_data_item_drop = self.on_data_item_drop
            if callable(on_data_item_drop):
                on_data_item_drop(data_item_uuid)
                return "copy"
            return "ignore"

    def key_pressed(self, key):
        if key.is_delete:
            on_data_item_delete = self.on_data_item_delete
            if callable(on_data_item_delete):
                on_data_item_delete()
                return True
        return super().key_pressed(key)

    def mouse_pressed(self, x, y, modifiers):
        on_drag_pressed = self.on_drag_pressed
        if on_drag_pressed:
            on_drag_pressed(x, y, modifiers)
        return True


class DataItemThumbnailCanvasItem(CanvasItem.CanvasItemComposition):

    # TODO: add 1 pixel progress bar to indicate live acquisition

    def __init__(self, ui, data_item_thumbnail_source: AbstractDataItemThumbnailSource, size: Geometry.IntSize):
        super().__init__()
        bitmap_overlay_canvas_item = BitmapOverlayCanvasItem()
        bitmap_canvas_item = CanvasItem.BitmapCanvasItem(background_color="#CCC", border_color="#444")
        bitmap_canvas_item.sizing.set_fixed_size(size)
        bitmap_overlay_canvas_item.add_canvas_item(bitmap_canvas_item)
        self.__thumbnail_source = data_item_thumbnail_source
        self.on_drag = None
        self.on_data_item_drop = None
        self.on_data_item_delete = None

        def drag_pressed(x, y, modifiers):
            on_drag = self.on_drag
            if callable(on_drag):
                data_item = data_item_thumbnail_source.data_item
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                if display_specifier.data_item is not None:
                    mime_data = ui.create_mime_data()
                    mime_data.set_data_as_string("text/data_item_uuid", str(display_specifier.data_item.uuid))
                    thumbnail_data = display_specifier.display.get_processed_data("thumbnail")
                    on_drag(mime_data, Image.get_rgba_data_from_rgba(Image.scaled(Image.get_rgba_view_from_rgba_data(thumbnail_data), (size.width, size.height))), x, y)

        def data_item_drop(data_item_uuid):
            on_data_item_drop = self.on_data_item_drop
            if callable(on_data_item_drop):
                on_data_item_drop(data_item_uuid)

        def data_item_delete():
            on_data_item_delete = self.on_data_item_delete
            if callable(on_data_item_delete):
                on_data_item_delete()

        bitmap_overlay_canvas_item.on_drag_pressed = drag_pressed
        bitmap_overlay_canvas_item.on_data_item_drop = data_item_drop
        bitmap_overlay_canvas_item.on_data_item_delete = data_item_delete

        def rgba_bitmap_data_changed(data_item, thumbnail_data):
            bitmap_overlay_canvas_item.active = data_item.is_live if data_item else False
            bitmap_canvas_item.rgba_bitmap_data = thumbnail_data

        self.__thumbnail_source.on_rgba_bitmap_data_changed = rgba_bitmap_data_changed

        bitmap_canvas_item.rgba_bitmap_data = self.__thumbnail_source.thumbnail_data

        self.add_canvas_item(bitmap_overlay_canvas_item)

    def close(self):
        self.__thumbnail_source.close()
        self.__thumbnail_source = None
        self.on_drag = None
        self.on_data_item_drop = None
        self.on_data_item_delete = None
        super().close()


class DataItemThumbnailWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui, data_item_thumbnail_source: AbstractDataItemThumbnailSource, size: Geometry.IntSize):
        super().__init__(ui.create_column_widget())
        data_item_thumbnail_canvas_item = DataItemThumbnailCanvasItem(ui, data_item_thumbnail_source, size)
        bitmap_canvas_widget = ui.create_canvas_widget(properties={"height": size.height, "width": size.width})
        bitmap_canvas_widget.canvas_item.add_canvas_item(data_item_thumbnail_canvas_item)
        self.content_widget.add(bitmap_canvas_widget)
        self.on_drag = None
        self.on_data_item_drop = None
        self.on_data_item_delete = None

        def drag(mime_data, thumbnail, x, y):
            on_drag = self.on_drag
            if callable(on_drag):
                on_drag(mime_data, thumbnail, x, y)

        def data_item_drop(data_item_uuid):
            on_data_item_drop = self.on_data_item_drop
            if callable(on_data_item_drop):
                on_data_item_drop(data_item_uuid)

        def data_item_delete():
            on_data_item_delete = self.on_data_item_delete
            if callable(on_data_item_delete):
                on_data_item_delete()

        data_item_thumbnail_canvas_item.on_drag = drag
        data_item_thumbnail_canvas_item.on_data_item_drop = data_item_drop
        data_item_thumbnail_canvas_item.on_data_item_delete = data_item_delete

    def close(self):
        super().close()
        self.on_drag = None
        self.on_data_item_drop = None
        self.on_data_item_delete = None
