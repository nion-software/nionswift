# standard libraries
import copy
import logging
import types

# third party libraries
import numpy

# local libraries
# None
from nion.swift import Storage


class Calibration(object):
    def __init__(self, origin=None, scale=None, units=None):
        super(Calibration, self).__init__()
        self.__origin = float(origin) if origin else None
        self.__scale = float(scale) if scale else None
        self.__units = unicode(units) if units else None

    def __str__(self):
        return "{0:s} origin:{1:g} scale:{2:g} units:\'{3:s}\'".format(self.__repr__(), self.origin, self.scale, self.units)

    def __copy__(self):
        return type(self)(self.__origin, self.__scale, self.__units)

    def __get_is_calibrated(self):
        return self.__origin is not None or self.__scale is not None or self.__units is not None
    is_calibrated = property(__get_is_calibrated)

    def clear(self):
        self.__origin = None
        self.__scale = None
        self.__units = None

    def __get_origin(self):
        return self.__origin if self.__origin else 0.0
    def __set_origin(self, value):
        value = float(value) if value else None
        if self.__origin != value:
            self.__origin = value
    origin = property(__get_origin, __set_origin)

    def __get_scale(self):
        return self.__scale if self.__scale else 1.0
    def __set_scale(self, value):
        value = float(value) if value else None
        if self.__scale != value:
            self.__scale = value
    scale = property(__get_scale, __set_scale)

    def __get_units(self):
        return self.__units if self.__units else unicode()
    def __set_units(self, value):
        value = unicode(value) if value else None
        if self.units != value:
            self.__units = value
    units = property(__get_units, __set_units)

    def convert_to_calibrated_value(self, value):
        return self.origin + value * self.scale
    def convert_to_calibrated_size(self, size):
        return size * self.scale
    def convert_from_calibrated_value(self, value):
        return (value - self.origin) / self.scale
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


class CalibrationItem(Storage.StorageBase):
    def __init__(self, origin=None, scale=None, units=None, calibration=None):
        super(CalibrationItem, self).__init__()
        # TODO: add optional saving for these items
        self.storage_properties += ["origin", "scale", "units"]
        self.storage_type = "calibration"
        self.calibration = copy.copy(calibration) if calibration else Calibration(origin, scale, units)

    @classmethod
    def build(cls, datastore, item_node, uuid_):
        origin = datastore.get_property(item_node, "origin", None)
        scale = datastore.get_property(item_node, "scale", None)
        units = datastore.get_property(item_node, "units", None)
        calibration = Calibration(origin, scale, units)
        return cls(calibration=calibration)

    def __deepcopy__(self, memo):
        calibration_item = CalibrationItem(calibration=self.calibration)
        memo[id(self)] = calibration_item
        return calibration_item

    def __str__(self):
        return "{0:s} origin:{1:g} scale:{2:g} units:\'{3:s}\'".format(self.__repr__(), self.origin, self.scale, self.units)

    def __get_is_calibrated(self):
        return self.calibration.is_calibrated
    is_calibrated = property(__get_is_calibrated)

    def clear(self):
        self.calibration.clear()

    def __get_origin(self):
        return self.calibration.origin
    def __set_origin(self, value):
        self.calibration.origin = value
        self.notify_set_property("origin", value)
    origin = property(__get_origin, __set_origin)

    def __get_scale(self):
        return self.calibration.scale
    def __set_scale(self, value):
        self.calibration.scale = value
        self.notify_set_property("scale", value)
    scale = property(__get_scale, __set_scale)

    def __get_units(self):
        return self.calibration.units
    def __set_units(self, value):
        self.calibration.units = value
        self.notify_set_property("units", value)
    units = property(__get_units, __set_units)

    # pass these through to calibration object
    def convert_to_calibrated_value(self, value):
        return self.calibration.convert_to_calibrated_value(value)
    def convert_to_calibrated_size(self, size):
        return self.calibration.convert_to_calibrated_size(size)
    def convert_from_calibrated_value(self, value):
        return self.calibration.convert_from_calibrated_value(value)
    def convert_from_calibrated_size(self, size):
        return self.calibration.convert_from_calibrated_size(size)
    def convert_to_calibrated_value_str(self, value, include_units=True):
        return self.calibration.convert_to_calibrated_value_str(value, include_units)
    def convert_to_calibrated_size_str(self, size, include_units=True):
        return self.calibration.convert_to_calibrated_size_str(size, include_units)

    def notify_set_property(self, key, value):
        super(CalibrationItem, self).notify_set_property(key, value)
        self.notify_listeners("calibration_changed", self)