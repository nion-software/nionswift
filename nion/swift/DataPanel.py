from __future__ import annotations

# standard libraries
import asyncio
import copy
import gettext
import pkgutil
import threading
import typing

# third party libraries
import numpy.typing

# local libraries
from nion.data import Image
from nion.swift import MimeTypes
from nion.swift import Panel
from nion.swift import Thumbnails
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import Persistence
from nion.ui import Bitmap
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import GridCanvasItem
from nion.ui import ListCanvasItem
from nion.ui import Widgets
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel
from nion.utils import Model
from nion.utils import Process
from nion.utils import ReferenceCounting
from nion.utils import Stream

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.ui import UserInterface
    from nion.utils import Selection

_NDArray = numpy.typing.NDArray[typing.Any]

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
        self.ui = ui
        self.needs_update_event = Event.Event()
        self.__list_item_drawing_context: typing.Optional[DrawingContext.DrawingContext] = None
        self.__grid_item_drawing_context: typing.Optional[DrawingContext.DrawingContext] = None

        self.__display_item = display_item

        def display_item_changed() -> None:
            self.__list_item_drawing_context = None
            self.__grid_item_drawing_context = None
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
            self.__display_item = typing.cast(typing.Any, None)

        self.__display_item_about_to_be_removed_event_listener = display_item.about_to_be_removed_event.listen(display_item_removed) if display_item else None

        self.__thumbnail_updated_event_listener: typing.Optional[Event.EventListener] = None
        self.__thumbnail_source : typing.Optional[Thumbnails.ThumbnailSource] = None

    def close(self) -> None:
        # remove the listener.
        self.__thumbnail_updated_event_listener = None
        self.__thumbnail_source = None
        if self.__display_changed_event_listener:
            self.__display_changed_event_listener.close()
            self.__display_changed_event_listener = None
        if self.__display_item_about_to_be_removed_event_listener:
            self.__display_item_about_to_be_removed_event_listener.close()
            self.__display_item_about_to_be_removed_event_listener = None

    @property
    def display_item(self) -> DisplayItem.DisplayItem:
        return self.__display_item

    @property
    def data_item(self) -> typing.Optional[DataItem.DataItem]:
        return self.__display_item.data_item if self.__display_item else None

    def __create_thumbnail(self, draw_rect: Geometry.IntRect) -> DrawingContext.DrawingContext:
        drawing_context = DrawingContext.DrawingContext()
        if self.__display_item:
            thumbnail_data = self.calculate_thumbnail_data()
            if thumbnail_data is not None:
                draw_rect_f = Geometry.fit_to_size(draw_rect, typing.cast(typing.Tuple[int, int], thumbnail_data.shape))
                drawing_context.draw_image(thumbnail_data, draw_rect_f.left, draw_rect_f.top, draw_rect_f.width, draw_rect_f.height)
        return drawing_context

    @property
    def title_str(self) -> str:
        return self.__display_item.displayed_title if self.__display_item else str()

    @property
    def format_str(self) -> str:
        format_str = self.__display_item.size_and_data_format_as_string if self.__display_item else str()
        storage_space_string = self.__display_item.storage_space_string if self.__display_item else str()
        return " ".join([format_str, storage_space_string])

    @property
    def datetime_str(self) -> str:
        return self.__display_item.date_for_sorting_local_as_string if self.__display_item else str()

    @property
    def status_str(self) -> str:
        return self.__display_item.status_str if self.__display_item else str()

    @property
    def project_str(self) -> str:
        return self.__display_item.project_str if self.__display_item else str()

    @property
    def list_tool_tip(self) -> str:
        return self.__display_item.list_tool_tip_str if self.__display_item else str()

    @property
    def grid_tool_tip(self) -> str:
        return self.__display_item.grid_tool_tip_str if self.__display_item else str()

    def drag_started(self, ui: UserInterface.UserInterface, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> typing.Tuple[typing.Optional[UserInterface.MimeData], typing.Optional[_NDArray]]:
        if self.__display_item:
            mime_data = self.ui.create_mime_data()
            if self.__display_item:
                MimeTypes.mime_data_put_display_item(mime_data, self.__display_item)
            thumbnail_data = self.calculate_thumbnail_data()
            if thumbnail_data is not None:
                # scaling is very slow
                thumbnail_data = Image.get_rgba_data_from_rgba(Image.scaled(Image.get_rgba_view_from_rgba_data(thumbnail_data), tuple(Geometry.IntSize(w=80, h=80))))
            return mime_data, thumbnail_data
        return None, None

    def calculate_thumbnail_data(self) -> typing.Optional[_NDArray]:
        # grab the display specifier and if there is a display, handle thumbnail updating.
        if self.__display_item and not self.__thumbnail_source:
            self.__thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.ui, self.__display_item)

            def thumbnail_updated() -> None:
                self.__list_item_drawing_context = None
                self.__grid_item_drawing_context = None
                self.needs_update_event.fire()

            assert self.__thumbnail_source  # type checker
            self.__thumbnail_updated_event_listener = self.__thumbnail_source.thumbnail_updated_event.listen(thumbnail_updated)

        return self.__thumbnail_source.thumbnail_data if self.__thumbnail_source else None

    def draw_list_item(self, drawing_context: DrawingContext.DrawingContext, rect: Geometry.IntRect) -> None:
        if not self.__list_item_drawing_context:
            list_item_drawing_context = DrawingContext.DrawingContext()
            with list_item_drawing_context.saver():
                item_rect = Geometry.IntRect(Geometry.IntPoint(), size=rect.size)
                draw_rect = Geometry.IntRect(origin=item_rect.top_left + Geometry.IntPoint(y=4, x=4), size=Geometry.IntSize(h=72, w=72))
                list_item_drawing_context.add(self.__create_thumbnail(draw_rect))
                list_item_drawing_context.fill_style = "#000"
                list_item_drawing_context.font = "11px serif"
                list_item_drawing_context.fill_text(self.title_str, item_rect.left + 4 + 72 + 4, item_rect.top + 4 + 12)
                list_item_drawing_context.fill_text(self.format_str, item_rect.left + 4 + 72 + 4, item_rect.top + 4 + 12 + 15)
                list_item_drawing_context.fill_text(self.datetime_str, item_rect.left + 4 + 72 + 4, item_rect.top + 4 + 12 + 15 + 15)
                if status_str := self.status_str:
                    list_item_drawing_context.fill_text(status_str, item_rect.left + 4 + 72 + 4, item_rect.top + 4 + 12 + 15 + 15 + 15)
                else:
                    list_item_drawing_context.fill_style = "#888"
                    list_item_drawing_context.fill_text(self.project_str, item_rect.left + 4 + 72 + 4, item_rect.top + 4 + 12 + 15 + 15 + 15)
            self.__list_item_drawing_context = list_item_drawing_context
        with drawing_context.saver():
            drawing_context.translate(rect.left, rect.top)
            drawing_context.add(self.__list_item_drawing_context)

    def draw_grid_item(self, drawing_context: DrawingContext.DrawingContext, rect: Geometry.IntRect) -> None:
        if not self.__grid_item_drawing_context:
            grid_item_drawing_context = DrawingContext.DrawingContext()
            item_rect = Geometry.IntRect(Geometry.IntPoint(), size=rect.size)
            grid_item_drawing_context.add(self.__create_thumbnail(item_rect.inset(6)))
            self.__grid_item_drawing_context = grid_item_drawing_context
        with drawing_context.saver():
            drawing_context.translate(rect.left, rect.top)
            drawing_context.add(self.__grid_item_drawing_context)


