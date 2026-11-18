# Measure which steps of the histogram panel's computations hold the interpreter lock, and for how long.
#
# Standalone; needs only numpy. Run from a plain command prompt, not the nionswift console:
#     python histogram_lock_holds.py
# Each step runs in a loop on one thread while this thread sleeps 1 ms at a time. The sleeper wakes late only when it
# cannot get the interpreter lock, so its p99 and max lateness show how long the step blocks other threads.
# A step which releases the lock stays near the baseline line.
import datetime
import os
import platform
import threading
import time
import typing

import numpy
import numpy.typing

NAME = "histogram_lock_holds"

# the revision of the measured work.
REVISION = 1

# the steps measure arrays of any type.
_NDArray = numpy.typing.NDArray[typing.Any]

# a step is a call whose result is discarded.
_Step = typing.Callable[[], object]

bins = 320
low, range_ = 40.0, 120.0


def print_header() -> None:
    """Print the lines which identify a report: what it measured, when, on which machine and with which software."""
    print(f"{NAME}, revision {REVISION}")
    print(f"date      {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"machine   {platform.node()}, {platform.platform()}, {os.cpu_count()} processors")
    print(f"software  Python {platform.python_version()}, numpy {numpy.__version__}")
    print()


def lateness(work: _Step, seconds: float = 1.5) -> tuple[float, float]:
    """Return the 99th percentile and the maximum lateness in milliseconds of a 1 ms sleep, while work runs in a loop on another thread."""
    stop = threading.Event()
    delays_ns = list[int]()

    # yield the lock between calls, so the lateness measures a single call rather than the interpreter's switch interval.
    def loop() -> None:
        while not stop.is_set():
            work()
            time.sleep(0)

    thread = threading.Thread(target=loop)
    thread.start()
    previous_ns = time.perf_counter_ns()
    end_ns = previous_ns + int(seconds * 1e9)
    while previous_ns < end_ns:
        time.sleep(0.001)
        now_ns = time.perf_counter_ns()
        delays_ns.append(now_ns - previous_ns - 1_000_000)
        previous_ns = now_ns
    stop.set()
    thread.join()
    delays_ms = numpy.array(delays_ns) / 1e6
    return float(numpy.percentile(delays_ms, 99)), float(delays_ms.max())


def duration(work: _Step) -> float:
    """Return the median time in milliseconds of a call to work."""
    work()
    durations_ns = list[int]()
    for _ in range(30):
        start_ns = time.perf_counter_ns()
        work()
        durations_ns.append(time.perf_counter_ns() - start_ns)
    return float(numpy.median(durations_ns)) / 1e6


def report(name: str, work: _Step) -> None:
    """Print the duration of work and how late a sleeping thread wakes while it runs."""
    p99_ms, max_ms = lateness(work)
    print("  %-16s duration %7.3f ms   sleeper p99 %6.2f ms  max %6.2f ms" % (name, duration(work), p99_ms, max_ms), flush=True)


def histogram_steps(data: _NDArray) -> typing.Mapping[str, _Step]:
    """Return the steps of the histogram panel's histogram of data, each on the result of the step before it."""
    shifted = data - low
    scaled = shifted / range_
    multiplied = (bins + 2) * scaled
    indexes_int32 = multiplied.astype(numpy.int32)
    indexes_int64 = multiplied.astype(numpy.int64)
    clipped = numpy.clip(indexes_int32, 0, bins + 2)
    clipped_int64 = numpy.clip(indexes_int64, 0, bins + 2)
    return {
        "copy": lambda: numpy.copy(data),
        "subtract": lambda: data - low,
        "divide": lambda: shifted / range_,
        "multiply": lambda: (bins + 2) * scaled,
        "astype int32": lambda: multiplied.astype(numpy.int32),
        "astype int64": lambda: multiplied.astype(numpy.int64),
        "clip int32": lambda: numpy.clip(indexes_int32, 0, bins + 2),
        "clip int64": lambda: numpy.clip(indexes_int64, 0, bins + 2),
        "bincount int32": lambda: numpy.bincount(clipped, minlength=bins + 3),
        "bincount int64": lambda: numpy.bincount(clipped_int64, minlength=bins + 3),
    }


def statistics_steps(data: _NDArray) -> typing.Mapping[str, _Step]:
    """Return the steps of the histogram panel's statistics of data."""
    squares = numpy.square(numpy.absolute(data))
    return {
        "mean": lambda: numpy.mean(data),
        "std": lambda: numpy.std(data),
        "absolute": lambda: numpy.absolute(data),
        "square": lambda: numpy.square(data),
        "mean of squares": lambda: numpy.mean(squares),
        "amin": lambda: numpy.amin(data),
        "amax": lambda: numpy.amax(data),
    }


# each step allocates, writes, and frees a temporary, as the histogram's arithmetic does for each result.
def allocation_steps(element_count: int) -> typing.Mapping[str, _Step]:
    return {
        "ones float32": lambda: numpy.ones(element_count, dtype=numpy.float32),
        "ones int64": lambda: numpy.ones(element_count, dtype=numpy.int64),
    }


def main() -> None:
    print_header()
    frame = numpy.random.default_rng(0).normal(100.0, 20.0, 2048 * 2048).astype(numpy.float32)
    p99_ms, max_ms = lateness(lambda: time.sleep(0.01))
    print("baseline, nothing competing: sleeper p99 %.2f ms  max %.2f ms" % (p99_ms, max_ms))
    for label, data in (("histogram, 4M full frame", frame), ("histogram, 1M slice", frame[:1_000_000].copy()), ("histogram, 200k slice", frame[:200_000].copy())):
        print("== " + label)
        for name, work in histogram_steps(data).items():
            report(name, work)
    print("== statistics, 2048x2048 frame")
    for name, work in statistics_steps(frame.reshape(2048, 2048)).items():
        report(name, work)
    for label, element_count in (("allocation, 4M elements", 2048 * 2048), ("allocation, 200k elements", 200_000)):
        print("== " + label)
        for name, work in allocation_steps(element_count).items():
            report(name, work)


if __name__ == "__main__":
    main()
