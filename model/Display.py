"""
    Contains classes related to display of data items.
"""

# standard libraries
import copy
import logging
import gettext
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift.model import DataItemProcessor
from nion.swift.model import Graphics
from nion.swift.model import Image
from nion.swift.model import LineGraphCanvasItem
from nion.swift.model import Storage
from nion.ui import Model
from nion.ui import Observable
from nion.ui import ThreadPool

_ = gettext.gettext


class Display(Observable.Observable, Observable.Broadcaster, Observable.ReferenceCounted, Storage.Cacheable):
    # Displays are associated with exactly one data item.

    def __init__(self):
        super(Display, self).__init__()
        self.__weak_data_item = None
        self.__graphics = list()
        self.__display_calibrated_values = True
        self.__display_limits = None
        self.__y_min = None
        self.__y_max = None
        self.__left_channel = None
        self.__right_channel = None
        self.__drawn_graphics = Model.ListModel(self, "drawn_graphics")
        self.__preview = None
        self.__shared_thread_pool = ThreadPool.create_thread_queue()
        self.__processors = dict()
        self.__processors["thumbnail"] = ThumbnailDataItemProcessor(self)
        self.__processors["histogram"] = HistogramDataItemProcessor(self)
        self.datastore = None

    def about_to_delete(self):
        self.__shared_thread_pool.close()
        for graphic in copy.copy(self.graphics):
            self.remove_graphic(graphic)
        self._set_data_item(None)

    @classmethod
    def build(cls, storage_dict):
        display = cls()
        display.__display_calibrated_values = storage_dict.get("display_calibrated_values", True)
        display.__display_limits = storage_dict.get("display_limits")
        display.__y_min = storage_dict.get("y_min")
        display.__y_max = storage_dict.get("y_max")
        display.__left_channel = storage_dict.get("left_channel")
        display.__right_channel = storage_dict.get("right_channel")
        graphic_list = storage_dict.get("graphics", list())
        for graphic_dict in graphic_list:
            graphic_item = Graphics.build(graphic_dict)
            display.append_graphic(graphic_item)
        return display

    def write(self, storage_dict):
        storage_dict["display_calibrated_values"] = self.display_calibrated_values
        storage_dict["display_limits"] = self.display_limits
        storage_dict["y_min"] = self.y_min
        storage_dict["y_max"] = self.y_max
        storage_dict["left_channel"] = self.left_channel
        storage_dict["right_channel"] = self.right_channel
        graphic_list = storage_dict.setdefault("graphics", list())
        for graphic in self.graphics:
            graphic_dict = dict()
            graphic.write(graphic_dict)
            graphic_list.append(graphic_dict)

    def __deepcopy__(self, memo):
        display_copy = Display()
        display_copy.display_calibrated_values = self.display_calibrated_values
        display_copy.display_limits = self.display_limits
        display_copy.y_min = self.y_min
        display_copy.y_max = self.y_max
        display_copy.left_channel = self.left_channel
        display_copy.right_channel = self.right_channel
        for graphic in self.graphics:
            display_copy.append_graphic(copy.deepcopy(graphic, memo))
        memo[id(self)] = display_copy
        return display_copy

    def add_shared_task(self, task_id, item, fn):
        self.__shared_thread_pool.add_task(task_id, item, fn)

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

    def __get_preview_2d(self):
        if self.__preview is None:
            with self.data_item.data_ref() as data_ref:
                data = data_ref.data
            if Image.is_data_2d(data):
                data_2d = Image.scalar_from_array(data)
            # TODO: fix me 3d
            elif Image.is_data_3d(data):
                data_2d = Image.scalar_from_array(data.reshape(tuple([data.shape[0] * data.shape[1], ] + list(data.shape[2::]))))
            else:
                data_2d = None
            if data_2d is not None:
                data_range = self.data_range
                display_limits = self.display_limits
                self.__preview = Image.create_rgba_image_from_array(data_2d, data_range=data_range, display_limits=display_limits)
        return self.__preview
    preview_2d = property(__get_preview_2d)

    def get_processed_data(self, processor_id, ui, completion_fn):
        return self.get_processor(processor_id).get_data(ui, completion_fn)

    def __get_drawn_graphics(self):
        return self.__drawn_graphics
    drawn_graphics = property(__get_drawn_graphics)

    def __get_display_calibrated_values(self):
        return self.__display_calibrated_values
    def __set_display_calibrated_values(self, display_calibrated_values):
        self.__display_calibrated_values = display_calibrated_values
        if self.datastore:
            with self.datastore:
                self.datastore.storage_dict["display_calibrated_values"] = self.display_calibrated_values
        self.notify_set_property("display_calibrated_values", display_calibrated_values)
        self.notify_listeners("display_changed", self)
        self.__preview = None
    display_calibrated_values = property(__get_display_calibrated_values, __set_display_calibrated_values)

    def __get_display_limits(self):
        return self.__display_limits
    def __set_display_limits(self, display_limits):
        # setting display limits to max,min will silently reverse them to min,max
        # this is a HACK to make sure the cache gets cleared before we ask to calculate it
        # this is temporary until I clean up the message passing a bit more.
        if display_limits is not None:
            display_limits = min(display_limits[0], display_limits[1]), max(display_limits[0], display_limits[1])
        for processor in self.__processors.values():
            processor.data_item_changed()
        self.__display_limits = display_limits
        if self.datastore:
            with self.datastore:
                self.datastore.storage_dict["display_limits"] = display_limits
        self.notify_set_property("display_limits", display_limits)
        if self.data_item:
            self.notify_set_property("display_range", self.display_range)
        self.notify_listeners("display_changed", self)
        self.__preview = None
    display_limits = property(__get_display_limits, __set_display_limits)

    def __get_data_range(self):
        return self.data_item.data_range
    data_range = property(__get_data_range)

    def __get_display_range(self):
        data_range = self.data_range
        return self.display_limits if self.display_limits else data_range
    # TODO: this is only valid after data has been called (!)
    # NOTE: setting display_range actually just sets display limits. helpful for inspector bindings.
    display_range = property(__get_display_range, __set_display_limits)

    def __get_y_min(self):
        return self.__y_min
    def __set_y_min(self, y_min):
        self.__y_min = y_min
        if self.datastore:
            with self.datastore:
                self.datastore.storage_dict["y_min"] = y_min
        self.notify_set_property("y_min", y_min)
        self.notify_listeners("display_changed", self)
        self.__preview = None
    y_min = property(__get_y_min, __set_y_min)

    def __get_y_max(self):
        return self.__y_max
    def __set_y_max(self, y_max):
        self.__y_max = y_max
        if self.datastore:
            with self.datastore:
                self.datastore.storage_dict["y_max"] = y_max
        self.notify_set_property("y_max", y_max)
        self.notify_listeners("display_changed", self)
        self.__preview = None
    y_max = property(__get_y_max, __set_y_max)

    def __get_left_channel(self):
        return self.__left_channel
    def __set_left_channel(self, left_channel):
        self.__left_channel = left_channel
        if self.datastore:
            with self.datastore:
                self.datastore.storage_dict["left_channel"] = left_channel
        self.notify_set_property("left_channel", left_channel)
        self.notify_listeners("display_changed", self)
        self.__preview = None
    left_channel = property(__get_left_channel, __set_left_channel)

    def __get_right_channel(self):
        return self.__right_channel
    def __set_right_channel(self, right_channel):
        self.__right_channel = right_channel
        if self.datastore:
            with self.datastore:
                self.datastore.storage_dict["right_channel"] = right_channel
        self.notify_set_property("right_channel", right_channel)
        self.notify_listeners("display_changed", self)
        self.__preview = None
    right_channel = property(__get_right_channel, __set_right_channel)

    # message sent from data_item or graphics. established using add/remove observer.
    def property_changed(self, object, property, value):
        if property == "data_range":
            self.__preview = None
            self.notify_set_property(property, value)
            if self.data_item:
                self.notify_set_property("display_range", self.display_range)
        if object in self.__graphics:
            if self.datastore:
                with self.datastore:
                    graphic_dict = self.datastore.storage_dict["graphics"][self.__graphics.index(object)]
                    graphic_dict[property] = value

    # this message received from data item. the connection is established using
    # add_listener and remove_listener.
    def data_item_content_changed(self, data_item, changes):
        DATA = 1
        METADATA = 2
        SOURCE = 5
        if DATA in changes or METADATA in changes or SOURCE in changes:
            self.__preview = None
            self.notify_listeners("display_changed", self)
            # clear the processor caches
            for processor in self.__processors.values():
                processor.data_item_changed()

    def add_operation_graphics(self, operation_graphics):
        for operation_graphic in operation_graphics:
            operation_graphic.add_listener(self)
            self.__drawn_graphics.append(operation_graphic)

    def remove_operation_graphics(self, operation_graphics):
        for operation_graphic in operation_graphics:
            operation_graphic.remove_listener(self)
            self.__drawn_graphics.remove(operation_graphic)

    def __get_graphics(self):
        """ A copy of the graphics """
        return copy.copy(self.__graphics)
    graphics = property(__get_graphics)

    def insert_graphic(self, before_index, graphic):
        """ Insert a graphic before the index """
        self.__graphics.insert(before_index, graphic)
        graphic.add_ref()
        graphic.add_listener(self)
        graphic.add_observer(self)
        if self.datastore:
            with self.datastore:
                graphic_list = self.datastore.storage_dict.setdefault("graphics", list())
                graphic_dict = dict()
                graphic.write(graphic_dict)
                graphic_list.append(graphic_dict)
        self.__drawn_graphics.insert(before_index, graphic)
        self.notify_listeners("display_changed", self)

    def append_graphic(self, graphic):
        """ Append a graphic """
        self.insert_graphic(len(self.__graphics), graphic)

    def remove_graphic(self, graphic):
        """ Remove a graphic """
        graphic_index = self.__graphics.index(graphic)
        self.__graphics.remove(graphic)
        self.__drawn_graphics.remove(graphic)
        self.notify_listeners("display_changed", self)
        graphic.remove_listener(self)
        graphic.remove_observer(self)
        graphic.remove_ref()
        if self.datastore:
            with self.datastore:
                graphic_list = self.datastore.storage_dict["graphics"]
                del graphic_list[graphic_index]

    def extend_graphics(self, graphics):
        """ Extend the graphics array with the list of graphics """
        for graphic in graphics:
            self.append_graphic(graphic)

    # drawn graphics and the regular graphic items, plus those derived from the operation classes
    def __get_drawn_graphics(self):
        """ List of drawn graphics """
        return self.__drawn_graphics
    drawn_graphics = property(__get_drawn_graphics)

    def remove_drawn_graphic(self, drawn_graphic):
        """ Remove a drawn graphic which might be intrinsic or a graphic associated with an operation on a child """
        if drawn_graphic in self.__graphics:
            self.remove_graphic(drawn_graphic)
        else:  # a synthesized graphic
            drawn_graphic.notify_remove_operation_graphic()

    # this message comes from the graphic. the connection is established when a graphic
    # is added or removed from this object.
    def graphic_changed(self, graphic):
        self.notify_listeners("display_changed", self)

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(Display, self).notify_set_property(key, value)
        for processor in self.__processors.values():
            processor.item_property_changed(key, value)


