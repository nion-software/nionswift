# standard libraries
import collections
import copy
import gettext
import logging
import threading
import uuid
import weakref

# third party libraries
import numpy
import scipy.interpolate

# local libraries
from nion.swift.Decorators import ProcessingThread
from nion.swift import Image
from nion.swift import Storage

_ = gettext.gettext


# Calibration notes:
#   The user wants calibrations to persist during pixel-by-pixel processing
#   The user expects operations to handle calibrations and perhaps other metadata
#   The user expects that calibrating a processed item adjust source calibration

class Calibration(Storage.StorageBase):
    def __init__(self, origin=None, scale=None, units=None):
        super(Calibration, self).__init__()
        # TODO: add optional saving for these items
        self.storage_properties += ["origin", "scale", "units"]
        self.storage_type = "calibration"
        self.description = [
            {"name": _("Origin"), "property": "origin", "type": "float-field"},
            {"name": _("Scale"), "property": "scale", "type": "float-field"},
            {"name": _("Units"), "property": "units", "type": "string-field"}
        ]
        self.__origin = origin  # the calibrated value at the origin
        self.__scale = scale  # the calibrated value at location 1.0
        self.__units = units  # the units of the calibrated value

    @classmethod
    def build(cls, storage_reader, item_node):
        origin = storage_reader.get_property(item_node, "origin", None)
        scale = storage_reader.get_property(item_node, "scale", None)
        units = storage_reader.get_property(item_node, "units", None)
        return cls(origin, scale, units)

    def __deepcopy__(self, memo):
        calibration = Calibration(origin=self.__origin, scale=self.__scale, units=self.__units)
        memo[id(self)] = calibration
        return calibration

    def __get_is_calibrated(self):
        return self.__origin is not None or self.__scale is not None or self.__units is not None
    is_calibrated = property(__get_is_calibrated)

    def clear(self):
        self.__origin = None
        self.__scale = None
        self.__units = None

    def __get_origin(self):
        return self.__origin if self.__origin else 0.0
    def __set_origin(self, value):
        self.__origin = value
        self.notify_set_property("origin", value)
    origin = property(__get_origin, __set_origin)

    def __get_scale(self):
        return self.__scale if self.__scale else 1.0
    def __set_scale(self, value):
        self.__scale = value
        self.notify_set_property("scale", value)
    scale = property(__get_scale, __set_scale)

    def __get_units(self):
        return self.__units if self.__units else unicode()
    def __set_units(self, value):
        self.__units = value
        self.notify_set_property("units", value)
    units = property(__get_units, __set_units)

    def convert_to_calibrated_value(self, value):
        return self.origin + value * self.scale
    def convert_to_calibrated_size(self, size):
        return size * self.scale
    def convert_from_calibrated(self, value):
        return (value - self.origin) / self.scale
    def convert_to_calibrated_value_str(self, value):
        result = u"{0:.1f}".format(self.convert_to_calibrated_value(value)) + ((" " + self.units) if self.__units else "")
        return result
    def convert_to_calibrated_size_str(self, size):
        result = u"{0:.1f}".format(self.convert_to_calibrated_size(size)) + ((" " + self.units) if self.__units else "")
        return result

    def notify_set_property(self, key, value):
        super(Calibration, self).notify_set_property(key, value)
        self.notify_listeners("calibration_changed", self)


class ThumbnailThread(ProcessingThread):

    def __init__(self):
        super(ThumbnailThread, self).__init__(minimum_interval=0.2)
        self.__data_item = None
        self.__mutex = threading.RLock()  # access to the data item
        # mutex is needed to avoid case where grab data is called
        # simultaneously to handle_data and data item would get
        # released twice, once in handle data and once in the final
        # call to release data.
        # don't start until everything is initialized
        self.start()

    def close(self):
        super(ThumbnailThread, self).close()
        # protect against handle_data being called, but the data
        # was never grabbed. this must go _after_ the super.close
        with self.__mutex:
            if self.__data_item:
                self.__data_item.remove_ref()

    def handle_data(self, data_item):
        with self.__mutex:
            if self.__data_item:
                self.__data_item.remove_ref()
            self.__data_item = data_item
        if data_item:
            data_item.add_ref()

    def grab_data(self):
        with self.__mutex:
            data_item = self.__data_item
            self.__data_item = None
            return data_item

    def process_data(self, data_item):
        data_item.load_thumbnail()

    def release_data(self, data_item):
        data_item.remove_ref()


