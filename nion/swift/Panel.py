# futures
from __future__ import absolute_import

# standard libraries
import code
import contextlib
import gettext
import logging
import sys
import weakref

# conditional imports
if sys.version < '3':
    import cStringIO as io
else:
    import io

# third party libraries
# None

# local libraries
from nion.ui import CanvasItem
from nion.ui import Geometry
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

    @property
    def document_controller(self):
        return self.__document_controller_weakref()

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
        self.document_controller.queue_task(task)

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


@contextlib.contextmanager
def reassign_stdout(new_stdout, new_stderr):
    oldstdout, oldtsderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = new_stdout, new_stderr
    yield
    sys.stdout, sys.stderr = oldstdout, oldtsderr


class ConsolePanel(Panel):

    def __init__(self, document_controller, panel_id, properties):
        super().__init__(document_controller, panel_id, "Console")
        properties["min-height"] = 180
        properties["stylesheet"] = "background: black; color: white; font: 12px courier, monospace"
        # sys.ps1/2 is not always defined, we'll use it if it is
        self.ps1 = getattr(sys, "ps1", ">>> ")
        self.ps2 = getattr(sys, "ps2", "... ")
        self.widget = self.ui.create_text_edit_widget(properties)
        self.widget.text = self.ps1
        self.widget.on_cursor_position_changed = self.__cursor_position_changed
        self.widget.on_selection_changed = self.__selection_changed
        self.widget.on_return_pressed = self.__return_pressed
        self.widget.on_key_pressed = self.__key_pressed

        locals = {'__name__': None, '__console__': None, '__doc__': None, '_document_controller': document_controller}
        self.console = code.InteractiveConsole(locals)
        lines = [
            "from nion.swift import DocumentController",
            "from nion.swift.model import DocumentModel, DataItem, Image, PlugInManager, Region",
            "from nion.swift.Application import print_stack_all as _bt",
            "from nion.swift.Application import sample_stack_all as _pr",
            "import logging",
            "import numpy as np",
            "import numpy as numpy",
            "import uuid",
            "_document_model = _document_controller.document_model",
            "get_api = PlugInManager.api_broker_fn"
            ]
        for l in lines:
            self.interpret_command(l)
        self.document_controller.register_console(self)

    def close(self):
        self.document_controller.unregister_console(self)
        super().close()

    def insert_lines(self, lines):
        self.widget.insert_lines(lines)

    # interpretCommand is called from the intrinsic widget.
    def interpret_command(self, command):
        output = io.StringIO()
        error = io.StringIO()
        with reassign_stdout(output, error):
            incomplete = self.console.push(command)
        prompt = self.ps2 if incomplete else self.ps1
        if error.getvalue():
            result =  error.getvalue()
            error_code = -1
        else:
            result = output.getvalue()
            error_code = 0
        return result, error_code, prompt

    def __return_pressed(self):
        command = self.widget.text.split('\n')[-1]
        if command.startswith(self.ps1):
            command = command[len(self.ps1):]
        elif command.startswith(self.ps2):
            command = command[len(self.ps2):]
        result, error_code, prompt = self.interpret_command(command)
        self.widget.append_text(result + prompt)
        self.widget.move_cursor_position("end")
        return True

    def __key_pressed(self, key):
        return False

    def __cursor_position_changed(self, cursor_position):
        print("cursor", cursor_position)

    def __selection_changed(self, selection):
        print("selection", selection)


