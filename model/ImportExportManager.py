# standard libraries
import cStringIO
import datetime
import json
import os
import string
import zipfile

# third party libraries
import numpy

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.model import Image
from nion.swift.model import Operation
from nion.swift.model import Utility


class ImportExportIncompatibleDataError(Exception):
    pass


class ImportExportHandler(object):

    """
        A base class for implementing import/export handlers.

        :param name: the localized name for the handler; will appear in file dialogs
        :param extensions: the list of handled extensions; do not include leading dots
    """

    # Extensions should not include a period.
    def __init__(self, io_handler_id, name, extensions):
        self.io_handler_id = io_handler_id
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

    def can_write(self, data_and_calibration, extension):
        return False

    def write(self, ui, data_item, path, extension):
        with open(path, 'wb') as f:
            self.write_file(data_item, extension, f)

    def write_file(self, data_item, extension, file):
        data = data_item.maybe_data_source.data if data_item.maybe_data_source else None
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

    def get_writers(self):
        writers = []
        for io_handler in self.__io_handlers:
            if io_handler.can_read():
                writers.append(io_handler)
        return writers

    def get_writer_by_id(self, io_handler_id):
        for io_handler in self.__io_handlers:
            if io_handler.io_handler_id == io_handler_id:
                return io_handler
        return None

    def get_writers_for_data_item(self, data_item):
        writers = []
        if len(data_item.data_sources) > 0:
            data_and_calibration = data_item.data_sources[0].data_and_calibration
            for io_handler in self.__io_handlers:
                for extension in io_handler.extensions:
                    if io_handler.can_write(data_and_calibration, string.lower(extension)):
                        writers.append(io_handler)
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

    def write_data_items_with_writer(self, ui, writer, data_item, path):
        root, extension = os.path.splitext(path)
        if extension:
            extension = extension[1:]  # remove the leading "."
            extension = string.lower(extension)
            buffered_data_source = data_item.maybe_data_source
            if extension in writer.extensions and buffered_data_source and writer.can_write(buffered_data_source.data_and_calibration, extension):
                writer.write(ui, data_item, path, extension)

    def write_data_items(self, ui, data_item, path):
        root, extension = os.path.splitext(path)
        if extension:
            extension = extension[1:]  # remove the leading "."
            extension = string.lower(extension)
            for io_handler in self.__io_handlers:
                buffered_data_source = data_item.maybe_data_source
                if extension in io_handler.extensions and buffered_data_source and io_handler.can_write(buffered_data_source.data_and_calibration, extension):
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
    if len(data_item.data_sources) == 0:
        data_item.append_data_source(DataItem.BufferedDataSource())
    version = data_element["version"] if "version" in data_element else 1
    if version == 1:
        update_data_item_from_data_element_1(data_item, data_element, data_file_path)
    else:
        raise NotImplementedError("Data element version {:d} not supported.".format(version))

def update_data_item_from_data_element_1(data_item, data_element, data_file_path=None):
    # assumes that data item has a single buffered_data_source
    display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
    assert display_specifier.buffered_data_source and display_specifier.display
    with data_item.data_item_changes(), display_specifier.buffered_data_source._changes():
        # file path
        # master data
        if data_file_path is not None:
            data_item.source_file_path = data_file_path
        with display_specifier.buffered_data_source.data_ref() as data_ref:
            data = data_element["data"]
            sub_area = data_element.get("sub_area")
            if sub_area is not None:
                top = sub_area[0][0]
                bottom = sub_area[0][0] + sub_area[1][0]
                left = sub_area[0][1]
                right = sub_area[0][1] + sub_area[1][1]
                if top == 0 and left == 0 and bottom == data.shape[0] and right == data.shape[1]:
                    sub_area = None  # sub-area is specified, but specifies entire data
            data_matches = data_ref.master_data is not None and data.shape == data_ref.master_data.shape and data.dtype == data_ref.master_data.dtype
            if data_matches:
                if sub_area is not None:
                    data_ref.master_data[top:bottom, left:right] = data[top:bottom, left:right]
                else:
                    data_ref.master_data[:] = data[:]
                data_ref.data_updated()  # trigger change notifications
            else:
                data_ref.master_data = data.copy()
        # spatial calibrations
        if "spatial_calibrations" in data_element:
            dimensional_calibrations = data_element.get("spatial_calibrations")
            if len(dimensional_calibrations) == len(display_specifier.buffered_data_source.dimensional_shape):
                for dimension, dimension_calibration in enumerate(dimensional_calibrations):
                    offset = float(dimension_calibration.get("offset", 0.0))
                    scale = float(dimension_calibration.get("scale", 1.0))
                    units = unicode(dimension_calibration.get("units", ""))
                    if scale != 0.0:
                        display_specifier.buffered_data_source.set_dimensional_calibration(dimension, Calibration.Calibration(offset, scale, units))
        if "intensity_calibration" in data_element:
            intensity_calibration = data_element.get("intensity_calibration")
            offset = float(intensity_calibration.get("offset", 0.0))
            scale = float(intensity_calibration.get("scale", 1.0))
            units = unicode(intensity_calibration.get("units", ""))
            if scale != 0.0:
                display_specifier.buffered_data_source.set_intensity_calibration(Calibration.Calibration(offset, scale, units))
        # properties (general tags)
        if "properties" in data_element:
            buffered_data_source = data_item.maybe_data_source
            if buffered_data_source:
                metadata = buffered_data_source.metadata
                hardware_source_metadata = metadata.setdefault("hardware_source", dict())
                hardware_source_metadata.update(Utility.clean_dict(data_element.get("properties")))
                buffered_data_source.set_metadata(metadata)
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
        datetime_item = data_element.get("datetime_modified")
        if not datetime_item:
            datetime_item = Utility.get_datetime_item_from_datetime(datetime.datetime.now())
        if datetime_item:
            dst_value = datetime_item.get("dst", "+00")
            tz_value = datetime_item.get("tz", "+0000")
            time_zone = { "dst": dst_value, "tz": tz_value}
            dst_adjust = int(dst_value)
            tz_adjust = int(tz_value[0:3]) * 60 + int(tz_value[3:5]) * (-1 if tz_value[0] == '-1' else 1)
            local_datetime = Utility.get_datetime_from_datetime_item(datetime_item)
            utc_datetime = local_datetime - datetime.timedelta(minutes=dst_adjust + tz_adjust)
            data_item.created = utc_datetime
            buffered_data_source = data_item.maybe_data_source
            if buffered_data_source:
                buffered_data_source.created = utc_datetime
            metadata = data_item.metadata
            metadata.setdefault("description", dict())["time_zone"] = time_zone
            data_item.set_metadata(metadata)
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
                dimensional_shape = display_specifier.buffered_data_source.dimensional_shape
                line_graphic = Graphics.LineGraphic()
                line_graphic.start = (float(start[0]) / dimensional_shape[0], float(start[1]) / dimensional_shape[1])
                line_graphic.end = (float(end[0]) / dimensional_shape[0], float(end[1]) / dimensional_shape[1])
                line_graphic.end_arrow_enabled = True
                display_specifier.display.append_graphic(line_graphic)


