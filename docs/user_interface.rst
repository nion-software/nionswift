:orphan:

.. _user-interface:

**************
Utility Panels
**************

.. _Workspaces:
.. This section will be covered by the overview section so this will remain here temporarily until that section is finished.
Workspaces
==========
The workspace is the area where you can view your data.

The workspace can be subdivided into display panels and the size of the display panels can be adjusted by dragging on their edges.

You can drag external files into display panels to import them.

You can drag items from the data panel to the display panels to show them.

You can select one or more display panels for processing by clicking to select one or shift-clicking to select multiple.

If you do processing or acquisition which produces new data, its associated display item will be displayed in an empty display panel if available.

See :ref:`display-panels`.

Utility Panels
==============

Utility panels are individual windows within the software that serve different functions. While the display panels display data items and allow for customization, the utility panels are where the customization actually happens. For example, a display panel can display image data in different colors, but in order to choose which color to display, the option must be selected in the Inspector utility panel. Each utility panel serves to change or edit a given parameter about the selected data.

Having individual utility panels for similar parameters means that the workspace can be fully customized for the user's purpose. There are several ways to customize the utility panel layout:

* Choose to show or hide any utility panel by using the [Window] menu.

* Quickly close a utility panel by clicking the x button in the corner of its title bar.

* Click and drag a utility panel by its title bar to rearrange the layout of the shown panels.

* Layer utility panels by dropping one utility panel onto another. If two or more panels are layered, selection buttons will appear at the bottom of the panel to switch between them.

* Pop utility panels out into a separate window by dragging the panel away from the main window by the title bar.

* Resize a utility panel by clicking and dragging from its edges.

IMAGE: CUSTOMIZING UTILITY PANELS 

The utility panels are organized alphabetically in the [Window] menu, and their functions are as follows:

.. _Activity Panel:

Activity
========
IMAGE: ACTIVITY PANEL 

The Activity panel shows activity that is running in the background of the application. Changes to computations updated during live data acquisition or editing will be displayed in this panel.
Observe background activity.

.. _Collections Panel:

Collections
===========
IMAGE: COLLECTIONS PANEL 

The Collections panel sorts the data items in a project into folders. Data items are automatically sorted into four categories:

* All - All data items in the current project

* Persistent - Data items that are not actively gathering data

* Live - Data items that are actively gathering data

* Latest Session - Data items used in the most recent session (since the most recent time the project was opened)

To view a collection, click on the title of the desired collection in the Collections panel. All data items in the collection will be listed in the Data panel. By default, the Data panel is set to show the “All” collection.

The Collections panel also provides a “My Data” collection which is curated by the user. “My Data” can be used to group any data items together. To add a data item to the “My Data” collection, drag the data item from the data panel into the “My Data” collection in the Collections panel.

.. _Data Panel:

Data Panel
==========
IMAGE: DATA PANEL 

The Data panel provides a list of all the data items in a given collection. By default, the Data panel is set to show all data items in a project. The data items that are shown can be changed by choosing a different collection in the Collections panel.

Newly created data items will appear in the data panel. Make sure the collection is set to “All.” A new data item may not be applicable to the currently selected collection.

To delete a data item, select it and press the delete key.

You can also search for data items in the selected collection by using the filter text box at the bottom of the Data panel. If a data item is not in the selected collection, it will not appear in the filtered results. The filter search bar looks for keywords in the titles and captions of data items. 

Any data item in the display panel can be displayed in a display panel. To display a data item, drag the data item from the data panel into an empty display panel.

.. _Histogram Panel:

Histogram
=========
IMAGE: HISTOGRAM 

The Histogram shows the range of data in the selected data item. The bar directly under the histogram displays the color range of the data and will change color to match the color map of the selected display. General values about the data (maximum value, mean, minimum value, etc.) are displayed under the histogram. If no display panel or data item is selected, the histogram panel will not display anything.

To select a certain range of data, click and drag on the histogram. Doing this will zoom into the histogram on the selected range and the associated display panel will only display data values within that range. To reset the histogram range, double click on the histogram.

If a graphic is selected, the histogram will show data within that graphic. Click outside of the graphic on a display panel to show the histogram for the whole data item.

.. _Info Panel:

Info
====
IMAGE: INFO PANEL

The Info panel shows the position of the cursor over a displayed data item and gives the corresponding value for the data at that position. When hovering the cursor over the histogram, the info panel will show the intensity for a given position along the histogram.

.. _Inspector Panel:

Inspector
=========
The Inspector Panel shows information and settings for the selected item. The Inspector is split into subsections to help you find the specific types of information you are looking for. When different kinds of items are selected (display item, graphic, etc.) the Inspector’s subsections will change to display settings relevant to that type of item.

Clicking the triangle next to the title of a given subsection will expand or hide the subsection.

IMAGE: IMAGE INSPECTOR 

IMAGE: LINE PLOT INSPECTOR 

.. _Info Inspector Section:

Info
----
IMAGE: INFO SECTION 