class HeaderCanvasItem(CanvasItem.LayerCanvasItem):

    def __init__(self, title=None, label=None, display_close_control=False):
        super(HeaderCanvasItem, self).__init__()
        self.wants_mouse_events = True
        self.__title = title if title else ""
        self.__label = label if label else ""
        self.__display_close_control = display_close_control
        self.header_height = 20 if sys.platform == "win32" else 22
        self.sizing.set_fixed_height(self.header_height)
        self.on_select_pressed = None
        self.on_drag_pressed = None
        self.on_close_clicked = None
        self.__start_header_color = "#ededed"
        self.__end_header_color = "#cacaca"
        self.__mouse_pressed_position = None

    def close(self):
        self.on_select_pressed = None
        self.on_drag_pressed = None
        self.on_close_clicked = None
        super(HeaderCanvasItem, self).close()

    def __str__(self):
        return self.__title

    @property
    def title(self):
        return self.__title

    @title.setter
    def title(self, title):
        if self.__title != title:
            self.__title = title
            self.update()

    @property
    def label(self):
        return self.__label

    @label.setter
    def label(self, label):
        if self.__label != label:
            self.__label = label
            self.update()

    @property
    def start_header_color(self):
        return self.__start_header_color

    @start_header_color.setter
    def start_header_color(self, start_header_color):
        if self.__start_header_color != start_header_color:
            self.__start_header_color = start_header_color
            self.update()

    @property
    def end_header_color(self):
        return self.__end_header_color

    @end_header_color.setter
    def end_header_color(self, end_header_color):
        if self.__end_header_color != end_header_color:
            self.__end_header_color = end_header_color
            self.update()

    def reset_header_colors(self):
        self.__start_header_color = "#ededed"
        self.__end_header_color = "#cacaca"
        self.update()

    def mouse_pressed(self, x, y, modifiers):
        self.__mouse_pressed_position = Geometry.IntPoint(y=y, x=x)
        return True

    def mouse_position_changed(self, x, y, modifiers):
        pt = Geometry.IntPoint(y=y, x=x)
        if self.__mouse_pressed_position and Geometry.distance(self.__mouse_pressed_position, pt) > 12:
            on_drag_pressed = self.on_drag_pressed
            if callable(on_drag_pressed):
                self.__mouse_pressed_position = None
                on_drag_pressed()

    def mouse_released(self, x, y, modifiers):
        canvas_size = self.canvas_size
        select_ok = self.__mouse_pressed_position is not None
        if self.__display_close_control:
            if x > canvas_size.width - 20 + 4 and x < canvas_size.width - 20 + 18 and y > 2 and y < canvas_size.height - 2:
                on_close_clicked = self.on_close_clicked
                if callable(on_close_clicked):
                    on_close_clicked()
                    select_ok = False
        if select_ok:
            on_select_pressed = self.on_select_pressed
            if callable(on_select_pressed):
                on_select_pressed()
        self.__mouse_pressed_position = None
        return True

    def _repaint(self, drawing_context):

        canvas_size = self.canvas_size

        with drawing_context.saver():
            drawing_context.begin_path()
            drawing_context.move_to(0, 0)
            drawing_context.line_to(0, canvas_size.height)
            drawing_context.line_to(canvas_size.width, canvas_size.height)
            drawing_context.line_to(canvas_size.width, 0)
            drawing_context.close_path()
            gradient = drawing_context.create_linear_gradient(canvas_size.width, canvas_size.height, 0, 0, 0, canvas_size.height)
            gradient.add_color_stop(0, self.__start_header_color)
            gradient.add_color_stop(1, self.__end_header_color)
            drawing_context.fill_style = gradient
            drawing_context.fill()

        with drawing_context.saver():
            drawing_context.begin_path()
            # line is adjust 1/2 pixel down to align to pixel boundary
            drawing_context.move_to(0, 0.5)
            drawing_context.line_to(canvas_size.width, 0.5)
            drawing_context.stroke_style = '#FFF'
            drawing_context.stroke()

        with drawing_context.saver():
            drawing_context.begin_path()
            # line is adjust 1/2 pixel down to align to pixel boundary
            drawing_context.move_to(0, canvas_size.height-0.5)
            drawing_context.line_to(canvas_size.width, canvas_size.height-0.5)
            drawing_context.stroke_style = '#b0b0b0'
            drawing_context.stroke()

        if self.__display_close_control:
            with drawing_context.saver():
                drawing_context.begin_path()
                drawing_context.move_to(canvas_size.width - 20 + 7, canvas_size.height//2 - 3)
                drawing_context.line_to(canvas_size.width - 20 + 13, canvas_size.height//2 + 3)
                drawing_context.move_to(canvas_size.width - 20 + 7, canvas_size.height//2 + 3)
                drawing_context.line_to(canvas_size.width - 20 + 13, canvas_size.height//2 - 3)
                drawing_context.line_width = 2.0
                drawing_context.line_cap = "round"
                drawing_context.stroke_style = '#888'
                drawing_context.stroke()

        with drawing_context.saver():
            drawing_context.font = 'normal 11px serif'
            drawing_context.text_align = 'left'
            drawing_context.text_baseline = 'middle'
            drawing_context.fill_style = '#888'
            drawing_context.fill_text(self.label, 8, canvas_size.height//2+1)

        with drawing_context.saver():
            drawing_context.font = 'normal 11px serif'
            drawing_context.text_align = 'center'
            drawing_context.text_baseline = 'middle'
            drawing_context.fill_style = '#000'
            drawing_context.fill_text(self.title, canvas_size.width//2, canvas_size.height//2+1)
