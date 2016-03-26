# standard libraries
import collections
import copy
import datetime
import functools
import gettext
import json
import logging
import numbers
import os.path
import threading
import time
import uuid
import weakref

# typing
from typing import List

# third party libraries
import scipy

# local libraries
from nion.data import Image
from nion.swift.model import Cache
from nion.swift.model import Connection
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import HardwareSource
from nion.swift.model import ImportExportManager
from nion.swift.model import Region
from nion.swift.model import Symbolic
from nion.swift.model import Utility
from nion.swift.model import WorkspaceLayout
from nion.ui import Converter
from nion.ui import Event
from nion.ui import Observable
from nion.ui import Persistence
from nion.ui import ThreadPool

_ = gettext.gettext


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
        persistent_object_parent = object.persistent_object_parent
        if not persistent_object_parent:
            return self.__properties
        else:
            parent_storage_dict = self.__get_storage_dict(persistent_object_parent.parent)
            return object.get_accessor_in_parent()(parent_storage_dict)

    def __update_modified_and_get_storage_dict(self, object):
        storage_dict = self.__get_storage_dict(object)
        with self.__properties_lock:
            storage_dict["modified"] = object.modified.isoformat()
        persistent_object_parent = object.persistent_object_parent
        parent = persistent_object_parent.parent if persistent_object_parent else None
        if parent:
            self.__update_modified_and_get_storage_dict(parent)
        return storage_dict

    def update_properties(self):
        if self.__filepath:
            with open(self.__filepath, "w") as fp:
                json.dump(self.__properties, fp)

    def insert_item(self, parent, name, before_index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict.setdefault(name, list())
            item_dict = item.write_to_dict()
            item_list.insert(before_index, item_dict)
            item.persistent_object_context = parent.persistent_object_context
        self.update_properties()

    def remove_item(self, parent, name, index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict[name]
            del item_list[index]
        self.update_properties()
        item.persistent_object_context = None

    def set_item(self, parent, name, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            if item:
                item_dict = item.write_to_dict()
                storage_dict[name] = item_dict
                item.persistent_object_context = parent.persistent_object_context
            else:
                if name in storage_dict:
                    del storage_dict[name]
        self.update_properties()

    def set_property(self, object, name, value):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict[name] = value
        self.update_properties()


class DataItemPersistentStorage(object):

    """
        Manages persistent storage for data items by caching properties and data, maintaining the PersistentObjectContext
        on contained items, and writing to disk when necessary.

        The persistent_storage_handler must respond to these methods:
            read_properties()
            read_data()
            write_properties(properties, file_datetime)
            write_data(data, file_datetime)
    """

    def __init__(self, persistent_storage_handler=None, data_item=None, properties=None):
        self.__persistent_storage_handler = persistent_storage_handler
        self.__properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
        self.__properties_lock = threading.RLock()
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
        self.write_delayed = False

    @property
    def data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None

    @data_item.setter
    def data_item(self, data_item):
        self.__weak_data_item = weakref.ref(data_item) if data_item else None

    @property
    def properties(self):
        with self.__properties_lock:
            return copy.deepcopy(self.__properties)

    @property
    def _persistent_storage_handler(self):
        return self.__persistent_storage_handler

    def __get_storage_dict(self, object):
        persistent_object_parent = object.persistent_object_parent
        if not persistent_object_parent:
            return self.__properties
        else:
            parent_storage_dict = self.__get_storage_dict(persistent_object_parent.parent)
            return object.get_accessor_in_parent()(parent_storage_dict)

    def __update_modified_and_get_storage_dict(self, object):
        storage_dict = self.__get_storage_dict(object)
        with self.__properties_lock:
            storage_dict["modified"] = object.modified.isoformat()
        persistent_object_parent = object.persistent_object_parent
        parent = persistent_object_parent.parent if persistent_object_parent else None
        if parent:
            self.__update_modified_and_get_storage_dict(parent)
        return storage_dict

    def update_properties(self):
        if not self.write_delayed:
            file_datetime = self.data_item.created_local
            self.__persistent_storage_handler.write_properties(self.properties, file_datetime)

    def insert_item(self, parent, name, before_index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict.setdefault(name, list())
            item_dict = item.write_to_dict()
            item_list.insert(before_index, item_dict)
            item.persistent_object_context = parent.persistent_object_context
        self.update_properties()

    def remove_item(self, parent, name, index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict[name]
            del item_list[index]
        self.update_properties()
        item.persistent_object_context = None

    def set_item(self, parent, name, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            if item:
                item_dict = item.write_to_dict()
                storage_dict[name] = item_dict
                item.persistent_object_context = parent.persistent_object_context
            else:
                if name in storage_dict:
                    del storage_dict[name]
        self.update_properties()

    def update_data(self, data_shape, data_dtype, data=None):
        if not self.write_delayed:
            file_datetime = self.data_item.created_local
            if data is not None:
                self.__persistent_storage_handler.write_data(data, file_datetime)

    def load_data(self):
        assert self.data_item.maybe_data_source and self.data_item.maybe_data_source.has_data
        return self.__persistent_storage_handler.read_data()

    def set_property(self, object, name, value):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict[name] = value
        self.update_properties()

    def remove(self):
        self.__persistent_storage_handler.remove()


class MemoryPersistentStorageSystem(object):

    def __init__(self):
        self.data = dict()
        self.properties = dict()
        self._test_data_read_event = Event.Event()

    class MemoryStorageHandler(object):

        def __init__(self, uuid, properties, data, data_read_event):
            self.__uuid = uuid
            self.__properties = properties
            self.__data = data
            self.__data_read_event = data_read_event

        @property
        def reference(self):
            return str(self.__uuid)

        def read_properties(self):
            return self.__properties.get(self.__uuid, dict())

        def read_data(self):
            self.__data_read_event.fire(self.__uuid)
            return self.__data.get(self.__uuid)

        def write_properties(self, properties, file_datetime):
            self.__properties[self.__uuid] = copy.deepcopy(properties)

        def write_data(self, data, file_datetime):
            self.__data[self.__uuid] = data.copy()

        def remove(self):
            self.__data.pop(self.__uuid, None)
            self.__properties.pop(self.__uuid, None)

    def find_data_items(self):
        persistent_storage_handlers = list()
        for key in sorted(self.properties):
            self.properties[key].setdefault("uuid", str(uuid.uuid4()))
            persistent_storage_handlers.append(MemoryPersistentStorageSystem.MemoryStorageHandler(key, self.properties, self.data, self._test_data_read_event))
        return persistent_storage_handlers

    def make_persistent_storage_handler(self, data_item):
        uuid = str(data_item.uuid)
        return MemoryPersistentStorageSystem.MemoryStorageHandler(uuid, self.properties, self.data, self._test_data_read_event)


from nion.swift import NDataHandler

class FilePersistentStorageSystem(object):

    def __init__(self, directories):
        self.__directories = directories
        self.__file_handlers = [NDataHandler.NDataHandler]

    def find_data_items(self):
        persistent_storage_handlers = list()
        absolute_file_paths = set()
        for directory in self.__directories:
            for root, dirs, files in os.walk(directory):
                absolute_file_paths.update([os.path.join(root, data_file) for data_file in files])
        for file_handler in self.__file_handlers:
            for data_file in filter(file_handler.is_matching, absolute_file_paths):
                try:
                    persistent_storage_handler = file_handler(data_file)
                    assert persistent_storage_handler.is_valid
                    persistent_storage_handlers.append(persistent_storage_handler)
                except Exception as e:
                    logging.error("Exception reading file: %s", data_file)
                    logging.error(str(e))
                    raise
        return persistent_storage_handlers

    def __get_default_path(self, data_item):
        uuid_ = data_item.uuid
        created_local = data_item.created_local
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
        path_components = created_local.strftime("%Y-%m-%d").split('-')
        session_id = session_id if session_id else created_local.strftime("%Y%m%d-000000")
        path_components.append(session_id)
        path_components.append("data_" + encoded_uuid_str)
        return os.path.join(*path_components)

    def make_persistent_storage_handler(self, data_item):
        return self.__file_handlers[0].make(os.path.join(self.__directories[0], self.__get_default_path(data_item)))


class PersistentDataItemContext(Persistence.PersistentObjectContext):

    """
        A PersistentObjectContext that adds extra methods for handling data items.

        Versioning

        If the file is too old, it must be migrated to the newer version.
        If the file is too new, it cannot be loaded.

        When writing, the version the file format is written to the 'version' property.

    """

    def __init__(self, persistent_storage_systems=None, ignore_older_files=False, log_migrations=True):
        super(PersistentDataItemContext, self).__init__()
        self.__persistent_storage_systems = persistent_storage_systems if persistent_storage_systems else [MemoryPersistentStorageSystem()]
        self.__ignore_older_files = ignore_older_files
        self.__log_migrations = log_migrations

    def read_data_items_version_stats(self):
        persistent_storage_handlers = list()  # persistent_storage_handler
        for persistent_storage_system in self.__persistent_storage_systems:
            persistent_storage_handlers.extend(persistent_storage_system.find_data_items())
        count = [0, 0, 0]  # data item matches version, data item has higher version, data item has lower version
        writer_version = DataItem.DataItem.writer_version
        for persistent_storage_handler in persistent_storage_handlers:
            properties = persistent_storage_handler.read_properties()
            version = properties.get("version", 0)
            if version < writer_version:
                count[2] += 1
            elif version > writer_version:
                count[1] += 1
            else:
                count[0] += 1
        return count

    def read_data_items(self):
        """
        Read data items from the data reference handler and return as a list.

        Data items will have persistent_object_context set upon return, but caller will need to call finish_reading
        on each of the data items.
        """
        persistent_storage_handlers = list()  # persistent_storage_handler
        for persistent_storage_system in self.__persistent_storage_systems:
            persistent_storage_handlers.extend(persistent_storage_system.find_data_items())
        data_items_by_uuid = dict()
        v7lookup = dict()  # map data_item.uuid to buffered_data_source.uuid
        for persistent_storage_handler in persistent_storage_handlers:
            try:
                properties = persistent_storage_handler.read_properties()
                version = properties.get("version", 0)
                if self.__ignore_older_files and version != 8:
                    version = 9999
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
                    temp_data = persistent_storage_handler.read_data()
                    if temp_data is not None:
                        properties["master_data_dtype"] = str(temp_data.dtype)
                        properties["master_data_shape"] = temp_data.shape
                    properties["displays"] = [{}]
                    properties["uuid"] = str(uuid.uuid4())  # assign a new uuid
                    properties["version"] = 2
                    # rewrite needed since we added a uuid
                    persistent_storage_handler.write_properties(copy.deepcopy(properties), datetime.datetime.now())
                    version = 2
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (ndata1)", persistent_storage_handler.reference, version)
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
                    persistent_storage_handler.write_properties(copy.deepcopy(properties), datetime.datetime.now())
                    version = 3
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (add uuids)", persistent_storage_handler.reference, version)
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
                    # persistent_storage_handler.write_properties(copy.deepcopy(properties), datetime.datetime.now())
                    version = 4
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (calibration offset)", persistent_storage_handler.reference, version)
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
                    # persistent_storage_handler.write_properties(copy.deepcopy(properties), datetime.datetime.now())
                    version = 5
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (region_uuid)", persistent_storage_handler.reference, version)
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
                    # persistent_storage_handler.write_properties(copy.deepcopy(properties), datetime.datetime.now())
                    version = 6
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (operation hierarchy)", persistent_storage_handler.reference, version)
                if version == 6:
                    # version 6 -> 7 changes data to be cached in the buffered data source object
                    buffered_data_source_dict = dict()
                    buffered_data_source_dict["type"] = "buffered-data-source"
                    buffered_data_source_dict["uuid"] = v7lookup.setdefault(properties["uuid"], str(uuid.uuid4()))  # assign a new uuid
                    include_data = "master_data_shape" in properties and "master_data_dtype" in properties
                    data_shape = properties.get("master_data_shape")
                    data_dtype = properties.get("master_data_dtype")
                    if "intensity_calibration" in properties:
                        buffered_data_source_dict["intensity_calibration"] = properties["intensity_calibration"]
                        del properties["intensity_calibration"]
                    if "dimensional_calibrations" in properties:
                        buffered_data_source_dict["dimensional_calibrations"] = properties["dimensional_calibrations"]
                        del properties["dimensional_calibrations"]
                    if "master_data_shape" in properties:
                        buffered_data_source_dict["data_shape"] = data_shape
                        del properties["master_data_shape"]
                    if "master_data_dtype" in properties:
                        buffered_data_source_dict["data_dtype"] = data_dtype
                        del properties["master_data_dtype"]
                    if "displays" in properties:
                        buffered_data_source_dict["displays"] = properties["displays"]
                        del properties["displays"]
                    if "regions" in properties:
                        buffered_data_source_dict["regions"] = properties["regions"]
                        del properties["regions"]
                    operation_dict = properties.pop("operation", None)
                    if operation_dict is not None:
                        buffered_data_source_dict["data_source"] = operation_dict
                        for data_source_dict in operation_dict.get("data_sources", dict()):
                            data_source_dict["buffered_data_source_uuid"] = v7lookup.setdefault(data_source_dict["data_item_uuid"], str(uuid.uuid4()))
                            data_source_dict.pop("data_item_uuid", None)
                    if include_data or operation_dict is not None:
                        properties["data_sources"] = [buffered_data_source_dict]
                    properties["version"] = 7
                    persistent_storage_handler.write_properties(copy.deepcopy(properties), datetime.datetime.now())
                    version = 7
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (buffered data sources)", persistent_storage_handler.reference, version)
                if version == 7:
                    # version 7 -> 8 changes metadata to be stored in buffered_data_source
                    data_source_dicts = properties.get("data_sources", list())
                    description_metadata = properties.setdefault("metadata", dict()).setdefault("description", dict())
                    if len(data_source_dicts) == 1:
                        data_source_dict = data_source_dicts[0]
                        excluded = ["rating", "datetime_original", "title", "source_file_path", "session_id", "caption",
                            "flag", "datetime_modified", "connections", "data_sources", "uuid", "reader_version",
                            "version", "metadata"]
                        for key in list(properties.keys()):
                            if key not in excluded:
                                data_source_dict.setdefault("metadata", dict())[key] = properties[key]
                                del properties[key]
                        for key in ["caption", "flag", "rating", "title"]:
                            if key in properties:
                                description_metadata[key] = properties[key]
                                del properties[key]
                    datetime_original = properties.get("datetime_original", dict())
                    dst_value = datetime_original.get("dst", "+00")
                    dst_adjust = int(dst_value)
                    tz_value = datetime_original.get("tz", "+0000")
                    tz_adjust = int(tz_value[0:3]) * 60 + int(tz_value[3:5]) * (-1 if tz_value[0] == '-1' else 1)
                    local_datetime = Utility.get_datetime_from_datetime_item(datetime_original)
                    if not local_datetime:
                        local_datetime = datetime.datetime.utcnow()
                    data_source_dict["created"] = (local_datetime - datetime.timedelta(minutes=dst_adjust + tz_adjust)).isoformat()
                    data_source_dict["modified"] = data_source_dict["created"]
                    properties["created"] = data_source_dict["created"]
                    properties["modified"] = properties["created"]
                    time_zone_dict = description_metadata.setdefault("time_zone", dict())
                    time_zone_dict["dst"] = dst_value
                    time_zone_dict["tz"] = tz_value
                    properties.pop("datetime_original", None)
                    properties.pop("datetime_modified", None)
                    properties["version"] = 8
                    # no rewrite needed, but do it anyway so the user can have a simple understanding of upgrading.
                    persistent_storage_handler.write_properties(copy.deepcopy(properties), datetime.datetime.now())
                    version = 8
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (metadata to data source)", persistent_storage_handler.reference, version)
                if version == 8:
                    # version 8 -> 9 is not implemented yet. but adjust the extra_high_tension tag anyway.
                    data_source_dicts = properties.get("data_sources", list())
                    for data_source_dict in data_source_dicts:
                        metadata = data_source_dict.get("metadata", dict())
                        hardware_source_dict = metadata.get("hardware_source", dict())
                        high_tension_v = hardware_source_dict.get("extra_high_tension")
                        # hardware_source_dict.pop("extra_high_tension", None)
                        if high_tension_v:
                            autostem_dict = hardware_source_dict.setdefault("autostem", dict())
                            autostem_dict["high_tension_v"] = high_tension_v
                # NOTE: Search for to-do 'file format' to gather together 'would be nice' changes
                # NOTE: change writer_version in DataItem.py
                data_item_uuid = properties["uuid"]
                data_item = DataItem.DataItem(item_uuid=data_item_uuid)
                if version <= data_item.writer_version:
                    data_item.begin_reading()
                    persistent_storage = DataItemPersistentStorage(persistent_storage_handler=persistent_storage_handler, data_item=data_item, properties=properties)
                    data_item.read_from_dict(persistent_storage.properties)
                    self._set_persistent_storage_for_object(data_item, persistent_storage)
                    data_item.persistent_object_context = self
                    if self.__log_migrations and data_item.uuid in data_items_by_uuid:
                        logging.info("Warning: Duplicate data item %s", data_item.uuid)
                    data_items_by_uuid[data_item.uuid] = data_item
            except Exception as e:
                logging.debug("Error reading %s", persistent_storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()
        def sort_by_date_key(data_item):
            return data_item.created
        data_items = list(data_items_by_uuid.values())
        data_items.sort(key=sort_by_date_key)
        return data_items

    def write_data_item(self, data_item):
        """ Write data item to persistent storage. """
        persistent_storage = self._get_persistent_storage_for_object(data_item)
        if not persistent_storage:
            persistent_storage_handler = None
            for persistent_storage_system in self.__persistent_storage_systems:
                persistent_storage_handler = persistent_storage_system.make_persistent_storage_handler(data_item)
                if persistent_storage_handler:
                    break
            properties = data_item.write_to_dict()
            persistent_storage = DataItemPersistentStorage(persistent_storage_handler=persistent_storage_handler, data_item=data_item, properties=properties)
            self._set_persistent_storage_for_object(data_item, persistent_storage)
        data_item.persistent_object_context_changed()
        # write the uuid and version explicitly
        self.property_changed(data_item, "uuid", str(data_item.uuid))
        self.property_changed(data_item, "version", data_item.writer_version)
        if data_item.maybe_data_source:
            self.rewrite_data_item_data(data_item.maybe_data_source)

    def rewrite_data_item_data(self, buffered_data_source):
        persistent_storage = self._get_persistent_storage_for_object(buffered_data_source)
        persistent_storage.update_data(buffered_data_source.data_shape, buffered_data_source.data_dtype, data=buffered_data_source.data)

    def erase_data_item(self, data_item):
        persistent_storage = self._get_persistent_storage_for_object(data_item)
        persistent_storage.remove()
        data_item.persistent_object_context = None

    def load_data(self, data_item):
        persistent_storage = self._get_persistent_storage_for_object(data_item)
        return persistent_storage.load_data()

    def _test_get_file_path(self, data_item):
        persistent_storage = self._get_persistent_storage_for_object(data_item)
        return persistent_storage._persistent_storage_handler.reference


class DocumentModel(Observable.Observable, Observable.Broadcaster, Observable.ReferenceCounted,
                    Persistence.PersistentObject):

    """The document model manages storage and dependencies between data items and other objects.

    The document model provides a dispatcher object which will run tasks in a thread pool.
    """

    def __init__(self, library_storage=None, persistent_storage_systems=None, storage_cache=None, log_migrations=True, ignore_older_files=False):
        super(DocumentModel, self).__init__()

        self.data_item_deleted_event = Event.Event()  # will be called after the item is deleted
        self.data_item_will_be_removed_event = Event.Event()  # will be called before the item is deleted

        self.__thread_pool = ThreadPool.ThreadPool()
        self.persistent_object_context = PersistentDataItemContext(persistent_storage_systems, ignore_older_files, log_migrations)
        self.__library_storage = library_storage if library_storage else FilePersistentStorage()
        self.persistent_object_context._set_persistent_storage_for_object(self, self.__library_storage)
        self.storage_cache = storage_cache if storage_cache else Cache.DictStorageCache()
        self.__transactions_lock = threading.RLock()
        self.__transactions = dict()
        self.__live_data_items_lock = threading.RLock()
        self.__live_data_items = dict()
        self.__dependent_data_items_lock = threading.RLock()
        self.__dependent_data_items = dict()
        self.__source_data_items = dict()
        self.__computation_dependency_data_items = dict()
        self.__data_items = list()
        self.__data_item_item_inserted_listeners = dict()
        self.__data_item_item_removed_listeners = dict()
        self.__data_item_request_remove_region = dict()
        self.__data_item_handle_dependency_action_listeners = dict()
        self.__computation_changed_or_mutated_listeners = dict()
        self.__data_item_references = dict()
        self.define_type("library")
        self.define_relationship("data_groups", DataGroup.data_group_factory)
        self.define_relationship("workspaces", WorkspaceLayout.factory)  # TODO: file format. Rename workspaces to workspace_layouts.
        self.define_property("session_metadata", dict(), copy_on_read=True, changed=self.__session_metadata_changed)
        self.define_property("workspace_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("data_item_references", dict(), hidden=True)
        self.__buffered_data_source_set = set()
        self.__buffered_data_source_set_changed_event = Event.Event()
        self.session_id = None
        self.start_new_session()
        self.__computation_changed_listeners = dict()
        self.__read()
        self.__library_storage.set_property(self, "uuid", str(self.uuid))
        self.__library_storage.set_property(self, "version", 0)

        self.__channel_buffer_updated_listeners = dict()
        self.__channel_buffer_start_listeners = dict()
        self.__channel_buffer_stop_listeners = dict()
        self.__channel_buffer_states_updated_listeners = dict()
        self.__last_data_items_dict = dict()  # maps hardware source to list of data items for that hardware source

        self.append_data_item_event = Event.Event()

        def append_data_item(data_item, is_recording):
            self.append_data_item_event.fire_any(data_item, is_recording)

        self.__hardware_source_added_event_listener = HardwareSource.HardwareSourceManager().hardware_source_added_event.listen(functools.partial(self.__hardware_source_added, append_data_item))
        self.__hardware_source_removed_event_listener = HardwareSource.HardwareSourceManager().hardware_source_removed_event.listen(self.__hardware_source_removed)

        for hardware_source in HardwareSource.HardwareSourceManager().hardware_sources:
            self.__hardware_source_added(append_data_item, hardware_source)

    def __read(self):
        # first read the items
        self.read_from_dict(self.__library_storage.properties)
        data_items = self.persistent_object_context.read_data_items()
        for index, data_item in enumerate(data_items):
            self.__data_items.insert(index, data_item)
            data_item.storage_cache = self.storage_cache
            self.__data_item_item_inserted_listeners[data_item.uuid] = data_item.item_inserted_event.listen(self.__item_inserted)
            self.__data_item_item_removed_listeners[data_item.uuid] = data_item.item_removed_event.listen(self.__item_removed)
            self.__data_item_request_remove_region[data_item.uuid] = data_item.request_remove_region_event.listen(self.__remove_region_specifier)
            self.__data_item_handle_dependency_action_listeners[data_item.uuid] = data_item.handle_dependency_action.listen(self.__handle_dependency_action)
            self.__computation_changed_or_mutated_listeners[data_item.uuid] = data_item.computation_changed_or_mutated_event.listen(self.__handle_computation_changed_or_mutated)
            if data_item.maybe_data_source:
                self.__handle_computation_changed_or_mutated(data_item, data_item.maybe_data_source, data_item.maybe_data_source.computation)
            data_item.add_listener(self)
            data_item.set_data_item_manager(self)
            self.__buffered_data_source_set.update(set(data_item.data_sources))
            self.buffered_data_source_set_changed_event.fire(set(data_item.data_sources), set())
        # all sorts of interconnections may occur between data items and other objects. give the data item a chance to
        # mark itself clean after reading all of them in.
        for data_item in data_items:
            data_item.finish_reading()
        for data_item in data_items:
            for buffered_data_source in data_item.data_sources:
                computation = buffered_data_source.computation
                if computation:
                    try:
                        computation.bind(self)
                    except Exception as e:
                        print(str(e))
            data_item.connect_data_items(self.get_data_item_by_uuid)
        # # initialize data item references
        data_item_references_dict = self._get_persistent_property_value("data_item_references")
        for key, data_item_uuid in data_item_references_dict.items():
            data_item = self.get_data_item_by_uuid(uuid.UUID(data_item_uuid))
            if data_item:
                self.__data_item_references.setdefault(key, DocumentModel.DataItemReference(self, key, data_item))
        # all data items will already have a persistent_object_context
        for data_group in self.data_groups:
            data_group.connect_data_items(self.get_data_item_by_uuid)

    def close(self):
        # close hardware source related stuff
        self.__hardware_source_added_event_listener.close()
        self.__hardware_source_added_event_listener = None
        self.__hardware_source_removed_event_listener.close()
        self.__hardware_source_removed_event_listener = None
        for listener in self.__channel_buffer_states_updated_listeners.values():
            listener.close()
        self.__channel_buffer_states_updated_listeners = None
        # TODO: close other listeners here too
        HardwareSource.HardwareSourceManager().abort_all_and_close()

        for listeners in self.__channel_buffer_updated_listeners.values():
            for listener in listeners:
                listener.close()
        for listeners in self.__channel_buffer_start_listeners.values():
            for listener in listeners:
                listener.close()
        for listeners in self.__channel_buffer_stop_listeners.values():
            for listener in listeners:
                listener.close()
        self.__channel_buffer_updated_listeners = None
        self.__channel_buffer_start_listeners = None
        self.__channel_buffer_stop_listeners = None

        self.__thread_pool.close()
        for data_item in self.data_items:
            data_item.about_to_be_removed()
            data_item.close()
        self.storage_cache.close()

    def about_to_delete(self):
        # override from ReferenceCounted. several DocumentControllers may retain references
        self.close()
        # these are here so that the document model gets garbage collected.
        # TODO: generalize this behavior into a close method on persistent object
        self.undefine_properties()
        self.undefine_items()
        self.undefine_relationships()

    def start_new_session(self):
        self.session_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    def __session_metadata_changed(self, name, value):
        self.notify_set_property("session_metadata", self.session_metadata)

    def set_session_field(self, field_id: str, value: str) -> None:
        session_metadata = self.session_metadata
        session_metadata[field_id] = str(value)
        self.session_metadata = session_metadata

    def get_session_field(self, field_id: str) -> str:
        return self.session_metadata.get(field_id)

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
        """Insert a new data item into document model.

        Data item will have persistent_object_context set upon return.

        This method is NOT threadsafe.
        """
        assert data_item is not None
        assert data_item not in self.__data_items
        assert before_index <= len(self.__data_items) and before_index >= 0
        # insert in internal list
        self.__data_items.insert(before_index, data_item)
        data_item.storage_cache = self.storage_cache
        data_item.persistent_object_context = self.persistent_object_context
        self.persistent_object_context.write_data_item(data_item)
        # be a listener. why?
        data_item.add_listener(self)
        self.__data_item_item_inserted_listeners[data_item.uuid] = data_item.item_inserted_event.listen(self.__item_inserted)
        self.__data_item_item_removed_listeners[data_item.uuid] = data_item.item_removed_event.listen(self.__item_removed)
        self.__data_item_request_remove_region[data_item.uuid] = data_item.request_remove_region_event.listen(self.__remove_region_specifier)
        self.__data_item_handle_dependency_action_listeners[data_item.uuid] = data_item.handle_dependency_action.listen(self.__handle_dependency_action)
        self.__computation_changed_or_mutated_listeners[data_item.uuid] = data_item.computation_changed_or_mutated_event.listen(self.__handle_computation_changed_or_mutated)
        if data_item.maybe_data_source:
            self.__handle_computation_changed_or_mutated(data_item, data_item.maybe_data_source, data_item.maybe_data_source.computation)
        self.notify_listeners("data_item_inserted", self, data_item, before_index, False)
        for data_item_reference in self.__data_item_references.values():
            data_item_reference.data_item_inserted(data_item)
        data_item.set_data_item_manager(self)
        # fire buffered_data_source_set_changed_event
        self.__buffered_data_source_set.update(set(data_item.data_sources))
        self.buffered_data_source_set_changed_event.fire(set(data_item.data_sources), set())
        # handle computation
        for data_source in data_item.data_sources:
            self.computation_changed(data_source, data_source.computation)
            if data_source.computation:
                data_source.computation.bind(self)
        self.__handle_dependency_action(data_item)

    def remove_data_item(self, data_item):
        """Remove data item from document model.

        Data item will have persistent_object_context cleared upon return.

        This method is NOT threadsafe.
        """
        # remove data item from any selections
        self.data_item_will_be_removed_event.fire(data_item)
        # remove the data item from any groups
        for data_group in self.get_flat_data_group_generator():
            if data_item in data_group.data_items:
                data_group.remove_data_item(data_item)
        # remove data items that are entirely dependent on data item being removed
        # entirely dependent means that the data item has a single data item source
        # and it matches the data_item being removed.
        for other_data_item in self.get_dependent_data_items(data_item):
            if self.get_source_data_items(other_data_item) == [data_item]:  # ordered data sources exactly equal to data item?
                self.remove_data_item(other_data_item)
        # fire buffered_data_source_set_changed_event
        self.__buffered_data_source_set.difference_update(set(data_item.data_sources))
        self.buffered_data_source_set_changed_event.fire(set(), set(data_item.data_sources))
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
        self.persistent_object_context.erase_data_item(data_item)
        data_item.__storage_cache = None
        # un-listen to data item
        data_item.remove_listener(self)
        self.__data_item_item_inserted_listeners[data_item.uuid].close()
        del self.__data_item_item_inserted_listeners[data_item.uuid]
        self.__data_item_item_removed_listeners[data_item.uuid].close()
        del self.__data_item_item_removed_listeners[data_item.uuid]
        self.__data_item_request_remove_region[data_item.uuid].close()
        del self.__data_item_request_remove_region[data_item.uuid]
        self.__data_item_handle_dependency_action_listeners[data_item.uuid].close()
        del self.__data_item_handle_dependency_action_listeners[data_item.uuid]
        self.__computation_changed_or_mutated_listeners[data_item.uuid].close()
        del self.__computation_changed_or_mutated_listeners[data_item.uuid]
        # update data item count
        for data_item_reference in self.__data_item_references.values():
            data_item_reference.data_item_removed(data_item)
        self.notify_listeners("data_item_removed", self, data_item, index, False)
        data_item.close()  # make sure dependents get updated. argh.
        self.data_item_deleted_event.fire(data_item)

    def __item_inserted(self, key, value, before_index):
        # called when a relationship in one of the items we're observing changes.
        if key == "data_sources":
            # fire buffered_data_source_set_changed_event
            assert isinstance(value, DataItem.BufferedDataSource)
            data_source = value
            self.__buffered_data_source_set.update(set([data_source]))
            self.buffered_data_source_set_changed_event.fire(set([data_source]), set())

    def __item_removed(self, key, value, index):
        # called when a relationship in one of the items we're observing changes.
        if key == "data_sources":
            # fire buffered_data_source_set_changed_event
            assert isinstance(value, DataItem.BufferedDataSource)
            data_source = value
            self.__buffered_data_source_set.difference_update(set([data_source]))
            self.buffered_data_source_set_changed_event.fire(set(), set([data_source]))

    def __remove_region_specifier(self, region_specifier) -> None:
        bound_region = self.resolve_object_specifier(region_specifier)
        if bound_region:
            region = bound_region.value
            for data_item in self.data_items:
                for data_source in data_item.data_sources:
                    if region in data_source.regions:
                        if not region._about_to_be_removed:  # HACK! to handle document closing. Argh.
                            data_source.remove_region(region)
                            break

    def __handle_dependency_action(self, data_item):
        for action, target_data_item in data_item._get_pending_dependent_data_items():
            if action == 'add':
                self.__add_dependency(data_item, target_data_item)
            elif action == 'remove':
                self.__remove_dependency(data_item, target_data_item)

    def __remove_dependency(self, source_data_item, target_data_item):
        with self.__dependent_data_items_lock:
            self.__dependent_data_items.setdefault(weakref.ref(source_data_item), list()).remove(target_data_item)
            self.__source_data_items.setdefault(weakref.ref(target_data_item), list()).remove(source_data_item)
        # propagate transaction and live states to dependents
        if source_data_item.in_transaction_state:
            self.end_data_item_transaction(target_data_item)
        if source_data_item.is_live:
            self.end_data_item_live(target_data_item)

    def __add_dependency(self, source_data_item, target_data_item):
        with self.__dependent_data_items_lock:
            self.__dependent_data_items.setdefault(weakref.ref(source_data_item), list()).append(target_data_item)
            self.__source_data_items.setdefault(weakref.ref(target_data_item), list()).append(source_data_item)
        # propagate transaction and live states to dependents
        if source_data_item.in_transaction_state:
            self.begin_data_item_transaction(target_data_item)
        if source_data_item.is_live:
            self.begin_data_item_live(target_data_item)

    def __handle_computation_changed_or_mutated(self, data_item, data_source, computation):
        with self.__dependent_data_items_lock:
            source_data_item_set = self.__computation_dependency_data_items.setdefault(weakref.ref(data_item), set())
            for source_data_item in source_data_item_set:
                self.__remove_dependency(source_data_item, data_item)
            source_data_item_set.clear()
            if computation:
                for variable in computation.variables:
                    specifier = variable.specifier
                    if specifier:
                        object = self.resolve_object_specifier(variable.specifier)
                        if hasattr(object, "data_item"):
                            source_data_item = object.data_item
                            if not source_data_item in source_data_item_set:
                                source_data_item_set.add(source_data_item)
                                self.__add_dependency(source_data_item, data_item)

    # TODO: evaluate if buffered_data_source_set is needed
    @property
    def buffered_data_source_set(self):
        return self.__buffered_data_source_set

    @property
    def buffered_data_source_set_changed_event(self):
        return self.__buffered_data_source_set_changed_event

    def __get_data_items(self):
        return tuple(self.__data_items)  # tuple makes it read only
    data_items = property(__get_data_items)

    # transactions, live state, and dependencies

    def get_source_data_items(self, data_item):
        with self.__dependent_data_items_lock:
            return copy.copy(self.__source_data_items.get(weakref.ref(data_item), list()))

    def get_dependent_data_items(self, data_item):
        """Return the list of data items containing data that directly depends on data in this item."""
        with self.__dependent_data_items_lock:
            return copy.copy(self.__dependent_data_items.get(weakref.ref(data_item), list()))

    def data_item_transaction(self, data_item):
        """ Return a context manager to put the data item under a 'transaction'. """
        class TransactionContextManager(object):
            def __init__(self, manager, object):
                self.__manager = manager
                self.__object = object
            def __enter__(self):
                self.__manager.begin_data_item_transaction(self.__object)
                return self
            def __exit__(self, type, value, traceback):
                self.__manager.end_data_item_transaction(self.__object)
        return TransactionContextManager(self, data_item)

    def begin_data_item_transaction(self, data_item):
        """Begin transaction state.

        A transaction state is exists to prevent writing out to disk, mainly for performance reasons.
        All changes to the object are delayed until the transaction state exits.

        Has the side effects of entering the write delay state, cache delay state (via is_cached_delayed),
        loading data of data sources, and entering transaction state for dependent data items.

        This method is thread safe.
        """
        with self.__transactions_lock:
            old_transaction_count = self.__transactions.get(data_item.uuid, 0)
            self.__transactions[data_item.uuid] = old_transaction_count + 1
        # if the old transaction count was 0, it means we're entering the transaction state.
        if old_transaction_count == 0:
            data_item._enter_transaction_state()
            # finally, tell dependent data items to enter their transaction states also
            # so that they also don't write change to disk immediately.
            for dependent_data_item in self.get_dependent_data_items(data_item):
                self.begin_data_item_transaction(dependent_data_item)

    def end_data_item_transaction(self, data_item):
        """End transaction state.

        Has the side effects of exiting the write delay state, cache delay state (via is_cached_delayed),
        unloading data of data sources, and exiting transaction state for dependent data items.

        As a consequence of exiting write delay state, data and metadata may be written to disk.

        As a consequence of existing cache delay state, cache may be written to disk.

        This method is thread safe.
        """
        # maintain the transaction count under a mutex
        with self.__transactions_lock:
            transaction_count = self.__transactions.get(data_item.uuid, 0) - 1
            assert transaction_count >= 0
            self.__transactions[data_item.uuid] = transaction_count
        # if the new transaction count is 0, it means we're exiting the transaction state.
        if transaction_count == 0:
            # first, tell our dependent data items to exit their transaction states.
            for dependent_data_item in self.get_dependent_data_items(data_item):
                self.end_data_item_transaction(dependent_data_item)
            data_item._exit_transaction_state()

    def data_item_live(self, data_item):
        """ Return a context manager to put the data item in a 'live state'. """
        class LiveContextManager(object):
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
        """Begins a live transaction for the data item.

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
        """Ends a live transaction for the data item.

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
            handler = ImportExportManager.NDataImportExportHandler("ndata1-io-handler", None, ["ndata1"])
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
            checkerboard_data_item = DataItem.DataItem(Image.create_checkerboard((512, 512)))
            checkerboard_data_item.title = "Checkerboard"
            self.append_data_item(checkerboard_data_item)
            # for testing, add a color image data item
            color_data_item = DataItem.DataItem(Image.create_color_image((512, 512), 128, 255, 128))
            color_data_item.title = "Green Color"
            self.append_data_item(color_data_item)
            # for testing, add a color image data item
            lena_data_item = DataItem.DataItem(scipy.misc.lena())
            lena_data_item.title = "Lena"
            self.append_data_item(lena_data_item)

    # this message comes from a data item when it wants to be removed from the document. ugh.
    def request_remove_data_item(self, data_item):
        DataGroup.get_data_item_container(self, data_item).remove_data_item(data_item)

    # TODO: what about thread safety for these classes?

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

    # access data items by title
    def get_data_item_by_title(self, title):
        for data_item in self.get_flat_data_item_generator():
            if data_item.title == title:
                return data_item
        return None

    # access data items by index
    def get_data_item_by_index(self, index):
        return list(self.get_flat_data_item_generator())[index]

    def get_index_for_data_item(self, data_item):
        return list(self.get_flat_data_item_generator()).index(data_item)

    # access data items by uuid
    def get_data_item_by_uuid(self, uuid: uuid.UUID) -> DataItem.DataItem:
        for data_item in self.get_flat_data_item_generator():
            if data_item.uuid == uuid:
                return data_item
        return None

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

    def recompute_all(self):
        self.__thread_pool.run_all()

    def start_dispatcher(self):
        self.__thread_pool.start(16)

    def create_computation(self, expression: str=None) -> Symbolic.Computation:
        computation = Symbolic.Computation(expression)
        computation.bind(self)
        return computation

    def computation_changed(self, buffered_data_source, computation):
        existing_computation_changed_listener = self.__computation_changed_listeners.get(buffered_data_source.uuid)
        if existing_computation_changed_listener:
            existing_computation_changed_listener.close()
            del self.__computation_changed_listeners[buffered_data_source.uuid]
        if computation:
            def computation_needs_update():
                def compute():
                    """Evaluate the computation, but make sure that only one thread is evaluating, and not too fast."""
                    if computation.begin_evaluate():
                        try:
                            while computation.needs_update:
                                with buffered_data_source.data_ref() as data_ref:
                                    data_and_metadata = computation.evaluate_data()
                                    if data_and_metadata:
                                        data_ref.data = data_and_metadata.data
                                        buffered_data_source.update_metadata(data_and_metadata.metadata)
                                        buffered_data_source.set_intensity_calibration(data_and_metadata.intensity_calibration)
                                        buffered_data_source.set_dimensional_calibrations(data_and_metadata.dimensional_calibrations)
                                time.sleep(0.05)
                        except Exception as e:
                            computation.error_text = _("Unable to compute data")
                        finally:
                            computation.end_evaluate()
                self.dispatch_task(compute)
            computation_changed_listener = computation.needs_update_event.listen(computation_needs_update)
            self.__computation_changed_listeners[buffered_data_source.uuid] = computation_changed_listener
            computation_needs_update()

    def get_object_specifier(self, object, property_name: str=None):
        if isinstance(object, DataItem.DataItem):
            if property_name:
                return {"version": 1, "type": "data_item", "uuid": str(object.uuid), "property": property_name}
            else:
                return {"version": 1, "type": "data_item", "uuid": str(object.uuid)}
        elif isinstance(object, Region.Region):
            return {"version": 1, "type": "region", "uuid": str(object.uuid)}
        return None

    def resolve_object_specifier(self, specifier: dict):
        document_model = self
        if specifier.get("version") == 1:
            specifier_type = specifier["type"]
            if specifier_type == "data_item":
                specifier_uuid_str = specifier.get("uuid")
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                data_item = self.get_data_item_by_uuid(object_uuid) if object_uuid else None
                property_name = specifier.get("property")
                class BoundDataItemAndMetadata(object):
                    def __init__(self, data_item):
                        self.__data_item = data_item
                        self.__buffered_data_source = data_item.maybe_data_source
                        self.changed_event = Event.Event()
                        self.deleted_event = Event.Event()
                        def data_and_metadata_changed():
                            self.changed_event.fire()
                        def data_item_will_be_removed(data_item):
                            if data_item == self.__data_item:
                                self.deleted_event.fire()
                        self.__data_and_metadata_changed_event_listener = self.__buffered_data_source.data_and_metadata_changed_event.listen(data_and_metadata_changed)
                        self.__data_item_will_be_removed_event_listener = document_model.data_item_will_be_removed_event.listen(data_item_will_be_removed)
                    @property
                    def value(self):
                        return self.__buffered_data_source.data_and_calibration
                    @property
                    def data_item(self):
                        return self.__data_item
                    def close(self):
                        self.__data_and_metadata_changed_event_listener.close()
                        self.__data_and_metadata_changed_event_listener = None
                        self.__data_item_will_be_removed_event_listener.close()
                        self.__data_item_will_be_removed_event_listener = None
                class BoundDataItem(object):
                    def __init__(self, data_item):
                        self.__data_item = data_item
                        self.__buffered_data_source = data_item.maybe_data_source
                        self.changed_event = Event.Event()
                        self.deleted_event = Event.Event()
                        def data_and_metadata_changed():
                            self.changed_event.fire()
                        def data_item_will_be_removed(data_item):
                            if data_item == self.__data_item:
                                self.deleted_event.fire()
                        self.__data_and_metadata_changed_event_listener = self.__buffered_data_source.data_and_metadata_changed_event.listen(data_and_metadata_changed)
                        self.__data_item_will_be_removed_event_listener = document_model.data_item_will_be_removed_event.listen(data_item_will_be_removed)
                    @property
                    def data(self):
                        return self.__data_item.maybe_data_source.data_and_calibration
                    @property
                    def display_data(self):
                        return self.__data_item.maybe_data_source.displays[0].display_data_and_calibration
                    @property
                    def data_item(self):
                        return self.__data_item
                    @property
                    def value(self):
                        return self
                    def close(self):
                        self.__data_and_metadata_changed_event_listener.close()
                        self.__data_and_metadata_changed_event_listener = None
                        self.__data_item_will_be_removed_event_listener.close()
                        self.__data_item_will_be_removed_event_listener = None
                class BoundDataItemDisplay(object):
                    def __init__(self, data_item):
                        self.__data_item = data_item
                        self.__buffered_data_source = data_item.maybe_data_source
                        self.changed_event = Event.Event()
                        self.deleted_event = Event.Event()
                        def display_changed():
                            self.changed_event.fire()
                        def data_item_will_be_removed(data_item):
                            if data_item == self.__data_item:
                                self.deleted_event.fire()
                        self.__display_changed_event_listener = self.__buffered_data_source.displays[0].display_changed_event.listen(display_changed)
                        self.__data_item_will_be_removed_event_listener = document_model.data_item_will_be_removed_event.listen(data_item_will_be_removed)
                    @property
                    def value(self):
                        return self.__buffered_data_source.displays[0].display_data_and_calibration
                    def close(self):
                        self.__display_changed_event_listener.close()
                        self.__display_changed_event_listener = None
                        self.__data_item_will_be_removed_event_listener.close()
                        self.__data_item_will_be_removed_event_listener = None
                if data_item:
                    if property_name == "data":
                        return BoundDataItemAndMetadata(data_item)
                    elif property_name == "display_data":
                        return BoundDataItemDisplay(data_item)
                    else:
                        return BoundDataItem(data_item)
            elif specifier_type == "region":
                specifier_uuid_str = specifier.get("uuid")
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                for data_item in self.data_items:
                    for data_source in data_item.data_sources:
                        for region in data_source.regions:
                            if region.uuid == object_uuid:
                                class BoundRegion(object):
                                    def __init__(self, object):
                                        self.__object = object
                                        self.changed_event = Event.Event()
                                        self.deleted_event = Event.Event()
                                        def remove_region():
                                            self.deleted_event.fire()
                                        self.__remove_region_because_graphic_removed_listener = self.__object.remove_region_because_graphic_removed_event.listen(remove_region)
                                        def property_changed(property_name_being_changed, value):
                                            self.changed_event.fire()
                                        self.__property_changed_listener = self.__object.property_changed_event.listen(property_changed)
                                    def close(self):
                                        self.__property_changed_listener.close()
                                        self.__property_changed_listener = None
                                        self.__remove_region_because_graphic_removed_listener.close()
                                        self.__remove_region_because_graphic_removed_listener = None
                                    @property
                                    def value(self):
                                        return self.__object
                                if region:
                                    return BoundRegion(region)
        return None

    class DataItemReference:
        def __init__(self, document_model: "DocumentModel", key: str, data_item: DataItem.DataItem=None):
            self.__document_model = document_model
            self.__key = key
            self.__data_item = data_item
            self.mutex = threading.RLock()
            self.data_item_changed_event = Event.Event()

        def close(self):
            pass

        # this method gets called directly from the document model
        def data_item_inserted(self, data_item):
            pass

        # this method gets called directly from the document model
        def data_item_removed(self, data_item):
            with self.mutex:
                if data_item == self.__data_item:
                    self.__data_item = None

        @property
        def data_item(self):
            with self.mutex:
                return self.__data_item

        @data_item.setter
        def data_item(self, value):
            with self.mutex:
                if self.__data_item != value:
                    self.__data_item = value
                    self.data_item_changed_event.fire()
                    self.__document_model._update_data_item_reference(self.__key, self.__data_item)

    def _update_data_item_reference(self, key: str, data_item: DataItem.DataItem) -> None:
        data_item_references_dict = copy.deepcopy(self._get_persistent_property_value("data_item_references"))
        if data_item:
            data_item_references_dict[key] = str(data_item.uuid)
        else:
            del data_item_references_dict[key]
        self._set_persistent_property_value("data_item_references", data_item_references_dict)

    def make_data_item_reference_key(self, *components) -> str:
        return "_".join([str(component) for component in list(components) if component is not None])

    def get_data_item_reference(self, key) -> "DocumentModel.DataItemReference":
        # this is implemented this way to avoid creating a data item reference unless it is missing.
        data_item_reference = self.__data_item_references.get(key)
        if data_item_reference:
            return data_item_reference
        return self.__data_item_references.setdefault(key, DocumentModel.DataItemReference(self, key))

    def setup_channel(self, hardware_source_id, channel_id, data_item):
        data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source_id, channel_id))
        data_item_reference.data_item = data_item

    def __construct_data_item_reference(self, hardware_source, channel_buffer, is_recording, append_data_item_fn):
        session_id = self.session_id
        data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, channel_buffer.channel_id))
        with data_item_reference.mutex:
            data_item = data_item_reference.data_item
            # if we still don't have a data item, create it.
            if not data_item:
                data_item = DataItem.DataItem()
                data_item.title = "%s (%s)" % (hardware_source.display_name, channel_buffer.name) if channel_buffer.name else hardware_source.display_name
                data_item.category = "temporary"
                buffered_data_source = DataItem.BufferedDataSource()
                data_item.append_data_source(buffered_data_source)
                data_item_reference.data_item = data_item
                data_item.increment_data_ref_counts()
                self.begin_data_item_transaction(data_item)
                self.begin_data_item_live(data_item)
                append_data_item_fn(data_item, is_recording)
            # update the session, but only if necessary (this is an optimization to prevent unnecessary display updates)
            if data_item.session_id != session_id:
                data_item.session_id = session_id
            session_metadata = self.session_metadata
            if data_item.session_metadata != session_metadata:
                data_item.session_metadata = session_metadata
            if channel_buffer.processor:
                src_channel_buffer = hardware_source.channel_buffers[channel_buffer.src_channel_index]
                src_data_item = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, src_channel_buffer.channel_id)).data_item
                channel_buffer.processor.connect(src_data_item, data_item)
            return data_item_reference

    def __channel_buffer_start(self, hardware_source, channel_buffer, append_data_item_fn):
        data_item = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, channel_buffer.channel_id)).data_item
        if data_item:
            data_item.increment_data_ref_counts()
            self.begin_data_item_transaction(data_item)
            self.begin_data_item_live(data_item)

    def __channel_buffer_stop(self, hardware_source, channel_buffer, append_data_item_fn):
        data_item = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, channel_buffer.channel_id)).data_item
        # the order of these two statements is important, at least for now (12/2013)
        # when the transaction ends, the data will get written to disk, so we need to
        # make sure it's still in memory. if decrement were to come before the end
        # of the transaction, the data would be unloaded from memory, losing it forever.
        if data_item:
            self.end_data_item_transaction(data_item)
            self.end_data_item_live(data_item)
            data_item.decrement_data_ref_counts()

    def __channel_buffer_updated(self, hardware_source, channel_buffer, append_data_item_fn, data_and_metadata, is_recording):
        data_item_reference = self.__construct_data_item_reference(hardware_source, channel_buffer, is_recording, append_data_item_fn)
        data_item = data_item_reference.data_item
        channel_data_state = channel_buffer.state
        sub_area = channel_buffer.sub_area
        # until the whole pipeline is cleaned up, recreate the data_element. guh.
        data_element = HardwareSource.convert_data_and_metadata_to_data_element(data_and_metadata)
        if sub_area:
            data_element["sub_area"] = sub_area
        ImportExportManager.update_data_item_from_data_element(data_item, data_element)
        if is_recording and channel_data_state == "complete":
            append_data_item_fn(copy.deepcopy(data_item), is_recording)

    def __channel_buffer_states_updated(self, hardware_source, channel_buffers):
        data_item_states = list()
        for channel_buffer in channel_buffers:
            data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, channel_buffer.channel_id))
            data_item = data_item_reference.data_item
            channel_id = channel_buffer.channel_id
            channel_data_state = channel_buffer.state
            sub_area = channel_buffer.sub_area
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

    def __hardware_source_added(self, append_data_item_fn, hardware_source):
        self.__channel_buffer_states_updated_listeners[hardware_source.hardware_source_id] = hardware_source.channel_buffer_states_updated.listen(functools.partial(self.__channel_buffer_states_updated, hardware_source))
        for channel_buffer in hardware_source.channel_buffers:
            channel_buffer_updated_listener = channel_buffer.channel_buffer_updated_event.listen(functools.partial(self.__channel_buffer_updated, hardware_source, channel_buffer, append_data_item_fn))
            self.__channel_buffer_updated_listeners.setdefault(hardware_source.hardware_source_id, list()).append(channel_buffer_updated_listener)
            channel_buffer_start_listener = channel_buffer.channel_buffer_start_event.listen(functools.partial(self.__channel_buffer_start, hardware_source, channel_buffer, append_data_item_fn))
            self.__channel_buffer_start_listeners.setdefault(hardware_source.hardware_source_id, list()).append(channel_buffer_start_listener)
            channel_buffer_stop_listener = channel_buffer.channel_buffer_stop_event.listen(functools.partial(self.__channel_buffer_stop, hardware_source, channel_buffer, append_data_item_fn))
            self.__channel_buffer_stop_listeners.setdefault(hardware_source.hardware_source_id, list()).append(channel_buffer_stop_listener)

    def __hardware_source_removed(self, hardware_source):
        self.__channel_buffer_states_updated_listeners[hardware_source.hardware_source_id].close()
        del self.__channel_buffer_states_updated_listeners[hardware_source.hardware_source_id]
        for listener in self.__channel_buffer_updated_listeners.get(hardware_source.hardware_source_id, list()):
            listener.close()
        for listener in self.__channel_buffer_start_listeners.get(hardware_source.hardware_source_id, list()):
            listener.close()
        for listener in self.__channel_buffer_stop_listeners.get(hardware_source.hardware_source_id, list()):
            listener.close()
        self.__channel_buffer_updated_listeners.pop(hardware_source.hardware_source_id, None)
        self.__channel_buffer_start_listeners.pop(hardware_source.hardware_source_id, None)
        self.__channel_buffer_stop_listeners.pop(hardware_source.hardware_source_id, None)

    Requirement = collections.namedtuple("Requirement", ["type", "mn", "mx"])

    @staticmethod
    def make_requirement(type, mn=None, mx=None):
        return DocumentModel.Requirement(type, mn, mx)

    Source = collections.namedtuple("Source", ["data_item", "crop_region", "name", "label", "use_display_data", "requirements", "regions"])

    @staticmethod
    def make_source(data_item, crop_region=None, name=None, label=None, use_display_data=True, requirements=None, regions=None):
        return DocumentModel.Source(data_item, crop_region, name, label, use_display_data, requirements, regions)

    Parameter = collections.namedtuple("Parameter", ["name", "label", "type", "value", "value_default", "value_min", "value_max", "control_type"])

    @staticmethod
    def make_parameter(name, label, type, value, value_default=None, value_min=None, value_max=None, control_type=None):
        return DocumentModel.Parameter(name, label, type, value, value_default, value_min, value_max, control_type)

    Region_ = collections.namedtuple("Region", ["name", "type", "label", "region"])

    @staticmethod
    def make_region(name, type, label=None, region=None):
        return DocumentModel.Region_(name, type, label, region)

    Connection = collections.namedtuple("Connection", ["type", "src", "src_prop", "dst", "dst_prop"])

    @staticmethod
    def make_connection(type, src=None, src_prop=None, dst=None, dst_prop=None):
        return DocumentModel.Connection(type, src, src_prop, dst, dst_prop)

    def __get_processing_new(self, fn_template: str, sources: List, params: List, label: str, prefix: str=None, out_regions=None, connections=None) -> DataItem.DataItem:
        data_items = [source.data_item for source in sources]
        display_specifiers = [DataItem.DisplaySpecifier.from_data_item(data_item) for data_item in data_items]
        buffered_data_sources = [display_specifier.buffered_data_source for display_specifier in display_specifiers]
        for source, buffered_data_source in zip(sources, buffered_data_sources):
            for requirement in source.requirements or list():
                if requirement.type == "dimensionality":
                    dimensionality = len(buffered_data_source.dimensional_shape)
                    if requirement.mn is not None and dimensionality < requirement.mn:
                        return None
                    if requirement.mx is not None and dimensionality > requirement.mx:
                        return None
        if len(buffered_data_sources) > 0 and all(buffered_data_sources):
            new_data_item = DataItem.DataItem()
            prefix = prefix if prefix else "{} of ".format(label)
            new_data_item.title = prefix + data_items[0].title
            new_data_item.category = data_items[0].category
            src_names = list()
            src_texts = list()
            crop_names = list()
            regions = list()
            region_map = dict()
            for i, (source, buffered_data_source) in enumerate(zip(sources, buffered_data_sources)):
                suffix = i if len(sources) > 1 else ""
                src_name = source.name if source.name else "src{}".format(suffix)
                src_text = "{}.{}".format(src_name, "display_data" if source.use_display_data else "data")
                crop_name = "crop_region{}".format(suffix) if source.crop_region else ""
                src_text = src_text if not source.crop_region else "crop({}, {}.bounds)".format(src_text, crop_name)
                src_names.append(src_name)
                src_texts.append(src_text)
                crop_names.append(crop_name)
                for region in source.regions or list():
                    if region.type == "point":
                        if region.region:
                            point_region = region.region
                        else:
                            point_region = Region.PointRegion()
                            point_region.label = region.label
                            buffered_data_source.add_region(point_region)
                        regions.append((region.name, point_region, region.label))
                        region_map[region.name] = point_region
                    elif region.type == "line":
                        if region.region:
                            line_region = region.region
                        else:
                            line_region = Region.LineRegion()
                            line_region.start = 0.25, 0.25
                            line_region.end = 0.75, 0.75
                            buffered_data_source.add_region(line_region)
                        regions.append((region.name, line_region, region.label))
                        region_map[region.name] = line_region
                    elif region.type == "rectangle":
                        if region.region:
                            rect_region = region.region
                        else:
                            rect_region = Region.RectRegion()
                            rect_region.center = 0.5, 0.5
                            rect_region.size = 0.5, 0.5
                            rect_region.label = region.label
                            buffered_data_source.add_region(rect_region)
                        regions.append((region.name, rect_region, region.label))
                        region_map[region.name] = rect_region
            expression = fn_template.format(**dict(zip(src_names, src_texts)))
            computation = self.create_computation(expression)
            for src_name, display_specifier, source in zip(src_names, display_specifiers, sources):
                computation.create_object(src_name, self.get_object_specifier(display_specifier.data_item), label=source.label, cascade_delete=True)
            for crop_name, source in zip(crop_names, sources):
                if crop_name:
                    computation.create_object(crop_name, self.get_object_specifier(source.crop_region), label=_("Crop Region"), cascade_delete=True)
            for region_name, region, region_label in regions:
                computation.create_object(region_name, self.get_object_specifier(region), label=region_label, cascade_delete=True)
            for param in params:
                computation.create_variable(param.name, param.type, param.value, value_default=param.value_default, value_min=param.value_min, value_max=param.value_max,
                                            control_type=param.control_type, label=param.label)
            computation.label = label
            buffered_data_source = DataItem.BufferedDataSource()
            new_data_item.append_data_source(buffered_data_source)
            buffered_data_source.set_computation(computation)
            new_regions = dict()
            for region in out_regions or list():
                if region.type == "interval":
                    interval_region = Region.IntervalRegion()
                    buffered_data_source.add_region(interval_region)
                    new_regions[region.name] = interval_region
            for connection in connections or list():
                if connection.type == "property":
                    if connection.src == "display":
                        # TODO: how to refer to the buffered_data_sources?
                        new_data_item.add_connection(Connection.PropertyConnection(buffered_data_sources[0].displays[0], connection.src_prop, new_regions[connection.dst], connection.dst_prop))
                elif connection.type == "interval_list":
                    new_data_item.add_connection(Connection.IntervalListConnection(buffered_data_source, region_map[connection.dst]))
            return new_data_item
        return None

    def get_fft_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"))
        return self.__get_processing_new("fft({src})", [src], [], _("FFT"))

    def get_ifft_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, None, "src", _("Source"), use_display_data=False)
        return self.__get_processing_new("ifft({src})", [src], [], _("Inverse FFT"))

    def get_auto_correlate_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"))
        return self.__get_processing_new("autocorrelate({src})", [src], [], _("Auto Correlate"))

    def get_cross_correlate_new(self, data_item1: DataItem.DataItem, crop_region1: Region.RectRegion, data_item2: DataItem.DataItem, crop_region2: Region.RectRegion) -> DataItem.DataItem:
        src1 = DocumentModel.make_source(data_item1, crop_region1, "src1", _("Source1"))
        src2 = DocumentModel.make_source(data_item2, crop_region2, "src2", _("Source2"))
        return self.__get_processing_new("crosscorrelate({src1}, {src2})", [src1, src2], [], _("Cross Correlate"))

    def get_sobel_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"))
        return self.__get_processing_new("sobel({src})", [src], [], _("Sobel"))

    def get_laplace_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"))
        return self.__get_processing_new("laplace({src})", [src], [], _("Laplace"))

    def get_gaussian_blur_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"))
        param = DocumentModel.make_parameter("sigma", _("Sigma"), "real", 3, value_default=3, value_min=0, value_max=100, control_type="slider")
        return self.__get_processing_new("gaussian_blur({src}, sigma)", [src], [param], _("Gaussian Blur"))

    def get_median_filter_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"))
        param = DocumentModel.make_parameter("filter_size", _("Size"), "integral", 3, value_default=3, value_min=1, value_max=100)
        return self.__get_processing_new("median_filter({src}, filter_size)", [src], [param], _("Median Filter"))

    def get_uniform_filter_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"))
        param = DocumentModel.make_parameter("filter_size", _("Size"), "integral", 3, value_default=3, value_min=1, value_max=100)
        return self.__get_processing_new("uniform_filter({src}, filter_size)", [src], [param], _("Uniform Filter"))

    def get_transpose_flip_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"))
        param1 = DocumentModel.make_parameter("do_transpose", _("Transpose"), "boolean", False, value_default=False)
        param2 = DocumentModel.make_parameter("do_flip_v", _("Flip Vertical"), "boolean", False, value_default=False)
        param3 = DocumentModel.make_parameter("do_flip_h", _("Flip Horizontal"), "boolean", False, value_default=False)
        return self.__get_processing_new("transpose_flip({src}, do_transpose, do_flip_v, do_flip_h)", [src], [param1, param2, param3], _("Transpose/Flip"))

    def get_resample_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"))
        param1 = DocumentModel.make_parameter("width", _("Width"), "integral", 256, value_default=256, value_min=1)
        param2 = DocumentModel.make_parameter("height", _("Height"), "integral", 256, value_default=256, value_min=1)
        return self.__get_processing_new("resample_image({src}, shape(height, width))", [src], [param1, param2], _("Resample"))

    def get_histogram_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"))
        param = DocumentModel.make_parameter("bins", _("Bins"), "integral", 256, value_default=256, value_min=2)
        return self.__get_processing_new("histogram({src}, bins)", [src], [param], _("Histogram"))

    def get_invert_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"))
        return self.__get_processing_new("invert({src})", [src], [], _("Invert"))

    def get_convert_to_scalar_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"))
        return self.__get_processing_new("{src}", [src], [], _("Scalar"))

    def get_crop_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        requirement = DocumentModel.make_requirement("dimensionality", mn=2, mx=2)
        in_region = DocumentModel.make_region("crop_region", "rectangle", _("Crop Region"), crop_region)
        src = DocumentModel.make_source(data_item, None, "src", _("Source"), regions=[in_region], requirements=[requirement])
        return self.__get_processing_new("crop({src}, crop_region.bounds)", [src], [], _("Crop"))

    def get_projection_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        requirement = DocumentModel.make_requirement("dimensionality", mn=2, mx=2)
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"), use_display_data=False, requirements=[requirement])
        return self.__get_processing_new("sum({src}, 0)", [src], [], _("Sum"))

    def get_slice_sum_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        requirement = DocumentModel.make_requirement("dimensionality", mn=3, mx=3)
        src = DocumentModel.make_source(data_item, crop_region, "src", _("Source"), use_display_data=False, requirements=[requirement])
        param1 = DocumentModel.make_parameter("center", _("Center"), "integral", 0, value_default=0, value_min=0)
        param2 = DocumentModel.make_parameter("width", _("Width"), "integral", 1, value_default=1, value_min=1)
        return self.__get_processing_new("slice_sum({src}, center, width)", [src], [param1, param2], _("Slice"))

    def get_pick_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion, pick_region: Region.PointRegion=None) -> DataItem.DataItem:
        requirement = DocumentModel.make_requirement("dimensionality", mn=3, mx=3)
        in_region = DocumentModel.make_region("pick_region", "point", _("Pick Point"), pick_region)
        out_region = DocumentModel.make_region("interval_region", "interval")
        connection = DocumentModel.make_connection("property", src="display", src_prop="slice_interval", dst="interval_region", dst_prop="interval")
        src = DocumentModel.make_source(data_item, None, "src", _("Source"), use_display_data=False, regions=[in_region], requirements=[requirement])
        return self.__get_processing_new("pick({src}, pick_region.position)", [src], [], _("Slice"), out_regions=[out_region], connections=[connection])

    def get_line_profile_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion, line_region: Region.LineRegion=None) -> DataItem.DataItem:
        in_region = DocumentModel.make_region("line_region", "line", _("Line Profile"), line_region)
        connection = DocumentModel.make_connection("interval_list", src="data_source", dst="line_region")
        src = DocumentModel.make_source(data_item, None, "src", _("Source"), regions=[in_region])
        return self.__get_processing_new("line_profile({src}, line_region.vector, line_region.width)", [src], [], _("Line Profile"), connections=[connection])
