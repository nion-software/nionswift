# Nion Swift Performance Measurement

Nion Swift's performance is measured with the tools in `performance/`, and with the instrumentation already in the code. This document describes how the tools measure, the techniques which separate contention for the interpreter lock from other costs, and the effects which have misled measurements. `performance/README.md` describes running the tools and recording their results.

Most figures below come from an investigation in September 2026 on two machines: a 14-core macOS machine with the simulator, and a 112-core Windows machine with a scan device and a camera producing 2048x2048 float32 frames. The figures about the scripts come from trials in November 2026 on the macOS machine.

## Tools

| Kind | Location | Measures | Runs |
|---|---|---|---|
| Script | `performance/*.py` | A fixed workload in a document which the script builds, timed per frame or per operation | From a command prompt |
| Diagnostic | `performance/diagnostics/` | A running Nion Swift during real work, such as live acquisition | From the Nion Swift console |
| Probe | `performance/probes/` | The interpreter and numpy on the machine | From a command prompt, with only numpy |

`nion.utils.Process.audit` brackets main-thread work throughout nionswift and nionui, such as `perform_data_item_updates`, `repaint_layer`, `dock_panel.<panel_id>`, computation `execute.<id>` and `cache.<action>`. `Process.audit_report` turns on collection and prints a breakdown on exit. It covers the main thread without new instrumentation. Its report looks up each event's children in time quadratic in the number of events, so it suits a window of a few seconds.

## How the scripts measure

A script uses only nionswift API which earlier commits also have, and the scripts ran unchanged against a commit from October 2026. That lets a checkout of the scripts which stays on one commit measure other branches and earlier commits, as `performance/README.md` describes for comparing branches.

A script times only the work it names. Building the document and preparing each frame happen outside the timed part, e.g. `data_panel_resort.py` queues each frame's data before timing the periodic which applies it, since a hardware source queues data from its own thread.

A script builds its document inside one transaction. Each append of a data item outside a transaction writes all of the project's properties, so its cost grows with the items already present: 2.3 ms for each of the first 500 items and 17.9 ms for each of items 2500 to 3000, on the macOS machine. A transaction writes the properties once, which brings building 5000 items from about 80 s to about 8 s.

The README's advice to record three runs rests on these trials. Two runs of the same commit differed by up to 8 %, and one run in a set was 65 % slower than the others, for a reason which wasn't found. Alternating two commits over two rounds kept the spread between the rounds of one commit within about 3 %, and showed two pairs of commits with no real difference within 3 % of each other.

## Separating interpreter lock contention from other costs

A background thread computing `numpy.histogram` of live data took about 6 ms, and about 18 ms on every third to fifth iteration. The cause was contention for the interpreter lock with the acquisition pipeline. These techniques established it, and they apply to any thread whose times vary under load.

**Wall time against the thread's own CPU time.** Timing the work with both `time.perf_counter_ns` and `time.thread_time_ns` separates time spent on a CPU from time spent waiting. Flat CPU time with rising wall time means contention or scheduling. Rising CPU time means more work, cache effects, a lower clock or a move to another core.

**A sleeping thread's lateness.** A thread which sleeps 1 ms at a time wakes late only when it can't get the interpreter lock or the process isn't scheduled. It sees long lock holds inside C extensions, which a stack sampler can't see, since the sampler needs the lock to take a sample. Its lateness had a median of 0.26 ms in an idle macOS process and 0.12 ms on the Windows machine, against a 90th percentile of 2 ms in the loaded application. Against a thread which held the lock for 12 ms every 44 ms, it found windows with a median of 12.4 ms and attributed 95 % of the worker's stall to them. `StallMonitor` in `diagnostics/histogram_jitter.py` implements it.

**The cores the process uses.** The process's CPU time over wall time is the average number of cores in use. A value near 1.0 with idle cores means the process is serialized, so its stalls come from lock ownership. A value near the core count means the machine is saturated. The application under acquisition used 2.5 to 3.0 of 14 cores, and 3.4 to 3.7 of 112 on the instrument. `time.process_time_ns` gives the process's CPU time on every platform; `resource.getrusage`, which exists only on Unix, adds page fault and context switch counts.

**The same work in a separate process.** Identical work on its own data in another process shares the CPUs, memory bandwidth and scheduler with the application, but not its interpreter lock. That copy had no slow iterations in 200, and a worst stall of 2.48 ms, while the thread in the application stalled 12.5 ms per frame. This comparison was the decisive evidence of lock contention.

**Whether an operation releases the lock.** An operation which releases the lock leaves another thread running at its idle rate. `probes/histogram_lock_holds.py` measures each numpy step of the histogram panel's calculations this way, by a sleeping thread's lateness. The simulator's Poisson noise step, 11.4 ms per frame, released the lock fully, so it competed for cores rather than for the lock, and removing it helped less than its CPU time suggested.

