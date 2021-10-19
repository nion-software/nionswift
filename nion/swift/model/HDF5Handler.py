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
import time
import typing

import h5py
import numpy
import numpy.typing

from nion.swift.model import StorageHandler
from nion.swift.model import Utility
from nion.utils import Geometry

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


def get_write_chunk_shape_for_data(data_shape: DataAndMetadata.ShapeType, data_dtype: numpy.typing.DTypeLike) -> typing.Optional[DataAndMetadata.ShapeType]:
    """
    Calculate an appropriate write chunk shape for a given data shape and dtype.

    The target chunk size is 580 kB which seems to be a sweet spot according to benchmarks.
    The algorithm assumes that the data is c-contiguous in memory.

    If the total number of chunks that the calculated chunk shape would lead to is less than 100 (i.e. the file will
    be less than 58 MB in size) or if the data shape is not suitable for chunking, return None.
    """
    data_dtype = numpy.dtype(data_dtype)

    target_chunk_size = 580*1024/data_dtype.itemsize
    chunk_size = 1
    counter = len(data_shape)
    chunk_shape = [1] * len(data_shape)
    while chunk_size < target_chunk_size and counter > 0:
        counter -= 1
        chunk_size *= data_shape[counter]
        chunk_shape[counter] = data_shape[counter]

    if chunk_size == 0: # This means one of the input dimensions was "0", so chunking cannot be used
        return None

    chunk_size //= data_shape[counter]
    remaining_elements = min(max(target_chunk_size // chunk_size, 1), data_shape[counter])
    chunk_shape[counter] = int(remaining_elements)

    n_chunks = 1
    for i in range(len(chunk_shape)):
        n_chunks *= data_shape[i] // chunk_shape[i]
    if n_chunks < 100:
        return None

    return tuple(chunk_shape)


class HDF5Handler(StorageHandler.StorageHandler):
    count = 0  # useful for detecting leaks in tests
    open = 0  # useful for detecting unclosed files

    def __init__(self, file_path: typing.Union[str, pathlib.Path]) -> None:
        self.__file_path = str(file_path)
        self.__lock = threading.RLock()
        self.__fp: typing.Any = None
        self.__dataset: typing.Any = None
        self._write_count = 0
        HDF5Handler.count += 1

    def close(self) -> None:
        HDF5Handler.count -= 1
        if self.__fp:
            self.__dataset = None
            self.__fp.close()
            HDF5Handler.open -= 1
            self.__fp = None

    # called before the file is moved; close but don't count.
    def prepare_move(self) -> None:
        with self.__lock:
            if self.__fp:
                self.__dataset = None
                self.__fp.close()
                HDF5Handler.open -= 1
                self.__fp = None

    @property
    def reference(self) -> str:
        return self.__file_path

    @property
    def is_valid(self) -> bool:
        return True

    @classmethod
    def is_matching(self, file_path: str) -> bool:
        if file_path.endswith(".h5") and os.path.exists(file_path):
            return True
        return False

    @classmethod
    def make(cls, file_path: pathlib.Path) -> StorageHandler.StorageHandler:
        return cls(cls.make_path(file_path))

    @classmethod
    def make_path(cls, file_path: pathlib.Path) -> str:
        return str(file_path.with_suffix(cls.get_extension()))

    @classmethod
    def get_extension(self) -> str:
        return ".h5"

    def __ensure_open(self) -> None:
        if not self.__fp:
            make_directory_if_needed(os.path.dirname(self.__file_path))
            self.__fp = h5py.File(self.__file_path, "a")
            HDF5Handler.open += 1

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
            self.__ensure_open()
            if self.__dataset is None:
                if "data" in self.__fp:
                    self.__dataset = self.__fp["data"]
                else:
                    self.__dataset = self.__fp.create_dataset("data", data=numpy.empty((0,)))

    def write_data(self, data: _NDArray, file_datetime: datetime.datetime) -> None:
        with self.__lock:
            assert data is not None
            self.__ensure_open()
            assert self.__fp is not None
            json_properties = None
            # handle three cases:
            #   1 - 'data' doesn't yet exist (require_dataset)
            #   2 - 'data' exists but is a different size (delete, then require_dataset)
            #   3 - 'data' exists and is the same size (overwrite)
            if not "data" in self.__fp:
                # case 1
                chunks = get_write_chunk_shape_for_data(data.shape, data.dtype)
                self.__dataset = self.__fp.require_dataset("data", shape=data.shape, dtype=data.dtype, chunks=chunks)
            else:
                if self.__dataset is None:
                    self.__dataset = self.__fp["data"]
                if self.__dataset.shape != data.shape or self.__dataset.dtype != data.dtype:
                    # case 2
                    json_properties = self.__dataset.attrs.get("properties", "")
                    self.__dataset = None
                    self.__fp.close()
                    HDF5Handler.open -= 1
                    self.__fp = None
                    os.remove(self.__file_path)
                    self.__ensure_open()
                    chunks = get_write_chunk_shape_for_data(data.shape, data.dtype)
                    self.__dataset = self.__fp.require_dataset("data", shape=data.shape, dtype=data.dtype, chunks=chunks)
            self.__copy_data(data)
            if json_properties is not None:
                self.__dataset.attrs["properties"] = json_properties
            self.__fp.flush()

    def reserve_data(self, data_shape: DataAndMetadata.ShapeType, data_dtype: numpy.typing.DTypeLike, file_datetime: datetime.datetime) -> None:
        # reserve data of the given shape and dtype, filled with zeros
        with self.__lock:
            self.__ensure_open()
            json_properties = None
            # first read existing properties and then close existing data set and file.
            if "data" in self.__fp:
                if self.__dataset is None:
                    self.__dataset = self.__fp["data"]
                json_properties = self.__dataset.attrs.get("properties", "")
                self.__dataset = None
                self.__fp.close()
                HDF5Handler.open -= 1
                self.__fp = None
                os.remove(self.__file_path)
                self.__ensure_open()
            # reserve the data
            chunks = get_write_chunk_shape_for_data(data_shape, data_dtype)
            self.__dataset = self.__fp.require_dataset("data", shape=data_shape, dtype=data_dtype, fillvalue=0, chunks=chunks)
            if json_properties is not None:
                self.__dataset.attrs["properties"] = json_properties
            self.__fp.flush()

    def __copy_data(self, data: _NDArray) -> None:
        if id(data) != id(self.__dataset):
            self.__dataset[:] = data
            self._write_count += 1

    def write_properties(self, properties: PersistentDictType, file_datetime: datetime.datetime) -> None:
        with self.__lock:
            self.__ensure_open()
            self.__ensure_dataset()
            self.__write_properties_to_dataset(properties)
            self.__fp.flush()

    def read_properties(self) -> PersistentDictType:
        with self.__lock:
            self.__ensure_open()
            self.__ensure_dataset()
            json_properties = self.__dataset.attrs.get("properties", "")
            return typing.cast(PersistentDictType, json.loads(json_properties))

    def read_data(self) -> typing.Optional[_NDArray]:
        with self.__lock:
            self.__ensure_open()
            self.__ensure_dataset()
            if self.__dataset.shape == (0, ):
                return None
            return typing.cast(typing.Optional[_NDArray], self.__dataset)

    def remove(self) -> None:
        if self.__fp:
            self.__dataset = None
            self.__fp.close()
            HDF5Handler.open -= 1
            self.__fp = None
        if os.path.isfile(self.__file_path):
            os.remove(self.__file_path)
