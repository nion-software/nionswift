from __future__ import annotations

# standard libraries
import abc
import asyncio
import collections
import contextlib
import copy
import datetime
import functools
import gettext
import threading
import time
import typing
import uuid
import weakref

# local libraries
from nion.data import DataAndMetadata
from nion.swift.model import ApplicationData
from nion.swift.model import Cache
from nion.swift.model import Changes
from nion.swift.model import Connection
from nion.swift.model import Connector
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DataStructure
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import HardwareSource
from nion.swift.model import Observer
from nion.swift.model import PlugInManager
from nion.swift.model import Persistence
from nion.swift.model import Processing
from nion.swift.model import Project
from nion.swift.model import Symbolic
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import Observable
from nion.utils import Recorder
from nion.utils import ReferenceCounting
from nion.utils import Registry
from nion.utils import ThreadPool

_ = gettext.gettext

Processing.init()


def save_item_order(items: typing.List[Persistence.PersistentObject]) -> typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]:
    return [item.item_specifier for item in items]


def restore_item_order(project: Project.Project, uuid_order: typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]) -> typing.List[Persistence.PersistentObject]:
    items = list()
    for item_specifier in uuid_order:
        items.append(project.resolve_item_specifier(item_specifier))
    return items

def insert_item_order(uuid_order: typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]], index: int, item: Persistence.PersistentObject) -> None:
    uuid_order.insert(index, item.item_specifier)


class ComputationMerge:
    def __init__(self, computation: Symbolic.Computation, fn: typing.Optional[typing.Callable[[], None]] = None, closeables: typing.Optional[typing.List] = None):
        self.computation = computation
        self.fn = fn
        self.closeables = closeables or list()

    def close(self) -> None:
        for closeable in self.closeables:
            closeable.close()

    def exec(self) -> None:
        if callable(self.fn):
            self.fn()


class ComputationQueueItem:
    def __init__(self, *, computation=None):
        self.computation = computation
        self.valid = True

    def recompute(self) -> typing.Optional[ComputationMerge]:
        # evaluate the computation in a thread safe manner
        # returns a list of functions that must be called on the main thread to finish the recompute action
        # threadsafe
        pending_data_item_merge: typing.Optional[ComputationMerge] = None
        data_item = None
        computation = self.computation
        if computation.expression:
            data_item = computation.get_output("target")
        if computation and computation.needs_update:
            try:
                api = PlugInManager.api_broker_fn("~1.0", None)
                if not data_item:
                    start_time = time.perf_counter()
                    compute_obj, error_text = computation.evaluate(api)
                    eval_time = time.perf_counter() - start_time
                    if error_text and computation.error_text != error_text:
                        def update_error_text():
                            computation.error_text = error_text
                        pending_data_item_merge = ComputationMerge(computation, update_error_text)
                        return pending_data_item_merge
                    throttle_time = max(DocumentModel.computation_min_period - (time.perf_counter() - computation.last_evaluate_data_time), 0)
                    time.sleep(max(throttle_time, min(eval_time * DocumentModel.computation_min_factor, 1.0)))
                    if self.valid and compute_obj:  # TODO: race condition for 'valid'
                        pending_data_item_merge = ComputationMerge(computation, functools.partial(compute_obj.commit))
                    else:
                        pending_data_item_merge = ComputationMerge(computation)
                else:
                    start_time = time.perf_counter()
                    data_item_clone = data_item.clone()
                    data_item_data_modified = data_item.data_modified or datetime.datetime.min
                    data_item_clone_recorder = Recorder.Recorder(data_item_clone)
                    api_data_item = api._new_api_object(data_item_clone)
                    error_text = computation.evaluate_with_target(api, api_data_item)
                    eval_time = time.perf_counter() - start_time
                    throttle_time = max(DocumentModel.computation_min_period - (time.perf_counter() - computation.last_evaluate_data_time), 0)
                    time.sleep(max(throttle_time, min(eval_time * DocumentModel.computation_min_factor, 1.0)))
                    if self.valid:  # TODO: race condition for 'valid'
                        def data_item_merge(data_item, data_item_clone, data_item_clone_recorder):
                            # merge the result item clones back into the document. this method is guaranteed to run at
                            # periodic and shouldn't do anything too time consuming.
                            data_item_data_clone_modified = data_item_clone.data_modified or datetime.datetime.min
                            with data_item.data_item_changes(), data_item.data_source_changes():
                                if data_item_data_clone_modified > data_item_data_modified:
                                    data_item.set_xdata(api_data_item.data_and_metadata)
                                data_item_clone_recorder.apply(data_item)
                                if computation.error_text != error_text:
                                    computation.error_text = error_text
                        pending_data_item_merge = ComputationMerge(computation, functools.partial(data_item_merge, data_item, data_item_clone, data_item_clone_recorder), [data_item_clone, data_item_clone_recorder])
            except Exception as e:
                import traceback
                traceback.print_exc()
                # computation.error_text = _("Unable to compute data")
        return pending_data_item_merge


class Transaction:
    def __init__(self, transaction_manager: "TransactionManager", item, items):
        self.__transaction_manager = transaction_manager
        self.__item = item
        self.__items = items

    def close(self):
        self.__transaction_manager._close_transaction(self)
        self.__items = None
        self.__transaction_manager = None

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    @property
    def item(self):
        return self.__item

    @property
    def items(self):
        return copy.copy(self.__items)

    def replace_items(self, items):
        self.__items = items


class TransactionManager:
    def __init__(self, document_model: "DocumentModel"):
        self.__document_model = document_model
        self.__transactions_lock = threading.RLock()
        self.__transaction_counts = collections.Counter()
        self.__transactions = list()

    def close(self):
        self.__document_model = None
        self.__transaction_counts = None

    def is_in_transaction_state(self, item) -> bool:
        return self.__transaction_counts[item] > 0

    @property
    def transaction_count(self):
        return len(list(self.__transaction_counts.elements()))

    def item_transaction(self, item) -> Transaction:
        """Begin transaction state for item.

        A transaction state is exists to prevent writing out to disk, mainly for performance reasons.
        All changes to the object are delayed until the transaction state exits.

        This method is thread safe.
        """
        items = self.__build_transaction_items(item)
        transaction = Transaction(self, item, items)
        self.__transactions.append(transaction)
        return transaction

    def _close_transaction(self, transaction):
        items = transaction.items
        self.__close_transaction_items(items)
        self.__transactions.remove(transaction)

    def __build_transaction_items(self, item):
        items = set()
        self.__get_deep_transaction_item_set(item, items)
        with self.__transactions_lock:
            for item in items:
                old_count = self.__transaction_counts[item]
                self.__transaction_counts.update({item})
                if old_count == 0:
                    if callable(getattr(item, "_transaction_state_entered", None)):
                        item._transaction_state_entered()
        return items

    def __close_transaction_items(self, items):
        with self.__transactions_lock:
            for item in items:
                self.__transaction_counts.subtract({item})
                if self.__transaction_counts[item] == 0:
                    if callable(getattr(item, "_transaction_state_exited", None)):
                        item._transaction_state_exited()

    def __get_deep_transaction_item_set(self, item, items):
        if item and not item in items:
            # first the dependent items, also keep track of which items are added
            old_items = copy.copy(items)
            if not item in items:
                items.add(item)
                for dependent in self.__document_model.get_dependent_items(item):
                    self.__get_deep_transaction_item_set(dependent, items)
            if isinstance(item, DisplayItem.DisplayItem):
                for display_data_channel in item.display_data_channels:
                    self.__get_deep_transaction_item_set(display_data_channel, items)
                for display_layer in item.display_layers:
                    self.__get_deep_transaction_item_set(display_layer, items)
                for graphic in item.graphics:
                    self.__get_deep_transaction_item_set(graphic, items)
            if isinstance(item, DisplayItem.DisplayDataChannel):
                if item.data_item:
                    self.__get_deep_transaction_item_set(item.data_item, items)
            if isinstance(item, DisplayItem.DisplayLayer):
                if item.display_data_channel:
                    self.__get_deep_transaction_item_set(item.display_data_channel, items)
            if isinstance(item, DataItem.DataItem):
                for display_item in self.__document_model.get_display_items_for_data_item(item):
                    self.__get_deep_transaction_item_set(display_item, items)
            if isinstance(item, DataStructure.DataStructure):
                for referenced_object in item.referenced_objects:
                    self.__get_deep_transaction_item_set(referenced_object, items)
            if isinstance(item, Connection.Connection):
                self.__get_deep_transaction_item_set(item._source, items)
                self.__get_deep_transaction_item_set(item._target, items)
            for connection in self.__document_model.connections:
                if isinstance(connection, Connection.PropertyConnection) and connection._source in items:
                    self.__get_deep_transaction_item_set(connection._target, items)
                if isinstance(connection, Connection.PropertyConnection) and connection._target in items:
                    self.__get_deep_transaction_item_set(connection._source, items)
                if isinstance(connection, Connection.IntervalListConnection) and connection._source in items:
                    self.__get_deep_transaction_item_set(connection._target, items)
            for implicit_dependency in self.__document_model.implicit_dependencies:
                for implicit_item in implicit_dependency.get_dependents(item):
                    self.__get_deep_transaction_item_set(implicit_item, items)
            for item in items - old_items:
                if isinstance(item, Graphics.Graphic):
                    self.__get_deep_transaction_item_set(item.container, items)

    def _add_item(self, item):
        self._rebuild_transactions()

    def _remove_item(self, item):
        for transaction in copy.copy(self.__transactions):
            if transaction.item == item:
                self._close_transaction(transaction)
        self._rebuild_transactions()

    def _rebuild_transactions(self):
        for transaction in self.__transactions:
            old_items = transaction.items
            new_items = self.__build_transaction_items(transaction.item)
            transaction.replace_items(new_items)
            self.__close_transaction_items(old_items)


class UndeleteObjectSpecifier(Changes.UndeleteBase):

    def __init__(self, document_model: "DocumentModel", computation: Symbolic.Computation, index: int, variable_index: int, object_specifier: typing.Dict):
        self.computation_proxy = computation.create_proxy()
        self.variable_index = variable_index
        self.specifier = object_specifier
        self.index = index

    def close(self) -> None:
        self.computation_proxy.close()
        self.computation_proxy = None

    def undelete(self, document_model: "DocumentModel") -> None:
        computation = self.computation_proxy.item
        variable = computation.variables[self.variable_index]
        computation.undelete_variable_item(variable.name, self.index, self.specifier)


class UndeleteDataItem(Changes.UndeleteBase):

    def __init__(self, document_model: "DocumentModel", data_item: DataItem.DataItem):
        container = data_item.container
        index = container.data_items.index(data_item)
        uuid_order = save_item_order(document_model.data_items)
        self.data_item_uuid = data_item.uuid
        self.index = index
        self.order = uuid_order

    def close(self):
        pass

    def undelete(self, document_model: "DocumentModel") -> None:
        document_model.restore_data_item(self.data_item_uuid, self.index)
        document_model.restore_items_order("data_items", self.order)


class UndeleteDisplayItemInDataGroup(Changes.UndeleteBase):

    def __init__(self, document_model: "DocumentModel", display_item: DisplayItem.DisplayItem, data_group: DataGroup.DataGroup):
        self.display_item_proxy = display_item.create_proxy()
        self.data_group_proxy = data_group.create_proxy()
        self.index = data_group.display_items.index(display_item)

    def close(self) -> None:
        self.display_item_proxy.close()
        self.display_item_proxy = None
        self.data_group_proxy.close()
        self.data_group_proxy = None

    def undelete(self, document_model: "DocumentModel") -> None:
        display_item = self.display_item_proxy.item
        data_group = self.data_group_proxy.item
        data_group.insert_display_item(self.index, display_item)


class UndeleteDisplayItem(Changes.UndeleteBase):

    def __init__(self, document_model: "DocumentModel", display_item: DisplayItem.DisplayItem):
        container = display_item.container
        index = container.display_items.index(display_item)
        uuid_order = save_item_order(document_model.display_items)
        self.item_dict = display_item.write_to_dict()
        self.index = index
        self.order = uuid_order

    def close(self):
        pass

    def undelete(self, document_model: "DocumentModel") -> None:
        display_item = DisplayItem.DisplayItem()
        display_item.begin_reading()
        display_item.read_from_dict(self.item_dict)
        display_item.finish_reading()
        document_model.insert_display_item(self.index, display_item, update_session=False)
        document_model.restore_items_order("display_items", self.order)


class ItemsController(abc.ABC):

    @abc.abstractmethod
    def get_container(self, item: Persistence.PersistentObject) -> typing.Optional[Persistence.PersistentObject]: ...

    @abc.abstractmethod
    def item_index(self, item: Persistence.PersistentObject) -> int: ...

    @abc.abstractmethod
    def save_item_order(self) -> typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]: ...

    @abc.abstractmethod
    def write_to_dict(self, data_structure: Persistence.PersistentObject) -> typing.Dict: ...

    @abc.abstractmethod
    def restore_from_dict(self, item_dict: typing.Dict, index: int, container: typing.Optional[Persistence.PersistentObject], container_properties: typing.Tuple, order: typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]) -> None: ...


class DataStructuresController(ItemsController):
    def __init__(self, document_model: "DocumentModel"):
        self.__document_model = document_model

    def get_container(self, item: Persistence.PersistentObject) -> typing.Optional[Persistence.PersistentObject]:
        return None

    def item_index(self, data_structure: Persistence.PersistentObject) -> int:
        return data_structure.container.data_structures.index(data_structure)

    def save_item_order(self) -> typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]:
        return save_item_order(self.__document_model.data_structures)

    def write_to_dict(self, data_structure: Persistence.PersistentObject) -> typing.Dict:
        return data_structure.write_to_dict()

    def restore_from_dict(self, item_dict: typing.Dict, index: int, container: typing.Optional[Persistence.PersistentObject], container_properties: typing.Tuple, order: typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]) -> None:
        data_structure = DataStructure.DataStructure()
        data_structure.begin_reading()
        data_structure.read_from_dict(item_dict)
        data_structure.finish_reading()
        self.__document_model.insert_data_structure(index, data_structure)
        self.__document_model.restore_items_order("data_structures", order)


class ComputationsController(ItemsController):
    def __init__(self, document_model: "DocumentModel"):
        self.__document_model = document_model

    def get_container(self, item: Persistence.PersistentObject) -> typing.Optional[Persistence.PersistentObject]:
        return None

    def item_index(self, computation: Persistence.PersistentObject) -> int:
        return computation.container.computations.index(computation)

    def save_item_order(self) -> typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]:
        return save_item_order(self.__document_model.computations)

    def write_to_dict(self, computation: Persistence.PersistentObject) -> typing.Dict:
        return computation.write_to_dict()

    def restore_from_dict(self, item_dict: typing.Dict, index: int, container: typing.Optional[Persistence.PersistentObject], container_properties: typing.Tuple, order: typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]) -> None:
        computation = Symbolic.Computation()
        computation.begin_reading()
        computation.read_from_dict(item_dict)
        computation.finish_reading()
        # if the computation is not resolved, then undelete may require additional items to make it
        # resolved. so mark it as needing update here. this is a hack.
        computation.needs_update = not computation.is_resolved
        self.__document_model.insert_computation(index, computation)
        self.__document_model.restore_items_order("computations", order)


class ConnectionsController(ItemsController):
    def __init__(self, document_model: "DocumentModel"):
        self.__document_model = document_model

    def get_container(self, item: Persistence.PersistentObject) -> typing.Optional[Persistence.PersistentObject]:
        return None

    def item_index(self, connection: Persistence.PersistentObject) -> int:
        return connection.container.connections.index(connection)

    def save_item_order(self) -> typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]:
        return save_item_order(self.__document_model.connections)

    def write_to_dict(self, connection: Persistence.PersistentObject) -> typing.Dict:
        return connection.write_to_dict()

    def restore_from_dict(self, item_dict: typing.Dict, index: int, container: typing.Optional[Persistence.PersistentObject], container_properties: typing.Tuple, order: typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]) -> None:
        item = Connection.connection_factory(item_dict.get)
        item.begin_reading()
        item.read_from_dict(item_dict)
        item.finish_reading()
        self.__document_model.insert_connection(index, item)
        self.__document_model.restore_items_order("connections", order)


class GraphicsController(ItemsController):
    def __init__(self, document_model: "DocumentModel"):
        self.__document_model = document_model

    def get_container(self, item: Persistence.PersistentObject) -> typing.Optional[Persistence.PersistentObject]:
        return item.container

    def item_index(self, graphic: Persistence.PersistentObject) -> int:
        return graphic.container.graphics.index(graphic)

    def save_item_order(self) -> typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]:
        return list()

    def write_to_dict(self, graphic: Persistence.PersistentObject) -> typing.Dict:
        return graphic.write_to_dict()

    def restore_from_dict(self, item_dict: typing.Dict, index: int, container: typing.Optional[Persistence.PersistentObject], container_properties: typing.Tuple, order: typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]) -> None:
        graphic = Graphics.factory(item_dict.get)
        graphic.begin_reading()
        graphic.read_from_dict(item_dict)
        graphic.finish_reading()
        display_item = typing.cast(DisplayItem.DisplayItem, container)
        display_item.insert_graphic(index, graphic)
        display_item.restore_properties(container_properties)


