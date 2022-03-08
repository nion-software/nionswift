:orphan:

.. _user-interface:

**************
Utility Panels
**************

.. _Workspaces:

Workspaces
==========
The workspace is the area where you can view your data.

The workspace can be subdivided into display panels and the size of the display panels can be adjusted by dragging on their edges.

You can drag external files into display panels to import them.

You can drag items from the data panel to the display panels to show them.

You can select one or more display panels for processing by clicking to select one or shift-clicking to select multiple.

If you do processing or acquisition which produces new data, its associated display item will be displayed in an empty display panel if available.

See :ref:`display-panels`.

.. _Activity Panel:

Activity
========
.. displays current computation activity
.. work in progress

The Activity panel (:menuselection:`Window --> Activity`) allows you to observe activity, such as computations, that are running in the background. It can be useful for understanding how live computations are being updated during acquisition or editing.

.. _Collections Panel:

Collections
===========
.. all, persistent, live, latest, data groups

The Collections panel (:menuselection:`Window --> Collections`) allows you to filter items in the data panel by whether they are Live, Persistent, created in the Latest Session, or in one of your custom Data Groups.

.. TODO: where are Data Groups covered?

.. _Data Panel:

Data Panel
==========
The Data panel (:menuselection:`Window --> Data Panel`) lists the display items in your project.

You can drag items from the data panel to display panels in the workspace.

You can delete display items (and associated data items if they become orphaned) by selecting them in the data panel and pressing the delete key.

You can filter (by text) what items appear in the data panel by typing into the :guilabel:`Filter` field at the bottom of the data panel. The filter works on the title and the size/data type fields.

.. _Histogram Panel:

Histogram
=========
The Histogram panel (:menuselection:`Window --> Histogram`) shows the histogram graph and other statistics of the data in the selected display panel if a display item with a single data item is shown. It also shows the mapping of data intensity values to colors in a color bar just below the graph.

If there are either zero or more than one display panels selected or if the display item in the selected display panel displays more than one data item, the histogram will be blank.

You can click and drag over a range of intensity levels in the histogram graph to change display limits of the display item.

You can double click in the histogram graph to reset the display limits. This is the same as clicking on a display panel with a single data item and pressing the :kbd:`Enter` key.

If the display item has a selected rectangle or ellipse (for an image) or an interval (for a line plot), the histogram panel will show the histogram graph and statistics for just the are within the sub-region. This provides a quick way to examine statistics within a sub-region.

.. _Info Panel:

Info
====
The Info panel (:menuselection:`Window --> Info`) shows the position of the cursor and the value at the pixel under the cursor if the cursor is over a display item showing a single data item in a display panel. It will also show the intensity level of the data represented at the cursor position in the histogram panel.

.. _Inspector Panel:

Inspector
=========
The Inspector panel (:menuselection:`Window --> Inspector`) shows detailed information about the selected item and allows you to edit it. The selected item may be a display item or a graphic.

The inspector is split into subsections that can be individually opened or closed, depending on your needs at the moment.

.. _Info Inspector Section:

Info
----
.. title, caption, session id, date

The :guilabel:`Info` inspector subsection displays the title of the display item or data item. It also allows you to edit a free text description / caption of the item. It also displays the session id and creation date of the item.

The title of the item is treated differently depending on whether a single data item is associated with the display item or not. If a single data item is associated with the display item, then the title field in the inspector displays and edits the data item title directly. Otherwise, if there are more than one data items associated with the display item (e.g. in a line plot displaying multiple layers), then the title field in the inspector displays and edits the display item title and does not display or change the individual data item titles. To edit the individual data item titles, you must use a display that is displaying just that data item only.

To edit the description / caption, press the :guilabel:`Edit` button, make your changes, then click :guilabel:`Save` or :guilabel:`Cancel`.

.. _Image Display Inspector Section:

Image Display
-------------
.. display type

The :guilabel:`Image Display` inspector subsection allows you to force the display to either a line plot or an image instead of the default, which is an image for 2d data and a line plot for 1d data.

.. _Image Data Inspector Section:

Image Data
----------
.. date, data description, data range (r/o), intensity display limits, color map, brightness, contrast, adjustment

The :guilabel:`Image Data` inspector subsection shows you information about data displayed as an image, including the creation date, a description of the dimension grouping, the minimum and maximum values in the data, the intensity display limits, the color map. It also allows you to adjust brightness and contrast, to apply a display adjustment, and to set the conversion from complex data to scalar if required.

The intensity display limits may entered in the fields or adjusted using the Histogram panel. You can reset them by deleting the values in the fields and pressing :kbd:`Enter`.

