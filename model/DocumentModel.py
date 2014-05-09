# standard libraries
import collections
import copy
import datetime
import gettext
import numbers
import os.path
import uuid
import weakref

# third party libraries
import scipy

# local libraries
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import Image
from nion.swift.model import ImportExportManager
from nion.swift.model import PlugInManager
from nion.swift.model import Storage

_ = gettext.gettext


class DocumentModel(Storage.StorageBase):

    def __init__(self, datastore, storage_cache=None):
        super(DocumentModel, self).__init__()
        self.__counted_data_items = collections.Counter()
        self.datastore = datastore
        self.storage_cache = storage_cache if storage_cache else Storage.DictStorageCache()
        self.storage_relationships += ["data_groups", "data_items"]
        self.storage_type = "document"
        self.data_groups = Storage.MutableRelationship(self, "data_groups")
        self.__data_items = Storage.MutableRelationship(self, "data_items")
        self.session_id = None
        self.start_new_session()
        if self.datastore.initialized:
            self.__read()
        else:
            self.datastore.set_root(self)
            self.write()

    def about_to_delete(self):
        self.datastore.disconnected = True
        for data_item in copy.copy(self.data_items):
            self.remove_data_item(data_item)
        for data_group in copy.copy(self.data_groups):
            self.data_groups.remove(data_group)

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

    def start_new_session(self):
        self.session_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    def append_data_item(self, data_item, sources=None):
        if sources is not None:
            assert len(sources) == 1
            sources[0].data_items.append(data_item)
        else:
            self.__data_items.append(data_item)

    def insert_data_item(self, before_index, data_item):
        self.__data_items.insert(before_index, data_item)

    def remove_data_item(self, data_item):
        for data_group in self.get_flat_data_group_generator():
            if data_item in data_group.data_items:
                data_group.remove_data_item(data_item)
        self.__data_items.remove(data_item)

    def __get_data_items(self):
        return tuple(self.__data_items)
    data_items = property(__get_data_items)

    def create_default_data_groups(self):
        # ensure there is at least one group
        if len(self.data_groups) < 1:
            data_group = DataGroup.DataGroup()
            data_group.title = _("My Data")
            self.data_groups.append(data_group)

    def create_sample_images(self, resources_path):
        if True:
            data_group = self.get_or_create_data_group(_("Example Data"))
            handler = ImportExportManager.NDataImportExportHandler(None, ["ndata1"])
            samples_dir = os.path.join(resources_path, "SampleImages")
            #logging.debug("Looking in %s", samples_dir)
            def is_ndata(file_path):
                #logging.debug("Checking %s", file_path)
                _, extension = os.path.splitext(file_path)
                return extension == ".ndata1"
            if os.path.isdir(samples_dir):
                sample_paths = [os.path.join(samples_dir, d) for d in os.listdir(samples_dir) if is_ndata(os.path.join(samples_dir, d))]
            else:
                sample_paths = []
            for sample_path in sorted(sample_paths):
                def source_file_path_in_document(sample_path_):
                    for member_data_item in self.data_items:
                        if member_data_item.source_file_path == sample_path_:
                            return True
                    return False
                if not source_file_path_in_document(sample_path):
                    data_items = handler.read_data_items(None, "ndata1", sample_path, False)
                    for data_item in data_items:
                        #__, file_name = os.path.split(sample_path)
                        #title, __ = os.path.splitext(file_name)
                        #data_item.title = title
                        with data_item.ref():
                            self.append_data_item(data_item)
                            data_group.append_data_item(data_item)
        else:
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

    # these are the internal counted data items, not the ones participating in the
    # data group counting. they are different because the document model doesn't
    # count data items in sub-groups, whereas the data groups do. these methods are
    # differentiated only in the two underscores preceding the name.
    def __update_counted_data_items(self, counted_data_items):
        self.__counted_data_items.update(counted_data_items)
        self.notify_parents("update_counted_data_items", counted_data_items)
        self.notify_listeners("update_counted_data_items", counted_data_items)
    def __subtract_counted_data_items(self, counted_data_items):
        self.__counted_data_items.subtract(counted_data_items)
        self.__counted_data_items += collections.Counter()  # strip empty items
        self.notify_parents("subtract_counted_data_items", counted_data_items)
        self.notify_listeners("subtract_counted_data_items", counted_data_items)

    # override from StorageBase.
    def notify_insert_item(self, key, value, before_index):
        super(DocumentModel, self).notify_insert_item(key, value, before_index)
        if key == "data_items":
            # an item was inserted, start observing
            self.item_inserted(self, key, value, before_index)

    # override from StorageBase
    def notify_remove_item(self, key, value, index):
        super(DocumentModel, self).notify_remove_item(key, value, index)
        if key == "data_items":
            # item will be removed, stop observing
            self.item_removed(self, key, value, index)

    def item_inserted(self, parent, key, item, before):
        # watch for data items inserted into this document model or into other data items
        # but not into data groups.
        if key == "data_items" and (parent == self or isinstance(parent, DataItem.DataItem)):
            data_item = item
            counted_data_items = collections.Counter()
            # become an observer of every data group and data item
            #logging.debug("add observer [5] %s %s", data_item, self)
            data_item.add_observer(self)
            data_item.add_listener(self)
            # update data item count
            counted_data_items.update([data_item])
            # and the children
            for child_data_item in DataGroup.get_flat_data_item_generator_in_container(data_item):
                #logging.debug("add observer [4] %s %s", child_data_item, self)
                child_data_item.add_observer(self)
                child_data_item.add_listener(self)
                # update data item count
                counted_data_items.update([child_data_item])
            self.__update_counted_data_items(counted_data_items)

    def item_removed(self, parent, key, item, index):
        # watch for data items inserted into this document model or into other data items
        # but not into data groups.
        if key == "data_items" and (parent == self or isinstance(parent, DataItem.DataItem)):
            data_item = item
            counted_data_items = collections.Counter()
            # become an observer of every data group and data item
            for child_data_item in DataGroup.get_flat_data_item_generator_in_container(data_item):
                #logging.debug("remove observer [4] %s %s", child_data_item, self)
                child_data_item.remove_listener(self)
                child_data_item.remove_observer(self)
                # update data item count
                counted_data_items.update([child_data_item])
            #logging.debug("remove observer [5] %s %s", data_item, self)
            data_item.remove_listener(self)
            data_item.remove_observer(self)
            # update data item count
            counted_data_items.update([data_item])
            self.__subtract_counted_data_items(counted_data_items)
            if data_item.get_observer_count(self) == 0:
                self.notify_listeners("data_item_deleted", data_item)

    # watch for property changes to data items so that smart filters get updated.
    # tell any data groups to update their filter.
    def data_item_property_changed(self, data_item, property, value):
        self.notify_parents("data_item_property_changed", data_item, property, value)
        self.notify_listeners("data_item_property_changed", data_item, property, value)

    # this message comes from a data item when it wants to be removed from the document. ugh.
    def request_remove_data_item(self, data_item):
        DataGroup.get_data_item_container(self, data_item).remove_data_item(data_item)

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
            return [data_item.title for data_item in self.document_model.data_items_by_key]
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
            return [data_item.title for data_item in self.document_model.data_items_by_key]
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
            if data_item.title == title:
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
