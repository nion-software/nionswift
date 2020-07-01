# standard libraries
import functools
import gettext
import pathlib
import pkgutil
import subprocess
import sys
import typing

# local libraries
from nion.swift import MimeTypes
from nion.swift import Panel
from nion.swift.model import DataGroup
from nion.swift.model import DocumentModel
from nion.swift.model import Profile
from nion.swift.model import Observer
from nion.ui import CanvasItem
from nion.ui import Dialog
from nion.ui import UserInterface
from nion.ui import Widgets
from nion.utils import Binding
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel
from nion.utils import Selection

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController

_ = gettext.gettext


def reveal_project(project_path: pathlib.Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(project_path)])
    elif sys.platform == 'win32':
        subprocess.run(['explorer', str(project_path.parent)])
    elif sys.platform == 'linux':
        subprocess.check_call(['xdg-open', '--', str(project_path.parent)])


def open_location(location: pathlib.Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(location)])
    elif sys.platform == 'win32':
        subprocess.run(['explorer', str(location)])
    elif sys.platform == 'linux':
        subprocess.check_call(['xdg-open', '--', str(location)])


class DocumentModelCounterDisplayItem:

    def __init__(self, document_model: DocumentModel.DocumentModel):
        self.__document_model = document_model

        self.__count = 0
        self.on_title_changed = None

        def count_changed(count: Observer.ItemValue) -> None:
            self.__count = count
            if callable(self.on_title_changed):
                self.on_title_changed(self.title)

        oo = Observer.ObserverBuilder()
        oo.source(self.__document_model).sequence_from_array("display_items").len().action_fn(count_changed)
        self.__count_observer = oo.make_observable()

    def close(self) -> None:
        self.__count_observer.close()
        self.__count_observer = None
        self.__document_model = None
        self.on_title_changed = None

    @property
    def title(self) -> str:
        title = _("All")
        return f"{title} ({self.__count})"


class ProjectCounterDisplayItem:

    def __init__(self, project_reference: Profile.ProjectReference):
        self.__project_reference = project_reference

        self.__count = 0
        self.on_title_changed = None

        def count_changed(count: Observer.ItemValue) -> None:
            self.__count = count
            if callable(self.on_title_changed):
                self.on_title_changed(self.title)

        oo = Observer.ObserverBuilder()
        oo.source(self.__project_reference).prop("project").sequence_from_array("display_items").len().action_fn(count_changed)
        self.__count_observer = oo.make_observable()

    def close(self) -> None:
        self.__count_observer.close()
        self.__count_observer = None
        self.__project_reference = None
        self.on_title_changed = None

    @property
    def project_reference(self) -> Profile.ProjectReference:
        return self.__project_reference

    @property
    def title(self) -> str:
        return f"{self.__project_reference.title} ({self.__count})"


class CollectionDisplayItemCounter:

    def __init__(self, base_title: str, data_group: typing.Optional[DataGroup.DataGroup], filter_id: typing.Optional[str], document_controller: "DocumentController.DocumentController"):
        self.__base_title = base_title
        self.__data_group = data_group
        self.__filter_id = filter_id
        self.__filter_predicate = document_controller.get_filter_predicate(filter_id) if self.__filter_id else ListModel.Filter(True)
        self.on_title_changed = None
        self.__count = 0

        # useful for drag and drop
        self.document_controller = document_controller
        self.document_model = document_controller.document_model

        container = self.__data_group or document_controller.document_model

        def count_changed(count: Observer.ItemValue) -> None:
            self.__count = count
            if callable(self.on_title_changed):
                self.on_title_changed(self.title)

        oo = Observer.ObserverBuilder()
        oo.source(container).sequence_from_array("display_items", predicate=self.__filter_predicate.matches).len().action_fn(count_changed)
        self.__count_observer = oo.make_observable()

    def close(self) -> None:
        self.on_title_changed = None
        self.__count_observer.close()
        self.__count_observer = None
        self.__data_group = None
        self.document_controller = None
        self.document_model = None

    @property
    def title(self) -> str:
        return f"{self.__base_title} ({self.__count})"

    @property
    def is_smart_collection(self) -> bool:
        return not isinstance(self.__data_group, DataGroup.DataGroup)

    @property
    def filter_id(self) -> typing.Optional[str]:
        return self.__filter_id

    @property
    def data_group(self) -> typing.Optional[DataGroup.DataGroup]:
        return self.__data_group


class ProjectPanelProjectItem:

    def __init__(self, indent: int, project_reference: Profile.ProjectReference, display_item_controller: ProjectCounterDisplayItem):
        self.is_folder = False
        self.indent = indent
        self.project_reference = project_reference
        self.display_item_controller = display_item_controller
        self.is_target = False
        self.is_work = False
        self.check_state = "unchecked"

    @property
    def __state_str(self) -> str:
        project = self.project_reference.project
        if not project:
            return f"(unloaded)"
        elif project.project_state == "loaded":
            return f"(loaded [v{project.project_version}]) ({len(project.data_items)}/{len(project.display_items)})"
        elif project.project_state == "needs_upgrade":
            return f"(needs upgrade [v{project.project_version}]) ({len(project.data_items)}/{len(project.display_items)})"
        elif project.project_state == "missing":
            return f"(missing)"
        return str()

    def __str__(self) -> str:
        icon = "\N{GEAR}" if self.is_work else "\N{CARD FILE BOX}"
        return f"{icon} {self.display_item_controller.title} {self.__state_str}"
        # NOTE: {DIRECT HIT} is the target icon

    @property
    def is_enabled(self) -> bool:
        return self.project_reference.project and self.project_reference.project.project_state == "loaded"


