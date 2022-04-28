.. include:: defs.rst
.. _introduction:

********
Overview
********
Nion Swift is open source scientific image processing software for controlling instruments, and managing the acquisition, organization, visualization, and analysis of data. The software is designed to be used in conjunction with electron microscopes. However, it is also useful in other data visualization applications. Nion Swift helps you visualize your data both while it is being acquired and during processing and analysis.

Click to download Nion Swift or for :ref:`installation` instructions.

Click here to get started fast with our :ref:`basic-use`.

User Interface
==============
The user interface is comprised of two main sections: a central section called the workspace, and the surrounding area for utility panels.

.. image:: graphics/workspace.png
  :width: 320
  :alt: Example of the Swift Workspace 

The central workspace is for display panels which can either display a single data item or thumbnail images of multiple data items in one of the browser formats. For more information, see :ref:`display-panels`.

The utility panels surrounding the central workspace allow you to make adjustments to a selected data item in a display panel. For more information on their specific functions, see :ref:`user-interface`.

Data and Display
================
Data is stored in a project as data items. Data items can be dragged into display panels to be displayed. Data items that are displayed in a display panel can be annotated with graphics, processed with computations, and more. These displayed data items are referred to as display items. 

Read more in :ref:`data-items`.

Graphics and Masks
==================
Use graphics to highlight portions of the data, select areas for processing, or focus on specific sections of data.

Masking allows you to block out part of an image and manipulate only a specific section of the data. Use a preset mask or add graphics to a mask to precisely define your area of interest.

See :ref:`graphics` for more information.

Processing and Analysis
=======================
Processing data by adding line profiles to an image, running Python scripts, filtering data, etc. can give you deeper insight into your data. Use the :ref:`inspector panel` to adjust processing settings. Customizing processing allows for easier and more specific analysis of data.

See :ref:`processing` for more information.

Projects and File Management
============================
Imported and gathered data items are stored as a project in the form of an index file on your computer. Projects can be transferred just like any other file and can be opened in other installations of Nion Swift provided the versions are compatible.

Import data into a project by dragging a data file into the workspace or by using the menu item [File > Import Data…]. Export data by using the menu item [File > Export…].

See :ref:`data-management` for more information.
