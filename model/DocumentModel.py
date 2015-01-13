# standard libraries
import collections
import copy
import datetime
import gettext
import json
import logging
import numbers
import os.path
import Queue as queue
import threading
import uuid
import weakref

# third party libraries
import scipy

# local libraries
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import HardwareSource
from nion.swift.model import Image
from nion.swift.model import ImportExportManager
from nion.swift.model import Storage
from nion.swift.model import Utility
from nion.swift.model import WorkspaceLayout
from nion.ui import Observable
from nion.ui import ThreadPool

_ = gettext.gettext


class DataReferenceMemoryHandler(object):

    """ Used for testing. """

    def __init__(self):
        self.data = dict()
        self.properties = dict()

    def find_data_item_tuples(self):
        tuples = []
        for key in self.properties:
            properties = self.properties[key]
            tuples.append((properties.setdefault("uuid", str(uuid.uuid4())), copy.deepcopy(properties), "relative_file", key))
        return tuples

    def load_data_reference(self, reference_type, reference):
        return self.data.get(reference)

    def write_data_reference(self, data, reference_type, reference, file_datetime):
        self.data[reference] = data.copy()

    def write_properties(self, properties, reference_type, reference, file_datetime):
        self.properties[reference] = copy.deepcopy(properties)

    def remove_data_reference(self, reference_type, reference):
        if reference in self.data:
            del self.data[reference]
        if reference in self.properties:
            del self.properties[reference]


class FilePersistentStorage(object):

    def __init__(self, filepath=None, create=True):
        self.__filepath = filepath
        self.__properties = self.__read_properties()
        self.__properties_lock = threading.RLock()

    def get_version(self):
        return 0

    def __read_properties(self):
        properties = dict()
        if self.__filepath and os.path.exists(self.__filepath):
            with open(self.__filepath, "r") as fp:
                properties = json.load(fp)
        # migrations go here
        return properties

    def __get_properties(self):
        with self.__properties_lock:
            return copy.deepcopy(self.__properties)
    properties = property(__get_properties)

    def __get_storage_dict(self, object):
        managed_parent = object.managed_parent
        if not managed_parent:
            return self.__properties
        else:
            parent_storage_dict = self.__get_storage_dict(managed_parent.parent)
            return object.get_accessor_in_parent()(parent_storage_dict)

    def update_properties(self):
        if self.__filepath:
            with open(self.__filepath, "w") as fp:
                properties = json.dump(self.__properties, fp)

    def insert_item(self, parent, name, before_index, item):
        storage_dict = self.__get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict.setdefault(name, list())
            item_dict = item.write_to_dict()
            item_list.insert(before_index, item_dict)
            item.managed_object_context = parent.managed_object_context
        self.update_properties()

    def remove_item(self, parent, name, index, item):
        storage_dict = self.__get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict[name]
            del item_list[index]
        self.update_properties()
        item.managed_object_context = None

    def set_item(self, parent, name, item):
        storage_dict = self.__get_storage_dict(parent)
        with self.__properties_lock:
            if item:
                item_dict = item.write_to_dict()
                storage_dict[name] = item_dict
                item.managed_object_context = parent.managed_object_context
            else:
                if name in storage_dict:
                    del storage_dict[name]
        self.update_properties()

    def set_value(self, object, name, value):
        storage_dict = self.__get_storage_dict(object)
        with self.__properties_lock:
            storage_dict[name] = value
        self.update_properties()


