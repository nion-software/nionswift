from __future__ import annotations

# system imports
import ast
import collections
import contextlib
import copy
import functools
import gettext
import importlib
import locale
import os
import pathlib
import re
import subprocess
import threading
import traceback
import typing
import sys
import urllib.parse
import webbrowser

# third part imports
import numpy.typing

# local libraries
from nion.swift.model import PlugInManager
from nion.swift.model import Profile
from nion.swift.model import Utility
from nion.swift import FacadeQueued
from nion.swift import Panel
from nion.ui import Declarative
from nion.ui import Dialog
from nion.ui import Widgets
from nion.utils import Converter
from nion.utils import Selection
from nion.utils import Geometry

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.ui import DrawingContext
    from nion.ui import UserInterface

_NDArray = numpy.typing.NDArray[typing.Any]

_ = gettext.gettext

NO_DESCRIPTION_AVAILABLE_TEXT = _("*No description available*.")


def pose_get_string_message_box(ui: UserInterface.UserInterface, message_column: UserInterface.BoxWidget, caption: str,
                                text: str, accepted_fn: typing.Callable[[str], None],
                                rejected_fn: typing.Optional[typing.Callable[[], None]] = None,
                                accepted_text: typing.Optional[str] = None,
                                rejected_text: typing.Optional[str] = None) -> UserInterface.BoxWidget:
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

    def reject_button_clicked() -> typing.Any:
        if callable(rejected_fn):
            rejected_fn()
        return False

    def accept_button_clicked() -> typing.Any:
        accepted_fn(string_edit_widget.text or str())
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


def pose_confirmation_message_box(ui: UserInterface.UserInterface, message_column: UserInterface.BoxWidget,
                                  caption: str, accepted_fn: typing.Callable[[], None],
                                  rejected_fn: typing.Optional[typing.Callable[[], None]] = None,
                                  accepted_text: typing.Optional[str] = None,
                                  rejected_text: typing.Optional[str] = None,
                                  display_rejected: bool = True) -> UserInterface.BoxWidget:
    if accepted_text is None:
        accepted_text = _("OK")
    if rejected_text is None:
        rejected_text = _("Cancel")
    message_box_widget = ui.create_column_widget()  # properties={"stylesheet": "background: #FFD"}

    def reject_button_clicked() -> typing.Any:
        if rejected_fn:
            rejected_fn()
        return False

    def accept_button_clicked() -> typing.Any:
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
    def __init__(self, full_path: str, indent: int = 0, indent_level: int = 0, show_dirname: bool = True) -> None:
        self.__full_path = os.path.abspath(full_path)
        self._exists = False
        self.indent = indent
        self.indent_level = indent_level
        self.show_dirname = show_dirname
        self.script_item: typing.Optional[Profile.ScriptItem] = None

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

    def check_existence(self) -> bool:
        self._exists = os.path.exists(self.full_path)
        return self._exists

    # Used by "sort"
    def __lt__(self, other: typing.Any) -> bool:
        if isinstance(other, FolderListItem):
            return False
        if isinstance(other, ScriptListItem):
            return locale.strxfrm(self.basename.casefold()) < locale.strxfrm(other.basename.casefold())
        return NotImplemented


class FolderListItem(ScriptListItem):

    def __init__(self, full_path: str, content: typing.Optional[typing.List[ScriptListItem]] = None, indent: int = 0,
                 indent_level: int = 0, show_dirname: bool = True):
        super().__init__(full_path, indent=indent, indent_level=indent_level, show_dirname=show_dirname)
        self.__content = content if content is not None else list()
        self.folder_closed = True

    @property
    def content(self) -> typing.List[ScriptListItem]:
        return self.__content

    def update_content_from_file_system(self, filter_pattern: typing.Optional[str] = None) -> None:
        if os.path.isdir(self.full_path):
            dirlist = os.listdir(self.full_path)
            filtered_items = list()
            for item in dirlist:
                if filter_pattern is None or re.search(filter_pattern, item):
                    indent_level = self.indent_level + 1
                    filtered_items.append(ScriptListItem(os.path.join(self.full_path, item), indent=indent_level * 20,
                                                         indent_level=indent_level, show_dirname=False))
            self.__content = filtered_items

    # Used by "sort"
    def __lt__(self, other: typing.Any) -> bool:
        if isinstance(other, FolderListItem):
            return locale.strxfrm(self.basename.casefold()) < locale.strxfrm(other.basename.casefold())
        if isinstance(other, ScriptListItem):
            return True
        return NotImplemented


