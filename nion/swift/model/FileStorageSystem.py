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
from nion.swift.model import HDF5Handler
from nion.swift.model import Migration
from nion.swift.model import NDataHandler
from nion.swift.model import Utility
from nion.utils import Event


# define the versions that get stored in the JSON files
PROFILE_VERSION = 2
PROJECT_VERSION = 3
PROJECT_VERSION_0_14 = 2

ReaderInfo = collections.namedtuple("ReaderInfo", ["properties", "changed_ref", "large_format", "storage_handler", "identifier"])


class DataItemStorageAdapter:
    """Persistent storage for writing data item properties, relationships, and data to its storage handler.

    The storage_handler must respond to these methods:
        close()
        read_data()
        write_properties(properties, file_datetime)
        write_data(data, file_datetime)
        remove()
    """

    def __init__(self, storage_handler, properties):
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

    def set_write_delayed(self, item, write_delayed: bool) -> None:
        self.__write_delayed = write_delayed

    def is_write_delayed(self, item) -> bool:
        return self.__write_delayed

    def rewrite_item(self, item) -> None:
        if not self.__write_delayed:
            file_datetime = item.created_local
            self.__storage_handler.write_properties(Migration.transform_from_latest(copy.deepcopy(self.__properties)), file_datetime)

    def update_data(self, item, data):
        if not self.__write_delayed:
            file_datetime = item.created_local
            if data is not None:
                self.__storage_handler.write_data(data, file_datetime)

    def load_data(self, item) -> None:
        assert item.has_data
        return self.__storage_handler.read_data()


