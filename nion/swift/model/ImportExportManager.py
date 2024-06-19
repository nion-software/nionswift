# standard libraries
import copy
import datetime
import io
import json
import os
import pathlib
import typing
import uuid
import zipfile
import itertools

# third party libraries
import imageio.v3 as imageio
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import Utility
from nion.utils import DateTime


DataElementType = typing.Dict[str, typing.Any]
_DataArrayType = numpy.typing.NDArray[typing.Any]


class ImportExportIncompatibleDataError(Exception):
    pass


class ImportExportHandler:

    """
        A base class for implementing import/export handlers.

        :param name: the localized name for the handler; will appear in file dialogs
        :param extensions: the list of handled extensions; do not include leading dots
    """

    # Extensions should not include a period.
    def __init__(self, io_handler_id: str, name: str, extensions: typing.Sequence[str]) -> None:
        self.io_handler_id = io_handler_id
        self.name = name
        self.extensions = list(extensions)
        self.supports_composite_data = False

    def can_read(self) -> bool:
        return True

    # return data items
    def read_data_items(self, extension: str, file_path: pathlib.Path) -> typing.Sequence[DataItem.DataItem]:
        data_items: typing.List[DataItem.DataItem] = list()
        if file_path.exists() or str(file_path.parent).startswith(":"):
            data_items.extend(self._read_data_items(extension, file_path))
        return data_items

    def _read_data_items(self, extension: str, file_path: pathlib.Path) -> typing.Sequence[DataItem.DataItem]:
        data_items = list()
        data_elements = self.read_data_elements(extension, file_path)
        for data_element in data_elements:
            if "data" in data_element:
                if not "title" in data_element:
                    title = file_path.stem
                    data_element["title"] = title
                data_element["filepath"] = file_path
                data_item = create_data_item_from_data_element(data_element, file_path)
                data_items.append(data_item)
        return data_items

    # return data
    def read_data_elements(self, extension: str, path: pathlib.Path) -> typing.Sequence[DataElementType]:
        return list()

    def can_write(self, data_metadata: DataAndMetadata.DataMetadata, extension: str) -> bool:
        return False

    def write_display_item(self, display_item: DisplayItem.DisplayItem, path: pathlib.Path, extension: str) -> None:
        data_item = display_item.data_item
        assert data_item
        with open(path, 'wb') as f:
            data = data_item.data
            if data is not None:
                self.write_data(data, extension, f)

    def write_data(self, data: _DataArrayType, extension: str, file: typing.BinaryIO) -> None:
        pass


class ImportExportManager(metaclass=Utility.Singleton):
    """
        Tracks import/export plugins.
    """
    def __init__(self) -> None:
        # we store a of dicts dicts containing extensions,
        # load_func, save_func, keyed by name.
        self.__io_handlers: typing.List[ImportExportHandler] = []

    def register_io_handler(self, io_handler: ImportExportHandler) -> None:
        self.__io_handlers.append(io_handler)

    def unregister_io_handler(self, io_handler: ImportExportHandler) -> None:
        self.__io_handlers.remove(io_handler)

    def get_readers(self) -> typing.Sequence[ImportExportHandler]:
        readers = []
        for io_handler in self.__io_handlers:
            if io_handler.can_read():
                readers.append(io_handler)
        return readers

    def get_writers(self) -> typing.Sequence[ImportExportHandler]:
        writers = []
        for io_handler in self.__io_handlers:
            if io_handler.can_read():
                writers.append(io_handler)
        return writers

    def get_writer_by_id(self, io_handler_id: str) -> typing.Optional[ImportExportHandler]:
        for io_handler in self.__io_handlers:
            if io_handler.io_handler_id == io_handler_id:
                return io_handler
        return None

    def get_writers_for_data_item(self, data_item: DataItem.DataItem) -> typing.Sequence[ImportExportHandler]:
        writers = []
        data_metadata = data_item.data_metadata
        if data_metadata:
            for io_handler in self.__io_handlers:
                for extension in io_handler.extensions:
                    if io_handler.can_write(data_metadata, extension.lower()):
                        writers.append(io_handler)
        return writers

    def get_writers_for_display_item(self, display_item: DisplayItem.DisplayItem) -> typing.Sequence[ImportExportHandler]:
        writers = self.get_writers_for_data_item(display_item.data_items[0]) if display_item.data_items else list()
        if len(display_item.data_items) > 1:
            composite_writers = list()
            for writer in writers:
                if writer.supports_composite_data:
                    composite_writers.append(writer)
            writers = composite_writers
        return writers

    # read file, return data items
    def read_data_items(self, path: pathlib.Path) -> typing.Sequence[DataItem.DataItem]:
        root, extension = os.path.splitext(path)
        if extension:
            extension = extension[1:]  # remove the leading "."
            extension = extension.lower()
            for io_handler in self.__io_handlers:
                if extension in io_handler.extensions:
                    return io_handler.read_data_items(extension, path)
        return list()

    # read file, return data elements
    def read_data_elements(self, path: pathlib.Path) -> typing.Sequence[DataElementType]:
        root, extension = os.path.splitext(path)
        if extension:
            extension = extension[1:]  # remove the leading "."
            extension = extension.lower()
            for io_handler in self.__io_handlers:
                if extension in io_handler.extensions:
                    return io_handler.read_data_elements(extension, path)
        return list()

    def write_display_item_with_writer(self, writer: ImportExportHandler, display_item: DisplayItem.DisplayItem, path: pathlib.Path) -> None:
        extension = path.suffix
        if extension:
            extension = extension[1:]  # remove the leading "."
            extension = extension.lower()
            data_metadata = display_item.data_items[0].data_metadata if display_item.data_items else None
            if extension in writer.extensions and data_metadata and writer.can_write(data_metadata, extension):
                writer.write_display_item(display_item, path, extension)

    def write_display_item(self, display_item: DisplayItem.DisplayItem, path: pathlib.Path) -> None:
        extension = path.suffix
        if extension:
            extension = extension[1:]  # remove the leading "."
            extension = extension.lower()
            for io_handler in self.__io_handlers:
                data_item = display_item.data_item
                assert data_item
                data_metadata = data_item.data_metadata
                if extension in io_handler.extensions and data_metadata and io_handler.can_write(data_metadata, extension):
                    io_handler.write_display_item(display_item, path, extension)


