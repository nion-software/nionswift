from __future__ import annotations

# standard libraries
import asyncio
import collections
import contextlib
import dataclasses
import datetime
import functools
import logging
import os
import pathlib
import re
import sys
import threading
import time
import traceback
import types

# third party libraries
import typing

import numpy

# local libraries
from nion.utils import DateTime


# datetimes are _local_ datetimes and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# timezone is for conversion and is the Olson timezone string.
# datetime_item is a dictionary with entries for the local_datetime, tz (timezone offset), and
# dst (daylight savings time offset). it may optionally include tz_name (timezone name), if available.
def get_datetime_item_from_datetime(datetime_local: datetime.datetime, tz_minutes: typing.Optional[int] = None,
                                    dst_minutes: typing.Optional[int] = None, timezone: typing.Optional[str] = None) -> typing.Dict[str, typing.Any]:
    # dst is information, tz already includes dst
    datetime_item = dict()
    datetime_item["local_datetime"] = datetime_local.isoformat()
    if tz_minutes is None:
        tz_minutes = int(round((datetime.datetime.now() - DateTime.utcnow()).total_seconds())) // 60
    if dst_minutes is None:
        dst_minutes = 60 if time.localtime().tm_isdst else 0
    datetime_item["tz"] = '{0:+03d}{1:02d}'.format(tz_minutes // 60, tz_minutes % 60)
    datetime_item["dst"] = "+{0:02d}".format(dst_minutes)
    if timezone is not None:
        datetime_item["timezone"] = timezone
    return datetime_item


def get_current_datetime_item() -> typing.Dict[str, typing.Any]:
    return get_datetime_item_from_datetime(datetime.datetime.now())


def get_datetime_item_from_utc_datetime(datetime_utc: datetime.datetime, tz_minutes: typing.Optional[int] = None,
                                        dst_minutes: typing.Optional[int] = None,
                                        timezone: typing.Optional[str] = None) -> typing.Dict[str, typing.Any]:
    # dst is information, tz already includes dst
    if tz_minutes is None:
        tz_minutes = int(round((datetime.datetime.now() - DateTime.utcnow()).total_seconds())) // 60
    return get_datetime_item_from_datetime(datetime_utc + datetime.timedelta(minutes=tz_minutes), tz_minutes,
                                           dst_minutes, timezone)


local_utcoffset_override: typing.Optional[typing.List[int]] = None  # for testing
def local_utcoffset_minutes(datetime_local: typing.Optional[datetime.datetime] = None) -> int:
    if local_utcoffset_override is not None:
        return local_utcoffset_override[0]
    now = datetime.datetime.now()
    return int((now - now.astimezone(tz=datetime.timezone.utc).replace(tzinfo=None)).total_seconds() / 60)


class TimezoneMinutesToStringConverter:
    def convert(self, value: typing.Optional[int]) -> typing.Optional[str]:
        return "{0:+03d}{1:02d}".format(value // 60, value % 60) if value is not None else None

    def convert_back(self, value: typing.Optional[str]) -> typing.Optional[int]:
        return (int(value[1:3]) * 60 + int(value[3:5])) * (-1 if value[0] == '-' else 1) if value is not None else None


local_timezone_override: typing.Optional[typing.List[str]] = None  # for testing
try:
    import tzlocal

    def get_local_timezone() -> typing.Optional[str]:
        if local_timezone_override is None:
            # see note https://github.com/regebro/tzlocal/issues/117#issuecomment-939351032
            return str(tzlocal.get_localzone())
        else:
            return local_timezone_override[0]
except ImportError:
    def get_local_timezone() -> typing.Optional[str]:
        return None if local_timezone_override is None else local_timezone_override[0]


# return python datetime object from a datetime_item. may return None if the datetime element is
# not properly formatted.
def get_datetime_from_datetime_item(datetime_item: typing.Dict[str, typing.Any]) -> typing.Optional[datetime.datetime]:
    local_datetime = datetime_item.get("local_datetime", str())
    if len(local_datetime) == 26:
        return datetime.datetime.strptime(local_datetime, "%Y-%m-%dT%H:%M:%S.%f")
    elif len(local_datetime) == 19:
        return datetime.datetime.strptime(local_datetime, "%Y-%m-%dT%H:%M:%S")
    return None


class Singleton(type):
    def __init__(cls, name: str, bases: typing.Tuple[type], dict: typing.Dict[str, typing.Any]):
        super(Singleton, cls).__init__(name, bases, dict)
        cls.instance = None

    def __call__(cls, *args: typing.List[typing.Any], **kw: typing.Dict[str, typing.Any]) -> typing.Any:
        if cls.instance is None:
            cls.instance = super(Singleton, cls).__call__(*args, **kw)
        return cls.instance


DirtyValue = typing.Any
CleanValue = typing.Union[typing.Dict[str, typing.Any], typing.List[typing.Any], typing.Tuple[typing.Any], str, float, int, bool, None]


def clean_dict(d0: typing.Dict[str, DirtyValue], clean_item_fn: typing.Optional[typing.Callable[[DirtyValue], CleanValue]] = None) -> typing.Dict[str, CleanValue]:
    """Return a json-clean dict. Will log info message for failures."""
    clean_item_fn = clean_item_fn if clean_item_fn else clean_item
    d: typing.Dict[str, CleanValue] = dict()
    for key in d0:
        cleaned_item = clean_item_fn(d0[key])
        if cleaned_item is not None:
            d[key] = cleaned_item
    return d


def clean_list(l0: typing.List[DirtyValue], clean_item_fn: typing.Optional[typing.Callable[[DirtyValue], CleanValue]] = None) -> typing.List[CleanValue]:
    """Return a json-clean list. Will log info message for failures."""
    clean_item_fn = clean_item_fn if clean_item_fn else clean_item
    l: typing.List[CleanValue] = list()
    for index, item in enumerate(l0):
        cleaned_item = clean_item_fn(item)
        l.append(cleaned_item)
    return l


def clean_tuple(t0: typing.Tuple[DirtyValue], clean_item_fn: typing.Optional[typing.Callable[[DirtyValue], CleanValue]] = None) -> typing.Tuple[CleanValue]:
    """Return a json-clean tuple. Will log info message for failures."""
    clean_item_fn = clean_item_fn if clean_item_fn else clean_item
    l: typing.List[CleanValue] = list()
    for index, item in enumerate(t0):
        cleaned_item = clean_item_fn(item)
        l.append(cleaned_item)
    return typing.cast(typing.Tuple[CleanValue], tuple(l))


type_lookup: typing.Mapping[typing.Type[typing.Any], typing.Callable[[DirtyValue], CleanValue]] = {
    dict: clean_dict,
    list: clean_list,
    tuple: clean_tuple,
    numpy.float32: lambda x: float(x),
    numpy.float64: lambda x: float(x),
    numpy.int16: lambda x: int(x),
    numpy.uint16: lambda x: int(x),
    numpy.int32: lambda x: int(x),
    numpy.uint32: lambda x: int(x),
    numpy.int64: lambda x: int(x),
    numpy.uint64: lambda x: int(x),
    float: lambda x: float(x),
    str: lambda x: str(x),
    int: lambda x: int(x),
    numpy.bool_: lambda x: bool(x),
    bool: lambda x: bool(x),
    type(None): lambda x: None
}


type_lookup_no_list: typing.Mapping[typing.Type[typing.Any], typing.Callable[[DirtyValue], CleanValue]] = {
    dict: clean_dict,
    list: clean_tuple,
    tuple: clean_tuple,
    numpy.float32: lambda x: float(x),
    numpy.float64: lambda x: float(x),
    numpy.int16: lambda x: int(x),
    numpy.uint16: lambda x: int(x),
    numpy.int32: lambda x: int(x),
    numpy.uint32: lambda x: int(x),
    numpy.int64: lambda x: int(x),
    numpy.uint64: lambda x: int(x),
    float: lambda x: float(x),
    str: lambda x: str(x),
    int: lambda x: int(x),
    numpy.bool_: lambda x: bool(x),
    bool: lambda x: bool(x),
    type(None): lambda x: None
}


def clean_item(i: DirtyValue) -> CleanValue:
    """Return a json-clean item or None. Will log info message for failure."""
    itype = type(i)
    c = type_lookup.get(itype, None)
    if c:
        return c(i)
    else:
        logging.info("[1] Unable to handle type %s", itype)
        import traceback
        traceback.print_stack()
        return None


def clean_item_no_list(i: DirtyValue) -> CleanValue:
    """Return a json-clean item or None. Will log info message for failure."""
    itype = type(i)
    c = type_lookup_no_list.get(itype, None)
    if c:
        return c(i)
    else:
        logging.info("[1] Unable to handle type %s", itype)
        import traceback
        traceback.print_stack()
        return None


def deep_compare_items(item1: CleanValue, item2: CleanValue) -> bool:
    """Deep compare dict/list/value. Return True if equal."""
    item1_type = type(item1)
    if item1_type != type(item2):
        return False
    if item1_type in (dict,):
        item1_dict = typing.cast(typing.Dict[str, CleanValue], item1)
        item2_dict = typing.cast(typing.Dict[str, CleanValue], item2)
        if item1_dict.keys() != item2_dict.keys():
            return False
        for key in item1_dict.keys():
            if not deep_compare_items(item1_dict[key], item2_dict[key]):
                return False
        return True
    elif item1_type in (list, tuple):
        item1_list = typing.cast(typing.List[CleanValue], item1)
        item2_list = typing.cast(typing.List[CleanValue], item2)
        if len(item1_list) != len(item2_list):
            return False
        for child_item1, child_item2 in zip(item1_list, item2_list):
            if not deep_compare_items(child_item1, child_item2):
                return False
        return True
    return item1 == item2


def parse_version(version: str, count: int = 3, max_count: typing.Optional[int] = None) -> typing.List[int]:
    max_count = max_count if max_count is not None else count
    version_components = [int(version_component) for version_component in version.split(".")]
    assert len(version_components) <= max_count
    while len(version_components) < count:
        version_components.append(0)
    return version_components


def compare_versions(version1: str, version2: str) -> int:
    if version1.startswith("~"):
        version1 = version1[1:]
        version_components1 = parse_version(version1, 1, 3)
        assert len(version_components1) > 1
    elif version1 == "1":  # same as "~1.0"
        version1 = "1.0"
        version_components1 = parse_version(version1, 2, 3)
    else:
        version_components1 = parse_version(version1)
    version_components2 = parse_version(version2)
    # print(version_components1, version_components2)
    for version_component1, version_component2 in zip(version_components1, version_components2):
        if version_component1 > version_component2:
            return 1
        elif version_component1 < version_component2:
            return -1
    return 0


class AtomicFileWriter:
    # see https://blog.gocept.com/2013/07/15/reliable-file-updates-with-python/
    # see https://github.com/mahmoud/boltons/blob/1885ed64006982cdd08a70c2cba193e1fe2eb693/boltons/fileutils.py#L343

    def __init__(self, filepath: pathlib.Path):
        self.__filepath = filepath
        self.__temp_filepath = self.__filepath.with_suffix(".temp")
        self.__fp: typing.Optional[typing.TextIO] = None

    def __enter__(self) -> typing.TextIO:
        self.__fp = self.__temp_filepath.open("w")
        return self.__fp

    def __exit__(self, exception_type: typing.Optional[typing.Type[Exception]], value: typing.Optional[Exception], traceback: typing.Optional[types.TracebackType]) -> None:
        assert self.__fp
        self.__fp.flush()
        os.fsync(self.__fp)
        self.__fp.close()
        if exception_type:
            try:
                os.unlink(self.__temp_filepath)
            except Exception:
                pass
        else:
            try:
                os.replace(self.__temp_filepath, self.__filepath)
                if hasattr(os, "O_DIRECTORY"):
                    # ensure the directory has been updated. not available all the time on Windows.
                    dirfd = os.open(os.path.dirname(self.__filepath), os.O_DIRECTORY)
                    os.fsync(dirfd)
                    os.close(dirfd)
            except OSError:
                try:
                    os.unlink(self.__temp_filepath)
                except Exception:
                    pass
                raise


@dataclasses.dataclass
class FPSRecord:
    window_elapsed_times: typing.List[float] = dataclasses.field(default_factory=list)
    window_elapsed_time: float = 0.0
    last_tick: typing.Optional[float] = None
    last_window_frame_mean: float = 0.0
    last_window_frame_std: float = 0.0


def fps_tick(fps_id: str) -> str:
    v = globals().setdefault("__fps_" + fps_id, FPSRecord())
    next_time = time.perf_counter()
    if v.last_tick is not None:
        elapsed_time = next_time - v.last_tick
        v.window_elapsed_times.append(elapsed_time)
        v.window_elapsed_time += elapsed_time
    if v.window_elapsed_time > 1.0:
        v.last_window_frame_mean = numpy.mean(v.window_elapsed_times)
        v.last_window_frame_std = numpy.std(v.window_elapsed_times)
        v.window_elapsed_time = 0.0
        v.window_elapsed_times = list()
    v.last_tick = next_time
    return fps_get(fps_id)


def fps_get(fps_id: str) -> str:
    v = globals().setdefault("__fps_" + fps_id, FPSRecord())
    m = v.last_window_frame_mean
    r = 1 / m if m != 0.0 else 0.0
    s = v.last_window_frame_std
    return str(int(r * 10) / 10.0) + "fps / " + str(int(m * 1000)) + "ms / " + str(int(s * 1000)) + "ms"


Trace = collections.namedtuple("Trace", ["start_time", "last_time_ref", "min_elapsed", "discard", "all"])


def trace_calls(trace: Trace, frame: types.FrameType, event: str, arg: typing.Any) -> None:
    if event != 'call':
        return
    co = frame.f_code
    func_name = co.co_name
    if func_name == 'write':
        # Ignore write() calls from print statements
        return
    func_line_no = frame.f_lineno
    func_filename = co.co_filename
    caller = frame.f_back
    assert caller is not None
    caller_line_no = caller.f_lineno
    caller_filename = caller.f_code.co_filename
    t = time.time()
    last_elapsed = t - trace.last_time_ref[0]
    if not trace.discard or trace.discard not in func_filename:
        if last_elapsed > trace.min_elapsed:
            s = "         " if last_elapsed > 0.001 else ""
            trace.all.append(":%s%12.5f %12.5f Call to %s on line %s of %s from line %s of %s" % (
                s, last_elapsed, t - trace.start_time, func_name, func_line_no, func_filename, caller_line_no, caller_filename))
        trace.last_time_ref[0] = t


def begin_trace(min_elapsed: float, discard: typing.Optional[str]) -> Trace:
    trace = Trace(start_time=time.time(), last_time_ref=[0], min_elapsed=min_elapsed, discard=discard, all=list())
    sys.settrace(typing.cast(typing.Callable[[types.FrameType, str, typing.Any], None], functools.partial(trace_calls, trace)))
    return trace


def end_trace(trace: Trace) -> None:
    sys.settrace(None)
    logging.debug("\n".join(trace.all))
    logging.debug("TOTAL: %s", len(trace.all))


@contextlib.contextmanager
def trace(min_elapsed: float = 0.0, discard: typing.Optional[str] = None) -> typing.Generator[None, None, None]:
    t = begin_trace(min_elapsed, discard)
    yield
    end_trace(t)


def sample_stack_all(count: int = 10, interval: float = 0.1) -> None:
    """Sample the stack in a thread and print it at regular intervals."""

    def print_stack_all(l: threading.RLock, ll: typing.MutableSequence[str]) -> None:
        l1 = list()
        l1.append("*** STACKTRACE - START ***")
        code = []
        for threadId, stack in sys._current_frames().items():
            sub_code = []
            sub_code.append("# ThreadID: %s" % threadId)
            for filename, lineno, name, line in traceback.extract_stack(stack):
                sub_code.append('File: "%s", line %d, in %s' % (filename, lineno, name))
                if line:
                    sub_code.append("  %s" % (line.strip()))
            if not "in select" in sub_code[-2] and \
               not "in wait" in sub_code[-2] and \
               not "in _worker" in sub_code[-2] and \
               not "in print_stack_all" in sub_code[-2] and \
               not "in sample_stack_all" in sub_code[-2] and \
               not "in checkcache" in sub_code[-2] and \
               not "do_sleep" in sub_code[-2] and \
               not "sleep" in sub_code[-1] and \
               not any(["in do_sample" in s for s in sub_code]):
                code.extend(sub_code)
        for line in code:
            l1.append(line)
        l1.append("*** STACKTRACE - END ***")
        with l:
            ll.extend(l1)

    def do_sample() -> None:
        l = threading.RLock()
        ll: typing.List[str] = list()
        for i in range(count):
            print_stack_all(l, ll)
            time.sleep(interval)
        with l:
            print("\n".join(ll))

    threading.Thread(target=do_sample).start()


def simplify_filename(filename: str, replacement_char: str = '_', maximum_length: int = 128) -> str:
    # This function replaces any illegal characters in a file name. Not a full path.
    # macOS illegal characters = \0 /
    # linux illegal characters = \0 /
    # Windows illegal characters = < > : / \ | ? * " ASCII values 0-31 (non-printable chars)
    # Windows illegal filenames = CON PRN AUX NUL COM1 COM2 COM3 COM4 COM5 COM6 COM7 COM8 COM9
    #                             LPT1 LPT2 LPT3 LPT4 LPT5 LPT6 LPT7 LPT8 LPT9
    # those files names are illegal with or without a suffix, upper and lower case
    # Windows file names cannot start or end with periods or spaces

    assert maximum_length > 5
    assert len(replacement_char) == 1

    # since windows is the most restrictive and covers the others, just focus on that
    illegal_chars = r'^[. ]|[<>:/\\|?*\"]|[\0-\31]|[. ]$'
    illegal_names = ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
                     'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9']

    # fix path length first so we don't uncover . or space at the start
    updated_filename = filename
    if len(updated_filename) > maximum_length:
        path = pathlib.Path(updated_filename)
        stem = path.stem
        suffix = path.suffix

        if len(suffix) >= maximum_length:
            updated_filename = replacement_char + suffix[1:]
        else:
            updated_filename = stem[:maximum_length - len(suffix)] + suffix

    # replace illegal characters with replacement_char
    updated_filename = re.sub(illegal_chars, replacement_char, updated_filename)

    # if filename (without suffix) is illegal name - prepend replacement_char
    file_name_without_suffix = pathlib.Path(updated_filename).stem
    if file_name_without_suffix.upper() in illegal_names:
        updated_filename = replacement_char + updated_filename
        if len(updated_filename) > maximum_length:
            # should only happen if the illegal name and suffix were already maximum_length
            updated_filename = replacement_char + updated_filename[2:]

    return updated_filename


class TraceCloseable:
    all: typing.List[TraceCloseable] = list()

    def __init__(self) -> None:
        self.__tb = traceback.extract_stack()
        TraceCloseable.all.append(self)

    def close(self) -> None:
        TraceCloseable.all.remove(self)

    @classmethod
    def print_leftovers(cls) -> None:
        import sys
        for x in TraceCloseable.all:
            print("**************************")
            print(f"LEAKED {x}")
            print(f"ALLOCATED HERE")
            for line in traceback.StackSummary.from_list(typing.cast(typing.List[typing.Tuple[str, int, str, typing.Optional[str]]], x.__tb)).format():
                print(line, file=sys.stderr, end="")
            print("^^^^^^^^^^^^^^^^^^^^^^^^^^")


class TestEventLoop:
    def __init__(self, event_loop: typing.Optional[asyncio.AbstractEventLoop] = None):
        logging.disable(logging.CRITICAL)  # suppress new_event_loop debug message
        self.__event_loop = event_loop if event_loop else asyncio.new_event_loop()
        logging.disable(logging.NOTSET)

    def close(self) -> None:
        # give cancelled tasks a chance to finish
        self.__event_loop.stop()
        self.__event_loop.run_forever()
        self.__event_loop.run_until_complete(asyncio.gather(*asyncio.all_tasks(loop=self.__event_loop)))
        # now close
        # due to a bug in Python libraries, the default executor needs to be shutdown explicitly before the event loop
        # see http://bugs.python.org/issue28464
        default_executor = getattr(self.__event_loop, "_default_executor", None)
        if default_executor:
            default_executor.shutdown()
        self.__event_loop.close()
        self.__event_loop = typing.cast(asyncio.AbstractEventLoop, None)

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop:
        return self.__event_loop


class Timer:
    def __init__(self, *, threshold: float = 0.0) -> None:
        self.start_time_ns = time.perf_counter_ns()
        self.last_time_ns = self.start_time_ns
        self.threshold = threshold

    def mark(self, title: str) -> None:
        current_time = time.perf_counter_ns()
        if self.threshold == 0.0 or (current_time - self.last_time_ns) // 1E9 > self.threshold:
            print(f"{title}: {(current_time - self.start_time_ns) // 1E6}ms +{(current_time - self.last_time_ns) // 1E6}ms")
        self.last_time_ns = current_time
