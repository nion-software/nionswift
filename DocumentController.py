# standard libraries
import collections
import copy
import gettext
import logging
import numbers
import os
import Queue
import random
import threading
import uuid
import weakref

# third party libraries
import scipy

# local libraries
from Decorators import queue_main_thread
from Decorators import relative_file
from Decorators import singleton
import DataItem
import DataPanel
import Graphics
import Image
import ImagePanel
import Menu
import Operation
import Panel
import Storage
import UserInterface
import Workspace

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
    parent). A smart group at the top level of groups will be able to filter
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

    Data item A1b1b gets added to A1b1. A1b1 counted_data_items gets updated, then tells its parents B, A1b
        that they have been updated. B, A1b counted_data_items get updated, then tell their parents, etc.
        When each group gets the counted_data_items_updated message, it tells any smart parent children
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

    # call this when the listeners need to be updated
    # (via data_item_changed). Calling this method will send the data_item_changed
    # method to each listener.
    def notify_data_item_changed(self, info):
        self.notify_listeners("data_item_changed", self, info)

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


def get_groups_in_group(grp, walk=False):
    """
    Returns a generator over the list of groups in the
    data_group, or documentcontroller, grp.
    If walk is True, also includes all subgroups.
    """
    for g in grp.data_groups:
        yield g
        if walk:
            for sub_g in get_groups_in_group(g, walk=True):
                yield sub_g


def get_dataitems_in_group(grp, walk=False):
    """
    Returns all the dataitems in the group grp.
    If walk is true, walks through any child groups
    and child items with sub_items
    """
    for di in grp.data_items:
        yield di
    if walk:
        for g in grp.data_groups:
            for di in get_dataitems_in_group(g, walk=True):
                yield di
        for parent_dataitem in grp.data_items:
            for di in get_subitems_in_item(parent_dataitem):
                yield di


def get_subitems_in_item(dit):
    """
    Returns all the subitems for the dataitems dit. includes
    any subitems of those items too
    """
    for di in dit.data_items:
        yield di
        for sub_di in get_subitems_in_item(di):
            yield sub_di


