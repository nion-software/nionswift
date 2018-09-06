import copy
import threading
import typing
import uuid

from nion.swift.model import DataItem
from nion.swift.model import FileStorageSystem
from nion.swift.model import Utility
from nion.utils import Event


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
        self.__properties2 = dict()
        self.__properties2_lock = threading.RLock()
        self.__data_item_storage = dict()

    def __deepcopy__(self, memo):
        deepcopy = self.__class__()
        deepcopy._set_properties(copy.deepcopy(self.library_storage_properties))
        deepcopy._set_storage_properties(copy.deepcopy(self.persistent_storage_properties))
        deepcopy.data = copy.deepcopy(self.data)
        memo[id(self)] = deepcopy
        return deepcopy

    def __write_properties(self, object):
        persistent_object_parent = object.persistent_object_parent if object else None
        if not persistent_object_parent:
            if object in self.__data_item_storage:
                self.__data_item_storage[object]._write_properties()
        else:
            self.__write_properties(persistent_object_parent.parent)

    @property
    def library_storage_properties(self):
        with self.__properties2_lock:
            return copy.deepcopy(self.__properties2)

    @property
    def persistent_storage_properties(self):
        return self.__properties

    def _set_properties(self, properties):
        """Set the properties; used for testing."""
        with self.__properties2_lock:
            self.__properties2 = properties

    def rewrite_properties(self, properties):
        """Set the properties and write to disk."""
        with self.__properties2_lock:
            self.__properties2 = properties
        self.__write_properties(None)

    def get_properties(self, object):
        return self.__get_storage_dict(object)

    def __get_storage_dict(self, object):
        persistent_object_parent = object.persistent_object_parent
        if not persistent_object_parent:
            if object in self.__data_item_storage:
                return self.__data_item_storage[object].properties
            return self.__properties2
        else:
            parent_storage_dict = self.__get_storage_dict(persistent_object_parent.parent)
            return object.get_accessor_in_parent()(parent_storage_dict)

    def __update_modified_and_get_storage_dict(self, object):
        storage_dict = self.__get_storage_dict(object)
        with self.__properties2_lock:
            storage_dict["modified"] = object.modified.isoformat()
        persistent_object_parent = object.persistent_object_parent
        parent = persistent_object_parent.parent if persistent_object_parent else None
        if parent:
            self.__update_modified_and_get_storage_dict(parent)
        return storage_dict

    def insert_item(self, parent, name, before_index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties2_lock:
            item_list = storage_dict.setdefault(name, list())
            item_dict = item.write_to_dict()
            item_list.insert(before_index, item_dict)
            item.persistent_object_context = parent.persistent_object_context
        self.__write_properties(parent)

    def remove_item(self, parent, name, index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties2_lock:
            item_list = storage_dict[name]
            del item_list[index]
        self.__write_properties(parent)
        item.persistent_object_context = None

    def set_item(self, parent, name, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties2_lock:
            if item:
                item_dict = item.write_to_dict()
                storage_dict[name] = item_dict
                item.persistent_object_context = parent.persistent_object_context
            else:
                if name in storage_dict:
                    del storage_dict[name]
        self.__write_properties(parent)

    def set_property(self, object, name, value):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties2_lock:
            storage_dict[name] = value
        self.__write_properties(object)

    def clear_property(self, object, name):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties2_lock:
            storage_dict.pop(name, None)
        self.__write_properties(object)

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

    def register_data_item(self, item: DataItem, storage_handler, properties: dict) -> None:
        assert item not in self.__data_item_storage
        self.__data_item_storage[item] = FileStorageSystem.DataItemStorageAdapter(self, storage_handler, item, properties)

    def unregister_data_item(self, item: DataItem) -> None:
        assert item in self.__data_item_storage
        self.__data_item_storage.pop(item).close()

    def __get_storage_for_item(self, item: DataItem) -> FileStorageSystem.DataItemStorageAdapter:
        return self.__data_item_storage.get(item)

    def _get_file_path(self, data_item: DataItem) -> typing.Optional[str]:
        storage = self.__get_storage_for_item(data_item)
        return storage._storage_handler.reference if storage else None

    def update_data(self, data_item, data):
        storage = self.__get_storage_for_item(data_item)
        storage.update_data(data_item, data)

    def load_data(self, data_item):
        storage = self.__get_storage_for_item(data_item)
        return storage.load_data(data_item)

    def delete_item(self, data_item, safe: bool=False) -> None:
        storage = self.__get_storage_for_item(data_item)
        storage.delete_item(data_item, safe)

    def set_write_delayed(self, data_item, write_delayed: bool) -> None:
        storage = self.__get_storage_for_item(data_item)
        storage.set_write_delayed(data_item, write_delayed)

    def is_write_delayed(self, data_item) -> bool:
        storage = self.__get_storage_for_item(data_item)
        return storage.is_write_delayed(data_item)

    def rewrite_item(self, data_item) -> None:
        storage = self.__get_storage_for_item(data_item)
        storage.rewrite_item(data_item)
