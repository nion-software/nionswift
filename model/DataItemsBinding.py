"""
    Contains classes that help bind a list of data items to another object.
"""

# standard libraries
import collections
import copy
import threading
import weakref

# third party libraries
# None

# local libraries
from nion.swift.model import DataGroup
from nion.swift.model import Utility
from nion.ui import Binding
from nion.ui import Observable


class AbstractDataItemsBinding(Binding.Binding):

    """
        Abstract base class to track a list of data items, generating insert and remove messages.

        Subclasses should override _build_data_items and _get_master_data_items. This class will
        automatically generate insert and remove messages when _update_data_items is called.

        This class implements a filter function and a sorting function. Both the filter and
        sorting can be changed on the fly and this class will generate the appropriate insert
        and remove messages. It also implements a flat attribute, indicating whether children of
        data items should also be tracked.

        Clients can add themselves to the list of inserters and removers to get messages from
        this class.

        Since changes can be slow, multiple changes are allowed to be made simultaneously by
        calling begin_change and end_change around the changes, or by using the convenience
        changes method to return a context manager.

        The current set of data items is returned using the data_items property.
    """

    def __init__(self):
        super(AbstractDataItemsBinding, self).__init__(None)
        self.__data_items = list()
        self._update_mutex = threading.RLock()
        self.inserters = dict()
        self.removers = dict()
        self.__filter = None
        self.__sort = None
        self.__flat = False
        self.__change_level = 0

    def begin_change(self):
        """ Begin a set of changes. Balance with end_changes. """
        self.__change_level += 1

    def end_change(self):
        """ End a set of changes and update data items if finished. """
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
    def __get_sort(self):
        """ Return the sort compare function. """
        return self.__sort
    def __set_sort(self, sort):
        """ Set the sort compare function. """
        with self._update_mutex:
            self.__sort = sort
        self._update_data_items()
    sort = property(__get_sort, __set_sort)

    # thread safe.
    def __get_filter(self):
        """ Return the filter function. """
        return self.__filter
    def __set_filter(self, filter_):
        """ Set the filter function. """
        with self._update_mutex:
            self.__filter = filter_
        self._update_data_items()
    filter = property(__get_filter, __set_filter)

    # allow non-masters. 'get' has to be inheritable. ugh.
    def _get_flat(self):
        """ Return whether data item list is flattened. """
        return self.__flat
    def __set_flat(self, flat):
        """ Set whether data item list is flattened. """
        with self._update_mutex:
            self.__flat = flat
        self._update_data_items()
    flat = property(_get_flat, __set_flat)

    # thread safe
    # data items are the currently filtered and sorted list.
    def __get_data_items(self):
        """ Return the data items. """
        with self._update_mutex:
            return copy.copy(self.__data_items)
    data_items = property(__get_data_items)

    # thread safe
    def _get_master_data_items(self):
        """
            Subclasses should implement this to return the master list of data items.

            This method must be thread safe.
        """
        raise NotImplementedError()

    # thread safe.
    def _build_data_items(self):
        """
            Build the data items from the master data items list.

            This method is thread safe.
        """
        master_data_items = list()
        for data_item in self._get_master_data_items():
            if self.flat or data_item.has_master_data:
                master_data_items.append(data_item)
        assert len(set(master_data_items)) == len(master_data_items)
        # sort the master data list
        if self.sort:
            sort_key, reverse = self.sort()
            master_data_items.sort(key=sort_key, reverse=reverse)
        # construct the data items list by expanding each master data item to
        # include its children
        data_items = list()
        for data_item in master_data_items:
            # apply filter
            if self.filter is None or self.filter(data_item):
                # add data item and its dependent data items
                data_items.append(data_item)
                if not self.flat:
                    data_items.extend(list(DataGroup.get_flat_data_item_generator_in_container(data_item)))
        return data_items

    # thread safe.
    def _update_data_items(self):
        """
            Build the data items from the master list and generate
            a sequence of change messages.
        """
        if self.__change_level > 0:
            return
        with self._update_mutex:
            # first build the new data_items list, including data items with master data.
            old_data_items = copy.copy(self.__data_items)
            data_items = self._build_data_items()
            # now generate the insert/remove instructions to make the official
            # list match the proposed list.
            assert len(set(self._get_master_data_items())) == len(self._get_master_data_items())
            assert len(set(data_items)) == len(data_items)
            index = 0
            for data_item in data_items:
                # if old data item at current index isn't in new list, remove it
                if index < len(old_data_items) and old_data_items[index] not in data_items:
                    data_item_to_remove = old_data_items[index]
                    assert data_item_to_remove in self.__data_items
                    del old_data_items[index]
                    del self.__data_items[index]
                    for remover in self.removers.values():
                        remover(data_item_to_remove, index)
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

    """
        Maintain a list of data items that tracks another list of data items.

        Filter and sort can be applied to this list independently of the source list.

        The flat attribute is copied directly from the source list.
    """

    def __init__(self, data_items_binding):
        super(DataItemsFilterBinding, self).__init__()
        self.__master_data_items = list()
        self.__data_items_binding = data_items_binding
        self.__data_items_binding.inserters[id(self)] = self.__data_item_inserted
        self.__data_items_binding.removers[id(self)] = self.__data_item_removed
        self.flat = data_items_binding.flat

    def close(self):
        del self.__data_items_binding.inserters[id(self)]
        del self.__data_items_binding.removers[id(self)]
        super(DataItemsFilterBinding, self).close()

    # thread safe.
    def __data_item_inserted(self, data_item, before_index):
        """ Handle insertion in the source list by updating this lists items. """
        with self._update_mutex:
            assert data_item not in self.__master_data_items
            self.__master_data_items.insert(before_index, data_item)
        self._update_data_items()

    # thread safe.
    def __data_item_removed(self, data_item, index):
        """ Handle removal from the source list by updating this lists items. """
        with self._update_mutex:
            assert data_item in self.__master_data_items
            del self.__master_data_items[index]
        self._update_data_items()

    # thread safe
    def _get_master_data_items(self):
        return self.__master_data_items


