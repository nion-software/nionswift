from __future__ import annotations

import abc
import contextlib
import copy
import dataclasses
import datetime
import json
import logging
import traceback

import numpy
import numpy.typing
import os.path
import pathlib
import shutil
import threading
import typing
import uuid

from nion.swift.model import DataItem
from nion.swift.model import HDF5Handler
from nion.swift.model import Migration
from nion.swift.model import Model
from nion.swift.model import NDataHandler
from nion.swift.model import Persistence
from nion.swift.model import StorageHandler
from nion.swift.model import Utility
from nion.utils import Event


# define the versions that get stored in the JSON files
PROFILE_VERSION = 2
PROJECT_VERSION = 3
PROJECT_VERSION_0_14 = 2


PersistentDictType = typing.Dict[str, typing.Any]
_NDArray = numpy.typing.NDArray[typing.Any]
_CreateStorageHandlerFn = typing.Type[StorageHandler.StorageHandler]


class ReaderInfo:
    def __init__(self,
                 properties: PersistentDictType,
                 changed_ref: typing.List[bool],
                 large_format: bool,
                 storage_handler: StorageHandler.StorageHandler,
                 identifier: str) -> None:
        self.properties = properties
        self.changed_ref = changed_ref
        self.large_format = large_format
        self.storage_handler = storage_handler
        self.identifier = identifier


class DataItemStorageAdapter:
    """Persistent storage for writing data item properties, relationships, and data to its storage handler."""

    def __init__(self, storage_handler: StorageHandler.StorageHandler, properties: PersistentDictType) -> None:
        self.__storage_handler = storage_handler
        self.__properties = properties

    def close(self) -> None:
        if self.__storage_handler:
            self.__storage_handler.close()
            self.__storage_handler = typing.cast(StorageHandler.StorageHandler, None)

    @property
    def properties(self) -> PersistentDictType:
        return self.__properties

    @property
    def storage_handler(self) -> StorageHandler.StorageHandler:
        return self.__storage_handler

    def rewrite_item(self, item: Persistence.PersistentObject) -> None:
        file_datetime = getattr(item, "created_local")
        self.__storage_handler.write_properties(Migration.transform_from_latest(copy.deepcopy(self.__properties)), file_datetime)

    def update_data(self, item: Persistence.PersistentObject, data: typing.Optional[_NDArray]) -> None:
        file_datetime = getattr(item, "created_local")
        if data is not None:
            self.__storage_handler.write_data(data, file_datetime)

    def reserve_data(self, item: Persistence.PersistentObject, data_shape: typing.Tuple[int, ...], data_dtype: numpy.typing.DTypeLike) -> None:
        file_datetime = getattr(item, "created_local")
        self.__storage_handler.reserve_data(data_shape, data_dtype, file_datetime)

    def load_data(self, item: Persistence.PersistentObject) -> typing.Optional[_NDArray]:
        return self.__storage_handler.read_data()


class MigrationReader(typing.Protocol):

    def get_storage_properties(self) -> PersistentDictType: ...

    def _get_migration_stages(self) -> typing.Sequence[ProjectStorageSystemMigrationStage]: ...

    def _find_data_items(self, migration_stage: ProjectStorageSystemMigrationStage) -> typing.Sequence[StorageHandler.StorageHandler]: ...

    def _is_storage_handler_large_format(self, storage_handler: StorageHandler.StorageHandler) -> bool: ...

    def _read_library_properties(self, migration_stage: ProjectStorageSystemMigrationStage) -> PersistentDictType: ...


class MigrationWriter(typing.Protocol):

    def _migrate_data_item(self, reader_info: ReaderInfo, index: int, count: int) -> typing.Optional[ReaderInfo]: ...

    def _migrate_library_properties(self, library_properties: PersistentDictType, reader_info_list: typing.List[ReaderInfo]) -> None: ...


def migrate_to_latest(source_project_storage_system: MigrationReader,
                      target_project_storage_system: MigrationWriter) -> None:
    """Migrate the library data in source to target, upgrading them in the process.

    If target is None, then migration is done in place.
    """
    library_properties = None
    data_item_uuids = set()
    reader_info_list = list()
    library_updates: typing.Dict[uuid.UUID, typing.Dict[str, typing.Any]] = dict()
    deletions = list()

    # iterate through migration stages from newest to oldest, reading data items, updating them to the latest
    # version, and copying them to the new library. migration stages are the high level directories representing
    # different library versions up to 13. after version 13, files are stored in project files which have their own
    # versioning. run newest to oldest so that deletions in newer libraries won't be migrated; nor will data items
    # in older projects with the same uuid in a newer project.

    for migration_stage in source_project_storage_system._get_migration_stages():

        # find all data items for the given migration stage and return a list of storage handlers.
        # examples of storage handlers are NDataHandler and HDF5Handler. these give low level access to the file.
        # every storage handler must be closed.
        storage_handlers = source_project_storage_system._find_data_items(migration_stage)

        # next, construct a list of ReaderInfo objects. ReaderInfo stores the properties portion of the data item,
        # whether it has been changed during migration, whether it is a large format file, its storage handler,
        # and an identifier key. this loop skips files that cannot be read but prints an error message.
        preliminary_reader_info_list: typing.List[ReaderInfo] = list()
        for storage_handler in storage_handlers:
            try:
                large_format = source_project_storage_system._is_storage_handler_large_format(storage_handler)
                storage_handler_properties = storage_handler.read_properties()
                assert storage_handler_properties is not None
                properties = Migration.transform_to_latest(storage_handler_properties)
                reader_info = ReaderInfo(properties, [False], large_format, storage_handler, storage_handler.reference)
                preliminary_reader_info_list.append(reader_info)
            except Exception:
                storage_handler.close()
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()
            storage_handler.prepare_move()

        # now read the library properties which contains the data item deletions. data item deletions exist to
        # facilitate switching between library versions. if the user deletes an item in a newer library, that item
        # is marked as deleted so that if migration is performed again, that deleted item will not be re-migrated.
        new_library_properties = source_project_storage_system._read_library_properties(migration_stage)
        for deletion in copy.deepcopy(new_library_properties.get("data_item_deletions", list())):
            if deletion not in deletions:
                deletions.append(deletion)

        # set library properties to one from the first/newest migration stage encountered with library properties.
        if library_properties is None:
            library_properties = copy.deepcopy(new_library_properties)

        # next, for each item in the list of ReaderInfo objects, migrate it to the latest version. doing this may
        # produce additional library updates in preliminary_library_updates. these are changes to the library that
        # must be made in order to move information that at one point was stored in the data item files into the
        # library. an example is a computation, which was originally stored in the data item file itself.
        preliminary_library_updates: typing.Dict[uuid.UUID, PersistentDictType] = dict()
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
                    if data_item_uuid not in data_item_uuids:
                        if not str(data_item_uuid) in deletions:
                            new_reader_info = target_project_storage_system._migrate_data_item(reader_info, index, count)
                            if new_reader_info:
                                reader_info_list.append(new_reader_info)
                                data_item_uuids.add(data_item_uuid)
                                library_update = preliminary_library_updates.get(data_item_uuid)
                                if library_update:
                                    library_updates[data_item_uuid] = library_update
            except Exception:
                logging.debug(f"Error reading {reader_info.storage_handler.reference}")
                import traceback
                traceback.print_exc()
                traceback.print_stack()

        for storage_handler in storage_handlers:
            storage_handler.close()

    assert len(reader_info_list) == len(data_item_uuids)

    assert library_properties is not None

    # for each data item represented by a ReaderInfo object, apply its library updates. this will include
    # connections, computations, and display items. for instance, before version 13, the data item and display item
    # were both stored in the data item file; this migrates the display portion to the library properties.
    for reader_info in reader_info_list:
        properties = reader_info.properties
        properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
        version = properties.get("version", 0)
        if version == DataItem.DataItem.writer_version:
            data_item_uuid = uuid.UUID(typing.cast(str, properties.get("uuid", str(uuid.uuid4()))))
            library_update = library_updates.get(data_item_uuid, dict())
            assert library_update is not None
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
    if source_library_properties and "uuid" in source_library_properties:
        library_properties["uuid"] = source_library_properties["uuid"]

    target_project_storage_system._migrate_library_properties(library_properties, reader_info_list)


