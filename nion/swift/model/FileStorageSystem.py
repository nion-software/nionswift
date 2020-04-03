import abc
import collections
import contextlib
import copy
import datetime
import json
import logging
import numpy
import os.path
import pathlib
import shutil
import threading
import typing
import uuid

from nion.swift.model import DataItem
from nion.swift.model import HDF5Handler
from nion.swift.model import Migration
from nion.swift.model import NDataHandler
from nion.swift.model import Persistence
from nion.swift.model import Utility
from nion.utils import Event


# define the versions that get stored in the JSON files
PROFILE_VERSION = 2
PROJECT_VERSION = 3
PROJECT_VERSION_0_14 = 2

ReaderInfo = collections.namedtuple("ReaderInfo", ["properties", "changed_ref", "large_format", "storage_handler", "identifier"])


class DataItemStorageAdapter:
    """Persistent storage for writing data item properties, relationships, and data to its storage handler."""

    def __init__(self, storage_handler, properties: typing.Dict):
        self.__storage_handler = storage_handler
        self.__properties = properties

    def close(self):
        if self.__storage_handler:
            self.__storage_handler.close()
            self.__storage_handler = None

    @property
    def properties(self):
        return self.__properties

    @property
    def storage_handler(self):
        return self.__storage_handler

    def rewrite_item(self, item) -> None:
        file_datetime = item.created_local
        self.__storage_handler.write_properties(Migration.transform_from_latest(copy.deepcopy(self.__properties)), file_datetime)

    def update_data(self, item, data):
        file_datetime = item.created_local
        if data is not None:
            self.__storage_handler.write_data(data, file_datetime)

    def reserve_data(self, item, data_shape: typing.Tuple[int, ...], data_dtype: numpy.dtype) -> None:
        file_datetime = item.created_local
        self.__storage_handler.reserve_data(data_shape, data_dtype, file_datetime)

    def load_data(self, item) -> None:
        return self.__storage_handler.read_data()


def migrate_to_latest(source_project_storage_system: "ProjectStorageSystem",
                      target_project_storage_system: "ProjectStorageSystem" = None) -> None:
    """Migrate the library data in source to target, upgrading them in the process.

    If target is None, then migration is done in place.
    """
    library_properties = None
    data_item_uuids = set()
    reader_info_list = list()
    library_updates = dict()
    deletions = list()

    target_project_storage_system = target_project_storage_system or source_project_storage_system

    # iterate through migration stages from newest to oldest, reading data items, updating them to the latest
    # version, and copying them to the new library. migration stages are the high level directories representing
    # different library versions up to 13. after version 13, files are stored in project files which have their own
    # versioning.
    for migration_stage in source_project_storage_system._get_migration_stages():

        # find all data items for the given migration stage and return a list of storage handlers.
        # examples of storage handlers are NDataHandler and HDF5Handler. these give low level access to the file.
        # every storage handle must be closed.
        storage_handlers = source_project_storage_system._find_data_items(migration_stage)

        # next, construct a list of ReaderInfo objects. ReaderInfo stores the properties portion of the data item,
        # whether it has been changed during migration, whether it is a large format file, its storage handler,
        # and an identifier key. this loop skips files that cannot be read but prints an error message.
        preliminary_reader_info_list = list()
        for storage_handler in storage_handlers:
            try:
                large_format = source_project_storage_system._is_storage_handler_large_format(storage_handler)
                properties = Migration.transform_to_latest(storage_handler.read_properties())
                reader_info = ReaderInfo(properties, [False], large_format, storage_handler, storage_handler.reference)
                preliminary_reader_info_list.append(reader_info)
            except Exception as e:
                storage_handler.close()
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

        # now read the library properties which contains the data item deletions. data item deletions exist to
        # facilitate switching between library versions. if the user deletes an item in a newer library, that item
        # is marked as deleted so that if migration is performed again, that deleted item will not be re-migrated.
        new_library_properties = source_project_storage_system._read_library_properties(migration_stage)
        for deletion in copy.deepcopy(new_library_properties.get("data_item_deletions", list())):
            if not deletion in deletions:
                deletions.append(deletion)

        # set library properties to one from the first/newest migration stage encountered with library properties.
        if library_properties is None:
            library_properties = copy.deepcopy(new_library_properties)

        # next, for each item in the list of ReaderInfo objects, migrate it to the latest version. doing this may
        # produce additional library updates in preliminary_library_updates. these are changes to the library that
        # must be made in order to move information that at one point was stored in the data item files into the
        # library. an example is a computation, which was originally stored in the data item file itself.
        preliminary_library_updates = dict()
        Migration.migrate_to_latest(preliminary_reader_info_list, preliminary_library_updates)

        # finally, for each item in the preliminary_reader_info_list, confirm that it is the latest version and then
        # check whether it has a unique UUID that hasn't been deleted, and, if so, try to copy the data item to its
        # new location. if successful, mark the data item as having been added to the new library and add any
        # preliminary library updates to the library updates list to be applied later.
        count = len(preliminary_reader_info_list)
        for index, reader_info in enumerate(preliminary_reader_info_list):
            properties = reader_info.properties
            try:
                version = properties.get("version", 0)
                if version == DataItem.DataItem.writer_version:
                    data_item_uuid = uuid.UUID(properties["uuid"])
                    if not data_item_uuid in data_item_uuids:
                        if not str(data_item_uuid) in deletions:
                            new_reader_info = target_project_storage_system._migrate_data_item(reader_info, index, count)
                            if new_reader_info:
                                reader_info_list.append(new_reader_info)
                                data_item_uuids.add(data_item_uuid)
                                library_update = preliminary_library_updates.get(data_item_uuid)
                                if library_update:
                                    library_updates[data_item_uuid] = library_update
            except Exception as e:
                logging.debug(f"Error reading {reader_info.storage_handler.reference}")
                import traceback
                traceback.print_exc()
                traceback.print_stack()

        for storage_handler in storage_handlers:
            storage_handler.close()

    assert len(reader_info_list) == len(data_item_uuids)

    # for each data item represented by a ReaderInfo object, apply its library updates. this will include
    # connections, computations, and display items. for instance, before version 13, the data item and display item
    # were both stored in the data item file; this migrates the display portion to the library properties.
    for reader_info in reader_info_list:
        properties = reader_info.properties
        properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
        version = properties.get("version", 0)
        if version == DataItem.DataItem.writer_version:
            data_item_uuid = uuid.UUID(properties.get("uuid", uuid.uuid4()))
            library_update = library_updates.get(data_item_uuid, dict())
            library_properties.setdefault("connections", list()).extend(library_update.get("connections", list()))
            library_properties.setdefault("computations", list()).extend(library_update.get("computations", list()))
            library_properties.setdefault("display_items", list()).extend(library_update.get("display_items", list()))

    connections_list = library_properties.get("connections", list())
    assert len(connections_list) == len({connection.get("uuid") for connection in connections_list})

    computations_list = library_properties.get("computations", list())
    assert len(computations_list) == len({computation.get("uuid") for computation in computations_list})

    # migrate the library properties
    Migration.migrate_library_to_latest(library_properties)

    # TODO: add consistency checks: no duplicated items [by uuid] such as connections or computations or data items

    assert library_properties["version"] == PROJECT_VERSION

    # propagate the UUID
    source_library_properties = source_project_storage_system.get_storage_properties()
    if "uuid" in source_library_properties:
        library_properties["uuid"] = source_library_properties["uuid"]

    target_project_storage_system._migrate_library_properties(library_properties, reader_info_list)


