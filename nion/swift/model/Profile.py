from __future__ import annotations

# standard libraries
import contextlib
import datetime
import gettext
import json
import logging
import os
import pathlib
import typing
import uuid

# local libraries
from nion.swift.model import Cache
from nion.swift.model import Changes
from nion.swift.model import DocumentModel
from nion.swift.model import FileStorageSystem
from nion.swift.model import Observer
from nion.swift.model import Persistence
from nion.swift.model import Project
from nion.utils import Converter
from nion.utils import Observable


_ = gettext.gettext


ProfileContext = typing.TypeVar("ProfileContext")


class ProjectReference(Observable.Observable, Persistence.PersistentObject):

    def __init__(self, type: str):
        super().__init__()
        self.define_type(type)
        self.define_property("project_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("last_used", None, converter=Converter.DatetimeToStringConverter())
        self.__has_project_info_been_read = False
        self.__project_version = None
        self.__project_state = "invalid"
        self.__document_model: typing.Optional[DocumentModel.DocumentModel] = None
        self.__document_model_about_to_close_listener = None
        self.storage_cache = None

    def close(self) -> None:
        if self.__document_model_about_to_close_listener:
            self.__document_model_about_to_close_listener.close()
            self.__document_model_about_to_close_listener = None
        super().close()

    def about_to_be_removed(self, container):
        self.unload_project()
        super().about_to_be_removed(container)

    def close_relationships(self) -> None:
        self.unload_project()
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

    def read_from_dict(self, properties):
        super().read_from_dict(properties)
        self.establish_last_used()

    def establish_last_used(self) -> None:
        if not self.last_used:
            self.last_used = self._get_last_used()

    def _get_last_used(self) -> datetime.datetime:
        # fallback when last_used is not initialized
        return self.modified

    def __property_changed(self, name, value):
        self.notify_property_changed(name)

    @property
    def project_version(self) -> typing.Optional[int]:
        return self.project.project_version if self.project else self.__project_version

    @property
    def project_state(self) -> str:
        return self.project.project_state if self.project else self.__project_state

    @property
    def project(self) -> typing.Optional[Project.Project]:
        return self.__document_model._project if self.__document_model else None

    @property
    def document_model(self) -> typing.Optional[DocumentModel.DocumentModel]:
        return self.__document_model

    @property
    def title(self) -> str:
        if self.project and self.project.title:
            return self.project.title
        project_reference_parts = self.project_reference_parts
        if project_reference_parts:
            return pathlib.Path(project_reference_parts[-1]).stem
        return _("Untited")

    @property
    def project_reference_parts(self) -> typing.Tuple[str]:
        raise NotImplementedError()

    def make_storage(self, profile_context: typing.Optional[ProfileContext]) -> typing.Optional[FileStorageSystem.ProjectStorageSystem]:
        raise NotImplementedError()

    def read_project_info(self, profile_context: typing.Optional[ProfileContext]) -> None:
        if not self.__has_project_info_been_read:
            try:
                project_storage_system = self.make_storage(profile_context)
            except Exception:
                project_storage_system = None
            if project_storage_system:
                project_storage_system.load_properties()
                with contextlib.closing(Project.Project(project_storage_system)) as project:
                    if self.project_uuid != project.project_uuid:
                        self.project_uuid = project.project_uuid
                    self.__project_version = project.project_version
                    self.__project_state = project.project_state
                    self.__has_project_info_been_read = True

    def load_project(self, profile_context: typing.Optional[ProfileContext]) -> None:
        """Read project.

        The profile context is used during testing.
        """
        if not self.project:  # the project from the document model
            project: typing.Optional[Project.Project] = None

            # create project if it doesn't exist
            project_storage_system = self.make_storage(profile_context)
            if project_storage_system:
                project_storage_system.load_properties()
                project = Project.Project(project_storage_system)

            if project:
                self.__document_model = DocumentModel.DocumentModel(project, storage_cache=self.storage_cache)

                # handle special case of document model closing during tests
                def document_window_close():
                    self.__document_model_about_to_close_listener.close()
                    self.__document_model_about_to_close_listener = None
                    self.__document_model = None

                self.project.prepare_read_project()  # sets up the uuid, used next.

                self.update_item_context(self.project)
                self.project.about_to_be_inserted(self)
                self.notify_property_changed("project")  # before reading, so document model has a chance to set up
                self.project.read_project()

                self.__document_model_about_to_close_listener = self.__document_model.about_to_close_event.listen(document_window_close)
            else:
                logging.getLogger("loader").warning(f"Project could not be loaded {self}.")

    def unload_project(self) -> None:
        """Unload project (high level, notify that project changed)."""
        if self.project:
            self.project.unmount()
            self.project.about_to_be_removed(self)
            self.project.persistent_object_context = None
            self.__document_model.close()
            self.__document_model = None
            self.notify_property_changed("project")

    def read_project_uuid(self, profile_context: typing.Optional[ProfileContext] = None) -> typing.Optional[uuid.UUID]:
        """Read the project UUID without loading entire project."""
        project_storage_system = self.make_storage(profile_context)
        if project_storage_system:
            project_storage_system.load_properties()
            with contextlib.closing(Project.Project(project_storage_system)) as project:
                project.prepare_read_project()  # sets up the uuid, used next.
                return project.uuid
        return None

    def upgrade(self, profile_context: typing.Optional[ProfileContext] = None) -> typing.Optional[ProjectReference]:
        if self.project_state == "needs_upgrade":
            project_storage_system = self.make_storage(profile_context)
            if project_storage_system:
                return self._upgrade_project_storage_system(project_storage_system)
        return None

    def _upgrade_project_storage_system(self, project_storage_system: FileStorageSystem.ProjectStorageSystem) -> ProjectReference:
        raise NotImplementedError()


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

    def _get_last_used(self) -> datetime.datetime:
        # fallback when last_used is not initialized
        try:
            return datetime.datetime.fromtimestamp(os.path.getmtime(self.project_path))
        except Exception:
            return super()._get_last_used()


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

    def _get_last_used(self) -> datetime.datetime:
        # fallback when last_used is not initialized
        try:
            return datetime.datetime.fromtimestamp(os.path.getmtime(self.project_folder_path))
        except Exception:
            return super()._get_last_used()

    def _upgrade_project_storage_system(self, project_storage_system: FileStorageSystem.ProjectStorageSystem) -> ProjectReference:
        legacy_path = pathlib.Path(project_storage_system.get_identifier())
        target_project_path = legacy_path.parent.with_suffix(".nsproj")
        target_data_path = target_project_path.with_name(target_project_path.stem + " Data")
        if target_project_path.exists() or target_data_path.exists():
            raise FileExistsError()
        logging.getLogger("loader").info(f"Created new project {target_project_path} {target_data_path}")
        target_project_uuid = uuid.uuid4()
        target_project_data_json = json.dumps(
            {"version": FileStorageSystem.PROJECT_VERSION, "uuid": str(target_project_uuid),
             "project_data_folders": [str(target_data_path.stem)]})
        target_project_path.write_text(target_project_data_json, "utf-8")
        with contextlib.closing(FileStorageSystem.FileProjectStorageSystem(target_project_path)) as new_storage_system:
            new_storage_system.load_properties()
            FileStorageSystem.migrate_to_latest(project_storage_system, new_storage_system)
        new_project_reference = IndexProjectReference()
        new_project_reference.project_path = target_project_path
        new_project_reference.project_uuid = target_project_uuid
        return new_project_reference


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
    count = 0  # useful for detecting leaks in tests

    def __init__(self, storage_system=None, storage_cache=None, *, profile_context: typing.Optional[ProfileContext] = None):
        super().__init__()
        self.__class__.count += 1

        self.define_root_context()
        self.define_type("profile")
        self.define_relationship("project_references", project_reference_factory, insert=self.__insert_project_reference, remove=self.__remove_project_reference)
        self.define_property("last_project_reference", converter=Converter.UuidToStringConverter())
        self.define_property("work_project_reference_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("closed_items", list())

        self.storage_system = storage_system or FileStorageSystem.MemoryPersistentStorageSystem()
        self.storage_system.load_properties()

        self.storage_cache = storage_cache or Cache.DictStorageCache()  # need to deallocate
        self.set_storage_system(self.storage_system)

        self.profile_context = None

        # helper object to produce the projects sequence
        oo = Observer.ObserverBuilder()
        oo.source(self).ordered_sequence_from_array("project_references").map(oo.x.prop("project")).filter(lambda x: x is not None).trampoline(self, "projects")
        self.__projects_observer = oo.make_observable()

        if profile_context:
            self.profile_context = profile_context
            self.add_project_memory()

    def close(self) -> None:
        self.storage_cache.close()
        self.storage_cache = None
        self.storage_system.close()
        self.storage_system = None
        self.__projects_observer.close()
        self.__projects_observer = None
        self.profile_context = None
        self.__class__.count -= 1
        super().close()

    def read_from_dict(self, properties):
        # cleanup from beta versions
        properties.pop("data_groups", None)
        properties.pop("data_item_references", None)
        properties.pop("data_item_variables", None)
        properties.pop("project_uuid", None)
        properties.pop("target_project_reference_uuid", None)
        properties.pop("workspace_uuid", None)
        properties.pop("workspaces", None)
        super().read_from_dict(properties)

    def __property_changed(self, name, value):
        self.notify_property_changed(name)

    def __insert_project_reference(self, name: str, before_index: int, project_reference: ProjectReference) -> None:
        project_reference.storage_cache = self.storage_cache
        project_reference.read_project_info(self.profile_context)
        self.notify_insert_item("project_references", project_reference, before_index)

    def __remove_project_reference(self, name: str, index: int, project_reference: ProjectReference) -> None:
        project_reference.storage_cache = None
        self.notify_remove_item("project_references", project_reference, index)

    @property
    def projects(self) -> typing.List[Project.Project]:
        return typing.cast(typing.List[Project.Project], self.__projects_observer.item)

    @property
    def _profile_storage_system(self) -> FileStorageSystem.PersistentStorageSystem:
        return self.storage_system

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

    def read_project(self, project_reference: ProjectReference) -> None:
        project_reference.load_project(self.profile_context)

    def create_project(self, project_dir: pathlib.Path, library_name: str) -> typing.Optional[ProjectReference]:
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
        return project_reference

    def open_project(self, path: pathlib.Path) -> typing.Optional[ProjectReference]:
        if path.suffix == ".nslib":
            return self.add_project_folder(pathlib.Path(path.parent), load=False)
        elif path.suffix == ".nsproj":
            return self.add_project_index(path, load=False)
        return None

    def get_project_reference(self, uuid_: uuid.UUID) -> typing.Optional[ProjectReference]:
        for project_reference in self.project_references:
            if project_reference.uuid == uuid_:
                return project_reference
        return None

    def append_project_reference(self, project_reference: ProjectReference) -> None:
        assert not self.get_item_by_uuid("project_references", project_reference.uuid)
        assert not project_reference.project_uuid in {project_reference.project_uuid for project_reference in self.project_references}
        self.append_item("project_references", project_reference)

    def remove_project_reference(self, project_reference: ProjectReference) -> None:
        assert project_reference.project_state != "loaded"
        project_reference.unload_project()
        self.remove_item("project_references", project_reference)

    def add_project_reference(self, project_reference: ProjectReference, load: bool = True) -> ProjectReference:
        # add the project reference if a project reference with the same project uuid
        # is not already present; otherwise activate the existing one.
        existing_project_reference = next(filter(lambda x: x.project_uuid == project_reference.project_uuid, self.project_references), None)
        if not existing_project_reference:
            self.append_project_reference(project_reference)
            if load:
                self.read_project(project_reference)
            return project_reference
        else:
            if load:
                existing_project_reference.load_project(self.profile_context)
            return existing_project_reference

    def add_project_index(self, project_path: pathlib.Path, load: bool = True) -> ProjectReference:
        project_reference = IndexProjectReference()
        project_reference.project_path = project_path
        project_reference.project_uuid = project_reference.read_project_uuid(self.profile_context)
        project_reference.establish_last_used()
        return self.add_project_reference(project_reference, load)

    def add_project_folder(self, project_folder_path: pathlib.Path, load: bool = True) -> ProjectReference:
        project_reference = FolderProjectReference()
        project_reference.project_folder_path = project_folder_path
        project_reference.project_uuid = project_reference.read_project_uuid(self.profile_context)
        project_reference.establish_last_used()
        return self.add_project_reference(project_reference, load)

    def add_project_memory(self, _uuid: uuid.UUID = None, load: bool = True) -> ProjectReference:
        assert callable(project_reference_factory_hook)
        project_reference = project_reference_factory_hook("project_memory")
        project_reference.project_uuid = _uuid or uuid.uuid4()
        project_reference.establish_last_used()
        return self.add_project_reference(project_reference, load)

    def upgrade(self, project_reference: ProjectReference) -> typing.Optional[ProjectReference]:
        new_project_reference = project_reference.upgrade(self.profile_context)
        if new_project_reference:
            self.remove_project_reference(project_reference)
            return self.add_project_reference(new_project_reference, load=False)
        return None
