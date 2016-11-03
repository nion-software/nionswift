# system imports
import code
import contextlib
import copy
import gettext
import io
import rlcompleter
import sys

# local libraries
from nion.swift import Panel
from nion.ui import Dialog
from nion.ui import Widgets

_ = gettext.gettext


@contextlib.contextmanager
def reassign_stdout(new_stdout, new_stderr):
    oldstdout, oldtsderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = new_stdout, new_stderr
    yield
    sys.stdout, sys.stderr = oldstdout, oldtsderr


class ConsoleWidget(Widgets.CompositeWidgetBase):

    def __init__(self, document_controller, locals=None, properties=None):
        ui = document_controller.ui
        super().__init__(ui.create_column_widget())

        self.document_controller = document_controller

        properties = properties if properties is not None else dict()
        properties["stylesheet"] = "background: black; color: white; font: 12px courier, monospace"

        self.prompt = ">>> "
        self.continuation_prompt = "... "

        self.__text_edit_widget = ui.create_text_edit_widget(properties)
        self.__text_edit_widget.on_cursor_position_changed = self.__cursor_position_changed
        self.__text_edit_widget.on_selection_changed = self.__selection_changed
        self.__text_edit_widget.on_return_pressed = self.__return_pressed
        self.__text_edit_widget.on_key_pressed = self.__key_pressed
        self.__text_edit_widget.on_insert_mime_data = self.__insert_mime_data

        locals = locals if locals is not None else dict()
        locals.update({'__name__': None, '__console__': None, '__doc__': None})
        self.console = code.InteractiveConsole(locals)
        self.__text_edit_widget.append_text(self.prompt)
        self.__text_edit_widget.move_cursor_position("end")
        self.__last_position = copy.deepcopy(self.__cursor_position)
        self.document_controller.register_console(self)

        self.content_widget.add(self.__text_edit_widget)

        self.__history = list()
        self.__history_point = None

    def close(self):
        self.document_controller.unregister_console(self)
        super().close()

    def insert_lines(self, lines):
        for l in lines:
            self.__text_edit_widget.move_cursor_position("end")
            self.__text_edit_widget.insert_text(l)
            result, error_code, prompt = self.interpret_command(l)
            if len(result) > 0:
                self.__text_edit_widget.set_text_color("red" if error_code else "green")
                self.__text_edit_widget.append_text(result[:-1])
                self.__text_edit_widget.set_text_color("white")
            self.__text_edit_widget.append_text(prompt)
            self.__text_edit_widget.move_cursor_position("end")
            self.__last_position = copy.deepcopy(self.__cursor_position)
            if l: self.__history.append(l)
            self.__history_point = None

    # interpretCommand is called from the intrinsic widget.
    def interpret_command(self, command):
        output = io.StringIO()
        error = io.StringIO()
        with reassign_stdout(output, error):
            self.__incomplete = self.console.push(command)
        prompt = self.continuation_prompt if self.__incomplete else self.prompt
        if error.getvalue():
            result =  error.getvalue()
            error_code = -1
        else:
            result = output.getvalue()
            error_code = 0
        return result, error_code, prompt

    def interpret_lines(self, lines):
        for l in lines:
            self.interpret_command(l)

    def __return_pressed(self):
        command = self.__get_partial_command()
        result, error_code, prompt = self.interpret_command(command)
        if len(result) > 0:
            self.__text_edit_widget.set_text_color("red" if error_code else "green")
            self.__text_edit_widget.append_text(result[:-1])
            self.__text_edit_widget.set_text_color("white")
        self.__text_edit_widget.append_text(prompt)
        self.__text_edit_widget.move_cursor_position("end")
        self.__last_position = copy.deepcopy(self.__cursor_position)
        if command: self.__history.append(command)
        self.__history_point = None
        return True

    def __get_partial_command(self):
        command = self.__text_edit_widget.text.split('\n')[-1]
        if command.startswith(self.prompt):
            command = command[len(self.prompt):]
        elif command.startswith(self.continuation_prompt):
            command = command[len(self.continuation_prompt):]
        return command

    def __key_pressed(self, key):
        is_cursor_on_last_line = self.__cursor_position.block_number == self.__last_position.block_number

        if is_cursor_on_last_line and key.is_up_arrow:
            if self.__history_point is None:
                self.__history_point = len(self.__history)
            self.__history_point = max(0, self.__history_point - 1)
            if self.__history_point < len(self.__history):
                line = self.__history[self.__history_point]
                self.__text_edit_widget.move_cursor_position("start_line", "move")
                self.__text_edit_widget.move_cursor_position("end_line", "keep")
                prompt = self.continuation_prompt if self.__incomplete else self.prompt
                self.__text_edit_widget.insert_text("{}{}".format(prompt, line))
                self.__text_edit_widget.move_cursor_position("end")
                self.__last_position = copy.deepcopy(self.__cursor_position)
            return True

        if is_cursor_on_last_line and key.is_down_arrow:
            if self.__history_point is not None:
                self.__history_point = min(len(self.__history), self.__history_point + 1)
                if self.__history_point < len(self.__history):
                    line = self.__history[self.__history_point]
                else:
                    self.__history_point = None
                    line = ""
                self.__text_edit_widget.move_cursor_position("start_line", "move")
                self.__text_edit_widget.move_cursor_position("end_line", "keep")
                prompt = self.continuation_prompt if self.__incomplete else self.prompt
                self.__text_edit_widget.insert_text("{}{}".format(prompt, line))
                self.__text_edit_widget.move_cursor_position("end")
                self.__last_position = copy.deepcopy(self.__cursor_position)

        if is_cursor_on_last_line and key.is_delete:
            partial_command = self.__get_partial_command()
            if not partial_command:
                return True

        if is_cursor_on_last_line and key.is_tab:
            partial_command = self.__get_partial_command()
            terms = list()
            completer = rlcompleter.Completer(namespace=self.console.locals)
            index = 0
            while True:
                term = completer.complete(partial_command, index)
                if term is None:
                    break
                index += 1
                if not term.startswith(partial_command + "__"):
                    terms.append(term)
            if len(terms) == 1:
                prompt = self.continuation_prompt if self.__incomplete else self.prompt
                self.__text_edit_widget.move_cursor_position("start_line", "move")
                self.__text_edit_widget.move_cursor_position("end_line", "keep")
                self.__text_edit_widget.insert_text("{}{}".format(prompt, terms[0]))
                self.__text_edit_widget.move_cursor_position("end")
                self.__last_position = copy.deepcopy(self.__cursor_position)
            elif len(terms) > 1:
                prompt = self.continuation_prompt if self.__incomplete else self.prompt
                self.__text_edit_widget.move_cursor_position("end")
                self.__text_edit_widget.set_text_color("brown")
                self.__text_edit_widget.append_text("   ".join(terms) + "\n")
                self.__text_edit_widget.move_cursor_position("end")
                self.__text_edit_widget.set_text_color("white")
                self.__text_edit_widget.insert_text("{}{}".format(prompt, partial_command))
                self.__text_edit_widget.move_cursor_position("end")
                self.__last_position = copy.deepcopy(self.__cursor_position)
            return True

        return False

    def __cursor_position_changed(self, cursor_position):
        self.__cursor_position = copy.deepcopy(cursor_position)

    def __selection_changed(self, selection):
        pass

    def __insert_mime_data(self, mime_data):
        text = mime_data.data_as_string("text/plain")
        text_lines = text.split()
        if len(text_lines) == 1 and text_lines[0] == text.rstrip():
            # special case where text has no line terminator
            self.__text_edit_widget.insert_text(text)
        else:
            self.insert_lines(text_lines)



class ConsoleDialog(Dialog.ActionDialog):

    def __init__(self, document_controller):
        super().__init__(document_controller.ui, _("Python Console"))

        console_widget = ConsoleWidget(document_controller, properties={"min-height": 180, "min-width": 540})
        lines = [
            "import logging",
            "import numpy as np",
            "import numpy as numpy",
            "import uuid",
            "from nion.swift.model import PlugInManager",
            "get_api = PlugInManager.api_broker_fn",
            "api = get_api('~1.0', '~1.0')"
            ]
        for l in lines:
            console_widget.interpret_command(l)

        self.content.add(console_widget)



class ConsolePanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super().__init__(document_controller, panel_id, "Console")

        console_widget = ConsoleWidget(document_controller, locals={"_document_window": document_controller}, properties={"min-height": 180, "min-width": 540})

        lines = [
            "from nion.swift import DocumentController",
            "from nion.swift.model import DocumentModel, DataItem, PlugInManager, Graphics",
            "from nion.data import Image",
            "import logging",
            "import numpy as np",
            "import numpy as numpy",
            "import uuid",
            "_document_model = _document_window.document_model",
            ]

        console_widget.interpret_lines(lines)

        self.widget = console_widget
