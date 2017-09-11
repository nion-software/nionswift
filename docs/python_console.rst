.. _python-console:

Python Console
==============
If you want to write quick snippets of code that act on Nion Swift immediately, you will want to use the Python Console.

Nion Swift includes a Python Console for basic scripting. You can access a Python Console window using the
menu item ``File > Python Console`` (Ctrl-K on Windows/Linux; Cmd-K on macOS).

Once you have a Python Console, you can enter Python code in the Python Console. In addition, the Python Console
automatically configures the ``api`` variable for you. ::

   >>> window = api.application.document_windows[0]
   >>> data_item = window.target_data_item
   >>> data_item.data.shape
   (512, 1024)

See :ref:`scripting-guide` for more examples.
