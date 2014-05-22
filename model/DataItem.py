# standard libraries
import collections
import copy
import datetime
import gettext
import logging
import os
import threading
import uuid

# third party libraries
import numpy

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import DataItemProcessor
from nion.swift.model import Display
from nion.swift.model import Image
from nion.swift.model import Operation
from nion.swift.model import Storage
from nion.swift.model import Utility
from nion.ui import Observable
from nion.ui import ThreadPool

_ = gettext.gettext


class StatisticsDataItemProcessor(DataItemProcessor.DataItemProcessor):

    def __init__(self, data_item):
        super(StatisticsDataItemProcessor, self).__init__(data_item, "statistics_data")

    def get_calculated_data(self, ui, data):
        #logging.debug("Calculating statistics %s", self)
        mean = numpy.mean(data)
        std = numpy.std(data)
        data_min, data_max = self.item.data_range
        all_computations = { "mean": mean, "std": std, "min": data_min, "max": data_max }
        global _computation_fns
        for computation_fn in _computation_fns:
            computations = computation_fn(self.item)
            if computations is not None:
                all_computations.update(computations)
        return all_computations

    def get_default_data(self):
        return { }

    def get_data_item(self):
        return self.item


# data items will represents a numpy array. the numpy array
# may be stored directly in this item (master data), or come
# from another data item (data source).

# thumbnail: a small representation of this data item

# displays: list of displays for this data item

# intrinsic_calibrations: calibration for each dimension

# data: data with all operations applied

# master data: a numpy array associated with this data item
# data source: another data item from which data is taken

# data range: cached value for data min/max. calculated when data is requested, or on demand.

# operations: a list of operations applied to make data

# data items: child data items (aka derived data)

# cached data: holds last result of data calculation

# last cached data: holds last valid cached data

# best data: returns the best data available without doing a calculation

# live data: a bool indicating whether the data is live

# data is calculated when requested. this makes it imperative that callers
# do not ask for data to be calculated on the main thread.

# values that are cached will be marked as dirty when they don't match
# the underlying data. however, the values will still return values for
# the out of date data.


# enumerations for types of changes
DATA = 1
METADATA = 2
DISPLAYS = 3
SOURCE = 4


# dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# time zone name is for display only and has no specified format