class PersistentStorageSystem(Persistence.PersistentStorageInterface):
    """Abstract base class for persistent storage which implements the persistent storage interface.

    Subclasses must implement _read_properties and _write_properties to read/write to persistent storage.

    The `load_properties` method must be called after instantiating the subclass.
    """

    def __init__(self) -> None:
        super().__init__()
        self.__identifier = str(uuid.uuid4())  # only used when subclasses do not override
        self.__properties: PersistentDictType = dict()
        self.__properties_lock = threading.RLock()
        self.__write_delay_counts: typing.Dict[Persistence.PersistentObject, int] = dict()
        self.__write_delay_count = 0

    def close(self) -> None:
        pass

    def reset(self) -> None:
        pass

    def get_identifier(self) -> str:
        return self.__identifier

    @abc.abstractmethod
    def _write_properties(self) -> None:
        """Write internal properties, retrieved using _get_properties, to persistent storage."""
        ...

    @abc.abstractmethod
    def _read_properties(self) -> PersistentDictType:
        """Read internal properties from persistent storage."""
        ...

    def __set_persistent_storage(self, item: Persistence.PersistentObject, persistent_dict: typing.Optional[Persistence.PersistentDictType], persistent_storage: typing.Optional[Persistence.PersistentStorageInterface]) -> None:
        persistent_storage = typing.cast(typing.Optional[PersistentStorageSystem], persistent_storage)
        if persistent_storage:
            persistent_storage._unregister_persistent_dict(item)
        item.persistent_storage = persistent_storage
        if persistent_storage:
            persistent_storage._register_persistent_dict(item, persistent_dict)
        for key in item.item_names:
            component_item = item.get_item(key)
            if component_item:
                d = item.persistent_storage._get_item_persistent_dict(item, key) if item.persistent_storage else None
                self.__set_persistent_storage(component_item, d if persistent_dict is not None else None, item.persistent_storage if persistent_dict is not None else None)
        for key in item.relationship_names:
            for index, relationship_item in enumerate(item.get_relationship_items(key)):
                d = item.persistent_storage._get_relationship_persistent_dict(item, relationship_item, key, index) if item.persistent_storage else None
                self.__set_persistent_storage(relationship_item, d if persistent_dict is not None else None, item.persistent_storage if persistent_dict is not None else None)

    def set_root_item(self, item: Persistence.PersistentObject) -> None:
        """Set the storage system for this item."""
        self.__set_persistent_storage(item, self.get_storage_properties(), self)

    def unload_item(self, item: Persistence.PersistentObject) -> None:
        self._unregister_persistent_dict(item)

    def load_properties(self) -> None:
        """Read properties and store them in internal storage. Should be called immediately after instantiation."""
        with self.__properties_lock:
            self.__properties = self._read_properties()

    def read_project_properties(self) -> typing.Tuple[PersistentDictType, typing.Sequence[Persistence.ReaderError]]:
        # dummy implementation for now until this is combined with load_properties.
        # subclass may override.
        return dict(), list()

    def get_storage_properties(self) -> PersistentDictType:
        """Return the internal properties. Callers should not modify; it is ok to not return a copy."""
        return self.__properties

    def migrate_to_latest(self) -> None:
        pass

    def _register_persistent_dict(self, item: Persistence.PersistentObject, persistent_dict: typing.Optional[PersistentDictType]) -> None:
        setattr(item, "__persistent_dict", persistent_dict)

    def _unregister_persistent_dict(self, item: Persistence.PersistentObject) -> None:
        setattr(item, "__persistent_dict", None)

    def _get_persistent_dict(self, item: Persistence.PersistentObject) -> typing.Optional[PersistentDictType]:
        return getattr(item, "__persistent_dict", None)

    def _get_item_persistent_dict(self, container: Persistence.PersistentObject, key: str) -> typing.Optional[PersistentDictType]:
        d = getattr(container, "__persistent_dict", None)
        return d[key] if d is not None else None

    def _get_relationship_persistent_dict(self, container: Persistence.PersistentObject, item: Persistence.PersistentObject, key: str, index: int) -> typing.Optional[PersistentDictType]:
        d = getattr(container, "__persistent_dict", None)
        return d[key][index] if d is not None else None

    def _get_relationship_persistent_dict_by_uuid(self, container: Persistence.PersistentObject, item: Persistence.PersistentObject, key: str) -> typing.Optional[PersistentDictType]:
        d = getattr(container, "__persistent_dict", None)
        if d is not None:
            item_uuid = str(item.uuid)
            for item_d in d.get(key, list()):
                if item_d.get("uuid") == item_uuid:  # a little dangerous, comparing the uuid str's, significantly faster
                    return typing.cast(PersistentDictType, item_d)
        return None

    def __write_properties_if_not_delayed(self, item: typing.Optional[Persistence.PersistentObject]) -> None:
        if not item or self.__write_delay_counts.get(item, 0) == 0:
            self._write_item_properties(item)

    def _write_item_properties(self, item: typing.Optional[Persistence.PersistentObject]) -> None:
        persistent_object_parent = item.persistent_object_parent if item else None
        if not persistent_object_parent:
            if self.__write_delay_count == 0:
                self._write_properties()
        else:
            self.__write_properties_if_not_delayed(persistent_object_parent.parent)

    def get_properties(self, item: Persistence.PersistentObject) -> typing.Optional[PersistentDictType]:
        return self._get_persistent_dict(item)

    def __update_modified_and_get_storage_dict(self, item: Persistence.PersistentObject) -> PersistentDictType:
        # update modified time on object and all parent objects in internal storage
        storage_dict = self._get_persistent_dict(item)
        assert storage_dict is not None
        with self.__properties_lock:
            storage_dict["modified"] = item.modified.isoformat()
        persistent_object_parent = item.persistent_object_parent
        parent = persistent_object_parent.parent if persistent_object_parent else None
        if parent:
            self.__update_modified_and_get_storage_dict(parent)
        return storage_dict

    def insert_relationship_item(self, parent: Persistence.PersistentObject, name: str, before_index: int, item: Persistence.PersistentObject) -> None:
        # insert item in internal storage
        self.__set_persistent_storage(item, item.write_to_dict(), self)
        self._insert_item(parent, name, before_index, item)

    def remove_relationship_item(self, parent: Persistence.PersistentObject, name: str, index: int, item: Persistence.PersistentObject) -> None:
        self._remove_item(parent, name, index, item)
        self.__set_persistent_storage(item, None, None)

    def load_relationship_item(self, parent: Persistence.PersistentObject, name: str, before_index: int, item: Persistence.PersistentObject) -> None:
        d = self._get_relationship_persistent_dict_by_uuid(parent, item, name) or dict()
        self.__set_persistent_storage(item, d, self)

    def unload_relationship_item(self, parent: Persistence.PersistentObject, item: Persistence.PersistentObject) -> None:
        self.__set_persistent_storage(item, None, None)

    def load_component_item(self, parent: Persistence.PersistentObject, name: str, item: Persistence.PersistentObject) -> None:
        d = self._get_item_persistent_dict(parent, name) or dict()
        self.__set_persistent_storage(item, d, self)

    def _insert_item(self, parent: Persistence.PersistentObject, name: str, before_index: int, item: Persistence.PersistentObject) -> None:
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict.setdefault(name, list())
            item_list.insert(before_index, self._get_persistent_dict(item))
        self.__write_properties_if_not_delayed(parent)

    def _remove_item(self, parent: Persistence.PersistentObject, name: str, index: int, item: Persistence.PersistentObject) -> None:
        # remove item from internal storage
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict[name]
            del item_list[index]
        self.__write_properties_if_not_delayed(parent)

    def set_component_item(self, parent: Persistence.PersistentObject, name: str, item: typing.Optional[Persistence.PersistentObject]) -> None:
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        if item:
            # set the item and update its persistent context
            with self.__properties_lock:
                self.__set_persistent_storage(item, item.write_to_dict(), self)
                storage_dict[name] = self._get_persistent_dict(item)
        else:
            # clear the item
            with self.__properties_lock:
                storage_dict.pop(name, None)
                if item:
                    self.__set_persistent_storage(item, None, None)
        self.__write_properties_if_not_delayed(parent)

    def set_property(self, object: Persistence.PersistentObject, name: str, value: typing.Any, delayed: bool = False) -> None:
        # set property in internal storage. if the delayed flag is set, it will not trigger a write to disk.
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict[name] = value
        if not delayed:
            self.__write_properties_if_not_delayed(object)

    def clear_property(self, object: Persistence.PersistentObject, name: str) -> None:
        # clear property in internal storage
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict.pop(name, None)
        self.__write_properties_if_not_delayed(object)

    def get_storage_property(self, item: Persistence.PersistentObject, name: str) -> typing.Optional[str]:
        return None

    def read_external_data(self, item: Persistence.PersistentObject, name: str) -> typing.Any:
        return None

    def write_external_data(self, item: Persistence.PersistentObject, name: str, value: _NDArray) -> None:
        pass

    def reserve_external_data(self, item: Persistence.PersistentObject, name: str, data_shape: typing.Tuple[int, ...],
                              data_dtype: numpy.typing.DTypeLike) -> None:
        pass

    def enter_write_delay(self, object: Persistence.PersistentObject) -> None:
        count = self.__write_delay_counts.setdefault(object, 0)
        self.__write_delay_counts[object] = count + 1

    def exit_write_delay(self, object: Persistence.PersistentObject) -> None:
        count = self.__write_delay_counts.get(object, 1)
        count -= 1
        if count == 0:
            self.__write_delay_counts.pop(object)
        else:
            self.__write_delay_counts[object] = count

    def is_write_delayed(self, item: Persistence.PersistentObject) -> bool:
        return self.__write_delay_counts.get(item, 0) > 0

    def rewrite_item(self, item: Persistence.PersistentObject) -> None:
        self.__write_properties_if_not_delayed(item)

    def restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[PersistentDictType]:
        raise NotImplementedError()

    def prune(self) -> None:
        pass

    def enter_transaction(self) -> None:
        self.__write_delay_count += 1

    def exit_transaction(self) -> None:
        self.__write_delay_count -= 1
        if self.__write_delay_count == 0:
            self.__write_properties_if_not_delayed(None)

    def _get_persistence_write_count(self, item: Persistence.PersistentObject) -> typing.Optional[int]:
        return None


