"""
    Provide symbolic math services.

    The goal is to provide a module (namespace) where users can be provided with variables representing
    data items (directly or indirectly via reference to workspace panels).

    DataNodes represent data items, operations, numpy arrays, and constants.
"""

# futures
from __future__ import absolute_import

# standard libraries
import copy
import datetime
import logging
import numbers
import operator
import uuid

# third party libraries
import numpy

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import DataAndMetadata


def range(data):
    return numpy.amax(data) - numpy.amin(data)

def take_slice(data, key):
    return data[key].copy()

_function_map = {
    "abs": operator.abs,
    "neg": operator.neg,
    "pos": operator.pos,
    "add": operator.add,
    "sub": operator.sub,
    "mul": operator.mul,
    "div": operator.truediv,
    "truediv": operator.truediv,
    "floordiv": operator.floordiv,
    "mod": operator.mod,
    "pow": operator.pow,
    "slice": take_slice,
    "amin": numpy.amin,
    "amax": numpy.amax,
    "range": range,
    "median": numpy.median,
    "average": numpy.average,
    "mean": numpy.mean,
    "std": numpy.std,
    "var": numpy.var,
    "log": numpy.log,
    "log10": numpy.log10,
    "log2": numpy.log2,
}


class DataNode(object):

    def __init__(self, inputs=None):
        self.inputs = inputs if inputs is not None else list()
        self.scalar = None

    @classmethod
    def factory(cls, d):
        data_node_type = d["data_node_type"]
        assert data_node_type in _node_map
        node = _node_map[data_node_type]()
        node.read(d)
        return node

    def read(self, d):
        inputs = list()
        input_dicts = d.get("inputs", list())
        for input_dict in input_dicts:
            node = DataNode.factory(input_dict)
            node.read(input_dict)
            inputs.append(node)
        self.inputs = inputs
        return d

    def write(self):
        d = dict()
        input_dicts = list()
        for input in self.inputs:
            input_dicts.append(input.write())
        if len(input_dicts) > 0:
            d["inputs"] = input_dicts
        return d

    @classmethod
    def make(cls, value):
        if isinstance(value, DataNode):
            return value
        elif isinstance(value, numbers.Integral):
            return ConstantDataNode(value)
        elif isinstance(value, numbers.Rational):
            return ConstantDataNode(value)
        elif isinstance(value, numbers.Real):
            return ConstantDataNode(value)
        elif isinstance(value, numbers.Complex):
            return ConstantDataNode(value)
        elif isinstance(value, DataItemDataNode):
            return value
        assert False
        return None

    def get_data_and_metadata(self, resolve):
        data_and_metadata_list = list()
        for input in self.inputs:
            data_and_metadata = input.get_data_and_metadata(resolve)
            if data_and_metadata is None:
                data = numpy.array(input.scalar)
                data_and_metadata = DataAndMetadata.DataAndMetadata(lambda: data, (data.shape, data.dtype),
                                                                    Calibration.Calibration(), list(), dict(),
                                                                    datetime.datetime.utcnow())
            data_and_metadata_list.append(data_and_metadata)
        return self._get_data_and_metadata(data_and_metadata_list, resolve)

    @property
    def data_reference_uuids(self):
        data_reference_uuids = list()
        for input in self.inputs:
            data_reference_uuids.extend(input.data_reference_uuids)
        return data_reference_uuids

    def _get_data_and_metadata(self, data_and_metadata_list, resolve):
        return None  # fall back on scalar

    def __abs__(self):
        return UnaryOperationDataNode([self], "abs")

    def __neg__(self):
        return UnaryOperationDataNode([self], "neg")

    def __pos__(self):
        return UnaryOperationDataNode([self], "pos")

    def __add__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "add")

    def __radd__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "add")

    def __sub__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "sub")

    def __rsub__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "sub")

    def __mul__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "mul")

    def __rmul__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "mul")

    def __div__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "div")

    def __rdiv__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "div")

    def __truediv__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "truediv")

    def __rtruediv__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "truediv")

    def __floordiv__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "floordiv")

    def __rfloordiv__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "floordiv")

    def __mod__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "mod")

    def __rmod__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "mod")

    def __pow__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "pow")

    def __rpow__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "pow")

    def __complex__(self):
        return ConstantDataNode(numpy.astype(numpy.complex128))

    def __int__(self):
        return ConstantDataNode(numpy.astype(numpy.uint32))

    def __long__(self):
        return ConstantDataNode(numpy.astype(numpy.int64))

    def __float__(self):
        return ConstantDataNode(numpy.astype(numpy.float64))

    def __getitem__(self, key):
        return UnaryOperationDataNode([self], "slice", {"key": key})


