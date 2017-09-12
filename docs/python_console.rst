.. _python-console:

Python Console
==============
If you want to write quick snippets of code that act on Nion Swift immediately, you will want to use the Python Console.

Nion Swift includes a Python Console for basic scripting. You can access a Python Console window using the
menu item ``File > Python Console`` (Ctrl-K on Windows/Linux; Cmd-K on macOS).

Once you have a Python console, you can enter Python code in the Python console. In addition, the Python console
automatically configures the ``api`` variable for you. ::

   >>> window = api.application.document_windows[0]
   >>> data_item = window.target_data_item
   >>> data_item.data.shape
   (512, 1024)

The Python console assigns the ``api.show`` method to ``show`` making it easy to quickly display new items. Remember to
make sure there is a blank display panel available to show the new item (right click on a display panel, choose ``None``). ::

    >>> d = numpy.random.randn(20, 20)
    >>> show(d)
    >>> api.show(d)  # same thing
    >>> dd = xd.new_from_data(d)
    >>> show(dd)

See :ref:`scripting-guide` for more examples.
