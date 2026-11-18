"""Diagnostic for the periodic stalling of a background numpy.histogram loop over live acquisition data.

Copy this file anywhere and import it from the Nion Swift console. With live acquisition playing:

    import sys
    sys.path.insert(0, r"<the directory holding this file>")
    import histogram_jitter
    histogram_jitter.start(_model)

The finished report is logged at the info level, so there is nothing to poll. It can also be printed on demand:

    print(histogram_jitter.report())

Then stop live acquisition and run the baseline, which reuses the same data item, so the two runs appear in one
report and differ only in whether acquisition is running:

    histogram_jitter.start(_model, tag="idle")

The phases are:

    refetch     fetch the latest xdata each iteration, then histogram it (the original scenario)
    copy        histogram a private copy, touching nothing the application owns inside the timed region
    bincount    the clip and bincount formulation from HistogramPanel, which is about six numpy calls
    sum         a single reduction, which acquires the interpreter lock once instead of a few hundred times

Each iteration records wall time and the worker thread's own CPU time, so a stall (wall time not spent on a
CPU) is separated from real work. A monitor thread does nothing but sleep for a millisecond at a time and
records when it returns much later than that; those windows are times when this interpreter could not run at
all, either because another thread held the interpreter lock or because no CPU was available. The report says
how much of each stall fell inside such a window, which is what distinguishes a lock problem from the cost of
the data or the computation itself.

On Windows the thread and process clocks advance only on a scheduler tick of roughly fifteen milliseconds,
which is coarser than one iteration. The report measures the tick and says so; read the per phase cpu, stall
and cores busy figures there, and disregard the per iteration ones. Page fault and context switch counts come
from the resource module and are omitted where it is unavailable.
"""

from __future__ import annotations

# standard libraries
import bisect
import collections
import ctypes
import dataclasses
import datetime
import importlib.metadata
import linecache
import logging
import os
import platform
import statistics
import sys
import threading
import time
import traceback
import types
import typing

# resource is available only on unix. it supplies the page fault and context switch counts, which are omitted on
# other platforms; the process cpu time, which matters more, comes from time.process_time_ns instead.
try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]

# third party libraries
import numpy
import numpy.typing

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel

# the measured data can be of any type.
_NDArray = numpy.typing.NDArray[typing.Any]

NAME = "histogram_jitter"

# the revision of the measured work.
REVISION = 1

# the packages whose versions the report lists.
PACKAGES = ("nionswift", "nionswift-instrumentation", "nionui", "niondata", "nionutils")

BIN_COUNT = 256

# a phase runs at least this many iterations, and then keeps going until it has spanned this much time, so that
# every phase covers many frames even when a single iteration is fast.
ITERATION_COUNT = 100
MINIMUM_PHASE_DURATION_NS = 2_000_000_000
MAXIMUM_PHASE_DURATION_NS = 6_000_000_000
MAXIMUM_ITERATION_COUNT = 40000

# a run with the sampler disabled measures the same timings without the per thread stack sampling, which is the
# control for whether the sampling is itself contributing to the stalls it reports.
SAMPLE_THREADS = True

# macOS QoS class values from sys/qos.h. a thread at a low QoS class is scheduled on the efficiency cores of an
# Apple silicon machine, which runs this work several times slower, so the QoS class of the measuring thread has
# to be known before any timing can be interpreted.
QOS_CLASS_USER_INTERACTIVE = 0x21
QOS_CLASS_DEFAULT = 0x15
QOS_CLASS_NAMES = {0x21: "user-interactive", 0x19: "user-initiated", 0x15: "default", 0x11: "utility",
                   0x09: "background", 0x00: "unspecified"}

# a sampled stack whose innermost frame matches one of these is parked rather than running, and says nothing
# about what was consuming the interpreter.
_PARKED_MARKERS = ("Event.wait", "Condition.wait", "Queue.get", "_worker:", "Thread.join", "select", "poll",
                   "acquire", "Semaphore", "run_forever", "_run_once")

# a thread whose current source line makes one of these calls is waiting inside a c function, which leaves no
# python frame of its own to recognize it by.
_PARKED_CALLS = ("time.sleep(", ".sleep(", ".wait(", ".join(", ".acquire(", ".get(", ".select(", ".poll(")