class FilePersistentStorageSystem(PersistentStorageSystem):
    """File based persistent storage system."""

    def __init__(self, path: pathlib.Path) -> None:
        self.__path = path
        super().__init__()

    def close(self) -> None:
        pass

    @property
    def path(self) -> pathlib.Path:
        return self.__path

    def _read_properties(self) -> PersistentDictType:
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
            with Utility.AtomicFileWriter(self.__path) as fp:
                properties = Utility.clean_dict(self.get_storage_properties())
                json.dump(properties, fp)


class MemoryPersistentStorageSystem(PersistentStorageSystem):
    """File based persistent storage system. Useful for testing."""

    def __init__(self, *, library_properties: typing.Optional[PersistentDictType] = None) -> None:
        self.__library_properties = library_properties if library_properties is not None else dict()
        super().__init__()

    def close(self) -> None:
        pass

    def _read_properties(self) -> PersistentDictType:
        return copy.deepcopy(self.__library_properties)

    def _write_properties(self) -> None:
        self.__library_properties.clear()
        self.__library_properties.update(self.get_storage_properties())

    def set_library_properties(self, library_properties: PersistentDictType) -> None:
        self.__library_properties.clear()
        self.__library_properties.update(library_properties)
        self.load_properties()


class ProjectStorageSystemMigrationStage:
    pass