class PersistentStorageSystem(Persistence.PersistentStorageInterface):
    """Abstract base class for persistent storage which implements the persistent storage interface.

    Subclasses must implement _read_properties and _write_properties to read/write to persistent storage.

    The `load_properties` method must be called after instantiating the subclass.
    """

    def __init__(self):
        super().__init__()
        self.__properties = dict()
        self.__properties_lock = threading.RLock()
        self.__write_delay_counts = dict()
        self.__write_delay_count = 0

    def close(self) -> None:
        pass

    @abc.abstractmethod
    def _write_properties(self) -> None:
        """Write internal properties, retrieved using _get_properties, to persistent storage."""
        ...

    @abc.abstractmethod
    def _read_properties(self) -> typing.Dict:
        """Read internal properties from persistent storage."""
        ...

    def load_properties(self) -> None:
        """Read properties and store them in internal storage. Should be called immediately after instantiation."""
        with self.__properties_lock:
            self.__properties = self._read_properties()

    def get_storage_properties(self) -> typing.Dict:
        """Return the internal properties. Callers should not modify and it is ok to not return a copy."""
        return self.__properties

    def __write_properties_if_not_delayed(self, item) -> None:
        if self.__write_delay_counts.get(item, 0) == 0:
            self._write_item_properties(item)

    def _write_item_properties(self, item) -> None:
        persistent_object_parent = item.persistent_object_parent if item else None
        if not persistent_object_parent:
            if self.__write_delay_count == 0:
                self._write_properties()
        else:
            self.__write_properties_if_not_delayed(persistent_object_parent.parent)

    def get_properties(self, item: Persistence.PersistentObject) -> typing.Dict:
        return item.persistent_dict

    def __update_modified_and_get_storage_dict(self, item: Persistence.PersistentObject) -> typing.Dict:
        # update modified time on object and all parent objects in internal storage
        storage_dict = item.persistent_dict
        with self.__properties_lock:
            storage_dict["modified"] = item.modified.isoformat()
        persistent_object_parent = item.persistent_object_parent
        parent = persistent_object_parent.parent if persistent_object_parent else None
        if parent:
            self.__update_modified_and_get_storage_dict(parent)
        return storage_dict

    def insert_item(self, parent, name: str, before_index: int, item) -> None:
        # insert item in internal storage
        item.persistent_dict = item.write_to_dict()
        item.persistent_storage = self
        self._insert_item(parent, name, before_index, item)

    def remove_item(self, parent, name: str, index: int, item) -> None:
        self._remove_item(parent, name, index, item)
        item.persistent_dict = None
        item.persistent_storage = None

    def _insert_item(self, parent, name: str, before_index: int, item) -> None:
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict.setdefault(name, list())
            item_list.insert(before_index, item.persistent_dict)
        self.__write_properties_if_not_delayed(parent)

    def _remove_item(self, parent, name: str, index: int, item) -> None:
        # remove item from internal storage
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict[name]
            del item_list[index]
        self.__write_properties_if_not_delayed(parent)

    def set_item(self, parent, name: str, item) -> None:
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        if item:
            # set the item and update its persistent context
            with self.__properties_lock:
                item.persistent_dict = item.write_to_dict()
                item.persistent_storage = self
                storage_dict[name] = item.persistent_dict
        else:
            # clear the item
            with self.__properties_lock:
                storage_dict.pop(name, None)
                item.persistent_dict = None
                item.persistent_storage = None
        self.__write_properties_if_not_delayed(parent)

    def set_property(self, object, name: str, value) -> None:
        # set property in internal storage
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict[name] = value
        self.__write_properties_if_not_delayed(object)

    def clear_property(self, object, name: str) -> None:
        # clear property in internal storage
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict.pop(name, None)
        self.__write_properties_if_not_delayed(object)

    def get_storage_property(self, item, name: str) -> typing.Optional[str]:
        return None

    def read_external_data(self, item, name: str) -> typing.Any:
        return None

    def write_external_data(self, item, name: str, value) -> None:
        pass

    def reserve_external_data(self, item, name: str, data_shape: typing.Tuple[int, ...], data_dtype: numpy.dtype) -> None:
        pass

    def enter_write_delay(self, object) -> None:
        count = self.__write_delay_counts.setdefault(object, 0)
        self.__write_delay_counts[object] = count + 1

    def exit_write_delay(self, object) -> None:
        count = self.__write_delay_counts.get(object, 1)
        count -= 1
        if count == 0:
            self.__write_delay_counts.pop(object)
        else:
            self.__write_delay_counts[object] = count

    def is_write_delayed(self, item) -> bool:
        return self.__write_delay_counts.get(item, 0) > 0

    def rewrite_item(self, item) -> None:
        self.__write_properties_if_not_delayed(item)

    def read_properties(self) -> typing.Dict:
        return self.get_storage_properties()

    def enter_transaction(self) -> None:
        self.__write_delay_count += 1

    def exit_transaction(self) -> None:
        self.__write_delay_count -= 1
        if self.__write_delay_count == 0:
            self.__write_properties_if_not_delayed(None)


