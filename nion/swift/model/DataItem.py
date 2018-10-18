# standard libraries
import abc
import copy
import datetime
import functools
import gettext
import pathlib
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
from nion.swift.model import Display
from nion.swift.model import Graphics
from nion.swift.model import Metadata
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
        self.__container_weak_ref = None
        self.about_to_be_removed_event = Event.Event()
        self._about_to_be_removed = False
        self._closed = False
        self.define_type("buffered-data-source")
        data_shape = data.shape if data is not None else None
        data_dtype = data.dtype if data is not None else None
        self.__source_file_path = None
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
        self.define_property("timezone", Utility.get_local_timezone(), changed=self.__timezone_property_changed)
        self.define_property("timezone_offset", Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes()), changed=self.__timezone_property_changed)
        self.define_property("metadata", dict(), hidden=True, changed=self.__metadata_property_changed)
        self.define_property("session_id", validate=self.__validate_session_id, changed=self.__property_changed)
        self.define_property("session", dict(), hidden=True, changed=self.__property_changed)
        self.define_property("category", "persistent", changed=self.__property_changed)
        self.define_property("title", changed=self.__property_changed)
        self.define_property("caption", changed=self.__property_changed)
        self.define_property("description", changed=self.__property_changed)
        self.__data_and_metadata = None
        self.__data_and_metadata_lock = threading.RLock()
        self.__intensity_calibration = None
        self.__dimensional_calibrations = list()
        self.__metadata = dict()
        self.__data_ref_count = 0
        self.__data_ref_count_mutex = threading.RLock()
        self.__pending_write = True
        self.__in_transaction_state = False
        self.__write_delay_modified_count = 0
        self.__write_delay_data_changed = False
        self.data_changed_event = Event.Event()
        self.metadata_changed_event = Event.Event()
        if data is not None:
            data_and_metadata = DataAndMetadata.DataAndMetadata.from_data(data, timezone=self.timezone, timezone_offset=self.timezone_offset)
            self.__set_data_metadata_direct(data_and_metadata)

    def close(self):
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
        self.about_to_be_removed_event.fire()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True
        self.__container_weak_ref = None

    def __deepcopy__(self, memo):
        deepcopy = self.__class__()
        deepcopy.deepcopy_from(self, memo)
        memo[id(self)] = deepcopy
        return deepcopy

    def deepcopy_from(self, buffered_data_source, memo):
        super().deepcopy_from(buffered_data_source, memo)
        # data and metadata
        self.set_data_and_metadata(copy.deepcopy(buffered_data_source.data_and_metadata))
        # other metadata
        self.session_id = buffered_data_source.session_id
        self.session_data = copy.deepcopy(buffered_data_source.session_data)
        self.category = buffered_data_source.category
        self.title = buffered_data_source.title
        self.caption = buffered_data_source.caption
        self.description = buffered_data_source.description

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
        # other metadata
        buffered_data_source_copy.session_id = self.session_id
        buffered_data_source_copy.session_data = copy.deepcopy(self.session_data)
        buffered_data_source_copy.category = self.category
        buffered_data_source_copy.title = self.title
        buffered_data_source_copy.caption = self.caption
        buffered_data_source_copy.description = self.description
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
        self.__pending_write = False

    def write_data(self):
        if self.__data_and_metadata:
            self.persistent_object_context.write_external_data(self, "data", self.__data_and_metadata.data)

    def persistent_object_context_changed(self):
        super().persistent_object_context_changed()
        if self.__in_transaction_state:
            self.__enter_write_delay_state()
        if self.__data_and_metadata:
            self.__data_and_metadata.unloadable = self.persistent_object_context is not None

    @property
    def source_file_path(self) -> pathlib.Path:
        return self.__source_file_path

    @source_file_path.setter
    def source_file_path(self, value: typing.Optional[typing.Union[pathlib.Path, str]]) -> None:
        self.__source_file_path = pathlib.Path(value) if value is not None else pathlib.Path()

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

    def __timezone_property_changed(self, name, value):
        if self.__data_and_metadata:
            self.__data_and_metadata.data_metadata.timezone = self.timezone
            self.__data_and_metadata.data_metadata.timezone_offset = self.timezone_offset
        self.notify_property_changed(name)

    @property
    def session_data(self) -> dict:
        return copy.deepcopy(self._get_persistent_property_value("session"))

    @session_data.setter
    def session_data(self, value: dict) -> None:
        self._set_persistent_property_value("session", copy.deepcopy(value))

    def __validate_session_id(self, value):
        assert value is None or datetime.datetime.strptime(value, "%Y%m%d-%H%M%S")
        return value

    @property
    def data_metadata(self):
        return self.__data_and_metadata.data_metadata if self.__data_and_metadata else None

    @property
    def data_and_metadata(self):
        return self.__data_and_metadata

    def __load_data(self):
        if self.persistent_object_context:
            return self.persistent_object_context.read_external_data(self, "data")
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
            # save timezone info here so it doesn't get overwritten in intermediate states.
            timezone = self.__data_and_metadata.timezone
            timezone_offset = self.__data_and_metadata.timezone_offset
            if timezone:
                self._set_persistent_property_value("timezone", timezone)
            if timezone_offset:
                self._set_persistent_property_value("timezone_offset", timezone_offset)
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
                timezone = data_and_metadata.timezone or Utility.get_local_timezone()
                timezone_offset = data_and_metadata.timezone_offset or Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes())
                new_data_and_metadata = DataAndMetadata.DataAndMetadata(self.__load_data, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp, data, data_descriptor, timezone, timezone_offset)
            else:
                new_data_and_metadata = None
            self.__set_data_metadata_direct(new_data_and_metadata, data_modified)
            if self.__data_and_metadata is not None:
                if self.persistent_object_context:
                    self.persistent_object_context.write_external_data(self, "data", self.__data_and_metadata.data)
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

    @property
    def in_transaction_state(self) -> bool:
        return self.__in_transaction_state

    def _transaction_state_entered(self):
        self.__in_transaction_state = True
        # first enter the write delay state.
        self.__enter_write_delay_state()
        # load data to prevent paging in and out.
        self.increment_data_ref_count()

    def __enter_write_delay_state(self):
        self.__write_delay_modified_count = self.modified_count
        self.__write_delay_data_changed = False
        if self.persistent_object_context:
            self.persistent_object_context.exit_write_delay(self)

    def _transaction_state_exited(self):
        self.__in_transaction_state = False
        # exit the write delay state.
        if self.persistent_object_context:
            self.persistent_object_context.exit_write_delay(self)
            self._finish_pending_write()
        # unload data.
        self.decrement_data_ref_count()

    def _finish_pending_write(self):
        if self.__pending_write:
            # write the uuid and version explicitly
            self.persistent_object_context.property_changed(self, "uuid", str(self.uuid))
            self.persistent_object_context.property_changed(self, "version", DataItem.writer_version)
            self.persistent_object_context.write_external_data(self, "data", self.data)
            self.__pending_write = False
        else:
            if self.modified_count > self.__write_delay_modified_count:
                self.persistent_object_context.rewrite_item(self)
            if self.__write_delay_data_changed:
                self.persistent_object_context.write_external_data(self, "data", self.data)

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