class DataItemPersistentStorage(object):

    """
        Manages persistent storage for data items by caching properties and data, maintaining the ManagedObjectContext
        on contained items, and writing to disk when necessary.
    """

    def __init__(self, data_reference_handler=None, data_item=None, properties=None, reference_type=None, reference=None):
        self.__data_reference_handler = data_reference_handler
        self.__data_reference_handler_lock = threading.RLock()
        self.__properties = copy.deepcopy(properties) if properties else dict()
        self.__properties_lock = threading.RLock()
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
        # reference type and reference indicate how to save/load data and properties
        self.reference_type = reference_type
        self.reference = reference
        self.write_delayed = False

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    def __set_data_item(self, data_item):
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
    data_item = property(__get_data_item, __set_data_item)

    def __get_properties(self):
        with self.__properties_lock:
            return copy.deepcopy(self.__properties)
    properties = property(__get_properties)

    def __get_properties_lock(self):
        return self.__properties_lock
    properties_lock = property(__get_properties_lock)

    def __get_storage_dict(self, object):
        managed_parent = object.managed_parent
        if not managed_parent:
            return self.__properties
        else:
            parent_storage_dict = self.__get_storage_dict(managed_parent.parent)
            return object.get_accessor_in_parent()(parent_storage_dict)

    def update_properties(self):
        if not self.write_delayed:
            self.__ensure_reference_valid(self.data_item)
            file_datetime = Utility.get_datetime_from_datetime_item(self.data_item.datetime_original)
            with self.__data_reference_handler_lock:
                self.__data_reference_handler.write_properties(self.properties, "relative_file", self.reference, file_datetime)

    def insert_item(self, parent, name, before_index, item):
        storage_dict = self.__get_storage_dict(parent)
        with self.properties_lock:
            item_list = storage_dict.setdefault(name, list())
            item_dict = item.write_to_dict()
            item_list.insert(before_index, item_dict)
            item.managed_object_context = parent.managed_object_context
        self.update_properties()

    def remove_item(self, parent, name, index, item):
        storage_dict = self.__get_storage_dict(parent)
        with self.properties_lock:
            item_list = storage_dict[name]
            del item_list[index]
        self.update_properties()
        item.managed_object_context = None

    def set_item(self, parent, name, item):
        storage_dict = self.__get_storage_dict(parent)
        with self.__properties_lock:
            if item:
                item_dict = item.write_to_dict()
                storage_dict[name] = item_dict
                item.managed_object_context = parent.managed_object_context
            else:
                if name in storage_dict:
                    del storage_dict[name]
        self.update_properties()

    def get_default_reference(self, data_item):
        uuid_ = data_item.uuid
        datetime_item = data_item.datetime_original
        session_id = data_item.session_id
        # uuid_.bytes.encode('base64').rstrip('=\n').replace('/', '_')
        # and back: uuid_ = uuid.UUID(bytes=(slug + '==').replace('_', '/').decode('base64'))
        # also:
        def encode(uuid_, alphabet):
            result = str()
            uuid_int = uuid_.int
            while uuid_int:
                uuid_int, digit = divmod(uuid_int, len(alphabet))
                result += alphabet[digit]
            return result
        encoded_uuid_str = encode(uuid_, "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")  # 25 character results
        datetime_item = datetime_item if datetime_item else Utility.get_current_datetime_item()
        datetime_ = Utility.get_datetime_from_datetime_item(datetime_item)
        datetime_ = datetime_ if datetime_ else datetime.datetime.now()
        path_components = datetime_.strftime("%Y-%m-%d").split('-')
        session_id = session_id if session_id else datetime_.strftime("%Y%m%d-000000")
        path_components.append(session_id)
        path_components.append("data_" + encoded_uuid_str)
        return os.path.join(*path_components)

    def __ensure_reference_valid(self, data_item):
        if not self.reference:
            self.reference_type = "relative_file"
            self.reference = self.get_default_reference(data_item)

    def update_data(self, data_shape, data_dtype, data=None):
        if not self.write_delayed:
            self.__ensure_reference_valid(self.data_item)
            file_datetime = Utility.get_datetime_from_datetime_item(self.data_item.datetime_original)
            if data is not None:
                with self.__data_reference_handler_lock:
                    self.__data_reference_handler.write_data_reference(data, "relative_file", self.reference, file_datetime)

    def load_data(self):
        assert self.data_item.has_master_data
        with self.__data_reference_handler_lock:
            return self.__data_reference_handler.load_data_reference(self.reference_type, self.reference)

    def set_value(self, object, name, value):
        storage_dict = self.__get_storage_dict(object)
        with self.properties_lock:
            storage_dict[name] = value
        self.update_properties()


