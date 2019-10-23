# standard libraries
import copy
import datetime
import functools
import gettext
import math
import numbers
import numpy
import operator
import threading
import time
import typing
import uuid
import weakref

# local libraries
from nion.data import Calibration
from nion.data import Core
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import Cache
from nion.swift.model import ColorMaps
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.model import Utility
from nion.utils import Event
from nion.utils import Observable
from nion.utils import Persistence


_ = gettext.gettext


class GraphicSelection:
    def __init__(self, indexes=None, anchor_index=None):
        super().__init__()
        self.__changed_event = Event.Event()
        self.__indexes = copy.copy(indexes) if indexes else set()
        self.__anchor_index = anchor_index

    def __copy__(self):
        return type(self)(self.__indexes, self.__anchor_index)

    def __eq__(self, other):
        return other is not None and self.indexes == other.indexes and self.anchor_index == other.anchor_index

    def __ne__(self, other):
        return other is None or self.indexes != other.indexes or self.anchor_index != other.anchor_index

    @property
    def changed_event(self):
        return self.__changed_event

    @property
    def current_index(self):
        if len(self.__indexes) == 1:
            for index in self.__indexes:
                return index
        return None

    @property
    def anchor_index(self):
        return self.__anchor_index

    @property
    def has_selection(self):
        return len(self.__indexes) > 0

    def contains(self, index):
        return index in self.__indexes

    @property
    def indexes(self):
        return self.__indexes

    def clear(self):
        old_index = self.__indexes.copy()
        self.__indexes = set()
        self.__anchor_index = None
        if old_index != self.__indexes:
            self.__changed_event.fire()

    def __update_anchor_index(self):
        for index in self.__indexes:
            if self.__anchor_index is None or index < self.__anchor_index:
                self.__anchor_index = index

    def add(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes.add(index)
        if len(old_index) == 0:
            self.__anchor_index = index
        if old_index != self.__indexes:
            self.__changed_event.fire()

    def remove(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes.remove(index)
        if not self.__anchor_index in self.__indexes:
            self.__update_anchor_index()
        if old_index != self.__indexes:
            self.__changed_event.fire()

    def add_range(self, range):
        for index in range:
            self.add(index)

    def set(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes = set()
        self.__indexes.add(index)
        self.__anchor_index = index
        if old_index != self.__indexes:
            self.__changed_event.fire()

    def toggle(self, index):
        assert isinstance(index, numbers.Integral)
        if index in self.__indexes:
            self.remove(index)
        else:
            self.add(index)

    def insert_index(self, new_index):
        new_indexes = set()
        for index in self.__indexes:
            if index < new_index:
                new_indexes.add(index)
            else:
                new_indexes.add(index + 1)
        if self.__anchor_index is not None:
            if new_index <= self.__anchor_index:
                self.__anchor_index += 1
        if self.__indexes != new_indexes:
            self.__indexes = new_indexes
            self.changed_event.fire()

    def remove_index(self, remove_index):
        new_indexes = set()
        for index in self.__indexes:
            if index != remove_index:
                if index > remove_index:
                    new_indexes.add(index - 1)
                else:
                    new_indexes.add(index)
        if self.__anchor_index is not None:
            if remove_index == self.__anchor_index:
                self.__update_anchor_index()
            elif remove_index < self.__anchor_index:
                self.__anchor_index -= 1
        if self.__indexes != new_indexes:
            self.__indexes = new_indexes
            self.changed_event.fire()


def calculate_display_range(display_limits, data_range, data_sample, xdata, complex_display_type):
    if display_limits is not None:
        display_limit_low = display_limits[0] if display_limits[0] is not None else data_range[0]
        display_limit_high = display_limits[1] if display_limits[1] is not None else data_range[1]
        return display_limit_low, display_limit_high
    if xdata and xdata.is_data_complex_type and complex_display_type is None:  # log absolute
        if data_sample is not None:
            fraction = 0.05
            display_limit_low = data_sample[int(data_sample.shape[0] * fraction)]
            display_limit_high = data_range[1]
            return display_limit_low, display_limit_high
    return data_range


class CalibrationStyle:
    label = None
    calibration_style_id = None
    is_calibrated = False

    def get_dimensional_calibrations(self, dimensional_shape, dimensional_calibrations) -> typing.Sequence[Calibration.Calibration]:
        return list()

    def get_intensity_calibration(self, xdata: DataAndMetadata.DataAndMetadata) -> Calibration.Calibration:
        return xdata.intensity_calibration if self.is_calibrated else Calibration.Calibration()


class CalibrationStyleNative(CalibrationStyle):
    label = _("Calibrated")
    calibration_style_id = "calibrated"
    is_calibrated = True

    def get_dimensional_calibrations(self, dimensional_shape, dimensional_calibrations) -> typing.Sequence[Calibration.Calibration]:
        return dimensional_calibrations


class CalibrationStylePixelsTopLeft(CalibrationStyle):
    label = _("Pixels (Top-Left)")
    calibration_style_id = "pixels-top-left"

    def get_dimensional_calibrations(self, dimensional_shape, dimensional_calibrations) -> typing.Sequence[Calibration.Calibration]:
        return [Calibration.Calibration() for display_dimension in dimensional_shape]


class CalibrationStylePixelsCenter(CalibrationStyle):
    label = _("Pixels (Center)")
    calibration_style_id = "pixels-center"

    def get_dimensional_calibrations(self, dimensional_shape, dimensional_calibrations) -> typing.Sequence[Calibration.Calibration]:
        return [Calibration.Calibration(offset=-display_dimension/2) for display_dimension in dimensional_shape]


class CalibrationStyleFractionalTopLeft(CalibrationStyle):
    label = _("Fractional (Top Left)")
    calibration_style_id = "relative-top-left"

    def get_dimensional_calibrations(self, dimensional_shape, dimensional_calibrations) -> typing.Sequence[Calibration.Calibration]:
        return [Calibration.Calibration(scale=1.0/display_dimension) for display_dimension in dimensional_shape]


class CalibrationStyleFractionalCenter(CalibrationStyle):
    label = _("Fractional (Center)")
    calibration_style_id = "relative-center"

    def get_dimensional_calibrations(self, dimensional_shape, dimensional_calibrations) -> typing.Sequence[Calibration.Calibration]:
        return [Calibration.Calibration(scale=2.0/display_dimension, offset=-1.0) for display_dimension in dimensional_shape]


class DisplayValues:
    """Display data used to render the display."""

    def __init__(self, data_and_metadata, sequence_index, collection_index, slice_center, slice_width, display_limits, complex_display_type, color_map_data):
        self.__lock = threading.RLock()
        self.__data_and_metadata = data_and_metadata
        self.__sequence_index = sequence_index
        self.__collection_index = collection_index
        self.__slice_center = slice_center
        self.__slice_width = slice_width
        self.__display_limits = display_limits
        self.__complex_display_type = complex_display_type
        self.__color_map_data = color_map_data
        self.__display_data_and_metadata_dirty = True
        self.__display_data_and_metadata = None
        self.__data_range_dirty = True
        self.__data_range = None
        self.__data_sample_dirty = True
        self.__data_sample = None
        self.__display_range_dirty = True
        self.__display_range = None
        self.__display_rgba_dirty = True
        self.__display_rgba = None
        self.__display_rgba_timestamp = data_and_metadata.timestamp if data_and_metadata else None
        self.__finalized = False
        self.on_finalize = None

    def finalize(self):
        with self.__lock:
            self.__finalized = True
        if callable(self.on_finalize):
            self.on_finalize(self)

    @property
    def color_map_data(self):
        return self.__color_map_data

    @property
    def data_and_metadata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_and_metadata

    @property
    def display_data_and_metadata(self) -> DataAndMetadata.DataAndMetadata:
        with self.__lock:
            if self.__display_data_and_metadata_dirty:
                self.__display_data_and_metadata_dirty = False
                data_and_metadata = self.__data_and_metadata
                if data_and_metadata is not None:
                    timestamp = data_and_metadata.timestamp
                    data_and_metadata, modified = Core.function_display_data_no_copy(data_and_metadata, self.__sequence_index, self.__collection_index, self.__slice_center, self.__slice_width, self.__complex_display_type)
                    if data_and_metadata:
                        data_and_metadata.data_metadata.timestamp = timestamp
                    self.__display_data_and_metadata = data_and_metadata
            return self.__display_data_and_metadata

    @property
    def data_range(self):
        with self.__lock:
            if self.__data_range_dirty:
                self.__data_range_dirty = False
                display_data_and_metadata = self.display_data_and_metadata
                display_data = display_data_and_metadata.data if display_data_and_metadata else None
                if display_data is not None and display_data.size and self.__data_and_metadata:
                    data_shape = self.__data_and_metadata.data_shape
                    data_dtype = self.__data_and_metadata.data_dtype
                    if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
                        self.__data_range = (0, 255)
                    elif Image.is_shape_and_dtype_complex_type(data_shape, data_dtype):
                        self.__data_range = (numpy.amin(display_data), numpy.amax(display_data))
                    else:
                        self.__data_range = (numpy.amin(display_data), numpy.amax(display_data))
                else:
                    self.__data_range = None
                if self.__data_range is not None:
                    if math.isnan(self.__data_range[0]) or math.isnan(self.__data_range[1]) or math.isinf(self.__data_range[0]) or math.isinf(self.__data_range[1]):
                        self.__data_range = (0.0, 0.0)
                    if numpy.issubdtype(type(self.__data_range[0]), numpy.bool_):
                        self.__data_range = (int(self.__data_range[0]), self.__data_range[1])
                    if numpy.issubdtype(type(self.__data_range[1]), numpy.bool_):
                        self.__data_range = (self.__data_range[0], int(self.__data_range[1]))
            return self.__data_range

    @property
    def display_range(self):
        with self.__lock:
            if self.__display_range_dirty:
                self.__display_range_dirty = False
                self.__display_range = calculate_display_range(self.__display_limits, self.data_range, self.data_sample, self.__data_and_metadata, self.__complex_display_type)
            return self.__display_range

    @property
    def data_sample(self):
        with self.__lock:
            if self.__data_sample_dirty:
                self.__data_sample_dirty = False
                display_data_and_metadata = self.display_data_and_metadata
                display_data = display_data_and_metadata.data if display_data_and_metadata else None
                if display_data is not None and display_data.size and self.__data_and_metadata:
                    data_shape = self.__data_and_metadata.data_shape
                    data_dtype = self.__data_and_metadata.data_dtype
                    if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
                        self.__data_sample = None
                    elif Image.is_shape_and_dtype_complex_type(data_shape, data_dtype):
                        self.__data_sample = numpy.sort(numpy.random.choice(display_data.reshape(numpy.product(display_data.shape, dtype=numpy.uint64)), 200))
                    else:
                        self.__data_sample = None
                else:
                    self.__data_sample = None
            return self.__data_sample

    @property
    def display_rgba(self):
        with self.__lock:
            if self.__display_rgba_dirty:
                self.__display_rgba_dirty = False
                display_data_and_metadata = self.display_data_and_metadata
                if display_data_and_metadata is not None and self.__data_and_metadata is not None:
                    if self.data_range is not None:  # workaround until validating and retrieving data stats is an atomic operation
                        # display_range is just display_limits but calculated if display_limits is None
                        display_range = self.display_range
                        self.__display_rgba = Core.function_display_rgba(display_data_and_metadata, display_range, self.__color_map_data).data
            return self.__display_rgba

    @property
    def display_rgba_timestamp(self):
        return self.__display_rgba_timestamp


class DisplayDataChannel(Observable.Observable, Persistence.PersistentObject):
    def __init__(self, data_item: DataItem.DataItem = None):
        super().__init__()
        self.__container_weak_ref = None

        self.define_type("display_data_channel")
        # conversion to scalar
        self.define_property("complex_display_type", changed=self.__property_changed)
        # data scaling and color (raster)
        self.define_property("display_limits", validate=self.__validate_display_limits, changed=self.__property_changed)
        self.define_property("color_map_id", changed=self.__color_map_id_changed)
        # slicing data to 1d or 2d
        self.define_property("sequence_index", 0, validate=self.__validate_sequence_index, changed=self.__property_changed)
        self.define_property("collection_index", (0, 0, 0), validate=self.__validate_collection_index, changed=self.__property_changed)
        self.define_property("slice_center", 0, validate=self.__validate_slice_center, changed=self.__slice_interval_changed)
        self.define_property("slice_width", 1, validate=self.__validate_slice_width, changed=self.__slice_interval_changed)
        self.define_property("data_item_reference", None)

        # # last display values is the last one to be fully displayed.
        # # when the current display values makes it all the way to display, it will invoke the finalize method.
        # # the display_data_channel will listen for that event and update last display values.
        self.__last_display_values = None
        self.__current_display_values = None
        self.__is_master = True
        self.__display_ref_count = 0

        self.__slice_interval = None

        self.__data_item = None
        if data_item:
            self.data_item_reference = str(data_item.uuid)
        self.__old_data_shape = None

        self.__color_map_data = None
        self.modified_state = 0

        self.property_changed_event = Event.Event()
        self.display_values_changed_event = Event.Event()
        self.display_data_will_change_event = Event.Event()
        self.__calculated_display_values_available_event = Event.Event()

        self.data_item_will_change_event = Event.Event()
        self.data_item_did_change_event = Event.Event()
        self.data_item_changed_event = Event.Event()
        self.data_item_description_changed_event = Event.Event()

        self.__data_item_property_changed_event_listener = None
        self.__data_item_will_change_listener = None
        self.__data_item_did_change_listener = None
        self.__data_item_item_changed_listener = None
        self.__data_item_data_item_changed_listener = None
        self.__data_item_data_changed_listener = None
        self.__data_item_description_changed_listener = None

        self.__connect_data_item(data_item)

        self.about_to_be_removed_event = Event.Event()
        self.about_to_cascade_delete_event = Event.Event()
        self._about_to_be_removed = False
        self._closed = False

    def close(self):
        self.__disconnect_data_item_events()
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None

    @property
    def container(self):
        return self.__container_weak_ref() if self.__container_weak_ref else None

    def prepare_cascade_delete(self) -> typing.List:
        cascade_items = list()
        self.about_to_cascade_delete_event.fire(cascade_items)
        return cascade_items

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        self.about_to_be_removed_event.fire()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

    def insert_model_item(self, container, name, before_index, item):
        if self.__container_weak_ref:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        if self.__container_weak_ref:
            return self.container.remove_model_item(container, name, item, safe=safe)
        else:
            container.remove_item(name, item)
            return None

    def clone(self):
        display_data_channel = DisplayDataChannel()
        display_data_channel.uuid = self.uuid
        return display_data_channel

    def copy_display_data_properties_from(self, display_data_channel: "DisplayDataChannel") -> None:
        self.complex_display_type = display_data_channel.complex_display_type
        self.display_limits = display_data_channel.display_limits
        self.color_map_id = display_data_channel.color_map_id
        self.sequence_index = display_data_channel.sequence_index
        self.collection_index = display_data_channel.collection_index
        self.slice_center = display_data_channel.slice_center
        self.slice_width = display_data_channel.slice_width

    def __connect_data_item_events(self):

        def property_changed(property_name):
            self.modified_state += 1

        def data_changed():
            data_metadata = self._get_data_metadata()
            new_data_shape = data_metadata.data_shape if data_metadata else None
            if new_data_shape != self.__old_data_shape:
                self.__validate_slice_indexes()
            self.__old_data_shape = new_data_shape
            self.data_item_changed_event.fire()

        if self.__data_item:
            self.__data_item_property_changed_event_listener = self.__data_item.property_changed_event.listen(property_changed)
            self.__data_item_will_change_listener = self.__data_item.will_change_event.listen(self.data_item_will_change_event.fire)
            self.__data_item_did_change_listener = self.__data_item.did_change_event.listen(self.data_item_did_change_event.fire)
            self.__data_item_item_changed_listener = self.__data_item.item_changed_event.listen(self.data_item_changed_event.fire)
            self.__data_item_data_item_changed_listener = self.__data_item.data_item_changed_event.listen(self.data_item_changed_event.fire)
            self.__data_item_data_changed_listener = self.__data_item.data_changed_event.listen(data_changed)
            self.__data_item_description_changed_listener = self.__data_item.description_changed_event.listen(self.data_item_description_changed_event.fire)

    def __disconnect_data_item_events(self):
        if self.__data_item_property_changed_event_listener:
            self.__data_item_property_changed_event_listener.close()
            self.__data_item_property_changed_event_listener = None
        if self.__data_item_will_change_listener:
            self.__data_item_will_change_listener.close()
            self.__data_item_will_change_listener = None
        if self.__data_item_did_change_listener:
            self.__data_item_did_change_listener.close()
            self.__data_item_did_change_listener = None
        if self.__data_item_item_changed_listener:
            self.__data_item_item_changed_listener.close()
            self.__data_item_item_changed_listener = None
        if self.__data_item_data_item_changed_listener:
            self.__data_item_data_item_changed_listener.close()
            self.__data_item_data_item_changed_listener = None
        if self.__data_item_data_changed_listener:
            self.__data_item_data_changed_listener.close()
            self.__data_item_data_changed_listener = None
        if self.__data_item_description_changed_listener:
            self.__data_item_description_changed_listener.close()
            self.__data_item_description_changed_listener = None

    def __connect_data_item(self, data_item):
        if self.__data_item:
            self.__disconnect_data_item_events()
            for _ in range(self.__display_ref_count):
                self.__data_item.decrement_data_ref_count()
        self.__data_item = data_item
        self.__connect_data_item_events()
        self.__validate_slice_indexes()
        if self.__data_item:
            for _ in range(self.__display_ref_count):
                self.__data_item.increment_data_ref_count()

    def connect_data_item(self, lookup_data_item):
        data_item = lookup_data_item(uuid.UUID(self.data_item_reference))
        self.__connect_data_item(data_item)

    def attempt_connect_data_item(self, data_item: DataItem.DataItem) -> bool:
        if not self.__data_item and self.data_item_reference == str(data_item.uuid):
            self.__connect_data_item(data_item)
            return True
        return False

    @property
    def data_item(self) -> DataItem.DataItem:
        return self.__data_item

    @property
    def created_local_as_string(self) -> str:
        return self.__data_item.created_local_as_string if self.__data_item else None

    @property
    def size_and_data_format_as_string(self) -> str:
        return self.__data_item.size_and_data_format_as_string if self.__data_item else None

    @property
    def display_data_shape(self) -> typing.Optional[typing.Tuple[int, ...]]:
        return self.__data_item.display_data_shape if self.__data_item else tuple()

    def _get_data_metadata(self) -> typing.Optional[DataAndMetadata.DataMetadata]:
        return self.__data_item.data_metadata if self.__data_item else None

    def __validate_display_limits(self, value):
        if value is not None:
            value = list(int(v) if numpy.issubdtype(type(v), numpy.bool_) else v for v in value)
            if len(value) == 0:
                return None
            elif len(value) == 1:
                return (value[0], None) if value[0] is not None else None
            elif value[0] is not None and value[1] is not None:
                return min(value[0], value[1]), max(value[0], value[1])
            elif value[0] is None and value[1] is None:
                return None
            else:
                return value[0], value[1]
        return value

    def __validate_sequence_index(self, value: int) -> int:
        if not self._is_reading:
            data_metadata = self._get_data_metadata()
            if data_metadata and data_metadata.dimensional_shape is not None:
                return max(min(int(value), data_metadata.max_sequence_index - 1), 0) if data_metadata.is_sequence else 0
        return value if self._is_reading else 0

    def __validate_collection_index(self, value: typing.Tuple[int, int, int]) -> typing.Tuple[int, int, int]:
        if not self._is_reading:
            data_metadata = self._get_data_metadata()
            if data_metadata and data_metadata.dimensional_shape is not None:
                dimensional_shape = data_metadata.dimensional_shape
                collection_base_index = 1 if data_metadata.is_sequence else 0
                collection_dimension_count = data_metadata.collection_dimension_count
                i0 = max(min(int(value[0]), dimensional_shape[collection_base_index + 0] - 1), 0) if collection_dimension_count > 0 else 0
                i1 = max(min(int(value[1]), dimensional_shape[collection_base_index + 1] - 1), 0) if collection_dimension_count > 1 else 0
                i2 = max(min(int(value[2]), dimensional_shape[collection_base_index + 2] - 1), 0) if collection_dimension_count > 2 else 0
                return i0, i1, i2
        return value if self._is_reading else (0, 0, 0)

    def __validate_slice_center_for_width(self, value, slice_width):
        data_metadata = self._get_data_metadata()
        if data_metadata and data_metadata.dimensional_shape is not None:
            depth = data_metadata.dimensional_shape[-1]
            mn = max(int(slice_width * 0.5), 0)
            mx = min(int(depth - slice_width * 0.5), depth - 1)
            return min(max(int(value), mn), mx)
        return value if self._is_reading else 0

    def __validate_slice_center(self, value):
        return self.__validate_slice_center_for_width(value, self.slice_width)

    def __validate_slice_width(self, value):
        data_metadata = self._get_data_metadata()
        if data_metadata and data_metadata.dimensional_shape is not None:
            depth = data_metadata.dimensional_shape[-1]  # signal_index
            slice_center = self.slice_center
            mn = 1
            mx = max(min(slice_center, depth - slice_center) * 2, 1)
            return min(max(value, mn), mx)
        return value if self._is_reading else 1

    def __validate_slice_indexes(self) -> None:
        sequence_index = self.__validate_sequence_index(self.sequence_index)
        if sequence_index != self.sequence_index:
            self.sequence_index = sequence_index

        collection_index = self.__validate_collection_index(self.collection_index)
        if collection_index != self.collection_index:
            self.collection_index = collection_index

        slice_center = self.__validate_slice_center_for_width(self.slice_center, 1)
        if slice_center != self.slice_center:
            old_slice_width = self.slice_width
            self.slice_width = 1
            self.slice_center = self.slice_center
            self.slice_width = old_slice_width

        # the slice interval may be invalid if the associated data item is not valid;
        # this ensures that as the data item becomes valid or invalid, the slice interval
        # if updated accordingly.
        if self.slice_interval != self.__slice_interval:
            self.__slice_interval_changed("slice_interval", None)

    @property
    def slice_interval(self):
        data_metadata = self._get_data_metadata()
        if data_metadata and data_metadata.dimensional_shape is not None:
            depth = data_metadata.dimensional_shape[-1]  # signal_index
            if depth > 0:
                slice_interval_start = round(self.slice_center - self.slice_width * 0.5)
                slice_interval_end = slice_interval_start + self.slice_width
                return (float(slice_interval_start) / depth, float(slice_interval_end) / depth)
            return 0, 0
        return None

    @slice_interval.setter
    def slice_interval(self, slice_interval):
        data_metadata = self._get_data_metadata()
        if data_metadata.dimensional_shape is not None:
            depth = data_metadata.dimensional_shape[-1]  # signal_index
            if depth > 0:
                slice_interval_center = round(((slice_interval[0] + slice_interval[1]) * 0.5) * depth)
                slice_interval_width = round((slice_interval[1] - slice_interval[0]) * depth)
                self.slice_center = slice_interval_center
                self.slice_width = slice_interval_width

    def __slice_interval_changed(self, name, value):
        # notify for dependent slice_interval property
        self.__property_changed(name, value)
        self.notify_property_changed("slice_interval")
        self.__slice_interval = self.slice_interval

    def __color_map_id_changed(self, property_name, value):
        self.__property_changed(property_name, value)
        if value:
            self.__color_map_data = ColorMaps.get_color_map_data_by_id(value)
        else:
            self.__color_map_data = None
        self.__property_changed("color_map_data", self.__color_map_data)

    @property
    def color_map_data(self) -> typing.Optional[numpy.ndarray]:
        """Return the color map data as a uint8 ndarray with shape (256, 3)."""
        if self.display_data_shape is None:  # is there display data?
            return None
        else:
            return self.__color_map_data if self.__color_map_data is not None else ColorMaps.get_color_map_data_by_id("grayscale")

    def __property_changed(self, property_name, value):
        # when one of the defined properties changes, this gets called
        self.notify_property_changed(property_name)
        if property_name in ("sequence_index", "collection_index", "slice_center", "slice_width", "complex_display_type", "display_limits", "color_map_data"):
            self.display_data_will_change_event.fire()
            self.__send_next_calculated_display_values()

    def save_properties(self) -> typing.Tuple:
        return (
            self.complex_display_type,
            self.display_limits,
            self.color_map_id,
            self.sequence_index,
            self.collection_index,
            self.slice_center,
            self.slice_interval,
        )

    def restore_properties(self, properties: typing.Tuple) -> None:
        self.complex_display_type = properties[0]
        self.display_limits = properties[1]
        self.color_map_id = properties[2]
        self.sequence_index = properties[3]
        self.collection_index = properties[4]
        self.slice_center = properties[5]
        self.slice_interval = properties[6]

    def update_display_data(self) -> None:
        self.__send_next_calculated_display_values()

    def add_calculated_display_values_listener(self, callback, send=True):
        listener = self.__calculated_display_values_available_event.listen(callback)
        if send:
            self.__send_next_calculated_display_values()
        return listener

    def __send_next_calculated_display_values(self) -> None:
        """Fire event to signal new display values are available."""
        self.__current_display_values = None
        self.__calculated_display_values_available_event.fire()

    def get_calculated_display_values(self, immediate: bool=False) -> DisplayValues:
        """Return the display values.

        Return the current (possibly uncalculated) display values unless 'immediate' is specified.

        If 'immediate', return the existing (calculated) values if they exist. Using the 'immediate' values
        avoids calculation except in cases where the display values haven't already been calculated.
        """
        if not immediate or not self.__is_master or not self.__last_display_values:
            if not self.__current_display_values and self.__data_item:
                self.__current_display_values = DisplayValues(self.__data_item.xdata, self.sequence_index, self.collection_index, self.slice_center, self.slice_width, self.display_limits, self.complex_display_type, self.__color_map_data)

                def finalize(display_values):
                    self.__last_display_values = display_values
                    self.display_values_changed_event.fire()

                self.__current_display_values.on_finalize = finalize
            return self.__current_display_values
        return self.__last_display_values

    def increment_display_ref_count(self, amount: int=1):
        """Increment display reference count to indicate this library item is currently displayed."""
        display_ref_count = self.__display_ref_count
        self.__display_ref_count += amount
        if display_ref_count == 0:
            self.__is_master = True
        if self.__data_item:
            for _ in range(amount):
                self.__data_item.increment_data_ref_count()

    def decrement_display_ref_count(self, amount: int=1):
        """Decrement display reference count to indicate this library item is no longer displayed."""
        assert not self._closed
        self.__display_ref_count -= amount
        if self.__display_ref_count == 0:
            self.__is_master = False
        if self.__data_item:
            for _ in range(amount):
                self.__data_item.decrement_data_ref_count()

    @property
    def _display_ref_count(self):
        return self.__display_ref_count

    def reset_display_limits(self):
        """Reset display limits so that they are auto calculated whenever the data changes."""
        self.display_limits = None

    def auto_display_limits(self):
        """Calculate best display limits and set them."""
        display_data_and_metadata = self.get_calculated_display_values(True).display_data_and_metadata
        data = display_data_and_metadata.data if display_data_and_metadata else None
        if data is not None:
            # The old algorithm was a problem during EELS where the signal data
            # is a small percentage of the overall data and was falling outside
            # the included range. This is the new simplified algorithm. Future
            # feature may allow user to select more complex algorithms.
            mn, mx = numpy.nanmin(data), numpy.nanmax(data)
            self.display_limits = mn, mx


def display_data_channel_factory(lookup_id):
    return DisplayDataChannel()


class DisplayItem(Observable.Observable, Persistence.PersistentObject):
    def __init__(self, item_uuid: uuid.UUID = None, *, data_item: DataItem.DataItem = None):
        super().__init__()
        self.uuid = item_uuid if item_uuid else self.uuid
        self.__container_weak_ref = None
        self.define_property("created", datetime.datetime.utcnow(), converter=DataItem.DatetimeToStringConverter(), changed=self.__property_changed)
        # windows utcnow has a resolution of 1ms, this sleep can guarantee unique times for all created times during a particular test.
        # this is not my favorite solution since it limits library item creation to 1000/s but until I find a better solution, this is my compromise.
        time.sleep(0.001)
        self.define_type("display_item")
        self.define_property("display_type", changed=self.__display_type_changed)
        self.define_property("title", hidden=True, changed=self.__property_changed)
        self.define_property("caption", hidden=True, changed=self.__property_changed)
        self.define_property("description", hidden=True, changed=self.__property_changed)
        self.define_property("session_id", hidden=True, changed=self.__property_changed)
        self.define_property("calibration_style_id", "calibrated", changed=self.__property_changed)
        self.define_property("display_properties", dict(), copy_on_read=True, changed=self.__display_properties_changed)
        self.define_property("display_layers", list(), copy_on_read=True, changed=self.__display_properties_changed)
        self.define_relationship("graphics", Graphics.factory, insert=self.__insert_graphic, remove=self.__remove_graphic)
        self.define_relationship("display_data_channels", display_data_channel_factory, insert=self.__insert_display_data_channel, remove=self.__remove_display_data_channel)

        self.__display_data_channel_property_changed_event_listeners = list()
        self.__display_data_channel_data_item_will_change_event_listeners = list()
        self.__display_data_channel_data_item_did_change_event_listeners = list()
        self.__display_data_channel_data_item_changed_event_listeners = list()
        self.__display_data_channel_data_item_description_changed_event_listeners = list()

        self.display_property_changed_event = Event.Event()
        self.display_changed_event = Event.Event()

        self.__registration_listener = None

        self.__cache = Cache.ShadowCache()
        self.__suspendable_storage_cache = None

        self.__in_transaction_state = False
        self.__write_delay_modified_count = 0

        # the most recent data to be displayed. should have immediate data available.
        self.__data_and_metadata = None
        self.__is_composite_data = False
        self.__dimensional_calibrations = None
        self.__intensity_calibration = None
        self.__dimensional_shape = None
        self.__scales = None

        self.__graphic_changed_listeners = list()
        self.__display_item_change_count = 0
        self.__display_item_change_count_lock = threading.RLock()
        self.__display_ref_count = 0
        self.graphic_selection = GraphicSelection()
        self.graphic_selection_changed_event = Event.Event()
        self.graphics_changed_event = Event.Event()
        self.display_values_changed_event = Event.Event()
        self.item_changed_event = Event.Event()
        self.about_to_be_removed_event = Event.Event()
        self.about_to_cascade_delete_event = Event.Event()
        self._about_to_be_removed = False
        self._closed = False

        def graphic_selection_changed():
            # relay the message
            self.graphic_selection_changed_event.fire(self.graphic_selection)
            self.graphics_changed_event.fire(self.graphic_selection)

        self.__graphic_selection_changed_event_listener = self.graphic_selection.changed_event.listen(graphic_selection_changed)

        if data_item:
            self.append_display_data_channel_for_data_item(data_item)

    def close(self):
        if self.__registration_listener:
            self.__registration_listener.close()
            self.__registration_listener = None
        self.__graphic_selection_changed_event_listener.close()
        self.__graphic_selection_changed_event_listener = None
        for display_data_channel in copy.copy(self.display_data_channels):
            self.__disconnect_display_data_channel(display_data_channel, 0)
            display_data_channel.close()
        for graphic in copy.copy(self.graphics):
            self.__disconnect_graphic(graphic, 0)
            graphic.close()
        self.graphic_selection = None
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None

    def __copy__(self):
        assert False

    def __deepcopy__(self, memo):
        display_item_copy = self.__class__()
        display_item_copy.display_type = self.display_type
        # metadata
        display_item_copy._set_persistent_property_value("title", self._get_persistent_property_value("title"))
        display_item_copy._set_persistent_property_value("caption", self._get_persistent_property_value("caption"))
        display_item_copy._set_persistent_property_value("description", self._get_persistent_property_value("description"))
        display_item_copy._set_persistent_property_value("session_id", self._get_persistent_property_value("session_id"))
        display_item_copy._set_persistent_property_value("calibration_style_id", self._get_persistent_property_value("calibration_style_id"))
        display_item_copy._set_persistent_property_value("display_properties", self._get_persistent_property_value("display_properties"))
        display_item_copy._set_persistent_property_value("display_layers", self._get_persistent_property_value("display_layers"))
        display_item_copy.created = self.created
        # data items
        for display_data_channel in self.display_data_channels:
            display_item_copy.append_display_data_channel(copy.deepcopy(display_data_channel))
        # display
        for graphic in self.graphics:
            display_item_copy.add_graphic(copy.deepcopy(graphic))
        memo[id(self)] = display_item_copy
        return display_item_copy

    @property
    def container(self):
        return self.__container_weak_ref()

    def about_to_close(self):
        self.__disconnect_data_sources()

    def prepare_cascade_delete(self) -> typing.List:
        cascade_items = list()
        self.about_to_cascade_delete_event.fire(cascade_items)
        return cascade_items

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        for display_data_channel in self.display_data_channels:
            display_data_channel.about_to_be_removed()
        for graphic in self.graphics:
            graphic.about_to_be_removed()
        self.about_to_be_removed_event.fire()
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

    # call this when the listeners need to be updated (via data_item_content_changed).
    # Calling this method will send the data_item_content_changed method to each listener by using the method
    # data_item_changes.
    def _notify_display_item_content_changed(self):
        with self.display_item_changes():
            pass

    # override from storage to watch for changes to this library item. notify observers.
    def notify_property_changed(self, key):
        super().notify_property_changed(key)
        self._notify_display_item_content_changed()

    def __display_type_changed(self, name, value):
        self.__property_changed(name, value)
        # the order here is important; display values must come before display changed
        # so that the display canvas item is updated properly.
        self.display_values_changed_event.fire()
        self.display_changed_event.fire()
        self.graphics_changed_event.fire(self.graphic_selection)

    def __property_changed(self, name, value):
        self.notify_property_changed(name)
        if name == "title":
            self.notify_property_changed("displayed_title")
        if name == "calibration_style_id":
            self.display_property_changed_event.fire("calibration_style_id")

    def __display_properties_changed(self, name, value):
        self.notify_property_changed(name)

    def clone(self) -> "DisplayItem":
        display_item = self.__class__()
        display_item.uuid = self.uuid
        for graphic in self.graphics:
            display_item.add_graphic(graphic.clone())
        return display_item

    def snapshot(self):
        """Return a new library item which is a copy of this one with any dynamic behavior made static."""
        display_item = self.__class__()
        display_item.display_type = self.display_type
        # metadata
        display_item._set_persistent_property_value("title", self._get_persistent_property_value("title"))
        display_item._set_persistent_property_value("caption", self._get_persistent_property_value("caption"))
        display_item._set_persistent_property_value("description", self._get_persistent_property_value("description"))
        display_item._set_persistent_property_value("session_id", self._get_persistent_property_value("session_id"))
        display_item._set_persistent_property_value("calibration_style_id", self._get_persistent_property_value("calibration_style_id"))
        display_item._set_persistent_property_value("display_properties", self._get_persistent_property_value("display_properties"))
        display_item.created = self.created
        for graphic in self.graphics:
            display_item.add_graphic(copy.deepcopy(graphic))
        for display_data_channel in self.display_data_channels:
            display_item.append_display_data_channel(copy.deepcopy(display_data_channel))
        # this goes after the display data channels so that the layers don't get adjusted
        display_item._set_persistent_property_value("display_layers", self._get_persistent_property_value("display_layers"))
        return display_item

    def set_storage_cache(self, storage_cache):
        self.__suspendable_storage_cache = Cache.SuspendableCache(storage_cache)
        self.__cache.set_storage_cache(self._suspendable_storage_cache, self)

    @property
    def _suspendable_storage_cache(self):
        return self.__suspendable_storage_cache

    @property
    def _display_cache(self):
        return self.__cache

    def read_from_dict(self, properties):
        super().read_from_dict(properties)
        if self.created is None:  # invalid timestamp -- set property to now but don't trigger change
            timestamp = datetime.datetime.now()
            self._get_persistent_property("created").value = timestamp

    @property
    def properties(self):
        """ Used for debugging. """
        if self.persistent_object_context:
            return self.persistent_object_context.get_properties(self)
        return dict()

    @property
    def in_transaction_state(self) -> bool:
        return self.__in_transaction_state

    def __enter_write_delay_state(self):
        self.__write_delay_modified_count = self.modified_count
        if self.persistent_object_context:
            self.persistent_object_context.enter_write_delay(self)

    def __exit_write_delay_state(self):
        if self.persistent_object_context:
            self.persistent_object_context.exit_write_delay(self)
            self._finish_pending_write()

    def _finish_pending_write(self):
        if self.modified_count > self.__write_delay_modified_count:
            self.persistent_object_context.rewrite_item(self)

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

    def persistent_object_context_changed(self):
        # handle case where persistent object context is set on an item that is already under transaction.
        # this can occur during acquisition. any other cases?
        super().persistent_object_context_changed()

        if self.__in_transaction_state:
            self.__enter_write_delay_state()

        def register_object(registered_object, unregistered_object):
            if isinstance(registered_object, DataItem.DataItem):
                connected = False
                for display_data_channel in self.display_data_channels:
                    connected = connected or display_data_channel.attempt_connect_data_item(registered_object)
                if connected:
                    self._update_displays()

        if self.persistent_object_context:
            self.__registration_listener = self.persistent_object_context.registration_event.listen(register_object)

    def get_display_property(self, property_name: str, default_value=None):
        return self.display_properties.get(property_name, default_value)

    def set_display_property(self, property_name: str, value) -> None:
        display_properties = self.display_properties
        if value is not None:
            display_properties[property_name] = value
        else:
            display_properties.pop(property_name, None)
        self.display_properties = display_properties
        self.display_property_changed_event.fire(property_name)
        if property_name in ("displayed_dimensional_scales", "displayed_dimensional_calibrations", "displayed_intensity_calibration"):
            self.graphics_changed_event.fire(self.graphic_selection)
        if property_name in ("calibration_style_id", ):
            self.display_property_changed_event.fire("displayed_dimensional_scales")
            self.display_property_changed_event.fire("displayed_dimensional_calibrations")
            self.display_property_changed_event.fire("displayed_intensity_calibration")
            self.graphics_changed_event.fire(self.graphic_selection)
        self.display_changed_event.fire()

    def get_display_layer_property(self, index: int, property_name: str, default_value=None):
        display_layers = self.display_layers
        if 0 <= index < len(display_layers):
            return display_layers[index].get(property_name, default_value)
        return None

    def _set_display_layer_property(self, index: int, property_name: str, value) -> None:
        self.display_layers = set_display_layer_property(self.display_layers, index, property_name, value)

    def add_display_layer(self, **kwargs) -> None:
        self.display_layers = add_display_layer(self.display_layers, **kwargs)

    def insert_display_layer(self, before_index: int, **kwargs) -> None:
        self.display_layers = insert_display_layer(self.display_layers, before_index, **kwargs)

    def remove_display_layer(self, index: int) -> None:
        self.display_layers = remove_display_layer(self.display_layers, index)

    def move_display_layer_forward(self, index: int) -> None:
        self.display_layers = move_display_layer_forward(self.display_layers, index)

    def move_display_layer_backward(self, index: int) -> None:
        self.display_layers = move_display_layer_backward(self.display_layers, index)

    def copy_display_layer(self, before_index: int, display_item: "DisplayItem", display_layer: typing.Dict) -> None:
        display_layer_copy = copy.deepcopy(display_layer)
        display_data_channel_copy = copy.deepcopy(display_item.display_data_channels[display_layer_copy["data_index"]])
        self.append_display_data_channel(display_data_channel_copy)
        display_data_channel_copy_index = len(self.display_data_channels) - 1
        display_layer_copy["data_index"] = display_data_channel_copy_index
        display_layer_copy["fill_color"] = display_layer["fill_color"]
        self.insert_display_layer(before_index, **display_layer_copy)
        self.__auto_display_legend()

    def populate_display_layers(self) -> None:
        if len(self.display_layers) == 0:
            # create basic display layers here
            while len(self.display_layers) < len(self.display_data_channels):
                self.__add_display_layer_auto(dict(), len(self.display_layers))

    def append_display_data_channel_for_data_item(self, data_item: DataItem.DataItem) -> None:
        self.populate_display_layers()
        if not data_item in self.data_items:
            display_data_channel = DisplayDataChannel(data_item)
            self.append_display_data_channel(display_data_channel, display_layer=dict())

    def save_properties(self) -> typing.Tuple:
        return self.display_properties, self.display_layers, self.calibration_style_id

    def restore_properties(self, properties: typing.Tuple) -> None:
        self.display_properties, self.display_layers, self.calibration_style_id = properties

    def display_item_changes(self):
        # return a context manager to batch up a set of changes so that listeners
        # are only notified after the last change is complete.
        display_item = self
        class ContextManager:
            def __enter__(self):
                display_item._begin_display_item_changes()
                return self
            def __exit__(self, type, value, traceback):
                display_item._end_display_item_changes()
        return ContextManager()

    def _begin_display_item_changes(self):
        with self.__display_item_change_count_lock:
            self.__display_item_change_count += 1

    def _end_display_item_changes(self):
        with self.__display_item_change_count_lock:
            self.__display_item_change_count -= 1
            change_count = self.__display_item_change_count
        # if the change count is now zero, it means that we're ready to notify listeners.
        if change_count == 0:
            self.__write_delay_data_changed = True
            self.__item_changed()
            self._update_displays()  # this ensures that the display will validate

    def increment_display_ref_count(self, amount: int=1):
        """Increment display reference count to indicate this library item is currently displayed."""
        display_ref_count = self.__display_ref_count
        self.__display_ref_count += amount
        for display_data_channel in self.display_data_channels:
            display_data_channel.increment_display_ref_count(amount)

    def decrement_display_ref_count(self, amount: int=1):
        """Decrement display reference count to indicate this library item is no longer displayed."""
        assert not self._closed
        self.__display_ref_count -= amount
        for display_data_channel in self.display_data_channels:
            display_data_channel.decrement_display_ref_count(amount)

    @property
    def _display_ref_count(self):
        return self.__display_ref_count

    def __data_item_will_change(self):
        self._begin_display_item_changes()

    def __data_item_did_change(self):
        self._end_display_item_changes()

    def __item_changed(self):
        # this event is only triggered when the data item changed live state; everything else goes through
        # the data changed messages.
        self.item_changed_event.fire()

    def __display_channel_property_changed(self, name):
        self.display_changed_event.fire()

    @property
    def display_data_channel(self) -> DisplayDataChannel:
        display_data_channels = self.display_data_channels
        return display_data_channels[0] if len(display_data_channels) > 0 else None

    def get_display_data_channel_for_data_item(self, data_item: DataItem.DataItem) -> typing.Optional[DisplayDataChannel]:
        for display_data_channel in self.display_data_channels:
            if display_data_channel.data_item == data_item:
                return display_data_channel
        return None

    def _update_displays(self):
        for display_data_channel in self.display_data_channels:
            display_data_channel.update_display_data()
        xdata_list = [data_item.xdata if data_item else None for data_item in self.data_items]
        if len(xdata_list) > 0 and xdata_list[0]:
            dimensional_calibrations = xdata_list[0].dimensional_calibrations
            if len(dimensional_calibrations) > 1:
                self.__dimensional_calibrations = dimensional_calibrations
                self.__intensity_calibration = xdata_list[0].intensity_calibration
                self.__scales = 0, xdata_list[0].dimensional_shape[-1]
                self.__dimensional_shape = xdata_list[0].dimensional_shape
            else:
                units = dimensional_calibrations[-1].units
                mn = math.inf
                mx = -math.inf
                for xdata in xdata_list:
                    if xdata and xdata.dimensional_calibrations[-1].units == units:
                        v = dimensional_calibrations[0].convert_from_calibrated_value(xdata.dimensional_calibrations[-1].convert_to_calibrated_value(0))
                        mn = min(mn, v)
                        mx = max(mx, v)
                        v = dimensional_calibrations[0].convert_from_calibrated_value(xdata.dimensional_calibrations[-1].convert_to_calibrated_value(xdata.dimensional_shape[-1]))
                        mn = min(mn, v)
                        mx = max(mx, v)
                self.__dimensional_calibrations = dimensional_calibrations
                self.__intensity_calibration = xdata_list[0].intensity_calibration
                self.__scales = mn, mx
                self.__dimensional_shape = (mx - mn, )
        else:
            self.__dimensional_calibrations = None
            self.__intensity_calibration = None
            self.__scales = 0, 1
            self.__dimensional_shape = None
        self.__data_and_metadata = xdata_list[0] if len(xdata_list) == 1 else None
        self.__is_composite_data = len(xdata_list) > 1
        self.display_property_changed_event.fire("displayed_dimensional_scales")
        self.display_property_changed_event.fire("displayed_dimensional_calibrations")
        self.display_property_changed_event.fire("displayed_intensity_calibration")
        self.display_changed_event.fire()
        self.graphics_changed_event.fire(self.graphic_selection)

    def _description_changed(self):
        self.notify_property_changed("title")
        self.notify_property_changed("caption")
        self.notify_property_changed("description")
        self.notify_property_changed("session_id")
        self.notify_property_changed("displayed_title")

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
            self._description_changed()

    @property
    def text_for_filter(self) -> str:
        return " ".join([self.displayed_title, self.caption, self.description, self.size_and_data_format_as_string])

    @property
    def displayed_title(self):
        if self.data_item and getattr(self.data_item, "displayed_title", None):
            return self.data_item.displayed_title
        else:
            return self.title

    @property
    def title(self) -> str:
        return self.__get_used_value("title", DataItem.UNTITLED_STR)

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
    def session_id(self) -> str:
        return self.__get_used_value("session_id", str())

    @session_id.setter
    def session_id(self, value: str) -> None:
        self.__set_cascaded_value("session_id", str(value) if value is not None else str())

    def connect_data_items(self, lookup_data_item):
        for display_data_channel in self.display_data_channels:
            display_data_channel.connect_data_item(lookup_data_item)
        self._update_displays()  # this ensures that the display will validate

    def __insert_display_data_channel(self, name, before_index, display_data_channel: DisplayDataChannel) -> None:
        display_data_channel.about_to_be_inserted(self)
        display_data_channel.increment_display_ref_count(self._display_ref_count)
        self.__display_data_channel_property_changed_event_listeners.insert(before_index, display_data_channel.property_changed_event.listen(self.__display_channel_property_changed))
        self.__display_data_channel_data_item_will_change_event_listeners.insert(before_index, display_data_channel.data_item_will_change_event.listen(self.__data_item_will_change))
        self.__display_data_channel_data_item_did_change_event_listeners.insert(before_index, display_data_channel.data_item_did_change_event.listen(self.__data_item_did_change))
        self.__display_data_channel_data_item_changed_event_listeners.insert(before_index, display_data_channel.data_item_changed_event.listen(self.__item_changed))
        self.__display_data_channel_data_item_description_changed_event_listeners.insert(before_index, display_data_channel.data_item_description_changed_event.listen(self._description_changed))
        self.notify_insert_item("display_data_channels", display_data_channel, before_index)

    def __remove_display_data_channel(self, name, index, display_data_channel: DisplayDataChannel) -> None:
        display_data_channel.decrement_display_ref_count(self._display_ref_count)
        display_data_channel.about_to_be_removed()
        self.__disconnect_display_data_channel(display_data_channel, index)
        display_data_channel.close()
        # adjust the display layers
        assert not self._is_reading
        display_layers = self.display_layers
        new_display_layers = list()
        for display_layer in display_layers:
            data_index = display_layer.get("data_index")
            if data_index is not None:
                if data_index < index:
                    new_display_layers.append(display_layer)
                elif data_index > index:
                    display_layer["data_index"] = data_index - 1
                    new_display_layers.append(display_layer)
            else:
                new_display_layers.append(display_layer)
        self.display_layers = new_display_layers

    def __disconnect_display_data_channel(self, display_data_channel: DisplayDataChannel, index: int) -> None:
        self.__display_data_channel_property_changed_event_listeners[index].close()
        del self.__display_data_channel_property_changed_event_listeners[index]
        self.__display_data_channel_data_item_will_change_event_listeners[index].close()
        del self.__display_data_channel_data_item_will_change_event_listeners[index]
        self.__display_data_channel_data_item_did_change_event_listeners[index].close()
        del self.__display_data_channel_data_item_did_change_event_listeners[index]
        self.__display_data_channel_data_item_changed_event_listeners[index].close()
        del self.__display_data_channel_data_item_changed_event_listeners[index]
        self.__display_data_channel_data_item_description_changed_event_listeners[index].close()
        del self.__display_data_channel_data_item_description_changed_event_listeners[index]
        self.notify_remove_item("display_data_channels", display_data_channel, index)

    def append_display_data_channel(self, display_data_channel: DisplayDataChannel, display_layer: typing.Mapping=None) -> None:
        self.insert_display_data_channel(len(self.display_data_channels), display_data_channel)
        if display_layer is not None:
            display_layer = dict(display_layer)
            data_index = self.display_data_channels.index(display_data_channel)
            self.__add_display_layer_auto(display_layer, data_index)

    def __get_unique_display_layer_color(self) -> str:
        existing_colors = [display_layer_.get("fill_color") for display_layer_ in self.display_layers]
        for color in ('#1E90FF', "#F00", "#0F0", "#00F", "#FF0", "#0FF", "#F0F", "#888", "#800", "#080", "#008", "#CCC", "#880", "#088", "#808", "#964B00"):
            if not color in existing_colors:
                return color
        return '#1E90FF'

    def __auto_display_legend(self) -> None:
        if len(self.display_layers) == 2 and self.get_display_property("legend_position") is None:
            self.set_display_property("legend_position", "top-right")

    def __add_display_layer_auto(self, display_layer: typing.Dict, data_index: int) -> None:
        # this fill color code breaks encapsulation. i'm leaving it here as a convenience for now.
        # eventually there should be a connection to a display controller based on the display type which can be
        # used to set defaults for the layers.
        display_layer["data_index"] = data_index
        display_layer.setdefault("fill_color", self.__get_unique_display_layer_color())
        self.add_display_layer(**display_layer)
        self.__auto_display_legend()

    def insert_display_data_channel(self, before_index: int, display_data_channel: DisplayDataChannel) -> None:
        self.insert_model_item(self, "display_data_channels", before_index, display_data_channel)
        # adjust the display layers
        assert not self._is_reading
        display_layers = self.display_layers
        for display_layer in display_layers:
            data_index = display_layer.get("data_index")
            if data_index is not None and data_index >= before_index:
                display_layer["data_index"] = data_index + 1
        self.display_layers = display_layers

    def remove_display_data_channel(self, display_data_channel: DisplayDataChannel, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        return self.remove_model_item(self, "display_data_channels", display_data_channel, safe=safe)

    def undelete_display_data_channel(self, before_index: int, display_data_channel: DisplayDataChannel, lookup_data_item) -> None:
        self.insert_display_data_channel(before_index, display_data_channel)
        data_item = lookup_data_item(uuid.UUID(display_data_channel.data_item_reference)) if display_data_channel.data_item_reference else None
        if data_item:
            if display_data_channel.attempt_connect_data_item(data_item):
                self._update_displays()

    @property
    def data_items(self) -> typing.Sequence[DataItem.DataItem]:
        return [display_data_channel.data_item for display_data_channel in self.display_data_channels]

    @property
    def data_item(self) -> typing.Optional[DataItem.DataItem]:
        data_items = self.data_items
        return data_items[0] if len(data_items) == 1 else None

    @property
    def selected_graphics(self) -> typing.Sequence[Graphics.Graphic]:
        return [self.graphics[i] for i in self.graphic_selection.indexes]

    def __insert_graphic(self, name, before_index, graphic):
        graphic.about_to_be_inserted(self)
        graphic_changed_listener = graphic.graphic_changed_event.listen(functools.partial(self.__graphic_changed, graphic))
        self.__graphic_changed_listeners.insert(before_index, graphic_changed_listener)
        self.graphic_selection.insert_index(before_index)
        self.notify_insert_item("graphics", graphic, before_index)
        self.__graphic_changed(graphic)

    def __remove_graphic(self, name, index, graphic):
        graphic.about_to_be_removed()
        self.__disconnect_graphic(graphic, index)
        graphic.close()

    def __disconnect_graphic(self, graphic, index):
        graphic_changed_listener = self.__graphic_changed_listeners[index]
        graphic_changed_listener.close()
        self.__graphic_changed_listeners.remove(graphic_changed_listener)
        self.graphic_selection.remove_index(index)
        self.__graphic_changed(graphic)
        self.notify_remove_item("graphics", graphic, index)

    def insert_graphic(self, before_index, graphic):
        """Insert a graphic before the index, but do it through the container, so dependencies can be tracked."""
        self.insert_model_item(self, "graphics", before_index, graphic)

    def add_graphic(self, graphic):
        """Append a graphic, but do it through the container, so dependencies can be tracked."""
        self.insert_model_item(self, "graphics", self.item_count("graphics"), graphic)

    def remove_graphic(self, graphic: Graphics.Graphic, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        """Remove a graphic, but do it through the container, so dependencies can be tracked."""
        return self.remove_model_item(self, "graphics", graphic, safe=safe)

    # this message comes from the graphic. the connection is established when a graphic
    # is added or removed from this object.
    def __graphic_changed(self, graphic):
        self.graphics_changed_event.fire(self.graphic_selection)

    @property
    def calibration_style(self) -> CalibrationStyle:
        return next(filter(lambda x: x.calibration_style_id == self.calibration_style_id, get_calibration_styles()), get_default_calibrated_calibration_style())

    @property
    def display_data_shape(self) -> typing.Optional[typing.Tuple[int, ...]]:
        if not self.__data_and_metadata:
            return None
        data_and_metadata = self.__data_and_metadata
        dimensional_shape = data_and_metadata.dimensional_shape
        next_dimension = 0
        if data_and_metadata.is_sequence:
            next_dimension += 1
        if data_and_metadata.is_collection:
            collection_dimension_count = data_and_metadata.collection_dimension_count
            datum_dimension_count = data_and_metadata.datum_dimension_count
            # next dimensions are treated as collection indexes.
            if collection_dimension_count == 1 and datum_dimension_count == 1:
                return dimensional_shape[next_dimension:next_dimension + collection_dimension_count + datum_dimension_count]
            elif collection_dimension_count == 2 and datum_dimension_count == 1:
                return dimensional_shape[next_dimension:next_dimension + collection_dimension_count]
            else:  # default, "pick"
                return dimensional_shape[next_dimension + collection_dimension_count:next_dimension + collection_dimension_count + datum_dimension_count]
        else:
            return dimensional_shape[next_dimension:]

    @property
    def dimensional_shape(self) -> typing.Optional[typing.Tuple[int, ...]]:
        """Shape of the underlying data, if only one."""
        if not self.__data_and_metadata:
            return None
        return self.__data_and_metadata.dimensional_shape

    @property
    def displayed_dimensional_scales(self) -> typing.Sequence[float]:
        """The scale of the fractional coordinate system.

        For displays associated with a single data item, this matches the size of the data.

        For displays associated with a composite data item, this must be stored in this class.
        """
        return self.__scales

    @property
    def displayed_dimensional_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        """The calibrations for all data dimensions in the displayed calibration style."""
        calibration_style = self.__get_calibration_style_for_id(self.calibration_style_id)
        calibration_style = CalibrationStyleNative() if not calibration_style else calibration_style
        if self.__dimensional_calibrations:
            return calibration_style.get_dimensional_calibrations(self.__dimensional_shape, self.__dimensional_calibrations)
        return [Calibration.Calibration() for c in self.__dimensional_calibrations] if self.__dimensional_calibrations else [Calibration.Calibration()]

    @property
    def displayed_datum_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        """The calibrations for only datum dimensions, in the displayed calibration style."""
        calibration_style = self.__get_calibration_style_for_id(self.calibration_style_id)
        calibration_style = CalibrationStyleNative() if not calibration_style else calibration_style
        if self.__dimensional_calibrations and self.__data_and_metadata:
            calibrations = calibration_style.get_dimensional_calibrations(self.__dimensional_shape, self.__dimensional_calibrations)
            data_and_metadata = self.__data_and_metadata
            next_dimension = 0
            if data_and_metadata.is_sequence:
                next_dimension += 1
            if data_and_metadata.is_collection:
                collection_dimension_count = data_and_metadata.collection_dimension_count
                datum_dimension_count = data_and_metadata.datum_dimension_count
                # next dimensions are treated as collection indexes.
                if collection_dimension_count == 1 and datum_dimension_count == 1:
                    return calibrations[next_dimension:next_dimension + collection_dimension_count + datum_dimension_count]
                elif collection_dimension_count == 2 and datum_dimension_count == 1:
                    return calibrations[next_dimension:next_dimension + collection_dimension_count]
                else:  # default, "pick"
                    return calibrations[next_dimension + collection_dimension_count:next_dimension + collection_dimension_count + datum_dimension_count]
            else:
                return calibrations[next_dimension:]
        return [Calibration.Calibration() for c in self.__dimensional_calibrations] if self.__dimensional_calibrations else [Calibration.Calibration()]

    @property
    def displayed_intensity_calibration(self) -> Calibration.Calibration:
        calibration_style = self.__get_calibration_style_for_id(self.calibration_style_id)
        if self.__intensity_calibration and (not calibration_style or calibration_style.is_calibrated):
            return self.__intensity_calibration
        return Calibration.Calibration()

    def __get_calibration_style_for_id(self, calibration_style_id: str) -> typing.Optional[CalibrationStyle]:
        return next(filter(lambda x: x.calibration_style_id == calibration_style_id, get_calibration_styles()), None)

    @property
    def size_and_data_format_as_string(self) -> str:
        data_item = self.data_item
        return data_item.size_and_data_format_as_string if data_item else str()

    @property
    def date_for_sorting(self):
        data_item_dates = [data_item.date_for_sorting if data_item else self.created for data_item in self.data_items]
        if len(data_item_dates):
            return max(data_item_dates)
        return self.created

    @property
    def date_for_sorting_local_as_string(self) -> str:
        data_item = self.data_item
        if data_item:
            return data_item.date_for_sorting_local_as_string
        date_utc = self.date_for_sorting
        tz_minutes = Utility.local_utcoffset_minutes(date_utc)
        date_local = date_utc + datetime.timedelta(minutes=tz_minutes)
        return date_local.strftime("%c")

    @property
    def created_local(self) -> datetime.datetime:
        created_utc = self.created
        tz_minutes = Utility.local_utcoffset_minutes(created_utc)
        return created_utc + datetime.timedelta(minutes=tz_minutes)

    @property
    def created_local_as_string(self) -> str:
        return self.created_local.strftime("%c")

    @property
    def is_live(self) -> bool:
        return any(data_item.is_live if data_item else False for data_item in self.data_items)

    @property
    def category(self) -> str:
        return "temporary" if any(data_item.category == "temporary" if data_item else None for data_item in self.data_items) else "persistent"

    @property
    def status_str(self) -> str:
        data_item = self.data_item
        if data_item and data_item.is_live:
            live_metadata = data_item.metadata.get("hardware_source", dict())
            frame_index_str = str(live_metadata.get("frame_index", str()))
            partial_str = "{0:d}/{1:d}".format(live_metadata.get("valid_rows"), data_item.dimensional_shape[0]) if "valid_rows" in live_metadata else str()
            return "{0:s} {1:s} {2:s}".format(_("Live"), frame_index_str, partial_str)
        return str()

    @property
    def used_display_type(self) -> str:
        display_type = self.display_type
        if not display_type in ("line_plot", "image", "display_script"):
            for data_item in self.data_items:
                display_data_shape = data_item.display_data_shape if data_item else None
                valid_data = (data_item is not None) and (functools.reduce(operator.mul, display_data_shape) > 0 if display_data_shape else False)
                if valid_data:
                    if data_item.collection_dimension_count == 2 and data_item.datum_dimension_count == 1:
                        display_type = "image"
                    elif data_item.datum_dimension_count == 1:
                        display_type = "line_plot"
                    elif data_item.datum_dimension_count == 2:
                        display_type = "image"
                    # override
                    if self.get_display_property("display_script"):
                        display_type = "display_script"
                    if display_type:
                        break
        return display_type

    def view_to_intervals(self, data_and_metadata: DataAndMetadata.DataAndMetadata, intervals: typing.List[typing.Tuple[float, float]]) -> None:
        """Change the view to encompass the channels and data represented by the given intervals."""
        left = None
        right = None
        for interval in intervals:
            left = min(left, interval[0]) if left is not None else interval[0]
            right = max(right, interval[1]) if right is not None else interval[1]
        left = left if left is not None else 0.0
        right = right if right is not None else 1.0
        extra = (right - left) * 0.5
        left_channel = int(max(0.0, left - extra) * data_and_metadata.data_shape[-1])
        right_channel = int(min(1.0, right + extra) * data_and_metadata.data_shape[-1])
        self.set_display_property("left_channel", left_channel)
        self.set_display_property("right_channel", right_channel)
        data_min = numpy.amin(data_and_metadata.data[..., left_channel:right_channel])
        data_max = numpy.amax(data_and_metadata.data[..., left_channel:right_channel])
        if data_min > 0 and data_max > 0:
            self.set_display_property("y_min", 0.0)
            self.set_display_property("y_max", data_max * 1.2)
        elif data_min < 0 and data_max < 0:
            self.set_display_property("y_min", data_min * 1.2)
            self.set_display_property("y_max", 0.0)
        else:
            self.set_display_property("y_min", data_min * 1.2)
            self.set_display_property("y_max", data_max * 1.2)

    def __get_calibrated_value_text(self, value: float, intensity_calibration) -> str:
        if value is not None:
            return intensity_calibration.convert_to_calibrated_value_str(value)
        elif value is None:
            return _("N/A")
        else:
            return str(value)

    def get_value_and_position_text(self, display_data_channel, pos) -> (str, str):
        data_and_metadata = self.__data_and_metadata
        dimensional_calibrations = self.displayed_dimensional_calibrations
        intensity_calibration = self.displayed_intensity_calibration

        if data_and_metadata is None or pos is None:
            if self.__is_composite_data and (pos is not None and len(pos) == 1):
                return u"{0}".format(dimensional_calibrations[-1].convert_to_calibrated_value_str(pos[0])), str()
            return str(), str()

        is_sequence = data_and_metadata.is_sequence
        collection_dimension_count = data_and_metadata.collection_dimension_count
        datum_dimension_count = data_and_metadata.datum_dimension_count
        if is_sequence:
            pos = (display_data_channel.sequence_index, ) + pos
        if collection_dimension_count == 2 and datum_dimension_count == 1:
            pos = pos + (display_data_channel.slice_center, )
        else:
            # reduce collection dimensions for case where 2 pos dimensions are supplied on 1 pos datum (line plot display as image)
            non_collection_dimension_count = datum_dimension_count + (1 if is_sequence else 0)
            collection_dimension_count -= len(pos) - non_collection_dimension_count
            # adjust position for collection dimensions
            pos = tuple(display_data_channel.collection_index[0:collection_dimension_count]) + pos

        while len(pos) < data_and_metadata.datum_dimension_count:
            pos = (0,) + tuple(pos)

        assert len(pos) == len(data_and_metadata.dimensional_shape)

        position_text = ""
        value_text = ""
        data_shape = data_and_metadata.data_shape
        if len(pos) == 4:
            # 4d image
            # make sure the position is within the bounds of the image
            if 0 <= pos[0] < data_shape[0] and 0 <= pos[1] < data_shape[1] and 0 <= pos[2] < data_shape[2] and 0 <= pos[3] < data_shape[3]:
                position_text = u"{0}, {1}, {2}, {3}".format(
                    dimensional_calibrations[3].convert_to_calibrated_value_str(pos[3], value_range=(0, data_shape[3]), samples=data_shape[3]),
                    dimensional_calibrations[2].convert_to_calibrated_value_str(pos[2], value_range=(0, data_shape[2]), samples=data_shape[2]),
                    dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1], value_range=(0, data_shape[1]), samples=data_shape[1]),
                    dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0], value_range=(0, data_shape[0]), samples=data_shape[0]))
                value_text = self.__get_calibrated_value_text(data_and_metadata.get_data_value(pos), intensity_calibration)
        if len(pos) == 3:
            # 3d image
            # make sure the position is within the bounds of the image
            if 0 <= pos[0] < data_shape[0] and 0 <= pos[1] < data_shape[1] and 0 <= pos[2] < data_shape[2]:
                position_text = u"{0}, {1}, {2}".format(dimensional_calibrations[2].convert_to_calibrated_value_str(pos[2], value_range=(0, data_shape[2]), samples=data_shape[2]),
                    dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1], value_range=(0, data_shape[1]), samples=data_shape[1]),
                    dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0], value_range=(0, data_shape[0]), samples=data_shape[0]))
                value_text = self.__get_calibrated_value_text(data_and_metadata.get_data_value(pos), intensity_calibration)
        if len(pos) == 2:
            # 2d image
            # make sure the position is within the bounds of the image
            if len(data_shape) == 1:
                if pos[-1] >= 0 and pos[-1] < data_shape[-1]:
                    position_text = u"{0}".format(dimensional_calibrations[-1].convert_to_calibrated_value_str(pos[-1], value_range=(0, data_shape[-1]), samples=data_shape[-1]))
                    full_pos = [0, ] * len(data_shape)
                    full_pos[-1] = pos[-1]
                    value_text = self.__get_calibrated_value_text(data_and_metadata.get_data_value(full_pos), intensity_calibration)
            else:
                if pos[0] >= 0 and pos[0] < data_shape[0] and pos[1] >= 0 and pos[1] < data_shape[1]:
                    is_polar = dimensional_calibrations[0].units.startswith("1/") and dimensional_calibrations[0].units == dimensional_calibrations[1].units
                    is_polar = is_polar and abs(dimensional_calibrations[0].scale * data_shape[0] - dimensional_calibrations[1].scale * data_shape[1]) < 1e-12
                    is_polar = is_polar and abs(dimensional_calibrations[0].offset / (dimensional_calibrations[0].scale * data_shape[0]) + 0.5) < 1e-12
                    is_polar = is_polar and abs(dimensional_calibrations[1].offset / (dimensional_calibrations[1].scale * data_shape[1]) + 0.5) < 1e-12
                    if is_polar:
                        x = dimensional_calibrations[1].convert_to_calibrated_value(pos[1])
                        y = dimensional_calibrations[0].convert_to_calibrated_value(pos[0])
                        r = math.sqrt(x * x + y * y)
                        angle = -math.atan2(y, x)
                        r_str = dimensional_calibrations[0].convert_to_calibrated_value_str(dimensional_calibrations[0].convert_from_calibrated_value(r), value_range=(0, data_shape[0]), samples=data_shape[0], display_inverted=True)
                        position_text = u"{0}, {1:.4f}° ({2})".format(r_str, math.degrees(angle), _("polar"))
                    else:
                        position_text = u"{0}, {1}".format(dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1], value_range=(0, data_shape[1]), samples=data_shape[1], display_inverted=True),
                            dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0], value_range=(0, data_shape[0]), samples=data_shape[0], display_inverted=True))
                    value_text = self.__get_calibrated_value_text(data_and_metadata.get_data_value(pos), intensity_calibration)
        if len(pos) == 1:
            # 1d plot
            # make sure the position is within the bounds of the line plot
            if pos[0] >= 0 and pos[0] < data_shape[-1]:
                position_text = u"{0}".format(dimensional_calibrations[-1].convert_to_calibrated_value_str(pos[0], value_range=(0, data_shape[-1]), samples=data_shape[-1]))
                full_pos = [0, ] * len(data_shape)
                full_pos[-1] = pos[0]
                value_text = self.__get_calibrated_value_text(data_and_metadata.get_data_value(full_pos), intensity_calibration)
        return position_text, value_text


