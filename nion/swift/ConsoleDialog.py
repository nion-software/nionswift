from __future__ import annotations

# system imports
import code
import contextlib
import copy
import dataclasses
import gettext
import importlib
import io
import logging
import re
import sys
import types
import typing

# local libraries
from nion.swift import Panel
from nion.swift.model import DocumentModel
from nion.swift.model import Persistence
from nion.ui import Dialog
from nion.ui import UserInterface
from nion.ui import Widgets
from nion.utils import Registry

# hack to work with conda/python3.10 until they fix readline
rlcompleter: typing.Optional[types.ModuleType]
try:
    rlcompleter = importlib.import_module("rlcompleter")
except Exception:
    rlcompleter = None

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController

_ = gettext.gettext


@dataclasses.dataclass
class ConsoleStartupInfo:
    console_startup_id: str
    console_startup_lines: typing.Sequence[str]
    console_startup_help: typing.Optional[typing.Sequence[str]]


class ConsoleStartupComponent(typing.Protocol):
    def get_console_startup_info(self, logger: logging.Logger) -> ConsoleStartupInfo: ...


class ConsoleWidgetStateController:
    delims = " \t\n`~!@#$%^&*()-=+[{]}\\|;:\'\",<>/?"

    def __init__(self, locals: typing.Dict[str, typing.Any]) -> None:
        self.__incomplete = False

        self.__console = code.InteractiveConsole(locals)

        self.__history: typing.List[str] = list()
        self.__history_point: typing.Optional[int] = None
        self.__command_cache: typing.Tuple[typing.Optional[int], str] = (None, str()) # Meaning of the tuple: (history_point where the command belongs, command)

    def close(self) -> None:
        # through experimentation, this is how to ensure the locals are
        # garbage collected upon closing.
        typing.cast(typing.Dict[str, typing.Any], self.__console.locals).clear()
        self.__console.locals = typing.cast(typing.Any, None)
        self.__console = typing.cast(typing.Any, None)

    @staticmethod
    def get_common_prefix(l: typing.List[str]) -> str:
        if not l:
            return str()
        s1 = min(l)  # return the first, alphabetically
        s2 = max(l)  # the last
        # check common characters in between
        for i, c in enumerate(s1):
            if c != s2[i]:
                return s1[:i]
        return s1

    @property
    def incomplete(self) -> bool:
        return self.__incomplete

    # interpretCommand is called from the intrinsic widget.
    def interpret_command(self, command: str) -> typing.Tuple[str, int]:
        if command:
            self.__history.append(command)
        self.__history_point = None
        self.__command_cache = (None, str())
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            self.__incomplete = self.__console.push(command)
        if error.getvalue():
            result =  error.getvalue()
            error_code = -1
        else:
            result = output.getvalue()
            error_code = 0
        return result, error_code

    def complete_command(self, command: str) -> typing.Tuple[str, typing.List[str]]:
        terms = list()
        completed_command = command
        if rlcompleter:
            completer = rlcompleter.Completer(namespace=getattr(self.__console, "locals"))  # TODO: why isn't locals defined?
            index = 0
            rx = "([" + re.escape(ConsoleWidgetStateController.delims) + "])"
            # the parenthesis around rx make it a group. This will cause split to keep the characters in rx in the
            # list, so that we can reconstruct the original string later
            split_commands = re.split(rx, command)
            if len(split_commands) > 0:
                completion_term = split_commands[-1]
                while True:
                    term = completer.complete(completion_term, index)
                    if term is None:
                        break
                    index += 1
                    # for some reason rlcomplete returns "\t" when completing "", so exclude that case here
                    if not term.startswith(completion_term + "__") and term != "\t":
                        terms.append(term)
                if len(terms) == 1:
                    completed_command = command[:command.rfind(completion_term)] + terms[0]
                    terms = list()
                elif len(terms) > 1:
                    common_prefix = ConsoleWidgetStateController.get_common_prefix(terms)
                    completed_command = str().join(split_commands[:-1]) + common_prefix
        return completed_command, terms

    def move_back_in_history(self, current_line: str) -> str:
        line = str()
        if self.__history_point is None:
            self.__history_point = len(self.__history)
            # do not update command_cache if the user didn't type anything
            if current_line:
                self.__command_cache = (None, current_line)
        elif self.__history_point < len(self.__history):
            # This means the user changed something at the current point in history. Save the temporary command.
            if current_line != self.__history[self.__history_point]:
                self.__command_cache = (self.__history_point, current_line)
        self.__history_point = max(0, self.__history_point - 1)
        if self.__history_point < len(self.__history):
            line = self.__command_cache[1] if self.__command_cache[0] == self.__history_point else self.__history[self.__history_point]
        return line

    def move_forward_in_history(self, current_line: str) -> str:
        line = str()
        if self.__history_point is not None:
            if self.__history_point < len(self.__history):
                # This means the user changed something at the current point in history.
                # Save the temporary command, but only if the user actually typed something
                if current_line and current_line != self.__history[self.__history_point]:
                    self.__command_cache = (self.__history_point, current_line)
            self.__history_point = min(len(self.__history), self.__history_point + 1)
            if self.__history_point < len(self.__history):
                line = self.__command_cache[1] if self.__command_cache[0] == self.__history_point else self.__history[self.__history_point]
            else:
                self.__history_point = None
        # Do not use 'else' here because history_point might have been set to 'None' in the first 'if' statement
        if self.__history_point is None:
            line = self.__command_cache[1] if self.__command_cache[0] is None else str()
        return line


