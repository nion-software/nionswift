# standard libraries
import copy
import datetime
import gettext
import itertools
import logging
import os
import threading
import uuid
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import Connection
from nion.swift.model import DataItemProcessor
from nion.swift.model import Display
from nion.swift.model import Image
from nion.swift.model import Operation
from nion.swift.model import Region
from nion.swift.model import Storage
from nion.swift.model import Utility
from nion.ui import Observable

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

    def __init__(self, calibrations=None):
        self.list = list() if calibrations is None else copy.deepcopy(calibrations)

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


"""
    Data sources are interfaces to get data and metadata.

    *Primary Properties*

    * data_shape_and_dtype
    * intensity_calibration
    * dimensional_calibrations
    * data

    *Derived Properties*
    * data_shape
    * data_dtype

    *Secondary Functionality*

    Data sources can only be associated in their operation tree of a single data item. The data source
    keeps track of that so as to maintain the dependent_data_item list on data items.

    set_dependent_data_item(data_item)

    *Notifications*

    Data items will emit the following notifications to listeners. Listeners should take care to not call
     functions which result in cycles of notifications. For instance, functions handling data_item_content_changed
     should not read the data property (although cached_data is ok) since calling data may trigger the data
     to be computed which will emit data_item_content_changed, resulting in a cycle.

    * data_source_content_changed(data_source, changes)
    * data_source_needs_recompute(data_source)

    data_source_content_changed is invoked when the content of the data source changes. The changes parameter is a set
    of changes from DATA, METADATA, DISPLAYS, SOURCE. This may be called on a thread.

    data_source_needs_recompute is invoked when a recompute of the data source is necessary. This can happen when an
    operation changes or when source data changes. This may be called on a thread.
"""


