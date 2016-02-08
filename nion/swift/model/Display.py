"""
    Contains classes related to display of data items.
"""

# futures
from __future__ import absolute_import
from __future__ import division

# standard libraries
import copy
import functools
import math
import gettext
import numbers
import operator

# third party libraries
import numpy

# local libraries
from nion.swift.model import Cache
from nion.swift.model import DataAndMetadata
from nion.swift.model import DataItemProcessor
from nion.swift.model import Graphics
from nion.swift.model import Image
from nion.swift.model import LineGraphCanvasItem
from nion.swift.model import Symbolic
from nion.ui import CanvasItem
from nion.ui import Event
from nion.ui import Model
from nion.ui import Observable
from nion.ui import Persistence

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


class Display(Observable.Observable, Observable.Broadcaster, Cache.Cacheable, Persistence.PersistentObject):
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
        self.define_property("slice_center", 0, validate=self.__validate_slice_center, changed=self.__slice_interval_changed)
        self.define_property("slice_width", 1, validate=self.__validate_slice_width, changed=self.__slice_interval_changed)
        self.__lookup = None  # temporary for experimentation
        self.define_relationship("graphics", Graphics.factory, insert=self.__insert_graphic, remove=self.__remove_graphic)
        self.__drawn_graphics = Model.ListModel(self, "drawn_graphics")
        self.__graphic_changed_listeners = list()
        self.__remove_region_graphic_listeners = list()
        self.__data_and_calibration = None  # the most recent data to be displayed. should have immediate data available.
        self.__display_data = None
        self.__preview = None
        self.__preview_last = None
        self.__processors = dict()
        self.__processors["statistics"] = StatisticsDataItemProcessor(self)
        self.__processors["thumbnail"] = ThumbnailDataItemProcessor(self)
        self.__processors["histogram"] = HistogramDataItemProcessor(self)
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
        self._about_to_be_removed = False
        self._closed = False

    def close(self):
        for processor in self.__processors.values():
            processor.close()
        self.__processors = None
        self.__graphic_selection_changed_event_listener.close()
        self.__graphic_selection_changed_event_listener = None
        for graphic in copy.copy(self.graphics):
            self.__disconnect_graphic(graphic)
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

    def get_processor(self, processor_id):
        # check for case where we might already be closed. not pretty.
        # TODO: get_processor should never be called after close
        return self.__processors[processor_id] if self.__processors else None

    @property
    def data_and_calibration(self):
        return self.__data_and_calibration

    @property
    def data_for_processor(self):
        return self.display_data

    def auto_display_limits(self):
        # auto set the display limits if not yet set and data is complex
        if self.__data_and_calibration.is_data_complex_type and self.display_limits is None:
            data = self.display_data
            samples, fraction = 200, 0.1
            sorted_data = numpy.sort(numpy.abs(numpy.random.choice(data.reshape(numpy.product(data.shape)), samples)))
            display_limit_low = numpy.log(sorted_data[samples*fraction])
            display_limit_high = self.data_range[1]
            self.display_limits = display_limit_low, display_limit_high

    @property
    def preview_2d(self):
        if self.__preview is None:
            data_2d = self.display_data
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
                self.__preview = Image.create_rgba_image_from_array(data_2d, data_range=data_range, display_limits=display_limits, lookup=self.__lookup, existing=self.__preview_last)
        return self.__preview

    @property
    def display_data(self):
        try:
            if self.__display_data is None:
                if self.__data_and_calibration:
                    data = self.__data_and_calibration.data
                    if Image.is_data_1d(data):
                        display_data = Image.scalar_from_array(data)
                    elif Image.is_data_2d(data):
                        display_data = Image.scalar_from_array(data)
                    elif Image.is_data_3d(data):
                        display_data = Image.scalar_from_array(Symbolic.function_slice_sum(self.__data_and_calibration, self.slice_center, self.slice_width).data)
                    else:
                        display_data = None
                    self.__display_data = display_data
            return self.__display_data
        except Exception as e:
            import traceback
            traceback.print_exc()
            traceback.print_stack()
            raise

    @property
    def display_data_and_calibration(self):
        """Return version of the source data guaranteed to be 1-dimensional scalar or 2-dimensional and scalar or RGBA."""
        if self.__data_and_calibration:
            if self.__data_and_calibration.is_data_1d:
                data_shape_and_dtype = self.__data_and_calibration.data_shape_and_dtype
                intensity_calibration = self.__data_and_calibration.intensity_calibration
                dimensional_calibrations = self.__data_and_calibration.dimensional_calibrations
                metadata = self.__data_and_calibration.metadata
                timestamp = self.__data_and_calibration.timestamp
                return DataAndMetadata.DataAndMetadata(lambda: self.display_data, data_shape_and_dtype,
                                                       intensity_calibration, dimensional_calibrations, metadata,
                                                       timestamp)
            elif self.__data_and_calibration.is_data_2d:
                data_shape_and_dtype = self.__data_and_calibration.data_shape_and_dtype
                intensity_calibration = self.__data_and_calibration.intensity_calibration
                dimensional_calibrations = self.__data_and_calibration.dimensional_calibrations
                metadata = self.__data_and_calibration.metadata
                timestamp = self.__data_and_calibration.timestamp
                return DataAndMetadata.DataAndMetadata(lambda: self.display_data, data_shape_and_dtype,
                                                       intensity_calibration, dimensional_calibrations, metadata,
                                                       timestamp)
            elif self.__data_and_calibration.is_data_3d:
                data_shape, data_dtype = self.__data_and_calibration.data_shape_and_dtype
                data_shape_and_dtype = data_shape[1:], data_dtype
                intensity_calibration = self.__data_and_calibration.intensity_calibration
                dimensional_calibrations = self.__data_and_calibration.dimensional_calibrations[1:]
                metadata = self.__data_and_calibration.metadata
                timestamp = self.__data_and_calibration.timestamp
                return DataAndMetadata.DataAndMetadata(lambda: self.display_data, data_shape_and_dtype,
                                                       intensity_calibration, dimensional_calibrations, metadata,
                                                       timestamp)
        return None

    @property
    def preview_2d_shape(self):
        if self.__data_and_calibration.is_data_2d:
            return self.__data_and_calibration.dimensional_shape
        elif self.__data_and_calibration.is_data_3d:
            return self.__data_and_calibration.dimensional_shape[1:]
        else:
            return None

    def get_processed_data(self, processor_id):
        return self.get_processor(processor_id).get_cached_data()

    @property
    def drawn_graphics(self):
        return copy.copy(self.__drawn_graphics)

    @property
    def selected_graphics(self):
        return [self.__drawn_graphics[i] for i in self.graphic_selection.indexes]

    def __validate_display_limits(self, value):
        if value is not None:
            return min(value[0], value[1]), max(value[0], value[1])
        return value

    def __display_limits_changed(self, name, value):
        self.__property_changed(name, value)
        self.notify_set_property("display_range", self.display_range)

    def __validate_slice_center_for_width(self, value, slice_width):
        if self.__data_and_calibration and self.__data_and_calibration.dimensional_shape is not None:
            depth = self.__data_and_calibration.dimensional_shape[0]
            mn = max(int(slice_width * 0.5), 0)
            mx = min(int(depth - slice_width * 0.5), depth - 1)
            return min(max(int(value), mn), mx)
        return value if self._is_reading else 0

    def __validate_slice_center(self, value):
        return self.__validate_slice_center_for_width(value, self.slice_width)

    def __validate_slice_width(self, value):
        if self.__data_and_calibration and self.__data_and_calibration.dimensional_shape is not None:
            depth = self.__data_and_calibration.dimensional_shape[0]
            slice_center = self.slice_center
            mn = 1
            mx = max(min(slice_center, depth - slice_center) * 2, 1)
            return min(max(value, mn), mx)
        return value if self._is_reading else 1

    @property
    def slice_interval(self):
        if self.__data_and_calibration and self.__data_and_calibration.dimensional_shape is not None:
            depth = self.__data_and_calibration.dimensional_shape[0]
            if depth > 0:
                slice_interval_start = int(self.slice_center + 1 - self.slice_width * 0.5)
                slice_interval_end = slice_interval_start + self.slice_width
                return (float(slice_interval_start) / depth, float(slice_interval_end) / depth)
        return None

    @slice_interval.setter
    def slice_interval(self, slice_interval):
        if self.__data_and_calibration.dimensional_shape is not None:
            depth = self.__data_and_calibration.dimensional_shape[0]
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
        self.__validate_data_stats()
        self.notify_set_property("slice_interval", self.slice_interval)

    def __display_type_changed(self, property_name, value):
        self.__property_changed(property_name, value)
        self.display_type_changed_event.fire()

    def __property_changed(self, property_name, value):
        # when one of the defined properties changes, this gets called
        self.__clear_cached_data()
        self.notify_set_property(property_name, value)
        self.display_changed_event.fire()

    @property
    def lookup_table(self):
        return self.__lookup

    @lookup_table.setter
    def lookup_table(self, lookup):
        self.__lookup = lookup
        self.__clear_cached_data()
        self.display_changed_event.fire()

    def __validate_data_stats(self):
        """Ensure that data stats are valid after reading."""
        display_data = self.display_data
        is_data_complex_type = self.__data_and_calibration.is_data_complex_type if self.__data_and_calibration else False
        data_range = self.get_cached_value("data_range")
        data_sample = self.get_cached_value("data_sample")
        if display_data is not None and (data_range is None or (is_data_complex_type and data_sample is None)):
            self.__calculate_data_stats_for_data(display_data)

    def __calculate_data_stats_for_data(self, data):
        if data is not None and data.size:
            if Image.is_shape_and_dtype_rgb_type(data.shape, data.dtype):
                data_range = (0, 255)
                data_sample = None
            elif Image.is_shape_and_dtype_complex_type(data.shape, data.dtype):
                scalar_data = Image.scalar_from_array(data)
                data_range = (numpy.amin(scalar_data), numpy.amax(scalar_data))
                data_sample = numpy.sort(numpy.abs(numpy.random.choice(data.reshape(numpy.product(data.shape)), 200)))
            else:
                data_range = (numpy.amin(data), numpy.amax(data))
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
        if self.__data_and_calibration and self.__data_and_calibration.is_data_complex_type:
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
    def update_data(self, data_and_calibration):
        old_data_shape = self.__data_and_calibration.data_shape if self.__data_and_calibration else None
        self.__data_and_calibration = data_and_calibration
        new_data_shape = self.__data_and_calibration.data_shape if self.__data_and_calibration else None
        self.__clear_cached_data()
        if old_data_shape != new_data_shape:
            slice_center = self.__validate_slice_center_for_width(self.slice_center, 1)
            if slice_center != self.slice_center:
                old_slice_width = self.slice_width
                self.slice_width = 1
                self.slice_center = self.slice_center
                self.slice_width = old_slice_width
        if not self._is_reading:
            self.remove_cached_value("data_range")
            self.remove_cached_value("data_sample")
            self.__validate_data_stats()
        self.display_changed_event.fire()

    def __clear_cached_data(self):
        self.__display_data = None
        if self.__preview is not None:
            self.__preview_last = self.__preview
        self.__preview = None
        # clear the processor caches
        if not self._is_reading:
            for processor in self.__processors.values():
                processor.mark_data_dirty()

    def add_region_graphic(self, region_graphic):
        region_graphic.add_listener(self)
        before_index = len(self.__drawn_graphics)
        self.__drawn_graphics.insert(before_index, region_graphic)
        graphic_changed_listener = region_graphic.graphic_changed_event.listen(functools.partial(self.graphic_changed, region_graphic))
        self.__graphic_changed_listeners.insert(before_index, graphic_changed_listener)
        remove_region_graphic_listener = region_graphic.remove_region_graphic_event.listen(functools.partial(self.remove_region_graphic, region_graphic))
        self.__remove_region_graphic_listeners.insert(before_index, remove_region_graphic_listener)
        self.graphic_selection.insert_index(before_index)
        self.display_changed_event.fire()

    def remove_region_graphic(self, region_graphic):
        if region_graphic in self.__drawn_graphics:
            # this hack (checking if region_graphic is in drawn graphics)
            # is here because removing a region may remove a data item which
            # will in turn remove the same region.
            # bad architecture.
            region_graphic.remove_listener(self)
            # region_graphic.about_to_be_removed()
            index = self.__drawn_graphics.index(region_graphic)
            self.__drawn_graphics.remove(region_graphic)
            graphic_changed_listener = self.__graphic_changed_listeners[index]
            graphic_changed_listener.close()
            self.__graphic_changed_listeners.remove(graphic_changed_listener)
            remove_region_graphic_listener = self.__remove_region_graphic_listeners[index]
            remove_region_graphic_listener.close()
            self.__remove_region_graphic_listeners.remove(remove_region_graphic_listener)
            self.graphic_selection.remove_index(index)
            self.display_changed_event.fire()

    def __insert_graphic(self, name, before_index, item):
        item.add_listener(self)
        self.__drawn_graphics.insert(before_index, item)
        graphic_changed_listener = item.graphic_changed_event.listen(functools.partial(self.graphic_changed, item))
        self.__graphic_changed_listeners.insert(before_index, graphic_changed_listener)
        remove_region_graphic_listener = item.remove_region_graphic_event.listen(functools.partial(self.remove_region_graphic, item))
        self.__remove_region_graphic_listeners.insert(before_index, remove_region_graphic_listener)
        self.graphic_selection.insert_index(before_index)
        self.display_changed_event.fire()

    def __remove_graphic(self, name, index, graphic):
        graphic.about_to_be_removed()
        self.__disconnect_graphic(graphic)
        graphic.close()

    def __disconnect_graphic(self, graphic):
        graphic.remove_listener(self)
        index = self.__drawn_graphics.index(graphic)
        self.__drawn_graphics.remove(graphic)
        graphic_changed_listener = self.__graphic_changed_listeners[index]
        graphic_changed_listener.close()
        self.__graphic_changed_listeners.remove(graphic_changed_listener)
        remove_region_graphic_listener = self.__remove_region_graphic_listeners[index]
        remove_region_graphic_listener.close()
        self.__remove_region_graphic_listeners.remove(remove_region_graphic_listener)
        self.graphic_selection.remove_index(index)
        self.display_changed_event.fire()

    def insert_graphic(self, before_index, graphic):
        """ Insert a graphic before the index """
        self.insert_item("graphics", before_index, graphic)

    def append_graphic(self, graphic):
        """ Append a graphic """
        self.append_item("graphics", graphic)

    def remove_graphic(self, graphic):
        """ Remove a graphic """
        self.remove_item("graphics", graphic)

    def extend_graphics(self, graphics):
        """ Extend the graphics array with the list of graphics """
        self.extend_items("graphics", graphics)

    def remove_drawn_graphic(self, drawn_graphic):
        """ Remove a drawn graphic which might be intrinsic or a graphic associated with an operation on a child """
        if drawn_graphic in self.graphics:
            self.remove_graphic(drawn_graphic)
        else:  # a synthesized graphic
            drawn_graphic.notify_remove_region_graphic()

    # this message comes from the graphic. the connection is established when a graphic
    # is added or removed from this object.
    def graphic_changed(self, graphic):
        self.display_changed_event.fire()

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(Display, self).notify_set_property(key, value)
        if not self._is_reading:
            for processor in self.__processors.values():
                processor.item_property_changed(key, value)

    # called from processors
    def processor_needs_recompute(self, processor):
        self.display_processor_needs_recompute_event.fire(processor)

    # called from processors
    def processor_data_updated(self, processor):
        self.display_processor_data_updated_event.fire(processor)


