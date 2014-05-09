"""
    Contains classes that help bind a list of data items to another object.
"""

# standard libraries
import copy
import operator
import threading

# third party libraries
# None

# local libraries
from nion.ui import Binding


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
        self.__filter = None
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
    def __get_sort_key(self):
        """ Return the sort key function (for data item). """
        return self.__sort_key
    def __set_sort_key(self, sort_key):
        """ Set the sort key function. """
        with self._update_mutex:
            self.__sort_key = sort_key
        self._update_data_items()
    sort_key = property(__get_sort_key, __set_sort_key)

    # thread safe.
    def __get_sort_reverse(self):
        """ Return the sort reverse value. """
        return self.__sort_reverse
    def __set_sort_reverse(self, sort_reverse):
        """ Set the sort reverse value. """
        with self._update_mutex:
            self.__sort_reverse = sort_reverse
        self._update_data_items()
    sort_reverse = property(__get_sort_reverse, __set_sort_reverse)

    # thread safe.
    def __get_filter(self):
        """ Return the filter function. """
        def always_true(dummy):  # pylint: disable=missing-docstring
            return True
        return self.__filter if self.__filter else always_true
    def __set_filter(self, filter_):
        """ Set the filter function. """
        with self._update_mutex:
            self.__filter = filter_
        self._update_data_items()
    filter = property(__get_filter, __set_filter)

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

    # thread safe
    def _inserted_master_data_item(self, before_index, data_item):
        """
            Subclasses can call this to notify this object that the master
            data list has been updated.
        """
        assert self.__change_level == 0
        data_item_filter = self.filter
        if data_item_filter(data_item):
            data_items = self.__data_items
            sort_key = self.sort_key
            sort_operator = operator.gt if self.sort_reverse else operator.lt
            if sort_key is not None:
                data_item_sort_key = sort_key(data_item)
                low = 0
                high = len(data_items)
                while low < high:
                    mid = (low + high) // 2
                    if sort_operator(sort_key(data_items[mid]), data_item_sort_key):
                        low = mid + 1
                    else:
                        high = mid
                before_index = low
            else:
                index = 0
                for data_item_ in self._get_master_data_items():
                    if data_item_ == data_item:
                        break
                    if data_item_filter(data_item_):
                        index += 1
                before_index = index
            with self._update_mutex:
                self.__data_items.insert(before_index, data_item)
                for inserter in self.inserters.values():
                    inserter(data_item, before_index)
        # self._update_data_items()

    # thread safe
    def _removed_master_data_item(self, index, data_item):
        """
            Subclasses can call this to notify this object that the master
            data list has been updated.
        """
        assert self.__change_level == 0
        if data_item in self.__data_items:
            index = self.__data_items.index(data_item)
            del self.__data_items[index]
            for remover in self.removers.values():
                remover(data_item, index)
        # self._update_data_items()

    # thread safe.
    def __build_data_items(self):
        """
            Build the data items from the master data items list.

            This method is thread safe.
        """
        master_data_items = copy.copy(self._get_master_data_items())
        assert len(set(master_data_items)) == len(master_data_items)
        # sort the master data list. this is optional since it may be sorted downstream.
        if self.sort_key is not None:
            master_data_items.sort(key=self.sort_key, reverse=self.sort_reverse)
        # construct the data items list by expanding each master data item to
        # include its children
        data_items = list()
        data_item_filter = self.filter
        for data_item in master_data_items:
            # apply filter
            if data_item_filter(data_item):
                # add data item and its dependent data items
                data_items.append(data_item)
        return data_items

    # thread safe.
    def _update_data_items(self):
        """
            Build the data items from the master list and generate
            a sequence of change messages.
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
    """

    def __init__(self, data_items_binding):
        super(DataItemsFilterBinding, self).__init__()
        self.__master_data_items = list()
        self.__data_items_binding = data_items_binding
        self.__data_items_binding.inserters[id(self)] = self.__data_item_inserted
        self.__data_items_binding.removers[id(self)] = self.__data_item_removed

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
        self._inserted_master_data_item(before_index, data_item)

    # thread safe.
    def __data_item_removed(self, data_item, index):
        """ Handle removal from the source list by updating this lists items. """
        with self._update_mutex:
            assert data_item in self.__master_data_items
            del self.__master_data_items[index]
        self._removed_master_data_item(index, data_item)

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
        self.__container = None
        self.__master_data_items = list()

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
            self.__container.remove_ref()
        self.__master_data_items = list()
        self.__container = container
        if self.__container:
            self.__container.add_ref()
            self.__container.add_listener(self)
            self.__master_data_items.extend(self.__container.data_items)
        self._update_data_items()
    container = property(__get_container, __set_container)

    # thread safe.
    def data_item_inserted(self, container, data_item, before_index, is_moving):
        """ Insert the data item. Called from the container. """
        with self._update_mutex:
            self.__master_data_items.insert(before_index, data_item)
        self._inserted_master_data_item(before_index, data_item)

    # thread safe.
    def data_item_removed(self, container, data_item, index, is_moving):
        """ Remove the data item. Called from the container. """
        with self._update_mutex:
            del self.__master_data_items[index]
        self._removed_master_data_item(index, data_item)

    # thread safe
    def _get_master_data_items(self):
        return self.__master_data_items
