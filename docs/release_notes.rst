:orphan:

.. _release-notes:

Release Notes
=============

Note: In order to release bug fixes in a timely manner, we try to publish Nion Swift releases on a regular basis.
Sometimes, though, as a consequence, bug fix releases will also include new features that are only partial steps
towards their final form. Instead of disabling these new partial features in bug fix releases, we choose to include
them for evaluation and feedback. If you encounter an issue or have feedback about these types of new features,
please contact us or `file issues
<https://github.com/nion-software/nionswift/issues>`_.

Version 16.11.0 (2024-06-13)
----------------------------
* Computed data items titles update automatically when changing source title. (`#32 <https://github.com/nion-software/nionswift/issues/32>`_)
* Improve drawing performance and fix minor inconsistencies.
* Improve startup performance by fixing issue that invalidated thumbnails on exit.
* Fix issue where exporting could overwrite files with same metadata. (`#586 <https://github.com/nion-software/nionswift/issues/586>`_)
* Add mechanism to include additional display calibrations (e.g., e/eV/s). (`#230 <https://github.com/nion-software/nionswift/issues/230>`_ `#1019 <https://github.com/nion-software/nionswift/issues/1019>`_)
* Improve handling of number precision for inspector calibrations and display limits. (`#253 <https://github.com/nion-software/nionswift/issues/253>`_)
* Ask user for SVG size before exporting (assumes 96 DPI).
* Improve ordering of fields in session dialogs to have most frequently used fields at top.
* Fix issue when displaying line plot of integer-valued 1D data item using log scale. (`#1045 <https://github.com/nion-software/nionswift/issues/1045>`_)
* Importing valid data always succeeds by assign new identifiers, instead of silently skipping possible duplicates.
* Sort recent workspaces in menu by creation date (if available). Older workspaces copy modified date to creation date.
* Add support for independent dimensional and intensity calibrations. (`#300 <https://github.com/nion-software/nionswift/issues/300>`_)
* Add menu items for flip horizontal/vertical and rotate right/left. (`#919 <https://github.com/nion-software/nionswift/issues/919>`_)
* Fix issue when removing workspace to select next most recent workspace. (`#1002 <https://github.com/nion-software/nionswift/issues/1002>`_)
* Fix issue when splitting display panels with multiple panels selected. (`#1001 <https://github.com/nion-software/nionswift/issues/1001>`_)
* Make filtering work on modified date text and session metadata text when filtering data items in data panel. (`#922 <https://github.com/nion-software/nionswift/issues/922>`_ `#327 <https://github.com/nion-software/nionswift/issues/327>`_)
* Fix issue with data panel spontaneously switching display after processing when using data panel text filter. (`#1001 <https://github.com/nion-software/nionswift/issues/1003>`_)
* Fix issues with line plot when dimensional calibrations are invalid. Fall back to pixel calibration. (`#998 <https://github.com/nion-software/nionswift/issues/998>`_)

Version 16.10.0 (2024-01-03)
----------------------------
* Fix crash when screen properties change. Also respond better to DPI changes. (`#995 <https://github.com/nion-software/nionswift/issues/995>`_)
* Add scroll bar to activity panel to prevent it growing beyond its available height. (`#992 <https://github.com/nion-software/nionswift/issues/992>`_)
* Hovering over items in grid browser shows info about the item. (`#5 <https://github.com/nion-software/nionswift/issues/5>`_)
* Hovering over title bar shows info about the displayed item.
* Add a Radial Power Spectrum menu item to Fourier processing sub-menu. (`#989 <https://github.com/nion-software/nionswift/issues/989>`_)
* Add a radial profile menu item to Fourier processing sub-menu. (`#988 <https://github.com/nion-software/nionswift/issues/988>`_)
* Expand About Box to include release notes and recent changes.
* Performance improvements to avoid metadata copying.
* Commands work after deleting multiple display items. (`#700 <https://github.com/nion-software/nionswift/issues/700>`_)
* Fall back to uncalibrated coordinates for angle/length if units don't match on datum dimensions. (`#980 <https://github.com/nion-software/nionswift/issues/980>`_)
* Data panel dragging works on first click now. (`#979 <https://github.com/nion-software/nionswift/issues/979>`_)
* Add the option to display the phase of a complex array. (`#981 <https://github.com/nion-software/nionswift/issues/981>`_) by `luc-j-bourhis <https://github.com/luc-j-bourhis>`_
* Mapped/unmapped processing (when available) now works in unmapped case. (`#985 <https://github.com/nion-software/nionswift/issues/985>`_)
* Fix several cases where index sliders were incorrect. (`#759 <https://github.com/nion-software/nionswift/issues/759>`_, `#987 <https://github.com/nion-software/nionswift/issues/987>`_)

Version 16.9.1 (2023-10-23)
----------------------------
* Minor performance improvement when loading projects.
* Minor fixes for Python 3.12 and mypy typing compatibility.
* Add mechanism for packages to run startup code for Console windows.
* Improve shutdown of Console to garbage collect local variables declared in console.

Version 16.9.0 (2023-08-17)
---------------------------
* Internal changes for stability and performance.
* Add Python 3.11 support. Drop 3.8.
* `#971 <https://github.com/nion-software/nionswift/issues/971>`_ Apply mapped operations to all navigable data instead of just collections.
* `#968 <https://github.com/nion-software/nionswift/issues/968>`_ Fix issue where scale marker could be temporarily incorrect.
* `#970 <https://github.com/nion-software/nionswift/issues/970>`_ Fix issue with GaussianWindow on non-square data.
* `#939 <https://github.com/nion-software/nionswift/issues/939>`_ View to interval on line plot handles special case of no-interval same as double clicking axis.
* `#105 <https://github.com/nion-software/nionswift/issues/105>`_ Add graphic position/shape lock and move to center button to inspector.
* `#959 <https://github.com/nion-software/nionswift/issues/959>`_ Data panel displays collection filter if used.
* Improve performance, eliminate flickering in metadata panel and activity panel.
* `#544 <https://github.com/nion-software/nionswift/issues/544>`_ Improve display pipeline performance.
* `#954 <https://github.com/nion-software/nionswift/issues/954>`_ Add session edit tab to title edit pop-up dialog. Also add action, menu item, key overload (Ctrl+T).
* `#916 <https://github.com/nion-software/nionswift/issues/916>`_ Changed process title format to put processing operation after base title stem.
* `#900 <https://github.com/nion-software/nionswift/issues/900>`_ Implement dynamic titles for processed data items. Changing base title updates dependents.
* `#944 <https://github.com/nion-software/nionswift/issues/944>`_ Fix line plot drawing when plot has drawn segments separated by nans.
* `#952 <https://github.com/nion-software/nionswift/issues/952>`_ Order project lists by load-ability then date.
* `#951 <https://github.com/nion-software/nionswift/issues/951>`_ Show missing projects as 'missing' rather than 'unreadable' in projects lists.
* `#950 <https://github.com/nion-software/nionswift/issues/950>`_ Include last-used date in projects lists.
* `#949 <https://github.com/nion-software/nionswift/issues/949>`_ Make choose project dialog resizable.
* `#946 <https://github.com/nion-software/nionswift/issues/946>`_ Ensure computations with multiple results reload properly.
* `#930 <https://github.com/nion-software/nionswift/issues/930>`_ Fix error when activity panel would grow too large during dragging graphics.
* Add project items dialog for debugging.
* Improve error handling when computation with error is deleted during execute phase.
* Show ' (Live)' suffix when data is live or dependent on live data.
* Add ability to launch interactive script from API ('window.run_interactive_script').
* Add minor project cleanup/maintenance at startup.
* Fix several numpy warnings.
* Add support for run-script docstring (help text) in Run Script dialog.
* Improve functionality of recent project list when missing projects.
* Add 1d rebin computation.
* Update Facade HardwareSource to match new capabilities in instrumentation-kit.