_thread_time_granularity_ns = 0


def measure_thread_time_granularity() -> int:
    """Return the smallest observed increment of time.thread_time_ns, in nanoseconds.

    The result is measured once and cached, since measuring it occupies a cpu and holds the interpreter lock.

    The reported resolution of the thread clock is not the rate at which it advances. On Windows it advances on a
    scheduler tick of about fifteen milliseconds, which is coarser than a single iteration of the work measured
    here, so the per iteration cpu figures are unusable there while the per phase figures remain sound.
    """
    global _thread_time_granularity_ns
    if _thread_time_granularity_ns:
        return _thread_time_granularity_ns
    granularity = 0
    tick_count = 0
    start_ns = time.perf_counter_ns()
    previous_ns = time.thread_time_ns()
    # a coarse clock ticks rarely, so wait for several ticks rather than for a fixed period, with a ceiling in
    # case the clock does not advance at all.
    while tick_count < 4 and time.perf_counter_ns() - start_ns < 200_000_000:
        current_ns = time.thread_time_ns()
        if current_ns != previous_ns:
            increment = current_ns - previous_ns
            granularity = increment if not granularity else min(granularity, increment)
            previous_ns = current_ns
            tick_count += 1
    _thread_time_granularity_ns = granularity
    return granularity


def _libsystem() -> ctypes.CDLL | None:
    """Return the macOS system library configured for the QoS calls, or None on other platforms."""
    if sys.platform != "darwin":
        return None
    library = ctypes.CDLL("/usr/lib/libSystem.dylib")
    library.pthread_self.restype = ctypes.c_void_p
    library.pthread_set_qos_class_self_np.argtypes = [ctypes.c_uint, ctypes.c_int]
    library.pthread_get_qos_class_np.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_int)]
    return library


def get_thread_qos_class() -> int:
    """Return the QoS class of the calling thread, or -1 if it cannot be determined."""
    library = _libsystem()
    if not library:
        return -1
    qos_class = ctypes.c_uint(0)
    relative_priority = ctypes.c_int(0)
    library.pthread_get_qos_class_np(library.pthread_self(), ctypes.byref(qos_class), ctypes.byref(relative_priority))
    return int(qos_class.value)


def set_thread_qos_class(qos_class: int) -> None:
    """Set the QoS class of the calling thread. Does nothing on platforms without QoS classes."""
    library = _libsystem()
    if library:
        library.pthread_set_qos_class_self_np(qos_class, 0)


_parked_cache: dict[tuple[str, int], bool] = dict()


def _is_parked(frame: types.FrameType) -> bool:
    """Return whether a sampled stack is waiting rather than running.

    A thread inside time.sleep or a lock acquire has no python frame for the call, so its innermost frame is the
    line which made the call; the source of that line is what identifies it. The frame labels are checked too,
    for waits which do have a python frame.
    """
    key = (frame.f_code.co_filename, frame.f_lineno)
    parked = _parked_cache.get(key)
    if parked is None:
        source_line = linecache.getline(key[0], key[1]).strip()
        parked = (any(marker in source_line for marker in _PARKED_CALLS)
                  or any(marker in _frame_label(frame, 3) for marker in _PARKED_MARKERS))
        _parked_cache[key] = parked
    return parked


def _frame_label(frame: types.FrameType, depth: int) -> str:
    """Return a short label for the innermost depth frames of a stack."""
    names: list[str] = list()
    current_frame: types.FrameType | None = frame
    for _ in range(depth):
        if current_frame is None:
            break
        names.append(f"{current_frame.f_code.co_qualname}:{current_frame.f_lineno}")
        current_frame = current_frame.f_back
    return " <- ".join(names)


