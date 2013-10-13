# standard libraries
import collections
import copy
import gettext

# third party libraries
# None

# local libraries
from nion.swift import DataItem
from nion.swift import Storage

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
    *   The user can create smart groups, which apply to sibling and their descendents.

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
        self.storage_properties += ["title"]
        self.storage_relationships += ["data_groups", "data_items"]
        self.storage_type = "data-group"
        self.__title = None
        self.data_groups = Storage.MutableRelationship(self, "data_groups")
        self.data_items = Storage.MutableRelationship(self, "data_items")
        self.__counted_data_items = collections.Counter()

    def __str__(self):
        return self.title if self.title else _("Untitled")

    @classmethod
    def build(cls, storage_reader, item_node):
        title = storage_reader.get_property(item_node, "title")
        data_groups = storage_reader.get_items(item_node, "data_groups")
        data_items = storage_reader.get_items(item_node, "data_items")
        data_group = cls()
        data_group.title = title
        data_group.data_groups.extend(data_groups)
        data_group.data_items.extend(data_items)
        return data_group

    # This gets called when reference count goes to 0, but before deletion.
    def about_to_delete(self):
        for data_group in copy.copy(self.data_groups):
            self.data_groups.remove(data_group)
        for data_item in copy.copy(self.data_items):
            self.data_items.remove(data_item)
        super(DataGroup, self).about_to_delete()

    # smart groups don't participate in the storage model directly. so allow
    # listeners an alternative way of hearing about data items being inserted
    # or removed via data_item_inserted and data_item_removed messages.

    # NOTE: this code is duplicated in DataItem

    # override from StorageBase.
    # watch for insertions to data_items and data_groups so that smart filters get updated.
    def notify_insert_item(self, key, value, before_index):
        super(DataGroup, self).notify_insert_item(key, value, before_index)
        if key == "data_items":
            self.notify_listeners("data_item_inserted", self, value, before_index)
            self.update_counted_data_items(value.counted_data_items + collections.Counter([value]))
        if key == "data_groups":
            self.update_counted_data_items(value.counted_data_items)
    # override from StorageBase
    # watch for removals from data_items and data_groups so that smart filters get updated.
    def notify_remove_item(self, key, value, index):
        super(DataGroup, self).notify_remove_item(key, value, index)
        if key == "data_items":
            self.subtract_counted_data_items(value.counted_data_items + collections.Counter([value]))
            self.notify_listeners("data_item_removed", self, value, index)
        if key == "data_groups":
            self.subtract_counted_data_items(value.counted_data_items)
    # override from StorageBase.
    # watch for property changes to data items so that smart filters get updated.
    def property_changed(self, sender, property, value):
        if isinstance(sender, DataItem.DataItem):
            self.data_item_property_changed(sender, property, value)

    # title
    def __get_title(self):
        return self.__title
    def __set_title(self, value):
        self.__title = value
        self.notify_set_property("title", value)
    title = property(__get_title, __set_title)

    def __get_counted_data_items(self):
        return self.__counted_data_items
    counted_data_items = property(__get_counted_data_items)

    def update_counted_data_items(self, counted_data_items):
        self.__counted_data_items.update(counted_data_items)
        self.notify_parents("update_counted_data_items", counted_data_items)
        for data_group in self.data_groups:
            if hasattr(data_group, "update_counted_data_items_for_filter"):
                data_group.update_counted_data_items_for_filter(counted_data_items)
    def subtract_counted_data_items(self, counted_data_items):
        self.__counted_data_items.subtract(counted_data_items)
        self.__counted_data_items += collections.Counter()  # strip empty items
        self.notify_parents("subtract_counted_data_items", counted_data_items)
        for data_group in self.data_groups:
            if hasattr(data_group, "subtract_counted_data_items_for_filter"):
                data_group.subtract_counted_data_items_for_filter(counted_data_items)

    # watch for property changes to data items so that smart filters get updated.
    # tell any data groups to update their filter.
    def data_item_property_changed(self, data_item, property, value):
        self.notify_parents("data_item_property_changed", data_item, property, value)
        for data_group in self.data_groups:
            if hasattr(data_group, "adjust_data_item_for_filter"):
                data_group.adjust_data_item_for_filter(data_item, property, value)

    def copy(self):
        data_group_copy = DataGroup()
        data_group_copy.title = self.title
        for data_group in self.data_groups:
            data_group_copy.data_groups.append(data_group.copy())
        for data_item in self.data_items:
            data_group_copy.data_items.append(data_item.copy())
        return data_group_copy


