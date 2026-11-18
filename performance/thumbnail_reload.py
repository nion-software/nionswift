# Time reloading a project from files until all of its thumbnails are ready, each reload in a new process.
#
# The script first creates a project of images, spectra and spectrum images in a temporary directory and waits for its
# thumbnails, which is not timed. Each reload then runs in a new Python process, as when Nion Swift starts. It opens the
# profile and reads the project (load), then creates a thumbnail source for every display item, as the data panel does,
# and waits until every source has an image (first images) and no source has changed for half a second (settled, which
# doesn't include the half second). --cache cold removes the thumbnail cache files before each reload.
#
# The test user interface rasterizes every thumbnail as the same noisy image, so that compressing and storing a thumbnail
# costs what it does for a real image. The rest is the work Nion Swift does.
#
# The standard case is 30 images of 512x512, 10 spectra of 2048 channels and 5 spectrum images of 64x64x256, with the
# thumbnail cache kept between reloads:
#     python thumbnail_reload.py
import argparse
import asyncio
import cProfile
import datetime
import importlib.metadata
import json
import os
import pathlib
import platform
import pstats
import statistics
import subprocess
import sys
import tempfile
import time
import typing
import uuid

import numpy

from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Thumbnails
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Profile
from nion.ui import Bitmap
from nion.ui import DrawingContext
from nion.ui import TestUI
from nion.utils import Stream

NAME = "thumbnail_reload"

# the revision of the measured work.
REVISION = 1

# the packages whose versions the report lists.
PACKAGES = ("nionswift", "nionui", "niondata", "nionutils")

# a reload prints its result on a line which starts with this, and the script reads it back.
RESULT_PREFIX = "RESULT "


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
    parser = argparse.ArgumentParser(description="Time reloading a project from files until all of its thumbnails are ready.")
    add_common_arguments(parser)
    parser.add_argument("--reloads", type=positive_int, default=3, help="the reloads timed, each in a new process")
    parser.add_argument("--cache", choices=("warm", "cold"), default="warm", help="keep the thumbnail cache between reloads, or remove it before each")
    parser.add_argument("--images", type=int, default=30, help="the images in the project")
    parser.add_argument("--image-size", type=positive_int, default=512, help="the width and height of each image")
    parser.add_argument("--spectra", type=int, default=10, help="the spectra of 2048 channels in the project")
    parser.add_argument("--spectrum-images", type=int, default=5, help="the 64x64 spectrum images in the project")
    parser.add_argument("--spectrum-image-depth", type=positive_int, default=256, help="the channels of each spectrum image")
    parser.add_argument("--timeout", type=float, default=120.0, help="the seconds which creating the project or one reload may take")
    # a reload runs this script in a new process, with the directory of the project to reload.
    parser.add_argument("--reload-directory", type=pathlib.Path, default=None, help=argparse.SUPPRESS)
    return parser, parser.parse_args()


class NoisyUserInterface(TestUI.UserInterface):
    """A test user interface which rasterizes every thumbnail as the same noisy image."""

    def __init__(self) -> None:
        super().__init__()
        random_generator = numpy.random.default_rng(1)
        y, x = numpy.mgrid[0:256, 0:256]
        gray = numpy.clip(numpy.exp(-((x - 128) ** 2 + (y - 128) ** 2) / 2000.0) * 200 + random_generator.normal(0, 20, (256, 256)), 0, 255).astype(numpy.uint32)
        self.__image = numpy.uint32(0xFF000000) | (gray << 16) | (gray << 8) | gray

    def create_rgba_image(self, drawing_context: DrawingContext.DrawingContext, width: int, height: int) -> DrawingContext.RGBA32Type | None:
        return numpy.array(self.__image[:height, :width])


class ThumbnailWatch:
    """A thumbnail source for every display item of a document, recording when each first has an image and when any last changes."""

    def __init__(self, document_model: DocumentModel.DocumentModel) -> None:
        self.start = time.perf_counter()
        self.last_change = self.start
        self.first_image_times = dict[uuid.UUID, float]()
        self.__sources = list[Thumbnails.ThumbnailSource]()
        self.__actions = list[Stream.ValueStreamAction[Bitmap.Bitmap]]()
        ui = NoisyUserInterface()
        for display_item in document_model.display_items:
            source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(ui, display_item)

            def handle_value_changed(value: Bitmap.Bitmap | None, display_item_uuid: uuid.UUID = display_item.uuid) -> None:
                now = time.perf_counter()
                if value is not None:
                    self.first_image_times.setdefault(display_item_uuid, now - self.start)
                self.last_change = now

            self.__actions.append(Stream.ValueStreamAction(source, handle_value_changed))
            if source.value is not None:
                self.first_image_times.setdefault(display_item.uuid, 0.0)
            self.__sources.append(source)

    @property
    def display_item_count(self) -> int:
        return len(self.__sources)

    def is_settled(self) -> bool:
        """Return whether every source has an image which isn't waiting to be recomputed, and none has changed for half a second."""
        # no public property says whether a thumbnail is waiting to be recomputed.
        sources_ready = all(source.thumbnail_data is not None and not source._is_thumbnail_dirty for source in self.__sources)
        return sources_ready and time.perf_counter() - self.last_change > 0.5

    def close(self) -> None:
        self.__actions = list()
        self.__sources = list()


def open_profile(work_directory: pathlib.Path) -> tuple[asyncio.AbstractEventLoop, Profile.Profile]:
    """Return a new event loop, and the profile in work_directory, which is created if it doesn't exist."""
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    profile, _ = Profile.establish_profile(work_directory / "Profiles" / "Benchmark.nsprof", event_loop)
    assert profile
    return event_loop, profile


