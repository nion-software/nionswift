# standard libraries
import copy
import cStringIO
import datetime
import json
import logging
import os
import re
import string
import zipfile

# third party libraries
import numpy

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.model import Image
from nion.swift.model import Utility


def clean_dict(d0):
    """
        Return a json-clean dict. Will log info message for failures.
    """
    d = dict()
    for key in d0:
        cleaned_item = clean_item(d0[key])
        if cleaned_item is None:
            logging.info("  in dict for key %s", key)
        else:
            d[key] = cleaned_item
    return d


def clean_list(l0):
    """
        Return a json-clean list. Will log info message for failures.
    """
    l = list()
    for index, item in enumerate(l0):
        cleaned_item = clean_item(item)
        if cleaned_item is None:
            logging.info("  in list at original index %s", index)
        else:
            l.append(cleaned_item)
    return l


def clean_tuple(t0):
    """
        Return a json-clean tuple. Will log info message for failures.
    """
    t = []
    for index, item in enumerate(t0):
        cleaned_item = clean_item(item)
        if cleaned_item is None:
            logging.info("  in tuple at original index %s", index)
        else:
            t.append(cleaned_item)
    return tuple(t)


def clean_item(i):
    """
        Return a json-clean item or None. Will log info message for failure.
    """
    itype = type(i)
    if itype == dict:
        return clean_dict(i)
    elif itype == list:
        return clean_list(i)
    elif itype == tuple:
        return clean_tuple(i)
    elif itype == numpy.float32:
        return float(i)
    elif itype == numpy.float64:
        return float(i)
    elif itype == float:
        return i
    elif itype == str or itype == unicode:
        return i
    elif itype == int or itype == long:
        return i
    elif itype == bool:
        return i
    logging.info("Unable to handle type %s", itype)
    return None


class ImportExportIncompatibleDataError(Exception):
    pass


class ImportExportHandler(object):

    """
        A base class for implementing import/export handlers.

        :param name: the localized name for the handler; will appear in file dialogs
        :param extensions: the list of handled extensions; do not include leading dots
    """

    # Extensions should not include a period.
    def __init__(self, name, extensions):
        self.name = name
        self.extensions = extensions

    def can_read(self):
        return True

    # return data items
    def read_data_items(self, ui, extension, file_path):
        data_items = list()
        if os.path.exists(file_path) or file_path.startswith(":"):  # check for colon is for testing
            data_elements = self.read_data_elements(ui, extension, file_path)
            for data_element in data_elements:
                if "data" in data_element:
                    if not "title" in data_element:
                        root, filename = os.path.split(file_path)
                        title, _ = os.path.splitext(filename)
                        data_element["title"] = title
                    data_element["filepath"] = file_path
                    data_item = create_data_item_from_data_element(data_element, file_path)
                    data_items.append(data_item)
        return data_items

    # return data
    def read_data_elements(self, ui, extension, file_path):
        return None

    def can_write(self, data_item, extension):
        return False

    def write(self, ui, data_item, path, extension):
        with open(path, 'wb') as f:
            self.write_file(data_item, extension, f)

    def write_file(self, data_item, extension, file):
        with data_item.data_ref() as data_ref:
            data = data_ref.data
        if data is not None:
            self.write_data(data, extension, file)

    def write_data(self, data, extension, file):
        pass


