# standard libraries
import collections
import copy
import datetime
import gettext
import logging
import os
import threading
import uuid
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import DataItemProcessor
from nion.swift.model import Display
from nion.swift.model import Image
from nion.swift.model import Operation
from nion.swift.model import Region
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
        data_range = self.item.data_range
        data_min, data_max = data_range if data_range is not None else (None, None)
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


class CalibrationList(object):

    def __init__(self):
        self.list = list()

    def read_dict(self, storage_list):
        # storage_list will be whatever is returned by write_dict.
        new_list = list()
        for calibration_dict in storage_list:
            new_list.append(Calibration.Calibration().read_dict(calibration_dict))
        self.list = new_list
        return self  # for convenience

    def write_dict(self):
        list = []
        for calibration in self.list:
            list.append(calibration.write_dict())
        return list


class DataSourceUuidList(object):

    def __init__(self):
        self.list = list()

    def read_dict(self, storage_list):
        # storage_list will be whatever is returned by write_dict.
        self.list = copy.copy(storage_list)
        return self  # for convenience

    def write_dict(self):
        return copy.copy(self.list)


class IntermediateDataItem(object):

    def __init__(self, data_item, data_shape_and_dtype, intensity_calibration, spatial_calibrations):
        super(IntermediateDataItem, self).__init__()

        class IntermediateDataAccessor(object):
            def __init__(self, data_item):
                self.__data_item = data_item
            def __get_data(self):
                with self.__data_item.data_ref() as data_ref:
                    return data_ref.master_data
            data = property(__get_data)

        self.__data_item = data_item
        self.__data_accessor = IntermediateDataAccessor(data_item)
        self.data_shape_and_dtype = data_shape_and_dtype
        self.calculated_intensity_calibration = intensity_calibration
        self.calculated_calibrations = spatial_calibrations

    def __get_data(self):
        return self.__data_accessor.data
    data = property(__get_data)


# data items will represents a numpy array. the numpy array
# may be stored directly in this item (master data), or come
# from another data item (data source).

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

