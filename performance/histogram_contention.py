# Measure how long the histogram panel's calculations of one frame of display data block another thread.
#
# The panel bins each frame in slices so that every temporary stays small, and this measures how long the calculations
# of a frame block another thread. A worker thread calculates the histogram and the statistics of each frame back to back,
# by the functions which the histogram panel's processor calls, while the main thread sleeps 1 ms at a time and records
# how late it wakes. The histogram measurement is the longest lateness during each frame's calculations, and the idle
# measurement is the longest lateness in windows of the same length after the worker stops, which is the machine's floor.
# The region's data, the processor's own thread and drawing are not part of the measurements, and histogram_frame.py
# times the calculations themselves.
#
# The standard case is a 2048x2048 float32 frame without a region:
#     python histogram_contention.py
#
# --region limits the work to a rectangle covering the middle quarter of the frame.
import argparse
import bisect
import cProfile
import datetime
import gc
import importlib.metadata
import inspect
import os
import platform
import pstats
import statistics
import sys
import threading
import time
import typing
import weakref

import numpy

from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import HistogramPanel
from nion.swift.model import Graphics

NAME = "histogram_contention"

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
    parser = argparse.ArgumentParser(description="Measure how long the histogram panel's calculations of one frame block another thread.")
    add_common_arguments(parser)
    parser.add_argument("--frames", type=positive_int, default=100, help="the frames measured")
    parser.add_argument("--warm-up-frames", type=int, default=5, help="the frames handled before measuring")
    parser.add_argument("--size", type=positive_int, default=2048, help="the width and height of each frame")
    parser.add_argument("--dtype", choices=("float32", "uint16"), default="float32", help="the type of the data")
    parser.add_argument("--region", action="store_true", help="limit the work to a rectangle covering the middle quarter of the frame")
    return parser, parser.parse_args()


class HistogramContention:
    """Frames of display data, and the histogram panel's calculations of their histogram and statistics on a worker thread."""

    def __init__(self, arguments: argparse.Namespace) -> None:
        self.__arguments = arguments
        random_generator = numpy.random.default_rng(0)
        shape = (arguments.size, arguments.size)
        # a few distinct frames, so that each frame's data is new to the calculations.
        self.__frames = [numpy.clip(random_generator.normal(1000.0, 200.0, shape), 0, 65535).astype(arguments.dtype) for _ in range(4)]
        self.__data_ranges = [(float(numpy.amin(frame)), float(numpy.amax(frame))) for frame in self.__frames]
        self.__region: Graphics.Graphic | None = None
        if arguments.region:
            rectangle_graphic = Graphics.RectangleGraphic()
            rectangle_graphic.bounds = (0.25, 0.25), (0.5, 0.5)
            self.__region = rectangle_graphic
        self.__displayed_intensity_calibration = Calibration.Calibration()
        # a nionswift before the working array calculates the statistics without one.
        self.__statistics_scratch = HistogramPanel.StatisticsScratchArray() if "scratch" in inspect.signature(HistogramPanel.calculate_statistics).parameters else None
        self.__region_xdata: DataAndMetadata.DataAndMetadata | None = None
        self.__data_range = self.__data_ranges[0]

        # the worker thread writes these, and the main thread reads them only after joining it.
        self.frame_windows = list[tuple[int, int]]()
        self.histogram_bin_count = 0
        self.profiler = cProfile.Profile() if arguments.profile else None

    # the region's data is calculated before each frame's window, so that the window covers the histogram and statistics.
    def prepare_frame(self, frame_index: int) -> None:
        xdata = DataAndMetadata.new_data_and_metadata(self.__frames[frame_index % len(self.__frames)])
        self.__region_xdata = HistogramPanel.calculate_region_data(weakref.ref(xdata), weakref.ref(self.__region) if self.__region else None)
        self.__data_range = self.__data_ranges[frame_index % len(self.__frames)]

    # the histogram and statistics of the prepared frame, as the processor calculates them.
    def run_frame(self) -> None:
        histogram_widget_data = HistogramPanel.calculate_histogram_widget_data(self.__region_xdata, self.__data_range)
        self.histogram_bin_count = len(histogram_widget_data.data) if histogram_widget_data.data is not None else 0
        if self.__statistics_scratch:
            HistogramPanel.calculate_statistics(self.__region_xdata, self.__data_range, self.__region, self.__displayed_intensity_calibration, self.__statistics_scratch)
        else:
            HistogramPanel.calculate_statistics(self.__region_xdata, self.__data_range, self.__region, self.__displayed_intensity_calibration)

    def run_frames(self) -> None:
        """Run the warm-up frames, then the measured frames, recording the start and end of each measured frame's calculations.

        It runs on the worker thread.
        """
        arguments = self.__arguments
        for frame_index in range(arguments.warm_up_frames):
            self.prepare_frame(frame_index)
            self.run_frame()
        gc.collect()
        # cProfile from Python 3.12 profiles every thread, so the main thread's sleeps appear in the profile too.
        if self.profiler:
            self.profiler.enable()
        for frame_index in range(arguments.warm_up_frames, arguments.warm_up_frames + arguments.frames):
            self.prepare_frame(frame_index)
            start_ns = time.perf_counter_ns()
            self.run_frame()
            self.frame_windows.append((start_ns, time.perf_counter_ns()))
            # yield the lock between frames, so that a wakeup's lateness comes from a single frame.
            time.sleep(0)
        if self.profiler:
            self.profiler.disable()


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
    """Measure the worker's frames, then the idle windows, and print the report."""
    parser, arguments = parse_arguments()
    histogram_contention = HistogramContention(arguments)
    worker_thread = threading.Thread(target=histogram_contention.run_frames)
    worker_thread.start()
    histogram_wakeups = record_wakeups(worker_thread.is_alive)
    worker_thread.join()
    assert len(histogram_contention.frame_windows) == arguments.frames, f"the worker measured only {len(histogram_contention.frame_windows)} frames"
    if histogram_contention.profiler:
        pstats.Stats(histogram_contention.profiler).sort_stats("tottime").print_stats(15)
    # a wakeup up to one sleep after a frame's calculations end may have been delayed by them.
    histogram_windows = [(start_ns, end_ns + SLEEP_NS) for start_ns, end_ns in histogram_contention.frame_windows]
    histogram_delays = get_longest_delays(histogram_wakeups, histogram_windows)
    # the idle windows follow one another, each as long as the median window of a frame.
    window_ns = int(statistics.median(end_ns - start_ns for start_ns, end_ns in histogram_windows))
    idle_start_ns = time.perf_counter_ns()
    idle_end_ns = idle_start_ns + window_ns * arguments.frames
    idle_wakeups = record_wakeups(lambda: time.perf_counter_ns() < idle_end_ns)
    idle_windows = [(idle_start_ns + window_index * window_ns, idle_start_ns + (window_index + 1) * window_ns) for window_index in range(arguments.frames)]
    idle_delays = get_longest_delays(idle_wakeups, idle_windows)
    # no public API says whether the interpreter lock is enabled.
    interpreter_lock = "enabled" if sys._is_gil_enabled() else "disabled"
    print_report(parser, arguments, [("histogram", histogram_delays), ("idle", idle_delays)],
                 {"interpreter_lock": interpreter_lock, "histogram_bin_count": histogram_contention.histogram_bin_count})


if __name__ == "__main__":
    main()