class DocumentController(Storage.StorageBase):

    # document_window is passed from the application container.
    # the next method to be called will be initialize.
    def __init__(self, application, document_window, storage_writer, storage_reader=None, _create_workspace=True):
        super(DocumentController, self).__init__()
        self.__weak_application = weakref.ref(application)
        self.ui = application.ui
        self.document_window = document_window
        self.menu_manager = Menu.MenuManager(self.ui)  # used only on Windows
        self.workspace = None
        self.__weak_image_panels = []
        self.__weak_selected_image_panel = None
        self.__cursor_weak_listeners = []
        self.__counted_data_items = collections.Counter()
        self.delay_queue = Queue.Queue()
        self.storage_writer = storage_writer
        self.storage_relationships += ["data_groups"]
        self.storage_type = "document"
        self.data_groups = Storage.MutableRelationship(self, "data_groups")
        self.application.register_document_window(self)
        if storage_reader:
            storage_writer.disconnected = True
            need_rewrite = self.read(storage_reader)
            storage_writer.disconnected = False
            # the structure of the document might have changed; rewrite
            # TODO: formalized db migration
            if need_rewrite:
                logging.debug("Rewriting database")
                self.rewrite()
        else:
            storage_writer.set_root(self)
            self.write()
        if _create_workspace:  # used only when testing reference counting
            self.workspace = Workspace.Workspace(self)
            self.selected_image_panel = None  # this has the effect of setting default image panel

    def __get_application(self):
        return self.__weak_application()
    application = property(__get_application)
    app = property(__get_application)

    def close(self):
        self.storage_writer.disconnected = True
        for data_group in copy.copy(self.data_groups):
            self.data_groups.remove(data_group)
        self.application.unregister_document_window(self)

    def reset(self, storage_writer):
        for data_group in copy.copy(self.data_groups):
            self.data_groups.remove(data_group)
        assert len(self.data_groups) == 0
        self.workspace.reset()
        self.storage_writer = storage_writer
        self.storage_writer.set_root(self)
        self.write()

    def read(self, storage_reader):
        need_rewrite = False
        parent_node, uuid = storage_reader.find_root_node("document")
        self._set_uuid(uuid)
        data_groups = storage_reader.get_items(parent_node, "data_groups")
        self.data_groups.extend(data_groups)
        if len(self.data_groups) == 0:
            data_group = DataGroup()
            data_group.title = _("Data")
            self.data_groups.append(data_group)
            need_rewrite = True
        if storage_reader.has_relationship(parent_node, "data_items"):
            data_items = storage_reader.get_items(parent_node, "data_items")
            self.default_data_group.data_items.extend(data_items)
            need_rewrite = True
        return need_rewrite

    def create_default_data_groups(self):
        # ensure there is at least one group
        if len(self.data_groups) < 1:
            data_group = DataGroup()
            data_group.title = _("Library")
            self.data_groups.append(data_group)

    def create_test_images(self):
        # for testing, add a checkerboard image data item
        checkerboard_image_source = DataItem.DataItem()
        checkerboard_image_source.title = "Checkerboard"
        checkerboard_image_source.master_data = Image.createCheckerboard((512, 512))
        self.default_data_group.data_items.append(checkerboard_image_source)
        # for testing, add a color image data item
        color_image_source = DataItem.DataItem()
        color_image_source.title = "Green Color"
        color_image_source.master_data = Image.createColor((512, 512), 128, 255, 128)
        self.default_data_group.data_items.append(color_image_source)
        # for testing, add a color image data item
        lena_image_source = DataItem.DataItem()
        lena_image_source.title = "Lena"
        lena_image_source.master_data = scipy.misc.lena()
        self.default_data_group.data_items.append(lena_image_source)

    def periodic(self):
        # perform any pending operations
        while not self.delay_queue.empty():
            try:
                task = self.delay_queue.get(False)
            except Queue.Empty:
                pass
            else:
                task()
                self.delay_queue.task_done()

    def __get_default_data_group(self):
        return self.data_groups[0]
    default_data_group = property(__get_default_data_group)

    # override from StorageBase.
    def notify_insert_item(self, key, value, before_index):
        super(DocumentController, self).notify_insert_item(key, value, before_index)
        if key == "data_groups":
            data_group = value
            self.update_counted_data_items(data_group.counted_data_items)
            # initialize data group with current set of data (used for smart data groups)
            if hasattr(data_group, "update_counted_data_items_for_filter"):
                data_group.update_counted_data_items_for_filter(self.counted_data_items)
    # override from StorageBase
    def notify_remove_item(self, key, value, index):
        super(DocumentController, self).notify_remove_item(key, value, index)
        if key == "data_groups":
            self.subtract_counted_data_items(value.counted_data_items)

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

    # TODO: what about thread safety for these classes?

    class _DataAccessorIter(object):
        def __init__(self, iter):
            self.iter = iter
        def __iter__(self):
            return self
        def next(self):
            data_item = self.iter.next()
            return data_item.image if data_item else None

    class DataAccessor(object):
        def __init__(self, document_controller):
            self.__document_controller_weakref = weakref.ref(document_controller)
        def __get_document_controller(self):
            return self.__document_controller_weakref()
        document_controller = property(__get_document_controller)
        # access by bracket notation
        def __len__(self):
            return self.document_controller.get_data_item_count()
        def __getitem__(self, key):
            data = self.document_controller.get_data_by_key(key)
            if data is None:
                raise KeyError
            return data
        def __setitem__(self, key, value):
            return self.document_controller.set_data_by_key(key, value)
        def __delitem__(self, key):
            data_item = self.document_controller.get_data_item_by_key(key)
            if data_item:
                self.document_controller.all_data_items.remove(data_item)
        def __iter__(self):
            return DocumentController._DataAccessorIter(self.document_controller.get_data_items())
        def uuid_keys(self):
            return [data_item.uuid for data_item in self.document_controller.data_items_by_key]
        def title_keys(self):
            return [str(data_item) for data_item in self.document_controller.data_items_by_key]
        def keys(self):
            return self.uuid_keys()

    # TODO: get rid of this
    @queue_main_thread
    def add_data_item_on_main_thread(self, data_item):
        self.default_data_group.data_items.append(data_item)

    # TODO: get rid of this
    @queue_main_thread
    def remove_data_item_on_main_thread(self, data_item):
        self.default_data_group.data_items.remove(data_item)

    def get_data_items(self):
        """
        returns an iterator over all current data items
        """
        for g in self.data_groups:
            for di in get_dataitems_in_group(g, walk=True):
                yield di

    def get_data_item_count(self):
        return len(list(self.get_data_items()))

    def get_data_groups(self):
        return get_groups_in_group(self, walk=True)

    def get_data_group_by_uuid(self, uuid):
        for data_group in self.get_data_groups():
            if data_group.uuid == uuid:
                return data_group
        return None

    # access data item by key (title, uuid, index)
    def get_data_item_by_key(self, key):
        if isinstance(key, numbers.Integral):
            return self.get_data_items()[key]
        if isinstance(key, uuid.UUID):
            return self.get_data_item_by_uuid(key)
        return self.get_data_item_by_title(str(key))
    def get_data_by_key(self, key):
        data_item = self.get_data_item_by_key(key)
        return data_item.image if data_item else None
    def set_data_by_key(self, key, data):
        data_item = self.get_data_item_by_key(key)
        if data_item:
            data_item.master_data = data
        else:
            if isinstance(key, numbers.Integral):
                raise IndexError
            if isinstance(key, uuid.UUID):
                raise KeyError
            data_item = DataItem.DataItem()
            data_item.title = str(key)
            data_item.master_data = data
            self.default_data_group.data_items.append(data_item)
        return data_item

    # access data items by title
    def get_data_item_by_title(self, title):
        for data_item in self.get_data_items():
            if str(data_item) == title:
                return data_item
        return None
    def get_data_by_title(self, title):
        data_item = self.get_data_item_by_title(title)
        return data_item.image if data_item else None
    def set_data_by_title(self, title, data):
        data_item = self.get_data_item_by_title(title)
        if data_item:
            data_item.data = data
        else:
            data_item = DataItem.DataItem()
            data_item.title = title
            data_item.master_data = data
            self.default_data_group.data_items.append(data_item)
        return data_item

    # access data items by index
    def get_data_item_by_index(self, index):
        return self.get_data_items()[index]
    def get_data_by_index(self, index):
        data_item = self.get_data_item_by_index(index)
        return data_item.image if data_item else None
    def set_data_by_index(self, index, data):
        data_item = self.get_data_item_by_index(index)
        if data_item:
            data_item.master_data = data
        else:
            raise IndexError
    def get_index_for_data_item(self, data_item):
        return self.get_data_items().index(data_item)

    # access data items by uuid
    def get_data_item_by_uuid(self, uuid):
        for data_item in self.get_data_items():
            if data_item.uuid == uuid:
                return data_item
        return None
    def get_data_by_uuid(self, uuid):
        data_item = self.get_data_item_by_uuid(uuid)
        return data_item.image if data_item else None
    def set_data_by_uuid(self, uuid, data):
        data_item = self.get_data_item_by_uuid(uuid)
        if data_item:
            data_item.master_data = data
        else:
            raise KeyError

    def register_image_panel(self, image_panel):
        weak_image_panel = weakref.ref(image_panel)
        self.__weak_image_panels.append(weak_image_panel)

    def unregister_image_panel(self, image_panel):
        if self.selected_image_panel == image_panel:
            self.selected_image_panel = None
        weak_image_panel = weakref.ref(image_panel)
        self.__weak_image_panels.remove(weak_image_panel)

    def find_panel(self, panel_id):
        panel = self.workspace.find_panel(panel_id)
        assert panel is not None
        return panel

    def __get_selected_image_panel(self):
        return self.__weak_selected_image_panel() if self.__weak_selected_image_panel else None
    def __set_selected_image_panel(self, selected_image_panel):
        if not selected_image_panel:
            selected_image_panel = self.find_panel("primary-image").content
        weak_selected_image_panel = weakref.ref(selected_image_panel) if selected_image_panel else None
        if weak_selected_image_panel != self.__weak_selected_image_panel:

            # first un-listen to the old selected panel, if any
            old_selected_image_panel = self.__weak_selected_image_panel() if self.__weak_selected_image_panel else None
            if old_selected_image_panel:
                old_selected_image_panel.remove_listener(self)

            # save the selected panel
            self.__weak_selected_image_panel = weak_selected_image_panel

            # now listen to the new selected panel, if any.
            # this will result in calls to image_panel_data_item_changed.
            if selected_image_panel:
                selected_image_panel.add_listener(self)

            # iterate through the image panels and update their 'focused' property
            for image_panel in [weak_image_panel() for weak_image_panel in self.__weak_image_panels]:
                image_panel.set_focused(image_panel == self.selected_image_panel)

            # notify listeners that the selected image panel has changed.
            self.notify_listeners("selected_image_panel_changed", selected_image_panel)

            # notify listeners that the data item has changed. some listeners will be just interested
            # in the data item itself, not the group/data item combo.
            selected_data_item = selected_image_panel.data_item if selected_image_panel else None
            self.notify_listeners("selected_data_item_changed", selected_data_item, {"property": "panel"})
    selected_image_panel = property(__get_selected_image_panel, __set_selected_image_panel)

    def __get_selected_data_item(self):
        selected_image_panel = self.selected_image_panel
        return selected_image_panel.data_item if selected_image_panel else None
    selected_data_item = property(__get_selected_data_item)

    def data_panel_selection_changed_from_image_panel(self, data_panel_selection):
        self.notify_listeners("data_panel_selection_changed_from_image_panel", data_panel_selection)

    # this message comes from the selected image panel. the connection is established
    # in __set_selected_image_panel via a call to ImagePanel.addListener.
    def image_panel_data_item_changed(self, image_panel, info):
        data_item = image_panel.data_item if image_panel else None
        self.notify_listeners("selected_data_item_changed", data_item, info)

    def addToolbarButton(self, id, title, callback):
        self.find_panel("button-list-panel").addButton(id, title, callback)
    def removeToolbarButton(self, id):
        self.find_panel("button-list-panel").removeButton(id)

    def layoutAdd(self):
        selected_image_panel = self.selected_image_panel
        if selected_image_panel:
            tab_group = self.selected_image_panel.container_chain[0]
            image_row = self.find_panel("image-row")
            desc = {
                "type": "tab",
                "id": "",
                "content": "image-panel",
                "title": _("Image"),
            }
            element = self.workspace.createElement(desc, self)
            image_row.insertChildAfter(element, tab_group)

    def layoutRemove(self):
        selected_image_panel = self.selected_image_panel
        if selected_image_panel:
            tab_group = self.selected_image_panel.container_chain[1]
            image_row = self.find_panel("image-row")
            image_row.removeChild(tab_group)
            self.selected_image_panel = None

    def add_smart_group(self):
        smart_data_group = SmartDataGroup()
        smart_data_group.title = _("Untitled Smart Group")
        self.data_groups.insert(0, smart_data_group)

    def add_group(self):
        data_group = DataGroup()
        data_group.title = _("Untitled Group")
        self.data_groups.insert(0, data_group)

    def add_green_data_item(self):
        color_image_source = DataItem.DataItem()
        color_image_source.title = "Green " + str(random.randint(1,1000000))
        color_image_source.master_data = Image.createColor((512, 512), 128, 255, 128)
        self.default_data_group.data_items.append(color_image_source)

    def add_line_graphic(self):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            graphic = Graphics.LineGraphic()
            graphic.start = (0.2,0.2)
            graphic.end = (0.8,0.8)
            data_item.graphics.append(graphic)
            self.selected_image_panel.graphic_selection.set(data_item.graphics.index(graphic))

    def add_rectangle_graphic(self):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            data_item.graphics.append(graphic)
            self.selected_image_panel.graphic_selection.set(data_item.graphics.index(graphic))

    def add_ellipse_graphic(self):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            graphic = Graphics.EllipseGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            data_item.graphics.append(graphic)
            self.selected_image_panel.graphic_selection.set(data_item.graphics.index(graphic))

    def remove_graphic(self):
        data_item = self.selected_data_item
        if data_item and self.selected_image_panel.graphic_selection.has_selection():
            graphics = [data_item.graphics[index] for index in self.selected_image_panel.graphic_selection.indexes]
            for graphic in graphics:
                data_item.graphics.remove(graphic)

    def remove_operation(self, operation):
        data_item = self.selected_data_item
        if data_item:
            data_item.operations.remove(operation)

    def add_processing_operation(self, operation, prefix=None, suffix=None, in_place=False):
        data_panel_selection = self.selected_image_panel.data_panel_selection if self.selected_image_panel else None
        data_item = data_panel_selection.data_item if data_panel_selection else None
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            if in_place:  # in place?
                data_item.operations.append(operation)
            else:
                new_data_item = DataItem.DataItem()
                new_data_item.title = (prefix if prefix else "") + str(data_item) + (suffix if suffix else "")
                new_data_item.operations.append(operation)
                data_item.data_items.append(new_data_item)
                self.selected_image_panel.data_panel_selection = DataPanel.DataPanelSelection(data_panel_selection.data_group, new_data_item)

    def processing_fft(self):
        self.add_processing_operation(Operation.FFTOperation(), prefix=_("FFT of "))

    def processing_ifft(self):
        self.add_processing_operation(Operation.IFFTOperation(), prefix=_("Inverse FFT of "))

    def processing_gaussian_blur(self):
        self.add_processing_operation(Operation.GaussianBlurOperation(), prefix=_("Gaussian Blur of "))

    def processing_resample(self):
        self.add_processing_operation(Operation.ResampleOperation(), prefix=_("Resample of "))

    def processing_crop(self):
        data_panel_selection = self.selected_image_panel.data_panel_selection if self.selected_image_panel else None
        data_item = data_panel_selection.data_item if data_panel_selection else None
        if data_item:
            operation = Operation.CropOperation()
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            data_item.graphics.append(graphic)
            operation.graphic = graphic
            self.add_processing_operation(operation, prefix=_("Crop of "))

    def processing_invert(self):
        self.add_processing_operation(Operation.InvertOperation(), suffix=_(" Inverted"))

    def processing_duplicate(self):
        data_item = self.selected_data_item
        if data_item:
            new_data_item = DataItem.DataItem()
            new_data_item.title = _("Clone of ") + str(data_item)
            data_item.data_items.append(new_data_item)

    def processing_snapshot(self):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            data_item_copy = data_item.copy()
            data_item_copy.title = _("Copy of ") + str(data_item_copy)
            self.default_data_group.data_items.append(data_item_copy)

    def add_custom_processing_operation(self, data_item, fn, title=None):
        class ZOperation(Operation.Operation):
            def __init__(self, fn):
                description = []
                Operation.Operation.__init__(self, title if title else _("Processing"), description)
                self.fn = fn
            def process_data_copy(self, data_array):
                return self.fn(data_array)
        self.add_processing_operation(ZOperation(fn))

    def test_storage_log(self):
        self.storage_writer.log()

    def test_storage_read(self):
        storage_reader = Storage.DictStorageReader()
        storage_reader.load_file("/Users/cmeyer/Developer/Nion/NionImaging/data.p")
        self.reset(Storage.DictStorageWriter())
        self.read(storage_reader)

    def test_storage_write(self):
        self.storage_writer.save_file("/Users/cmeyer/Developer/Nion/NionImaging/data.p")

    def test_storage_reset(self):
        self.reset(Storage.DictStorageWriter())