class DataItem(Observable.Observable, Observable.Broadcaster, Storage.Cacheable, Observable.ManagedObject):

    """
        Data items represent a list of data/metadata, a description of how that data is derived, and machinery to calculate it.

        Data is represented by ndarrays; and metadata consists of things such as dimensional and intensity
        calibrations, creation and modification dates, titles, captions, etc.

        The derivation description includes a list of source data items, operations, regions, and relationships
        between data/metadata.

        If a data item represents a single data/metadata, the following direct properties are available:

        * *data* an ndarray. see note about accessing data below.
        * *data_shape* an ndarray shape
        * *data_dtype* an ndarray shape

        and

        * *dimension_calibratons* a list of calibrations
        * *intensity_calibration* a calibration
        * *datetime_created* a datetime item
        * *datetime_modified* a datetime item
        * *title* a string (single line)
        * *caption* a string (multiple lines)
        * *rating* an integer star rating (0 to 5)
        * *flag* a flag (-1, 0, 1)
        * *session_id* a string representing the session
        * *regions* a list of regions
        * *operations* a list of operations

        For more complex data items, the following properties are also available:

        * *outputs* a list of data items
        * *inputs* a list of data items

        In addition to the properties above, data items may contain a list of displays. By convention, displays
        are only associated with "top level" data items.

        * *displays* a list of displays associated with the data item.

        Accessing data can be done directly via the data property. However, this may cause data to be loaded
        into memory from disk and unloaded every time the data property is used.

        A better way to access data if it will be used more than once is to ask for a data reference via the
        data_ref() method which returns a context manager object. When the context manager object is released,
        the data will be unloaded from memory if it is not used somewhere else. The context manager has a
        master_data property to access the data.

        Transactions.

        Liveness.

        Processors.

        Snapshots and deep copies.

        Properties.

        Data item changes.

        Metadata.

        Data range.

        Data values.
        
        Calibrations.
        
        Coordinate system. The coordinate system of the pixels refers to the position within the numpy array.
        For 1d data, this means that channel 0 is the first channel. For 2d data, this means that the pixel
        coordinate 0, 0 is at the top left, within increasing y moving downward and increasing x moving right.
        For 3d data, this means that the first coordinate specifies the depth with 0 considered to be the "top".
        The next two coordinates are y, x with 0, 0 at the top left of each layer.

        Cached data.
    """

    def __init__(self, data=None, item_uuid=None, create_display=True):
        super(DataItem, self).__init__()
        self.uuid = item_uuid if item_uuid else self.uuid
        self.min_reader_version = 4  # minimum version required to read this version when written
        self.writer_version = 4  # writes this version
        self.reader_version = 4  # won't read versions older than this
        self.__transaction_count = 0
        self.__transaction_count_mutex = threading.RLock()
        self.managed_object_context = None
        has_master_data = data is not None
        master_data_shape = data.shape if has_master_data else None
        master_data_dtype = data.dtype if has_master_data else None
        current_datetime_item = Utility.get_current_datetime_item()
        spatial_calibrations = CalibrationList()
        class DtypeToStringConverter(object):
            def convert(self, value):
                return str(value) if value is not None else None
            def convert_back(self, value):
                return numpy.dtype(value) if value is not None else None
        self.define_property("master_data_shape", master_data_shape, changed=self.__property_changed)
        self.define_property("master_data_dtype", master_data_dtype, converter=DtypeToStringConverter(), changed=self.__property_changed)
        self.define_property("intrinsic_intensity_calibration", Calibration.Calibration(), make=Calibration.Calibration, changed=self.__intrinsic_intensity_calibration_changed)
        self.define_property("intrinsic_spatial_calibrations", spatial_calibrations, make=CalibrationList, changed=self.__intrinsic_spatial_calibrations_changed)
        self.define_property("datetime_original", current_datetime_item, validate=self.__validate_datetime, changed=self.__metadata_property_changed)
        self.define_property("datetime_modified", current_datetime_item, validate=self.__validate_datetime, changed=self.__metadata_property_changed)
        self.define_property("title", _("Untitled"), validate=self.__validate_title, changed=self.__metadata_property_changed)
        self.define_property("caption", unicode(), validate=self.__validate_caption, changed=self.__metadata_property_changed)
        self.define_property("rating", 0, validate=self.__validate_rating, changed=self.__metadata_property_changed)
        self.define_property("flag", 0, validate=self.__validate_flag, changed=self.__metadata_property_changed)
        self.define_property("source_file_path", validate=self.__validate_source_file_path, changed=self.__property_changed)
        self.define_property("session_id", validate=self.__validate_session_id, changed=self.__session_id_changed)
        self.define_property("data_source_uuid_list", DataSourceUuidList(), make=DataSourceUuidList, key="data_sources")
        self.define_relationship("operations", Operation.operation_item_factory, insert=self.__insert_operation, remove=self.__remove_operation)
        self.define_relationship("displays", Display.display_factory, insert=self.__insert_display, remove=self.__remove_display)
        self.define_relationship("regions", Region.region_factory, insert=self.__insert_region, remove=self.__remove_region)
        self.__metadata = dict()
        self.closed = False
        # data is immutable but metadata isn't, keep track of original and modified dates
        self.__data_mutex = threading.RLock()
        self.__get_data_mutex = threading.RLock()
        self.__cached_data = None
        self.__cached_data_dirty = True
        # master data shape and dtype are cached to avoid loading data.
        self.__master_data = None
        self.__data_sources = []
        self.__data_ref_count = 0
        self.__data_ref_count_mutex = threading.RLock()
        self.__data_item_change_mutex = threading.RLock()
        self.__data_item_change_count = 0
        self.__data_item_changes = set()
        self.__shared_thread_pool = ThreadPool.create_thread_queue()
        self.__processors = dict()
        self.__processors["statistics"] = StatisticsDataItemProcessor(self)
        if data is not None:
            self.__set_master_data(data)
            self.sync_intrinsic_spatial_calibrations()
        # create a display if requested
        if create_display:
            self.add_display(Display.Display())  # always have one display, for now

    def __str__(self):
        return "{0} {1} ({2}, {3})".format(self.__repr__(), (self.title if self.title else _("Untitled")), str(self.uuid), self.datetime_original_as_string)

    def __deepcopy__(self, memo):
        data_item_copy = DataItem(create_display=False)
        # metadata
        data_item_copy.copy_metadata_from(self)
        # calibrations
        data_item_copy.intrinsic_intensity_calibration = self.intrinsic_intensity_calibration
        data_item_copy.intrinsic_spatial_calibrations = self.intrinsic_spatial_calibrations
        # displays
        for display in self.displays:
            data_item_copy.add_display(copy.deepcopy(display))
        # operations
        for operation in self.operations:
            data_item_copy.add_operation(copy.deepcopy(operation))
        # data sources
        data_item_copy.data_source_uuid_list = self.data_source_uuid_list
        # data.
        if self.has_master_data:
            with self.data_ref() as data_ref:
                data_item_copy.__set_master_data(numpy.copy(data_ref.master_data))
        else:
            data_item_copy.__set_master_data(None)
        # the data source connection will be established when this copy is inserted.
        memo[id(self)] = data_item_copy
        return data_item_copy

    def close(self):
        """ Optional method to close the data item. """
        for processor in self.__processors.values():
            processor.close()

    def copy_metadata_from(self, data_item):
        self.datetime_original = data_item.datetime_original
        self.datetime_modified = data_item.datetime_modified
        self.title = data_item.title
        self.caption = data_item.caption
        self.rating = data_item.rating
        self.flag = data_item.flag
        self.session_id = data_item.session_id
        self.source_file_path = data_item.source_file_path
        for key in data_item.__metadata.keys():
            with self.open_metadata(key) as metadata:
                metadata.clear()
                metadata.update(data_item.get_metadata(key))

    def snapshot(self):
        """
            Take a snapshot and return a new data item. A snapshot is a copy of everything
            except the data and operations which are replaced by new data with the operations
            applied or "burned in".
        """
        data_item_copy = DataItem(create_display=False)
        # metadata
        data_item_copy.copy_metadata_from(self)
        # calibrations
        data_item_copy.set_intensity_calibration(self.calculated_intensity_calibration)
        for index in xrange(len(self.spatial_shape)):
            data_item_copy.set_spatial_calibration(index, self.calculated_calibrations[index])
        # displays
        for display in self.displays:
            data_item_copy.add_display(copy.deepcopy(display))
        # data sources are NOT copied, since this is a snapshot of the data
        data_item_copy.data_source_uuid_list = DataSourceUuidList()
        # master data. operations are NOT copied, since this is a snapshot of the data
        with self.data_ref() as data_ref:
            data_copy = numpy.copy(data_ref.data)
            data_item_copy.__set_master_data(data_copy)
        return data_item_copy

    def about_to_be_removed(self):
        """ Tell contained objects that this data item is about to be removed from its container. """
        for operation in self.operations:
            operation.about_to_be_removed()
        for region in self.regions:
            region.about_to_be_removed()
        for display in self.displays:
            display.about_to_be_removed()

    def storage_cache_changed(self, storage_cache):
        # override from Cacheable to update the children that need updating
        for display in self.displays:
            display.storage_cache = storage_cache

    def _is_cache_delayed(self):
        """ Override from Cacheable base class to indicate when caching is delayed. """
        return self.__transaction_count > 0

    def transaction(self):
        """ Return a context manager to put the data item under a 'transaction'. """
        class TransactionContextManager(object):
            def __init__(self, object):
                self.__object = object
            def __enter__(self):
                self.__object.begin_transaction()
                return self
            def __exit__(self, type, value, traceback):
                self.__object.end_transaction()
        return TransactionContextManager(self)

    def begin_transaction(self, count=1):
        #logging.debug("begin transaction %s %s", self.uuid, self.__transaction_count)
        assert count > 0
        with self.__transaction_count_mutex:
            self.__transaction_count += count

    def end_transaction(self, count=1):
        assert count > 0
        with self.__transaction_count_mutex:
            self.__transaction_count -= count
            assert self.__transaction_count >= 0
            transaction_count = self.__transaction_count
        if transaction_count == 0:
            self.spill_cache()
            if self.managed_object_context:
                self.managed_object_context.rewrite_data_item_data(self, self.__master_data)
        #logging.debug("end transaction %s %s", self.uuid, self.__transaction_count)

    def get_data_file_info(self):
        if self.managed_object_context:
            return self.managed_object_context.get_data_item_file_info(self)
        return None, None

    # access properties

    def read_from_dict(self, properties):
        super(DataItem, self).read_from_dict(properties)
        for key in properties.keys():
            if key not in self.key_names and key not in self.relationship_names and key not in ("uuid", "reader_version", "version"):
                self.__metadata.setdefault(key, dict()).update(properties[key])

    def write_to_dict(self):
        # override from Observable to add the metadata to the properties
        properties = super(DataItem, self).write_to_dict()
        for key in self.__metadata:
            properties[key] = self.__metadata[key]
        return properties

    def __get_properties(self):
        """ Used for debugging. """
        if self.managed_object_context:
            return self.managed_object_context.get_properties(self)
        return dict()
    properties = property(__get_properties)

    def add_shared_task(self, task_id, item, fn):
        self.__shared_thread_pool.add_task(task_id, item, fn)

    def get_processor(self, processor_id):
        return self.__processors[processor_id]

    def __get_is_live(self):
        """ Return whether this data item represents a live acquisition data item. """
        return self.__transaction_count > 0
    is_live = property(__get_is_live)

    def __validate_session_id(self, value):
        assert value is None or datetime.datetime.strptime(value, "%Y%m%d-%H%M%S")
        return value

    def __session_id_changed(self, name, value):
        self.__property_changed(name, value)

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

    def __validate_datetime(self, value):
        return copy.deepcopy(value)

    def __validate_title(self, value):
        return unicode(value)

    def __validate_caption(self, value):
        return unicode(value)

    def __validate_flag(self, value):
        return max(min(int(value), 1), -1)

    def __validate_rating(self, value):
        return min(max(int(value), 0), 5)

    def __validate_source_file_path(self, value):
        value = unicode(value)
        if value:
            value = os.path.normpath(value)
        return unicode(value)

    def __intrinsic_intensity_calibration_changed(self, name, value):
        self.notify_set_property(name, value)
        self.notify_data_item_content_changed(set([METADATA]))
        self.notify_listeners("data_item_calibration_changed")

    def __metadata_property_changed(self, name, value):
        self.__property_changed(name, value)
        self.__metadata_changed()

    def __metadata_changed(self):
        self.notify_data_item_content_changed(set([METADATA]))

    def __property_changed(self, name, value):
        self.notify_set_property(name, value)

    # call this when the listeners need to be updated (via data_item_content_changed).
    # Calling this method will send the data_item_content_changed method to each listener.
    def notify_data_item_content_changed(self, changes):
        with self.data_item_changes():
            with self.__data_item_change_mutex:
                self.__data_item_changes.update(changes)

    def __get_data_range_for_data(self, data):
        if data is not None and data.size:
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

    def set_spatial_calibration(self, dimension, calibration):
        spatial_calibrations = self.intrinsic_spatial_calibrations
        while len(spatial_calibrations.list) <= dimension:
            spatial_calibrations.list.append(Calibration.Calibration())
        spatial_calibrations.list[dimension] = calibration
        self.intrinsic_spatial_calibrations = spatial_calibrations

    def __intrinsic_spatial_calibrations_changed(self, name, value):
        self.notify_data_item_content_changed(set([METADATA]))
        self.notify_listeners("data_item_calibration_changed")

    def set_intensity_calibration(self, calibration):
        self.intrinsic_intensity_calibration = calibration

    def __get_intrinsic_calibrations(self):
        return copy.deepcopy(self.intrinsic_spatial_calibrations.list)
    intrinsic_calibrations = property(__get_intrinsic_calibrations)

    def __get_calculated_intensity_calibration(self):
        data_outputs = self.data_outputs
        return data_outputs[0].calculated_intensity_calibration if len(data_outputs) == 1 else None
    calculated_intensity_calibration = property(__get_calculated_intensity_calibration)

    # call this when data changes. this makes sure that the right number
    # of intrinsic_calibrations exist in this object.
    def sync_intrinsic_spatial_calibrations(self):
        spatial_shape = self.spatial_shape
        ndim = len(spatial_shape) if spatial_shape is not None else 0
        spatial_calibrations = self.intrinsic_spatial_calibrations
        if len(spatial_calibrations.list) != ndim and not self.closed:
            while len(spatial_calibrations.list) < ndim:
                spatial_calibrations.list.append(Calibration.Calibration())
            while len(spatial_calibrations.list) > ndim:
                spatial_calibrations.list.remove(spatial_calibrations.list[-1])
            self.intrinsic_spatial_calibrations = spatial_calibrations

    # calculate the calibrations by starting with the source calibration
    # and then applying calibration transformations for each enabled
    # operation.
    def __get_calculated_calibrations(self):
        data_outputs = self.data_outputs
        return data_outputs[0].calculated_calibrations if len(data_outputs) == 1 else None
    calculated_calibrations = property(__get_calculated_calibrations)

    # date times

    def __get_datetime_original_as_string(self):
        datetime_original = self.datetime_original
        if datetime_original:
            datetime_ = Utility.get_datetime_from_datetime_item(datetime_original)
            if datetime_:
                return datetime_.strftime("%c")
        # fall through to here
        return str()
    datetime_original_as_string = property(__get_datetime_original_as_string)

    # access metadata

    def get_metadata(self, name):
        return copy.deepcopy(self.__metadata.get(name, dict()))

    def replace_metadata(self, name, metadata):
        metadata_group = self.__metadata.setdefault(name, dict())
        metadata_group.clear()
        metadata_group.update(metadata)
        if self.managed_object_context:
            self.managed_object_context.property_changed(self, name, copy.deepcopy(metadata_group))
        self.__metadata_changed()

    def open_metadata(self, name):
        metadata = self.__metadata
        metadata_changed = self.__metadata_changed
        class MetadataContextManager(object):
            def __init__(self, data_item, name):
                self.__data_item = data_item
                self.__metadata_copy = data_item.get_metadata(name)
                self.__name = name
            def __enter__(self):
                return self.__metadata_copy
            def __exit__(self, type, value, traceback):
                if self.__metadata_copy is not None:
                    self.__data_item.replace_metadata(self.__name, self.__metadata_copy)
        return MetadataContextManager(self, name)

    def __insert_display(self, name, before_index, display):
        # listen
        display.add_listener(self)
        display._set_data_item(self)
        self.notify_data_item_content_changed(set([DISPLAYS]))
        # connect the regions
        for region in self.regions:
            region_graphic = region.graphic
            if region_graphic:
                display.add_region_graphic(region_graphic)

    def __remove_display(self, name, index, display):
        # disconnect the regions
        for region in self.regions:
            region_graphic = region.graphic
            if region_graphic:
                display.remove_region_graphic(region_graphic)
        # unlisten
        self.notify_data_item_content_changed(set([DISPLAYS]))
        display.remove_listener(self)
        display._set_data_item(None)

    def add_display(self, display):
        self.append_item("displays", display)

    def remove_display(self, display):
        self.remove_item("displays", display)

    def __insert_region(self, name, before_index, region):
        # listen
        region.add_listener(self)
        region._set_data_item(self)
        self.notify_data_item_content_changed(set([DISPLAYS]))
        # connect to the displays
        region_graphic = region.graphic
        if region_graphic:
            for display in self.displays:
                display.add_region_graphic(region_graphic)

    def __remove_region(self, name, index, region):
        # disconnect from displays
        region_graphic = region.graphic
        if region_graphic:
            for display in self.displays:
                display.remove_region_graphic(region_graphic)
        # and unlisten
        self.notify_data_item_content_changed(set([DISPLAYS]))
        region.remove_listener(self)
        region._set_data_item(None)

    def add_region(self, region):
        self.append_item("regions", region)

    def remove_region(self, region):
        self.remove_item("regions", region)

    # call this when operations change or data souce changes
    # this allows operations to update their default values
    def sync_operations(self):
        data_inputs = self.data_inputs
        # apply operations
        for operation in self.operations:
            data_shapes_and_dtypes = [data_input.data_shape_and_dtype for data_input in data_inputs]
            operation.update_data_shapes_and_dtypes(data_shapes_and_dtypes)
            data_inputs = operation.get_processed_intermediate_data_items(data_inputs)

    def __insert_operation(self, name, before_index, operation):
        operation.add_listener(self)
        operation.add_observer(self)
        operation._set_data_item(self)
        self.sync_operations()
        self.notify_data_item_content_changed(set([DATA]))

    def __remove_operation(self, name, index, operation):
        self.sync_operations()
        self.notify_data_item_content_changed(set([DATA]))
        operation.remove_listener(self)
        operation.remove_observer(self)
        operation._set_data_item(None)

    def add_operation(self, operation):
        self.append_item("operations", operation)

    def remove_operation(self, operation):
        operation.about_to_be_removed()  # ugh. this is intended to notify that the data item is about to be removed from the document.
        self.remove_item("operations", operation)

    # this message comes from the operation.
    # by watching for changes to the operations relationship. when an operation
    # is added/removed, this object becomes a listener via add_listener/remove_listener.
    def operation_changed(self, operation):
        self.notify_data_item_content_changed(set([DATA]))

    # this message comes from the operation.
    # it is generated when the user deletes a operation graphic.
    # that informs the display which notifies the graphic which
    # notifies the operation which notifies this data item. ugh.
    def request_remove_data_item_because_operation_removed(self, operation):
        self.notify_listeners("request_remove_data_item", self)

    # this message comes from the region.
    # it is generated when the user deletes a graphic.
    def remove_region_because_graphic_removed(self, region):
        self.remove_region(region)

    # connect this item to its data source, if any. the lookup_data_item parameter
    # is a function to look up data items by uuid. this method also establishes the
    # display graphics for this items operations. direct data source is used for testing.
    def connect_data_sources(self, lookup_data_item=None, direct_data_sources=None):
        if direct_data_sources is not None:
            data_items = direct_data_sources
        else:
            data_items = [lookup_data_item(uuid.UUID(data_source_uuid_str)) for data_source_uuid_str in self.data_source_uuid_list.list]
        with self.__data_mutex:
            for data_source in data_items:
                if data_source is not None:
                    assert isinstance(data_source, DataItem)
                    # we will receive data_item_content_changed from data_source
                    data_source.add_listener(self)
                    self.__data_sources.append(data_source)
            self.sync_operations()
        self.data_item_content_changed(None, set([SOURCE]))

    # disconnect this item from its data source. also removes the graphics for this
    # items operations.
    def disconnect_data_sources(self):
        with self.__data_mutex:
            for data_source in copy.copy(self.__data_sources):
                data_source.remove_listener(self)
                self.__data_sources.remove(data_source)

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(DataItem, self).notify_set_property(key, value)
        self.notify_data_item_content_changed(set([METADATA]))
        for processor in self.__processors.values():
            processor.item_property_changed(key, value)

    # this message comes from the displays.
    def display_changed(self, display):
        self.notify_data_item_content_changed(set([DISPLAYS]))

    # data_item_content_changed comes from data sources to indicate that data
    # has changed. the connection is established via add_listener.
    def data_item_content_changed(self, data_source, changes):
        self.sync_intrinsic_spatial_calibrations()
        # we don't care about display changes to the data source; only data changes.
        if DATA in changes:
            # propogate to listeners
            self.notify_data_item_content_changed(changes)

    def __get_data_source(self):
        return self.__data_sources[0] if len(self.__data_sources) == 1 else None
    data_source = property(__get_data_source)

    # add a reference to the given data source
    def add_data_source(self, data_source):
        assert len(self.__data_sources) == 0  # for now we assume that this is only called before data sources are connected
        self.session_id = data_source.session_id
        data_source_uuid_list = self.data_source_uuid_list
        data_source_uuid_list.list.append(str(data_source.uuid))
        self.data_source_uuid_list = data_source_uuid_list

    # remove a reference to the given data source
    def remove_data_source(self, data_source):
        #assert len(self.__data_sources) == 0  # for now we assume that this is only called before data sources are connected
        data_source_uuid_list = self.data_source_uuid_list
        assert str(data_source.uuid) in data_source_uuid_list.list
        data_source_uuid_list.list.remove(str(data_source.uuid))
        self.data_source_uuid_list = data_source_uuid_list
        self.session_id = None

    def __get_master_data(self):
        return self.__master_data
    def __set_master_data(self, data):
        with self.data_item_changes():
            assert not self.closed or data is None
            assert (data.shape is not None) if data is not None else True  # cheap way to ensure data is an ndarray
            assert data is None or len(self.__data_sources) == 0  # can't have master data and data source
            with self.__data_mutex:
                if data is not None:
                    self.set_cached_value("master_data_shape", data.shape)
                    self.set_cached_value("master_data_dtype", data.dtype)
                else:
                    self.remove_cached_value("master_data_shape")
                    self.remove_cached_value("master_data_dtype")
                self.__master_data = data
                self.master_data_shape = data.shape if data is not None else None
                self.master_data_dtype = data.dtype if data is not None else None
                self.sync_intrinsic_spatial_calibrations()
            # tell the managed object context about it
            if self.__master_data is not None:
                if self.__transaction_count == 0:  # no race is possible here. just write it.
                    if self.managed_object_context:
                        self.managed_object_context.rewrite_data_item_data(self, self.__master_data)
                self.notify_set_property("data_range", self.data_range)
            self.notify_data_item_content_changed(set([DATA]))

    def __load_master_data(self):
        # load data from managed object context if data is not already loaded
        if self.has_master_data and self.__master_data is None:
            if self.managed_object_context:
                #logging.debug("loading %s", self)
                self.__master_data = self.managed_object_context.load_data(self)

    def __unload_master_data(self):
        # unload data if possible.
        # data cannot be unloaded if transaction count > 0 or if there is no managed object context.
        if self.__transaction_count == 0 and self.has_master_data:
            if self.managed_object_context:
                self.__master_data = None
                self.__cached_data = None
                #logging.debug("unloading %s", self)

    def increment_data_ref_count(self):
        with self.__data_ref_count_mutex:
            initial_count = self.__data_ref_count
            self.__data_ref_count += 1
            if initial_count == 0:
                for data_source in self.__data_sources:
                    data_source.increment_data_ref_count()
                self.__load_master_data()
        return initial_count+1
    def decrement_data_ref_count(self):
        with self.__data_ref_count_mutex:
            self.__data_ref_count -= 1
            final_count = self.__data_ref_count
            if final_count == 0:
                for data_source in self.__data_sources:
                    data_source.decrement_data_ref_count()
                self.__unload_master_data()
        return final_count

    # used for testing
    def __is_data_loaded(self):
        return self.has_master_data and self.__master_data is not None
    is_data_loaded = property(__is_data_loaded)

    def __get_has_master_data(self):
        return self.master_data_shape is not None and self.master_data_dtype is not None
    has_master_data = property(__get_has_master_data)

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
        with self.__data_mutex:
            is_dirty = self.__cached_data_dirty or self.__cached_data is None
        if is_dirty:
            # this SHOULD NOT happen under the 'data mutex'. it can take a long time.
            # however, it SHOULD happen under the 'get data mutex' to prevent it from
            # being calculated simulataneously more than once.
            with self.__get_data_mutex:
                data_outputs = self.data_outputs
                data = data_outputs[0].data if len(data_outputs) == 1 else None
                self.__get_data_range_for_data(data)
            with self.__data_mutex:
                self.__cached_data = data
                self.__cached_data_dirty = False
        return self.__cached_data

    def __get_data_inputs(self):
        """ Returns a copy of the data inputs """
        data_inputs = []
        if self.has_master_data:
            data_inputs.append(IntermediateDataItem(self,
                                                    (self.master_data_shape, self.master_data_dtype),
                                                    copy.deepcopy(self.intrinsic_intensity_calibration),
                                                    copy.deepcopy(self.intrinsic_calibrations)))
        data_inputs.extend(copy.copy(self.__data_sources))
        return data_inputs
    data_inputs = property(__get_data_inputs)

    def __get_data_outputs(self):
        with self.__data_mutex:
            data_inputs = self.data_inputs
             # apply operations
            for operation in self.operations:
                data_inputs = operation.get_processed_intermediate_data_items(data_inputs)
            return data_inputs
    data_outputs = property(__get_data_outputs)

    def __get_data_shape_and_dtype(self):
        data_outputs = self.data_outputs
        return data_outputs[0].data_shape_and_dtype if len(data_outputs) == 1 else (None, None)
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
        data_shape_and_dtype = self.data_shape_and_dtype
        if data_shape_and_dtype:
            data_shape, data_dtype = self.data_shape_and_dtype
            return Image.spatial_shape_from_shape_and_dtype(data_shape, data_dtype)
        return None
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


_computation_fns = list()

def register_data_item_computation(computation_fn):
    global _computation_fns
    _computation_fns.append(computation_fn)

def unregister_data_item_computation(self, computation_fn):
    pass
