from __future__ import annotations

# standard libraries
import abc
import contextlib
import copy
import datetime
import gettext
import operator
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
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import ApplicationData
from nion.swift.model import DynamicString
from nion.swift.model import Metadata
from nion.swift.model import Persistence
from nion.swift.model import Utility
from nion.utils import DateTime
from nion.utils import Event
from nion.utils import Stream
from nion.utils import ReferenceCounting

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
        self.define_property("created", DateTime.utcnow(), hidden=True, converter=DatetimeToStringConverter(), changed=self.__description_property_changed)
        data_shape = data.shape if data is not None else None
        data_dtype = data.dtype if data is not None else None
        dimensional_shape = Image.dimensional_shape_from_shape_and_dtype(data_shape, data_dtype)
        collection_dimension_count = (2 if len(dimensional_shape) == 3 else 0) if dimensional_shape is not None else None
        datum_dimension_count = len(dimensional_shape) - collection_dimension_count if dimensional_shape is not None and collection_dimension_count is not None else None
        self.define_property("data_shape", data_shape, hidden=True, recordable=False, is_equal_fn=operator.eq, changed=self.__property_changed)
        self.define_property("data_dtype", data_dtype, hidden=True, recordable=False, converter=DtypeToStringConverter(), changed=self.__property_changed, is_equal_fn=operator.eq)
        self.define_property("is_sequence", False, hidden=True, recordable=False, changed=self.__data_description_changed)
        self.define_property("collection_dimension_count", collection_dimension_count, hidden=True, recordable=False, changed=self.__data_description_changed, value_type=int)
        self.define_property("datum_dimension_count", datum_dimension_count, hidden=True, recordable=False, changed=self.__data_description_changed, value_type=int)
        self.define_property("intensity_calibration", Calibration.Calibration(), hidden=True, make=Calibration.Calibration, changed=self.__metadata_property_changed, is_equal_fn=operator.eq)
        self.define_property("dimensional_calibrations", CalibrationList(), hidden=True, make=CalibrationList, changed=self.__dimensional_calibrations_changed, is_equal_fn=operator.eq)
        self.define_property("data_modified", hidden=True, recordable=False, converter=DatetimeToStringConverter(), changed=self.__metadata_property_changed, value_type=datetime.datetime)
        self.define_property("timezone", Utility.get_local_timezone(), hidden=True, changed=self.__timezone_property_changed, recordable=False, value_type=str)
        self.define_property("timezone_offset", Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes()), hidden=True, changed=self.__timezone_property_changed, recordable=False, value_type=str)
        self.define_property("metadata", dict(), hidden=True, changed=self.__metadata_property_changed, is_equal_fn=Utility.deep_compare_items)
        self.define_property("title", str(), changed=self.__property_changed, hidden=True)
        self.define_property("dynamic_title", hidden=True)
        self.define_property("dynamic_title_enabled", True, changed=self.__property_changed, hidden=True)
        self.define_property("caption", changed=self.__property_changed, hidden=True, value_type=str)
        self.define_property("description", changed=self.__property_changed, hidden=True, value_type=str)
        self.define_property("source_specifier", changed=self.__source_specifier_changed, key="source_uuid", hidden=True)
        self.define_property("session_id", validate=self.__validate_session_id, changed=self.__property_changed, hidden=True, value_type=str)
        self.define_property("session", dict(), changed=self.__property_changed, hidden=True)
        self.define_property("category", "persistent", changed=self.__property_changed, hidden=True, value_type=str)
        self.__data: typing.Optional[_ImageDataType] = None
        self.__data_metadata: typing.Optional[DataAndMetadata.DataMetadata] = None
        self.__data_and_metadata_unloadable = False
        self.__data_and_metadata_first_update_after_reserve = False
        self.__data_and_metadata_lock = threading.RLock()
        self.__intensity_calibration: typing.Optional[Calibration.Calibration] = None
        self.__dimensional_calibrations: typing.List[Calibration.Calibration] = list()
        self.__metadata: typing.Dict[str, typing.Any] = dict()
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
        self.__display_data_channel_refs = set[weakref.ReferenceType["DisplayItem.DisplayDataChannel"]]()
        if data is not None:
            data_and_metadata = DataAndMetadata.DataAndMetadata.from_data(data, timezone=self.timezone, timezone_offset=self.timezone_offset)
            self.increment_data_ref_count()
            try:
                self.__set_data_and_metadata_direct(data_and_metadata)
            finally:
                self.decrement_data_ref_count()
        self.__dynamic_title: typing.Optional[DynamicString.DynamicString] = None
        self.__dynamic_title_persistence_action: typing.Optional[Stream.ValueStreamAction[Persistence.PersistentDictType]] = None
        self.__specified_title_stream = Stream.ValueStream[str]()
        self.__source_title_stream = Stream.FollowStream[str]()
        self.__computation_title_stream = Stream.ValueStream[str]()
        self.__dynamic_title_stream = Stream.FollowStream[str]()
        self.__dynamic_title_enabled_stream = Stream.ValueStream[bool](True)

        def combine_display_title(
                specified_title: typing.Optional[str],
                source_title: typing.Optional[str],
                computation_title: typing.Optional[str],
                dynamic_title: typing.Optional[str],
                dynamic_title_enabled: typing.Optional[bool]
        ) -> str:
            if dynamic_title_enabled:
                if dynamic_title:
                    return dynamic_title
            if dynamic_title_enabled or not specified_title:
                if source_title and computation_title:
                    return f"{source_title} ({computation_title})"
            if specified_title:
                return specified_title
            return UNTITLED_STR

        self.__title_stream = Stream.CombineLatestStream([self.__specified_title_stream, self.__source_title_stream, self.__computation_title_stream, self.__dynamic_title_stream, self.__dynamic_title_enabled_stream], combine_display_title)

        def update_dynamic_title(data_item: DataItem, dynamic_title_str: typing.Optional[str]) -> None:
            if not data_item._is_reading:
                data_item._set_persistent_property_value("title", dynamic_title_str)

        self.__title_stream_action = Stream.ValueStreamAction(self.__title_stream, ReferenceCounting.weak_partial(update_dynamic_title, self))

        def combine_placeholder_title(
                source_title: typing.Optional[str],
                computation_title: typing.Optional[str],
                dynamic_title: typing.Optional[str],
        ) -> str:
            if dynamic_title:
                return dynamic_title
            if source_title and computation_title:
                return f"{source_title} ({computation_title})"
            return str()

        self.__placeholder_title_stream = Stream.CombineLatestStream([self.__source_title_stream, self.__computation_title_stream, self.__dynamic_title_stream], combine_placeholder_title)


    def close(self) -> None:
        self.__title_stream = typing.cast(typing.Any, None)
        self.__dynamic_title = None
        self.__dynamic_title_persistence_action = None
        self.__specified_title_stream = typing.cast(typing.Any, None)
        self.__source_title_stream = typing.cast(typing.Any, None)
        self.__computation_title_stream = typing.cast(typing.Any, None)
        self.__dynamic_title_stream = typing.cast(typing.Any, None)
        self.__dynamic_title_enabled_stream = typing.cast(typing.Any, None)
        self.__title_stream = typing.cast(typing.Any, None)
        self.__title_stream_action = typing.cast(typing.Any, None)
        self.__placeholder_title_stream = typing.cast(typing.Any, None)
        self.__data = None
        super().close()

    def __str__(self) -> str:
        return "{0} {1} ({2}, {3})".format(self.__repr__(), (self.title if self.title else _("Untitled")), str(self.uuid), self.date_for_sorting_local_as_string)

    def __copy__(self) -> DataItem:
        return copy.deepcopy(self)

    def __deepcopy__(self, memo: typing.Dict[typing.Any, typing.Any]) -> DataItem:
        data_item_copy = self.__class__()
        try:
            # data format (temporary until moved to buffered data source)
            data_item_copy.large_format = self.large_format
            # metadata
            data_item_copy.created = self.created
            data_item_copy.timezone = self.timezone
            data_item_copy.timezone_offset = self.timezone_offset
            data_item_copy.metadata = self.metadata
            data_item_copy.title = self.title
            data_item_copy.dynamic_title_enabled = self.dynamic_title_enabled
            data_item_copy.caption = self.caption
            data_item_copy.description = self.description
            data_item_copy.session_id = self.session_id
            data_item_copy.session_data = copy.deepcopy(self.session_data)
            data_item_copy.category = self.category
            # data and metadata
            data_item_copy.set_data_and_metadata(copy.deepcopy(self.data_and_metadata), self.data_modified)
            # copy this last and avoid making an extra unnecessary copy
            data_item_copy.__set_dynamic_title(copy.deepcopy(self.__dynamic_title) if self.__dynamic_title else None)
            memo[id(self)] = data_item_copy
            return data_item_copy
        except Exception:
            data_item_copy.close()
            raise

    def snapshot(self) -> DataItem:
        """Return a new library item which is a copy of this one with any dynamic behavior made static."""
        data_item_snapshot = copy.deepcopy(self)
        data_item_snapshot.category = "persistent"
        return data_item_snapshot

    def clone(self) -> DataItem:
        data_item = self.__class__()
        data_item.uuid = self.uuid
        return data_item

    @property
    def created(self) -> datetime.datetime:
        return typing.cast(datetime.datetime, self._get_persistent_property_value("created"))

    @created.setter
    def created(self, value: datetime.datetime) -> None:
        self._set_persistent_property_value("created", value)

    @ property
    def dynamic_title_enabled(self) -> bool:
        return typing.cast(bool, self._get_persistent_property_value("dynamic_title_enabled"))

    @dynamic_title_enabled.setter
    def dynamic_title_enabled(self, value: bool) -> None:
        self._set_persistent_property_value("dynamic_title_enabled", value)
        if self.dynamic_title_enabled:
            self.__set_dynamic_title(self.__dynamic_title)

    @property
    def title(self) -> str:
        return self.__title_stream.value or str()

    @title.setter
    def title(self, value: typing.Optional[str]) -> None:
        if value:
            self._set_persistent_property_value("dynamic_title_enabled", False)
            self._set_persistent_property_value("title", value)
        else:
            self._set_persistent_property_value("dynamic_title_enabled", True)

    @property
    def title_stream(self) -> Stream.AbstractStream[str]:
        return self.__title_stream

    @property
    def placeholder_title_stream(self) -> Stream.AbstractStream[str]:
        return self.__placeholder_title_stream

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

    def add_display_data_channel(self, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        """Add a display data channel referencing this data item.

        This is used as an optimization to be able to easily access the display data channels for a data item.
        Think of it as an "index" in the database sense.
        """
        self.__display_data_channel_refs.add(weakref.ref(display_data_channel))
        self.notify_add_item("display_data_channels", display_data_channel)

    def remove_display_data_channel(self, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        """Remove a display data channel referencing this data item."""
        self.__display_data_channel_refs.remove(weakref.ref(display_data_channel))
        self.notify_discard_item("display_data_channels", display_data_channel)

    @property
    def display_data_channels(self) -> typing.Set[DisplayItem.DisplayDataChannel]:
        """Return the list of display data channels referencing this data item."""
        display_data_channels = set["DisplayItem.DisplayDataChannel"]()
        for display_data_channel_ref in self.__display_data_channel_refs:
            display_data_channel = display_data_channel_ref()
            assert display_data_channel  # should never be None
            display_data_channels.add(display_data_channel)
        return display_data_channels

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
            self.__data_and_metadata_unloadable = True
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
        if self.__data is not None:
            self.write_external_data("data", self.__data)

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
        # load data to prevent paging in and out.
        self.increment_data_ref_count()

    def _transaction_state_exited(self) -> None:
        self.__in_transaction_state = False
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

    def source_data_items_changed(self, source_data_items: typing.List[DataItem]) -> None:
        if len(source_data_items) == 1:
            self.__source_title_stream.stream = source_data_items[0].title_stream
        else:
            self.__source_title_stream.stream = None

    def computation_title_changed(self, computation_title: typing.Optional[str]) -> None:
        self.__computation_title_stream.value = computation_title

    def persistent_object_context_changed(self) -> None:
        # handle case where persistent object context is set on an item that is already under transaction.
        # this can occur during acquisition. any other cases?
        super().persistent_object_context_changed()

        if self.__in_transaction_state:
            self.__enter_write_delay_state()
        else:
            self.__data_and_metadata_unloadable = self.persistent_object_context is not None and not self.is_write_delayed

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
                    timestamp = self.created or DateTime.utcnow()
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
                self.__data_metadata = DataAndMetadata.DataMetadata(data_shape_and_dtype,
                                                                    intensity_calibration,
                                                                    dimensional_calibrations, metadata,
                                                                    timestamp,
                                                                    data_descriptor=data_descriptor,
                                                                    timezone=self.timezone,
                                                                    timezone_offset=self.timezone_offset)
                with self.__data_ref_count_mutex:
                    if self.__data_ref_count:
                        self.__load_data()
                self.__data_and_metadata_unloadable = self.persistent_object_context is not None
            else:
                metadata = self._get_persistent_property_value("metadata")
                self.__metadata = copy.deepcopy(metadata) if metadata else dict()
            self.__pending_write = False
            if self.created is None:  # invalid timestamp -- set property to now but don't trigger change
                self._get_persistent_property("created").value = DateTime.utcnow()
            self.__content_changed = False
        dynamic_title: typing.Optional[DynamicString.DynamicString] = None
        dynamic_title_d = self._get_persistent_property("dynamic_title").value
        if dynamic_title_d is not None:
            dynamic_title = DynamicString.make_dynamic_string(dynamic_title_d)
        if dynamic_title:
            self.__set_dynamic_title(dynamic_title)
        self.__pending_write = False

    def __set_dynamic_title(self, dynamic_title: typing.Optional[DynamicString.DynamicString]) -> None:
        self.__dynamic_title = dynamic_title
        if self.__dynamic_title:
            self.__dynamic_title.connect_item(self)
            self.__dynamic_title_persistence_action = Stream.ValueStreamAction(self.__dynamic_title.persistence_stream, ReferenceCounting.weak_partial(DataItem.__write_dynamic_title, self))
            self.__dynamic_title_stream.stream = self.__dynamic_title.string_stream
            self.__write_dynamic_title(self.__dynamic_title.persistence_stream.value)
        else:
            self.__dynamic_title_persistence_action = None
            self.__dynamic_title_stream.stream = None

    def __write_dynamic_title(self, dynamic_title_d: typing.Optional[Persistence.PersistentDictType]) -> None:
        if not self._is_reading:
            self._set_persistent_property_value("dynamic_title", dynamic_title_d)

    @property
    def dynamic_title(self) -> typing.Optional[DynamicString.DynamicString]:
        return self.__dynamic_title

    @dynamic_title.setter
    def dynamic_title(self, value: DynamicString.DynamicString) -> None:
        self.__set_dynamic_title(value)
        self._set_persistent_property_value("dynamic_title_enabled", True)

    def set_dynamic_title_by_id(self, dynamic_title_id: str) -> None:
        dynamic_string = DynamicString.make_dynamic_string({"type": dynamic_title_id})
        if dynamic_string:
            self.dynamic_title = dynamic_string

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
        self.notify_property_changed("date_for_sorting_local")
        self.__notify_description_changed()

    def __notify_description_changed(self) -> None:
        self._notify_data_item_content_changed()
        self._description_changed()

    def _description_changed(self) -> None:
        self.description_changed_event.fire()

    def __data_description_changed(self, name: str, value: int) -> None:
        self.__change_changed = True
        self.__property_changed(name, value)

    def __dimensional_calibrations_changed(self, name: str, value: typing.Any) -> None:
        self.__change_changed = True
        self.__property_changed(name, list(value.list))  # don't send out the CalibrationList object

    def __metadata_property_changed(self, name: str, value: typing.Any) -> None:
        self.__change_changed = True
        self.__property_changed(name, value)
        self.notify_property_changed("date_for_sorting_local")

    def __property_changed(self, name: str, value: typing.Any) -> None:
        if name == "title":
            self.__specified_title_stream.value = value
        if name == "dynamic_title_enabled":
            self.__dynamic_title_enabled_stream.value = value
        self.notify_property_changed(name)
        if name == "session":
            self.notify_property_changed("session_metadata")
        if name in ("title", "caption", "description"):
            self.__notify_description_changed()

    def __timezone_property_changed(self, name: str, value: typing.Optional[str]) -> None:
        timezone = self.timezone
        if self.__data_metadata and timezone is not None:
            self.__data_metadata._set_timezone(timezone)
            self.__data_metadata._set_timezone_offset(self.timezone_offset)
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
    def date_for_sorting_local(self) -> datetime.datetime:
        date_utc = self.date_for_sorting
        tz_minutes = Utility.local_utcoffset_minutes(date_utc)
        return date_utc + datetime.timedelta(minutes=tz_minutes)

    @property
    def date_for_sorting_local_as_string(self) -> str:
        date_local = self.date_for_sorting_local
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
                    self.__write_delay_data_changed = True
                if data_changed or changed:
                    self._notify_data_item_content_changed()
                    self.data_item_changed_event.fire()
        self.did_change_event.fire()

    def increment_data_ref_count(self) -> int:
        with self.__data_ref_count_mutex:
            initial_count = self.__data_ref_count
            self.__data_ref_count += 1
            if not initial_count or self.__data is None:
                self.__load_data()
        return initial_count + 1

    def decrement_data_ref_count(self) -> int:
        with self.__data_ref_count_mutex:
            assert self.__data_ref_count > 0
            self.__data_ref_count -= 1
            final_count = self.__data_ref_count
            if not final_count:
                self.__unload_data()
        return final_count

    @property
    def _data_ref_count(self) -> int:
        return self.__data_ref_count

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
                    self.set_xdata(pending_xdata, data_modified=pending_xdata.timestamp)
                for partial_xdata, partial_src_slice, partial_dst_slice, partial_metadata in pending_queue:
                    # note: data_modified is only used in case that the data has not been updated yet. subsequent
                    # updates use the timestamp of the existing data.
                    self.set_data_and_metadata_partial(partial_metadata, partial_xdata, partial_src_slice, partial_dst_slice, update_metadata=True, data_modified=partial_metadata.timestamp)

    _data_count = 0

    @property
    def xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        self.increment_data_ref_count()
        try:
            if self.__data_metadata and self.__data is not None:
                data_and_metadata = DataAndMetadata.DataAndMetadata(
                    self.__data,
                    self.__data_metadata.data_shape_and_dtype,
                    self.__data_metadata.intensity_calibration,
                    self.__data_metadata.dimensional_calibrations,
                    self.__data_metadata.metadata,
                    self.__data_metadata.timestamp,
                    self.__data_metadata.data_descriptor,
                    self.__data_metadata.timezone,
                    self.__data_metadata.timezone_offset
                )

                DataItem._data_count += 1

                def finalize() -> None:
                    DataItem._data_count -= 1

                weakref.finalize(data_and_metadata, finalize)

                return data_and_metadata

            return None
        finally:
            self.decrement_data_ref_count()

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

    def __validate_session_id(self, value: typing.Any) -> typing.Optional[str]:
        if value is not None:
            assert isinstance(value, str)
            assert (value[8] == '-' and all(c.isdigit() for c in value[:8] + value[9:]))
            return value
        return value  # use two returns to satisfy mypy

    @property
    def data(self) -> typing.Optional[_ImageDataType]:
        return self.__get_data()

    def set_data(self, data: _ImageDataType, data_modified: typing.Optional[datetime.datetime] = None) -> None:
        timezone = Utility.get_local_timezone()
        timezone_offset = Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes())
        self.set_xdata(DataAndMetadata.new_data_and_metadata(data, timestamp=data_modified, timezone=timezone, timezone_offset=timezone_offset))

    def set_xdata(self, xdata: typing.Optional[DataAndMetadata.DataAndMetadata], data_modified: typing.Optional[datetime.datetime] = None) -> None:
        with self.data_source_changes():
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

    # grab a data reference as a context manager. the object
    # returned defines data and data properties. reading data
    # should use the data property. writing data (if allowed) should
    # assign to the data property.
    def data_ref(self) -> contextlib.AbstractContextManager[DataItem.DataAccessor]:
        return DataItem.DataAccessor(self, self.__get_data, self.__set_data)

    def __get_data(self) -> typing.Optional[_ImageDataType]:
        xdata = self.xdata
        return xdata.data if xdata else None

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
        return self.__data_metadata.intensity_calibration if self.__data_metadata else self.__intensity_calibration

    @intensity_calibration.setter
    def intensity_calibration(self, intensity_calibration: Calibration.Calibration) -> None:
        with self.data_source_changes():
            if self.__data_metadata:  # handle case of missing data and metadata but doing recording
                self.__data_metadata._set_intensity_calibration(intensity_calibration)
            self.__intensity_calibration = copy.deepcopy(intensity_calibration)  # backup in case of no data and metadata
            self._set_persistent_property_value("intensity_calibration", intensity_calibration)

    def set_intensity_calibration(self, intensity_calibration: Calibration.Calibration) -> None:
        self.intensity_calibration = intensity_calibration

    @property
    def dimensional_calibrations(self) -> DataAndMetadata.CalibrationListType:
        data_metadata = self.__data_metadata
        return copy.deepcopy(data_metadata.dimensional_calibrations) if data_metadata else self.__dimensional_calibrations

    @dimensional_calibrations.setter
    def dimensional_calibrations(self, dimensional_calibrations: DataAndMetadata.CalibrationListType) -> None:
        with self.data_source_changes():
            if self.__data_metadata:  # handle case of missing data and metadata but doing recording
                self.__data_metadata._set_dimensional_calibrations(dimensional_calibrations)
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
        return self.__data_metadata.timestamp if self.__data_metadata else None

    @data_modified.setter
    def data_modified(self, value: datetime.datetime) -> None:
        if self.__data_metadata:
            self.__data_metadata._set_timestamp(value)
            self._set_persistent_property_value("data_modified", value)
            self.__metadata_property_changed("data_modified", value)

    @property
    def timezone(self) -> typing.Optional[str]:
        data_metadata = self.__data_metadata
        return data_metadata.timezone if data_metadata else Utility.get_local_timezone()

    @timezone.setter
    def timezone(self, value: str) -> None:
        if self.__data_metadata:
            self.__data_metadata._set_timezone(value)
            self._set_persistent_property_value("timezone", value)
            self.__timezone_property_changed("timezone", value)

    @property
    def timezone_offset(self) -> typing.Optional[str]:
        data_metadata = self.__data_metadata
        return data_metadata.timezone_offset if data_metadata else Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes())

    @timezone_offset.setter
    def timezone_offset(self, value: str) -> None:
        if self.__data_metadata:
            self.__data_metadata._set_timezone_offset(value)
            self._set_persistent_property_value("timezone_offset", value)
            self.__timezone_property_changed("timezone_offset", value)

    @property
    def metadata(self) -> DataAndMetadata.MetadataType:
        data_metadata = self.__data_metadata
        return dict(data_metadata.metadata) if data_metadata else copy.deepcopy(self.__metadata)

    @metadata.setter
    def metadata(self, metadata: DataAndMetadata.MetadataType) -> None:
        with self.data_source_changes():
            assert isinstance(metadata, dict)
            if self.__data_metadata:
                self.__data_metadata._set_metadata(metadata)
            self.__metadata = copy.deepcopy(metadata) if metadata else dict()
            self._set_persistent_property_value("metadata", self.__metadata)

    @property
    def has_data(self) -> bool:
        return self.__data_metadata is not None

    # used for testing
    @property
    def is_data_loaded(self) -> bool:
        return self.__data is not None

    @property
    def data_metadata(self) -> typing.Optional[DataAndMetadata.DataMetadata]:
        return self.__data_metadata

    @property
    def data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.xdata

    def __load_data(self) -> None:
        if self.persistent_object_context and self.__data is None and self.__data_metadata:
            self.__data = typing.cast(typing.Optional[_ImageDataType], self.read_external_data("data"))

    def __unload_data(self) -> None:
        if self.__data_and_metadata_unloadable:
            self.__data = None

    @property
    def is_unloadable(self) -> bool:
        return self.__data_and_metadata_unloadable

    def _force_unload(self) -> None:
        self.__data = None

    def __set_data_metadata_direct(self, data_metadata: DataAndMetadata.DataMetadata,
                                   data_modified: typing.Optional[datetime.datetime] = None) -> None:
        assert self.__data_ref_count > 0
        # set the data modified directly
        data_modified = data_modified if data_modified else DateTime.utcnow()
        data_metadata._set_timestamp(data_modified)
        # save the data_metadata. this must go before setting the persistent properties below because
        # of how the recorder works (grabs the attribute from data item).
        self.__data_metadata = copy.deepcopy(data_metadata)
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
        self.__metadata = dict(data_metadata.metadata)
        self._set_persistent_property_value("metadata", self.__metadata)
        self._set_persistent_property_value("data_modified", data_modified)

    def __set_data_and_metadata_direct(self, data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata],
                                       data_modified: typing.Optional[datetime.datetime] = None) -> None:
        assert self.__data_ref_count > 0
        self.__data = data_and_metadata.data if data_and_metadata else None
        if data_and_metadata:
            self.__set_data_metadata_direct(data_and_metadata.data_metadata, data_modified)
        self.__change_changed = True
        self.__change_data_changed = True
        if self._session_manager:
            session_id = self._session_manager.current_session_id
            self.session_id = session_id

    def set_data_and_metadata(self, data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata],
                              data_modified: typing.Optional[datetime.datetime] = None) -> None:
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
                new_data_and_metadata = DataAndMetadata.DataAndMetadata(data, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp, data_descriptor, timezone, timezone_offset)
            else:
                new_data_and_metadata = None
            self.__set_data_and_metadata_direct(new_data_and_metadata, data_modified)
            if self.__data is not None:
                if self.persistent_object_context and not self.is_write_delayed:
                    self.write_external_data("data", self.__data)
                    self.__data_and_metadata_unloadable = True
        finally:
            self.decrement_data_ref_count()

    def reserve_data(self, *, data_shape: DataAndMetadata.ShapeType, data_dtype: numpy.typing.DTypeLike, data_descriptor: DataAndMetadata.DataDescriptor, data_modified: typing.Optional[datetime.datetime] = None) -> None:
        """Reserves the underlying data without necessarily allocating memory. Useful for memory mapped files.
        """
        self.increment_data_ref_count()
        try:
            if self.persistent_object_context:
                self.reserve_external_data("data", data_shape, data_dtype)
                data_shape_and_dtype = data_shape, data_dtype
                timezone = Utility.get_local_timezone()
                timezone_offset = Utility.TimezoneMinutesToStringConverter().convert(Utility.local_utcoffset_minutes())
                data_metadata = DataAndMetadata.DataMetadata(data_shape_and_dtype=data_shape_and_dtype, data_descriptor=data_descriptor, metadata=self.metadata, timezone=timezone, timezone_offset=timezone_offset)
                self.__set_data_metadata_direct(data_metadata, data_modified)
                self.__load_data()
                self.__data_and_metadata_unloadable = True
                self.__data_and_metadata_first_update_after_reserve = True
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
                if self.__data is None:
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
                    new_data_and_metadata = DataAndMetadata.DataAndMetadata(data, data_shape_and_dtype,
                                                                            intensity_calibration,
                                                                            dimensional_calibrations, metadata,
                                                                            timestamp, data_descriptor, timezone,
                                                                            timezone_offset)
                    self.__set_data_and_metadata_direct(new_data_and_metadata, data_modified)
                if self.__data is not None:
                    date_modified = data_metadata.timestamp if self.__data_and_metadata_first_update_after_reserve else self.__data_metadata.timestamp if self.__data_metadata else None
                    self.__data_and_metadata_first_update_after_reserve = False
                    if update_metadata or date_modified:
                        self.__set_data_metadata_direct(data_metadata, date_modified)
                    assert self.data_shape == data_metadata.data_shape
                    assert self.data_dtype == data_metadata.data_dtype
                    assert self.data_dtype == data_and_metadata.data_dtype, f"{self.data_dtype=} == {data_and_metadata.data_dtype=}"
                    self.__data[tuple(dst)] = data_and_metadata._data_ex[tuple(src)]
                    # mark changes and update session
                    self.__change_changed = True
                    self.__change_data_changed = True
                    if self._session_manager:
                        session_id = self._session_manager.current_session_id
                        self.session_id = session_id
                    # set data_shape as a way to update 'modified' property
                    self._set_persistent_property_value("data_shape", self.data_shape)
                    if self.persistent_object_context and not self.is_write_delayed:
                        self.write_external_data("data", self.__data)
                        self.__data_and_metadata_unloadable = True
            finally:
                self.decrement_data_ref_count()

    @property
    def data_shape(self) -> typing.Optional[DataAndMetadata.ShapeType]:
        return self.__data_metadata.data_shape if self.__data_metadata else None

    @property
    def data_dtype(self) -> typing.Optional[numpy.typing.DTypeLike]:
        return self.__data_metadata.data_dtype if self.__data_metadata else None

    @property
    def dimensional_shape(self) -> DataAndMetadata.ShapeType:
        return self.__data_metadata.dimensional_shape if self.__data_metadata else tuple()

    @property
    def datum_dimension_shape(self) -> DataAndMetadata.ShapeType:
        return self.__data_metadata.datum_dimension_shape if self.__data_metadata else tuple()

    @property
    def datum_dimension_count(self) -> int:
        return self.__data_metadata.datum_dimension_count if self.__data_metadata else 0

    @property
    def collection_dimension_count(self) -> int:
        return self.__data_metadata.collection_dimension_count if self.__data_metadata else 0

    @property
    def is_collection(self) -> bool:
        return self.collection_dimension_count > 0 if self.collection_dimension_count is not None else False

    @property
    def is_sequence(self) -> bool:
        return self.__data_metadata.is_sequence if self.__data_metadata else False

    @property
    def is_data_1d(self) -> bool:
        return self.__data_metadata is not None and self.__data_metadata.is_data_1d

    @property
    def is_data_2d(self) -> bool:
        return self.__data_metadata is not None and self.__data_metadata.is_data_2d

    @property
    def is_data_3d(self) -> bool:
        return self.__data_metadata is not None and self.__data_metadata.is_data_3d

    @property
    def is_data_4d(self) -> bool:
        return self.__data_metadata is not None and self.__data_metadata.is_data_4d

    @property
    def is_data_rgb(self) -> bool:
        return self.__data_metadata is not None and self.__data_metadata.is_data_rgb

    @property
    def is_data_rgba(self) -> bool:
        return self.__data_metadata is not None and self.__data_metadata.is_data_rgba

    @property
    def is_datum_1d(self) -> bool:
        return self.__data_metadata is not None and self.__data_metadata.is_datum_1d

    @property
    def is_datum_2d(self) -> bool:
        return self.__data_metadata is not None and self.__data_metadata.is_datum_2d

    @property
    def is_data_rgb_type(self) -> bool:
        return self.__data_metadata is not None and self.__data_metadata.is_data_rgb_type

    @property
    def is_data_scalar_type(self) -> bool:
        return self.__data_metadata is not None and self.__data_metadata.is_data_scalar_type

    @property
    def is_data_complex_type(self) -> bool:
        return self.__data_metadata is not None and self.__data_metadata.is_data_complex_type

    @property
    def is_data_bool(self) -> bool:
        return self.__data_metadata is not None and self.__data_metadata.is_data_bool

    def get_data_value(self, pos: DataAndMetadata.ShapeType) -> typing.Any:
        xdata = self.xdata
        return xdata.get_data_value(pos) if xdata else None

    @property
    def size_and_data_format_as_string(self) -> str:
        return self.__data_metadata.size_and_data_format_as_string if self.__data_metadata else _("No Data")

    def has_metadata_value(self, key: str) -> bool:
        return Metadata.has_metadata_value(self, key)

    def get_metadata_value(self, key: str) -> typing.Any:
        return Metadata.get_metadata_value(self, key)

    def set_metadata_value(self, key: str, value: typing.Any) -> None:
        Metadata.set_metadata_value(self, key, value)

    def delete_metadata_value(self, key: str) -> None:
        Metadata.delete_metadata_value(self, key)


def new_data_item(data_and_metadata_in: typing.Optional[DataAndMetadata._DataAndMetadataLike] = None) -> DataItem:
    data_and_metadata = DataAndMetadata.promote_ndarray(data_and_metadata_in) if data_and_metadata_in is not None else None
    data_item = DataItem(large_format=len(data_and_metadata.dimensional_shape) > 2 if data_and_metadata else False)
    data_item.set_xdata(data_and_metadata)
    return data_item

"""
Architectural Decision Records.

ADR 2024-04-27. The data item will separately keep track of whether dynamic title updating is enabled rather than
have it be dependent on the existence of the dynamic string object itself. This allows the user to enable or disable
the dynamic title without having to remember its previous state. This may be important for custom acquisition dynamic
strings or computed data item titling.
"""