class ConsoleWidget(Widgets.CompositeWidgetBase):

    def __init__(self,
                 ui: UserInterface.UserInterface,
                 logger: logging.Logger,
                 locals: typing.Optional[typing.Dict[str, typing.Any]] = None,
                 properties: typing.Optional[Persistence.PersistentDictType] = None) -> None:
        content_widget = ui.create_column_widget()
        super().__init__(content_widget)

        self.__logger = logger

        self.prompt = ">>> "
        self.continuation_prompt = "... "

        self.__cursor_position: typing.Optional[UserInterface.CursorPosition] = None

        self.__text_edit_widget = ui.create_text_edit_widget(properties)
        self.__text_edit_widget.set_text_color("white")
        self.__text_edit_widget.set_text_background_color("black")
        self.__text_edit_widget.set_text_font(Panel.Panel.get_monospace_text_font())
        self.__text_edit_widget.set_line_height_proportional(Panel.Panel.get_monospace_proportional_line_height())
        self.__text_edit_widget.word_wrap_mode = "anywhere"
        self.__text_edit_widget.on_cursor_position_changed = self.__cursor_position_changed
        self.__text_edit_widget.on_return_pressed = self.__return_pressed
        self.__text_edit_widget.on_key_pressed = self.__key_pressed
        self.__text_edit_widget.on_insert_mime_data = self.__insert_mime_data

        class StdoutCatcher:
            def __init__(self, text_edit_widget: UserInterface.TextEditWidget) -> None:
                self.__text_edit_widget = text_edit_widget

            def write(self, stuff: str) -> int:
                if self.__text_edit_widget:
                    stripped_stuff = str(stuff).rstrip()
                    self.__text_edit_widget.append_text(stripped_stuff)
                    return len(stripped_stuff)
                return 0

            def flush(self) -> None:
                pass

        stdout = StdoutCatcher(self.__text_edit_widget)

        class LoggingHandler(logging.Handler):

            def __init__(self, console_widget: ConsoleWidget) -> None:
                super().__init__()
                self.__console_widget = console_widget
                self._prompted = False

            def emit(self, record: logging.LogRecord) -> None:
                if record.levelno >= logging.INFO:
                    color = None if self._prompted else "grey"
                    self.__console_widget.append_line(str(record.getMessage()).rstrip(), color=color)

        self.__logging_handler = LoggingHandler(self)
        self.__logger.addHandler(self.__logging_handler)

        locals = locals if locals is not None else dict()
        locals.update({'__name__': None, '__console__': None, '__doc__': None, '_stdout': stdout})

        self.__state_controller = ConsoleWidgetStateController(locals)

        self.__last_cursor_position: typing.Optional[UserInterface.CursorPosition] = None

        content_widget.add(self.__text_edit_widget)

    def close(self) -> None:
        super().close()
        self.__text_edit_widget = typing.cast(typing.Any, None)
        self.__state_controller.close()
        self.__state_controller = typing.cast(typing.Any, None)

    def show_prompt(self) -> None:
        self.__logging_handler._prompted = True
        self.__text_edit_widget.append_text(self.prompt)
        self.__text_edit_widget.move_cursor_position("end")
        self.__last_cursor_position = copy.deepcopy(self.__cursor_position)

    def activate(self) -> None:
        self.__text_edit_widget.focused = True

    @property
    def current_prompt(self) -> str:
        return self.continuation_prompt if self.__state_controller.incomplete else self.prompt

    def insert_lines(self, lines: typing.Sequence[str]) -> None:
        for l in lines:
            self.__text_edit_widget.move_cursor_position("end")
            self.__text_edit_widget.insert_text(l)
            result, error_code = self.__state_controller.interpret_command(l)
            if len(result) > 0:
                self.__text_edit_widget.set_text_color("red" if error_code else "aquamarine")
                self.__text_edit_widget.append_text(result[:-1])
                self.__text_edit_widget.set_text_color("white")
            self.__text_edit_widget.append_text(self.current_prompt)
            self.__text_edit_widget.move_cursor_position("end")
            self.__last_cursor_position = copy.deepcopy(self.__cursor_position)

    def append_line(self, line: str, *, color: typing.Optional[str] = None) -> None:
        self.__text_edit_widget.set_text_color(color if color else "aquamarine")
        self.__text_edit_widget.append_text(line)
        self.__text_edit_widget.set_text_color("white")

    def interpret_lines(self, lines: typing.Sequence[str]) -> None:
        for l in lines:
            self.__state_controller.interpret_command(l)

    def __return_pressed(self) -> bool:
        command = self.__get_partial_command()
        result, error_code = self.__state_controller.interpret_command(command)
        if len(result) > 0:
            self.__text_edit_widget.set_text_color("red" if error_code else "aquamarine")
            self.__text_edit_widget.append_text(result[:-1])
        self.__text_edit_widget.set_text_color("white")
        self.__text_edit_widget.append_text(self.current_prompt)
        self.__text_edit_widget.move_cursor_position("end")
        self.__last_cursor_position = copy.deepcopy(self.__cursor_position)
        return True

    def __get_partial_command(self) -> str:
        text = self.__text_edit_widget.text
        command = text.split('\n')[-1] if text else str()
        if command.startswith(self.prompt):
            command = command[len(self.prompt):]
        elif command.startswith(self.continuation_prompt):
            command = command[len(self.continuation_prompt):]
        return command

    def __key_pressed(self, key: UserInterface.Key) -> bool:
        block_number = self.__cursor_position.block_number if self.__cursor_position else None
        last_block_number = self.__last_cursor_position.block_number if self.__last_cursor_position else None
        is_cursor_on_last_line = block_number == last_block_number
        partial_command = self.__get_partial_command()
        column_number = self.__cursor_position.column_number if self.__cursor_position else 0
        is_cursor_on_last_column = (partial_command.strip() and column_number == len(self.current_prompt + partial_command))

        if is_cursor_on_last_line and key.is_up_arrow:
            line = self.__state_controller.move_back_in_history(partial_command)
            self.__text_edit_widget.move_cursor_position("start_para", "move")
            self.__text_edit_widget.move_cursor_position("end_para", "keep")
            self.__text_edit_widget.insert_text("{}{}".format(self.current_prompt, line))
            self.__text_edit_widget.move_cursor_position("end")
            self.__last_cursor_position = copy.deepcopy(self.__cursor_position)
            return True

        if is_cursor_on_last_line and key.is_down_arrow:
            line = self.__state_controller.move_forward_in_history(partial_command)
            self.__text_edit_widget.move_cursor_position("start_para", "move")
            self.__text_edit_widget.move_cursor_position("end_para", "keep")
            self.__text_edit_widget.insert_text("{}{}".format(self.current_prompt, line))
            self.__text_edit_widget.move_cursor_position("end")
            self.__last_cursor_position = copy.deepcopy(self.__cursor_position)
            return True

        if is_cursor_on_last_line and key.is_delete:
            if not partial_command:
                return True

        if is_cursor_on_last_line and key.is_move_to_start_of_line:
            mode = "keep" if key.modifiers.shift else "move"
            self.__text_edit_widget.move_cursor_position("start_para", mode)
            self.__text_edit_widget.move_cursor_position("next", mode, n=4)
            return True

        if is_cursor_on_last_line and key.is_delete_to_end_of_line:
            self.__text_edit_widget.move_cursor_position("end_para", "keep")
            self.__text_edit_widget.remove_selected_text()
            return True

        if is_cursor_on_last_line and key.key == 0x43 and key.modifiers.native_control and sys.platform == "darwin":
            self.__text_edit_widget.move_cursor_position("end")
            self.__text_edit_widget.insert_text("\n")
            self.__text_edit_widget.insert_text(self.current_prompt)
            self.__text_edit_widget.move_cursor_position("end")
            self.__last_cursor_position = copy.deepcopy(self.__cursor_position)
            return True

        if is_cursor_on_last_line and is_cursor_on_last_column and key.is_tab:
            completed_command, terms = self.__state_controller.complete_command(partial_command)
            if not terms:
                self.__text_edit_widget.move_cursor_position("start_para", "move")
                self.__text_edit_widget.move_cursor_position("end_para", "keep")
                self.__text_edit_widget.insert_text("{}{}".format(self.current_prompt, completed_command))
                self.__text_edit_widget.move_cursor_position("end")
                self.__last_cursor_position = copy.deepcopy(self.__cursor_position)
            elif len(terms) > 1:
                self.__text_edit_widget.move_cursor_position("end")
                self.__text_edit_widget.set_text_color("brown")
                self.__text_edit_widget.append_text("   ".join(terms) + "\n")
                self.__text_edit_widget.move_cursor_position("end")
                self.__text_edit_widget.set_text_color("white")
                self.__text_edit_widget.insert_text("{}{}".format(self.current_prompt, completed_command))
                self.__text_edit_widget.move_cursor_position("end")
                self.__last_cursor_position = copy.deepcopy(self.__cursor_position)
            return True
        return False

    def __cursor_position_changed(self, cursor_position: UserInterface.CursorPosition) -> None:
        self.__cursor_position = copy.deepcopy(cursor_position)

    def __insert_mime_data(self, mime_data: UserInterface.MimeData) -> None:
        text = mime_data.data_as_string("text/plain")
        text_lines = re.split("[" + re.escape("\n") + re.escape("\r") + "]", text)
        if not text_lines[-1]:
            text_lines = text_lines[:-1]
        if len(text_lines) == 1 and text_lines[0] == text.rstrip():
            # special case where text has no line terminator
            self.__text_edit_widget.insert_text(text)
        else:
            self.insert_lines(text_lines)


