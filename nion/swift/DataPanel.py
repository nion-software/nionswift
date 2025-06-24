from __future__ import annotations

# standard libraries
import asyncio
import copy
import gettext
import operator
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
from nion.swift.model import UISettings
from nion.ui import Bitmap
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import GridCanvasItem
from nion.ui import GridFlowCanvasItem
from nion.ui import ListCanvasItem
from nion.ui import UserInterface
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import Model
from nion.utils import ReferenceCounting
from nion.utils import Stream

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
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


class DataPanelItemBaseCanvasItem(CanvasItem.AbstractCanvasItem):
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

    def _get_composer(self, composer_cache: CanvasItem.ComposerCache) -> CanvasItem.BaseComposer:
        raise NotImplementedError()

    def close(self) -> None:
        self.__thumbnail_updated_event_listener = typing.cast(typing.Any, None)
        self.__thumbnail_source = typing.cast(typing.Any, None)
        super().close()

    @property
    def _thumbnail(self) -> typing.Optional[Bitmap.Bitmap]:
        return self.__thumbnail

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


class DataPanelListItem(DataPanelItemBaseCanvasItem):

    def __init__(self, display_item: DisplayItem.DisplayItem, ui: UserInterface.UserInterface, font_metrics_fn: typing.Callable[[str, str], UserInterface.FontMetrics]) -> None:
        super().__init__(display_item, ui, font_metrics_fn)
        self.__font_metrics_fn = font_metrics_fn
        self.update_sizing(self.sizing.with_fixed_height(72))
        self.update_sizing(self.sizing.with_fixed_width(CanvasItem.SizingEnum.UNRESTRAINED))

    def _get_composer(self, composer_cache: CanvasItem.ComposerCache) -> CanvasItem.BaseComposer:
        line_height = self.__font_metrics_fn("11px sans-serif", "M").height
        return DataPanelListItemComposer(self, self.layout_sizing, composer_cache, self._thumbnail, line_height, self.title, self.format_str, self.datetime_str, self.status_str)


