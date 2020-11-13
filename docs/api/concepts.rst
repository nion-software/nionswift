:orphan:

.. _concepts-guide:

Scripting Concepts
==================

Nion Swift API
--------------
The Nion Swift API allows developers the ability to control and extend Nion Swift and its extensions and plug-ins.

The API is a versioned API. This allows developers to write to a specific version of the API and know that their
scripts and extensions will work across different versions of Nion Swift that support their required API version.

.. note::
    Until Nion Swift reaches version 1.0, the API may change slightly. We will do our best to keep it stable and
    backwards compatible until then, though.

For detailed class and method references, see :ref:`api-architecture`.

Understanding Data Items, Data, and Metadata
--------------------------------------------

What is a Data Item?
++++++++++++++++++++
The library stores :dfn:`data items`, which are objects comprised of data (in the form of an ``ndarray``), metadata
(a Python :samp:`dict`), calibrations, and other components such as overlay :samp:`Graphics` and :samp:`Displays`.

The library also uses :samp:`DataAndMetadata` objects as a convenient structure to pass the combination of data,
metadata, and calibrations as arguments.

The library maintains connections/relationships between data items and other objects. For instance, the data in one
data item may be computed by applying a processing operation to the data in another data item.

.. _concepts-threads:

Threads
-------
Python includes the ability to run code on threads. While you may not directly using threads yourself, it is important
to understand how threading affects Nion Swift performance for each particular scripting environment such as the Console
windows or access from external programs.

Threads in Python will utilize additional processors, but with the limitation that for most Python code, only a single
Python instruction is being run at any given time. The exception is calls to processing or data acquisition functions
that explicitly tells the Python interpreter that it is OK to run other instructions. Specific examples include many
`numpy` processing functions, functions that wait on disk I/O or web I/O, and functions that acquire data from hardware
instrumentation.

One of the primary concepts is that Nion Swift has a user interface (UI) thread. The UI thread is important because it
handles interaction with the user. It is important to avoid running Python code on the UI thread that takes more than
20ms. Any code taking longer than 20ms should be put into its own thread.

Another primary concept is that much of the API is only available from the UI thread. For instance, adding a data item
to the document must be done on the UI thread. Fortunately, this is a fast operation and can easily be done in less than
20ms.

The various scripting environments are set up to handle threads in different ways.

Console
+++++++
Python scripts in the console windows run on the UI thread. Most API functions are safe to call from the console.

Some operations that you run in the console may take longer than 20ms, but this is usually OK since you're running them
directly and usually OK with trading off UI responsiveness for directness. However, you should be aware that other
processes such as acquisition that run require the UI thread will be paused while your console script is running.

In addition, you must be careful not to call functions that wait on other UI thread events to occur. For instance, you
might be tempted to call a function which waits for data to arrive from a particular camera. However, for that data to
arrive, the UI must first handle updating the data from the camera. But since your console script is already waiting on
the UI thread, the data never updates. This is called a deadlock and the only way out of it (currently) is to force Nion
Swift to exit and restart.

If you need to call a function that must wait for something else on the UI, you will need to put it into its own thread.
However, a function running on a thread has a similar limitation in that it cannot call API functions that are required
to be run on the UI thread. ::

    def acquire_one(camera):
        t = camera.create_record_task()
        d = t.grab()
        # show(d)  # not legal, not threadsafe

    import threading
    threading.Thread(target=acquire_one, args=[camera]).start()

Some functions are thread safe, and some of those are thread required (must be run on a thread). For instance,
``camera.grab_next_to_finish`` is thread safe but it will also run on the UI thread in most cases (you should pass a
timeout for the case where the camera has an error). On the other hand, ``record_task.grab()`` is thread safe but
_cannot_ run on the UI thread since it will deadlock. This information is documented in the API reference.

See :ref:`concepts-guide`.

Interactive Scripts
+++++++++++++++++++
Python scripts in the interactive windows run on the their own thread. However, most API functions are still safe to
call from interactive scripts because they are *marshalled* to the UI thread when they are called, which means the
interactive window temporarily suspends its execution until the API call completes.

See :ref:`interactive-guide`.

External Scripts
++++++++++++++++
External scripts, such Jupyter notebook or others using ``nionlib`` to call functions in Nion Swift, are running in an
entirely separate Python environment. When they call API functions, the API functions will be run in Nion Swift on the
UI thread unless otherwise noted in the API reference.

See :ref:`python-external`.

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