class ManagedDataItemContext(Observable.ManagedObjectContext):

    """
        A ManagedObjectContext that adds extra methods for handling data items.

        Versioning

        If the file is too old, it must be migrated to the newer version.
        If the file is too new, it cannot be loaded.

        When writing, the version the file format is written to the 'version' property.

    """

    def __init__(self, data_reference_handler, log_migrations):
        super(ManagedDataItemContext, self).__init__()
        self.__data_reference_handler = data_reference_handler
        self.__log_migrations = log_migrations

    def read_data_items(self):
        """
        Read data items from the data reference handler and return as a list.

        Data items will have managed_object_context set upon return, but caller will need to call finish_reading
        on each of the data items.
        """
        data_item_tuples = self.__data_reference_handler.find_data_item_tuples()
        data_items = list()
        for data_item_uuid, properties, reference_type, reference in data_item_tuples:
            try:
                version = properties.get("version", 0)
                if version <= 1:
                    if "spatial_calibrations" in properties:
                        properties["intrinsic_spatial_calibrations"] = properties["spatial_calibrations"]
                        del properties["spatial_calibrations"]
                    if "intensity_calibration" in properties:
                        properties["intrinsic_intensity_calibration"] = properties["intensity_calibration"]
                        del properties["intensity_calibration"]
                    if "data_source_uuid" in properties:
                        # for now, this is not translated into v2. it was an extra item.
                        del properties["data_source_uuid"]
                    if "properties" in properties:
                        old_properties = properties["properties"]
                        new_properties = properties.setdefault("hardware_source", dict())
                        new_properties.update(copy.deepcopy(old_properties))
                        if "session_uuid" in new_properties:
                            del new_properties["session_uuid"]
                        del properties["properties"]
                    temp_data = self.__data_reference_handler.load_data_reference(reference_type, reference)
                    if temp_data is not None:
                        properties["master_data_dtype"] = str(temp_data.dtype)
                        properties["master_data_shape"] = temp_data.shape
                    properties["displays"] = [{}]
                    properties["uuid"] = str(uuid.uuid4())  # assign a new uuid
                    properties["version"] = 2
                    # rewrite needed since we added a uuid
                    self.__data_reference_handler.write_properties(copy.deepcopy(properties), "relative_file", reference, datetime.datetime.now())
                    version = 2
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (ndata1)", reference, version)
                if version == 2:
                    # version 2 -> 3 adds uuid's to displays, graphics, and operations. regions already have uuids.
                    for display_properties in properties.get("displays", list()):
                        display_properties.setdefault("uuid", str(uuid.uuid4()))
                        for graphic_properties in display_properties.get("graphics", list()):
                            graphic_properties.setdefault("uuid", str(uuid.uuid4()))
                    for operation_properties in properties.get("operations", list()):
                        operation_properties.setdefault("uuid", str(uuid.uuid4()))
                    properties["version"] = 3
                    # rewrite needed since we added a uuid
                    self.__data_reference_handler.write_properties(copy.deepcopy(properties), "relative_file", reference, datetime.datetime.now())
                    version = 3
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (add uuids)", reference, version)
                if version == 3:
                    # version 3 -> 4 changes origin to offset in all calibrations.
                    calibration_dict = properties.get("intrinsic_intensity_calibration", dict())
                    if "origin" in calibration_dict:
                        calibration_dict["offset"] = calibration_dict["origin"]
                        del calibration_dict["origin"]
                    for calibration_dict in properties.get("intrinsic_spatial_calibrations", list()):
                        if "origin" in calibration_dict:
                            calibration_dict["offset"] = calibration_dict["origin"]
                            del calibration_dict["origin"]
                    properties["version"] = 4
                    # no rewrite needed
                    # self.__data_reference_handler.write_properties(copy.deepcopy(properties), "relative_file", reference, datetime.datetime.now())
                    version = 4
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (calibration offset)", reference, version)
                if version == 4:
                    # version 4 -> 5 changes region_uuid to region_connections map.
                    operations_list = properties.get("operations", list())
                    for operation_dict in operations_list:
                        if operation_dict["operation_id"] == "crop-operation" and "region_uuid" in operation_dict:
                            operation_dict["region_connections"] = { "crop": operation_dict["region_uuid"] }
                            del operation_dict["region_uuid"]
                        elif operation_dict["operation_id"] == "line-profile-operation" and "region_uuid" in operation_dict:
                            operation_dict["region_connections"] = { "line": operation_dict["region_uuid"] }
                            del operation_dict["region_uuid"]
                    properties["version"] = 5
                    # no rewrite needed
                    # self.__data_reference_handler.write_properties(copy.deepcopy(properties), "relative_file", reference, datetime.datetime.now())
                    version = 5
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (region_uuid)", reference, version)
                if version == 5:
                    # version 5 -> 6 changes operations to a single operation, expands data sources list
                    operations_list = properties.get("operations", list())
                    if len(operations_list) == 1:
                        operation_dict = operations_list[0]
                        operation_dict["type"] = "operation"
                        properties["operation"] = operation_dict
                        data_sources_list = properties.get("data_sources", list())
                        if len(data_sources_list) > 0:
                            new_data_sources_list = list()
                            for data_source_uuid_str in data_sources_list:
                                new_data_sources_list.append({"type": "data-item-data-source", "data_item_uuid": data_source_uuid_str})
                            operation_dict["data_sources"] = new_data_sources_list
                    if "operations" in properties:
                        del properties["operations"]
                    if "data_sources" in properties:
                        del properties["data_sources"]
                    if "intrinsic_intensity_calibration" in properties:
                        properties["intensity_calibration"] = properties["intrinsic_intensity_calibration"]
                        del properties["intrinsic_intensity_calibration"]
                    if "intrinsic_spatial_calibrations" in properties:
                        properties["dimensional_calibrations"] = properties["intrinsic_spatial_calibrations"]
                        del properties["intrinsic_spatial_calibrations"]
                    properties["version"] = 6
                    # no rewrite needed
                    # self.__data_reference_handler.write_properties(copy.deepcopy(properties), "relative_file", reference, datetime.datetime.now())
                    version = 6
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (operation hierarchy)", reference, version)
                # NOTE: Search for to-do 'file format' to gather together 'would be nice' changes
                # NOTE: change writer_version in DataItem.py
                data_item = DataItem.DataItem(item_uuid=data_item_uuid, create_display=False)
                if version <= data_item.writer_version:
                    data_item.begin_reading()
                    persistent_storage = DataItemPersistentStorage(data_reference_handler=self.__data_reference_handler, data_item=data_item, properties=properties, reference_type=reference_type, reference=reference)
                    data_item.read_from_dict(persistent_storage.properties)
                    assert(len(data_item.displays) > 0)
                    self.set_persistent_storage_for_object(data_item, persistent_storage)
                    data_item.managed_object_context = self
                    data_items.append(data_item)
            except Exception as e:
                logging.info("Error reading %s (uuid=%s)", reference, data_item_uuid)
                import traceback
                traceback.print_exc()
                traceback.print_stack()
        # all sorts of interconnections may occur between data items and other objects.
        # give the data item a chance to mark itself clean after reading all of them in.
        def sort_by_date_key(data_item):
            return Utility.get_datetime_from_datetime_item(data_item.datetime_original)
        data_items.sort(key=sort_by_date_key)
        return data_items

    def write_data_item(self, data_item):
        """ Write data item to persistent storage. """
        properties = data_item.write_to_dict()
        persistent_storage = DataItemPersistentStorage(data_reference_handler=self.__data_reference_handler, data_item=data_item, properties=properties)
        self.set_persistent_storage_for_object(data_item, persistent_storage)
        self.property_changed(data_item, "uuid", str(data_item.uuid))
        self.property_changed(data_item, "version", data_item.writer_version)
        with data_item.data_ref() as data_ref:
            self.rewrite_data_item_data(data_item, data=data_ref.master_data)

    def rewrite_data_item_data(self, data_item, data):
        persistent_storage = self.get_persistent_storage_for_object(data_item)
        persistent_storage.update_data(data_item.master_data_shape, data_item.master_data_dtype, data=data)

    def erase_data_item(self, data_item):
        persistent_storage = self.get_persistent_storage_for_object(data_item)
        self.__data_reference_handler.remove_data_reference(persistent_storage.reference_type, persistent_storage.reference)
        data_item.managed_object_context = None

    def load_data(self, data_item):
        persistent_storage = self.get_persistent_storage_for_object(data_item)
        return persistent_storage.load_data()

    def get_data_item_file_info(self, data_item):
        persistent_storage = self.get_persistent_storage_for_object(data_item)
        return persistent_storage.reference_type, persistent_storage.reference


