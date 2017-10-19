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
* Data Displays
    * Display Panels
    * Images
    * Line Plots
* Data
    * :ref:`coordinate-systems`
    * Collections
    * Sequences
* Tool Panels
    * Info
    * Histogram
    * Inspector
    * Sessions
    * Metadata Editor
    * Tools
* Data Management
    * Importing/Exporting
    * Recorder
    * Acquisition
* Graphics and Processing
    * Graphics
    * Processing

.. _python-scripting:

Python Scripting
----------------

Learning Python
+++++++++++++++
We assume that you are familiar with Python programming, syntax, and usage. If you're new to Python, consider the book
`Think Python <http://www.greenteapress.com/thinkpython/>`_, available for free on the web or for a small charge on
Amazon. The `Hitchhikers Guide to Python <http://docs.python-guide.org/en/latest/>`_ also provides some practical
information and tutorials on getting started.

Getting Started
+++++++++++++++
If you're new to Nion Swift Python scripts, start here.

    * :ref:`python-console` - Run Python from a command line console
    * :ref:`scripting-guide` - A guide with common scripting examples

Getting Help
++++++++++++
You can contact us using the email address `swift@nion.com <mailto:swift@nion.com>`_. Sending email to that address will
go straight to the developers and we will respond via email. We can also provide contact information for instant message
sessions.

More Scripting Resources
++++++++++++++++++++++++
The *Nion Swift API* gives access to the user interface and data. It is intended to be stable, meaning that applications
written using the API will remain valid and function the same in the future, independent of changes to Nion Swift
itself.

There are many ways to access the API and extend Nion Swift using Python:

    * :ref:`concepts-guide` - Use scripting concepts
    * :ref:`python-console` - Run Python from a command line console
    * :ref:`python-interactive` - Run files that interact with the user
    * Computed Data Items - Short Python scripts to update data when sources change
    * :ref:`python-external` - External access via PyCharm, iPython/Jupyter, or command line
    * :ref:`python-extensions` - Customized extensions using Python packages and modules
    * Open Source Development - Main source code for Nion Swift
    * :ref:`api-architecture` - A minimal API overview
    * :ref:`api-reference` - API Reference docuemntation

Indices and Tables
==================

Contents
--------
.. toctree::
    installation
    release_notes
    basic_use
    coordinates
    python_console
    python_interactive
    python_external
    python_extensions
    api/api_index
    :maxdepth: 1
    :caption: Contents:

Links
-----
* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