# Connect a user interface to an observable object, based on the description of the object.
# Changes to the object's properties will result in changes to the UI.
# Changes to the UI will result in changes to the object's properties.


class ScalarController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.Widget_loadIntrinsicWidget("pyscalar")
        self.ui.PyControl_connect(self.widget, self.object, property)
        self.ui.PyControl_setTitle(self.widget, name)
        self.ui.PyControl_setFloatValue(self.widget, float(getattr(self.object, property)))
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        self.ui.PyControl_setFloatValue(self.widget, float(getattr(self.object, self.property)))


class IntegerFieldController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.Widget_loadIntrinsicWidget("pyintegerfield")
        self.ui.PyControl_connect(self.widget, self.object, property)
        self.ui.PyControl_setTitle(self.widget, name)
        self.ui.PyControl_setIntegerValue(self.widget, int(getattr(self.object, property)))
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        self.ui.PyControl_setIntegerValue(self.widget, int(getattr(self.object, self.property)))


class FloatFieldController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.Widget_loadIntrinsicWidget("pyfloatfield")
        self.ui.PyControl_connect(self.widget, self.object, property)
        self.ui.PyControl_setTitle(self.widget, name)
        self.ui.PyControl_setFloatValue(self.widget, float(getattr(self.object, property)))
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        self.ui.PyControl_setFloatValue(self.widget, float(getattr(self.object, self.property)))