def make_storage_handler_attributes(data_item: DataItem.DataItem) -> StorageHandler.StorageHandlerAttributes:
    dimensional_shape = data_item.dimensional_shape
    data_dtype = data_item.data_dtype
    n_bytes = typing.cast(int, numpy.prod(dimensional_shape + (numpy.dtype(data_dtype).itemsize,), dtype=numpy.int64))
    return StorageHandler.StorageHandlerAttributes(data_item.uuid, data_item.created_local, data_item.session_id, n_bytes, data_item.large_format)


class ProjectStorageSystem(PersistentStorageSystem):
    """Persistent storage system to provide special handling of data items."""

    def __init__(self) -> None:
        super().__init__()
        self.__storage_adapter_map: typing.Dict[uuid.UUID, DataItemStorageAdapter] = dict()

    def close(self) -> None:
        for storage_adapter in self.__storage_adapter_map.values():
            storage_adapter.close()
        self.__storage_adapter_map.clear()

    @abc.abstractmethod
    def _make_storage_handler(self, storage_handler_attributes: StorageHandler.StorageHandlerAttributes, file_handler: typing.Optional[StorageHandler.StorageHandlerFactoryLike] = None) -> StorageHandler.StorageHandler: ...

    @abc.abstractmethod
    def _find_storage_handlers(self) -> typing.Sequence[StorageHandler.StorageHandler]: ...

    @abc.abstractmethod
    def _remove_storage_handler(self, storage_handler: StorageHandler.StorageHandler, *, safe: bool = False) -> None: ...

    @abc.abstractmethod
    def _restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[PersistentDictType]: ...

    @abc.abstractmethod
    def _prune(self) -> None: ...

    # for migration

    @abc.abstractmethod
    def _get_migration_stages(self) -> typing.Sequence[ProjectStorageSystemMigrationStage]: ...

    @abc.abstractmethod
    def _find_data_items(self, migration_stage: ProjectStorageSystemMigrationStage) -> typing.Sequence[StorageHandler.StorageHandler]: ...

    @abc.abstractmethod
    def _is_storage_handler_large_format(self, storage_handler: StorageHandler.StorageHandler) -> bool: ...

    @abc.abstractmethod
    def _migrate_data_item(self, reader_info: ReaderInfo, index: int, count: int) -> typing.Optional[ReaderInfo]: ...

    @abc.abstractmethod
    def _migrate_library_properties(self, library_properties: PersistentDictType, reader_info_list: typing.List[ReaderInfo]) -> None: ...

    @abc.abstractmethod
    def _read_library_properties(self, migration_stage: ProjectStorageSystemMigrationStage) -> PersistentDictType: ...

    #

    @property
    def _data_properties_map(self) -> typing.Dict[uuid.UUID, DataItemStorageAdapter]:
        return self.__storage_adapter_map

    def reset(self) -> None:
        self.__storage_adapter_map = dict()

    def _get_persistence_write_count(self, item: Persistence.PersistentObject) -> typing.Optional[int]:
        return getattr(self._data_properties_map[item.uuid].storage_handler, "_write_count", None)

    def _get_relationship_persistent_dict(self, container: Persistence.PersistentObject, item: Persistence.PersistentObject, key: str, index: int) -> typing.Optional[PersistentDictType]:
        if key == "data_items":
            return self._data_properties_map[item.uuid].properties
        else:
            return super()._get_relationship_persistent_dict(container, item, key, index)

    def _get_relationship_persistent_dict_by_uuid(self, container: Persistence.PersistentObject, item: Persistence.PersistentObject, key: str) -> typing.Optional[PersistentDictType]:
        if key == "data_items":
            return self._data_properties_map[item.uuid].properties
        else:
            return super()._get_relationship_persistent_dict_by_uuid(container, item, key)

    def get_persistent_dict(self, name: str, item_uuid: uuid.UUID) -> PersistentDictType:
        if name == "data_items":
            return self._data_properties_map[item_uuid].properties
        for item_d in self.get_storage_properties()[name]:
            if uuid.UUID(item_d["uuid"]) == item_uuid:
                return typing.cast(PersistentDictType, item_d)
        assert False

    def register_storage_handler(self, storage_handler: StorageHandler.StorageHandler, properties: PersistentDictType) -> None:
        data_item_uuid = uuid.UUID(properties["uuid"])
        assert data_item_uuid not in self.__storage_adapter_map
        storage_adapter = DataItemStorageAdapter(storage_handler, properties)
        self.__storage_adapter_map[data_item_uuid] = storage_adapter

    def read_project_properties(self) -> typing.Tuple[PersistentDictType, typing.Sequence[Persistence.ReaderError]]:
        """Read data items from the data reference handler and return as a dict.

        The dict may contain keys for data_items, display_items, data_structures, connections, and computations.
        """
        storage_handlers = self._find_storage_handlers()

        reader_info_list = list()
        reader_error_list = list()
        for storage_handler in storage_handlers:
            try:
                large_format = self._is_storage_handler_large_format(storage_handler)
                storage_handler_properties = storage_handler.read_properties()
                storage_handler.prepare_move()
                assert storage_handler_properties is not None
                properties = Migration.transform_to_latest(storage_handler_properties)
                reader_info = ReaderInfo(properties, [False], large_format, storage_handler, storage_handler.reference)
                reader_info_list.append(reader_info)
            except Exception as e:
                reader_error_list.append(Persistence.ReaderError(storage_handler.reference, e, traceback.extract_stack()))

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
            data_item_properties = reader_info.properties if reader_info.properties else dict()
            if data_item_properties.get("version", 0) == DataItem.DataItem.writer_version:
                data_item_properties["__large_format"] = reader_info.large_format
                properties_copy.setdefault("data_items", list()).append(data_item_properties)

        def data_item_created(data_item_properties: PersistentDictType) -> str:
            # created is a utc timestamp
            earliest_datetime = datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc).isoformat()
            return typing.cast(str, data_item_properties.get("created", earliest_datetime))

        data_items_copy = sorted(properties_copy.get("data_items", list()), key=data_item_created)
        if len(data_items_copy) > 0:
            properties_copy["data_items"] = data_items_copy

        return Model.transform_forward(properties_copy), reader_error_list

    # override
    def _write_item_properties(self, item: typing.Optional[Persistence.PersistentObject]) -> None:
        if item and isinstance(item, DataItem.DataItem):
            self.__rewrite_data_item_properties(item)
        else:
            super()._write_item_properties(item)

    # override
    def _insert_item(self, parent: Persistence.PersistentObject, name: str, before_index: int, item: Persistence.PersistentObject) -> None:
        if isinstance(item, DataItem.DataItem):
            item_uuid = item.uuid
            storage_handler = self._make_storage_handler(make_storage_handler_attributes(item))
            assert item_uuid not in self.__storage_adapter_map
            persistent_dict = self._get_persistent_dict(item)
            assert persistent_dict is not None
            storage_adapter = DataItemStorageAdapter(storage_handler, persistent_dict)
            self.__storage_adapter_map[item_uuid] = storage_adapter
        else:
            super()._insert_item(parent, name, before_index, item)

    # override
    def _remove_item(self, parent: Persistence.PersistentObject, name: str, index: int, item: Persistence.PersistentObject) -> None:
        if isinstance(item, DataItem.DataItem):
            assert item.uuid in self.__storage_adapter_map
            storage = self.__storage_adapter_map.get(item.uuid)
            assert storage
            self._remove_storage_handler(storage.storage_handler, safe=True)
            self.__storage_adapter_map.pop(item.uuid).close()
        else:
            super()._remove_item(parent, name, index, item)

    # override
    def get_storage_property(self, item: Persistence.PersistentObject, name: str) -> typing.Optional[str]:
        if isinstance(item, DataItem.DataItem):
            return self.__get_data_item_property(item, name)
        return super().get_storage_property(item, name)

    # override
    def read_external_data(self, item: Persistence.PersistentObject, name: str) -> typing.Any:
        if isinstance(item, DataItem.DataItem) and name == "data":
            return self.__read_data_item_data(item)
        return super().read_external_data(item, name)

    # override
    def write_external_data(self, item: Persistence.PersistentObject, name: str, value: _NDArray) -> None:
        if isinstance(item, DataItem.DataItem) and name == "data":
            self.__write_data_item_data(item, value)
        else:
            super().write_external_data(item, name, value)

    # override
    def reserve_external_data(self, item: Persistence.PersistentObject, name: str, data_shape: typing.Tuple[int, ...],
                              data_dtype: numpy.typing.DTypeLike) -> None:
        if isinstance(item, DataItem.DataItem) and name == "data":
            self.__reserve_data_item_data(item, data_shape, numpy.dtype(data_dtype))
        else:
            super().reserve_external_data(item, name, data_shape, data_dtype)

    # override
    def rewrite_item(self, item: Persistence.PersistentObject) -> None:
        if isinstance(item, DataItem.DataItem):
            self.__rewrite_data_item_properties(item)
        else:
            super().rewrite_item(item)

    def restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[PersistentDictType]:
        return self.__restore_item(data_item_uuid)

    def prune(self) -> None:
        self._prune()

    def find_data_items(self) -> typing.Sequence[StorageHandler.StorageHandler]:
        return self._find_storage_handlers()

    def migrate_to_latest(self) -> None:
        migrate_to_latest(self, self)

    def __get_data_item_properties(self, data_item: DataItem.DataItem) -> PersistentDictType:
        storage_adapter = self.__storage_adapter_map.get(data_item.uuid)
        assert storage_adapter
        return storage_adapter.properties

    def __get_data_item_property(self, data_item: DataItem.DataItem, name: str) -> typing.Optional[str]:
        if name == "file_path":
            storage = self.__storage_adapter_map.get(data_item.uuid)
            return storage.storage_handler.reference if storage else None
        return None

    def __read_data_item_data(self, data_item: DataItem.DataItem) -> typing.Optional[_NDArray]:
        storage_adapter = self.__storage_adapter_map.get(data_item.uuid)
        assert storage_adapter
        return storage_adapter.load_data(data_item)

    def __write_data_item_data(self, data_item: DataItem.DataItem, data: typing.Optional[_NDArray]) -> None:
        if not self.is_write_delayed(data_item):
            storage_adapter = self.__storage_adapter_map.get(data_item.uuid)
            assert storage_adapter
            storage_adapter.update_data(data_item, data)

    def __reserve_data_item_data(self, data_item: DataItem.DataItem, data_shape: typing.Tuple[int, ...], data_dtype: numpy.typing.DTypeLike) -> None:
        storage_adapter = self.__storage_adapter_map.get(data_item.uuid)
        assert storage_adapter
        storage_adapter.reserve_data(data_item, data_shape, data_dtype)

    def __rewrite_data_item_properties(self, data_item: DataItem.DataItem) -> None:
        if not self.is_write_delayed(data_item):
            storage_adapter = self.__storage_adapter_map.get(data_item.uuid)
            assert storage_adapter
            storage_adapter.rewrite_item(data_item)

    def __restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[PersistentDictType]:
        return self._restore_item(data_item_uuid)