@dataclasses.dataclass(frozen=True)
class IterationSample:
    """The measurements for a single iteration of a measured loop.

    The times are nanoseconds from time.perf_counter_ns, except cpu_ns, which is the CPU time consumed by the
    worker thread itself between fetch_end_ns and end_ns. buffer_address is the address of the first element of
    the array which was worked on, and changes when live acquisition hands over a new frame buffer.
    involuntary_switch_count and minor_fault_count are process-wide, not thread specific, so they only hint at
    preemption and at memory being faulted in.
    """

    index: int
    start_ns: int
    fetch_end_ns: int
    end_ns: int
    cpu_ns: int
    buffer_address: int
    is_new_buffer: bool
    is_new_frame: bool
    involuntary_switch_count: int
    minor_fault_count: int
    process_cpu_ns: int

    @property
    def cores_busy(self) -> float:
        """Return the average number of cores the whole process used during this iteration.

        A value near one means the process was serialized, so a stall was a wait for the interpreter lock. A
        value near the core count means the machine was saturated, so a stall was the scheduler.
        """
        return self.process_cpu_ns / max(1, self.end_ns - self.start_ns)

    @property
    def fetch_ns(self) -> int:
        return self.fetch_end_ns - self.start_ns

    @property
    def work_ns(self) -> int:
        return self.end_ns - self.fetch_end_ns

    @property
    def stall_ns(self) -> int:
        """Return the wall time of the work which was not spent running on a CPU."""
        return max(0, self.work_ns - self.cpu_ns)


@dataclasses.dataclass(frozen=True)
class StallWindow:
    """A period during which the monitor thread could not run, with what the main thread was doing at its end.

    The window is bounded by when the monitor's sleep should have returned and when it actually returned. The
    labels are sampled once the monitor runs again, so they describe the state just after the window, which is
    usually still inside whatever caused it.
    """

    start_ns: int
    end_ns: int
    main_thread_label: str
    running_labels: tuple[str, ...]

    @property
    def duration_ns(self) -> int:
        return self.end_ns - self.start_ns


@dataclasses.dataclass(frozen=True)
class PhaseResult:
    """The samples for one measured phase, along with a description of the data which produced them.

    The phase totals are each measured with a single pair of readings across the whole phase, so they remain
    accurate on a platform whose thread clock advances only on a scheduler tick, where the per iteration cpu
    figures are too coarse to use.
    """

    name: str
    description: str
    samples: typing.Sequence[IterationSample]
    phase_wall_ns: int
    phase_cpu_ns: int
    phase_process_cpu_ns: int


class StallMonitor:
    """Records the periods during which this interpreter could not run the monitor thread.

    The monitor sleeps for interval seconds in a loop. The sleep releases the interpreter lock, and returning
    from it requires reacquiring the lock and being scheduled, so a return much later than requested means the
    interpreter was unavailable for that long. This observes a long lock hold by a C extension, which a stack
    sampler cannot see, because a sampler needs the lock in order to sample.
    """

    def __init__(self, interval: float = 0.001, threshold_ns: int = 3_000_000, depth: int = 4) -> None:
        self.__interval = interval
        self.__threshold_ns = threshold_ns
        self.__depth = depth
        self.__main_thread_ident = typing.cast(int, threading.main_thread().ident)
        # both lists are only touched by the monitor thread until stop joins it, so no lock is needed.
        self.__windows: list[StallWindow] = list()
        self.__delays: list[int] = list()
        self.__stop_event = threading.Event()
        self.__thread = threading.Thread(target=self.__run, name="histogram-jitter-monitor", daemon=True)

    def start(self) -> None:
        self.__thread.start()

    def stop(self) -> None:
        self.__stop_event.set()
        self.__thread.join(2.0)

    @property
    def windows(self) -> typing.Sequence[StallWindow]:
        return self.__windows

    @property
    def delays(self) -> typing.Sequence[int]:
        return self.__delays

    # this method runs on the monitor thread.
    def __run(self) -> None:
        interval_ns = int(self.__interval * 1e9)
        monitor_ident = threading.current_thread().ident
        previous_ns = time.perf_counter_ns()
        while not self.__stop_event.wait(self.__interval):
            now_ns = time.perf_counter_ns()
            delay_ns = now_ns - previous_ns - interval_ns
            self.__delays.append(delay_ns)
            if delay_ns > self.__threshold_ns:
                frames = sys._current_frames()
                main_frame = frames.get(self.__main_thread_ident)
                main_thread_label = _frame_label(main_frame, self.__depth) if main_frame else "<none>"
                running_labels: list[str] = list()
                for thread_ident, frame in frames.items():
                    if thread_ident in (monitor_ident, self.__main_thread_ident):
                        continue
                    if not _is_parked(frame):
                        running_labels.append(_frame_label(frame, 2))
                self.__windows.append(StallWindow(previous_ns + interval_ns, now_ns, main_thread_label, tuple(running_labels)))
            previous_ns = now_ns


