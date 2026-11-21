# Time the main thread's handling of one live frame while the data panel holds many display items.
#
# Each frame queues new data for each channel's data item, as a hardware source does, and runs the document controller's
# periodic, which applies the data. Each data item then fires item_changed_event, and the data panel re-sorts its display
# item with a binary search, calling the sort key about log n times. The time covers the data update and the re-sort,
# but not drawing, since the test user interface draws nothing.
#
# The standard case is two scan channels of 16x16 among 5000 display items:
#     python data_panel_resort.py
#
# --live-computation adds an FFT of the first channel, which is live because its source is live.
import argparse
import contextlib
import cProfile
import datetime
import gc
import importlib.metadata
import os
import platform
import pstats
import statistics
import time
import typing

import numpy

from nion.data import DataAndMetadata
from nion.swift import Facade
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.test import TestContext

NAME = "data_panel_resort"

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
    parser = argparse.ArgumentParser(description="Time the main thread's handling of one live frame with many display items.")
    add_common_arguments(parser)
    parser.add_argument("--frames", type=positive_int, default=500, help="the frames timed")
    parser.add_argument("--warm-up-frames", type=int, default=20, help="the frames handled before timing")
    parser.add_argument("--display-items", type=int, default=5000, help="the display items which are not live")
    parser.add_argument("--channels", type=positive_int, default=2, help="the live channels")
    parser.add_argument("--size", type=positive_int, default=16, help="the width and height of each channel's image")
    parser.add_argument("--live-computation", action="store_true", help="add a live FFT of the first channel")
    return parser, parser.parse_args()


class DataPanelResort:
    """A document with many display items and live channels, receiving one frame of data at a time."""

    def __init__(self, arguments: argparse.Namespace) -> None:
        self.__arguments = arguments
        self.__frames = [numpy.full((arguments.size, arguments.size), frame_index, numpy.uint32) for frame_index in range(64)]
        self.__test_setup: TestContext.TestSetup | None = None
        self.__exit_stack = contextlib.ExitStack()
        self.__data_item_references = list[DocumentModel.DocumentModel.DataItemReference]()
        self.__channel_data_items = list[DataItem.DataItem]()
        self.data_panel_item_count = 0

    def setup(self) -> None:
        arguments = self.__arguments
        # the computation of the FFT needs the API broker which the Facade module registers.
        Facade.initialize()
        self.__test_setup = TestContext.TestSetup()
        test_context = self.__exit_stack.enter_context(TestContext.create_memory_context())
        self.__document_controller = test_context.create_document_controller()
        document_model = self.__document_controller.document_model
        self.__document_model = document_model
        # one transaction writes the project once, rather than once for each item.
        with document_model.transaction_context():
            for _ in range(arguments.display_items):
                document_model.append_data_item(DataItem.DataItem(numpy.zeros((2, 2), numpy.uint32)))
        # a hardware source starts a data item reference for each channel it acquires.
        for channel_index in range(arguments.channels):
            data_item = DataItem.DataItem(numpy.zeros((arguments.size, arguments.size), numpy.uint32))
            data_item.title = f"Scan ({channel_index})"
            document_model.append_data_item(data_item)
            data_item_reference_key = document_model.make_data_item_reference_key("scan", str(channel_index))
            document_model.setup_channel(data_item_reference_key, data_item)
            data_item_reference = document_model.get_data_item_reference(data_item_reference_key)
            data_item_reference.start()
            self.__data_item_references.append(data_item_reference)
            self.__channel_data_items.append(data_item)
        if arguments.live_computation:
            display_item = document_model.get_display_item_for_data_item(self.__channel_data_items[0])
            assert display_item
            document_model.get_fft_new(display_item, self.__channel_data_items[0])
        self.__document_controller.periodic()
        # the data panel must hold the display items, or the re-sort searches a short list.
        self.data_panel_item_count = len(self.__document_controller.display_items_model.items)
        assert self.data_panel_item_count >= arguments.display_items + arguments.channels, f"the data panel holds only {self.data_panel_item_count} items"

    # a hardware source queues the data from its own thread, so the queueing is not part of the frame's time.
    def prepare_frame(self, frame_index: int) -> None:
        for channel_index, channel_data_item in enumerate(self.__channel_data_items):
            xdata = DataAndMetadata.new_data_and_metadata(self.__frames[(frame_index + channel_index) % len(self.__frames)])
            self.__document_model._queue_data_item_update(channel_data_item, xdata)

    def run_frame(self, frame_index: int) -> None:
        self.__document_controller.periodic()

    def teardown(self) -> None:
        for data_item_reference in self.__data_item_references:
            data_item_reference.stop()
        self.__exit_stack.close()
        self.__test_setup = None


def main() -> None:
    parser, arguments = parse_arguments()
    data_panel_resort = DataPanelResort(arguments)
    data_panel_resort.setup()
    try:
        frame_times = time_frames(arguments, data_panel_resort.run_frame, data_panel_resort.prepare_frame)
    finally:
        data_panel_resort.teardown()
    print_report(parser, arguments, [("frame", frame_times)], {"data_panel_item_count": data_panel_resort.data_panel_item_count})


if __name__ == "__main__":
    main()
