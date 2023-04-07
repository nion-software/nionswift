from __future__ import annotations

# standard libraries
import contextlib
import datetime
import gettext
import json
import logging
import os
import pathlib
import types
import typing
import uuid

# local libraries
from nion.swift.model import Cache
from nion.swift.model import Changes
from nion.swift.model import DocumentModel
from nion.swift.model import FileStorageSystem
from nion.swift.model import Model
from nion.swift.model import Observer
from nion.swift.model import Persistence
from nion.swift.model import Project
from nion.swift.model import Schema
from nion.utils import Converter

_ = gettext.gettext

ProfileContext = typing.TypeVar("ProfileContext")


class ProjectReference(Persistence.PersistentObject):

    def __init__(self, type: str) -> None:
        super().__init__()
        self.define_type(type)
        self.define_property("project_uuid", converter=Converter.UuidToStringConverter(), hidden=True)
        self.define_property("last_used", None, converter=Converter.DatetimeToStringConverter(), hidden=True)
        self.__has_project_info_been_read = False
        self.__project_version: typing.Optional[int] = None
        self.__project_state = "invalid"
        self.__document_model: typing.Optional[DocumentModel.DocumentModel] = None

    @property
    def project_uuid(self) -> typing.Optional[uuid.UUID]:
        return typing.cast(typing.Optional[uuid.UUID], self._get_persistent_property_value("project_uuid"))

    @project_uuid.setter
    def project_uuid(self, value: typing.Optional[uuid.UUID]) -> None:
        self._set_persistent_property_value("project_uuid", value)

    @property
    def is_valid(self) -> bool:
        return False

    @property
    def last_used(self) -> typing.Optional[datetime.datetime]:
        return typing.cast(typing.Optional[datetime.datetime], self._get_persistent_property_value("last_used"))

    @last_used.setter
    def last_used(self, value: typing.Optional[datetime.datetime]) -> None:
        self._set_persistent_property_value("last_used", value)

    @property
    def recents_key(self) -> typing.Tuple[bool, typing.Optional[datetime.datetime]]:
        # intended to be used as a key for sorting recents. the first value is a boolean indicating whether the project
        # is loaded. the second value is the last used date. the sort should be reversed.
        return self.project_state == "unloaded", self.last_used or self.modified

    def about_to_be_removed(self, container: Persistence.PersistentObject) -> None:
        self.unload_project()
        super().about_to_be_removed(container)

    def close_relationships(self) -> None:
        self.unload_project()
        super().close_relationships()

    def read_from_dict(self, properties: Persistence.PersistentDictType) -> None:
        super().read_from_dict(properties)
        self.establish_last_used()

    def establish_last_used(self) -> None:
        if self.last_used is None:
            self.last_used = self._get_last_used()

    def _get_last_used(self) -> datetime.datetime:
        # fallback when last_used is not initialized
        return self.modified

    def __property_changed(self, name: str, value: typing.Any) -> None:
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
    def path(self) -> pathlib.Path:
        project_reference_parts = self.project_reference_parts
        if project_reference_parts:
            return pathlib.Path(*project_reference_parts)
        return pathlib.Path()

    @property
    def project_reference_parts(self) -> typing.Sequence[str]:
        raise NotImplementedError()

    def make_storage(self, profile_context: typing.Optional[ProfileContext]) -> typing.Optional[Persistence.PersistentStorageInterface]:
        raise NotImplementedError()

    def read_project_info(self, profile_context: typing.Optional[ProfileContext]) -> None:
        if not self.__has_project_info_been_read:
            try:
                project_storage_system = self.make_storage(profile_context)
                if project_storage_system:
                    project_storage_system.load_properties()
                # handle the case where the project storage system is never read; the folder project case.
                # this will get set again below if the project is read.
                self.__project_state = "missing"
            except Exception:
                project_storage_system = None
            # note: the project state can be set two different ways, depending on whether the project is an index file
            # or folder based project. in the former, the project state is set by the project itself. in the latter,
            # the project state is set by the profile.
            if project_storage_system:
                with contextlib.closing(Project.Project(project_storage_system)) as project:
                    if self.project_uuid != project.project_uuid:
                        self.project_uuid = project.project_uuid
                    self.__project_version = project.project_version
                    self.__project_state = project.project_state
            self.__has_project_info_been_read = True

    def load_project(self, profile_context: typing.Optional[ProfileContext], cache_dir_path: typing.Optional[pathlib.Path], *, cache_factory: typing.Optional[Cache.CacheFactory]) -> None:
        """Read project.

        The profile context is used during testing.
        """
        if not self.project:  # the project from the document model
            project: typing.Optional[Project.Project] = None

            # create project if it doesn't exist
            project_storage_system = self.make_storage(profile_context)
            if project_storage_system:
                project_storage_system.load_properties()
                if not cache_factory:
                    assert cache_dir_path

                    def encode(uuid_: uuid.UUID, alphabet: str) -> str:
                        result = str()
                        uuid_int = uuid_.int
                        while uuid_int:
                            uuid_int, digit = divmod(uuid_int, len(alphabet))
                            result += alphabet[digit]
                        return result

                    encoded_base_path = "proj_" + encode(self.project_uuid or self.uuid, "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")  # 25 character results
                    cache_factory = Cache.DbCacheFactory(cache_dir_path, str(encoded_base_path))
                project = Project.Project(project_storage_system, cache_factory)

            if project:
                self.__document_model = DocumentModel.DocumentModel(project)

                project.prepare_read_project()  # sets up the uuid, used next.

                self.update_item_context(project)
                project.about_to_be_inserted(self)
                self.notify_property_changed("project")  # before reading, so document model has a chance to set up
                project.read_project()
            else:
                logging.getLogger("loader").warning(f"Project could not be loaded {self}.")

    def unload_project(self) -> None:
        """Unload project (high level, notify that project changed)."""
        if self.project:
            self.project.unmount()
            self.project.about_to_be_removed(self)
            self.project.persistent_object_context = typing.cast(Persistence.PersistentObjectContext, None)
            assert self.__document_model
            # add/remove ref in case it was never added anywhere else. this will delete it.
            with self.__document_model.ref():
                pass
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

    def _upgrade_project_storage_system(self, project_storage_system: Persistence.PersistentStorageInterface) -> ProjectReference:
        raise NotImplementedError()


