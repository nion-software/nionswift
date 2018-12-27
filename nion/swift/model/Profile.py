# standard libraries
import logging
import os
import pathlib
import shutil
import typing
import uuid

# local libraries
from nion.swift.model import Cache
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import FileStorageSystem
from nion.swift.model import Project
from nion.swift.model import WorkspaceLayout
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Observable
from nion.utils import Persistence


class Profile(Observable.Observable, Persistence.PersistentObject):

    profile_version = 2

    def __init__(self, storage_system=None, projects: typing.Optional[typing.List[Project.Project]] = None, storage_cache=None):
        super().__init__()
        self.define_type("profile")
        self.define_relationship("workspaces", WorkspaceLayout.factory)
        self.define_relationship("data_groups", DataGroup.data_group_factory)
        self.define_property("workspace_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("data_item_references", dict(), hidden=True)  # map string key to data item, used for data acquisition channels
        self.define_property("data_item_variables", dict(), hidden=True)  # map string key to data item, used for reference in scripts
        self.storage_system = storage_system if storage_system else FileStorageSystem.FileStorageSystem(FileStorageSystem.MemoryLibraryHandler())
        self.__projects = projects if projects is not None else [Project.Project(FileStorageSystem.MemoryLibraryHandler())]
        self.storage_cache = storage_cache if storage_cache else Cache.DictStorageCache()
        # the persistent object context allows reading/writing of objects to the persistent storage specific to them.
        # there is a single shared object context per profile.
        self.persistent_object_context = Persistence.PersistentObjectContext()
        self.persistent_object_context._set_persistent_storage_for_object(self, self.storage_system)
        # attach project listeners
        self.__item_loaded_event_listeners = list()
        for project in self.__projects:
            self.__item_loaded_event_listeners.append(project.item_loaded_event.listen(self.__project_item_loaded))
        self.__document_model = None

    @property
    def projects(self) -> typing.List[Project.Project]:
        return self.__projects

    @property
    def _profile_storage_system(self) -> FileStorageSystem.FileStorageSystem:
        return self.storage_system

    @property
    def _target_project_storage_system(self) -> FileStorageSystem.FileStorageSystem:
        return self.__projects[0]._project_storage_system

    def open(self, document_model):
        self.storage_system.reset()  # this makes storage reusable during tests
        for project in self.__projects:
            project.open()
        self.__document_model = document_model

    def close(self):
        # detach project listeners
        for item_loaded_event_listener in self.__item_loaded_event_listeners:
            item_loaded_event_listener.close()
        self.__item_loaded_event_listeners.clear()

    def transaction_context(self):
        """Return a context object for a document-wide transaction."""
        class Transaction:
            def __init__(self, profile):
                self.__profile = profile

            def __enter__(self):
                self.__profile._profile_storage_system.enter_write_delay(self.__profile)
                for project in self.__profile.projects:
                    project._project_storage_system._enter_transaction()
                return self

            def __exit__(self, type, value, traceback):
                self.__profile._profile_storage_system.exit_write_delay(self.__profile)
                self.__profile._profile_storage_system.rewrite_item(self.__profile)
                for project in self.__profile.projects:
                    project._project_storage_system._exit_transaction()

        return Transaction(self)

    def restore_data_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[dict]:
        for project in self.__projects:
            d = project.restore_data_item(data_item_uuid)
            if d is not None:
                return d
        return None

    def prune(self):
        for project in self.__projects:
            project.prune()

    def read(self) -> None:
        properties = self.storage_system.read_library()
        self.begin_reading()
        try:
            self.read_from_dict(properties)
        finally:
            self.finish_reading()
        self.storage_system.set_property(self, "uuid", str(self.uuid))
        self.storage_system.set_property(self, "version", Profile.profile_version)

    def read_projects(self) -> None:
        for project in self.__projects:
            project.read()

    @property
    def data_item_variables(self):
        return self._get_persistent_property_value("data_item_variables")

    @data_item_variables.setter
    def data_item_variables(self, value):
        self._set_persistent_property_value("data_item_variables", value)

    @property
    def data_item_references(self) -> typing.Dict[str, uuid.UUID]:
        return {k: uuid.UUID(v) for k, v in self._get_persistent_property_value("data_item_references").items()}

    def set_data_item_reference(self, key: str, data_item: DataItem.DataItem) -> None:
        data_item_references = self.data_item_references
        data_item_references[key] = data_item.uuid
        self._set_persistent_property_value("data_item_references", {k: str(v) for k, v in data_item_references.items()})

    def clear_data_item_reference(self, key: str) -> None:
        data_item_references = self.data_item_references
        del data_item_references[key]
        self._set_persistent_property_value("data_item_references", {k: str(v) for k, v in data_item_references.items()})

    def __project_item_loaded(self, item_type: str, item_d: typing.Dict, storage_system) -> None:
        self.__document_model.handle_load_item(item_type, item_d, storage_system)


class MemoryProfileContext:
    # used for testing

    def __init__(self):
        self.storage_cache = Cache.DictStorageCache()

        self.profile_properties = dict()
        self.__profile_handler = FileStorageSystem.MemoryLibraryHandler(library_properties=self.profile_properties)

        self.project_properties = dict()
        self.data_properties_map = dict()
        self.data_map = dict()
        self.trash_map = dict()
        self._test_data_read_event = Event.Event()
        self.__project_handler = FileStorageSystem.MemoryLibraryHandler(library_properties=self.project_properties,
                                                                        data_properties_map=self.data_properties_map,
                                                                        data_map=self.data_map,
                                                                        trash_map=self.trash_map,
                                                                        data_read_event=self._test_data_read_event)

    def create_profile(self) -> Profile:
        project = Project.Project(self.__project_handler)
        storage_system = FileStorageSystem.FileStorageSystem(self.__profile_handler)
        return Profile(storage_system=storage_system, projects=[project], storage_cache=self.storage_cache)

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
    return Profile(storage_system=storage_system, storage_cache=storage_cache), create_new_document
