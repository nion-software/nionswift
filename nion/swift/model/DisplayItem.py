from __future__ import annotations

# standard libraries
import asyncio
import contextlib
import copy
import datetime
import functools
import gettext
import math
import numbers
import weakref

import numpy
import operator
import threading
import types
import typing
import uuid

# local libraries
from nion.data import Calibration
from nion.data import Core
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import Cache
from nion.swift.model import Changes
from nion.swift.model import ColorMaps
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.model import Model
from nion.swift.model import Persistence
from nion.swift.model import Schema
from nion.swift.model import Utility
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ReferenceCounting
from nion.utils import Registry
from nion.utils import Color

if typing.TYPE_CHECKING:
    from nion.swift.model import Project

_ImageDataType = Image._ImageDataType
_RGBA32Type = Image._RGBAImageDataType
DisplayLimitsType = typing.Optional[typing.Tuple[typing.Optional[typing.Union[float, int]], typing.Optional[typing.Union[float, int]]]]

_ = gettext.gettext


class GraphicSelection:
    def __init__(self, indexes: typing.Optional[typing.Set[int]] = None, anchor_index: typing.Optional[int] = None) -> None:
        super().__init__()
        self.__changed_event = Event.Event()
        self.__indexes = copy.copy(indexes) if indexes else set()
        self.__anchor_index = anchor_index

    def __copy__(self) -> GraphicSelection:
        return type(self)(self.__indexes, self.__anchor_index)

    def __eq__(self, other: typing.Any) -> bool:
        return other is not None and self.indexes == other.indexes and self.anchor_index == other.anchor_index

    def __ne__(self, other: typing.Any) -> bool:
        return other is None or self.indexes != other.indexes or self.anchor_index != other.anchor_index

    @property
    def changed_event(self) -> Event.Event:
        return self.__changed_event

    @property
    def current_index(self) -> typing.Optional[int]:
        if len(self.__indexes) == 1:
            for index in self.__indexes:
                return index
        return None

    @property
    def anchor_index(self) -> typing.Optional[int]:
        return self.__anchor_index

    @property
    def has_selection(self) -> bool:
        return len(self.__indexes) > 0

    def contains(self, index: int) -> bool:
        return index in self.__indexes

    @property
    def indexes(self) -> typing.Set[int]:
        return self.__indexes

    def clear(self) -> None:
        old_index = self.__indexes.copy()
        self.__indexes = set()
        self.__anchor_index = None
        if old_index != self.__indexes:
            self.__changed_event.fire()

    def __update_anchor_index(self) -> None:
        for index in self.__indexes:
            if self.__anchor_index is None or index < self.__anchor_index:
                self.__anchor_index = index

    def add(self, index: int) -> None:
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes.add(index)
        if len(old_index) == 0:
            self.__anchor_index = index
        if old_index != self.__indexes:
            self.__changed_event.fire()

    def remove(self, index: int) -> None:
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes.remove(index)
        if not self.__anchor_index in self.__indexes:
            self.__update_anchor_index()
        if old_index != self.__indexes:
            self.__changed_event.fire()

    def add_range(self, range: range) -> None:
        for index in range:
            self.add(index)

    def set(self, index: int) -> None:
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes = set()
        self.__indexes.add(index)
        self.__anchor_index = index
        if old_index != self.__indexes:
            self.__changed_event.fire()

    def toggle(self, index: int) -> None:
        assert isinstance(index, numbers.Integral)
        if index in self.__indexes:
            self.remove(index)
        else:
            self.add(index)

    def insert_index(self, new_index: int) -> None:
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

    def remove_index(self, remove_index: int) -> None:
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


def calculate_display_range(display_limits: DisplayLimitsType,
                            data_range: typing.Optional[typing.Tuple[float, float]],
                            data_sample: typing.Optional[_ImageDataType], xdata: typing.Optional[DataAndMetadata.DataAndMetadata],
                            complex_display_type: typing.Optional[str]) -> typing.Optional[typing.Tuple[float, float]]:
    if display_limits is not None:
        assert data_range is not None
        display_limit_low = display_limits[0] if display_limits[0] is not None else data_range[0]
        display_limit_high = display_limits[1] if display_limits[1] is not None else data_range[1]
        return display_limit_low, display_limit_high
    if xdata and xdata.is_data_complex_type and complex_display_type is None:  # log absolute
        if data_sample is not None:
            assert data_range is not None
            fraction = 0.05
            display_limit_low = data_sample[int(data_sample.shape[0] * fraction)]
            display_limit_high = data_range[1]
            return display_limit_low, display_limit_high
    return data_range


class CalibrationStyle:
    label: typing.Optional[str] = None
    calibration_style_id: typing.Optional[str] = None
    is_calibrated: bool = False

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType) -> DataAndMetadata.CalibrationListType:
        return list()

    def get_intensity_calibration(self, xdata: DataAndMetadata.DataAndMetadata) -> Calibration.Calibration:
        return xdata.intensity_calibration if self.is_calibrated else Calibration.Calibration()


class CalibrationStyleNative(CalibrationStyle):
    label = _("Calibrated")
    calibration_style_id = "calibrated"
    is_calibrated = True

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType) -> DataAndMetadata.CalibrationListType:
        return dimensional_calibrations


class CalibrationStylePixelsTopLeft(CalibrationStyle):
    label = _("Pixels (Top-Left)")
    calibration_style_id = "pixels-top-left"

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType) -> DataAndMetadata.CalibrationListType:
        return [Calibration.Calibration() for display_dimension in dimensional_shape]


class CalibrationStylePixelsCenter(CalibrationStyle):
    label = _("Pixels (Center)")
    calibration_style_id = "pixels-center"

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType) -> DataAndMetadata.CalibrationListType:
        return [Calibration.Calibration(offset=-display_dimension/2) for display_dimension in dimensional_shape]


class CalibrationStyleFractionalTopLeft(CalibrationStyle):
    label = _("Fractional (Top Left)")
    calibration_style_id = "relative-top-left"

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType) -> DataAndMetadata.CalibrationListType:
        return [Calibration.Calibration(scale=1.0/display_dimension) for display_dimension in dimensional_shape]


class CalibrationStyleFractionalCenter(CalibrationStyle):
    label = _("Fractional (Center)")
    calibration_style_id = "relative-center"

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType) -> DataAndMetadata.CalibrationListType:
        return [Calibration.Calibration(scale=2.0/display_dimension, offset=-1.0) for display_dimension in dimensional_shape]


class AdjustmentType(typing.Protocol):
    def transform(self, data: _ImageDataType, display_limits: typing.Tuple[float, float]) -> _ImageDataType: ...


def adjustment_factory(adjustment_d: Persistence.PersistentDictType) -> typing.Optional[AdjustmentType]:
    if adjustment_d.get("type", None) == "gamma":
        class AdjustGamma:
            def __init__(self, gamma: float) -> None:
                self.__gamma = gamma

            def transform(self, data: _ImageDataType, display_limits: typing.Tuple[float, float]) -> _ImageDataType:
                return numpy.power(numpy.clip(data, 0.0, 1.0), self.__gamma, dtype=numpy.float32)  # type: ignore

        return AdjustGamma(adjustment_d.get("gamma", 1.0))
    elif adjustment_d.get("type", None) == "log":
        class AdjustLog:
            def transform(self, data: _ImageDataType, display_limits: typing.Tuple[float, float]) -> _ImageDataType:
                range = display_limits[1] - display_limits[0]
                c = 1.0 / (numpy.log2(1 + range))
                return c * numpy.log2(1 + range * numpy.clip(data, 0.0, 1.0), dtype=numpy.float32)  # type: ignore

        return AdjustLog()
    elif adjustment_d.get("type", None) == "equalized":
        class AdjustEqualized:
            def transform(self, data: _ImageDataType, display_limits: typing.Tuple[float, float]) -> _ImageDataType:
                data = numpy.clip(data, 0.0, 1.0)
                histogram, bins = numpy.histogram(data.flatten(), 256, density=True)  # type: ignore
                histogram_cdf = histogram.cumsum()
                histogram_cdf = histogram_cdf / histogram_cdf[-1]
                equalized = numpy.interp(data.flatten(), bins[:-1], histogram_cdf)  # type: ignore
                return equalized.reshape(data.shape)  # type: ignore

        return AdjustEqualized()
    else:
        return None


