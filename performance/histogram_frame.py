# Time the histogram panel's work for one frame of display data, as its processor does for each frame during acquisition.
#
# Each frame computes the histogram of new display data, and separately its statistics, by the functions which the
# histogram panel's processor calls, with the statistics reusing a working array from one frame to the next as the
# processor does. Cropping to the region, the processor's thread, its contention with other threads and drawing are not
# part of the times.
#
# The standard case is a 2048x2048 float32 frame without a region:
#     python histogram_frame.py
#
# --region limits the work to a rectangle covering the middle quarter of the frame.
import argparse
import cProfile
import datetime
import gc
import importlib.metadata
import inspect
import os
import platform
import pstats
import statistics
import time
import typing
import weakref

import numpy

from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import HistogramPanel
from nion.swift.model import Graphics

NAME = "histogram_frame"

# the revision of the measured work.
REVISION = 1

# the packages whose versions the report lists.
PACKAGES = ("nionswift", "nionui", "niondata", "nionutils")


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
    # a single sample has no spread, and quantiles needs two values before Python 3.13.
    if len(times_ms) > 1:
        quartiles = statistics.quantiles(times_ms, n=4)
        iqr_ms = quartiles[2] - quartiles[0]
    else:
        iqr_ms = 0.0
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
    parser = argparse.ArgumentParser(description="Time the histogram panel's work for one frame of display data.")
    add_common_arguments(parser)
    parser.add_argument("--frames", type=positive_int, default=200, help="the frames timed, for the histogram and again for the statistics")
    parser.add_argument("--warm-up-frames", type=int, default=10, help="the frames handled before timing")
    parser.add_argument("--size", type=positive_int, default=2048, help="the width and height of each frame")
    parser.add_argument("--dtype", choices=("float32", "uint16"), default="float32", help="the type of the data")
    parser.add_argument("--region", action="store_true", help="limit the work to a rectangle covering the middle quarter of the frame")
    return parser, parser.parse_args()


class HistogramFrame:
    """Frames of display data, and the histogram panel's calculations of their histogram and statistics."""

    def __init__(self, arguments: argparse.Namespace) -> None:
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
        self.histogram_bin_count = 0

    # the region's data is calculated once for both the histogram and the statistics, so it is not part of either time.
    def prepare_frame(self, frame_index: int) -> None:
        xdata = DataAndMetadata.new_data_and_metadata(self.__frames[frame_index % len(self.__frames)])
        self.__region_xdata = HistogramPanel.calculate_region_data(weakref.ref(xdata), weakref.ref(self.__region) if self.__region else None)
        self.__data_range = self.__data_ranges[frame_index % len(self.__frames)]

    def run_histogram(self, frame_index: int) -> None:
        histogram_widget_data = HistogramPanel.calculate_histogram_widget_data(self.__region_xdata, self.__data_range)
        self.histogram_bin_count = len(histogram_widget_data.data) if histogram_widget_data.data is not None else 0

    def run_statistics(self, frame_index: int) -> None:
        if self.__statistics_scratch:
            HistogramPanel.calculate_statistics(self.__region_xdata, self.__data_range, self.__region, self.__displayed_intensity_calibration, self.__statistics_scratch)
        else:
            HistogramPanel.calculate_statistics(self.__region_xdata, self.__data_range, self.__region, self.__displayed_intensity_calibration)


def main() -> None:
    parser, arguments = parse_arguments()
    histogram_frame = HistogramFrame(arguments)
    histogram_times = time_frames(arguments, histogram_frame.run_histogram, histogram_frame.prepare_frame)
    statistics_times = time_frames(arguments, histogram_frame.run_statistics, histogram_frame.prepare_frame)
    print_report(parser, arguments, [("histogram", histogram_times), ("statistics", statistics_times)], {"histogram_bin_count": histogram_frame.histogram_bin_count})


if __name__ == "__main__":
    main()
