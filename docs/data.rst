.. include:: defs.rst
.. _data-items:

Data and Displays
=================
Data items are a piece of data that contains all values and numerical information for a certain file or instance of live data. They are comparable to files that you would have on your computer. Data items store data.

All data items in a project can be found in the data panel given that the “All” collection is selected in the COLLECTIONS PANEL. The “All” collection is selected by default.

Data Items
----------
Data items are a piece of data that contains all values and numerical information for a certain file or instance of live data. They are comparable to files that you would have on your computer. Data items store data.

All data items in a project can be found in the data panel given that the “All” collection is selected in the COLLECTIONS PANEL. The “All” collection is selected by default.

Display Items
-------------
Display items are created when a data item is dragged into an empty display panel. Display items are somewhat separate from data items but still use them as a base. A display item shows the values of the data item as an image or line plot, but then allows for the addition of graphics, changing of colors, and other modifications.

Display items will change the look of the associated data item but not the actual values of the data. It is possible to have the same data item displayed in multiple display panels. Doing this will not allow for different modifications on the same data item, it will only display the same modifications in all of the associated display panels.

Selections
----------
Click on any data item, display panel, or graphic to select it. You can select more than one item of the same kind using [ctrl + click] on Windows or [cmd + click] on macOS. 

Selecting more than one display panel will display with a solid blue rectangle around the primary selection and with dashed lines around the secondary selections. If a computation or function can only use one input, the primary selection will be used. For computations using multiple inputs, secondary selections may be used as well.

Selecting multiple data items will allow you to move them at the same time. However, multiple data items cannot be dragged into the same display panel.

Selecting multiple graphics in the same display panel will allow you to move them at the same time. The inspector panel will display options for all of the selected graphics.

Reducing Data for Display
-------------------------
It is possible for a data item in the application to be complex (have more than one value at a given coordinate). In order to display a data item like this, the complex values must be reduced to scalar values. There are two ways to do this:

* Display the data item as a 1D line plot by choosing one x,y coordinate and reading the values at that point.

* Display the data item as a 2D image by choosing one intensity value at each coordinate.

To decide which method for data reduction to use, make sure that the data item in question is selected. Then, using the IMAGE DISPLAY or LINE PLOT subsection in the Inspector Panel, choose the desired display method from the Display Type drop-down.

Calibrations
------------
Each data item stores a dimensional calibration for each dimension it contains. It also stores an intensity calibration for the values in the data. You can edit calibrations in the CALIBRATIONS subsection of the inspector panel.

Metadata
--------
Data items store metadata for various markers and identifiers. For example, metadata about when a data item was created will be stored. Keywords in metadata can be used to search for data items in the data panel search bar. Metadata can also be used as a variable in Python scripts. To view metadata, you can use the METADATA panel.

Coordinate Systems
------------------
Coordinate systems are how the points on an image or a line plot are named. Each point will be given a coordinate of its x (horizontal) value, and its y (vertical) value. They are displayed in the (x,y) format. The various coordinate systems determine where the origin (0,0) is and how the data is split up.

Image Coordinate Systems
------------------------
**Calibrated** - Ranges with the changed values in the CALIBRATIONS subsection of the inspector panel.

**Pixels (Top Left)** - The top left of the image is (0,0) and the bottom right is the maximum height and width of the image.

**Pixels (Center)** - The middle of the image is (0,0) with the image being split into four quadrants.

* Top left (-,-)
* Bottom left (-,+)
* Bottom right (+,+)
* Top right (+,-)

**Fractional (Top Left)** - The top left of the image is (0,0) and the bottom right is (1,1). Values in between will be displayed as decimal fractions like (0.5,0.5).

**Fractional (Center)** - The middle of the image is (0,0) with the image being split into four quadrants. Values in between will be listed as decimal fractions like (0.5,0.5).

* Top left (-1,-1)
* Bottom left (-1,+1)
* Bottom right (+1,+1)
* Top right (+1,-1)

Line Plot Coordinate systems
----------------------------
Changing the coordinate system for a line plot will only change the values on the x axis. The y axis and values will remain the same.

**Calibrated** - Ranges with the changed values in the CALIBRATIONS subsection of the inspector panel.

**Pixels (Top Left)** - The x axis increases to the right from 0 to the maximum value of the data.

**Pixels (Center)** - The middle of the x axis is 0 with negative x values to the left and positive x values to the right.

**Fractional (Top Left)** - The x axis increases to the right from 0 to 1. X values in between will be displayed as a decimal fraction like 0.5.

**Fractional (Center)** - The middle of the x axis is 0 with negative 1 to the far left and positive 1 to the far right. X values in between will be displayed as a decimal fraction like 0.5.

Collections
-----------
Sometimes a data item can have multiple 'instances' of data in sequence. For example, data gathered from a microscope over time might contain multiple images. Usually, we think of many images in sequence as a movie. Nion Swift can work with differently-dimensional data. Multi-dimensional data items are referred to as “collections” if they contain 1 or 2 dimensions and as “sequences” if they are higher-dimensional. This is not to be confused with the COLLECTIONS PANEL which serves the function of organizing data items into separate folders. The terms "collection" and "sequence" are not typical in reference to this. More common terms are "navigation" and "signal."

