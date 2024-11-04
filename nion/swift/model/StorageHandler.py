from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing
import uuid

import numpy
import numpy.typing


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


@dataclasses.dataclass
class StorageHandlerAttributes:
    """Attributes for organizing within storage system."""
    uuid: uuid.UUID
    created_local: datetime.datetime
    session_id: str | None
    n_bytes: int
    _force_large_format: bool = False


class StorageHandlerProvider(typing.Protocol):
    def make_storage_handler(self, attributes: StorageHandlerAttributes) -> StorageHandler: ...


@dataclasses.dataclass
class StorageHandlerImportData:
    storage_handlers: typing.Sequence[StorageHandler]
    uuid_map: typing.Mapping[uuid.UUID, uuid.UUID]
    items: typing.Sequence[PersistentDictType]


class StorageHandlerExportDataItem(typing.Protocol):
    def write_to_dict(self) -> PersistentDictType: ...

    @property
    def data(self) -> _NDArray: raise NotImplementedError()


class StorageHandlerExportItem(typing.Protocol):
    def write_to_dict(self) -> PersistentDictType: ...

    @property
    def data_items(self) -> typing.Sequence[StorageHandlerExportDataItem]: raise NotImplementedError()
