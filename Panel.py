# standard libraries
import code
import gettext
import logging
import os
import sys
import uuid
import weakref
from contextlib import contextmanager
from StringIO import StringIO

# third party libraries
# None

# local libraries
# None


_ = gettext.gettext


class Panel(object):
    """
        The Panel represents a panel within the document window.

        The Panel includes the ability to load a Qt widget. The Qt widget will be
        deleted when the Panel is deleted.
        """

    def __init__(self, document_controller, panel_id, display_name):
        self.__document_controller_weakref = weakref.ref(document_controller)
        self.ui = document_controller.ui
        self.panel_id = panel_id
        self.dock_widget = None
        self.display_name = display_name

    # subclasses can override to clean up when the panel closes.
    def close(self):
        pass

    def __get_document_controller(self):
        return self.__document_controller_weakref()
    document_controller = property(__get_document_controller)

    def __str__(self):
        return self.display_name

    # access for the property. this allows C++ to get the value.
    def get_uuid_str(self):
        return str(self.uuid)


class OutputPanel(Panel):
    def __init__(self, document_controller, panel_id, properties):
        super(OutputPanel, self).__init__(document_controller, panel_id, "Output")
        properties["min-height"] = 180
        self.widget = self.ui.create_output_widget(properties)
        output_widget = self.widget  # no access to OutputPanel.self inside OutputPanelHandler
        class OutputPanelHandler(logging.Handler):
            def __init__(self, ui):
                super(OutputPanelHandler, self).__init__()
                self.ui = ui
            def emit(self, record):
                if record.levelno >= logging.INFO:
                    output_widget.send(record.getMessage())
        self.__output_panel_handler = OutputPanelHandler(document_controller.ui)
        logging.getLogger().addHandler(self.__output_panel_handler)
    def close(self):
        logging.getLogger().removeHandler(self.__output_panel_handler)
        super(OutputPanel, self).close()

@contextmanager
def reassign_stdout(new_stdout, new_stderr):
    oldstdout, oldtsderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = new_stdout, new_stderr
    yield
    sys.stdout, sys.stderr = oldstdout, oldtsderr

class ConsolePanel(Panel):
    # TODO: Replace this with a proper console. As it is, basic functionality
    # like raw_input is broken, pdb doesn't work and we can't embed an IPython
    # console.
    def __init__(self, document_controller, panel_id, properties):
        super(ConsolePanel, self).__init__(document_controller, panel_id, "Console")
        properties["min-height"] = 180
        self.widget = self.ui.create_console_widget(properties)
        self.widget.on_interpret_command = lambda command: self.interpret_command(command)
        self.other_stdout = StringIO()
        self.other_stderr = StringIO()
        # sys.ps1/2 is not always defined, we'll use it if it is
        self.ps1 = getattr(sys, "ps1", ">>> ")
        self.ps2 = getattr(sys, "ps2", "... ")

        locals = {'__name__': None, '__console__': None, '__doc__': None, 'dc': document_controller}
        self.console = code.InteractiveConsole(locals)
        lines = ["from nion.swift import DocumentController, DocumentModel, DataItem, Image",
                 "import logging",
                 "import numpy as np",
                 "import numpy as numpy",
                 "_d = DocumentModel.DocumentModel.DataAccessor(dc.document_model)"]
        for l in lines:
            self.interpret_command(l)

    # interpretCommand is called from the intrinsic widget.
    def interpret_command(self, command):
        with reassign_stdout(self.other_stdout, self.other_stderr):
            incomplete = self.console.push(command)

        prompt = self.ps2 if incomplete else self.ps1
        if self.other_stderr.getvalue():
            result =  self.other_stderr.getvalue()
            error_code = -1
        else:
            result =  self.other_stdout.getvalue()
            error_code = 0
        self.other_stdout.truncate(0)
        self.other_stderr.truncate(0)
        return result, error_code, prompt
