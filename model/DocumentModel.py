# standard libraries
import collections
import copy
import datetime
import gettext
import logging
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
from nion.swift.model import Utility

_ = gettext.gettext


class DataItemVault(object):

    """ Vaults should be stateless so that we can switch them in data items without repercussions. """

    def __init__(self, datastore=None, data_item_uuid=None, properties=None, storage_dict=None, delegate=None):
        self.datastore = datastore
        properties = datastore.get_root_property(data_item_uuid, "properties") if data_item_uuid else properties
        self.__properties = properties if properties else dict()
        self.storage_dict = storage_dict if storage_dict is not None else self.__properties
        self.__delegate = delegate  # a delegate item vault for updating properties
        self.__weak_data_item = None
        # reference type and reference indicate how to save/load data and properties
        self.reference_type = None
        self.reference = None
        if data_item_uuid:
            reference_type, reference = self.datastore.get_root_data_reference(data_item_uuid, "master_data")
            if reference:
                self.reference_type = reference_type
                self.reference = reference

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    def __set_data_item(self, data_item):
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
    data_item = property(__get_data_item, __set_data_item)

    def __get_delegate(self):
        return self.__delegate
    delegate = property(__get_delegate)

    def __get_properties(self):
        return copy.deepcopy(self.__properties)
    properties = property(__get_properties)

    def update_properties(self):
        if self.__delegate:
            self.__delegate.update_properties()
        elif self.datastore:
            self.datastore.set_root_property(self.data_item.uuid, "properties", self.__properties)
            # write to the file too
            self.ensure_data_file_path()
            file_datetime = Utility.get_datetime_from_datetime_item(self.data_item.datetime_original)
            data_file_path = os.path.splitext(self.reference)[0] + ".mtd"
            self.datastore.write_properties(self.__properties, "relative_file", data_file_path, file_datetime)

    def insert_item(self, name, before_index, item):
        item_list = self.storage_dict.setdefault(name, list())
        item_dict = dict()
        item_list.insert(before_index, item_dict)
        item.vault = DataItemVault(delegate=self, storage_dict=item_dict)
        item.write_storage(DataItemVault(delegate=self, storage_dict=item_dict))
        self.update_properties()

    def remove_item(self, name, index, item):
        item_list = self.storage_dict[name]
        del item_list[index]
        self.update_properties()

    def get_data_file_path(self):
        uuid_ = self.data_item.uuid
        datetime_item = self.data_item.datetime_original
        session_id = self.data_item.session_id
        # uuid_.bytes.encode('base64').rstrip('=\n').replace('/', '_')
        # and back: uuid_ = uuid.UUID(bytes=(slug + '==').replace('_', '/').decode('base64'))
        # also:
        def encode(uuid_, alphabet):
            result = str()
            uuid_int = uuid_.int
            while uuid_int:
                uuid_int, digit = divmod(uuid_int, len(alphabet))
                result += alphabet[digit]
            return result
        encoded_uuid_str = encode(uuid_, "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")  # 25 character results
        datetime_item = datetime_item if datetime_item else Utility.get_current_datetime_item()
        datetime_ = Utility.get_datetime_from_datetime_item(datetime_item)
        datetime_ = datetime_ if datetime_ else datetime.datetime.now()
        path_components = datetime_.strftime("%Y-%m-%d").split('-')
        session_id = session_id if session_id else datetime_.strftime("%Y%m%d-000000")
        path_components.append(session_id)
        path_components.append("master_data_" + encoded_uuid_str + ".nsdata")
        return os.path.join(*path_components)

    def ensure_data_file_path(self):
        if not self.reference:
            self.reference_type = "relative_file"
            self.reference = self.get_data_file_path()

    def update_data(self, data_shape, data_dtype, data=None, data_file_path=None):
        if self.datastore is not None:
            if data is not None:
                self.ensure_data_file_path()
                data_file_path = self.reference
                self.datastore.set_root_data_reference(self.data_item.uuid, "master_data", data, data_shape, data_dtype, "relative_file", data_file_path)
                file_datetime = Utility.get_datetime_from_datetime_item(self.data_item.datetime_original)
                self.datastore.write_data_reference(data, "relative_file", data_file_path, file_datetime)
                self.reference_type = "relative_file"
                self.reference = data_file_path
            elif data_file_path is not None:
                self.datastore.set_root_data_reference(self.data_item.uuid, "master_data", None, data_shape, data_dtype, "external_file", data_file_path)
                self.reference_type = "external_file"
                self.reference = data_file_path

    def load_data(self):
        assert self.data_item.has_master_data
        return self.datastore.load_data_reference("master_data", self.reference_type, self.reference)

    def __can_reload_data(self):
        return self.datastore is not None
    can_reload_data = property(__can_reload_data)

    def set_value(self, name, value):
        self.storage_dict[name] = value
        self.update_properties()

    def get_vault_for_item(self, name, index):
        storage_dict = self.storage_dict[name][index]
        return DataItemVault(delegate=self, storage_dict=storage_dict)

    def has_value(self, name):
        return name in self.storage_dict

    def get_value(self, name):
        return self.storage_dict[name]

    def get_item_vaults(self, name):
        if name in self.storage_dict:
            return [DataItemVault(delegate=self, storage_dict=storage_dict) for storage_dict in self.storage_dict[name]]
        return list()

    def get_master_data_info(self):
        if not self.datastore:
            return False, None, None
        has_master_data = self.datastore.has_root_data(self.data_item.uuid, "master_data")
        if has_master_data:
            master_data_shape, master_data_dtype = self.datastore.get_root_data_shape_and_dtype(self.data_item.uuid, "master_data")
        else:
            master_data_shape, master_data_dtype = None, None
        return has_master_data, master_data_shape, master_data_dtype