# create a new data item with a data element.
# data element is a dict which can be processed into a data item
# when this method returns, the data item has not been added to a document. therefore, the
# data is still loaded into memory, but with a data ref count of zero.
def create_data_item_from_data_element(data_element: DataElementType,
                                       data_file_path: typing.Optional[pathlib.Path] = None) -> DataItem.DataItem:
    uuid_str = data_element.get("uuid")
    uuid_ = uuid.UUID(uuid_str) if uuid_str else None
    large_format = data_element.get("large_format")
    if large_format is None:
        data = data_element.get("data")
        large_format = len(data.shape) > 2 and data.dtype != numpy.uint8 if data is not None else False
    data_item = DataItem.DataItem(item_uuid=uuid_, large_format=large_format)
    update_data_item_from_data_element(data_item, data_element, data_file_path)
    return data_item


# update an existing data item with a data element.
# data element is a dict which can be processed into a data item
# the existing data item may have a new size and dtype after returning.
def update_data_item_from_data_element(data_item: DataItem.DataItem, data_element: DataElementType,
                                       data_file_path: typing.Optional[pathlib.Path] = None) -> None:
    version = data_element["version"] if "version" in data_element else 1
    if version == 1:
        update_data_item_from_data_element_1(data_item, data_element, data_file_path)
    else:
        raise NotImplementedError("Data element version {:d} not supported.".format(version))