class HistogramDataItemProcessor(DataItemProcessor.DataItemProcessor):

    def __init__(self, display):
        super(HistogramDataItemProcessor, self).__init__(display, "histogram_data")
        self.bins = 256

    def item_property_changed(self, key, value):
        """ Called directly from data item. """
        super(HistogramDataItemProcessor, self).item_property_changed(key, value)
        if key == "display_limits":
            self.set_cached_value_dirty()

    def get_calculated_data(self, ui, data):
        display_range = self.item.display_range  # may be None
        histogram_data = numpy.histogram(data, range=display_range, bins=self.bins)[0]
        histogram_max = float(numpy.max(histogram_data))
        histogram_data = histogram_data / histogram_max
        return histogram_data

    def get_default_data(self):
        return numpy.zeros((self.bins, ), dtype=numpy.uint32)

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
            # TODO: fix me 3d
            data_range = self.item.data_range
            display_limits = self.item.display_limits
            thumbnail_data = self.__get_thumbnail_3d_data(ui, data, self.height, self.width, data_range, display_limits)
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
        line_graph_canvas_item.draw_frame = False
        line_graph_canvas_item.background_color = "#EEEEEE"
        line_graph_canvas_item.graph_background_color = "rgba(0,0,0,0)"
        line_graph_canvas_item.data_info = LineGraphCanvasItem.LineGraphDataInfo(data)
        line_graph_canvas_item.update_layout((0, 0), (height, width))
        drawing_context = ui.create_offscreen_drawing_context()
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

    # TODO: fix me 3d
    def __get_thumbnail_3d_data(self, ui, image, height, width, data_range, display_limits):
        assert image is not None
        assert image.ndim in (3,4)
        new_shape = tuple([image.shape[0] * image.shape[1], ] + list(image.shape[2::]))
        image = Image.scalar_from_array(image.reshape(new_shape))
        image_height = image.shape[0]
        image_width = image.shape[1]
        assert image_height > 0 and image_width > 0
        scaled_height = max(height if image_height > image_width else height * image_height / image_width, 1)
        scaled_width = max(width if image_width > image_height else width * image_width / image_height, 1)
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