class FilePersistentStorageSystem(PersistentStorageSystem):
    """File based persistent storage system."""

    def __init__(self, path: pathlib.Path):
        self.__path = path
        super().__init__()

    def close(self) -> None:
        pass

    @property
    def path(self) -> pathlib.Path:
        return self.__path

    def _read_properties(self) -> typing.Dict:
        properties = dict()
        if self.__path and self.__path.exists():
            try:
                with self.__path.open("r") as fp:
                    properties = json.load(fp)
            except Exception:
                os.replace(self.__path, self.__path.with_suffix(".bak"))
        return properties

    def _write_properties(self) -> None:
        if self.__path:
            # atomically overwrite
            temp_filepath = self.__path.with_suffix(".temp")
            with temp_filepath.open("w") as fp:
                properties = Utility.clean_dict(self.get_storage_properties())
                json.dump(properties, fp)
            os.replace(temp_filepath, self.__path)


class MemoryPersistentStorageSystem(PersistentStorageSystem):
    """File based persistent storage system. Useful for testing."""

    def __init__(self, *, library_properties: typing.Dict = None):
        self.__library_properties = library_properties if library_properties is not None else dict()
        super().__init__()

    def close(self) -> None:
        pass

    def _read_properties(self) -> typing.Dict:
        return copy.deepcopy(self.__library_properties)

    def _write_properties(self) -> None:
        self.__library_properties.clear()
        self.__library_properties.update(self.get_storage_properties())

    def set_library_properties(self, library_properties: typing.Dict) -> None:
        self.__library_properties.clear()
        self.__library_properties.update(library_properties)
        self.load_properties()


