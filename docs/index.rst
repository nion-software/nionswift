.. _index:

Nion Swift User's Guide (v0.11.0)
=================================
Nion Swift is open source scientific image processing software integrating hardware control, data acquisition,
visualization, processing, and analysis using Python. Nion Swift is easily extended using Python. It runs on
Windows, Linux, and macOS.

Nion Swift is being developed for the operation of Nion electron microscope instruments. It is also useful as an
offline tool to visualize, process, and analyze data from the Nion instruments. It is being developed with the
intention of supporting additional instrumentation and fields.

Nion Swift is provided as an open source project. You can find the source code on
`GitHub Nion Swift <https://github.com/nion-software/nionswift/>`_.

Nion Swift should currently be considered **beta** level software.

Installation
------------
To install Nion Swift, you will need to install a Python environment with some specific Python packages. When you
initially launch the application, it will ask you for the directory of that Python environment.

For specific installation details and download links, see the installation link below. Instructions to install
additional packages to extend Nion Swift are also covered in that link.

* :ref:`installation`
* :ref:`release-notes`

Using Nion Swift
----------------
Nion Swift stores its data on disk as a *library*. You interact with Nion Swift using *workspaces* which display
one or more individual *data items* within the library. The *data panel* and *browsers* allow you to choose which
items from the library are displayed in the current workspace.

* :ref:`basic-use`

Data Displays
-------------
* Display Panels
* Images
* Line Plots

Data
----
* :ref:`coordinate-systems`
* Collections
* Sequences

Tool Panels
-----------
* Info
* Histogram
* Inspector
* Sessions
* Metadata Editor
* Tools

Data Management
---------------
* Importing/Exporting
* Recorder
* Acquisition

Graphics and Processing
-----------------------
* Graphics
* Processing

Python Scripting
----------------
* :ref:`python-scripting`
* :ref:`python-console`
* :ref:`python-interactive`
* Computations
* :ref:`python-external`
* :ref:`python-extensions`
* :ref:`api-index`

.. toctree::
    installation
    release_notes
    basic_use
    coordinates
    python_scripting
    python_console
    python_interactive
    python_external
    python_extensions
    api/api_index
    :maxdepth: 1
    :caption: Contents:

Indices and Tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