Version 0.16.8 (2022-12-06)
---------------------------
* `#904 <https://github.com/nion-software/nionswift/issues/904>`_ Session data is once again persistent between restarts.

Version 0.16.7 (2022-11-04)
---------------------------
* `#897 <https://github.com/nion-software/nionswift/issues/897>`_ Canceling script no longer prints stack trace (but does give one line cancel message).
* `#893 <https://github.com/nion-software/nionswift/issues/893>`_ Fix snapshot creating multiple copies.

Version 0.16.6 (2022-10-03)
---------------------------
* `#891 <https://github.com/nion-software/nionswift/issues/891>`_ Fix issue in handling edited text in utility dialogs.
* Minor changes to support plug-ins.

Version 0.16.5 (2022-09-15)
---------------------------
* `#887 <https://github.com/nion-software/nionswift/issues/887>`_ Fix issue with grid browser not drawing in some cases.
* `#619 <https://github.com/nion-software/nionswift/issues/619>`_, `#885 <https://github.com/nion-software/nionswift/issues/885>`_, `#886 <https://github.com/nion-software/nionswift/issues/886>`_ Fix issues switching from acquisition controller panel to regular display.
* `#657 <https://github.com/nion-software/nionswift/issues/657>`_ Make secondary layers use stroke-only rather than fill on composite line plots. Draw fills and then strokes.
* `#884 <https://github.com/nion-software/nionswift/issues/884>`_ Fix copy/paste regression for graphics.
* `#679 <https://github.com/nion-software/nionswift/issues/679>`_ Use separate thumbnail cache for each project and purge when unused. Saves disk space.
* `#345 <https://github.com/nion-software/nionswift/issues/345>`_ Create new display item when initially creating composite line plot (drag/drop or copy/paste).
* `#883 <https://github.com/nion-software/nionswift/issues/883>`_ Fix issue where composite line plot thumbnails would not update.
* `#866 <https://github.com/nion-software/nionswift/issues/866>`_ Handle zoom-to-interval using Enter key on composite line plots.
* `#577 <https://github.com/nion-software/nionswift/issues/577>`_ Show error state of computation in computation editor.
* `#878 <https://github.com/nion-software/nionswift/issues/878>`_ Handle renamed project index/data folder.

Version 0.16.4 (2022-07-26)
---------------------------
* `#640 <https://github.com/nion-software/nionswift/issues/640>`_ Improve file dialogs handling of default directory.
* Make line plot smarter about choosing new colors.
* `#861 <https://github.com/nion-software/nionswift/issues/861>`_ Fix view-to-intervals with intervals entirely outside data bounds.
* `#513 <https://github.com/nion-software/nionswift/issues/513>`_ Fix view to intervals to show selected area when interval is outside of data bounds.
* `#495 <https://github.com/nion-software/nionswift/issues/495>`_ Add option to put legend outside of line plot.
* `#390 <https://github.com/nion-software/nionswift/issues/390>`_ Allow resizing intervals from center using option/alt key.
* `#36 <https://github.com/nion-software/nionswift/issues/36>`_ Add +/- keyboard shortcuts for line profile width (must be selected).
* `#855 <https://github.com/nion-software/nionswift/issues/855>`_ Fix regression where line profile with width was not drawn correction.
* `#852 <https://github.com/nion-software/nionswift/issues/852>`_ Additional performance improvements in histogram.
* `#831 <https://github.com/nion-software/nionswift/issues/831>`_ Performance improvements during index slider drags and movie player.
* `#851 <https://github.com/nion-software/nionswift/issues/851>`_ Sort workspace menu by modified date and include date in menu.
* Import/export WebP file format.
* Performance improvements in FFT.
* Performance improvements in startup time with large libraries.

Version 0.16.3 (2022-05-28)
---------------------------
* `#842 <https://github.com/nion-software/nionswift/issues/842>`_ Partial fix to allow dropping of nx1 data on a composite line plot display.
* `#821 <https://github.com/nion-software/nionswift/issues/821>`_ Fix handling of invalid contrast/gamma edit field values.
* `#75 <https://github.com/nion-software/nionswift/issues/75>`_ Add menu item to snapshot display rather than entire data. This is now default Ctrl+S behavior.
* `#819 <https://github.com/nion-software/nionswift/issues/819>`_ Improve handling of multiple input selection for computations such as Make RGB.
* `#74 <https://github.com/nion-software/nionswift/issues/74>`_ Add play/pause button to sequence slider for movie-like playback. Experimental.
* `#813 <https://github.com/nion-software/nionswift/issues/813>`_ Assigning to xdata in API accepts anything convertible to xdata such as a numpy array.
* Performance/reliability improvements with the live histogram updates.
* Improve Python 3.10 compatibility on Windows.
* Improve reporting of file loading errors in startup log.
* Improve Quickstart guide in documentation.

New contributors: gosselind1, ejensen28

Version 0.16.2 (2022-02-18)
---------------------------
* `#796 <https://github.com/nion-software/nionswift/issues/796>`_ Using auto display limits on RGB image no longer corrupts data item.
* `#795 <https://github.com/nion-software/nionswift/issues/795>`_ Exporting to JPEG works again.
* `#792 <https://github.com/nion-software/nionswift/issues/792>`_ Rectangle mask now draws properly even when out of bounds.
* `#623 <https://github.com/nion-software/nionswift/issues/623>`_ Line and point graphics now generate masks when included.
* `#789 <https://github.com/nion-software/nionswift/issues/789>`_ Handle cursor properly when deleting display item under cursor.
* `#779 <https://github.com/nion-software/nionswift/issues/779>`_ Mappable processing operations now complete when mapped and no graphic.
* Improved (slightly) documentation.

Version 0.16.1 (2021-12-13)
---------------------------
* `#772 <https://github.com/nion-software/nionswift/issues/772>`_ Fix issue deselecting empty display panels.
* `#770 <https://github.com/nion-software/nionswift/issues/770>`_ Fix issue where some HDF5 files may not load properly.
* `#765 <https://github.com/nion-software/nionswift/issues/765>`_ Add support for Python 3.10.

Version 0.16.0 (2021-11-12)
---------------------------
The highlights of this release are improved performance, reliability, and internal Python code maintainability.

This 0.16.0 release is file compatible with the 0.15.x release and switching between the two versions is supported.

Requires Python 3.8 or Python 3.9.

* `#758 <https://github.com/nion-software/nionswift/issues/758>`_ Composite line plots can now display any data that can be reduced to 1D data.
* `#753 <https://github.com/nion-software/nionswift/issues/753>`_ Improved performance of HDF5 backed files by not blocking via cursor updates.
* `#741 <https://github.com/nion-software/nionswift/issues/741>`_ Fix issue deselecting secondary display panels when clicking on primary.
* `#731 <https://github.com/nion-software/nionswift/issues/731>`_ Dropped support for Python 3.7.
* `#724 <https://github.com/nion-software/nionswift/issues/724>`_ Moved hardware source into instrumentation kit.
* `#717 <https://github.com/nion-software/nionswift/issues/717>`_ Fix issues with scale marker not updating when calibration changed.
* `#713 <https://github.com/nion-software/nionswift/issues/713>`_ Fix issues with HDF5 backed file not displaying as line plot.
* `#712 <https://github.com/nion-software/nionswift/issues/712>`_ Improve look and functionality of toolbar.
* `#705 <https://github.com/nion-software/nionswift/issues/705>`_ Allow line plot stroke width to be edited in inspector.
* `#699 <https://github.com/nion-software/nionswift/issues/699>`_ Improve reliability of data file writes.
* `#681 <https://github.com/nion-software/nionswift/issues/681>`_ Fix line plot display jitter when dragging axes.
* `#323 <https://github.com/nion-software/nionswift/issues/323>`_ Provide sequence and collection controls directly in display panel.
* `#155 <https://github.com/nion-software/nionswift/issues/155>`_ Store preferences in file rather than registry. File printed at startup. Easier backup.
* `#132 <https://github.com/nion-software/nionswift/issues/132>`_ Add activity panel (beta) and notification panel (beta, lightly used so far).
* Speed up project loading by simplifying code and avoiding rewrites upon loading.
* Many improvements to internal Python code (strict typing, cleanup).

