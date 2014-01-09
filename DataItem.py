# standard libraries
import collections
import copy
import datetime
import gettext
import logging
import os
import threading
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import CanvasItem
from nion.swift.Decorators import ProcessingThread
from nion.swift import Image
from nion.swift import LineGraphCanvasItem
from nion.swift import Storage
from nion.swift import Utility

_ = gettext.gettext


# Calibration notes:
#   The user wants calibrations to persist during pixel-by-pixel processing
#   The user expects operations to handle calibrations and perhaps other metadata
#   The user expects that calibrating a processed item adjust source calibration

# origin: the calibrated value at the origin
# scale: the calibrated value at location 1.0
# units: the units of the calibrated value
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
        self.__origin = float(origin) if origin else None
        self.__scale = float(scale) if scale else None
        self.__units = unicode(units) if units else None

    @classmethod
    def build(cls, datastore, item_node, uuid_):
        origin = datastore.get_property(item_node, "origin", None)
        scale = datastore.get_property(item_node, "scale", None)
        units = datastore.get_property(item_node, "units", None)
        return cls(origin, scale, units)

    def __str__(self):
        return "{0:s} origin:{1:g} scale:{2:g} units:\'{3:s}\'".format(self.__repr__(), self.origin, self.scale, self.units)

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
        value = float(value) if value else None
        if self.__origin != value:
            self.__origin = value
            self.notify_set_property("origin", value)
    origin = property(__get_origin, __set_origin)

    def __get_scale(self):
        return self.__scale if self.__scale else 1.0
    def __set_scale(self, value):
        value = float(value) if value else None
        if self.__scale != value:
            self.__scale = value
            self.notify_set_property("scale", value)
    scale = property(__get_scale, __set_scale)

    def __get_units(self):
        return self.__units if self.__units else unicode()
    def __set_units(self, value):
        value = unicode(value) if value else None
        if self.units != value:
            self.__units = value
            self.notify_set_property("units", value)
    units = property(__get_units, __set_units)

    def convert_to_calibrated_value(self, value):
        return self.origin + value * self.scale
    def convert_to_calibrated_size(self, size):
        return size * self.scale
    def convert_from_calibrated(self, value):
        return (value - self.origin) / self.scale
    def convert_to_calibrated_value_str(self, value, include_units=True):
        units_str = (" " + self.units) if include_units and self.__units else ""
        result = u"{0:.1f}{1:s}".format(self.convert_to_calibrated_value(value), units_str)
        return result
    def convert_to_calibrated_size_str(self, size, include_units=True):
        units_str = (" " + self.units) if include_units and self.__units else ""
        result = u"{0:.1f}{1:s}".format(self.convert_to_calibrated_size(size), units_str)
        return result

    def notify_set_property(self, key, value):
        super(Calibration, self).notify_set_property(key, value)
        self.notify_listeners("calibration_changed", self)


class CalibratedValueFloatToStringConverter(object):
    """
        Converter object to convert from calibrated value to string and back.
    """
    def __init__(self, data_item, index, data_size):
        self.__data_item = data_item
        self.__index = index
        self.__data_size = data_size
    def convert(self, value):
        calibration = self.__data_item.calculated_calibrations[self.__index]
        return calibration.convert_to_calibrated_value_str(self.__data_size * value)
    def convert_back(self, str):
        calibration = self.__data_item.calculated_calibrations[self.__index]
        return calibration.convert_from_calibrated(float(str)) / self.__data_size


class CalibratedSizeFloatToStringConverter(object):
    """
        Converter object to convert from calibrated size to string and back.
        """
    def __init__(self, data_item, index, data_size):
        self.__data_item = data_item
        self.__index = index
        self.__data_size = data_size
    def convert(self, size):
        calibration = self.__data_item.calculated_calibrations[self.__index]
        return calibration.convert_to_calibrated_size_str(self.__data_size * size)
    def convert_back(self, str):
        calibration = self.__data_item.calculated_calibrations[self.__index]
        return calibration.convert_from_calibrated(float(str)) / self.__data_size


class ThumbnailThread(ProcessingThread):

    def __init__(self):
        super(ThumbnailThread, self).__init__(minimum_interval=0.5)
        self.ui = None
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
        data_item.load_thumbnail_on_thread(self.ui)

    def release_data(self, data_item):
        data_item.remove_ref()


class HistogramThread(ProcessingThread):

    def __init__(self):
        super(HistogramThread, self).__init__(minimum_interval=0.2)
        self.__data_item = None
        self.__mutex = threading.RLock()  # access to the data item
        # mutex is needed to avoid case where grab data is called
        # simultaneously to handle_data and data item would get
        # released twice, once in handle data and once in the final
        # call to release data.
        # don't start until everything is initialized
        self.start()

    def close(self):
        super(HistogramThread, self).close()
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
        data_item.load_histogram_on_thread()

    def release_data(self, data_item):
        data_item.remove_ref()


# data items will represents a numpy array. the numpy array
# may be stored directly in this item (master data), or come
# from another data item (data source).

