.. _introduction:

Introduction to Scripting
=========================

Learning Python
---------------
We assume that you are familiar with Python programming, syntax, and usage. If you're new to Python, consider the book
`Think Python <http://www.greenteapress.com/thinkpython/>`_, available for free on the web or for a small charge on
Amazon. The `Hitchhikers Guide to Python <http://docs.python-guide.org/en/latest/>`_ also provides some practical
information and tutorials on getting started.

Getting Help
------------
You can contact us using the email address `swift@nion.com <mailto:swift@nion.com>`_. Sending email to that address will
go straight to the developers and we will respond via email. We can also provide contact information for instant message
sessions.

Nion Swift API
--------------
The Nion Swift API gives access to the user interface and data. It is intended to be stable, meaning that applications
written using the API will remain valid and function the same in the future, independent of changes to Nion Swift itself.

To accompish this, the API is versioned. When you request the API object, you must specify which version of the API you
would like to use. If the running version of Nion Swift can provide that version of the API, then your script should work.

.. note::
    Until Nion Swift reaches version 1.0, the API may change slightly. We will do our best to keep it stable and backwards
    compatible until then, though.

Scripting vs. Extensions
------------------------
The Nion Swift API can be accessed in script mode or in extension mode.

If you want to write quick snippets of code that act on Nion Swift immediately, you will want to use script mode. See
:ref:`scripting`.

If you want to write extensions to Nion Swift that provide a user interface or otherwise extend the functionality you
will want to use the more complex extension mode. See :ref:`writing-extensions`.

Some things you can do with the API in script mode.

   * Create and modify data items with new data, calibrations, or metadata.
   * Start, stop, and grab data from hardware sources.
   * Control instruments such as the microscope.
   * Run algorithms that don't require high performance data transfer.

Some things you can do with the API in extension mode.

   * Create a menu item.
   * Create a panel providing a new user interface.
   * Create an IO handler for importing and exporting new file types.
   * Create a custom hardware source for data acquisition.
   * Create more complex acquisition procedures using a hardware source for control and data acquisition.
   * Create high performance algorithms that run on threads.

.. _sample-code-links:

Sample Code
-----------
Some sample code is available here:

* `Example Code Used in This Guide <https://github.com/nion-software/examples>`_
* `Useful Extensions <https://github.com/nion-software/extensions>`_

Please feel free to fork these projects, add your own code, and request pull requests when you think you have something
suitable for others to look at and learn from.

.. _scripting:

Scripting
---------
Nion Swift includes a Python Console for basic scripting. You can access a Python Console window using the
menu item ``File > Python Console`` (Ctrl-K on Windows/Linux; Cmd-K on macOS).

Once you have a Python Console, you can enter Python code in the Python Console. In addition, the Python Console
automatically configures the ``api`` variable for you. ::

   >>> window = api.application.document_windows[0]
   >>> data_item = window.target_data_item
   >>> data_item.data.shape
   (512, 1024)

See :ref:`scripting-guide` for more examples.

External Scripting
------------------
The Python world has numerous great tools for development, such as `IPython <http://ipython.org/>`_, `PyCharm
<https://www.jetbrains.com/pycharm/>`_, and the Python command line interpreter. You can access the Nion Swift API
using those tools.

To use an external tool, you will first need to install the ``nionlib`` module matching the version of Nion Swift that
you are running. The ``nionlib`` module acts as a communication liaison to Nion Swift.

We recommend that you keep separate Python environments for external development and for running Nion Swift. You will be
installing ``nionlib`` into the external environment, not into the Python environment that Nion Swift uses. The details of
this will be specific to your Python distribution.

See :ref:`installing-nionlib` below.

Once you have installed ``nionlib``, you can get started with external scripting. Nion Swift must be running before using
``nionlib`` so launch it first.