def create_data_element_from_data_item(data_item, include_data=True):
    data_element = dict()
    data_element["version"] = 1
    data_element["reader_version"] = 1
    buffered_data_source = data_item.maybe_data_source
    if buffered_data_source:
        if include_data:
            data_element["data"] = buffered_data_source.data
        dimensional_calibrations = buffered_data_source.dimensional_calibrations
        if dimensional_calibrations is not None:
            calibrations_element = list()
            for calibration in dimensional_calibrations:
                calibration_element = { "offset": calibration.offset, "scale": calibration.scale, "units": calibration.units }
                calibrations_element.append(calibration_element)
            data_element["spatial_calibrations"] = calibrations_element
        intensity_calibration = buffered_data_source.intensity_calibration
        if intensity_calibration is not None:
            intensity_calibration_element = { "offset": intensity_calibration.offset, "scale": intensity_calibration.scale, "units": intensity_calibration.units }
            data_element["intensity_calibration"] = intensity_calibration_element
        data_element["properties"] = dict(buffered_data_source.metadata.get("hardware_source", dict()))
        data_element["title"] = data_item.title
        data_element["source_file_path"] = data_item.source_file_path
        data_element["datetime_modified"] = Utility.get_datetime_item_from_utc_datetime(data_item.created)
        data_element["datetime_original"] = Utility.get_datetime_item_from_utc_datetime(data_item.created)
        data_element["uuid"] = str(data_item.uuid)
        # operation
        # graphics
    return data_element


class StandardImportExportHandler(ImportExportHandler):

    def __init__(self, io_handler_id, name, extensions):
        super(StandardImportExportHandler, self).__init__(io_handler_id, name, extensions)

    def read_data_elements(self, ui, extension, path):
        data = None
        try:
            data = Image.read_image_from_file(ui, path)
        except Exception as e:
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

    def can_write(self, data_and_calibration, extension):
        return len(data_and_calibration.dimensional_shape) == 2

    def write(self, ui, data_item, path, extension):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        data = display_specifier.display.preview_2d  # export the display rather than the data for these types
        if data is not None:
            ui.save_rgba_data_to_file(data, path, extension)


class CSVImportExportHandler(ImportExportHandler):

    def __init__(self, io_handler_id, name, extensions):
        super(CSVImportExportHandler, self).__init__(io_handler_id, name, extensions)

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
        data = data_item.maybe_data_source.data if data_item.maybe_data_source else None
        if data is not None:
            numpy.savetxt(path, data, delimiter=', ')


class NDataImportExportHandler(ImportExportHandler):

    def __init__(self, io_handler_id, name, extensions):
        super(NDataImportExportHandler, self).__init__(io_handler_id, name, extensions)

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

    def can_write(self, data_and_calibration, extension):
        return True

    def write(self, ui, data_item, path, extension):
        data_element = create_data_element_from_data_item(data_item, include_data=False)
        data = data_item.maybe_data_source.data if data_item.maybe_data_source else None
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


ImportExportManager().register_io_handler(StandardImportExportHandler("jpeg-io-handler", "JPEG", ["jpg", "jpeg"]))
ImportExportManager().register_io_handler(StandardImportExportHandler("png-io-handler", "PNG", ["png"]))
#ImportExportManager().register_io_handler(StandardImportExportHandler("tiff-io-handler", "TIFF", ["tif", "tiff"]))
ImportExportManager().register_io_handler(CSVImportExportHandler("csv-io-handler", "CSV", ["csv"]))
ImportExportManager().register_io_handler(NDataImportExportHandler("ndata1-io-handler", "NData 1", ["ndata1"]))