class ProjectPanelFolderItem:

    def __init__(self, node: "TreeNode", indent: int, folder_name: str, folder_closed: bool, folder_key: str):
        self.node = node
        self.is_folder = True
        self.indent = indent
        self.folder_name = folder_name
        self.folder_closed = folder_closed
        self.folder_key = folder_key
        self.check_state = "unchecked"
        self.is_enabled = True
        self.project_reference = None

    def __str__(self) -> str:
        if sys.platform == "win32":
            triangle_right = "\N{BLACK MEDIUM RIGHT-POINTING TRIANGLE CENTRED}"
            triangle_down = "\N{BLACK MEDIUM DOWN-POINTING TRIANGLE CENTRED}"
        else:
            triangle_right = "\N{BLACK RIGHT-POINTING TRIANGLE}"
            triangle_down = "\N{BLACK DOWN-POINTING TRIANGLE}"
        if self.folder_closed:
            return f"{triangle_right} \N{FILE FOLDER} {self.folder_name} {len(self.node.children)} {len(self.node.data)}"
        else:
            return f"{triangle_down} \N{OPEN FILE FOLDER} {self.folder_name} {len(self.node.children)} {len(self.node.data)}"


class TreeNode:

    def __init__(self):
        self.children = dict()
        self.data = list()