The Info subsection of the inspector allows you to edit the title and description of the selected item. The Info subsection will only be visible if a single item is selected. 

If the item selected contains multiple data items, like a layered line plot for example, changing the title and description of the item will not affect the names and descriptions of each data item; it will change the title and description for the combined display item.

.. _Image Display Inspector Section:

Image Display
-------------
IMAGE: IMAGE DISPLAY SECTION 

Image Display allows you to force an image to be displayed as a line plot or as script instead of the default.

.. _Image Data Inspector Section:

Image Data
----------
IMAGE: IMAGE DATA SECTION 

Image Data presents several figures and settings for a selected image:

* Date - Displays the date and time a selected image was created.
  
* Data - Displays the dimensions of the image and the bit count.

* Data Range - Displays the minimum and maximum values of the selected data.
  
* Display Limits - Change the minimum and maximum values currently shown in the selected data. Editing these is the same as zooming in or out on an interval on the Histogram.
  
* Color Map - Change the color of the data. The data range is mapped to a range of colors. Choose from a list of preset color profiles. Grayscale is the default.
  
* Brightness - Change the brightness of the color values on the color map. Moving the slider to the right will increase the brightness and moving the slider to the left will decrease the brightness.
  
* Contrast - Change the range of color values on the color map. Moving the slider to the right will increase the contrast and moving the slider to the left will decrease the contrast.
  
* Adjustment - Change the equalization of the selected data. Choose between Equalized, Gamma, Log, or no adjustment.

.. _Line Plot Inspector Section:

Line Plot Display
-----------------
IMAGE: LINE PLOT DISPLAY SECTION 

Line Plot Display presents several figures and settings for a selected line plot:

* Display Type - Force the selected line plot to display as an image or script.

* Display - Change the range of y values shown on the line plot. These values are set to automatically calculate by default, but changing them allows you to zoom into a specific section on the line plot.

* Channels - Change the range of x values shown on the line plot. These values are set to automatically calculate by default, but changing them allows you to zoom into a specific section on the line plot. Changing the channel values is similar to zooming into an interval on the line plot with an interval graphic.

* Log Scale Y - Set the y axis to scale logarithmically.

* Legend Position - Choose the position of the legend for a layered line plot. Line plots with no layers will not show a legend. 

.. _Data Info Inspector Section:

Data Info
---------
IMAGE: DATA INFO SECTION 

Data Info displays the date and time a selected line plot was created. It will also display the dimensions of the line plot and the bit count. For line plots with multiple layers, each data item in the stack will have its own Data Info section.

.. _Calibrations Inspector Section:

Calibrations
------------
Calibrations allow you to make specific changes to the scale and position of a selected item. Images and line plot displays have different features in the calibrations subsection.

Image Calibrations
++++++++++++++++++
IMAGE: IMAGE CALIBRATIONS 

When an image is selected, use the calibrations subsection to

* Change the offset, scale, and units on the y and x axes. The default units for images is nanometers (nm).

* Change the intensity and scale of the selected image.

* Change the coordinate system. This will also change how the cursor position over a display item is shown in the Info panel. See :ref:`data-items` for more information.

Line Plot Calibrations
++++++++++++++++++++++
IMAGE: LINE PLOT CALIBRATIONS 

When a line plot is selected, use the calibrations subsection to

* Change the offset, scale, and units of the x axis (Channel).

* Change the coordinate system. This will also change how the cursor position over a display item is shown in the Info panel. See :ref:`data-items` for more information.

.. _Session Inspector Section:

Session
-------
IMAGE: SESSION SECTION 

The Session subsection of the inspector allows you to change the session info for the selected item. Editing session info in the inspector will not change global session info. To change global session info, use the Session utility panel.

.. _Computation Inspector Section:

Computation
-----------
IMAGE: COMPUTATION SECTION 

With the Computation subsection of the inspector, you can quickly adjust several variables for a computation associated with the selected item. If the selected item has no associated computations, the Computation subsection will say “None.” 

The variables in this subsection will change based on what kind of computation is selected. For example, a line profile will have adjustments for the coordinates of each end of the line, the angle of the line, and the length and width of the line; whereas a processing filter like a gaussian blur may only have a single slider to adjust the sigma (or blur) value.

The Computation subsection can also be accessed in a separate pop-up window by hitting [ctrl + E] (or [cmd + E] on macOS). 

IMAGE: COMPUTATION POP UP 

.. _Layers Inspector Section:

Line Plot Display Layers
------------------------
IMAGE: LINE PLOT DISPLAY LAYERS SECTION 

With this subsection, you can manage all aspects of the layers in a layered line plot. With the layered line plot selected, you can

* Change the order of layers using the up and down arrow buttons under the layer number.

* Add or remove layers with the plus and minus buttons to the right of the arrow buttons.
* Associate layers with data items in the stack using the text box labeled “Data Index.” Type the number of the data item as it appears in the stack. The first data item will be called “Data #0,” the second will be called “Data #1,” and so on. Type 0 or 1 into the text box to associate the layer with Data #0 or Data #1 respectively.

