import copy
import threading
import typing
import uuid

from nion.swift.model import DataItem
from nion.swift.model import FileStorageSystem
from nion.swift.model import Migration
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
        return copy.deepcopy(self.__properties.get(self.__uuid, dict()))

    def read_data(self):
        self.__data_read_event.fire(self.__uuid)
        return self.__data.get(self.__uuid)

    def write_properties(self, properties, file_datetime):
        self.__properties[self.__uuid] = Utility.clean_dict(properties)

    def write_data(self, data, file_datetime):
        self.__data[self.__uuid] = data.copy()


class MemoryStorageSystem:
    """Simulate the file system interface for storage.

    data_item_storage is a dict used to hold data item files.

    library_storage is a  dict used to hold the library, while in memory.

    library_persistent_storage is a  dict used to hold the library, after written to disk.
    """

    def __init__(self, *, auto_migrations=None):
        self.data = dict()
        self.__data_item_storage = dict()
        self.trash = dict()
        self._test_data_read_event = Event.Event()
        self.__library_storage = dict()
        self.__library_storage_lock = threading.RLock()
        self.__library_persistent_storage = dict()
        self.__data_item_storage_adapters = dict()
        self.__write_delay_counts = dict()
        self.__auto_migrations = auto_migrations or list()
        for auto_migration in self.__auto_migrations:
            auto_migration.storage_system = self

    def __deepcopy__(self, memo):
        deepcopy = self.__class__()
        deepcopy._set_library_properties(copy.deepcopy(self.library_storage_properties))
        deepcopy._set_storage_properties(copy.deepcopy(self.persistent_storage_properties))
        deepcopy.data = copy.deepcopy(self.data)
        memo[id(self)] = deepcopy
        return deepcopy

    def reset(self):
        self.__data_item_storage_adapters = dict()

    def get_auto_migrations(self):
        return self.__auto_migrations

    def __write_properties(self, object):
        if self.__write_delay_counts.get(object, 0) == 0:
            persistent_object_parent = object.persistent_object_parent if object else None
            if object and isinstance(object, DataItem.DataItem):
                self.__get_storage_for_item(object).rewrite_item(object)
            elif not persistent_object_parent:
                self.__library_persistent_storage = copy.deepcopy(self.__library_storage)
            elif persistent_object_parent:
                self.__write_properties(persistent_object_parent.parent)

    @property
    def library_persistent_storage(self):
        return self.__library_persistent_storage

    @property
    def library_storage_properties(self):
        return self.__library_persistent_storage

    @property
    def persistent_storage_properties(self):
        return self.__data_item_storage

    def _set_library_properties(self, properties):
        """Set the properties; used for testing."""
        with self.__library_storage_lock:
            self.__library_storage = properties

    @property
    def library_properties(self):
        return self.__library_persistent_storage

    def rewrite_properties(self, properties):
        """Set the properties and write to disk."""
        with self.__library_storage_lock:
            self.__library_storage = properties
        self.__write_properties(None)

    def get_properties(self, object):
        return self.__get_storage_dict(object)

    def __get_storage_dict(self, object):
        persistent_object_parent = object.persistent_object_parent
        if isinstance(object, DataItem.DataItem):
            return self.__get_storage_for_item(object).properties
        if not persistent_object_parent:
            return self.__library_storage
        else:
            parent_storage_dict = self.__get_storage_dict(persistent_object_parent.parent)
            return object.get_accessor_in_parent()(parent_storage_dict)

    def __update_modified_and_get_storage_dict(self, object):
        storage_dict = self.__get_storage_dict(object)
        with self.__library_storage_lock:
            storage_dict["modified"] = object.modified.isoformat()
        persistent_object_parent = object.persistent_object_parent
        parent = persistent_object_parent.parent if persistent_object_parent else None
        if parent:
            self.__update_modified_and_get_storage_dict(parent)
        return storage_dict

    def insert_item(self, parent, name, before_index, item):
        if isinstance(item, DataItem.DataItem):
            item.persistent_object_context = parent.persistent_object_context
            storage_handler = self.make_storage_handler(item)
            self.register_data_item(item, item.uuid, storage_handler, item.write_to_dict())
        else:
            storage_dict = self.__update_modified_and_get_storage_dict(parent)
            with self.__library_storage_lock:
                item_list = storage_dict.setdefault(name, list())
                item_dict = item.write_to_dict()
                item_list.insert(before_index, item_dict)
                item.persistent_object_context = parent.persistent_object_context
            self.__write_properties(parent)

    def remove_item(self, parent, name, index, item):
        if isinstance(item, DataItem.DataItem):
            self.delete_item(item, safe=True)
            item.persistent_object_context = None
            self.unregister_data_item(item)
        else:
            storage_dict = self.__update_modified_and_get_storage_dict(parent)
            with self.__library_storage_lock:
                item_list = storage_dict[name]
                del item_list[index]
            self.__write_properties(parent)
            item.persistent_object_context = None

    def set_item(self, parent, name, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__library_storage_lock:
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
        with self.__library_storage_lock:
            storage_dict[name] = value
        self.__write_properties(object)

    def clear_property(self, object, name):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__library_storage_lock:
            storage_dict.pop(name, None)
        self.__write_properties(object)

    def _set_storage_properties(self, properties):
        self.__data_item_storage = properties

    def find_data_items(self):
        storage_handlers = list()
        for key in sorted(self.__data_item_storage):
            self.__data_item_storage[key].setdefault("uuid", str(uuid.uuid4()))
            storage_handlers.append(MemoryStorageHandler(key, self.__data_item_storage, self.data, self._test_data_read_event))
        return storage_handlers

    def make_storage_handler(self, data_item, file_handler=None):
        data_item_uuid_str = str(data_item.uuid)
        return MemoryStorageHandler(data_item_uuid_str, self.__data_item_storage, self.data, self._test_data_read_event)

    def remove_storage_handler(self, storage_handler, *, safe: bool=False) -> None:
        storage_handler_reference = storage_handler.reference
        data = self.data.pop(storage_handler_reference, None)
        properties = self.__data_item_storage.pop(storage_handler_reference)
        if safe:
            assert storage_handler_reference not in self.trash
            self.trash[storage_handler_reference] = {"data": data, "properties": properties}

    def restore_item(self, data_item_uuid: uuid.UUID) -> typing.Tuple[typing.Optional[dict], bool]:
        data_item_uuid_str = str(data_item_uuid)
        trash_entry = self.trash.pop(data_item_uuid_str)
        assert data_item_uuid_str not in self.__data_item_storage
        assert data_item_uuid_str not in self.data
        self.__data_item_storage[data_item_uuid_str] = Migration.transform_to_latest(trash_entry["properties"])
        self.data[data_item_uuid_str] = trash_entry["data"]
        properties = self.__data_item_storage.get(data_item_uuid_str, dict())
        properties["__large_format"] = False
        return properties

    def purge_removed_storage_handlers(self):
        self.trash = dict()

    def prune(self):
        pass

    def register_data_item(self, item, item_uuid, storage_handler, properties: dict) -> None:
        assert item_uuid not in self.__data_item_storage_adapters
        storage = FileStorageSystem.DataItemStorageAdapter(self, storage_handler, properties)
        self.__data_item_storage_adapters[item_uuid] = storage
        if item and self.is_write_delayed(item):
            storage.set_write_delayed(item, True)

    def unregister_data_item(self, item: DataItem) -> None:
        assert item.uuid in self.__data_item_storage_adapters
        self.__data_item_storage_adapters.pop(item.uuid).close()

    def __get_storage_for_item(self, item: DataItem) -> FileStorageSystem.DataItemStorageAdapter:
        if not item.uuid in self.__data_item_storage_adapters:
            storage_handler = self.make_storage_handler(item)
            self.register_data_item(item, item.uuid, storage_handler, item.write_to_dict())
        return self.__data_item_storage_adapters.get(item.uuid)

    def get_storage_property(self, data_item: DataItem.DataItem, name: str) -> typing.Optional[str]:
        if name == "file_path":
            storage = self.__get_storage_for_item(data_item)
            return storage._storage_handler.reference if storage else None
        return None

    def read_external_data(self, item, name):
        if isinstance(item, DataItem.DataItem) and name == "data":
            storage = self.__get_storage_for_item(item)
            return storage.load_data(item)
        return None

    def write_external_data(self, item, name, value) -> None:
        if isinstance(item, DataItem.DataItem) and name == "data":
            storage = self.__get_storage_for_item(item)
            storage.update_data(item, value)

    def delete_item(self, data_item, safe: bool=False) -> None:
        storage = self.__get_storage_for_item(data_item)
        self.remove_storage_handler(storage._storage_handler, safe=safe)

    def enter_write_delay(self, object) -> None:
        count = self.__write_delay_counts.setdefault(object, 0)
        if count == 0:
            if isinstance(object, DataItem.DataItem):
                self.set_write_delayed(object, True)
        self.__write_delay_counts[object] = count + 1

    def exit_write_delay(self, object) -> None:
        count = self.__write_delay_counts.get(object, 1)
        count -= 1
        if count == 0:
            if isinstance(object, DataItem.DataItem):
                self.set_write_delayed(object, False)
            self.__write_delay_counts.pop(object)
        else:
            self.__write_delay_counts[object] = count

    def set_write_delayed(self, data_item, write_delayed: bool) -> None:
        storage = self.__data_item_storage_adapters.get(data_item.uuid)
        if storage:
            storage.set_write_delayed(data_item, write_delayed)

    def is_write_delayed(self, data_item) -> bool:
        if isinstance(data_item, DataItem.DataItem):
            return self.__write_delay_counts.get(data_item, 0) > 0
        return False

    def rewrite_item(self, item) -> None:
        if isinstance(item, DataItem.DataItem):
            storage = self.__get_storage_for_item(item)
            storage.rewrite_item(item)
        else:
            self.__write_properties(item)

    def read_data_items_version_stats(self):
        return FileStorageSystem.read_data_items_version_stats(self)

    def read_library(self, ignore_older_files) -> typing.Dict:
        return FileStorageSystem.read_library(self, ignore_older_files)
