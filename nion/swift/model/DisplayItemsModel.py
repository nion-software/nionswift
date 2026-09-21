"""Two chained models over the document's display items, used by the data panel.

DocumentController keeps a DisplayItemsModel, filtered by the current project/session/group filter and
sorted by date (this only changes when the user switches groups or collections), and on top of that a
FilteredDisplayItemsModel, filtered again by whatever the user types into the search box. That second
filter changes on every keystroke, so it needs to be fast.

Both classes work against the same simple container contract: something with a display_items property that
fires item_inserted_event/item_removed_event for key "display_items" (DocumentModel and DataGroup both
qualify), plus one begin_change/end_change pair for batching. Since FilteredDisplayItemsModel never sorts,
its filtered list is always a subsequence of the master list in the same order, so a filter change can be
applied as a single pass that only touches the items whose membership actually changed, instead of rebuilding
the whole list.
"""

from __future__ import annotations

import operator
import typing

from nion.swift.model import DisplayItem
from nion.utils import Event
from nion.utils import ListModel
from nion.utils import Selection
from nion.utils.ReferenceCounting import weak_partial

SortKeyCallable = typing.Callable[[DisplayItem.DisplayItem], typing.Any]


class DisplayItemsContainerLike(typing.Protocol):
    item_inserted_event: Event.Event
    item_removed_event: Event.Event

    @property
    def display_items(self) -> typing.Sequence[DisplayItem.DisplayItem]: raise NotImplementedError()


class DisplayItemsModelLike(typing.Protocol):
    item_inserted_event: Event.Event
    item_removed_event: Event.Event
    begin_changes_event: Event.Event
    end_changes_event: Event.Event

    @property
    def items(self) -> typing.Sequence[DisplayItem.DisplayItem]: raise NotImplementedError()


