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
from nion.swift import Workspace

_ = gettext.gettext


class Panel(Workspace.Workspace.Element):
    """
        The Panel represents a panel within the document window.

        The Panel includes the ability to load a Qt widget. The Qt widget will be
        deleted when the Panel is deleted.

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

    def close(self):
        try:
            if self.dock_widget:
                self.ui.Widget_removeDockWidget(self.document_controller.document_window, self.dock_widget)
                # NOTE: deleting the widget is not needed, despite the Qt documentation to the contrary. Tested sep 11 2013. CEM.
                # self.ui.Widget_removeWidget(self.dock_widget)
                self.dock_widget = None
                self.__widget = None
            if self.__widget:
                self.ui.Widget_removeWidget(self.__widget)
                self.__widget = None
        except Exception, e:
            import traceback
            traceback.print_exc()
            raise
        Workspace.Workspace.Element.close(self)

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
    def __init__(self, document_controller, panel_id):
        Panel.__init__(self, document_controller, panel_id, "Console")
        self.widget = self.loadIntrinsicWidget("console")
        self.ui.Widget_setWidgetProperty(self.widget, "min-height", 180)
        self.ui.Console_setDelegate(self.widget, self)
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
            self.interpretCommand(l) 

    # interpretCommand is called from the intrinsic widget.
    def interpretCommand(self, command):
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


class HeaderPanel(Panel):

    def __init__(self, document_controller, panel_id):
        Panel.__init__(self, document_controller, panel_id, "Header")

        ui = document_controller.ui

        self.canvas = ui.create_canvas_widget(document_controller)
        self.canvas.on_size_changed = lambda width, height: self.size_changed(width, height)

        self.layer = self.canvas.create_layer()

        self.update_header()

        self.widget = self.canvas.widget

    def update_header(self):

        ctx = self.layer.drawing_context

        ctx.clear()

        ctx.save()
        ctx.beginPath()
        ctx.moveTo(0, 0)
        ctx.lineTo(0, self.canvas.height)
        ctx.lineTo(self.canvas.width, self.canvas.height)
        ctx.lineTo(self.canvas.width, 0)
        ctx.closePath()
        gradient = ctx.create_linear_gradient(0, 0, 0, self.canvas.height);
        gradient.add_color_stop(0, '#ededed');
        gradient.add_color_stop(1, '#cacaca');
        ctx.fillStyle = gradient
        ctx.fill()
        ctx.restore()

        ctx.save()
        ctx.beginPath()
        # line is adjust 1/2 pixel down to align to pixel boundary
        ctx.moveTo(0, 0.5)
        ctx.lineTo(self.canvas.width, 0.5)
        ctx.strokeStyle = '#FFF'
        ctx.stroke()
        ctx.restore()

        ctx.save()
        ctx.beginPath()
        # line is adjust 1/2 pixel down to align to pixel boundary
        ctx.moveTo(0, self.canvas.height-0.5)
        ctx.lineTo(self.canvas.width, self.canvas.height-0.5)
        ctx.strokeStyle = '#b0b0b0'
        ctx.stroke()
        ctx.restore()

        ctx.save()
        ctx.font = 'normal 11px serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillStyle = '#000'
        ctx.fillText(self.display_name, self.canvas.width/2, self.canvas.height/2+1)
        ctx.restore()

        self.canvas.draw()

    def mouseEntered(self):
        pass
    def mouseExited(self):
        pass
    def mouseClicked(self, y, x, raw_modifiers):
        pass
    def mouseDoubleClicked(self, y, x, raw_modifiers):
        pass
    def mousePressed(self, y, x, raw_modifiers):
        pass
    def mouseReleased(self, y, x, raw_modifiers):
        pass
    def mousePositionChanged(self, y, x, raw_modifiers):
        pass

    def size_changed(self, width, height):
        if width > 0 and height > 0:
            self.update_header()