Version 0.15.7 (2021-05-27)
---------------------------
* `#475 <https://github.com/nion-software/nionswift/issues/475>`_ Fix issue with font sizes when changing screen resolution without rebooting.
* `#211 <https://github.com/nion-software/nionswift/issues/211>`_ Fix issue shifting and zooming raster displays during acquisition.
* `#236 <https://github.com/nion-software/nionswift/issues/236>`_ Console dialog gets focus immediately after opening.
* `#257 <https://github.com/nion-software/nionswift/issues/257>`_ Fix focus issues after processing produces a new item.
* `#151 <https://github.com/nion-software/nionswift/issues/151>`_ Calculate line angles using calibrated coordinates.
* `#471 <https://github.com/nion-software/nionswift/issues/471>`_, `#692 <https://github.com/nion-software/nionswift/issues/692>`_ Improve handling of corrupt projects and logging.
* `#293 <https://github.com/nion-software/nionswift/issues/293>`_ Change rotation knob on rectangles and ellipses to be easier to see, at top.
* `#148 <https://github.com/nion-software/nionswift/issues/148>`_, `#686 <https://github.com/nion-software/nionswift/issues/686>`_, `#688 <https://github.com/nion-software/nionswift/issues/688>`_, `#690 <https://github.com/nion-software/nionswift/issues/690>`_ Improvements to mask handling.
* `#683 <https://github.com/nion-software/nionswift/issues/683>`_ Fix issue undoing and saving workspaces.
* Add preliminary controls to toolbar for adjusting workspace (splits, close, delete, clear, etc.).
* `#101 <https://github.com/nion-software/nionswift/issues/101>`_ Add preliminary key shortcuts for pointer (e), hand (h), line (n), and rectangle (c).
* `#644 <https://github.com/nion-software/nionswift/issues/644>`_ Fix issue when dragging line plot intervals outside of data domain.
* `#643 <https://github.com/nion-software/nionswift/issues/643>`_ Improve line plot stability when calibration changes.
* `#402 <https://github.com/nion-software/nionswift/issues/402>`_ Fixed Reveal right-click menu item to work again.
* Clean up utility windows (do not display unneeded menus).

Version 0.15.6 (2021-04-12)
---------------------------
* (2021-04-12) Fix export issue resulting in incomplete or corrupt data after export of fresh scan data.
* (2021-04-09) Fix performance issue when data item created during acquisition.
* (2021-03-27) Fix logo display in about box on Linux.
* (2021-03-25) Improve sorting in run scripts dialog.


Version 0.15.5 (2021-03-12)
---------------------------
* (2021-03-05) Add menu item to select sibling display panels, useful for clearing/closing.
* (2021-03-04) Restructure context menu to only show options available for selected display panel(s).
* (2021-03-04) Add menu items for common n x m layouts, applied to a selected display panel.
* (2021-03-02) Add ability to select secondary display panels using Shift or Control/Command key.
* (2021-03-02) Update various processing menu items to utilize multiple selected display panels.
* (2021-03-02) Right click Export using data panel now exports all selected data panel items.
* (2021-02-22) Generalize align sequences to operate on collections too.
* (2021-02-22) Fix issue with new generate data dialog when using sequences.
* (2021-02-22) Add ability to bypass opening default project by holding Shift at launch.
* (2021-02-22) Change window title to display current project and workspace.
* (2021-02-21) Improve performance on composite line plots by minimizing thumbnail recalculation.
* (2021-02-13) Improve handling of line plot data when removing a display layer.
* (2021-02-13) Improve handling of line plot displaying 2D with 16+ rows.
* (2021-02-03) Improve About Box to show more installation info.

Version 0.15.4 (2021-02-02)
---------------------------
* (2021-01-22) Add dialog to generate data, useful for testing and experiments.
* (2021-01-20) Allow computations to be deleted directly from computation editor.
* (2021-01-18) Allow computation editor to show dependent computations in addition to source computations.
* (2020-12-28) Minor improvements to computation editor panel.
* (2020-12-23) Add color wells for editing line plot layer colors in inspector.
* (2020-12-20) Improve line plot layers to be more robust during adding/removing/undo.

Version 0.15.3 (2020-12-10)
---------------------------
* (2020-12-09) Fix regression (0.15.2) of drawing composite line plot layers in reverse order.
* (2020-12-07) Fix issue with export and other items crashing after context menu.
* (2020-12-03) Change collections of 1D data to show single line plot with navigation in inspector.
* (2020-11-26) Change console script r-var's to refer to display not data item.
* (2020-11-24) Improve menu and context menu layout (Display, Graphics, Workspace).

Version 0.15.2 (2020-11-13)
---------------------------
* (2020-11-13) Add documentation about upgrading. Also other minor documentation changes.
* (2020-11-12) Add progress bar when finding existing projects upon first launch.
* (2020-11-06) Split View menu into Display and Workspace menus. Add Graphics menu.
* (2020-11-06) Ensure all context menu items are also in main menus.
* (2020-10-08) Fix issue with reading metadata from scripts.
* (2020-10-08) Fix issue with images updating during partial acquisition.
* (2020-10-06) Fix issue dragging spot graphic.
* (2020-10-06) Partially fix performance when dragging graphics on complex data.
* (2020-09-23) Add RGB processing commands (beta). Fix related RGB issues.
* (2020-09-21) Fix issue where line plot would sometimes fail to update properly.
* (2020-09-18) Introduce brightness/contrast/gamma/log controls (beta).
* (2020-09-15) Fixed issue with line plot on sequences/collections of images.

Version 0.15.1 (2020-09-03)
---------------------------
* (2020-09-03) Clean up launch workflow when no project already open.

Version 0.15.0 (2020-08-31)
---------------------------
The highlights of this release are improved display performance, improved reliability,
improved line plot displays, and an improved computation inspector.

Requires Python 3.7 or later.

The new computation inspector is accessible with Cmd/Ctrl+E. This key previously opened the
data item script editor. The data item script editor is now available with Cmd/Ctrl+Shift+E.

