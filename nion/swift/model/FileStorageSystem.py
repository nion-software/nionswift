import copy
import json
import logging
import os.path
import pathlib
import shutil
import threading
import uuid

from nion.swift.model import DataItem
from nion.swift.model import HDF5Handler
from nion.swift.model import NDataHandler


class FilePersistentStorage:
    # this class is used to store the data for the library itself.
    # it is not used for library items.

    def __init__(self, filepath=None):
        self.__filepath = filepath
        self.__properties = self.__read_properties()
        self.__properties_lock = threading.RLock()

    def get_version(self):
        return 0

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

    def __write_properties(self):
        if self.__filepath:
            # atomically overwrite
            temp_filepath = self.__filepath + ".temp"
            with open(temp_filepath, "w") as fp:
                json.dump(self.__properties, fp)
            os.replace(temp_filepath, self.__filepath)

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


class FileStorageSystem:

    _file_handlers = [NDataHandler.NDataHandler, HDF5Handler.HDF5Handler]

    def __init__(self, file_path, directories):
        self.__directories = directories
        self.__file_handlers = FileStorageSystem._file_handlers
        self.__persistent_storage = FilePersistentStorage(file_path)

    @property
    def library_storage_properties(self):
        return self.__persistent_storage.properties

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
