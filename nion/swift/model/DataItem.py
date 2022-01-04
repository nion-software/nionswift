from __future__ import annotations

# standard libraries
import abc
import contextlib
import copy
import datetime
import functools
import gettext
import pathlib
import threading
import types
import typing
import uuid
import warnings
import weakref

# third party libraries
import numpy
import numpy.typing

# local libraries
from nion.data import Calibration
from nion.data import Core
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import ApplicationData
from nion.swift.model import Cache
from nion.swift.model import Graphics
from nion.swift.model import Metadata
from nion.swift.model import Persistence
from nion.swift.model import Schema
from nion.swift.model import Utility
from nion.utils import Event
from nion.utils import Geometry

if typing.TYPE_CHECKING:
    from nion.swift.model import DisplayItem
    from nion.swift.model import DocumentModel
    from nion.swift.model import Project

from nion.data.DataAndMetadata import _ImageDataType

_ = gettext.gettext

UNTITLED_STR = _("Untitled")


class CalibrationList:

    def __init__(self, calibrations: typing.Optional[DataAndMetadata.CalibrationListType] = None) -> None:
        self.list = list() if calibrations is None else copy.deepcopy(list(calibrations))

    def read_dict(self, storage_list: typing.Sequence[typing.Mapping[str, typing.Any]]) -> CalibrationList:
        # storage_list will be whatever is returned by write_dict.
        new_list: typing.List[Calibration.Calibration] = list()
        for calibration_dict in storage_list:
            new_list.append(Calibration.Calibration().read_dict(calibration_dict))
        self.list = new_list
        return self  # for convenience

    def write_dict(self) -> typing.List[Persistence.PersistentDictType]:
        l: typing.List[Persistence.PersistentDictType] = list()
        for calibration in self.list:
            l.append(calibration.write_dict())
        return l


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
    def convert(self, value: typing.Optional[numpy.typing.DTypeLike]) -> typing.Optional[str]:
        return str(value) if value is not None else None

    def convert_back(self, value: typing.Optional[str]) -> typing.Optional[numpy.typing.DTypeLike]:
        return numpy.dtype(value) if value is not None else None


class DatetimeToStringConverter:
    def convert(self, value: typing.Optional[datetime.datetime]) -> typing.Optional[str]:
        return value.isoformat() if value is not None else None

    def convert_back(self, value: typing.Optional[str]) -> typing.Optional[datetime.datetime]:
        try:
            if value and len(value) == 26:
                return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f")
            elif value and len(value) == 19:
                return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
        except ValueError as e:
            pass  # fall through
        return None


class UuidsToStringsConverter:
    def convert(self, value: typing.List[uuid.UUID]) -> typing.List[str]:
        return [str(uuid_) for uuid_ in value]

    def convert_back(self, value: typing.List[str]) -> typing.List[uuid.UUID]:
        return [uuid.UUID(uuid_str) for uuid_str in value]


class SessionManager(abc.ABC):

    @property
    @abc.abstractmethod
    def current_session_id(self) -> typing.Optional[str]:
        pass


# dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# time zone name is for display only and has no specified format

