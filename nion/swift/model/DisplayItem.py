from __future__ import annotations

# standard libraries
import asyncio
import concurrent.futures
import contextlib
import copy
import dataclasses
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
from nion.swift.model import DynamicString
from nion.swift.model import Graphics
from nion.swift.model import Model
from nion.swift.model import Persistence
from nion.swift.model import Schema
from nion.swift.model import Utility
from nion.utils import Color
from nion.utils import DateTime
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import Process
from nion.utils import ReferenceCounting
from nion.utils import Registry
from nion.utils import Stream

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
                            data_sample: typing.Optional[_ImageDataType],
                            xdata: typing.Optional[DataAndMetadata.DataAndMetadata],
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


class CalibrationStyleLike(typing.Protocol):
    label: str
    calibration_style_id: str
    is_calibrated: bool = False


class CalibrationStyle(CalibrationStyleLike):
    label: str
    calibration_style_id: str
    is_calibrated: bool = False

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType, metadata: typing.Optional[DataAndMetadata.MetadataType]) -> DataAndMetadata.CalibrationListType:
        return list()

    def get_intensity_calibration(self, calibration: Calibration.Calibration) -> Calibration.Calibration:
        return calibration


class CalibrationStyleNative(CalibrationStyle):
    label = _("Calibrated")
    calibration_style_id = "calibrated"
    is_calibrated = True

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType, metadata: typing.Optional[DataAndMetadata.MetadataType]) -> DataAndMetadata.CalibrationListType:
        if all(calibration.is_valid for calibration in dimensional_calibrations):
            return dimensional_calibrations
        return [Calibration.Calibration() for _ in dimensional_shape]


class CalibrationDescriptionCalibrationStyle(CalibrationStyle):
    def __init__(self, label: str, calibration_description: CalibrationDescription) -> None:
        self.label = label
        self.calibration_style_id = calibration_description.calibration_style_id
        self.is_calibrated = True
        self.calibration_description = calibration_description

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType, metadata: typing.Optional[DataAndMetadata.MetadataType]) -> DataAndMetadata.CalibrationListType:
        assert self.calibration_description.dimensional_calibrations is not None
        return self.calibration_description.dimensional_calibrations

    def get_intensity_calibration(self, calibration: Calibration.Calibration) -> Calibration.Calibration:
        assert self.calibration_description.intensity_calibration is not None
        return self.calibration_description.intensity_calibration


class CalibrationStylePixelsTopLeft(CalibrationStyle):
    label = _("Pixels (Top-Left)")
    calibration_style_id = "pixels-top-left"

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType, metadata: typing.Optional[DataAndMetadata.MetadataType]) -> DataAndMetadata.CalibrationListType:
        return [Calibration.Calibration() for display_dimension in dimensional_shape]


class CalibrationStylePixelsCenter(CalibrationStyle):
    label = _("Pixels (Center)")
    calibration_style_id = "pixels-center"

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType, metadata: typing.Optional[DataAndMetadata.MetadataType]) -> DataAndMetadata.CalibrationListType:
        return [Calibration.Calibration(offset=-display_dimension/2) for display_dimension in dimensional_shape]


class CalibrationStyleFractionalTopLeft(CalibrationStyle):
    label = _("Fractional (Top Left)")
    calibration_style_id = "relative-top-left"

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType, metadata: typing.Optional[DataAndMetadata.MetadataType]) -> DataAndMetadata.CalibrationListType:
        return [Calibration.Calibration(scale=1.0/display_dimension) for display_dimension in dimensional_shape]


class CalibrationStyleFractionalCenter(CalibrationStyle):
    label = _("Fractional (Center)")
    calibration_style_id = "relative-center"

    def get_dimensional_calibrations(self, dimensional_shape: DataAndMetadata.ShapeType, dimensional_calibrations: DataAndMetadata.CalibrationListType, metadata: typing.Optional[DataAndMetadata.MetadataType]) -> DataAndMetadata.CalibrationListType:
        return [Calibration.Calibration(scale=2.0/display_dimension, offset=-1.0) for display_dimension in dimensional_shape]


class IntensityCalibrationStyleUncalibrated(CalibrationStyle):
    label = _("Uncalibrated")
    calibration_style_id = "uncalibrated"

    def get_intensity_calibration(self, calibration: Calibration.Calibration) -> Calibration.Calibration:
        return Calibration.Calibration()


class AdjustmentType(typing.Protocol):
    def transform(self, data: _ImageDataType, display_limits: typing.Tuple[float, float]) -> _ImageDataType: ...


def adjustment_factory(adjustment_d: Persistence.PersistentDictType) -> typing.Optional[AdjustmentType]:
    if adjustment_d.get("type", None) == "gamma":
        class AdjustGamma:
            def __init__(self, gamma: float) -> None:
                self.__gamma = gamma

            def transform(self, data: _ImageDataType, display_limits: typing.Tuple[float, float]) -> _ImageDataType:
                return numpy.power(numpy.clip(data, 0.0, 1.0), self.__gamma, dtype=numpy.float32)

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
                histogram, bins = numpy.histogram(data.flatten(), 256, density=True)
                histogram_cdf = histogram.cumsum()
                histogram_cdf = histogram_cdf / histogram_cdf[-1]
                equalized = numpy.interp(data.flatten(), bins[:-1], histogram_cdf)
                return equalized.reshape(data.shape)

        return AdjustEqualized()
    else:
        return None


@typing.runtime_checkable
class ProcessorLike(typing.Protocol):
    """A processor like object that can be used to process data and metadata.

    Subclasses should implement _get_result but callers should call get_result, which provides caching.
    """

    def execute(self) -> None: ...

    def _execute(self) -> None: ...

    def set_parameter(self, key: str, value: typing.Any) -> None: ...

    def _get_parameter(self, key: str) -> typing.Any: ...

    def get_result(self, key: str) -> typing.Any: ...

    def set_result(self, key: str, value: typing.Any) -> None: ...


@dataclasses.dataclass
class ProcessorConnection:
    source: ProcessorLike
    source_key: str
    target_key: typing.Optional[str] = None


class ProcessorBase(ProcessorLike):
    """A processor-like object that can be used to process data and metadata.

    The result timestamps must be set to the first input timestamp.
    """

    def __init__(self, **kwargs: typing.Any) -> None:
        self.__dirty = True
        self.__parameters = dict[str, typing.Any]()
        self.__results = dict[str, typing.Any]()
        self.__lock = threading.RLock()
        self.__connections = list[ProcessorConnection]()
        for key, value in kwargs.items():
            if isinstance(value, ProcessorConnection):
                self.add_connection(value.source, value.source_key, value.target_key)
            self.set_parameter(key, value)

    def add_connection(self, source: ProcessorLike, source_key: str, target_key: typing.Optional[str] = None) -> None:
        target_key = target_key if target_key else source_key
        self.__connections.append(ProcessorConnection(source, source_key, target_key))

    def execute(self) -> None:
        with self.__lock:
            if self.__dirty:
                self._execute()
                self.__dirty = False

    def set_parameter(self, key: str, value: typing.Any) -> None:
        with self.__lock:
            self.__parameters[key] = value
            self.__dirty = True

    def _get_parameter(self, key: str) -> typing.Any:
        with self.__lock:
            for connection in self.__connections:
                if key == (connection.target_key or connection.source_key):
                    self.__parameters[key] = connection.source.get_result(connection.source_key)
            return self.__parameters.get(key, None)

    def _get_string(self, key: str) -> str:
        with self.__lock:
            return typing.cast(str, self._get_parameter(key))

    def _get_optional_string(self, key: str) -> typing.Optional[str]:
        with self.__lock:
            return typing.cast(typing.Optional[str], self._get_parameter(key))

    def _get_int(self, key: str) -> int:
        with self.__lock:
            return typing.cast(int, self._get_parameter(key))

    def _get_optional_int(self, key: str) -> typing.Optional[int]:
        with self.__lock:
            return typing.cast(typing.Optional[int], self._get_parameter(key))

    def _get_float(self, key: str) -> float:
        with self.__lock:
            return typing.cast(float, self._get_parameter(key))

    def _get_optional_float(self, key: str) -> typing.Optional[float]:
        with self.__lock:
            return typing.cast(typing.Optional[float], self._get_parameter(key))

    def get_result(self, key: str) -> typing.Any:
        with self.__lock:
            self.execute()
            return self.__results.get(key, None)

    def set_result(self, key: str, value: typing.Any) -> None:
        with self.__lock:
            self.__results[key] = value

    def _get_data_and_metadata_like(self, key: str) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        input_data_and_metadata = self._get_parameter(key)
        return DataAndMetadata.promote_ndarray(input_data_and_metadata) if input_data_and_metadata is not None else None


class ElementDataProcessor(ProcessorBase):
    def __init__(self, *,
                    data: typing.Union[typing.Optional[DataAndMetadata._DataAndMetadataLike], ProcessorConnection] = None,
                    sequence_index: typing.Union[typing.Optional[int], ProcessorConnection] = None,
                    collection_index: typing.Union[typing.Optional[DataAndMetadata.PositionType], ProcessorConnection] = None,
                    slice_center: typing.Union[typing.Optional[int], ProcessorConnection] = None,
                    slice_width: typing.Union[typing.Optional[int], ProcessorConnection] = None) -> None:
        super().__init__(data=data, sequence_index=sequence_index, collection_index=collection_index,
                         slice_center=slice_center, slice_width=slice_width)

    def _execute(self) -> None:
        input_data_and_metadata = self._get_data_and_metadata_like("data")
        sequence_index = self._get_int("sequence_index")
        collection_index = typing.cast(typing.Optional[DataAndMetadata.PositionType], self._get_parameter("collection_index"))
        slice_center = self._get_int("slice_center")
        slice_width = self._get_int("slice_width")
        data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        if input_data_and_metadata:
            data_and_metadata, modified = Core.function_element_data_no_copy(input_data_and_metadata,
                                                                             sequence_index,
                                                                             collection_index,
                                                                             slice_center,
                                                                             slice_width,
                                                                             flag16=False)
        self.set_result("data", data_and_metadata)


class DisplayDataProcessor(ProcessorBase):
    def __init__(self, *,
                 element_data: typing.Union[typing.Optional[DataAndMetadata._DataAndMetadataLike], ProcessorConnection] = None,
                 complex_display_type: typing.Union[typing.Optional[str], ProcessorConnection] = None) -> None:
        super().__init__(element_data=element_data, complex_display_type=complex_display_type)

    def _execute(self) -> None:
        element_data_and_metadata = self._get_data_and_metadata_like("element_data")
        complex_display_type = self._get_string("complex_display_type")
        data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        if element_data_and_metadata:
            data_and_metadata, modified = Core.function_scalar_data_no_copy(element_data_and_metadata, complex_display_type)
        self.set_result("data", data_and_metadata)


