import copy
import json
import logging
import os.path
import pathlib
import shutil
import threading
import typing
import uuid
import weakref

from nion.swift.model import DataItem
from nion.swift.model import HDF5Handler
from nion.swift.model import NDataHandler
from nion.swift.model import Utility


class DataItemStorageAdapter:
    """Persistent storage for writing data item properties, relationships, and data to its storage handler.

    The storage_handler must respond to these methods:
        close()
        read_data()
        write_properties(properties, file_datetime)
        write_data(data, file_datetime)
        remove()
    """

    def __init__(self, storage_system, storage_handler, data_item, properties):
        self.__storage_system = storage_system
        self.__storage_handler = storage_handler
        self.__properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
        self.__properties_lock = threading.RLock()
        self.__write_delayed = False

    def close(self):
        if self.__storage_handler:
            self.__storage_handler.close()
            self.__storage_handler = None

    @property
    def properties(self):
        with self.__properties_lock:
            return self.__properties

    @property
    def _storage_handler(self):
        return self.__storage_handler

    def set_write_delayed(self, data_item, write_delayed: bool) -> None:
        self.__write_delayed = write_delayed

    def is_write_delayed(self, data_item) -> bool:
        return self.__write_delayed

    def rewrite_item(self, data_item) -> None:
        if not self.__write_delayed:
            file_datetime = data_item.created_local
            self.__storage_handler.write_properties(self.properties, file_datetime)

    def update_data(self, data_item, data):
        if not self.__write_delayed:
            file_datetime = data_item.created_local
            if data is not None:
                self.__storage_handler.write_data(data, file_datetime)

    def load_data(self, data_item) -> None:
        assert data_item.has_data
        return self.__storage_handler.read_data()


