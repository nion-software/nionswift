import base64
import copy
import datetime
import pickle
import re


class Calibration:

    """
        Represents a transformation from one coordinate system to another.

        Uses a transformation x' = x * scale + offset
    """

    def __init__(self, offset=None, scale=None, units=None):
        super(Calibration, self).__init__()
        self.__offset = float(offset) if offset else None
        self.__scale = float(scale) if scale else None
        self.__units = str(units) if units else None

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.offset == other.offset and self.scale == other.scale and self.units == other.units
        return False

    def __str__(self):
        return "{0:s} offset:{1:g} scale:{2:g} units:\'{3:s}\'".format(self.__repr__(), self.offset, self.scale, self.units)

    def __copy__(self):
        return type(self)(self.__offset, self.__scale, self.__units)

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
        return self.__units if self.__units else str()

    @units.setter
    def units(self, value):
        self.__units = str(value) if value else None


class DataAndCalibration:
    """Represent the ability to calculate data and provide immediate calibrations."""

    def __init__(self, data_fn, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp):
        assert metadata is not None
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
        data = pickle.loads(base64.b64decode(d["data"].encode('utf-8')))
        data_shape_and_dtype = data.shape, data.dtype  # TODO: DataAndMetadata from_rpc_dict fails for RGB
        intensity_calibration = Calibration.from_rpc_dict(d.get("intensity_calibration"))
        if "dimensional_calibrations" in d:
            dimensional_calibrations = [Calibration.from_rpc_dict(dc) for dc in d.get("dimensional_calibrations")]
        else:
            dimensional_calibrations = None
        metadata = d.get("metadata", {})
        timestamp = datetime.datetime(*map(int, re.split(r'[^\d]', d.get("timestamp")))) if "timestamp" in d else None
        return DataAndCalibration(lambda: data, data_shape_and_dtype, intensity_calibration, dimensional_calibrations, metadata, timestamp)

    @property
    def rpc_dict(self):
        d = dict()
        data = self.data
        if data is not None:
            d["data"] = base64.b64encode(pickle.dumps(data)).decode('utf=8')
        if self.intensity_calibration:
            d["intensity_calibration"] = self.intensity_calibration.rpc_dict
        if self.dimensional_calibrations:
            d["dimensional_calibrations"] = [dimensional_calibration.rpc_dict for dimensional_calibration in self.dimensional_calibrations]
        if self.timestamp:
            d["timestamp"] = self.timestamp.isoformat()
        if self.metadata:
            d["metadata"] = copy.deepcopy(self.metadata)
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

    def get_intensity_calibration(self):
        return self.intensity_calibration

    def get_dimensional_calibration(self, index):
        return self.dimensional_calibrations[index]
