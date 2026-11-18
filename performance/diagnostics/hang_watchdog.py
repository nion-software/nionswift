"""Diagnostic which writes every thread's stack to a file whenever the main thread stops for longer than a timeout.

Copy this file anywhere and import it from the Nion Swift console of the machine which freezes:

    import sys
    sys.path.insert(0, r"<the directory holding this file>")
    import hang_watchdog
    hang_watchdog.start(_window)

The call returns the path of the file, which by default is hang_stacks.txt in the application's data location. Pass
timeout to change the ten second default, and path to write somewhere else. The file is opened for appending, so
several runs collect in one file, each beginning with the lines which identify a report.

A watchdog thread of the standard library's faulthandler module writes the dumps. The main thread restarts its
countdown from the event loop several times per timeout, so a dump appears only when the main thread stops for
longer than the timeout, and it repeats every timeout for as long as the main thread stays stopped. Each dump starts
with a "Timeout" line and lists every thread with its stack, most recent call first. The watchdog writes from C, so it
works while another thread holds the interpreter lock. The dumps carry no time, so when the main thread runs again
after such a stop, a "main thread resumed" line follows them with the date and how long the main thread was stopped.

End it with:

    hang_watchdog.stop()

faulthandler has a single timer per process, so starting this diagnostic replaces any other use of that timer, and
stopping it cancels the timer.
"""

from __future__ import annotations

# standard libraries
import asyncio
import datetime
import faulthandler
import importlib.metadata
import os
import pathlib
import platform
import time
import typing

# third party libraries
import numpy

# local libraries
from nion.swift import DocumentController

NAME = "hang_watchdog"

# the revision of what the diagnostic writes.
REVISION = 1

# the packages whose versions the report lists.
PACKAGES = ("nionswift", "nionswift-instrumentation", "nionui", "niondata", "nionutils")

# the module state is confined to the main thread, which runs start, stop and the re-arming from the event loop.
_file: typing.TextIO | None = None
_timer_handle: asyncio.TimerHandle | None = None


def get_version(distribution_name: str) -> str:
    """Return the installed version of a distribution."""
    try:
        return importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        # a checkout on the path which is not installed has no version.
        return "not installed"


def get_header_lines() -> typing.Sequence[str]:
    """Return the lines which identify a report: what it measured, when, on which machine and with which software."""
    versions = ", ".join(f"{name} {get_version(name)}" for name in PACKAGES)
    return [f"{NAME}, revision {REVISION}",
            f"date      {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"machine   {platform.node()}, {platform.platform()}, {os.cpu_count()} processors",
            f"software  Python {platform.python_version()}, numpy {numpy.__version__}, {versions}",
            ""]


def is_running() -> bool:
    """Return whether the watchdog is running."""
    return _file is not None


def start(document_controller: DocumentController.DocumentController, *, timeout: float = 10.0, path: pathlib.Path | None = None) -> pathlib.Path:
    """Start writing every thread's stack to a file whenever the main thread stops for longer than timeout seconds.

    The file is opened for appending, and is hang_stacks.txt in the application's data location unless path is given.
    Return the path of the file.
    """
    global _file
    assert not is_running(), "the hang watchdog is already running"
    assert timeout > 0, "the timeout must be positive"
    path = path or pathlib.Path(document_controller.ui.get_data_location()) / "hang_stacks.txt"
    event_loop = document_controller.event_loop
    file = path.open("a", encoding="utf-8")
    file.write("\n".join(get_header_lines()) + f"started {datetime.datetime.now().isoformat(sep=' ', timespec='seconds')}, timeout {timeout}s\n")
    # faulthandler writes to the file descriptor directly, so the buffered text has to reach the file first.
    file.flush()
    # faulthandler needs the descriptor to stay open, so the module holds the file until stop closes it.
    _file = file

    previous_rearm_time = time.monotonic()

    # each call to dump_traceback_later replaces the timer, which restarts its countdown.
    def rearm() -> None:
        global _timer_handle
        nonlocal previous_rearm_time
        faulthandler.dump_traceback_later(timeout, repeat=True, file=file)
        now = time.monotonic()
        stopped_seconds = now - previous_rearm_time
        previous_rearm_time = now
        # a gap longer than the timeout means a dump was written, so this line dates the stop which caused it. it is
        # written after the timer is replaced, so no dump of the same stop can follow it.
        if stopped_seconds > timeout:
            file.write(f"main thread resumed {datetime.datetime.now().isoformat(sep=' ', timespec='seconds')} after {stopped_seconds:.1f}s\n")
            file.flush()
        _timer_handle = event_loop.call_later(timeout / 4, rearm)

    rearm()
    return path


def stop() -> None:
    """Stop the watchdog, if it is running, and close its file."""
    global _file, _timer_handle
    if not _file:
        return
    faulthandler.cancel_dump_traceback_later()
    if _timer_handle:
        _timer_handle.cancel()
        _timer_handle = None
    _file.write(f"stopped {datetime.datetime.now().isoformat(sep=' ', timespec='seconds')}\n\n")
    _file.close()
    _file = None