class DefaultConsoleStartupComponent:
    def get_console_startup_info(self, logger: logging.Logger) -> ConsoleStartupInfo:
        logger.info("Console Startup (logger, api, ui, show, etc.)")
        lines = [
            "import logging",
            "import numpy as np",
            "import numpy as numpy",
            "import uuid",
            "from nion.utils import Registry",
            "from nion.swift.model import PlugInManager",
            "from nion.ui import Declarative",
            "from nion.data import xdata_1_0 as xd",
            "get_api = PlugInManager.api_broker_fn",
            "api = get_api('~1.0', '~1.0')",
            "ui = Declarative.DeclarativeUI()",
            "show = api.show",
            "def run_script(*args, **kwargs):",
            "  api.run_script(*args, stdout=_stdout, **kwargs)",
            "",
            f"logger = logging.getLogger('console-loggers-{ConsoleDialog.console_number}')",
            ]

        variable_to_item_map = DocumentModel.MappedItemManager().item_map
        for variable_name, data_item in variable_to_item_map.items():
            data_item_specifier = data_item.item_specifier
            lines.append(f"{variable_name} = api.library.get_item_by_specifier(api.create_specifier(item_uuid=uuid.UUID('{str(data_item_specifier.item_uuid)}')))")

        return ConsoleStartupInfo("default_startup", lines, None)


