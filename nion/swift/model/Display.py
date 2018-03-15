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
import weakref

import numpy

from nion.data import Calibration
from nion.data import Core
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import Cache
from nion.swift.model import ColorMaps
from nion.swift.model import Graphics
from nion.utils import Event
from nion.utils import ListModel
from nion.utils import Observable
from nion.utils import Persistence


_ = gettext.gettext


class CalibrationList:

    def __init__(self, calibrations=None):
        self.list = list() if calibrations is None else copy.deepcopy(calibrations)

    def __len__(self):
        return len(self.list)

    def __getitem__(self, item):
        return self.list[item]

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
    def display_data_and_metadata(self):
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
                        self.__data_sample = numpy.sort(numpy.random.choice(display_data.reshape(numpy.product(display_data.shape)), 200))
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


class ObservableListEventObserver:

    def __init__(self, container, key, event, fn):
        self.__event_listeners = list()

        def item_inserted(key_, value, index):
            if key == key_:
                def handle_event(*args, **kwargs):
                    fn(value, *args, **kwargs)

                self.__event_listeners.insert(index, getattr(value, event).listen(handle_event))

        def item_removed(key_, value, index):
            if key_ == key:
                self.__event_listeners[index].close()
                del self.__event_listeners[index]

        self.__item_inserted_event_listener = container.item_inserted_event.listen(item_inserted)
        self.__item_removed_event_listener = container.item_removed_event.listen(item_removed)

        for index, item in enumerate(getattr(container, key)):
            item_inserted(key, item, index)

    def close(self):
        self.__item_inserted_event_listener.close()
        self.__item_inserted_event_listener = None
        self.__item_removed_event_listener.close()
        self.__item_removed_event_listener = None
        for event_listener in self.__event_listeners:
            event_listener.close()
        self.__event_listeners = None


