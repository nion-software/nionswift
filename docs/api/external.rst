:orphan:

.. _python-external:

External Scripting
==================
The Python world has numerous great tools for development, such as `IPython <http://ipython.org/>`_, `PyCharm
<https://www.jetbrains.com/pycharm/>`_, and the Python command line interpreter. You can access the Nion Swift API
using those tools.

.. warning::
    External scripting is an advanced topic. It is **not required** to use Python with Nion Swift. See
    :ref:`python-console` for an easier alternative.

To use an external tool, you will use the ``nionlib`` module, which acts as a communication liaison to Nion Swift.

Installing NionLib
------------------
To use ``nionlib`` you will need to tell Python where to find the ``nionlib`` module. One direct way to do this is to
modify ``sys.path`` at the beginning of your external script.

If Nion Swift is located at ``C:\NionSwift``, you can put Python code similar to the following at the start of your
external file or notebook. ::

    import sys
    sys.path.insert(0, 'C:\\NionSwift\nionswift')
    import nionlib

There are other more advanced techniques, such as using the ``pip`` tool to add ``nionswift``, which is the package in
which ``nionlib`` is distributed, directly to the Python path. ::

    >>> pip install -e /path/to/NionSwift/nionswift

Using this technique, you do not have to modify ``sys.path`` each time.

Using NionLib
-------------
Nion Swift must be running before using ``nionlib`` so launch it first.

Once Nion Swift is running, run your favorite Python tool and import the ``nionlib`` module. ::

    $ python
    Python 3.5.1 |Anaconda 2.4.0 (x86_64)| (default, Dec  7 2015, 11:24:55)
    [GCC 4.2.1 (Apple Inc. build 5577)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    >>> import sys
    >>> sys.path.insert(0, 'C:\\NionSwift\nionswift')
    >>> import nionlib
    >>> api = nionlib.get_api('~1.0')
    >>> library = api.library
    >>> print(library.data_item_count)
    16
    >>>

You can import the ``nionlib`` module into other interpreters such as IPython or PyCharm. You can launch multiple
interpreters and import ``nionlib`` into each interpreter if you need multiple scripts open simultaneously.

.. note::
    If your Python tool doesn't find ``nionlib`` then ``sys.path`` is incorrectly configured.

See :ref:`scripting-guide` for more examples.

IPython
-------
You can use IPython for Nion Swift scripting.::

    $ ipython notebook

    In [1]: import sys
            sys.path.insert(0, 'C:\\NionSwift\nionswift')
            import nionlib
            api = nionlib.get_api('~1.0')
            library = api.library
            print(library.data_item_count)

PyCharm
-------
You can use PyCharm for Nion Swift scripting.

To be able to edit and run a script, first create a new folder with your script. Then open that folder as a project.

Next open your script file.

Now configure PyCharm to run your script file using the menu item ``Run`` > ``Edit Configurations...`` Click the ``+``
button and add a new Python script. Configure the correct interpreter (either the system Python or the Python included
with the Swift distribution). Make sure that either the ``nionlib`` module is available to that interpreter or you edit
the ``sys.path`` at the start of the script.

Edit your file::

    import sys
    sys.path.insert(0, 'C:\\NionSwift\nionswift')
    import nionlib
    api = nionlib.get_api('~1.0')
    print(api.library.data_item_count)

Click the ``Run`` button and make sure it returns a reasonable value.
