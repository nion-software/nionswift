"""The command history: each entry of the command log as values, logged as the record's message and kept in memory for a panel to list."""

from __future__ import annotations

# standard libraries
import collections
import dataclasses
import datetime
import enum
import logging
import types
import typing

# third party libraries
# None

# local libraries
from nion.ui import Window
from nion.utils import Event

commands_logger = logging.getLogger("_commands")

# the most entries the command history keeps, so that a session which runs for days doesn't grow it without bound.
MAX_ENTRY_COUNT = 1000


class CommandHistoryEntryKind(enum.StrEnum):
    """The kind of a command history entry, one for each kind of command log line."""
    APPLICATION = "application"
    PLUG_IN = "plug-in"
    WINDOW = "window"
    PANEL = "panel"
    ACTION = "action"
    ACTION_END = "action end"
    CHANGE = "change"
    UNDO = "undo"
    REDO = "redo"
    EXPORT = "export"


@dataclasses.dataclass(frozen=True)
class CommandHistoryEntry:
    """An entry in the command history, holding what the command log line for it says, as values.

    kind: the kind of entry.
    time: when the entry was recorded.
    title: the text a person reads, such as the action's or the change's name, or the event, e.g. "window opened".
    identifier: the action id, the change's command id or the panel id, if the entry has one.
    invoked_from: for an action or a change, the kind of user interface element a person used, if any.
    invoked_from_id: for an action or a change, the panel or dialog a person used, if any.
    action_id: for a change, the action it was made in, if any.
    parameters: for an action, the parameters of its context, which may hold any value an action accepts.
    duration: for an action end, how long the action ran, in seconds.
    details: other text the command log line carries, such as a window's open panels or a plug-in's message.
    """
    kind: CommandHistoryEntryKind
    time: datetime.datetime
    title: str
    identifier: str | None = None
    invoked_from: Window.ActionOrigin | None = None
    invoked_from_id: str | None = None
    action_id: str | None = None
    parameters: typing.Mapping[str, typing.Any] = dataclasses.field(default_factory=lambda: types.MappingProxyType(dict()))
    duration: float | None = None
    details: str | None = None

    def __str__(self) -> str:
        # a log handler writes the entry as its command log line.
        return get_log_line(self)


class CommandHistoryHandler(logging.Handler):
    """A handler on the command log which keeps the most recent entries, and fires an event for each entry it keeps.

    It keeps only the records whose message is an entry. An entry may be logged on any thread, so the entries are protected
    by the handler's lock, and entry_appended_event fires on the thread which logged the entry.
    """

    def __init__(self) -> None:
        super().__init__()
        self.__entries = collections.deque[CommandHistoryEntry](maxlen=MAX_ENTRY_COUNT)
        self.entry_appended_event = Event.Event()

    @property
    def entries(self) -> typing.Sequence[CommandHistoryEntry]:
        self.acquire()
        try:
            return list(self.__entries)
        finally:
            self.release()

    def emit(self, record: logging.LogRecord) -> None:
        # logging calls emit with the handler's lock held.
        if isinstance(entry := record.msg, CommandHistoryEntry):
            self.__entries.append(entry)
            self.entry_appended_event.fire(entry)


# the application's command history, which the application adds to the command log when it sets the log up.
command_history = CommandHistoryHandler()


def get_log_line(entry: CommandHistoryEntry) -> str:
    """Return the command log line for the entry, made from its values."""
    kind = entry.kind
    if kind == CommandHistoryEntryKind.ACTION:
        origin_text = Window.invoked_from_text(entry.invoked_from, entry.invoked_from_id)
        return f"# action {entry.details}" + (f" (from {origin_text})" if origin_text else "")
    if kind == CommandHistoryEntryKind.ACTION_END:
        return f"# action end {entry.identifier} ({entry.duration or 0.0:.3f} s)"
    if kind in (CommandHistoryEntryKind.CHANGE, CommandHistoryEntryKind.UNDO, CommandHistoryEntryKind.REDO):
        # " <command id>: <title>", or ": <title>" for a command with no id, such as a plug-in's.
        command_text = f" {entry.identifier}: {entry.title}" if entry.identifier else f": {entry.title}"
        suffix = str()
        if kind == CommandHistoryEntryKind.CHANGE:
            # a change made in an action gives the action, since the action's own line gives its origin.
            if entry.action_id:
                suffix = f" (in action {entry.action_id})"
            elif origin_text := Window.invoked_from_text(entry.invoked_from, entry.invoked_from_id):
                suffix = f" (from {origin_text})"
        return f"# {kind}{command_text}{suffix}"
    if kind == CommandHistoryEntryKind.WINDOW:
        return f"# {entry.title} with panels:" + (f" {entry.details}" if entry.details else "")
    if kind == CommandHistoryEntryKind.PANEL:
        return f"# {entry.title}: {entry.identifier}"
    if kind == CommandHistoryEntryKind.PLUG_IN:
        return (entry.details or str()).replace("Plug-in", "# plug-in")
    if kind == CommandHistoryEntryKind.EXPORT:
        return f"# export metrics {entry.details}"
    return f"# {entry.title}"


def record(kind: CommandHistoryEntryKind, title: str, *, identifier: str | None = None, invoked_from: Window.ActionOrigin | None = None,
           invoked_from_id: str | None = None, action_id: str | None = None, parameters: typing.Mapping[str, typing.Any] | None = None,
           duration: float | None = None, details: str | None = None) -> None:
    """Log an entry, recorded now, to the command log, whose handlers write its line and keep it in the command history.

    The parameters are copied, so a later change to the caller's mapping doesn't change the entry.
    """
    commands_logger.info(CommandHistoryEntry(kind, datetime.datetime.now(), title, identifier, invoked_from, invoked_from_id, action_id,
                                             types.MappingProxyType(dict(parameters or dict())), duration, details))
