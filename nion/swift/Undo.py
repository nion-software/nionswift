import abc
import gettext


_ = gettext.gettext


class UndoableCommand(abc.ABC):

    def __init__(self):
        self.__old_modified_state = None
        self.__new_modified_state = None

    def close(self):
        self.__old_modified_state = None
        self.__new_modified_state = None

    @property
    @abc.abstractmethod
    def title(self) -> str:
        return str()

    @title.setter
    @abc.abstractmethod
    def title(self, title: str) -> None:
        pass

    @property
    def is_redo_valid(self) -> bool:
        return self.__old_modified_state == self._get_modified_state()

    @property
    def is_undo_valid(self) -> bool:
        return self.__new_modified_state == self._get_modified_state()

    def initialize(self):
        self.__old_modified_state = self._get_modified_state()

    def commit(self):
        self.__new_modified_state = self._get_modified_state()

    def undo(self):
        self._undo()
        self._set_modified_state(self.__old_modified_state)

    def redo(self):
        self._redo()
        self._set_modified_state(self.__new_modified_state)

    @abc.abstractmethod
    def _get_modified_state(self):
        pass

    @abc.abstractmethod
    def _set_modified_state(self, modified_state) -> None:
        pass

    @abc.abstractmethod
    def _undo(self) -> None:
        pass

    def _redo(self) -> None:
        self._undo()


class UndoStack:

    def __init__(self):
        # undo/redo stack. next item is at the end.
        self.__undo_stack = list()
        self.__redo_stack = list()

    @property
    def can_redo(self) -> bool:
        return len(self.__redo_stack) > 0 and self.__redo_stack[-1].is_redo_valid

    @property
    def can_undo(self) -> bool:
        return len(self.__undo_stack) > 0 and self.__undo_stack[-1].is_undo_valid

    def validate(self) -> None:
        if len(self.__undo_stack) > 0 and not self.__undo_stack[-1].is_undo_valid:
            self.clear()

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

    @property
    def _undo_count(self) -> int:
        return len(self.__undo_stack)  # for testing

    @property
    def _redo_count(self) -> int:
        return len(self.__redo_stack)  # for testing

    def clear(self) -> None:
        while len(self.__redo_stack) > 0:
            self.__redo_stack.pop().close()
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
        self.__undo_stack.append(undo_command)
        undo_command.commit()
        while len(self.__redo_stack) > 0:
            self.__redo_stack.pop().close()
