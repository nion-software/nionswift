# Time creating many data items, then deleting some and undoing the deletion, with the project in memory or in files.
#
# Creating appends one data item at a time, running the document controller's periodic every 50 items, and is timed
# once. Each round then selects the first display items in the data panel, deletes them, and undoes the deletion; the
# deletion and the undo are each timed with the periodic which follows them, once per round.
#
# The standard case is 1000 data items in memory, deleting 100 of them in each of 5 rounds:
#     python delete_undo.py
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

NAME = "delete_undo"

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
    parser = argparse.ArgumentParser(description="Time creating data items, then deleting some and undoing the deletion.")
    add_common_arguments(parser)
    parser.add_argument("--storage", choices=("memory", "file"), default="memory", help="where the project is stored")
    parser.add_argument("--items", type=positive_int, default=1000, help="the data items created")
    parser.add_argument("--delete-items", type=positive_int, default=100, help="the display items deleted in each round")
    parser.add_argument("--rounds", type=positive_int, default=5, help="the rounds of deleting and undoing")
    arguments = parser.parse_args()
    if arguments.delete_items > arguments.items:
        parser.error("--delete-items must not be more than --items")
    return parser, arguments


class DeleteUndo:
    """A project which creates data items, then deletes some of them and undoes the deletion."""

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

    def create(self) -> float:
        """Return the time in seconds to create the data items."""
        document_model = self.__document_controller.document_model
        start = time.perf_counter()
        for item_index in range(self.__arguments.items):
            document_model.append_data_item(DataItem.DataItem(numpy.zeros((8, 8))))
            if item_index % 50 == 0:
                self.__document_controller.periodic()
        self.__document_controller.periodic()
        return time.perf_counter() - start

    def delete(self) -> float:
        """Return the time in seconds to delete the first display items, which are selected beforehand."""
        display_items = list(self.__document_controller.document_model.display_items[:self.__arguments.delete_items])
        self.__document_controller.select_display_items_in_data_panel(display_items)
        self.__document_controller.periodic()
        start = time.perf_counter()
        self.__document_controller.delete_display_items(display_items)
        self.__document_controller.periodic()
        return time.perf_counter() - start

    def undo(self) -> float:
        """Return the time in seconds to undo the deletion."""
        start = time.perf_counter()
        self.__document_controller.handle_undo()
        self.__document_controller.periodic()
        elapsed = time.perf_counter() - start
        display_item_count = len(self.__document_controller.document_model.display_items)
        assert display_item_count == self.__arguments.items, f"the undo restored {display_item_count} of {self.__arguments.items} display items"
        return elapsed

    def teardown(self) -> None:
        self.__exit_stack.close()
        self.__test_setup = None


def main() -> None:
    parser, arguments = parse_arguments()
    delete_undo = DeleteUndo(arguments)
    delete_undo.setup()
    try:
        gc.collect()
        profiler = cProfile.Profile() if arguments.profile else None
        if profiler:
            profiler.enable()
        create_times = [delete_undo.create()]
        delete_times = list[float]()
        undo_times = list[float]()
        for _ in range(arguments.rounds):
            delete_times.append(delete_undo.delete())
            undo_times.append(delete_undo.undo())
        if profiler:
            profiler.disable()
            pstats.Stats(profiler).sort_stats("tottime").print_stats(15)
    finally:
        delete_undo.teardown()
    print_report(parser, arguments, [("create", create_times), ("delete", delete_times), ("undo", undo_times)], {"display_items": arguments.items})


if __name__ == "__main__":
    main()
