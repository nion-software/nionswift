"""
    A module for handle .h5 files for Swift.
"""

import io
import json
import os
import pathlib
import threading
import typing
import shutil

import zarr
import numpy

from nion.swift.model import StorageHandler
from nion.swift.model import Utility
from nion.utils import Geometry

import numcodecs
numcodecs.blosc.init()
numcodecs.blosc.set_nthreads(8)
numcodecs.blosc.use_threads = True


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

    The target chunk size is 100 MB which has shown good results in benchmarks.
    The algorithm assumes that the data is c-contiguous in memory.

    If the total number of chunks that the calculated chunk shape would lead to is less than 10 (i.e. the file will
    be less than 1000 MB in size) or if the data shape is not suitable for chunking, return False.
    """
    data_dtype = numpy.dtype(data_dtype)

    target_chunk_size = 10485760/data_dtype.itemsize
    chunk_size = 1
    counter = len(data_shape)
    chunk_shape = [1] * len(data_shape)
    while chunk_size < target_chunk_size and counter > 0:
        counter -= 1
        chunk_size *= data_shape[counter]
        chunk_shape[counter] = data_shape[counter]

    if chunk_size == 0: # This means one of the input dimensions was "0", so chunking cannot be used
        return False

    chunk_size /= data_shape[counter]
    remaining_elements = min(max(target_chunk_size // chunk_size, 1), data_shape[counter])
    chunk_shape[counter] = int(remaining_elements)

    n_chunks = 1
    for i in range(len(chunk_shape)):
        n_chunks *= data_shape[i] / chunk_shape[i]
    if n_chunks < 10:
        return False

    return tuple(chunk_shape)



class ZarrHandler(StorageHandler.StorageHandler):
    count = 0  # useful for detecting leaks in tests

    def __init__(self, file_path):
        self.__file_path = str(file_path)
        self.__fp = None
        self.__store = None
        self.__dataset = None
        self.__array = None
        self.__compressor = numcodecs.Blosc(cname='blosclz', clevel=3, shuffle=numcodecs.Blosc.NOSHUFFLE)
        self._write_count = 0
        ZarrHandler.count += 1

    def close(self):
        ZarrHandler.count -= 1
        if self.__store:
            self.__array = None
            try:
                self.__store.close()
            except AttributeError:
                pass
            self.__store = None

    # called before the file is moved; close but don't count.
    def prepare_move(self) -> None:
        if self.__fp:
            self.__array = None
            try:
                self.__store.close()
            except AttributeError:
                pass
            self.__store = None

    @property
    def reference(self):
        return self.__file_path

    @property
    def is_valid(self):
        return True

    @classmethod
    def is_matching(self, file_path):
        if file_path.endswith(".zarr") and os.path.exists(file_path):
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
        return ".zarr"

    def __ensure_open(self):
        if not self.__store:
            make_directory_if_needed(os.path.dirname(self.__file_path))
            self.__store = zarr.storage.NestedDirectoryStore(self.__file_path, normalize_keys=True)

    def __write_properties_to_dataset(self, properties):
        assert self.__array is not None

        class JSONEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, Geometry.IntPoint) or isinstance(obj, Geometry.IntSize) or isinstance(obj, Geometry.IntRect) or isinstance(obj, Geometry.FloatPoint) or isinstance(obj, Geometry.FloatSize) or isinstance(obj, Geometry.FloatRect):
                    return tuple(obj)
                else:
                    return json.JSONEncoder.default(self, obj)

        json_io = io.StringIO()
        json.dump(Utility.clean_dict(properties), json_io, cls=JSONEncoder)
        json_str = json_io.getvalue()

        self.__array.attrs["properties"] = json_str

    def __ensure_dataset(self):
        self.__ensure_open()
        if self.__array is None:
            try:
                self.__array = zarr.Array(self.__store)
            except zarr.errors.ArrayNotFoundError:
                self.__array = zarr.create((), chunks=False, overwrite=True, store=self.__store, compressor=self.__compressor)

    def write_data(self, data, file_datetime):
        assert data is not None
        self.__ensure_open()
        json_properties = None
        # handle three cases:
        #   1 - 'data' doesn't yet exist (require_dataset)
        #   2 - 'data' exists but is a different size (delete, then require_dataset)
        #   3 - 'data' exists and is the same size (overwrite)
        try:
            self.__array = zarr.Array(self.__store)
        except zarr.errors.ArrayNotFoundError:
            # case 1
            chunks = get_write_chunk_shape_for_data(data.shape, data.dtype)
            self.__array = zarr.array(data, chunks=chunks, overwrite=True, store=self.__store, compressor=self.__compressor)
        else:
            # case 2
            if self.__array.shape != data.shape or self.__array.dtype != data.dtype:
                chunks = get_write_chunk_shape_for_data(data.shape, data.dtype)
                json_properties = self.__array.attrs.get("properties", "")
                self.__array = zarr.array(data, chunks=chunks, overwrite=True, store=self.__store, compressor=self.__compressor)
            # case 3
            else:
                self.__copy_data(data)

        if json_properties is not None:
            self.__array.attrs["properties"] = json_properties

    def reserve_data(self, data_shape: typing.Tuple[int, ...], data_dtype: numpy.dtype, file_datetime) -> None:
        # reserve data of the given shape and dtype, filled with zeros
        self.__ensure_open()
        json_properties = None
        # first read existing properties and then close existing data set and file.
        try:
            self.__array = zarr.Array(self.__store)
        except zarr.errors.ArrayNotFoundError:
            pass
        else:
            json_properties = self.__array.attrs.get("properties", "")
        # reserve the data
        chunks = get_write_chunk_shape_for_data(data_shape, data_dtype)
        self.__array = zarr.zeros(data_shape, dtype=data_dtype, chunks=chunks, overwrite=True, store=self.__store, compressor=self.__compressor)

        if json_properties is not None:
            self.__array.attrs["properties"] = json_properties

    def __copy_data(self, data):
        if id(data) != id(self.__array):
            self.__array[:] = data
            self._write_count += 1

    def write_properties(self, properties, file_datetime):
        self.__ensure_open()
        self.__ensure_dataset()
        self.__write_properties_to_dataset(properties)

    def read_properties(self):
        self.__ensure_open()
        self.__ensure_dataset()
        json_properties = self.__array.attrs.get("properties", "")
        return json.loads(json_properties)

    def read_data(self):
        self.__ensure_open()
        self.__ensure_dataset()
        if self.__array.shape == ():
            return None
        return self.__array

    def remove(self):
        if self.__store:
            self.__array = None
            try:
                self.__store.close()
            except AttributeError:
                pass
            self.__store = None
        if os.path.isfile(self.__file_path):
            os.remove(self.__file_path)
        elif os.path.isdir(self.__file_path):
            shutil.rmtree(self.__file_path)
