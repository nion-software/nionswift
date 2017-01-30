"""
    Contains classes that help bind a list of data items to another object.
"""

# standard libraries
import copy
import logging
import operator
import re
import threading
import typing

# third party libraries
# None

# local libraries
from nion.swift.model import DataItem
from nion.utils import Binding
from nion.ui import Selection


class Filter:
    def __init__(self, default: bool=False):
        self.__default = default

    def __deepcopy__(self, memo):
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result
        result.__default = self.__default
        return result

    def matches(self, d) -> bool:
        return self.__default


class AndFilter(Filter):
    def __init__(self, filters: typing.Sequence[Filter]=None):
        super().__init__()
        self.__filters = copy.copy(filters) if filters else list()

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.__filters = copy.deepcopy(self.__filters, memo)
        return result

    def matches(self, d) -> bool:
        return all(map(operator.methodcaller('matches', d), self.__filters))


class OrFilter(Filter):
    def __init__(self, filters: typing.Sequence[Filter]=None):
        super().__init__()
        self.__filters = copy.copy(filters) if filters else list()

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.__filters = copy.deepcopy(self.__filters, memo)
        return result

    def matches(self, d) -> bool:
        return any(map(operator.methodcaller('matches', d), self.__filters))


class NotFilter(Filter):
    def __init__(self, filter: Filter):
        super().__init__()
        self.__filter = filter

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.__filter = copy.deepcopy(self.__filter, memo)
        return result

    def matches(self, d) -> bool:
        return not self.__filter.matches(d)


class EqFilter(Filter):
    def __init__(self, key: str, value, cmp=None):
        super().__init__()
        self.__key = key
        self.__value = value
        self.__cmp = cmp if cmp else operator.eq

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.__key = self.__key
        result.__value = self.__value
        result.__cmp = self.__cmp
        return result

    def matches(self, d) -> bool:
        d_value = getattr(d, self.__key)
        return self.__cmp(d_value, self.__value)


class NotEqFilter(Filter):
    def __init__(self, key: str, value, cmp=None):
        super().__init__()
        self.__key = key
        self.__value = value
        self.__cmp = cmp if cmp else operator.eq

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.__key = self.__key
        result.__value = self.__value
        result.__cmp = self.__cmp
        return result

    def matches(self, d) -> bool:
        d_value = getattr(d, self.__key)
        return not self.__cmp(d_value, self.__value)


class StartsWithFilter(Filter):
    def __init__(self, key: str, value: str):
        super().__init__()
        self.__key = key
        self.__value = value

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.__key = self.__key
        result.__value = self.__value
        return result

    def matches(self, d) -> bool:
        d_value = getattr(d, self.__key)
        return d_value.startswith(self.__value)


class TextFilter(Filter):
    def __init__(self, key: str, text: str):
        super().__init__()
        self.__key = key
        self.__text = text

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.__key = self.__key
        result.__text = self.__text
        return result

    def matches(self, d) -> bool:
        d_value = getattr(d, self.__key)
        return re.search(self.__text, d_value, re.IGNORECASE)


class PartialDateFilter(Filter):
    def __init__(self, key: str, year: int=None, month: int=None, day: int=None):
        super().__init__()
        self.__key = key
        self.__year = year
        self.__month = month
        self.__day = day

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.__key = self.__key
        result.__year = self.__year
        result.__month = self.__month
        result.__day = self.__day
        return result

    def matches(self, d) -> bool:
        d_value = getattr(d, self.__key)
        if self.__year and d_value.year != self.__year:
            return False
        if self.__month and d_value.month != self.__month:
            return False
        if self.__day and d_value.day != self.__day:
            return False
        return True


class PredicateFilter(Filter):
    # used for testing, not serializable
    def __init__(self, predicate):
        super().__init__()
        self.__predicate = predicate

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result.__predicate = self.__predicate
        return result

    def matches(self, d) -> bool:
        return self.__predicate(d)


SortKeyCallable = typing.Callable[[DataItem.DataItem], typing.Any]


