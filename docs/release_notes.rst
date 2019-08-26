.. _release-notes:

Release Notes
=============

UNRELEASED
----------
* (2019-09-17) Fix issue with graphics and scale bar coordinates on 4D data image display.
* (2019-08-26) Add adaptive computation throttling to keep CPU usage below maximum.
* (2019-08-26) Eliminate unnecessary data copy during partial acquisition (scan).
* (2019-08-26) Add support for dragging legend items to reorder layers on composite line plotes.
* (2019-08-19) Add MIME image/svg+xml to clipboard when copying displays (allows pasting to Office).
* (2019-08-06) Add support to copy line plot and paste to create composite line plot.
* (2019-07-28) Fix bug where cursor position would not display on composite line plots.

Version 0.14.6, July 8, 2019
-----------------------------
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
