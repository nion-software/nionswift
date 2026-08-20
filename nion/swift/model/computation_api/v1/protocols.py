"""Protocols and public types for computation API v1."""

import abc
import typing

from nion.data import annotated_array
import nion.swift.model.Graphics

AnnotatedArray: typing.TypeAlias = annotated_array.AnnotatedArray
RegionBase: typing.TypeAlias = nion.swift.model.Graphics.RegionBase

ScalarValue = typing.Union[float, int, bool, complex, str, None]
ComputationLeafValue = typing.Union[AnnotatedArray, RegionBase, ScalarValue]
ComputationValue = typing.Union[ComputationLeafValue, typing.Sequence["ComputationValue"], typing.Mapping[str, "ComputationValue"]]
OutputScalarValue = typing.Union[float, int, bool, complex, str]
OutputValue = typing.Union[AnnotatedArray, OutputScalarValue]
Outputs = typing.Mapping[str, OutputValue]


class Parameters(typing.Protocol):
    """Typed access to computation parameters with strict extraction rules."""

    def get_float(self, key: str, default: float | None = None) -> float: ...
    def get_int(self, key: str, default: int | None = None) -> int: ...
    def get_bool(self, key: str, default: bool | None = None) -> bool: ...
    def get_str(self, key: str, default: str | None = None) -> str: ...
    def get_complex(self, key: str, default: complex | None = None) -> complex: ...
    def get_annotated_array(self, key: str) -> AnnotatedArray: ...
    def get_region(self, key: str) -> RegionBase: ...
    def get_list(self, key: str) -> typing.Sequence[ComputationValue]: ...
    def get_map(self, key: str) -> typing.Mapping[str, ComputationValue]: ...


class Executor(abc.ABC):
    """Base class for computation executors registered by plugins."""

    @abc.abstractmethod
    def execute(self, parameters: Parameters) -> Outputs:
        """Execute a computation operation with typed parameters."""
        raise NotImplementedError


__all__ = ["AnnotatedArray", "Executor", "Parameters", "RegionBase"]