# enumerations for types of data item content changes
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
    Data items represent data + metadata, a description of how that data is derived, and machinery to calculate it.

    Data is represented by ndarrays; and metadata consists of things such as dimensional and intensity
     calibrations, creation and modification dates, titles, captions, etc.

    The derivation description includes a list of source data items, operation, regions, and relationships
     between data/metadata (connections).

    The following direct properties are available:

    * *data* an ndarray. see note about accessing data below.
    * *data_shape* an ndarray shape
    * *data_dtype* an ndarray shape
    * *cached_data* an ndarray. see note about accessing data below.

    and

    * *dimension_calibrations* a list of calibrations
    * *intensity_calibration* a calibration
    * *datetime_created* a datetime item
    * *datetime_modified* a datetime item
    * *title* a string (single line)
    * *caption* a string (multiple lines)
    * *rating* an integer star rating (0 to 5)
    * *flag* a flag (-1, 0, 1)
    * *session_id* a string representing the session
    * *regions* a list of regions
    * *connections* a list of connections between objects
    * *operation* an operation describing how to compute this data item

    In addition to the properties above, data items may contain a list of displays. By convention, displays
     are only associated with "top level" data items.

    * *displays* a list of displays associated with the data item.

    Accessing data can be done directly via the data property. However, this may cause data to be loaded
     into memory from disk and unloaded every time the data property is used.

    A better way to access data if it will be used more than once is to ask for a data reference via the
     data_ref() method which returns a context manager object. When the context manager object is released,
     the data will be unloaded from memory if it is not used somewhere else. The context manager has a
     master_data property to access the data.

    Furthermore, data accessed via the data property will always return the fully computed data. If data
     sources are out of date, they will be updated and accessing the data property will not return until
     all data sources have valid data. This can cause lengthy blocks on the calling thread.

    An alternative accessor is cached_data which will return the most recently computed data, which may be
     None. However, it is guaranteed to not block the calling thread.

    *Notifications*

    Data items will emit the following notifications to listeners. Listeners should take care to not call
     functions which result in cycles of notifications. For instance, functions handling data_item_content_changed
     should not read the data property (although cached_data is ok) since calling data may trigger the data
     to be computed which will emit data_item_content_changed, resulting in a cycle.

    * data_item_content_changed(data_item, changes)
    * data_item_needs_recompute(data_item)
    * data_item_calibration_changed()
    * request_remove_data_item(data_item)

    data_item_content_changed is invoked when the content of the data item changes. The changes parameter is a set
    of changes from DATA, METADATA, DISPLAYS, SOURCE. This may be called on a thread.

    data_item_needs_recompute is invoked when a recompute of the data is necessary. This can happen when an operation
    changes or when source data changes. This may be called on a thread.

    TODO: merge usage of data_item_calibration_changed with data_item_content_changed.

    request_remove_data_item is invoked when a region associated with an operation is removed by the user. This
    message can be used to remove the associated dependent data item. This will not be called from a thread.

    *Stale Data*

    Cached data can be stale. When a data source or becomes stale or has its data changed, this data item
     will be marked as having stale data. When this items data becomes stale, the
     data_needs_recompute notification will be sent to listeners. In addition, processors will be marked
     as having stale data.

    Data stale-ness propagates to all listeners. This ensures that if a data changed notification is
     not sent out for some reason then the dependent still knows to update.

    *Processors*

    Data stale-ness propagates to processors.

    *Miscellaneous*

    Operation. An OperationItem describing how to compute data for this data item.

    Transactions.

    Live-ness.

    Snapshots and deep copies.

    Properties.

    Metadata.

    Data range. Cached value for data min/max. Calculated when data is requested, or on demand.

    Data values.

    Calibrations.

    Coordinate system. The coordinate system of the pixels refers to the position within the numpy array.
     For 1d data, this means that channel 0 is the first channel. For 2d data, this means that the pixel
     coordinate 0, 0 is at the top left, within increasing y moving downward and increasing x moving right.
     For 3d data, this means that the first coordinate specifies the depth with 0 considered to be the "top".
     The next two coordinates are y, x with 0, 0 at the top left of each layer.
    """

    def __init__(self, data=None, item_uuid=None, create_display=True):
        super(DataItem, self).__init__()
        self.uuid = item_uuid if item_uuid else self.uuid
        self.writer_version = 6  # writes this version
        self.__transaction_count = 0
        self.__transaction_count_mutex = threading.RLock()
        self.managed_object_context = None
        has_master_data = data is not None
        master_data_shape = data.shape if has_master_data else None
        master_data_dtype = data.dtype if has_master_data else None
        current_datetime_item = Utility.get_current_datetime_item()
        dimensional_calibrations = CalibrationList()
        class DtypeToStringConverter(object):
            def convert(self, value):
                return str(value) if value is not None else None
            def convert_back(self, value):
                return numpy.dtype(value) if value is not None else None
        self.define_property("master_data_shape", master_data_shape, changed=self.__property_changed)
        self.define_property("master_data_dtype", master_data_dtype, converter=DtypeToStringConverter(), changed=self.__property_changed)
        # TODO: file format rename calibrations to match property names
        self.define_property("intensity_calibration", Calibration.Calibration(), hidden=True, make=Calibration.Calibration, changed=self.__intensity_calibration_changed, key="intrinsic_intensity_calibration")
        self.define_property("dimensional_calibrations", dimensional_calibrations, hidden=True, make=CalibrationList, changed=self.__dimensional_calibrations_changed, key="intrinsic_spatial_calibrations")
        self.define_property("datetime_original", current_datetime_item, validate=self.__validate_datetime, changed=self.__metadata_property_changed)
        self.define_property("datetime_modified", current_datetime_item, validate=self.__validate_datetime, changed=self.__metadata_property_changed)
        self.define_property("title", _("Untitled"), validate=self.__validate_title, changed=self.__metadata_property_changed)
        self.define_property("caption", unicode(), validate=self.__validate_caption, changed=self.__metadata_property_changed)
        self.define_property("rating", 0, validate=self.__validate_rating, changed=self.__metadata_property_changed)
        self.define_property("flag", 0, validate=self.__validate_flag, changed=self.__metadata_property_changed)
        self.define_property("source_file_path", validate=self.__validate_source_file_path, changed=self.__property_changed)
        self.define_property("session_id", validate=self.__validate_session_id, changed=self.__session_id_changed)
        self.define_item("operation", Operation.operation_item_factory, item_changed=self.__operation_item_changed)
        self.define_relationship("displays", Display.display_factory, insert=self.__insert_display, remove=self.__remove_display)
        self.define_relationship("regions", Region.region_factory, insert=self.__insert_region, remove=self.__remove_region)
        self.define_relationship("connections", Connection.connection_factory, insert=self.__insert_connection, remove=self.__remove_connection)
        self.__live_count = 0  # specially handled property
        self.__live_count_lock = threading.RLock()
        self.__metadata = dict()
        self.__metadata_lock = threading.RLock()
        self.__master_data = None
        self.__master_data_lock = threading.RLock()
        self.__is_master_data_stale = True
        self.__is_master_data_stale_lock = threading.RLock()
        self.__data_ref_count = 0
        self.__data_ref_count_mutex = threading.RLock()
        self.__data_item_change_count = 0
        self.__data_item_change_count_lock = threading.RLock()
        self.__data_item_changes = set()
        self.__data_item_manager = None
        self.__data_item_manager_lock = threading.RLock()
        self.__dependent_data_item_refs = list()
        self.__processors = dict()
        self.__processors["statistics"] = StatisticsDataItemProcessor(self)
        if data is not None:
            self.__set_master_data(data)
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
        data_item_copy.set_intensity_calibration(self.intensity_calibration)
        data_item_copy.set_dimensional_calibrations(self.dimensional_calibrations)
        # displays
        for display in self.displays:
            data_item_copy.add_display(copy.deepcopy(display))
        # operation
        if self.operation:
            data_item_copy.set_operation(copy.deepcopy(self.operation))
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
        for display in self.displays:
            display.remove_listener(self)
            display._set_data_item(None)
            display.close()
        for processor in self.__processors.values():
            processor.close()
        self.__processors = None

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
            except the data and operation which are replaced by new data with the operation
            applied or "burned in".
        """
        data_item_copy = DataItem(create_display=False)
        # metadata
        data_item_copy.copy_metadata_from(self)
        # calibrations
        data_item_copy.set_intensity_calibration(self.intensity_calibration)
        for index in xrange(len(self.spatial_shape)):
            data_item_copy.set_dimensional_calibration(index, self.dimensional_calibrations[index])
        # displays
        for display in self.displays:
            data_item_copy.add_display(copy.deepcopy(display))
        # master data. operation is NOT copied, since this is a snapshot of the data
        data_item_copy.__set_master_data(numpy.copy(self.data))
        return data_item_copy

    def about_to_be_removed(self):
        """ Tell contained objects that this data item is about to be removed from its container. """
        for connection in self.connections:
            connection.about_to_be_removed()
        if self.operation:
            self.operation.about_to_be_removed()
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

    def __get_transaction_count(self):
        """ Return the transaction count for this data item. """
        return self.__transaction_count
    transaction_count = property(__get_transaction_count)

    def begin_transaction(self, count=1):
        #logging.debug("begin transaction %s %s", self.uuid, self.__transaction_count)
        assert count > 0
        with self.__transaction_count_mutex:
            old_transaction_count = self.__transaction_count
            self.__transaction_count += count
        if old_transaction_count == 0:
            if self.managed_object_context:
                persistent_storage = self.managed_object_context.get_persistent_storage_for_object(self)
                if persistent_storage:
                    persistent_storage.write_delayed = True
        for data_item in self.dependent_data_items:
            data_item.begin_transaction(count)

    def end_transaction(self, count=1):
        assert count > 0
        for data_item in self.dependent_data_items:
            data_item.end_transaction(count)
        with self.__transaction_count_mutex:
            self.__transaction_count -= count
            assert self.__transaction_count >= 0
            transaction_count = self.__transaction_count
        if transaction_count == 0:
            self.spill_cache()
            if self.managed_object_context:
                persistent_storage = self.managed_object_context.get_persistent_storage_for_object(self)
                if persistent_storage:
                    persistent_storage.write_delayed = False
                self.managed_object_context.write_data_item(self)
        #logging.debug("end transaction %s %s", self.uuid, self.__transaction_count)

    def managed_object_context_changed(self):
        # handle case where managed object context is set on an item that is already under transaction
        super(DataItem, self).managed_object_context_changed()
        if self.__transaction_count > 0 and self.managed_object_context:
            persistent_storage = self.managed_object_context.get_persistent_storage_for_object(self)
            if persistent_storage:
                persistent_storage.write_delayed = True

    def get_data_file_info(self):
        if self.managed_object_context:
            return self.managed_object_context.get_data_item_file_info(self)
        return None, None

    # access properties

    def read_from_dict(self, properties):
        # when reading, handle changes specially. first, put everything into a change
        # block; then make sure that no change notifications actually occur. this makes
        # sure things like cached values are preserved after reading.
        with self.data_item_changes():
            super(DataItem, self).read_from_dict(properties)
            for key in properties.keys():
                if key not in self.key_names and key not in self.relationship_names and key not in ("uuid", "reader_version", "version"):
                    metadata = properties[key]
                    if isinstance(metadata, dict):
                        self.__metadata.setdefault(key, dict()).update(metadata)
            self.__data_item_changes = set()

    def write_to_dict(self):
        # override from Observable to add the metadata to the properties
        properties = super(DataItem, self).write_to_dict()
        for key in self.__metadata:
            properties[key] = self.__metadata[key]
        return properties

    def finish_reading(self):
        # called when reading is finished. gives the data item a chance to
        # mark its data as valid.
        if self.has_master_data:
            with self.__is_master_data_stale_lock:
                self.__is_master_data_stale = False
        super(DataItem, self).finish_reading()

    def __get_properties(self):
        """ Used for debugging. """
        if self.managed_object_context:
            return self.managed_object_context.get_properties(self)
        return dict()
    properties = property(__get_properties)

    def get_processor(self, processor_id):
        return self.__processors[processor_id]

    def get_processed_data(self, processor_id):
        return self.get_processor(processor_id).get_cached_data()

    # called from processors
    def notify_processor_needs_recompute(self, processor):
        self.notify_listeners("data_item_processor_needs_recompute", self, processor)

    # called from processors
    def notify_processor_data_updated(self, processor):
        self.notify_listeners("data_item_processor_data_updated", self, processor)

    def __get_is_live(self):
        """ Return whether this data item represents a live acquisition data item. """
        return self.__live_count > 0
    is_live = property(__get_is_live)

    def live(self):
        """ Return a context manager to put the data item under a live count. """
        class LiveContextManager(object):
            def __init__(self, object):
                self.__object = object
            def __enter__(self):
                self.__object.begin_live()
                return self
            def __exit__(self, type, value, traceback):
                self.__object.end_live()
        return LiveContextManager(self)

    def __get_live_count(self):
        """ Return the live count for this data item. """
        return self.__live_count
    live_count = property(__get_live_count)

    def begin_live(self, count=1):
        """
        Begins a live transaction with this item. The live-ness property is propagated to
        dependent data items, similar to the transactions.
        """
        assert count > 0
        with self.__live_count_lock:
            old_live_count = self.__live_count
            self.__live_count += count
        if old_live_count == 0:
            self.notify_data_item_content_changed(set([METADATA]))  # this will affect is_live, so notify
        for data_item in self.dependent_data_items:
            data_item.begin_live(count)

    def end_live(self, count=1):
        """
        Ends a live transaction with this item. The live-ness property is propagated to
        dependent data items, similar to the transactions.
        """
        assert count > 0
        for data_item in self.dependent_data_items:
            data_item.end_live(count)
        with self.__live_count_lock:
            self.__live_count -= count
            assert self.__live_count >= 0
            live_count = self.__live_count
        if live_count == 0:
            self.notify_data_item_content_changed(set([METADATA]))  # this will affect is_live, so notify

    def __validate_session_id(self, value):
        assert value is None or datetime.datetime.strptime(value, "%Y%m%d-%H%M%S")
        return value

    def __session_id_changed(self, name, value):
        self.__property_changed(name, value)

    def data_item_changes(self):
        # return a context manager to batch up a set of changes so that listeners
        # are only notified after the last change is complete.
        data_item = self
        class DataItemChangeContextManager(object):
            def __enter__(self):
                data_item.begin_data_item_changes()
                return self
            def __exit__(self, type, value, traceback):
                data_item.end_data_item_changes()
        return DataItemChangeContextManager()

    def begin_data_item_changes(self):
        with self.__data_item_change_count_lock:
            self.__data_item_change_count += 1

    def end_data_item_changes(self):
        with self.__data_item_change_count_lock:
            self.__data_item_change_count -= 1
            data_item_change_count = self.__data_item_change_count
            if data_item_change_count == 0:
                changes = self.__data_item_changes
                self.__data_item_changes = set()
        # if the data item change count is now zero, it means that we're ready
        # to notify listeners. but only notify listeners if there are actual
        # changes to report.
        if data_item_change_count == 0 and len(changes) > 0:
            for processor in self.__processors.values():
                processor.data_item_changed()
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
            with self.__data_item_change_count_lock:
                self.__data_item_changes.update(changes)

    def __calculate_data_range_for_data(self, data):
        if data is not None and data.size:
            if Image.is_shape_and_dtype_rgb_type(data.shape, data.dtype):
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
        return self.get_cached_value("data_range")
    data_range = property(__get_data_range)

    # calibration stuff

    @property
    def intensity_calibration(self):
        """ Return the intensity calibration. """
        try:
            if self.is_data_stale:
                if self.operation:
                    return self.operation.intensity_calibration
            return copy.deepcopy(self._get_managed_property("intensity_calibration"))
        except Exception as e:
            import traceback
            traceback.print_exc()
            traceback.print_stack()
            raise

    @property
    def dimensional_calibrations(self):
        """ Return the dimensional calibrations as a list. """
        try:
            if self.is_data_stale:
                if self.operation:
                    return self.operation.dimensional_calibrations
            return copy.deepcopy(self._get_managed_property("dimensional_calibrations").list)
        except Exception as e:
            import traceback
            traceback.print_exc()
            traceback.print_stack()
            raise

    def set_intensity_calibration(self, calibration):
        """ Set the intenisty calibration. """
        self._set_managed_property("intensity_calibration", calibration)

    def set_dimensional_calibrations(self, dimensional_calibrations):
        """ Set the dimensional calibrations. """
        self._set_managed_property("dimensional_calibrations", CalibrationList(dimensional_calibrations))

    def set_dimensional_calibration(self, dimension, calibration):
        dimensional_calibrations = self.dimensional_calibrations
        while len(dimensional_calibrations) <= dimension:
            dimensional_calibrations.append(Calibration.Calibration())
        dimensional_calibrations[dimension] = calibration
        self.set_dimensional_calibrations(dimensional_calibrations)

    def __intensity_calibration_changed(self, name, value):
        self.notify_set_property(name, value)
        self.notify_data_item_content_changed(set([METADATA]))
        self.notify_listeners("data_item_calibration_changed")

    def __dimensional_calibrations_changed(self, name, value):
        self.notify_data_item_content_changed(set([METADATA]))
        self.notify_listeners("data_item_calibration_changed")

    # call this when data changes. this makes sure that the right number
    # of dimensional_calibrations exist in this object.
    def __sync_dimensional_calibrations(self, ndim):
        dimensional_calibrations = self.dimensional_calibrations
        if len(dimensional_calibrations) != ndim:
            while len(dimensional_calibrations) < ndim:
                dimensional_calibrations.append(Calibration.Calibration())
            while len(dimensional_calibrations) > ndim:
                dimensional_calibrations.remove(dimensional_calibrations[-1])
            self.set_dimensional_calibrations(dimensional_calibrations)

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
        with self.__metadata_lock:
            return copy.deepcopy(self.__metadata.get(name, dict()))

    def replace_metadata(self, name, metadata):
        with self.__metadata_lock:
            metadata_group = self.__metadata.setdefault(name, dict())
            metadata_group.clear()
            metadata_group.update(metadata)
            metadata_group_copy = copy.deepcopy(metadata_group)
        if self.managed_object_context:
            self.managed_object_context.property_changed(self, name, metadata_group_copy)
        self.__metadata_changed()

    def open_metadata(self, name):
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
        display.close()

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

    def __insert_connection(self, name, before_index, connection):
        # listen
        connection.add_listener(self)
        connection._set_data_item(self)

    def __remove_connection(self, name, index, connection):
        # unlisten
        connection.remove_listener(self)
        connection._set_data_item(None)

    def add_connection(self, connection):
        self.append_item("connections", connection)

    def remove_connection(self, connection):
        self.remove_item("connections", connection)

    # call this when the operation changes or data source changes
    # this allows the operation tree to update default values
    def __sync_operation(self):
        # apply the operation
        if self.operation:
            self.operation.update_data_shapes_and_dtypes()

    def set_operation(self, operation):
        self.set_item("operation", operation)

    @property
    def ordered_operations(self):
        if self.operation:
            return [self.operation]
        else:
            return []

    @property
    def ordered_data_item_data_sources(self):
        if self.operation:
            return self.operation.ordered_data_item_data_sources
        else:
            return []

    def __operation_item_changed(self, name, old_value, new_value):
        # and about to be removed messages
        if old_value and not new_value:
            old_value.about_to_be_removed()  # ugh. this is intended to notify that the data item is about to be removed from the document.
        if old_value:
            # generate changed messages (temporary)
            self.notify_listeners("item_removed", self, "ordered_operations", old_value, 0)
            # handle listeners/observers
            old_value.remove_listener(self)
            old_value.remove_observer(self)
            old_value.set_dependent_data_item(None)
            old_value.set_data_item_manager(None)
        if new_value:
            # generate changed messages (temporary)
            self.notify_listeners("item_inserted", self, "ordered_operations", new_value, 0)
            # handle listeners/observers
            new_value.add_listener(self)
            new_value.add_observer(self)
            new_value.set_dependent_data_item(self)
            new_value.set_data_item_manager(self.__data_item_manager)
        self.__sync_operation()
        self.notify_data_item_content_changed(set([DATA]))
        if not self._is_reading:
            self.__mark_data_stale()

    # this message comes from the operation.
    def operation_changed(self, operation):
        if not self._is_reading:
            self.__mark_data_stale()

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

    def set_data_item_manager(self, data_item_manager):
        """Set the data item manager. May be called from thread."""
        with self.__data_item_manager_lock:
            self.__data_item_manager = data_item_manager
            if self.operation:
                self.operation.set_data_item_manager(self.__data_item_manager)

    # track dependent data items. useful for propagating transaction support.
    def add_dependent_data_item(self, data_item):
        self.__dependent_data_item_refs.append(weakref.ref(data_item))
        if self.__transaction_count > 0:
            data_item.begin_transaction(self.__transaction_count)
        if self.__live_count > 0:
            data_item.begin_live(self.__live_count)

    # track dependent data items. useful for propagating transaction support.
    def remove_dependent_data_item(self, data_item):
        self.__dependent_data_item_refs.remove(weakref.ref(data_item))
        if self.__transaction_count > 0:
            data_item.end_transaction(self.__transaction_count)
        if self.__live_count > 0:
            data_item.end_live(self.__live_count)

    def __get_dependent_data_items(self):
        return [data_item_ref() for data_item_ref in self.__dependent_data_item_refs]
    dependent_data_items = property(__get_dependent_data_items)

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(DataItem, self).notify_set_property(key, value)
        self.notify_data_item_content_changed(set([METADATA]))
        for processor in self.__processors.values():
            processor.item_property_changed(key, value)

    # this message comes from the displays.
    # thread safe
    def display_changed(self, display):
        self.notify_data_item_content_changed(set([DISPLAYS]))

    # data_item_content_changed comes from data sources to indicate that data
    # has changed. the connection is established via add_listener.
    def data_source_content_changed(self, data_source, changes):
        if DATA in changes or SOURCE in changes:
            self.__mark_data_stale()

    # data_item_needs_recompute comes from data sources to indicate that data has
    # become stale. the connection is established via add_listener.
    def data_source_needs_recompute(self, data_source):
        self.__mark_data_stale()

    def __get_master_data(self):
        with self.__master_data_lock:
            return self.__master_data
    def __set_master_data(self, data):
        with self.data_item_changes():
            assert (data.shape is not None) if data is not None else True  # cheap way to ensure data is an ndarray
            with self.__master_data_lock:
                self.__master_data = data
                with self.__is_master_data_stale_lock:
                    self.__is_master_data_stale = False
                self.master_data_shape = data.shape if data is not None else None
                self.master_data_dtype = data.dtype if data is not None else None
                spatial_shape = Image.spatial_shape_from_shape_and_dtype(self.master_data_shape, self.master_data_dtype)
                self.__sync_dimensional_calibrations(len(spatial_shape) if spatial_shape is not None else 0)
                self.__calculate_data_range_for_data(data)
            # tell the managed object context about it
            if self.__master_data is not None:
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
                #logging.debug("unloading %s", self)

    def increment_data_ref_count(self):
        with self.__data_ref_count_mutex:
            initial_count = self.__data_ref_count
            self.__data_ref_count += 1
            if initial_count == 0:
                self.__load_master_data()
        return initial_count+1

    def decrement_data_ref_count(self):
        with self.__data_ref_count_mutex:
            self.__data_ref_count -= 1
            final_count = self.__data_ref_count
            if final_count == 0:
                self.__unload_master_data()
        return final_count

    @property
    def is_data_stale(self):
        """Return whether the data is currently stale."""
        return self.__is_master_data_stale

    def __mark_data_stale(self):
        """Mark the master data as stale."""
        with self.__is_master_data_stale_lock:
            self.__is_master_data_stale = True
        for processor in self.__processors.values():
            processor.data_item_changed()
        self.notify_listeners("data_item_needs_recompute", self)

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
                set_master_data(self.__data_item, get_master_data(self.__data_item))
            def __get_data(self):
                self.__data_item.recompute_data()
                return self.__get_master_data()
            data = property(__get_data)
        return DataAccessor(self)

    @property
    def data(self):
        """Return the up-to-date data for this data item.

        The data returned from this method will be the latest data and if a computation
        is in progress it will wait for the computation to complete.

        This method may block for a significant amount of time and should be avoided
        on the main thread.

        Multiple calls to access data should be bracketed in a data_ref context to
        avoid loading and unloading from disk."""
        try:
            with self.data_ref() as data_ref:
                return data_ref.data
        except Exception as e:
            import traceback
            traceback.print_exc()
            traceback.print_stack()
            raise

    @property
    def cached_data(self):
        """Return the cached data for this data item.

        The data returned from this method may not be the latest data if a computation
        is in progress.

        This method will never block and can be called from the main thread.

        Multiple calls to access data should be bracketed in a data_ref context to
        avoid loading and unloading from disk."""
        try:
            with self.data_ref() as data_ref:
                return data_ref.master_data
        except Exception as e:
            import traceback
            traceback.print_exc()
            traceback.print_stack()
            raise

    def recompute_data(self):
        """Ensures that the master data is synchronized with the sources/operation by recomputing if necessary."""

        # prevent multiple data changed notifications by surrounding everything in data_item_changes.
        # if there are no changes, then this will not trigger any notifications. it is important that the
        # notifications, if any, take place outside of the lock to prevent deadlocks.
        with self.data_item_changes():
            with self.__is_master_data_stale_lock:  # only one thread should be computing master data at once
                if self.is_data_stale:
                    operation = self.operation
                    if operation:
                        self.increment_data_ref_count()  # make sure master data is loaded
                        try:
                            self.__set_master_data(operation.data)
                        finally:
                            self.decrement_data_ref_count()  # unload master data
                        self.set_intensity_calibration(operation.intensity_calibration)
                        for index, dimensional_calibration in enumerate(operation.dimensional_calibrations):
                            self.set_dimensional_calibration(index, dimensional_calibration)
                self.__is_master_data_stale = False

    def __get_data_shape_and_dtype(self):
        if self.is_data_stale:
            if self.operation:
                return self.operation.data_shape_and_dtype
        return self.master_data_shape, self.master_data_dtype
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
        data = self.cached_data
        if self.is_data_1d:
            if data is not None:
                return data[pos[0]]
        elif self.is_data_2d:
            if data is not None:
                return data[pos[0], pos[1]]
        # TODO: fix me 3d
        elif self.is_data_3d:
            if data is not None:
                return data[pos[0], pos[1]]
        return None


_computation_fns = list()

def register_data_item_computation(computation_fn):
    global _computation_fns
    _computation_fns.append(computation_fn)

def unregister_data_item_computation(self, computation_fn):
    pass
