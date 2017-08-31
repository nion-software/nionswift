# standard libraries
import asyncio
import collections
import copy
import datetime
import functools
import gettext
import json
import logging
import numbers
import os.path
import shutil
import threading
import time
import typing
import uuid
import weakref

# third party libraries
import numpy
import scipy

# local libraries
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import Cache
from nion.swift.model import Connection
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.model import HardwareSource
from nion.swift.model import ImportExportManager
from nion.swift.model import PlugInManager
from nion.swift.model import Symbolic
from nion.swift.model import Utility
from nion.swift.model import WorkspaceLayout
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Observable
from nion.utils import Persistence
from nion.utils import Recorder
from nion.utils import ReferenceCounting
from nion.utils import ThreadPool

_ = gettext.gettext


class FilePersistentStorage:
    # this class is used to store the data for the library itself.
    # it is not used for library items.

    def __init__(self, filepath=None):
        self.__filepath = filepath
        self.__properties = self.__read_properties()
        self.__properties_lock = threading.RLock()

    def get_version(self):
        return 0

    def __read_properties(self):
        properties = dict()
        if self.__filepath and os.path.exists(self.__filepath):
            try:
                with open(self.__filepath, "r") as fp:
                    properties = json.load(fp)
            except Exception:
                os.replace(self.__filepath, self.__filepath + ".bak")
        # migrations go here
        return properties

    def __write_properties(self):
        if self.__filepath:
            # atomically overwrite
            temp_filepath = self.__filepath + ".temp"
            with open(temp_filepath, "w") as fp:
                json.dump(self.__properties, fp)
            os.replace(temp_filepath, self.__filepath)

    @property
    def properties(self):
        with self.__properties_lock:
            return copy.deepcopy(self.__properties)

    def _set_properties(self, properties):
        """Set the properties; used for testing."""
        with self.__properties_lock:
            self.__properties = properties

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

    def insert_item(self, parent, name, before_index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict.setdefault(name, list())
            item_dict = item.write_to_dict()
            item_list.insert(before_index, item_dict)
            item.persistent_object_context = parent.persistent_object_context
        self.__write_properties()

    def remove_item(self, parent, name, index, item):
        storage_dict = self.__update_modified_and_get_storage_dict(parent)
        with self.__properties_lock:
            item_list = storage_dict[name]
            del item_list[index]
        self.__write_properties()
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
        self.__write_properties()

    def set_property(self, object, name, value):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict[name] = value
        self.__write_properties()


class DataItemStorage:

    """
        Manages storage for data items by caching properties and data, maintaining the PersistentObjectContext
        on contained items, and writing to disk when necessary.

        The storage_handler must respond to these methods:
            read_properties()
            read_data()
            write_properties(properties, file_datetime)
            write_data(data, file_datetime)
    """

    def __init__(self, storage_handler=None, data_item=None, properties=None):
        self.__storage_handler = storage_handler
        self.__properties = Utility.clean_dict(copy.deepcopy(properties) if properties else dict())
        self.__properties_lock = threading.RLock()
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
        self.write_delayed = False

    def close(self):
        if self.__storage_handler:
            self.__storage_handler.close()
            self.__storage_handler = None

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
    def _storage_handler(self):
        return self.__storage_handler

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
            self.__storage_handler.write_properties(self.properties, file_datetime)

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
                item.persistent_object_context = None
                item.persistent_object_context = parent.persistent_object_context
            else:
                if name in storage_dict:
                    del storage_dict[name]
        self.update_properties()

    def update_data(self, data):
        if not self.write_delayed:
            file_datetime = self.data_item.created_local
            if data is not None:
                self.__storage_handler.write_data(data, file_datetime)

    def load_data(self):
        assert self.data_item.has_data
        return self.__storage_handler.read_data()

    def set_property(self, object, name, value):
        storage_dict = self.__update_modified_and_get_storage_dict(object)
        with self.__properties_lock:
            storage_dict[name] = value
        self.update_properties()

    def remove(self):
        self.__storage_handler.remove()


class MemoryStorageSystem:

    def __init__(self):
        self.data = dict()
        self.properties = dict()
        self._test_data_read_event = Event.Event()

    class MemoryStorageHandler:

        def __init__(self, uuid, properties, data, data_read_event):
            self.__uuid = uuid
            self.__properties = properties
            self.__data = data
            self.__data_read_event = data_read_event

        def close(self):
            self.__uuid = None
            self.__properties = None
            self.__data = None

        @property
        def reference(self):
            return str(self.__uuid)

        def read_properties(self):
            return self.__properties.get(self.__uuid, dict())

        def read_data(self):
            self.__data_read_event.fire(self.__uuid)
            return self.__data.get(self.__uuid)

        def write_properties(self, properties, file_datetime):
            self.__properties[self.__uuid] = Utility.clean_dict(copy.deepcopy(properties))

        def write_data(self, data, file_datetime):
            self.__data[self.__uuid] = data.copy()

        def remove(self):
            self.__data.pop(self.__uuid, None)
            self.__properties.pop(self.__uuid, None)

    def find_data_items(self):
        storage_handlers = list()
        for key in sorted(self.properties):
            self.properties[key].setdefault("uuid", str(uuid.uuid4()))
            storage_handlers.append(MemoryStorageSystem.MemoryStorageHandler(key, self.properties, self.data, self._test_data_read_event))
        return storage_handlers

    def make_storage_handler(self, data_item):
        uuid = str(data_item.uuid)
        return MemoryStorageSystem.MemoryStorageHandler(uuid, self.properties, self.data, self._test_data_read_event)


from nion.swift.model import NDataHandler
from nion.swift.model import HDF5Handler

class FileStorageSystem:

    _file_handlers = [NDataHandler.NDataHandler, HDF5Handler.HDF5Handler]

    def __init__(self, directories):
        self.__directories = directories
        self.__file_handlers = FileStorageSystem._file_handlers

    def find_data_items(self):
        storage_handlers = list()
        absolute_file_paths = set()
        for directory in self.__directories:
            for root, dirs, files in os.walk(directory):
                absolute_file_paths.update([os.path.join(root, data_file) for data_file in files])
        for file_handler in self.__file_handlers:
            for data_file in filter(file_handler.is_matching, absolute_file_paths):
                try:
                    storage_handler = file_handler(data_file)
                    assert storage_handler.is_valid
                    storage_handlers.append(storage_handler)
                except Exception as e:
                    logging.error("Exception reading file: %s", data_file)
                    logging.error(str(e))
                    raise
        return storage_handlers

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

    def make_storage_handler(self, data_item):
        # if there are two handlers, first is small, second is large
        # if there is only one handler, it is used in all cases
        file_handler = self.__file_handlers[-1] if data_item.large_format else self.__file_handlers[0]
        return file_handler.make(os.path.join(self.__directories[0], self.__get_default_path(data_item)))


class PersistentDataItemContext(Persistence.PersistentObjectContext):

    """
        A PersistentObjectContext that adds extra methods for handling data items.

        Versioning

        If the file is too old, it must be migrated to the newer version.
        If the file is too new, it cannot be loaded.

        When writing, the version the file format is written to the 'version' property.

    """

    def __init__(self, persistent_storage_systems=None, ignore_older_files: bool=False, log_migrations: bool=True, log_copying: bool=False):
        super().__init__()
        self.__persistent_storage_systems = persistent_storage_systems if persistent_storage_systems else [MemoryStorageSystem()]
        self.__ignore_older_files = ignore_older_files
        self.__log_migrations = log_migrations
        self.__log_copying = log_copying

    @property
    def persistent_storage_systems(self):
        return self.__persistent_storage_systems

    def read_data_items_version_stats(self):
        storage_handlers = list()  # storage_handler
        for persistent_storage_system in self.__persistent_storage_systems:
            storage_handlers.extend(persistent_storage_system.find_data_items())
        count = [0, 0, 0]  # data item matches version, data item has higher version, data item has lower version
        writer_version = DataItem.DataItem.writer_version
        for storage_handler in storage_handlers:
            properties = storage_handler.read_properties()
            version = properties.get("version", 0)
            if version < writer_version:
                count[2] += 1
            elif version > writer_version:
                count[1] += 1
            else:
                count[0] += 1
        return count

    def read_data_items(self, target_document=None):
        """
        Read data items from the data reference handler and return as a list.

        Data items will have persistent_object_context set upon return, but caller will need to call finish_reading
        on each of the data items.

        Pass target_document to copy data items into new document. Useful for auto migration.
        """
        storage_handlers = list()  # storage_handler
        for persistent_storage_system in self.__persistent_storage_systems:
            storage_handlers.extend(persistent_storage_system.find_data_items())
        data_items_by_uuid = dict()
        ReaderInfo = collections.namedtuple("ReaderInfo", ["properties", "changed_ref", "storage_handler"])
        reader_info_list = list()
        for storage_handler in storage_handlers:
            try:
                reader_info_list.append(ReaderInfo(storage_handler.read_properties(), [False], storage_handler))
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()
        if not self.__ignore_older_files:
            self.__migrate_to_latest(reader_info_list)
        for reader_info in reader_info_list:
            properties = reader_info.properties
            changed_ref = reader_info.changed_ref
            storage_handler = reader_info.storage_handler
            try:
                version = properties.get("version", 0)
                if version == DataItem.DataItem.writer_version:
                    data_item_uuid = uuid.UUID(properties["uuid"])
                    if target_document is not None:
                        if not target_document.get_data_item_by_uuid(data_item_uuid):
                            new_data_item = self.__auto_migrate_data_item(data_item_uuid, storage_handler, properties, target_document)
                            if new_data_item:
                                data_items_by_uuid[data_item_uuid] = new_data_item
                    else:
                        if changed_ref[0]:
                            storage_handler.write_properties(copy.deepcopy(properties), datetime.datetime.now())
                        # NOTE: Search for to-do 'file format' to gather together 'would be nice' changes
                        # NOTE: change writer_version in DataItem.py
                        if len(properties.get("data_item_uuids", list())) > 0:
                            data_item = DataItem.CompositeLibraryItem(item_uuid=data_item_uuid)
                            data_item.begin_reading()
                            persistent_storage = DataItemStorage(storage_handler=storage_handler, data_item=data_item, properties=properties)
                            data_item.read_from_dict(persistent_storage.properties)
                            self._set_persistent_storage_for_object(data_item, persistent_storage)
                            data_item.persistent_object_context = self
                            if self.__log_migrations and data_item.uuid in data_items_by_uuid:
                                logging.info("Warning: Duplicate data item %s", data_item.uuid)
                            data_items_by_uuid[data_item.uuid] = data_item
                        else:
                            large_format = isinstance(storage_handler, HDF5Handler.HDF5Handler)
                            data_item = DataItem.DataItem(item_uuid=data_item_uuid, large_format=large_format)
                            data_item.begin_reading()
                            persistent_storage = DataItemStorage(storage_handler=storage_handler, data_item=data_item, properties=properties)
                            data_item.read_from_dict(persistent_storage.properties)
                            self._set_persistent_storage_for_object(data_item, persistent_storage)
                            data_item.persistent_object_context = self
                            if self.__log_migrations and data_item.uuid in data_items_by_uuid:
                                logging.info("Warning: Duplicate data item %s", data_item.uuid)
                            data_items_by_uuid[data_item.uuid] = data_item
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()
        def sort_by_date_key(data_item):
            return data_item.created
        data_items = list(data_items_by_uuid.values())
        data_items.sort(key=sort_by_date_key)
        return data_items

    def __auto_migrate_data_item(self, data_item_uuid, storage_handler, properties, target_document):
        new_data_item = None
        target_storage_handler = None
        for persistent_storage_system in target_document.persistent_object_context.persistent_storage_systems:
            # create a temporary data item that can be used to get the new file reference
            old_data_item = DataItem.DataItem(item_uuid=data_item_uuid)
            old_data_item.begin_reading()
            old_data_item.read_from_dict(properties)
            old_data_item.finish_reading()
            target_storage_handler = persistent_storage_system.make_storage_handler(old_data_item)
            if target_storage_handler:
                break
        if target_storage_handler:
            os.makedirs(os.path.dirname(target_storage_handler.reference), exist_ok=True)
            shutil.copyfile(storage_handler.reference, target_storage_handler.reference)
            target_storage_handler.write_properties(copy.deepcopy(properties), datetime.datetime.now())
            new_data_item = DataItem.DataItem(item_uuid=data_item_uuid)
            new_data_item.begin_reading()
            persistent_storage = DataItemStorage(storage_handler=target_storage_handler, data_item=new_data_item, properties=properties)
            new_data_item.read_from_dict(persistent_storage.properties)
            target_document.persistent_object_context._set_persistent_storage_for_object(new_data_item, persistent_storage)
            new_data_item.persistent_object_context = target_document.persistent_object_context
            if self.__log_copying:
                logging.info("Copying data item %s to library.", data_item_uuid)
        elif self.__log_copying:
            logging.info("Unable to copy data item %s to library.", data_item_uuid)
        return new_data_item

    def __migrate_to_latest(self, reader_info_list):
        self.__migrate_to_v2(reader_info_list)
        self.__migrate_to_v3(reader_info_list)
        self.__migrate_to_v4(reader_info_list)
        self.__migrate_to_v5(reader_info_list)
        self.__migrate_to_v6(reader_info_list)
        self.__migrate_to_v7(reader_info_list)
        self.__migrate_to_v8(reader_info_list)
        self.__migrate_to_v9(reader_info_list)
        self.__migrate_to_v10(reader_info_list)
        self.__migrate_to_v11(reader_info_list)

    def __migrate_to_v11(self, reader_info_list):
        for reader_info in reader_info_list:
            storage_handler = reader_info.storage_handler
            properties = reader_info.properties
            try:
                version = properties.get("version", 0)
                if version == 10:
                    reader_info.changed_ref[0] = True
                    # pprint.pprint(properties)
                    # version 9 -> 10 merges regions into graphics.
                    data_source_dicts = properties.get("data_sources", list())
                    if len(data_source_dicts) > 0:
                        data_source_dict = data_source_dicts[0]

                        # update computation content
                        variables_dict = data_source_dict.get("computation", dict()).get("variables")
                        processing_id = data_source_dict.get("computation", dict()).get("processing_id")
                        if variables_dict and processing_id:
                            # import pprint
                            # print(pprint.pformat(variables_dict))
                            variable_lookup = dict()
                            for variable_dict in variables_dict:
                                variable_lookup[variable_dict['name']] = variable_dict
                            if "src" in variable_lookup and "crop_region" in variable_lookup:
                                variable_lookup["src"]["secondary_specifier"] = copy.deepcopy(variable_lookup["crop_region"]["specifier"])
                                variables_dict.remove(variable_lookup["crop_region"])
                            if "src1" in variable_lookup and "crop_region0" in variable_lookup:
                                variable_lookup["src1"]["secondary_specifier"] = copy.deepcopy(variable_lookup["crop_region0"]["specifier"])
                                variables_dict.remove(variable_lookup["crop_region0"])
                            if "src2" in variable_lookup and "crop_region1" in variable_lookup:
                                variable_lookup["src2"]["secondary_specifier"] = copy.deepcopy(variable_lookup["crop_region1"]["specifier"])
                                variables_dict.remove(variable_lookup["crop_region1"])
                            # print(pprint.pformat(variables_dict))
                            # print("-----------------------")

                        # update computation location
                        computation = data_source_dict.get("computation")
                        if computation:
                            properties["computation"] = computation
                        data_source_dict.pop("computation", None)

                        # update displays location
                        displays = data_source_dict.get("displays")
                        if displays and len(displays) > 0:
                            properties["displays"] = displays[0:1]
                        data_source_dict.pop("displays", None)

                        # update data_source location
                        properties["data_source"] = data_source_dict

                    # get rid of data_sources
                    properties.pop("data_sources", None)

                    # change metadata to description
                    properties["description"] = properties.pop("metadata", dict()).get("description", dict())

                    properties["version"] = 11

                    if self.__log_migrations:
                        logging.info("Updated %s to %s (computed data items combined crop, data source merge)", storage_handler.reference, properties["version"])
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

    def __migrate_to_v10(self, reader_info_list):
        translate_region_type = {"point-region": "point-graphic", "line-region": "line-profile-graphic", "rectangle-region": "rect-graphic", "ellipse-region": "ellipse-graphic",
            "interval-region": "interval-graphic"}
        for reader_info in reader_info_list:
            storage_handler = reader_info.storage_handler
            properties = reader_info.properties
            try:
                version = properties.get("version", 0)
                if version == 9:
                    reader_info.changed_ref[0] = True
                    # import pprint
                    # pprint.pprint(properties)
                    for data_source in properties.get("data_sources", list()):
                        displays = data_source.get("displays", list())
                        if len(displays) > 0:
                            display = displays[0]
                            for region in data_source.get("regions", list()):
                                graphic = dict()
                                graphic["type"] = translate_region_type[region["type"]]
                                graphic["uuid"] = region["uuid"]
                                region_id = region.get("region_id")
                                if region_id is not None:
                                    graphic["graphic_id"] = region_id
                                label = region.get("label")
                                if label is not None:
                                    graphic["label"] = label
                                is_position_locked = region.get("is_position_locked")
                                if is_position_locked is not None:
                                    graphic["is_position_locked"] = is_position_locked
                                is_shape_locked = region.get("is_shape_locked")
                                if is_shape_locked is not None:
                                    graphic["is_shape_locked"] = is_shape_locked
                                is_bounds_constrained = region.get("is_bounds_constrained")
                                if is_bounds_constrained is not None:
                                    graphic["is_bounds_constrained"] = is_bounds_constrained
                                center = region.get("center")
                                size = region.get("size")
                                if center is not None and size is not None:
                                    graphic["bounds"] = (center[0] - size[0] * 0.5, center[1] - size[1] * 0.5), (size[0], size[1])
                                start = region.get("start")
                                if start is not None:
                                    graphic["start"] = start
                                end = region.get("end")
                                if end is not None:
                                    graphic["end"] = end
                                width = region.get("width")
                                if width is not None:
                                    graphic["width"] = width
                                position = region.get("position")
                                if position is not None:
                                    graphic["position"] = position
                                interval = region.get("interval")
                                if interval is not None:
                                    graphic["interval"] = interval
                                display.setdefault("graphics", list()).append(graphic)
                        data_source.pop("regions", None)
                    for connection in properties.get("connections", list()):
                        if connection.get("type") == "interval-list-connection":
                            connection["source_uuid"] = properties["data_sources"][0]["displays"][0]["uuid"]
                    # pprint.pprint(properties)
                    # version 9 -> 10 merges regions into graphics.
                    properties["version"] = 10
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (regions merged into graphics)", storage_handler.reference, properties["version"])
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

    def __migrate_to_v9(self, reader_info_list):
        data_source_uuid_to_data_item_uuid = dict()
        for reader_info in reader_info_list:
            storage_handler = reader_info.storage_handler
            properties = reader_info.properties
            try:
                data_source_dicts = properties.get("data_sources", list())
                for data_source_dict in data_source_dicts:
                    data_source_uuid_to_data_item_uuid[data_source_dict["uuid"]] = properties["uuid"]
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

        for reader_info in reader_info_list:
            storage_handler = reader_info.storage_handler
            properties = reader_info.properties
            try:
                version = properties.get("version", 0)
                if version == 8:
                    reader_info.changed_ref[0] = True
                    # version 8 -> 9 changes operations to computations
                    data_source_dicts = properties.get("data_sources", list())
                    for data_source_dict in data_source_dicts:
                        metadata = data_source_dict.get("metadata", dict())
                        hardware_source_dict = metadata.get("hardware_source", dict())
                        high_tension_v = hardware_source_dict.get("extra_high_tension")
                        # hardware_source_dict.pop("extra_high_tension", None)
                        if high_tension_v:
                            autostem_dict = hardware_source_dict.setdefault("autostem", dict())
                            autostem_dict["high_tension_v"] = high_tension_v
                    data_source_dicts = properties.get("data_sources", list())
                    ExpressionInfo = collections.namedtuple("ExpressionInfo", ["label", "expression", "processing_id", "src_labels", "src_names", "variables", "use_display_data"])
                    info = dict()
                    info["fft-operation"] = ExpressionInfo(_("FFT"), "xd.fft({src})", "fft", [_("Source")], ["src"], list(), True)
                    info["inverse-fft-operation"] = ExpressionInfo(_("Inverse FFT"), "xd.ifft({src})", "inverse-fft", [_("Source")], ["src"], list(), False)
                    info["auto-correlate-operation"] = ExpressionInfo(_("Auto Correlate"), "xd.autocorrelate({src})", "auto-correlate", [_("Source")], ["src"], list(), True)
                    info["cross-correlate-operation"] = ExpressionInfo(_("Cross Correlate"), "xd.crosscorrelate({src1}, {src2})", "cross-correlate", [_("Source1"), _("Source2")], ["src1", "src2"], list(), True)
                    info["invert-operation"] = ExpressionInfo(_("Invert"), "xd.invert({src})", "invert", [_("Source")], ["src"], list(), True)
                    info["sobel-operation"] = ExpressionInfo(_("Sobel"), "xd.sobel({src})", "sobel", [_("Source")], ["src"], list(), True)
                    info["laplace-operation"] = ExpressionInfo(_("Laplace"), "xd.laplace({src})", "laplace", [_("Source")], ["src"], list(), True)
                    sigma_var = {'control_type': 'slider', 'label': _('Sigma'), 'name': 'sigma', 'type': 'variable', 'value': 3.0, 'value_default': 3.0, 'value_max': 100.0, 'value_min': 0.0, 'value_type': 'real'}
                    info["gaussian-blur-operation"] = ExpressionInfo(_("Gaussian Blur"), "xd.gaussian_blur({src}, sigma)", "gaussian-blur", [_("Source")], ["src"], [sigma_var], True)
                    filter_size_var = {'label': _("Size"), 'op_name': 'size', 'name': 'filter_size', 'type': 'variable', 'value': 3, 'value_default': 3, 'value_max': 100, 'value_min': 1, 'value_type': 'integral'}
                    info["median-filter-operation"] = ExpressionInfo(_("Median Filter"), "xd.median_filter({src}, filter_size)", "median-filter", [_("Source")], ["src"], [filter_size_var], True)
                    info["uniform-filter-operation"] = ExpressionInfo(_("Uniform Filter"), "xd.uniform_filter({src}, filter_size)", "uniform-filter", [_("Source")], ["src"], [filter_size_var], True)
                    do_transpose_var = {'label': _("Tranpose"), 'op_name': 'transpose', 'name': 'do_transpose', 'type': 'variable', 'value': False, 'value_default': False, 'value_type': 'boolean'}
                    do_flip_v_var = {'label': _("Flip Vertical"), 'op_name': 'flip_horizontal', 'name': 'do_flip_v', 'type': 'variable', 'value': False, 'value_default': False, 'value_type': 'boolean'}
                    do_flip_h_var = {'label': _("Flip Horizontal"), 'op_name': 'flip_vertical', 'name': 'do_flip_h', 'type': 'variable', 'value': False, 'value_default': False, 'value_type': 'boolean'}
                    info["transpose-flip-operation"] = ExpressionInfo(_("Transpose/Flip"), "xd.transpose_flip({src}, do_transpose, do_flip_v, do_flip_h)", "transpose-flip", [_("Source")], ["src"], [do_transpose_var, do_flip_v_var, do_flip_h_var], True)
                    info["crop-operation"] = ExpressionInfo(_("Crop"), "{src}", "crop", [_("Source")], ["src"], list(), False)
                    center_var = {'label': _("Center"), 'op_name': 'slice_center', 'name': 'center', 'type': 'variable', 'value': 0, 'value_default': 0, 'value_min': 0, 'value_type': 'integral'}
                    width_var = {'label': _("Width"), 'op_name': 'slice_width', 'name': 'width', 'type': 'variable', 'value': 1, 'value_default': 1, 'value_min': 1, 'value_type': 'integral'}
                    info["slice-operation"] = ExpressionInfo(_("Slice"), "xd.slice_sum({src}, center, width)", "slice", [_("Source")], ["src"], [center_var, width_var], False)
                    pt_var = {'label': _("Pick Point"), 'name': 'pick_region', 'type': 'variable', 'value_type': 'point'}
                    info["pick-operation"] = ExpressionInfo(_("Pick"), "xd.pick({src}, pick_region.position)", "pick-point", [_("Source")], ["src"], [pt_var], False)
                    info["projection-operation"] = ExpressionInfo(_("Sum"), "xd.sum({src}, src.xdata.datum_dimension_indexes[0])", "sum", [_("Source")], ["src"], list(), False)
                    width_var = {'label': _("Width"), 'name': 'width', 'type': 'variable', 'value': 256, 'value_default': 256, 'value_min': 1, 'value_type': 'integral'}
                    height_var = {'label': _("Height"), 'name': 'height', 'type': 'variable', 'value': 256, 'value_default': 256, 'value_min': 1, 'value_type': 'integral'}
                    info["resample-operation"] = ExpressionInfo(_("Reshape"), "xd.resample_image({src}, (height, width))", "resample", [_("Source")], ["src"], [width_var, height_var], True)
                    bins_var = {'label': _("Bins"), 'name': 'bins', 'type': 'variable', 'value': 256, 'value_default': 256, 'value_min': 2, 'value_type': 'integral'}
                    info["histogram-operation"] = ExpressionInfo(_("Histogram"), "xd.histogram({src}, bins)", "histogram", [_("Source")], ["src"], [bins_var], True)
                    line_var = {'label': _("Line Profile"), 'name': 'line_region', 'type': 'variable', 'value_type': 'line'}
                    info["line-profile-operation"] = ExpressionInfo(_("Line Profile"), "xd.line_profile({src}, line_region.vector, line_region.line_width)", "line-profile", [_("Source")], ["src"], [line_var], True)
                    info["convert-to-scalar-operation"] = ExpressionInfo(_("Scalar"), "{src}", "convert-to-scalar", [_("Source")], ["src"], list(), True)
                    # node-operation
                    for data_source_dict in data_source_dicts:
                        operation_dict = data_source_dict.get("data_source")
                        if operation_dict and operation_dict.get("type") == "operation":
                            del data_source_dict["data_source"]
                            operation_id = operation_dict["operation_id"]
                            computation_dict = dict()
                            if operation_id in info:
                                computation_dict["label"] = info[operation_id].label
                                computation_dict["processing_id"] = info[operation_id].processing_id
                                computation_dict["type"] = "computation"
                                computation_dict["uuid"] = str(uuid.uuid4())
                                variables_list = list()
                                data_sources = operation_dict.get("data_sources", list())
                                srcs = ("src", ) if len(data_sources) < 2 else ("src1", "src2")
                                kws = {}
                                for src in srcs:
                                    kws[src] = None
                                for i, src_data_source in enumerate(data_sources):
                                    kws[srcs[i]] = srcs[i] + (".display_data" if info[operation_id].use_display_data else ".data")
                                    if src_data_source.get("type") == "data-item-data-source":
                                        src_uuid = data_source_uuid_to_data_item_uuid.get(src_data_source["buffered_data_source_uuid"], str(uuid.uuid4()))
                                        variable_src = {"label": info[operation_id].src_labels[i], "name": info[operation_id].src_names[i], "type": "variable", "uuid": str(uuid.uuid4())}
                                        variable_src["specifier"] = {"type": "data_item", "uuid": src_uuid, "version": 1}
                                        variables_list.append(variable_src)
                                        if operation_id == "crop-operation":
                                            variable_src = {"label": _("Crop Region"), "name": "crop_region", "type": "variable", "uuid": str(uuid.uuid4())}
                                            variable_src["specifier"] = {"type": "region", "uuid": operation_dict["region_connections"]["crop"], "version": 1}
                                            variables_list.append(variable_src)
                                    elif src_data_source.get("type") == "operation":
                                        src_uuid = data_source_uuid_to_data_item_uuid.get(src_data_source["data_sources"][0]["buffered_data_source_uuid"], str(uuid.uuid4()))
                                        variable_src = {"label": info[operation_id].src_labels[i], "name": info[operation_id].src_names[i], "type": "variable", "uuid": str(uuid.uuid4())}
                                        variable_src["specifier"] = {"type": "data_item", "uuid": src_uuid, "version": 1}
                                        variables_list.append(variable_src)
                                        variable_src = {"label": _("Crop Region"), "name": "crop_region", "type": "variable", "uuid": str(uuid.uuid4())}
                                        variable_src["specifier"] = {"type": "region", "uuid": src_data_source["region_connections"]["crop"], "version": 1}
                                        variables_list.append(variable_src)
                                        kws[srcs[i]] = "xd.crop({}, crop_region.bounds)".format(kws[srcs[i]])
                                for rc_k, rc_v in operation_dict.get("region_connections", dict()).items():
                                    if rc_k == 'pick':
                                        variable_src = {"name": "pick_region", "type": "variable", "uuid": str(uuid.uuid4())}
                                        variable_src["specifier"] = {"type": "region", "uuid": rc_v, "version": 1}
                                        variables_list.append(variable_src)
                                    elif rc_k == 'line':
                                        variable_src = {"name": "line_region", "type": "variable", "uuid": str(uuid.uuid4())}
                                        variable_src["specifier"] = {"type": "region", "uuid": rc_v, "version": 1}
                                        variables_list.append(variable_src)
                                for var in copy.deepcopy(info[operation_id].variables):
                                    if var.get("value_type") not in ("line", "point"):
                                        var["uuid"] = str(uuid.uuid4())
                                        var_name = var.get("op_name") or var.get("name")
                                        var["value"] = operation_dict["values"].get(var_name, var.get("value"))
                                        variables_list.append(var)
                                computation_dict["variables"] = variables_list
                                computation_dict["original_expression"] = info[operation_id].expression.format(**kws)
                                data_source_dict["computation"] = computation_dict
                    properties["version"] = 9
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (operation to computation)", storage_handler.reference, properties["version"])
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

    def __migrate_to_v8(self, reader_info_list):
        for reader_info in reader_info_list:
            storage_handler = reader_info.storage_handler
            properties = reader_info.properties
            try:
                version = properties.get("version", 0)
                if version == 7:
                    reader_info.changed_ref[0] = True
                    # version 7 -> 8 changes metadata to be stored in buffered data source
                    data_source_dicts = properties.get("data_sources", list())
                    description_metadata = properties.setdefault("metadata", dict()).setdefault("description", dict())
                    data_source_dict = dict()
                    if len(data_source_dicts) == 1:
                        data_source_dict = data_source_dicts[0]
                        excluded = ["rating", "datetime_original", "title", "source_file_path", "session_id", "caption", "flag", "datetime_modified", "connections", "data_sources", "uuid", "reader_version",
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
                    timezone = datetime_original.get("timezone")
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
                    if timezone is not None:
                        time_zone_dict["timezone"] = timezone
                    properties.pop("datetime_original", None)
                    properties.pop("datetime_modified", None)
                    properties["version"] = 8
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (metadata to data source)", storage_handler.reference, properties["version"])
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

    def __migrate_to_v7(self, reader_info_list):
        v7lookup = dict()  # map data_item.uuid to buffered data source.uuid
        for reader_info in reader_info_list:
            storage_handler = reader_info.storage_handler
            properties = reader_info.properties
            try:
                version = properties.get("version", 0)
                if version == 6:
                    reader_info.changed_ref[0] = True
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
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (buffered data sources)", storage_handler.reference, properties["version"])
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

    def __migrate_to_v6(self, reader_info_list):
        for reader_info in reader_info_list:
            storage_handler = reader_info.storage_handler
            properties = reader_info.properties
            try:
                version = properties.get("version", 0)
                if version == 5:
                    reader_info.changed_ref[0] = True
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
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (operation hierarchy)", storage_handler.reference, properties["version"])
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

    def __migrate_to_v5(self, reader_info_list):
        for reader_info in reader_info_list:
            storage_handler = reader_info.storage_handler
            properties = reader_info.properties
            try:
                version = properties.get("version", 0)
                if version == 4:
                    reader_info.changed_ref[0] = True
                    # version 4 -> 5 changes region_uuid to region_connections map.
                    operations_list = properties.get("operations", list())
                    for operation_dict in operations_list:
                        if operation_dict["operation_id"] == "crop-operation" and "region_uuid" in operation_dict:
                            operation_dict["region_connections"] = {"crop": operation_dict["region_uuid"]}
                            del operation_dict["region_uuid"]
                        elif operation_dict["operation_id"] == "line-profile-operation" and "region_uuid" in operation_dict:
                            operation_dict["region_connections"] = {"line": operation_dict["region_uuid"]}
                            del operation_dict["region_uuid"]
                    properties["version"] = 5
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (region_uuid)", storage_handler.reference, properties["version"])
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

    def __migrate_to_v4(self, reader_info_list):
        for reader_info in reader_info_list:
            storage_handler = reader_info.storage_handler
            properties = reader_info.properties
            try:
                version = properties.get("version", 0)
                if version == 3:
                    reader_info.changed_ref[0] = True
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
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (calibration offset)", storage_handler.reference, properties["version"])
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

    def __migrate_to_v3(self, reader_info_list):
        for reader_info in reader_info_list:
            storage_handler = reader_info.storage_handler
            properties = reader_info.properties
            try:
                version = properties.get("version", 0)
                if version == 2:
                    reader_info.changed_ref[0] = True
                    # version 2 -> 3 adds uuid's to displays, graphics, and operations. regions already have uuids.
                    for display_properties in properties.get("displays", list()):
                        display_properties.setdefault("uuid", str(uuid.uuid4()))
                        for graphic_properties in display_properties.get("graphics", list()):
                            graphic_properties.setdefault("uuid", str(uuid.uuid4()))
                    for operation_properties in properties.get("operations", list()):
                        operation_properties.setdefault("uuid", str(uuid.uuid4()))
                    properties["version"] = 3
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (add uuids)", storage_handler.reference, properties["version"])
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

    def __migrate_to_v2(self, reader_info_list):
        for reader_info in reader_info_list:
            storage_handler = reader_info.storage_handler
            properties = reader_info.properties
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
                    temp_data = storage_handler.read_data()
                    if temp_data is not None:
                        properties["master_data_dtype"] = str(temp_data.dtype)
                        properties["master_data_shape"] = temp_data.shape
                    properties["displays"] = [{}]
                    properties["uuid"] = str(uuid.uuid4())  # assign a new uuid
                    properties["version"] = 2
                    if self.__log_migrations:
                        logging.info("Updated %s to %s (ndata1)", storage_handler.reference, properties["version"])
            except Exception as e:
                logging.debug("Error reading %s", storage_handler.reference)
                import traceback
                traceback.print_exc()
                traceback.print_stack()

    def _ensure_persistent_storage(self, data_item):
        persistent_storage = self._get_persistent_storage_for_object(data_item)
        if not persistent_storage:
            storage_handler = None
            for persistent_storage_system in self.__persistent_storage_systems:
                storage_handler = persistent_storage_system.make_storage_handler(data_item)
                if storage_handler:
                    break
            properties = data_item.write_to_dict()
            persistent_storage = DataItemStorage(storage_handler=storage_handler, data_item=data_item, properties=properties)
            self._set_persistent_storage_for_object(data_item, persistent_storage)
            data_item.persistent_object_context_changed()
        return persistent_storage

    def write_data_item(self, data_item):
        """ Write data item to persistent storage. """
        self._ensure_persistent_storage(data_item)
        # write the uuid and version explicitly
        self.property_changed(data_item, "uuid", str(data_item.uuid))
        self.property_changed(data_item, "version", DataItem.DataItem.writer_version)
        data_item._finish_write()

    def rewrite_data_item_properties(self, data_item):
        persistent_storage = self._get_persistent_storage_for_object(data_item)
        persistent_storage.update_properties()

    def rewrite_data_item_data(self, data_item, data: numpy.ndarray) -> None:
        persistent_storage = self._get_persistent_storage_for_object(data_item)
        persistent_storage.update_data(data)

    def erase_data_item(self, data_item):
        persistent_storage = self._get_persistent_storage_for_object(data_item)
        persistent_storage.remove()
        data_item.persistent_object_context = None

    def load_data(self, data_item):
        persistent_storage = self._get_persistent_storage_for_object(data_item)
        return persistent_storage.load_data()

    def _test_get_file_path(self, data_item):
        persistent_storage = self._get_persistent_storage_for_object(data_item)
        return persistent_storage._storage_handler.reference


class ComputationQueueItem:
    def __init__(self, data_item):
        self.data_item = data_item
        self.valid = True

    def recompute(self) -> typing.Sequence[typing.Callable[[], None]]:
        # evaluate the computation in a thread safe manner
        # returns a list of functions that must be called on the main thread to finish the recompute action
        # threadsafe
        pending_data_item_merges = list()
        data_item = self.data_item
        computation = data_item.computation
        if computation:
            try:
                api = PlugInManager.api_broker_fn("~1.0", None)
                data_item_clone = data_item.clone()
                data_item_data_modified = data_item.data_modified or datetime.datetime.min
                data_item_clone_recorder = Recorder.Recorder(data_item_clone)
                api_data_item = api._new_api_object(data_item_clone)
                error_text = computation.error_text
                if computation.needs_update:
                    error_text = computation.evaluate_with_target(api, api_data_item)
                    throttle_time = max(DocumentModel.computation_min_period - (time.perf_counter() - computation.last_evaluate_data_time), 0)
                    time.sleep(max(throttle_time, 0.0))
                if self.valid:  # TODO: race condition for 'valid'
                    def data_item_merge(data_item, data_item_clone, data_item_clone_recorder):
                        data_item_data_clone_modified = data_item_clone.data_modified or datetime.datetime.min
                        with data_item.data_item_changes(), data_item.data_source_changes():
                            if data_item_data_clone_modified > data_item_data_modified:
                                data_item.set_xdata(api_data_item.data_and_metadata)
                            data_item_clone_recorder.apply(data_item)
                            if computation.error_text != error_text:
                                computation.error_text = error_text
                    pending_data_item_merges.append(functools.partial(data_item_merge, data_item, data_item_clone, data_item_clone_recorder))
            except Exception as e:
                import traceback
                traceback.print_exc()
                # computation.error_text = _("Unable to compute data")
        return pending_data_item_merges


class AutoMigration:
    def __init__(self, paths: typing.List[str], log_copying: bool=True):
        self.paths = paths
        self.log_copying = log_copying


class DocumentModel(Observable.Observable, ReferenceCounting.ReferenceCounted, Persistence.PersistentObject, DataItem.SessionManager):

    """The document model manages storage and dependencies between data items and other objects.

    The document model provides a dispatcher object which will run tasks in a thread pool.
    """

    computation_min_period = 0.0

    def __init__(self, library_storage=None, persistent_storage_systems=None, storage_cache=None, log_migrations=True, ignore_older_files=False, auto_migrations=None):
        super(DocumentModel, self).__init__()

        self.data_item_deleted_event = Event.Event()  # will be called after the item is deleted
        self.data_item_will_be_removed_event = Event.Event()  # will be called before the item is deleted
        self.data_item_inserted_event = Event.Event()
        self.data_item_removed_event = Event.Event()

        self.dependency_added_event = Event.Event()
        self.dependency_removed_event = Event.Event()

        self.computation_updated_event = Event.Event()

        self.__thread_pool = ThreadPool.ThreadPool()
        self.__computation_thread_pool = ThreadPool.ThreadPool()
        self.persistent_object_context = PersistentDataItemContext(persistent_storage_systems, ignore_older_files, log_migrations)
        self.__library_storage = library_storage if library_storage else FilePersistentStorage()
        self.persistent_object_context._set_persistent_storage_for_object(self, self.__library_storage)
        self.storage_cache = storage_cache if storage_cache else Cache.DictStorageCache()
        self.__auto_migrations = auto_migrations or list()
        self.__transactions_lock = threading.RLock()
        self.__transactions = dict()
        self.__live_data_items_lock = threading.RLock()
        self.__live_data_items = dict()
        self.__dependency_tree_lock = threading.RLock()
        self.__dependency_tree_source_to_target_map = dict()
        self.__dependency_tree_target_to_source_map = dict()
        self.__data_items = list()
        self.__data_item_uuids = set()
        self.__uuid_to_data_item = dict()
        self.__computation_changed_listeners = dict()
        self.__data_item_references = dict()
        self.__recompute_lock = threading.RLock()
        self.__computation_queue_lock = threading.RLock()
        self.__computation_pending_queue = list()  # type: typing.List[ComputationQueueItem]
        self.__computation_active_items = list()  # type: typing.List[ComputationQueueItem]
        self.define_type("library")
        self.define_relationship("data_groups", DataGroup.data_group_factory)
        self.define_relationship("workspaces", WorkspaceLayout.factory)  # TODO: file format. Rename workspaces to workspace_layouts.
        self.define_property("session_metadata", dict(), copy_on_read=True, changed=self.__session_metadata_changed)
        self.define_property("workspace_uuid", converter=Converter.UuidToStringConverter())
        self.define_property("data_item_references", dict(), hidden=True)  # map string key to data item, used for data acquisition channels
        self.define_property("data_item_variables", dict(), hidden=True)  # map string key to data item, used for reference in scripts
        self.session_id = None
        self.start_new_session()
        self.__read()
        self.__library_storage.set_property(self, "uuid", str(self.uuid))
        self.__library_storage.set_property(self, "version", 0)

        self.__data_channel_updated_listeners = dict()
        self.__data_channel_start_listeners = dict()
        self.__data_channel_stop_listeners = dict()
        self.__data_channel_states_updated_listeners = dict()
        self.__last_data_items_dict = dict()  # maps hardware source to list of data items for that hardware source

        self.__hardware_source_call_soon_event_listeners = dict()

        self.__pending_data_item_updates_lock = threading.RLock()
        self.__pending_data_item_updates = list()

        self.__pending_data_item_merges_lock = threading.RLock()
        self.__pending_data_item_merges = list()

        self.call_soon_event = Event.Event()

        self.__hardware_source_added_event_listener = HardwareSource.HardwareSourceManager().hardware_source_added_event.listen(self.__hardware_source_added)
        self.__hardware_source_removed_event_listener = HardwareSource.HardwareSourceManager().hardware_source_removed_event.listen(self.__hardware_source_removed)

        for hardware_source in HardwareSource.HardwareSourceManager().hardware_sources:
            self.__hardware_source_added(hardware_source)

    def __read(self):
        # first read the items
        self.read_from_dict(self.__library_storage.properties)
        data_items = self.persistent_object_context.read_data_items()
        self.__finish_read_partial(data_items)
        for auto_migration in self.__auto_migrations:
            file_persistent_storage_system = FileStorageSystem(auto_migration.paths)
            persistent_object_context = PersistentDataItemContext([file_persistent_storage_system], ignore_older_files=False, log_migrations=False, log_copying=auto_migration.log_copying)
            data_items = persistent_object_context.read_data_items(target_document=self)
            self.__finish_read_partial(data_items)
        self.__finish_read()

    def __finish_read_partial(self, data_items: typing.List[DataItem.DataItem]) -> None:
        for index, data_item in enumerate(data_items):
            if data_item.uuid not in self.__data_item_uuids:  # an error, but don't crash
                data_item.about_to_be_inserted(self)
                self.__data_items.insert(index, data_item)
                self.__data_item_uuids.add(data_item.uuid)
                self.__uuid_to_data_item[data_item.uuid] = data_item
                data_item.set_storage_cache(self.storage_cache)
                data_item.set_session_manager(self)
        # all sorts of interconnections may occur between data items and other objects. give the data item a chance to
        # mark itself clean after reading all of them in.
        for data_item in data_items:
            data_item.finish_reading()

    def __finish_read(self) -> None:
        data_items = self.data_items
        for data_item in data_items:
            self.__computation_changed(data_item, None, data_item.computation)  # set up initial computation listeners
        for data_item in data_items:
            data_item.update_and_bind_computation(self)
            data_item.connect_data_items(data_items, self.get_data_item_by_uuid)
        # initialize data item references
        data_item_references_dict = self._get_persistent_property_value("data_item_references")
        for key, data_item_uuid in data_item_references_dict.items():
            data_item = self.get_data_item_by_uuid(uuid.UUID(data_item_uuid))
            if data_item:
                self.__data_item_references.setdefault(key, DocumentModel.DataItemReference(self, key, data_item))
        # all data items will already have a persistent_object_context
        for data_group in self.data_groups:
            data_group.connect_data_items(data_items, self.get_data_item_by_uuid)
        # handle the reference variable assignments
        data_item_variables = self._get_persistent_property_value("data_item_variables")
        new_data_item_variables = dict()
        for r_var, data_item_uuid_str in data_item_variables.items():
            data_item_uuid = uuid.UUID(data_item_uuid_str)
            if data_item_uuid in self.__data_item_uuids:
                new_data_item_variables[r_var] = data_item_uuid_str
                data_item = self.__uuid_to_data_item[data_item_uuid]
                data_item.set_r_value(r_var, notify_changed=False)
        self._set_persistent_property_value("data_item_variables", new_data_item_variables)

    def close(self):
        # stop computations
        with self.__computation_queue_lock:
            self.__computation_pending_queue.clear()
            for computation_queue_item in self.__computation_active_items:
                computation_queue_item.valid = False
            self.__computation_active_items.clear()

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
        for data_item in self.data_items:
            for data_item_reference in self.__data_item_references.values():
                data_item_reference.data_item_removed(data_item)

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

        self.__thread_pool.close()
        self.__computation_thread_pool.close()
        for data_item in self.data_items:
            data_item.about_to_be_removed()
            data_item.close()
        self.storage_cache.close()

    def __call_soon(self, fn):
        self.call_soon_event.fire_any(fn)

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
        self.notify_property_changed("session_metadata")

    def has_session_field(self, field_id: str) -> bool:
        return field_id in self.session_metadata

    def set_session_field(self, field_id: str, value: str) -> None:
        session_metadata = self.session_metadata
        session_metadata[field_id] = str(value)
        self.session_metadata = session_metadata

    def get_session_field(self, field_id: str) -> str:
        return self.session_metadata.get(field_id)

    def delete_session_field(self, field_id: str) -> None:
        session_metadata = self.session_metadata
        session_metadata.pop(field_id, None)
        self.session_metadata = session_metadata

    @property
    def current_session_id(self):
        return self.session_id

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
        assert data_item.uuid not in self.__data_item_uuids
        # insert in internal list
        data_item.about_to_be_inserted(self)
        self.__data_items.insert(before_index, data_item)
        self.__data_item_uuids.add(data_item.uuid)
        self.__uuid_to_data_item[data_item.uuid] = data_item
        data_item.set_storage_cache(self.storage_cache)
        data_item.persistent_object_context = self.persistent_object_context
        data_item.persistent_object_context._ensure_persistent_storage(data_item)
        data_item.session_id = self.session_id
        persistent_storage = data_item.persistent_object_context._get_persistent_storage_for_object(data_item)
        if persistent_storage and not persistent_storage.write_delayed:
            # don't directly write data item, or else write_pending is not cleared on data item
            # self.persistent_object_context.write_data_item(data_item)
            # call finish pending write instead
            data_item._finish_pending_write()  # initially write to disk
        self.__computation_changed(data_item, None, data_item.computation)  # set up initial computation listeners
        data_item.set_session_manager(self)
        self.data_item_inserted_event.fire(self, data_item, before_index, False)
        for data_item_reference in self.__data_item_references.values():
            data_item_reference.data_item_inserted(data_item)
        data_item.data_item_was_inserted(self)

    def remove_data_item(self, data_item):
        """Remove data item from document model.

        Data item will have persistent_object_context cleared upon return.

        This method is NOT threadsafe.
        """
        # remove data item from any computations
        self.__cascade_delete(data_item)

    def __remove_data_item(self, data_item):
        assert data_item.uuid in self.__data_item_uuids
        with self.__computation_queue_lock:
            for computation_queue_item in self.__computation_pending_queue + self.__computation_active_items:
                if computation_queue_item.data_item is data_item:
                    computation_queue_item.valid = False
        # remove data item from any selections
        self.data_item_will_be_removed_event.fire(data_item)
        # remove the data item from any groups
        for data_group in self.get_flat_data_group_generator():
            if data_item in data_group.data_items:
                data_group.remove_data_item(data_item)
        # tell the data item it is about to be removed
        data_item.about_to_be_removed()
        # remove it from the persistent_storage
        assert data_item is not None
        assert data_item in self.__data_items
        index = self.__data_items.index(data_item)
        # do actual removal
        del self.__data_items[index]
        self.__data_item_uuids.remove(data_item.uuid)
        del self.__uuid_to_data_item[data_item.uuid]
        if data_item.r_var:
            data_item_variables = self._get_persistent_property_value("data_item_variables")
            del data_item_variables[data_item.r_var]
            self._set_persistent_property_value("data_item_variables", data_item_variables)
            data_item.r_var = None
        # keep storage up-to-date
        self.persistent_object_context.erase_data_item(data_item)
        data_item.__storage_cache = None
        computation = data_item.computation
        if computation:
            self.__computation_changed(data_item, computation, None)
        # update data item count
        for data_item_reference in self.__data_item_references.values():
            data_item_reference.data_item_removed(data_item)
        self.data_item_removed_event.fire(self, data_item, index, False)
        data_item.close()  # make sure dependents get updated. argh.
        self.data_item_deleted_event.fire(data_item)

    def insert_model_item(self, container, name, before_index, item):
        container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item):
        self.__cascade_delete(item)

    def assign_variable_to_data_item(self, data_item: DataItem.DataItem) -> str:
        if not data_item.r_var:
            data_item_variables = self._get_persistent_property_value("data_item_variables")
            def find_var() -> str:
                for r in range(1, 1000000):
                    r_var = "r{:02d}".format(r)
                    if not r_var in data_item_variables:
                        return r_var
                return str()
            data_item_var = find_var()
            data_item_variables[data_item_var] = str(data_item.uuid)
            data_item.set_r_value(data_item_var)
            self._set_persistent_property_value("data_item_variables", data_item_variables)
        return data_item.r_var

    def variable_to_data_item_map(self) -> typing.Mapping[str, DataItem.DataItem]:
        m = dict()
        data_item_variables = self._get_persistent_property_value("data_item_variables")
        for variable, data_item_uuid_str in data_item_variables.items():
            m[variable] = self.__uuid_to_data_item[uuid.UUID(data_item_uuid_str)]
        return m

    def __build_cascade(self, item, items: list, dependencies: list) -> None:
        # build a list of items to delete, with the leafs at the end of the list.
        # print(f"build {item}")
        if item not in items:
            # first handle the case where a data item that is the only target of a graphic cascades to the graphic.
            # this is the only case where a target causes a source to be deleted.
            items.append(item)
            if isinstance(item, DataItem.DataItem):
                sources = self.__dependency_tree_target_to_source_map.get(weakref.ref(item), list())
                for source in sources:
                    if isinstance(source, Graphics.Graphic):
                        source_targets = self.__dependency_tree_source_to_target_map.get(weakref.ref(source), list())
                        if len(source_targets) == 1 and source_targets[0] == item:
                            self.__build_cascade(source, items, dependencies)
                for display in item.displays:
                    for graphic in display.graphics:
                        self.__build_cascade(graphic, items, dependencies)
            targets = self.__dependency_tree_source_to_target_map.get(weakref.ref(item), list())
            for target in targets:
                assert isinstance(target, DataItem.DataItem)
                dependencies.append((item, target))
                self.__build_cascade(target, items, dependencies)

    def __cascade_delete(self, item):
        # print(f"cascade {item}")
        items = list()
        dependencies = list()
        self.__build_cascade(item, items, dependencies)
        # print(list(reversed(items)))
        for source, target in reversed(dependencies):
            self.__remove_dependency(source, target)
        for item in reversed(items):
            container = item.container
            name = "data_items" if isinstance(item, DataItem.DataItem) else "graphics"
            # print(container, name, item)
            if container is self:
                # call the version of __remove_data_item that doesn't cascade again
                self.__remove_data_item(item)
            else:
                container.remove_item(name, item)

    def __remove_dependency(self, source_item, target_item):
        # print(f"remove dependency {source_item} {target_item}")
        with self.__dependency_tree_lock:
            self.__dependency_tree_source_to_target_map.setdefault(weakref.ref(source_item), list()).remove(target_item)
            self.__dependency_tree_target_to_source_map.setdefault(weakref.ref(target_item), list()).remove(source_item)
        if isinstance(source_item, DataItem.DataItem) and isinstance(target_item, DataItem.DataItem):
            # propagate transaction and live states to dependents
            if source_item.in_transaction_state:
                self.end_data_item_transaction(target_item)
            if source_item.is_live:
                self.end_data_item_live(target_item)
        self.dependency_removed_event.fire(source_item, target_item)

    def __add_dependency(self, source_item, target_item):
        # print(f"add dependency {source_item} {target_item}")
        with self.__dependency_tree_lock:
            self.__dependency_tree_source_to_target_map.setdefault(weakref.ref(source_item), list()).append(target_item)
            self.__dependency_tree_target_to_source_map.setdefault(weakref.ref(target_item), list()).append(source_item)
        if isinstance(source_item, DataItem.DataItem) and isinstance(target_item, DataItem.DataItem):
            # propagate transaction and live states to dependents
            if source_item.in_transaction_state:
                self.begin_data_item_transaction(target_item)
            if source_item.is_live:
                self.begin_data_item_live(target_item)
        self.dependency_added_event.fire(source_item, target_item)

    def __computation_needs_update(self, data_item):
        with self.__computation_queue_lock:
            for computation_queue_item in self.__computation_pending_queue:
                if computation_queue_item.data_item == data_item:
                    return
            computation_queue_item = ComputationQueueItem(data_item)
            self.__computation_pending_queue.append(computation_queue_item)
        self.dispatch_task2(self.__recompute)

    def __handle_computation_changed_or_mutated(self, data_item: DataItem.DataItem, computation) -> None:
        """Establish the dependencies between data items based on the computation."""

        new_source_items = set()
        if computation:
            for variable in computation.variables:
                specifier = variable.specifier
                if specifier:
                    object = self.resolve_object_specifier(variable.specifier, variable.secondary_specifier)
                    if hasattr(object, "value"):
                        source_item = object.value
                        if isinstance(source_item, DataItem.DataSource):
                            new_source_items.add(source_item.data_item)
                            if source_item.graphic:
                                new_source_items.add(source_item.graphic)
                        else:
                            new_source_items.add(source_item)

        with self.__dependency_tree_lock:
            old_source_items = set(self.__dependency_tree_target_to_source_map.setdefault(weakref.ref(data_item), list()))
            # add the items in new set that aren't in the old set
            for source_item in (new_source_items - old_source_items):
                self.__add_dependency(source_item, data_item)
            # remove the items in the old set that aren't in the new set
            for source_item in (old_source_items - new_source_items):
                self.__remove_dependency(source_item, data_item)

        if data_item.computation:
            self.__computation_needs_update(data_item)

    def rebind_computations(self):
        """Call this to rebind all computations.

        This is helpful when extending the computation type system.
        After new objcts have been loaded, call this so that existing
        computations can find the new objects during startup.
        """
        for data_item in self.data_items:
            data_item.rebind_computations(self)

    @property
    def data_items(self):
        return tuple(self.__data_items)  # tuple makes it read only

    # transactions, live state, and dependencies

    def get_source_data_items(self, data_item: DataItem.DataItem) -> typing.List[DataItem.DataItem]:
        with self.__dependency_tree_lock:
            return [data_item for data_item in self.__dependency_tree_target_to_source_map.get(weakref.ref(data_item), list()) if isinstance(data_item, DataItem.DataItem)]

    def get_dependent_data_items(self, data_item: DataItem.DataItem) -> typing.List[DataItem.DataItem]:
        """Return the list of data items containing data that directly depends on data in this item."""
        with self.__dependency_tree_lock:
            return [data_item for data_item in self.__dependency_tree_source_to_target_map.get(weakref.ref(data_item), list()) if isinstance(data_item, DataItem.DataItem)]

    def data_item_transaction(self, data_item):
        """ Return a context manager to put the data item under a 'transaction'. """
        class TransactionContextManager:
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
                data_items = handler.read_data_items(None, "ndata1", sample_path)
                for data_item in data_items:
                    if not self.get_data_item_by_uuid(data_item.uuid):
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

    def safe_insert_data_item(self, data_group, data_item, index_ref, logging=True):
        if data_group and isinstance(data_group, DataGroup.DataGroup):
            if not data_item.uuid in self.__data_item_uuids:
                self.append_data_item(data_item)
            if index_ref[0] >= 0:
                data_group.insert_data_item(index_ref[0], data_item)
                index_ref[0] += 1
            else:
                data_group.append_data_item(data_item)
        elif not data_item.uuid in self.__data_item_uuids:
            if index_ref[0] >= 0:
                self.insert_data_item(index_ref[0], data_item)
                index_ref[0] += 1
            else:
                self.append_data_item(data_item)

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
        return self.__uuid_to_data_item.get(uuid)

    def get_or_create_data_group(self, group_name):
        data_group = DataGroup.get_data_group_in_container_by_title(self, group_name)
        if data_group is None:
            # we create a new group
            data_group = DataGroup.DataGroup()
            data_group.title = group_name
            self.insert_data_group(0, data_group)
        return data_group

    def create_computation(self, expression: str=None) -> Symbolic.Computation:
        computation = Symbolic.Computation(expression)
        computation.bind(self)
        return computation

    def dispatch_task(self, task, description=None):
        self.__thread_pool.queue_fn(task, description)

    def dispatch_task2(self, task, description=None):
        self.__computation_thread_pool.queue_fn(task, description)

    def recompute_all(self, merge=True):
        self.__computation_thread_pool.run_all()
        if merge:
            self.perform_data_item_merges()

    def recompute_one(self, merge=True):
        self.__computation_thread_pool.run_one()
        if merge:
            self.perform_data_item_merges()

    def start_dispatcher(self):
        self.__thread_pool.start()
        self.__computation_thread_pool.start(1)

    def __recompute(self):
        computation_queue_item = None
        skipped_pending = False
        with self.__computation_queue_lock:
            # loop through the items in the pending queue
            for i, _computation_queue_item in enumerate(self.__computation_pending_queue):
                # first check to see if the item in the pending queue matches an item in the active list
                match = None
                for active_computation_item in self.__computation_active_items:
                    if _computation_queue_item.data_item == active_computation_item.data_item:
                        match = _computation_queue_item
                        break
                # if it doesn't match, move it to active, and break out of this loop
                # other items in the queue will be serviced by future calls to __recompute.
                # there is one __recompute for each item put into the pending queue.
                if not match:
                    computation_queue_item = self.__computation_pending_queue.pop(i)
                    self.__computation_active_items.append(computation_queue_item)
                    break
                # otherwise, mark it as skipped so that __recompute is called again.
                # so that it eventually gets serviced.
                else:
                    skipped_pending = True

        if computation_queue_item:
            # an item was put into the active queue, so compute it, then merge
            pending_data_item_merges = computation_queue_item.recompute()
            with self.__pending_data_item_merges_lock:
                self.__pending_data_item_merges.extend(pending_data_item_merges)
            self.__call_soon(self.perform_data_item_merges)
            # it is now merged, so remove it from the active queue
            with self.__computation_queue_lock:
                self.__computation_active_items.remove(computation_queue_item)

        if skipped_pending:
            self.dispatch_task2(self.__recompute)

    def perform_data_item_merges(self):
        with self.__pending_data_item_merges_lock:
            pending_data_item_merges = self.__pending_data_item_merges
            self.__pending_data_item_merges = list()
        for pending_data_item_merge in pending_data_item_merges:
            pending_data_item_merge()

    async def recompute_immediate(self, event_loop: asyncio.AbstractEventLoop, data_item: DataItem.DataItem) -> None:
        computation = data_item.computation
        if computation:
            def sync_recompute():
                with self.__recompute_lock:
                    pass
            await event_loop.run_in_executor(None, sync_recompute)
            self.perform_data_item_merges()

    def get_object_specifier(self, object):
        if isinstance(object, DataItem.DataItem):
            return {"version": 1, "type": "data_item", "uuid": str(object.uuid)}
        elif isinstance(object, Graphics.Graphic):
            return {"version": 1, "type": "region", "uuid": str(object.uuid)}
        return Symbolic.ComputationVariable.get_extension_object_specifier(object)

    def get_graphic_by_uuid(self, object_uuid: uuid.UUID) -> typing.Optional[Graphics.Graphic]:
        for data_item in self.data_items:
            for display in data_item.displays:
                for graphic in display.graphics:
                    if graphic.uuid == object_uuid:
                        return graphic
        return None

    def resolve_object_specifier(self, specifier: dict, secondary_specifier: dict=None):
        document_model = self
        if specifier.get("version") == 1:
            specifier_type = specifier["type"]
            if specifier_type == "data_item":
                specifier_uuid_str = specifier.get("uuid")
                secondary_uuid_str = secondary_specifier.get("uuid") if secondary_specifier else None
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                secondary_uuid = uuid.UUID(secondary_uuid_str) if secondary_uuid_str else None
                data_item = self.get_data_item_by_uuid(object_uuid) if object_uuid else None
                graphic = self.get_graphic_by_uuid(secondary_uuid) if secondary_uuid else None
                class BoundDataSource:
                    def __init__(self, data_item, graphic):
                        self.changed_event = Event.Event()
                        self.__data_source = DataItem.DataSource(data_item, graphic, self.changed_event)
                    @property
                    def value(self):
                        return self.__data_source
                    def close(self):
                        self.__data_source.close()
                        self.__data_source = None
                if data_item:
                    return BoundDataSource(data_item, graphic)
            elif specifier_type == "region":
                specifier_uuid_str = specifier.get("uuid")
                object_uuid = uuid.UUID(specifier_uuid_str) if specifier_uuid_str else None
                graphic = self.get_graphic_by_uuid(object_uuid)
                if graphic:
                    class BoundGraphic:
                        def __init__(self, object):
                            self.__object = object
                            self.changed_event = Event.Event()
                            def property_changed(property_name_being_changed):
                                self.changed_event.fire()
                            self.__property_changed_listener = self.__object.property_changed_event.listen(property_changed)
                        def close(self):
                            self.__property_changed_listener.close()
                            self.__property_changed_listener = None
                        @property
                        def value(self):
                            return self.__object
                    return BoundGraphic(graphic)
        return Symbolic.ComputationVariable.resolve_extension_object_specifier(specifier)

    class DataItemReference:
        """A data item reference to coordinate data item access between acquisition and main thread.

        Call start/stop a matching number of times to start/stop using the data reference (from the
        acquisition thread).

        Set data_item property when it is created (from the UI thread).

        This class will also track when the data item is deleted and handle it appropriately if it
        happens while the acquisition thread is using it.
        """
        def __init__(self, document_model: "DocumentModel", key: str, data_item: DataItem.DataItem=None):
            self.__document_model = document_model
            self.__key = key
            self.__data_item = data_item
            self.__starts = 0
            self.__pending_starts = 0
            self.mutex = threading.RLock()
            self.data_item_changed_event = Event.Event()

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
            self.__document_model.begin_data_item_transaction(self.__data_item)
            self.__document_model.begin_data_item_live(self.__data_item)
            self.__starts += 1

        def __stop(self):
            # the order of these two statements is important, at least for now (12/2013)
            # when the transaction ends, the data will get written to disk, so we need to
            # make sure it's still in memory. if decrement were to come before the end
            # of the transaction, the data would be unloaded from memory, losing it forever.
            self.__document_model.end_data_item_transaction(self.__data_item)
            self.__document_model.end_data_item_live(self.__data_item)
            self.__data_item.decrement_data_ref_count()
            self.__starts -= 1

        # this method gets called directly from the document model
        def data_item_inserted(self, data_item):
            pass

        # this method gets called directly from the document model
        def data_item_removed(self, data_item):
            with self.mutex:
                if data_item == self.__data_item:
                    # when this data item is removed, it can no longer be used.
                    # but to ensure that start/stop calls are matching in the case where this item
                    # is removed and then a new item is set, we need to copy the number of starts
                    # to the pending starts so when the new item is set, start gets called the right
                    # number of times to match the stops that will eventually be called.
                    self.__pending_starts = self.__starts
                    self.__starts = 0
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
                    # start (internal) for each pending start.
                    for i in range(self.__pending_starts):
                        self.__start()
                    self.__pending_starts = 0
                    self.data_item_changed_event.fire()

    def __queue_data_item_update(self, data_item, data_and_metadata):
        # put the data update to data_item into the pending_data_item_updates list.
        # the pending_data_item_updates will be serviced when the main thread calls
        # perform_data_item_updates.
        if data_item:
            with self.__pending_data_item_updates_lock:
                found = False
                pending_data_item_updates = list()
                for data_item_, data_and_metadata_ in self.__pending_data_item_updates:
                    # does it match? if so and not yet found, put the new data into the matching
                    # slot; but then filter the rest of the matches.
                    if data_item_ == data_item:
                        if not found:
                            pending_data_item_updates.append((data_item, data_and_metadata))
                            found = True
                    else:
                        pending_data_item_updates.append((data_item_, data_and_metadata_))
                if not found:  # if not added yet, add it
                    pending_data_item_updates.append((data_item, data_and_metadata))
                self.__pending_data_item_updates = pending_data_item_updates

    def perform_data_item_updates(self):
        assert threading.current_thread() == threading.main_thread()
        with self.__pending_data_item_updates_lock:
            pending_data_item_updates = self.__pending_data_item_updates
            self.__pending_data_item_updates = list()
        for data_item, data_and_metadata in pending_data_item_updates:
            data_item.update_data_and_metadata(data_and_metadata)

    # for testing
    def _get_pending_data_item_updates_count(self):
        return len(self.__pending_data_item_updates)

    def _update_data_item_reference(self, key: str, data_item: DataItem.DataItem) -> None:
        assert threading.current_thread() == threading.main_thread()
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

    def setup_channel(self, data_item_reference_key: str, data_item: DataItem.DataItem) -> None:
        data_item_reference = self.get_data_item_reference(data_item_reference_key)
        data_item_reference.data_item = data_item

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

                def append_data_item():
                    self.append_data_item(data_item)
                    self._update_data_item_reference(key, data_item)

                self.__call_soon(append_data_item)

            def update_session():
                # update the session, but only if necessary (this is an optimization to prevent unnecessary display updates)
                if data_item.session_id != session_id:
                    data_item.session_id = session_id
                session_metadata = self.session_metadata
                if data_item.session_metadata != session_metadata:
                    data_item.session_metadata = session_metadata
                if data_channel.processor:
                    src_data_channel = hardware_source.data_channels[data_channel.src_channel_index]
                    src_data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, src_data_channel.channel_id))
                    data_channel.processor.connect(src_data_item_reference)

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
            data_item_reference = self.get_data_item_reference(self.make_data_item_reference_key(hardware_source.hardware_source_id, data_channel.channel_id))
            data_item = data_item_reference.data_item
            if data_item:
                hardware_source.clean_data_item(data_item, data_channel)

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

    def get_snapshot_new(self, data_item: DataItem.DataItem) -> DataItem.DataItem:
        assert isinstance(data_item, DataItem.DataItem)
        data_item_copy = data_item.snapshot()
        data_item_copy.title = _("Snapshot of ") + data_item.title
        self.append_data_item(data_item_copy)
        return data_item_copy

    def set_data_item_computation(self, data_item: DataItem.DataItem, computation: Symbolic.Computation) -> None:
        if data_item:
            old_computation = data_item.computation
            data_item.set_computation(computation)
            self.__computation_changed(data_item, old_computation, computation)

    def __computation_changed(self, data_item, old_computation, new_computation):
        def computation_mutated():
            self.__handle_computation_changed_or_mutated(data_item, new_computation)
            self.computation_updated_event.fire(data_item, new_computation)
        if old_computation:
            computation_changed_listener = self.__computation_changed_listeners.pop(data_item, None)
            if computation_changed_listener: computation_changed_listener.close()
        if new_computation:
            self.__computation_changed_listeners[data_item] = new_computation.computation_mutated_event.listen(computation_mutated)
        computation_mutated()

    def make_data_item_with_computation(self, processing_id: str, inputs: typing.List[typing.Tuple[DataItem.DataItem, Graphics.Graphic]], region_list_map: typing.Mapping[str, typing.List[Graphics.Graphic]]=None) -> DataItem.DataItem:
        return self.__make_computation(processing_id, inputs, region_list_map)

    def __make_computation(self, processing_id: str, inputs: typing.List[typing.Tuple[DataItem.DataItem, Graphics.Graphic]], region_list_map: typing.Mapping[str, typing.List[Graphics.Graphic]]=None) -> DataItem.DataItem:
        """Create a new data item with computation specified by processing_id, inputs, and region_list_map.

        The region_list_map associates a list of graphics corresponding to the required regions with a computation source (key).
        """
        region_list_map = region_list_map or dict()

        processing_descriptions = self._processing_descriptions
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

            display_specifier = DataItem.DisplaySpecifier.from_data_item(input[0])
            data_item = display_specifier.data_item
            display = display_specifier.display

            if not data_item:
                return None

            # each source can have a list of requirements, check through them
            requirements = src_dict.get("requirements", list())
            for requirement in requirements:
                requirement_type = requirement["type"]
                if requirement_type == "dimensionality":
                    min_dimension = requirement.get("min")
                    max_dimension = requirement.get("max")
                    dimensionality = len(data_item.dimensional_shape)
                    if min_dimension is not None and dimensionality < min_dimension:
                        return None
                    if max_dimension is not None and dimensionality > max_dimension:
                        return None

            suffix = i if len(src_dicts) > 1 else ""
            src_name = src_dict["name"]
            src_label = src_dict["label"]
            use_display_data = src_dict.get("use_display_data", True)
            xdata_property = "display_xdata" if use_display_data else "xdata"
            if src_dict.get("croppable"):
                xdata_property = "cropped_" + xdata_property
            elif src_dict.get("use_filtered_data", False):
                xdata_property = "filtered_" + xdata_property
            src_text = "{}.{}".format(src_name, xdata_property)
            src_names.append(src_name)
            src_texts.append(src_text)
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
                        if display:
                            display.add_graphic(point_region)
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
                        if display:
                            display.add_graphic(line_region)
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
                        if display:
                            display.add_graphic(rect_region)
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
                        if display:
                            display.add_graphic(ellipse_region)
                    regions.append((region_name, ellipse_region, region_params.get("label")))
                    region_map[region_name] = ellipse_region
                elif region_type == "spot":
                    if region:
                        assert isinstance(region, Graphics.SpotGraphic)
                        spot_region = region
                    else:
                        spot_region = Graphics.SpotGraphic()
                        spot_region.center = 0.25, 0.75
                        spot_region.size = 0.1, 0.1
                        for k, v in region_params.items():
                            setattr(spot_region, k, v)
                        if display:
                            display.add_graphic(spot_region)
                    regions.append((region_name, spot_region, region_params.get("label")))
                    region_map[region_name] = spot_region
                elif region_type == "interval":
                    if region:
                        assert isinstance(region, Graphics.IntervalGraphic)
                        interval_region = region
                    else:
                        interval_region = Graphics.IntervalGraphic()
                        for k, v in region_params.items():
                            setattr(interval_region, k, v)
                        if display:
                            display.add_graphic(interval_region)
                    regions.append((region_name, interval_region, region_params.get("label")))
                    region_map[region_name] = interval_region
                elif region_type == "channel":
                    if region:
                        assert isinstance(region, Graphics.ChannelGraphic)
                        channel_region = region
                    else:
                        channel_region = Graphics.ChannelGraphic()
                        for k, v in region_params.items():
                            setattr(channel_region, k, v)
                        if display:
                            display.add_graphic(channel_region)
                    regions.append((region_name, channel_region, region_params.get("label")))
                    region_map[region_name] = channel_region

        # now extract the script (full script) or expression (implied imports and return statement)
        script = processing_description.get("script")
        if not script:
            expression = processing_description.get("expression")
            if expression:
                script = Symbolic.xdata_expression(expression)
        assert script

        # construct the computation
        script = script.format(**dict(zip(src_names, src_texts)))
        computation = self.create_computation(script)
        computation.label = processing_description["title"]
        computation.processing_id = processing_id
        # process the data item inputs
        for src_dict, src_name, src_label, input in zip(src_dicts, src_names, src_labels, inputs):
            display_specifier = DataItem.DisplaySpecifier.from_data_item(input[0])
            secondary_specifier = None
            if src_dict.get("croppable", False):
                secondary_specifier = self.get_object_specifier(input[1])
            computation.create_object(src_name, self.get_object_specifier(display_specifier.data_item), label=src_label, secondary_specifier=secondary_specifier)
        # process the regions
        for region_name, region, region_label in regions:
            computation.create_object(region_name, self.get_object_specifier(region), label=region_label)
        # next process the parameters
        for param_dict in processing_description.get("parameters", list()):
            computation.create_variable(param_dict["name"], param_dict["type"], param_dict["value"], value_default=param_dict.get("value_default"),
                                        value_min=param_dict.get("value_min"), value_max=param_dict.get("value_max"),
                                        control_type=param_dict.get("control_type"), label=param_dict["label"])

        data_item0 = inputs[0][0]
        new_data_item = DataItem.new_data_item()
        prefix = "{} of ".format(processing_description["title"])
        new_data_item.title = prefix + data_item0.title
        new_data_item.category = data_item0.category

        self.append_data_item(new_data_item)

        display_specifier = DataItem.DisplaySpecifier.from_data_item(new_data_item)
        display = display_specifier.display

        # next come the output regions that get created on the target itself
        new_regions = dict()
        for out_region_dict in processing_description.get("out_regions", list()):
            region_type = out_region_dict["type"]
            region_name = out_region_dict["name"]
            region_params = out_region_dict.get("params", dict())
            if region_type == "interval":
                interval_region = Graphics.IntervalGraphic()
                for k, v in region_params.items():
                    setattr(interval_region, k, v)
                display.add_graphic(interval_region)
                new_regions[region_name] = interval_region

        # now come the connections between the source and target
        for connection_dict in processing_description.get("connections", list()):
            connection_type = connection_dict["type"]
            connection_src = connection_dict["src"]
            connection_src_prop = connection_dict.get("src_prop")
            connection_dst = connection_dict["dst"]
            connection_dst_prop = connection_dict.get("dst_prop")
            if connection_type == "property":
                if connection_src == "display":
                    # TODO: how to refer to the data_items? hardcode to data_item0 for now.
                    new_data_item.add_connection(Connection.PropertyConnection(data_item0.displays[0], connection_src_prop, new_regions[connection_dst], connection_dst_prop))
            elif connection_type == "interval_list":
                new_data_item.add_connection(Connection.IntervalListConnection(display, region_map[connection_dst]))

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

    _processing_descriptions = dict()
    _builtin_processing_descriptions = None

    @classmethod
    def register_processing_descriptions(cls, processing_descriptions: typing.Dict) -> None:
        assert len(set(cls._processing_descriptions.keys()).intersection(set(processing_descriptions.keys()))) == 0
        cls._processing_descriptions.update(processing_descriptions)

    @classmethod
    def unregister_processing_descriptions(cls, processing_ids: typing.Sequence[str]):
        assert len(set(cls.__get_builtin_processing_descriptions().keys()).intersection(set(processing_ids))) == len(processing_ids)
        for processing_id in processing_ids:
            cls._processing_descriptions.pop(processing_id)

    @classmethod
    def _get_builtin_processing_descriptions(cls) -> typing.Dict:
        if not cls._builtin_processing_descriptions:
            vs = dict()
            vs["fft"] = {"title": _("FFT"), "expression": "xd.fft({src})", "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["inverse-fft"] = {"title": _("Inverse FFT"), "expression": "xd.ifft({src})",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False}]}
            vs["auto-correlate"] = {"title": _("Auto Correlate"), "expression": "xd.autocorrelate({src})",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["cross-correlate"] = {"title": _("Cross Correlate"), "expression": "xd.crosscorrelate({src1}, {src2})",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["sobel"] = {"title": _("Sobel"), "expression": "xd.sobel({src})",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["laplace"] = {"title": _("Laplace"), "expression": "xd.laplace({src})",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            sigma_param = {"name": "sigma", "label": _("Sigma"), "type": "real", "value": 3, "value_default": 3, "value_min": 0, "value_max": 100,
                "control_type": "slider"}
            vs["gaussian-blur"] = {"title": _("Gaussian Blur"), "expression": "xd.gaussian_blur({src}, sigma)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [sigma_param]}
            filter_size_param = {"name": "filter_size", "label": _("Size"), "type": "integral", "value": 3, "value_default": 3, "value_min": 1, "value_max": 100}
            vs["median-filter"] = {"title": _("Median Filter"), "expression": "xd.median_filter({src}, filter_size)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [filter_size_param]}
            vs["uniform-filter"] = {"title": _("Uniform Filter"), "expression": "xd.uniform_filter({src}, filter_size)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [filter_size_param]}
            do_transpose_param = {"name": "do_transpose", "label": _("Transpose"), "type": "boolean", "value": False, "value_default": False}
            do_flip_v_param = {"name": "do_flip_v", "label": _("Flip Vertical"), "type": "boolean", "value": False, "value_default": False}
            do_flip_h_param = {"name": "do_flip_h", "label": _("Flip Horizontal"), "type": "boolean", "value": False, "value_default": False}
            vs["transpose-flip"] = {"title": _("Transpose/Flip"), "expression": "xd.transpose_flip({src}, do_transpose, do_flip_v, do_flip_h)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [do_transpose_param, do_flip_v_param, do_flip_h_param]}
            width_param = {"name": "width", "label": _("Width"), "type": "integral", "value": 256, "value_default": 256, "value_min": 1}
            height_param = {"name": "height", "label": _("Height"), "type": "integral", "value": 256, "value_default": 256, "value_min": 1}
            vs["resample"] = {"title": _("Resample"), "expression": "xd.resample_image({src}, (height, width))",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [width_param, height_param]}
            vs["resize"] = {"title": _("Resize"), "expression": "xd.resize({src}, (height, width), 'mean')",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [width_param, height_param]}
            bins_param = {"name": "bins", "label": _("Bins"), "type": "integral", "value": 256, "value_default": 256, "value_min": 2}
            vs["histogram"] = {"title": _("Histogram"), "expression": "xd.histogram({src}, bins)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}], "parameters": [bins_param]}
            vs["add"] = {"title": _("Add"), "expression": "{src1} + {src2}",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["subtract"] = {"title": _("Add"), "expression": "{src1} - {src2}",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["multiply"] = {"title": _("Add"), "expression": "{src1} * {src2}",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["divide"] = {"title": _("Add"), "expression": "{src1} / {src2}",
                "sources": [{"name": "src1", "label": _("Source 1"), "croppable": True}, {"name": "src2", "label": _("Source 2"), "croppable": True}]}
            vs["invert"] = {"title": _("Negate"), "expression": "xd.invert({src})", "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["convert-to-scalar"] = {"title": _("Scalar"), "expression": "{src}",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            requirement_2d = {"type": "dimensionality", "min": 2, "max": 2}
            requirement_3d = {"type": "dimensionality", "min": 3, "max": 3}
            requirement_2d_to_4d = {"type": "dimensionality", "min": 2, "max": 4}
            vs["crop"] = {"title": _("Crop"), "expression": "{src}",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True}]}
            vs["sum"] = {"title": _("Sum"), "expression": "xd.sum({src}, src.xdata.datum_dimension_indexes[0])",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True, "use_display_data": False, "requirements": [requirement_2d_to_4d]}]}
            slice_center_param = {"name": "center", "label": _("Center"), "type": "integral", "value": 0, "value_default": 0, "value_min": 0}
            slice_width_param = {"name": "width", "label": _("Width"), "type": "integral", "value": 1, "value_default": 1, "value_min": 1}
            vs["slice"] = {"title": _("Slice"), "expression": "xd.slice_sum({src}, center, width)",
                "sources": [{"name": "src", "label": _("Source"), "croppable": True, "use_display_data": False, "requirements": [requirement_3d]}],
                "parameters": [slice_center_param, slice_width_param]}
            pick_in_region = {"name": "pick_region", "type": "point", "params": {"label": _("Pick Point")}}
            pick_out_region = {"name": "interval_region", "type": "interval", "params": {"label": _("Display Slice")}}
            pick_connection = {"type": "property", "src": "display", "src_prop": "slice_interval", "dst": "interval_region", "dst_prop": "interval"}
            vs["pick-point"] = {"title": _("Pick"), "expression": "xd.pick({src}, pick_region.position)",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "regions": [pick_in_region], "requirements": [requirement_3d]}],
                "out_regions": [pick_out_region], "connections": [pick_connection]}
            pick_sum_in_region = {"name": "region", "type": "rectangle", "params": {"label": _("Pick Region")}}
            pick_sum_out_region = {"name": "interval_region", "type": "interval", "params": {"label": _("Display Slice")}}
            pick_sum_connection = {"type": "property", "src": "display", "src_prop": "slice_interval", "dst": "interval_region", "dst_prop": "interval"}
            vs["pick-mask-sum"] = {"title": _("Pick Sum"), "expression": "xd.sum_region({src}, region.mask_xdata_with_shape({src}.data_shape[0:2]))",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "regions": [pick_sum_in_region], "requirements": [requirement_3d]}],
                "out_regions": [pick_sum_out_region], "connections": [pick_sum_connection]}
            line_profile_in_region = {"name": "line_region", "type": "line", "params": {"label": _("Line Profile")}}
            line_profile_connection = {"type": "interval_list", "src": "data_source", "dst": "line_region"}
            vs["line-profile"] = {"title": _("Line Profile"), "expression": "xd.line_profile({src}, line_region.vector, line_region.line_width)",
                "sources": [{"name": "src", "label": _("Source"), "regions": [line_profile_in_region]}], "connections": [line_profile_connection]}
            vs["filter"] = {"title": _("Filter"), "expression": "xd.real(xd.ifft({src}))",
                "sources": [{"name": "src", "label": _("Source"), "use_display_data": False, "use_filtered_data": True, "requirements": [requirement_2d]}]}
            cls._builtin_processing_descriptions = vs
        return cls._builtin_processing_descriptions

    def get_fft_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("fft", [(data_item, crop_region)])

    def get_ifft_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("inverse-fft", [(data_item, crop_region)])

    def get_auto_correlate_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("auto-correlate", [(data_item, crop_region)])

    def get_cross_correlate_new(self, data_item1: DataItem.DataItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("cross-correlate", [(data_item1, crop_region1), (data_item2, crop_region2)])

    def get_sobel_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sobel", [(data_item, crop_region)])

    def get_laplace_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("laplace", [(data_item, crop_region)])

    def get_gaussian_blur_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("gaussian-blur", [(data_item, crop_region)])

    def get_median_filter_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("median-filter", [(data_item, crop_region)])

    def get_uniform_filter_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("uniform-filter", [(data_item, crop_region)])

    def get_transpose_flip_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("transpose-flip", [(data_item, crop_region)])

    def get_resample_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("resample", [(data_item, crop_region)])

    def get_resize_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("resize", [(data_item, crop_region)])

    def get_histogram_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("histogram", [(data_item, crop_region)])

    def get_add_new(self, data_item1: DataItem.DataItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("add", [(data_item1, crop_region1), (data_item2, crop_region2)])

    def get_subtract_new(self, data_item1: DataItem.DataItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("subtract", [(data_item1, crop_region1), (data_item2, crop_region2)])

    def get_multiply_new(self, data_item1: DataItem.DataItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("multiply", [(data_item1, crop_region1), (data_item2, crop_region2)])

    def get_divide_new(self, data_item1: DataItem.DataItem, data_item2: DataItem.DataItem, crop_region1: Graphics.RectangleTypeGraphic=None, crop_region2: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("divide", [(data_item1, crop_region1), (data_item2, crop_region2)])

    def get_invert_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("invert", [(data_item, crop_region)])

    def get_convert_to_scalar_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("convert-to-scalar", [(data_item, crop_region)])

    def get_crop_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        if data_item and len(data_item.displays) > 0 and not crop_region:
            display = data_item.displays[0]
            if data_item.is_data_2d:
                rect_region = Graphics.RectangleGraphic()
                rect_region.center = 0.5, 0.5
                rect_region.size = 0.5, 0.5
                display.add_graphic(rect_region)
                crop_region = rect_region
            elif data_item.is_data_1d:
                interval_region = Graphics.IntervalGraphic()
                interval_region.interval = 0.25, 0.75
                display.add_graphic(interval_region)
                crop_region = interval_region
        return self.__make_computation("crop", [(data_item, crop_region)])

    def get_projection_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("sum", [(data_item, crop_region)])

    def get_slice_sum_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("slice", [(data_item, crop_region)])

    def get_pick_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, pick_region: Graphics.PointTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("pick-point", [(data_item, crop_region)], {"src": [pick_region]})

    def get_pick_region_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, pick_region: Graphics.Graphic=None) -> DataItem.DataItem:
        return self.__make_computation("pick-mask-sum", [(data_item, crop_region)], {"src": [pick_region]})

    def get_line_profile_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None, line_region: Graphics.LineTypeGraphic=None) -> DataItem.DataItem:
        return self.__make_computation("line-profile", [(data_item, crop_region)], {"src": [line_region]})

    def get_fourier_filter_new(self, data_item: DataItem.DataItem, crop_region: Graphics.RectangleTypeGraphic=None) -> DataItem.DataItem:
        if data_item and len(data_item.displays) > 0:
            display = data_item.displays[0]
            has_mask = False
            for graphic in display.graphics:
                if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                    has_mask = True
                    break
            if not has_mask:
                graphic = Graphics.RingGraphic()
                graphic.radius_1 = 0.15
                graphic.radius_2 = 0.25
                display.add_graphic(graphic)
        return self.__make_computation("filter", [(data_item, crop_region)])

DocumentModel.register_processing_descriptions(DocumentModel._get_builtin_processing_descriptions())

def evaluate_data(computation) -> DataAndMetadata.DataAndMetadata:
    api = PlugInManager.api_broker_fn("~1.0", None)
    api_data_item = api._new_api_object(DataItem.new_data_item(None))
    error_text = computation.evaluate_with_target(api, api_data_item)
    computation.error_text = error_text
    return api_data_item.data_and_metadata
