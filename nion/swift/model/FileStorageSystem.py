import collections
import copy
import datetime
import json
import logging
import os.path
import pathlib
import shutil
import threading
import typing
import uuid

from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import HDF5Handler
from nion.swift.model import Migration
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

    def __init__(self, storage_system, storage_handler, properties):
        self.__storage_system = storage_system
        self.__storage_handler = storage_handler
        self.__properties = Migration.transform_to_latest(Utility.clean_dict(copy.deepcopy(properties) if properties else dict()))
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
            self.__storage_handler.write_properties(Migration.transform_from_latest(copy.deepcopy(self.__properties)), file_datetime)

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

    def __init__(self, file_path, directories, *, auto_migrations=None):
        self.__directories = directories
        self.__file_handlers = FileStorageSystem._file_handlers
        self.__data_item_storage = dict()
        self.__filepath = file_path
        self.__properties = self.__read_properties()
        self.__properties_lock = threading.RLock()
        self.__write_delay_counts = dict()
        self.__auto_migrations = auto_migrations or list()
        for auto_migration in self.__auto_migrations:
            auto_migration.storage_system = self

    def reset(self):
        self.__data_item_storage = dict()

    def get_auto_migrations(self):
        return self.__auto_migrations

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
        if object and isinstance(object, DataItem.DataItem):
            self.__get_storage_for_item(object).rewrite_item(object)
        elif not persistent_object_parent:
            if self.__filepath:
                # atomically overwrite
                temp_filepath = self.__filepath + ".temp"
                with open(temp_filepath, "w") as fp:
                    json.dump(Utility.clean_dict(self.__properties), fp)
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

    def get_properties(self, object):
        return self.__get_storage_dict(object)

    def rewrite_properties(self, properties):
        """Set the properties and write to disk."""
        with self.__properties_lock:
            self.__properties = properties
        self.__write_properties(None)  # write to library

    def __get_storage_dict(self, object):
        persistent_object_parent = object.persistent_object_parent
        if isinstance(object, DataItem.DataItem):
            return self.__get_storage_for_item(object).properties
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
        if isinstance(item, DataItem.DataItem):
            item.persistent_object_context = parent.persistent_object_context
            storage_handler = self.make_storage_handler(item)
            self.register_data_item(item, item.uuid, storage_handler, item.write_to_dict())
        else:
            storage_dict = self.__update_modified_and_get_storage_dict(parent)
            with self.__properties_lock:
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

    def restore_item(self, data_item_uuid: uuid.UUID) -> typing.Tuple[typing.Optional[dict], bool]:
        data_item_uuid_str = str(data_item_uuid)
        trash_dir = os.path.join(self.__directories[0], "trash")
        storage_handlers = self.__find_storage_handlers([trash_dir], skip_trash=False)
        for storage_handler in storage_handlers:
            properties = Migration.transform_to_latest(storage_handler.read_properties())
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
                properties["__large_format"] = isinstance(storage_handler, HDF5Handler.HDF5Handler)
                return properties
        return None, False

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

    def register_data_item(self, item: typing.Optional[DataItem.DataItem], item_uuid: uuid.UUID, storage_handler, properties: dict) -> None:
        assert item_uuid not in self.__data_item_storage
        storage_adapter = DataItemStorageAdapter(self, storage_handler, properties)
        self.__data_item_storage[item_uuid] = storage_adapter
        if item and self.is_write_delayed(item):
            storage_adapter.set_write_delayed(item, True)

    def unregister_data_item(self, item: DataItem.DataItem) -> None:
        assert item.uuid in self.__data_item_storage
        self.__data_item_storage.pop(item.uuid).close()

    def __get_storage_for_item(self, item: DataItem.DataItem) -> DataItemStorageAdapter:
        if not item.uuid in self.__data_item_storage:
            storage_handler = self.make_storage_handler(item)
            self.register_data_item(item, item.uuid, storage_handler, item.write_to_dict())
        return self.__data_item_storage.get(item.uuid)

    def get_storage_property(self, data_item: DataItem.DataItem, name: str) -> typing.Optional[str]:
        if name == "file_path":
            storage = self.__get_storage_for_item(data_item)
            return storage._storage_handler.reference if storage else None
        return None

    def read_external_data(self, item, name):
        if isinstance(item, DataItem.BufferedDataSource):
            item = item.persistent_object_parent.parent
        if isinstance(item, DataItem.DataItem) and name == "data":
            storage = self.__get_storage_for_item(item)
            return storage.load_data(item)
        return None

    def write_external_data(self, item, name, value) -> None:
        if isinstance(item, DataItem.BufferedDataSource):
            item = item.persistent_object_parent.parent
        if isinstance(item, DataItem.DataItem) and name == "data":
            storage = self.__get_storage_for_item(item)
            storage.update_data(item, value)

    def delete_item(self, data_item, safe: bool=False) -> None:
        storage = self.__get_storage_for_item(data_item)
        self.remove_storage_handler(storage._storage_handler, safe=safe)

    def enter_write_delay(self, object) -> None:
        if isinstance(object, DataItem.DataItem):
            count = self.__write_delay_counts.setdefault(object, 0)
            if count == 0:
                self.set_write_delayed(object, True)
            self.__write_delay_counts[object] = count + 1

    def exit_write_delay(self, object) -> None:
        if isinstance(object, DataItem.DataItem):
            count = self.__write_delay_counts.setdefault(object, 0)
            count -= 1
            if count == 0:
                self.set_write_delayed(object, False)
                self.__write_delay_counts.pop(object)
            else:
                self.__write_delay_counts[object] = count

    def set_write_delayed(self, data_item, write_delayed: bool) -> None:
        storage = self.__data_item_storage.get(data_item.uuid)
        if storage:
            storage.set_write_delayed(data_item, write_delayed)

    def is_write_delayed(self, data_item) -> bool:
        if isinstance(data_item, DataItem.DataItem):
            return self.__write_delay_counts.get(data_item, 0) > 0
        return False

    def rewrite_item(self, item) -> None:
        if isinstance(item, DataItem.BufferedDataSource):
            item = item.persistent_object_parent.parent
        storage = self.__get_storage_for_item(item)
        storage.rewrite_item(item)

    def read_data_items_version_stats(self):
        return read_data_items_version_stats(self)

    def read_library(self, ignore_older_files, log_migrations):
        return read_library(self, ignore_older_files, log_migrations)


