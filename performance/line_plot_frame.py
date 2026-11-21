# Time the line plot layers drawing one live frame, as during acquisition.
#
# Each frame gives every layer new data, updates the layers canvas item and repaints it into a new drawing context. This
# covers the layer calculation (rebinning or decimation), the composers and the drawing commands, but not the host's
# rasterizing of the commands, the axes, or the display item's update of its display data.
#
# The standard live acquisition case is a 2048 channel spectrum drawn as a step with a stroke and a fill into about 720
# pixels, without markers, which is the default:
#     python line_plot_frame.py
#
# --plot-kind, --marker-shape, --marker-size and --stroke-dash need a nionswift with line plot layer kinds.
import argparse
import contextlib
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

import numpy

from nion.data import DataAndMetadata
from nion.swift import LineGraphCanvasItem
from nion.swift import LinePlotCanvasItem
from nion.swift.model import DataItem
from nion.swift.model import LinePlotDisplay
from nion.swift.test import TestContext
from nion.ui import DrawingContext
from nion.utils import Color
from nion.utils import Geometry

NAME = "line_plot_frame"

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
    parser = argparse.ArgumentParser(description="Time the line plot layers drawing one live frame.")
    add_common_arguments(parser)
    parser.add_argument("--frames", type=positive_int, default=2000, help="the frames timed")
    parser.add_argument("--warm-up-frames", type=int, default=50, help="the frames drawn before timing")
    parser.add_argument("--channels", type=positive_int, default=2048, help="the channels in each spectrum")
    parser.add_argument("--plot-width", type=positive_int, default=720, help="the width of the plot in pixels")
    parser.add_argument("--plot-height", type=positive_int, default=400, help="the height of the plot in pixels")
    parser.add_argument("--layers", type=positive_int, default=1, help="the number of layers, each with its own data")
    parser.add_argument("--fill-color", default="#cdf", help="the fill color, or 'none'")
    parser.add_argument("--stroke-color", default="#1e90ff", help="the stroke color, or 'none'")
    parser.add_argument("--stroke-width", type=float, default=None, help="the stroke width; the layer's default if not given")
    parser.add_argument("--plot-kind", default=None, help="step, line, bar, stem or none")
    parser.add_argument("--marker-shape", default=None, help="none, circle, square, diamond, triangle, plus, cross or point")
    parser.add_argument("--marker-size", type=float, default=None, help="the marker size in points")
    parser.add_argument("--stroke-dash", default=None, help="solid, dashed or dotted")
    arguments = parser.parse_args()
    # an earlier nionswift has no layer kinds, and its layers don't accept these options.
    layer_parameters = inspect.signature(LinePlotDisplay.LineGraphLayer).parameters
    unsupported_options = [name for name in ("plot_kind", "marker_shape", "marker_size", "stroke_dash") if getattr(arguments, name) is not None and name not in layer_parameters]
    if unsupported_options:
        parser.error(f"this nionswift has no line plot layer kinds, so it doesn't accept {', '.join(unsupported_options)}")
    return parser, arguments


def get_color(color_text: str) -> Color.Color | None:
    """Return the color named by color_text, or None for 'none'."""
    return Color.Color(color_text) if color_text != "none" else None


class LinePlotFrame:
    """A line plot display and a layers canvas item, drawing one frame of new data at a time."""

    def __init__(self, arguments: argparse.Namespace) -> None:
        self.__arguments = arguments
        # the options which an earlier nionswift doesn't know are passed only when they are given.
        self.__layer_options = {name: value for name, value in (("plot_kind", arguments.plot_kind), ("marker_shape", arguments.marker_shape),
                                                                ("marker_size", arguments.marker_size), ("stroke_dash", arguments.stroke_dash)) if value is not None}
        self.__fill_color = get_color(arguments.fill_color)
        self.__stroke_color = get_color(arguments.stroke_color)
        # the plot is the width of the canvas less one pixel.
        self.__canvas_size = Geometry.IntSize(width=arguments.plot_width + 1, height=arguments.plot_height)
        random_generator = numpy.random.default_rng(0)
        self.__frames = [random_generator.standard_normal(arguments.channels) + 10.0 for _ in range(64)]
        self.__test_setup: TestContext.TestSetup | None = None
        self.__exit_stack = contextlib.ExitStack()
        self.command_count = 0

    def setup(self) -> None:
        arguments = self.__arguments
        self.__test_setup = TestContext.TestSetup()
        test_context = self.__exit_stack.enter_context(TestContext.create_memory_context())
        document_controller = test_context.create_document_controller()
        document_model = document_controller.document_model
        display_panel = document_controller.selected_display_panel
        assert display_panel
        data_item = DataItem.DataItem(self.__frames[0])
        document_model.append_data_item(data_item)
        display_item = document_model.get_display_item_for_data_item(data_item)
        display_panel.set_display_panel_display_item(display_item)
        display_panel.layout_immediate((arguments.plot_width + 80, arguments.plot_height + 80))
        display_canvas_item = display_panel.display_canvas_item
        assert isinstance(display_canvas_item, LinePlotCanvasItem.LinePlotCanvasItem)
        # the axes span the channels of the data; the canvas size, not the display panel, sets the plot's pixels.
        self.__axes = display_canvas_item._axes_for_testing
        self.__layers_canvas_item = LineGraphCanvasItem.LineGraphLayersCanvasItem(display_canvas_item.drawing_metrics)

    def run_frame(self, frame_index: int) -> None:
        line_graph_layers = list[LinePlotDisplay.LineGraphLayer]()
        for layer_index in range(self.__arguments.layers):
            xdata = DataAndMetadata.new_data_and_metadata(self.__frames[(frame_index + layer_index) % len(self.__frames)])
            line_graph_layers.append(LinePlotDisplay.LineGraphLayer(xdata, self.__axes, self.__fill_color, self.__stroke_color, self.__arguments.stroke_width,
                                                                    **self.__layer_options))
        self.__layers_canvas_item.update_line_graph_layers(line_graph_layers)
        drawing_context = DrawingContext.DrawingContext()
        self.__layers_canvas_item.repaint_immediate(drawing_context, self.__canvas_size)
        self.command_count = len(drawing_context.commands)

    def teardown(self) -> None:
        self.__exit_stack.close()
        self.__test_setup = None


def main() -> None:
    parser, arguments = parse_arguments()
    line_plot_frame = LinePlotFrame(arguments)
    line_plot_frame.setup()
    try:
        frame_times = time_frames(arguments, line_plot_frame.run_frame)
    finally:
        line_plot_frame.teardown()
    print_report(parser, arguments, [("frame", frame_times)], {"command_count": line_plot_frame.command_count})


if __name__ == "__main__":
    main()
