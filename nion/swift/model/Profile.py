# standard libraries
import copy
import datetime
import json
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
from nion.utils import Model
from nion.utils import Observable
from nion.utils import Persistence
from nion.utils import Selection


class Profile(Observable.Observable, Persistence.PersistentObject):

    def __init__(self, storage_system=None, storage_cache=None, *, auto_project: bool = True):
        super().__init__()
        self.define_type("profile")
        self.define_relationship("workspaces", WorkspaceLayout.factory)
        self.define_relationship("data_groups", DataGroup.data_group_factory)
        self.define_property("workspace_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("data_item_references", dict(), hidden=True)  # map string key to data item, used for data acquisition channels
        self.define_property("data_item_variables", dict(), hidden=True)  # map string key to data item, used for reference in scripts
        self.define_property("project_references", list())
        self.define_property("work_project_reference_uuid", converter=Converter.UuidToStringConverter())

        self.storage_system = storage_system if storage_system else FileStorageSystem.MemoryPersistentStorageSystem()

        if auto_project:
            self.__projects = [Project.Project(FileStorageSystem.MemoryLibraryHandler(), {"type": "memory", "uuid": str(uuid.uuid4())})]
            self.__work_project = self.__projects[0]
        else:
            self.__projects = list()
            self.__work_project = None

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

        # the projects model is a property model where the value is the current list of projects.
        self.projects_model = Model.PropertyModel(copy.copy(self.__projects))

        # two selection models are provided: one where the value is the ordered list of selected projects; the other
        # is a single selected project.
        self.selected_projects_model = Model.PropertyModel(set())
        self.selected_project_model = Model.PropertyModel(None)

        # the projects selection is the common object to represent the user's selected projects, if any.
        self.projects_selection = Selection.IndexedSelection(Selection.Style.multiple)

        # define a function to track changes to the selection object and update the selection models.
        def update_selected_projects_models():
            indexes = self.projects_selection.ordered_indexes
            self.selected_project_model.value = self.__projects[list(indexes)[0]] if len(indexes) == 1 else None
            selected_projects = list()
            for index in indexes:
                if 0 <= index < len(self.__projects):
                    selected_projects.append(self.__projects[index])
            self.selected_projects_model.value = selected_projects

        # connect the listener
        self.__projects_selection_changed_event_listener = self.projects_selection.changed_event.listen(update_selected_projects_models)

    @property
    def projects(self) -> typing.List[Project.Project]:
        return self.__projects

    @property
    def _profile_storage_system(self) -> FileStorageSystem.StorageSystem:
        return self.storage_system

    @property
    def _target_project_storage_system(self) -> typing.Optional[FileStorageSystem.ProjectStorageSystem]:
        return self.__work_project._project_storage_system if self.__work_project else None

    @property
    def _work_project(self) -> typing.Optional[Project.Project]:
        return self.__work_project

    def open(self, document_model):
        for project in self.__projects:
            project.open()
        self.__document_model = document_model

    def close(self):
        # detach project listeners
        for item_loaded_event_listener in self.__item_loaded_event_listeners:
            item_loaded_event_listener.close()
        self.__item_loaded_event_listeners.clear()
        self.__projects_selection_changed_event_listener.close()
        self.__projects_selection_changed_event_listener = None

    def transaction_context(self):
        """Return a context object for a document-wide transaction."""
        class Transaction:
            def __init__(self, profile):
                self.__profile = profile

            def __enter__(self):
                self.__profile._profile_storage_system.enter_write_delay(self.__profile)
                for project in self.__profile.projects:
                    project._project_storage_system.enter_transaction()
                return self

            def __exit__(self, type, value, traceback):
                self.__profile._profile_storage_system.exit_write_delay(self.__profile)
                self.__profile._profile_storage_system.rewrite_item(self.__profile)
                for project in self.__profile.projects:
                    project._project_storage_system.exit_transaction()

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

    def read_profile(self) -> None:
        # read the properties from the storage system
        properties = self.storage_system.read_library()

        # if the properties match the current version, read the properties.
        if properties.get("version", 0) == FileStorageSystem.PROFILE_VERSION:
            self.begin_reading()
            try:
                self.read_from_dict(properties)
            finally:
                self.finish_reading()
            self.storage_system.set_property(self, "uuid", str(self.uuid))
            self.storage_system.set_property(self, "version", FileStorageSystem.PROFILE_VERSION)

        # create project objects for each project reference
        for project_reference in self.project_references:
            # note: project context is passed for use during testing
            project = Project.make_project(self.profile_context, project_reference)
            if project:
                self.__append_project(project)

    def read_projects(self) -> None:
        for project in self.__projects:
            project.read_project()

        # attempt to establish existing work project
        if self.work_project_reference_uuid:
            for project in self.__projects:
                if str(self.work_project_reference_uuid) == project.project_reference.get("uuid", None):
                    self.__work_project = project
                    break

        # if existing one cannot be found, attempt to create one
        if not self.__work_project:

            def create_work_project_files(project_path: pathlib.Path) -> typing.Dict:
                project_path = project_path.parent / "Work.nsproj"
                suffix = str()
                if project_path.exists():
                    suffix = f" {datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    project_path =  project_path.parent / f"Work{suffix}.nsproj"
                logging.getLogger("loader").warning(f"Created work project {project_path.parent / project_path.stem}")
                project_data_json = json.dumps({"version": FileStorageSystem.PROJECT_VERSION, "uuid": str(uuid.uuid4()), "project_data_folders": [f"Work Data{suffix}"]})
                project_path.write_text(project_data_json, "utf-8")
                return {"type": "project_index", "uuid": str(uuid.uuid4()), "project_path": str(project_path)}

            project_path = self.storage_system.path
            work_project_reference = create_work_project_files(project_path)

            if work_project_reference:
                self.add_project_reference(work_project_reference)
                project = Project.make_project(self.profile_context, work_project_reference)
                if project:
                    self.__append_project(project)
                    self.work_project_reference_uuid = uuid.UUID(work_project_reference["uuid"])
                    self.__work_project = project

        if not self.__work_project:
            logging.getLogger("loader").warning(f"Work project could not be loaded or created.")

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
        assert "type" in project_reference
        assert "uuid" in project_reference
        project_references = self.project_references
        project_references.append(project_reference)
        self._set_persistent_property_value("project_references", project_references)

    def add_project_folder(self, project_path: pathlib.Path) -> None:
        project_reference = {"type": "project_index", "uuid": str(uuid.uuid4()), "project_path": str(project_path)}
        self.add_project_reference(project_reference)

    def add_legacy_project_folder(self, project_path: pathlib.Path) -> None:
        project_reference = {"type": "legacy_project", "uuid": str(uuid.uuid4()), "project_path": str(project_path)}
        self.add_project_reference(project_reference)

    def __append_project(self, project):
        self.__projects.append(project)
        self.projects_model.value = copy.copy(self.__projects)
        self.__item_loaded_event_listeners.append(project.item_loaded_event.listen(self.__project_item_loaded))


class MemoryProfileContext:
    # used for testing

    def __init__(self):
        self.storage_cache = Cache.DictStorageCache()

        self.profile_properties = dict()
        self.__storage_system = FileStorageSystem.MemoryPersistentStorageSystem(library_properties=self.profile_properties)

        self.project_properties = {"version": FileStorageSystem.PROJECT_VERSION}
        self.data_properties_map = dict()
        self.data_map = dict()
        self.trash_map = dict()
        self._test_data_read_event = Event.Event()
        self.__profile = None

    def create_profile(self) -> Profile:
        if not self.__profile:
            storage_system = self.__storage_system
            profile = Profile(storage_system=storage_system, storage_cache=self.storage_cache, auto_project=False)
            project_reference_uuid = uuid.uuid4()
            project_reference = {"type": "memory", "uuid": str(project_reference_uuid)}
            profile.add_project_reference(project_reference)
            profile.storage_system = storage_system
            profile.profile_context = self
            profile.work_project_reference_uuid = project_reference_uuid
            self.__profile = profile
            return profile
        else:
            storage_system = self.__storage_system
            profile = Profile(storage_system=storage_system, storage_cache=self.storage_cache, auto_project=False)
            profile.storage_system = storage_system
            profile.profile_context = self
            return profile

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        pass
