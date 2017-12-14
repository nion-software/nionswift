# system imports
import ast
import collections
import contextlib
import copy
import functools
import gettext
import os
import threading
import traceback

# typing
from typing import AbstractSet

# third part imports
import numpy

# local libraries
from nion.swift.model import PlugInManager
from nion.swift.model import Utility
from nion.swift import FacadeQueued
from nion.ui import Declarative
from nion.ui import Dialog
from nion.ui import Widgets
from nion.utils import Converter
from nion.utils import Selection

_ = gettext.gettext


def pose_get_string_message_box(ui, message_column, caption, text, accepted_fn, rejected_fn=None, accepted_text=None, rejected_text=None):
    if accepted_text is None:
        accepted_text = _("OK")
    if rejected_text is None:
        rejected_text = _("Cancel")
    message_box_widget = ui.create_column_widget()  # properties={"stylesheet": "background: #FFD"}
    caption_row = ui.create_row_widget()
    caption_row.add_spacing(12)
    caption_row.add(ui.create_label_widget(caption))
    caption_row.add_stretch()
    inside_row = ui.create_row_widget()

    def reject_button_clicked():
        if rejected_fn:
            rejected_fn()
        return False

    def accept_button_clicked():
        accepted_fn(string_edit_widget.text)
        return False

    string_edit_widget = ui.create_line_edit_widget()
    string_edit_widget.text = text
    string_edit_widget.on_return_pressed = accept_button_clicked
    string_edit_widget.on_escape_pressed = reject_button_clicked
    reject_button = ui.create_push_button_widget(rejected_text)
    reject_button.on_clicked = reject_button_clicked
    accepted_button = ui.create_push_button_widget(accepted_text)
    accepted_button.on_clicked = accept_button_clicked
    inside_row.add_spacing(12)
    inside_row.add(string_edit_widget)
    inside_row.add_spacing(12)
    inside_row.add(reject_button)
    inside_row.add_spacing(12)
    inside_row.add(accepted_button)
    inside_row.add_stretch()
    message_box_widget.add_spacing(6)
    message_box_widget.add(caption_row)
    message_box_widget.add_spacing(4)
    message_box_widget.add(inside_row)
    message_box_widget.add_spacing(4)
    message_column.add(message_box_widget)
    string_edit_widget.select_all()
    string_edit_widget.focused = True
    return message_box_widget


def pose_confirmation_message_box(ui, message_column, caption, accepted_fn, rejected_fn=None, accepted_text=None, rejected_text=None, display_rejected=True):
    if accepted_text is None:
        accepted_text = _("OK")
    if rejected_text is None:
        rejected_text = _("Cancel")
    message_box_widget = ui.create_column_widget()  # properties={"stylesheet": "background: #FFD"}

    def reject_button_clicked():
        if rejected_fn:
            rejected_fn()
        return False

    def accept_button_clicked():
        accepted_fn()
        return False

    reject_button = ui.create_push_button_widget(rejected_text)
    reject_button.on_clicked = reject_button_clicked
    accepted_button = ui.create_push_button_widget(accepted_text)
    accepted_button.on_clicked = accept_button_clicked
    caption_row = ui.create_row_widget()
    caption_row.add_spacing(12)
    caption_row.add(ui.create_label_widget(caption))
    if display_rejected:
        caption_row.add_spacing(12)
        caption_row.add(reject_button)
    caption_row.add_spacing(12)
    caption_row.add(accepted_button)
    caption_row.add_stretch()
    message_box_widget.add_spacing(6)
    message_box_widget.add(caption_row)
    message_box_widget.add_spacing(4)
    message_column.add(message_box_widget)
    return message_box_widget