class DataItemsInContainerBinding(AbstractDataItemsBinding):
    """
        Bind the data items in a container to this list.

        The container is listened to and must send the update_counted_data_items
        and subtract_counted_data_items messages to this object.
    """

    def __init__(self):
        super(DataItemsInContainerBinding, self).__init__()
        self.__counted_data_items = collections.Counter()
        self.__container = None

    def close(self):
        self.container = None
        super(DataItemsInContainerBinding, self).close()

    # thread safe.
    def __get_container(self):
        """ Return the container. """
        return self.__container
    # not thread safe.
    def __set_container(self, container):
        """ Set the container to which to listen. """
        if self.__container:
            self.__container.remove_listener(self)
            self.subtract_counted_data_items(self.__container.counted_data_items)
            self.__container.remove_ref()
        self.__container = container
        if self.__container:
            self.__container.add_ref()
            self.update_counted_data_items(self.__container.counted_data_items)
            self.__container.add_listener(self)
    container = property(__get_container, __set_container)

    # thread safe.
    def update_counted_data_items(self, counted_data_items):
        """ Update the counted items. Called from the container. """
        with self._update_mutex:
            self.__counted_data_items.update(counted_data_items)
        self._update_data_items()

    # thread safe.
    def subtract_counted_data_items(self, counted_data_items):
        """ Subtract the counted items. Called from the container. """
        with self._update_mutex:
            self.__counted_data_items.subtract(counted_data_items)
            self.__counted_data_items += collections.Counter()  # strip empty items
        self._update_data_items()

    # thread safe
    def _get_master_data_items(self):
        return self.__counted_data_items


def sort_natural(container):
    """ Return a sort key to sort by index within the given container. """
    flat_data_items = list(DataGroup.get_flat_data_item_generator_in_container(container))
    def sort_key(data_item):  # pylint: disable=missing-docstring
        return flat_data_items.index(data_item)
    return sort_key, False


def sort_by_date_desc():
    """ Return a sort key to sort by date descending. """
    def sort_key(data_item):  # pylint: disable=missing-docstring
        date_item_datetime = Utility.get_datetime_from_datetime_item(data_item.datetime_original)
        return date_item_datetime
    return sort_key, True


class DataItemQueueContainer(Observable.Broadcaster):
    """
        A queue of data items. Compatible with DataItemsInContainerBinding.

        A data item container, organized as a queue, for use with DataItemsInContainerBinding.
        Sends update_counted_data_items and subtract_counted_data_items messages.
    """
    def __init__(self):
        super(DataItemQueueContainer, self).__init__()
        self.__weak_data_items = collections.deque(maxlen=16)

    def __get_data_items(self):
        """ Return the data items in this container. """
        return [weak_data_item() for weak_data_item in self.__weak_data_items]
    data_items = property(__get_data_items)

    def insert_data_item(self, data_item):
        """ Insert a new data item into the queue. """
        old_counted_data_items = collections.Counter()
        old_counted_data_items.update(copy.copy(self.data_items))
        weak_data_item = weakref.ref(data_item)
        if weak_data_item in self.__weak_data_items:
            self.__weak_data_items.remove(weak_data_item)
        self.__weak_data_items.appendleft(weak_data_item)
        new_counted_data_items = collections.Counter()
        new_counted_data_items.update(copy.copy(self.data_items))
        self.notify_listeners("update_counted_data_items", new_counted_data_items)
        self.notify_listeners("subtract_counted_data_items", old_counted_data_items)

    def __get_counted_data_items(self):
        """ Return the counted data items. """
        counted_data_items = collections.Counter()
        counted_data_items.update(copy.copy(self.data_items))
        return counted_data_items
    counted_data_items = property(__get_counted_data_items)

    def add_ref(self):
        """ Used for testing. """
        pass

    def remove_ref(self):
        """ Used for testing. """
        pass
