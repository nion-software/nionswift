:orphan:

.. _plugins-guide:

Customization Using Python Packages and Modules
===============================================
You can extend with additional user interface and other complex capabilities that aren't covered by other Python
scripting techniques.

Some examples of things you must do with a Python plug-in package or module.

   * Create a menu item.
   * Create a panel providing a new user interface.
   * Create an IO handler for importing and exporting new file types.
   * Create a data acquisition device.
   * Create more complex acquisition procedures using a hardware source for control and data acquisition.
   * Create high performance algorithms that run on threads.

At launch time, Nion Swift searches its Python environment for packages, searches some predefined locations for
modules, and starts them using a startup procedure which can include dependency and order checking.

Finding Your Python Package
---------------------------
Nion Swift first searches its Python environment for packages.

It looks for installed packages which have a ``nionswift_plugin`` namespace and treats packages within that
namespace as packages to be loaded.

When you create a Python package, you should NOT put a ``__init__.py`` in the ``nionswift_plugin`` directory, since it
is a Python namespace. See `PEP 420 <https://www.python.org/dev/peps/pep-0420/>`_ for more details. Similarly, you will
NOT need the `namespace_packages` directive in your `setup.py` file.

Loading Your Python Package
---------------------------
After Nion Swift finds your packages, it loads them.

When the package is imported, Swift will look for a class that ends with ``Extension`` and defines a class property
``extension_id``. If it finds such a class, it will instantiate it, passing the ``api_broker`` object that allows you to
get the versioned API your extension requires. Your extension should do initialization in the ``__init__`` method of
that class.

When Swift exits, the ``close`` method of that class will also be called. You can do any de-initialization in the close
method.

You should avoid executing code that depends on other extensions or on Swift during extension module loading.

When the package is loaded, the class will be instantiated and an ``api_broker`` object will be passed to
``__init__``. The ``api_broker`` can be used to get an ``api`` object. ::

    class MyExtension:

        # required for Swift to recognize this as an extension class.
        extension_id = "my.extension.identifier"

        def __init__(self, api_broker):
            # grab the api object.
            api = api_broker.get_api(version='~1.0', ui_version='~1.0')
            # api can be used to access Nion Swift...

        def close(self):
            pass  # perform any shutdown activities

Organizing Your Python Package
------------------------------
If you are planning on making your plug-in available publicly, we recommend using Python packages to distribute your
extension and publishing it to PyPI. Other users will be able to install your plug-in using ``pip`` and other standard
Python installation tools. ::

    $ pip install my-great-nion-swift-extension

If you are planning on using your plug-in privately, we still recommend using a standard Python package, but installing
it into your Python environment using one of two techniques. ::

    $ python setup.py /path/to/your/extension  # for end users
    $ pip install -e /path/to/your/extension  # for development

If parts of your package may be reusable in other packages (e.g. a library of processing functions), then you will
want to split your package into different namespaces so that other packages can import your library independently of
the user interface or other Nion Swift specific code.

.. warning::
    You should never import anything from the nionswift_plugin namespace directly. Instead, split your code into
    two namespaces.

For instance, you might have the following directory structure. ::

    mycompany/__init__.py
    mycompany/processing/feature_finder.py
    nionswift_plugin/mycompany_featurefinder/feature_finder_ui.py

This allows your UI code and other packages to access your ``feature_finder`` code. ::

    >>> from mycompany.processing import feature_finder

And it allows Nion Swift to load your UI code during startup.

PlugIns
-------
.. warning::
    Installing Python packages using the ``nionswift_plugin`` namespace is preferable to using ``PlugIns``.

For backwards compatility, you can also organize your extension as a ``PlugIn``. If you're organizing your code into
a plug-in, you simply put your code into a sub-directory of one of the ``PlugIn`` directories listed above.

Using this technique is not recommended since you cannot cleanly provide code to other plug-ins nor can you nicely
specify dependencies using imports.

Nion Swift looks for packages within various ``PlugIns`` directories. The ``PlugIns`` directories can be located in the
following locations:

Windows
    * :samp:`C:\\Users\\<username>\\AppData\\Local\\Nion\\Swift\\PlugIns`
    * :samp:`C:\\Users\\<username>\\Documents\\Nion\\Swift\\PlugIns`
    * ``PlugIns`` in the same location as the ``Swift.exe`` file

Mac OS
    * :samp:`/Users/<username>/Library/Application Support/Nion/Swift/PlugIns`
    * :samp:`/Users/<username>/Documents/Nion/Swift/PlugIns`
    * ``PlugIns`` in the same location as the ``NionSwift`` executable file

Linux
    * TODO: Describe locations for Linux extensions

Debugging
---------
When using the API for external scripting, the Python instance used for scripting is separate from the Python instance
used internally in Swift, so debugging is easy. You can set breakpoints and otherwise step through your code as necessary.

However, debugging packages is more tricky. There are two main options for debugging packages:

   * Using print and logging facilities.
   * Launch your Python package outside of Nion Swift.

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

Designing Python Packages to Extend Swift
-----------------------------------------
Questions to help define a plug-in package.

- What actions can the user perform?
- What is presented to user?
- Custom UI?
- Custom workspace layout?
- How saved?
- How restored?
- How initialized?
- What happens dynamically?
- How are deletes handled?
- Copy/paste/clone/snapshot?
- Any required configuration?
- How tested?

Plug-in Checklist
-----------------
A list of items that make a well defined plug-in package.

- Available on PyPI
- Has setup script
- Available on conda, plus feedstock.
- Automated testing
- Settings stored using API paths
- JSON settings
- Settings location logging.info
- Settings are isolated; don't read other settings
- Clean install/uninstall with pip
- Avoid committing large files to GitHub projects (use Git LFS instead).