Once Nion Swift is running, run your favorite Python tool and import the ``nionlib`` module. ::

    $ python
    Python 3.5.1 |Anaconda 2.4.0 (x86_64)| (default, Dec  7 2015, 11:24:55)
    [GCC 4.2.1 (Apple Inc. build 5577)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    >>> import nionlib
    >>> api = nionlib.get_api('~1.0')
    >>> library = api.library
    >>> print(library.data_item_count)
    16
    >>>

You can import the ``nionlib`` module into other interpreters such as IPython or PyCharm. You can launch multiple
interpreters and import ``nionlib`` into each interpreter if you need multiple scripts open simultaneously.

.. note::
    If your Python tool doesn't find ``nionlib`` then it is probably running the wrong Python interpreter.

See :ref:`scripting-guide` for more examples.

IPython
-------
You can use IPython for Nion Swift scripting.::

    $ ipython notebook

    In [1]: import nionlib
            api = nionlib.get_api('~1.0')
            library = api.library
            print(library.data_item_count)

PyCharm
-------
You can use PyCharm for Nion Swift scripting. PyCharm also has built-in IPython support.

To be able to edit and run a script, first create a new folder with your script. Then open that folder as a project.

Next open your script file.

Now configure PyCharm to run your script file using the menu item ``Run`` > ``Edit Configurations...`` Click the ``+`` button and
add a new Python script. Configure the correct interpreter (either the system Python or the Python included with the Swift distribution).
Make sure that the ``nionlib`` module is available to that interpreter.

Edit your file::

    import nionlib
    api = nionlib.get_api('~1.0')
    print(api.library.data_item_count)

Click the ``Run`` button and make sure it returns a reasonable value.

.. _installing-nionlib:

Installing ``nionlib``
----------------------
The easiest technique is to install ``nionlib`` into your Python 3 installation using ``easy_install`` which is usually
included as part of your Python installation.

On Windows::

    C:> easy_install "C:\Program Files\Nion Swift\PlugIns\Connection\NionLib\dist\nionlib-0.5.7.zip"

On OS X::

    $ easy_install "/Applications/Nion Swift.app/Contents/Resources/PlugIns/Connection/NionLib/dist/nionlib-0.5.7.tar.gz"

On Linux::

    $ sudo easy_install-3.4 "Nion Swift/PlugIns/Connection/NionLib/dist/nionlib-0.5.7.tar.gz"

.. _writing-extensions:

Writing Extensions
------------------
Writing Nion Swift extensions is straightforward. Extensions are loaded into Nion Swift when it is launched.

At launch time, Nion Swift searches through various directories to load extensions. It imports each package within those
directories and then searches the imported package for classes that appear to be Nion Swift extensions. The specific
criteria (beyond appearing in one of the extension locations) is a class name that ends in 'Extension' and includes a
class variable 'extension_id'.

When the extension is loaded, the class will be instantiated and an ``api_broker`` object will be passed to
``__init__``. The ``api_broker`` can be used to supply a versioned ``api`` object. ::

    class MyExtension(object):

        # required for Swift to recognize this as an extension class.
        extension_id = "my.extension.identifier"

        def __init__(self, api_broker):
            # grab the api object.
            api = api_broker.get_api(version='1', ui_version='1')
            # api can be used to access Nion Swift...

        def close(self):
            pass  # perform any shutdown activities

See more about extensions in  :ref:`extension-locations` and :ref:`extension-loading`.

.. _extension-locations:

Extension Locations
-------------------
If you are writing an extension, you need to make sure your extension gets loaded into Nion Swift.

To do that, you can put custom extensions in the following locations:

Windows
   * :samp:`C:\\Users\\<username>\\AppData\\Local\\Nion\\Swift\\PlugIns`
   * :samp:`C:\\Users\\<username>\\Documents\\Nion\\Swift\\PlugIns`

Mac OS
   * :samp:`/Users/<username>/Library/Application Support/Nion/Swift/PlugIns`
   * :samp:`/Users/<username>/Documents/Nion/Swift/PlugIns`

Linux
   * TODO: Describe locations for Linux extensions

.. _extension-loading:

Extension Loading
-----------------
When the extension is imported, Swift will look for a class defined in the module that ends with :samp:`Extension` and
defines a class property :samp:`extension_id`. If it finds such a class, it will instantiate it, passing the
:samp:`api_broker` object that allows you to get the versioned API your extension requires. Your extension should do
initialization in the :samp:`__init__` method of that class.

When Swift exits, the :samp:`close` method of that class will also be called. You can do any de-initialization in the
close method.

You should avoid executing code that depends on other extensions or on Swift during extension module loading.

Debugging
---------
When using the API for external scripting, the Python instance used for scripting is separate from the Python instance
used internally in Swift, so debugging is easy. You can set breakpoints and otherwise step through your code as necessary.

Debugging extensions is more tricky. There are two main options for debugging extensions:

   * Using print and logging facilities.
   * Launch your Python module outside of Nion Swift.

You can use the Python logging module to output to the Output window. logging.info and above are sent. logging.debug is
only sent to developer console. ::

    import logging
    logging.info("Here is your result: 42")
    logging.debug("Debugging: 21 + 21 = 42")
    print("Forty-two")

When launching your module outside of Nion Swift, you may be able to debug parts of your software using the scripting
mode of development. You will not be able to directly debug the part of your plug-in that implements the extension.

For instance, if you have a menu item in an extension, the menu item might call a function ``perform_action``. While you
can't step through the code that creates the menu item (since it is part of the extension architecture), you could at
least load the library that implements ``perform_action`` and run code that directly invokes that function for
debugging.

API Notes
---------
Versions numbering follows `Semantic Version Numbering <http://semver.org/>`_.

:samp:`on_xyz` methods are used when a callback needs a return value and has only a single listener.

:samp:`xyz_event` methods are used when a callback is optional and may have multiple listeners.

Nion Swift uses c-indexing for numpy (fastest changing coordinate in memory is last). This means that sizes are usually
specified in height, width and coordinates are specified in :samp:`y, x`.

Coordinates used with overlay graphics are specified in data-relative coordinates, which means that the values range from
0.0 to 1.0 for each dimension with 0.0, 0.0 being the top left corner.

Two dimensional points are represented as :samp:`y, x`. Three dimensional points are represented as :samp:`z, y, x`.

Two dimensional sizes are represented as :samp:`height, width`.

Rectangles are specified by the tuple :samp:`top_left, size` where :samp:`top_left` is a point and :samp:`size` is a
size.

Where to Go Next?
-----------------

:ref:`concepts-guide`

:ref:`scripting-guide`

:ref:`api-architecture`

:ref:`api-reference`