def read_data_items_version_stats(persistent_storage_system):
    storage_handlers = list()  # storage_handler
    storage_handlers.extend(persistent_storage_system.find_data_items())
    count = [0, 0, 0]  # data item matches version, data item has higher version, data item has lower version
    writer_version = DataItem.DataItem.writer_version
    for storage_handler in storage_handlers:
        try:
            properties = Migration.transform_to_latest(storage_handler.read_properties())
            version = properties.get("version", 0)
            if version < writer_version:
                count[2] += 1
            elif version > writer_version:
                count[1] += 1
            else:
                count[0] += 1
        except Exception as e:
            pass  # logging.warning("Could not open file {}".format(storage_handler.reference))
    return count


def read_library(persistent_storage_system, ignore_older_files, log_migrations):
    """Read data items from the data reference handler and return as a list.

    Data items will have persistent_object_context set upon return, but caller will need to call finish_reading
    on each of the data items.
    """
    migration_log = Migration.MigrationLog(log_migrations)
    data_item_uuids = set()
    utilized_deletions = set()  # the uuid's skipped due to being deleted
    deletions = list()

    reader_info_list, library_updates = auto_migrate_storage_system(persistent_storage_system=persistent_storage_system,
                                                                    new_persistent_storage_system=persistent_storage_system,
                                                                    data_item_uuids=data_item_uuids,
                                                                    deletions=deletions,
                                                                    utilized_deletions=utilized_deletions,
                                                                    ignore_older_files=ignore_older_files,
                                                                    migration_log=migration_log)

    # next, for each auto migration, create a temporary storage system and read items from that storage system
    # using auto_migrate_storage_system. the data items returned will have been copied to the current storage
    # system (persistent object context).
    for auto_migration in reversed(persistent_storage_system.get_auto_migrations()):
        old_persistent_storage_system = FileStorageSystem(auto_migration.library_path, auto_migration.paths) if auto_migration.paths else auto_migration.storage_system
        new_reader_info_list, new_library_updates = auto_migrate_storage_system(persistent_storage_system=old_persistent_storage_system,
                                                                                new_persistent_storage_system=persistent_storage_system,
                                                                                data_item_uuids=data_item_uuids,
                                                                                deletions=deletions,
                                                                                utilized_deletions=utilized_deletions,
                                                                                ignore_older_files=ignore_older_files,
                                                                                migration_log=Migration.MigrationLog(False))
        reader_info_list.extend(new_reader_info_list)
        library_updates.update(new_library_updates)

    assert len(reader_info_list) == len(data_item_uuids)

    library_storage_properties = persistent_storage_system.library_storage_properties

    for reader_info in reader_info_list:
        properties = reader_info.properties
        properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
        version = properties.get("version", 0)
        if version == DataItem.DataItem.writer_version:
            data_item_uuid = uuid.UUID(properties.get("uuid", uuid.uuid4()))
            library_update = library_updates.get(data_item_uuid, dict())
            library_storage_properties.setdefault("connections", list()).extend(library_update.get("connections", list()))
            library_storage_properties.setdefault("computations", list()).extend(library_update.get("computations", list()))
            library_storage_properties.setdefault("display_items", list()).extend(library_update.get("display_items", list()))

    # mark deletions that need to be tracked because they've been deleted but are also present in older libraries
    # and would be migrated during reading unless they explicitly are prevented from doing so (via data_item_deletions).
    # utilized deletions are the ones that were attempted; if nothing was attempted, then no reason to track it anymore
    # since there is nothing to migrate in the future.
    library_storage_properties["data_item_deletions"] = [str(uuid_) for uuid_ in utilized_deletions]

    connections_list = library_storage_properties.get("connections", list())
    assert len(connections_list) == len({connection.get("uuid") for connection in connections_list})

    computations_list = library_storage_properties.get("computations", list())
    assert len(computations_list) == len({computation.get("uuid") for computation in computations_list})

    # migrations

    if library_storage_properties.get("version", 0) < 2:
        for data_group_properties in library_storage_properties.get("data_groups", list()):
            data_group_properties.pop("data_groups")
            display_item_references = data_group_properties.setdefault("display_item_references", list())
            data_item_uuid_strs = data_group_properties.pop("data_item_uuids", list())
            for data_item_uuid_str in data_item_uuid_strs:
                for display_item_properties in library_storage_properties.get("display_items", list()):
                    if data_item_uuid_str in display_item_properties.get("data_item_references", list()):
                        display_item_references.append(display_item_properties["uuid"])
        data_item_to_display_item_map = dict()
        for display_item_properties in library_storage_properties.get("display_items", list()):
            for data_item_uuid_str in display_item_properties.get("data_item_references", list()):
                data_item_to_display_item_map.setdefault(data_item_uuid_str, display_item_properties["uuid"])
        for workspace_properties in library_storage_properties.get("workspaces", list()):
            def replace1(d):
                if "children" in d:
                    for dd in d["children"]:
                        replace1(dd)
                if "data_item_uuid" in d:
                    data_item_uuid_str = d.pop("data_item_uuid")
                    display_item_uuid_str = data_item_to_display_item_map.get(data_item_uuid_str)
                    if display_item_uuid_str:
                        d["display_item_uuid"] = display_item_uuid_str
            replace1(workspace_properties["layout"])
        library_storage_properties["version"] = DocumentModel.DocumentModel.library_version

    # TODO: add consistency checks: no duplicated items [by uuid] such as connections or computations or data items

    assert library_storage_properties["version"] == DocumentModel.DocumentModel.library_version

    persistent_storage_system.rewrite_properties(library_storage_properties)

    properties = copy.deepcopy(library_storage_properties)

    for reader_info in reader_info_list:
        data_item_properties = Utility.clean_dict(reader_info.properties if reader_info.properties else dict())
        if data_item_properties.get("version", 0) == DataItem.DataItem.writer_version:
            data_item_properties["__large_format"] = reader_info.large_format
            data_item_properties["__identifier"] = reader_info.identifier
            properties.setdefault("data_items", list()).append(data_item_properties)

    def data_item_created(data_item_properties: typing.Mapping) -> str:
        return data_item_properties.get("created", "1900-01-01T00:00:00.000000")

    properties["data_items"] = sorted(properties.get("data_items", list()), key=data_item_created)

    return properties