class AbstractDataItemsBinding(Binding.Binding):

    """
        Abstract base class to track a list of data items, generating insert and remove messages.

        Subclasses must override _get_master_data_items.

        When making changes to the master data items, they can then call _update_data_items to
        automatically generate insert and remove messages.

        Alternatively, they can call _inserted_master_data_item and _removed_master_data_item for
        finer grained control. These calls can be significantly faster than _update_data_items.

        This class implements a filter function and a sorting function. Both the filter and
        sorting can be changed on the fly and this class will generate the appropriate insert
        and remove messages.

        Clients can add themselves to the list of inserters and removers to get messages from
        this class.

        Since changes can be slow, multiple changes are allowed to be made simultaneously by
        calling begin_change and end_change around the changes, or by using a context manager
        available via the changes method. Only _update_data_items is valid during the changes
        method. _inserted_master_data_item and _removed_master_data_item are invalid and will
        raise an exception.

        The current set of data items is returned using the data_items property.
    """

    def __init__(self):
        super(AbstractDataItemsBinding, self).__init__(None)
        self.__data_items = list()
        self._update_mutex = threading.RLock()
        self.inserters = dict()
        self.removers = dict()
        self.__filter = Filter(True)
        self.__sort_key = None
        self.__sort_reverse = False
        self.__change_level = 0

    def begin_change(self):
        """ Begin a set of changes. Balance with end_changes. """
        self.__change_level += 1

    def end_change(self):
        """ End a set of changes and update data items if finished. """
        with self._update_mutex:
            self.__change_level -= 1
            if self.__change_level == 0:
                self._update_data_items()

    def changes(self):
        """ Acquire this while setting filter or sort so that changes get made simultaneously. """
        class ChangeTracker(object):  # pylint: disable=missing-docstring
            def __init__(self, binding):
                self.__binding = binding
            def __enter__(self):
                self.__binding.begin_change()
                return self
            def __exit__(self, type_, value, traceback):
                self.__binding.end_change()
        return ChangeTracker(self)

    # thread safe.
    @property
    def sort_key(self) -> SortKeyCallable:
        """ Return the sort key function (for data item). """
        return self.__sort_key

    @sort_key.setter
    def sort_key(self, value: SortKeyCallable) -> None:
        """ Set the sort key function. """
        with self._update_mutex:
            self.__sort_key = value
        self._update_data_items()

    @property
    def sort_reverse(self) -> bool:
        """ Return the sort reverse value. """
        return self.__sort_reverse

    @sort_reverse.setter
    def sort_reverse(self, value: bool) -> None:
        """ Set the sort reverse value. """
        with self._update_mutex:
            self.__sort_reverse = value
        self._update_data_items()

    # thread safe.
    @property
    def filter(self) -> Filter:
        """ Return the filter function. """
        return self.__filter

    @filter.setter
    def filter(self, value: Filter) -> None:
        """ Set the filter function. """
        self.__filter = value
        self._update_data_items()

    @property
    def data_items(self) -> typing.Sequence[DataItem.DataItem]:
        """ Return the data items. """
        with self._update_mutex:
            return copy.copy(self.__data_items)

    # thread safe
    def _get_master_data_items(self):
        """
            Subclasses should implement this to return the master list of data items.

            This method must be thread safe.
        """
        raise NotImplementedError()

    def __find_sorted_index_for_data_item(self, data_item, data_items, sort_key, sort_operator):
        data_item_sort_key = sort_key(data_item)
        low = 0
        high = len(data_items)
        while low < high:
            mid = (low + high) // 2
            if sort_operator(sort_key(data_items[mid]), data_item_sort_key):
                low = mid + 1
            else:
                high = mid
        return low

    def __find_unsorted_index_for_data_item(self, data_item, master_data_items, filter):
        index = 0
        for data_item_ in master_data_items:
            if data_item_ == data_item:
                break
            if filter.matches(data_item_):
                index += 1
        return index

    # thread safe
    def _inserted_master_data_item(self, before_index, data_item):
        """
            Subclasses can call this to notify this object that a data item in
            the master data list has been inserted.
        """
        with self._update_mutex:
            if self.__change_level > 0:
                return
            if self.filter.matches(data_item):
                data_items = self.__data_items
                sort_key = self.sort_key
                if sort_key is not None:
                    sort_operator = operator.gt if self.sort_reverse else operator.lt
                    before_index = self.__find_sorted_index_for_data_item(data_item, data_items, sort_key, sort_operator)
                else:
                    before_index = self.__find_unsorted_index_for_data_item(data_item, self._get_master_data_items(), self.filter)
                self.__data_items.insert(before_index, data_item)
                for inserter in self.inserters.values():
                    inserter(data_item, before_index)

    # thread safe
    def _removed_master_data_item(self, index, data_item):
        """
            Subclasses can call this to notify this object that a data item in
            the master data list has been removed.
        """
        with self._update_mutex:
            if self.__change_level > 0:
                return
            if data_item in self.__data_items:
                index = self.__data_items.index(data_item)
                assert self.__data_items[index] == data_item
                del self.__data_items[index]
                for remover in self.removers.values():
                    remover(data_item, index)

    # thread safe
    def _updated_master_data_item(self, data_item):
        """
            Subclasses can call this to notify this object that a data item in
            the master data list has been updated.
        """
        with self._update_mutex:
            if self.__change_level > 0:
                return
            data_items = self.__data_items
            if self.filter.matches(data_item):
                # data item will be in the list
                sort_key = self.sort_key
                if sort_key is not None:
                    # are items sorted?
                    sort_operator = operator.gt if self.sort_reverse else operator.lt
                    before_index = self.__find_sorted_index_for_data_item(data_item, data_items, sort_key, sort_operator)
                    if data_item in data_items:
                        # data item already in list?
                        index = data_items.index(data_item)
                        if before_index < index:
                            self._removed_master_data_item(index, data_item)
                            self._inserted_master_data_item(before_index, data_item)
                        elif before_index > index:
                            self._removed_master_data_item(index, data_item)
                            self._inserted_master_data_item(before_index - 1, data_item)
                    else:
                        # data item is not in list, just insert
                        self._inserted_master_data_item(before_index, data_item)
                else:
                    # items are not sorted
                    if not data_item in data_items:
                        # data item is not in list, just insert. the before_index we pass will not be used so just pass 0
                        self._inserted_master_data_item(0, data_item)
            else:
                # data item will not be in list
                if data_item in data_items:
                    # data item already in list
                    index = data_items.index(data_item)
                    self._removed_master_data_item(index, data_item)

    # thread safe.
    def __build_data_items(self):
        """Build the data items from the master data items list.

        This method is thread safe.

        Builds the data items from the master list by sorting them and then
         filtering them.
        """
        master_data_items = self._get_master_data_items()
        assert len(set(master_data_items)) == len(master_data_items)
        # sort the master data list. this is optional since it may be sorted downstream.
        if self.sort_key is not None:
            master_data_items.sort(key=self.sort_key, reverse=self.sort_reverse)
        # construct the data items list by expanding each master data item to
        # include its children
        data_items = list()
        for data_item in master_data_items:
            # apply filter
            if self.filter.matches(data_item):
                # add data item and its dependent data items
                data_items.append(data_item)
        return data_items

    # thread safe.
    def _update_data_items(self):
        """Build the data items and generate change messages.

        Builds the data items from the master data item list, then generates a sequence of
         inserter and remover calls representing the changes from the previous list.
        """
        with self._update_mutex:
            if self.__change_level > 0:
                return
            # first build the new data_items list, including data items with master data.
            old_data_items = copy.copy(self.__data_items)
            data_items = self.__build_data_items()
            # now generate the insert/remove instructions to make the official
            # list match the proposed list.
            assert len(set(self._get_master_data_items())) == len(self._get_master_data_items())
            assert len(set(data_items)) == len(data_items)
            index = 0
            for data_item in data_items:
                # otherwise, if new data item at current index is in old list, remove it, then re-insert
                if data_item in old_data_items:
                    old_index = old_data_items.index(data_item)
                    assert index <= old_index
                    # remove, re-insert, unless old and new position are the same
                    if index < old_index:
                        assert data_item in self.__data_items
                        del old_data_items[old_index]
                        del self.__data_items[old_index]
                        for remover in self.removers.values():
                            remover(data_item, old_index)
                        assert data_item not in self.__data_items
                        old_data_items.insert(index, data_item)
                        self.__data_items.insert(index, data_item)
                        for inserter in self.inserters.values():
                            inserter(data_item, index)
                # else new data item at current index is not in old list, insert it
                else:
                    assert data_item not in self.__data_items
                    old_data_items.insert(index, data_item)
                    self.__data_items.insert(index, data_item)
                    for inserter in self.inserters.values():
                        inserter(data_item, index)
                index += 1
            # finally anything left in the old list can be removed
            while index < len(old_data_items):
                data_item_to_remove = old_data_items[index]
                assert data_item_to_remove in self.__data_items
                del old_data_items[index]
                del self.__data_items[index]
                for remover in self.removers.values():
                    remover(data_item_to_remove, index)


