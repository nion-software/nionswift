:orphan:

.. _interactive-guide:

Python Interactive Scripting Guide
==================================
If you want to write short scripts that interact with the user in a conversational manner, you will want to use
Interactive Scripts.

You can run Interactive Scripts using the menu item ``File > Scripts`` (Ctrl-R on Windows/Linux; Cmd-R on macOS).

The Interactive Scripts dialog will give you a list of scripts to run. If you want to add a new one or remove an unused
one, use the ``Add`` and ``Remove`` buttons at the lower left.

To run a script, select it and click the ``Run`` button, press ``Enter`` or double click on the desired script.

As with other Python code within Nion Swift, interactive scripts have access to the API, but also define a special API
that you can use to interact with the users via questions. The interactive API is only available when running scripts
as _interactive_.

Interactive scripts must include a ``script_main`` function that looks similar to this. ::

    def script_main(api_broker):
        interactive = api_broker.get_interactive(version='~1.0')
        api = api_broker.get_api(version='~1.0')
        is_confirmed = interactive.confirm_yes_no('Are you ready?')
        if is_confirmed:
            print('Proceeding...')
            data_item = api.library.create_data_item_from_data(numpy.random.randn(16, 16))
            api.application.document_windows[0].display_data_item(data_item)

The special object ``interactive`` represents functions useful in an interactive environment.

Some functions (e.g. ``confirm_yes_no``) will pause the script until the user responds or cancels.

See :ref:`scripting-guide` to learn about the Nion Swift API.

See :ref:`interactive-guide` to learn more specifics about the Interactive API.

More Examples
+++++++++++++

Basic interactive script. Annotating ``api_broker`` with ``Facade.InteractiveAPIBroker`` gives ``interactive`` the type
``Facade.InteractiveSession`` and ``api`` the type ``Facade.API_1``, so that a type checker such as mypy can check their
use. ::

    import numpy

    from nion.swift import Facade

    def do_something(interactive: Facade.InteractiveSession, api: Facade.API_1) -> None:
        target_data_item = api.application.document_windows[0].target_data_item
        if target_data_item:
            interactive.print(f"Sum of target image: {numpy.sum(target_data_item.data)}")

    def script_main(api_broker: Facade.InteractiveAPIBroker) -> None:
        interactive = api_broker.get_interactive(version='~1.0')
        api = api_broker.get_api(version='~1.0', ui_version='~1.0')
        do_something(interactive, api)
