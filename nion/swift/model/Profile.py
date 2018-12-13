# standard libraries
import logging
import os
import pathlib
import shutil
import typing
import uuid

# local libraries
from nion.swift.model import Cache
from nion.swift.model import DataItem
from nion.swift.model import FileStorageSystem
from nion.utils import Event
from nion.utils import Persistence


class Profile:

    def __init__(self, storage_system=None, storage_cache=None, ignore_older_files=False):
        self.__storage_system = storage_system if storage_system else FileStorageSystem.FileStorageSystem(FileStorageSystem.MemoryLibraryHandler())
        self.__ignore_older_files = ignore_older_files
        self.storage_cache = storage_cache if storage_cache else Cache.DictStorageCache()
        # the persistent object context allows reading/writing of objects to the persistent storage specific to them.
        # there is a single shared object context per profile.
        self.persistent_object_context = Persistence.PersistentObjectContext()

    def open(self, document_model):
        self.__storage_system.reset()  # this makes storage reusable during tests
        self.persistent_object_context._set_persistent_storage_for_object(document_model, self.__storage_system)

    def close(self):
        pass

    def validate_uuid_and_version(self, document_model, uuid_: uuid.UUID, version: int) -> None:
        self.__storage_system.set_property(document_model, "uuid", str(uuid_))
        self.__storage_system.set_property(document_model, "version", version)

    def restore_data_item(self, data_item_uuid: uuid.UUID) -> typing.Tuple[typing.Optional[dict], bool]:
        return self.__storage_system.restore_item(data_item_uuid)

    def prune(self):
        self.__storage_system.prune()

    def read_library(self) -> typing.Dict:
        # first read the library (for deletions) and the library items from the primary storage systems
        return self.__storage_system.read_library(self.__ignore_older_files)


class MemoryProfileContext:
    # used for testing

    def __init__(self):
        self.library_properties = dict()
        self.data_properties_map = dict()
        self.data_map = dict()
        self.trash_map = dict()
        self._test_data_read_event = Event.Event()
        library_handler = FileStorageSystem.MemoryLibraryHandler(library_properties=self.library_properties,
                                                         data_properties_map=self.data_properties_map,
                                                         data_map=self.data_map, trash_map=self.trash_map,
                                                         data_read_event=self._test_data_read_event)
        self.storage_system = FileStorageSystem.FileStorageSystem(library_handler)

    def create_profile(self, *, storage_cache=None) -> Profile:
        storage_system = self.storage_system
        storage_cache = storage_cache or Cache.DictStorageCache()
        profile = Profile(storage_system=storage_system, storage_cache=storage_cache)
        profile.storage_cache = storage_cache
        profile.storage_system = storage_system
        return profile

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        pass


def _migrate_library(workspace_dir: pathlib.Path, do_logging: bool=True) -> pathlib.Path:
    """ Migrate library to latest version. """

    library_path_11 = workspace_dir / "Nion Swift Workspace.nslib"
    library_path_12 = workspace_dir / "Nion Swift Library 12.nslib"
    library_path_13 = workspace_dir / "Nion Swift Library 13.nslib"

    library_paths = (library_path_11, library_path_12)
    library_path_latest = library_path_13

    if not os.path.exists(library_path_latest):
        for library_path in reversed(library_paths):
            if os.path.exists(library_path):
                if do_logging:
                    logging.info("Migrating library: %s -> %s", library_path, library_path_latest)
                shutil.copyfile(library_path, library_path_latest)
                break

    return library_path_latest


class AutoMigration:
    def __init__(self, library_path: pathlib.Path=None, paths: typing.List[pathlib.Path]=None, log_copying: bool=True, storage_system=None):
        self.library_path = library_path
        self.paths = paths
        self.log_copying = log_copying
        self.storage_system = storage_system


def create_profile(workspace_dir: pathlib.Path, do_logging: bool, force_create: bool) -> typing.Tuple[typing.Optional[Profile], bool]:
    library_path = _migrate_library(workspace_dir, do_logging)
    if not force_create and not os.path.exists(library_path):
        return None, False
    create_new_document = not os.path.exists(library_path)
    if do_logging:
        if create_new_document:
            logging.info(f"Creating new document: {library_path}")
        else:
            logging.info(f"Using existing document {library_path}")
    auto_migrations = list()
    auto_migrations.append(AutoMigration(pathlib.Path(workspace_dir) / "Nion Swift Workspace.nslib", [pathlib.Path(workspace_dir) / "Nion Swift Data"]))
    auto_migrations.append(AutoMigration(pathlib.Path(workspace_dir) / "Nion Swift Workspace.nslib", [pathlib.Path(workspace_dir) / "Nion Swift Data 10"]))
    auto_migrations.append(AutoMigration(pathlib.Path(workspace_dir) / "Nion Swift Workspace.nslib", [pathlib.Path(workspace_dir) / "Nion Swift Data 11"]))
    auto_migrations.append(AutoMigration(pathlib.Path(workspace_dir) / "Nion Swift Library 12.nslib", [pathlib.Path(workspace_dir) / "Nion Swift Data 12"]))
    # NOTE: when adding an AutoMigration here, also add the corresponding file copy in _migrate_library
    storage_system = FileStorageSystem.FileStorageSystem(FileStorageSystem.FileLibraryHandler(library_path))
    cache_filename = f"Nion Swift Cache {DataItem.DataItem.storage_version}.nscache"
    cache_path = workspace_dir / cache_filename
    storage_cache = Cache.DbStorageCache(cache_path)
    return Profile(storage_system=storage_system, storage_cache=storage_cache, ignore_older_files=False), create_new_document