class DataItemsFilterBinding(AbstractDataItemsBinding):
    """Maintain a list of data items that tracks another list of data items.

    Filter and sort can be applied to this list independently of the source list.

    This class can also optionally keep a selection up to date.
    """

    def __init__(self, data_items_binding, selection=None):
        super(DataItemsFilterBinding, self).__init__()
        self.__master_data_items = list()
        self.__selections = list()
        if selection:
            self.__selections.append(selection)
        self.__data_items_binding = data_items_binding
        self.__data_items_binding.inserters[id(self)] = self.__data_item_inserted
        self.__data_items_binding.removers[id(self)] = self.__data_item_removed
        self.__data_item_content_changed_event_listeners = dict()
        for index, data_item in enumerate(self.__data_items_binding.data_items):
            self.__data_item_inserted(data_item, index)

    def close(self):
        for data_item in self._get_master_data_items():
            self.__data_item_removed(data_item, 0)
        self.__data_item_content_changed_event_listeners = None
        del self.__data_items_binding.inserters[id(self)]
        del self.__data_items_binding.removers[id(self)]
        self.__master_data_items = None
        self.__data_items_binding = None
        super(DataItemsFilterBinding, self).close()

    def make_selection(self):
        selection = Selection.IndexedSelection()
        self.__selections.append(selection)
        return selection

    def release_selection(self, selection):
        self.__selections.remove(selection)

    # thread safe.
    def __data_item_inserted(self, data_item, before_index):
        """ Handle insertion in the source list by updating this lists items. """
        with self._update_mutex:
            assert data_item not in self.__master_data_items
            self.__master_data_items.insert(before_index, data_item)

            def data_item_content_changed():
                with self._update_mutex:
                    if not data_item in self.__master_data_items:
                        logging.debug("Data item not in master list %s", data_item)
                    else:
                        self._updated_master_data_item(data_item)

            data_item_content_changed_event_listener = data_item.data_item_content_changed_event.listen(data_item_content_changed)
            self.__data_item_content_changed_event_listeners[data_item.uuid] = data_item_content_changed_event_listener
            self._inserted_master_data_item(before_index, data_item)
            for selection in self.__selections:
                selection.insert_index(before_index)

    # thread safe.
    def __data_item_removed(self, data_item, index):
        """ Handle removal from the source list by updating this lists items. """
        with self._update_mutex:
            assert data_item in self.__master_data_items
            assert self.__master_data_items[index] == data_item
            del self.__master_data_items[index]
            self.__data_item_content_changed_event_listeners[data_item.uuid].close()
            del self.__data_item_content_changed_event_listeners[data_item.uuid]
            self._removed_master_data_item(index, data_item)
            for selection in self.__selections:
                selection.remove_index(index)

    # thread safe
    def _get_master_data_items(self):
        with self._update_mutex:
            return copy.copy(self.__master_data_items)