class DisplayItemsModel:
    """A filtered, optionally sorted view of a container's display items.

    The container is a DocumentModel or a DataGroup. Item insertions/removals from the container are applied
    incrementally (with a binary search if sorted). Changing the container, filter, or sort key only happens
    on a data group / collection switch, so that's just handled with a full rebuild.
    """

    def __init__(self) -> None:
        self.item_inserted_event = Event.Event()
        self.item_removed_event = Event.Event()
        self.begin_changes_event = Event.Event()
        self.end_changes_event = Event.Event()
        # bookkeeping for DocumentController to remember which named filter is active; not used here.
        self.filter_id: str | None = None
        self.__container: DisplayItemsContainerLike | None = None
        self.__filter: ListModel.Filter = ListModel.Filter(True)
        self.__sort_key: SortKeyCallable | None = None
        self.__sort_reverse = False
        self.__items: list[DisplayItem.DisplayItem] = list()
        self.__included: set[DisplayItem.DisplayItem] = set()  # mirrors self.__items for O(1) membership tests
        self.__item_changed_listeners: dict[DisplayItem.DisplayItem, Event.EventListener | None] = dict()
        self.__item_inserted_listener: Event.EventListener | None = None
        self.__item_removed_listener: Event.EventListener | None = None
        self.__selections: list[Selection.IndexedSelection] = list()

    def close(self) -> None:
        self.set_container_filter_sort(None, ListModel.Filter(True), None, False)

    @property
    def items(self) -> typing.Sequence[DisplayItem.DisplayItem]:
        return list(self.__items)

    @property
    def display_items(self) -> typing.Sequence[DisplayItem.DisplayItem]:
        return self.items

    @property
    def item_count(self) -> int:
        return len(self.__items)

    @property
    def container(self) -> DisplayItemsContainerLike | None:
        return self.__container

    @container.setter
    def container(self, container: DisplayItemsContainerLike | None) -> None:
        self.set_container_filter_sort(container, self.__filter, self.__sort_key, self.__sort_reverse)

    @property
    def filter(self) -> ListModel.Filter:
        return self.__filter

    @filter.setter
    def filter(self, value: ListModel.Filter) -> None:
        self.set_container_filter_sort(self.__container, value, self.__sort_key, self.__sort_reverse)

    @property
    def sort_key(self) -> SortKeyCallable | None:
        return self.__sort_key

    def make_selection(self) -> Selection.IndexedSelection:
        selection = Selection.IndexedSelection()
        self.__selections.append(selection)
        return selection

    def release_selection(self, selection: Selection.IndexedSelection) -> None:
        self.__selections.remove(selection)

    def set_container_filter_sort(self, container: DisplayItemsContainerLike | None, filter_: ListModel.Filter, sort_key: SortKeyCallable | None, sort_reverse: bool) -> None:
        # this only happens on a data group / collection switch, so it's fine to just tear down and rebuild.
        self.begin_changes_event.fire("display_items")
        try:
            if self.__item_inserted_listener:
                self.__item_inserted_listener.close()
                self.__item_inserted_listener = None
            if self.__item_removed_listener:
                self.__item_removed_listener.close()
                self.__item_removed_listener = None
            for listener in self.__item_changed_listeners.values():
                if listener:
                    listener.close()
            self.__item_changed_listeners.clear()

            for index in reversed(range(len(self.__items))):
                self.__remove_item_at_index(index)

            self.__container = container
            self.__filter = filter_
            self.__sort_key = sort_key
            self.__sort_reverse = sort_reverse

            if container is not None:
                self.__item_inserted_listener = container.item_inserted_event.listen(weak_partial(DisplayItemsModel.__container_item_inserted, self))
                self.__item_removed_listener = container.item_removed_event.listen(weak_partial(DisplayItemsModel.__container_item_removed, self))
                # do this directly instead of calling __insert_item per item -- that does a position
                # search for each one, which would make populating the whole list O(n^2).
                display_items = list(container.display_items)
                for item in display_items:
                    item_changed_listener = item.item_changed_event.listen(weak_partial(DisplayItemsModel.__item_changed, self, item)) if hasattr(item, "item_changed_event") else None
                    self.__item_changed_listeners[item] = item_changed_listener
                matched_items = [item for item in display_items if filter_.matches(item)]
                if sort_key is not None:
                    matched_items.sort(key=sort_key, reverse=sort_reverse)
                for index, item in enumerate(matched_items):
                    self.__items.append(item)
                    self.__included.add(item)
                    self.item_inserted_event.fire("display_items", item, index)
                    for selection in self.__selections:
                        selection.insert_index(index)
        finally:
            self.end_changes_event.fire("display_items")

    def __container_item_inserted(self, key: str, item: DisplayItem.DisplayItem, before_index: int) -> None:
        if key != "display_items":
            return
        item_changed_listener = item.item_changed_event.listen(weak_partial(DisplayItemsModel.__item_changed, self, item)) if hasattr(item, "item_changed_event") else None
        self.__item_changed_listeners[item] = item_changed_listener
        if self.__filter.matches(item):
            self.__insert_item(item, before_index)

    def __container_item_removed(self, key: str, item: DisplayItem.DisplayItem, index: int) -> None:
        if key != "display_items":
            return
        listener = self.__item_changed_listeners.pop(item, None)
        if listener:
            listener.close()
        if item in self.__included:
            self.__remove_item_at_index(self.__items.index(item))

    def __item_changed(self, item: DisplayItem.DisplayItem) -> None:
        # item changed, so it might need to be added, removed, or re-sorted. this fires on every
        # item_changed_event -- including once per frame while something is live-acquiring -- so
        # was_included needs to be a quick set lookup, not a list scan.
        was_included = item in self.__included
        is_included = self.__filter.matches(item)
        if was_included and not is_included:
            self.__remove_item_at_index(self.__items.index(item))
        elif is_included and not was_included:
            self.__insert_item(item, None)
        elif was_included and is_included and self.__sort_key:
            old_index = self.__items.index(item)
            # pull the item out first -- otherwise it's still sitting in its old (now wrong) spot, which
            # would break the binary search.
            items_without_item = self.__items[:old_index] + self.__items[old_index + 1:]
            new_index = self.__find_sorted_index(item, items_without_item)
            if new_index != old_index:
                self.__remove_item_at_index(old_index)
                self.__insert_item_at_index(item, new_index)

    def __find_sorted_index(self, item: DisplayItem.DisplayItem, items: typing.Sequence[DisplayItem.DisplayItem]) -> int:
        sort_key = self.__sort_key
        assert sort_key is not None
        sort_operator = operator.gt if self.__sort_reverse else operator.lt
        item_key = sort_key(item)
        low = 0
        high = len(items)
        while low < high:
            mid = (low + high) // 2
            if sort_operator(sort_key(items[mid]), item_key):
                low = mid + 1
            else:
                high = mid
        return low

    def __find_unsorted_index(self, item: DisplayItem.DisplayItem, container_index: int | None) -> int:
        container_items = self.__container.display_items if self.__container else ()
        # common case: item was just appended to the container (e.g. importing new data), so there's
        # nothing to scan for -- everything already included comes before it.
        if container_index is not None and container_index == len(container_items) - 1:
            return len(self.__items)
        index = 0
        for container_item in container_items:
            if container_item == item:
                break
            if self.__filter.matches(container_item):
                index += 1
        return index

    def __insert_item(self, item: DisplayItem.DisplayItem, container_index: int | None) -> None:
        before_index = self.__find_sorted_index(item, self.__items) if self.__sort_key else self.__find_unsorted_index(item, container_index)
        self.__insert_item_at_index(item, before_index)

    def __insert_item_at_index(self, item: DisplayItem.DisplayItem, before_index: int) -> None:
        self.__items.insert(before_index, item)
        self.__included.add(item)
        self.item_inserted_event.fire("display_items", item, before_index)
        for selection in self.__selections:
            selection.insert_index(before_index)

    def __remove_item_at_index(self, index: int) -> None:
        item = self.__items.pop(index)
        self.__included.discard(item)
        self.item_removed_event.fire("display_items", item, index)
        for selection in self.__selections:
            selection.remove_index(index)