class FileProjectStorageSystemMigrationStage(ProjectStorageSystemMigrationStage):
    def __init__(self, library_path: pathlib.Path, library_folder: pathlib.Path) -> None:
        self.library_path = library_path
        self.library_folder = library_folder



class FileProjectStorageSystem(ProjectStorageSystem):

    _file_handler_factories: typing.List[StorageHandler.StorageHandlerFactoryLike] = [NDataHandler.NDataHandlerFactory(), HDF5Handler.HDF5HandlerFactory()]

    def __init__(self, project_path: pathlib.Path, project_data_path: typing.Optional[pathlib.Path] = None) -> None:
        super().__init__()
        self.__project_path = project_path
        self.__project_data_path = project_data_path

    def load_properties(self) -> None:
        # in order to be resilient to name changes, first make a list of folders in project_data_folders which
        # (1) can be constructed and (2) which exist. if none actually exist, see if one exists based on the
        # root name. then, if a folder exists, use it. otherwise, use the first one that can be constructed from
        # either the project_data_folders or the root name. this method is expected to supply a project_data_path
        # that can be written; the case where the project is created is where the folder will not exist in the
        # first place.
        super().load_properties()
        project_data_folder_paths = list()
        existing_project_data_folder_paths = list()
        for project_data_folder in self.get_storage_properties().get("project_data_folders", list()):
            project_data_folder_path = pathlib.Path(project_data_folder)
            if not project_data_folder_path.is_absolute():
                project_data_folder_path = self.__project_path.parent / project_data_folder_path
            project_data_folder_paths.append(project_data_folder_path)
            if project_data_folder_path.exists():
                existing_project_data_folder_paths.append(project_data_folder_path)
        if not existing_project_data_folder_paths:
            project_data_folder_path = self.__project_path.with_name(self.__project_path.stem + " Data")
            if not project_data_folder_path.is_absolute():
                project_data_folder_path = self.__project_path.parent / project_data_folder_path
            project_data_folder_paths.append(project_data_folder_path)
            if project_data_folder_path.exists():
                existing_project_data_folder_paths.append(project_data_folder_path)
        if existing_project_data_folder_paths:
            self.__project_data_path = existing_project_data_folder_paths[0]
        else:
            self.__project_data_path = project_data_folder_paths[0] if len(project_data_folder_paths) > 0 else self.__project_data_path

    @property
    def project_path(self) -> pathlib.Path:
        return self.__project_path

    def _read_properties(self) -> PersistentDictType:
        properties = dict()
        if self.__project_path and self.__project_path.exists():
            with self.__project_path.open("r") as fp:
                properties = json.load(fp)
        return properties

    def _write_properties(self) -> None:
        self.__write_properties_inner(Model.transform_backward(copy.deepcopy(self.get_storage_properties())))

    def __write_properties_inner(self, properties: PersistentDictType) -> None:
        if self.__project_path:
            # atomically overwrite
            with Utility.AtomicFileWriter(self.__project_path) as fp:
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

    def get_identifier(self) -> str:
        return str(self.__project_path)

    def _make_storage_handler(self, storage_handler_attributes: StorageHandler.StorageHandlerAttributes, file_handler_factory: typing.Optional[StorageHandler.StorageHandlerFactoryLike] = None) -> StorageHandler.StorageHandler:
        # if there are two handlers, first is small, second is large
        # if there is only one handler, it is used in all cases
        is_large_format = storage_handler_attributes.n_bytes > 16 * 1024 * 1024 or storage_handler_attributes._force_large_format
        file_handler_factory = file_handler_factory if file_handler_factory else (self._file_handler_factories[-1] if is_large_format else self._file_handler_factories[0])
        assert self.__project_data_path is not None
        return file_handler_factory.make(self.__project_data_path / self.__get_base_path(storage_handler_attributes))

    def _find_storage_handlers(self) -> typing.Sequence[StorageHandler.StorageHandler]:
        return self.__find_storage_handlers(self.__project_data_path)

    def _is_storage_handler_large_format(self, storage_handler: StorageHandler.StorageHandler) -> bool:
        return isinstance(storage_handler, HDF5Handler.HDF5Handler)

    def _remove_storage_handler(self, storage_handler: StorageHandler.StorageHandler, *, safe: bool = False) -> None:
        assert self.__project_data_path is not None
        file_path = pathlib.Path(storage_handler.reference)
        file_name = file_path.parts[-1]
        trash_dir = self.__project_data_path / "trash"
        new_file_path = trash_dir / file_name
        storage_handler.prepare_move()  # moving files in the storage handler requires it to be closed.
        # TODO: move this functionality to the storage handler.
        if safe and not os.path.exists(new_file_path):
            trash_dir.mkdir(exist_ok=True)
            shutil.move(str(file_path), new_file_path)
        storage_handler.remove()

    def _restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[PersistentDictType]:
        assert self.__project_data_path is not None
        data_item_uuid_str = str(data_item_uuid)
        trash_dir = self.__project_data_path / "trash"
        storage_handlers = self.__find_storage_handlers(trash_dir, skip_trash=False)
        try:
            for storage_handler in storage_handlers:
                storage_handler_properties = storage_handler.read_properties()
                assert storage_handler_properties is not None
                properties = Migration.transform_to_latest(storage_handler_properties)
                if properties.get("uuid", None) == data_item_uuid_str:
                    data_item = DataItem.DataItem(item_uuid=data_item_uuid)
                    with contextlib.closing(data_item):
                        data_item.begin_reading()
                        data_item.read_from_dict(properties)
                        data_item.finish_reading()
                        old_file_path = storage_handler.reference
                        new_file_path = storage_handler.factory.make_path(self.__project_data_path / self.__get_base_path(make_storage_handler_attributes(data_item)))
                        if not os.path.exists(new_file_path):
                            os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
                            shutil.move(old_file_path, new_file_path)
                        self._make_storage_handler(make_storage_handler_attributes(data_item)).close()  # what's this line for?
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
        assert self.__project_data_path is not None
        return self.__project_data_path / "trash"

    def _migrate_data_item(self, reader_info: ReaderInfo, index: int, count: int) -> typing.Optional[ReaderInfo]:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
        data_item_uuid = uuid.UUID(typing.cast(str, properties["uuid"]))
        old_data_item = DataItem.DataItem(item_uuid=data_item_uuid)
        with contextlib.closing(old_data_item):
            old_data_item.begin_reading()
            old_data_item.read_from_dict(properties)
            old_data_item.finish_reading()
            old_data_item_path = storage_handler.reference
            # ask the storage system for the file handler for the data item path
            file_handler_factory = self.__get_file_handler_factory_for_file(str(old_data_item_path))
            # ask the storage system to make a storage handler (an instance of a file handler) for the data item
            # this ensures that the storage handler (file format) is the same as before.
            with contextlib.closing(self._make_storage_handler(make_storage_handler_attributes(old_data_item), file_handler_factory)) as target_storage_handler:
                if target_storage_handler and storage_handler.reference != target_storage_handler.reference:
                    os.makedirs(os.path.dirname(target_storage_handler.reference), exist_ok=True)
                    target_storage_handler.prepare_move()
                    shutil.copyfile(storage_handler.reference, target_storage_handler.reference)
                    shutil.copystat(storage_handler.reference, target_storage_handler.reference)
                    target_storage_handler.write_properties(Migration.transform_from_latest(copy.deepcopy(properties)), datetime.datetime.now())
                    logging.getLogger("migration").info(f"Copying data item ({index + 1}/{count}) {data_item_uuid} to new library.")
                    return ReaderInfo(properties, [False], self._is_storage_handler_large_format(target_storage_handler),
                                      target_storage_handler, target_storage_handler.reference)
            logging.getLogger("migration").warning(f"Unable to copy data item {data_item_uuid} to new library.")
            return None

    def _migrate_library_properties(self, library_properties: PersistentDictType, reader_info_list: typing.List[ReaderInfo]) -> None:
        self.__write_properties_inner(library_properties)
        for reader_info in reader_info_list:
            data_item_properties = Utility.clean_dict(reader_info.properties if reader_info.properties else dict())
            if data_item_properties.get("version", 0) == DataItem.DataItem.writer_version:
                # file modified dates are stored as local timestamps
                earliest_datetime = datetime.datetime.fromtimestamp(0).isoformat()
                created = typing.cast(str, data_item_properties.get("created", earliest_datetime))
                file_datetime = DataItem.DatetimeToStringConverter().convert_back(created) or datetime.datetime.now()
                # storage handler has already been closed; writing properties MAY reopen it.
                # close it by "prepare for move".
                # this should be redesigned so that storage handler lifetime is well defined.
                # TODO: storage handler open/close is bad design.
                reader_info.storage_handler.write_properties(reader_info.properties, file_datetime)
                reader_info.storage_handler.prepare_move()

    @staticmethod
    def _get_migration_paths(library_path: pathlib.Path) -> typing.List[typing.Tuple[pathlib.Path, pathlib.Path]]:
        return [
            (library_path / "Nion Swift Library 13.nslib", library_path / "Nion Swift Data 13"),
            (library_path / "Nion Swift Library 12.nslib", library_path / "Nion Swift Data 12"),
            (library_path / "Nion Swift Workspace.nslib", library_path / "Nion Swift Data 11"),
            (library_path / "Nion Swift Workspace.nslib", library_path / "Nion Swift Data 10"),
            (library_path / "Nion Swift Workspace.nslib", library_path / "Nion Swift Data"),
        ]

    def _get_migration_stages(self) -> typing.Sequence[ProjectStorageSystemMigrationStage]:
        return list([FileProjectStorageSystemMigrationStage(p, f) for p, f in self._get_migration_paths(self.__project_path.parent)])

    def _read_library_properties(self, migration_stage: ProjectStorageSystemMigrationStage) -> PersistentDictType:
        migration_stage = typing.cast(FileProjectStorageSystemMigrationStage, migration_stage)
        properties = dict()
        project_path = migration_stage.library_path
        if project_path and os.path.exists(project_path):
            try:
                with project_path.open("r") as fp:
                    properties = json.load(fp)
            except Exception:
                os.replace(project_path, project_path.with_suffix(".bak"))
        return properties

    def _find_data_items(self, migration_stage: ProjectStorageSystemMigrationStage) -> typing.Sequence[StorageHandler.StorageHandler]:
        migration_stage = typing.cast(FileProjectStorageSystemMigrationStage, migration_stage)
        return self.__find_storage_handlers(migration_stage.library_folder)

    def __get_base_path(self, storage_handler_attributes: StorageHandler.StorageHandlerAttributes) -> pathlib.Path:
        data_item_uuid = storage_handler_attributes.uuid
        created_local = storage_handler_attributes.created_local
        session_id = storage_handler_attributes.session_id
        # data_item_uuid.bytes.encode('base64').rstrip('=\n').replace('/', '_')
        # and back: data_item_uuid = uuid.UUID(bytes=(slug + '==').replace('_', '/').decode('base64'))
        # also:

        def encode(uuid_: uuid.UUID, alphabet: str) -> str:
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

    def __get_file_handler_factory_for_file(self, path: str) -> typing.Optional[StorageHandler.StorageHandlerFactoryLike]:
        for file_handler_factory in self._file_handler_factories:
            if file_handler_factory.is_matching(path):
                return file_handler_factory
        return None

    def __find_storage_handlers(self, directory: typing.Optional[pathlib.Path], *, skip_trash: bool = True) -> typing.Sequence[StorageHandler.StorageHandler]:
        storage_handlers = list()
        if directory and directory.exists():
            absolute_file_paths = set()
            for file_path in directory.rglob("*"):
                if not skip_trash or file_path.parent.name != "trash":
                    if not file_path.name.startswith("."):
                        absolute_file_paths.add(str(file_path))
            for file_handler_factory in self._file_handler_factories:
                for data_file in filter(file_handler_factory.is_matching, absolute_file_paths):
                    try:
                        storage_handler = file_handler_factory.make(pathlib.Path(data_file))
                        assert storage_handler.is_valid
                        storage_handlers.append(storage_handler)
                    except Exception as e:
                        logging.error("Exception reading file: %s", data_file)
                        logging.error(str(e))
                        raise
        return storage_handlers


