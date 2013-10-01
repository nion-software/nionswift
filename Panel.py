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

        The Panel includes a method tryToClose which can be re-implemented in sub-
        classes to handle the case where the user clicks the close box. The default
        implementation is to call close.
        """

    def __init__(self, document_controller, panel_id, display_name):
        self.__document_controller_weakref = weakref.ref(document_controller)
        self.ui = document_controller.ui
        self.panel_id = panel_id
        self.__uuid = uuid.uuid4()
        self.dock_widget = None
        self.__widget = None
        self.display_name = display_name

    def close(self):
        try:
            if self.dock_widget:
                self.ui.Widget_removeDockWidget(self.document_controller.document_window, self.dock_widget)
                # NOTE: deleting the widget is not needed, despite the Qt documentation to the contrary. Tested sep 11 2013. CEM.
                # self.ui.Widget_removeWidget(self.dock_widget)
                self.dock_widget = None
                self.__widget = None
# For now, don't remove this widget here. Dockable items are never removed; and image panels are handled external to this class. CEM 2013-09-30.
#            if self.__widget:
#                self.ui.Widget_removeWidget(self.__widget)
#                self.__widget = None
        except Exception, e:
            import traceback
            traceback.print_exc()
            raise

    def __get_document_controller(self):
        return self.__document_controller_weakref()
    document_controller = property(__get_document_controller)

    def __str__(self):
        return self.display_name

    # uuid property. read only.
    def __get_uuid(self):
        return self.__uuid
    uuid = property(__get_uuid)

    # access for the property. this allows C++ to get the value.
    def get_uuid_str(self):
        return str(self.uuid)

    def __get_widget(self):
        return self.__widget
    def __set_widget(self, widget):
        self.__widget = widget
    widget = property(__get_widget, __set_widget)

    def loadIntrinsicWidget(self, intrinsic_id):
        return self.ui.Widget_loadIntrinsicWidget(intrinsic_id)

    def getWidgetProperty(self, property):
        return self.ui.Widget_getWidgetProperty(self.__widget, property)

    def setWidgetProperty(self, property, value):
        self.ui.Widget_setWidgetProperty(self.__widget, property, value)

    def tryToClose(self):
        self.close()


class OutputPanel(Panel):
    def __init__(self, document_controller, panel_id, properties):
        Panel.__init__(self, document_controller, panel_id, "Output")
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
        Panel.close(self)

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
        Panel.__init__(self, document_controller, panel_id, "Console")
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
        lines = ["from nion.swift import DocumentController, DataItme, Image, Menu",
                 "import logging",
                 "import numpy as np",
                 "import numpy as numpy",
                 "_d = DocumentController.DocumentController.DataAccessor(dc)"]
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
