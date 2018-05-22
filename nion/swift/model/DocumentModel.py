# standard libraries
import asyncio
import collections
import copy
import datetime
import functools
import gettext
import json
import logging
import numbers
import os.path
import pathlib
import shutil
import threading
import time
import typing
import uuid
import weakref

# third party libraries
import numpy
import scipy

# local libraries
from nion.data import Core
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import Cache
from nion.swift.model import Connection
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.swift.model import Graphics
from nion.swift.model import HardwareSource
from nion.swift.model import ImportExportManager
from nion.swift.model import Migration
from nion.swift.model import PlugInManager
from nion.swift.model import Symbolic
from nion.swift.model import Utility
from nion.swift.model import WorkspaceLayout
from nion.utils import Converter
from nion.utils import Event
from nion.utils import ListModel
from nion.utils import Observable
from nion.utils import Persistence
from nion.utils import Recorder
from nion.utils import ReferenceCounting
from nion.utils import ThreadPool

_ = gettext.gettext


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


class MemoryPersistentStorage:
    # this class is used to store the data for the library itself.
    # it is not used for library items.

    def __init__(self, properties=None):
        self.__properties = properties if properties else dict()
        self.__properties_lock = threading.RLock()

    def get_version(self):
        return 0

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

    def remove_item(self, parent, name, index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict[name]
            del item_list[index]
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

    def set_property(self, object, name, value):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict[name] = value

    def clear_property(self, object, name):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict.pop(name, None)


class DataItemPersistentStorage:
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
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
        self.write_delayed = False

    def close(self):
        if self.__storage_handler:
            self.__storage_handler.close()
            self.__storage_handler = None

    @property
    def data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None

    @data_item.setter
    def data_item(self, data_item):
        self.__weak_data_item = weakref.ref(data_item) if data_item else None

    @property
    def properties(self):
        with self.__properties_lock:
            return copy.deepcopy(self.__properties)

    @property
    def _storage_handler(self):
        return self.__storage_handler

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

    def update_properties(self):
        if not self.write_delayed:
            file_datetime = self.data_item.created_local
            self.__storage_handler.write_properties(self.properties, file_datetime)

    def insert_item(self, parent, name, before_index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict.setdefault(name, list())
            item_dict = item.write_to_dict()
            item_list.insert(before_index, item_dict)
            item.persistent_object_context = parent.persistent_object_context
        self.update_properties()

    def remove_item(self, parent, name, index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict[name]
            del item_list[index]
        self.update_properties()
        item.persistent_object_context = None

    def set_item(self, parent, name, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            if item:
                item_dict = item.write_to_dict()
                storage_dict[name] = item_dict
                item.persistent_object_context = None
                item.persistent_object_context = parent.persistent_object_context
            else:
                if name in storage_dict:
                    del storage_dict[name]
        self.update_properties()

    def update_data(self, data):
        if not self.write_delayed:
            file_datetime = self.data_item.created_local
            if data is not None:
                self.__storage_handler.write_data(data, file_datetime)

    def load_data(self):
        assert self.data_item.has_data
        return self.__storage_handler.read_data()

    def set_property(self, object, name, value):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict[name] = value
        self.update_properties()

    def clear_property(self, object, name):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict.pop(name, None)
        self.update_properties()

    def remove(self, safe: bool=False) -> None:
        self.__storage_system.remove_storage_handler(self.__storage_handler, safe=safe)


class MemoryStorageSystem:

    def __init__(self):
        self.data = dict()
        self.properties = dict()
        self.trash = dict()
        self._test_data_read_event = Event.Event()

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

    def find_data_items(self):
        storage_handlers = list()
        for key in sorted(self.properties):
            self.properties[key].setdefault("uuid", str(uuid.uuid4()))
            storage_handlers.append(MemoryStorageSystem.MemoryStorageHandler(key, self.properties, self.data, self._test_data_read_event))
        return storage_handlers

    def make_storage_handler(self, data_item, file_handler=None):
        data_item_uuid_str = str(data_item.uuid)
        return MemoryStorageSystem.MemoryStorageHandler(data_item_uuid_str, self.properties, self.data, self._test_data_read_event)

    def remove_storage_handler(self, storage_handler, *, safe: bool=False) -> None:
        storage_handler_reference = storage_handler.reference
        data = self.data.pop(storage_handler_reference, None)
        properties = self.properties.pop(storage_handler_reference)
        if safe:
            assert storage_handler_reference not in self.trash
            self.trash[storage_handler_reference] = {"data": data, "properties": properties}

    def restore_storage_handler(self, data_item_uuid: uuid.UUID):
        data_item_uuid_str = str(data_item_uuid)
        trash_entry = self.trash.pop(data_item_uuid_str)
        assert data_item_uuid_str not in self.properties
        assert data_item_uuid_str not in self.data
        self.properties[data_item_uuid_str] = trash_entry["properties"]
        self.data[data_item_uuid_str] = trash_entry["data"]
        return MemoryStorageSystem.MemoryStorageHandler(data_item_uuid_str, self.properties, self.data, self._test_data_read_event)

    def purge_removed_storage_handlers(self):
        self.trash = dict()

    def prune(self):
        pass


from nion.swift.model import NDataHandler
from nion.swift.model import HDF5Handler

class FileStorageSystem:

    _file_handlers = [NDataHandler.NDataHandler, HDF5Handler.HDF5Handler]

    def __init__(self, directories):
        self.__directories = directories
        self.__file_handlers = FileStorageSystem._file_handlers

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

def read_data_items_version_stats(persistent_storage_system):
    storage_handlers = list()  # storage_handler
    storage_handlers.extend(persistent_storage_system.find_data_items())
    count = [0, 0, 0]  # data item matches version, data item has higher version, data item has lower version
    writer_version = DataItem.DataItem.writer_version
    for storage_handler in storage_handlers:
        properties = storage_handler.read_properties()
        version = properties.get("version", 0)
        if version < writer_version:
            count[2] += 1
        elif version > writer_version:
            count[1] += 1
        else:
            count[0] += 1
    return count


def read_data_items(library_storage_properties, persistent_storage_system, ignore_older_files, log_migrations):
    """Read data items from the data reference handler and return as a list.

    Data items will have persistent_object_context set upon return, but caller will need to call finish_reading
    on each of the data items.
    """
    storage_handlers = persistent_storage_system.find_data_items()
    data_items_by_uuid = dict()
    ReaderInfo = collections.namedtuple("ReaderInfo", ["properties", "changed_ref", "storage_handler"])
    reader_info_list = list()
    for storage_handler in storage_handlers:
        try:
            reader_info_list.append(ReaderInfo(storage_handler.read_properties(), [False], storage_handler))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()
    library_updates = dict()
    if not ignore_older_files:
        migration_log = Migration.MigrationLog(log_migrations)
        Migration.migrate_to_latest(reader_info_list, library_updates, migration_log)
    for reader_info in reader_info_list:
        properties = reader_info.properties
        properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
        changed_ref = reader_info.changed_ref
        storage_handler = reader_info.storage_handler
        try:
            version = properties.get("version", 0)
            if version == DataItem.DataItem.writer_version:
                data_item_uuid = uuid.UUID(properties["uuid"])
                if changed_ref[0]:
                    storage_handler.write_properties(copy.deepcopy(properties), datetime.datetime.now())
                # NOTE: Search for to-do 'file format' to gather together 'would be nice' changes
                # NOTE: change writer_version in DataItem.py
                if len(properties.get("data_item_uuids", list())) > 0:
                    data_item = DataItem.CompositeLibraryItem(item_uuid=data_item_uuid)
                else:
                    large_format = isinstance(storage_handler, HDF5Handler.HDF5Handler)
                    data_item = DataItem.DataItem(item_uuid=data_item_uuid, large_format=large_format)
                data_item.begin_reading()
                data_item.read_from_dict(properties)
                # persistent storage facilitates writing properties and relationships to the storage handler
                persistent_storage = DataItemPersistentStorage(persistent_storage_system, storage_handler, data_item, properties)
                data_item.persistent_storage = persistent_storage
                if log_migrations and data_item.uuid in data_items_by_uuid:
                    logging.info("Warning: Duplicate data item %s", data_item.uuid)
                data_items_by_uuid[data_item.uuid] = data_item
                library_update = library_updates.get(data_item_uuid, dict())
                library_storage_properties.setdefault("connections", list()).extend(library_update.get("connections", list()))
                library_storage_properties.setdefault("computations", list()).extend(library_update.get("computations", list()))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

    def sort_by_date_key(data_item):
        return data_item.created

    data_items = list(data_items_by_uuid.values())
    data_items.sort(key=sort_by_date_key)
    return data_items


def auto_migrate_data_item(reader_info, persistent_storage_system, migration_log: Migration.MigrationLog) -> DataItem.LibraryItem:
    properties = reader_info.properties
    properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
    storage_handler = reader_info.storage_handler
    data_item_uuid = uuid.UUID(properties["uuid"])
    new_data_item = None
    target_storage_handler = None
    # create a temporary data item that can be used to get the new file reference
    old_data_item = DataItem.DataItem(item_uuid=data_item_uuid)
    old_data_item.begin_reading()
    old_data_item.read_from_dict(properties)
    old_data_item.finish_reading()
    old_data_item_path = storage_handler.reference
    # ask the storage system for the file handler for the data item path
    file_handler = persistent_storage_system.get_file_handler_for_file(old_data_item_path)
    # ask the storage system to make a storage handler (an instance of a file handler) for the data item
    # this ensures that the storage handler (file format) is the same as before.
    target_storage_handler = persistent_storage_system.make_storage_handler(old_data_item, file_handler)
    if target_storage_handler:
        os.makedirs(os.path.dirname(target_storage_handler.reference), exist_ok=True)
        shutil.copyfile(storage_handler.reference, target_storage_handler.reference)
        target_storage_handler.write_properties(copy.deepcopy(properties), datetime.datetime.now())
        new_data_item = DataItem.DataItem(item_uuid=data_item_uuid)
        new_data_item.begin_reading()
        new_data_item.read_from_dict(properties)
        # persistent storage facilitates writing properties and relationships to the storage handler
        persistent_storage = DataItemPersistentStorage(persistent_storage_system, target_storage_handler, new_data_item, properties)
        new_data_item.persistent_storage = persistent_storage
        migration_log.push("Copying data item {} to library.".format(data_item_uuid))
    else:
        migration_log.push("Unable to copy data item %s to library.".format(data_item_uuid))
    return new_data_item


def auto_migrate_storage_system(library_storage_properties, *, persistent_storage_system=None, new_persistent_storage_system=None, data_item_uuids=None, deletions: typing.Set[uuid.UUID] = None, utilized_deletions: typing.Set[uuid.UUID] = None):
    """Migrate items from the storage system to the object context.

    Files in data_item_uuids have already been loaded and are ignored (not migrated).

    Files in deletes have been deleted in object context and are ignored (not migrated) and then added
    to the utilized deletions list.

    Data items will have persistent_object_context set upon return, but caller will need to call finish_reading
    on each of the data items.
    """
    storage_handlers = persistent_storage_system.find_data_items()
    data_items_by_uuid = dict()
    ReaderInfo = collections.namedtuple("ReaderInfo", ["properties", "changed_ref", "storage_handler"])
    reader_info_list = list()
    for storage_handler in storage_handlers:
        try:
            reader_info_list.append(ReaderInfo(storage_handler.read_properties(), [False], storage_handler))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()
    library_updates = dict()
    migration_log = Migration.MigrationLog(False)
    Migration.migrate_to_latest(reader_info_list, library_updates, migration_log)
    for reader_info in reader_info_list:
        properties = reader_info.properties
        storage_handler = reader_info.storage_handler
        try:
            version = properties.get("version", 0)
            if version == DataItem.DataItem.writer_version:
                data_item_uuid = uuid.UUID(properties["uuid"])
                if not data_item_uuid in data_item_uuids:
                    if str(data_item_uuid) in deletions:
                        utilized_deletions.add(data_item_uuid)
                    else:
                        new_data_item = auto_migrate_data_item(reader_info, new_persistent_storage_system, migration_log)
                        if new_data_item:
                            data_items_by_uuid[data_item_uuid] = new_data_item
                            library_update = library_updates.get(data_item_uuid, dict())
                            library_storage_properties.setdefault("connections", list()).extend(library_update.get("connections", list()))
                            library_storage_properties.setdefault("computations", list()).extend(library_update.get("computations", list()))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

    def sort_by_date_key(data_item):
        return data_item.created

    data_items = list(data_items_by_uuid.values())
    data_items.sort(key=sort_by_date_key)
    return data_items


class ComputationQueueItem:
    def __init__(self, *, data_item=None, computation=None):
        self.computation = computation
        self.data_item = data_item
        self.valid = True

    def recompute(self) -> typing.Optional[typing.Tuple[Symbolic.Computation, typing.Callable[[], None]]]:
        # evaluate the computation in a thread safe manner
        # returns a list of functions that must be called on the main thread to finish the recompute action
        # threadsafe
        pending_data_item_merge = None
        data_item = None
        computation = self.computation
        if computation.expression:
            data_item = computation.get_referenced_object("target")
        if computation and computation.needs_update:
            try:
                api = PlugInManager.api_broker_fn("~1.0", None)
                if not data_item:
                    compute_obj, error_text = computation.evaluate(api)
                    if error_text and computation.error_text != error_text:
                        def update_error_text():
                            computation.error_text = error_text
                        pending_data_item_merge = (computation, update_error_text)
                        return pending_data_item_merge
                    throttle_time = max(DocumentModel.computation_min_period - (time.perf_counter() - computation.last_evaluate_data_time), 0)
                    time.sleep(max(throttle_time, 0.0))
                    if self.valid and compute_obj:  # TODO: race condition for 'valid'
                        pending_data_item_merge = (computation, functools.partial(compute_obj.commit))
                    else:
                        pending_data_item_merge = (computation, None)
                else:
                    data_item_clone = data_item.clone()
                    data_item_data_modified = data_item.data_modified or datetime.datetime.min
                    data_item_clone_recorder = Recorder.Recorder(data_item_clone)
                    api_data_item = api._new_api_object(data_item_clone)
                    error_text = computation.evaluate_with_target(api, api_data_item)
                    throttle_time = max(DocumentModel.computation_min_period - (time.perf_counter() - computation.last_evaluate_data_time), 0)
                    time.sleep(max(throttle_time, 0.0))
                    if self.valid:  # TODO: race condition for 'valid'
                        def data_item_merge(data_item, data_item_clone, data_item_clone_recorder):
                            # merge the result item clones back into the document. this method is guaranteed to run at
                            # periodic and shouldn't do anything too time consuming.
                            data_item_data_clone_modified = data_item_clone.data_modified or datetime.datetime.min
                            with data_item.data_item_changes(), data_item.data_source_changes():
                                if data_item_data_clone_modified > data_item_data_modified:
                                    data_item.set_xdata(api_data_item.data_and_metadata)
                                data_item_clone_recorder.apply(data_item)
                                if computation.error_text != error_text:
                                    computation.error_text = error_text
                        pending_data_item_merge = (computation, functools.partial(data_item_merge, data_item, data_item_clone, data_item_clone_recorder))
            except Exception as e:
                import traceback
                traceback.print_exc()
                # computation.error_text = _("Unable to compute data")
        return pending_data_item_merge


class AutoMigration:
    def __init__(self, paths: typing.List[str]=None, log_copying: bool=True, storage_system=None):
        self.paths = paths
        self.log_copying = log_copying
        self.storage_system = storage_system


class DataStructure(Observable.Observable, Persistence.PersistentObject):
    # regarding naming: https://en.wikipedia.org/wiki/Passive_data_structure
    def __init__(self, *, structure_type: str=None, source=None):
        super().__init__()
        self.__container_weak_ref = None
        self.about_to_be_removed_event = Event.Event()
        self._about_to_be_removed = False
        self._closed = False
        self.__properties = dict()
        self.__referenced_objects = dict()
        self.define_type("data_structure")
        self.define_property("structure_type", structure_type)
        self.define_property("source_uuid", converter=Converter.UuidToStringConverter())
        # properties is handled explicitly
        self.data_structure_changed_event = Event.Event()
        self.referenced_objects_changed_event = Event.Event()
        self.__source = source
        if source is not None:
            self.source_uuid = source.uuid

    def close(self):
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None

    def __getattr__(self, name):
        properties = self.__dict__.get("_DataStructure__properties", dict())
        if name in properties:
            return properties[name]
        return super().__getattr__(name)

    def __setattr__(self, name, value):
        properties = self.__dict__.get("_DataStructure__properties", dict())
        if name in properties:
            if value is not None:
                self.set_property_value(name, value)
            else:
                self.remove_property_value(name)
        else:
            super().__setattr__(name, value)

    @property
    def container(self):
        return self.__container_weak_ref()

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        self.about_to_be_removed_event.fire()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True
        self.__container_weak_ref = None

    def insert_model_item(self, container, name, before_index, item):
        if self.__container_weak_ref:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        if self.__container_weak_ref:
            return self.container.remove_model_item(container, name, item, safe=safe)
        else:
            container.remove_item(name, item)
            return None

    def read_from_dict(self, properties):
        super().read_from_dict(properties)
        self.__properties = properties.get("properties")

    def write_to_dict(self):
        properties = super().write_to_dict()
        properties["properties"] = copy.deepcopy(self.__properties)
        return properties

    @property
    def source(self):
        return self.__source

    @source.setter
    def source(self, source):
        self.__source = source
        self.source_uuid = source.uuid if source else None

    def persistent_object_context_changed(self):
        """ Override from PersistentObject. """
        super().persistent_object_context_changed()

        def source_registered(source):
            self.__source = source

        def source_unregistered(source=None):
            pass

        def reference_registered(property_name, reference):
            self.__referenced_objects[property_name] = reference

        def reference_unregistered(property_name, reference=None):
            pass

        if self.persistent_object_context:
            self.persistent_object_context.subscribe(self.source_uuid, source_registered, source_unregistered)

            for property_name, value in self.__properties.items():
                if isinstance(value, dict) and value.get("type") in {"data_item", "region", "structure"} and "uuid" in value:
                    self.persistent_object_context.subscribe(uuid.UUID(value["uuid"]), functools.partial(reference_registered, property_name), functools.partial(reference_unregistered, property_name))
        else:
            source_unregistered()

            for property_name, value in self.__properties.items():
                if isinstance(value, dict) and value.get("type") in {"data_item", "region", "structure"} and "uuid" in value:
                    reference_unregistered(property_name)

    def set_property_value(self, property: str, value) -> None:
        self.__properties[property] = value
        self.__referenced_objects.pop(property, None)
        self.data_structure_changed_event.fire(property)
        self.property_changed_event.fire(property)
        self._update_persistent_property("properties", self.__properties)

    def remove_property_value(self, property: str) -> None:
        if property in self.__properties:
            self.__properties.pop(property)
            self.__referenced_objects.pop(property, None)
            self.data_structure_changed_event.fire(property)
            self.property_changed_event.fire(property)
            self._update_persistent_property("properties", self.__properties)

    def get_property_value(self, property: str, default_value=None):
        return self.__properties.get(property, default_value)

    def set_referenced_object(self, property: str, item) -> None:
        assert item is not None
        if item != self.__referenced_objects.get(property):
            self.__properties[property] = get_object_specifier(item)
            self.data_structure_changed_event.fire(property)
            self.property_changed_event.fire(property)
            self._update_persistent_property("properties", self.__properties)
            self.__referenced_objects[property] = item
            self.referenced_objects_changed_event.fire()

    def remove_referenced_object(self, property: str) -> None:
        self.remove_property_value(property)

    def get_referenced_object(self, property: str):
        return self.__referenced_objects.get(property)

    @property
    def _referenced_objects(self):
        return self.__referenced_objects.values()


def computation_factory(lookup_id):
    return Symbolic.Computation()


def data_structure_factory(lookup_id):
    return DataStructure()


def get_object_specifier(object, object_type: str=None) -> typing.Optional[typing.Mapping]:
    if isinstance(object, DataItem.DataItem) and object_type == "data_item":
        return {"version": 1, "type": "data_item_object", "uuid": str(object.uuid)}
    if isinstance(object, DataItem.DataItem) and object_type in ("xdata", "display_xdata", "cropped_xdata", "cropped_display_xdata", "filter_xdata", "filtered_xdata"):
        return {"version": 1, "type": object_type, "uuid": str(object.uuid)}
    if isinstance(object, DataItem.DataItem):
        # should be "data_source" but requires file format change
        return {"version": 1, "type": "data_item", "uuid": str(object.uuid)}
    elif isinstance(object, Graphics.Graphic):
        return {"version": 1, "type": "region", "uuid": str(object.uuid)}
    elif isinstance(object, DataStructure):
        return {"version": 1, "type": "structure", "uuid": str(object.uuid)}
    return None


class Transaction:
    def __init__(self, transaction_manager: "TransactionManager", item, items):
        self.__transaction_manager = transaction_manager
        self.__item = item
        self.__items = items

    def close(self):
        self.__transaction_manager._close_transaction(self)
        self.__items = None
        self.__transaction_manager = None

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    @property
    def item(self):
        return self.__item

    @property
    def items(self):
        return copy.copy(self.__items)

    def replace_items(self, items):
        self.__items = items


class TransactionManager:
    def __init__(self, document_model: "DocumentModel"):
        self.__document_model = document_model
        self.__transactions_lock = threading.RLock()
        self.__transaction_counts = collections.Counter()
        self.__transactions = list()

    def close(self):
        self.__document_model = None
        self.__transaction_counts = None

    def is_in_transaction_state(self, item) -> bool:
        return self.__transaction_counts[item] > 0

    @property
    def transaction_count(self):
        return len(list(self.__transaction_counts.elements()))

    def item_transaction(self, item) -> Transaction:
        """Begin transaction state for item.

        A transaction state is exists to prevent writing out to disk, mainly for performance reasons.
        All changes to the object are delayed until the transaction state exits.

        This method is thread safe.
        """
        items = self.__build_transaction_items(item)
        transaction = Transaction(self, item, items)
        self.__transactions.append(transaction)
        return transaction

    def _close_transaction(self, transaction):
        items = transaction.items
        self.__close_transaction_items(items)
        self.__transactions.remove(transaction)

    def __build_transaction_items(self, item):
        items = set()
        self.__get_deep_transaction_item_set(item, items)
        with self.__transactions_lock:
            for item in items:
                old_count = self.__transaction_counts[item]
                self.__transaction_counts.update({item})
                if old_count == 0:
                    if callable(getattr(item, "_transaction_state_entered", None)):
                        item._transaction_state_entered()
        return items

    def __close_transaction_items(self, items):
        with self.__transactions_lock:
            for item in items:
                self.__transaction_counts.subtract({item})
                if self.__transaction_counts[item] == 0:
                    if callable(getattr(item, "_transaction_state_exited", None)):
                        item._transaction_state_exited()

    def __get_deep_transaction_item_set(self, item, items):
        if not item in items:
            # first the dependent items, also keep track of which items are added
            old_items = copy.copy(items)
            self.__get_deep_dependent_item_set(item, items)
            # next, the graphics and connections (where item is source)
            if isinstance(item, DataItem.LibraryItem):
                for display in item.displays:
                    for graphic in display.graphics:
                        self.__get_deep_transaction_item_set(graphic, items)
            if isinstance(item, DataStructure):
                for referenced_object in item._referenced_objects:
                    self.__get_deep_dependent_item_set(referenced_object, items)
            if isinstance(item, Connection.Connection):
                self.__get_deep_dependent_item_set(item._source, items)
                self.__get_deep_dependent_item_set(item._target, items)
            for connection in self.__document_model.connections:
                if isinstance(connection, Connection.PropertyConnection) and connection._source in items:
                    self.__get_deep_transaction_item_set(connection._target, items)
                if isinstance(connection, Connection.PropertyConnection) and connection._target in items:
                    self.__get_deep_transaction_item_set(connection._source, items)
            for item in items - old_items:
                if isinstance(item, Graphics.Graphic):
                    self.__get_deep_transaction_item_set(item.container.container, items)

    def __get_deep_dependent_item_set(self, item, item_set) -> None:
        """Return the list of data items containing data that directly depends on data in this item."""
        if not item in item_set:
            item_set.add(item)
            for dependent in self.__document_model.get_dependent_items(item):
                self.__get_deep_dependent_item_set(dependent, item_set)

    def _add_item(self, item):
        self._rebuild_transactions()

    def _remove_item(self, item):
        for transaction in copy.copy(self.__transactions):
            if transaction.item == item:
                self._close_transaction(transaction)
        self._rebuild_transactions()

    def _rebuild_transactions(self):
        for transaction in self.__transactions:
            old_items = transaction.items
            new_items = self.__build_transaction_items(transaction.item)
            transaction.replace_items(new_items)
            self.__close_transaction_items(old_items)


class DocumentModel(Observable.Observable, ReferenceCounting.ReferenceCounted, Persistence.PersistentObject, DataItem.SessionManager):

    """The document model manages storage and dependencies between data items and other objects.

    The document model provides a dispatcher object which will run tasks in a thread pool.
    """

    computation_min_period = 0.0

    def __init__(self, library_storage=None, persistent_storage_system=None, storage_cache=None, log_migrations=True, ignore_older_files=False, auto_migrations=None):
        super().__init__()

        self.library_item_will_be_removed_event = Event.Event()  # will be called before the item is deleted
        self.data_item_inserted_event = Event.Event()
        self.data_item_removed_event = Event.Event()

        self.dependency_added_event = Event.Event()
        self.dependency_removed_event = Event.Event()
        self.related_items_changed = Event.Event()

        self.computation_updated_event = Event.Event()

        self.__thread_pool = ThreadPool.ThreadPool()
        self.__computation_thread_pool = ThreadPool.ThreadPool()
        self.__persistent_storage_system = persistent_storage_system if persistent_storage_system else MemoryStorageSystem()
        self.__ignore_older_files = ignore_older_files
        self.__log_migrations = log_migrations
        self.persistent_object_context = Persistence.PersistentObjectContext()
        self.__library_storage = library_storage if library_storage else FilePersistentStorage()
        self.persistent_object_context._set_persistent_storage_for_object(self, self.__library_storage)
        self.storage_cache = storage_cache if storage_cache else Cache.DictStorageCache()
        self.__auto_migrations = auto_migrations or list()
        self.__transaction_manager = TransactionManager(self)
        self.__data_structure_listeners = dict()
        self.__live_data_items_lock = threading.RLock()
        self.__live_data_items = dict()
        self.__dependency_tree_lock = threading.RLock()
        self.__dependency_tree_source_to_target_map = dict()
        self.__dependency_tree_target_to_source_map = dict()
        self.__data_items = list()
        self.__uuid_to_data_item = dict()
        self.__computation_changed_listeners = dict()
        self.__computation_output_changed_listeners = dict()
        self.__data_item_references = dict()
        self.__computation_queue_lock = threading.RLock()
        self.__computation_pending_queue = list()  # type: typing.List[ComputationQueueItem]
        self.__computation_active_item = None  # type: ComputationQueueItem
        self.define_type("library")
        self.define_relationship("data_groups", DataGroup.data_group_factory)
        self.define_relationship("workspaces", WorkspaceLayout.factory)
        self.define_relationship("computations", computation_factory, insert=self.__inserted_computation, remove=self.__removed_computation)
        self.define_relationship("data_structures", data_structure_factory, insert=self.__inserted_data_structure, remove=self.__removed_data_structure)
        self.define_relationship("connections", Connection.connection_factory, insert=self.__inserted_connection, remove=self.__removed_connection)
        self.define_property("session_metadata", dict(), copy_on_read=True, changed=self.__session_metadata_changed)
        self.define_property("workspace_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("data_item_references", dict(), hidden=True)  # map string key to data item, used for data acquisition channels
        self.define_property("data_item_variables", dict(), hidden=True)  # map string key to data item, used for reference in scripts
        self.define_property("data_item_deletions", list(), hidden=True)  # list of deleted uuids. usefor for migration.
        self.session_id = None
        self.start_new_session()
        self.__prune()
        self.__read()
        self.__library_storage.set_property(self, "uuid", str(self.uuid))
        self.__library_storage.set_property(self, "version", 0)

        self.displays_list_model = ListModel.FlattenedListModel(container=self, master_items_key="data_items", child_items_key="displays")

        self.__data_channel_updated_listeners = dict()
        self.__data_channel_start_listeners = dict()
        self.__data_channel_stop_listeners = dict()
        self.__data_channel_states_updated_listeners = dict()
        self.__last_data_items_dict = dict()  # maps hardware source to list of data items for that hardware source

        self.__hardware_source_call_soon_event_listeners = dict()

        self.__pending_data_item_updates_lock = threading.RLock()
        self.__pending_data_item_updates = list()

        self.__pending_data_item_merge_lock = threading.RLock()
        self.__pending_data_item_merge = None
        self.__current_computation = None

        self.call_soon_event = Event.Event()

        self.__hardware_source_added_event_listener = HardwareSource.HardwareSourceManager().hardware_source_added_event.listen(self.__hardware_source_added)
        self.__hardware_source_removed_event_listener = HardwareSource.HardwareSourceManager().hardware_source_removed_event.listen(self.__hardware_source_removed)

        for hardware_source in HardwareSource.HardwareSourceManager().hardware_sources:
            self.__hardware_source_added(hardware_source)

    def __prune(self):
        self.__persistent_storage_system.prune()

    def __read(self):
        # first read the library (for deletions) and the library items from the primary storage systems
        library_storage_properties = self.__library_storage.properties
        data_items = read_data_items(library_storage_properties, self.__persistent_storage_system, self.__ignore_older_files, self.__log_migrations)
        data_item_uuids = {data_item.uuid for data_item in data_items}
        utilized_deletions = set()  # the uuid's skipped due to being deleted
        deletions = library_storage_properties.get("data_item_deletions", list())
        # next, for each auto migration, create a temporary storage system and read items from that storage system
        # using auto_migrate_storage_system. the data items returned will have been copied to the current storage
        # system (persistent object context).
        for auto_migration in self.__auto_migrations:
            file_persistent_storage_system = FileStorageSystem(auto_migration.paths) if auto_migration.paths else auto_migration.storage_system
            new_data_items = auto_migrate_storage_system(library_storage_properties,
                                                         persistent_storage_system=file_persistent_storage_system,
                                                         new_persistent_storage_system=self.__persistent_storage_system,
                                                         data_item_uuids=data_item_uuids,
                                                         deletions=deletions,
                                                         utilized_deletions=utilized_deletions)
            data_items.extend(new_data_items)
            data_item_uuids.update({data_item.uuid for data_item in new_data_items})
        for data_item in data_items:
            self.persistent_object_context._set_persistent_storage_for_object(data_item, data_item.persistent_storage)
            data_item.persistent_object_context = self.persistent_object_context
        self.__library_storage.rewrite_properties(library_storage_properties)
        self.begin_reading()
        try:
            self.read_from_dict(library_storage_properties)
            self.__finish_read_partial(data_items)
            self.__finish_read(utilized_deletions)
        finally:
            self.finish_reading()

    def __finish_read_partial(self, data_items: typing.List[DataItem.DataItem]) -> None:
        for index, data_item in enumerate(data_items):
            if data_item.uuid not in self.__uuid_to_data_item:
                data_item.about_to_be_inserted(self)
                self.__data_items.insert(index, data_item)
                self.__uuid_to_data_item[data_item.uuid] = data_item
                data_item.set_storage_cache(self.storage_cache)
                data_item.set_session_manager(self)
        # all sorts of interconnections may occur between data items and other objects. give the data item a chance to
        # mark itself clean after reading all of them in.
        for data_item in data_items:
            data_item.finish_reading()

    def __finish_read(self, utilized_deletions: typing.Set[uuid.UUID]) -> None:
        # deletions
        self._set_persistent_property_value("data_item_deletions", [str(uuid_) for uuid_ in utilized_deletions])
        # computations and connections
        data_items = self.data_items
        for data_item in data_items:
            self.__data_item_computation_changed(data_item, None, None)  # set up initial computation listeners
        for data_item in data_items:
            data_item.connect_data_items(self.get_data_item_by_uuid)
        # this loop reestablishes dependencies now that everything is loaded.
        # the change listener for the computation will already have been established via the regular
        # loading mechanism; but because some data items may not have been loaded at the first time computation
        # changed was called (during insert computation), this call is made to update the dependencies.
        for computation in self.computations:
            computation.update_script(self._processing_descriptions)
            self.__computation_changed(computation)
            computation.bind(self)
        # initialize data item references
        data_item_references_dict = self._get_persistent_property_value("data_item_references")
        for key, data_item_uuid in data_item_references_dict.items():
            data_item = self.get_data_item_by_uuid(uuid.UUID(data_item_uuid))
            if data_item:
                self.__data_item_references.setdefault(key, DocumentModel.DataItemReference(self, key, data_item))
        # all data items will already have a persistent_object_context
        for data_group in self.data_groups:
            data_group.connect_data_items(self.get_data_item_by_uuid)
        # handle the reference variable assignments
        data_item_variables = self._get_persistent_property_value("data_item_variables")
        new_data_item_variables = dict()
        for r_var, data_item_uuid_str in data_item_variables.items():
            data_item_uuid = uuid.UUID(data_item_uuid_str)
            if data_item_uuid in self.__uuid_to_data_item:
                new_data_item_variables[r_var] = data_item_uuid_str
                data_item = self.__uuid_to_data_item[data_item_uuid]
                data_item.set_r_value(r_var, notify_changed=False)
        self._set_persistent_property_value("data_item_variables", new_data_item_variables)

    def close(self):
        # stop computations
        with self.__computation_queue_lock:
            self.__computation_pending_queue.clear()
            if self.__computation_active_item:
                self.__computation_active_item.valid = False
                self.__computation_active_item = None

        # close connections
        for connection in copy.copy(self.connections):
            connection.about_to_be_removed()
        for connection in copy.copy(self.connections):
            connection.close()

        # close hardware source related stuff
        self.__hardware_source_added_event_listener.close()
        self.__hardware_source_added_event_listener = None
        self.__hardware_source_removed_event_listener.close()
        self.__hardware_source_removed_event_listener = None
        for listener in self.__data_channel_states_updated_listeners.values():
            listener.close()
        self.__data_channel_states_updated_listeners = None
        # TODO: close other listeners here too
        HardwareSource.HardwareSourceManager().abort_all_and_close()

        # make sure the data item references shut down cleanly
        for data_item in self.data_items:
            for data_item_reference in self.__data_item_references.values():
                data_item_reference.data_item_removed(data_item)

        for listeners in self.__data_channel_updated_listeners.values():
            for listener in listeners:
                listener.close()
        for listeners in self.__data_channel_start_listeners.values():
            for listener in listeners:
                listener.close()
        for listeners in self.__data_channel_stop_listeners.values():
            for listener in listeners:
                listener.close()
        self.__data_channel_updated_listeners = None
        self.__data_channel_start_listeners = None
        self.__data_channel_stop_listeners = None

        self.__thread_pool.close()
        self.__computation_thread_pool.close()
        self.displays_list_model.close()
        self.displays_list_model = None
        for data_item in self.data_items:
            data_item.about_to_close()
        for data_item in self.data_items:
            data_item.about_to_be_removed()
        for data_item in self.data_items:
            data_item.close()
        self.storage_cache.close()
        self.__transaction_manager.close()
        self.__transaction_manager = None

    def __call_soon(self, fn):
        self.call_soon_event.fire_any(fn)

    def about_to_delete(self):
        # override from ReferenceCounted. several DocumentControllers may retain references
        self.close()
        # these are here so that the document model gets garbage collected.
        # TODO: generalize this behavior into a close method on persistent object
        self.undefine_properties()
        self.undefine_items()
        self.undefine_relationships()

    @property
    def _s2tm(self):
        return self.__dependency_tree_source_to_target_map

    @property
    def _t2sm(self):
        return self.__dependency_tree_target_to_source_map

    def start_new_session(self):
        self.session_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    def __session_metadata_changed(self, name, value):
        self.notify_property_changed("session_metadata")

    def has_session_field(self, field_id: str) -> bool:
        return field_id in self.session_metadata

    def set_session_field(self, field_id: str, value: str) -> None:
        session_metadata = self.session_metadata
        session_metadata[field_id] = str(value)
        self.session_metadata = session_metadata

    def get_session_field(self, field_id: str) -> str:
        return self.session_metadata.get(field_id)

    def delete_session_field(self, field_id: str) -> None:
        session_metadata = self.session_metadata
        session_metadata.pop(field_id, None)
        self.session_metadata = session_metadata

    @property
    def current_session_id(self):
        return self.session_id

    def append_workspace(self, workspace):
        self.insert_workspace(len(self.workspaces), workspace)

    def insert_workspace(self, before_index, workspace):
        self.insert_item("workspaces", before_index, workspace)
        self.notify_insert_item("workspaces", workspace, before_index)

    def remove_workspace(self, workspace):
        index = self.workspaces.index(workspace)
        self.remove_item("workspaces", workspace)
        self.notify_remove_item("workspaces", workspace, index)

    def copy_data_item(self, data_item: DataItem.DataItem) -> DataItem.DataItem:
        computation_copy = copy.deepcopy(self.get_data_item_computation(data_item))
        data_item_copy = copy.deepcopy(data_item)
        self.append_data_item(data_item_copy)
        if computation_copy:
            computation_copy.source = None
            computation_copy._clear_referenced_object("target")
            computation_copy.bind(self)
            self.set_data_item_computation(data_item_copy, computation_copy)
        return data_item_copy

    def append_data_item(self, data_item):
        self.insert_data_item(len(self.data_items), data_item)

    def insert_data_item(self, before_index, data_item):
        """Insert a new data item into document model.

        Data item will have persistent_object_context set upon return.

        This method is NOT threadsafe.
        """
        assert data_item is not None
        assert data_item not in self.__data_items
        assert before_index <= len(self.__data_items) and before_index >= 0
        assert data_item.uuid not in self.__uuid_to_data_item
        # ensure the data item has a new persistent storage
        assert not data_item.persistent_storage
        storage_handler = self.__persistent_storage_system.make_storage_handler(data_item)
        properties = data_item.write_to_dict()
        do_write = True
        # update the session
        data_item.session_id = self.session_id
        # insert in internal list
        self.__insert_data_item(before_index, data_item, storage_handler, properties, do_write)

    def __insert_data_item(self, before_index, data_item, storage_handler, properties, do_write):
        data_item.about_to_be_inserted(self)
        self.__data_items.insert(before_index, data_item)
        self.__uuid_to_data_item[data_item.uuid] = data_item
        data_item.set_storage_cache(self.storage_cache)
        data_item.persistent_object_context = self.persistent_object_context
        # persistent storage facilitates writing properties and relationships to the storage handler
        # persistent object context tracks the persistent storage for each object in the system
        persistent_storage = DataItemPersistentStorage(self.__persistent_storage_system, storage_handler, data_item,
                                                       properties)
        data_item.persistent_storage = persistent_storage
        data_item.persistent_object_context._set_persistent_storage_for_object(data_item, persistent_storage)
        data_item.persistent_object_context_changed()
        if do_write and persistent_storage and not persistent_storage.write_delayed:
            # don't directly write data item, or else write_pending is not cleared on data item
            # call finish pending write instead
            data_item._finish_pending_write()  # initially write to disk
        self.__data_item_computation_changed(data_item, None, None)  # set up initial computation listeners
        data_item.connect_data_items(self.get_data_item_by_uuid)
        data_item.set_session_manager(self)
        self.data_item_inserted_event.fire(self, data_item, before_index, False)
        self.notify_insert_item("data_items", data_item, before_index)
        for data_item_reference in self.__data_item_references.values():
            data_item_reference.data_item_inserted(data_item)
        self.__rebind_computations()  # rebind any unresolved that may now be resolved
        self.__transaction_manager._add_item(data_item)

    def __rebind_computations(self):
        for computation in self.computations:
            if not computation.is_resolved:
                computation.unbind()
                computation.bind(self)
                if computation.is_resolved:
                    computation.mark_update()

    def remove_data_item(self, library_item: DataItem.LibraryItem, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        """Remove data item from document model.

        Data item will have persistent_object_context cleared upon return.

        This method is NOT threadsafe.
        """
        # remove data item from any computations
        return self.__cascade_delete(library_item, safe=safe)

    def __remove_data_item(self, data_item, *, safe: bool=False) -> typing.Sequence:
        undelete_log = list()
        self.__transaction_manager._remove_item(data_item)
        assert data_item.uuid in self.__uuid_to_data_item
        library_computation = self.get_data_item_computation(data_item)
        with self.__computation_queue_lock:
            computation_pending_queue = self.__computation_pending_queue
            self.__computation_pending_queue = list()
            for computation_queue_item in computation_pending_queue:
                if not computation_queue_item.data_item is data_item and not computation_queue_item.computation is library_computation:
                    self.__computation_pending_queue.append(computation_queue_item)
            if self.__computation_active_item and data_item is self.__computation_active_item.data_item:
                self.__computation_active_item.valid = False
        # remove data item from any selections
        self.library_item_will_be_removed_event.fire(data_item)
        # remove the data item from any groups
        for data_group in self.get_flat_data_group_generator():
            if data_item in data_group.data_items:
                undelete_log.append({"type": "data_group_entry", "data_group_uuid": data_group.uuid, "properties": None, "index": data_group.data_items.index(data_item), "data_item_uuid": data_item.uuid})
                data_group.remove_data_item(data_item)
        # tell the data item it is about to be removed
        data_item.about_to_be_removed()
        # remove it from the persistent_storage
        assert data_item is not None
        assert data_item in self.__data_items
        index = self.__data_items.index(data_item)
        # do actual removal
        del self.__data_items[index]
        self._set_persistent_property_value("data_item_deletions", self._get_persistent_property_value("data_item_deletions") + [str(data_item.uuid)])
        self.__uuid_to_data_item.pop(data_item.uuid, None)
        if data_item.r_var:
            data_item_variables = self._get_persistent_property_value("data_item_variables")
            del data_item_variables[data_item.r_var]
            self._set_persistent_property_value("data_item_variables", data_item_variables)
            data_item.r_var = None
        # keep storage up-to-date
        persistent_storage = data_item.persistent_storage
        persistent_storage.remove(safe=safe)
        data_item.persistent_object_context = None
        data_item.__storage_cache = None
        # update data item count
        for data_item_reference in self.__data_item_references.values():
            data_item_reference.data_item_removed(data_item)
        self.data_item_removed_event.fire(self, data_item, index, False)
        self.notify_remove_item("data_items", data_item, index)
        data_item.close()
        return undelete_log

    def restore_data_item(self, data_item_uuid: uuid.UUID, before_index: int=None) -> DataItem.DataItem:
        before_index = before_index if before_index is not None else len(self.data_items)
        storage_handler = self.__persistent_storage_system.restore_storage_handler(data_item_uuid)
        properties = storage_handler.read_properties()
        if len(properties.get("data_item_uuids", list())) > 0:
            data_item = DataItem.CompositeLibraryItem(item_uuid=data_item_uuid)
        else:
            large_format = isinstance(storage_handler, HDF5Handler.HDF5Handler)
            data_item = DataItem.DataItem(item_uuid=data_item_uuid, large_format=large_format)
        data_item.begin_reading()
        data_item.read_from_dict(properties)
        # insert in internal list
        self.__insert_data_item(before_index, data_item, storage_handler, properties, do_write=False)
        data_item.finish_reading()
        return data_item

    def insert_model_item(self, container, name, before_index, item):
        container.insert_item(name, before_index, item)
        if name == "graphics":
            # inserting a graphic may cause computations to become bounds
            # there may be a better place for this
            self.__rebind_computations()  # rebind any unresolved that may now be resolved

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        return self.__cascade_delete(item, safe=safe)

    def assign_variable_to_library_item(self, library_item: DataItem.LibraryItem) -> str:
        if not library_item.r_var:
            data_item_variables = self._get_persistent_property_value("data_item_variables")
            def find_var() -> str:
                for r in range(1, 1000000):
                    r_var = "r{:02d}".format(r)
                    if not r_var in data_item_variables:
                        return r_var
                return str()
            data_item_var = find_var()
            data_item_variables[data_item_var] = str(library_item.uuid)
            library_item.set_r_value(data_item_var)
            self._set_persistent_property_value("data_item_variables", data_item_variables)
        return library_item.r_var

    def variable_to_data_item_map(self) -> typing.Mapping[str, DataItem.DataItem]:
        m = dict()
        data_item_variables = self._get_persistent_property_value("data_item_variables")
        for variable, data_item_uuid_str in data_item_variables.items():
            m[variable] = self.__uuid_to_data_item[uuid.UUID(data_item_uuid_str)]
        return m

    def __build_cascade(self, item, items: list, dependencies: list) -> None:
        # build a list of items to delete, with the leafs at the end of the list.
        # print(f"build {item}")
        if item not in items:
            # first handle the case where a data item that is the only target of a graphic cascades to the graphic.
            # this is the only case where a target causes a source to be deleted.
            items.append(item)
            sources = self.__dependency_tree_target_to_source_map.get(weakref.ref(item), list())
            if isinstance(item, DataItem.DataItem):
                for source in sources:
                    if isinstance(source, Graphics.Graphic):
                        source_targets = self.__dependency_tree_source_to_target_map.get(weakref.ref(source), list())
                        if len(source_targets) == 1 and source_targets[0] == item:
                            self.__build_cascade(source, items, dependencies)
                for display in item.displays:
                    for graphic in display.graphics:
                        self.__build_cascade(graphic, items, dependencies)
            elif isinstance(item, Symbolic.Computation):
                for output in item._outputs:
                    self.__build_cascade(output, items, dependencies)
            targets = self.__dependency_tree_source_to_target_map.get(weakref.ref(item), list())
            for target in targets:
                if (item, target) not in dependencies:
                    dependencies.append((item, target))
                self.__build_cascade(target, items, dependencies)
            for data_item in self.data_items:
                if data_item.source == item:
                    if (item, data_item) not in dependencies:
                        dependencies.append((item, data_item))
                    self.__build_cascade(data_item, items, dependencies)
            for connection in self.connections:
                if connection.parent == item:
                    if (item, connection) not in dependencies:
                        dependencies.append((item, connection))
                    self.__build_cascade(connection, items, dependencies)
            for data_structure in self.data_structures:
                if data_structure.source == item:
                    if (item, data_structure) not in dependencies:
                        dependencies.append((item, data_structure))
                    self.__build_cascade(data_structure, items, dependencies)
            for computation in self.computations:
                if computation.source == item:
                    if (item, computation) not in dependencies:
                        dependencies.append((item, computation))
                    self.__build_cascade(computation, items, dependencies)
            for source in sources:
                if (source, item) not in dependencies:
                    dependencies.append((source, item))

    def __cascade_delete(self, master_item, items=None, dependencies=None, safe: bool=False) -> typing.Optional[typing.Sequence]:
        # print(f"cascade {item}")
        undelete_log = list()
        items = items if items else list()
        dependencies = dependencies if dependencies else list()
        self.__build_cascade(master_item, items, dependencies)
        cascaded = True
        while cascaded:
            cascaded = False
            # adjust computation bookkeeping to remove deleted items, then delete unused computations
            items_set = set(items)
            for computation in copy.copy(self.computations):
                output_deleted = master_item in computation._outputs
                computation._inputs -= items_set
                computation._outputs -= items_set
                if computation not in items and computation != self.__current_computation:
                    # computations are auto deleted if all inputs are deleted or any output is deleted
                    if output_deleted or all(input in items for input in computation._inputs):
                        self.__build_cascade(computation, items, dependencies)
                        cascaded = True
        # print(list(reversed(items)))
        for source, target in reversed(dependencies):
            self.__remove_dependency(source, target)
        # now delete the actual items
        for item in reversed(items):
            container = item.container
            if isinstance(item, DataItem.LibraryItem):
                name = "data_items"
            elif isinstance(item, Graphics.Graphic):
                name = "graphics"
            elif isinstance(item, DataStructure):
                name = "data_structures"
            elif isinstance(item, Symbolic.Computation):
                name = "computations"
            elif isinstance(item, Connection.Connection):
                name = "connections"
            else:
                print("Unable to cascade delete type " + str(type(item)))
                name = None
            assert name
            # print(container, name, item)
            if container is self and name == "data_items":
                # call the version of __remove_data_item that doesn't cascade again
                index = getattr(container, name).index(item)
                item_dict = item.write_to_dict()
                undelete_log.extend(self.__remove_data_item(item, safe=safe))
                undelete_log.append({"type": name, "index": index, "properties": item_dict})
            else:
                container_ref = str(container.uuid)
                index = getattr(container, name).index(item)
                item_dict = item.write_to_dict()
                undelete_log.append({"type": name, "container": container_ref, "index": index, "properties": item_dict})
                container.remove_item(name, item)
        return undelete_log

    def undelete_all(self, undelete_log):
        for entry in reversed(undelete_log):
            index = entry["index"]
            name = entry["type"]
            properties = entry["properties"]
            if name == "data_items":
                self.restore_data_item(properties["uuid"], index)
            elif name == "computations":
                item = Symbolic.Computation()
                item.begin_reading()
                item.read_from_dict(properties)
                item.finish_reading()
                item.bind(self)
                self.insert_computation(index, item)
            elif name == "graphics":
                item = Graphics.factory(properties.get)
                item.begin_reading()
                item.read_from_dict(properties)
                item.finish_reading()
                self.get_display_by_uuid(uuid.UUID(entry["container"])).insert_graphic(index, item)
            elif name == "connections":
                item = Connection.connection_factory(properties.get)
                item.begin_reading()
                item.read_from_dict(properties)
                item.finish_reading()
                self.insert_connection(index, item)
            elif name == "data_structures":
                item = data_structure_factory(properties.get)
                item.begin_reading()
                item.read_from_dict(properties)
                item.finish_reading()
                self.insert_data_structure(index, item)
            elif name == "data_group_entry":
                data_group = self.get_data_group_by_uuid(entry["data_group_uuid"])
                data_item = self.get_data_item_by_uuid(entry["data_item_uuid"])
                data_group.insert_data_item(index, data_item)
            else:
                assert False

    def __remove_dependency(self, source_item, target_item):
        # print(f"remove dependency {source_item} {target_item}")
        with self.__dependency_tree_lock:
            target_items = self.__dependency_tree_source_to_target_map.setdefault(weakref.ref(source_item), list())
            if target_item in target_items:
                target_items.remove(target_item)
            if not target_items:
                self.__dependency_tree_source_to_target_map.pop(weakref.ref(source_item), None)
            source_items = self.__dependency_tree_target_to_source_map.setdefault(weakref.ref(target_item), list())
            if source_item in source_items:
                source_items.remove(source_item)
            if not source_items:
                self.__dependency_tree_target_to_source_map.pop(weakref.ref(target_item), None)
        if isinstance(source_item, DataItem.DataItem) and isinstance(target_item, DataItem.DataItem):
            # propagate live states to dependents
            if source_item.is_live:
                self.end_data_item_live(target_item)
        self.dependency_removed_event.fire(source_item, target_item)
        # fire the display messages
        if isinstance(source_item, DataItem.DataItem):
            display = source_item.primary_display_specifier.display
            source_displays = self.get_source_displays(display) if display else list()
            dependent_displays = self.get_dependent_displays(display) if display else list()
            self.related_items_changed.fire(display, source_displays, dependent_displays)

    def __add_dependency(self, source_item, target_item):
        # print(f"add dependency {source_item} {target_item}")
        with self.__dependency_tree_lock:
            self.__dependency_tree_source_to_target_map.setdefault(weakref.ref(source_item), list()).append(target_item)
            self.__dependency_tree_target_to_source_map.setdefault(weakref.ref(target_item), list()).append(source_item)
        if isinstance(source_item, DataItem.DataItem) and isinstance(target_item, DataItem.DataItem):
            # propagate live states to dependents
            if source_item.is_live:
                self.begin_data_item_live(target_item)
        self.dependency_added_event.fire(source_item, target_item)
        # fire the display messages
        if isinstance(source_item, DataItem.DataItem):
            display = source_item.primary_display_specifier.display
            source_displays = self.get_source_displays(display) if display else list()
            dependent_displays = self.get_dependent_displays(display) if display else list()
            self.related_items_changed.fire(display, source_displays, dependent_displays)

    def __computation_needs_update(self, data_item, computation):
        # When the computation for a data item is set or mutated, this function will be called.
        # This function looks through the existing pending computation queue, and if this data
        # item is not already in the queue, it adds it and ensures the dispatch thread eventually
        # executes the computation.
        with self.__computation_queue_lock:
            for computation_queue_item in self.__computation_pending_queue:
                if data_item and computation_queue_item.data_item == data_item:
                    return
                if computation and computation_queue_item.computation == computation:
                    return
            computation_queue_item = ComputationQueueItem(data_item=data_item, computation=computation)
            self.__computation_pending_queue.append(computation_queue_item)
        self.dispatch_task2(self.__recompute)

    def __resolve_computation_inputs(self, computation: Symbolic.Computation) -> typing.Set:
        # resolve the computation inputs and return the set of input items.
        input_items = set()
        for variable in computation.variables:
            specifier = variable.specifier
            if specifier:
                object = self.resolve_object_specifier(variable.specifier, variable.secondary_specifier, variable.property_name)
                if hasattr(object, "base_objects"):
                    input_items.update(object.base_objects)
        return input_items

    def __resolve_computation_outputs(self, computation: Symbolic.Computation) -> typing.Set:
        # resolve the computation inputs and return the set of input items.
        output_items = set()
        for result in computation.results:
            specifier = result.specifier
            if specifier:
                object = self.resolve_object_specifier(specifier)
                if hasattr(object, "value"):
                    source_item = object.value
                    output_items.add(source_item)
            specifiers = result.specifiers
            if specifiers:
                for specifier in specifiers:
                    object = self.resolve_object_specifier(specifier)
                    if hasattr(object, "value"):
                        source_item = object.value
                        output_items.add(source_item)
        return output_items

    def __establish_computation_dependencies(self, old_inputs: typing.Set, new_inputs: typing.Set, old_outputs: typing.Set, new_outputs: typing.Set) -> None:
        # establish dependencies between input and output items.
        with self.__dependency_tree_lock:
            removed_inputs = old_inputs - new_inputs
            added_inputs = new_inputs - old_inputs
            removed_outputs = old_outputs - new_outputs
            added_outputs = new_outputs - old_outputs
            same_inputs = old_inputs.intersection(new_inputs)
            # a, b -> x, y => a, c => x, z
            # [a -> x, a -> y, b -> x, b -> y]
            # [a -> x, a -> z, c -> x, c -> z]
            # old_inputs = [a, b]
            # new_inputs = [a, c]
            # removed inputs = [b]
            # added_inputs = [c]
            # old_outputs = [x, y]
            # new_outputs = [x, z]
            # removed_outputs = [y]
            # added_outputs = [z]
            # for each removed input, remove dependency to old outputs: [a -> x, a -> y]
            # for each removed output, remove dependency from old inputs to that output: [a -> x]
            # for each added input, add dependency to new outputs: [a -> x, c -> x, c -> z]
            # for each added output, add dependency from unchanged inputs to that output: [a -> x, a -> z, c -> x, c -> z]
            for input in removed_inputs:
                for output in old_outputs:
                    self.__remove_dependency(input, output)
            for output in removed_outputs:
                for input in old_inputs:
                    self.__remove_dependency(input, output)
            for input in added_inputs:
                for output in new_outputs:
                    self.__add_dependency(input, output)
            for output in added_outputs:
                for input in same_inputs:
                    self.__add_dependency(input, output)
        if removed_inputs or added_inputs or removed_outputs or added_outputs:
            self.__transaction_manager._rebuild_transactions()

    @property
    def data_items(self):
        return tuple(self.__data_items)  # tuple makes it read only

    # live state, and dependencies

    def get_source_items(self, item) -> typing.List:
        with self.__dependency_tree_lock:
            return copy.copy(self.__dependency_tree_target_to_source_map.get(weakref.ref(item), list()))

    def get_dependent_items(self, item) -> typing.List:
        """Return the list of data items containing data that directly depends on data in this item."""
        with self.__dependency_tree_lock:
            return copy.copy(self.__dependency_tree_source_to_target_map.get(weakref.ref(item), list()))

    def __get_deep_dependent_item_set(self, item, item_set) -> None:
        """Return the list of data items containing data that directly depends on data in this item."""
        if not item in item_set:
            item_set.add(item)
            with self.__dependency_tree_lock:
                for dependent in self.get_dependent_items(item):
                    self.__get_deep_dependent_item_set(dependent, item_set)

    def get_source_data_items(self, data_item: DataItem.DataItem) -> typing.List[DataItem.DataItem]:
        with self.__dependency_tree_lock:
            return [data_item for data_item in self.__dependency_tree_target_to_source_map.get(weakref.ref(data_item), list()) if isinstance(data_item, DataItem.DataItem)]

    def get_dependent_data_items(self, data_item: DataItem.DataItem) -> typing.List[DataItem.DataItem]:
        """Return the list of data items containing data that directly depends on data in this item."""
        with self.__dependency_tree_lock:
            return [data_item for data_item in self.__dependency_tree_source_to_target_map.get(weakref.ref(data_item), list()) if isinstance(data_item, DataItem.DataItem)]

    def get_source_displays(self, display: Display.Display) -> typing.List[Display.Display]:
        data_item = DataItem.DisplaySpecifier.from_display(display).data_item
        if data_item:
            data_items = self.get_source_data_items(data_item)
            return [data_item.primary_display_specifier.display for data_item in data_items]
        return list()

    def get_dependent_displays(self, display: Display.Display) -> typing.List[Display.Display]:
        data_item = DataItem.DisplaySpecifier.from_display(display).data_item
        if data_item:
            data_items = self.get_dependent_data_items(data_item)
            return [data_item.primary_display_specifier.display for data_item in data_items]
        return list()

    def item_transaction(self, item) -> Transaction:
        return self.__transaction_manager.item_transaction(item)

    def is_in_transaction_state(self, item) -> bool:
        return self.__transaction_manager.is_in_transaction_state(item)

    @property
    def transaction_count(self):
        return self.__transaction_manager.transaction_count

    def begin_display_transaction(self, display: Display.Display) -> Transaction:
        library_item = DataItem.DisplaySpecifier.from_display(display).library_item
        if library_item:
            return self.item_transaction(library_item)
        else:
            return Transaction(self.__transaction_manager, set())

    def data_item_live(self, data_item):
        """ Return a context manager to put the data item in a 'live state'. """
        class LiveContextManager:
            def __init__(self, manager, object):
                self.__manager = manager
                self.__object = object
            def __enter__(self):
                self.__manager.begin_data_item_live(self.__object)
                return self
            def __exit__(self, type, value, traceback):
                self.__manager.end_data_item_live(self.__object)
        return LiveContextManager(self, data_item)

    def begin_data_item_live(self, data_item):
        """Begins a live state for the data item.

        The live state is propagated to dependent data items.

        This method is thread safe. See slow_test_dependent_data_item_removed_while_live_data_item_becomes_unlive.
        """
        with self.__live_data_items_lock:
            old_live_count = self.__live_data_items.get(data_item.uuid, 0)
            self.__live_data_items[data_item.uuid] = old_live_count + 1
        if old_live_count == 0:
            data_item._enter_live_state()
            for dependent_data_item in self.get_dependent_data_items(data_item):
                self.begin_data_item_live(dependent_data_item)

    def end_data_item_live(self, data_item):
        """Ends a live state for the data item.

        The live-ness property is propagated to dependent data items, similar to the transactions.

        This method is thread safe.
        """
        with self.__live_data_items_lock:
            live_count = self.__live_data_items.get(data_item.uuid, 0) - 1
            assert live_count >= 0
            self.__live_data_items[data_item.uuid] = live_count
        if live_count == 0:
            data_item._exit_live_state()
            for dependent_data_item in self.get_dependent_data_items(data_item):
                self.end_data_item_live(dependent_data_item)

    # data groups

    def append_data_group(self, data_group):
        self.insert_data_group(len(self.data_groups), data_group)

    def insert_data_group(self, before_index, data_group):
        self.insert_item("data_groups", before_index, data_group)
        self.notify_insert_item("data_groups", data_group, before_index)

    def remove_data_group(self, data_group):
        data_group.disconnect_data_items()
        index = self.data_groups.index(data_group)
        self.remove_item("data_groups", data_group)
        self.notify_remove_item("data_groups", data_group, index)

    def create_default_data_groups(self):
        # ensure there is at least one group
        if len(self.data_groups) < 1:
            data_group = DataGroup.DataGroup()
            data_group.title = _("My Data")
            self.append_data_group(data_group)

    def create_sample_images(self, resources_path):
        if True:
            data_group = self.get_or_create_data_group(_("Example Data"))
            handler = ImportExportManager.NDataImportExportHandler("ndata1-io-handler", None, ["ndata1"])
            samples_dir = os.path.join(resources_path, "SampleImages")
            #logging.debug("Looking in %s", samples_dir)
            def is_ndata(file_path):
                #logging.debug("Checking %s", file_path)
                _, extension = os.path.splitext(file_path)
                return extension == ".ndata1"
            if os.path.isdir(samples_dir):
                sample_paths = [os.path.normpath(os.path.join(samples_dir, d)) for d in os.listdir(samples_dir) if is_ndata(os.path.join(samples_dir, d))]
            else:
                sample_paths = []
            for sample_path in sorted(sample_paths):
                data_items = handler.read_data_items(None, "ndata1", sample_path)
                for data_item in data_items:
                    if not self.get_data_item_by_uuid(data_item.uuid):
                        self.append_data_item(data_item)
                        data_group.append_data_item(data_item)
        else:
            # for testing, add a checkerboard image data item
            checkerboard_data_item = DataItem.DataItem(Image.create_checkerboard((512, 512)))
            checkerboard_data_item.title = "Checkerboard"
            self.append_data_item(checkerboard_data_item)
            # for testing, add a color image data item
            color_data_item = DataItem.DataItem(Image.create_color_image((512, 512), 128, 255, 128))
            color_data_item.title = "Green Color"
            self.append_data_item(color_data_item)
            # for testing, add a color image data item
            lena_data_item = DataItem.DataItem(scipy.misc.lena())
            lena_data_item.title = "Lena"
            self.append_data_item(lena_data_item)

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

    def get_data_group_or_document_model_by_uuid(self, uuid) -> typing.Optional[typing.Union["DocumentModel", DataGroup.DataGroup]]:
        if self.uuid == uuid:
            return self
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

    # access data items by title
    def get_data_item_by_title(self, title):
        for data_item in self.get_flat_data_item_generator():
            if data_item.title == title:
                return data_item
        return None

    # access data items by index
    def get_data_item_by_index(self, index):
        return list(self.get_flat_data_item_generator())[index]

    def get_index_for_data_item(self, data_item):
        return list(self.get_flat_data_item_generator()).index(data_item)

    # access data items by uuid
    def get_data_item_by_uuid(self, uuid: uuid.UUID) -> DataItem.DataItem:
        return self.__uuid_to_data_item.get(uuid)

    def get_or_create_data_group(self, group_name):
        data_group = DataGroup.get_data_group_in_container_by_title(self, group_name)
        if data_group is None:
            # we create a new group
            data_group = DataGroup.DataGroup()
            data_group.title = group_name
            self.insert_data_group(0, data_group)
        return data_group

    def create_computation(self, expression: str=None) -> Symbolic.Computation:
        computation = Symbolic.Computation(expression)
        computation.bind(self)
        return computation

    def dispatch_task(self, task, description=None):
        self.__thread_pool.queue_fn(task, description)

    def dispatch_task2(self, task, description=None):
        self.__computation_thread_pool.queue_fn(task, description)

    def recompute_all(self, merge=True):
        while True:
            self.__computation_thread_pool.run_all()
            if merge:
                self.perform_data_item_merge()
                with self.__computation_queue_lock:
                    if not (self.__computation_pending_queue or self.__computation_active_item or self.__pending_data_item_merge):
                        break
            else:
                break

    def recompute_one(self, merge=True):
        self.__computation_thread_pool.run_one()
        if merge:
            self.perform_data_item_merge()

    def start_dispatcher(self):
        self.__thread_pool.start()
        self.__computation_thread_pool.start(1)

    def __recompute(self):
        computation_queue_item = None
        with self.__computation_queue_lock:
            if not self.__computation_active_item and self.__computation_pending_queue:
                computation_queue_item = self.__computation_pending_queue.pop(0)
                self.__computation_active_item = computation_queue_item

        if computation_queue_item:
            # an item was put into the active queue, so compute it, then merge
            pending_data_item_merge = computation_queue_item.recompute()
            if pending_data_item_merge is not None:
                with self.__pending_data_item_merge_lock:
                    self.__pending_data_item_merge = pending_data_item_merge
                self.__call_soon(self.perform_data_item_merge)
            else:
                self.__computation_active_item = None

    def perform_data_item_merge(self):
        with self.__pending_data_item_merge_lock:
            pending_data_item_merge = self.__pending_data_item_merge
            self.__pending_data_item_merge = None
        if pending_data_item_merge is not None:
            computation, pending_data_item_merge_fn = pending_data_item_merge
            self.__current_computation = computation
            try:
                if callable(pending_data_item_merge_fn):
                    pending_data_item_merge_fn()
            finally:
                self.__current_computation = None
                with self.__computation_queue_lock:
                    self.__computation_active_item = None
                computation.is_initial_computation_complete.set()
        self.dispatch_task2(self.__recompute)

    async def compute_immediate(self, event_loop: asyncio.AbstractEventLoop, computation: Symbolic.Computation, timeout: float=None) -> None:
        if computation:
            def sync_recompute():
                computation.is_initial_computation_complete.wait(timeout)
            await event_loop.run_in_executor(None, sync_recompute)

    def get_object_specifier(self, object, object_type: str=None) -> typing.Optional[typing.Dict]:
        return get_object_specifier(object, object_type)

    def get_display_by_uuid(self, object_uuid: uuid.UUID) -> typing.Optional[Display.Display]:
        for data_item in self.data_items:
            for display in data_item.displays:
                if display.uuid == object_uuid:
                    return display
        return None

    def get_graphic_by_uuid(self, object_uuid: uuid.UUID) -> typing.Optional[Graphics.Graphic]:
        for data_item in self.data_items:
            for display in data_item.displays:
                for graphic in display.graphics:
                    if graphic.uuid == object_uuid:
                        return graphic
        return None

    def get_data_structure_by_uuid(self, object_uuid: uuid.UUID) -> typing.Optional[DataStructure]:
        for data_structure in self.data_structures:
            if data_structure.uuid == object_uuid:
                return data_structure
        return None

    def get_computation_by_uuid(self, object_uuid: uuid.UUID) -> typing.Optional[Symbolic.Computation]:
        for computation in self.computations:
            if computation.uuid == object_uuid:
                return computation
        return None

    def resolve_object_specifier(self, specifier: dict, secondary_specifier: dict=None, property_name: str=None):
        document_model = self
        if specifier.get("version") == 1:
            specifier_type = specifier["type"]
            if specifier_type == "data_item":  # should be "data_source" but requires file format change
                specifier_uuid_str = specifier.get("uuid")
                secondary_uuid_str = secondary_specifier.get("uuid") if secondary_specifier else None
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                secondary_uuid = uuid.UUID(secondary_uuid_str) if secondary_uuid_str else None
                data_item = self.get_data_item_by_uuid(object_uuid) if object_uuid else None
                graphic = self.get_graphic_by_uuid(secondary_uuid) if secondary_uuid else None
                class BoundDataSource:
                    def __init__(self, data_item, graphic):
                        self.changed_event = Event.Event()
                        self.property_changed_event = Event.Event()
                        self.__data_source = DataItem.DataSource(data_item, graphic, self.changed_event)
                    @property
                    def value(self):
                        return self.__data_source
                    @property
                    def base_objects(self):
                        objects = {self.__data_source.data_item}
                        if self.__data_source.graphic:
                            objects.add(self.__data_source.graphic)
                        return objects
                    def close(self):
                        self.__data_source.close()
                        self.__data_source = None
                if data_item:
                    return BoundDataSource(data_item, graphic)
            elif specifier_type == "data_item_object":
                specifier_uuid_str = specifier.get("uuid")
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                data_item = self.get_data_item_by_uuid(object_uuid) if object_uuid else None
                if data_item:
                    class BoundDataItem:
                        def __init__(self, object):
                            self.__object = object
                            self.changed_event = Event.Event()
                            self.property_changed_event = Event.Event()
                            self.__data_item_changed_event_listener = self.__object.data_item_changed_event.listen(self.changed_event.fire)
                        def close(self):
                            self.__data_item_changed_event_listener.close()
                            self.__data_item_changed_event_listener = None
                        @property
                        def value(self):
                            return self.__object
                        @property
                        def base_objects(self):
                            return {self.__object}
                    return BoundDataItem(data_item)
            elif specifier_type == "xdata":
                specifier_uuid_str = specifier.get("uuid")
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                data_item = self.get_data_item_by_uuid(object_uuid) if object_uuid else None
                if data_item:
                    class BoundDataItem:
                        def __init__(self, object):
                            self.__object = object
                            self.changed_event = Event.Event()
                            self.property_changed_event = Event.Event()
                            self.__data_changed_event_listener = self.__object.data_changed_event.listen(self.changed_event.fire)
                        def close(self):
                            self.__data_changed_event_listener.close()
                            self.__data_changed_event_listener = None
                        @property
                        def value(self):
                            return self.__object.xdata
                        @property
                        def base_objects(self):
                            return {self.__object}
                    return BoundDataItem(data_item)
            elif specifier_type == "display_xdata":
                specifier_uuid_str = specifier.get("uuid")
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                data_item = self.get_data_item_by_uuid(object_uuid) if object_uuid else None
                if data_item:
                    class BoundDataItem:
                        def __init__(self, object):
                            self.__object = object
                            self.changed_event = Event.Event()
                            self.property_changed_event = Event.Event()
                            self.__data_changed_event_listener = self.__object.data_changed_event.listen(self.changed_event.fire)
                        def close(self):
                            self.__data_changed_event_listener.close()
                            self.__data_changed_event_listener = None
                        @property
                        def value(self):
                            return self.__object.displays[0].get_calculated_display_values(True).display_data_and_metadata
                        @property
                        def base_objects(self):
                            return {self.__object}
                    return BoundDataItem(data_item)
            elif specifier_type == "cropped_xdata":
                specifier_uuid_str = specifier.get("uuid")
                secondary_uuid_str = secondary_specifier.get("uuid") if secondary_specifier else None
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                secondary_uuid = uuid.UUID(secondary_uuid_str) if secondary_uuid_str else None
                data_item = self.get_data_item_by_uuid(object_uuid) if object_uuid else None
                graphic = self.get_graphic_by_uuid(secondary_uuid) if secondary_uuid else None
                if data_item:
                    class BoundDataItem:
                        def __init__(self, data_item, graphic):
                            self.__data_item = data_item
                            self.__graphic = graphic
                            self.changed_event = Event.Event()
                            self.property_changed_event = Event.Event()
                            self.__data_changed_event_listener = self.__data_item.data_changed_event.listen(self.changed_event.fire)
                        def close(self):
                            self.__data_changed_event_listener.close()
                            self.__data_changed_event_listener = None
                        @property
                        def value(self):
                            xdata = self.__data_item.xdata
                            graphic = self.__graphic
                            if graphic:
                                if hasattr(graphic, "bounds"):
                                    return Core.function_crop(xdata, graphic.bounds)
                                if hasattr(graphic, "interval"):
                                    return Core.function_crop_interval(xdata, graphic.interval)
                            return xdata
                        @property
                        def base_objects(self):
                            objects = {self.__data_item}
                            if self.__graphic:
                                objects.add(self.__graphic)
                            return objects
                    return BoundDataItem(data_item, graphic)
            elif specifier_type == "cropped_display_xdata":
                specifier_uuid_str = specifier.get("uuid")
                secondary_uuid_str = secondary_specifier.get("uuid") if secondary_specifier else None
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                secondary_uuid = uuid.UUID(secondary_uuid_str) if secondary_uuid_str else None
                data_item = self.get_data_item_by_uuid(object_uuid) if object_uuid else None
                graphic = self.get_graphic_by_uuid(secondary_uuid) if secondary_uuid else None
                if data_item:
                    class BoundDataItem:
                        def __init__(self, data_item, graphic):
                            self.__data_item = data_item
                            self.__graphic = graphic
                            self.changed_event = Event.Event()
                            self.property_changed_event = Event.Event()
                            self.__data_changed_event_listener = self.__data_item.data_changed_event.listen(self.changed_event.fire)
                        def close(self):
                            self.__data_changed_event_listener.close()
                            self.__data_changed_event_listener = None
                        @property
                        def value(self):
                            xdata = self.__data_item.displays[0].get_calculated_display_values(True).display_data_and_metadata
                            graphic = self.__graphic
                            if graphic:
                                if hasattr(graphic, "bounds"):
                                    return Core.function_crop(xdata, graphic.bounds)
                                if hasattr(graphic, "interval"):
                                    return Core.function_crop_interval(xdata, graphic.interval)
                            return xdata
                        @property
                        def base_objects(self):
                            objects = {self.__data_item}
                            if self.__graphic:
                                objects.add(self.__graphic)
                            return objects
                    return BoundDataItem(data_item, graphic)
            elif specifier_type == "filter_xdata":
                specifier_uuid_str = specifier.get("uuid")
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                data_item = self.get_data_item_by_uuid(object_uuid) if object_uuid else None
                if data_item:
                    class BoundDataItem:
                        def __init__(self, object):
                            self.__object = object
                            self.changed_event = Event.Event()
                            self.property_changed_event = Event.Event()
                            self.__data_changed_event_listener = self.__object.data_changed_event.listen(self.changed_event.fire)
                        def close(self):
                            self.__data_changed_event_listener.close()
                            self.__data_changed_event_listener = None
                        @property
                        def value(self):
                            shape = self.__object.displays[0].get_calculated_display_values(True).display_data_and_metadata.data_shape
                            mask = numpy.zeros(shape)
                            for graphic in self.__object.displays[0].graphics:
                                if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                                    mask = numpy.logical_or(mask, graphic.get_mask(shape))
                            return DataAndMetadata.DataAndMetadata.from_data(mask)
                        @property
                        def base_objects(self):
                            objects = {self.__object}
                            for graphic in self.__object.displays[0].graphics:
                                if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                                    objects.add(graphic)
                            return objects
                    return BoundDataItem(data_item)
            elif specifier_type == "filtered_xdata":
                specifier_uuid_str = specifier.get("uuid")
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                data_item = self.get_data_item_by_uuid(object_uuid) if object_uuid else None
                if data_item:
                    class BoundDataItem:
                        def __init__(self, object):
                            self.__object = object
                            self.changed_event = Event.Event()
                            self.property_changed_event = Event.Event()
                            self.__data_changed_event_listener = self.__object.data_changed_event.listen(self.changed_event.fire)
                        def close(self):
                            self.__data_changed_event_listener.close()
                            self.__data_changed_event_listener = None
                        @property
                        def value(self):
                            xdata = self.__object.xdata
                            if xdata.is_data_2d and xdata.is_data_complex_type:
                                shape = xdata.data_shape
                                mask = numpy.zeros(shape)
                                for graphic in self.__object.displays[0].graphics:
                                    if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                                        mask = numpy.logical_or(mask, graphic.get_mask(shape))
                                return Core.function_fourier_mask(xdata, DataAndMetadata.DataAndMetadata.from_data(mask))
                            return xdata
                        @property
                        def base_objects(self):
                            objects = {self.__object}
                            for graphic in self.__object.displays[0].graphics:
                                if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                                    objects.add(graphic)
                            return objects
                    return BoundDataItem(data_item)
            elif specifier_type == "structure":
                specifier_uuid_str = specifier.get("uuid")
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                data_structure = self.get_data_structure_by_uuid(object_uuid)
                if data_structure:
                    class BoundDataStructure:
                        def __init__(self, object):
                            self.__object = object
                            self.changed_event = Event.Event()
                            self.property_changed_event = Event.Event()
                            def data_structure_changed(property_name_):
                                self.changed_event.fire()
                                if property_name_ == property_name:
                                    self.property_changed_event.fire(property_name_)
                            self.__changed_listener = self.__object.data_structure_changed_event.listen(data_structure_changed)
                        def close(self):
                            self.__changed_listener.close()
                            self.__changed_listener = None
                        @property
                        def value(self):
                            if property_name:
                                return self.__object.get_property_value(property_name)
                            return self.__object
                        @property
                        def base_objects(self):
                            return {self.__object}
                    return BoundDataStructure(data_structure)
            elif specifier_type == "region":
                specifier_uuid_str = specifier.get("uuid")
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                graphic = self.get_graphic_by_uuid(object_uuid)
                if graphic:
                    class BoundGraphic:
                        def __init__(self, object):
                            self.__object = object
                            self.changed_event = Event.Event()
                            self.property_changed_event = Event.Event()
                            def property_changed(property_name_):
                                self.changed_event.fire()
                                if property_name_ == property_name:
                                    self.property_changed_event.fire(property_name_)
                            self.__property_changed_listener = self.__object.property_changed_event.listen(property_changed)
                        def close(self):
                            self.__property_changed_listener.close()
                            self.__property_changed_listener = None
                        @property
                        def value(self):
                            if property_name:
                                return getattr(self.__object, property_name)
                            return self.__object
                        @property
                        def base_objects(self):
                            return {self.__object}
                    return BoundGraphic(graphic)
        return None

    class DataItemReference:
        """A data item reference to coordinate data item access between acquisition and main thread.

        Call start/stop a matching number of times to start/stop using the data reference (from the
        acquisition thread).

        Set data_item property when it is created (from the UI thread).

        This class will also track when the data item is deleted and handle it appropriately if it
        happens while the acquisition thread is using it.
        """
        def __init__(self, document_model: "DocumentModel", key: str, data_item: DataItem.DataItem=None):
            self.__document_model = document_model
            self.__key = key
            self.__data_item = data_item
            self.__starts = 0
            self.__pending_starts = 0
            self.__data_item_transaction = None
            self.mutex = threading.RLock()
            self.data_item_changed_event = Event.Event()

        def start(self):
            """Start using the data item reference. Must call stop a matching number of times.

            Increments ref counts and begins transaction/live state.

            Keeps track of pending starts if the data item has not yet been set.

            This call is thread safe.
            """
            if self.__data_item:
                self.__start()
            else:
                self.__pending_starts += 1

        def stop(self):
            """Stop using the data item reference. Must have called start a matching number of times.

            Decrements ref counts and ends transaction/live state.

            Keeps track of pending starts if the data item has not yet been set.

            This call is thread safe.
            """
            if self.__data_item:
                self.__stop()
            else:
                self.__pending_starts -= 1

        def __start(self):
            self.__data_item.increment_data_ref_count()
            self.__data_item_transaction = self.__document_model.item_transaction(self.__data_item)
            self.__document_model.begin_data_item_live(self.__data_item)
            self.__starts += 1

        def __stop(self):
            # the order of these two statements is important, at least for now (12/2013)
            # when the transaction ends, the data will get written to disk, so we need to
            # make sure it's still in memory. if decrement were to come before the end
            # of the transaction, the data would be unloaded from memory, losing it forever.
            if self.__data_item_transaction:
                self.__data_item_transaction.close()
                self.__data_item_transaction = None
                self.__document_model.end_data_item_live(self.__data_item)
                self.__data_item.decrement_data_ref_count()
                self.__starts -= 1

        # this method gets called directly from the document model
        def data_item_inserted(self, data_item):
            pass

        # this method gets called directly from the document model
        def data_item_removed(self, data_item):
            with self.mutex:
                if data_item == self.__data_item:
                    # when this data item is removed, it can no longer be used.
                    # but to ensure that start/stop calls are matching in the case where this item
                    # is removed and then a new item is set, we need to copy the number of starts
                    # to the pending starts so when the new item is set, start gets called the right
                    # number of times to match the stops that will eventually be called.
                    self.__pending_starts = self.__starts
                    self.__starts = 0
                    self.__data_item = None

        @property
        def data_item(self):
            with self.mutex:
                return self.__data_item

        @data_item.setter
        def data_item(self, value):
            with self.mutex:
                if self.__data_item != value:
                    self.__data_item = value
                    # start (internal) for each pending start.
                    for i in range(self.__pending_starts):
                        self.__start()
                    self.__pending_starts = 0
                    self.data_item_changed_event.fire()

    def __queue_data_item_update(self, data_item, data_and_metadata):
        # put the data update to data_item into the pending_data_item_updates list.
        # the pending_data_item_updates will be serviced when the main thread calls
        # perform_data_item_updates.
        if data_item:
            with self.__pending_data_item_updates_lock:
                found = False
                pending_data_item_updates = list()
                for data_item_ in self.__pending_data_item_updates:
                    # does it match? if so and not yet found, put the new data into the matching
                    # slot; but then filter the rest of the matches.
                    if data_item_ == data_item:
                        if not found:
                            data_item.set_pending_xdata(data_and_metadata)
                            pending_data_item_updates.append(data_item)
                            found = True
                    else:
                        pending_data_item_updates.append(data_item_)
                if not found:  # if not added yet, add it
                    data_item.set_pending_xdata(data_and_metadata)
                    pending_data_item_updates.append(data_item)
                self.__pending_data_item_updates = pending_data_item_updates

    def perform_data_item_updates(self):
        assert threading.current_thread() == threading.main_thread()
        with self.__pending_data_item_updates_lock:
            pending_data_item_updates = self.__pending_data_item_updates
            self.__pending_data_item_updates = list()
        for data_item in pending_data_item_updates:
            data_item.update_to_pending_xdata()

    # for testing
    def _get_pending_data_item_updates_count(self):
        return len(self.__pending_data_item_updates)

    @property
    def data_item_deletions(self) -> typing.Set[uuid.UUID]:
        return {uuid.UUID(uuid_str) for uuid_str in self._get_persistent_property_value("data_item_deletions")}

    def _update_data_item_reference(self, key: str, data_item: DataItem.DataItem) -> None:
        assert threading.current_thread() == threading.main_thread()
        data_item_references_dict = copy.deepcopy(self._get_persistent_property_value("data_item_references"))
        if data_item:
            data_item_references_dict[key] = str(data_item.uuid)
        else:
            del data_item_references_dict[key]
        self._set_persistent_property_value("data_item_references", data_item_references_dict)

    def make_data_item_reference_key(self, *components) -> str:
        return "_".join([str(component) for component in list(components) if component is not None])

    def get_data_item_reference(self, key) -> "DocumentModel.DataItemReference":
        # this is implemented this way to avoid creating a data item reference unless it is missing.
        data_item_reference = self.__data_item_references.get(key)
        if data_item_reference:
            return data_item_reference
        return self.__data_item_references.setdefault(key, DocumentModel.DataItemReference(self, key))

    def setup_channel(self, data_item_reference_key: str, data_item: DataItem.DataItem) -> None:
        data_item_reference = self.get_data_item_reference(data_item_reference_key)
        data_item_reference.data_item = data_item

    def __construct_data_item_reference(self, hardware_source: HardwareSource.HardwareSource, data_channel: HardwareSource.DataChannel):
        """Construct a data item reference.

        Construct a data item reference and assign a data item to it. Update data item session id and session metadata.
        Also connect the data channel processor.

        This method is thread safe.
        """
        session_id = self.session_id
        key = self.make_data_item_reference_key(hardware_source.hardware_source_id, data_channel.channel_id)
        data_item_reference = self.get_data_item_reference(key)
        with data_item_reference.mutex:
            data_item = data_item_reference.data_item
            # if we still don't have a data item, create it.
            if data_item is None:
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                data_item.title = "%s (%s)" % (hardware_source.display_name, data_channel.name) if data_channel.name else hardware_source.display_name
                data_item.category = "temporary"
                data_item_reference.data_item = data_item

                def append_data_item():
                    self.append_data_item(data_item)
                    self._update_data_item_reference(key, data_item)

                self.__call_soon(append_data_item)

            def update_session():
                # update the session, but only if necessary (this is an optimization to prevent unnecessary display updates)
                if data_item.session_id != session_id:
                    data_item.session_id = session_id
                session_metadata = self.session_metadata
                if data_item.session_metadata != session_metadata:
                    data_item.session_metadata = session_metadata
                if data_channel.processor:
                    src_data_channel = hardware_source.data_channels[data_channel.src_channel_index]
                    src_data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, src_data_channel.channel_id))
                    data_channel.processor.connect(src_data_item_reference)

            self.__call_soon(update_session)
            return data_item_reference

    def __data_channel_start(self, hardware_source, data_channel):
        def data_channel_start():
            assert threading.current_thread() == threading.main_thread()
            data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, data_channel.channel_id))
            data_item_reference.start()
        self.__call_soon(data_channel_start)

    def __data_channel_stop(self, hardware_source, data_channel):
        def data_channel_stop():
            assert threading.current_thread() == threading.main_thread()
            data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, data_channel.channel_id))
            data_item_reference.stop()
        self.__call_soon(data_channel_stop)

    def __data_channel_updated(self, hardware_source, data_channel, data_and_metadata):
        data_item_reference = self.__construct_data_item_reference(hardware_source, data_channel)
        self.__queue_data_item_update(data_item_reference.data_item, data_and_metadata)

    def __data_channel_states_updated(self, hardware_source, data_channels):
        data_item_states = list()
        for data_channel in data_channels:
            data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, data_channel.channel_id))
            data_item = data_item_reference.data_item
            channel_id = data_channel.channel_id
            channel_data_state = data_channel.state
            sub_area = data_channel.sub_area
            # make sure to send out the complete frame
            data_item_state = dict()
            if channel_id is not None:
                data_item_state["channel_id"] = channel_id
            data_item_state["data_item"] = data_item
            data_item_state["channel_state"] = channel_data_state
            if sub_area:
                data_item_state["sub_area"] = sub_area
            data_item_states.append(data_item_state)
        # temporary until things get cleaned up
        hardware_source.data_item_states_changed_event.fire(data_item_states)
        hardware_source.data_item_states_changed(data_item_states)

    def __hardware_source_added(self, hardware_source: HardwareSource.HardwareSource) -> None:
        self.__hardware_source_call_soon_event_listeners[hardware_source.hardware_source_id] = hardware_source.call_soon_event.listen(self.__call_soon)
        self.__data_channel_states_updated_listeners[hardware_source.hardware_source_id] = hardware_source.data_channel_states_updated.listen(functools.partial(self.__data_channel_states_updated, hardware_source))
        for data_channel in hardware_source.data_channels:
            data_channel_updated_listener = data_channel.data_channel_updated_event.listen(functools.partial(self.__data_channel_updated, hardware_source, data_channel))
            self.__data_channel_updated_listeners.setdefault(hardware_source.hardware_source_id, list()).append(data_channel_updated_listener)
            data_channel_start_listener = data_channel.data_channel_start_event.listen(functools.partial(self.__data_channel_start, hardware_source, data_channel))
            self.__data_channel_start_listeners.setdefault(hardware_source.hardware_source_id, list()).append(data_channel_start_listener)
            data_channel_stop_listener = data_channel.data_channel_stop_event.listen(functools.partial(self.__data_channel_stop, hardware_source, data_channel))
            self.__data_channel_stop_listeners.setdefault(hardware_source.hardware_source_id, list()).append(data_channel_stop_listener)
            data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, data_channel.channel_id))
            data_item = data_item_reference.data_item
            if data_item:
                hardware_source.clean_data_item(data_item, data_channel)

    def __hardware_source_removed(self, hardware_source):
        self.__hardware_source_call_soon_event_listeners[hardware_source.hardware_source_id].close()
        del self.__hardware_source_call_soon_event_listeners[hardware_source.hardware_source_id]
        self.__data_channel_states_updated_listeners[hardware_source.hardware_source_id].close()
        del self.__data_channel_states_updated_listeners[hardware_source.hardware_source_id]
        for listener in self.__data_channel_updated_listeners.get(hardware_source.hardware_source_id, list()):
            listener.close()
        for listener in self.__data_channel_start_listeners.get(hardware_source.hardware_source_id, list()):
            listener.close()
        for listener in self.__data_channel_stop_listeners.get(hardware_source.hardware_source_id, list()):
            listener.close()
        self.__data_channel_updated_listeners.pop(hardware_source.hardware_source_id, None)
        self.__data_channel_start_listeners.pop(hardware_source.hardware_source_id, None)
        self.__data_channel_stop_listeners.pop(hardware_source.hardware_source_id, None)

    def get_snapshot_new(self, data_item: DataItem.DataItem) -> DataItem.DataItem:
        assert isinstance(data_item, DataItem.DataItem)
        data_item_copy = data_item.snapshot()
        data_item_copy.title = _("Snapshot of ") + data_item.title
        self.append_data_item(data_item_copy)
        return data_item_copy

    def append_connection(self, connection: Connection.Connection) -> None:
        self.insert_connection(len(self.connections), connection)

    def insert_connection(self, before_index, connection):
        self.insert_item("connections", before_index, connection)
        self.notify_insert_item("connections", connection, before_index)

    def remove_connection(self, connection):
        self.remove_item("connections", connection)

    def __inserted_connection(self, name, before_index, connection):
        connection.about_to_be_inserted(self)

    def __removed_connection(self, name, index, connection):
        connection.about_to_be_removed()
        connection.close()

    def create_data_structure(self, *, structure_type: str=None, source=None):
        return DataStructure(structure_type=structure_type, source=source)

    def append_data_structure(self, data_structure):
        self.insert_data_structure(len(self.data_structures), data_structure)

    def insert_data_structure(self, before_index, data_structure):
        self.insert_item("data_structures", before_index, data_structure)
        self.notify_insert_item("data_structures", data_structure, before_index)

    def remove_data_structure(self, data_structure: DataStructure) -> typing.Optional[typing.Sequence]:
        return self.__cascade_delete(data_structure)

    def __inserted_data_structure(self, name, before_index, data_structure):
        data_structure.about_to_be_inserted(self)
        def rebuild_transactions(): self.__transaction_manager._rebuild_transactions()
        self.__data_structure_listeners[data_structure] = data_structure.referenced_objects_changed_event.listen(rebuild_transactions)
        self.__transaction_manager._add_item(data_structure)
        if not self._is_reading:
            self.__rebind_computations()  # rebind any unresolved that may now be resolved

    def __removed_data_structure(self, name, index, data_structure):
        self.__data_structure_listeners[data_structure].close()
        self.__data_structure_listeners.pop(data_structure, None)
        self.__transaction_manager._remove_item(data_structure)
        data_structure.about_to_be_removed()
        data_structure.close()

    def attach_data_structure(self, data_structure, data_item):
        data_structure.source = data_item

    def get_data_item_computation(self, data_item: DataItem.DataItem) -> typing.Optional[Symbolic.Computation]:
        for computation in self.computations:
            if computation.source == data_item:
                target_object = computation.get_referenced_object("target")
                if target_object == data_item:
                    return computation
        return None

    def set_data_item_computation(self, data_item: DataItem.DataItem, computation: typing.Optional[Symbolic.Computation]) -> None:
        if data_item:
            old_computation = self.get_data_item_computation(data_item)
            if old_computation is computation:
                pass
            elif computation:
                computation.source = data_item
                computation.create_result("target", self.get_object_specifier(data_item, "data_item"))
                self.append_computation(computation)
            elif old_computation:
                # remove old computation without cascade (it would delete this data item itself)
                old_computation.valid = False
                self.remove_item("computations", old_computation)
            if old_computation is not computation:
                self.__data_item_computation_changed(data_item, old_computation, computation)

    def append_computation(self, computation):
        self.insert_computation(len(self.computations), computation)

    def insert_computation(self, before_index, computation):
        input_items = self.__resolve_computation_inputs(computation)
        output_items = self.__resolve_computation_outputs(computation)
        input_set = set()
        for input in input_items:
            self.__get_deep_dependent_item_set(input, input_set)
        output_set = set()
        for output in output_items:
            self.__get_deep_dependent_item_set(output, output_set)
        if input_set.intersection(output_set):
            raise Exception("Computation would result in duplicate dependency.")
        self.insert_item("computations", before_index, computation)
        self.notify_insert_item("computations", computation, before_index)

    def remove_computation(self, computation: Symbolic.Computation, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        return self.__cascade_delete(computation, safe=safe)

    def __computation_changed(self, computation):
        # when the computation is mutated, this function is called. it calls the handle computation
        # changed or mutated method to resolve computation variables and update dependencies between
        # library objects. it also fires the computation_updated_event to allow the user interface
        # to update.
        self.__computation_update_dependencies(computation)
        self.__computation_needs_update(None, computation)

    def __computation_update_dependencies(self, computation):
        # when a computation output is changed, this function is called to establish dependencies.
        # if other parts of the computation are changed (inputs, values, etc.), the __computation_changed
        # will handle the change (and trigger a new computation).
        input_items = self.__resolve_computation_inputs(computation)
        output_items = self.__resolve_computation_outputs(computation)
        self.__establish_computation_dependencies(computation._inputs, input_items, computation._outputs, output_items)
        computation._inputs = input_items
        computation._outputs = output_items

    def __inserted_computation(self, name: str, before_index: int, computation: Symbolic.Computation) -> None:
        computation.about_to_be_inserted(self)
        self.__computation_changed_listeners[computation] = computation.computation_mutated_event.listen(functools.partial(self.__computation_changed, computation))
        self.__computation_output_changed_listeners[computation] = computation.computation_output_changed_event.listen(functools.partial(self.__computation_update_dependencies, computation))
        self.__computation_changed(computation)  # ensure the initial mutation is reported

    def __removed_computation(self, name: str, index: int, computation: Symbolic.Computation) -> None:
        with self.__computation_queue_lock:
            computation_pending_queue = self.__computation_pending_queue
            self.__computation_pending_queue = list()
            for computation_queue_item in computation_pending_queue:
                if not computation_queue_item.computation is computation:
                    self.__computation_pending_queue.append(computation_queue_item)
            if self.__computation_active_item and computation is self.__computation_active_item.computation:
                self.__computation_active_item.valid = False
        computation_changed_listener = self.__computation_changed_listeners.pop(computation, None)
        if computation_changed_listener: computation_changed_listener.close()
        computation_output_changed_listener = self.__computation_output_changed_listeners.pop(computation, None)
        if computation_output_changed_listener: computation_output_changed_listener.close()
        computation.unbind()
        computation.about_to_be_removed()
        computation.close()

    def __data_item_computation_changed(self, data_item, old_computation, new_computation):
        # when the computation for a data item changes, this method is called to tear down the old listeners and
        # configure the new listeners. it is called when the document loads the data item, when a data item is
        # inserted, when a data item is removed, and when a data item is changed.
        assert data_item is not None

        def computation_mutated():
            # when the computation is mutated, this function is called. it calls the handle computation
            # changed or mutated method to resolve computation variables and update dependencies between
            # library objects. it also fires the computation_updated_event to allow the user interface
            # to update.
            input_items = self.__resolve_computation_inputs(new_computation) if new_computation else set()
            old_input_items = set(self.__dependency_tree_target_to_source_map.get(weakref.ref(data_item), list()))
            self.__establish_computation_dependencies(old_input_items, input_items, {data_item}, {data_item})
            self.computation_updated_event.fire(data_item, new_computation)

        if old_computation:
            # remove computation_changed_listener associated with the old computation
            computation_changed_listener = self.__computation_changed_listeners.pop(data_item, None)
            if computation_changed_listener: computation_changed_listener.close()

        if new_computation:
            # add computation_changed_listener to the new computation
            self.__computation_changed_listeners[data_item] = new_computation.computation_mutated_event.listen(computation_mutated)

        computation_mutated()  # ensure the initial mutation is reported

    def make_data_item_with_computation(self, processing_id: str, inputs: typing.List[typing.Tuple[DataItem.DataItem, typing.Optional[Graphics.Graphic]]], region_list_map: typing.Mapping[str, typing.List[Graphics.Graphic]]=None) -> DataItem.DataItem:
        return self.__make_computation(processing_id, inputs, region_list_map)

    def __make_computation(self, processing_id: str, inputs: typing.List[typing.Tuple[DataItem.DataItem, Graphics.Graphic]], region_list_map: typing.Mapping[str, typing.List[Graphics.Graphic]]=None) -> DataItem.DataItem:
        """Create a new data item with computation specified by processing_id, inputs, and region_list_map.

        The region_list_map associates a list of graphics corresponding to the required regions with a computation source (key).
        """
        region_list_map = region_list_map or dict()

        processing_descriptions = self._processing_descriptions
        processing_description = processing_descriptions[processing_id]

        # first process the sources in the description. match them to the inputs (which are data item/crop graphic tuples)
        src_dicts = processing_description.get("sources", list())
        assert len(inputs) == len(src_dicts)
        src_names = list()
        src_texts = list()
        src_labels = list()
        regions = list()
        region_map = dict()
        for i, (src_dict, input) in enumerate(zip(src_dicts, inputs)):

            display_specifier = DataItem.DisplaySpecifier.from_data_item(input[0])
            data_item = display_specifier.data_item
            display = display_specifier.display

            if not data_item:
                return None

            # each source can have a list of requirements, check through them
            requirements = src_dict.get("requirements", list())
            for requirement in requirements:
                requirement_type = requirement["type"]
                if requirement_type == "dimensionality":
                    min_dimension = requirement.get("min")
                    max_dimension = requirement.get("max")
                    dimensionality = len(data_item.dimensional_shape)
                    if min_dimension is not None and dimensionality < min_dimension:
                        return None
                    if max_dimension is not None and dimensionality > max_dimension:
                        return None
                if requirement_type == "is_sequence":
                    if not data_item.is_sequence:
                        return None

            src_name = src_dict["name"]
            src_label = src_dict["label"]
            use_display_data = src_dict.get("use_display_data", True)
            xdata_property = "display_xdata" if use_display_data else "xdata"
            if src_dict.get("croppable"):
                xdata_property = "cropped_" + xdata_property
            elif src_dict.get("use_filtered_data", False):
                xdata_property = "filtered_" + xdata_property
            src_text = "{}.{}".format(src_name, xdata_property)
            src_names.append(src_name)
            src_texts.append(src_text)
            src_labels.append(src_label)

            # each source can have a list of regions to be matched to arguments or created on the source
            region_dict_list = src_dict.get("regions", list())
            src_region_list = region_list_map.get(src_name, list())
            assert len(region_dict_list) == len(src_region_list)
            for region_dict, region in zip(region_dict_list, src_region_list):
                region_params = region_dict.get("params", dict())
                region_type = region_dict["type"]
                region_name = region_dict["name"]
                region_label = region_params.get("label")
                if region_type == "point":
                    if region:
                        assert isinstance(region, Graphics.PointGraphic)
                        point_region = region
                    else:
                        point_region = Graphics.PointGraphic()
                        for k, v in region_params.items():
                            setattr(point_region, k, v)
                        if display:
                            display.add_graphic(point_region)
                    regions.append((region_name, point_region, region_label))
                    region_map[region_name] = point_region
                elif region_type == "line":
                    if region:
                        assert isinstance(region, Graphics.LineProfileGraphic)
                        line_region = region
                    else:
                        line_region = Graphics.LineProfileGraphic()
                        line_region.start = 0.25, 0.25
                        line_region.end = 0.75, 0.75
                        for k, v in region_params.items():
                            setattr(line_region, k, v)
                        if display:
                            display.add_graphic(line_region)
                    regions.append((region_name, line_region, region_params.get("label")))
                    region_map[region_name] = line_region
                elif region_type == "rectangle":
                    if region:
                        assert isinstance(region, Graphics.RectangleGraphic)
                        rect_region = region
                    else:
                        rect_region = Graphics.RectangleGraphic()
                        rect_region.center = 0.5, 0.5
                        rect_region.size = 0.5, 0.5
                        for k, v in region_params.items():
                            setattr(rect_region, k, v)
                        if display:
                            display.add_graphic(rect_region)
                    regions.append((region_name, rect_region, region_params.get("label")))
                    region_map[region_name] = rect_region
                elif region_type == "ellipse":
                    if region:
                        assert isinstance(region, Graphics.EllipseGraphic)
                        ellipse_region = region
                    else:
                        ellipse_region = Graphics.RectangleGraphic()
                        ellipse_region.center = 0.5, 0.5
                        ellipse_region.size = 0.5, 0.5
                        for k, v in region_params.items():
                            setattr(ellipse_region, k, v)
                        if display:
                            display.add_graphic(ellipse_region)
                    regions.append((region_name, ellipse_region, region_params.get("label")))
                    region_map[region_name] = ellipse_region
                elif region_type == "spot":
                    if region:
                        assert isinstance(region, Graphics.SpotGraphic)
                        spot_region = region
                    else:
                        spot_region = Graphics.SpotGraphic()
                        spot_region.center = 0.25, 0.75
                        spot_region.size = 0.1, 0.1
                        for k, v in region_params.items():
                            setattr(spot_region, k, v)
                        if display:
                            display.add_graphic(spot_region)
                    regions.append((region_name, spot_region, region_params.get("label")))
                    region_map[region_name] = spot_region
                elif region_type == "interval":
                    if region:
                        assert isinstance(region, Graphics.IntervalGraphic)
                        interval_region = region
                    else:
                        interval_region = Graphics.IntervalGraphic()
                        for k, v in region_params.items():
                            setattr(interval_region, k, v)
                        if display:
                            display.add_graphic(interval_region)
                    regions.append((region_name, interval_region, region_params.get("label")))
                    region_map[region_name] = interval_region
                elif region_type == "channel":
                    if region:
                        assert isinstance(region, Graphics.ChannelGraphic)
                        channel_region = region
                    else:
                        channel_region = Graphics.ChannelGraphic()
                        for k, v in region_params.items():
                            setattr(channel_region, k, v)
                        if display:
                            display.add_graphic(channel_region)
                    regions.append((region_name, channel_region, region_params.get("label")))
                    region_map[region_name] = channel_region

        # now extract the script (full script) or expression (implied imports and return statement)
        script = processing_description.get("script")
        if not script:
            expression = processing_description.get("expression")
            if expression:
                script = Symbolic.xdata_expression(expression)
        assert script

        # construct the computation
        script = script.format(**dict(zip(src_names, src_texts)))
        computation = self.create_computation(script)
        computation.label = processing_description["title"]
        computation.processing_id = processing_id
        # process the data item inputs
        for src_dict, src_name, src_label, input in zip(src_dicts, src_names, src_labels, inputs):
            display_specifier = DataItem.DisplaySpecifier.from_data_item(input[0])
            secondary_specifier = None
            if src_dict.get("croppable", False):
                secondary_specifier = self.get_object_specifier(input[1])
            computation.create_object(src_name, self.get_object_specifier(display_specifier.data_item), label=src_label, secondary_specifier=secondary_specifier)
        # process the regions
        for region_name, region, region_label in regions:
            computation.create_object(region_name, self.get_object_specifier(region), label=region_label)
        # next process the parameters
        for param_dict in processing_description.get("parameters", list()):
            computation.create_variable(param_dict["name"], param_dict["type"], param_dict["value"], value_default=param_dict.get("value_default"),
                                        value_min=param_dict.get("value_min"), value_max=param_dict.get("value_max"),
                                        control_type=param_dict.get("control_type"), label=param_dict["label"])

        data_item0 = inputs[0][0]
        new_data_item = DataItem.new_data_item()
        prefix = "{} of ".format(processing_description["title"])
        new_data_item.title = prefix + data_item0.title
        new_data_item.category = data_item0.category

        self.append_data_item(new_data_item)

        display_specifier = DataItem.DisplaySpecifier.from_data_item(new_data_item)
        display = display_specifier.display

        # next come the output regions that get created on the target itself
        new_regions = dict()
        for out_region_dict in processing_description.get("out_regions", list()):
            region_type = out_region_dict["type"]
            region_name = out_region_dict["name"]
            region_params = out_region_dict.get("params", dict())
            if region_type == "interval":
                interval_region = Graphics.IntervalGraphic()
                for k, v in region_params.items():
                    setattr(interval_region, k, v)
                display.add_graphic(interval_region)
                new_regions[region_name] = interval_region

        # now come the connections between the source and target
        for connection_dict in processing_description.get("connections", list()):
            connection_type = connection_dict["type"]
            connection_src = connection_dict["src"]
            connection_src_prop = connection_dict.get("src_prop")
            connection_dst = connection_dict["dst"]
            connection_dst_prop = connection_dict.get("dst_prop")
            if connection_type == "property":
                if connection_src == "display":
                    # TODO: how to refer to the data_items? hardcode to data_item0 for now.
                    connection = Connection.PropertyConnection(data_item0.displays[0], connection_src_prop, new_regions[connection_dst], connection_dst_prop, parent=new_data_item)
                    self.append_connection(connection)
            elif connection_type == "interval_list":
                connection = Connection.IntervalListConnection(display, region_map[connection_dst], parent=new_data_item)
                self.append_connection(connection)

        # save setting the computation until last to work around threaded clone/merge operation bug.
        # the bug is that setting the computation triggers the recompute to occur on a thread.
        # the recompute clones the data item and runs the operation. meanwhile this thread
        # updates the connection. now the recompute finishes and merges back the data item
        # which was cloned before the connection was established, effectively reversing the
        # update that matched the graphic interval to the slice interval on the display.
        # the result is that the slice interval on the display would get set to the default
        # value of the graphic interval. so don't actually update the computation until after
        # everything is configured. permanent solution would be to improve the clone/merge to
        # only update data that had been changed. alternative implementation would only track
        # changes to the data item and then apply them again to the original during merge.
        self.set_data_item_computation(new_data_item, computation)

        return new_data_item

    _processing_descriptions = dict()
    _builtin_processing_descriptions = None

    @classmethod
    def register_processing_descriptions(cls, processing_descriptions: typing.Dict) -> None:
        assert len(set(cls._processing_descriptions.keys()).intersection(set(processing_descriptions.keys()))) == 0
        cls._processing_descriptions.update(processing_descriptions)

    @classmethod
    def unregister_processing_descriptions(cls, processing_ids: typing.Sequence[str]):
        assert len(set(cls.__get_builtin_processing_descriptions().keys()).intersection(set(processing_ids))) == len(processing_ids)
        for processing_id in processing_ids:
            cls._processing_descriptions.pop(processing_id)

    @classmethod
    def _get_builtin_processing_descriptions(cls) -> typing.Dict:
        if not cls._builtin_processing_descriptions:
            vs = dict()
            vs["fft"] = {"title": _("FFT"), "expression": "xd.fft({src})", "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["inverse-fft"] = {"title": _("Inverse FFT"), "expression": "xd.ifft({src})",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False}]}
            vs["auto-correlate"] = {"title": _("Auto Correlate"), "expression": "xd.autocorrelate({src})",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["cross-correlate"] = {"title": _("Cross Correlate"), "expression": "xd.crosscorrelate({src1}, {src2})",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["sobel"] = {"title": _("Sobel"), "expression": "xd.sobel({src})",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["laplace"] = {"title": _("Laplace"), "expression": "xd.laplace({src})",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            sigma_param = {"name": "sigma", "label": _("Sigma"), "type": "real", "value": 3, "value_default": 3, "value_min": 0, "value_max": 100,
                "control_type": "slider"}
            vs["gaussian-blur"] = {"title": _("Gaussian Blur"), "expression": "xd.gaussian_blur({src}, sigma)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [sigma_param]}
            filter_size_param = {"name": "filter_size", "label": _("Size"), "type": "integral", "value": 3, "value_default": 3, "value_min": 1, "value_max": 100}
            vs["median-filter"] = {"title": _("Median Filter"), "expression": "xd.median_filter({src}, filter_size)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [filter_size_param]}
            vs["uniform-filter"] = {"title": _("Uniform Filter"), "expression": "xd.uniform_filter({src}, filter_size)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [filter_size_param]}
            do_transpose_param = {"name": "do_transpose", "label": _("Transpose"), "type": "boolean", "value": False, "value_default": False}
            do_flip_v_param = {"name": "do_flip_v", "label": _("Flip Vertical"), "type": "boolean", "value": False, "value_default": False}
            do_flip_h_param = {"name": "do_flip_h", "label": _("Flip Horizontal"), "type": "boolean", "value": False, "value_default": False}
            vs["transpose-flip"] = {"title": _("Transpose/Flip"), "expression": "xd.transpose_flip({src}, do_transpose, do_flip_v, do_flip_h)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [do_transpose_param, do_flip_v_param, do_flip_h_param]}
            width_param = {"name": "width", "label": _("Width"), "type": "integral", "value": 256, "value_default": 256, "value_min": 1}
            height_param = {"name": "height", "label": _("Height"), "type": "integral", "value": 256, "value_default": 256, "value_min": 1}
            vs["resample"] = {"title": _("Resample"), "expression": "xd.resample_image({src}, (height, width))",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [width_param, height_param]}
            vs["resize"] = {"title": _("Resize"), "expression": "xd.resize({src}, (height, width), 'mean')",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [width_param, height_param]}
            bins_param = {"name": "bins", "label": _("Bins"), "type": "integral", "value": 256, "value_default": 256, "value_min": 2}
            vs["histogram"] = {"title": _("Histogram"), "expression": "xd.histogram({src}, bins)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [bins_param]}
            vs["add"] = {"title": _("Add"), "expression": "{src1} + {src2}",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["subtract"] = {"title": _("Add"), "expression": "{src1} - {src2}",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["multiply"] = {"title": _("Add"), "expression": "{src1} * {src2}",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["divide"] = {"title": _("Add"), "expression": "{src1} / {src2}",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["invert"] = {"title": _("Negate"), "expression": "xd.invert({src})", "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["convert-to-scalar"] = {"title": _("Scalar"), "expression": "{src}",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            requirement_2d = {"type": "dimensionality", "min": 2, "max": 2}
            requirement_3d = {"type": "dimensionality", "min": 3, "max": 3}
            requirement_2d_to_3d = {"type": "dimensionality", "min": 2, "max": 3}
            requirement_2d_to_4d = {"type": "dimensionality", "min": 2, "max": 4}
            vs["crop"] = {"title": _("Crop"), "expression": "{src}",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["sum"] = {"title": _("Sum"), "expression": "xd.sum({src}, src.xdata.datum_dimension_indexes[0])",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True, "use_display_data": False, "requirements": [requirement_2d_to_4d]}]}
            slice_center_param = {"name": "center", "label": _("Center"), "type": "integral", "value": 0, "value_default": 0, "value_min": 0}
            slice_width_param = {"name": "width", "label": _("Width"), "type": "integral", "value": 1, "value_default": 1, "value_min": 1}
            vs["slice"] = {"title": _("Slice"), "expression": "xd.slice_sum({src}, center, width)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True, "use_display_data": False, "requirements": [requirement_3d]}],
                "parameters": [slice_center_param, slice_width_param]}
            pick_in_region = {"name": "pick_region", "type": "point", "params": {"label": _("Pick Point")}}
            pick_out_region = {"name": "interval_region", "type": "interval", "params": {"label": _("Display Slice")}}
            pick_connection = {"type": "property", "src": "display", "src_prop": "slice_interval", "dst": "interval_region", "dst_prop": "interval"}
            vs["pick-point"] = {"title": _("Pick"), "expression": "xd.pick({src}, pick_region.position)",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "regions": [pick_in_region], "requirements": [requirement_3d]}],
                "out_regions": [pick_out_region], "connections": [pick_connection]}
            pick_sum_in_region = {"name": "region", "type": "rectangle", "params": {"label": _("Pick Region")}}
            pick_sum_out_region = {"name": "interval_region", "type": "interval", "params": {"label": _("Display Slice")}}
            pick_sum_connection = {"type": "property", "src": "display", "src_prop": "slice_interval", "dst": "interval_region", "dst_prop": "interval"}
            vs["pick-mask-sum"] = {"title": _("Pick Sum"), "expression": "xd.sum_region({src}, region.mask_xdata_with_shape({src}.data_shape[0:2]))",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "regions": [pick_sum_in_region], "requirements": [requirement_3d]}],
                "out_regions": [pick_sum_out_region], "connections": [pick_sum_connection]}
            vs["pick-mask-average"] = {"title": _("Pick Average"), "expression": "xd.average_region({src}, region.mask_xdata_with_shape({src}.data_shape[0:2]))",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "regions": [pick_sum_in_region], "requirements": [requirement_3d]}],
                "out_regions": [pick_sum_out_region], "connections": [pick_sum_connection]}
            vs["subtract-mask-average"] = {"title": _("Subtract Average"), "expression": "{src} - xd.average_region({src}, region.mask_xdata_with_shape({src}.data_shape[0:2]))",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "regions": [pick_sum_in_region], "requirements": [requirement_3d]}],
                "out_regions": [pick_sum_out_region], "connections": [pick_sum_connection]}
            line_profile_in_region = {"name": "line_region", "type": "line", "params": {"label": _("Line Profile")}}
            line_profile_connection = {"type": "interval_list", "src": "data_source", "dst": "line_region"}
            vs["line-profile"] = {"title": _("Line Profile"), "expression": "xd.line_profile({src}, line_region.vector, line_region.line_width)",
                "sources": [{"name": "src", "label": _("Source"), "regions": [line_profile_in_region]}], "connections": [line_profile_connection]}
            vs["filter"] = {"title": _("Filter"), "expression": "xd.real(xd.ifft({src}))",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "use_filtered_data": True, "requirements": [requirement_2d]}]}
            requirement_is_sequence = {"type": "is_sequence"}
            vs["sequence-register"] = {"title": _("Shifts"), "expression": "xd.sequence_register_translation({src}, 100)",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "requirements": [requirement_2d_to_3d, requirement_is_sequence]}]}
            vs["sequence-align"] = {"title": _("Alignment"), "expression": "xd.sequence_align({src}, 100)",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "requirements": [requirement_2d_to_3d, requirement_is_sequence]}]}
            vs["sequence-integrate"] = {"title": _("Integrate"), "expression": "xd.sequence_integrate({src})",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "requirements": [requirement_2d_to_3d, requirement_is_sequence]}]}
            trim_start_param = {"name": "start", "label": _("Start"), "type": "integral", "value": 0, "value_default": 0, "value_min": 0}
            trim_end_param = {"name": "end", "label": _("End"), "type": "integral", "value": 1, "value_default": 1, "value_min": 1}
            vs["sequence-trim"] = {"title": _("Trim"), "expression": "xd.sequence_trim({src}, start, end)",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "requirements": [requirement_2d_to_3d, requirement_is_sequence]}],
                "parameters": [trim_start_param, trim_end_param]}
            index_param = {"name": "index", "label": _("Index"), "type": "integral", "value": 1, "value_default": 1, "value_min": 1}
            vs["sequence-extract"] = {"title": _("Extract"), "expression": "xd.sequence_extract({src}, index)",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "requirements": [requirement_2d_to_3d, requirement_is_sequence]}],
                "parameters": [index_param]}
            cls._builtin_processing_descriptions = vs
        return cls._builtin_processing_descriptions

    def get_fft_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("fft", [(data_item, crop_region)])

    def get_ifft_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("inverse-fft", [(data_item, crop_region)])

    def get_auto_correlate_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("auto-correlate", [(data_item, crop_region)])

    def get_cross_correlate_new(self, data_item1: DataItem.DataItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("cross-correlate", [(data_item1, crop_region1), (data_item2, crop_region2)])

    def get_sobel_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sobel", [(data_item, crop_region)])

    def get_laplace_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("laplace", [(data_item, crop_region)])

    def get_gaussian_blur_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("gaussian-blur", [(data_item, crop_region)])

    def get_median_filter_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("median-filter", [(data_item, crop_region)])

    def get_uniform_filter_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("uniform-filter", [(data_item, crop_region)])

    def get_transpose_flip_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("transpose-flip", [(data_item, crop_region)])

    def get_resample_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("resample", [(data_item, crop_region)])

    def get_resize_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("resize", [(data_item, crop_region)])

    def get_histogram_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("histogram", [(data_item, crop_region)])

    def get_add_new(self, data_item1: DataItem.DataItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("add", [(data_item1, crop_region1), (data_item2, crop_region2)])

    def get_subtract_new(self, data_item1: DataItem.DataItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("subtract", [(data_item1, crop_region1), (data_item2, crop_region2)])

    def get_multiply_new(self, data_item1: DataItem.DataItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("multiply", [(data_item1, crop_region1), (data_item2, crop_region2)])

    def get_divide_new(self, data_item1: DataItem.DataItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("divide", [(data_item1, crop_region1), (data_item2, crop_region2)])

    def get_invert_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("invert", [(data_item, crop_region)])

    def get_convert_to_scalar_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("convert-to-scalar", [(data_item, crop_region)])

    def get_crop_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        if data_item and len(data_item.displays) > 0 and not crop_region:
            display = data_item.displays[0]
            if data_item.is_data_2d:
                rect_region = Graphics.RectangleGraphic()
                rect_region.center = 0.5, 0.5
                rect_region.size = 0.5, 0.5
                display.add_graphic(rect_region)
                crop_region = rect_region
            elif data_item.is_data_1d:
                interval_region = Graphics.IntervalGraphic()
                interval_region.interval = 0.25, 0.75
                display.add_graphic(interval_region)
                crop_region = interval_region
        return self.__make_computation("crop", [(data_item, crop_region)])

    def get_projection_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sum", [(data_item, crop_region)])

    def get_slice_sum_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("slice", [(data_item, crop_region)])

    def get_pick_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, pick_region: Graphics.PointTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("pick-point", [(data_item, crop_region)], {"src": [pick_region]})

    def get_pick_region_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, pick_region: Graphics.Graphic=None) -> DataItem.DataItem:
        return self.__make_computation("pick-mask-sum", [(data_item, crop_region)], {"src": [pick_region]})

    def get_pick_region_average_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, pick_region: Graphics.Graphic=None) -> DataItem.DataItem:
        return self.__make_computation("pick-mask-average", [(data_item, crop_region)], {"src": [pick_region]})

    def get_subtract_region_average_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, pick_region: Graphics.Graphic=None) -> DataItem.DataItem:
        return self.__make_computation("subtract-mask-average", [(data_item, crop_region)], {"src": [pick_region]})

    def get_line_profile_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, line_region: Graphics.LineTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("line-profile", [(data_item, crop_region)], {"src": [line_region]})

    def get_fourier_filter_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        if data_item and len(data_item.displays) > 0:
            display = data_item.displays[0]
            has_mask = False
            for graphic in display.graphics:
                if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                    has_mask = True
                    break
            if not has_mask:
                graphic = Graphics.RingGraphic()
                graphic.radius_1 = 0.15
                graphic.radius_2 = 0.25
                display.add_graphic(graphic)
        return self.__make_computation("filter", [(data_item, crop_region)])

    def get_sequence_measure_shifts_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sequence-register", [(data_item, crop_region)])

    def get_sequence_align_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sequence-align", [(data_item, crop_region)])

    def get_sequence_integrate_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sequence-integrate", [(data_item, crop_region)])

    def get_sequence_trim_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sequence-trim", [(data_item, crop_region)])

    def get_sequence_extract_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sequence-extract", [(data_item, crop_region)])



DocumentModel.register_processing_descriptions(DocumentModel._get_builtin_processing_descriptions())

def evaluate_data(computation) -> DataAndMetadata.DataAndMetadata:
    api = PlugInManager.api_broker_fn("~1.0", None)
    api_data_item = api._new_api_object(DataItem.new_data_item(None))
    error_text = computation.evaluate_with_target(api, api_data_item)
    computation.error_text = error_text
    return api_data_item.data_and_metadata