def auto_migrate_data_item(reader_info, persistent_storage_system, new_persistent_storage_system, migration_log: Migration.MigrationLog):
    storage_handler = reader_info.storage_handler
    properties = reader_info.properties
    properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
    data_item_uuid = uuid.UUID(properties["uuid"])
    if persistent_storage_system == new_persistent_storage_system:
        if reader_info.changed_ref[0]:
            storage_handler.write_properties(Migration.transform_from_latest(copy.deepcopy(properties)), datetime.datetime.now())
        persistent_storage_system.register_data_item(None, data_item_uuid, storage_handler, properties)
    else:
        # create a temporary data item that can be used to get the new file reference
        old_data_item = DataItem.DataItem(item_uuid=data_item_uuid)
        old_data_item.begin_reading()
        old_data_item.read_from_dict(properties)
        old_data_item.finish_reading()
        old_data_item_path = storage_handler.reference
        # ask the storage system for the file handler for the data item path
        file_handler = new_persistent_storage_system.get_file_handler_for_file(old_data_item_path)
        # ask the storage system to make a storage handler (an instance of a file handler) for the data item
        # this ensures that the storage handler (file format) is the same as before.
        target_storage_handler = new_persistent_storage_system.make_storage_handler(old_data_item, file_handler)
        if target_storage_handler:
            os.makedirs(os.path.dirname(target_storage_handler.reference), exist_ok=True)
            shutil.copyfile(storage_handler.reference, target_storage_handler.reference)
            target_storage_handler.write_properties(Migration.transform_from_latest(copy.deepcopy(properties)), datetime.datetime.now())
            new_persistent_storage_system.register_data_item(None, data_item_uuid, target_storage_handler, properties)
            migration_log.push("Copying data item {} to library.".format(data_item_uuid))
        else:
            migration_log.push("Unable to copy data item %s to library.".format(data_item_uuid))


