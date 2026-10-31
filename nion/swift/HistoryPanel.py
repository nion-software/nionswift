"""The History panel, which lists the command history for debugging actions."""

from __future__ import annotations

# standard libraries
import dataclasses
import gettext
import threading
import typing

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.model import CommandHistory
from nion.swift.model import Feature
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import ListCanvasItem
from nion.ui import UserInterface
from nion.ui import Window
from nion.utils import Geometry
from nion.utils import Selection

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.swift.model import Persistence

_ = gettext.gettext


history_panel_feature_id = "feature.history_panel"

Feature.FeatureManager().add_feature(Feature.Feature(history_panel_feature_id, _("History panel, for debugging actions."), False))

ITEM_HEIGHT = 20

# the row's column widths, and the narrowest panel which shows the time and the detail columns; a narrower panel leaves
# them out, and the row's tool tip still shows them.
TIME_WIDTH = 56
KIND_WIDTH = 72
CHANGE_INDENT = 12
COLUMN_GAP = 8
MAX_DETAIL_WIDTH = 220
MIN_WIDTH_FOR_TIME = 400
MIN_WIDTH_FOR_DETAIL = 280


@dataclasses.dataclass(frozen=True)
class HistoryColumns:
    """The left edge and width of each column in a row of a given width; a column a narrow row leaves out has no width.

    The header and the rows share it, so that the header's titles stay above their columns.
    """
    time_left: float
    time_width: float
    kind_left: float
    title_left: float
    title_width: float
    detail_left: float
    detail_width: float

    @staticmethod
    def for_row(left: float, width: float) -> HistoryColumns:
        x = left + 4
        right = left + width - 4
        time_width = TIME_WIDTH if width >= MIN_WIDTH_FOR_TIME else 0
        time_left = x
        x += time_width + COLUMN_GAP if time_width else 0
        kind_left = x
        x += KIND_WIDTH + COLUMN_GAP
        detail_width = min(MAX_DETAIL_WIDTH, width * 0.35) if width >= MIN_WIDTH_FOR_DETAIL else 0
        detail_left = right - detail_width
        title_right = detail_left - COLUMN_GAP if detail_width else right
        return HistoryColumns(time_left, time_width, kind_left, x, max(title_right - x, 0), detail_left, detail_width)


def fill_column_text(drawing_context: DrawingContext.DrawingContext, text: str, left: float, width: float, top: float, height: float, color: str) -> None:
    """Draw the text from the column's left edge, cut off at its right edge."""
    if width > 0 and text:
        with drawing_context.saver():
            drawing_context.clip_rect(left, top, width, height)
            drawing_context.fill_style = color
            drawing_context.fill_text(text, left, top + height - 5)


# the color of each kind's label, so that actions, changes and undo or redo stand out from the rest.
KIND_COLORS: typing.Mapping[CommandHistory.CommandHistoryEntryKind, str] = {
    CommandHistory.CommandHistoryEntryKind.ACTION: "#2060C0",
    CommandHistory.CommandHistoryEntryKind.ACTION_END: "#2060C0",
    CommandHistory.CommandHistoryEntryKind.CHANGE: "#208040",
    CommandHistory.CommandHistoryEntryKind.UNDO: "#C06000",
    CommandHistory.CommandHistoryEntryKind.REDO: "#C06000",
}


def get_entry_detail(entry: CommandHistory.CommandHistoryEntry) -> str:
    """Return the entry's detail column: where an action came from, how long it ran, the action a change was made in, or its details."""
    if entry.kind == CommandHistory.CommandHistoryEntryKind.ACTION_END and entry.duration is not None:
        return f"{entry.duration * 1000:.0f} ms"
    if entry.kind == CommandHistory.CommandHistoryEntryKind.CHANGE and entry.action_id:
        return f"in {entry.action_id}"
    if origin_text := Window.invoked_from_text(entry.invoked_from, entry.invoked_from_id):
        return f"from {origin_text}"
    return entry.details or entry.identifier or str()


def get_entry_text(entry: CommandHistory.CommandHistoryEntry) -> str:
    """Return a line of text with every value of the entry, for Copy and for the row's tool tip."""
    detail = get_entry_detail(entry)
    parts = [entry.time.strftime("%H:%M:%S.%f")[:-3], str(entry.kind), entry.title]
    if entry.identifier and entry.identifier not in (entry.title, detail):
        parts.append(f"[{entry.identifier}]")
    if detail:
        parts.append(f"- {detail}")
    if entry.details and entry.details != detail:
        parts.append(f"({entry.details})")
    if entry.parameters:
        parts.append(", ".join(f"{key}={value!r}" for key, value in entry.parameters.items()))
    return " ".join(parts)