class DisplayValues:
    """Calculate display data used to render the display.

    The display calculation goes through the following steps:

    1. start with raw data
    2. extract the raw data element using sequence and/or collection indexes and/or slices if required
    3. produce display data by applying complex to real conversion if required
    4. apply adjustments by normalizing display data and performing adjustment operation
    5. calculate rgb display data by scaling display range and applying color table

    data -> element -> display -> normalized -> adjusted -> display_rgba

    Display renderers may request data at any stage of this pipeline.
    """
    _count = 0

    def __init__(self, data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata], sequence_index: int,
                 collection_index: typing.Optional[DataAndMetadata.PositionType], slice_center: int, slice_width: int,
                 display_limits: DisplayLimitsType,
                 complex_display_type: typing.Optional[str],
                 color_map_data: typing.Optional[_RGBA32Type], brightness: float, contrast: float,
                 adjustments: typing.Sequence[Persistence.PersistentDictType]) -> None:
        DisplayValues._count += 1
        self.__lock = threading.RLock()
        self.__data_and_metadata = data_and_metadata
        self.__sequence_index = sequence_index
        self.__collection_index = collection_index
        self.__slice_center = slice_center
        self.__slice_width = slice_width
        self.__display_limits = display_limits
        self.__complex_display_type = complex_display_type
        self.__color_map_data = color_map_data
        self.__brightness = brightness
        self.__contrast = contrast
        self.__adjustments = list(adjustments)
        self.__element_data_and_metadata_dirty = True
        self.__element_data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.__display_data_and_metadata_dirty = True
        self.__display_data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.__normalized_data_and_metadata_dirty = True
        self.__normalized_data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.__adjusted_data_and_metadata_dirty = True
        self.__adjusted_data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.__transformed_data_and_metadata_dirty = True
        self.__transformed_data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.__data_range_dirty = True
        self.__data_range: typing.Optional[typing.Tuple[float, float]] = None
        self.__data_sample_dirty = True
        self.__data_sample: typing.Optional[_ImageDataType] = None
        self.__display_range_dirty = True
        self.__display_range: typing.Optional[typing.Tuple[float, float]] = None
        self.__display_rgba_dirty = True
        self.__display_rgba: typing.Optional[_ImageDataType] = None
        self.__display_rgba_timestamp: typing.Optional[datetime.datetime] = data_and_metadata.timestamp if data_and_metadata else None
        self.__finalized = False
        self.on_finalize: typing.Optional[typing.Callable[[DisplayValues], None]] = None

        def finalize() -> None:
            DisplayValues._count -= 1

        weakref.finalize(self, finalize)

    def finalize(self) -> None:
        with self.__lock:
            self.__finalized = True
        if callable(self.on_finalize):
            self.on_finalize(self)

    @property
    def color_map_data(self) -> typing.Optional[_RGBA32Type]:
        return self.__color_map_data

    @property
    def data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__data_and_metadata

    @property
    def element_data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        with self.__lock:
            if self.__element_data_and_metadata_dirty:
                self.__element_data_and_metadata_dirty = False
                data_and_metadata = self.__data_and_metadata
                if data_and_metadata is not None:
                    timestamp = data_and_metadata.timestamp
                    data_and_metadata, modified = Core.function_element_data_no_copy(data_and_metadata,
                                                                                     self.__sequence_index,
                                                                                     self.__collection_index,
                                                                                     self.__slice_center,
                                                                                     self.__slice_width,
                                                                                     flag16=False)
                    if data_and_metadata:
                        data_and_metadata.data_metadata.timestamp = timestamp
                    self.__element_data_and_metadata = data_and_metadata
            return self.__element_data_and_metadata

    @property
    def display_data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        with self.__lock:
            if self.__display_data_and_metadata_dirty:
                self.__display_data_and_metadata_dirty = False
                data_and_metadata = self.element_data_and_metadata
                if data_and_metadata is not None:
                    timestamp = data_and_metadata.timestamp
                    data_and_metadata, modified = Core.function_scalar_data_no_copy(data_and_metadata, self.__complex_display_type)
                    if data_and_metadata:
                        data_and_metadata.data_metadata.timestamp = timestamp
                    self.__display_data_and_metadata = data_and_metadata
            return self.__display_data_and_metadata

    @property
    def data_range(self) -> typing.Optional[typing.Tuple[float, float]]:
        with self.__lock:
            if self.__data_range_dirty:
                self.__data_range_dirty = False
                display_data_and_metadata = self.display_data_and_metadata
                display_data = display_data_and_metadata.data if display_data_and_metadata else None
                if display_data is not None and display_data.shape and self.__data_and_metadata:
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
    def display_range(self) -> typing.Optional[typing.Tuple[float, float]]:
        with self.__lock:
            if self.__display_range_dirty:
                self.__display_range_dirty = False
                self.__display_range = calculate_display_range(self.__display_limits, self.data_range, self.data_sample, self.__data_and_metadata, self.__complex_display_type)
            return self.__display_range

    @property
    def data_sample(self) -> typing.Optional[_ImageDataType]:
        with self.__lock:
            if self.__data_sample_dirty:
                self.__data_sample_dirty = False
                display_data_and_metadata = self.display_data_and_metadata
                display_data = display_data_and_metadata.data if display_data_and_metadata else None
                if display_data is not None and display_data.shape and self.__data_and_metadata:
                    data_shape = self.__data_and_metadata.data_shape
                    data_dtype = self.__data_and_metadata.data_dtype
                    if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
                        self.__data_sample = None
                    elif Image.is_shape_and_dtype_complex_type(data_shape, data_dtype):
                        self.__data_sample = numpy.sort(numpy.random.choice(display_data.reshape(numpy.product(display_data.shape, dtype=numpy.uint64)), 200))  # type: ignore
                    else:
                        self.__data_sample = None
                else:
                    self.__data_sample = None
            return self.__data_sample

    @property
    def display_rgba(self) -> typing.Optional[_ImageDataType]:
        with self.__lock:
            if self.__display_rgba_dirty:
                self.__display_rgba_dirty = False
                display_data = self.adjusted_data_and_metadata
                if display_data is not None and self.__data_and_metadata is not None:
                    if self.data_range is not None:  # workaround until validating and retrieving data stats is an atomic operation
                        # display_range is just display_limits but calculated if display_limits is None
                        display_range = self.transformed_display_range
                        display_rgba = Core.function_display_rgba(display_data, display_range, self.__color_map_data)
                        self.__display_rgba = display_rgba.data if display_rgba else None
            return self.__display_rgba

    @property
    def display_rgba_timestamp(self) -> typing.Optional[datetime.datetime]:
        return self.__display_rgba_timestamp

    @property
    def normalized_data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        with self.__lock:
            if self.__normalized_data_and_metadata_dirty:
                self.__normalized_data_and_metadata_dirty = False
                display_data_and_metadata = self.display_data_and_metadata
                display_range = self.display_range
                if display_range is not None and display_data_and_metadata:
                    display_limit_low, display_limit_high = display_range
                    # normalize the data to [0, 1].
                    m = 1 / (display_limit_high - display_limit_low) if display_limit_high != display_limit_low else 0.0
                    b = -display_limit_low
                    self.__normalized_data_and_metadata = float(m) * (display_data_and_metadata + float(b))
            return self.__normalized_data_and_metadata

    @property
    def adjusted_data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        with self.__lock:
            if self.__adjusted_data_and_metadata_dirty:
                self.__adjusted_data_and_metadata_dirty = False
                if self.__adjustments:
                    display_xdata = self.normalized_data_and_metadata
                    for adjustment_d in self.__adjustments:
                        adjustment = adjustment_factory(adjustment_d)
                        if adjustment:
                            display_range = self.display_range
                            if display_xdata and display_range is not None:
                                display_data = display_xdata.data
                                if display_data is not None:
                                    display_xdata = DataAndMetadata.new_data_and_metadata(adjustment.transform(display_data, display_range))
                    self.__adjusted_data_and_metadata = display_xdata
                else:
                    self.__adjusted_data_and_metadata = self.display_data_and_metadata
            return self.__adjusted_data_and_metadata

    @property
    def adjusted_display_range(self) -> typing.Optional[typing.Tuple[float, float]]:
        if self.__adjustments:
            # transforms have already been applied and data is now in the range of 0.0, 1.0.
            # brightness and contrast will be applied on top of this transform.
            return 0.0, 1.0
        else:
            return self.display_range

    @property
    def transformed_data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        with self.__lock:
            if self.__transformed_data_and_metadata_dirty:
                self.__transformed_data_and_metadata_dirty = False
                adjusted_xdata = self.adjusted_data_and_metadata
                if adjusted_xdata:
                    self.__transformed_data_and_metadata = Core.function_rescale(adjusted_xdata, data_range=(0.0, 1.0), in_range=self.transformed_display_range)
                else:
                    self.__transformed_data_and_metadata = None
            return self.__transformed_data_and_metadata

    @property
    def transformed_display_range(self) -> typing.Tuple[float, float]:
        adjusted_display_range = self.adjusted_display_range
        assert adjusted_display_range is not None
        display_limit_low, display_limit_high = adjusted_display_range
        brightness = self.__brightness
        contrast = self.__contrast
        m = (contrast / (display_limit_high - display_limit_low)) if contrast > 0 and display_limit_high != display_limit_low else 1
        b = 1 / (2 * m) - (1 - brightness) * (display_limit_high - display_limit_low) / 2 - display_limit_low
        # back calculate the display limits as they would be would be with brightness/contrast adjustments
        return (0 - m * b) / m, (1 - m * b) / m