class DisplayDataChannelsController(ItemsController):
    def __init__(self, document_model: "DocumentModel"):
        self.__document_model = document_model

    def get_container(self, item: Persistence.PersistentObject) -> typing.Optional[Persistence.PersistentObject]:
        return item.container

    def item_index(self, display_data_channel: Persistence.PersistentObject) -> int:
        return display_data_channel.container.display_data_channels.index(display_data_channel)

    def save_item_order(self) -> typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]:
        return list()

    def write_to_dict(self, display_data_channel: Persistence.PersistentObject) -> typing.Dict:
        return display_data_channel.write_to_dict()

    def restore_from_dict(self, item_dict: typing.Dict, index: int, container: typing.Optional[Persistence.PersistentObject], container_properties: typing.Tuple, order: typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]) -> None:
        display_data_channel = DisplayItem.display_data_channel_factory(item_dict.get)
        display_data_channel.begin_reading()
        display_data_channel.read_from_dict(item_dict)
        display_data_channel.finish_reading()
        display_item = typing.cast(DisplayItem.DisplayItem, container)
        display_item.undelete_display_data_channel(index, display_data_channel)
        display_item.restore_properties(container_properties)


class DisplayLayersController(ItemsController):
    def __init__(self, document_model: "DocumentModel"):
        self.__document_model = document_model

    def get_container(self, item: Persistence.PersistentObject) -> typing.Optional[Persistence.PersistentObject]:
        return item.container

    def item_index(self, display_layer: Persistence.PersistentObject) -> int:
        return display_layer.container.display_layers.index(display_layer)

    def save_item_order(self) -> typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]:
        return list()

    def write_to_dict(self, display_layer: Persistence.PersistentObject) -> typing.Dict:
        return display_layer.write_to_dict()

    def restore_from_dict(self, item_dict: typing.Dict, index: int, container: typing.Optional[Persistence.PersistentObject], container_properties: typing.Tuple, order: typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]) -> None:
        display_layer = DisplayItem.display_layer_factory(item_dict.get)
        display_layer.begin_reading()
        display_layer.read_from_dict(item_dict)
        display_layer.finish_reading()
        display_item = typing.cast(DisplayItem.DisplayItem, container)
        display_item.undelete_display_layer(index, display_layer)
        display_item.restore_properties(container_properties)


class UndeleteItem(Changes.UndeleteBase):

    def __init__(self, items_controller: ItemsController, item: Persistence.PersistentObject):
        self.__items_controller = items_controller
        container = self.__items_controller.get_container(item)
        index = self.__items_controller.item_index(item)
        self.container_item_proxy = container.create_proxy() if container else None
        self.container_properties = container.save_properties() if hasattr(container, "save_properties") else dict()
        self.item_dict = self.__items_controller.write_to_dict(item)
        self.index = index
        self.order = self.__items_controller.save_item_order()

    def close(self) -> None:
        if self.container_item_proxy:
            self.container_item_proxy.close()
            self.container_item_proxy = None

    def undelete(self, document_model: "DocumentModel") -> None:
        container = typing.cast(Persistence.PersistentObject, self.container_item_proxy.item) if self.container_item_proxy else None
        container_properties = self.container_properties
        self.__items_controller.restore_from_dict(self.item_dict, self.index, container, container_properties, self.order)


class AbstractImplicitDependency(abc.ABC):

    @abc.abstractmethod
    def get_dependents(self, item) -> typing.Sequence: ...


class ImplicitDependency(AbstractImplicitDependency):

    def __init__(self, items: typing.Sequence, item):
        self.__item = item
        self.__items = items

    def get_dependents(self, item) -> typing.Sequence:
        return [self.__item] if item in self.__items else list()


class MappedItemManager(metaclass=Registry.Singleton):

    def __init__(self):
        self.__item_map = dict()
        self.__item_listener_map = dict()
        self.__document_map = dict()
        self.changed_event = Event.Event()

    def register(self, document_model: DocumentModel, item: Persistence.PersistentObject) -> str:
        for r in range(1, 1000000):
            r_var = f"r{r:02d}"
            if not r_var in self.__item_map:
                self.__item_map[r_var] = item
                self.__document_map.setdefault(document_model, set()).add(r_var)

                def remove_item():
                    self.__item_map.pop(r_var)
                    self.__item_listener_map.pop(r_var).close()
                    self.__document_map.setdefault(document_model, set()).remove(r_var)
                    self.changed_event.fire()

                self.__item_listener_map[r_var] = item.about_to_be_removed_event.listen(remove_item)
                self.changed_event.fire()

                return r_var
        return str()

    def unregister_document(self, document_model: DocumentModel) -> None:
        r_vars = self.__document_map.pop(document_model, set())
        for r_var in r_vars:
            self.__item_map.pop(r_var, None)
            self.__item_listener_map.pop(r_var).close()
        self.changed_event.fire()

    @property
    def item_map(self) -> typing.Mapping[str, Persistence.PersistentObject]:
        return dict(self.__item_map)

    def get_item_r_var(self, item: Persistence.PersistentObject) -> typing.Optional[str]:
        for k, v in self.__item_map.items():
            if v == item:
                return k
        return None


