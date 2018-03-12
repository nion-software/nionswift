"""
    A module for handle .h5 files for Swift.
"""

import io
import json
import os
import pathlib
import threading

import h5py
import numpy

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


class HDF5Handler:

    def __init__(self, file_path):
        self.__file_path = str(file_path)
        self.__lock = threading.RLock()
        self.__fp = None
        self.__dataset = None

    def close(self):
        if self.__fp:
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
    def make(cls, file_path):
        return cls(cls.make_path(file_path))

    @classmethod
    def make_path(cls, file_path) -> str:
        return str(pathlib.Path(file_path).with_suffix(cls.get_extension()))

    @classmethod
    def get_extension(self) -> str:
        return ".h5"

    def __ensure_open(self):
        if not self.__fp:
            make_directory_if_needed(os.path.dirname(self.__file_path))
            self.__fp = h5py.File(self.__file_path)

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
                self.__dataset = self.__fp.require_dataset("data", shape=data.shape, dtype=data.dtype, data=data)
            else:
                self.__dataset = self.__fp["data"]
                if self.__dataset.shape != data.shape or self.__dataset.dtype != data.dtype:
                    # case 2
                    json_properties = self.__dataset.attrs.get("properties", "")
                    self.__dataset = None
                    self.__fp.close()
                    self.__fp = None
                    os.remove(self.__file_path)
                    self.__ensure_open()
                    self.__dataset = self.__fp.require_dataset("data", shape=data.shape, dtype=data.dtype, data=data)
                else:
                    # case 3
                    self.__dataset[:] = data
            if json_properties is not None:
                self.__dataset.attrs["properties"] = json_properties
            self.__fp.flush()

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
        self.close()
        if os.path.isfile(self.__file_path):
            os.remove(self.__file_path)