class TreeModel:

    def __init__(self, document_controller: "DocumentController.DocumentController", closed_items: typing.Set[str]):
        self.document_controller = document_controller

        # cache
        self.__project_panel_items = None

        # define the top level list
        self.__root_node = TreeNode()

        # define events to make this a model
        self.property_changed_event = Event.Event()

        # define the closed items
        self.__closed_items = closed_items
        self.on_closed_items_changed = None

        def update_items(item: Observer.ItemValue) -> None:
            if self.__project_panel_items is not None:
                self.__update_project_panel_items(self.__project_panel_items)
                self.property_changed_event.fire("value")

        # build an observer that will call update_items whenever any of the project_references
        # or work or target project changes.
        oo = Observer.ObserverBuilder()
        oo.source(self.document_controller.document_model).prop("profile").tuple(
            oo.x.ordered_sequence_from_array("project_references").map(oo.x.prop("is_active")).collect_list(),
            oo.x.prop("work_project"),
            oo.x.prop("target_project")).action_fn(update_items)

        self.__profile_observer = oo.make_observable()

    def close(self) -> None:
        self.__profile_observer.close()
        self.__profile_observer = None
        self.__project_panel_items = None
        self.document_controller = None

    def update_project_references(self, project_references: typing.Sequence[Profile.ProjectReference]):
        # build hierarchy of nodes reflecting the project reference parts (strings).
        # this is called when the projects model changes.
        self.__project_panel_items = None
        root_node = TreeNode()
        for project_reference in project_references:
            parts = project_reference.project_reference_parts
            node = root_node
            for part in parts[:-1]:
                node = node.children.setdefault(part, TreeNode())
            node.data.append(project_reference)
        self.__root_node = root_node
        self.property_changed_event.fire("value")

    # recursively construct the project panel items
    def __construct_project_panel_items(self, key_path: typing.List[str], node: TreeNode, closed: bool, project_panel_items: typing.List, closed_items: typing.Set, encountered_items: typing.Set) -> None:
        # if the node has no data (no projects) and no children, do not display it; move down a level.
        if len(node.data) == 0 and len(node.children) == 1:
            # this node represents a directory that only has a sub directory.
            # start by extracting the key and only child.
            key, child = list(node.children.items())[0]
            # if not root (the key path is not empty), combine the child with the key (directory path).
            if len(key_path) > 0:
                new_key = key_path[:-1] + [key_path[-1] + (key if key_path[-1].endswith("/") else "/" + key)]
            # otherwise combine the child with the key (directory path).
            else:
                new_key = [key]
            # recurse
            self.__construct_project_panel_items(new_key, child, closed, project_panel_items, closed_items, encountered_items)
        else:
            # this node represents a directory that more than one of either sub directory or project.
            folder_key = "/".join(key_path)
            folder_closed = folder_key in self.__closed_items or closed
            if len(key_path) > 0:
                encountered_items.add(folder_key)
                if not closed:  # closed indicates whether the parent is closed
                    project_panel_items.append(ProjectPanelFolderItem(node, len(key_path), key_path[-1], folder_closed, folder_key))
            for key, child in node.children.items():
                self.__construct_project_panel_items(key_path + [key], child, folder_closed, project_panel_items, closed_items, encountered_items)
            for project_reference in typing.cast(typing.Sequence[Profile.ProjectReference], node.data):
                project_reference_parts = project_reference.project_reference_parts
                project_key = "/".join(key_path + [project_reference_parts[-1]]) if project_reference_parts else str(id(project_reference))
                encountered_items.add(project_key)
                if not folder_closed:

                    def handle_item_controller_title_changed(t: str) -> None:
                        self.property_changed_event.fire("value")

                    display_item_counter = ProjectCounterDisplayItem(project_reference)
                    display_item_counter.on_title_changed = handle_item_controller_title_changed
                    project_panel_items.append(ProjectPanelProjectItem(len(key_path) + 1, project_reference, display_item_counter))

    # define a function to determine the check state of a node.
    def __get_node_check_state(self, folder_node: TreeNode) -> str:
        check_state = None
        for project_reference in typing.cast(typing.Sequence[Profile.ProjectReference], folder_node.data):
            project_check_state = "checked" if project_reference.is_active else "unchecked"
            if not check_state:
                check_state = project_check_state
            elif project_check_state != check_state:
                return "partial"
        for key, child_node in folder_node.children.items():
            node_check_state = self.__get_node_check_state(child_node)
            if not check_state:
                check_state = node_check_state
            elif node_check_state != check_state:
                return "partial"
            elif node_check_state == "partial":
                return "partial"
        return check_state or "unchecked"

    def __update_project_panel_items(self, project_panel_items) -> None:
        # iterate through items and configure the check, target, and work states.
        for project_panel_item in project_panel_items:
            if isinstance(project_panel_item, ProjectPanelFolderItem):
                project_panel_item.check_state = self.__get_node_check_state(project_panel_item.node)
            elif isinstance(project_panel_item, ProjectPanelProjectItem):
                project_panel_item.is_target = project_panel_item.project_reference.project == self.document_controller.profile.target_project
                project_panel_item.is_work = project_panel_item.project_reference.project == self.document_controller.profile.work_project
                project_panel_item.check_state = "checked" if project_panel_item.project_reference.is_active else "unchecked"

    @property
    def value(self) -> typing.List:
        # build the value reflecting a compact version of the node hierarchy.
        # nodes with only one child are combined with that child.
        # building the project panel is expensive; so cache it.

        if not self.__project_panel_items:
            project_panel_items = list()
            encountered_items = set()
            self.__construct_project_panel_items(list(), self.__root_node, False, project_panel_items, self.__closed_items, encountered_items)
            self.__update_project_panel_items(project_panel_items)
            self.__closed_items = self.__closed_items.intersection(encountered_items)
            self.__project_panel_items = project_panel_items

        return self.__project_panel_items

    def toggle_folder(self, folder_key: str) -> None:
        if not folder_key in self.__closed_items:
            self.__closed_items.add(folder_key)
        else:
            self.__closed_items.remove(folder_key)
        self.__project_panel_items = None
        self.property_changed_event.fire("value")
        if self.on_closed_items_changed:
            self.on_closed_items_changed(self.__closed_items)

    def toggle_folder_active(self, folder_node: TreeNode) -> None:

        # define a function to recursive set projects/folders to active
        def set_folder_node_active(folder_node: TreeNode, active: bool) -> None:
            for project_reference in typing.cast(typing.Sequence[Profile.ProjectReference], folder_node.data):
                self.document_controller.profile.set_project_reference_active(project_reference, active)
            for key, child_node in folder_node.children.items():
                set_folder_node_active(child_node, active)

        if self.__get_node_check_state(folder_node) != "checked":
            set_folder_node_active(folder_node, True)
        else:
            set_folder_node_active(folder_node, False)

    def toggle_project_reference_active(self, project_reference: Profile.ProjectReference) -> None:
        self.document_controller.profile.toggle_project_reference_active(project_reference)