class RunScriptDialog(Dialog.ActionDialog):

    def __init__(self, document_controller):
        ui = document_controller.ui
        super().__init__(ui, _("Interactive Dialog"), document_controller.app, persistent_id="ScriptsDialog")

        self.ui = ui
        self.document_controller = document_controller

        self._create_menus()

        self.__cancelled = False

        self.__thread = None

        properties = dict()
        properties["min-height"] = 180
        properties["min-width"] = 540
        properties["stylesheet"] = "background: white; font-family: Monaco, Courier, monospace"

        self.__output_widget = self.ui.create_text_edit_widget(properties)

        self.__message_column = ui.create_column_widget()

        self.__message_column.add(self.__make_cancel_row())

        items = self.ui.get_persistent_object("interactive_scripts_0", list())

        def selected_changed(indexes: AbstractSet[int]) -> None:
            run_button_widget.enabled = len(indexes) == 1

        def add_clicked() -> None:
            add_dir = self.ui.get_persistent_string("import_directory", "")
            file_paths, filter_str, directory = self.get_file_paths_dialog(_("Add Scripts"), add_dir, "Python Files (*.py)", "Python Files (*.py)")
            self.ui.set_persistent_string("import_directory", directory)
            items.extend(file_paths)
            items.sort()
            list_widget.items = items
            self.ui.set_persistent_object("interactive_scripts_0", items)

        def remove_clicked() -> None:
            indexes = list(list_widget.selected_items)
            for index in sorted(indexes, reverse=True):
                del items[index]
            list_widget.items = items
            self.ui.set_persistent_object("interactive_scripts_0", items)

        def run_clicked() -> None:
            indexes = list_widget.selected_items
            if len(indexes) == 1:
                script_path = items[list(indexes)[0]]
                self.run_script(script_path)

        def item_selected(index: int) -> bool:
            run_clicked()
            return True

        list_widget = Widgets.StringListWidget(ui, items, Selection.Style.single_or_none, properties={"min-height": 200, "min-width": 560})
        list_widget.on_selection_changed = selected_changed
        list_widget.on_item_selected = item_selected

        add_button_widget = ui.create_push_button_widget(_("Add..."))
        add_button_widget.on_clicked = add_clicked

        remove_button_widget = ui.create_push_button_widget(_("Remove"))
        remove_button_widget.on_clicked = remove_clicked

        run_button_widget = ui.create_push_button_widget(_("Run"))
        run_button_widget.on_clicked = run_clicked
        run_button_widget.enabled = False

        list_widget_row = ui.create_row_widget()
        list_widget_row.add_spacing(8)
        list_widget_row.add(list_widget)
        list_widget_row.add_spacing(8)

        close_button_widget = ui.create_push_button_widget(_("Close"))
        close_button_widget.on_clicked = self.request_close

        button_row = ui.create_row_widget()
        button_row.add_spacing(12)
        button_row.add(add_button_widget)
        button_row.add(remove_button_widget)
        button_row.add_stretch()
        button_row.add(run_button_widget)
        button_row.add_spacing(12)

        select_column = ui.create_column_widget()
        select_column.add_spacing(8)
        select_column.add(list_widget_row)
        select_column.add_spacing(8)
        select_column.add(button_row)
        select_column.add_spacing(8)

        run_column = ui.create_column_widget()
        run_column.add(self.__output_widget)
        run_column.add_spacing(6)
        run_column.add(self.__message_column)

        self.__stack = ui.create_stack_widget()

        self.__stack.add(select_column)
        self.__stack.add(run_column)

        self.content.add(self.__stack)

        self.__lock = threading.RLock()

        self.__q = collections.deque()
        self.__output_queue = collections.deque()

    def close(self):
        self.document_controller.clear_task(str(id(self)))
        super().close()

    @property
    def cancelled(self):
        return self.__cancelled

    def __make_cancel_row(self):
        def cancel_script():
            self.__cancelled = True

        cancel_button = self.ui.create_push_button_widget(_("Cancel"))
        cancel_button.on_clicked = cancel_script
        cancel_row = self.ui.create_row_widget()
        cancel_row.add_stretch()
        cancel_row.add(cancel_button)
        cancel_row.add_spacing(12)
        return cancel_row

    def run_script(self, script_path: str) -> None:
        self.__output_widget.text = None

        script_name = os.path.basename(script_path)

        self.title = os.path.splitext(script_name)[0]

        try:
            with open(script_path) as f:
                script = f.read()

            script_ast = ast.parse(script, script_name, 'exec')
        except Exception as e:
            self.print(str(e))
            self.__stack.current_index = 1
            self.continue_after_parse_error(script_path)
            return

        class AddCallFunctionNodeTransformer(ast.NodeTransformer):
            def __init__(self, func_id, arg_id):
                self.__func_id = func_id
                self.__arg_id = arg_id

            def visit_Module(self, node):
                name_expr = ast.Name(id=self.__func_id, ctx=ast.Load())
                arg_expr = ast.Name(id=self.__arg_id, ctx=ast.Load())
                call_expr = ast.Expr(value=ast.Call(func=name_expr, args=[arg_expr], keywords=[]))
                new_node = copy.deepcopy(node)
                new_node.body.append(call_expr)
                ast.fix_missing_locations(new_node)
                return new_node

        # if script_main exists, add a node to call it
        for node in script_ast.body:
            if getattr(node, "name", None) == "script_main":
                script_ast = AddCallFunctionNodeTransformer('script_main', 'api_broker').visit(script_ast)

        compiled = compile(script_ast, script_name, 'exec')

        def run_it(compiled, interactive_session):
            class APIBroker:
                def get_interactive(self, version=None):
                    actual_version = "1.0.0"
                    if Utility.compare_versions(version, actual_version) > 0:
                        raise NotImplementedError("API requested version %s is greater than %s." % (version, actual_version))
                    return interactive_session
                def get_api(self, version, ui_version=None):
                    ui_version = ui_version if ui_version else "~1.0"
                    api = PlugInManager.api_broker_fn(version, ui_version)
                    queued_api = FacadeQueued.API(api, None)
                    queued_api._queue_task = api.queue_task
                    return queued_api
                def get_ui(self, version):
                    actual_version = "1.0.0"
                    if Utility.compare_versions(version, actual_version) > 0:
                        raise NotImplementedError("API requested version %s is greater than %s." % (version, actual_version))
                    return Declarative.DeclarativeUI()
            try:
                g = dict()
                g["api_broker"] = APIBroker()
                g["print"] = self.print
                g["input"] = self.get_string

                print_fn = self.print
                class StdoutCatcher:
                    def __init__(self):
                        pass
                    def write(self, stuff):
                        print_fn(stuff.rstrip())
                    def flush(self):
                        pass
                stdout = StdoutCatcher()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stdout):
                    exec(compiled, g)
            except Exception:
                self.print("{}: {}".format(_("Error"), traceback.format_exc()))

        self.__stack.current_index = 1

        self.run(script_path, functools.partial(run_it, compiled))

    def continue_after_parse_error(self, script_path):
        def func_continue():
            result = self.confirm(_("Finished"), _("Run Again"), _("Close"))

            with self.__lock:
                if result:
                    self.__q.append(functools.partial(self.run_script, script_path))
                else:
                    self.__q.append(self.request_close)
                self.document_controller.add_task(str(id(self)), self.__handle_output_and_q)

        self.__thread = threading.Thread(target=func_continue)
        self.__thread.start()

    def run(self, script_path, func):
        def func_run(func):
            try:
                func(self)
            except Exception:
                pass

            result = self.confirm(_("Finished"), _("Run Again"), _("Close"))

            with self.__lock:
                if result:
                    self.__q.append(functools.partial(self.run_script, script_path))
                else:
                    self.__q.append(self.request_close)
                self.document_controller.add_task(str(id(self)), self.__handle_output_and_q)

        self.__thread = threading.Thread(target=func_run, args=(func,))
        self.__thread.start()

    def __handle_output_and_q(self):
        func = None
        with self.__lock:
            while len(self.__output_queue) > 0:
                self.__output_widget.move_cursor_position("end")
                self.__output_widget.append_text(self.__output_queue.popleft())
            while len(self.__q) > 0:
                func = self.__q.popleft()
        if callable(func):
            func()

    def print(self, text):
        with self.__lock:
            self.__output_queue.append(str(text))
            self.document_controller.add_task(str(id(self)), self.__handle_output_and_q)

    def print_debug(self, text):
        self.print(text)

    def print_info(self, text):
        self.print(text)

    def print_warn(self, text):
        self.print(text)

    def get_string(self, prompt, default_str=None) -> str:
        """Return a string value that the user enters. Raises exception for cancel."""
        accept_event = threading.Event()
        value_ref = [None]

        def perform():
            def accepted(text):
                value_ref[0] = text
                self.__message_column.add(self.__make_cancel_row())
                accept_event.set()

            def rejected():
                self.__message_column.add(self.__make_cancel_row())
                accept_event.set()

            self.__message_column.remove_all()
            pose_get_string_message_box(self.ui, self.__message_column, prompt, str(default_str), accepted, rejected)

        with self.__lock:
            self.__q.append(perform)
            self.document_controller.add_task(str(id(self)), self.__handle_output_and_q)
        accept_event.wait()
        if value_ref[0] is None:
            raise Exception("Cancel")
        return value_ref[0]

    def get_integer(self, prompt: str, default_value: int=0) -> int:
        converter = Converter.IntegerToStringConverter()
        result = self.get_string(prompt, converter.convert(default_value))
        return converter.convert_back(result)

    def get_float(self, prompt: str, default_value: float=0, format_str: str=None) -> float:
        converter = Converter.FloatToStringConverter(format_str)
        result = self.get_string(prompt, converter.convert(default_value))
        return converter.convert_back(result)

    def show_ndarray(self, data: numpy.ndarray, title:str = None) -> None:
        accept_event = threading.Event()
        def perform():
            data_item = self.document_controller.add_data(data, title)
            result_display_panel = self.document_controller.next_result_display_panel()
            if result_display_panel:
                result_display_panel.set_display_panel_data_item(data_item)
                result_display_panel.request_focus()
            accept_event.set()

        with self.__lock:
            self.__q.append(perform)
            self.document_controller.add_task(str(id(self)), self.__handle_output_and_q)
        accept_event.wait()

    def __accept_reject(self, prompt, accepted_text, rejected_text, display_rejected):
        """Return a boolean value for accept/reject."""
        accept_event = threading.Event()
        result_ref = [False]

        def perform():
            def accepted():
                result_ref[0] = True
                self.__message_column.add(self.__make_cancel_row())
                accept_event.set()

            def rejected():
                result_ref[0] = False
                self.__message_column.add(self.__make_cancel_row())
                accept_event.set()

            self.__message_column.remove_all()
            pose_confirmation_message_box(self.ui, self.__message_column, prompt, accepted, rejected, accepted_text, rejected_text, display_rejected)

        with self.__lock:
            self.__q.append(perform)
            self.document_controller.add_task(str(id(self)), self.__handle_output_and_q)
        accept_event.wait()
        return result_ref[0]

    def confirm_ok_cancel(self, prompt: str) -> bool:
        return self.__accept_reject(prompt, _("OK"), _("Cancel"), True)

    def confirm_yes_no(self, prompt: str) -> bool:
        return self.__accept_reject(prompt, _("Yes"), _("No"), True)

    def confirm(self, prompt: str, accepted_text: str, rejected_text: str) -> bool:
        return self.__accept_reject(prompt, accepted_text, rejected_text, True)

    def alert(self, prompt: str, button_label: str = None) -> None:
        self.__accept_reject(prompt, button_label, None, False)