def update_data_item_from_data_element_1(data_item: DataItem.DataItem, data_element: DataElementType,
                                         data_file_path: typing.Optional[pathlib.Path] = None) -> None:
    assert data_item
    with data_item.data_item_changes(), data_item.data_source_changes():
        # file path
        # master data
        if data_file_path is not None:
            data_item.source_file_path = data_file_path
        data_and_metadata = convert_data_element_to_data_and_metadata(data_element)
        dimensional_calibrations = data_and_metadata.dimensional_calibrations
        intensity_calibration = data_and_metadata.intensity_calibration
        is_sequence = data_and_metadata.is_sequence
        collection_dimension_count = data_and_metadata.collection_dimension_count
        datum_dimension_count = data_and_metadata.datum_dimension_count
        data_shape_data_dtype = data_and_metadata.data_shape_and_dtype
        assert data_shape_data_dtype is not None
        is_same_shape = data_item.data_shape == data_shape_data_dtype[0] and data_item.data_dtype == data_shape_data_dtype[1] and data_item.is_sequence == is_sequence and data_item.collection_dimension_count == collection_dimension_count and data_item.datum_dimension_count == datum_dimension_count
        if is_same_shape:
            data_element_data = data_and_metadata.data
            assert data_element_data is not None
            with data_item.data_ref() as data_ref:
                sub_area = data_element.get("sub_area")
                data = data_ref.data
                if data is not None:
                    if sub_area is not None:
                        top = sub_area[0][0]
                        bottom = sub_area[0][0] + sub_area[1][0]
                        left = sub_area[0][1]
                        right = sub_area[0][1] + sub_area[1][1]
                        data[top:bottom, left:right] = data_element_data[top:bottom, left:right]
                    else:
                        data[:] = data_element_data[:]
                data_ref.data_updated()  # trigger change notifications
            if dimensional_calibrations is not None:
                for dimension, dimensional_calibration in enumerate(dimensional_calibrations):
                    data_item.set_dimensional_calibration(dimension, dimensional_calibration)
            if intensity_calibration:
                data_item.set_intensity_calibration(intensity_calibration)
            data_item.metadata = data_and_metadata.metadata
        else:
            data_item.set_xdata(data_and_metadata)
        # title
        if "title" in data_element:
            data_item.title = data_element["title"]
        # description
        # dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
        # time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
        # daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
        # timezone is for conversion and is the Olson timezone string.
        # datetime.datetime.strptime(datetime.datetime.isoformat(datetime.datetime.now()), "%Y-%m-%dT%H:%M:%S.%f" )
        # datetime_modified, datetime_modified_tz, datetime_modified_dst, datetime_modified_tzname is the time at which this image was modified.
        # datetime_original, datetime_original_tz, datetime_original_dst, datetime_original_tzname is the time at which this image was created.
        utc_datetime = data_and_metadata.timestamp
        data_item.created = utc_datetime
        if "time_zone" in data_and_metadata.metadata.get("description", dict()):
            timezone_dict = copy.deepcopy(data_and_metadata.metadata["description"]["time_zone"])
            timezone = timezone_dict.get("timezone")
            if timezone is not None:
                data_item.timezone = timezone
            timezone_offset = timezone_dict.get("tz")
            if timezone_offset is not None:
                data_item.timezone_offset = timezone_offset
        # author
        # sample
        # facility
        # location
        # gps
        # instrument
        # copyright
        # exposure
        # extra_high_tension


def convert_data_element_to_data_and_metadata(data_element: DataElementType) -> DataAndMetadata.DataAndMetadata:
    # NOTE: takes ownership of data_element['data']
    version = data_element["version"] if "version" in data_element else 1
    if version == 1:
        return convert_data_element_to_data_and_metadata_1(data_element)
    else:
        raise NotImplementedError("Data element version {:d} not supported.".format(version))