class DisplayCalibrationInfo:

    def __init__(self, display_item, display_data_shape=None):
        self.display_data_shape = display_data_shape if display_data_shape is not None else display_item.display_data_shape
        self.displayed_dimensional_scales = display_item.displayed_dimensional_scales
        self.displayed_dimensional_calibrations = copy.deepcopy(display_item.displayed_dimensional_calibrations)
        self.displayed_intensity_calibration = copy.deepcopy(display_item.displayed_intensity_calibration)
        self.calibration_style = display_item.calibration_style

    def __ne__(self, display_calibration_info):
        if not display_calibration_info:
            return True
        if  self.display_data_shape != display_calibration_info.display_data_shape:
            return True
        if  self.displayed_dimensional_scales != display_calibration_info.displayed_dimensional_scales:
            return True
        if  self.displayed_dimensional_calibrations != display_calibration_info.displayed_dimensional_calibrations:
            return True
        if  self.displayed_intensity_calibration != display_calibration_info.displayed_intensity_calibration:
            return True
        if  type(self.calibration_style) != type(display_calibration_info.calibration_style):
            return True
        return False


def get_calibration_styles():
    return [CalibrationStyleNative(), CalibrationStylePixelsTopLeft(), CalibrationStylePixelsCenter(),
            CalibrationStyleFractionalTopLeft(), CalibrationStyleFractionalCenter()]


