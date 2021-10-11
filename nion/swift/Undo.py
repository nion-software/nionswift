from __future__ import annotations

import abc
import copy
import gettext
import typing


_ = gettext.gettext


class UndoableCommand(abc.ABC):

    def __init__(self, title: str, *, command_id: typing.Optional[str] = None, is_mergeable: bool = False) -> None:
        self.__old_modified_state = None
        self.__new_modified_state = None
        self.__title = title
        self.__command_id = command_id
        self.__is_mergeable = is_mergeable

    def close(self) -> None:
        self.__old_modified_state = None
        self.__new_modified_state = None

    @property
    def title(self) -> str:
        return self.__title

    @property
    def command_id(self) -> typing.Optional[str]:
        return self.__command_id

    @property
    def is_mergeable(self) -> bool:
        return self.__is_mergeable

    @property
    def is_redo_valid(self) -> bool:
        return self._compare_modified_states(self.__old_modified_state, self._get_modified_state())

    @property
    def is_undo_valid(self) -> bool:
        return self._compare_modified_states(self.__new_modified_state, self._get_modified_state())

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1 == state2)

    def initialize(self, modified_state: typing.Any = None) -> None:
        self.__old_modified_state = modified_state if modified_state else self._get_modified_state()

    @property
    def _old_modified_state(self) -> typing.Any:
        return self.__old_modified_state

    def commit(self) -> None:
        self.__new_modified_state = self._get_modified_state()

    def perform(self) -> None:
        self._perform()

    def undo(self) -> None:
        self._undo()
        self._set_modified_state(self.__old_modified_state)
        self.__is_mergeable = False

    def redo(self) -> None:
        self._redo()
        self._set_modified_state(self.__new_modified_state)

    def can_merge(self, command: UndoableCommand) -> bool:
        return False

    def merge(self, command: UndoableCommand) -> None:
        assert self.command_id and self.command_id == command.command_id
        self._merge(command)
        self.__new_modified_state = self._get_modified_state()

    def _merge(self, command: UndoableCommand) -> None:
        pass

    @abc.abstractmethod
    def _get_modified_state(self) -> typing.Any:
        pass

    @abc.abstractmethod
    def _set_modified_state(self, modified_state: typing.Any) -> None:
        pass

    def _perform(self) -> None:
        pass

    @abc.abstractmethod
    def _undo(self) -> None:
        pass

    def _redo(self) -> None:
        self._undo()


class UndoStack:

    def __init__(self) -> None:
        # undo/redo stack. next item is at the end.
        self.__undo_stack: typing.List[UndoableCommand] = list()
        self.__redo_stack: typing.List[UndoableCommand] = list()

    def close(self) -> None:
        self.clear()

    @property
    def can_redo(self) -> bool:
        return len(self.__redo_stack) > 0 and self.__redo_stack[-1].is_redo_valid

    @property
    def can_undo(self) -> bool:
        return len(self.__undo_stack) > 0 and self.__undo_stack[-1].is_undo_valid

    @property
    def last_command(self) -> typing.Optional[UndoableCommand]:
        return self.__undo_stack[-1] if self.__undo_stack else None

    def pop_command(self) -> None:
        self.__undo_stack.pop().close() if self.__undo_stack else None

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
            undo_command.close()
        else:
            self.__undo_stack.append(undo_command)
        while len(self.__redo_stack) > 0:
            self.__redo_stack.pop().close()