def convert_data_element_to_data_and_metadata_1(data_element: DataElementType) -> DataAndMetadata.DataAndMetadata:
    """Convert a data element to xdata. No data copying occurs.

    The data element can have the following keys:
        data (required)
        is_sequence, collection_dimension_count, datum_dimension_count (optional description of the data)
        spatial_calibrations (optional list of spatial calibration dicts, scale, offset, units)
        intensity_calibration (optional intensity calibration dict, scale, offset, units)
        metadata (optional)
        properties (get stored into metadata.hardware_source)
        one of either timestamp or datetime_modified
        if datetime_modified (dst, tz) it is converted and used as timestamp
            then timezone gets stored into metadata.description.timezone.
    """
    # data. takes ownership.
    data = data_element["data"]
    dimensional_shape = Image.dimensional_shape_from_data(data)
    is_sequence = data_element.get("is_sequence", False)
    dimension_count = len(dimensional_shape) if dimensional_shape else 0
    adjusted_dimension_count = dimension_count - (1 if is_sequence else 0)
    collection_dimension_count = data_element.get("collection_dimension_count", 2 if adjusted_dimension_count in (3, 4) else 0)
    datum_dimension_count = data_element.get("datum_dimension_count", adjusted_dimension_count - collection_dimension_count)
    data_descriptor = DataAndMetadata.DataDescriptor(is_sequence, collection_dimension_count, datum_dimension_count)

    # dimensional calibrations
    dimensional_calibrations = None
    if "spatial_calibrations" in data_element:
        dimensional_calibrations_list = typing.cast(typing.List[typing.Any], data_element.get("spatial_calibrations"))
        if len(dimensional_calibrations_list) == dimension_count:
            dimensional_calibrations = list()
            for dimension_calibration in dimensional_calibrations_list:
                offset = float(dimension_calibration.get("offset", 0.0))
                scale = float(dimension_calibration.get("scale", 1.0))
                units = dimension_calibration.get("units", "")
                units = str(units) if units is not None else str()
                if scale != 0.0:
                    dimensional_calibrations.append(Calibration.Calibration(offset, scale, units))
                else:
                    dimensional_calibrations.append(Calibration.Calibration())

    # intensity calibration
    intensity_calibration = None
    if "intensity_calibration" in data_element:
        intensity_calibration_dict = typing.cast(typing.Dict[str, typing.Any], data_element.get("intensity_calibration"))
        offset = float(intensity_calibration_dict.get("offset", 0.0))
        scale = float(intensity_calibration_dict.get("scale", 1.0))
        units = intensity_calibration_dict.get("units", "")
        units = str(units) if units is not None else str()
        if scale != 0.0:
            intensity_calibration = Calibration.Calibration(offset, scale, units)

    # properties (general tags)
    metadata: typing.Dict[str, typing.Any] = dict()
    if "metadata" in data_element:
        metadata.update(Utility.clean_dict(typing.cast(typing.Dict[str, typing.Any], data_element.get("metadata"))))
    if "properties" in data_element and data_element["properties"]:
        hardware_source_metadata = metadata.setdefault("hardware_source", dict())
        hardware_source_metadata.update(Utility.clean_dict(typing.cast(typing.Dict[str, typing.Any], data_element.get("properties"))))

    # dates are _local_ time and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
    # time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
    # daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
    # timezone is for conversion and is the Olson timezone string.
    # datetime.datetime.strptime(datetime.datetime.isoformat(datetime.datetime.now()), "%Y-%m-%dT%H:%M:%S.%f" )
    # datetime_modified, datetime_modified_tz, datetime_modified_dst, datetime_modified_tzname is the time at which this image was modified.
    # datetime_original, datetime_original_tz, datetime_original_dst, datetime_original_tzname is the time at which this image was created.
    timestamp = data_element.get("timestamp", DateTime.utcnow())
    datetime_item = data_element.get("datetime_modified", Utility.get_datetime_item_from_utc_datetime(timestamp))

    local_datetime = Utility.get_datetime_from_datetime_item(datetime_item)
    assert local_datetime
    dst_value = datetime_item.get("dst", "+00")
    tz_value = datetime_item.get("tz", "+0000")
    timezone = datetime_item.get("timezone")
    time_zone = { "dst": dst_value, "tz": tz_value}
    if timezone is not None:
        time_zone["timezone"] = timezone
    # note: dst is informational only; tz already include dst
    tz_adjust = (int(tz_value[1:3]) * 60 + int(tz_value[3:5])) * (-1 if tz_value[0] == '-' else 1)
    utc_datetime = local_datetime - datetime.timedelta(minutes=tz_adjust)  # tz_adjust already contains dst_adjust
    timestamp = utc_datetime

    return DataAndMetadata.new_data_and_metadata(data,
                                                 intensity_calibration=intensity_calibration,
                                                 dimensional_calibrations=dimensional_calibrations,
                                                 metadata=metadata,
                                                 timestamp=timestamp,
                                                 data_descriptor=data_descriptor,
                                                 timezone=timezone,
                                                 timezone_offset=tz_value)


