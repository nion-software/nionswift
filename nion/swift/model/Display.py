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

import numpy
from nion.data import Core
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import Cache
from nion.swift.model import ColorMaps
from nion.swift.model import DataItemProcessor
from nion.swift.model import Graphics
from nion.swift.model import LineGraphCanvasItem
from nion.ui import CanvasItem
from nion.utils import Event
from nion.utils import Observable
from nion.utils import Persistence
from nion.utils import Promise

_ = gettext.gettext


class GraphicSelection(object):
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
            self._indexes.remove(index)
        else:
            self._indexes.add(index)
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


class Display(Observable.Observable, Cache.Cacheable, Persistence.PersistentObject):
    # Displays are associated with exactly one data item.

    def __init__(self):
        super(Display, self).__init__()
        self.__graphics = list()
        self.define_property("display_type", changed=self.__display_type_changed)
        self.define_property("display_calibrated_values", True, changed=self.__property_changed)
        self.define_property("display_limits", validate=self.__validate_display_limits, changed=self.__display_limits_changed)
        self.define_property("y_min", changed=self.__property_changed)
        self.define_property("y_max", changed=self.__property_changed)
        self.define_property("y_style", "linear", changed=self.__property_changed)
        self.define_property("left_channel", changed=self.__property_changed)
        self.define_property("right_channel", changed=self.__property_changed)
        self.define_property("legend_labels", changed=self.__property_changed)
        self.define_property("slice_center", 0, validate=self.__validate_slice_center, changed=self.__slice_interval_changed)
        self.define_property("slice_width", 1, validate=self.__validate_slice_width, changed=self.__slice_interval_changed)
        self.define_property("color_map_id", changed=self.__color_map_id_changed)

        self.sequence_index = 0
        self.reduction_type = "slice"
        self.pick_indexes = 0, 0, 0
        self.complex_display_type = "log-absolute"

        self.__lookup = None
        self.define_relationship("graphics", Graphics.factory, insert=self.__insert_graphic, remove=self.__remove_graphic)
        self.__graphic_changed_listeners = list()
        self.__data_and_metadata = None  # the most recent data to be displayed. should have immediate data available.
        self.__display_data_and_metadata = None
        self.__display_data_and_metadata_lock = threading.RLock()
        self.__preview = None
        self.__preview_lock = threading.RLock()
        self.__thumbnail_processor = ThumbnailDataItemProcessor(self)
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
        self.__thumbnail_processor.close()
        self.__thumbnail_processor = None
        self.__graphic_selection_changed_event_listener.close()
        self.__graphic_selection_changed_event_listener = None
        for graphic in copy.copy(self.graphics):
            self.__disconnect_graphic(graphic, 0)
            graphic.close()
        self.graphic_selection = None
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        for graphic in self.graphics:
            graphic.about_to_be_removed()
        self.about_to_be_removed_event.fire()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

    @property
    def thumbnail_processor(self):
        return self.__thumbnail_processor

    @property
    def thumbnail_data(self):
        return self.__thumbnail_processor.get_cached_data() if self.__thumbnail_processor else None

    @property
    def data_for_processor(self):
        return self.display_data

    def auto_display_limits(self):
        # auto set the display limits if not yet set and data is complex
        if self.__data_and_metadata.is_data_complex_type:
            data = self.display_data
            samples, fraction = 200, 0.1
            sorted_data = numpy.sort(numpy.abs(numpy.random.choice(data.reshape(numpy.product(data.shape)), samples)))
            display_limit_low = numpy.log(sorted_data[int(samples*fraction)].astype(numpy.float64) + numpy.nextafter(0,1))
            display_limit_high = self.data_range[1]
            self.display_limits = display_limit_low, display_limit_high
        else:
            self.display_limits = self.data_range

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
                data_2d = self.display_data
                if Image.is_data_1d(data_2d):
                    data_2d = data_2d.reshape(1, data_2d.shape[0])
                if data_2d is not None:
                    data_range = self.data_range
                    display_limits = self.display_limits
                    # enforce a maximum of 1024 in either dimension on the preview for performance.
                    # but only scale by integer factors.
                    target_size = 1024.0
                    if data_2d.shape[0] > 1.5 * target_size or data_2d.shape[1] > 1.5 * target_size:
                        if data_2d.shape[0] > data_2d.shape[1]:
                            stride = round(data_2d.shape[0]/target_size)
                        else:
                            stride = round(data_2d.shape[1]/target_size)
                        data_2d = data_2d[0:data_2d.shape[0]:stride, 0:data_2d.shape[1]:stride]
                    self.__preview = Image.create_rgba_image_from_array(data_2d, data_range=data_range, display_limits=display_limits, lookup=self.__lookup)
            return self.__preview

    @property
    def display_data(self) -> numpy.ndarray:
        display_data_and_metadata = self.display_data_and_metadata
        return display_data_and_metadata.data if display_data_and_metadata else None

    def __get_display_data_and_metadata(self) -> DataAndMetadata.DataAndMetadata:
        with self.__display_data_and_metadata_lock:
            data_and_metadata = self.__data_and_metadata
            if self.__display_data_and_metadata is None and data_and_metadata is not None:
                dimensional_shape = data_and_metadata.dimensional_shape
                next_dimension = 0
                if data_and_metadata.is_sequence:
                    # next dimension is treated as a sequence index, which may be time or just a sequence index
                    sequence_index = min(max(self.sequence_index, 0), dimensional_shape[next_dimension])
                    data_and_metadata = DataAndMetadata.function_data_slice(data_and_metadata, [slice(sequence_index), Ellipsis])
                    next_dimension += 1
                if data_and_metadata and data_and_metadata.is_collection:
                    collection_index_count = data_and_metadata.collection_index_count
                    datum_index_count = data_and_metadata.datum_index_count
                    # next dimensions are treated as collection indexes.
                    if self.reduction_type == "slice" and collection_index_count in (1, 2) and datum_index_count == 1:
                        data_and_metadata = Core.function_slice_sum(data_and_metadata, self.slice_center, self.slice_width)
                    else:  # default, "pick"
                        pick_slice = [slice(pick_index) for pick_index in self.pick_indexes][0:collection_index_count] + [Ellipsis, ]
                        data_and_metadata = DataAndMetadata.function_data_slice(data_and_metadata, pick_slice)
                    next_dimension += collection_index_count + datum_index_count
                if data_and_metadata and data_and_metadata.is_data_complex_type:
                    if self.complex_display_type == "real":
                        data_and_metadata = Core.function_array(numpy.real, data_and_metadata)
                    elif self.complex_display_type == "imaginary":
                        data_and_metadata = Core.function_array(numpy.imag, data_and_metadata)
                    elif self.complex_display_type == "absolute":
                        data_and_metadata = Core.function_array(numpy.absolute, data_and_metadata)
                    else:  # default, log-absolute
                        def log_absolute(d):
                            return numpy.log(numpy.abs(d).astype(numpy.float64) + numpy.nextafter(0,1))
                        data_and_metadata = Core.function_array(log_absolute, data_and_metadata)
                if data_and_metadata and functools.reduce(operator.mul, data_and_metadata.dimensional_shape) == 0:
                    data_and_metadata = None
                self.__display_data_and_metadata = data_and_metadata
            return self.__display_data_and_metadata

    def __get_display_dimensional_shape(self) -> typing.Tuple[int, ...]:
        if not self.__data_and_metadata:
            return None
        data_and_metadata = self.__data_and_metadata
        dimensional_shape = data_and_metadata.dimensional_shape
        next_dimension = 0
        if data_and_metadata.is_sequence:
            next_dimension += 1
        if data_and_metadata.is_collection:
            collection_index_count = data_and_metadata.collection_index_count
            datum_index_count = data_and_metadata.datum_index_count
            # next dimensions are treated as collection indexes.
            if self.reduction_type == "slice" and collection_index_count in (1, 2) and datum_index_count == 1:
                return dimensional_shape[next_dimension:next_dimension + collection_index_count]
            else:  # default, "pick"
                return dimensional_shape[next_dimension + collection_index_count:next_dimension + collection_index_count + datum_index_count]
        else:
            return dimensional_shape[next_dimension:]

    @property
    def display_data_and_metadata(self) -> DataAndMetadata.DataAndMetadata:
        """Return version of the source data guaranteed to be 1-dimensional scalar or 2-dimensional and scalar or RGBA.

        Accessing display data may involve computation, so this method should not be used on UI thread.
        """
        return self.__get_display_data_and_metadata()

    @property
    def preview_2d_shape(self):
        return self.__get_display_dimensional_shape()

    @property
    def display_data_and_metadata_promise(self) -> Promise.Promise[DataAndMetadata.DataAndMetadata]:
        return Promise.Promise(lambda: self.display_data_and_metadata)

    @property
    def selected_graphics(self):
        return [self.graphics[i] for i in self.graphic_selection.indexes]

    def __validate_display_limits(self, value):
        if value is not None:
            return min(value[0], value[1]), max(value[0], value[1])
        return value

    def __display_limits_changed(self, name, value):
        self.__property_changed(name, value)
        self.notify_set_property("display_range", self.display_range)

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
            self.remove_cached_value("data_range")
            self.remove_cached_value("data_sample")
        if self.__data_and_metadata and self.__data_and_metadata.is_data_valid:
            self.__validate_data_stats()
        self.notify_set_property("slice_interval", self.slice_interval)

    def __display_type_changed(self, property_name, value):
        self.__property_changed(property_name, value)
        self.display_type_changed_event.fire()

    def __color_map_id_changed(self, property_name, value):
        self.__property_changed(property_name, value)
        if value:
            lookup_table_options = ColorMaps.color_maps
            self.__lookup = lookup_table_options.get(value)
        else:
            self.__lookup = None
        self.__property_changed("color_map_data", self.__lookup)

    @property
    def color_map_data(self) -> numpy.ndarray:
        """
        Should return an numpy array with shape (256, 3) of data type uint8
        """
        if self.preview_2d_shape is None:  # is there display data?
            return None
        else:
            return self.__lookup if self.__lookup is not None else ColorMaps.color_maps.get("grayscale")

    def __property_changed(self, property_name, value):
        # when one of the defined properties changes, this gets called
        self.__clear_cached_data()
        self.notify_set_property(property_name, value)
        self.display_changed_event.fire()
        if property_name in ("slice_center", "slice_width"):
            self.notify_set_property("display_data_and_metadata_promise", self.display_data_and_metadata_promise)

    def __validate_data_stats(self):
        """Ensure that data stats are valid after reading."""
        display_data = self.display_data
        is_data_complex_type = self.__data_and_metadata.is_data_complex_type if self.__data_and_metadata else False
        data_range = self.get_cached_value("data_range")
        data_sample = self.get_cached_value("data_sample")
        if display_data is not None and (data_range is None or (is_data_complex_type and data_sample is None)):
            self.__calculate_data_stats_for_data(display_data, self.__data_and_metadata.data_shape, self.__data_and_metadata.data_dtype)

    def __calculate_data_stats_for_data(self, display_data, data_shape, data_dtype):
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
            self.set_cached_value("data_range", data_range)
        else:
            self.remove_cached_value("data_range")
        if data_sample is not None:
            self.set_cached_value("data_sample", data_sample)
        else:
            self.remove_cached_value("data_sample")
        self.__clear_cached_data()
        self.notify_set_property("data_range", data_range)
        self.notify_set_property("data_sample", data_sample)
        self.notify_set_property("display_range", self.__get_display_range(data_range, data_sample))

    @property
    def data_range(self):
        self.__validate_data_stats()
        return self.get_cached_value("data_range")

    @property
    def data_sample(self):
        self.__validate_data_stats()
        return self.get_cached_value("data_sample")

    def __get_display_range(self, data_range, data_sample):
        if self.display_limits is not None:
            return self.display_limits
        if self.__data_and_metadata and self.__data_and_metadata.is_data_complex_type:
            if data_sample is not None:
                data_sample_10 = data_sample[int(len(data_sample) * 0.1)]
                display_limit_low = numpy.log(data_sample_10) if data_sample_10 > 0.0 else data_range[0]
                display_limit_high = data_range[1]
                return display_limit_low, display_limit_high
        return data_range

    @property
    def display_range(self):
        self.__validate_data_stats()
        return self.__get_display_range(self.data_range, self.data_sample)

    @display_range.setter
    def display_range(self, display_range):
        # NOTE: setting display_range actually just sets display limits. helpful for inspector bindings.
        self.display_limits = display_range

    # message sent from buffered_data_source when data changes.
    # thread safe
    def update_data(self, data_and_metadata):
        old_data_shape = self.__data_and_metadata.data_shape if self.__data_and_metadata else None
        self.__data_and_metadata = data_and_metadata
        new_data_shape = self.__data_and_metadata.data_shape if self.__data_and_metadata else None
        self.__clear_cached_data()
        if old_data_shape != new_data_shape:
            self.validate()
        if not self._is_reading:
            self.remove_cached_value("data_range")
            self.remove_cached_value("data_sample")
            self.__validate_data_stats()
        self.notify_set_property("display_data_and_metadata_promise", self.display_data_and_metadata_promise)
        self.display_changed_event.fire()

    def __clear_cached_data(self):
        with self.__display_data_and_metadata_lock:
            self.__display_data_and_metadata = None
        with self.__preview_lock:
            self.__preview = None
        # clear the processor caches
        if not self._is_reading:
            self.__thumbnail_processor.mark_data_dirty()

    def __insert_graphic(self, name, before_index, item):
        graphic_changed_listener = item.graphic_changed_event.listen(functools.partial(self.graphic_changed, item))
        self.__graphic_changed_listeners.insert(before_index, graphic_changed_listener)
        self.graphic_selection.insert_index(before_index)
        self.display_changed_event.fire()
        self.notify_insert_item("graphics", item, before_index)

    def __remove_graphic(self, name, index, graphic):
        graphic.about_to_be_removed()
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

    # this message comes from the graphic. the connection is established when a graphic
    # is added or removed from this object.
    def graphic_changed(self, graphic):
        self.display_changed_event.fire()

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(Display, self).notify_set_property(key, value)
        if not self._is_reading:
            self.__thumbnail_processor.item_property_changed(key, value)

    # called from processors
    def processor_needs_recompute(self, processor):
        self.display_processor_needs_recompute_event.fire(processor)

    # called from processors
    def processor_data_updated(self, processor):
        self.display_processor_data_updated_event.fire(processor)


