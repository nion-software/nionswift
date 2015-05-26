# futures
from __future__ import absolute_import
from __future__ import division

# standard libraries
import types

# third party libraries
import numpy

# local libraries
from nion.ui import Unicode


class Calibration(object):

    """
        Represents a transformation from one coordinate system to another.

        Uses a transformation x' = x * scale + offset
    """

    def __init__(self, offset=None, scale=None, units=None):
        super(Calibration, self).__init__()
        self.__offset = float(offset) if offset else None
        self.__scale = float(scale) if scale else None
        self.__units = Unicode.u(units) if units else None

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.offset == other.offset and self.scale == other.scale and self.units == other.units
        return False

    def __str__(self):
        return "{0:s} offset:{1:g} scale:{2:g} units:\'{3:s}\'".format(self.__repr__(), self.offset, self.scale, self.units)

    def __copy__(self):
        return type(self)(self.__offset, self.__scale, self.__units)

    def read_dict(self, storage_dict):
        self.offset = storage_dict["offset"] if "offset" in storage_dict else None
        self.scale = storage_dict["scale"] if "scale" in storage_dict else None
        self.units = storage_dict["units"] if "units" in storage_dict else None
        return self  # for convenience

    def write_dict(self):
        storage_dict = dict()
        storage_dict["offset"] = self.offset
        storage_dict["scale"] = self.scale
        storage_dict["units"] = self.units
        return storage_dict

    @classmethod
    def from_rpc_dict(cls, d):
        if d is None:
            return None
        return Calibration(d.get("offset"), d.get("scale"), d.get("units"))

    @property
    def rpc_dict(self):
        d = dict()
        if self.__offset: d["offset"] = self.__offset
        if self.__scale: d["scale"] = self.__scale
        if self.__units: d["units"] = self.__units
        return d

    @property
    def is_calibrated(self):
        return self.__offset is not None or self.__scale is not None or self.__units is not None

    def clear(self):
        self.__offset = None
        self.__scale = None
        self.__units = None

    @property
    def offset(self):
        return self.__offset if self.__offset else 0.0

    @offset.setter
    def offset(self, value):
        self.__offset = float(value) if value else None

    @property
    def scale(self):
        return self.__scale if self.__scale else 1.0

    @scale.setter
    def scale(self, value):
        self.__scale = float(value) if value else None

    @property
    def units(self):
        return self.__units if self.__units else Unicode.u()

    @units.setter
    def units(self, value):
        self.__units = Unicode.u(value) if value else None

    def convert_to_calibrated_value(self, value):
        return self.offset + value * self.scale

    def convert_to_calibrated_size(self, size):
        return size * self.scale

    def convert_from_calibrated_value(self, value):
        return (value - self.offset) / self.scale

    def convert_from_calibrated_size(self, size):
        return size / self.scale

    def convert_to_calibrated_value_str(self, value, include_units=True):
        units_str = (" " + self.units) if include_units and self.__units else ""
        if hasattr(value, 'dtype') and not value.shape:  # convert NumPy types to Python scalar types
            value = numpy.asscalar(value)
        if isinstance(value, types.IntType) or isinstance(value, types.LongType):
            result = u"{0:g}{1:s}".format(self.convert_to_calibrated_value(value), units_str)
        elif isinstance(value, types.FloatType) or isinstance(value, types.ComplexType):
            result = u"{0:g}{1:s}".format(self.convert_to_calibrated_value(value), units_str)
        elif isinstance(value, numpy.ndarray) and numpy.ndim(value) == 1 and value.shape[0] in (3, 4) and value.dtype == numpy.uint8:
            result = u", ".join([u"{0:d}".format(v) for v in value])
        else:
            result = None
        return result

    def convert_to_calibrated_size_str(self, size, include_units=True):
        units_str = (" " + self.units) if include_units and self.__units else ""
        if hasattr(size, 'dtype') and not size.shape:  # convert NumPy types to Python scalar types
            size = numpy.asscalar(size)
        if isinstance(size, types.IntType) or isinstance(size, types.LongType):
            result = u"{0:g}{1:s}".format(self.convert_to_calibrated_size(size), units_str)
        elif isinstance(size, types.FloatType) or isinstance(size, types.ComplexType):
            result = u"{0:g}{1:s}".format(self.convert_to_calibrated_size(size), units_str)
        elif isinstance(size, numpy.ndarray) and numpy.ndim(size) == 1 and size.shape[0] in (3, 4) and size.dtype == numpy.uint8:
            result = u", ".join([u"{0:d}".format(v) for v in size])
        else:
            result = None
        return result