class ThreadSampler:
    """Samples the innermost frames of every thread which is not parked, from a background thread."""

    def __init__(self, interval: float = 0.002, depth: int = 3) -> None:
        self.__interval = interval
        self.__depth = depth
        self.__samples: list[tuple[int, str]] = list()
        self.__stop_event = threading.Event()
        self.__thread = threading.Thread(target=self.__run, name="histogram-jitter-sampler", daemon=True)

    def start(self) -> None:
        self.__thread.start()

    def stop(self) -> None:
        self.__stop_event.set()
        self.__thread.join(2.0)

    @property
    def samples(self) -> typing.Sequence[tuple[int, str]]:
        return self.__samples

    # this method runs on the sampler thread.
    def __run(self) -> None:
        sampler_ident = threading.current_thread().ident
        thread_names: dict[int, str] = dict()
        sample_count = 0
        while not self.__stop_event.wait(self.__interval):
            # refresh the thread names occasionally rather than on every sample, to keep sampling cheap.
            if sample_count % 100 == 0:
                thread_names = {typing.cast(int, thread.ident): thread.name for thread in threading.enumerate()}
            sample_count += 1
            timestamp_ns = time.perf_counter_ns()
            # sys._current_frames is the only way to observe another thread's stack.
            for thread_ident, frame in sys._current_frames().items():
                if thread_ident == sampler_ident:
                    continue
                if not _is_parked(frame):
                    label = _frame_label(frame, self.__depth)
                    self.__samples.append((timestamp_ns, f"[{thread_names.get(thread_ident, str(thread_ident))}] {label}"))


_results: list[PhaseResult] = list()
_sampler_samples: list[tuple[int, str]] = list()
_stall_windows: list[StallWindow] = list()
_monitor_delays: list[int] = list()
_failures: list[str] = list()
_worker_thread: threading.Thread | None = None


def is_running() -> bool:
    """Return whether the measurement worker thread is still running."""
    return _worker_thread is not None and _worker_thread.is_alive()


def reset() -> None:
    """Discard every result gathered so far."""
    _results.clear()
    _sampler_samples.clear()
    _stall_windows.clear()
    _monitor_delays.clear()
    _failures.clear()


def find_data_item(document_model: DocumentModel.DocumentModel,
                   title_substring: str | None = None) -> DataItem.DataItem:
    """Return the data item to measure against.

    title_substring, if given, selects the live data item whose title contains it, which is how to choose between
    several hardware sources playing at once.

    Prefers the live data item of a playing hardware source, then any live data item, and finally the most
    recently modified two dimensional data item, so that a baseline run with acquisition stopped measures the
    same data as a run with acquisition playing. Raises RuntimeError if the document has no usable data item.
    """
    if title_substring:
        for data_item in document_model.data_items:
            if title_substring.lower() in data_item.title.lower() and data_item.data_shape:
                return data_item
        raise RuntimeError(f"no data item found whose title contains {title_substring!r}")
    from nion.instrumentation import HardwareSource
    for hardware_source in HardwareSource.HardwareSourceManager().hardware_sources:
        if getattr(hardware_source, "is_playing", False):
            playing_data_item = document_model.get_data_item_reference(hardware_source.hardware_source_id).data_item
            if playing_data_item:
                return playing_data_item
    for data_item in document_model.data_items:
        if data_item.is_live:
            return data_item
    candidates = [data_item for data_item in document_model.data_items
                  if data_item.data_shape and len(data_item.data_shape) == 2 and data_item.data_modified]
    if candidates:
        return max(candidates, key=lambda data_item: typing.cast(datetime.datetime, data_item.data_modified))
    raise RuntimeError("no two dimensional data item found in the document")


def _fetch_data(data_item: DataItem.DataItem) -> _NDArray:
    xdata = data_item.xdata
    assert xdata is not None
    return xdata.data