class MemoryStorageHandler(StorageHandler.StorageHandler):

    def __init__(self, uuid_: str, data_properties_map: typing.Dict[str, PersistentDictType],
                 data_map: typing.Dict[str, _NDArray], data_read_event: Event.Event) -> None:
        self.__uuid = uuid_
        self.__data_properties_map = data_properties_map
        self.__data_map = data_map
        self.__data_read_event = data_read_event

    def close(self) -> None:
        self.__uuid = typing.cast(str, None)
        self.__data_properties_map = typing.cast(typing.Dict[str, PersistentDictType], None)
        self.__data_map = typing.cast(typing.Dict[str, _NDArray], None)

    @property
    def factory(self) -> StorageHandler.StorageHandlerFactoryLike:
        return MemoryStorageHandlerFactory()

    @property
    def reference(self) -> str:
        return str(self.__uuid)

    @property
    def is_valid(self) -> bool:
        return True

    def read_properties(self) -> PersistentDictType:
        return copy.deepcopy(self.__data_properties_map.get(self.__uuid, dict()))

    def read_data(self) -> typing.Optional[_NDArray]:
        self.__data_read_event.fire(self.__uuid)
        return self.__data_map.get(self.__uuid)

    def write_properties(self, properties: PersistentDictType, file_datetime: datetime.datetime) -> None:
        self.__data_properties_map[self.__uuid] = Utility.clean_dict(properties)

    def write_data(self, data: _NDArray, file_datetime: datetime.datetime) -> None:
        self.__data_map[self.__uuid] = numpy.copy(data)

    def reserve_data(self, data_shape: typing.Tuple[int, ...], data_dtype: numpy.typing.DTypeLike, file_datetime: datetime.datetime) -> None:
        self.__data_map[self.__uuid] = numpy.zeros(data_shape, data_dtype)

    def prepare_move(self) -> None:
        pass

    def remove(self) -> None:
        pass


