from __future__ import annotations

import abc
import typing

if typing.TYPE_CHECKING:
    from nion.swift.model import DocumentModel


class UndeleteBase(abc.ABC):

    @abc.abstractmethod
    def close(self) -> None: ...

    @abc.abstractmethod
    def undelete(self, document_model: DocumentModel.DocumentModel) -> None: ...


class UndeleteLog:
    count = 0  # useful for detecting leaks in tests

    def __init__(self) -> None:
        UndeleteLog.count += 1
        self.__items : typing.List[UndeleteBase] = list()

    def close(self) -> None:
        for item in self.__items:
            item.close()
        self.__items = typing.cast(typing.Any, None)
        UndeleteLog.count -= 1

    def append(self, item: UndeleteBase) -> None:
        self.__items.append(item)

    def undelete_all(self, document_model: DocumentModel.DocumentModel) -> None:
        for entry in reversed(self.__items):
            entry.undelete(document_model)

    @property
    def _items(self) -> typing.List[UndeleteBase]:
        return self.__items