class DataRangeProcessor(ProcessorBase):
    def __init__(self, *,
                 data: typing.Union[typing.Optional[DataAndMetadata._DataAndMetadataLike], ProcessorConnection] = None,
                 display_data: typing.Union[typing.Optional[DataAndMetadata._DataAndMetadataLike], ProcessorConnection] = None) -> None:
        super().__init__(data=data, display_data=display_data)

    def _execute(self) -> None:
        data_and_metadata = self._get_data_and_metadata_like("data")
        display_data_and_metadata = self._get_data_and_metadata_like("display_data")
        display_data = display_data_and_metadata.data if display_data_and_metadata else None
        data_range: typing.Optional[typing.Tuple[float, float]]
        if display_data is not None and display_data.shape and data_and_metadata:
            data_shape = data_and_metadata.data_shape
            data_dtype = data_and_metadata.data_dtype
            if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
                data_range = (0, 255)
            elif Image.is_shape_and_dtype_complex_type(data_shape, data_dtype):
                data_range = (numpy.amin(display_data), numpy.amax(display_data))
            else:
                data_range = (numpy.amin(display_data), numpy.amax(display_data))
        else:
            data_range = None
        if data_range is not None:
            if math.isnan(data_range[0]) or math.isnan(data_range[1]) or math.isinf(
                    data_range[0]) or math.isinf(data_range[1]):
                data_range = (0.0, 0.0)
            if numpy.issubdtype(type(data_range[0]), numpy.bool_):
                data_range = (int(data_range[0]), data_range[1])
            if numpy.issubdtype(type(data_range[1]), numpy.bool_):
                data_range = (data_range[0], int(data_range[1]))
        self.set_result("data_range", data_range)


class DisplayRangeProcessor(ProcessorBase):
    def __init__(self, *,
                 element_data: typing.Union[typing.Optional[DataAndMetadata._DataAndMetadataLike], ProcessorConnection] = None,
                 display_limits: typing.Union[typing.Optional[DisplayLimitsType], ProcessorConnection] = None,
                 data_range: typing.Union[typing.Optional[typing.Tuple[float, float]], ProcessorConnection] = None,
                 data_sample: typing.Union[typing.Optional[_ImageDataType], ProcessorConnection] = None,
                 complex_display_type: typing.Union[typing.Optional[str], ProcessorConnection] = None) -> None:
        super().__init__(element_data=element_data, display_limits=display_limits, data_range=data_range,
                         data_sample=data_sample, complex_display_type=complex_display_type)

    def _execute(self) -> None:
        element_data_and_metadata = self._get_data_and_metadata_like("element_data")
        display_limits = typing.cast(typing.Optional[DisplayLimitsType], self._get_parameter("display_limits"))
        data_range = typing.cast(typing.Optional[typing.Tuple[float, float]], self._get_parameter("data_range"))
        data_sample = typing.cast(typing.Optional[_ImageDataType], self._get_parameter("data_sample"))
        complex_display_type = self._get_optional_string("complex_display_type")
        display_range = calculate_display_range(display_limits, data_range, data_sample, element_data_and_metadata, complex_display_type)
        self.set_result("display_range", display_range)


class DataSampleProcessor(ProcessorBase):
    def __init__(self, *,
                 data: typing.Union[typing.Optional[DataAndMetadata._DataAndMetadataLike], ProcessorConnection] = None,
                 display_data: typing.Union[typing.Optional[DataAndMetadata._DataAndMetadataLike], ProcessorConnection] = None) -> None:
        super().__init__(data=data, display_data=display_data)

    def _execute(self) -> None:
        data_and_metadata = self._get_data_and_metadata_like("data")
        display_data_and_metadata = self._get_data_and_metadata_like("display_data")
        display_data = display_data_and_metadata.data if display_data_and_metadata else None
        data_sample: typing.Optional[_ImageDataType] = None
        if display_data is not None and display_data.shape and data_and_metadata:
            data_shape = data_and_metadata.data_shape
            data_dtype = data_and_metadata.data_dtype
            if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
                data_sample = None
            elif Image.is_shape_and_dtype_complex_type(data_shape, data_dtype):
                data_sample = numpy.sort(numpy.random.choice(display_data.reshape(numpy.prod(display_data.shape, dtype=numpy.uint64)), 200))
            else:
                data_sample = None
        self.set_result("data_sample", data_sample)


class DisplayRGBProcessor(ProcessorBase):
    def __init__(self, *,
                 adjusted_data: typing.Union[typing.Optional[DataAndMetadata._DataAndMetadataLike], ProcessorConnection] = None,
                 data_range: typing.Union[typing.Optional[typing.Tuple[float, float]], ProcessorConnection] = None,
                 display_range: typing.Union[typing.Optional[typing.Tuple[float, float]], ProcessorConnection] = None,
                 color_map_data: typing.Union[typing.Optional[_ImageDataType], ProcessorConnection] = None) -> None:
        super().__init__(adjusted_data=adjusted_data, data_range=data_range, display_range=display_range, color_map_data=color_map_data)

    def _execute(self) -> None:
        adjusted_data_and_metadata = self._get_data_and_metadata_like("adjusted_data")
        data_range = typing.cast(typing.Optional[typing.Tuple[float, float]], self._get_parameter("data_range"))
        display_range = typing.cast(typing.Optional[typing.Tuple[float, float]], self._get_parameter("display_range"))
        color_map_data = typing.cast(typing.Optional[_ImageDataType], self._get_parameter("color_map_data"))
        display_rgba_data: typing.Optional[_ImageDataType] = None
        if adjusted_data_and_metadata:
            if data_range is not None:  # workaround until validating and retrieving data stats is an atomic operation
                # display_range is just display_limits but calculated if display_limits is None
                display_rgba = Core.function_display_rgba(adjusted_data_and_metadata, display_range, color_map_data)
                display_rgba_data = display_rgba.data if display_rgba else None
        self.set_result("display_rgba", display_rgba_data)


class NormalizedDataProcessor(ProcessorBase):
    def __init__(self, *,
                 display_data: typing.Union[typing.Optional[DataAndMetadata._DataAndMetadataLike], ProcessorConnection] = None,
                 display_range: typing.Union[typing.Optional[typing.Tuple[float, float]], ProcessorConnection] = None) -> None:
        super().__init__(display_data=display_data, display_range=display_range)

    def _execute(self) -> None:
        display_data_and_metadata = self._get_data_and_metadata_like("display_data")
        display_range = typing.cast(typing.Optional[typing.Tuple[float, float]], self._get_parameter("display_range"))
        data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        if display_range is not None and display_data_and_metadata:
            display_limit_low, display_limit_high = display_range
            # normalize the data to [0, 1].
            m = 1 / (display_limit_high - display_limit_low) if display_limit_high != display_limit_low else 0.0
            b = -display_limit_low
            data_and_metadata = DataAndMetadata.new_data_and_metadata(data=float(m) * (display_data_and_metadata.data + float(b)),
                                                                      timestamp=display_data_and_metadata.timestamp,
                                                                      timezone=display_data_and_metadata.timezone,
                                                                      timezone_offset=display_data_and_metadata.timezone_offset)
        self.set_result("data", data_and_metadata)


class AdjustedDataProcessor(ProcessorBase):
    def __init__(self, *,
                 normalized_data: typing.Union[typing.Optional[DataAndMetadata._DataAndMetadataLike], ProcessorConnection] = None,
                 display_data: typing.Union[typing.Optional[DataAndMetadata._DataAndMetadataLike], ProcessorConnection] = None,
                 display_range: typing.Union[typing.Optional[typing.Tuple[float, float]], ProcessorConnection] = None,
                 adjustments: typing.Union[typing.Optional[typing.Sequence[Persistence.PersistentDictType]], ProcessorConnection] = None) -> None:
        super().__init__(normalized_data=normalized_data, display_data=display_data, display_range=display_range, adjustments=adjustments)

    def _execute(self) -> None:
        display_data_and_metadata = self._get_data_and_metadata_like("display_data")
        display_range = typing.cast(typing.Optional[typing.Tuple[float, float]], self._get_parameter("display_range"))
        adjustments = typing.cast(typing.Optional[typing.Sequence[Persistence.PersistentDictType]], self._get_parameter("adjustments"))
        adjusted_data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = display_data_and_metadata
        if adjustments:
            # only request normalized data and metadata if required
            normalized_data_and_metadata = self._get_data_and_metadata_like("normalized_data")
            adjusted_data_and_metadata = normalized_data_and_metadata
            for adjustment_d in adjustments:
                adjustment = adjustment_factory(adjustment_d)
                if adjustment:
                    display_range = display_range
                    if adjusted_data_and_metadata and display_range is not None:
                        display_data = adjusted_data_and_metadata.data
                        if display_data is not None:
                            adjusted_data_and_metadata = DataAndMetadata.new_data_and_metadata(
                                adjustment.transform(display_data, display_range),
                                timestamp=adjusted_data_and_metadata.timestamp,
                                timezone=adjusted_data_and_metadata.timezone,
                                timezone_offset=adjusted_data_and_metadata.timezone_offset)
        self.set_result("data", adjusted_data_and_metadata)


class AdjustedDisplayRangeProcessor(ProcessorBase):
    def __init__(self, *,
                 display_range: typing.Union[typing.Optional[typing.Tuple[float, float]], ProcessorConnection] = None,
                 adjustments: typing.Union[typing.Optional[typing.Sequence[Persistence.PersistentDictType]], ProcessorConnection] = None) -> None:
        super().__init__(display_range=display_range, adjustments=adjustments)

    def _execute(self) -> None:
        display_range = typing.cast(typing.Optional[typing.Tuple[float, float]], self._get_parameter("display_range"))
        adjustments = typing.cast(typing.Optional[typing.Sequence[Persistence.PersistentDictType]], self._get_parameter("adjustments"))
        adjusted_display_range: typing.Optional[typing.Tuple[float, float]]
        if adjustments:
            # transforms have already been applied and data is now in the range of 0.0, 1.0.
            # brightness and contrast will be applied on top of this transform.
            adjusted_display_range = 0.0, 1.0
        else:
            adjusted_display_range = display_range
        self.set_result("display_range", adjusted_display_range)