# data items will represents a numpy array. the numpy array
# may be stored directly in this item (master data), or come
# from another data item (data source).

# thumbnail: a small representation of this data item

# graphic items: roi's

# calibrations: calibration for each dimension

# data: data with all operations applied

# master data: a numpy array associated with this data item
# data source: another data item from which data is taken

# display limits: data limits for display. may be None.

# data range: cached value for data min/max. calculated when data is requested, or on demand.

# display range: display limits if not None, else data range.

# operations: a list of operations applied to make data

# data items: child data items (aka derived data)

# cached data: holds last result of data calculation

# last cached data: holds last valid cached data

# best data: returns the best data available without doing a calculation

# preview_2d: a 2d visual representation of data

# live data: a bool indicating whether the data is live

# data is calculated when requested. this makes it imperative that callers
# do not ask for data to be calculated on the main thread.

# values that are cached will be marked as dirty when they don't match
# the underlying data. however, the values will still return values for
# the out of date data.


class DataItem(Storage.StorageBase):

    def __init__(self, data=None):
        super(DataItem, self).__init__()
        self.storage_properties += ["title", "param", "display_limits", "properties"]
        self.storage_relationships += ["calibrations", "graphics", "operations", "data_items"]
        self.storage_data_keys += ["master_data"]
        self.storage_type = "data-item"
        self.description = [
            {"name": _("Parameter"), "property": "param", "type": "scalar", "default": 0.5},
            {"name": _("Calibrations"), "property": "calibrations", "type": "fixed-array"},
        ]
        self.closed = False
        self.__title = None
        self.__param = 0.5
        self.__display_limits = None  # auto
        self.calibrations = Storage.MutableRelationship(self, "calibrations")
        self.graphics = Storage.MutableRelationship(self, "graphics")
        self.data_items = Storage.MutableRelationship(self, "data_items")
        self.operations = Storage.MutableRelationship(self, "operations")
        self.__properties = dict()
        self.__data_mutex = threading.RLock()
        self.__cached_data = None
        self.__cached_data_dirty = True
        self.__cached_data_range = None
        self.__cached_data_range_dirty = True
        self.__master_data = None
        self.__master_data_shape = None
        self.__master_data_dtype = None
        self.__data_source = None
        self.__data_accessor_count = 0
        self.__data_accessor_count_mutex = threading.RLock()
        self.__preview = None
        self.thumbnail_data = None
        self.thumbnail_data_dirty = True
        self.__live_data = False
        self.__counted_data_items = collections.Counter()
        self.__thumbnail_thread = ThumbnailThread()
        self.__set_master_data(data)

    def __str__(self):
        return self.title if self.title else _("Untitled")

    @classmethod
    def build(cls, storage_reader, item_node):
        title = storage_reader.get_property(item_node, "title")
        param = storage_reader.get_property(item_node, "param")
        properties = storage_reader.get_property(item_node, "properties")
        display_limits = storage_reader.get_property(item_node, "display_limits")
        calibrations = storage_reader.get_items(item_node, "calibrations")
        graphics = storage_reader.get_items(item_node, "graphics")
        operations = storage_reader.get_items(item_node, "operations")
        data_items = storage_reader.get_items(item_node, "data_items")
        master_data = storage_reader.get_data(item_node, "master_data") if storage_reader.has_data(item_node, "master_data") else None
        data_item = cls()
        data_item.title = title
        data_item.param = param
        data_item.set_properties(properties if properties else dict())
        data_item.__set_master_data(master_data)
        data_item.data_items.extend(data_items)
        data_item.operations.extend(operations)
        # setting master data may add calibrations automatically. remove them here to start from clean slate.
        while len(data_item.calibrations):
            data_item.calibrations.pop()
        data_item.calibrations.extend(calibrations)
        if display_limits:
            data_item.display_limits = display_limits
        data_item.graphics.extend(graphics)
        return data_item

    # This gets called when reference count goes to 0, but before deletion.
    def about_to_delete(self):
        self.__thumbnail_thread.close()
        self.__thumbnail_thread = None
        self.closed = True
        self.data_source = None
        self.__set_master_data(None)
        for data_item in copy.copy(self.data_items):
            self.data_items.remove(data_item)
        for calibration in copy.copy(self.calibrations):
            self.calibrations.remove(calibration)
        for graphic in copy.copy(self.graphics):
            self.graphics.remove(graphic)
        for operation in copy.copy(self.operations):
            self.operations.remove(operation)
        super(DataItem, self).about_to_delete()

    def __get_live_data(self):
        return self.__live_data
    def __set_live_data(self, live_data):
        if self.__live_data != live_data:
            self.__live_data = live_data
            if not self.__live_data:
                self.notify_set_data("master_data", self.__master_data)
    live_data = property(__get_live_data, __set_live_data)

    # call this when the listeners need to be updated
    # (via data_item_changed). Calling this method will send the data_item_changed
    # method to each listener.
    def notify_data_item_changed(self, info):
        # clear the preview and thumbnail
        if info["property"] != "thumbnail":
            self.thumbnail_data_dirty = True
        self.__preview = None
        # but only clear the data cache if the data changed
        if info["property"] != "display":
            self.__clear_cached_data()
        self.notify_listeners("data_item_changed", self, info)

    def __get_display_limits(self):
        return self.__display_limits
    def __set_display_limits(self, display_limits):
        if self.__display_limits != display_limits:
            self.__display_limits = display_limits
            self.notify_set_property("display_limits", display_limits)
            self.notify_data_item_changed({"property": "display"})
    display_limits = property(__get_display_limits, __set_display_limits)

    def __get_display_range(self):
        with self.__data_mutex:
            data_range = self.__cached_data_range
        return self.__display_limits if self.__display_limits else data_range
    # TODO: this is only valid after data has been called (!)
    display_range = property(__get_display_range)

    def __is_calibrated(self):
        return len(self.calibrations) == len(self.spatial_shape)
    is_calibrated = property(__is_calibrated)

    # access properties

    def __get_properties(self):
        return self.__properties.copy()
    properties = property(__get_properties)

    def set_properties(self, properties):
        self.__properties = properties

    def grab_properties(self):
        return self.__properties
    def release_properties(self, properties):
        self.__properties = properties
        self.notify_set_property("properties", properties)
        self.notify_data_item_changed({"property": "display"})

    # call this when data changes. this makes sure that the right number
    # of calibrations exist in this object. it also propogates the calibrations
    # to the dependent items.
    def sync_calibrations(self, ndim):
        while len(self.calibrations) < ndim:
            self.calibrations.append(Calibration(0.0, 1.0, None))
        while len(self.calibrations) > ndim:
            self.calibrations.remove(self.calibrations[ndim])

    # calculate the calibrations by starting with the source calibration
    # and then applying calibration transformations for each enabled
    # operation.
    def __get_calculated_calibrations(self):
        # if calibrations are set on this item, use it, giving it precedence
        calibrations = self.calibrations
        # if calibrations are not set, then try to get them from the data source
        if not calibrations and self.data_source:
            calibrations = self.data_source.calculated_calibrations
        data_shape, data_dtype = self.__get_root_data_shape_and_dtype()
        if data_shape is not None and data_dtype is not None:
            for operation in self.operations:
                if operation.enabled:
                    calibrations = operation.get_processed_calibrations(data_shape, data_dtype, calibrations)
                    data_shape, data_dtype = operation.get_processed_data_shape_and_dtype(data_shape, data_dtype)
        return calibrations
    calculated_calibrations = property(__get_calculated_calibrations)

    # call this when operations change or data souce changes
    # this allows operations to update their default values
    def sync_operations(self):
        data_shape, data_dtype = self.__get_root_data_shape_and_dtype()
        if data_shape is not None and data_dtype is not None:
            for operation in self.operations:
                operation.update_data_shape_and_dtype(data_shape, data_dtype)
                if operation.enabled:
                    data_shape, data_dtype = operation.get_processed_data_shape_and_dtype(data_shape, data_dtype)

    # smart groups don't participate in the storage model directly. so allow
    # listeners an alternative way of hearing about data items being inserted
    # or removed via data_item_inserted and data_item_removed messages.

    def notify_insert_item(self, key, value, before_index):
        super(DataItem, self).notify_insert_item(key, value, before_index)
        if key == "operations":
            value.add_listener(self)
            self.sync_operations()
            self.notify_data_item_changed({"property": "data"})
        elif key == "data_items":
            self.notify_listeners("data_item_inserted", self, value, before_index)  # see note about smart groups
            value.data_source = self
            self.notify_data_item_changed({"property": "children"})
            self.update_counted_data_items(value.counted_data_items + collections.Counter([value]))
        elif key == "calibrations":
            value.add_listener(self)
            self.notify_data_item_changed({"property": "display"})
        elif key == "graphics":
            value.add_listener(self)
            self.notify_data_item_changed({"property": "display"})

    def notify_remove_item(self, key, value, index):
        super(DataItem, self).notify_remove_item(key, value, index)
        if key == "operations":
            value.remove_listener(self)
            self.sync_operations()
            self.notify_data_item_changed({"property": "data"})
        elif key == "data_items":
            self.subtract_counted_data_items(value.counted_data_items + collections.Counter([value]))
            self.notify_listeners("data_item_removed", self, value, index)  # see note about smart groups
            value.data_source = None
            self.notify_data_item_changed({"property": "children"})
        elif key == "calibrations":
            value.remove_listener(self)
            self.notify_data_item_changed({"property": "display"})
        elif key == "graphics":
            value.remove_listener(self)
            self.notify_data_item_changed({"property": "display"})

    def __get_counted_data_items(self):
        return self.__counted_data_items
    counted_data_items = property(__get_counted_data_items)

    def update_counted_data_items(self, counted_data_items):
        self.__counted_data_items.update(counted_data_items)
        self.notify_parents("update_counted_data_items", counted_data_items)
    def subtract_counted_data_items(self, counted_data_items):
        self.__counted_data_items.subtract(counted_data_items)
        self.__counted_data_items += collections.Counter()  # strip empty items
        self.notify_parents("subtract_counted_data_items", counted_data_items)

    # title
    def __get_title(self):
        return self.__title
    def __set_title(self, value):
        self.__title = value
        self.notify_set_property("title", value)
    title = property(__get_title, __set_title)

    # param (for testing)
    def __get_param(self):
        return self.__param
    def __set_param(self, value):
        self.__param = value
        self.notify_set_property("param", self.__param)
    param = property(__get_param, __set_param)

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(DataItem, self).notify_set_property(key, value)
        self.notify_data_item_changed({"property": "display"})

    # this message comes from the graphic. the connection is established when a graphic
    # is added or removed from this object.
    def graphic_changed(self, graphic):
        self.notify_data_item_changed({"property": "display"})

    # this message comes from the calibration. the connection is established when a calibration
    # is added or removed from this object.
    def calibration_changed(self, calibration):
        self.notify_data_item_changed({"property": "display"})

    # this message comes from the operation. the connection is managed
    # by watching for changes to the operations relationship. when an operation
    # is added/removed, this object becomes a listener via add_listener/remove_listener.
    def operation_changed(self, operation):
        self.__clear_cached_data()
        self.notify_data_item_changed({"property": "data"})

    # data_item_changed comes from data sources to indicate that data
    # has changed. the connection is established in __set_data_source.
    def data_item_changed(self, data_source, info):
        assert data_source == self.data_source
        # we don't care about display changes to the data source; only data changes.
        if info["property"] == "data":
            self.__clear_cached_data()
            # propogate to listeners
            self.notify_data_item_changed(info)

    # use a property here to correct add_ref/remove_ref
    # also manage connection to data source.
    # data_source is a caching value only. it is not part of the model.
    def __get_data_source(self):
        return self.__data_source
    def __set_data_source(self, data_source):
        assert data_source is None or self.__master_data is None  # can't have master data and data source
        if self.__data_source:
            with self.__data_mutex:
                self.__data_source.remove_listener(self)
                self.__data_source.remove_ref()
                self.__data_source = None
                self.sync_operations()
        if data_source:
            with self.__data_mutex:
                assert isinstance(data_source, DataItem)
                self.__data_source = data_source
                # we will receive data_item_changed from data_source
                self.__data_source.add_listener(self)
                self.__data_source.add_ref()
                self.sync_operations()
            self.data_item_changed(self.__data_source, {"property": "source"})
    data_source = property(__get_data_source, __set_data_source)

    def __get_master_data(self):
        return self.__master_data
    def __set_master_data(self, data):
        assert not self.closed or data is None
        assert (data.shape is not None) if data is not None else True  # cheap way to ensure data is an ndarray
        assert data is None or self.__data_source is None  # can't have master data and data source
        with self.__data_mutex:
            if data is not None:
                self.__master_data_shape = data.shape
                self.__master_data_dtype = data.dtype
            else:
                self.__master_data_shape = None
                self.__master_data_dtype = None
            self.__master_data = data
            spatial_ndim = len(Image.spatial_shape_from_data(data)) if data is not None else 0
            self.sync_calibrations(spatial_ndim)
        if not self.live_data:
            self.notify_set_data("master_data", self.__master_data)
        self.notify_data_item_changed({"property": "data"})
    # hidden accessor for storage subsystem. temporary.
    def _get_master_data(self):
        return self.__get_master_data()

    def increment_accessor_count(self):
        with self.__data_accessor_count_mutex:
            initial_count = self.__data_accessor_count
            self.__data_accessor_count += 1
        if initial_count == 0:
            import traceback
            #logging.debug("loading %s", self)
            #traceback.print_stack()
        return initial_count+1
    def decrement_accessor_count(self):
        with self.__data_accessor_count_mutex:
            self.__data_accessor_count -= 1
            final_count = self.__data_accessor_count
        if final_count == 0:
            pass
            #logging.debug("unloading %s", self)
        return final_count

    def __get_has_master_data(self):
        return self.__master_data is not None
    has_master_data = property(__get_has_master_data)

    def create_data_accessor(self):
        get_master_data = DataItem.__get_master_data
        set_master_data = DataItem.__set_master_data
        get_data = DataItem.__get_data
        class DataAccessor(object):
            def __init__(self, data_item):
                self.__data_item = data_item
            def __enter__(self):
                self.__data_item.increment_accessor_count()
                return self
            def __exit__(self, type, value, traceback):
                self.__data_item.decrement_accessor_count()
            def __get_master_data(self):
                return get_master_data(self.__data_item)
            def __set_master_data(self, data):
                set_master_data(self.__data_item, data)
            master_data = property(__get_master_data, __set_master_data)
            def master_data_updated(self):
                pass
            def __get_data(self):
                return get_data(self.__data_item)
            data = property(__get_data)
        return DataAccessor(self)

    # root data is data before operations have been applied.
    def __get_root_data(self):
        with self.__data_mutex:
            data = None
            if self.has_master_data:
                with self.create_data_accessor() as data_accessor:
                    data = data_accessor.master_data
            if data is None:
                if self.data_source:
                    with self.data_source.create_data_accessor() as data_accessor:
                        data = data_accessor.data
            return data

    # get the root data shape and dtype without causing calculation to occur if possible.
    def __get_root_data_shape_and_dtype(self):
        with self.__data_mutex:
            master_data = None
            if self.has_master_data:
                with self.create_data_accessor() as data_accessor:
                    master_data = data_accessor.master_data
            if master_data is not None:
                return master_data.shape, master_data.dtype
            data_source = self.data_source
            if data_source:
                return data_source.data_shape_and_dtype
        return None, None

    def __clear_cached_data(self):
        with self.__data_mutex:
            self.__cached_data_dirty = True
            self.__cached_data_range_dirty = True
        self.__preview = None

    # data property. read only. this method should almost *never* be called on the main thread since
    # it takes an unpredictable amount of time.
    def __get_data(self):
        if threading.current_thread().getName() == "MainThread":
            #logging.debug("*** WARNING: data called on main thread ***")
            #import traceback
            #traceback.print_stack()
            pass
        with self.__data_mutex:
            if self.__cached_data_dirty or self.__cached_data is None:
                self.__data_mutex.release()
                try:
                    data = self.__get_root_data()
                    operations = self.operations
                    if len(operations) and data is not None:
                        # apply operations
                            if data is not None:
                                for operation in reversed(operations):
                                    data = operation.process_data(data)
                finally:
                    self.__data_mutex.acquire()
                self.__cached_data = data
                if self.is_data_rgb_type:
                    self.__cached_data_range = (0, 255)
                elif self.is_data_complex_type:
                    scalar_data = Image.scalar_from_array(data)
                    self.__cached_data_range = (scalar_data.min(), scalar_data.max())
                elif data is not None:
                    self.__cached_data_range = (data.min(), data.max())
                else:
                    self.__cached_data_range = None
                self.__cached_data_range_dirty = False
            return self.__cached_data

    def __get_data_shape_and_dtype(self):
        with self.__data_mutex:
            if self.has_master_data:
                data_shape = self.__master_data_shape
                data_dtype = self.__master_data_dtype
            elif self.data_source:
                data_shape = self.data_source.data_shape
                data_dtype = self.data_source.data_dtype
            else:
                data_shape = None
                data_dtype = None
            # apply operations
            if data_shape is not None:
                for operation in self.operations:
                    if operation.enabled:
                        data_shape, data_dtype = operation.get_processed_data_shape_and_dtype(data_shape, data_dtype)
            return data_shape, data_dtype
    data_shape_and_dtype = property(__get_data_shape_and_dtype)

    def __get_data_shape(self):
        return self.data_shape_and_dtype[0]
    data_shape = property(__get_data_shape)

    def __get_spatial_shape(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.spatial_shape_from_shape_and_dtype(data_shape, data_dtype)
    spatial_shape = property(__get_spatial_shape)

    def __get_data_dtype(self):
        return self.data_shape_and_dtype[1]
    data_dtype = property(__get_data_dtype)

    def __is_data_1d(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_1d(data_shape, data_dtype)
    is_data_1d = property(__is_data_1d)

    def __is_data_2d(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_2d(data_shape, data_dtype)
    is_data_2d = property(__is_data_2d)

    def __is_data_rgb_type(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_rgb(data_shape, data_dtype) or Image.is_shape_and_dtype_rgba(data_shape, data_dtype)
    is_data_rgb_type = property(__is_data_rgb_type)

    def __is_data_complex_type(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_complex_type(data_shape, data_dtype)
    is_data_complex_type = property(__is_data_complex_type)

    def get_data_value(self, pos):
        # do not force data calculation here
        with self.__data_mutex:
            if self.is_data_2d:
                if self.__cached_data is not None:
                    return self.__cached_data[pos[0], pos[1]]
        return None

    def __get_preview_2d(self):
        if self.__preview is None:
            with self.create_data_accessor() as data_accessor:
                data_2d = data_accessor.data
            if Image.is_data_2d(data_2d):
                data_2d = Image.scalar_from_array(data_2d)
                with self.__data_mutex:
                    data_range = self.__cached_data_range
                self.__preview = Image.create_rgba_image_from_array(data_2d, data_range=data_range, display_limits=self.display_limits)
        return self.__preview
    preview_2d = property(__get_preview_2d)

    def __get_thumbnail_1d_data(self, data, height, width):
        assert data is not None
        assert Image.is_data_1d(data)
        if Image.is_data_rgb(data) or Image.is_data_rgba(data):
            # note 0=b, 1=g, 2=r, 3=a. calculate luminosity.
            data = 0.0722 * data[:,0] + 0.7152 * data[:,1] + 0.2126 * data[:,2]
        else:
            data = Image.scalar_from_array(data)
        rgba = numpy.empty((height, width, 4), numpy.uint8)
        rgba[:] = 64
        data_scaled = Image.scale_multidimensional(data, (width,))
        data_min = numpy.amin(data_scaled)
        data_max = numpy.amax(data_scaled)
        if data_max - data_min != 0.0:
            data_scaled[:] = height * (data_scaled - data_min) / (data_max - data_min)
        else:
            data_scaled[:] = height * 0.5
        rgba[:,:,3] = numpy.fromfunction(lambda y,x: numpy.where(height-1-y<data_scaled,255,0), (height,width))
        return rgba.view(numpy.uint32).reshape(rgba.shape[:-1])

    def __get_thumbnail_2d_data(self, image, height, width, data_range, display_limits):
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

    # this will be invoked on a thread
    def load_thumbnail(self):
        with self.create_data_accessor() as data_accessor:
            data = data_accessor.data
        if data is not None:  # for data to load and make sure it has data
            height, width = self.__thumbnail_size
            if Image.is_data_1d(data):
                self.thumbnail_data = self.__get_thumbnail_1d_data(data, height, width)
            elif Image.is_data_2d(data):
                with self.__data_mutex:
                    data_range = self.__cached_data_range
                self.thumbnail_data = self.__get_thumbnail_2d_data(data, height, width, data_range, self.display_limits)
            else:
                pass
            self.thumbnail_data_dirty = self.thumbnail_data is None
            self.notify_data_item_changed({"property": "thumbnail"})

    # returns a 2D uint32 array interpreted as RGBA pixels
    def get_thumbnail_data(self, height, width):
        if self.thumbnail_data_dirty:
            if self.__thumbnail_thread and self.__master_data is not None or self.__data_source is not None:
                self.__thumbnail_size = (height, width)
                self.__thumbnail_thread.update_data(self)
            if self.thumbnail_data is not None:
                return self.thumbnail_data
            return numpy.zeros((height, width), dtype=numpy.uint32)
        return self.thumbnail_data

    def __deepcopy__(self, memo):
        data_item_copy = DataItem()
        data_item_copy.title = self.title
        data_item_copy.param = self.param
        data_item_copy.display_limits = self.display_limits
        for calibration in self.calibrations:
            data_item_copy.calibrations.append(copy.deepcopy(calibration, memo))
        # graphic must be copied before operation, since operations can
        # depend on graphics.
        for graphic in self.graphics:
            data_item_copy.graphics.append(copy.deepcopy(graphic, memo))
        for operation in self.operations:
            data_item_copy.operations.append(copy.deepcopy(operation, memo))
        for data_item in self.data_items:
            data_item_copy.data_items.append(copy.deepcopy(data_item, memo))
        if self.has_master_data:
            with self.create_data_accessor() as data_accessor:
                data_item_copy.__set_master_data(numpy.copy(data_accessor.master_data))
        else:
            data_item_copy.__set_master_data(None)
        #data_item_copy.data_source = self.data_source  # not needed; handled by insert/remove.
        memo[id(self)] = data_item_copy
        return data_item_copy


# persistently store a data specifier
class DataItemSpecifier(object):
    def __init__(self, data_group=None, data_item=None):
        self.__data_group = data_group
        self.__data_item = data_item
        self.__data_item_container = self.__search_container(data_item, data_group) if data_group and data_item else None
        assert data_item is None or data_item in self.__data_item_container.data_items
    def __is_empty(self):
        return not (self.__data_group and self.__data_item)
    is_empty = property(__is_empty)
    def __get_data_group(self):
        return self.__data_group
    data_group = property(__get_data_group)
    def __get_data_item(self):
        return self.__data_item
    data_item = property(__get_data_item)
    def __search_container(self, data_item, container):
        if hasattr(container, "data_items"):
            if data_item in container.data_items:
                return container
            for child_data_item in container.data_items:
                child_container = self.__search_container(data_item, child_data_item)
                if child_container:
                    return child_container
        if hasattr(container, "data_groups"):
            for data_group in container.data_groups:
                child_container = self.__search_container(data_item, data_group)
                if child_container:
                    return child_container
        return None
    def __get_data_item_container(self):
        return self.__data_item_container
    data_item_container = property(__get_data_item_container)
    def __str__(self):
        return "(%s,%s)" % (str(self.data_group), str(self.data_item))