**Which threads run during a stall.** A thread which samples `sys._current_frames()` every 1 to 2 ms records what each thread is doing. A thread blocked in a C call has no Python frame for the call, so it shows as the line which made the call and looks busy. Reading that line's source tells a parked thread from a running one, and the result is memoized, since reading source through `linecache` on every sample caused a stall of 3.1 s. A thread which appears in every stall window with the same count is almost always parked. `ThreadSampler` in `diagnostics/histogram_jitter.py` implements it.

**Cost per item.** A counter incremented at the per-item site, read as the difference over an interval, gives the number of items, and the cost divided by it gives the cost per item. This found about 1.15 us per widget node in the periodic walk, flat across a tenfold range of panel sizes, which showed the walk was linear in the number of nodes.

**Timing at the root.** Timing the outermost call of a recursive or repeated operation takes two clock readings per call where timing each step takes thousands, and it gives the cost per call. Keying the totals by name, such as each panel's identifier in `Panel.periodic`, gives a breakdown of the live application which a benchmark that calls a function repeatedly can't give.

**Reading counters from a background thread.** A thread which takes two readings of accumulating counters, sleeps between them and logs the difference measures a real interval. Sleeping on the main thread blocks the work being measured, and two console commands typed one after another measure an interval near zero. `logging` is safe from any thread; writing to a widget from a thread doesn't work, and in the console the text appears at the prompt as though typed.

**The clock's real resolution.** `time.get_clock_info().resolution` reports 100 ns on Windows, while the thread clock advances every 15.6 ms. Measuring the smallest increment over several ticks gives its real step. `measure_thread_time_granularity` in `diagnostics/histogram_jitter.py` does this.

**Calibrating one machine against another.** Timing a cheap reference operation per element on both machines, such as `ndarray.sum`, gives a ratio for carrying a measurement from one machine to the other. The Windows machine ran memory-bound numpy work 4 to 5 times slower per element than the macOS machine, 0.49 ns against 0.11 ns. A measurement compared across the machines without this ratio was wrongly judged irrelevant: 84 ns on macOS against 1.2 us on Windows.

## Effects which have misled measurements

**Coarse clocks on Windows.** Thread and process CPU time advance in steps of 15.6 ms on Windows, so CPU time per iteration and any stall derived from it are meaningless there. CPU time over a phase of several seconds is sound. `time.perf_counter_ns` uses the high resolution counter and isn't affected.

**A share of the main thread.** The application's event loop ticks as fast as it can, so making `periodic` cheaper raises the tick rate rather than lowering its share of the main thread. The rate rose from 512 to 834 ticks a second while the share stayed near 12.5 %, though the cost per call fell 38 %. The cost per call is the comparable figure.

**Repeated calls.** A benchmark which calls a function many times in a row doesn't reproduce the live path, since the calls after the first find nothing pending. A benchmark of the panel walk reported a 63 % improvement where the live application improved 38 %.

**Stack sampling.** Sampling adds to what it measures: about 20 points of apparent stall on long phases, 39 % against 17 % without it. `histogram_jitter.start` takes `sample_threads=False` to measure without sampling, as a control for its effect.

**Attribution at the end of a stall window.** The monitor records which threads run when it gets the lock back, so the thread whose release ended the window is the one most likely to be sampled. Threads which release the lock often are over-represented, and this misled three conclusions in the investigation: `os.fsync` in `AtomicFileWriter`, `create_rgba_image`, and the histogram panel's rise after it was made 25 % cheaper. Whether a function can hold the lock at all, measured by a probe, settles whether a prominent stack is a cause.

**Parked threads.** A thread waiting in `time.sleep`, a device library or a socket read leaves no Python frame for the call and appears busy. In one run such threads topped 961 of 961 stall windows.

**Large allocations on Windows.** On Windows, a freed allocation of 1 MB or more goes back to the operating system, so a numpy temporary of that size is faulted in again on every use, at about 0.4 ms per MB. Work split into pieces whose temporaries stay under 1 MB gains more there than on macOS. `probes/numpy_allocation_probe.py` measures the threshold and the cost.

**An idle large machine.** On the 112-core instrument, identical Python cost about twice as much per operation when the machine was idle as under acquisition load, probably because an idle machine runs at a lower clock. Comparisons there hold within one state of activity, and an idle baseline there isn't a clean reference.

**What held up.** An idle baseline with the workload stopped had no stall windows and 5 % stall, against 51 % under acquisition, which showed the contention came from acquisition. Each instrument was checked against a known cause before it was trusted with an unknown one. Three identical runs differed by 21 %, so a difference under about 20 % needed repetition. A yes-or-no check, such as whether a stack has left the profile, held up through variation which hid a change of 2 % in timing.

## Decisions

The tools are standalone scripts using only the standard library, numpy and nionswift, since the project prefers the standard library to another dependency. Trials of asv and pytest-benchmark against the data panel script found neither fits a workload which builds a large document once and then times many frames: asv runs a benchmark's setup before each sample, which built the 5000-item document 17 or more times for one benchmark, and pytest-benchmark's comparison lists alternating runs one by one, without combining the runs of each commit.

A script prints a report and rows for a table, since its results are recorded in a wiki or by the test department, which compares them from release to release.