class DataItemsInContainerBinding(AbstractDataItemsBinding):
    """Bind the data items in a container to this list."""

    def __init__(self):
        super(DataItemsInContainerBinding, self).__init__()
        self.__container = None
        self.__master_data_items = list()
        self.__data_item_content_changed_event_listeners = dict()
        self.__data_item_inserted_event_listener = None
        self.__data_item_removed_event_listener = None

    def close(self):
        self.container = None
        self.__data_item_content_changed_event_listeners = None
        super(DataItemsInContainerBinding, self).close()

    # thread safe.
    @property
    def container(self):
        return self.__container

    # thread safe.
    @container.setter
    def container(self, container):
        if self.__container:
            self.__data_item_inserted_event_listener.close()
            self.__data_item_inserted_event_listener = None
            self.__data_item_removed_event_listener.close()
            self.__data_item_removed_event_listener = None
            for data_item in reversed(copy.copy(self.__container.data_items)):
                self.data_item_removed(self.__container, data_item, len(self._get_master_data_items()) - 1, False)
        self.__container = container
        if self.__container:
            self.__data_item_inserted_event_listener = self.__container.data_item_inserted_event.listen(self.data_item_inserted)
            self.__data_item_removed_event_listener = self.__container.data_item_removed_event.listen(self.data_item_removed)
            for index, data_item in enumerate(self.__container.data_items):
                self.data_item_inserted(self.__container, data_item, index, False)

    # thread safe.
    def data_item_inserted(self, container, data_item, before_index, is_moving):
        """ Insert the data item. Called from the container. """
        with self._update_mutex:
            assert not data_item in self.__master_data_items
            self.__master_data_items.insert(before_index, data_item)

            # thread safe
            def data_item_content_changed():
                with self._update_mutex:
                    if not data_item in self.__master_data_items:
                        logging.debug("data item not in master data %s", data_item)
                    else:
                        self._updated_master_data_item(data_item)

            data_item_content_changed_event_listener = data_item.data_item_content_changed_event.listen(data_item_content_changed)
            self.__data_item_content_changed_event_listeners[data_item.uuid] = data_item_content_changed_event_listener
            self._inserted_master_data_item(before_index, data_item)

    # thread safe.
    def data_item_removed(self, container, data_item, index, is_moving):
        """ Remove the data item. Called from the container. """
        with self._update_mutex:
            del self.__master_data_items[index]
            self.__data_item_content_changed_event_listeners[data_item.uuid].close()
            del self.__data_item_content_changed_event_listeners[data_item.uuid]
            self._removed_master_data_item(index, data_item)

    # thread safe
    def _get_master_data_items(self):
        with self._update_mutex:
            return copy.copy(self.__master_data_items)