class UuidToStringConverter(object):
    def convert(self, value):
        return str(value)
    def convert_back(self, value):
        return uuid.UUID(value)


class DocumentModel(Observable.Observable, Observable.Broadcaster, Observable.ReferenceCounted, Observable.ManagedObject):

    """The document model manages storage and dependencies between data items and other objects.

    The document model provides a dispatcher object which will run tasks in a thread pool.
    """

    def __init__(self, library_storage=None, data_reference_handler=None, storage_cache=None, log_migrations=True):
        super(DocumentModel, self).__init__()
        self.__thread_pool = ThreadPool.ThreadPool()
        data_reference_handler = data_reference_handler if data_reference_handler else DataReferenceMemoryHandler()
        self.managed_object_context = ManagedDataItemContext(data_reference_handler, log_migrations)
        self.__library_storage = library_storage if library_storage else FilePersistentStorage()
        self.managed_object_context.set_persistent_storage_for_object(self, self.__library_storage)
        self.storage_cache = storage_cache if storage_cache else Storage.DictStorageCache()
        self.__data_items = list()
        self.define_type("library")
        self.define_relationship("data_groups", DataGroup.data_group_factory)
        self.define_relationship("workspaces", WorkspaceLayout.factory)
        self.define_property("workspace_uuid", converter=UuidToStringConverter())
        self.session_id = None
        self.start_new_session()
        self.__data_item_listeners = dict()
        self.__read()
        self.__library_storage.set_value(self, "uuid", str(self.uuid))
        self.__library_storage.set_value(self, "version", 0)

    def __read(self):
        # first read the items
        self.read_from_dict(self.__library_storage.properties)
        data_items = self.managed_object_context.read_data_items()
        for index, data_item in enumerate(data_items):
            self.__data_items.insert(index, data_item)
            data_item.storage_cache = self.storage_cache
            data_item.add_listener(self)
            data_item.set_data_item_manager(self)
        for data_item in data_items:
            data_item.finish_reading()
        # all data items will already have a managed_object_context
        for data_group in self.data_groups:
            data_group.connect_data_items(self.get_data_item_by_uuid)

    def close(self):
        HardwareSource.HardwareSourceManager().abort_all_and_close()
        self.__thread_pool.close()
        for data_item in self.data_items:
            data_item.close()
        self.storage_cache.close()

    def about_to_delete(self):
        # override from ReferenceCounted. several DocumentControllers may retain references
        self.close()

    def start_new_session(self):
        self.session_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    def append_workspace(self, workspace):
        self.insert_workspace(len(self.workspaces), workspace)

    def insert_workspace(self, before_index, workspace):
        self.insert_item("workspaces", before_index, workspace)
        self.notify_insert_item("workspaces", workspace, before_index)

    def remove_workspace(self, workspace):
        index = self.workspaces.index(workspace)
        self.remove_item("workspaces", workspace)
        self.notify_remove_item("workspaces", workspace, index)

    def append_data_item(self, data_item):
        self.insert_data_item(len(self.data_items), data_item)

    def insert_data_item(self, before_index, data_item):
        """ Insert a new data item into document model. Data item will have managed_object_context set upon return. """
        assert data_item is not None
        assert data_item not in self.__data_items
        assert before_index <= len(self.__data_items) and before_index >= 0
        # insert in internal list
        self.__data_items.insert(before_index, data_item)
        data_item.storage_cache = self.storage_cache
        self.managed_object_context.write_data_item(data_item)
        data_item.managed_object_context = self.managed_object_context
        #data_item.write()
        # be a listener. why?
        data_item.add_listener(self)
        self.notify_listeners("data_item_inserted", self, data_item, before_index, False)
        data_item.set_data_item_manager(self)
        listener_list = self.__data_item_listeners.get(data_item.uuid, list())
        for listener in listener_list:
            listener.set_data_item(data_item)

    def remove_data_item(self, data_item):
        """ Remove data item from document model. Data item will have managed_object_context cleared upon return. """
        # remove the data item from any groups
        for data_group in self.get_flat_data_group_generator():
            if data_item in data_group.data_items:
                data_group.remove_data_item(data_item)
        # remove data items that are entirely dependent on data item being removed
        for other_data_item in copy.copy(self.data_items):
            if other_data_item.ordered_data_item_data_sources == [data_item]:  # ordered data sources exactly equal to data item?
                self.remove_data_item(other_data_item)
        # tell the data item it is about to be removed
        data_item.about_to_be_removed()
        # disconnect the data source
        data_item.set_data_item_manager(None)
        # remove it from the persistent_storage
        assert data_item is not None
        assert data_item in self.__data_items
        index = self.__data_items.index(data_item)
        # do actual removal
        del self.__data_items[index]
        # keep storage up-to-date
        self.managed_object_context.erase_data_item(data_item)
        data_item.__storage_cache = None
        # unlisten to data item
        data_item.remove_listener(self)
        # update data item count
        self.notify_listeners("data_item_removed", self, data_item, index, False)
        if data_item.get_observer_count(self) == 0:  # ugh?
            self.notify_listeners("data_item_deleted", data_item)
        listener_list = self.__data_item_listeners.get(data_item.uuid, list())
        for listener in listener_list:
            listener.set_data_item(None)

    def add_data_item_listener(self, data_item_uuid, listener):
        listener_list = self.__data_item_listeners.setdefault(data_item_uuid, list())
        assert listener not in listener_list
        listener_list.append(listener)
        data_item = self.get_data_item_by_uuid(data_item_uuid)
        listener.set_data_item(data_item)

    def remove_data_item_listener(self, data_item_uuid, listener):
        listener_list = self.__data_item_listeners.setdefault(data_item_uuid, list())
        assert listener in listener_list
        listener_list.remove(listener)
        listener.set_data_item(None)

    def _get_data_item_listeners(self, data_item_uuid):
        """For testing."""
        return self.__data_item_listeners.get(data_item_uuid, list())

    def __get_data_items(self):
        return tuple(self.__data_items)  # tuple makes it read only
    data_items = property(__get_data_items)

    def get_dependent_data_items(self, parent_data_item):
        return parent_data_item.dependent_data_items

    def append_data_group(self, data_group):
        self.insert_data_group(len(self.data_groups), data_group)

    def insert_data_group(self, before_index, data_group):
        self.insert_item("data_groups", before_index, data_group)
        self.notify_insert_item("data_groups", data_group, before_index)

    def remove_data_group(self, data_group):
        data_group.disconnect_data_items()
        index = self.data_groups.index(data_group)
        self.remove_item("data_groups", data_group)
        self.notify_remove_item("data_groups", data_group, index)

    def create_default_data_groups(self):
        # ensure there is at least one group
        if len(self.data_groups) < 1:
            data_group = DataGroup.DataGroup()
            data_group.title = _("My Data")
            self.append_data_group(data_group)

    def create_sample_images(self, resources_path):
        if True:
            data_group = self.get_or_create_data_group(_("Example Data"))
            handler = ImportExportManager.NDataImportExportHandler(None, ["ndata1"])
            samples_dir = os.path.join(resources_path, "SampleImages")
            #logging.debug("Looking in %s", samples_dir)
            def is_ndata(file_path):
                #logging.debug("Checking %s", file_path)
                _, extension = os.path.splitext(file_path)
                return extension == ".ndata1"
            if os.path.isdir(samples_dir):
                sample_paths = [os.path.normpath(os.path.join(samples_dir, d)) for d in os.listdir(samples_dir) if is_ndata(os.path.join(samples_dir, d))]
            else:
                sample_paths = []
            for sample_path in sorted(sample_paths):
                def source_file_path_in_document(sample_path_):
                    for member_data_item in self.data_items:
                        if member_data_item.source_file_path and os.path.normpath(member_data_item.source_file_path) == sample_path_:
                            return True
                    return False
                if not source_file_path_in_document(sample_path):
                    data_items = handler.read_data_items(None, "ndata1", sample_path)
                    for data_item in data_items:
                        #__, file_name = os.path.split(sample_path)
                        #title, __ = os.path.splitext(file_name)
                        #data_item.title = title
                        self.append_data_item(data_item)
                        data_group.append_data_item(data_item)
        else:
            # for testing, add a checkerboard image data item
            checkerboard_image_source = DataItem.DataItem()
            checkerboard_image_source.title = "Checkerboard"
            with checkerboard_image_source.data_ref() as data_ref:
                data_ref.master_data = Image.create_checkerboard((512, 512))
            self.append_data_item(checkerboard_image_source)
            # for testing, add a color image data item
            color_image_source = DataItem.DataItem()
            color_image_source.title = "Green Color"
            with color_image_source.data_ref() as data_ref:
                data_ref.master_data = Image.create_color_image((512, 512), 128, 255, 128)
            self.append_data_item(color_image_source)
            # for testing, add a color image data item
            lena_image_source = DataItem.DataItem()
            lena_image_source.title = "Lena"
            with lena_image_source.data_ref() as data_ref:
                data_ref.master_data = scipy.misc.lena()
            self.append_data_item(lena_image_source)

    # this message comes from a data item when it wants to be removed from the document. ugh.
    def request_remove_data_item(self, data_item):
        DataGroup.get_data_item_container(self, data_item).remove_data_item(data_item)

    # TODO: what about thread safety for these classes?

    class _DataAccessorIter(object):
        def __init__(self, iter):
            self.iter = iter
        def __iter__(self):
            return self
        def next(self):
            data_item = self.iter.next()
            if data_item:
                return data_item.data
            return None

    class DataAccessor(object):
        def __init__(self, document_model):
            self.__document_model_weakref = weakref.ref(document_model)
        def __get_document_model(self):
            return self.__document_model_weakref()
        document_model = property(__get_document_model)
        # access by bracket notation
        def __len__(self):
            return self.document_model.get_data_item_count()
        def __getitem__(self, key):
            data = self.document_model.get_data_by_key(key)
            if data is None:
                raise KeyError
            return data
        def __setitem__(self, key, value):
            return self.document_model.set_data_by_key(key, value)
        def __delitem__(self, key):
            data_item = self.document_model.get_data_item_by_key(key)
            if data_item:
                self.document_model.remove_data_item(data_item)
        def __iter__(self):
            return DocumentModel._DataAccessorIter(self.document_model.get_flat_data_item_generator())
        def uuid_keys(self):
            return [data_item.uuid for data_item in self.document_model.data_items_by_key]
        def title_keys(self):
            return [data_item.title for data_item in self.document_model.data_items_by_key]
        def keys(self):
            return self.uuid_keys()

    class DataItemAccessor(object):
        def __init__(self, document_model):
            self.__document_model_weakref = weakref.ref(document_model)
        def __get_document_model(self):
            return self.__document_model_weakref()
        document_model = property(__get_document_model)
        # access by bracket notation
        def __len__(self):
            return self.document_model.get_data_item_count()
        def __getitem__(self, key):
            data_item = self.document_model.get_data_item_by_key(key)
            if data_item is None:
                raise KeyError
            return data_item
        def __delitem__(self, key):
            data_item = self.document_model.get_data_item_by_key(key)
            if data_item:
                self.document_model.remove_data_item(data_item)
        def __iter__(self):
            return iter(self.document_model.get_flat_data_item_generator())
        def uuid_keys(self):
            return [data_item.uuid for data_item in self.document_model.data_items_by_key]
        def title_keys(self):
            return [data_item.title for data_item in self.document_model.data_items_by_key]
        def keys(self):
            return self.uuid_keys()

    # Return a generator over all data items
    def get_flat_data_item_generator(self):
        for data_item in self.data_items:
            yield data_item

    # Return a generator over all data groups
    def get_flat_data_group_generator(self):
        return DataGroup.get_flat_data_group_generator_in_container(self)

    def get_data_group_by_uuid(self, uuid):
        for data_group in DataGroup.get_flat_data_group_generator_in_container(self):
            if data_group.uuid == uuid:
                return data_group
        return None

    def get_data_item_count(self):
        return len(list(self.get_flat_data_item_generator()))

    # temporary method to find the container of a data item. this goes away when
    # data items get stored in a flat table.
    def get_data_item_data_group(self, data_item):
        for data_group in self.get_flat_data_group_generator():
            if data_item in DataGroup.get_flat_data_item_generator_in_container(data_group):
                return data_group
        return None

    # access data item by key (title, uuid, index)
    def get_data_item_by_key(self, key):
        if isinstance(key, numbers.Integral):
            return list(self.get_flat_data_item_generator())[key]
        if isinstance(key, uuid.UUID):
            return self.get_data_item_by_uuid(key)
        return self.get_data_item_by_title(str(key))
    def get_data_by_key(self, key):
        data_item = self.get_data_item_by_key(key)
        if data_item:
            return data_item.data
        return None
    def set_data_by_key(self, key, data):
        data_item = self.get_data_item_by_key(key)
        if data_item:
            with data_item.data_ref() as data_ref:
                data_ref.master_data = data
        else:
            if isinstance(key, numbers.Integral):
                raise IndexError
            if isinstance(key, uuid.UUID):
                raise KeyError
            data_item = DataItem.DataItem()
            data_item.title = str(key)
            with data_item.data_ref() as data_ref:
                data_ref.master_data = data
            self.append_data_item(data_item)
        return data_item

    # access data items by title
    def get_data_item_by_title(self, title):
        for data_item in self.get_flat_data_item_generator():
            if data_item.title == title:
                return data_item
        return None
    def get_data_by_title(self, title):
        data_item = self.get_data_item_by_title(title)
        if data_item:
            return data_item.data
        return None

    # access data items by index
    def get_data_item_by_index(self, index):
        return list(self.get_flat_data_item_generator())[index]
    def get_data_by_index(self, index):
        data_item = self.get_data_item_by_index(index)
        if data_item:
            return data_item.data
        return None
    def set_data_by_index(self, index, data):
        data_item = self.get_data_item_by_index(index)
        if data_item:
            with data_item.data_ref() as data_ref:
                data_ref.master_data = data
        else:
            raise IndexError
    def get_index_for_data_item(self, data_item):
        return list(self.get_flat_data_item_generator()).index(data_item)

    # access data items by uuid
    def get_data_item_by_uuid(self, uuid):
        for data_item in self.get_flat_data_item_generator():
            if data_item.uuid == uuid:
                return data_item
        return None
    def get_data_by_uuid(self, uuid):
        data_item = self.get_data_item_by_uuid(uuid)
        if data_item:
            return data_item.data
        return None
    def set_data_by_uuid(self, uuid, data):
        data_item = self.get_data_item_by_uuid(uuid)
        if data_item:
            with data_item.data_ref() as data_ref:
                data_ref.master_data = data
        else:
            raise KeyError

    def get_or_create_data_group(self, group_name):
        data_group = DataGroup.get_data_group_in_container_by_title(self, group_name)
        if data_group is None:
            # we create a new group
            data_group = DataGroup.DataGroup()
            data_group.title = group_name
            self.insert_data_group(0, data_group)
        return data_group

    def dispatch_task(self, task, description=None):
        self.__thread_pool.queue_fn(task, description)

    def data_item_needs_recompute(self, data_item):
        self.dispatch_task(lambda: data_item.recompute_data(), "data")

    def recompute_all(self):
        self.__thread_pool.run_all()

    def start_dispatcher(self):
        self.__thread_pool.start(16)