# thumbnail: a small representation of this data item

# graphic items: roi's

# intrinsic_calibrations: calibration for each dimension
# display_calibrated_values: whether calibrated units are displayed

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


# enumerations for types of changes
DATA = 1
DISPLAY = 2
CHILDREN = 3
PANEL = 4
THUMBNAIL = 5
HISTOGRAM = 6
SOURCE = 7


# dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# time zone name is for display only and has no specified format

class DataItem(Storage.StorageBase):

    def __init__(self, data=None):
        super(DataItem, self).__init__()
        self.storage_properties += ["title", "param", "display_limits", "datetime_modified", "datetime_original", "display_calibrated_values", "properties"]
        self.storage_items += ["intrinsic_intensity_calibration"]
        self.storage_relationships += ["intrinsic_calibrations", "graphics", "operations", "data_items"]
        self.storage_data_keys += ["master_data"]
        self.storage_type = "data-item"
        self.register_dependent_key("master_data", "data_range")
        self.register_dependent_key("data_range", "display_range")
        self.register_dependent_key("display_limits", "display_range")
        self.register_key_alias("intrinsic_calibrations", "calibrations")
        self.description = []
        self.closed = False
        self.__title = None
        self.__param = 0.5
        self.__display_limits = None  # auto
        # data is immutable but metadata isn't, keep track of original and modified dates
        self.__datetime_original = Utility.get_current_datetime_element()
        self.__datetime_modified = self.__datetime_original
        self.intrinsic_calibrations = Storage.MutableRelationship(self, "intrinsic_calibrations")
        self.__display_calibrated_values = True
        self.__intrinsic_intensity_calibration = None
        self.graphics = Storage.MutableRelationship(self, "graphics")
        self.data_items = Storage.MutableRelationship(self, "data_items")
        self.operations = Storage.MutableRelationship(self, "operations")
        self.__properties = dict()
        self.__data_mutex = threading.RLock()
        self.__cached_data = None
        self.__cached_data_dirty = True
        # master data shape and dtype are always valid if there is no data source.
        self.__master_data = None
        self.__master_data_shape = None
        self.__master_data_dtype = None
        self.__has_master_data = False
        self.__data_source = None
        self.__data_ref_count = 0
        self.__data_ref_count_mutex = threading.RLock()
        self.__data_item_change_mutex = threading.RLock()
        self.__data_item_change_count = 0
        self.__data_item_changes = set()
        self.__preview = None
        self.__counted_data_items = collections.Counter()
        self.__thumbnail_thread = ThumbnailThread()
        self.__histogram_thread = HistogramThread()
        self.__set_master_data(data)

    def __str__(self):
        return self.title if self.title else _("Untitled")

    @classmethod
    def _get_data_file_path(cls, uuid_, datetime_element, session_id=None):
        # uuid_.bytes.encode('base64').rstrip('=\n').replace('/', '_')
        # and back: uuid_ = uuid.UUID(bytes=(slug + '==').replace('_', '/').decode('base64'))
        # also:
        def encode(uuid_, alphabet):
            result = str()
            uuid_int = uuid_.int
            while uuid_int:
                uuid_int, digit = divmod(uuid_int, len(alphabet))
                result += alphabet[digit]
            return result
        encoded_uuid_str = encode(uuid_, "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")  # 25 character results
        datetime_element = datetime_element if datetime_element else Utility.get_current_datetime_element()
        datetime_ = Utility.get_datetime_from_datetime_element(datetime_element)
        datetime_ = datetime_ if datetime_ else datetime.datetime.now()
        path_components = datetime_.strftime("%Y-%m-%d").split('-')
        session_id = session_id if session_id else datetime_.strftime("%Y%m%d-000000")
        path_components.append(session_id)
        path_components.append("master_data_" + encoded_uuid_str + ".nsdata")
        return os.path.join(*path_components)

    @classmethod
    def build(cls, datastore, item_node, uuid_):
        title = datastore.get_property(item_node, "title")
        param = datastore.get_property(item_node, "param")
        properties = datastore.get_property(item_node, "properties")
        display_limits = datastore.get_property(item_node, "display_limits")
        intrinsic_calibrations = datastore.get_items(item_node, "calibrations")  # uses old key until migrated
        intrinsic_intensity_calibration = datastore.get_item(item_node, "intrinsic_intensity_calibration")
        display_calibrated_values = datastore.get_property(item_node, "display_calibrated_values")
        datetime_modified = datastore.get_property(item_node, "datetime_modified")
        datetime_original = datastore.get_property(item_node, "datetime_original")
        graphics = datastore.get_items(item_node, "graphics")
        operations = datastore.get_items(item_node, "operations")
        data_items = datastore.get_items(item_node, "data_items")
        has_master_data = datastore.has_data(item_node, "master_data")
        if has_master_data:
            master_data_shape, master_data_dtype = datastore.get_data_shape_and_dtype(item_node, "master_data")
        else:
            master_data_shape, master_data_dtype = None, None
        data_item = cls()
        data_item.title = title
        data_item.param = param
        data_item.__properties = properties if properties else dict()
        data_item.__master_data_shape = master_data_shape
        data_item.__master_data_dtype = master_data_dtype
        data_item.__has_master_data = has_master_data
        data_item.data_items.extend(data_items)
        data_item.operations.extend(operations)
        # setting master data may add intrinsic_calibrations automatically. remove them here to start from clean slate.
        while len(data_item.intrinsic_calibrations):
            data_item.intrinsic_calibrations.pop()
        data_item.intrinsic_calibrations.extend(intrinsic_calibrations)
        # if we have master data, we should have intensity calibration
        if has_master_data and intrinsic_intensity_calibration is None:
            intrinsic_intensity_calibration = Calibration()
        data_item.intrinsic_intensity_calibration = intrinsic_intensity_calibration
        if display_calibrated_values is not None:
            data_item.display_calibrated_values = display_calibrated_values
        if display_limits is not None:
            data_item.display_limits = display_limits
        if datetime_modified is not None:
            data_item.datetime_modified = datetime_modified
        if datetime_original is not None:
            data_item.datetime_original = datetime_original
        data_item.graphics.extend(graphics)
        return data_item

    # This gets called when reference count goes to 0, but before deletion.
    def about_to_delete(self):
        if self.__thumbnail_thread:
            self.__thumbnail_thread.close()
            self.__thumbnail_thread = None
        if self.__histogram_thread:
            self.__histogram_thread.close()
            self.__histogram_thread = None
        self.closed = True
        self.data_source = None
        self.__set_master_data(None)
        for data_item in copy.copy(self.data_items):
            self.data_items.remove(data_item)
        for calibration in copy.copy(self.intrinsic_calibrations):
            self.intrinsic_calibrations.remove(calibration)
        self.intrinsic_intensity_calibration = None
        for graphic in copy.copy(self.graphics):
            self.graphics.remove(graphic)
        for operation in copy.copy(self.operations):
            self.operations.remove(operation)
        super(DataItem, self).about_to_delete()

    # cheap, but incorrect, way to tell whether this is live acquisition
    def __get_is_live(self):
        return self.transaction_count > 0
    is_live = property(__get_is_live)

    def __get_live_status_as_string(self):
        if self.is_live:
            return "{0:s} {1:s}".format(_("Live"), str(self.__properties.get("frame_index", str())))
        return str()
    live_status_as_string = property(__get_live_status_as_string)

    def __get_session_id(self):
        # first check to see if we have a session_id set directly
        session_id = self.__properties.get("session_id", str())
        # if not, try the data source
        if not session_id and self.data_source:
            session_id = self.data_source.session_id
        # if not, try the datetime
        if not session_id:
            datetime_element = self.datetime_original if self.datetime_original else Utility.get_current_datetime_element()
            datetime_ = Utility.get_datetime_from_datetime_element(datetime_element)
            datetime_ = datetime_ if datetime_ else datetime.datetime.now()
            session_id = datetime_.strftime("%Y%m%d-000000")
        return session_id
    # used for testing only (for now)
    def _set_session_id(self, session_id):
        # verify its in suitable form
        assert datetime.datetime.strptime(session_id, "%Y%m%d-%H%M%S")
        # set it into properties
        with self.property_changes() as property_accessor:
            property_accessor.properties["session_id"] = session_id
    session_id = property(__get_session_id)

    def data_item_changes(self):
        class DataItemChangeContextManager(object):
            def __init__(self, data_item):
                self.__data_item = data_item
            def __enter__(self):
                self.__data_item.begin_data_item_changes()
                return self
            def __exit__(self, type, value, traceback):
                self.__data_item.end_data_item_changes()
        return DataItemChangeContextManager(self)

    def begin_data_item_changes(self):
        with self.__data_item_change_mutex:
            self.__data_item_change_count += 1

    def end_data_item_changes(self):
        with self.__data_item_change_mutex:
            self.__data_item_change_count -= 1
            data_item_change_count = self.__data_item_change_count
            if data_item_change_count == 0:
                changes = self.__data_item_changes
                self.__data_item_changes = set()
        if data_item_change_count == 0:
            # clear the preview and thumbnail
            if not THUMBNAIL in changes and not HISTOGRAM in changes:
                self.set_cached_value_dirty("thumbnail_data")
                self.set_cached_value_dirty("histogram_data")
            self.__preview = None
            # but only clear the data cache if the data changed
            if not DISPLAY in changes:
                self.__clear_cached_data()
            self.notify_listeners("data_item_content_changed", self, changes)

    # call this when the listeners need to be updated (via data_item_content_changed).
    # Calling this method will send the data_item_content_changed method to each listener.
    def notify_data_item_content_changed(self, changes):
        with self.data_item_changes():
            with self.__data_item_change_mutex:
                self.__data_item_changes.update(changes)

    def __get_display_limits(self):
        return self.__display_limits
    def __set_display_limits(self, display_limits):
        if self.__display_limits != display_limits:
            self.__display_limits = display_limits
            self.set_cached_value_dirty("histogram_data")
            self.notify_set_property("display_limits", display_limits)
            self.notify_data_item_content_changed(set([DISPLAY]))
    display_limits = property(__get_display_limits, __set_display_limits)

    def __get_data_range_for_data(self, data):
        if data is not None:
            if self.is_data_rgb_type:
                data_range = (0, 255)
            elif self.is_data_complex_type:
                scalar_data = Image.scalar_from_array(data)
                data_range = (scalar_data.min(), scalar_data.max())
            else:
                data_range = (data.min(), data.max())
        else:
            data_range = None
        if data_range:
            self.set_cached_value("data_range", data_range)
        else:
            self.remove_cached_value("data_range")

    def __get_data_range(self):
        with self.__data_mutex:
            data_range = self.get_cached_value("data_range")
        if not data_range or self.is_cached_value_dirty("data_range"):
            with self.data_ref() as data_ref:
                data = data_ref.data
                self.__get_data_range_for_data(data)
        return data_range
    data_range = property(__get_data_range)

    def __get_display_range(self):
        data_range = self.__get_data_range()
        return self.__display_limits if self.__display_limits else data_range
    # TODO: this is only valid after data has been called (!)
    display_range = property(__get_display_range)

    # calibration stuff

    def __is_calibrated(self):
        return len(self.intrinsic_calibrations) == len(self.spatial_shape)
    is_calibrated = property(__is_calibrated)

    def __get_display_calibrated_values(self):
        return self.__display_calibrated_values
    def __set_display_calibrated_values(self, display_calibrated_values):
        if self.__display_calibrated_values != display_calibrated_values:
            self.__display_calibrated_values = display_calibrated_values
            self.notify_set_property("display_calibrated_values", display_calibrated_values)
            self.notify_data_item_content_changed(set([DISPLAY]))
    display_calibrated_values = property(__get_display_calibrated_values, __set_display_calibrated_values)

    def set_calibration(dimension, calibration):
        self.intrinsic_calibrations[dimension].origin = calibration.origin
        self.intrinsic_calibrations[dimension].scale = calibration.scale
        self.intrinsic_calibrations[dimension].units = calibration.units

    def __get_intrinsic_intensity_calibration(self):
        return self.__intrinsic_intensity_calibration
    def __set_intrinsic_intensity_calibration(self, intrinsic_intensity_calibration):
        if self.__intrinsic_intensity_calibration:
            self.notify_clear_item("intrinsic_intensity_calibration")
            self.__intrinsic_intensity_calibration.remove_listener(self)
            self.__intrinsic_intensity_calibration.remove_ref()
        self.__intrinsic_intensity_calibration = intrinsic_intensity_calibration
        if self.__intrinsic_intensity_calibration:
            # watch for calibration_changed messages
            self.__intrinsic_intensity_calibration.add_listener(self)
            self.__intrinsic_intensity_calibration.add_ref()
            self.notify_set_item("intrinsic_intensity_calibration", intrinsic_intensity_calibration)
    intrinsic_intensity_calibration = property(__get_intrinsic_intensity_calibration, __set_intrinsic_intensity_calibration)

    def __get_calculated_intensity_calibration(self):
        intensity_calibration = None
        # if intrinsic_calibrations are set on this item, use it, giving it precedence
        if self.intrinsic_intensity_calibration:
            if self.display_calibrated_values:
                # use actual intrinsic_calibrations
                intensity_calibration = self.intrinsic_intensity_calibration
            else:
                # construct empty calibration to display unitless
                intensity_calibration = Calibration()
        # if intrinsic_calibrations are not set, then try to get calibrations from the data source
        if intensity_calibration is None and self.data_source:
            intensity_calibration = self.data_source.calculated_intensity_calibration
        data_shape, data_dtype = self.__get_root_data_shape_and_dtype()
        if data_shape is not None and data_dtype is not None:
            for operation in self.operations:
                if operation.enabled:
                    intensity_calibration = operation.get_processed_intensity_calibration(data_shape, data_dtype, intensity_calibration)
                    data_shape, data_dtype = operation.get_processed_data_shape_and_dtype(data_shape, data_dtype)
        return intensity_calibration
    calculated_intensity_calibration = property(__get_calculated_intensity_calibration)

    # call this when data changes. this makes sure that the right number
    # of intrinsic_calibrations exist in this object.
    def sync_intrinsic_calibrations(self, ndim):
        while len(self.intrinsic_calibrations) < ndim:
            self.intrinsic_calibrations.append(Calibration())
        while len(self.intrinsic_calibrations) > ndim:
            self.intrinsic_calibrations.remove(self.intrinsic_calibrations[ndim])
        if self.has_master_data and self.intrinsic_intensity_calibration is None:
            self.intrinsic_intensity_calibration = Calibration()
        if not self.has_master_data and self.intrinsic_intensity_calibration is not None:
            self.intrinsic_intensity_calibration = None

    # calculate the calibrations by starting with the source calibration
    # and then applying calibration transformations for each enabled
    # operation.
    def __get_calculated_calibrations(self):
        calibrations = None
        # if intrinsic_calibrations are set on this item, use it, giving it precedence
        if self.intrinsic_calibrations:
            if self.display_calibrated_values:
                # use actual intrinsic_calibrations
                calibrations = self.intrinsic_calibrations
            else:
                # construct empty calibrations to display pixels
                calibrations = list()
                for _ in xrange(0, len(self.spatial_shape)):
                    calibrations.append(Calibration())
        # if intrinsic_calibrations are not set, then try to get calibrations from the data source
        if calibrations is None and self.data_source:
            calibrations = self.data_source.calculated_calibrations
        data_shape, data_dtype = self.__get_root_data_shape_and_dtype()
        if data_shape is not None and data_dtype is not None:
            for operation in self.operations:
                if operation.enabled:
                    calibrations = operation.get_processed_calibrations(data_shape, data_dtype, calibrations)
                    data_shape, data_dtype = operation.get_processed_data_shape_and_dtype(data_shape, data_dtype)
        return calibrations
    calculated_calibrations = property(__get_calculated_calibrations)

    # date times

    def __get_datetime_modified(self):
        return self.__datetime_modified
    def __set_datetime_modified(self, datetime_modified):
        if self.__datetime_modified != datetime_modified:
            self.__datetime_modified = datetime_modified
            self.notify_set_property("datetime_modified", datetime_modified)
            self.notify_data_item_content_changed(set([DISPLAY]))
    datetime_modified = property(__get_datetime_modified, __set_datetime_modified)

    def __get_datetime_original(self):
        return self.__datetime_original
    def __set_datetime_original(self, datetime_original):
        if self.__datetime_original != datetime_original:
            self.__datetime_original = datetime_original
            self.notify_set_property("datetime_original", datetime_original)
            self.notify_data_item_content_changed(set([DISPLAY]))
    datetime_original = property(__get_datetime_original, __set_datetime_original)

    def __get_datetime_original_as_string(self):
        datetime_original = self.datetime_original
        if datetime_original:
            datetime_ = Utility.get_datetime_from_datetime_element(datetime_original)
            if datetime_:
                return datetime_.strftime("%c")
        # fall through to here
        return str()
    datetime_original_as_string = property(__get_datetime_original_as_string)

    # access properties

    def __get_properties(self):
        return self.__properties.copy()
    properties = property(__get_properties)

    def __grab_properties(self):
        return self.__properties
    def __release_properties(self):
        self.notify_set_property("properties", self.__properties)
        self.notify_data_item_content_changed(set([DISPLAY]))

    def property_changes(self):
        grab_properties = DataItem.__grab_properties
        release_properties = DataItem.__release_properties
        class PropertyChangeContextManager(object):
            def __init__(self, data_item):
                self.__data_item = data_item
            def __enter__(self):
                return self
            def __exit__(self, type, value, traceback):
                release_properties(self.__data_item)
            def __get_properties(self):
                return grab_properties(self.__data_item)
            properties = property(__get_properties)
        return PropertyChangeContextManager(self)

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
            self.notify_data_item_content_changed(set([DATA]))
        elif key == "data_items":
            self.notify_listeners("data_item_inserted", self, value, before_index, False)  # see note about smart groups
            value.data_source = self
            self.notify_data_item_content_changed(set([CHILDREN]))
            self.update_counted_data_items(value.counted_data_items + collections.Counter([value]))
        elif key == "intrinsic_calibrations":
            value.add_listener(self)
            self.notify_data_item_content_changed(set([DISPLAY]))
        elif key == "graphics":
            value.add_listener(self)
            self.notify_data_item_content_changed(set([DISPLAY]))

    def notify_remove_item(self, key, value, index):
        super(DataItem, self).notify_remove_item(key, value, index)
        if key == "operations":
            value.remove_listener(self)
            self.sync_operations()
            self.notify_data_item_content_changed(set([DATA]))
        elif key == "data_items":
            self.subtract_counted_data_items(value.counted_data_items + collections.Counter([value]))
            self.notify_listeners("data_item_removed", self, value, index, False)  # see note about smart groups
            value.data_source = None
            self.notify_data_item_content_changed(set([CHILDREN]))
        elif key == "intrinsic_calibrations":
            value.remove_listener(self)
            self.notify_data_item_content_changed(set([DISPLAY]))
        elif key == "graphics":
            value.remove_listener(self)
            self.notify_data_item_content_changed(set([DISPLAY]))

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
        if self.__param != value:
            self.__param = value
            self.notify_set_property("param", self.__param)
    param = property(__get_param, __set_param)

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(DataItem, self).notify_set_property(key, value)
        self.notify_data_item_content_changed(set([DISPLAY]))

    # this message comes from the graphic. the connection is established when a graphic
    # is added or removed from this object.
    def graphic_changed(self, graphic):
        self.notify_data_item_content_changed(set([DISPLAY]))

    # this message comes from the calibration. the connection is established when a calibration
    # is added or removed from this object.
    def calibration_changed(self, calibration):
        self.notify_data_item_content_changed(set([DISPLAY]))

    # this message comes from the operation. the connection is managed
    # by watching for changes to the operations relationship. when an operation
    # is added/removed, this object becomes a listener via add_listener/remove_listener.
    def operation_changed(self, operation):
        self.__clear_cached_data()
        self.notify_data_item_content_changed(set([DATA]))

    # data_item_content_changed comes from data sources to indicate that data
    # has changed. the connection is established in __set_data_source.
    def data_item_content_changed(self, data_source, changes):
        assert data_source == self.data_source
        # we don't care about display changes to the data source; only data changes.
        if DATA in changes:
            self.__clear_cached_data()
            # propogate to listeners
            self.notify_data_item_content_changed(changes)

    # use a property here to correct add_ref/remove_ref
    # also manage connection to data source.
    # data_source is a caching value only. it is not part of the model.
    def __get_data_source(self):
        return self.__data_source
    def __set_data_source(self, data_source):
        assert data_source is None or not self.has_master_data  # can't have master data and data source
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
                # we will receive data_item_content_changed from data_source
                self.__data_source.add_listener(self)
                self.__data_source.add_ref()
                self.sync_operations()
            self.data_item_content_changed(self.__data_source, set([SOURCE]))
    data_source = property(__get_data_source, __set_data_source)

    def __get_master_data(self):
        return self.__master_data
    def __set_master_data(self, data):
        with self.data_item_changes():
            assert not self.closed or data is None
            assert (data.shape is not None) if data is not None else True  # cheap way to ensure data is an ndarray
            assert data is None or self.__data_source is None  # can't have master data and data source
            with self.__data_mutex:
                if data is not None:
                    self.set_cached_value("master_data_shape", data.shape)
                    self.set_cached_value("master_data_dtype", data.dtype)
                else:
                    self.remove_cached_value("master_data_shape")
                    self.remove_cached_value("master_data_dtype")
                self.__master_data = data
                self.__master_data_shape = data.shape if data is not None else None
                self.__master_data_dtype = data.dtype if data is not None else None
                self.__has_master_data = data is not None
                spatial_ndim = len(Image.spatial_shape_from_data(data)) if data is not None else 0
                self.sync_intrinsic_calibrations(spatial_ndim)
            data_file_path = DataItem._get_data_file_path(self.uuid, self.datetime_original, session_id=self.session_id)
            data_file_datetime = Utility.get_datetime_from_datetime_element(self.datetime_original)
            self.notify_set_data("master_data", self.__master_data, data_file_path, data_file_datetime)
            self.notify_data_item_content_changed(set([DATA]))
    # hidden accessor for storage subsystem. temporary.
    def _get_master_data(self):
        return self.__get_master_data()
    def _get_master_data_data_file_path(self):
        return DataItem._get_data_file_path(self.uuid, self.datetime_original, self.session_id)
    def _get_master_data_data_file_datetime(self):
        return Utility.get_datetime_from_datetime_element(self.datetime_original)

    def increment_data_ref_count(self):
        with self.__data_ref_count_mutex:
            initial_count = self.__data_ref_count
            self.__data_ref_count += 1
        if initial_count == 0:
            # load data from datastore if not present
            if self.has_master_data and self.datastore and self.__master_data is None:
                #logging.debug("loading %s (%s)", self, self.uuid)
                master_data = self.datastore.get_data(self.datastore.find_parent_node(self), "master_data")
                self.__master_data = master_data
                #import traceback
                #traceback.print_stack()
        return initial_count+1
    def decrement_data_ref_count(self):
        with self.__data_ref_count_mutex:
            self.__data_ref_count -= 1
            final_count = self.__data_ref_count
        if final_count == 0:
            # unload data if it can be reloaded from datastore
            if self.has_master_data and self.datastore:
                self.__master_data = None
                #logging.debug("unloading %s (%s)", self, self.uuid)
        return final_count

    def __get_has_master_data(self):
        return self.__has_master_data
    has_master_data = property(__get_has_master_data)

    def __get_has_data_source(self):
        return self.__data_source is not None
    has_data_source = property(__get_has_data_source)

    # grab a data reference as a context manager. the object
    # returned defines data and master_data properties. reading data
    # should use the data property. writing data (if allowed) should
    # assign to the master_data property.
    def data_ref(self):
        get_master_data = DataItem.__get_master_data
        set_master_data = DataItem.__set_master_data
        get_data = DataItem.__get_data
        class DataAccessor(object):
            def __init__(self, data_item):
                self.__data_item = data_item
            def __enter__(self):
                self.__data_item.increment_data_ref_count()
                return self
            def __exit__(self, type, value, traceback):
                self.__data_item.decrement_data_ref_count()
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
                with self.data_ref() as data_ref:
                    data = data_ref.master_data
            if data is None:
                if self.data_source:
                    with self.data_source.data_ref() as data_ref:
                        data = data_ref.data
            return data

    # get the root data shape and dtype without causing calculation to occur if possible.
    def __get_root_data_shape_and_dtype(self):
        with self.__data_mutex:
            if self.has_master_data:
                return self.__master_data_shape, self.__master_data_dtype
            if self.has_data_source:
                return self.data_source.data_shape_and_dtype
        return None, None

    def __clear_cached_data(self):
        with self.__data_mutex:
            self.__cached_data_dirty = True
            self.set_cached_value_dirty("data_range")
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
                    self.__get_data_range_for_data(data)
                finally:
                    self.__data_mutex.acquire()
                self.__cached_data = data
            return self.__cached_data

    def __get_data_shape_and_dtype(self):
        with self.__data_mutex:
            if self.has_master_data:
                data_shape = self.__master_data_shape
                data_dtype = self.__master_data_dtype
            elif self.has_data_source:
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

    def __get_size_and_data_format_as_string(self):
        spatial_shape = self.spatial_shape
        data_dtype = self.data_dtype
        if spatial_shape is not None and data_dtype is not None:
            spatial_shape_str = " x ".join([str(d) for d in spatial_shape])
            if len(spatial_shape) == 1:
                spatial_shape_str += " x 1"
            dtype_names = {
                numpy.int8: _("Integer (8-bit)"),
                numpy.int16: _("Integer (16-bit)"),
                numpy.int32: _("Integer (32-bit)"),
                numpy.int64: _("Integer (64-bit)"),
                numpy.uint8: _("Unsigned Integer (8-bit)"),
                numpy.uint16: _("Unsigned Integer (16-bit)"),
                numpy.uint32: _("Unsigned Integer (32-bit)"),
                numpy.uint64: _("Unsigned Integer (64-bit)"),
                numpy.float32: _("Real (32-bit)"),
                numpy.float64: _("Real (64-bit)"),
                numpy.complex64: _("Complex (2 x 32-bit)"),
                numpy.complex128: _("Complex (2 x 64-bit)"),
            }
            if self.is_data_rgb_type:
                data_size_and_data_format_as_string = _("RGB (8-bit)") if self.is_data_rgb else _("RGBA (8-bit)")
            else:
                if not self.data_dtype.type in dtype_names:
                    logging.debug("Unknown %s", self.data_dtype)
                data_size_and_data_format_as_string = dtype_names[self.data_dtype.type] if self.data_dtype.type in dtype_names else _("Unknown Data Type")
            return "{0}, {1}".format(spatial_shape_str, data_size_and_data_format_as_string)
        return _("No Data")
    size_and_data_format_as_string = property(__get_size_and_data_format_as_string)

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

    def __is_data_rgb(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_rgb(data_shape, data_dtype)
    is_data_rgb = property(__is_data_rgb)

    def __is_data_rgba(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_rgba(data_shape, data_dtype)
    is_data_rgba = property(__is_data_rgba)

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
            if self.is_data_1d:
                if self.__cached_data is not None:
                    return self.__cached_data[pos[0]]
            elif self.is_data_2d:
                if self.__cached_data is not None:
                    return self.__cached_data[pos[0], pos[1]]
        return None

    def __get_preview_2d(self):
        if self.__preview is None:
            with self.data_ref() as data_ref:
                data_2d = data_ref.data
            if Image.is_data_2d(data_2d):
                data_2d = Image.scalar_from_array(data_2d)
                data_range = self.__get_data_range()
                self.__preview = Image.create_rgba_image_from_array(data_2d, data_range=data_range, display_limits=self.display_limits)
        return self.__preview
    preview_2d = property(__get_preview_2d)

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
        line_graph_canvas_item.data = data
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

    # this will be invoked on a thread
    def load_thumbnail_on_thread(self, ui):
        with self.data_ref() as data_ref:
            data = data_ref.data
        if data is not None:  # for data to load and make sure it has data
            #logging.debug("load_thumbnail_on_thread")
            height, width = self.__thumbnail_size
            if Image.is_data_1d(data):
                self.set_cached_value("thumbnail_data", self.__get_thumbnail_1d_data(ui, data, height, width))
            elif Image.is_data_2d(data):
                data_range = self.__get_data_range()
                self.set_cached_value("thumbnail_data", self.__get_thumbnail_2d_data(ui, data, height, width, data_range, self.display_limits))
            else:
                self.remove_cached_value("thumbnail_data")
            self.notify_data_item_content_changed(set([THUMBNAIL]))
        else:
            self.remove_cached_value("thumbnail_data")

    # returns a 2D uint32 array interpreted as RGBA pixels
    def get_thumbnail_data(self, ui, height, width):
        if self.thumbnail_data_dirty:
            if self.__thumbnail_thread and (self.has_master_data or self.has_data_source):
                self.__thumbnail_thread.ui = ui
                self.__thumbnail_size = (height, width)
                self.__thumbnail_thread.update_data(self)
        thumbnail_data = self.get_cached_value("thumbnail_data")
        if thumbnail_data is not None:
            return thumbnail_data
        return numpy.zeros((height, width), dtype=numpy.uint32)

    def __get_thumbnail_data_dirty(self):
        return self.is_cached_value_dirty("thumbnail_data")
    thumbnail_data_dirty = property(__get_thumbnail_data_dirty)

    # this will be invoked on a thread
    def load_histogram_on_thread(self):
        with self.data_ref() as data_ref:
            data = data_ref.data
        if data is not None:  # for data to load and make sure it has data
            display_range = self.display_range  # may be None
            #logging.debug("Calculating histogram %s", self)
            histogram_data = numpy.histogram(data, range=display_range, bins=256)[0]
            histogram_max = float(numpy.max(histogram_data))
            histogram_data = histogram_data / histogram_max
            self.set_cached_value("histogram_data", histogram_data)
            self.notify_data_item_content_changed(set([HISTOGRAM]))
        else:
            self.remove_cached_value("histogram_data")

    def get_histogram_data(self):
        if self.is_cached_value_dirty("histogram_data"):
            if self.__histogram_thread and (self.has_master_data or self.has_data_source):
                self.__histogram_thread.update_data(self)
        histogram_data = self.get_cached_value("histogram_data")
        if histogram_data is not None:
            return histogram_data
        return numpy.zeros((256, ), dtype=numpy.uint32)

    def __deepcopy__(self, memo):
        data_item_copy = DataItem()
        data_item_copy.title = self.title
        data_item_copy.param = self.param
        with data_item_copy.property_changes() as property_accessor:
            property_accessor.properties.clear()
            property_accessor.properties.update(self.properties)
        data_item_copy.display_limits = self.display_limits
        data_item_copy.datetime_modified = copy.copy(self.datetime_modified)
        data_item_copy.datetime_original = copy.copy(self.datetime_original)
        for calibration in self.intrinsic_calibrations:
            data_item_copy.intrinsic_calibrations.append(copy.deepcopy(calibration, memo))
        data_item_copy.intrinsic_intensity_calibration = self.intrinsic_intensity_calibration
        data_item_copy.display_calibrated_values = self.display_calibrated_values
        # graphic must be copied before operation, since operations can
        # depend on graphics.
        for graphic in self.graphics:
            data_item_copy.graphics.append(copy.deepcopy(graphic, memo))
        for operation in self.operations:
            data_item_copy.operations.append(copy.deepcopy(operation, memo))
        for data_item in self.data_items:
            data_item_copy.data_items.append(copy.deepcopy(data_item, memo))
        if self.has_master_data:
            with self.data_ref() as data_ref:
                data_item_copy.__set_master_data(numpy.copy(data_ref.master_data))
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


# TODO: Migrate to use DataItemBindingSource instead.
class DataItemBinding(Storage.Broadcaster):

    """
        Hold a data item and notify listeners when the data item
        changes or the content of the existing data item changes.
    """

    def __init__(self):
        super(DataItemBinding, self).__init__()
        self.__weak_data_item = None

    def close(self):
        self.__weak_data_item = None

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    data_item = property(__get_data_item)

    # this message is received from subclasses (and tests).
    def notify_data_item_binding_data_item_changed(self, data_item):
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
        self.notify_listeners("data_item_binding_data_item_changed", data_item)

    # this message is received from subclasses (and tests).
    def notify_data_item_binding_data_item_content_changed(self, data_item, changes):
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
        self.notify_listeners("data_item_binding_data_item_content_changed", data_item, changes)


class DataItemBindingSource(Storage.Observable):
    """
        Hold a data item and notify observers when changed.
        Also allow access to the properties of the data item
        and allow them to be observed.
    """
    def __init__(self, data_item=None):
        super(DataItemBindingSource, self).__init__()
        self.__data_item = None
        self.__initialized = True
        self.data_item = data_item

    def close(self):
        self.data_item = None
        self.__initialized = False

    def __get_data_item(self):
        return self.__data_item
    def __set_data_item(self, data_item):
        if self.__data_item:
            self.__data_item.remove_observer(self)
        self.__data_item = data_item
        if self.__data_item:
            self.__data_item.add_observer(self)
        self.notify_set_property("data_item", data_item)
    data_item = property(__get_data_item, __set_data_item)

    def __getattr__(self, name):
        return getattr(self.__data_item, name)

    def __setattr__(self, name, value):
        # this test allows attributes to be set in the __init__ method
        if self.__dict__.has_key(name) or not self.__dict__.has_key('_DataItemBindingSource__initialized'):
            super(DataItemBindingSource, self).__setattr__(name, value)
        elif name == "data_item":
            super(DataItemBindingSource, self).__setattr__(name, value)
        else:
            setattr(self.__data_item, name, value)

    def property_changed(self, sender, property, value):
        self.notify_set_property(property, value)

    def item_inserted(self, sender, key, object, before_index):
        self.notify_insert_item(key, object, before_index)

    def item_removed(self, container, key, object, index):
        self.notify_remove_item(key, object, index)
