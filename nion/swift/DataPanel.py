from __future__ import annotations

# standard libraries
import asyncio
import datetime
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
from nion.swift.model import DisplayItem
from nion.swift.model import Persistence
from nion.swift.model import UISettings
from nion.swift.model import Utility
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


def get_mime_data_and_thumbnail_data(drag_started_event: GridFlowCanvasItem.GridFlowCanvasItemDragStartedEvent,
                                     ui: UserInterface.UserInterface) -> tuple[UserInterface.MimeData | None, _NDArray | None]:
    display_item = typing.cast(DisplayItem.DisplayItem, drag_started_event.item)
    assert display_item is not None
    display_items = tuple(typing.cast(DisplayItem.DisplayItem, item) for item in drag_started_event.selected_items)
    display_item = typing.cast(DisplayItem.DisplayItem, drag_started_event.item)
    mime_data = ui.create_mime_data()
    if len(display_items) <= 1:
        MimeTypes.mime_data_put_display_item(mime_data, display_item)
    else:
        MimeTypes.mime_data_put_display_items(mime_data, display_items)

    # Get and scale thumbnail
    thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(ui, display_item)
    thumbnail_data = thumbnail_source.thumbnail_data

    if thumbnail_data is not None:
        scaled_view = Image.scaled(Image.get_rgba_view_from_rgba_data(thumbnail_data), tuple(Geometry.IntSize(w=80, h=80)))
        thumbnail_data = Image.get_rgba_data_from_rgba(scaled_view)

    return mime_data, thumbnail_data


class DataPanelItemBaseCanvasItem(CanvasItem.AbstractCanvasItem):
    """Canvas item to draw a data panel list item.

    This is critical performance code. It is called for every item in the list. So use a custom renderer.
    """

    def __init__(self, display_item: DisplayItem.DisplayItem, ui: UserInterface.UserInterface, font_metrics_fn: typing.Callable[[str, str], UserInterface.FontMetrics]) -> None:
        super().__init__()
        self.__display_item = display_item
        self.__ui = ui
        self.__font_metrics_fn = font_metrics_fn
        self.__thumbnail: Bitmap.Bitmap | None = None
        self.__thumbnail_source: Thumbnails.ThumbnailSource | None = None
        self.__thumbnail_source_action: Stream.ValueStreamAction[Bitmap.Bitmap] | None = None

        # the data panel creates the thumbnail source once the item is in view, so that the thumbnails of items which
        # are never shown are not read or drawn. an item which is recreated, such as when it moves in a sorted list,
        # shows the thumbnail of its existing source immediately rather than blank until the data panel shows it.
        if thumbnail_source := Thumbnails.ThumbnailManager().existing_thumbnail_source_for_display_item(display_item):
            self.__attach_thumbnail_source(thumbnail_source)

        self.__item_changed_listener = display_item.item_changed_event.listen(ReferenceCounting.weak_partial(DataPanelListItem.__item_changed, self))

    def _get_composer(self, composer_cache: CanvasItem.ComposerCache) -> CanvasItem.BaseComposer:
        raise NotImplementedError()

    def close(self) -> None:
        self.__thumbnail_source_action = None
        self.__thumbnail_source = None
        super().close()

    @property
    def _thumbnail(self) -> typing.Optional[Bitmap.Bitmap]:
        return self.__thumbnail

    @property
    def _has_thumbnail_source(self) -> bool:
        # for testing.
        return self.__thumbnail_source is not None

    def _show_thumbnail(self) -> None:
        """Show the thumbnail of the display item, creating its thumbnail source if needed. Call on the main thread."""
        if not self.__thumbnail_source:
            self.__attach_thumbnail_source(Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.__ui, self.__display_item))

    def _show_in_view(self) -> None:
        """Show the parts of the item which are made only once it is in view, such as its thumbnail. Call on the main thread."""
        self._show_thumbnail()

    def __attach_thumbnail_source(self, thumbnail_source: Thumbnails.ThumbnailSource) -> None:
        self.__thumbnail_source = thumbnail_source
        self.__thumbnail_source_action = Stream.ValueStreamAction(thumbnail_source, ReferenceCounting.weak_partial(DataPanelItemBaseCanvasItem.__handle_thumbnail_updated, self))
        self.__handle_thumbnail_updated(thumbnail_source.value)

    def __handle_thumbnail_updated(self, thumbnail_bitmap: Bitmap.Bitmap | None) -> None:
        # called on the main thread; the thumbnail source sends its value there.
        self.__thumbnail = thumbnail_bitmap
        self.update()

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
    def date_for_sorting_local(self) -> datetime.datetime:
        return self.__display_item.date_for_sorting_local if self.__display_item else datetime.datetime.now()

    @property
    def datetime_str(self) -> str:
        return self.__display_item.date_for_sorting_local_as_string if self.__display_item else str()

    @property
    def status_str(self) -> str:
        return self.__display_item.status_str if self.__display_item else str()

    def __item_changed(self) -> None:
        self._item_changed()

    def _item_changed(self) -> None:
        self.update()


