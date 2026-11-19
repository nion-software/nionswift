# Time appending a data item and editing a display property in projects of several sizes, with the project in memory or
# in files.
#
# For each size, the project is first filled to that many data items inside a transaction, which writes the project
# once. Each append sample then appends one data item and is timed alone; the document controller's periodic and the
# removal of the appended data item follow it untimed, so that every sample runs in a project of the same size. Each edit
# sample changes the display limits of the first display item, which writes the project, and is timed alone.
#
# The standard case is 250 appends and 250 edits in memory at each of 1000, 2000 and 4000 data items:
#     python append_edit.py
#
# --storage file stores the project in a temporary directory.
import argparse
import contextlib
import cProfile
import datetime
import gc
import importlib.metadata
import os
import pathlib
import platform
import pstats
import statistics
import tempfile
import time
import typing

import numpy

from nion.swift.model import DataItem
from nion.swift.test import Storage_test
from nion.swift.test import TestContext

NAME = "append_edit"

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
        print(f"{measurement_name:11} median {median_ms:.3f} ms  p90 {p90_ms:.3f} ms  iqr {iqr_ms:.3f} ms  ({len(times)} samples)")
        rows.append(f"| {date_text} | {platform.node()} | nionswift {versions['nionswift']} | {arguments.label} | {options_text} | {measurement_name} | {len(times)} "
                    f"| {median_ms:.3f} | {p90_ms:.3f} | {iqr_ms:.3f} |")
    if arguments.profile:
        print("The profiler inflates the times, so there are no table rows.")
    else:
        print()
        print("\n".join(rows))


def parse_arguments() -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    """Return the parser and the options from the command line."""
    parser = argparse.ArgumentParser(description="Time appending a data item and editing a display property in projects of several sizes.")
    add_common_arguments(parser)
    parser.add_argument("--storage", choices=("memory", "file"), default="memory", help="where the project is stored")
    parser.add_argument("--sizes", type=positive_int, nargs="+", default=[1000, 2000, 4000], help="the project sizes, in data items, in increasing order")
    parser.add_argument("--samples", type=positive_int, default=250, help="the appends and the edits timed at each size")
    arguments = parser.parse_args()
    if arguments.sizes != sorted(set(arguments.sizes)):
        parser.error("--sizes must be distinct and in increasing order")
    return parser, arguments


class AppendEdit:
    """A project which grows to each size in turn, and appends data items and edits a display property at each size."""

    def __init__(self, arguments: argparse.Namespace) -> None:
        self.__arguments = arguments
        self.__test_setup: TestContext.TestSetup | None = None
        self.__exit_stack = contextlib.ExitStack()

    def setup(self) -> None:
        self.__test_setup = TestContext.TestSetup()
        if self.__arguments.storage == "file":
            # the temporary profile context stores its files in the current directory, in every nionswift this measures.
            temporary_directory = self.__exit_stack.enter_context(tempfile.TemporaryDirectory())
            self.__exit_stack.enter_context(contextlib.chdir(pathlib.Path(temporary_directory)))
            test_context: TestContext.MemoryProfileContext | TestContext.FileProfileContext = self.__exit_stack.enter_context(Storage_test.create_temp_profile_context())
        else:
            test_context = self.__exit_stack.enter_context(TestContext.create_memory_context())
        self.__document_controller = test_context.create_document_controller()

    def fill(self, size: int) -> None:
        """Append data items until the project holds size of them, writing the project once."""
        document_model = self.__document_controller.document_model
        with document_model.transaction_context():
            for _ in range(size - len(document_model.data_items)):
                document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8))))
        self.__document_controller.periodic()
        display_item_count = len(document_model.display_items)
        assert display_item_count == size, f"the project holds {display_item_count} display items rather than {size}"

    def append(self) -> float:
        """Return the time in seconds to append one data item, which is removed again afterwards."""
        document_model = self.__document_controller.document_model
        data_item = DataItem.DataItem(numpy.zeros((8, 8)))
        start = time.perf_counter()
        document_model.append_data_item(data_item)
        elapsed = time.perf_counter() - start
        self.__document_controller.periodic()
        document_model.remove_data_item(data_item)
        self.__document_controller.periodic()
        return elapsed

    def edit(self, sample_index: int) -> float:
        """Return the time in seconds to change the display limits of the first display item."""
        display_data_channel = self.__document_controller.document_model.display_items[0].display_data_channels[0]
        # the limits alternate, so that each edit changes them.
        display_limits = (0.0, float(1 + sample_index % 2))
        start = time.perf_counter()
        display_data_channel.display_limits = display_limits
        elapsed = time.perf_counter() - start
        self.__document_controller.periodic()
        return elapsed

    def teardown(self) -> None:
        self.__exit_stack.close()
        self.__test_setup = None


def main() -> None:
    parser, arguments = parse_arguments()
    append_edit = AppendEdit(arguments)
    append_edit.setup()
    measurements = list[tuple[str, typing.Sequence[float]]]()
    try:
        profiler = cProfile.Profile() if arguments.profile else None
        for size in arguments.sizes:
            append_edit.fill(size)
            gc.collect()
            if profiler:
                profiler.enable()
            append_times = [append_edit.append() for _ in range(arguments.samples)]
            edit_times = [append_edit.edit(sample_index) for sample_index in range(arguments.samples)]
            if profiler:
                profiler.disable()
            measurements.append((f"append {size}", append_times))
            measurements.append((f"edit {size}", edit_times))
        if profiler:
            pstats.Stats(profiler).sort_stats("tottime").print_stats(15)
    finally:
        append_edit.teardown()
    print_report(parser, arguments, measurements, {"sizes": " ".join(str(size) for size in arguments.sizes)})


if __name__ == "__main__":
    main()