You can choose a different color map. The intensity values will be mapped from the intensity display limits to the full range of the color map. You can set it to default to use the default color map (grayscale).

You can adjust the brightness and contrast using the sliders or by entering values in the associated text fields. The values for brightness range from -1.0 to 1.0 with a default of 0.0. The values for contrast typically range from 1/10 to 10 with a default value of 1. You can enter numbers as fractions, such as "1/2".

The adjustment can be set to None, Equalized, Gamma, or Log. Adjustments are applied after brightness and contrast. Equalized means the display will attempt to have more color variation where there are is intensity density. Gamma means the display will apply a gamma curve to the contrast transfer function. The values for gamma typically range from 10 to 1/10 with the default value of 1. You can enter numbers as fractions, such as "1/2". Log means the display will apply a log to the contrast transfer function. If intensity values are small or negative, the behavior is undefined.

If your data is complex, you can also choose how to convert the data from complex to a scalar value for display. The options are Log Absolute, Absolute, Real, and Imaginary. The default is Log Absolute.


.. _Line Plot Inspector Section:

Line Plot Display
-----------------
.. intensity range, channels, auto, log scale, legend position

The :guilabel:`Line Plot Display` inspector subsection allows you to force the display to either a line plot or an image instead of the default, which is an image for 2d data and a line plot for 1d data.

It also allows you to specify an intensity range to be displayed vertically on the line plot and a channel range to be displayed horizontally on the line plot. You can remove values from low/high intensity and/or left/right channels by deleting the text and pressing enter. This will trigger that particular value to be auto calculated.

This inspector subsection also allows you to indicate whether to display the vertical intensity axis of the line plot on a log scale. You can change the setting by checking/unchecking the :guilabel:`Log Scale (Y)` checkbox.

Finally, you can also specify the legend position as :guilabel:`None`, :guilabel:`Top Left`, or :guilabel:`Top Right`.

.. _Data Info Inspector Section:

Data Info
---------
.. for each data item
.. date, data description, shape, data type

For each data item displayed with the display item, the :guilabel:`Data Info` inspector subsection shows you the creation date, description of the dimensional groupings, shape of the data, and the data type.

For image displays, there will only be one data item. For line plots will be one or more data items.

.. _Calibrations Inspector Section:

Calibrations
------------
.. for each data item
.. offset, scale, units for each dimension
.. displayed units

For each data item displayed with the display item, the :guilabel:`Calibrations` inspector subsection shows you the dimensional and intensity calibrations and allows you to edit them. You can edit the offset, scale, and units for each dimension.

.. see https://github.com/nion-software/nionswift/issues/300

The :guilabel:`Display` combo box also allows you to select how the units are displayed and edited.

.. _Session Inspector Section:

Session
-------
.. for each data item
.. specific to data item

For each data item displayed with the display item, the :guilabel:`Session` inspector subsection allows you to see and edit the session info for that particular data item. For editing the global session information which gets applied to new data, see `Sessions`_.

.. _Computation Inspector Section:

Computation
-----------
.. for each data item
.. recommend using editor instead

For each data item displayed with the display item, the :guilabel:`Computation` inspector subsection allows you to edit the computation associated with that data item.

The computation editor  (see :ref:`Edit Computation`) is recommended instead of the computation inspector for editing computations. They do similar things but the editor is easier to access.

.. _Layers Inspector Section:

Line Plot Display Layers
------------------------
.. layer name, move layer forward/back, add/remove layer
.. data index, row
.. fill color, stroke color, stroke width
.. complex display type

The :guilabel:`Line Plot Display Layers` inspector subsection shows and allows you to edit the layers of a line plot display. In many cases, there will only be a single layer.

The up and down arrows allow you to change the ordering of layers.

The plus and minus buttons allow you to add and remove layers.

The data index and row fields allow you to associate the layer with one of the data items displayed by the line plot display. A data item may be one dimensional or two dimensional. If the data item is two dimensional, the row field allows you to indicate which row of the data to use for the line plot display. The default is row 0. For example, a data item which is 1024x4 can still be displayed as four layers by using the same data index and change the row field for the values 0, 1, 2, 3.

.. see https://github.com/nion-software/nionswift/issues/758

The fill color, stroke color, and stroke width control the look of the layer in the line plot. You can click on the color wells to bring up a color picker. You can enter colors as "#F00", "#00FF00", "blue". Clearing the field will make the color tranparent (not displayed). The default stroke width is 1.