class MemoryStorageHandlerFactory(StorageHandler.StorageHandlerFactoryLike):

    def is_matching(self, file_path: str) -> bool:
        return True

    def make(self, file_path: pathlib.Path) -> StorageHandler.StorageHandler:
        return MemoryStorageHandler(str(uuid.uuid4()), dict(), dict(), Event.Event())

    def make_path(self, file_path: pathlib.Path) -> str:
        return str(file_path)

    def get_extension(self) -> str:
        return ".memory"


class MemoryProjectStorageSystem(ProjectStorageSystem):

    def __init__(self, *, library_properties: typing.Optional[PersistentDictType] = None,
                 data_properties_map: typing.Optional[typing.Dict[str, PersistentDictType]] = None,
                 data_map: typing.Optional[typing.Dict[str, _NDArray]] = None,
                 trash_map: typing.Optional[typing.Dict[str, PersistentDictType]] = None,
                 data_read_event: typing.Optional[Event.Event] = None) -> None:
        super().__init__()
        self.__library_properties = library_properties if library_properties is not None else dict()
        self.__data_properties_map = data_properties_map if data_properties_map is not None else dict()
        self.__data_map = data_map if data_map is not None else dict()
        self.__trash_map = trash_map if trash_map is not None else dict()
        self._test_data_read_event = data_read_event or Event.Event()
        self._write_count = 0

    def _read_properties(self) -> PersistentDictType:
        return copy.deepcopy(self.__library_properties)

    def _write_properties(self) -> None:
        self._write_count += 1
        self.__library_properties.clear()
        self.__library_properties.update(Model.transform_backward(copy.deepcopy(self.get_storage_properties())))

    def get_identifier(self) -> str:
        return "memory"

    def _make_storage_handler(self, storage_handler_attributes: StorageHandler.StorageHandlerAttributes, file_handler: typing.Optional[StorageHandler.StorageHandlerFactoryLike] = None) -> MemoryStorageHandler:
        data_item_uuid_str = str(storage_handler_attributes.uuid)
        return MemoryStorageHandler(data_item_uuid_str, self.__data_properties_map, self.__data_map, self._test_data_read_event)

    def _find_storage_handlers(self) -> typing.Sequence[StorageHandler.StorageHandler]:
        storage_handlers = list()
        for key in sorted(self.__data_properties_map):
            self.__data_properties_map[key].setdefault("uuid", str(uuid.uuid4()))
            storage_handlers.append(MemoryStorageHandler(key, self.__data_properties_map, self.__data_map, self._test_data_read_event))
        return storage_handlers

    def _is_storage_handler_large_format(self, storage_handler: StorageHandler.StorageHandler) -> bool:
        return False

    def _remove_storage_handler(self, storage_handler: StorageHandler.StorageHandler, *, safe: bool = False) -> None:
        storage_handler_reference = storage_handler.reference
        data = self.__data_map.pop(storage_handler_reference, None)
        properties = self.__data_properties_map.pop(storage_handler_reference)
        if safe:
            assert storage_handler_reference not in self.__trash_map
            self.__trash_map[storage_handler_reference] = {"data": data, "properties": properties}
        storage_handler.close()  # moving files in the storage handler requires it to be closed.

    def _restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[PersistentDictType]:
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

    def _migrate_library_properties(self, library_properties: PersistentDictType, reader_info_list: typing.List[ReaderInfo]) -> None:
        self.__library_properties.clear()
        self.__library_properties.update(library_properties)

        data_properties_map = dict()

        for reader_info in reader_info_list:
            data_item_properties = Utility.clean_dict(reader_info.properties if reader_info.properties else dict())
            if data_item_properties.get("version", 0) == DataItem.DataItem.writer_version:
                data_item_properties["__large_format"] = reader_info.large_format
                data_properties_map[reader_info.identifier] = data_item_properties

        def data_item_created(data_item_properties: typing.Tuple[str, PersistentDictType]) -> str:
            # created is a utc timestamp
            earliest_datetime = datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc).isoformat()
            return typing.cast(str, data_item_properties[1].get("created", earliest_datetime))

        data_properties_map = {k: v for k, v in sorted(data_properties_map.items(), key=data_item_created)}

        self.__data_properties_map.clear()
        self.__data_properties_map.update(data_properties_map)

    def _get_migration_stages(self) -> typing.Sequence[ProjectStorageSystemMigrationStage]:
        return [ProjectStorageSystemMigrationStage()]

    def _read_library_properties(self, migration_stage: ProjectStorageSystemMigrationStage) -> PersistentDictType:
        return copy.deepcopy(self.__library_properties)

    def _find_data_items(self, migration_stage: ProjectStorageSystemMigrationStage) -> typing.Sequence[StorageHandler.StorageHandler]:
        return self._find_storage_handlers()