class StatisticsDataItemProcessor(DataItemProcessor.DataItemProcessor):

    def __init__(self, buffered_data_source):
        super(StatisticsDataItemProcessor, self).__init__(buffered_data_source, "statistics_data_2")

    def get_calculated_data(self, ui, data):
        #logging.debug("Calculating statistics %s", self)
        mean = numpy.mean(data)
        std = numpy.std(data)
        rms = numpy.sqrt(numpy.mean(numpy.absolute(data)**2))
        sum = mean * functools.reduce(operator.mul, Image.dimensional_shape_from_shape_and_dtype(data.shape, data.dtype))
        data_range = self.item.data_range
        data_min, data_max = data_range if data_range is not None else (None, None)
        return { "mean": mean, "std": std, "min": data_min, "max": data_max, "rms": rms, "sum": sum }

    def get_default_data(self):
        return { }


class HistogramDataItemProcessor(DataItemProcessor.DataItemProcessor):

    def __init__(self, display):
        super(HistogramDataItemProcessor, self).__init__(display, "histogram_data")
        self.bins = 320
        self.subsample = None  # hard coded subsample size
        self.subsample_fraction = None  # fraction of total pixels
        self.subsample_min = 1024  # minimum subsample size

    def item_property_changed(self, key, value):
        """ Called directly from data item. """
        super(HistogramDataItemProcessor, self).item_property_changed(key, value)
        if key == "display_limits" or key == "slice_interval":
            self._set_cached_value_dirty()

    def get_calculated_data(self, ui, data):
        subsample = self.subsample
        total_pixels = numpy.product(data.shape)
        if not subsample and self.subsample_fraction:
            subsample = min(max(total_pixels * self.subsample_fraction, self.subsample_min), total_pixels)
        if subsample:
            factor = total_pixels / subsample
            data_sample = numpy.random.choice(data.reshape(numpy.product(data.shape)), subsample)
        else:
            factor = 1.0
            data_sample = numpy.copy(data)
        display_range = self.item.display_range  # may be None
        if display_range is None or data_sample is None:
            return None
        histogram_data = factor * numpy.histogram(data_sample, range=display_range, bins=self.bins)[0]
        histogram_max = numpy.max(histogram_data)  # assumes that histogram_data is int
        if histogram_max > 0:
            histogram_data = histogram_data / float(histogram_max)
        return histogram_data


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
        assert image.ndim in (2,3)
        image = Image.scalar_from_array(image)
        image_height = image.shape[0]
        image_width = image.shape[1]
        if image_height > 0 and image_width > 0:
            scaled_height = height if image_height > image_width else height * image_height // image_width
            scaled_width = width if image_width > image_height else width * image_width // image_height
            scaled_height = max(1, scaled_height)
            scaled_width = max(1, scaled_width)
            thumbnail_image = Image.scaled(image, (scaled_height, scaled_width), 'nearest')
            if numpy.ndim(thumbnail_image) == 2:
                if data_range is not None and (any([math.isnan(x) for x in data_range]) or any([math.isinf(x) for x in data_range])):
                    return self.get_default_data()
                else:
                    return Image.create_rgba_image_from_array(thumbnail_image, data_range=data_range, display_limits=display_limits)
            elif numpy.ndim(thumbnail_image) == 3:
                data = thumbnail_image
                if thumbnail_image.shape[2] == 4:
                    return data.view(numpy.uint32).reshape(data.shape[:-1])
                elif thumbnail_image.shape[2] == 3:
                    rgba = numpy.empty(data.shape[:-1] + (4,), numpy.uint8)
                    rgba[:,:,0:3] = data
                    rgba[:,:,3] = 255
                    return rgba.view(numpy.uint32).reshape(rgba.shape[:-1])
        else:
            return self.get_default_data()


def display_factory(lookup_id):
    return Display()
