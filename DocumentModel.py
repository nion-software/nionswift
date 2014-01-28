# standard libraries
import collections
import copy
import gettext
import logging
import numbers
import uuid
import weakref

# third party libraries
import scipy

# local libraries
from nion.swift import DataGroup
from nion.swift import DataItem
from nion.swift import Image
from nion.swift import Session
from nion.swift import Storage

_ = gettext.gettext


class DocumentModel(Storage.StorageBase):

    def __init__(self, datastore, storage_cache=None):
        super(DocumentModel, self).__init__()
        self.__counted_data_items = collections.Counter()
        self.datastore = datastore
        self.storage_cache = storage_cache if storage_cache else Storage.DictStorageCache()
        self.storage_relationships += ["data_groups"]
        self.storage_type = "document"
        self.data_groups = Storage.MutableRelationship(self, "data_groups")
        self.__data_items = Storage.MutableRelationship(self, "data_items")
        self.session = Session.Session(self)
        if self.datastore.initialized:
            self.__read()
        else:
            self.datastore.set_root(self)
            self.write()

    def about_to_delete(self):
        self.datastore.disconnected = True
        self.session = None
        for data_group in copy.copy(self.data_groups):
            self.data_groups.remove(data_group)
        for data_item in copy.copy(self.data_items):
            self.remove_data_item(data_item)

    # TODO: make DocumentModel.read private
    def __read(self):
        # first read the items
        parent_node, uuid = self.datastore.find_root_node("document")
        self._set_uuid(uuid)
        data_groups = self.datastore.get_items(parent_node, "data_groups")
        data_items = self.datastore.get_items(parent_node, "data_items")
        # now update the fields on self, disconnecting the datastore
        # to prevent writing them back out to the database.
        self.datastore.disconnected = True
        self.data_groups.extend(data_groups)
        self.__data_items.extend(data_items)
        self.datastore.disconnected = False

    def append_data_item(self, data_item):
        self.__data_items.append(data_item)

    def insert_data_item(self, before_index, data_item):
        self.__data_items.insert(before_index, data_item)

    def remove_data_item(self, data_item):
        self.__data_items.remove(data_item)

    def __get_data_items(self):
        return tuple(self.__data_items)
    data_items = property(__get_data_items)

    def create_default_data_groups(self):
        # ensure there is at least one group
        if len(self.data_groups) < 1:
            data_group = DataGroup.DataGroup()
            data_group.title = _("Library")
            self.data_groups.append(data_group)

    def create_test_images(self):
        # for testing, add a checkerboard image data item
        checkerboard_image_source = DataItem.DataItem()
        checkerboard_image_source.title = "Checkerboard"
        with checkerboard_image_source.data_ref() as data_ref:
            data_ref.master_data = Image.create_checkerboard((512, 512))
        self.append_data_item(checkerboard_image_source)
        # for testing, add a color image data item
        color_image_source = DataItem.DataItem()
        color_image_source.title = "Green Color"
        with color_image_source.data_ref() as data_ref:
            data_ref.master_data = Image.create_color_image((512, 512), 128, 255, 128)
        self.append_data_item(color_image_source)
        # for testing, add a color image data item
        lena_image_source = DataItem.DataItem()
        lena_image_source.title = "Lena"
        with lena_image_source.data_ref() as data_ref:
            data_ref.master_data = scipy.misc.lena()
        self.append_data_item(lena_image_source)

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

    # override from StorageBase.
    def notify_insert_item(self, key, value, before_index):
        super(DocumentModel, self).notify_insert_item(key, value, before_index)
        if key == "data_groups":
            data_group = value
            # update the count in the data groups
            self.update_counted_data_items(data_group.counted_data_items)
            # initialize data group with current set of data (used for smart data groups)
            if hasattr(data_group, "update_counted_data_items_for_filter"):
                data_group.update_counted_data_items_for_filter(self.counted_data_items)
        if key == "data_items":
            # an item was inserted, start observing
            self.item_inserted(self, key, value, before_index)

    # override from StorageBase
    def notify_remove_item(self, key, value, index):
        super(DocumentModel, self).notify_remove_item(key, value, index)
        if key == "data_groups":
            # update the count in the data groups
            self.subtract_counted_data_items(value.counted_data_items)
        if key == "data_items":
            # item will be removed, stop observing
            self.item_removed(self, key, value, index)

    def item_inserted(self, parent, key, item, before):
        # watch for data items inserted into this document model or into other data items
        # but not into data groups.
        if key == "data_items" and (parent == self or isinstance(parent, DataItem.DataItem)):
            data_item = item
            # become an observer of every data group and data item
            #logging.debug("add observer [5] %s %s", data_item, self)
            data_item.add_observer(self)
            # and the children
            for child_data_item in DataGroup.get_flat_data_item_generator_in_container(data_item):
                #logging.debug("add observer [4] %s %s", child_data_item, self)
                child_data_item.add_observer(self)

    def item_removed(self, parent, key, item, index):
        # watch for data items inserted into this document model or into other data items
        # but not into data groups.
        if key == "data_items" and (parent == self or isinstance(parent, DataItem.DataItem)):
            data_item = item
            # become an observer of every data group and data item
            for child_data_item in DataGroup.get_flat_data_item_generator_in_container(data_item):
                #logging.debug("remove observer [4] %s %s", child_data_item, self)
                child_data_item.remove_observer(self)
            #logging.debug("remove observer [5] %s %s", data_item, self)
            data_item.remove_observer(self)
            if data_item.get_observer_count(self) == 0:
                self.notify_listeners("data_item_deleted", data_item)

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
            if data_item:
                with data_item.data_ref() as data_ref:
                    return data_ref.data
            return None

    class DataAccessor(object):
        def __init__(self, document_model):
            self.__document_model_weakref = weakref.ref(document_model)
        def __get_document_model(self):
            return self.__document_model_weakref()
        document_model = property(__get_document_model)
        # access by bracket notation
        def __len__(self):
            return self.document_model.get_data_item_count()
        def __getitem__(self, key):
            data = self.document_model.get_data_by_key(key)
            if data is None:
                raise KeyError
            return data
        def __setitem__(self, key, value):
            return self.document_model.set_data_by_key(key, value)
        def __delitem__(self, key):
            data_item = self.document_model.get_data_item_by_key(key)
            if data_item:
                self.document_model.remove_data_item(data_item)
        def __iter__(self):
            return DocumentModel._DataAccessorIter(self.document_model.get_flat_data_item_generator())
        def uuid_keys(self):
            return [data_item.uuid for data_item in self.document_model.data_items_by_key]
        def title_keys(self):
            return [str(data_item) for data_item in self.document_model.data_items_by_key]
        def keys(self):
            return self.uuid_keys()

    class DataItemAccessor(object):
        def __init__(self, document_model):
            self.__document_model_weakref = weakref.ref(document_model)
        def __get_document_model(self):
            return self.__document_model_weakref()
        document_model = property(__get_document_model)
        # access by bracket notation
        def __len__(self):
            return self.document_model.get_data_item_count()
        def __getitem__(self, key):
            data_item = self.document_model.get_data_item_by_key(key)
            if data_item is None:
                raise KeyError
            return data_item
        def __delitem__(self, key):
            data_item = self.document_model.get_data_item_by_key(key)
            if data_item:
                self.document_model.remove_data_item(data_item)
        def __iter__(self):
            return iter(self.document_model.get_flat_data_item_generator())
        def uuid_keys(self):
            return [data_item.uuid for data_item in self.document_model.data_items_by_key]
        def title_keys(self):
            return [str(data_item) for data_item in self.document_model.data_items_by_key]
        def keys(self):
            return self.uuid_keys()

    # Return a generator over all data items
    def get_flat_data_item_generator(self):
        for data_item in self.data_items:
            yield data_item
            for child_data_item in DataGroup.get_flat_data_item_generator_in_container(data_item):
                yield child_data_item

    # Return a generator over all data groups
    def get_flat_data_group_generator(self):
        return DataGroup.get_flat_data_group_generator_in_container(self)

    def get_data_group_by_uuid(self, uuid):
        for data_group in DataGroup.get_flat_data_group_generator_in_container(self):
            if data_group.uuid == uuid:
                return data_group
        return None

    def get_data_item_count(self):
        return len(list(self.get_flat_data_item_generator()))

    # temporary method to find the container of a data item. this goes away when
    # data items get stored in a flat table.
    def get_data_item_data_group(self, data_item):
        for data_group in self.get_flat_data_group_generator():
            if data_item in DataGroup.get_flat_data_item_generator_in_container(data_group):
                return data_group
        return None

    # access data item by key (title, uuid, index)
    def get_data_item_by_key(self, key):
        if isinstance(key, numbers.Integral):
            return list(self.get_flat_data_item_generator())[key]
        if isinstance(key, uuid.UUID):
            return self.get_data_item_by_uuid(key)
        return self.get_data_item_by_title(str(key))
    def get_data_by_key(self, key):
        data_item = self.get_data_item_by_key(key)
        if data_item:
            with data_item.data_ref() as data_ref:
                return data_ref.data
        return None
    def set_data_by_key(self, key, data):
        data_item = self.get_data_item_by_key(key)
        if data_item:
            with data_item.data_ref() as data_ref:
                data_ref.master_data = data
        else:
            if isinstance(key, numbers.Integral):
                raise IndexError
            if isinstance(key, uuid.UUID):
                raise KeyError
            data_item = DataItem.DataItem()
            data_item.title = str(key)
            with data_item.data_ref() as data_ref:
                data_ref.master_data = data
            self.append_data_item(data_item)
        return data_item

    # access data items by title
    def get_data_item_by_title(self, title):
        for data_item in self.get_flat_data_item_generator():
            if str(data_item) == title:
                return data_item
        return None
    def get_data_by_title(self, title):
        data_item = self.get_data_item_by_title(title)
        if data_item:
            with data_item.data_ref() as data_ref:
                return data_ref.data
        return None

    # access data items by index
    def get_data_item_by_index(self, index):
        return list(self.get_flat_data_item_generator())[index]
    def get_data_by_index(self, index):
        data_item = self.get_data_item_by_index(index)
        if data_item:
            with data_item.data_ref() as data_ref:
                return data_ref.data
        return None
    def set_data_by_index(self, index, data):
        data_item = self.get_data_item_by_index(index)
        if data_item:
            with data_item.data_ref() as data_ref:
                data_ref.master_data = data
        else:
            raise IndexError
    def get_index_for_data_item(self, data_item):
        return list(self.get_flat_data_item_generator()).index(data_item)

    # access data items by uuid
    def get_data_item_by_uuid(self, uuid):
        for data_item in self.get_flat_data_item_generator():
            if data_item.uuid == uuid:
                return data_item
        return None
    def get_data_by_uuid(self, uuid):
        data_item = self.get_data_item_by_uuid(uuid)
        if data_item:
            with data_item.data_ref() as data_ref:
                return data_ref.data
        return None
    def set_data_by_uuid(self, uuid, data):
        data_item = self.get_data_item_by_uuid(uuid)
        if data_item:
            with data_item.data_ref() as data_ref:
                data_ref.master_data = data
        else:
            raise KeyError

    def get_or_create_data_group(self, group_name):
        data_group = DataGroup.get_data_group_in_container_by_title(self, group_name)
        if data_group is None:
            # we create a new group
            data_group = DataGroup.DataGroup()
            data_group.title = group_name
            self.data_groups.insert(0, data_group)
        return data_group