class ProjectStorageSystem(PersistentStorageSystem):
    """Persistent storage system to provide special handling of data items."""

    def __init__(self):
        super().__init__()
        self.__storage_adapter_map = dict()

    def close(self) -> None:
        for storage_adapter in self.__storage_adapter_map.values():
            storage_adapter.close()
        self.__storage_adapter_map.clear()

    @abc.abstractmethod
    def _get_identifier(self) -> str: ...

    @abc.abstractmethod
    def _make_storage_handler(self, data_item: DataItem.DataItem, file_handler=None): ...

    @abc.abstractmethod
    def _find_storage_handlers(self) -> typing.List: ...

    @abc.abstractmethod
    def _is_storage_handler_large_format(self, storage_handler) -> bool: ...

    @abc.abstractmethod
    def _remove_storage_handler(self, storage_handler, *, safe: bool=False) -> None: ...

    @abc.abstractmethod
    def _restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[dict]: ...

    @abc.abstractmethod
    def _prune(self) -> None: ...

    @abc.abstractmethod
    def _migrate_data_item(self, reader_info: ReaderInfo, index: int, count: int) -> typing.Optional[ReaderInfo]: ...

    @abc.abstractmethod
    def _migrate_library_properties(self, library_properties: typing.Dict, reader_info_list: typing.List[ReaderInfo]) -> None: ...

    @abc.abstractmethod
    def _get_migration_stages(self) -> typing.List[typing.Tuple[pathlib.Path, pathlib.Path]]: ...

    @abc.abstractmethod
    def _read_library_properties(self, migration_stage) -> typing.Dict: ...

    @abc.abstractmethod
    def _find_data_items(self, migration_stage) -> typing.List: ...

    def get_identifier(self) -> str:
        return self._get_identifier()

    @property
    def _data_properties_map(self) -> typing.Dict:
        return self.__storage_adapter_map

    def reset(self) -> None:
        self.__storage_adapter_map = dict()

    def get_persistent_dict(self, name: str, item_uuid: uuid.UUID) -> typing.Dict:
        if name == "data_items":
            return self._data_properties_map[item_uuid].properties
        for item_d in self.get_storage_properties()[name]:
            if uuid.UUID(item_d["uuid"]) == item_uuid:
                return item_d
        assert False

    def read_project_properties(self) -> typing.Dict:
        """Read data items from the data reference handler and return as a dict.

        The dict may contain keys for data_items, display_items, data_structures, connections, and computations.
        """
        storage_handlers = self._find_storage_handlers()

        reader_info_list = list()
        for storage_handler in storage_handlers:
            try:
                large_format = self._is_storage_handler_large_format(storage_handler)
                properties = Migration.transform_to_latest(storage_handler.read_properties())
                reader_info = ReaderInfo(properties, [False], large_format, storage_handler, storage_handler.reference)
                reader_info_list.append(reader_info)
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

        # to allow later writing back to storage, associate the data items with their storage adapters
        for reader_info in reader_info_list:
            storage_handler = reader_info.storage_handler
            properties = reader_info.properties
            data_item_uuid = uuid.UUID(properties["uuid"])
            storage_adapter = DataItemStorageAdapter(storage_handler, properties)
            old_storage_adapter = self.__storage_adapter_map.pop(data_item_uuid, None)
            if old_storage_adapter:
                old_storage_adapter.close()
            self.__storage_adapter_map[data_item_uuid] = storage_adapter

        properties_copy = self._read_properties()

        # ensure unique connections
        connections_list = properties_copy.get("connections", list())
        assert len(connections_list) == len({connection.get("uuid") for connection in connections_list})

        # ensure unique computations
        computations_list = properties_copy.get("computations", list())
        assert len(computations_list) == len({computation.get("uuid") for computation in computations_list})

        for reader_info in reader_info_list:
            data_item_properties = Utility.clean_dict(reader_info.properties if reader_info.properties else dict())
            if data_item_properties.get("version", 0) == DataItem.DataItem.writer_version:
                data_item_properties["__large_format"] = reader_info.large_format
                properties_copy.setdefault("data_items", list()).append(data_item_properties)

        def data_item_created(data_item_properties: typing.Mapping) -> str:
            return data_item_properties.get("created", "1900-01-01T00:00:00.000000")

        data_items_copy = sorted(properties_copy.get("data_items", list()), key=data_item_created)
        if len(data_items_copy) > 0:
            properties_copy["data_items"] = data_items_copy

        return properties_copy

    # override
    def _write_item_properties(self, item):
        if item and isinstance(item, DataItem.DataItem):
            self.__rewrite_data_item_properties(item)
        else:
            super()._write_item_properties(item)

    # override
    def _insert_item(self, parent, name: str, before_index: int, item) -> None:
        if isinstance(item, DataItem.DataItem):
            item_uuid = item.uuid
            storage_handler = self._make_storage_handler(item)
            assert item_uuid not in self.__storage_adapter_map
            storage_adapter = DataItemStorageAdapter(storage_handler, item.persistent_dict)
            self.__storage_adapter_map[item_uuid] = storage_adapter
        else:
            super()._insert_item(parent, name, before_index, item)

    # override
    def _remove_item(self, parent, name: str, index: int, item) -> None:
        if isinstance(item, DataItem.DataItem):
            assert item.uuid in self.__storage_adapter_map
            storage = self.__storage_adapter_map.get(item.uuid)
            self._remove_storage_handler(storage.storage_handler, safe=True)
            self.__storage_adapter_map.pop(item.uuid).close()
        else:
            super()._remove_item(parent, name, index, item)

    # override
    def get_storage_property(self, item, name: str) -> typing.Optional[str]:
        if isinstance(item, DataItem.DataItem):
            return self.__get_data_item_property(item, name)
        return super().get_storage_property(item, name)

    # override
    def read_external_data(self, item, name: str) -> typing.Any:
        if isinstance(item, DataItem.DataItem) and name == "data":
            return self.__read_data_item_data(item)
        return super().read_external_data(item, name)

    # override
    def write_external_data(self, item, name: str, value) -> None:
        if isinstance(item, DataItem.DataItem) and name == "data":
            self.__write_data_item_data(item, value)
        else:
            super().write_external_data(item, name, value)

    # override
    def reserve_external_data(self, item, name: str, data_shape: typing.Tuple[int, ...], data_dtype: numpy.dtype) -> None:
        if isinstance(item, DataItem.DataItem) and name == "data":
            self.__reserve_data_item_data(item, data_shape, data_dtype)
        else:
            super().reserve_external_data(item, name, data_shape, data_dtype)

    # override
    def rewrite_item(self, item) -> None:
        if isinstance(item, DataItem.DataItem):
            self.__rewrite_data_item_properties(item)
        else:
            super().rewrite_item(item)

    def restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[dict]:
        return self.__restore_item(data_item_uuid)

    def prune(self) -> None:
        self._prune()

    def find_data_items(self) -> typing.List:
        return self._find_storage_handlers()

    def migrate_to_latest(self) -> None:
        migrate_to_latest(self)

    def __get_data_item_properties(self, data_item: DataItem.DataItem) -> typing.Dict:
        return self.__storage_adapter_map.get(data_item.uuid).properties

    def __get_data_item_property(self, data_item: DataItem.DataItem, name: str) -> typing.Optional[str]:
        if name == "file_path":
            storage = self.__storage_adapter_map.get(data_item.uuid)
            return storage.storage_handler.reference if storage else None
        return None

    def __read_data_item_data(self, data_item: DataItem.DataItem):
        storage = self.__storage_adapter_map.get(data_item.uuid)
        return storage.load_data(data_item)

    def __write_data_item_data(self, data_item: DataItem.DataItem, data) -> None:
        storage = self.__storage_adapter_map.get(data_item.uuid)
        if not self.is_write_delayed(data_item):
            storage.update_data(data_item, data)

    def __reserve_data_item_data(self, data_item: DataItem.DataItem, data_shape: typing.Tuple[int, ...], data_dtype: numpy.dtype) -> None:
        storage = self.__storage_adapter_map.get(data_item.uuid)
        storage.reserve_data(data_item, data_shape, data_dtype)

    def __rewrite_data_item_properties(self, data_item: DataItem.DataItem) -> None:
        if not self.is_write_delayed(data_item):
            self.__storage_adapter_map.get(data_item.uuid).rewrite_item(data_item)

    def __restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[dict]:
        return self._restore_item(data_item_uuid)