def create_data_element_from_data_item(data_item: DataItem.DataItem, include_data: bool = True) -> DataElementType:
    data_element: DataElementType = dict()
    data_element["version"] = 1
    data_element["reader_version"] = 1
    if data_item.has_data:
        data_element["large_format"] = bool(data_item.large_format)
        if include_data:
            data_element["data"] = data_item.data
        dimensional_calibrations = data_item.dimensional_calibrations
        if dimensional_calibrations is not None:
            calibrations_element = list()
            for calibration in dimensional_calibrations:
                calibration_element = { "offset": calibration.offset, "scale": calibration.scale, "units": calibration.units }
                calibrations_element.append(calibration_element)
            data_element["spatial_calibrations"] = calibrations_element
        intensity_calibration = data_item.intensity_calibration
        if intensity_calibration is not None:
            intensity_calibration_element = { "offset": intensity_calibration.offset, "scale": intensity_calibration.scale, "units": intensity_calibration.units }
            data_element["intensity_calibration"] = intensity_calibration_element
        if data_item.is_sequence:
            data_element["is_sequence"] = data_item.is_sequence
        data_element["collection_dimension_count"] = data_item.collection_dimension_count
        data_element["datum_dimension_count"] = data_item.datum_dimension_count
        data_item_metadata = data_item.metadata or dict()
        data_element["metadata"] = copy.deepcopy(data_item_metadata)
        data_element["properties"] = copy.deepcopy(data_item_metadata.get("hardware_source", dict()))
        data_element["title"] = data_item.title
        data_element["source_file_path"] = data_item.source_file_path.as_posix() if data_item.source_file_path else None
        tz_value = data_item.timezone_offset
        timezone = data_item.timezone
        dst_minutes = None
        time_zone_dict = data_item_metadata.get("description", dict()).get("time_zone")
        if time_zone_dict:
            # note: dst is informational only; tz already include dst
            if tz_value is None:
                tz_value = time_zone_dict["tz"]
            dst_minutes = int(time_zone_dict["dst"])
            if timezone is None:
                timezone = time_zone_dict.get("timezone")
        tz_minutes: typing.Optional[int]
        if tz_value is not None:
            tz_minutes = (int(tz_value[1:3]) * 60 + int(tz_value[3:5])) * (-1 if tz_value[0] == '-' else 1)
        else:
            tz_minutes = None
        data_element["datetime_modified"] = Utility.get_datetime_item_from_utc_datetime(data_item.created, tz_minutes, dst_minutes, timezone)
        data_element["datetime_original"] = Utility.get_datetime_item_from_utc_datetime(data_item.created, tz_minutes, dst_minutes, timezone)
        data_element["uuid"] = str(data_item.uuid)
        # operation
        # graphics
    return data_element


def create_data_element_from_extended_data(xdata: DataAndMetadata.DataAndMetadata) -> DataElementType:
    data_element: DataElementType = dict()
    data_element["version"] = 1
    data_element["reader_version"] = 1
    data_element["data"] = xdata.data
    data_element["large_format"] = len(xdata.dimensional_shape) > 2
    dimensional_calibrations = xdata.dimensional_calibrations
    calibrations_element = list()
    for calibration in dimensional_calibrations:
        calibration_element = { "offset": calibration.offset, "scale": calibration.scale, "units": calibration.units }
        calibrations_element.append(calibration_element)
    data_element["spatial_calibrations"] = calibrations_element
    intensity_calibration = xdata.intensity_calibration
    intensity_calibration_element = { "offset": intensity_calibration.offset, "scale": intensity_calibration.scale, "units": intensity_calibration.units }
    data_element["intensity_calibration"] = intensity_calibration_element
    if xdata.is_sequence:
        data_element["is_sequence"] = xdata.is_sequence
    data_element["collection_dimension_count"] = xdata.collection_dimension_count
    data_element["datum_dimension_count"] = xdata.datum_dimension_count
    data_element["metadata"] = xdata.metadata
    # properties are redundant; but here for backwards compatibility
    data_element["properties"] = xdata.metadata.get("hardware_source", dict())
    tz_minutes = None
    dst_minutes = None
    timezone = None
    time_zone_dict = xdata.metadata.get("description", dict()).get("time_zone")
    if time_zone_dict:
        # note: dst is informational only; tz already include dst
        tz_value = time_zone_dict["tz"]
        tz_minutes = (int(tz_value[1:3]) * 60 + int(tz_value[3:5])) * (-1 if tz_value[0] == '-' else 1)
        dst_minutes = int(time_zone_dict["dst"])
        timezone = time_zone_dict.get("timezone")
    data_element["datetime_modified"] = Utility.get_datetime_item_from_utc_datetime(xdata.timestamp, tz_minutes, dst_minutes, timezone)
    data_element["datetime_original"] = Utility.get_datetime_item_from_utc_datetime(xdata.timestamp, tz_minutes, dst_minutes, timezone)
    return data_element


# return True if data is grayscale.
def is_grayscale(data: _DataArrayType) -> bool:
    if Image.is_data_rgb(data) or Image.is_data_rgba(data):
        return numpy.array_equal(data[..., 0],data[..., 1]) and numpy.array_equal(data[..., 1],data[..., 2])
    return True


