:orphan:

.. _basic-use:

Introduction Tutorial
=====================

Introduction
------------
Nion Swift stores its data on disk as a *library*. You interact with Nion Swift using *workspaces* which display
one or more individual *data items* within the library. The *data panel* and *browsers* allow you to choose which
items from the library are displayed in the current workspace.

Getting Data In and Out
-----------------------
You can drag your own data into Nion Swift. It will copy your data into its own library and will never touch your
original files other than to read them during import.

Nion Swift also provides some sample images that you can view by dragging from the data panel on the left to the large
viewer panel in the center of the window.

Swift accepts many major file types including TIFF, JPEG, PNG, and DM files. We plan to support HDF5 in the future but
that is not yet available.

To get data out of Swift, click on the data item that you want to export and use the File > Export… menu item to save
the file. We suggest saving in the ``NData`` format for now. This is a custom format that saves complete information
associated with a data item in Swift. For those interested, it is a zip file and you can view the contents by treating
it as a zip file.

The NData format can be imported into other Swift installations.

The Data Item Library
---------------------
Swift stores all of your data within the library directory structure that you choose when you first launch. You can
create new libraries, switch to recently used ones, and open existing libraries using the Switch Library sub-menu in the
File menu.

The user interface is comprised of a data viewing area and panels attached to the viewing area. Try changing the layout
of the center panel by dragging data into the layout area. You can easily show multiple images simultaneously.

You can zoom into and out of a particular image by clicking on it and then using the plus and minus keys, arrow keys,
zero, shift-zero, and one keys.

You can hide and show panels using the Window menu.

The Data Panel is shown by default and is used to show what data items (images, spectra, data cubes, etc.) you have
available in the library.

The Info Panel is shown by default at the top right and shows the data under the cursor.

The Inspector Panel is shown by default on the right and shows specific information about the selected data item, either
in the data panel or in one of the view panes in the middle.

The library folder structure should be considered to be private data, so you should **not** drag files into or out of
the directory structure directly. Use the techniques described above instead.
