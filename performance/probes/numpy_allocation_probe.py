# Probe whether numpy temporaries above some size are served with fresh pages from the OS on every allocation.
#
# Standalone; needs only numpy. Run from a plain command prompt, not the nionswift console:
#     python numpy_allocation_probe.py
# Part 1 allocates, writes, and frees an array of each size; a jump in the time per MB marks the size above which every
# allocation is page faulted afresh. Part 2 compares the same operation writing to a new array and to a reused array.
import datetime
import os
import platform
import time
import typing

import numpy

NAME = "numpy_allocation_probe"

# the revision of the measured work.
REVISION = 1


def print_header() -> None:
    """Print the lines which identify a report: what it measured, when, on which machine and with which software."""
    print(f"{NAME}, revision {REVISION}")
    print(f"date      {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"machine   {platform.node()}, {platform.platform()}, {os.cpu_count()} processors")
    print(f"software  Python {platform.python_version()}, numpy {numpy.__version__}")
    print()


def median_ms(work: typing.Callable[[], object], repeats: int = 40) -> float:
    """Return the median time in milliseconds of a call to work, after one call which isn't timed."""
    work()
    durations_ns = list[int]()
    for _ in range(repeats):
        start_ns = time.perf_counter_ns()
        work()
        durations_ns.append(time.perf_counter_ns() - start_ns)
    return float(numpy.median(durations_ns)) / 1e6


def main() -> None:
    print_header()
    print("== allocate, write, free")
    for kilobytes in (256, 512, 768, 960, 1000, 1024, 1100, 1536, 2048, 4096, 16384, 32768):
        byte_count = kilobytes * 1024
        ms = median_ms(lambda: numpy.ones(byte_count, dtype=numpy.uint8))
        print("  %6d KB  %8.3f ms  %7.3f ms per MB" % (kilobytes, ms, ms / (byte_count / 1048576)), flush=True)
    print("== 2048x2048 float32: new result versus reused result")
    data = numpy.random.default_rng(0).normal(100.0, 20.0, 2048 * 2048).astype(numpy.float32)
    reused = numpy.empty_like(data)
    reused_int64 = numpy.empty(data.shape, dtype=numpy.int64)
    comparisons = (
        ("copy", lambda: numpy.copy(data), lambda: numpy.copyto(reused, data)),
        ("subtract", lambda: numpy.subtract(data, 40.0), lambda: numpy.subtract(data, 40.0, out=reused)),
        ("square", lambda: numpy.square(data), lambda: numpy.square(data, out=reused)),
        ("absolute", lambda: numpy.absolute(data), lambda: numpy.absolute(data, out=reused)),
        ("astype int64", lambda: data.astype(numpy.int64), lambda: numpy.copyto(reused_int64, data, casting="unsafe")),
    )
    for name, new_result, reused_result in comparisons:
        print("  %-13s new %7.3f ms   reused %7.3f ms" % (name, median_ms(new_result), median_ms(reused_result)), flush=True)
    print("== reference, no result array")
    print("  %-13s     %7.3f ms" % ("sum", median_ms(lambda: data.sum())))


if __name__ == "__main__":
    main()