# based roughly on https://github.com/imageio/imageio/blob/896aa50c1797c3642149aa3110547d85190017db/imageio/core/util.py#L45
def convert_to_uint8(d: _DataArrayType) -> numpy.typing.NDArray[numpy.uint8]:
    if d.dtype == numpy.dtype(numpy.uint8):
        return d
    # check the int types first.
    if d.dtype == numpy.dtype(numpy.uint16):
        return typing.cast(numpy.typing.NDArray[numpy.uint8], numpy.right_shift(d, 8).astype(numpy.uint8))
    elif d.dtype == numpy.dtype(numpy.uint32):
        return typing.cast(numpy.typing.NDArray[numpy.uint8], numpy.right_shift(d, 24).astype(numpy.uint8))
    elif d.dtype == numpy.dtype(numpy.uint64):
        return typing.cast(numpy.typing.NDArray[numpy.uint8], numpy.right_shift(d, 56).astype(numpy.uint8))
    # now check float type
    mn, mx = numpy.nanmin(d), numpy.nanmax(d)
    if str(d.dtype).startswith("float") and mn >= 0 and mx <= 1:
        return typing.cast(numpy.typing.NDArray[numpy.uint8], numpy.round(d.astype(numpy.float64) * 255).astype(numpy.uint8))
    elif numpy.isfinite(mn) and numpy.isfinite(mx) and mn != mx:
        return typing.cast(numpy.typing.NDArray[numpy.uint8], numpy.round((d.astype(d.astype(numpy.float64)) - mn) / (mx - mn) * 255).astype(numpy.uint8))
    else:
        return d.astype(numpy.uint8)

# read image file. convert to dtype if it is grayscale.
def read_image_from_file(filename: pathlib.Path) -> _DataArrayType:
    if str(filename).startswith(":"):
        return numpy.zeros((20, 20, 4), numpy.uint8)
    # TODO: fix typing when imageio gets their numpy typing correct.
    image = imageio.imread(filename, index=0)
    if image is not None:
        image_u8 = convert_to_uint8(image)
        if len(image_u8.shape) == 3:
            rgba_image: numpy.typing.NDArray[numpy.uint8]
            if image_u8.shape[-1] == 3:
                rgba_image = numpy.empty(image_u8.shape[:-1] + (4,), numpy.uint8)
                rgba_image[..., 0] = image_u8[..., 2]
                rgba_image[..., 1] = image_u8[..., 1]
                rgba_image[..., 2] = image_u8[..., 0]
                rgba_image[..., 3] = 255
            else:
                assert image_u8.shape[-1] == 4
                rgba_image = numpy.empty(image_u8.shape[:-1] + (4,), numpy.uint8)
                rgba_image[..., 0] = image_u8[..., 2]
                rgba_image[..., 1] = image_u8[..., 1]
                rgba_image[..., 2] = image_u8[..., 0]
                rgba_image[..., 3] = image_u8[..., 3]
            if is_grayscale(rgba_image):
                rgba_image = Image.convert_to_grayscale(rgba_image)
        else:
            assert len(image_u8.shape) == 2
            rgba_image = image_u8
        assert rgba_image is not None
        return rgba_image
    raise IOError()


class StandardImportExportHandler(ImportExportHandler):

    def __init__(self, io_handler_id: str, name: str, extensions: typing.Sequence[str]) -> None:
        super().__init__(io_handler_id, name, extensions)

    def read_data_elements(self, extension: str, path: pathlib.Path) -> typing.List[DataElementType]:
        data = None
        try:
            data = read_image_from_file(path)
        except Exception as e:
            print(e)
        if data is not None:
            data_element: DataElementType = dict()
            data_element["version"] = 1
            data_element["data"] = data
            if path.exists():
                try:
                    file_datetime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
                    data_element["datetime_modified"] = Utility.get_datetime_item_from_datetime(file_datetime)
                except Exception:
                    pass
            return [data_element]
        return list()

    def can_write(self, data_metadata: DataAndMetadata.DataMetadata, extension: str) -> bool:
        return len(data_metadata.dimensional_shape) == 2

    def write_display_item(self, display_item: DisplayItem.DisplayItem, path: pathlib.Path, extension: str) -> None:
        display_data_channel = display_item.display_data_channel
        assert display_data_channel
        display_values = display_data_channel.get_latest_computed_display_values()
        assert display_values
        data = display_values.display_rgba  # export the display rather than the data for these types
        assert data is not None
        # TODO: fix typing when imageio gets their numpy typing correct.
        imageio.imwrite(path, Image.get_rgb_view(data), extension="." + extension)


