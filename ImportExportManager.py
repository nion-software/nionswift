# standard libraries
import datetime
import logging
import os
import time

# third party libraries
# None

# local libraries
from nion.swift import DataItem
from nion.swift import Decorators
from nion.swift import Image


class ImportExportIncompatibleDataError(Exception):
    pass


class ImportExportHandler(object):

    # Extensions should not include a period.
    def __init__(self, name, extensions):
        self.name = name
        self.extensions = extensions

    def can_read(self):
        return True

    # return data items
    def read(self, ui, file_path, extension):
        with open(file_path, 'rb') as f:
            return self.read_file(file_path, extension, f)

    # return data items
    def read_file(self, file_path, extension, file):
        data_elements = self.read_data(extension, file)
        data_items = list()
        for data_element in data_elements:
            if "data" in data_element:
                if not "title" in data_element:
                    root, filename = os.path.split(file_path)
                    title, _ = os.path.splitext(filename)
                    data_element["title"] = title
                data_element["filepath"] = file_path
                data_item = create_data_item_from_data_element(data_element)
                data_items.append(data_item)
        return data_items

    # return data
    def read_data(self, extension, file):
        return None

    def can_write(self, data_item, extension):
        return False

    def write(self, ui, data_item, path, extension):
        with open(path, 'wb') as f:
            self.write_file(data_item, extension, f)

    def write_file(self, data_item, extension, file):
        with data_item.create_data_accessor() as data_accessor:
            data = data_accessor.data
        if data is not None:
            self.write_data(data, extension, file)

    def write_data(self, data, extension, file):
        pass


class ImportExportManager(object):
    __metaclass__ = Decorators.Singleton

    """
    Keeps track of import/export plugins.
    """
    def __init__(self):
        # we store a of dicts dicts containing extensions,
        # load_func, save_func, keyed by name.
        self.__io_handlers = []

    def register_io_handler(self, io_handler):
        self.__io_handlers.append(io_handler)

    def unregister_io_handler(self, io_handler):
        self.__io_handlers.remove(io_handler)

    def get_readers(self):
        readers = []
        for io_handler in self.__io_handlers:
            if io_handler.can_read():
                readers.append(io_handler)
        return readers

    def get_writers_for_data_item(self, data_item):
        writers = []
        for io_handler in self.__io_handlers:
            for extension in io_handler.extensions:
                if io_handler.can_write(data_item, extension):
                    writers.append(io_handler)
                    break  # from iterating extensions
        return writers

    # read file, return data items
    def read(self, ui, path):
        root, extension = os.path.splitext(path)
        if extension:
            extension = extension[1:]  # remove the leading "."
            for io_handler in self.__io_handlers:
                if extension in io_handler.extensions:
                    return io_handler.read(ui, path, extension)
        return None

    def write(self, ui, data_item, path):
        root, extension = os.path.splitext(path)
        if extension:
            extension = extension[1:]  # remove the leading "."
            for io_handler in self.__io_handlers:
                if extension in io_handler.extensions and io_handler.can_write(data_item, extension):
                    io_handler.write(ui, data_item, path, extension)


# data element is a dict which can be processed into a data item
def create_data_item_from_data_element(data_element):
    data_item = DataItem.DataItem()
    update_data_item_from_data_element(data_item, data_element)
    return data_item