class FileProjectStorageSystem(ProjectStorageSystem):

    _file_handlers = [NDataHandler.NDataHandler, HDF5Handler.HDF5Handler]

    def __init__(self, project_path: pathlib.Path, project_data_path: pathlib.Path = None):
        super().__init__()
        self.__project_path = project_path
        self.__project_data_path = project_data_path

    def load_properties(self) -> None:
        super().load_properties()
        project_data_folder_paths = list()
        for project_data_folder in self.get_storage_properties().get("project_data_folders", list()):
            project_data_folder_path = pathlib.Path(project_data_folder)
            if not project_data_folder_path.is_absolute():
                project_data_folder_path = self.__project_path.parent / project_data_folder_path
            project_data_folder_paths.append(project_data_folder_path)
        self.__project_data_path = project_data_folder_paths[0] if len(project_data_folder_paths) > 0 else self.__project_data_path

    @property
    def project_path(self) -> pathlib.Path:
        return self.__project_path

    def _read_properties(self) -> typing.Dict:
        properties = dict()
        if self.__project_path and self.__project_path.exists():
            try:
                with self.__project_path.open("r") as fp:
                    properties = json.load(fp)
            except Exception:
                os.replace(self.__project_path, self.__project_path.with_suffix(".bak"))
        return properties

    def _write_properties(self) -> None:
        self.__write_properties_inner(self.get_storage_properties())

    def __write_properties_inner(self, properties: typing.Dict) -> None:
        if self.__project_path:
            # atomically overwrite
            temp_filepath = self.__project_path.with_suffix(".temp")
            with temp_filepath.open("w") as fp:
                properties = Utility.clean_dict(properties)
                project_data_paths = list()
                for project_data_path in [self.__project_data_path] if self.__project_data_path else []:
                    if project_data_path.parent == self.__project_path.parent:
                        project_data_path = project_data_path.relative_to(project_data_path.parent)
                    project_data_paths.append(project_data_path)
                project_uuid = uuid.uuid4()
                properties.setdefault("uuid", str(project_uuid))
                properties["project_data_folders"] = [str(project_data_path) for project_data_path in project_data_paths]
                json.dump(properties, fp)
            os.replace(temp_filepath, self.__project_path)

    def _get_identifier(self) -> str:
        return str(self.__project_path)

    def _make_storage_handler(self, data_item: DataItem.DataItem, file_handler=None):
        # if there are two handlers, first is small, second is large
        # if there is only one handler, it is used in all cases
        large_format = hasattr(data_item, "large_format") and data_item.large_format
        file_handler = file_handler if file_handler else (self._file_handlers[-1] if large_format else self._file_handlers[0])
        return file_handler.make(self.__project_data_path / self.__get_base_path(data_item))

    def _find_storage_handlers(self) -> typing.List:
        return self.__find_storage_handlers(self.__project_data_path)

    def _is_storage_handler_large_format(self, storage_handler) -> bool:
        return isinstance(storage_handler, HDF5Handler.HDF5Handler)

    def _remove_storage_handler(self, storage_handler, *, safe: bool=False) -> None:
        file_path = pathlib.Path(storage_handler.reference)
        file_name = file_path.parts[-1]
        trash_dir = self.__project_data_path / "trash"
        new_file_path = trash_dir / file_name
        storage_handler.prepare_move()  # moving files in the storage handler requires it to be closed.
        # TODO: move this functionality to the storage handler.
        if safe and not os.path.exists(new_file_path):
            trash_dir.mkdir(exist_ok=True)
            shutil.move(file_path, new_file_path)
        storage_handler.remove()

    def _restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[dict]:
        data_item_uuid_str = str(data_item_uuid)
        trash_dir = self.__project_data_path / "trash"
        storage_handlers = self.__find_storage_handlers(trash_dir, skip_trash=False)
        try:
            for storage_handler in storage_handlers:
                properties = Migration.transform_to_latest(storage_handler.read_properties())
                if properties.get("uuid", None) == data_item_uuid_str:
                    data_item = DataItem.DataItem(item_uuid=data_item_uuid)
                    data_item.begin_reading()
                    data_item.read_from_dict(properties)
                    data_item.finish_reading()
                    old_file_path = storage_handler.reference
                    new_file_path = storage_handler.make_path(self.__project_data_path / self.__get_base_path(data_item))
                    if not os.path.exists(new_file_path):
                        os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
                        shutil.move(old_file_path, new_file_path)
                    self._make_storage_handler(data_item, file_handler=None).close()  # what's this line for?
                    properties["__large_format"] = isinstance(storage_handler, HDF5Handler.HDF5Handler)
                    return properties
        finally:
            for storage_handler in storage_handlers:
                storage_handler.close()
        return None

    def _prune(self) -> None:
        if self.__project_data_path:
            trash_dir = self.__project_data_path / "trash"
            for file_path in trash_dir.rglob("*"):
                # the date is not a reliable way of determining the age since a user may trash an old file. for now,
                # we just delete anything in the trash at startup. future version may have an index file for
                # tracking items in the trash. when items are again retained in the trash, update the disabled
                # test_delete_and_undelete_from_file_storage_system_restores_data_item_after_reload
                file_path.unlink()

    @property
    def _trash_dir(self) -> pathlib.Path:
        return self.__project_data_path / "trash"

    def _migrate_data_item(self, reader_info: ReaderInfo, index: int, count: int) -> typing.Optional[ReaderInfo]:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
        data_item_uuid = uuid.UUID(properties["uuid"])
        old_data_item = DataItem.DataItem(item_uuid=data_item_uuid)
        old_data_item.begin_reading()
        old_data_item.read_from_dict(properties)
        old_data_item.finish_reading()
        old_data_item_path = storage_handler.reference
        # ask the storage system for the file handler for the data item path
        file_handler = self.__get_file_handler_for_file(str(old_data_item_path))
        # ask the storage system to make a storage handler (an instance of a file handler) for the data item
        # this ensures that the storage handler (file format) is the same as before.
        with contextlib.closing(self._make_storage_handler(old_data_item, file_handler)) as target_storage_handler:
            if target_storage_handler and storage_handler.reference != target_storage_handler.reference:
                os.makedirs(os.path.dirname(target_storage_handler.reference), exist_ok=True)
                shutil.copyfile(storage_handler.reference, target_storage_handler.reference)
                target_storage_handler.write_properties(Migration.transform_from_latest(copy.deepcopy(properties)), datetime.datetime.now())
                logging.getLogger("migration").info(f"Copying data item ({index + 1}/{count}) {data_item_uuid} to new library.")
                return ReaderInfo(properties, [False], self._is_storage_handler_large_format(target_storage_handler), target_storage_handler, target_storage_handler.reference)
        logging.getLogger("migration").warning(f"Unable to copy data item {data_item_uuid} to new library.")
        return None

    def _migrate_library_properties(self, library_properties: typing.Dict, reader_info_list: typing.List[ReaderInfo]) -> None:
        self.__write_properties_inner(library_properties)
        for reader_info in reader_info_list:
            data_item_properties = Utility.clean_dict(reader_info.properties if reader_info.properties else dict())
            if data_item_properties.get("version", 0) == DataItem.DataItem.writer_version:
                file_datetime = DataItem.DatetimeToStringConverter().convert_back(data_item_properties.get("created", "1900-01-01T00:00:00.000000"))
                reader_info.storage_handler.write_properties(reader_info.properties, file_datetime)

    @staticmethod
    def _get_migration_paths(library_path: pathlib.Path) -> typing.List[typing.Tuple[pathlib.Path, pathlib.Path]]:
        return [
            (library_path / "Nion Swift Library 13.nslib", library_path / "Nion Swift Data 13"),
            (library_path / "Nion Swift Library 12.nslib", library_path / "Nion Swift Data 12"),
            (library_path / "Nion Swift Workspace.nslib", library_path / "Nion Swift Data 11"),
            (library_path / "Nion Swift Workspace.nslib", library_path / "Nion Swift Data 10"),
            (library_path / "Nion Swift Workspace.nslib", library_path / "Nion Swift Data"),
        ]

    def _get_migration_stages(self) -> typing.List[typing.Tuple[pathlib.Path, pathlib.Path]]:
        return self._get_migration_paths(self.__project_path.parent)

    def _read_library_properties(self, migration_stage) -> typing.Dict:
        properties = dict()
        project_path = migration_stage[0]
        if project_path and os.path.exists(project_path):
            try:
                with project_path.open("r") as fp:
                    properties = json.load(fp)
            except Exception:
                os.replace(project_path, project_path.with_suffix(".bak"))
        return properties

    def _find_data_items(self, migration_stage) -> typing.List:
        return self.__find_storage_handlers(migration_stage[1])

    def __get_base_path(self, data_item: DataItem.DataItem) -> pathlib.Path:
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
        return pathlib.Path(*path_components)

    def __get_file_handler_for_file(self, path: str):
        for file_handler in self._file_handlers:
            if file_handler.is_matching(path):
                return file_handler
        return None

    def __find_storage_handlers(self, directory: pathlib.Path, *, skip_trash=True) -> typing.List:
        storage_handlers = list()
        if directory and directory.exists():
            absolute_file_paths = set()
            for file_path in directory.rglob("*"):
                if not skip_trash or file_path.parent.name != "trash":
                    if not file_path.name.startswith("."):
                        absolute_file_paths.add(str(file_path))
            for file_handler in self._file_handlers:
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