def _build_sorted_scripts_list(scripts_list: typing.Sequence[typing.Any]) -> typing.Sequence[ScriptListItem]:
    filtered_items = []
    for item in scripts_list:
        if item.indent_level == 0:
            filtered_items.append(item)
    filtered_items.sort()
    set_items = []
    for item in filtered_items:
        set_items.append(item)
        if isinstance(item, FolderListItem):
            if not item.folder_closed:
                for content_item in sorted(item.content):
                    set_items.append(content_item)
    return set_items


def open_location(location: str) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(location)])
    elif sys.platform == 'win32':
        subprocess.run(['explorer', str(location)])
    elif sys.platform == 'linux':
        subprocess.check_call(['xdg-open', '--', str(location)])


class ScriptListCanvasItemDelegate(Widgets.ListCanvasItemDelegate):

    def __init__(self, ui: UserInterface.UserInterface, document_controller: DocumentController.DocumentController,
                 update_list_fn: typing.Callable[[], typing.Any]) -> None:
        super().__init__()
        self.__ui = ui
        self.__document_controller = document_controller
        self.__update_list_fn = update_list_fn

    @staticmethod
    def _closed_folder_icon_strings() -> typing.Tuple[str, str]:
        if sys.platform == "win32":
            triangle = "\N{BLACK MEDIUM RIGHT-POINTING TRIANGLE CENTRED} "
        else:
            triangle = "\N{BLACK RIGHT-POINTING TRIANGLE} "
        return triangle, "\N{FILE FOLDER} "

    @staticmethod
    def _open_folder_icon_strings() -> typing.Tuple[str, str]:
        if sys.platform == "win32":
            triangle = "\N{BLACK MEDIUM DOWN-POINTING TRIANGLE CENTRED} "
        else:
            triangle = "\N{BLACK DOWN-POINTING TRIANGLE} "
        return triangle, "\N{OPEN FILE FOLDER} "

    @staticmethod
    def _file_icon_string() -> str:
        return "\N{PAGE FACING UP} "

    @staticmethod
    def _major_font_size() -> str:
        return "12px"

    @staticmethod
    def _minor_font_size() -> str:
        return "10px"

    @staticmethod
    def _major_font_color() -> str:
        return "#000"

    @staticmethod
    def _minor_font_color() -> str:
        return "#888"

    def mouse_pressed_in_item(self, mouse_index: int, pos: Geometry.IntPoint, modifiers: UserInterface.KeyboardModifiers) -> bool:
        display_item = self.items[mouse_index]
        width = self.__ui.get_font_metrics(self._major_font_size(), self._closed_folder_icon_strings()[0]).width
        if isinstance(display_item, FolderListItem) and display_item.indent - 4 < pos.x < display_item.indent + width + 2:
            display_item.folder_closed = not display_item.folder_closed
            if display_item.script_item:
                display_item.script_item.is_closed = not display_item.script_item.is_closed
            self.__update_list_fn()
            return True
        return False

    def context_menu_event(self, index: typing.Optional[int], x: int, y: int, gx: int, gy: int) -> bool:
        if index is not None:
            display_item = self.items[index]
            menu = self.__document_controller.create_context_menu()
            if isinstance(display_item, FolderListItem):
                menu.add_menu_item(_("Open Folder"), functools.partial(open_location, display_item.full_path))
            elif isinstance(display_item, ScriptListItem):
                menu = self.__document_controller.create_context_menu()
                menu.add_menu_item(_("Open Containing Folder"), functools.partial(open_location, display_item.dirname))
            menu.popup(gx, gy)
            return True
        return False

    def __calculate_indent(self, display_item: typing.Any) -> int:
        # An item that can cause an indent_level > 0 is always an open folder
        triangle_string, icon_string = self._open_folder_icon_strings()
        return round(4 + float(self.__ui.get_font_metrics(self._major_font_size(), triangle_string + icon_string).width * display_item.indent_level))

    def paint_item(self, drawing_context: DrawingContext.DrawingContext, display_item: typing.Any, rect: Geometry.IntRect, is_selected: bool) -> None:
        if isinstance(display_item, FolderListItem):
            if display_item.folder_closed:
                triangle_string, icon_string = self._closed_folder_icon_strings()
            else:
                triangle_string, icon_string = self._open_folder_icon_strings()
        else:
            triangle_string = str()
            icon_string = self._file_icon_string()

        icon_offset = self.__ui.get_font_metrics(self._major_font_size(), self._closed_folder_icon_strings()[0]).width
        icon_width = self.__ui.get_font_metrics(self._major_font_size(), icon_string).width

        if isinstance(display_item, ScriptListItem):
            with drawing_context.saver():

                drawing_context.fill_style = self._major_font_color()
                drawing_context.font = self._major_font_size()
                drawing_context.text_align = "left"
                drawing_context.text_baseline = "bottom"
                name_string = display_item.basename
                display_item.indent = self.__calculate_indent(display_item)
                drawing_context.fill_text(triangle_string, rect[0][1] + display_item.indent, rect[0][0] + 20 - 4)
                drawing_context.fill_text(icon_string + name_string, rect[0][1] + display_item.indent + icon_offset, rect[0][0] + 20 - 4)
                drawing_context.fill_style = self._minor_font_color()
                drawing_context.font = self._minor_font_color()
                name_width = self.__ui.get_font_metrics(self._major_font_size(), name_string).width
                if display_item.exists is not None and not display_item.exists:
                    type_str = "Folder" if type(display_item) is FolderListItem else "File"
                    drawing_context.fill_text(f"({type_str} not found: {display_item.full_path})",
                                              rect[0][1] + 4 + display_item.indent + 4 + icon_offset + icon_width + name_width,
                                              rect[0][0] + 20 - 4)
                elif display_item.show_dirname:
                    drawing_context.fill_text(f"({display_item.dirname})",
                                              rect[0][1] + 4 + display_item.indent + 4 + icon_offset + icon_width + name_width,
                                              rect[0][0] + 20 - 4)


