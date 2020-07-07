# standard libraries
import contextlib
import datetime
import gettext
import json
import logging
import pathlib
import typing
import uuid

# local libraries
from nion.swift.model import Cache
from nion.swift.model import Changes
from nion.swift.model import Connection
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayItem
from nion.swift.model import FileStorageSystem
from nion.swift.model import Observer
from nion.swift.model import Persistence
from nion.swift.model import Project
from nion.swift.model import Symbolic
from nion.swift.model import WorkspaceLayout
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Observable

if typing.TYPE_CHECKING:
    from nion.swift.model import DocumentModel


_ = gettext.gettext


ProfileContext = typing.TypeVar("ProfileContext")


class ProjectReference(Observable.Observable, Persistence.PersistentObject):

    def __init__(self, type: str):
        super().__init__()
        self.define_type(type)
        self.define_property("project_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("is_active", False, changed=self.__property_changed)
        self.__project: typing.Optional[Project.Project] = None

    def open(self) -> None:
        if self.__project:
            self.__project.open()

    def read_from_dict(self, properties: typing.Mapping) -> None:
        super().read_from_dict(properties)
        # copy this uuid to the project uuid for backwards compatibility.
        # this is only needed for the beta version.
        if self.project_uuid is None:
            self.project_uuid = self.uuid

    def about_to_be_removed(self, container):
        self.__unmount_project()
        super().about_to_be_removed(container)

    def close_relationships(self) -> None:
        self.__unmount_project()
        super().close_relationships()

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

    def __property_changed(self, name, value):
        self.notify_property_changed(name)

    @property
    def project(self) -> typing.Optional[Project.Project]:
        return self.__project

    @property
    def title(self) -> str:
        if self.__project and self.__project.title:
            return self.__project.title
        project_reference_parts = self.project_reference_parts
        if project_reference_parts:
            return pathlib.Path(project_reference_parts[-1]).stem
        return _("Untited")

    @property
    def project_reference_parts(self) -> typing.Tuple[str]:
        raise NotImplementedError()

    def make_storage(self, profile_context: typing.Optional[ProfileContext]) -> typing.Optional[FileStorageSystem.ProjectStorageSystem]:
        raise NotImplementedError()

    def load_project(self, existing_projects: typing.Sequence[Project.Project], profile_context: typing.Optional[ProfileContext]) -> None:
        """Make this project active and read it if it isn't already active."""
        if not self.is_active:
            self.is_active = True
            self.read_project(existing_projects, profile_context)

    def unload_project(self) -> None:
        """Make this project inactive."""
        if self.is_active and self.__project:
            self.is_active = False
            self.__unmount_project()
            self.notify_property_changed("project")

    def __unmount_project(self):
        if self.__project:
            self.__project.unmount()
            self.__project.about_to_be_removed(self)
            self.__project.persistent_object_context = None
            self.__project.close()
            self.__project = None

    def read_project(self, existing_projects: typing.Sequence[Project.Project], profile_context: typing.Optional[ProfileContext] = None) -> None:
        """Read the project if it is active.

        The profile context is used during testing.
        """
        assert not self.__project
        if self.is_active:
            project_storage_system = self.make_storage(profile_context)
            if project_storage_system:
                project_storage_system.load_properties()
                self.__project = Project.Project(project_storage_system)
            else:
                logging.getLogger("loader").warning(f"Project could not be loaded {self}.")
            # do not allow multiple projects to load with same uuid
            existing_project_uuids = {project.uuid for project in existing_projects}
            if self.__project:
                self.__project.prepare_read_project()  # sets up the uuid, used next.
                if not self.__project.uuid in existing_project_uuids and self.__project.uuid == self.project_uuid:
                    self.update_item_context(self.__project)
                    self.__project.about_to_be_inserted(self)
                    self.notify_property_changed("project")  # before reading, so document model has a chance to set up
                    self.__project.read_project()
                else:
                    self.__project.close()
                    self.__project = None

    def read_project_uuid(self, profile_context: typing.Optional[ProfileContext] = None) -> typing.Optional[uuid.UUID]:
        project_storage_system = self.make_storage(profile_context)
        if project_storage_system:
            project_storage_system.load_properties()
            with contextlib.closing(Project.Project(project_storage_system)) as project:
                project.prepare_read_project()  # sets up the uuid, used next.
                return project.uuid
        return None



class IndexProjectReference(ProjectReference):
    type = "project_index"

    def __init__(self):
        super().__init__(self.__class__.type)
        self.define_property("project_path", converter=Converter.PathToStringConverter())

    @property
    def project_reference_parts(self) -> typing.Tuple[str]:
        return self.project_path.parts if self.project_path else tuple()

    def make_storage(self, profile_context: typing.Optional[ProfileContext]) -> typing.Optional[FileStorageSystem.ProjectStorageSystem]:
        return FileStorageSystem.make_index_project_storage_system(self.project_path)


class FolderProjectReference(ProjectReference):
    type = "project_folder"

    def __init__(self):
        super().__init__(self.__class__.type)
        self.define_property("project_folder_path", converter=Converter.PathToStringConverter())

    @property
    def project_reference_parts(self) -> typing.Tuple[str]:
        return self.project_folder_path.parts if self.project_folder_path else tuple()

    def make_storage(self, profile_context: typing.Optional[ProfileContext]) -> typing.Optional[FileStorageSystem.ProjectStorageSystem]:
        if self.project_folder_path:
            return FileStorageSystem.make_folder_project_storage_system(self.project_folder_path)
        return None


project_reference_factory_hook = None

def project_reference_factory(lookup_id: typing.Callable[[str], str]) -> typing.Optional[ProjectReference]:
    type = lookup_id("type")
    if type == IndexProjectReference.type:
        return IndexProjectReference()
    if type == FolderProjectReference.type:
        return FolderProjectReference()
    if callable(project_reference_factory_hook):
        return project_reference_factory_hook(type)
    return None


class Profile(Observable.Observable, Persistence.PersistentObject):

    def __init__(self, storage_system=None, storage_cache=None, *, profile_context: typing.Optional[ProfileContext] = None):
        super().__init__()

        self.define_root_context()
        self.define_type("profile")
        self.define_relationship("workspaces", WorkspaceLayout.factory)
        self.define_relationship("data_groups", DataGroup.data_group_factory)
        self.define_relationship("project_references", project_reference_factory, insert=self.__insert_project_reference, remove=self.__remove_project_reference)
        self.define_property("workspace_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("data_item_references", dict(), hidden=True)  # map string key to data item, used for data acquisition channels
        self.define_property("data_item_variables", dict(), hidden=True)  # map string key to data item, used for reference in scripts
        self.define_property("target_project_reference_uuid", converter=Converter.UuidToStringConverter(), changed=self.__property_changed)
        self.define_property("work_project_reference_uuid", converter=Converter.UuidToStringConverter(), changed=self.__property_changed)
        self.define_property("closed_items", list())

        self.storage_system = storage_system or FileStorageSystem.MemoryPersistentStorageSystem()
        self.storage_system.load_properties()

        self.__work_project_reference : typing.Optional[ProjectReference] = None
        self.__target_project_reference : typing.Optional[ProjectReference] = None

        self.storage_cache = storage_cache or Cache.DictStorageCache()  # need to deallocate
        self.set_storage_system(self.storage_system)

        self.profile_context = None

        # helper object to produce the projects sequence
        oo = Observer.ObserverBuilder()
        oo.source(self).ordered_sequence_from_array("project_references").map(oo.x.prop("project")).filter(lambda x: x is not None).trampoline(self, "projects")
        self.__projects_observer = oo.make_observable()

        self.__is_read = False

        if profile_context:
            self.profile_context = profile_context
            project_reference = self.add_project_memory()
            self.work_project_reference_uuid = project_reference.uuid
            self.target_project_reference_uuid = project_reference.uuid

    def close(self) -> None:
        self.storage_cache.close()
        self.storage_cache = None
        self.storage_system.close()
        self.storage_system = None
        self.__projects_observer.close()
        self.__projects_observer = None
        self.profile_context = None
        super().close()

    def __property_changed(self, name, value):
        self.notify_property_changed(name)

    def __insert_project_reference(self, name: str, before_index: int, project_reference: ProjectReference) -> None:
        self.notify_insert_item("project_references", project_reference, before_index)

    def __remove_project_reference(self, name: str, index: int, project_reference: ProjectReference) -> None:
        self.notify_remove_item("project_references", project_reference, index)

    @property
    def projects(self) -> typing.List[Project.Project]:
        return typing.cast(typing.List[Project.Project], self.__projects_observer.item)

    @property
    def _profile_storage_system(self) -> FileStorageSystem.PersistentStorageSystem:
        return self.storage_system

    @property
    def target_project(self) -> typing.Optional[Project.Project]:
        return self.__target_project_reference.project if self.__target_project_reference else None

    @property
    def target_project_reference(self) -> typing.Optional[ProjectReference]:
        return self.__target_project_reference

    @property
    def work_project(self) -> typing.Optional[Project.Project]:
        return self.__work_project_reference.project

    @property
    def work_project_reference(self) -> typing.Optional[ProjectReference]:
        return self.__work_project_reference

    def set_target_project_reference(self, project_reference: typing.Optional[ProjectReference]) -> None:
        if project_reference != self.__target_project_reference:
            self.target_project_reference_uuid = project_reference.uuid if project_reference else None
            self.__target_project_reference = project_reference
            self.property_changed_event.fire("target_project")

    def set_work_project_reference(self, project_reference: ProjectReference) -> None:
        if project_reference != self.__work_project_reference:
            work_project = self.__work_project_reference.project
            if work_project and any(data_item.is_live for data_item in work_project.data_items):
                raise Exception("Work project contains live items.")
            if work_project and any(display_item.is_live for display_item in work_project.display_items):
                raise Exception("Work project contains live items.")
            self.work_project_reference_uuid = project_reference.uuid
            self.__work_project_reference = project_reference
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

    def open(self, document_model: "DocumentModel.DocumentModel"):
        # this makes storage reusable during tests
        for project_reference in self.project_references:
            project_reference.open()

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
        for project in self.projects:
            data_item = project.restore_data_item(data_item_uuid)
            if data_item:
                return data_item
        return None

    def prune(self):
        for project in self.projects:
            project.prune()

    def read_from_dict(self, properties: typing.Mapping) -> None:
        super().read_from_dict(properties)
        # activate the project uuids. needed for backwards compatibility during beta only.
        for project_reference_uuid_str in typing.cast(typing.MutableMapping, properties).pop("active_project_uuids", list()):
            project_reference_uuid = uuid.UUID(project_reference_uuid_str)
            for project_reference in self.project_references:
                if project_reference.uuid == project_reference_uuid:
                    project_reference.is_active = True

    def read_profile(self) -> None:
        # read the properties from the storage system. called after open.
        properties = self.storage_system.read_properties()

        # if the properties match the current version, read the properties.
        if properties.get("version", 0) == FileStorageSystem.PROFILE_VERSION:
            self.begin_reading()
            try:
                if not self.project_references:  # hack for testing. tests will have already set up profile.
                    self.read_from_dict(properties)
            finally:
                self.finish_reading()
            self.storage_system.set_property(self, "uuid", str(self.uuid))
            self.storage_system.set_property(self, "version", FileStorageSystem.PROFILE_VERSION)

        # create project objects for each project reference
        for project_reference in self.project_references:
            project_reference.read_project(self.projects, self.profile_context)

        # attempt to establish existing target project
        if self.target_project_reference_uuid:
            for project_reference in self.project_references:
                if project_reference.uuid == self.target_project_reference_uuid:
                    self.__target_project_reference = project_reference
                    break

        # attempt to establish existing work project
        if self.work_project_reference_uuid:
            for project_reference in self.project_references:
                if project_reference.uuid == self.work_project_reference_uuid:
                    self.__work_project_reference = project_reference
                    break

        # if existing one cannot be found, attempt to create one
        if not self.__work_project_reference:
            project_path = self.storage_system.path
            project_path = project_path.parent / "Work.nsproj"
            suffix = str()
            if project_path.exists():
                suffix = f" {datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
                project_path = project_path.parent / f"Work{suffix}.nsproj"
            logging.getLogger("loader").warning(f"Created work project {project_path.parent / project_path.stem}")
            project_uuid = uuid.uuid4()
            project_data_json = json.dumps({"version": FileStorageSystem.PROJECT_VERSION, "uuid": str(project_uuid), "project_data_folders": [f"Work Data{suffix}"]})
            project_path.write_text(project_data_json, "utf-8")
            project_reference = IndexProjectReference()
            project_reference.project_path = project_path
            project_reference.project_uuid = project_uuid
            self.append_project_reference(project_reference)
            project_reference.load_project(self.projects, self.profile_context)
            self.work_project_reference_uuid = project_reference.uuid
            self.__work_project_reference = project_reference

        self.__is_read = True

        if not self.__work_project_reference:
            logging.getLogger("loader").warning(f"Work project could not be loaded or created.")

    def create_project(self, project_dir: pathlib.Path, library_name: str) -> None:
        project_name = pathlib.Path(library_name)
        project_data_path = pathlib.Path(library_name + " Data")
        project_path = project_dir / project_name.with_suffix(".nsproj")
        project_dir.mkdir(parents=True, exist_ok=True)
        project_uuid = uuid.uuid4()
        project_data_json = json.dumps({"version": FileStorageSystem.PROJECT_VERSION, "uuid": str(project_uuid), "project_data_folders": [str(project_data_path)]})
        project_path.write_text(project_data_json, "utf-8")
        project_reference = IndexProjectReference()
        project_reference.project_path = project_path
        project_reference.project_uuid = project_uuid
        self.append_project_reference(project_reference)
        project_reference.load_project(self.projects, self.profile_context)

    def open_project(self, path: pathlib.Path) -> None:
        if path.suffix == ".nslib":
            self.add_project_folder(pathlib.Path(path.parent))
        elif path.suffix == ".nsproj":
            self.add_project_index(path)

    def upgrade_project(self, project: Project) -> None:
        assert False
        assert project in self.projects
        if project.needs_upgrade:
            legacy_path = project.storage_system_path.parent
            target_project_path = legacy_path.with_suffix(".nsproj")
            target_data_path = legacy_path.parent / (str(legacy_path.stem) + " Data")
            logging.getLogger("loader").info(f"Created new project {target_project_path} {target_data_path}")
            target_project_uuid = uuid.uuid4()
            target_project_data_json = json.dumps({"version": FileStorageSystem.PROJECT_VERSION, "uuid": str(target_project_uuid), "project_data_folders": [str(target_data_path.stem)]})
            target_project_path.write_text(target_project_data_json, "utf-8")
            with contextlib.closing(FileStorageSystem.FileProjectStorageSystem(target_project_path)) as new_storage_system:
                new_storage_system.load_properties()
                FileStorageSystem.migrate_to_latest(project.project_storage_system, new_storage_system)
            self.remove_project_reference(project)
            self.read_project(self.add_project_index(target_project_path))

    def set_project_reference_active(self, project_reference: ProjectReference, active: bool) -> None:
        if active:
            project_reference.load_project(self.projects, self.profile_context)
        else:
            project_reference.unload_project()

    def toggle_project_reference_active(self, project_reference: ProjectReference) -> None:
        self.set_project_reference_active(project_reference, not project_reference.is_active)

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

    def append_project_reference(self, project_reference: ProjectReference) -> None:
        assert not self.get_item_by_uuid("project_references", project_reference.uuid)
        assert not project_reference.project_uuid in {project_reference.project_uuid for project_reference in self.project_references}
        self.append_item("project_references", project_reference)

    def unload_project_reference(self, project_reference: ProjectReference) -> None:
        if project_reference.project != self.work_project:
            if project_reference == self.__target_project_reference:
                self.__target_project_reference = None
                self.property_changed_event.fire("target_project")
            project_reference.unload_project()

    def remove_project_reference(self, project_reference: ProjectReference) -> None:
        if project_reference.project != self.work_project:
            if project_reference == self.__target_project_reference:
                self.__target_project_reference = None
                self.property_changed_event.fire("target_project")
            project_reference.unload_project()
            self.remove_item("project_references", project_reference)

    def add_project_reference(self, project_reference: ProjectReference, load: bool = True) -> ProjectReference:
        # add the project reference if a project reference with the same project uuid
        # is not already present; otherwise activate the existing one.
        existing_project_reference = next(filter(lambda x: x.project_uuid == project_reference.project_uuid, self.project_references), None)
        if not existing_project_reference:
            self.append_project_reference(project_reference)
            if load:
                if self.__is_read:
                    self.set_project_reference_active(project_reference, True)
                else:
                    project_reference.is_active = True
            return project_reference
        else:
            if load:
                existing_project_reference.load_project(self.projects, self.profile_context)
            return existing_project_reference

    def add_project_index(self, project_path: pathlib.Path, load: bool = True) -> ProjectReference:
        project_reference = IndexProjectReference()
        project_reference.project_path = project_path
        project_reference.project_uuid = project_reference.read_project_uuid(self.profile_context)
        return self.add_project_reference(project_reference, load)

    def add_project_folder(self, project_folder_path: pathlib.Path, load: bool = True) -> ProjectReference:
        project_reference = FolderProjectReference()
        project_reference.project_folder_path = project_folder_path
        project_reference.project_uuid = project_reference.read_project_uuid(self.profile_context)
        return self.add_project_reference(project_reference, load)
