# standard libraries
import copy
import datetime
import functools
import json
import logging
import pathlib
import typing
import uuid
import weakref

# local libraries
from nion.swift.model import Cache
from nion.swift.model import Changes
from nion.swift.model import Connection
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayItem
from nion.swift.model import FileStorageSystem
from nion.swift.model import Persistence
from nion.swift.model import Project
from nion.swift.model import Symbolic
from nion.swift.model import WorkspaceLayout
from nion.utils import Converter
from nion.utils import Event
from nion.utils import ListModel
from nion.utils import Model
from nion.utils import Observable
from nion.utils import Selection


class Profile(Observable.Observable, Persistence.PersistentObject):

    def __init__(self, storage_system=None, storage_cache=None, *, auto_project: bool = True):
        super().__init__()

        # handle special case of auto project - make the auto project active
        project_uuid_str = None
        active_project_uuids = list()
        if auto_project:
            project_uuid_str = str(uuid.uuid4())
            active_project_uuids = [project_uuid_str]

        self.define_root_context()
        self.define_type("profile")
        self.define_relationship("workspaces", WorkspaceLayout.factory)
        self.define_relationship("data_groups", DataGroup.data_group_factory)
        self.define_property("workspace_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("data_item_references", dict(), hidden=True)  # map string key to data item, used for data acquisition channels
        self.define_property("data_item_variables", dict(), hidden=True)  # map string key to data item, used for reference in scripts
        self.define_property("project_references", list())
        self.define_property("target_project_reference_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("work_project_reference_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("closed_items", list())
        self.define_property("active_project_uuids", active_project_uuids)

        self.project_inserted_event = Event.Event()
        self.project_removed_event = Event.Event()

        self.storage_system = storage_system if storage_system else FileStorageSystem.MemoryPersistentStorageSystem()
        self.storage_system.load_properties()

        if auto_project:
            project_storage_system = FileStorageSystem.MemoryProjectStorageSystem()
            project_storage_system.load_properties()
            project = Project.Project(project_storage_system, {"type": "memory", "uuid": project_uuid_str})
            self.__projects = [project]
            project.project_uuid_str = project_uuid_str
            self.__work_project = self.__projects[0]
            self.__target_project = self.__projects[0]
        else:
            self.__projects = list()
            self.__work_project = None
            self.__target_project = None

        self.storage_cache = storage_cache if storage_cache else Cache.DictStorageCache()

        self.set_storage_system(self.storage_system)

        for project in self.__projects:
            self.update_item_context(project)
            project.about_to_be_inserted(self)

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

        # define a function to update project selections
        def projects_changed(property_name: str) -> None:
            indexes = set()
            for project in self.selected_projects_model.value:
                if project in self.projects_model.value:
                    indexes.add(self.projects_model.value.index(project))
            self.projects_selection.set_multiple(indexes)

        # update selection when projects change
        self.__projects_changed_event_listener = self.projects_model.property_changed_event.listen(projects_changed)

    @property
    def projects(self) -> typing.List[Project.Project]:
        return self.__projects

    @property
    def _profile_storage_system(self) -> FileStorageSystem.PersistentStorageSystem:
        return self.storage_system

    @property
    def target_project(self) -> typing.Optional[Project.Project]:
        return self.__target_project

    @property
    def work_project(self) -> typing.Optional[Project.Project]:
        return self.__work_project

    def set_target_project(self, project: Project.Project) -> None:
        if project != self.__target_project:
            self.target_project_reference_uuid = project.project_uuid_str if project else None
            self.__target_project = project
            self.property_changed_event.fire("target_project")

    def set_work_project(self, project: Project.Project) -> None:
        if project != self.__work_project:
            if any(data_item.is_live for data_item in self.__work_project.data_items):
                raise Exception("Work project contains live items.")
            if any(display_item.is_live for display_item in self.__work_project.display_items):
                raise Exception("Work project contains live items.")
            assert project.project_uuid_str is not None
            self.work_project_reference_uuid = project.project_uuid_str
            self.__work_project = project
            self.property_changed_event.fire("work_project")

    def target_project_for_item(self, item) -> typing.Optional[Project.Project]:

        def get_item_project(item) -> typing.Optional[Project.Project]:
            container = item.container
            if isinstance(container, Project.Project):
                return container
            return get_item_project(container) if container else None

        if isinstance(item, DisplayItem.DisplayItem):
            target_projects = set(get_item_project(data_item) for data_item in item.data_items)
            target_project = list(target_projects)[0] if len(target_projects) == 1 else None
            if target_project:
                return target_project
        elif isinstance(item, DataStructure.DataStructure):
            target_projects = set(get_item_project(data_structure_item) for data_structure_item in item.referenced_objects)
            target_project = list(target_projects)[0] if len(target_projects) == 1 else None
            if target_project:
                return target_project
        elif isinstance(item, Symbolic.Computation):
            target_projects = set()
            base_objects = item.direct_input_items
            for variable_item in base_objects:
                target_projects.add(get_item_project(variable_item))
            target_project = list(target_projects)[0] if len(target_projects) == 1 else None
            if target_project:
                return target_project
        elif isinstance(item, Connection.Connection):
            target_projects = set()
            for connection_item in item.connected_items:
                project = get_item_project(connection_item)
                target_projects.add(project)
            # target_projects = set(get_item_project(connection_item) for connection_item in item.connected_items)
            target_project = list(target_projects)[0] if len(target_projects) == 1 else None
            if target_project:
                return target_project

        return self.target_project or self.work_project

    def open(self, document_model):
        for project in self.__projects:
            project.open()
        self.__document_model = document_model

    def about_to_be_removed(self, container):
        for project in self.__projects:
            project.about_to_be_removed(self)
        super().about_to_be_removed(container)

    def close_relationships(self) -> None:
        for project in self.__projects:
            project.persistent_object_context = None
            project.close()
        super().close_relationships()

    def close(self):
        # detach project listeners
        self.__projects_selection_changed_event_listener.close()
        self.__projects_selection_changed_event_listener = None
        self.__projects_changed_event_listener.close()
        self.__projects_changed_event_listener = None
        super().close()

    def insert_model_item(self, container, name, before_index, item):
        """Insert a model item. Let this item's container do it if possible; otherwise do it directly.

        Passing responsibility to this item's container allows the library to easily track dependencies.
        However, if this item isn't yet in the library hierarchy, then do the operation directly.
        """
        if self.container:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> Changes.UndeleteLog:
        """Remove a model item. Let this item's container do it if possible; otherwise do it directly.

        Passing responsibility to this item's container allows the library to easily track dependencies.
        However, if this item isn't yet in the library hierarchy, then do the operation directly.
        """
        if self.container:
            return self.container.remove_model_item(container, name, item, safe=safe)
        else:
            container.remove_item(name, item)
            return Changes.UndeleteLog()

    def _get_related_item(self, item_specifier: Persistence.PersistentObjectSpecifier) -> typing.Optional[Persistence.PersistentObject]:

        def check_data_group(data_group: DataGroup.DataGroup, item_specifier: Persistence.PersistentObjectSpecifier) -> typing.Optional[DataGroup.DataGroup]:
            for data_group in data_group.data_groups:
                if data_group.uuid == item_specifier.item_uuid:
                    return data_group
                matching_data_group = check_data_group(data_group, item_specifier)
                if matching_data_group:
                    return matching_data_group
            return None

        for data_group in self.data_groups:
            if data_group.uuid == item_specifier.item_uuid:
                return data_group
            matching_data_group = check_data_group(data_group, item_specifier)
            if matching_data_group:
                return matching_data_group

        return super()._get_related_item(item_specifier)

    def transaction_context(self):
        """Return a context object for a document-wide transaction."""
        class Transaction:
            def __init__(self, profile):
                self.__profile = profile

            def __enter__(self):
                self.__profile._profile_storage_system.enter_write_delay(self.__profile)
                for project in self.__profile.projects:
                    project.project_storage_system.enter_transaction()
                return self

            def __exit__(self, type, value, traceback):
                self.__profile._profile_storage_system.exit_write_delay(self.__profile)
                self.__profile._profile_storage_system.rewrite_item(self.__profile)
                for project in self.__profile.projects:
                    project.project_storage_system.exit_transaction()

        return Transaction(self)

    def restore_data_item(self, project: Project.Project, data_item_uuid: uuid.UUID) -> typing.Optional[DataItem.DataItem]:
        data_item = project.restore_data_item(data_item_uuid)
        if data_item:
            return data_item
        for project in self.__projects:
            data_item = project.restore_data_item(data_item_uuid)
            if data_item:
                return data_item
        return None

    def prune(self):
        for project in self.__projects:
            project.prune()

    def read_profile(self) -> None:
        # read the properties from the storage system
        properties = self.storage_system.read_properties()

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
            self.read_project(project_reference)

        # attempt to establish existing target project
        if self.target_project_reference_uuid:
            for project in self.__projects:
                if str(self.target_project_reference_uuid) == project.project_reference.get("uuid", None):
                    self.__target_project = project
                    break

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
                project_uuid = uuid.uuid4()
                project_data_json = json.dumps({"version": FileStorageSystem.PROJECT_VERSION, "uuid": str(project_uuid), "project_data_folders": [f"Work Data{suffix}"]})
                project_path.write_text(project_data_json, "utf-8")
                return {"type": "project_index", "uuid": str(project_uuid), "project_path": str(project_path)}

            project_path = self.storage_system.path
            work_project_reference = create_work_project_files(project_path)

            if work_project_reference:
                project = self.read_project(work_project_reference)
                if project:
                    self.add_project_reference(work_project_reference)
                    self.work_project_reference_uuid = uuid.UUID(work_project_reference["uuid"])
                    self.__work_project = project

        if not self.__work_project:
            logging.getLogger("loader").warning(f"Work project could not be loaded or created.")

    def create_project(self, project_dir: pathlib.Path, library_name: str) -> None:
        project_name = pathlib.Path(library_name)
        project_data_path = pathlib.Path(library_name + " Data")
        project_path = project_dir / project_name.with_suffix(".nsproj")
        project_dir.mkdir(parents=True, exist_ok=True)
        project_uuid = uuid.uuid4()
        project_data_json = json.dumps({"version": FileStorageSystem.PROJECT_VERSION, "uuid": str(project_uuid), "project_data_folders": [str(project_data_path)]})
        project_path.write_text(project_data_json, "utf-8")
        project_reference = {"type": "project_index", "uuid": str(project_uuid), "project_path": str(project_path)}
        project = self.read_project(project_reference)
        if project:
            self.add_project_reference(project_reference)

    def open_project(self, path: pathlib.Path) -> None:
        project_reference = None
        if path.suffix == ".nslib":
            project_reference = self.add_project_folder(pathlib.Path(path.parent))
        elif path.suffix == ".nsproj":
            project_reference = self.add_project_index(path)
        self.read_project(project_reference)

    def upgrade_project(self, project: Project) -> None:
        assert project in self.__projects
        if project.needs_upgrade:
            legacy_path = project.legacy_path
            target_project_path = legacy_path.with_suffix(".nsproj")
            target_data_path = legacy_path.parent / (str(legacy_path.stem) + " Data")
            logging.getLogger("loader").info(f"Created new project {target_project_path} {target_data_path}")
            target_project_uuid = uuid.uuid4()
            target_project_data_json = json.dumps({"version": FileStorageSystem.PROJECT_VERSION, "uuid": str(target_project_uuid), "project_data_folders": [str(target_data_path.stem)]})
            target_project_path.write_text(target_project_data_json, "utf-8")
            new_storage_system = FileStorageSystem.FileProjectStorageSystem(target_project_path)
            new_storage_system.load_properties()
            FileStorageSystem.migrate_to_latest(project.project_storage_system, new_storage_system)
            self.remove_project(project)
            self.read_project(self.add_project_index(target_project_path))

    def read_project(self, project_reference: typing.Dict) -> typing.Optional[Project.Project]:
        if project_reference:
            # note: project context is passed for use during testing
            project = Project.make_project(self.profile_context, project_reference)
            project_uuids = {project.uuid for project in self.projects}
            # do not allow multiple projects to load with same uuid
            if project and not project.uuid in project_uuids:
                project.prepare_read_project()
                self.__append_project(project)
                project.read_project()
            return project
        return None

    def remove_project(self, project: Project) -> None:
        if project in self.__projects and project != self.work_project:
            if project == self.__target_project:
                self.__target_project = None
                self.property_changed_event.fire("target_project")
            project.unmount()
            project_index = self.__projects.index(project)
            project_references = self.project_references
            project_references.pop(project_index)
            self._set_persistent_property_value("project_references", project_references)
            self.__projects.remove(project)
            project.project_uuid_str = None
            self.projects_model.value = copy.copy(self.__projects)
            self.project_removed_event.fire(project, project_index)

    def toggle_project_active(self, project: Project.Project) -> None:
        active_projects = self.active_projects
        if project in active_projects:
            active_projects.remove(project)
        else:
            active_projects.add(project)
        self.active_project_uuids = list(project.project_uuid_str for project in active_projects)

    @property
    def active_projects(self) -> typing.Set[Project.Project]:
        active_project_uuids = self.active_project_uuids
        active_projects = set()
        for project in self.__projects:
            if project.project_reference.get("uuid", None) in active_project_uuids:
                active_projects.add(project)
        return active_projects

    @property
    def project_filter(self) -> ListModel.Filter:

        def is_display_item_active(profile_weak_ref, display_item: DisplayItem.DisplayItem) -> bool:
            active_projects = profile_weak_ref().active_projects
            for project in active_projects:
                if display_item in project.display_items:
                    return True
            return False

        # use a weak reference to avoid circular references loops that prevent garbage collection
        return ListModel.PredicateFilter(functools.partial(is_display_item_active, weakref.ref(self)))

    @property
    def data_item_variables(self):
        return self._get_persistent_property_value("data_item_variables")

    @data_item_variables.setter
    def data_item_variables(self, value):
        self._set_persistent_property_value("data_item_variables", value)

    @property
    def data_item_references(self) -> typing.Dict[str, uuid.UUID]:
        return {k: v for k, v in self._get_persistent_property_value("data_item_references").items()}

    def set_data_item_reference(self, key: str, data_item: DataItem.DataItem) -> None:
        data_item_references = self.data_item_references
        data_item_references[key] = data_item.item_specifier.write()
        self._set_persistent_property_value("data_item_references", {k: v for k, v in data_item_references.items()})

    def clear_data_item_reference(self, key: str) -> None:
        data_item_references = self.data_item_references
        del data_item_references[key]
        self._set_persistent_property_value("data_item_references", {k: v for k, v in data_item_references.items()})

    def add_project_reference(self, project_reference: typing.Dict) -> None:
        assert "type" in project_reference
        assert "uuid" in project_reference
        project_references = self.project_references
        project_references.append(project_reference)
        self._set_persistent_property_value("project_references", project_references)
        active_project_uuid_strs = set(self.active_project_uuids)
        active_project_uuid_strs.add(project_reference["uuid"])
        self.active_project_uuids = list(active_project_uuid_strs)

    def add_project_index(self, project_path: pathlib.Path) -> typing.Dict:
        # add a project reference for the project index. does not create or add project.
        # must be called before read_projects, where project will be created.
        # note: this is an extra "read" of the project that might be avoid through revision of flow in the future
        storage_system = FileStorageSystem.FilePersistentStorageSystem(project_path)
        storage_system.load_properties()
        project_uuid_str = storage_system.get_storage_properties()["uuid"]
        project_reference = {"type": "project_index", "uuid": project_uuid_str, "project_path": str(project_path)}
        self.add_project_reference(project_reference)
        return project_reference

    def add_project_folder(self, project_path: pathlib.Path) -> typing.Dict:
        # add a project reference for the project folder. does not create or add project.
        # must be called before read_projects, where project will be created.
        project_reference = {"type": "project_folder", "uuid": str(uuid.uuid4()), "project_folder_path": str(project_path)}
        self.add_project_reference(project_reference)
        return project_reference

    def add_project_memory(self, project_uuid: uuid.UUID = None) -> typing.Dict:
        # add a project reference for a memory based project. does not create or add project.
        # must be called before read_projects, where project will be created.
        project_reference = {"type": "memory", "uuid": str(project_uuid or uuid.uuid4())}
        self.add_project_reference(project_reference)
        return project_reference

    def __append_project(self, project: Project.Project) -> None:
        self.update_item_context(project)
        project.about_to_be_inserted(self)
        project_index = len(self.__projects)
        self.__projects.append(project)
        self.projects_model.value = copy.copy(self.__projects)
        self.project_inserted_event.fire(project, project_index)


class MemoryProfileContext:
    # used for testing

    def __init__(self):
        self.storage_cache = Cache.DictStorageCache()

        self.profile_properties = dict()
        self.__storage_system = FileStorageSystem.MemoryPersistentStorageSystem(library_properties=self.profile_properties)
        self.__storage_system.load_properties()

        # these contain the data for each project.
        self.x_project_properties = dict()
        self.x_data_properties_map = dict()
        self.x_data_map = dict()
        self.x_trash_map = dict()

        # these contain the data for the first created project. they also facilitate legacy project testing.
        self.project_uuid = None
        self.project_properties = None
        self.data_properties_map = None
        self.data_map = None
        self.trash_map = None

        self._test_data_read_event = Event.Event()
        self.__profile = None

    def reset_profile(self):
        self.__profile = None
        self.profile_properties.clear()
        self.project_uuid = None
        self.project_properties = None
        self.data_properties_map = None
        self.data_map = None
        self.trash_map = None

    def create_legacy_project(self) -> None:
        """Create a legacy project."""
        self.project_uuid = uuid.uuid4()
        self.project_properties = self.x_project_properties[self.project_uuid] = {"uuid": str(self.project_uuid)}
        self.data_properties_map = self.x_data_properties_map[self.project_uuid] = dict()
        self.data_map = self.x_data_map[self.project_uuid] = dict()
        self.trash_map = self.x_trash_map[self.project_uuid] = dict()

    def create_profile(self) -> Profile:
        if not self.__profile:
            library_properties = {"version": FileStorageSystem.PROFILE_VERSION}
            storage_system = self.__storage_system
            storage_system.set_library_properties(library_properties)
            profile = Profile(storage_system=storage_system, storage_cache=self.storage_cache, auto_project=False)
            profile.storage_system = storage_system
            profile.profile_context = self
            self.project_uuid = uuid.UUID(profile.add_project_memory(self.project_uuid)["uuid"])
            profile.target_project_reference_uuid = self.project_uuid
            profile.work_project_reference_uuid = self.project_uuid
            self.__profile = profile
            return profile
        else:
            storage_system = self.__storage_system
            storage_system.load_properties()
            profile = Profile(storage_system=storage_system, storage_cache=self.storage_cache, auto_project=False)
            profile.storage_system = storage_system
            profile.profile_context = self
            return profile

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        pass