class ItemExplorerCanvasItemLike(typing.Protocol):
    def detach_delegate(self) -> None: ...
    def make_selection_visible(self) -> None: ...


class ThreadHelper:
    def __init__(self, event_loop: asyncio.AbstractEventLoop) -> None:
        self.__event_loop = event_loop
        self.__pending_calls: typing.Dict[str, asyncio.Handle] = dict()

    def close(self) -> None:
        for handle in self.__pending_calls.values():
            handle.cancel()
        self.__pending_calls = dict()

    def call_on_main_thread(self, key: str, func: typing.Callable[[], None]) -> None:
        if threading.current_thread() != threading.main_thread():
            handle = self.__pending_calls.pop(key, None)
            if handle:
                handle.cancel()
            def audited_func() -> None:
                with Process.audit(f"threadhelper.{key}"):
                    func()
            self.__pending_calls[key] = self.__event_loop.call_soon_threadsafe(audited_func)
        else:
            func()


class ItemExplorerController:
    def __init__(self, ui: UserInterface.UserInterface,
                 canvas_item: CanvasItem.AbstractCanvasItem,
                 display_item_adapters_model: ListModel.MappedListModel, selection: Selection.IndexedSelection,
                 direction: GridCanvasItem.Direction = GridCanvasItem.Direction.Row, wrap: bool = True) -> None:
        self.__pending_tasks: typing.List[asyncio.Task[None]] = list()
        self.ui = ui
        self.__selection = selection
        self.__display_item_adapters: typing.List[DisplayItemAdapter] = list()
        self.__display_item_adapter_needs_update_listeners: typing.List[Event.EventListener] = list()
        self.__display_item_adapters_model = display_item_adapters_model
        self.__display_item_adapter_inserted_event_listener = self.__display_item_adapters_model.item_inserted_event.listen(self.__display_item_adapter_inserted)
        self.__display_item_adapter_removed_event_listener = self.__display_item_adapters_model.item_removed_event.listen(self.__display_item_adapter_removed)
        self.__display_item_adapter_end_changes_event_listener = self.__display_item_adapters_model.end_changes_event.listen(self.__display_item_adapter_end_changes)
        self.on_delete_display_item_adapters: typing.Optional[typing.Callable[[typing.List[DisplayItemAdapter]], None]] = None
        self.on_key_pressed: typing.Optional[typing.Callable[[UserInterface.Key], bool]] = None
        self.on_display_item_adapter_double_clicked: typing.Optional[typing.Callable[[DisplayItemAdapter], bool]] = None
        self.on_context_menu_event: typing.Optional[typing.Callable[[typing.Optional[DisplayItem.DisplayItem], typing.List[DisplayItem.DisplayItem], int, int, int, int], bool]] = None
        self.on_focus_changed: typing.Optional[typing.Callable[[bool], None]] = None
        self.on_drag_started: typing.Optional[typing.Callable[[UserInterface.MimeData, typing.Optional[_NDArray]], None]] = None
        # changed display items keep track of items whose content has changed
        # the content changed messages may come from a thread so have to be
        # moved to the main thread via this object.
        self.__changed_display_item_adapters = False
        self.__changed_display_item_adapters_mutex = threading.RLock()
        self.__list_canvas_item = canvas_item

        def focus_changed(focused: bool) -> None:
            self.__list_canvas_item.update()
            if self.on_focus_changed:
                self.on_focus_changed(focused)

        self.__list_canvas_item.on_focus_changed = focus_changed
        self.scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(self.__list_canvas_item)
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

        self.__canvas_item = self.scroll_group_canvas_item

        def selection_changed() -> None:
            self.selected_indexes = list(self.__selection.indexes)
            typing.cast(ItemExplorerCanvasItemLike, self.__list_canvas_item).make_selection_visible()

        self.__selection_changed_listener: typing.Optional[Event.EventListener] = self.__selection.changed_event.listen(selection_changed)
        self.selected_indexes = list()

        for index, display_item_adapter in enumerate(self.__display_item_adapters_model.display_item_adapters):
            self.__display_item_adapter_inserted("display_item_adapters", display_item_adapter, index)

        self.__closed = False

    def close(self) -> None:
        assert not self.__closed
        for pending_task in self.__pending_tasks:
            pending_task.cancel()
        self.__pending_tasks = typing.cast(typing.Any, None)
        typing.cast(ItemExplorerCanvasItemLike, self.__list_canvas_item).detach_delegate()
        if self.__selection_changed_listener:
            self.__selection_changed_listener.close()
            self.__selection_changed_listener = None
        for display_item_adapter_needs_update_listener in self.__display_item_adapter_needs_update_listeners:
            display_item_adapter_needs_update_listener.close()
        self.__display_item_adapter_needs_update_listeners = typing.cast(typing.Any, None)
        self.__display_item_adapter_inserted_event_listener.close()
        self.__display_item_adapter_inserted_event_listener = typing.cast(typing.Any, None)
        self.__display_item_adapter_removed_event_listener.close()
        self.__display_item_adapter_removed_event_listener = typing.cast(typing.Any, None)
        self.__display_item_adapter_end_changes_event_listener.close()
        self.__display_item_adapter_end_changes_event_listener = typing.cast(typing.Any, None)
        self.__display_item_adapters = typing.cast(typing.Any, None)
        self.__display_item_adapters_model = typing.cast(typing.Any, None)
        self.on_context_menu_event = None
        self.on_drag_started = None
        self.on_focus_changed = None
        self.on_delete_display_item_adapters = None
        self.on_key_pressed = None
        self.on_display_item_adapter_double_clicked = None
        self.__closed = True

    @property
    def canvas_item(self) -> CanvasItem.AbstractCanvasItem:
        return self.__canvas_item

    def request_focus(self) -> None:
        self.__list_canvas_item.request_focus()

    def clear_selection(self) -> None:
        self.__selection.clear()

    def make_selection_visible(self) -> None:
        typing.cast(ItemExplorerCanvasItemLike, self.__list_canvas_item).make_selection_visible()

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

    def context_menu_event(self, index: typing.Optional[int], x: int, y: int, gx: int, gy: int) -> bool:
        if callable(self.on_context_menu_event):
            display_item_adapter = self.__display_item_adapters[index] if index is not None else None
            display_item = display_item_adapter.display_item if display_item_adapter else None
            display_items = list()
            for display_item_adapter in self.selected_display_item_adapters:
                display_item = display_item_adapter.display_item
                if display_item:
                    display_items.append(display_item)
            return self.on_context_menu_event(display_item, display_items, x, y, gx, gy)
        return False

    def drag_started(self, index: int, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> None:
        mime_data = None
        thumbnail_data = None
        display_item_adapters = self.selected_display_item_adapters
        if len(display_item_adapters) <= 1 and 0 <= index < len(self.__display_item_adapters):
            mime_data, thumbnail_data = self.__display_item_adapters[index].drag_started(self.ui, x, y, modifiers)
        elif len(display_item_adapters) > 1:
            mime_data = self.ui.create_mime_data()
            anchor_index = self.__selection.anchor_index or 0
            MimeTypes.mime_data_put_display_items(mime_data,
                                                  [display_item_adapter.display_item for display_item_adapter in
                                                   display_item_adapters if display_item_adapter.display_item])
            thumbnail_data = self.__display_item_adapters[anchor_index].calculate_thumbnail_data()
        if mime_data:
            if callable(self.on_drag_started):
                self.on_drag_started(mime_data, thumbnail_data)

    # this message comes from the canvas item when a key is pressed
    def _double_clicked(self) -> bool:
        if len(self.__selection.indexes) == 1:
            if callable(self.on_display_item_adapter_double_clicked):
                return self.on_display_item_adapter_double_clicked(self.__display_item_adapters[list(self.__selection.indexes)[0]])
        return False

    def _test_get_display_item_adapter(self, index: int) -> DisplayItemAdapter:
        return self.__display_item_adapters[index]

    def __display_item_adapter_needs_update(self) -> None:
        self.__list_canvas_item.update()

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
                # note: layout is not needed here since only an individual adapter has changed
                # self.__list_canvas_item.refresh_layout()
                self.__list_canvas_item.update()


class GridCanvasItemDelegate(GridCanvasItem.GridCanvasItemDelegate):
    def __init__(self, data_grid_controller: DataGridController):
        self.__data_grid_controller = data_grid_controller

    @property
    def item_count(self) -> int:
        return self.__data_grid_controller.display_item_adapter_count

    @property
    def items(self) -> typing.Sequence[DisplayItemAdapter]:
        return self.__data_grid_controller.display_item_adapters

    @items.setter
    def items(self, value: typing.Sequence[DisplayItemAdapter]) -> None:
        raise NotImplementedError()

    def item_tool_tip(self, index: int) -> typing.Optional[str]:
        items = self.items
        if 0 <= index < len(items):
            return items[index].grid_tool_tip
        return None

    def paint_item(self, drawing_context: DrawingContext.DrawingContext, display_item_adapter: DisplayItemAdapter, rect: Geometry.IntRect, is_selected: bool) -> None:
        display_item_adapter.draw_grid_item(drawing_context, rect)

    def context_menu_event(self, index: typing.Optional[int], x: int, y: int, gx: int, gy: int) -> bool:
        return self.__data_grid_controller.context_menu_event(index, x, y, gx, gy)

    def delete_pressed(self) -> None:
        self.__data_grid_controller._delete_pressed()

    def key_pressed(self, key: UserInterface.Key) -> bool:
        return self.__data_grid_controller._key_pressed(key)

    def mouse_double_clicked(self, mouse_index: int, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        return self.__data_grid_controller._double_clicked()

    def drag_started(self, index: int, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> None:
        self.__data_grid_controller.drag_started(index, x, y, modifiers)


class DataGridController(ItemExplorerController):
    def __init__(self, ui: UserInterface.UserInterface, display_item_adapters_model: ListModel.MappedListModel,
                 selection: Selection.IndexedSelection,
                 direction: GridCanvasItem.Direction = GridCanvasItem.Direction.Row, wrap: bool = True) -> None:
        canvas_item = GridCanvasItem.GridCanvasItem(GridCanvasItemDelegate(self), selection, direction, wrap)
        super().__init__(ui, canvas_item, display_item_adapters_model, selection, direction, wrap)


class ItemExplorerWidget(Widgets.CompositeWidgetBase):
    """Provide a widget wrapper for an item explorer controller."""

    def __init__(self, ui: UserInterface.UserInterface, item_explorer_controller: ItemExplorerController):
        # note: the expanding policies ensure that the first update has non-empty widget size.
        # this showed up when switching from list to grid the first time.
        content_widget = ui.create_column_widget(properties={"size-policy-horizontal": "expanding", "size-policy-vertical": "expanding"})
        super().__init__(content_widget)
        self.item_explorer_controller = item_explorer_controller
        data_list_widget = ui.create_canvas_widget()
        data_list_widget.canvas_item.add_canvas_item(item_explorer_controller.canvas_item)
        content_widget.add(data_list_widget)

        def data_list_drag_started(mime_data: UserInterface.MimeData, thumbnail_data: typing.Optional[_NDArray]) -> None:
            self.drag(mime_data, thumbnail_data)

        item_explorer_controller.on_drag_started = data_list_drag_started

    def close(self) -> None:
        self.item_explorer_controller.on_drag_started = None
        self.item_explorer_controller = typing.cast(typing.Any, None)
        super().close()


class DataPanelListItemComposer(CanvasItem.BaseComposer):
    def __init__(self, canvas_item: CanvasItem.AbstractCanvasItem, layout_sizing: CanvasItem.Sizing, cache: CanvasItem.ComposerCache,
                 thumbnail: typing.Optional[Bitmap.Bitmap], line_height: int, displayed_title: str, format_str: str, datetime_str: str, status_str: str) -> None:
        super().__init__(canvas_item, layout_sizing, cache)
        self.__bitmap = thumbnail
        self.__line_height = line_height
        self.__displayed_title = displayed_title
        self.__format_str = format_str
        self.__datetime_str = datetime_str
        self.__status_str = status_str

    def _repaint(self, drawing_context: DrawingContext.DrawingContext, canvas_bounds: Geometry.IntRect, composer_cache: CanvasItem.ComposerCache) -> None:
        text_font = "11px sans-serif"
        text_color = "black"

        line_number = 1
        line_height = self.__line_height + 2

        if self.__displayed_title:
            drawing_context.font = text_font
            drawing_context.text_baseline = "bottom"
            drawing_context.text_align = "left"
            drawing_context.fill_style = text_color
            drawing_context.fill_text(self.__displayed_title, 82, line_height * line_number)
            line_number += 1

        if self.__format_str:
            drawing_context.font = text_font
            drawing_context.text_baseline = "bottom"
            drawing_context.text_align = "left"
            drawing_context.fill_style = text_color
            drawing_context.fill_text(self.__format_str, 82, line_height * line_number)
            line_number += 1

        if self.__datetime_str:
            drawing_context.font = text_font
            drawing_context.text_baseline = "bottom"
            drawing_context.text_align = "left"
            drawing_context.fill_style = text_color
            drawing_context.fill_text(self.__datetime_str, 82, line_height * line_number)
            line_number += 1

        if self.__status_str:
            drawing_context.font = text_font
            drawing_context.text_baseline = "bottom"
            drawing_context.text_align = "left"
            drawing_context.fill_style = text_color
            drawing_context.fill_text(self.__status_str, 82, line_height * line_number)
            line_number += 1

        if self.__bitmap and self.__bitmap.rgba_bitmap_data is not None:
            image_size = self.__bitmap.computed_shape
            if image_size.height > 0 and image_size.width > 0:
                rect = Geometry.IntRect(Geometry.IntPoint(y=4, x=4), size=Geometry.IntSize(h=72, w=72))
                display_rect = Geometry.fit_to_size(rect, image_size)
                display_height = display_rect.height
                display_width = display_rect.width
                if display_rect and display_width > 0 and display_height > 0:
                    display_top = display_rect.top
                    display_left = display_rect.left
                    drawing_context.draw_image(self.__bitmap.rgba_bitmap_data, display_left, display_top, display_width, display_height)


class DataPanelListItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw a data panel list item.

    This is critical performance code. It is called for every item in the list. So use a custom renderer.
    """

    def __init__(self, display_item: DisplayItem.DisplayItem, ui: UserInterface.UserInterface, font_metrics_fn: typing.Callable[[str, str], UserInterface.FontMetrics]) -> None:
        super().__init__()
        self.__display_item = display_item
        self.__ui = ui
        self.__font_metrics_fn = font_metrics_fn
        self.__thumbnail: typing.Optional[Bitmap.Bitmap] = None

        def thumbnail_updated() -> None:
            bitmap_data = self.__thumbnail_source.thumbnail_data if self.__thumbnail_source else None
            self.__thumbnail = Bitmap.Bitmap(rgba_bitmap_data=bitmap_data)
            self.update()

        self.__thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.__ui, self.__display_item)
        self.__thumbnail_updated_event_listener = self.__thumbnail_source.thumbnail_updated_event.listen(thumbnail_updated)

        thumbnail_updated()

        self.__item_changed_listener = display_item.item_changed_event.listen(ReferenceCounting.weak_partial(DataPanelListItem.__item_changed, self))

        self.update_sizing(self.sizing.with_fixed_height(72))
        self.update_sizing(self.sizing.with_fixed_width(CanvasItem.SizingEnum.UNRESTRAINED))

    def _get_composer(self, composer_cache: CanvasItem.ComposerCache) -> CanvasItem.BaseComposer:
        line_height = self.__font_metrics_fn("11px sans-serif", "M").height
        return DataPanelListItemComposer(self, self.layout_sizing, composer_cache, self.__thumbnail, line_height, self.title, self.format_str, self.datetime_str, self.status_str)

    def close(self) -> None:
        self.__thumbnail_updated_event_listener = typing.cast(typing.Any, None)
        self.__thumbnail_source = typing.cast(typing.Any, None)
        super().close()

    @property
    def display_item(self) -> DisplayItem.DisplayItem:
        return self.__display_item

    @property
    def title(self) -> str:
        return self.__display_item.displayed_title

    @property
    def format_str(self) -> str:
        format_str = self.__display_item.size_and_data_format_as_string if self.__display_item else str()
        storage_space_string = self.__display_item.storage_space_string if self.__display_item else str()
        return " ".join([format_str, storage_space_string])

    @property
    def datetime_str(self) -> str:
        return self.__display_item.date_for_sorting_local_as_string if self.__display_item else str()

    @property
    def status_str(self) -> str:
        return self.__display_item.status_str if self.__display_item else str()

    def __item_changed(self) -> None:
        self.update()


class DataPanel(Panel.Panel):

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: Persistence.PersistentDictType) -> None:
        super().__init__(document_controller, panel_id, _("Data Items"))

        ui = document_controller.ui

        def show_context_menu(display_item: typing.Optional[DisplayItem.DisplayItem], display_items: typing.List[DisplayItem.DisplayItem], x: int, y: int, gx: int, gy: int) -> bool:
            document_controller = self.document_controller
            menu = document_controller.create_context_menu()
            action_context = document_controller._get_action_context_for_display_items(display_items, None)
            document_controller.populate_context_menu(menu, action_context)
            menu.add_separator()
            document_controller.add_action_to_menu(menu, "item.delete", action_context)
            menu.popup(gx, gy)
            return True

        def map_display_item_to_display_item_adapter(display_item: DisplayItem.DisplayItem) -> DisplayItemAdapter:
            return DisplayItemAdapter(display_item, ui)

        def unmap_display_item_to_display_item_adapter(display_item_adapter: DisplayItemAdapter) -> None:
            display_item_adapter.close()

        display_items_model = document_controller.filtered_display_items_model

        self.__filtered_display_item_adapters_model = ListModel.MappedListModel(container=display_items_model, master_items_key="display_items", items_key="display_item_adapters", map_fn=map_display_item_to_display_item_adapter, unmap_fn=unmap_display_item_to_display_item_adapter)

        self.__selection = self.document_controller.selection

        self.__focused = False

        def selection_changed() -> None:
            # called when the selection changes; notify selected display item changed if focused.
            self.__notify_focus_changed()

        self.__selection_changed_event_listener = self.__selection.changed_event.listen(selection_changed)

        def focus_changed(focused: bool) -> None:
            self.focused = focused

        def delete_display_item_adapters(display_item_adapters: typing.List[DisplayItemAdapter]) -> None:
            document_controller.delete_display_items([display_item_adapter.display_item for display_item_adapter in display_item_adapters if display_item_adapter.display_item])

        self.data_grid_controller = DataGridController(ui, self.__filtered_display_item_adapters_model, self.__selection)
        self.data_grid_controller.on_context_menu_event = show_context_menu
        self.data_grid_controller.on_focus_changed = focus_changed
        self.data_grid_controller.on_delete_display_item_adapters = delete_display_item_adapters

        def list_item_factory(item: typing.Any, is_selected_model: Model.PropertyModel[bool]) -> CanvasItem.AbstractCanvasItem:
            return DataPanelListItem(typing.cast(DisplayItem.DisplayItem, item), document_controller.ui, document_controller.get_font_metrics)

        class ListItemDelegate(ListCanvasItem.ListCanvasItem2Delegate):
            def __init__(self, data_panel: DataPanel, selection: Selection.IndexedSelection) -> None:
                self.__data_panel = data_panel
                self.__selection = selection

            def item_tool_tip(self, item: typing.Any) -> typing.Optional[str]:
                display_item = typing.cast(DisplayItem.DisplayItem, item)
                return display_item.list_tool_tip_str

            def context_menu_event(self, context_menu_event: ListCanvasItem.ListCanvasItem2ContextMenuEvent) -> bool:
                display_items = tuple(typing.cast(DisplayItem.DisplayItem, item) for item in context_menu_event.selected_items)
                menu = document_controller.create_context_menu()
                action_context = document_controller._get_action_context_for_display_items(display_items, None)
                document_controller.populate_context_menu(menu, action_context)
                menu.add_separator()
                document_controller.add_action_to_menu(menu, "item.delete", action_context)
                menu.popup(context_menu_event.gp.x, context_menu_event.gp.y)
                return True

            def delete_event(self, delete_event: ListCanvasItem.ListCanvasItem2DeleteEvent) -> bool:
                display_items = tuple(typing.cast(DisplayItem.DisplayItem, item) for item in delete_event.selected_items)
                document_controller.delete_display_items(display_items)
                return True

            def drag_started_event(self, drag_started_event: ListCanvasItem.ListCanvasItem2DragStartedEvent) -> bool:
                mime_data, thumbnail_data = self._get_mime_data_and_thumbnail_data(drag_started_event)
                if mime_data:
                    self.__data_panel.widget.drag(mime_data, thumbnail_data)
                    return True
                return False

            def _get_mime_data_and_thumbnail_data(self, drag_started_event: ListCanvasItem.ListCanvasItem2DragStartedEvent) -> typing.Tuple[typing.Optional[UserInterface.MimeData], typing.Optional[_NDArray]]:
                mime_data = None
                thumbnail_data = None
                display_item = typing.cast(DisplayItem.DisplayItem, drag_started_event.item)
                display_items = tuple(
                    typing.cast(DisplayItem.DisplayItem, item) for item in drag_started_event.selected_items)
                if len(display_items) <= 1 and display_item is not None:
                    mime_data = document_controller.ui.create_mime_data()
                    MimeTypes.mime_data_put_display_item(mime_data, display_item)
                    thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.__data_panel.ui, display_item)
                    thumbnail_data = thumbnail_source.thumbnail_data
                    if thumbnail_data is not None:
                        # scaling is very slow
                        thumbnail_data = Image.get_rgba_data_from_rgba(
                            Image.scaled(Image.get_rgba_view_from_rgba_data(thumbnail_data),
                                         tuple(Geometry.IntSize(w=80, h=80))))
                elif len(display_items) > 1:
                    mime_data = document_controller.ui.create_mime_data()
                    MimeTypes.mime_data_put_display_items(mime_data, display_items)
                    anchor_index = self.__selection.anchor_index or 0
                    thumbnail_display_item = display_items[anchor_index]
                    thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.__data_panel.ui, thumbnail_display_item)
                    thumbnail_data = thumbnail_source.thumbnail_data
                return mime_data, thumbnail_data

        list_item_delegate = ListItemDelegate(self, self.__selection)
        list_canvas_item = ListCanvasItem.ListCanvasItem2(display_items_model, self.__selection, list_item_factory, list_item_delegate, item_height=80, key="display_items")
        scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(list_canvas_item)
        scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(scroll_area_canvas_item, CanvasItem.Orientation.Vertical)
        scroll_group_canvas_item = CanvasItem.CanvasItemComposition()
        scroll_group_canvas_item.layout = CanvasItem.CanvasItemRowLayout()
        scroll_group_canvas_item.add_canvas_item(scroll_area_canvas_item)
        scroll_group_canvas_item.add_canvas_item(scroll_bar_canvas_item)

        def begin_changes(key: str) -> None:
            list_canvas_item._begin_batch_update()

        def end_changes(key: str) -> None:
            list_canvas_item._end_batch_update()

        # the display items model can notify us when it is about to change. in order to gang up changes, watch
        # for these notification events and tell the list canvas item to only update at the end of the changes.
        self.__display_items_begin_changes_listener = display_items_model.begin_changes_event.listen(begin_changes)
        self.__display_items_end_changes_listener = display_items_model.end_changes_event.listen(end_changes)

        data_list_canvas_item = scroll_group_canvas_item

        data_list_widget = ui.create_canvas_widget()
        data_list_widget.canvas_item.add_canvas_item(data_list_canvas_item)

        # for testing
        self._list_canvas_item = list_canvas_item
        self._scroll_area_canvas_item = scroll_area_canvas_item
        self._scroll_bar_canvas_item = scroll_bar_canvas_item

        data_grid_widget = ItemExplorerWidget(ui, self.data_grid_controller)

        list_icon_20_bytes = pkgutil.get_data(__name__, "resources/list_icon_20.png")
        grid_icon_20_bytes = pkgutil.get_data(__name__, "resources/grid_icon_20.png")
        list_icon_20_bytes = list_icon_20_bytes or bytes()
        grid_icon_20_bytes = grid_icon_20_bytes or bytes()
        list_icon_button = CanvasItem.BitmapButtonCanvasItem(CanvasItem.load_rgba_data_from_bytes(list_icon_20_bytes))
        grid_icon_button = CanvasItem.BitmapButtonCanvasItem(CanvasItem.load_rgba_data_from_bytes(grid_icon_20_bytes))

        list_icon_button.update_sizing(list_icon_button.sizing.with_fixed_size(Geometry.IntSize(20, 20)))
        grid_icon_button.update_sizing(grid_icon_button.sizing.with_fixed_size(Geometry.IntSize(20, 20)))

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

        self.__filter_description = ui.create_label_widget(_("All Items"))

        status_row = ui.create_row_widget()
        status_row.add_spacing(8)
        status_row.add(self.__filter_description)
        status_row.add_stretch()

        divider_widget = ui.create_canvas_widget(properties={"height": 2})
        divider_widget.canvas_item.add_canvas_item(CanvasItem.DividerCanvasItem(orientation="horizontal"))

        self.__status_section = ui.create_column_widget()
        self.__status_section.add_spacing(4)
        self.__status_section.add(status_row)
        self.__status_section.add_spacing(2)
        self.__status_section.add(divider_widget)

        widget = ui.create_column_widget(properties=properties)
        widget.add(self.__status_section)
        widget.add(self.data_view_widget)
        widget.add_spacing(6)
        widget.add(search_widget)
        widget.add_spacing(6)

        self.widget = widget

        self._data_list_widget = data_list_widget
        self._data_grid_widget = data_grid_widget

        def update_filter_description(collection_info: typing.Optional[DocumentController.CollectionInfo]) -> None:
            self.__status_section.visible = True
            self.__filter_description.text = collection_info.title if collection_info else str()

        self.__filter_description_action = Stream.ValueStreamAction(document_controller.current_collection_info, update_filter_description)

        update_filter_description(document_controller.current_collection_info.value)


    def close(self) -> None:
        # close the widget to stop repainting the widgets before closing the controllers.
        super().close()
        # finish closing
        self.data_grid_controller.close()
        self.data_grid_controller = typing.cast(DataGridController, None)
        self.__filtered_display_item_adapters_model.close()
        self.__filtered_display_item_adapters_model = typing.cast(ListModel.MappedListModel, None)
        # button group
        self.__view_button_group.close()
        self.__view_button_group = typing.cast(CanvasItem.RadioButtonGroup, None)
        self.__selection_changed_event_listener.close()
        self.__selection_changed_event_listener = typing.cast(Event.EventListener, None)
        # listeners
        self.__filter_description_action = typing.cast(typing.Any, None)

    def __notify_focus_changed(self) -> None:
        # this is called when the keyboard focus for the data panel is changed.
        # if we are receiving focus, tell the window (document_controller) that
        # we now have the focus.
        if self.__focused:
            self.document_controller.data_panel_focused()

    @property
    def focused(self) -> bool:
        return self.__focused

    @focused.setter
    def focused(self, value: bool) -> None:
        self.__focused = value
        self.__notify_focus_changed()