If your data is complex, you can also choose how to convert the data from complex to a scalar value for display. The options are Log Absolute, Absolute, Real, and Imaginary. The default is Log Absolute.

.. _Graphics Inspector Section:

Graphics
--------
.. label, properties of specific graphic, displayed units

For each graphic display with the display item, the :guilabel:`Graphics` inspector subsection allows you to inspect and edit the properties of the graphic.

If a graphic is selected, it shows the inspector for the single selected graphic; otherwise it shows an inspector for each graphic in the display item.

The :guilabel:`Label` field is common to all graphics and can be edited to label the graphic.

The :guilabel:`Display` combo box allows you to select the units displayed for graphics. It allows you to change the setting for the display item as a whole and it will apply to all graphics (see `Calibrations`_).

The inspector for the Line graphic allows you to edit the start and end points, length, and angle (in degrees).

The inspector for the Rectangle and Ellipse allow you to edit the center position, size, and rotation (in degrees).

The inspector for the Point allows you to edit the position.

The inspector for the Interval allows you to edit the start and end channels.

The inspector for the Channel allows you to edit the channel.

The inspector for the Spot Fourier Mask allows you to edit the center position, size, and rotation (in degrees) of the primary spot.

The inspector for the Wedge Fourier Mask allows you to edit the start and end angle (both in degrees).

The inspector for the Bandpass Fourier Mask allows you to edit the inner radius and outer radius and allows you to select the bandpass type (low, high, band).

The inspector for the Lattice Fourier Mask allows you to edit the center position, size, and rotation (in degrees) of the primary and secondary spots.

.. _Metadata Panel:

Metadata
========
.. a viewer for the metadata

The Metadata panel (:menuselection:`Window --> Metadata`) allows you to see and edit the metadata attached to the data item associated with the selected display item.

.. _Output Panel:

Output
======
The Output panel (:menuselection:`Window --> Output`) shows text output while running the application.

Additional debugging information may be available using debugger consoles if launched from the console.

.. _Sessions Panel:

Sessions
========
.. the information to seed new sessions
.. when does a session begin?

The Session panel (:menuselection:`Window --> Sessions`) allows you to see and edit the session info that gets applied to new acquisition data. For editing the session information already attached to a data item, see `Sessions`_.

.. _Task Panel:

Task Panel
==========
.. table output from alignment

The Task panel (:menuselection:`Window --> Task Panel`) allows you to see the output from tasks such as microscope tuning. The output is often arranged into a table of data.

.. _Tool Panel:

Toolbar
=======
.. tools: pointer, hand, line, rectangle, ellipse, point, line profile, interval, spot, wedge, band pass, array
.. images: zoom options
.. workspace: split h,v, 2x2, 3x2, 3x3, 4x3, 4x4, 5x4, select more panels, clear selected panels, reset workspace, close selected panels

The Tools panel (:menuselection:`Window --> Tools`) allows you to select tools, adjust image zooming, and modify the workspace.

The tools available are the pointer, hand, line, rectangle, ellipse, point, line profile, interval, spot, wedge, band pass, and lattice tools. Some tools have keyboard shortcuts which can be seen by hovering over the tool.

The zoom buttons allow you to set raster image displays to fill the space with the image (Fill), fit the image to the space (Fit), set the pixel scaling to one data pixel per screen pixel (1:1), and set the pixel scaling to one data pixel per two screen pixels (2:1).

The workspace buttons allow you to split the workspace panels horizontally and vertically, or into grids of 2x2, 3x2, 3x3, 4x3, 4x4, 5x4. There is a button to expand the selected display panels. Pressing this button repeatedly allows you to select all of the display panels with a few clicks. There are also buttons to clear the contents of the selected display panels, close the selected display panels, and reset the workspace to a single display panel.

.. _Recorder Dialog:

Recorder
========
.. records a data item, useful during live acquisition or adjustments
.. interval, number of frames
.. what does it produce?

The Recorder dialog (:menuselection:`File --> Data Item Recorder...`) allows you to record data at regular intervals from the display item selected when you open the recorder.

To record acquisition, click on the live acquisition display panel. Then open the Recorder dialog. Enter the desired interval (in milliseconds) and the number of items to record. Then click Record. The resulting data item will be a sequence of data sampled from the live data at regular intervals.

.. _Notifications Panel:

Notifications
=============
.. displays notifications, must be dismissed, global

The Notification dialog (:menuselection:`File --> Notifications...`) allows you to see notifications about errors and other important information that occurs while running the software.

The dialog will open automatically in the last location if a notification occurs. You must dismiss the notification and close the dialog.