class DataItem(Observable.Observable, Persistence.PersistentObject):
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

    storage_version = 13
    writer_version = 13

    def __init__(self, data=None, item_uuid=None, large_format=False):
        super().__init__()
        self.uuid = item_uuid if item_uuid else self.uuid
        self.large_format = large_format
        self.__container_weak_ref = None
        self.__in_transaction_state = False
        self.__is_live = False
        self.__pending_write = True
        self.__write_delay_modified_count = 0
        self.persistent_object_context = None
        self.define_property("created", datetime.datetime.utcnow(), converter=DatetimeToStringConverter(), changed=self.__description_property_changed)
        # windows utcnow has a resolution of 1ms, this sleep can guarantee unique times for all created times during a particular test.
        # this is not my favorite solution since it limits library item creation to 1000/s but until I find a better solution, this is my compromise.
        time.sleep(0.001)
        self.define_property("title", hidden=True, changed=self.__property_changed)
        self.define_property("caption", hidden=True, changed=self.__property_changed)
        self.define_property("description", hidden=True, changed=self.__property_changed)
        self.define_property("session_id", hidden=True, changed=self.__property_changed)
        self.define_property("category", "persistent", changed=self.__property_changed)
        self.define_property("source_uuid", converter=Converter.UuidToStringConverter())
        self.define_relationship("data_sources", data_source_factory, insert=self.__insert_data_source, remove=self.__remove_data_source)
        self.__session_manager = None
        self.__data_source_property_changed_event_listeners = list()
        self.__data_source_data_changed_event_listeners = list()
        self.__data_source_metadata_changed_event_listeners = list()
        self.__source = None
        self.description_changed_event = Event.Event()
        self.item_changed_event = Event.Event()
        self.metadata_changed_event = Event.Event()  # see Metadata Note above
        self.data_item_changed_event = Event.Event()  # anything has changed
        self.data_changed_event = Event.Event()  # data has changed
        self.__data_item_change_count = 0
        self.__data_item_change_count_lock = threading.RLock()
        self.__change_thread = None
        self.__change_count = 0
        self.__change_count_lock = threading.RLock()
        self.__change_changed = False
        self.__change_data_changed = False
        self.__pending_xdata_lock = threading.RLock()
        self.__pending_xdata = None
        self.__content_changed = False
        self.__suspendable_storage_cache = None
        self.r_var = None
        self.about_to_be_removed_event = Event.Event()
        self._about_to_be_removed = False
        self._closed = False
        if data is not None:
            self.set_data_source(BufferedDataSource(data))

    def __str__(self):
        return "{0} {1} ({2}, {3})".format(self.__repr__(), (self.title if self.title else _("Untitled")), str(self.uuid), self.date_for_sorting_local_as_string)

    def __copy__(self):
        assert False

    def __deepcopy__(self, memo):
        data_item_copy = self.__class__()
        # data format (temporary until moved to buffered data source)
        data_item_copy.large_format = self.large_format
        # metadata
        data_item_copy._set_persistent_property_value("title", self._get_persistent_property_value("title"))
        data_item_copy._set_persistent_property_value("caption", self._get_persistent_property_value("caption"))
        data_item_copy._set_persistent_property_value("description", self._get_persistent_property_value("description"))
        data_item_copy.created = self.created
        data_item_copy.session_id = self.session_id
        # data sources
        for data_source in self.data_sources:
            data_item_copy.append_data_source(copy.deepcopy(data_source))
        memo[id(self)] = data_item_copy
        return data_item_copy

    def close(self):
        self.__disconnect_data_sources()
        for data_source in self.data_sources:
            data_source.close()
        self.persistent_object_context = None
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None

    @property
    def container(self):
        return self.__container_weak_ref()

    def about_to_close(self):
        self.__disconnect_data_sources()

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self):
        self.__disconnect_data_sources()
        # called before close and before item is removed from its container
        self.about_to_be_removed_event.fire()
        for data_source in self.data_sources:
            data_source.about_to_be_removed()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

    def __disconnect_data_sources(self):
        for listener in self.__data_source_property_changed_event_listeners:
            listener.close()
        self.__data_source_property_changed_event_listeners.clear()
        for listener in self.__data_source_data_changed_event_listeners:
            listener.close()
        self.__data_source_data_changed_event_listeners.clear()
        for listener in self.__data_source_metadata_changed_event_listeners:
            listener.close()
        self.__data_source_metadata_changed_event_listeners.clear()

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

    def clone(self) -> "DataItem":
        data_item = self.__class__()
        data_item.uuid = self.uuid
        for data_source in self.data_sources:
            data_item.append_data_source(data_source.clone())
        return data_item

    def snapshot(self):
        """Return a new library item which is a copy of this one with any dynamic behavior made static."""
        data_item = self.__class__()
        # data format (temporary until moved to buffered data source)
        data_item.large_format = self.large_format
        # metadata
        data_item._set_persistent_property_value("title", self._get_persistent_property_value("title"))
        data_item._set_persistent_property_value("caption", self._get_persistent_property_value("caption"))
        data_item._set_persistent_property_value("description", self._get_persistent_property_value("description"))
        data_item.created = self.created
        data_item.session_id = self.session_id
        for data_source in self.data_sources:
            data_item.append_data_source(data_source.snapshot())
        return data_item

    def set_storage_cache(self, storage_cache):
        self.__suspendable_storage_cache = Cache.SuspendableCache(storage_cache)

    @property
    def _suspendable_storage_cache(self):
        return self.__suspendable_storage_cache

    @property
    def in_transaction_state(self) -> bool:
        return self.__in_transaction_state

    def __enter_write_delay_state(self):
        self.__write_delay_modified_count = self.modified_count
        self.__write_delay_data_changed = False
        if self.persistent_object_context:
            self.persistent_object_context.enter_write_delay(self)

    def __exit_write_delay_state(self):
        if self.persistent_object_context:
            self.persistent_object_context.exit_write_delay(self)
            self._finish_pending_write()

    def write_to_dict(self):
        properties = super().write_to_dict()
        properties["version"] = DataItem.writer_version
        return properties

    def _finish_pending_write(self):
        if self.__pending_write:
            # write the uuid and version explicitly
            self.persistent_object_context.property_changed(self, "uuid", str(self.uuid))
            self.persistent_object_context.property_changed(self, "version", DataItem.writer_version)
            for data_source in self.data_sources:
                data_source.write_data()
            self.__pending_write = False
        else:
            if self.modified_count > self.__write_delay_modified_count:
                self.persistent_object_context.rewrite_item(self)
            if self.__write_delay_data_changed:
                for data_source in self.data_sources:
                    data_source.write_data()

    def _transaction_state_entered(self):
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

    def _transaction_state_exited(self):
        self.__in_transaction_state = False
        # being in the transaction state has the side effect of delaying the cache too.
        # spill whatever was into the local cache into the persistent cache.
        if self.__suspendable_storage_cache:
            self.__suspendable_storage_cache.spill_cache()
        # exit the write delay state.
        self.__exit_write_delay_state()
        # tell each data source to unload its data.
        for data_source in self.data_sources:
            data_source.decrement_data_ref_count()

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
        return self.persistent_object_context.get_storage_property(self, "file_path")

    # access properties

    def read_from_dict(self, properties):
        self.large_format = properties.get("__large_format", self.large_format)
        # when reading, handle changes specially. first, put everything into a change
        # block; then make sure that no change notifications actually occur. this makes
        # sure things like cached values are preserved after reading.
        with self.data_item_changes():
            super().read_from_dict(properties)
            if self.created is None:  # invalid timestamp -- set property to now but don't trigger change
                timestamp = datetime.datetime.now()
                self._get_persistent_property("created").value = timestamp
            self.__content_changed = False
        self.__pending_write = False

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
        self._notify_data_item_content_changed()  # this will affect is_live, so notify

    def _exit_live_state(self):
        self.__is_live = False
        self._notify_data_item_content_changed()  # this will affect is_live, so notify

    @property
    def session_id(self) -> str:
        return self._get_persistent_property_value("session_id")

    @session_id.setter
    def session_id(self, value: str) -> None:
        assert value is None or datetime.datetime.strptime(value, "%Y%m%d-%H%M%S")
        self._set_persistent_property_value("session_id", value)
        if self.data_source:
            self.data_source.session_id = value

    def data_item_changes(self):
        # return a context manager to batch up a set of changes so that listeners
        # are only notified after the last change is complete.
        data_item = self
        class DataItemChangeContextManager:
            def __enter__(self):
                data_item._begin_data_item_changes()
                return self
            def __exit__(self, type, value, traceback):
                data_item._end_data_item_changes()
        return DataItemChangeContextManager()

    def _begin_data_item_changes(self):
        with self.__data_item_change_count_lock:
            self.__data_item_change_count += 1

    def _end_data_item_changes(self):
        with self.__data_item_change_count_lock:
            self.__data_item_change_count -= 1
            change_count = self.__data_item_change_count
            content_changed = self.__content_changed
        # if the change count is now zero, it means that we're ready to notify listeners. but only notify listeners if
        # there are actual changes to report.
        if change_count == 0 and content_changed:
            self.item_changed_event.fire()

    def __description_property_changed(self, name, value):
        self.__property_changed(name, value)
        self.__notify_description_changed()

    def __notify_description_changed(self):
        self._notify_data_item_content_changed()
        self._description_changed()

    def _description_changed(self):
        self.description_changed_event.fire()

    def __property_changed(self, name, value):
        self.notify_property_changed(name)

    def set_r_value(self, r_var: str, *, notify_changed=True) -> None:
        """Used to signal changes to the ref var, which are kept in document controller. ugh."""
        self.r_var = r_var
        self._description_changed()
        if notify_changed:  # set to False to set the r-value at startup; avoid marking it as a change
            self.__notify_description_changed()

    @property
    def displayed_title(self):
        if self.r_var:
            return "{0} ({1})".format(self.title, self.r_var)
        else:
            return self.title

    # call this when the listeners need to be updated (via data_item_content_changed).
    # Calling this method will send the data_item_content_changed method to each listener by using the method
    # data_item_changes.
    def _notify_data_item_content_changed(self):
        with self.data_item_changes():
            with self.__data_item_change_count_lock:
                self.__content_changed = True

    # date times

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
    def _session_manager(self) -> SessionManager:
        return self.__session_manager

    def set_session_manager(self, session_manager: SessionManager) -> None:
        self.__session_manager = session_manager

    # override from storage to watch for changes to this library item. notify observers.
    def notify_property_changed(self, key):
        super().notify_property_changed(key)
        self._notify_data_item_content_changed()

    # description

    # TODO: this needs to be connected to data sources
    def _data_source_property_changed(self, key: str) -> None:
        if self.data_source:
            if key in ("title", "caption", "description"):
                self.__description_property_changed("title", getattr(self.data_source, key))

    def __get_used_value(self, key: str, default_value):
        if self._get_persistent_property_value(key) is not None:
            return self._get_persistent_property_value(key)
        if self.data_source and getattr(self.data_source, key, None):
            return getattr(self.data_source, key)
        return default_value

    def __set_cascaded_value(self, key: str, value) -> None:
        if self.data_source:
            self._set_persistent_property_value(key, None)
            setattr(self.data_source, key, value)
        else:
            self._set_persistent_property_value(key, value)
            self.__description_property_changed(key, value)

    @property
    def title(self) -> str:
        return self.__get_used_value("title", UNTITLED_STR)

    @title.setter
    def title(self, value: str) -> None:
        self.__set_cascaded_value("title", str(value) if value is not None else str())

    @property
    def caption(self) -> str:
        return self.__get_used_value("caption", str())

    @caption.setter
    def caption(self, value: str) -> None:
        self.__set_cascaded_value("caption", str(value) if value is not None else str())

    @property
    def description(self) -> str:
        return self.__get_used_value("description", str())

    @description.setter
    def description(self, value: str) -> None:
        self.__set_cascaded_value("description", str(value) if value is not None else str())

    @property
    def text_for_filter(self):
        return " ".join([self.displayed_title, self.caption, self.description])

    # data sources

    def append_data_source(self, data_source):
        self.insert_data_source(len(self.data_sources), data_source)

    def insert_data_source(self, before_index, data_source):
        self.insert_item("data_sources", before_index, data_source)

    def remove_data_source(self, data_source):
        self.remove_item("data_sources", data_source)

    def __insert_data_source(self, name, before_index, data_source):
        data_source.about_to_be_inserted(self)
        assert name == "data_sources"
        self.__data_source_property_changed_event_listeners.append(data_source.property_changed_event.listen(self._data_source_property_changed))
        self.__data_source_data_changed_event_listeners.append(data_source.data_changed_event.listen(self._handle_data_changed))
        self.__data_source_metadata_changed_event_listeners.append(data_source.metadata_changed_event.listen(self._handle_metadata_changed))
        if self.in_transaction_state:
            data_source.increment_data_ref_count()
        self.notify_insert_item("data_sources", data_source, before_index)
        self._notify_data_item_content_changed()

    def __remove_data_source(self, name, index, data_source):
        data_source.about_to_be_removed()
        self.notify_remove_item("data_sources", data_source, index)
        self.__data_source_property_changed_event_listeners[index].close()
        del self.__data_source_property_changed_event_listeners[index]
        self.__data_source_data_changed_event_listeners[index].close()
        del self.__data_source_data_changed_event_listeners[index]
        self.__data_source_metadata_changed_event_listeners[index].close()
        del self.__data_source_metadata_changed_event_listeners[index]
        if self.in_transaction_state:
            data_source.decrement_data_ref_count()
        self._notify_data_item_content_changed()
        data_source.close()

    # temporary methods during restructuring

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
                if not self._is_reading:
                    self._handle_write_delay_data_changed()
                    self._notify_data_item_content_changed()
                    self.data_item_changed_event.fire()

    def _handle_data_changed(self, data_source):
        self.__change_changed = True
        self.__change_data_changed = True
        if self._session_manager:
            session_id = self._session_manager.current_session_id
            self.session_id = session_id
            if self.data_source:
                self.data_source.session_id = session_id

    def _handle_metadata_changed(self):
        self.__change_changed = True
        self.metadata_changed_event.fire()

    def _handle_write_delay_data_changed(self):
        self.__write_delay_data_changed = True

    def increment_data_ref_count(self):
        for data_source in self.data_sources:
            data_source.increment_data_ref_count()

    def decrement_data_ref_count(self):
        for data_source in self.data_sources:
            data_source.decrement_data_ref_count()

    def set_pending_xdata(self, xd: DataAndMetadata.DataAndMetadata) -> None:
        with self.__pending_xdata_lock:
            self.__pending_xdata = xd

    def update_to_pending_xdata(self):
        with self.__pending_xdata_lock:
            pending_xdata = self.__pending_xdata
            self.__pending_xdata = None
        if pending_xdata:
            assert threading.current_thread() == threading.main_thread()
            with self.data_item_changes():
                self.set_xdata(pending_xdata)

    def set_data_source(self, data_source):
        while len(self.data_sources) > 0:
            self.remove_data_source(self.data_sources[0])
        self.append_data_source(data_source)

    @property
    def data_source(self) -> typing.Optional[BufferedDataSource]:
        return self.data_sources[0] if len(self.data_sources) == 1 else None

    @property
    def xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.data_source.data_and_metadata if self.data_source else None

    @property
    def source_file_path(self) -> typing.Optional[pathlib.Path]:
        return self.data_source.source_file_path if self.data_source else None

    @source_file_path.setter
    def source_file_path(self, value: typing.Optional[typing.Union[pathlib.Path, str]]) -> None:
        assert self.data_source
        self.data_source.source_file_path = value

    @property
    def session_metadata(self) -> dict:
        return self.data_source.session_data if self.data_source else dict()

    @session_metadata.setter
    def session_metadata(self, value: dict) -> None:
        assert self.data_source
        self.data_source.session_data = value

    def ensure_data_source(self) -> None:
        if not self.data_source:
            self.set_data_source(BufferedDataSource())

    @property
    def data(self) -> numpy.ndarray:
        return self.__get_data()

    def set_data(self, data: numpy.ndarray, data_modified: datetime.datetime=None) -> None:
        timezone = Utility.get_local_timezone()
        timezone_offset = Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes())
        self.set_xdata(DataAndMetadata.new_data_and_metadata(data, data_modified, timezone=timezone, timezone_offset=timezone_offset))

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

    @property
    def timezone(self):
        return self.data_source.timezone

    @timezone.setter
    def timezone(self, value):
        self.data_source.timezone = value

    @property
    def timezone_offset(self):
        return self.data_source.timezone_offset

    @timezone_offset.setter
    def timezone_offset(self, value):
        self.data_source.timezone_offset = value

    def has_metadata_value(self, key: str) -> bool:
        return Metadata.has_metadata_value(self, key)

    def get_metadata_value(self, key: str) -> typing.Any:
        return Metadata.get_metadata_value(self, key)

    def set_metadata_value(self, key: str, value: typing.Any) -> None:
        Metadata.set_metadata_value(self, key, value)

    def delete_metadata_value(self, key: str) -> None:
        Metadata.delete_metadata_value(self, key)