def make_file_persistent_storage_system(path: pathlib.Path) -> Persistence.PersistentStorageInterface:
    return FilePersistentStorageSystem(path)


def make_memory_persistent_storage_system() -> Persistence.PersistentStorageInterface:
    return MemoryPersistentStorageSystem()


def make_index_project_storage_system(project_path: pathlib.Path) -> ProjectStorageSystem:
    return FileProjectStorageSystem(project_path)


def make_folder_project_storage_system(project_folder_path: pathlib.Path) -> typing.Optional[ProjectStorageSystem]:
    for project_file, project_dir in FileProjectStorageSystem._get_migration_paths(project_folder_path):
        if project_file.exists():
            return FileProjectStorageSystem(project_file, project_dir)
    return None


def make_memory_project_storage_system(profile_context: typing.Any, _uuid: uuid.UUID, d: PersistentDictType) -> typing.Optional[Persistence.PersistentStorageInterface]:
    storage_system_uuid = d.get("uuid") or _uuid or uuid.uuid4()  # allow d to override project uuid for testing failures
    # the profile context must be valid here.
    new_project_properties = profile_context.x_project_properties.setdefault(storage_system_uuid,
                                                                             {"version": d.get("version", PROJECT_VERSION),
                                                                              "uuid": str(storage_system_uuid)})
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
