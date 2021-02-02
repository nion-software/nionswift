from __future__ import annotations

import abc
import typing

if typing.TYPE_CHECKING:
    import datetime
    import pathlib
    import numpy


class StorageHandler(abc.ABC):

    @classmethod
    @abc.abstractmethod
    def is_matching(cls, file_path: str) -> bool: ...

    @classmethod
    @abc.abstractmethod
    def make(cls, file_path: pathlib.Path) -> StorageHandler: ...

    @classmethod
    @abc.abstractmethod
    def make_path(cls, file_path: pathlib.Path) -> str: ...

    def close(self) -> None:
        pass

    @property
    @abc.abstractmethod
    def reference(self) -> str: ...

    @property
    @abc.abstractmethod
    def is_valid(self) -> bool: ...

    @abc.abstractmethod
    def read_properties(self) -> typing.Dict: ...

    @abc.abstractmethod
    def read_data(self) -> typing.Optional[numpy.ndarray]: ...

    @abc.abstractmethod
    def write_properties(self, properties, file_datetime: datetime.datetime): ...

    @abc.abstractmethod
    def write_data(self, data, file_datetime: datetime.datetime): ...

    @abc.abstractmethod
    def reserve_data(self, data_shape: typing.Tuple[int, ...], data_dtype: numpy.dtype, file_datetime: datetime.datetime) -> None: ...

    @abc.abstractmethod
    def prepare_move(self) -> None: ...

    @abc.abstractmethod
    def remove(self) -> None: ...


# class FileStorageHandler(StorageHandler):