class DbDataItemVault(object):

    def __init__(self, document_model, datastore, storage_cache):
        self.__weak_document_model = weakref.ref(document_model)
        self.__datastore = datastore
        self.__storage_cache = storage_cache
        self.__data_items = list()

    def __get_data_items(self):
        return self.__data_items
    data_items = property(__get_data_items)

    def read_data_items(self):
        document_model = self.__weak_document_model()
        data_item_uuids = self.__datastore.find_root_item_uuids("data-item")
        data_items = list()
        for index, data_item_uuid in enumerate(data_item_uuids):
            vault = DataItemVault(self.__datastore, data_item_uuid)
            data_item = DataItem.DataItem(vault=vault, item_uuid=data_item_uuid, create_display=False)
            assert(len(data_item.displays) > 0)
            data_item.add_ref()
            data_items.append(data_item)
        def sort_by_date_key(data_item):
            return Utility.get_datetime_from_datetime_item(data_item.datetime_original)
        data_items.sort(key=sort_by_date_key)
        for data_item in data_items:
            self.__data_items.insert(index, data_item)
            data_item.sync_intrinsic_spatial_calibrations()
            data_item.storage_cache = self.__storage_cache
            data_item.add_listener(document_model)

    def insert(self, before_index, data_item):
        # TODO: move the tail into the caller area
        # this comes from MutableRelationship, StorageBase, and DocumentModel.notify_insert_item
        assert data_item is not None
        assert data_item not in self.__data_items
        assert before_index <= len(self.__data_items) and before_index >= 0
        document_model = self.__weak_document_model()
        # ref count
        data_item.add_ref()
        # insert in internal list
        self.__data_items.insert(before_index, data_item)
        # keep storage up-to-date
        data_item.update_vault(DataItemVault(properties=data_item.vault.properties))
        data_item.vault.data_item = data_item
        data_item.vault.datastore = self.__datastore
        self.__datastore.add_root_item_uuid("data-item", data_item.uuid)
        data_item.storage_cache = self.__storage_cache
        data_item.write()
        # be a listener. why?
        data_item.add_listener(document_model)
        document_model.notify_listeners("data_item_inserted", document_model, data_item, before_index, False)

    def remove(self, data_item):
        # TODO: move the tail into the caller area
        # this comes from MutableRelationship, StorageBase, and DocumentModel.notify_remove_item
        assert data_item is not None
        assert data_item in self.__data_items
        document_model = self.__weak_document_model()
        index = self.__data_items.index(data_item)
        # do actual removal
        del self.__data_items[index]
        # keep storage up-to-date
        self.__datastore.remove_root_item_uuid("data-item", data_item.uuid)
        data_item.update_vault(DataItem.DataItemMemoryVault(properties=data_item.vault.properties))
        #data_item.vault.datastore = None
        data_item.__storage_cache = None
        # unlisten to data item
        data_item.remove_listener(document_model)
        # update data item count
        document_model.notify_listeners("data_item_removed", document_model, data_item, index, False)
        if data_item.get_observer_count(document_model) == 0:  # ugh?
            document_model.notify_listeners("data_item_deleted", data_item)
        # ref count
        data_item.remove_ref()


