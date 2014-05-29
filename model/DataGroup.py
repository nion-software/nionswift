# standard libraries
import collections
import copy
import gettext

# third party libraries
# None

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import Storage


_ = gettext.gettext


"""

    Group layout.
    Live. Live acquisition items.
    Library. Static items.

    *   The user can edit/delete the Library group, and create additional top level groups.
    However, at least one group in addition to the Live group must always be present.
    *   The user cannot delete the live group.
    *   The user cannot add/delete items from the Live group.
    *   Groups can be re-ordered, but the Live group is always first.
    *   New items are put in the first group after Live.

    *   NOTES
    Groups can contain child groups and data items.

    One design option is to have the document controller hold a single data group.
    This has the advantage of making access very uniform. However, this also makes
    it very easy for the user to "lose" items at the top level, which they might not
    see unless they selected the topmost group.

    Another design option is to have the document controller hold a list of data
    groups. This is more complex structure, but makes it easier for the user to
    understand the structure.

    Smart Groups

    Smart groups work on sibling data groups (aka the data items in the smart group's
    container). A smart group at the top level of groups will be able to filter
    and sort data items contained in other top level groups.
    Is there a need for smart groups anywhere except at the top level?

    - (A1a: 1, A1b: 1, A1b1: 2, A1b1a: 2, A1b2: 1, B1: 1, B1a: 1) [0]
    Smart Group [-]
    Group A (A1a: 1, A1b: 1, A1b1: 1, A1b1a: 1, A1b2: 1) [-]
    Group A1 (A1a: 1, A1b: 1, A1b1: 1, A1b1a: 1, A1b2: 1) [A]
    Data Item A1a () [A1]
    Data Item A1b (A1b1: 1, A1b1a: 1, A1b2: 1) [A1]
    Data Item A1b1 (A1b1a: 1 [A1b]
    Data Item A1b1a () [A1b1]
    Data Item A1b2 () [A1b]
    Group B (B1: 1, B1a: 1, A1b1: 1, A1b1a: 1) [-]
    Data Item B1 (B1a: 1) [B]
    Data Item B1a [B1]
    Data Item A1b1 (A1b1a: 1) [B, A1b]
    Data Item A1b1a [A1b1]

    Data item A1b1b gets added to A1b1. A1b1 counted_data_items gets updated, then tells its containers B, A1b
    that they have been updated. B, A1b counted_data_items get updated, then tell their containers, etc.
    When each group gets the counted_data_items_updated message, it tells any smart container children
    that they need to re-filter.

    Data item A2 gets added to Group A.

    """