class LibraryHandler:

    def __init__(self):
        self.__properties = self._read_properties()
        self.__properties_lock = threading.RLock()
        self.__data_properties_map = dict()

    def _get_identifier(self) -> str:
        return str()

    def _read_properties(self) -> typing.Dict:
        return dict()

    def _write_properties(self, properties: typing.Dict) -> None:
        pass

    def _find_storage_handlers(self) -> typing.List:
        """Find storage handlers.

        Subclasses should override this method.
        """
        return list()

    def _is_storage_handler_large_format(self, storage_handler) -> bool:
        return False

    def _create_work_project_files(self) -> typing.Dict:
        return dict()

    def _prune(self) -> None:
        pass

    def _make_storage_handler(self, data_item: DataItem.DataItem, file_handler=None):
        return None

    def _remove_storage_handler(self, storage_handler, *, safe: bool=False) -> None:
        pass

    def _restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[dict]:
        return None

    def get_identifier(self) -> str:
        return self._get_identifier()

    def reset(self):
        self.__data_properties_map = dict()

    def write_properties(self) -> None:
        self._write_properties(self.__properties)

    @property
    def properties(self) -> typing.Dict:
        return self.__properties

    @property
    def properties_copy(self) -> typing.Dict:
        with self.__properties_lock:
            return copy.deepcopy(self.__properties)

    def update_modified(self, storage_dict: typing.Dict, modified: datetime.datetime) -> None:
        """Update the modified entry in the storage dict which is assumed to be a fragment dict of properties."""
        with self.__properties_lock:
            storage_dict["modified"] = modified.isoformat()

    def insert_item(self, storage_dict: typing.Dict, name: str, before_index: int, item) -> None:
        """Insert an item into the storage dict which is assumed to be a fragment dict of properties."""
        with self.__properties_lock:
            item_list = storage_dict.setdefault(name, list())
            item_dict = item.write_to_dict()
            item_list.insert(before_index, item_dict)

    def remove_item(self, storage_dict: typing.Dict, name: str, index: int) -> None:
        """Remove an item from the storage dict which is assumed to be a fragment dict of properties."""
        with self.__properties_lock:
            item_list = storage_dict[name]
            del item_list[index]

    def set_item(self, storage_dict: typing.Dict, name: str, item) -> None:
        with self.__properties_lock:
            item_dict = item.write_to_dict()
            storage_dict[name] = item_dict

    def clear_item(self, storage_dict: typing.Dict, name: str) -> None:
        with self.__properties_lock:
            storage_dict.pop(name, None)

    def set_property(self, storage_dict: typing.Dict, name: str, value) -> None:
        with self.__properties_lock:
            storage_dict[name] = value

    def clear_property(self, storage_dict: typing.Dict, name: str) -> None:
        with self.__properties_lock:
            storage_dict.pop(name, None)

    def find_data_items(self) -> typing.List:
        return self._find_storage_handlers()

    def read_library(self) -> typing.Dict:
        """Read data items from the data reference handler and return as a dict.

        The dict may contain keys for data_items, display_items, data_structures, connections, and computations.
        """
        self.__properties = self._read_properties()

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
            self.__data_properties_map[data_item_uuid] = storage_adapter

        properties_copy = self.properties_copy

        # ensure unique connections
        connections_list = properties_copy.get("connections", list())
        assert len(connections_list) == len({connection.get("uuid") for connection in connections_list})

        # ensure unique computations
        computations_list = properties_copy.get("computations", list())
        assert len(computations_list) == len({computation.get("uuid") for computation in computations_list})

        # TODO: if version is not current, this project will need an upgrade, which must be done explicitly by the user.

        # TODO: version 2 is from 0.14.

        if properties_copy.get("version", 0) < 1:
            properties_copy["version"] = PROJECT_VERSION_0_14

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

    def _get_migration_stages(self) -> typing.List:
        return list()

    def _read_library_properties(self, migration_stage) -> typing.Dict:
        return dict()

    def _find_data_items(self, migration_stage) -> typing.List:
        return list()

    def _migrate_data_item(self, reader_info: ReaderInfo, index: int, count: int) -> typing.Optional[ReaderInfo]:
        pass

    def _migrate_library_properties(self, library_properties: typing.Dict, reader_info_list: typing.List[ReaderInfo]) -> None:
        pass

    def migrate_to_latest(self) -> None:
        library_properties = None
        data_item_uuids = set()
        reader_info_list = list()
        library_updates = dict()
        deletions = list()
        for migration_stage in self._get_migration_stages():
            storage_handlers = self._find_data_items(migration_stage)
            new_reader_info_list = list()
            for storage_handler in storage_handlers:
                try:
                    large_format = self._is_storage_handler_large_format(storage_handler)
                    properties = Migration.transform_to_latest(storage_handler.read_properties())
                    reader_info = ReaderInfo(properties, [False], large_format, storage_handler, storage_handler.reference)
                    new_reader_info_list.append(reader_info)
                except Exception as e:
                    logging.debug("Error reading %s", storage_handler.reference)
                    import traceback
                    traceback.print_exc()
                    traceback.print_stack()
            new_library_properties = self._read_library_properties(migration_stage)
            for deletion in copy.deepcopy(new_library_properties.get("data_item_deletions", list())):
                if not deletion in deletions:
                    deletions.append(deletion)
            if library_properties is None:
                library_properties = copy.deepcopy(new_library_properties)
            preliminary_library_updates = dict()
            Migration.migrate_to_latest(new_reader_info_list, preliminary_library_updates)
            count = len(new_reader_info_list)
            for index, reader_info in enumerate(new_reader_info_list):
                storage_handler = reader_info.storage_handler
                properties = reader_info.properties
                try:
                    version = properties.get("version", 0)
                    if version == DataItem.DataItem.writer_version:
                        data_item_uuid = uuid.UUID(properties["uuid"])
                        if not data_item_uuid in data_item_uuids:
                            if not str(data_item_uuid) in deletions:
                                new_reader_info = self._migrate_data_item(reader_info, index, count)
                                if new_reader_info:
                                    reader_info_list.append(new_reader_info)
                                    data_item_uuids.add(data_item_uuid)
                                    library_update = preliminary_library_updates.get(data_item_uuid)
                                    if library_update:
                                        library_updates[data_item_uuid] = library_update
                except Exception as e:
                    logging.debug("Error reading %s", storage_handler.reference)
                    import traceback
                    traceback.print_exc()
                    traceback.print_stack()

        assert len(reader_info_list) == len(data_item_uuids)

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

        # migrations

        if library_properties.get("version", 0) < 2:
            for data_group_properties in library_properties.get("data_groups", list()):
                data_group_properties.pop("data_groups")
                display_item_references = data_group_properties.setdefault("display_item_references", list())
                data_item_uuid_strs = data_group_properties.pop("data_item_uuids", list())
                for data_item_uuid_str in data_item_uuid_strs:
                    for display_item_properties in library_properties.get("display_items", list()):
                        data_item_references = [d.get("data_item_reference", None) for d in display_item_properties.get("display_data_channels", list())]
                        if data_item_uuid_str in data_item_references:
                            display_item_references.append(display_item_properties["uuid"])
            data_item_uuid_to_display_item_uuid_map = dict()
            data_item_uuid_to_display_item_dict_map = dict()
            display_to_display_item_map = dict()
            display_to_display_data_channel_map = dict()
            for display_item_properties in library_properties.get("display_items", list()):
                display_to_display_item_map[display_item_properties["display"]["uuid"]] = display_item_properties["uuid"]
                display_to_display_data_channel_map[display_item_properties["display"]["uuid"]] = display_item_properties["display_data_channels"][0]["uuid"]
                data_item_references = [d.get("data_item_reference", None) for d in display_item_properties.get("display_data_channels", list())]
                for data_item_uuid_str in data_item_references:
                    data_item_uuid_to_display_item_uuid_map.setdefault(data_item_uuid_str, display_item_properties["uuid"])
                    data_item_uuid_to_display_item_dict_map.setdefault(data_item_uuid_str, display_item_properties)
                display_item_properties.pop("display", None)
            for workspace_properties in library_properties.get("workspaces", list()):
                def replace1(d):
                    if "children" in d:
                        for dd in d["children"]:
                            replace1(dd)
                    if "data_item_uuid" in d:
                        data_item_uuid_str = d.pop("data_item_uuid")
                        display_item_uuid_str = data_item_uuid_to_display_item_uuid_map.get(data_item_uuid_str)
                        if display_item_uuid_str:
                            d["display_item_uuid"] = display_item_uuid_str
                replace1(workspace_properties["layout"])
            for connection_dict in library_properties.get("connections", list()):
                source_uuid_str = connection_dict["source_uuid"]
                if connection_dict["type"] == "interval-list-connection":
                    connection_dict["source_uuid"] = display_to_display_item_map.get(source_uuid_str, None)
                if connection_dict["type"] == "property-connection" and connection_dict["source_property"] == "slice_interval":
                    connection_dict["source_uuid"] = display_to_display_data_channel_map.get(source_uuid_str, None)

            def fix_specifier(specifier_dict):
                if specifier_dict.get("type") in ("data_item", "display_xdata", "cropped_xdata", "cropped_display_xdata", "filter_xdata", "filtered_xdata"):
                    if specifier_dict.get("uuid") in data_item_uuid_to_display_item_dict_map:
                        specifier_dict["uuid"] = data_item_uuid_to_display_item_dict_map[specifier_dict["uuid"]]["display_data_channels"][0]["uuid"]
                    else:
                        specifier_dict.pop("uuid", None)
                if specifier_dict.get("type") == "data_item":
                    specifier_dict["type"] = "data_source"
                if specifier_dict.get("type") == "data_item_object":
                    specifier_dict["type"] = "data_item"
                if specifier_dict.get("type") == "region":
                    specifier_dict["type"] = "graphic"

            for computation_dict in library_properties.get("computations", list()):
                for variable_dict in computation_dict.get("variables", list()):
                    if "specifier" in variable_dict:
                        specifier_dict = variable_dict["specifier"]
                        if specifier_dict is not None:
                            fix_specifier(specifier_dict)
                    if "secondary_specifier" in variable_dict:
                        specifier_dict = variable_dict["secondary_specifier"]
                        if specifier_dict is not None:
                            fix_specifier(specifier_dict)
                for result_dict in computation_dict.get("results", list()):
                    fix_specifier(result_dict["specifier"])

            library_properties["version"] = PROJECT_VERSION

        # TODO: add consistency checks: no duplicated items [by uuid] such as connections or computations or data items

        assert library_properties["version"] == PROJECT_VERSION

        self._migrate_library_properties(library_properties, reader_info_list)

    def prune(self) -> None:
        self._prune()

    def insert_data_item(self, data_item: DataItem.DataItem, is_write_delayed: bool) -> None:
        storage_handler = self._make_storage_handler(data_item)
        item_uuid = data_item.uuid
        assert item_uuid not in self.__data_properties_map
        storage_adapter = DataItemStorageAdapter(storage_handler, data_item.write_to_dict())
        self.__data_properties_map[item_uuid] = storage_adapter
        if is_write_delayed:
            storage_adapter.set_write_delayed(data_item, True)

    def remove_data_item(self, data_item: DataItem.DataItem) -> None:
        assert data_item.uuid in self.__data_properties_map
        self.__data_properties_map.pop(data_item.uuid).close()

    def get_data_item_property(self, data_item: DataItem.DataItem, name: str) -> typing.Optional[str]:
        if name == "file_path":
            storage = self.__data_properties_map.get(data_item.uuid)
            return storage._storage_handler.reference if storage else None
        return None

    def get_data_item_properties(self, data_item: DataItem.DataItem) -> typing.Dict:
        return self.__data_properties_map.get(data_item.uuid).properties

    def rewrite_data_item_properties(self, data_item: DataItem.DataItem) -> None:
        self.__data_properties_map.get(data_item.uuid).rewrite_item(data_item)

    def read_data_item_data(self, data_item: DataItem.DataItem):
        storage = self.__data_properties_map.get(data_item.uuid)
        return storage.load_data(data_item)

    def write_data_item_data(self, data_item: DataItem.DataItem, data) -> None:
        storage = self.__data_properties_map.get(data_item.uuid)
        storage.update_data(data_item, data)

    def delete_data_item(self, data_item: DataItem.DataItem, *, safe: bool=False) -> None:
        storage = self.__data_properties_map.get(data_item.uuid)
        self._remove_storage_handler(storage._storage_handler, safe=safe)

    def restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[dict]:
        return self._restore_item(data_item_uuid)

    def set_write_delayed(self, data_item: DataItem.DataItem, write_delayed: bool) -> None:
        storage = self.__data_properties_map.get(data_item.uuid)
        if storage:
            storage.set_write_delayed(data_item, write_delayed)


