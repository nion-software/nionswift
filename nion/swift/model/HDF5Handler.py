"""
    A module for handle .h5 files for Swift.
"""
from __future__ import annotations

import datetime
import io
import json
import os
import pathlib
import threading
import typing
import uuid

import h5py
import hdf5plugin
import numpy
import numpy.typing

from nion.swift.model import StorageHandler
from nion.swift.model import Utility
from nion.utils import DateTime
from nion.utils import Geometry
from nion.utils import Registry

if typing.TYPE_CHECKING:
    from nion.data import DataAndMetadata


PersistentDictType = typing.Dict[str, typing.Any]
_NDArray = numpy.typing.NDArray[typing.Any]


def make_directory_if_needed(directory_path: str) -> None:
    """
        Make the directory path, if needed.
    """
    if os.path.exists(directory_path):
        if not os.path.isdir(directory_path):
            raise OSError("Path is not a directory:", directory_path)
    else:
        os.makedirs(directory_path)


def get_write_chunk_shape_for_data(data_shape: DataAndMetadata.ShapeType, data_dtype: numpy.typing.DTypeLike, target_chunk_size: int=240000) -> typing.Optional[DataAndMetadata.ShapeType]:
    """
    Calculate an appropriate write chunk shape for a given data shape and dtype.

    The default target chunk size is 240 kB which seems to be a sweet spot according to benchmarks.
    The algorithm assumes that the data is c-contiguous in memory.

    If the total number of chunks that the calculated chunk shape would lead to is less than 100 (i.e. the file will
    be less than 24 MB in size) or if the data shape is not suitable for chunking, return None.

    The chunk shape is calculated according to the following rules:
    - Use a quarter of the data axis (i.e. the last axis for 1D data and the last two axis for 2D data)
      if the number of elements in the last two or last three dimensions is large enough. If not, use
      the entire data axis.
    - Work backwards from the last axis and increse the number of elements per axis until prod(chunk_chape) >= target_chunk size.
      A chunk cannot exceed the number of elements of an axis, so if one dimension is "full", move to the next axis.
    - The slow scan axis and the sequence axis when acquiring a sequence of SIs or 4D STEM images can never be chunked (i.e.
      chunk shape == 1 for these axis).
    - The sequence axis in a sequence of 1D or 2D data can be chunked.
    """
    data_dtype = numpy.dtype(data_dtype)

    if len(data_shape) > 1:
        is_2d_data = data_shape[-1] <= 1.5 * data_shape[-2]
    else:
        is_2d_data = False

    target_chunk_size = int(round(target_chunk_size / data_dtype.itemsize))
    divisors = [1] * len(data_shape)
    if len(data_shape) > 2 and (
        (numpy.prod(data_shape[-3:]) > 8 * target_chunk_size and is_2d_data) or
        (numpy.prod(data_shape[-2:]) > 2 * target_chunk_size)):
        if is_2d_data:
            # Assume these are 2D camera frames if the x-dimension is not much larger than the y-dimension
            divisors[-2:] = [4, 4]
        else:
            divisors[-1] = 4

    chunk_size = 1
    counter = len(data_shape)
    chunk_shape = [1] * len(data_shape)
    while chunk_size < target_chunk_size and counter > 0:
        counter -= 1
        chunk_size *= data_shape[counter] // divisors[counter]
        chunk_shape[counter] = data_shape[counter] // divisors[counter]

    if chunk_size == 0: # This means one of the input dimensions was "0", so chunking cannot be used
        return None

    chunk_size //= chunk_shape[counter]
    remaining_elements = min(max(target_chunk_size // chunk_size, 1), data_shape[counter])
    chunk_shape[counter] = int(remaining_elements)

    n_chunks = 1
    for i in range(len(chunk_shape)):
        n_chunks *= data_shape[i] // chunk_shape[i]
    if n_chunks < 100:
        return None

    # Do not allow chunking of the slow scan axis or the sequence axis when acquiring a sequence of SIs or 4D STEM images.
    if is_2d_data and len(data_shape) > 3:
        chunk_shape[:-3] = [1] * (len(data_shape) - 3)
    elif not is_2d_data and len(data_shape) > 2:
        chunk_shape[:-2] = [1] * (len(data_shape) - 2)

    return tuple(chunk_shape)


_HDF5FilePointer = typing.Any


class HDF5FileEntry:
    def __init__(self, path: pathlib.Path) -> None:
        self.__lock = threading.RLock()
        self.__path = path
        self.__fp: typing.Optional[_HDF5FilePointer] = None
        self._count = 0

    @property
    def fp(self) -> _HDF5FilePointer:
        with self.__lock:
            self.open()
            assert self.__fp
            return self.__fp

    def open(self) -> None:
        with self.__lock:
            if not self.__fp:
                self.__path.parent.mkdir(parents=True, exist_ok=True)
                self.__fp = h5py.File(self.__path, "a")

    def close(self) -> None:
        with self.__lock:
            if self.__fp:
                self.__fp.close()
            self.__fp = None


class HDF5FileManager:
    def __init__(self) -> None:
        self.__file_entries: typing.Dict[pathlib.Path, HDF5FileEntry] = dict()
        self.__lock = threading.RLock()

    def _clear(self) -> None:
        # for tests only
        self.__file_entries.clear()

    @property
    def _open_count(self) -> int:
        return len(self.__file_entries.items())

    def open(self, path: pathlib.Path) -> HDF5FileEntry:
        with self.__lock:
            if not path in self.__file_entries:
                self.__file_entries[path] = HDF5FileEntry(path)
            self.__file_entries[path]._count += 1
            return self.__file_entries[path]

    def close(self, path: pathlib.Path) -> None:
        with self.__lock:
            self.__file_entries[path]._count -= 1
            if self.__file_entries[path]._count == 0:
                self.__file_entries.pop(path).close()

    def force_close(self, path: pathlib.Path) -> None:
        with self.__lock:
            if path in self.__file_entries:
                self.__file_entries[path].close()


_file_manager = HDF5FileManager()


class HDF5Handler(StorageHandler.StorageHandler):
    count = 0  # useful for detecting leaks in tests
    open = 0  # useful for detecting unclosed files

    def __init__(self, file_path: typing.Union[str, pathlib.Path]) -> None:
        self.__file_path = str(file_path)
        self.__lock = threading.RLock()
        self.__file = _file_manager.open(pathlib.Path(self.__file_path))
        self.__dataset: typing.Any = None
        self._write_count = 0
        self.compression_enabled = True
        HDF5Handler.count += 1

    def close(self) -> None:
        HDF5Handler.count -= 1
        self.__close_fp()
        _file_manager.close(pathlib.Path(self.__file_path))

    def __get_compressor(self) -> h5py.filters.FilterRefBase | None:
        return hdf5plugin.Blosc(cname='lz4', clevel=9, shuffle=hdf5plugin.Blosc.BITSHUFFLE) if self.compression_enabled else None

    @property
    def factory(self) -> StorageHandler.StorageHandlerFactoryLike:
        return HDF5HandlerFactory()

    @property
    def storage_handler_type(self) -> str:
        return "hdf5"

    # called before the file is moved; close but don't count.
    def prepare_move(self) -> None:
        with self.__lock:
            self.__close_fp()
            _file_manager.force_close(pathlib.Path(self.__file_path))

    @property
    def reference(self) -> str:
        return self.__file_path

    @property
    def is_valid(self) -> bool:
        return True

    def get_extension(self) -> str:
        return ".h5"

    def __write_properties_to_dataset(self, properties: PersistentDictType) -> None:
        with self.__lock:
            assert self.__dataset is not None

            class JSONEncoder(json.JSONEncoder):
                def default(self, obj: typing.Any) -> typing.Any:
                    if isinstance(obj, Geometry.IntPoint) or isinstance(obj, Geometry.IntSize) or isinstance(obj, Geometry.IntRect) or isinstance(obj, Geometry.FloatPoint) or isinstance(obj, Geometry.FloatSize) or isinstance(obj, Geometry.FloatRect):
                        return tuple(obj)
                    else:
                        return json.JSONEncoder.default(self, obj)

            json_io = io.StringIO()
            json.dump(Utility.clean_dict(properties), json_io, cls=JSONEncoder)
            json_str = json_io.getvalue()

            self.__dataset.attrs["properties"] = json_str

    def __ensure_dataset(self) -> None:
        with self.__lock:
            if self.__dataset is None:
                if "data" in self.__file.fp:
                    self.__dataset = self.__file.fp["data"]
                else:
                    self.__dataset = self.__file.fp.create_dataset("data", data=numpy.empty((0,)), compression=self.__get_compressor())

    def write_data(self, data: _NDArray, file_datetime: datetime.datetime) -> None:
        with self.__lock:
            assert data is not None
            json_properties = None
            # handle three cases:
            #   1 - 'data' doesn't yet exist (require_dataset)
            #   2 - 'data' exists but is a different size (delete, then require_dataset)
            #   3 - 'data' exists and is the same size (overwrite)
            if not "data" in self.__file.fp:
                # case 1
                chunks = get_write_chunk_shape_for_data(data.shape, data.dtype)
                self.__dataset = self.__file.fp.require_dataset("data", shape=data.shape, dtype=data.dtype, chunks=chunks, compression=self.__get_compressor())
            else:
                if self.__dataset is None:
                    self.__dataset = self.__file.fp["data"]
                if self.__dataset.shape != data.shape or self.__dataset.dtype != data.dtype:
                    # case 2
                    json_properties = self.__dataset.attrs.get("properties", "")
                    self.__close_fp()
                    os.remove(self.__file_path)
                    chunks = get_write_chunk_shape_for_data(data.shape, data.dtype)
                    self.__dataset = self.__file.fp.require_dataset("data", shape=data.shape, dtype=data.dtype, chunks=chunks, compression=self.__get_compressor())
            self.__copy_data(data)
            if json_properties is not None:
                self.__dataset.attrs["properties"] = json_properties
            self.__file.fp.flush()

    def reserve_data(self, data_shape: DataAndMetadata.ShapeType, data_dtype: numpy.typing.DTypeLike, file_datetime: datetime.datetime) -> None:
        # reserve data of the given shape and dtype, filled with zeros
        with self.__lock:
            json_properties = None
            # first read existing properties and then close existing data set and file.
            if "data" in self.__file.fp:
                if self.__dataset is None:
                    self.__dataset = self.__file.fp["data"]
                json_properties = self.__dataset.attrs.get("properties", "")
                self.__close_fp()
                os.remove(self.__file_path)
                self.__file.open()
            # reserve the data
            chunks = get_write_chunk_shape_for_data(data_shape, data_dtype)
            self.__dataset = self.__file.fp.require_dataset("data", shape=data_shape, dtype=data_dtype, fillvalue=0, chunks=chunks, compression=self.__get_compressor())
            if json_properties is not None:
                self.__dataset.attrs["properties"] = json_properties
            self.__file.fp.flush()

    def __copy_data(self, data: _NDArray) -> None:
        if id(data) != id(self.__dataset):
            self.__dataset[:] = data
            self._write_count += 1

    def write_properties(self, properties: PersistentDictType, file_datetime: datetime.datetime) -> None:
        with self.__lock:
            self.__ensure_dataset()
            self.__write_properties_to_dataset(properties)
            self.__file.fp.flush()

    def read_properties(self) -> PersistentDictType:
        with self.__lock:
            self.__ensure_dataset()
            json_properties = self.__dataset.attrs.get("properties", "")
            return typing.cast(PersistentDictType, json.loads(json_properties))

    def read_data(self) -> typing.Optional[_NDArray]:
        with self.__lock:
            self.__ensure_dataset()
            if self.__dataset.shape == (0, ):
                return None
            return typing.cast(typing.Optional[_NDArray], self.__dataset)

    def remove(self) -> None:
        self.__close_fp()
        if os.path.isfile(self.__file_path):
            os.remove(self.__file_path)

    def __close_fp(self) -> None:
        self.__dataset = None
        self.__file.close()


class HDF5HandlerFactory(StorageHandler.StorageHandlerFactoryLike):

    def get_storage_handler_type(self) -> str:
        return "hdf5"

    def is_matching(self, file_path: str) -> bool:
        if file_path.endswith(".h5") and os.path.exists(file_path):
            return True
        return False

    def make(self, file_path: pathlib.Path) -> StorageHandler.StorageHandler:
        return HDF5Handler(self.make_path(file_path))

    def make_path(self, file_path: pathlib.Path) -> str:
        return str(file_path.with_suffix(self.get_extension()))

    def get_extension(self) -> str:
        return ".h5"


class HDFImportExportDriver:
    def __init__(self) -> None:
        pass

    def read_data(self, file_path: pathlib.Path, storage_handler_provider: StorageHandler.StorageHandlerProvider) -> StorageHandler.StorageHandlerImportData:
        storage_handlers = list[StorageHandler.StorageHandler]()
        uuid_map = dict[uuid.UUID, uuid.UUID]()
        items = list[PersistentDictType]()
        fp = h5py.File(file_path, "r")
        if "data" in fp:
            data_group = fp["data"]
            for key in sorted(data_group.keys()):
                ds = data_group[key]
                data_item_uuid = uuid.uuid4()
                data_item_properties = json.loads(ds.attrs["properties"])
                data_item_data = ds
                if "uuid" in data_item_properties:
                    uuid_map[uuid.UUID(data_item_properties["uuid"])] = data_item_uuid
                data_item_properties["uuid"] = str(data_item_uuid)
                storage_handler_attributes = StorageHandler.StorageHandlerAttributes(
                    data_item_uuid,
                    DateTime.utcnow(),
                    data_item_properties.get("session_id", None),
                    ds.nbytes
                )
                storage_handler = storage_handler_provider.make_storage_handler(storage_handler_attributes)
                storage_handler.write_data(data_item_data, storage_handler_attributes.created_local)
                storage_handler.write_properties(data_item_properties, storage_handler_attributes.created_local)
                storage_handlers.append(storage_handler)
        if "index" in fp:
            index_group = fp["index"]
            for key in sorted(index_group.attrs.keys()):
                items.append(json.loads(index_group.attrs[key]))
        fp.close()
        return StorageHandler.StorageHandlerImportData(storage_handlers, uuid_map, items)

    def write_display_item(self, path: pathlib.Path, items: typing.Sequence[StorageHandler.StorageHandlerExportItem]) -> None:
        path.unlink(missing_ok=True)
        fp = h5py.File(path, "a")
        index_group = fp.create_group("index")
        data_group = fp.create_group("data")
        data_index = 0
        for index, item in enumerate(items):
            index_group.attrs["1"] = json.dumps(item.write_to_dict())
            for data_item in item.data_items:
                ds = data_group.create_dataset(str(data_index), data=data_item.data)
                ds.attrs["properties"] = json.dumps(data_item.write_to_dict())
                data_index += 1
        fp.close()


class HDFImportExportDriverFactory:
    driver_id = "nhdf-io-handler"
    title = "NData HDF"
    extensions = ["nhdf"]

    def make_import_export_driver(self) -> HDFImportExportDriver:
        return HDFImportExportDriver()


Registry.register_component(HDFImportExportDriverFactory(), {"import-export-driver-factory"})


"""
Architectural Decision Records.

ADR 2024-02-19. Do not use Single Writer Multiple Reader (SWMR) mode for HDF5 files. This requires the writing process
to set the flag and we don't have control of the writers outside of our process. In addition, the docs curently say that
SWMR is not supported on Windows.
"""