class StringFieldController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.Widget_loadIntrinsicWidget("pystringfield")
        self.ui.PyControl_connect(self.widget, self.object, property)
        self.ui.PyControl_setTitle(self.widget, name)
        value = getattr(self.object, property)
        self.ui.PyControl_setStringValue(self.widget, str(value) if value else "")
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        self.ui.PyControl_setStringValue(self.widget, str(getattr(self.object, self.property)))


# fixed array means the user cannot add/remove items; but it still tracks additions/removals
# from its object.
class FixedArrayController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.Widget_loadIntrinsicWidget("column")
        self.__columns = []
        array = getattr(self.object, property)
        for item in array:
            column_widget = self.ui.Widget_loadIntrinsicWidget("column")
            controller = PropertyEditorController(self.ui, item, column_widget)
            self.__columns.append((controller, column_widget))
            self.ui.Widget_addWidget(self.widget, column_widget)
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        for column in self.__columns:
            column[0].close()
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        for controller, column_widget in self.__columns:
            controller.update()


# fixed array means the user cannot add/remove items; but it still tracks additions/removals
# from its object.
class ItemController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.Widget_loadIntrinsicWidget("column")
        self.columns = None
        item = getattr(self.object, property)
        self.controller = PropertyEditorController(self.ui, item, self.widget)
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.controller.close()
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        self.controller.update()