class DisplayDataChannel(Persistence.PersistentObject):
    def __init__(self, data_item: typing.Optional[DataItem.DataItem] = None) -> None:
        super().__init__()

        self.define_type("display_data_channel")
        # conversion to scalar
        self.define_property("complex_display_type", changed=self.__property_changed, hidden=True)
        # data scaling and color (raster)
        self.define_property("display_limits", validate=self.__validate_display_limits, changed=self.__property_changed, hidden=True)
        self.define_property("color_map_id", changed=self.__color_map_id_changed, hidden=True)
        self.define_property("brightness", 0.0, changed=self.__property_changed, hidden=True)
        self.define_property("contrast", 1.0, changed=self.__property_changed, hidden=True)
        self.define_property("adjustments", list(), copy_on_read=True, changed=self.__property_changed, hidden=True)
        # slicing data to 1d or 2d
        self.define_property("sequence_index", 0, validate=self.__validate_sequence_index, changed=self.__property_changed, hidden=True)
        self.define_property("collection_index", (0, 0, 0), validate=self.__validate_collection_index, changed=self.__collection_index_changed, hidden=True)
        self.define_property("slice_center", 0, validate=self.__validate_slice_center, changed=self.__slice_interval_changed, hidden=True)
        self.define_property("slice_width", 1, validate=self.__validate_slice_width, changed=self.__slice_interval_changed, hidden=True)
        self.define_property("data_item_reference", str(data_item.uuid) if data_item else None, changed=self.__data_item_reference_changed, hidden=True)

        # # last display values is the last one to be fully displayed.
        # # when the current display values makes it all the way to display, it will invoke the finalize method.
        # # the display_data_channel will listen for that event and update last display values.
        self.__last_display_values: typing.Optional[DisplayValues] = None
        self.__current_display_values: typing.Optional[DisplayValues] = None
        self.__current_data_item: typing.Optional[DataItem.DataItem] = None
        self.__current_data_item_modified_count = 0
        self.__is_master = True
        self.__display_ref_count = 0

        self.__slice_interval: typing.Optional[typing.Tuple[float, float]] = None

        data_item_specifier = Persistence.read_persistent_specifier(self.data_item_reference) if self.data_item_reference else None
        self.__data_item_reference = self.create_item_reference(item_specifier=data_item_specifier, item=data_item)

        self.__old_data_shape: typing.Optional[DataAndMetadata.ShapeType] = None

        self.__color_map_data: typing.Optional[_RGBA32Type] = None
        self.modified_state = 0

        self.display_values_changed_event = Event.Event()
        self.display_data_will_change_event = Event.Event()
        self.data_item_proxy_changed_event = Event.Event()
        self.__calculated_display_values_available_event = Event.Event()

        self.data_item_will_change_event = Event.Event()
        self.data_item_did_change_event = Event.Event()
        self.data_item_changed_event = Event.Event()
        self.data_item_description_changed_event = Event.Event()

        self.__data_item_property_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.__data_item_will_change_listener: typing.Optional[Event.EventListener] = None
        self.__data_item_did_change_listener: typing.Optional[Event.EventListener] = None
        self.__data_item_item_changed_listener: typing.Optional[Event.EventListener] = None
        self.__data_item_data_item_changed_listener: typing.Optional[Event.EventListener] = None
        self.__data_item_data_changed_listener: typing.Optional[Event.EventListener] = None
        self.__data_item_description_changed_listener: typing.Optional[Event.EventListener] = None

        self.__last_data_item: typing.Optional[DataItem.DataItem] = None

        def connect_data_item(data_item_: typing.Optional[Persistence.PersistentObject]) -> None:
            data_item = typing.cast(DataItem.DataItem, data_item_)
            self.__disconnect_data_item_events()
            if self.__last_data_item:
                for _ in range(self.__display_ref_count):
                    self.__last_data_item.decrement_data_ref_count()
            self.__connect_data_item_events()
            self.__validate_slice_indexes()
            # tell the data item that this display data channel is referencing it
            if data_item:
                data_item.add_display_data_channel(self)
            if self.__data_item:
                for _ in range(self.__display_ref_count):
                    self.__data_item.increment_data_ref_count()
            self.__last_data_item = self.__data_item
            self.data_item_proxy_changed_event.fire()

        def disconnect_data_item(data_item_: typing.Optional[Persistence.PersistentObject]) -> None:
            data_item = typing.cast(DataItem.DataItem, data_item_)
            # tell the data item that this display data channel is no longer referencing it
            if data_item:
                data_item.remove_display_data_channel(self)

        self.__data_item_reference.on_item_registered = connect_data_item
        self.__data_item_reference.on_item_unregistered = disconnect_data_item

        if self.__data_item_reference.item:
            connect_data_item(typing.cast(DataItem.DataItem, self.__data_item_reference.item))

    def close(self) -> None:
        self.__disconnect_data_item_events()
        self.__current_display_values = None
        self.__last_display_values = None
        self.__current_data_item = None
        super().close()

    def about_to_be_inserted(self, container: Persistence.PersistentObject) -> None:
        super().about_to_be_inserted(container)
        self.notify_property_changed("display_item")  # used for implicit connections

    def about_to_be_removed(self, container: Persistence.PersistentObject) -> None:
        # tell the data item that this display data channel is no longer referencing it
        if self.__data_item:
            self.__data_item.remove_display_data_channel(self)
        self.notify_property_changed("display_item")  # used for implicit connections
        super().about_to_be_removed(container)

    @property
    def complex_display_type(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("complex_display_type"))

    @complex_display_type.setter
    def complex_display_type(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("complex_display_type", value)

    @property
    def display_limits(self) -> DisplayLimitsType:
        return typing.cast(DisplayLimitsType, self._get_persistent_property_value("display_limits"))

    @display_limits.setter
    def display_limits(self, value: DisplayLimitsType) -> None:
        self._set_persistent_property_value("display_limits", value)

    @property
    def color_map_id(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("color_map_id"))

    @color_map_id.setter
    def color_map_id(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("color_map_id", value)

    @property
    def brightness(self) -> float:
        return typing.cast(float, self._get_persistent_property_value("brightness"))

    @brightness.setter
    def brightness(self, value: float) -> None:
        self._set_persistent_property_value("brightness", value)

    @property
    def contrast(self) -> float:
        return typing.cast(float, self._get_persistent_property_value("contrast"))

    @contrast.setter
    def contrast(self, value: float) -> None:
        self._set_persistent_property_value("contrast", value)

    @property
    def sequence_index(self) -> int:
        return typing.cast(int, self._get_persistent_property_value("sequence_index"))

    @sequence_index.setter
    def sequence_index(self, value: int) -> None:
        self._set_persistent_property_value("sequence_index", value)

    @property
    def collection_index(self) -> typing.Tuple[int, ...]:
        return typing.cast(typing.Tuple[int, ...], self._get_persistent_property_value("collection_index"))

    @collection_index.setter
    def collection_index(self, value: typing.Tuple[int, ...]) -> None:
        self._set_persistent_property_value("collection_index", value)

    @property
    def slice_center(self) -> int:
        return typing.cast(int, self._get_persistent_property_value("slice_center"))

    @slice_center.setter
    def slice_center(self, value: int) -> None:
        self._set_persistent_property_value("slice_center", value)

    @property
    def slice_width(self) -> int:
        return typing.cast(int, self._get_persistent_property_value("slice_width"))

    @slice_width.setter
    def slice_width(self, value: int) -> None:
        self._set_persistent_property_value("slice_width", value)

    @property
    def adjustments(self) -> typing.Sequence[Persistence.PersistentDictType]:
        return typing.cast(typing.Sequence[Persistence.PersistentDictType], self._get_persistent_property_value("adjustments"))

    @adjustments.setter
    def adjustments(self, value: typing.Sequence[Persistence.PersistentDictType]) -> None:
        self._set_persistent_property_value("adjustments", value)

    @property
    def data_item_reference(self) -> str:
        return typing.cast(str, self._get_persistent_property_value("data_item_reference"))

    @data_item_reference.setter
    def data_item_reference(self, value: str) -> None:
        self._set_persistent_property_value("data_item_reference", value)

    @property
    def display_item(self) -> DisplayItem:
        return typing.cast(DisplayItem, self.container)

    def __deepcopy__(self, memo: typing.Dict[typing.Any, typing.Any]) -> DisplayDataChannel:
        display_data_channel = self.__class__()
        display_data_channel._set_persistent_property_value("complex_display_type", self._get_persistent_property_value("complex_display_type"))
        display_data_channel._set_persistent_property_value("display_limits", self._get_persistent_property_value("display_limits"))
        display_data_channel._set_persistent_property_value("color_map_id", self._get_persistent_property_value("color_map_id"))
        display_data_channel._set_persistent_property_value("brightness", self._get_persistent_property_value("brightness"))
        display_data_channel._set_persistent_property_value("contrast", self._get_persistent_property_value("contrast"))
        display_data_channel._set_persistent_property_value("adjustments", self._get_persistent_property_value("adjustments"))
        display_data_channel._set_persistent_property_value("sequence_index", self._get_persistent_property_value("sequence_index"))
        display_data_channel._set_persistent_property_value("collection_index", self._get_persistent_property_value("collection_index"))
        display_data_channel._set_persistent_property_value("slice_center", self._get_persistent_property_value("slice_center"))
        display_data_channel._set_persistent_property_value("slice_width", self._get_persistent_property_value("slice_width"))
        display_data_channel._set_persistent_property_value("data_item_reference", self._get_persistent_property_value("data_item_reference"))
        if self.__data_item and self.__data_item.uuid == uuid.UUID(self._get_persistent_property_value("data_item_reference")):
            # setting the item here allows it to be used to determine the project
            # so that the new item can be added to the same project. however, it
            # also prevents the item_registered call from happening; so do it
            # explicitly here.
            display_data_channel.__data_item_reference.item = self.__data_item
            if callable(display_data_channel.__data_item_reference.on_item_registered):
                display_data_channel.__data_item_reference.on_item_registered(self.__data_item)
        memo[id(self)] = display_data_channel
        return display_data_channel

    @property
    def project(self) -> typing.Optional[Project.Project]:
        return typing.cast("Project.Project", self.container.container) if self.container else None

    def create_proxy(self) -> Persistence.PersistentObjectProxy[DisplayDataChannel]:
        project = self.project
        assert project
        return project.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(self.uuid)

    def clone(self) -> DisplayDataChannel:
        display_data_channel = DisplayDataChannel()
        display_data_channel.uuid = self.uuid
        return display_data_channel

    def copy_display_data_properties_from(self, display_data_channel: DisplayDataChannel) -> None:
        self.complex_display_type = display_data_channel.complex_display_type
        self.display_limits = display_data_channel.display_limits
        self.brightness = display_data_channel.brightness
        self.contrast = display_data_channel.contrast
        self.adjustments = display_data_channel.adjustments
        self.color_map_id = display_data_channel.color_map_id
        self.sequence_index = display_data_channel.sequence_index
        self.collection_index = display_data_channel.collection_index
        self.slice_center = display_data_channel.slice_center
        self.slice_width = display_data_channel.slice_width

    @property
    def __data_item(self) -> typing.Optional[DataItem.DataItem]:
        return typing.cast(typing.Optional[DataItem.DataItem], self.__data_item_reference.item)

    def __data_item_reference_changed(self, name: str, data_item_reference: str) -> None:
        if data_item_reference:
            item_uuid = uuid.UUID(data_item_reference)
            self.__data_item_reference.item_specifier = Persistence.read_persistent_specifier(item_uuid)
        self.__current_display_values = None

    def __connect_data_item_events(self) -> None:

        def property_changed(property_name: str) -> None:
            self.modified_state += 1

        def data_changed() -> None:
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

    def __disconnect_data_item_events(self) -> None:
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

    @property
    def data_item(self) -> typing.Optional[DataItem.DataItem]:
        return self.__data_item

    @property
    def created_local_as_string(self) -> typing.Optional[str]:
        return self.__data_item.created_local_as_string if self.__data_item else None

    @property
    def size_and_data_format_as_string(self) -> typing.Optional[str]:
        return self.__data_item.size_and_data_format_as_string if self.__data_item else None

    @property
    def has_valid_data(self) -> bool:
        data_item = self.data_item
        display_data_shape = self.display_data_shape
        return (data_item is not None) and (functools.reduce(operator.mul, display_data_shape) > 0 if display_data_shape else False)

    @property
    def display_data_shape(self) -> typing.Optional[typing.Tuple[int, ...]]:
        data_item = self.__data_item
        if not data_item:
            return None
        dimensional_shape = data_item.dimensional_shape
        next_dimension = 0
        if data_item.is_sequence:
            next_dimension += 1
        if data_item.is_collection:
            collection_dimension_count = data_item.collection_dimension_count
            datum_dimension_count = data_item.datum_dimension_count
            # next dimensions are treated as collection indexes.
            if collection_dimension_count == 2 and datum_dimension_count == 1:
                return tuple(dimensional_shape[next_dimension:next_dimension + collection_dimension_count])
            else:  # default, "pick"
                return tuple(dimensional_shape[next_dimension + collection_dimension_count:next_dimension + collection_dimension_count + datum_dimension_count])
        else:
            return tuple(dimensional_shape[next_dimension:])

    def get_display_position_as_data_position(self, pos: typing.Tuple[int, ...]) -> typing.Tuple[int, ...]:
        data_item = self.__data_item
        if data_item:
            data_and_metadata = data_item.xdata
            if data_and_metadata:
                is_sequence = data_and_metadata.is_sequence
                collection_dimension_count = data_and_metadata.collection_dimension_count
                datum_dimension_count = data_and_metadata.datum_dimension_count
                if is_sequence:
                    pos = (self.sequence_index, ) + pos
                if self.is_sliced:
                    pos = pos + (self.slice_center, )
                else:
                    # reduce collection dimensions for case where 2 pos dimensions are supplied on 1 pos datum (line plot display as image)
                    non_collection_dimension_count = datum_dimension_count + (1 if is_sequence else 0)
                    collection_dimension_count -= len(pos) - non_collection_dimension_count
                    # adjust position for collection dimensions
                    pos = tuple(self.collection_index[0:collection_dimension_count]) + pos
                while len(pos) < data_and_metadata.datum_dimension_count:
                    pos = (0,) + tuple(pos)
                assert len(pos) == len(data_and_metadata.dimensional_shape)
        return pos

    @property
    def dimensional_shape(self) -> typing.Optional[typing.Tuple[int, ...]]:
        return self.__data_item.dimensional_shape if self.__data_item else None

    @property
    def is_sequence(self) -> bool:
        return self.__data_item.is_sequence if self.__data_item else False

    @property
    def is_collection(self) -> bool:
        return self.__data_item.is_collection if self.__data_item else False

    @property
    def is_sliced(self) -> bool:
        return self.__data_item.is_collection and self.__data_item.collection_dimension_count == 2 and self.__data_item.datum_dimension_count == 1 if self.__data_item else False

    @property
    def datum_rank(self) -> int:
        return self.__data_item.datum_dimension_count if self.__data_item else 0

    @property
    def collection_rank(self) -> int:
        return self.__data_item.collection_dimension_count if self.__data_item else 0

    @property
    def is_display_1d_preferred(self) -> bool:
        data_item = self.data_item
        if not data_item:
            return False
        if data_item.collection_dimension_count == 2 and data_item.datum_dimension_count == 1:
            return False
        return data_item.datum_dimension_count == 1 or (data_item.datum_dimension_count == 2 and data_item.datum_dimension_shape[0] == 1)

    @property
    def is_display_2d_preferred(self) -> bool:
        data_item = self.data_item
        if not data_item:
            return False
        display_data_shape = self.display_data_shape
        if data_item.collection_dimension_count == 2 and data_item.datum_dimension_count == 1:
            return True
        elif display_data_shape is not None and len(display_data_shape) == 2 and not self.is_display_1d_preferred:
            return True
        return False

    def get_datum_calibrations(self, dimensional_calibrations: typing.Sequence[Calibration.Calibration]) -> typing.Optional[typing.Sequence[Calibration.Calibration]]:
        if self.__data_item:
            next_dimension = 0
            if self.__data_item.is_sequence:
                next_dimension += 1
            if self.__data_item.is_collection:
                collection_dimension_count = self.__data_item.collection_dimension_count
                datum_dimension_count = self.__data_item.datum_dimension_count
                # next dimensions are treated as collection indexes.
                if collection_dimension_count == 2 and datum_dimension_count == 1:
                    return dimensional_calibrations[next_dimension:next_dimension + collection_dimension_count]
                else:  # default, "pick"
                    return dimensional_calibrations[next_dimension + collection_dimension_count:next_dimension + collection_dimension_count + datum_dimension_count]
            else:
                return dimensional_calibrations[next_dimension:]
        return None

    @property
    def datum_calibrations(self) -> typing.Optional[typing.Sequence[Calibration.Calibration]]:
        """The calibrations for only datum dimensions."""
        return self.get_datum_calibrations(self.__data_item.dimensional_calibrations) if self.__data_item else None

    def get_data_value(self, pos: DataAndMetadata.ShapeType) -> typing.Any:
        return self.__data_item.get_data_value(pos) if self.__data_item else None

    def _get_data_metadata(self) -> typing.Optional[DataAndMetadata.DataMetadata]:
        return self.__data_item.data_metadata if self.__data_item else None

    def __validate_display_limits(self, value: typing.Any) -> DisplayLimitsType:
        if value is not None:
            # convert any number to its numpy equivalent using numpy.array() and then convert back to Python using item()
            value = list(numpy.array(v).item() if v is not None else None for v in value)
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

    @property
    def collection_point(self) -> typing.Optional[Geometry.FloatPoint]:
        data_metadata = self._get_data_metadata()
        if data_metadata and data_metadata.collection_dimension_count == 2:
            return Geometry.FloatPoint(y=self.collection_index[0] / data_metadata.collection_dimension_shape[0],
                                       x=self.collection_index[1] / data_metadata.collection_dimension_shape[1])
        return None

    @collection_point.setter
    def collection_point(self, collection_point_: Geometry.FloatPointTuple) -> None:
        collection_point = Geometry.FloatPoint.make(collection_point_)
        data_metadata = self._get_data_metadata()
        if data_metadata and data_metadata.collection_dimension_count == 2:
            self.collection_index = (round(collection_point.y * data_metadata.collection_dimension_shape[0]),
                                     round(collection_point.x * data_metadata.collection_dimension_shape[1]))

    def __collection_index_changed(self, name: str, value: typing.Tuple[int, ...]) -> None:
        # notify for dependent slice_interval property
        self.__property_changed(name, value)
        self.notify_property_changed("collection_point")

    def __validate_collection_index(self, value: typing.Tuple[int, ...]) -> typing.Tuple[int, ...]:
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

    def __validate_slice_center_for_width(self, value: int, slice_width: int) -> int:
        data_metadata = self._get_data_metadata()
        if data_metadata and len(data_metadata.dimensional_shape) > 0:
            depth = data_metadata.dimensional_shape[-1]
            mn = max(int(slice_width * 0.5), 0)
            mx = min(int(depth - slice_width * 0.5), depth - 1)
            return min(max(int(value), mn), mx)
        return value if self._is_reading else 0

    def __validate_slice_center(self, value: int) -> int:
        return self.__validate_slice_center_for_width(value, self.slice_width)

    def __validate_slice_width(self, value: int) -> int:
        data_metadata = self._get_data_metadata()
        if data_metadata and len(data_metadata.dimensional_shape) > 0:
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
        if collection_index != tuple(self.collection_index):
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
    def slice_interval(self) -> typing.Optional[typing.Tuple[float, float]]:
        data_metadata = self._get_data_metadata()
        if data_metadata and len(data_metadata.dimensional_shape) > 0:
            depth = data_metadata.dimensional_shape[-1]  # signal_index
            if depth > 0:
                slice_interval_start = round(self.slice_center - self.slice_width * 0.5)
                slice_interval_end = slice_interval_start + self.slice_width
                return (float(slice_interval_start) / depth, float(slice_interval_end) / depth)
            return 0.0, 0.0
        return None

    @slice_interval.setter
    def slice_interval(self, slice_interval: typing.Tuple[float, float]) -> None:
        data_metadata = self._get_data_metadata()
        if data_metadata is not None and len(data_metadata.dimensional_shape) > 0:
            depth = data_metadata.dimensional_shape[-1]  # signal_index
            if depth > 0:
                slice_interval_center = round(((slice_interval[0] + slice_interval[1]) * 0.5) * depth)
                slice_interval_width = round((slice_interval[1] - slice_interval[0]) * depth)
                self.slice_center = slice_interval_center
                self.slice_width = slice_interval_width

    def __slice_interval_changed(self, name: str, value: typing.Optional[typing.Tuple[float, float]]) -> None:
        # notify for dependent slice_interval property
        self.__property_changed(name, value)
        self.notify_property_changed("slice_interval")
        self.__slice_interval = self.slice_interval

    def __color_map_id_changed(self, property_name: str, value: typing.Optional[str]) -> None:
        if value:
            self.__color_map_data = ColorMaps.get_color_map_data_by_id(value)
        else:
            self.__color_map_data = None
        self.__property_changed(property_name, value)
        self.__property_changed("color_map_data", self.__color_map_data)

    @property
    def color_map_data(self) -> typing.Optional[_RGBA32Type]:
        """Return the color map data as a uint8 ndarray with shape (256, 3)."""
        if self.display_data_shape is None:  # is there display data?
            return None
        else:
            return self.__color_map_data if self.__color_map_data is not None else ColorMaps.get_color_map_data_by_id("grayscale")

    def __property_changed(self, property_name: str, value: typing.Any) -> None:
        # when one of the defined properties changes, this gets called
        self.notify_property_changed(property_name)
        if property_name in ("sequence_index", "collection_index", "slice_center", "slice_width", "complex_display_type", "display_limits", "brightness", "contrast", "adjustments", "color_map_data"):
            self.display_data_will_change_event.fire()
            self.__current_display_values = None
            self.__send_next_calculated_display_values()

    def save_properties(self) -> typing.Tuple[typing.Any, ...]:
        return (
            self.complex_display_type,
            self.display_limits,
            self.brightness,
            self.contrast,
            self.adjustments,
            self.color_map_id,
            self.sequence_index,
            self.collection_index,
            self.slice_center,
            self.slice_interval,
        )

    def restore_properties(self, properties: typing.Tuple[typing.Any, ...]) -> None:
        self.complex_display_type = properties[0]
        self.display_limits = properties[1]
        self.brightness = properties[2]
        self.contrast = properties[3]
        self.adjustments = properties[4]
        self.color_map_id = properties[5]
        self.sequence_index = properties[6]
        self.collection_index = properties[7]
        self.slice_center = properties[8]
        self.slice_interval = properties[9]

    def update_display_data(self) -> None:
        if self.__data_item != self.__current_data_item or (self.__data_item and self.__data_item.modified_count != self.__current_data_item_modified_count):
            self.__current_display_values = None
            self.__send_next_calculated_display_values()

    def add_calculated_display_values_listener(self, callback: typing.Callable[[], None], send: bool = True) -> Event.EventListener:
        listener = self.__calculated_display_values_available_event.listen(callback)
        if send:
            self.__send_next_calculated_display_values()
        return listener

    def __send_next_calculated_display_values(self) -> None:
        """Fire event to signal new display values are available."""
        self.__calculated_display_values_available_event.fire()

    def get_calculated_display_values(self, immediate: bool=False) -> typing.Optional[DisplayValues]:
        """Return the display values.

        Return the current (possibly not calculated) display values unless 'immediate' is specified.

        If 'immediate', return the existing (calculated) values if they exist. Using the 'immediate' values
        avoids calculation except in cases where the display values haven't already been calculated.
        """
        if not immediate or not self.__is_master or not self.__last_display_values:
            if not self.__current_display_values and self.__data_item:
                self.__current_data_item = self.__data_item
                self.__current_data_item_modified_count = self.__data_item.modified_count if self.__data_item else 0
                self.__current_display_values = DisplayValues(self.__data_item.xdata, self.sequence_index, self.collection_index, self.slice_center, self.slice_width, self.display_limits, self.complex_display_type, self.__color_map_data, self.brightness, self.contrast, self.adjustments)
                self.__current_display_values.on_finalize = ReferenceCounting.weak_partial(DisplayDataChannel.__finalize, self)
            return self.__current_display_values
        return self.__last_display_values

    def __finalize(self, display_values: DisplayValues) -> None:
        self.__last_display_values = display_values
        self.display_values_changed_event.fire()

    def increment_display_ref_count(self, amount: int = 1) -> None:
        """Increment display reference count to indicate this library item is currently displayed."""
        display_ref_count = self.__display_ref_count
        self.__display_ref_count += amount
        if display_ref_count == 0:
            self.__is_master = True
        if self.__data_item:
            for _ in range(amount):
                self.__data_item.increment_data_ref_count()

    def decrement_display_ref_count(self, amount: int = 1) -> None:
        """Decrement display reference count to indicate this library item is no longer displayed."""
        assert not self._closed
        self.__display_ref_count -= amount
        if self.__display_ref_count == 0:
            self.__is_master = False
        if self.__data_item:
            for _ in range(amount):
                self.__data_item.decrement_data_ref_count()

    @property
    def _display_ref_count(self) -> int:
        return self.__display_ref_count

    def reset_display_limits(self) -> None:
        """Reset display limits so that they are auto calculated whenever the data changes."""
        self.display_limits = None

    def auto_display_limits(self) -> None:
        """Calculate best display limits and set them."""
        display_values = self.get_calculated_display_values()
        display_data_and_metadata = display_values.display_data_and_metadata if display_values else None
        data = display_data_and_metadata.data if display_data_and_metadata else None
        if data is not None:
            # The old algorithm was a problem during EELS where the signal data
            # is a small percentage of the overall data and was falling outside
            # the included range. This is the new simplified algorithm. Future
            # feature may allow user to select more complex algorithms.
            mn, mx = numpy.array(numpy.nanmin(data)).item(), numpy.array(numpy.nanmax(data)).item()  # type: ignore
            self.display_limits = mn, mx


def display_data_channel_factory(lookup_id: typing.Callable[[str], str]) -> DisplayDataChannel:
    return DisplayDataChannel()


class DisplayLayer(Schema.Entity):
    def __init__(self) -> None:
        super().__init__(Model.DisplayLayer)
        self.persistent_storage = None
        self.display_data_channel: typing.Optional[DisplayDataChannel] = None

    @property
    def display_item(self) -> DisplayItem:
        return typing.cast(DisplayItem, self.container)

    def _create(self, context: typing.Optional[Schema.EntityContext]) -> Schema.Entity:
        display_layer = DisplayLayer()
        if context:
            display_layer._set_entity_context(context)
        return display_layer

    @property
    def label(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_field_value("label"))

    @label.setter
    def label(self, value: typing.Optional[str]) -> None:
        self._set_field_value("label", value)

    @property
    def data_row(self) -> typing.Optional[int]:
        return typing.cast(typing.Optional[int], self._get_field_value("data_row"))

    @data_row.setter
    def data_row(self, value: typing.Optional[int]) -> None:
        self._set_field_value("data_row", value)

    @property
    def stroke_color(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_field_value("stroke_color"))

    @stroke_color.setter
    def stroke_color(self, value: typing.Optional[str]) -> None:
        self._set_field_value("stroke_color", value)

    @property
    def fill_color(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_field_value("fill_color"))

    @fill_color.setter
    def fill_color(self, value: typing.Optional[str]) -> None:
        self._set_field_value("fill_color", value)

    @property
    def stroke_width(self) -> typing.Optional[float]:
        return typing.cast(typing.Optional[float], self._get_field_value("stroke_width"))

    @stroke_width.setter
    def stroke_width(self, value: typing.Optional[float]) -> None:
        self._set_field_value("stroke_width", value)

    # standard overrides from entity to fit within persistent object architecture

    def _field_value_changed(self, name: str, value: typing.Any) -> None:
        # this is called when a property changes. to be compatible with the older
        # persistent object structure, check if persistent storage exists and pass
        # the message along to persistent storage.
        persistent_storage = typing.cast(Persistence.PersistentStorageInterface, getattr(self, "persistent_storage", None))
        if persistent_storage:
            if value is not None:
                persistent_storage.set_property(typing.cast(Persistence.PersistentObject, self), name, value)
            else:
                persistent_storage.clear_property(typing.cast(Persistence.PersistentObject, self), name)


def display_layer_factory(lookup_id: typing.Callable[[str], str]) -> DisplayLayer:
    return DisplayLayer()


class DisplayItem(Persistence.PersistentObject):
    DEFAULT_COLORS = ("#1E90FF", "#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#00FFFF", "#FF00FF", "#888888", "#880000", "#008800", "#000088", "#CCCCCC", "#888800", "#008888", "#880088", "#964B00")

    def __init__(self, item_uuid: typing.Optional[uuid.UUID] = None, *, data_item: typing.Optional[DataItem.DataItem] = None) -> None:
        super().__init__()
        if item_uuid:
            self.uuid = item_uuid
        self.define_type("display_item")
        self.define_property("created", DataItem.DataItem.utcnow(), hidden=True, converter=DataItem.DatetimeToStringConverter(), changed=self.__property_changed)
        self.define_property("display_type", hidden=True, changed=self.__display_type_changed)
        self.define_property("title", hidden=True, changed=self.__property_changed)
        self.define_property("caption", hidden=True, changed=self.__property_changed)
        self.define_property("description", hidden=True, changed=self.__property_changed)
        self.define_property("session_id", hidden=True, changed=self.__property_changed)
        self.define_property("calibration_style_id", "calibrated", hidden=True, changed=self.__property_changed)
        self.define_property("display_properties", dict(), hidden=True, copy_on_read=True, changed=self.__display_properties_changed)
        self.define_relationship("graphics", Graphics.factory, insert=self.__insert_graphic, remove=self.__remove_graphic, hidden=True)
        self.define_relationship("display_layers", typing.cast(Persistence._PersistentObjectFactoryFn, display_layer_factory), insert=self.__insert_display_layer, remove=self.__remove_display_layer, hidden=True)
        self.define_relationship("display_data_channels", display_data_channel_factory, insert=self.__insert_display_data_channel, remove=self.__remove_display_data_channel, hidden=True)

        self.__display_data_channel_property_changed_event_listeners: typing.List[Event.EventListener] = list()
        self.__display_data_channel_data_item_will_change_event_listeners: typing.List[Event.EventListener] = list()
        self.__display_data_channel_data_item_did_change_event_listeners: typing.List[Event.EventListener] = list()
        self.__display_data_channel_data_item_changed_event_listeners: typing.List[Event.EventListener] = list()
        self.__display_data_channel_data_item_description_changed_event_listeners: typing.List[Event.EventListener] = list()
        self.__display_data_channel_data_item_proxy_changed_event_listeners: typing.List[Event.EventListener] = list()

        self.display_property_changed_event = Event.Event()
        self.display_changed_event = Event.Event()

        self.__cache = Cache.ShadowCache()
        self.__suspendable_storage_cache: typing.Optional[Cache.CacheLike] = None

        self.__in_transaction_state = False
        self.__write_delay_modified_count = 0

        # some async methods (cursor info) may run in a thread. these two variables allow the display item to
        # prevent closing until any outstanding threads that access this object are finished.
        self.__outstanding_condition = threading.Condition()
        self.__outstanding_thread_count = 0

        # the most recent data to be displayed. should have immediate data available.
        self.__is_composite_data = False
        self.__dimensional_calibrations: typing.Optional[DataAndMetadata.CalibrationListType] = None
        self.__intensity_calibration: typing.Optional[Calibration.Calibration] = None
        self.__dimensional_shape: typing.Optional[DataAndMetadata.ShapeType] = None
        self.__scales: typing.Optional[typing.Tuple[float, ...]] = None

        self.__graphic_changed_listeners: typing.List[Event.EventListener] = list()
        self.__display_item_change_count = 0
        self.__display_item_change_count_lock = threading.RLock()
        self.__display_ref_count = 0
        self.graphic_selection = GraphicSelection()
        self.graphic_selection_changed_event = Event.Event()
        self.graphics_changed_event = Event.Event()
        self.display_values_changed_event = Event.Event()
        self.item_changed_event = Event.Event()

        def graphic_selection_changed() -> None:
            # relay the message
            self.graphic_selection_changed_event.fire(self.graphic_selection)
            self.graphics_changed_event.fire(self.graphic_selection)

        self.__graphic_selection_changed_event_listener = self.graphic_selection.changed_event.listen(graphic_selection_changed)

        if data_item:
            self.append_display_data_channel_for_data_item(data_item)

    def close(self) -> None:
        # wait for outstanding threads to finish
        with self.__outstanding_condition:
            while self.__outstanding_thread_count:
                self.__outstanding_condition.wait()
        self.__graphic_selection_changed_event_listener.close()
        self.__graphic_selection_changed_event_listener = typing.cast(typing.Any, None)
        for display_data_channel in copy.copy(self.display_data_channels):
            self.__disconnect_display_data_channel(display_data_channel, 0)
        for graphic in copy.copy(self.graphics):
            self.__disconnect_graphic(graphic, 0)
        self.graphic_selection = typing.cast(typing.Any, None)
        super().close()

    def __copy__(self) -> DisplayItem:
        assert False

    def __deepcopy__(self, memo: typing.Dict[typing.Any, typing.Any]) -> DisplayItem:
        display_item_copy = self.__class__()
        display_item_copy.display_type = self.display_type
        # metadata
        display_item_copy._set_persistent_property_value("title", self._get_persistent_property_value("title"))
        display_item_copy._set_persistent_property_value("caption", self._get_persistent_property_value("caption"))
        display_item_copy._set_persistent_property_value("description", self._get_persistent_property_value("description"))
        display_item_copy._set_persistent_property_value("session_id", self._get_persistent_property_value("session_id"))
        display_item_copy._set_persistent_property_value("calibration_style_id", self._get_persistent_property_value("calibration_style_id"))
        display_item_copy._set_persistent_property_value("display_properties", self._get_persistent_property_value("display_properties"))
        display_item_copy.created = self.created
        # display data channels
        for display_data_channel in self.display_data_channels:
            display_item_copy.append_display_data_channel(copy.deepcopy(display_data_channel))
        for i, display_layer in enumerate(self.display_layers):
            data_index = self.display_data_channels.index(display_layer.display_data_channel)
            display_data_channel = display_item_copy.display_data_channels[data_index]
            display_item_copy.add_display_layer_for_display_data_channel(display_data_channel, **self.get_display_layer_properties(i))
        # display
        for graphic in self.graphics:
            display_item_copy.add_graphic(copy.deepcopy(graphic))
        memo[id(self)] = display_item_copy
        return display_item_copy

    @property
    def created(self) -> datetime.datetime:
        return typing.cast(datetime.datetime, self._get_persistent_property_value("created"))

    @created.setter
    def created(self, value: datetime.datetime) -> None:
        self._set_persistent_property_value("created", value)

    @property
    def project(self) -> Project.Project:
        return typing.cast("Project.Project", self.container)

    @property
    def display_type(self) -> typing.Optional[str]:
        return typing.cast(typing.Optional[str], self._get_persistent_property_value("display_type"))

    @display_type.setter
    def display_type(self, value: typing.Optional[str]) -> None:
        self._set_persistent_property_value("display_type", value)

    @property
    def calibration_style_id(self) -> str:
        return typing.cast(str, self._get_persistent_property_value("calibration_style_id"))

    @calibration_style_id.setter
    def calibration_style_id(self, value: str) -> None:
        self._set_persistent_property_value("calibration_style_id", value)

    @property
    def display_properties(self) -> Persistence.PersistentDictType:
        return typing.cast(Persistence.PersistentDictType, self._get_persistent_property_value("display_properties"))

    @display_properties.setter
    def display_properties(self, value: Persistence.PersistentDictType) -> None:
        self._set_persistent_property_value("display_properties", value)

    @property
    def graphics(self) -> typing.Sequence[Graphics.Graphic]:
        return typing.cast(typing.Sequence[Graphics.Graphic], self._get_relationship_values("graphics"))

    @property
    def display_layers(self) -> typing.Sequence[DisplayLayer]:
        return typing.cast(typing.Sequence[DisplayLayer], self._get_relationship_values("display_layers"))

    @property
    def display_data_channels(self) -> typing.Sequence[DisplayDataChannel]:
        return typing.cast(typing.Sequence[DisplayDataChannel], self._get_relationship_values("display_data_channels"))

    def create_proxy(self) -> Persistence.PersistentObjectProxy[DisplayItem]:
        return self.project.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(self.uuid)

    # call this when the listeners need to be updated (via data_item_content_changed).
    # Calling this method will send the data_item_content_changed method to each listener by using the method
    # data_item_changes.
    def _notify_display_item_content_changed(self) -> None:
        with self.display_item_changes():
            pass

    # override from storage to watch for changes to this library item. notify observers.
    def notify_property_changed(self, key: str) -> None:
        super().notify_property_changed(key)
        self._notify_display_item_content_changed()

    def __display_type_changed(self, name: str, value: str) -> None:
        self.__property_changed(name, value)
        # the order here is important; display values must come before display changed
        # so that the display canvas item is updated properly.
        self.display_values_changed_event.fire()
        self.display_changed_event.fire()
        self.graphics_changed_event.fire(self.graphic_selection)
        if self.used_display_type == "line_plot":
            if self.display_data_shape and len(self.display_data_shape) == 2:
                for display_layer in self.display_layers:
                    # use the version of remove that does not cascade
                    self.remove_item("display_layers", typing.cast(Persistence.PersistentObject, display_layer))
                for display_data_channel in self.display_data_channels:
                    data_item = display_data_channel.data_item
                    if data_item:
                        for data_row in range(data_item.dimensional_shape[0]):
                            self.__add_display_layer_auto(DisplayLayer(), display_data_channel, data_row)
        else:
            while len(self.display_layers) > 1:
                # use the version of remove that does not cascade
                self.remove_item("display_layers", typing.cast(Persistence.PersistentObject, self.display_layers[-1]))

    def __property_changed(self, name: str, value: typing.Any) -> None:
        self.notify_property_changed(name)
        if name == "title":
            self.notify_property_changed("displayed_title")
        if name == "calibration_style_id":
            self.display_property_changed_event.fire("calibration_style_id")

    def __display_properties_changed(self, name: str, value: typing.Any) -> None:
        self.notify_property_changed(name)

    def clone(self) -> DisplayItem:
        display_item = self.__class__()
        display_item.uuid = self.uuid
        for graphic in self.graphics:
            display_item.add_graphic(graphic.clone())
        return display_item

    def snapshot(self) -> DisplayItem:
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
        for i, display_layer in enumerate(self.display_layers):
            data_index = self.display_data_channels.index(self.get_display_layer_display_data_channel(i))
            display_item.add_display_layer_for_display_data_channel(display_item.display_data_channels[data_index], **self.get_display_layer_properties(i))
        return display_item

    def set_storage_cache(self, storage_cache: Cache.CacheLike) -> None:
        self.__suspendable_storage_cache = Cache.SuspendableCache(storage_cache)
        self.__cache.set_storage_cache(self._suspendable_storage_cache, self)

    @property
    def _suspendable_storage_cache(self) -> typing.Optional[Cache.CacheLike]:
        return self.__suspendable_storage_cache

    @property
    def _display_cache(self) -> Cache.CacheLike:
        return self.__cache

    def read_from_dict(self, properties: Persistence.PersistentDictType) -> None:
        super().read_from_dict(properties)
        if self.created is None:  # invalid timestamp -- set property to now but don't trigger change
            timestamp = datetime.datetime.now()
            self._get_persistent_property("created").value = timestamp

    @property
    def properties(self) -> typing.Optional[Persistence.PersistentDictType]:
        """ Used for debugging. """
        if self.persistent_object_context:
            return self.get_storage_properties()
        return dict()

    @property
    def in_transaction_state(self) -> bool:
        return self.__in_transaction_state

    def __enter_write_delay_state(self) -> None:
        self.__write_delay_modified_count = self.modified_count
        if self.persistent_object_context:
            self.enter_write_delay()

    def __exit_write_delay_state(self) -> None:
        if self.persistent_object_context:
            self.exit_write_delay()
            self._finish_pending_write()

    def _finish_pending_write(self) -> None:
        if self.modified_count > self.__write_delay_modified_count:
            self.rewrite()

    def _transaction_state_entered(self) -> None:
        self.__in_transaction_state = True
        # first enter the write delay state.
        self.__enter_write_delay_state()
        # suspend disk caching
        if self.__suspendable_storage_cache:
            self.__suspendable_storage_cache.suspend_cache()

    def _transaction_state_exited(self) -> None:
        self.__in_transaction_state = False
        # being in the transaction state has the side effect of delaying the cache too.
        # spill whatever was into the local cache into the persistent cache.
        if self.__suspendable_storage_cache:
            self.__suspendable_storage_cache.spill_cache()
        # exit the write delay state.
        self.__exit_write_delay_state()

    def persistent_object_context_changed(self) -> None:
        # handle case where persistent object context is set on an item that is already under transaction.
        # this can occur during acquisition. any other cases?
        super().persistent_object_context_changed()

        if self.__in_transaction_state:
            self.__enter_write_delay_state()

    def get_display_property(self, property_name: str, default_value: typing.Any = None) -> typing.Any:
        return self.display_properties.get(property_name, default_value)

    def set_display_property(self, property_name: str, value: typing.Any) -> None:
        display_properties = self.display_properties
        if display_properties.get(property_name) != value:
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

    def insert_display_layer(self, before_index: int, display_layer: DisplayLayer) -> None:
        self.insert_model_item(self, "display_layers", before_index, typing.cast(Persistence.PersistentObject, display_layer))

    def append_display_layer(self, display_layer: DisplayLayer) -> None:
        self.insert_display_layer(len(self.display_layers), display_layer)

    def __insert_display_layer(self, name: str, before_index: int, display_layer: DisplayLayer) -> None:
        self.notify_insert_item("display_layers", display_layer, before_index)
        self.auto_display_legend()

    def __remove_display_layer(self, name: str, index: int, display_layer: DisplayLayer) -> None:
        self.notify_remove_item("display_layers", display_layer, index)
        self.auto_display_legend()

    @property
    def display_layers_list(self) -> typing.List[Persistence.PersistentDictType]:
        properties = ["data_row", "fill_color", "stroke_color", "label", "stroke_width"]
        l = list()
        for display_layer in self.display_layers:
            d = dict()
            for property in properties:
                value = getattr(display_layer, property, None)
                if value is not None:
                    d[property] = value
            # the check for display data channel still being in display data channels is a hack needed because the
            # removal of a display layer can cascade remove a display data channel and leave the display data channel
            # of the display layer dangling during the cascade. hack it here.
            if display_layer.display_data_channel and display_layer.display_data_channel in self.display_data_channels:
                d["data_index"] = self.display_data_channels.index(display_layer.display_data_channel)
            l.append(d)
        return l

    @display_layers_list.setter
    def display_layers_list(self, value: typing.List[Persistence.PersistentDictType]) -> None:
        assert len(value) == len(self.display_layers)
        properties = ["data_row", "fill_color", "stroke_color", "label", "stroke_width"]
        for index, (display_layer, display_layer_dict) in enumerate(zip(self.display_layers, value)):
            for property in properties:
                if not property in display_layer_dict:
                    display_layer_dict[property] = None
            self._set_display_layer_properties(index, **display_layer_dict)

    def get_display_layer_property(self, index: int, property_name: str, default_value: typing.Any = None) -> typing.Any:
        return getattr(self.display_layers[index], property_name, default_value)

    def _set_display_layer_property(self, index: int, property_name: str, value: typing.Any) -> None:
        setattr(self.display_layers[index], property_name, value)

    def _set_display_layer_properties(self, index: int, **kwargs: typing.Any) -> None:
        for kw, v in kwargs.items():
            self._set_display_layer_property(index, kw, v)

    def remove_display_layer(self, index_or_display_layer: typing.Union[int, DisplayLayer], *, safe: bool = False) -> Changes.UndeleteLog:
        if isinstance(index_or_display_layer, DisplayLayer):
            display_layer = index_or_display_layer
        else:
            display_layer = self.display_layers[index_or_display_layer]
        return self.remove_model_item(self, "display_layers", typing.cast(Persistence.PersistentObject, display_layer), safe=safe)

    def undelete_display_layer(self, before_index: int, display_layer: DisplayLayer) -> None:
        self.insert_display_layer(before_index, display_layer)

    def move_display_layer_forward(self, index: int) -> None:
        assert 0 <= index < len(self.display_layers)
        if index > 0:
            display_layer_copy = copy.deepcopy(self.display_layers[index])
            # use the version of remove that does not cascade
            self.remove_item("display_layers", typing.cast(Persistence.PersistentObject, self.display_layers[index]))
            self.insert_display_layer(index - 1, display_layer_copy)

    def move_display_layer_backward(self, index: int) -> None:
        assert 0 <= index < len(self.display_layers)
        if index < len(self.display_layers) - 1:
            display_layer_copy = copy.deepcopy(self.display_layers[index])
            # use the version of remove that does not cascade
            self.remove_item("display_layers", typing.cast(Persistence.PersistentObject, self.display_layers[index]))
            self.insert_display_layer(index + 1, display_layer_copy)

    def move_display_layer_at_index_forward(self, index: int) -> None:
        self.move_display_layer_forward(index)

    def move_display_layer_at_index_backward(self, index: int) -> None:
        self.move_display_layer_backward(index)

    def _add_display_layer_for_data_item(self, data_item: DataItem.DataItem, **kwargs: typing.Any) -> None:
        # note: self.data_items is constructed from self.display_data_channels; so index is valid.
        display_data_channel = self.display_data_channels[self.data_items.index(data_item)]
        self.add_display_layer_for_display_data_channel(display_data_channel, **kwargs)

    def get_display_layer_display_data_channel(self, index: int) -> typing.Optional[DisplayDataChannel]:
        assert 0 <= index < len(self.display_layers)
        return self.display_layers[index].display_data_channel

    def set_display_layer_display_data_channel(self, index: int, display_data_channel: typing.Optional[DisplayDataChannel]) -> None:
        assert 0 <= index < len(self.display_layers)
        assert display_data_channel is None or display_data_channel in self.display_data_channels
        self.display_layers[index].display_data_channel = display_data_channel

    def insert_display_layer_for_display_data_channel(self, before_index: int, display_data_channel: DisplayDataChannel, **kwargs: typing.Any) -> None:
        assert display_data_channel in self.display_data_channels
        display_layer = DisplayLayer()
        display_layer.display_data_channel = display_data_channel
        self.insert_display_layer(before_index, display_layer)
        self._set_display_layer_properties(before_index, **kwargs)

    def add_display_layer_for_display_data_channel(self, display_data_channel: DisplayDataChannel, **kwargs: typing.Any) -> None:
        self.insert_display_layer_for_display_data_channel(len(self.display_layers), display_data_channel, **kwargs)

    def get_display_layer_properties(self, index: int) -> Persistence.PersistentDictType:
        assert 0 <= index < len(self.display_layers)
        display_layer_properties = self.display_layers[index].write_to_dict()
        display_layer_properties.pop("uuid", None)
        display_layer_properties.pop("modified", None)
        display_layer_properties.pop("display_data_channel", None)
        return display_layer_properties

    def get_display_data_channel_layer_use_count(self, display_data_channel: DisplayDataChannel) -> int:
        count = 0
        for display_layer in self.display_layers:
            if display_layer.display_data_channel == display_data_channel:
                count += 1
        return count

    def display_layers_match(self, display_item: DisplayItem) -> bool:
        if len(self.display_layers) != len(display_item.display_layers):
            return False
        for i in range(len(self.display_layers)):
            if self.get_display_layer_properties(i) != display_item.get_display_layer_properties(i):
                return False
            if self.display_data_channels.index(
                    self.get_display_layer_display_data_channel(i)) != display_item.display_data_channels.index(
                    display_item.get_display_layer_display_data_channel(i)):
                return False
        return True

    def append_display_data_channel_for_data_item(self, data_item: DataItem.DataItem) -> None:
        if not data_item in self.data_items:
            try:
                display_data_channel = DisplayDataChannel(data_item)
                self.append_display_data_channel(display_data_channel, display_layer=DisplayLayer())
            except Exception as e:
                import traceback; traceback.print_exc()

    def save_properties(self) -> typing.Tuple[Persistence.PersistentDictType, typing.List[Persistence.PersistentDictType], str]:
        return self.display_properties, self.display_layers_list, self.calibration_style_id

    def restore_properties(self, properties: typing.Tuple[Persistence.PersistentDictType, typing.List[Persistence.PersistentDictType], str]) -> None:
        self.display_properties, self.display_layers_list, self.calibration_style_id = properties

    class ContextManager:
        def __init__(self, display_item: DisplayItem) -> None:
            self.__display_item = display_item

        def __enter__(self) -> DisplayItem.ContextManager:
            self.__display_item._begin_display_item_changes()
            return self

        def __exit__(self, exception_type: typing.Optional[typing.Type[BaseException]], value: typing.Optional[BaseException], traceback: typing.Optional[types.TracebackType]) -> typing.Optional[bool]:
            self.__display_item._end_display_item_changes()
            return None

    def display_item_changes(self) -> contextlib.AbstractContextManager[DisplayItem.ContextManager]:
        # return a context manager to batch up a set of changes so that listeners
        # are only notified after the last change is complete.
        display_item = self
        return DisplayItem.ContextManager(self)

    def _begin_display_item_changes(self) -> None:
        with self.__display_item_change_count_lock:
            self.__display_item_change_count += 1

    def _end_display_item_changes(self) -> None:
        with self.__display_item_change_count_lock:
            self.__display_item_change_count -= 1
            change_count = self.__display_item_change_count
        # if the change count is now zero, it means that we're ready to notify listeners.
        if change_count == 0:
            self.__write_delay_data_changed = True
            self.__item_changed()
            self.__update_displays()  # this ensures that the display will validate

    def increment_display_ref_count(self, amount: int = 1) -> None:
        """Increment display reference count to indicate this library item is currently displayed."""
        display_ref_count = self.__display_ref_count
        self.__display_ref_count += amount
        for display_data_channel in self.display_data_channels:
            display_data_channel.increment_display_ref_count(amount)

    def decrement_display_ref_count(self, amount: int = 1) -> None:
        """Decrement display reference count to indicate this library item is no longer displayed."""
        assert not self._closed
        self.__display_ref_count -= amount
        for display_data_channel in self.display_data_channels:
            display_data_channel.decrement_display_ref_count(amount)

    @property
    def _display_ref_count(self) -> int:
        return self.__display_ref_count

    def __data_item_will_change(self) -> None:
        self._begin_display_item_changes()

    def __data_item_did_change(self) -> None:
        self._end_display_item_changes()

    def __item_changed(self) -> None:
        # this event is only triggered when the data item changed live state; everything else goes through
        # the data changed messages.
        self.item_changed_event.fire()

    def __display_channel_property_changed(self, name: str) -> None:
        self.display_changed_event.fire()

    @property
    def display_data_channel(self) -> typing.Optional[DisplayDataChannel]:
        display_data_channels = self.display_data_channels
        return display_data_channels[0] if len(display_data_channels) == 1 else None

    def get_display_data_channel_for_data_item(self, data_item: DataItem.DataItem) -> typing.Optional[DisplayDataChannel]:
        for display_data_channel in self.display_data_channels:
            if display_data_channel.data_item == data_item:
                return display_data_channel
        return None

    def __update_displays(self) -> None:
        for display_data_channel in self.display_data_channels:
            display_data_channel.update_display_data()
        xdata_list = [data_item.xdata if data_item else None for data_item in self.data_items]
        dimensional_calibrations: typing.Optional[DataAndMetadata.CalibrationListType] = None
        intensity_calibration: typing.Optional[Calibration.Calibration] = None
        scales: typing.Tuple[float, float] = 0.0, 1.0
        dimensional_shape: typing.Optional[DataAndMetadata.ShapeType] = None
        if len(xdata_list) > 0:
            xdata0 = xdata_list[0]
            if xdata0 and len(xdata0.dimensional_calibrations) > 0:
                dimensional_calibrations = list(xdata0.dimensional_calibrations)
                if len(dimensional_calibrations) > 1:
                    intensity_calibration = xdata0.intensity_calibration
                    scales = 0, xdata0.dimensional_shape[-1]
                    dimensional_shape = xdata0.dimensional_shape
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
                    intensity_calibration = xdata0.intensity_calibration
                    scales = mn, mx
                    dimensional_shape = (int(mx - mn), )
        self.__dimensional_calibrations = dimensional_calibrations
        self.__intensity_calibration = intensity_calibration
        self.__scales = scales
        self.__dimensional_shape = dimensional_shape
        self.__is_composite_data = len(xdata_list) > 1
        self.display_property_changed_event.fire("displayed_dimensional_scales")
        self.display_property_changed_event.fire("displayed_dimensional_calibrations")
        self.display_property_changed_event.fire("displayed_intensity_calibration")
        self.display_changed_event.fire()
        self.graphics_changed_event.fire(self.graphic_selection)

    def _description_changed(self) -> None:
        self.notify_property_changed("title")
        self.notify_property_changed("caption")
        self.notify_property_changed("description")
        self.notify_property_changed("session_id")
        self.notify_property_changed("displayed_title")

    def __get_used_str_value(self, key: str, default_value: str) -> str:
        if self._get_persistent_property_value(key) is not None:
            return typing.cast(str, self._get_persistent_property_value(key))
        if self.data_item and getattr(self.data_item, key, None):
            return typing.cast(str, getattr(self.data_item, key))
        return default_value

    def __set_cascaded_value(self, key: str, value: typing.Any) -> None:
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
    def displayed_title(self) -> str:
        return self.title

    @property
    def title(self) -> str:
        return self.__get_used_str_value("title", DataItem.UNTITLED_STR)

    @title.setter
    def title(self, value: str) -> None:
        self.__set_cascaded_value("title", str(value) if value is not None else str())

    @property
    def caption(self) -> str:
        return self.__get_used_str_value("caption", str())

    @caption.setter
    def caption(self, value: str) -> None:
        self.__set_cascaded_value("caption", str(value) if value is not None else str())

    @property
    def description(self) -> str:
        return self.__get_used_str_value("description", str())

    @description.setter
    def description(self, value: str) -> None:
        self.__set_cascaded_value("description", str(value) if value is not None else str())

    @property
    def session_id(self) -> typing.Optional[str]:
        return self.__get_used_str_value("session_id", str())

    @session_id.setter
    def session_id(self, value: typing.Optional[str]) -> None:
        self.__set_cascaded_value("session_id", str(value) if value is not None else str())

    def __insert_display_data_channel(self, name: str, before_index: int, display_data_channel: DisplayDataChannel) -> None:
        display_data_channel.increment_display_ref_count(self._display_ref_count)
        self.__display_data_channel_property_changed_event_listeners.insert(before_index, display_data_channel.property_changed_event.listen(self.__display_channel_property_changed))
        self.__display_data_channel_data_item_will_change_event_listeners.insert(before_index, display_data_channel.data_item_will_change_event.listen(self.__data_item_will_change))
        self.__display_data_channel_data_item_did_change_event_listeners.insert(before_index, display_data_channel.data_item_did_change_event.listen(self.__data_item_did_change))
        self.__display_data_channel_data_item_changed_event_listeners.insert(before_index, display_data_channel.data_item_changed_event.listen(self.__item_changed))
        self.__display_data_channel_data_item_description_changed_event_listeners.insert(before_index, display_data_channel.data_item_description_changed_event.listen(self._description_changed))
        self.__display_data_channel_data_item_proxy_changed_event_listeners.insert(before_index, display_data_channel.data_item_proxy_changed_event.listen(self.__update_displays))
        self.notify_insert_item("display_data_channels", display_data_channel, before_index)

    def __remove_display_data_channel(self, name: str, index: int, display_data_channel: DisplayDataChannel) -> None:
        display_data_channel.decrement_display_ref_count(self._display_ref_count)
        self.__disconnect_display_data_channel(display_data_channel, index)

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
        self.__display_data_channel_data_item_proxy_changed_event_listeners[index].close()
        del self.__display_data_channel_data_item_proxy_changed_event_listeners[index]
        self.notify_remove_item("display_data_channels", display_data_channel, index)

    def append_display_data_channel(self, display_data_channel: DisplayDataChannel, display_layer: typing.Optional[DisplayLayer] = None) -> None:
        self.insert_display_data_channel(len(self.display_data_channels), display_data_channel)
        if display_layer:
            self.__add_display_layer_auto(display_layer, display_data_channel)

    def __get_unique_display_layer_color(self) -> str:
        existing_colors: typing.List[Color.Color] = list()
        existing_colors.extend([Color.Color(display_layer.fill_color).to_color_without_alpha() for display_layer in self.display_layers])
        existing_colors.extend([Color.Color(display_layer.stroke_color).to_color_without_alpha() for display_layer in self.display_layers])
        possible_colors = [Color.Color(color) for color in DisplayItem.DEFAULT_COLORS]
        for possible_color in possible_colors:
            if not any(map(operator.methodcaller("matches_without_alpha", possible_color), existing_colors)):
                return possible_color.to_named_color_without_alpha().color_str or DisplayItem.DEFAULT_COLORS[0]
        return DisplayItem.DEFAULT_COLORS[0]

    def auto_display_legend(self) -> None:
        if len(self.display_layers) == 2 and self.get_display_property("legend_position") is None:
            self.set_display_property("legend_position", "top-right")
        elif len(self.display_layers) == 1:
            self.set_display_property("legend_position", None)

    def __add_display_layer_auto(self, display_layer: DisplayLayer, display_data_channel: DisplayDataChannel, data_row: int = 0) -> None:
        # this fill color code breaks encapsulation. i'm leaving it here as a convenience for now.
        # eventually there should be a connection to a display controller based on the display type which can be
        # used to set defaults for the layers.
        display_layer.display_data_channel = display_data_channel
        if data_row is not None:
            display_layer.data_row = data_row
        if not display_layer.fill_color:
            display_layer.fill_color = self.__get_unique_display_layer_color()
            display_layer.stroke_color = display_layer.fill_color
            if len(self.display_data_channels) > 1:  # if the layer is an additional stack
                display_layer.fill_color = None
        self.append_display_layer(display_layer)
        self.auto_display_legend()

    def insert_display_data_channel(self, before_index: int, display_data_channel: DisplayDataChannel) -> None:
        self.insert_model_item(self, "display_data_channels", before_index, display_data_channel)

    def remove_display_data_channel(self, display_data_channel: DisplayDataChannel, *, safe: bool = False) -> Changes.UndeleteLog:
        return self.remove_model_item(self, "display_data_channels", display_data_channel, safe=safe)

    def undelete_display_data_channel(self, before_index: int, display_data_channel: DisplayDataChannel) -> None:
        self.insert_display_data_channel(before_index, display_data_channel)
        self.__update_displays()

    @property
    def data_items(self) -> typing.Sequence[DataItem.DataItem]:
        return [display_data_channel.data_item for display_data_channel in self.display_data_channels if display_data_channel.data_item]

    @property
    def data_item(self) -> typing.Optional[DataItem.DataItem]:
        data_items = self.data_items
        return data_items[0] if len(data_items) == 1 else None

    @property
    def selected_graphics(self) -> typing.Sequence[Graphics.Graphic]:
        return [self.graphics[i] for i in self.graphic_selection.indexes]

    def __insert_graphic(self, name: str, before_index: int, graphic: Graphics.Graphic) -> None:
        graphic_changed_listener = graphic.property_changed_event.listen(lambda p: self.__graphic_changed(graphic))
        self.__graphic_changed_listeners.insert(before_index, graphic_changed_listener)
        self.graphic_selection.insert_index(before_index)
        self.notify_insert_item("graphics", graphic, before_index)
        self.__graphic_changed(graphic)

    def __remove_graphic(self, name: str, index: int, graphic: Graphics.Graphic) -> None:
        self.__disconnect_graphic(graphic, index)
        self.notify_remove_item("graphics", graphic, index)

    def __disconnect_graphic(self, graphic: Graphics.Graphic, index: int) -> None:
        graphic_changed_listener = self.__graphic_changed_listeners[index]
        graphic_changed_listener.close()
        self.__graphic_changed_listeners.remove(graphic_changed_listener)
        self.graphic_selection.remove_index(index)
        self.__graphic_changed(graphic)

    def insert_graphic(self, before_index: int, graphic: Graphics.Graphic) -> None:
        """Insert a graphic before the index, but do it through the container, so dependencies can be tracked."""
        self.insert_model_item(self, "graphics", before_index, graphic)

    def add_graphic(self, graphic: Graphics.Graphic) -> None:
        """Append a graphic, but do it through the container, so dependencies can be tracked."""
        self.insert_model_item(self, "graphics", self.item_count("graphics"), graphic)

    def remove_graphic(self, graphic: Graphics.Graphic, *, safe: bool = False) -> Changes.UndeleteLog:
        """Remove a graphic, but do it through the container, so dependencies can be tracked."""
        return self.remove_model_item(self, "graphics", graphic, safe=safe)

    # this message comes from the graphic. the connection is established when a graphic
    # is added or removed from this object.
    def __graphic_changed(self, graphic: Graphics.Graphic) -> None:
        self.graphics_changed_event.fire(self.graphic_selection)

    @property
    def calibration_style(self) -> CalibrationStyle:
        return next(filter(lambda x: x.calibration_style_id == self.calibration_style_id, get_calibration_styles()), get_default_calibrated_calibration_style())

    @property
    def display_data_shape(self) -> typing.Optional[DataAndMetadata.ShapeType]:
        if not self.display_data_channel:
            return self.__dimensional_shape if self.__is_composite_data else None
        return self.display_data_channel.display_data_shape

    @property
    def dimensional_shape(self) -> typing.Optional[DataAndMetadata.ShapeType]:
        """Shape of the underlying data, if only one."""
        return self.display_data_channel.dimensional_shape if self.display_data_channel else None

    @property
    def displayed_dimensional_scales(self) -> typing.Optional[typing.Tuple[float, ...]]:
        """The scale of the fractional coordinate system.

        For displays associated with a single data item, this matches the size of the data.

        For displays associated with a composite data item, this must be stored in this class.
        """
        return self.__scales

    @property
    def datum_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        """The calibrations for only datum dimensions."""
        if self.display_data_channel:
            datum_calibrations = self.display_data_channel.datum_calibrations
            if datum_calibrations is not None:
                return datum_calibrations
        return [Calibration.Calibration() for c in self.__dimensional_calibrations] if self.__dimensional_calibrations else [Calibration.Calibration()]

    @property
    def displayed_dimensional_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        """The calibrations for all data dimensions in the displayed calibration style."""
        calibration_style = self.__get_calibration_style_for_id(self.calibration_style_id)
        calibration_style = CalibrationStyleNative() if not calibration_style else calibration_style
        if self.__dimensional_calibrations and self.__dimensional_shape:
            return calibration_style.get_dimensional_calibrations(self.__dimensional_shape, self.__dimensional_calibrations)
        return [Calibration.Calibration() for c in self.__dimensional_calibrations] if self.__dimensional_calibrations else [Calibration.Calibration()]

    @property
    def displayed_datum_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        """The calibrations for only datum dimensions, in the displayed calibration style."""
        calibration_style = self.__get_calibration_style_for_id(self.calibration_style_id)
        calibration_style = CalibrationStyleNative() if not calibration_style else calibration_style
        display_data_channel = self.display_data_channel
        if self.__dimensional_calibrations and self.__dimensional_shape and display_data_channel:
            calibrations = calibration_style.get_dimensional_calibrations(self.__dimensional_shape, self.__dimensional_calibrations)
            datum_calibrations = display_data_channel.get_datum_calibrations(calibrations)
            if datum_calibrations:
                return datum_calibrations
        if self.__is_composite_data:
            return self.displayed_dimensional_calibrations
        return [Calibration.Calibration() for c in self.__dimensional_calibrations] if self.__dimensional_calibrations else [Calibration.Calibration()]

    @property
    def displayed_intensity_calibration(self) -> Calibration.Calibration:
        calibration_style = self.__get_calibration_style_for_id(self.calibration_style_id)
        if self.__intensity_calibration and (not calibration_style or calibration_style.is_calibrated):
            return self.__intensity_calibration
        return Calibration.Calibration()

    def __get_calibration_style_for_id(self, calibration_style_id: str) -> typing.Optional[CalibrationStyle]:
        for calibration_style in get_calibration_styles():
            if calibration_style.calibration_style_id == calibration_style_id:
                return calibration_style
        return None

    @property
    def size_and_data_format_as_string(self) -> str:
        data_item = self.data_item
        return data_item.size_and_data_format_as_string if data_item else str()

    @property
    def date_for_sorting(self) -> datetime.datetime:
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
            # allow registered metadata_display components to populate a dictionary
            # the display item will use 'frame_index' and 'valid_rows' for the status string in the data panel
            d: Persistence.PersistentDictType = dict()
            for component in Registry.get_components_by_type("metadata_display"):
                component.populate(d, data_item.metadata)
            # build the status string
            frame_index_str = str(d.get("frame_index", str()))
            partial_str = "{0:d}/{1:d}".format(d["valid_rows"], data_item.dimensional_shape[0]) if "valid_rows" in d else str()
            return "{0:s} {1:s} {2:s}".format(_("Live"), frame_index_str, partial_str)
        return str()

    @property
    def project_str(self) -> str:
        display_item = self.display_data_channel.display_item if self.display_data_channel else None
        if display_item:
            return display_item.project.title if display_item.container else str()
        return str()

    @property
    def used_display_type(self) -> typing.Optional[str]:
        display_type = self.display_type
        if not display_type in ("line_plot", "image", "display_script"):
            for display_data_channel in self.display_data_channels:
                if display_data_channel.has_valid_data:
                    if display_data_channel.is_display_1d_preferred:
                        display_type = "line_plot"
                    elif display_data_channel.is_display_2d_preferred:
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
            if left is not None:
                left = min(left, interval[0])
            else:
                left = interval[0]
            if right is not None:
                right = max(right, interval[1])
            else:
                right = interval[1]
        left = left if left is not None else 0.0
        right = right if right is not None else 1.0
        extra = (right - left) * 0.5
        left_channel = int(max(0.0, left - extra) * data_and_metadata.data_shape[-1])
        right_channel = int(min(1.0, right + extra) * data_and_metadata.data_shape[-1])
        self.set_display_property("left_channel", left_channel)
        self.set_display_property("right_channel", right_channel)
        data_min = numpy.amin(data_and_metadata.data[..., left_channel:right_channel])  # type: ignore
        data_max = numpy.amax(data_and_metadata.data[..., left_channel:right_channel])  # type: ignore
        if data_min > 0 and data_max > 0:
            self.set_display_property("y_min", 0.0)
            self.set_display_property("y_max", data_max * 1.2)
        elif data_min < 0 and data_max < 0:
            self.set_display_property("y_min", data_min * 1.2)
            self.set_display_property("y_max", 0.0)
        else:
            self.set_display_property("y_min", data_min * 1.2)
            self.set_display_property("y_max", data_max * 1.2)

    def __get_calibrated_value_text(self, value: float, intensity_calibration: Calibration.Calibration) -> str:
        if value is not None:
            return intensity_calibration.convert_to_calibrated_value_str(value)
        elif value is None:
            return _("N/A")
        else:
            return str(value)

    def get_value_and_position_text(self, pos: typing.Optional[typing.Tuple[int, ...]]) -> typing.Tuple[str, str]:
        display_data_channel = self.display_data_channel
        dimensional_calibrations = self.displayed_dimensional_calibrations
        intensity_calibration = self.displayed_intensity_calibration

        if display_data_channel is None or pos is None:
            if self.__is_composite_data and (pos is not None and len(pos) == 1):
                return u"{0}".format(dimensional_calibrations[-1].convert_to_calibrated_value_str(pos[0])), str()
            return str(), str()

        # pass in the position of the cursor as reported by the display. it will be 1D or 2D position.
        # convert it to a position that is an index into the data.
        assert pos is not None
        pos = display_data_channel.get_display_position_as_data_position(pos)

        position_text = ""
        value_text = ""
        dimensional_shape = display_data_channel.dimensional_shape  # don't include the RGB part of the shape
        if len(pos) == 4 and dimensional_shape:
            # 4d image
            # make sure the position is within the bounds of the image
            if 0 <= pos[0] < dimensional_shape[0] and 0 <= pos[1] < dimensional_shape[1] and 0 <= pos[2] < dimensional_shape[2] and 0 <= pos[3] < dimensional_shape[3]:
                position_text = u"{0}, {1}, {2}, {3}".format(
                    dimensional_calibrations[3].convert_to_calibrated_value_str(pos[3], value_range=(0, dimensional_shape[3]), samples=dimensional_shape[3]),
                    dimensional_calibrations[2].convert_to_calibrated_value_str(pos[2], value_range=(0, dimensional_shape[2]), samples=dimensional_shape[2]),
                    dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1], value_range=(0, dimensional_shape[1]), samples=dimensional_shape[1]),
                    dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0], value_range=(0, dimensional_shape[0]), samples=dimensional_shape[0]))
                value_text = self.__get_calibrated_value_text(display_data_channel.get_data_value(pos), intensity_calibration)
        if len(pos) == 3 and dimensional_shape:
            # 3d image
            # make sure the position is within the bounds of the image
            if 0 <= pos[0] < dimensional_shape[0] and 0 <= pos[1] < dimensional_shape[1] and 0 <= pos[2] < dimensional_shape[2]:
                position_text = u"{0}, {1}, {2}".format(dimensional_calibrations[2].convert_to_calibrated_value_str(pos[2], value_range=(0, dimensional_shape[2]), samples=dimensional_shape[2]),
                    dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1], value_range=(0, dimensional_shape[1]), samples=dimensional_shape[1]),
                    dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0], value_range=(0, dimensional_shape[0]), samples=dimensional_shape[0]))
                value_text = self.__get_calibrated_value_text(display_data_channel.get_data_value(pos), intensity_calibration)
        if len(pos) == 2 and dimensional_shape:
            # 2d image
            # make sure the position is within the bounds of the image
            if len(dimensional_shape) == 1:
                if pos[-1] >= 0 and pos[-1] < dimensional_shape[-1]:
                    position_text = u"{0}".format(dimensional_calibrations[-1].convert_to_calibrated_value_str(pos[-1], value_range=(0, dimensional_shape[-1]), samples=dimensional_shape[-1]))
                    full_pos = [0, ] * len(dimensional_shape)
                    full_pos[-1] = pos[-1]
                    value_text = self.__get_calibrated_value_text(display_data_channel.get_data_value(tuple(full_pos)), intensity_calibration)
            else:
                if pos[0] >= 0 and pos[0] < dimensional_shape[0] and pos[1] >= 0 and pos[1] < dimensional_shape[1]:
                    is_polar = dimensional_calibrations[0].units.startswith("1/") and dimensional_calibrations[0].units == dimensional_calibrations[1].units
                    if is_polar:
                        x = dimensional_calibrations[1].convert_to_calibrated_value(pos[1])
                        y = dimensional_calibrations[0].convert_to_calibrated_value(pos[0])
                        r = math.sqrt(x * x + y * y)
                        angle = -math.atan2(y, x)
                        r_str = dimensional_calibrations[0].convert_to_calibrated_value_str(dimensional_calibrations[0].convert_from_calibrated_value(r), value_range=(0, dimensional_shape[0]), samples=dimensional_shape[0], display_inverted=True)
                        position_text = u"{0}, {1:.4f}° ({2})".format(r_str, math.degrees(angle), _("polar"))
                    else:
                        position_text = u"{0}, {1}".format(dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1], value_range=(0, dimensional_shape[1]), samples=dimensional_shape[1], display_inverted=True),
                            dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0], value_range=(0, dimensional_shape[0]), samples=dimensional_shape[0], display_inverted=True))
                    value_text = self.__get_calibrated_value_text(display_data_channel.get_data_value(pos), intensity_calibration)
        if len(pos) == 1 and dimensional_shape:
            # 1d plot
            # make sure the position is within the bounds of the line plot
            if pos[0] >= 0 and pos[0] < dimensional_shape[-1]:
                position_text = u"{0}".format(dimensional_calibrations[-1].convert_to_calibrated_value_str(pos[0], value_range=(0, dimensional_shape[-1]), samples=dimensional_shape[-1]))
                full_pos = [0, ] * len(dimensional_shape)
                full_pos[-1] = pos[0]
                value_text = self.__get_calibrated_value_text(display_data_channel.get_data_value(tuple(full_pos)), intensity_calibration)
        return position_text, value_text

    async def get_value_and_position_text_async(self, pos: typing.Optional[typing.Tuple[int, ...]]) -> typing.Tuple[str, str]:
        def get_cursor_value(display_item: DisplayItem) -> typing.Tuple[str, str]:
            try:
                return display_item.get_value_and_position_text(pos)
            except Exception as e:
                import traceback
                traceback.print_exc()
                return str(), str()
            finally:
                # decrement the outstanding thread count and notify listeners (the close method) that it has changed
                with display_item.__outstanding_condition:
                    display_item.__outstanding_thread_count -= 1
                    display_item.__outstanding_condition.notify_all()

        # avoid race condition around close by checking if already closed. this method and close must always be
        # called on the same thread for this to be effective.
        if not self._closed:
            # assume close cannot be happening at the same time; so if not closed, increment the outstanding
            # thread count to prevent close until the executor finishes the get cursor value call.
            with self.__outstanding_condition:
                self.__outstanding_thread_count += 1
            return await asyncio.get_event_loop().run_in_executor(None, get_cursor_value, self)
        return str(), str()