class ImportExportManager(object):
    __metaclass__ = Utility.Singleton
    """
        Tracks import/export plugins.
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
                if io_handler.can_write(data_item, string.lower(extension)):
                    writers.append(io_handler)
                    break  # from iterating extensions
        return writers

    # read file, return data items
    def read_data_items(self, ui, path):
        root, extension = os.path.splitext(path)
        if extension:
            extension = extension[1:]  # remove the leading "."
            extension = string.lower(extension)
            for io_handler in self.__io_handlers:
                if extension in io_handler.extensions:
                    return io_handler.read_data_items(ui, extension, path)
        return None

    # read file, return data elements
    def read_data_elements(self, ui, path):
        root, extension = os.path.splitext(path)
        if extension:
            extension = extension[1:]  # remove the leading "."
            extension = string.lower(extension)
            for io_handler in self.__io_handlers:
                if extension in io_handler.extensions:
                    return io_handler.read_data_elements(ui, extension, path)
        return None

    def write_data_items(self, ui, data_item, path):
        root, extension = os.path.splitext(path)
        if extension:
            extension = extension[1:]  # remove the leading "."
            extension = string.lower(extension)
            for io_handler in self.__io_handlers:
                if extension in io_handler.extensions and io_handler.can_write(data_item, extension):
                    io_handler.write(ui, data_item, path, extension)


# create a new data item with a data element.
# data element is a dict which can be processed into a data item
# when this method returns, the data item has not been added to a document. therefore, the
# data is still loaded into memory, but with a data ref count of zero.
def create_data_item_from_data_element(data_element, data_file_path=None):
    data_item = DataItem.DataItem()
    update_data_item_from_data_element(data_item, data_element, data_file_path)
    return data_item


# update an existing data item with a data element.
# data element is a dict which can be processed into a data item
# the existing data item may have a new size and dtype after returning.
def update_data_item_from_data_element(data_item, data_element, data_file_path=None):
    version = data_element["version"] if "version" in data_element else 1
    if version == 1:
        update_data_item_from_data_element_1(data_item, data_element, data_file_path)
    else:
        raise NotImplementedError("Data element version {:d} not supported.".format(version))

def update_data_item_from_data_element_1(data_item, data_element, data_file_path=None):
    with data_item.data_item_changes():
        # file path
        # master data
        if data_file_path is not None:
            data_item.source_file_path = data_file_path
        with data_item.data_ref() as data_ref:
            data = data_element["data"]
            sub_area = data_element.get("sub_area")
            data_matches = data_ref.master_data is not None and data.shape == data_ref.master_data.shape and data.dtype == data_ref.master_data.dtype
            if data_matches and data_ref.master_data is not None and sub_area is not None:
                top = sub_area[0][0]
                bottom = sub_area[0][0] + sub_area[1][0]
                left = sub_area[0][1]
                right = sub_area[0][1] + sub_area[1][1]
                data_ref.master_data[top:bottom, left:right] = data[top:bottom, left:right]
                data_ref.master_data = data_ref.master_data  # trigger change notifications, for lack of better mechanism
            else:
                data_ref.master_data = data
        # spatial calibrations
        if "spatial_calibrations" in data_element:
            spatial_calibrations = data_element.get("spatial_calibrations")
            if len(spatial_calibrations) == len(data_item.spatial_shape):
                for dimension, dimension_calibration in enumerate(spatial_calibrations):
                    origin = float(dimension_calibration["origin"])
                    scale = float(dimension_calibration["scale"])
                    units = unicode(dimension_calibration["units"])
                    if scale != 0.0:
                        data_item.set_spatial_calibration(dimension, Calibration.Calibration(origin, scale, units))
        if "intensity_calibration" in data_element:
            intensity_calibration = data_element.get("intensity_calibration")
            origin = float(intensity_calibration["origin"])
            scale = float(intensity_calibration["scale"])
            units = unicode(intensity_calibration["units"])
        # properties (general tags)
        if "properties" in data_element:
            with data_item.open_metadata("hardware_source") as metadata:
                metadata.update(clean_dict(data_element.get("properties")))
        # title
        if "title" in data_element:
            data_item.title = data_element["title"]
        # description
        # dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
        # time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
        # daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
        # time zone name is for display only and has no specified format
        # datetime.datetime.strptime(datetime.datetime.isoformat(datetime.datetime.now()), "%Y-%m-%dT%H:%M:%S.%f" )
        # datetime_modified, datetime_modified_tz, datetime_modified_dst, datetime_modified_tzname is the time at which this image was modified.
        # datetime_original, datetime_original_tz, datetime_original_dst, datetime_original_tzname is the time at which this image was created.
        def parse_datetime_keys(key, default=None):
            if key in data_element:
                datetime_element = data_element[key]
                datetime_item = dict()
                datetime_item["local_datetime"] = Utility.get_datetime_from_datetime_item(datetime_element).isoformat()
                if "tz" in datetime_element:
                    tz_match = re.compile("([-+])(\d{4})").match(datetime_element["tz"])
                    if tz_match:
                        datetime_item["tz"] = tz_match.group(0)
                if "dst" in datetime_element:
                    dst_match = re.compile("([-+])(\d{2})").match(datetime_element["dst"])
                    if dst_match:
                        datetime_item["dst"] = dst_match.group(0)
                if "tzname" in datetime_element:
                    datetime_item["tzname"] = datetime_element["tzname"]
                return datetime_item
            return default
        current_datetime_item = Utility.get_current_datetime_item()  # get this once to be consistent
        data_item.datetime_modified = parse_datetime_keys("datetime_modified", current_datetime_item)
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
        if "arrows" in data_element:
            for arrow_coordinates in data_element["arrows"]:
                start, end = arrow_coordinates
                spatial_shape = data_item.spatial_shape
                line_graphic = Graphics.LineGraphic()
                line_graphic.start = (float(start[0]) / spatial_shape[0], float(start[1]) / spatial_shape[1])
                line_graphic.end = (float(end[0]) / spatial_shape[0], float(end[1]) / spatial_shape[1])
                line_graphic.end_arrow_enabled = True
                data_item.displays[0].append_graphic(line_graphic)


def create_data_element_from_data_item(data_item, include_data=True):
    data_element = dict()
    data_element["version"] = 1
    data_element["reader_version"] = 1
    if include_data:
        with data_item.data_ref() as d:
            data_element["data"] = d.data
    calculated_calibrations = data_item.calculated_calibrations
    if calculated_calibrations is not None:
        calibrations_element = list()
        for calibration in calculated_calibrations:
            calibration_element = { "origin": calibration.origin, "scale": calibration.scale, "units": calibration.units }
            calibrations_element.append(calibration_element)
        data_element["spatial_calibrations"] = calibrations_element
    intensity_calibration = data_item.calculated_intensity_calibration
    if intensity_calibration is not None:
        intensity_calibration_element = { "origin": intensity_calibration.origin, "scale": intensity_calibration.scale, "units": intensity_calibration.units }
        data_element["intensity_calibration"] = calibration_element
    data_element["properties"] = dict(data_item.get_metadata("hardware_source"))
    data_element["title"] = data_item.title
    data_element["source_file_path"] = data_item.source_file_path
    data_element["datetime_modified"] = copy.deepcopy(data_item.datetime_modified)
    data_element["datetime_original"] = copy.deepcopy(data_item.datetime_original)
    data_element["uuid"] = str(data_item.uuid)
    data_inputs = data_item.data_inputs
    if len(data_inputs) == 1 and isinstance(data_inputs[0], DataItem.DataItem):
        data_element["data_source_uuid"] = str(data_inputs[0].uuid)
    # operations
    # graphics
    return data_element


class StandardImportExportHandler(ImportExportHandler):

    def __init__(self, name, extensions):
        super(StandardImportExportHandler, self).__init__(name, extensions)

    def read_data_elements(self, ui, extension, path):
        data = None
        try:
            data = Image.read_image_from_file(ui, path)
        except Exception:
            pass
        if data is not None:
            data_element = dict()
            data_element["version"] = 1
            data_element["data"] = data
            if os.path.exists(path) or path.startswith(":"):  # check for colon is for testing
                try:
                    file_datetime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
                except:
                    file_datetime = None
                if file_datetime is not None:
                    data_element["datetime_modified"] = Utility.get_datetime_item_from_datetime(file_datetime)
            return [data_element]
        return list()

    def can_write(self, data_item, extension):
        return len(data_item.spatial_shape) == 2

    def write(self, ui, data_item, path, extension):
        data = data_item.displays[0].preview_2d  # export the display rather than the data for these types
        if data is not None:
            ui.save_rgba_data_to_file(data, path, extension)


class CSVImportExportHandler(ImportExportHandler):

    def __init__(self, name, extensions):
        super(CSVImportExportHandler, self).__init__(name, extensions)

    def read_data_elements(self, ui, extension, path):
        data = numpy.loadtxt(path, delimiter=',')
        if data is not None:
            data_element = dict()
            data_element["data"] = data
            return [data_element]
        return list()

    def can_write(self, data_item, extension):
        return True

    def write(self, ui, data_item, path, extension):
        with data_item.data_ref() as data_ref:
            data = data_ref.data
        if data is not None:
            numpy.savetxt(path, data, delimiter=', ')


class NDataImportExportHandler(ImportExportHandler):

    def __init__(self, name, extensions):
        super(NDataImportExportHandler, self).__init__(name, extensions)

    def read_data_elements(self, ui, extension, path):
        zip_file = zipfile.ZipFile(path, 'r')
        namelist = zip_file.namelist()
        if "metadata.json" in namelist and "data.npy" in namelist:
            with zip_file.open("metadata.json") as fp:
                metadata = json.load(fp)
            with zip_file.open("data.npy") as fp:
                data_buffer = cStringIO.StringIO(fp.read())
                data = numpy.load(data_buffer)
        if data is not None:
            data_element = metadata
            data_element["data"] = data
            return [data_element]
        return list()

    def can_write(self, data_item, extension):
        return True

    def write(self, ui, data_item, path, extension):
        data_element = create_data_element_from_data_item(data_item, include_data=False)
        with data_item.data_ref() as data_ref:
            data = data_ref.data
        if data is not None:
            root, ext = os.path.splitext(path)
            metadata_path = root + "_metadata.json"
            data_path = root + "_data.npy"
            try:
                with open(metadata_path, "w") as fp:
                    json.dump(data_element, fp)
                numpy.save(data_path, data)
                zip_file = zipfile.ZipFile(path, 'w')
                zip_file.write(metadata_path, "metadata.json")
                zip_file.write(data_path, "data.npy")
            finally:
                os.remove(metadata_path)
                os.remove(data_path)


ImportExportManager().register_io_handler(StandardImportExportHandler("JPEG", ["jpg", "jpeg"]))
ImportExportManager().register_io_handler(StandardImportExportHandler("PNG", ["png"]))
ImportExportManager().register_io_handler(StandardImportExportHandler("TIFF", ["tif", "tiff"]))
ImportExportManager().register_io_handler(CSVImportExportHandler("CSV", ["csv"]))
ImportExportManager().register_io_handler(NDataImportExportHandler("NData", ["ndata1"]))
