import abc


class UndeleteBase(abc.ABC):

    @abc.abstractmethod
    def close(self) -> None: ...

    @abc.abstractmethod
    def undelete(self, document_model) -> None: ...


class UndeleteLog:

    def __init__(self):
        self.__items = list()

    def close(self):
        for item in self.__items:
            item.close()
        self.__items = None

    def append(self, item: UndeleteBase) -> None:
        self.__items.append(item)

    def undelete_all(self, document_model) -> None:
        for entry in reversed(self.__items):
            entry.undelete(document_model)
