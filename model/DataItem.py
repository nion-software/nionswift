# futures
from __future__ import absolute_import

# standard libraries
import copy
import datetime
import functools
import gettext
import operator
import os
import threading
import time
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import Connection
from nion.swift.model import DataAndMetadata
from nion.swift.model import DataItemProcessor
from nion.swift.model import Display
from nion.swift.model import Image
from nion.swift.model import Operation
from nion.swift.model import Region
from nion.swift.model import Storage
from nion.swift.model import Symbolic
from nion.ui import Observable
from nion.ui import Unicode

_ = gettext.gettext

UNTITLED_STR = _("Untitled")


class StatisticsDataItemProcessor(DataItemProcessor.DataItemProcessor):

    def __init__(self, buffered_data_source):
        super(StatisticsDataItemProcessor, self).__init__(buffered_data_source, "statistics_data_2")

    def get_calculated_data(self, ui, data):
        #logging.debug("Calculating statistics %s", self)
        assert isinstance(self.item, BufferedDataSource)
        mean = numpy.mean(data)
        std = numpy.std(data)
        rms = numpy.sqrt(numpy.mean(numpy.absolute(data)**2))
        sum = mean * functools.reduce(operator.mul, Image.dimensional_shape_from_shape_and_dtype(data.shape, data.dtype))
        data_range = self.item.data_range
        data_min, data_max = data_range if data_range is not None else (None, None)
        all_computations = { "mean": mean, "std": std, "min": data_min, "max": data_max, "rms": rms, "sum": sum }
        global _computation_fns
        for computation_fn in _computation_fns:
            computations = computation_fn(self.item)
            if computations is not None:
                all_computations.update(computations)
        return all_computations

    def get_default_data(self):
        return { }


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

    Data sources should support deep copy. They are never shared (i.e. they only occur once in the model).

    *Primary Functionality*

    Data sources provide a get_data_and_calibration_publisher method to return a publisher of
    DataAndMetadata objects.

    *Secondary Functionality*

    When data sources is about to be closed, they will receive this message.

    closed()

    When data sources are about to be removed, they will receive this message.

    about_to_be_removed()

    Data sources can only be associated in the operation tree of a single data item. The data source
    keeps track of that so as to maintain the dependent_data_item list on data items.

    set_dependent_data_item(data_item)

    Data sources, particularly operations, may have associated regions. When a region is deleted, it will
    notify its listeners that it is being removed via this method.

    remove_region(region)

    Data sources can subscribe to other data items becoming available via the data item manager.

    set_data_item_manager(data_item_manager)

    Data sources should provide a list of child data sources of important types.

    * ordered_data_item_data_sources
    * ordered_operation_data_sources
