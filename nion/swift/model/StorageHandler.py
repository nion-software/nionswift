from __future__ import annotations

import typing

import numpy
import numpy.typing

if typing.TYPE_CHECKING:
    import datetime
    import pathlib


PersistentDictType = typing.Dict[str, typing.Any]
_NDArray = numpy.typing.NDArray[typing.Any]


class StorageHandlerFactoryLike(typing.Protocol):

    def is_matching(self, file_path: str) -> bool: ...

    def make(self, file_path: pathlib.Path) -> StorageHandler: ...

    def make_path(self, file_path: pathlib.Path) -> str: ...

    def get_extension(self) -> str: ...


class StorageHandler(typing.Protocol):

    def close(self) -> None: ...

    @property
    def factory(self) -> StorageHandlerFactoryLike: raise NotImplementedError()

    @property
    def reference(self) -> str: raise NotImplementedError()

    @property
    def is_valid(self) -> bool: raise NotImplementedError()

    def read_properties(self) -> PersistentDictType: ...

    def read_data(self) -> typing.Optional[_NDArray]: ...

    def write_properties(self, properties: PersistentDictType, file_datetime: datetime.datetime) -> None: ...

    def write_data(self, data: _NDArray, file_datetime: datetime.datetime) -> None: ...

    def reserve_data(self, data_shape: typing.Tuple[int, ...], data_dtype: numpy.typing.DTypeLike, file_datetime: datetime.datetime) -> None: ...

    def prepare_move(self) -> None: ...

    def remove(self) -> None: ...