def auto_migrate_storage_system(*, persistent_storage_system=None, new_persistent_storage_system=None, data_item_uuids=None, deletions: typing.List[uuid.UUID] = None, utilized_deletions: typing.Set[uuid.UUID] = None, ignore_older_files: bool = True, migration_log: Migration.MigrationLog = None):
    """Migrate items from the storage system to the object context.

    Files in data_item_uuids have already been loaded and are ignored (not migrated).

    Files in deletes have been deleted in object context and are ignored (not migrated) and then added
    to the utilized deletions list.

    Data items will have persistent_object_context set upon return, but caller will need to call finish_reading
    on each of the data items.
    """
    storage_handlers = persistent_storage_system.find_data_items()
    ReaderInfo = collections.namedtuple("ReaderInfo", ["properties", "changed_ref", "large_format", "storage_handler", "identifier"])
    reader_info_list = list()
    for storage_handler in storage_handlers:
        try:
            large_format = isinstance(storage_handler, HDF5Handler.HDF5Handler)
            properties = Migration.transform_to_latest(storage_handler.read_properties())
            reader_info = ReaderInfo(properties, [False], large_format, storage_handler, storage_handler.reference)
            reader_info_list.append(reader_info)
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()
    library_storage_properties = persistent_storage_system.library_storage_properties
    for deletion in copy.deepcopy(library_storage_properties.get("data_item_deletions", list())):
        if not deletion in deletions:
            deletions.append(deletion)
    preliminary_library_updates = dict()
    library_updates = dict()
    if not ignore_older_files:
        Migration.migrate_to_latest(reader_info_list, preliminary_library_updates, migration_log)
    good_reader_info_list = list()
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version == DataItem.DataItem.writer_version:
                data_item_uuid = uuid.UUID(properties["uuid"])
                if not data_item_uuid in data_item_uuids:
                    if str(data_item_uuid) in deletions:
                        utilized_deletions.add(data_item_uuid)
                    else:
                        auto_migrate_data_item(reader_info, persistent_storage_system, new_persistent_storage_system, migration_log)
                        good_reader_info_list.append(reader_info)
                        data_item_uuids.add(data_item_uuid)
                        library_update = preliminary_library_updates.get(data_item_uuid)
                        if library_update:
                            library_updates[data_item_uuid] = library_update
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()
    return good_reader_info_list, library_updates