Registry.register_component(DefaultConsoleStartupComponent(), {"console-startup"})


class ConsoleDialog(Dialog.ActionDialog):

    console_number = 0

    def __init__(self, document_controller: DocumentController.DocumentController) -> None:
        super().__init__(document_controller.ui, _("Python Console"), parent_window=document_controller, persistent_id="ConsoleDialog")

        self.__document_controller = document_controller

        ConsoleDialog.console_number += 1
        logger = logging.getLogger(f"console-loggers-{ConsoleDialog.console_number}")

        self.__console_widget = ConsoleWidget(document_controller.ui, logger, properties={"min-height": 180, "min-width": 540})

        lines: list[str] = list()
        for component in Registry.get_components_by_type("console-startup"):
            console_startup_component = typing.cast(ConsoleStartupComponent, component)
            lines.extend(console_startup_component.get_console_startup_info(logger).console_startup_lines)

        self.__console_widget.interpret_lines(lines)

        self.__console_widget.show_prompt()

        self.content.add(self.__console_widget)

        self.__document_controller.register_console(self)

        self._create_menus()

    def close(self) -> None:
        self.__document_controller.unregister_console(self)
        super().close()

    def about_to_show(self) -> None:
        super().about_to_show()
        def request_focus() -> None:
            self.activate()
            self.__console_widget.activate()
        self.queue_task(request_focus)

    def assign_item_var(self, item_var: str, item: Persistence.PersistentObject) -> None:
        self.__console_widget.insert_lines([f"{item_var} = api.library.get_item_by_specifier(api.create_specifier(uuid.UUID(\"{item.uuid}\")))"])
