.. _api-architecture:

API Architecture
================

This page describes the objects used to access Nion Swift and how they relate to one another.

For a basic introduction to scripting, see :ref:`scripting-guide`.

For detailed API reference, see :ref:`api-reference` or click on the classes described below.

API Object
----------

The API is accessed through an API class.

:py:class:`API <nion.swift.Facade.API_1>`
    The API object gives access to the other objects.

Data Model
----------
The Nion Swift data model is comprised of several objects which are persistent and stored to disk.

:py:class:`Library <nion.swift.Facade.Library>`
    The library holds a collection of data and a description of how that data fits together.

:py:class:`DataItem <nion.swift.Facade.DataItem>`
    An item saved to a file on disk that contains a data array, calibrations, metadata, display information, operations,
    and more.

:py:class:`Graphic <nion.swift.Facade.Graphic>`
    A graphic overlay object.

:py:class:`DataGroup <nion.swift.Facade.DataGroup>`
    A group of data items, ordered, and defined by the user.

Auxiliary Classes
-----------------
The API uses several auxiliary data types.

Data Array
    A low level NumPy ndarray.

Metadata
    Information about a ``Data Array``, in the form of a dict. Includes calibration, regions, displays, and other data
    such as title and caption. Metadata is structured data and we recommend that you contact Nion for guidance on how to
    use metadata.

Calibration
    A calibration for a single dimension with ``offset``, ``scale``, and ``units``. See
    :py:meth:`~nion.swift.Facade.API_1.create_calibration`.

DataAndMetadata
    A read only object representing the combination of a Data Array and Metadata. See
    :py:meth:`~nion.swift.Facade.API_1.create_data_and_metadata`.

User Interface
--------------
The Nion Swift user interface classes represent what the user sees in the Nion Swift application. It is distinct from
the individual elements that make up the low level details of the user interface.

:py:class:`Application <nion.swift.Facade.Application>`
    The root object representing the Application. Contains a collection of document controllers and the library.

:py:class:`DocumentWindow <nion.swift.Facade.DocumentWindow>`
    An object representing a window with display panels.

:py:class:`DisplayPanel <nion.swift.Facade.DisplayPanel>`
    A display panel within a window. Maybe contain a data item or a browser of data items or other things.

Instrument Control and Data Collection
--------------------------------------
There are a few classes which allow you to control instruments and collect data.

:py:class:`HardwareSource <nion.swift.Facade.HardwareSource>`
    An object that generates data.

:py:class:`Instrument <nion.swift.Facade.Instrument>`
    An object that controls hardware.

:py:class:`RecordTask <nion.swift.Facade.RecordTask>`
    An object representing a Record data task.

:py:class:`ViewTask <nion.swift.Facade.ViewTask>`
    An object representing a live data View.

User Interface Elements
-----------------------
There are many low level object which allow you to construct a user interface.

.. note::
    TODO: Describe user interface objects