class DisplayItem(Observable.Observable, Persistence.PersistentObject):
    def __init__(self, item_uuid=None):
        super().__init__()
        self.uuid = item_uuid if item_uuid else self.uuid
        self.__container_weak_ref = None
        self.define_property("created", datetime.datetime.utcnow(), converter=DatetimeToStringConverter(), changed=self.__property_changed)
        # windows utcnow has a resolution of 1ms, this sleep can guarantee unique times for all created times during a particular test.
        # this is not my favorite solution since it limits library item creation to 1000/s but until I find a better solution, this is my compromise.
        time.sleep(0.001)
        self.define_property("title", hidden=True, changed=self.__property_changed)
        self.define_property("caption", hidden=True, changed=self.__property_changed)
        self.define_property("description", hidden=True, changed=self.__property_changed)
        self.define_property("data_item_references", list(), changed=self.__property_changed)
        self.define_relationship("displays", Display.display_factory, insert=self.__insert_display, remove=self.__remove_display)
        self.__data_items = list()
        self.__suspendable_storage_cache = None
        self.__display_ref_count = 0
        self.about_to_be_removed_event = Event.Event()
        self._about_to_be_removed = False
        self._closed = False
        self.append_display(Display.Display())  # always have one display, for now
        self.__display_about_to_be_removed_listener = self.display.about_to_be_removed_event.listen(self.about_to_be_removed_event.fire)
        self._update_displays()

    def close(self):
        self.__display_about_to_be_removed_listener.close()
        self.__display_about_to_be_removed_listener = None
        for display in self.displays:
            display.close()
        self.__data_items = list()
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None

    def __copy__(self):
        assert False

    def __deepcopy__(self, memo):
        display_item_copy = self.__class__()
        # metadata
        display_item_copy._set_persistent_property_value("title", self._get_persistent_property_value("title"))
        display_item_copy._set_persistent_property_value("caption", self._get_persistent_property_value("caption"))
        display_item_copy._set_persistent_property_value("description", self._get_persistent_property_value("description"))
        display_item_copy.created = self.created
        # displays
        for display in copy.copy(display_item_copy.displays):
            display_item_copy.remove_display(display)
        for display in self.displays:
            display_item_copy.append_display(copy.deepcopy(display))
        display_item_copy.data_item_references = copy.deepcopy(self.data_item_references)
        memo[id(self)] = display_item_copy
        display_item_copy._update_displays()
        return display_item_copy

    @property
    def container(self):
        return self.__container_weak_ref()

    def about_to_close(self):
        self.__disconnect_data_sources()

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

    def __property_changed(self, name, value):
        self.notify_property_changed(name)

    def clone(self) -> "DisplayItem":
        display_item = self.__class__()
        display_item.uuid = self.uuid
        for display in copy.copy(display_item.displays):
            display_item.remove_display(display)
        for display in self.displays:
            display_item.append_display(display.clone())
        display_item._update_displays()
        return display_item

    def snapshot(self):
        """Return a new library item which is a copy of this one with any dynamic behavior made static."""
        display_item = self.__class__()
        # metadata
        display_item._set_persistent_property_value("title", self._get_persistent_property_value("title"))
        display_item._set_persistent_property_value("caption", self._get_persistent_property_value("caption"))
        display_item._set_persistent_property_value("description", self._get_persistent_property_value("description"))
        display_item.created = self.created
        for display in copy.copy(display_item.displays):
            display_item.remove_display(display)
        for display in self.displays:
            display_item.append_display(copy.deepcopy(display))
        display_item._update_displays()
        return display_item

    def set_storage_cache(self, storage_cache):
        self.__suspendable_storage_cache = Cache.SuspendableCache(storage_cache)
        for display in self.displays:
            display.set_storage_cache(self._suspendable_storage_cache)

    @property
    def _suspendable_storage_cache(self):
        return self.__suspendable_storage_cache

    def read_from_dict(self, properties):
        for display in copy.copy(self.displays):
            self.remove_display(display)
        super().read_from_dict(properties)
        if self.created is None:  # invalid timestamp -- set property to now but don't trigger change
            timestamp = datetime.datetime.now()
            self._get_persistent_property("created").value = timestamp
        self._update_displays()  # this ensures that the display will validate

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

    def append_display(self, display):
        """Add a display, but do it through the container, so dependencies can be tracked."""
        self.insert_model_item(self, "displays", self.item_count("displays"), display)
        if self.__display_ref_count > 0:
            display._become_master()

    def remove_display(self, display: Display.Display) -> typing.Optional[typing.Sequence]:
        """Remove display, but do it through the container, so dependencies can be tracked."""
        if self.__display_ref_count > 0:
            display._relinquish_master()
        return self.remove_model_item(self, "displays", display)

    def increment_display_ref_count(self, amount: int=1):
        """Increment display reference count to indicate this library item is currently displayed."""
        display_ref_count = self.__display_ref_count
        self.__display_ref_count += amount
        if display_ref_count == 0:
            for display in self.displays:
                display._become_master()
        for data_item in self.data_items:
            for _ in range(amount):
                data_item.increment_data_ref_count()

    def decrement_display_ref_count(self, amount: int=1):
        """Decrement display reference count to indicate this library item is no longer displayed."""
        assert not self._closed
        self.__display_ref_count -= amount
        if self.__display_ref_count == 0:
            for display in self.displays:
                display._relinquish_master()
        for data_item in self.data_items:
            for _ in range(amount):
                data_item.decrement_data_ref_count()

    @property
    def _display_ref_count(self):
        return self.__display_ref_count

    # TODO: connect to data item item_changed_event
    def _item_changed(self):
        for display in self.displays:
            display._item_changed()

    # TODO: connect to data item (various)
    def _description_changed(self):
        for display in self.displays:
            display.title = self.displayed_title

    def __get_used_value(self, key: str, default_value):
        if self._get_persistent_property_value(key) is not None:
            return self._get_persistent_property_value(key)
        if self.data_item and getattr(self.data_item, key, None):
            return getattr(self.data_item, key)
        return default_value

    def __set_cascaded_value(self, key: str, value) -> None:
        if self.data_item:
            self._set_persistent_property_value(key, None)
            setattr(self.data_item, key, value)
        else:
            self._set_persistent_property_value(key, value)
            self.__description_property_changed(key, value)

    @property
    def displayed_title(self):
        if self.data_item and getattr(self.data_item, "displayed_title", None):
            return self.data_item.displayed_title
        else:
            return self.title

    @property
    def title(self) -> str:
        return self.__get_used_value("title", UNTITLED_STR)

    @title.setter
    def title(self, value: str) -> None:
        self.__set_cascaded_value("title", str(value) if value is not None else str())

    @property
    def caption(self) -> str:
        return self.__get_used_value("caption", str())

    @caption.setter
    def caption(self, value: str) -> None:
        self.__set_cascaded_value("caption", str(value) if value is not None else str())

    @property
    def description(self) -> str:
        return self.__get_used_value("description", str())

    @description.setter
    def description(self, value: str) -> None:
        self.__set_cascaded_value("description", str(value) if value is not None else str())

    def connect_data_items(self, lookup_data_item):
        self.__data_items = [lookup_data_item(uuid.UUID(data_item_reference)) for data_item_reference in self.data_item_references]

    def append_data_item(self, data_item):
        self.insert_data_item(len(self.data_items), data_item)

    def insert_data_item(self, before_index, data_item):
        data_item_references = self.data_item_references
        data_item_references.insert(before_index, str(data_item.uuid))
        self.__data_items.insert(before_index, data_item)
        self.data_item_references = data_item_references

    def remove_data_item(self, data_item):
        data_item_references = self.data_item_references
        data_item_references.remove(str(data_item.uuid))
        self.__data_items.remove(data_item)
        self.data_item_references = data_item_references

    @property
    def data_items(self) -> typing.Sequence[DataItem]:
        return self.__data_items

    @property
    def data_item(self) -> typing.Optional[DataItem]:
        return self.__data_items[0] if len(self.__data_items) == 1 else None

    # TODO: connect this to changes in data item too
    def _update_displays(self):
        data_and_metadata = self.data_item.xdata if self.data_item else None
        for display in self.displays:
            display.update_data(data_and_metadata)

    @property
    def display(self) -> typing.Optional[Display.Display]:
        return self.displays[0]

    @property
    def graphics(self) -> typing.Sequence[Graphics.Graphic]:
        display = self.display
        return display.graphics if display else list()

    def insert_graphic(self, before_index: int, graphic: Graphics.Graphic) -> None:
        self.display.insert_graphic(before_index, graphic)

    def add_graphic(self, graphic: Graphics.Graphic) -> None:
        self.display.add_graphic(graphic)

    def remove_graphic(self, graphic: Graphics.Graphic, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        return self.display.remove_graphic(graphic, safe=safe)

    @property
    def graphic_selection(self):
        return self.display.graphic_selection

    @property
    def size_and_data_format_as_string(self) -> str:
        return self.data_item.size_and_data_format_as_string

    @property
    def date_for_sorting_local_as_string(self) -> str:
        return self.data_item.date_for_sorting_local_as_string

    @property
    def created_local(self) -> datetime.datetime:
        created_utc = self.created
        tz_minutes = Utility.local_utcoffset_minutes(created_utc)
        return created_utc + datetime.timedelta(minutes=tz_minutes)

    @property
    def is_live(self) -> bool:
        return any(data_item.is_live for data_item in self.data_items)

    @property
    def status_str(self) -> str:
        if self.data_item.is_live:
            live_metadata = self.data_item.metadata.get("hardware_source", dict())
            frame_index_str = str(live_metadata.get("frame_index", str()))
            partial_str = "{0:d}/{1:d}".format(live_metadata.get("valid_rows"), self.data_item.dimensional_shape[0]) if "valid_rows" in live_metadata else str()
            return "{0:s} {1:s} {2:s}".format(_("Live"), frame_index_str, partial_str)
        return str()

    @property
    def display_type(self) -> str:
        return self.display.display_type
    
    @display_type.setter
    def display_type(self, value: str) -> None:
        self.display.display_type = value

    @property
    def legend_labels(self) -> typing.Sequence[str]:
        return self.display.legend_labels

    @legend_labels.setter
    def legend_labels(self, value: typing.Sequence[str]) -> None:
        self.display.legend_labels = value

    def view_to_intervals(self, data_and_metadata: DataAndMetadata.DataAndMetadata, intervals: typing.List[typing.Tuple[float, float]]) -> None:
        self.display.view_to_intervals(data_and_metadata, intervals)


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

    def __init__(self, display_item: DisplayItem, graphic, changed_event):
        self.__display_item = display_item
        self.__graphic = graphic
        self.__changed_event = changed_event  # not public since it is passed in
        data_item = display_item.data_item if self.__display_item else None
        display = display_item.display if self.__display_item else None
        self.__data_item_changed_event_listener = None
        self.__data_item_changed_event_listener = data_item.data_item_changed_event.listen(self.__changed_event.fire) if data_item else None
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
        if self.__data_item_changed_event_listener:
            self.__data_item_changed_event_listener.close()
            self.__data_item_changed_event_listener = None
        if self.__display_values_event_listener:
            self.__display_values_event_listener.close()
            self.__display_values_event_listener = None

    @property
    def data_item(self) -> typing.Optional[DataItem]:
        return self.__display_item.data_item if self.__display_item else None

    @property
    def display(self) -> typing.Optional[Display.Display]:
        return self.__display_item.display if self.__display_item else None

    @property
    def graphic(self) -> typing.Optional[Graphics.Graphic]:
        return self.__graphic

    @property
    def data(self) -> typing.Optional[numpy.ndarray]:
        data_item = self.data_item
        return data_item.data if data_item else None

    @property
    def xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        data_item = self.data_item
        return data_item.xdata if data_item else None

    @property
    def display_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display = self.display
        return display.get_calculated_display_values(True).display_data_and_metadata if display else None

    @property
    def cropped_display_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        data_item = self.data_item
        if data_item:
            displayed_xdata = self.display_xdata
            graphic = self.__graphic
            if graphic:
                if hasattr(graphic, "bounds") and displayed_xdata.is_data_2d:
                    if graphic.rotation:
                        return Core.function_crop_rotated(displayed_xdata, graphic.bounds, graphic.rotation)
                    else:
                        return Core.function_crop(displayed_xdata, graphic.bounds)
                if hasattr(graphic, "interval") and displayed_xdata.is_data_1d:
                    return Core.function_crop_interval(displayed_xdata, graphic.interval)
            return displayed_xdata
        return None

    @property
    def cropped_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        data_item = self.data_item
        if data_item:
            xdata = self.xdata
            graphic = self.__graphic
            if graphic:
                if hasattr(graphic, "bounds"):
                    if graphic.rotation:
                        return Core.function_crop_rotated(xdata, graphic.bounds, graphic.rotation)
                    else:
                        return Core.function_crop(xdata, graphic.bounds)
                if hasattr(graphic, "interval"):
                    return Core.function_crop_interval(xdata, graphic.interval)
            return xdata
        return None

    @property
    def filtered_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        xdata = self.xdata
        if self.__display_item and xdata.is_data_2d and xdata.is_data_complex_type:
            shape = xdata.data_shape
            mask = numpy.zeros(shape)
            for graphic in self.__display_item.graphics:
                if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                    mask = numpy.logical_or(mask, graphic.get_mask(shape))
            return Core.function_fourier_mask(xdata, DataAndMetadata.DataAndMetadata.from_data(mask))
        return xdata

    @property
    def filter_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        shape = self.display_xdata.data_shape
        mask = numpy.zeros(shape)
        for graphic in self.__display_item.graphics:
            if isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic)):
                mask = numpy.logical_or(mask, graphic.get_mask(shape))
        return DataAndMetadata.DataAndMetadata.from_data(mask)