class DataGroup(Storage.StorageBase):
    def __init__(self):
        super(DataGroup, self).__init__()
        self.storage_properties += ["title", "data_item_uuids"]
        self.storage_relationships += ["data_groups"]
        self.storage_type = "data-group"
        self.__title = None
        self.__data_item_uuids = list()
        self.__get_data_item_by_uuid = None
        self.data_groups = Storage.MutableRelationship(self, "data_groups")
        self.__data_items = list()
        self.__counted_data_items = collections.Counter()
        self.__moving = False  # ugh

    def __str__(self):
        return self.title if self.title else _("Untitled")

    @classmethod
    def build(cls, datastore, item_node, uuid_):
        title = datastore.get_property(item_node, "title")
        data_item_uuids = datastore.get_property(item_node, "data_item_uuids")
        data_groups = datastore.get_items(item_node, "data_groups")
        data_group = cls()
        data_group.title = title
        data_group.data_groups.extend(data_groups)
        data_group.__data_item_uuids = data_item_uuids
        return data_group

    # This gets called when reference count goes to 0, but before deletion.
    def about_to_delete(self):
        for data_group in copy.copy(self.data_groups):
            self.data_groups.remove(data_group)
        super(DataGroup, self).about_to_delete()

    def __deepcopy__(self, memo):
        data_group_copy = DataGroup()
        data_group_copy.title = self.title
        data_group_copy.__data_item_uuids = self.__data_item_uuids
        # data groups get deep copied
        for data_group in self.data_groups:
            data_group_copy.append_data_group(copy.deepcopy(data_group, memo))
        memo[id(self)] = data_group_copy
        return data_group_copy

    def connect_data_items(self, lookup_data_item):
        for data_group in self.data_groups:
            data_group.connect_data_items(lookup_data_item)
        for data_item_uuid in self.__data_item_uuids:
            data_item = lookup_data_item(data_item_uuid)
            if data_item is None:
                import logging
                logging.debug("data_item not found %s", data_item_uuid)
            assert data_item is not None
            self.__data_items.append(data_item)
        self.__get_data_item_by_uuid = lookup_data_item

    def disconnect_data_items(self):
        for data_group in self.data_groups:
            data_group.disconnect_data_items()
        self.__get_data_item_by_uuid = None

    def append_data_item(self, data_item):
        self.insert_data_item(len(self.__data_items), data_item)

    def insert_data_item(self, before_index, data_item):
        assert data_item not in self.__data_items
        self.__data_items.insert(before_index, data_item)
        self.notify_listeners("data_item_inserted", self, data_item, before_index, self.__moving)
        self.update_counted_data_items(collections.Counter([data_item]))
        self.__data_item_uuids.insert(before_index, data_item.uuid)
        self.notify_set_property("data_item_uuids", self.__data_item_uuids)

    def remove_data_item(self, data_item):
        index = self.__data_items.index(data_item)
        self.__data_items.remove(data_item)
        self.subtract_counted_data_items(collections.Counter([data_item]))
        self.notify_listeners("data_item_removed", self, data_item, index, self.__moving)
        self.__data_item_uuids.remove(data_item.uuid)
        self.notify_set_property("data_item_uuids", self.__data_item_uuids)

    def __get_data_items(self):
        return tuple(self.__data_items)
    data_items = property(__get_data_items)

    def append_data_group(self, data_group):
        self.insert_data_group(len(self.data_groups), data_group)

    def insert_data_group(self, before_index, data_group):
        self.data_groups.insert(before_index, data_group)
        if self.__get_data_item_by_uuid:
            data_group.connect_data_items(self.__get_data_item_by_uuid)

    def remove_data_group(self, data_group):
        data_group.disconnect_data_items()
        self.data_groups.remove(data_group)

    # override from StorageBase.
    # watch for insertions to data_items and data_groups so that smart filters get updated.
    def notify_insert_item(self, key, value, before_index):
        super(DataGroup, self).notify_insert_item(key, value, before_index)
        if key == "data_groups":
            self.update_counted_data_items(value.counted_data_items)

    # override from StorageBase
    # watch for removals from data_items and data_groups so that smart filters get updated.
    def notify_remove_item(self, key, value, index):
        super(DataGroup, self).notify_remove_item(key, value, index)
        if key == "data_groups":
            self.subtract_counted_data_items(value.counted_data_items)

    # title
    def __get_title(self):
        return self.__title
    def __set_title(self, value):
        self.__title = value
        self.notify_set_property("title", value)
    title = property(__get_title, __set_title)

    # data_item_uuids
    def __get_data_item_uuids(self):
        return tuple(self.__data_item_uuids)
    data_item_uuids = property(__get_data_item_uuids)

    def __get_counted_data_items(self):
        return self.__counted_data_items
    counted_data_items = property(__get_counted_data_items)

    def update_counted_data_items(self, counted_data_items):
        self.__counted_data_items.update(counted_data_items)
        self.notify_parents("update_counted_data_items", counted_data_items)
        self.notify_listeners("update_counted_data_items", counted_data_items)
    def subtract_counted_data_items(self, counted_data_items):
        self.__counted_data_items.subtract(counted_data_items)
        self.__counted_data_items += collections.Counter()  # strip empty items
        self.notify_parents("subtract_counted_data_items", counted_data_items)
        self.notify_listeners("subtract_counted_data_items", counted_data_items)

    def move_data_item(self, data_item, before_index):
        index = self.data_items.index(data_item)
        if index != before_index:
            data_item.add_ref()
            self.__moving = True
            self.remove_data_item(data_item)
            if index < before_index:
                before_index -= 1
            self.insert_data_item(before_index, data_item)
            self.__moving = False
            data_item.remove_ref()


# return a generator for all data groups and child data groups in container
def get_flat_data_group_generator_in_container(container):
    for data_group in container.data_groups:
        yield data_group
        for child_data_group in get_flat_data_group_generator_in_container(data_group):
            yield child_data_group


# return a generator for all data items, child data items, and data items in child groups in container
def get_flat_data_item_generator_in_container(container):
    if hasattr(container, "data_items"):
        for data_item in container.data_items:
            yield data_item
    if hasattr(container, "data_groups"):
        for data_group in container.data_groups:
            for data_item in get_flat_data_item_generator_in_container(data_group):
                yield data_item


# Return the data_group matching name that is the descendent of the container.
def get_data_group_in_container_by_title(container, data_group_title):
    for data_group in container.data_groups:
        if data_group.title == data_group_title:
            return data_group
    return None


# Return the data_item matching name that is the descendent of the container.
def get_data_item_in_container_by_title(container, data_item_title):
    for data_item in container.data_items:
        if data_item.title == data_item_title:
            return data_item
    return None


# Return the data_group matching name that is the descendent of the container.
def get_data_group_in_container_by_uuid(container, data_group_uuid):
    for data_group in container.data_groups:
        if data_group.uuid == data_group_uuid:
            return data_group
    return None


# Return the data_item matching name that is the descendent of the container.
def get_data_item_in_container_by_uuid(container, data_item_uuid):
    for data_item in container.data_items:
        if data_item.uuid == data_item_uuid:
            return data_item
    return None


# determine the container for the data item. this may be the document model,
# a data group, or a data item.
def get_data_item_container(container, query_data_item):
    if hasattr(container, "data_items") and query_data_item in container.data_items:
        return container
    if hasattr(container, "data_groups"):
        for data_group in container.data_groups:
            check_container = get_data_item_container(data_group, query_data_item)
            if check_container:
                return check_container
    if hasattr(container, "data_items"):
        for data_item in container.data_items:
            check_container = get_data_item_container(data_item, query_data_item)
            if check_container:
                return check_container
    return None
