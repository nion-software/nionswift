# standard libraries
import code
import copy
from contextlib import contextmanager
import gettext
import logging
import os
import sys
import uuid
import weakref
import StringIO

# third party libraries
# None

# local libraries
from nion.ui import CanvasItem
from nion.ui import Process


_ = gettext.gettext


class Panel(object):
    """
        Represents content within a dock widget. The dock widget owns
        the panel and will invoke close and periodic on it. The dock
        widget expects the widget property to contain the ui content.
    """

    def __init__(self, document_controller, panel_id, display_name):
        self.__document_controller_weakref = weakref.ref(document_controller)
        self.ui = document_controller.ui
        self.panel_id = panel_id
        self.display_name = display_name
        self.widget = None
        # useful for many panels.
        self.__periodic_task_queue = Process.TaskQueue()
        self.__periodic_task_set = Process.TaskSet()

    # subclasses can override to clean up when the panel closes.
    def close(self):
        pass

    def __get_document_controller(self):
        return self.__document_controller_weakref()
    document_controller = property(__get_document_controller)

    # not thread safe. always call from main thread.
    def periodic(self):
        pass

    # tasks can be added in two ways, queued or added
    # queued tasks are guaranteed to be executed in the order queued.
    # added tasks are only executed if not replaced before execution.
    # added tasks do not guarantee execution order or execution at all.

    def add_task(self, key, task):
        self.document_controller.add_task(key + str(id(self)), task)

    def clear_task(self, key):
        self.document_controller.clear_task(key + str(id(self)))

    def queue_task(self, task):
        self.document_controller.put(task)

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
        self.other_stdout = StringIO.StringIO()
        self.other_stderr = StringIO.StringIO()
        # sys.ps1/2 is not always defined, we'll use it if it is
        self.ps1 = getattr(sys, "ps1", ">>> ")
        self.ps2 = getattr(sys, "ps2", "... ")

        locals = {'__name__': None, '__console__': None, '__doc__': None, '_document_controller': document_controller}
        self.console = code.InteractiveConsole(locals)
        lines = [
            "from nion.swift import DocumentController",
            "from nion.swift.model import DocumentModel, DataItem, Image, Region",
            "from nion.swift.Application import print_stack_all as _bt",
            "from nion.swift.Application import sample_stack_all as _pr",
            "import logging",
            "import numpy as np",
            "import numpy as numpy",
            "import uuid",
            "_data = DocumentModel.DocumentModel.DataAccessor(_document_controller.document_model)",
            "_data_item = DocumentModel.DocumentModel.DataItemAccessor(_document_controller.document_model)",
            "_document_model = _document_controller.document_model",
            # deprecated abbreviations
            "_d = _data",
            "_di = _data_item",
            "dc = _document_controller",
            ]
        for l in lines:
            self.interpret_command(l)
        self.document_controller.register_console(self)

    def close(self):
        self.document_controller.unregister_console(self)
        super(ConsolePanel, self).close()

    def insert_lines(self, lines):
        self.widget.insert_lines(lines)

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


class HeaderCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self, title=None, display_drag_control=False, display_sync_control=False):
        super(HeaderCanvasItem, self).__init__()
        self.wants_mouse_events = True
        self.__title = title if title else ""
        self.__display_drag_control = display_drag_control
        self.__display_sync_control = display_sync_control
        self.header_height = 20 if sys.platform == "win32" else 22
        self.sizing.set_fixed_height(self.header_height)
        self.on_drag_pressed = None
        self.on_sync_clicked = None

    def __str__(self):
        return self.__title

    def __get_title(self):
        return self.__title
    def __set_title(self, title):
        if self.__title != title:
            self.__title = title
            self.update()
    title = property(__get_title, __set_title)

    def mouse_pressed(self, x, y, modifiers):
        canvas_size = self.canvas_size
        if self.__display_drag_control:
            if x > 4 and x < 18 and y > 2 and y < canvas_size.height - 2:
                if self.on_drag_pressed:
                    self.on_drag_pressed()
        return True

    def mouse_released(self, x, y, modifiers):
        canvas_size = self.canvas_size
        if self.__display_sync_control:
            if x > 22 and x < 36 and y > 2 and y < canvas_size.height - 2:
                if self.on_sync_clicked:
                    self.on_sync_clicked()
        return True

    def _repaint(self, drawing_context):

        canvas_size = self.canvas_size

        drawing_context.save()
        drawing_context.begin_path()
        drawing_context.move_to(0, 0)
        drawing_context.line_to(0, canvas_size.height)
        drawing_context.line_to(canvas_size.width, canvas_size.height)
        drawing_context.line_to(canvas_size.width, 0)
        drawing_context.close_path()
        gradient = drawing_context.create_linear_gradient(canvas_size.width, canvas_size.height, 0, 0, 0, canvas_size.height)
        gradient.add_color_stop(0, '#ededed')
        gradient.add_color_stop(1, '#cacaca')
        drawing_context.fill_style = gradient
        drawing_context.fill()
        drawing_context.restore()

        drawing_context.save()
        drawing_context.begin_path()
        # line is adjust 1/2 pixel down to align to pixel boundary
        drawing_context.move_to(0, 0.5)
        drawing_context.line_to(canvas_size.width, 0.5)
        drawing_context.stroke_style = '#FFF'
        drawing_context.stroke()
        drawing_context.restore()

        drawing_context.save()
        drawing_context.begin_path()
        # line is adjust 1/2 pixel down to align to pixel boundary
        drawing_context.move_to(0, canvas_size.height-0.5)
        drawing_context.line_to(canvas_size.width, canvas_size.height-0.5)
        drawing_context.stroke_style = '#b0b0b0'
        drawing_context.stroke()
        drawing_context.restore()

        if self.__display_drag_control:
            drawing_context.save()
            drawing_context.begin_path()
            drawing_context.move_to(6, canvas_size.height/2 - 4)
            drawing_context.line_to(16, canvas_size.height/2 - 4)
            drawing_context.move_to(6, canvas_size.height/2 - 1)
            drawing_context.line_to(16, canvas_size.height/2 - 1)
            drawing_context.move_to(6, canvas_size.height/2 + 2)
            drawing_context.line_to(16, canvas_size.height/2 + 2)
            drawing_context.move_to(6, canvas_size.height/2 + 5)
            drawing_context.line_to(16, canvas_size.height/2 + 5)
            drawing_context.stroke_style = '#444'
            drawing_context.stroke()
            drawing_context.restore()

        if self.__display_sync_control:
            drawing_context.save()
            drawing_context.begin_path()
            drawing_context.move_to(24, canvas_size.height/2 - 2)
            drawing_context.line_to(34, canvas_size.height/2 - 2)
            drawing_context.line_to(31, canvas_size.height/2 - 4)
            drawing_context.move_to(34, canvas_size.height/2 + 1)
            drawing_context.line_to(24, canvas_size.height/2 + 1)
            drawing_context.line_to(27, canvas_size.height/2 + 3)
            drawing_context.stroke_style = '#444'
            drawing_context.stroke()
            drawing_context.restore()

        drawing_context.save()
        drawing_context.font = 'normal 11px serif'
        drawing_context.text_align = 'center'
        drawing_context.text_baseline = 'middle'
        drawing_context.fill_style = '#000'
        drawing_context.fill_text(self.title, canvas_size.width/2, canvas_size.height/2+1)
        drawing_context.restore()