def _measure(name: str, description: str, fetch_fn: typing.Callable[[], _NDArray],
             work_fn: typing.Callable[[_NDArray], None], frame_probe_fn: typing.Callable[[], datetime.datetime | None]) -> PhaseResult:
    """Measure one phase and return its samples.

    fetch_fn supplies the array for each iteration and is timed separately from work_fn, so that the cost of
    getting the latest data is not confused with the cost of the computation over it. frame_probe_fn returns a
    value which changes when a new frame has been delivered, so that an iteration can be correlated with frame
    arrival even in the phases which do not refetch the data. The phase runs for at least ITERATION_COUNT
    iterations and at least MINIMUM_PHASE_DURATION_NS, whichever takes longer.
    """
    samples: list[IterationSample] = list()
    previous_buffer_address = 0
    previous_frame_marker: datetime.datetime | None = None
    index = 0
    phase_start_ns = time.perf_counter_ns()
    phase_cpu_start_ns = time.thread_time_ns()
    phase_process_cpu_start_ns = time.process_time_ns()
    while ((index < ITERATION_COUNT or time.perf_counter_ns() - phase_start_ns < MINIMUM_PHASE_DURATION_NS)
           and index < MAXIMUM_ITERATION_COUNT
           and time.perf_counter_ns() - phase_start_ns < MAXIMUM_PHASE_DURATION_NS):
        usage_before = resource.getrusage(resource.RUSAGE_SELF) if resource else None
        process_cpu_start_ns = time.process_time_ns()
        frame_marker = frame_probe_fn()
        start_ns = time.perf_counter_ns()
        data = fetch_fn()
        fetch_end_ns = time.perf_counter_ns()
        cpu_start_ns = time.thread_time_ns()
        work_fn(data)
        cpu_end_ns = time.thread_time_ns()
        end_ns = time.perf_counter_ns()
        process_cpu_ns = time.process_time_ns() - process_cpu_start_ns
        usage_after = resource.getrusage(resource.RUSAGE_SELF) if resource else None
        buffer_address = data.ctypes.data
        samples.append(IterationSample(index=index, start_ns=start_ns, fetch_end_ns=fetch_end_ns, end_ns=end_ns,
                                       cpu_ns=cpu_end_ns - cpu_start_ns, buffer_address=buffer_address,
                                       is_new_buffer=bool(previous_buffer_address) and buffer_address != previous_buffer_address,
                                       is_new_frame=previous_frame_marker is not None and frame_marker != previous_frame_marker,
                                       involuntary_switch_count=usage_after.ru_nivcsw - usage_before.ru_nivcsw if usage_after and usage_before else -1,
                                       minor_fault_count=usage_after.ru_minflt - usage_before.ru_minflt if usage_after and usage_before else -1,
                                       process_cpu_ns=process_cpu_ns))
        previous_buffer_address = buffer_address
        previous_frame_marker = frame_marker
        index += 1
    return PhaseResult(name=name, description=description, samples=samples,
                       phase_wall_ns=time.perf_counter_ns() - phase_start_ns,
                       phase_cpu_ns=time.thread_time_ns() - phase_cpu_start_ns,
                       phase_process_cpu_ns=time.process_time_ns() - phase_process_cpu_start_ns)