* (2020-08-27) Improve HDF5 performance.
* (2020-08-17) Add API function to create graphic from dict description.
* (2020-08-10) Add new computation inspector (Cmd/Ctrl+E).
* (2020-07-30) Add processing menu item to rebin an image to a specified size.
* (2020-06-10) Improve internal metadata handling during acquisition.
* (2020-05-18) Improve tick drawing on line plots.  Also scientific notation.
* (2020-05-18) Improve auto-scaling of log line plots.
* (2020-05-13) Add complex display type chooser for images and line plots.
* (2020-05-12) Add support for exporting composite line plots to csv. Fixes #209.
* (2020-05-12) Improve font handling/scaling on Windows.
* (2020-05-11) Add context menu to open folder location of Scripts.
* (2020-05-08) Ensure inspector shows calibrated units for composite line plots. Fixes #406.
* (2020-05-08) Use thread pools to reduce graphics resource usage.
* (2020-05-05) Force drag interval graphics when control is held down. Fixes #389.
* (2020-04-27) Use cursor style to indicate drag areas in line plot. Improves #37.
* (2020-04-24) Ensure negative scale in line plots is handled properly. Fixes #130.
* (2020-03-26) Add support for running 'pick' on sequences of spectrum images.
* (2020-04-03) Fix issues that might prevent projects from loading.
* (2020-04-01) Fix problems handling input in scripts dialog.
* (2020-03-24) Optimize several aspects of data panel.
* (2020-03-21) Update each display panel in its own thread for decreased latency.
* (2020-03-07) Improve performance when dragging display intervals on line profile.
* (2020-03-04) Improve performance when starting acquisition.
* (2020-03-02) Add keyboard shortcuts for line profile (l) and pick (p or P).
* (2020-02-13) Allow prefix to be prepended to file names in export dialog (thanks Sherjeel Shabih).
* (2020-02-12) Add sequence align variants for spline and Fourier.
* (2020-01-21) Add support for folders to Run Script dialog.
* (2020-01-17) Add internal support for sectioned acquisition.
* (2019-12-30) Allow spot masks to be elliptical and rotatable.
* (2019-12-26) Change mask graphics to center on calibrated origin.
* (2019-12-23) Add Gaussian, Hamming, and Hann window processing functions.
* (2019-12-15) Allow graphics to be designated as masks.
* (2019-12-13) Add mapped sum and mapped average processing commands.
* (2019-12-01) Add support for new project index file structure.
* (2019-11-30) Add support for PySide2 host.

Version 0.14.8, November 27, 2019
---------------------------------
* (2019-11-25) Improve display of sequence measurements.
* (2019-11-07) Fix drag and drop issue in computation panel.
* (2019-10-31) Change data panel 'All' filter to include acquisition items too.

Version 0.14.7, October 24, 2019
--------------------------------
* (2019-10-22) Fix issue with cursor display on collections of 1D data displayed as image.
* (2019-10-22) Add support for dragging legend items to reorder layers on composite line plotes.
* (2019-09-17) Fix issue with graphics and scale bar coordinates on 4D data image display.
* (2019-08-26) Add adaptive computation throttling to keep CPU usage below maximum.
* (2019-08-26) Eliminate unnecessary data copy during partial acquisition (scan).
* (2019-08-19) Add MIME image/svg+xml to clipboard when copying displays (allows pasting to Office).
* (2019-08-06) Add support to copy line plot and paste to create composite line plot.
* (2019-07-28) Fix bug where cursor position would not display on composite line plots.

Version 0.14.6, July 8, 2019
----------------------------
* (2019-07-08) Fix issue loading old libraries (had been inadvertently disabled).

Version 0.14.5, June 27, 2019
-----------------------------
* (2019-06-25) Make default display slice after pick processing be 5% to 15%.
* (2019-06-25) Fix inspector update bug when deleting data item.
* (2019-04-25) Add lattice mask tool. No inspector yet.
* (2019-04-25) Improve handling of data items with bool data type.
* (2019-04-24) Gracefully handle unknown graphic types for future compatibility.

Version 0.14.4, April 19, 2019
------------------------------
* (2019-04-01) Improve acquisition performance by eliminating unnecessary copy.
* (2019-03-19) Fix potential issue with histogram not showing current data.
* (2019-03-19) Fix issues with prompts and Cancel button in Run Script dialog.
* (2019-03-13) Fix titles of Subtract, Multiply, Divide arithmetic processing results.
* (2019-03-12) Fix history/auto-complete issues in Console windows.
* (2019-02-24) Add 'data_item' and 'data_items' methods to Display API.
* (2019-01-18) Fix issue with line plot log display in inspector.

Version 0.14.3, January 17, 2019
--------------------------------
* (2019-01-17) Fix issue of orphaned data items with no display making acquisition impossible.

Version 0.14.2, January 15, 2019
--------------------------------
* (2019-01-14) Improve performance of deletes (by using transactions).
* (2019-01-09) Fix line plot frame drawing.
* (2019-01-09) Add a progress bar widget.

Version 0.14.1, January 7, 2019
-------------------------------
* (2019-01-05) Adjust auto display intervals to only use data within intervals rather than extending by 10%.
* (2019-01-05) Enable line plot legend automatically when adding 2nd layer (but not otherwise).
* (2019-01-05) Fix problem with new line plot layer coloring after migrating data from old versions.
* (2019-01-03) Fix handling of delete from display panel when multiple items in data panel also selected.
* (2019-01-03) Fix problem so interval graphics update properly on associated line profile.
* (2019-01-02) Fix problem so interval graphics update if only calibration changed.
* (2019-01-02) Add title/caption editor when display panel header is double clicked.
* (2018-12-31) Fix problem starting acquisition when acquisition data item is not yet created.
* (2018-12-12) Fix memory leak when using API data item refs.

Version 0.14.0, December 12, 2018
---------------------------------
* (2018-12-05) Allow text filtering in data panel on data shape and type.
* (2018-12-05) Add export to SVG menu item File > Export SVG...
* (2018-12-04) Add support for string types within computations (inspector, computation panel).
* (2018-11-15) Make menu item for Assign Variable Reference be named sensibly.
* (2018-10-29) Fix bug where line plot grid lines were not consistently drawn.
* (2018-10-15) Introduce composite line plot display items (all inputs must have same calibration units).
* (2018-10-15) Update to new file format (v13). Display items. Simplified data items.
* (2018-10-15) Introduce display item and associated operations.
* (2018-10-08) Print Python and UI versions at startup for reference.
* (2018-10-08) Fix issue with error handling during computations.

The display item feature makes possible line plots with multiple layers which can be reordered. Each
layer in the line plot can have its own label (appearing in the legend) and be adjusted with custom fill
color and stroke color. Additional layers can be added by dragging and removed using the inspector.

The display item feature also make it possible to have two simultaneous views of a single data item
using the Display Copy command in the View menu.

The procedure for updating files from file version 12 to 13 is to open the library folder in the new version -- files
will be automatically updated, but may trigger a delay up to a couple minutes, depending on the size of the library. You
can switch between old versions of Nion Swift and new versions, but when you have fully verified the new data and are
only using the new version of Nion Swift, you can remove the old, unneeded data by removing the folder ``Nion Swift Data
12`` in the library folder.

Version 0.13.9, October 1, 2018
-------------------------------
* (2018-09-29) Minor improvements for data acquisition support.
* (2018-09-12) Improve reliability of undo/redo, enabled in more situations.
* (2018-08-09) Improve reliability when loading corrupted data files.
* (2018-08-03) Add some experimental API functions.

Version 0.13.8, July 23, 2018
-----------------------------
* (2018-07-23) Make launcher command Python 3.7 compatible.
* (2018-07-03) Restructure master session metadata to be stored with application rather than library.

Version 0.13.7, July 2, 2018
----------------------------
* (2018-06-29) Fix regression where annular ring inspector was not available.
* (2018-06-29) Fix regression where spot graphic could not be created/edited by dragging.

Version 0.13.6, June 26, 2018
-----------------------------
* (2018-06-26) Add Ctrl/Cmd-Left/Right-Arrow to move through sequences/collections.
* (2018-06-25) Improve auto complete in Console to auto insert common prefix.
* (2018-06-20) Fix issue with undo not writing undone items to storage in a few isolated cases.
* (2018-06-20) Keep keyboard focus on original when taking snapshot of live data.
* (2018-06-13) Fix undo issues when editing computation variables.
* (2018-06-12) Add redimension sub-menu with redimensioning and squeeze menu items.
* (2018-06-12) Rename 'None' menu item for displays to 'Empty Display'.
* (2018-06-08) Add rotation property to rectangles and ellipses.