class TransformedDisplayRangeProcessor(ProcessorBase):
    def __init__(self, *,
                 adjusted_display_range: typing.Union[typing.Optional[typing.Tuple[float, float]], ProcessorConnection] = None,
                 brightness: typing.Union[typing.Optional[float], ProcessorConnection] = None,
                 contrast: typing.Union[typing.Optional[float], ProcessorConnection] = None) -> None:
        super().__init__(adjusted_display_range=adjusted_display_range, brightness=brightness, contrast=contrast)

    def _execute(self) -> None:
        adjusted_display_range = typing.cast(typing.Optional[typing.Tuple[float, float]], self._get_parameter("adjusted_display_range"))
        brightness = self._get_float("brightness")
        contrast = self._get_float("contrast")
        assert adjusted_display_range is not None
        display_limit_low, display_limit_high = adjusted_display_range
        m = (contrast / (display_limit_high - display_limit_low)) if contrast > 0 and display_limit_high != display_limit_low else 1
        b = 1 / (2 * m) - (1 - brightness) * (display_limit_high - display_limit_low) / 2 - display_limit_low
        # back calculate the display limits as they would be with brightness/contrast adjustments
        transformed_display_range = (0 - m * b) / m, (1 - m * b) / m
        self.set_result("display_range", transformed_display_range)


class TransformedDataProcessor(ProcessorBase):
    def __init__(self, *,
                 adjusted_data: typing.Union[typing.Optional[DataAndMetadata._DataAndMetadataLike], ProcessorConnection] = None,
                 transformed_display_range: typing.Union[typing.Optional[typing.Tuple[float, float]], ProcessorConnection] = None) -> None:
        super().__init__(adjusted_data=adjusted_data, transformed_display_range=transformed_display_range)

    def _execute(self) -> None:
        adjusted_data_and_metadata = self._get_data_and_metadata_like("adjusted_data")
        transformed_display_range = typing.cast(typing.Optional[typing.Tuple[float, float]], self._get_parameter("transformed_display_range"))
        transformed_data_and_metadata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        if adjusted_data_and_metadata:
            transformed_data_and_metadata = Core.function_rescale(adjusted_data_and_metadata, data_range=(0.0, 1.0), in_range=transformed_display_range)
        self.set_result("data", transformed_data_and_metadata)



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

        self.__data_and_metadata = data_and_metadata
        self.__color_map_data = color_map_data

        self.__element_data_processor = ElementDataProcessor(data=data_and_metadata,
                                                             sequence_index=sequence_index,
                                                             collection_index=collection_index,
                                                             slice_center=slice_center,
                                                             slice_width=slice_width)

        self.__display_data_processor = DisplayDataProcessor(
            element_data=ProcessorConnection(self.__element_data_processor, "data", "element_data"),
            complex_display_type=complex_display_type)

        self.__data_range_processor = DataRangeProcessor(
            data=data_and_metadata,
            display_data=ProcessorConnection(self.__display_data_processor, "data", "display_data"),
        )

        self.__data_sample_processor = DataSampleProcessor(
            data=data_and_metadata,
            display_data=ProcessorConnection(self.__display_data_processor, "data", "display_data"),
        )

        self.__display_range_processor = DisplayRangeProcessor(
            element_data=ProcessorConnection(self.__element_data_processor, "data", "element_data"),
            display_limits=display_limits,
            complex_display_type=complex_display_type,
            data_range=ProcessorConnection(self.__data_range_processor, "data_range"),
            data_sample=ProcessorConnection(self.__data_sample_processor, "data_sample"),
        )

        self.__normalized_data_processor = NormalizedDataProcessor(
            display_data=ProcessorConnection(self.__display_data_processor, "data", "display_data"),
            display_range=ProcessorConnection(self.__display_range_processor, "display_range"),
        )

        self.__adjusted_data_processor = AdjustedDataProcessor(
            normalized_data=ProcessorConnection(self.__normalized_data_processor, "data", "normalized_data"),
            display_data=ProcessorConnection(self.__display_data_processor, "data", "display_data"),
            display_range=ProcessorConnection(self.__display_range_processor, "display_range"),
            adjustments=adjustments,
        )

        self.__adjusted_display_range_processor = AdjustedDisplayRangeProcessor(
            display_range=ProcessorConnection(self.__display_range_processor, "display_range"),
            adjustments=adjustments
        )

        self.__transformed_display_range_processor = TransformedDisplayRangeProcessor(
            adjusted_display_range=ProcessorConnection(self.__adjusted_display_range_processor, "display_range", "adjusted_display_range"),
            brightness=brightness,
            contrast=contrast
        )

        self.__display_rgb_processor = DisplayRGBProcessor(
            adjusted_data=ProcessorConnection(self.__adjusted_data_processor, "data", "adjusted_data"),
            data_range=ProcessorConnection(self.__data_range_processor, "data_range"),
            display_range=ProcessorConnection(self.__transformed_display_range_processor, "display_range"),
            color_map_data=color_map_data
        )

        self.__transformed_data_processor = TransformedDataProcessor(
            adjusted_data=ProcessorConnection(self.__adjusted_data_processor, "data", "adjusted_data"),
            transformed_display_range=ProcessorConnection(self.__transformed_display_range_processor, "display_range", "transformed_display_range"),
        )

        def finalize() -> None:
            DisplayValues._count -= 1

        weakref.finalize(self, finalize)

    @property
    def color_map_data(self) -> typing.Optional[_RGBA32Type]:
        return self.__color_map_data

    @property
    def data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.__data_and_metadata

    @property
    def display_rgba_timestamp(self) -> typing.Optional[datetime.datetime]:
        return self.__data_and_metadata.timestamp if self.__data_and_metadata else None

    @property
    def element_data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return typing.cast(typing.Optional[DataAndMetadata.DataAndMetadata], self.__element_data_processor.get_result("data"))

    @property
    def display_data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return typing.cast(typing.Optional[DataAndMetadata.DataAndMetadata], self.__display_data_processor.get_result("data"))

    @property
    def data_range(self) -> typing.Optional[typing.Tuple[float, float]]:
        return typing.cast(typing.Optional[typing.Tuple[float, float]], self.__data_range_processor.get_result("data_range"))

    @property
    def data_sample(self) -> typing.Optional[_ImageDataType]:
        return typing.cast(typing.Optional[_ImageDataType], self.__data_sample_processor.get_result("data_sample"))

    @property
    def display_range(self) -> typing.Optional[typing.Tuple[float, float]]:
        return typing.cast(typing.Optional[typing.Tuple[float, float]], self.__display_range_processor.get_result("display_range"))

    @property
    def display_rgba(self) -> typing.Optional[_ImageDataType]:
        return typing.cast(typing.Optional[_ImageDataType], self.__display_rgb_processor.get_result("display_rgba"))

    @property
    def normalized_data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return typing.cast(typing.Optional[DataAndMetadata.DataAndMetadata], self.__normalized_data_processor.get_result("data"))

    @property
    def adjusted_data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return typing.cast(typing.Optional[DataAndMetadata.DataAndMetadata], self.__adjusted_data_processor.get_result("data"))

    @property
    def adjusted_display_range(self) -> typing.Optional[typing.Tuple[float, float]]:
        return typing.cast(typing.Optional[typing.Tuple[float, float]], self.__adjusted_display_range_processor.get_result("display_range"))

    @property
    def transformed_data_and_metadata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return typing.cast(typing.Optional[DataAndMetadata.DataAndMetadata], self.__transformed_data_processor.get_result("data"))

    @property
    def transformed_display_range(self) -> typing.Tuple[float, float]:
        return typing.cast(typing.Tuple[float, float], self.__transformed_display_range_processor.get_result("display_range"))

    def get_calibration_styles(self) -> typing.Sequence[CalibrationStyle]:
        return get_calibration_styles([self.display_data_and_metadata])

    def get_intensity_calibration_styles(self) -> typing.Sequence[CalibrationStyle]:
        return get_intensity_calibration_styles([self.display_data_and_metadata])


DisplayValuesSubscription = object


