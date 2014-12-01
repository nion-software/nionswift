"""
    Contains classes related to display of data items.
"""

# standard libraries
import copy
import logging
import gettext
import numbers
import weakref
import uuid

# third party libraries
import numpy

# local libraries
from nion.swift.model import DataItemProcessor
from nion.swift.model import Graphics
from nion.swift.model import Image
from nion.swift.model import LineGraphCanvasItem
from nion.swift.model import Operation
from nion.swift.model import Storage
from nion.ui import Model
from nion.ui import Observable

_ = gettext.gettext


class GraphicSelection(Observable.Broadcaster):
    def __init__(self):
        super(GraphicSelection, self).__init__()
        self.__indexes = set()
    # manage selection
    def __get_current_index(self):
        if len(self.__indexes) == 1:
            for index in self.__indexes:
                return index
        return None
    current_index = property(__get_current_index)
    def has_selection(self):
        return len(self.__indexes) > 0
    def contains(self, index):
        return index in self.__indexes
    def __get_indexes(self):
        return self.__indexes
    indexes = property(__get_indexes)
    def clear(self):
        old_index = self.__indexes.copy()
        self.__indexes = set()
        if old_index != self.__indexes:
            self.notify_listeners("graphic_selection_changed", self)
    def add(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes.add(index)
        if old_index != self.__indexes:
            self.notify_listeners("graphic_selection_changed", self)
    def remove(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes.remove(index)
        if old_index != self.__indexes:
            self.notify_listeners("graphic_selection_changed", self)
    def set(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        self.__indexes = set()
        self.__indexes.add(index)
        if old_index != self.__indexes:
            self.notify_listeners("graphic_selection_changed", self)
    def toggle(self, index):
        assert isinstance(index, numbers.Integral)
        old_index = self.__indexes.copy()
        if index in self.__indexes:
            self._indexes.remove(index)
        else:
            self._indexes.add(index)
        if old_index != self.__indexes:
            self.notify_listeners("graphic_selection_changed", self)
    def insert_index(self, new_index):
        new_indexes = set()
        for index in self.__indexes:
            if index < new_index:
                new_indexes.add(index)
            else:
                new_indexes.add(index+1)
        if self.__indexes != new_indexes:
            self.__indexes = new_indexes
            self.notify_listeners("graphic_selection_changed", self)
    def remove_index(self, remove_index):
        new_indexes = set()
        for index in self.__indexes:
            if index != remove_index:
                if index > remove_index:
                    new_indexes.add(index-1)
                else:
                    new_indexes.add(index)
        if self.__indexes != new_indexes:
            self.__indexes = new_indexes
            self.notify_listeners("graphic_selection_changed", self)


class Display(Observable.Observable, Observable.Broadcaster, Storage.Cacheable, Observable.ManagedObject):
    # Displays are associated with exactly one data item.

    def __init__(self):
        super(Display, self).__init__()
        self.__weak_data_item = None
        self.__graphics = list()
        self.define_property("display_calibrated_values", True, changed=self.__property_changed)
        self.define_property("display_limits", validate=self.__validate_display_limits, changed=self.__display_limits_changed)
        self.define_property("y_min", changed=self.__property_changed)
        self.define_property("y_max", changed=self.__property_changed)
        self.define_property("left_channel", changed=self.__property_changed)
        self.define_property("right_channel", changed=self.__property_changed)
        self.define_property("slice_center", 0, changed=self.__slice_interval_changed)
        self.define_property("slice_width", 1, changed=self.__slice_interval_changed)
        self.__lookup = None  # temporary for experimentation
        self.define_relationship("graphics", Graphics.factory, insert=self.__insert_graphic, remove=self.__remove_graphic)
        self.__drawn_graphics = Model.ListModel(self, "drawn_graphics")
        self.__preview_data = None
        self.__preview = None
        self.__processors = dict()
        self.__processors["thumbnail"] = ThumbnailDataItemProcessor(self)
        self.__processors["histogram"] = HistogramDataItemProcessor(self)
        self.graphic_selection = GraphicSelection()
        self.graphic_selection.add_listener(self)

    def close(self):
        for processor in self.__processors.values():
            processor.close()
        self.__processors = None

    def about_to_be_removed(self):
        self.graphic_selection.remove_listener(self)
        self.graphic_selection = None

    def graphic_selection_changed(self, graphic_selection):
        """ This message comes from the graphic selection object. Notify our listeners too. """
        self.notify_listeners("display_graphic_selection_changed", self, graphic_selection)

    def get_processor(self, processor_id):
        return self.__processors[processor_id]

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    data_item = property(__get_data_item)

    # called from data item when added/removed.
    def _set_data_item(self, data_item):
        if self.data_item:
            self.data_item.remove_observer(self)
            self.data_item.remove_listener(self)
            self.storage_cache = None
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
        if self.data_item:
            self.data_item.add_observer(self)
            self.data_item.add_listener(self)
            self.storage_cache = self.data_item.storage_cache

    def auto_display_limits(self):
        # auto set the display limits if not yet set and data is complex
        if self.data_item.is_data_complex_type and self.display_limits is None:
            data = self.data_item.data
            samples, fraction = 200, 0.1
            sorted_data = numpy.sort(numpy.abs(numpy.random.choice(data.reshape(numpy.product(data.shape)), samples)))
            display_limit_low = numpy.log(sorted_data[samples*fraction])
            display_limit_high = self.data_item.data_range[1]
            self.display_limits = display_limit_low, display_limit_high

    def __get_preview_2d(self):
        if self.__preview is None:
            data_2d = self.preview_2d_data
            if data_2d is not None:
                data_range = self.data_range
                display_limits = self.display_limits
                self.__preview = Image.create_rgba_image_from_array(data_2d, data_range=data_range, display_limits=display_limits, lookup=self.__lookup)
        return self.__preview
    preview_2d = property(__get_preview_2d)

    def __get_preview_2d_data(self):
        if self.__preview_data is None:
            data = self.data_item.data
            if Image.is_data_2d(data):
                data_2d = Image.scalar_from_array(data)
            # TODO: fix me 3d
            elif Image.is_data_3d(data):
                slice_operation = Operation.Slice3dOperation()
                slice_operation.slice_center = self.slice_center
                slice_operation.slice_width = self.slice_width
                data_2d = slice_operation.process(data)
            else:
                data_2d = None
            self.__preview_data = data_2d
        return self.__preview_data
    preview_2d_data = property(__get_preview_2d_data)

    def __get_preview_2d_shape(self):
        if self.data_item.is_data_2d:
            return self.data_item.spatial_shape
        elif self.data_item.is_data_3d:
            return self.data_item.spatial_shape[1:]
        else:
            return None
    preview_2d_shape = property(__get_preview_2d_shape)

    def get_processed_data(self, processor_id):
        return self.get_processor(processor_id).get_cached_data()

    def __get_drawn_graphics(self):
        return copy.copy(self.__drawn_graphics)
    drawn_graphics = property(__get_drawn_graphics)

    def __validate_display_limits(self, value):
        if value is not None:
            return min(value[0], value[1]), max(value[0], value[1])
        return value

    def __display_limits_changed(self, name, value):
        self.__property_changed(name, value)
        self.notify_set_property("display_range", self.display_range)

    def __get_slice_interval(self):
        if self.data_item:
            depth = self.data_item.spatial_shape[0]
            slice_interval_start = int(self.slice_center + 1 - self.slice_width * 0.5)
            slice_interval_end = slice_interval_start + self.slice_width
            return (float(slice_interval_start) / depth, float(slice_interval_end) / depth)
        return None
    def __set_slice_interval(self, slice_interval):
        depth = self.data_item.spatial_shape[0]
        slice_interval_center = int(((slice_interval[0] + slice_interval[1]) * 0.5) * depth)
        slice_interval_width = int((slice_interval[1] - slice_interval[0]) * depth)
        self.slice_center = slice_interval_center
        self.slice_width = slice_interval_width
    slice_interval = property(__get_slice_interval, __set_slice_interval)

    def __slice_interval_changed(self, name, value):
        self.__property_changed(name, value)
        self.notify_set_property("slice_interval", self.slice_interval)

    def __property_changed(self, property_name, value):
        self.notify_set_property(property_name, value)
        self.__preview_data = None
        self.__preview = None
        self.notify_listeners("display_changed", self)

    def __get_lookup_table(self):
        return self.__lookup
    def __set_lookup_table(self, lookup):
        self.__lookup = lookup
        self.__preview_data = None
        self.__preview = None
        self.notify_listeners("display_changed", self)
    lookup_table = property(__get_lookup_table, __set_lookup_table)

    def __get_data_range(self):
        return self.data_item.data_range if self.data_item else None
    data_range = property(__get_data_range)

    def __get_display_range(self):
        data_range = self.data_range
        return self.display_limits if self.display_limits else data_range
    def __set_display_range(self, display_range):
        self.display_limits = display_range
    # TODO: this is only valid after data has been called (!)
    # NOTE: setting display_range actually just sets display limits. helpful for inspector bindings.
    display_range = property(__get_display_range, __set_display_range)

    # message sent from data_item or graphics. established using add/remove observer.
    def property_changed(self, object, property, value):
        if property == "data_range":
            self.__preview_data = None
            self.__preview = None
            self.notify_set_property(property, value)
            if self.data_item:
                self.notify_set_property("display_range", self.display_range)

    # this message received from data item. the connection is established using
    # add_listener and remove_listener.
    # thread safe
    def data_item_content_changed(self, data_item, changes):
        DATA = 1
        METADATA = 2
        SOURCE = 4
        if DATA in changes or METADATA in changes or SOURCE in changes:
            # TODO: Threading: Display data_item_content_changed __preview, __preview_data
            self.__preview_data = None
            self.__preview = None
            self.notify_listeners("display_changed", self)
            # clear the processor caches
            if not self._is_reading:
                for processor in self.__processors.values():
                    processor.data_item_changed()

    # this message received from data item. the connection is established using
    # add_listener and remove_listener.
    def data_item_needs_recompute(self, data_item):
        for processor in self.__processors.values():
            processor.data_item_changed()

    def add_region_graphic(self, region_graphic):
        region_graphic.add_listener(self)
        before_index = len(self.__drawn_graphics)
        self.__drawn_graphics.insert(before_index, region_graphic)
        self.graphic_selection.insert_index(before_index)
        self.notify_listeners("display_changed", self)

    def remove_region_graphic(self, region_graphic):
        if region_graphic in self.__drawn_graphics:
            # this hack (checking if region_graphic is in drawn graphics)
            # is here because removing a region may remove a data item which
            # will in turn remove the same region.
            # bad architecture.
            region_graphic.remove_listener(self)
            index = self.__drawn_graphics.index(region_graphic)
            self.__drawn_graphics.remove(region_graphic)
            self.graphic_selection.remove_index(index)
            self.notify_listeners("display_changed", self)

    def __insert_graphic(self, name, before_index, item):
        item.add_listener(self)
        item.add_observer(self)
        self.__drawn_graphics.insert(before_index, item)
        self.graphic_selection.insert_index(before_index)
        self.notify_listeners("display_changed", self)

    def __remove_graphic(self, name, index, item):
        item.remove_listener(self)
        item.remove_observer(self)
        index = self.__drawn_graphics.index(item)
        self.__drawn_graphics.remove(item)
        self.graphic_selection.remove_index(index)
        self.notify_listeners("display_changed", self)

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

    # drawn graphics and the regular graphic items, plus those derived from the operation classes
    def __get_drawn_graphics(self):
        """ List of drawn graphics """
        return self.__drawn_graphics
    drawn_graphics = property(__get_drawn_graphics)

    def remove_drawn_graphic(self, drawn_graphic):
        """ Remove a drawn graphic which might be intrinsic or a graphic associated with an operation on a child """
        if drawn_graphic in self.graphics:
            self.remove_graphic(drawn_graphic)
        else:  # a synthesized graphic
            drawn_graphic.notify_remove_region_graphic()

    # this message comes from the graphic. the connection is established when a graphic
    # is added or removed from this object.
    def graphic_changed(self, graphic):
        self.notify_listeners("display_changed", self)

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        if not self._is_reading:
            super(Display, self).notify_set_property(key, value)
            for processor in self.__processors.values():
                processor.item_property_changed(key, value)

    # called from processors
    def notify_processor_needs_recompute(self, processor):
        self.notify_listeners("display_processor_needs_recompute", self, processor)

    # called from processors
    def notify_processor_data_updated(self, processor):
        self.notify_listeners("display_processor_data_updated", self, processor)


class HistogramDataItemProcessor(DataItemProcessor.DataItemProcessor):

    def __init__(self, display):
        super(HistogramDataItemProcessor, self).__init__(display, "histogram_data")
        self.bins = 320

    def item_property_changed(self, key, value):
        """ Called directly from data item. """
        super(HistogramDataItemProcessor, self).item_property_changed(key, value)
        if key == "display_limits" or key == "slice_interval":
            self._set_cached_value_dirty()

    def get_calculated_data(self, ui, data):
        if Image.is_data_3d(data):
            data = self.item.preview_2d_data
        display_range = self.item.display_range  # may be None
        histogram_data = numpy.histogram(data, range=display_range, bins=self.bins)[0]
        histogram_max = numpy.max(histogram_data)  # assumes that histogram_data is int
        if histogram_max > 0:
            histogram_data = histogram_data / float(histogram_max)
        return histogram_data

    def get_data_item(self):
        return self.item.data_item


class ThumbnailDataItemProcessor(DataItemProcessor.DataItemProcessor):

    def __init__(self, display):
        super(ThumbnailDataItemProcessor, self).__init__(display, "thumbnail_data")
        self.width = 72
        self.height = 72

    def get_calculated_data(self, ui, data):
        thumbnail_data = None
        if Image.is_data_1d(data):
            thumbnail_data = self.__get_thumbnail_1d_data(ui, data, self.height, self.width)
        elif Image.is_data_2d(data):
            data_range = self.item.data_range
            display_limits = self.item.display_limits
            thumbnail_data = self.__get_thumbnail_2d_data(ui, data, self.height, self.width, data_range, display_limits)
        elif Image.is_data_3d(data):
            data = self.item.preview_2d_data
            data_range = self.item.data_range
            display_limits = self.item.display_limits
            thumbnail_data = self.__get_thumbnail_2d_data(ui, data, self.height, self.width, data_range, display_limits)
        return thumbnail_data

    def get_default_data(self):
        return numpy.zeros((self.height, self.width), dtype=numpy.uint32)

    def get_data_item(self):
        return self.item.data_item

    def __get_thumbnail_1d_data(self, ui, data, height, width):
        assert data is not None
        assert Image.is_data_1d(data)
        data = Image.convert_to_grayscale(data)
        line_graph_canvas_item = LineGraphCanvasItem.LineGraphCanvasItem()
        line_graph_canvas_item.draw_captions = False
        line_graph_canvas_item.draw_grid = False
        line_graph_canvas_item.draw_frame = True
        line_graph_canvas_item.background_color = "#EEEEEE"
        line_graph_canvas_item.graph_background_color = "rgba(0,0,0,0)"
        line_graph_canvas_item.data_info = LineGraphCanvasItem.LineGraphDataInfo(data, data_left=0, data_right=data.shape[0])
        line_graph_canvas_item.update_layout(((height - width / 1.618) * 0.5, 0), (width / 1.618, width))
        drawing_context = ui.create_offscreen_drawing_context()
        drawing_context.save()
        drawing_context.begin_path()
        drawing_context.rect(0, 0, width, height)
        drawing_context.fill_style = "#EEEEEE"
        drawing_context.fill()
        drawing_context.restore()
        drawing_context.translate(0, (height - width / 1.618) * 0.5)
        line_graph_canvas_item._repaint(drawing_context)
        return ui.create_rgba_image(drawing_context, width, height)

    def __get_thumbnail_2d_data(self, ui, image, height, width, data_range, display_limits):
        assert image is not None
        assert image.ndim in (2,3)
        image = Image.scalar_from_array(image)
        image_height = image.shape[0]
        image_width = image.shape[1]
        assert image_height > 0 and image_width > 0
        scaled_height = height if image_height > image_width else height * image_height / image_width
        scaled_width = width if image_width > image_height else width * image_width / image_height
        thumbnail_image = Image.scaled(image, (scaled_height, scaled_width), 'nearest')
        if numpy.ndim(thumbnail_image) == 2:
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


def display_factory(lookup_id):
    return Display()