class IndexProjectReference(ProjectReference):
    type = "project_index"

    def __init__(self) -> None:
        super().__init__(self.__class__.type)
        self.define_property("project_path", converter=Converter.PathToStringConverter(), hidden=True)

    @property
    def is_valid(self) -> bool:
        project_path = self.project_path
        return project_path is not None and project_path.exists()

    @property
    def project_path(self) -> typing.Optional[pathlib.Path]:
        return typing.cast(typing.Optional[pathlib.Path], self._get_persistent_property_value("project_path"))

    @project_path.setter
    def project_path(self, value: typing.Optional[pathlib.Path]) -> None:
        self._set_persistent_property_value("project_path", value)

    @property
    def project_reference_parts(self) -> typing.Sequence[str]:
        project_path = self.project_path
        return project_path.parts if project_path else tuple()

    def make_storage(self, profile_context: typing.Optional[ProfileContext]) -> typing.Optional[Persistence.PersistentStorageInterface]:
        project_path = self.project_path
        if project_path:
            return FileStorageSystem.make_index_project_storage_system(project_path)
        return None

    def _get_last_used(self) -> datetime.datetime:
        # fallback when last_used is not initialized
        try:
            project_path = self.project_path
            if project_path:
                return datetime.datetime.fromtimestamp(os.path.getmtime(project_path))
            else:
                return super()._get_last_used()
        except Exception:
            return super()._get_last_used()


class FolderProjectReference(ProjectReference):
    type = "project_folder"

    def __init__(self) -> None:
        super().__init__(self.__class__.type)
        self.define_property("project_folder_path", converter=Converter.PathToStringConverter(), hidden=True)

    @property
    def is_valid(self) -> bool:
        project_folder_path = self.project_folder_path
        if project_folder_path:
            for project_file, project_dir in FileStorageSystem.FileProjectStorageSystem._get_migration_paths(project_folder_path):
                if project_file.exists():
                    return True
        return False

    @property
    def project_folder_path(self) -> typing.Optional[pathlib.Path]:
        return typing.cast(typing.Optional[pathlib.Path], self._get_persistent_property_value("project_folder_path"))

    @project_folder_path.setter
    def project_folder_path(self, value: typing.Optional[pathlib.Path]) -> None:
        self._set_persistent_property_value("project_folder_path", value)

    @property
    def project_reference_parts(self) -> typing.Sequence[str]:
        return self.project_folder_path.parts if self.project_folder_path else tuple()

    def make_storage(self, profile_context: typing.Optional[ProfileContext]) -> typing.Optional[Persistence.PersistentStorageInterface]:
        if self.project_folder_path:
            return FileStorageSystem.make_folder_project_storage_system(self.project_folder_path)
        return None

    def _get_last_used(self) -> datetime.datetime:
        # fallback when last_used is not initialized
        try:
            project_folder_path = self.project_folder_path
            if project_folder_path:
                return datetime.datetime.fromtimestamp(os.path.getmtime(project_folder_path))
            else:
                return super()._get_last_used()
        except Exception:
            return super()._get_last_used()

    def _upgrade_project_storage_system(self, project_storage_system: Persistence.PersistentStorageInterface) -> ProjectReference:
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
        with contextlib.closing(FileStorageSystem.make_index_project_storage_system(target_project_path)) as new_storage_system:
            new_storage_system.load_properties()
            FileStorageSystem.migrate_to_latest(
                typing.cast(FileStorageSystem.MigrationReader, project_storage_system),
                typing.cast(FileStorageSystem.MigrationWriter, new_storage_system)
            )
        new_project_reference = IndexProjectReference()
        new_project_reference.project_path = target_project_path
        new_project_reference.project_uuid = target_project_uuid
        return new_project_reference