class DisplayDataChannel(Persistence.PersistentObject):
    _executor = concurrent.futures.ThreadPoolExecutor()
    _force_sync = 0  # for running tests

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

        self.__current_data_item: typing.Optional[DataItem.DataItem] = None
        self.__current_data_item_modified_count = 0
        self.__display_ref_count = 0

        self.__slice_interval: typing.Optional[typing.Tuple[float, float]] = None

        data_item_specifier = Persistence.read_persistent_specifier(self.data_item_reference) if self.data_item_reference else None
        self.__data_item_reference = self.create_item_reference(item_specifier=data_item_specifier, item=data_item)

        self.__old_data_shape: typing.Optional[DataAndMetadata.ShapeType] = None

        self.__color_map_data: typing.Optional[_RGBA32Type] = None
        self.modified_state = 0

        self.data_item_proxy_changed_event = Event.Event()

        # fields for computing display values on a thread. there are two streams: one for uncomputed values and one
        # for computed values. the caller must subscribe to either stream. the computed values stream is only started
        # when there are subscribers.
        self.__closing = False
        self.__display_values_update_lock = threading.RLock()
        self.__display_values_future: typing.Optional[concurrent.futures.Future[typing.Optional[DisplayValues]]] = None
        self.__has_pending_display_values = False
        self.__display_values_stream = Stream.ValueStream[DisplayValues]()
        self.__computed_display_values_stream = Stream.ValueStream[DisplayValues]()
        self.__computed_display_values_subscription_count = 0

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

        self.__is_data_item_connected = False

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
                self.__is_data_item_connected = True
            if self.__data_item:
                for _ in range(self.__display_ref_count):
                    self.__data_item.increment_data_ref_count()
            self.__last_data_item = self.__data_item
            # until this gets cleaned up, the data_item changed notification needs to go before the proxy changed
            # event. the notification ensures that the 'data_items_model' is updated properly first. when
            # data_item_proxy_changed is fired, it assumes that data_items_model is already updated.
            self.notify_property_changed("data_item")
            self.data_item_proxy_changed_event.fire()

        def disconnect_data_item(data_item_: typing.Optional[Persistence.PersistentObject]) -> None:
            data_item = typing.cast(DataItem.DataItem, data_item_)
            # tell the data item that this display data channel is no longer referencing it
            if data_item:
                data_item.remove_display_data_channel(self)
                self.__is_data_item_connected = False
            self.notify_property_changed("data_item")

        self.__data_item_reference.on_item_registered = connect_data_item
        self.__data_item_reference.on_item_unregistered = disconnect_data_item

        if self.__data_item_reference.item:
            connect_data_item(typing.cast(DataItem.DataItem, self.__data_item_reference.item))

    def close(self) -> None:
        # ensure display data channel is disconnected from the data item in case it was never added to document
        # and subsequently about_to_be_removed is not called.
        if self.__is_data_item_connected and (data_item := self.data_item):
            data_item.remove_display_data_channel(self)
            self.__is_data_item_connected = False
        self.__data_item_reference.on_item_registered = None
        self.__data_item_reference.on_item_unregistered = None
        self.__closing = True
        # wait for display values threads to finish. first notify the thread that we are closing, then wait for it
        # to complete by getting the future and waiting for it to complete. then clear the streams to release any
        # resources (display values).
        with self.__display_values_update_lock:
            display_values_future = self.__display_values_future
        if display_values_future:
            display_values_future.result()
        self.__display_values_stream = typing.cast(typing.Any, None)
        self.__computed_display_values_stream = typing.cast(typing.Any, None)
        # continue close.
        self.__disconnect_data_item_events()
        self.__current_data_item = None
        super().close()

    def about_to_be_inserted(self, container: Persistence.PersistentObject) -> None:
        super().about_to_be_inserted(container)
        self.notify_property_changed("display_item")  # used for implicit connections

    def about_to_be_removed(self, container: Persistence.PersistentObject) -> None:
        # tell the data item that this display data channel is no longer referencing it
        if self.__data_item:
            self.__data_item.remove_display_data_channel(self)
            self.__is_data_item_connected = False
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
    def display_data_shape(self) -> typing.Optional[DataAndMetadata.ShapeType]:
        if data_item := self.__data_item:
            return DisplayDataShapeCalculator(data_item.data_metadata).shape
        return None

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
    def dimensional_shape(self) -> typing.Optional[DataAndMetadata.ShapeType]:
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

    @property
    def datum_calibrations(self) -> typing.Optional[typing.Sequence[Calibration.Calibration]]:
        """The calibrations for only datum dimensions."""
        if data_item := self.__data_item:
            return DisplayDataShapeCalculator(data_item.data_metadata).calibrations
        return None

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
            self.__queue_display_values_update()

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
            self.__current_data_item = self.__data_item
            self.__current_data_item_modified_count = self.__data_item.modified_count if self.__data_item else 0
            self.__queue_display_values_update()

    def get_latest_computed_display_values(self) -> typing.Optional[DisplayValues]:
        # returns the latest computed display values.
        return self.__computed_display_values_stream.value

    def subscribe_to_latest_computed_display_values(self, callback: typing.Callable[[typing.Optional[DisplayValues]], None]) -> DisplayValuesSubscription:
        # returns a subscription to the latest computed display values.
        # track the subscription count to only compute display values when there is at least one subscriber.

        self.__computed_display_values_subscription_count += 1
        subscription = Stream.ValueStreamAction(self.__computed_display_values_stream, callback)

        def subscription_finalized(display_data_channel: DisplayDataChannel) -> None:
            display_data_channel.__computed_display_values_subscription_count -= 1

        weakref.finalize(subscription, ReferenceCounting.weak_partial(subscription_finalized, self))

        return subscription

    def get_display_values_stream(self) -> Stream.ValueStream[DisplayValues]:
        # returns the latest possibly-not-yet-computed display values.
        return self.__display_values_stream

    def get_latest_display_values(self) -> typing.Optional[DisplayValues]:
        # returns the latest possibly-not-yet-computed display values.
        return self.__display_values_stream.value

    def subscribe_to_latest_display_values(self, callback: typing.Callable[[typing.Optional[DisplayValues]], None]) -> DisplayValuesSubscription:
        return Stream.ValueStreamAction(self.__display_values_stream, callback)

    def __queue_display_values_update(self) -> None:
        # queue a display values update.
        # there are two display values streams: one for the latest possibly-not-yet-computed display values, and one
        # for the latest computed display values.
        # the latest possibly-not-yet-computed display values are computed on a background thread, and the latest
        # computed display values are computed on the callers thread (which should not be the main thread).
        # an overarching goal is to never compute the display values on the main thread, which would prevent the
        # rest of the UI from activity, which would prevent smooth updating.

        # make display values. this can be converted to a method as it gets more complicated.
        def make_display_values() -> typing.Optional[DisplayValues]:
            if self.__data_item:
                return DisplayValues(self.__data_item.xdata,
                                     self.sequence_index,
                                     self.collection_index,
                                     self.slice_center, self.slice_width,
                                     self.display_limits,
                                     self.complex_display_type,
                                     self.__color_map_data, self.brightness,
                                     self.contrast, self.adjustments)
            return None

        # the method to compute the display values on the background thread.
        # as long as this display data channel is not closing, check whether there are pending display values to
        # compute, and if so, compute them up to the adjusted_data_and_metadata level.
        # a future change may allow the subscriber to specify the level of computation, but for now, this is the
        # only level of computation.
        def compute_display_values() -> None:
            while not self.__closing:
                display_values: typing.Optional[DisplayValues] = None
                with self.__display_values_update_lock:
                    if self.__has_pending_display_values:
                        display_values = self.__display_values_stream.value
                        self.__has_pending_display_values = False
                if display_values:
                    try:
                        with Process.audit("compute_display_values"):
                            # getattr(display_values, "display_rgba")  # too slow and not needed in most cases.
                            getattr(display_values, "adjusted_data_and_metadata")
                    except Exception as e:
                        pass
                    self.__computed_display_values_stream.send_value(display_values)
                with self.__display_values_update_lock:
                    if not self.__has_pending_display_values:
                        self.__display_values_future = None
                        break

        # use this only for _force_sync below.
        display_values_future: typing.Optional[concurrent.futures.Future[typing.Optional[DisplayValues]]] = None

        with self.__display_values_update_lock:
            display_values = make_display_values()
            self.__has_pending_display_values = True
            # send the display values to the latest possibly-not-yet-computed display values stream.
            self.__display_values_stream.send_value(display_values)
            if not self.__display_values_future:
                if self.__computed_display_values_subscription_count > 0:
                    # if not already computing display values, start computing display values on the background thread.
                    display_values_future = DisplayDataChannel._executor.submit(functools.partial(compute_display_values))
                    self.__display_values_future = display_values_future
                else:
                    # if no subscribers, send to the computed display values stream immediately. this allows future
                    # subscribers to get the proper value at the cost of a little extra computation in the caller's
                    # thread.
                    self.__computed_display_values_stream.send_value(display_values)
                    self.__has_pending_display_values = False

        # force sync is used for testing where we want to ensure that the display values are computed before continuing.
        if DisplayDataChannel._force_sync:
            if display_values_future:
                display_values_future.result()

    def increment_display_ref_count(self, amount: int = 1) -> None:
        """Increment display reference count to indicate this library item is currently displayed."""
        self.__display_ref_count += amount
        if self.__data_item:
            for _ in range(amount):
                self.__data_item.increment_data_ref_count()

    def decrement_display_ref_count(self, amount: int = 1) -> None:
        """Decrement display reference count to indicate this library item is no longer displayed."""
        assert not self._closed
        self.__display_ref_count -= amount
        if self.__data_item:
            for _ in range(amount):
                self.__data_item.decrement_data_ref_count()

    @property
    def _display_ref_count(self) -> int:
        return self.__display_ref_count

    def reset_display_limits(self) -> None:
        """Reset display limits so that they are auto calculated whenever the data changes."""
        self.display_limits = None


def display_data_channel_factory(lookup_id: typing.Callable[[str], str]) -> DisplayDataChannel:
    return DisplayDataChannel()


class DisplayLayer(Schema.Entity):
    data_row = Schema.EntityAttribute[typing.Optional[int]]()
    label = Schema.EntityAttribute[typing.Optional[str]]()
    stroke_color = Schema.EntityAttribute[typing.Optional[str]]()
    fill_color = Schema.EntityAttribute[typing.Optional[str]]()
    stroke_width = Schema.EntityAttribute[typing.Optional[int]]()
    display_data_channel = Schema.EntityAttribute[typing.Optional[DisplayDataChannel]]()

    def __init__(self, display_layer_properties: typing.Optional[Persistence.PersistentDictType] = None) -> None:
        super().__init__(Model.DisplayLayer)
        self.persistent_storage: typing.Optional[Persistence.PersistentStorageInterface] = None
        self.display_data_channel = None
        display_layer_properties = display_layer_properties or dict()
        for k, v in display_layer_properties.items():
            setattr(self, k, v)

    @property
    def display_item(self) -> DisplayItem:
        return typing.cast(DisplayItem, self.container)

    def _create(self, context: typing.Optional[Schema.EntityContext]) -> Schema.Entity:
        display_layer = DisplayLayer()
        if context:
            display_layer._set_entity_context(context)
        return display_layer

    def get_display_layer_properties(self) -> Persistence.PersistentDictType:
        display_layer_properties = self.write_to_dict()
        display_layer_properties.pop("uuid", None)
        display_layer_properties.pop("modified", None)
        display_layer_properties.pop("display_data_channel", None)
        return display_layer_properties

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


@dataclasses.dataclass
class DisplayItemSaveProperties:
    display_properties: Persistence.PersistentDictType
    display_layers_list: typing.List[Persistence.PersistentDictType]
    calibration_style_id: str
    intensity_calibration_style_id: str


class DisplayDataShapeCalculator:
    """Display data shape calculator.

    Represents a calculation to look at data metadata and determine the dimensions used for display. The shape and
    calibrations can be accessed as properties.

    This is a heuristic to determine the dimensions used for display, and this class consolidates the algorithm to
    this location.
    """
    def __init__(self, data_metadata: typing.Optional[DataAndMetadata.DataMetadata]) -> None:
        self.shape: typing.Optional[DataAndMetadata.ShapeType] = None
        self.calibrations: typing.Optional[typing.Sequence[Calibration.Calibration]] = None

        if data_metadata:
            dimensional_calibrations = data_metadata.dimensional_calibrations
            dimensional_shape = data_metadata.dimensional_shape
            next_dimension = 0
            if data_metadata.is_sequence:
                next_dimension += 1
            if data_metadata.is_collection:
                collection_dimension_count = data_metadata.collection_dimension_count
                datum_dimension_count = data_metadata.datum_dimension_count
                # next dimensions are treated as collection indexes.
                if collection_dimension_count == 2 and datum_dimension_count == 1:
                    self.shape = tuple(dimensional_shape[next_dimension:next_dimension + collection_dimension_count])
                    self.calibrations = dimensional_calibrations[next_dimension:next_dimension + collection_dimension_count]
                else:  # default, "pick"
                    self.shape = tuple(dimensional_shape[next_dimension + collection_dimension_count:next_dimension + collection_dimension_count + datum_dimension_count])
                    self.calibrations = dimensional_calibrations[next_dimension + collection_dimension_count:next_dimension + collection_dimension_count + datum_dimension_count]
            else:
                self.shape = tuple(dimensional_shape[next_dimension:])
                self.calibrations = dimensional_calibrations[next_dimension:]


