.. include:: defs.rst
.. _data-items:

Data and Displays
=================
|AppName| operates on data arrays, which include 2D images and 1D spectra, which are generally called *Data Items*.

Data items represent data arrays with anywhere from one to five dimensions. The data array associated with a data item can be 1D or 2D data and then organized into 1D or 2D collections or 1D sequences. A data item can store scalar, complex, or RGB data. The scalar data can be integer or real.

A data item also stores both formal and informal metadata about the data. The formal metadata includes a title and description; the grouping of dimensions into data, collections, and sequences; dimensional and intensity calibrations; and creation and modification timestamps including time zone information. The informal metadata includes a freeform Python dict that is JSON compatible.

A data item is displayed in one or more *Display Items*.

Display Items
-------------
Display items represent a view on one or more data items. A display item tracks things like how to translate the data in a 2D image data item to an image in the user interface. It also tracks how to reduce more complex data structures to either a 2D or 1D representation.

Display items are distinct from data items so that you can have multiple views on a particular data item and also so that you can display multiple data items in the same display.

Display items include their own title and description. If these are empty, the title and description of the first data item is used instead.

Display panels show individual display items and also allow you to browse available display items. The data panel shows the list of display items available in the project. See :ref:`display-panels` and :ref:`user-interface` for more information.

Reducing Data for Display
-------------------------
A data item can possibly represent more data than it can display at once. In addition, there may be multiple ways of viewing the data. The process of data reduction reduces all data items to either a 2D image or a 1D plot suitable for display.

For example, a 2D spatial collection of 1D energy spectra (2D x 1D) cannot be displayed without reducing it. There are two obvious ways to reduce the data: either reduce to 1D by choosing a particular x, y coordinate from the collection dimensions; or reduce to 2D by choosing a particular energy at each x, y coordinate.

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
To be consistent with scripting and Python NumPy coordinates, all coordinate systems increase towards the right and down and indices are ordered such that the slowest changing index in memory is first.

The pixel coordinate system displays pixels and can be displayed with the origin at the top-left or the origin at the center.

The relative coordinate system displays fractional coordinates and can be displayed with the origin at the top-left and a range of 0.0 to 1.0 or with the origin at the center a range of -1.0 to 1.0.

The calibrated coordinate system displays calibrated coordinates. The origin is determined by the calibration offset.

Collections
-----------
Images and plots (2D and 1D) data can be arranged into collections with one or two dimensions. These are often expressed as 1D x 1D (spectra along a line), 2D x 1D (a spectrum image), 1D x 2D (images along a line), or 2D x 2D (4D STEM).

Sequences
---------
In addition to collections, 1D or 2D data or 1D or 2D collections of 1D or 2D data can be arranged into sequences. A sequence is roughly equivalent to a 1D collection.

As an example, a sequence of 2D images would be a movie.

But more complex arrangements are possible. It is possible to have a sequence of 2D collections of 2D images, resulting in 5D data: e.g., a recording of 4D STEM images.
