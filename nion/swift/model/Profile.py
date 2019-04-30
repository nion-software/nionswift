# standard libraries
import logging
import pathlib
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

    def __init__(self, storage_system=None, storage_cache=None, *, auto_project: bool = True):
        super().__init__()
        self.define_type("profile")
        self.define_relationship("workspaces", WorkspaceLayout.factory)
        self.define_relationship("data_groups", DataGroup.data_group_factory)
        self.define_property("workspace_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("data_item_references", dict(), hidden=True)  # map string key to data item, used for data acquisition channels
        self.define_property("data_item_variables", dict(), hidden=True)  # map string key to data item, used for reference in scripts
        self.define_property("project_references", list())

        self.storage_system = storage_system if storage_system else FileStorageSystem.FileStorageSystem(FileStorageSystem.MemoryLibraryHandler())

        if auto_project:
            self.__projects = [Project.Project(FileStorageSystem.MemoryLibraryHandler())]
        else:
            self.__projects = list()

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
        self.profile_context = None

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
        for project_reference in self.project_references:
            # note: storage system is passed for use during testing
            library_handler = FileStorageSystem.make_library_handler(self.profile_context, project_reference)
            if library_handler:
                project = Project.Project(library_handler)
                self.__append_project(project)

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

    def add_project_reference(self, project_reference: typing.Dict) -> None:
        project_references = self.project_references
        project_references.append(project_reference)
        self._set_persistent_property_value("project_references", project_references)

    def add_project_folder(self, project_path: pathlib.Path) -> None:
        project_reference = {"type": "project_index", "project_path": str(project_path)}
        self.add_project_reference(project_reference)

    def __append_project(self, project):
        self.__projects.append(project)
        self.__item_loaded_event_listeners.append(project.item_loaded_event.listen(self.__project_item_loaded))


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
        self.__profile = None

    def create_profile(self) -> Profile:
        if not self.__profile:
            project_handler = FileStorageSystem.MemoryLibraryHandler(library_properties=self.project_properties,
                                                                     data_properties_map=self.data_properties_map,
                                                                     data_map=self.data_map,
                                                                     trash_map=self.trash_map,
                                                                     data_read_event=self._test_data_read_event)
            project = Project.Project(project_handler)
            project_reference = project.project_reference
            project.close()
            storage_system = FileStorageSystem.FileStorageSystem(self.__profile_handler)
            profile = Profile(storage_system=storage_system, storage_cache=self.storage_cache, auto_project=False)
            profile.add_project_reference(project_reference)
            profile.storage_system = storage_system
            profile.profile_context = self
            self.__profile = profile
            return profile
        else:
            storage_system = FileStorageSystem.FileStorageSystem(self.__profile_handler)
            profile = Profile(storage_system=storage_system, storage_cache=self.storage_cache, auto_project=False)
            profile.storage_system = storage_system
            profile.profile_context = self
            return profile

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        pass