class MemoryStorageHandler:

    def __init__(self, uuid, data_properties_map, data_map, data_read_event):
        self.__uuid = uuid
        self.__data_properties_map = data_properties_map
        self.__data_map = data_map
        self.__data_read_event = data_read_event

    def close(self):
        self.__uuid = None
        self.__data_properties_map = None
        self.__data_map = None

    @property
    def reference(self):
        return str(self.__uuid)

    def read_properties(self):
        return copy.deepcopy(self.__data_properties_map.get(self.__uuid, dict()))

    def read_data(self):
        self.__data_read_event.fire(self.__uuid)
        return self.__data_map.get(self.__uuid)

    def write_properties(self, properties, file_datetime):
        self.__data_properties_map[self.__uuid] = Utility.clean_dict(properties)

    def write_data(self, data, file_datetime):
        self.__data_map[self.__uuid] = data.copy()

    def reserve_data(self, data_shape: typing.Tuple[int, ...], data_dtype: numpy.dtype, file_datetime) -> None:
        self.__data_map[self.__uuid] = numpy.zeros(data_shape, data_dtype)


class MemoryProjectStorageSystem(ProjectStorageSystem):

    def __init__(self, *, library_properties: typing.Dict = None, data_properties_map: typing.Dict = None, data_map: typing.Dict = None, trash_map: typing.Dict = None, data_read_event: Event.Event = None):
        super().__init__()
        self.__library_properties = library_properties if library_properties is not None else dict()
        self.__data_properties_map = data_properties_map if data_properties_map is not None else dict()
        self.__data_map = data_map if data_map is not None else dict()
        self.__trash_map = trash_map if trash_map is not None else dict()
        self._test_data_read_event = data_read_event or Event.Event()

    def _read_properties(self) -> typing.Dict:
        return copy.deepcopy(self.__library_properties)

    def _write_properties(self) -> None:
        self.__library_properties.clear()
        self.__library_properties.update(copy.deepcopy(self.get_storage_properties()))

    def _get_identifier(self) -> str:
        return "memory"

    def _make_storage_handler(self, data_item: DataItem.DataItem, file_handler=None):
        data_item_uuid_str = str(data_item.uuid)
        return MemoryStorageHandler(data_item_uuid_str, self.__data_properties_map, self.__data_map, self._test_data_read_event)

    def _find_storage_handlers(self) -> typing.List:
        storage_handlers = list()
        for key in sorted(self.__data_properties_map):
            self.__data_properties_map[key].setdefault("uuid", str(uuid.uuid4()))
            storage_handlers.append(MemoryStorageHandler(key, self.__data_properties_map, self.__data_map, self._test_data_read_event))
        return storage_handlers

    def _is_storage_handler_large_format(self, storage_handler) -> bool:
        return False

    def _remove_storage_handler(self, storage_handler, *, safe: bool=False) -> None:
        storage_handler_reference = storage_handler.reference
        data = self.__data_map.pop(storage_handler_reference, None)
        properties = self.__data_properties_map.pop(storage_handler_reference)
        if safe:
            assert storage_handler_reference not in self.__trash_map
            self.__trash_map[storage_handler_reference] = {"data": data, "properties": properties}
        storage_handler.close()  # moving files in the storage handler requires it to be closed.

    def _restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[dict]:
        data_item_uuid_str = str(data_item_uuid)
        trash_entry = self.__trash_map.pop(data_item_uuid_str)
        assert data_item_uuid_str not in self.__data_properties_map
        assert data_item_uuid_str not in self.__data_map
        self.__data_properties_map[data_item_uuid_str] = Migration.transform_to_latest(trash_entry["properties"])
        self.__data_map[data_item_uuid_str] = trash_entry["data"]
        properties = self.__data_properties_map.get(data_item_uuid_str, dict())
        properties["__large_format"] = False
        properties = Migration.transform_to_latest(properties)
        return properties

    def _prune(self) -> None:
        pass  # disabled for testing self.__trash_map = dict()

    def _migrate_data_item(self, reader_info: ReaderInfo, index: int, count: int) -> typing.Optional[ReaderInfo]:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
        if reader_info.changed_ref[0]:
            self.__data_properties_map[storage_handler.reference] = Migration.transform_from_latest(copy.deepcopy(properties))
        return reader_info

    def _migrate_library_properties(self, library_properties: typing.Dict, reader_info_list: typing.List[ReaderInfo]) -> None:
        self.__library_properties.clear()
        self.__library_properties.update(library_properties)

        data_properties_map = dict()

        for reader_info in reader_info_list:
            data_item_properties = Utility.clean_dict(reader_info.properties if reader_info.properties else dict())
            if data_item_properties.get("version", 0) == DataItem.DataItem.writer_version:
                data_item_properties["__large_format"] = reader_info.large_format
                data_properties_map[reader_info.identifier] = data_item_properties

        def data_item_created(data_item_properties: typing.Mapping) -> str:
            return data_item_properties[1].get("created", "1900-01-01T00:00:00.000000")

        data_properties_map = {k: v for k, v in sorted(data_properties_map.items(), key=data_item_created)}

        self.__data_properties_map.clear()
        self.__data_properties_map.update(data_properties_map)

    def _get_migration_stages(self) -> typing.List[typing.Tuple[pathlib.Path, pathlib.Path]]:
        return [(pathlib.Path(), pathlib.Path())]

    def _read_library_properties(self, migration_stage) -> typing.Dict:
        return copy.deepcopy(self.__library_properties)

    def _find_data_items(self, migration_stage) -> typing.List:
        return self._find_storage_handlers()


