from __future__ import annotations

# standard libraries
import functools
import logging
import operator
import time
import typing
import uuid
import weakref

# local libraries
from nion.swift.model import Cache
from nion.swift.model import Changes
from nion.swift.model import Connection
from nion.swift.model import DataGroup
from nion.swift.model import Symbolic
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayItem
from nion.swift.model import FileStorageSystem
from nion.swift.model import Persistence
from nion.swift.model import Symbolic
from nion.swift.model import WorkspaceLayout
from nion.utils import Converter
from nion.utils import ListModel

PersistentDictType = typing.Dict[str, typing.Any]

ProjectItemType = typing.Union[DataItem.DataItem, DisplayItem.DisplayItem, DataStructure.DataStructure, Connection.Connection, Symbolic.Computation]


class Project(Persistence.PersistentObject):
    """A project manages raw data items, display items, computations, data structures, and connections.

    Projects are stored in project indexes, which are files that describe how to find data and and tracks the other
    project relationships (display items, computations, data structures, connections).

    Projects manage reading, writing, and data migration.
    """

    PROJECT_VERSION = 3

    def __init__(self, storage_system: Persistence.PersistentStorageInterface, cache_factory: typing.Optional[Cache.CacheFactory] = None) -> None:
        super().__init__()

        self.define_type("project")
        self.define_property("title", str(), hidden=True)
        self.define_relationship("data_items", data_item_factory, insert=self.__data_item_inserted, remove=self.__data_item_removed, hidden=True)
        self.define_relationship("display_items", display_item_factory, insert=self.__display_item_inserted, remove=self.__display_item_removed, hidden=True)
        self.define_relationship("computations", computation_factory, insert=self.__computation_inserted, remove=self.__computation_removed, hidden=True)
        self.define_relationship("data_structures", data_structure_factory, insert=self.__data_structure_inserted, remove=self.__data_structure_removed, hidden=True)
        self.define_relationship("connections", Connection.connection_factory, insert=self.__connection_inserted, remove=self.__connection_removed, hidden=True)
        self.define_relationship("data_groups", DataGroup.data_group_factory, insert=self.__data_group_inserted, remove=self.__data_group_removed, hidden=True)
        self.define_relationship("workspaces", WorkspaceLayout.factory, hidden=True)
        self.define_property("workspace_uuid", converter=Converter.UuidToStringConverter(), hidden=True)
        self.define_property("data_item_references", dict(), changed=self.__property_changed, hidden=True)  # map string key to data item, used for data acquisition channels
        self.define_property("mapped_items", list(), changed=self.__property_changed, hidden=True)  # list of item references, used for shortcut variables in scripts

        self.handle_start_read: typing.Optional[typing.Callable[[], None]] = None
        self.handle_insert_model_item: typing.Optional[typing.Callable[[Persistence.PersistentContainerType, str, int, Persistence.PersistentObject], None]] = None
        self.handle_remove_model_item: typing.Optional[typing.Callable[[Persistence.PersistentContainerType, str, Persistence.PersistentObject, bool], Changes.UndeleteLog]] = None
        self.handle_finish_read: typing.Optional[typing.Callable[[], None]] = None

        self.__has_been_read = False
        self.__project_load_start_time = 0.0

        self._raw_properties: typing.Optional[PersistentDictType] = None
        self.__reader_errors: typing.Sequence[Persistence.ReaderError] = list()

        self.__storage_system = storage_system

        self.set_storage_system(self.__storage_system)

        self.__cache_factory = cache_factory
        self.__cache = cache_factory.create_cache() if cache_factory else None

    def close(self) -> None:
        self.handle_start_read = None
        self.handle_insert_model_item = None
        self.handle_remove_model_item = None
        self.handle_finish_read = None
        if self.__cache_factory:
            self.__cache_factory.release_cache(typing.cast(Cache.CacheLike, self.__cache))
            self.__cache_factory = None
            self.__cache = None
        self.__storage_system.close()
        self.__storage_system = typing.cast(typing.Any, None)
        super().close()

    @property
    def title(self) -> str:
        return typing.cast(str, self._get_persistent_property_value("title"))

    @title.setter
    def title(self, value: str) -> None:
        self._set_persistent_property_value("title", value)

    @property
    def workspace_uuid(self) -> typing.Optional[uuid.UUID]:
        uuid_str = typing.cast(typing.Optional[str], self._get_persistent_property_value("workspace_uuid"))
        return uuid.UUID(uuid_str) if uuid_str else None

    @workspace_uuid.setter
    def workspace_uuid(self, value: typing.Optional[uuid.UUID]) -> None:
        self._set_persistent_property_value("workspace_uuid", str(value) if value else None)

    @property
    def mapped_items(self) -> typing.List[Persistence._SpecifierType]:
        return list(self._get_persistent_property_value("mapped_items"))

    @mapped_items.setter
    def mapped_items(self, value: typing.List[Persistence._SpecifierType]) -> None:
        self._set_persistent_property_value("mapped_items", value)

    @property
    def data_items(self) -> typing.Sequence[DataItem.DataItem]:
        return typing.cast(typing.Sequence[DataItem.DataItem], self._get_relationship_values("data_items"))

    @property
    def display_items(self) -> typing.Sequence[DisplayItem.DisplayItem]:
        return typing.cast(typing.Sequence[DisplayItem.DisplayItem], self._get_relationship_values("display_items"))

    @property
    def computations(self) -> typing.Sequence[Symbolic.Computation]:
        return typing.cast(typing.Sequence[Symbolic.Computation], self._get_relationship_values("computations"))

    @property
    def data_structures(self) -> typing.Sequence[DataStructure.DataStructure]:
        return typing.cast(typing.Sequence[DataStructure.DataStructure], self._get_relationship_values("data_structures"))

    @property
    def connections(self) -> typing.Sequence[Connection.Connection]:
        return typing.cast(typing.Sequence[Connection.Connection], self._get_relationship_values("connections"))

    @property
    def data_groups(self) -> typing.Sequence[DataGroup.DataGroup]:
        return typing.cast(typing.Sequence[DataGroup.DataGroup], self._get_relationship_values("data_groups"))

    @property
    def workspaces(self) -> typing.Sequence[WorkspaceLayout.WorkspaceLayout]:
        return typing.cast(typing.Sequence[WorkspaceLayout.WorkspaceLayout], self._get_relationship_values("workspaces"))

    @property
    def sorted_workspaces(self) -> typing.Sequence[WorkspaceLayout.WorkspaceLayout]:
        return sorted(self.workspaces, key=operator.attrgetter("timestamp_for_sorting"), reverse=True)

    def open(self) -> None:
        self.__storage_system.reset()  # this makes storage reusable during tests

    def create_proxy(self) -> Persistence.PersistentObjectProxy[Project]:
        container = self.container
        assert container
        return container.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(self.uuid)

    def insert_model_item(self, container: Persistence.PersistentContainerType, name: str, before_index: int, item: Persistence.PersistentObject) -> None:
        # special handling to pass on to the document model
        assert callable(self.handle_insert_model_item)
        self.handle_insert_model_item(container, name, before_index, item)

    def remove_model_item(self, container: Persistence.PersistentContainerType, name: str, item: Persistence.PersistentObject, *, safe: bool = False) -> Changes.UndeleteLog:
        # special handling to pass on to the document model
        assert callable(self.handle_remove_model_item)
        return self.handle_remove_model_item(container, name, item, safe)

    @property
    def storage_location_str(self) -> str:
        return self.__storage_system.get_identifier()

    @property
    def storage_cache(self) -> Cache.CacheLike:
        assert self.__cache
        return self.__cache

    @property
    def project_uuid(self) -> typing.Optional[uuid.UUID]:
        properties = self.__storage_system.get_storage_properties()
        try:
            return uuid.UUID(properties.get("uuid", str(uuid.uuid4()))) if properties else None
        except Exception as e:
            return None

    @property
    def project_state(self) -> str:
        properties = self.__storage_system.get_storage_properties()
        if properties is not None and not properties:
            return "missing"
        project_uuid = self.project_uuid
        project_version = self.project_version
        if project_uuid is not None and project_version is not None:
            if project_version  == FileStorageSystem.PROJECT_VERSION:
                return "loaded" if self.__has_been_read else "unloaded"
            else:
                return "needs_upgrade"
        return "invalid"

    @property
    def project_version(self) -> typing.Optional[int]:
        properties = self.__storage_system.get_storage_properties()
        try:
            return properties.get("version", None) if properties else None
        except Exception:
            return None

    @property
    def project_filter(self) -> ListModel.Filter:

        # Python 3.9+ weak ref
        def is_display_item_active(project_weak_ref: typing.Any, display_item: DisplayItem.DisplayItem) -> bool:
            return bool(display_item.project == project_weak_ref())

        # use a weak reference to avoid circular references loops that prevent garbage collection
        return ListModel.PredicateFilter(functools.partial(is_display_item_active, weakref.ref(self)))

    @property
    def project_storage_system(self) -> Persistence.PersistentStorageInterface:
        return self.__storage_system

    def __data_item_inserted(self, name: str, before_index: int, data_item: DataItem.DataItem) -> None:
        self.notify_insert_item("data_items", data_item, before_index)

    def __data_item_removed(self, name: str, index: int, data_item: DataItem.DataItem) -> None:
        self.notify_remove_item("data_items", data_item, index)

    def __display_item_inserted(self, name: str, before_index: int, display_item: DisplayItem.DisplayItem) -> None:
        self.notify_insert_item("display_items", display_item, before_index)

    def __display_item_removed(self, name: str, index: int, display_item: DisplayItem.DisplayItem) -> None:
        self.notify_remove_item("display_items", display_item, index)

    def __data_structure_inserted(self, name: str, before_index: int, data_structure: DataStructure.DataStructure) -> None:
        self.notify_insert_item("data_structures", data_structure, before_index)

    def __data_structure_removed(self, name: str, index: int, data_structure: DataStructure.DataStructure) -> None:
        self.notify_remove_item("data_structures", data_structure, index)

    def __computation_inserted(self, name: str, before_index: int, computation: Symbolic.Computation) -> None:
        self.notify_insert_item("computations", computation, before_index)

    def __computation_removed(self, name: str, index: int, computation: Symbolic.Computation) -> None:
        self.notify_remove_item("computations", computation, index)

    def __connection_inserted(self, name: str, before_index: int, connection: Connection.Connection) -> None:
        self.notify_insert_item("connections", connection, before_index)

    def __connection_removed(self, name: str, index: int, connection: Connection.Connection) -> None:
        self.notify_remove_item("connections", connection, index)

    def __data_group_inserted(self, name: str, before_index: int, data_group: DataGroup.DataGroup) -> None:
        self.notify_insert_item("data_groups", data_group, before_index)

    def __data_group_removed(self, name: str, index: int, data_group: DataGroup.DataGroup) -> None:
        self.notify_remove_item("data_groups", data_group, index)

    def prepare_read_project(self) -> None:
        self.__project_load_start_time = time.time()
        logging.getLogger("loader").info(f"Loading project {self.__storage_system.get_identifier()}")
        self._raw_properties, self.__reader_errors = self.__storage_system.read_project_properties()  # combines library and data item properties
        self.uuid = uuid.UUID(self._raw_properties.get("uuid", str(uuid.uuid4())))

        for reader_error in self.__reader_errors:
            logging.getLogger("loader").error(f"Error reading {reader_error.identifier} ({reader_error.exception})")
            if False and reader_error.tb is not None:
                import sys
                import traceback
                print(f"Event Listener Traceback (most recent call last)", file=sys.stderr)
                frame_summaries = typing.cast(typing.List[typing.Any], reader_error.tb)
                for line in traceback.StackSummary.from_list(frame_summaries).format():
                    print(line, file=sys.stderr, end="")

    def read_project(self) -> None:
        if callable(self.handle_start_read):
            self.handle_start_read()
        properties = self._raw_properties
        if properties:
            project_version = properties.get("version", None)
            if project_version is not None and project_version == FileStorageSystem.PROJECT_VERSION:
                for item_d in properties.get("data_items", list()):
                    data_item = DataItem.DataItem()
                    data_item.begin_reading()
                    data_item.read_from_dict(item_d)
                    data_item.finish_reading()
                    if not self.get_item_by_uuid("data_items", data_item.uuid):
                        self.load_item("data_items", len(self.data_items), data_item)
                    else:
                        data_item.close()
                for item_d in properties.get("display_items", list()):
                    display_item = DisplayItem.DisplayItem()
                    display_item.begin_reading()
                    display_item.read_from_dict(item_d)
                    display_item.finish_reading()
                    if not self.get_item_by_uuid("display_items", display_item.uuid):
                        self.load_item("display_items", len(self.display_items), display_item)
                    else:
                        display_item.close()
                for item_d in properties.get("data_structures", list()):
                    data_structure = DataStructure.DataStructure()
                    data_structure.begin_reading()
                    data_structure.read_from_dict(item_d)
                    data_structure.finish_reading()
                    if not self.get_item_by_uuid("data_structures", data_structure.uuid):
                        self.load_item("data_structures", len(self.data_structures), data_structure)
                    else:
                        data_structure.close()
                for item_d in properties.get("computations", list()):
                    computation = Symbolic.Computation()
                    computation.begin_reading()
                    computation.read_from_dict(item_d)
                    computation.finish_reading()
                    if not self.get_item_by_uuid("computations", computation.uuid):
                        self.load_item("computations", len(self.computations), computation)
                        # TODO: handle update script and bind after reload in document model
                        computation.update_script()
                        computation.reset()
                    else:
                        computation.close()
                for item_d in properties.get("connections", list()):
                    connection = Connection.connection_factory(item_d.get)
                    if connection:
                        connection.begin_reading()
                        connection.read_from_dict(item_d)
                        connection.finish_reading()
                        if not self.get_item_by_uuid("connections", connection.uuid):
                            self.load_item("connections", len(self.connections), connection)
                        else:
                            connection.close()
                for item_d in properties.get("data_groups", list()):
                    data_group = DataGroup.data_group_factory(item_d.get)
                    if data_group:
                        data_group.begin_reading()
                        data_group.read_from_dict(item_d)
                        data_group.finish_reading()
                        if not self.get_item_by_uuid("data_groups", data_group.uuid):
                            self.load_item("data_groups", len(self.data_groups), data_group)
                        else:
                            data_group.close()
                for item_d in properties.get("workspaces", list()):
                    workspace = WorkspaceLayout.factory(item_d.get)
                    workspace.begin_reading()
                    workspace.read_from_dict(item_d)
                    workspace.finish_reading()
                    if not self.get_item_by_uuid("workspaces", workspace.uuid):
                        self.load_item("workspaces", len(self.workspaces), workspace)
                    else:
                        workspace.close()
                workspace_uuid_str = properties.get("workspace_uuid", None)
                workspace_uuid = uuid.UUID(workspace_uuid_str) if workspace_uuid_str else None
                existing_workspace_uuid = self._get_persistent_property_value("workspace_uuid", None)
                if workspace_uuid and existing_workspace_uuid != workspace_uuid:
                    self._get_persistent_property("workspace_uuid").set_value(str(workspace_uuid))
                self._get_persistent_property("data_item_references").set_value(properties.get("data_item_references", dict()))
                self._get_persistent_property("mapped_items").set_value(properties.get("mapped_items", list()))
                self.__has_been_read = True
        if callable(self.handle_finish_read):
            self.handle_finish_read()
        elapsed_s = int(time.time() - self.__project_load_start_time)
        logging.getLogger("loader").info(f"Loaded project {elapsed_s}s (data items: {len(self.data_items)}, display items: {len(self.display_items)}, data structures: {len(self.data_structures)}, computations: {len(self.computations)}, connections: {len(self.connections)}, data groups: {len(self.data_groups)}, workspaces: {len(self.workspaces)})")

    def __property_changed(self, name: str, value: typing.Any) -> None:
        self.notify_property_changed(name)

    def append_data_item(self, data_item: DataItem.DataItem) -> None:
        assert not self.get_item_by_uuid("data_items", data_item.uuid)
        self.append_item("data_items", data_item)
        data_item.write_data_if_not_delayed()  # initially write to disk

    def remove_data_item(self, data_item: DataItem.DataItem) -> None:
        self.remove_item("data_items", data_item)

    def restore_data_item(self, data_item_uuid: uuid.UUID) -> typing.Optional[DataItem.DataItem]:
        item_d = self.__storage_system.restore_item(data_item_uuid)
        if item_d is not None:
            data_item_uuid = uuid.UUID(item_d.get("uuid"))
            large_format = item_d.get("__large_format", False)
            data_item = DataItem.DataItem(item_uuid=data_item_uuid, large_format=large_format)
            data_item.begin_reading()
            data_item.read_from_dict(item_d)
            data_item.finish_reading()
            assert not self.get_item_by_uuid("data_items", data_item.uuid)
            self.append_item("data_items", data_item)
            assert data_item.container == self
            return data_item
        return None

    def append_display_item(self, display_item: DisplayItem.DisplayItem) -> None:
        assert not self.get_item_by_uuid("display_items", display_item.uuid)
        self.append_item("display_items", display_item)

    def remove_display_item(self, display_item: DisplayItem.DisplayItem) -> None:
        self.remove_item("display_items", display_item)

    def append_data_structure(self, data_structure: DataStructure.DataStructure) -> None:
        assert not self.get_item_by_uuid("data_structures", data_structure.uuid)
        self.append_item("data_structures", data_structure)

    def remove_data_structure(self, data_structure: DataStructure.DataStructure) -> None:
        self.remove_item("data_structures", data_structure)

    def append_computation(self, computation: Symbolic.Computation) -> None:
        assert not self.get_item_by_uuid("computations", computation.uuid)
        self.append_item("computations", computation)

    def remove_computation(self, computation: Symbolic.Computation) -> None:
        self.remove_item("computations", computation)

    def append_connection(self, connection: Connection.Connection) -> None:
        assert not self.get_item_by_uuid("connections", connection.uuid)
        self.append_item("connections", connection)

    def remove_connection(self, connection: Connection.Connection) -> None:
        self.remove_item("connections", connection)

    @property
    def data_item_references(self) -> typing.Dict[str, str]:
        return dict(self._get_persistent_property_value("data_item_references").items())

    def set_data_item_reference(self, key: str, data_item: DataItem.DataItem) -> None:
        data_item_references = self.data_item_references
        data_item_references[key] = str(data_item.item_specifier.write())
        self._set_persistent_property_value("data_item_references", {k: v for k, v in data_item_references.items()})

    def clear_data_item_reference(self, key: str) -> None:
        data_item_references = self.data_item_references
        del data_item_references[key]
        self._set_persistent_property_value("data_item_references", {k: v for k, v in data_item_references.items()})

    def prune(self) -> None:
        self.__storage_system.prune()

    def migrate_to_latest(self) -> None:
        self.__storage_system.migrate_to_latest()
        self.__storage_system.load_properties()
        self.update_storage_system()  # reload the properties
        self.prepare_read_project()
        self.read_project()

    def unmount(self) -> None:
        while len(self.data_groups) > 0:
            self.unload_item("data_groups", len(self.data_groups) - 1)
        while len(self.connections) > 0:
            self.unload_item("connections", len(self.connections) - 1)
        while len(self.computations) > 0:
            self.unload_item("computations", len(self.computations) - 1)
        while len(self.data_structures) > 0:
            self.unload_item("data_structures", len(self.data_structures) - 1)
        while len(self.display_items) > 0:
            self.unload_item("display_items", len(self.display_items) - 1)
        while len(self.data_items) > 0:
            self.unload_item("data_items", len(self.data_items) - 1)


def data_item_factory(lookup_id: typing.Callable[[str], str]) -> DataItem.DataItem:
    data_item_uuid = uuid.UUID(lookup_id("uuid"))
    # TODO: typing hack for default arg
    large_format = typing.cast(typing.Callable[..., typing.Any], lookup_id)("__large_format", False)
    return DataItem.DataItem(item_uuid=data_item_uuid, large_format=large_format)


def display_item_factory(lookup_id: typing.Callable[[str], str]) -> DisplayItem.DisplayItem:
    display_item_uuid = uuid.UUID(lookup_id("uuid"))
    return DisplayItem.DisplayItem(item_uuid=display_item_uuid)


def computation_factory(lookup_id: typing.Callable[[str], str]) -> Symbolic.Computation:
    return Symbolic.Computation()


def data_structure_factory(lookup_id: typing.Callable[[str], str]) -> DataStructure.DataStructure:
    return DataStructure.DataStructure()
