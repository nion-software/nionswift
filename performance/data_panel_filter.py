# Time a text filter change in the data panel while it holds many display items.
#
# Each round narrows the filter to the text which half of the display items' titles hold, then widens it back to no
# filter, as the data panel's search field does when the text is typed and then cleared. The filtered display items model
# applies each change at once, inserting or removing display items in the data panel's list, so the time covers the
# filter and the list's update, but not drawing, since the test user interface draws nothing. A periodic after each
# change runs the work which the change queues, such as showing the thumbnails in view, and is not timed.
#
# The standard case is 20000 display items, with 20 rounds:
#     python data_panel_filter.py
#
# --display-items and --rounds change the number of display items and of rounds.
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

from nion.swift.model import DataItem
from nion.swift.test import TestContext

NAME = "data_panel_filter"

# the revision of the measured work.
REVISION = 1

# the packages whose versions the report lists.
PACKAGES = ("nionswift", "nionui", "niondata", "nionutils")

# the text which narrows the filter. "an" alone also matches the month in each item's date in January.
NARROW_TEXT = "_an"


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


def time_rounds(arguments: argparse.Namespace, changes: typing.Sequence[tuple[typing.Callable[[], None], typing.Callable[[], None]]]) -> typing.Sequence[typing.Sequence[float]]:
    """Return the times in seconds of each change, one for each round, after the warm-up rounds.

    changes holds, for each change, a function which makes it and a function which finishes it, which is not timed. Each
    round makes each change in turn. With --profile, the rounds run under cProfile and the functions taking the most time
    are printed.
    """
    def handle_change(make_change: typing.Callable[[], None], finish_change: typing.Callable[[], None]) -> float:
        start = time.perf_counter()
        make_change()
        change_time = time.perf_counter() - start
        finish_change()
        return change_time

    for _ in range(arguments.warm_up_rounds):
        for make_change, finish_change in changes:
            handle_change(make_change, finish_change)
    gc.collect()
    profiler = cProfile.Profile() if arguments.profile else None
    if profiler:
        profiler.enable()
    change_times = [list[float]() for _ in changes]
    for _ in range(arguments.rounds):
        for (make_change, finish_change), times in zip(changes, change_times):
            times.append(handle_change(make_change, finish_change))
    if profiler:
        profiler.disable()
        pstats.Stats(profiler).sort_stats("tottime").print_stats(15)
    return change_times


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
    parser = argparse.ArgumentParser(description="Time a text filter change in the data panel with many display items.")
    add_common_arguments(parser)
    parser.add_argument("--rounds", type=positive_int, default=20, help="the rounds timed, each narrowing the filter and then widening it")
    parser.add_argument("--warm-up-rounds", type=int, default=2, help="the rounds made before timing")
    parser.add_argument("--display-items", type=int, default=20000, help="the display items, half of which the narrowed filter matches")
    return parser, parser.parse_args()


class DataPanelFilter:
    """A document with many display items, whose data panel filters them by text as its search field does."""

    def __init__(self, arguments: argparse.Namespace) -> None:
        self.__arguments = arguments
        self.__test_setup: TestContext.TestSetup | None = None
        self.__exit_stack = contextlib.ExitStack()
        self.narrowed_item_count = 0
        self.data_panel_item_count = 0

    def setup(self) -> None:
        arguments = self.__arguments
        self.__test_setup = TestContext.TestSetup()
        test_context = self.__exit_stack.enter_context(TestContext.create_memory_context())
        self.__document_controller = test_context.create_document_controller()
        document_model = self.__document_controller.document_model
        # one transaction writes the project once, rather than once for each item.
        with document_model.transaction_context():
            for item_index in range(arguments.display_items):
                data_item = DataItem.DataItem(numpy.zeros((2, 2), numpy.uint32))
                data_item.title = f"item_{item_index:06d}" + ("_an" if item_index % 2 == 0 else "")
                document_model.append_data_item(data_item)
        self.__document_controller.periodic()
        # without a data panel, the times would cover the filter but not the update of its list.
        assert self.__document_controller.find_dock_panel("data-panel"), "the document controller has no data panel"
        self.finish_widen()

    def narrow(self) -> None:
        """Narrow the filter to the display items whose titles hold NARROW_TEXT, as typing it in the search field does."""
        self.__document_controller.filter_controller.text_filter_changed(NARROW_TEXT)

    def widen(self) -> None:
        # the search field passes an empty text when it is cleared.
        self.__document_controller.filter_controller.text_filter_changed("")

    def finish_narrow(self) -> None:
        """Run the work which narrowing queues, and check that the data panel holds half of the display items."""
        self.__document_controller.periodic()
        self.narrowed_item_count = len(self.__document_controller.filtered_display_items_model.items)
        expected_item_count = (self.__arguments.display_items + 1) // 2
        assert self.narrowed_item_count == expected_item_count, f"the data panel holds {self.narrowed_item_count} items after narrowing, not {expected_item_count}"

    def finish_widen(self) -> None:
        """Run the work which widening queues, and check that the data panel holds every display item."""
        self.__document_controller.periodic()
        self.data_panel_item_count = len(self.__document_controller.filtered_display_items_model.items)
        expected_item_count = self.__arguments.display_items
        assert self.data_panel_item_count == expected_item_count, f"the data panel holds {self.data_panel_item_count} items after widening, not {expected_item_count}"

    def teardown(self) -> None:
        self.__exit_stack.close()
        self.__test_setup = None


def main() -> None:
    parser, arguments = parse_arguments()
    data_panel_filter = DataPanelFilter(arguments)
    data_panel_filter.setup()
    try:
        narrow_times, widen_times = time_rounds(arguments, [(data_panel_filter.narrow, data_panel_filter.finish_narrow), (data_panel_filter.widen, data_panel_filter.finish_widen)])
    finally:
        data_panel_filter.teardown()
    print_report(parser, arguments, [("narrow", narrow_times), ("widen", widen_times)],
                 {"narrowed_item_count": data_panel_filter.narrowed_item_count, "data_panel_item_count": data_panel_filter.data_panel_item_count})


if __name__ == "__main__":
    main()
