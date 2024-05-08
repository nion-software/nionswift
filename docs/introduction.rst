.. include:: defs.rst
.. _introduction:

..
    This file is a short introduction to key parts of the application that allow the user to
    understand the high level concepts necessary to use the application. It is structured partially
    as a reference file but also as a how-to guide in the sense of "if I'm using the application,
    what do I need to know and how do I proceed from here?".

Introduction
============
This page is a brief introduction to understanding the high level concepts necessary to use |AppName|.

For an introductory tutorial, see :ref:`basic-use`.

For installation instructions, :ref:`installation`.

User Interface
--------------
The user interface is comprised of two main sections: a central section called the workspace, and the surrounding area for utility panels.

.. image:: graphics/workspace.png
  :width: 320
  :alt: Example of the Swift Workspace

Workspace
^^^^^^^^^
The central workspace is organized into display panels which can either display a single data item or thumbnail images of multiple data items in one of the browser formats. For more information, see :ref:`display-panels`.

Utility Panels
^^^^^^^^^^^^^^
The utility panels surrounding the central workspace allow you to make adjustments to a selected data item in a display panel. For more information on their specific functions, see :ref:`user-interface`.

Data Items and Display Items
----------------------------
|AppName| primarily operates on data arrays such as 2D images and 1D spectra, which are generally called *Data Items*.

Data is stored in a project as data items. Data items can be dragged into display panels to be displayed. Data items that are displayed in a display panel can be annotated with graphics, processed with computations, and more. These displayed data items are referred to as display items.

See :ref:`data-items`.

Graphics and Masks
------------------
Graphics are used to highlight portions of the data, select areas for processing, focus on specific sections of data, or otherwise annotate the data.

Masking allows you to block out part of an image and manipulate only a specific section of the data. You can use a preset mask or add graphics to a mask to precisely define your area of interest.

See :ref:`graphics`.

Processing and Analysis
-----------------------
|AppName| can perform processing and analysis on data by running computations, running Python scripts, filtering data, and more.

See :ref:`processing` for more information.

Projects
--------
|AppName| organizes data and other items into projects that are stored on your computer, similar to a folder. The project tracks relationships between items in the project.

All data items are stored in a project. Only one project can be open at a time.

You can add data to projects by importing data files or using |AppName| to acquire data from acquisition devices.

See :ref:`data-management`.
