# standard libraries
import code
import gettext
import logging
import os
import sys
import uuid
import weakref

# third party libraries
# None

# local libraries
from Decorators import relative_file
import UserInterface
import Workspace

_ = gettext.gettext


class Panel(Workspace.Workspace.Element):
    """
        The Panel represents a panel within the document window.

        The Panel includes the ability to load a Qt widget. The Qt widget will be
        automatically unloaded when the Panel is deleted.

        The Panel includes a method tryToClose which can be re-implemented in sub-
        classes to handle the case where the user clicks the close box. The default
        implementation is to call close.
        """

    def __init__(self, document_controller, panel_id, display_name):
        super(Panel, self).__init__(document_controller.ui, panel_id)
        self.__document_controller_weakref = weakref.ref(document_controller)
        self.panel_id = panel_id
        self.__uuid = uuid.uuid4()
        self.dock_widget = None
        self.__widget = None
        self.display_name = display_name

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

    def loadQmlWidget(self, qml_filename, context_properties = None):
        context_properties = context_properties if context_properties else {}
        return self.ui.DocumentWindow_loadQmlWidget(self.document_controller.document_window, qml_filename, self, context_properties)

    def loadIntrinsicWidget(self, intrinsic_id):
        return self.ui.Widget_loadIntrinsicWidget(intrinsic_id)

    def setContextProperty(self, property, value):
        self.ui.Widget_setContextProperty(self.__widget, property, value)

    def getWidgetProperty(self, property):
        return self.ui.Widget_getWidgetProperty(self.__widget, property)

    def setWidgetProperty(self, property, value):
        self.ui.Widget_setWidgetProperty(self.__widget, property, value)

    def tryToClose(self):
        self.close()
    
    def close(self):
        try:
            if self.dock_widget:
                self.ui.Widget_removeDockWidget(self.document_controller.document_window, self.dock_widget)
                self.ui.Widget_unloadWidget(self.dock_widget)
                self.dock_widget = None
                self.__widget = None
            if self.__widget:
                self.ui.Widget_unloadWidget(self.__widget)
                self.__widget = None
        except Exception, e:
            import traceback
            traceback.print_exc()
            raise
        Workspace.Workspace.Element.close(self)


class OutputPanel(Panel):
    def __init__(self, document_controller, panel_id):
        Panel.__init__(self, document_controller, panel_id, "Output")
        self.widget = self.loadIntrinsicWidget("output")
        self.ui.Widget_setWidgetProperty(self.widget, "min-height", 180)
        output_widget = self.widget
        class OutputPanelHandler(logging.Handler):
            def __init__(self, ui):
                super(OutputPanelHandler, self).__init__()
                self.ui = ui
            def emit(self, record):
                if record.levelno >= logging.INFO:
                    self.ui.Output_out(output_widget, record.getMessage())
        self.__output_panel_handler = OutputPanelHandler(document_controller.ui)
        logging.getLogger().addHandler(self.__output_panel_handler)
    def close(self):
        logging.getLogger().removeHandler(self.__output_panel_handler)
        Panel.close(self)


class ConsolePanel(Panel):
    def __init__(self, document_controller, panel_id):
        Panel.__init__(self, document_controller, panel_id, "Console")
        self.widget = self.loadIntrinsicWidget("console")
        self.ui.Widget_setWidgetProperty(self.widget, "min-height", 180)
        self.ui.Console_setDelegate(self.widget, self)
        # this is the console object which carries out the user commands
        class Console(code.InteractiveConsole):
            def __init__(self, locals):
                code.InteractiveConsole.__init__(self, locals)
                self.error = None
            def write(self, data):
                self.error = (self.error if self.error else "") + str(data)
        locals = {'__name__': None, '__console__': None, '__doc__': None, 'dc': document_controller}
        self.console = Console(locals)
        lines = ["from nion.swift import DocumentController, DataItme, Image, Menu",
                 "import logging",
                 "import numpy as np",
                 "import numpy as numpy",
                 "_d = DocumentController.DocumentController.DataAccessor(dc)"]
        output, error = self.pushLines(lines)
    # capture console output
    def captureOutput(self):
        class ConsoleOut(object):
            def __init__(self):
                self.output = []
            def write(self, data):
                self.output.append(data)
        # capture all output and put it into console_out.output
        oldstdout = sys.stdout
        oldstderr = sys.stderr
        console_out = ConsoleOut()
        sys.stdout = console_out
        sys.stdout = console_out
        self.console.error = None
        return console_out, oldstdout, oldstderr
    # release the console output and return captured output and error
    def releaseOutput(self, captured):
        console_out = captured[0]
        sys.stdout = captured[1]
        sys.stderr = captured[2]
        output = "".join(console_out.output)
        error = self.console.error
        return output, error
    def pushLines(self, lines):
        captured = self.captureOutput()
        map(self.console.push,lines)
        return self.releaseOutput(captured)
    # interpretCommand is called from the intrinsic widget.
    def interpretCommand(self, command):
        captured = self.captureOutput()
        incomplete = self.console.push(command)
        output, error = self.releaseOutput(captured)
        # figure out what we're sending back to the console intrinsic widget
        result = error if error else output
        prompt = "... " if incomplete else ">>> "
        error_code = -1 if error else 0
        return result, error_code, prompt


class HeaderPanel(Panel):

    def __init__(self, document_controller, panel_id):
        Panel.__init__(self, document_controller, panel_id, "Header")
        self.widget = self.loadQmlWidget(relative_file(__file__, "HeaderView.qml"))


class ButtonListPanel(Panel):

    class ButtonListModel(UserInterface.ListModel):
        def __init__(self, document_controller, button_list_panel):
            super(ButtonListPanel.ButtonListModel, self).__init__(document_controller, ["buttonColor", "buttonTitle"])
            self.button_list_panel_weakref = weakref.ref(button_list_panel)
            self.rebuild()
        def rebuild(self):
            button_list_panel = self.button_list_panel_weakref()
            values = []
            for button_id in button_list_panel.button_ids:
                assert button_id in button_list_panel.button_tuples
                button_tuple = button_list_panel.button_tuples[button_id]
                values.append({"buttonTitle": button_tuple["buttonTitle"]})
            self.replaceModel(values)

    def __init__(self, document_controller, panel_id):
        super(ButtonListPanel, self).__init__(document_controller, panel_id, _("Tool Bar"))
        self.button_ids = []     # order of buttons
        self.button_tuples = {}  # by map id to tuple
        self.button_list_model = ButtonListPanel.ButtonListModel(document_controller, self)
        context_properties = { "buttonListModel": self.button_list_model.py_list_model }
        self.widget = self.loadQmlWidget(self._relativeFile("ButtonList.qml"), context_properties)

    def _relativeFile(self, filename):
        dir = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
        return os.path.join(dir, filename)

    def buttonClicked(self, index):
        button_id = self.button_ids[index]
        button_tuple = self.button_tuples[button_id]
        callback = button_tuple["callback"]
        callback()

    def addButton(self, button_id, title, callback):
        if button_id not in self.button_ids:
            self.button_ids.append(button_id)
        self.button_tuples[button_id] = { "buttonTitle": title, "callback": callback }
        self.button_list_model.rebuild()

    def removeButton(self, button_id):
        if button_id in self.button_ids:
            self.button_ids.remove(button_id)
            del self.button_tuples[button_id]
        self.button_list_model.rebuild()

    def close(self):
        self.setContextProperty("buttonListModel", None)
        self.button_list_model.close()
        super(ButtonListPanel, self).close()