class DataPanelGridItemComposer(CanvasItem.BaseComposer):
    def __init__(self, canvas_item: CanvasItem.AbstractCanvasItem, layout_sizing: CanvasItem.Sizing,
                 cache: CanvasItem.ComposerCache, ui_settings: UISettings.UISettings,
                 thumbnail: typing.Optional[Bitmap.Bitmap], line_height: int, displayed_title: str, format_str: str,
                 datetime_str: str, status_str: str, draw_label: bool) -> None:
        super().__init__(canvas_item, layout_sizing, cache)
        self.__ui_settings = ui_settings
        self.__bitmap = thumbnail
        self.__line_height = line_height
        self.__displayed_title = displayed_title
        self.__format_str = format_str
        self.__datetime_str = datetime_str
        self.__status_str = status_str
        self.__draw_label = draw_label

    def _repaint(self, drawing_context: DrawingContext.DrawingContext, canvas_bounds: Geometry.IntRect, composer_cache: CanvasItem.ComposerCache) -> None:
        if self.__bitmap and self.__bitmap.rgba_bitmap_data is not None:
            image_size = self.__bitmap.computed_shape
            if image_size.height > 0 and image_size.width > 0:
                rect = canvas_bounds.inset(4, 4)
                if self.__draw_label:
                    rect = Geometry.IntRect.from_tlhw(rect.top, rect.left, rect.height - self.__line_height, rect.width)
                display_rect = Geometry.fit_to_size(rect, image_size)
                display_height = display_rect.height
                display_width = display_rect.width
                if display_rect and display_width > 0 and display_height > 0:
                    display_top = display_rect.top
                    display_left = display_rect.left
                    drawing_context.draw_image(self.__bitmap.rgba_bitmap_data, display_left, display_top, display_width, display_height)
                    if self.__draw_label:
                        font = "11px sans-serif"
                        drawing_context.font = font
                        drawing_context.fill_style = "black"
                        truncated_displayed_title = self.__ui_settings.truncate_string_to_width(font, self.__displayed_title, canvas_bounds.width, UISettings.TruncateModeType.MIDDLE)
                        drawing_context.text_baseline = "middle"
                        drawing_context.text_align = "center"
                        drawing_context.fill_text(truncated_displayed_title, canvas_bounds.center.x, (rect.bottom + 4 + canvas_bounds.bottom) // 2)


class DataPanelGridItem(DataPanelItemBaseCanvasItem):

    def __init__(self, display_item: DisplayItem.DisplayItem, ui: UserInterface.UserInterface, ui_settings: UISettings.UISettings, draw_label: bool = True) -> None:
        super().__init__(display_item, ui, typing.cast(typing.Callable[[str, str], UserInterface.FontMetrics], ui_settings.get_font_metrics))
        self.__ui_settings = ui_settings
        self.__draw_label = draw_label
        self.update_sizing(self.sizing.with_fixed_height(CanvasItem.SizingEnum.UNRESTRAINED))
        self.update_sizing(self.sizing.with_fixed_width(CanvasItem.SizingEnum.UNRESTRAINED))

    def _get_composer(self, composer_cache: CanvasItem.ComposerCache) -> CanvasItem.BaseComposer:
        # return CanvasItem.EmptyCanvasItemComposer(self, self.layout_sizing, composer_cache)
        line_height = self.__ui_settings.get_font_metrics("11px sans-serif", "M").height
        return DataPanelGridItemComposer(self, self.layout_sizing, composer_cache, self.__ui_settings, self._thumbnail, line_height, self.title, self.format_str, self.datetime_str, self.status_str, self.__draw_label)


class DataPanelUISettings(UISettings.UISettings):
    def __init__(self, ui: UserInterface.UserInterface) -> None:
        self.__ui = ui

    def get_font_metrics(self, font: str, text: str) -> UISettings.FontMetrics:
        return typing.cast(UISettings.FontMetrics, self.__ui.get_font_metrics(font, text))

    def truncate_string_to_width(self, font_str: str, text: str, pixel_width: int, mode: UISettings.TruncateModeType) -> str:
        return self.__ui.truncate_string_to_width(font_str, text, pixel_width, typing.cast(UserInterface.TruncateModeType, mode))

    @property
    def cursor_tolerance(self) -> float:
        return self.__ui.get_tolerance(UserInterface.ToleranceType.CURSOR)


class DataPanel(Panel.Panel):

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: Persistence.PersistentDictType) -> None:
        super().__init__(document_controller, panel_id, _("Data Items"))

        ui = document_controller.ui

        display_items_model = document_controller.filtered_display_items_model

        self.__selection = self.document_controller.selection

        def selection_changed() -> None:
            # called when the selection changes; notify selected display item changed if focused.
            self.__notify_focus_changed()

        self.__selection_changed_event_listener = self.__selection.changed_event.listen(selection_changed)

        class ItemDelegate(GridFlowCanvasItem.GridFlowCanvasItemDelegate):
            def __init__(self, data_panel: DataPanel, selection: Selection.IndexedSelection) -> None:
                self.__data_panel = data_panel
                self.__selection = selection

            def item_tool_tip(self, item: typing.Any) -> typing.Optional[str]:
                display_item = typing.cast(DisplayItem.DisplayItem, item)
                return display_item.list_tool_tip_str

            def context_menu_event(self, context_menu_event: GridFlowCanvasItem.GridFlowCanvasItemContextMenuEvent) -> bool:
                display_items = tuple(typing.cast(DisplayItem.DisplayItem, item) for item in context_menu_event.selected_items)
                menu = document_controller.create_context_menu()
                action_context = document_controller._get_action_context_for_display_items(display_items, None)
                document_controller.populate_context_menu(menu, action_context)
                menu.add_separator()
                document_controller.add_action_to_menu(menu, "item.delete", action_context)
                menu.popup(context_menu_event.gp.x, context_menu_event.gp.y)
                return True

            def delete_event(self, delete_event: GridFlowCanvasItem.GridFlowCanvasItemDeleteEvent) -> bool:
                display_items = tuple(typing.cast(DisplayItem.DisplayItem, item) for item in delete_event.selected_items)
                document_controller.delete_display_items(display_items)
                return True

            def drag_started_event(self, drag_started_event: GridFlowCanvasItem.GridFlowCanvasItemDragStartedEvent) -> bool:
                mime_data, thumbnail_data = self._get_mime_data_and_thumbnail_data(drag_started_event)
                if mime_data:
                    self.__data_panel.widget.drag(mime_data, thumbnail_data)
                    return True
                return False

            def can_drop_mime_data(self, mime_data: UserInterface.MimeData, action: str, drop_index: int | None) -> bool:
                return mime_data.has_file_paths

            def drop_mime_data(self, mime_data: UserInterface.MimeData, action: str, drop_index: int | None) -> str:
                display_items = document_controller.receive_files(mime_data.file_paths)
                if set(display_items).intersection(set(document_controller.filtered_display_items_model.display_items)):
                    document_controller.select_display_items_in_data_panel(display_items)
                return "accept"

            def _get_mime_data_and_thumbnail_data(self, drag_started_event: GridFlowCanvasItem.GridFlowCanvasItemDragStartedEvent) -> typing.Tuple[typing.Optional[UserInterface.MimeData], typing.Optional[_NDArray]]:
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

        item_delegate = ItemDelegate(self, self.__selection)

        def list_item_factory(item: typing.Any, is_selected_model: Model.PropertyModel[bool]) -> CanvasItem.AbstractCanvasItem:
            return DataPanelListItem(typing.cast(DisplayItem.DisplayItem, item), document_controller.ui, document_controller.get_font_metrics)

        # note is_shared_selection is True for both list and grid canvas items. prevents the selection from being updated when items are inserted.
        # instead, the selection in the model itself is used.
        list_canvas_item = ListCanvasItem.ListCanvasItem2(Panel.ThreadSafeListModel(display_items_model, document_controller.event_loop), self.__selection, list_item_factory, item_delegate, item_height=80, key="display_items", is_shared_selection=True)
        list_canvas_item.wants_drag_events = True
        list_scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(list_canvas_item)
        list_scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(list_scroll_area_canvas_item, CanvasItem.Orientation.Vertical)
        list_scroll_group_canvas_item = CanvasItem.CanvasItemComposition()
        list_scroll_group_canvas_item.layout = CanvasItem.CanvasItemRowLayout()
        list_scroll_group_canvas_item.add_canvas_item(list_scroll_area_canvas_item)
        list_scroll_group_canvas_item.add_canvas_item(list_scroll_bar_canvas_item)

        def grid_item_factory(item: typing.Any, is_selected_model: Model.PropertyModel[bool]) -> CanvasItem.AbstractCanvasItem:
            return DataPanelGridItem(typing.cast(DisplayItem.DisplayItem, item), document_controller.ui, DataPanelUISettings(document_controller.ui))

        # note is_shared_selection is True for both list and grid canvas items. prevents the selection from being updated when items are inserted.
        # instead, the selection in the model itself is used.
        line_height = document_controller.get_font_metrics("11px sans-serif", "M").height
        grid_canvas_item = GridCanvasItem.GridCanvasItem2(Panel.ThreadSafeListModel(display_items_model, document_controller.event_loop), self.__selection, grid_item_factory, item_delegate, item_size=Geometry.IntSize(80 + line_height, 80), key="display_items", is_shared_selection=True)
        grid_canvas_item.wants_drag_events = True
        grid_scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(grid_canvas_item)
        grid_scroll_area_canvas_item.auto_resize_contents = True
        grid_scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(grid_scroll_area_canvas_item, CanvasItem.Orientation.Vertical)
        grid_scroll_group_canvas_item = CanvasItem.CanvasItemComposition()
        grid_scroll_group_canvas_item.layout = CanvasItem.CanvasItemRowLayout()
        grid_scroll_group_canvas_item.add_canvas_item(grid_scroll_area_canvas_item)
        grid_scroll_group_canvas_item.add_canvas_item(grid_scroll_bar_canvas_item)

        def begin_changes(key: str) -> None:
            list_canvas_item._begin_batch_update()
            grid_canvas_item._begin_batch_update()

        def end_changes(key: str) -> None:
            list_canvas_item._end_batch_update()
            grid_canvas_item._end_batch_update()

        # the display items model can notify us when it is about to change. in order to gang up changes, watch
        # for these notification events and tell the list canvas item to only update at the end of the changes.
        self.__display_items_begin_changes_listener = display_items_model.begin_changes_event.listen(begin_changes)
        self.__display_items_end_changes_listener = display_items_model.end_changes_event.listen(end_changes)

        # for testing
        self._scroll_area_canvas_item = list_scroll_area_canvas_item
        self._scroll_bar_canvas_item = list_scroll_bar_canvas_item

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

        stack_canvas_item = CanvasItem.StackCanvasItem()
        stack_canvas_item.add_canvas_item(list_scroll_group_canvas_item)
        stack_canvas_item.add_canvas_item(grid_scroll_group_canvas_item)
        stack_canvas_item.current_index = 0
        stack_canvas_item.update_sizing(stack_canvas_item.sizing.with_unconstrained_height())

        self.data_view_widget = ui.create_canvas_widget(properties={"size-policy-vertical": "expanding"})
        self.data_view_widget.canvas_item.add_canvas_item(stack_canvas_item)

        self.__view_button_group = CanvasItem.RadioButtonGroup([list_icon_button, grid_icon_button])
        self.__view_button_group.current_index = 0
        self.__view_button_group.on_current_index_changed = lambda index: setattr(stack_canvas_item, "current_index", index)

        self.__filter_description_combo_box = ui.create_combo_box_widget(item_getter=operator.attrgetter("title"))

        status_row = ui.create_row_widget()
        status_row.add_spacing(4)
        status_row.add(self.__filter_description_combo_box)
        status_row.add_spacing(3)

        divider_widget = ui.create_canvas_widget(properties={"height": 2})
        divider_widget.canvas_item.add_canvas_item(CanvasItem.DividerCanvasItem(orientation="horizontal"))

        self.__status_section = ui.create_column_widget()
        self.__status_section.add_spacing(2)
        self.__status_section.add(status_row)
        self.__status_section.add_spacing(4)
        self.__status_section.add(divider_widget)

        widget = ui.create_column_widget(properties=properties)
        widget.add(self.__status_section)
        widget.add(self.data_view_widget)
        widget.add_spacing(6)
        widget.add(search_widget)
        widget.add_spacing(6)

        self.widget = widget

        self.__list_canvas_item = list_canvas_item
        self.__grid_canvas_item = grid_canvas_item

        # listen to the focus changed event for the list and grid canvas items.
        # if we are receiving focus, tell the window (document_controller) to update the selected display item.
        self.__list_canvas_item_focus_changed_event_listener = list_canvas_item.focus_changed_event.listen(self.__notify_focus_changed)
        self.__grid_canvas_item_focus_changed_event_listener = grid_canvas_item.focus_changed_event.listen(self.__notify_focus_changed)

        # for tests only
        self._data_list_canvas_item = list_scroll_group_canvas_item
        self._data_grid_canvas_item = grid_scroll_group_canvas_item

        def update_filter_description(collection_info: typing.Optional[DocumentController.CollectionInfo]) -> None:
            if collection_info != self.__filter_description_combo_box.current_item:
                self.__filter_description_combo_box.current_item = collection_info

        def update_filter_descriptions(collection_info_list: typing.Optional[typing.Sequence[DocumentController.CollectionInfo]]) -> None:
            if collection_info_list is not None:
                self.__filter_description_combo_box.items = collection_info_list
                update_filter_description(document_controller.current_collection_info.value)

        def on_current_collection_changed(collection_info: typing.Optional[DocumentController.CollectionInfo]) -> None:
            if collection_info and document_controller.current_collection_info.value != collection_info:
                if collection_info.is_smart_collection:
                    document_controller.set_filter(collection_info.filter_id)
                else:
                    document_controller.set_data_group(collection_info.data_group)

        self.__filter_description_action = Stream.ValueStreamAction(document_controller.current_collection_info, update_filter_description)
        collection_info_list_stream = Stream.PropertyChangedEventStream[typing.Sequence["DocumentController.CollectionInfo"]](document_controller.collection_info_list_model, "items")
        self.__collection_info_list_stream_action = Stream.ValueStreamAction(collection_info_list_stream, update_filter_descriptions)

        update_filter_descriptions(document_controller.collection_info_list_model.items)
        self.__filter_description_combo_box.on_current_item_changed = on_current_collection_changed

    def close(self) -> None:
        self.__selection_changed_event_listener.close()
        self.__selection_changed_event_listener = typing.cast(Event.EventListener, None)
        self.__filter_description_action = typing.cast(typing.Any, None)
        self.__view_button_group.close()
        self.__view_button_group = typing.cast(CanvasItem.RadioButtonGroup, None)
        # close the widget to stop repainting the widgets before closing the controllers.
        super().close()

    @property
    def _selection(self) -> Selection.IndexedSelection:
        return self.__selection

    @property
    def _list_canvas_item(self) -> ListCanvasItem.ListCanvasItem2:
        return self.__list_canvas_item

    @property
    def _grid_canvas_item(self) -> GridCanvasItem.GridCanvasItem2:
        return self.__grid_canvas_item

    def __notify_focus_changed(self) -> None:
        # this is called when the keyboard focus for the data panel is changed.
        # if we are receiving focus, tell the window (document_controller) that
        # we now have the focus.
        if self.__list_canvas_item.focused or self.__grid_canvas_item.focused:
            self.document_controller.data_panel_focused()

    def _request_focus_for_test(self) -> None:
        self.__list_canvas_item.request_focus()

    def make_selection_visible(self) -> None:
        self.__list_canvas_item.make_selection_visible()
        self.__grid_canvas_item.make_selection_visible()