class ScriptCancelException(Exception):
    pass


class RunScriptDialog(Dialog.ActionDialog):

    def __init__(self, document_controller: "DocumentController.DocumentController"):
        ui = document_controller.ui
        super().__init__(ui, _("Scripts"), parent_window=document_controller, persistent_id="ScriptsDialog")

        self.ui = ui
        self.document_controller = document_controller

        app = typing.cast(typing.Any, self.document_controller.app)  # trick typing
        self.__profile: typing.Optional[Profile.Profile] = app.profile if app else None

        self.script_filter_pattern = "(?<!__init__)\\.py$"

        self.__cancelled = False

        self.__thread: typing.Optional[threading.Thread] = None

        properties = dict()
        properties["min-height"] = 180
        properties["min-width"] = 540

        self.__output_widget = self.ui.create_text_edit_widget(properties)
        self.__output_widget.set_text_font(Panel.Panel.get_monospace_text_font())
        self.__output_widget.set_line_height_proportional(Panel.Panel.get_monospace_proportional_line_height())

        self.__message_column = ui.create_column_widget()

        self.__message_column.add(self.__make_cancel_row())

        # load the list of script items
        items = []
        if self.__profile:
            for script_item in self.__profile.script_items:
                if isinstance(script_item, Profile.FileScriptItem):
                    script_list_item = ScriptListItem(str(script_item.path))
                    script_list_item.script_item = script_item
                    items.append(script_list_item)
                elif isinstance(script_item, Profile.FolderScriptItem):
                    folder_list_item = FolderListItem(str(script_item.folder_path))
                    folder_list_item.script_item = script_item
                    folder_list_item.folder_closed = script_item.is_closed
                    items.append(folder_list_item)

        self.__new_path_entries = []

        for item in items:
            if isinstance(item, FolderListItem):
                full_path = item.full_path
                self.__new_path_entries.append(full_path)
                if full_path not in sys.path:
                    sys.path.append(full_path)

        def update_script_description() -> None:
            indexes = self.scripts_list_widget.selected_items
            if len(indexes) == 1:
                script_item = self.scripts_list_widget.items[list(indexes)[0]]
                # Use "type" instead of "isinstance" to exclude subclasses from matching
                if type(script_item) is ScriptListItem:
                    script_path = pathlib.Path(script_item.full_path)
                    script_ast = None
                    if script_path.exists():
                        try:
                            with open(script_path) as f:
                                script = f.read()

                            script_ast = ast.parse(script, script_path.stem, 'exec')
                        except Exception as e:
                            pass
                        docstring = ast.get_docstring(script_ast) if script_ast else None
                        if docstring:
                            text_browser_widget.markdown = docstring
                        else:
                            text_browser_widget.markdown = NO_DESCRIPTION_AVAILABLE_TEXT

        def selected_changed(indexes: typing.AbstractSet[int]) -> None:
            run_button_widget.enabled = len(indexes) == 1
            update_script_description()

        def add_clicked() -> None:
            assert self.__profile
            add_dir = self.ui.get_persistent_string("import_directory", "")
            file_paths, filter_str, directory = self.get_file_paths_dialog(_("Add Scripts"), add_dir, "Python Files (*.py)", "Python Files (*.py)")
            if len(file_paths) > 0:
                self.ui.set_persistent_string("import_directory", directory)
                items = list(self.scripts_list_widget.items)
                for file_path_str in file_paths:
                    script_item = Profile.FileScriptItem(pathlib.Path(file_path_str))
                    self.__profile.append_script_item(script_item)
                    script_list_item = ScriptListItem(file_path_str)
                    script_list_item.script_item = script_item
                    items.append(script_list_item)
                self.update_scripts_list(items)

        def add_folder_clicked() -> None:
            assert self.__profile
            add_dir = self.ui.get_persistent_string("import_directory", "")
            existing_directory, directory = self.ui.get_existing_directory_dialog(_("Add Scripts Folder"), add_dir)
            if existing_directory:
                folder_list_item = FolderListItem(existing_directory)
                folder_list_item.update_content_from_file_system(filter_pattern=self.script_filter_pattern)
                full_path = folder_list_item.full_path
                if full_path not in sys.path:
                    sys.path.append(full_path)
                    self.__new_path_entries.append(full_path)
                items = list(self.scripts_list_widget.items)
                script_item = Profile.FolderScriptItem(pathlib.Path(existing_directory))
                self.__profile.append_script_item(script_item)
                folder_list_item.script_item = script_item
                items.append(folder_list_item)
                self.update_scripts_list(items)
            else:
                self.rebuild_scripts_list()

        def remove_clicked() -> None:
            assert self.__profile
            indexes = list(self.scripts_list_widget.selected_items)
            new_items = []
            for i, item in enumerate(self.scripts_list_widget.items):
                if i not in indexes:
                    new_items.append(item)
                elif item.script_item:
                    self.__profile.remove_script_item(item.script_item)
            self.update_scripts_list(new_items)

        def run_clicked() -> None:
            indexes = self.scripts_list_widget.selected_items
            if len(indexes) == 1:
                script_item = self.scripts_list_widget.items[list(indexes)[0]]
                script_item.check_existence()
                # Use "type" instead of "isinstance" to exclude subclasses from matching
                if type(script_item) is ScriptListItem and script_item.exists:
                    script_path = script_item.full_path
                    self.run_script(script_path)

        def item_selected(index: int) -> bool:
            run_clicked()
            return True

        def handle_anchor_clicked(anchor: str) -> bool:
            o = urllib.parse.urlparse(anchor)
            if o.scheme in ("http", "https"):
                webbrowser.open(anchor)
                return True
            return False

        self.scripts_list_widget = Widgets.ListWidget(ui, ScriptListCanvasItemDelegate(ui, document_controller,
                                                                                       self.rebuild_scripts_list),
                                                      items=items, selection_style=Selection.Style.single_or_none,
                                                      border_color="#888",
                                                      properties={"min-height": 200, "min-width": 560,
                                                                  "size-policy-vertical": "expanding"})
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

        text_browser_widget = ui.create_text_browser_widget()
        text_browser_widget.markdown = NO_DESCRIPTION_AVAILABLE_TEXT
        text_browser_widget.on_anchor_clicked = handle_anchor_clicked

        description_row = ui.create_row_widget(properties={"height": 110})
        description_row.add_spacing(8)
        description_row.add(text_browser_widget)
        description_row.add_spacing(8)

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
        select_column.add(description_row)
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

        self.__sync_events: typing.Set[threading.Event] = set()

        self.__lock = threading.RLock()

        self.__q: typing.Deque[typing.Callable[[], None]] = collections.deque()
        self.__output_queue: typing.Deque[str] = collections.deque()

        self.__is_closed = False

    def close(self) -> None:
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
    def cancelled(self) -> bool:
        return self.__cancelled

    def update_scripts_list(self, new_scripts_list: typing.Sequence[typing.Any]) -> None:
        for item in new_scripts_list:
            if isinstance(item, FolderListItem):
                item.update_content_from_file_system(filter_pattern=self.script_filter_pattern)
        items = _build_sorted_scripts_list(new_scripts_list)
        for item in items:
            item.check_existence()
        self.scripts_list_widget.items = items

    def rebuild_scripts_list(self) -> None:
        self.update_scripts_list(self.scripts_list_widget.items)

    def __make_cancel_row(self) -> UserInterface.BoxWidget:
        def cancel_script() -> None:
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
                    do_reload = os.path.abspath(module.__file__ or str())[:len(path)] == path
                except (AttributeError, ValueError, TypeError):
                    pass
                else:
                    try:
                        if do_reload:
                            importlib.reload(module)
                    except Exception:
                        self.print(traceback.format_exc())
                        self.__stack.current_index = 1
                        self.continue_after_parse_error(script_path)
                        return

        self.__output_widget.text = str()

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
            def __init__(self, func_id: str, arg_id: str) -> None:
                self.__func_id = func_id
                self.__arg_id = arg_id

            def visit_Module(self, node: typing.Any) -> typing.Any:
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

        def run_it(compiled: typing.Any, interactive_session: typing.Any) -> None:
            class APIBroker:
                def get_interactive(self, version: typing.Optional[str] = None) -> typing.Any:
                    actual_version = "1.0.0"
                    if Utility.compare_versions(version or str(), actual_version) > 0:
                        raise NotImplementedError("API requested version %s is greater than %s." % (version, actual_version))
                    return interactive_session

                def get_api(self, version: str, ui_version: typing.Optional[str] = None) -> typing.Any:
                    ui_version = ui_version if ui_version else "~1.0"
                    api = PlugInManager.api_broker_fn(version, ui_version)
                    queued_api = FacadeQueued.API(api, None)  # type: ignore
                    queued_api._queue_task = api.queue_task
                    return queued_api

                def get_ui(self, version: str) -> Declarative.DeclarativeUI:
                    actual_version = "1.0.0"
                    if Utility.compare_versions(version, actual_version) > 0:
                        raise NotImplementedError("API requested version %s is greater than %s." % (version, actual_version))
                    return Declarative.DeclarativeUI()
            try:
                g: typing.Dict[str, typing.Any] = dict()
                g["api_broker"] = APIBroker()
                g["print"] = self.print
                g["input"] = self.get_string

                print_fn = self.print
                self.__cancelled = False  # Reset cancelled flag to make "Run again" work after a script was cancelled

                class StdoutCatcher:
                    def __init__(self) -> None:
                        pass

                    def write(self, stuff: str) -> None:
                        print_fn(stuff.rstrip())

                    def flush(self) -> None:
                        pass

                stdout = StdoutCatcher()
                with contextlib.redirect_stdout(typing.cast(typing.Any, stdout)), contextlib.redirect_stderr(typing.cast(typing.Any, stdout)):
                    try:
                        exec(compiled, g)
                    except ScriptCancelException as e:
                        self.print(_("Script canceled by user."))
            except Exception:
                self.print("{}: {}".format(_("Error"), traceback.format_exc()))

        self.__stack.current_index = 1

        self.run(script_path, functools.partial(run_it, compiled))

    def continue_after_parse_error(self, script_path: str) -> None:
        def func_continue() -> None:
            result = self.confirm(_("Finished"), _("Run Again"), _("Close"))

            with self.__lock:
                if result:
                    self.__q.append(functools.partial(self.run_script, script_path))
                else:
                    self.__q.append(self.request_close)
                self.document_controller.add_task("run_" + str(id(self)), self.__handle_output_and_q)

        self.__thread = threading.Thread(target=func_continue)
        self.__thread.start()

    def run(self, script_path: str, func: typing.Callable[[RunScriptDialog], None]) -> None:
        def func_run(func: typing.Callable[[RunScriptDialog], None]) -> None:
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

    def __handle_output_and_q(self) -> None:
        func = None
        with self.__lock:
            while len(self.__output_queue) > 0:
                self.__output_widget.move_cursor_position("end")
                self.__output_widget.append_text(self.__output_queue.popleft())
            if len(self.__q) > 0:
                func = self.__q.popleft()
        if callable(func):
            func()

    def print(self, text: typing.Any) -> None:
        with self.__lock:
            self.__output_queue.append(str(text))
            self.document_controller.add_task("print_" + str(id(self)), self.__handle_output_and_q)

    def print_debug(self, text: typing.Any) -> None:
        self.print(text)

    def print_info(self, text: typing.Any) -> None:
        self.print(text)

    def print_warn(self, text: typing.Any) -> None:
        self.print(text)

    def get_string(self, prompt: str, default_str: typing.Optional[str] = None) -> typing.Optional[str]:
        """Return a string value that the user enters. Raises exception for cancel."""
        with self.sync_event() as accept_event:
            result = None

            def perform() -> None:
                def accepted(text: str) -> None:
                    nonlocal result
                    result = text
                    accept_event.set()

                def rejected() -> None:
                    accept_event.set()

                self.__message_column.remove_all()
                pose_get_string_message_box(self.ui, self.__message_column, prompt, str(default_str), accepted, rejected)

            with self.__lock:
                self.__q.append(perform)
                self.document_controller.add_task("ui_" + str(id(self)), self.__handle_output_and_q)
            accept_event.wait()
            if self.__is_closed:
                raise ScriptCancelException()

        def update_message_column() -> None:
            self.__message_column.remove_all()
            self.__message_column.add(self.__make_cancel_row())
        self.document_controller.add_task("ui_" + str(id(self)), update_message_column)
        if result is None:
            raise ScriptCancelException()
        return result

    def get_integer(self, prompt: str, default_value: int = 0) -> int:
        converter = Converter.IntegerToStringConverter()
        result = self.get_string(prompt, converter.convert(default_value))
        return converter.convert_back(result) or 0

    def get_float(self, prompt: str, default_value: float = 0, format_str: typing.Optional[str] = None) -> float:
        converter = Converter.FloatToStringConverter(format_str)
        result = self.get_string(prompt, converter.convert(default_value))
        return converter.convert_back(result) or 0.0

    def show_ndarray(self, data: _NDArray, title: typing.Optional[str] = None) -> None:
        with self.sync_event() as accept_event:

            def perform() -> None:
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
                raise ScriptCancelException()

    def __register_sync_event(self, sync_event: threading.Event) -> None:
        self.__sync_events.add(sync_event)

    def __unregister_sync_event(self, sync_event: threading.Event) -> None:
        self.__sync_events.remove(sync_event)

    @contextlib.contextmanager
    def sync_event(self) -> typing.Iterator[threading.Event]:
        sync_event = threading.Event()
        self.__register_sync_event(sync_event)
        yield sync_event
        self.__unregister_sync_event(sync_event)

    def __accept_reject(self, prompt: str, accepted_text: typing.Optional[str], rejected_text: typing.Optional[str], display_rejected: bool) -> bool:
        """Return a boolean value for accept/reject."""
        with self.sync_event() as accept_event:
            result = False

            def perform() -> None:
                def accepted() -> None:
                    nonlocal result
                    result = True
                    accept_event.set()

                def rejected() -> None:
                    nonlocal result
                    result = False
                    accept_event.set()

                self.__message_column.remove_all()
                pose_confirmation_message_box(self.ui, self.__message_column, prompt, accepted, rejected, accepted_text, rejected_text, display_rejected)
                # self.__message_column.add(self.__make_cancel_row())

            with self.__lock:
                self.__q.append(perform)
                self.document_controller.add_task("ui_" + str(id(self)), self.__handle_output_and_q)
            accept_event.wait()
            if self.__is_closed:
                raise ScriptCancelException()

        def update_message_column() -> None:
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

    def alert(self, prompt: str, button_label: typing.Optional[str] = None) -> None:
        self.__accept_reject(prompt, button_label, None, False)
