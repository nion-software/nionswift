from __future__ import annotations

# standard libraries
import asyncio
import copy
import gettext
import pkgutil
import threading
import typing

# third party libraries
# None

# local libraries
from nion.data import Image
from nion.swift import MimeTypes
from nion.swift import Panel
from nion.swift import Thumbnails
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import GridCanvasItem
from nion.ui import ListCanvasItem
from nion.ui import Widgets
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel

if typing.TYPE_CHECKING:
    import numpy
    from nion.swift import DocumentController
    from nion.ui import UserInterface
    from nion.utils import Selection

_ = gettext.gettext


"""
    The data panel has two parts:

    (1) a selection of what collection is displayed, which may be a data group, smart data group,
    or the whole document. If the whole document, then an optional filter may also be applied.
    "within the last 24 hours" would be an example filter.

    (2) the list of display items from the collection. the user may further refine the list of
    items by filtering by additional criteria. the user also chooses the sorting on the list of
    display items.

"""


class DisplayItemAdapter:
    """ Provide a simplified interface to a display item for the purpose of display.

        The display_item property is always valid.

        There is typically one display item associated with each display item.

        Provides the following interface:
            (method) close()
            (property, read-only) display_item
            (property, read-only) title_str
            (property, read-only) datetime_str
            (property, read-only) format_str
            (property, read-only) status_str
            (property, read-only) project_str
            (method) drag_started(ui, x, y, modifiers), returns mime_data, thumbnail_data
            (event) needs_update_event
    """

    def __init__(self, display_item: DisplayItem.DisplayItem, ui: UserInterface.UserInterface):
        self.__display_item: typing.Optional[DisplayItem.DisplayItem] = display_item
        self.ui = ui
        self.needs_update_event = Event.Event()

        def display_item_changed() -> None:
            self.needs_update_event.fire()

        self.__display_changed_event_listener = display_item.item_changed_event.listen(display_item_changed) if display_item else None

        self.__display_item_about_to_be_removed_event_listener = None

        def display_item_removed() -> None:
            if self.__display_changed_event_listener:
                self.__display_changed_event_listener.close()
                self.__display_changed_event_listener = None
            if self.__display_item_about_to_be_removed_event_listener:
                self.__display_item_about_to_be_removed_event_listener.close()
                self.__display_item_about_to_be_removed_event_listener = None
            self.__display_item = None

        self.__display_item_about_to_be_removed_event_listener = display_item.about_to_be_removed_event.listen(display_item_removed) if display_item else None

        self.__thumbnail_updated_event_listener = None
        self.__thumbnail_source : typing.Optional[Thumbnails.ThumbnailSource] = None

    def close(self) -> None:
        # remove the listener.
        if self.__thumbnail_updated_event_listener:
            self.__thumbnail_updated_event_listener.close()
            self.__thumbnail_updated_event_listener = None
        if self.__thumbnail_source:
            self.__thumbnail_source.close()
            self.__thumbnail_source = None
        if self.__display_changed_event_listener:
            self.__display_changed_event_listener.close()
            self.__display_changed_event_listener = None
        if self.__display_item_about_to_be_removed_event_listener:
            self.__display_item_about_to_be_removed_event_listener.close()
            self.__display_item_about_to_be_removed_event_listener = None

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        return self.__display_item

    @property
    def data_item(self) -> typing.Optional[DataItem.DataItem]:
        return self.__display_item.data_item if self.__display_item else None

    def __create_thumbnail_source(self) -> None:
        # grab the display specifier and if there is a display, handle thumbnail updating.
        if self.__display_item and not self.__thumbnail_source:
            self.__thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.ui, self.__display_item)

            def thumbnail_updated():
                self.needs_update_event.fire()

            self.__thumbnail_updated_event_listener = self.__thumbnail_source.thumbnail_updated_event.listen(thumbnail_updated)

    def __create_thumbnail(self, draw_rect: Geometry.IntRect) -> DrawingContext.DrawingContext:
        drawing_context = DrawingContext.DrawingContext()
        if self.__display_item:
            thumbnail_data = self.calculate_thumbnail_data()
            if thumbnail_data is not None:
                draw_rect = Geometry.fit_to_size(draw_rect, thumbnail_data.shape)
                drawing_context.draw_image(thumbnail_data, draw_rect[0][1], draw_rect[0][0], draw_rect[1][1], draw_rect[1][0])
        return drawing_context

    @property
    def title_str(self) -> str:
        return self.__display_item.displayed_title if self.__display_item else str()

    @property
    def format_str(self) -> str:
        return self.__display_item.size_and_data_format_as_string if self.__display_item else str()

    @property
    def datetime_str(self) -> str:
        return self.__display_item.date_for_sorting_local_as_string if self.__display_item else str()

    @property
    def status_str(self) -> str:
        return self.__display_item.status_str if self.__display_item else str()

    @property
    def project_str(self) -> str:
        return self.__display_item.project_str if self.__display_item else str()

    def drag_started(self, ui: UserInterface.UserInterface, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> typing.Tuple[typing.Optional[UserInterface.MimeData], typing.Optional[numpy.ndarray]]:
        if self.__display_item:
            mime_data = self.ui.create_mime_data()
            if self.__display_item:
                MimeTypes.mime_data_put_display_item(mime_data, self.__display_item)
            thumbnail_data = self.calculate_thumbnail_data()
            return mime_data, thumbnail_data
        return None, None

    def calculate_thumbnail_data(self) -> typing.Optional[numpy.ndarray]:
        self.__create_thumbnail_source()
        thumbnail_data = self.__thumbnail_source.thumbnail_data if self.__thumbnail_source else None
        if thumbnail_data is not None:
            thumbnail_data = Image.get_rgba_data_from_rgba(Image.scaled(Image.get_rgba_view_from_rgba_data(thumbnail_data), Geometry.IntSize(w=80, h=80)))
        return thumbnail_data

    def draw_list_item(self, drawing_context: DrawingContext.DrawingContext, rect: Geometry.IntRect) -> None:
        with drawing_context.saver():
            draw_rect = Geometry.IntRect(origin=rect.top_left + Geometry.IntPoint(y=4, x=4), size=Geometry.IntSize(h=72, w=72))
            drawing_context.add(self.__create_thumbnail(draw_rect))
            drawing_context.fill_style = "#000"
            drawing_context.font = "11px serif"
            drawing_context.fill_text(self.title_str, rect.left + 4 + 72 + 4, rect.top + 4 + 12)
            drawing_context.fill_text(self.format_str, rect.left + 4 + 72 + 4, rect.top + 4 + 12 + 15)
            drawing_context.fill_text(self.datetime_str, rect.left + 4 + 72 + 4, rect.top + 4 + 12 + 15 + 15)
            if self.status_str:
                drawing_context.fill_text(self.status_str, rect.left + 4 + 72 + 4, rect.top + 4 + 12 + 15 + 15 + 15)
            else:
                drawing_context.fill_style = "#888"
                drawing_context.fill_text(self.project_str, rect.left + 4 + 72 + 4, rect.top + 4 + 12 + 15 + 15 + 15)

    def draw_grid_item(self, drawing_context: DrawingContext.DrawingContext, rect: Geometry.IntRect) -> None:
        drawing_context.add(self.__create_thumbnail(rect.inset(6)))


class DataListController:
    """Control a list of display items in a list widget.

    The following properties are available:
        selected_indexes (r/o)

    The following methods can be called:
        close()

    The controller provides the following callbacks:
        on_delete_display_item_adapters(display_item_adapters)
        on_key_pressed(key)
        on_display_item_adapter_selection_changed(display_item_adapters)
        on_focus_changed(focused)
        on_context_menu_event(display_item_adapter, x, y, gx, gy)

    Display items should respond to these properties and methods and events:
        (method) close()
        (property, read-only) title_str
        (property, read-only) datetime_str
        (property, read-only) format_str
        (property, read-only) status_str
        (method) draw_list_item(drawing_context, draw_rect)
        (method) drag_started(ui, x, y, modifiers), returns mime_data, thumbnail_data
    """

    def __init__(self, event_loop: asyncio.AbstractEventLoop, ui: UserInterface.UserInterface, display_item_adapters_model: ListModel.MappedListModel, selection: Selection.IndexedSelection):
        super().__init__()
        self.__event_loop = event_loop
        self.__pending_tasks : typing.List = list()
        self.ui = ui
        self.__selection = selection
        self.on_delete_display_item_adapters : typing.Optional[typing.Callable[[typing.List[DisplayItemAdapter]], None]] = None
        self.on_key_pressed : typing.Optional[typing.Callable[[UserInterface.Key], bool]] = None

        self.__display_item_adapters : typing.List[DisplayItemAdapter] = list()
        self.__display_item_adapter_needs_update_listeners : typing.List = list()

        self.__display_item_adapters_model = display_item_adapters_model
        self.__display_item_adapter_inserted_event_listener = self.__display_item_adapters_model.item_inserted_event.listen(self.__display_item_adapter_inserted)
        self.__display_item_adapter_removed_event_listener = self.__display_item_adapters_model.item_removed_event.listen(self.__display_item_adapter_removed)
        self.__display_item_adapter_end_changes_event_listener = self.__display_item_adapters_model.end_changes_event.listen(self.__display_item_adapter_end_changes)

        class ListCanvasItemDelegate:
            def __init__(self, data_list_controller: DataListController):
                self.__data_list_controller = data_list_controller

            @property
            def item_count(self) -> int:
                return self.__data_list_controller.display_item_adapter_count

            @property
            def items(self) -> typing.List[DisplayItemAdapter]:
                return self.__data_list_controller.display_item_adapters

            def paint_item(self, drawing_context: DrawingContext.DrawingContext, display_item_adapter: DisplayItemAdapter, rect: Geometry.IntRect, is_selected: bool) -> None:
                display_item_adapter.draw_list_item(drawing_context, rect)

            def context_menu_event(self, index: int, x: int, y: int, gx: int, gy: int) -> bool:
                return self.__data_list_controller.context_menu_event(index, x, y, gx, gy)

            def delete_pressed(self) -> None:
                self.__data_list_controller._delete_pressed()

            def key_pressed(self, key: UserInterface.Key) -> bool:
                return self.__data_list_controller._key_pressed(key)

            def drag_started(self, index: int, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> None:
                self.__data_list_controller.drag_started(index, x, y, modifiers)

        self.__list_canvas_item = ListCanvasItem.ListCanvasItem(ListCanvasItemDelegate(self), self.__selection)

        def focus_changed(focused: bool) -> None:
            self.__list_canvas_item.update()
            if self.on_focus_changed:
                self.on_focus_changed(focused)

        self.__list_canvas_item.on_focus_changed = focus_changed
        self.scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(self.__list_canvas_item)
        self.scroll_area_canvas_item.auto_resize_contents = True
        self.scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(self.scroll_area_canvas_item)
        self.scroll_group_canvas_item = CanvasItem.CanvasItemComposition()
        self.scroll_group_canvas_item.layout = CanvasItem.CanvasItemRowLayout()
        self.scroll_group_canvas_item.add_canvas_item(self.scroll_area_canvas_item)
        self.scroll_group_canvas_item.add_canvas_item(self.scroll_bar_canvas_item)
        self.canvas_item = self.scroll_group_canvas_item

        def selection_changed() -> None:
            self.selected_indexes = list(self.__selection.indexes)
            if callable(self.on_display_item_adapter_selection_changed):
                self.on_display_item_adapter_selection_changed([self.__display_item_adapters[index] for index in list(self.__selection.indexes)])
            self.__list_canvas_item.make_selection_visible()

        self.__selection_changed_listener = self.__selection.changed_event.listen(selection_changed)
        self.selected_indexes = list()
        self.on_display_item_adapter_selection_changed : typing.Optional[typing.Callable[[typing.List[DisplayItemAdapter]], None]] = None
        self.on_context_menu_event : typing.Optional[typing.Callable[[typing.Optional[DisplayItem.DisplayItem], int, int, int, int], bool]] = None
        self.on_focus_changed : typing.Optional[typing.Callable[[bool], None]] = None
        self.on_drag_started : typing.Optional[typing.Callable[[UserInterface.MimeData, numpy.ndarray], None]] = None

        # changed display items keep track of items whose content has changed
        # the content changed messages may come from a thread so have to be
        # moved to the main thread via this object.
        self.__changed_display_item_adapters = False
        self.__changed_display_item_adapters_mutex = threading.RLock()

        for index, display_item_adapter in enumerate(self.__display_item_adapters_model.display_item_adapters):
            self.__display_item_adapter_inserted("display_item_adapters", display_item_adapter, index)

    def close(self) -> None:
        for pending_task in self.__pending_tasks:
            pending_task.cancel()
        self.__pending_tasks = typing.cast(typing.List, None)
        self.__selection_changed_listener.close()
        self.__selection_changed_listener = None
        for display_item_adapter_needs_update_listener in self.__display_item_adapter_needs_update_listeners:
            display_item_adapter_needs_update_listener.close()
        self.__display_item_adapter_needs_update_listeners = typing.cast(typing.List, None)
        self.__display_item_adapter_inserted_event_listener.close()
        self.__display_item_adapter_inserted_event_listener = None
        self.__display_item_adapter_removed_event_listener.close()
        self.__display_item_adapter_removed_event_listener = None
        self.__display_item_adapter_end_changes_event_listener.close()
        self.__display_item_adapter_end_changes_event_listener = None
        self.__display_item_adapters = typing.cast(typing.List, None)
        self.on_display_item_adapter_selection_changed = None
        self.on_context_menu_event = None
        self.on_drag_started = None
        self.on_focus_changed = None
        self.on_delete_display_item_adapters = None
        self.on_key_pressed = None

    async def __update_display_item_adapters(self) -> None:
        # handle the 'changed' stuff. a call to this function is scheduled
        # whenever __changed_display_item_adapters changes.
        with self.__changed_display_item_adapters_mutex:
            changed_display_item_adapters = self.__changed_display_item_adapters
            self.__changed_display_item_adapters = False
        if changed_display_item_adapters:
            self.__list_canvas_item.update()
        self.__pending_tasks.pop(0)

    def make_selection_visible(self) -> None:
        self.__list_canvas_item.make_selection_visible()

    # this message comes from the canvas item when delete key is pressed
    def _delete_pressed(self) -> None:
        if callable(self.on_delete_display_item_adapters):
            self.on_delete_display_item_adapters(self.selected_display_item_adapters)

    @property
    def selected_display_item_adapters(self) -> typing.List[DisplayItemAdapter]:
        return [self.__display_item_adapters[index] for index in self.__selection.indexes]

    # this message comes from the canvas item when a key is pressed
    def _key_pressed(self, key: UserInterface.Key) -> bool:
        if callable(self.on_key_pressed):
            return self.on_key_pressed(key)
        return False

    @property
    def display_item_adapter_count(self) -> int:
        return len(self.__display_item_adapters)

    @property
    def display_item_adapters(self) -> typing.List[DisplayItemAdapter]:
        return copy.copy(self.__display_item_adapters)

    def _test_get_display_item_adapter(self, index: int) -> DisplayItemAdapter:
        return self.__display_item_adapters[index]

    def context_menu_event(self, index: int, x: int, y: int, gx: int, gy: int) -> bool:
        if callable(self.on_context_menu_event):
            display_item_adapter = self.__display_item_adapters[index] if index is not None else None
            display_item = display_item_adapter.display_item if display_item_adapter else None
            return self.on_context_menu_event(display_item, x, y, gx, gy)
        return False

    def drag_started(self, index: int, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> None:
        mime_data = None
        thumbnail_data = None
        display_item_adapters = self.selected_display_item_adapters
        if len(display_item_adapters) == 1:
            mime_data, thumbnail_data = self.__display_item_adapters[index].drag_started(self.ui, x, y, modifiers)
        elif len(display_item_adapters) > 1:
            mime_data = self.ui.create_mime_data()
            anchor_index = self.__selection.anchor_index or 0
            MimeTypes.mime_data_put_display_items(mime_data, [display_item_adapter.display_item for display_item_adapter in display_item_adapters if display_item_adapter.display_item])
            thumbnail_data = self.__display_item_adapters[anchor_index].calculate_thumbnail_data()
        if mime_data:
            if self.on_drag_started:
                self.on_drag_started(mime_data, thumbnail_data)

    def __display_item_adapter_needs_update(self) -> None:
        with self.__changed_display_item_adapters_mutex:
            self.__changed_display_item_adapters = True
            self.__pending_tasks.append(self.__event_loop.create_task(self.__update_display_item_adapters()))

    # call this method to insert a display item
    # not thread safe
    def __display_item_adapter_inserted(self, key: str, display_item_adapter: DisplayItemAdapter, before_index: int) -> None:
        if key == "display_item_adapters":
            self.__display_item_adapters.insert(before_index, display_item_adapter)
            self.__display_item_adapter_needs_update_listeners.insert(before_index, display_item_adapter.needs_update_event.listen(self.__display_item_adapter_needs_update))
            self.__selection.insert_index(before_index)

    # call this method to remove a display item (by index)
    # not thread safe
    def __display_item_adapter_removed(self, key: str, display_item_adapter: DisplayItemAdapter, index: int) -> None:
        if key == "display_item_adapters":
            self.__display_item_adapter_needs_update_listeners[index].close()
            del self.__display_item_adapter_needs_update_listeners[index]
            del self.__display_item_adapters[index]
            self.__selection.remove_index(index)

    def __display_item_adapter_end_changes(self, key: str) -> None:
        if key == "display_item_adapters":
            if self.canvas_item.visible:
                self.__list_canvas_item.refresh_layout()
                self.__list_canvas_item.update()


class DataGridController:
    """Control a grid of display items in a grid widget.

    The following properties are available:
        selected_indexes (r/o)

    The following methods can be called:
        close()

    The controller provides the following callbacks:
        on_delete_display_item_adapters(display_item_adapters)
        on_key_pressed(key)
        on_display_item_adapter_selection_changed(display_item_adapters)
        on_display_item_adapter_double_clicked(display_item_adapter)
        on_focus_changed(focused)
        on_context_menu_event(display_item_adapter, x, y, gx, gy)
        on_drag_started(mime_data, thumbnail_data)

    Display items should respond to these properties and methods and events:
        (method) close()
        (property, read-only) thumbnail
        (property, read-only) title_str
        (property, read-only) datetime_str
        (property, read-only) format_str
        (property, read-only) status_str
        (method) draw_grid_item(drawing_context, draw_rect)
        (method) drag_started(ui, x, y, modifiers), returns mime_data, thumbnail_data
    """

    def __init__(self, event_loop: asyncio.AbstractEventLoop, ui, display_item_adapters_model, selection, direction=GridCanvasItem.Direction.Row, wrap=True):
        super().__init__()
        self.__event_loop = event_loop
        self.__pending_tasks : typing.List = list()
        self.ui = ui
        self.__selection = selection
        self.on_delete_display_item_adapters : typing.Optional[typing.Callable[[typing.List[DisplayItemAdapter]], None]] = None
        self.on_key_pressed : typing.Optional[typing.Callable[[UserInterface.Key], bool]] = None
        self.on_display_item_adapter_double_clicked : typing.Optional[typing.Callable[[DisplayItemAdapter], bool]] = None
        self.on_display_item_adapter_selection_changed : typing.Optional[typing.Callable[[typing.List[DisplayItemAdapter]], None]] = None
        self.on_context_menu_event : typing.Optional[typing.Callable[[typing.Optional[DisplayItem.DisplayItem], int, int, int, int], bool]] = None
        self.on_focus_changed : typing.Optional[typing.Callable[[bool], None]] = None
        self.on_drag_started : typing.Optional[typing.Callable[[UserInterface.MimeData, numpy.ndarray], None]] = None

        self.__display_item_adapters : typing.List[DisplayItemAdapter] = list()
        self.__display_item_adapter_needs_update_listeners : typing.List = list()

        self.__display_item_adapters_model = display_item_adapters_model
        self.__display_item_adapter_inserted_event_listener = self.__display_item_adapters_model.item_inserted_event.listen(self.__display_item_adapter_inserted)
        self.__display_item_adapter_removed_event_listener = self.__display_item_adapters_model.item_removed_event.listen(self.__display_item_adapter_removed)
        self.__display_item_adapter_end_changes_event_listener = self.__display_item_adapters_model.end_changes_event.listen(self.__display_item_adapter_end_changes)

        class GridCanvasItemDelegate:
            def __init__(self, data_grid_controller: DataGridController):
                self.__data_grid_controller = data_grid_controller

            @property
            def item_count(self) -> int:
                return self.__data_grid_controller.display_item_adapter_count

            @property
            def items(self) -> typing.List[DisplayItemAdapter]:
                return self.__data_grid_controller.display_item_adapters

            def paint_item(self, drawing_context: DrawingContext.DrawingContext, display_item_adapter: DisplayItemAdapter, rect: Geometry.IntRect, is_selected: bool) -> None:
                display_item_adapter.draw_grid_item(drawing_context, rect)

            def on_context_menu_event(self, index: int, x: int, y: int, gx: int, gy: int) -> bool:
                return self.__data_grid_controller.context_menu_event(index, x, y, gx, gy)

            def on_delete_pressed(self) -> None:
                self.__data_grid_controller._delete_pressed()

            def on_key_pressed(self, key: UserInterface.Key) -> bool:
                return self.__data_grid_controller._key_pressed(key)

            def on_mouse_double_clicked(self, mouse_index: int, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
                return self.__data_grid_controller._double_clicked()

            def on_drag_started(self, index: int, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> None:
                self.__data_grid_controller.drag_started(index, x, y, modifiers)

        self.icon_view_canvas_item = GridCanvasItem.GridCanvasItem(GridCanvasItemDelegate(self), self.__selection, direction, wrap)

        def icon_view_canvas_item_focus_changed(focused: bool) -> None:
            self.icon_view_canvas_item.update()
            if self.on_focus_changed:
                self.on_focus_changed(focused)

        self.icon_view_canvas_item.on_focus_changed = icon_view_canvas_item_focus_changed
        self.scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(self.icon_view_canvas_item)
        self.scroll_area_canvas_item.auto_resize_contents = True
        self.scroll_group_canvas_item = CanvasItem.CanvasItemComposition()
        if (wrap and direction == GridCanvasItem.Direction.Row) or (not wrap and direction == GridCanvasItem.Direction.Column):
            self.scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(self.scroll_area_canvas_item)
            self.scroll_group_canvas_item.layout = CanvasItem.CanvasItemRowLayout()
        else:
            self.scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(self.scroll_area_canvas_item, CanvasItem.Orientation.Horizontal)
            self.scroll_group_canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        self.scroll_group_canvas_item.add_canvas_item(self.scroll_area_canvas_item)
        self.scroll_group_canvas_item.add_canvas_item(self.scroll_bar_canvas_item)

        """
        # dual scroll bars, leave here for easy testing
        self.vertical_scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(self.scroll_area_canvas_item)
        self.horizontal_scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(self.scroll_area_canvas_item, CanvasItem.Orientation.Horizontal)
        self.scroll_group_canvas_item.layout = CanvasItem.CanvasItemGridLayout(Geometry.IntSize(width=2, height=2))
        self.scroll_group_canvas_item.add_canvas_item(self.scroll_area_canvas_item, Geometry.IntPoint(x=0, y=0))
        self.scroll_group_canvas_item.add_canvas_item(self.vertical_scroll_bar_canvas_item, Geometry.IntPoint(x=1, y=0))
        self.scroll_group_canvas_item.add_canvas_item(self.horizontal_scroll_bar_canvas_item, Geometry.IntPoint(x=0, y=1))
        """

        self.canvas_item = self.scroll_group_canvas_item

        def selection_changed() -> None:
            self.selected_indexes = list(self.__selection.indexes)
            if callable(self.on_display_item_adapter_selection_changed):
                self.on_display_item_adapter_selection_changed([self.__display_item_adapters[index] for index in list(self.__selection.indexes)])
            self.icon_view_canvas_item.make_selection_visible()

        self.__selection_changed_listener = self.__selection.changed_event.listen(selection_changed)
        self.selected_indexes = list()

        # changed display items keep track of items whose content has changed
        # the content changed messages may come from a thread so have to be
        # moved to the main thread via this object.
        self.__changed_display_item_adapters = False
        self.__changed_display_item_adapters_mutex = threading.RLock()
        self.__closed = False

        for index, display_item_adapter in enumerate(self.__display_item_adapters_model.display_item_adapters):
            self.__display_item_adapter_inserted("display_item_adapters", display_item_adapter, index)

    def close(self) -> None:
        assert not self.__closed
        for pending_task in self.__pending_tasks:
            pending_task.cancel()
        self.__pending_tasks = typing.cast(typing.List, None)
        self.icon_view_canvas_item.detach_delegate()
        self.__selection_changed_listener.close()
        self.__selection_changed_listener = None
        self.__display_item_adapter_inserted_event_listener.close()
        self.__display_item_adapter_inserted_event_listener = None
        self.__display_item_adapter_removed_event_listener.close()
        self.__display_item_adapter_removed_event_listener = None
        self.__display_item_adapter_end_changes_event_listener.close()
        self.__display_item_adapter_end_changes_event_listener = None
        for display_item_adapter_needs_update_listener in self.__display_item_adapter_needs_update_listeners:
            display_item_adapter_needs_update_listener.close()
        self.__display_item_adapter_needs_update_listeners = typing.cast(typing.List, None)
        self.__display_item_adapters = typing.cast(typing.List, None)
        self.on_display_item_adapter_selection_changed = None
        self.on_context_menu_event = None
        self.on_drag_started = None
        self.on_focus_changed = None
        self.on_delete_display_item_adapters = None
        self.on_key_pressed = None
        self.on_display_item_adapter_double_clicked = None
        self.__closed = True

    async def __update_display_item_adapters(self) -> None:
        with self.__changed_display_item_adapters_mutex:
            changed_display_item_adapters = self.__changed_display_item_adapters
            self.__changed_display_item_adapters = False
        if changed_display_item_adapters:
            self.icon_view_canvas_item.update()
        self.__pending_tasks.pop(0)

    def clear_selection(self) -> None:
        self.__selection.clear()

    def make_selection_visible(self) -> None:
        self.icon_view_canvas_item.make_selection_visible()

    # this message comes from the canvas item when delete key is pressed
    def _delete_pressed(self) -> None:
        if callable(self.on_delete_display_item_adapters):
            self.on_delete_display_item_adapters(self.selected_display_item_adapters)

    @property
    def selected_display_item_adapters(self) -> typing.List[DisplayItemAdapter]:
        return [self.__display_item_adapters[index] for index in self.__selection.indexes]

    # this message comes from the canvas item when a key is pressed
    def _key_pressed(self, key: UserInterface.Key) -> bool:
        if callable(self.on_key_pressed):
            return self.on_key_pressed(key)
        return False

    # this message comes from the canvas item when a key is pressed
    def _double_clicked(self) -> bool:
        if len(self.__selection.indexes) == 1:
            if callable(self.on_display_item_adapter_double_clicked):
                return self.on_display_item_adapter_double_clicked(self.__display_item_adapters[list(self.__selection.indexes)[0]])
        return False

    @property
    def display_item_adapter_count(self) -> int:
        return len(self.__display_item_adapters)

    @property
    def display_item_adapters(self) -> typing.List[DisplayItemAdapter]:
        return copy.copy(self.__display_item_adapters)

    def context_menu_event(self, index, x, y, gx, gy):
        if callable(self.on_context_menu_event):
            display_item_adapter = self.__display_item_adapters[index] if index is not None else None
            display_item = display_item_adapter.display_item if display_item_adapter else None
            return self.on_context_menu_event(display_item, x, y, gx, gy)
        return False

    def drag_started(self, index: int, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> None:
        mime_data = None
        thumbnail_data = None
        display_item_adapters = self.selected_display_item_adapters
        if len(display_item_adapters) == 1:
            mime_data, thumbnail_data = self.__display_item_adapters[index].drag_started(self.ui, x, y, modifiers)
        elif len(display_item_adapters) > 1:
            mime_data = self.ui.create_mime_data()
            anchor_index = self.__selection.anchor_index or 0
            MimeTypes.mime_data_put_display_items(mime_data, [display_item_adapter.display_item for display_item_adapter in display_item_adapters if display_item_adapter.display_item])
            thumbnail_data = self.__display_item_adapters[anchor_index].calculate_thumbnail_data()
        if mime_data:
            if self.on_drag_started:
                self.on_drag_started(mime_data, thumbnail_data)

    def __display_item_adapter_needs_update(self) -> None:
        with self.__changed_display_item_adapters_mutex:
            self.__changed_display_item_adapters = True
            self.__pending_tasks.append(self.__event_loop.create_task(self.__update_display_item_adapters()))

    # call this method to insert a display item
    # not thread safe
    def __display_item_adapter_inserted(self, key: str, display_item_adapter: DisplayItemAdapter, before_index: int) -> None:
        if key == "display_item_adapters":
            self.__display_item_adapters.insert(before_index, display_item_adapter)
            self.__display_item_adapter_needs_update_listeners.insert(before_index, display_item_adapter.needs_update_event.listen(self.__display_item_adapter_needs_update))

    # call this method to remove a display item (by index)
    # not thread safe
    def __display_item_adapter_removed(self, key: str, display_item_adapter: DisplayItemAdapter, index: int) -> None:
        if key == "display_item_adapters":
            self.__display_item_adapter_needs_update_listeners[index].close()
            del self.__display_item_adapter_needs_update_listeners[index]
            del self.__display_item_adapters[index]

    def __display_item_adapter_end_changes(self, key: str) -> None:
        if key == "display_item_adapters":
            if self.canvas_item.visible:
                self.icon_view_canvas_item.refresh_layout()
                self.icon_view_canvas_item.update()


class DataListWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui: UserInterface.UserInterface, data_list_controller: DataListController):
        super().__init__(ui.create_column_widget())
        self.data_list_controller = data_list_controller
        data_list_widget = ui.create_canvas_widget()
        data_list_widget.canvas_item.add_canvas_item(data_list_controller.canvas_item)
        self.content_widget.add(data_list_widget)

        def data_list_drag_started(mime_data: UserInterface.MimeData, thumbnail_data: numpy.ndarray) -> None:
            self.drag(mime_data, thumbnail_data)

        data_list_controller.on_drag_started = data_list_drag_started

    def close(self) -> None:
        self.data_list_controller.on_drag_started = None
        self.data_list_controller = typing.cast(DataListController, None)
        super().close()


class DataGridWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui: UserInterface.UserInterface, data_grid_controller: DataGridController):
        super().__init__(ui.create_column_widget())
        self.data_grid_controller = data_grid_controller
        data_grid_widget = ui.create_canvas_widget()
        data_grid_widget.canvas_item.add_canvas_item(data_grid_controller.canvas_item)
        self.content_widget.add(data_grid_widget)

        def data_list_drag_started(mime_data: UserInterface.MimeData, thumbnail_data: numpy.ndarray) -> None:
            self.drag(mime_data, thumbnail_data)

        data_grid_controller.on_drag_started = data_list_drag_started

    def close(self) -> None:
        self.data_grid_controller.on_drag_started = None
        self.data_grid_controller = typing.cast(DataGridController, None)
        super().close()


class DataPanel(Panel.Panel):

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: typing.Dict):
        super().__init__(document_controller, panel_id, _("Data Items"))

        ui = document_controller.ui

        def show_context_menu(display_item: typing.Optional[DisplayItem.DisplayItem], x: int, y: int, gx: int, gy: int) -> bool:
            menu = document_controller.create_context_menu_for_display(display_item, use_selection=True)
            menu.popup(gx, gy)
            return True

        def map_display_item_to_display_item_adapter(display_item: DisplayItem.DisplayItem) -> DisplayItemAdapter:
            return DisplayItemAdapter(display_item, ui)

        def unmap_display_item_to_display_item_adapter(display_item_adapter: DisplayItemAdapter) -> None:
            display_item_adapter.close()

        self.__filtered_display_item_adapters_model = ListModel.MappedListModel(container=document_controller.filtered_display_items_model, master_items_key="display_items", items_key="display_item_adapters", map_fn=map_display_item_to_display_item_adapter, unmap_fn=unmap_display_item_to_display_item_adapter)

        self.__selection = self.document_controller.selection

        self.__focused = False

        def selection_changed() -> None:
            # called when the selection changes; notify selected display item changed if focused.
            self.__notify_focus_changed()

        self.__selection_changed_event_listener = self.__selection.changed_event.listen(selection_changed)

        def display_item_adapter_selection_changed(display_item_adapters: typing.List[DisplayItemAdapter]) -> None:
            indexes = set()
            for index, display_item_adapter in enumerate(self.__filtered_display_item_adapters_model.display_item_adapters):
                if display_item_adapter in display_item_adapters:
                    indexes.add(index)
            self.__selection.set_multiple(indexes)
            self.__notify_focus_changed()

        def focus_changed(focused: bool) -> None:
            self.focused = focused

        def delete_display_item_adapters(display_item_adapters: typing.List[DisplayItemAdapter]) -> None:
            document_controller.delete_display_items([display_item_adapter.display_item for display_item_adapter in display_item_adapters if display_item_adapter.display_item])

        self.data_list_controller = DataListController(document_controller.event_loop, ui, self.__filtered_display_item_adapters_model, self.__selection)
        self.data_list_controller.on_display_item_adapter_selection_changed = display_item_adapter_selection_changed
        self.data_list_controller.on_context_menu_event = show_context_menu
        self.data_list_controller.on_focus_changed = focus_changed
        self.data_list_controller.on_delete_display_item_adapters = delete_display_item_adapters

        self.data_grid_controller = DataGridController(document_controller.event_loop, ui, self.__filtered_display_item_adapters_model, self.__selection)
        self.data_grid_controller.on_display_item_adapter_selection_changed = display_item_adapter_selection_changed
        self.data_grid_controller.on_context_menu_event = show_context_menu
        self.data_grid_controller.on_focus_changed = focus_changed
        self.data_grid_controller.on_delete_display_item_adapters = delete_display_item_adapters

        data_list_widget = DataListWidget(ui, self.data_list_controller)
        data_grid_widget = DataGridWidget(ui, self.data_grid_controller)

        list_icon_button = CanvasItem.BitmapButtonCanvasItem(CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/list_icon_20.png")))
        grid_icon_button = CanvasItem.BitmapButtonCanvasItem(CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/grid_icon_20.png")))

        list_icon_button.sizing.set_fixed_size(Geometry.IntSize(20, 20))
        grid_icon_button.sizing.set_fixed_size(Geometry.IntSize(20, 20))

        button_row = CanvasItem.CanvasItemComposition()
        button_row.layout = CanvasItem.CanvasItemRowLayout(spacing=4)
        button_row.add_canvas_item(list_icon_button)
        button_row.add_canvas_item(grid_icon_button)

        buttons_widget = ui.create_canvas_widget(properties={"height": 20, "width": 44})
        buttons_widget.canvas_item.add_canvas_item(button_row)

        search_widget = ui.create_row_widget()
        search_widget.add_spacing(8)
        search_widget.add(ui.create_label_widget(_("Filter")))
        search_widget.add_spacing(8)
        search_line_edit = ui.create_line_edit_widget()
        search_line_edit.placeholder_text = _("No Filter")
        search_line_edit.clear_button_enabled = True  # Qt 5.3 doesn't signal text edited or editing finished when clearing. useless so disabled.
        search_line_edit.on_text_edited = self.document_controller.filter_controller.text_filter_changed
        search_line_edit.on_editing_finished = self.document_controller.filter_controller.text_filter_changed
        search_widget.add(search_line_edit)
        search_widget.add_spacing(6)
        search_widget.add(buttons_widget)
        search_widget.add_spacing(8)

        self.data_view_widget = ui.create_stack_widget()
        self.data_view_widget.add(data_list_widget)
        self.data_view_widget.add(data_grid_widget)
        self.data_view_widget.current_index = 0

        self.__view_button_group = CanvasItem.RadioButtonGroup([list_icon_button, grid_icon_button])
        self.__view_button_group.current_index = 0
        self.__view_button_group.on_current_index_changed = lambda index: setattr(self.data_view_widget, "current_index", index)

        widget = ui.create_column_widget(properties=properties)
        widget.add(self.data_view_widget)
        widget.add_spacing(6)
        widget.add(search_widget)
        widget.add_spacing(6)

        self.widget = widget

        self._data_list_widget = data_list_widget
        self._data_grid_widget = data_grid_widget

    def close(self) -> None:
        # close the widget to stop repainting the widgets before closing the controllers.
        super().close()
        # finish closing
        self.data_list_controller.close()
        self.data_list_controller = typing.cast(DataListController, None)
        self.data_grid_controller.close()
        self.data_grid_controller = typing.cast(DataGridController, None)
        self.__filtered_display_item_adapters_model.close()
        self.__filtered_display_item_adapters_model = typing.cast(ListModel.MappedListModel, None)
        # button group
        self.__view_button_group.close()
        self.__view_button_group = None

    def __notify_focus_changed(self) -> None:
        if self.__focused:
            if len(self.__selection.indexes) == 1:
                display_item_adapter = self.__filtered_display_item_adapters_model.display_item_adapters[list(self.__selection.indexes)[0]]
                self.document_controller.notify_focused_display_changed(display_item_adapter.display_item)
            else:
                self.document_controller.notify_focused_display_changed(None)

    @property
    def focused(self) -> bool:
        return self.__focused

    @focused.setter
    def focused(self, value: bool) -> None:
        self.__focused = value
        self.__notify_focus_changed()
