"""Deprecated. Hardware source has been moved to nionswift-instrumentation-kit.

For backwards compatibility, a few functions are provided until all packages can be migrated to
the new API available in nionswift-instrumentation-kit.
"""
import contextlib
import numpy
import typing

from nion.utils import Registry


class HardwareSourceManagerInterface:
    def register_hardware_source(self, hardware_source) -> None: ...
    def get_all_instrument_ids(self) -> typing.List[str]: ...
    def get_all_hardware_source_ids(self) -> typing.List[str]: ...
    def get_instrument_by_id(self, instrument_id) -> typing.Any: ...
    def get_hardware_source_for_hardware_source_id(self, hardware_source_id: str) -> typing.Any: ...
    def make_delegate_hardware_source(self, delegate, hardware_source_id: str, hardware_source_name: str) -> typing.Any: ...


def hardware_source_manager() -> HardwareSourceManagerInterface:
    return typing.cast(HardwareSourceManagerInterface, Registry.get_component("hardware_source_manager"))


def HardwareSourceManager():
    return hardware_source_manager()


@contextlib.contextmanager
def get_data_generator_by_id(hardware_source_id: str, sync: bool = True) -> typing.Any:
    """Return a generator for data.

    :param bool sync: whether to wait for current frame to finish then collect next frame

    NOTE: a new ndarray is created for each call.
    """
    hardware_source = HardwareSourceManager().get_hardware_source_for_hardware_source_id(hardware_source_id)

    def get_last_data() -> numpy.ndarray:
        return hardware_source.get_next_xdatas_to_finish()[0].data.copy()

    yield get_last_data
