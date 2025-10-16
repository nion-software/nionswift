from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing
import uuid

import numpy
import numpy.typing

from nion.data import DataAndMetadata


PersistentDictType = typing.Dict[str, typing.Any]
_NDArray = numpy.typing.NDArray[typing.Any]


class StorageHandlerFactoryLike(typing.Protocol):

    def get_storage_handler_type(self) -> str: ...

    def is_matching(self, file_path: str) -> bool: ...

    def make(self, file_path: pathlib.Path) -> StorageHandler: ...

    def make_path(self, file_path: pathlib.Path) -> str: ...

    def get_extension(self) -> str: ...


class StorageHandler(typing.Protocol):
    """
    Protocol for storage handler implementations that manage reading and writing data and properties
    to persistent storage backends.
    """

    def close(self) -> None:
        """Close the storage handler and release any resources."""
        ...

    @property
    def factory(self) -> StorageHandlerFactoryLike:
        """Return the factory that created this storage handler. Used for moving and restoring items."""
        raise NotImplementedError()

    @property
    def storage_handler_type(self) -> str:
        """Return the type identifier for this storage handler."""
        raise NotImplementedError()

    @property
    def reference(self) -> str:
        """Return a unique reference string for this storage handler. Represents the file on disk."""
        raise NotImplementedError()

    @property
    def is_valid(self) -> bool:
        """Return True if the storage handler is valid and usable."""
        raise NotImplementedError()

    def read_properties(self) -> PersistentDictType:
        """Read and return the persistent properties from storage."""
        ...

    def read_data(self) -> typing.Optional[_NDArray]:
        """Read and return the data array from storage, or None if not available."""
        ...

    def write_properties(self, properties: PersistentDictType, file_datetime: datetime.datetime) -> None:
        """Write the given properties to storage with the specified file datetime."""
        ...

    def write_data(self, data: _NDArray, data_descriptor: DataAndMetadata.DataDescriptor, file_datetime: datetime.datetime) -> None:
        """Write the given data array and descriptor to storage with the specified file datetime."""
        ...

    def reserve_data(self, data_shape: typing.Tuple[int, ...], data_dtype: numpy.typing.DTypeLike, data_descriptor: DataAndMetadata.DataDescriptor, file_datetime: datetime.datetime) -> None:
        """Reserve space for data in storage with the given shape, dtype, descriptor, and file datetime."""
        ...

    def prepare_move(self) -> None:
        """Prepare the storage handler for moving or renaming the underlying storage."""
        ...

    def remove(self) -> None:
        """Remove the storage and all associated data."""
        ...


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
