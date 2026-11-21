# Time the display's data range of one frame of display data, and measure how long it blocks another thread.
#
# A display update makes a new data range processor for each frame and reads its result, on a thread of the display's
# thread pool during acquisition. Each frame here does the same with DisplayItem.DataRangeProcessor and new display data,
# so the time covers numpy.amin and numpy.amax of the whole frame and the processor's checks of the range. The data_range
# measurement is that time for one frame. The blocking measurement runs the same work on a worker thread frame after
# frame, while the main thread sleeps 1 ms at a time and records how late it wakes, and is the longest lateness during
# each frame's work. The idle measurement is the longest lateness in windows of the same length after the worker stops,
# which is the machine's floor. Making the display data, the other display calculations, the thread pool and drawing
# are not part of the measurements.
#
# The standard case is a 2048x2048 float32 frame:
#     python display_data_range.py
#
# --dtype uint16 measures integer data. Complex data has no option, since its display data is already float data and
# its data range is computed in the same way.
import argparse
import bisect
import cProfile
import datetime
import gc
import importlib.metadata
import os
import platform
import pstats
import statistics
import sys
import threading
import time
import typing

import numpy

from nion.data import DataAndMetadata
from nion.swift.model import DisplayItem

NAME = "display_data_range"

# the revision of the measured work.
REVISION = 1

# the packages whose versions the report lists.
PACKAGES = ("nionswift", "nionui", "niondata", "nionutils")

# the time the main thread sleeps between wakeups, in nanoseconds.
SLEEP_NS = 1_000_000


