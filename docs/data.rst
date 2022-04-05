.. include:: defs.rst
.. _data-items:

Data and Displays
=================
Data items are a piece of data that contains all values and numerical information for a certain file or instance of live data. They are comparable to files that you would have on your computer. Data items store data.

All data items in a project can be found in the data panel given that the “All” collection is selected in the COLLECTIONS PANEL. The “All” collection is selected by default.

Display Items
-------------
Display items are created when a data item is dragged into an empty display panel. Display items are somewhat separate from data items but still use them as a base. A display item shows the values of the data item as an image or line plot, but then allows for the addition of graphics, changing of colors, and other modifications.

Display items will change the look of the associated data item but not the actual values of the data. It is possible to have the same data item displayed in multiple display panels. Doing this will not allow for different modifications on the same data item, it will only display the same modifications in all of the associated display panels.

Reducing Data for Display
-------------------------
It is possible for a data item in the application to be complex (have more than one value at a given coordinate). In order to display a data item like this, the complex values must be reduced to scalar values. There are two ways to do this:

* Display the data item as a 1D line plot by choosing one x,y coordinate and reading the values at that point.

* Display the data item as a 2D image by choosing one intensity value at each coordinate.

To decide which method for data reduction to use, make sure that the data item in question is selected. Then, using the IMAGE DISPLAY or LINE PLOT subsection in the Inspector Panel, choose the desired display method from the Display Type drop-down.

Calibrations
------------
A data item keeps track of a dimensional calibration for each dimension of the data. In addition, it tracks an intensity calibration for each value in the data.

Calibrations have the form:

`x' = x * scale + offset`

They also have units.

A calibration is empty when scale is one, offset is zero, and units are empty.

Metadata
--------
In addition to the description of the dimension groups and the calibrations, a data item has freeform metadata.

The freeform metadata can be viewed in the Metadata Panel or accessed from scripts. See :ref:`user-interface`.

Coordinate Systems
------------------
Coordinate systems are how the points on an image or a line plot are named. Each point will be given a coordinate of its x (horizontal) value, and its y (vertical) value. They are displayed in the (x,y) format. The various coordinate systems determine where the origin (0,0) is and how the data is split up.

Collections
-----------
Images and plots (2D and 1D) data can be arranged into collections with one or two dimensions. These are often expressed as 1D x 1D (spectra along a line), 2D x 1D (a spectrum image), 1D x 2D (images along a line), or 2D x 2D (4D STEM).

Sequences
---------
In addition to collections, 1D or 2D data or 1D or 2D collections of 1D or 2D data can be arranged into sequences. A sequence is roughly equivalent to a 1D collection.

As an example, a sequence of 2D images would be a movie.

But more complex arrangements are possible. It is possible to have a sequence of 2D collections of 2D images, resulting in 5D data: e.g., a recording of 4D STEM images.