class FileLibraryHandler(LibraryHandler):

    _file_handlers = [NDataHandler.NDataHandler, HDF5Handler.HDF5Handler]

    def __init__(self, project_path: pathlib.Path, project_data_path: pathlib.Path = None):
        self.__project_path = project_path
        self.__project_data_path = project_data_path
        super().__init__()

    @property
    def _project_path(self) -> pathlib.Path:
        return self.__project_path

    def _get_identifier(self) -> str:
        return str(self.__project_path)

    def _read_properties(self) -> typing.Dict:
        properties = dict()
        if self.__project_path and self.__project_path.exists():
            try:
                with self.__project_path.open("r") as fp:
                    properties = json.load(fp)
            except Exception:
                os.replace(self.__project_path, self.__project_path.with_suffix(".bak"))
        project_data_folder_paths = list()
        for project_data_folder in properties.get("project_data_folders", list()):
            project_data_folder_path = pathlib.Path(project_data_folder)
            if not project_data_folder_path.is_absolute():
                project_data_folder_path = self.__project_path.parent / project_data_folder_path
            project_data_folder_paths.append(project_data_folder_path)
        self.__project_data_path = project_data_folder_paths[0] if len(project_data_folder_paths) > 0 else None
        return properties

    def _write_properties(self, properties: typing.Dict) -> None:
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
                properties["project_data_folders"] = [str(project_data_path) for project_data_path in project_data_paths]
                json.dump(properties, fp)
            os.replace(temp_filepath, self.__project_path)

    def _find_storage_handlers(self) -> typing.List:
        return self.__find_storage_handlers(self.__project_data_path)

    def _is_storage_handler_large_format(self, storage_handler) -> bool:
        return isinstance(storage_handler, HDF5Handler.HDF5Handler)

    def _create_work_project_files(self) -> typing.Dict:
        project_path = self.__project_path.parent / "Work.nsproj"
        suffix = str()
        if project_path.exists():
            suffix = f" {datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            project_path =  self.__project_path.parent / f"Work{suffix}.nsproj"
        logging.getLogger("loader").warning(f"Created work project {project_path.parent / project_path.stem}")
        project_data_json = json.dumps({"version": PROJECT_VERSION, "uuid": str(uuid.uuid4()), "project_data_folders": [f"Work Data{suffix}"]})
        project_path.write_text(project_data_json, "utf-8")
        return {"type": "project_index", "uuid": str(uuid.uuid4()), "project_path": str(project_path)}

    def _prune(self) -> None:
        trash_dir = self.__project_data_path / "trash"
        for file_path in trash_dir.rglob("*"):
            # the date is not a reliable way of determining the age since a user may trash an old file. for now,
            # we just delete anything in the trash at startup. future version may have an index file for
            # tracking items in the trash. when items are again retained in the trash, update the disabled
            # test_delete_and_undelete_from_file_storage_system_restores_data_item_after_reload
            file_path.unlink()

    def _make_storage_handler(self, data_item: DataItem.DataItem, file_handler=None):
        # if there are two handlers, first is small, second is large
        # if there is only one handler, it is used in all cases
        large_format = hasattr(data_item, "large_format") and data_item.large_format
        file_handler = file_handler if file_handler else (self._file_handlers[-1] if large_format else self._file_handlers[0])
        return file_handler.make(self.__project_data_path / self.__get_base_path(data_item))

    def _remove_storage_handler(self, storage_handler, *, safe: bool=False) -> None:
        file_path = pathlib.Path(storage_handler.reference)
        file_name = file_path.parts[-1]
        trash_dir = self.__project_data_path / "trash"
        new_file_path = trash_dir / file_name
        storage_handler.close()  # moving files in the storage handler requires it to be closed.
        # TODO: move this functionality to the storage handler.
        if safe and not os.path.exists(new_file_path):
            trash_dir.mkdir(exist_ok=True)
            shutil.move(file_path, new_file_path)
        storage_handler.remove()

    def _restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[dict]:
        data_item_uuid_str = str(data_item_uuid)
        trash_dir = self.__project_data_path / "trash"
        storage_handlers = self.__find_storage_handlers(trash_dir, skip_trash=False)
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
                self._make_storage_handler(data_item, file_handler=None)
                properties["__large_format"] = isinstance(storage_handler, HDF5Handler.HDF5Handler)
                return properties
        return None

    def get_file_handler_for_file(self, path: str):
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
        file_handler = self.get_file_handler_for_file(str(old_data_item_path))
        # ask the storage system to make a storage handler (an instance of a file handler) for the data item
        # this ensures that the storage handler (file format) is the same as before.
        target_storage_handler = self._make_storage_handler(old_data_item, file_handler)
        if target_storage_handler and storage_handler.reference != target_storage_handler.reference:
            os.makedirs(os.path.dirname(target_storage_handler.reference), exist_ok=True)
            shutil.copyfile(storage_handler.reference, target_storage_handler.reference)
            target_storage_handler.write_properties(Migration.transform_from_latest(copy.deepcopy(properties)), datetime.datetime.now())
            logging.getLogger("migration").info(f"Copying data item ({index + 1}/{count}) {data_item_uuid} to new library.")
            return ReaderInfo(properties, [False], self._is_storage_handler_large_format(target_storage_handler), target_storage_handler, target_storage_handler.reference)
        logging.getLogger("migration").warning(f"Unable to copy data item {data_item_uuid} to new library.")
        return None

    def _migrate_library_properties(self, library_properties: typing.Dict, reader_info_list: typing.List[ReaderInfo]) -> None:
        self._write_properties(library_properties)

        for reader_info in reader_info_list:
            data_item_properties = Utility.clean_dict(reader_info.properties if reader_info.properties else dict())
            if data_item_properties.get("version", 0) == DataItem.DataItem.writer_version:
                file_datetime = DataItem.DatetimeToStringConverter().convert_back(data_item_properties.get("created", "1900-01-01T00:00:00.000000"))
                reader_info.storage_handler.write_properties(reader_info.properties, file_datetime)


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


