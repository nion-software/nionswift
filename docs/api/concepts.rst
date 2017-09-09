.. _concepts-guide:

Scripting Concepts
==================

For detailed class and method references, see :ref:`api-architecture`.

Understanding Data Items, Data, and Metadata
--------------------------------------------

What is a Data Item?
^^^^^^^^^^^^^^^^^^^^
The library stores :dfn:`data items`, which are objects comprised of data (in the form of an ``ndarray``), metadata
(a Python :samp:`dict`), calibrations, and other components such as overlay :samp:`Graphics` and :samp:`Displays`.

The library also uses :samp:`DataAndMetadata` objects as a convenient structure to pass the combination of data,
metadata, and calibrations as arguments.

The library maintains connections/relationships between data items and other objects. For instance, the data in one
data item may be computed by applying a processing operation to the data in another data item.