class HistoryListCanvasItemDelegate(ListCanvasItem.ListCanvasItemDelegate):
    """Draw each command history entry as a row of time, kind, title and detail."""

    def __init__(self) -> None:
        super().__init__()
        self.on_item_selected: typing.Callable[[int], None] | None = None
        self.on_cancel: typing.Callable[[], None] | None = None
        self.__entries: typing.Sequence[CommandHistory.CommandHistoryEntry] = list()

    @property
    def items(self) -> typing.Sequence[typing.Any]:
        return self.__entries

    @items.setter
    def items(self, value: typing.Sequence[typing.Any]) -> None:
        self.__entries = value

    @property
    def item_count(self) -> int:
        return len(self.__entries)

    def item_tool_tip(self, index: int) -> str | None:
        return get_entry_text(self.__entries[index]) if 0 <= index < len(self.__entries) else None

    def paint_item(self, drawing_context: DrawingContext.DrawingContext, display_item: typing.Any, rect: Geometry.IntRect, is_selected: bool) -> None:
        entry = typing.cast(CommandHistory.CommandHistoryEntry, display_item)
        columns = HistoryColumns.for_row(rect.left, rect.width)
        # a change made by an action is indented under it, with an arrow.
        is_in_action = entry.kind == CommandHistory.CommandHistoryEntryKind.CHANGE and bool(entry.action_id)
        indent = CHANGE_INDENT if is_in_action else 0
        title = f"\N{DOWNWARDS ARROW WITH TIP RIGHTWARDS} {entry.title}" if is_in_action else entry.title
        # a selected row draws its text in white, so that it reads on the selection's fill.
        time_color = "#FFF" if is_selected else "#888"
        kind_color = "#FFF" if is_selected else KIND_COLORS.get(entry.kind, "#888")
        title_color = "#FFF" if is_selected else "#000"
        detail_color = "#FFF" if is_selected else "#666"
        with drawing_context.saver():
            drawing_context.font = "11px"
            drawing_context.text_baseline = "alphabetic"
            drawing_context.text_align = "left"
            fill_column_text(drawing_context, entry.time.strftime("%H:%M:%S"), columns.time_left, columns.time_width, rect.top, rect.height, time_color)
            fill_column_text(drawing_context, str(entry.kind), columns.kind_left, KIND_WIDTH, rect.top, rect.height, kind_color)
            fill_column_text(drawing_context, title, columns.title_left + indent, columns.title_width - indent, rect.top, rect.height, title_color)
            fill_column_text(drawing_context, get_entry_detail(entry), columns.detail_left, columns.detail_width, rect.top, rect.height, detail_color)


class HistoryHeaderComposer(CanvasItem.BaseComposer):
    """Draw the History panel's column titles."""

    def _repaint(self, drawing_context: DrawingContext.DrawingContext, canvas_bounds: Geometry.IntRect, composer_cache: CanvasItem.ComposerCache) -> None:
        columns = HistoryColumns.for_row(canvas_bounds.left, canvas_bounds.width)
        with drawing_context.saver():
            drawing_context.begin_path()
            drawing_context.rect(canvas_bounds.left, canvas_bounds.top, canvas_bounds.width, canvas_bounds.height)
            drawing_context.fill_style = "#EEE"
            drawing_context.fill()
            drawing_context.begin_path()
            drawing_context.move_to(canvas_bounds.left, canvas_bounds.bottom - 0.5)
            drawing_context.line_to(canvas_bounds.right, canvas_bounds.bottom - 0.5)
            drawing_context.stroke_style = "#CCC"
            drawing_context.stroke()
            drawing_context.font = "bold 11px"
            drawing_context.text_baseline = "alphabetic"
            drawing_context.text_align = "left"
            top, height = canvas_bounds.top, canvas_bounds.height
            fill_column_text(drawing_context, _("Time"), columns.time_left, columns.time_width, top, height, "#444")
            fill_column_text(drawing_context, _("Kind"), columns.kind_left, KIND_WIDTH, top, height, "#444")
            fill_column_text(drawing_context, _("Title"), columns.title_left, columns.title_width, top, height, "#444")
            fill_column_text(drawing_context, _("Detail"), columns.detail_left, columns.detail_width, top, height, "#444")


class HistoryHeaderCanvasItem(CanvasItem.AbstractCanvasItem):
    """The History panel's column titles, which stay above the list as it scrolls."""

    def __init__(self) -> None:
        super().__init__()
        self.update_sizing(self.sizing.with_fixed_height(ITEM_HEIGHT))

    def _get_composer(self, composer_cache: CanvasItem.ComposerCache) -> CanvasItem.BaseComposer:
        return HistoryHeaderComposer(self, self.layout_sizing, composer_cache)


class HistoryListCanvasItem(ListCanvasItem.ListCanvasItem):
    """The list of command history entries, which copies the selected entries' text for the Copy edit command."""

    def __init__(self, ui: UserInterface.UserInterface, delegate: HistoryListCanvasItemDelegate, selection: Selection.IndexedSelection) -> None:
        super().__init__(delegate, selection, ITEM_HEIGHT)
        self.__ui = ui
        self.__history_delegate = delegate
        self.__history_selection = selection

    def handle_copy(self) -> bool:
        # the list handles Copy even with nothing selected, so that Copy doesn't reach the window and copy something else.
        entries = self.__history_delegate.items
        indexes = sorted(index for index in self.__history_selection.indexes if 0 <= index < len(entries))
        if indexes:
            self.__ui.clipboard_set_text("\n".join(get_entry_text(entries[index]) for index in indexes))
        return True


