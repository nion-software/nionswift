# futures
from __future__ import absolute_import
from __future__ import division

# standard libraries
import base64
import copy
import datetime
import gettext
import logging
import re

# third party libraries
import numpy

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import Image

_ = gettext.gettext


class DataAndMetadata(object):
    """Represent the ability to calculate data and provide immediate calibrations."""

    def __init__(self, data_fn, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp):
        self.data_fn = data_fn
        self.data_shape_and_dtype = data_shape_and_dtype
        self.intensity_calibration = intensity_calibration
        self.dimensional_calibrations = dimensional_calibrations
        self.timestamp = timestamp
        self.metadata = copy.deepcopy(metadata)

    @classmethod
    def from_rpc_dict(cls, d):
        if d is None:
            return None
        data = numpy.loads(base64.b64decode(d["data"].encode('utf-8')))
        data_shape_and_dtype = Image.spatial_shape_from_data(data), data.dtype
        intensity_calibration = Calibration.from_rpc_dict(d.get("intensity_calibration"))
        if "dimensional_calibrations" in d:
            dimensional_calibrations = [Calibration.from_rpc_dict(dc) for dc in d.get("dimensional_calibrations")]
        else:
            dimensional_calibrations = None
        metadata = d.get("metadata")
        timestamp = datetime.datetime(*list(map(int, re.split('[^\d]', d.get("timestamp"))))) if "timestamp" in d else None
        return DataAndMetadata(lambda: data, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp)

    @property
    def rpc_dict(self):
        d = dict()
        data = self.data
        if data is not None:
            d["data"] = base64.b64encode(numpy.ndarray.dumps(data)).decode('utf=8')
        if self.intensity_calibration:
            d["intensity_calibration"] = self.intensity_calibration.rpc_dict
        if self.dimensional_calibrations:
            d["dimensional_calibrations"] = [dimensional_calibration.rpc_dict for dimensional_calibration in self.dimensional_calibrations]
        if self.timestamp:
            d["timestamp"] = self.timestamp.isoformat()
        if self.metadata:
            d["metadata"] = copy.copy(self.metadata)
        return d

    @property
    def data(self):
        return self.data_fn()

    @property
    def data_shape(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return data_shape_and_dtype[0] if data_shape_and_dtype is not None else None

    @property
    def data_dtype(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return data_shape_and_dtype[1] if data_shape_and_dtype is not None else None

    @property
    def dimensional_shape(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        if data_shape_and_dtype is not None:
            data_shape, data_dtype = self.data_shape_and_dtype
            return Image.dimensional_shape_from_shape_and_dtype(data_shape, data_dtype)
        return None

    def get_intensity_calibration(self):
        return self.intensity_calibration

    def get_dimensional_calibration(self, index):
        return self.dimensional_calibrations[index]

    @property
    def is_data_1d(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_1d(*data_shape_and_dtype) if data_shape_and_dtype else False

    @property
    def is_data_2d(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_2d(*data_shape_and_dtype) if data_shape_and_dtype else False

    @property
    def is_data_3d(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_3d(*data_shape_and_dtype) if data_shape_and_dtype else False

    @property
    def is_data_rgb(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_rgb(*data_shape_and_dtype) if data_shape_and_dtype else False

    @property
    def is_data_rgba(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_rgba(*data_shape_and_dtype) if data_shape_and_dtype else False

    @property
    def is_data_rgb_type(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return (Image.is_shape_and_dtype_rgb(*data_shape_and_dtype) or Image.is_shape_and_dtype_rgba(*data_shape_and_dtype)) if data_shape_and_dtype else False

    @property
    def is_data_scalar_type(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_scalar_type(*data_shape_and_dtype) if data_shape_and_dtype else False

    @property
    def is_data_complex_type(self):
        data_shape_and_dtype = self.data_shape_and_dtype
        return Image.is_shape_and_dtype_complex_type(*data_shape_and_dtype) if data_shape_and_dtype else False

    def get_data_value(self, pos):
        data = self.data
        if self.is_data_1d:
            if data is not None:
                return data[pos[0]]
        elif self.is_data_2d:
            if data is not None:
                return data[pos[0], pos[1]]
        elif self.is_data_3d:
            if data is not None:
                return data[pos[0], pos[1], pos[2]]
        return None

    @property
    def size_and_data_format_as_string(self):
        dimensional_shape = self.dimensional_shape
        data_dtype = self.data_dtype
        if dimensional_shape is not None and data_dtype is not None:
            spatial_shape_str = " x ".join([str(d) for d in dimensional_shape])
            if len(dimensional_shape) == 1:
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
                    logging.debug("Unknown dtype %s", self.data_dtype.type)
                data_size_and_data_format_as_string = dtype_names[self.data_dtype.type] if self.data_dtype.type in dtype_names else _("Unknown Data Type")
            return "{0}, {1}".format(spatial_shape_str, data_size_and_data_format_as_string)
        return _("No Data")