class DataItem(Storage.StorageBase, Observable.ActiveSerializable):

    def __init__(self, data=None, create_display=True):
        super(DataItem, self).__init__()
        self.storage_properties += ["properties"]
        self.storage_data_keys += ["master_data"]
        self.storage_type = "data-item"
        self.define_property("intrinsic_intensity_calibration", Calibration.Calibration(), cls=Calibration.Calibration)
        self.closed = False
        # data is immutable but metadata isn't, keep track of original and modified dates
        self.__operations = list()
        self.__displays = list()
        self.__properties = dict()
        current_datetime_item = Utility.get_current_datetime_item()
        self.__properties["datetime_original"] = current_datetime_item
        self.__properties["datetime_modified"] = copy.deepcopy(current_datetime_item)
        self.__data_mutex = threading.RLock()
        self.__get_data_mutex = threading.RLock()
        self.__cached_data = None
        self.__cached_data_dirty = True
        # master data shape and dtype are always valid if there is no data source.
        self.__master_data = None
        self.__master_data_shape = None
        self.__master_data_dtype = None
        self.__master_data_reference_type = None  # used for temporary storage
        self.__master_data_reference = None  # used for temporary storage
        self.__master_data_file_datetime = None  # used for temporary storage
        self.master_data_save_event = threading.Event()
        self.__has_master_data = False
        self.__data_source = None
        self.__data_ref_count = 0
        self.__data_ref_count_mutex = threading.RLock()
        self.__data_item_change_mutex = threading.RLock()
        self.__data_item_change_count = 0
        self.__data_item_changes = set()
        self.__shared_thread_pool = ThreadPool.create_thread_queue()
        self.__processors = dict()
        self.__processors["statistics"] = StatisticsDataItemProcessor(self)
        self.__set_master_data(data)
        if create_display:
            self.add_display(Display.Display())  # always have one display, for now

    def __str__(self):
        return "{0} {1} ({2}, {3})".format(self.__repr__(), (self.title if self.title else _("Untitled")), str(self.uuid), self.datetime_original_as_string)

    @classmethod
    def _get_data_file_path(cls, uuid_, datetime_item, session_id=None):
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
        path_components.append("master_data_" + encoded_uuid_str + ".nsdata")
        return os.path.join(*path_components)

    @classmethod
    def build(cls, datastore, item_node, uuid_):
        properties = datastore.get_property(item_node, "properties")
        properties = properties if properties else dict()
        operation_list = properties.get("operations", list())
        if "operations" in properties:
            del properties["operations"]  # these will be added back below
        display_list = properties.get("displays", list())
        if "displays" in properties:
            del properties["displays"]  # these will be added back below
        has_master_data = datastore.has_data(item_node, "master_data")
        if has_master_data:
            master_data_shape, master_data_dtype = datastore.get_data_shape_and_dtype(item_node, "master_data")
        else:
            master_data_shape, master_data_dtype = None, None
        data_item = DataItem(create_display=False)
        data_item.__properties = properties
        data_item.__master_data_shape = master_data_shape
        data_item.__master_data_dtype = master_data_dtype
        data_item.__has_master_data = has_master_data
        data_item.read_storage(data_item.__properties)
        for operation_dict in operation_list:
            operation_item = Operation.OperationItem.build(operation_dict)
            data_item.add_operation(operation_item)
        # replace existing displays. TODO: remove this when we can handle data items without any displays
        for display_dict in display_list:
            display_item = Display.Display.build(display_dict)
            data_item.add_display(display_item)
        assert(len(data_item.displays) > 0)
        return data_item

    # This gets called when reference count goes to 0, but before deletion.
    def about_to_delete(self):
        self.closed = True
        self.__shared_thread_pool.close()
        for operation in self.operations:
            self.remove_operation(operation)
        for display in self.displays:
            self.remove_display(display)
        self.__set_data_source(None)
        self.__set_master_data(None)
        super(DataItem, self).about_to_delete()

    def __deepcopy__(self, memo):
        data_item_copy = DataItem(create_display=False)
        with data_item_copy.property_changes() as property_accessor:
            properties_copy = self.properties
            if "operations" in properties_copy:
                del properties_copy["operations"]  # these will be added back below
            if "displays" in properties_copy:
                del properties_copy["displays"]  # these will be added back below
            property_accessor.properties.clear()
            property_accessor.properties.update(properties_copy)
        for operation in self.operations:
            data_item_copy.add_operation(copy.deepcopy(operation, memo))
        # replace existing displays. TODO: remove this when we can handle data items without any displays
        for display in self.displays:
            data_item_copy.add_display(copy.deepcopy(display, memo))
        if self.has_master_data:
            with self.data_ref() as data_ref:
                data_item_copy.__set_master_data(numpy.copy(data_ref.master_data))
        else:
            data_item_copy.__set_master_data(None)
        # data source will be copied with properties and the connection established when
        # this copy is inserted.
        memo[id(self)] = data_item_copy
        return data_item_copy

    def add_shared_task(self, task_id, item, fn):
        self.__shared_thread_pool.add_task(task_id, item, fn)

    def get_processor(self, processor_id):
        return self.__processors[processor_id]

    # cheap, but incorrect, way to tell whether this is live acquisition
    def __get_is_live(self):
        return self.transaction_count > 0
    is_live = property(__get_is_live)

    def __get_live_status_as_string(self):
        if self.is_live:
            frame_index_str = str(self.__properties.get("frame_index", str()))
            partial_str = "{0:d}/{1:d}".format(self.__properties.get("valid_rows"), self.spatial_shape[-1]) if "valid_rows" in self.__properties else str()
            return "{0:s} {1:s} {2:s}".format(_("Live"), frame_index_str, partial_str)
        return str()
    live_status_as_string = property(__get_live_status_as_string)

    def __get_session_id(self):
        # first check to see if we have a session_id set directly
        session_id = self.__properties.get("session_id", str())
        # if not, try the data source
        if not session_id and self.data_source:
            session_id = self.data_source.session_id
        # if not, try the datetime
        if not session_id:
            datetime_item = self.datetime_original if self.datetime_original else Utility.get_current_datetime_item()
            datetime_ = Utility.get_datetime_from_datetime_item(datetime_item)
            datetime_ = datetime_ if datetime_ else datetime.datetime.now()
            session_id = datetime_.strftime("%Y%m%d-000000")
        return session_id
    def __set_session_id(self, session_id):
        # verify its in suitable form
        assert datetime.datetime.strptime(session_id, "%Y%m%d-%H%M%S")
        # set it into properties
        with self.property_changes() as property_accessor:
            property_accessor.properties["session_id"] = session_id
    session_id = property(__get_session_id, __set_session_id)

    def data_item_changes(self):
        class DataItemChangeContextManager(object):
            def __init__(self, data_item):
                self.__data_item = data_item
            def __enter__(self):
                self.__data_item.begin_data_item_changes()
                return self
            def __exit__(self, type, value, traceback):
                self.__data_item.end_data_item_changes()
        return DataItemChangeContextManager(self)

    def begin_data_item_changes(self):
        with self.__data_item_change_mutex:
            self.__data_item_change_count += 1

    def end_data_item_changes(self):
        with self.__data_item_change_mutex:
            self.__data_item_change_count -= 1
            data_item_change_count = self.__data_item_change_count
            if data_item_change_count == 0:
                changes = self.__data_item_changes
                self.__data_item_changes = set()
        if data_item_change_count == 0:
            # clear the processor caches
            for processor in self.__processors.values():
                processor.data_item_changed()
            # clear the data cache and preview if the data changed
            if DATA in changes or SOURCE in changes:
                self.__clear_cached_data()
            self.notify_listeners("data_item_content_changed", self, changes)

    def _property_changed(self, property_name, value):
        if property_name == "intrinsic_intensity_calibration":
            with self.property_changes() as pc:
                intensity_calibration_dict = pc.properties.setdefault("intrinsic_intensity_calibration", dict())
                value.write_dict(intensity_calibration_dict)
            self.notify_listeners("data_item_calibration_changed")

    # call this when the listeners need to be updated (via data_item_content_changed).
    # Calling this method will send the data_item_content_changed method to each listener.
    def notify_data_item_content_changed(self, changes):
        with self.data_item_changes():
            with self.__data_item_change_mutex:
                self.__data_item_changes.update(changes)

    def __get_data_range_for_data(self, data):
        if data is not None:
            if self.is_data_rgb_type:
                data_range = (0, 255)
            elif Image.is_shape_and_dtype_complex_type(data.shape, data.dtype):
                scalar_data = Image.scalar_from_array(data)
                data_range = (scalar_data.min(), scalar_data.max())
            else:
                data_range = (data.min(), data.max())
        else:
            data_range = None
        if data_range:
            self.set_cached_value("data_range", data_range)
        else:
            self.remove_cached_value("data_range")
        return data_range

    def __get_data_range(self):
        with self.__data_mutex:
            data_range = self.get_cached_value("data_range")
        # this property may be access on the main thread (inspector)
        # so it really needs to return quickly in most cases. don't
        # recalculate in the main thread unless the value doesn't exist
        # at all.
        # TODO: use promises here?
        if self.is_cached_value_dirty("data_range"):
            pass  # TODO: calculate data range in thread
        if not data_range:
            with self.data_ref() as data_ref:
                data = data_ref.data
                data_range = self.__get_data_range_for_data(data)
        return data_range
    data_range = property(__get_data_range)

    # calibration stuff

    def __is_calibrated(self):
        return len(self.intrinsic_calibrations) == len(self.spatial_shape)
    is_calibrated = property(__is_calibrated)

    def set_spatial_calibration(self, dimension, calibration):
        with self.property_changes() as pc:
            spatial_calibration_list = pc.properties.setdefault("spatial_calibrations", list())
            while len(spatial_calibration_list) <= dimension:
                spatial_calibration_list.append(dict())
            calibration.write_dict(spatial_calibration_list[dimension])
        self.notify_listeners("data_item_calibration_changed")

    def set_intensity_calibration(self, calibration):
        self.intrinsic_intensity_calibration = calibration

    def __get_intrinsic_calibrations(self):
        spatial_calibration_list = self.__properties.get("spatial_calibrations", list())
        while len(spatial_calibration_list) < len(self.spatial_shape):
            spatial_calibration_list.append(dict())
        return [Calibration.Calibration().read_dict(spatial_calibration_list[i]) for i in xrange(len(self.spatial_shape))]
    intrinsic_calibrations = property(__get_intrinsic_calibrations)

    def __get_calculated_intensity_calibration(self):
        # data source calibrations override
        if self.data_source:
            intensity_calibration = self.data_source.calculated_intensity_calibration
        else:
            intensity_calibration = self.intrinsic_intensity_calibration
        data_shape, data_dtype = self.__get_root_data_shape_and_dtype()
        if data_shape is not None and data_dtype is not None:
            for operation in self.operations:
                if operation.enabled:
                    intensity_calibration = operation.get_processed_intensity_calibration(data_shape, data_dtype, intensity_calibration)
                    data_shape, data_dtype = operation.get_processed_data_shape_and_dtype(data_shape, data_dtype)
        return intensity_calibration
    calculated_intensity_calibration = property(__get_calculated_intensity_calibration)

    # calculate the calibrations by starting with the source calibration
    # and then applying calibration transformations for each enabled
    # operation.
    def __get_calculated_calibrations(self):
        # data source calibrations override
        if self.data_source:
            calibrations = self.data_source.calculated_calibrations
        else:
            calibrations = self.intrinsic_calibrations
        data_shape, data_dtype = self.__get_root_data_shape_and_dtype()
        if data_shape is not None and data_dtype is not None:
            for operation_item in self.operations:
                if operation_item.enabled:
                    calibrations = operation_item.get_processed_calibrations(data_shape, data_dtype, calibrations)
                    data_shape, data_dtype = operation_item.get_processed_data_shape_and_dtype(data_shape, data_dtype)
        return calibrations
    calculated_calibrations = property(__get_calculated_calibrations)

    # date times

    def __get_datetime_modified(self):
        return self.__properties.get("datetime_modified")
    def __set_datetime_modified(self, datetime_modified):
        if self.datetime_modified != datetime_modified:
            with self.property_changes() as pc:
                if datetime_modified is not None:
                    pc.properties["datetime_modified"] = copy.deepcopy(datetime_modified)
                else:
                    del pc.properties["datetime_modified"]
            self.notify_set_property("datetime_modified", datetime_modified)
            self.notify_data_item_content_changed(set([METADATA]))
    datetime_modified = property(__get_datetime_modified, __set_datetime_modified)

    def __get_datetime_original(self):
        return self.__properties.get("datetime_original")
    def __set_datetime_original(self, datetime_original):
        if self.datetime_original != datetime_original:
            with self.property_changes() as pc:
                if datetime_original is not None:
                    pc.properties["datetime_original"] = copy.deepcopy(datetime_original)
                else:
                    del pc.properties["datetime_original"]
            self.notify_set_property("datetime_original", datetime_original)
            self.notify_data_item_content_changed(set([METADATA]))
    datetime_original = property(__get_datetime_original, __set_datetime_original)

    def __get_datetime_original_as_string(self):
        datetime_original = self.datetime_original
        if datetime_original:
            datetime_ = Utility.get_datetime_from_datetime_item(datetime_original)
            if datetime_:
                return datetime_.strftime("%c")
        # fall through to here
        return str()
    datetime_original_as_string = property(__get_datetime_original_as_string)

    # access properties

    def __get_properties(self):
        return copy.deepcopy(self.__properties)
    properties = property(__get_properties)

    def grab_properties(self):
        return self.__properties
    def release_properties(self):
        self.notify_set_property("properties", self.__properties)
        self.notify_data_item_content_changed(set([METADATA]))

    def property_changes(self):
        grab_properties = DataItem.grab_properties
        release_properties = DataItem.release_properties
        class PropertyChangeContextManager(object):
            def __init__(self, data_item):
                self.__data_item = data_item
            def __enter__(self):
                return self
            def __exit__(self, type, value, traceback):
                release_properties(self.__data_item)
            def __get_properties(self):
                return grab_properties(self.__data_item)
            properties = property(__get_properties)
        return PropertyChangeContextManager(self)

    class Datastore(object):

        def __init__(self, data_item, storage_dict):
            self.data_item = data_item
            self.storage_dict = storage_dict

        def __enter__(self):
            return self.storage_dict

        def __exit__(self, type, value, traceback):
            self.data_item.release_properties()

    def add_display(self, display):
        self.__displays.append(display)
        display.add_ref()
        display.add_listener(self)
        with self.property_changes() as pc:
            display_list = pc.properties.setdefault("displays", list())
            display_dict = dict()
            display_list.append(display_dict)
            display.datastore = DataItem.Datastore(self, display_dict)
            display.write_storage(display.datastore.storage_dict)
        display._set_data_item(self)
        self.notify_data_item_content_changed(set([DISPLAYS]))

    def remove_display(self, display):
        display_index = self.__displays.index(display)
        self.__displays.remove(display)
        self.notify_data_item_content_changed(set([DISPLAYS]))
        display.remove_listener(self)
        display.remove_ref()
        display.datastore = None
        display._set_data_item(None)
        with self.property_changes() as pc:
            display_list = pc.properties["displays"]
            del display_list[display_index]

    def __get_displays(self):
        return copy.copy(self.__displays)
    displays = property(__get_displays)

    # call this when operations change or data souce changes
    # this allows operations to update their default values
    def sync_operations(self):
        data_shape, data_dtype = self.__get_root_data_shape_and_dtype()
        if data_shape is not None and data_dtype is not None:
            for operation in self.operations:
                operation.update_data_shape_and_dtype(data_shape, data_dtype)
                if operation.enabled:
                    data_shape, data_dtype = operation.get_processed_data_shape_and_dtype(data_shape, data_dtype)

    def add_operation(self, operation):
        self.__operations.append(operation)
        operation.add_ref()
        operation.add_listener(self)
        operation.add_observer(self)
        with self.property_changes() as pc:
            operation_list = pc.properties.setdefault("operations", list())
            operation_dict = dict()
            operation.write_storage(operation_dict)
            operation_list.append(operation_dict)
        self.sync_operations()
        self.notify_data_item_content_changed(set([DATA]))
        if self.data_source:
            self.data_source.add_operation_graphics_to_displays(operation.graphics)

    def remove_operation(self, operation):
        operation_index = self.__operations.index(operation)
        self.__operations.remove(operation)
        self.sync_operations()
        self.notify_data_item_content_changed(set([DATA]))
        if self.data_source:
            self.data_source.remove_operation_graphics_from_displays(operation.graphics)
        operation.remove_listener(self)
        operation.remove_observer(self)
        operation.remove_ref()
        with self.property_changes() as pc:
            operation_list = pc.properties["operations"]
            del operation_list[operation_index]

    def __get_operations(self):
        return copy.copy(self.__operations)
    operations = property(__get_operations)

    # this message comes from the operation.
    # by watching for changes to the operations relationship. when an operation
    # is added/removed, this object becomes a listener via add_listener/remove_listener.
    def operation_changed(self, operation):
        self.notify_data_item_content_changed(set([DATA]))

    # this message comes from the operation.
    # it is generated when the user deletes a operation graphic.
    # that informs the display which notifies the graphic which
    # notifies the operation which notifies this data item. ugh.
    def remove_operation_because_graphic_removed(self, operation):
        self.notify_listeners("request_remove_data_item", self)

    # this message is received by other data items using this one as a data source.
    def add_operation_graphics_to_displays(self, operation_graphics):
        for display in self.displays:
            display.add_operation_graphics(operation_graphics)

    # this message is received by other data items using this one as a data source.
    def remove_operation_graphics_from_displays(self, operation_graphics):
        for display in self.displays:
            display.remove_operation_graphics(operation_graphics)

    def property_changed(self, object, property, value):
        if object in self.__operations:
            with self.property_changes() as pc:
                operation_dict = pc.properties["operations"][self.__operations.index(object)]
                operation_dict[property] = value

    # connect this item to its data source, if any. the lookup_data_item parameter
    # is a function to look up data items by uuid. this method also establishes the
    # display graphics for this items operations. direct data source is used for testing.
    def connect_data_source(self, lookup_data_item=None, direct_data_source=None):
        assert lookup_data_item or direct_data_source
        data_source_uuid_str = self.properties.get("data_source_uuid")
        data_source = lookup_data_item(uuid.UUID(data_source_uuid_str)) if data_source_uuid_str and lookup_data_item else direct_data_source
        self.__set_data_source(data_source)
        if data_source:
            for operation_item in self.operations:
                data_source.add_operation_graphics_to_displays(operation_item.graphics)

    # disconnect this item from its data source. also removes the graphics for this
    # items operations.
    def disconnect_data_source(self):
        data_source = self.data_source
        if data_source:
            for operation_item in self.operations:
                data_source.remove_operation_graphics_from_displays(operation_item.graphics)
        self.__set_data_source(None)

    # title
    def __get_title(self):
        return self.__properties.get("title", _("Untitled"))
    def __set_title(self, value):
        with self.property_changes() as pc:
            if value is not None:
                pc.properties["title"] = unicode(copy.copy(value))
            else:
                del pc.properties["title"]
        self.notify_set_property("title", value)
    title = property(__get_title, __set_title)

    # caption
    def __get_caption(self):
        return self.__properties.get("caption", unicode())
    def __set_caption(self, value):
        with self.property_changes() as pc:
            pc.properties["caption"] = unicode(value)
        self.notify_set_property("caption", value)
    caption = property(__get_caption, __set_caption)

    # flag
    def __get_flag(self):
        return self.__properties.get("flag", 0)
    def __set_flag(self, value):
        with self.property_changes() as pc:
            pc.properties["flag"] = max(min(int(value), 1), -1)
        self.notify_set_property("flag", value)
    flag = property(__get_flag, __set_flag)

    # rating
    def __get_rating(self):
        return self.__properties.get("rating", 0)
    def __set_rating(self, value):
        with self.property_changes() as pc:
            pc.properties["rating"] = min(max(int(value), 0), 5)
        self.notify_set_property("rating", value)
    rating = property(__get_rating, __set_rating)

    # source file path
    def __get_source_file_path(self):
        return self.__properties.get("source_file_path")
    def __set_source_file_path(self, value):
        if self.source_file_path != value:
            with self.property_changes() as pc:
                if value is not None:
                    pc.properties["source_file_path"] = unicode(copy.copy(value))
                else:
                    del pc.properties["source_file_path"]
            self.notify_set_property("source_file_path", self.source_file_path)
    source_file_path = property(__get_source_file_path, __set_source_file_path)

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(DataItem, self).notify_set_property(key, value)
        self.notify_data_item_content_changed(set([METADATA]))
        for processor in self.__processors.values():
            processor.item_property_changed(key, value)

    # this message comes from the calibration. the connection is established when a calibration
    # is added or removed from this object.
    def calibration_changed(self, calibration):
        self.notify_data_item_content_changed(set([METADATA]))

    # this message comes from the displays.
    def display_changed(self, display):
        self.notify_data_item_content_changed(set([DISPLAYS]))

    # data_item_content_changed comes from data sources to indicate that data
    # has changed. the connection is established in __set_data_source.
    def data_item_content_changed(self, data_source, changes):
        assert data_source == self.data_source
        # we don't care about display changes to the data source; only data changes.
        if DATA in changes:
            # propogate to listeners
            self.notify_data_item_content_changed(changes)

    # use a property here to correct add_ref/remove_ref
    # also manage connection to data source.
    # data_source is a caching value only. it is not part of the model.
    def __get_data_source(self):
        return self.__data_source
    def __set_data_source(self, data_source):
        assert data_source is None or not self.has_master_data  # can't have master data and data source
        if self.__data_source:
            with self.__data_mutex:
                self.__data_source.remove_listener(self)
                self.__data_source.remove_ref()
                self.__data_source = None
                self.sync_operations()
        if data_source:
            with self.__data_mutex:
                assert isinstance(data_source, DataItem)
                self.__data_source = data_source
                # we will receive data_item_content_changed from data_source
                self.__data_source.add_listener(self)
                self.__data_source.add_ref()
                self.sync_operations()
            self.data_item_content_changed(self.__data_source, set([SOURCE]))
    data_source = property(__get_data_source)

    # add a reference to the given data source
    def add_data_source(self, data_source):
        with self.property_changes() as property_accessor:
            property_accessor.properties["data_source_uuid"] = str(data_source.uuid)

    # remove a reference to the given data source
    def remove_data_source(self, data_source):
        with self.property_changes() as property_accessor:
            property_accessor.properties.pop("data_source_uuid", None)

    def __get_master_data(self):
        return self.__master_data
    def __set_master_data(self, data):
        with self.data_item_changes():
            assert not self.closed or data is None
            assert (data.shape is not None) if data is not None else True  # cheap way to ensure data is an ndarray
            assert data is None or self.__data_source is None  # can't have master data and data source
            with self.__data_mutex:
                if data is not None:
                    self.set_cached_value("master_data_shape", data.shape)
                    self.set_cached_value("master_data_dtype", data.dtype)
                else:
                    self.remove_cached_value("master_data_shape")
                    self.remove_cached_value("master_data_dtype")
                self.__master_data = data
                self.__master_data_shape = data.shape if data is not None else None
                self.__master_data_dtype = data.dtype if data is not None else None
                self.__has_master_data = data is not None
            data_file_path = DataItem._get_data_file_path(self.uuid, self.datetime_original, session_id=self.session_id)
            file_datetime = Utility.get_datetime_from_datetime_item(self.datetime_original)
            # tell the database about it
            if self.__master_data is not None:
                # save these here so that if the data isn't immediately written out, these values can be returned
                # from _get_master_data_data_reference when the data is written.
                self.__master_data_reference_type = "relative_file"
                self.__master_data_reference = data_file_path
                self.__master_data_file_datetime = file_datetime
                self.notify_set_data_reference("master_data", self.__master_data, self.__master_data.shape, self.__master_data.dtype, "relative_file", data_file_path, file_datetime)
                self.notify_set_property("data_range", self.data_range)
            self.notify_data_item_content_changed(set([DATA]))

    # accessor for storage subsystem.
    def _get_master_data_data_reference(self):
        reference_type = self.__master_data_reference_type # if self.__master_data_reference_type else "relative_file"
        reference = self.__master_data_reference # if self.__master_data_reference else DataItem._get_data_file_path(self.uuid, self.datetime_original, session_id=self.session_id)
        file_datetime = self.__master_data_file_datetime # if self.__master_data_file_datetime else Utility.get_datetime_from_datetime_item(self.datetime_original)
        # when data items are initially created, they will have their data in memory.
        # this method will be called when the data gets written out to disk.
        # to ensure that the data gets unloaded, grab it here and release it.
        # if no other object is holding a reference, the data will be unloaded from memory.
        if self.__master_data is not None:
            with self.data_ref() as d:
                master_data = d.master_data
        else:
            master_data = None
        self.master_data_save_event.set()
        return master_data, self.__master_data_shape, self.__master_data_dtype, reference_type, reference, file_datetime

    def set_external_master_data(self, data_file_path, data_shape, data_dtype):
        with self.__data_mutex:
            self.set_cached_value("master_data_shape", data_shape)
            self.set_cached_value("master_data_dtype", data_dtype)
            self.__master_data_shape = data_shape
            self.__master_data_dtype = data_dtype
            self.__has_master_data = True
            file_datetime = datetime.datetime.fromtimestamp(os.path.getmtime(data_file_path))
        # save these here so that if the data isn't immediately written out, these values can be returned
        # from _get_master_data_data_reference when the data is written.
        self.__master_data_reference_type = "external_file"
        self.__master_data_reference = data_file_path
        self.__master_data_file_datetime = file_datetime
        self.notify_set_data_reference("master_data", None, data_shape, data_dtype, "external_file", data_file_path, file_datetime)
        self.notify_set_property("data_range", self.data_range)
        self.notify_data_item_content_changed(set([DATA]))

    def __load_master_data(self):
        # load data from datastore if not present
        if self.has_master_data and self.datastore and self.__master_data is None:
            #logging.debug("loading %s", self)
            reference_type, reference = self.datastore.get_data_reference(self.datastore.find_parent_node(self), "master_data")
            self.__master_data = self.datastore.load_data_reference("master_data", reference_type, reference)

    def __unload_master_data(self):
        # unload data if it can be reloaded from datastore.
        # data cannot be unloaded if transaction count > 0 or if there is no datastore.
        if self.transaction_count == 0 and self.has_master_data and self.datastore:
            self.__master_data = None
            self.__cached_data = None
            #logging.debug("unloading %s", self)

    def increment_data_ref_count(self):
        with self.__data_ref_count_mutex:
            initial_count = self.__data_ref_count
            self.__data_ref_count += 1
            if initial_count == 0:
                if self.__data_source:
                    self.__data_source.increment_data_ref_count()
                else:
                    self.__load_master_data()
        return initial_count+1
    def decrement_data_ref_count(self):
        with self.__data_ref_count_mutex:
            self.__data_ref_count -= 1
            final_count = self.__data_ref_count
            if final_count == 0:
                if self.__data_source:
                    self.__data_source.decrement_data_ref_count()
                else:
                    self.__unload_master_data()
        return final_count

    # used for testing
    def __is_data_loaded(self):
        return self.has_master_data and self.__master_data is not None
    is_data_loaded = property(__is_data_loaded)

    def __get_has_master_data(self):
        return self.__has_master_data
    has_master_data = property(__get_has_master_data)

    def __get_has_data_source(self):
        return self.__data_source is not None
    has_data_source = property(__get_has_data_source)

    # grab a data reference as a context manager. the object
    # returned defines data and master_data properties. reading data
    # should use the data property. writing data (if allowed) should
    # assign to the master_data property.
    def data_ref(self):
        get_master_data = DataItem.__get_master_data
        set_master_data = DataItem.__set_master_data
        get_data = DataItem.__get_data
        class DataAccessor(object):
            def __init__(self, data_item):
                self.__data_item = data_item
            def __enter__(self):
                self.__data_item.increment_data_ref_count()
                return self
            def __exit__(self, type, value, traceback):
                self.__data_item.decrement_data_ref_count()
            def __get_master_data(self):
                return get_master_data(self.__data_item)
            def __set_master_data(self, data):
                set_master_data(self.__data_item, data)
            master_data = property(__get_master_data, __set_master_data)
            def master_data_updated(self):
                pass
            def __get_data(self):
                return get_data(self.__data_item)
            data = property(__get_data)
        return DataAccessor(self)

    def __get_data_immediate(self):
        """ add_ref, get data, remove_ref """
        with self.data_ref() as data_ref:
            return data_ref.data
    data = property(__get_data_immediate)

    # get the root data shape and dtype without causing calculation to occur if possible.
    def __get_root_data_shape_and_dtype(self):
        with self.__data_mutex:
            if self.has_master_data:
                return self.__master_data_shape, self.__master_data_dtype
            if self.has_data_source:
                return self.data_source.data_shape_and_dtype
        return None, None

    def __clear_cached_data(self):
        with self.__data_mutex:
            self.__cached_data_dirty = True
            self.set_cached_value_dirty("data_range")

    # data property. read only. this method should almost *never* be called on the main thread since
    # it takes an unpredictable amount of time.
    def __get_data(self):
        if threading.current_thread().getName() == "MainThread":
            #logging.debug("*** WARNING: data called on main thread ***")
            #import traceback
            #traceback.print_stack()
            pass
        self.__data_mutex.acquire()
        if self.__cached_data_dirty or self.__cached_data is None:
            self.__data_mutex.release()
            with self.__get_data_mutex:
                # this should NOT happen under the data mutex. it can take a long time.
                data = None
                if self.has_master_data:
                    data = self.__master_data
                if data is None:
                    if self.data_source:
                        with self.data_source.data_ref() as data_ref:
                            # this can be a lengthy operation
                            data = data_ref.data
                operations = self.operations
                if len(operations) and data is not None:
                    # apply operations
                    if data is not None:
                        for operation in reversed(operations):
                            data = operation.process_data(data)
                self.__get_data_range_for_data(data)
            with self.__data_mutex:
                self.__cached_data = data
                self.__cached_data_dirty = False
        else:
            self.__data_mutex.release()
        return self.__cached_data

    def __get_data_shape_and_dtype(self):
        with self.__data_mutex:
            if self.has_master_data:
                data_shape = self.__master_data_shape
                data_dtype = self.__master_data_dtype
            elif self.has_data_source:
                data_shape = self.data_source.data_shape
                data_dtype = self.data_source.data_dtype
            else:
                data_shape = None
                data_dtype = None
            # apply operations
            if data_shape is not None:
                for operation in self.operations:
                    if operation.enabled:
                        data_shape, data_dtype = operation.get_processed_data_shape_and_dtype(data_shape, data_dtype)
            return data_shape, data_dtype
    data_shape_and_dtype = property(__get_data_shape_and_dtype)

    def __get_size_and_data_format_as_string(self):
        spatial_shape = self.spatial_shape
        data_dtype = self.data_dtype
        if spatial_shape is not None and data_dtype is not None:
            spatial_shape_str = " x ".join([str(d) for d in spatial_shape])
            if len(spatial_shape) == 1:
                spatial_shape_str += " x 1"
            dtype_names = {
                numpy.int8: _("Integer (8-bit)"),
                numpy.int16: _("Integer (16-bit)"),
                numpy.int32: _("Integer (32-bit)"),
                numpy.int64: _("Integer (64-bit)"),
                numpy.uint8: _("Unsigned Integer (8-bit)"),
                numpy.uint16: _("Unsigned Integer (16-bit)"),
                numpy.uint32: _("Unsigned Integer (32-bit)"),
                numpy.uint64: _("Unsigned Integer (64-bit)"),
                numpy.float32: _("Real (32-bit)"),
                numpy.float64: _("Real (64-bit)"),
                numpy.complex64: _("Complex (2 x 32-bit)"),
                numpy.complex128: _("Complex (2 x 64-bit)"),
            }
            if self.is_data_rgb_type:
                data_size_and_data_format_as_string = _("RGB (8-bit)") if self.is_data_rgb else _("RGBA (8-bit)")
            else:
                if not self.data_dtype.type in dtype_names:
                    logging.debug("Unknown %s", self.data_dtype)
                data_size_and_data_format_as_string = dtype_names[self.data_dtype.type] if self.data_dtype.type in dtype_names else _("Unknown Data Type")
            return "{0}, {1}".format(spatial_shape_str, data_size_and_data_format_as_string)
        return _("No Data")
    size_and_data_format_as_string = property(__get_size_and_data_format_as_string)

    def __get_data_shape(self):
        return self.data_shape_and_dtype[0]
    data_shape = property(__get_data_shape)

    def __get_spatial_shape(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.spatial_shape_from_shape_and_dtype(data_shape, data_dtype)
    spatial_shape = property(__get_spatial_shape)

    def __get_data_dtype(self):
        return self.data_shape_and_dtype[1]
    data_dtype = property(__get_data_dtype)

    def __is_data_1d(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_1d(data_shape, data_dtype)
    is_data_1d = property(__is_data_1d)

    def __is_data_2d(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_2d(data_shape, data_dtype)
    is_data_2d = property(__is_data_2d)

    def __is_data_3d(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_3d(data_shape, data_dtype)
    is_data_3d = property(__is_data_3d)

    def __is_data_rgb(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_rgb(data_shape, data_dtype)
    is_data_rgb = property(__is_data_rgb)

    def __is_data_rgba(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_rgba(data_shape, data_dtype)
    is_data_rgba = property(__is_data_rgba)

    def __is_data_rgb_type(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_rgb(data_shape, data_dtype) or Image.is_shape_and_dtype_rgba(data_shape, data_dtype)
    is_data_rgb_type = property(__is_data_rgb_type)

    def __is_data_scalar_type(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_scalar_type(data_shape, data_dtype)
    is_data_scalar_type = property(__is_data_scalar_type)

    def __is_data_complex_type(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_complex_type(data_shape, data_dtype)
    is_data_complex_type = property(__is_data_complex_type)

    def get_data_value(self, pos):
        # do not force data calculation here, but trigger data loading
        if self.__cached_data is None:
            pass  # TODO: Cursor should trigger loading of data if not already laoded.
        with self.__data_mutex:
            if self.is_data_1d:
                if self.__cached_data is not None:
                    return self.__cached_data[pos[0]]
            elif self.is_data_2d:
                if self.__cached_data is not None:
                    return self.__cached_data[pos[0], pos[1]]
            # TODO: fix me 3d
            elif self.is_data_3d:
                if self.__cached_data is not None:
                    return self.__cached_data[pos[0], pos[1]]
        return None

    def snapshot(self):
        """
            Take a snapshot and return a new data item. A snapshot is a copy of everything
            except the data and operations which are replaced by new data with the operations
            applied or "burned in".
        """
        data_item_copy = DataItem()
        with data_item_copy.property_changes() as property_accessor:
            property_accessor.properties.clear()
            property_accessor.properties.update(self.properties)
            property_accessor.properties.pop("data_source_uuid", None)
        data_item_copy.set_intensity_calibration(self.calculated_intensity_calibration)
        for index in xrange(len(self.spatial_shape)):
            data_item_copy.set_spatial_calibration(index, self.calculated_calibrations[index])
        while len(data_item_copy.displays) > 0:
            data_item_copy.remove_display(data_item_copy.displays[0])
        for display in self.displays:
            data_item_copy.add_display(copy.deepcopy(display))
        # operations are NOT copied, since this is a snapshot of the data
        with self.data_ref() as data_ref:
            data_copy = numpy.copy(data_ref.data)
            data_item_copy.__set_master_data(data_copy)
        return data_item_copy


_computation_fns = list()

def register_data_item_computation(computation_fn):
    global _computation_fns
    _computation_fns.append(computation_fn)

def unregister_data_item_computation(self, computation_fn):
    pass