class CalibrationDescriptionLike:

    @property
    def calibration_style_id(self) -> str: raise NotImplementedError()

    @property
    def calibration_style_type(self) -> str: raise NotImplementedError()

    @property
    def dimension_set_id(self) -> str: raise NotImplementedError()

    @property
    def intensity_calibration(self) -> typing.Optional[Calibration.Calibration]: raise NotImplementedError()

    @property
    def dimensional_calibrations(self) -> typing.Optional[DataAndMetadata.CalibrationListType]: raise NotImplementedError()


@dataclasses.dataclass
class CalibrationDescription:
    calibration_style_id: str
    calibration_style_type: str
    dimension_set_id: str
    intensity_calibration: typing.Optional[Calibration.Calibration]
    dimensional_calibrations: typing.Optional[DataAndMetadata.CalibrationListType]

    def __hash__(self) -> int:
        return hash((self.calibration_style_id, self.calibration_style_type, self.dimension_set_id))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CalibrationDescription):
            return False
        return (self.calibration_style_id == other.calibration_style_id and
                self.calibration_style_type == other.calibration_style_type and
                self.dimension_set_id == other.dimension_set_id)


class CalibrationProvider(typing.Protocol):
    def get_calibration_descriptions(self, data_metadata: DataAndMetadata.DataMetadata) -> typing.Sequence[CalibrationDescriptionLike]: ...


def get_calibration_descriptions(xdata_list: typing.Sequence[typing.Optional[DataAndMetadata.DataAndMetadata]]) -> typing.Sequence[CalibrationDescription]:
    all_calibration_descriptions = list[CalibrationDescription]()
    common_calibration_descriptions = set[CalibrationDescription]()
    for xdata in xdata_list:
        if xdata:
            xdata_calibration_descriptions = list[CalibrationDescription]()
            for component in Registry.get_components_by_type("calibration-provider"):
                calibration_provider = typing.cast(CalibrationProvider, component)
                if calibration_provider:
                    calibration_description_likes = calibration_provider.get_calibration_descriptions(xdata.data_metadata)
                    for calibration_description_like in calibration_description_likes:
                        calibration_description = CalibrationDescription(
                            calibration_description_like.calibration_style_id,
                            calibration_description_like.calibration_style_type,
                            calibration_description_like.dimension_set_id,
                            calibration_description_like.intensity_calibration,
                            calibration_description_like.dimensional_calibrations)
                        xdata_calibration_descriptions.append(calibration_description)
            if not all_calibration_descriptions:
                all_calibration_descriptions = xdata_calibration_descriptions
                common_calibration_descriptions = set(xdata_calibration_descriptions)
            common_calibration_descriptions.intersection_update(xdata_calibration_descriptions)
    return [calibration_description for calibration_description in all_calibration_descriptions if calibration_description in common_calibration_descriptions]


def get_calibration_styles(xdata_list: typing.Sequence[typing.Optional[DataAndMetadata.DataAndMetadata]]) -> typing.Sequence[CalibrationStyle]:
    calibration_styles = list[CalibrationStyle]()
    calibration_styles.append(CalibrationStyleNative())
    calibration_descriptions = get_calibration_descriptions(xdata_list)
    for calibration_description in calibration_descriptions:
        if calibration_description.calibration_style_id == "spatial":
            calibration_styles.append(CalibrationDescriptionCalibrationStyle(_("Spatial"), calibration_description))
        elif calibration_description.calibration_style_id == "temporal":
            calibration_styles.append(CalibrationDescriptionCalibrationStyle(_("Temporal"), calibration_description))
        elif calibration_description.calibration_style_id == "angular":
            calibration_styles.append(CalibrationDescriptionCalibrationStyle(_("Angular"), calibration_description))
    calibration_styles.append(CalibrationStylePixelsTopLeft())
    calibration_styles.append(CalibrationStylePixelsCenter())
    calibration_styles.append(CalibrationStyleFractionalTopLeft())
    calibration_styles.append(CalibrationStyleFractionalCenter())
    return calibration_styles


def get_intensity_calibration_styles(xdata_list: typing.Sequence[typing.Optional[DataAndMetadata.DataAndMetadata]]) -> typing.Sequence[CalibrationStyle]:
    calibration_styles = list[CalibrationStyle]()
    calibration_styles.append(CalibrationStyleNative())
    calibration_descriptions = get_calibration_descriptions(xdata_list)
    for calibration_description in calibration_descriptions:
        if calibration_description.calibration_style_id.startswith("intensity"):
            calibration_styles.append(CalibrationDescriptionCalibrationStyle(_("Calibrated"), calibration_description))
    calibration_styles.append(IntensityCalibrationStyleUncalibrated())
    return calibration_styles


@dataclasses.dataclass
class DisplayDataDelta:
    graphics: typing.Sequence[Graphics.Graphic]
    graphic_selection: GraphicSelection
    display_calibration_info: DisplayCalibrationInfo
    display_values_list: typing.List[typing.Optional[DisplayValues]]
    display_properties: Persistence.PersistentDictType
    display_layers_list: typing.List[Persistence.PersistentDictType]
    graphics_changed: bool = False
    graphic_selection_changed: bool = False
    display_calibration_info_changed: bool = False
    display_values_list_changed: bool = False
    display_properties_changed: bool = False
    display_layers_list_changed: bool = False

    def mark_changed(self) -> None:
        self.graphics_changed = True
        self.graphic_selection_changed = True
        self.display_calibration_info_changed = True
        self.display_values_list_changed = True
        self.display_properties_changed = True
        self.display_layers_list_changed = True


