"""
    Contains classes related to display of data items.
"""

# standard libraries
import copy
import functools
import gettext
import math
import numbers
import operator
import threading
import typing
import uuid

import numpy

from nion.data import Calibration
from nion.data import Core
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import Cache
from nion.swift.model import ColorMaps
from nion.swift.model import Graphics
from nion.utils import Event
from nion.utils import Model
from nion.utils import Observable
from nion.utils import Persistence
from nion.utils import Promise

_ = gettext.gettext


class GraphicSelection:
    def __init__(self, indexes=None):
        super(GraphicSelection, self).__init__()
        self.__indexes = copy.copy(indexes) if indexes else set()
        self.changed_event = Event.Event()

    def __copy__(self):
        return type(self)(self.__indexes)

    def __eq__(self, other):
        return other is not None and self.indexes == other.indexes

    def __ne__(self, other):
        return other is None or self.indexes != other.indexes

    # manage selection
    @property
    def current_index(self):
        if len(self.__indexes) == 1:
            for index in self.__indexes:
                return index
        return None

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
        if old_index != self.__indexes:
            self.changed_event.fire()

    def add(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes.add(index)
        if old_index != self.__indexes:
            self.changed_event.fire()

    def remove(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes.remove(index)
        if old_index != self.__indexes:
            self.changed_event.fire()

    def add_range(self, range):
        for index in range:
            self.add(index)

    def set(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes = set()
        self.__indexes.add(index)
        if old_index != self.__indexes:
            self.changed_event.fire()

    def toggle(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        if index in self.__indexes:
            self.__indexes.remove(index)
        else:
            self.__indexes.add(index)
        if old_index != self.__indexes:
            self.changed_event.fire()

    def insert_index(self, new_index):
        new_indexes = set()
        for index in self.__indexes:
            if index < new_index:
                new_indexes.add(index)
            else:
                new_indexes.add(index + 1)
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


class Display(Observable.Observable, Persistence.PersistentObject):
    # Displays are associated with exactly one data item.

    def __init__(self):
        super(Display, self).__init__()
        self.__cache = Cache.ShadowCache()
        self.__color_map_data = None
        self.define_property("display_type", changed=self.__display_type_changed)
        self.define_property("complex_display_type", changed=self.__complex_display_type_changed)
        self.define_property("display_calibrated_values", True, changed=self.__property_changed)
        self.define_property("dimensional_calibration_style", None, changed=self.__property_changed)
        self.define_property("display_limits", validate=self.__validate_display_limits, changed=self.__display_limits_changed)
        self.define_property("y_min", changed=self.__property_changed)
        self.define_property("y_max", changed=self.__property_changed)
        self.define_property("y_style", "linear", changed=self.__property_changed)
        self.define_property("left_channel", changed=self.__property_changed)
        self.define_property("right_channel", changed=self.__property_changed)
        self.define_property("legend_labels", changed=self.__property_changed)
        self.define_property("sequence_index", 0, validate=self.__validate_sequence_index, changed=self.__sequence_index_changed)
        self.define_property("collection_index", (0, 0, 0), validate=self.__validate_collection_index, changed=self.__collection_index_changed)
        self.define_property("slice_center", 0, validate=self.__validate_slice_center, changed=self.__slice_interval_changed)
        self.define_property("slice_width", 1, validate=self.__validate_slice_width, changed=self.__slice_interval_changed)
        self.define_property("color_map_id", changed=self.__color_map_id_changed)
        self.define_relationship("graphics", Graphics.factory, insert=self.__insert_graphic, remove=self.__remove_graphic)
        self.__data_range_model = Model.PropertyModel()
        self.__display_range_model = Model.PropertyModel()
        self.__graphics_map = dict()  # type: typing.MutableMapping[uuid.UUID, Graphics.Graphic]
        self.__graphic_changed_listeners = list()
        self.__data_and_metadata = None  # the most recent data to be displayed. should have immediate data available.
        self.__display_data_and_metadata_model = Model.AsyncPropertyModel(self.__calculate_display_data_and_metadata)
        self.__display_data_and_metadata = None
        self.__display_data_and_metadata_lock = threading.RLock()
        self.__preview = None
        self.__preview_lock = threading.RLock()
        self.thumbnail_changed_event = Event.Event()
        self.graphic_selection = GraphicSelection()
        def graphic_selection_changed():
            # relay the message
            self.display_graphic_selection_changed_event.fire(self.graphic_selection)
        self.__graphic_selection_changed_event_listener = self.graphic_selection.changed_event.listen(graphic_selection_changed)
        self.about_to_be_removed_event = Event.Event()
        self.display_changed_event = Event.Event()
        self.display_type_changed_event = Event.Event()
        self.display_graphic_selection_changed_event = Event.Event()
        self.display_processor_needs_recompute_event = Event.Event()
        self.display_processor_data_updated_event = Event.Event()
        self.display_graphic_will_remove_event = Event.Event()
        self._about_to_be_removed = False
        self._closed = False

    def close(self):
        self.__graphic_selection_changed_event_listener.close()
        self.__graphic_selection_changed_event_listener = None
        for graphic in copy.copy(self.graphics):
            self.__disconnect_graphic(graphic, 0)
            graphic.close()
        self.graphic_selection = None
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True

    def read_from_dict(self, properties):
        super().read_from_dict(properties)
        if self.dimensional_calibration_style is None:
            self._get_persistent_property("dimensional_calibration_style").value = "calibrated" if self.display_calibrated_values else "relative-top-left"

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        for graphic in self.graphics:
            graphic.about_to_be_removed()
        self.about_to_be_removed_event.fire()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

    def clone(self) -> "Display":
        display = Display()
        display.uuid = self.uuid
        for graphic in self.graphics:
            display.add_graphic(graphic.clone())
        return display

    @property
    def _display_cache(self):
        return self.__cache

    @property
    def data_and_metadata_for_display_panel(self):
        return self.__data_and_metadata

    def auto_display_limits(self):
        # auto set the display limits if not yet set and data is complex
        self.display_limits = None

    def view_to_intervals(self, data_and_metadata: DataAndMetadata.DataAndMetadata, intervals: typing.List[typing.Tuple[float, float]]) -> None:
        left = None
        right = None
        for interval in intervals:
            left = min(left, interval[0]) if left is not None else interval[0]
            right = max(right, interval[1]) if right is not None else interval[1]
        left = left if left is not None else 0.0
        right = right if right is not None else 1.0
        extra = (right - left) * 0.5
        self.left_channel = int(max(0.0, left - extra) * data_and_metadata.data_shape[-1])
        self.right_channel = int(min(1.0, right + extra) * data_and_metadata.data_shape[-1])
        data_min = numpy.amin(data_and_metadata.data[..., self.left_channel:self.right_channel])
        data_max = numpy.amax(data_and_metadata.data[..., self.left_channel:self.right_channel])
        if data_min > 0 and data_max > 0:
            self.y_min = 0.0
            self.y_max = data_max * 1.2
        elif data_min < 0 and data_max < 0:
            self.y_min = data_min * 1.2
            self.y_max = 0.0
        else:
            self.y_min = data_min * 1.2
            self.y_max = data_max * 1.2

    def view_to_selected_graphics(self, data_and_metadata: DataAndMetadata.DataAndMetadata) -> None:
        all_graphics = self.graphics
        graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if self.graphic_selection.contains(graphic_index)]
        intervals = list()
        for graphic in graphics:
            if isinstance(graphic, Graphics.IntervalGraphic):
                intervals.append(graphic.interval)
        self.view_to_intervals(data_and_metadata, intervals)

    @property
    def preview_2d(self):
        with self.__preview_lock:
            if self.__preview is None:
                data_and_metadata = self.display_data_and_metadata
                if data_and_metadata is not None:
                    # display_range is just display_limits but calculated if display_limits is None
                    self.__validate_data_stats()
                    data_range = self.__cache.get_cached_value(self, "data_range")
                    data_sample = self.__cache.get_cached_value(self, "data_sample")
                    display_range = calculate_display_range(self.display_limits, data_range, data_sample, self.__data_and_metadata, self.complex_display_type)
                    preview_xdata = Core.function_display_rgba(data_and_metadata, display_range, self.__color_map_data)
                    self.__preview = preview_xdata.data
            return self.__preview

    def __get_display_dimensional_shape(self) -> typing.Tuple[int, ...]:
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
    def display_data_and_metadata(self) -> DataAndMetadata.DataAndMetadata:
        """Return version of the source data guaranteed to be 1-dimensional scalar or 2-dimensional and scalar or RGBA.

        Accessing display data may involve computation, so this method should not be used on UI thread.
        """
        with self.__display_data_and_metadata_lock:
            data_and_metadata = self.__data_and_metadata
            if self.__display_data_and_metadata is None and data_and_metadata is not None:
                data_and_metadata = Core.function_display_data(data_and_metadata, self.sequence_index, self.collection_index, self.slice_center,
                                                               self.slice_width, self.complex_display_type)
                self.__display_data_and_metadata = data_and_metadata
            return self.__display_data_and_metadata

    @property
    def display_data_and_metadata_model(self):
        return self.__display_data_and_metadata_model

    def __calculate_display_data_and_metadata(self):
        data_and_metadata = self.__data_and_metadata
        if data_and_metadata is not None:
            return Core.function_display_data(data_and_metadata, self.sequence_index, self.collection_index, self.slice_center, self.slice_width, self.complex_display_type)
        return None

    @property
    def preview_2d_shape(self):
        return self.__get_display_dimensional_shape()

    @property
    def selected_graphics(self):
        return [self.graphics[i] for i in self.graphic_selection.indexes]

    def __validate_display_limits(self, value):
        if value is not None:
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

    def __display_limits_changed(self, name, value):
        self.__property_changed(name, value)
        self.__display_range_model.value = value

    def __validate_sequence_index(self, value: int) -> int:
        if self.__data_and_metadata and self.__data_and_metadata.dimensional_shape is not None:
            return max(min(int(value), self.__data_and_metadata.max_sequence_index), 0)
        return value if self._is_reading else 0

    def __validate_collection_index(self, value: typing.Tuple[int, int, int]) -> typing.Tuple[int, int, int]:
        if self.__data_and_metadata and self.__data_and_metadata.dimensional_shape is not None:
            dimensional_shape = self.__data_and_metadata.dimensional_shape
            collection_base_index = 1 if self.__data_and_metadata.is_sequence else 0
            collection_dimension_count = self.__data_and_metadata.collection_dimension_count
            i0 = max(min(int(value[0]), dimensional_shape[collection_base_index + 0]), 0) if collection_dimension_count > 0 else 0
            i1 = max(min(int(value[1]), dimensional_shape[collection_base_index + 1]), 0) if collection_dimension_count > 1 else 0
            i2 = max(min(int(value[2]), dimensional_shape[collection_base_index + 2]), 0) if collection_dimension_count > 2 else 0
            return i0, i1, i2
        return value if self._is_reading else (0, 0, 0)

    def __validate_slice_center_for_width(self, value, slice_width):
        if self.__data_and_metadata and self.__data_and_metadata.dimensional_shape is not None:
            depth = self.__data_and_metadata.dimensional_shape[-1]
            mn = max(int(slice_width * 0.5), 0)
            mx = min(int(depth - slice_width * 0.5), depth - 1)
            return min(max(int(value), mn), mx)
        return value if self._is_reading else 0

    def __validate_slice_center(self, value):
        return self.__validate_slice_center_for_width(value, self.slice_width)

    def __validate_slice_width(self, value):
        if self.__data_and_metadata and self.__data_and_metadata.dimensional_shape is not None:
            depth = self.__data_and_metadata.dimensional_shape[-1]  # signal_index
            slice_center = self.slice_center
            mn = 1
            mx = max(min(slice_center, depth - slice_center) * 2, 1)
            return min(max(value, mn), mx)
        return value if self._is_reading else 1

    def validate(self):
        slice_center = self.__validate_slice_center_for_width(self.slice_center, 1)
        if slice_center != self.slice_center:
            old_slice_width = self.slice_width
            self.slice_width = 1
            self.slice_center = self.slice_center
            self.slice_width = old_slice_width

    def __sequence_index_changed(self, name, value):
        self.__property_changed(name, value)
        if not self._is_reading:
            self.__cache.remove_cached_value(self, "data_range")
            self.__cache.remove_cached_value(self, "data_sample")
        if self.__data_and_metadata and self.__data_and_metadata.is_data_valid:
            self.__validate_data_stats()
        self.notify_property_changed("sequence_index")

    def __collection_index_changed(self, name, value):
        self.__property_changed(name, value)
        if not self._is_reading:
            self.__cache.remove_cached_value(self, "data_range")
            self.__cache.remove_cached_value(self, "data_sample")
        if self.__data_and_metadata and self.__data_and_metadata.is_data_valid:
            self.__validate_data_stats()
        self.notify_property_changed("collection_index")

    @property
    def actual_display_type(self):
        display_type = self.display_type
        data_and_metadata = self.__data_and_metadata
        valid_data = functools.reduce(operator.mul, self.preview_2d_shape) > 0 if self.preview_2d_shape is not None else False
        if valid_data and data_and_metadata and not display_type in ("line_plot", "image"):
            if data_and_metadata.collection_dimension_count == 2 and data_and_metadata.datum_dimension_count == 1:
                display_type = "image"
            elif data_and_metadata.datum_dimension_count == 1:
                display_type = "line_plot"
            elif data_and_metadata.datum_dimension_count == 2:
                display_type = "image"
        return display_type

    def get_line_plot_display_parameters(self):
        data_and_metadata = self.data_and_metadata_for_display_panel
        if data_and_metadata:

            class LinePlotDisplayParameters:
                def __init__(self, display):
                    displayed_dimensional_calibrations = display.displayed_dimensional_calibrations
                    metadata = data_and_metadata.metadata
                    dimensional_shape = data_and_metadata.dimensional_shape
                    displayed_dimensional_calibration = displayed_dimensional_calibrations[-1] if len(displayed_dimensional_calibrations) > 0 else Calibration.Calibration()
                    displayed_intensity_calibration = copy.deepcopy(data_and_metadata.intensity_calibration)
                    self.display_data_fn = lambda: display.display_data_and_metadata.data if display.display_data_and_metadata else None
                    self.dimensional_shape = dimensional_shape
                    self.displayed_intensity_calibration = displayed_intensity_calibration
                    self.displayed_dimensional_calibration = displayed_dimensional_calibration
                    self.metadata = metadata
                    self.y_range = display.y_min, display.y_max
                    self.y_style = display.y_style
                    self.channel_range = display.left_channel, display.right_channel
                    self.legend_labels = display.legend_labels

            return LinePlotDisplayParameters(self)
        return None

    def get_image_display_parameters(self):
        data_and_metadata = self.data_and_metadata_for_display_panel
        if data_and_metadata:

            class ImageDisplayParameters:
                def __init__(self, display):
                    displayed_dimensional_calibrations = display.displayed_dimensional_calibrations
                    if len(displayed_dimensional_calibrations) == 0:
                        dimensional_calibration = Calibration.Calibration()
                    elif len(displayed_dimensional_calibrations) == 1:
                        dimensional_calibration = displayed_dimensional_calibrations[0]
                    else:
                        display_data_and_metadata = display.display_data_and_metadata
                        if display_data_and_metadata:
                            dimensional_calibration = display_data_and_metadata.dimensional_calibrations[-1]
                        else:
                            dimensional_calibration = Calibration.Calibration()
                    self.display_rgba_fn = lambda: display.preview_2d
                    self.display_rgba_shape = display.preview_2d_shape
                    self.dimensional_calibration = dimensional_calibration
                    self.metadata = data_and_metadata.metadata

            return ImageDisplayParameters(self)
        return None

    @property
    def slice_interval(self):
        if self.__data_and_metadata and self.__data_and_metadata.dimensional_shape is not None:
            depth = self.__data_and_metadata.dimensional_shape[-1]  # signal_index
            if depth > 0:
                slice_interval_start = int(self.slice_center + 1 - self.slice_width * 0.5)
                slice_interval_end = slice_interval_start + self.slice_width
                return (float(slice_interval_start) / depth, float(slice_interval_end) / depth)
            return 0, 0
        return None

    @slice_interval.setter
    def slice_interval(self, slice_interval):
        if self.__data_and_metadata.dimensional_shape is not None:
            depth = self.__data_and_metadata.dimensional_shape[-1]  # signal_index
            if depth > 0:
                slice_interval_center = int(((slice_interval[0] + slice_interval[1]) * 0.5) * depth)
                slice_interval_width = int((slice_interval[1] - slice_interval[0]) * depth)
                self.slice_center = slice_interval_center
                self.slice_width = slice_interval_width

    def __slice_interval_changed(self, name, value):
        # notify for dependent slice_interval property
        self.__property_changed(name, value)
        if not self._is_reading:
            self.__cache.remove_cached_value(self, "data_range")
            self.__cache.remove_cached_value(self, "data_sample")
        if self.__data_and_metadata and self.__data_and_metadata.is_data_valid:
            self.__validate_data_stats()
        self.notify_property_changed("slice_interval")

    def __display_type_changed(self, property_name, value):
        self.__property_changed(property_name, value)
        self.display_type_changed_event.fire()

    def __complex_display_type_changed(self, property_name, value):
        self.__property_changed(property_name, value)
        if not self._is_reading:
            self.__cache.remove_cached_value(self, "data_range")
            self.__cache.remove_cached_value(self, "data_sample")

    def __color_map_id_changed(self, property_name, value):
        self.__property_changed(property_name, value)
        if value:
            lookup_table_options = ColorMaps.color_maps
            self.__color_map_data = lookup_table_options.get(value)
        else:
            self.__color_map_data = None
        self.__property_changed("color_map_data", self.__color_map_data)

    @property
    def color_map_data(self) -> numpy.ndarray:
        """
        Should return an numpy array with shape (256, 3) of data type uint8
        """
        if self.preview_2d_shape is None:  # is there display data?
            return None
        else:
            return self.__color_map_data if self.__color_map_data is not None else ColorMaps.color_maps.get("grayscale")

    def __property_changed(self, property_name, value):
        # when one of the defined properties changes, this gets called
        self.__clear_cached_data()
        self.notify_property_changed(property_name)
        self.display_changed_event.fire()
        if property_name in ("slice_center", "slice_width", "sequence_index", "collection_index", "complex_display_type"):
            self.__display_data_and_metadata_model.mark_dirty()
            with self.__display_data_and_metadata_lock:
                self.__display_data_and_metadata = None
        if property_name in ("dimensional_calibration_style", ):
            self.notify_property_changed("displayed_dimensional_calibrations")
            self.notify_property_changed("displayed_intensity_calibration")
            self._get_persistent_property("display_calibrated_values").value = value == "calibrated"
        if not self._is_reading:
            self.thumbnail_changed_event.fire()

    def __validate_data_stats(self):
        # ensure that data_range and data_sample (if required) are valid.
        display_data_and_metadata = self.display_data_and_metadata
        is_data_complex_type = self.__data_and_metadata.is_data_complex_type if self.__data_and_metadata else False
        data_range = self.__cache.get_cached_value(self, "data_range")
        data_sample = self.__cache.get_cached_value(self, "data_sample")
        if display_data_and_metadata is not None and (data_range is None or (is_data_complex_type and data_sample is None)):
            self.__calculate_data_stats_for_data(display_data_and_metadata.data, self.__data_and_metadata.data_shape, self.__data_and_metadata.data_dtype)

    def __calculate_data_stats_for_data(self, display_data, data_shape, data_dtype):
        # calculates data_range and data_sample (if required), stores them in cache, and notifies listeners
        if display_data is not None and display_data.size:
            if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
                data_range = (0, 255)
                data_sample = None
            elif Image.is_shape_and_dtype_complex_type(data_shape, data_dtype):
                data_range = (numpy.amin(display_data), numpy.amax(display_data))
                data_sample = numpy.sort(numpy.random.choice(display_data.reshape(numpy.product(display_data.shape)), 200))
            else:
                data_range = (numpy.amin(display_data), numpy.amax(display_data))
                data_sample = None
        else:
            data_range = None
            data_sample = None
        if data_range is not None:
            if math.isnan(data_range[0]) or math.isnan(data_range[1]) or math.isinf(data_range[0]) or math.isinf(data_range[1]):
                data_range = (0.0, 0.0)
            self.__cache.set_cached_value(self, "data_range", data_range)
        else:
            self.__cache.remove_cached_value(self, "data_range")
        if data_sample is not None:
            self.__cache.set_cached_value(self, "data_sample", data_sample)
        else:
            self.__cache.remove_cached_value(self, "data_sample")
        self.__clear_cached_data()
        self.__data_range_model.value = data_range
        self.__display_range_model.value = calculate_display_range(self.display_limits, data_range, data_sample, self.__data_and_metadata, self.complex_display_type)

    @property
    def data_range_model(self):
        self.__validate_data_stats()
        return self.__data_range_model

    def _set_data_range_for_test(self, data_range):
        self.__cache.set_cached_value(self, "data_range", data_range)

    @property
    def display_range_model(self):
        self.__validate_data_stats()
        data_range = self.__cache.get_cached_value(self, "data_range")
        data_sample = self.__cache.get_cached_value(self, "data_sample")
        self.__display_range_model.value = calculate_display_range(self.display_limits, data_range, data_sample, self.__data_and_metadata, self.complex_display_type)
        return self.__display_range_model

    # message sent from buffered_data_source when data changes.
    # thread safe
    def update_data(self, data_and_metadata):
        old_data_shape = self.__data_and_metadata.data_shape if self.__data_and_metadata else None
        self.__data_and_metadata = data_and_metadata
        new_data_shape = self.__data_and_metadata.data_shape if self.__data_and_metadata else None
        self.__clear_cached_data()
        if old_data_shape != new_data_shape:
            self.validate()
        self.__display_data_and_metadata_model.mark_dirty()
        with self.__display_data_and_metadata_lock:
            self.__display_data_and_metadata = None
        if not self._is_reading:
            self.__cache.remove_cached_value(self, "data_range")
            self.__cache.remove_cached_value(self, "data_sample")
            self.__validate_data_stats()
        self.notify_property_changed("displayed_dimensional_calibrations")
        self.notify_property_changed("displayed_intensity_calibration")
        self.display_changed_event.fire()

    def set_storage_cache(self, storage_cache):
        self.__cache.set_storage_cache(storage_cache, self)
        self.__data_range_model.value = self.__cache.get_cached_value(self, "data_range")

    def __clear_cached_data(self):
        with self.__preview_lock:
            self.__preview = None
        # clear the processor caches
        if not self._is_reading:
            self.thumbnail_changed_event.fire()

    def __insert_graphic(self, name, before_index, graphic):
        graphic_changed_listener = graphic.graphic_changed_event.listen(functools.partial(self.graphic_changed, graphic))
        self.__graphic_changed_listeners.insert(before_index, graphic_changed_listener)
        self.__graphics_map[graphic.uuid] = graphic
        self.graphic_selection.insert_index(before_index)
        self.display_changed_event.fire()
        self.notify_insert_item("graphics", graphic, before_index)

    def __remove_graphic(self, name, index, graphic):
        graphic.about_to_be_removed()
        self.__graphics_map.pop(graphic.uuid)
        self.__disconnect_graphic(graphic, index)
        self.display_graphic_will_remove_event.fire(graphic)
        graphic.close()

    def __disconnect_graphic(self, graphic, index):
        graphic_changed_listener = self.__graphic_changed_listeners[index]
        graphic_changed_listener.close()
        self.__graphic_changed_listeners.remove(graphic_changed_listener)
        self.graphic_selection.remove_index(index)
        self.display_changed_event.fire()
        self.notify_remove_item("graphics", graphic, index)

    def insert_graphic(self, before_index, graphic):
        """ Insert a graphic before the index """
        self.insert_item("graphics", before_index, graphic)

    def add_graphic(self, graphic):
        """ Append a graphic """
        self.append_item("graphics", graphic)

    def remove_graphic(self, graphic):
        """ Remove a graphic """
        self.remove_item("graphics", graphic)

    def extend_graphics(self, graphics):
        """ Extend the graphics array with the list of graphics """
        self.extend_items("graphics", graphics)

    def get_graphic_by_uuid(self, graphic_uuid: uuid.UUID) -> Graphics.Graphic:
        return self.__graphics_map.get(graphic_uuid)

    # this message comes from the graphic. the connection is established when a graphic
    # is added or removed from this object.
    def graphic_changed(self, graphic):
        self.display_changed_event.fire()
        if not self._is_reading:
            self.thumbnail_changed_event.fire()

    @property
    def displayed_dimensional_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        dimensional_calibration_style = self.dimensional_calibration_style
        if (dimensional_calibration_style is None or dimensional_calibration_style == "calibrated") and self.__data_and_metadata:
            return self.__data_and_metadata.dimensional_calibrations
        else:
            dimensional_shape = self.__data_and_metadata.dimensional_shape if self.__data_and_metadata is not None else None
            if dimensional_shape is not None:
                if dimensional_calibration_style == "relative-top-left":
                    return [Calibration.Calibration(scale=1.0/display_dimension) for display_dimension in dimensional_shape]
                elif dimensional_calibration_style == "relative-center":
                    return [Calibration.Calibration(scale=2.0/display_dimension, offset=-1.0) for display_dimension in dimensional_shape]
                elif dimensional_calibration_style == "pixels-top-left":
                    return [Calibration.Calibration() for display_dimension in dimensional_shape]
                else:  # "pixels-center"
                    return [Calibration.Calibration(offset=-display_dimension/2) for display_dimension in dimensional_shape]
            else:
                return list()

    @property
    def displayed_intensity_calibration(self):
        if self.dimensional_calibration_style == "calibrated" and self.__data_and_metadata:
            return self.__data_and_metadata.intensity_calibration
        else:
            return Calibration.Calibration()

    def __get_calibrated_value_text(self, value: float, intensity_calibration) -> str:
        if value is not None:
            return intensity_calibration.convert_to_calibrated_value_str(value)
        elif value is None:
            return _("N/A")
        else:
            return str(value)

    def get_value_and_position_text(self, pos) -> (str, str):
        data_and_metadata = self.__data_and_metadata
        dimensional_calibrations = self.displayed_dimensional_calibrations
        intensity_calibration = self.displayed_intensity_calibration

        if data_and_metadata is None or pos is None:
            return str(), str()

        is_sequence = data_and_metadata.is_sequence
        collection_dimension_count = data_and_metadata.collection_dimension_count
        datum_dimension_count = data_and_metadata.datum_dimension_count
        if is_sequence:
            pos = (self.sequence_index, ) + pos
        if collection_dimension_count == 2 and datum_dimension_count == 1:
            pos = pos + (self.slice_center, )
        else:
            for collection_index in self.collection_index[0:collection_dimension_count]:
                pos = (collection_index, ) + pos

        assert len(pos) == len(data_and_metadata.dimensional_shape)

        position_text = ""
        value_text = ""
        data_shape = data_and_metadata.data_shape
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

    # called from processors
    def processor_needs_recompute(self, processor):
        self.display_processor_needs_recompute_event.fire(processor)

    # called from processors
    def processor_data_updated(self, processor):
        self.display_processor_data_updated_event.fire(processor)


def display_factory(lookup_id):
    return Display()