def make_storage_system(profile_context, d: typing.Dict) -> typing.Optional[ProjectStorageSystem]:
    if d.get("type") == "project_index":
        project_path = pathlib.Path(d.get("project_path"))
        return FileProjectStorageSystem(project_path)
    elif d.get("type") == "project_folder":
        project_folder_path = pathlib.Path(d.get("project_folder_path"))
        for project_file, project_dir in FileProjectStorageSystem._get_migration_paths(project_folder_path):
            if project_file.exists():
                return FileProjectStorageSystem(project_file, project_dir)
        return None
    elif d.get("type") == "memory":
        storage_system_uuid = uuid.UUID(d.get("uuid"))
        # the profile context must be valid here.
        new_project_properties = profile_context.x_project_properties.setdefault(storage_system_uuid, {"version": PROJECT_VERSION, "uuid": str(storage_system_uuid)})
        new_data_properties_map = profile_context.x_data_properties_map.setdefault(storage_system_uuid, dict())
        new_data_map = profile_context.x_data_map.setdefault(storage_system_uuid, dict())
        new_trash_map = profile_context.x_trash_map.setdefault(storage_system_uuid, dict())
        library_properties = d.get("project_properties", new_project_properties)
        data_properties_map = d.get("data_properties_map", new_data_properties_map)
        data_map = d.get("data_map", new_data_map)
        trash_map = d.get("trash_map", new_trash_map)
        if profile_context.project_properties is None:
            profile_context.project_properties = library_properties
        if profile_context.data_properties_map is None:
            profile_context.data_properties_map = data_properties_map
        if profile_context.data_map is None:
            profile_context.data_map = data_map
        if profile_context.trash_map is None:
            profile_context.trash_map = trash_map
        return MemoryProjectStorageSystem(library_properties=library_properties, data_properties_map=data_properties_map, data_map=data_map, trash_map=trash_map)
    return None
