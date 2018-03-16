import abc
import copy
import gettext
import typing


_ = gettext.gettext


class UndoableCommand(abc.ABC):

    def __init__(self, title: str, *, command_id: str=None, is_mergeable: bool=False):
        self.__old_modified_state = None
        self.__new_modified_state = None
        self.__title = title
        self.__command_id = command_id
        self.__is_mergeable = is_mergeable

    def close(self):
        self.__old_modified_state = None
        self.__new_modified_state = None

    @property
    def title(self):
        return self.__title

    @property
    def command_id(self):
        return self.__command_id

    @property
    def is_mergeable(self):
        return self.__is_mergeable

    @property
    def is_redo_valid(self) -> bool:
        return self.__old_modified_state == self._get_modified_state()

    @property
    def is_undo_valid(self) -> bool:
        return self.__new_modified_state == self._get_modified_state()

    def initialize(self, modified_state=None):
        self.__old_modified_state = modified_state if modified_state else self._get_modified_state()

    @property
    def _old_modified_state(self):
        return self.__old_modified_state

    def commit(self):
        self.__new_modified_state = self._get_modified_state()

    def perform(self):
        self._perform()

    def undo(self):
        self._undo()
        self._set_modified_state(self.__old_modified_state)
        self.__is_mergeable = False

    def redo(self):
        self._redo()
        self._set_modified_state(self.__new_modified_state)

    def can_merge(self, command: "UndoableCommand") -> bool:
        return False

    def merge(self, command: "UndoableCommand") -> None:
        assert self.command_id and self.command_id == command.command_id
        self._merge(command)
        self.__new_modified_state = self._get_modified_state()

    def _merge(self, command: "UndoableCommand") -> None:
        pass

    @abc.abstractmethod
    def _get_modified_state(self):
        pass

    @abc.abstractmethod
    def _set_modified_state(self, modified_state) -> None:
        pass

    def _perform(self) -> None:
        pass

    @abc.abstractmethod
    def _undo(self) -> None:
        pass

    def _redo(self) -> None:
        self._undo()


class AggregateUndoableCommand(UndoableCommand):

    def __init__(self, title: str, children: typing.Sequence[UndoableCommand]=None):
        super().__init__(title)
        self.__commands = copy.copy(children)
        self.initialize(self.__commands[-1]._old_modified_state)

    def close(self):
        while len(self.__commands) > 0:
            self.__commands.pop().close()
        super().close()

    @property
    def is_redo_valid(self) -> bool:
        return self.__commands[0].is_redo_valid if self.__commands else False

    @property
    def is_undo_valid(self) -> bool:
        return self.__commands[-1].is_undo_valid if self.__commands else False

    def _get_modified_state(self):
        return self.__commands[-1]._get_modified_state()

    def _set_modified_state(self, modified_state) -> None:
        self.__commands[-1]._set_modified_state(modified_state)

    def _perform(self) -> None:
        for command in self.__commands:
            command.perform()

    def _undo(self) -> None:
        for command in reversed(self.__commands):
            command.undo()

    def _redo(self) -> None:
        for command in self.__commands:
            command.redo()


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

    @property
    def last_command(self) -> typing.Optional[UndoableCommand]:
        return self.__undo_stack[-1] if self.__undo_stack else None

    def pop_command(self) -> typing.Optional[UndoableCommand]:
        return self.__undo_stack.pop() if self.__undo_stack else None

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
        undo_command.commit()
        last_undo_command = self.__undo_stack[-1] if self.__undo_stack else None
        if last_undo_command and last_undo_command.is_mergeable and undo_command.is_mergeable and last_undo_command.command_id == undo_command.command_id:
            last_undo_command.merge(undo_command)
        else:
            self.__undo_stack.append(undo_command)
        while len(self.__redo_stack) > 0:
            self.__redo_stack.pop().close()