class DataPanelBrowserThumbnailLoader:
    """Show the data panel items in view in a browser.

    Only the items in view are shown, so that the parts of items which are never shown, such as their thumbnails, are not
    made. Close the loader before closing the browser.
    """

    def __init__(self, browser_canvas_item: GridFlowCanvasItem.GridFlowCanvasItem, event_loop: asyncio.AbstractEventLoop) -> None:
        self.__browser_canvas_item: GridFlowCanvasItem.GridFlowCanvasItem | None = browser_canvas_item
        self.__event_loop = event_loop

        # the items in view change on render threads during layout, so showing them is queued to the main thread. the lock
        # protects the pending flag. the browser canvas item is used only on the main thread.
        self.__lock = threading.Lock()
        self.__is_pending = False

        self.__items_in_view_changed_listener: Event.EventListener | None = browser_canvas_item.items_in_view_changed_event.listen(ReferenceCounting.weak_partial(DataPanelBrowserThumbnailLoader.handle_items_in_view_changed, self))

    def close(self) -> None:
        self.__items_in_view_changed_listener = None
        self.__browser_canvas_item = None

    def handle_items_in_view_changed(self) -> None:
        """Show the items in view soon. Call on any thread.

        The browser calls this when the items in view change, except when it or a container is hidden or shown.
        """
        with self.__lock:
            if self.__is_pending:
                return
            self.__is_pending = True
        try:
            self.__event_loop.call_soon_threadsafe(ReferenceCounting.weak_partial(DataPanelBrowserThumbnailLoader.__show_items_in_view, self))
        except RuntimeError:
            # the event loop is closed during shutdown, so there is no browser left to show.
            pass

    def __show_items_in_view(self) -> None:
        with self.__lock:
            self.__is_pending = False
        if browser_canvas_item := self.__browser_canvas_item:
            for item_canvas_item in browser_canvas_item.item_canvas_items_in_view:
                if isinstance(item_canvas_item, DataPanelItemBaseCanvasItem):
                    item_canvas_item._show_in_view()


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


def get_detail_date_format_type(date_local: datetime.datetime, now_local: datetime.datetime) -> Utility.DateTimeFormatType:
    """Return the form of a date shown in a detail browser item.

    The form is the time with seconds for a date within the minute before now_local, the time for a date on the same day,
    the month and day for a date within 48 weeks, and the year and month for a date further away. The seconds let the
    date of a live item visibly advance.
    """
    if 0 <= (now_local - date_local).total_seconds() < 60:
        return Utility.DateTimeFormatType.TIME_WITH_SECONDS
    if date_local.date() == now_local.date():
        return Utility.DateTimeFormatType.TIME
    if abs(now_local - date_local) <= datetime.timedelta(weeks=48):
        return Utility.DateTimeFormatType.MONTH_DAY
    return Utility.DateTimeFormatType.YEAR_MONTH


def update_detail_dates_in_view(detail_canvas_item: GridFlowCanvasItem.GridFlowCanvasItem, is_changing_only: bool) -> None:
    """Update the date text of the detail browser items in view for the current time.

    With is_changing_only, only the items whose date shows its seconds or whose display item has changed are updated.
    """
    now_local = datetime.datetime.now()
    for item_canvas_item in detail_canvas_item.item_canvas_items_in_view:
        if isinstance(item_canvas_item, DataPanelDetailItem) and (item_canvas_item._is_date_changing or not is_changing_only):
            item_canvas_item._update_date(now_local)