class HistoryPanel(Panel.Panel):
    """A panel which lists the most recent command history entries, one row each, for debugging actions."""

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: Persistence.PersistentDictType) -> None:
        super().__init__(document_controller, panel_id, _("History"))
        self.__delegate = HistoryListCanvasItemDelegate()
        self.__selection = Selection.IndexedSelection(Selection.Style.multiple)
        self.__list_canvas_item = HistoryListCanvasItem(self.ui, self.__delegate, self.__selection)
        self.__scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(self.__list_canvas_item)
        self.__scroll_area_canvas_item.auto_resize_contents = True
        scroll_group_canvas_item = CanvasItem.CanvasItemComposition()
        scroll_group_canvas_item.layout = CanvasItem.CanvasItemRowLayout()
        scroll_group_canvas_item.add_canvas_item(self.__scroll_area_canvas_item)
        scroll_group_canvas_item.add_canvas_item(CanvasItem.ScrollBarCanvasItem(self.__scroll_area_canvas_item))
        # the header leaves room for the scroll bar on its right, so that its titles line up with the rows' columns.
        header_row_canvas_item = CanvasItem.CanvasItemComposition()
        header_row_canvas_item.layout = CanvasItem.CanvasItemRowLayout()
        header_row_canvas_item.add_canvas_item(HistoryHeaderCanvasItem())
        header_row_canvas_item.add_spacing(16)
        header_row_canvas_item.update_sizing(header_row_canvas_item.sizing.with_fixed_height(ITEM_HEIGHT))
        list_column_canvas_item = CanvasItem.CanvasItemComposition()
        list_column_canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        list_column_canvas_item.add_canvas_item(header_row_canvas_item)
        list_column_canvas_item.add_canvas_item(scroll_group_canvas_item)
        canvas_widget = self.ui.create_canvas_widget()
        canvas_widget.canvas_item.add_canvas_item(list_column_canvas_item)
        # the column takes the registered properties, such as a preferred size, and expands to fill the panel.
        column = self.ui.create_column_widget(properties={"size-policy-horizontal": "expanding", "size-policy-vertical": "expanding", **properties})
        column.add_spacing(0)  # work around unexplained Qt layout issue where widget did not appear at top of column on macOS
        column.add(canvas_widget)
        column.add_spacing(0)
        self.widget = column

        # an entry may be appended on any thread, so the queued flag is protected by the lock, and the list is only
        # updated on the main thread.
        self.__lock = threading.RLock()
        self.__is_update_queued = False
        self.__is_closed = False

        self.__entry_appended_listener = CommandHistory.command_history.entry_appended_event.listen(self.__entry_appended)
        self.__update_entries()
        self.__scroll_area_canvas_item.scroll_to_end()

    @property
    def _list_canvas_item(self) -> HistoryListCanvasItem:
        return self.__list_canvas_item

    @property
    def _selection(self) -> Selection.IndexedSelection:
        return self.__selection

    def close(self) -> None:
        self.__is_closed = True
        self.__entry_appended_listener = typing.cast(typing.Any, None)
        super().close()

    def __entry_appended(self, entry: CommandHistory.CommandHistoryEntry) -> None:
        with self.__lock:
            is_update_needed = not self.__is_update_queued
            self.__is_update_queued = True
        if is_update_needed:
            self.document_controller.queue_task(self.__update_entries)

    def __update_entries(self) -> None:
        # runs on the main thread, after any entries appended since the last update.
        with self.__lock:
            self.__is_update_queued = False
        if not self.__is_closed:
            old_entries = self.__delegate.items
            entries = CommandHistory.command_history.entries
            # once the history is full, it drops its oldest entries; dropping their rows from the selection keeps it on
            # the same entries.
            dropped_count = next((index for index, entry in enumerate(old_entries) if entries and entry is entries[0]), len(old_entries))
            for dropped_index in range(dropped_count):
                self.__selection.remove_index(0)
            is_at_end = self.__is_at_end()
            self.__delegate.items = entries
            self.__list_canvas_item.size_to_content()
            self.__list_canvas_item.update()
            # new rows keep the end in view only when it was in view, so that a person reading older rows stays there.
            if is_at_end:
                self.__scroll_area_canvas_item.scroll_to_end()

    def __is_at_end(self) -> bool:
        # whether the last row is in view; before the first layout, there is nothing to scroll.
        scroll_area_canvas_item = self.__scroll_area_canvas_item
        canvas_size = scroll_area_canvas_item.canvas_size
        content_size = scroll_area_canvas_item.content_size
        if not canvas_size or not content_size:
            return True
        return -scroll_area_canvas_item.content_origin.y + canvas_size.height >= content_size.height