class CSVImportExportHandler(ImportExportHandler):

    def __init__(self, io_handler_id: str, name: str, extensions: typing.Sequence[str]) -> None:
        super().__init__(io_handler_id, name, extensions)

    def read_data_elements(self, extension: str, path: pathlib.Path) -> typing.List[DataElementType]:
        data = numpy.loadtxt(str(path), delimiter=',')
        if data is not None:
            data_element: DataElementType = dict()
            data_element["data"] = data
            return [data_element]
        return list()

    def can_write(self, data_metadata: DataAndMetadata.DataMetadata, extension: str) -> bool:
        return 0 < len(data_metadata.dimensional_shape) <= 2

    def write_display_item(self, display_item: DisplayItem.DisplayItem, path: pathlib.Path, extension: str) -> None:
        data_item = display_item.data_item
        assert data_item
        assert data_item.data_metadata
        data = data_item.data
        if data is not None and self.can_write(data_item.data_metadata, 'csv'):
            numpy.savetxt(path, data, delimiter=', ')


def build_table(display_item: DisplayItem.DisplayItem) -> typing.Tuple[typing.List[str], typing.List[_DataArrayType]]:
    data_items = display_item.data_items
    assert all([data_item.is_data_1d for data_item in data_items])

    def make_x_data(calibration: Calibration.Calibration, length: int) -> _DataArrayType:
        return numpy.linspace(calibration.offset, calibration.offset + (length - 1) * calibration.scale, length)

    xdata0 = data_items[0].xdata
    calibration0 = xdata0.dimensional_calibrations[0] if xdata0 else Calibration.Calibration()
    if all([calibration0 == (data_item.xdata.dimensional_calibrations[0] if data_item.xdata else Calibration.Calibration()) for data_item in data_items]):
        length = max([data_item.xdata.data_shape[0] if data_item.xdata else 0 for data_item in data_items])
        data_list = [make_x_data(calibration0, length)]
        headers = [f"X ({calibration0.units or 'pixel'})"]
        for index in range(len(display_item.display_layers)):
            display_data_channel = display_item.get_display_layer_display_data_channel(index)
            assert display_data_channel
            display_values = display_data_channel.get_latest_computed_display_values()
            assert display_values
            xdata = display_values.display_data_and_metadata
            assert xdata
            data = xdata.data
            assert data is not None
            data_list.append(xdata.intensity_calibration.convert_array_to_calibrated_value(data))
            label = display_item.get_display_layer_property(index, "label") or f"Data {index}"
            label = label + f" ({xdata.intensity_calibration.units or 'None'})"
            headers.append(label)
    else:
        data_list = list()
        headers = list()
        for index in range(len(display_item.display_layers)):
            display_data_channel = display_item.get_display_layer_display_data_channel(index)
            assert display_data_channel
            display_values = display_data_channel.get_latest_computed_display_values()
            assert display_values
            xdata = display_values.display_data_and_metadata
            assert xdata
            data = xdata.data
            assert data is not None
            data_list.append(make_x_data(xdata.dimensional_calibrations[0], xdata.data_shape[0]))
            data_list.append(xdata.intensity_calibration.convert_array_to_calibrated_value(data))
            label = display_item.get_display_layer_property(index, "label") or f"Data {index}"
            x_label = "X " + label + f" ({xdata.dimensional_calibrations[0].units or 'pixel'})"
            y_label = "Y " + label + f" ({xdata.intensity_calibration.units or 'None'})"
            headers.append(x_label)
            headers.append(y_label)

    return headers, data_list


class CSV1ImportExportHandler(ImportExportHandler):

    def __init__(self, io_handler_id: str, name: str, extensions: typing.Sequence[str]) -> None:
        super().__init__(io_handler_id, name, extensions)
        self.supports_composite_data = True

    def read_data_elements(self, extension: str, path: pathlib.Path) -> typing.List[DataElementType]:
        return list()

    def can_write(self, data_metadata: DataAndMetadata.DataMetadata, extension: str) -> bool:
        return data_metadata.is_data_1d

    def write_display_item(self, display_item: DisplayItem.DisplayItem, path: pathlib.Path, extension: str) -> None:
        headers, data_list = build_table(display_item)

        newline = "\n"
        delimiter = ", "
        format_ = "{}" # We need to stick with an empty format string here, otherwise we will have problems with the
                       # fill value of zip_longest
        row_template = delimiter.join([format_] * len(data_list))
        row_template += newline
        header_template = "# " + row_template

        with open(path, "w+") as f:
            f.write(header_template.format(*headers))
            for row in itertools.zip_longest(*data_list, fillvalue=""):
                f.write(row_template.format(*row))