class MemoryLibraryHandler(LibraryHandler):

    def __init__(self, *, library_properties: typing.Dict = None, data_properties_map: typing.Dict = None, data_map: typing.Dict = None, trash_map: typing.Dict = None, data_read_event: Event.Event = None):
        self.__library_properties = library_properties if library_properties is not None else dict()
        self.__data_properties_map = data_properties_map if data_properties_map is not None else dict()
        self.__data_map = data_map if data_map is not None else dict()
        self.__trash_map = trash_map if trash_map is not None else dict()
        super().__init__()
        self._test_data_read_event = data_read_event or Event.Event()

    @property
    def library_properties(self) -> typing.Dict:
        return self.__library_properties

    @property
    def data_properties_map(self) -> typing.Dict:
        return self.__data_properties_map

    @property
    def data_map(self) -> typing.Dict:
        return self.__data_map

    @property
    def trash_map(self) -> typing.Dict:
        return self.__trash_map

    def _get_identifier(self) -> str:
        return "memory"

    def _read_properties(self) -> typing.Dict:
        return copy.deepcopy(self.__library_properties)

    def _write_properties(self, properties: typing.Dict) -> None:
        self.__library_properties.clear()
        self.__library_properties.update(copy.deepcopy(properties))

    def _find_storage_handlers(self) -> typing.List:
        storage_handlers = list()
        for key in sorted(self.__data_properties_map):
            self.__data_properties_map[key].setdefault("uuid", str(uuid.uuid4()))
            storage_handlers.append(MemoryStorageHandler(key, self.__data_properties_map, self.__data_map, self._test_data_read_event))
        return storage_handlers

    def _is_storage_handler_large_format(self, storage_handler) -> bool:
        return False

    def _prune(self) -> None:
        pass  # disabled for testing self.__trash_map = dict()

    def _make_storage_handler(self, data_item: DataItem.DataItem, file_handler=None):
        data_item_uuid_str = str(data_item.uuid)
        return MemoryStorageHandler(data_item_uuid_str, self.__data_properties_map, self.__data_map, self._test_data_read_event)

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

    def _get_migration_stages(self) -> typing.List:
        return [None]

    def _read_library_properties(self, migration_stage) -> typing.Dict:
        return copy.deepcopy(self.__library_properties)

    def _find_data_items(self, migration_stage) -> typing.List:
        return self._find_storage_handlers()

    def _migrate_data_item(self, reader_info: ReaderInfo, index: int, count: int) -> typing.Optional[ReaderInfo]:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
        if reader_info.changed_ref[0]:
            self.data_properties_map[storage_handler.reference] = Migration.transform_from_latest(copy.deepcopy(properties))
        return reader_info

    def _migrate_library_properties(self, library_properties: typing.Dict, reader_info_list: typing.List[ReaderInfo]) -> None:
        self._write_properties(library_properties)

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


