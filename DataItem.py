# standard libraries
import collections
import copy
import datetime
import gettext
import logging
import threading
import uuid
import weakref

# third party libraries
import numpy
import scipy.interpolate

# local libraries
from nion.swift import CanvasItem
from nion.swift.Decorators import ProcessingThread
from nion.swift import Image
from nion.swift import Inspector
from nion.swift import Storage
from nion.swift import Utility

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
    def build(cls, datastore, item_node, uuid_):
        origin = datastore.get_property(item_node, "origin", None)
        scale = datastore.get_property(item_node, "scale", None)
        units = datastore.get_property(item_node, "units", None)
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


# enumerations for types of changes
DATA = 1
DISPLAY = 2
CHILDREN = 3
PANEL = 4
THUMBNAIL = 5
HISTOGRAM = 6
SOURCE = 7


class DataItemEditor(object):
    def __init__(self, ui, data_item):
        self.ui = ui
        self.data_item = data_item
        self.widget = self.ui.create_column_widget()

        self.widget.add_spacing(6)

        # info editor
        self.info_section = self.ui.create_column_widget()
        self.info_section_title = self.ui.create_row_widget()
        #self.info_section_title.add(self.ui.create_label_widget(u"\u25B6", properties={"width": "20"}))
        self.info_section_title.add(self.ui.create_label_widget(_("Info"), properties={"stylesheet": "font-weight: bold"}))
        self.info_section_title.add_stretch()
        # title
        self.info_section.add(self.info_section_title)
        self.info_section_title_row = self.ui.create_row_widget()
        self.info_section_title_row.add_spacing(20)
        self.info_section_title_row.add(self.ui.create_label_widget(_("Title"), properties={"width":60}))
        self.info_title_label = self.ui.create_label_widget(properties={"width":240})
        self.info_section_title_row.add(self.info_title_label)
        self.info_section_title_row.add_stretch()
        self.info_section.add(self.info_section_title_row)
        # date
        self.info_section.add_spacing(2)
        self.info_section_datetime_row = self.ui.create_row_widget()
        self.info_section_datetime_row.add_spacing(20)
        self.info_section_datetime_row.add(self.ui.create_label_widget(_("Date"), properties={"width":60}))
        self.info_datetime_label = self.ui.create_label_widget(properties={"width":240})
        self.info_section_datetime_row.add(self.info_datetime_label)
        self.info_section_datetime_row.add_stretch()
        self.info_section.add(self.info_section_datetime_row)
        # format (size, datatype)
        self.info_section.add_spacing(2)
        self.info_section_format_row = self.ui.create_row_widget()
        self.info_section_format_row.add_spacing(20)
        self.info_section_format_row.add(self.ui.create_label_widget(_("Data"), properties={"width":60}))
        self.info_format_label = self.ui.create_label_widget(properties={"width":240})
        self.info_section_format_row.add(self.info_format_label)
        self.info_section_format_row.add_stretch()
        self.info_section.add(self.info_section_format_row)
        # extra space
        self.info_section.add_spacing(8)
        # add to enclosing widget
        self.widget.add(self.info_section)

        # param editor
        self.param_row = self.ui.create_row_widget()
        param_label = self.ui.create_label_widget(_("Parameter"))
        self.param_slider = self.ui.create_slider_widget()
        self.param_slider.maximum = 100
        self.param_slider.on_value_changed = lambda value: self.param_slider_value_changed(value)
        self.param_field = self.ui.create_line_edit_widget()
        self.param_field.on_editing_finished = lambda text: self.param_editing_finished(text)
        self.param_field_formatter = Inspector.FloatFormatter(self.param_field)
        self.param_row.add(param_label)
        self.param_row.add_spacing(8)
        self.param_row.add(self.param_slider)
        self.param_row.add_spacing(8)
        self.param_row.add(self.param_field)
        self.param_row.add_stretch()
        self.param_row.visible = False
        self.widget.add(self.param_row)

        # calibrations editor
        self.calibrations_section = self.ui.create_column_widget()
        self.calibrations_section_title = self.ui.create_row_widget()
        #self.calibrations_section_title.add(self.ui.create_label_widget(u"\u25B6", properties={"width": "20"}))
        self.calibrations_section_title.add(self.ui.create_label_widget(_("Calibrations"), properties={"stylesheet": "font-weight: bold"}))
        self.calibrations_section_title.add_stretch()
        self.calibrations_section.add(self.calibrations_section_title)
        self.calibrations_table = self.ui.create_column_widget()
        self.calibrations_labels = self.ui.create_column_widget()
        self.calibrations_column = self.ui.create_column_widget(properties={"spacing": 2})
        self.calibrations_table.add(self.calibrations_labels)
        self.calibrations_column_row = self.ui.create_row_widget()
        self.calibrations_column_row.add_spacing(20)
        self.calibrations_column_row.add(self.calibrations_column)
        self.calibrations_table.add(self.calibrations_column_row)
        self.calibrations_section.add(self.calibrations_table)
        self.widget.add(self.calibrations_section)

        # display limit editor
        self.display_limits_section = self.ui.create_column_widget()
        self.display_limits_section_title = self.ui.create_row_widget()
        #self.display_limits_section_title.add(self.ui.create_label_widget(u"\u25B6", properties={"width": "20"}))
        self.display_limits_section_title.add(self.ui.create_label_widget(_("Display Limits"), properties={"stylesheet": "font-weight: bold"}))
        self.display_limits_section_title.add_stretch()
        self.display_limits_section.add(self.display_limits_section_title)
        self.display_limits_section_table = self.ui.create_row_widget()
        self.display_limits_section_rows = self.ui.create_column_widget()
        self.display_limits_section_table.add_spacing(20)
        self.display_limits_section_table.add(self.display_limits_section_rows)
        self.display_limits_range_row = self.ui.create_row_widget()
        self.display_limits_range_low = self.ui.create_label_widget(properties={"width":60})
        self.display_limits_range_high = self.ui.create_label_widget(properties={"width":60})
        self.display_limits_range_row.add(self.ui.create_label_widget(_("Data Range:"), properties={"width":120}))
        self.display_limits_range_row.add(self.display_limits_range_low)
        self.display_limits_range_row.add_spacing(8)
        self.display_limits_range_row.add(self.display_limits_range_high)
        self.display_limits_range_row.add_stretch()
        self.display_limits_limit_row = self.ui.create_row_widget()
        self.display_limits_limit_low = self.ui.create_line_edit_widget(properties={"width":60})
        self.display_limits_limit_high = self.ui.create_line_edit_widget(properties={"width":60})
        self.display_limits_limit_low.on_editing_finished = lambda text: self.display_limit_low_editing_finished(text)
        self.display_limits_limit_high.on_editing_finished = lambda text: self.display_limit_high_editing_finished(text)
        self.display_limits_limit_row.add(self.ui.create_label_widget(_("Display:"), properties={"width":120}))
        self.display_limits_limit_row.add(self.display_limits_limit_low)
        self.display_limits_limit_row.add_spacing(8)
        self.display_limits_limit_row.add(self.display_limits_limit_high)
        self.display_limits_limit_row.add_stretch()
        self.display_limits_section_rows.add_spacing(4)
        self.display_limits_section_rows.add(self.display_limits_range_row)
        self.display_limits_section_rows.add_spacing(4)
        self.display_limits_section_rows.add(self.display_limits_limit_row)
        self.display_limits_section.add(self.display_limits_section_table)
        self.widget.add(self.display_limits_section)

        # first update to get the values right
        self.__block = False
        self.needs_update = False
        self.update()

        # make sure we're listening to changes of the data item
        self.data_item.add_listener(self)

    def close(self):
        # unlisten to the data item
        self.data_item.remove_listener(self)

    # update the values if needed
    def periodic(self):
        if self.needs_update:
            self.update()

    # this will typically happen on a thread
    def data_item_content_changed(self, data_source, changes):
        if not self.__block:
            # TODO: this is pretty weak!
            if any (k in changes for k in (DISPLAY, )):
                self.needs_update = True

    # update will NEVER be called on a thread
    def update(self):
        # info
        self.info_title_label.text = self.data_item.title
        self.info_datetime_label.text = self.data_item.datetime_original_as_string
        self.info_format_label.text = self.data_item.size_and_data_format_as_string
        # param
        value = self.data_item.param
        self.param_field_formatter.value = float(value)
        self.param_slider.value = int(value * 100)
        # calibrations
        # first match the number of rows to the number of calibrations
        # then populate
        calibrations = self.data_item.calibrations
        if len(calibrations) > 0:
            while self.calibrations_labels.count() > 0:
                self.calibrations_labels.remove(self.calibrations_labels.count() - 1)
            calibration_row = self.ui.create_row_widget()
            row_label = self.ui.create_label_widget("Axis", properties={"width":60})
            origin_field = self.ui.create_label_widget("Origin", properties={"width":60})
            scale_field = self.ui.create_label_widget("Scale", properties={"width":60})
            units_field = self.ui.create_label_widget("Units", properties={"width":60})
            calibration_row.add_spacing(20)
            calibration_row.add(row_label)
            calibration_row.add_spacing(12)
            calibration_row.add(origin_field)
            calibration_row.add_spacing(12)
            calibration_row.add(scale_field)
            calibration_row.add_spacing(12)
            calibration_row.add(units_field)
            calibration_row.add_stretch()
            calibration_header_column = self.ui.create_column_widget()
            calibration_header_column.add(calibration_row)
            calibration_header_column.add_spacing(4)
            self.calibrations_labels.add(calibration_header_column)
        else:
            while self.calibrations_labels.count() > 0:
                self.calibrations_labels.remove(self.calibrations_labels.count() - 1)
            self.calibrations_none_column = self.ui.create_column_widget()
            self.calibrations_none_column.add_spacing(4)
            self.calibrations_none_row = self.ui.create_row_widget()
            self.calibrations_none_row.add_spacing(20)
            self.calibrations_none_row.add(self.ui.create_label_widget("None", properties={"stylesheet": "font: italic"}))
            self.calibrations_none_column.add(self.calibrations_none_row)
            self.calibrations_labels.add(self.calibrations_none_column)
        while self.calibrations_column.count() < len(calibrations):
            calibration_index = self.calibrations_column.count()
            calibration_row = self.ui.create_row_widget()
            row_label = self.ui.create_label_widget(properties={"width":60})
            origin_field = self.ui.create_line_edit_widget(properties={"width":60})
            scale_field = self.ui.create_line_edit_widget(properties={"width":60})
            units_field = self.ui.create_line_edit_widget(properties={"width":60})
            # notice the binding of calibration_index below.
            origin_field.on_editing_finished = lambda text, i=calibration_index: self.calibration_origin_editing_finished(i, text)
            scale_field.on_editing_finished = lambda text, i=calibration_index: self.calibration_scale_editing_finished(i, text)
            units_field.on_editing_finished = lambda text, i=calibration_index: self.calibration_units_editing_finished(i, text)
            calibration_row.add(row_label)
            calibration_row.add_spacing(12)
            calibration_row.add(origin_field)
            calibration_row.add_spacing(12)
            calibration_row.add(scale_field)
            calibration_row.add_spacing(12)
            calibration_row.add(units_field)
            calibration_row.add_stretch()
            self.calibrations_column.add(calibration_row)
        while self.calibrations_column.count() > len(calibrations):
            self.calibrations_column.remove(len(calibrations) - 1)
        for calibration_index, calibration in enumerate(calibrations):
            calibration_row = self.calibrations_column.children[calibration_index]
            calibration_row.children[0].text = "{0:.2f}".format(calibration_index)
            calibration_row.children[1].text = "{0:.2f}".format(calibration.origin)
            calibration_row.children[2].text = "{0:.2f}".format(calibration.scale)
            calibration_row.children[3].text = calibration.units
        # display limits
        data_range = self.data_item.data_range
        if data_range:
            self.display_limits_range_low.text = "{0:.2f}".format(data_range[0])
            self.display_limits_range_high.text = "{0:.2f}".format(data_range[1])
        else:
            self.display_limits_range_low.text = _("N/A")
            self.display_limits_range_high.text = _("N/A")
        display_range = self.data_item.display_range
        if display_range:
            self.display_limits_limit_low.text = "{0:.2f}".format(display_range[0])
            self.display_limits_limit_high.text = "{0:.2f}".format(display_range[1])
        else:
            self.display_limits_limit_low.text = _("N/A")
            self.display_limits_limit_high.text = _("N/A")
        self.needs_update = False

    # handle param editing
    def param_slider_value_changed(self, value):
        self.data_item.param = self.param_slider.value/100.0
        self.update()  # clean up displayed values
    def param_editing_finished(self, text):
        self.data_item.param = self.param_field_formatter.value
        self.update()  # clean up displayed values
        if self.param_field.focused:
            self.param_field.select_all()

    # handle calibration editing
    def calibration_origin_editing_finished(self, calibration_index, text):
        block = self.__block
        self.__block = True
        self.data_item.calibrations[calibration_index].origin = float(text)
        self.__block = block
        self.update()  # clean up displayed values
        line_edit_widget = self.calibrations_column.children[calibration_index].children[1]
        if line_edit_widget.focused:
            line_edit_widget.select_all()
    def calibration_scale_editing_finished(self, calibration_index, text):
        block = self.__block
        self.__block = True
        self.data_item.calibrations[calibration_index].scale = float(text)
        self.__block = block
        self.update()  # clean up displayed values
        line_edit_widget = self.calibrations_column.children[calibration_index].children[2]
        if line_edit_widget.focused:
            line_edit_widget.select_all()
    def calibration_units_editing_finished(self, calibration_index, text):
        block = self.__block
        self.__block = True
        self.data_item.calibrations[calibration_index].units = text
        self.__block = block
        self.update()  # clean up displayed values
        line_edit_widget = self.calibrations_column.children[calibration_index].children[3]
        if line_edit_widget.focused:
            line_edit_widget.select_all()

    # handle display limit editing
    def display_limit_low_editing_finished(self, text):
        if self.display_limits_range_low.text != text:
            display_limit_low = float(text)
            block = self.__block
            self.__block = True
            self.data_item.display_limits = (display_limit_low, self.data_item.display_range[1])
            self.__block = block
            self.update()  # clean up displayed values
            if self.display_limits_range_low.focused:
                self.display_limits_range_low.select_all()
    def display_limit_high_editing_finished(self, text):
        if self.display_limits_range_high.text != text:
            display_limit_high = float(text)
            block = self.__block
            self.__block = True
            self.data_item.display_limits = (self.data_item.display_range[0], display_limit_high)
            self.__block = block
            self.update()  # clean up displayed values
            if self.display_limits_limit_high.focused:
                self.display_limits_range_high.select_all()


# dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HH:MM" or "-HH:MM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# time zone name is for display only and has no specified format

class DataItem(Storage.StorageBase):

    def __init__(self, data=None):
        super(DataItem, self).__init__()
        self.storage_properties += ["title", "param", "display_limits", "datetime_modified", "datetime_original", "properties"]
        self.storage_relationships += ["calibrations", "graphics", "operations", "data_items"]
        self.storage_data_keys += ["master_data"]
        self.storage_type = "data-item"
        self.description = []
        self.closed = False
        self.__title = None
        self.__param = 0.5
        self.__display_limits = None  # auto
        # data is immutable but metadata isn't, keep track of original and modified dates
        self.__datetime_original = Utility.get_current_datetime_element()
        self.__datetime_modified = self.__datetime_original
        self.calibrations = Storage.MutableRelationship(self, "calibrations")
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
        self.__data_accessor_count = 0
        self.__data_accessor_count_mutex = threading.RLock()
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
    def _get_data_file_path(cls, uuid_):
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
        # encode(uuid.uuid4(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")  # 25 character results
        return "master-data-" + str(uuid_) + ".nsdata"

    @classmethod
    def build(cls, datastore, item_node, uuid_):
        title = datastore.get_property(item_node, "title")
        param = datastore.get_property(item_node, "param")
        properties = datastore.get_property(item_node, "properties")
        display_limits = datastore.get_property(item_node, "display_limits")
        calibrations = datastore.get_items(item_node, "calibrations")
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
        # setting master data may add calibrations automatically. remove them here to start from clean slate.
        while len(data_item.calibrations):
            data_item.calibrations.pop()
        data_item.calibrations.extend(calibrations)
        if display_limits:
            data_item.display_limits = display_limits
        if datetime_modified:
            data_item.datetime_modified = datetime_modified
        if datetime_original:
            data_item.datetime_original = datetime_original
        data_item.graphics.extend(graphics)
        return data_item

    # This gets called when reference count goes to 0, but before deletion.
    def about_to_delete(self):
        self.__thumbnail_thread.close()
        self.__thumbnail_thread = None
        self.__histogram_thread.close()
        self.__histogram_thread = None
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

    def create_editor(self, ui):
        return DataItemEditor(ui, self)

    # cheap, but incorrect, way to tell whether this is live acquisition
    def __get_is_live(self):
        return self.transaction_count > 0
    is_live = property(__get_is_live)

    def __get_live_status_as_string(self):
        if self.is_live:
            return _("{0:s} {1:s}".format(_("Live"), str(self.__properties.get("frame_index", str()))))
        return str()
    live_status_as_string = property(__get_live_status_as_string)

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
        if self.is_data_rgb_type:
            data_range = (0, 255)
        elif self.is_data_complex_type:
            scalar_data = Image.scalar_from_array(data)
            data_range = (scalar_data.min(), scalar_data.max())
        elif data is not None:
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
            with self.create_data_accessor() as data_accessor:
                data = data_accessor.data
                self.__get_data_range_for_data(data)
        return data_range
    data_range = property(__get_data_range)

    def __get_display_range(self):
        data_range = self.__get_data_range()
        return self.__display_limits if self.__display_limits else data_range
    # TODO: this is only valid after data has been called (!)
    display_range = property(__get_display_range)

    def __is_calibrated(self):
        return len(self.calibrations) == len(self.spatial_shape)
    is_calibrated = property(__is_calibrated)

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
            if len(datetime_original["local_datetime"]) == 26:
                datetime_ = datetime.datetime.strptime(datetime_original["local_datetime"], "%Y-%m-%dT%H:%M:%S.%f")
            else:
                datetime_ = datetime.datetime.strptime(datetime_original["local_datetime"], "%Y-%m-%dT%H:%M:%S")
            return datetime_.strftime("%c")
        else:
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
            self.notify_data_item_content_changed(set([DATA]))
        elif key == "data_items":
            self.notify_listeners("data_item_inserted", self, value, before_index, False)  # see note about smart groups
            value.data_source = self
            self.notify_data_item_content_changed(set([CHILDREN]))
            self.update_counted_data_items(value.counted_data_items + collections.Counter([value]))
        elif key == "calibrations":
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
        elif key == "calibrations":
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
                self.sync_calibrations(spatial_ndim)
            data_file_path = DataItem._get_data_file_path(self.uuid)
            self.notify_set_data("master_data", self.__master_data, data_file_path)
            self.notify_data_item_content_changed(set([DATA]))
    # hidden accessor for storage subsystem. temporary.
    def _get_master_data(self):
        return self.__get_master_data()
    def _get_master_data_data_file_path(self):
        return DataItem._get_data_file_path(self.uuid)

    def increment_accessor_count(self):
        with self.__data_accessor_count_mutex:
            initial_count = self.__data_accessor_count
            self.__data_accessor_count += 1
        if initial_count == 0:
            # load data from datastore if not present
            if self.has_master_data and self.datastore and self.__master_data is None:
                #logging.debug("loading %s (%s)", self, self.uuid)
                master_data = self.datastore.get_data(self.datastore.find_parent_node(self), "master_data")
                self.__master_data = master_data
                #import traceback
                #traceback.print_stack()
        return initial_count+1
    def decrement_accessor_count(self):
        with self.__data_accessor_count_mutex:
            self.__data_accessor_count -= 1
            final_count = self.__data_accessor_count
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
            with self.create_data_accessor() as data_accessor:
                data_2d = data_accessor.data
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
        line_graph_canvas_item = CanvasItem.LineGraphCanvasItem()
        line_graph_canvas_item.update_layout((0, 0), (height, width))
        line_graph_canvas_item.draw_captions = False
        line_graph_canvas_item.draw_grid = False
        line_graph_canvas_item.draw_frame = False
        line_graph_canvas_item.background_color = "#EEEEEE"
        line_graph_canvas_item.graph_background_color = "rgba(0,0,0,0)"
        line_graph_canvas_item.data = data
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
        with self.create_data_accessor() as data_accessor:
            data = data_accessor.data
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
        with self.create_data_accessor() as data_accessor:
            data = data_accessor.data
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
        data_item_copy.datetime_modified = self.datetime_modified
        data_item_copy.datetime_original = self.datetime_original
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