def positive_int(text: str) -> int:
    """Return text as an integer, for an option which must be at least one."""
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"{value} is not at least 1")
    return value


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the options which each script shares to parser."""
    parser.add_argument("--label", default="", help="a label for the results, such as a branch name")
    parser.add_argument("--profile", action="store_true", help="print the functions taking the most time, which inflates the times")


def time_frames(arguments: argparse.Namespace, run_frame: typing.Callable[[int], None], prepare_frame: typing.Callable[[int], None] | None = None) -> typing.Sequence[float]:
    """Return the time in seconds of run_frame for each frame, after the warm-up frames.

    prepare_frame, when given, runs before each frame and is not timed. With --profile, the frames run under cProfile and
    the functions taking the most time are printed.
    """
    def handle_frame(frame_index: int) -> float:
        if prepare_frame:
            prepare_frame(frame_index)
        start = time.perf_counter()
        run_frame(frame_index)
        return time.perf_counter() - start

    for frame_index in range(arguments.warm_up_frames):
        handle_frame(frame_index)
    gc.collect()
    profiler = cProfile.Profile() if arguments.profile else None
    if profiler:
        profiler.enable()
    frame_times = [handle_frame(frame_index) for frame_index in range(arguments.frames)]
    if profiler:
        profiler.disable()
        pstats.Stats(profiler).sort_stats("tottime").print_stats(15)
    return frame_times


def get_statistics(times: typing.Sequence[float]) -> tuple[float, float, float]:
    """Return the median, 90th percentile and interquartile range of times, in milliseconds."""
    times_ms = sorted(time_s * 1000 for time_s in times)
    quartiles = statistics.quantiles(times_ms, n=4)
    iqr_ms = quartiles[2] - quartiles[0]
    return statistics.median(times_ms), times_ms[int(len(times_ms) * 0.9)], iqr_ms


def get_version(distribution_name: str) -> str:
    """Return the installed version of a distribution."""
    try:
        return importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        # a checkout on the path which is not installed has no version.
        return "not installed"


def print_report(parser: argparse.ArgumentParser, arguments: argparse.Namespace, measurements: typing.Sequence[tuple[str, typing.Sequence[float]]],
                 details: typing.Mapping[str, int | float | str]) -> None:
    """Print the report of a run, then one table row for each measurement unless the run was profiled.

    measurements holds the name of each measurement and its times in seconds. details holds counts which confirm that the
    run measured what it intends.
    """
    date_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    options_text = " ".join(f"{name}={value}" for name, value in vars(arguments).items() if name not in ("label", "profile") and value != parser.get_default(name)) or "defaults"
    versions = {distribution_name: get_version(distribution_name) for distribution_name in PACKAGES}
    print(f"{NAME}, revision {REVISION}")
    print(f"date      {date_text}")
    if arguments.label:
        print(f"label     {arguments.label}")
    print(f"machine   {platform.node()}, {platform.platform()}, {os.cpu_count()} processors")
    print(f"software  Python {platform.python_version()}, numpy {numpy.__version__}, " + ", ".join(f"{name} {version}" for name, version in versions.items()))
    print(f"options   {options_text}")
    if details:
        print("details   " + ", ".join(f"{name} {value}" for name, value in details.items()))
    rows = list[str]()
    for measurement_name, times in measurements:
        median_ms, p90_ms, iqr_ms = get_statistics(times)
        print(f"{measurement_name:9} median {median_ms:.3f} ms  p90 {p90_ms:.3f} ms  iqr {iqr_ms:.3f} ms  ({len(times)} samples)")
        rows.append(f"| {date_text} | {platform.node()} | nionswift {versions['nionswift']} | {arguments.label} | {options_text} | {measurement_name} | {len(times)} "
                    f"| {median_ms:.3f} | {p90_ms:.3f} | {iqr_ms:.3f} |")
    if arguments.profile:
        print("The profiler inflates the times, so there are no table rows.")
    else:
        print()
        print("\n".join(rows))


def parse_arguments() -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    """Return the parser and the options from the command line."""
    parser = argparse.ArgumentParser(description="Time the display's data range of one frame, and measure how long it blocks another thread.")
    add_common_arguments(parser)
    parser.add_argument("--frames", type=positive_int, default=200, help="the frames timed, and again the frames measured on the worker thread")
    parser.add_argument("--warm-up-frames", type=int, default=10, help="the frames handled before timing, and again before measuring")
    parser.add_argument("--size", type=positive_int, default=2048, help="the width and height of each frame")
    parser.add_argument("--dtype", choices=("float32", "uint16"), default="float32", help="the type of the data")
    return parser, parser.parse_args()


class DisplayDataRange:
    """Frames of display data, and the display's calculation of their data range."""

    def __init__(self, arguments: argparse.Namespace) -> None:
        self.__arguments = arguments
        random_generator = numpy.random.default_rng(0)
        shape = (arguments.size, arguments.size)
        # a few distinct frames, so that each frame's data is new to the calculation.
        self.__frames = [numpy.clip(random_generator.normal(1000.0, 200.0, shape), 0, 65535).astype(arguments.dtype) for _ in range(4)]
        self.__data_range_processor: DisplayItem.DataRangeProcessor | None = None

        # the worker thread writes these, and the main thread reads them only after joining it.
        self.frame_windows = list[tuple[int, int]]()
        self.data_range: tuple[float, float] | None = None

    # a display update makes a new processor for each frame, which is not part of the time.
    def prepare_frame(self, frame_index: int) -> None:
        xdata = DataAndMetadata.new_data_and_metadata(self.__frames[frame_index % len(self.__frames)])
        self.__data_range_processor = DisplayItem.DataRangeProcessor(data_metadata=xdata.data_metadata, display_data=xdata)

    # the data range of the prepared frame, read as the display reads it.
    def run_frame(self, frame_index: int) -> None:
        assert self.__data_range_processor
        self.data_range = typing.cast(tuple[float, float] | None, self.__data_range_processor.get_result("data_range"))

    def run_frames(self) -> None:
        """Run the warm-up frames, then the measured frames, recording the start and end of each measured frame's data range.

        It runs on the worker thread.
        """
        arguments = self.__arguments
        for frame_index in range(arguments.warm_up_frames):
            self.prepare_frame(frame_index)
            self.run_frame(frame_index)
        gc.collect()
        for frame_index in range(arguments.warm_up_frames, arguments.warm_up_frames + arguments.frames):
            self.prepare_frame(frame_index)
            start_ns = time.perf_counter_ns()
            self.run_frame(frame_index)
            self.frame_windows.append((start_ns, time.perf_counter_ns()))
            # yield the lock between frames, so that a wakeup's lateness comes from a single frame.
            time.sleep(0)