class FileStorageSystem:
    """The file storage system which tracks libraries and items within those libraries.

    The JSON-compatible dict for each library is managed by this object. It is loaded and kept in
    memory and written out when necessary.
    """

    def __init__(self, library_handler: LibraryHandler):
        self.__library_handler = library_handler
        self.__write_delay_counts = dict()
        self.__write_delay_count = 0

    def reset(self):
        self.__library_handler.reset()

    def get_auto_migrations(self) -> typing.List:
        return list()

    @property
    def _library_handler(self) -> LibraryHandler:
        return self.__library_handler

    def __write_properties(self, object):
        if self.__write_delay_counts.get(object, 0) == 0:
            persistent_object_parent = object.persistent_object_parent if object else None
            if object and isinstance(object, DataItem.DataItem):
                self.__library_handler.rewrite_data_item_properties(object)
            elif not persistent_object_parent:
                if self.__write_delay_count == 0:
                    self.__library_handler.write_properties()
            else:
                self.__write_properties(persistent_object_parent.parent)

    @property
    def library_storage_properties(self) -> typing.Dict:
        """Get the properties; used for testing."""
        return self.__library_handler.properties_copy

    def get_properties(self, object):
        return self.__get_storage_dict(object)

    def __get_storage_dict(self, object):
        """Return the storage dict for the object. The storage dict is a fragment of the properties dict."""
        persistent_object_parent = object.persistent_object_parent
        if isinstance(object, DataItem.DataItem):
            return self.__library_handler.get_data_item_properties(object)
        if not persistent_object_parent:
            return self.__library_handler.properties
        else:
            parent_storage_dict = self.__get_storage_dict(persistent_object_parent.parent)
            return object.get_accessor_in_parent()(parent_storage_dict)

    def __update_modified_and_get_storage_dict(self, object):
        storage_dict = self.__get_storage_dict(object)
        self.__library_handler.update_modified(storage_dict, object.modified)
        persistent_object_parent = object.persistent_object_parent
        parent = persistent_object_parent.parent if persistent_object_parent else None
        if parent:
            self.__update_modified_and_get_storage_dict(parent)
        return storage_dict

    def insert_item(self, parent, name: str, before_index: int, item) -> None:
        if isinstance(item, DataItem.DataItem):
            item.persistent_object_context = parent.persistent_object_context
            is_write_delayed = item and self.is_write_delayed(item)
            self.__library_handler.insert_data_item(item, is_write_delayed)
        else:
            storage_dict = self.__update_modified_and_get_storage_dict(parent)
            self.__library_handler.insert_item(storage_dict, name, before_index, item)
            item.persistent_object_context = parent.persistent_object_context
            self.__write_properties(parent)

    def remove_item(self, parent, name, index, item):
        if isinstance(item, DataItem.DataItem):
            self.delete_item(item, safe=True)
            item.persistent_object_context = None
            self.__library_handler.remove_data_item(item)
        else:
            storage_dict = self.__update_modified_and_get_storage_dict(parent)
            self.__library_handler.remove_item(storage_dict, name, index)
            self.__write_properties(parent)
            item.persistent_object_context = None

    def set_item(self, parent, name, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        if item:
            self.__library_handler.set_item(storage_dict, name, item)
            item.persistent_object_context = parent.persistent_object_context
        else:
            self.__library_handler.clear_item(storage_dict, name)
        self.__write_properties(parent)

    def set_property(self, object, name, value):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        self.__library_handler.set_property(storage_dict, name, value)
        self.__write_properties(object)

    def clear_property(self, object, name):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        self.__library_handler.clear_property(storage_dict, name)
        self.__write_properties(object)

    def restore_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[dict]:
        return self.__library_handler.restore_item(data_item_uuid)

    def prune(self) -> None:
        self.__library_handler.prune()

    def get_storage_property(self, data_item: DataItem.DataItem, name: str) -> typing.Optional[str]:
        return self.__library_handler.get_data_item_property(data_item, name)

    def read_external_data(self, item, name):
        if isinstance(item, DataItem.DataItem) and name == "data":
            return self.__library_handler.read_data_item_data(item)
        return None

    def write_external_data(self, item, name, value) -> None:
        if isinstance(item, DataItem.DataItem) and name == "data":
            self.__library_handler.write_data_item_data(item, value)

    def delete_item(self, data_item, safe: bool=False) -> None:
        self.__library_handler.delete_data_item(data_item, safe=safe)

    def enter_write_delay(self, object) -> None:
        count = self.__write_delay_counts.setdefault(object, 0)
        if count == 0:
            self.__library_handler.set_write_delayed(object, True)
        self.__write_delay_counts[object] = count + 1

    def exit_write_delay(self, object) -> None:
        count = self.__write_delay_counts.get(object, 1)
        count -= 1
        if count == 0:
            self.__library_handler.set_write_delayed(object, False)
            self.__write_delay_counts.pop(object)
        else:
            self.__write_delay_counts[object] = count

    def is_write_delayed(self, data_item) -> bool:
        if isinstance(data_item, DataItem.DataItem):
            return self.__write_delay_counts.get(data_item, 0) > 0
        return False

    def rewrite_item(self, item) -> None:
        if isinstance(item, DataItem.DataItem):
            self.__library_handler.rewrite_data_item_properties(item)
        else:
            self.__write_properties(item)

    def find_data_items(self) -> typing.List:
        return self.__library_handler.find_data_items()

    def read_library(self) -> typing.Dict:
        return self.__library_handler.read_library()

    def migrate_to_latest(self) -> None:
        self.__library_handler.migrate_to_latest()

    def _enter_transaction(self):
        self.__write_delay_count += 1
        return self

    def _exit_transaction(self):
        self.__write_delay_count -= 1
        if self.__write_delay_count == 0:
            self.__write_properties(None)


def make_library_handler(profile_context, d: typing.Dict) -> typing.Optional[LibraryHandler]:
    if d.get("type") == "project_index":
        project_path = pathlib.Path(d.get("project_path"))
        return FileLibraryHandler(project_path)
    elif d.get("type") == "legacy_project":
        project_path = pathlib.Path(d.get("project_path"))
        for project_file, project_dir in FileLibraryHandler._get_migration_paths(project_path):
            if project_file.exists():
                return FileLibraryHandler(project_file)
        return None
    elif d.get("type") == "memory":
        # the profile context must be valid here.
        library_properties = profile_context.project_properties
        data_properties_map = profile_context.data_properties_map
        data_map = profile_context.data_map
        trash_map = profile_context.trash_map
        return MemoryLibraryHandler(library_properties=library_properties, data_properties_map=data_properties_map, data_map=data_map, trash_map=trash_map)
    return None
