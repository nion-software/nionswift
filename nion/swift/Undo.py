import abc
import gettext


_ = gettext.gettext


class UndoableCommand(abc.ABC):

    @abc.abstractmethod
    def close(self):
        pass

    @property
    @abc.abstractmethod
    def title(self) -> str:
        return str()

    @title.setter
    @abc.abstractmethod
    def title(self, title: str) -> None:
        pass

    @abc.abstractmethod
    def undo(self) -> None:
        pass

    @abc.abstractmethod
    def redo(self) -> None:
        pass


class UndoStack:

    def __init__(self):
        # undo/redo stack. next item is at the end.
        self.__undo_stack = list()
        self.__redo_stack = list()

    @property
    def can_redo(self) -> bool:
        return len(self.__redo_stack) > 0

    @property
    def can_undo(self) -> bool:
        return len(self.__undo_stack) > 0

    @property
    def undo_title(self) -> str:
        if self.can_undo:
            return _("Undo") + " " + self.__undo_stack[-1].title
        return _("Undo")

    @property
    def redo_title(self) -> str:
        if self.can_redo:
            return _("Redo") + " " + self.__redo_stack[-1].title
        return _("Redo")

    def clear(self) -> None:
        # close current to last
        while len(self.__redo_stack) > 0:
            self.__redo_stack.pop().close()
        # close current to first
        while (len(self.__undo_stack)) > 0:
            self.__undo_stack.pop().close()

    def undo(self) -> None:
        assert len(self.__undo_stack) > 0
        undo_command = self.__undo_stack.pop()
        undo_command.undo()
        self.__redo_stack.append(undo_command)

    def redo(self) -> None:
        assert len(self.__redo_stack) > 0
        undo_command = self.__redo_stack.pop()
        undo_command.redo()
        self.__undo_stack.append(undo_command)

    def push(self, undo_command: UndoableCommand) -> None:
        assert undo_command
        # close current to last
        self.__undo_stack.append(undo_command)
        while len(self.__redo_stack) > 0:
            self.__redo_stack.pop().close()