def construct_controller(ui, object, type, name, property, container_widget):
    controller = None
    if type == "scalar":
        controller = ScalarController(ui, object, name, property, container_widget)
    elif type == "integer-field":
        controller = IntegerFieldController(ui, object, name, property, container_widget)
    elif type == "float-field":
        controller = FloatFieldController(ui, object, name, property, container_widget)
    elif type == "string-field":
        controller = StringFieldController(ui, object, name, property, container_widget)
    elif type == "fixed-array":
        controller = FixedArrayController(ui, object, name, property, container_widget)
    elif type == "item":
        controller = ItemController(ui, object, name, property, container_widget)
    return controller

class PropertyEditorController(object):

    def __init__(self, ui, object, container_widget):
        self.ui = ui
        self.object = object
        self.__controllers = {}
        # add self as observer. this will result in property_changed messages.
        self.object.add_observer(self)
        for dict in object.description:
            name = dict["name"]
            type = dict["type"]
            property = dict["property"]
            controller = construct_controller(self.ui, self.object, type, name, property, container_widget)
            if controller:
                self.__controllers[property] = controller
            else:
                logging.debug("Unknown controller type %s", type)

    def close(self):
        # stop observing
        self.object.remove_observer(self)
        # delete widgets
        for controller in self.__controllers.values():
            controller.close()
        self.__controllers = {}

    def property_changed(self, sender, property, value):
        if property in self.__controllers:
            self.__controllers[property].update()

    def update(self):
        for controller in self.__controllers.values():
            controller.update()


