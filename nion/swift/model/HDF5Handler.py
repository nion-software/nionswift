"""
    A module for handle .h5 files for Swift.
"""

import io
import json
import os
import pathlib
import threading
import typing

import h5py
import numpy

from nion.swift.model import StorageHandler
from nion.swift.model import Utility
from nion.utils import Geometry


def make_directory_if_needed(directory_path):
    """
        Make the directory path, if needed.
    """
    if os.path.exists(directory_path):
        if not os.path.isdir(directory_path):
            raise OSError("Path is not a directory:", directory_path)
    else:
        os.makedirs(directory_path)


def get_write_chunk_shape_for_data(data_shape, data_dtype):
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

    chunk_size /= data_shape[counter]
    remaining_elements = min(max(target_chunk_size // chunk_size, 1), data_shape[counter])
    chunk_shape[counter] = int(remaining_elements)

    n_chunks = 1
    for i in range(len(chunk_shape)):
        n_chunks *= data_shape[i] / chunk_shape[i]
    if n_chunks < 100:
        return None

    return tuple(chunk_shape)



class HDF5Handler(StorageHandler.StorageHandler):
    count = 0  # useful for detecting leaks in tests

    def __init__(self, file_path):
        self.__file_path = str(file_path)
        self.__lock = threading.RLock()
        self.__fp = None
        self.__dataset = None
        self._write_count = 0
        HDF5Handler.count += 1

    def close(self):
        HDF5Handler.count -= 1
        if self.__fp:
            self.__dataset = None
            self.__fp.close()
            self.__fp = None

    # called before the file is moved; close but don't count.
    def prepare_move(self) -> None:
        if self.__fp:
            self.__dataset = None
            self.__fp.close()
            self.__fp = None

    @property
    def reference(self):
        return self.__file_path

    @property
    def is_valid(self):
        return True

    @classmethod
    def is_matching(self, file_path):
        if file_path.endswith(".h5") and os.path.exists(file_path):
            return True
        return False

    @classmethod
    def make(cls, file_path: pathlib.Path):
        return cls(cls.make_path(file_path))

    @classmethod
    def make_path(cls, file_path: pathlib.Path) -> str:
        return str(file_path.with_suffix(cls.get_extension()))

    @classmethod
    def get_extension(self) -> str:
        return ".h5"

    def __ensure_open(self):
        if not self.__fp:
            make_directory_if_needed(os.path.dirname(self.__file_path))
            self.__fp = h5py.File(self.__file_path, "a")

    def __write_properties_to_dataset(self, properties):
        with self.__lock:
            assert self.__dataset is not None

            class JSONEncoder(json.JSONEncoder):
                def default(self, obj):
                    if isinstance(obj, Geometry.IntPoint) or isinstance(obj, Geometry.IntSize) or isinstance(obj, Geometry.IntRect) or isinstance(obj, Geometry.FloatPoint) or isinstance(obj, Geometry.FloatSize) or isinstance(obj, Geometry.FloatRect):
                        return tuple(obj)
                    else:
                        return json.JSONEncoder.default(self, obj)

            json_io = io.StringIO()
            json.dump(Utility.clean_dict(properties), json_io, cls=JSONEncoder)
            json_str = json_io.getvalue()

            self.__dataset.attrs["properties"] = json_str

    def __ensure_dataset(self):
        with self.__lock:
            self.__ensure_open()
            if self.__dataset is None:
                if "data" in self.__fp:
                    self.__dataset = self.__fp["data"]
                else:
                    self.__dataset = self.__fp.create_dataset("data", data=numpy.empty((0,)))

    def write_data(self, data, file_datetime):
        with self.__lock:
            assert data is not None
            self.__ensure_open()
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
                    self.__fp = None
                    os.remove(self.__file_path)
                    self.__ensure_open()
                    chunks = get_write_chunk_shape_for_data(data.shape, data.dtype)
                    self.__dataset = self.__fp.require_dataset("data", shape=data.shape, dtype=data.dtype, chunks=chunks)
            self.__copy_data(data)
            if json_properties is not None:
                self.__dataset.attrs["properties"] = json_properties
            self.__fp.flush()

    def reserve_data(self, data_shape: typing.Tuple[int, ...], data_dtype: numpy.dtype, file_datetime) -> None:
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
                self.__fp = None
                os.remove(self.__file_path)
                self.__ensure_open()
            # reserve the data
            chunks = get_write_chunk_shape_for_data(data_shape, data_dtype)
            self.__dataset = self.__fp.require_dataset("data", shape=data_shape, dtype=data_dtype, fillvalue=0, chunks=chunks)
            if json_properties is not None:
                self.__dataset.attrs["properties"] = json_properties
            self.__fp.flush()

    def __copy_data(self, data):
        if id(data) != id(self.__dataset):
            self.__dataset[:] = data
            self._write_count += 1

    def write_properties(self, properties, file_datetime):
        with self.__lock:
            self.__ensure_open()
            self.__ensure_dataset()
            self.__write_properties_to_dataset(properties)
            self.__fp.flush()

    def read_properties(self):
        with self.__lock:
            self.__ensure_open()
            self.__ensure_dataset()
            json_properties = self.__dataset.attrs.get("properties", "")
            return json.loads(json_properties)

    def read_data(self):
        with self.__lock:
            self.__ensure_open()
            self.__ensure_dataset()
            if self.__dataset.shape == (0, ):
                return None
            return self.__dataset

    def remove(self):
        if self.__fp:
            self.__dataset = None
            self.__fp.close()
            self.__fp = None
        if os.path.isfile(self.__file_path):
            os.remove(self.__file_path)