def update_data_item_from_data_element(data_item, data_element):
    with data_item.data_item_changes():
        # file path
        # master data
        with data_item.create_data_accessor() as data_accessor:
            data = data_element["data"]
            sub_area = data_element.get("sub_area")
            if data_accessor.master_data is not None and sub_area is not None:
                top = sub_area[0][0]
                bottom = sub_area[0][0] + sub_area[1][0]
                left = sub_area[0][1]
                right = sub_area[0][1] + sub_area[1][1]
                data_accessor.master_data[top:bottom, left:right] = data[top:bottom, left:right]
                data_accessor.master_data = data_accessor.master_data  # trigger change notifications, for lack of better mechanism
            else:
                data_accessor.master_data = data
        # spatial calibrations
        if "spatial_calibration" in data_element:
            spatial_calibration = data_element.get("spatial_calibration")
            if len(spatial_calibration) == len(data_item.spatial_shape):
                for dimension, dimension_calibration in enumerate(spatial_calibration):
                    origin = float(dimension_calibration[0])
                    scale = float(dimension_calibration[1])
                    units = unicode(dimension_calibration[2])
                    if scale != 0.0:
                        data_item.calibrations[dimension].origin = origin
                        data_item.calibrations[dimension].scale = scale
                        data_item.calibrations[dimension].units = units
        # properties (general tags)
        if "properties" in data_element:
            properties = data_item.grab_properties()
            properties.update(data_element.get("properties"))
            data_item.release_properties(properties)
        # title
        if "title" in data_element:
            data_item.title = data_element["title"]
        # description
        # dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
        # time zones are offsets (east of UTC) in the following format "+HH:MM" or "-HH:MM"
        # daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
        # time zone name is for display only and has no specified format
        # datetime.datetime.strptime(datetime.datetime.isoformat(datetime.datetime.now()), "%Y-%m-%dT%H:%M:%S.%f" )
        # datetime_modified, datetime_modified_tz, datetime_modified_dst, datetime_modified_tzname is the time at which this image was modified.
        # datetime_original, datetime_original_tz, datetime_original_dst, datetime_original_tzname is the time at which this image was created.
        def get_current_datetime_element():
            datetime_element = dict()
            datetime_element["local_datetime"] = datetime.datetime.now().isoformat()
            tz_minutes = int(round((datetime.datetime.now() - datetime.datetime.utcnow()).total_seconds())) / 60
            datetime_element["tz"] = '{0:+03d}{1:02d}'.format(tz_minutes/60, tz_minutes%60)
            datetime_element["dst"] = "+60" if time.localtime().tm_isdst else "+00"
            return datetime_element
        def parse_datetime_keys(root, default=None):
            if root in data_element:
                datetime_element = dict()
                datetime_element["local_datetime"] = datetime.datetime.strptime(data_element[root], "%Y-%m-%dT%H:%M:%S.%f").isoformat()
                if root + "_tz" in data_element:
                    tz_match = re.compile("([-+])(\d{4})").match(data_element[root + "_tz"])
                    if tz_match:
                        datetime_element["tz"] = tz_match.group(0)
                if root + "_dst" in data_element:
                    dst_match = re.compile("([-+])(\d{2})").match(data_element[root + "_dst"])
                    if dst_match:
                        datetime_element["dst"] = dst_match.group(0)
                if "datatime_tzname" in data_element:
                    datetime_element["tzname"] = data_element["datatime_tzname"]
                return datetime_element
            return default
        current_datetime_element = get_current_datetime_element()  # get this once to be consistent
        data_item.datetime_modified = parse_datetime_keys("datetime_modified", current_datetime_element)
        data_item.datetime_original = parse_datetime_keys("datetime_original", data_item.datetime_modified)
        # author
        # sample
        # facility
        # location
        # gps
        # instrument
        # copyright
        # exposure
        # extra_high_tension


class StandardImportExportHandler(ImportExportHandler):

    def __init__(self, name, extensions):
        super(StandardImportExportHandler, self).__init__(name, extensions)

    def read(self, ui, path, extension):
        data = Image.read_image_from_file(ui, path)
        if data is not None:
            root, filename = os.path.split(path)
            title, _ = os.path.splitext(filename)
            data_item = DataItem.DataItem()
            with data_item.create_data_accessor() as data_accessor:
                data_accessor.master_data = data
            data_item.title = title
            return data_item
        return None

    def can_write(self, data_item, extension):
        return len(data_item.spatial_shape) == 2

    def write(self, ui, data_item, path, extension):
        data = data_item.preview_2d
        if data is not None:
            ui.save_rgba_data_to_file(data, path, extension)


ImportExportManager().register_io_handler(StandardImportExportHandler("JPEG", ["jpg", "jpeg"]))
ImportExportManager().register_io_handler(StandardImportExportHandler("PNG", ["png"]))
ImportExportManager().register_io_handler(StandardImportExportHandler("TIFF", ["tif", "tiff"]))
