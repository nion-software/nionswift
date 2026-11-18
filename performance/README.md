# Performance Scripts

Each script at the top of this directory times one part of Nion Swift, using the nionswift which is installed, and prints
a report and one table row for each of its measurements. The rows are meant for a table in a wiki or a spreadsheet, so
that the results of one machine can be followed from release to release. The subdirectories hold diagnostics, which
measure a running Nion Swift, and probes, which measure the platform it runs on; the last two sections describe them.

| Script | Measures |
|---|---|
| `data_panel_resort.py` | The main thread's handling of one live frame while the data panel holds 5000 display items |
| `data_panel_filter.py` | A text filter change in the data panel, narrowing and widening, while it holds 20000 display items |
| `line_plot_frame.py` | The line plot layers drawing one frame of a 2048 channel spectrum |
| `delete_undo.py` | Creating 1000 data items, then deleting 100 of them and undoing the deletion, in memory or in files |
| `histogram_frame.py` | The histogram panel's histogram and statistics of one 2048x2048 frame |
| `histogram_contention.py` | How long the histogram panel's calculations of one 2048x2048 frame block another thread |
| `display_data_range.py` | The display's data range of one 2048x2048 frame, and how long it blocks another thread |
| `thumbnail_reload.py` | Reloading a project from files in a new process until all of its thumbnails are ready |

The comment at the top of each script describes its work and its standard case in more detail.

## Running

Run a script with the Python environment which has Nion Swift installed, on a machine with nothing else running:

    python data_panel_resort.py

The defaults are the standard case, and `--help` lists the options. Every script accepts `--label`, which adds a label
such as a branch name to the report and the rows, and `--profile`, which prints the functions taking the most time. The
profiler inflates the times, so a profiled run prints no rows.

## Recording

A run prints a report, then a row for each measurement:

    data_panel_resort, revision 1
    date      2026-11-18 10:42
    machine   example-host, macOS-26.6.2-arm64-arm-64bit-Mach-O, 14 processors
    software  Python 3.14.9, numpy 2.5.4, nionswift 16.18.1, nionui 11.1.0, niondata 15.10.0, nionutils 4.14.3
    options   defaults
    details   data_panel_item_count 5002
    frame     median 1.024 ms  p90 1.060 ms  iqr 0.025 ms  (500 samples)

    | 2026-11-18 10:42 | example-host | nionswift 16.18.1 |  | defaults | frame | 500 | 1.024 | 1.060 | 0.025 |

The rows fit a table with this header, one table for each script:

    | Date | Machine | Software | Label | Options | Measurement | Samples | Median ms | P90 ms | IQR ms |
    |---|---|---|---|---|---|---|---|---|---|

Options lists only the options which differ from their defaults, so a run of the standard case shows `defaults`. The
details line holds counts which confirm that the run measured what it intends; they aren't part of the row.

Run each script three times and record all three rows. Whole runs on one machine differ by a few percent, and one run in
a set can differ by much more, so a single row can mislead.

## Comparing

Compare rows only when they come from the same machine, script revision, options and measurement. A change shows when all
three runs move together, beyond the spread of the runs before it.

A script raises its revision when the work it measures changes, including a change to the default of an option. Rows of
different revisions measure different work.

The statistics of each measurement are:

- median, the median of its samples;
- p90, the sample at 90 % of the sorted samples, counting from the fastest;
- iqr, the interquartile range, from `statistics.quantiles` with its default method, or zero for a single sample.

## Comparing branches

To compare two branches of nionswift, run the scripts from a separate checkout which stays on one commit, such as a
worktree made with `git worktree add <scripts checkout> master`, and switch the installed nionswift between the branches.
Each branch is then measured by the same scripts, including a branch made before a script existed. Alternate the
branches for three rounds, so that drift over time affects both alike, and label each run with its branch:

    for round in 1 2 3; do
        git -C <installed nionswift> checkout -q master && python <scripts checkout>/performance/data_panel_resort.py --label master
        git -C <installed nionswift> checkout -q <branch> && python <scripts checkout>/performance/data_panel_resort.py --label <branch>
    done

The scripts use only nionswift API which earlier commits also have, so that they measure earlier commits too. A script
stops with a message when it is given an option which an earlier nionswift lacks, such as the layer kinds of
`line_plot_frame.py`.

## Diagnostics

A diagnostic in `diagnostics/` measures a running Nion Swift during real work, such as live acquisition, rather than a
fixed workload, so its results depend on the instrument and its settings. It prints a detailed report and no table rows.

| Diagnostic | Measures |
|---|---|
| `diagnostics/histogram_jitter.py` | How often and for how long a background histogram loop stalls, and which threads run during the stalls |

The docstring at the top of the diagnostic says how to run it from the Nion Swift console. Its report starts with the
same lines which identify a script's report: the name and revision, the date, the machine and the software.

## Probes

A probe in `probes/` measures the platform which Nion Swift runs on, such as the interpreter and numpy, and doesn't use
Nion Swift. It needs only numpy, and runs from a command prompt:

    python probes/numpy_allocation_probe.py

| Probe | Measures |
|---|---|
| `probes/histogram_lock_holds.py` | How long each numpy step of the histogram panel's calculations blocks other threads |
| `probes/numpy_allocation_probe.py` | The cost of allocating numpy arrays of increasing size, and of a new result array against a reused one |

A probe prints the identifying lines and then tables of its own, with no rows for the wiki. Its reports are most useful
compared across machines, or across versions of Python and numpy on one machine.
