# standard libraries
import abc
import copy
import datetime
import gettext
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
        try:
            if len(value) == 26:
                return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f")
            elif len(value) == 19:
                return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
        except ValueError as e:
            pass  # fall through
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


class BufferedDataSource(Observable.Observable, Persistence.PersistentObject):

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
        self.__container_weak_ref = None
        self.define_type("buffered-data-source")
        data_shape = data.shape if data is not None else None
        data_dtype = data.dtype if data is not None else None
        # windows utcnow has a resolution of 1ms, this sleep can guarantee unique times for all created times during a particular test.
        # this is not my favorite solution since it limits data item creation to 1000/s but until I find a better solution, this is my compromise.
        self.define_property("data_shape", data_shape, hidden=True, recordable=False)
        self.define_property("data_dtype", data_dtype, hidden=True, recordable=False, converter=DtypeToStringConverter())
        self.define_property("is_sequence", False, recordable=False, changed=self.__data_description_changed)
        dimensional_shape = Image.dimensional_shape_from_shape_and_dtype(data_shape, data_dtype)
        collection_dimension_count = (2 if len(dimensional_shape) == 3 else 0) if dimensional_shape is not None else None
        datum_dimension_count = len(dimensional_shape) - collection_dimension_count if dimensional_shape is not None else None
        self.define_property("collection_dimension_count", collection_dimension_count, recordable=False, changed=self.__data_description_changed)
        self.define_property("datum_dimension_count", datum_dimension_count, recordable=False, changed=self.__data_description_changed)
        self.define_property("intensity_calibration", Calibration.Calibration(), hidden=True, make=Calibration.Calibration, changed=self.__metadata_property_changed)
        self.define_property("dimensional_calibrations", CalibrationList(), hidden=True, make=CalibrationList, changed=self.__dimensional_calibrations_changed)
        self.define_property("created", datetime.datetime.utcnow(), converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        self.define_property("source_data_modified", converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        self.define_property("data_modified", recordable=False, converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        self.define_property("metadata", dict(), hidden=True, changed=self.__metadata_property_changed)
        self.define_item("computation", computation_factory)  # will be deep copied when copying, needs explicit set method set_computation
        self.define_relationship("displays", Display.display_factory, insert=self.__insert_display, remove=self.__remove_display)
        self.__timezone = None  # set by the data item, used when returning data_and_metadata
        self.__timezone_offset = None  # set by the data item, used when returning data_and_metadata
        self.__data_and_metadata = None
        self.__data_and_metadata_lock = threading.RLock()
        self.__intensity_calibration = None
        self.__dimensional_calibrations = None
        self.__metadata = dict()
        self.__change_thread = None
        self.__change_count = 0
        self.__change_count_lock = threading.RLock()
        self.__change_changed = False
        self.__data_ref_count = 0
        self.__data_ref_count_mutex = threading.RLock()
        self.__subscription = None
        self.data_item_changed_event = Event.Event()
        self.data_changed_event = Event.Event()
        self.metadata_changed_event = Event.Event()
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
        self.__data_and_metadata = None
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None

    @property
    def container(self):
        return self.__container_weak_ref()

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        for display in self.displays:
            display.about_to_be_removed()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

    def insert_model_item(self, container, name, before_index, item):
        if self.__container_weak_ref:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item):
        if self.__container_weak_ref:
            self.container.remove_model_item(container, name, item)
        else:
            container.remove_item(name, item)

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
            data_and_metadata = copy.deepcopy(data_and_metadata) if data_and_metadata else None
            self.set_data_and_metadata(data_and_metadata)
            # displays
            for display in self.displays:
                self.remove_display(display)
            for display in buffered_data_source.displays:
                self.add_display(copy.deepcopy(display))

    def clone(self) -> "BufferedDataSource":
        data_source = BufferedDataSource(create_display=False)
        data_source.uuid = self.uuid
        for display in self.displays:
            data_source.add_display(display.clone())
        return data_source

    def snapshot(self):
        """
            Take a snapshot and return a new buffered data source. A snapshot is a copy of everything
            except the data and operation which are replaced by new data with the operation
            applied or "burned in".
        """
        buffered_data_source_copy = BufferedDataSource()
        buffered_data_source_copy.set_data_and_metadata(copy.deepcopy(self.data_and_metadata))
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
                dimensional_shape = Image.dimensional_shape_from_shape_and_dtype(data_shape, data_dtype)
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
                if timestamp is None:  # invalid timestamp -- set property to now but don't trigger change
                    timestamp = datetime.datetime.now()
                    self._get_persistent_property("created").value = timestamp
                is_sequence = self._get_persistent_property_value("is_sequence", False)
                collection_dimension_count = self._get_persistent_property_value("collection_dimension_count")
                datum_dimension_count = self._get_persistent_property_value("datum_dimension_count")
                if collection_dimension_count is None:
                    collection_dimension_count = 2 if len(dimensional_shape) == 3 and not is_sequence else 0
                    # update collection_dimension_count, but in a way that sets the internal value but
                    # doesn't trigger a write to disk or a change modification.
                    self._get_persistent_property("collection_dimension_count").set_value(collection_dimension_count)
                if datum_dimension_count is None:
                    datum_dimension_count = len(dimensional_shape) - collection_dimension_count - (1 if is_sequence else 0)
                    # update collection_dimension_count, but in a way that sets the internal value but
                    # doesn't trigger a write to disk or a change modification.
                    self._get_persistent_property("datum_dimension_count").set_value(datum_dimension_count)
                data_descriptor = DataAndMetadata.DataDescriptor(is_sequence, collection_dimension_count, datum_dimension_count)
                self.__data_and_metadata = DataAndMetadata.DataAndMetadata(self.__load_data, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp,
                                                                           data_descriptor=data_descriptor, timezone=self.timezone, timezone_offset=self.timezone_offset)
                with self.__data_ref_count_mutex:
                    self.__data_and_metadata._add_data_ref_count(self.__data_ref_count)
                self.__data_and_metadata.unloadable = self.persistent_object_context is not None
            for display in self.displays:
                display.validate_slice_indexes()  # do this here to avoid having changes happen outside of _changes

    def finish_reading(self):
        for display in self.displays:
            display.update_data(self.data_and_metadata)
        super(BufferedDataSource, self).finish_reading()

    def persistent_object_context_changed(self):
        super().persistent_object_context_changed()
        if self.__data_and_metadata:
            self.__data_and_metadata.unloadable = self.persistent_object_context is not None

    def set_dependent_data_item(self, data_item):
        self.__weak_dependent_data_item = weakref.ref(data_item) if data_item else None

    def __get_dependent_data_item(self):
        return self.__weak_dependent_data_item() if self.__weak_dependent_data_item else None

    @property
    def _data_item(self):
        return self.__get_dependent_data_item()

    def __data_description_changed(self, name, value):
        self.__property_changed(name, value)
        self.__metadata_changed()

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
        self.notify_property_changed(name)

    def _set_computation(self, computation):
        self.set_item("computation", computation)

    @property
    def timezone(self):
        return self.__timezone

    @timezone.setter
    def timezone(self, value):
        self.__timezone = value
        if self.__data_and_metadata:
            self.__data_and_metadata.data_metadata.timezone = self.__timezone

    @property
    def timezone_offset(self):
        return self.__timezone_offset

    @timezone_offset.setter
    def timezone_offset(self, value):
        self.__timezone_offset = value
        if self.__data_and_metadata:
            self.__data_and_metadata.data_metadata.timezone_offset = self.__timezone_offset

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
            self._set_persistent_property_value("is_sequence", self.__data_and_metadata.is_sequence)
            self._set_persistent_property_value("collection_dimension_count", self.__data_and_metadata.collection_dimension_count)
            self._set_persistent_property_value("datum_dimension_count", self.__data_and_metadata.datum_dimension_count)
            self._set_persistent_property_value("intensity_calibration", self.__data_and_metadata.intensity_calibration)
            self._set_persistent_property_value("dimensional_calibrations", CalibrationList(self.__data_and_metadata.dimensional_calibrations))
            metadata_copy = copy.deepcopy(self.__data_and_metadata.metadata)
            self.__metadata = metadata_copy
            self._set_persistent_property_value("metadata", metadata_copy)
        self.data_modified = data_modified if data_modified else datetime.datetime.utcnow()
        self.data_changed_event.fire(self)

    def set_data_and_metadata(self, data_and_metadata, data_modified=None):
        """Sets the underlying data and data-metadata to the data_and_metadata.

        Note: this does not make a copy of the data.
        """
        with self._changes():
            self.increment_data_ref_count()
            try:
                if data_and_metadata:
                    data = data_and_metadata.data
                    data_shape_and_dtype = data_and_metadata.data_shape_and_dtype
                    intensity_calibration = data_and_metadata.intensity_calibration
                    dimensional_calibrations = data_and_metadata.dimensional_calibrations
                    metadata = data_and_metadata.metadata
                    timestamp = data_and_metadata.timestamp
                    data_descriptor = data_and_metadata.data_descriptor
                    new_data_and_metadata = DataAndMetadata.DataAndMetadata(self.__load_data, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp, data, data_descriptor)
                else:
                    new_data_and_metadata = None
                self.__set_data_metadata_direct(new_data_and_metadata, data_modified)
                if self.__data_and_metadata is not None:
                    if self.persistent_object_context:
                        self.persistent_object_context.rewrite_data_item_data(self._data_item)  # ouch, up reference to data item
                        self.__data_and_metadata.unloadable = True
                self.__change_changed = True
            finally:
                self.decrement_data_ref_count()

    def set_data(self, data: numpy.ndarray, data_modified: datetime.datetime=None) -> None:
        self.set_data_and_metadata(DataAndMetadata.new_data_and_metadata(data, data_modified))

    @property
    def data_shape_and_dtype(self) -> typing.Tuple[typing.Iterable[int], numpy.dtype]:
        return self.__data_and_metadata.data_shape_and_dtype if self.__data_and_metadata else None

    @property
    def dimensional_shape(self):
        return self.__data_and_metadata.dimensional_shape if self.__data_and_metadata else None

    @property
    def is_collection(self):
        return self.collection_dimension_count > 0 if self.collection_dimension_count is not None else False

    @property
    def intensity_calibration(self):
        return copy.deepcopy(self.__data_and_metadata.intensity_calibration) if self.__data_and_metadata else self.__intensity_calibration

    @intensity_calibration.setter
    def intensity_calibration(self, intensity_calibration):
        """ Set the intensity calibration. """
        with self._changes():
            if self.__data_and_metadata:  # handle case of missing data and metadata but doing recording
                self.__data_and_metadata._set_intensity_calibration(intensity_calibration)
            self.__intensity_calibration = copy.deepcopy(intensity_calibration)  # backup in case of no data and metadata
            self._set_persistent_property_value("intensity_calibration", intensity_calibration)
            self.__change_changed = True

    def set_intensity_calibration(self, intensity_calibration):
        self.intensity_calibration = intensity_calibration

    @property
    def dimensional_calibrations(self):
        return copy.deepcopy(self.__data_and_metadata.dimensional_calibrations) if self.__data_and_metadata else self.__dimensional_calibrations

    @dimensional_calibrations.setter
    def dimensional_calibrations(self, dimensional_calibrations):
        """ Set the dimensional calibrations. """
        with self._changes():
            if self.__data_and_metadata:  # handle case of missing data and metadata but doing recording
                self.__data_and_metadata._set_dimensional_calibrations(dimensional_calibrations)
            self.__dimensional_calibrations = copy.deepcopy(dimensional_calibrations)  # backup in case of no data and metadata
            self._set_persistent_property_value("dimensional_calibrations", CalibrationList(dimensional_calibrations))
            self.__change_changed = True

    def set_dimensional_calibrations(self, dimensional_calibrations):
        self.dimensional_calibrations = dimensional_calibrations

    def set_dimensional_calibration(self, dimension, calibration):
        dimensional_calibrations = self.dimensional_calibrations
        while len(dimensional_calibrations) <= dimension:
            dimensional_calibrations.append(Calibration.Calibration())
        dimensional_calibrations[dimension] = calibration
        self.set_dimensional_calibrations(dimensional_calibrations)

    @property
    def metadata(self):
        return copy.deepcopy(self.__data_and_metadata.metadata) if self.__data_and_metadata else self.__metadata

    @metadata.setter
    def metadata(self, metadata):
        assert metadata is not None
        with self._changes():
            self.__data_and_metadata._set_metadata(metadata)
            self.__metadata = copy.deepcopy(metadata)
            self._set_persistent_property_value("metadata", self.__metadata)
            self.__change_changed = True

    def set_metadata(self, metadata):
        self.metadata = metadata

    def update_metadata(self, additional_metadata):
        metadata = self.metadata
        metadata.update(additional_metadata)
        self.metadata = metadata

    def set_storage_cache(self, storage_cache):
        for display in self.displays:
            display.set_storage_cache(storage_cache)

    def __insert_display(self, name, before_index, display):
        display.about_to_be_inserted(self)
        with self._changes():
            self.__change_changed = True

    def __remove_display(self, name, index, display):
        display.about_to_be_removed()
        display.close()

    def add_display(self, display):
        """Add a display, but do it through the container, so dependencies can be tracked."""
        self.insert_model_item(self, "displays", self.item_count("displays"), display)

    def remove_display(self, display):
        """Remove display, but do it through the container, so dependencies can be tracked."""
        self.remove_model_item(self, "displays", display)

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
        timestamp = None  # always update when the data is modified
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
            self.data_item_changed_event.fire()
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
    def is_data_4d(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_data_4d

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
        return self.__data_and_metadata.size_and_data_format_as_string if self.__data_and_metadata else _("No Data")


class SessionManager(abc.ABC):

    @property
    @abc.abstractmethod
    def current_session_id(self) -> str:
        pass


# dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# time zone name is for display only and has no specified format

class LibraryItem(Observable.Observable, Persistence.PersistentObject):
    """
    Data items represent a data, metadata, display, and graphics within a library.

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

    *Miscellaneous*

    Transactions.

    Live state.

    Snapshots and deep copies.

    Properties.

    Metadata.
    """

    writer_version = 10

    def __init__(self, item_uuid=None):
        super().__init__()
        global writer_version
        self.uuid = item_uuid if item_uuid else self.uuid
        self.__container_weak_ref = None
        self.__in_transaction_state = False
        self.__is_live = False
        self.__pending_write = True
        self.__write_delay_modified_count = 0
        self.persistent_object_context = None
        self.define_property("created", datetime.datetime.utcnow(), converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        # windows utcnow has a resolution of 1ms, this sleep can guarantee unique times for all created times during a particular test.
        # this is not my favorite solution since it limits library item creation to 1000/s but until I find a better solution, this is my compromise.
        time.sleep(0.001)
        self.define_property("metadata", dict(), hidden=True, changed=self.__property_changed)
        self.define_property("source_file_path", validate=self.__validate_source_file_path, changed=self.__property_changed)
        self.define_property("session_id", validate=self.__validate_session_id, changed=self.__session_id_changed)
        self.define_property("category", "persistent", changed=self.__property_changed)
        self.define_property("session_metadata", dict(), copy_on_read=True, changed=self.__property_changed)
        self.define_property("timezone", Utility.get_local_timezone(), changed=self.__timezone_property_changed)
        self.define_property("timezone_offset", Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes()), changed=self.__timezone_property_changed)
        self.define_relationship("connections", Connection.connection_factory, remove=self.__remove_connection)
        self.__session_manager = None
        self.__metadata = dict()
        self.__metadata_lock = threading.RLock()
        self.metadata_changed_event = Event.Event()
        self.data_item_content_changed_event = Event.Event()
        self.__change_count = 0
        self.__change_count_lock = threading.RLock()
        self.__content_changed = False
        self.__suspendable_storage_cache = None
        self.r_var = None
        self._about_to_be_removed = False
        self._closed = False

    def __str__(self):
        return "{0} {1} ({2}, {3})".format(self.__repr__(), (self.title if self.title else _("Untitled")), str(self.uuid), self.date_for_sorting_local_as_string)

    def __copy__(self):
        assert False

    def __deepcopy__(self, memo):
        library_item_copy = self.__class__()
        # metadata
        library_item_copy.metadata = self.metadata
        library_item_copy.session_metadata = self.session_metadata
        library_item_copy.created = self.created
        library_item_copy.timezone = self.timezone
        library_item_copy.timezone_offset = self.timezone_offset
        library_item_copy.session_id = self.session_id
        library_item_copy.source_file_path = self.source_file_path
        memo[id(self)] = library_item_copy
        return library_item_copy

    def close(self):
        for connection in copy.copy(self.connections):
            connection.close()
        # close the storage handler
        if self.persistent_object_context:
            persistent_storage = self.persistent_object_context._get_persistent_storage_for_object(self)
            if persistent_storage:
                persistent_storage.close()
            self.persistent_object_context._set_persistent_storage_for_object(self, None)
            self.persistent_object_context = None
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None

    @property
    def container(self):
        return self.__container_weak_ref()

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

    def insert_model_item(self, container, name, before_index, item):
        """Insert a model item. Let this item's container do it if possible; otherwise do it directly.
        
        Passing responsibility to this item's container allows the library to easily track dependencies.
        However, if this item isn't yet in the library hierarchy, then do the operation directly.
        """
        if self.__container_weak_ref:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item):
        """Remove a model item. Let this item's container do it if possible; otherwise do it directly.
        
        Passing responsibility to this item's container allows the library to easily track dependencies.
        However, if this item isn't yet in the library hierarchy, then do the operation directly.
        """
        if self.__container_weak_ref:
            self.container.remove_model_item(container, name, item)
        else:
            container.remove_item(name, item)

    def clone(self) -> "LibraryItem":
        library_item = self.__class__()
        library_item.uuid = self.uuid
        for connection in self.connections:
            library_item.add_connection(connection.clone())
        return library_item

    def snapshot(self):
        """Return a new library item which is a copy of this one with any dynamic behavior made static."""
        libary_item = self.__class__()
        # metadata
        libary_item.metadata = self.metadata
        libary_item.session_metadata = self.session_metadata
        libary_item.created = self.created
        libary_item.timezone = self.timezone
        libary_item.timezone_offset = self.timezone_offset
        libary_item.session_id = self.session_id
        libary_item.source_file_path = self.source_file_path
        return libary_item

    def connect_data_items(self, data_items, lookup_data_item):
        pass

    def set_storage_cache(self, storage_cache):
        self.__suspendable_storage_cache = Cache.SuspendableCache(storage_cache)

    @property
    def _suspendable_storage_cache(self):
        return self.__suspendable_storage_cache

    @property
    def in_transaction_state(self) -> bool:
        return self.__in_transaction_state

    def _enter_write_delay_state_inner(self):
        pass

    def _finish_pending_write_inner(self):
        pass

    def __enter_write_delay_state(self):
        self.__write_delay_modified_count = self.modified_count
        self._enter_write_delay_state_inner()
        if self.persistent_object_context:
            persistent_storage = self.persistent_object_context._get_persistent_storage_for_object(self)
            if persistent_storage:
                persistent_storage.write_delayed = True

    def __exit_write_delay_state(self):
        if self.persistent_object_context:
            persistent_storage = self.persistent_object_context._get_persistent_storage_for_object(self)
            if persistent_storage:
                persistent_storage.write_delayed = False
            self._finish_pending_write()

    def _finish_write(self):
        pass

    def _finish_pending_write(self):
        if self.__pending_write:
            self.persistent_object_context.write_data_item(self)
            self.__pending_write = False
        else:
            if self.modified_count > self.__write_delay_modified_count:
                self.persistent_object_context.rewrite_data_item_properties(self)
            self._finish_pending_write_inner()

    def _enter_transaction_state(self):
        self.__in_transaction_state = True
        # first enter the write delay state.
        self.__enter_write_delay_state()
        # suspend disk caching
        if self.__suspendable_storage_cache:
            self.__suspendable_storage_cache.suspend_cache()

    def _exit_transaction_state(self):
        self.__in_transaction_state = False
        # being in the transaction state has the side effect of delaying the cache too.
        # spill whatever was into the local cache into the persistent cache.
        if self.__suspendable_storage_cache:
            self.__suspendable_storage_cache.spill_cache()
        # exit the write delay state.
        self.__exit_write_delay_state()

    def persistent_object_context_changed(self):
        # handle case where persistent object context is set on an item that is already under transaction.
        # this can occur during acquisition. any other cases?
        super().persistent_object_context_changed()
        if self.__in_transaction_state:
            self.__enter_write_delay_state()

    def update_and_bind_computation(self, computation_context):
        pass

    def data_item_was_inserted(self, computation_context):
        pass

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
            self._read_from_dict_inner(properties)
            if self.created is None:  # invalid timestamp -- set property to now but don't trigger change
                timestamp = datetime.datetime.now()
                self._get_persistent_property("created").value = timestamp
            self.__content_changed = False
        self.__pending_write = False

    def _read_from_dict_inner(self, properties):
        super().read_from_dict(properties)

    @property
    def properties(self):
        """ Used for debugging. """
        if self.persistent_object_context:
            return self.persistent_object_context.get_properties(self)
        return dict()

    @property
    def is_live(self):
        """Return whether this library item represents live acquisition."""
        return self.__is_live

    def _enter_live_state(self):
        self.__is_live = True
        self._notify_library_item_content_changed()  # this will affect is_live, so notify

    def _exit_live_state(self):
        self.__is_live = False
        self._notify_library_item_content_changed()  # this will affect is_live, so notify

    def __validate_session_id(self, value):
        assert value is None or datetime.datetime.strptime(value, "%Y%m%d-%H%M%S")
        return value

    def __session_id_changed(self, name, value):
        self.__property_changed(name, value)

    def data_item_changes(self):
        # return a context manager to batch up a set of changes so that listeners
        # are only notified after the last change is complete.
        library_item = self
        class LibraryItemChangeContextManager(object):
            def __enter__(self):
                library_item._begin_library_item_changes()
                return self
            def __exit__(self, type, value, traceback):
                library_item._end_library_item_changes()
        return LibraryItemChangeContextManager()

    def _begin_library_item_changes(self):
        with self.__change_count_lock:
            self.__change_count += 1

    def _end_library_item_changes(self):
        with self.__change_count_lock:
            self.__change_count -= 1
            change_count = self.__change_count
            content_changed = self.__content_changed
        # if the change count is now zero, it means that we're ready to notify listeners. but only notify listeners if
        # there are actual changes to report.
        if change_count == 0 and content_changed:
            self.data_item_content_changed_event.fire()

    def __validate_source_file_path(self, value):
        value = str(value) if value is not None else str()
        if value:
            value = os.path.normpath(value)
        return value

    def __metadata_property_changed(self, name, value):
        self.__property_changed(name, value)
        self.__metadata_changed()

    def __metadata_changed(self):
        self._notify_library_item_content_changed()
        self.metadata_changed_event.fire()

    def __property_changed(self, name, value):
        self.notify_property_changed(name)

    def __timezone_property_changed(self, name, value):
        self._update_timezone()
        self.__property_changed(name, value)

    def _update_timezone(self):
        pass

    def set_r_value(self, r_var: str) -> None:
        """Used to signal changes to the ref var, which are kept in document controller. ugh."""
        self.r_var = r_var
        self._r_value_changed()
        self.__metadata_changed()

    def _r_value_changed(self):
        pass

    def increment_display_ref_count(self):
        """Increment display reference count to indicate this library item is currently displayed."""
        pass

    def decrement_display_ref_count(self):
        """Decrement display reference count to indicate this library item is no longer displayed."""
        pass

    @property
    def displayed_title(self):
        if self.r_var:
            return "{0} ({1})".format(self.title, self.r_var)
        else:
            return self.title

    # call this when the listeners need to be updated (via data_item_content_changed).
    # Calling this method will send the data_item_content_changed method to each listener by using the method
    # data_item_changes.
    def _notify_library_item_content_changed(self):
        with self.data_item_changes():
            with self.__change_count_lock:
                self.__content_changed = True

    # date times

    @property
    def date_for_sorting(self):
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

    @metadata.setter
    def metadata(self, metadata):
        assert metadata is not None
        self._set_persistent_property_value("metadata", copy.deepcopy(metadata))

    def set_metadata(self, metadata):
        self.metadata = metadata

    @property
    def _session_manager(self) -> SessionManager:
        return self.__session_manager

    def set_session_manager(self, session_manager: SessionManager) -> None:
        self.__session_manager = session_manager

    def add_connection(self, connection):
        self.append_item("connections", connection)

    def remove_connection(self, connection):
        self.remove_item("connections", connection)

    def __remove_connection(self, name, index, connection):
        connection.close()

    # override from storage to watch for changes to this library item. notify observers.
    def notify_property_changed(self, key):
        super().notify_property_changed(key)
        self._notify_library_item_content_changed()

    @property
    def computation(self) -> typing.Optional[Symbolic.Computation]:
        return None

    # descriptive metadata

    @property
    def title(self):
        return self.metadata.get("description", dict()).get("title", UNTITLED_STR)

    @title.setter
    def title(self, value):
        metadata = self.metadata
        metadata.setdefault("description", dict())["title"] = str(value) if value is not None else str()
        self.metadata = metadata
        self.__metadata_property_changed("title", value)

    @property
    def caption(self):
        return self.metadata.get("description", dict()).get("caption", str())

    @caption.setter
    def caption(self, value):
        metadata = self.metadata
        metadata.setdefault("description", dict())["caption"] = str(value) if value is not None else str()
        self.metadata = metadata
        self.__metadata_property_changed("caption", value)

    @property
    def flag(self):
        return self.metadata.get("description", dict()).get("flag", 0)

    @flag.setter
    def flag(self, value):
        metadata = self.metadata
        metadata.setdefault("description", dict())["flag"] = max(min(int(value), 1), -1)
        self.metadata = metadata
        self.__metadata_property_changed("flag", value)

    @property
    def rating(self):
        return self.metadata.get("description", dict()).get("rating", 0)

    @rating.setter
    def rating(self, value):
        metadata = self.metadata
        metadata.setdefault("description", dict())["rating"] = min(max(int(value), 0), 5)
        self.metadata = metadata
        self.__metadata_property_changed("rating", value)

    @property
    def text_for_filter(self):
        return " ".join([self.displayed_title, self.caption])


class CompositeLibraryItem(LibraryItem):
    def __init__(self, item_uuid=None):
        super().__init__(item_uuid=item_uuid)
        self.define_property("data_item_uuids", list(), converter=UuidsToStringsConverter(), changed=self.__property_changed)
        self.__data_items = list()

    def __property_changed(self, name, value):
        self.notify_property_changed(name)

    @property
    def data_items(self):
        return tuple(self.__data_items)

    def connect_data_items(self, data_items, lookup_data_item):
        super().connect_data_items(data_items, lookup_data_item)
        for data_item_uuid in self.data_item_uuids:
            data_item = lookup_data_item(data_item_uuid)
            if data_item in data_items:
                self.__data_items.append(data_item)

    def append_data_item(self, data_item):
        self.insert_data_item(len(self.__data_items), data_item)

    def insert_data_item(self, before_index, data_item):
        assert data_item not in self.__data_items
        self.__data_items.insert(before_index, data_item)
        data_item_uuids = self.data_item_uuids
        data_item_uuids.insert(before_index, data_item.uuid)
        self.data_item_uuids = data_item_uuids
        self.notify_property_changed("data_item_uuids")

    def remove_data_item(self, data_item):
        # index = self.__data_items.index(data_item)
        self.__data_items.remove(data_item)
        data_item_uuids = self.data_item_uuids
        data_item_uuids.remove(data_item.uuid)
        self.data_item_uuids = data_item_uuids
        self.notify_property_changed("data_item_uuids")

    def increment_display_ref_count(self):
        super().increment_display_ref_count()
        for data_item in self.data_items:
            data_item.increment_display_ref_count()

    def decrement_display_ref_count(self):
        super().decrement_display_ref_count()
        for data_item in self.data_items:
            data_item.decrement_display_ref_count()


class DataItem(LibraryItem):

    def __init__(self, data=None, item_uuid=None, large_format=False):
        super().__init__(item_uuid)
        self.large_format = large_format
        self.define_relationship("data_sources", data_source_factory, insert=self.__insert_data_source, remove=self.__remove_data_source)
        self.__write_delay_data_changed = False
        self.__data_item_changed_event_listeners = list()
        self.__data_changed_event_listeners = list()
        if data is not None:
            data_source = BufferedDataSource(data)
            self.append_data_source(data_source)

    def __deepcopy__(self, memo):
        data_item_copy = super().__deepcopy__(memo)
        # format
        data_item_copy.large_format = self.large_format
        # data sources
        for data_source in copy.copy(data_item_copy.data_sources):
            data_item_copy.remove_data_source(data_source)
        for data_source in self.data_sources:
            data_item_copy.append_data_source(copy.deepcopy(data_source))
        return data_item_copy

    def close(self):
        for data_source in self.data_sources:
            self.__disconnect_data_source(0, data_source)
            data_source.close()
        for listener in self.__data_item_changed_event_listeners:
            listener.close()
        self.__data_item_changed_event_listeners = list()
        for listener in self.__data_changed_event_listeners:
            listener.close()
        self.__data_changed_event_listeners = list()
        super().close()

    def about_to_be_removed(self):
        for data_source in self.data_sources:
            data_source.about_to_be_removed()
        super().about_to_be_removed()

    def clone(self) -> "DataItem":
        data_item = super().clone()
        for data_source in self.data_sources:
            data_item.append_data_source(data_source.clone())
        return data_item

    def snapshot(self):
        data_item = super().snapshot()
        # format
        data_item.large_format = self.large_format
        # data sources
        for data_source in copy.copy(data_item.data_sources):
            data_item.remove_data_source(data_source)
        for data_source in self.data_sources:
            data_item.append_data_source(data_source.snapshot())
        return data_item

    def set_storage_cache(self, storage_cache):
        super().set_storage_cache(storage_cache)
        for data_source in self.data_sources:
            data_source.set_storage_cache(self._suspendable_storage_cache)

    def _enter_transaction_state(self):
        super()._enter_transaction_state()
        # tell each data source to load its data.
        # this prevents paging in and out.
        for data_source in self.data_sources:
            data_source.increment_data_ref_count()

    def _exit_transaction_state(self):
        super()._exit_transaction_state()
        # finally, tell each data source to unload its data.
        for data_source in self.data_sources:
            data_source.decrement_data_ref_count()

    def _read_from_dict_inner(self, properties):
        for data_source in copy.copy(self.data_sources):
            self.remove_data_source(data_source)
        super()._read_from_dict_inner(properties)

    def _finish_write(self):
        super()._finish_write()
        if self.maybe_data_source:
            self.persistent_object_context.rewrite_data_item_data(self)

    def _enter_write_delay_state_inner(self):
        super()._enter_write_delay_state_inner()
        self.__write_delay_data_changed = False

    def _finish_pending_write_inner(self):
        super()._finish_pending_write_inner()
        if self.__write_delay_data_changed:
            self.persistent_object_context.rewrite_data_item_data(self)

    def _r_value_changed(self):
        for data_source in self.data_sources:
            data_source.r_value_changed()

    def update_and_bind_computation(self, computation_context):
        super().update_and_bind_computation(computation_context)
        for buffered_data_source in self.data_sources:
            computation = buffered_data_source.computation
            if computation:
                try:
                    self.__update_computation(computation, computation_context._processing_descriptions)
                    computation.bind(computation_context)
                except Exception as e:
                    print(str(e))

    def __update_computation(self, computation: Symbolic.Computation, processing_descriptions) -> None:
        processing_id = computation.processing_id
        processing_description = processing_descriptions.get(processing_id)
        if processing_description:
            src_names = list()
            src_texts = list()
            source_dicts = processing_description["sources"]
            for i, source_dict in enumerate(source_dicts):
                src_names.append(source_dict["name"])
                data_expression = source_dict["name"] + (".display_xdata" if source_dict.get("use_display_data", True) else ".xdata")
                if source_dict.get("croppable", False):
                    crop_region_variable_name = "crop_region" + "" if len(source_dicts) == 1 else str(i)
                    if computation._has_variable(crop_region_variable_name):
                        data_expression = "xd.crop(" + data_expression + ", " + crop_region_variable_name + ".bounds)"
                src_texts.append(data_expression)
            script = processing_description.get("script")
            if not script:
                expression = processing_description.get("expression")
                if expression:
                    script = Symbolic.xdata_expression(expression)
            script = script.format(**dict(zip(src_names, src_texts)))
            computation._get_persistent_property("original_expression").value = script

    def data_item_was_inserted(self, computation_context):
        super().data_item_was_inserted(computation_context)
        for data_source in self.data_sources:
            if data_source.computation:
                data_source.computation.bind(computation_context)

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
        return super().date_for_sorting

    def update_data_and_metadata(self, data_and_metadata: DataAndMetadata.DataAndMetadata) -> None:
        assert threading.current_thread() == threading.main_thread()
        display_specifier = DisplaySpecifier.from_data_item(self)
        assert display_specifier.buffered_data_source and display_specifier.display
        with self.data_item_changes():
            display_specifier.buffered_data_source.set_data_and_metadata(data_and_metadata)
            self.timezone = Utility.get_local_timezone()
            self.timezone_offset = Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes())

    def __handle_data_changed(self, data_source):
        self.timezone = Utility.get_local_timezone()
        self.timezone_offset = Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes())
        if self._session_manager:
            self.session_id = self._session_manager.current_session_id

    def __insert_data_source(self, name, before_index, data_source):
        data_source.about_to_be_inserted(self)
        data_source.timezone = self.timezone
        data_source.timezone_offset = self.timezone_offset
        data_source.set_dependent_data_item(self)
        self.__data_changed_event_listeners.insert(before_index, data_source.data_changed_event.listen(self.__handle_data_changed))
        # being in transaction state means that data sources have their data loaded.
        # so load data here to keep the books straight when the transaction state is exited.
        if self.in_transaction_state:
            data_source.increment_data_ref_count()
        def data_item_changed():
            if not self._is_reading:
                self.__write_delay_data_changed = True
                self._notify_library_item_content_changed()
        self.__data_item_changed_event_listeners.insert(before_index, data_source.data_item_changed_event.listen(data_item_changed))
        self._notify_library_item_content_changed()
        # the document model watches for new data sources via observing.
        # send this message to make data_sources observable.
        self.notify_insert_item("data_sources", data_source, before_index)

    def __remove_data_source(self, name, index, data_source):
        data_source.about_to_be_removed()
        self.__disconnect_data_source(index, data_source)
        data_source.close()

    def __disconnect_data_source(self, index, data_source):
        self.__data_item_changed_event_listeners[index].close()
        del self.__data_item_changed_event_listeners[index]
        data_source.set_dependent_data_item(None)
        self.__data_changed_event_listeners[index].close()
        del self.__data_changed_event_listeners[index]
        # being in transaction state means that data sources have their data loaded.
        # so unload data here to keep the books straight when the transaction state is exited.
        if self.in_transaction_state:
            data_source.decrement_data_ref_count()
        # the document model watches for new data sources via observing.
        # send this message to make data_sources observable.
        self.notify_remove_item("data_sources", data_source, index)

    def append_data_source(self, data_source):
        """Add a display, but do it through the container, so dependencies can be tracked."""
        self.insert_model_item(self, "data_sources", self.item_count("data_sources"), data_source)

    def remove_data_source(self, data_source):
        """Remove display, but do it through the container, so dependencies can be tracked."""
        self.remove_model_item(self, "data_sources", data_source)

    @property
    def computation(self) -> typing.Optional[Symbolic.Computation]:
        return self.maybe_data_source.computation if self.maybe_data_source else None

    @property
    def maybe_data_source(self) -> typing.Optional[BufferedDataSource]:
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

    def increment_display_ref_count(self):
        super().increment_display_ref_count()
        self.increment_data_ref_count()

    def decrement_display_ref_count(self):
        super().decrement_display_ref_count()
        self.decrement_data_ref_count()

    def increment_data_ref_count(self):
        for data_source in self.data_sources:
            assert isinstance(data_source, BufferedDataSource)
            data_source.increment_data_ref_count()

    def decrement_data_ref_count(self):
        for data_source in self.data_sources:
            assert isinstance(data_source, BufferedDataSource)
            data_source.decrement_data_ref_count()

    # primary display

    @property
    def primary_display_specifier(self):
        if len(self.data_sources) == 1:
            return DisplaySpecifier(self, self.data_sources[0], self.data_sources[0].displays[0])
        return DisplaySpecifier()

    def _update_timezone(self):
        for data_source in self.data_sources:
            data_source.timezone = self.timezone
            data_source.timezone_offset = self.timezone_offset
        super()._update_timezone()


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


class DisplaySpecifier:
    """Specify a Display contained within a DataItem.

    If display is not None, then data_item is not None.
    If buffered_data_source is not None, then data_item is not None.
    """

    def __init__(self, data_item: DataItem=None, buffered_data_source: BufferedDataSource=None, display: Display.Display=None):
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

def new_data_item(data_and_metadata: DataAndMetadata.DataAndMetadata=None) -> DataItem:
    data_item = DataItem()
    buffered_data_source = BufferedDataSource()
    data_item.append_data_source(buffered_data_source)
    buffered_data_source.set_data_and_metadata(data_and_metadata)
    return data_item