def record_wakeups(is_running: typing.Callable[[], bool]) -> typing.Sequence[tuple[int, int]]:
    """Sleep 1 ms at a time while is_running returns true.

    Return the time of each wakeup and its lateness beyond the sleep, in nanoseconds, in order of time.
    """
    wakeups = list[tuple[int, int]]()
    previous_ns = time.perf_counter_ns()
    while is_running():
        time.sleep(SLEEP_NS / 1e9)
        now_ns = time.perf_counter_ns()
        wakeups.append((now_ns, now_ns - previous_ns - SLEEP_NS))
        previous_ns = now_ns
    return wakeups


def get_longest_delays(wakeups: typing.Sequence[tuple[int, int]], windows: typing.Sequence[tuple[int, int]]) -> typing.Sequence[float]:
    """Return the longest lateness in seconds of the wakeups within each window of start and end times in nanoseconds.

    A window without a wakeup takes the lateness of the first wakeup after it.
    """
    wakeup_times = [wakeup_ns for wakeup_ns, _ in wakeups]
    longest_delays = list[float]()
    for start_ns, end_ns in windows:
        first_index = bisect.bisect_left(wakeup_times, start_ns)
        # a sleep which spans the whole window wakes after it.
        stop_index = max(bisect.bisect_right(wakeup_times, end_ns), first_index + 1)
        longest_delays.append(max(lateness_ns for _, lateness_ns in wakeups[first_index:stop_index]) / 1e9)
    return longest_delays


def main() -> None:
    """Time the data range of each frame, measure how long the worker's frames block the main thread, then the idle windows, and print the report."""
    parser, arguments = parse_arguments()
    display_data_range = DisplayDataRange(arguments)
    # --profile profiles only these frames, since the blocking measurement prints no profile of its own.
    data_range_times = time_frames(arguments, display_data_range.run_frame, display_data_range.prepare_frame)
    worker_thread = threading.Thread(target=display_data_range.run_frames)
    worker_thread.start()
    blocking_wakeups = record_wakeups(worker_thread.is_alive)
    worker_thread.join()
    assert len(display_data_range.frame_windows) == arguments.frames, f"the worker measured only {len(display_data_range.frame_windows)} frames"
    # a wakeup up to one sleep after a frame's data range ends may have been delayed by it.
    blocking_windows = [(start_ns, end_ns + SLEEP_NS) for start_ns, end_ns in display_data_range.frame_windows]
    blocking_delays = get_longest_delays(blocking_wakeups, blocking_windows)
    # the idle windows follow one another, each as long as the median window of a frame.
    window_ns = int(statistics.median(end_ns - start_ns for start_ns, end_ns in blocking_windows))
    idle_start_ns = time.perf_counter_ns()
    idle_end_ns = idle_start_ns + window_ns * arguments.frames
    idle_wakeups = record_wakeups(lambda: time.perf_counter_ns() < idle_end_ns)
    idle_windows = [(idle_start_ns + window_index * window_ns, idle_start_ns + (window_index + 1) * window_ns) for window_index in range(arguments.frames)]
    idle_delays = get_longest_delays(idle_wakeups, idle_windows)
    # no public API says whether the interpreter lock is enabled.
    interpreter_lock = "enabled" if sys._is_gil_enabled() else "disabled"
    # the processor gives no data range when its calculation fails, since it ignores the exception.
    data_range = display_data_range.data_range
    data_range_text = f"{data_range[0]:g} to {data_range[1]:g}" if data_range else "none"
    print_report(parser, arguments, [("data_range", data_range_times), ("blocking", blocking_delays), ("idle", idle_delays)],
                 {"interpreter_lock": interpreter_lock, "data_range": data_range_text})


if __name__ == "__main__":
    main()
