# standard libraries
import abc
import copy
import datetime
import functools
import gettext
import os
import threading
import time
import typing
import uuid
import warnings
import weakref

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import Core
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import Cache
from nion.swift.model import Connection
from nion.swift.model import Display
from nion.swift.model import Graphics
from nion.swift.model import Metadata
from nion.swift.model import Symbolic
from nion.swift.model import Utility
from nion.utils import Converter
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


class DtypeToStringConverter:
    def convert(self, value):
        return str(value) if value is not None else None
    def convert_back(self, value):
        return numpy.dtype(value) if value is not None else None


class DatetimeToStringConverter:
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


class UuidsToStringsConverter:
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

    def __init__(self, data=None):
        super().__init__()
        self.define_type("buffered-data-source")
        self.persistent_storage = None
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
        self.define_property("data_modified", recordable=False, converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        self.define_property("metadata", dict(), hidden=True, changed=self.__metadata_property_changed)
        self.__timezone = None  # set by the data item, used when returning data_and_metadata
        self.__timezone_offset = None  # set by the data item, used when returning data_and_metadata
        self.__data_and_metadata = None
        self.__data_and_metadata_lock = threading.RLock()
        self.__intensity_calibration = None
        self.__dimensional_calibrations = list()
        self.__metadata = dict()
        self.__data_ref_count = 0
        self.__data_ref_count_mutex = threading.RLock()
        self.data_changed_event = Event.Event()
        self.metadata_changed_event = Event.Event()
        if data is not None:
            data_and_metadata = DataAndMetadata.DataAndMetadata.from_data(data)
            self.__set_data_metadata_direct(data_and_metadata)
        self._about_to_be_removed = False
        self._closed = False

    def close(self):
        self.__data_and_metadata = None
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

    def __deepcopy__(self, memo):
        deepcopy = self.__class__()
        deepcopy.deepcopy_from(self, memo)
        memo[id(self)] = deepcopy
        return deepcopy

    def deepcopy_from(self, buffered_data_source, memo):
        super().deepcopy_from(buffered_data_source, memo)
        # data and metadata
        self.set_data_and_metadata(copy.deepcopy(buffered_data_source.data_and_metadata))

    def clone(self) -> "BufferedDataSource":
        data_source = BufferedDataSource()
        data_source.uuid = self.uuid
        return data_source

    def snapshot(self):
        """
            Take a snapshot and return a new buffered data source. A snapshot is a copy of everything
            except the data and operation which are replaced by new data with the operation
            applied or "burned in".
        """
        buffered_data_source_copy = BufferedDataSource()
        buffered_data_source_copy.set_data_and_metadata(copy.deepcopy(self.data_and_metadata))
        return buffered_data_source_copy

    def read_from_dict(self, properties):
        super().read_from_dict(properties)
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

    def persistent_object_context_changed(self):
        super().persistent_object_context_changed()
        if self.__data_and_metadata:
            self.__data_and_metadata.unloadable = self.persistent_object_context is not None

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
        self.metadata_changed_event.fire()

    def __property_changed(self, name, value):
        self.notify_property_changed(name)

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
        return self.__data_and_metadata.data_metadata if self.__data_and_metadata else None

    @property
    def data_and_metadata(self):
        return self.__data_and_metadata

    def __load_data(self):
        if self.persistent_storage:
            return self.persistent_storage.load_data()
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
                if self.persistent_storage:
                    self.persistent_storage.update_data(self.__data_and_metadata.data)
                    self.__data_and_metadata.unloadable = True
        finally:
            self.decrement_data_ref_count()

    @property
    def dimensional_shape(self):
        return self.__data_and_metadata.dimensional_shape if self.__data_and_metadata else list()

    @property
    def is_collection(self):
        return self.collection_dimension_count > 0 if self.collection_dimension_count is not None else False

    @property
    def intensity_calibration(self):
        return copy.deepcopy(self.__data_and_metadata.intensity_calibration) if self.__data_and_metadata else self.__intensity_calibration

    @intensity_calibration.setter
    def intensity_calibration(self, intensity_calibration):
        """ Set the intensity calibration. """
        if self.__data_and_metadata:  # handle case of missing data and metadata but doing recording
            self.__data_and_metadata._set_intensity_calibration(intensity_calibration)
        self.__intensity_calibration = copy.deepcopy(intensity_calibration)  # backup in case of no data and metadata
        self._set_persistent_property_value("intensity_calibration", intensity_calibration)

    def set_intensity_calibration(self, intensity_calibration):
        self.intensity_calibration = intensity_calibration

    @property
    def dimensional_calibrations(self):
        return copy.deepcopy(self.__data_and_metadata.dimensional_calibrations) if self.__data_and_metadata else self.__dimensional_calibrations

    @dimensional_calibrations.setter
    def dimensional_calibrations(self, dimensional_calibrations):
        """ Set the dimensional calibrations. """
        if self.__data_and_metadata:  # handle case of missing data and metadata but doing recording
            self.__data_and_metadata._set_dimensional_calibrations(dimensional_calibrations)
        self.__dimensional_calibrations = copy.deepcopy(dimensional_calibrations)  # backup in case of no data and metadata
        self._set_persistent_property_value("dimensional_calibrations", CalibrationList(dimensional_calibrations))

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
        assert isinstance(metadata, dict)
        self.__data_and_metadata._set_metadata(metadata)
        self.__metadata = copy.deepcopy(metadata)
        self._set_persistent_property_value("metadata", self.__metadata)

    def _get_data(self):
        return self.__data_and_metadata.data if self.__data_and_metadata else None

    def _update_data(self, data, data_modified=None):
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
    def is_datum_1d(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_datum_1d

    @property
    def is_datum_2d(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_datum_2d

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
    def size_and_data_format_as_string(self) -> str:
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
    Data items represent a data, description, display, and graphics within a library.

    * *created* a datetime item
    * *session_id* a string representing the session

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

    Metadata Note: Until data source is merged into data item, metadata access cannot be done in this base class;
    instead it is implemented in the derived classes. It is a regular field in the composite library item; but in
    the data item, it is stored in the data source. When data source is merged, it will become a regular field
    and can be moved into this class.
    """

    writer_version = 12

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
        self.__persistent_storage = None
        self.define_property("created", datetime.datetime.utcnow(), converter=DatetimeToStringConverter(), changed=self.__description_property_changed)
        # windows utcnow has a resolution of 1ms, this sleep can guarantee unique times for all created times during a particular test.
        # this is not my favorite solution since it limits library item creation to 1000/s but until I find a better solution, this is my compromise.
        time.sleep(0.001)
        self.define_property("description", dict(), hidden=True, changed=self.__property_changed)
        self.define_property("source_file_path", validate=self.__validate_source_file_path, changed=self.__property_changed)
        self.define_property("session_id", validate=self.__validate_session_id, changed=self.__session_id_changed)
        self.define_property("category", "persistent", changed=self.__property_changed)
        self.define_property("session_metadata", dict(), copy_on_read=True, changed=self.__property_changed)
        self.define_property("timezone", Utility.get_local_timezone(), changed=self.__timezone_property_changed)
        self.define_property("timezone_offset", Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes()), changed=self.__timezone_property_changed)
        self.define_property("source_uuid", converter=Converter.UuidToStringConverter())
        self.define_relationship("displays", Display.display_factory, insert=self.__insert_display, remove=self.__remove_display)
        self.__session_manager = None
        self.__source = None
        self.library_item_changed_event = Event.Event()
        self.item_changed_event = Event.Event()  # equivalent to library_item_changed_event
        self.metadata_changed_event = Event.Event()  # see Metadata Note above
        self.__display_ref_count = 0
        self.__change_count = 0
        self.__change_count_lock = threading.RLock()
        self.__content_changed = False
        self.__suspendable_storage_cache = None
        self.r_var = None
        self.about_to_be_removed_event = Event.Event()
        self._about_to_be_removed = False
        self._closed = False

    def __str__(self):
        return "{0} {1} ({2}, {3})".format(self.__repr__(), (self.title if self.title else _("Untitled")), str(self.uuid), self.date_for_sorting_local_as_string)

    def __copy__(self):
        assert False

    def __deepcopy__(self, memo):
        library_item_copy = self.__class__()
        # metadata
        library_item_copy.description = self.description
        library_item_copy.session_metadata = self.session_metadata
        library_item_copy.created = self.created
        library_item_copy.timezone = self.timezone
        library_item_copy.timezone_offset = self.timezone_offset
        library_item_copy.session_id = self.session_id
        library_item_copy.source_file_path = self.source_file_path
        # displays
        for display in copy.copy(library_item_copy.displays):
            library_item_copy.remove_display(display)
        for display in self.displays:
            library_item_copy.add_display(copy.deepcopy(display))
        memo[id(self)] = library_item_copy
        return library_item_copy

    def close(self):
        for display in self.displays:
            display.close()
        # close the storage handler
        if self.persistent_object_context:
            if self.persistent_storage:
                self.persistent_storage.close()
            self.persistent_storage = None
            self.persistent_object_context = None
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None

    @property
    def container(self):
        return self.__container_weak_ref()

    def about_to_close(self):
        pass

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        self.about_to_be_removed_event.fire()
        for display in self.displays:
            display.about_to_be_removed()
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

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        """Remove a model item. Let this item's container do it if possible; otherwise do it directly.

        Passing responsibility to this item's container allows the library to easily track dependencies.
        However, if this item isn't yet in the library hierarchy, then do the operation directly.
        """
        if self.__container_weak_ref:
            return self.container.remove_model_item(container, name, item, safe=safe)
        else:
            container.remove_item(name, item)
            return None

    @property
    def persistent_storage(self):
        return self.__persistent_storage

    @persistent_storage.setter
    def persistent_storage(self, persistent_storage):
        self._set_persistent_storage(persistent_storage)

    def _set_persistent_storage(self, persistent_storage):
        self.__persistent_storage = persistent_storage

    def clone(self) -> "LibraryItem":
        library_item = self.__class__()
        library_item.uuid = self.uuid
        for display in copy.copy(library_item.displays):
            library_item.remove_display(display)
        for display in self.displays:
            library_item.add_display(display.clone())
        return library_item

    def snapshot(self):
        """Return a new library item which is a copy of this one with any dynamic behavior made static."""
        libary_item = self.__class__()
        # metadata
        libary_item.description = self.description
        libary_item.session_metadata = self.session_metadata
        libary_item.created = self.created
        libary_item.timezone = self.timezone
        libary_item.timezone_offset = self.timezone_offset
        libary_item.session_id = self.session_id
        libary_item.source_file_path = self.source_file_path
        for display in copy.copy(libary_item.displays):
            libary_item.remove_display(display)
        for display in self.displays:
            libary_item.add_display(copy.deepcopy(display))
        return libary_item

    @property
    def data_items(self):
        return tuple()

    def connect_data_items(self, lookup_data_item):
        pass

    def set_storage_cache(self, storage_cache):
        self.__suspendable_storage_cache = Cache.SuspendableCache(storage_cache)
        for display in self.displays:
            display.set_storage_cache(self._suspendable_storage_cache)

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
            if self.persistent_storage:
                self.persistent_storage.write_delayed = True

    def __exit_write_delay_state(self):
        if self.persistent_object_context:
            if self.persistent_storage:
                self.persistent_storage.write_delayed = False
            self._finish_pending_write()

    def _finish_write(self):
        pass

    def _finish_pending_write(self):
        if self.__pending_write:
            # write the uuid and version explicitly
            self.persistent_object_context.property_changed(self, "uuid", str(self.uuid))
            self.persistent_object_context.property_changed(self, "version", DataItem.writer_version)
            self._finish_write()
            self.__pending_write = False
        else:
            if self.modified_count > self.__write_delay_modified_count:
                self.persistent_storage.update_properties()
            self._finish_pending_write_inner()

    def _transaction_state_entered(self):
        self.__in_transaction_state = True
        # first enter the write delay state.
        self.__enter_write_delay_state()
        # suspend disk caching
        if self.__suspendable_storage_cache:
            self.__suspendable_storage_cache.suspend_cache()

    def _transaction_state_exited(self):
        self.__in_transaction_state = False
        # being in the transaction state has the side effect of delaying the cache too.
        # spill whatever was into the local cache into the persistent cache.
        if self.__suspendable_storage_cache:
            self.__suspendable_storage_cache.spill_cache()
        # exit the write delay state.
        self.__exit_write_delay_state()

    @property
    def source(self):
        return self.__source

    @source.setter
    def source(self, source):
        self.__source = source
        self.source_uuid = source.uuid if source else None

    def persistent_object_context_changed(self):
        # handle case where persistent object context is set on an item that is already under transaction.
        # this can occur during acquisition. any other cases?
        super().persistent_object_context_changed()

        if self.__in_transaction_state:
            self.__enter_write_delay_state()

        def register():
            if self.__source is not None:
                pass

        def source_registered(source):
            self.__source = source
            register()

        def unregistered(source=None):
            pass

        if self.persistent_object_context:
            self.persistent_object_context.subscribe(self.source_uuid, source_registered, unregistered)
        else:
            unregistered()

    def _test_get_file_path(self):
        return self.persistent_storage._storage_handler.reference if self.persistent_storage else None

    # access properties

    def read_from_dict(self, properties):
        for display in copy.copy(self.displays):
            self.remove_display(display)
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

    def __insert_display(self, name, before_index, display):
        display.about_to_be_inserted(self)
        display.title = self.displayed_title

    def __remove_display(self, name, index, display):
        display.about_to_be_removed()
        display.close()

    def add_display(self, display):
        """Add a display, but do it through the container, so dependencies can be tracked."""
        self.insert_model_item(self, "displays", self.item_count("displays"), display)
        if self.__display_ref_count > 0:
            display._become_master()

    def remove_display(self, display: Display.Display) -> typing.Optional[typing.Sequence]:
        """Remove display, but do it through the container, so dependencies can be tracked."""
        if self.__display_ref_count > 0:
            display._relinquish_master()
        return self.remove_model_item(self, "displays", display)

    @property
    def primary_display_specifier(self):
        if len(self.displays) > 0:
            return DisplaySpecifier(self, self.displays[0])
        return DisplaySpecifier()

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
        class LibraryItemChangeContextManager:
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
            self.library_item_changed_event.fire()
            self.item_changed_event.fire()
            self._item_changed()

    def _item_changed(self):
        for display in self.displays:
            display._item_changed()

    def __validate_source_file_path(self, value):
        value = str(value) if value is not None else str()
        if value:
            value = os.path.normpath(value)
        return value

    def __description_property_changed(self, name, value):
        self.__property_changed(name, value)
        self.__notify_description_changed()

    def __notify_description_changed(self):
        self._notify_library_item_content_changed()
        self._description_changed()

    def _description_changed(self):
        for display in self.displays:
            display.title = self.displayed_title

    def __property_changed(self, name, value):
        self.notify_property_changed(name)

    def __timezone_property_changed(self, name, value):
        self._update_timezone()
        self.__property_changed(name, value)

    def _update_timezone(self):
        pass

    def set_r_value(self, r_var: str, *, notify_changed=True) -> None:
        """Used to signal changes to the ref var, which are kept in document controller. ugh."""
        self.r_var = r_var
        self._description_changed()
        if notify_changed:  # set to False to set the r-value at startup; avoid marking it as a change
            self.__notify_description_changed()

    def increment_display_ref_count(self, amount: int=1):
        """Increment display reference count to indicate this library item is currently displayed."""
        display_ref_count = self.__display_ref_count
        self.__display_ref_count += amount
        if display_ref_count == 0:
            for display in self.displays:
                display._become_master()

    def decrement_display_ref_count(self, amount: int=1):
        """Decrement display reference count to indicate this library item is no longer displayed."""
        assert not self._closed
        self.__display_ref_count -= amount
        if self.__display_ref_count == 0:
            for display in self.displays:
                display._relinquish_master()

    @property
    def _display_ref_count(self):
        return self.__display_ref_count

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

    # access description

    @property
    def description(self):
        return copy.deepcopy(self._get_persistent_property_value("description"))

    @description.setter
    def description(self, description):
        assert description is not None
        self._set_persistent_property_value("description", copy.deepcopy(description))

    def set_description(self, description):
        self.description = description

    @property
    def _session_manager(self) -> SessionManager:
        return self.__session_manager

    def set_session_manager(self, session_manager: SessionManager) -> None:
        self.__session_manager = session_manager

    # override from storage to watch for changes to this library item. notify observers.
    def notify_property_changed(self, key):
        super().notify_property_changed(key)
        self._notify_library_item_content_changed()

    # description

    @property
    def title(self):
        return self.description.get("title", UNTITLED_STR)

    @title.setter
    def title(self, value):
        description = self.description
        description["title"] = str(value) if value is not None else str()
        self.description = description
        self.__description_property_changed("title", value)

    @property
    def caption(self):
        return self.description.get("caption", str())

    @caption.setter
    def caption(self, value):
        description = self.description
        description["caption"] = str(value) if value is not None else str()
        self.description = description
        self.__description_property_changed("caption", value)

    @property
    def flag(self):
        return self.description.get("flag", 0)

    @flag.setter
    def flag(self, value):
        description = self.description
        description["flag"] = max(min(int(value), 1), -1)
        self.description = description
        self.__description_property_changed("flag", value)

    @property
    def rating(self):
        return self.description.get("rating", 0)

    @rating.setter
    def rating(self, value):
        description = self.description
        description["rating"] = min(max(int(value), 0), 5)
        self.description = description
        self.__description_property_changed("rating", value)

    @property
    def text_for_filter(self):
        return " ".join([self.displayed_title, self.caption])


class CompositeLibraryItem(LibraryItem):
    """Composite library item consists of references to other library items."""

    def __init__(self, item_uuid=None):
        super().__init__(item_uuid=item_uuid)
        self.__data_items = list()
        self.__data_item_about_to_be_removed_listeners = list()
        self.add_display(Display.Display())  # always have one display, for now
        self.define_property("data_item_uuids", list(), converter=UuidsToStringsConverter(), changed=self.__property_changed)
        self.define_property("metadata", dict(), hidden=True, changed=self.__metadata_property_changed)
        self.__metadata = dict()

    def close(self):
        self.__unlisten_about_to_be_removed()
        super().close()

    def about_to_close(self):
        self.__unlisten_about_to_be_removed()
        super().about_to_close()

    def about_to_be_removed(self):
        self.__unlisten_about_to_be_removed()
        super().about_to_be_removed()

    def __unlisten_about_to_be_removed(self):
        for listener in self.__data_item_about_to_be_removed_listeners:
            listener.close()
        self.__data_item_about_to_be_removed_listeners.clear()

    def read_from_dict(self, properties):
        super().read_from_dict(properties)
        self.__metadata = self._get_persistent_property_value("metadata", dict())

    @property
    def data_items(self):
        return tuple(self.__data_items)

    @property
    def metadata(self):
        return copy.deepcopy(self.__metadata)

    @metadata.setter
    def metadata(self, metadata):
        assert isinstance(metadata, dict)
        self.__metadata = copy.deepcopy(metadata)
        self._set_persistent_property_value("metadata", self.__metadata)

    def connect_data_items(self, lookup_data_item):
        super().connect_data_items(lookup_data_item)
        for data_item_uuid in self.data_item_uuids:
            data_item = lookup_data_item(data_item_uuid)
            # check whether the data item is already in data items; this covers the case where data items are added
            # to the composite library item before it is added to the document when it will be connected.
            if data_item and not data_item in self.__data_items:
                before_index = len(self.__data_items)
                self.__data_items.append(data_item)
                self.__data_item_about_to_be_removed_listeners.append(data_item.about_to_be_removed_event.listen(functools.partial(self.__data_item_about_to_be_removed, data_item)))
                self.notify_insert_item("data_items", data_item, before_index)

    def append_data_item(self, data_item):
        self.insert_data_item(len(self.__data_items), data_item)

    def insert_data_item(self, before_index, data_item):
        assert data_item not in self.__data_items
        self.__data_items.insert(before_index, data_item)
        self.__data_item_about_to_be_removed_listeners.append(data_item.about_to_be_removed_event.listen(functools.partial(self.__data_item_about_to_be_removed, data_item)))
        data_item_uuids = self.data_item_uuids
        data_item_uuids.insert(before_index, data_item.uuid)
        self.data_item_uuids = data_item_uuids
        self.notify_property_changed("data_item_uuids")
        self.notify_insert_item("data_items", data_item, before_index)
        data_item.increment_display_ref_count(self._display_ref_count)

    def remove_data_item(self, data_item):
        index = self.__data_items.index(data_item)
        self.notify_remove_item("data_items", data_item, index)
        self.__data_item_about_to_be_removed_listeners[index].close()
        del self.__data_item_about_to_be_removed_listeners[index]
        self.__data_items.remove(data_item)
        data_item_uuids = self.data_item_uuids
        data_item_uuids.remove(data_item.uuid)
        self.data_item_uuids = data_item_uuids
        self.notify_property_changed("data_item_uuids")
        data_item.decrement_display_ref_count(self._display_ref_count)

    def __data_item_about_to_be_removed(self, data_item):
        self.remove_data_item(data_item)

    def increment_display_ref_count(self, amount: int=1):
        super().increment_display_ref_count(amount)
        for data_item in self.data_items:
            data_item.increment_display_ref_count(amount)

    def decrement_display_ref_count(self, amount: int=1):
        super().decrement_display_ref_count(amount)
        for data_item in self.data_items:
            data_item.decrement_display_ref_count(amount)

    def __property_changed(self, name, value):
        self.notify_property_changed(name)

    def __metadata_property_changed(self, name, value):
        self.__property_changed(name, value)
        self.metadata_changed_event.fire()

    @property
    def size_and_data_format_as_string(self) -> str:
        return "{0} ({1})".format(_("Composite"), len(self.__data_items))


class DataItem(LibraryItem):

    def __init__(self, data=None, item_uuid=None, large_format=False):
        super().__init__(item_uuid)
        self.add_display(Display.Display())  # always have one display, for now
        self.large_format = large_format
        self.define_item("data_source", data_source_factory, item_changed=self.__data_source_changed)
        self.data_item_changed_event = Event.Event()  # anything has changed
        self.data_changed_event = Event.Event()  # data has changed
        self.__write_delay_data_changed = False
        self.__data_source_metadata_changed_event_listener = None
        self.__data_source_data_changed_event_listener = None
        self.__change_thread = None
        self.__change_count = 0
        self.__change_count_lock = threading.RLock()
        self.__change_changed = False
        self.__change_data_changed = False
        self.__pending_xdata_lock = threading.RLock()
        self.__pending_xdata = None
        if data is not None:
            self.set_data_source(BufferedDataSource(data))
        self.__update_displays()

    def __deepcopy__(self, memo):
        data_item_copy = super().__deepcopy__(memo)
        # format
        data_item_copy.large_format = self.large_format
        # data source
        data_item_copy.set_data_source(copy.deepcopy(self.data_source))
        data_item_copy.__update_displays()
        return data_item_copy

    def close(self):
        data_source = self.data_source
        if data_source:
            self.__disconnect_data_source(data_source)
            data_source.close()
        super().close()

    def about_to_be_removed(self):
        data_source = self.data_source
        if data_source:
            data_source.about_to_be_removed()
        super().about_to_be_removed()

    def _set_persistent_storage(self, persistent_storage):
        super()._set_persistent_storage(persistent_storage)
        if self.data_source:
            self.data_source.persistent_storage = persistent_storage

    def clone(self) -> "DataItem":
        data_item = super().clone()
        data_source = self.data_source
        if data_source:
            data_item.set_data_source(data_source.clone())
        data_item.__update_displays()
        return data_item

    def snapshot(self):
        data_item = super().snapshot()
        # format
        data_item.large_format = self.large_format
        # data sources
        data_source = self.data_source
        if data_source:
            data_item.set_data_source(data_source.snapshot())
        data_item.__update_displays()
        return data_item

    def _transaction_state_entered(self):
        super()._transaction_state_entered()
        # tell each data source to load its data.
        # this prevents paging in and out.
        data_source = self.data_source
        if data_source:
            data_source.increment_data_ref_count()

    def _transaction_state_exited(self):
        super()._transaction_state_exited()
        # tell each data source to unload its data.
        data_source = self.data_source
        if data_source:
            data_source.decrement_data_ref_count()

    def _read_from_dict_inner(self, properties):
        super()._read_from_dict_inner(properties)
        self.__update_displays()  # this ensures that the display will validate

    def finish_reading(self):
        super().finish_reading()

    def _finish_write(self):
        super()._finish_write()
        if self.data_source:
            self.persistent_storage.update_data(self.data)

    def _enter_write_delay_state_inner(self):
        super()._enter_write_delay_state_inner()
        self.__write_delay_data_changed = False

    def _finish_pending_write_inner(self):
        super()._finish_pending_write_inner()
        if self.__write_delay_data_changed:
            self.persistent_storage.update_data(self.data)

    @property
    def date_for_sorting(self):
        data_modified_list = list()
        data_source = self.data_source
        if data_source:
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
        with self.data_item_changes():
            self.set_xdata(data_and_metadata)
            self.timezone = Utility.get_local_timezone()
            self.timezone_offset = Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes())

    def set_pending_xdata(self, xd: DataAndMetadata.DataAndMetadata) -> None:
        with self.__pending_xdata_lock:
            self.__pending_xdata = xd

    def update_to_pending_xdata(self):
        with self.__pending_xdata_lock:
            pending_xdata = self.__pending_xdata
            self.__pending_xdata = None
        if pending_xdata:
            self.update_data_and_metadata(pending_xdata)

    def __handle_data_changed(self, data_source):
        self.__change_changed = True
        self.__change_data_changed = True
        self.timezone = Utility.get_local_timezone()
        self.timezone_offset = Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes())
        if self._session_manager:
            self.session_id = self._session_manager.current_session_id

    def __handle_metadata_changed(self):
        self.__change_changed = True
        self.metadata_changed_event.fire()

    def __data_source_changed(self, name, old_data_source, data_source):
        if old_data_source:
            old_data_source.about_to_be_removed()
            self.__disconnect_data_source(old_data_source)
            old_data_source.close()

        if data_source:
            data_source.persistent_storage = self.persistent_storage
            data_source.timezone = self.timezone
            data_source.timezone_offset = self.timezone_offset
            self.__data_source_data_changed_event_listener = data_source.data_changed_event.listen(self.__handle_data_changed)
            # being in transaction state means that data sources have their data loaded.
            # so load data here to keep the books straight when the transaction state is exited.
            if self.in_transaction_state:
                data_source.increment_data_ref_count()
            self.__data_source_metadata_changed_event_listener = data_source.metadata_changed_event.listen(self.__handle_metadata_changed)
            self._notify_library_item_content_changed()
            # the document model watches for new data sources via observing.
            # send this message to make data_source observable.
            self.notify_set_item("data_source", data_source)

    def __disconnect_data_source(self, data_source):
        if self.__data_source_metadata_changed_event_listener:
            self.__data_source_metadata_changed_event_listener.close()
            self.__data_source_metadata_changed_event_listener = None
        if self.__data_source_data_changed_event_listener:
            self.__data_source_data_changed_event_listener.close()
            self.__data_source_data_changed_event_listener = None
        # being in transaction state means that data sources have their data loaded.
        # so unload data here to keep the books straight when the transaction state is exited.
        if self.in_transaction_state:
            data_source.decrement_data_ref_count()
        data_source.persistent_storage = None
        # the document model watches for new data sources via observing.
        # send this message to make data_source observable.
        self.notify_clear_item("data_source")

    def set_data_source(self, data_source):
        """Set data source."""
        self.set_item("data_source", data_source)

    @property
    def data_source(self) -> typing.Optional[BufferedDataSource]:
        return self.get_item("data_source")

    def increment_display_ref_count(self, amount: int=1):
        super().increment_display_ref_count(amount)
        for _ in range(amount):
            self.increment_data_ref_count()

    def decrement_display_ref_count(self, amount: int=1):
        super().decrement_display_ref_count(amount)
        for _ in range(amount):
            self.decrement_data_ref_count()

    def increment_data_ref_count(self):
        data_source = self.data_source
        if data_source:
            data_source.increment_data_ref_count()

    def decrement_data_ref_count(self):
        data_source = self.data_source
        if data_source:
            data_source.decrement_data_ref_count()

    # primary display

    @property
    def primary_display_specifier(self):
        data_source = self.data_source
        if data_source:
            return DisplaySpecifier(self, self.displays[0])
        return DisplaySpecifier()

    def _update_timezone(self):
        with self.data_source_changes():
            data_source = self.data_source
            if data_source:
                data_source.timezone = self.timezone
                data_source.timezone_offset = self.timezone_offset
            super()._update_timezone()

    def ensure_data_source(self) -> None:
        if not self.data_source:
            self.set_data_source(BufferedDataSource())

    @property
    def data(self) -> numpy.ndarray:
        return self.__get_data()

    @property
    def xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.data_source.data_and_metadata if self.data_source else None

    def set_data(self, data: numpy.ndarray, data_modified: datetime.datetime=None) -> None:
        self.set_xdata(DataAndMetadata.new_data_and_metadata(data, data_modified))

    def set_xdata(self, xdata: DataAndMetadata.DataAndMetadata, data_modified: datetime.datetime=None) -> None:
        with self.data_source_changes():
            self.ensure_data_source()
            self.data_source.set_data_and_metadata(xdata, data_modified)

    # grab a data reference as a context manager. the object
    # returned defines data and data properties. reading data
    # should use the data property. writing data (if allowed) should
    # assign to the data property.
    def data_ref(self):
        get_data = self.__get_data
        set_data = self.__set_data
        class DataAccessor:
            def __init__(self, data_item):
                self.__data_item = data_item
            def __enter__(self):
                self.__data_item.increment_data_ref_count()
                return self
            def __exit__(self, type, value, traceback):
                self.__data_item.decrement_data_ref_count()
            @property
            def data(self):
                return get_data()
            @data.setter
            def data(self, value):
                set_data(value)
            def data_updated(self):
                set_data(get_data())
            @property
            def master_data(self):
                return get_data()
            @master_data.setter
            def master_data(self, value):
                set_data(value)
            def master_data_updated(self):
                set_data(get_data())
        return DataAccessor(self)

    def __get_data(self):
        return self.data_source._get_data() if self.data_source else None

    def __set_data(self, data, data_modified=None):
        with self.data_source_changes():
            self.data_source._update_data(data, data_modified)

    def data_source_changes(self):
        # return a context manager to batch up a set of changes so that listeners
        # are only notified after the last change is complete.
        begin_changes = self.__begin_changes
        end_changes = self.__end_changes
        class ChangeContextManager:
            def __enter__(self):
                begin_changes()
                return self
            def __exit__(self, type, value, traceback):
                end_changes()
        return ChangeContextManager()

    def __begin_changes(self):
        with self.__change_count_lock:
            if self.__change_count == 0:
                self.__change_thread = threading.current_thread()
            else:
                if self.__change_thread != threading.current_thread():
                    warnings.warn('begin changes from different threads', RuntimeWarning, stacklevel=2)
            self.__change_count += 1

    def __end_changes(self):
        changed = False
        data_changed = False
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
                data_changed = self.__change_data_changed
                self.__change_data_changed = False
        # if the change count is now zero, it means that we're ready
        # to pass on the next value.
        if change_count == 0:
            if data_changed:
                self.data_changed_event.fire()
            if changed:
                self.__update_displays()
                if not self._is_reading:
                    self.__write_delay_data_changed = True
                    self._notify_library_item_content_changed()
                    self.data_item_changed_event.fire()

    def __update_displays(self):
        data_and_metadata = self.xdata
        for display in self.displays:
            display.update_data(data_and_metadata)

    @property
    def data_modified(self) -> datetime.datetime:
        return self.data_source.data_modified if self.data_source else None

    @data_modified.setter
    def data_modified(self, value: datetime.datetime) -> None:
        with self.data_source_changes():
            if self.data_source:
                self.data_source.data_modified = value

    @property
    def intensity_calibration(self) -> Calibration.Calibration:
        return self.data_source.intensity_calibration if self.data_source else None

    @intensity_calibration.setter
    def intensity_calibration(self, intensity_calibration: Calibration.Calibration) -> None:
        with self.data_source_changes():
            if self.data_source:
                self.data_source.set_intensity_calibration(intensity_calibration)

    def set_intensity_calibration(self, intensity_calibration):
        self.intensity_calibration = intensity_calibration

    @property
    def dimensional_calibrations(self) -> typing.List[Calibration.Calibration]:
        return self.data_source.dimensional_calibrations if self.data_source else list()

    @dimensional_calibrations.setter
    def dimensional_calibrations(self, dimensional_calibrations: typing.Sequence[Calibration.Calibration]) -> None:
        with self.data_source_changes():
            if self.data_source:
                self.data_source.set_dimensional_calibrations(dimensional_calibrations)

    def set_dimensional_calibrations(self, dimensional_calibrations: typing.Sequence[Calibration.Calibration]) -> None:
        self.dimensional_calibrations = dimensional_calibrations

    def set_dimensional_calibration(self, dimension: int, calibration: Calibration.Calibration) -> None:
        dimensional_calibrations = self.dimensional_calibrations
        while len(dimensional_calibrations) <= dimension:
            dimensional_calibrations.append(Calibration.Calibration())
        dimensional_calibrations[dimension] = calibration
        self.set_dimensional_calibrations(dimensional_calibrations)

    @property
    def metadata(self) -> dict:
        return self.data_source.metadata if self.data_source else dict()

    @metadata.setter
    def metadata(self, value: dict) -> None:
        with self.data_source_changes():
            if self.data_source:
                self.data_source.metadata = value

    @property
    def has_data(self) -> bool:
        return self.data_source.has_data if self.data_source else False

    # used for testing
    @property
    def is_data_loaded(self) -> bool:
        return self.data_source.is_data_loaded if self.data_source else False

    @property
    def data_metadata(self):
        return self.data_source.data_metadata if self.data_source else None

    @property
    def data_shape(self):
        return self.data_source.data_shape if self.data_source else None

    @property
    def data_dtype(self):
        return self.data_source.data_dtype if self.data_source else None

    @property
    def dimensional_shape(self):
        return self.data_source.dimensional_shape if self.data_source else list()

    @property
    def datum_dimension_count(self) -> int:
        return self.data_source.datum_dimension_count if self.data_source else 0

    @property
    def collection_dimension_count(self) -> int:
        return self.data_source.collection_dimension_count if self.data_source else 0

    @property
    def is_collection(self):
        return self.data_source.is_collection if self.data_source else None

    @property
    def is_sequence(self) -> bool:
        return self.data_source.is_sequence if self.data_source else None

    @property
    def is_data_1d(self) -> bool:
        return self.data_source is not None and self.data_source.is_data_1d

    @property
    def is_data_2d(self) -> bool:
        return self.data_source is not None and self.data_source.is_data_2d

    @property
    def is_data_3d(self) -> bool:
        return self.data_source is not None and self.data_source.is_data_3d

    @property
    def is_data_4d(self) -> bool:
        return self.data_source is not None and self.data_source.is_data_4d

    @property
    def is_data_rgb(self) -> bool:
        return self.data_source is not None and self.data_source.is_data_rgb

    @property
    def is_data_rgba(self) -> bool:
        return self.data_source is not None and self.data_source.is_data_rgba

    @property
    def is_datum_1d(self) -> bool:
        return self.data_source is not None and self.data_source.is_datum_1d

    @property
    def is_datum_2d(self) -> bool:
        return self.data_source is not None and self.data_source.is_datum_2d

    @property
    def is_data_rgb_type(self) -> bool:
        return self.data_source is not None and self.data_source.is_data_rgb_type

    @property
    def is_data_scalar_type(self) -> bool:
        return self.data_source is not None and self.data_source.is_data_scalar_type

    @property
    def is_data_complex_type(self) -> bool:
        return self.data_source is not None and self.data_source.is_data_complex_type

    @property
    def is_data_bool(self) -> bool:
        return self.data_source is not None and self.data_source.is_data_bool

    def get_data_value(self, pos):
        return self.data_source.get_data_value(pos) if self.data_source else None

    @property
    def size_and_data_format_as_string(self) -> str:
        return self.data_source.size_and_data_format_as_string if self.data_source else _("No Data")

    def has_metadata_value(self, key: str) -> bool:
        return Metadata.has_metadata_value(self, key)

    def get_metadata_value(self, key: str) -> typing.Any:
        return Metadata.get_metadata_value(self, key)

    def set_metadata_value(self, key: str, value: typing.Any) -> None:
        Metadata.set_metadata_value(self, key, value)

    def delete_metadata_value(self, key: str) -> None:
        Metadata.delete_metadata_value(self, key)


class DisplaySpecifier:
    """Specify a Display contained within a DataItem."""

    def __init__(self, library_item: LibraryItem=None, display: Display.Display=None):
        self.library_item = library_item
        self.display = display

    def __eq__(self, other):
        return self.library_item == other.library_item and self.display == other.display

    def __ne__(self, other):
        return self.library_item != other.library_item or self.display != other.display

    @property
    def data_item(self):
        return self.library_item if isinstance(self.library_item, DataItem) else None

    @property
    def composite_library_item(self):
        return self.library_item if isinstance(self.library_item, CompositeLibraryItem) else None

    @classmethod
    def from_display(cls, display):
        library_item = display.container if display else None
        return cls(library_item, display)

    @classmethod
    def from_library_item(cls, library_item):
        display = library_item.displays[0] if library_item and len(library_item.displays) > 0 else None
        return cls(library_item, display)

    @classmethod
    def from_data_item(cls, data_item):
        display = data_item.displays[0] if data_item and len(data_item.displays) > 0 else None
        return cls(data_item, display)


def sort_by_date_key(data_item):
    """ A sort key to for the created field of a data item. The sort by uuid makes it determinate. """
    return data_item.title + str(data_item.uuid) if data_item.is_live else str(), data_item.date_for_sorting, str(data_item.uuid)


def new_data_item(data_and_metadata: DataAndMetadata.DataAndMetadata=None) -> DataItem:
    data_item = DataItem(large_format=data_and_metadata and len(data_and_metadata.dimensional_shape) > 2)
    data_item.ensure_data_source()
    data_item.set_xdata(data_and_metadata)
    return data_item


class DataSource:
    DATA_SOURCE_MIME_TYPE = "text/vnd.nion.display_source_type"

    def __init__(self, data_item: DataItem, graphic, changed_event):
        self.__data_item = data_item
        self.__graphic = graphic
        self.__changed_event = changed_event  # not public since it is passed in
        display = data_item.displays[0] if len(data_item.displays) > 0 else None
        self.__data_item_changed_event_listener = data_item.data_item_changed_event.listen(self.__changed_event.fire)
        self.__display_values_event_listener = display.display_data_will_change_event.listen(self.__changed_event.fire) if display else None
        self.__property_changed_listener = None
        def property_changed(key):
            self.__changed_event.fire()
        if graphic:
            self.__property_changed_listener = graphic.property_changed_event.listen(property_changed)
        def filter_property_changed(key):
            self.__changed_event.fire()
        self.__graphic_property_changed_listeners = list()
        def graphic_inserted(key, value, before_index):
            if key == "graphics":
                property_changed_listener = None
                if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                    property_changed_listener = value.property_changed_event.listen(filter_property_changed)
                    self.__changed_event.fire()
                self.__graphic_property_changed_listeners.insert(before_index, property_changed_listener)
        def graphic_removed(key, value, index):
            if key == "graphics":
                property_changed_listener = self.__graphic_property_changed_listeners.pop(index)
                if property_changed_listener:
                    property_changed_listener.close()
                    self.__changed_event.fire()
        self.__graphic_inserted_event_listener = display.item_inserted_event.listen(graphic_inserted) if display else None
        self.__graphic_removed_event_listener = display.item_removed_event.listen(graphic_removed) if display else None
        for graphic in display.graphics if display else list():
            property_changed_listener = None
            if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                property_changed_listener = graphic.property_changed_event.listen(filter_property_changed)
            self.__graphic_property_changed_listeners.append(property_changed_listener)

    def close(self):
        for graphic_property_changed_listener in self.__graphic_property_changed_listeners:
            if graphic_property_changed_listener:
                graphic_property_changed_listener.close()
        self.__graphic_property_changed_listeners = list()
        if self.__graphic_inserted_event_listener:
            self.__graphic_inserted_event_listener.close()
            self.__graphic_inserted_event_listener = None
        if self.__graphic_removed_event_listener:
            self.__graphic_removed_event_listener.close()
            self.__graphic_removed_event_listener = None
        if self.__property_changed_listener:
            self.__property_changed_listener.close()
            self.__property_changed_listener = None
        self.__data_item_changed_event_listener.close()
        self.__data_item_changed_event_listener = None
        if self.__display_values_event_listener:
            self.__display_values_event_listener.close()
            self.__display_values_event_listener = None

    @property
    def data_item(self):
        return self.__data_item

    @property
    def graphic(self):
        return self.__graphic

    @property
    def data(self) -> numpy.ndarray:
        return self.__data_item.data

    @property
    def xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__data_item.xdata

    @property
    def display_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_item.displays[0].get_calculated_display_values(True).display_data_and_metadata

    @property
    def cropped_display_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        data_item = self.__data_item
        if data_item:
            displayed_xdata = self.display_xdata
            graphic = self.__graphic
            if graphic:
                if hasattr(graphic, "bounds") and displayed_xdata.is_data_2d:
                    return Core.function_crop(displayed_xdata, graphic.bounds)
                if hasattr(graphic, "interval") and displayed_xdata.is_data_1d:
                    return Core.function_crop_interval(displayed_xdata, graphic.interval)
            return displayed_xdata
        return None

    @property
    def cropped_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        data_item = self.__data_item
        if data_item:
            xdata = self.xdata
            graphic = self.__graphic
            if graphic:
                if hasattr(graphic, "bounds"):
                    return Core.function_crop(xdata, graphic.bounds)
                if hasattr(graphic, "interval"):
                    return Core.function_crop_interval(xdata, graphic.interval)
            return xdata
        return None

    @property
    def filtered_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        xdata = self.xdata
        if xdata.is_data_2d and xdata.is_data_complex_type:
            shape = xdata.data_shape
            mask = numpy.zeros(shape)
            for graphic in self.__data_item.displays[0].graphics:
                if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                    mask = numpy.logical_or(mask, graphic.get_mask(shape))
            return Core.function_fourier_mask(xdata, DataAndMetadata.DataAndMetadata.from_data(mask))
        return xdata

    @property
    def filter_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        shape = self.display_xdata.data_shape
        mask = numpy.zeros(shape)
        for graphic in self.__data_item.displays[0].graphics:
            if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                mask = numpy.logical_or(mask, graphic.get_mask(shape))
        return DataAndMetadata.DataAndMetadata.from_data(mask)