"""


# enumerations for types of data item content changes
DATA = 1
METADATA = 2
DISPLAYS = 3


class DtypeToStringConverter(object):
    def convert(self, value):
        return str(value) if value is not None else None
    def convert_back(self, value):
        return numpy.dtype(value) if value is not None else None


class DatetimeToStringConverter(object):
    def convert(self, value):
        return value.isoformat() if value is not None else None
    def convert_back(self, value):
        if len(value) == 26:
            return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f")
        elif len(value) == 19:
            return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
        else:
            return None


def data_source_factory(lookup_id):
    type = lookup_id("type")
    if type == "buffered-data-source":
        return BufferedDataSource()
    elif type == "data-item-data-source":
        return Operation.DataItemDataSource()
    elif type == "operation":
        return Operation.operation_item_factory(lookup_id)
    else:
        return None


def computation_factory(lookup_id):
    return Symbolic.Computation()


class BufferedDataSource(Observable.Observable, Observable.Broadcaster, Storage.Cacheable, Observable.ManagedObject):

    """
    A data source that stores the data directly, with optional source data that gets updated as necessary.

    The buffered data source stores data directly. If the optional data_source is present, it will update the stored
    data when the data_source is updated.

    Coordinate system. The coordinate system of the pixels refers to the position within the numpy array. For 1d data,
    this means that channel 0 is the first channel. For 2d data, this means that the pixel coordinate 0, 0 is at the top
    left, within increasing y moving downward and increasing x moving right. For 3d data, this means that the first
    coordinate specifies the depth with 0 considered to be the "top". The next two coordinates are y, x with 0, 0 at the
    top left of each layer.
    """

    def __init__(self, data=None, create_display=True):
        super(BufferedDataSource, self).__init__()
        self.__weak_dependent_data_item = None
        self.__data_item_manager = None
        self.__data_item_manager_lock = threading.RLock()
        self.define_type("buffered-data-source")
        data_shape = data.shape if data is not None else None
        data_dtype = data.dtype if data is not None else None
        # windows utcnow has a resolution of 1ms, this sleep can guarantee unique times for all created times during a particular test.
        # this is not my favorite solution since it limits data item creation to 1000/s but until I find a better solution, this is my compromise.
        self.define_property("data_shape", data_shape)
        self.define_property("data_dtype", data_dtype, converter=DtypeToStringConverter())
        self.define_property("intensity_calibration", Calibration.Calibration(), hidden=True, make=Calibration.Calibration, changed=self.__metadata_property_changed)
        self.define_property("dimensional_calibrations", CalibrationList(), hidden=True, make=CalibrationList, changed=self.__metadata_property_changed)
        self.define_property("created", datetime.datetime.utcnow(), converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        self.define_property("source_data_modified", converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        self.define_property("data_modified", converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        self.define_property("metadata", dict(), hidden=True, changed=self.__metadata_property_changed)
        self.define_item("data_source", data_source_factory, item_changed=self.__data_source_changed)  # will be deep copied when copying, needs explicit set method set_data_source
        self.define_item("computation", computation_factory, item_changed=self.__computation_changed)  # will be deep copied when copying, needs explicit set method set_computation
        self.define_relationship("displays", Display.display_factory, insert=self.__insert_display, remove=self.__remove_display)
        self.define_relationship("regions", Region.region_factory, insert=self.__insert_region, remove=self.__remove_region)
        self.__remove_region_listeners = list()
        self.__request_remove_listener = None
        self.__data = None
        self.__data_lock = threading.RLock()
        self.__change_count = 0
        self.__change_count_lock = threading.RLock()
        self.__change_changed = False
        self.__recompute_lock = threading.RLock()
        self.__recompute_allowed = True
        self.__pending_data = None
        self.__pending_data_lock = threading.RLock()
        self.__is_recomputing = False
        self.__data_ref_count = 0
        self.__data_ref_count_mutex = threading.RLock()
        self.__subscription = None
        self.__publisher = Observable.Publisher()
        self.__publisher.on_subscribe = self.__notify_next_data_and_calibration_after_subscribe
        self.__computation_changed_event_listener = None  # incoming to know when the computation changes internally
        self.computation_changed_event = Observable.Event()  # outgoing message
        self.data_and_metadata_changed_event = Observable.Event()
        self.metadata_changed_event = Observable.Event()
        self.request_remove_data_item_because_operation_removed_event = Observable.Event()
        self.__processors = dict()
        self.__processors["statistics"] = StatisticsDataItemProcessor(self)
        if data is not None:
            self.__set_data(data)
        if create_display:
            self.add_display(Display.Display())  # always have one display, for now

    def close(self):
        for processor in self.__processors.values():
            processor.close()
        self.__processors = None
        if self.__subscription:
            self.__subscription.close()
        self.__subscription = None
        for display in self.displays:
            display.close()
        for remove_region_listener in self.__remove_region_listeners:
            remove_region_listener.close()
        self.__remove_region_listeners = None
        if self.data_source:
            self.data_source.close()
        if self.__computation_changed_event_listener:
            self.__computation_changed_event_listener.close()
            self.__computation_changed_event_listener = None
        self.__publisher.close()
        self.__publisher = None

    def __deepcopy__(self, memo):
        deepcopy = self.__class__()
        deepcopy.deepcopy_from(self, memo)
        memo[id(self)] = deepcopy
        return deepcopy

    def deepcopy_from(self, buffered_data_source, memo):
        super(BufferedDataSource, self).deepcopy_from(buffered_data_source, memo)
        # calibrations
        self.set_intensity_calibration(buffered_data_source.intensity_calibration)
        self.set_dimensional_calibrations(buffered_data_source.dimensional_calibrations)
        # metadata
        self.set_metadata(buffered_data_source.metadata)
        self.created = buffered_data_source.created
        # displays
        for display in self.displays:
            self.remove_display(display)
        for display in buffered_data_source.displays:
            self.add_display(copy.deepcopy(display))
        # regions
        for region in self.regions:
            self.remove_region(region)
        for region in buffered_data_source.regions:
            self.add_region(copy.deepcopy(region))
        # data source
        if buffered_data_source.data_source:
            self.set_item("data_source", copy.deepcopy(buffered_data_source.data_source))
        # data
        if buffered_data_source.has_data:
            self.__set_data(numpy.copy(buffered_data_source.data))
        else:
            self.__set_data(None)

    def snapshot(self):
        """
            Take a snapshot and return a new buffered data source. A snapshot is a copy of everything
            except the data and operation which are replaced by new data with the operation
            applied or "burned in".
        """
        buffered_data_source_copy = BufferedDataSource()
        buffered_data_source_copy.set_intensity_calibration(self.intensity_calibration)
        buffered_data_source_copy.set_dimensional_calibrations(self.dimensional_calibrations)
        buffered_data_source_copy.set_metadata(self.metadata)
        buffered_data_source_copy.created = self.created
        for display in self.displays:
            buffered_data_source_copy.add_display(copy.deepcopy(display))
        if self.has_data:
            buffered_data_source_copy.__set_data(numpy.copy(self.data))
        return buffered_data_source_copy

    def read_from_dict(self, properties):
        for display in self.displays:
            self.remove_display(display)
        for region in self.regions:
            self.remove_region(region)
        super(BufferedDataSource, self).read_from_dict(properties)

    def finish_reading(self):
        # called when reading is finished. gives the data item a chance to
        # mark its data as valid.
        if self.has_data:
            with self.__pending_data_lock:
                self.__pending_data = None
        # display properties need to be updated after storage_cache is initialized.
        # this is where to do it. in order for these methods to not have the side
        # effect of invalidating cached values, they need to occur while is_reading
        # is still true. call super after these two.
        for display in self.displays:
            display.update_properties(self.data_properties)
            display.update_data(self.data_and_calibration)
        super(BufferedDataSource, self).finish_reading()

    def set_data_item_manager(self, data_item_manager):
        with self.__data_item_manager_lock:
            computation = self.computation
            if self.__data_item_manager and computation:
                self.__data_item_manager.computation_changed(self, None)
            self.__data_item_manager = data_item_manager
            if self.data_source:
                self.data_source.set_data_item_manager(self.__data_item_manager)
            if self.__data_item_manager and computation:
                self.__data_item_manager.computation_changed(self, computation)

    def set_dependent_data_item(self, data_item):
        self.__weak_dependent_data_item = weakref.ref(data_item) if data_item else None
        if self.data_source:
            self.data_source.set_dependent_data_item(data_item)

    def __get_dependent_data_item(self):
        return self.__weak_dependent_data_item() if self.__weak_dependent_data_item else None

    @property
    def _data_item(self):
        return self.__get_dependent_data_item()

    def about_to_be_removed(self):
        with self.__recompute_lock:
            self.__recompute_allowed = False
        for region in self.regions:
            region.about_to_be_removed()
        for display in self.displays:
            display.about_to_be_removed()
        if self.data_source:
            self.data_source.about_to_be_removed()

    def get_processor(self, processor_id):
        # check for case where we might already be closed. not pretty.
        return self.__processors[processor_id] if self.__processors else None

    def get_processed_data(self, processor_id):
        return self.get_processor(processor_id).get_cached_data()

    # called from processors
    def processor_needs_recompute(self, processor):
        self.notify_listeners("buffered_data_source_processor_needs_recompute", self, processor)

    # called from processors
    def processor_data_updated(self, processor):
        self.notify_listeners("buffered_data_source_processor_data_updated", self, processor)

    @property
    def data_for_processor(self):
        return self.data

    def will_remove_operation_region(self, region):
        self.remove_region(region)

    def __metadata_property_changed(self, name, value):
        self.__property_changed(name, value)
        self.__metadata_changed()

    def __metadata_changed(self):
        self.__notify_next_data_and_calibration()
        self.metadata_changed_event.fire()

    def __property_changed(self, name, value):
        self.notify_set_property(name, value)

    def __notify_next_data_and_calibration(self):
        """Grab the data_and_calibration from the data item and pass it to subscribers."""
        with self._changes() as changes:
            self.__change_changed = True

    def __notify_next_data_and_calibration_after_subscribe(self, subscriber):
        data_and_calibration = self.data_and_calibration
        data_and_calibration.timestamp = self.data_modified if self.data_modified else self.created
        self.__publisher.notify_next_value(data_and_calibration, subscriber)

    def get_data_and_calibration_publisher(self):
        """Return the data and calibration publisher. This is a required method for data sources."""
        return self.__publisher

    def set_data_source(self, data_source):
        self.set_item("data_source", data_source)

    def set_computation(self, computation):
        self.set_item("computation", computation)

    def __computation_changed(self, name, old_computation, new_computation):
        if old_computation:
            self.__computation_changed_event_listener.close()
            self.__computation_changed_event_listener = None
        if self.__data_item_manager:
            self.__data_item_manager.computation_changed(self, new_computation)
        if new_computation:
            def computation_changed():
                self.computation_changed_event.fire()
                self.__metadata_changed()
            self.__computation_changed_event_listener = new_computation.computation_changed_event.listen(computation_changed)
        self.computation_changed_event.fire()
        self.__metadata_changed()

    def __data_source_changed(self, name, old_data_source, new_data_source):
        # and about to be removed messages
        if old_data_source and not new_data_source:
            old_data_source.about_to_be_removed()  # ugh. this is intended to notify that the data item is about to be removed from the document.
        if old_data_source:
            # handle listeners/observers
            old_data_source.set_dependent_data_item(None)
            old_data_source.set_data_item_manager(None)
            self.__request_remove_listener.close()
            self.__request_remove_listener = None
        if new_data_source:
            # handle listeners/observers
            new_data_source.set_dependent_data_item(self.__get_dependent_data_item())
            new_data_source.set_data_item_manager(self.__data_item_manager)
            def notify_request_remove_data_item_because_operation_removed():
                self.request_remove_data_item_because_operation_removed_event.fire()
            self.__request_remove_listener = new_data_source.request_remove_data_item_because_operation_removed_event.listen(notify_request_remove_data_item_because_operation_removed)
            subscriber = Observable.Subscriber(self.__handle_next_value)
            publisher = new_data_source.get_data_and_calibration_publisher()
            self.__subscription = publisher.subscribex(subscriber)

    def __handle_next_value(self, data_and_calibration):
        # when a new value from the data source comes in, it should replace
        # any existing pending value. if the data is not being computed, it
        # should also schedule the computation using the data item manager.
        # the recompute function will take care of scheduling another
        # computation if necessary at the end.
        with self.__pending_data_lock:
            self.__pending_data = data_and_calibration
            if self.__data_item_manager and not self.__is_recomputing:
                self.__data_item_manager.dispatch_task(self.recompute_data, "data")
            for processor in self.__processors.values():
                processor.mark_data_dirty()

    @property
    def ordered_data_item_data_sources(self):
        if self.data_source:
            return self.data_source.ordered_data_item_data_sources
        else:
            return list()

    @property
    def ordered_operation_data_sources(self):
        if self.data_source:
            return self.data_source.ordered_operation_data_sources
        else:
            return list()

    @property
    def data_and_calibration(self):
        try:
            data_fn = lambda: self.data
            data_shape_and_dtype = self.data_shape_and_dtype
            intensity_calibration = self.intensity_calibration
            dimensional_calibrations = self.dimensional_calibrations
            metadata = self.metadata
            created = self.created
            return DataAndMetadata.DataAndMetadata(data_fn, data_shape_and_dtype, intensity_calibration,
                                                   dimensional_calibrations, metadata, created)
        except Exception as e:
            import traceback
            traceback.print_exc()
            traceback.print_stack()
            raise

    def set_data_and_calibration(self, data_and_calibration):
        with self._changes():
            self.__set_data(data_and_calibration.data)
            self.set_intensity_calibration(data_and_calibration.intensity_calibration)
            self.set_dimensional_calibrations(data_and_calibration.dimensional_calibrations)
            self.set_metadata(data_and_calibration.metadata)
            self.created = data_and_calibration.timestamp

    @property
    def data_shape_and_dtype(self):
        if self.has_data:
            return self.data_shape, self.data_dtype
        return None

    @property
    def intensity_calibration(self):
        if self.has_data:
            return copy.deepcopy(self._get_managed_property("intensity_calibration"))
        return None

    @property
    def dimensional_calibrations(self):
        try:
            if self.has_data:
                return copy.deepcopy(self._get_managed_property("dimensional_calibrations").list)
            return list()
        except Exception as e:
            import traceback
            traceback.print_exc()
            traceback.print_stack()
            raise

    def set_intensity_calibration(self, calibration):
        """ Set the intensity calibration. """
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

    def __sync_dimensional_calibrations(self, ndim):
        dimensional_calibrations = self.dimensional_calibrations
        if len(dimensional_calibrations) != ndim:
            while len(dimensional_calibrations) < ndim:
                dimensional_calibrations.append(Calibration.Calibration())
            while len(dimensional_calibrations) > ndim:
                dimensional_calibrations.remove(dimensional_calibrations[-1])
            self.set_dimensional_calibrations(dimensional_calibrations)

    @property
    def metadata(self):
        return copy.deepcopy(self._get_managed_property("metadata"))

    def set_metadata(self, metadata):
        self._set_managed_property("metadata", copy.deepcopy(metadata))

    def storage_cache_changed(self, storage_cache):
        # override from Cacheable
        self.__validate_data_stats()
        for display in self.displays:
            display.storage_cache = storage_cache
        for region in self.regions:
            region.storage_cache = storage_cache

    def __insert_display(self, name, before_index, display):
        # listen
        display.update_properties(self.data_properties)
        display.update_data(self.data_and_calibration)
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
        # close the display
        display.close()

    def add_display(self, display):
        self.append_item("displays", display)

    def remove_display(self, display):
        self.remove_item("displays", display)

    def __insert_region(self, name, before_index, region):
        # listen
        remove_region_listener = region.remove_region_because_graphic_removed_event.listen(functools.partial(self.remove_region, region))
        self.__remove_region_listeners.insert(before_index, remove_region_listener)
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
        remove_region_listener = self.__remove_region_listeners[index]
        remove_region_listener.close()
        self.__remove_region_listeners.remove(remove_region_listener)

    def add_region(self, region):
        self.append_item("regions", region)

    def remove_region(self, region):
        self.remove_item("regions", region)

    def __validate_data_stats(self):
        """Ensure that data stats are valid after reading."""
        if self.has_data and (self.data_range is None or (self.is_data_complex_type and self.data_sample is None)):
            self.__calculate_data_stats_for_data(self.data)

    def __calculate_data_stats_for_data(self, data):
        if data is not None and data.size:
            if Image.is_shape_and_dtype_rgb_type(data.shape, data.dtype):
                data_range = (0, 255)
                data_sample = None
            elif Image.is_shape_and_dtype_complex_type(data.shape, data.dtype):
                scalar_data = Image.scalar_from_array(data)
                data_range = (scalar_data.min(), scalar_data.max())
                data_sample = numpy.sort(numpy.abs(numpy.random.choice(data.reshape(numpy.product(data.shape)), 200)))
            else:
                data_range = (data.min(), data.max())
                data_sample = None
        else:
            data_range = None
            data_sample = None
        if data_range is not None:
            self.set_cached_value("data_range", data_range)
        else:
            self.remove_cached_value("data_range")
        if data_sample is not None:
            self.set_cached_value("data_sample", data_sample)
        else:
            self.remove_cached_value("data_sample")

    @property
    def data_range(self):
        return self.get_cached_value("data_range")

    @property
    def data_sample(self):
        return self.get_cached_value("data_sample")

    @property
    def data_properties(self):
        data_properties = dict()
        data_properties["data_range"] = self.data_range
        data_properties["data_sample"] = self.data_sample
        return data_properties

    @property
    def has_data(self):
        return self.data_shape is not None and self.data_dtype is not None

    def __get_data(self):
        with self.__data_lock:
            return self.__data

    def __set_data(self, data, data_modified=None):
        with self._changes():
            assert (data.shape is not None) if data is not None else True  # cheap way to ensure data is an ndarray
            with self.__data_lock:
                self.__data = data
                self.data_modified = data_modified if data_modified else datetime.datetime.utcnow()
                self.data_shape = data.shape if data is not None else None
                self.data_dtype = data.dtype if data is not None else None
                dimensional_shape = Image.dimensional_shape_from_shape_and_dtype(self.data_shape, self.data_dtype)
                self.__sync_dimensional_calibrations(len(dimensional_shape) if dimensional_shape is not None else 0)
                self.__calculate_data_stats_for_data(data)
            # tell the managed object context about it
            if self.__data is not None:
                if self.managed_object_context:
                    self.managed_object_context.rewrite_data_item_data(self)
                data_range = self.data_range
                data_sample = self.data_sample
                self.notify_set_property("data_range", data_range)
                self.notify_set_property("data_sample", data_sample)
                for display in self.displays:
                    display.update_property("data_range", data_range)
                    display.update_property("data_sample", data_sample)
            self.__notify_next_data_and_calibration()

    def __load_data(self):
        # load data from managed object context if data is not already loaded
        if self.has_data and self.__data is None:
            if self.managed_object_context:
                #logging.debug("loading %s", self)
                self.__data = self.managed_object_context.load_data(self)

    def __unload_data(self):
        # unload data if possible.
        # data cannot be unloaded if there is no managed object context.
        if self.managed_object_context:
            self.__data = None
            #logging.debug("unloading %s", self)

    def increment_data_ref_count(self):
        with self.__data_ref_count_mutex:
            initial_count = self.__data_ref_count
            self.__data_ref_count += 1
            if initial_count == 0:
                self.__load_data()
        return initial_count+1

    def decrement_data_ref_count(self):
        with self.__data_ref_count_mutex:
            self.__data_ref_count -= 1
            final_count = self.__data_ref_count
            if final_count == 0:
                self.__unload_data()
        return final_count

    @property
    def is_data_stale(self):
        """Return whether the data is currently stale."""
        return self.__pending_data is not None

    # used for testing
    @property
    def is_data_loaded(self):
        return self.has_data and self.__data is not None

    @property
    def has_data(self):
        return self.data_shape is not None and self.data_dtype is not None

    # grab a data reference as a context manager. the object
    # returned defines data and data properties. reading data
    # should use the data property. writing data (if allowed) should
    # assign to the data property.
    def data_ref(self):
        get_data = BufferedDataSource.__get_data
        set_data = BufferedDataSource.__set_data
        class DataAccessor(object):
            def __init__(self, data_item):
                self.__data_item = data_item
            def __enter__(self):
                self.__data_item.increment_data_ref_count()
                return self
            def __exit__(self, type, value, traceback):
                self.__data_item.decrement_data_ref_count()
            @property
            def data(self):
                return get_data(self.__data_item)
            @data.setter
            def data(self, value):
                set_data(self.__data_item, value)
            def data_updated(self):
                set_data(self.__data_item, get_data(self.__data_item))
            @property
            def master_data(self):
                return get_data(self.__data_item)
            @data.setter
            def master_data(self, value):
                set_data(self.__data_item, value)
            def master_data_updated(self):
                set_data(self.__data_item, get_data(self.__data_item))
        return DataAccessor(self)

    @property
    def data(self):
        """Return the cached data for this data item.

        The data returned from this method may not be the latest data if a computation
        is in progress.

        This method will never block and can be called from the main thread.

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

    def _changes(self):
        # return a context manager to batch up a set of changes so that listeners
        # are only notified after the last change is complete.
        buffered_data_source = self
        class ChangeContextManager(object):
            def __enter__(self):
                buffered_data_source._begin_changes()
                return self
            def __exit__(self, type, value, traceback):
                buffered_data_source._end_changes()
        return ChangeContextManager()

    def _begin_changes(self):
        with self.__change_count_lock:
            self.__change_count += 1

    def _end_changes(self):
        with self.__change_count_lock:
            self.__change_count -= 1
            change_count = self.__change_count
            if change_count == 0:
                changed = self.__change_changed
                self.__change_changed = False
        # if the change count is now zero, it means that we're ready
        # to pass on the next value.
        if change_count == 0 and changed:
            data_and_calibration = self.data_and_calibration
            self.__publisher.notify_next_value(data_and_calibration)
            self.data_and_metadata_changed_event.fire()
            for display in self.displays:
                display.update_data(data_and_calibration)
            if not self._is_reading:
                for processor in self.__processors.values():
                    processor.mark_data_dirty()

    def r_value_changed(self):
        with self._changes():
            self.__change_changed = True

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(BufferedDataSource, self).notify_set_property(key, value)
        for processor in self.__processors.values():
            processor.item_property_changed(key, value)

    def recompute_data(self):
        """Ensures that the data is synchronized with the sources/operation by recomputing if necessary."""
        with self._changes():
            with self.__recompute_lock:
                if self.__recompute_allowed:
                    try:
                        with self.__pending_data_lock:  # only one thread should be computing data at once
                            pending_data = self.__pending_data
                            self.__pending_data = None
                            self.__is_recomputing = True
                        if pending_data is not None:
                            self.increment_data_ref_count()  # make sure data is loaded
                            try:
                                operation_data = pending_data.data_fn()
                                if operation_data is not None:
                                    self.__set_data(operation_data)
                                    self.source_data_modified = pending_data.timestamp
                            finally:
                                self.decrement_data_ref_count()  # unload data
                            operation_intensity_calibration = pending_data.intensity_calibration
                            operation_dimensional_calibrations = pending_data.dimensional_calibrations
                            if operation_intensity_calibration is not None and operation_dimensional_calibrations is not None:
                                self.set_intensity_calibration(operation_intensity_calibration)
                                for index, dimensional_calibration in enumerate(operation_dimensional_calibrations):
                                    self.set_dimensional_calibration(index, dimensional_calibration)
                    finally:  # this should occur so that temporary errors in computation are ignored
                        with self.__pending_data_lock:
                            self.__is_recomputing = False
                            if self.__pending_data and self.__data_item_manager:
                                self.__data_item_manager.dispatch_task(self.recompute_data, "data")

    @property
    def dimensional_shape(self):
        return self.data_and_calibration.dimensional_shape

    @property
    def is_data_1d(self):
        return self.data_and_calibration.is_data_1d

    @property
    def is_data_2d(self):
        return self.data_and_calibration.is_data_2d

    @property
    def is_data_3d(self):
        return self.data_and_calibration.is_data_3d

    @property
    def is_data_rgb(self):
        return self.data_and_calibration.is_data_rgb

    @property
    def is_data_rgba(self):
        return self.data_and_calibration.is_data_rgba

    @property
    def is_data_rgb_type(self):
        return self.data_and_calibration.is_data_rgb_type

    @property
    def is_data_scalar_type(self):
        return self.data_and_calibration.is_data_scalar_type

    @property
    def is_data_complex_type(self):
        return self.data_and_calibration.is_data_complex_type

    def get_data_value(self, pos):
        return self.data_and_calibration.get_data_value(pos)

    @property
    def size_and_data_format_as_string(self):
        return self.data_and_calibration.size_and_data_format_as_string


# dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# time zone name is for display only and has no specified format

class DataItem(Observable.Observable, Observable.Broadcaster, Storage.Cacheable, Observable.ManagedObject):

    """
    Data items represent a set of data sources + metadata.

    * *created* a datetime item
    * *session_id* a string representing the session
    * *connections* a list of connections between objects
    * *operation* an operation describing how to compute this data item

    *Descriptive Metadata*

    * *title* a string (single line)
    * *caption* a string (multiple lines)
    * *rating* an integer star rating (0 to 5)
    * *flag* a flag (-1, 0, 1)

    *Modification Dates*

    Data items keep track of a created datetime, which is set once when the object is created; a modified datetime,
    which is updated whenever the object or its related objects get modified.

    Data items also provide a data modified datetime, which is the latest data modified datetime from all of the data
    sources.

    *Notifications*

    Data items will emit the following notifications to listeners. Listeners should take care to not call functions
    which result in cycles of notifications. For instance, functions handling data_item_content_changed should not use
    functions that will trigger the data to be computed which will emit data_item_content_changed, resulting in a cycle.

    * data_item_content_changed(data_item, changes)

    data_item_content_changed is invoked when the content of the data item changes. The changes parameter is a set of
    changes from DATA, METADATA, DISPLAYS, SOURCE. This may be called on a thread.

    request_remove_data_item is invoked when a region associated with an operation is removed by the user. This message
    can be used to remove the associated dependent data item. This will not be called from a thread.

    *Miscellaneous*

    Transactions.

    Live state.

    Snapshots and deep copies.

    Properties.

    Metadata.
    """

    writer_version = 8

    def __init__(self, data=None, item_uuid=None):
        super(DataItem, self).__init__()
        global writer_version
        self.uuid = item_uuid if item_uuid else self.uuid
        self.writer_version = DataItem.writer_version  # writes this version
        self.__transaction_count = 0
        self.__transaction_count_mutex = threading.RLock()
        self.__pending_write = True
        self.managed_object_context = None
        self.define_property("created", datetime.datetime.utcnow(), converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        # windows utcnow has a resolution of 1ms, this sleep can guarantee unique times for all created times during a particular test.
        # this is not my favorite solution since it limits data item creation to 1000/s but until I find a better solution, this is my compromise.
        time.sleep(0.001)
        self.define_property("metadata", dict(), hidden=True, changed=self.__property_changed)
        self.define_property("source_file_path", validate=self.__validate_source_file_path, changed=self.__property_changed)
        self.define_property("session_id", validate=self.__validate_session_id, changed=self.__session_id_changed)
        self.define_relationship("data_sources", data_source_factory, insert=self.__insert_data_source, remove=self.__remove_data_source)
        self.define_relationship("connections", Connection.connection_factory)
        self.__request_remove_listeners = list()
        self.__subscriptions = list()
        self.__live_count = 0  # specially handled property
        self.__live_count_lock = threading.RLock()
        self.__metadata = dict()
        self.__metadata_lock = threading.RLock()
        self.metadata_changed_event = Observable.Event()
        self.__data_item_change_count = 0
        self.__data_item_change_count_lock = threading.RLock()
        self.__data_item_changes = set()
        self.__data_item_manager = None
        self.__data_item_manager_lock = threading.RLock()
        self.__dependent_data_item_refs = list()
        self.__dependent_data_item_refs_lock = threading.RLock()
        self.__suspendable_storage_cache = None
        self.r_var = None
        if data is not None:
            data_source = BufferedDataSource(data)
            self.append_data_source(data_source)

    def __str__(self):
        return "{0} {1} ({2}, {3})".format(self.__repr__(), (self.title if self.title else _("Untitled")), str(self.uuid), self.date_for_sorting_local_as_string)

    def __copy__(self):
        assert False

    def __deepcopy__(self, memo):
        data_item_copy = DataItem()
        # metadata
        data_item_copy.set_metadata(self.metadata)
        data_item_copy.created = self.created
        data_item_copy.session_id = self.session_id
        data_item_copy.source_file_path = self.source_file_path
        # data sources
        for data_source in copy.copy(data_item_copy.data_sources):
            data_item_copy.remove_data_source(data_source)
        for data_source in self.data_sources:
            data_item_copy.append_data_source(copy.deepcopy(data_source))
        # the data source connection will be established when this copy is inserted.
        memo[id(self)] = data_item_copy
        return data_item_copy

    def close(self):
        for data_source in copy.copy(self.data_sources):
            data_source.close()
        for subscription in self.__subscriptions:
            subscription.close()
        self.__subscriptions = list()

    def snapshot(self):
        """
            Take a snapshot and return a new data item. A snapshot is a copy of everything
            except the data and operation which are replaced by new data with the operation
            applied or "burned in".
        """
        data_item_copy = DataItem()
        # metadata
        data_item_copy.set_metadata(self.metadata)
        data_item_copy.created = self.created
        data_item_copy.session_id = self.session_id
        data_item_copy.source_file_path = self.source_file_path
        # data sources
        for data_source in copy.copy(data_item_copy.data_sources):
            data_item_copy.remove_data_source(data_source)
        for data_source in self.data_sources:
            data_item_copy.append_data_source(data_source.snapshot())
        return data_item_copy

    def about_to_be_removed(self):
        """ Tell contained objects that this data item is about to be removed from its container. """
        for connection in self.connections:
            connection.about_to_be_removed()
        for data_source in self.data_sources:
            data_source.about_to_be_removed()

    def storage_cache_changed(self, storage_cache):
        # override from Cacheable to update the children that need updating
        self.__suspendable_storage_cache = Storage.SuspendableCache(storage_cache)
        for data_source in self.data_sources:
            data_source.storage_cache = self.__suspendable_storage_cache

    @property
    def _suspendable_storage_cache(self):
        return self.__suspendable_storage_cache

    @property
    def transaction_count(self):
        """ Return the transaction count for this data item. """
        return self.__transaction_count

    def __enter_write_delay_state(self):
        self.__write_delay_modified_count = self.modified_count
        if self.managed_object_context:
            persistent_storage = self.managed_object_context.get_persistent_storage_for_object(self)
            if persistent_storage:
                persistent_storage.write_delayed = True

    def __exit_write_delay_state(self):
        if self.managed_object_context:
            persistent_storage = self.managed_object_context.get_persistent_storage_for_object(self)
            if persistent_storage:
                persistent_storage.write_delayed = False
            if self.__pending_write or self.modified_count > self.__write_delay_modified_count:
                self.managed_object_context.write_data_item(self)
            self.__pending_write = False

    def _begin_transaction(self):
        """Begin transaction state.

        A transaction state is exists to prevent writing out to disk, mainly for performance reasons.
        All changes to the object are delayed until the transaction state exits.

        Has the side effects of entering the write delay state, cache delay state (via is_cached_delayed),
        loading data of data sources, and entering transaction state for dependent data items.

        This method is thread safe.
        """
        #logging.debug("begin transaction %s %s", self.uuid, self.__transaction_count)
        # maintain the transaction count under a mutex
        with self.__transaction_count_mutex:
            old_transaction_count = self.__transaction_count
            self.__transaction_count += 1
        # if the old transaction count was 0, it means we're entering the transaction state.
        if old_transaction_count == 0:
            # first enter the write delay state.
            self.__enter_write_delay_state()
            # suspend disk caching
            if self.__suspendable_storage_cache:
                self.__suspendable_storage_cache.suspend_cache()
            # now tell each data source to load its data.
            # this prevents paging in and out.
            for data_source in self.data_sources:
                data_source.increment_data_ref_count()
            # finally, tell dependent data items to enter their transaction states also
            # so that they also don't write change to disk immediately.
            for data_item in self.dependent_data_items:
                data_item._begin_transaction()

    def _end_transaction(self):
        """End transaction state.

        Has the side effects of exiting the write delay state, cache delay state (via is_cached_delayed),
        unloading data of data sources, and exiting transaction state for dependent data items.

        As a consequence of exiting write delay state, data and metadata may be written to disk.

        As a consequence of existing cache delay state, cache may be written to disk.

        This method is thread safe.
        """
        # maintain the transaction count under a mutex
        with self.__transaction_count_mutex:
            self.__transaction_count -= 1
            assert self.__transaction_count >= 0
            transaction_count = self.__transaction_count
        # if the new transaction count is 0, it means we're exiting the transaction state.
        if transaction_count == 0:
            # first, tell our dependent data items to exit their transaction states.
            for data_item in self.dependent_data_items:
                data_item._end_transaction()
            # being in the transaction state has the side effect of delaying the cache too.
            # spill whatever was into the local cache into the persistent cache.
            if self.__suspendable_storage_cache:
                self.__suspendable_storage_cache.spill_cache()
            # exit the write delay state.
            self.__exit_write_delay_state()
            # finally, tell each data source to unload its data.
            for data_source in self.data_sources:
                data_source.decrement_data_ref_count()
        #logging.debug("end transaction %s %s", self.uuid, self.__transaction_count)

    def managed_object_context_changed(self):
        # handle case where managed object context is set on an item that is already under transaction.
        # this can occur during acquisition. any other cases?
        super(DataItem, self).managed_object_context_changed()
        if self.__transaction_count > 0:
            self.__enter_write_delay_state()

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
            for data_source in copy.copy(self.data_sources):
                self.remove_data_source(data_source)
            super(DataItem, self).read_from_dict(properties)
            self.__data_item_changes = set()
        self.__pending_write = False

    @property
    def properties(self):
        """ Used for debugging. """
        if self.managed_object_context:
            return self.managed_object_context.get_properties(self)
        return dict()

    @property
    def is_live(self):
        """ Return whether this data item represents a live acquisition data item. """
        return self.__live_count > 0

    @property
    def live_count(self):
        """ Return the live count for this data item. """
        return self.__live_count

    def _begin_live(self):
        """Begins a live transaction with this item.

        The live state is propagated to dependent data items.

        This method is thread safe. See slow_test_dependent_data_item_removed_while_live_data_item_becomes_unlive.
        """
        with self.__live_count_lock:
            old_live_count = self.__live_count
            self.__live_count += 1
        if old_live_count == 0:
            self.notify_data_item_content_changed(set([METADATA]))  # this will affect is_live, so notify
            for data_item in self.dependent_data_items:
                data_item._begin_live()

    def _end_live(self):
        """
        Ends a live transaction with this item. The live-ness property is propagated to
        dependent data items, similar to the transactions.

        This method is thread safe.
        """
        with self.__live_count_lock:
            self.__live_count -= 1
            assert self.__live_count >= 0
            live_count = self.__live_count
        if live_count == 0:
            self.notify_data_item_content_changed(set([METADATA]))  # this will affect is_live, so notify
            for data_item in self.dependent_data_items:
                data_item._end_live()

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
            self.notify_listeners("data_item_content_changed", self, changes)

    def __validate_source_file_path(self, value):
        value = Unicode.u(value)
        if value:
            value = os.path.normpath(value)
        return Unicode.u(value)

    def __metadata_property_changed(self, name, value):
        self.__property_changed(name, value)
        self.__metadata_changed()

    def __metadata_changed(self):
        self.notify_data_item_content_changed(set([METADATA]))
        self.metadata_changed_event.fire()

    def __property_changed(self, name, value):
        self.notify_set_property(name, value)

    def set_r_value(self, r_var):
        """Used to signal changes to the data ref var, which are kept in document controller. ugh."""
        self.r_var = r_var
        for data_source in self.data_sources:
            data_source.r_value_changed()
        self.notify_data_item_content_changed(set([METADATA]))

    @property
    def displayed_title(self):
        if self.r_var:
            return "{0} ({1})".format(self.title, self.r_var)
        else:
            return self.title

    # call this when the listeners need to be updated (via data_item_content_changed).
    # Calling this method will send the data_item_content_changed method to each listener.
    def notify_data_item_content_changed(self, changes):
        with self.data_item_changes():
            with self.__data_item_change_count_lock:
                self.__data_item_changes.update(changes)

    # date times

    @property
    def date_for_sorting(self):
        data_modified_list = list()
        for data_source in self.data_sources:
            source_data_modified = data_source.source_data_modified
            if source_data_modified:
                data_modified_list.append(source_data_modified)
            else:
                data_modified = data_source.data_modified
                if data_modified:
                    data_modified_list.append(data_modified)
                else:
                    data_modified_list.append(self.created)
        if len(data_modified_list):
            return max(data_modified_list)
        return self.created

    @property
    def date_for_sorting_local_as_string(self):
        date_utc = self.date_for_sorting
        tz_minutes = int(round((datetime.datetime.now() - datetime.datetime.utcnow()).total_seconds())) // 60
        date_local = date_utc + datetime.timedelta(minutes=tz_minutes)
        return date_local.strftime("%c")

    @property
    def created_local_as_string(self):
        return self.created_local.strftime("%c")

    @property
    def created_local(self):
        created_utc = self.created
        tz_minutes = int(round((datetime.datetime.now() - datetime.datetime.utcnow()).total_seconds())) // 60
        return created_utc + datetime.timedelta(minutes=tz_minutes)

    # access metadata

    @property
    def metadata(self):
        return copy.deepcopy(self._get_managed_property("metadata"))

    def set_metadata(self, metadata):
        self._set_managed_property("metadata", copy.deepcopy(metadata))

    def __insert_data_source(self, name, before_index, data_source):
        data_source.set_dependent_data_item(self)
        data_source.set_data_item_manager(self.__data_item_manager)
        def notify_request_remove_data_item():
            # this message comes from the operation.
            # it is generated when the user deletes a operation graphic.
            # that informs the display which notifies the graphic which
            # notifies the operation which notifies this data item. ugh.
            self.notify_listeners("request_remove_data_item", self)
        request_remove_listener = data_source.request_remove_data_item_because_operation_removed_event.listen(notify_request_remove_data_item)
        self.__request_remove_listeners.insert(before_index, request_remove_listener)
        # being in transaction state means that data sources have their data loaded.
        # so load data here to keep the books straight when the transaction state is exited.
        if self.__transaction_count > 0:
            data_source.increment_data_ref_count()
        def next_value(data_and_calibration):
            if not self._is_reading:
                self.notify_listeners("data_item_content_changed", self, set([DATA]))
        subscriber = Observable.Subscriber(next_value)
        publisher = data_source.get_data_and_calibration_publisher()
        self.__subscriptions.insert(before_index, publisher.subscribex(subscriber))
        self.notify_data_item_content_changed(set([DATA]))
        # the document model watches for new data sources via observing.
        # send this message to make data_sources observable.
        self.notify_insert_item("data_sources", data_source, before_index)

    def __remove_data_source(self, name, index, data_source):
        subscription = self.__subscriptions[index]
        del self.__subscriptions[index]
        subscription.close()
        data_source.about_to_be_removed()
        data_source.set_dependent_data_item(None)
        data_source.set_data_item_manager(None)
        request_remove_listener = self.__request_remove_listeners[index]
        request_remove_listener.close()
        self.__request_remove_listeners.remove(request_remove_listener)
        # being in transaction state means that data sources have their data loaded.
        # so unload data here to keep the books straight when the transaction state is exited.
        if self.__transaction_count > 0:
            data_source.decrement_data_ref_count()
        # the document model watches for new data sources via observing.
        # send this message to make data_sources observable.
        self.notify_remove_item("data_sources", data_source, index)

    def append_data_source(self, data_source):
        self.append_item("data_sources", data_source)

    def remove_data_source(self, data_source):
        self.remove_item("data_sources", data_source)

    def add_connection(self, connection):
        self.append_item("connections", connection)

    def remove_connection(self, connection):
        self.remove_item("connections", connection)

    @property
    def operation(self):
        if len(self.data_sources) == 1:
            return self.data_sources[0].data_source
        return None

    def set_operation(self, operation):
        if len(self.data_sources) == 0:
            self.append_data_source(BufferedDataSource())
        if len(self.data_sources) == 1:
            old_operation = self.data_sources[0].data_source
            if old_operation is not None:
                self.notify_remove_item("ordered_operations", old_operation, 0)
            self.data_sources[0].set_data_source(operation)
            if operation is not None:
                self.notify_insert_item("ordered_operations", operation, 0)
        else:
            raise AttributeError("operation")

    @property
    def ordered_operations(self):
        data_sources = list()
        for data_source in self.data_sources:
            data_sources.extend(data_source.ordered_operation_data_sources)
        return data_sources

    @property
    def ordered_data_item_data_sources(self):
        data_sources = list()
        for data_source in self.data_sources:
            data_sources.extend(data_source.ordered_data_item_data_sources)
        return data_sources

    def set_data_item_manager(self, data_item_manager):
        """Set the data item manager. May be called from thread."""
        with self.__data_item_manager_lock:
            self.__data_item_manager = data_item_manager
            for data_source in self.data_sources:
                data_source.set_data_item_manager(self.__data_item_manager)

    # track dependent data items. useful for propagating transaction support.
    def add_dependent_data_item(self, data_item):
        # add the data item from our list of dependents
        with self.__dependent_data_item_refs_lock:
            self.__dependent_data_item_refs.append(weakref.ref(data_item))
        # when transaction or live count is changed, it will propagate those changes
        # to dependent items. since we're inserting a new dependent, we need
        # to compensate for those changes here.
        if self.__transaction_count > 0:
            data_item._begin_transaction()
        if self.__live_count > 0:
            data_item._begin_live()

    # track dependent data items. useful for propagating transaction support.
    def remove_dependent_data_item(self, data_item):
        # remove the data item from our list of dependents
        with self.__dependent_data_item_refs_lock:
            self.__dependent_data_item_refs.remove(weakref.ref(data_item))
        # when transaction or live count is changed, it will propagate those changes
        # to dependent items. since we're removing the dependent completely, we need
        # to compensate for those changes here.
        # TODO: is this open to a race condition?
        # if acquisition is running, live count is being changed regularly on a thread.
        # if that change occurs after end_live has been called below, but before it's
        # actually changed within the end_live method, a race condition has occurred.
        if self.__transaction_count > 0:
            data_item._end_transaction()
        if self.__live_count > 0:
            data_item._end_live()

    @property
    def dependent_data_items(self):
        """Return the list of data items containing data that directly depends on data in this item."""
        with self.__dependent_data_item_refs_lock:
            return [data_item_ref() for data_item_ref in self.__dependent_data_item_refs]

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(DataItem, self).notify_set_property(key, value)
        self.notify_data_item_content_changed(set([METADATA]))

    @property
    def maybe_data_source(self):
        return self.data_sources[0] if len(self.data_sources) == 1 else None

    def recompute_data(self):
        """Recompute all data sources."""
        for data_source in self.data_sources:
            data_source.recompute_data()

    @property
    def size_and_data_format_as_string(self):
        data_source_count = len(self.data_sources)
        if data_source_count == 0:
            return _("No Data")
        elif data_source_count == 1:
            return self.maybe_data_source.size_and_data_format_as_string
        else:
            return _("Multiple Data Sources ({0})".format(data_source_count))

    def increment_data_ref_counts(self):
        """Increment data ref counts for each data source. Will have effect of loading data if necessary."""
        for data_source in self.data_sources:
            data_source.increment_data_ref_count()

    def decrement_data_ref_counts(self):
        """Decrement data ref counts for each data source. Will have effect of unloading data if not used elsewhere."""
        for data_source in self.data_sources:
            data_source.decrement_data_ref_count()

    # notification from buffered_data_source
    def buffered_data_source_processor_needs_recompute(self, data_item, processor):
        self.notify_listeners("data_item_processor_needs_recompute", self, processor)

    # notification from buffered_data_source
    def buffered_data_source_processor_data_updated(self, data_item, processor):
        self.notify_listeners("data_item_processor_data_updated", self, processor)

    # primary display

    @property
    def primary_display_specifier(self):
        if len(self.data_sources) == 1:
            return DisplaySpecifier(self, self.data_sources[0], self.data_sources[0].displays[0])
        return DisplaySpecifier()

    # testing methods

    def _create_test_data_source(self):
        return Operation.DataItemDataSource(BufferedDataSourceSpecifier.from_data_item(self).buffered_data_source)

    # descriptive metadata

    @property
    def title(self):
        return self.metadata.get("description", dict()).get("title", UNTITLED_STR)

    @title.setter
    def title(self, value):
        metadata = self.metadata
        metadata.setdefault("description", dict())["title"] = Unicode.u(value)
        self.set_metadata(metadata)
        self.__metadata_property_changed("title", value)

    @property
    def caption(self):
        return self.metadata.get("description", dict()).get("caption", Unicode.u())

    @caption.setter
    def caption(self, value):
        metadata = self.metadata
        metadata.setdefault("description", dict())["caption"] = Unicode.u(value)
        self.set_metadata(metadata)
        self.__metadata_property_changed("caption", value)

    @property
    def flag(self):
        return self.metadata.get("description", dict()).get("flag", 0)

    @flag.setter
    def flag(self, value):
        metadata = self.metadata
        metadata.setdefault("description", dict())["flag"] = max(min(int(value), 1), -1)
        self.set_metadata(metadata)
        self.__metadata_property_changed("flag", value)

    @property
    def rating(self):
        return self.metadata.get("description", dict()).get("rating", 0)

    @rating.setter
    def rating(self, value):
        metadata = self.metadata
        metadata.setdefault("description", dict())["rating"] = min(max(int(value), 0), 5)
        self.set_metadata(metadata)
        self.__metadata_property_changed("rating", value)


class BufferedDataSourceSpecifier(object):
    """Specify a BufferedDataSource contained within a DataItem.

    If buffered_data_source is not None, then data_item is not None.
    """

    def __init__(self, data_item=None, buffered_data_source=None):
        self.data_item = data_item
        self.buffered_data_source = buffered_data_source

    def __eq__(self, other):
        return self.data_item == other.data_item and self.buffered_data_source == other.buffered_data_source

    def __ne__(self, other):
        return self.data_item != other.data_item or self.buffered_data_source != other.buffered_data_source

    @classmethod
    def from_data_item(cls, data_item):
        buffered_data_source = data_item.maybe_data_source if data_item else None
        return cls(data_item, buffered_data_source)


class DisplaySpecifier(object):
    """Specify a Display contained within a DataItem.

    If display is not None, then data_item is not None.
    If buffered_data_source is not None, then data_item is not None.
    """

    def __init__(self, data_item=None, buffered_data_source=None, display=None):
        self.data_item = data_item
        self.buffered_data_source = buffered_data_source
        self.display = display

    def __eq__(self, other):
        return self.data_item == other.data_item and self.buffered_data_source == other.buffered_data_source and self.display == other.display

    def __ne__(self, other):
        return self.data_item != other.data_item or self.buffered_data_source != other.buffered_data_source or self.display != other.display

    @classmethod
    def from_data_item(cls, data_item):
        buffered_data_source = data_item.maybe_data_source if data_item else None
        display = buffered_data_source.displays[0] if buffered_data_source else None
        return cls(data_item, buffered_data_source, display)

    @property
    def buffered_data_source_specifier(self):
        return BufferedDataSourceSpecifier(self.data_item, self.buffered_data_source)


def sort_by_date_key(data_item):
    """ A sort key to for the created field of a data item. The sort by uuid makes it determinate. """
    return data_item.title + str(data_item.uuid) if data_item.is_live else str(), data_item.date_for_sorting, str(data_item.uuid)


_computation_fns = list()

def register_computation(computation_fn):
    global _computation_fns
    _computation_fns.append(computation_fn)

def unregister_computation(self, computation_fn):
    pass
