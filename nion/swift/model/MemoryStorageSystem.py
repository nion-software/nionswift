import copy
import threading
import uuid

from nion.swift.model import Utility
from nion.utils import Event


class MemoryPersistentStorage:
    # this class is used to store the data for the library itself.
    # it is not used for library items.

    def __init__(self, properties=None):
        self.__properties = properties if properties else dict()
        self.__properties_lock = threading.RLock()

    def get_version(self):
        return 0

    def __write_properties(self):
        pass

    @property
    def properties(self):
        with self.__properties_lock:
            return copy.deepcopy(self.__properties)

    def _set_properties(self, properties):
        """Set the properties; used for testing."""
        with self.__properties_lock:
            self.__properties = properties

    def rewrite_properties(self, properties):
        """Set the properties and write to disk."""
        with self.__properties_lock:
            self.__properties = properties
        self.__write_properties()

    def __get_storage_dict(self, object):
        persistent_object_parent = object.persistent_object_parent
        if not persistent_object_parent:
            return self.__properties
        else:
            parent_storage_dict = self.__get_storage_dict(persistent_object_parent.parent)
            return object.get_accessor_in_parent()(parent_storage_dict)

    def __update_modified_and_get_storage_dict(self, object):
        storage_dict = self.__get_storage_dict(object)
        with self.__properties_lock:
            storage_dict["modified"] = object.modified.isoformat()
        persistent_object_parent = object.persistent_object_parent
        parent = persistent_object_parent.parent if persistent_object_parent else None
        if parent:
            self.__update_modified_and_get_storage_dict(parent)
        return storage_dict

    def insert_item(self, parent, name, before_index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict.setdefault(name, list())
            item_dict = item.write_to_dict()
            item_list.insert(before_index, item_dict)
            item.persistent_object_context = parent.persistent_object_context
        self.__write_properties()

    def remove_item(self, parent, name, index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict[name]
            del item_list[index]
        self.__write_properties()
        item.persistent_object_context = None

    def set_item(self, parent, name, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            if item:
                item_dict = item.write_to_dict()
                storage_dict[name] = item_dict
                item.persistent_object_context = parent.persistent_object_context
            else:
                if name in storage_dict:
                    del storage_dict[name]
        self.__write_properties()

    def set_property(self, object, name, value):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict[name] = value
        self.__write_properties()

    def clear_property(self, object, name):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict.pop(name, None)
        self.__write_properties()


class MemoryStorageHandler:

    def __init__(self, uuid, properties, data, data_read_event):
        self.__uuid = uuid
        self.__properties = properties
        self.__data = data
        self.__data_read_event = data_read_event

    def close(self):
        self.__uuid = None
        self.__properties = None
        self.__data = None

    @property
    def reference(self):
        return str(self.__uuid)

    def read_properties(self):
        return self.__properties.get(self.__uuid, dict())

    def read_data(self):
        self.__data_read_event.fire(self.__uuid)
        return self.__data.get(self.__uuid)

    def write_properties(self, properties, file_datetime):
        self.__properties[self.__uuid] = Utility.clean_dict(copy.deepcopy(properties))

    def write_data(self, data, file_datetime):
        self.__data[self.__uuid] = data.copy()


class MemoryStorageSystem:

    def __init__(self):
        self.data = dict()
        self.__properties = dict()
        self.trash = dict()
        self._test_data_read_event = Event.Event()
        self.__persistent_storage = MemoryPersistentStorage()

    def __deepcopy__(self, memo):
        deepcopy = self.__class__()
        deepcopy._set_properties(copy.deepcopy(self.library_storage_properties))
        deepcopy._set_storage_properties(copy.deepcopy(self.persistent_storage_properties))
        deepcopy.data = copy.deepcopy(self.data)
        memo[id(self)] = deepcopy
        return deepcopy

    @property
    def library_storage_properties(self):
        return self.__persistent_storage.properties

    @property
    def persistent_storage_properties(self):
        return self.__properties

    def _set_properties(self, properties):
        self.__persistent_storage._set_properties(properties)

    def rewrite_properties(self, properties):
        self.__persistent_storage.rewrite_properties(properties)

    def insert_item(self, parent, name, before_index, item):
        self.__persistent_storage.insert_item(parent, name, before_index, item)

    def remove_item(self, parent, name, index, item):
        self.__persistent_storage.remove_item(parent, name, index, item)

    def set_item(self, parent, name, item):
        self.__persistent_storage.set_item(parent, name, item)

    def set_property(self, object, name, value):
        self.__persistent_storage.set_property(object, name, value)

    def clear_property(self, object, name):
        self.__persistent_storage.clear_property(object, name)

    def _set_storage_properties(self, properties):
        self.__properties = properties

    def find_data_items(self):
        storage_handlers = list()
        for key in sorted(self.__properties):
            self.__properties[key].setdefault("uuid", str(uuid.uuid4()))
            storage_handlers.append(MemoryStorageHandler(key, self.__properties, self.data, self._test_data_read_event))
        return storage_handlers

    def make_storage_handler(self, data_item, file_handler=None):
        data_item_uuid_str = str(data_item.uuid)
        return MemoryStorageHandler(data_item_uuid_str, self.__properties, self.data, self._test_data_read_event)

    def remove_storage_handler(self, storage_handler, *, safe: bool=False) -> None:
        storage_handler_reference = storage_handler.reference
        data = self.data.pop(storage_handler_reference, None)
        properties = self.__properties.pop(storage_handler_reference)
        if safe:
            assert storage_handler_reference not in self.trash
            self.trash[storage_handler_reference] = {"data": data, "properties": properties}

    def restore_storage_handler(self, data_item_uuid: uuid.UUID):
        data_item_uuid_str = str(data_item_uuid)
        trash_entry = self.trash.pop(data_item_uuid_str)
        assert data_item_uuid_str not in self.__properties
        assert data_item_uuid_str not in self.data
        self.__properties[data_item_uuid_str] = trash_entry["properties"]
        self.data[data_item_uuid_str] = trash_entry["data"]
        return MemoryStorageHandler(data_item_uuid_str, self.__properties, self.data, self._test_data_read_event)

    def purge_removed_storage_handlers(self):
        self.trash = dict()

    def prune(self):
        pass