def get_default_calibrated_calibration_style():
    return CalibrationStyleNative()


def get_default_uncalibrated_calibration_style():
    return CalibrationStylePixelsCenter()


def set_display_layer_property(display_layers: list, index: int, property_name: str, value) -> list:
    assert 0 <= index < len(display_layers)
    if value is not None:
        display_layers[index][property_name] = value
    else:
        display_layers[index].pop(property_name, None)
    return display_layers


def add_display_layer(display_layers: list, **kwargs) -> list:
    return insert_display_layer(display_layers, len(display_layers), **kwargs)


def insert_display_layer(display_layers: list, before_index: int, **kwargs) -> list:
    display_layers.insert(before_index, kwargs)
    return display_layers


def remove_display_layer(display_layers: list, index: int) -> list:
    display_layers.pop(index)
    return display_layers


def move_display_layer_forward(display_layers: list, index: int) -> list:
    assert 0 <= index < len(display_layers)
    if index > 0:
        display_layer = display_layers.pop(index)
        display_layers.insert(index - 1, display_layer)
    return display_layers


def shift_display_layers(display_layers: list, from_index: int, to_index: int) -> list:
    assert 0 <= from_index < len(display_layers)
    assert 0 <= to_index < len(display_layers)

    if from_index == to_index:
        return display_layers

    moving_layer = display_layers.pop(from_index)

    display_layers.insert(to_index, moving_layer)

    return display_layers


def move_display_layer_backward(display_layers: list, index: int) -> list:
    assert 0 <= index < len(display_layers)
    if index < len(display_layers) - 1:
        display_layer = display_layers.pop(index)
        display_layers.insert(index + 1, display_layer)
    return display_layers