class PlaceholderProjectReference(ProjectReference):

    def __init__(self, type: str) -> None:
        super().__init__(type)

    @property
    def is_valid(self) -> bool:
        return False

    @property
    def project_reference_parts(self) -> typing.Sequence[str]:
        return (self.type, str(self.project_uuid or uuid.UUID()))

    def make_storage(self, profile_context: typing.Optional[ProfileContext]) -> typing.Optional[Persistence.PersistentStorageInterface]:
        return None


project_reference_factory_hook: typing.Optional[typing.Callable[[str], typing.Optional[ProjectReference]]] = None


def project_reference_factory(lookup_id: typing.Callable[[str], str]) -> typing.Optional[ProjectReference]:
    type = lookup_id("type")
    if type == IndexProjectReference.type:
        return IndexProjectReference()
    if type == FolderProjectReference.type:
        return FolderProjectReference()
    if callable(project_reference_factory_hook):
        return project_reference_factory_hook(type)
    return PlaceholderProjectReference(type)


class ScriptItem(Schema.Entity):
    def __init__(self, entity_type: Schema.EntityType, context: typing.Optional[Schema.EntityContext] = None) -> None:
        super().__init__(entity_type, context)
        self.persistent_storage: typing.Optional[Persistence.PersistentStorageInterface] = None

    @property
    def is_closed(self) -> bool:
        return typing.cast(bool, self._get_field_value("is_closed"))

    @is_closed.setter
    def is_closed(self, value: bool) -> None:
        self._set_field_value("is_closed", value)

    # standard overrides from entity to fit within persistent object architecture

    def _field_value_changed(self, name: str, value: typing.Any) -> None:
        # this is called when a property changes. to be compatible with the older
        # persistent object structure, check if persistent storage exists and pass
        # the message along to persistent storage.
        persistent_storage = typing.cast(Persistence.PersistentStorageInterface, getattr(self, "persistent_storage", None))
        if persistent_storage:
            if value is not None:
                persistent_storage.set_property(typing.cast(Persistence.PersistentObject, self), name, value)
            else:
                persistent_storage.clear_property(typing.cast(Persistence.PersistentObject, self), name)


class FileScriptItem(ScriptItem):
    def __init__(self, path: typing.Optional[pathlib.Path] = None) -> None:
        super().__init__(Model.FileScriptItem)
        if path:
            self.path = path

    @property
    def path(self) -> typing.Optional[pathlib.Path]:
        path_str = self._get_field_value("path")
        if path_str:
            return pathlib.Path(path_str)
        return None

    @path.setter
    def path(self, value: typing.Optional[pathlib.Path]) -> None:
        self._set_field_value("path", value)


class FolderScriptItem(ScriptItem):
    def __init__(self, folder_path: typing.Optional[pathlib.Path] = None, is_closed: bool = True) -> None:
        super().__init__(Model.FolderScriptItem)
        if folder_path:
            self.folder_path = folder_path
        self.is_closed = is_closed

    @property
    def folder_path(self) -> typing.Optional[pathlib.Path]:
        path_str = self._get_field_value("folder_path")
        if path_str:
            return pathlib.Path(path_str)
        return None

    @folder_path.setter
    def folder_path(self, value: typing.Optional[pathlib.Path]) -> None:
        self._set_field_value("folder_path", value)


