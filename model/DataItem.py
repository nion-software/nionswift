# standard libraries
import collections
import copy
import datetime
import gettext
import logging
import os
import threading
import time
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import Image
from nion.swift.model import LineGraphCanvasItem
from nion.swift.model import Storage
from nion.swift.model import Utility
from nion.ui import Binding
from nion.ui import Model
from nion.ui import Observable
from nion.ui import ThreadPool

_ = gettext.gettext


# CalibrationItem notes:
#   The user wants calibrations to persist during pixel-by-pixel processing
#   The user expects operations to handle calibrations and perhaps other metadata
#   The user expects that calibrating a processed item adjust source calibration


# origin: the calibrated value at the origin
# scale: the calibrated value at location 1.0
# units: the units of the calibrated value


class DataItemProcessor(object):

    def __init__(self, data_item, cache_property_name):
        self.__weak_data_item = weakref.ref(data_item)
        self.__cache_property_name = cache_property_name
        self.__mutex = threading.RLock()
        self.__in_progress = False

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    data_item = property(__get_data_item)

    def data_item_changed(self):
        """ Called directly from data item. """
        self.set_cached_value_dirty()

    def data_item_property_changed(self, key, value):
        """
            Subclasses should override and call set_cached_value_dirty to add
            property dependencies. Called directly from data item.
        """
        pass

    def set_cached_value_dirty(self):
        self.data_item.set_cached_value_dirty(self.__cache_property_name)

    def get_calculated_data(self, ui, data):
        """ Subclasses must implement. """
        raise NotImplementedError()

    def get_default_data(self):
        return None

    def get_data(self, ui, completion_fn=None):
        if self.data_item.is_cached_value_dirty(self.__cache_property_name):
            if not self.data_item.closed and (self.data_item.has_master_data or self.data_item.has_data_source):
                def load_data_on_thread():
                    time.sleep(0.2)
                    with self.data_item.data_ref() as data_ref:
                        data = data_ref.data
                        if data is not None:  # for data to load and make sure it has data
                            calculated_data = self.get_calculated_data(ui, data)
                            self.data_item.set_cached_value(self.__cache_property_name, calculated_data)
                        else:
                            calculated_data = None
                    if calculated_data is None:
                        calculated_data = self.get_default_data()
                        self.data_item.remove_cached_value(self.__cache_property_name)
                    if completion_fn:
                        completion_fn(calculated_data)
                    with self.__mutex:
                        self.__in_progress = False
                with self.__mutex:
                    if not self.__in_progress:
                        self.__in_progress = True
                        self.data_item.add_shared_task(self.__cache_property_name, None, lambda: load_data_on_thread())
        calculated_data = self.data_item.get_cached_value(self.__cache_property_name)
        if calculated_data is not None:
            return calculated_data
        return self.get_default_data()


class HistogramDataItemProcessor(DataItemProcessor):

    def __init__(self, data_item):
        super(HistogramDataItemProcessor, self).__init__(data_item, "histogram_data")
        self.bins = 256

    def data_item_property_changed(self, key, value):
        """ Called directly from data item. """
        super(HistogramDataItemProcessor, self).data_item_property_changed(key, value)
        if key == "display_limits":
            self.set_cached_value_dirty()

    def get_calculated_data(self, ui, data):
        #logging.debug("Calculating histogram %s", self)
        display_range = self.data_item.display_range  # may be None
        histogram_data = numpy.histogram(data, range=display_range, bins=self.bins)[0]
        histogram_max = float(numpy.max(histogram_data))
        histogram_data = histogram_data / histogram_max
        return histogram_data

    def get_default_data(self):
        return numpy.zeros((self.bins, ), dtype=numpy.uint32)