class DisplayDataDeltaStream(Stream.ValueStream[DisplayDataDelta]):
    """Display data tracker.

    Observe a data item form the dimensional calibrations, intensity calibration, scales, dimensional
    shape, and is composite data properties of the display item, the display values list, the graphics,
    the graphic selection, the display layers, and the display properties.
    """

    def __init__(self,
                 display_item: DisplayItem,
                 calibration_style_id_stream: Stream.PropertyChangedEventStream[str],
                 intensity_calibration_style_id_stream: Stream.PropertyChangedEventStream[str],
                 ) -> None:
        super().__init__()

        self.__display_item_ref = weakref.ref(display_item)

        self.__display_values_list = list[typing.Optional[DisplayValues]]()
        self.__display_data_channel_actions = list[typing.Optional[Stream.ValueStreamAction[DisplayValues]]]()

        self.__dimensional_calibrations: typing.Optional[DataAndMetadata.CalibrationListType] = None
        self.__intensity_calibration: typing.Optional[Calibration.Calibration] = None
        self.__scales = 0.0, 1.0
        self.__dimensional_shape: typing.Optional[DataAndMetadata.ShapeType] = None
        self.__is_composite_data: bool = False
        self.__graphics = list[Graphics.Graphic]()
        self.__graphic_selection = copy.copy(display_item.graphic_selection)
        self.__display_layers = list[DisplayLayer]()
        self.__display_layers_list = list[Persistence.PersistentDictType]()
        self.__display_properties = copy.deepcopy(display_item.display_properties)

        self.__last_display_data_delta: typing.Optional[DisplayDataDelta] = None

        self.__calibration_style_id_stream = calibration_style_id_stream
        self.__intensity_calibration_style_id_stream = intensity_calibration_style_id_stream

        self.__display_item_item_inserted_listener = display_item.item_inserted_event.listen(ReferenceCounting.weak_partial(DisplayDataDeltaStream.__display_item_item_inserted, self))
        self.__display_item_item_removed_listener = display_item.item_removed_event.listen(ReferenceCounting.weak_partial(DisplayDataDeltaStream.__display_item_item_removed, self))
        self.__graphic_changed_listeners = list[typing.Optional[Event.EventListener]]()
        self.__display_layer_changed_listeners = list[typing.Optional[Event.EventListener]]()

        self.__graphic_selection_changed_event_listener = display_item.graphic_selection_changed_event.listen(ReferenceCounting.weak_partial(DisplayDataDeltaStream.__graphic_selection_changed, self))
        self.__graphic_changed_event_listener = display_item.graphics_changed_event.listen(ReferenceCounting.weak_partial(DisplayDataDeltaStream.__graphics_changed, self))

        self.__display_properties_changed_event_listener = display_item.property_changed_event.listen(ReferenceCounting.weak_partial(DisplayDataDeltaStream.__display_item_properties_changed, self))

        self.__calibration_style_id_stream_action = Stream.ValueStreamAction(calibration_style_id_stream, ReferenceCounting.weak_partial(DisplayDataDeltaStream.__update_display_calibration_info, self))

        self.__intensity_calibration_style_id_stream_action = Stream.ValueStreamAction(intensity_calibration_style_id_stream, ReferenceCounting.weak_partial(DisplayDataDeltaStream.__update_display_calibration_info, self))

        for index, display_data_channel in enumerate(display_item.display_data_channels):
            self.__display_item_item_inserted("display_data_channels", display_data_channel, index)

        for index, graphic in enumerate(display_item.graphics):
            self.__display_item_item_inserted("graphics", graphic, index)

        for index, display_layer in enumerate(display_item.display_layers):
            self.__display_item_item_inserted("display_layers", display_layer, index)

        self.__update()
        self.__send_delta()

    def __send_delta(self) -> None:
        display_data_delta = DisplayDataDelta(list(self.graphics),
                                              copy.copy(self.graphic_selection),
                                              self.__get_display_calibration_info(),
                                              list(self.__display_values_list),
                                              copy.deepcopy(self.display_properties),
                                              list(self.display_layers))
        if self.__last_display_data_delta:
            if display_data_delta.graphics != self.__last_display_data_delta.graphics:
                display_data_delta.graphics_changed = True
            if display_data_delta.graphic_selection != self.__last_display_data_delta.graphic_selection:
                display_data_delta.graphic_selection_changed = True
            if display_data_delta.display_calibration_info != self.__last_display_data_delta.display_calibration_info:
                display_data_delta.display_calibration_info_changed = True
            if display_data_delta.display_values_list != self.__last_display_data_delta.display_values_list:
                display_data_delta.display_values_list_changed = True
            if display_data_delta.display_properties != self.__last_display_data_delta.display_properties:
                display_data_delta.display_properties_changed = True
            if display_data_delta.display_layers_list != self.__last_display_data_delta.display_layers_list:
                display_data_delta.display_layers_list_changed = True
        else:
            display_data_delta.mark_changed()
        self.__last_display_data_delta = display_data_delta
        self.send_value(display_data_delta)

    @property
    def dimensional_calibrations(self) -> typing.Optional[DataAndMetadata.CalibrationListType]:
        return self.__dimensional_calibrations

    @property
    def intensity_calibration(self) -> typing.Optional[Calibration.Calibration]:
        return self.__intensity_calibration

    @property
    def scales(self) -> typing.Tuple[float, float]:
        return self.__scales

    @property
    def dimensional_shape(self) -> typing.Optional[DataAndMetadata.ShapeType]:
        return self.__dimensional_shape

    @property
    def metadata(self) -> typing.Optional[DataAndMetadata.MetadataType]:
        return self.__metadata

    @property
    def is_composite_data(self) -> bool:
        return self.__is_composite_data

    @property
    def graphics(self) -> typing.Sequence[Graphics.Graphic]:
        return self.__graphics

    @property
    def graphic_selection(self) -> GraphicSelection:
        return self.__graphic_selection

    @property
    def display_layers(self) -> typing.Sequence[Persistence.PersistentDictType]:
        return self.__display_layers_list

    @property
    def display_properties(self) -> Persistence.PersistentDictType:
        return self.__display_properties

    def __display_item_item_inserted(self, key: str, item: typing.Any, index: int) -> None:
        if key == "display_data_channels":
            display_data_channel = typing.cast(typing.Optional[DisplayDataChannel], item)
            display_values_stream = display_data_channel.get_display_values_stream() if display_data_channel else None
            display_values = display_values_stream.value if display_values_stream else None
            self.__display_values_list.insert(index, display_values)
            self.__display_data_channel_actions.insert(index, Stream.ValueStreamAction(display_values_stream, ReferenceCounting.weak_partial(DisplayDataDeltaStream.__display_data_channel_display_values_changed, self, display_data_channel)) if display_values_stream else None)
            # send the update
            self.__update()
            self.__send_delta()
        elif key == "graphics":
            self.__graphics.insert(index, item)
            self.__graphic_changed_listeners.append(item.property_changed_event.listen(ReferenceCounting.weak_partial(DisplayDataDeltaStream.__graphic_changed, self)))
            self.__update()
            self.__send_delta()
        elif key == "display_layers":
            display_item = self.__display_item
            self.__display_layers.insert(index, item)
            self.__display_layers_list = display_item.display_layers_list
            self.__display_layer_changed_listeners.append(item.property_changed_event.listen(ReferenceCounting.weak_partial(DisplayDataDeltaStream.__display_layer_changed, self)))
            self.__update()
            self.__send_delta()

    def __display_item_item_removed(self, key: str, item: typing.Any, index: int) -> None:
        if key == "display_data_channels":
            self.__display_values_list.pop(index)
            self.__display_data_channel_actions.pop(index)
            # send the update
            self.__update()
            self.__send_delta()
        elif key == "graphics":
            self.__graphics.pop(index)
            self.__graphic_changed_listeners.pop(index)
            self.__send_delta()
        elif key == "display_layers":
            display_item = self.__display_item
            self.__display_layers.pop(index)
            self.__display_layers_list = display_item.display_layers_list
            self.__display_layer_changed_listeners.pop(index)
            self.__send_delta()

    def __display_data_channel_display_values_changed(self, display_data_channel: DisplayDataChannel, display_values: typing.Optional[DisplayValues]) -> None:
        display_item = self.__display_item
        index = display_item.display_data_channels.index(display_data_channel)
        self.__display_values_list[index] = display_values
        # send the update
        self.__update()
        self.__send_delta()

    def __graphic_changed(self, name: str) -> None:
        if self.__last_display_data_delta:
            self.__last_display_data_delta.graphics = list()
        self.__send_delta()

    def __display_layer_changed(self, name: str) -> None:
        display_item = self.__display_item
        self.__display_layers_list = display_item.display_layers_list
        self.__send_delta()

    @property
    def __display_item(self) -> DisplayItem:
        display_item = self.__display_item_ref()
        assert display_item
        return display_item

    def __graphic_selection_changed(self, graphic_selection: GraphicSelection) -> None:
        self.__graphic_selection = copy.copy(graphic_selection)
        self.__send_delta()

    def __graphics_changed(self, graphic_selection: GraphicSelection) -> None:
        self.__graphic_selection = copy.copy(graphic_selection)
        self.__send_delta()

    def __display_item_properties_changed(self, property_name: str) -> None:
        if property_name == "display_properties":
            display_item = self.__display_item
            new_display_properties = display_item.display_properties
            if new_display_properties != self.__display_properties:
                self.__display_properties = copy.deepcopy(new_display_properties)
                self.__send_delta()

    def __get_xdata_list(self) -> typing.Sequence[typing.Optional[DataAndMetadata.DataAndMetadata]]:
        return [display_values.data_and_metadata if display_values else None for display_values in list(self.__display_values_list)]

    def __update(self) -> None:
        xdata_list = self.__get_xdata_list()
        dimensional_calibrations: typing.Optional[DataAndMetadata.CalibrationListType] = None
        intensity_calibration: typing.Optional[Calibration.Calibration] = None
        scales = 0.0, 1.0
        dimensional_shape: typing.Optional[DataAndMetadata.ShapeType] = None
        metadata: typing.Optional[DataAndMetadata.MetadataType] = None
        if xdata_list:
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
                            v = dimensional_calibrations[0].convert_from_calibrated_value(
                                xdata.dimensional_calibrations[-1].convert_to_calibrated_value(0))
                            mn = min(mn, v)
                            mx = max(mx, v)
                            v = dimensional_calibrations[0].convert_from_calibrated_value(
                                xdata.dimensional_calibrations[-1].convert_to_calibrated_value(xdata.dimensional_shape[-1]))
                            mn = min(mn, v)
                            mx = max(mx, v)
                    intensity_calibration = xdata0.intensity_calibration
                    if math.isfinite(mn) and math.isfinite(mx):
                        scales = mn, mx
                        dimensional_shape = (int(mx - mn),)
                    else:
                        scales = 0, xdata0.dimensional_shape[-1]
                        dimensional_shape = xdata0.dimensional_shape
            if xdata0 and len(xdata_list) == 1:
                metadata = xdata0.metadata
        self.__dimensional_calibrations = dimensional_calibrations
        self.__intensity_calibration = intensity_calibration
        self.__scales = scales
        self.__dimensional_shape = dimensional_shape
        self.__metadata = metadata
        self.__is_composite_data = len(xdata_list) > 1
        self.__display_layers_list = self.__display_item.display_layers_list

    def __get_display_calibration_info(self) -> DisplayCalibrationInfo:
        return DisplayCalibrationInfo(self.display_data_shape,
                                      self.scales,
                                      self.displayed_dimensional_calibrations,
                                      self.displayed_intensity_calibration,
                                      self.calibration_style,
                                      self.intensity_calibration_style,
                                      list(self.datum_calibrations))

    def __update_display_calibration_info(self, value: typing.Optional[str]) -> None:
        self.__update()
        self.__send_delta()

    def reset(self) -> None:
        self.__last_display_data_delta = None
        self.__update()
        self.__send_delta()

    @property
    def display_data_shape(self) -> typing.Optional[DataAndMetadata.ShapeType]:
        xdata_list = self.__get_xdata_list()
        if len(xdata_list) == 1 and (d := xdata_list[0]):
            return DisplayDataShapeCalculator(d.data_metadata).shape
        return self.dimensional_shape if self.is_composite_data else None

    @property
    def calibration_styles(self) -> typing.Sequence[CalibrationStyle]:
        return get_calibration_styles(self.__get_xdata_list())

    @property
    def intensity_calibration_styles(self) -> typing.Sequence[CalibrationStyle]:
        return get_intensity_calibration_styles(self.__get_xdata_list())

    def get_calibration_style_for_id(self, calibration_style_id: typing.Optional[str]) -> typing.Optional[CalibrationStyle]:
        for calibration_style in self.calibration_styles:
            if calibration_style.calibration_style_id == calibration_style_id:
                return calibration_style
        return None

    def get_intensity_calibration_style_for_id(self, calibration_style_id: typing.Optional[str]) -> typing.Optional[CalibrationStyle]:
        for calibration_style in self.intensity_calibration_styles:
            if calibration_style.calibration_style_id == calibration_style_id:
                return calibration_style
        return None

    @property
    def calibration_style(self) -> CalibrationStyle:
        return self.get_calibration_style_for_id(self.__calibration_style_id_stream.value) or CalibrationStyleNative()

    @property
    def intensity_calibration_style(self) -> CalibrationStyle:
        return self.get_intensity_calibration_style_for_id(self.__intensity_calibration_style_id_stream.value) or CalibrationStyleNative()

    @property
    def displayed_dimensional_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        """The calibrations for all data dimensions in the displayed calibration style."""
        if self.dimensional_calibrations and self.dimensional_shape:
            return self.calibration_style.get_dimensional_calibrations(self.dimensional_shape, self.dimensional_calibrations, self.metadata)
        return [Calibration.Calibration() for c in self.dimensional_calibrations] if self.dimensional_calibrations else [Calibration.Calibration()]

    @property
    def displayed_intensity_calibration(self) -> Calibration.Calibration:
        if self.intensity_calibration:
            return self.intensity_calibration_style.get_intensity_calibration(self.intensity_calibration)
        return Calibration.Calibration()

    @property
    def display_data_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        """The calibrations for only datum dimensions."""
        display_data_calibrations: typing.Optional[typing.Sequence[Calibration.Calibration]] = None
        xdata_list = self.__get_xdata_list()
        if len(xdata_list) == 1 and (d := xdata_list[0]):
            display_data_calibrations = DisplayDataShapeCalculator(d.data_metadata).calibrations
        return display_data_calibrations if display_data_calibrations else [Calibration.Calibration()]

    @property
    def displayed_datum_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        """The calibrations for only datum dimensions, in the displayed calibration style."""
        calibration_style = self.get_calibration_style_for_id(self.__calibration_style_id_stream.value)
        calibration_style = CalibrationStyleNative() if not calibration_style else calibration_style
        xdata_list = self.__get_xdata_list()
        dimensional_shape = self.dimensional_shape
        dimensional_calibrations = self.dimensional_calibrations
        if dimensional_calibrations and dimensional_shape and len(xdata_list) == 1:
            display_data_calibrations = self.display_data_calibrations
            display_data_calibrations = display_data_calibrations if display_data_calibrations else [Calibration.Calibration() for c in dimensional_calibrations]
            datum_calibrations = calibration_style.get_dimensional_calibrations(dimensional_shape, display_data_calibrations, self.metadata)
            if datum_calibrations:
                return datum_calibrations
        if self.is_composite_data:
            return self.displayed_dimensional_calibrations
        return [Calibration.Calibration() for c in dimensional_calibrations] if dimensional_calibrations else [Calibration.Calibration()]

    @property
    def datum_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        """The calibrations for only datum dimensions."""
        xdata_list = self.__get_xdata_list()
        if len(xdata_list) == 1 and (d := xdata_list[0]):
            datum_calibrations = DisplayDataShapeCalculator(d.data_metadata).calibrations
            if datum_calibrations is not None:
                return datum_calibrations
        dimensional_calibrations = self.dimensional_calibrations
        return [Calibration.Calibration() for c in dimensional_calibrations] if dimensional_calibrations else [Calibration.Calibration()]