* Choose which row of a data item to show. If a data item has multiple rows, use the “Row” text box to choose which one is shown. Like data items, the row numbering will start at 0 and count up.

* Change the fill color and stroke color using the color or text boxes under each layer's section.

 * Input colors with text like rgb(100, 50, 200), #55AAFF, or a web-defined color like “Blue”
  
 * Choose colors with the color selection panel by clicking on the color box next to “Fill Color” or “Stroke Color.”

 * Input transparent colors with text like rgb(100, 50, 200, .5) or #55AAFF80.

 * Change the transparency of a color using the opacity sliders at the bottom of the color selection panel.

 * Choose no color by deleting any text from the text box next to “Fill Color” or “Stroke Color.” The text box will show a gray “None.”

* Change the stroke width by typing a number into the “Stroke Width” text box. This will create an outline of the stroke color around the associated layer.

.. _Graphics Inspector Section:

Graphics
--------
IMAGE: GRAPHICS SECTION 

The Graphics subsection shows options for selected graphics, or for graphics associated with the selected data item. If multiple graphics are selected, the inspector will not list options for graphics that are not selected.

Each graphic will have different variables that can be changed in this subsection. Most of the variables can either be manipulated by text in the inspector panel or by moving points around in the display panel. The inputs and outputs for the variables will be based off of the coordinate system selected in the calibration drop-down. See :ref:`data-items` for information on different types of coordinate systems. 

Each graphic will have some or all of the following variables:

* Name - The name of the selected graphic. To show no name on a graphic, remove all text from the name text box. The box will show a gray “None.”

* X, Y - The center coordinate of a graphic in nanometers (nm), pixels, or a decimal fraction depending on the coordinate system selected.

* X0, Y0 and/or X1, Y1 - The coordinates of anchor points or vertices of a graphic in nanometers (nm), pixels, or a decimal fraction depending on the coordinate system selected.

* W, H - The width and height of a graphic in nanometers (nm), pixels, or a decimal fraction depending on the coordinate system selected.

* L - The length of a graphic in nanometers (nm), pixels, or a decimal fraction depending on the coordinate system selected.

* A - The angle of a graphic in degrees. Angle inputs over 180 degrees will be automatically reformatted into the equivalent negative angle. For example, an input of 225 degrees in the text box will be reformatted as -135 degrees.

* Rotation - The rotation of a graphic in degrees around its center point.

* Start/End - The end points of a graphic on a line plot in nanometers (nm), pixels, or a decimal fraction depending on the coordinate system selected.

* Radius 1 - The outer radius of a ring mask in nanometers (nm), pixels, or a decimal fraction depending on the coordinate system selected.

* Radius 2 The inner radius of a ring mask in nanometers (nm), pixels, or a decimal fraction depending on the coordinate system selected.

* Mode - The type of ring mask. See :ref:`graphics` for more information on ring masks.

* Start Angle - The top left inside angle of a wedge mask in degrees.

* End Angle - The inside opposite angle of a wedge mask in degrees.

* Display - The type of coordinate system used to label the coordinates on the image or line plot. See :ref:`data-items` for information on different types of coordinate systems.

.. _Metadata Panel:

Metadata
========
The Metadata utility panel shows any metadata associated with the selected data item. The session info will be added as metadata to any live data acquired during a given session.

.. _Output Panel:

Output
======
The Output panel displays output text at the bottom of the window while running Nion Swift. This is useful for debugging the application.

.. _Sessions Panel:

Sessions
========
IMAGE: SESSIONS PANEL 

The Session panel allows you to edit the session info for the whole project rather than for a single data item. The session info will be added as metadata to any live data acquired during a given session. A new session starts and global session info resets every time the Nion Swift is closed.

.. _Task Panel:

Task Panel
==========
The Task panel allows you to see the output from tasks such as microscope tuning. The output is often arranged into a table of data.

.. _Tool Panel:

Toolbar
=======
The Toolbar provides quick access to several options for the workspace. You can select items, move images, add graphics, create masks, choose image scale options, and edit the layout and content of display panels.
 IMAGE: TOOLBAR 

.. _Recorder Dialog:

Recorder
========
.. records a data item, useful during live acquisition or adjustments
.. interval, number of frames
.. what does it produce?

The Recorder dialog allows you to record data at regular intervals from the display item selected when you open the recorder.

To record acquisition, click on the live acquisition display panel. Then open the Recorder dialog. Enter the desired interval (in milliseconds) and the number of items to record. Then click Record. The resulting data item will be a sequence of data sampled from the live data at regular intervals.

.. _Notifications Panel:

Notifications
=============
.. displays notifications, must be dismissed, global

The Notification dialog allows you to see notifications about errors and other important information that occurs while running the software.

The dialog will open automatically in the last location if a notification occurs. You must dismiss the notification and close the dialog.