class StatisticsDataItemProcessor(DataItemProcessor):

    def __init__(self, data_item):
        super(StatisticsDataItemProcessor, self).__init__(data_item, "statistics_data")

    def get_calculated_data(self, ui, data):
        #logging.debug("Calculating statistics %s", self)
        mean = numpy.mean(data)
        std = numpy.std(data)
        data_min, data_max = self.data_item.data_range
        all_computations = { "mean": mean, "std": std, "min": data_min, "max": data_max }
        global _computation_fns
        for computation_fn in _computation_fns:
            computations = computation_fn(self.data_item)
            if computations is not None:
                all_computations.update(computations)
        return all_computations

    def get_default_data(self):
        return { }


class ThumbnailDataItemProcessor(DataItemProcessor):

    def __init__(self, data_item):
        super(ThumbnailDataItemProcessor, self).__init__(data_item, "thumbnail_data")
        self.width = 72
        self.height = 72

    def get_calculated_data(self, ui, data):
        #logging.debug("Calculating thumbnail %s", self)
        thumbnail_data = None
        if Image.is_data_1d(data):
            thumbnail_data = self.__get_thumbnail_1d_data(ui, data, self.height, self.width)
        elif Image.is_data_2d(data):
            data_range = self.data_item.data_range
            display_limits = self.data_item.display_limits
            thumbnail_data = self.__get_thumbnail_2d_data(ui, data, self.height, self.width, data_range, display_limits)
        elif Image.is_data_3d(data):
            # TODO: fix me 3d
            data_range = self.data_item.data_range
            display_limits = self.data_item.display_limits
            thumbnail_data = self.__get_thumbnail_3d_data(ui, data, self.height, self.width, data_range, display_limits)
        return thumbnail_data

    def get_default_data(self):
        return numpy.zeros((self.height, self.width), dtype=numpy.uint32)

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


# data items will represents a numpy array. the numpy array
# may be stored directly in this item (master data), or come
# from another data item (data source).

# thumbnail: a small representation of this data item

# displays: list of displays for this data item

# intrinsic_calibrations: calibration for each dimension

# data: data with all operations applied

# master data: a numpy array associated with this data item
# data source: another data item from which data is taken

# data range: cached value for data min/max. calculated when data is requested, or on demand.

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
SOURCE = 5


# dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# time zone name is for display only and has no specified format

