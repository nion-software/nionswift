.. include:: defs.rst
.. _introduction:

Overview
========
|AppName| is open source scientific image processing software integrating hardware control, data acquisition, visualization, processing, and analysis using Python. |AppName| is easily extended using Python. It runs on Windows, Linux, and macOS.

|AppName| is intended to provide an extensible platform to acquire scientific data from a variety of microscopes and other instruments, be intuitive and easy to use, and allow sophisticated data visualization, processing, and analysis.

Key Features

- Data handling of 1D plots, 2D images, 1D and 2D collections of plots and images, and sequences.
- Live computations that can be chained during acquisition or live parameter adjustment.
- Open source, cross platform (macOS, Windows, Linux), and Python based scientific data processing.
- Low latency, high throughput data acquisition platform.

Data Items and Display Items
----------------------------
|AppName| operates on data arrays, which include 2D images and 1D spectra, which are generally called *Data Items*.

Data items represent data arrays with anywhere from one to five dimensions. The data array associated with a data item can be 1D or 2D data and then organized into 1D or 2D collections or 1D sequences.

A spectrum image would be a 2D collection of 1D data. This would be typical data acquired from a STEM microscope spectrum imaging acquisition.

Data Items are displayed using one or more *Display Items*.

See :ref:`data-items`.

Projects
--------
Data items are organized into projects. Projects are stored on disk and take the form of an index file and an associated data directory.

You can have any number of projects, but only a single one can be open at once. When you open a project, it is associated with a main document window.

See :ref:`data-management`.

Workspaces
----------
The main window is organized around a main area called a workspace. A workspace has a layout which includes one or more display panels in which display items can be visualized.

You can create additional workspace for different uses and easily switch between them.

In addition, the main window has a variety of utility panels attached or associated with the main window. Some examples of utility panels are the data browser panel, the inspector panel, and the info and histogram panels.

See :ref:`user-interface`.

Display Panels
--------------
Workspaces are split into one or more display panels. Each display panel can show one display item.

A typical display item would show a single data item, but you can create multiple display items for each data item to visualize the data differently at the same time.

In addition, some display items may display multiple data items at once: a line plot may have multiple layers, each displaying a different data item or even different reductions of the same data item.

See :ref:`display-panels`.

Computations
------------
Computations are processing algorithms that take input data items and other parameters to produce output data items. The algorithm watches for changes to the input data items and automatically runs the processing when it sees a change.

In this way, it is easy to create new data items that update in real time during acquisition or when the parameters change.

See :ref:`processing`.

Graphics
--------
Graphics are annotations or other graphical items that can be attached to display items.

Examples of graphics would be a point, line, or rectangle on a 2D image or a interval or channel on a 1D plot.

Additionally, Fourier mask filter graphics, such as band pass filters or lattice filters, can be attached to data in the Fourier domain.

See :ref:`graphics`.