def min(data_node):
    return ScalarOperationDataNode([data_node], "amin")

def max(data_node):
    return ScalarOperationDataNode([data_node], "amax")

def range(data_node):
    return ScalarOperationDataNode([data_node], "range")

def median(data_node):
    return ScalarOperationDataNode([data_node], "median")

def average(data_node):
    return ScalarOperationDataNode([data_node], "average")

def mean(data_node):
    return ScalarOperationDataNode([data_node], "mean")

def std(data_node):
    return ScalarOperationDataNode([data_node], "std")

def var(data_node):
    return ScalarOperationDataNode([data_node], "var")

def log(data_node):
    return UnaryOperationDataNode([data_node], "log")

def log10(data_node):
    return UnaryOperationDataNode([data_node], "log10")

def log2(data_node):
    return UnaryOperationDataNode([data_node], "log2")


class ConstantDataNode(DataNode):

    def __init__(self, value=None):
        super(ConstantDataNode, self).__init__()
        self.scalar = numpy.array(value)
        if isinstance(value, numbers.Integral):
            self.scalar_type = "integral"
        elif isinstance(value, numbers.Rational):
            self.scalar_type = "rational"
        elif isinstance(value, numbers.Real):
            self.scalar_type = "real"
        elif isinstance(value, numbers.Complex):
            self.scalar_type = "complex"
        # else:
        #     raise Exception("Invalid constant type [{}].".format(type(value)))

    def read(self, d):
        super(ConstantDataNode, self).read(d)
        scalar_type = d.get("scalar_type")
        if scalar_type == "integral":
            self.scalar = numpy.array(int(d["value"]))
        elif scalar_type == "real":
            self.scalar = numpy.array(float(d["value"]))
        elif scalar_type == "complex":
            self.scalar = numpy.array(complex(*d["value"]))

    def write(self):
        d = super(ConstantDataNode, self).write()
        d["data_node_type"] = "constant"
        d["scalar_type"] = self.scalar_type
        value = self.scalar
        if self.scalar_type == "integral":
            d["value"] = int(value)
        elif isinstance(value, numbers.Rational):
            pass
        elif self.scalar_type == "real":
            d["value"] = float(value)
        elif self.scalar_type == "complex":
            d["value"] = complex(float(value.real), float(value.imag))
        return d

    def __str__(self):
        return "{0} ({1})".format(self.__repr__(), self.scalar)