class DocumentModel(Storage.StorageBase):

    def __init__(self, datastore, storage_cache=None):
        super(DocumentModel, self).__init__()
        self.datastore = datastore
        self.storage_cache = storage_cache if storage_cache else Storage.DictStorageCache()
        self.__data_item_vault = DbDataItemVault(self, datastore, self.storage_cache)
        self.storage_relationships += ["data_groups"]
        self.storage_type = "document"
        self.data_groups = Storage.MutableRelationship(self, "data_groups")
        self.session_id = None
        self.start_new_session()
        if self.datastore.initialized:
            self.__read()
        else:
            self.datastore.set_root(self)
            self.write()

    def about_to_delete(self):
        self.datastore.disconnected = True
        while len(self.data_items) > 0:
            self.remove_data_item(self.data_items[-1])
        for data_group in copy.copy(self.data_groups):
            self.remove_data_group(data_group)

    def __read(self):
        # first read the items
        parent_node, uuid = self.datastore.find_root_node("document")
        self._set_uuid(uuid)
        data_groups = self.datastore.get_items(parent_node, "data_groups")
        self.__data_item_vault.read_data_items()
        # now update the fields on self, disconnecting the datastore
        # to prevent writing them back out to the database.
        self.datastore.disconnected = True
        for data_item in self.__data_item_vault.data_items:
            data_item.connect_data_source(self.get_data_item_by_uuid)
        for data_group in data_groups:
            self.append_data_group(data_group)
        for data_group in self.data_groups:
            data_group.connect_data_items(self.get_data_item_by_uuid)
        self.datastore.disconnected = False

    def start_new_session(self):
        self.session_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    def append_data_item(self, data_item):
        self.insert_data_item(len(self.data_items), data_item)

    def insert_data_item(self, before_index, data_item):
        self.__data_item_vault.insert(before_index, data_item)
        data_item.connect_data_source(self.get_data_item_by_uuid)

    def remove_data_item(self, data_item):
        for data_group in self.get_flat_data_group_generator():
            if data_item in data_group.data_items:
                data_group.remove_data_item(data_item)
        for other_data_item in copy.copy(self.data_items):
            if other_data_item.data_source == data_item:
                self.remove_data_item(other_data_item)
        data_item.disconnect_data_source()
        self.__data_item_vault.remove(data_item)

    def __get_data_items(self):
        return tuple(self.__data_item_vault.data_items)
    data_items = property(__get_data_items)

    def get_dependent_data_items(self, parent_data_item):
        return [data_item for data_item in self.data_items if data_item.data_source == parent_data_item]

    def append_data_group(self, data_group):
        self.insert_data_group(len(self.data_groups), data_group)

    def insert_data_group(self, before_index, data_group):
        self.data_groups.insert(before_index, data_group)

    def remove_data_group(self, data_group):
        data_group.disconnect_data_items()
        self.data_groups.remove(data_group)

    def create_default_data_groups(self):
        # ensure there is at least one group
        if len(self.data_groups) < 1:
            data_group = DataGroup.DataGroup()
            data_group.title = _("My Data")
            self.append_data_group(data_group)

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
            self.insert_data_group(0, data_group)
        return data_group