class ProjectTreeCanvasItemDelegate(Widgets.ListCanvasItemDelegate):

    def __init__(self, document_controller: "DocumentController.DocumentController", tree_model: TreeModel):
        super().__init__()
        self.__document_controller = document_controller
        self.__tree_model = tree_model
        get_font_metrics_fn = document_controller.ui.get_font_metrics
        self.__folder_indent = get_font_metrics_fn("12px", "\N{BLACK DOWN-POINTING TRIANGLE} ").width
        self.__project_indent = get_font_metrics_fn("12px", "\N{OPEN FILE FOLDER} ").width

    def mouse_pressed_in_item(self, mouse_index: int, pos: Geometry.IntPoint, modifiers) -> bool:
        display_item = self.__tree_model.value[mouse_index]
        indent = self.__calculate_indent(display_item.indent, 0)
        if display_item.is_folder and indent < pos.x < indent + self.__folder_indent:
            self.__tree_model.toggle_folder(display_item.folder_key)
            return True
        indent0 = self.__calculate_indent(0, 0)
        if indent0 < pos.x < indent0 + 12:
            if isinstance(display_item, ProjectPanelFolderItem):
                self.__tree_model.toggle_folder_active(display_item.node)
            elif isinstance(display_item, ProjectPanelProjectItem):
                self.__tree_model.toggle_project_reference_active(display_item.project_reference)
            return True
        return False

    def paint_item(self, drawing_context, display_item, rect, is_selected):
        item_string = str(display_item)
        with drawing_context.saver():
            drawing_context.fill_style = "#000" if display_item.is_enabled else "#888"
            drawing_context.font = "12px bold" if not display_item.is_folder and display_item.is_target else "12px"
            drawing_context.text_align = 'left'
            drawing_context.text_baseline = 'bottom'
            # drawing_context.fill_text("\N{BALLOT BOX}", rect[0][1] + 4, rect[0][0] + 20 - 4)
            extra_indent = self.__project_indent if not display_item.is_folder else 0
            drawing_context.fill_text(item_string, rect[0][1] + self.__calculate_indent(display_item.indent, extra_indent), rect[0][0] + 20 - 4)
            drawing_context.begin_path()
            drawing_context.move_to(rect[0][1] + 4, rect[0][0] + 20 - 4)
            drawing_context.line_to(rect[0][1] + 4 + 11, rect[0][0] + 20 - 4)
            drawing_context.line_to(rect[0][1] + 4 + 11, rect[0][0] + 20 - 4 - 11)
            drawing_context.line_to(rect[0][1] + 4, rect[0][0] + 20 - 4 - 11)
            drawing_context.close_path()
            if display_item.check_state == "partial":
                drawing_context.move_to(rect[0][1] + 4 + 3, rect[0][0] + 20 - 4 - 6)
                drawing_context.line_to(rect[0][1] + 4 + 8, rect[0][0] + 20 - 4 - 6)
            if display_item.check_state == "checked":
                drawing_context.move_to(rect[0][1] + 4 + 8, rect[0][0] + 20 - 4 - 8)
                drawing_context.line_to(rect[0][1] + 4 + 3, rect[0][0] + 20 - 4 - 3)
                drawing_context.move_to(rect[0][1] + 4 + 8, rect[0][0] + 20 - 4 - 3)
                drawing_context.line_to(rect[0][1] + 4 + 3, rect[0][0] + 20 - 4 - 8)
            drawing_context.stroke_style = "#444"
            drawing_context.stroke()

    def item_can_drop_mime_data(self, mime_data, action: str, drop_index: int) -> bool:
        display_item = self.__tree_model.value[drop_index]
        if display_item.project and display_item.is_enabled:
            display_items = MimeTypes.mime_data_get_display_items(mime_data, self.__document_controller.document_model)
            if display_items:
                return True
            return mime_data.has_file_paths
        return False

    def item_drop_mime_data(self, mime_data, action: str, drop_index: int) -> str:
        display_item = self.__tree_model.value[drop_index]
        if display_item.project and display_item.is_enabled:
            document_controller = display_item.display_item_controller.document_controller
            document_controller._register_ui_activity()
            if mime_data.has_file_paths:
                file_paths = [pathlib.Path(file_path) for file_path in mime_data.file_paths]
                document_controller.receive_project_files(file_paths, project=display_item.project)
                return "copy"
        return "ignore"

    def item_tool_tip(self, index: int) -> typing.Optional[str]:
        display_item = self.__tree_model.value[index]
        if isinstance(display_item, ProjectPanelProjectItem):
            return str(display_item.project_reference.project.storage_system_path if display_item.project_reference.project else _("Missing"))
        return None

    def context_menu_event(self, index: int, x: int, y: int, gx: int, gy: int) -> bool:
        display_item = self.__tree_model.value[index]
        menu = self.__document_controller.create_context_menu()
        if isinstance(display_item, ProjectPanelProjectItem) and display_item.project_reference.project:
            menu.add_menu_item(_(f"Open Project Location"), functools.partial(reveal_project, display_item.project_reference.project.storage_system_path))
        elif isinstance(display_item, ProjectPanelFolderItem):
            menu.add_menu_item(_(f"Open Folder Location"), functools.partial(open_location, pathlib.Path(display_item.folder_key)))
        menu.popup(gx, gy)
        return True

    def __calculate_indent(self, display_item_indent, extra_indent):
        return 4 + display_item_indent * self.__folder_indent + extra_indent


class ProjectTreeWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui, document_controller):
        super().__init__(ui.create_column_widget())

        column = self.content_widget

        document_model = document_controller.document_model

        self._tree_model = TreeModel(document_controller, set(document_controller.profile.closed_items))

        def closed_items_changed(closed_items: typing.Set[str]):
            document_controller.profile.closed_items = list(closed_items)

        self._tree_model.on_closed_items_changed = closed_items_changed

        self._tree_selection = Selection.IndexedSelection(Selection.Style.multiple)

        projects_list_widget = Widgets.ListWidget(ui, ProjectTreeCanvasItemDelegate(document_controller, self._tree_model), selection=self._tree_selection, v_scroll_enabled=False, v_auto_resize=True)
        projects_list_widget.wants_drag_events = True
        projects_list_widget.bind_items(Binding.PropertyBinding(self._tree_model, "value"))

        projects_section = Widgets.SectionWidget(ui, _("Projects"), projects_list_widget)
        projects_section.expanded = True

        column.add(projects_section)

        # configure the selection objects to track each other

        blocked = False

        def tree_selection_changed() -> None:
            nonlocal blocked
            if not blocked:
                blocked = True
                try:
                    selected_project_references = list()
                    for index in self._tree_selection.indexes:
                        tree_item = self._tree_model.value[index]
                        if hasattr(tree_item, "project_reference") and tree_item.project_reference:
                            selected_project_references.append(tree_item.project_reference)
                    document_controller.selected_project_references_model.value = selected_project_references
                finally:
                    blocked = False

        self.__tree_selection_changed_event_listener = self._tree_selection.changed_event.listen(tree_selection_changed)

        def selected_project_references_model_changed(key: str) -> None:
            nonlocal blocked
            if not blocked:
                blocked = True
                try:
                    selected_project_references = document_controller.selected_project_references
                    indexes = set()
                    for index, tree_item in enumerate(self._tree_model.value):
                        if hasattr(tree_item, "project_reference") and tree_item.project_reference:
                            if tree_item.project_reference in selected_project_references:
                                indexes.add(index)
                    self._tree_selection.set_multiple(indexes)
                finally:
                    blocked = False

        self.__selected_project_references_changed_listener = document_controller.selected_project_references_model.property_changed_event.listen(selected_project_references_model_changed)

        # configure an observer for watching for project references changes.
        # this serves as the master updater for changes. move to document controller?

        def project_references_changed(item: Observer.ItemValue) -> None:
            # update the tree model.
            project_references = typing.cast(typing.Sequence[Profile.ProjectReference], item)
            self._tree_model.update_project_references(project_references)

        oo = Observer.ObserverBuilder()
        oo.source(document_controller.document_model).prop("profile").ordered_sequence_from_array("project_references").collect_list().action_fn(project_references_changed)
        self.__projects_model_observer = oo.make_observable()

        selected_project_references_model_changed(str())

    def close(self):
        self.__selected_project_references_changed_listener.close()
        self.__selected_project_references_changed_listener = None
        self.__tree_selection_changed_event_listener.close()
        self.__tree_selection_changed_event_listener = None
        self._tree_model.on_closed_items_changed = None
        self.__projects_model_observer.close()
        self.__projects_model_observer = None
        super().close()


class ProjectListCanvasItemDelegate(Widgets.ListCanvasItemDelegate):

    def __init__(self, document_controller: "DocumentController.DocumentController", project_selection: Selection.IndexedSelection):
        super().__init__()
        self.__document_controller = document_controller
        self.__profile = document_controller.profile
        self.__project_selection = project_selection

    def close(self):
        self.__document_controller = None
        self.__profile = None
        self.__project_selection = None

    def paint_item(self, drawing_context, display_item, rect, is_selected):
        # target project is bold
        # work project is italic
        # unloaded projects are dimmed with reason in parenthesis
        # reasons can be missing, unloaded, or needs upgrade

        if isinstance(display_item, ProjectCounterDisplayItem):
            is_active = display_item.project_reference.is_active
            is_target_project = self.__profile.target_project_reference == display_item.project_reference
            is_work_project = self.__profile.work_project_reference == display_item.project_reference
            title = "\N{CARD FILE BOX} " + display_item.title
            if display_item.project_reference.project:
                if display_item.project_reference.project.project_state == "missing":
                    is_active = False
                    title += " (" + _("missing").upper() + ")"
                elif display_item.project_reference.project.project_state == "needs_upgrade":
                    is_active = False
                    title += " (" + _("needs upgrade").upper() + ")"
            else:
                is_active = False
                title += " (" + _("unloaded").upper() + ")"
        else:
            is_active = True
            is_target_project = False
            is_work_project = False
            title = "\N{CARD FILE BOX} " + display_item.title

        with drawing_context.saver():
            drawing_context.fill_style = "#000" if is_active else "#888"
            font = "12px"
            if is_target_project:
                font += " bold"
            if is_work_project:
                font += " italic"
            drawing_context.font = font
            drawing_context.text_align = 'left'
            drawing_context.text_baseline = 'bottom'
            drawing_context.fill_text(title, rect[0][1] + 4, rect[0][0] + 20 - 4)

    def item_can_drop_mime_data(self, mime_data, action: str, drop_index: int) -> bool:
        display_item = self.items[drop_index]
        if isinstance(display_item, ProjectCounterDisplayItem):
            if display_item.project_reference.is_active and display_item.project_reference.project:
                display_items = MimeTypes.mime_data_get_display_items(mime_data, self.__document_controller.document_model)
                if display_items:
                    return True
                return mime_data.has_file_paths
        return False

    def item_drop_mime_data(self, mime_data, action: str, drop_index: int) -> str:
        display_item = self.items[drop_index]
        if isinstance(display_item, ProjectCounterDisplayItem):
            display_item = self.items[drop_index]
            if display_item.project_reference.is_active and display_item.project_reference.project:
                document_controller = self.__document_controller
                document_controller._register_ui_activity()
                display_items = MimeTypes.mime_data_get_display_items(mime_data, document_controller.document_model)
                if display_items:
                    document_controller.move_items(display_items, display_item.project_reference.project)
                    return "move"
                if mime_data.has_file_paths:
                    file_paths = [pathlib.Path(file_path) for file_path in mime_data.file_paths]
                    document_controller.receive_project_files(file_paths, display_item.project_reference.project)
                    return "copy"
        return "ignore"

    def item_tool_tip(self, index: int) -> typing.Optional[str]:
        display_item = self.items[index]
        if isinstance(display_item, ProjectCounterDisplayItem):
            return str(display_item.project_reference.project.storage_system_path if display_item.project_reference.project else _("Missing"))
        return None

    def context_menu_event(self, index: int, x: int, y: int, gx: int, gy: int) -> bool:
        display_item = self.items[index]
        menu = self.__document_controller.create_context_menu()
        project_reference = display_item.project_reference
        if isinstance(project_reference, Profile.IndexProjectReference) and project_reference.project:
            menu.add_menu_item(_(f"Open Project Location"), functools.partial(reveal_project, project_reference.project.storage_system_path))
        elif isinstance(project_reference, Profile.FolderProjectReference):
            menu.add_menu_item(_(f"Open Folder Location"), functools.partial(open_location, project_reference.project_folder_path))
        menu.popup(gx, gy)
        return True


class ProjectsWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui: UserInterface.UserInterface, document_controller: "DocumentController.DocumentController"):
        super().__init__(ui.create_column_widget())

        self.__document_controller = document_controller

        column = self.content_widget

        self.__document_model_counter = DocumentModelCounterDisplayItem(document_controller.document_model)

        self.__project_counters : typing.List[ProjectCounterDisplayItem] = list()

        project_selection = Selection.IndexedSelection(Selection.Style.single_or_none)

        self.__projects_list_delegate = ProjectListCanvasItemDelegate(document_controller, project_selection)
        self.__projects_list_widget = Widgets.ListWidget(ui, self.__projects_list_delegate, selection=project_selection, v_scroll_enabled=False, v_auto_resize=True)
        self.__projects_list_widget.wants_drag_events = True

        self.__projects_observer = None
        self.__projects_filtered = True

        self.__set_filtering(document_controller)

        projects_column = ui.create_column_widget()
        projects_column.add(self.__projects_list_widget)

        projects_section = Widgets.SectionWidget(ui, _("Projects"), projects_column)
        projects_section.expanded = True

        filter_dark_icon_data = CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/filter2_icon_20.png"))
        filter_light_icon_data = CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/filter3_icon_20.png"))

        def toggle_filtering() -> None:
            self.__projects_filtered = not self.__projects_filtered
            self.__set_filtering(document_controller)
            bitmap_button_canvas_item.set_rgba_bitmap_data(filter_dark_icon_data if self.__projects_filtered else filter_light_icon_data)

        filter_button_widget = ui.create_canvas_widget(properties={"height": 20, "width": 20})
        bitmap_button_canvas_item = CanvasItem.BitmapButtonCanvasItem(filter_dark_icon_data)
        filter_button_widget.canvas_item.add_canvas_item(bitmap_button_canvas_item)
        bitmap_button_canvas_item.on_button_clicked = toggle_filtering

        gear_button_widget = ui.create_canvas_widget(properties={"height": 20, "width": 20})
        gear_button_canvas_item = CanvasItem.BitmapButtonCanvasItem(CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/gear_icon_20.png")))
        gear_button_widget.canvas_item.add_canvas_item(gear_button_canvas_item)
        gear_button_canvas_item.on_button_clicked = lambda: document_controller.perform_action("window.open_project_dialog")

        projects_section.section_title_row.add(filter_button_widget)
        projects_section.section_title_row.add_spacing(4)
        projects_section.section_title_row.add(gear_button_widget)
        projects_section.section_title_row.add_spacing(4)

        # filter_button.on_clicked = lambda: print("CLICKED")

        column.add(projects_section)

        blocked = False

        def selection_changed() -> None:
            nonlocal blocked
            if not blocked:
                blocked = True
                try:
                    selected_project_references = list()
                    for index in project_selection.indexes:
                        if index >= 1:
                            project_counter = self.__project_counters[index - 1]
                            selected_project_references.append(project_counter.project_reference)
                        document_controller.selected_project_references_model.value = selected_project_references
                finally:
                    blocked = False

        self.__selection_changed_event_listener = project_selection.changed_event.listen(selection_changed)

        def selected_project_references_model_changed(key: str) -> None:
            nonlocal blocked
            if not blocked:
                blocked = True
                try:
                    selected_project_references = document_controller.selected_project_references
                    if len(selected_project_references) == 1:
                        selected_project_reference = selected_project_references[0]
                        project_index = None
                        for index, project_counter in enumerate(self.__project_counters):
                            if project_counter.project_reference == selected_project_reference:
                                project_index = index + 1
                        if project_index is not None:
                            project_selection.set(project_index)
                        else:
                            project_selection.set(0)
                    else:
                        project_selection.set(0)
                finally:
                    blocked = False

        self.__selected_project_references_changed_listener = document_controller.selected_project_references_model.property_changed_event.listen(selected_project_references_model_changed)

        selected_project_references_model_changed(str())

        # for testing
        self._project_selection = project_selection

    def __set_filtering(self, document_controller: "DocumentController.DocumentController") -> None:
        if self.__projects_observer:
            self.__projects_observer.close()
        # build an observer for the project property of project references and call projects changed upon changes.
        # ideally we could pass project references having non-None projects, but there is currently no way to
        # rebuild the project references when the state of the project property changes.
        oo = Observer.ObserverBuilder()
        oo.source(document_controller.document_model).prop("profile").ordered_sequence_from_array(
            "project_references").map(oo.x.prop("project")).collect_list().action_fn(self.__projects_changed)
        self.__projects_observer = oo.make_observable()

    def close(self):
        self.__projects_list_delegate.close()
        self.__projects_list_delegate = None
        self.__selected_project_references_changed_listener.close()
        self.__selected_project_references_changed_listener = None
        self.__selection_changed_event_listener.close()
        self.__selection_changed_event_listener = None
        self.__projects_observer.close()
        self.__projects_observer = None
        for project_counter in self.__project_counters:
            project_counter.close()
        self.__project_counters.clear()
        self.__document_model_counter.close()
        self.__document_model_counter = None
        self.__document_controller = None
        super().close()

    def __project_counters_changed(self) -> None:
        self.__projects_list_widget.items = [self.__document_model_counter] + self.__project_counters

    def __projects_changed(self, item: Observer.ItemValue) -> None:
        project_references = [pr for pr in self.__document_controller.document_model.profile.project_references if pr.project or not self.__projects_filtered]
        for project_counter in self.__project_counters:
            project_counter.close()
        self.__project_counters.clear()
        for project_reference in project_references:
            project_counter = ProjectCounterDisplayItem(project_reference)
            project_counter.on_title_changed = lambda t: self.__project_counters_changed()
            self.__project_counters.append(project_counter)
        self.__project_counters_changed()


class CollectionListCanvasItemDelegate(Widgets.ListCanvasItemDelegate):

    def __init__(self, collection_selection: Selection.IndexedSelection):
        super().__init__()
        self.__collection_selection = collection_selection

    def close(self):
        pass

    def paint_item(self, drawing_context, display_item, rect, is_selected):
        is_smart_collection = display_item.is_smart_collection if display_item else False
        title = ("\N{LEDGER} " if is_smart_collection else "\N{NOTEBOOK} ") + (display_item.title if display_item else str())

        with drawing_context.saver():
            drawing_context.fill_style = "#000"
            drawing_context.font = "12px italic" if is_smart_collection else "12px"
            drawing_context.text_align = 'left'
            drawing_context.text_baseline = 'bottom'
            drawing_context.fill_text(title, rect[0][1] + 4, rect[0][0] + 20 - 4)

    def item_can_drop_mime_data(self, mime_data, action: str, drop_index: int) -> bool:
        list_display_item = self.items[drop_index]
        is_smart_collection = list_display_item.is_smart_collection if list_display_item else False
        display_items = MimeTypes.mime_data_get_display_items(mime_data, list_display_item.document_model)
        if list_display_item and not is_smart_collection and display_items:
            # if the display item exists in this document, then it is copied to the
            # target group. if it doesn't exist in this document, then it is coming
            # from another document and can't be handled here.
            return True
        return False

    def item_drop_mime_data(self, mime_data, action: str, drop_index: int) -> str:
        list_display_item = self.items[drop_index]
        is_smart_collection = list_display_item.is_smart_collection if list_display_item else False
        display_items = MimeTypes.mime_data_get_display_items(mime_data, list_display_item.document_model)
        if list_display_item and not is_smart_collection and display_items:
            # if the display item exists in this document, then it is copied to the
            # target group. if it doesn't exist in this document, then it is coming
            # from another document and can't be handled here.
            document_controller = list_display_item.document_controller
            data_group = list_display_item.data_group
            command = document_controller.create_insert_data_group_display_items_command(data_group, len(data_group.display_items), display_items)
            command.perform()
            document_controller.push_undo_command(command)
            return "copy"
        return "ignore"

    def delete_pressed(self) -> None:
        index = self.__collection_selection.current_index
        list_display_item = self.items[index] if index is not None else None
        data_group = list_display_item.data_group
        if data_group:
            list_display_item.document_controller.remove_data_group_from_container(data_group, list_display_item.document_controller.document_model._project)


class CollectionsWidget(Widgets.CompositeWidgetBase):

    def __init__(self, ui, document_controller):
        super().__init__(ui.create_column_widget())

        column = self.content_widget

        document_model = document_controller.document_model

        all_items_controller = CollectionDisplayItemCounter(_("All"), None, "all", document_controller)
        persistent_items_controller = CollectionDisplayItemCounter(_("Persistent"), None, "persistent", document_controller)
        live_items_controller = CollectionDisplayItemCounter(_("Live"), None, "temporary", document_controller)
        latest_items_controller = CollectionDisplayItemCounter(_("Latest Session"), None, "latest-session", document_controller)

        self.__item_controllers = [
            all_items_controller,
            persistent_items_controller,
            live_items_controller,
            latest_items_controller
        ]

        self.__data_group_controllers = list()

        collection_selection = Selection.IndexedSelection(Selection.Style.single_or_none)

        collections_list_widget = Widgets.ListWidget(ui, CollectionListCanvasItemDelegate(collection_selection), selection=collection_selection, v_scroll_enabled=False, v_auto_resize=True)
        collections_list_widget.wants_drag_events = True

        def filter_changed(data_group: DataGroup.DataGroup, filter_id: str) -> None:
            if data_group:
                for index, controller in enumerate(collections_list_widget.items):
                    if data_group == controller.data_group:
                        collection_selection.set(index)
                        break
            else:
                if filter_id == "latest-session":
                    collection_selection.set(3)
                elif filter_id == "temporary":
                    collection_selection.set(2)
                elif filter_id == "persistent":
                    collection_selection.set(1)
                else:
                    collection_selection.set(0)

        self.__filter_changed_event_listener = document_controller.filter_changed_event.listen(filter_changed)

        def collections_changed(t: str) -> None:
            collections_list_widget.items = [
                all_items_controller,
                persistent_items_controller,
                live_items_controller,
                latest_items_controller,
            ] + self.__data_group_controllers

        all_items_controller.on_title_changed = collections_changed
        persistent_items_controller.on_title_changed = collections_changed
        live_items_controller.on_title_changed = collections_changed
        latest_items_controller.on_title_changed = collections_changed

        def document_model_item_inserted(key: str, value, before_index: int) -> None:
            if key == "data_groups":
                data_group = value
                controller = CollectionDisplayItemCounter(data_group.title, data_group, None, document_controller)
                self.__data_group_controllers.insert(before_index, controller)
                controller.on_title_changed = collections_changed
                collections_changed(str())

        def document_model_item_removed(key: str, value, index: int) -> None:
            if key == "data_groups":
                controller = self.__data_group_controllers.pop(index)
                controller.close()
                collections_changed(str())

        self.__document_model_item_inserted_listener = document_model.item_inserted_event.listen(document_model_item_inserted)
        self.__document_model_item_removed_listener = document_model.item_removed_event.listen(document_model_item_removed)

        filter_changed(*document_controller.get_data_group_and_filter_id())

        for index, data_group in enumerate(document_model.data_groups):
            document_model_item_inserted("data_groups", data_group, index)

        collections_changed(str())

        def collections_selection_changed(indexes: typing.Set) -> None:
            if len(indexes) == 0:
                controller = collections_list_widget.items[0]
                document_controller.set_filter(controller.filter_id)
            elif len(indexes) == 1:
                controller = collections_list_widget.items[list(indexes)[0]]
                if controller.is_smart_collection:
                    document_controller.set_filter(controller.filter_id)
                    document_controller.set_data_group(None)
                else:
                    document_controller.set_filter(None)
                    document_controller.set_data_group(controller.data_group)

        collections_list_widget.on_selection_changed = collections_selection_changed

        collections_column = ui.create_column_widget()
        collections_column.add(collections_list_widget)

        collections_section = Widgets.SectionWidget(ui, _("Collections"), collections_column)
        collections_section.expanded = True

        column.add(collections_section)
        column.add_stretch()

        # for testing
        self._collection_selection = collection_selection

    def close(self):
        for controller in self.__data_group_controllers:
            controller.close()
        self.__data_group_controllers.clear()
        for item_controller in self.__item_controllers:
            item_controller.close()
        self.__item_controllers.clear()
        self.__filter_changed_event_listener.close()
        self.__filter_changed_event_listener = None
        self.__document_model_item_inserted_listener.close()
        self.__document_model_item_inserted_listener = None
        self.__document_model_item_removed_listener.close()
        self.__document_model_item_removed_listener = None
        super().close()


class ProjectPanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super().__init__(document_controller, panel_id, _("Projects"))

        ui = document_controller.ui

        self._projects_section = ProjectsWidget(ui, document_controller)
        self._collections_section = CollectionsWidget(ui, document_controller)

        column = ui.create_column_widget()
        column.add(self._projects_section)
        column.add(self._collections_section)
        column.add_stretch()

        scroll_area = ui.create_scroll_area_widget(properties=properties)
        scroll_area.set_scrollbar_policies("off", "needed")
        scroll_area.content = column

        self.widget = scroll_area

    @property
    def _collection_selection(self) -> Selection.IndexedSelection:
        return self._collections_section._collection_selection

    @property
    def _projects_selection(self) -> Selection.IndexedSelection:
        return self._projects_section._project_selection


class ProjectDialog(Dialog.ActionDialog):

    def __init__(self, document_controller):
        ui = document_controller.ui
        super().__init__(ui, _("Project Manager"), parent_window=document_controller, persistent_id="ProjectsDialog")

        self._create_menus()

        projects_section = ProjectTreeWidget(ui, document_controller)

        column = ui.create_column_widget()
        column.add(projects_section)
        column.add_stretch()

        scroll_area = ui.create_scroll_area_widget()
        scroll_area.set_scrollbar_policies("off", "needed")
        scroll_area.content = column

        column = self.content
        column.add_spacing(6)
        column.add(scroll_area)