# casting required to use entity in place of persistent object
def script_item_factory(lookup_id: typing.Callable[[str], str]) -> typing.Optional[ScriptItem]:
    type = lookup_id("type")
    if type == Model.FileScriptItem.entity_id:
        return FileScriptItem()
    if type == Model.FolderScriptItem.entity_id:
        return FolderScriptItem()
    return None


class Profile(Persistence.PersistentObject):
    count = 0  # useful for detecting leaks in tests

    def __init__(self, storage_system: typing.Optional[Persistence.PersistentStorageInterface] = None,
                 cache_dir_path: typing.Optional[pathlib.Path] = None, *,
                 cache_factory: typing.Optional[Cache.CacheFactory] = None,
                 profile_context: typing.Optional[ProfileContext] = None) -> None:
        super().__init__()
        self.__class__.count += 1

        self.define_root_context()
        self.define_type("profile")
        self.define_property("last_project_reference", converter=Converter.UuidToStringConverter(), hidden=True)
        self.define_property("work_project_reference_uuid", converter=Converter.UuidToStringConverter(), hidden=True)
        self.define_property("closed_items", list(), hidden=True)
        self.define_property("script_items_updated", False, changed=self.__property_changed, hidden=True)
        self.define_relationship("project_references", project_reference_factory,
                                 insert=self.__insert_project_reference, remove=self.__remove_project_reference,
                                 hidden=True)
        self.define_relationship("script_items", typing.cast(
            typing.Callable[[typing.Callable[[str], str]], typing.Optional[Persistence.PersistentObject]],
            script_item_factory), hidden=True)

        # ensure a storage system; use a memory based storage as a fallback (for testing).
        self.storage_system = storage_system or FileStorageSystem.make_memory_persistent_storage_system()
        self.storage_system.load_properties()

        self.set_storage_system(self.storage_system)

        self.__cache_dir_path = cache_dir_path
        self.__cache_factory = cache_factory

        self.profile_context = None

        # helper object to produce the projects sequence
        oo = Observer.ObserverBuilder()
        oo.source(typing.cast(Observer.ItemValue, self)).ordered_sequence_from_array("project_references").map(
            oo.x.prop("project")).filter(lambda x: x is not None).trampoline(self, "projects")
        self.__projects_observer = oo.make_observable()

        if profile_context:
            self.profile_context = profile_context
            self.add_project_memory()

    def close(self) -> None:
        self.storage_system.close()
        self.storage_system = typing.cast(typing.Any, None)
        if self.__projects_observer:
            self.__projects_observer.close()
        self.__projects_observer = typing.cast(Observer.AbstractItemSource, None)
        self.profile_context = None
        self.__class__.count -= 1
        super().close()

    @property
    def last_project_reference(self) -> typing.Optional[uuid.UUID]:
        return typing.cast(typing.Optional[uuid.UUID], self._get_persistent_property_value("last_project_reference"))

    @last_project_reference.setter
    def last_project_reference(self, value: typing.Optional[uuid.UUID]) -> None:
        self._set_persistent_property_value("last_project_reference", value)

    @property
    def work_project_reference_uuid(self) -> typing.Optional[uuid.UUID]:
        return typing.cast(typing.Optional[uuid.UUID], self._get_persistent_property_value("work_project_reference_uuid"))

    @work_project_reference_uuid.setter
    def work_project_reference_uuid(self, value: typing.Optional[uuid.UUID]) -> None:
        self._set_persistent_property_value("work_project_reference_uuid", value)

    @property
    def closed_items(self) -> typing.Sequence[str]:
        return typing.cast(typing.Sequence[str], self._get_persistent_property_value("closed_items"))

    @closed_items.setter
    def closed_items(self, value: typing.Sequence[str]) -> None:
        self._set_persistent_property_value("closed_items", value)

    @property
    def script_items_updated(self) -> bool:
        return typing.cast(bool, self._get_persistent_property_value("script_items_updated"))

    @script_items_updated.setter
    def script_items_updated(self, value: bool) -> None:
        self._set_persistent_property_value("script_items_updated", value)

    @property
    def project_references(self) -> typing.Sequence[ProjectReference]:
        return typing.cast(typing.Sequence[ProjectReference], self._get_relationship_values("project_references"))

    @property
    def script_items(self) -> typing.Sequence[ScriptItem]:
        return typing.cast(typing.Sequence[ScriptItem], self._get_relationship_values("script_items"))

    def read_from_dict(self, properties: Persistence.PersistentDictType) -> None:
        # cleanup from beta versions
        properties.pop("data_groups", None)
        properties.pop("data_item_references", None)
        properties.pop("data_item_variables", None)
        properties.pop("project_uuid", None)
        properties.pop("target_project_reference_uuid", None)
        properties.pop("workspace_uuid", None)
        properties.pop("workspaces", None)
        super().read_from_dict(properties)

    def __property_changed(self, name: str, value: typing.Any) -> None:
        self.notify_property_changed(name)

    def __insert_project_reference(self, name: str, before_index: int, project_reference: ProjectReference) -> None:
        project_reference.read_project_info(self.profile_context)
        self.notify_insert_item("project_references", project_reference, before_index)

    def __remove_project_reference(self, name: str, index: int, project_reference: ProjectReference) -> None:
        self.notify_remove_item("project_references", project_reference, index)

    @property
    def projects(self) -> typing.Sequence[Project.Project]:
        assert self.__projects_observer
        return typing.cast(typing.Sequence[Project.Project], self.__projects_observer.item)

    def insert_script_item(self, before_index: int, script_item: ScriptItem) -> None:
        """Insert a script_item before the index, but do it through the container, so dependencies can be tracked."""
        self.insert_model_item(self, "script_items", before_index, typing.cast(Persistence.PersistentObject, script_item))

    def append_script_item(self, script_item: ScriptItem) -> None:
        """Append a script_item, but do it through the container, so dependencies can be tracked."""
        self.insert_model_item(self, "script_items", self.item_count("script_items"), typing.cast(Persistence.PersistentObject, script_item))

    def remove_script_item(self, script_item: ScriptItem, *, safe: bool = False) -> Changes.UndeleteLog:
        """Remove a script_item, but do it through the container, so dependencies can be tracked."""
        return self.remove_model_item(self, "script_items", typing.cast(Persistence.PersistentObject, script_item), safe=safe)

    def __insert_script_item(self, name: str, before_index: int, script_item: ScriptItem) -> None:
        self.notify_insert_item("script_items", script_item, before_index)

    def __remove_script_item(self, name: str, index: int, script_item: ScriptItem) -> None:
        self.notify_remove_item("script_items", script_item, index)

    @property
    def _profile_storage_system(self) -> typing.Optional[Persistence.PersistentStorageInterface]:
        return self.storage_system

    def read_profile(self) -> None:
        # read the properties from the storage system. called after open.
        properties = self.storage_system.get_storage_properties()

        # if the properties match the current version, read the properties.
        if properties is not None and properties.get("version", 0) == FileStorageSystem.PROFILE_VERSION:
            self.begin_reading()
            try:
                if not self.project_references:  # hack for testing. tests will have already set up profile.
                    self.read_from_dict(properties)
            finally:
                self.finish_reading()
            self.storage_system.set_property(self, "uuid", str(self.uuid))
            self.storage_system.set_property(self, "version", FileStorageSystem.PROFILE_VERSION)

    def read_project(self, project_reference: ProjectReference) -> None:
        project_reference.load_project(self.profile_context, self.__cache_dir_path, cache_factory=self.__cache_factory)

    def create_project(self, project_dir: pathlib.Path, library_name: str) -> typing.Optional[ProjectReference]:
        project_name = pathlib.Path(library_name)
        project_data_path = pathlib.Path(library_name + " Data")
        project_path = project_dir / project_name.with_suffix(".nsproj")
        project_dir.mkdir(parents=True, exist_ok=True)
        project_uuid = uuid.uuid4()
        project_data_json = json.dumps({"version": FileStorageSystem.PROJECT_VERSION, "uuid": str(project_uuid),
                                        "project_data_folders": [str(project_data_path)]})
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
        assert project_reference.project_uuid not in {project_reference.project_uuid for project_reference in self.project_references}
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
            project_reference.close()
            if load:
                existing_project_reference.load_project(self.profile_context, self.__cache_dir_path, cache_factory=self.__cache_factory)
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

    def add_project_memory(self, _uuid: typing.Optional[uuid.UUID] = None, load: bool = True) -> ProjectReference:
        assert callable(project_reference_factory_hook)
        project_reference = project_reference_factory_hook("project_memory")
        assert project_reference
        project_reference.project_uuid = _uuid or uuid.uuid4()
        project_reference.establish_last_used()
        return self.add_project_reference(project_reference, load)

    def upgrade(self, project_reference: ProjectReference) -> typing.Optional[ProjectReference]:
        new_project_reference = project_reference.upgrade(self.profile_context)
        if new_project_reference:
            self.remove_project_reference(project_reference)
            return self.add_project_reference(new_project_reference, load=False)
        return None
