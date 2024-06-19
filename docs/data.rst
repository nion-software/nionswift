.. include:: defs.rst
.. _data-items:

Data and Displays
=================
This section describes the distinction between data items and display items in |AppName|.

Data Items
----------
|AppName| primarily operates on data arrays such as 2D images and 1D spectra, which are generally called *Data Items*.

The data in a data item may be organized into collections. For instance, a sequence of two dimensional images, or a two dimensional collection of one dimension spectra.

The data in a data item may be stored as floating point numbers, integer numbers, complex numbers, or as RGB or RGBA values.

A data item also stores metadata about the data. The metadata includes a title and description; the grouping of dimensions into data, collections, and sequences; dimensional and intensity calibrations; and creation and modification timestamps including time zone information. There may be other metadata stored as key-value pairs in more free-form manner.

Display Items
-------------
Display items represent a view of one or more data items and can be edited separately its associated data items.

A display item keeps track of how to display the data in a data item. For instance, the color table used to show an image or the range of data shown in a line plot.

A data item can often represent more data than can be shown in a single display. For example, a sequence of 2D images can only sensibly display one of those images at once.

A display item ultimately must reduce complicated data to a single 2D image or 1D plot. For example, it keeps track of which index of a sequence of images is shown, similar to how a movie shows only a single frame at time. Display items keep track of similar data reductions for other types of collections and data types.

Display items may be associated with just a single data item, such as when the data is a 2D image. However, data items may also be associated with multiple data items, such as when multiple 1D data items are displayed on a single line plot.

Display items include their own title and description. If these are empty, the title and description of the first data item is used instead.

Display items are shown in the workspace in display panels. See :ref:`display-panels` and :ref:`user-interface` for more information.

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
In addition to calibrated coordinate systems, |AppName| uses pixel and relative coordinate systems.

The pixel coordinate system spans the size of the data array and can be displayed with the origin at the top-left or the origin at the center.

The relative coordinate system displays fractional coordinates and can be displayed with the origin at the top-left and a range of 0.0 to 1.0 or with the origin at the center a range of -1.0 to 1.0.

The calibrated coordinate system displays calibrated coordinates. The origin is determined by the calibration offset.

Note: when referring to pixels, to be consistent with scripting and Python NumPy coordinates, all coordinate systems increase towards the right and down and indices are ordered such that the slowest changing index in memory is first, i.e. `image[y, x]`.

Collections
-----------
Images and plots (2D and 1D) data can be arranged into collections with one or two dimensions. These are often expressed as 1D x 1D (spectra along a line), 2D x 1D (a spectrum image), 1D x 2D (images along a line), or 2D x 2D (4D STEM).

In addition to collections, 1D or 2D data or 1D or 2D collections of 1D or 2D data can be arranged into sequences. A sequence is roughly equivalent to a 1D collection.

As an example, a sequence of 2D images would be a movie.

But more complex arrangements are possible. It is possible to have a sequence of 2D collections of 2D images, resulting in 5D data: e.g., a recording of 4D STEM images.
