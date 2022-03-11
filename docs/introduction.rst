.. include:: defs.rst
.. _introduction:

********
Overview
********
Nion Swift is an image processing software for controlling instruments, and managing the acquisition, organization, visualization, and analysis of data. The software was designed to be used in conjunction with Nion's electron microscopes, but the functionality and the ability to extend its capabilities using Python mean that Nion Swift is useful for any number of data visualization projects. Whether you already have your data, or you want to see the data as it is acquired, Nion Swift helps you visualize your data in exactly the way you want.

Click to download Nion Swift or for :ref:`installation` instructions.

Click here to get started fast with our :ref:`basic-use`.

User Interface
==============
The user interface is split up into a central section of the window called the workspace and the surrounding area for utility panels. 

The central workspace is for display panels which can either display a single piece of data (also called a data item) or can display multiple pieces of data side by side in one of the browser formats. For more information, see :ref:`display-panels`.

The utility panels surrounding the central workspace allow you to make adjustments to a selected data item in a display panel. For more information on their specific functions, see :ref:`user-interface`.

Data and Display
================
A piece of data stored in the program is called a data item. Data items can be dragged into display panels to be displayed. Once displayed, they become display items. Display items can be modified and viewed to see various aspects or values of the original data item. Read more in :ref:`data-items`.

If a data item includes complex components, it will need to be reduced into a scalar image or line plot in order to be displayed. For more info, see :ref:`data-items`.

Sometimes, data items can be part of a larger 'stack' of data which will require higher level organization that the data panel can provide. See :ref:`data-items` for more info.

The INFO PANEL shows you the location and value of the data in a display panel under your cursor. You can choose how you would like the :ref:`data-items` (coordinate system) to be defined in the inspector panel.

Click on any data item, display panel, or graphic to select it. You can select more than one item of the same kind using [ctrl + click] on Windows or [cmd + click] on macOS. 

Selecting more than one display panel will display with a solid blue rectangle around the primary selection and with dashed lines around the secondary selections. If a computation or function can only use one input, the primary selection will be used. For computations using multiple inputs, secondary selections may be used as well.

Selecting multiple data items will allow you to move them at the same time. However, multiple data items cannot be dragged into the same display panel.

Selecting multiple graphics in the same display panel will allow you to move them at the same time. The inspector panel will display options for all of the selected graphics.

Graphics and Masks
==================
Nion Swift provides plenty of useful graphics to narrow down your view of the data. Use graphics to highlight portions of the data, select areas for processing, or to focus on specific sections of data.

Masking allows you to block out the rest of an image and see only what you want. Choose from a variety of mask shapes to precisely define your area of interest.

See :ref:`graphics` for more information.

Processing and Analysis
=======================
Processing and analysis greatly expand the functionality of Nion Swift. The software provides many options for filtering, transforming, and more. Computations allow for specific and customizable processes, and there is even support for python scripting to add your own computations.

See :ref:`processing` for more information.

File Management
===============
Make use of Nion Swift without live acquisition by importing your own data files into the program, take your files with you by exporting your data, save your project files and use them on any other installation of Nion Swift, make copies of your data to create a backup, and contact us about recovery options.

See :ref:`data-management` for more information.
