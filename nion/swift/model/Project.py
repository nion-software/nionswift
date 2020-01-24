# standard libraries
import copy
import functools
import logging
import pathlib
import typing
import uuid
import weakref

# local libraries
from nion.swift.model import Changes
from nion.swift.model import Connection
from nion.swift.model import Symbolic
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayItem
from nion.swift.model import FileStorageSystem
from nion.swift.model import Persistence
from nion.utils import ListModel
from nion.utils import Observable


ProjectItemType = typing.Union[DataItem.DataItem, DisplayItem.DisplayItem, DataStructure.DataStructure, Connection.Connection, Symbolic.Computation]


class Project(Observable.Observable, Persistence.PersistentObject):
    """A project manages raw data items, display items, computations, data structures, and connections.

    Projects are stored in project indexes, which are files that describe how to find data and and tracks the other
    project relationships (display items, computations, data structures, connections).

    Projects manage reading, writing, and data migration.
    """

    PROJECT_VERSION = 3

    def __init__(self, storage_system: FileStorageSystem.ProjectStorageSystem, project_reference: typing.Dict):
        super().__init__()

        self.uuid = uuid.UUID(project_reference["uuid"])

        self.define_type("project")
        self.define_relationship("data_items", data_item_factory, insert=self.__data_item_inserted, remove=self.__data_item_removed)
        self.define_relationship("display_items", display_item_factory, insert=self.__display_item_inserted, remove=self.__display_item_removed)
        self.define_relationship("computations", computation_factory, insert=self.__computation_inserted, remove=self.__computation_removed)
        self.define_relationship("data_structures", data_structure_factory, insert=self.__data_structure_inserted, remove=self.__data_structure_removed)
        self.define_relationship("connections", Connection.connection_factory, insert=self.__connection_inserted, remove=self.__connection_removed)

        self.__project_reference = copy.deepcopy(project_reference)
        self.__project_state = None
        self.__project_version = 0

        self._raw_properties = None  # debugging

        self.__storage_system = storage_system

        self.set_storage_system(self.__storage_system)

    def open(self) -> None:
        self.__storage_system.reset()  # this makes storage reusable during tests

    def create_proxy(self) -> Persistence.PersistentObjectProxy:
        return self.container.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(item_uuid=self.uuid)

    def create_specifier(self, item: Persistence.PersistentObject, *, allow_partial: bool = True) -> Persistence.PersistentObjectSpecifier:
        if item.project == self and allow_partial:
            return Persistence.PersistentObjectSpecifier(item=item)
        else:
            return Persistence.PersistentObjectSpecifier(item=item, context=item.project)

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
        if item_specifier.context_uuid is None or item_specifier.context_uuid == self.uuid:
            item_uuid = item_specifier.item_uuid
            data_item = self.get_item_by_uuid("data_items", item_uuid)
            if data_item:
                return data_item
            display_item = self.get_item_by_uuid("display_items", item_uuid)
            if display_item:
                return display_item
            connection = self.get_item_by_uuid("connections", item_uuid)
            if connection:
                return connection
            data_structure = self.get_item_by_uuid("data_structures", item_uuid)
            if data_structure:
                return data_structure
            computation = self.get_item_by_uuid("computations", item_uuid)
            if computation:
                return computation
            for display_item in self.display_items:
                display_data_channel = display_item.get_item_by_uuid("display_data_channels", item_uuid)
                if display_data_channel:
                    return display_data_channel
                graphic = display_item.get_item_by_uuid("graphics", item_uuid)
                if graphic:
                    return graphic
        return super()._get_related_item(item_specifier)

    @property
    def needs_upgrade(self) -> bool:
        return self.__project_reference.get("type") == "project_folder"

    @property
    def project_reference(self) -> typing.Dict:
        return copy.deepcopy(self.__project_reference)

    @property
    def project_reference_parts(self) -> typing.Tuple[str]:
        if self.__project_reference.get("type") == "project_folder":
            return pathlib.Path(self.__storage_system.get_identifier()).parent.parts
        else:
            return pathlib.Path(self.__storage_system.get_identifier()).parts

    @property
    def legacy_path(self) -> pathlib.Path:
        return pathlib.Path(self.__storage_system.get_identifier()).parent

    @property
    def project_reference_str(self) -> str:
        return str(pathlib.Path(self.__storage_system.get_identifier()))

    @property
    def project_state(self) -> str:
        return self.__project_state

    @property
    def project_version(self) -> int:
        return self.__project_version

    @property
    def project_title(self) -> str:
        return pathlib.Path(self.project_reference_parts[-1]).stem

    @property
    def project_filter(self) -> ListModel.Filter:

        def is_display_item_active(project_weak_ref, display_item: DisplayItem.DisplayItem) -> bool:
            return display_item in project_weak_ref().display_items

        # use a weak reference to avoid circular references loops that prevent garbage collection
        return ListModel.PredicateFilter(functools.partial(is_display_item_active, weakref.ref(self)))

    @property
    def project_storage_system(self) -> FileStorageSystem.ProjectStorageSystem:
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

    def _get_relationship_persistent_dict(self, item, key: str, index: int) -> typing.Dict:
        if key == "data_items":
            return self.__storage_system.get_persistent_dict("data_items", item.uuid)
        else:
            return super()._get_relationship_persistent_dict(item, key, index)

    def _get_relationship_persistent_dict_by_uuid(self, item, key: str) -> typing.Optional[typing.Dict]:
        if key == "data_items":
            return self.__storage_system.get_persistent_dict("data_items", item.uuid)
        else:
            return super()._get_relationship_persistent_dict_by_uuid(item, key)

    def prepare_read_project(self) -> None:
        logging.getLogger("loader").info(f"Loading project {self.__storage_system.get_identifier()}")
        self._raw_properties = self.__storage_system.read_project_properties()  # combines library and data item properties
        self.project_uuid_str = self._raw_properties.get("uuid", str(uuid.uuid4()))
        self.uuid = uuid.UUID(self.project_uuid_str)

    def read_project(self) -> None:
        properties = self._raw_properties
        self.__project_version = properties.get("version", None)
        if not self._raw_properties:
            self.__project_state = "missing"
        elif self.project_reference["uuid"] != self.project_uuid_str:
            self.__project_state = "uuid_mismatch"
        elif self.__project_version is not None and self.__project_version in (FileStorageSystem.PROJECT_VERSION, 2):
            for item_d in properties.get("data_items", list()):
                data_item = DataItem.DataItem()
                data_item.begin_reading()
                data_item.read_from_dict(item_d)
                data_item.finish_reading()
                if not self.get_item_by_uuid("data_items", data_item.uuid):
                    self.load_item("data_items", len(self.data_items), data_item)
            for item_d in properties.get("display_items", list()):
                display_item = DisplayItem.DisplayItem()
                display_item.begin_reading()
                display_item.read_from_dict(item_d)
                display_item.finish_reading()
                if not self.get_item_by_uuid("display_items", display_item.uuid):
                    self.load_item("display_items", len(self.display_items), display_item)
            for item_d in properties.get("data_structures", list()):
                data_structure = DataStructure.DataStructure()
                data_structure.begin_reading()
                data_structure.read_from_dict(item_d)
                data_structure.finish_reading()
                if not self.get_item_by_uuid("data_structures", data_structure.uuid):
                    self.load_item("data_structures", len(self.data_structures), data_structure)
            for item_d in properties.get("computations", list()):
                computation = Symbolic.Computation()
                computation.begin_reading()
                computation.read_from_dict(item_d)
                computation.finish_reading()
                if not self.get_item_by_uuid("computations", computation.uuid):
                    self.load_item("computations", len(self.computations), computation)
                    # TODO: handle update script and bind after reload in document model
                    computation.update_script(self.container.container._processing_descriptions)
            for item_d in properties.get("connections", list()):
                connection = Connection.connection_factory(item_d.get)
                connection.begin_reading()
                connection.read_from_dict(item_d)
                connection.finish_reading()
                if not self.get_item_by_uuid("connections", connection.uuid):
                    self.load_item("connections", len(self.connections), connection)
            self.__project_state = "loaded"
        elif self.__project_version is not None:
            self.__project_state = "needs_upgrade"
        else:
            self.__project_state = "missing"

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
            assert get_project_for_item(data_item) == self
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

    def prune(self) -> None:
        self.__storage_system.prune()

    def migrate_to_latest(self) -> None:
        self.__storage_system.migrate_to_latest()
        self.__storage_system.load_properties()
        self.update_storage_system()  # reload the properties
        self.prepare_read_project()
        self.read_project()

    def unmount(self) -> None:
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


def data_item_factory(lookup_id):
    data_item_uuid = uuid.UUID(lookup_id("uuid"))
    large_format = lookup_id("__large_format", False)
    return DataItem.DataItem(item_uuid=data_item_uuid, large_format=large_format)


def display_item_factory(lookup_id):
    display_item_uuid = uuid.UUID(lookup_id("uuid"))
    return DisplayItem.DisplayItem(item_uuid=display_item_uuid)


def computation_factory(lookup_id):
    return Symbolic.Computation()


def data_structure_factory(lookup_id):
    return DataStructure.DataStructure()


def make_project(profile_context, project_reference: typing.Dict) -> typing.Optional[Project]:
    project_storage_system = FileStorageSystem.make_storage_system(profile_context, project_reference)
    if project_storage_system:
        project_storage_system.load_properties()
        return Project(project_storage_system, project_reference)
    else:
        logging.getLogger("loader").warning(f"Project could not be loaded {project_reference}.")
    return None


def get_project_for_item(item) -> typing.Optional[Project]:
    if item:
        if isinstance(item, Project):
            return item
        return get_project_for_item(item.container)
    return None