def _run(document_model: DocumentModel.DocumentModel, tag: str, title_substring: str | None) -> None:
    """Run every phase and store the results. This runs on the worker thread."""
    data_item = find_data_item(document_model, title_substring)
    latest_data = _fetch_data(data_item)
    copied_data = numpy.array(latest_data, copy=True)
    data_range = (float(latest_data.min()), float(latest_data.max()))
    if data_range[1] <= data_range[0]:
        # a uniform frame, such as one taken with the beam blanked, has no range to divide by.
        data_range = (data_range[0], data_range[0] + 1.0)
    # the data reference count says whether the data stays loaded, and no public property gives it.
    description = (f"{data_item.title!r} shape={latest_data.shape} dtype={latest_data.dtype} "
                   f"contiguous={latest_data.flags.c_contiguous} live={data_item.is_live} "
                   f"unloadable={data_item.is_unloadable} data_ref_count={data_item._data_ref_count} "
                   f"worker_qos={QOS_CLASS_NAMES.get(get_thread_qos_class(), '?')}")

    def probe_frame() -> datetime.datetime | None:
        return data_item.data_modified

    def histogram(data: _NDArray) -> None:
        numpy.histogram(data, BIN_COUNT)

    def bincount_histogram(data: _NDArray) -> None:
        # the formulation used by HistogramPanel: a handful of numpy calls rather than a python loop over blocks
        span = data_range[1] - data_range[0]
        numpy.bincount(numpy.clip(((BIN_COUNT + 2) * ((data.ravel() - data_range[0]) / span)).astype(int), 0, BIN_COUNT + 2), minlength=BIN_COUNT + 2)[1:BIN_COUNT + 1]

    def total(data: _NDArray) -> None:
        data.sum()

    def fetch_latest() -> _NDArray:
        return _fetch_data(data_item)

    _results.append(_measure(f"{tag}.refetch", description, fetch_latest, histogram, probe_frame))
    _results.append(_measure(f"{tag}.copy", description, lambda: copied_data, histogram, probe_frame))
    _results.append(_measure(f"{tag}.bincount", description, lambda: copied_data, bincount_histogram, probe_frame))
    _results.append(_measure(f"{tag}.sum", description, lambda: copied_data, total, probe_frame))


def start(document_model: DocumentModel.DocumentModel, tag: str = "live", *,
          title_substring: str | None = None, sample_threads: bool = SAMPLE_THREADS) -> None:
    """Start a measurement run on a worker thread and return immediately.

    The main thread is left free so that live acquisition keeps running at its normal rate. Pass a tag to label
    a run, for example "idle" for a run with live acquisition stopped, so that runs can be compared in one
    report. Any failure is recorded in the report rather than raised on the worker thread.

    The finished report is logged at the info level, so there is nothing to poll. title_substring selects the
    data item by title, for an instrument with several hardware sources playing at once. Pass sample_threads as
    False to omit the stack sampling, which is the control for whether the sampling itself affects the timings.
    """
    global _worker_thread
    assert not is_running(), "a measurement run is already in progress"
    monitor = StallMonitor()
    sampler = ThreadSampler() if sample_threads else None

    def run() -> None:
        try:
            _run(document_model, tag, title_substring)
        except Exception:
            _failures.append(f"{tag}: {traceback.format_exc()}")
        finally:
            monitor.stop()
            if sampler:
                sampler.stop()
                _sampler_samples.extend(sampler.samples)
            _stall_windows.extend(monitor.windows)
            _monitor_delays.extend(monitor.delays)
            # logging is thread safe and needs no marshalling to the main thread, unlike writing to a widget.
            logging.info(f"histogram_jitter finished\n\n{report()}")

    monitor.start()
    if sampler:
        sampler.start()
    _worker_thread = threading.Thread(target=run, name="histogram-jitter-worker", daemon=True)
    _worker_thread.start()


def _microseconds(nanoseconds: float) -> str:
    return f"{nanoseconds / 1000:.0f}us"


def _percentile(sorted_values: typing.Sequence[float], fraction: float) -> float:
    return sorted_values[int(fraction * (len(sorted_values) - 1))]


def _attribute(samples: typing.Sequence[IterationSample], limit: int) -> typing.Sequence[tuple[str, int]]:
    """Return the most commonly sampled running stacks observed during the given iterations."""
    timestamps = [timestamp_ns for timestamp_ns, _ in _sampler_samples]
    counter: collections.Counter[str] = collections.Counter()
    for sample in samples:
        start_index = bisect.bisect_left(timestamps, sample.fetch_end_ns)
        end_index = bisect.bisect_right(timestamps, sample.end_ns)
        for _, label in _sampler_samples[start_index:end_index]:
            counter[label] += 1
    return counter.most_common(limit)


def _stalled_overlap_ns(sample: IterationSample) -> int:
    """Return how much of an iteration's work overlapped a window where the interpreter could not run."""
    starts = [window.start_ns for window in _stall_windows]
    start_index = max(0, bisect.bisect_left(starts, sample.fetch_end_ns) - 4)
    overlap_ns = 0
    for window in _stall_windows[start_index:]:
        if window.start_ns > sample.end_ns:
            break
        overlap_ns += max(0, min(window.end_ns, sample.end_ns) - max(window.start_ns, sample.fetch_end_ns))
    return overlap_ns


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


