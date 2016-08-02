# standard libraries
import copy
import datetime
import gettext
import logging
import os
import threading
import time
import typing
import uuid
import warnings
import weakref

# typing
from typing import Tuple

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import Cache
from nion.swift.model import Connection
from nion.swift.model import Display
from nion.swift.model import Symbolic
from nion.swift.model import Utility
from nion.utils import Event
from nion.utils import Observable
from nion.utils import Persistence

_ = gettext.gettext

UNTITLED_STR = _("Untitled")


class CalibrationList:

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

    When data sources is about to be closed, they will receive this message.

    closed()

    When data sources are about to be removed, they will receive this message.

    about_to_be_removed()

    Data sources can only be associated in the operation tree of a single data item. The data source
    keeps track of that so as to maintain the dependent_data_item list on data items.

    set_dependent_data_item(data_item)

    Data sources can subscribe to other data items becoming available via the data item manager.

    set_data_item_manager(data_item_manager)
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
    else:
        return None


def computation_factory(lookup_id):
    return Symbolic.Computation()


class UuidsToStringsConverter(object):
    def convert(self, value):
        return [str(uuid_) for uuid_ in value]
    def convert_back(self, value):
        return [uuid.UUID(uuid_str) for uuid_str in value]


class BufferedDataSource(Observable.Observable, Cache.Cacheable, Persistence.PersistentObject):

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
        self.define_property("data_shape", data_shape, hidden=True)
        self.define_property("data_dtype", data_dtype, hidden=True, converter=DtypeToStringConverter())
        self.define_property("intensity_calibration", Calibration.Calibration(), hidden=True, make=Calibration.Calibration, changed=self.__metadata_property_changed)
        self.define_property("dimensional_calibrations", CalibrationList(), hidden=True, make=CalibrationList, changed=self.__dimensional_calibrations_changed)
        self.define_property("created", datetime.datetime.utcnow(), converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        self.define_property("source_data_modified", converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        self.define_property("data_modified", converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        self.define_property("metadata", dict(), hidden=True, changed=self.__metadata_property_changed)
        self.define_item("computation", computation_factory, item_changed=self.__computation_changed)  # will be deep copied when copying, needs explicit set method set_computation
        self.define_relationship("displays", Display.display_factory, insert=self.__insert_display, remove=self.__remove_display)
        self.__data_and_metadata = None
        self.__data_and_metadata_lock = threading.RLock()
        self.__change_thread = None
        self.__change_count = 0
        self.__change_count_lock = threading.RLock()
        self.__change_changed = False
        self.__data_ref_count = 0
        self.__data_ref_count_mutex = threading.RLock()
        self.__subscription = None
        self.__computation_mutated_event_listener = None  # incoming to know when the computation changes internally
        self.__computation_cascade_delete_event_listener = None
        self.computation_changed_or_mutated_event = Event.Event()  # outgoing message
        self.data_and_metadata_changed_event = Event.Event()
        self.metadata_changed_event = Event.Event()
        self.request_remove_data_item_because_computation_removed_event = Event.Event()
        self.request_remove_region_because_data_item_removed_event = Event.Event()
        if data is not None:
            with self._changes():
                dimensional_calibrations = list()
                for index in range(len(Image.dimensional_shape_from_data(data))):
                    dimensional_calibrations.append(Calibration.Calibration())
                self.__set_data_metadata_direct(DataAndMetadata.DataAndMetadata.from_data(data, dimensional_calibrations=dimensional_calibrations))
                self.__change_changed = True
        if create_display:
            self.add_display(Display.Display())  # always have one display, for now
        self._about_to_be_removed = False
        self._closed = False

    def close(self):
        if self.__subscription:
            self.__subscription.close()
        self.__subscription = None
        for display in self.displays:
            display.close()
        if self.__computation_mutated_event_listener:
            self.__computation_mutated_event_listener.close()
            self.__computation_mutated_event_listener = None
        self.__data_and_metadata = None
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        for display in self.displays:
            display.about_to_be_removed()
        if self.computation:
            for variable in self.computation.variables:
                if variable.cascade_delete:
                    variable_specifier = variable.variable_specifier
                    if variable_specifier and variable_specifier.get("type") == "region":
                        self.request_remove_region_because_data_item_removed_event.fire(variable_specifier)
            self.computation_changed_or_mutated_event.fire(self, None)
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

    def __deepcopy__(self, memo):
        deepcopy = self.__class__()
        deepcopy.deepcopy_from(self, memo)
        memo[id(self)] = deepcopy
        return deepcopy

    def deepcopy_from(self, buffered_data_source, memo):
        with self._changes():
            super(BufferedDataSource, self).deepcopy_from(buffered_data_source, memo)
            # data and metadata
            data_and_metadata = buffered_data_source.data_and_metadata
            if data_and_metadata:
                data = data_and_metadata.data
                intensity_calibration = data_and_metadata.intensity_calibration
                dimensional_calibrations = data_and_metadata.dimensional_calibrations
                metadata = data_and_metadata.metadata
                timestamp = data_and_metadata.timestamp
                new_data_and_metadata = DataAndMetadata.DataAndMetadata.from_data(numpy.copy(data), intensity_calibration, dimensional_calibrations, metadata, timestamp)
            else:
                new_data_and_metadata = None
            self.set_data_and_metadata(new_data_and_metadata)
            # displays
            for display in self.displays:
                self.remove_display(display)
            for display in buffered_data_source.displays:
                self.add_display(copy.deepcopy(display))

    def snapshot(self):
        """
            Take a snapshot and return a new buffered data source. A snapshot is a copy of everything
            except the data and operation which are replaced by new data with the operation
            applied or "burned in".
        """
        buffered_data_source_copy = BufferedDataSource()
        buffered_data_source_copy.set_data_and_metadata(self.data_and_metadata)
        for display in self.displays:
            buffered_data_source_copy.add_display(copy.deepcopy(display))
        return buffered_data_source_copy

    def read_from_dict(self, properties):
        with self._changes():
            for display in self.displays:
                self.remove_display(display)
            super(BufferedDataSource, self).read_from_dict(properties)
            data_shape = self._get_persistent_property_value("data_shape", None)
            data_dtype = DtypeToStringConverter().convert_back(self._get_persistent_property_value("data_dtype", None))
            if data_shape is not None and data_dtype is not None:
                data_shape_and_dtype = data_shape, data_dtype
                intensity_calibration = self._get_persistent_property_value("intensity_calibration")
                dimensional_calibration_list = self._get_persistent_property_value("dimensional_calibrations")
                dimensional_calibrations = dimensional_calibration_list.list if dimensional_calibration_list else None
                if dimensional_calibrations is not None:
                    dimensional_shape = Image.dimensional_shape_from_shape_and_dtype(data_shape, data_dtype)
                    while len(dimensional_shape) > len(dimensional_calibrations):
                        dimensional_calibrations.append(Calibration.Calibration())
                    while len(dimensional_shape) < len(dimensional_calibrations):
                        dimensional_calibrations.pop(-1)
                metadata = self._get_persistent_property_value("metadata")
                timestamp = self._get_persistent_property_value("created")
                self.__data_and_metadata = DataAndMetadata.DataAndMetadata(self.__load_data, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp)
                with self.__data_ref_count_mutex:
                    self.__data_and_metadata._add_data_ref_count(self.__data_ref_count)
                self.__data_and_metadata.unloadable = self.persistent_object_context is not None

    def finish_reading(self):
        # display properties need to be updated after storage_cache is initialized.
        # this is where to do it. in order for these methods to not have the side
        # effect of invalidating cached values, they need to occur while is_reading
        # is still true. call super after these two.
        for display in self.displays:
            display.update_data(self.data_and_metadata)
        super(BufferedDataSource, self).finish_reading()

    def persistent_object_context_changed(self):
        super().persistent_object_context_changed()
        if self.__data_and_metadata:
            self.__data_and_metadata.unloadable = self.persistent_object_context is not None

    def set_data_item_manager(self, data_item_manager):
        with self.__data_item_manager_lock:
            computation = self.computation
            if self.__data_item_manager and computation:
                self.__data_item_manager.computation_changed(self, None)
            self.__data_item_manager = data_item_manager
            if self.__data_item_manager and computation:
                self.__data_item_manager.computation_changed(self, computation)

    def set_dependent_data_item(self, data_item):
        self.__weak_dependent_data_item = weakref.ref(data_item) if data_item else None

    def __get_dependent_data_item(self):
        return self.__weak_dependent_data_item() if self.__weak_dependent_data_item else None

    @property
    def _data_item(self):
        return self.__get_dependent_data_item()

    def __dimensional_calibrations_changed(self, name, value):
        self.__property_changed(name, self.dimensional_calibrations)  # don't send out the CalibrationList object
        self.__metadata_changed()

    def __metadata_property_changed(self, name, value):
        self.__property_changed(name, value)
        self.__metadata_changed()

    def __metadata_changed(self):
        with self._changes():
            self.__change_changed = True
        self.metadata_changed_event.fire()

    def __property_changed(self, name, value):
        self.notify_set_property(name, value)

    def set_computation(self, computation):
        self.set_item("computation", computation)

    def __computation_changed(self, name, old_computation, new_computation):
        if old_computation:
            self.__computation_mutated_event_listener.close()
            self.__computation_mutated_event_listener = None
            self.__computation_cascade_delete_event_listener.close()
            self.__computation_cascade_delete_event_listener= None
        if self.__data_item_manager:
            self.__data_item_manager.computation_changed(self, new_computation)
        if new_computation:
            def computation_mutated():
                self.computation_changed_or_mutated_event.fire(self, new_computation)
                self.__metadata_changed()
            def computation_cascade_delete():
                self.request_remove_data_item_because_computation_removed_event.fire()
            self.__computation_mutated_event_listener = new_computation.computation_mutated_event.listen(computation_mutated)
            self.__computation_cascade_delete_event_listener = new_computation.cascade_delete_event.listen(computation_cascade_delete)
        self.computation_changed_or_mutated_event.fire(self, self.computation)
        self.__metadata_changed()

    @property
    def data_metadata(self):
        return self.__data_and_metadata.data_metadata

    @property
    def data_and_metadata(self):
        return self.__data_and_metadata

    def __load_data(self):
        if self.persistent_object_context:
            return self.persistent_object_context.load_data(self)
        return None

    def __set_data_metadata_direct(self, data_and_metadata, data_modified=None):
        self.__data_and_metadata = data_and_metadata
        if self.__data_and_metadata:
            with self.__data_ref_count_mutex:
                self.__data_and_metadata._add_data_ref_count(self.__data_ref_count)
        if self.__data_and_metadata:
            self._set_persistent_property_value("data_shape", self.__data_and_metadata.data_shape)
            self._set_persistent_property_value("data_dtype", DtypeToStringConverter().convert(self.__data_and_metadata.data_dtype))
            self._set_persistent_property_value("intensity_calibration", self.__data_and_metadata.intensity_calibration)
            self._set_persistent_property_value("dimensional_calibrations", CalibrationList(self.__data_and_metadata.dimensional_calibrations))
            self._set_persistent_property_value("metadata", self.__data_and_metadata.metadata)
        self.data_modified = data_modified if data_modified else datetime.datetime.utcnow()

    def set_data_and_metadata(self, data_and_metadata, data_modified=None):
        """Sets the underlying data and data-metadata to the data_and_metadata.

        Note: this does not make a copy of the data.
        """
        with self._changes():
            if data_and_metadata:
                data = data_and_metadata.data
                data_shape_and_dtype = data_and_metadata.data_shape_and_dtype
                intensity_calibration = data_and_metadata.intensity_calibration
                dimensional_calibrations = data_and_metadata.dimensional_calibrations
                metadata = data_and_metadata.metadata
                timestamp = data_and_metadata.timestamp
                new_data_and_metadata = DataAndMetadata.DataAndMetadata(self.__load_data, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp, data)
            else:
                new_data_and_metadata = None
            self.__set_data_metadata_direct(new_data_and_metadata, data_modified)
            if self.__data_and_metadata is not None:
                if self.persistent_object_context:
                    self.persistent_object_context.rewrite_data_item_data(self)
                    self.__data_and_metadata.unloadable = True
            self.__change_changed = True

    @property
    def data_shape_and_dtype(self) -> typing.Tuple[typing.Iterable[int], numpy.dtype]:
        return self.__data_and_metadata.data_shape_and_dtype if self.__data_and_metadata else None

    @property
    def dimensional_shape(self):
        return self.__data_and_metadata.dimensional_shape if self.__data_and_metadata else None

    @property
    def intensity_calibration(self):
        return copy.deepcopy(self.__data_and_metadata.intensity_calibration) if self.__data_and_metadata else None

    @property
    def dimensional_calibrations(self):
        return copy.deepcopy(self.__data_and_metadata.dimensional_calibrations) if self.__data_and_metadata else None

    @property
    def metadata(self):
        return copy.deepcopy(self.__data_and_metadata.metadata) if self.__data_and_metadata else None

    def set_intensity_calibration(self, intensity_calibration):
        """ Set the intensity calibration. """
        with self._changes():
            self.__data_and_metadata._set_intensity_calibration(intensity_calibration)
            self._set_persistent_property_value("intensity_calibration", intensity_calibration)
            self.__change_changed = True

    def set_dimensional_calibrations(self, dimensional_calibrations):
        """ Set the dimensional calibrations. """
        with self._changes():
            self.__data_and_metadata._set_dimensional_calibrations(dimensional_calibrations)
            self._set_persistent_property_value("dimensional_calibrations", CalibrationList(dimensional_calibrations))
            self.__change_changed = True

    def set_dimensional_calibration(self, dimension, calibration):
        dimensional_calibrations = self.dimensional_calibrations
        while len(dimensional_calibrations) <= dimension:
            dimensional_calibrations.append(Calibration.Calibration())
        dimensional_calibrations[dimension] = calibration
        self.set_dimensional_calibrations(dimensional_calibrations)

    def set_metadata(self, metadata):
        with self._changes():
            self.__data_and_metadata._set_metadata(metadata)
            self._set_persistent_property_value("metadata", copy.deepcopy(metadata))
            self.__change_changed = True

    def update_metadata(self, additional_metadata):
        metadata = self.metadata
        metadata.update(additional_metadata)
        self.set_metadata(metadata)

    def storage_cache_changed(self, storage_cache):
        # override from Cacheable
        for display in self.displays:
            display.storage_cache = storage_cache

    def __insert_display(self, name, before_index, display):
        # listen
        with self._changes():
            self.__change_changed = True

    def __remove_display(self, name, index, display):
        display.about_to_be_removed()
        display.close()

    def add_display(self, display):
        self.append_item("displays", display)

    def remove_display(self, display):
        self.remove_item("displays", display)

    @property
    def has_data(self):
        return self.data_shape is not None and self.data_dtype is not None

    def __get_data(self):
        return self.__data_and_metadata.data if self.__data_and_metadata else None

    def __set_data(self, data, data_modified=None):
        dimensional_shape = Image.dimensional_shape_from_data(data)
        data_and_metadata = self.data_and_metadata
        intensity_calibration = data_and_metadata.intensity_calibration if data_and_metadata else None
        dimensional_calibrations = copy.deepcopy(data_and_metadata.dimensional_calibrations) if data_and_metadata else None
        if data_and_metadata:
            while len(dimensional_calibrations) < len(dimensional_shape):
                dimensional_calibrations.append(Calibration.Calibration())
            while len(dimensional_calibrations) > len(dimensional_shape):
                dimensional_calibrations.pop(-1)
        metadata = data_and_metadata.metadata if data_and_metadata else None
        timestamp = data_and_metadata.timestamp if data_and_metadata else None
        self.set_data_and_metadata(DataAndMetadata.DataAndMetadata.from_data(data, intensity_calibration, dimensional_calibrations, metadata, timestamp), data_modified)

    def increment_data_ref_count(self):
        with self.__data_ref_count_mutex:
            initial_count = self.__data_ref_count
            self.__data_ref_count += 1
            if initial_count == 0 and self.__data_and_metadata:
                self.__data_and_metadata.increment_data_ref_count()
        return initial_count+1

    def decrement_data_ref_count(self):
        with self.__data_ref_count_mutex:
            assert self.__data_ref_count > 0
            self.__data_ref_count -= 1
            final_count = self.__data_ref_count
            if final_count == 0 and self.__data_and_metadata:
                self.__data_and_metadata.decrement_data_ref_count()
        return final_count

    # used for testing
    @property
    def is_data_loaded(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_data_valid

    @property
    def has_data(self) -> bool:
        return self.__data_and_metadata is not None

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
            @master_data.setter
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
            if self.__change_count == 0:
                self.__change_thread = threading.current_thread()
            else:
                if self.__change_thread != threading.current_thread():
                    warnings.warn('begin changes from different threads', RuntimeWarning, stacklevel=2)
            self.__change_count += 1

    def _end_changes(self):
        changed = False
        with self.__change_count_lock:
            if self.__change_count == 1:
                self.__change_thread = None
            else:
                if self.__change_thread != threading.current_thread():
                    warnings.warn('end changes from different threads', RuntimeWarning, stacklevel=2)
            self.__change_count -= 1
            change_count = self.__change_count
            if change_count == 0:
                changed = self.__change_changed
                self.__change_changed = False
        # if the change count is now zero, it means that we're ready
        # to pass on the next value.
        if change_count == 0 and changed:
            data_and_metadata = self.data_and_metadata
            self.data_and_metadata_changed_event.fire()
            for display in self.displays:
                display.update_data(data_and_metadata)

    def r_value_changed(self):
        with self._changes():
            self.__change_changed = True

    @property
    def data_shape(self):
        return self.__data_and_metadata.data_shape if self.__data_and_metadata else None

    @property
    def data_dtype(self):
        return self.__data_and_metadata.data_dtype if self.__data_and_metadata else None

    @property
    def is_data_1d(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_data_1d

    @property
    def is_data_2d(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_data_2d

    @property
    def is_data_3d(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_data_3d

    @property
    def is_data_rgb(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_data_rgb

    @property
    def is_data_rgba(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_data_rgba

    @property
    def is_data_rgb_type(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_data_rgb_type

    @property
    def is_data_scalar_type(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_data_scalar_type

    @property
    def is_data_complex_type(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_data_complex_type

    @property
    def is_data_bool(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_data_bool

    def get_data_value(self, pos):
        return self.__data_and_metadata.get_data_value(pos) if self.__data_and_metadata else None

    @property
    def size_and_data_format_as_string(self):
        try:
            dimensional_shape = self.dimensional_shape
            data_dtype = self.data_dtype
            if dimensional_shape is not None and data_dtype is not None:
                spatial_shape_str = " x ".join([str(d) for d in dimensional_shape])
                if len(dimensional_shape) == 1:
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
                        logging.debug("Unknown dtype %s", self.data_dtype.type)
                    data_size_and_data_format_as_string = dtype_names[self.data_dtype.type] if self.data_dtype.type in dtype_names else _("Unknown Data Type")
                return "{0}, {1}".format(spatial_shape_str, data_size_and_data_format_as_string)
            return _("No Data")
        except Exception as e:
            import traceback
            traceback.print_exc()


# dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# time zone name is for display only and has no specified format

class DataItem(Observable.Observable, Cache.Cacheable, Persistence.PersistentObject):

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

    writer_version = 10

    def __init__(self, data=None, item_uuid=None):
        super(DataItem, self).__init__()
        global writer_version
        self.uuid = item_uuid if item_uuid else self.uuid
        self.__in_transaction_state = False
        self.__is_live = False
        self.__pending_write = True
        self.persistent_object_context = None
        self.define_property("created", datetime.datetime.utcnow(), converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        # windows utcnow has a resolution of 1ms, this sleep can guarantee unique times for all created times during a particular test.
        # this is not my favorite solution since it limits data item creation to 1000/s but until I find a better solution, this is my compromise.
        time.sleep(0.001)
        self.define_property("metadata", dict(), hidden=True, changed=self.__property_changed)
        self.define_property("source_file_path", validate=self.__validate_source_file_path, changed=self.__property_changed)
        self.define_property("session_id", validate=self.__validate_session_id, changed=self.__session_id_changed)
        self.define_property("data_item_uuids", list(), converter=UuidsToStringsConverter(), changed=self.__property_changed)
        self.define_property("category", "persistent", changed=self.__property_changed)
        self.define_property("session_metadata", dict(), copy_on_read=True, changed=self.__property_changed)
        self.define_relationship("data_sources", data_source_factory, insert=self.__insert_data_source, remove=self.__remove_data_source)
        self.define_relationship("connections", Connection.connection_factory, remove=self.__remove_connection)
        self.__get_data_item_by_uuid = None
        self.__data_items = list()
        self.__request_remove_listeners = list()
        self.__request_remove_region_listeners = list()
        self.__computation_changed_or_mutated_event_listeners = list()
        self.__data_and_metadata_changed_event_listeners = list()
        self.__metadata = dict()
        self.__metadata_lock = threading.RLock()
        self.metadata_changed_event = Event.Event()
        self.data_item_content_changed_event = Event.Event()
        self.request_remove_region_event = Event.Event()
        self.request_remove_data_item_event = Event.Event()
        self.computation_changed_or_mutated_event = Event.Event()
        self.__data_item_change_count = 0
        self.__data_item_change_count_lock = threading.RLock()
        self.__data_item_changes = set()
        self.__data_item_manager = None
        self.__data_item_manager_lock = threading.RLock()
        self.__suspendable_storage_cache = None
        self.r_var = None
        if data is not None:
            data_source = BufferedDataSource(data)
            self.append_data_source(data_source)
        self._about_to_be_removed = False
        self._closed = False

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
        for data_source in self.data_sources:
            self.__disconnect_data_source(0, data_source)
            data_source.close()
        for listener in self.__data_and_metadata_changed_event_listeners:
            listener.close()
        self.__data_and_metadata_changed_event_listeners = list()
        for connection in copy.copy(self.connections):
            connection.close()
        self.__get_data_item_by_uuid = None
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        self.request_remove_data_item_event = None
        for data_source in self.data_sources:
            data_source.about_to_be_removed()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

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

    def connect_data_items(self, data_items, lookup_data_item):
        for data_item_uuid in self.data_item_uuids:
            data_item = lookup_data_item(data_item_uuid)
            if data_item in data_items:
                self.__data_items.append(data_item)
        self.__get_data_item_by_uuid = lookup_data_item

    def append_data_item(self, data_item):
        self.insert_data_item(len(self.__data_items), data_item)

    def insert_data_item(self, before_index, data_item):
        assert data_item not in self.__data_items
        self.__data_items.insert(before_index, data_item)
        data_item_uuids = self.data_item_uuids
        data_item_uuids.insert(before_index, data_item.uuid)
        self.data_item_uuids = data_item_uuids
        self.notify_set_property("data_item_uuids", self.data_item_uuids)

    def remove_data_item(self, data_item):
        # index = self.__data_items.index(data_item)
        self.__data_items.remove(data_item)
        data_item_uuids = self.data_item_uuids
        data_item_uuids.remove(data_item.uuid)
        self.data_item_uuids = data_item_uuids
        self.notify_set_property("data_item_uuids", self.data_item_uuids)

    @property
    def data_items(self):
        return tuple(self.__data_items)

    def storage_cache_changed(self, storage_cache):
        # override from Cacheable to update the children that need updating
        self.__suspendable_storage_cache = Cache.SuspendableCache(storage_cache)
        for data_source in self.data_sources:
            data_source.storage_cache = self.__suspendable_storage_cache

    @property
    def _suspendable_storage_cache(self):
        return self.__suspendable_storage_cache

    @property
    def in_transaction_state(self) -> bool:
        return self.__in_transaction_state

    def __enter_write_delay_state(self):
        self.__write_delay_modified_count = self.modified_count
        if self.persistent_object_context:
            persistent_storage = self.persistent_object_context._get_persistent_storage_for_object(self)
            if persistent_storage:
                persistent_storage.write_delayed = True

    def __exit_write_delay_state(self):
        if self.persistent_object_context:
            persistent_storage = self.persistent_object_context._get_persistent_storage_for_object(self)
            if persistent_storage:
                persistent_storage.write_delayed = False
            if self.__pending_write or self.modified_count > self.__write_delay_modified_count:
                self.persistent_object_context.write_data_item(self)
            self.__pending_write = False

    def _enter_transaction_state(self):
        self.__in_transaction_state = True
        # first enter the write delay state.
        self.__enter_write_delay_state()
        # suspend disk caching
        if self.__suspendable_storage_cache:
            self.__suspendable_storage_cache.suspend_cache()
        # tell each data source to load its data.
        # this prevents paging in and out.
        for data_source in self.data_sources:
            data_source.increment_data_ref_count()

    def _exit_transaction_state(self):
        self.__in_transaction_state = False
        # being in the transaction state has the side effect of delaying the cache too.
        # spill whatever was into the local cache into the persistent cache.
        if self.__suspendable_storage_cache:
            self.__suspendable_storage_cache.spill_cache()
        # exit the write delay state.
        self.__exit_write_delay_state()
        # finally, tell each data source to unload its data.
        for data_source in self.data_sources:
            data_source.decrement_data_ref_count()

    def persistent_object_context_changed(self):
        # handle case where persistent object context is set on an item that is already under transaction.
        # this can occur during acquisition. any other cases?
        super(DataItem, self).persistent_object_context_changed()
        if self.__in_transaction_state:
            self.__enter_write_delay_state()

    def _test_get_file_path(self):
        if self.persistent_object_context:
            return self.persistent_object_context._test_get_file_path(self)
        return None

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
        if self.persistent_object_context:
            return self.persistent_object_context.get_properties(self)
        return dict()

    @property
    def is_live(self):
        """ Return whether this data item represents a live acquisition data item. """
        return self.__is_live

    def _enter_live_state(self):
        self.__is_live = True
        self.notify_data_item_content_changed(set([METADATA]))  # this will affect is_live, so notify

    def _exit_live_state(self):
        self.__is_live = False
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
            self.data_item_content_changed_event.fire(changes)

    def update_data_and_metadata(self, data_and_metadata: DataAndMetadata.DataAndMetadata, sub_area: Tuple[Tuple[int, int], Tuple[int, int]]=None) -> None:
        display_specifier = DisplaySpecifier.from_data_item(self)
        assert display_specifier.buffered_data_source and display_specifier.display
        with self.data_item_changes(), display_specifier.buffered_data_source._changes():
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                data = data_and_metadata.data
                data_matches = data_ref.master_data is not None and data.shape == data_ref.master_data.shape and data.dtype == data_ref.master_data.dtype
                if data_matches:
                    if sub_area is not None:
                        top = sub_area[0][0]
                        bottom = sub_area[0][0] + sub_area[1][0]
                        left = sub_area[0][1]
                        right = sub_area[0][1] + sub_area[1][1]
                        data_ref.master_data[top:bottom, left:right] = data[top:bottom, left:right]
                    else:
                        data_ref.master_data[:] = data[:]
                    data_ref.data_updated()  # trigger change notifications
                else:
                    data_ref.master_data = data.copy()
            # spatial calibrations
            dimensional_calibrations = data_and_metadata.dimensional_calibrations
            if len(dimensional_calibrations) == len(display_specifier.buffered_data_source.dimensional_shape):
                for dimension, dimension_calibration in enumerate(dimensional_calibrations):
                    display_specifier.buffered_data_source.set_dimensional_calibration(dimension, dimension_calibration)
            display_specifier.buffered_data_source.set_intensity_calibration(data_and_metadata.intensity_calibration)
            # properties (general tags)
            properties = data_and_metadata.metadata.get("hardware_source", dict())
            buffered_data_source = display_specifier.buffered_data_source
            metadata = buffered_data_source.metadata
            hardware_source_metadata = metadata.setdefault("hardware_source", dict())
            hardware_source_metadata.update(Utility.clean_dict(properties))
            buffered_data_source.set_metadata(metadata)

    def __validate_source_file_path(self, value):
        value = str(value) if value is not None else str()
        if value:
            value = os.path.normpath(value)
        return value

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
        self.__metadata_changed()

    @property
    def displayed_title(self):
        if self.r_var:
            return "{0} ({1})".format(self.title, self.r_var)
        else:
            return self.title

    # call this when the listeners need to be updated (via data_item_content_changed).
    # Calling this method will send the data_item_content_changed method to each listener by using the method
    # data_item_changes.
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
        tz_minutes = Utility.local_utcoffset_minutes(date_utc)
        date_local = date_utc + datetime.timedelta(minutes=tz_minutes)
        return date_local.strftime("%c")

    @property
    def created_local_as_string(self):
        return self.created_local.strftime("%c")

    @property
    def created_local(self):
        created_utc = self.created
        tz_minutes = Utility.local_utcoffset_minutes(created_utc)
        return created_utc + datetime.timedelta(minutes=tz_minutes)

    # access metadata

    @property
    def metadata(self):
        return copy.deepcopy(self._get_persistent_property_value("metadata"))

    def set_metadata(self, metadata):
        self._set_persistent_property_value("metadata", copy.deepcopy(metadata))

    def __computation_changed_or_mutated(self, data_source, computation):
        self.computation_changed_or_mutated_event.fire(self, data_source, computation)

    def __insert_data_source(self, name, before_index, data_source):
        data_source.set_dependent_data_item(self)
        data_source.set_data_item_manager(self.__data_item_manager)
        def notify_request_remove_data_item():
            # this message comes from the operation.
            # it is generated when the user deletes a graphic.
            # that informs the display which notifies the graphic which
            # notifies the operation which notifies this data item. ugh.
            if self.request_remove_data_item_event:
                self.request_remove_data_item_event.fire(self)
        request_remove_listener = data_source.request_remove_data_item_because_computation_removed_event.listen(notify_request_remove_data_item)
        self.__request_remove_listeners.insert(before_index, request_remove_listener)
        def request_remove_region(region_specifier):
            self.request_remove_region_event.fire(region_specifier)
        self.__request_remove_region_listeners.insert(before_index, data_source.request_remove_region_because_data_item_removed_event.listen(request_remove_region))
        self.__computation_changed_or_mutated_event_listeners.insert(before_index, data_source.computation_changed_or_mutated_event.listen(self.__computation_changed_or_mutated))
        self.__computation_changed_or_mutated(data_source, data_source.computation)
        # being in transaction state means that data sources have their data loaded.
        # so load data here to keep the books straight when the transaction state is exited.
        if self.__in_transaction_state:
            data_source.increment_data_ref_count()
        def data_and_metadata_changed():
            if not self._is_reading:
                self.data_item_content_changed_event.fire(set([DATA]))
        self.__data_and_metadata_changed_event_listeners.insert(before_index, data_source.data_and_metadata_changed_event.listen(data_and_metadata_changed))
        self.notify_data_item_content_changed(set([DATA]))
        # the document model watches for new data sources via observing.
        # send this message to make data_sources observable.
        self.notify_insert_item("data_sources", data_source, before_index)

    def __remove_data_source(self, name, index, data_source):
        data_source.about_to_be_removed()
        self.__disconnect_data_source(index, data_source)
        data_source.close()

    def __disconnect_data_source(self, index, data_source):
        self.__data_and_metadata_changed_event_listeners[index].close()
        del self.__data_and_metadata_changed_event_listeners[index]
        data_source.set_dependent_data_item(None)
        data_source.set_data_item_manager(None)
        self.__request_remove_listeners[index].close()
        del self.__request_remove_listeners[index]
        self.__request_remove_region_listeners[index].close()
        del self.__request_remove_region_listeners[index]
        self.__computation_changed_or_mutated_event_listeners[index].close()
        del self.__computation_changed_or_mutated_event_listeners[index]
        # being in transaction state means that data sources have their data loaded.
        # so unload data here to keep the books straight when the transaction state is exited.
        if self.__in_transaction_state:
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

    def __remove_connection(self, name, index, connection):
        connection.close()

    def set_data_item_manager(self, data_item_manager):
        """Set the data item manager. May be called from thread."""
        with self.__data_item_manager_lock:
            self.__data_item_manager = data_item_manager
            for data_source in self.data_sources:
                data_source.set_data_item_manager(self.__data_item_manager)

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(DataItem, self).notify_set_property(key, value)
        self.notify_data_item_content_changed(set([METADATA]))

    @property
    def maybe_data_source(self):
        return self.data_sources[0] if len(self.data_sources) == 1 else None

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
            assert isinstance(data_source, BufferedDataSource)
            data_source.increment_data_ref_count()
        for data_item in self.data_items:
            assert isinstance(data_item, DataItem)
            data_item.increment_data_ref_counts()

    def decrement_data_ref_counts(self):
        """Decrement data ref counts for each data source. Will have effect of unloading data if not used elsewhere."""
        for data_source in self.data_sources:
            assert isinstance(data_source, BufferedDataSource)
            data_source.decrement_data_ref_count()
        for data_item in self.data_items:
            assert isinstance(data_item, DataItem)
            data_item.decrement_data_ref_counts()

    # primary display

    @property
    def primary_display_specifier(self):
        if len(self.data_sources) == 1:
            return DisplaySpecifier(self, self.data_sources[0], self.data_sources[0].displays[0])
        return DisplaySpecifier()

    # descriptive metadata

    @property
    def title(self):
        return self.metadata.get("description", dict()).get("title", UNTITLED_STR)

    @title.setter
    def title(self, value):
        metadata = self.metadata
        metadata.setdefault("description", dict())["title"] = str(value) if value is not None else str()
        self.set_metadata(metadata)
        self.__metadata_property_changed("title", value)

    @property
    def caption(self):
        return self.metadata.get("description", dict()).get("caption", str())

    @caption.setter
    def caption(self, value):
        metadata = self.metadata
        metadata.setdefault("description", dict())["caption"] = str(value) if value is not None else str()
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