class DisplayItem(Persistence.PersistentObject):
    DEFAULT_COLORS = ("#1E90FF", "#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#00FFFF", "#FF00FF", "#888888", "#880000", "#008800", "#000088", "#CCCCCC", "#888800", "#008888", "#880088", "#964B00")

    def __init__(self, item_uuid: typing.Optional[uuid.UUID] = None, *, data_item: typing.Optional[DataItem.DataItem] = None) -> None:
        super().__init__()
        if item_uuid:
            self.uuid = item_uuid
        self.define_type("display_item")
        self.define_property("created", DateTime.utcnow(), hidden=True, converter=DataItem.DatetimeToStringConverter(), changed=self.__property_changed)
        self.define_property("display_type", hidden=True, changed=self.__display_type_changed)
        self.define_property("title", hidden=True, changed=self.__property_changed)
        self.define_property("caption", hidden=True, changed=self.__property_changed)
        self.define_property("description", hidden=True, changed=self.__property_changed)
        self.define_property("session_id", hidden=True, changed=self.__property_changed)
        self.define_property("calibration_style_id", "calibrated", hidden=True, changed=self.__property_changed)
        self.define_property("intensity_calibration_style_id", "calibrated", hidden=True, changed=self.__property_changed)
        self.define_property("display_properties", dict(), hidden=True, copy_on_read=True, changed=self.__display_properties_changed)
        self.define_relationship("graphics", Graphics.factory, insert=self.__insert_graphic, remove=self.__remove_graphic, hidden=True)
        self.define_relationship("display_layers", typing.cast(Persistence._PersistentObjectFactoryFn, display_layer_factory), insert=self.__insert_display_layer, remove=self.__remove_display_layer, hidden=True)
        self.define_relationship("display_data_channels", display_data_channel_factory, insert=self.__insert_display_data_channel, remove=self.__remove_display_data_channel, hidden=True)

        self.__data_items = list[typing.Optional[DataItem.DataItem]]()

        self.__display_layer_changed_event_listeners: typing.List[Event.EventListener] = list()

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

        # configure the title logic

        # the specified title is the title property that is set on the display item. it may override other derived titles.
        self.__specified_title_stream = Stream.ValueStream[str]()

        def combine_only_one(*vs: typing.Optional[str]) -> str:
            return (vs[0] or str()) if len(vs) == 1 else str()

        # the data item title is the title of the data item that this display item is displaying, but only if there is
        # exactly one data item.
        self.__single_data_item_title_stream = Stream.CombineLatestStream(list[Stream.ValueStream[str]](), combine_only_one)
        self.__single_data_item_placeholder_title_stream = Stream.CombineLatestStream(list[Stream.ValueStream[str]](), combine_only_one)

        def combine_display_title(specified_title: typing.Optional[str], data_item_title: typing.Optional[str]) -> str:
            if specified_title:
                return specified_title
            if data_item_title:
                return data_item_title
            return _("Multiple Data Items")

        self.displayed_title_stream = Stream.CombineLatestStream([self.__specified_title_stream, self.__single_data_item_title_stream], combine_display_title)

        def displayed_titled_changed(display_item: DisplayItem, displayed_title: typing.Optional[str]) -> None:
            if not display_item._is_reading:
                self.notify_property_changed("displayed_title")

        self.__displayed_title_stream_action = Stream.ValueStreamAction(self.displayed_title_stream, ReferenceCounting.weak_partial(displayed_titled_changed, self))

        self.__graphic_changed_listeners: typing.List[Event.EventListener] = list()
        self.__display_item_change_count = 0
        self.__display_item_change_count_lock = threading.RLock()
        self.__display_ref_count = 0
        self.graphic_selection = GraphicSelection()
        self.graphic_selection_changed_event = Event.Event()
        self.graphics_changed_event = Event.Event()
        self.display_values_changed_event = Event.Event()
        self.item_changed_event = Event.Event()

        self.__display_data_delta_stream = DisplayDataDeltaStream(
            self,
            Stream.PropertyChangedEventStream[str](self, "calibration_style_id"),
            Stream.PropertyChangedEventStream[str](self, "intensity_calibration_style_id"),
        )

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
        self.__single_data_item_title_stream = typing.cast(typing.Any, None)
        self.__single_data_item_placeholder_title_stream = typing.cast(typing.Any, None)
        self.displayed_title_stream = typing.cast(typing.Any, None)
        self.__displayed_title_stream_action = typing.cast(typing.Any, None)
        self.__display_data_delta_stream = typing.cast(typing.Any, None)
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
        display_item_copy._set_persistent_property_value("intensity_calibration_style_id", self._get_persistent_property_value("intensity_calibration_style_id"))
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
    def display_data_delta_stream(self) -> Stream.ValueStream[DisplayDataDelta]:
        return self.__display_data_delta_stream

    @property
    def calibration_style_id(self) -> str:
        return typing.cast(str, self._get_persistent_property_value("calibration_style_id"))

    @calibration_style_id.setter
    def calibration_style_id(self, value: str) -> None:
        self._set_persistent_property_value("calibration_style_id", value)

    @property
    def intensity_calibration_style_id(self) -> str:
        return typing.cast(str, self._get_persistent_property_value("intensity_calibration_style_id"))

    @intensity_calibration_style_id.setter
    def intensity_calibration_style_id(self, value: str) -> None:
        self._set_persistent_property_value("intensity_calibration_style_id", value)

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
        # this is a hack right now to not notify content changes when only the displayed title changes.
        # in addition to be more efficient, this avoids a close bug appearing in various tests.
        if key not in ("displayed_title",):
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
                            display_layer = DisplayLayer()
                            display_layer.stroke_color = self.get_unique_display_layer_color()
                            display_layer.fill_color = None if len(self.display_data_channels) > 1 else display_layer.stroke_color
                            self.__add_display_layer_auto(display_layer, display_data_channel, data_row)
        else:
            while len(self.display_layers) > 1:
                # use the version of remove that does not cascade
                self.remove_item("display_layers", typing.cast(Persistence.PersistentObject, self.display_layers[-1]))

    def __property_changed(self, name: str, value: typing.Any) -> None:
        self.notify_property_changed(name)
        if name == "title":
            self.__specified_title_stream.value = value
            self.notify_property_changed("displayed_title")
        if name == "calibration_style_id":
            self.display_property_changed_event.fire("calibration_style_id")
        if name == "intensity_calibration_style_id":
            self.display_property_changed_event.fire("intensity_calibration_style_id")

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
        display_item = DisplayItem()
        display_item.display_type = self.display_type
        # metadata
        display_item._set_persistent_property_value("title", self._get_persistent_property_value("title"))
        display_item._set_persistent_property_value("caption", self._get_persistent_property_value("caption"))
        display_item._set_persistent_property_value("description", self._get_persistent_property_value("description"))
        display_item._set_persistent_property_value("session_id", self._get_persistent_property_value("session_id"))
        display_item._set_persistent_property_value("calibration_style_id", self._get_persistent_property_value("calibration_style_id"))
        display_item._set_persistent_property_value("intensity_calibration_style_id", self._get_persistent_property_value("intensity_calibration_style_id"))
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

    def set_storage_cache(self, storage_cache: typing.Optional[Cache.CacheLike]) -> None:
        if storage_cache:
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
            timestamp = DateTime.utcnow()
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
            # TODO: neither graphics_changed_event.fire is probably not necessary since these will change the display calibration info instead.
            if property_name in ("displayed_dimensional_scales", "displayed_dimensional_calibrations", "displayed_intensity_calibration"):
                self.graphics_changed_event.fire(self.graphic_selection)
            if property_name in ("calibration_style_id", "intensity_calibration_style_id"):
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
        self.__display_layer_changed_event_listeners.insert(before_index, display_layer.property_changed_event.listen(self.__display_layer_changed))
        self.notify_insert_item("display_layers", display_layer, before_index)
        self.auto_display_legend()

    def __remove_display_layer(self, name: str, index: int, display_layer: DisplayLayer) -> None:
        self.__display_layer_changed_event_listeners[index].close()
        del self.__display_layer_changed_event_listeners[index]
        self.notify_remove_item("display_layers", display_layer, index)
        self.auto_display_legend()

    def __display_layer_changed(self, name: str) -> None:
        self.display_changed_event.fire()

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
        return self.display_layers[index].get_display_layer_properties()

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

    def append_display_data_channel_for_data_item(self, data_item: DataItem.DataItem, display_layer_properties: typing.Optional[Persistence.PersistentDictType] = None) -> None:
        if not data_item in self.data_items:
            try:
                if display_layer_properties is None:
                    display_layer_properties = dict()
                    unique_color_str = self.get_unique_display_layer_color()
                    display_layer_properties["fill_color"] = unique_color_str
                    display_layer_properties["stroke_color"] = unique_color_str
                display_data_channel = DisplayDataChannel(data_item)
                self.append_display_data_channel(display_data_channel, display_layer=DisplayLayer(display_layer_properties))
            except Exception as e:
                import traceback; traceback.print_exc()

    def save_properties(self) -> DisplayItemSaveProperties:
        return DisplayItemSaveProperties(self.display_properties, self.display_layers_list, self.calibration_style_id, self.intensity_calibration_style_id)

    def restore_properties(self, properties: DisplayItemSaveProperties) -> None:
        self.display_properties = properties.display_properties
        self.display_layers_list = properties.display_layers_list
        self.calibration_style_id = properties.calibration_style_id
        self.intensity_calibration_style_id = properties.intensity_calibration_style_id

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
            self.item_changed_event.fire()
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
        self.notify_property_changed("displayed_title")

    def __display_channel_property_changed(self, display_data_channel: DisplayDataChannel, name: str) -> None:
        data_item = display_data_channel.data_item
        if name == "data_item":
            index = self.display_data_channels.index(display_data_channel)
            self.__data_items[index] = data_item
            self.__single_data_item_title_stream.replace_stream(index, data_item.title_stream if data_item else Stream.ValueStream[str]())
            self.__single_data_item_placeholder_title_stream.replace_stream(index, data_item.placeholder_title_stream if data_item else Stream.ValueStream[str]())
        # during shutdown, the project persistent context will get cleared before the display item is closed. this
        # triggers the data item to become unregistered which triggers the display data channel to fire a data item
        # changed. this is a check for that condition, which hopefully doesn't occur in other situations. this is
        # difficult to test since threading is involved. to test manually, ensure that thumbnails are not recomputed
        # during shutdown by using print statements. consequently, ensure that thumbnails are not recomputed during
        # startup.
        if name != "data_item" or data_item:  # shutting down?
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

    def source_display_items_changed(self, source_display_items: typing.Sequence[DisplayItem], is_loading: bool) -> None:
        # the line below is a hack to resend the display data delta. this is required because of an architectural
        # problem: the display layer may not initially have a correct display_data_channel until the whole project is
        # read. the display_data_channel will only return the correct value once the data items are read; and that
        # may not happen until after the display item is constructed. so we need to resend the display data delta
        # once the data items are read. do that here as a convenient place to do it. the display layer needs its
        # display_data_channel to be correct in order to send the correct display index. there is probably a better
        # way to do this in the future, perhaps directly pointing to the display data channel rather than requiring
        # the index. future work.
        self.__display_data_delta_stream.reset()

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
        if data_item := self.data_item:
            session_metadata_str = " ".join([str(v) for v in data_item.session_metadata.values()])
        else:
            session_metadata_str = ""
        return " ".join([self.displayed_title, self.caption, self.description, self.size_and_data_format_as_string, self.date_for_sorting_local_as_string, session_metadata_str])

    @property
    def displayed_title(self) -> str:
        return self.displayed_title_stream.value or DataItem.UNTITLED_STR

    @property
    def placeholder_title(self) -> str:
        return self.__single_data_item_placeholder_title_stream.value or DataItem.UNTITLED_STR

    @property
    def title(self) -> str:
        if self._get_persistent_property_value("title") is not None:
            return typing.cast(str, self._get_persistent_property_value("title"))
        if title_str := self.__single_data_item_title_stream.value:
            return title_str
        return str()

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

    @property
    def tool_tip_str(self) -> str:
        lines = [self.displayed_title, self.size_and_data_format_as_string, self.date_for_sorting_local_as_string, self.status_str, self.project_str]
        lines = [line for line in lines if line]
        return "\n".join(lines)

    def __insert_display_data_channel(self, name: str, before_index: int, display_data_channel: DisplayDataChannel) -> None:
        display_data_channel.increment_display_ref_count(self._display_ref_count)
        self.__display_data_channel_property_changed_event_listeners.insert(before_index, display_data_channel.property_changed_event.listen(functools.partial(self.__display_channel_property_changed, display_data_channel)))
        self.__display_data_channel_data_item_will_change_event_listeners.insert(before_index, display_data_channel.data_item_will_change_event.listen(self.__data_item_will_change))
        self.__display_data_channel_data_item_did_change_event_listeners.insert(before_index, display_data_channel.data_item_did_change_event.listen(self.__data_item_did_change))
        self.__display_data_channel_data_item_changed_event_listeners.insert(before_index, display_data_channel.data_item_changed_event.listen(self.__item_changed))
        self.__display_data_channel_data_item_description_changed_event_listeners.insert(before_index, display_data_channel.data_item_description_changed_event.listen(self._description_changed))
        self.__display_data_channel_data_item_proxy_changed_event_listeners.insert(before_index, display_data_channel.data_item_proxy_changed_event.listen(self.__update_displays))
        self.notify_insert_item("display_data_channels", display_data_channel, before_index)
        data_item = display_data_channel.data_item
        self.__data_items.insert(before_index, data_item)
        self.__single_data_item_title_stream.insert_stream(before_index, data_item.title_stream if data_item else Stream.ValueStream[str]())
        self.__single_data_item_placeholder_title_stream.insert_stream(before_index, data_item.placeholder_title_stream if data_item else Stream.ValueStream[str]())

    def __remove_display_data_channel(self, name: str, index: int, display_data_channel: DisplayDataChannel) -> None:
        display_data_channel.decrement_display_ref_count(self._display_ref_count)
        self.__disconnect_display_data_channel(display_data_channel, index)
        self.__data_items.pop(index)
        self.__single_data_item_title_stream.remove_stream(index)
        self.__single_data_item_placeholder_title_stream.remove_stream(index)

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

    def get_unique_display_layer_color(self, preferred_color: typing.Optional[Color.Color] = None) -> str:
        existing_colors: typing.List[Color.Color] = list()
        existing_colors.extend([Color.Color(display_layer.fill_color).to_color_without_alpha() for display_layer in self.display_layers])
        existing_colors.extend([Color.Color(display_layer.stroke_color).to_color_without_alpha() for display_layer in self.display_layers])
        possible_colors: typing.List[Color.Color] = list()
        if preferred_color:
            possible_colors.append(preferred_color)
        possible_colors += [Color.Color(color) for color in DisplayItem.DEFAULT_COLORS]
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
        display_layer.display_data_channel = display_data_channel
        if data_row is not None:
            display_layer.data_row = data_row
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
        return self.__display_data_delta_stream.calibration_style

    @property
    def intensity_calibration_style(self) -> CalibrationStyle:
        return self.__display_data_delta_stream.intensity_calibration_style

    @property
    def display_data_shape(self) -> typing.Optional[DataAndMetadata.ShapeType]:
        return self.__display_data_delta_stream.display_data_shape

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
        return self.__display_data_delta_stream.scales

    @property
    def datum_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        """The calibrations for only datum dimensions."""
        return self.__display_data_delta_stream.datum_calibrations

    def get_displayed_dimensional_calibrations_with_calibration_style(self, calibration_style: CalibrationStyle) -> typing.Sequence[Calibration.Calibration]:
        dimensional_shape = self.__display_data_delta_stream.dimensional_shape
        dimensional_calibrations = self.__display_data_delta_stream.dimensional_calibrations
        if dimensional_calibrations and dimensional_shape:
            display_data_channel = self.display_data_channel
            data_item = display_data_channel.data_item if display_data_channel else None
            metadata = data_item.metadata if data_item else None
            return calibration_style.get_dimensional_calibrations(dimensional_shape, dimensional_calibrations, metadata)
        return [Calibration.Calibration() for c in dimensional_calibrations] if dimensional_calibrations else [Calibration.Calibration()]

    @property
    def displayed_dimensional_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        """The calibrations for all data dimensions in the displayed calibration style."""
        return self.__display_data_delta_stream.displayed_dimensional_calibrations

    @property
    def displayed_datum_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        """The calibrations for only datum dimensions, in the displayed calibration style."""
        return self.__display_data_delta_stream.displayed_datum_calibrations

    def get_displayed_intensity_calibration_with_calibration_style(self, calibration_style: CalibrationStyle) -> Calibration.Calibration:
        intensity_calibration = self.__display_data_delta_stream.intensity_calibration
        if intensity_calibration:
            return calibration_style.get_intensity_calibration(intensity_calibration)
        return Calibration.Calibration()

    @property
    def displayed_intensity_calibration(self) -> Calibration.Calibration:
        return self.__display_data_delta_stream.displayed_intensity_calibration

    def __get_calibration_style_for_id(self, calibration_style_id: str) -> typing.Optional[CalibrationStyle]:
        return self.__display_data_delta_stream.get_calibration_style_for_id(calibration_style_id)

    def __get_intensity_calibration_style_for_id(self, calibration_style_id: str) -> typing.Optional[CalibrationStyle]:
        return self.__display_data_delta_stream.get_intensity_calibration_style_for_id(calibration_style_id)

    @property
    def calibration_styles(self) -> typing.Sequence[CalibrationStyle]:
        return self.__display_data_delta_stream.calibration_styles

    @property
    def intensity_calibration_styles(self) -> typing.Sequence[CalibrationStyle]:
        return self.__display_data_delta_stream.intensity_calibration_styles

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

        if not all(map(operator.attrgetter("is_valid"), dimensional_calibrations)):
            dimensional_calibrations = [Calibration.Calibration() for _ in dimensional_calibrations]

        if not intensity_calibration.is_valid:
            intensity_calibration = Calibration.Calibration()

        if display_data_channel is None or pos is None:
            if self.__display_data_delta_stream.is_composite_data and (pos is not None and len(pos) == 1):
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
                with Process.audit("get_value_and_position_text"):
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
    def __init__(self,
                 display_data_shape: typing.Optional[DataAndMetadata.ShapeType],
                 displayed_dimensional_scales: typing.Optional[typing.Tuple[float, ...]],
                 displayed_dimensional_calibrations: typing.Sequence[Calibration.Calibration],
                 displayed_intensity_calibration: Calibration.Calibration,
                 calibration_style: CalibrationStyle,
                 intensity_calibration_style: CalibrationStyle,
                 datum_calibrations: list[Calibration.Calibration]
                 ) -> None:
        assert all(calibration.is_valid for calibration in displayed_dimensional_calibrations)
        self.display_data_shape = display_data_shape
        self.displayed_dimensional_scales = displayed_dimensional_scales
        self.displayed_dimensional_calibrations = displayed_dimensional_calibrations
        self.displayed_intensity_calibration = displayed_intensity_calibration
        self.calibration_style = calibration_style
        self.intensity_calibration_style = intensity_calibration_style
        self.datum_calibrations = datum_calibrations

    @classmethod
    def from_display_item(cls, display_item: DisplayItem) -> DisplayCalibrationInfo:
        return DisplayCalibrationInfo(
            display_item.display_data_shape,
            display_item.displayed_dimensional_scales,
            copy.deepcopy(display_item.displayed_dimensional_calibrations),
            copy.deepcopy(display_item.displayed_intensity_calibration),
            display_item.calibration_style,
            display_item.intensity_calibration_style,
            list(display_item.datum_calibrations))

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
        if  type(self.intensity_calibration_style) != type(display_calibration_info.intensity_calibration_style):
            return True
        return False


def sort_by_date_key(display_item: DisplayItem) -> typing.Tuple[typing.Optional[str], datetime.datetime, str]:
    """A sort key for display items. The sort by uuid makes it determinate."""
    return display_item.title + str(display_item.uuid) if display_item.is_live else str(), display_item.date_for_sorting, str(display_item.uuid)