class DocumentModel(Observable.Observable, ReferenceCounting.ReferenceCounted, DataItem.SessionManager):
    """Manages storage and dependencies between data items and other objects.

    The document model provides a dispatcher object which will run tasks in a thread pool.
    """
    count = 0  # useful for detecting leaks in tests

    computation_min_period = 0.0
    computation_min_factor = 0.0

    def __init__(self, project: Project.Project, *, storage_cache = None):
        super().__init__()
        self.__class__.count += 1

        self.about_to_close_event = Event.Event()

        self.data_item_will_be_removed_event = Event.Event()  # will be called before the item is deleted

        self.dependency_added_event = Event.Event()
        self.dependency_removed_event = Event.Event()
        self.related_items_changed = Event.Event()

        self.computation_updated_event = Event.Event()

        self.__computation_thread_pool = ThreadPool.ThreadPool()

        self.__project = project

        self.uuid = self._project.uuid

        project.handle_start_read = self.__start_project_read
        project.handle_insert_model_item = self.insert_model_item
        project.handle_remove_model_item = self.remove_model_item
        project.handle_finish_read = self.__finish_project_read

        self.__project_item_inserted_listener = project.item_inserted_event.listen(self.__project_item_inserted)
        self.__project_item_removed_listener = project.item_removed_event.listen(self.__project_item_removed)
        self.__project_property_changed_listener = project.property_changed_event.listen(self.__project_property_changed)

        self.storage_cache = storage_cache
        self.__storage_cache = None  # needed to deallocate
        if not storage_cache:
            self.__storage_cache = Cache.DictStorageCache()
            self.storage_cache = self.__storage_cache
        self.__transaction_manager = TransactionManager(self)
        self.__data_structure_listeners = dict()
        self.__live_data_items_lock = threading.RLock()
        self.__live_data_items = dict()
        self.__dependency_tree_lock = threading.RLock()
        self.__dependency_tree_source_to_target_map = dict()
        self.__dependency_tree_target_to_source_map = dict()
        self.__computation_changed_listeners = dict()
        self.__computation_output_changed_listeners = dict()
        self.__computation_changed_delay_list = None
        self.__data_item_references = dict()
        self.__computation_queue_lock = threading.RLock()
        self.__computation_pending_queue = list()  # type: typing.List[ComputationQueueItem]
        self.__computation_active_item = None  # type: typing.Optional[ComputationQueueItem]
        self.__data_items = list()
        self.__display_items = list()
        self.__data_structures = list()
        self.__computations = list()
        self.__connections = list()
        self.__display_item_item_inserted_listeners = dict()
        self.__display_item_item_removed_listeners = dict()
        self.__data_items_to_append_lock = threading.RLock()
        self.__data_items_to_append: typing.List[typing.Tuple[str, DataItem.DataItem]] = list()
        self.session_id = None
        self.start_new_session()
        self.__prune()

        for data_group in self.data_groups:
            data_group.connect_display_items(self.__resolve_display_item_specifier)

        self.__data_channel_updated_listeners = dict()
        self.__data_channel_start_listeners = dict()
        self.__data_channel_stop_listeners = dict()
        self.__data_channel_states_updated_listeners = dict()
        self.__last_data_items_dict = dict()  # maps hardware source to list of data items for that hardware source

        self.__hardware_source_call_soon_event_listeners = dict()

        self.__pending_data_item_updates_lock = threading.RLock()
        self.__pending_data_item_updates = list()

        self.__pending_data_item_merge_lock = threading.RLock()
        self.__pending_data_item_merge = None
        self.__current_computation = None

        self.__call_soon_queue = list()
        self.__call_soon_queue_lock = threading.RLock()

        self.call_soon_event = Event.Event()

        self.__hardware_source_added_event_listener = HardwareSource.HardwareSourceManager().hardware_source_added_event.listen(self.__hardware_source_added)
        self.__hardware_source_removed_event_listener = HardwareSource.HardwareSourceManager().hardware_source_removed_event.listen(self.__hardware_source_removed)

        for hardware_source in HardwareSource.HardwareSourceManager().hardware_sources:
            self.__hardware_source_added(hardware_source)

        # the implicit connections watch for computations matching specific criteria and then set up
        # connections between inputs/outputs of the computation. for instance, when the user changes
        # the display interval on a line profile resulting from a pick-style operation, it can be
        # linked to the slice interval on the collection of 1D data from which the pick was computed.
        # in addition, the implicit connections track implicit dependencies - this is helpful so that
        # when dragging the interval on the line plot, the source data is treated as under transaction
        # which dramatically improves performance during dragging.
        self.__implicit_dependencies = list()
        self.__implicit_map_connection = ImplicitMapConnection(self)
        self.__implicit_pick_connection = ImplicitPickConnection(self)
        self.__implicit_line_profile_intervals_connection = ImplicitLineProfileIntervalsConnection(self)

        for index, item in enumerate(self.__project.data_items):
            self.__project_item_inserted("data_items", item, index)
        for index, item in enumerate(self.__project.display_items):
            self.__project_item_inserted("display_items", item, index)
        for index, item in enumerate(self.__project.data_structures):
            self.__project_item_inserted("data_structures", item, index)
        for index, item in enumerate(self.__project.computations):
            self.__project_item_inserted("computations", item, index)
        for index, item in enumerate(self.__project.connections):
            self.__project_item_inserted("connections", item, index)
        for index, item in enumerate(self.__project.data_groups):
            self.__project_item_inserted("data_groups", item, index)

    def __resolve_display_item_specifier(self, display_item_specifier_d: typing.Dict) -> typing.Optional[DisplayItem.DisplayItem]:
        display_item_specifier = Persistence.PersistentObjectSpecifier.read(display_item_specifier_d)
        return typing.cast(typing.Optional[DisplayItem.DisplayItem], self.resolve_item_specifier(display_item_specifier))

    def __resolve_mapped_items(self):
        # handle the reference variable assignments
        for mapped_item in self._project.mapped_items:
            item_proxy = self._project.create_item_proxy(
                item_specifier=Persistence.PersistentObjectSpecifier.read(mapped_item))
            with contextlib.closing(item_proxy):
                if isinstance(item_proxy.item, DisplayItem.DisplayItem):
                    display_item = typing.cast(Persistence.PersistentObject, item_proxy.item)
                    if not display_item in MappedItemManager().item_map.values():
                        MappedItemManager().register(self, item_proxy.item)

    def __resolve_data_item_references(self):
        # update the data item references
        data_item_references = self._project.data_item_references
        for key, data_item_specifier in data_item_references.items():
            persistent_object_specifier = Persistence.PersistentObjectSpecifier.read(data_item_specifier)
            if key in self.__data_item_references:
                self.__data_item_references[key].set_data_item_specifier(self._project, persistent_object_specifier)
            else:
                self.__data_item_references.setdefault(key, DocumentModel.DataItemReference(self, key, self._project, persistent_object_specifier))

    def __prune(self):
        self._project.prune()

    def close(self):
        with self.__call_soon_queue_lock:
            self.__call_soon_queue = list()

        # notify listeners
        self.about_to_close_event.fire()

        # stop computations
        with self.__computation_queue_lock:
            self.__computation_pending_queue.clear()
            if self.__computation_active_item:
                self.__computation_active_item.valid = False
                self.__computation_active_item = None

        with self.__pending_data_item_merge_lock:
            if self.__pending_data_item_merge:
                self.__pending_data_item_merge.close()
            self.__pending_data_item_merge = None

        # close data items left to append that haven't been appended
        with self.__data_items_to_append_lock:
            for key, data_item in self.__data_items_to_append:
                data_item.close()

        # r_vars
        MappedItemManager().unregister_document(self)

        # close implicit connections
        self.__implicit_map_connection.close()
        self.__implicit_map_connection = None
        self.__implicit_pick_connection.close()
        self.__implicit_pick_connection = None
        self.__implicit_line_profile_intervals_connection.close()
        self.__implicit_line_profile_intervals_connection = None

        # close hardware source related stuff
        self.__hardware_source_added_event_listener.close()
        self.__hardware_source_added_event_listener = None
        self.__hardware_source_removed_event_listener.close()
        self.__hardware_source_removed_event_listener = None
        for listener in self.__data_channel_states_updated_listeners.values():
            listener.close()
        self.__data_channel_states_updated_listeners = None
        # TODO: close other listeners here too
        HardwareSource.HardwareSourceManager().abort_all_and_close()

        # make sure the data item references shut down cleanly
        for data_item_reference in self.__data_item_references.values():
            data_item_reference.close()
        self.__data_item_references = None

        for listeners in self.__data_channel_updated_listeners.values():
            for listener in listeners:
                listener.close()
        for listeners in self.__data_channel_start_listeners.values():
            for listener in listeners:
                listener.close()
        for listeners in self.__data_channel_stop_listeners.values():
            for listener in listeners:
                listener.close()
        self.__data_channel_updated_listeners = None
        self.__data_channel_start_listeners = None
        self.__data_channel_stop_listeners = None

        if self.__storage_cache:
            self.__storage_cache.close()
            self.__storage_cache = None

        self.__computation_thread_pool.close()
        self.__transaction_manager.close()
        self.__transaction_manager = None

        for display_item in self.__display_items:
            self.__display_item_item_inserted_listeners.pop(display_item).close()
            self.__display_item_item_removed_listeners.pop(display_item).close()

        if self.__project_item_inserted_listener:
            self.__project_item_inserted_listener.close()
            self.__project_item_inserted_listener = None

        if self.__project_item_removed_listener:
            self.__project_item_removed_listener.close()
            self.__project_item_removed_listener = None

        if self.__project_property_changed_listener:
            self.__project_property_changed_listener.close()
            self.__project_property_changed_listener = None

        for computation in self.__computations:
            computation_changed_listener = self.__computation_changed_listeners.pop(computation, None)
            if computation_changed_listener: computation_changed_listener.close()
            computation_output_changed_listener = self.__computation_output_changed_listeners.pop(computation, None)
            if computation_output_changed_listener: computation_output_changed_listener.close()

        self.__project.persistent_object_context = None
        self.__project.close()
        self.__project = None
        self.__class__.count -= 1

    def __call_soon(self, fn):
        # add the function to the queue of items to call on the main thread.
        # use a queue here in case it is called before the listener is configured,
        # as is the case as the document loads.
        with self.__call_soon_queue_lock:
            self.__call_soon_queue.append(fn)
        self.call_soon_event.fire_any()

    def perform_call_soon(self):
        # call one function in the call soon queue
        fn = None
        with self.__call_soon_queue_lock:
            if self.__call_soon_queue:
                fn = self.__call_soon_queue.pop(0)
        if fn:
            fn()

    def perform_all_call_soon(self):
        # call all functions in the call soon queue
        with self.__call_soon_queue_lock:
            call_soon_queue = self.__call_soon_queue
            self.__call_soon_queue = list()
        for fn in call_soon_queue:
            fn()

    def about_to_delete(self):
        # override from ReferenceCounted. several DocumentControllers may retain references
        self.close()

    def __project_item_inserted(self, name: str, item, before_index: int) -> None:
        if name == "data_items":
            self.__handle_data_item_inserted(item)
        elif name == "display_items":
            self.__handle_display_item_inserted(item)
        elif name == "data_structures":
            self.__handle_data_structure_inserted(item)
        elif name == "computations":
            self.__handle_computation_inserted(item)
        elif name == "connections":
            self.__handle_connection_inserted(item)
        elif name == "data_groups":
            self.notify_insert_item("data_groups", item, before_index)
            item.connect_display_items(self.__resolve_display_item_specifier)

    def __project_item_removed(self, name: str, item, index: int) -> None:
        if name == "data_items":
            self.__handle_data_item_removed(item)
        elif name == "display_items":
            self.__handle_display_item_removed(item)
        elif name == "data_structures":
            self.__handle_data_structure_removed(item)
        elif name == "computations":
            self.__handle_computation_removed(item)
        elif name == "connections":
            self.__handle_connection_removed(item)
        elif name == "data_groups":
            item.disconnect_display_items()
            self.notify_remove_item("data_groups", item, index)

    def __project_property_changed(self, name: str) -> None:
        if name == "data_item_references":
            self.__resolve_data_item_references()
        if name == "mapped_items":
            self.__resolve_mapped_items()

    def create_item_proxy(self, *, item_uuid: uuid.UUID = None, item_specifier: Persistence.PersistentObjectSpecifier = None, item: Persistence.PersistentObject = None) -> Persistence.PersistentObjectProxy:
        # returns item proxy in projects. used in data group hierarchy.
        return self._project.create_item_proxy(item_uuid=item_uuid, item_specifier=item_specifier, item=item)

    def resolve_item_specifier(self, item_specifier: Persistence.PersistentObjectSpecifier) -> Persistence.PersistentObject:
        return self._project.resolve_item_specifier(item_specifier)

    @property
    def modified_state(self) -> int:
        return self._project.modified_state

    @modified_state.setter
    def modified_state(self, value: int) -> None:
        self._project.modified_state = value

    @property
    def data_items(self) -> typing.List[DataItem.DataItem]:
        return self.__data_items

    @property
    def display_items(self) -> typing.List[DisplayItem.DisplayItem]:
        return self.__display_items

    @property
    def data_structures(self) -> typing.List[DataStructure.DataStructure]:
        return self.__data_structures

    @property
    def computations(self) -> typing.List[Symbolic.Computation]:
        return self.__computations

    @property
    def connections(self) -> typing.List[Connection.Connection]:
        return self.__connections

    @property
    def _project(self) -> Project.Project:
        return self.__project

    @property
    def implicit_dependencies(self):
        return self.__implicit_dependencies

    def register_implicit_dependency(self, implicit_dependency: AbstractImplicitDependency):
        self.__implicit_dependencies.append(implicit_dependency)

    def unregister_implicit_dependency(self, implicit_dependency: AbstractImplicitDependency):
        self.__implicit_dependencies.remove(implicit_dependency)

    def start_new_session(self):
        self.session_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    @property
    def current_session_id(self):
        return self.session_id

    def copy_data_item(self, data_item: DataItem.DataItem) -> DataItem.DataItem:
        computation_copy = copy.deepcopy(self.get_data_item_computation(data_item))
        data_item_copy = copy.deepcopy(data_item)
        self.append_data_item(data_item_copy)
        if computation_copy:
            computation_copy.source = None
            computation_copy._clear_referenced_object("target")
            self.set_data_item_computation(data_item_copy, computation_copy)
        return data_item_copy

    def __handle_data_item_inserted(self, data_item: DataItem.DataItem) -> None:
        assert data_item is not None
        assert data_item not in self.data_items
        # data item bookkeeping
        data_item.set_storage_cache(self.storage_cache)
        # insert in internal list
        before_index = len(self.__data_items)
        self.__data_items.append(data_item)
        data_item._document_model = self
        data_item.set_session_manager(self)
        self.notify_insert_item("data_items", data_item, before_index)
        self.__transaction_manager._add_item(data_item)

    def __handle_data_item_removed(self, data_item: DataItem.DataItem) -> None:
        self.__transaction_manager._remove_item(data_item)
        library_computation = self.get_data_item_computation(data_item)
        with self.__computation_queue_lock:
            computation_pending_queue = self.__computation_pending_queue
            self.__computation_pending_queue = list()
            for computation_queue_item in computation_pending_queue:
                if not computation_queue_item.computation is library_computation:
                    self.__computation_pending_queue.append(computation_queue_item)
            if self.__computation_active_item and library_computation is self.__computation_active_item.computation:
                self.__computation_active_item.valid = False
        # remove data item from any selections
        self.data_item_will_be_removed_event.fire(data_item)
        # remove it from the persistent_storage
        data_item._document_model = None
        assert data_item is not None
        assert data_item in self.data_items
        index = self.data_items.index(data_item)
        self.__data_items.remove(data_item)
        self.notify_remove_item("data_items", data_item, index)

    def append_data_item(self, data_item: DataItem.DataItem, auto_display: bool = True) -> None:
        data_item.session_id = self.session_id
        self._project.append_data_item(data_item)
        # automatically add a display
        if auto_display:
            display_item = DisplayItem.DisplayItem(data_item=data_item)
            self.append_display_item(display_item)

    def insert_data_item(self, index: int, data_item: DataItem.DataItem, auto_display: bool = True) -> None:
        uuid_order = save_item_order(self.__data_items)
        self.append_data_item(data_item, auto_display=auto_display)
        insert_item_order(uuid_order, index, data_item)
        self.__data_items = restore_item_order(self._project, uuid_order)

    def remove_data_item(self, data_item: DataItem.DataItem, *, safe: bool=False) -> None:
        self.__cascade_delete(data_item, safe=safe).close()

    def remove_data_item_with_log(self, data_item: DataItem.DataItem, *, safe: bool=False) -> Changes.UndeleteLog:
        return self.__cascade_delete(data_item, safe=safe)

    def restore_data_item(self, data_item_uuid: uuid.UUID, before_index: int=None) -> typing.Optional[DataItem.DataItem]:
        return self._project.restore_data_item(data_item_uuid)

    def restore_items_order(self, name: str, order: typing.List[typing.Tuple[Project.Project, Persistence.PersistentObject]]) -> None:
        if name == "data_items":
            self.__data_items = restore_item_order(self._project, order)
        elif name == "display_items":
            self.__display_items = restore_item_order(self._project, order)
        elif name == "data_strutures":
            self.__data_structures = restore_item_order(self._project, order)
        elif name == "computations":
            self.__computations = restore_item_order(self._project, order)
        elif name == "connections":
            self.__connections = restore_item_order(self._project, order)

    def deepcopy_display_item(self, display_item: DisplayItem.DisplayItem) -> DisplayItem.DisplayItem:
        display_item_copy = copy.deepcopy(display_item)
        data_item_copies = list()
        for data_item in display_item.data_items:
            if data_item:
                data_item_copy = copy.deepcopy(data_item)
                self.append_data_item(data_item_copy, False)
                data_item_copies.append(data_item_copy)
            else:
                data_item_copies.append(None)
        for display_data_channel in copy.copy(display_item_copy.display_data_channels):
            display_item_copy.remove_display_data_channel(display_data_channel).close()
        for data_item_copy, display_data_channel in zip(data_item_copies, display_item.display_data_channels):
            display_data_channel_copy = DisplayItem.DisplayDataChannel(data_item=data_item_copy)
            display_data_channel_copy.copy_display_data_properties_from(display_data_channel)
            display_item_copy.append_display_data_channel(display_data_channel_copy)
        for display_layer in copy.copy(display_item_copy.display_layers):
            display_item_copy.remove_display_layer(display_layer).close()
        for i in range(len(display_item.display_layers)):
            data_index = display_item.display_data_channels.index(display_item.get_display_layer_display_data_channel(i))
            display_item_copy.add_display_layer_for_display_data_channel(display_item_copy.display_data_channels[data_index], **display_item.get_display_layer_properties(i))
        self.append_display_item(display_item_copy)
        return display_item_copy

    def append_display_item(self, display_item: DisplayItem.DisplayItem, *, update_session: bool = True) -> None:
        if update_session:
            display_item.session_id = self.session_id
        self._project.append_display_item(display_item)

    def insert_display_item(self, before_index: int, display_item: DisplayItem.DisplayItem, *, update_session: bool = True) -> None:
        uuid_order = save_item_order(self.__display_items)
        self.append_display_item(display_item, update_session=update_session)
        insert_item_order(uuid_order, before_index, display_item)
        self.__display_items = restore_item_order(self._project, uuid_order)

    def remove_display_item(self, display_item) -> None:
        self.__cascade_delete(display_item).close()

    def remove_display_item_with_log(self, display_item) -> Changes.UndeleteLog:
        return self.__cascade_delete(display_item)

    def __handle_display_item_inserted(self, display_item: DisplayItem.DisplayItem) -> None:
        assert display_item is not None
        assert display_item not in self.__display_items
        # data item bookkeeping
        display_item.set_storage_cache(self.storage_cache)
        # insert in internal list
        before_index = len(self.__display_items)
        self.__display_items.append(display_item)

        def item_changed(display_item: DisplayItem.DisplayItem, name: str, value, index: int) -> None:
            # pass display item because display data channel might be being removed in which case it will have no container.
            if name == "display_data_channels":
                # handle cases where a display data channel is added or removed.
                # update the related items. this is a blunt approach - they may not
                # have changed, but a display update is relatively cheap.
                assert display_item
                source_display_items = self.get_source_display_items(display_item) if display_item else list()
                dependent_display_items = self.get_dependent_display_items(display_item) if display_item else list()
                self.related_items_changed.fire(display_item, source_display_items, dependent_display_items)
        self.__display_item_item_inserted_listeners[display_item] = display_item.item_inserted_event.listen(functools.partial(item_changed, display_item))
        self.__display_item_item_removed_listeners[display_item] = display_item.item_removed_event.listen(functools.partial(item_changed, display_item))
        # send notifications
        self.notify_insert_item("display_items", display_item, before_index)

    def __handle_display_item_removed(self, display_item: DisplayItem.DisplayItem) -> None:
        # remove it from the persistent_storage
        assert display_item is not None
        assert display_item in self.__display_items
        index = self.__display_items.index(display_item)
        self.notify_remove_item("display_items", display_item, index)
        self.__display_items.remove(display_item)
        self.__display_item_item_inserted_listeners.pop(display_item).close()
        self.__display_item_item_removed_listeners.pop(display_item).close()

    def __start_project_read(self) -> None:
        pass

    def __finish_project_read(self) -> None:
        # clean the display items for each data channel
        for hardware_source in HardwareSource.HardwareSourceManager().hardware_sources:
            for data_channel in hardware_source.data_channels:
                data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, data_channel.channel_id))
                data_item = data_item_reference.data_item
                if data_item:
                    hardware_source.clean_display_items(self, list(self.get_display_items_for_data_item(data_item)))

    def insert_model_item(self, container, name, before_index, item):
        container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> Changes.UndeleteLog:
        return self.__cascade_delete(item, safe=safe)

    def assign_variable_to_display_item(self, display_item: DisplayItem.DisplayItem) -> str:
        r_var = MappedItemManager().get_item_r_var(display_item)
        if not r_var:
            r_var = MappedItemManager().register(self, display_item)
            mapped_items = self._project.mapped_items
            mapped_items.append(display_item.project.create_specifier(display_item).write())
            self._project.mapped_items = mapped_items
        return r_var

    def __build_cascade(self, item, items: list, dependencies: list) -> None:
        # build a list of items to delete using item as the base. put the leafs at the end of the list.
        # store associated dependencies in the form source -> target into dependencies.
        # print(f"build {item}")
        if item not in items:
            # first handle the case where a data item that is the only target of a graphic cascades to the graphic.
            # this is the only case where a target causes a source to be deleted.
            items.append(item)
            sources = self.__dependency_tree_target_to_source_map.get(weakref.ref(item), list())
            if isinstance(item, DataItem.DataItem):
                for source in sources:
                    if isinstance(source, Graphics.Graphic):
                        source_targets = self.__dependency_tree_source_to_target_map.get(weakref.ref(source), list())
                        if len(source_targets) == 1 and source_targets[0] == item:
                            self.__build_cascade(source, items, dependencies)
                # delete display items whose only data item is being deleted
                for display_item in self.get_display_items_for_data_item(item):
                    display_item_alive = False
                    for display_data_channel in display_item.display_data_channels:
                        if display_data_channel.data_item == item:
                            self.__build_cascade(display_data_channel, items, dependencies)
                        elif not display_data_channel.data_item in items:
                            display_item_alive = True
                    if not display_item_alive:
                        self.__build_cascade(display_item, items, dependencies)
            elif isinstance(item, DisplayItem.DisplayItem):
                # graphics on a display item are deleted.
                for graphic in item.graphics:
                    self.__build_cascade(graphic, items, dependencies)
                # display data channels are deleted.
                for display_data_channel in item.display_data_channels:
                    self.__build_cascade(display_data_channel, items, dependencies)
                # delete data items whose only display item is being deleted
                for data_item in item.data_items:
                    if data_item and len(self.get_display_items_for_data_item(data_item)) == 1:
                        self.__build_cascade(data_item, items, dependencies)
            elif isinstance(item, DisplayItem.DisplayDataChannel):
                # delete data items whose only display item channel is being deleted
                display_item = typing.cast(DisplayItem.DisplayItem, item.container)
                data_item = typing.cast(typing.Optional[DataItem.DataItem], item.data_item)
                if data_item and len(self.get_display_items_for_data_item(data_item)) == 1:
                    display_data_channels_referring_to_data_item = 0
                    # only delete data item if it is used by only the one display data channel being deleted
                    for display_data_channel in display_item.display_data_channels:
                        if display_data_channel.data_item == data_item:
                            display_data_channels_referring_to_data_item += 1
                    if display_data_channels_referring_to_data_item == 1:
                        self.__build_cascade(data_item, items, dependencies)
                for display_layer in display_item.display_layers:
                    if display_layer.display_data_channel == item:
                        self.__build_cascade(display_layer, items, dependencies)
            elif isinstance(item, DisplayItem.DisplayLayer):
                # delete display data channels whose only referencing display layer is being deleted
                display_layer = typing.cast(DisplayItem.DisplayLayer, item)
                display_data_channel = display_layer.display_data_channel
                display_item = typing.cast(DisplayItem.DisplayItem, item.container)
                reference_count = display_item.get_display_data_channel_layer_use_count(display_layer.display_data_channel)
                if reference_count == 1:
                    self.__build_cascade(display_data_channel, items, dependencies)
            # outputs of a computation are deleted.
            elif isinstance(item, Symbolic.Computation):
                for output in item._outputs:
                    self.__build_cascade(output, items, dependencies)
            # dependencies are deleted
            # in order to be able to have finer control over how dependencies of input lists are handled,
            # enumerate the computations and match up dependencies instead of using the dependency tree.
            # this could obviously be optimized.
            if not isinstance(item, Symbolic.Computation):
                for computation in self.computations:
                    base_objects = set(computation.direct_input_items)
                    if item in base_objects:
                        targets = computation._outputs
                        for target in targets:
                            if (item, target) not in dependencies:
                                dependencies.append((item, target))
                            self.__build_cascade(target, items, dependencies)
            # dependencies are deleted
            # see note above
            # targets = self.__dependency_tree_source_to_target_map.get(weakref.ref(item), list())
            # for target in targets:
            #     if (item, target) not in dependencies:
            #         dependencies.append((item, target))
            #     self.__build_cascade(target, items, dependencies)
            # data items whose source is the item are deleted
            for data_item in self.data_items:
                if data_item.source == item:
                    if (item, data_item) not in dependencies:
                        dependencies.append((item, data_item))
                    self.__build_cascade(data_item, items, dependencies)
            # display items whose source is the item are deleted
            for display_item in self.display_items:
                pass
                # if display_item.source == item:
                #     if (item, display_item) not in dependencies:
                #         dependencies.append((item, display_item))
                #     self.__build_cascade(display_item, items, dependencies)
            # graphics whose source is the item are deleted
            for display_item in self.display_items:
                for graphic in display_item.graphics:
                    if graphic.source == item:
                        if (item, graphic) not in dependencies:
                            dependencies.append((item, graphic))
                        self.__build_cascade(graphic, items, dependencies)
            # connections whose source is the item are deleted
            for connection in self.connections:
                if connection.parent == item:
                    if (item, connection) not in dependencies:
                        dependencies.append((item, connection))
                    self.__build_cascade(connection, items, dependencies)
            # data structures whose source is the item are deleted
            for data_structure in self.data_structures:
                if data_structure.source == item:
                    if (item, data_structure) not in dependencies:
                        dependencies.append((item, data_structure))
                    self.__build_cascade(data_structure, items, dependencies)
            # computations whose source is the item are deleted
            for computation in self.computations:
                if computation.source == item or not computation.is_valid_with_removals(set(items)):
                    if (item, computation) not in dependencies:
                        dependencies.append((item, computation))
                    self.__build_cascade(computation, items, dependencies)
            # item is being removed; so remove any dependency from any source to this item
            for source in sources:
                if (source, item) not in dependencies:
                    dependencies.append((source, item))

    def __cascade_delete(self, master_item, safe: bool=False) -> Changes.UndeleteLog:
        with self.transaction_context():
            return self.__cascade_delete_inner(master_item, safe=safe)

    def __cascade_delete_inner(self, master_item, safe: bool=False) -> Changes.UndeleteLog:
        """Cascade delete an item.

        Returns an undelete log that can be used to undo the cascade deletion.

        Builds a cascade of items to be deleted and dependencies to be removed when the passed item is deleted. Then
        removes computations that are no longer valid. Removing a computation may result in more deletions, so the
        process is repeated until nothing more gets removed.

        Next remove dependencies.

        Next remove individual items (from the most distant from the root item to the root item).
        """
        # print(f"cascade {master_item}")
        # this horrible little hack ensures that computation changed messages are delayed until the end of the cascade
        # delete; otherwise there are cases where dependencies can be reestablished during the changed messages while
        # this method is partially finished. ugh. see test_computation_deletes_when_source_cycle_deletes.
        if self.__computation_changed_delay_list is None:
            computation_changed_delay_list = list()
            self.__computation_changed_delay_list = computation_changed_delay_list
        else:
            computation_changed_delay_list = None
        undelete_log = Changes.UndeleteLog()
        try:
            items = list()
            dependencies = list()
            self.__build_cascade(master_item, items, dependencies)
            cascaded = True
            while cascaded:
                cascaded = False
                # adjust computation bookkeeping to remove deleted items, then delete unused computations
                items_set = set(items)
                for computation in copy.copy(self.computations):
                    input_deleted = not items_set.isdisjoint(computation.direct_input_items)
                    output_deleted = not items_set.isdisjoint(computation.output_items)
                    computation._inputs -= items_set
                    computation._outputs -= items_set
                    if computation not in items and computation != self.__current_computation:
                        # computations are auto deleted if any input or output is deleted.
                        if output_deleted or not computation._inputs or input_deleted:
                            self.__build_cascade(computation, items, dependencies)
                            cascaded = True
            # print(list(reversed(items)))
            # print(list(reversed(dependencies)))
            for source, target in reversed(dependencies):
                self.__remove_dependency(source, target)
            # now delete the actual items
            for item in reversed(items):
                for computation in self.computations:
                    t = computation.list_item_removed(item)
                    if t is not None:
                        index, variable_index, object_specifier = t
                        undelete_log.append(UndeleteObjectSpecifier(self, computation, index, variable_index, object_specifier))
            for item in reversed(items):
                container = item.container
                # if container is None, then this object has already been removed
                if isinstance(container, Project.Project) and isinstance(item, DataItem.DataItem):
                    undelete_log.append(UndeleteDataItem(self, item))
                    # call the version of remove_data_item that doesn't cascade again
                    # NOTE: remove_data_item will notify_remove_item
                    container.remove_data_item(item)
                elif isinstance(container, Project.Project) and isinstance(item, DisplayItem.DisplayItem):
                    # remove the data item from any groups
                    for data_group in self.get_flat_data_group_generator():
                        if item in data_group.display_items:
                            undelete_log.append(UndeleteDisplayItemInDataGroup(self, item, data_group))
                            data_group.remove_display_item(item)
                    undelete_log.append(UndeleteDisplayItem(self, item))
                    # call the version of remove_display_item that doesn't cascade again
                    # NOTE: remove_display_item will notify_remove_item
                    container.remove_display_item(item)
                elif isinstance(container, Project.Project) and isinstance(item, DataStructure.DataStructure):
                    undelete_log.append(UndeleteItem(DataStructuresController(self), item))
                    container.remove_item("data_structures", item)
                elif isinstance(container, Project.Project) and isinstance(item, Symbolic.Computation):
                    undelete_log.append(UndeleteItem(ComputationsController(self), item))
                    container.remove_item("computations", item)
                    if item in self.__computation_changed_delay_list:
                        self.__computation_changed_delay_list.remove(item)
                elif isinstance(container, Project.Project) and isinstance(item, Connection.Connection):
                    undelete_log.append(UndeleteItem(ConnectionsController(self), item))
                    container.remove_item("connections", item)
                elif container and isinstance(item, Graphics.Graphic):
                    undelete_log.append(UndeleteItem(GraphicsController(self), item))
                    container.remove_item("graphics", item)
                elif container and isinstance(item, DisplayItem.DisplayDataChannel):
                    undelete_log.append(UndeleteItem(DisplayDataChannelsController(self), item))
                    container.remove_item("display_data_channels", item)
                elif container and isinstance(item, DisplayItem.DisplayLayer):
                    undelete_log.append(UndeleteItem(DisplayLayersController(self), item))
                    container.remove_item("display_layers", item)
        except Exception as e:
            import sys, traceback
            traceback.print_exc()
            traceback.format_exception(*sys.exc_info())
            raise
        finally:
            # check whether this call of __cascade_delete is the top level one that will finish the computation
            # changed messages.
            if computation_changed_delay_list is not None:
                self.__finish_computation_changed()
        return undelete_log

    def undelete_all(self, undelete_log: Changes.UndeleteLog) -> None:
        undelete_log.undelete_all(self)

    def __remove_dependency(self, source_item, target_item):
        # print(f"remove dependency {source_item} {target_item}")
        with self.__dependency_tree_lock:
            target_items = self.__dependency_tree_source_to_target_map.setdefault(weakref.ref(source_item), list())
            if target_item in target_items:
                target_items.remove(target_item)
            if not target_items:
                self.__dependency_tree_source_to_target_map.pop(weakref.ref(source_item), None)
            source_items = self.__dependency_tree_target_to_source_map.setdefault(weakref.ref(target_item), list())
            if source_item in source_items:
                source_items.remove(source_item)
            if not source_items:
                self.__dependency_tree_target_to_source_map.pop(weakref.ref(target_item), None)
        if isinstance(source_item, DataItem.DataItem) and isinstance(target_item, DataItem.DataItem):
            # propagate live states to dependents
            if source_item.is_live:
                self.end_data_item_live(target_item)
        self.dependency_removed_event.fire(source_item, target_item)
        # fire the display messages
        if isinstance(source_item, DataItem.DataItem):
            for display_item in self.get_display_items_for_data_item(source_item):
                source_display_items = self.get_source_display_items(display_item) if display_item else list()
                dependent_display_items = self.get_dependent_display_items(display_item) if display_item else list()
                self.related_items_changed.fire(display_item, source_display_items, dependent_display_items)

    def __add_dependency(self, source_item, target_item):
        # print(f"add dependency {source_item} {target_item}")
        with self.__dependency_tree_lock:
            self.__dependency_tree_source_to_target_map.setdefault(weakref.ref(source_item), list()).append(target_item)
            self.__dependency_tree_target_to_source_map.setdefault(weakref.ref(target_item), list()).append(source_item)
        if isinstance(source_item, DataItem.DataItem) and isinstance(target_item, DataItem.DataItem):
            # propagate live states to dependents
            if source_item.is_live:
                self.begin_data_item_live(target_item)
        self.dependency_added_event.fire(source_item, target_item)
        # fire the display messages
        if isinstance(source_item, DataItem.DataItem):
            for display_item in self.get_display_items_for_data_item(source_item):
                source_display_items = self.get_source_display_items(display_item) if display_item else list()
                dependent_display_items = self.get_dependent_display_items(display_item) if display_item else list()
                self.related_items_changed.fire(display_item, source_display_items, dependent_display_items)

    def __computation_needs_update(self, computation: Symbolic.Computation) -> None:
        # When the computation for a data item is set or mutated, this function will be called.
        # This function looks through the existing pending computation queue, and if this data
        # item is not already in the queue, it adds it and ensures the dispatch thread eventually
        # executes the computation.
        with self.__computation_queue_lock:
            for computation_queue_item in self.__computation_pending_queue:
                if computation and computation_queue_item.computation == computation:
                    return
            computation_queue_item = ComputationQueueItem(computation=computation)
            self.__computation_pending_queue.append(computation_queue_item)
        self.dispatch_task(self.__recompute)

    def __establish_computation_dependencies(self, old_inputs: typing.Set, new_inputs: typing.Set, old_outputs: typing.Set, new_outputs: typing.Set) -> None:
        # establish dependencies between input and output items.
        with self.__dependency_tree_lock:
            removed_inputs = old_inputs - new_inputs
            added_inputs = new_inputs - old_inputs
            removed_outputs = old_outputs - new_outputs
            added_outputs = new_outputs - old_outputs
            same_inputs = old_inputs.intersection(new_inputs)
            # a, b -> x, y => a, c => x, z
            # [a -> x, a -> y, b -> x, b -> y]
            # [a -> x, a -> z, c -> x, c -> z]
            # old_inputs = [a, b]
            # new_inputs = [a, c]
            # removed inputs = [b]
            # added_inputs = [c]
            # old_outputs = [x, y]
            # new_outputs = [x, z]
            # removed_outputs = [y]
            # added_outputs = [z]
            # for each removed input, remove dependency to old outputs: [a -> x, a -> y]
            # for each removed output, remove dependency from old inputs to that output: [a -> x]
            # for each added input, add dependency to new outputs: [a -> x, c -> x, c -> z]
            # for each added output, add dependency from unchanged inputs to that output: [a -> x, a -> z, c -> x, c -> z]
            for input in removed_inputs:
                for output in old_outputs:
                    self.__remove_dependency(input, output)
            for output in removed_outputs:
                for input in old_inputs:
                    self.__remove_dependency(input, output)
            for input in added_inputs:
                for output in new_outputs:
                    self.__add_dependency(input, output)
            for output in added_outputs:
                for input in same_inputs:
                    self.__add_dependency(input, output)
        if removed_inputs or added_inputs or removed_outputs or added_outputs:
            self.__transaction_manager._rebuild_transactions()

    # live state, and dependencies

    def get_source_items(self, item) -> typing.List:
        with self.__dependency_tree_lock:
            return copy.copy(self.__dependency_tree_target_to_source_map.get(weakref.ref(item), list()))

    def get_dependent_items(self, item) -> typing.List:
        """Return the list of data items containing data that directly depends on data in this item."""
        with self.__dependency_tree_lock:
            return copy.copy(self.__dependency_tree_source_to_target_map.get(weakref.ref(item), list()))

    def __get_deep_dependent_item_set(self, item, item_set) -> None:
        """Return the list of data items containing data that directly depends on data in this item."""
        if not item in item_set:
            item_set.add(item)
            with self.__dependency_tree_lock:
                for dependent in self.get_dependent_items(item):
                    self.__get_deep_dependent_item_set(dependent, item_set)

    def get_source_data_items(self, data_item: DataItem.DataItem) -> typing.List[DataItem.DataItem]:
        with self.__dependency_tree_lock:
            return [data_item for data_item in self.__dependency_tree_target_to_source_map.get(weakref.ref(data_item), list()) if isinstance(data_item, DataItem.DataItem)]

    def get_dependent_data_items(self, data_item: DataItem.DataItem) -> typing.List[DataItem.DataItem]:
        """Return the list of data items containing data that directly depends on data in this item."""
        with self.__dependency_tree_lock:
            return [data_item for data_item in self.__dependency_tree_source_to_target_map.get(weakref.ref(data_item), list()) if isinstance(data_item, DataItem.DataItem)]

    def get_source_display_items(self, display_item: DisplayItem.DisplayItem) -> typing.List[DisplayItem.DisplayItem]:
        display_items = list()
        for data_item in display_item.data_items:
            if data_item:  # may be none for missing data
                for data_item_ in self.get_source_data_items(data_item):
                    for display_item_ in self.get_display_items_for_data_item(data_item_):
                        if display_item_ not in display_items and display_item_ != display_item:
                            display_items.append(display_item_)
        return display_items

    def get_dependent_display_items(self, display_item: DisplayItem.DisplayItem) -> typing.List[DisplayItem.DisplayItem]:
        display_items = list()
        for data_item in display_item.data_items:
            if data_item:  # may be none for missing data
                for data_item_ in self.get_dependent_data_items(data_item):
                    for display_item_ in self.get_display_items_for_data_item(data_item_):
                        if display_item_ not in display_items and display_item_ != display_item:
                            display_items.append(display_item_)
        return display_items

    def transaction_context(self):
        """Return a context object for a document-wide transaction."""

        class Transaction:
            def __init__(self, document_model: DocumentModel):
                self.__document_model = document_model

            def __enter__(self):
                self.__document_model._project.project_storage_system.enter_transaction()
                return self

            def __exit__(self, type, value, traceback):
                self.__document_model._project.project_storage_system.exit_transaction()

        return Transaction(self)

    def item_transaction(self, item) -> Transaction:
        return self.__transaction_manager.item_transaction(item)

    def is_in_transaction_state(self, item) -> bool:
        return self.__transaction_manager.is_in_transaction_state(item)

    @property
    def transaction_count(self):
        return self.__transaction_manager.transaction_count

    def begin_display_item_transaction(self, display_item: DisplayItem.DisplayItem) -> Transaction:
        if display_item:
            return self.item_transaction(display_item)
        else:
            return self.__transaction_manager.item_transaction(set())

    def data_item_live(self, data_item):
        """ Return a context manager to put the data item in a 'live state'. """
        class LiveContextManager:
            def __init__(self, manager, object):
                self.__manager = manager
                self.__object = object
            def __enter__(self):
                self.__manager.begin_data_item_live(self.__object)
                return self
            def __exit__(self, type, value, traceback):
                self.__manager.end_data_item_live(self.__object)
        return LiveContextManager(self, data_item)

    def begin_data_item_live(self, data_item):
        """Begins a live state for the data item.

        The live state is propagated to dependent data items.

        This method is thread safe. See slow_test_dependent_data_item_removed_while_live_data_item_becomes_unlive.
        """
        with self.__live_data_items_lock:
            old_live_count = self.__live_data_items.get(data_item.uuid, 0)
            self.__live_data_items[data_item.uuid] = old_live_count + 1
        if old_live_count == 0:
            data_item._enter_live_state()
            for dependent_data_item in self.get_dependent_data_items(data_item):
                self.begin_data_item_live(dependent_data_item)

    def end_data_item_live(self, data_item):
        """Ends a live state for the data item.

        The live-ness property is propagated to dependent data items, similar to the transactions.

        This method is thread safe.
        """
        with self.__live_data_items_lock:
            live_count = self.__live_data_items.get(data_item.uuid, 0) - 1
            assert live_count >= 0
            self.__live_data_items[data_item.uuid] = live_count
        if live_count == 0:
            data_item._exit_live_state()
            for dependent_data_item in self.get_dependent_data_items(data_item):
                self.end_data_item_live(dependent_data_item)

    # data groups

    def append_data_group(self, data_group):
        self.insert_data_group(len(self.data_groups), data_group)

    def insert_data_group(self, before_index, data_group):
        self._project.insert_item("data_groups", before_index, data_group)

    def remove_data_group(self, data_group):
        self._project.remove_item("data_groups", data_group)

    def create_default_data_groups(self):
        # ensure there is at least one group
        if len(self.data_groups) < 1:
            data_group = DataGroup.DataGroup()
            data_group.title = _("My Data")
            self.append_data_group(data_group)

    # Return a generator over all data groups
    def get_flat_data_group_generator(self):
        return DataGroup.get_flat_data_group_generator_in_container(self)

    def get_data_group_by_uuid(self, uuid: uuid.UUID):
        for data_group in DataGroup.get_flat_data_group_generator_in_container(self):
            if data_group.uuid == uuid:
                return data_group
        return None

    def get_display_items_for_data_item(self, data_item: typing.Optional[DataItem.DataItem]) -> typing.Set[DisplayItem.DisplayItem]:
        # return the set of display items for the data item
        display_items = set()
        if data_item:
            for display_data_channel in data_item.display_data_channels:
                display_items.add(display_data_channel.container)
        return display_items

    def get_any_display_item_for_data_item(self, data_item: typing.Optional[DataItem.DataItem]) -> typing.Optional[DisplayItem.DisplayItem]:
        # return the first display item containing the data item.
        # ordering is preserved (useful, at least for tests).
        for display_item in self.display_items:
            if data_item in display_item.data_items:
                return display_item
        return None

    def get_display_item_for_data_item(self, data_item: DataItem.DataItem) -> typing.Optional[DisplayItem.DisplayItem]:
        display_items = self.get_display_items_for_data_item(data_item)
        return next(iter(display_items)) if len(display_items) == 1 else None

    def get_best_display_item_for_data_item(self, data_item: DataItem.DataItem) -> typing.Optional[DisplayItem.DisplayItem]:
        display_items = self.get_display_items_for_data_item(data_item)
        for display_item in display_items:
            if display_item.data_item == data_item:
                return display_item
        return next(iter(display_items)) if len(display_items) == 1 else None

    def are_display_items_equal(self, display_item1: DisplayItem.DisplayItem, display_item2: DisplayItem.DisplayItem) -> bool:
        return display_item1 == display_item2

    def get_or_create_data_group(self, group_name):
        data_group = DataGroup.get_data_group_in_container_by_title(self, group_name)
        if data_group is None:
            # we create a new group
            data_group = DataGroup.DataGroup()
            data_group.title = group_name
            self.insert_data_group(0, data_group)
        return data_group

    def create_computation(self, expression: str=None) -> Symbolic.Computation:
        return Symbolic.Computation(expression)

    def dispatch_task(self, task, description=None):
        self.__computation_thread_pool.queue_fn(task, description)

    def recompute_all(self, merge=True):
        while True:
            self.__computation_thread_pool.run_all()
            if merge:
                self.perform_data_item_merge()
                with self.__computation_queue_lock:
                    if not (self.__computation_pending_queue or self.__computation_active_item or self.__pending_data_item_merge):
                        break
            else:
                break

    def recompute_one(self, merge=True):
        self.__computation_thread_pool.run_one()
        if merge:
            self.perform_data_item_merge()

    def start_dispatcher(self):
        self.__computation_thread_pool.start(1)

    def __recompute(self):
        while True:
            computation_queue_item = None
            with self.__computation_queue_lock:
                if not self.__computation_active_item and self.__computation_pending_queue:
                    computation_queue_item = self.__computation_pending_queue.pop(0)
                    self.__computation_active_item = computation_queue_item

            if computation_queue_item:
                # an item was put into the active queue, so compute it, then merge
                pending_data_item_merge = computation_queue_item.recompute()
                if pending_data_item_merge is not None:
                    with self.__pending_data_item_merge_lock:
                        if self.__pending_data_item_merge:
                            self.__pending_data_item_merge.close()
                        self.__pending_data_item_merge = pending_data_item_merge
                    self.__call_soon(self.perform_data_item_merge)
                else:
                    with self.__computation_queue_lock:
                        self.__computation_active_item = None
            else:
                break

    def perform_data_item_merge(self):
        with self.__pending_data_item_merge_lock:
            pending_data_item_merge = self.__pending_data_item_merge
            self.__pending_data_item_merge = None
        if pending_data_item_merge:
            computation = pending_data_item_merge.computation
            self.__current_computation = computation
            try:
                pending_data_item_merge.exec()
            finally:
                self.__current_computation = None
                with self.__computation_queue_lock:
                    self.__computation_active_item = None
                computation.is_initial_computation_complete.set()
                pending_data_item_merge.close()
        self.dispatch_task(self.__recompute)

    async def compute_immediate(self, event_loop: asyncio.AbstractEventLoop, computation: Symbolic.Computation, timeout: float=None) -> None:
        if computation:
            def sync_recompute():
                computation.is_initial_computation_complete.wait(timeout)
            await event_loop.run_in_executor(None, sync_recompute)

    def get_object_specifier(self, object, object_type: str=None) -> typing.Optional[typing.Dict]:
        return DataStructure.get_object_specifier(object, object_type)

    def get_graphic_by_uuid(self, object_uuid: uuid.UUID) -> typing.Optional[Graphics.Graphic]:
        for display_item in self.display_items:
            for graphic in display_item.graphics:
                if graphic.uuid == object_uuid:
                    return graphic
        return None

    class DataItemReference:
        """A data item reference to coordinate data item access between acquisition and main thread.

        Call start/stop a matching number of times to start/stop using the data reference (from the
        acquisition thread).

        Set data_item property when it is created (from the UI thread).

        This class will also track when the data item is deleted and handle it appropriately if it
        happens while the acquisition thread is using it.
        """
        def __init__(self, document_model: "DocumentModel", key: str, project: Project.Project, data_item_specifier: Persistence.PersistentObjectSpecifier=None):
            self.__document_model = document_model
            self.__key = key
            self.__data_item_proxy = project.create_item_proxy(item_specifier=data_item_specifier)
            self.__starts = 0
            self.__pending_starts = 0
            self.__data_item_transaction = None
            self.mutex = threading.RLock()
            self.data_item_reference_changed_event = Event.Event()

            def item_unregistered(item) -> None:
                # when this data item is removed, it can no longer be used.
                # but to ensure that start/stop calls are matching in the case where this item
                # is removed and then a new item is set, we need to copy the number of starts
                # to the pending starts so when the new item is set, start gets called the right
                # number of times to match the stops that will eventually be called.
                self.__pending_starts = self.__starts
                self.__starts = 0

            self.__data_item_proxy.on_item_unregistered = item_unregistered

        def close(self) -> None:
            self.__data_item_proxy.close()
            self.__data_item_proxy = None

        def set_data_item_specifier(self, project: Project.Project, data_item_specifier: Persistence.PersistentObjectSpecifier) -> None:
            data_item_proxy = project.create_item_proxy(item_specifier=data_item_specifier)
            if data_item_proxy.item != self.__data_item:
                assert self.__starts == 0
                assert self.__pending_starts == 0
                assert not self.__data_item_transaction
                self.__stop()  # data item is changing; close existing one.
                self.__data_item_proxy.close()
                self.__data_item_proxy = data_item_proxy
            else:
                data_item_proxy.close()

        @property
        def __data_item(self) -> typing.Optional[DataItem.DataItem]:
            return self.__data_item_proxy.item

        def start(self):
            """Start using the data item reference. Must call stop a matching number of times.

            Increments ref counts and begins transaction/live state.

            Keeps track of pending starts if the data item has not yet been set.

            This call is thread safe.
            """
            if self.__data_item:
                self.__start()
            else:
                self.__pending_starts += 1

        def stop(self):
            """Stop using the data item reference. Must have called start a matching number of times.

            Decrements ref counts and ends transaction/live state.

            Keeps track of pending starts if the data item has not yet been set.

            This call is thread safe.
            """
            if self.__data_item:
                self.__stop()
            else:
                self.__pending_starts -= 1

        def __start(self):
            self.__data_item.increment_data_ref_count()
            self.__data_item_transaction = self.__document_model.item_transaction(self.__data_item)
            self.__document_model.begin_data_item_live(self.__data_item)
            self.__starts += 1

        def __stop(self):
            # the order of these two statements is important, at least for now (12/2013)
            # when the transaction ends, the data will get written to disk, so we need to
            # make sure it's still in memory. if decrement were to come before the end
            # of the transaction, the data would be unloaded from memory, losing it forever.
            if self.__data_item_transaction:
                self.__data_item_transaction.close()
                self.__data_item_transaction = None
                self.__document_model.end_data_item_live(self.__data_item)
                self.__data_item.decrement_data_ref_count()
                self.__starts -= 1

        @property
        def data_item(self) -> DataItem.DataItem:
            with self.mutex:
                return self.__data_item

        @property
        def display_item(self) -> DisplayItem.DisplayItem:
            return self.__document_model.get_display_item_for_data_item(self.data_item)

        @data_item.setter
        def data_item(self, value):
            with self.mutex:
                if self.__data_item != value:
                    self.__data_item_proxy.item = value
                    # start (internal) for each pending start.
                    for i in range(self.__pending_starts):
                        self.__start()
                    self.__pending_starts = 0
                    if self.__data_item in self.__document_model.data_items:
                        self.data_item_reference_changed_event.fire()
                    else:
                        def item_inserted(key, value, index):
                            if value == self.__data_item:
                                self.data_item_reference_changed_event.fire()
                                self.__item_inserted_listener.close()
                                self.__item_inserted_listener = None
                        self.__item_inserted_listener = self.__document_model.item_inserted_event.listen(item_inserted)

    def __queue_data_item_update(self, data_item: DataItem.DataItem, data_and_metadata: DataAndMetadata.DataAndMetadata) -> None:
        # put the data update to data_item into the pending_data_item_updates list.
        # the pending_data_item_updates will be serviced when the main thread calls
        # perform_data_item_updates.
        if data_item:
            with self.__pending_data_item_updates_lock:
                found = False
                pending_data_item_updates = list()
                for data_item_ in self.__pending_data_item_updates:
                    # does it match? if so and not yet found, put the new data into the matching
                    # slot; but then filter the rest of the matches.
                    if data_item_ == data_item:
                        if not found:
                            data_item.set_pending_xdata(data_and_metadata)
                            pending_data_item_updates.append(data_item)
                            found = True
                    else:
                        pending_data_item_updates.append(data_item_)
                if not found:  # if not added yet, add it
                    data_item.set_pending_xdata(data_and_metadata)
                    pending_data_item_updates.append(data_item)
                self.__pending_data_item_updates = pending_data_item_updates

    def update_data_item_partial(self, data_item: DataItem.DataItem, data_metadata: DataAndMetadata.DataMetadata,
                                 data_and_metadata: DataAndMetadata.DataAndMetadata, src_slice: typing.Sequence[slice],
                                 dst_slice: typing.Sequence[slice]) -> None:
        if data_item:
            with self.__pending_data_item_updates_lock:
                assert data_metadata
                data_item.queue_partial_update(data_and_metadata, src_slice=src_slice, dst_slice=dst_slice, metadata=data_metadata)
                self.__pending_data_item_updates.append(data_item)

    def perform_data_item_updates(self):
        assert threading.current_thread() == threading.main_thread()
        with self.__pending_data_item_updates_lock:
            pending_data_item_updates = self.__pending_data_item_updates
            self.__pending_data_item_updates = list()
        for data_item in pending_data_item_updates:
            data_item.update_to_pending_xdata()

    # for testing
    def _get_pending_data_item_updates_count(self):
        return len(self.__pending_data_item_updates)

    @property
    def data_groups(self) -> typing.List[DataGroup.DataGroup]:
        return self._project.data_groups

    def _update_data_item_reference(self, key: str, data_item: DataItem.DataItem) -> None:
        assert threading.current_thread() == threading.main_thread()
        if data_item:
            self._project.set_data_item_reference(key, data_item)
        else:
            self._project.clear_data_item_reference(key)

    def make_data_item_reference_key(self, *components) -> str:
        return "_".join([str(component) for component in list(components) if component is not None])

    def get_data_item_reference(self, key) -> "DocumentModel.DataItemReference":
        # this is implemented this way to avoid creating a data item reference unless it is missing.
        data_item_reference = self.__data_item_references.get(key)
        if data_item_reference:
            return data_item_reference
        return self.__data_item_references.setdefault(key, DocumentModel.DataItemReference(self, key, self._project))

    def setup_channel(self, data_item_reference_key: str, data_item: DataItem.DataItem) -> None:
        data_item_reference = self.get_data_item_reference(data_item_reference_key)
        data_item_reference.data_item = data_item
        self._update_data_item_reference(data_item_reference_key, data_item)

    def __construct_data_item_reference(self, hardware_source: HardwareSource.HardwareSource, data_channel: HardwareSource.DataChannel):
        """Construct a data item reference.

        Construct a data item reference and assign a data item to it. Update data item session id and session metadata.
        Also connect the data channel processor.

        This method is thread safe.
        """
        session_id = self.session_id
        key = self.make_data_item_reference_key(hardware_source.hardware_source_id, data_channel.channel_id)
        data_item_reference = self.get_data_item_reference(key)
        with data_item_reference.mutex:
            data_item = data_item_reference.data_item
            # if we still don't have a data item, create it.
            if data_item is None:
                data_item = DataItem.DataItem()
                data_item.ensure_data_source()
                data_item.title = "%s (%s)" % (hardware_source.display_name, data_channel.name) if data_channel.name else hardware_source.display_name
                data_item.category = "temporary"
                data_item_reference.data_item = data_item

                def append_data_items():
                    with self.__data_items_to_append_lock:
                        for key, data_item in self.__data_items_to_append:
                            self.append_data_item(data_item)
                            self._update_data_item_reference(key, data_item)
                        self.__data_items_to_append.clear()

                with self.__data_items_to_append_lock:
                    self.__data_items_to_append.append((key, data_item))

                self.__call_soon(append_data_items)

            def update_session():
                # since this is a delayed call, the data item might have disappeared. check it.
                if data_item._closed:
                    return
                # update the session, but only if necessary (this is an optimization to prevent unnecessary display updates)
                if data_item.session_id != session_id:
                    data_item.session_id = session_id
                session_metadata = ApplicationData.get_session_metadata_dict()
                if data_item.session_metadata != session_metadata:
                    data_item.session_metadata = session_metadata
                if data_channel.processor:
                    src_data_channel = hardware_source.data_channels[data_channel.src_channel_index]
                    src_data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, src_data_channel.channel_id))
                    data_channel.processor.connect_data_item_reference(src_data_item_reference)

            self.__call_soon(update_session)

            return data_item_reference

    def __data_channel_start(self, hardware_source, data_channel):
        def data_channel_start():
            assert threading.current_thread() == threading.main_thread()
            data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, data_channel.channel_id))
            data_item_reference.start()
        self.__call_soon(data_channel_start)

    def __data_channel_stop(self, hardware_source, data_channel):
        def data_channel_stop():
            assert threading.current_thread() == threading.main_thread()
            data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, data_channel.channel_id))
            data_item_reference.stop()
        self.__call_soon(data_channel_stop)

    def __data_channel_updated(self, hardware_source, data_channel, data_and_metadata):
        data_item_reference = self.__construct_data_item_reference(hardware_source, data_channel)
        self.__queue_data_item_update(data_item_reference.data_item, data_and_metadata)

    def __data_channel_states_updated(self, hardware_source, data_channels):
        data_item_states = list()
        for data_channel in data_channels:
            data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, data_channel.channel_id))
            data_item = data_item_reference.data_item
            channel_id = data_channel.channel_id
            channel_data_state = data_channel.state
            sub_area = data_channel.sub_area
            # make sure to send out the complete frame
            data_item_state = dict()
            if channel_id is not None:
                data_item_state["channel_id"] = channel_id
            data_item_state["data_item"] = data_item
            data_item_state["channel_state"] = channel_data_state
            if sub_area:
                data_item_state["sub_area"] = sub_area
            data_item_states.append(data_item_state)
        # temporary until things get cleaned up
        hardware_source.data_item_states_changed_event.fire(data_item_states)
        hardware_source.data_item_states_changed(data_item_states)

    def __hardware_source_added(self, hardware_source: HardwareSource.HardwareSource) -> None:
        self.__hardware_source_call_soon_event_listeners[hardware_source.hardware_source_id] = hardware_source.call_soon_event.listen(self.__call_soon)
        self.__data_channel_states_updated_listeners[hardware_source.hardware_source_id] = hardware_source.data_channel_states_updated.listen(functools.partial(self.__data_channel_states_updated, hardware_source))
        for data_channel in hardware_source.data_channels:
            data_channel_updated_listener = data_channel.data_channel_updated_event.listen(functools.partial(self.__data_channel_updated, hardware_source, data_channel))
            self.__data_channel_updated_listeners.setdefault(hardware_source.hardware_source_id, list()).append(data_channel_updated_listener)
            data_channel_start_listener = data_channel.data_channel_start_event.listen(functools.partial(self.__data_channel_start, hardware_source, data_channel))
            self.__data_channel_start_listeners.setdefault(hardware_source.hardware_source_id, list()).append(data_channel_start_listener)
            data_channel_stop_listener = data_channel.data_channel_stop_event.listen(functools.partial(self.__data_channel_stop, hardware_source, data_channel))
            self.__data_channel_stop_listeners.setdefault(hardware_source.hardware_source_id, list()).append(data_channel_stop_listener)
            # NOTE: clean_display_items is called in __finish_project_read

    def __hardware_source_removed(self, hardware_source):
        self.__hardware_source_call_soon_event_listeners[hardware_source.hardware_source_id].close()
        del self.__hardware_source_call_soon_event_listeners[hardware_source.hardware_source_id]
        self.__data_channel_states_updated_listeners[hardware_source.hardware_source_id].close()
        del self.__data_channel_states_updated_listeners[hardware_source.hardware_source_id]
        for listener in self.__data_channel_updated_listeners.get(hardware_source.hardware_source_id, list()):
            listener.close()
        for listener in self.__data_channel_start_listeners.get(hardware_source.hardware_source_id, list()):
            listener.close()
        for listener in self.__data_channel_stop_listeners.get(hardware_source.hardware_source_id, list()):
            listener.close()
        self.__data_channel_updated_listeners.pop(hardware_source.hardware_source_id, None)
        self.__data_channel_start_listeners.pop(hardware_source.hardware_source_id, None)
        self.__data_channel_stop_listeners.pop(hardware_source.hardware_source_id, None)

    def populate_action_context(self, data_item: DataItem.DataItem, d: typing.MutableMapping) -> None:
        if data_item.has_metadata_value("stem.hardware_source.id"):
            d["hardware_source"] = HardwareSource.HardwareSourceManager().get_hardware_source_for_hardware_source_id(data_item.get_metadata_value("stem.hardware_source.id"))

    def get_display_item_snapshot_new(self, display_item: DisplayItem.DisplayItem) -> DisplayItem.DisplayItem:
        display_item_copy = display_item.snapshot()
        data_item_copies = list()
        for data_item in display_item.data_items:
            if data_item:
                data_item_copy = data_item.snapshot()
                self.append_data_item(data_item_copy, False)
                data_item_copies.append(data_item_copy)
            else:
                data_item_copies.append(None)
        for display_data_channel in copy.copy(display_item_copy.display_data_channels):
            display_item_copy.remove_display_data_channel(display_data_channel)
        for data_item_copy, display_data_channel in zip(data_item_copies, display_item.display_data_channels):
            display_data_channel_copy = DisplayItem.DisplayDataChannel(data_item=data_item_copy)
            display_data_channel_copy.copy_display_data_properties_from(display_data_channel)
            display_item_copy.append_display_data_channel(display_data_channel_copy, display_layer=DisplayItem.DisplayLayer())
        # the display layers will be disrupted by appending data channels; so just recopy them here
        # this code can be simplified once display layers are objects
        while len(display_item_copy.display_layers):
            display_item_copy.remove_display_layer(0).close()
        for i in range(len(display_item.display_layers)):
            data_index = display_item.display_data_channels.index(display_item.get_display_layer_display_data_channel(i))
            display_item_copy.add_display_layer_for_display_data_channel(display_item_copy.display_data_channels[data_index], **display_item.get_display_layer_properties(i))
        display_item_copy.title = _("Snapshot of ") + display_item.title
        self.append_display_item(display_item_copy)
        return display_item_copy

    def get_display_item_copy_new(self, display_item: DisplayItem.DisplayItem) -> DisplayItem.DisplayItem:
        display_item_copy = display_item.snapshot()
        self.append_display_item(display_item_copy)
        return display_item_copy

    def append_connection(self, connection: Connection.Connection) -> None:
        self._project.append_connection(connection)

    def insert_connection(self, before_index: int, connection: Connection.Connection) -> None:
        uuid_order = save_item_order(self.__connections)
        self.append_connection(connection)
        insert_item_order(uuid_order, before_index, connection)
        self.__connections = restore_item_order(self._project, uuid_order)

    def remove_connection(self, connection: Connection.Connection) -> None:
        connection.container.remove_connection(connection)

    def __handle_connection_inserted(self, connection: Connection.Connection) -> None:
        assert connection is not None
        assert connection not in self.__connections
        # insert in internal list
        before_index = len(self.__connections)
        self.__connections.append(connection)
        # send notifications
        self.notify_insert_item("connections", connection, before_index)

    def __handle_connection_removed(self, connection: Connection.Connection) -> None:
        # remove it from the persistent_storage
        assert connection is not None
        assert connection in self.__connections
        index = self.__connections.index(connection)
        self.notify_remove_item("connections", connection, index)
        self.__connections.remove(connection)

    def create_data_structure(self, *, structure_type: str=None, source=None):
        return DataStructure.DataStructure(structure_type=structure_type, source=source)

    def append_data_structure(self, data_structure: DataStructure.DataStructure) -> None:
        self._project.append_data_structure(data_structure)

    def insert_data_structure(self, before_index: int, data_structure: DataStructure.DataStructure) -> None:
        uuid_order = save_item_order(self.__data_structures)
        self.append_data_structure(data_structure)
        insert_item_order(uuid_order, before_index, data_structure)
        self.__data_structures = restore_item_order(self._project, uuid_order)

    def remove_data_structure(self, data_structure: DataStructure.DataStructure) -> None:
        return self.__cascade_delete(data_structure).close()

    def remove_data_structure_with_log(self, data_structure: DataStructure.DataStructure) -> Changes.UndeleteLog:
        return self.__cascade_delete(data_structure)

    def __handle_data_structure_inserted(self, data_structure: DataStructure.DataStructure) -> None:
        assert data_structure is not None
        assert data_structure not in self.__data_structures
        # insert in internal list
        before_index = len(self.__data_structures)
        self.__data_structures.append(data_structure)
        # listeners
        def rebuild_transactions(): self.__transaction_manager._rebuild_transactions()
        self.__data_structure_listeners[data_structure] = data_structure.data_structure_objects_changed_event.listen(rebuild_transactions)
        # transactions
        self.__transaction_manager._add_item(data_structure)
        # send notifications
        self.notify_insert_item("data_structures", data_structure, before_index)

    def __handle_data_structure_removed(self, data_structure: DataStructure.DataStructure) -> None:
        # remove it from the persistent_storage
        assert data_structure is not None
        assert data_structure in self.__data_structures
        # listeners
        self.__data_structure_listeners[data_structure].close()
        self.__data_structure_listeners.pop(data_structure, None)
        # transactions
        self.__transaction_manager._remove_item(data_structure)
        index = self.__data_structures.index(data_structure)
        # notifications
        self.notify_remove_item("data_structures", data_structure, index)
        # remove from internal list
        self.__data_structures.remove(data_structure)

    def attach_data_structure(self, data_structure, data_item):
        data_structure.source = data_item

    def get_data_item_computation(self, data_item: DataItem.DataItem) -> typing.Optional[Symbolic.Computation]:
        for computation in self.computations:
            if data_item in computation.output_items:
                target_object = computation.get_output("target")
                if target_object == data_item:
                    return computation
        return None

    def set_data_item_computation(self, data_item: DataItem.DataItem, computation: typing.Optional[Symbolic.Computation]) -> None:
        if data_item:
            old_computation = self.get_data_item_computation(data_item)
            if old_computation is computation:
                pass
            elif computation:
                computation.create_output_item("target", Symbolic.make_item(data_item), label=_("Target"))
                self.append_computation(computation)
            elif old_computation:
                # remove old computation without cascade (it would delete this data item itself)
                old_computation.valid = False
                old_computation.container.remove_computation(old_computation)

    def append_computation(self, computation: Symbolic.Computation) -> None:
        computation.pending_project = self._project  # tell the computation where it will end up so get related item works
        # input/output bookkeeping
        input_items = computation.get_preliminary_input_items()
        output_items = computation.get_preliminary_output_items()
        input_set = set()
        for input in input_items:
            self.__get_deep_dependent_item_set(input, input_set)
        output_set = set()
        for output in output_items:
            self.__get_deep_dependent_item_set(output, output_set)
        if input_set.intersection(output_set):
            computation.close()
            raise Exception("Computation would result in duplicate dependency.")
        self._project.append_computation(computation)

    def insert_computation(self, before_index: int, computation: Symbolic.Computation) -> None:
        uuid_order = save_item_order(self.__computations)
        self.append_computation(computation)
        insert_item_order(uuid_order, before_index, computation)
        self.__computations = restore_item_order(self._project, uuid_order)

    def remove_computation(self, computation: Symbolic.Computation, *, safe: bool=False) -> None:
        self.__cascade_delete(computation, safe=safe).close()

    def remove_computation_with_log(self, computation: Symbolic.Computation, *, safe: bool=False) -> Changes.UndeleteLog:
        return self.__cascade_delete(computation, safe=safe)

    def __handle_computation_inserted(self, computation: Symbolic.Computation) -> None:
        assert computation is not None
        assert computation not in self.__computations
        # insert in internal list
        before_index = len(self.__computations)
        self.__computations.append(computation)
        # listeners
        self.__computation_changed_listeners[computation] = computation.computation_mutated_event.listen(functools.partial(self.__computation_changed, computation))
        self.__computation_output_changed_listeners[computation] = computation.computation_output_changed_event.listen(functools.partial(self.__computation_update_dependencies, computation))
        # send notifications
        self.__computation_changed(computation)  # ensure the initial mutation is reported
        self.notify_insert_item("computations", computation, before_index)

    def __handle_computation_removed(self, computation: Symbolic.Computation) -> None:
        # remove it from the persistent_storage
        assert computation is not None
        assert computation in self.__computations
        # remove it from any computation queues
        with self.__computation_queue_lock:
            computation_pending_queue = self.__computation_pending_queue
            self.__computation_pending_queue = list()
            for computation_queue_item in computation_pending_queue:
                if not computation_queue_item.computation is computation:
                    self.__computation_pending_queue.append(computation_queue_item)
            if self.__computation_active_item and computation is self.__computation_active_item.computation:
                self.__computation_active_item.valid = False
        computation_changed_listener = self.__computation_changed_listeners.pop(computation, None)
        if computation_changed_listener: computation_changed_listener.close()
        computation_output_changed_listener = self.__computation_output_changed_listeners.pop(computation, None)
        if computation_output_changed_listener: computation_output_changed_listener.close()
        # notifications
        index = self.__computations.index(computation)
        self.notify_remove_item("computations", computation, index)
        # remove from internal list
        self.__computations.remove(computation)

    def __computation_changed(self, computation):
        # when the computation is mutated, this function is called. it calls the handle computation
        # changed or mutated method to resolve computation variables and update dependencies between
        # library objects. it also fires the computation_updated_event to allow the user interface
        # to update.
        # during updating of dependencies, this HUGE hack is in place to delay the computation changed
        # messages until ALL of the dependencies are updated so as to avoid the computation changed message
        # reestablishing dependencies during the updating of them. UGH. planning a better way...
        if self.__computation_changed_delay_list is not None:
            if computation not in self.__computation_changed_delay_list:
                self.__computation_changed_delay_list.append(computation)
        else:
            self.__computation_update_dependencies(computation)
            self.__computation_needs_update(computation)
        self.computation_updated_event.fire(computation)

    def __finish_computation_changed(self):
        computation_changed_delay_list = self.__computation_changed_delay_list
        self.__computation_changed_delay_list = None
        for computation in computation_changed_delay_list:
            self.__computation_changed(computation)

    def __computation_update_dependencies(self, computation):
        # when a computation output is changed, this function is called to establish dependencies.
        # if other parts of the computation are changed (inputs, values, etc.), the __computation_changed
        # will handle the change (and trigger a new computation).
        input_items = set(computation.input_items)
        output_items = set(computation.output_items)
        self.__establish_computation_dependencies(computation._inputs, input_items, computation._outputs, output_items)
        computation._inputs = input_items
        computation._outputs = output_items

    def __digest_requirement(self, requirement: typing.Mapping[str, typing.Any], data_item: DataItem.DataItem) -> bool:
        requirement_type = requirement["type"]
        if requirement_type == "datum_rank":
            values = requirement.get("values")
            if not data_item.datum_dimension_count in values:
                return False
        if requirement_type == "datum_calibrations":
            if requirement.get("units") == "equal":
                if len(set([calibration.units for calibration in data_item.xdata.datum_dimensional_calibrations])) != 1:
                    return False
        if requirement_type == "dimensionality":
            min_dimension = requirement.get("min")
            max_dimension = requirement.get("max")
            dimensionality = len(data_item.dimensional_shape)
            if min_dimension is not None and dimensionality < min_dimension:
                return False
            if max_dimension is not None and dimensionality > max_dimension:
                return False
        if requirement_type == "is_rgb_type":
            if not data_item.xdata.is_data_rgb_type:
                return False
        if requirement_type == "is_sequence":
            if not data_item.is_sequence:
                return False
        if requirement_type == "is_navigable":
            if not data_item.is_sequence and not data_item.is_collection:
                return False
        if requirement_type == "bool":
            operator = requirement["operator"]
            for operand in requirement["operands"]:
                requirement_satisfied = self.__digest_requirement(operand, data_item)
                if operator == "not":
                    return not requirement_satisfied
                if operator == "and" and not requirement_satisfied:
                    return False
                if operator == "or" and requirement_satisfied:
                    return True
            else:
                if operator == "or":
                    return False
        return True

    def __make_computation(self, processing_id: str, inputs: typing.List[typing.Tuple[DisplayItem.DisplayItem, typing.Optional[DisplayItem.DataItem], typing.Optional[Graphics.Graphic]]], region_list_map: typing.Mapping[str, typing.List[Graphics.Graphic]]=None, parameters: typing.Mapping[str, typing.Any]=None) -> typing.Optional[DataItem.DataItem]:
        """Create a new data item with computation specified by processing_id, inputs, and region_list_map.

        The region_list_map associates a list of graphics corresponding to the required regions with a computation source (key).
        """
        region_list_map = region_list_map or dict()

        parameters = parameters or dict()

        processing_descriptions = Project.Project._processing_descriptions
        processing_description = processing_descriptions[processing_id]

        # first process the sources in the description. match them to the inputs (which are data item/crop graphic tuples)
        src_dicts = processing_description.get("sources", list())
        assert len(inputs) == len(src_dicts)
        src_names = list()
        src_texts = list()
        src_labels = list()
        regions = list()
        region_map = dict()
        for i, (src_dict, input) in enumerate(zip(src_dicts, inputs)):

            display_item, data_item, _ = input

            if not data_item:
                return None

            # each source can have a list of requirements, check through them
            # implicit "and" connection between the requirements in the list. Could be changed to use the new
            # boolean options, but leave it like this for backwards compatibility for now.
            requirements = src_dict.get("requirements", list())
            for requirement in requirements:
                if not self.__digest_requirement(requirement, data_item):
                    return None

            src_name = src_dict["name"]
            src_label = src_dict["label"]
            src_names.append(src_name)
            src_texts.append(src_name)
            src_labels.append(src_label)

            # each source can have a list of regions to be matched to arguments or created on the source
            region_dict_list = src_dict.get("regions", list())
            src_region_list = region_list_map.get(src_name, list())
            assert len(region_dict_list) == len(src_region_list)
            for region_dict, region in zip(region_dict_list, src_region_list):
                region_params = region_dict.get("params", dict())
                region_type = region_dict["type"]
                region_name = region_dict["name"]
                region_label = region_params.get("label")
                if region_type == "point":
                    if region:
                        assert isinstance(region, Graphics.PointGraphic)
                        point_region = region
                    else:
                        point_region = Graphics.PointGraphic()
                        for k, v in region_params.items():
                            setattr(point_region, k, v)
                        if display_item:
                            display_item.add_graphic(point_region)
                    regions.append((region_name, point_region, region_label))
                    region_map[region_name] = point_region
                elif region_type == "line":
                    if region:
                        assert isinstance(region, Graphics.LineProfileGraphic)
                        line_region = region
                    else:
                        line_region = Graphics.LineProfileGraphic()
                        line_region.start = 0.25, 0.25
                        line_region.end = 0.75, 0.75
                        for k, v in region_params.items():
                            setattr(line_region, k, v)
                        if display_item:
                            display_item.add_graphic(line_region)
                    regions.append((region_name, line_region, region_params.get("label")))
                    region_map[region_name] = line_region
                elif region_type == "rectangle":
                    if region:
                        assert isinstance(region, Graphics.RectangleGraphic)
                        rect_region = region
                    else:
                        rect_region = Graphics.RectangleGraphic()
                        rect_region.center = 0.5, 0.5
                        rect_region.size = 0.5, 0.5
                        for k, v in region_params.items():
                            setattr(rect_region, k, v)
                        if display_item:
                            display_item.add_graphic(rect_region)
                    regions.append((region_name, rect_region, region_params.get("label")))
                    region_map[region_name] = rect_region
                elif region_type == "ellipse":
                    if region:
                        assert isinstance(region, Graphics.EllipseGraphic)
                        ellipse_region = region
                    else:
                        ellipse_region = Graphics.RectangleGraphic()
                        ellipse_region.center = 0.5, 0.5
                        ellipse_region.size = 0.5, 0.5
                        for k, v in region_params.items():
                            setattr(ellipse_region, k, v)
                        if display_item:
                            display_item.add_graphic(ellipse_region)
                    regions.append((region_name, ellipse_region, region_params.get("label")))
                    region_map[region_name] = ellipse_region
                elif region_type == "spot":
                    if region:
                        assert isinstance(region, Graphics.SpotGraphic)
                        spot_region = region
                    else:
                        spot_region = Graphics.SpotGraphic()
                        spot_region.bounds = Geometry.FloatRect.from_center_and_size((0.25, 0.25), (0.25, 0.25))
                        for k, v in region_params.items():
                            setattr(spot_region, k, v)
                        if display_item:
                            display_item.add_graphic(spot_region)
                    regions.append((region_name, spot_region, region_params.get("label")))
                    region_map[region_name] = spot_region
                elif region_type == "interval":
                    if region:
                        assert isinstance(region, Graphics.IntervalGraphic)
                        interval_graphic = region
                    else:
                        interval_graphic = Graphics.IntervalGraphic()
                        for k, v in region_params.items():
                            setattr(interval_graphic, k, v)
                        if display_item:
                            display_item.add_graphic(interval_graphic)
                    regions.append((region_name, interval_graphic, region_params.get("label")))
                    region_map[region_name] = interval_graphic
                elif region_type == "channel":
                    if region:
                        assert isinstance(region, Graphics.ChannelGraphic)
                        channel_region = region
                    else:
                        channel_region = Graphics.ChannelGraphic()
                        for k, v in region_params.items():
                            setattr(channel_region, k, v)
                        if display_item:
                            display_item.add_graphic(channel_region)
                    regions.append((region_name, channel_region, region_params.get("label")))
                    region_map[region_name] = channel_region

        # now extract the script (full script) or expression (implied imports and return statement)
        script = None
        expression = processing_description.get("expression")
        if expression:
            script = Symbolic.xdata_expression(expression)
            script = script.format(**dict(zip(src_names, src_texts)))

        # construct the computation
        computation = self.create_computation(script)
        computation.attributes.update(processing_description.get("attributes", dict()))
        computation.label = processing_description["title"]
        computation.processing_id = processing_id
        # process the data item inputs
        for src_dict, src_name, src_label, input in zip(src_dicts, src_names, src_labels, inputs):
            in_display_item, data_item, graphic = input
            secondary_item = None
            if src_dict.get("croppable", False):
                secondary_item = graphic
            display_data_channel = in_display_item.get_display_data_channel_for_data_item(data_item)
            computation.create_input_item(src_name, Symbolic.make_item(display_data_channel, secondary_item=secondary_item), label=src_label)
        # process the regions
        for region_name, region, region_label in regions:
            computation.create_input_item(region_name, Symbolic.make_item(region), label=region_label)
        # next process the parameters
        for param_dict in processing_description.get("parameters", list()):
            parameter_value = parameters.get(param_dict["name"], param_dict["value"])
            computation.create_variable(param_dict["name"], param_dict["type"], parameter_value, value_default=param_dict.get("value_default"),
                                        value_min=param_dict.get("value_min"), value_max=param_dict.get("value_max"),
                                        control_type=param_dict.get("control_type"), label=param_dict.get("label"))

        data_item0 = inputs[0][1]
        new_data_item = DataItem.new_data_item()
        prefix = "{} of ".format(processing_description["title"])
        new_data_item.title = prefix + data_item0.title
        new_data_item.category = data_item0.category

        self.append_data_item(new_data_item)

        new_display_item = self.get_display_item_for_data_item(new_data_item)

        # next come the output regions that get created on the target itself
        new_regions = dict()
        for out_region_dict in processing_description.get("out_regions", list()):
            region_type = out_region_dict["type"]
            region_name = out_region_dict["name"]
            region_params = out_region_dict.get("params", dict())
            if region_type == "interval":
                interval_graphic = Graphics.IntervalGraphic()
                for k, v in region_params.items():
                    setattr(interval_graphic, k, v)
                new_display_item.add_graphic(interval_graphic)
                new_regions[region_name] = interval_graphic
            elif region_type == "point":
                point_graphic = Graphics.PointGraphic()
                for k, v in region_params.items():
                    setattr(point_graphic, k, v)
                new_display_item.add_graphic(point_graphic)
                new_regions[region_name] = point_graphic

        # save setting the computation until last to work around threaded clone/merge operation bug.
        # the bug is that setting the computation triggers the recompute to occur on a thread.
        # the recompute clones the data item and runs the operation. meanwhile this thread
        # updates the connection. now the recompute finishes and merges back the data item
        # which was cloned before the connection was established, effectively reversing the
        # update that matched the graphic interval to the slice interval on the display.
        # the result is that the slice interval on the display would get set to the default
        # value of the graphic interval. so don't actually update the computation until after
        # everything is configured. permanent solution would be to improve the clone/merge to
        # only update data that had been changed. alternative implementation would only track
        # changes to the data item and then apply them again to the original during merge.
        self.set_data_item_computation(new_data_item, computation)

        return new_data_item

    _builtin_processing_descriptions = None

    @classmethod
    def register_processing_descriptions(cls, processing_descriptions: typing.Dict) -> None:
        assert len(set(Project.Project._processing_descriptions.keys()).intersection(set(processing_descriptions.keys()))) == 0
        Project.Project._processing_descriptions.update(processing_descriptions)

    @classmethod
    def unregister_processing_descriptions(cls, processing_ids: typing.Sequence[str]):
        assert len(set(Project.Project._processing_descriptions.keys()).intersection(set(processing_ids))) == len(processing_ids)
        for processing_id in processing_ids:
            Project.Project._processing_descriptions.pop(processing_id)

    @classmethod
    def _get_builtin_processing_descriptions(cls) -> typing.Dict:
        if not cls._builtin_processing_descriptions:
            vs = dict()

            requirement_2d = {"type": "dimensionality", "min": 2, "max": 2}
            requirement_3d = {"type": "dimensionality", "min": 3, "max": 3}
            requirement_4d = {"type": "dimensionality", "min": 4, "max": 4}
            requirement_2d_to_3d = {"type": "dimensionality", "min": 2, "max": 3}
            requirement_2d_to_4d = {"type": "dimensionality", "min": 2, "max": 4}
            requirement_2d_to_5d = {"type": "dimensionality", "min": 2, "max": 5}
            requirement_is_rgb_type = {"type": "is_rgb_type"}
            requirement_is_sequence = {"type": "is_sequence"}
            requirement_is_navigable = {"type": "is_navigable"}
            requirement_is_not_sequence = {"type": "bool", "operator": "not", "operands": [requirement_is_sequence]}
            requirement_4d_if_sequence_else_3d = {"type": "bool", "operator": "or",
                                                  "operands": [{"type": "bool", "operator": "and",
                                                                "operands": [requirement_is_not_sequence, requirement_3d]},
                                                               {"type": "bool", "operator": "and",
                                                                "operands": [requirement_is_sequence, requirement_4d]}]}

            for processing_component in typing.cast(typing.Sequence[Processing.ProcessingBase], Registry.get_components_by_type("processing-component")):
                processing_component.register_computation()
                vs[processing_component.processing_id] = {
                    "title": processing_component.title,
                    "sources": processing_component.sources,
                    "parameters": processing_component.parameters,
                    "attributes": processing_component.attributes,
                }
                if processing_component.is_mappable and not processing_component.is_scalar:
                    mapping_param = {"name": "mapping", "label": _("Sequence/Collection Mapping"), "type": "string", "value": "none", "value_default": "none", "control_type": "choice"}
                    vs[processing_component.processing_id].setdefault("parameters", list()).insert(0, mapping_param)
                if processing_component.is_mappable and processing_component.is_scalar:
                    map_out_region = {"name": "pick_point", "type": "point", "params": {"label": _("Pick"), "role": "collection_index"}}
                    vs[processing_component.processing_id]["out_regions"] = [map_out_region]
                    # TODO: generalize this so that other sequence/collections can be accepted by making a coordinate system monitor or similar
                    # TODO: processing should declare its relationship to input coordinate system and swift should automatically connect pickers
                    # TODO: in appropriate places.
                    vs[processing_component.processing_id]["requirements"] = [requirement_4d]

            vs["fft"] = {"title": _("FFT"), "expression": "xd.fft({src}.cropped_display_xdata)", "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["inverse-fft"] = {"title": _("Inverse FFT"), "expression": "xd.ifft({src}.xdata)",
                "sources": [{"name": "src", "label": _("Source")}]}
            vs["auto-correlate"] = {"title": _("Auto Correlate"), "expression": "xd.autocorrelate({src}.cropped_display_xdata)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["cross-correlate"] = {"title": _("Cross Correlate"), "expression": "xd.crosscorrelate({src1}.cropped_display_xdata, {src2}.cropped_display_xdata)",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["sobel"] = {"title": _("Sobel"), "expression": "xd.sobel({src}.cropped_display_xdata)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["laplace"] = {"title": _("Laplace"), "expression": "xd.laplace({src}.cropped_display_xdata)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            sigma_param = {"name": "sigma", "label": _("Sigma"), "type": "real", "value": 3, "value_default": 3, "value_min": 0, "value_max": 100,
                "control_type": "slider"}
            vs["gaussian-blur"] = {"title": _("Gaussian Blur"), "expression": "xd.gaussian_blur({src}.cropped_display_xdata, sigma)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [sigma_param]}
            filter_size_param = {"name": "filter_size", "label": _("Size"), "type": "integral", "value": 3, "value_default": 3, "value_min": 1, "value_max": 100}
            vs["median-filter"] = {"title": _("Median Filter"), "expression": "xd.median_filter({src}.cropped_display_xdata, filter_size)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [filter_size_param]}
            vs["uniform-filter"] = {"title": _("Uniform Filter"), "expression": "xd.uniform_filter({src}.cropped_display_xdata, filter_size)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [filter_size_param]}
            do_transpose_param = {"name": "do_transpose", "label": _("Transpose"), "type": "boolean", "value": False, "value_default": False}
            do_flip_v_param = {"name": "do_flip_v", "label": _("Flip Vertical"), "type": "boolean", "value": False, "value_default": False}
            do_flip_h_param = {"name": "do_flip_h", "label": _("Flip Horizontal"), "type": "boolean", "value": False, "value_default": False}
            vs["transpose-flip"] = {"title": _("Transpose/Flip"), "expression": "xd.transpose_flip({src}.cropped_display_xdata, do_transpose, do_flip_v, do_flip_h)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [do_transpose_param, do_flip_v_param, do_flip_h_param]}
            width_param = {"name": "width", "label": _("Width"), "type": "integral", "value": 256, "value_default": 256, "value_min": 1}
            height_param = {"name": "height", "label": _("Height"), "type": "integral", "value": 256, "value_default": 256, "value_min": 1}
            vs["rebin"] = {"title": _("Rebin"), "expression": "xd.rebin_image({src}.cropped_display_xdata, (height, width))",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [width_param, height_param]}
            vs["resample"] = {"title": _("Resample"), "expression": "xd.resample_image({src}.cropped_display_xdata, (height, width))",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [width_param, height_param]}
            vs["resize"] = {"title": _("Resize"), "expression": "xd.resize({src}.cropped_display_xdata, (height, width), 'mean')",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [width_param, height_param]}
            is_sequence_param = {"name": "is_sequence", "label": _("Sequence"), "type": "bool", "value": False, "value_default": False}
            collection_dims_param = {"name": "collection_dims", "label": _("Collection Dimensions"), "type": "integral", "value": 0, "value_default": 0, "value_min": 0, "value_max": 0}
            datum_dims_param = {"name": "datum_dims", "label": _("Datum Dimensions"), "type": "integral", "value": 1, "value_default": 1, "value_min": 1, "value_max": 0}
            vs["redimension"] = {"title": _("Redimension"), "expression": "xd.redimension({src}.xdata, xd.data_descriptor(is_sequence=is_sequence, collection_dims=collection_dims, datum_dims=datum_dims))",
                "sources": [{"name": "src", "label": _("Source")}], "parameters": [is_sequence_param, collection_dims_param, datum_dims_param]}
            vs["squeeze"] = {"title": _("Squeeze"), "expression": "xd.squeeze({src}.xdata)",
                "sources": [{"name": "src", "label": _("Source")}]}
            bins_param = {"name": "bins", "label": _("Bins"), "type": "integral", "value": 256, "value_default": 256, "value_min": 2}
            vs["histogram"] = {"title": _("Histogram"), "expression": "xd.histogram({src}.cropped_display_xdata, bins)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [bins_param]}
            vs["add"] = {"title": _("Add"), "expression": "{src1}.cropped_display_xdata + {src2}.cropped_display_xdata",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["subtract"] = {"title": _("Subtract"), "expression": "{src1}.cropped_display_xdata - {src2}.cropped_display_xdata",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["multiply"] = {"title": _("Multiply"), "expression": "{src1}.cropped_display_xdata * {src2}.cropped_display_xdata",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["divide"] = {"title": _("Divide"), "expression": "{src1}.cropped_display_xdata / {src2}.cropped_display_xdata",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["invert"] = {"title": _("Negate"), "expression": "xd.invert({src}.cropped_display_xdata)", "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["masked"] = {"title": _("Masked"), "expression": "{src}.filtered_xdata", "sources": [{"name": "src", "label": _("Source")}]}
            vs["mask"] = {"title": _("Mask"), "expression": "{src}.filter_xdata", "sources": [{"name": "src", "label": _("Source")}]}
            vs["convert-to-scalar"] = {"title": _("Scalar"), "expression": "{src}.cropped_display_xdata",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["crop"] = {"title": _("Crop"), "expression": "{src}.cropped_display_xdata",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["sum"] = {"title": _("Sum"), "expression": "xd.sum({src}.cropped_xdata, {src}.xdata.datum_dimension_indexes[0])",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True, "requirements": [requirement_2d_to_4d]}]}
            slice_center_param = {"name": "center", "label": _("Center"), "type": "integral", "value": 0, "value_default": 0, "value_min": 0}
            slice_width_param = {"name": "width", "label": _("Width"), "type": "integral", "value": 1, "value_default": 1, "value_min": 1}
            vs["slice"] = {"title": _("Slice"), "expression": "xd.slice_sum({src}.cropped_xdata, center, width)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True, "requirements": [requirement_3d]}],
                "parameters": [slice_center_param, slice_width_param]}
            pick_in_region = {"name": "pick_region", "type": "point", "params": {"label": _("Pick Point")}}
            pick_out_region = {"name": "interval_region", "type": "interval", "params": {"label": _("Display Slice"), "role": "slice"}}
            vs["pick-point"] = {"title": _("Pick"), "expression": "xd.pick({src}.xdata, pick_region.position)",
                "sources": [{"name": "src", "label": _("Source"), "regions": [pick_in_region], "requirements": [requirement_4d_if_sequence_else_3d]}],
                "out_regions": [pick_out_region]}
            pick_sum_in_region = {"name": "region", "type": "rectangle", "params": {"label": _("Pick Region")}}
            pick_sum_out_region = {"name": "interval_region", "type": "interval", "params": {"label": _("Display Slice"), "role": "slice"}}
            vs["pick-mask-sum"] = {"title": _("Pick Sum"), "expression": "xd.sum_region({src}.xdata, region.mask_xdata_with_shape({src}.xdata.data_shape[-3:-1]))",
                "sources": [{"name": "src", "label": _("Source"), "regions": [pick_sum_in_region], "requirements": [requirement_4d_if_sequence_else_3d]}],
                "out_regions": [pick_sum_out_region]}
            vs["pick-mask-average"] = {"title": _("Pick Average"), "expression": "xd.average_region({src}.xdata, region.mask_xdata_with_shape({src}.xdata.data_shape[-3:-1]))",
                "sources": [{"name": "src", "label": _("Source"), "regions": [pick_sum_in_region], "requirements": [requirement_4d_if_sequence_else_3d]}],
                "out_regions": [pick_sum_out_region]}
            vs["subtract-mask-average"] = {"title": _("Subtract Average"), "expression": "{src}.xdata - xd.average_region({src}.xdata, region.mask_xdata_with_shape({src}.xdata.data_shape[0:2]))",
                "sources": [{"name": "src", "label": _("Source"), "regions": [pick_sum_in_region], "requirements": [requirement_3d]}],
                "out_regions": [pick_sum_out_region]}
            line_profile_in_region = {"name": "line_region", "type": "line", "params": {"label": _("Line Profile")}}
            vs["line-profile"] = {"title": _("Line Profile"), "expression": "xd.line_profile(xd.absolute({src}.element_xdata) if {src}.element_xdata.is_data_complex_type else {src}.element_xdata, line_region.vector, line_region.line_width)",
                "sources": [{"name": "src", "label": _("Source"), "regions": [line_profile_in_region]}]}
            vs["filter"] = {"title": _("Filter"), "expression": "xd.real(xd.ifft({src}.filtered_xdata))",
                "sources": [{"name": "src", "label": _("Source"), "requirements": [requirement_2d]}]}
            vs["sequence-register"] = {"title": _("Shifts"), "expression": "xd.sequence_squeeze_measurement(xd.sequence_measure_relative_translation({src}.xdata, {src}.xdata[numpy.unravel_index(0, {src}.xdata.navigation_dimension_shape)], 100))",
                "sources": [{"name": "src", "label": _("Source"), "requirements": [requirement_2d_to_3d]}]}
            vs["sequence-align"] = {"title": _("Alignment"), "expression": "xd.sequence_align({src}.xdata, 100)",
                "sources": [{"name": "src", "label": _("Source"), "requirements": [requirement_2d_to_5d, requirement_is_navigable]}]}
            vs["sequence-fourier-align"] = {"title": _("Alignment"), "expression": "xd.sequence_fourier_align({src}.xdata, 100)",
                "sources": [{"name": "src", "label": _("Source"), "requirements": [requirement_2d_to_5d, requirement_is_navigable]}]}
            vs["sequence-integrate"] = {"title": _("Integrate"), "expression": "xd.sequence_integrate({src}.xdata)",
                "sources": [{"name": "src", "label": _("Source"), "requirements": [requirement_is_sequence]}]}
            trim_start_param = {"name": "start", "label": _("Start"), "type": "integral", "value": 0, "value_default": 0, "value_min": 0}
            trim_end_param = {"name": "end", "label": _("End"), "type": "integral", "value": 1, "value_default": 1, "value_min": 1}
            vs["sequence-trim"] = {"title": _("Trim"), "expression": "xd.sequence_trim({src}.xdata, start, end)",
                "sources": [{"name": "src", "label": _("Source"), "requirements": [requirement_is_sequence]}],
                "parameters": [trim_start_param, trim_end_param]}
            index_param = {"name": "index", "label": _("Index"), "type": "integral", "value": 1, "value_default": 1, "value_min": 1}
            vs["sequence-extract"] = {"title": _("Extract"), "expression": "xd.sequence_extract({src}.xdata, index)",
                "sources": [{"name": "src", "label": _("Source"), "requirements": [requirement_is_sequence]}],
                "parameters": [index_param]}
            vs["make-rgb"] = {"title": _("RGB"), "expression": "xd.rgb({src_red}.cropped_transformed_xdata, {src_green}.cropped_transformed_xdata, {src_blue}.cropped_transformed_xdata)",
                "sources": [{"name": "src_red", "label": _("Red"), "croppable": True, "requirements": [requirement_2d]},
                            {"name": "src_green", "label": _("Green"), "croppable": True, "requirements": [requirement_2d]},
                            {"name": "src_blue", "label": _("Blue"), "croppable": True, "requirements": [requirement_2d]}]}
            vs["extract-luminance"] = {"title": _("Luminance"), "expression": "xd.luminance({src}.display_rgba)", "sources": [{"name": "src", "label": _("Source"), "requirements": [requirement_is_rgb_type]}]}
            vs["extract-red"] = {"title": _("Red"), "expression": "xd.red({src}.display_rgba)", "sources": [{"name": "src", "label": _("Source"), "requirements": [requirement_is_rgb_type]}]}
            vs["extract-green"] = {"title": _("Green"), "expression": "xd.green({src}.display_rgba)", "sources": [{"name": "src", "label": _("Source"), "requirements": [requirement_is_rgb_type]}]}
            vs["extract-blue"] = {"title": _("Blue"), "expression": "xd.blue({src}.display_rgba)", "sources": [{"name": "src", "label": _("Source"), "requirements": [requirement_is_rgb_type]}]}
            vs["extract-alpha"] = {"title": _("Alpha"), "expression": "xd.alpha({src}.display_rgba)", "sources": [{"name": "src", "label": _("Source"), "requirements": [requirement_is_rgb_type]}]}
            cls._builtin_processing_descriptions = vs
        return cls._builtin_processing_descriptions

    def get_fft_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("fft", [(display_item, data_item, crop_region)])

    def get_ifft_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("inverse-fft", [(display_item, data_item, crop_region)])

    def get_auto_correlate_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("auto-correlate", [(display_item, data_item, crop_region)])

    def get_cross_correlate_new(self, display_item1: DisplayItem.DisplayItem, data_item1: DataItem.DataItem, display_item2: DisplayItem.DisplayItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("cross-correlate", [(display_item1, data_item1, crop_region1), (display_item2, data_item2, crop_region2)])

    def get_sobel_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sobel", [(display_item, data_item, crop_region)])

    def get_laplace_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("laplace", [(display_item, data_item, crop_region)])

    def get_gaussian_blur_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("gaussian-blur", [(display_item, data_item, crop_region)])

    def get_median_filter_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("median-filter", [(display_item, data_item, crop_region)])

    def get_uniform_filter_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("uniform-filter", [(display_item, data_item, crop_region)])

    def get_transpose_flip_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("transpose-flip", [(display_item, data_item, crop_region)])

    def get_rebin_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("rebin", [(display_item, data_item, crop_region)])

    def get_resample_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("resample", [(display_item, data_item, crop_region)])

    def get_resize_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("resize", [(display_item, data_item, crop_region)])

    def get_redimension_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, data_descriptor: DataAndMetadata.DataDescriptor) -> DataItem.DataItem:
        return self.__make_computation("redimension", [(display_item, data_item, None)], parameters={"is_sequence": data_descriptor.is_sequence, "collection_dims": data_descriptor.collection_dimension_count, "datum_dims": data_descriptor.datum_dimension_count})

    def get_squeeze_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem) -> DataItem.DataItem:
        return self.__make_computation("squeeze", [(display_item, data_item, None)])

    def get_histogram_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("histogram", [(display_item, data_item, crop_region)])

    def get_add_new(self, display_item1: DisplayItem.DisplayItem, data_item1: DataItem.DataItem, display_item2: DisplayItem.DisplayItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("add", [(display_item1, data_item1, crop_region1), (display_item2, data_item2, crop_region2)])

    def get_subtract_new(self, display_item1: DisplayItem.DisplayItem, data_item1: DataItem.DataItem, display_item2: DisplayItem.DisplayItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("subtract", [(display_item1, data_item1, crop_region1), (display_item2, data_item2, crop_region2)])

    def get_multiply_new(self, display_item1: DisplayItem.DisplayItem, data_item1: DataItem.DataItem, display_item2: DisplayItem.DisplayItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("multiply", [(display_item1, data_item1, crop_region1), (display_item2, data_item2, crop_region2)])

    def get_divide_new(self, display_item1: DisplayItem.DisplayItem, data_item1: DataItem.DataItem, display_item2: DisplayItem.DisplayItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("divide", [(display_item1, data_item1, crop_region1), (display_item2, data_item2, crop_region2)])

    def get_invert_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("invert", [(display_item, data_item, crop_region)])

    def get_masked_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("masked", [(display_item, data_item, crop_region)])

    def get_mask_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("mask", [(display_item, data_item, crop_region)])

    def get_convert_to_scalar_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("convert-to-scalar", [(display_item, data_item, crop_region)])

    def get_crop_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        if data_item and display_item and not crop_region:
            if data_item.is_data_2d:
                rect_region = Graphics.RectangleGraphic()
                rect_region.center = 0.5, 0.5
                rect_region.size = 0.5, 0.5
                display_item.add_graphic(rect_region)
                crop_region = rect_region
            elif data_item.is_data_1d:
                interval_region = Graphics.IntervalGraphic()
                interval_region.interval = 0.25, 0.75
                display_item.add_graphic(interval_region)
                crop_region = interval_region
        return self.__make_computation("crop", [(display_item, data_item, crop_region)])

    def get_projection_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sum", [(display_item, data_item, crop_region)])

    def get_slice_sum_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("slice", [(display_item, data_item, crop_region)])

    def get_pick_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, pick_region: Graphics.PointTypeGraphic=None) -> DataItem.DataItem:
        data_item = self.__make_computation("pick-point", [(display_item, data_item, crop_region)], {"src": [pick_region]})
        if data_item:
            display_data_channel = display_item.display_data_channels[0]
            if display_data_channel.slice_center == 0 and display_data_channel.slice_width == 1:
                display_data_channel.slice_interval = (0.05, 0.15)
        return data_item

    def get_pick_region_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, pick_region: Graphics.Graphic=None) -> DataItem.DataItem:
        data_item = self.__make_computation("pick-mask-sum", [(display_item, data_item, crop_region)], {"src": [pick_region]})
        if data_item:
            display_data_channel = display_item.display_data_channels[0]
            if display_data_channel.slice_center == 0 and display_data_channel.slice_width == 1:
                display_data_channel.slice_interval = (0.05, 0.15)
        return data_item

    def get_pick_region_average_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, pick_region: Graphics.Graphic=None) -> DataItem.DataItem:
        data_item = self.__make_computation("pick-mask-average", [(display_item, data_item, crop_region)], {"src": [pick_region]})
        if data_item:
            display_data_channel = display_item.display_data_channels[0]
            if display_data_channel.slice_center == 0 and display_data_channel.slice_width == 1:
                display_data_channel.slice_interval = (0.05, 0.15)
        return data_item

    def get_subtract_region_average_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, pick_region: Graphics.Graphic=None) -> DataItem.DataItem:
        return self.__make_computation("subtract-mask-average", [(display_item, data_item, crop_region)], {"src": [pick_region]})

    def get_line_profile_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, line_region: Graphics.LineTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("line-profile", [(display_item, data_item, crop_region)], {"src": [line_region]})

    def get_fourier_filter_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        data_item = display_item.data_item
        if data_item and display_item:
            has_mask = False
            for graphic in display_item.graphics:
                if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
                    has_mask = True
                    break
            if not has_mask:
                graphic = Graphics.RingGraphic()
                graphic.radius_1 = 0.15
                graphic.radius_2 = 0.25
                display_item.add_graphic(graphic)
        return self.__make_computation("filter", [(display_item, data_item, crop_region)])

    def get_processing_new(self, processing_id: str, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation(processing_id, [(display_item, data_item, crop_region)])

    def get_sequence_measure_shifts_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sequence-register", [(display_item, data_item, crop_region)])

    def get_sequence_align_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sequence-align", [(display_item, data_item, crop_region)])

    def get_sequence_fourier_align_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sequence-fourier-align", [(display_item, data_item, crop_region)])

    def get_sequence_integrate_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sequence-integrate", [(display_item, data_item, crop_region)])

    def get_sequence_trim_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sequence-trim", [(display_item, data_item, crop_region)])

    def get_sequence_extract_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sequence-extract", [(display_item, data_item, crop_region)])

    def get_rgb_new(self, display_item1: DisplayItem.DisplayItem, data_item1: DataItem.DataItem, display_item2: DisplayItem.DisplayItem, data_item2: DataItem.DataItem, display_item3: DisplayItem.DisplayItem, data_item3: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None, crop_region3: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("make-rgb", [(display_item1, data_item1, crop_region1),
                                                    (display_item2, data_item2, crop_region2),
                                                    (display_item3, data_item3, crop_region3)])

    def get_rgb_alpha_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("extract-alpha", [(display_item, data_item, crop_region)])

    def get_rgb_blue_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("extract-blue", [(display_item, data_item, crop_region)])

    def get_rgb_green_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("extract-green", [(display_item, data_item, crop_region)])

    def get_rgb_luminance_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("extract-luminance", [(display_item, data_item, crop_region)])

    def get_rgb_red_new(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("extract-red", [(display_item, data_item, crop_region)])


class ConnectPickDisplay(Observer.AbstractAction):

    def __init__(self, document_model: DocumentModel, item_value: Observer.ItemValue):
        self.__document_model = document_model
        self.__implicit_dependency = None
        self.__sequence_index_property_connector = None
        self.__slice_interval_property_connector = None

        if item_value and isinstance(item_value, tuple):
            item_value = typing.cast(typing.Tuple[DisplayItem.DisplayDataChannel, typing.Sequence[Graphics.IntervalGraphic]], item_value)
            if len(item_value) == 2 and item_value[0] and item_value[1]:
                display_data_channel = item_value[0]
                interval_graphics = item_value[1]

                sequence_index_property_connector_items = list()
                slice_interval_property_connector_items = list()

                sequence_index_property_connector_items.append(Connector.PropertyConnectorItem(display_data_channel, "sequence_index"))
                slice_interval_property_connector_items.append(Connector.PropertyConnectorItem(display_data_channel, "slice_interval"))

                for interval_graphic in interval_graphics:
                    slice_interval_property_connector_items.append(Connector.PropertyConnectorItem(interval_graphic, "interval"))
                    for interval_display_data_channel in typing.cast(typing.Sequence[DisplayItem.DisplayDataChannel], interval_graphic.container.display_data_channels):
                        sequence_index_property_connector_items.append(Connector.PropertyConnectorItem(interval_display_data_channel, "sequence_index"))

                self.__sequence_index_property_connector = Connector.PropertyConnector(sequence_index_property_connector_items)
                self.__slice_interval_property_connector = Connector.PropertyConnector(slice_interval_property_connector_items)

                self.__implicit_dependency = ImplicitDependency(interval_graphics, display_data_channel)
                document_model.register_implicit_dependency(self.__implicit_dependency)

    def close(self) -> None:
        if self.__sequence_index_property_connector:
            self.__sequence_index_property_connector.close()
            self.__sequence_index_property_connector = None
        if self.__slice_interval_property_connector:
            self.__slice_interval_property_connector.close()
            self.__slice_interval_property_connector = None
        if self.__implicit_dependency:
            self.__document_model.unregister_implicit_dependency(self.__implicit_dependency)


class ImplicitPickConnection:
    """Facilitate connections between a sequence/collection of 1D data and a line plot from a pick-style computation.

    When the sequence/collection slice interval changes, update the line plot display slice interval (if present).

    When the line plot display slice interval changes, update the sequence/collection slice interval.

    When the sequence/collection sequence index changes, update the line plot sequence index.

    When the line plot sequence index changes, update the sequence/collection sequence index.
    """

    def __init__(self, document_model: DocumentModel):

        def match_pick(computation: Symbolic.Computation) -> bool:
            return computation.processing_id in ("pick-point", "pick-mask-sum", "pick-mask-average", "subtract-mask-average")

        def match_graphic(graphic: Graphics.Graphic) -> bool:
            return graphic.role == "slice"

        # use an observer builder to construct the observer
        oo = Observer.ObserverBuilder()

        # match the pick-style computation
        matched_computations = oo.source(document_model).sequence_from_array("computations", predicate=match_pick)

        # select the _display_data_channel of the bound_item of the first computation input variable this observer is
        # created as a sub-observer (x) and will be applied to each item from the container (computations).
        computation_display_data_channel = oo.x.ordered_sequence_from_array("variables").index(0).prop("bound_item").get("_display_data_channel")

        # select the _data_item of the bound_item of the first computation output variable this observer is created as a
        # sub-observer (x) and will serve as the base for the further selection of the display items
        computation_result_data_item = oo.x.ordered_sequence_from_array("results").index(0).prop("bound_item").get("_data_item")

        # select the display_items from each of the display data channels from each of the data items. this serves as
        # the base for further selection of the interval graphics.
        computation_result_display_items = computation_result_data_item.sequence_from_set("display_data_channels").map(oo.x.prop("display_item"))

        # select the graphics items of the container object (display items) and collect them into a list this observer
        # is created as a sub-observer (x) and will be applied to each item from the container (display items).
        slice_interval_graphic = oo.x.sequence_from_array("graphics", predicate=match_graphic).collect_list()

        # select the graphics as a list from each display item and then further collect into a list and flatten that
        # list.
        computation_result_graphics = computation_result_display_items.map(slice_interval_graphic).collect_list().flatten()

        # create the action to connect the various properties. this will be recreated whenever its inputs change.
        connect_action = typing.cast(typing.Callable[[Observer.ItemValue], Observer.AbstractAction], functools.partial(ConnectPickDisplay, document_model))

        # configure the action (connecting the properties) as each tuple is produced from the matching computations.
        matched_computations.for_each(oo.x.tuple(computation_display_data_channel, computation_result_graphics).action(connect_action))

        # finally, construct the observer and save it.
        self.__observer = oo.make_observable()

    def close(self) -> None:
        self.__observer.close()


class ConnectMapDisplay(Observer.AbstractAction):

    def __init__(self, document_model: DocumentModel, item_value: Observer.ItemValue):
        self.__document_model = document_model
        self.__implicit_dependency = None
        self.__sequence_index_property_connector = None
        self.__slice_interval_property_connector = None

        if item_value and isinstance(item_value, tuple):
            item_value = typing.cast(typing.Tuple[DisplayItem.DisplayDataChannel, typing.Sequence[Graphics.PointGraphic]], item_value)
            if len(item_value) == 2 and item_value[0] and item_value[1]:
                display_data_channel = item_value[0]
                point_graphics = item_value[1]

                sequence_index_property_connector_items = list()
                collection_point_property_connector_items = list()

                sequence_index_property_connector_items.append(Connector.PropertyConnectorItem(display_data_channel, "sequence_index"))
                collection_point_property_connector_items.append(Connector.PropertyConnectorItem(display_data_channel, "collection_point"))

                for point_graphic in point_graphics:
                    collection_point_property_connector_items.append(Connector.PropertyConnectorItem(point_graphic, "position"))
                    for interval_display_data_channel in typing.cast(typing.Sequence[DisplayItem.DisplayDataChannel], point_graphic.container.display_data_channels):
                        sequence_index_property_connector_items.append(Connector.PropertyConnectorItem(interval_display_data_channel, "sequence_index"))

                self.__sequence_index_property_connector = Connector.PropertyConnector(sequence_index_property_connector_items)
                self.__slice_interval_property_connector = Connector.PropertyConnector(collection_point_property_connector_items)

                self.__implicit_dependency = ImplicitDependency(point_graphics, display_data_channel)
                document_model.register_implicit_dependency(self.__implicit_dependency)

    def close(self) -> None:
        if self.__sequence_index_property_connector:
            self.__sequence_index_property_connector.close()
            self.__sequence_index_property_connector = None
        if self.__slice_interval_property_connector:
            self.__slice_interval_property_connector.close()
            self.__slice_interval_property_connector = None
        if self.__implicit_dependency:
            self.__document_model.unregister_implicit_dependency(self.__implicit_dependency)


class ImplicitMapConnection:
    def __init__(self, document_model: DocumentModel):

        def match_pick(computation: Symbolic.Computation) -> bool:
            if computation.get_computation_attribute("connection_type", None) == "map":
                return True
            if DocumentModel._builtin_processing_descriptions.get(computation.processing_id, dict()).get("attributes", dict()).get("connection_type", None) == "map":
                return True
            return False

        def match_graphic(graphic: Graphics.Graphic) -> bool:
            return graphic.role == "collection_index"

        oo = Observer.ObserverBuilder()

        matched_computations = oo.source(document_model).sequence_from_array("computations", predicate=match_pick)
        computation_display_data_channel = oo.x.ordered_sequence_from_array("variables").index(0).prop("bound_item").get("_display_data_channel")
        computation_result_data_item = oo.x.ordered_sequence_from_array("results").index(0).prop("bound_item").get("_data_item")
        computation_result_display_items = computation_result_data_item.sequence_from_set("display_data_channels").map(oo.x.prop("display_item"))
        slice_interval_graphic = oo.x.sequence_from_array("graphics", predicate=match_graphic).collect_list()
        computation_result_graphics = computation_result_display_items.map(slice_interval_graphic).collect_list().flatten()
        connect_action = typing.cast(typing.Callable[[Observer.ItemValue], Observer.AbstractAction], functools.partial(ConnectMapDisplay, document_model))
        matched_computations.for_each(oo.x.tuple(computation_display_data_channel, computation_result_graphics).action(connect_action))

        self.__observer = oo.make_observable()

    def close(self) -> None:
        self.__observer.close()


class IntervalListConnector(Observer.AbstractAction):

    def __init__(self, document_model: DocumentModel, item_value: Observer.ItemValue):
        self.__document_model = document_model
        self.__listeners = list()
        self.__implicit_dependency = None

        if item_value and isinstance(item_value, tuple):
            item_value = typing.cast(typing.Tuple[Graphics.LineProfileGraphic, typing.Sequence[Graphics.IntervalGraphic]], item_value)
            if len(item_value) == 2 and item_value[0] and item_value[1] is not None:
                line_profile_graphic = item_value[0]
                interval_graphics = item_value[1]

                def property_changed(key):
                    if key == "interval":
                        interval_descriptors = list()
                        for interval_graphic in interval_graphics:
                            interval_descriptor = {"interval": interval_graphic.interval, "color": "#F00"}
                            interval_descriptors.append(interval_descriptor)
                        line_profile_graphic.interval_descriptors = interval_descriptors

                for interval_graphic in interval_graphics:
                    self.__listeners.append(interval_graphic.property_changed_event.listen(property_changed))

                property_changed("interval")

                self.__implicit_dependency = ImplicitDependency(interval_graphics, line_profile_graphic)
                document_model.register_implicit_dependency(self.__implicit_dependency)

    def close(self) -> None:
        for listener in self.__listeners:
            listener.close()
        if self.__implicit_dependency:
            self.__document_model.unregister_implicit_dependency(self.__implicit_dependency)
        self.__listeners = None


class ImplicitLineProfileIntervalsConnection:

    def __init__(self, document_model: DocumentModel):

        def match_line_profile(computation: Symbolic.Computation) -> bool:
            return computation.processing_id in ("line-profile",)

        def match_graphic(graphic: Graphics.Graphic) -> bool:
            return isinstance(graphic, Graphics.IntervalGraphic)

        oo = Observer.ObserverBuilder()
        matched_computations = oo.source(document_model).sequence_from_array("computations", predicate=match_line_profile)
        computation_display_data_channel = oo.x.ordered_sequence_from_array("variables").index(1).prop("bound_item").get("_graphic")
        interval_graphics = oo.x.sequence_from_array("graphics", predicate=match_graphic).collect_list()
        computation_result_data_item = oo.x.ordered_sequence_from_array("results").index(0).prop("bound_item").get("_data_item")
        computation_result_display_items = computation_result_data_item.sequence_from_set("display_data_channels").map(oo.x.prop("display_item"))
        computation_result_graphics = computation_result_display_items.map(interval_graphics).collect_list().flatten()
        connect_action = typing.cast(typing.Callable[[Observer.ItemValue], Observer.AbstractAction], functools.partial(IntervalListConnector, document_model))
        matched_computations.for_each(oo.x.tuple(computation_display_data_channel, computation_result_graphics).action(connect_action))
        self.__observer = oo.make_observable()

    def close(self) -> None:
        self.__observer.close()


DocumentModel.register_processing_descriptions(DocumentModel._get_builtin_processing_descriptions())


def evaluate_data(computation) -> DataAndMetadata.DataAndMetadata:
    api = PlugInManager.api_broker_fn("~1.0", None)
    data_item = DataItem.new_data_item(None)
    with contextlib.closing(data_item):
        api_data_item = api._new_api_object(data_item)
        if computation.expression:
            error_text = computation.evaluate_with_target(api, api_data_item)
            computation.error_text = error_text
            return api_data_item.data_and_metadata
        else:
            compute_obj, error_text = computation.evaluate(api)
            compute_obj.commit()
            computation.error_text = error_text
            return computation.get_output("target").xdata