# TODO: subclass Broadcaster
class DataItemBinding(object):

    def __init__(self):
        self.__listeners = []
        self.__listeners_mutex = threading.RLock()
        self.__weak_data_item = None

    def close(self):
        self.__weak_data_item = None

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    data_item = property(__get_data_item)

    # Add a listener
    def add_listener(self, listener):
        with self.__listeners_mutex:
            assert listener is not None
            self.__listeners.append(listener)
    # Remove a listener.
    def remove_listener(self, listener):
        with self.__listeners_mutex:
            assert listener is not None
            self.__listeners.remove(listener)
    # Send a message to the listeners
    def notify_listeners(self, fn, *args, **keywords):
        try:
            with self.__listeners_mutex:
                listeners = copy.copy(self.__listeners)
            for listener in listeners:
                if hasattr(listener, fn):
                    getattr(listener, fn)(*args, **keywords)
        except Exception as e:
            import traceback
            traceback.print_exc()
            logging.debug("Notify Error: %s", e)

    # this message is received from subclasses (and tests).
    def notify_data_item_binding_data_item_changed(self, data_item):
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
        self.notify_listeners("data_item_binding_data_item_changed", data_item)

    # this message is received from subclasses (and tests).
    def notify_data_item_binding_data_item_content_changed(self, data_item, changes):
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
        self.notify_listeners("data_item_binding_data_item_content_changed", data_item, changes)