class DataItem(Storage.StorageBase):

    def __init__(self, data=None):
        super(DataItem, self).__init__()
        self.storage_properties += ["title", "param", "datetime_modified", "datetime_original", "properties", "source_file_path"]
        self.storage_items += ["intrinsic_intensity_calibration"]
        self.storage_relationships += ["intrinsic_calibrations", "operations", "data_items", "displays"]
        self.storage_data_keys += ["master_data"]
        self.storage_type = "data-item"
        self.register_dependent_key("master_data", "data_range")
        self.register_key_alias("intrinsic_calibrations", "calibrations")
        self.closed = False
        self.__title = None
        self.__param = 0.5
        self.__source_file_path = None
        # data is immutable but metadata isn't, keep track of original and modified dates
        self.__datetime_original = Utility.get_current_datetime_item()
        self.__datetime_modified = self.__datetime_original
        self.intrinsic_calibrations = Storage.MutableRelationship(self, "intrinsic_calibrations")
        self.__intrinsic_intensity_calibration = None
        self.data_items = Storage.MutableRelationship(self, "data_items")
        self.operations = Storage.MutableRelationship(self, "operations")
        self.displays = Storage.MutableRelationship(self, "displays")
        self.__properties = dict()
        self.__data_mutex = threading.RLock()
        self.__get_data_mutex = threading.RLock()
        self.__cached_data = None
        self.__cached_data_dirty = True
        # master data shape and dtype are always valid if there is no data source.
        self.__master_data = None
        self.__master_data_shape = None
        self.__master_data_dtype = None
        self.__master_data_reference_type = None  # used for temporary storage
        self.__master_data_reference = None  # used for temporary storage
        self.__master_data_file_datetime = None  # used for temporary storage
        self.master_data_save_event = threading.Event()
        self.__has_master_data = False
        self.__data_source = None
        self.__data_ref_count = 0
        self.__data_ref_count_mutex = threading.RLock()
        self.__data_item_change_mutex = threading.RLock()
        self.__data_item_change_count = 0
        self.__data_item_changes = set()
        self.__preview = None
        self.__counted_data_items = collections.Counter()
        self.__shared_thread_pool = ThreadPool.create_thread_queue()
        self.__processors = dict()
        self.__processors["thumbnail"] = ThumbnailDataItemProcessor(self)
        self.__processors["histogram"] = HistogramDataItemProcessor(self)
        self.__processors["statistics"] = StatisticsDataItemProcessor(self)
        self.__set_master_data(data)

    def __str__(self):
        return "{0} {1} ({2}, {3})".format(self.__repr__(), (self.title if self.title else _("Untitled")), str(self.uuid), self.datetime_original_as_string)

    @classmethod
    def _get_data_file_path(cls, uuid_, datetime_item, session_id=None):
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
        datetime_item = datetime_item if datetime_item else Utility.get_current_datetime_item()
        datetime_ = Utility.get_datetime_from_datetime_item(datetime_item)
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
        source_file_path = datastore.get_property(item_node, "source_file_path")
        properties = datastore.get_property(item_node, "properties")
        intrinsic_calibrations = datastore.get_items(item_node, "calibrations")  # uses old key until migrated
        intrinsic_intensity_calibration = datastore.get_item(item_node, "intrinsic_intensity_calibration")
        datetime_modified = datastore.get_property(item_node, "datetime_modified")
        datetime_original = datastore.get_property(item_node, "datetime_original")
        operations = datastore.get_items(item_node, "operations")
        displays = datastore.get_items(item_node, "displays")
        data_items = datastore.get_items(item_node, "data_items")
        has_master_data = datastore.has_data(item_node, "master_data")
        if has_master_data:
            master_data_shape, master_data_dtype = datastore.get_data_shape_and_dtype(item_node, "master_data")
        else:
            master_data_shape, master_data_dtype = None, None
        data_item = cls()
        data_item.title = title
        data_item.param = param
        data_item.source_file_path = source_file_path
        data_item.__properties = properties if properties else dict()
        data_item.__master_data_shape = master_data_shape
        data_item.__master_data_dtype = master_data_dtype
        data_item.__has_master_data = has_master_data
        data_item.data_items.extend(data_items)
        data_item.operations.extend(operations)
        data_item.displays.extend(displays)
        # setting master data may add intrinsic_calibrations automatically. remove them here to start from clean slate.
        while len(data_item.intrinsic_calibrations):
            data_item.intrinsic_calibrations.pop()
        data_item.intrinsic_calibrations.extend(intrinsic_calibrations)
        # if we have master data, we should have intensity calibration
        if has_master_data and intrinsic_intensity_calibration is None:
            intrinsic_intensity_calibration = Calibration.CalibrationItem()
        data_item.intrinsic_intensity_calibration = intrinsic_intensity_calibration
        if datetime_modified is not None:
            data_item.datetime_modified = datetime_modified
        if datetime_original is not None:
            data_item.datetime_original = datetime_original
        return data_item

    # This gets called when reference count goes to 0, but before deletion.
    def about_to_delete(self):
        self.closed = True
        self.__shared_thread_pool.close()
        self.data_source = None
        self.__set_master_data(None)
        for data_item in copy.copy(self.data_items):
            self.data_items.remove(data_item)
        for calibration in copy.copy(self.intrinsic_calibrations):
            self.intrinsic_calibrations.remove(calibration)
        self.intrinsic_intensity_calibration = None
        for operation in copy.copy(self.operations):
            self.operations.remove(operation)
        for display in copy.copy(self.displays):
            self.displays.remove(display)
        super(DataItem, self).about_to_delete()

    def __deepcopy__(self, memo):
        data_item_copy = DataItem()
        data_item_copy.title = self.title
        data_item_copy.param = self.param
        data_item_copy.source_file_path = self.source_file_path
        with data_item_copy.property_changes() as property_accessor:
            property_accessor.properties.clear()
            property_accessor.properties.update(self.properties)
        data_item_copy.display_limits = self.display_limits
        data_item_copy.datetime_modified = copy.copy(self.datetime_modified)
        data_item_copy.datetime_original = copy.copy(self.datetime_original)
        for calibration in self.intrinsic_calibrations:
            data_item_copy.intrinsic_calibrations.append(copy.deepcopy(calibration, memo))
        data_item_copy.intrinsic_intensity_calibration = self.intrinsic_intensity_calibration
        for operation in self.operations:
            data_item_copy.operations.append(copy.deepcopy(operation, memo))
        for display in self.displays:
            data_item_copy.displays.append(copy.deepcopy(display, memo))
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

    def add_shared_task(self, task_id, item, fn):
        self.__shared_thread_pool.add_task(task_id, item, fn)

    def get_processor(self, processor_id):
        return self.__processors[processor_id]

    def remove_data_item(self, data_item):
        self.data_items.remove(data_item)

    # cheap, but incorrect, way to tell whether this is live acquisition
    def __get_is_live(self):
        return self.transaction_count > 0
    is_live = property(__get_is_live)

    def __get_live_status_as_string(self):
        if self.is_live:
            frame_index_str = str(self.__properties.get("frame_index", str()))
            partial_str = "{0:d}/{1:d}".format(self.__properties.get("valid_rows"), self.spatial_shape[-1]) if "valid_rows" in self.__properties else str()
            return "{0:s} {1:s} {2:s}".format(_("Live"), frame_index_str, partial_str)
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
            datetime_item = self.datetime_original if self.datetime_original else Utility.get_current_datetime_item()
            datetime_ = Utility.get_datetime_from_datetime_item(datetime_item)
            datetime_ = datetime_ if datetime_ else datetime.datetime.now()
            session_id = datetime_.strftime("%Y%m%d-000000")
        return session_id
    def __set_session_id(self, session_id):
        # verify its in suitable form
        assert datetime.datetime.strptime(session_id, "%Y%m%d-%H%M%S")
        # set it into properties
        with self.property_changes() as property_accessor:
            property_accessor.properties["session_id"] = session_id
    session_id = property(__get_session_id, __set_session_id)

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
            # clear the processor caches
            for processor in self.__processors.values():
                processor.data_item_changed()
            # clear the preview if the the display changed
            if DISPLAY in changes:
                self.__preview = None
            # clear the data cache and preview if the data changed
            if DATA in changes or SOURCE in changes:
                self.__clear_cached_data()
                self.__preview = None
            self.notify_listeners("data_item_content_changed", self, changes)

    # call this when the listeners need to be updated (via data_item_content_changed).
    # Calling this method will send the data_item_content_changed method to each listener.
    def notify_data_item_content_changed(self, changes):
        with self.data_item_changes():
            with self.__data_item_change_mutex:
                self.__data_item_changes.update(changes)

    def __get_data_range_for_data(self, data):
        if data is not None:
            if self.is_data_rgb_type:
                data_range = (0, 255)
            elif Image.is_shape_and_dtype_complex_type(data.shape, data.dtype):
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
        return data_range

    def __get_data_range(self):
        with self.__data_mutex:
            data_range = self.get_cached_value("data_range")
        # this property may be access on the main thread (inspector)
        # so it really needs to return quickly in most cases. don't
        # recalculate in the main thread unless the value doesn't exist
        # at all.
        # TODO: use promises here?
        if self.is_cached_value_dirty("data_range"):
            pass  # TODO: calculate data range in thread
        if not data_range:
            with self.data_ref() as data_ref:
                data = data_ref.data
                data_range = self.__get_data_range_for_data(data)
        return data_range
    data_range = property(__get_data_range)

    # calibration stuff

    def __is_calibrated(self):
        return len(self.intrinsic_calibrations) == len(self.spatial_shape)
    is_calibrated = property(__is_calibrated)

    def set_calibration(self, dimension, calibration):
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
        intensity_calibration_item = None
        # if intrinsic_calibrations are set on this item, use it, giving it precedence
        if self.intrinsic_intensity_calibration:
            intensity_calibration_item = self.intrinsic_intensity_calibration
        # if intrinsic_calibrations are not set, then try to get calibrations from the data source
        if intensity_calibration_item is None and self.data_source:
            intensity_calibration_item = self.data_source.calculated_intensity_calibration
        data_shape, data_dtype = self.__get_root_data_shape_and_dtype()
        if data_shape is not None and data_dtype is not None:
            for operation in self.operations:
                if operation.enabled:
                    intensity_calibration_item = operation.get_processed_intensity_calibration_item(data_shape, data_dtype, intensity_calibration_item)
                    data_shape, data_dtype = operation.get_processed_data_shape_and_dtype(data_shape, data_dtype)
        return intensity_calibration_item
    calculated_intensity_calibration = property(__get_calculated_intensity_calibration)

    # call this when data changes. this makes sure that the right number
    # of intrinsic_calibrations exist in this object.
    def sync_intrinsic_calibrations(self, ndim):
        while len(self.intrinsic_calibrations) < ndim:
            self.intrinsic_calibrations.append(Calibration.CalibrationItem())
        while len(self.intrinsic_calibrations) > ndim:
            self.intrinsic_calibrations.remove(self.intrinsic_calibrations[-1])
        if self.has_master_data and self.intrinsic_intensity_calibration is None:
            self.intrinsic_intensity_calibration = Calibration.CalibrationItem()
        if not self.has_master_data and self.intrinsic_intensity_calibration is not None:
            self.intrinsic_intensity_calibration = None

    # calculate the calibrations by starting with the source calibration
    # and then applying calibration transformations for each enabled
    # operation.
    def __get_calculated_calibrations(self):
        calibration_items = None
        # if intrinsic_calibrations are set on this item, use it, giving it precedence
        if self.intrinsic_calibrations:
            calibration_items = self.intrinsic_calibrations
        # if intrinsic_calibrations are not set, then try to get calibrations from the data source
        if calibration_items is None and self.data_source:
            calibration_items = self.data_source.calculated_calibrations
        data_shape, data_dtype = self.__get_root_data_shape_and_dtype()
        if data_shape is not None and data_dtype is not None:
            for operation_item in self.operations:
                if operation_item.enabled:
                    calibration_items = operation_item.get_processed_calibration_items(data_shape, data_dtype, calibration_items)
                    data_shape, data_dtype = operation_item.get_processed_data_shape_and_dtype(data_shape, data_dtype)
        return calibration_items
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
            datetime_ = Utility.get_datetime_from_datetime_item(datetime_original)
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
        elif key == "displays":
            value.add_listener(self)
            value._set_data_item(self)
            self.notify_data_item_content_changed(set([DISPLAY]))
        elif key == "data_items":
            self.notify_listeners("data_item_inserted", self, value, before_index, False)
            value.data_source = self
            self.notify_data_item_content_changed(set([CHILDREN]))
            self.update_counted_data_items(value.counted_data_items + collections.Counter([value]))
            for operation_index, operation_item in enumerate(value.operations):
                self.item_inserted(value, "operations", operation_item, operation_index)
            value.add_observer(self)
        elif key == "intrinsic_calibrations":
            value.add_listener(self)
            self.notify_data_item_content_changed(set([DISPLAY]))

    def notify_remove_item(self, key, value, index):
        super(DataItem, self).notify_remove_item(key, value, index)
        if key == "operations":
            value.remove_listener(self)
            self.sync_operations()
            self.notify_data_item_content_changed(set([DATA]))
        elif key == "displays":
            value._set_data_item(None)
            value.remove_listener(self)
            self.notify_data_item_content_changed(set([DISPLAY]))
        elif key == "data_items":
            value.remove_observer(self)
            for operation_index, operation_item in enumerate(reversed(value.operations)):
                self.item_removed(value, "operations", operation_item, operation_index)
            self.subtract_counted_data_items(value.counted_data_items + collections.Counter([value]))
            self.notify_listeners("data_item_removed", self, value, index, False)
            value.data_source = None
            self.notify_data_item_content_changed(set([CHILDREN]))
        elif key == "intrinsic_calibrations":
            value.remove_listener(self)
            self.notify_data_item_content_changed(set([DISPLAY]))

    # this message is received when an item being listened to (child data items)
    # has something inserted.
    def item_inserted(self, parent, key, object, before_index):
        # watch for operations being inserted into child data items
        # the parent parameter is the child data item and
        # the object parameter is the child data item operation being inserted.
        if parent in self.data_items and key == "operations":
            for display in self.displays:
                display.operation_inserted_into_child_data_item(parent, object)

    # this message is received when an item being listened to (child data items)
    # has something removed.
    def item_removed(self, parent, key, item, index):
        # watch for operations being removed from child data items
        # the parent parameter is a child data item and has already been removed from self.data_items
        # the item parameter is the child data item operation being removed.
        if key == "operations":
            for display in self.displays:
                display.operation_removed_from_child_data_item(item)

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
        return self.__title if self.__title else _("Untitled")
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

    # source file path
    def __get_source_file_path(self):
        return self.__source_file_path
    def __set_source_file_path(self, value):
        if self.__source_file_path != value:
            self.__source_file_path = value
            self.notify_set_property("source_file_path", self.__source_file_path)
    source_file_path = property(__get_source_file_path, __set_source_file_path)

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(DataItem, self).notify_set_property(key, value)
        self.notify_data_item_content_changed(set([DISPLAY]))
        for processor in self.__processors.values():
            processor.data_item_property_changed(key, value)

    # this message comes from the calibration. the connection is established when a calibration
    # is added or removed from this object.
    def calibration_changed(self, calibration):
        self.notify_data_item_content_changed(set([DISPLAY]))

    # this message comes from the operation. the connection is managed
    # by watching for changes to the operations relationship. when an operation
    # is added/removed, this object becomes a listener via add_listener/remove_listener.
    def operation_changed(self, operation):
        self.notify_data_item_content_changed(set([DATA]))

    # this message comes from the display. the connection is established when a display
    # is added or removed from this object.
    def display_changed(self, display):
        self.notify_data_item_content_changed(set([DISPLAY]))

    # data_item_content_changed comes from data sources to indicate that data
    # has changed. the connection is established in __set_data_source.
    def data_item_content_changed(self, data_source, changes):
        assert data_source == self.data_source
        # we don't care about display changes to the data source; only data changes.
        if DATA in changes:
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
            file_datetime = Utility.get_datetime_from_datetime_item(self.datetime_original)
            # tell the database about it
            if self.__master_data is not None:
                # save these here so that if the data isn't immediately written out, these values can be returned
                # from _get_master_data_data_reference when the data is written.
                self.__master_data_reference_type = "relative_file"
                self.__master_data_reference = data_file_path
                self.__master_data_file_datetime = file_datetime
                self.notify_set_data_reference("master_data", self.__master_data, self.__master_data.shape, self.__master_data.dtype, "relative_file", data_file_path, file_datetime)
            self.notify_data_item_content_changed(set([DATA]))

    # accessor for storage subsystem.
    def _get_master_data_data_reference(self):
        reference_type = self.__master_data_reference_type # if self.__master_data_reference_type else "relative_file"
        reference = self.__master_data_reference # if self.__master_data_reference else DataItem._get_data_file_path(self.uuid, self.datetime_original, session_id=self.session_id)
        file_datetime = self.__master_data_file_datetime # if self.__master_data_file_datetime else Utility.get_datetime_from_datetime_item(self.datetime_original)
        # when data items are initially created, they will have their data in memory.
        # this method will be called when the data gets written out to disk.
        # to ensure that the data gets unloaded, grab it here and release it.
        # if no other object is holding a reference, the data will be unloaded from memory.
        if self.__master_data is not None:
            with self.data_ref() as d:
                master_data = d.master_data
        else:
            master_data = None
        self.master_data_save_event.set()
        return master_data, self.__master_data_shape, self.__master_data_dtype, reference_type, reference, file_datetime

    def set_external_master_data(self, data_file_path, data_shape, data_dtype):
        with self.__data_mutex:
            self.set_cached_value("master_data_shape", data_shape)
            self.set_cached_value("master_data_dtype", data_dtype)
            self.__master_data_shape = data_shape
            self.__master_data_dtype = data_dtype
            self.__has_master_data = True
            spatial_ndim = len(Image.spatial_shape_from_shape_and_dtype(data_shape, data_dtype))
            self.sync_intrinsic_calibrations(spatial_ndim)
            file_datetime = datetime.datetime.fromtimestamp(os.path.getmtime(data_file_path))
        # save these here so that if the data isn't immediately written out, these values can be returned
        # from _get_master_data_data_reference when the data is written.
        self.__master_data_reference_type = "external_file"
        self.__master_data_reference = data_file_path
        self.__master_data_file_datetime = file_datetime
        self.notify_set_data_reference("master_data", None, data_shape, data_dtype, "external_file", data_file_path, file_datetime)
        self.notify_data_item_content_changed(set([DATA]))

    def __load_master_data(self):
        # load data from datastore if not present
        if self.has_master_data and self.datastore and self.__master_data is None:
            #logging.debug("loading %s", self)
            reference_type, reference = self.datastore.get_data_reference(self.datastore.find_parent_node(self), "master_data")
            self.__master_data = self.datastore.load_data_reference("master_data", reference_type, reference)

    def __unload_master_data(self):
        # unload data if it can be reloaded from datastore.
        # data cannot be unloaded if transaction count > 0 or if there is no datastore.
        if self.transaction_count == 0 and self.has_master_data and self.datastore:
            self.__master_data = None
            self.__cached_data = None
            #logging.debug("unloading %s", self)

    def increment_data_ref_count(self):
        with self.__data_ref_count_mutex:
            initial_count = self.__data_ref_count
            self.__data_ref_count += 1
            if initial_count == 0:
                if self.__data_source:
                    self.__data_source.increment_data_ref_count()
                else:
                    self.__load_master_data()
        return initial_count+1
    def decrement_data_ref_count(self):
        with self.__data_ref_count_mutex:
            self.__data_ref_count -= 1
            final_count = self.__data_ref_count
            if final_count == 0:
                if self.__data_source:
                    self.__data_source.decrement_data_ref_count()
                else:
                    self.__unload_master_data()
        return final_count

    # used for testing
    def __is_data_loaded(self):
        return self.has_master_data and self.__master_data is not None
    is_data_loaded = property(__is_data_loaded)

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

    def __get_data_immediate(self):
        """ add_ref, get data, remove_ref """
        with self.data_ref() as data_ref:
            return data_ref.data
    data = property(__get_data_immediate)

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

    # data property. read only. this method should almost *never* be called on the main thread since
    # it takes an unpredictable amount of time.
    def __get_data(self):
        if threading.current_thread().getName() == "MainThread":
            #logging.debug("*** WARNING: data called on main thread ***")
            #import traceback
            #traceback.print_stack()
            pass
        self.__data_mutex.acquire()
        if self.__cached_data_dirty or self.__cached_data is None:
            self.__data_mutex.release()
            with self.__get_data_mutex:
                # this should NOT happen under the data mutex. it can take a long time.
                data = None
                if self.has_master_data:
                    data = self.__master_data
                if data is None:
                    if self.data_source:
                        with self.data_source.data_ref() as data_ref:
                            # this can be a lengthy operation
                            data = data_ref.data
                operations = self.operations
                if len(operations) and data is not None:
                    # apply operations
                    if data is not None:
                        for operation in reversed(operations):
                            data = operation.process_data(data)
                self.__get_data_range_for_data(data)
            with self.__data_mutex:
                self.__cached_data = data
                self.__cached_data_dirty = False
        else:
            self.__data_mutex.release()
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

    def __is_data_3d(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_3d(data_shape, data_dtype)
    is_data_3d = property(__is_data_3d)

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

    def __is_data_scalar_type(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_scalar_type(data_shape, data_dtype)
    is_data_scalar_type = property(__is_data_scalar_type)

    def __is_data_complex_type(self):
        data_shape, data_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_complex_type(data_shape, data_dtype)
    is_data_complex_type = property(__is_data_complex_type)

    def get_data_value(self, pos):
        # do not force data calculation here, but trigger data loading
        if self.__cached_data is None:
            pass  # TODO: Cursor should trigger loading of data if not already laoded.
        with self.__data_mutex:
            if self.is_data_1d:
                if self.__cached_data is not None:
                    return self.__cached_data[pos[0]]
            elif self.is_data_2d:
                if self.__cached_data is not None:
                    return self.__cached_data[pos[0], pos[1]]
            # TODO: fix me 3d
            elif self.is_data_3d:
                if self.__cached_data is not None:
                    return self.__cached_data[pos[0], pos[1]]
        return None

    def __get_preview_2d(self):
        if self.__preview is None:
            with self.data_ref() as data_ref:
                data = data_ref.data
            if Image.is_data_2d(data):
                data_2d = Image.scalar_from_array(data)
            # TODO: fix me 3d
            elif Image.is_data_3d(data):
                data_2d = Image.scalar_from_array(data.reshape(tuple([data.shape[0] * data.shape[1], ] + list(data.shape[2::]))))
            else:
                data_2d = None
            if data_2d is not None:
                data_range = self.__get_data_range()
                display_limits = self.display_limits
                self.__preview = Image.create_rgba_image_from_array(data_2d, data_range=data_range, display_limits=display_limits)
        return self.__preview
    preview_2d = property(__get_preview_2d)

    def snapshot(self):
        """
            Take a snapshot and return a new data item. A snapshot is a copy of everything
            except the data and operations which are replaced by new data with the operations
            applied or "burned in".
        """
        data_item_copy = DataItem()
        data_item_copy.title = self.title
        data_item_copy.param = self.param
        data_item_copy.source_file_path = self.source_file_path
        with data_item_copy.property_changes() as property_accessor:
            property_accessor.properties.clear()
            property_accessor.properties.update(self.properties)
        data_item_copy.display_limits = self.display_limits
        data_item_copy.datetime_original = Utility.get_current_datetime_item()
        data_item_copy.datetime_modified = data_item_copy.datetime_original
        for calibration in self.calculated_calibrations:
            data_item_copy.intrinsic_calibrations.append(copy.deepcopy(calibration))
        data_item_copy.intrinsic_intensity_calibration = self.calculated_intensity_calibration
        for data_item in self.data_items:
            data_item_copy.data_items.append(copy.deepcopy(data_item))
        for display in self.displays:
            data_item_copy.displays.append(copy.deepcopy(display))
        # operations are NOT copied, since this is a snapshot of the data
        with self.data_ref() as data_ref:
            data_item_copy.__set_master_data(numpy.copy(data_ref.data))
        return data_item_copy


class DataItemBindingSource(Observable.Observable):
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


_computation_fns = list()

def register_data_item_computation(computation_fn):
    global _computation_fns
    _computation_fns.append(computation_fn)

def unregister_data_item_computation(self, computation_fn):
    pass