class DataItem(Persistence.PersistentObject):
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

    def __init__(self, data: typing.Optional[_ImageDataType] = None, item_uuid: typing.Optional[uuid.UUID] = None,
                 large_format: bool = False) -> None:
        super().__init__()
        self.uuid = item_uuid if item_uuid else self.uuid
        self.large_format = large_format
        self._document_model: typing.Optional[DocumentModel.DocumentModel] = None  # used only for Facade
        self.define_type("data-item")
        self.define_property("created", self.utcnow(), hidden=True, converter=DatetimeToStringConverter(), changed=self.__description_property_changed)
        data_shape = data.shape if data is not None else None
        data_dtype = data.dtype if data is not None else None
        dimensional_shape = Image.dimensional_shape_from_shape_and_dtype(data_shape, data_dtype)
        collection_dimension_count = (2 if len(dimensional_shape) == 3 else 0) if dimensional_shape is not None else None
        datum_dimension_count = len(dimensional_shape) - collection_dimension_count if dimensional_shape is not None and collection_dimension_count is not None else None
        self.define_property("data_shape", data_shape, hidden=True, recordable=False)
        self.define_property("data_dtype", data_dtype, hidden=True, recordable=False, converter=DtypeToStringConverter())
        self.define_property("is_sequence", False, hidden=True, recordable=False, changed=self.__data_description_changed)
        self.define_property("collection_dimension_count", collection_dimension_count, hidden=True, recordable=False, changed=self.__data_description_changed)
        self.define_property("datum_dimension_count", datum_dimension_count, hidden=True, recordable=False, changed=self.__data_description_changed)
        self.define_property("intensity_calibration", Calibration.Calibration(), hidden=True, make=Calibration.Calibration, changed=self.__metadata_property_changed)
        self.define_property("dimensional_calibrations", CalibrationList(), hidden=True, make=CalibrationList, changed=self.__dimensional_calibrations_changed)
        self.define_property("data_modified", hidden=True, recordable=False, converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed)
        self.define_property("timezone", Utility.get_local_timezone(), hidden=True, changed=self.__timezone_property_changed, recordable=False)
        self.define_property("timezone_offset", Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes()), hidden=True, changed=self.__timezone_property_changed, recordable=False)
        self.define_property("metadata", dict(), hidden=True, changed=self.__metadata_property_changed)
        self.define_property("title", UNTITLED_STR, changed=self.__property_changed, hidden=True)
        self.define_property("caption", changed=self.__property_changed, hidden=True)
        self.define_property("description", changed=self.__property_changed, hidden=True)
        self.define_property("source_specifier", changed=self.__source_specifier_changed, key="source_uuid", hidden=True)
        self.define_property("session_id", validate=self.__validate_session_id, changed=self.__property_changed, hidden=True)
        self.define_property("session", dict(), changed=self.__property_changed, hidden=True)
        self.define_property("category", "persistent", changed=self.__property_changed, hidden=True)
        self.__data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.__data_and_metadata_lock = threading.RLock()
        self.__intensity_calibration: typing.Optional[Calibration.Calibration] = None
        self.__dimensional_calibrations: typing.List[Calibration.Calibration] = list()
        self.__metadata: DataAndMetadata.MetadataType = dict()
        self.__data_ref_count = 0
        self.__data_ref_count_mutex = threading.RLock()
        self.__pending_write = True
        self.__in_transaction_state = False
        self.__write_delay_modified_count = 0
        self.__write_delay_data_changed = False
        self.__source_file_path: typing.Optional[pathlib.Path] = None
        self.__is_live = False
        self.__session_manager: typing.Optional[SessionManager] = None
        self.__source_reference = self.create_item_reference()
        self.description_changed_event = Event.Event()
        self.item_changed_event = Event.Event()
        self.metadata_changed_event = Event.Event()  # see Metadata Note above
        self.data_item_changed_event = Event.Event()  # anything has changed
        self.data_changed_event = Event.Event()  # data has changed
        self.will_change_event = Event.Event()
        self.did_change_event = Event.Event()
        self.__data_item_change_count = 0
        self.__data_item_change_count_lock = threading.RLock()
        self.__change_thread: typing.Optional[threading.Thread] = None
        self.__change_count = 0
        self.__change_count_lock = threading.RLock()
        self.__change_changed = False
        self.__change_data_changed = False
        self.__pending_xdata_lock = threading.RLock()
        self.__pending_xdata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.__pending_queue: typing.List[typing.Tuple[DataAndMetadata.DataAndMetadata, typing.Sequence[slice], typing.Sequence[slice], DataAndMetadata.DataMetadata]] = list()
        self.__content_changed = False
        self.__suspendable_storage_cache: typing.Optional[Cache.CacheLike] = None
        # Python 3.9+: parameterized set, weakref
        self.__display_data_channel_refs = set()  # type: ignore  # display data channels referencing this data item
        if data is not None:
            data_and_metadata = DataAndMetadata.DataAndMetadata.from_data(data, timezone=self.timezone, timezone_offset=self.timezone_offset)
            self.__set_data_and_metadata_direct(data_and_metadata)

    @classmethod
    def utcnow(cls) -> datetime.datetime:
        return Schema.utcnow()

    def __str__(self) -> str:
        return "{0} {1} ({2}, {3})".format(self.__repr__(), (self.title if self.title else _("Untitled")), str(self.uuid), self.date_for_sorting_local_as_string)

    def __copy__(self) -> DataItem:
        assert False

    def __deepcopy__(self, memo: typing.Dict[typing.Any, typing.Any]) -> DataItem:
        data_item_copy = self.__class__()
        # data format (temporary until moved to buffered data source)
        data_item_copy.large_format = self.large_format
        # metadata
        data_item_copy.created = self.created
        data_item_copy.timezone = self.timezone
        data_item_copy.timezone_offset = self.timezone_offset
        data_item_copy.metadata = self.metadata
        data_item_copy.title = self.title
        data_item_copy.caption = self.caption
        data_item_copy.description = self.description
        data_item_copy.session_id = self.session_id
        data_item_copy.session_data = copy.deepcopy(self.session_data)
        data_item_copy.category = self.category
        # data and metadata
        data_item_copy.set_data_and_metadata(copy.deepcopy(self.data_and_metadata), self.data_modified)
        memo[id(self)] = data_item_copy
        return data_item_copy

    def close(self) -> None:
        self.__data_and_metadata = None
        super().close()

    @property
    def created(self) -> datetime.datetime:
        return typing.cast(datetime.datetime, self._get_persistent_property_value("created"))

    @created.setter
    def created(self, value: datetime.datetime) -> None:
        self._set_persistent_property_value("created", value)

    @property
    def title(self) -> str:
        return typing.cast(str, self._get_persistent_property_value("title"))

    @title.setter
    def title(self, value: str) -> None:
        self._set_persistent_property_value("title", value)

    @property
    def caption(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("caption"))

    @caption.setter
    def caption(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("caption", value)

    @property
    def description(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("description"))

    @description.setter
    def description(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("description", value)

    @property
    def category(self) -> str:
        return typing.cast(str, self._get_persistent_property_value("category"))

    @category.setter
    def category(self, value: str) -> None:
        self._set_persistent_property_value("category", value)

    @property
    def session_id(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("session_id"))

    @session_id.setter
    def session_id(self, value: typing.Optional[str]) -> None:
        assert value is None or datetime.datetime.strptime(value, "%Y%m%d-%H%M%S")
        self._set_persistent_property_value("session_id", value)

    @property
    def session(self) -> Persistence.PersistentDictType:
        return typing.cast(Persistence.PersistentDictType, self._get_persistent_property_value("session"))

    @session.setter
    def session(self, value: Persistence.PersistentDictType) -> None:
        self._set_persistent_property_value("session", value)

    @property
    def source_specifier(self) -> typing.Optional[Persistence._SpecifierType]:
        return typing.cast(typing.Optional[Persistence._SpecifierType], self._get_persistent_property_value("source_specifier"))

    @source_specifier.setter
    def source_specifier(self, value: typing.Optional[Persistence._SpecifierType]) -> None:
        self._set_persistent_property_value("source_specifier", value)

    @property
    def project(self) -> Project.Project:
        return typing.cast("Project.Project", self.container)

    def create_proxy(self) -> Persistence.PersistentObjectProxy[DataItem]:
        return self.project.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(self.uuid)

    def clone(self) -> DataItem:
        data_item = self.__class__()
        data_item.uuid = self.uuid
        return data_item

    def snapshot(self) -> DataItem:
        """Return a new library item which is a copy of this one with any dynamic behavior made static."""
        data_item = self.__class__()
        # data format (temporary until moved to buffered data source)
        data_item.large_format = self.large_format
        data_item.set_data_and_metadata(copy.deepcopy(self.data_and_metadata), self.data_modified)
        # metadata
        data_item.created = self.created
        data_item.timezone = self.timezone
        data_item.timezone_offset = self.timezone_offset
        data_item.metadata = self.metadata
        data_item.title = self.title
        data_item.caption = self.caption
        data_item.description = self.description
        data_item.session_id = self.session_id
        data_item.session_data = copy.deepcopy(self.session_data)
        return data_item

    def set_storage_cache(self, storage_cache: Cache.CacheLike) -> None:
        self.__suspendable_storage_cache = Cache.SuspendableCache(storage_cache)

    @property
    def _suspendable_storage_cache(self) -> typing.Optional[Cache.CacheLike]:
        return self.__suspendable_storage_cache

    def add_display_data_channel(self, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        """Add a display data channel referencing this data item."""
        self.__display_data_channel_refs.add(weakref.ref(display_data_channel))
        self.notify_add_item("display_data_channels", display_data_channel)

    def remove_display_data_channel(self, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        """Remove a display data channel referencing this data item."""
        self.__display_data_channel_refs.remove(weakref.ref(display_data_channel))
        self.notify_discard_item("display_data_channels", display_data_channel)

    @property
    def display_data_channels(self) -> typing.Set[DisplayItem.DisplayDataChannel]:
        """Return the list of display data channels referencing this data item."""
        return {display_data_channel_ref() for display_data_channel_ref in self.__display_data_channel_refs}

    @property
    def in_transaction_state(self) -> bool:
        return self.__in_transaction_state

    def __enter_write_delay_state(self) -> None:
        self.__write_delay_modified_count = self.modified_count
        self.__write_delay_data_changed = False
        if self.persistent_object_context:
            self.enter_write_delay()

    def __exit_write_delay_state(self) -> None:
        if self.persistent_object_context:
            self.exit_write_delay()
            if self.__data_and_metadata:
                self.__data_and_metadata.unloadable = True
            self._finish_pending_write()

    def write_to_dict(self) -> Persistence.PersistentDictType:
        properties = super().write_to_dict()
        properties["version"] = DataItem.writer_version
        return properties

    def write_data_if_not_delayed(self) -> None:
        if not self.is_write_delayed:
            # write the uuid and version explicitly
            self.property_changed("uuid", str(self.uuid))
            self.property_changed("version", DataItem.writer_version)
            self.__write_data()
            self.__pending_write = False

    def __write_data(self) -> None:
        if self.__data_and_metadata:
            self.write_external_data("data", self.__data_and_metadata.data)

    def _finish_pending_write(self) -> None:
        if self.__pending_write:
            self.write_data_if_not_delayed()
        else:
            if self.modified_count > self.__write_delay_modified_count:
                self.rewrite()
            if self.__write_delay_data_changed:
                self.__write_data()

    def _transaction_state_entered(self) -> None:
        self.__in_transaction_state = True
        # first enter the write delay state.
        self.__enter_write_delay_state()
        # suspend disk caching
        if self.__suspendable_storage_cache:
            self.__suspendable_storage_cache.suspend_cache()
        # load data to prevent paging in and out.
        self.increment_data_ref_count()

    def _transaction_state_exited(self) -> None:
        self.__in_transaction_state = False
        # being in the transaction state has the side effect of delaying the cache too.
        # spill whatever was into the local cache into the persistent cache.
        if self.__suspendable_storage_cache:
            self.__suspendable_storage_cache.spill_cache()
        # exit the write delay state.
        self.__exit_write_delay_state()
        # unload data.
        self.decrement_data_ref_count()

    @property
    def source(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__source_reference.item

    @source.setter
    def source(self, source: typing.Optional[Persistence.PersistentObject]) -> None:
        self.__source_reference.item = source
        self.source_specifier = Persistence.write_persistent_specifier(source.uuid) if source else None

    def __source_specifier_changed(self, name: str, d: Persistence._SpecifierType) -> None:
        self.__source_reference.item_specifier = Persistence.read_persistent_specifier(d)

    def persistent_object_context_changed(self) -> None:
        # handle case where persistent object context is set on an item that is already under transaction.
        # this can occur during acquisition. any other cases?
        super().persistent_object_context_changed()

        # if self.__data_and_metadata:
        #     self.__data_and_metadata.unloadable = self.persistent_object_context is not None and not self.is_write_delayed

        if self.__in_transaction_state:
            self.__enter_write_delay_state()
        elif self.__data_and_metadata:
            self.__data_and_metadata.unloadable = self.persistent_object_context is not None and not self.is_write_delayed

    def _test_get_file_path(self) -> str:
        # hack for test function
        return typing.cast(str, getattr(self.persistent_storage, "get_storage_property")(self, "file_path")) if self.persistent_storage else str()

    def read_from_dict(self, properties: Persistence.PersistentDictType) -> None:
        self.large_format = properties.get("__large_format", self.large_format)
        # when reading, handle changes specially. first, put everything into a change
        # block; then make sure that no change notifications actually occur. this makes
        # sure things like cached values are preserved after reading.
        with self.data_item_changes():
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
                    assert dimensional_shape is not None
                    while len(dimensional_shape) > len(dimensional_calibrations):
                        dimensional_calibrations.append(Calibration.Calibration())
                    while len(dimensional_shape) < len(dimensional_calibrations):
                        dimensional_calibrations.pop(-1)
                metadata = self._get_persistent_property_value("metadata")
                timestamp = self._get_persistent_property_value("data_modified")
                if timestamp is None:  # invalid timestamp -- set property to now but don't trigger change
                    timestamp = self.created or datetime.datetime.now()
                    self._get_persistent_property("data_modified").value = timestamp
                is_sequence = self._get_persistent_property_value("is_sequence", False)
                collection_dimension_count = self._get_persistent_property_value("collection_dimension_count")
                datum_dimension_count = self._get_persistent_property_value("datum_dimension_count")
                if collection_dimension_count is None:
                    collection_dimension_count = 2 if dimensional_shape is not None and len(dimensional_shape) == 3 and not is_sequence else 0
                    # update collection_dimension_count, but in a way that sets the internal value but
                    # doesn't trigger a write to disk or a change modification.
                    self._get_persistent_property("collection_dimension_count").set_value(collection_dimension_count)
                if datum_dimension_count is None:
                    datum_dimension_count = len(dimensional_shape) - collection_dimension_count - (1 if is_sequence else 0) if dimensional_shape is not None and collection_dimension_count is not None else 0
                    # update collection_dimension_count, but in a way that sets the internal value but
                    # doesn't trigger a write to disk or a change modification.
                    self._get_persistent_property("datum_dimension_count").set_value(datum_dimension_count)
                data_descriptor = DataAndMetadata.DataDescriptor(is_sequence, collection_dimension_count, datum_dimension_count)
                self.__data_and_metadata = DataAndMetadata.DataAndMetadata(self.__load_data, data_shape_and_dtype,
                                                                           intensity_calibration,
                                                                           dimensional_calibrations, metadata,
                                                                           timestamp,
                                                                           data_descriptor=data_descriptor,
                                                                           timezone=self.timezone,
                                                                           timezone_offset=self.timezone_offset)
                with self.__data_ref_count_mutex:
                    self.__data_and_metadata._add_data_ref_count(self.__data_ref_count)
                self.__data_and_metadata.unloadable = self.persistent_object_context is not None
            else:
                metadata = self._get_persistent_property_value("metadata")
                self.__metadata = copy.deepcopy(metadata) if metadata else dict()
            self.__pending_write = False
            if self.created is None:  # invalid timestamp -- set property to now but don't trigger change
                self._get_persistent_property("created").value = datetime.datetime.now()
            self.__content_changed = False
        self.__pending_write = False

    @property
    def properties(self) -> typing.Optional[Persistence.PersistentDictType]:
        """ Used for debugging. """
        return self.get_storage_properties()

    @property
    def is_live(self) -> bool:
        """Return whether this library item represents live acquisition."""
        return self.__is_live

    def _enter_live_state(self) -> None:
        self.__is_live = True
        # live state is only a display item
        # also, there are still tests which filter data items; so leave this here until those tests are updated
        # the item_changed_event facilitates data item filtering
        self.item_changed_event.fire()

    def _exit_live_state(self) -> None:
        self.__is_live = False
        # live state is only a display item
        # also, there are still tests which filter data items; so leave this here until those tests are updated
        # the item_changed_event facilitates data item filtering
        self.item_changed_event.fire()

    def update_session(self, session_id: typing.Optional[str]) -> None:
        # update the session, but only if necessary (this is an optimization to prevent unnecessary display updates)
        if self.session_id != session_id:
            self.session_id = session_id
        session_metadata = ApplicationData.get_session_metadata_dict()
        if self.session_metadata != session_metadata:
            self.session_metadata = session_metadata

    class DataItemChangeContextManager:
        def __init__(self, data_item: DataItem) -> None:
            self.__data_item = data_item
        def __enter__(self) -> DataItem.DataItemChangeContextManager:
            self.__data_item._begin_data_item_changes()
            return self
        def __exit__(self, exception_type: typing.Optional[typing.Type[BaseException]], value: typing.Optional[BaseException], traceback: typing.Optional[types.TracebackType]) -> typing.Optional[bool]:
            self.__data_item._end_data_item_changes()
            return None

    def data_item_changes(self) -> contextlib.AbstractContextManager[DataItem.DataItemChangeContextManager]:
        # return a context manager to batch up a set of changes so that listeners
        # are only notified after the last change is complete.
        return DataItem.DataItemChangeContextManager(self)

    def _begin_data_item_changes(self) -> None:
        with self.__data_item_change_count_lock:
            change_count = self.__data_item_change_count
            self.__data_item_change_count += 1
        if change_count == 0:
            self.will_change_event.fire()

    def _end_data_item_changes(self) -> None:
        with self.__data_item_change_count_lock:
            self.__data_item_change_count -= 1
            change_count = self.__data_item_change_count
            content_changed = self.__content_changed
        # if the change count is now zero, it means that we're ready to notify listeners. but only notify listeners if
        # there are actual changes to report.
        if change_count == 0 and content_changed:
            self.item_changed_event.fire()
            self.did_change_event.fire()

    def __description_property_changed(self, name: str, value: typing.Any) -> None:
        self.__property_changed(name, value)
        self.__notify_description_changed()

    def __notify_description_changed(self) -> None:
        self._notify_data_item_content_changed()
        self._description_changed()

    def _description_changed(self) -> None:
        self.description_changed_event.fire()

    def __data_description_changed(self, name: str, value: int) -> None:
        self.__property_changed(name, value)
        self.__metadata_changed()

    def __dimensional_calibrations_changed(self, name: str, value: typing.Any) -> None:
        self.__property_changed(name, self.dimensional_calibrations)  # don't send out the CalibrationList object
        self.__metadata_changed()

    def __metadata_property_changed(self, name: str, value: typing.Any) -> None:
        self.__property_changed(name, value)
        self.__metadata_changed()

    def __metadata_changed(self) -> None:
        self.__change_changed = True
        self.metadata_changed_event.fire()

    def __property_changed(self, name: str, value: typing.Any) -> None:
        self.notify_property_changed(name)
        if name in ("title", "caption", "description"):
            self.__notify_description_changed()

    def __timezone_property_changed(self, name: str, value: typing.Optional[str]) -> None:
        timezone = self.timezone
        if self.__data_and_metadata and timezone is not None:
            self.__data_and_metadata.data_metadata.timezone = timezone
            self.__data_and_metadata.data_metadata.timezone_offset = self.timezone_offset or str()
        self.notify_property_changed(name)

    # call this when the listeners need to be updated (via data_item_content_changed).
    # Calling this method will send the data_item_content_changed method to each listener by using the method
    # data_item_changes.
    def _notify_data_item_content_changed(self) -> None:
        with self.data_item_changes():
            with self.__data_item_change_count_lock:
                self.__content_changed = True

    # date times

    @property
    def date_for_sorting(self) -> datetime.datetime:
        data_modified_list = list()
        data_modified = self.data_modified
        if data_modified:
            data_modified_list.append(data_modified)
        else:
            data_modified_list.append(self.created)
        if len(data_modified_list):
            return max(data_modified_list)
        return self.created

    @property
    def date_for_sorting_local_as_string(self) -> str:
        date_utc = self.date_for_sorting
        tz_minutes = Utility.local_utcoffset_minutes(date_utc)
        date_local = date_utc + datetime.timedelta(minutes=tz_minutes)
        return date_local.strftime("%c")

    @property
    def created_local_as_string(self) -> str:
        return self.created_local.strftime("%c")

    @property
    def created_local(self) -> datetime.datetime:
        created_utc = self.created
        tz_minutes = Utility.local_utcoffset_minutes(created_utc)
        return created_utc + datetime.timedelta(minutes=tz_minutes)

    # access description

    @property
    def _session_manager(self) -> typing.Optional[SessionManager]:
        return self.__session_manager

    def set_session_manager(self, session_manager: typing.Optional[SessionManager]) -> None:
        self.__session_manager = session_manager

    # override from storage to watch for changes to this library item. notify observers.
    def notify_property_changed(self, key: str) -> None:
        super().notify_property_changed(key)
        self._notify_data_item_content_changed()

    class ChangeContextManager:
        def __init__(self, begin_changes_fn: typing.Callable[[], None], end_changes_fn: typing.Callable[[], None]) -> None:
            self.__begin_changes_fn = begin_changes_fn
            self.__end_changes_fn = end_changes_fn
        def __enter__(self) -> DataItem.ChangeContextManager:
            self.__begin_changes_fn()
            return self
        def __exit__(self, exception_type: typing.Optional[typing.Type[BaseException]], value: typing.Optional[BaseException], traceback: typing.Optional[types.TracebackType]) -> typing.Optional[bool]:
            self.__end_changes_fn()
            return None

    def data_source_changes(self) -> contextlib.AbstractContextManager[DataItem.ChangeContextManager]:
        # return a context manager to batch up a set of changes so that listeners
        # are only notified after the last change is complete.
        return DataItem.ChangeContextManager(self.__begin_changes, self.__end_changes)

    def __begin_changes(self) -> None:
        self.will_change_event.fire()
        with self.__change_count_lock:
            if self.__change_count == 0:
                self.__change_thread = threading.current_thread()
            else:
                if self.__change_thread != threading.current_thread():
                    warnings.warn('begin changes from different threads', RuntimeWarning, stacklevel=2)
            self.__change_count += 1

    def __end_changes(self) -> None:
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
            if not self._is_reading:
                if data_changed:
                     self._handle_write_delay_data_changed()
                if data_changed or changed:
                    self._notify_data_item_content_changed()
                    self.data_item_changed_event.fire()
        self.did_change_event.fire()

    def _handle_write_delay_data_changed(self) -> None:
        self.__write_delay_data_changed = True

    def increment_data_ref_count(self) -> int:
        with self.__data_ref_count_mutex:
            initial_count = self.__data_ref_count
            self.__data_ref_count += 1
            if self.__data_and_metadata:
                self.__data_and_metadata.increment_data_ref_count()
        return initial_count + 1

    def decrement_data_ref_count(self) -> int:
        with self.__data_ref_count_mutex:
            assert self.__data_ref_count > 0
            self.__data_ref_count -= 1
            final_count = self.__data_ref_count
            if self.__data_and_metadata:
                self.__data_and_metadata.decrement_data_ref_count()
        return final_count

    def set_pending_xdata(self, xd: DataAndMetadata.DataAndMetadata) -> None:
        with self.__pending_xdata_lock:
            self.__pending_xdata = xd

    def queue_partial_update(self, partial_xdata: DataAndMetadata.DataAndMetadata, *, src_slice: typing.Sequence[slice],
                             dst_slice: typing.Sequence[slice], metadata: DataAndMetadata.DataMetadata) -> None:
        with self.__pending_xdata_lock:
            self.__pending_queue.append((partial_xdata, src_slice, dst_slice, metadata))

    def update_to_pending_xdata(self) -> None:
        with self.__pending_xdata_lock:
            pending_xdata = self.__pending_xdata
            pending_queue = self.__pending_queue
            self.__pending_xdata = None
            self.__pending_queue = list()
        if pending_xdata or pending_queue:
            assert threading.current_thread() == threading.main_thread()
            with self.data_item_changes():
                # it is an error to have both pending xdata and a pending queue
                assert not pending_xdata or not pending_queue
                if pending_xdata:
                    self.set_xdata(pending_xdata)
                for partial_xdata, partial_src_slice, partial_dst_slice, partial_metadata in pending_queue:
                    self.set_data_and_metadata_partial(partial_metadata, partial_xdata, partial_src_slice, partial_dst_slice, update_metadata=True)

    @property
    def xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.data_and_metadata

    @property
    def source_file_path(self) -> typing.Optional[pathlib.Path]:
        return self.__source_file_path

    @source_file_path.setter
    def source_file_path(self, value: typing.Optional[typing.Union[pathlib.Path, str]]) -> None:
        self.__source_file_path = pathlib.Path(value) if value is not None else pathlib.Path()

    @property
    def session_metadata(self) -> DataAndMetadata.MetadataType:
        return copy.deepcopy(self._get_persistent_property_value("session"))

    @session_metadata.setter
    def session_metadata(self, value: DataAndMetadata.MetadataType) -> None:
        self._set_persistent_property_value("session", copy.deepcopy(value))

    @property
    def session_data(self) -> DataAndMetadata.MetadataType:
        return self.session_metadata

    @session_data.setter
    def session_data(self, value: DataAndMetadata.MetadataType) -> None:
        self.session_metadata = value

    def __validate_session_id(self, value: typing.Any) -> typing.Optional[datetime.datetime]:
        assert value is None or datetime.datetime.strptime(value, "%Y%m%d-%H%M%S")
        return typing.cast(typing.Optional[datetime.datetime], value)

    def ensure_data_source(self) -> None:
        pass

    @property
    def data(self) -> typing.Optional[_ImageDataType]:
        return self.__get_data()

    def set_data(self, data: _ImageDataType, data_modified: typing.Optional[datetime.datetime] = None) -> None:
        timezone = Utility.get_local_timezone()
        timezone_offset = Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes())
        self.set_xdata(DataAndMetadata.new_data_and_metadata(data, timestamp=data_modified, timezone=timezone, timezone_offset=timezone_offset))

    def set_xdata(self, xdata: typing.Optional[DataAndMetadata.DataAndMetadata], data_modified: typing.Optional[datetime.datetime] = None) -> None:
        with self.data_source_changes():
            self.ensure_data_source()
            self.set_data_and_metadata(xdata, data_modified)

    class DataAccessor:
        def __init__(self, data_item: DataItem, get_data: typing.Callable[[], typing.Optional[_ImageDataType]], set_data: typing.Callable[[typing.Optional[_ImageDataType]], None]) -> None:
            self.__data_item = data_item
            self.__get_data = get_data
            self.__set_data = set_data

        def __enter__(self) -> DataItem.DataAccessor:
            self.__data_item.increment_data_ref_count()
            return self

        def __exit__(self, exception_type: typing.Optional[typing.Type[BaseException]], value: typing.Optional[BaseException], traceback: typing.Optional[types.TracebackType]) -> typing.Optional[bool]:
            self.__data_item.decrement_data_ref_count()
            return None

        @property
        def data(self) -> typing.Optional[_ImageDataType]:
            return self.__get_data()

        @data.setter
        def data(self, value: _ImageDataType) -> None:
            self.__set_data(value)

        def data_updated(self) -> None:
            self.__set_data(self.__get_data())

        @property
        def master_data(self) -> typing.Optional[_ImageDataType]:
            return self.__get_data()

        @master_data.setter
        def master_data(self, value: _ImageDataType) -> None:
            self.__set_data(value)

        def master_data_updated(self) -> None:
            self.__set_data(self.__get_data())

    # grab a data reference as a context manager. the object
    # returned defines data and data properties. reading data
    # should use the data property. writing data (if allowed) should
    # assign to the data property.
    def data_ref(self) -> contextlib.AbstractContextManager[DataItem.DataAccessor]:
        return DataItem.DataAccessor(self, self.__get_data, self.__set_data)

    def __get_data(self) -> typing.Optional[_ImageDataType]:
        return self.__data_and_metadata.data if self.__data_and_metadata else None

    def __set_data(self, data: typing.Optional[_ImageDataType], data_modified: typing.Optional[datetime.datetime] = None) -> None:
        with self.data_source_changes():
            if data is not None:
                dimensional_shape = Image.dimensional_shape_from_data(data)
                data_and_metadata = self.data_and_metadata
                intensity_calibration = data_and_metadata.intensity_calibration if data_and_metadata else None
                dimensional_calibrations: typing.Optional[typing.List[Calibration.Calibration]] = None
                metadata: typing.Optional[DataAndMetadata.MetadataType] = None
                timestamp: typing.Optional[datetime.datetime] = None  # always update when the data is modified
                data_descriptor: typing.Optional[DataAndMetadata.DataDescriptor] = None
                if data_and_metadata:
                    assert dimensional_shape is not None
                    dimensional_calibrations = list(data_and_metadata.dimensional_calibrations)
                    while len(dimensional_calibrations) < len(dimensional_shape):
                        dimensional_calibrations.append(Calibration.Calibration())
                    while len(dimensional_calibrations) > len(dimensional_shape):
                        dimensional_calibrations.pop(-1)
                    metadata = data_and_metadata.metadata
                    data_descriptor = data_and_metadata.data_descriptor
                self.set_data_and_metadata(DataAndMetadata.DataAndMetadata.from_data(data, intensity_calibration, dimensional_calibrations, metadata, timestamp, data_descriptor), data_modified)
            else:
                self.set_data_and_metadata(None)

    @property
    def intensity_calibration(self) -> typing.Optional[Calibration.Calibration]:
        data_and_metadata = self.__data_and_metadata
        return copy.deepcopy(data_and_metadata.intensity_calibration) if data_and_metadata else self.__intensity_calibration

    @intensity_calibration.setter
    def intensity_calibration(self, intensity_calibration: Calibration.Calibration) -> None:
        with self.data_source_changes():
            if self.__data_and_metadata:  # handle case of missing data and metadata but doing recording
                self.__data_and_metadata._set_intensity_calibration(intensity_calibration)
            self.__intensity_calibration = copy.deepcopy(intensity_calibration)  # backup in case of no data and metadata
            self._set_persistent_property_value("intensity_calibration", intensity_calibration)

    def set_intensity_calibration(self, intensity_calibration: Calibration.Calibration) -> None:
        self.intensity_calibration = intensity_calibration

    @property
    def dimensional_calibrations(self) -> DataAndMetadata.CalibrationListType:
        data_and_metadata = self.__data_and_metadata
        return copy.deepcopy(data_and_metadata.dimensional_calibrations) if data_and_metadata else self.__dimensional_calibrations

    @dimensional_calibrations.setter
    def dimensional_calibrations(self, dimensional_calibrations: DataAndMetadata.CalibrationListType) -> None:
        with self.data_source_changes():
            if self.__data_and_metadata:  # handle case of missing data and metadata but doing recording
                self.__data_and_metadata._set_dimensional_calibrations(dimensional_calibrations)
            self.__dimensional_calibrations = copy.deepcopy(list(dimensional_calibrations))  # backup in case of no data and metadata
            self._set_persistent_property_value("dimensional_calibrations", CalibrationList(dimensional_calibrations))

    def set_dimensional_calibrations(self, dimensional_calibrations: DataAndMetadata.CalibrationListType) -> None:
        self.dimensional_calibrations = dimensional_calibrations

    def set_dimensional_calibration(self, dimension: int, calibration: Calibration.Calibration) -> None:
        dimensional_calibrations = list(self.dimensional_calibrations)
        while len(dimensional_calibrations) <= dimension:
            dimensional_calibrations.append(Calibration.Calibration())
        dimensional_calibrations[dimension] = calibration
        self.set_dimensional_calibrations(dimensional_calibrations)

    @property
    def data_modified(self) -> typing.Optional[datetime.datetime]:
        return self.__data_and_metadata.timestamp if self.__data_and_metadata else None

    @data_modified.setter
    def data_modified(self, value: datetime.datetime) -> None:
        if self.__data_and_metadata:
            self.__data_and_metadata.timestamp = value
            self._set_persistent_property_value("data_modified", value)
            self.__metadata_property_changed("data_modified", value)

    @property
    def timezone(self) -> typing.Optional[str]:
        data_and_metadata = self.__data_and_metadata
        return data_and_metadata.timezone if data_and_metadata else Utility.get_local_timezone()

    @timezone.setter
    def timezone(self, value: str) -> None:
        if self.__data_and_metadata:
            self.__data_and_metadata.timezone = value
            self._set_persistent_property_value("timezone", value)
            self.__timezone_property_changed("timezone", value)

    @property
    def timezone_offset(self) -> typing.Optional[str]:
        data_and_metadata = self.__data_and_metadata
        return data_and_metadata.timezone_offset if data_and_metadata else Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes())

    @timezone_offset.setter
    def timezone_offset(self, value: str) -> None:
        if self.__data_and_metadata:
            self.__data_and_metadata.timezone_offset = value
            self._set_persistent_property_value("timezone_offset", value)
            self.__timezone_property_changed("timezone_offset", value)

    @property
    def metadata(self) -> DataAndMetadata.MetadataType:
        data_and_metadata = self.__data_and_metadata
        return copy.deepcopy(dict(data_and_metadata.metadata)) if data_and_metadata else self.__metadata

    @metadata.setter
    def metadata(self, metadata: DataAndMetadata.MetadataType) -> None:
        with self.data_source_changes():
            assert isinstance(metadata, dict)
            if self.__data_and_metadata:
                self.__data_and_metadata._set_metadata(metadata)
            self.__metadata = copy.deepcopy(metadata) if metadata else dict()
            self._set_persistent_property_value("metadata", self.__metadata)

    @property
    def has_data(self) -> bool:
        return self.__data_and_metadata is not None

    # used for testing
    @property
    def is_data_loaded(self) -> bool:
        return self.__data_and_metadata is not None and self.__data_and_metadata.is_data_valid

    @property
    def data_metadata(self) -> typing.Optional[DataAndMetadata.DataMetadata]:
        data_and_metadata = self.__data_and_metadata
        return data_and_metadata.data_metadata if data_and_metadata else None

    @property
    def data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__data_and_metadata

    def __load_data(self) -> typing.Optional[_ImageDataType]:
        if self.persistent_object_context:
            return typing.cast(typing.Optional[_ImageDataType], self.read_external_data("data"))
        return None

    def __set_data_metadata_direct(self, data_metadata: DataAndMetadata.DataMetadata,
                                   data_modified: typing.Optional[datetime.datetime] = None) -> None:
        # set the persistent values for the data_metadata
        self._set_persistent_property_value("data_shape", data_metadata.data_shape)
        self._set_persistent_property_value("data_dtype", DtypeToStringConverter().convert(data_metadata.data_dtype))
        self._set_persistent_property_value("is_sequence", data_metadata.is_sequence)
        self._set_persistent_property_value("collection_dimension_count", data_metadata.collection_dimension_count)
        self._set_persistent_property_value("datum_dimension_count", data_metadata.datum_dimension_count)
        self._set_persistent_property_value("intensity_calibration", copy.deepcopy(data_metadata.intensity_calibration))
        self._set_persistent_property_value("dimensional_calibrations", CalibrationList(data_metadata.dimensional_calibrations))
        # save timezone info here so it doesn't get overwritten in intermediate states.
        timezone = data_metadata.timezone
        timezone_offset = data_metadata.timezone_offset
        if timezone:
            self._set_persistent_property_value("timezone", timezone)
        if timezone_offset:
            self._set_persistent_property_value("timezone_offset", timezone_offset)
        # explicitly set metadata into persistent storage to prevent notifications.
        self.__metadata = data_metadata.metadata
        self._set_persistent_property_value("metadata", self.__metadata)
        # set the data modified directly
        data_modified = data_modified if data_modified else datetime.datetime.utcnow()
        data_metadata.timestamp = data_modified
        self._set_persistent_property_value("data_modified", data_modified)

    def __set_data_and_metadata_direct(self, data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata],
                                       data_modified: typing.Optional[datetime.datetime] = None) -> None:
        with self.__data_ref_count_mutex:
            if self.__data_and_metadata:
                self.__data_and_metadata._subtract_data_ref_count(self.__data_ref_count)
            self.__data_and_metadata = data_and_metadata
            if self.__data_and_metadata:
                self.__data_and_metadata._add_data_ref_count(self.__data_ref_count)
        if self.__data_and_metadata:
            self.__set_data_metadata_direct(self.__data_and_metadata.data_metadata, data_modified)
        self.__change_changed = True
        self.__change_data_changed = True
        if self._session_manager:
            session_id = self._session_manager.current_session_id
            self.session_id = session_id

    def set_data_and_metadata(self, data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata], data_modified: typing.Optional[datetime.datetime] = None) -> None:
        """Sets the underlying data and data-metadata to the data_and_metadata.

        Note: this does not make a copy of the data.
        """
        self.increment_data_ref_count()
        try:
            new_data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata]
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
            self.__set_data_and_metadata_direct(new_data_and_metadata, data_modified)
            if self.__data_and_metadata is not None:
                if self.persistent_object_context and not self.is_write_delayed:
                    self.write_external_data("data", self.__data_and_metadata.data)
                    self.__data_and_metadata.unloadable = True
        finally:
            self.decrement_data_ref_count()

    def reserve_data(self, *, data_shape: DataAndMetadata.ShapeType, data_dtype: numpy.typing.DTypeLike, data_descriptor: DataAndMetadata.DataDescriptor, data_modified: typing.Optional[datetime.datetime] = None) -> None:
        """Reserves the underlying data without necessarily allocating memory. Useful for memory mapped files.
        """
        self.increment_data_ref_count()
        try:
            if self.persistent_object_context:
                self.reserve_external_data("data", data_shape, data_dtype)
                data = self.__load_data()
                if data is None:
                    data = numpy.zeros(data_shape, data_dtype)
                data_shape_and_dtype = data_shape, data_dtype
                timezone = Utility.get_local_timezone()
                timezone_offset = Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes())
                new_data_and_metadata = DataAndMetadata.DataAndMetadata(self.__load_data, data_shape_and_dtype, None, None, None, None, data, data_descriptor, timezone, timezone_offset)
                self.__set_data_and_metadata_direct(new_data_and_metadata, data_modified)
                if self.__data_and_metadata:
                    self.__data_and_metadata.unloadable = True
        finally:
            self.decrement_data_ref_count()

    def set_data_and_metadata_partial(self, data_metadata: DataAndMetadata.DataMetadata,
                                      data_and_metadata: DataAndMetadata.DataAndMetadata, src: typing.Sequence[slice],
                                      dst: typing.Sequence[slice], update_metadata: bool = False,
                                      data_modified: typing.Optional[datetime.datetime] = None) -> None:
        # metadata is updated from data_metadata; data_and_metadata is only used for data
        with self.data_source_changes():
            self.increment_data_ref_count()
            try:
                if not self.__data_and_metadata:
                    data: numpy.typing.NDArray[typing.Any] = numpy.zeros(data_metadata.data_shape, data_metadata.data_dtype)
                    data_shape_and_dtype = data_metadata.data_shape_and_dtype
                    intensity_calibration = data_metadata.intensity_calibration
                    dimensional_calibrations = data_metadata.dimensional_calibrations
                    metadata = data_metadata.metadata
                    timestamp = data_metadata.timestamp
                    data_descriptor = data_metadata.data_descriptor
                    timezone = data_metadata.timezone or Utility.get_local_timezone()
                    timezone_offset = data_metadata.timezone_offset or Utility.TimezoneMinutesToStringConverter().convert(
                        Utility.local_utcoffset_minutes())
                    new_data_and_metadata = DataAndMetadata.DataAndMetadata(self.__load_data, data_shape_and_dtype,
                                                                            intensity_calibration,
                                                                            dimensional_calibrations, metadata,
                                                                            timestamp, data, data_descriptor, timezone,
                                                                            timezone_offset)
                    self.__set_data_and_metadata_direct(new_data_and_metadata, data_modified)
                if self.__data_and_metadata is not None:
                    if update_metadata:
                        self.__data_and_metadata._set_data_descriptor(data_metadata.data_descriptor)
                        self.__data_and_metadata._set_intensity_calibration(data_metadata.intensity_calibration)
                        self.__data_and_metadata._set_dimensional_calibrations(data_metadata.dimensional_calibrations)
                        self.__data_and_metadata._set_metadata(data_metadata.metadata)
                        self.__data_and_metadata._set_timestamp(data_metadata.timestamp)
                        self.__data_and_metadata.timezone = data_metadata.timezone
                        self.__data_and_metadata.timezone_offset = data_metadata.timezone_offset
                        self.__set_data_metadata_direct(data_metadata)
                    assert self.__data_and_metadata.data_shape == data_metadata.data_shape
                    assert self.__data_and_metadata.data_dtype == data_metadata.data_dtype
                    assert self.__data_and_metadata.data_dtype == data_and_metadata.data_dtype
                    self.__data_and_metadata._data_ex[tuple(dst)] = data_and_metadata._data_ex[tuple(src)]
                    # mark changes and update session
                    self.__change_changed = True
                    self.__change_data_changed = True
                    if self._session_manager:
                        session_id = self._session_manager.current_session_id
                        self.session_id = session_id
                    # set data_shape as a way to update 'modified' property
                    self._set_persistent_property_value("data_shape", self.__data_and_metadata.data_shape)
                    if self.persistent_object_context and not self.is_write_delayed:
                        self.write_external_data("data", self.__data_and_metadata.data)
                        self.__data_and_metadata.unloadable = True
            finally:
                self.decrement_data_ref_count()

    @property
    def data_shape(self) -> typing.Optional[DataAndMetadata.ShapeType]:
        return self.__data_and_metadata.data_shape if self.__data_and_metadata else None

    @property
    def data_dtype(self) -> typing.Optional[numpy.typing.DTypeLike]:
        return self.__data_and_metadata.data_dtype if self.__data_and_metadata else None

    @property
    def dimensional_shape(self) -> DataAndMetadata.ShapeType:
        return self.__data_and_metadata.dimensional_shape if self.__data_and_metadata else tuple()

    @property
    def datum_dimension_shape(self) -> DataAndMetadata.ShapeType:
        return self.__data_and_metadata.datum_dimension_shape if self.__data_and_metadata else tuple()

    @property
    def datum_dimension_count(self) -> int:
        return self.__data_and_metadata.datum_dimension_count if self.__data_and_metadata else 0

    @property
    def collection_dimension_count(self) -> int:
        return self.__data_and_metadata.collection_dimension_count if self.__data_and_metadata else 0

    @property
    def is_collection(self) -> bool:
        return self.collection_dimension_count > 0 if self.collection_dimension_count is not None else False

    @property
    def is_sequence(self) -> bool:
        return self.__data_and_metadata.is_sequence if self.__data_and_metadata else False

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

    def get_data_value(self, pos: DataAndMetadata.ShapeType) -> typing.Any:
        return self.__data_and_metadata.get_data_value(pos) if self.__data_and_metadata else None

    @property
    def size_and_data_format_as_string(self) -> str:
        return self.__data_and_metadata.size_and_data_format_as_string if self.__data_and_metadata else _("No Data")

    def has_metadata_value(self, key: str) -> bool:
        return Metadata.has_metadata_value(self, key)

    def get_metadata_value(self, key: str) -> typing.Any:
        return Metadata.get_metadata_value(self, key)

    def set_metadata_value(self, key: str, value: typing.Any) -> None:
        Metadata.set_metadata_value(self, key, value)

    def delete_metadata_value(self, key: str) -> None:
        Metadata.delete_metadata_value(self, key)