def run_event_loop(event_loop: asyncio.AbstractEventLoop, seconds: float) -> None:
    """Run event_loop for the given seconds."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        event_loop.run_until_complete(asyncio.sleep(0.005))


def wait_until_settled(event_loop: asyncio.AbstractEventLoop, thumbnail_watch: ThumbnailWatch, timeout: float) -> None:
    """Run event_loop until the thumbnails of thumbnail_watch settle.

    Raises TimeoutError if they don't settle within timeout seconds.
    """
    deadline = time.monotonic() + timeout
    while not thumbnail_watch.is_settled():
        if time.monotonic() > deadline:
            raise TimeoutError(f"the thumbnails didn't settle within {timeout} seconds")
        run_event_loop(event_loop, 0.02)


def close_profile(event_loop: asyncio.AbstractEventLoop, profile: Profile.Profile, project_reference: Profile.ProjectReference) -> None:
    """Unload the project, close the profile and close event_loop."""
    Thumbnails.ThumbnailManager().reset()
    project_reference.unload_project()
    run_event_loop(event_loop, 0.2)
    profile.close()
    event_loop.run_until_complete(asyncio.sleep(0.05))
    event_loop.close()


def create_project(arguments: argparse.Namespace, work_directory: pathlib.Path) -> None:
    """Create a profile and a project of images, spectra and spectrum images in work_directory, and wait for its thumbnails."""
    (work_directory / "Profiles").mkdir(parents=True)
    event_loop, profile = open_profile(work_directory)
    project_reference = profile.create_project(work_directory / "Projects", "Benchmark")
    assert project_reference
    profile.read_project(project_reference)
    document_model = project_reference.document_model
    assert document_model
    random_generator = numpy.random.default_rng(0)
    for _ in range(arguments.images):
        data = random_generator.standard_normal((arguments.image_size, arguments.image_size), dtype=numpy.float32)
        document_model.append_data_item(DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(data)))
    for _ in range(arguments.spectra):
        data = random_generator.standard_normal((2048,), dtype=numpy.float32)
        document_model.append_data_item(DataItem.new_data_item(DataAndMetadata.new_data_and_metadata(data, dimensional_calibrations=[Calibration.Calibration()])))
    for _ in range(arguments.spectrum_images):
        data = random_generator.standard_normal((64, 64, arguments.spectrum_image_depth), dtype=numpy.float32)
        xdata = DataAndMetadata.new_data_and_metadata(data, data_descriptor=DataAndMetadata.DataDescriptor(False, 2, 1))
        document_model.append_data_item(DataItem.new_data_item(xdata))
    thumbnail_watch = ThumbnailWatch(document_model)
    wait_until_settled(event_loop, thumbnail_watch, arguments.timeout)
    thumbnail_watch.close()
    close_profile(event_loop, profile, project_reference)


def reload_project(arguments: argparse.Namespace) -> None:
    """Reload the project in --reload-directory, wait for its thumbnails, and print the result."""
    profiler = cProfile.Profile() if arguments.profile else None
    if profiler:
        profiler.enable()
    start = time.perf_counter()
    event_loop, profile = open_profile(arguments.reload_directory)
    project_reference = profile.project_references[0]
    profile.read_project(project_reference)
    document_model = project_reference.document_model
    assert document_model
    load_time = time.perf_counter() - start
    thumbnail_watch = ThumbnailWatch(document_model)
    wait_until_settled(event_loop, thumbnail_watch, arguments.timeout)
    if profiler:
        profiler.disable()
        pstats.Stats(profiler).sort_stats("tottime").print_stats(15)
    display_item_count = thumbnail_watch.display_item_count
    image_count = len(thumbnail_watch.first_image_times)
    assert image_count == display_item_count, f"{image_count} of {display_item_count} thumbnail sources reported an image"
    result = {"load": load_time, "first_images": max(thumbnail_watch.first_image_times.values(), default=0.0),
              "settled": thumbnail_watch.last_change - thumbnail_watch.start, "display_item_count": display_item_count}
    thumbnail_watch.close()
    close_profile(event_loop, profile, project_reference)
    print(RESULT_PREFIX + json.dumps(result))


def main() -> None:
    parser, arguments = parse_arguments()
    if arguments.reload_directory:
        reload_project(arguments)
        return
    measurements: dict[str, list[float]] = {"load": list(), "first_images": list(), "settled": list()}
    display_item_count = 0
    with tempfile.TemporaryDirectory() as temporary_directory:
        work_directory = pathlib.Path(temporary_directory)
        create_project(arguments, work_directory)
        for _ in range(arguments.reloads):
            if arguments.cache == "cold":
                for cache_path in (work_directory / "Profiles" / "Cache").glob("*.ns*"):
                    cache_path.unlink()
            command = [sys.executable, __file__, "--reload-directory", str(work_directory), "--timeout", str(arguments.timeout)]
            if arguments.profile:
                command.append("--profile")
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            result_lines = [line for line in completed.stdout.splitlines() if line.startswith(RESULT_PREFIX)]
            if completed.returncode != 0 or not result_lines:
                sys.exit(f"A reload failed.\n{completed.stdout}{completed.stderr}")
            if arguments.profile:
                print("\n".join(line for line in completed.stdout.splitlines() if not line.startswith(RESULT_PREFIX)))
            result = json.loads(result_lines[-1][len(RESULT_PREFIX):])
            for measurement_name, times in measurements.items():
                times.append(result[measurement_name])
            display_item_count = result["display_item_count"]
    print_report(parser, arguments, list(measurements.items()), {"display_item_count": display_item_count})


if __name__ == "__main__":
    main()