class FileStorageSystem:

    _file_handlers = [NDataHandler.NDataHandler, HDF5Handler.HDF5Handler]

    def __init__(self, file_path, directories):
        self.__directories = directories
        self.__file_handlers = FileStorageSystem._file_handlers
        self.__data_item_storage = dict()
        self.__filepath = file_path
        self.__properties = self.__read_properties()
        self.__properties_lock = threading.RLock()

    def __read_properties(self):
        properties = dict()
        if self.__filepath and os.path.exists(self.__filepath):
            try:
                with open(self.__filepath, "r") as fp:
                    properties = json.load(fp)
            except Exception:
                os.replace(self.__filepath, self.__filepath + ".bak")
        # migrations go here
        return properties

    def __write_properties(self, object):
        persistent_object_parent = object.persistent_object_parent if object else None
        if not persistent_object_parent:
            if object in self.__data_item_storage:
                self.__data_item_storage[object].rewrite_item(object)
            else:
                if self.__filepath:
                    # atomically overwrite
                    temp_filepath = self.__filepath + ".temp"
                    with open(temp_filepath, "w") as fp:
                        json.dump(self.__properties, fp)
                    os.replace(temp_filepath, self.__filepath)
        else:
            self.__write_properties(persistent_object_parent.parent)

    @property
    def library_storage_properties(self):
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
        self.__write_properties(None)  # write to library

    def __get_storage_dict(self, object):
        persistent_object_parent = object.persistent_object_parent
        if not persistent_object_parent:
            if object in self.__data_item_storage:
                return self.__data_item_storage[object].properties
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
        self.__write_properties(parent)

    def remove_item(self, parent, name, index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict[name]
            del item_list[index]
        self.__write_properties(parent)
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
        self.__write_properties(parent)

    def set_property(self, object, name, value):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict[name] = value
        self.__write_properties(object)

    def clear_property(self, object, name):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict.pop(name, None)
        self.__write_properties(object)

    def find_data_items(self):
        return self.__find_storage_handlers(self.__directories)

    def __find_storage_handlers(self, directories, *, skip_trash=True):
        storage_handlers = list()
        absolute_file_paths = set()
        for directory in directories:
            for root, dirs, files in os.walk(directory):
                if not skip_trash or pathlib.Path(root).name != "trash":
                    for data_file in files:
                        if not data_file.startswith("."):
                            absolute_file_paths.add(os.path.join(root, data_file))
        for file_handler in self.__file_handlers:
            for data_file in filter(file_handler.is_matching, absolute_file_paths):
                try:
                    storage_handler = file_handler(data_file)
                    assert storage_handler.is_valid
                    storage_handlers.append(storage_handler)
                except Exception as e:
                    logging.error("Exception reading file: %s", data_file)
                    logging.error(str(e))
                    raise
        return storage_handlers

    def __get_base_path(self, data_item):
        data_item_uuid = data_item.uuid
        created_local = data_item.created_local
        session_id = data_item.session_id
        # data_item_uuid.bytes.encode('base64').rstrip('=\n').replace('/', '_')
        # and back: data_item_uuid = uuid.UUID(bytes=(slug + '==').replace('_', '/').decode('base64'))
        # also:
        def encode(uuid_, alphabet):
            result = str()
            uuid_int = uuid_.int
            while uuid_int:
                uuid_int, digit = divmod(uuid_int, len(alphabet))
                result += alphabet[digit]
            return result
        path_components = created_local.strftime("%Y-%m-%d").split('-')
        session_id = session_id if session_id else created_local.strftime("%Y%m%d-000000")
        path_components.append(session_id)
        encoded_base_path = "data_" + encode(data_item_uuid, "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")  # 25 character results
        path_components.append(encoded_base_path)
        return os.path.join(*path_components)

    def get_file_handler_for_file(self, path):
        for file_handler in self.__file_handlers:
            if file_handler.is_matching(path):
                return file_handler
        return None

    def make_storage_handler(self, data_item, file_handler=None):
        # if there are two handlers, first is small, second is large
        # if there is only one handler, it is used in all cases
        large_format = hasattr(data_item, "large_format") and data_item.large_format
        file_handler = file_handler if file_handler else (self.__file_handlers[-1] if large_format else self.__file_handlers[0])
        return file_handler.make(os.path.join(self.__directories[0], self.__get_base_path(data_item)))

    def remove_storage_handler(self, storage_handler, *, safe: bool=False) -> None:
        file_path = storage_handler.reference
        file_name = os.path.split(file_path)[1]
        trash_dir = os.path.join(self.__directories[0], "trash")
        new_file_path = os.path.join(trash_dir, file_name)
        storage_handler.close()  # moving files in the storage handler requires it to be closed.
        # TODO: move this functionality to the storage handler.
        if safe and not os.path.exists(new_file_path):
            os.makedirs(trash_dir, exist_ok=True)
            shutil.move(file_path, new_file_path)
        storage_handler.remove()

    def restore_storage_handler(self, data_item_uuid: uuid.UUID):
        data_item_uuid_str = str(data_item_uuid)
        trash_dir = os.path.join(self.__directories[0], "trash")
        storage_handlers = self.__find_storage_handlers([trash_dir], skip_trash=False)
        for storage_handler in storage_handlers:
            properties = storage_handler.read_properties()
            if properties.get("uuid", None) == data_item_uuid_str:
                data_item = DataItem.DataItem(item_uuid=data_item_uuid)
                data_item.begin_reading()
                data_item.read_from_dict(properties)
                data_item.finish_reading()
                old_file_path = storage_handler.reference
                new_file_path = storage_handler.make_path(os.path.join(self.__directories[0], self.__get_base_path(data_item)))
                if not os.path.exists(new_file_path):
                    os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
                    shutil.move(old_file_path, new_file_path)
                self.make_storage_handler(data_item, file_handler=None)
                return storage_handler.make(new_file_path)
        return None

    def purge_removed_storage_handlers(self):
        self.trash = dict()

    def prune(self):
        trash_dir = os.path.join(self.__directories[0], "trash")
        for root, dirs, files in os.walk(trash_dir):
            if pathlib.Path(root).name == "trash":
                for file in files:
                    # the date is not a reliable way of determining the age since a user may trash an old file. for now,
                    # we just delete anything in the trash at startup. future version may have an index file for
                    # tracking items in the trash. when items are again retained in the trash, update the disabled
                    # test_delete_and_undelete_from_file_storage_system_restores_data_item_after_reload
                    file_path = pathlib.Path(root) / pathlib.Path(file)
                    file_path.unlink()

    def register_data_item(self, item: DataItem, storage_handler, properties: dict) -> None:
        assert item not in self.__data_item_storage
        self.__data_item_storage[item] = DataItemStorageAdapter(self, storage_handler, item, properties)

    def unregister_data_item(self, item: DataItem) -> None:
        assert item in self.__data_item_storage
        self.__data_item_storage.pop(item).close()

    def __get_storage_for_item(self, item: DataItem) -> DataItemStorageAdapter:
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
        self.remove_storage_handler(storage._storage_handler, safe=safe)

    def set_write_delayed(self, data_item, write_delayed: bool) -> None:
        storage = self.__get_storage_for_item(data_item)
        storage.set_write_delayed(data_item, write_delayed)

    def is_write_delayed(self, data_item) -> bool:
        storage = self.__get_storage_for_item(data_item)
        return storage.is_write_delayed(data_item)

    def rewrite_item(self, data_item) -> None:
        storage = self.__get_storage_for_item(data_item)
        storage.rewrite_item(data_item)