class ThumbnailDataItemProcessor(DataItemProcessor.DataItemProcessor):

    def __init__(self, display):
        super(ThumbnailDataItemProcessor, self).__init__(display, "thumbnail_data")
        self.width = 72
        self.height = 72

    def get_calculated_data(self, ui, data):
        thumbnail_data = None
        assert isinstance(self.item, Display)
        if Image.is_data_1d(data):
            thumbnail_data = self.__get_thumbnail_1d_data(ui, data, self.height, self.width)
        elif Image.is_data_2d(data):
            data_range = self.item.data_range
            display_limits = self.item.display_limits
            thumbnail_data = self.__get_thumbnail_2d_data(ui, data, self.height, self.width, data_range, display_limits)
        return thumbnail_data

    def get_default_data(self):
        return numpy.zeros((self.height, self.width), dtype=numpy.uint32)

    def __get_thumbnail_1d_data(self, ui, data, height, width):
        assert data is not None
        assert Image.is_data_1d(data)
        data = Image.convert_to_grayscale(data)
        data_info = LineGraphCanvasItem.LineGraphDataInfo(lambda: data, data_left=0, data_right=data.shape[0])
        line_graph_area_stack = CanvasItem.CanvasItemComposition()
        line_graph_background = LineGraphCanvasItem.LineGraphBackgroundCanvasItem()
        line_graph_background.draw_grid = False
        line_graph_background.background_color = "#EEEEEE"
        line_graph_background.data_info = data_info
        line_graph_canvas_item = LineGraphCanvasItem.LineGraphCanvasItem()
        line_graph_canvas_item.draw_captions = False
        line_graph_canvas_item.graph_background_color = "rgba(0,0,0,0)"
        line_graph_canvas_item.data_info = data_info
        line_graph_frame = LineGraphCanvasItem.LineGraphFrameCanvasItem()
        line_graph_frame.data_info = data_info
        line_graph_area_stack.add_canvas_item(line_graph_background)
        line_graph_area_stack.add_canvas_item(line_graph_canvas_item)
        line_graph_area_stack.add_canvas_item(line_graph_frame)
        line_graph_area_stack.update_layout(((height - width / 1.618) * 0.5, 0), (width / 1.618, width))
        drawing_context = ui.create_offscreen_drawing_context()
        drawing_context.save()
        drawing_context.begin_path()
        drawing_context.rect(0, 0, width, height)
        drawing_context.fill_style = "#EEEEEE"
        drawing_context.fill()
        drawing_context.restore()
        drawing_context.translate(0, (height - width / 1.618) * 0.5)
        line_graph_area_stack._repaint(drawing_context)
        return ui.create_rgba_image(drawing_context, width, height)

    def __get_thumbnail_2d_data(self, ui, image, height, width, data_range, display_limits):
        assert image is not None
        assert Image.is_data_2d(image)
        image = Image.scalar_from_array(image)
        image_height = image.shape[0]
        image_width = image.shape[1]
        if image_height > 0 and image_width > 0:
            scaled_height = height if image_height > image_width else height * image_height // image_width
            scaled_width = width if image_width > image_height else width * image_width // image_height
            scaled_height = max(1, scaled_height)
            scaled_width = max(1, scaled_width)
            thumbnail_image = Image.scaled(image, (scaled_height, scaled_width), 'nearest')
            if data_range is None or not (any([math.isnan(x) for x in data_range]) or any([math.isinf(x) for x in data_range])):
                return Image.create_rgba_image_from_array(thumbnail_image, data_range=data_range, display_limits=display_limits)
        return self.get_default_data()


def display_factory(lookup_id):
    return Display()
