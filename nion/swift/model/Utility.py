# standard libraries
import asyncio
import collections
import contextlib
import datetime
import functools
import logging
import sys
import threading
import time
import traceback

# third party libraries
import numpy

# local libraries
# None


# datetimes are _local_ datetimes and must use this specific ISO 8601 format. 2013-11-17T08:43:21.389391
# time zones are offsets (east of UTC) in the following format "+HHMM" or "-HHMM"
# daylight savings times are time offset (east of UTC) in format "+MM" or "-MM"
# timezone is for conversion and is the Olson timezone string.
# datetime_item is a dictionary with entries for the local_datetime, tz (timezone offset), and
# dst (daylight savings time offset). it may optionally include tz_name (timezone name), if available.
def get_datetime_item_from_datetime(datetime_local, tz_minutes=None, dst_minutes=None, timezone=None):
    # dst is information, tz already includes dst
    datetime_item = dict()
    datetime_item["local_datetime"] = datetime_local.isoformat()
    if tz_minutes is None:
        tz_minutes = int(round((datetime.datetime.now() - datetime.datetime.utcnow()).total_seconds())) // 60
    if dst_minutes is None:
        dst_minutes = 60 if time.localtime().tm_isdst else 0
    datetime_item["tz"] = '{0:+03d}{1:02d}'.format(tz_minutes // 60, tz_minutes % 60)
    datetime_item["dst"] = "+{0:02d}".format(dst_minutes)
    if timezone is not None:
        datetime_item["timezone"] = timezone
    return datetime_item


def get_current_datetime_item():
    return get_datetime_item_from_datetime(datetime.datetime.now())


def get_datetime_item_from_utc_datetime(datetime_utc, tz_minutes=None, dst_minutes=None, timezone=None):
    # dst is information, tz already includes dst
    if tz_minutes is None:
        tz_minutes = int(round((datetime.datetime.now() - datetime.datetime.utcnow()).total_seconds())) // 60
    return get_datetime_item_from_datetime(datetime_utc + datetime.timedelta(minutes=tz_minutes), tz_minutes, dst_minutes, timezone)

local_utcoffset_override = None  # for testing
try:
    import pytz.reference
    def local_utcoffset_minutes(datetime_local:datetime.datetime=None) -> int:
        if local_utcoffset_override is not None:
            return local_utcoffset_override[0]
        datetime_local = datetime_local if datetime_local else datetime.datetime.now()
        return int(pytz.reference.LocalTimezone().utcoffset(datetime_local).total_seconds() // 60)
except ImportError:
    def local_utcoffset_minutes(datetime_local:datetime.datetime=None) -> int:
        if local_utcoffset_override is not None:
            return local_utcoffset_override[0]
        return int(round((datetime.datetime.now() - datetime.datetime.utcnow()).total_seconds())) // 60

class TimezoneMinutesToStringConverter:
    def convert(self, value):
        return "{0:+03d}{1:02d}".format(value // 60, value % 60) if value is not None else None
    def convert_back(self, value):
        return (int(value[1:3]) * 60 + int(value[3:5])) * (-1 if value[0] == '-' else 1) if value is not None else None

local_timezone_override = None  # for testing
try:
    import tzlocal
    def get_local_timezone():
        return tzlocal.get_localzone().zone if local_timezone_override is None else local_timezone_override[0]
except ImportError:
    def get_local_timezone():
        return None if local_timezone_override is None else local_timezone_override[0]

# return python datetime object from a datetime_item. may return None if the datetime element is
# not properly formatted.
def get_datetime_from_datetime_item(datetime_item):
    local_datetime = datetime_item.get("local_datetime", str())
    if len(local_datetime) == 26:
        return datetime.datetime.strptime(local_datetime, "%Y-%m-%dT%H:%M:%S.%f")
    elif len(local_datetime) == 19:
        return datetime.datetime.strptime(local_datetime, "%Y-%m-%dT%H:%M:%S")
    return None


class Singleton(type):
    def __init__(cls, name, bases, dict):
        super(Singleton, cls).__init__(name, bases, dict)
        cls.instance = None

    def __call__(cls, *args, **kw):
        if cls.instance is None:
            cls.instance = super(Singleton, cls).__call__(*args, **kw)
        return cls.instance


def clean_dict(d0, clean_item_fn=None):
    """
        Return a json-clean dict. Will log info message for failures.
    """
    clean_item_fn = clean_item_fn if clean_item_fn else clean_item
    d = dict()
    for key in d0:
        cleaned_item = clean_item_fn(d0[key])
        if cleaned_item is not None:
            d[key] = cleaned_item
    return d


def clean_list(l0, clean_item_fn=None):
    """
        Return a json-clean list. Will log info message for failures.
    """
    clean_item_fn = clean_item_fn if clean_item_fn else clean_item
    l = list()
    for index, item in enumerate(l0):
        cleaned_item = clean_item_fn(item)
        l.append(cleaned_item)
    return l


def clean_tuple(t0, clean_item_fn=None):
    """
        Return a json-clean tuple. Will log info message for failures.
    """
    clean_item_fn = clean_item_fn if clean_item_fn else clean_item
    l = list()
    for index, item in enumerate(t0):
        cleaned_item = clean_item_fn(item)
        l.append(cleaned_item)
    return tuple(l)


def clean_item(i):
    """
        Return a json-clean item or None. Will log info message for failure.
    """
    itype = type(i)
    if itype == dict:
        return clean_dict(i)
    elif itype == list:
        return clean_list(i)
    elif itype == tuple:
        return clean_tuple(i)
    elif itype == numpy.float32:
        return float(i)
    elif itype == numpy.float64:
        return float(i)
    elif itype == numpy.int16:
        return int(i)
    elif itype == numpy.uint16:
        return int(i)
    elif itype == numpy.int32:
        return int(i)
    elif itype == numpy.uint32:
        return int(i)
    elif itype == numpy.int64:
        return int(i)
    elif itype == numpy.uint64:
        return int(i)
    elif itype == float:
        return i
    elif itype == str:
        return i
    elif itype == int:
        return i
    elif itype == bool:
        return i
    elif itype == type(None):
        return i
    logging.info("[1] Unable to handle type %s", itype)
    import traceback
    traceback.print_stack()
    return None


def clean_item_no_list(i):
    """
        Return a json-clean item or None. Will log info message for failure.
    """
    itype = type(i)
    if itype == dict:
        return clean_dict(i, clean_item_no_list)
    elif itype == list:
        return clean_tuple(i, clean_item_no_list)
    elif itype == tuple:
        return clean_tuple(i, clean_item_no_list)
    elif itype == numpy.float32:
        return float(i)
    elif itype == numpy.float64:
        return float(i)
    elif itype == numpy.int16:
        return int(i)
    elif itype == numpy.uint16:
        return int(i)
    elif itype == numpy.int32:
        return int(i)
    elif itype == numpy.uint32:
        return int(i)
    elif itype == float:
        return i
    elif itype == str:
        return i
    elif itype == int:
        return i
    elif itype == bool:
        return i
    elif itype == type(None):
        return i
    logging.info("[2] Unable to handle type %s", itype)
    return None


def parse_version(version, count=3, max_count=None):
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


def fps_tick(fps_id):
    v = globals().setdefault("__fps_" + fps_id, [0, 0.0, None, 0.0, None, []])
    v[0] += 1
    next_time = time.perf_counter()
    while len(v[5]) > 100:
        v[5].pop(0)
    if v[2] is not None:
        v[5].append(next_time - v[2])
    v[1] += next_time - v[2] if v[2] is not None else 0.0
    if v[1] > 1.0:
        v[3] = v[0] / v[1]
        v[0] = 0
        v[1] = 0.0
    v[2] = next_time
    return fps_get(fps_id)

def fps_get(fps_id):
    v = globals().setdefault("__fps_" + fps_id, [0, 0.0, None, 0.0, None, []])
    # s = numpy.std(v[5]) if len(v[5]) > 0 else 0.0
    return str(int(v[3]*100)/100.0) # + " " + str(int(s*1000)) + "ms"

def trace_calls(trace, frame, event, arg):
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


def begin_trace(min_elapsed, discard):
    Trace = collections.namedtuple("Trace", ["start_time", "last_time_ref", "min_elapsed", "discard", "all"])
    trace = Trace(start_time=time.time(), last_time_ref=[0], min_elapsed=min_elapsed, discard=discard, all=list())
    sys.settrace(functools.partial(trace_calls, trace))
    return trace


def end_trace(trace):
    sys.settrace(None)
    logging.debug("\n".join(trace.all))
    logging.debug("TOTAL: %s", len(trace.all))


@contextlib.contextmanager
def trace(min_elapsed=0.0, discard=None):
    t = begin_trace(min_elapsed, discard)
    yield
    end_trace(t)


def sample_stack_all(count=10, interval=0.1):
    """Sample the stack in a thread and print it at regular intervals."""

    def print_stack_all(l, ll):
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

    def do_sample():
        l = threading.RLock()
        ll = list()
        for i in range(count):
            print_stack_all(l, ll)
            time.sleep(interval)
        with l:
            print("\n".join(ll))

    threading.Thread(target=do_sample).start()


class TestEventLoop:
    def __init__(self, event_loop: asyncio.AbstractEventLoop = None):
        logging.disable(logging.CRITICAL)  # suppress new_event_loop debug message
        self.__event_loop = event_loop if event_loop else asyncio.new_event_loop()
        logging.disable(logging.NOTSET)
        self.__event_loop.has_no_pulse = True

    def close(self):
        # give cancelled tasks a chance to finish
        self.__event_loop.stop()
        self.__event_loop.run_forever()
        self.__event_loop.run_until_complete(asyncio.gather(*asyncio.Task.all_tasks(loop=self.__event_loop), loop=self.__event_loop))
        # now close
        # due to a bug in Python libraries, the default executor needs to be shutdown explicitly before the event loop
        # see http://bugs.python.org/issue28464
        if self.__event_loop._default_executor:
            self.__event_loop._default_executor.shutdown()
        self.__event_loop.close()
        self.__event_loop = None

    @property
    def event_loop(self):
        return self.__event_loop