Version 0.13.5, June 6, 2018
----------------------------
* (2018-06-04) Extend color map choices with 'black body' and 'kindlmann'.
* (2018-05-25) Fix scaling of composite line plot to scale to common intensity.
* (2018-05-23) Add a clone workspace command.

See http://www.kennethmoreland.com/color-advice/ for advice on color maps.

Version 0.13.4, May 23, 2018
----------------------------
* (2018-05-22) Add pick region average and subtract region average menu items..
* (2018-05-22) Consolidate/compact the processing menu.

Version 0.13.3, May 18, 2018
----------------------------
* (2018-05-15) Consolidate output mechanisms to output window.

Version 0.13.2, May 16, 2018
----------------------------
* (2018-05-15) Add support for scaling on high DPI displays (Windows).

Version 0.13.0, May 10, 2018
----------------------------
* (2018-05-03) Add support for launching using pyqt backend (simpler install).
* (2018-03-26) Add support for preference panels in internal packages (video capture).
* (2018-03-21) Add undo capability for most operations (early version, proceed with caution).
* (2018-03-09) Fix issues with live computations not displaying error messages consistently.
* (2018-03-09) Clean up issues with source and dependent data thumbnails on displays.
* (2018-03-08) Fix histogram update issues.

Version 0.12.0, March 6, 2018
-----------------------------
* (2018-03-05) Improve About Box to give additional Python and important package version info.
* (2018-03-03) Make zoom/position of raster image displays persistent.
* (2018-03-01) Update to new file format (v12). Composites, computations, connections, data structures.
* (2018-02-27) Fix issue with DM export when exporting 32-bit integer data.
* (2018-02-27) Fix calibration on histogram processing output.
* (2018-02-25) Improve compatibility xdata with regular numpy functions.
* (2018-02-22) Improve resilience of workspace during unexpected exit.
* (2018-02-22) Improve compatibility of xdata functions with HDF5 backed data items.
* (2018-02-22) Include eels-analysis package in standard distribution.
* (2018-02-08) Add (internal) support for data structures.
* (2018-01-07) Add (internal) support for composite line plot.
* (2017-12-22) Add (internal) support for composite library items.
* (2017-12-19) Add aberration simulation to Ronchigram simulator.
* (2017-12-14) Performance improvements to display pipeline, raster and line plot.
* (2017-12-09) Fix bugs with data panel, scroll bars.
* (2017-11-27) Fix bugs with cancelling export dialog.
* (2017-11-24) Add (internal) support for library computations.
* (2017-10-27) Improve metadata recording during scans.
* (2017-10-27) Add xdata squeeze function to remove empty dimensions.