class SmartDataGroup(Storage.StorageBase):
    def __init__(self):
        super(SmartDataGroup, self).__init__()
        self.storage_properties += ["title"]
        self.storage_type = "smart-data-group"
        self.__title = None
        self.__counted_data_items = collections.Counter()
        self.__data_items = []

    def __str__(self):
        return "* " + (self.title if self.title else _("Untitled"))

    @classmethod
    def build(cls, storage_reader, item_node):
        title = storage_reader.get_property(item_node, "title")
        data_group = cls()
        data_group.title = title
        return data_group

    # This gets called when reference count goes to 0, but before deletion.
    def about_to_delete(self):
        super(SmartDataGroup, self).about_to_delete()

    # title
    def __get_title(self):
        return self.__title
    def __set_title(self, value):
        self.__title = value
        self.notify_set_property("title", value)
    title = property(__get_title, __set_title)

    def __get_data_groups(self):
        return []
    data_groups = property(__get_data_groups)

    def __get_data_items(self):
        return self.__data_items
    data_items = property(__get_data_items)

    def __get_counted_data_items(self):
        return collections.Counter()
    counted_data_items = property(__get_counted_data_items)

    def __includes(self, data_item):
        return data_item.title and "Green" in data_item.title
    def __position(self, data_item):
        for index, i_data_item in enumerate(self.__data_items):
            if data_item.title.lower() > i_data_item.title.lower():
                return index
        return len(self.__data_items)

    def __insert_data_item(self, data_item):
        if not data_item in self.__data_items and self.__includes(data_item):
            before_index = self.__position(data_item)
            self.__data_items.insert(before_index, data_item)
            self.notify_listeners("data_item_inserted", self, data_item, before_index)

    def __remove_data_item(self, data_item):
        if data_item in self.__data_items:
            index = self.__data_items.index(data_item)
            del self.__data_items[index]
            self.notify_listeners("data_item_removed", self, data_item, index)

    # TODO: how will filters based on data get updated?
    # TODO: how will filters based on time stamp get updated?
    # TODO: how will filters based on meta data get updated?
    def update_counted_data_items_for_filter(self, counted_data_items):
        for data_item in counted_data_items.keys():
            assert data_item is not None
            self.__insert_data_item(data_item)
        self.__counted_data_items.update(counted_data_items)
    def subtract_counted_data_items_for_filter(self, counted_data_items):
        self.__counted_data_items.subtract(counted_data_items)
        for data_item in self.__counted_data_items.keys():
            if self.__counted_data_items[data_item] == 0:
                self.__remove_data_item(data_item)
        self.__counted_data_items += collections.Counter()  # strip empty items

    # watch for property changes to data items so that smart filters get updated.
    # insert or remove if the inclusion changes.
    def adjust_data_item_for_filter(self, data_item, property, value):
        if self.__includes(data_item):
            if data_item not in self.__data_items:
                self.__insert_data_item(data_item)
        else:
            if data_item in self.__data_items:
                self.__remove_data_item(data_item)

    def copy(self):
        data_group = SmartDataGroup()
        data_group.title = self.title
        return data_group


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
            for child_data_item in get_flat_data_item_generator_in_container(data_item):
                yield child_data_item
    if hasattr(container, "data_groups"):
        for data_group in container.data_groups:
            for data_item in get_flat_data_item_generator_in_container(data_group):
                yield data_item

# Return the data_group matching name that is the descendent of the container.
# Use the document_controller as the container if container is None.
def get_data_group_in_container_by_title(container, data_group_title):
    for data_group in container.data_groups:
        if data_group.title == data_group_title:
            return data_group
    return None

# Return the data_item matching name that is the descendent of the container.
# Use the document_controller as the container if container is None.
def get_data_item_in_container_by_title(container, data_item_title):
    for data_item in container.data_items:
        if data_item.title == data_item_title:
            return data_item
    return None

# Return the data_group matching name that is the descendent of the container.
# Use the document_controller as the container if container is None.
def get_data_group_in_container_by_uuid(container, data_group_uuid):
    for data_group in container.data_groups:
        if data_group.uuid == data_group_uuid:
            return data_group
    return None

# Return the data_item matching name that is the descendent of the container.
# Use the document_controller as the container if container is None.
def get_data_item_in_container_by_uuid(container, data_item_uuid):
    for data_item in container.data_items:
        if data_item.uuid == data_item_uuid:
            return data_item
    return None
