.. _api-index:

Nion Swift API
==============
The Nion Swift API allows developers the ability to control and extend Nion Swift and its extensions and plug-ins.

The API is a versioned API. This allows developers to write to a specific version of the API and know that their
scripts and extensions will work across different versions of Nion Swift that support their required API version.

.. note::
    Until Nion Swift reaches version 1.0, the API may change slightly. We will do our best to keep it stable and
    backwards compatible until then, though.

How do I start?
---------------
1. Read the introduction in :ref:`python-scripting`.
2. Review the :ref:`concepts-guide`.
3. Follow the :ref:`scripting-guide`.
4. See the list of classes, methods, properties :ref:`api-quick`.

Where do I go from here?
------------------------
1. Explore the :ref:`hardware-guide`.
2. Write interactive scripts :ref:`interactive-guide`.
3. Write your own plug-in using :ref:`plugins-guide`.
4. Read about :ref:`xdata-guide`.
5. Browse the :ref:`api-reference`.
6. Develop with :ref:`userinterface-guide`.

API Notes
---------
Versions numbering follows `Semantic Version Numbering <http://semver.org/>`_.

:samp:`on_xyz` methods are used when a callback needs a return value and has only a single listener.

:samp:`xyz_event` methods are used when a callback is optional and may have multiple listeners.

Nion Swift uses c-indexing for NumPy (fastest changing index in memory is last). This means that sizes are usually
specified in height, width and coordinates are specified in :samp:`y, x`.

Coordinates used with overlay graphics are specified in data-relative coordinates, which means that the values range
from 0.0 to 1.0 for each dimension with 0.0, 0.0 being the top left corner.

Two dimensional points are represented as :samp:`y, x`. Three dimensional points are represented as :samp:`z, y, x`.

Two dimensional sizes are represented as :samp:`height, width`.

Rectangles are specified by the tuple :samp:`top_left, size` where :samp:`top_left` is a point and :samp:`size` is a
size.

Table of Contents
-----------------

.. toctree::
   :maxdepth: 2

   concepts
   scripting
   hardware
   interactive
   userinterface
   extended_data
   plugins
   architecture
   quick
   reference