def report() -> str:
    """Return the report text for every phase measured so far."""
    lines = list[str](get_header_lines())
    for failure in _failures:
        lines.append(f"!!! failure: {failure}")
    granularity_ns = measure_thread_time_granularity()
    is_clock_coarse = granularity_ns > 1_000_000 or not granularity_ns
    granularity_text = ("never advanced" if not granularity_ns
                        else f"{granularity_ns}ns" if granularity_ns < 1000 else f"{granularity_ns / 1000:.0f}us")
    lines.append(f"=== environment: {sys.platform}, {os.cpu_count()} cores, "
                 f"thread clock advances in steps of {granularity_text}")
    if is_clock_coarse:
        lines.append("    the thread clock is coarser than one iteration, so read the per phase cpu and stall")
        lines.append("    figures below and disregard the per iteration cpu, stall and cores busy figures")
    lines.append("")
    if _monitor_delays:
        sorted_delays = sorted(_monitor_delays)
        long_windows = sorted(window.duration_ns for window in _stall_windows)
        lines.append(f"=== interpreter availability ({len(_monitor_delays)} monitor wakeups over the whole run)")
        lines.append(f"    monitor delay beyond its 1ms sleep: median {_microseconds(statistics.median(sorted_delays))} "
                     f"p90 {_microseconds(_percentile(sorted_delays, 0.90))} p99 {_microseconds(_percentile(sorted_delays, 0.99))} "
                     f"max {_microseconds(sorted_delays[-1])}")
        lines.append(f"    windows over 3ms: {len(_stall_windows)}"
                     + (f", median {_microseconds(statistics.median(long_windows))}, max {_microseconds(long_windows[-1])}"
                        if long_windows else ""))
        if len(_stall_windows) > 1:
            spacings = [second.start_ns - first.start_ns for first, second in zip(_stall_windows, _stall_windows[1:])]
            total_ns = _stall_windows[-1].end_ns - _stall_windows[0].start_ns
            lines.append(f"    median spacing between windows {_microseconds(statistics.median(spacings))}, "
                         f"they cover {100.0 * sum(long_windows) / total_ns:.0f}% of the elapsed time")
            main_counter: collections.Counter[str] = collections.Counter()
            running_counter: collections.Counter[str] = collections.Counter()
            for window in _stall_windows:
                main_counter[window.main_thread_label] += 1
                for label in window.running_labels:
                    running_counter[label] += 1
            lines.append("    main thread at the end of those windows:")
            for label, count in main_counter.most_common(8):
                lines.append(f"      {count:5d}  {label}")
            lines.append("    other threads running at the end of those windows:")
            for label, count in running_counter.most_common(8):
                lines.append(f"      {count:5d}  {label}")
        lines.append("")
    for phase in _results:
        work_times = sorted(sample.work_ns for sample in phase.samples)
        median_work_ns = statistics.median(work_times)
        slow_threshold_ns = 1.8 * median_work_ns
        slow_samples = [sample for sample in phase.samples if sample.work_ns > slow_threshold_ns]
        # if nothing crossed the threshold, look at the slowest iterations anyway, so the report always shows
        # what the rest of the process was doing during the worst iterations of the phase.
        if not slow_samples:
            slow_samples = sorted(phase.samples, key=lambda sample: sample.work_ns)[-3:]
        slow_indexes = {sample.index for sample in slow_samples}
        fast_samples = [sample for sample in phase.samples if sample.index not in slow_indexes]
        elapsed_ns = phase.samples[-1].end_ns - phase.samples[0].start_ns
        frame_count = sum(1 for sample in phase.samples if sample.is_new_frame)
        lines.append(f"=== {phase.name} ({len(phase.samples)} iterations over {elapsed_ns / 1e6:.0f}ms)")
        lines.append(f"    data: {phase.description}")
        lines.append(f"    fetch: median {_microseconds(statistics.median(sample.fetch_ns for sample in phase.samples))} "
                     f"max {_microseconds(max(sample.fetch_ns for sample in phase.samples))}")
        lines.append(f"    work:  median {_microseconds(median_work_ns)} p90 {_microseconds(_percentile(work_times, 0.90))} "
                     f"p99 {_microseconds(_percentile(work_times, 0.99))} max {_microseconds(work_times[-1])} "
                     f"(max/median {work_times[-1] / median_work_ns:.1f}x)")
        lines.append(f"    cpu:   median {_microseconds(statistics.median(sample.cpu_ns for sample in phase.samples))} "
                     f"max {_microseconds(max(sample.cpu_ns for sample in phase.samples))}")
        lines.append(f"    phase:  wall {phase.phase_wall_ns / 1e6:.0f}ms, worker cpu {phase.phase_cpu_ns / 1e6:.0f}ms "
                     f"({100.0 * max(0, phase.phase_wall_ns - phase.phase_cpu_ns) / max(1, phase.phase_wall_ns):.0f}% stalled), "
                     f"process cpu {phase.phase_process_cpu_ns / 1e6:.0f}ms "
                     f"({phase.phase_process_cpu_ns / max(1, phase.phase_wall_ns):.1f} of {os.cpu_count()} cores busy)")
        if is_clock_coarse:
            lines.append(f"    stall: per iteration figures omitted; the thread clock is too coarse. overlap with "
                         f"windows where the interpreter could not run: "
                         f"{sum(_stalled_overlap_ns(sample) for sample in phase.samples) / 1e6:.0f}ms of "
                         f"{elapsed_ns / 1e6:.0f}ms elapsed")
        else:
            stall_ns = sum(sample.stall_ns for sample in phase.samples)
            stalled_overlap_ns = sum(_stalled_overlap_ns(sample) for sample in phase.samples)
            lines.append(f"    stall: total {stall_ns / 1e6:.0f}ms of {elapsed_ns / 1e6:.0f}ms elapsed, of which "
                         f"{100.0 * stalled_overlap_ns / max(1, stall_ns):.0f}% fell inside a window where the interpreter could not run")
        lines.append(f"    frames: {frame_count} new frames seen ({1e9 * frame_count / elapsed_ns:.1f} per second), "
                     f"{sum(1 for sample in phase.samples if sample.is_new_buffer)} new buffers")
        lines.append(f"    slow iterations (over {_microseconds(slow_threshold_ns)}): "
                     f"{sum(1 for sample in phase.samples if sample.work_ns > slow_threshold_ns)} of {len(phase.samples)}")
        if slow_samples:
            if is_clock_coarse:
                lines.append(f"      median work {_microseconds(statistics.median(sample.work_ns for sample in slow_samples))}, "
                             f"inside an unavailable window {_microseconds(statistics.median(_stalled_overlap_ns(sample) for sample in slow_samples))}")
            else:
                lines.append(f"      median work {_microseconds(statistics.median(sample.work_ns for sample in slow_samples))}, "
                             f"of which stalled {_microseconds(statistics.median(sample.stall_ns for sample in slow_samples))}, "
                             f"inside an unavailable window {_microseconds(statistics.median(_stalled_overlap_ns(sample) for sample in slow_samples))}")
            lines.append(f"      new frame: {sum(1 for sample in slow_samples if sample.is_new_frame)} of {len(slow_samples)} slow, "
                         f"{sum(1 for sample in fast_samples if sample.is_new_frame)} of {len(fast_samples)} fast")
            if not is_clock_coarse:
                lines.append(f"      cores busy in the whole process: median {statistics.median(sample.cores_busy for sample in slow_samples):.1f} during slow, "
                             f"{statistics.median(sample.cores_busy for sample in fast_samples):.1f} during fast, of {os.cpu_count()} cores")
            if resource:
                lines.append(f"      involuntary switches: median {statistics.median(sample.involuntary_switch_count for sample in slow_samples)}, "
                             f"minor faults: median {statistics.median(sample.minor_fault_count for sample in slow_samples)}")
            lines.append("      threads running during slow iterations:")
            for label, count in _attribute(slow_samples[:60], 8):
                lines.append(f"        {count:5d}  {label}")
        lines.append("")
    return "\n".join(lines)