def add_detail_dates_periodic_listeners(document_controller: DocumentController.DocumentController, detail_canvas_item: GridFlowCanvasItem.GridFlowCanvasItem) -> typing.Sequence[DocumentController.PeriodicListener]:
    """Add the periodic listeners which update the date text of the detail browser items in view, and return them.

    The form of a date depends on the current time, so the items in view are updated each minute, and the changing ones
    each second. The updates continue while the returned listeners are held.
    """
    return (document_controller.add_periodic(60.0, ReferenceCounting.weak_partial(update_detail_dates_in_view, detail_canvas_item, False)),
            document_controller.add_periodic(1.0, ReferenceCounting.weak_partial(update_detail_dates_in_view, detail_canvas_item, True)))


def get_detail_item_height(font_metrics_fn: typing.Callable[[str, str], UserInterface.FontMetrics]) -> int:
    """Return the height of a detail browser item."""
    line_height: float = font_metrics_fn("11px sans-serif", "M").height
    return round(line_height) + 6


class DataPanelDetailItemComposer(CanvasItem.BaseComposer):
    def __init__(self, canvas_item: CanvasItem.AbstractCanvasItem, layout_sizing: CanvasItem.Sizing, cache: CanvasItem.ComposerCache,
                 ui_settings: UISettings.UISettings, thumbnail: typing.Optional[Bitmap.Bitmap], displayed_title: str, date_str: str) -> None:
        super().__init__(canvas_item, layout_sizing, cache)
        self.__ui_settings = ui_settings
        self.__bitmap = thumbnail
        self.__displayed_title = displayed_title
        self.__date_str = date_str

    def _repaint(self, drawing_context: DrawingContext.DrawingContext, canvas_bounds: Geometry.IntRect, composer_cache: CanvasItem.ComposerCache) -> None:
        font = "11px sans-serif"
        margin = 4
        spacing = 6

        # the row is the thumbnail, then the title, then the date against the right edge. the title is truncated in
        # the middle to fit the space which the date leaves.
        thumbnail_size = max(canvas_bounds.height - 4, 0)
        thumbnail_rect = Geometry.IntRect.from_tlhw(canvas_bounds.top + (canvas_bounds.height - thumbnail_size) // 2, canvas_bounds.left + margin, thumbnail_size, thumbnail_size)
        if self.__bitmap and self.__bitmap.rgba_bitmap_data is not None:
            image_size = self.__bitmap.computed_shape
            if image_size.height > 0 and image_size.width > 0:
                display_rect = Geometry.fit_to_size(thumbnail_rect, image_size)
                if display_rect.width > 0 and display_rect.height > 0:
                    drawing_context.draw_image(self.__bitmap.rgba_bitmap_data, display_rect.left, display_rect.top, display_rect.width, display_rect.height)

        drawing_context.font = font
        drawing_context.fill_style = "black"
        drawing_context.text_baseline = "middle"
        text_y = canvas_bounds.center.y
        date_right = canvas_bounds.right - margin
        date_width = int(self.__ui_settings.get_font_metrics(font, self.__date_str).width) if self.__date_str else 0
        if self.__date_str:
            drawing_context.text_align = "right"
            drawing_context.fill_text(self.__date_str, date_right, text_y)
        title_left = thumbnail_rect.right + spacing
        title_width = date_right - date_width - spacing - title_left
        if self.__displayed_title and title_width > 0:
            truncated_displayed_title = self.__ui_settings.truncate_string_to_width(font, self.__displayed_title, title_width, UISettings.TruncateModeType.MIDDLE)
            drawing_context.text_align = "left"
            drawing_context.fill_text(truncated_displayed_title, title_left, text_y)


class DataPanelDetailItem(DataPanelItemBaseCanvasItem):

    def __init__(self, display_item: DisplayItem.DisplayItem, ui: UserInterface.UserInterface, ui_settings: UISettings.UISettings, height: int) -> None:
        super().__init__(display_item, ui, typing.cast(typing.Callable[[str, str], UserInterface.FontMetrics], ui_settings.get_font_metrics))
        self.__ui_settings = ui_settings

        # the date is formatted on the main thread, only once the item is in view, so that the dates of items which are
        # never shown are not formatted. a change to the display item can arrive on any thread, so it only marks the date
        # as changed, and the periodic update formats it.
        self.__date_local: datetime.datetime | None = None
        self.__date_format_type: Utility.DateTimeFormatType | None = None
        self.__date_str = str()
        self.__is_date_changed = False

        self.update_sizing(self.sizing.with_fixed_height(height))
        self.update_sizing(self.sizing.with_fixed_width(CanvasItem.SizingEnum.UNRESTRAINED))

    @property
    def _date_str(self) -> str:
        # for testing.
        return self.__date_str

    @property
    def _is_date_with_seconds(self) -> bool:
        return self.__date_format_type == Utility.DateTimeFormatType.TIME_WITH_SECONDS

    @property
    def _is_date_changing(self) -> bool:
        return self.__is_date_changed or self._is_date_with_seconds

    def _show_in_view(self) -> None:
        super()._show_in_view()
        self._update_date(datetime.datetime.now())

    def _update_date(self, now_local: datetime.datetime) -> None:
        """Redraw the item if its date text for now_local differs from the text drawn."""
        # the flag is cleared before the date is read, so that a change during the update is not lost.
        self.__is_date_changed = False
        date_local = self.date_for_sorting_local
        date_format_type = get_detail_date_format_type(date_local, now_local)
        if date_local != self.__date_local or date_format_type != self.__date_format_type:
            self.__date_local = date_local
            self.__date_format_type = date_format_type
            date_str = Utility.format_date_time(date_local, date_format_type)
            if date_str != self.__date_str:
                self.__date_str = date_str
                self.update()

    def _item_changed(self) -> None:
        self.__is_date_changed = True
        super()._item_changed()

    def _get_composer(self, composer_cache: CanvasItem.ComposerCache) -> CanvasItem.BaseComposer:
        return DataPanelDetailItemComposer(self, self.layout_sizing, composer_cache, self.__ui_settings, self._thumbnail, self.title, self.__date_str)


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

    # the user's choice of browser type (list/detail/grid) is persisted under this key (via ui.get/set_persistent_string)
    # so it is restored the next time the application is launched.
    BROWSER_TYPE_PREFERENCE_KEY = "DataPanel/BrowserType"

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: Persistence.PersistentDictType) -> None:
        super().__init__(document_controller, panel_id, _("Data Items"))

        ui = document_controller.ui

        display_items_model = document_controller.filtered_display_items_model
        self.__display_items_model = display_items_model

        self.__selection = self.document_controller.selection

        # each browser type (list/grid, and whatever gets added later) is built lazily, the first time it's
        # actually needed -- switched to, restored from the saved preference, or grabbed directly by a test.
        # building every type eagerly would multiply the per-item cost of every insert/remove on the filtered
        # display items model by however many browser types exist, even though only one is ever visible.
        # this follows the same lazy-build convention as DisplayPanel's per-panel browsers (see
        # DisplayPanel.__ensure_grid_browser_canvas_item), but there's only one DataPanel, so once a browser
        # type is built it's kept around for the panel's lifetime rather than torn down when switched away.
        #
        # browser types are stored by name in dicts rather than a pair of ivars per type, so adding a new
        # type doesn't mean adding a whole new parallel set of ivars: __browser_view_items holds the inner
        # view canvas item (the browser types share a base type, see GridFlowCanvasItem.GridFlowCanvasItem),
        # __browser_wrapper_items holds the scroll-group wrapper that gets inserted into __stack_canvas_item,
        # __browser_focus_listeners holds each view's focus_changed_event listener, and __browser_thumbnail_loaders
        # holds each view's thumbnail loader. see the __ensure_*_canvas_item methods and __switch_to_browser_type below.
        self.__browser_view_items: dict[str, GridFlowCanvasItem.GridFlowCanvasItem | None] = {"list": None, "detail": None, "grid": None}
        self.__browser_wrapper_items: dict[str, CanvasItem.CanvasItemComposition | None] = {"list": None, "detail": None, "grid": None}
        self.__browser_focus_listeners: dict[str, Event.EventListener | None] = {"list": None, "detail": None, "grid": None}
        self.__browser_thumbnail_loaders: dict[str, DataPanelBrowserThumbnailLoader | None] = {"list": None, "detail": None, "grid": None}

        # the listeners which update the dates in the detail browser while it exists.
        self.__detail_dates_periodic_listeners: typing.Sequence[DocumentController.PeriodicListener] = tuple()

        # extra test-only hooks specific to the list view's internal layout (no grid equivalent exists yet).
        self.__list_scroll_area_canvas_item: CanvasItem.ScrollAreaCanvasItem | None = None
        self.__list_scroll_bar_canvas_item: CanvasItem.ScrollBarCanvasItem | None = None

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
                action_context = document_controller.get_action_context_for_display_items(display_items, None)
                document_controller.populate_context_menu(menu, action_context)
                menu.add_separator()
                document_controller.add_action_to_menu_if_enabled(menu, "workspace.new_workspace_from_selection", action_context)
                menu.add_separator()
                document_controller.add_action_to_menu(menu, "item.delete", action_context)
                menu.popup(context_menu_event.gp.x, context_menu_event.gp.y)
                return True

            def delete_event(self, delete_event: GridFlowCanvasItem.GridFlowCanvasItemDeleteEvent) -> bool:
                display_items = tuple(typing.cast(DisplayItem.DisplayItem, item) for item in delete_event.selected_items)
                document_controller.delete_display_items(display_items)
                return True

            def drag_started_event(self, drag_started_event: GridFlowCanvasItem.GridFlowCanvasItemDragStartedEvent) -> bool:
                mime_data, thumbnail_data = get_mime_data_and_thumbnail_data(drag_started_event, self.__data_panel.ui)
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


        self.__item_delegate = ItemDelegate(self, self.__selection)

        def begin_changes(key: str) -> None:
            for view_item in self.__browser_view_items.values():
                if view_item is not None:
                    view_item._begin_batch_update()

        def end_changes(key: str) -> None:
            for view_item in self.__browser_view_items.values():
                if view_item is not None:
                    view_item._end_batch_update()

        # the display items model can notify us when it is about to change. in order to gang up changes, watch
        # for these notification events and tell whichever canvas items have been built to only update at the
        # end of the changes.
        self.__display_items_begin_changes_listener = display_items_model.begin_changes_event.listen(begin_changes)
        self.__display_items_end_changes_listener = display_items_model.end_changes_event.listen(end_changes)

        list_icon_20_bytes = pkgutil.get_data(__name__, "resources/list_icon_20.png")
        detail_icon_20_bytes = pkgutil.get_data(__name__, "resources/detail_icon_20.png")
        grid_icon_20_bytes = pkgutil.get_data(__name__, "resources/grid_icon_20.png")
        list_icon_20_bytes = list_icon_20_bytes or bytes()
        detail_icon_20_bytes = detail_icon_20_bytes or bytes()
        grid_icon_20_bytes = grid_icon_20_bytes or bytes()
        list_icon_button = CanvasItem.BitmapButtonCanvasItem(CanvasItem.load_rgba_data_from_bytes(list_icon_20_bytes))
        detail_icon_button = CanvasItem.BitmapButtonCanvasItem(CanvasItem.load_rgba_data_from_bytes(detail_icon_20_bytes))
        grid_icon_button = CanvasItem.BitmapButtonCanvasItem(CanvasItem.load_rgba_data_from_bytes(grid_icon_20_bytes))

        list_icon_button.update_sizing(list_icon_button.sizing.with_fixed_size(Geometry.IntSize(20, 20)))
        detail_icon_button.update_sizing(detail_icon_button.sizing.with_fixed_size(Geometry.IntSize(20, 20)))
        grid_icon_button.update_sizing(grid_icon_button.sizing.with_fixed_size(Geometry.IntSize(20, 20)))

        button_row = CanvasItem.CanvasItemComposition()
        button_row.layout = CanvasItem.CanvasItemRowLayout(spacing=4)
        button_row.add_canvas_item(list_icon_button)
        button_row.add_canvas_item(detail_icon_button)
        button_row.add_canvas_item(grid_icon_button)

        buttons_widget = ui.create_canvas_widget(properties={"height": 20, "width": 68})
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
        stack_canvas_item.update_sizing(stack_canvas_item.sizing.with_unconstrained_height())
        self.__stack_canvas_item = stack_canvas_item

        self.data_view_widget = ui.create_canvas_widget(properties={"size-policy-vertical": "expanding"})
        self.data_view_widget.canvas_item.add_canvas_item(stack_canvas_item)

        # keyed by name so no browser type is special-cased in the switch logic below -- the order here just
        # needs to match the buttons passed to RadioButtonGroup. each is built lazily (see
        # __ensure_list_canvas_item, __ensure_detail_canvas_item and __ensure_grid_canvas_item); __switch_to_browser_type
        # builds whichever one is needed and looks up its position in the stack dynamically, since browser
        # types can end up built in any order.
        self.__browser_type_ensure_fns: dict[str, typing.Callable[[], CanvasItem.CanvasItemComposition]] = {
            "list": self.__ensure_list_canvas_item,
            "detail": self.__ensure_detail_canvas_item,
            "grid": self.__ensure_grid_canvas_item,
        }
        self.__browser_type_ids = list(self.__browser_type_ensure_fns)

        self.__view_button_group = CanvasItem.RadioButtonGroup([list_icon_button, detail_icon_button, grid_icon_button])

        def on_view_button_group_current_index_changed(index: int) -> None:
            self.__switch_to_browser_type(self.__browser_type_ids[index], persist=True)

        self.__view_button_group.on_current_index_changed = on_view_button_group_current_index_changed

        # restore the persisted browser type (defaulting to "list" on first launch or an unrecognized value),
        # building only that one browser type at startup rather than assuming any particular type is built.
        initial_browser_type_id = ui.get_persistent_string(self.BROWSER_TYPE_PREFERENCE_KEY, "list")
        if initial_browser_type_id not in self.__browser_type_ids:
            initial_browser_type_id = "list"
        self.__switch_to_browser_type(initial_browser_type_id, persist=False)
        self.__view_button_group.current_index = self.__browser_type_ids.index(initial_browser_type_id)

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
        for browser_type_id, browser_thumbnail_loader in self.__browser_thumbnail_loaders.items():
            if browser_thumbnail_loader:
                browser_thumbnail_loader.close()
            self.__browser_thumbnail_loaders[browser_type_id] = None
        self.__detail_dates_periodic_listeners = tuple()
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

    def __switch_to_browser_type(self, browser_type_id: str, persist: bool) -> None:
        # build (if needed) and switch to the given browser type. since types get built in whatever order
        # they're first needed, the canvas item's position in the stack is looked up rather than assumed.
        canvas_item = self.__browser_type_ensure_fns[browser_type_id]()
        self.__stack_canvas_item.current_index = list(self.__stack_canvas_item.canvas_items).index(canvas_item)
        # the items of the browser type shown are now in view.
        if browser_thumbnail_loader := self.__browser_thumbnail_loaders[browser_type_id]:
            browser_thumbnail_loader.handle_items_in_view_changed()
        if persist:
            self.document_controller.ui.set_persistent_string(self.BROWSER_TYPE_PREFERENCE_KEY, browser_type_id)

    def __ensure_list_canvas_item(self) -> CanvasItem.CanvasItemComposition:
        # build the list canvas item and its wrapper the first time it's needed. mirrors
        # __ensure_grid_canvas_item; see the comment in __init__ near __browser_view_items for why this
        # is lazy.
        list_scroll_group_canvas_item = self.__browser_wrapper_items["list"]
        if list_scroll_group_canvas_item is None:
            document_controller = self.document_controller

            def list_item_factory(item: typing.Any, is_selected_model: Model.PropertyModel[bool]) -> CanvasItem.AbstractCanvasItem:
                return DataPanelListItem(typing.cast(DisplayItem.DisplayItem, item), document_controller.ui, document_controller.get_font_metrics)

            # note is_shared_selection is True across all browser types' canvas items. prevents the selection from being updated when items are inserted.
            # instead, the selection in the model itself is used.
            list_canvas_item = ListCanvasItem.ListCanvasItem2(Panel.ThreadSafeListModel(self.__display_items_model, document_controller.event_loop), self.__selection, list_item_factory, self.__item_delegate, item_height=80, key="display_items", is_shared_selection=True)
            list_canvas_item.wants_drag_events = True
            list_scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(list_canvas_item)
            list_scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(list_scroll_area_canvas_item, CanvasItem.Orientation.Vertical)
            list_scroll_group_canvas_item = CanvasItem.CanvasItemComposition()
            list_scroll_group_canvas_item.layout = CanvasItem.CanvasItemRowLayout()
            list_scroll_group_canvas_item.add_canvas_item(list_scroll_area_canvas_item)
            list_scroll_group_canvas_item.add_canvas_item(list_scroll_bar_canvas_item)
            self.__stack_canvas_item.add_canvas_item(list_scroll_group_canvas_item)
            self.__browser_focus_listeners["list"] = list_canvas_item.focus_changed_event.listen(self.__notify_focus_changed)
            self.__browser_thumbnail_loaders["list"] = DataPanelBrowserThumbnailLoader(list_canvas_item, document_controller.event_loop)
            self.__browser_view_items["list"] = list_canvas_item
            self.__browser_wrapper_items["list"] = list_scroll_group_canvas_item
            self.__list_scroll_area_canvas_item = list_scroll_area_canvas_item
            self.__list_scroll_bar_canvas_item = list_scroll_bar_canvas_item
        return list_scroll_group_canvas_item

    def __ensure_detail_canvas_item(self) -> CanvasItem.CanvasItemComposition:
        # build the detail canvas item and its wrapper the first time it's needed. see the comment in __init__ near
        # __browser_view_items for why this is lazy.
        detail_scroll_group_canvas_item = self.__browser_wrapper_items["detail"]
        if detail_scroll_group_canvas_item is None:
            document_controller = self.document_controller
            detail_item_height = get_detail_item_height(document_controller.get_font_metrics)

            def detail_item_factory(item: typing.Any, is_selected_model: Model.PropertyModel[bool]) -> CanvasItem.AbstractCanvasItem:
                return DataPanelDetailItem(typing.cast(DisplayItem.DisplayItem, item), document_controller.ui, DataPanelUISettings(document_controller.ui), detail_item_height)

            # note is_shared_selection is True across all browser types' canvas items. prevents the selection from being updated when items are inserted.
            # instead, the selection in the model itself is used.
            detail_canvas_item = ListCanvasItem.ListCanvasItem2(Panel.ThreadSafeListModel(self.__display_items_model, document_controller.event_loop), self.__selection, detail_item_factory, self.__item_delegate, item_height=detail_item_height, key="display_items", is_shared_selection=True)
            detail_canvas_item.wants_drag_events = True
            detail_scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(detail_canvas_item)
            detail_scroll_area_canvas_item.auto_resize_contents = True
            detail_scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(detail_scroll_area_canvas_item, CanvasItem.Orientation.Vertical)
            detail_scroll_group_canvas_item = CanvasItem.CanvasItemComposition()
            detail_scroll_group_canvas_item.layout = CanvasItem.CanvasItemRowLayout()
            detail_scroll_group_canvas_item.add_canvas_item(detail_scroll_area_canvas_item)
            detail_scroll_group_canvas_item.add_canvas_item(detail_scroll_bar_canvas_item)
            self.__stack_canvas_item.add_canvas_item(detail_scroll_group_canvas_item)
            self.__browser_focus_listeners["detail"] = detail_canvas_item.focus_changed_event.listen(self.__notify_focus_changed)
            self.__browser_thumbnail_loaders["detail"] = DataPanelBrowserThumbnailLoader(detail_canvas_item, document_controller.event_loop)
            self.__browser_view_items["detail"] = detail_canvas_item
            self.__browser_wrapper_items["detail"] = detail_scroll_group_canvas_item
            self.__detail_dates_periodic_listeners = add_detail_dates_periodic_listeners(document_controller, detail_canvas_item)
        return detail_scroll_group_canvas_item

    def __ensure_grid_canvas_item(self) -> CanvasItem.CanvasItemComposition:
        # build the grid canvas item and its wrapper the first time it's needed (see the comment in
        # __init__ near __browser_view_items for why this is lazy). shaped like
        # DisplayPanel.__ensure_grid_browser_canvas_item, but this view is never torn down once built,
        # since there's only ever one DataPanel (unlike DisplayPanel, which can have many open at once).
        grid_scroll_group_canvas_item = self.__browser_wrapper_items["grid"]
        if grid_scroll_group_canvas_item is None:
            document_controller = self.document_controller

            def grid_item_factory(item: typing.Any, is_selected_model: Model.PropertyModel[bool]) -> CanvasItem.AbstractCanvasItem:
                return DataPanelGridItem(typing.cast(DisplayItem.DisplayItem, item), document_controller.ui, DataPanelUISettings(document_controller.ui))

            # note is_shared_selection is True across all browser types' canvas items. prevents the selection from being updated when items are inserted.
            # instead, the selection in the model itself is used.
            line_height = document_controller.get_font_metrics("11px sans-serif", "M").height
            grid_canvas_item = GridCanvasItem.GridCanvasItem2(Panel.ThreadSafeListModel(self.__display_items_model, document_controller.event_loop), self.__selection, grid_item_factory, self.__item_delegate, item_size=Geometry.IntSize(80 + line_height, 80), key="display_items", is_shared_selection=True)
            grid_canvas_item.wants_drag_events = True
            grid_scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(grid_canvas_item)
            grid_scroll_area_canvas_item.auto_resize_contents = True
            grid_scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(grid_scroll_area_canvas_item, CanvasItem.Orientation.Vertical)
            grid_scroll_group_canvas_item = CanvasItem.CanvasItemComposition()
            grid_scroll_group_canvas_item.layout = CanvasItem.CanvasItemRowLayout()
            grid_scroll_group_canvas_item.add_canvas_item(grid_scroll_area_canvas_item)
            grid_scroll_group_canvas_item.add_canvas_item(grid_scroll_bar_canvas_item)
            self.__stack_canvas_item.add_canvas_item(grid_scroll_group_canvas_item)
            self.__browser_focus_listeners["grid"] = grid_canvas_item.focus_changed_event.listen(self.__notify_focus_changed)
            self.__browser_thumbnail_loaders["grid"] = DataPanelBrowserThumbnailLoader(grid_canvas_item, document_controller.event_loop)
            self.__browser_view_items["grid"] = grid_canvas_item
            self.__browser_wrapper_items["grid"] = grid_scroll_group_canvas_item
        return grid_scroll_group_canvas_item

    @property
    def _list_canvas_item(self) -> ListCanvasItem.ListCanvasItem2:
        self.__ensure_list_canvas_item()
        list_canvas_item = self.__browser_view_items["list"]
        assert isinstance(list_canvas_item, ListCanvasItem.ListCanvasItem2)
        return list_canvas_item

    @property
    def _data_list_canvas_item(self) -> CanvasItem.CanvasItemComposition:
        return self.__ensure_list_canvas_item()

    @property
    def _scroll_area_canvas_item(self) -> CanvasItem.ScrollAreaCanvasItem:
        self.__ensure_list_canvas_item()
        assert self.__list_scroll_area_canvas_item is not None
        return self.__list_scroll_area_canvas_item

    @property
    def _scroll_bar_canvas_item(self) -> CanvasItem.ScrollBarCanvasItem:
        self.__ensure_list_canvas_item()
        assert self.__list_scroll_bar_canvas_item is not None
        return self.__list_scroll_bar_canvas_item

    @property
    def _detail_canvas_item(self) -> ListCanvasItem.ListCanvasItem2:
        self.__ensure_detail_canvas_item()
        detail_canvas_item = self.__browser_view_items["detail"]
        assert isinstance(detail_canvas_item, ListCanvasItem.ListCanvasItem2)
        return detail_canvas_item

    @property
    def _data_detail_canvas_item(self) -> CanvasItem.CanvasItemComposition:
        return self.__ensure_detail_canvas_item()

    @property
    def _grid_canvas_item(self) -> GridCanvasItem.GridCanvasItem2:
        self.__ensure_grid_canvas_item()
        grid_canvas_item = self.__browser_view_items["grid"]
        assert isinstance(grid_canvas_item, GridCanvasItem.GridCanvasItem2)
        return grid_canvas_item

    @property
    def _data_grid_canvas_item(self) -> CanvasItem.CanvasItemComposition:
        return self.__ensure_grid_canvas_item()

    def __notify_focus_changed(self) -> None:
        # this is called when the keyboard focus for the data panel is changed.
        # if we are receiving focus, tell the window (document_controller) that
        # we now have the focus.
        if any(view_item is not None and view_item.focused for view_item in self.__browser_view_items.values()):
            self.document_controller.data_panel_focused()

    def _switch_to_browser_type_for_test(self, browser_type_id: str) -> None:
        self.__switch_to_browser_type(browser_type_id, persist=False)

    def _request_focus_for_test(self) -> None:
        self.__ensure_list_canvas_item()
        list_canvas_item = self.__browser_view_items["list"]
        assert list_canvas_item is not None
        list_canvas_item.request_focus()

    def make_selection_visible(self) -> None:
        for view_item in self.__browser_view_items.values():
            if view_item is not None:
                view_item.make_selection_visible()