def sort_by_date_key(data_item: DataItem) -> typing.Tuple[typing.Optional[str], datetime.datetime, str]:
    """ A sort key to for the created field of a data item. The sort by uuid makes it determinate. """
    return data_item.title + str(data_item.uuid) if data_item.is_live else str(), data_item.date_for_sorting, str(data_item.uuid)


def new_data_item(data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None) -> DataItem:
    data_item = DataItem(large_format=len(data_and_metadata.dimensional_shape) > 2 if data_and_metadata else False)
    data_item.ensure_data_source()
    data_item.set_xdata(data_and_metadata)
    return data_item


def create_mask_data(graphics: typing.Sequence[Graphics.Graphic], shape: DataAndMetadata.ShapeType, calibrated_origin: Geometry.FloatPoint) -> _ImageDataType:
    mask = None
    for graphic in graphics:
        if isinstance(graphic, (Graphics.PointTypeGraphic, Graphics.LineTypeGraphic, Graphics.RectangleTypeGraphic, Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
            if graphic.used_role in ("mask", "fourier_mask"):
                if mask is None:
                    mask = numpy.zeros(shape)
                mask = numpy.logical_or(mask, graphic.get_mask(shape, calibrated_origin))
    if mask is None:
        mask = numpy.ones(shape)
    return mask


class DataSource:
    def __init__(self, display_data_channel: DisplayItem.DisplayDataChannel, graphic: typing.Optional[Graphics.Graphic], xdata: typing.Optional[DataAndMetadata.DataAndMetadata] = None) -> None:
        self.__display_data_channel = display_data_channel
        self.__display_item = typing.cast("DisplayItem.DisplayItem", display_data_channel.container) if display_data_channel else None
        self.__data_item = display_data_channel.data_item if display_data_channel else None
        self.__graphic = graphic
        self.__xdata = xdata

    def close(self) -> None:
        pass

    @property
    def display_data_channel(self) -> DisplayItem.DisplayDataChannel:
        return self.__display_data_channel

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        return self.__display_item

    @property
    def data_item(self) -> typing.Optional[DataItem]:
        return self.__data_item

    @property
    def graphic(self) -> typing.Optional[Graphics.Graphic]:
        return self.__graphic

    @property
    def data(self) -> typing.Optional[_ImageDataType]:
        return self.xdata.data if self.xdata else None

    @property
    def xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        if self.__xdata is not None:
            return self.__xdata
        if self.data_item:
            return self.data_item.xdata
        return None

    @property
    def element_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self.__display_data_channel
        if display_data_channel:
            if self.__xdata is not None:
                return Core.function_convert_to_scalar(self.__xdata, display_data_channel.complex_display_type)
            else:
                display_values = display_data_channel.get_calculated_display_values()
                if display_values:
                    return display_values.element_data_and_metadata
        return None

    @property
    def display_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self.__display_data_channel
        if display_data_channel:
            if self.__xdata is not None:
                return Core.function_convert_to_scalar(self.__xdata, display_data_channel.complex_display_type)
            else:
                display_values = display_data_channel.get_calculated_display_values()
                if display_values:
                    return display_values.display_data_and_metadata
        return None

    @property
    def display_rgba(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self.__display_data_channel
        if display_data_channel:
            if self.__xdata is not None:
                return self.xdata
            else:
                display_values = display_data_channel.get_calculated_display_values()
                if display_values:
                    display_rgba = display_values.display_rgba
                    return DataAndMetadata.new_data_and_metadata(Image.get_byte_view(display_rgba)) if display_rgba is not None else None
        return None

    @property
    def normalized_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self.__display_data_channel
        if display_data_channel:
            if self.__xdata is not None:
                display_xdata = self.display_xdata
                if display_xdata:
                    return Core.function_rescale(display_xdata, (0, 1))
                else:
                    return None
            else:
                display_values = display_data_channel.get_calculated_display_values()
                if display_values:
                    return display_values.normalized_data_and_metadata
        return None

    @property
    def adjusted_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self.__display_data_channel
        if display_data_channel:
            if self.__xdata is not None:
                return self.normalized_xdata
            else:
                display_values = display_data_channel.get_calculated_display_values()
                if display_values:
                    return display_values.adjusted_data_and_metadata
        return None

    @property
    def transformed_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        display_data_channel = self.__display_data_channel
        if display_data_channel:
            if self.__xdata is not None:
                return self.normalized_xdata
            else:
                display_values = display_data_channel.get_calculated_display_values()
                if display_values:
                    return display_values.transformed_data_and_metadata
        return None

    def __cropped_xdata(self, xdata: typing.Optional[DataAndMetadata.DataAndMetadata]) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        data_item = self.data_item
        graphic = self.__graphic
        if data_item:
            if isinstance(graphic, Graphics.RectangleTypeGraphic) and xdata and xdata.is_data_2d:
                if graphic.rotation:
                    return Core.function_crop_rotated(xdata, graphic.bounds.as_tuple(), graphic.rotation)
                else:
                    return Core.function_crop(xdata, graphic.bounds.as_tuple())
            if isinstance(graphic, Graphics.IntervalGraphic) and xdata and xdata.is_data_1d:
                return Core.function_crop_interval(xdata, graphic.interval)
        return xdata

    @property
    def cropped_element_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__cropped_xdata(self.element_xdata)

    @property
    def cropped_display_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__cropped_xdata(self.display_xdata)

    @property
    def cropped_normalized_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__cropped_xdata(self.normalized_xdata)

    @property
    def cropped_adjusted_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__cropped_xdata(self.adjusted_xdata)

    @property
    def cropped_transformed_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__cropped_xdata(self.transformed_xdata)

    @property
    def cropped_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        data_item = self.data_item
        if data_item:
            xdata = self.xdata
            graphic = self.__graphic
            if xdata and graphic:
                if isinstance(graphic, Graphics.RectangleTypeGraphic):
                    if graphic.rotation:
                        return Core.function_crop_rotated(xdata, graphic.bounds.as_tuple(), graphic.rotation)
                    else:
                        return Core.function_crop(xdata, graphic.bounds.as_tuple())
                if isinstance(graphic, Graphics.IntervalGraphic):
                    return Core.function_crop_interval(xdata, graphic.interval)
            return xdata
        return None

    @property
    def filtered_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        xdata = self.xdata
        if self.__display_item and xdata and xdata.is_data_2d:
            display_xdata = self.display_xdata
            if display_xdata:
                shape = display_xdata.data_shape
                calibrated_origin = Geometry.FloatPoint(y=self.__display_item.datum_calibrations[0].convert_from_calibrated_value(0.0),
                                                        x=self.__display_item.datum_calibrations[1].convert_from_calibrated_value(0.0))
                if xdata.is_data_complex_type:
                    return Core.function_fourier_mask(xdata, DataAndMetadata.DataAndMetadata.from_data(create_mask_data(self.__display_item.graphics, shape, calibrated_origin)))
                else:
                    return DataAndMetadata.DataAndMetadata.from_data(create_mask_data(self.__display_item.graphics, shape, calibrated_origin)) * display_xdata
        return xdata

    @property
    def filter_xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        xdata = self.xdata
        if self.__display_item and xdata and xdata.is_data_2d:
            display_xdata = self.display_xdata
            if display_xdata:
                shape = display_xdata.data_shape
                calibrated_origin = Geometry.FloatPoint(y=self.__display_item.datum_calibrations[0].convert_from_calibrated_value(0.0),
                                                        x=self.__display_item.datum_calibrations[1].convert_from_calibrated_value(0.0))
                return DataAndMetadata.DataAndMetadata.from_data(create_mask_data(self.__display_item.graphics, shape, calibrated_origin))
        return None


class MonitoredDataSource(DataSource):
    def __init__(self, display_data_channel: DisplayItem.DisplayDataChannel, graphic: typing.Optional[Graphics.Graphic], changed_event: Event.Event) -> None:
        super().__init__(display_data_channel, graphic)
        self.__display_item = typing.cast("DisplayItem.DisplayItem", display_data_channel.container)
        self.__graphic = graphic
        self.__changed_event = changed_event  # not public since it is passed in
        self.__data_item = display_data_channel.data_item
        # display_data_channel = self.__display_item.get_display_data_channel_for_data_item(self.__data_item) if self.__display_item else None
        # self.__data_item_changed_event_listener = None
        self.__data_item_changed_event_listener = self.__data_item.data_item_changed_event.listen(self.__changed_event.fire) if self.__data_item else None
        self.__display_values_event_listener = display_data_channel.display_data_will_change_event.listen(self.__changed_event.fire)  # type: ignore  # mypy bug?
        self.__property_changed_listener: typing.Optional[Event.EventListener] = None

        def property_changed(key: str) -> None:
            self.__changed_event.fire()

        if self.__graphic:
            self.__property_changed_listener = self.__graphic.property_changed_event.listen(property_changed)

        # when a graphic changes, if it's used in the mask or fourier_mask role, send out the changed event.
        def filter_property_changed(graphic: Graphics.Graphic, key: str) -> None:
            if key == "role" or graphic.used_role in ("mask", "fourier_mask"):
                self.__changed_event.fire()

        self.__graphic_property_changed_listeners: typing.List[typing.Optional[Event.EventListener]] = list()

        # when a new graphic is inserted, track it
        def graphic_inserted(key: str, graphic: Graphics.Graphic, before_index: int) -> None:
            if key == "graphics":
                property_changed_listener = None
                if isinstance(graphic, (Graphics.PointTypeGraphic, Graphics.LineTypeGraphic, Graphics.RectangleTypeGraphic, Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
                    property_changed_listener = graphic.property_changed_event.listen(functools.partial(filter_property_changed, graphic))
                    self.__changed_event.fire()
                self.__graphic_property_changed_listeners.insert(before_index, property_changed_listener)

        # when a graphic is removed, untrack it
        def graphic_removed(key: str, graphic: Graphics.Graphic, index: int) -> None:
            if key == "graphics":
                property_changed_listener = self.__graphic_property_changed_listeners.pop(index)
                if property_changed_listener:
                    property_changed_listener.close()
                    self.__changed_event.fire()

        self.__graphic_inserted_event_listener = self.__display_item.item_inserted_event.listen(graphic_inserted) if self.__display_item else None
        self.__graphic_removed_event_listener = self.__display_item.item_removed_event.listen(graphic_removed) if self.__display_item else None

        # set up initial tracking
        for graphic in self.__display_item.graphics if self.__display_item else list():
            property_changed_listener = None
            if isinstance(graphic, (Graphics.PointTypeGraphic, Graphics.LineTypeGraphic, Graphics.RectangleTypeGraphic, Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)):
                property_changed_listener = graphic.property_changed_event.listen(functools.partial(filter_property_changed, graphic))
            self.__graphic_property_changed_listeners.append(property_changed_listener)

    def close(self) -> None:
        # shut down the trackers
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
        self.__display_item = None
        self.__graphic = typing.cast(typing.Any, None)
        self.__changed_event = typing.cast(typing.Any, None)