class ScalarOperationDataNode(DataNode):

    def __init__(self, inputs=None, function_id=None, args=None):
        super(ScalarOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def read(self, d):
        super(ScalarOperationDataNode, self).read(d)
        function_id = d.get("function_id")
        assert function_id in _function_map
        self.__function_id = function_id
        args = d.get("args")
        self.__args = copy.copy(args if args is not None else dict())

    def write(self):
        d = super(ScalarOperationDataNode, self).write()
        d["data_node_type"] = "scalar"
        d["function_id"] = self.__function_id
        if self.__args:
            d["args"] = self.__args
        return d

    def _get_data_and_metadata(self, data_and_metadata_list, resolve):
        def calculate_data():
            return _function_map[self.__function_id](data_and_metadata_list[0].data, **self.__args)

        return DataAndMetadata.DataAndMetadata(calculate_data, data_and_metadata_list[0].data_shape_and_dtype,
                                               Calibration.Calibration(), list(), dict(), datetime.datetime.utcnow())

    def __str__(self):
        return "{0} {1}({2})".format(self.__repr__(), self.__function_id, self.inputs[0])


class UnaryOperationDataNode(DataNode):

    def __init__(self, inputs=None, function_id=None, args=None):
        super(UnaryOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def read(self, d):
        super(UnaryOperationDataNode, self).read(d)
        function_id = d.get("function_id")
        assert function_id in _function_map
        self.__function_id = function_id
        args = d.get("args")
        self.__args = copy.copy(args if args is not None else dict())

    def write(self):
        d = super(UnaryOperationDataNode, self).write()
        d["data_node_type"] = "unary"
        d["function_id"] = self.__function_id
        if self.__args:
            d["args"] = self.__args
        return d

    def _get_data_and_metadata(self, data_and_metadata_list, resolve):
        def calculate_data():
            return _function_map[self.__function_id](data_and_metadata_list[0].data, **self.__args)

        return DataAndMetadata.DataAndMetadata(calculate_data, data_and_metadata_list[0].data_shape_and_dtype,
                                               data_and_metadata_list[0].intensity_calibration,
                                               data_and_metadata_list[0].dimensional_calibrations,
                                               data_and_metadata_list[0].metadata, datetime.datetime.utcnow())

    def __str__(self):
        return "{0} {1}({2})".format(self.__repr__(), self.__function_id, self.inputs[0])


class BinaryOperationDataNode(DataNode):

    def __init__(self, inputs=None, function_id=None, args=None):
        super(BinaryOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def read(self, d):
        super(BinaryOperationDataNode, self).read(d)
        function_id = d.get("function_id")
        assert function_id in _function_map
        self.__function_id = function_id
        args = d.get("args")
        self.__args = copy.copy(args if args is not None else dict())

    def write(self):
        d = super(BinaryOperationDataNode, self).write()
        d["data_node_type"] = "binary"
        d["function_id"] = self.__function_id
        if self.__args:
            d["args"] = self.__args
        return d

    def _get_data_and_metadata(self, data_and_metadata_list, resolve):
        def calculate_data():
            return _function_map[self.__function_id](data_and_metadata_list[0].data, data_and_metadata_list[1].data, **self.__args)

        return DataAndMetadata.DataAndMetadata(calculate_data, data_and_metadata_list[0].data_shape_and_dtype,
                                               data_and_metadata_list[0].intensity_calibration,
                                               data_and_metadata_list[0].dimensional_calibrations,
                                               data_and_metadata_list[0].metadata, datetime.datetime.utcnow())

    def __str__(self):
        return "{0} {1}({2}, {3})".format(self.__repr__(), self.__function_id, self.inputs[0], self.inputs[1])


class DataItemDataNode(DataNode):

    def __init__(self, data_reference=None):
        super(DataItemDataNode, self).__init__()
        self.__data_reference_uuid = data_reference.uuid if data_reference else uuid.uuid4()

    def read(self, d):
        super(DataItemDataNode, self).read(d)
        data_reference_uuid_str = d.get("data_reference_uuid")
        if data_reference_uuid_str:
            self.__data_reference_uuid = uuid.UUID(data_reference_uuid_str)

    def write(self):
        d = super(DataItemDataNode, self).write()
        d["data_node_type"] = "data"
        if self.__data_reference_uuid:
            d["data_reference_uuid"] = str(self.__data_reference_uuid)
        return d

    @property
    def data_reference_uuid(self):
        return self.__data_reference_uuid

    @property
    def data_reference_uuids(self):
        return [self.__data_reference_uuid]

    def _get_data_and_metadata(self, data_and_metadata_list, resolve):
        return resolve(self.__data_reference_uuid) if self.__data_reference_uuid else None

    def __str__(self):
        return "{0} ({1})".format(self.__repr__(), self.__data_reference_uuid)


_node_map = {
    "constant": ConstantDataNode,
    "scalar": ScalarOperationDataNode,
    "unary": UnaryOperationDataNode,
    "binary": BinaryOperationDataNode,
    "data": DataItemDataNode
}


def parse_expression(calculation_script, weak_data_item_variable_map):
    code_lines = []
    code_lines.append("from nion.swift.model.Symbolic import *")
    g = dict()
    l = dict()
    mapping = dict()
    for data_item_ref in weak_data_item_variable_map:
        data_item = data_item_ref()
        if data_item:
            data_item_var = weak_data_item_variable_map[data_item_ref]
            data_reference = DataItemDataNode()
            mapping[data_reference.data_reference_uuid] = data_item
            g[data_item_var] = data_reference
    code_lines.append("result = {0}".format(calculation_script))
    code = "\n".join(code_lines)
    exec(code, g, l)
    return l["result"], mapping


#d1 = DataNode(title="data1")
#d2 = DataNode(title="data2")

#print((d1 + d2).crop(((0.25, 0.25), (0.5, 0.5))) - 120)
#print d1
#print 3 + d1 + d2
#print -d1

# -r100
# r100 * 10
# r100 - min(r100)