class Display(Observable.Observable, Persistence.PersistentObject):
    """The display properties for a DataItem.

    Also handles conversion of raw data to formats suitable for display such as raster RGBA.

    Display data is the associated data item data after it has been reduced to basic form (1d, 2d) by slicing and/or
    conversion to scalar.

    RGB data is the display data after it has been converted to RGB for raster display.

    In order to be able to efficiently route data in a thread, and also to make the data consistent with a snapshot
    in time, display data and RGB data is managed via a DisplayValues object.

    In addition to regular observable events, this class also generates the following events:
        - about_to_be_removed_event: fired when about to be removed from parent container.
        - display_changed_event: fired when display changes in a way to affect drawing.
        - display_data_will_change_event: fired when display data changes.
        - display_type_changed_event: fired when the display type changes.
        - display_graphic_selection_changed_event: fired when the graphic selection changes.
    """

    def __init__(self):
        super().__init__()
        self.__container_weak_ref = None
        self.__cache = Cache.ShadowCache()
        self.__color_map_data = None
        # display type to use
        self.define_property("display_type", changed=self.__display_type_changed)
        # conversion to scalar
        self.define_property("complex_display_type", changed=self.__property_changed)
        # calibration display
        self.define_property("display_calibrated_values", True, changed=self.__property_changed)
        self.define_property("dimensional_calibration_style", None, changed=self.__property_changed)
        # data scaling and color (raster)
        self.define_property("display_limits", validate=self.__validate_display_limits, changed=self.__property_changed)
        self.define_property("color_map_id", changed=self.__color_map_id_changed)
        # image zoom and position
        self.define_property("image_zoom", 1.0, changed=self.__property_changed)
        self.define_property("image_position", (0.5, 0.5), changed=self.__property_changed)
        self.define_property("image_canvas_mode", "fit", changed=self.__property_changed)
        # line plot axes and labels
        self.define_property("y_min", changed=self.__property_changed)
        self.define_property("y_max", changed=self.__property_changed)
        self.define_property("y_style", "linear", changed=self.__property_changed)
        self.define_property("left_channel", changed=self.__property_changed)
        self.define_property("right_channel", changed=self.__property_changed)
        self.define_property("legend_labels", changed=self.__property_changed)
        self.define_property("intensity_calibration", None, make=Calibration.Calibration, changed=self.__property_changed)
        self.define_property("dimensional_calibrations", CalibrationList(), hidden=True, make=CalibrationList, changed=self.__property_changed)
        self.define_property("dimensional_scales", None, changed=self.__property_changed)
        # slicing data to 1d or 2d
        self.define_property("sequence_index", 0, validate=self.__validate_sequence_index, changed=self.__property_changed)
        self.define_property("collection_index", (0, 0, 0), validate=self.__validate_collection_index, changed=self.__property_changed)
        self.define_property("slice_center", 0, validate=self.__validate_slice_center, changed=self.__slice_interval_changed)
        self.define_property("slice_width", 1, validate=self.__validate_slice_width, changed=self.__slice_interval_changed)
        # display script
        self.define_property("display_script", changed=self.__property_changed)
        # graphics
        self.define_relationship("graphics", Graphics.factory, insert=self.__insert_graphic, remove=self.__remove_graphic)

        self.__title = None  # not persistent during display panel transition

        self.item_changed_event = Event.Event()  # for indicated this display has mutated somehow

        # # last display values is the last one to be fully displayed.
        # # when the current display values makes it all the way to display, it will fire an event.
        # # the display will listen for that event and update last display values.
        self.__last_display_values = None
        self.__current_display_values = None
        self.__is_master = True

        self.display_values_changed_event = Event.Event()
        self.__calculated_display_values_available_event = Event.Event()

        self.__graphics_map = dict()  # type: typing.MutableMapping[uuid.UUID, Graphics.Graphic]
        self.__graphic_changed_listeners = list()
        self.__data_and_metadata = None  # the most recent data to be displayed. should have immediate data available.
        self.graphic_selection = GraphicSelection()

        def graphic_selection_changed():
            # relay the message
            self.display_graphic_selection_changed_event.fire(self.graphic_selection)

        self.__graphic_selection_changed_event_listener = self.graphic_selection.changed_event.listen(graphic_selection_changed)
        self.about_to_be_removed_event = Event.Event()
        self.display_changed_event = Event.Event()
        self.display_data_will_change_event = Event.Event()
        self.display_type_changed_event = Event.Event()
        self.display_graphic_selection_changed_event = Event.Event()
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
        self.__container_weak_ref = None

    def read_from_dict(self, properties):
        super().read_from_dict(properties)
        dimensional_calibration_style_property = self._get_persistent_property("dimensional_calibration_style")
        if self.dimensional_calibration_style is None:
            calibration_style = self.default_calibrated_calibration_style if self.display_calibrated_values else self.default_uncalibrated_calibration_style
            dimensional_calibration_style_property.value = calibration_style.calibration_style_id
        else:
            valid_calibration_styles = (calibrated_style.calibration_style_id for calibrated_style in self.calibration_styles)
            if not dimensional_calibration_style_property.value in valid_calibration_styles:
                calibration_style = self.default_calibrated_calibration_style if dimensional_calibration_style_property.value.startswith("calibration") else self.default_uncalibrated_calibration_style
                dimensional_calibration_style_property.value = calibration_style.calibration_style_id

    def save_properties(self) -> typing.Tuple:
        return (
            self.left_channel,
            self.right_channel,
            self.y_min,
            self.y_max,
            self.y_style,
            self.image_zoom,
            self.image_position,
            self.image_canvas_mode,
            self.complex_display_type,
            self.display_calibrated_values,
            self.dimensional_calibration_style,
            self.display_limits,
            self.color_map_id,
            self.sequence_index,
            self.collection_index,
            self.slice_center,
            self.slice_interval,
            self.display_type,
            self.display_script
        )

    def restore_properties(self, properties: typing.Tuple) -> None:
        self.left_channel = properties[0]
        self.right_channel = properties[1]
        self.y_min = properties[2]
        self.y_max = properties[3]
        self.y_style = properties[4]
        self.image_zoom = properties[5]
        self.image_position = properties[6]
        self.image_canvas_mode = properties[7]
        self.complex_display_type = properties[8]
        self.display_calibrated_values = properties[9]
        self.dimensional_calibration_style = properties[10]
        self.display_limits = properties[11]
        self.color_map_id = properties[12]
        self.sequence_index = properties[13]
        self.collection_index = properties[14]
        self.slice_center = properties[15]
        self.slice_interval = properties[16]
        self.display_type = properties[17]
        self.display_script = properties[18]

    @property
    def container(self):
        return self.__container_weak_ref()

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

        # child displays model will watch the container for data items and make a new list with each of the displays in each data item.
        self.__child_displays_model = ListModel.FlattenedListModel(container=container, master_items_key="data_items", child_items_key="displays")

        def handle_display_changed(display):
            self.display_changed_event.fire()

        # watch the child display model for insert/removes from displays; and passes on the display_changed_event for each active display
        self.__child_display_observer = ObservableListEventObserver(self.__child_displays_model, "displays", "display_changed_event", handle_display_changed)

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        for graphic in self.graphics:
            graphic.about_to_be_removed()
        self.about_to_be_removed_event.fire()
        self.__child_display_observer.close()
        self.__child_display_observer = None
        self.__child_displays_model.close()
        self.__child_displays_model = None
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
    def child_displays_model(self):
        return self.__child_displays_model

    @property
    def title(self) -> str:
        return self.__title

    @title.setter
    def title(self, value: str) -> None:
        self.__title = value
        self.notify_property_changed("title")

    @property
    def dimensional_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        return copy.deepcopy(self._get_persistent_property_value("dimensional_calibrations", CalibrationList()).list)

    @dimensional_calibrations.setter
    def dimensional_calibrations(self, dimensional_calibrations: typing.Sequence[Calibration.Calibration]) -> None:
        """ Set the dimensional calibrations. """
        self._set_persistent_property_value("dimensional_calibrations", CalibrationList(dimensional_calibrations))

    # when the data item changes, it will call this method so that item_changed can be fired.
    def _item_changed(self):
        self.item_changed_event.fire()

    @property
    def data_and_metadata_for_display_panel(self):
        return self.__data_and_metadata

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
        """Change the view to encompass the selected graphic intervals."""
        all_graphics = self.graphics
        graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if self.graphic_selection.contains(graphic_index)]
        intervals = list()
        for graphic in graphics:
            if isinstance(graphic, Graphics.IntervalGraphic):
                intervals.append(graphic.interval)
        self.view_to_intervals(data_and_metadata, intervals)

    @property
    def preview_2d_shape(self) -> typing.Optional[typing.Tuple[int, ...]]:
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

    def __validate_sequence_index(self, value: int) -> int:
        if not self._is_reading:
            if self.__data_and_metadata and self.__data_and_metadata.dimensional_shape is not None:
                return max(min(int(value), self.__data_and_metadata.max_sequence_index - 1), 0) if self.__data_and_metadata.is_sequence else 0
        return 0

    def __validate_collection_index(self, value: typing.Tuple[int, int, int]) -> typing.Tuple[int, int, int]:
        if not self._is_reading:
            if self.__data_and_metadata and self.__data_and_metadata.dimensional_shape is not None:
                dimensional_shape = self.__data_and_metadata.dimensional_shape
                collection_base_index = 1 if self.__data_and_metadata.is_sequence else 0
                collection_dimension_count = self.__data_and_metadata.collection_dimension_count
                i0 = max(min(int(value[0]), dimensional_shape[collection_base_index + 0] - 1), 0) if collection_dimension_count > 0 else 0
                i1 = max(min(int(value[1]), dimensional_shape[collection_base_index + 1] - 1), 0) if collection_dimension_count > 1 else 0
                i2 = max(min(int(value[2]), dimensional_shape[collection_base_index + 2] - 1), 0) if collection_dimension_count > 2 else 0
                return i0, i1, i2
        return (0, 0, 0)

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

    def validate_slice_indexes(self) -> None:
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

    @property
    def actual_display_type(self):
        display_type = self.display_type
        data_and_metadata = self.__data_and_metadata
        valid_data = functools.reduce(operator.mul, self.preview_2d_shape) > 0 if self.preview_2d_shape is not None else False
        if valid_data and data_and_metadata and not display_type in ("line_plot", "image", "display_script"):
            if data_and_metadata.collection_dimension_count == 2 and data_and_metadata.datum_dimension_count == 1:
                display_type = "image"
            elif data_and_metadata.datum_dimension_count == 1:
                display_type = "line_plot"
            elif data_and_metadata.datum_dimension_count == 2:
                display_type = "image"
            # override
            if self.display_script:
                display_type = "display_script"
        if not valid_data and len(self.__child_displays_model.items) > 0:
            if display_type not in ("line_plot", ):
                display_type = "composite-image"
        return display_type

    @property
    def slice_interval(self):
        if self.__data_and_metadata and self.__data_and_metadata.dimensional_shape is not None:
            depth = self.__data_and_metadata.dimensional_shape[-1]  # signal_index
            if depth > 0:
                slice_interval_start = round(self.slice_center - self.slice_width * 0.5)
                slice_interval_end = slice_interval_start + self.slice_width
                return (float(slice_interval_start) / depth, float(slice_interval_end) / depth)
            return 0, 0
        return None

    @slice_interval.setter
    def slice_interval(self, slice_interval):
        if self.__data_and_metadata.dimensional_shape is not None:
            depth = self.__data_and_metadata.dimensional_shape[-1]  # signal_index
            if depth > 0:
                slice_interval_center = round(((slice_interval[0] + slice_interval[1]) * 0.5) * depth)
                slice_interval_width = round((slice_interval[1] - slice_interval[0]) * depth)
                self.slice_center = slice_interval_center
                self.slice_width = slice_interval_width

    def __slice_interval_changed(self, name, value):
        # notify for dependent slice_interval property
        self.__property_changed(name, value)
        self.notify_property_changed("slice_interval")

    def __display_type_changed(self, property_name, value):
        self.__property_changed(property_name, value)
        self.display_type_changed_event.fire()

    def __color_map_id_changed(self, property_name, value):
        self.__property_changed(property_name, value)
        if value:
            lookup_table_options = ColorMaps.color_maps
            self.__color_map_data = lookup_table_options.get(value)
        else:
            self.__color_map_data = None
        self.__property_changed("color_map_data", self.__color_map_data)

    @property
    def color_map_data(self) -> typing.Optional[numpy.ndarray]:
        """Return the color map data as a uint8 ndarray with shape (256, 3)."""
        if self.preview_2d_shape is None:  # is there display data?
            return None
        else:
            return self.__color_map_data if self.__color_map_data is not None else ColorMaps.color_maps.get("grayscale")

    def __property_changed(self, property_name, value):
        # when one of the defined properties changes, this gets called
        self.notify_property_changed(property_name)
        self.display_changed_event.fire()
        if property_name in ("sequence_index", "collection_index", "slice_center", "slice_width", "complex_display_type", "display_limits", "color_map_data"):
            self.display_data_will_change_event.fire()
            self.__send_next_calculated_display_values()
        if property_name in ("dimensional_calibration_style", ):
            self.notify_property_changed("displayed_dimensional_scales")
            self.notify_property_changed("displayed_dimensional_calibrations")
            self.notify_property_changed("displayed_intensity_calibration")
            calibration_style = self.__get_calibration_style_for_id(value)
            self._get_persistent_property("display_calibrated_values").value = calibration_style.is_calibrated if calibration_style else None
        if property_name in ("dimensional_calibrations", "intensity_calibration", "dimensional_scales"):
            self.notify_property_changed("displayed_dimensional_scales")
            self.notify_property_changed("displayed_dimensional_calibrations")
            self.notify_property_changed("displayed_intensity_calibration")

    # message sent when data changes.
    # thread safe
    def update_data(self, data_and_metadata):
        old_data_shape = self.__data_and_metadata.data_shape if self.__data_and_metadata else None
        self.__data_and_metadata = data_and_metadata
        new_data_shape = self.__data_and_metadata.data_shape if self.__data_and_metadata else None
        if old_data_shape != new_data_shape:
            self.validate_slice_indexes()
        self.__send_next_calculated_display_values()
        self.notify_property_changed("displayed_dimensional_calibrations")
        self.notify_property_changed("displayed_intensity_calibration")
        self.display_changed_event.fire()

    def set_storage_cache(self, storage_cache):
        self.__cache.set_storage_cache(storage_cache, self)

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
            if not self.__current_display_values:
                self.__current_display_values = DisplayValues(self.__data_and_metadata, self.sequence_index, self.collection_index, self.slice_center, self.slice_width, self.display_limits, self.complex_display_type, self.__color_map_data)

                def finalize(display_values):
                    self.__last_display_values = display_values
                    self.display_values_changed_event.fire()

                self.__current_display_values.on_finalize = finalize
            return self.__current_display_values
        return self.__last_display_values

    def increment_display_ref_count(self, amount: int=1):
        self.container.increment_display_ref_count(amount)

    def decrement_display_ref_count(self, amount: int=1):
        self.container.decrement_display_ref_count(amount)

    def _become_master(self):
        self.__is_master = True

    def _relinquish_master(self):
        self.__is_master = False

    def _changes(self):
        return self.container.data_item_changes()

    @property
    def is_live(self):
        return self.container.is_live

    def __insert_graphic(self, name, before_index, graphic):
        graphic.about_to_be_inserted(self)
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
        graphic.close()

    def __disconnect_graphic(self, graphic, index):
        graphic_changed_listener = self.__graphic_changed_listeners[index]
        graphic_changed_listener.close()
        self.__graphic_changed_listeners.remove(graphic_changed_listener)
        self.graphic_selection.remove_index(index)
        self.display_changed_event.fire()
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

    def get_graphic_by_uuid(self, graphic_uuid: uuid.UUID) -> Graphics.Graphic:
        return self.__graphics_map.get(graphic_uuid)

    # this message comes from the graphic. the connection is established when a graphic
    # is added or removed from this object.
    def graphic_changed(self, graphic):
        self.display_changed_event.fire()

    @property
    def displayed_dimensional_scales(self) -> typing.Sequence[float]:
        """The scale of the fractional coordinate system.

        For displays associated with a single data item, this matches the size of the data.

        For displays associated with a composite data item, this must be stored in this class.
        """
        if self.__data_and_metadata:
            return self.__data_and_metadata.dimensional_shape
        if self.dimensional_scales:
            return self.dimensional_scales
        return [1, 1]

    def get_dimensional_calibrations_with_calibration_style(self, dimensional_calibration_style) -> typing.Sequence[Calibration.Calibration]:
        calibration_style = self.__get_calibration_style_for_id(dimensional_calibration_style)
        if self.__data_and_metadata:
            calibration_style = CalibrationStyleNative() if calibration_style is None else calibration_style
            return calibration_style.get_dimensional_calibrations(self.__data_and_metadata.dimensional_shape, self.__data_and_metadata.dimensional_calibrations)
        else:
            calibration_style = CalibrationStyleNative() if calibration_style is None else calibration_style
            dimensional_scales = self.dimensional_scales
            dimensional_scales = [1] if dimensional_scales is None and self.display_type == "line_plot" else dimensional_scales
            dimensional_scales = [1, 1] if dimensional_scales is None and self.display_type == "image" else dimensional_scales
            dimensional_calibrations = self.dimensional_calibrations if self.dimensional_calibrations else [Calibration.Calibration() for i in range(len(dimensional_scales))]
            return calibration_style.get_dimensional_calibrations(dimensional_scales, dimensional_calibrations)

    @property
    def displayed_dimensional_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        return self.get_dimensional_calibrations_with_calibration_style(self.dimensional_calibration_style)

    def get_intensity_calibration_with_calibration_style(self, dimensional_calibration_style) -> Calibration.Calibration:
        calibration_style = self.__get_calibration_style_for_id(dimensional_calibration_style)
        if calibration_style is None or self.__data_and_metadata is None:
            if self.__data_and_metadata:
                return self.__data_and_metadata.intensity_calibration
            if self.intensity_calibration:
                return self.intensity_calibration
            return Calibration.Calibration()
        return calibration_style.get_intensity_calibration(self.__data_and_metadata)

    @property
    def displayed_intensity_calibration(self) -> Calibration.Calibration:
        return self.get_intensity_calibration_with_calibration_style(self.dimensional_calibration_style)

    @property
    def calibration_styles(self) -> typing.List[CalibrationStyle]:
        return [CalibrationStyleNative(), CalibrationStylePixelsTopLeft(), CalibrationStylePixelsCenter(),
                CalibrationStyleFractionalTopLeft(), CalibrationStyleFractionalCenter()]

    @property
    def default_calibrated_calibration_style(self):
        return CalibrationStyleNative()

    @property
    def default_uncalibrated_calibration_style(self):
        return CalibrationStylePixelsCenter()

    def __get_calibration_style_for_id(self, calibration_style_id: str) -> typing.Optional[CalibrationStyle]:
        return next(filter(lambda x: x.calibration_style_id == calibration_style_id, self.calibration_styles), None)

    def get_calibration_style_for_id(self, calibration_style_id: str) -> typing.Optional[CalibrationStyle]:
        return next(filter(lambda x: x.calibration_style_id == calibration_style_id, self.calibration_styles), self.default_calibrated_calibration_style)

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
            pos = tuple(self.collection_index[0:collection_dimension_count]) + pos

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


def display_factory(lookup_id):
    return Display()