class NDataImportExportHandler(ImportExportHandler):

    def __init__(self, io_handler_id: str, name: str, extensions: typing.Sequence[str]) -> None:
        super().__init__(io_handler_id, name, extensions)

    def read_data_elements(self, extension: str, path: pathlib.Path) -> typing.List[DataElementType]:
        zip_file = zipfile.ZipFile(path, 'r')
        namelist = zip_file.namelist()
        if "metadata.json" in namelist and "data.npy" in namelist:
            metadata = json.loads(zip_file.read("metadata.json").decode("utf-8"))
            data_bytes = zip_file.read("data.npy")
            data = numpy.load(io.BytesIO(data_bytes))
            if data is not None:
                data_element = metadata
                data_element["data"] = data
                return [data_element]
        return list()

    def can_write(self, data_metadata: DataAndMetadata.DataMetadata, extension: str) -> bool:
        return True

    def write_display_item(self, display_item: DisplayItem.DisplayItem, path: pathlib.Path, extension: str) -> None:
        data_item = display_item.data_item
        assert data_item
        data_element = create_data_element_from_data_item(data_item, include_data=False)
        data = data_item.data
        if data is not None:
            root = str(path.parent)
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


class NumPyImportExportHandler(ImportExportHandler):
    """A file import/export handler to read/write the npy file type.

    The npy file type is the one included in the NumPy package.

    This i/o handler will optionally read metadata with the same name but the
    '.json' suffix located in the same directory.

    This i/o handler will write metadata to a file with the same name in the same
    directory but with the '.json' suffix.
    """

    def __init__(self, io_handler_id: str, name: str, extensions: typing.Sequence[str]) -> None:
        super().__init__(io_handler_id, name, extensions)

    def read_data_elements(self, extension: str, path: pathlib.Path) -> typing.List[DataElementType]:
        data = numpy.load(str(path))
        metadata_path = path.with_suffix(".json")
        if metadata_path.exists():
            with open(metadata_path) as f:
                metadata = json.load(f)
        else:
            metadata = dict()
        if data is not None:
            data_element = metadata
            data_element["data"] = data
            return [data_element]
        return list()

    def can_write(self, data_metadata: DataAndMetadata.DataMetadata, extension: str) -> bool:
        return True

    def write_display_item(self, display_item: DisplayItem.DisplayItem, path: pathlib.Path, extension: str) -> None:
        data_item = display_item.data_item
        assert data_item
        data_path = path
        metadata_path = data_path.with_suffix(".json")
        data_element = create_data_element_from_data_item(data_item, include_data=False)
        data = data_item.data
        if data is not None:
            try:
                with open(str(metadata_path), "w") as fp:
                    json.dump(data_element, fp)
                numpy.save(str(data_path), data)
            except Exception:
                os.remove(str(metadata_path))
                os.remove(str(data_path))
                raise


# Register the intrinsic I/O handlers.
ImportExportManager().register_io_handler(StandardImportExportHandler("jpeg-io-handler", "JPEG", ["jpg", "jpeg"]))
ImportExportManager().register_io_handler(StandardImportExportHandler("png-io-handler", "PNG", ["png"]))
ImportExportManager().register_io_handler(StandardImportExportHandler("gif-io-handler", "GIF", ["gif"]))
ImportExportManager().register_io_handler(StandardImportExportHandler("bmp-io-handler", "BMP", ["bmp"]))
# ImportExportManager().register_io_handler(StandardImportExportHandler("tiff-io-handler", "TIFF", ["tif", "tiff"]))
# ImportExportManager().register_io_handler(StandardImportExportHandler("cr2-io-handler", "CR2", ["cr2"]))
# ImportExportManager().register_io_handler(StandardImportExportHandler("nef-io-handler", "NEF", ["nef"]))
ImportExportManager().register_io_handler(CSVImportExportHandler("csv-io-handler", "CSV Raw", ["csv"]))
ImportExportManager().register_io_handler(CSV1ImportExportHandler("csv1-io-handler", "CSV 1D", ["csv"]))
ImportExportManager().register_io_handler(NDataImportExportHandler("ndata1-io-handler", "NData 1", ["ndata1"]))
ImportExportManager().register_io_handler(NumPyImportExportHandler("numpy-io-handler", "Raw NumPy", ["npy"]))
ImportExportManager().register_io_handler(StandardImportExportHandler("webp-io-handler", "WebP", ["webp"]))