class ProcessingPanel(Panel.Panel):

    """
        The processing panel watches for changes to the selected image panel,
        changes to the data item of the image panel, and changes to the
        data item itself.
    """

    def __init__(self, document_controller, panel_id):
        Panel.Panel.__init__(self, document_controller, panel_id, _("Processing"))

        # load the Qml and associate it with this panel.
        self.widget = self.loadIntrinsicWidget("pystack")
        self.__stack_groups = []

        # connect self as listener. this will result in calls to selected_data_item_changed
        self.document_controller.add_listener(self)

    def close(self):
        # first set the data item to None
        self.selected_data_item_changed(None, {"property": "source"})
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # finish closing
        Panel.Panel.close(self)

    # represents the UI for a specific data item (operation) in the image
    # source chain. for instance, an data item chain might have a structure
    # like display -> fft -> invert -> data. this class might represent the
    # controls for the invert step.
    class StackGroup(object):
        def __init__(self, panel, operation):
            self.__document_controller_weakref = weakref.ref(panel.document_controller)
            self.operation = operation
            # add self as observer. this will result in property_changed messages.
            # needed to handle 'enabled'
            self.operation.add_observer(self)
            self.stack_group_widget = panel.loadIntrinsicWidget("pystackgroup")
            self.ui.PyStackGroup_connect(self.stack_group_widget, self, "enabled", "add_pressed", "remove_pressed")
            self.ui.PyStackGroup_setTitle(self.stack_group_widget, operation.name)
            self.ui.PyStackGroup_setEnabled(self.stack_group_widget, self.operation.enabled)
            self.property_editor_controller = PropertyEditorController(self.ui, operation, self.ui.PyStackGroup_content(self.stack_group_widget))
        def __get_document_controller(self):
            return self.__document_controller_weakref()
        document_controller = property(__get_document_controller)
        def __get_ui(self):
            return self.document_controller.ui
        ui = property(__get_ui)
        def close(self):
            self.property_editor_controller.close()
            self.operation.remove_observer(self)
            self.ui.Widget_removeWidget(self.stack_group_widget)
        # receive change notifications from the operation. this connection is established
        # using add_observer/remove_observer.
        def property_changed(self, sender, property, value):
            if property == "enabled":
                self.ui.PyStackGroup_setEnabled(self.stack_group_widget, value)
        def __get_enabled(self):
            return self.operation.enabled
        def __set_enabled(self, enabled):
            try:  # try/except is for testing
                self.operation.enabled = enabled
            except Exception, e:
                import traceback
                traceback.print_exc()
                raise
        enabled = property(__get_enabled, __set_enabled)
        def add_pressed(self):
            logging.debug("add")
        def remove_pressed(self):
            self.document_controller.remove_operation(self.operation)

    # used for queue_main_thread decorator
    delay_queue = property(lambda self: self.document_controller.delay_queue)

    @queue_main_thread
    def rebuild_panel(self, operations):
        if self.widget:
            for stack_group in self.__stack_groups:
                stack_group.close()
            self.ui.Widget_removeAll(self.ui.PyStack_content(self.widget))
            self.__stack_groups = []
            for operation in operations:
                stack_group = self.StackGroup(self, operation)
                self.ui.Widget_addWidget(self.ui.PyStack_content(self.widget), stack_group.stack_group_widget)
                self.__stack_groups.append(stack_group)
            self.ui.Widget_addStretch(self.ui.PyStack_content(self.widget))

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_data_item_changed(self, data_item, info):
        operations = data_item.operations if data_item and data_item else []
        if info["property"] != "data":
            self.rebuild_panel(operations)