class FilteredDisplayItemsModel:
    """A further-filtered view of a DisplayItemsModel's items, preserving the master order.

    Unlike DisplayItemsModel, this one never sorts -- it only filters, and always keeps the master's
    ordering. That means the old and new filtered lists are always subsequences of the same master order,
    so a filter change can be applied as a single O(n) pass that only emits the inserts/removes actually
    needed, instead of removing and re-inserting everything. This matters because it's the hot path: the
    interactive search/date filter changes on every keystroke, and documents can be large.
    """

    def __init__(self, master: DisplayItemsModelLike) -> None:
        self.item_inserted_event = Event.Event()
        self.item_removed_event = Event.Event()
        self.begin_changes_event = Event.Event()
        self.end_changes_event = Event.Event()
        self.__filter: ListModel.Filter = ListModel.Filter(True)
        self.__master_items: list[DisplayItem.DisplayItem] = list()
        self.__items: list[DisplayItem.DisplayItem] = list()
        self.__included: set[DisplayItem.DisplayItem] = set()  # mirrors self.__items for O(1) membership tests
        self.__item_changed_listeners: dict[DisplayItem.DisplayItem, Event.EventListener | None] = dict()
        self.__selections: list[Selection.IndexedSelection] = list()
        self.__change_level = 0

        self.__master = master
        self.__master_item_inserted_listener = master.item_inserted_event.listen(weak_partial(FilteredDisplayItemsModel.__master_item_inserted, self))
        self.__master_item_removed_listener = master.item_removed_event.listen(weak_partial(FilteredDisplayItemsModel.__master_item_removed, self))
        self.__master_begin_changes_listener = master.begin_changes_event.listen(weak_partial(FilteredDisplayItemsModel.__master_begin_changes, self))
        self.__master_end_changes_listener = master.end_changes_event.listen(weak_partial(FilteredDisplayItemsModel.__master_end_changes, self))

        # do this directly in master order instead of going through __master_item_inserted per item, which
        # would make this O(n^2).
        for item in master.items:
            self.__master_items.append(item)
            item_changed_listener = item.item_changed_event.listen(weak_partial(FilteredDisplayItemsModel.__item_changed, self, item)) if hasattr(item, "item_changed_event") else None
            self.__item_changed_listeners[item] = item_changed_listener
            if self.__filter.matches(item):
                self.__items.append(item)
                self.__included.add(item)

    def close(self) -> None:
        self.__master_item_inserted_listener = typing.cast(typing.Any, None)
        self.__master_item_removed_listener = typing.cast(typing.Any, None)
        self.__master_begin_changes_listener = typing.cast(typing.Any, None)
        self.__master_end_changes_listener = typing.cast(typing.Any, None)
        for listener in self.__item_changed_listeners.values():
            if listener:
                listener.close()
        self.__item_changed_listeners.clear()

    @property
    def items(self) -> typing.Sequence[DisplayItem.DisplayItem]:
        return list(self.__items)

    @property
    def display_items(self) -> typing.Sequence[DisplayItem.DisplayItem]:
        return self.items

    @property
    def item_count(self) -> int:
        return len(self.__items)

    @property
    def filter(self) -> ListModel.Filter:
        return self.__filter

    @filter.setter
    def filter(self, value: ListModel.Filter) -> None:
        self.__begin_change()
        try:
            self.__filter = value
            self.__apply_filter_diff()
        finally:
            self.__end_change()

    def make_selection(self) -> Selection.IndexedSelection:
        selection = Selection.IndexedSelection()
        self.__selections.append(selection)
        return selection

    def release_selection(self, selection: Selection.IndexedSelection) -> None:
        self.__selections.remove(selection)

    def __begin_change(self) -> None:
        if self.__change_level == 0:
            self.begin_changes_event.fire("display_items")
        self.__change_level += 1

    def __end_change(self) -> None:
        self.__change_level -= 1
        if self.__change_level == 0:
            self.end_changes_event.fire("display_items")

    def __master_begin_changes(self, key: str) -> None:
        if key == "display_items":
            self.__begin_change()

    def __master_end_changes(self, key: str) -> None:
        if key == "display_items":
            self.__end_change()

    def __master_item_inserted(self, key: str, item: DisplayItem.DisplayItem, before_index: int) -> None:
        if key != "display_items":
            return
        self.__master_items.insert(before_index, item)
        item_changed_listener = item.item_changed_event.listen(weak_partial(FilteredDisplayItemsModel.__item_changed, self, item)) if hasattr(item, "item_changed_event") else None
        self.__item_changed_listeners[item] = item_changed_listener
        if self.__filter.matches(item):
            self.__insert_item_at_index(item, self.__position_for_master_index(before_index))

    def __master_item_removed(self, key: str, item: DisplayItem.DisplayItem, index: int) -> None:
        if key != "display_items":
            return
        del self.__master_items[index]
        listener = self.__item_changed_listeners.pop(item, None)
        if listener:
            listener.close()
        if item in self.__included:
            self.__remove_item_at_index(self.__items.index(item))

    def __item_changed(self, item: DisplayItem.DisplayItem) -> None:
        was_included = item in self.__included
        is_included = self.__filter.matches(item)
        if was_included and not is_included:
            self.__remove_item_at_index(self.__items.index(item))
        elif is_included and not was_included:
            master_index = self.__master_items.index(item)
            self.__insert_item_at_index(item, self.__position_for_master_index(master_index))

    def __position_for_master_index(self, master_index: int) -> int:
        # how many currently-filtered-in items come before master_index in master order.
        # if it's the last item in master (e.g. one just got appended), skip the scan -- everything already
        # included comes before it.
        if master_index == len(self.__master_items) - 1:
            return len(self.__items)
        position = 0
        for master_item in self.__master_items[:master_index]:
            if master_item in self.__included:
                position += 1
        return position

    def __apply_filter_diff(self) -> None:
        # master order hasn't changed, only the filter -- so the old and new filtered lists are both
        # subsequences of master in the same order. walk master once and only emit an insert/remove for
        # items whose membership actually flipped.
        master_items = self.__master_items
        old_items = list(self.__items)  # snapshot; self.__items is mutated in place below
        new_filter = self.__filter
        old_len = len(old_items)
        old_index = 0  # position into old_items (the snapshot)
        position = 0  # position into self.__items (the live list being edited)
        for item in master_items:
            was_included = old_index < old_len and old_items[old_index] == item
            if was_included:
                old_index += 1
            is_included = new_filter.matches(item)
            if was_included and is_included:
                position += 1
            elif was_included and not is_included:
                self.__remove_item_at_index(position)
            elif is_included and not was_included:
                self.__insert_item_at_index(item, position)
                position += 1

    def __insert_item_at_index(self, item: DisplayItem.DisplayItem, before_index: int) -> None:
        self.__items.insert(before_index, item)
        self.__included.add(item)
        self.item_inserted_event.fire("display_items", item, before_index)
        for selection in self.__selections:
            selection.insert_index(before_index)

    def __remove_item_at_index(self, index: int) -> None:
        item = self.__items.pop(index)
        self.__included.discard(item)
        self.item_removed_event.fire("display_items", item, index)
        for selection in self.__selections:
            selection.remove_index(index)
