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
import typing
import re
import locale
from importlib import reload
import sys
import json

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
from nion.utils import Geometry

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


class ScriptListItem:
    __version__ = "1"

    def __init__(self, full_path: str, indent: int = 0, show_dirname: bool = True):
        self.__full_path = os.path.abspath(full_path)
        self._exists = None
        self.indent = indent
        self.show_dirname = show_dirname

    @property
    def full_path(self) -> str:
        return self.__full_path

    @property
    def basename(self) -> str:
        return os.path.basename(self.full_path)

    @property
    def dirname(self) -> str:
        return os.path.dirname(self.full_path)

    @property
    def exists(self) -> bool:
        return self._exists

    def check_existance(self) -> bool:
        self._exists = os.path.exists(self.full_path)
        return self._exists

    def to_dict(self) -> dict:
        return {"__version__": ScriptListItem.__version__,
                "__type__": "ScriptListItem",
                "full_path": self.full_path,
                "indent": self.indent,
                "show_dirname": self.show_dirname,
                "_exists": self._exists}

    @classmethod
    def from_dict(cls, cls_dict: dict) -> "ScriptListItem":
        version = cls_dict.pop("__version__")
        if version != cls.__version__:
            raise ValueError(f"Cannot read the dictionary provided. Dictionary version '{version}' != implemented version '{cls.__version__}'.")
        instance = cls(cls_dict.pop("full_path"))
        for key, value in cls_dict.items():
            attr_name = key
            if key.startswith("__"):
                attr_name = "_" + cls.__name__ + key
            if hasattr(instance, attr_name):
                setattr(instance, attr_name, value)
        return instance

    def to_json_string(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json_string(cls, json_string: str) -> "ScriptListItem":
        return cls.from_dict(json.loads(json_string))

    # Used by "sort"
    def __lt__(self, other) -> bool:
        if isinstance(other, FolderListItem):
            return False
        if isinstance(other, ScriptListItem):
            return locale.strxfrm(self.basename) < locale.strxfrm(other.basename)
        return NotImplemented


class FolderListItem(ScriptListItem):
    __version__ = "1"

    def __init__(self, full_path: str, content: typing.Optional[typing.List[ScriptListItem]] = None, indent: int = 0, show_dirname: bool = True):
        super().__init__(full_path)
        self.__content = content if content is not None else list()
        self.folder_closed = True

    @property
    def content(self) -> typing.List[ScriptListItem]:
        return self.__content

    def update_content_from_file_system(self, filter_pattern: typing.Optional[str] = None):
        if os.path.isdir(self.full_path):
            dirlist = os.listdir(self.full_path)
            filtered_items = list()
            for item in dirlist:
                if filter_pattern is None or re.search(filter_pattern, item):
                    filtered_items.append(ScriptListItem(os.path.join(self.full_path, item), indent=20, show_dirname=False))
            self.__content = filtered_items

    def to_dict(self) -> dict:
        return {"__version__": FolderListItem.__version__,
                "__type__": "FolderListItem",
                "full_path": self.full_path,
                "indent": self.indent,
                "show_dirname": self.show_dirname,
                "_exists": self._exists,
                "__content": [item.to_dict() for item in self.content],
                "folder_closed": self.folder_closed}

    @classmethod
    def from_dict(cls, cls_dict: dict) -> "FolderListItem":
        content = cls_dict.pop("__content", list())
        instance = super(FolderListItem, cls).from_dict(cls_dict)
        instance._FolderListItem__content = [ScriptListItem.from_dict(item) for item in content]
        return instance

    # Used by "sort"
    def __lt__(self, other) -> bool:
        if isinstance(other, FolderListItem):
            return locale.strxfrm(self.basename) < locale.strxfrm(other.basename)
        if isinstance(other, ScriptListItem):
            return True
        return NotImplemented


def _create_list_item_from_dict(item_dict) -> ScriptListItem:
    type_ = item_dict.pop("__type__")
    return globals()[type_].from_dict(item_dict)


def _build_sorted_scripts_list(scripts_list: typing.List[ScriptListItem]) -> typing.List[ScriptListItem]:
        filtered_items = []
        for item in scripts_list:
            if item.indent == 0:
                filtered_items.append(item)
        filtered_items.sort()
        set_items = []
        for item in filtered_items:
            set_items.append(item)
            if isinstance(item, FolderListItem):
                if not item.folder_closed:
                    for content_item in item.content:
                        set_items.append(content_item)
        return set_items


class ScriptListCanvasItemDelegate(Widgets.ListCanvasItemDelegate):

    def __init__(self, ui, update_list_fn: typing.Callable[[], typing.Any]):
        super().__init__()
        self.__ui = ui
        self.__update_list_fn = update_list_fn

    def close(self):
        ...

    def mouse_pressed_in_item(self, mouse_index: int, pos: Geometry.IntPoint, modifiers) -> bool:
        display_item = self.items[mouse_index]
        if isinstance(display_item, FolderListItem) and display_item.indent < pos.x < display_item.indent + 20:
            display_item.folder_closed = not display_item.folder_closed
            self.__update_list_fn()
            return True
        return False

    def paint_item(self, drawing_context, display_item, rect, is_selected):
        folder_string = ''
        if isinstance(display_item, FolderListItem):
            if display_item.folder_closed:
                folder_string = f"\N{BLACK RIGHT-POINTING TRIANGLE} \N{FILE FOLDER} "
            else:
                folder_string = f"\N{BLACK DOWN-POINTING SMALL TRIANGLE} \N{OPEN FILE FOLDER} "

        if isinstance(display_item, ScriptListItem):
            with drawing_context.saver():

                drawing_context.fill_style = "#000"
                drawing_context.font = "12px"
                drawing_context.text_align = "left"
                drawing_context.text_baseline = "bottom"
                name_string = folder_string + display_item.basename
                drawing_context.fill_text(name_string, rect[0][1] + 4 + display_item.indent, rect[0][0] + 20 - 4)
                drawing_context.fill_style = "#888"
                drawing_context.font = "10px"
                name_width = self.__ui.get_font_metrics("12px", name_string).width
                if display_item.exists is not None and not display_item.exists:
                    type_str = "Folder" if type(display_item) is FolderListItem else "File"
                    drawing_context.fill_text(f"({type_str} not found)",
                                              rect[0][1] + 4 + display_item.indent + 4 + name_width,
                                              rect[0][0] + 20 - 4)
                elif display_item.show_dirname:
                    drawing_context.fill_text(f"({display_item.dirname})",
                                              rect[0][1] + 4 + display_item.indent + 4 + name_width,
                                              rect[0][0] + 20 - 4)


class RunScriptDialog(Dialog.ActionDialog):

    def __init__(self, document_controller):
        ui = document_controller.ui
        super().__init__(ui, _("Interactive Dialog"), document_controller.app, persistent_id="ScriptsDialog")

        self.ui = ui
        self.document_controller = document_controller

        self.script_filter_pattern = "\.py$"

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

        # Load the list of known scripts. Upgrade from old storage system ("interactive_scripts_0")
        items = []
        items_str = self.ui.get_persistent_string("interactive_scripts_1", "")
        if items_str:
            for item_dict in json.loads(items_str):
                items.append(_create_list_item_from_dict(item_dict))
        else:
            items_old = self.ui.get_persistent_object("interactive_scripts_0", list())
            for item in items_old:
                items.append(ScriptListItem(item))
        if items:
            items = _build_sorted_scripts_list(items)
            self.ui.set_persistent_string("interactive_scripts_1", json.dumps([item.to_dict() for item in items]))

        self.__new_path_entries = []

        for item in items:
            if isinstance(item, FolderListItem):
                full_path = item.full_path
                self.__new_path_entries.append(full_path)
                if not full_path in sys.path:
                    sys.path.append(full_path)

        def selected_changed(indexes: AbstractSet[int]) -> None:
            run_button_widget.enabled = len(indexes) == 1

        def add_clicked() -> None:
            add_dir = self.ui.get_persistent_string("import_directory", "")
            file_paths, filter_str, directory = self.get_file_paths_dialog(_("Add Scripts"), add_dir, "Python Files (*.py)", "Python Files (*.py)")
            self.ui.set_persistent_string("import_directory", directory)
            items = self.scripts_list_widget.items
            items.extend([ScriptListItem(file_path) for file_path in file_paths])
            self.update_scripts_list(items)

        def add_folder_clicked() -> None:
            add_dir = self.ui.get_persistent_string("import_directory", "")
            existing_directory, directory = self.ui.get_existing_directory_dialog(_("Add Scripts Folder"), add_dir)
            if existing_directory:
                new_folder = FolderListItem(existing_directory)
                new_folder.update_content_from_file_system(filter_pattern=self.script_filter_pattern)
                full_path = new_folder.full_path
                if not full_path in sys.path:
                    sys.path.append(full_path)
                    self.__new_path_entries.append(full_path)
                items = self.scripts_list_widget.items
                items.append(new_folder)
                self.update_scripts_list(items)
            else:
                self.rebuild_scripts_list()

        def remove_clicked() -> None:
            indexes = list(self.scripts_list_widget.selected_items)
            new_items = []
            for i, item in enumerate(self.scripts_list_widget.items):
                if not i in indexes:
                    new_items.append(item)
            self.update_scripts_list(new_items)

        def run_clicked() -> None:
            indexes = self.scripts_list_widget.selected_items
            if len(indexes) == 1:
                script_item = self.scripts_list_widget.items[list(indexes)[0]]
                script_item.check_existance()
                # Use "type" instead of "isinstance" to exclude subclasses from matching
                if type(script_item) is ScriptListItem and script_item.exists:
                    script_path = script_item.full_path
                    self.run_script(script_path)

        def item_selected(index: int) -> bool:
            run_clicked()
            return True

        self.scripts_list_widget = Widgets.ListWidget(ui, ScriptListCanvasItemDelegate(ui, self.rebuild_scripts_list), items=items, selection_style=Selection.Style.single_or_none, border_color="#888", properties={"min-height": 200, "min-width": 560, "size-policy-vertical": "expanding"})
        self.scripts_list_widget.on_selection_changed = selected_changed
        self.scripts_list_widget.on_item_selected = item_selected
        self.rebuild_scripts_list()

        add_button_widget = ui.create_push_button_widget(_("Add..."))
        add_button_widget.on_clicked = add_clicked

        add_folder_button_widget = ui.create_push_button_widget(_("Add Folder..."))
        add_folder_button_widget.on_clicked = add_folder_clicked

        remove_button_widget = ui.create_push_button_widget(_("Remove"))
        remove_button_widget.on_clicked = remove_clicked

        run_button_widget = ui.create_push_button_widget(_("Run"))
        run_button_widget.on_clicked = run_clicked
        run_button_widget.enabled = False

        list_widget_row = ui.create_row_widget()
        list_widget_row.add_spacing(8)
        list_widget_row.add(self.scripts_list_widget)
        list_widget_row.add_spacing(8)

        close_button_widget = ui.create_push_button_widget(_("Close"))
        close_button_widget.on_clicked = self.request_close

        button_row = ui.create_row_widget()
        button_row.add_spacing(12)
        button_row.add(add_button_widget)
        button_row.add_spacing(4)
        button_row.add(add_folder_button_widget)
        button_row.add_spacing(4)
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

        self.__sync_events = set()

        self.__lock = threading.RLock()

        self.__q = collections.deque()
        self.__output_queue = collections.deque()

        self.__is_closed = False

    def close(self):
        self.__is_closed = True
        for sync_event in self.__sync_events:
            sync_event.set()
        if self.__thread:
            self.__thread.join()
        self.document_controller.clear_task("ui_" + str(id(self)))
        self.document_controller.clear_task("run_" + str(id(self)))
        self.document_controller.clear_task("show_" + str(id(self)))
        self.document_controller.clear_task("print_" + str(id(self)))
        super().close()

    @property
    def cancelled(self):
        return self.__cancelled

    def update_scripts_list(self, new_scripts_list):
        for item in new_scripts_list:
            if isinstance(item, FolderListItem):
                item.update_content_from_file_system(filter_pattern=self.script_filter_pattern)
        items = _build_sorted_scripts_list(new_scripts_list)
        for item in items:
            item.check_existance()
        self.scripts_list_widget.items = items
        self.ui.set_persistent_string("interactive_scripts_1", json.dumps([item.to_dict() for item in self.scripts_list_widget.items]))

    def rebuild_scripts_list(self):
        self.update_scripts_list(self.scripts_list_widget.items)

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
        # Reload modules that are in on of the script folders.
        current_modules = list(sys.modules.values())
        for module in current_modules:
            for path in self.__new_path_entries:
                try:
                    do_reload = os.path.abspath(module.__file__)[:len(path)] == path
                except (AttributeError, ValueError, TypeError):
                    pass
                else:
                    try:
                        if do_reload:
                            reload(module)
                    except:
                        self.print(traceback.format_exc())
                        self.__stack.current_index = 1
                        self.continue_after_parse_error(script_path)
                        return

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
                self.__cancelled = False # Reset cancelled flag to make "Run again" work after a script was cancelled
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
                self.document_controller.add_task("run_" + str(id(self)), self.__handle_output_and_q)

        self.__thread = threading.Thread(target=func_continue)
        self.__thread.start()

    def run(self, script_path, func):
        def func_run(func):
            try:
                func(self)
            except Exception:
                pass

            if not self.__is_closed:
                result = self.confirm(_("Finished"), _("Run Again"), _("Close"))

                with self.__lock:
                    if result:
                        self.__q.append(functools.partial(self.run_script, script_path))
                    else:
                        self.__q.append(self.request_close)
                    self.document_controller.add_task("run_" + str(id(self)), self.__handle_output_and_q)

        self.__thread = threading.Thread(target=func_run, args=(func,))
        self.__thread.start()

    def __handle_output_and_q(self):
        func = None
        with self.__lock:
            while len(self.__output_queue) > 0:
                self.__output_widget.move_cursor_position("end")
                self.__output_widget.append_text(self.__output_queue.popleft())
            if len(self.__q) > 0:
                func = self.__q.popleft()
        if callable(func):
            func()

    def print(self, text):
        with self.__lock:
            self.__output_queue.append(str(text))
            self.document_controller.add_task("print_" + str(id(self)), self.__handle_output_and_q)

    def print_debug(self, text):
        self.print(text)

    def print_info(self, text):
        self.print(text)

    def print_warn(self, text):
        self.print(text)

    def get_string(self, prompt, default_str=None) -> typing.Optional[str]:
        """Return a string value that the user enters. Raises exception for cancel."""
        with self.sync_event() as accept_event:
            result = None

            def perform():
                def accepted(text):
                    nonlocal result
                    result = text
                    accept_event.set()

                def rejected():
                    accept_event.set()

                self.__message_column.remove_all()
                pose_get_string_message_box(self.ui, self.__message_column, prompt, str(default_str), accepted, rejected)

            with self.__lock:
                self.__q.append(perform)
                self.document_controller.add_task("ui_" + str(id(self)), self.__handle_output_and_q)
            accept_event.wait()
            if self.__is_closed:
                raise Exception("Cancel")

        def update_message_column():
            self.__message_column.remove_all()
            self.__message_column.add(self.__make_cancel_row())
        self.document_controller.add_task("ui_" + str(id(self)), update_message_column)
        if result is None:
            raise Exception("Cancel")
        return result

    def get_integer(self, prompt: str, default_value: int=0) -> int:
        converter = Converter.IntegerToStringConverter()
        result = self.get_string(prompt, converter.convert(default_value))
        return converter.convert_back(result)

    def get_float(self, prompt: str, default_value: float=0, format_str: str=None) -> float:
        converter = Converter.FloatToStringConverter(format_str)
        result = self.get_string(prompt, converter.convert(default_value))
        return converter.convert_back(result)

    def show_ndarray(self, data: numpy.ndarray, title:str = None) -> None:
        with self.sync_event() as accept_event:

            def perform():
                result_display_panel = self.document_controller.next_result_display_panel()
                if result_display_panel:
                    data_item = self.document_controller.add_data(data, title)
                    display_item = self.document_controller.document_model.get_display_item_for_data_item(data_item)
                    result_display_panel.set_display_panel_display_item(display_item)
                    result_display_panel.request_focus()
                accept_event.set()

            with self.__lock:
                self.__q.append(perform)
                self.document_controller.add_task("show_" + str(id(self)), self.__handle_output_and_q)
            accept_event.wait()
            if self.__is_closed:
                raise Exception("Cancel")

    def __register_sync_event(self, sync_event: threading.Event) -> None:
        self.__sync_events.add(sync_event)

    def __unregister_sync_event(self, sync_event: threading.Event) -> None:
        self.__sync_events.remove(sync_event)

    @contextlib.contextmanager
    def sync_event(self):
        sync_event = threading.Event()
        self.__register_sync_event(sync_event)
        yield sync_event
        self.__unregister_sync_event(sync_event)

    def __accept_reject(self, prompt, accepted_text, rejected_text, display_rejected):
        """Return a boolean value for accept/reject."""
        with self.sync_event() as accept_event:
            result = False

            def perform():
                def accepted():
                    nonlocal result
                    result = True
                    accept_event.set()

                def rejected():
                    nonlocal result
                    result = False
                    accept_event.set()

                self.__message_column.remove_all()
                pose_confirmation_message_box(self.ui, self.__message_column, prompt, accepted, rejected, accepted_text, rejected_text, display_rejected)
                #self.__message_column.add(self.__make_cancel_row())

            with self.__lock:
                self.__q.append(perform)
                self.document_controller.add_task("ui_" + str(id(self)), self.__handle_output_and_q)
            accept_event.wait()
            if self.__is_closed:
                raise Exception("Cancel")

        def update_message_column():
            self.__message_column.remove_all()
            self.__message_column.add(self.__make_cancel_row())
        self.document_controller.add_task("ui_" + str(id(self)), update_message_column)
        return result

    def confirm_ok_cancel(self, prompt: str) -> bool:
        return self.__accept_reject(prompt, _("OK"), _("Cancel"), True)

    def confirm_yes_no(self, prompt: str) -> bool:
        return self.__accept_reject(prompt, _("Yes"), _("No"), True)

    def confirm(self, prompt: str, accepted_text: str, rejected_text: str) -> bool:
        return self.__accept_reject(prompt, accepted_text, rejected_text, True)

    def alert(self, prompt: str, button_label: str = None) -> None:
        self.__accept_reject(prompt, button_label, None, False)