class DisplayCalibrationInfo:

    def __init__(self, display_item: DisplayItem, display_data_shape: typing.Optional[DataAndMetadata.ShapeType] = None) -> None:
        self.display_data_shape = display_data_shape if display_data_shape is not None else display_item.display_data_shape
        self.displayed_dimensional_scales = display_item.displayed_dimensional_scales
        self.displayed_dimensional_calibrations = copy.deepcopy(display_item.displayed_dimensional_calibrations)
        self.displayed_intensity_calibration = copy.deepcopy(display_item.displayed_intensity_calibration)
        self.calibration_style = display_item.calibration_style
        self.datum_calibrations = list(display_item.datum_calibrations)

    def __ne__(self, other: typing.Any) -> bool:
        if not isinstance(other, DisplayCalibrationInfo):
            return False
        display_calibration_info = other
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
        if  self.datum_calibrations != display_calibration_info.datum_calibrations:
            return True
        if  type(self.calibration_style) != type(display_calibration_info.calibration_style):
            return True
        return False


def get_calibration_styles() -> typing.Sequence[CalibrationStyle]:
    return [CalibrationStyleNative(), CalibrationStylePixelsTopLeft(), CalibrationStylePixelsCenter(),
            CalibrationStyleFractionalTopLeft(), CalibrationStyleFractionalCenter()]


def get_default_calibrated_calibration_style() -> CalibrationStyle:
    return CalibrationStyleNative()


def get_default_uncalibrated_calibration_style() -> CalibrationStyle:
    return CalibrationStylePixelsCenter()