Version 0.11.1, October 23, 2017
--------------------------------
* (2017-10-20) Fixed nionlib import issue (wasn't starting host).
* (2017-10-20) Additional documentation on readthedocs.
* (2017-10-19) Improve recorder panel to sync to frames for devices with partial acquisition (scans).
* (2017-10-11) Fix crashes in keyboard handling in interactive scripts and mouse tracker (scan rotation).
* (2017-10-11) Use min/max for auto display limits (enter key). Was more complex algorithm.
* (2017-10-04) Fix launch issue on Linux with recent Miniconda releases.
* (2017-10-02) Improvements to metadata organization during camera/scan acquisition.
* (2017-09-25) Add additional options for exporting TIFF to ImageJ or Baseline compatible files.
* (2017-09-21) Add option to export 1D as X-Y CSV.
* (2017-09-21) Add interval/count controls to recorder dialog.

Version 0.11.0, September 18, 2017
----------------------------------
* (2017-09-14) Improve rendering pipeline again to reduce latency.
* (2017-09-11) Add api.show(), available in Console as show(). Useful to quickly show data.
* (2017-09-10) Consolidate calibrated center/top-left into just calibrated, for consistency.
* (2017-09-09) Improve display of display limits in inspector (5 significant digits now).
* (2017-09-09) Fix bug where width of line profile was displayed incorrectly.
* (2017-09-06) Add menu items for sequence integration, trim, and extract index.
* (2017-09-02) Add measure shifts of sequence and align sequence menu items.
* (2017-09-02) Add an experimental live data recorder (Ctrl-Shift-R on a data item) producing a sequence.
* (2017-08-30) Add a resize menu item which crops/pads without reinterpreting the data.
* (2017-08-28) Reorganize libraries in preparation for standard Python installation.
* (2017-08-28) Update to new file format (v11)
* (2017-08-23) Fix updating issues with line plot, splitters, and other displays.
* (2017-08-17) Add xdata functions: clone_with_data, align, shift, and register.
* (2017-08-08) Fix issues with copy/paste in script edit windows.
* (2017-08-04) Simplify selection of two-source operations such as cross correlation or subtraction.
* (2017-08-04) Add menu items for add/subtract/multiply/divide operations.
* (2017-08-04) Change handling of computed data items to integrate source data/crop into single object.
* (2017-07-28) Restore thumbnail drawing in Jupyter notebooks when using nionlib.
* (2017-07-18) Change Run Script and Console editor windows to float above main window.
* (2017-07-18) Change computation editor panel into window more like Run Script.
* (2017-07-17) Fix issues with splitter in data panel (first launch).
* (2017-07-14) Improve switch dialog (handle return, escape and double clicking).
* (2017-07-14) Add File > Open menu item to directly open other libraries.
* (2017-07-14) Add File > New menu item to directly create new libraries.

The procedure for updating files from 10 to 11 is to open the library folder in the new version -- files will be
automatically updated, but may trigger a delay, up to a couple minutes, depending on the size of the library. You can
switch between old versions of Nion Swift and new versions, but when you have fully verified the new data and are only
using the new version of Nion Swift, you can remove the old, unneeded data by removing the folder ``Nion Swift Data 10``
in the library folder.

Version 0.10.7, July 13, 2017
-----------------------------
* (2017-07-06) Fix bug choosing library at first launch.
* (2017-07-06) Unbundle Qt from Linux distribution (improved compatibility).

Version 0.10.6, June 21, 2017
-----------------------------
* (2017-05-25) Fix bug where data item relationships (dependencies) would get out of sync.
* (2017-05-23) Change focus handling to keep focus on displays rather than text fields.
* (2017-05-04) Improve rendering pipeline to reduce latency.
* (2017-04-28) Improve when 'Correct' button is enabled in tuning. Avoids applying failed tunings.
* (2017-04-24) Fix bug in recompute algorithm (removes sluggishness).
* (2017-04-24) Improve rendering performance (watch for display issues please).
* (2017-04-24) Added date to exported DM3 files (data bar tags).
* (2017-04-22) Improve vertical ticks on line plots.
* (2017-04-21) Improve scan 'Record' reliability.
* (2017-04-21) Name Run Script window with name of script.
* (2017-04-21) Add titles to scan 'Record' images.
* (2017-04-18) Improve handling of missing data on data items (allows delete).
* (2017-04-10) Fix bug where probe graphic wouldn't appear reliably after stopping scan.
* (2017-03-30) Fix bug with recurring 'font' log messages.
* (2017-03-29) Add a center-calibrated coordinate system (inspector).
* (2017-03-24) Standardize on defocus sign during click-to-tilt. May need AS2 adjustment.
* (2017-02-28) Fix return value issues when using API from another process, including Run Script.
* (2017-02-28) Improvements to Run Script window (run again, save window sizing, double clicks, enter).
* (2017-02-23) Improve plug-in loading dependency messages.

Hardware Plug-ins
-----------------
* N4206 (2017-05-23): Improve how fine tuning result output.
* H5928 (2017-05-01): Increase buffering during camera manager (Orca) acquisition.
* H5923 (2017-04-28): Improvements to fine tuning (always using Coarse before).
* H5923 (2017-04-28): Improve reliability of C10 adjustment upon failure.
* H5920 (2017-04-28): Decrease delays when changing exposures on Orca.
* H5907 (2017-04-25): Fix camera monitor window crash (Orca).
* H5906 (2017-04-25): Internal changes to AS2 backplane communication.
* H5882 (2017-04-12): Fix defocus sign issue in tuning.

Version 0.10.5, February 23, 2017
---------------------------------
* Enter key now locks display limits again (useful during acquisition).
* Fix drag and drop issues when adding items to Collections in Data Panel.
* Fix various issues with updating Library and Collections in Data Panel (Latest Session now much more useful).
* Fix cursor display for 3d/4d data sets.
* Fix bugs when changing source objects in computation inspector.
* Fix bugs where line profile (and other processing) not updated when changing collection index on 4d data.
* Improve mouse tracking (priority to already selected items).
* Improve thumbnail generation (was intermittent in last version).
* Improve Projection processing to work on 4d data sets (produces 3d spectrum image from 4d data sets).
* Change image display pipeline to be more threaded, please report any display issues including latency and throughput.
* Large spectrum images or 4d data sets are now stored as HDF5.
* Python h5py package is now an installation requirement.
* nionutils and nionui are now available as open source under Apache 2.0 license.

Processing operations that work on data sets stored as HDF5 and result in a large data set that must be stored
as HDF5 may fail.

There is a known issue using keyboard shortcuts on Linux due to a bug in an underlying library (Qt). We expect this
to be fixed when Qt 5.8.1 is released.

Version 0.10.4, January 13, 2017
--------------------------------
* Fix performance issue introduced just before last release.

Version 0.10.3, January 10, 2017
--------------------------------
* Display quality improvements (improved downscaling).
* Performance improvements (display pipeline).
* Inspector now works during live acquisition (however calibrations still can't be edited during acquisition).
* Fix bug in handling of Fourier mask data.
* Import now able to handle GIF and BMP directly.
* Import improvements to TIFF (contributed by Andreas Mittelberger).

Version 0.10.2, December 2, 2016
--------------------------------
* Extend TIFF_IO with 1-d, 2-d, 3-d, 4-d data, ImageJ compatibility (contributed by Andreas MittelBerger).
* Integrate grid browser, new thumbnail browser into display panel.
* Add cut, copy, paste support for graphics.
* Handle modified/created timestamps in create_data_element_from_extended_data in script API.
* Installer no longer includes Visual C++ 2013 Redistributable package.
* Linux installation now loads Python dynamically, allowing use of Python 3.5 on older systems.

This release brings an improved way of selecting data items to be displayed in display panels.
Click on a display panel (one without an acquisition controller) and press the 'v' key to
switch to a thumbnail browser view. Choosing new data items by clicking or using the arrow
keys will immediately display them in the display panel. Type 'v' again to return to regular
view.

Version 0.10.1, November 21, 2016
---------------------------------
* Fix bug where computed data not always updated properly during dragging.
* Fix DM importer for 3d data sets (move first dimension to last to match Nion Swift).
* Fix scale marker on spectrum images (was using wrong dimension).
* Add ability to specify data descriptor from API when creating extended data.
* Improve handling of metadata in data elements (affects DM importer).

Version 0.10.0, November 15, 2016
---------------------------------
* Display source and dependent thumbnails within each display panel for easier data item navigation.
* Add new script window accessible with Ctrl+K with predefined 'api' for interfacing using API.
* Add history and tab completion to new script window.
* Improvements to dark and gain normalization in some cameras (Orca).
* Rework 'computation' functionality to use API calls for more flexibility. See note below.
* Metadata is no longer copied from source to target during computations. See note below.
* Thumbnails are now rendered with more detail.
* Numerous inspector bug fixes and minor improvements.
* Numerous API improvements. See documentation and typing files for specific details.
* Add more calibration display options (pixels, calibrated, and relative). Edit using Calibration inspector.
* Add annular ring mask graphic (experimental).
* Tuning diagnostic arrows are now available on failed tuning runs.
* Capture button works more consistently for EELS camera.
* Fix some bugs in UI when switching modes on Camera.
* Simplified the threading within the library. See note below.

This release brings an improved way of seeing dependent and source data items in display panels.
Small thumbnails appear indicating source (bottom left) or dependent (bottom right) data items.
The small thumbnails can be dragged into display panels to be displayed.

Computations have changed in this version. Standard computations such as FFT or line profile that
were initially created using menu items should continue to work as expected. If you have entered a custom
computation to generate the data for a data item, the custom computation will need to be modified. Use
the menu item computations as examples on how to make the modifications.

Computations no longer copy metadata. We are working on a solution for gathering metadata in dependent
data items for an upcoming version.

The threading model within the library has been simplified. The result is more reliable data updates,
particularly during acquisition. The downside is potential performance issues if too much processing
is occurring during acquisition. In most cases, processing will be sped up (three or less processed items
occurring live).

Version 0.9.0, August 22, 2016
------------------------------
* Recording data via API no longer creates new data item for each acquisition.
* Extend data system to include descriptions of dimensions (sequence, collection, datum).
* Fix crash bug after Import Data menu command.
* Fix intermittent bug causing hangs when switching workspaces.
* Fix bug in auto computing display limits on complex data (improves FFT display).
* Change SI and other 3d images to treat last dimension as signal rather than first.
* Fix drawing issues on line plot display (intervals drawn outside bounds).
* Enter key on line plot with selected intervals will auto-scale to data in intervals.
* Add spot and wedge mask graphics (experimental). Add Fourer Filter menu item.
* Add display rate limiter. Improves performance.
* Add color map property for displays; add inspector for it; add display in histogram panel.
* Fix bugs with graphic item inspectors on ndim > 2 data.
* Fix bugs in threaded computations (single threaded for now). Improves performance unless many computations.
* Display statistics in calibrated units in histogram window.
* Add cursor intensity display when hovering over histogram window.
* Improve cursor display during live acquisition.
* Fix bugs in computation panel.

Data indexing has changed in this version. 2d and 1d data has not been affected. 3d data where
the signal is in the first index will have to be changed so that the signal is in the last index.
4d data should be organized into two collection indexes followed by two datum indexes. Existing
3d and 4d data is not automatically migrated since the information about how to migrate it is missing
in older versions. Please contact Nion for help in migrating 3d and 4d data sets to this version.

Version 0.8.2, June 17, 2016
----------------------------
* Change wording of split workspace panel menu commands.
* Provide automatic migration from old files to new files, but still leaves old file directory intact.
* Ensure script dialogs get closed at exit.
* Minor improvements to 'run script' dialog, resizable.

Version 0.8.0, May 3, 2016
--------------------------
* File version to 10 (was 8), uses 'Nion Swift Data 10' as internal data storage folder name.
* Continued improvements to computations. Still experimental unless initiated from menus.
* Add additional data generation and RGB functions for use in computations.
* Histogram and statistics are displayed for selected region instead of entire image if there is one.
* Add a pick region tool for summing spectra over a region.
* Add import folder functionality, which imports a folder as a new library.
* Disable automatic migration from file version 8 to 10. See note.

Procedure for updating files from 8 to 10 is to duplicate the 'Nion Swift Data' subfolder in your
library and rename the copy to be 'Nion Swift Data 10'. Then run Swift (or switch to the desired
library within Swift) and allow Swift to upgrade the files. Two copies of the files will now exist,
a set compatible with Swift 0.7 and a new set compatible with Swift 0.8. Changes to one set will
not affect the other set, making it easy to switch between versions.

Version 0.7.0, March 29, 2016
-----------------------------
* Change all processing menu items to use computations. Processed data can't be loaded in older versions of Swift.
* Improve line plot display drawing when displaying with more pixels than channels.
* Improve FFT performance, fix display limit bug.
* Improve performance of dragging graphics and other mouse tracking.
* Improve reliability of exiting application (making sure settings get saved).
* Improve handling of inverted calibration units in FFT data (now display non-inverted).
* Display FFT calibrations in polar coordinates.
* Fix problem in calibrated length calculations when calibration offset is non-zero.
* Fix problem of origin for FFT calibrations.
* Add support for importing .npy files directly. Useful for debugging.
* Separate data processing functions into their own nion.data module (open source).
* Change versioning check in API. Recommended technique is now "~1.0" meaning compatible with 1.0 API.
* Fix problem when deleting data items from display panel.
* Add experimental Run Script... menu item.
* Add experimental line plot displays with multiple plots.
* Add option in inspector to change display type (useful for line plot displays with multiple plots).

Version 0.6.0, January 26, 2016
-------------------------------
* Switch to Python 3.5. You must use Nion Swift with Python 3.5 and NumPy 1.10.
* Add a 'Choose...' dialog in Switch Workspace sub-menu for loading previous workspace. This makes it easier to choose
  from numerous workspaces.
* New implementations of Python console and output windows. Some previous functionality (particularly up-arrow to
  repeat last command) is missing in new version.
* Fix another issue with exporting individual data items under Linux.
* Linux distribution now bundles Qt libraries. This eliminates the need to match the installed Qt version to the
  particular Nion Swift distribution.

Version 0.5.8, December 29, 2015
--------------------------------
* Add draggable acquisition thumbnails to each controller panel (SuperScan, Camera, etc.).
* Generate fewer data items by splitting library into persistent and temporary (live) sections and re-using existing
  data items for acquisition where possible.
* Ensure that old tuning images get deleted when starting tuning.
* Add ability to copy tuning output table from Task panel.
* Handle arrow keys in grid/list views. Also do a better job of keeping selection in view.
* Fix bugs on moving line plot intervals with arrow keys. Display intervals from line plot on the line profile itself.
* Change click-to-shift to use S-click and T-click to avoid conflict with regular graphic dragging.
* Add Metadata panel in the Window menu to view most metadata associated with a data item.
* Add Session panel in the Window menu and session inspector. The session panel allows you to edit what data is
  copied to each acquisition. The session inspector views the data already attached to a specific data item.
* Fix crash during the Export or Import dialogs. Also add additional export options to include the data item title in
  filename and more.
* Simplify title bars of display panels and make them draggable. Fix bug when changing display controller during
  acquisition. Improve handling of acquisition control bars in display panel when dragging.
* Improve startup times with libraries with many data items.
* Fix problems with Computations (parenthesis for precedence, bugs). Other improvements.
* Include proper Visual Studio C++ redistributable in Windows installer.
* Improve handling of variable width utility panels.
* Fix issues with start_recording/abort_recording API calls.
* Fix RGB handling in DM3 IO handler.

Version 0.5.7, October 4, 2015 (r3683)
--------------------------------------
* Switch to loading Python dynamically on Windows/OS X.
* Dynamic Python allows use of any Python installation on your machine.
* Dynamic Python may ask for Python location first time it is used.
* Fix issues when exiting using window close buttons.
* Add length/angle controls to line inspector.
* SuperScan: Add control to link/unlink width/height in UI.
* SuperScan: Add access to AC frame sync in UI.
* API/Scripting: Add support for 'confirm' to set_control_output.

Version 0.5.6, August 22, 2015 (r3614)
--------------------------------------
* Switch to Python 3.
* Add symbolic "computation" panel.
* Cleaned up shut down / switch library behavior.
* Fixed bugs in dm3 file format support.
* Fixed bugs when deleting data items.
* Automatically use empty displays when placing new data items.
* Add tool tips for some toolbar items.
* Make interval selections easier to use in line plot.
* Improve hit testing when moving graphics on images.
* Scripting changes
   * class API
      * Add method get_instrument_by_id
   * class DocumentController
      * Add method display_data_item.
      * Add method target_display.
      * Add method target_data_item.
   * class HardwareSource
      * Add frame_parameters parameter to method start_playing
      * Add method get_default_frame_parameters
      * Add method get_frame_parameters_for_profile_by_index
      * Add property profile_index.
      * Add method get_frame_parameters.
      * Add method set_frame_parameters.
      * Add method set_frame_parameters_for_profile_by_index.
      * Add method stop_playing.
      * Add method abort_playing.
      * Add property is_playing.
      * Add method start_recording.
      * Add method abort_recording.
* API changes
   * class API
      * Add method get_instrument_by_id
   * class DocumentController
      * Add method display_data_item.
      * Add method target_display.
      * Add method target_data_item.
   * class HardwareSource
      * Change method get_default_frame_parameters to return dict instead of struct.
      * Change method get_frame_parameters_for_profile_by_index to return dict instead of struct.
      * Change methods taking frame parameters to take a dict rather than struct.
      * Add property profile_index.
      * Add method get_frame_parameters.
      * Add method set_frame_parameters.
      * Add method set_frame_parameters_for_profile_by_index.
      * Add method stop_playing.
      * Add method abort_playing.
      * Add property is_playing.
      * Add method start_recording.
      * Add method abort_recording.

Version 0.5.5, June 2015 (r3399)
--------------------------------
* Introduce Connection plug-in for scripting via external Python script.
* Add additional items to context menu to export and change display panel type.
* Change cursor when using tools or mouse over splitter controls.
* Increase zoom change so that zooming in/out happens faster.
* Fix bugs in drag and drop, focusing, mouse position, inspector, data bar.
* Fix bugs in time zone, export multiple items from context menu.
* Fix bugs in DM3 file format importer/exporter.
* Fix bugs with slice operations (handling calibrations).
* Add sum to statistics, twist down options in inspector.
* Add display panel identifiers displayed in header.
* Scripting changes
   * Introduce scripting (a subset of API, available externally via nionlib)
   * class Region
      * Add property type
   * class DataItem
      * Add method add_point_region
      * Add property data
      * Add property data_and_metadata
      * Add property intensity_calibration
      * Add property dimensional_calibrations
      * Add property metadata
      * Add method set_data
      * Add method set_data_and_metadata
      * Add method set_intensity_calibration
      * Add method set_dimensional_calibrations
      * Add method set_metadata
   * class DataGroup
      * Add method add_data_item
   * class DisplayPanel
      * Add property data_item
   * class DocumentController
      * Add property library
      * Add property all_display_panels
   * class HardwareSource
      * Add method start_playing
      * Add method grab_next_to_finish
   * class Library
      * Add property data_item_count
      * Add property data_items
      * Add method create_data_item
      * Add method create_data_item_from_data
      * Add method create_data_item_from_data_and_metadata
      * Add method get_or_create_data_group
   * class Application
      * Add property library
      * Add property document_controllers
   * class API
      * Add method create_calibration
      * Add method create_data_and_metadata
      * Add method get_hardware_source_by_id
      * Add property application
      * Add property library
* API changes
   * class DataItem
      * Add property data
      * Add property data_and_metadata
      * Add property intensity_calibration
      * Add property dimensional_calibrations
      * Add property metadata
      * Add method set_data
      * Add method set_data_and_metadata
      * Add method set_intensity_calibration
      * Add method set_dimensional_calibrations
      * Add method set_metadata
   * class DisplayPanel (Add)
      * Add property data_item
   * class Library
      * Add property data_item_count
      * Add property data_items
   * class DocumentController
      * Add property all_display_panels
   * class Application (Add)
      * Add property library
      * Add property document_controllers
   * class API
      * Add property application
      * Add property library
      * Add method create_data_and_metadata
      * Deprecate method create_data_and_metadata_from_data

Version 0.5.4, May 2015 (r3235)
-------------------------------
* Add ability to put a data item browser in a display panel in workspace.
* Change tools such as line profile and crop to interactively create the regions.
* Make 'enter' key fix the current display limits.
* Add support for log display in line plot, enabled by checkbox in Inspector. (Partial)
* Add context menu (right-click) to set display panel type and split existing panels without dragging.
* Improve error handling during acquisition.
* Updated host application to use Qt 5.4 for all platforms.
* Camera improvements
   * Camera controller now shows binning rather than frame size.
   * Fix click to shift issues.
   * Bug fixes and consistency fixes.
* SuperScan improvements
   * Better partial frame readout.
   * Fix click to shift issues.
* API changes
   * class HardwareSource
       * Add method get_frame_parameters_for_profile_by_index
   * class Library (Add)
      * Add method create_data_item
      * Add method create_data_item_from_data
      * Add method create_data_item_from_data_and_metadata
      * Add method get_or_create_data_group
      * Add method data_ref_for_data_item
   * class DocumentController
      * Add property library
      * Deprecate method add_data
      * Deprecate method create_data_item_from_data
      * Deprecate method create_data_item_from_data_and_metadata
      * Deprecate method get_or_create_data_group

Version 0.5.3, April 2015 (r3118)
---------------------------------
* Performance improvements.
* Stability improvements, particularly during exceptions.
* Fix cursor flickering bug, bug when exporting single data item, and other minor bugs.
* Camera improvements
   * Added new camera panel controller
   * Includes ability to automatically view projected version of EELS raw data
   * Work in progress
* SuperScan improvements
   * Add controls to adjust PMT
   * Add pixel size, pixel time, FoV adjustment buttons
* API changes
   * class RecordTask (Add)
      * Add property is_finished
      * Add method grab
   * class ViewTask (Add)
      * Add method grab_immediate
      * Add method grab_next_to_finish
      * Add method grab_next_to_start
   * class HardwareSource
      * Remove method get_data_and_metadata_generator
      * Add method get_default_frame_parameters
      * Add method start_playing
      * Add method record
      * Add method create_record_task
      * Add method create_view_task
   * class Instrument
      * Remove method start_playing
      * Add method get_property
      * Add method set_property
   * IO Handler Delegate
       * Require property io_handler_id for IOHandler delegate
   * class API
      * Add version parameter to get_hardware_source_by_id
      * Remove get_hardware_source_api_by_id
      * Add get_instrument_by_id

Version 0.5.2, March 2015 (r2920)
---------------------------------
* Improve acquisition performance.
* Include Anaconda Python with Swift distribution.
* Restructured extension mechanism to go through a versioned API (work in progress).
* Expand batch export dialog to allow choice of file type.
* Extend dm3 file I/O to read/write calibration and metadata.
* Fix bug with display of histogram for complex data (easier to adjust contrast).
* Add sobel filter and laplace filter processing menu items.
* Add median filter, uniform (mean) filter, transpose/flip processing menu items.
* Fix bug preventing entering of numbers with attached units in inspector.
* Keep processing and regions attached to acquisition data items connected after restart.
* Add warning dialogs before updating data items to newer version, with choice to skip.
* Improve support and fix bugs for partial data acquisition.
* Add main API version 1.0 (work in progress).
* Add acquisition API version 1.0 (work in progress).
* Fix bug that quit application when switching workspaces.
* Fix bug importing dm3 files (introduced in 0.5.1).
* Added View > Live sub-menu to select live controllers for a display panel.
* SuperScan improvements
   * Add new panel for controlling the SuperScan
   * Includes beam position and blanking support
   * Includes multi-channel readout
   * Includes ability to configure size, field of view, rotation, and other frame parameters
   * Includes ability to do Record, then assess recorded image before returning to view
   * Includes Capture button

Version 0.5.1, February 2015
----------------------------
* Significant internal changes to support processing relationships between data.
* Many bug fixes and performance improvements.
* Versioning to NData v8 (buffered data source, dates)

Version 0.4.0, December 2014
----------------------------
* Improve display of FFTs (throw out bottom 10% of pixels).
* Improve scaling of FFTs (now preserve RMS).
* Add auto correlate and cross correlate menu items.
* Changed Graphic objects such as rectangles and points to be named Regions in menus.
* Restructured dependent items to store their data in file. Reduces recalculations.
* Renamed calibration accessors in DataItem to intensity_calibration and dimensional_calibrations.
* Versioning to NData v6 (restructure operations)

Version 0.3.6, November 10, 2014
--------------------------------
* Enable new TIFF_IO handler for TIFF files (supports native data types).
* Fix bugs that sometimes prevents live items from appearing at top of data panel.
* Fix bugs occurring after switching libraries (libraries were previously called workspaces).
* Improve AutoTuning output.
* Fixed potential crash bug during canvas drawing.

Version 0.3.5, September 23, 2014
---------------------------------
* Fixed compatibility issue with Numpy 1.9.
* Preliminary implementation of batch export.
* Performance improvements, particularly for line plot.
* Add data item grid view as alternative to data item list.

Version 0.3.4, August 4, 2014
-----------------------------
* Added Calculation panel for doing simple math on data items.
* Added width to slice operation which integrates around slice center.
* Added pick operation for working with 3d data sets.
* Made default display for 3d data sets use slice operation (in Display section of inspector).
* Speed up line plot drawing and region dragging, and all drawing in general.
* Fix importing files that are newer than allowed.
* Fix problem displaying line plot values under cursor.
* Fix slice operator to use correct upper limit.
* Fix problem of inadvertently selecting graphics when right clicking
* Fix problem where multiple dependent data items didn't appear in "Go to" pop-up menu
* Fix problem where selection mark on PointSelection covered center point
* Fix problem displaying Point inspector (Graphic, not Region)
* Added ability for operations to utilize multiple Regions.

Version 0.3.3, July 27, 2014
----------------------------
* Bug fixes and performance improvements
* Internal changes (canvas, performance)

Version 0.3.2, July 18, 2014
----------------------------
* Clean up calibration transforms on 2d images (uncalibrated origin at top-left)
* Versioning to NData v3 (rename calibration 'origin' to 'offset')
* Change .nswrk library file to .nslib and store as JSON
* Internal changes (storage)

Version 0.3.1, July 8, 2014
----------------------------
* Added projection operation to go from 2d to 1d data
* Added point region for 2d image displays
* Added interval regions for line plot display, tool bar item too
* Added slice operator for slicing 3-d data sets
* Added selector operator for selecting data from data items with multiple sources (experimental)
* Internal changes

Version 0.3.0, June 6, 2014
---------------------------
* Added ability to manage workspaces, switching, creating, loading.
* Data item files within workspace are now self-contained, using ndata file format.
* Improved line plot display and controls. Proper binning, drawing every pixel.
* Improved histogram display.
* API: Introduce new mechanism to access metadata on data items
* Updates internal database to version 10.

Version 0.2.1, May 13, 2014
---------------------------
* Improved speed of large libraries, particularly deleting and starting acquisition.
* Data items are now listed strictly by date descending, rather than hierarchically.
* Added context menu (right click) to go to data item source or dependents.
* Added data item title editing and caption field to inspector.
* Added search field to filter user interface to search on title or caption.
* Automatically select new data item when doing processing or snapshot, for easier metadata editing.
* Removed Recent data group (temporarily).
* Updates internal database to version 7.

Version 0.2.0, May 2, 2014
--------------------------
* Improved performance with 1000+ data items.
* Improve line plot display, controls, and inspector.
* Merged Operations panel into Inspector.
* Removed inset processing overlays temporarily (you probably didn't even know about these).
* Updates internal database to version 6.
