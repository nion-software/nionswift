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
import logging
import numbers
import operator

# third party libraries
import numpy

# local libraries
from nion.swift.model import DataItem


def take_slice(data, key):
    return data[key].copy()

_function_map = {
    "abs": operator.abs,
    "neg": operator.neg,
    "pos": operator.pos,
    "add": operator.add,
    "sub": operator.sub,
    "mul": operator.mul,
    "div": operator.div,
    "truediv": operator.truediv,
    "floordiv": operator.floordiv,
    "mod": operator.mod,
    "pow": operator.pow,
    "slice": take_slice,
    "log": numpy.log,
    "log10": numpy.log10,
    "log2": numpy.log2,
}


class DataNode(object):

    def __init__(self, inputs=None):
        self.inputs = inputs if inputs is not None else list()
        self.scalar = None

    @classmethod
    def factory(cls, d, resolve):
        data_node_type = d["data_node_type"]
        assert data_node_type in _node_map
        node = _node_map[data_node_type]()
        node.read(d, resolve)
        return node

    def read(self, d, resolve):
        inputs = list()
        input_dicts = d.get("inputs", list())
        for input_dict in input_dicts:
            node = DataNode.factory(input_dict, resolve)
            node.read(input_dict, resolve)
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
            return ScalarDataNode(value)
        elif isinstance(value, numbers.Rational):
            return ScalarDataNode(value)
        elif isinstance(value, numbers.Real):
            return ScalarDataNode(value)
        elif isinstance(value, numbers.Complex):
            return ScalarDataNode(value)
        elif isinstance(value, DataItem.DataItem):
            return DataItemDataNode(value)
        assert False
        return None

    def __get_data(self):
        data_list = list()
        for input in self.inputs:
            data = input.data
            data = data if data is not None else input.scalar
            data_list.append(data)
        return self._get_data(data_list)
    data = property(__get_data)

    def _get_data(self, data_list):
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
        return ScalarDataNode(numpy.astype(numpy.complex128))

    def __int__(self):
        return ScalarDataNode(numpy.astype(numpy.uint32))

    def __long__(self):
        return ScalarDataNode(numpy.astype(numpy.int64))

    def __float__(self):
        return ScalarDataNode(numpy.astype(numpy.float64))

    def __getitem__(self, key):
        return UnaryOperationDataNode([self], "slice", {"key": key})


def min(data_node):
    return ScalarDataNode(numpy.amin(data_node.data))

def max(data_node):
    return ScalarDataNode(numpy.amax(data_node.data))

def range(data_node):
    return ScalarDataNode(numpy.amax(data_node.data) - numpy.amin(data_node.data))

def median(data_node):
    return ScalarDataNode(numpy.median(data_node.data))

def average(data_node):
    return ScalarDataNode(numpy.average(data_node.data))

def mean(data_node):
    return ScalarDataNode(numpy.mean(data_node.data))

def std(data_node):
    return ScalarDataNode(numpy.std(data_node.data))

def var(data_node):
    return ScalarDataNode(numpy.var(data_node.data))

def log(data_node):
    return UnaryOperationDataNode([data_node], "log")

def log10(data_node):
    return UnaryOperationDataNode([data_node], "log10")

def log2(data_node):
    return UnaryOperationDataNode([data_node], "log2")


class ScalarDataNode(DataNode):

    def __init__(self, value=None):
        super(ScalarDataNode, self).__init__()
        self.scalar = value

    def read(self, d, resolve):
        super(ScalarDataNode, self).read(d, resolve)
        scalar_type = d.get("scalar_type")
        if scalar_type == "integral":
            self.scalar = int(d["value"])
        elif scalar_type == "real":
            self.scalar = float(d["value"])
        elif scalar_type == "complex":
            self.scalar = complex(*d["value"])

    def write(self):
        d = super(ScalarDataNode, self).write()
        d["data_node_type"] = "scalar"
        value = self.scalar
        if isinstance(value, numbers.Integral):
            d["scalar_type"] = "integral"
            d["value"] = value
        elif isinstance(value, numbers.Rational):
            pass
        elif isinstance(value, numbers.Real):
            d["scalar_type"] = "real"
            d["value"] = value
        elif isinstance(value, numbers.Complex):
            d["scalar_type"] = "complex"
            d["value"] = (value.real, value.imag)
        return d

    def __str__(self):
        return "{0} ({1})".format(self.__repr__(), self.scalar)


class UnaryOperationDataNode(DataNode):

    def __init__(self, inputs=None, function_id=None, args=None):
        super(UnaryOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def read(self, d, resolve):
        super(UnaryOperationDataNode, self).read(d, resolve)
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

    def _get_data(self, data_list):
        return _function_map[self.__function_id](data_list[0], **self.__args)

    def __str__(self):
        return "{0} {1}({2})".format(self.__repr__(), self.__function_id, self.inputs[0])


class BinaryOperationDataNode(DataNode):

    def __init__(self, inputs=None, function_id=None, args=None):
        super(BinaryOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def read(self, d, resolve):
        super(BinaryOperationDataNode, self).read(d, resolve)
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

    def _get_data(self, data_list):
        return _function_map[self.__function_id](data_list[0], data_list[1],  **self.__args)

    def __str__(self):
        return "{0} {1}({2}, {3})".format(self.__repr__(), self.__function_id, self.inputs[0], self.inputs[1])


class DataItemDataNode(DataNode):

    def __init__(self, data_item=None):
        super(DataItemDataNode, self).__init__()
        self.__data_item = data_item

    def read(self, d, resolve):
        super(DataItemDataNode, self).read(d, resolve)
        data_item_uuid = d.get("data_item_uuid")
        if data_item_uuid:
            self.__data_item = resolve(uuid.UUID(data_item_uuid))

    def write(self):
        d = super(DataItemDataNode, self).write()
        d["data_node_type"] = "data"
        if self.__data_item:
            d["data_item_uuid"] = str(self.__data_item.uuid)
        return d

    def _get_data(self, data_list):
        return self.__data_item.maybe_data_source.data if self.__data_item.maybe_data_source else None

    def __str__(self):
        return "{0} ({1})".format(self.__repr__(), self.__data_item.r_var)


_node_map = {
    "scalar": ScalarDataNode,
    "unary": UnaryOperationDataNode,
    "binary": BinaryOperationDataNode,
    "data": DataItemDataNode
}


def execute_code_lines(code_lines, g, l):
    """ Execute a list of code lines in the g, l globals, locals context. """


def calculate(calculation_script, weak_data_item_variable_map):
    code_lines = []
    code_lines.append("from nion.swift.model.Symbolic import *")
    g = dict()
    l = dict()
    for data_item_ref in weak_data_item_variable_map:
        data_item = data_item_ref()
        if data_item:
            data_item_var = weak_data_item_variable_map[data_item_ref]
            g[data_item_var] = DataNode.make(data_item)
    code_lines.append("result = {0}".format(calculation_script))
    code = "\n".join(code_lines)
    exec(code, g, l)
    return l["result"]



#d1 = DataNode(title="data1")
#d2 = DataNode(title="data2")

#print((d1 + d2).crop(((0.25, 0.25), (0.5, 0.5))) - 120)
#print d1
#print 3 + d1 + d2
#print -d1

# -r100
# r100 * 10
# r100 - min(r100)
