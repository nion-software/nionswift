"""Built-in host-side computations.

This module intentionally lives on the nionswift side of the boundary: it
registers concrete executors for built-in operations, but it does not define
or extend the computation API itself.
"""

from __future__ import annotations

import typing

import numpy

from nion.data import annotated_array
from nion.data.annotated_array import primitives
from nion.swift.model.computation_api import v1 as computation_api


class FFTExecutor(computation_api.Executor):
    """Execute the built-in FFT computation."""

    def execute(self, parameters: computation_api.Parameters) -> typing.Mapping[str, typing.Any]:
        source = parameters.get_annotated_array("src")
        return {"target": primitives.fft(source)}


def _validate_window_source(name: str, source: annotated_array.AnnotatedArray) -> annotated_array.AxisGroup:
    """Validate that ``source`` is a suitable target for a windowing operation.

    Windows are only meaningful when multiplied into a scalar or complex signal
    with exactly one axis group. Returns that axis group.
    """
    if len(source.descriptor.axis_groups) != 1:
        raise ValueError(f"{name} requires a source with exactly one axis group, got {len(source.descriptor.axis_groups)}")
    if source.descriptor.value_type not in (annotated_array.ValueType.SCALAR, annotated_array.ValueType.COMPLEX):
        raise ValueError(f"{name} requires a scalar or complex source, got {source.descriptor.value_type!r}")
    return source.descriptor.axis_groups[0]


def _apply_window(source: annotated_array.AnnotatedArray, window: annotated_array.AnnotatedArray) -> annotated_array.AnnotatedArray:
    """Fuse a generated ``window`` into ``source`` by elementwise multiplication.

    This is the nionswift-side counterpart to niondata's standalone window
    generators (`gaussian_window`, `hamming_window`, `hann_window`): the
    generators produce a real-valued window array only, and this function
    performs the multiply so that niondata's primitives can remain pure
    generators. See `Windowing Generators` in the processing-operations design
    document.
    """
    data = numpy.asarray(source.data) * numpy.asarray(window.data)
    return annotated_array.AnnotatedArray(data=data, descriptor=source.descriptor, metadata=source.metadata)


class GaussianWindowExecutor(computation_api.Executor):
    """Execute the built-in Gaussian window computation."""

    def execute(self, parameters: computation_api.Parameters) -> typing.Mapping[str, typing.Any]:
        source = parameters.get_annotated_array("src")
        axis_group = _validate_window_source("gaussian-window", source)
        sigma = parameters.get_float("sigma", 0.3)
        window = primitives.gaussian_window(axis_group, sigma)
        return {"target": _apply_window(source, window)}


class HammingWindowExecutor(computation_api.Executor):
    """Execute the built-in Hamming window computation."""

    def execute(self, parameters: computation_api.Parameters) -> typing.Mapping[str, typing.Any]:
        source = parameters.get_annotated_array("src")
        axis_group = _validate_window_source("hamming-window", source)
        window = primitives.hamming_window(axis_group)
        return {"target": _apply_window(source, window)}


class HannWindowExecutor(computation_api.Executor):
    """Execute the built-in Hann window computation."""

    def execute(self, parameters: computation_api.Parameters) -> typing.Mapping[str, typing.Any]:
        source = parameters.get_annotated_array("src")
        axis_group = _validate_window_source("hann-window", source)
        window = primitives.hann_window(axis_group)
        return {"target": _apply_window(source, window)}


_definitions_registered = False


def register_builtin_computations() -> None:
    """Register all built-in host-side computation executors."""
    global _definitions_registered
    if _definitions_registered:
        return
    computation_api.get_api().register_executor("fft", FFTExecutor())
    computation_api.get_api().register_executor("gaussian-window", GaussianWindowExecutor())
    computation_api.get_api().register_executor("hamming-window", HammingWindowExecutor())
    computation_api.get_api().register_executor("hann-window", HannWindowExecutor())
    _definitions_registered = True


__all__ = [
    "FFTExecutor",
    "GaussianWindowExecutor",
    "HammingWindowExecutor",
    "HannWindowExecutor",
    "register_builtin_computations",
]
